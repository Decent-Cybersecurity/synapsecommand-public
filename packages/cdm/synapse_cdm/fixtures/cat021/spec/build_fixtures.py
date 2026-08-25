"""Builds every CAT021 fixture, from field values, with the arithmetic worked out in comments.

WHY THE GENERATOR IS THE REVIEWABLE FORM
-----------------------------------------
An ASTERIX data block is raw octets and cannot carry a comment, and unlike an ADS-B frame it
cannot be built from its parsed twin either: a record's FSPEC and its block's LEN are both
FUNCTIONS of the contents, so a hand-edited byte file is a mis-parse waiting to happen and a
hand-edited twin would not tell you what octets it implies.

So this file is the source of truth for both artefacts. Each fixture names its items, states
each field in the units the specification talks in, and shows the arithmetic that turns it into
octets. Running this module writes `<name>.cat021` (the octets) and `<name>.parsed.json` (what
the adapter's own parser produces from them, which is what the harness measures the never-drop
rule against).

    python -m synapse_cdm.fixtures.cat021.spec.build_fixtures      # from the package root
    python build_fixtures.py                      # from the directory this file is in

It lives in `spec/` rather than beside the payloads for the reason the Legion pin does:
`harness.run()` replays every FILE in a fixture directory through `to_cdm()`, so a module
sitting next to the blocks would be fed to the adapter and fail as an unrecognised payload.
Subdirectories are skipped, which is also why `refusals/` and `egress/` are subdirectories.

EVERYTHING HERE IS SYNTHETIC
----------------------------
No recorded ASTERIX traffic, no real ground station, no real aircraft.

  Target addresses  0029xx — the ADS-B fixtures' block. The ICAO allocation table's lowest
                    state block begins at 004000, so everything below it is in no
                    administration's range. Reused deliberately: `icao24_shared_with_adsb`
                    carries 0029C1, the SAME address as the ADS-B set's Gulf of Riga fixture,
                    so the two adapters derive the SAME entity_id without coordinating.
  SAC / SIC         0x29 / 0x29 — PINNED, see spec/sac_pin.json. The retrieved EUROCONTROL
                    allocation tables list SAC 0x29 with an explicitly empty country cell in
                    the EUR table and nowhere else. (0xFE, this row set's first proposal, is
                    Nicaragua.) SIC is operator-assigned within a SAC, so it carries no
                    allocation claim of its own and inherits the SAC's.
  Identifications   EXRCS01, EXHELO2, EXMAST1 — fictional, marked as exercise traffic.
  Mode 3/A          ordinary codes. 7500, 7600 and 7700 are the hijack, radio-failure and
                    emergency codes and are deliberately absent: an emergency in this set is
                    declared through I021/200 and REF/STA, which is where CAT021 carries one.
  Positions         the Gulf of Riga, west of Saaremaa, Ventspils and the Riga apron.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
FIXTURES = HERE.parent.parent
sys.path.insert(0, str(FIXTURES.parents[2]))

from synapse_cdm.adapters import asterix_cat021 as cat021          # noqa: E402

SAC, SIC = 0x29, 0x29

# --------------------------------------------------------------------- field helpers


def u(value: int, octets: int) -> bytes:
    return int(value).to_bytes(octets, "big")


def signed(value: int, octets: int) -> bytes:
    return int(value).to_bytes(octets, "big", signed=True)


def tod(hours: int, minutes: int, seconds: float) -> bytes:
    """A time of day at LSB 1/128 s, three octets.

    06:11:20.000 -> 22280 s -> 22280 x 128 = 2 851 840 units -> 0x2B8000.
    """
    units = int(round((hours * 3600 + minutes * 60 + seconds) / cat021.TIME_LSB_SECONDS))
    assert units < (1 << 24), units
    return u(units, 3)


def latlon_131(latitude: float, longitude: float) -> bytes:
    """I021/131: two 32-bit two's complement values at LSB 180/2^30 deg (about 2 cm).

    57.5981 / (180/2^30) = 57.5981 x 5 965 232.355... = 343 601 000 (rounded).
    """
    def one(value: float) -> bytes:
        return signed(int(round(value / cat021.LSB_131_DEGREES)), 4)
    return one(latitude) + one(longitude)


def latlon_130(latitude: float, longitude: float) -> bytes:
    """I021/130: two 24-bit two's complement values at LSB 180/2^23 deg (about 2.4 m)."""
    def one(value: float) -> bytes:
        return signed(int(round(value / cat021.LSB_130_DEGREES)), 3)
    return one(latitude) + one(longitude)


