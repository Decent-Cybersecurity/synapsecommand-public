#!/usr/bin/env python3
"""Build the CAT034 fixture set. THE SOURCE OF TRUTH FOR BOTH ARTEFACTS.

    python packages/cdm/synapse_cdm/fixtures/cat034/spec/build_fixtures.py
    PYTHONPATH=packages/cdm python -m synapse_cdm.harness --adapter cat034 \
        --fixtures packages/cdm/synapse_cdm/fixtures/cat034 --update-golden   # then READ it

Edit this file, never the `.cat034` octets and never the `.parsed.json` twins.

WHY A GENERATOR AND NOT HAND-EDITED BYTES
-----------------------------------------
A record's FSPEC and its block's LEN are both functions of the contents, so a hand-edited byte
file is a mis-parse waiting to happen and a hand-edited twin does not tell you what octets it
implies. Every fixture below is described by its FIELD VALUES and the octets are derived.

EVERYTHING IS SYNTHETIC
-----------------------
No recorded ASTERIX traffic and no real radar head. `SAC = 0x29` is listed with an explicitly
empty country cell in the EUROCONTROL allocation tables pinned at `../../cat021/spec/sac_pin.json`
and in no other regional table — the evidence transfers to Part 2b by CITATION, because §5.2.2's
NOTE points at the same published list the CAT021 row does. `SIC` carries no allocation claim.
Station coordinates are in the Gulf of Riga, matching the other five sets.

THE LAYOUT SUMS AGAINST THE STANDARD'S OWN BYTE TOTALS
------------------------------------------------------
`_ITEM_OCTETS` states each item's length as §5.2 and Table 3 give it, and `check_layouts()`
asserts that every encoder emits exactly that — so a fixture whose octet count drifts from the
document fails here rather than in a golden diff. `tests/test_cdm_asterix_cat034_adapter.py`
calls it, so it cannot be skipped by not running this file.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
FIXTURES = HERE.parent.parent
sys.path.insert(0, str(FIXTURES.parent.parent.parent))

from synapse_cdm.adapters import asterix_cat034 as cat034          # noqa: E402
from synapse_cdm.adapters import cat034_codec as codec             # noqa: E402

# --------------------------------------------------------------------- the identifiers

#: Pinned by citation: listed-but-blank in the EUR table and in no other. `../README.md` carries
#: the evidence and the reason a second retrieval was not needed.
SAC = 0x29
SIC = 0x29

#: The Gulf of Riga, off Ventspils. Baltic-plausible and no real radar head.
STATION_LAT = 57.39
STATION_LON = 21.56
#: NEGATIVE, and the sign is the point: §5.2.12's height is "Signed ... expressed in meters above
#: WGS 84 reference ellipsoid", so a station below the ellipsoid is a legal value and this is the
#: one fixture that carries the two's-complement pattern for it end to end.
STATION_HEIGHT_M = -12.0

#: 06:00:00.000, fifteen minutes before `times.FROZEN_NOW`, so every ordinary fixture resolves on
#: the receipt date and only the rollover fixture does anything else.
TOD_0600 = 6 * 3600 * 128
#: 23:59:59.000 and 00:00:01.000 — the rollover pair. See `midnight_rollover_nearest`.
TOD_2359 = (23 * 3600 + 59 * 60 + 59) * 128
TOD_0000 = 1 * 128

# ------------------------------------------------------------------- the layout table
#
# Each item's octet count as §5.2 states it and Table 3 repeats it. The compound and repetitive
# items state the rule instead of a number, because their length is a function of their contents.
_ITEM_OCTETS: dict[str, object] = {
    "I034/010": 2, "I034/000": 1, "I034/030": 3, "I034/020": 1, "I034/041": 2,
    "I034/050": "1+", "I034/060": "1+", "I034/070": "(1+2*N)", "I034/100": 8,
    "I034/110": 1, "I034/120": 8, "I034/090": 2, "RE": "1+1+", "SP": "1+1+",
}


# ----------------------------------------------------------------------- item builders

def _primary(*, com=0, psr=0, ssr=0, mds=0) -> dict:
    """The I034/050 / I034/060 primary subfield. Every spare bit and FX explicitly zero."""
    return {"com": com, "spare_bit_7": 0, "spare_bit_6": 0, "psr": psr, "ssr": ssr,
            "mds": mds, "spare_bit_2": 0, "fx": 0}


def _tod(raw: int) -> dict:
    return {"time_of_day_raw": raw}


def _sector(degrees: float) -> dict:
    return {"sector_raw": codec.to_raw("sector", degrees)}


def _rotation(period_s: float) -> dict:
    return {"rotation_raw": codec.to_raw("rotation_period", period_s)}


def _collimation(range_nm: float, azimuth_deg: float) -> dict:
    return {"range_error_raw": codec.to_raw("range_error", range_nm),
            "azimuth_error_raw": codec.to_raw("azimuth_error", azimuth_deg)}


def _window(rho_start: float, rho_end: float, theta_start: float, theta_end: float) -> dict:
    return {"rho_start_raw": codec.to_raw("rho", rho_start),
            "rho_end_raw": codec.to_raw("rho", rho_end),
            "theta_start_raw": codec.to_raw("theta", theta_start),
            "theta_end_raw": codec.to_raw("theta", theta_end)}


def _position(lat: float, lon: float, height_m: float) -> dict:
    return {"height_raw": codec.to_raw("height", height_m),
            "latitude_raw": codec.to_raw("latitude", lat),
            "longitude_raw": codec.to_raw("longitude", lon)}


def _counters(*pairs: tuple[int, int]) -> dict:
    return {"rep": len(pairs),
            "counters": [{"typ": typ, "counter": count} for typ, count in pairs]}


def _explicit(payload: bytes) -> dict:
    """A one-octet length INCLUDING itself, then opaque contents."""
    return {"length": len(payload) + 1, "contents": payload.hex()}


def record(items: dict, *, fspec: bytes | None = None) -> bytes:
    """One record: the FSPEC then the present items in FRN order."""
    frns = sorted(cat034.FRN_BY_ITEM[item] for item in items)
    body = fspec if fspec is not None else codec.write_fspec(frns)
    for frn in frns:
        item = cat034.UAP_BY_FRN[frn][1]
        body += cat034.ENCODERS[item](items[item])
    return body


def block(*bodies: bytes) -> bytes:
    payload = b"".join(bodies)
    return bytes([cat034.CATEGORY]) + \
        codec.write_unsigned(len(payload) + cat034.BLOCK_HEADER_OCTETS, 2) + payload


def _base(message_type: int, tod: int | None = TOD_0600, **extra) -> dict:
    """I034/010 + I034/000, the two items M in every column of Table 2, plus a time."""
    items: dict = {
        "I034/010": {"sac": SAC, "sic": SIC},
        "I034/000": {"message_type": message_type},
    }
    if tod is not None:
        items["I034/030"] = _tod(tod)
    items.update(extra)
    return items


# ============================================================================ fixtures


def fixtures() -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # ------------------------------------------------- the shortest legal record
    # Type 001 with only its M items. One FSPEC octet, and a parser that assumed FRN order
    # equalled item-number order would read I034/000 where I034/030 is: Table 3 puts I034/010 at
    # FRN 1, I034/000 at FRN 2 and I034/030 at FRN 3, so the wire order is 010, 000, 030.
    out["north_marker_minimal"] = block(record(_base(1)))

    # ------------------------------------------------- the sweep
    # Type 002 with the sector number and the antenna rotation period. ALSO A TABLE 2 `X` CASE,
    # and deliberately so: Table 2 makes I034/041 O for a North Marker and X for a Sector
    # Crossing, so this record says more than its type admits. It is parked and named in
    # attributes.table_2_disposition rather than refused — the asymmetry _check_table_2 argues.
    out["sector_crossing_with_rotation"] = block(record(_base(
        2, **{"I034/020": _sector(123.75), "I034/041": _rotation(4.0)})))

    # ------------------------------------------------- the station's own position
    out["station_position_three_dimensional"] = block(record(_base(
        1, **{"I034/120": _position(STATION_LAT, STATION_LON, STATION_HEIGHT_M)})))

    # ------------------------------------------------- the two compound items
    # All four secondary subfields present, and CH-A/B = 11 in all three sensor subfields, which
    # is what makes the three different wordings visible under three separate keys.
    out["system_status_all_four_subfields"] = block(record(_base(1, **{
        "I034/050": {
            "primary": _primary(com=1, psr=1, ssr=1, mds=1),
            "com": {"nogo": 1, "rdpc": 1, "rdpr": 0, "ovl_rdp": 1, "ovl_xmt": 0, "msc": 1,
                    "tsv": 1, "spare_bit_1": 0},
            "psr": {"ant": 1, "ch_ab": 3, "ovl": 1, "msc": 0, "spare_bits_3_1": 0},
            "ssr": {"ant": 0, "ch_ab": 3, "ovl": 0, "msc": 1, "spare_bits_3_1": 0},
            "mds": {"ant": 1, "ch_ab": 3, "ovl_sur": 1, "msc": 0, "scf": 1, "dlf": 0,
                    "ovl_scf": 1, "ovl_dlf": 1, "spare_bits_7_1": 0},
        },
    })))

    # Every reduction field non-zero, so that a merge of the two compound items into one bag
    # would show up as a collision rather than as a quietly overwritten key.
    out["processing_mode_reduction_steps"] = block(record(_base(1, **{
        "I034/060": {
            "primary": _primary(com=1, psr=1, ssr=1, mds=1),
            "com": {"spare_bit_8": 0, "red_rdp": 3, "red_xmt": 5, "spare_bit_1": 0},
            "psr": {"pol": 1, "red_rad": 2, "stc": 3, "spare_bits_2_1": 0},
            "ssr": {"red_rad": 6, "spare_bits_5_1": 0},
            "mds": {"red_rad": 7, "clu": 1, "spare_bits_4_1": 0},
        },
    })))

    # ------------------------------------------------- the counters
    # One counter of every defined TYP, 0 to 20, in order, plus a DUPLICATE of TYP 0 at the end:
    # §5.2.8 does not say the TYPs are unique, order is data, and a set-valued park would lose
    # both facts. The counter values are the TYP times ten so a transposition is visible.
    out["message_counts_twenty_one_types"] = block(record(_base(1, **{
        "I034/070": _counters(*[(typ, typ * 10) for typ in range(21)], (0, 7)),
    })))

    # ------------------------------------------------- the three jamming strobes
    # Type 004. ALERT and WARNING, and GNSS_INTERFERENCE never set. I034/100 is M here.
    out["jamming_strobe_is_not_gnss"] = block(record(_base(
        4, **{"I034/100": _window(12.0, 48.0, 90.0, 135.0)})))

    # Type 007, the newest type in the pinned edition — Edition 1.29's change record reads
    # "Data Item I034/000: new message types 6&7", so an adapter written against Edition 1.28
    # would classify this record as an undefined type instead of as an ALERT.
    out["mode_s_jamming_strobe"] = block(record(_base(
        7, **{"I034/100": _window(0.0, 256.0 - 1 / 256.0, 0.0, 359.9945068359375)})))

    # ------------------------------------------------- geographical filtering
    # Type 003: the polar window parked as four raw fields with NO Geometry, and I034/110 = 0,
    # which §5.2.11 spells "invalid value" — so it lands in unresolved_raw and never reads as
    # "no filter". I034/110 is M for this type; I034/100 is O.
    out["geographical_filter_polar_window"] = block(record(_base(
        3, **{"I034/100": _window(5.0, 25.0, 300.0, 330.0), "I034/110": {"typ": 0}})))

    # ------------------------------------------------- the solar storm
    # Type 005, the type Edition 1.28 added. Translated and not refused.
    out["solar_storm_message"] = block(record(_base(
        5, **{"I034/100": _window(0.0, 256.0 - 1 / 256.0, 0.0, 359.9945068359375)})))

    # ------------------------------------------------- the permitted absence
    # Type 004 with no I034/030 at all. §5.2.4's Encoding Rule permits it; the absence lands in
    # attributes.unavailable_fields and observed_at falls back to the injected clock.
    out["time_of_day_absent_where_optional"] = block(record(_base(
        4, tod=None, **{"I034/100": _window(30.0, 60.0, 200.0, 240.0)})))

    # ------------------------------------------------- the midnight wrap
    # TWO RECORDS, and the fixture is built so the wrap happens under the HARNESS'S OWN frozen
    # clock rather than only under one a test injects — the failure `../../README.md` records
    # for CAT048's two rollover fixtures, which described times that resolved to the receipt
    # date at the frozen instant and so tested no rollover in either direction.
    #
    # times.FROZEN_NOW is 2026-04-29T06:15:00Z. Record 0's 23:59:59 is 6 h 15 min from the
    # PREVIOUS day's instant and 17 h 45 min from the receipt day's, so the previous day wins and
    # a rollover is applied. Record 1's 00:00:01 is 6 h 15 min from the receipt day's own
    # instant, which wins. The forward roll is unreachable from a 06:15 receipt time by
    # construction and is asserted in the test module against an injected late-evening clock.
    out["midnight_rollover_nearest"] = block(
        record(_base(1, tod=TOD_2359)),
        record(_base(1, tod=TOD_0000)),
    )

    # ------------------------------------------------- two records, one block
    out["two_records_one_block"] = block(
        record(_base(1)),
        record(_base(2, **{"I034/020": _sector(45.0)})),
    )

    # ------------------------------------------------- a legal but non-conventional FSPEC
    # FRNs 1, 2 and 3 all fit in one octet; this record sets FX and follows it with an all-zero
    # second octet. §4.7 requires only that a present item's bit is set, so this is legal and the
    # round trip is byte-exact only because the octets are re-emitted as parked.
    out["non_minimal_fspec"] = block(record(_base(1), fspec=bytes([0xE1, 0x00])))

    # ------------------------------------------------- FRN 13 and FRN 14
    # Both parked octet-for-octet, neither decoded, both restored unchanged.
    out["re_and_sp_carried"] = block(record(_base(1, **{
        "RE": _explicit(bytes.fromhex("0102030405")),
        "SP": _explicit(bytes.fromhex("aabbcc")),
    })))

    # ------------------------------------------------- §4.4, and it is a NORMATIVE sentence
    # "Decoders of ASTERIX data shall NEVER ASSUME AND RELY on specific settings of spare or
    # unused bits. However in order to improve the readability of binary dumps of ASTERIX records,
    # it is RECOMMENDED to set all spare bits to zero." So zero is a recommendation and a decoder
    # that depends on it is non-conformant — while eleven of the subfield bit-diagrams in §5.2.6
    # and §5.2.7 legend their spare bits "set to zero". Ambiguity 12.
    #
    # THIS FIXTURE WAS ADDED BY A MUTATION, not by the Phase 1 plan. Zeroing I034/050's COM spare
    # bit inside the decoder passed every other fixture and every test, because every other
    # fixture's spare bits are zero and a dropped zero re-encodes as a zero. Every reachable spare
    # bit is set to 1 here, so the round trip is the check §4.4 asks for.
    #
    # The three PRIMARY-subfield spare bits are NOT among them and cannot be: bits 7, 6 and 2 are
    # presence bits for Subfields #2, #3 and #7, all three spelled "Spare Subfield", so a set one
    # announces a secondary subfield that does not exist and is refused by the length rule. The
    # reachable spares are the ones inside the secondary subfields.
    out["spare_bits_nonzero"] = block(record(_base(1, **{
        "I034/050": {
            "primary": _primary(com=1, psr=1, ssr=1, mds=1),
            "com": {"nogo": 0, "rdpc": 0, "rdpr": 0, "ovl_rdp": 0, "ovl_xmt": 0, "msc": 0,
                    "tsv": 0, "spare_bit_1": 1},
            "psr": {"ant": 0, "ch_ab": 0, "ovl": 0, "msc": 0, "spare_bits_3_1": 0b111},
            "ssr": {"ant": 0, "ch_ab": 0, "ovl": 0, "msc": 0, "spare_bits_3_1": 0b111},
            "mds": {"ant": 0, "ch_ab": 0, "ovl_sur": 0, "msc": 0, "scf": 0, "dlf": 0,
                    "ovl_scf": 0, "ovl_dlf": 0, "spare_bits_7_1": 0b1111111},
        },
        "I034/060": {
            "primary": _primary(com=1, psr=1, ssr=1, mds=1),
            "com": {"spare_bit_8": 1, "red_rdp": 0, "red_xmt": 0, "spare_bit_1": 1},
            "psr": {"pol": 0, "red_rad": 0, "stc": 0, "spare_bits_2_1": 0b11},
            "ssr": {"red_rad": 0, "spare_bits_5_1": 0b11111},
            "mds": {"red_rad": 0, "clu": 0, "spare_bits_4_1": 0b1111},
        },
    })))

    # ------------------------------------------------- THE EDITION 1.30 TRIPWIRE
    # A record whose I034/000 is 008. Read, parked in unresolved_raw, classified
    # STATUS_CHANGE/ADVISORY, and NOT refused: an undefined-in-this-edition type is not a
    # malformed record. §5.2.1 NOTE 2 says "All Message Type values are reserved for common
    # standard use", so it is not a private extension point either.
    #
    # It is here in the TRANSLATABLE set and not in `refusals/`, which is where the Phase 1
    # fixture plan listed it under a heading its own text contradicted. See the row set.
    #
    # The day Edition 1.30 lands and Message Type 008 is defined, this fixture changes from a
    # park to a translation and its golden file moves — which is the point of writing it now.
    out["message_type_008"] = block(record(_base(8)))

    return out


def refusals() -> dict[str, bytes]:
    """Blocks the adapter must refuse. No golden file: the refusal IS the expected output."""
    out: dict[str, bytes] = {}

    # A block whose CAT octet is 48. Decoded against the category 034 UAP it would yield a
    # plausible wrong radar status rather than an error — the failure the CAT048 declines table
    # names, from the other side.
    good = block(record(_base(1)))
    out["wrong_category"] = bytes([48]) + good[1:]

    # LEN longer than the octets supplied. Reading to the end of the buffer instead would
    # translate whatever followed the block as if it were part of it.
    padded = bytearray(good)
    padded[1:3] = codec.write_unsigned(len(padded) + 4, 2)
    out["length_disagrees_with_buffer"] = bytes(padded)

    # No I034/010 — M in every column of Table 2, and there is no checksum behind the record to
    # have caught the truncation.
    out["missing_mandatory_data_source"] = block(record(
        {"I034/000": {"message_type": 1}, "I034/030": _tod(TOD_0600)}))

    return out


def check_layouts() -> None:
    """Every encoder emits exactly the octet count the standard states for its item."""
    problems: list[str] = []
    samples: dict[str, dict] = {
        "I034/010": {"sac": 0, "sic": 0},
        "I034/000": {"message_type": 0},
        "I034/030": _tod(0),
        "I034/020": {"sector_raw": 0},
        "I034/041": {"rotation_raw": 0},
        "I034/090": {"range_error_raw": 0, "azimuth_error_raw": 0},
        "I034/100": _window(0.0, 0.0, 0.0, 0.0),
        "I034/110": {"typ": 1},
        "I034/120": _position(0.0, 0.0, 0.0),
    }
    for item, expected in _ITEM_OCTETS.items():
        if not isinstance(expected, int):
            continue
        emitted = len(cat034.ENCODERS[item](samples[item]))
        if emitted != expected:
            problems.append(f"{item}: the standard states {expected} octet(s), encoder emitted "
                            f"{emitted}")
    # The compound, repetitive and explicit-length items, at a stated shape each. §5.2.6's MDS
    # subfield is TWO octets and §5.2.7's is ONE, which is the one asymmetry between the two
    # compound items and the thing a copied length rule would get wrong.
    checks = [
        ("I034/050", {"primary": _primary()}, 1),
        ("I034/050", {"primary": _primary(com=1),
                      "com": {"nogo": 0, "rdpc": 0, "rdpr": 0, "ovl_rdp": 0, "ovl_xmt": 0,
                              "msc": 0, "tsv": 0, "spare_bit_1": 0}}, 2),
        ("I034/050", {"primary": _primary(mds=1),
                      "mds": {"ant": 0, "ch_ab": 0, "ovl_sur": 0, "msc": 0, "scf": 0, "dlf": 0,
                              "ovl_scf": 0, "ovl_dlf": 0, "spare_bits_7_1": 0}}, 3),
        ("I034/060", {"primary": _primary()}, 1),
        ("I034/060", {"primary": _primary(mds=1),
                      "mds": {"red_rad": 0, "clu": 0, "spare_bits_4_1": 0}}, 2),
        # §5.2.8: "(1+2*N)" — a one-octet REP then two octets per counter.
        ("I034/070", _counters((0, 0)), 3),
        ("I034/070", _counters((0, 0), (1, 1), (2, 2)), 7),
        # RE and SP: a one-octet length counting itself, then the contents.
        ("RE", _explicit(b"\x00\x01"), 3),
        ("SP", _explicit(b""), 1),
    ]
    for item, sample, expected in checks:
        emitted = len(cat034.ENCODERS[item](sample))
        if emitted != expected:
            problems.append(f"{item}: expected {expected} octet(s) for that shape, encoder "
                            f"emitted {emitted}")
    if problems:
        raise AssertionError("layout(s) disagree with the standard's own byte counts:\n  "
                             + "\n  ".join(problems))


def main() -> None:
    check_layouts()
    written = 0
    for name, octets in fixtures().items():
        (FIXTURES / f"{name}.cat034").write_bytes(octets)
        parsed = cat034.parse_block(octets)
        (FIXTURES / f"{name}.parsed.json").write_text(
            json.dumps(parsed, indent=2, sort_keys=True) + "\n")
        written += 1
    refusal_dir = FIXTURES / "refusals"
    refusal_dir.mkdir(exist_ok=True)
    for name, octets in refusals().items():
        (refusal_dir / f"{name}.cat034").write_bytes(octets)
        written += 1
    print(f"wrote {written} fixtures into {FIXTURES} "
          f"({len(fixtures())} translatable, {len(refusals())} refusals)")


if __name__ == "__main__":
    main()
