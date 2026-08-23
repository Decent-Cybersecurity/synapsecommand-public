"""ASTERIX Category 021 — ADS-B target reports in, CDM out; CDM out to CAT021 data blocks.

Adapter #6, and the fourth bidirectional one. It implements the CAT021 row set in
FORMAT_COVERAGE.md row by row; that table is this module's specification, written and reviewed
before this file existed, and a test resolves every CDM path in it against the models so the
two cannot drift.

WHAT EACH DIRECTION IS
----------------------
INGEST  one ASTERIX **data block** — `CAT | LEN | FSPEC + items | ...` — becomes an Entity + an
        Event **per record**. A block legitimately holds several records, they may name several
        aircraft, and each is a target report in its own right.

EGRESS  one Entity, or one Track, becomes the data block that restates it. A Track becomes ONE
        block of N records, which is the shape this format has for a history and the shape
        1090ES did not have.

THE RELATIONSHIP TO adsb.py, WHICH IS NOT "A SECOND ADS-B ADAPTER"
------------------------------------------------------------------
Same underlying data, different wire format, and one hop of processing in between. CAT021 is
what a ground station emits after it has received 1090ES broadcasts, CPR-decoded the position,
validated it, correlated the type codes into one target report and added its own quality
assessment. Three of the four hard problems in `adsb.py` are therefore simply gone — the
position arrives decoded, the frame types arrive merged, and the format states times — and they
are replaced by different ones:

1. **A time with no date.** Seven time items, not one of them carrying a calendar date. See
   THE REFERENCE DATE below.
2. **A quality vocabulary whose meaning depends on another item.** I021/090's primary subfield
   is literally "NUCr or NACv" and "NUCp or NIC", decided by the MOPS version in I021/210 —
   which is *optional*. A record can carry a quality indicator whose quantity is undetermined.
3. **A ground station that has already made judgements.** Range checks, CPR validation, an
   independent position check, a black-list lookup. This adapter carries them and re-decides
   none of them — see THE RANGE-CHECK ROW.

THE REFERENCE DATE, AND WHY MIDNIGHT ROLLOVER FALLS OUT
--------------------------------------------------------
Every CAT021 time is "elapsed time since last midnight, expressed as UTC" — a time of day, at
1/128 s, and never a date. Something has to supply the date and there are only two candidates:
the payload, which does not carry one, or us.

So the date comes from `self.now()`, the injected clock, exactly as `received_at` does and never
from `datetime.now()`. The instant chosen is the one bearing the stated time of day **nearest
the receipt instant**, considering the receipt date, the day before and the day after. That one
rule handles both rollover directions without a special case:

    stated 23:59:58.500, received 00:00:01.100 next day  -> the PREVIOUS day  (not 24 h late)
    stated 00:00:00.900, received 23:59:59.700           -> the NEXT day      (a fast GS clock)

It is the AIS construction generalised. AIS states a second-of-minute and no date and resolves
it against the receipt minute; this states a time of day and resolves it against the receipt
date. `payload.observed_at_basis` names the item, the date's source and any rollover applied,
because a decision about which day a contact was seen on is not one to leave invisible.

**A value at or beyond 86 400 s is a REFUSAL, not a modulo.** Twenty-four bits at 1/128 s reach
131 071.99 s, so the field can express times of day that do not exist. The counter resets at
midnight, so such a value is corrupt or non-conforming; taking it modulo 86 400 would move a
contact by hours and leave every other check passing.

THERE IS NO CRC HERE, AND WHAT REPLACES IT
-------------------------------------------
The strongest gate in `adsb.py` is the 24-bit parity: a frame that fails is refused, never
best-effort decoded. **ASTERIX has no checksum at any level** — not on the block, not on a
record, not on an item. Whatever integrity the link has belongs to the transport below it.

So the gate is structural, and deliberately strict for the same reason the CRC one is: a length
or an FSPEC that does not add up is the only evidence available that a record was corrupted.
`LEN` must match the buffer; the records must tile it exactly; every FSPEC bit must name a
defined FRN; every variable item must terminate inside the record; every compound subfield must
be present; and the four items the specification says shall be in every record — I021/010,
I021/040, I021/080, I021/090 — must be there.

That is weaker than a CRC and the difference is named rather than smoothed over: a single bit
flipped inside a fixed-length field satisfies every structural check and reaches the CDM as a
measurement. `attributes.integrity_basis` says so on every object, so a consumer comparing a
CAT021 contact against a 1090ES one can see which of the two was checked and which was parsed.

WHY THE ROUND TRIP IS BYTE-EXACT AND TRANSFORMS IS EMPTY
--------------------------------------------------------
Three things would have prevented a byte-exact round trip, and all three are handled by parking
rather than by an exemption:

    I021/074, I021/076   2^-30 s, and a CDM Timestamp renders three decimal places
    every time item      1/128 s = 7.8125 ms, not a whole number of milliseconds
    spare and unused     s4.3 forbids relying on their settings and only RECOMMENDS zeroing

So the wire octets of every item are parked verbatim at `attributes.cat021_items` and egress
re-emits from there; the canonical fields are a derived, one-way view beside them. That is
Legion's ECEF argument and its verbatim-timestamp argument wearing one hat.

It also has a consequence worth stating outright: **`TRANSFORMS` is empty, and that is a claim
rather than an oversight.** A declared transform is an exemption from the never-drop check — a
hole with a reason attached — and this adapter needs none, because every source value is present
in the output verbatim as well as converted. `lossless.unrepresented()` therefore runs at full
strength over every fixture with nothing excused. See the class docstring.

THE RANGE-CHECK ROW, WHERE THE SPECIFICATION ASKS US TO FILTER
---------------------------------------------------------------
I021/040's second extension carries `RCF`, range check failed, and the specification's own note
says: "For operational users such a target will be suppressed." An adapter may not filter — that
is rule 2 of the `Adapter` contract, and a decision made inside a translator is invisible in the
CDM output and absent from the audit trail. So a range-check-failed target is translated in
full, the flag is parked, and the suppression decision belongs to a consumer where somebody can
see it being made. The specification is describing what a surveillance system should do; this is
a translator inside one.

WHY NOTHING HERE IS AN IDENTIFICATION — INCLUDING AN AUTHENTICATED ONE
-----------------------------------------------------------------------
`affiliation` is UNKNOWN on every record. The base reason is `adsb.py`'s: everything in a target
report except the ground station's own flags originated as an unauthenticated cooperative
broadcast.

The Reserved Expansion Field makes that a decision rather than an inherited default. `MES`
subfield #1 carries `ID` and `DA` — "authenticated Mode 5 ID reply/report" and "authenticated
Mode 5 Data reply or Report" — which is the first cryptographically attested identity statement
any source in this repository carries, and in IFF doctrine an authenticated Mode 5 reply is what
"friend" means. It is still not read as FRIENDLY: that is an adjudication, `Affiliation`'s own
docstring puts adjudications outside an adapter, and over-claiming FRIENDLY from a translator is
the fratricide-adjacent direction. The bits are parked in full and
`attributes.affiliation_basis` records that an attested indication was present and deliberately
not read. Gap 2 carries the consequence: the CDM cannot say "attested, not adjudicated".

THE FULL REF IS IN SCOPE
------------------------
Not for completeness. The core specification RELOCATES two things into it: a Version 3
aircraft's Priority Status (I021/200's PS is superseded by `REF/STA/PS3`), and the whole surface
ground vector (I021/160 is the AIRBORNE one; the surface one is `REF/SGV`). An adapter without
the REF translates a Version 3 aircraft in distress as an ordinary track update and leaves every
surface target motionless.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Sequence

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

SYSTEM = "ASTERIX_CAT021"

#: The source id system for a 24-bit ICAO aircraft address. NOT this adapter's own name, and
#: not "CAT021": the address is an ICAO Annex 10 aircraft address, and `adsb.py` files the same
#: string under the same name — which is what makes a CAT021 contact and a 1090ES contact of one
#: airframe derive the SAME entity_id without the two adapters coordinating. That agreement is
#: the single largest reason this adapter is worth having.
ICAO_SYSTEM = "ICAO24"

#: I021/040's ATP says the address is NOT an ICAO24 address — duplicate, surface vehicle,
#: anonymous or reserved. Still the only identifier the record carries, so still the source id,
#: under a system name that cannot collide with a real airframe's. `adsb.py`'s DF18 CF 1/5
#: decision, reached from a different field.
NONICAO_SYSTEM = "ADSB_NONICAO"

# --------------------------------------------------------------------- the data block

#: One octet, and this adapter speaks exactly one category. A CAT062 or CAT048 block decoded
#: against the CAT021 UAP yields a plausible wrong aircraft rather than an error.
CATEGORY = 21

#: CAT (1) + LEN (2). LEN counts itself and the CAT octet.
BLOCK_HEADER_OCTETS = 3

#: 1/128 s. The LSB of every CAT021 time-of-day item except the two high-precision ones.
TIME_LSB_SECONDS = 1.0 / 128.0

#: 2^-30 s ~ 0.93 ns — I021/074 and I021/076. Far finer than a CDM Timestamp's milliseconds,
#: which is why those items are parked raw and never recomputed from `observed_at`.
HIGH_PRECISION_LSB_SECONDS = 2.0 ** -30

SECONDS_PER_DAY = 86400

#: I021/130: 24-bit two's complement, LSB 180/2^23 degrees, at least 2.4 m.
LSB_130_DEGREES = 180.0 / (2 ** 23)

#: I021/131: 32-bit two's complement, LSB 180/2^30 degrees, at least 2 cm.
LSB_131_DEGREES = 180.0 / (2 ** 30)

#: I021/140 geometric height, LSB 6.25 ft, and the marker that is not a height.
GEOMETRIC_HEIGHT_LSB_FEET = 6.25
GEOMETRIC_HEIGHT_GREATER_THAN = 0x7FFF
FEET_TO_METRES = 0.3048

#: I021/160: ground speed LSB 2^-14 NM/s, track angle LSB 360/2^16 degrees from TRUE north.
GROUND_SPEED_LSB_NM_PER_S = 2.0 ** -14
METRES_PER_NAUTICAL_MILE = 1852.0
ANGLE_LSB_DEGREES = 360.0 / (2 ** 16)

#: I021/155 and I021/157: 6.25 ft/min, two's complement.
VERTICAL_RATE_LSB_FEET_PER_MINUTE = 6.25

#: I021/165 track angle rate, LSB 1/32 deg/s, and its "or above" ceiling.
TRACK_ANGLE_RATE_LSB = 1.0 / 32.0
TRACK_ANGLE_RATE_MAXIMUM = 16.0

#: I021/295 ages: LSB 0.1 s, maximum 25.5 s meaning "25.5 s or above" — a floor, not an age,
#: exactly as AIS's 102.2 kt is a floor and not a speed.
AGE_LSB_SECONDS = 0.1
AGE_AT_OR_ABOVE_MAXIMUM = 255

#: The ICAO Annex 10 Vol. IV Table 3-8 six-bit alphabet, as I021/170 and 1090ES both use it.
#: Index is the six-bit value; "#" marks a code the alphabet does not define, kept visible
#: rather than cleaned away for the reason `adsb.py` keeps it.
IDENTIFICATION_ALPHABET = (
    "#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####"
    " ###############0123456789######"
)
IDENTIFICATION_UNDEFINED = "#"


# ------------------------------------------------------------------- the vocabularies

#: I021/040 primary, bits 8/6. Decides which system name the target address is filed under.
ADDRESS_TYPE: dict[int, str] = {
    0: "24-bit ICAO address",
    1: "duplicate address",
    2: "surface vehicle address",
    3: "anonymous address",
    4: "reserved for future use",
    5: "reserved for future use",
    6: "reserved for future use",
    7: "reserved for future use",
}

#: Only ATP 0 is an ICAO24 address. Everything else goes to the pool that cannot be joined to a
#: real airframe — including the RESERVED values, which are NOT refused: unlike `adsb.py`'s
#: DF18 CF 3/4/7, a reserved ATP changes only what the address MEANS and every other field
#: decodes identically, so the safe pool is available and a refusal would discard a good
#: position to express an uncertainty about a name.
ATP_ICAO = 0

ALTITUDE_REPORTING_CAPABILITY: dict[int, str] = {
    0: "25 ft", 1: "100 ft", 2: "unknown", 3: "invalid",
}

CONFIDENCE_LEVEL: dict[int, str] = {
    0: "report valid", 1: "report suspect", 2: "no information",
    3: "reserved for future use",
}

#: I021/020. Every code accounted for — see the table in FORMAT_COVERAGE.md, where each row
#: carries its reason. Values 4, 6, 13, 14 and 16 are ADS-B Versions 0-2 only and are still sent
#: for a Version 3 system, per the item's own note.
EMITTER_CATEGORY: dict[int, str] = {
    0: "no ADS-B emitter category information",
    1: "light aircraft <= 15500 lbs",
    2: "small aircraft, 15500-75000 lbs",
    3: "medium aircraft, 75000-300000 lbs",
    4: "high vortex large",
    5: "heavy aircraft >= 300000 lbs",
    6: "highly manoeuvrable (5 g) and high speed (> 400 kt cruise)",
    10: "rotorcraft",
    11: "glider / sailplane",
    12: "lighter-than-air",
    13: "unmanned aerial vehicle",
    14: "space / transatmospheric vehicle",
    15: "ultralight / hang-glider / paraglider",
    16: "parachutist / skydiver",
    20: "surface emergency vehicle",
    21: "surface service vehicle",
    22: "fixed ground or tethered obstruction",
    23: "cluster obstacle",
    24: "line obstacle",
}

#: The reserved ranges, named so a reserved code lands in `unresolved_raw` — "the source said
#: something this adapter cannot use" — rather than silently reading as an unknown category.
EMITTER_CATEGORY_RESERVED = frozenset(range(7, 10)) | frozenset(range(17, 20))

#: The ONE place an emitter category refines the entity type. A point, cluster or line obstacle
#: is a fixed structure — the same three objects `adsb.py` maps to FACILITY from category set C
#: values 3, 4 and 5, reached through a different vocabulary, and the two adapters agree because
#: the reasoning is written down rather than because they were written together.
#:
#: Everything else is PLATFORM: a light aircraft, a heavy and a rotorcraft are all platforms,
#: and inventing a finer CDM distinction would put a judgement in a translator, exactly as an
#: AIS ship type does not change an entity type.
EMITTER_CATEGORY_FACILITY = frozenset({22, 23, 24})

#: I021/200, bits 5/3. The same six emergencies `adsb.py` reads from a type code 28 frame.
PRIORITY_STATUS: dict[int, str] = {
    0: "no emergency / not reported",
    1: "general emergency",
    2: "lifeguard / medical emergency",
    3: "minimum fuel",
    4: "no communications",
    5: "unlawful interference",
    6: "downed aircraft",
    7: "undefined",
}
PRIORITY_STATUS_EMERGENCIES = frozenset({1, 2, 3, 4, 5, 6})

#: REF/STA first extension. ADS-B Version 3 REDEFINED these values, and this is where a Version
#: 3 aircraft's emergency actually lives — I021/200's PS is superseded for such a system.
PRIORITY_STATUS_V3: dict[int, str] = {
    0: "no emergency / not reported",
    1: "general emergency",
    2: "UAS/RPAS lost link",
    3: "minimum fuel",
    4: "no communications",
    5: "unlawful interference",
    6: "aircraft in distress - automatic activation",
    7: "aircraft in distress - manual activation",
}
PRIORITY_STATUS_V3_EMERGENCIES = frozenset({1, 5, 6, 7})

#: The specification's own mapping from Version 3 values back to the pre-Version-3 vocabulary.
#: Recorded and NEVER run in reverse: 6 and 7 both collapse to 1, so inferring a distress
#: activation mode from a general emergency would invent one.
PRIORITY_STATUS_V3_TO_LEGACY: dict[int, int] = {0: 0, 1: 1, 2: 4, 3: 3, 4: 4, 5: 5, 6: 1, 7: 1}

#: I021/200, bits 2/1. 1 is the standard's own emergency declaration; 2 and 3 are procedural.
SURVEILLANCE_STATUS: dict[int, str] = {
    0: "no condition reported",
    1: "permanent alert (emergency condition)",
    2: "temporary alert (change in Mode 3/A code other than emergency)",
    3: "SPI set",
}
SURVEILLANCE_STATUS_EMERGENCY = 1

#: I021/210, bits 6/4, for LTT = 2 (1090 ES). It is what says how to read I021/090 and parts of
#: I021/200 — which is why a record without it has quality indicators of undetermined meaning.
MOPS_VERSION: dict[int, str] = {
    0: "ED-102 / DO-260 (ADS-B Version 0)",
    1: "DO-260A (ADS-B Version 1)",
    2: "ED-102A / DO-260B (ADS-B Version 2)",
    3: "ED-102B / DO-260C (ADS-B Version 3)",
}

LINK_TECHNOLOGY: dict[int, str] = {
    0: "other", 1: "UAT", 2: "1090 ES", 3: "VDL 4",
    4: "not assigned", 5: "not assigned", 6: "not assigned", 7: "not assigned",
}

#: I021/150's IM bit picks the quantity in the same fifteen bits — gap 10's evidence that one
#: `airspeed_mps` would close a third of a question.
AIRSPEED_TYPE: dict[int, str] = {0: "IAS", 1: "Mach"}

#: I021/146, bits 15/14. "Unknown" and "aircraft altitude" are kept for backward compatibility
#: and are not provided by Version 2 or higher systems.
SELECTED_ALTITUDE_SOURCE: dict[int, str] = {
    0: "unknown", 1: "aircraft altitude (holding altitude)",
    2: "MCP/FCU selected altitude", 3: "FMS selected altitude",
}

#: REF/SGV. HTT decides whether the angle is a HEADING or a GROUND TRACK, and only a ground
#: track may become `course_deg` — a heading is not a course.
HEADING_REFERENCE: dict[int, str] = {0: "true north", 1: "magnetic north"}
SGV_ANGLE_KIND: dict[int, str] = {0: "heading", 1: "ground track"}

#: I021/271 first extension: a four-bit BUCKET index, not a number. A bucket is a range, so an
#: extent field holding one figure would have to pick a midpoint and state a size nobody
#: measured — which is gap 8's argument against a scalar, made by a source rather than inferred.
AIRCRAFT_SIZE_BUCKET: dict[int, str] = {
    0: "L < 15 m, W < 11.5 m", 1: "L < 15 m, W < 23 m",
    2: "L < 25 m, W < 28.5 m", 3: "L < 25 m, W < 34 m",
    4: "L < 35 m, W < 33 m", 5: "L < 35 m, W < 38 m",
    6: "L < 45 m, W < 39.5 m", 7: "L < 45 m, W < 45 m",
    8: "L < 55 m, W < 45 m", 9: "L < 55 m, W < 52 m",
    10: "L < 65 m, W < 59.5 m", 11: "L < 65 m, W < 67 m",
    12: "L < 75 m, W < 72.5 m", 13: "L < 75 m, W < 80 m",
    14: "L < 85 m, W < 80 m", 15: "L > 85 m or W > 80 m",
}

#: I021/090 third extension: PIC, an integrity CONTAINMENT BOUND. The sharpest case in this
#: whole repository, because the specification finally hands over a number with a unit on it and
#: it is STILL the wrong kind of number — a containment bound is a radius inside which the truth
#: lies with a stated integrity, not the 1-sigma error `Position.accuracy_m` holds.
POSITION_INTEGRITY_CATEGORY: dict[int, str] = {
    0: "no integrity (or > 20.0 NM)", 1: "< 20.0 NM", 2: "< 10.0 NM", 3: "< 8.0 NM",
    4: "< 4.0 NM", 5: "< 2.0 NM", 6: "< 1.0 NM", 7: "< 0.6 NM", 8: "< 0.5 NM",
    9: "< 0.3 NM", 10: "< 0.2 NM", 11: "< 0.1 NM", 12: "< 0.04 NM", 13: "< 0.013 NM",
    14: "< 0.004 NM", 15: "not defined",
}

#: I021/074 and I021/076, bits 32/31. A WHOLE-SECOND CORRECTION to the item it accompanies, not
#: a rounding hint: ignoring it puts the fix a full second out at exactly the moment the ground
#: station took the trouble to say it was near a second boundary. 3 is reserved.
FULL_SECOND_INDICATION: dict[int, int | None] = {0: 0, 1: +1, 2: -1, 3: None}

#: I021/295's twenty-three subfields, in primary-subfield bit order: the item each one ages.
#: The strongest evidence for gap 13 — the format states per-field staleness and the CDM has
#: nowhere to put any of it.
DATA_AGE_SUBFIELDS: tuple[tuple[str, str], ...] = (
    ("aircraft_operational_status", "I021/008"), ("target_report_descriptor", "I021/040"),
    ("mode_3a", "I021/070"), ("quality_indicators", "I021/090"),
    ("trajectory_intent", "I021/110"), ("message_amplitude", "I021/132"),
    ("geometric_height", "I021/140"), ("flight_level", "I021/145"),
    ("selected_altitude", "I021/146"), ("final_state_selected_altitude", "I021/148"),
    ("air_speed", "I021/150"), ("true_air_speed", "I021/151"),
    ("magnetic_heading", "I021/152"), ("barometric_vertical_rate", "I021/155"),
    ("geometric_vertical_rate", "I021/157"), ("ground_vector", "I021/160"),
    ("track_angle_rate", "I021/165"), ("target_identification", "I021/170"),
    ("target_status", "I021/200"), ("met_information", "I021/220"),
    ("roll_angle", "I021/230"), ("acas_resolution_advisory", "I021/260"),
    ("surface_capabilities", "I021/271"),
)

#: REF item order is the Items Indicator's bit order, 8 down to 1.
REF_ITEMS: tuple[str, ...] = ("BPS", "SelH", "NAV", "GAO", "SGV", "STA", "TNH", "MES")

#: REF/MES compound subfields, in primary-subfield bit order 8 down to 3, with their octet
#: lengths. Parsed in full and parked in full — see the module docstring for the one act of
#: interpretation this adapter declines.
MES_SUBFIELDS: tuple[tuple[str, int], ...] = (
    ("mode_5_summary", 1), ("mode_5_pin_national_origin", 4),
    ("extended_mode_1_code", 2), ("x_pulse_presence", 1),
    ("figure_of_merit", 1), ("mode_2_code", 2),
)


# --------------------------------------------------------------- refusals, loudly

def _hex(data: bytes) -> str:
    """Octets as lowercase hex pairs. Every refusal quotes the bytes it refused."""
    return " ".join(f"{b:02x}" for b in data)


class Cat021ParseError(ValueError):
    """A structural refusal. Always quotes the offending octets.

    A subclass rather than a bare ValueError because a caller reading a feed wants to tell a
    malformed block apart from a programming error, and because `to_cdm` must never return a
    partial object: every one of these aborts the WHOLE block, including records already
    decoded. A trailing partial record means the parse desynchronised somewhere earlier, so
    every field decoded before it is suspect — emitting those would be a partial set of objects
    that looks complete, which is worse than none.
    """


def _refuse(message: str, data: bytes, start: int, length: int = 8) -> "Cat021ParseError":
    window = data[start:start + length]
    return Cat021ParseError(
        f"{message} (at octet {start}: {_hex(window)}"
        f"{'...' if start + length < len(data) else ''})"
    )


# ------------------------------------------------------------------ item length rules
#
# The five format kinds CAT021 uses. Each returns how many octets the item occupies, so the
# caller can slice it whole and keep the raw for egress.
#
# Two traps are worth naming because both decode into plausible nonsense rather than into an
# error. A VARIABLE item's extension count is data-dependent, so a decoder that assumed one
# octet would read the next item's first octet as an extension and shift everything after it.
# And a COMPOUND item's primary subfield is itself FX-extensible — I021/295's is up to four
# octets — so the presence map has to be read to its own end before any subfield is consumed.

FX = 0x01


def _fixed(n: int) -> Callable[[bytes, int], int]:
    return lambda data, offset: n


def _variable(data: bytes, offset: int) -> int:
    """One octet, extending one octet at a time while bit 1 (FX) is set."""
    length = 0
    while True:
        if offset + length >= len(data):
            raise _refuse("variable item runs past the end of the record", data, offset)
        extends = data[offset + length] & FX
        length += 1
        if not extends:
            return length


def _variable_from(primary: int) -> Callable[[bytes, int], int]:
    """A variable item whose primary subfield is `primary` octets, FX in the last one.

    REF/SGV is the only one: two octets of primary with FX in bit 1 of the SECOND, then one-octet
    extensions. Written as its own rule rather than special-cased inside the reader, because a
    two-octet primary read as a one-octet one desynchronises the rest of the REF.
    """
    def rule(data: bytes, offset: int) -> int:
        if offset + primary > len(data):
            raise _refuse("item runs past the end of the record", data, offset)
        length = primary
        while data[offset + length - 1] & FX:
            if offset + length >= len(data):
                raise _refuse("item extension runs past the end of the record", data, offset)
            length += 1
        return length
    return rule


def _repetitive(stride: int) -> Callable[[bytes, int], int]:
    """One octet of repetition factor, then REP blocks of `stride` octets."""
    def rule(data: bytes, offset: int) -> int:
        if offset >= len(data):
            raise _refuse("repetitive item has no repetition factor", data, offset)
        repetitions = data[offset]
        length = 1 + repetitions * stride
        if offset + length > len(data):
            raise _refuse(
                f"repetitive item declares {repetitions} repetitions of {stride} octets "
                f"({length} total) but only {len(data) - offset} remain",
                data, offset)
        return length
    return rule


def _explicit(data: bytes, offset: int) -> int:
    """One octet of length INCLUDING ITSELF, then the contents. RE and SP."""
    if offset >= len(data):
        raise _refuse("explicit item has no length octet", data, offset)
    length = data[offset]
    if length < 1 or offset + length > len(data):
        raise _refuse(
            f"explicit item declares {length} octets but only {len(data) - offset} remain",
            data, offset)
    return length


def _compound(sizes: Sequence[tuple[int, Callable[[bytes, int], int] | int]]) -> \
        Callable[[bytes, int], int]:
    """A presence-bit primary subfield (itself FX-extensible), then the present subfields.

    `sizes` is (bit_index_from_the_top_of_the_whole_primary, size) in primary order, where size
    is an octet count or a length rule. The bit index counts across ALL primary octets, seven
    bits per octet, because I021/295's map spans four of them.
    """
    def rule(data: bytes, offset: int) -> int:
        primary = _variable(data, offset)
        present = _presence_bits(data[offset:offset + primary])
        length = primary
        for index, size in sizes:
            if index >= len(present) or not present[index]:
                continue
            if callable(size):
                length += size(data, offset + length)
            else:
                if offset + length + size > len(data):
                    raise _refuse("compound subfield runs past the end of the record",
                                  data, offset + length)
                length += size
        return length
    return rule


def _presence_bits(primary: bytes) -> list[bool]:
    """The presence flags of a compound primary subfield, in order, FX bits excluded."""
    flags: list[bool] = []
    for octet in primary:
        for bit in range(7, 0, -1):
            flags.append(bool(octet & (1 << bit)))
    return flags


# ------------------------------------------------------------------------- the UAP
#
# The single User Application Profile for category 021, Edition 2.6, Table 2. Items appear in a
# record in FRN order, back to back, with no separators and no lengths of their own except where
# the item's own format carries one.
#
# FRN 43-47 are "Not Used". A set bit there is a REFUSAL: there is no item to decode, so skipping
# it is impossible and guessing a length would desynchronise every following item in the record.

UAP: tuple[tuple[int, str, Callable[[bytes, int], int] | None], ...] = (
    (1,  "I021/010", _fixed(2)),
    (2,  "I021/040", _variable),
    (3,  "I021/161", _fixed(2)),
    (4,  "I021/015", _fixed(1)),
    (5,  "I021/071", _fixed(3)),
    (6,  "I021/130", _fixed(6)),
    (7,  "I021/131", _fixed(8)),
    (8,  "I021/072", _fixed(3)),
    (9,  "I021/150", _fixed(2)),
    (10, "I021/151", _fixed(2)),
    (11, "I021/080", _fixed(3)),
    (12, "I021/073", _fixed(3)),
    (13, "I021/074", _fixed(4)),
    (14, "I021/075", _fixed(3)),
    (15, "I021/076", _fixed(4)),
    (16, "I021/140", _fixed(2)),
    (17, "I021/090", _variable),
    (18, "I021/210", _fixed(1)),
    (19, "I021/070", _fixed(2)),
    (20, "I021/230", _fixed(2)),
    (21, "I021/145", _fixed(2)),
    (22, "I021/152", _fixed(2)),
    (23, "I021/200", _fixed(1)),
    (24, "I021/155", _fixed(2)),
    (25, "I021/157", _fixed(2)),
    (26, "I021/160", _fixed(4)),
    (27, "I021/165", _fixed(2)),
    (28, "I021/077", _fixed(3)),
    (29, "I021/170", _fixed(6)),
    (30, "I021/020", _fixed(1)),
    # Met information: WS 2, WD 2, TMP 2, TRB 1.
    (31, "I021/220", _compound(((0, 2), (1, 2), (2, 2), (3, 1)))),
    (32, "I021/146", _fixed(2)),
    (33, "I021/148", _fixed(2)),
    # Trajectory intent: subfield #1 is itself VARIABLE, subfield #2 is repetitive with a
    # fifteen-octet stride. The prose says "fifteen octets" and the bit diagram numbers octets
    # 1..16 with REP as octet 1, i.e. fifteen per point after the count — the diagram is
    # authoritative and a fixture pins the reading, because a mis-sized point shifts every
    # field after it.
    (34, "I021/110", _compound(((0, _variable), (1, _repetitive(15))))),
    (35, "I021/016", _fixed(1)),
    (36, "I021/008", _fixed(1)),
    (37, "I021/271", _variable),
    (38, "I021/132", _fixed(1)),
    (39, "I021/250", _repetitive(8)),
    (40, "I021/260", _fixed(7)),
    (41, "I021/400", _fixed(1)),
    # Data ages: twenty-three one-octet subfields across a primary of up to four octets.
    (42, "I021/295", _compound(tuple((i, 1) for i in range(23)))),
    (43, None, None),
    (44, None, None),
    (45, None, None),
    (46, None, None),
    (47, None, None),
    (48, "RE", _explicit),
    (49, "SP", _explicit),
)

UAP_BY_FRN = {frn: (item, rule) for frn, item, rule in UAP}

#: The four items the specification says shall be present in every ASTERIX record. Their absence
#: is a refusal, and it is most of what replaces the CRC gate `adsb.py` has.
MANDATORY_ITEMS = ("I021/010", "I021/040", "I021/080", "I021/090")


# ------------------------------------------------------------------------- bit helpers

def _u(octets: bytes) -> int:
    """Big-endian unsigned integer. ASTERIX numbers bits from the MSB of octet 1."""
    return int.from_bytes(octets, "big")


def _twos(value: int, bits: int) -> int:
    """Two's complement over `bits` bits. Used on every signed CAT021 field."""
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def _bit(octet: int, number: int) -> int:
    """Bit `number` as the specification numbers it — 8 is the MSB of the octet, 1 the LSB."""
    return (octet >> (number - 1)) & 1


