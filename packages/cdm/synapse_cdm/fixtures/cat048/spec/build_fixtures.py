#!/usr/bin/env python3
"""Build the CAT048 fixture set. THE SOURCE OF TRUTH FOR BOTH ARTEFACTS.

    python build_fixtures.py                      # from the directory this file is in
    python -m synapse_cdm.harness --adapter cat048 --update-golden   # then READ it

Edit this file, never the `.cat048` octets and never the `.parsed.json` twins.

WHY A GENERATOR AND NOT HAND-EDITED BYTES
-----------------------------------------
A record's FSPEC and its block's LEN are both functions of the contents, so a hand-edited byte
file is a mis-parse waiting to happen and a hand-edited twin does not tell you what octets it
implies. Every fixture below is described by its FIELD VALUES and the octets are derived.

EVERYTHING IS SYNTHETIC
-----------------------
No recorded ASTERIX traffic, no real radar station, no real aircraft. SAC 0x25 is listed with an
explicitly empty country cell in the EUROCONTROL allocation tables pinned at
`../../cat021/spec/sac_pin.json`, and in no other regional table — see `../README.md` for the
evidence and for why 0x48, the obvious mnemonic, is Estonia and Micronesia. Aircraft addresses
come from the `0029xx` block the ADS-B and CAT021 sets use. Positions are polar and therefore
nowhere on the earth until a caller injects a site; the site the tests inject is in the Gulf of
Riga, matching the other sets.

THE LAYOUT SUMS AGAINST THE STANDARD'S OWN BYTE TOTALS
------------------------------------------------------
`_ITEM_OCTETS` states each item's length as §5.2 gives it, and `check_layouts()` asserts that
every encoder emits exactly that — so a fixture whose octet count drifts from the document fails
here rather than in a golden diff.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
FIXTURES = HERE.parent.parent
sys.path.insert(0, str(FIXTURES.parent.parent.parent))

from synapse_cdm.adapters import asterix_cat048 as cat048          # noqa: E402
from synapse_cdm.adapters import cat048_codec as codec             # noqa: E402

# --------------------------------------------------------------------- the identifiers

#: Pinned: listed-but-blank in the EUR table and in no other. `../README.md` carries the
#: evidence and the rejected candidates.
SAC = 0x25
SIC = 0x25
#: The second Radar System, for the §4.5.4 fixture. "By convention a dedicated and unambiguous
#: SAC/SIC code shall be assigned to every Radar System."
SIC_SECOND = 0x26

#: The ADS-B and CAT021 block. Everything below `004000` is in no administration's range.
ADDRESS = 0x0029AB
ADDRESS_SHARED_WITH_CAT021 = 0x0029AB
ADDRESS_SECOND = 0x0029AC

#: Fictional, marked as exercise traffic, matching the other sets character for character.
IDENT = "EXRDR01"
IDENT_HELO = "EXHELO2"

#: Twelve bits, station-scoped and recycled — which is what the identity fixture exercises.
TRACK_NUMBER = 199

TOD_0615 = round(6.25 * 3600 * 128)          # 06:15:00.000
TOD_0600 = round(6.0 * 3600 * 128)           # 06:00:00.000

# ------------------------------------------------------------------- the layout table
#
# Each item's octet count as §5.2 states it. Variable, compound and repetitive items state the
# rule instead of a number, because their length is a function of their contents.
_ITEM_OCTETS: dict[str, object] = {
    "I048/010": 2, "I048/140": 3, "I048/020": "1+", "I048/040": 4, "I048/070": 2,
    "I048/090": 2, "I048/130": "1+n", "I048/220": 3, "I048/240": 6, "I048/250": "1+8n",
    "I048/161": 2, "I048/042": 4, "I048/200": 4, "I048/170": "1+", "I048/210": 4,
    "I048/030": "1+", "I048/080": 2, "I048/100": 4, "I048/110": 2, "I048/120": "1+n",
    "I048/230": 2, "I048/260": 7, "I048/055": 1, "I048/050": 2, "I048/065": 1,
    "I048/060": 2, "SP": "1+n", "RE": "1+n",
}


def _fl(level: float) -> dict:
    # `to_raw` already applies the two's-complement conversion for a signed form, so applying
    # `twos_to_raw` on top of it converts twice — which the codec refuses rather than wrapping,
    # and that refusal is what caught this on the generator's first run.
    return {"v": 0, "g": 0, "flight_level_raw": codec.to_raw("flight_level", level)}


def _height(feet: float) -> dict:
    return {"spare_bits_16_15": 0, "height_raw": codec.to_raw("height_3d", feet)}


def _polar(rho_nm: float, theta_deg: float) -> dict:
    return {"rho_raw": codec.to_raw("rho", rho_nm), "theta_raw": codec.to_raw("theta", theta_deg)}


def _descriptor(typ: int, **flags) -> dict:
    out = {"typ": typ, "sim": False, "rdp": 0, "spi": False, "rab": False, "extensions": []}
    exts = flags.pop("extensions", None)
    out.update(flags)
    if exts:
        out["extensions"] = exts
    return out


def _ext1(**flags) -> dict:
    ext = {"tst": False, "err": False, "xpp": False, "me": False, "mi": False, "foe_fri": 0}
    ext.update(flags)
    ext["foe_fri_text"] = cat048.FOE_FRI_TEXT[ext["foe_fri"]]
    return ext


def _track_status(*, tre=0, gho=0, sup=0, tcc=0, cnf=0, rad=2, dou=0, mah=0, cdm=0,
                  spare=0, extent=True) -> dict:
    status = {"cnf": cnf, "rad": rad, "rad_text": cat048.RAD_TEXT[rad], "dou": dou,
              "mah": mah, "cdm": cdm, "cdm_text": cat048.CDM_TEXT[cdm]}
    if extent:
        status["extent"] = {"tre": tre, "gho": gho, "sup": sup, "tcc": tcc,
                            "spare_bits_4_2": spare}
    return status


def _mode_code(octal: str, *, v=0, g=0, l=0, spare=0) -> dict:
    raw = codec.encode_octal(octal, 4)
    return {"v": v, "g": g, "l": l, "spare_bit_13": spare, "code_raw": raw,
            "code_octal": codec.decode_octal(raw, 4)}


def _comms(*, com=1, stat=0, si=0, mssc=1, arc=1, aic=1, b1a=0, b1b=0, spare=0) -> dict:
    return {"com": com, "com_text": cat048.COM_TEXT.get(com), "stat": stat,
            "stat_text": cat048.STAT_TEXT.get(stat), "si": si, "spare_bit_9": spare,
            "mssc": mssc, "arc": arc, "aic": aic, "b1a": b1a, "b1b": b1b}


def _we(*codes: int) -> dict:
    return {"codes": [{"code": c, "text": cat048.WARNING_ERROR_TEXT.get(c)} for c in codes]}


def _explicit(payload: bytes) -> dict:
    """A one-octet length INCLUDING itself, then opaque contents."""
    return {"length": len(payload) + 1, "contents": payload.hex()}


def record(items: dict, *, fspec: bytes | None = None) -> bytes:
    """One record: the FSPEC then the present items in FRN order."""
    frns = sorted(cat048.FRN_BY_ITEM[item] for item in items)
    body = fspec if fspec is not None else codec.write_fspec(frns)
    for frn in frns:
        item = cat048.UAP_BY_FRN[frn][1]
        body += cat048.ENCODERS[item](items[item])
    return body


def block(*bodies: bytes) -> bytes:
    payload = b"".join(bodies)
    return bytes([cat048.CATEGORY]) + \
        codec.write_unsigned(len(payload) + cat048.BLOCK_HEADER_OCTETS, 2) + payload


# ---------------------------------------------------------------------- common records

def _base(typ: int = 5, tod: int = TOD_0600, **extra) -> dict:
    """I048/010 + I048/140 + I048/020, the mandatory core plus a time."""
    items = {
        "I048/010": {"sac": SAC, "sic": SIC},
        "I048/140": {"time_of_day_raw": tod},
        "I048/020": _descriptor(typ),
    }
    items.update(extra)
    return items


def _mode_s(tod: int = TOD_0600, **extra) -> dict:
    """A Mode S record, which needs I048/220 and I048/230 unless TRE is set."""
    items = _base(5, tod, **{
        "I048/220": {"address_raw": ADDRESS},
        "I048/230": _comms(),
    })
    items.update(extra)
    return items


# ============================================================================ fixtures


def fixtures() -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # -------------------------------------------------- the ordinary case
    out["mode_s_roll_call_track"] = block(record(_mode_s(**{
        "I048/040": _polar(55.5, 123.75),
        "I048/070": _mode_code("4271"),
        "I048/090": _fl(350.0),
        "I048/240": {"identification_raw": codec.encode_six_bit(IDENT),
                     "identification": IDENT},
        "I048/161": {"spare_bits_16_13": 0, "track_number": TRACK_NUMBER},
        "I048/170": _track_status(),
        "I048/200": {"groundspeed_raw": codec.to_raw("groundspeed", 0.13),
                     "heading_raw": codec.to_raw("heading", 91.5)},
    })))

    # The inversion audit: awkward values on purpose, so a rounding fault shows.
    out["derived_position_inverts_to_the_polar_values"] = block(record(_mode_s(**{
        "I048/040": _polar(137.99609375, 271.2304687500),
        "I048/110": _height(24975.0),
        "I048/170": _track_status(),
    })))

    # A site injected and no height at all: the documented no-geometry outcome.
    out["injected_site_no_height_item"] = block(record(_mode_s(**{
        "I048/040": _polar(40.25, 15.0),
        "I048/170": _track_status(),
    })))

    # The degraded branch: a pressure altitude standing in for a geometric height.
    out["injected_site_pressure_height_only"] = block(record(_mode_s(**{
        "I048/040": _polar(40.25, 15.0),
        "I048/090": _fl(350.0),
    })))

    # ERR set and RHO all-ones: a FLOOR, and no position may be derived from a bound.
    out["injected_site_range_at_maximum"] = block(record(_mode_s(**{
        "I048/020": _descriptor(5, extensions=[_ext1(err=True)]),
        "I048/040": {"rho_raw": 0xFFFF, "theta_raw": codec.to_raw("theta", 88.0)},
        "I048/110": _height(30000.0),
        "RE": _explicit(bytes.fromhex("0140")),
    })))

    # -------------------------------------------------- identity
    out["psr_only_plot_no_identity"] = block(record(_base(1, **{
        "I048/040": _polar(12.5, 300.0),
    })))

    out["psr_plot_with_track_number_only"] = block(record(_base(1, **{
        "I048/040": _polar(12.5, 300.0),
        "I048/161": {"spare_bits_16_13": 0, "track_number": TRACK_NUMBER},
        "I048/170": _track_status(rad=1),
    })))

    # The same track number one scan later, at a different measurement. Two records in one
    # block so the test can assert two DIFFERENT entity_ids from one payload.
    out["psr_track_two_scans_same_track_number"] = block(
        record(_base(1, **{
            "I048/040": _polar(12.5, 300.0),
            "I048/161": {"spare_bits_16_13": 0, "track_number": TRACK_NUMBER},
            "I048/170": _track_status(rad=1),
        })),
        record(_base(1, tod=TOD_0600 + 512, **{
            "I048/040": _polar(12.9, 300.4),
            "I048/161": {"spare_bits_16_13": 0, "track_number": TRACK_NUMBER},
            "I048/170": _track_status(rad=1),
        })),
    )

    out["no_detection_track_only"] = block(record(_base(0, **{
        "I048/040": _polar(60.0, 200.0),
        "I048/110": _height(28000.0),
        "I048/161": {"spare_bits_16_13": 0, "track_number": 77},
        "I048/170": _track_status(),
        "I048/200": {"groundspeed_raw": codec.to_raw("groundspeed", 0.11),
                     "heading_raw": codec.to_raw("heading", 200.0)},
    })))

    # -------------------------------------------------- End of Track
    out["end_of_track_full_items"] = block(record(_mode_s(**{
        "I048/161": {"spare_bits_16_13": 0, "track_number": TRACK_NUMBER},
        "I048/170": _track_status(tre=1),
        "I048/240": {"identification_raw": codec.encode_six_bit(IDENT),
                     "identification": IDENT},
        "I048/250": {"rep": 1, "registers": [{"data": "20" + "00" * 6, "bds1": 2, "bds2": 0,
                                              "extraction": "GICB register 2,0"}]},
    })))

    # The relaxation: TRE set and all four relaxed items absent. A PERMITTED absence.
    out["end_of_track_items_omitted"] = block(record(_base(5, **{
        "I048/161": {"spare_bits_16_13": 0, "track_number": TRACK_NUMBER},
        "I048/170": _track_status(tre=1),
    })))

    # -------------------------------------------------- time
    out["time_of_day_exactly_86400"] = block(record(_mode_s(
        tod=codec.to_raw("tod", 86400.0))))

    out["midnight_rollover_before"] = block(record(_mode_s(
        tod=round((23 * 3600 + 59 * 60 + 58.5) * 128))))

    out["midnight_rollover_after"] = block(record(_mode_s(tod=round(0.9 * 128))))

    out["no_time_item_at_all"] = block(record({
        "I048/010": {"sac": SAC, "sic": SIC},
        "I048/020": _descriptor(5, extensions=[]),
        "I048/220": {"address_raw": ADDRESS},
        "I048/230": _comms(),
        "I048/040": _polar(30.0, 45.0),
    }))

    # -------------------------------------------------- altitude
    out["three_altitudes_disagreeing"] = block(record(_mode_s(**{
        "I048/040": _polar(48.0, 66.0),
        "I048/090": _fl(350.0),
        "I048/100": {"v": 1, "g": 0, "spare_bits_30_29": 0, "mode_c_gray_raw": 0b101010101010,
                     "spare_bits_16_13": 0, "quality_bits": [0] * 12},
        "I048/110": _height(35600.0),
        "I048/030": _we(18, 12),
    })))

    out["flight_level_negative"] = block(record(_mode_s(**{
        "I048/090": _fl(-12.5),
    })))

    # -------------------------------------------------- warning/error
    out["warning_error_code_series"] = block(record(_mode_s(**{
        "I048/030": _we(0, 15, 33, 34, 9, 96),
    })))

    out["warning_error_code_37"] = block(record(_mode_s(**{
        "I048/030": _we(37),
        "RE": _explicit(bytes.fromhex("05aa")),
    })))

    out["ic_conflict_codes"] = block(record(_mode_s(**{
        "I048/030": _we(35, 36),
    })))

    # -------------------------------------------------- Doppler
    out["radial_doppler_calculated"] = block(record(_mode_s(**{
        "I048/120": {"primary": {"cal": True, "rds": False},
                     "cal": {"doubtful": True, "spare_bits_15_11": 0,
                             "cal_raw": codec.to_raw("doppler", -142.0),
                             "calculated_doppler_mps": -142.0}},
    })))

    out["radial_doppler_both_subfields"] = block(record(_mode_s(**{
        "I048/120": {"primary": {"cal": True, "rds": True},
                     "cal": {"doubtful": False, "spare_bits_15_11": 0,
                             "cal_raw": 90, "calculated_doppler_mps": 90.0},
                     "rds": {"rep": 2, "dop_raw": 90, "amb_raw": 512, "frq_raw": 1090,
                             "doppler_mps": 90.0, "ambiguity_mps": 512.0,
                             "frequency_mhz": 1090.0}},
    })))

    # -------------------------------------------------- the REF and the SP
    out["mode_4_result_in_ref"] = block(record(_mode_s(**{
        "I048/020": _descriptor(5, extensions=[_ext1(mi=True, foe_fri=0)]),
        "RE": _explicit(bytes.fromhex("0203ff")),
    })))

    out["special_purpose_field_opaque"] = block(record(_mode_s(**{
        "SP": _explicit(bytes.fromhex("deadbeef")),
    })))

    out["reserved_expansion_field_carried"] = block(record(_mode_s(**{
        "RE": _explicit(bytes.fromhex("0102030405")),
        "SP": _explicit(bytes.fromhex("77")),
    })))

    # -------------------------------------------------- emergency and ACAS
    out["military_emergency"] = block(record(_mode_s(**{
        "I048/020": _descriptor(5, extensions=[_ext1(me=True)]),
    })))

    out["mode_s_alert_is_not_an_emergency"] = block(record(_mode_s(**{
        "I048/230": _comms(stat=2),
        "I048/260": {"acas_ra": "30" + "00" * 6},
    })))

    out["acas_ra_active_undecoded"] = block(record(_mode_s(**{
        "I048/020": _descriptor(5, extensions=[
            _ext1(),
            {"adsb": {"populated": False, "available": False},
             "scn": {"populated": False, "available": False},
             "pai": {"populated": False, "available": False}, "spare_bit_2": 0},
            {"acasxv": {"populated": True, "value": 2, "text": cat048.ACASXV_TEXT[2]},
             "poxpr": {"populated": True, "supported": True}},
        ]),
        "I048/260": {"acas_ra": "3141592653589a"},
        "I048/250": {"rep": 1, "registers": [{"data": "31" + "11" * 6, "bds1": 3, "bds2": 1,
                                              "extraction": "GICB register 3,1"}]},
    })))

    out["bds_registers_comm_b_broadcast"] = block(record(_mode_s(**{
        "I048/250": {"rep": 2, "registers": [
            {"data": "00" * 7, "bds1": 0, "bds2": 0,
             "extraction": "Comm-B broadcast, register unidentified"},
            {"data": "40" + "22" * 6, "bds1": 4, "bds2": 0,
             "extraction": "GICB register 4,0"},
        ]},
    })))

    # -------------------------------------------------- track status
    out["ghost_target_still_translated"] = block(record(_mode_s(**{
        "I048/161": {"spare_bits_16_13": 0, "track_number": 512},
        "I048/170": _track_status(gho=1, sup=1, tcc=1),
    })))

    out["radial_ambiguity_rad_invalid"] = block(record(_mode_s(**{
        "I048/161": {"spare_bits_16_13": 0, "track_number": 1024},
        "I048/170": _track_status(rad=3, cdm=3, dou=1, mah=1, cnf=1),
    })))

    out["track_quality_vector"] = block(record(_mode_s(**{
        "I048/161": {"spare_bits_16_13": 0, "track_number": 88},
        "I048/170": _track_status(),
        "I048/200": {"groundspeed_raw": codec.to_raw("groundspeed", 0.09),
                     "heading_raw": codec.to_raw("heading", 359.9945068359375)},
        "I048/210": {"sigma_x_raw": 12, "sigma_y_raw": 9, "sigma_v_raw": 4, "sigma_h_raw": 7,
                     "sigma_x_nm": codec.from_raw("sigma_position", 12),
                     "sigma_y_nm": codec.from_raw("sigma_position", 9),
                     "sigma_v_nm_s": codec.from_raw("sigma_speed", 4),
                     "sigma_h_deg": codec.from_raw("sigma_heading", 7)},
    })))

    # -------------------------------------------------- multi-record and cross-adapter
    out["plot_and_track_one_block"] = block(
        record(_base(1, **{"I048/040": _polar(20.0, 100.0)})),
        record(_mode_s(**{
            "I048/040": _polar(20.05, 100.1),
            "I048/161": {"spare_bits_16_13": 0, "track_number": 300},
            "I048/170": _track_status(),
        })),
    )

    out["icao24_shared_with_cat021"] = block(record(_mode_s(**{
        "I048/220": {"address_raw": ADDRESS_SHARED_WITH_CAT021},
        "I048/040": _polar(33.0, 210.0),
        "I048/110": _height(31000.0),
    })))

    out["two_stations_one_block"] = block(
        record(_mode_s(**{"I048/040": _polar(15.0, 30.0)})),
        record({
            "I048/010": {"sac": SAC, "sic": SIC_SECOND},
            "I048/140": {"time_of_day_raw": TOD_0600 + 64},
            "I048/020": _descriptor(5),
            "I048/220": {"address_raw": ADDRESS_SECOND},
            "I048/230": _comms(),
            "I048/040": _polar(15.4, 30.6),
        }),
    )

    # -------------------------------------------------- Mode codes and plot characteristics
    out["mode_1_and_mode_2_with_confidence"] = block(record(_mode_s(**{
        "I048/050": _mode_code("0037", l=1),
        "I048/055": {"v": 0, "g": 0, "l": 1, "code_raw": 0o13,
                     "code_octal": codec.decode_octal(0o13, 2)},
        "I048/060": {"spare_bits_16_13": 0,
                     "quality_bits": [0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0]},
        "I048/065": {"spare_bits_8_6": 0, "quality_bits": [0, 1, 0, 0, 0]},
        "I048/070": _mode_code("4271", g=1),
        "I048/080": {"spare_bits_16_13": 0,
                     "quality_bits": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
        "I048/030": _we(21, 22),
    })))

    out["plot_characteristics_all_subfields"] = block(record(_mode_s(**{
        "I048/130": {
            "primary": {"srl": True, "srr": True, "sam": True, "prl": True, "pam": True,
                        "rpd": True, "apd": True},
            "srl": {"raw": 60, "ssr_plot_runlength_deg": codec.from_raw("runlength", 60)},
            "srr": {"raw": 4, "ssr_reply_count": 4.0},
            "sam": {"raw": codec.to_raw("amplitude", -71.0),
                    "ssr_amplitude_dbm": -71.0},
            "prl": {"raw": 48, "psr_plot_runlength_deg": codec.from_raw("runlength", 48)},
            "pam": {"raw": codec.to_raw("amplitude", -93.0),
                    "psr_amplitude_dbm": -93.0},
            "rpd": {"raw": 0x7F,
                    "range_difference_nm": codec.from_raw("range_difference", 0x7F)},
            "apd": {"raw": 0x7F,
                    "azimuth_difference_deg": codec.from_raw("azimuth_difference", 0x7F)},
        },
        "I048/042": {"x_raw": codec.to_raw("cartesian", -12.5),
                     "y_raw": codec.to_raw("cartesian", 44.25),
                     "x_nm": -12.5, "y_nm": 44.25},
        "I048/170": _track_status(tcc=1),
    })))

    # -------------------------------------------------- spare bits and a long FSPEC
    # §4.4's zeroing is a RECOMMENDATION, so a conforming encoder may set them to anything and
    # the byte-exact round trip only survives if they are parked as sent.
    out["spare_bits_nonzero"] = block(record(_mode_s(**{
        "I048/050": _mode_code("0037", spare=1),
        "I048/161": {"spare_bits_16_13": 0b1011, "track_number": TRACK_NUMBER},
        "I048/170": _track_status(spare=0b101),
        "I048/230": _comms(spare=1),
    })))

    # A longer-than-necessary FSPEC. A conforming encoder emits the shortest one covering its
    # highest FRN, but the specification does not forbid a longer one, and the round trip is
    # byte-exact only if we re-emit what we read.
    mandatory = {
        "I048/010": {"sac": SAC, "sic": SIC},
        "I048/140": {"time_of_day_raw": TOD_0615},
        "I048/020": _descriptor(1),
    }
    long_fspec = bytes([0b11100001, 0b00000001, 0b00000001, 0b00000000])
    out["fspec_longer_than_necessary"] = block(record(mandatory, fspec=long_fspec))

    out["helicopter_classification_not_read_as_a_type"] = block(record(_mode_s(**{
        "I048/030": _we(24),
        "I048/240": {"identification_raw": codec.encode_six_bit(IDENT_HELO),
                     "identification": IDENT_HELO},
    })))

    out["field_monitor_report"] = block(record(_mode_s(**{
        "I048/020": _descriptor(5, rab=True, spi=True, extensions=[_ext1(tst=True, xpp=True)]),
    })))

    return out


def refusals() -> dict[str, bytes]:
    """Payloads that are MEANT to raise. Exercised from `tests/`, not by the harness."""
    out: dict[str, bytes] = {}
    core = record(_mode_s())

    wrong = bytearray(block(core))
    wrong[0] = 21
    out["wrong_category"] = bytes(wrong)

    short = bytearray(block(core))
    short[2] = (short[2] + 4) & 0xFF
    out["length_disagrees_with_buffer"] = bytes(short)

    # I048/140 one LSB past §5.2.17's inclusive stated range. A modulo would move the contact
    # by hours and leave every other check passing.
    out["time_of_day_one_lsb_past_86400"] = block(record(_mode_s(
        tod=codec.to_raw("tod", 86400.0) + 1)))

    # The FSPEC's fourth octet sets its FX bit and there is no FRN 29.
    out["trailing_fspec_fx_set"] = block(
        bytes([0b11100001, 0b00000001, 0b00000001, 0b00000001])
        + cat048.ENCODERS["I048/010"]({"sac": SAC, "sic": SIC})
        + cat048.ENCODERS["I048/140"]({"time_of_day_raw": TOD_0600})
        + cat048.ENCODERS["I048/020"](_descriptor(1))
    )

    # I048/170's first extent sets its FX and §5.2.19 defines no second extent.
    status = cat048.ENCODERS["I048/170"](_track_status())
    out["track_status_second_extent"] = block(
        codec.write_fspec([1, 2, 3, 14])
        + cat048.ENCODERS["I048/010"]({"sac": SAC, "sic": SIC})
        + cat048.ENCODERS["I048/140"]({"time_of_day_raw": TOD_0600})
        + cat048.ENCODERS["I048/020"](_descriptor(1))
        + bytes([status[0], status[1] | codec.FX])
    )

    # I048/020's FIFTH extension sets its FX bit and §5.2.2 defines no sixth. THE THIRD
    # "FX to nowhere" in this category, and the ruling document recorded only two — see the
    # close-out. Same refusal as I048/170's second extent and Table 2's fourth FX.
    descriptor = bytearray(cat048.ENCODERS["I048/020"](_descriptor(1, extensions=[
        _ext1(),
        {"adsb": {"populated": False, "available": False},
         "scn": {"populated": False, "available": False},
         "pai": {"populated": False, "available": False}, "spare_bit_2": 0},
        {"acasxv": {"populated": False, "value": 0, "text": cat048.ACASXV_TEXT[0]},
         "poxpr": {"populated": False, "supported": False}},
        {"poact": {"populated": False, "active": False},
         "dtfxpr": {"populated": False, "supported": False},
         "dtfact": {"populated": False, "active": False}, "spare_bit_2": 0},
        {"irmxpr": {"populated": False, "capable": False},
         "irmact": {"populated": False, "active": False}, "spare_bits_4_2": 0},
    ])))
    descriptor[-1] |= codec.FX
    out["descriptor_sixth_extension"] = block(
        codec.write_fspec([1, 2, 3])
        + cat048.ENCODERS["I048/010"]({"sac": SAC, "sic": SIC})
        + cat048.ENCODERS["I048/140"]({"time_of_day_raw": TOD_0600})
        + bytes(descriptor)
    )

    # I048/120's primary subfield sets a bit in 6/2 — presence bits for subfields #3/7, which
    # §5.2.15 documents as Spare and does not define.
    out["radial_doppler_spare_presence_bit"] = block(
        codec.write_fspec([1, 2, 3, 20])
        + cat048.ENCODERS["I048/010"]({"sac": SAC, "sic": SIC})
        + cat048.ENCODERS["I048/140"]({"time_of_day_raw": TOD_0600})
        + cat048.ENCODERS["I048/020"](_descriptor(1))
        + bytes([0b00100000])
    )

    # I048/130's primary subfield sets its FX and only seven subfields are defined.
    out["plot_characteristics_second_primary_octet"] = block(
        codec.write_fspec([1, 2, 3, 7])
        + cat048.ENCODERS["I048/010"]({"sac": SAC, "sic": SIC})
        + cat048.ENCODERS["I048/140"]({"time_of_day_raw": TOD_0600})
        + cat048.ENCODERS["I048/020"](_descriptor(1))
        + bytes([0b10000001, 0x3C, 0x00])
    )

    # A Mode S record with TRE clear and no I048/220.
    out["mode_s_target_missing_address"] = block(record({
        "I048/010": {"sac": SAC, "sic": SIC},
        "I048/140": {"time_of_day_raw": TOD_0600},
        "I048/020": _descriptor(5),
        "I048/230": _comms(),
    }))

    # A record with no I048/010, which §5.2.1 says shall be present in every ASTERIX record.
    out["missing_mandatory_data_source"] = block(record({
        "I048/140": {"time_of_day_raw": TOD_0600},
        "I048/020": _descriptor(1),
    }))

    # The records do not tile LEN: a trailing partial record.
    padded = bytearray(block(core))
    padded += bytes([0x80])
    padded[1:3] = codec.write_unsigned(len(padded), 2)
    out["records_do_not_tile_len"] = bytes(padded)

    return out


def check_layouts() -> None:
    """Every encoder emits exactly the octet count §5.2 states. Fails here, not in a diff."""
    problems = []
    samples = {
        "I048/010": {"sac": 1, "sic": 2},
        "I048/140": {"time_of_day_raw": 5},
        "I048/040": _polar(1.0, 2.0),
        "I048/042": {"x_raw": 1, "y_raw": 2},
        "I048/070": _mode_code("0000"),
        "I048/050": _mode_code("0000"),
        "I048/055": {"v": 0, "g": 0, "l": 0, "code_raw": 0},
        "I048/060": {"spare_bits_16_13": 0, "quality_bits": [0] * 12},
        "I048/065": {"spare_bits_8_6": 0, "quality_bits": [0] * 5},
        "I048/080": {"spare_bits_16_13": 0, "quality_bits": [0] * 12},
        "I048/090": _fl(0.0),
        "I048/100": {"v": 0, "g": 0, "spare_bits_30_29": 0, "mode_c_gray_raw": 0,
                     "spare_bits_16_13": 0, "quality_bits": [0] * 12},
        "I048/110": _height(0.0),
        "I048/161": {"spare_bits_16_13": 0, "track_number": 0},
        "I048/200": {"groundspeed_raw": 0, "heading_raw": 0},
        "I048/210": {"sigma_x_raw": 0, "sigma_y_raw": 0, "sigma_v_raw": 0, "sigma_h_raw": 0},
        "I048/220": {"address_raw": 0},
        "I048/230": _comms(),
        "I048/240": {"identification_raw": 0},
        "I048/260": {"acas_ra": "00" * 7},
    }
    for item, expected in _ITEM_OCTETS.items():
        if not isinstance(expected, int):
            continue
        emitted = len(cat048.ENCODERS[item](samples[item]))
        if emitted != expected:
            problems.append(f"{item}: §5.2 states {expected} octet(s), encoder emitted {emitted}")
    # The variable, compound and repetitive items, at a stated shape each.
    checks = [
        ("I048/020", _descriptor(1), 1),
        ("I048/020", _descriptor(1, extensions=[_ext1()]), 2),
        ("I048/030", _we(1), 1),
        ("I048/030", _we(1, 2, 3), 3),
        ("I048/170", _track_status(extent=False), 1),
        ("I048/170", _track_status(), 2),
        # §5.2.15: a one-octet primary, then subfield #1 (2 octets) or #2 (7 octets).
        ("I048/120", {"primary": {"cal": True, "rds": False},
                      "cal": {"doubtful": False, "spare_bits_15_11": 0, "cal_raw": 0}}, 3),
        ("I048/120", {"primary": {"cal": False, "rds": True},
                      "rds": {"rep": 0, "dop_raw": 0, "amb_raw": 0, "frq_raw": 0}}, 8),
        # §5.2.16: a one-octet primary plus one octet per present subfield.
        ("I048/130", {"primary": {"srl": True}, "srl": {"raw": 0}}, 2),
        # §5.2.25: "1+8*n" — a one-octet REP then eight octets per register.
        ("I048/250", {"rep": 1, "registers": [{"data": "00" * 7, "bds1": 0, "bds2": 0}]}, 9),
        ("I048/250", {"rep": 2, "registers": [{"data": "00" * 7, "bds1": 0, "bds2": 0}] * 2}, 17),
    ]
    for item, sample, expected in checks:
        emitted = len(cat048.ENCODERS[item](sample))
        if emitted != expected:
            problems.append(f"{item}: expected {expected} octet(s) for that shape, "
                            f"encoder emitted {emitted}")
    if problems:
        raise AssertionError("layout(s) disagree with the standard's own byte counts:\n  "
                             + "\n  ".join(problems))


def main() -> None:
    check_layouts()
    written = 0
    for name, octets in fixtures().items():
        (FIXTURES / f"{name}.cat048").write_bytes(octets)
        parsed = cat048.parse_block(octets)
        (FIXTURES / f"{name}.parsed.json").write_text(
            json.dumps(parsed, indent=2, sort_keys=True) + "\n")
        written += 1
    refusal_dir = FIXTURES / "refusals"
    refusal_dir.mkdir(exist_ok=True)
    for name, octets in refusals().items():
        (refusal_dir / f"{name}.cat048").write_bytes(octets)
        written += 1
    print(f"wrote {written} fixtures into {FIXTURES} "
          f"({len(fixtures())} translatable, {len(refusals())} refusals)")


if __name__ == "__main__":
    main()