def identification(text: str) -> bytes:
    """Eight characters at six bits each, ICAO Annex 10 Vol. IV Table 3-8.

    'EXRCS01 ' -> E=5, X=24, R=18, C=3, S=19, 0=48, 1=49, space=32, packed MSB-first into
    48 bits. The same alphabet a 1090ES type code 1-4 frame uses, which is the whole point of
    the divergence note: it is the same field, not a similar one.
    """
    text = text.ljust(8)[:8]
    value = 0
    for character in text:
        value = (value << 6) | cat021.IDENTIFICATION_ALPHABET.index(character)
    return u(value, 6)


def geometric_height(feet: float) -> bytes:
    """I021/140 at LSB 6.25 ft. 7 600 ft / 6.25 = 1216 -> 0x04C0."""
    return signed(int(round(feet / cat021.GEOMETRIC_HEIGHT_LSB_FEET)), 2)


def flight_level(level: float) -> bytes:
    """I021/145 at LSB 1/4 FL. FL 250 -> 1000 -> 0x03E8."""
    return signed(int(round(level * 4)), 2)


def ground_vector(knots: float, track_deg: float, range_exceeded: bool = False) -> bytes:
    """I021/160: 15 bits of ground speed at LSB 2^-14 NM/s, then 16 bits of track angle.

    440 kt = 440/3600 NM/s = 0.12222 NM/s; / 2^-14 = 2002.6 -> 2003 units.
    Track 118.0 deg / (360/2^16) = 118 x 182.0444 = 21481 units.
    """
    speed_units = int(round(knots / 3600.0 / cat021.GROUND_SPEED_LSB_NM_PER_S))
    angle_units = int(round((track_deg % 360.0) / cat021.ANGLE_LSB_DEGREES)) & 0xFFFF
    assert speed_units < (1 << 15), speed_units
    return u(((1 << 31) if range_exceeded else 0) | (speed_units << 16) | angle_units, 4)


def vertical_rate(feet_per_minute: float, range_exceeded: bool = False) -> bytes:
    """I021/155 / I021/157: RE bit, then 15 bits of two's complement at LSB 6.25 ft/min.

    -1 200 ft/min / 6.25 = -192 -> 0x7F40 in fifteen bits.
    """
    units = int(round(feet_per_minute / cat021.VERTICAL_RATE_LSB_FEET_PER_MINUTE))
    return u(((1 << 15) if range_exceeded else 0) | (units & 0x7FFF), 2)


def angle_16(degrees: float) -> bytes:
    """I021/152 and REF/TNH at LSB 360/2^16 deg. 070.0 deg -> 12743 units."""
    return u(int(round((degrees % 360.0) / cat021.ANGLE_LSB_DEGREES)) & 0xFFFF, 2)


def mode_3a(octal: str, spare: int = 0) -> bytes:
    """I021/070: four octal digits in bits 12/1. Bits 16/13 are spare and settable."""
    return u((spare << 12) | int(octal, 8), 2)


def descriptor(*, atp: int = 0, arc: int = 0, rc: int = 0, rab: int = 0,
               ext1: int | None = None, ext2: int | None = None) -> bytes:
    """I021/040, primary plus optional extensions, FX chained."""
    primary = (atp << 5) | (arc << 3) | (rc << 2) | (rab << 1)
    if ext1 is None and ext2 is None:
        return u(primary, 1)
    if ext2 is None:
        return u(primary | 1, 1) + u(ext1, 1)
    return u(primary | 1, 1) + u(ext1 | 1, 1) + u(ext2, 1)


def quality(primary: int, *extensions: int) -> bytes:
    """I021/090, FX chained. Every value in it is a category or a bound; none becomes canonical."""
    if not extensions:
        return u(primary, 1)
    octets = [primary | 1]
    for index, extension in enumerate(extensions):
        last = index == len(extensions) - 1
        octets.append(extension if last else extension | 1)
    return bytes(octets)


def target_status(*, icf: int = 0, lnav_raw: int = 1, me: int = 0, ps: int = 0,
                  ss: int = 0) -> bytes:
    """I021/200. Note lnav_raw: the item's own logic is REVERSED, so 1 means NOT engaged."""
    return u((icf << 7) | (lnav_raw << 6) | (me << 5) | (ps << 2) | ss, 1)