def _bits(value: int, high: int, low: int) -> int:
    """Bits `high`..`low` inclusive, numbered as the specification numbers them."""
    return (value >> (low - 1)) & ((1 << (high - low + 1)) - 1)


# -------------------------------------------------------------------- item decoders
#
# Every decoder returns NAMED fields in the units the specification talks in. The item's raw
# octets are kept separately by the record parser, so a decoder never has to worry about
# preserving them and egress never has to worry about re-encoding a decoded value.
#
# Note what is NOT here: any decision. A decoder reads bits; the mapping to canonical fields
# happens once, further down, where it can be read in one place.

def _d_010(o: bytes) -> dict: return {"sac": o[0], "sic": o[1]}
def _d_015(o: bytes) -> dict: return {"service_identification": o[0]}
def _d_016(o: bytes) -> dict: return {"report_period_raw": o[0]}
def _d_020(o: bytes) -> dict: return {"emitter_category": o[0]}
def _d_080(o: bytes) -> dict: return {"target_address": _u(o)}
def _d_132(o: bytes) -> dict: return {"message_amplitude_dbm": _twos(o[0], 8)}
def _d_140(o: bytes) -> dict: return {"geometric_height_raw": _u(o)}
def _d_145(o: bytes) -> dict: return {"flight_level_raw": _twos(_u(o), 16)}
def _d_152(o: bytes) -> dict: return {"magnetic_heading_raw": _u(o)}
def _d_161(o: bytes) -> dict: return {"track_number": _u(o) & 0x0FFF}
def _d_400(o: bytes) -> dict: return {"receiver_id": o[0]}
def _d_070(o: bytes) -> dict: return {"mode_3a_raw": _u(o) & 0x0FFF}
def _d_230(o: bytes) -> dict: return {"roll_angle_raw": _twos(_u(o), 16)}
def _d_165(o: bytes) -> dict: return {"track_angle_rate_raw": _twos(_u(o) & 0x03FF, 10)}


