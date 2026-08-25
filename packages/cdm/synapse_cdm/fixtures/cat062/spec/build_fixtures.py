#!/usr/bin/env python3
"""Build the CAT062 fixture set. THE SOURCE OF TRUTH FOR BOTH ARTEFACTS.

    python build_fixtures.py                      # from the directory this file is in
    python -m synapse_cdm.harness --adapter cat062 --update-golden   # then READ it

Edit this file, never the `.cat062` octets and never the `.parsed.json` twins.

WHY A GENERATOR AND NOT HAND-EDITED BYTES
-----------------------------------------
A record's FSPEC and its block's LEN are both functions of the contents, and this category adds a
third: the Reserved Expansion Field's own length octet counts itself and everything its items
indicator names. So a hand-edited byte file is a mis-parse waiting to happen in three independent
ways, and a hand-edited twin does not tell you what octets it implies. Every fixture below is
described by its FIELD VALUES and the octets are derived.

EVERYTHING IS SYNTHETIC
-----------------------
No recorded ASTERIX traffic and no real SDPS. `SAC = 0x29` is listed with an explicitly empty
country cell in the EUROCONTROL allocation tables pinned at `../../cat021/spec/sac_pin.json` and in
no other regional table — the evidence transfers to Part 9 by CITATION, because §5.2.1's NOTE
points at the same published list the CAT021 row does. `SIC` carries no allocation claim. Positions
are in the Gulf of Riga, matching the other six ASTERIX and GMTI sets. The Mode S addresses are in
the 0xF00000 block, which no ICAO 24-bit allocation table assigns to any state.

THE LAYOUT SUMS AGAINST THE STANDARD'S OWN BYTE TOTALS
------------------------------------------------------
`_ITEM_OCTETS` states each item's length as §5.2 and Table 1 give it, and `check_layouts()` asserts
that every encoder emits exactly that — so a fixture whose octet count drifts from the document
fails here rather than in a golden diff. It also checks the SUBFIELD lengths of all six compound
items, which is where this category's real exposure is: `I062/290` Subfield #5 is two octets where
the other nine are one, and a decoder that got that wrong would desynchronise the record with no
length error anywhere. `tests/test_cdm_asterix_cat062_adapter.py` calls it, so it cannot be skipped
by not running this file.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
FIXTURES = HERE.parent.parent
sys.path.insert(0, str(FIXTURES.parent.parent.parent))

from synapse_cdm.adapters import asterix_cat062 as cat062          # noqa: E402
from synapse_cdm.adapters import cat062_codec as codec             # noqa: E402

# --------------------------------------------------------------------- the identifiers

#: Pinned by citation: listed-but-blank in the EUR table and in no other.
SAC = 0x29
SIC = 0x29

#: A second SAC/SIC for the contributing-sensor lists and I062/340, so a fixture that named one
#: system everywhere could not hide a decoder writing the wrong pair into the wrong place.
SENSOR_SAC, SENSOR_SIC = 0x29, 0x2A
FPPS_SAC, FPPS_SIC = 0x29, 0x2B

#: The Gulf of Riga, off Ventspils. Baltic-plausible and no real aircraft.
TRACK_LAT = 57.39
TRACK_LON = 21.56

#: 0xF00000 upward: no ICAO 24-bit allocation table assigns this block to any state.
ICAO24 = 0xF0A1C7
ICAO24_SECOND = 0xF0A1C8

#: 06:00:00.000, fifteen minutes before `times.FROZEN_NOW`, so every ordinary fixture resolves on
#: the receipt date and only the rollover fixture does anything else.
TOD_0600 = 6 * 3600 * 128
#: 23:59:59.000 and 00:00:01.000 — the rollover pair.
TOD_2359 = (23 * 3600 + 59 * 60 + 59) * 128
TOD_0000 = 1 * 128

# ------------------------------------------------------------------- the layout table
#
# Each item's octet count as §5.2 states it and Table 1 repeats it. The compound, repetitive and
# FX-chained items state the rule instead of a number, because their length is a function of their
# contents.
_ITEM_OCTETS: dict[str, object] = {
    "I062/010": 2, "I062/015": 1, "I062/070": 3, "I062/105": 8, "I062/100": 6,
    "I062/185": 4, "I062/210": 2, "I062/060": 2, "I062/245": 7, "I062/380": "1+",
    "I062/040": 2, "I062/080": "1+", "I062/290": "1+", "I062/200": 1, "I062/295": "1+",
    "I062/136": 2, "I062/130": 2, "I062/135": 2, "I062/220": 2, "I062/390": "1+",
    "I062/270": "1+", "I062/300": 1, "I062/110": "1+", "I062/120": 2, "I062/510": "3+",
    "I062/500": "1+", "I062/340": "1+", "RE": "1+", "SP": "1+",
}


# ----------------------------------------------------------------------- item builders


def _tod(raw: int) -> dict:
    return {"time_of_day_raw": raw}


def _source(sac: int = SAC, sic: int = SIC) -> dict:
    return {"sac": sac, "sic": sic}


def _position(lat: float, lon: float) -> dict:
    return {"latitude_raw": codec.to_raw("latitude_105", lat),
            "longitude_raw": codec.to_raw("longitude_105", lon)}


def _cartesian(x_m: float, y_m: float) -> dict:
    return {"x_raw": codec.to_raw("cartesian_m", x_m),
            "y_raw": codec.to_raw("cartesian_m", y_m)}


def _velocity(vx: float, vy: float) -> dict:
    return {"vx_raw": codec.to_raw("velocity_mps", vx),
            "vy_raw": codec.to_raw("velocity_mps", vy)}


def _acceleration(ax: float, ay: float) -> dict:
    return {"ax_raw": codec.to_raw("acceleration_mps2", ax),
            "ay_raw": codec.to_raw("acceleration_mps2", ay)}


def _mode_3a(octal: str, *, v: int = 0, g: int = 0, ch: int = 0, spare: int = 0) -> dict:
    return {"v": v, "g": g, "ch": ch, "spare_bit_13": spare,
            "mode_3a": cat062._octal_to_raw(octal)}


def _mode_2(octal: str, *, spare: int = 0) -> dict:
    return {"spare_bits_16_13": spare, "mode_2": cat062._octal_to_raw(octal)}


def _characters(text: str) -> int:
    """Eight six-bit characters, space padded, through the ICAO alphabet."""
    padded = text.ljust(8)[:8]
    value = 0
    for character in padded:
        code = cat062.IDENTIFICATION_ALPHABET.index(character)
        value = (value << 6) | code
    return value


def _target_identification(text: str, *, sti: int = 0, spare: int = 0) -> dict:
    return {"sti": sti, "spare_bits_54_49": spare, "characters_raw": _characters(text)}


def _geometric_altitude(feet: float) -> dict:
    return {"altitude_raw": codec.to_raw("geometric_altitude", feet)}


def _barometric_altitude(flight_level: float, *, qnh: int = 0) -> dict:
    return {"qnh": qnh, "ctba_raw": codec.to_raw("barometric_altitude", flight_level)}


def _measured_flight_level(flight_level: float) -> dict:
    return {"flight_level_raw": codec.to_raw("measured_flight_level", flight_level)}


def _rate_of_climb(feet_per_minute: float) -> dict:
    return {"rate_raw": codec.to_raw("rate_of_climb", feet_per_minute)}


def _movement(trans: int = 0, long: int = 0, vert: int = 0, adf: int = 0,
              spare: int = 0) -> dict:
    return {"trans": trans, "long": long, "vert": vert, "adf": adf, "spare_bit_1": spare}


def _fleet(vfi: int) -> dict:
    return {"vfi": vfi}


def _track_status(*extents: dict, spares: bool = False) -> dict:
    """I062/080 from a list of per-octet field dicts. FX is computed from the chain's length.

    Every field the extent defines has to be given: the encoder writes what the decoder read and
    an omitted field would be a KeyError here rather than a silent zero, which is the point.
    """
    octets = []
    for index, fields in enumerate(extents):
        parsed = dict(fields)
        for name, _high, _low in cat062._080_LAYOUT[index]:
            default = (0b111111 if (spares and name == "spare_bits_7_2") else 0)
            parsed.setdefault(name, default)
        parsed["fx"] = 1 if index + 1 < len(extents) else 0
        octets.append(parsed)
    return {"octets": octets}


def _target_size(length_m: int, orientation_deg: float | None = None,
                 width_m: int | None = None) -> dict:
    values = [("length", codec.to_raw("target_length_m", float(length_m)))]
    if orientation_deg is not None:
        values.append(("orientation", codec.to_raw("target_orientation", orientation_deg)))
    if width_m is not None:
        values.append(("width", codec.to_raw("target_length_m", float(width_m))))
    octets = []
    for index, (field, raw) in enumerate(values):
        octets.append({"field": field, "value_raw": raw,
                       "fx": 1 if index + 1 < len(values) else 0})
    return {"octets": octets}


def _composed(*units: tuple[int, int]) -> dict:
    return {"units": [{"system_unit": unit, "system_track_number": number,
                       "fx": 1 if index + 1 < len(units) else 0}
                      for index, (unit, number) in enumerate(units)]}


def _compound(item: str, subfields: dict, *, spare_presence: int = 0) -> dict:
    """A compound item's parsed form, with the presence octets derived from the subfields given.

    `spare_presence` is a per-octet OR mask, used only by the spare-bits fixture — and note that
    it can only ever be zero for a fixture the adapter must accept, because a set spare PRESENCE
    bit is a refusal. The spare bits a legal record can carry are the ones INSIDE subfields.
    """
    layout = cat062._PRESENCE[item]
    present = [name for octet in layout for name, _bit in octet if name in subfields]
    unknown = set(subfields) - set(present)
    if unknown:
        raise AssertionError(f"{item}: no presence bit for {sorted(unknown)}")
    octets = bytearray(len(layout))
    highest = 0
    for index, octet_layout in enumerate(layout):
        for name, bit in octet_layout:
            if name in subfields:
                octets[index] |= 1 << (bit - 1)
                highest = index
    octets = octets[:highest + 1]
    for index in range(len(octets) - 1):
        octets[index] |= codec.FX
    if spare_presence:
        octets[0] |= spare_presence
    return {"presence": bytes(octets).hex(),
            "subfields": {name: subfields[name] for name in present}}


def _ages(item: str, **seconds: float) -> dict:
    """I062/290 or I062/295 from named ages in seconds."""
    subfields = {}
    for name, value in seconds.items():
        form = "age_quarter_s_16" if (item == "I062/290" and name == "ads") else "age_quarter_s"
        subfields[name] = {"age_raw": codec.to_raw(form, value)}
    return _compound(item, subfields)


def _ref(*, items: dict, spare_bits: int = 0) -> dict:
    """The Reserved Expansion Field, with its own length octet computed from its contents."""
    indicator = spare_bits
    for name, bit in cat062._REF_ITEMS:
        if name in items:
            indicator |= 1 << (bit - 1)
    parsed = {"length": 0, "items_indicator": indicator,
              "spare_bits_3_1": spare_bits & 0b111,
              "items": {name: items[name] for name, _bit in cat062._REF_ITEMS
                        if name in items}}
    parsed["length"] = len(cat062._encode_ref(parsed))
    return parsed


def _explicit(payload: bytes) -> dict:
    return {"length": len(payload) + 1, "contents": payload.hex()}


def record(items: dict, *, fspec: bytes | None = None) -> bytes:
    """One record: the FSPEC then the present items in FRN order."""
    frns = sorted(cat062.FRN_BY_ITEM[item] for item in items)
    body = fspec if fspec is not None else codec.write_fspec(frns)
    for frn in frns:
        item = cat062.UAP_BY_FRN[frn][1]
        body += cat062.ENCODERS[item](items[item])
    return body


def block(*bodies: bytes) -> bytes:
    payload = b"".join(bodies)
    return bytes([cat062.CATEGORY]) + \
        codec.write_unsigned(len(payload) + cat062.BLOCK_HEADER_OCTETS, 2) + payload


def _base(*, tod: int = TOD_0600, track_number: int = 4242,
          status: dict | None = None, **extra) -> dict:
    """The four items whose Encoding Rule reads "present in every ASTERIX record", plus extras."""
    items: dict = {
        "I062/010": _source(),
        "I062/040": {"track_number": track_number},
        "I062/070": _tod(tod),
        "I062/080": status if status is not None else _track_status({"cnf": 0}),
    }
    items.update(extra)
    return items


# ============================================================================ fixtures


def fixtures() -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # ---------------------------------------------- the shortest legal record
    # The four items whose Encoding Rule reads "This Item shall be present in every ASTERIX
    # record", and nothing else. ONE FSPEC OCTET, and a parser that assumed FRN order equalled
    # item-number order would read I062/070 where I062/010 is: Table 1 puts I062/010 at FRN 1,
    # I062/070 at FRN 4, I062/040 at FRN 12 and I062/080 at FRN 13, so the wire order is
    # 010, 070, 040, 080 and the FSPEC needs two octets to reach FRN 13.
    out["minimum_fspec_track"] = block(record(_base()))

    # ---------------------------------------------- every item present
    # ALL 27 ITEMS AND BOTH EXPANSION FIELDS, five FSPEC octets, every compound item's every
    # subfield, every REF item. The fixture that proves the FSPEC ceiling is FIVE and not four:
    # a codec importing cat048_codec's would refuse this record at FRN 29 and never reach the RE.
    out["full_mask_track"] = block(record(_full_items()))

    # ---------------------------------------------- the lifecycle
    # TSB on the first message for a track and TSE on the last. Entity.valid_from is the record's
    # own time in both; Entity.valid_to stays None in BOTH, and the test asserts it — TSE ends the
    # TRACK, and valid_to on an entity keyed on a 24-bit airframe address would say the aircraft
    # ceased to exist.
    out["track_begin"] = block(record(_base(
        status=_track_status({"cnf": 1}, {"tsb": 1}),
        **{"I062/380": _compound("I062/380", {"adr": {"address": ICAO24}})})))
    out["track_end"] = block(record(_base(
        status=_track_status({"cnf": 0}, {"tse": 1}),
        **{"I062/380": _compound("I062/380", {"adr": {"address": ICAO24}})})))

    # ---------------------------------------------- settlement 5, twice
    # Both altitudes present and DISAGREEING, with MRH saying "geometric more reliable". alt_m
    # comes from I062/130 because it is the ellipsoidal one and NOT because MRH said so; the
    # second record flips MRH and the test asserts alt_m does not move.
    out["both_altitudes_disagreeing"] = block(
        record(_base(status=_track_status({"mrh": 1, "src": 1}), **{
            "I062/130": _geometric_altitude(31000.0),
            "I062/135": _barometric_altitude(305.0, qnh=1)})),
        record(_base(status=_track_status({"mrh": 0, "src": 1}), **{
            "I062/130": _geometric_altitude(31000.0),
            "I062/135": _barometric_altitude(305.0, qnh=1)})),
    )

    # Four altitude quantities in one record, all different, with ADF set — the tracker saying two
    # of them disagree. One alt_m, three in the payload with their datums, and I062/340 SF#3's
    # datum is the one the record does not state.
    out["three_altitudes_and_a_measured_height"] = block(record(_base(
        status=_track_status({"mrh": 0, "src": 3}),
        **{
            "I062/130": _geometric_altitude(31000.0),
            "I062/135": _barometric_altitude(305.0),
            "I062/136": _measured_flight_level(304.75),
            "I062/200": _movement(trans=0, long=0, vert=1, adf=1),
            "I062/340": _compound("I062/340", {
                "sid": {"sac": SENSOR_SAC, "sic": SENSOR_SIC},
                "hei": {"height_raw": codec.to_raw("measured_height", 30975.0)},
                "mdc": {"v": 0, "g": 0,
                        "mode_c_raw": codec.to_raw("measured_mode_c", 304.5)},
            }),
        })))

    # ---------------------------------------------- settlement 3, both steps
    # An ICAO24 present: entity_id is uuid5 over ("ICAO24", "F0A1C7"), and the test asserts it
    # equals what asterix_cat021.py derives for the same address.
    out["mode_s_address_present"] = block(record(_base(**{
        "I062/105": _position(TRACK_LAT, TRACK_LON),
        "I062/380": _compound("I062/380", {
            "adr": {"address": ICAO24},
            "id": {"characters_raw": _characters("BAW117")},
        }),
    })))

    # NO I062/380 at all. The id is record-scoped and says so; TWO RECORDS with the SAME track
    # number and different times, so the test can assert they get different entity_id values —
    # which is gap 27's truncation made visible rather than described.
    out["track_number_only"] = block(
        record(_base(tod=TOD_0600, track_number=777,
                     **{"I062/105": _position(TRACK_LAT, TRACK_LON)})),
        record(_base(tod=TOD_0600 + 512, track_number=777,
                     **{"I062/105": _position(TRACK_LAT + 0.01, TRACK_LON)})),
    )

    # ---------------------------------------------- the two expansion fields
    out["reserved_and_extension_fields"] = block(record(_base(**{
        "RE": _ref(items={
            "cst": {"rep": 1, "sensors": [
                {"sac": SENSOR_SAC, "sic": SENSOR_SIC, "spare_bits_24_21": 0, "typ": 5,
                 "local_track_number": 1234}]},
            "tvs": {"vx_raw": codec.to_raw("ref_velocity_mps", 120.0),
                    "vy_raw": codec.to_raw("ref_velocity_mps", -45.25)},
            "sts": {"fdr": 1, "lnav_ep": 1, "lnav_val": 0, "spare_bits_5_2": 0, "fx": 0},
        }),
        "SP": _explicit(bytes.fromhex("aabbccdd")),
    })))

    # ---------------------------------------------- §4.5, and it is a NORMATIVE sentence
    # "Decoders of ASTERIX data shall NEVER ASSUME AND RELY on specific settings of spare or
    # unused bits. However in order to improve the readability of binary dumps of ASTERIX records,
    # it is RECOMMENDED to set all spare bits to zero." So zero is a recommendation and a decoder
    # that depends on it is non-conformant — while dozens of structure diagrams legend their
    # spares "set to zero". FORMAT_COVERAGE.md ambiguity 12.
    #
    # THE CAT034 ROUND FOUND WHY THIS FIXTURE IS MANDATORY RATHER THAN THOROUGH: zeroing a spare
    # bit inside the decoder passed every test and every other fixture, because every other
    # fixture's spares are zero and a dropped zero re-encodes as a zero.
    #
    # The spare PRESENCE bits of the six compound items are NOT among these and cannot be: a set
    # one is refused by `_read_presence`. The reachable spares are the ones inside items and
    # subfields, and every one of them is set here.
    out["spare_bits_nonzero"] = block(record(_base(
        status=_track_status({}, {}, {}, {}, {}, {}, {}, spares=True),
        **{
            "I062/060": _mode_3a("7000", spare=1),
            "I062/120": _mode_2("3456", spare=0b1111),
            "I062/200": _movement(spare=1),
            "I062/245": _target_identification("TEST", spare=0b111111),
            "I062/110": _compound("I062/110", {
                "pmn": {"spare_bits_32_31": 0b11, "pin": 999, "spare_bits_16_14": 0b111,
                        "nat": 3, "spare_bits_8_7": 0b11, "mis": 12},
                "ga": {"spare_bit_16": 1, "res": 1,
                       "ga_raw": codec.to_raw("gnss_altitude", 12500.0)},
                "em1": {"spare_bits_16_13": 0b1111,
                        "extended_mode_1": cat062._octal_to_raw("1234")},
                "xp": {"spare_bits_8_6": 0b111, "x5": 1, "xc": 0, "x3": 1, "x2": 0, "x1": 1},
            }),
            "I062/340": _compound("I062/340", {
                "mda": {"v": 0, "g": 0, "l": 1, "spare_bit_13": 1,
                        "mode_3a": cat062._octal_to_raw("2000")},
                "typ": {"typ": 3, "sim": 0, "rab": 0, "tst": 0, "spare_bits_2_1": 0b11},
            }),
            "I062/380": _compound("I062/380", {
                "tis": {"nav": 1, "nvb": 0, "spare_bits_6_2": 0b11111, "fx": 0},
                "com": {"com": 3, "stat": 0, "spare_bits_10_9": 0b11, "ssc": 1, "arc": 1,
                        "aic": 1, "b1a": 1, "b1b": 0b1010},
                "sab": {"ac": 2, "mn": 2, "dc": 2, "gbs": 0, "spare_bits_9_4": 0b111111,
                        "stat": 0},
                "tar": {"ti": 2, "spare_bits_14_9": 0b111111,
                        "rate_of_turn_raw": codec.to_raw("rate_of_turn", 3.0),
                        "spare_bit_1": 1},
                "met": _met(300.0, 360.0, -40.0, 15, spare=0b1111),
                "pun": {"spare_bits_8_5": 0b1111, "pun": 5},
                "bps": {"spare_bits_16_13": 0b1111,
                        "bps_raw": codec.to_raw("barometric_pressure", 213.4)},
            }),
            "I062/390": _compound("I062/390", {
                "ifi": {"typ": 2, "spare_bits_30_28": 0b111, "nbr": 99999999},
                "fct": {"gat_oat": 1, "fr": 0, "rvsm": 1, "hpr": 1, "spare_bit_1": 1},
                "tod": {"rep": 1, "entries": [
                    {"typ": 7, "day": 0, "spare_bits_25_22": 0b1111, "spare_bits_16_15": 0b11, "hor": 5, "min": 43,
                     "avs": 0, "spare_bit_7": 1, "sec": 21}]},
                "sts": {"emp": 1, "avl": 0, "spare_bits_4_1": 0b1111},
                "pem": {"spare_bits_16_14": 0b111, "va": 1,
                        "mode_3a": cat062._octal_to_raw("7700")},
            }),
            "RE": _ref(items={
                "csn": {"rep": 1, "sensors": [
                    {"sac": SENSOR_SAC, "sic": SENSOR_SIC, "spare_bits_8_5": 0b1111, "typ": 8}]},
                "sts": {"fdr": 0, "lnav_ep": 1, "lnav_val": 1, "spare_bits_5_2": 0b1111,
                        "fx": 0},
                "v3": _v3(ps3=(1, 5), spare=0b1111),
            }, spare_bits=0b111),
        })))

    # ---------------------------------------------- the two-octet age
    # I062/290 with SF#5 present AND later subfields present, so a decoder that read ADS-C age as
    # one octet desynchronises and the following subfield's value is visibly wrong. This is the
    # single most dangerous uniformity assumption in the category.
    out["ads_c_age_two_octets"] = block(record(_base(**{
        "I062/290": _ages("I062/290", trk=12.5, psr=1.25, ads=4000.0, es=0.75, mlt=63.75),
    })))

    # ---------------------------------------------- settlement 2's whole reason
    # I062/380 SF#11 STAT = 1 ("General emergency") AND the REF's PS3 = 7 ("Aircraft in Distress -
    # Manual Activation"). The back-mapping's worst case: the core item is LEGALLY CORRECT and
    # lossy — the document's own table maps 7 onto 1 — the REF has the real value, severity comes
    # from the REF, and the disagreement is recorded.
    out["adsb_version_3_emergency"] = block(record(_base(**{
        "I062/105": _position(TRACK_LAT, TRACK_LON),
        "I062/380": _compound("I062/380", {
            "adr": {"address": ICAO24},
            "sab": {"ac": 2, "mn": 2, "dc": 2, "gbs": 0, "spare_bits_9_4": 0, "stat": 1},
        }),
        "RE": _ref(items={"v3": _v3(ps3=(1, 7))}),
    })))

    # Two core statements disagreeing, with IEC set. The more severe wins, both are carried, and
    # attributes.fusion_provenance.track_status.iec is the tracker saying the same thing.
    out["emergency_disagreement"] = block(record(_base(
        status=_track_status({}, {}, {}, {}, {"ems": 3}, {"iec": 1}),
        **{
            "I062/380": _compound("I062/380", {
                "adr": {"address": ICAO24},
                "sab": {"ac": 0, "mn": 0, "dc": 0, "gbs": 0, "spare_bits_9_4": 0, "stat": 5},
            }),
        })))

    # ---------------------------------------------- settlement 4's substitution
    # I062/110 with the reported position, the GNSS altitude and a NEGATIVE time offset, so the
    # two's complement goes end to end. The second record omits Subfield #6 and the test asserts
    # the STATED ZERO rather than an unknown.
    out["mode5_time_offset"] = block(
        record(_base(**{"I062/110": _compound("I062/110", {
            "sum": {"m5": 1, "id": 1, "da": 1, "m1": 1, "m2": 0, "m3": 1, "mc": 1, "x": 0},
            "pos": {"latitude_raw": codec.to_raw("latitude_23", TRACK_LAT),
                    "longitude_raw": codec.to_raw("longitude_23", TRACK_LON)},
            "ga": {"spare_bit_16": 0, "res": 1,
                   "ga_raw": codec.to_raw("gnss_altitude", 24000.0)},
            "tos": {"tos_raw": codec.to_raw("time_offset", -0.5)},
        })})),
        record(_base(**{"I062/110": _compound("I062/110", {
            "sum": {"m5": 1, "id": 0, "da": 1, "m1": 0, "m2": 0, "m3": 0, "mc": 0, "x": 1},
            "pos": {"latitude_raw": codec.to_raw("latitude_23", TRACK_LAT),
                    "longitude_raw": codec.to_raw("longitude_23", TRACK_LON)},
        })})),
    )

    # ---------------------------------------------- the trajectory that is not a track
    # Three Trajectory Change Points: one with TOA = 0 and a resolvable TOV, one with TOA = 1, one
    # with TRA = 0. No Track and no Event.geometry are emitted and the test asserts both.
    out["trajectory_intent_three_points"] = block(record(_base(**{
        "I062/380": _compound("I062/380", {
            "adr": {"address": ICAO24},
            "tis": {"nav": 0, "nvb": 0, "spare_bits_6_2": 0, "fx": 0},
            "tid": {"rep": 3, "points": [
                _intent(0, 30000.0, TRACK_LAT + 0.5, TRACK_LON + 0.5, 7, toa=0, tra=1,
                        tov_s=22000, ttr_nm=12.5),
                _intent(1, 33000.0, TRACK_LAT + 1.0, TRACK_LON + 1.0, 1, toa=1, tra=1,
                        tov_s=0, ttr_nm=8.0),
                _intent(2, 33000.0, TRACK_LAT + 1.5, TRACK_LON + 1.5, 8, toa=0, tra=0,
                        tov_s=22600, ttr_nm=0.0),
            ]},
        }),
    })))

    # ---------------------------------------------- the whole flight plan
    out["flight_plan_correlated"] = block(record(_base(
        status=_track_status({}, {"fpc": 1}),
        **{"I062/390": _compound("I062/390", _full_flight_plan())})))

    # ---------------------------------------------- the pair an operator needs
    out["pre_emergency_pair"] = block(
        record(_base(**{"I062/390": _compound("I062/390", {
            "pem": {"spare_bits_16_14": 0, "va": 1,
                    "mode_3a": cat062._octal_to_raw("1234")},
            "pec": {"pre_emergency_raw": b"BAW117 ".hex()},
        })})),
        record(_base(**{"I062/390": _compound("I062/390", {
            "pem": {"spare_bits_16_14": 0, "va": 0,
                    "mode_3a": cat062._octal_to_raw("7700")},
        })})),
    )

    # ---------------------------------------------- settlement 1's most direct provenance
    out["contributing_sensors"] = block(record(_base(**{
        "RE": _ref(items={
            "cst": {"rep": 2, "sensors": [
                {"sac": SENSOR_SAC, "sic": SENSOR_SIC, "spare_bits_24_21": 0, "typ": 5,
                 "local_track_number": 4001},
                {"sac": SENSOR_SAC, "sic": SENSOR_SIC + 1, "spare_bits_24_21": 0, "typ": 8,
                 "local_track_number": 4002}]},
            "csn": {"rep": 1, "sensors": [
                # TYP in the reserved 1010-1111 range. Parked, and unresolved_raw says so.
                {"sac": SENSOR_SAC, "sic": SENSOR_SIC + 2, "spare_bits_8_5": 0, "typ": 0b1011}]},
        }),
    })))

    # ---------------------------------------------- the accuracies, one of them saturated
    out["estimated_accuracies_full"] = block(record(_base(**{
        "I062/105": _position(TRACK_LAT, TRACK_LON),
        "I062/100": _cartesian(12000.0, -8000.0),
        "I062/185": _velocity(210.5, -60.25),
        "I062/210": _acceleration(1.5, -0.75),
        "I062/220": _rate_of_climb(1875.0),
        "I062/130": _geometric_altitude(31000.0),
        "I062/135": _barometric_altitude(305.0),
        "I062/500": _compound("I062/500", {
            "apc": {"x_raw": codec.to_raw("accuracy_position_m", 45.0),
                    "y_raw": codec.to_raw("accuracy_position_m", 60.0)},
            "cov": {"covariance_raw": codec.to_raw("accuracy_covariance_m", -32.5)},
            "apw": {"x_raw": codec.to_raw("accuracy_position_deg", 0.0004),
                    "y_raw": codec.to_raw("accuracy_position_deg", 0.0008)},
            "aga": {"accuracy_raw": codec.to_raw("accuracy_geometric_altitude", 125.0)},
            "aba": {"accuracy_raw": codec.to_raw("accuracy_barometric_altitude", 1.5)},
            "atv": {"x_raw": codec.to_raw("accuracy_velocity_mps", 2.5),
                    "y_raw": codec.to_raw("accuracy_velocity_mps", 3.0)},
            "aa": {"x_raw": codec.to_raw("accuracy_acceleration_mps2", 0.5),
                   "y_raw": codec.to_raw("accuracy_acceleration_mps2", 0.75)},
            # AT THE MAXIMUM, so the floor flag fires: §5.2.26 says "Maximum value means maximum
            # value or above" under all eight subfields.
            "arc": {"accuracy_raw": 255},
        }),
    })))

    # ---------------------------------------------- settlement 6
    out["cartesian_position_parked"] = block(record(_base(**{
        "I062/105": _position(TRACK_LAT, TRACK_LON),
        "I062/100": _cartesian(-125000.5, 88000.0),
    })))

    # ---------------------------------------------- settlement 9
    # I062/245 present at all is non-conformant, and its STI is 11 ("Invalid"). All three
    # callsign-shaped strings in one object and none promoted.
    out["target_identification_forbidden"] = block(record(_base(**{
        "I062/245": _target_identification("BAW117", sti=3),
        "I062/380": _compound("I062/380", {
            "adr": {"address": ICAO24},
            "id": {"characters_raw": _characters("BAW117")},
        }),
        "I062/390": _compound("I062/390", {"csn": {"callsign_raw": b"BAW117 ".hex()}}),
    })))

    # ---------------------------------------------- the two items that refine entity_type
    out["emitter_category_and_fleet"] = block(
        record(_base(**{"I062/300": _fleet(5),
                        "I062/380": _compound("I062/380", {"emc": {"ecat": 21}})})),
        record(_base(**{"I062/300": _fleet(200),
                        "I062/380": _compound("I062/380", {"emc": {"ecat": 2}})})),
        record(_base(**{"I062/380": _compound("I062/380", {"emc": {"ecat": 22}})})),
    )

    # ---------------------------------------------- settlement 3's own witness
    out["composed_track_number_three_units"] = block(record(_base(**{
        "I062/510": _composed((0x11, 4242), (0x22, 8888), (0x33, 1111)),
    })))

    # ---------------------------------------------- ambiguity 10, both readings
    out["target_size_length_only"] = block(
        record(_base(**{"I062/270": _target_size(64)})),
        record(_base(**{"I062/270": _target_size(64, 225.0, 60)})),
    )

    # ---------------------------------------------- the midnight wrap
    # TWO RECORDS, built so the wrap happens under the HARNESS'S OWN frozen clock rather than only
    # under one a test injects — the failure this package's README records for CAT048's two
    # rollover fixtures, which described times that resolved to the receipt date at the frozen
    # instant and so tested no rollover in either direction.
    #
    # times.FROZEN_NOW is 2026-04-29T06:15:00Z. Record 0's 23:59:59 is 6 h 15 min from the
    # PREVIOUS day's instant and 17 h 45 min from the receipt day's, so the previous day wins.
    # Record 1's 00:00:01 is 6 h 15 min from the receipt day's own instant, which wins. The
    # forward roll is unreachable from a 06:15 receipt time by construction and is asserted in
    # the test module against an injected late-evening clock.
    out["midnight_rollover_nearest"] = block(
        record(_base(tod=TOD_2359)),
        record(_base(tod=TOD_0000)),
    )

    # ---------------------------------------------- two records, one block
    out["two_records_one_block"] = block(
        record(_base(track_number=1, **{
            "I062/105": _position(TRACK_LAT, TRACK_LON),
            "I062/380": _compound("I062/380", {"adr": {"address": ICAO24}})})),
        record(_base(track_number=2, **{
            "I062/105": _position(TRACK_LAT + 0.2, TRACK_LON + 0.2),
            "I062/380": _compound("I062/380", {"adr": {"address": ICAO24_SECOND}})})),
    )

    # ---------------------------------------------- a legal but non-conventional FSPEC
    # FRNs 1, 4, 12 and 13 need two octets; this record sets FX on the second and follows it with
    # an all-zero third. §4.7 requires only that a present item's bit is set, so this is legal and
    # the round trip is byte-exact only because the octets are re-emitted as parked.
    out["non_minimal_fspec"] = block(record(_base(), fspec=bytes([0x91, 0x0D, 0x00])))

    # ---------------------------------------------- the thirty-one ages
    out["track_data_ages"] = block(record(_base(**{
        "I062/295": _ages("I062/295", mfl=1.5, mda=2.0, mhg=0.25, ias=3.0, tas=3.25,
                          sal=4.0, com=5.0, sab=5.25, bvr=6.0, gvr=6.25, ran=7.0,
                          tar=7.25, tan=8.0, gsp=8.25, met=9.0, emc=63.75, pos=10.0,
                          gal=10.25, pun=11.0, mb=11.25, iar=12.0, mac=12.25, bps=13.0),
        "I062/380": _compound("I062/380", {
            "adr": {"address": ICAO24},
            "mhg": {"heading_raw": codec.to_raw("heading_16", 271.0)},
            "mac": {"mach_number_raw": codec.to_raw("mach_number", 0.824)},
        }),
    })))

    return out


def _met(speed: float, direction: float, celsius: float, turbulence: int,
         *, spare: int = 0) -> dict:
    return {"ws": 1, "wd": 1, "tmp": 1, "trb": 1, "spare_bits_60_57": spare,
            "wind_speed_raw": codec.to_raw("wind_speed", speed),
            "wind_direction_raw": codec.to_raw("wind_direction", direction),
            "temperature_raw": codec.to_raw("temperature", celsius),
            "turbulence_raw": turbulence}


def _v3(*, ps3: tuple[int, int] | None = None, spare: int = 0) -> dict:
    """Appendix A §2.7. `ps3` is (populated, value)."""
    subfields: dict = {}
    primary = 0
    if ps3 is not None:
        primary |= 1 << 7
        subfields["ps3"] = {"ps3_ep": ps3[0], "ps3_val": ps3[1], "spare_bits_4_1": spare}
    return {"primary": primary, "spare_bits_4_2": 0, "fx": 0, "subfields": subfields}


def _intent(tcp: int, altitude_ft: float, lat: float, lon: float, point_type: int, *,
            toa: int, tra: int, tov_s: int, ttr_nm: float) -> dict:
    return {"tca": 0, "nc": 0, "tcp_number": tcp,
            "altitude_raw": codec.to_raw("tid_altitude", altitude_ft),
            "latitude_raw": codec.to_raw("latitude_23", lat),
            "longitude_raw": codec.to_raw("longitude_23", lon),
            "point_type": point_type, "td": 1, "tra": tra, "toa": toa,
            "tov_raw": tov_s, "ttr_raw": codec.to_raw("turn_radius", ttr_nm)}


def _full_flight_plan() -> dict:
    return {
        "tag": {"sac": FPPS_SAC, "sic": FPPS_SIC},
        "csn": {"callsign_raw": b"BAW117 ".hex()},
        "ifi": {"typ": 0, "spare_bits_30_28": 0, "nbr": 12345678},
        "fct": {"gat_oat": 1, "fr": 0, "rvsm": 1, "hpr": 0, "spare_bit_1": 0},
        "tac": {"aircraft_type_raw": b"B738".hex()},
        "wtc": {"wtc": ord("M")},
        "dep": {"departure_raw": b"EVRA".hex()},
        "dst": {"destination_raw": b"EGLL".hex()},
        "rds": {"nu1": ord("1"), "nu2": ord("8"), "ltr": ord("R")},
        "cfl": {"cleared_flight_level_raw": codec.to_raw("cleared_flight_level", 310.0)},
        "ctl": {"centre": 0x07, "position": 0x1F},
        "tod": {"rep": 2, "entries": [
            {"typ": 7, "day": 0, "spare_bits_25_22": 0, "spare_bits_16_15": 0, "hor": 5, "min": 43, "avs": 0,
             "spare_bit_7": 0, "sec": 21},
            # DAY = 1 ("Yesterday") and AVS = 1 ("Seconds not available"): two of the three
            # reasons no absolute instant is derived, in one entry.
            {"typ": 9, "day": 1, "spare_bits_25_22": 0, "spare_bits_16_15": 0, "hor": 9, "min": 12, "avs": 1,
             "spare_bit_7": 0, "sec": 0},
        ]},
        "ast": {"aircraft_stand_raw": b"A12   ".hex()},
        "sts": {"emp": 1, "avl": 0, "spare_bits_4_1": 0},
        "std": {"sid_raw": b"RIGA1A ".hex()},
        "sta": {"star_raw": b"LAM2C  ".hex()},
        "pem": {"spare_bits_16_14": 0, "va": 1, "mode_3a": cat062._octal_to_raw("1234")},
        "pec": {"pre_emergency_raw": b"BAW117 ".hex()},
    }


def _full_items() -> dict:
    """Every one of the 27 items and both expansion fields, with every subfield present."""
    return {
        "I062/010": _source(),
        "I062/015": {"service_identification": 3},
        "I062/070": _tod(TOD_0600),
        "I062/105": _position(TRACK_LAT, TRACK_LON),
        "I062/100": _cartesian(12000.0, -8000.0),
        "I062/185": _velocity(210.5, -60.25),
        "I062/210": _acceleration(1.5, -0.75),
        "I062/060": _mode_3a("7000", ch=1),
        "I062/245": _target_identification("BAW117", sti=0),
        "I062/380": _compound("I062/380", {
            "adr": {"address": ICAO24},
            "id": {"characters_raw": _characters("BAW117")},
            "mhg": {"heading_raw": codec.to_raw("heading_16", 271.0)},
            "ias": {"im": 0, "air_speed_raw": codec.to_raw("airspeed_nm_s", 0.0765)},
            "tas": {"true_airspeed_raw": codec.to_raw("true_airspeed", 462.0)},
            "sal": {"sas": 1, "source": 2,
                    "altitude_raw": codec.to_raw("selected_altitude", 31000.0)},
            "fss": {"mv": 1, "ah": 0, "am": 0,
                    "altitude_raw": codec.to_raw("selected_altitude", 33000.0)},
            "tis": {"nav": 0, "nvb": 0, "spare_bits_6_2": 0, "fx": 0},
            "tid": {"rep": 1, "points": [
                _intent(0, 33000.0, TRACK_LAT + 0.5, TRACK_LON + 0.5, 7, toa=0, tra=1,
                        tov_s=22000, ttr_nm=12.5)]},
            "com": {"com": 3, "stat": 0, "spare_bits_10_9": 0, "ssc": 1, "arc": 1, "aic": 1,
                    "b1a": 0, "b1b": 0},
            "sab": {"ac": 2, "mn": 2, "dc": 2, "gbs": 0, "spare_bits_9_4": 0, "stat": 0},
            "acs": {"acas_ra": "30" * 7},
            "bvr": {"vertical_rate_raw": codec.to_raw("vertical_rate", 1875.0)},
            "gvr": {"vertical_rate_raw": codec.to_raw("vertical_rate", 1900.0)},
            "ran": {"roll_angle_raw": codec.to_raw("roll_angle", -12.5)},
            "tar": {"ti": 2, "spare_bits_14_9": 0,
                    "rate_of_turn_raw": codec.to_raw("rate_of_turn", 2.5), "spare_bit_1": 0},
            "tan": {"track_angle_raw": codec.to_raw("heading_16", 268.5)},
            "gsp": {"ground_speed_raw": codec.to_raw("ground_speed", 0.1345)},
            "vun": {"velocity_uncertainty": 2},
            "met": _met(48.0, 235.0, -52.25, 3),
            "emc": {"ecat": 3},
            "pos": {"latitude_raw": codec.to_raw("latitude_23", TRACK_LAT),
                    "longitude_raw": codec.to_raw("longitude_23", TRACK_LON)},
            "gal": {"geometric_altitude_raw": codec.to_raw("geometric_altitude", 31050.0)},
            "pun": {"spare_bits_8_5": 0, "pun": 4},
            "mb": {"rep": 2, "registers": [
                {"bds_data": "40" + "00" * 6, "bds1": 4, "bds2": 0},
                {"bds_data": "50" + "11" * 6, "bds1": 5, "bds2": 0}]},
            "iar": {"indicated_airspeed_raw": codec.to_raw("indicated_airspeed", 290.0)},
            "mac": {"mach_number_raw": codec.to_raw("mach_number", 0.824)},
            "bps": {"spare_bits_16_13": 0,
                    "bps_raw": codec.to_raw("barometric_pressure", 213.4)},
        }),
        "I062/040": {"track_number": 4242},
        "I062/080": _track_status(
            {"mon": 0, "spi": 1, "mrh": 1, "src": 1, "cnf": 0},
            {"sim": 0, "tse": 0, "tsb": 0, "fpc": 1, "aff": 0, "stp": 0, "kos": 1},
            {"ama": 1, "md4": 1, "me": 0, "mi": 1, "md5": 1},
            {"cst": 0, "psr": 1, "ssr": 0, "mds": 0, "ads": 1, "suc": 1, "aac": 0},
            {"sds": 0, "ems": 0, "pft": 1, "fplt": 0},
            {"dupt": 0, "dupf": 1, "dupm": 0, "sfc": 0, "idd": 0, "iec": 0, "mlat": 1},
            {"m5i": 1},
        ),
        "I062/290": _ages("I062/290", trk=12.5, psr=1.25, ssr=1.5, mds=0.75, ads=4000.0,
                          es=0.5, vdl=2.0, uat=2.25, lop=3.0, mlt=3.25),
        "I062/200": _movement(trans=1, long=2, vert=1, adf=1),
        "I062/295": _ages("I062/295", mfl=1.5, md1=1.75, md2=2.0, mda=2.25, md4=2.5,
                          md5=2.75, mhg=3.0, ias=3.25, tas=3.5, sal=3.75, fss=4.0,
                          tid=4.25, com=4.5, sab=4.75, acs=5.0, bvr=5.25, gvr=5.5,
                          ran=5.75, tar=6.0, tan=6.25, gsp=6.5, vun=6.75, met=7.0,
                          emc=7.25, pos=7.5, gal=7.75, pun=8.0, mb=8.25, iar=8.5,
                          mac=8.75, bps=9.0),
        "I062/136": _measured_flight_level(304.75),
        "I062/130": _geometric_altitude(31000.0),
        "I062/135": _barometric_altitude(305.0, qnh=1),
        "I062/220": _rate_of_climb(1875.0),
        "I062/390": _compound("I062/390", _full_flight_plan()),
        "I062/270": _target_size(64, 225.0, 60),
        "I062/300": _fleet(0),
        "I062/110": _compound("I062/110", {
            "sum": {"m5": 1, "id": 1, "da": 1, "m1": 1, "m2": 1, "m3": 1, "mc": 1, "x": 1},
            "pmn": {"spare_bits_32_31": 0, "pin": 4321, "spare_bits_16_14": 0, "nat": 7,
                    "spare_bits_8_7": 0, "mis": 21},
            "pos": {"latitude_raw": codec.to_raw("latitude_23", TRACK_LAT),
                    "longitude_raw": codec.to_raw("longitude_23", TRACK_LON)},
            "ga": {"spare_bit_16": 0, "res": 1,
                   "ga_raw": codec.to_raw("gnss_altitude", 24000.0)},
            "em1": {"spare_bits_16_13": 0, "extended_mode_1": cat062._octal_to_raw("1234")},
            "tos": {"tos_raw": codec.to_raw("time_offset", -0.5)},
            "xp": {"spare_bits_8_6": 0, "x5": 1, "xc": 1, "x3": 0, "x2": 0, "x1": 1},
        }),
        "I062/120": _mode_2("3456"),
        "I062/510": _composed((0x11, 4242), (0x22, 8888)),
        "I062/500": _compound("I062/500", {
            "apc": {"x_raw": codec.to_raw("accuracy_position_m", 45.0),
                    "y_raw": codec.to_raw("accuracy_position_m", 60.0)},
            "cov": {"covariance_raw": codec.to_raw("accuracy_covariance_m", -32.5)},
            "apw": {"x_raw": codec.to_raw("accuracy_position_deg", 0.0004),
                    "y_raw": codec.to_raw("accuracy_position_deg", 0.0008)},
            "aga": {"accuracy_raw": codec.to_raw("accuracy_geometric_altitude", 125.0)},
            "aba": {"accuracy_raw": codec.to_raw("accuracy_barometric_altitude", 1.5)},
            "atv": {"x_raw": codec.to_raw("accuracy_velocity_mps", 2.5),
                    "y_raw": codec.to_raw("accuracy_velocity_mps", 3.0)},
            "aa": {"x_raw": codec.to_raw("accuracy_acceleration_mps2", 0.5),
                   "y_raw": codec.to_raw("accuracy_acceleration_mps2", 0.75)},
            "arc": {"accuracy_raw": codec.to_raw("accuracy_rate_of_climb", 125.0)},
        }),
        "I062/340": _compound("I062/340", {
            "sid": {"sac": SENSOR_SAC, "sic": SENSOR_SIC},
            "pos": {"rho_raw": codec.to_raw("rho", 42.5),
                    "theta_raw": codec.to_raw("theta", 137.25)},
            "hei": {"height_raw": codec.to_raw("measured_height", 30975.0)},
            "mdc": {"v": 0, "g": 0, "mode_c_raw": codec.to_raw("measured_mode_c", 304.5)},
            "mda": {"v": 0, "g": 0, "l": 1, "spare_bit_13": 0,
                    "mode_3a": cat062._octal_to_raw("7000")},
            "typ": {"typ": 5, "sim": 0, "rab": 0, "tst": 0, "spare_bits_2_1": 0},
        }),
        "RE": _ref(items={
            "cst": {"rep": 2, "sensors": [
                {"sac": SENSOR_SAC, "sic": SENSOR_SIC, "spare_bits_24_21": 0, "typ": 5,
                 "local_track_number": 4001},
                {"sac": SENSOR_SAC, "sic": SENSOR_SIC + 1, "spare_bits_24_21": 0, "typ": 8,
                 "local_track_number": 4002}]},
            "csn": {"rep": 1, "sensors": [
                {"sac": SENSOR_SAC, "sic": SENSOR_SIC + 2, "spare_bits_8_5": 0, "typ": 9}]},
            "tvs": {"vx_raw": codec.to_raw("ref_velocity_mps", 120.0),
                    "vy_raw": codec.to_raw("ref_velocity_mps", -45.25)},
            "sts": {"fdr": 1, "lnav_ep": 1, "lnav_val": 0, "spare_bits_5_2": 0, "fx": 0},
            "v3": _full_v3(),
        }),
        "SP": _explicit(bytes.fromhex("aabbccdd")),
    }


def _full_v3() -> dict:
    """Appendix A §2.7 with all four subfields and every Element-Populated bit set."""
    return {
        "primary": (1 << 7) | (1 << 6) | (1 << 5) | (1 << 4),
        "spare_bits_4_2": 0, "fx": 0,
        "subfields": {
            "ps3": {"ps3_ep": 1, "ps3_val": 2, "spare_bits_4_1": 0},
            "as": {"rce_ep": 1, "rce_val": 1, "rrl_ep": 1, "rrl_val": 0, "tpw_ep": 1,
                   "tpw_val": 2, "tsi_ep": 1, "tsi_val": 1, "tao_ep": 1, "re": 1,
                   "tao_val": 31, "spare_bits_5_1": 0},
            "uas": {"muo_ep": 1, "muo_val": 1, "daa_ep": 1, "daa_val": 1, "rwc_ep": 1,
                    "rwc_val": 1, "spare_bit_1": 0},
            "cass": {"svh_ep": 1, "svh_val": 2, "catc_ep": 1, "catc_val": 4, "spare_bit_1": 0},
        },
    }


def refusals() -> dict[str, bytes]:
    """Blocks the adapter must refuse. No golden file: the refusal IS the expected output."""
    out: dict[str, bytes] = {}
    good = block(record(_base()))

    # A block whose CAT octet is 48. Decoded against the category 062 UAP it would yield a
    # plausible wrong aircraft rather than an error.
    out["wrong_category"] = bytes([48]) + good[1:]

    # LEN longer than the octets supplied.
    padded = bytearray(good)
    padded[1:3] = codec.write_unsigned(len(padded) + 4, 2)
    out["length_disagrees_with_buffer"] = bytes(padded)

    # No I062/040 — one of the four items whose own Encoding Rule makes it unconditional.
    out["missing_mandatory_track_number"] = block(record({
        "I062/010": _source(), "I062/070": _tod(TOD_0600),
        "I062/080": _track_status({"cnf": 0})}))

    # An FSPEC bit for FRN 30, which Table 1 marks '- Spare -'. The refusal names it as a spare
    # slot rather than as an undefined FRN, because the two mean different things to somebody
    # debugging an encoder — and FRN 2's refusal quotes the document's own reason where FRNs 29 to
    # 33 have none.
    #
    # Assembled from octets, because `codec.write_fspec` REFUSES a spare FRN: a presence bit for a
    # spare slot announces content the record does not carry, so a conforming encoder cannot
    # produce this either. FRN 30 is octet 5, bit 6.
    spare_fspec = bytes([0x91, 0x0D, 0x01, 0x01, 0x40])
    out["fspec_names_a_spare_frn"] = block(spare_fspec + _mandatory_items())

    # A fifth FSPEC octet with FX set. There is no FRN 36.
    out["fspec_sixth_octet"] = block(
        bytes([0x91, 0x0D, 0x01, 0x01, 0x01]) + _mandatory_items())

    # I062/080's sixth extent with FX set — ambiguity 11, and a hole Edition 1.21 opened.
    seventh = _track_status({}, {}, {}, {}, {}, {}, {})
    seventh["octets"][6]["fx"] = 1
    out["track_status_seventh_extent"] = block(record(_base(status=seventh)))

    # A compound item's presence octet with a SPARE presence bit set. It announces a subfield the
    # document does not define.
    #
    # ASSEMBLED FROM OCTETS RATHER THAN THROUGH `record()`, and that is itself a check: the
    # encoder REFUSES to write this, because `_encode_compound` re-reads the presence map it is
    # about to emit and `_read_presence` rejects a spare presence bit in either direction. So the
    # only way to produce this fixture is by hand, which is the correct answer — a conforming
    # encoder cannot emit it either.
    out["compound_spare_presence_bit"] = block(
        codec.write_fspec([1, 4, 12, 13, 14]) + _mandatory_items()
        # presence octet 1 with FX set, octet 2 with bit 4 — a spare presence bit — then one age
        + bytes([0x81, 0b00001000, 0x04]))

    # A repetitive subfield with REP = 0, excluded by the item's own "at least one".
    bds = _compound("I062/380", {"mb": {"rep": 0, "registers": []}})
    out["repetitive_rep_zero"] = block(record(_base(**{"I062/380": bds})))

    # A REF whose own length indicator does not match the octets its items indicator implies —
    # Appendix A §2.1's second length statement inside a record that already has one. The stated
    # length is two octets LONGER and two pad octets are supplied, so the block still tiles and the
    # `_len_explicit` bound is satisfied: what fails is `_decode_ref`'s exact-tiling check, which
    # is the path this fixture is for. A shorter block would refuse one level up and never reach it.
    ref = _ref(items={"tvs": {"vx_raw": 0, "vy_raw": 0}})
    ref["length"] += 2
    tail = cat062.ENCODERS["RE"](ref) + b"\x00\x00"
    out["ref_length_disagrees"] = block(
        codec.write_fspec([1, 4, 12, 13, 34]) + _mandatory_items() + tail)

    return out


def _mandatory_items() -> bytes:
    """The four unconditionally mandatory items, in FRN order, as octets.

    Used by the refusals that have to be assembled from octets because a conforming encoder
    refuses to produce them — which is itself the point: `codec.write_fspec` rejects a spare FRN
    and `_encode_compound` rejects a spare presence bit, so the only way to build those fixtures is
    by hand.
    """
    return (cat062.ENCODERS["I062/010"](_source())
            + cat062.ENCODERS["I062/070"](_tod(TOD_0600))
            + cat062.ENCODERS["I062/040"]({"track_number": 4242})
            + cat062.ENCODERS["I062/080"](_track_status({"cnf": 0})))


def check_layouts() -> None:
    """Every encoder emits exactly the octet count the standard states for its item."""
    problems: list[str] = []
    samples: dict[str, dict] = {
        "I062/010": _source(0, 0),
        "I062/015": {"service_identification": 0},
        "I062/070": _tod(0),
        "I062/105": _position(0.0, 0.0),
        "I062/100": _cartesian(0.0, 0.0),
        "I062/185": _velocity(0.0, 0.0),
        "I062/210": _acceleration(0.0, 0.0),
        "I062/060": _mode_3a("0000"),
        "I062/245": _target_identification(""),
        "I062/040": {"track_number": 0},
        "I062/200": _movement(),
        "I062/136": _measured_flight_level(0.0),
        "I062/130": _geometric_altitude(0.0),
        "I062/135": _barometric_altitude(0.0),
        "I062/220": _rate_of_climb(0.0),
        "I062/300": _fleet(0),
        "I062/120": _mode_2("0000"),
    }
    for item, expected in _ITEM_OCTETS.items():
        if not isinstance(expected, int):
            continue
        emitted = len(cat062.ENCODERS[item](samples[item]))
        if emitted != expected:
            problems.append(f"{item}: the standard states {expected} octet(s), encoder emitted "
                            f"{emitted}")

    # THE COMPOUND SUBFIELDS, one at a time, against §5.2's own figures. This is where the real
    # exposure is: I062/290 Subfield #5 is TWO octets where the other nine are one, and a decoder
    # that got that wrong would desynchronise the record with no length error anywhere.
    subfield_samples = _subfield_samples()
    for item, widths in cat062._SUBFIELD_OCTETS.items():
        for name, expected in widths.items():
            if expected is None:
                continue
            sample = subfield_samples[item][name]
            emitted = len(cat062._SUBFIELD_ENCODERS[item][name](sample))
            if emitted != expected:
                problems.append(f"{item} subfield {name}: §5.2 states {expected} octet(s), "
                                f"encoder emitted {emitted}")

    # The FX chains and the repetitions, at a stated shape each.
    checks = [
        ("I062/080", _track_status({"cnf": 0}), 1),
        ("I062/080", _track_status({}, {}, {}, {}, {}, {}, {}), 7),
        ("I062/270", _target_size(1), 1),
        ("I062/270", _target_size(1, 0.0, 1), 3),
        ("I062/510", _composed((0, 0)), 3),
        ("I062/510", _composed((0, 0), (0, 0), (0, 0)), 9),
        ("SP", _explicit(b"\x00\x01"), 3),
    ]
    for item, sample, expected in checks:
        emitted = len(cat062.ENCODERS[item](sample))
        if emitted != expected:
            problems.append(f"{item}: expected {expected} octet(s) for that shape, encoder "
                            f"emitted {emitted}")

    # The REF's own length octet has to equal the octets it precedes, INCLUDING ITSELF — Appendix
    # A §2.1. A second length statement inside a record that already has one.
    ref = _ref(items={"tvs": {"vx_raw": 0, "vy_raw": 0},
                      "sts": {"fdr": 0, "lnav_ep": 0, "lnav_val": 0, "spare_bits_5_2": 0,
                              "fx": 0}})
    emitted = cat062.ENCODERS["RE"](ref)
    if len(emitted) != ref["length"] or emitted[0] != len(emitted):
        problems.append(f"RE: the length octet says {emitted[0]} and the field is {len(emitted)} "
                        "octets; Appendix A §2.1 makes the length include itself")

    if problems:
        raise AssertionError("layout(s) disagree with the standard's own byte counts:\n  "
                             + "\n  ".join(problems))


def _subfield_samples() -> dict[str, dict[str, dict]]:
    """A minimal sample per fixed-length subfield, for `check_layouts`."""
    ages_290 = {name: {"age_raw": 0} for octet in cat062._PRESENCE["I062/290"]
                for name, _bit in octet}
    ages_295 = {name: {"age_raw": 0} for octet in cat062._PRESENCE["I062/295"]
                for name, _bit in octet}
    return {
        "I062/110": {
            "sum": {"m5": 0, "id": 0, "da": 0, "m1": 0, "m2": 0, "m3": 0, "mc": 0, "x": 0},
            "pmn": {"spare_bits_32_31": 0, "pin": 0, "spare_bits_16_14": 0, "nat": 0,
                    "spare_bits_8_7": 0, "mis": 0},
            "pos": {"latitude_raw": 0, "longitude_raw": 0},
            "ga": {"spare_bit_16": 0, "res": 0, "ga_raw": 0},
            "em1": {"spare_bits_16_13": 0, "extended_mode_1": 0},
            "tos": {"tos_raw": 0},
            "xp": {"spare_bits_8_6": 0, "x5": 0, "xc": 0, "x3": 0, "x2": 0, "x1": 0},
        },
        "I062/290": ages_290,
        "I062/295": ages_295,
        "I062/340": {
            "sid": {"sac": 0, "sic": 0},
            "pos": {"rho_raw": 0, "theta_raw": 0},
            "hei": {"height_raw": 0},
            "mdc": {"v": 0, "g": 0, "mode_c_raw": 0},
            "mda": {"v": 0, "g": 0, "l": 0, "spare_bit_13": 0, "mode_3a": 0},
            "typ": {"typ": 0, "sim": 0, "rab": 0, "tst": 0, "spare_bits_2_1": 0},
        },
        "I062/380": {
            "adr": {"address": 0}, "id": {"characters_raw": 0}, "mhg": {"heading_raw": 0},
            "ias": {"im": 0, "air_speed_raw": 0}, "tas": {"true_airspeed_raw": 0},
            "sal": {"sas": 0, "source": 0, "altitude_raw": 0},
            "fss": {"mv": 0, "ah": 0, "am": 0, "altitude_raw": 0},
            "com": {"com": 0, "stat": 0, "spare_bits_10_9": 0, "ssc": 0, "arc": 0, "aic": 0,
                    "b1a": 0, "b1b": 0},
            "sab": {"ac": 0, "mn": 0, "dc": 0, "gbs": 0, "spare_bits_9_4": 0, "stat": 0},
            "acs": {"acas_ra": "00" * 7}, "bvr": {"vertical_rate_raw": 0},
            "gvr": {"vertical_rate_raw": 0}, "ran": {"roll_angle_raw": 0},
            "tar": {"ti": 0, "spare_bits_14_9": 0, "rate_of_turn_raw": 0, "spare_bit_1": 0},
            "tan": {"track_angle_raw": 0}, "gsp": {"ground_speed_raw": 0},
            "vun": {"velocity_uncertainty": 0}, "met": _met(0.0, 1.0, 0.0, 0),
            "emc": {"ecat": 0}, "pos": {"latitude_raw": 0, "longitude_raw": 0},
            "gal": {"geometric_altitude_raw": 0}, "pun": {"spare_bits_8_5": 0, "pun": 0},
            "iar": {"indicated_airspeed_raw": 0}, "mac": {"mach_number_raw": 0},
            "bps": {"spare_bits_16_13": 0, "bps_raw": 0},
        },
        "I062/390": {
            "tag": {"sac": 0, "sic": 0}, "csn": {"callsign_raw": "20" * 7},
            "ifi": {"typ": 0, "spare_bits_30_28": 0, "nbr": 0},
            "fct": {"gat_oat": 0, "fr": 0, "rvsm": 0, "hpr": 0, "spare_bit_1": 0},
            "tac": {"aircraft_type_raw": "20" * 4}, "wtc": {"wtc": 0},
            "dep": {"departure_raw": "20" * 4}, "dst": {"destination_raw": "20" * 4},
            "rds": {"nu1": 0, "nu2": 0, "ltr": 0},
            "cfl": {"cleared_flight_level_raw": 0}, "ctl": {"centre": 0, "position": 0},
            "ast": {"aircraft_stand_raw": "20" * 6},
            "sts": {"emp": 0, "avl": 0, "spare_bits_4_1": 0},
            "std": {"sid_raw": "20" * 7}, "sta": {"star_raw": "20" * 7},
            "pem": {"spare_bits_16_14": 0, "va": 0, "mode_3a": 0},
            "pec": {"pre_emergency_raw": "20" * 7},
        },
        "I062/500": {
            "apc": {"x_raw": 0, "y_raw": 0}, "cov": {"covariance_raw": 0},
            "apw": {"x_raw": 0, "y_raw": 0}, "aga": {"accuracy_raw": 0},
            "aba": {"accuracy_raw": 0}, "atv": {"x_raw": 0, "y_raw": 0},
            "aa": {"x_raw": 0, "y_raw": 0}, "arc": {"accuracy_raw": 0},
        },
    }


def main() -> None:
    check_layouts()
    written = 0
    for name, octets in fixtures().items():
        (FIXTURES / f"{name}.cat062").write_bytes(octets)
        parsed = cat062.parse_block(octets)
        (FIXTURES / f"{name}.parsed.json").write_text(
            json.dumps(parsed, indent=2, sort_keys=True) + "\n")
        written += 1
    refusal_dir = FIXTURES / "refusals"
    refusal_dir.mkdir(exist_ok=True)
    for name, octets in refusals().items():
        (refusal_dir / f"{name}.cat062").write_bytes(octets)
        written += 1
    print(f"wrote {written} fixtures into {FIXTURES} "
          f"({len(fixtures())} translatable, {len(refusals())} refusals)")


if __name__ == "__main__":
    main()