def mops(version: int, *, link: int = 2, vns: int = 0) -> bytes:
    """I021/210: VNS bit 7, VN bits 6/4, LTT bits 3/1. LTT 2 is 1090 ES."""
    return u((vns << 6) | (version << 3) | link, 1)


def data_ages(**ages: float) -> bytes:
    """I021/295: a presence map of up to four octets, then one octet per age at LSB 0.1 s."""
    names = [name for name, _ in cat021.DATA_AGE_SUBFIELDS]
    present = sorted((names.index(name) for name in ages), reverse=False)
    octet_count = (max(present) // 7) + 1
    primary = bytearray(octet_count)
    for index in present:
        primary[index // 7] |= 1 << (7 - (index % 7))
    for i in range(octet_count - 1):
        primary[i] |= 1
    body = bytes(int(round(ages[names[index]] / cat021.AGE_LSB_SECONDS)) for index in present)
    return bytes(primary) + body


def ref(**items: bytes) -> bytes:
    """The Reserved Expansion Field: its own length octet (counting itself), then an items
    indicator, then the present items in bit order BPS, SelH, NAV, GAO, SGV, STA, TNH, MES."""
    indicator = 0
    body = b""
    for index, name in enumerate(cat021.REF_ITEMS):
        if name in items:
            indicator |= 1 << (7 - index)
            body += items[name]
    return u(len(body) + 2, 1) + u(indicator, 1) + body


def sgv(*, stopped: int, valid: int, is_ground_track: int, hrd: int, knots: float,
        angle_deg: float | None) -> bytes:
    """REF/SGV: a two-octet primary with FX in bit 1 of the SECOND octet, then extensions.

    12.0 kt / 0.125 = 96 units. Ground track 235.0 deg / 2.8125 = 83.6 -> 84 units.
    """
    speed_units = int(round(knots / 0.125))
    primary = ((stopped << 15) | (valid << 14) | (is_ground_track << 13) | (hrd << 12)
               | (speed_units << 1))
    if angle_deg is None:
        return u(primary, 2)
    extension = (int(round((angle_deg % 360.0) / 2.8125)) & 0x7F) << 1
    return u(primary | 1, 2) + u(extension, 1)


def sta(*, es: int = 0, uat: int = 0, ps3: int | None = None) -> bytes:
    """REF/STA. PS3 lives in the FIRST EXTENSION and carries an Element Populated bit."""
    primary = (es << 7) | (uat << 6)
    if ps3 is None:
        return u(primary, 1)
    return u(primary | 1, 1) + u((1 << 7) | (ps3 << 4), 1)


def mes_summary(*, m5: int = 0, authenticated_id: int = 0, authenticated_data: int = 0,
                position_from_mode_5: int = 0) -> bytes:
    """REF/MES with subfield #1 only: the Mode 5 summary bits."""
    summary = ((m5 << 7) | (authenticated_id << 6) | (authenticated_data << 5)
               | position_from_mode_5)
    return u(1 << 7, 1) + u(summary, 1)


def trajectory_point(*, tcp: int, altitude_ft: float, latitude: float, longitude: float,
                     point_type: int, time_over_point_s: int) -> bytes:
    """One fifteen-octet trajectory intent point. Altitude LSB 10 ft, lat/lon LSB 180/2^23."""
    # Bit numbers are the specification's — bits high..low — so a field whose lowest bit is
    # `low` is shifted by `low - 1`. Getting that off by one shifts every field after it and
    # still produces a well-formed record, which is exactly why the two-point fixture exists.
    value = tcp << 112                                             # bits 118/113
    value |= (int(round(altitude_ft / 10)) & 0xFFFF) << 96         # bits 112/97,  LSB 10 ft
    value |= (int(round(latitude / cat021.LSB_130_DEGREES)) & 0xFFFFFF) << 72     # bits 96/73
    value |= (int(round(longitude / cat021.LSB_130_DEGREES)) & 0xFFFFFF) << 48    # bits 72/49
    value |= point_type << 44                                      # bits 48/45
    value |= time_over_point_s << 16                               # bits 40/17, LSB 1 s
    return u(value, 15)


def record(items: dict[int, bytes]) -> bytes:
    """FSPEC computed from the FRNs present, then the items in FRN order."""
    frns = sorted(items)
    return cat021._fspec_for(frns) + b"".join(items[frn] for frn in frns)


def block(*records: bytes) -> bytes:
    return cat021._render_block(records)


# --------------------------------------------------------------------- the fixtures
#
# The FRN of each item, from the Edition 2.6 UAP, is written next to it — that is what the FSPEC
# encodes, and reading a record means reading FRNs in order.
#
#   1 I021/010   2 I021/040   3 I021/161   5 I021/071   6 I021/130   7 I021/131
#   8 I021/072  11 I021/080  12 I021/073  13 I021/074  16 I021/140  17 I021/090
#  18 I021/210  19 I021/070  21 I021/145  22 I021/152  23 I021/200  24 I021/155
#  25 I021/157  26 I021/160  27 I021/165  28 I021/077  29 I021/170  30 I021/020
#  32 I021/146  34 I021/110  37 I021/271  41 I021/400  42 I021/295  48 RE  49 SP

MANDATORY_ONLY = {
    1: u((SAC << 8) | SIC, 2),      # I021/010 data source: SAC 0x29, SIC 0x29 — see sac_pin.json
    2: descriptor(atp=0),          # I021/040 ATP 0: a 24-bit ICAO address
    11: u(0x0029C1, 3),            # I021/080 target address
    17: quality(0x00),             # I021/090 all-zero: NUCp/NIC 0, the "no integrity" reading
}


def fixtures() -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # ---------------------------------------------------------------- the ordinary case
    #
    # EXRCS01, airborne over the Gulf of Riga at 06:11:20.000 UTC, FL 250 by the altimeter and
    # 7 600 ft geometrically, making 440 kt on track 118 degrees true.
    #
    #   I021/071  06:11:20.000 -> 22 280 s -> x128 = 2 851 840 units -> 0x2B8000
    #   I021/131  57.5981 N -> /(180/2^30) ->  343 601 022 -> 0x147B8C9E (approx.)
    #             23.8412 E ->               142 219 264
    #   I021/140  7 600 ft / 6.25 = 1216 -> 0x04C0 ; -> 2 316.48 m in Position.alt_m
    #   I021/145  FL 250 x 4 = 1000 -> 0x03E8 ; parked as attributes.flight_level = 250.0 (gap 9)
    #   I021/160  440 kt -> 2003 units ; track 118.0 deg -> 21 481 units
    #   I021/157  +1 200 ft/min -> +192 units -> Kinematics.climb_mps = +6.096
    out["airborne_position_time_of_applicability"] = block(record({
        **MANDATORY_ONLY,
        5: tod(6, 11, 20.0),                       # I021/071 time of applicability, position
        7: latlon_131(57.5981, 23.8412),           # I021/131 high-resolution position
        16: geometric_height(7600),                # I021/140 geometric height (maps to alt_m)
        18: mops(2),                               # I021/210 MOPS version 2 — how to read /090
        19: mode_3a("4271"),                       # I021/070 Mode 3/A, an ordinary code
        21: flight_level(250),                     # I021/145 flight level (gap 9)
        26: ground_vector(440.0, 118.0),           # I021/160 airborne ground vector
        25: vertical_rate(1200),                   # I021/157 geometric vertical rate
        29: identification("EXRCS01"),             # I021/170 -> attributes.target_identification
        30: u(3, 1),                               # I021/020 emitter category 3, medium a/c
        41: u(0x07, 1),                            # I021/400 receiver id
    }))

    # ---------------------------------------------------------------- both position items
    #
    # The encoding rule says either I021/130 or I021/131 is sent, never both. A non-conforming
    # encoder can set both FSPEC bits, so the case has to have an answer: the high-resolution
    # item wins, both are parked, and a disagreement beyond one coarse LSB is recorded.
    # Here they agree to within rounding, so position_disagreement_deg must be ABSENT.
    out["airborne_position_coarse_and_high_resolution"] = block(record({
        **MANDATORY_ONLY,
        5: tod(6, 11, 22.0),
        6: latlon_130(57.5981, 23.8412),           # I021/130 coarse, 2.4 m
        7: latlon_131(57.5981, 23.8412),           # I021/131 fine, 2 cm — this one is read
        18: mops(2),
    }))

    # -------------------------------------------------- high-precision reception time, FSI = 1
    #
    # I021/073 says 06:11:23.units; I021/074's FSI = 01 means the whole seconds are I021/073's
    # PLUS ONE. An adapter ignoring FSI would be a full second early here.
    #
    #   I021/073  06:11:23.000 -> 22 283 s -> 2 852 224 units
    #   I021/074  FSI = 01, fraction 0.25 s -> 0.25 x 2^30 = 268 435 456
    #             resolved: whole 22 283 + 1 = 22 284, + 0.25 -> 06:11:24.250
    out["position_time_of_message_reception_high_precision"] = block(record({
        **MANDATORY_ONLY,
        12: tod(6, 11, 23.0),                                  # I021/073
        13: u((0b01 << 30) | 268435456, 4),                    # I021/074 FSI = 1, +0.25 s
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
    }))

    # ------------------------------------------------------------ reserved FSI, which is 0b11
    #
    # There is no defined correction for FSI = 3, and applying one of the other three would be a
    # guess with a nanosecond's worth of false authority on it. The high-precision value goes to
    # unresolved_raw and the plain I021/073 is used: 06:11:23.000 exactly.
    out["reserved_full_second_indication"] = block(record({
        **MANDATORY_ONLY,
        12: tod(6, 11, 23.0),
        13: u((0b11 << 30) | 268435456, 4),                    # I021/074 FSI = 3, reserved
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
    }))

    # ------------------------------------------------------------------ midnight, backwards
    #
    # Stated 23:59:58.500. The test clock is 00:00:01.100 on the FOLLOWING day, so the nearest
    # candidate is the previous day's — 2.6 s back rather than 86 397.4 s forward.
    out["midnight_rollover_before"] = block(record({
        **MANDATORY_ONLY,
        5: tod(23, 59, 58.5),
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
    }))

    # ------------------------------------------------------------------- midnight, forwards
    #
    # Stated 00:00:00.875 with the clock at 23:59:59.700 — a ground station clock a fraction
    # ahead of ours. The nearest candidate is the NEXT day's, 1.175 s forward. The same rule,
    # which is why there is no special case to get backwards.
    #
    # 0.875 s is EXACTLY 112 units of 1/128 s, chosen so the fixture states a time the format
    # can represent. 0.9 s would quantise to 115 units = 0.8984375 s, which is the format
    # behaving correctly and would make this fixture read as if the rollover were approximate.
    out["midnight_rollover_after"] = block(record({
        **MANDATORY_ONLY,
        5: tod(0, 0, 0.875),
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
    }))

    # ------------------------------------------------- a surface vehicle, motion only in the REF
    #
    # ATP 2, a surface vehicle address -> ADSB_NONICAO, because filing a vehicle address under
    # ICAO24 would let fusion join it to a real airframe sharing the number. GBS set. I021/160 is
    # the AIRBORNE ground vector and is absent; the motion is in REF/SGV, without which this
    # target would have no kinematics at all — which is why the REF is in scope.
    #
    #   REF/SGV  12.0 kt / 0.125 = 96 units ; ground track 235.0 deg / 2.8125 = 84 units
    #            HTT = 1 (ground track, so it may become course_deg) ; HRD = 0 (true north)
    out["surface_vehicle_with_ref_ground_vector"] = block(record({
        1: u((SAC << 8) | SIC, 2),
        2: descriptor(atp=2, ext1=(1 << 6)),                   # ATP 2, GBS set
        11: u(0x0029A4, 3),
        17: quality(0x00),
        5: tod(6, 11, 30.0),
        7: latlon_131(56.9236, 23.9711),                       # the Riga apron
        18: mops(2),
        29: identification("EXMAST1"),
        30: u(21, 1),                                          # I021/020 surface service vehicle
        48: ref(SGV=sgv(stopped=0, valid=1, is_ground_track=1, hrd=0,
                        knots=12.0, angle_deg=235.0)),
    }))

    # -------------------------------------------------- stopped, and an invalid heading/track
    #
    # Two absences of DIFFERENT kinds in one item. STP set is a measurement of STILLNESS, so
    # speed_mps is 0.0 and not null — AIS's stationary life raft. HTS clear is the source
    # declining, so the course is absent, "surface_heading_track" is named in unavailable_fields,
    # and the real-looking angle survives in the parked octets rather than being discarded.
    out["surface_stopped_track_invalid"] = block(record({
        1: u((SAC << 8) | SIC, 2),
        2: descriptor(atp=2, ext1=(1 << 6)),
        11: u(0x0029A5, 3),
        17: quality(0x00),
        5: tod(6, 11, 35.0),
        7: latlon_131(56.9236, 23.9711),
        18: mops(2),
        48: ref(SGV=sgv(stopped=1, valid=0, is_ground_track=1, hrd=0,
                        knots=0.0, angle_deg=170.0)),
    }))

    # ------------------------------------------------------------------- an emergency, PS 5
    #
    # I021/200 priority status 5, unlawful interference -> Event ALERT at CRITICAL. The line is
    # drawn at the standard's own emergency declaration, exactly where adsb.py draws it at a type
    # code 28 emergency state and ais.py at navigational status 14.
    out["emergency_unlawful_interference"] = block(record({
        **MANDATORY_ONLY,
        5: tod(6, 12, 0.0),
        7: latlon_131(58.1200, 21.5000),                       # west of Saaremaa
        16: geometric_height(31000),
        18: mops(2),
        23: target_status(ps=5),                               # I021/200 PS 5
        26: ground_vector(455.0, 265.0),
        29: identification("EXRCS01"),
        30: u(3, 1),
    }))

    # ----------------------------------------------- a Version 3 emergency, which is IN THE REF
    #
    # THE FIXTURE THAT JUSTIFIES THE REF DECISION. I021/210 says MOPS version 3; I021/200's
    # priority status is ZERO, because for a Version 3 system it is superseded; REF/STA's first
    # extension carries PS3 = 7, aircraft in distress, manual activation. An adapter that skipped
    # the REF would translate this as an ordinary track update.
    out["version_three_emergency_in_ref"] = block(record({
        **MANDATORY_ONLY,
        5: tod(6, 12, 10.0),
        7: latlon_131(58.1200, 21.5000),
        16: geometric_height(28000),
        18: mops(3),                                           # I021/210 VN = 3
        23: target_status(ps=0),                               # I021/200 PS = 0 — deliberately
        29: identification("EXHELO2"),
        30: u(10, 1),                                          # rotorcraft
        48: ref(STA=sta(es=1, ps3=7)),                         # REF/STA PS3 = 7
    }))

    # -------------------------------------------- quality indicators with NO MOPS version item
    #
    # I021/090 carries all three extensions, including PIC — a containment bound in nautical
    # miles, the most tempting number in the format. I021/210 is ABSENT, so which quantity the
    # primary subfield holds cannot be established. quality_basis must say UNDETERMINED, and
    # nothing may reach Position.accuracy_m or Entity.confidence under either reading.
    #
    #   primary   NUCr/NACv = 3, NUCp/NIC = 9   -> 0x64 | FX
    #   ext 1     NICBARO 1, SIL 2, NACp 8      -> 0xA0 | FX
    #   ext 2     SILS 1, SDA 2, GVA 2          -> 0x2C | FX
    #   ext 3     PIC 11 (< 0.1 NM)             -> 0xB0
    out["quality_indicators_without_mops_version"] = block(record({
        1: u((SAC << 8) | SIC, 2),
        2: descriptor(atp=0),
        11: u(0x0029C7, 3),
        17: quality(0x64, 0xA0, 0x2C, 0xB0),
        5: tod(6, 12, 20.0),
        7: latlon_131(57.5981, 23.8412),
    }))

    # ---------------------------------------------- range check failed, translated ANYWAY
    #
    # The specification's own note says an operational user will SUPPRESS such a target. This
    # adapter does not: filtering is a decision, and a decision made inside a translator is
    # invisible in the CDM output. A fixture that produced no objects would mean the adapter had
    # started making suppression decisions.
    out["range_check_failed_still_translated"] = block(record({
        1: u((SAC << 8) | SIC, 2),
        2: descriptor(atp=0, ext1=(1 << 1), ext2=(1 << 1)),    # CL bits 3/2 = 01 suspect; RCF set
        11: u(0x0029C8, 3),
        17: quality(0x00),
        5: tod(6, 12, 30.0),
        7: latlon_131(58.1200, 21.5000),
        18: mops(2),
    }))

    # ------------------------------------------------------------------- a duplicate address
    #
    # ATP 1: the ground station is saying the address is NOT unique on the wire. Filed under
    # ADSB_NONICAO so it cannot fuse with the genuine airframe, and attributes.identity_caveat
    # records that this entity may still conflate two aircraft — which one record cannot resolve.
    out["duplicate_address"] = block(record({
        1: u((SAC << 8) | SIC, 2),
        2: descriptor(atp=1),
        11: u(0x0029C1, 3),
        17: quality(0x00),
        5: tod(6, 12, 40.0),
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
    }))

    # ----------------------------------------------------------------------- a line obstacle
    #
    # I021/020 = 24. The ONE place an emitter category refines the entity type: FACILITY, which
    # is the same object adsb.py maps from category set C value 5 through a different vocabulary.
    out["obstacle_line"] = block(record({
        1: u((SAC << 8) | SIC, 2),
        2: descriptor(atp=3),                                  # anonymous / obstruction address
        11: u(0x0029B0, 3),
        17: quality(0x00),
        5: tod(6, 12, 50.0),
        7: latlon_131(57.3908, 21.5606),                       # Ventspils
        18: mops(2),
        29: identification("EXMAST1"),
        30: u(24, 1),                                          # line obstacle -> FACILITY
    }))

    # ------------------------------------------------------- two records, one block, two targets
    #
    # FOUR objects from one payload, in block order, with record_index and record_count on each.
    # And they are TWO ENTITIES, not one track: several records in a block are several target
    # reports and may name several aircraft. Grouping the ones that agree would be correlation
    # inside a translator.
    out["two_records_one_block"] = block(
        record({**MANDATORY_ONLY, 5: tod(6, 13, 0.0),
                7: latlon_131(57.5981, 23.8412), 18: mops(2),
                29: identification("EXRCS01"), 30: u(3, 1)}),
        record({1: u((SAC << 8) | SIC, 2), 2: descriptor(atp=0), 11: u(0x0029D2, 3),
                17: quality(0x00), 5: tod(6, 13, 1.0),
                7: latlon_131(58.1200, 21.5000), 18: mops(2),
                29: identification("EXHELO2"), 30: u(10, 1)}),
    )

    # ------------------------------------------- the SAME airframe adsb.py already knows about
    #
    # Address 0029C1 is the ADS-B fixture set's Gulf of Riga aircraft. Both adapters file it
    # under ICAO24, so `ids.derive` gives the SAME entity_id from two different wire formats
    # without the two adapters coordinating — which is the single largest reason this adapter is
    # worth having, and the test asserts the two ids are equal.
    out["icao24_shared_with_adsb"] = block(record({
        **MANDATORY_ONLY,
        5: tod(6, 13, 10.0),
        7: latlon_131(57.5981, 23.8412),
        16: geometric_height(7600),
        18: mops(2),
        29: identification("EXRCS01"),
        30: u(3, 1),
    }))

    # ------------------------------------------------------------ trajectory intent, two points
    #
    # Pins the repetitive item's stride: fifteen octets per point after a one-octet REP. A
    # mis-sized point shifts every field after it and still parses, so the block's total length
    # is what makes the reading falsifiable. INTENT, so the points are parked and NEVER become
    # Event.geometry — a LineString there would paint a declared future as an observation.
    out["trajectory_intent_two_points"] = block(record({
        **MANDATORY_ONLY,
        5: tod(6, 13, 20.0),
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
        34: (u(0b11000000, 1)                                  # I021/110 TIS and TID present
             + u(0b00000000, 1)                                # subfield #1: available and valid
             + u(2, 1)                                         # subfield #2: REP = 2 points
             + trajectory_point(tcp=0, altitude_ft=24000, latitude=57.8000,
                                longitude=23.4000, point_type=7, time_over_point_s=22500)
             + trajectory_point(tcp=1, altitude_ft=10000, latitude=58.2000,
                                longitude=22.9000, point_type=8, time_over_point_s=22800)),
    }))

    # ------------------------------------------------------- an authenticated Mode 5 reply
    #
    # REF/MES subfield #1 with ID and DA set. The test asserts a REFUSAL TO DECIDE: affiliation
    # stays UNKNOWN and affiliation_basis says an attested IFF indication was present and was
    # deliberately not read as an identification. The CDM cannot say "attested, not adjudicated"
    # — gap 2.
    out["mode_five_authenticated"] = block(record({
        1: u((SAC << 8) | SIC, 2),
        2: descriptor(atp=0),
        11: u(0x0029E5, 3),
        17: quality(0x00),
        5: tod(6, 13, 30.0),
        7: latlon_131(58.1200, 21.5000),
        16: geometric_height(15000),
        18: mops(2),
        29: identification("EXRCS01"),
        30: u(6, 1),                                           # highly manoeuvrable, high speed
        48: ref(MES=mes_summary(m5=1, authenticated_id=1, authenticated_data=1,
                                position_from_mode_5=1)),
    }))

    # ------------------------------------------------------------------ an opaque SP field
    #
    # The Special Purpose Field: contents settled by bilateral agreement between one sender and
    # one receiver. Parked verbatim on ingest, restored verbatim on egress, and NEVER written to
    # for an object that did not arrive with one — an octet invented here is an octet some
    # deployment already reads as something else.
    out["special_purpose_field_opaque"] = block(record({
        **MANDATORY_ONLY,
        5: tod(6, 13, 40.0),
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
        49: u(0x04, 1) + bytes((0xDE, 0xAD, 0xBE)),            # SP: length 4, three octets
    }))

    # --------------------------------------------------------------- spare bits set to one
    #
    # Section 4.3 forbids RELYING on spare-bit settings and only RECOMMENDS zeroing them, so a
    # real encoder may set them. Here I021/070's four spare bits (16/13) and I021/161's four
    # (16/13) are all set. The byte-exact round trip survives it only because the octets are
    # parked as sent rather than normalised — which is the whole reason they are parked.
    out["spare_bits_nonzero"] = block(record({
        **MANDATORY_ONLY,
        3: u(0xF000 | 1234, 2),                                # I021/161 track number + spares
        5: tod(6, 13, 50.0),
        7: latlon_131(57.5981, 23.8412),
        18: mops(2),
        19: mode_3a("4271", spare=0b1111),                     # I021/070 with spare bits set
        42: data_ages(geometric_height=2.5, ground_vector=25.5),  # I021/295, gap 13's evidence
    }))
    return out


# ---------------------------------------------------------------------- the refusals
#
# In a SUBDIRECTORY, because `harness.run()` replays every file in a fixture directory through
# `to_cdm()` and each of these is meant to raise. They are exercised by tests/, which is where a
# refusal belongs: the harness measures translation, and a refusal is the absence of one.

def refusals() -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # A time of day beyond a day. 100 000 s x 128 = 12 800 000 units, which fits in 24 bits and
    # is not a time: the counter resets at midnight. Refused, never taken modulo 86 400.
    out["time_beyond_one_day"] = block(record({
        **MANDATORY_ONLY,
        5: u(int(100000 / cat021.TIME_LSB_SECONDS), 3),
        7: latlon_131(57.5981, 23.8412),
    }))

    # The wrong category. A CAT062 block decoded against the CAT021 UAP yields a plausible wrong
    # aircraft, not an error.
    wrong = bytearray(block(record(MANDATORY_ONLY)))
    wrong[0] = 62
    out["wrong_category"] = bytes(wrong)

    # LEN disagreeing with the buffer. Reading to the end instead would translate whatever
    # followed the block as if it were part of it.
    short = bytearray(block(record(MANDATORY_ONLY)))
    short[2] = (short[2] + 4) & 0xFF
    out["length_disagrees_with_buffer"] = bytes(short)

    # An FSPEC bit on FRN 43, which the UAP marks Not Used. There is no item to decode, so it
    # cannot be skipped, and guessing a length would desynchronise the rest of the record.
    items = dict(MANDATORY_ONLY)
    frns = sorted(items) + [43]
    out["fspec_names_a_not_used_frn"] = block(
        cat021._fspec_for(frns) + b"".join(items[frn] for frn in sorted(items)))

    # A record missing I021/080, which the specification says shall be present in every record.
    # ASTERIX carries no checksum, so the mandatory items are part of what replaces one.
    without_address = {frn: octets for frn, octets in MANDATORY_ONLY.items() if frn != 11}
    out["missing_mandatory_target_address"] = block(record(without_address))
    return out


def main() -> None:
    written = 0
    for name, octets in fixtures().items():
        (FIXTURES / f"{name}.cat021").write_bytes(octets)
        parsed = cat021._parse_block(octets)
        (FIXTURES / f"{name}.parsed.json").write_text(
            json.dumps(parsed, indent=2, sort_keys=True) + "\n")
        written += 1
    for name, octets in refusals().items():
        (FIXTURES / "refusals" / f"{name}.cat021").write_bytes(octets)
        written += 1
    print(f"wrote {written} fixtures into {FIXTURES}")


if __name__ == "__main__":
    main()