def _d_time(o: bytes) -> dict:
    """One of the five 1/128 s time-of-day items. The RAW count, deliberately.

    Not converted here, and not converted anywhere that egress reads: 1/128 s is 7.8125 ms and
    a CDM Timestamp renders three decimal places, so a value recomputed from `observed_at`
    would lose the remainder. The raw integer is the record and the instant is a derived view.
    """
    return {"time_of_day_raw": _u(o)}


def _d_high_precision(o: bytes) -> dict:
    """I021/074 / I021/076. FSI is a WHOLE-SECOND correction, not a rounding hint."""
    value = _u(o)
    return {
        "full_second_indication": _bits(value, 32, 31),
        "fraction_raw": _bits(value, 30, 1),
    }


def _d_130(o: bytes) -> dict:
    return {"latitude_raw": _twos(_u(o[0:3]), 24), "longitude_raw": _twos(_u(o[3:6]), 24)}


def _d_131(o: bytes) -> dict:
    return {"latitude_raw": _twos(_u(o[0:4]), 32), "longitude_raw": _twos(_u(o[4:8]), 32)}


def _d_150(o: bytes) -> dict:
    value = _u(o)
    return {"airspeed_is_mach": _bit(o[0], 8), "airspeed_raw": _bits(value, 15, 1)}


def _d_151(o: bytes) -> dict:
    value = _u(o)
    return {"range_exceeded": _bit(o[0], 8), "true_airspeed_kt": _bits(value, 15, 1)}


def _d_155_157(o: bytes) -> dict:
    value = _u(o)
    return {"range_exceeded": _bit(o[0], 8),
            "vertical_rate_raw": _twos(_bits(value, 15, 1), 15)}


def _d_160(o: bytes) -> dict:
    value = _u(o)
    return {
        "range_exceeded": _bit(o[0], 8),
        "ground_speed_raw": _bits(value, 31, 17),
        "track_angle_raw": _bits(value, 16, 1),
    }


def _d_146(o: bytes) -> dict:
    value = _u(o)
    return {
        "source_available": _bit(o[0], 8),
        "source": _bits(value, 15, 14),
        "altitude_raw": _twos(_bits(value, 13, 1), 13),
    }


def _d_148(o: bytes) -> dict:
    value = _u(o)
    return {
        "manage_vertical_mode": _bit(o[0], 8),
        "altitude_hold": _bit(o[0], 7),
        "approach_mode": _bit(o[0], 6),
        "altitude_raw": _twos(_bits(value, 13, 1), 13),
    }


def _d_170(o: bytes) -> dict:
    """Eight characters at six bits each, ICAO Annex 10 Vol. IV Table 3-8.

    The same alphabet and the same section `adsb.py` decodes for a 1090ES type code 1-4 frame —
    which is the whole point of the divergence note in FORMAT_COVERAGE.md: this is not a
    different field with a different ambiguity, it is the same field.
    """
    value = _u(o)
    characters = "".join(IDENTIFICATION_ALPHABET[_bits(value, 48 - 6 * i, 43 - 6 * i)]
                         for i in range(8))
    return {"target_identification_raw": characters}


def _d_200(o: bytes) -> dict:
    return {
        "intent_change_flag": _bit(o[0], 8),
        # The LOGIC IS REVERSED relative to ED-102/DO-260 per the item's own note: 0 means
        # engaged. Kept as sent, with the inversion recorded in the attributes, because a
        # consumer reading it the DO-260 way gets it exactly backwards.
        "lnav_mode_raw": _bit(o[0], 7),
        "military_emergency": _bit(o[0], 6),
        "priority_status": _bits(o[0], 5, 3),
        "surveillance_status": _bits(o[0], 2, 1),
    }


def _d_210(o: bytes) -> dict:
    return {
        "version_not_supported": _bit(o[0], 7),
        "mops_version": _bits(o[0], 6, 4),
        "link_technology": _bits(o[0], 3, 1),
    }


def _d_008(o: bytes) -> dict:
    return {
        "resolution_advisory_active": _bit(o[0], 8),
        "trajectory_change_capability": _bits(o[0], 7, 6),
        "target_state_capability": _bit(o[0], 5),
        "air_referenced_velocity_capability": _bit(o[0], 4),
        "cdti_airborne": _bit(o[0], 3),
        # Inverted sense: 1 means TCAS is NOT operational.
        "tcas_not_operational": _bit(o[0], 2),
        "single_antenna": _bit(o[0], 1),
    }


def _d_260(o: bytes) -> dict:
    """The ACAS resolution advisory report — a copy of BDS register 3,0.

    Decoded to its stated fields and NO further. The ARA and RAC bits are an ACAS vocabulary
    defined outside this specification, so decoding them means adopting a second standard —
    the same category as AIS's DAC/FI application identifiers, and the same call `adsb.py`
    makes about type code 28 subtype 2.
    """
    value = _u(o)
    return {
        "message_type": _bits(value, 56, 52),
        "message_subtype": _bits(value, 51, 49),
        "active_resolution_advisories": _bits(value, 48, 35),
        "resolution_advisory_complement": _bits(value, 34, 31),
        "ra_terminated": _bits(value, 30, 30),
        "multiple_threat_encounter": _bits(value, 29, 29),
        "threat_type_indicator": _bits(value, 28, 27),
        "threat_identity_data": _bits(value, 26, 1),
    }


def _d_040(o: bytes) -> dict:
    """Target report descriptor: primary plus up to four extensions."""
    out: dict[str, Any] = {
        "address_type": _bits(o[0], 8, 6),
        "altitude_reporting_capability": _bits(o[0], 5, 4),
        "range_check": _bit(o[0], 3),
        "report_from_field_monitor": _bit(o[0], 2),
    }
    if len(o) > 1:
        out.update({
            "differential_correction": _bit(o[1], 8),
            "ground_bit_set": _bit(o[1], 7),
            "simulated_target": _bit(o[1], 6),
            "test_target": _bit(o[1], 5),
            # Inverted sense: 0 means the equipment IS capable of providing a selected altitude.
            "selected_altitude_not_available": _bit(o[1], 4),
            "confidence_level": _bits(o[1], 3, 2),
        })
    if len(o) > 2:
        out.update({
            "list_lookup_check_failed": _bit(o[2], 7),
            "independent_position_check_failed": _bit(o[2], 6),
            "nogo_bit_set": _bit(o[2], 5),
            "cpr_validation_failed": _bit(o[2], 4),
            "local_decoding_position_jump": _bit(o[2], 3),
            # The row where the specification asks for filtering. See the module docstring.
            "range_check_failed": _bit(o[2], 2),
        })
    if len(o) > 3:
        # An Element Populated bit: NOT POPULATED IS NOT A COUNT OF ZERO.
        out.update({"total_bits_corrected_populated": _bit(o[3], 8),
                    "total_bits_corrected": _bits(o[3], 7, 2)})
    if len(o) > 4:
        out.update({"maximum_bits_corrected_populated": _bit(o[4], 8),
                    "maximum_bits_corrected": _bits(o[4], 7, 2)})
    return out


def _d_090(o: bytes) -> dict:
    """Quality indicators. Every value here is a CATEGORY or a BOUND, and none becomes canonical.

    The primary subfield holds one of two different quantities in each of its two groups —
    "NUCr or NACv" and "NUCp or NIC" — decided by the MOPS version in I021/210, which is
    optional. So this decoder reads the BITS and names them by both readings; which one applies
    is settled once, in `_quality_basis`, or declared undetermined.
    """
    out: dict[str, Any] = {
        "nucr_or_nacv": _bits(o[0], 8, 6),
        "nucp_or_nic": _bits(o[0], 5, 2),
    }
    if len(o) > 1:
        out.update({"nic_baro": _bit(o[1], 8), "source_integrity_level": _bits(o[1], 7, 6),
                    "nac_position": _bits(o[1], 5, 2)})
    if len(o) > 2:
        out.update({"sil_supplement": _bit(o[2], 6),
                    "system_design_assurance": _bits(o[2], 5, 4),
                    "geometric_altitude_accuracy": _bits(o[2], 3, 2)})
    if len(o) > 3:
        out.update({"position_integrity_category": _bits(o[3], 8, 5)})
    return out


def _d_271(o: bytes) -> dict:
    out: dict[str, Any] = {
        "position_offset_applied": _bit(o[0], 6),
        "cdti_surface": _bit(o[0], 5),
        "class_b2_low_power": _bit(o[0], 4),
        "receiving_atc_services": _bit(o[0], 3),
        "ident_switch_active": _bit(o[0], 2),
    }
    if len(o) > 1:
        # A four-bit BUCKET index, not a number — gap 8's argument against a scalar extent.
        out["aircraft_size_bucket"] = _bits(o[1], 8, 5)
    return out


def _d_220(o: bytes) -> dict:
    """Met information. Wind direction's range starts at 1, so it has no zero and 360 is north."""
    primary = _variable(o, 0)
    present = _presence_bits(o[:primary])
    out: dict[str, Any] = {}
    at = primary
    if present[0]:
        out["wind_speed_kt"] = _u(o[at:at + 2]); at += 2
    if present[1]:
        out["wind_direction_deg"] = _u(o[at:at + 2]); at += 2
    if present[2]:
        out["temperature_raw"] = _twos(_u(o[at:at + 2]), 16); at += 2
    if present[3]:
        out["turbulence"] = o[at]; at += 1
    return out


def _d_110(o: bytes) -> dict:
    """Trajectory intent. INTENT, not position — see gap 15, and note what does NOT happen here.

    The points are decoded and parked. They are never written to `Event.geometry`: a LineString
    there would paint an aircraft's declared FUTURE as something observed, which is the one
    failure mode a picture cannot survive.
    """
    primary = _variable(o, 0)
    present = _presence_bits(o[:primary])
    out: dict[str, Any] = {}
    at = primary
    if present[0]:
        status_length = _variable(o, at)
        # Both bits are NEGATIVE-sense: 1 means not available / not valid.
        out["trajectory_intent_not_available"] = _bit(o[at], 8)
        out["trajectory_intent_not_valid"] = _bit(o[at], 7)
        at += status_length
    if present[1]:
        repetitions = o[at]
        at += 1
        points = []
        for _ in range(repetitions):
            block = o[at:at + 15]
            at += 15
            value = _u(block)
            points.append({
                "tcp_number_not_available": _bits(value, 120, 120),
                "tcp_non_compliance": _bits(value, 119, 119),
                "tcp_number": _bits(value, 118, 113),
                "altitude_raw": _twos(_bits(value, 112, 97), 16),
                "latitude_raw": _twos(_bits(value, 96, 73), 24),
                "longitude_raw": _twos(_bits(value, 72, 49), 24),
                "point_type": _bits(value, 48, 45),
                "turn_direction": _bits(value, 44, 43),
                "turn_radius_available": _bits(value, 42, 42),
                "time_over_point_not_available": _bits(value, 41, 41),
                "time_over_point_s": _bits(value, 40, 17),
                "turn_radius_raw": _bits(value, 16, 1),
            })
        out["trajectory_intent_points"] = points
    return out


def _d_250(o: bytes) -> dict:
    """BDS register data, repetitive. Parked as raw hex per register with its address.

    Not decoded further, and the specification's own note says why: the payload "is not encoded
    in ASTERIX but in the original Squitter format". The BDS registers are a separate register
    set with their own document, which is the reason `adsb.py` names a Mode S BDS adapter as a
    different adapter.
    """
    repetitions = o[0]
    registers = []
    for i in range(repetitions):
        block = o[1 + i * 8: 9 + i * 8]
        registers.append({
            "bds_data": _hex(block[0:7]).replace(" ", ""),
            "bds1": _bits(block[7], 8, 5),
            "bds2": _bits(block[7], 4, 1),
        })
    return {"bds_registers": registers}


def _d_295(o: bytes) -> dict:
    """Twenty-three per-item ages at 0.1 s. The strongest evidence for gap 13.

    The maximum, 255 (25.5 s), means "25.5 s OR ABOVE" — a floor and not an age, recorded as one
    exactly as AIS's 102.2 kt is.
    """
    primary = _variable(o, 0)
    present = _presence_bits(o[:primary])
    ages: dict[str, Any] = {}
    at = primary
    for index, (name, item) in enumerate(DATA_AGE_SUBFIELDS):
        if index >= len(present) or not present[index]:
            continue
        raw = o[at]
        at += 1
        ages[name] = {
            "item": item,
            "age_raw": raw,
            "age_s": round(raw * AGE_LSB_SECONDS, 1),
            "at_or_above_maximum": raw == AGE_AT_OR_ABOVE_MAXIMUM or None,
        }
    return {"data_ages": ages}


ITEM_DECODERS: dict[str, Callable[[bytes], dict]] = {
    "I021/008": _d_008, "I021/010": _d_010, "I021/015": _d_015, "I021/016": _d_016,
    "I021/020": _d_020, "I021/040": _d_040, "I021/070": _d_070, "I021/071": _d_time,
    "I021/072": _d_time, "I021/073": _d_time, "I021/074": _d_high_precision,
    "I021/075": _d_time, "I021/076": _d_high_precision, "I021/077": _d_time,
    "I021/080": _d_080, "I021/090": _d_090, "I021/110": _d_110, "I021/130": _d_130,
    "I021/131": _d_131, "I021/132": _d_132, "I021/140": _d_140, "I021/145": _d_145,
    "I021/146": _d_146, "I021/148": _d_148, "I021/150": _d_150, "I021/151": _d_151,
    "I021/152": _d_152, "I021/155": _d_155_157, "I021/157": _d_155_157, "I021/160": _d_160,
    "I021/161": _d_161, "I021/165": _d_165, "I021/170": _d_170, "I021/200": _d_200,
    "I021/210": _d_210, "I021/220": _d_220, "I021/230": _d_230, "I021/250": _d_250,
    "I021/260": _d_260, "I021/271": _d_271, "I021/295": _d_295, "I021/400": _d_400,
}


# ------------------------------------------------------- the Reserved Expansion Field
#
# In scope IN FULL for 1.0.0, and the reason is in the module docstring: the core specification
# relocates a Version 3 aircraft's emergency and the whole surface ground vector into here.

def _d_ref_bps(o: bytes) -> dict:
    """Barometric pressure setting. The wire value is the setting MINUS 800 hPa.

    0 means "800 hPa or less" and 4095 (409.5) means "1209.5 hPa or more" — two floors, recorded
    as floors and not as settings.
    """
    raw = _u(o) & 0x0FFF
    return {"barometric_pressure_setting_raw": raw}


def _d_ref_selh(o: bytes) -> dict:
    value = _u(o)
    return {
        "heading_reference": _bits(value, 12, 12),
        "selected_heading_valid": _bits(value, 11, 11),
        "selected_heading_raw": _bits(value, 10, 1),
    }


def _d_ref_nav(o: bytes) -> dict:
    """Navigation mode. MFM#VAL = 0 forces AP/VN/AH/AM to 0 and I021/200's LNAV to 1.

    So a record with the element unpopulated states NOTHING about the autopilot, and reading
    those zeros as "autopilot off" would be a fabricated fact. `unavailable_fields` records it.
    """
    return {
        "autopilot_engaged": _bit(o[0], 8),
        "vnav_active": _bit(o[0], 7),
        "altitude_hold_engaged": _bit(o[0], 6),
        "approach_mode_active": _bit(o[0], 5),
        "mcp_fcu_mode_bits_populated": _bit(o[0], 4),
        "mcp_fcu_mode_bits_value": _bit(o[0], 3),
    }


def _d_ref_gao(o: bytes) -> dict:
    """GPS antenna offset, LSB 2 m. Bit 8 gives the lateral direction, 0 left of centreline.

    Gap 8's offset reference point, stated numerically by a source for the first time.
    """
    return {
        "lateral_offset_raw": _bits(o[0], 8, 6),
        "longitudinal_offset_raw": _bits(o[0], 5, 1),
    }


def _d_ref_sgv(o: bytes) -> dict:
    """Surface ground vector — without which a surface target has no motion at all."""
    value = _u(o[0:2])
    out = {
        "aircraft_stopped": _bits(value, 16, 16),
        "heading_track_valid": _bits(value, 15, 15),
        "heading_track_is_ground_track": _bits(value, 14, 14),
        "heading_reference": _bits(value, 13, 13),
        "ground_speed_raw": _bits(value, 12, 2),
    }
    if len(o) > 2:
        out["heading_track_raw"] = _bits(o[2], 8, 2)
    return out


def _d_ref_sta(o: bytes) -> dict:
    """Aircraft status, primary plus five Version 3 extensions.

    Every value here carries an Element Populated bit and NOT POPULATED IS NOT A VALUE OF ZERO:
    the two are kept distinct and an unpopulated element is named in `unresolved_raw`.
    """
    out: dict[str, Any] = {
        "es_in_capable": _bit(o[0], 8),
        "uat_in_capable": _bit(o[0], 7),
        "reduced_capability_populated": _bit(o[0], 6),
        "reduced_capability": _bits(o[0], 5, 4),
        "reply_rate_limiting_populated": _bit(o[0], 3),
        "reply_rate_limiting": _bit(o[0], 2),
    }
    if len(o) > 1:
        # PS3 — where a Version 3 aircraft's emergency actually lives.
        out.update({"priority_status_v3_populated": _bit(o[1], 8),
                    "priority_status_v3": _bits(o[1], 7, 5),
                    "transmit_power_populated": _bit(o[1], 4),
                    "transmit_power": _bits(o[1], 3, 2)})
    if len(o) > 2:
        out.update({"transponder_side_populated": _bit(o[2], 8),
                    "transponder_side": _bits(o[2], 7, 6),
                    "manned_unmanned_populated": _bit(o[2], 5),
                    "unmanned_operation": _bit(o[2], 4),
                    "remain_well_clear_populated": _bit(o[2], 3),
                    "remain_well_clear_alert": _bit(o[2], 2)})
    if len(o) > 3:
        out.update({"detect_and_avoid_populated": _bit(o[3], 8),
                    "detect_and_avoid": _bits(o[3], 7, 6),
                    "df17_capability_populated": _bit(o[3], 5),
                    "df17_capability": _bits(o[3], 4, 2)})
    if len(o) > 4:
        out.update({"sense_vertical_horizontal_populated": _bit(o[4], 8),
                    "sense_vertical_horizontal": _bits(o[4], 7, 6),
                    "cas_type_capability_populated": _bit(o[4], 5),
                    "cas_type_capability": _bits(o[4], 4, 2)})
    if len(o) > 5:
        out.update({"transponder_antenna_offset_populated": _bit(o[5], 8),
                    "transponder_antenna_offset": _bits(o[5], 7, 3)})
    return out


def _d_ref_tnh(o: bytes) -> dict:
    """True north heading — gap 7's datum, stated by the source in its own item."""
    return {"true_north_heading_raw": _u(o)}


def _d_ref_mes(o: bytes) -> dict:
    """Military extended squitter. Parsed in full, parked in full, interpreted not at all.

    Subfield #1's `ID` and `DA` are authenticated Mode 5 indications — the first cryptographically
    attested identity any source here carries. They are NOT read as an affiliation; see the
    module docstring and gap 2.
    """
    primary = _variable(o, 0)
    present = _presence_bits(o[:primary])
    out: dict[str, Any] = {}
    at = primary
    for index, (name, size) in enumerate(MES_SUBFIELDS):
        if index >= len(present) or not present[index]:
            continue
        block = o[at:at + size]
        at += size
        if name == "mode_5_summary":
            out[name] = {
                "mode_5_interrogation": _bit(block[0], 8),
                "authenticated_mode_5_id": _bit(block[0], 7),
                "authenticated_mode_5_data": _bit(block[0], 6),
                "mode_1_from_mode_5": _bit(block[0], 5),
                "mode_2_from_mode_5": _bit(block[0], 4),
                "mode_3_from_mode_5": _bit(block[0], 3),
                "flight_level_from_mode_5": _bit(block[0], 2),
                "position_from_mode_5": _bit(block[0], 1),
            }
        elif name == "mode_5_pin_national_origin":
            value = _u(block)
            out[name] = {"pin": _bits(value, 30, 17), "national_origin": _bits(value, 11, 1)}
        elif name in ("extended_mode_1_code", "mode_2_code"):
            value = _u(block)
            out[name] = {"not_validated": _bits(value, 16, 16),
                         "smoothed_by_local_tracker": _bits(value, 14, 14),
                         "code_raw": _bits(value, 12, 1)}
        elif name == "x_pulse_presence":
            out[name] = {"from_mode_5_pin": _bit(block[0], 6), "from_mode_5_data": _bit(block[0], 5),
                         "from_mode_c": _bit(block[0], 4), "from_mode_3a": _bit(block[0], 3),
                         "from_mode_2": _bit(block[0], 2), "from_mode_1": _bit(block[0], 1)}
        else:
            out[name] = {"figure_of_merit": _bits(block[0], 5, 1)}
    return out


REF_DECODERS: dict[str, tuple[Callable[[bytes, int], int], Callable[[bytes], dict]]] = {
    "BPS":  (_fixed(2), _d_ref_bps),
    "SelH": (_fixed(2), _d_ref_selh),
    "NAV":  (_fixed(1), _d_ref_nav),
    "GAO":  (_fixed(1), _d_ref_gao),
    "SGV":  (_variable_from(2), _d_ref_sgv),
    "STA":  (_variable, _d_ref_sta),
    "TNH":  (_fixed(2), _d_ref_tnh),
    "MES":  (_compound(tuple((i, size) for i, (_, size) in enumerate(MES_SUBFIELDS))),
             _d_ref_mes),
}


def _parse_ref(octets: bytes) -> dict:
    """The RE field's contents: its own length octet, an items indicator, then the items."""
    if len(octets) < 2:
        raise _refuse("Reserved Expansion Field is shorter than its own header", octets, 0)
    declared = octets[0]
    if declared != len(octets):
        raise Cat021ParseError(
            f"Reserved Expansion Field declares {declared} octets (its length counts itself) "
            f"but {len(octets)} were read: {_hex(octets)}"
        )
    indicator = octets[1]
    out: dict[str, Any] = {
        "length": declared,
        "items_indicator": indicator,
        "items": {},
        "item_octets": {},
    }
    at = 2
    for index, name in enumerate(REF_ITEMS):
        if not _bit(indicator, 8 - index):
            continue
        rule, decoder = REF_DECODERS[name]
        length = rule(octets, at)
        block = octets[at:at + length]
        if len(block) != length:
            raise _refuse(f"REF item {name} runs past the end of the field", octets, at)
        out["item_octets"][name] = block.hex()
        out["items"][name] = decoder(block)
        at += length
    if at != len(octets):
        raise Cat021ParseError(
            f"Reserved Expansion Field has {len(octets) - at} octets left over after its "
            f"declared items ({_hex(octets[at:])}) — the items indicator and the contents "
            "disagree, so nothing after this point can be trusted"
        )
    return out


# ------------------------------------------------------------------ block and record

def _parse_block(raw: bytes) -> dict:
    """One ASTERIX data block -> the parsed form. Every failure quotes its octets."""
    data = bytes(raw)
    if len(data) < BLOCK_HEADER_OCTETS:
        raise Cat021ParseError(
            f"an ASTERIX data block is at least {BLOCK_HEADER_OCTETS} octets (CAT + LEN); "
            f"got {len(data)}: {_hex(data)}"
        )
    category = data[0]
    if category != CATEGORY:
        raise Cat021ParseError(
            f"data block declares category {category}, not {CATEGORY}. This adapter speaks "
            "ASTERIX category 021 only — every category has its own User Application Profile, "
            "and a block decoded against the wrong one yields a plausible wrong aircraft "
            f"rather than an error. First octets: {_hex(data[:8])}"
        )
    declared = _u(data[1:3])
    if declared != len(data):
        raise Cat021ParseError(
            f"data block declares LEN {declared} octets but {len(data)} were supplied. LEN "
            "counts the CAT and LEN octets themselves; reading to the end of the buffer instead "
            "would translate whatever followed the block as if it were part of it. "
            f"Header: {_hex(data[:8])}"
        )

    records = []
    at = BLOCK_HEADER_OCTETS
    while at < len(data):
        record, at = _parse_record(data, at, index=len(records))
        records.append(record)
    if not records:
        raise Cat021ParseError(
            f"data block of {declared} octets holds no records: {_hex(data)}. An empty list "
            "means 'this payload legitimately carries nothing', and a block with a header and "
            "no records is a malformed block rather than an empty one"
        )
    return {
        "block": {"category": category, "length": declared, "record_count": len(records)},
        "records": records,
    }


def _parse_record(data: bytes, offset: int, *, index: int) -> tuple[dict, int]:
    """One record: the FSPEC, then the present items in FRN order."""
    fspec_start = offset
    at = offset
    frns: list[int] = []
    while True:
        if at >= len(data):
            raise _refuse(f"record {index}: FSPEC runs past the end of the block",
                          data, fspec_start)
        octet = data[at]
        base = (at - fspec_start) * 7
        for bit in range(7, 0, -1):
            if octet & (1 << bit):
                frns.append(base + (8 - bit))
        at += 1
        if not octet & FX:
            break
    fspec = data[fspec_start:at]

    items: dict[str, Any] = {}
    item_octets: dict[str, str] = {}
    for frn in frns:
        entry = UAP_BY_FRN.get(frn)
        if entry is None or entry[0] is None:
            raise _refuse(
                f"record {index}: FSPEC sets FRN {frn}, which the category 021 UAP marks Not "
                "Used. There is no item to decode, so it cannot be skipped, and guessing a "
                "length would desynchronise every following item in the record",
                data, fspec_start)
        item, rule = entry
        length = rule(data, at)
        block = data[at:at + length]
        if len(block) != length:
            raise _refuse(f"record {index}: item {item} runs past the end of the block",
                          data, at)
        item_octets[item] = block.hex()
        if item == "RE":
            items[item] = _parse_ref(block)
        elif item == "SP":
            # Opaque by definition: the Special Purpose Field's contents are settled by
            # bilateral agreement between one sender and one receiver. Parked verbatim, and
            # never written to on egress for an object that did not arrive with one.
            items[item] = {"length": block[0], "contents": block[1:].hex()}
        else:
            items[item] = ITEM_DECODERS[item](block)
        at += length

    missing = [item for item in MANDATORY_ITEMS if item not in items]
    if missing:
        raise _refuse(
            f"record {index} is missing {', '.join(missing)}, which the specification says "
            "shall be present in every ASTERIX record. ASTERIX carries no checksum at any "
            "level, so the mandatory items are part of what replaces one",
            data, fspec_start)

    return {
        "index": index,
        "fspec": fspec.hex(),
        "items": items,
        "item_octets": item_octets,
    }, at


# ------------------------------------------------------------------------ time

#: The `observed_at` chain, in order, with the sentence that goes into the basis. Position
#: applicability first, because the fix is the thing on the map; the ground station's own report
#: transmission time last, because it is a source-stated time about the REPORT rather than about
#: the observation.
TIME_CHAIN: tuple[tuple[str, str], ...] = (
    ("I021/071", "I021/071, the time of applicability of the POSITION — the aircraft's own "
                 "synchronised measurement instant, and the best answer this format has"),
    ("I021/073", "I021/073, the time of message reception of the POSITION at the ground "
                 "station. Not the aircraft's instant, but a stated time about the position "
                 "rather than about the report; I021/071 was absent"),
    ("I021/072", "I021/072, the time of applicability of the VELOCITY — this record carries "
                 "velocity and no position"),
    ("I021/075", "I021/075, the time of message reception of the VELOCITY at the ground "
                 "station"),
    ("I021/077", "I021/077, the ground station's own report transmission time. A source-stated "
                 "time, but about the REPORT and not about the observation, which is why it is "
                 "last in the chain"),
)

#: Which high-precision item refines which whole-seconds item.
HIGH_PRECISION_PARTNER = {"I021/073": "I021/074", "I021/075": "I021/076"}


def _time_of_day_seconds(items: dict, item: str) -> float:
    """The stated time of day in seconds, refined by its high-precision partner if present.

    Raises on a value at or beyond 86 400 s. Twenty-four bits at 1/128 s reach 131 071.99 s, so
    the field can express times of day that do not exist; the counter resets at midnight, so
    such a value is corrupt or non-conforming. Taking it modulo 86 400 would move a contact by
    hours and leave every other check passing.
    """
    raw = int(items[item]["time_of_day_raw"])
    seconds = raw * TIME_LSB_SECONDS
    if seconds >= SECONDS_PER_DAY:
        raise Cat021ParseError(
            f"{item} states {raw} units of 1/128 s = {seconds:.4f} s since midnight, which is "
            f"not a time of day: the counter resets at every midnight, so it cannot reach "
            f"{SECONDS_PER_DAY}. Refusing rather than taking it modulo a day — a modulo would "
            "move this contact by hours and leave every other check passing"
        )
    partner = HIGH_PRECISION_PARTNER.get(item)
    if partner and partner in items:
        correction = FULL_SECOND_INDICATION[int(items[partner]["full_second_indication"])]
        if correction is not None:
            whole = int(seconds)
            fraction = int(items[partner]["fraction_raw"]) * HIGH_PRECISION_LSB_SECONDS
            seconds = whole + correction + fraction
    return seconds


def _resolve_instant(seconds: float, received_at: _dt.datetime) -> tuple[_dt.datetime, int]:
    """A time of day plus the receipt instant -> the instant it names, and the rollover applied.

    The candidates are the stated time of day on the receipt date, the day before and the day
    after; the nearest to the receipt instant wins. That single rule handles both rollover
    directions without a special case, which is why there is no special case here to get wrong.
    """
    midnight = received_at.astimezone(_dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    best, best_offset, best_distance = None, 0, None
    for offset in (-1, 0, 1):
        candidate = midnight + _dt.timedelta(days=offset, seconds=seconds)
        distance = abs((candidate - received_at).total_seconds())
        if best_distance is None or distance < best_distance:
            best, best_offset, best_distance = candidate, offset, distance
    return best, best_offset


def _observed_at(items: dict, received_at: _dt.datetime) -> tuple[_dt.datetime, str]:
    """Walk the chain; return the instant and the basis sentence naming every half of it."""
    for item, description in TIME_CHAIN:
        if item not in items:
            continue
        seconds = _time_of_day_seconds(items, item)
        instant, rollover = _resolve_instant(seconds, received_at)
        partner = HIGH_PRECISION_PARTNER.get(item)
        refined = partner in items if partner else False
        basis = (
            f"{description}. CAT021 states a time of DAY and never a date: "
            f"{seconds:.7f} s since midnight UTC"
            + (f", refined by {partner}'s full-second indication and 2^-30 s fraction"
               if refined else "")
            + ". The date is the injected clock's, and the instant chosen is the one bearing "
              "that time of day NEAREST the receipt instant"
            + ("" if rollover == 0 else
               f" — which here is the {'previous' if rollover < 0 else 'next'} day, a midnight "
               "rollover, applied because that candidate is nearer than the receipt date's")
            + ". The raw wire integer is parked at attributes.cat021_times: 1/128 s is not a "
              "whole number of milliseconds, so a value recomputed from this timestamp would "
              "lose the remainder"
        )
        return instant, basis
    return received_at, (
        "this record carries no time item at all — no applicability time, no message reception "
        "time and no report transmission time — so the receipt instant is used and the record "
        "states nothing about when. The four items the specification makes mandatory do not "
        "include one"
    )


# -------------------------------------------------------------------- canonical views

def _position_item(items: dict) -> str | None:
    """I021/131 wins when both are present: it is strictly more precise.

    The encoding rule says "either I021/130 or I021/131 shall be sent", but both sit in the UAP
    at FRN 6 and 7 and a non-conforming encoder can set both bits, so the case has to have an
    answer rather than a hope.
    """
    if "I021/131" in items:
        return "I021/131"
    return "I021/130" if "I021/130" in items else None


def _coordinates(items: dict, item: str) -> tuple[float, float]:
    lsb = LSB_131_DEGREES if item == "I021/131" else LSB_130_DEGREES
    return (items[item]["latitude_raw"] * lsb, items[item]["longitude_raw"] * lsb)


def _geometric_height_m(items: dict) -> float | None:
    """I021/140 in metres, or None when the item carries the "greater than" marker.

    The marker names no bound — the item's stated range tops out at 150 000 ft and the note does
    not say the marker means "above that" — so it is a statement this adapter cannot use rather
    than the source saying it does not know. `alt_m` is absent and the raw goes to
    `unresolved_raw`; reading 0x7FFF as a value would report 204 793.75 ft, which is not an
    altitude any aircraft is at.
    """
    if "I021/140" not in items:
        return None
    raw = int(items["I021/140"]["geometric_height_raw"])
    if raw == GEOMETRIC_HEIGHT_GREATER_THAN:
        return None
    return round(_twos(raw, 16) * GEOMETRIC_HEIGHT_LSB_FEET * FEET_TO_METRES, 4)


def _position(items: dict) -> Position | None:
    """The fix, or None. Never a Position holding zeros, and never a remembered one."""
    item = _position_item(items)
    if item is None:
        return None
    latitude, longitude = _coordinates(items, item)
    return Position(
        lat=round(latitude, 10),
        lon=round(longitude, 10),
        alt_m=_geometric_height_m(items),
        # A CAT021 position originated as the aircraft's own GNSS fix; the ground station
        # CPR-decoded it upstream. attributes.position_source_basis records that the decode
        # happened there and that this adapter did not perform it.
        position_source=PositionSource.GNSS,
        # None, always. Every accuracy statement CAT021 carries is a category or a containment
        # bound, and None means unknown accuracy — never perfect accuracy.
        accuracy_m=None,
    )


def _kinematics(items: dict) -> Kinematics | None:
    """Speed, course and climb — each from the item that actually states that quantity."""
    speed = course = climb = None
    ref_items = (items.get("RE") or {}).get("items", {})
    sgv = ref_items.get("SGV")

    if "I021/160" in items:
        vector = items["I021/160"]
        speed = round(int(vector["ground_speed_raw"]) * GROUND_SPEED_LSB_NM_PER_S
                      * METRES_PER_NAUTICAL_MILE, 6)
        course = round(int(vector["track_angle_raw"]) * ANGLE_LSB_DEGREES, 6) % 360.0
    elif sgv is not None:
        if sgv.get("aircraft_stopped"):
            # A measurement of stillness, not an absence — AIS's stationary life raft.
            speed = 0.0
        else:
            speed = round(int(sgv["ground_speed_raw"]) * 0.125
                          * METRES_PER_NAUTICAL_MILE / 3600.0, 6)
        # Only a GROUND TRACK may become a course. A heading is not a course, and HTT is the
        # bit that says which of the two the same seven bits are carrying.
        if sgv.get("heading_track_valid") and sgv.get("heading_track_is_ground_track") \
                and "heading_track_raw" in sgv:
            course = round(int(sgv["heading_track_raw"]) * 2.8125, 6) % 360.0

    # The GEOMETRIC rate is preferred: it differentiates the same surface `alt_m` is measured
    # against. The barometric one is used only when it is the only one present, and both raws
    # are parked either way.
    for item in ("I021/157", "I021/155"):
        if item in items:
            climb = round(int(items[item]["vertical_rate_raw"])
                          * VERTICAL_RATE_LSB_FEET_PER_MINUTE * FEET_TO_METRES / 60.0, 6)
            break

    if speed is None and course is None and climb is None:
        return None
    return Kinematics(speed_mps=speed, course_deg=course, climb_mps=climb)


def _entity_type(items: dict) -> EntityType:
    """PLATFORM, refined to FACILITY only for a point, cluster or line obstacle."""
    category = (items.get("I021/020") or {}).get("emitter_category")
    if isinstance(category, int) and category in EMITTER_CATEGORY_FACILITY:
        return EntityType.FACILITY
    return EntityType.PLATFORM


def _source_id_system(items: dict) -> tuple[str, str]:
    """The system name for the target address, and the wording of why."""
    atp = int((items.get("I021/040") or {}).get("address_type", ATP_ICAO))
    if atp == ATP_ICAO:
        return ICAO_SYSTEM, ADDRESS_TYPE[atp]
    return NONICAO_SYSTEM, ADDRESS_TYPE.get(atp, "reserved for future use")


def _emergency(items: dict) -> tuple[bool, str]:
    """Is this record an emergency, and the sentence that says why or why not.

    The line is drawn where the standard itself declares an emergency — exactly where `adsb.py`
    draws it at a type code 28 emergency state and `ais.py` at navigational status 14. Four
    independent declarations, and a record can raise more than one.
    """
    status = items.get("I021/200") or {}
    ref_items = (items.get("RE") or {}).get("items", {})
    sta = ref_items.get("STA") or {}
    version = (items.get("I021/210") or {}).get("mops_version")

    reasons = []
    priority = status.get("priority_status")
    if isinstance(priority, int) and priority in PRIORITY_STATUS_EMERGENCIES:
        reasons.append(f"I021/200 priority status {priority} — {PRIORITY_STATUS[priority]}")
    if status.get("surveillance_status") == SURVEILLANCE_STATUS_EMERGENCY:
        reasons.append("I021/200 surveillance status 1 — permanent alert, the standard's own "
                       "emergency condition")
    if status.get("military_emergency"):
        reasons.append("I021/200 military emergency bit set")
    if sta.get("priority_status_v3_populated"):
        v3 = int(sta.get("priority_status_v3", 0))
        if v3 in PRIORITY_STATUS_V3_EMERGENCIES:
            reasons.append(
                f"REF/STA priority status (Version 3) {v3} — {PRIORITY_STATUS_V3[v3]}. This is "
                "where an emergency lives for a Version 3 system: I021/200's priority status is "
                f"superseded, and this record's MOPS version is {version}")
    if reasons:
        return True, ("the standard's own emergency declaration: " + "; ".join(reasons))
    return False, (
        "no emergency is declared. INFO records that the format is SILENT here — I021/200's "
        "priority status, surveillance status and military emergency bit, and REF/STA's "
        "Version 3 priority status, all read as no condition — and not that a translator judged "
        "the flight to be calm"
    )


# ------------------------------------------------------------------- the attributes

def _unavailable_fields(items: dict) -> list[str]:
    """What the SOURCE explicitly said it does not know. Never what this adapter had nothing on.

    A stated absence and an adapter's silence are different facts and only one of them is in
    the data — which is why this list and `unresolved_raw` are two keys and not one.
    """
    found = []
    category = (items.get("I021/020") or {}).get("emitter_category")
    if category == 0:
        found.append("emitter_category")
    if (items.get("I021/040") or {}).get("altitude_reporting_capability") == 2:
        found.append("altitude_reporting_capability")
    ref_items = (items.get("RE") or {}).get("items", {})
    selh = ref_items.get("SelH")
    if selh is not None and not selh.get("selected_heading_valid"):
        found.append("selected_heading")
    sgv = ref_items.get("SGV")
    if sgv is not None and not sgv.get("heading_track_valid"):
        found.append("surface_heading_track")
    nav = ref_items.get("NAV")
    if nav is not None and not nav.get("mcp_fcu_mode_bits_populated"):
        # MFM#VAL clear forces AP/VN/AH/AM to 0 and LNAV to 1, so those zeros state NOTHING
        # about the autopilot. Reading them as "autopilot off" would be a fabricated fact.
        found.append("navigation_mode")
    return sorted(found)


def _unresolved_raw(items: dict) -> dict[str, Any]:
    """What the source stated and this adapter could not turn into a CDM value.

    A DIFFERENT fact from `unavailable_fields`, and the pair is the point: that list is "the
    source said it does not know", this one is "the source said something and the translator
    could not use it, so here are its bits". Both render as an absent field.
    """
    found: dict[str, Any] = {}
    category = (items.get("I021/020") or {}).get("emitter_category")
    if isinstance(category, int) and (category in EMITTER_CATEGORY_RESERVED
                                      or category not in EMITTER_CATEGORY):
        found["emitter_category"] = category
    if "I021/140" in items:
        raw = int(items["I021/140"]["geometric_height_raw"])
        if raw == GEOMETRIC_HEIGHT_GREATER_THAN:
            found["geometric_height_greater_than_indication"] = raw
    for item in ("I021/074", "I021/076"):
        if item in items and int(items[item]["full_second_indication"]) == 3:
            # Reserved: no defined correction, and applying one of the other three would be a
            # guess with a nanosecond's worth of false authority on it.
            found[f"{item}_reserved_full_second_indication"] = items[item]
    sta = ((items.get("RE") or {}).get("items", {}) or {}).get("STA") or {}
    for element in ("reduced_capability", "reply_rate_limiting", "priority_status_v3",
                    "transmit_power", "transponder_side", "detect_and_avoid",
                    "df17_capability", "sense_vertical_horizontal", "cas_type_capability",
                    "transponder_antenna_offset"):
        if element in sta and not sta.get(f"{element}_populated"):
            # An Element Populated bit clear is NOT a value of zero.
            found[f"sta_{element}_not_populated"] = sta[element]
    return found


def _quality_basis(items: dict) -> str:
    """Which reading of I021/090's primary subfield applies — or that none could be established.

    The primary subfield holds "NUCr or NACv" and "NUCp or NIC", decided by the MOPS version in
    I021/210 — which is OPTIONAL. Guessing would report one scale's number under another's name.
    """
    version = (items.get("I021/210") or {}).get("mops_version")
    if not isinstance(version, int):
        return (
            "UNDETERMINED. I021/090's primary subfield holds 'NUCr or NACv' and 'NUCp or NIC', "
            "and which of each pair it is depends on the MOPS version in I021/210 — which this "
            "record does not carry. The bits are parked as read and NOT interpreted: NUCp and "
            "NIC are different scales, so naming one would report a number under the wrong "
            "quantity. Nothing here reaches Position.accuracy_m or Entity.confidence in either "
            "reading"
        )
    reading = ("NUCr / NUCp (ADS-B Version 0)" if version == 0
               else "NACv / NIC (ADS-B Version 1 or higher)")
    return (
        f"I021/210 states MOPS version {version} ({MOPS_VERSION.get(version, 'unknown')}), so "
        f"I021/090's primary subfield reads as {reading}. Every value in this item is a "
        "CATEGORY or a containment BOUND, so none of it reaches Position.accuracy_m — which is "
        "one horizontal 1-sigma figure in metres — or Entity.confidence, which is a confidence "
        "in the object's identity. PIC is the sharpest case: it states a bound in nautical "
        "miles and is still not a standard deviation"
    )


def _position_basis(items: dict) -> str | None:
    item = _position_item(items)
    if item is None:
        return None
    lsb = LSB_131_DEGREES if item == "I021/131" else LSB_130_DEGREES
    resolution = "at least 2 cm" if item == "I021/131" else "at least 2.4 m"
    both = "I021/130" in items and "I021/131" in items
    return (
        f"{item}, two's complement, LSB 180/2^{30 if item == 'I021/131' else 23} = {lsb:.16g} "
        f"degrees ({resolution}). WGS-84 already, so there is NO datum conversion and no "
        "ellipsoid to name — the only transform is the scaling, and it is exact in binary. The "
        "raw integers are re-emitted verbatim at attributes.cat021_position: the source "
        "coordinates are the record and this Position is a derived, one-way view of them"
        + (". Both I021/130 and I021/131 were present, which the encoding rule says cannot "
           "happen; the high-resolution item was read because it is strictly more precise, and "
           "both are parked" if both else "")
    )


def _position_disagreement(items: dict) -> float | None:
    """How far apart the two position items are, when a record carries both.

    A disagreement beyond one I021/130 LSB is more than rounding can explain, and it is the
    source's to explain rather than ours to average away.
    """
    if not ("I021/130" in items and "I021/131" in items):
        return None
    coarse = _coordinates(items, "I021/130")
    fine = _coordinates(items, "I021/131")
    apart = max(abs(coarse[0] - fine[0]), abs(coarse[1] - fine[1]))
    return round(apart, 10) if apart > LSB_130_DEGREES else None


def _attributes(record: dict, block: dict, consumed: Sequence[str], *,
                observed_basis: str) -> dict[str, Any]:
    """Everything about this target that is not a canonical field. Nones are dropped later."""
    items = record["items"]
    ref = items.get("RE") or {}
    ref_items = ref.get("items", {})
    sgv = ref_items.get("SGV") or {}
    sta = ref_items.get("STA") or {}
    mes = ref_items.get("MES") or {}
    descriptor = items.get("I021/040") or {}
    status = items.get("I021/200") or {}
    version = (items.get("I021/210") or {}).get("mops_version")
    category = (items.get("I021/020") or {}).get("emitter_category")
    atp = int(descriptor.get("address_type", ATP_ICAO))
    position_item = _position_item(items)
    identification = (items.get("I021/170") or {}).get("target_identification_raw")

    attributes: dict[str, Any] = {
        # ---- the block and record envelope, parked so egress can rebuild it exactly
        "cat021_block": dict(block),
        "cat021_record_index": record["index"],
        "cat021_fspec": record["fspec"],
        # The wire octets of every item, verbatim. This is the evidence an auditor asks for —
        # every decoded field is a claim ABOUT these octets — and it is what makes the round
        # trip byte-exact without a single declared transform.
        "cat021_items": dict(record["item_octets"]),

        # ---- identity
        "target_address": f"{items['I021/080']['target_address']:06X}",
        "address_type": ADDRESS_TYPE.get(atp, "reserved for future use"),
        "address_type_raw": atp,
        "identity_caveat": (
            "I021/040 states ATP 1, DUPLICATE ADDRESS: the ground station is saying this "
            "address is not unique on the wire, so this entity may conflate two airframes. The "
            "source id is filed under "
            f"{NONICAO_SYSTEM} so this contact cannot be fused with the genuine airframe, but "
            "two different aircraft sharing the duplicated address would still merge with each "
            "other. That cannot be resolved from one record and is stated rather than hidden"
            if atp == 1 else None),
        # gap 1 — and deliberately NOT attributes.callsign, the key TAK and adsb.py share. The
        # specification defines this as flight-plan identification OR registration marking with
        # no bit saying which, so that key would assert the first reading about half the time.
        "target_identification": (identification.rstrip() or None
                                  if isinstance(identification, str)
                                  and IDENTIFICATION_UNDEFINED not in identification else None),
        "target_identification_raw": identification,
        # Converging on adsb.py's key IS right here: a Mode 3/A code means one thing in both
        # formats, because it is the same transponder answering.
        "mode_a_code": (f"{(items['I021/070']['mode_3a_raw']):04o}"
                        if "I021/070" in items else None),
        "mode_a_code_raw": (items.get("I021/070") or {}).get("mode_3a_raw"),
        # Station-scoped and recycled, so NOT a SourceId.
        "track_number": (items.get("I021/161") or {}).get("track_number"),
        "emitter_category": category,
        "emitter_category_text": (EMITTER_CATEGORY.get(category)
                                  if isinstance(category, int) else None),

        # ---- the ground station, which is a SENSOR and not the target (gap 14)
        "data_source": ({"sac": items["I021/010"]["sac"], "sic": items["I021/010"]["sic"]}
                        if "I021/010" in items else None),
        "receiver_id": (items.get("I021/400") or {}).get("receiver_id"),
        "service_identification": (items.get("I021/015") or {}).get("service_identification"),
        "report_period_s": _report_period(items),

        # ---- the bases
        "affiliation_basis": _affiliation_basis(mes),
        "symbol_basis": "derived from affiliation; CAT021 states no symbol",
        "valid_from_basis": observed_basis,
        "entity_id_basis": f"I021/080 target address, filed under {_source_id_system(items)[0]}",
        "integrity_basis": (
            "ASTERIX carries NO checksum at any level — not on the data block, not on a record, "
            "not on an item — so unlike a 1090ES frame this record was not verified, it was "
            "PARSED. What it passed is a structural gate: LEN matched the buffer, the records "
            "tiled it exactly, every FSPEC bit named a defined FRN, every variable item "
            "terminated inside the record, and the four mandatory items were present. A single "
            "bit flipped inside a fixed-length field would satisfy all of that"),
        "position_basis": _position_basis(items),
        "position_source_basis": (
            "GNSS. A CAT021 position originated as the aircraft's own GNSS fix; the ground "
            "station CPR-decoded it upstream, which is why this adapter has no CPR decision to "
            "make and adsb.py does" if position_item else None),
        "position_disagreement_deg": _position_disagreement(items),
        "cat021_position": ({"item": position_item,
                             "latitude_raw": items[position_item]["latitude_raw"],
                             "longitude_raw": items[position_item]["longitude_raw"],
                             "lsb_deg": (LSB_131_DEGREES if position_item == "I021/131"
                                         else LSB_130_DEGREES)}
                            if position_item else None),
        "cat021_times": ({item: items[item]["time_of_day_raw"]
                          for item, _ in TIME_CHAIN if item in items} or None),
        "quality_basis": _quality_basis(items) if "I021/090" in items else None,

        # ---- altitude: one maps, one is gap 9
        "altitude_basis": _altitude_basis(items),
        # gap 9, parked in the SOURCE'S OWN UNIT. adsb.py parks the same concept at
        # attributes.baro_altitude_ft; converging on that key would repeat gap 1's mistake of
        # turning a private convention into a de-facto standard without an owner.
        "flight_level": (round(items["I021/145"]["flight_level_raw"] * 0.25, 2)
                         if "I021/145" in items else None),

        # ---- gap 7: heading, and CAT021 is the first source to state its datum
        "magnetic_heading_deg": (round(items["I021/152"]["magnetic_heading_raw"]
                                       * ANGLE_LSB_DEGREES, 6) if "I021/152" in items else None),
        "true_north_heading_deg": (round(ref_items["TNH"]["true_north_heading_raw"]
                                         * ANGLE_LSB_DEGREES, 6) if "TNH" in ref_items else None),
        "heading_reference": (HEADING_REFERENCE.get(int(sgv["heading_reference"]))
                              if "heading_reference" in sgv else None),
        "surface_angle_kind": (SGV_ANGLE_KIND.get(int(sgv["heading_track_is_ground_track"]))
                               if "heading_track_is_ground_track" in sgv else None),
        # gap 7's turn-rate half, in the source's own unit: degrees per SECOND, where AIS states
        # degrees per minute and the gap's proposal is named turn_rate_dpm.
        "track_angle_rate_deg_per_s": _track_angle_rate(items),
        "roll_angle_deg": (round(items["I021/230"]["roll_angle_raw"] * 0.01, 4)
                           if "I021/230" in items else None),

        # ---- gap 10: air-data speeds, three quantities in two items
        "airspeed_ias_kt": _airspeed_ias_kt(items),
        "airspeed_mach": _airspeed_mach(items),
        "airspeed_true_kt": (items["I021/151"]["true_airspeed_kt"]
                             if "I021/151" in items else None),
        "airspeed_true_at_or_above_maximum": (True if (items.get("I021/151") or {})
                                              .get("range_exceeded") else None),

        # ---- vertical rate: two measurements, and which was used
        "climb_basis": _climb_basis(items),
        "baro_vertical_rate_ft_min": (
            round(items["I021/155"]["vertical_rate_raw"] * VERTICAL_RATE_LSB_FEET_PER_MINUTE, 4)
            if "I021/155" in items else None),
        "geometric_vertical_rate_ft_min": (
            round(items["I021/157"]["vertical_rate_raw"] * VERTICAL_RATE_LSB_FEET_PER_MINUTE, 4)
            if "I021/157" in items else None),

        # ---- floors, which are not measurements
        "ground_speed_at_or_above_maximum": (True if (items.get("I021/160") or {})
                                             .get("range_exceeded") else None),
        "vertical_rate_at_or_above_maximum": _vertical_rate_floor(items),

        # ---- gap 15: intent
        "selected_altitude_ft": (items["I021/146"]["altitude_raw"] * 25
                                 if "I021/146" in items else None),
        "selected_altitude_source": (SELECTED_ALTITUDE_SOURCE.get(
            int(items["I021/146"]["source"])) if "I021/146" in items else None),
        "final_state_selected_altitude_ft": (items["I021/148"]["altitude_raw"] * 25
                                             if "I021/148" in items else None),
        "selected_heading_deg": (round(ref_items["SelH"]["selected_heading_raw"] * 0.703125, 6)
                                 if "SelH" in ref_items
                                 and ref_items["SelH"].get("selected_heading_valid") else None),

        # ---- gap 8: extent, as a BUCKET, and the offset reference point
        "aircraft_size_bucket": (items.get("I021/271") or {}).get("aircraft_size_bucket"),
        "aircraft_size_bounds": (AIRCRAFT_SIZE_BUCKET.get(
            int(items["I021/271"]["aircraft_size_bucket"]))
            if "aircraft_size_bucket" in (items.get("I021/271") or {}) else None),
        "gps_antenna_offset_m": ({
            "lateral": (_bits(int(ref_items["GAO"]["lateral_offset_raw"]), 2, 1)) * 2,
            "lateral_right_of_centreline": bool(
                int(ref_items["GAO"]["lateral_offset_raw"]) & 0b100),
            "longitudinal": int(ref_items["GAO"]["longitudinal_offset_raw"]) * 2,
        } if "GAO" in ref_items else None),

        # ---- the pressure setting, the other half of gap 9's bridge
        "barometric_pressure_setting_hpa": _pressure_setting(ref_items),

        # ---- the ground station's verdicts: parked, never re-decided, never a filter
        "confidence_level": (CONFIDENCE_LEVEL.get(int(descriptor["confidence_level"]))
                             if "confidence_level" in descriptor else None),
        "range_check_failed": (True if descriptor.get("range_check_failed") else None),
        "range_check_note": (
            "the specification's own note says an operational user will SUPPRESS a "
            "range-check-failed target. This adapter does not: filtering is a decision, and a "
            "decision made inside a translator is invisible in the CDM output and absent from "
            "the audit trail. The record is translated in full and the suppression belongs to a "
            "consumer where somebody can see it being made"
            if descriptor.get("range_check_failed") else None),
        "simulated_target": (True if descriptor.get("simulated_target") else None),
        "simulated_target_note": (
            "I021/040 states SIM, a simulated target. This does NOT rewrite source.synthetic, "
            "which is a deployment declaration about the FEED — a payload field may not flip it, "
            "exactly as a Legion EXERCISE_* affiliation may not"
            if descriptor.get("simulated_target") else None),
        "test_target": (True if descriptor.get("test_target") else None),
        "report_from_field_monitor": (True if descriptor.get("report_from_field_monitor")
                                      else None),
        "ground_bit_set": (True if descriptor.get("ground_bit_set") else None),
        "lnav_mode_engaged": _lnav(status),
        "mops_version": version,
        "mops_version_text": (MOPS_VERSION.get(version) if isinstance(version, int) else None),
        "link_technology": (LINK_TECHNOLOGY.get(int(items["I021/210"]["link_technology"]))
                            if "I021/210" in items else None),
        "priority_status_text": (PRIORITY_STATUS.get(int(status["priority_status"]))
                                 if "priority_status" in status else None),
        "surveillance_status_text": (SURVEILLANCE_STATUS.get(int(status["surveillance_status"]))
                                     if "surveillance_status" in status else None),
        "priority_status_v3_text": (PRIORITY_STATUS_V3.get(int(sta["priority_status_v3"]))
                                    if sta.get("priority_status_v3_populated") else None),
        "priority_status_v3_legacy_equivalent": (
            PRIORITY_STATUS_V3_TO_LEGACY.get(int(sta["priority_status_v3"]))
            if sta.get("priority_status_v3_populated") else None),
        "position_integrity_category_bound": (
            POSITION_INTEGRITY_CATEGORY.get(int(items["I021/090"]["position_integrity_category"]))
            if "position_integrity_category" in (items.get("I021/090") or {}) else None),

        # ---- the two absence lists, which are two facts and not one
        "unavailable_fields": _unavailable_fields(items) or None,
        "unresolved_raw": _unresolved_raw(items) or None,
        "source_extras": lossless.residual(record, consumed),
    }
    return attributes


def _affiliation_basis(mes: dict) -> str:
    summary = mes.get("mode_5_summary") or {}
    attested = bool(summary.get("authenticated_mode_5_id") or
                    summary.get("authenticated_mode_5_data"))
    base = (
        "UNKNOWN. Everything in a CAT021 target report except the ground station's own flags "
        "originated as an unauthenticated cooperative broadcast: it states an identity — a "
        "target identification, an emitter category, an address — with no integrity mechanism "
        "behind it, so reading one as an identification would be reading a spoofable claim"
    )
    if not attested:
        return base
    return (
        base + ". AND THIS RECORD CARRIES MORE THAN THAT. REF/MES subfield #1 states an "
        "AUTHENTICATED Mode 5 reply — the first cryptographically attested identity statement "
        "any source in this repository carries, and in IFF doctrine an authenticated Mode 5 "
        "reply is what 'friend' means. It is deliberately NOT read as FRIENDLY: that is an "
        "adjudication, which belongs to an IFF authority and not to a translator, and "
        "over-claiming FRIENDLY is the fratricide-adjacent direction. The bits are parked in "
        "full. The CDM has no way to say 'attested, not adjudicated' — see gap 2"
    )


def _altitude_basis(items: dict) -> str | None:
    geometric = "I021/140" in items
    barometric = "I021/145" in items
    if not (geometric or barometric):
        return None
    parts = []
    if geometric:
        raw = int(items["I021/140"]["geometric_height_raw"])
        if raw == GEOMETRIC_HEIGHT_GREATER_THAN:
            parts.append(
                "I021/140 carries the 'greater than' marker (0x7FFF), which names no bound — "
                "the item's stated range tops out at 150 000 ft and the note does not say the "
                "marker means above that. So alt_m is ABSENT and the raw is in unresolved_raw; "
                "reading the marker as a value would report 204 793.75 ft")
        else:
            parts.append(
                "Position.alt_m is I021/140 Geometric Height, feet to metres at LSB 6.25 ft. "
                "The item DEFINES its own reference surface — 'a plane tangent to the earth's "
                "ellipsoid, defined by WGS-84' — so this is a mapping and not an assertion, "
                "which is the half of gap 9's datum problem that adsb.py had to assert")
    if barometric:
        parts.append(
            "I021/145 Flight Level is a BAROMETRIC pressure altitude, not QNH corrected, and "
            "has no canonical home (gap 9). Parked at attributes.flight_level in FL, the "
            "source's own unit")
    return " ".join(parts)


def _climb_basis(items: dict) -> str | None:
    geometric = "I021/157" in items
    barometric = "I021/155" in items
    if not (geometric or barometric):
        return None
    if geometric and barometric:
        return ("both vertical rates are present and they are two different measurements. "
                "Kinematics.climb_mps is the GEOMETRIC one (I021/157), which is referenced to "
                "WGS-84 and therefore differentiates the same surface Position.alt_m is "
                "measured against; the barometric one is parked at "
                "attributes.baro_vertical_rate_ft_min")
    if geometric:
        return ("Kinematics.climb_mps is I021/157, the geometric vertical rate, referenced to "
                "WGS-84")
    return ("Kinematics.climb_mps is I021/155, the BAROMETRIC vertical rate — the only one this "
            "record carries. It is a rate of change of pressure altitude and not of height "
            "above the ellipsoid, and attributes.baro_vertical_rate_ft_min keeps the figure in "
            "its own unit beside it")


def _report_period(items: dict) -> float | str | None:
    """I021/016. 0 means DATA DRIVEN MODE, not a period of zero; 127.5 means "or above"."""
    if "I021/016" not in items:
        return None
    raw = int(items["I021/016"]["report_period_raw"])
    if raw == 0:
        return "data driven mode"
    return round(raw * 0.5, 1)


def _pressure_setting(ref_items: dict) -> float | str | None:
    """REF/BPS. The wire value is the setting MINUS 800 hPa, and both ends are floors."""
    if "BPS" not in ref_items:
        return None
    raw = int(ref_items["BPS"]["barometric_pressure_setting_raw"])
    if raw == 0:
        return "800 hPa or less"
    if raw == 0x0FFF:
        return "1209.5 hPa or more"
    return round(800.0 + raw * 0.1, 1)


def _track_angle_rate(items: dict) -> float | None:
    if "I021/165" not in items:
        return None
    value = int(items["I021/165"]["track_angle_rate_raw"]) * TRACK_ANGLE_RATE_LSB
    return round(value, 5)


def _airspeed_ias_kt(items: dict) -> float | None:
    """I021/150 with IM clear: indicated airspeed at LSB 2^-14 NM/s."""
    item = items.get("I021/150")
    if item is None or item.get("airspeed_is_mach"):
        return None
    return round(int(item["airspeed_raw"]) * GROUND_SPEED_LSB_NM_PER_S * 3600.0, 6)


def _airspeed_mach(items: dict) -> float | None:
    item = items.get("I021/150")
    if item is None or not item.get("airspeed_is_mach"):
        return None
    return round(int(item["airspeed_raw"]) * 0.001, 6)


def _vertical_rate_floor(items: dict) -> str | None:
    """The RE bit on a vertical rate, and the ambiguity it carries on a NEGATIVE value.

    The specification says the true value is "greater than" the one in the field. For a
    descending rate, greater in magnitude and greater in signed value are opposite claims, and
    it does not say which. The figure is kept with the floor recorded and is never re-signed.
    """
    for item in ("I021/157", "I021/155"):
        entry = items.get(item)
        if entry and entry.get("range_exceeded"):
            sign = "descending" if int(entry["vertical_rate_raw"]) < 0 else "climbing"
            return (
                f"{item} sets the Range Exceeded bit: the avionics could not downlink the true "
                f"value, so the figure is a FLOOR and not a rate. The aircraft is {sign}. Note "
                "the ambiguity for a negative value — 'greater' could mean greater in magnitude "
                "or greater in signed value and the specification does not say — so the figure "
                "is kept as sent and never re-signed"
            )
    return None


def _lnav(status: dict) -> bool | None:
    """I021/200's LNAV bit, with its documented inversion applied ONCE and recorded.

    The item's own note says the logic is reversed relative to ED-102/DO-260: 0 means engaged.
    The raw bit survives in source_extras; this is the reading, so a consumer does not have to
    know about the inversion to get it right.
    """
    if "lnav_mode_raw" not in status:
        return None
    return not int(status["lnav_mode_raw"])


# ----------------------------------------------------------------------- encoding

#: LEN is two octets, so a data block cannot exceed this. A Track too large for one block is
#: REFUSED with its sample count named rather than split across blocks: splitting is framing,
#: and framing belongs to the caller.
MAX_BLOCK_OCTETS = 0xFFFF


def _fspec_for(frns: Sequence[int]) -> bytes:
    """The shortest conforming FSPEC covering `frns`, with FX set on every octet but the last."""
    if not frns:
        raise ValueError("a record with no items has no FSPEC")
    octet_count = (max(frns) + 6) // 7
    octets = bytearray(octet_count)
    for frn in frns:
        index = (frn - 1) // 7
        position = (frn - 1) % 7
        octets[index] |= 1 << (7 - position)
    for index in range(octet_count - 1):
        octets[index] |= FX
    return bytes(octets)


def _e_010(sac: int, sic: int) -> bytes:
    return bytes((sac & 0xFF, sic & 0xFF))


def _e_040(address_type: int) -> bytes:
    """The primary subfield only, FX clear. Every other field defaults to its 0 meaning."""
    return bytes(((address_type & 0x07) << 5,))


def _e_080(address: int) -> bytes:
    return address.to_bytes(3, "big")


def _e_090() -> bytes:
    """The mandatory quality item for a synthesised record: all zero, FX clear.

    Zero is NUCp/NIC 0 and NUCr/NACv 0 — the standard's own "no integrity" reading. That is the
    honest encoding for an object whose accuracy nobody measured, and it is `adsb.py`'s NIC 0
    default argument: emitting a better category would assert a containment radius no one has.
    """
    return b"\x00"


def _e_time(instant: _dt.datetime) -> bytes:
    """A CDM instant -> a 1/128 s time of day. The DATE cannot travel; CAT021 states none."""
    instant = instant.astimezone(_dt.timezone.utc)
    midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds = (instant - midnight).total_seconds()
    return int(round(seconds / TIME_LSB_SECONDS)).to_bytes(3, "big")


def _e_131(latitude: float, longitude: float) -> bytes:
    """The HIGH-RESOLUTION item, for a synthesised record.

    Choosing the coarse item would discard resolution the CDM was holding — 2.4 m against 2 cm
    — which is a loss this direction has no reason to take.
    """
    def encode(value: float) -> bytes:
        units = int(round(value / LSB_131_DEGREES))
        return (units & 0xFFFFFFFF).to_bytes(4, "big")
    return encode(latitude) + encode(longitude)


def _e_140(alt_m: float) -> bytes:
    """Geometric height. An altitude outside the item's range is REFUSED, never clipped."""
    feet = alt_m / FEET_TO_METRES
    if not (-1500.0 <= feet <= 150000.0):
        raise ValueError(
            f"cannot encode altitude {alt_m} m ({feet:.1f} ft) into I021/140: the item's range "
            "is -1500 ft to 150000 ft. Refusing rather than clipping — a cruise level clipped "
            "to a range bound reads as a real altitude to every consumer"
        )
    units = int(round(feet / GEOMETRIC_HEIGHT_LSB_FEET))
    return (units & 0xFFFF).to_bytes(2, "big")


def _e_160(speed_mps: float, course_deg: float) -> bytes:
    speed_units = int(round(speed_mps / METRES_PER_NAUTICAL_MILE / GROUND_SPEED_LSB_NM_PER_S))
    if not 0 <= speed_units < (1 << 15):
        raise ValueError(
            f"cannot encode ground speed {speed_mps} m/s into I021/160: the item's range is "
            "0 to 2 NM/s. Refusing rather than wrapping the field"
        )
    angle_units = int(round((course_deg % 360.0) / ANGLE_LSB_DEGREES)) & 0xFFFF
    return ((speed_units << 16) | angle_units).to_bytes(4, "big")


def _e_157(climb_mps: float) -> bytes:
    units = int(round(climb_mps * 60.0 / FEET_TO_METRES / VERTICAL_RATE_LSB_FEET_PER_MINUTE))
    if not -(1 << 14) <= units < (1 << 14):
        raise ValueError(
            f"cannot encode vertical rate {climb_mps} m/s into I021/157: the field is fifteen "
            "bits of two's complement at 6.25 ft/min"
        )
    return (units & 0x7FFF).to_bytes(2, "big")


def _record_from_parked(attributes: dict) -> bytes:
    """Rebuild the exact record this object was parsed from, octet for octet.

    The FSPEC is re-emitted VERBATIM rather than recomputed. A conforming encoder emits the
    shortest FSPEC covering its highest set FRN, but the specification does not forbid a longer
    one, and the round trip is byte-exact only if what we emit is what we read.
    """
    fspec = bytes.fromhex(str(attributes["cat021_fspec"]))
    parked = attributes["cat021_items"]
    body = b"".join(bytes.fromhex(parked[item])
                    for _, item, _ in UAP if item and item in parked)
    return fspec + body


def _synthesised_record(*, station: tuple[int, int], address: int, address_type: int,
                        instant: _dt.datetime, position: Position | None,
                        kinematics: Kinematics | None) -> bytes:
    """A minimal conforming record for an object that never came from CAT021."""
    items: dict[int, bytes] = {
        1: _e_010(*station),
        2: _e_040(address_type),
        11: _e_080(address),
        17: _e_090(),
        5: _e_time(instant),
    }
    if position is not None:
        items[7] = _e_131(position.lat, position.lon)
        if position.alt_m is not None:
            items[16] = _e_140(position.alt_m)
    if kinematics is not None:
        if kinematics.speed_mps is not None and kinematics.course_deg is not None:
            items[26] = _e_160(kinematics.speed_mps, kinematics.course_deg)
        if kinematics.climb_mps is not None:
            items[25] = _e_157(kinematics.climb_mps)
    frns = sorted(items)
    return _fspec_for(frns) + b"".join(items[frn] for frn in frns)


def _render_block(records: Sequence[bytes]) -> bytes:
    """CAT, LEN and the records. LEN is COMPUTED and never copied."""
    body = b"".join(records)
    length = BLOCK_HEADER_OCTETS + len(body)
    if length > MAX_BLOCK_OCTETS:
        raise ValueError(
            f"the records total {length} octets and an ASTERIX data block's LEN field is two "
            f"octets, so a block cannot exceed {MAX_BLOCK_OCTETS}. Refusing rather than "
            "splitting across blocks: splitting is framing, and framing belongs to the caller"
        )
    return bytes((CATEGORY,)) + length.to_bytes(2, "big") + body


class AsterixCat021Adapter(Adapter):
    """CAT021 data blocks in, CDM out; an Entity or a Track out to a CAT021 data block."""

    name = "cat021"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: EMPTY, and that is a claim rather than an oversight.
    #:
    #: A declared transform is an EXEMPTION from the never-drop check — a hole with a reason
    #: attached — and this adapter needs none. Every wire value is parked verbatim as well as
    #: converted: the octets of every item at `attributes.cat021_items`, the position's raw
    #: integers at `attributes.cat021_position`, the raw 1/128 s counts at
    #: `attributes.cat021_times`, and every decoded field this adapter did not rename at
    #: `attributes.source_extras`. So `lossless.unrepresented()` runs at full strength over
    #: every fixture with nothing excused, which is the Legion argument — a verbatim copy is not
    #: a hole, an exemption is.
    #:
    #: There is a second, structural reason it could not be used here even if it were wanted:
    #: TRANSFORMS matches dotted paths, and this adapter's parsed form has an ARRAY of records
    #: at its root, so any path a declaration could name is either per-record-index (and
    #: therefore unmatchable in general) or the whole `records` subtree (and therefore an
    #: exemption for everything). A format that carries N reports per payload cannot use a
    #: per-field escape hatch, which is worth knowing before the next multi-record adapter.
    TRANSFORMS: dict[str, str] = {}

    #: Dotted paths in a parsed RECORD that this adapter re-emits under a name of its own.
    #: Everything else — the whole decoded `items` tree — is collected by `lossless.residual()`
    #: and parked with its structure intact at `attributes.source_extras`.
    #:
    #: Deliberately short. `adsb.py` consumes each field it maps; here the decoded values are
    #: parked wholesale and the canonical fields are additions on top, so consuming a mapped
    #: field would DELETE the evidence rather than move it.
    CONSUMED = ("index", "fspec", "item_octets")

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 station: tuple[int, int] | None = None) -> None:
        """`station` is the (SAC, SIC) this adapter emits as, or None.

        CONFIGURATION and not state, exactly like `adsb.py`'s reference position and the
        injected clock: a constant of the deployment, supplied here, never accumulated from the
        data stream. It is needed because I021/010 is mandatory in every record and names a
        GROUND STATION whose System Area Code EUROCONTROL allocates centrally — so a SAC/SIC
        this adapter invented would claim an identity somebody else holds.

        None is the default, and therefore the default behaviour is the conservative one: an
        object that did not come from CAT021 cannot be emitted at all. An object that DID came
        with its station's codes parked, and those are restored rather than replaced.
        """
        super().__init__(clock, synthetic=synthetic)
        if station is not None:
            sac, sic = station
            if not (0 <= sac <= 0xFF and 0 <= sic <= 0xFF):
                raise ValueError(
                    f"station {station} is not a (SAC, SIC) pair of octets. Both are one octet "
                    "each and both are stamped into every record this adapter emits"
                )
            station = (int(sac), int(sic))
        self._station = station

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One data block -> [Entity, Event] per record, in block order.

        Several records in one block are several TARGET REPORTS, not one target's history: they
        may name several aircraft and nothing in the format says otherwise. They are all
        translated because they arrived in one payload — the line `ais.py` draws when it
        reassembles the fragments present in one payload while refusing to buffer across them.

        `adsb.py` refuses a payload holding two frames, and that reasoning does NOT transfer: it
        refuses because accepting a pair would smuggle a CPR global decode in through the
        framing, and a CAT021 record carries a position the ground station already decoded. There
        is no join left for two records to smuggle.
        """
        parsed = self._as_parsed(raw)
        records = parsed.get("records")
        if not isinstance(records, list) or not records:
            raise Cat021ParseError(
                "CAT021 payload holds no records — refusing to translate; top-level keys: "
                f"{sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__}"
            )
        block = parsed.get("block") or {}
        received_at = self.now()
        source = self.source_ref()

        objects: list[CDMBase] = []
        for record in records:
            objects += self._record_to_cdm(record, block, source, received_at)
        return objects

    def _record_to_cdm(self, record: dict, block: dict, source, received_at) -> list[CDMBase]:
        items = record["items"]
        address = int(items["I021/080"]["target_address"])
        external_id = f"{address:06X}"
        id_system, _ = _source_id_system(items)

        observed_at, observed_basis = _observed_at(items, received_at)
        entity_id = ids.derive(id_system, external_id, kind="entity")
        # Keyed on BOTH, for the reason the CoT, AIS and ADS-B adapters give: an address
        # identifies the airframe and repeats on every report, so an id keyed on it alone would
        # collapse a whole flight into one event.
        event_id = ids.derive(id_system, f"{external_id}@{times.render(observed_at)}",
                              kind="event")

        emergency, emergency_note = _emergency(items)
        attributes = _attributes(record, block, self.CONSUMED, observed_basis=observed_basis)
        position = _position(items)
        kinematics = _kinematics(items)

        entity = Entity(
            source=source,
            entity_id=entity_id,
            source_ids=[{"system": id_system, "external_id": external_id}],
            entity_type=_entity_type(items),
            affiliation=Affiliation.UNKNOWN,
            symbol=sidc_from_affiliation(Affiliation.UNKNOWN, synthetic=self._synthetic),
            position=position,
            kinematics=kinematics,
            valid_from=observed_at,
            # CAT021 has no staleness field. I021/295 states how old data IS — a measurement
            # backwards — and not when it ceases to be good, which is a judgement about data and
            # therefore fusion's.
            valid_to=None,
            # The quality indicators are position accuracy and integrity CATEGORIES, and
            # I021/040's "report suspect" is a data-quality flag. Neither is a confidence in the
            # object's identity, which is what this field means.
            confidence=None,
            attributes={k: v for k, v in attributes.items() if v is not None},
        )

        states_motion = kinematics is not None
        event = Event(
            source=source,
            source_ids=[{"system": id_system, "external_id": external_id}],
            event_id=event_id,
            event_type=(EventType.ALERT if emergency else
                        EventType.TRACK_UPDATE if (position is not None or states_motion)
                        else EventType.STATUS_CHANGE),
            severity=Severity.CRITICAL if emergency else Severity.INFO,
            related_entities=[entity_id],
            # No geometry. A record states one position and it belongs to the target; copying it
            # onto the event would be a second representation of one measurement. And the
            # trajectory intent points are NOT a geometry either — see gap 15.
            geometry=None,
            payload={
                "cat021_record_index": record["index"],
                "cat021_record_count": block.get("record_count"),
                "observed_at_basis": observed_basis,
                "received_at_basis": (
                    "the injected clock. CAT021 states seven times and not one of them is ours: "
                    "I021/073 and I021/075 are receipt instants at the GROUND STATION, which is "
                    "a different party, and I021/077 is when it transmitted the report"),
                "event_id_basis": "I021/080 target address + observed_at",
                "severity_basis": emergency_note,
            },
            observed_at=observed_at,
            received_at=received_at,
        )
        return [entity, event]

    def _as_parsed(self, raw: bytes | dict) -> dict:
        """Raw octets -> the parsed form; a dict passes straight through.

        The `bytes | dict` shape `adsb.py` accepts, for the same reason: the harness's lossless
        check has no leaf structure to harvest from bytes, so every fixture ships a parsed twin
        and the twin has to be replayable through this same entry point.
        """
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray)):
            return _parse_block(bytes(raw))
        raise Cat021ParseError(
            f"CAT021 payload is a {type(raw).__name__}; this adapter reads the octets of one "
            "ASTERIX data block, or the parsed dict a fixture twin holds"
        )

    # ------------------------------------------------------------------- egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """Entities, or one Track, -> the CAT021 data block that restates them.

        MANY Entities are accepted and become many records in ONE block. That is not a join and
        not a widening of the contract: a data block holds N records by construction, the caller
        handed these over together, and it is what makes the round-trip claim in
        FORMAT_COVERAGE.md true of a BLOCK rather than only of a record — a two-record block
        ingested and re-emitted must come back octet for octet.

        A Track becomes ONE block of N records — the shape this format has for a history, and
        the shape 1090ES did not have, which is why `adsb.py` emits a stream of separate frames
        instead. Each sample's own time of day travels; the DATE does not, because CAT021 states
        none. A receiver dates each record against its own midnight, which is right in normal
        operation and wrong for a replay of an old track. Stated rather than worked around.
        """
        tracks = [o for o in objects if isinstance(o, Track)]
        entities = [o for o in objects if isinstance(o, Entity)]
        if len(tracks) > 1 or (tracks and entities and len(entities) > 1):
            kinds = [getattr(o, "object_kind", type(o).__name__) for o in objects]
            raise ValueError(
                f"from_cdm() emits ONE data block and was given {len(tracks)} tracks and "
                f"{len(entities)} entities (kinds: {kinds or 'none'}). A block holds many "
                "records, so many Entities are fine — but a history and a set of separate "
                "reports are two different shapes and cannot share one block."
            )
        if tracks:
            return _render_block(
                self._track_records(tracks[0], entities[0] if entities else None))
        if not entities:
            kinds = [getattr(o, "object_kind", type(o).__name__) for o in objects]
            raise ValueError(
                f"from_cdm() was given nothing emittable (kinds: {kinds or 'none'}). An Event "
                "alone is not emittable: a CAT021 record is both the object and the report "
                "about it."
            )
        # MANY Entities become MANY RECORDS IN ONE BLOCK, which is what a data block is for and
        # what `adsb.py` could not do — 1090ES has no container above a frame. The order is the
        # block order they were parsed from where every Entity carries one, so a block this
        # adapter ingested is reproduced octet for octet rather than merely field for field;
        # otherwise it is the caller's own order, which is the caller's decision to have made.
        indices = [e.attributes.get("cat021_record_index") for e in entities]
        if all(isinstance(index, int) for index in indices):
            entities = [e for _, e in sorted(zip(indices, entities), key=lambda pair: pair[0])]
        return _render_block([self._entity_record(entity) for entity in entities])

    def _entity_record(self, entity: Entity) -> bytes:
        """The record this Entity arrived as, or the record a ground station would emit."""
        attributes = entity.attributes or {}
        if attributes.get("cat021_items") and attributes.get("cat021_fspec"):
            return _record_from_parked(attributes)
        return _synthesised_record(
            station=self._require_station(entity),
            address=self._require_address(entity),
            address_type=self._address_type(entity),
            instant=entity.valid_from,
            position=entity.position,
            kinematics=entity.kinematics,
        )

    def _track_records(self, track: Track, entity: Entity | None) -> list[bytes]:
        """One record per sample, in the track's own order, inside one block."""
        station = self._require_station(track)
        address = self._require_address(track)
        address_type = self._address_type(track)
        return [
            _synthesised_record(
                station=station, address=address, address_type=address_type,
                instant=sample.observed_at, position=sample.position,
                kinematics=entity.kinematics if entity is not None else None,
            )
            for sample in track.samples
        ]

    def _require_station(self, obj: CDMBase) -> tuple[int, int]:
        parked = (getattr(obj, "attributes", None) or {}).get("data_source")
        if isinstance(parked, dict) and "sac" in parked and "sic" in parked:
            return int(parked["sac"]), int(parked["sic"])
        if self._station is None:
            raise ValueError(
                "cannot emit CAT021 for an object that did not come from CAT021: I021/010 is "
                "mandatory in every record and names a ground station whose System Area Code "
                "EUROCONTROL allocates centrally. Construct the adapter with "
                "AsterixCat021Adapter(station=(sac, sic)) — a SAC/SIC invented here would claim "
                "an identity somebody else holds, which is the same refusal adsb.py makes about "
                "deriving an ICAO address"
            )
        return self._station

    @staticmethod
    def _require_address(obj: CDMBase) -> int:
        for entry in obj.source_ids:
            if entry.system in (ICAO_SYSTEM, NONICAO_SYSTEM):
                return int(entry.external_id, 16)
        systems = [entry.system for entry in obj.source_ids]
        raise ValueError(
            f"cannot emit CAT021 for {getattr(obj, 'entity_id', None) or obj}: it carries no "
            f"{ICAO_SYSTEM} or {NONICAO_SYSTEM} source id (systems present: {systems}). "
            "I021/080 is mandatory in every record, and deriving a target address would put an "
            "aircraft into a surveillance picture under a number nobody allocated"
        )

    @staticmethod
    def _address_type(obj: CDMBase) -> int:
        parked = (getattr(obj, "attributes", None) or {}).get("address_type_raw")
        if isinstance(parked, int):
            return parked
        systems = [entry.system for entry in obj.source_ids]
        # An address filed under the non-ICAO pool must not be re-emitted as ATP 0: that would
        # tell every downstream system the number IS an ICAO24 address, which is the join hazard
        # the pool exists to prevent. ATP 3, anonymous, is the honest encoding.
        return ATP_ICAO if ICAO_SYSTEM in systems else 3
