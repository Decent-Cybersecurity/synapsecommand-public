#!/usr/bin/env python3
"""Build the CAT023 fixture set. THE SOURCE OF TRUTH FOR BOTH ARTEFACTS.

    python build_fixtures.py                      # from the directory this file is in
    python -m synapse_cdm.harness --adapter cat023 --update-golden   # then READ it

Edit this file, never the `.cat023` octets and never the `.parsed.json` twins.

WHY A GENERATOR AND NOT HAND-EDITED BYTES
-----------------------------------------
A record's FSPEC and its block's LEN are both functions of the contents, so a hand-edited byte file
is a mis-parse waiting to happen and a hand-edited twin does not tell you what octets it implies.
Every fixture below is described by its FIELD VALUES and the octets are derived.

EVERYTHING IS SYNTHETIC
-----------------------
No recorded ASTERIX traffic and no real ground station. `SAC = 0x29` is listed with an explicitly
empty country cell in the EUROCONTROL allocation tables pinned at `../../cat021/spec/sac_pin.json`
and in no other regional table — the evidence transfers to Part 16 by CITATION, because §5.2.2's
NOTE points at the same published list the CAT021 row does, at the same URL under a different
scheme. `SIC` carries no allocation claim.

THERE ARE NO COORDINATES HERE TO BE SYNTHETIC ABOUT
---------------------------------------------------
Which is worth one line, because every other fixture set in this repository has to say where its
synthetic positions are. Part 16 carries no position of any kind: nine items and not one coordinate.
`I023/200` is an operational range with no centre.

THE LAYOUT SUMS AGAINST THE STANDARD'S OWN BYTE TOTALS
------------------------------------------------------
`_ITEM_OCTETS` states each item's length as §5.2 and Table 3 give it, and `check_layouts()` asserts
that every encoder emits exactly that. `I023/101` is the interesting one: its first part is TWO
octets with the FX in the second and its extension is one, which is the only `2+` shape in any
ASTERIX category this repository pins. `tests/test_cdm_asterix_cat023_adapter.py` calls it, so it
cannot be skipped by not running this file.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
FIXTURES = HERE.parent.parent
sys.path.insert(0, str(FIXTURES.parent.parent.parent))

from synapse_cdm.adapters import asterix_cat023 as cat023          # noqa: E402
from synapse_cdm.adapters import cat023_codec as codec             # noqa: E402

# --------------------------------------------------------------------- the identifiers

#: Pinned by citation: listed-but-blank in the EUR table and in no other.
SAC = 0x29
SIC = 0x29

#: 06:00:00.000, fifteen minutes before `times.FROZEN_NOW`, so every ordinary fixture resolves on
#: the receipt date and only the rollover fixture does anything else.
TOD_0600 = 6 * 3600 * 128
#: 23:59:59.000 and 00:00:01.000 — the rollover pair.
TOD_2359 = (23 * 3600 + 59 * 60 + 59) * 128
TOD_0000 = 1 * 128

# ------------------------------------------------------------------- the layout table
_ITEM_OCTETS: dict[str, object] = {
    "I023/010": 2, "I023/000": 1, "I023/015": 1, "I023/070": 3, "I023/100": "1+",
    "I023/101": "2+", "I023/200": 1, "I023/110": "1+", "I023/120": "1+",
    "RE": "1+1+", "SP": "1+1+",
}


# ----------------------------------------------------------------------- item builders


def _source(sac: int = SAC, sic: int = SIC) -> dict:
    return {"sac": sac, "sic": sic}


def _report(report_type: int) -> dict:
    return {"report_type": report_type}


def _service(sid: int, styp: int) -> dict:
    return {"sid": sid, "styp": styp}


def _tod(raw: int) -> dict:
    return {"time_of_day_raw": raw}


def _station_status(*, nogo: int = 0, odp: int = 0, oxt: int = 0, msc: int = 0, tsv: int = 0,
                    spo: int = 0, rn: int = 0, gssp: int | None = None,
                    gssp_raw: int | None = None) -> dict:
    parsed: dict = {"nogo": nogo, "odp": odp, "oxt": oxt, "msc": msc, "tsv": tsv, "spo": spo,
                    "rn": rn, "fx": 0}
    if gssp is not None or gssp_raw is not None:
        parsed["fx"] = 1
        raw = gssp_raw if gssp_raw is not None else codec.to_raw("gssp", float(gssp))
        parsed["extension"] = {"gssp_raw": raw, "fx": 0}
    return parsed


def _configuration(*, rp_raw: int, sc: int = 0, spare: int = 0, ssrp: int | None = None,
                   ssrp_raw: int | None = None) -> dict:
    parsed: dict = {"rp_raw": rp_raw, "sc": sc, "spare_bits_5_2": spare, "fx": 0}
    if ssrp is not None or ssrp_raw is not None:
        parsed["fx"] = 1
        raw = ssrp_raw if ssrp_raw is not None else codec.to_raw("ssrp", float(ssrp))
        parsed["extension"] = {"ssrp_raw": raw, "fx": 0}
    return parsed


def _status(stat: int, *, spare: int = 0, fx: int = 0) -> dict:
    return {"spare_bits_8_5": spare, "stat": stat, "fx": fx}


def _statistics(*counters: tuple[int, int, int], spare: int = 0) -> dict:
    """Each counter is (TYPE, REF, COUNTER VALUE)."""
    return {"rep": len(counters),
            "counters": [{"type": t, "ref": r, "spare_bits_39_33": spare, "counter": c}
                         for t, r, c in counters]}


def _range(nautical_miles: int) -> dict:
    return {"range_raw": codec.to_raw("operational_range", float(nautical_miles))}


def _explicit(payload: bytes) -> dict:
    return {"length": len(payload) + 1, "contents": payload.hex()}


def record(items: dict, *, fspec: bytes | None = None) -> bytes:
    """One record: the FSPEC then the present items in FRN order."""
    frns = sorted(cat023.FRN_BY_ITEM[item] for item in items)
    body = fspec if fspec is not None else codec.write_fspec(frns)
    for frn in frns:
        item = cat023.UAP_BY_FRN[frn][1]
        body += cat023.ENCODERS[item](items[item])
    return body


def block(*bodies: bytes) -> bytes:
    payload = b"".join(bodies)
    return bytes([cat023.CATEGORY]) + \
        codec.write_unsigned(len(payload) + cat023.BLOCK_HEADER_OCTETS, 2) + payload


def _base(report_type: int, tod: int | None = TOD_0600, **extra) -> dict:
    """I023/010 + I023/000, the two items M in every column of Table 2, plus a time."""
    items: dict = {"I023/010": _source(), "I023/000": _report(report_type)}
    if tod is not None:
        items["I023/070"] = _tod(tod)
    items.update(extra)
    return items


def _mandatory_items() -> bytes:
    """I023/010 + I023/000 + I023/070 as octets, for the refusals assembled by hand."""
    return (cat023.ENCODERS["I023/010"](_source())
            + cat023.ENCODERS["I023/000"](_report(1))
            + cat023.ENCODERS["I023/070"](_tod(TOD_0600)))


# ============================================================================ fixtures


def fixtures() -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # ---------------------------------------------- the shortest legal record
    # Type 001 with only its M items. ONE FSPEC OCTET, and a parser that assumed FRN order equalled
    # item-number order would read I023/000 where I023/010 is: Table 3 puts I023/010 at FRN 1 and
    # I023/000 at FRN 2, so the wire order is 010, 000, 070, 100.
    out["ground_station_status_minimal"] = block(record(_base(
        1, **{"I023/100": _station_status()})))

    # ---------------------------------------------- every station flag set
    # I023/100's first part AND its extension, plus the optional I023/200. Every flag on, GSSP = 60.
    out["ground_station_status_full"] = block(record(_base(
        1, **{
            "I023/100": _station_status(nogo=1, odp=1, oxt=1, msc=1, tsv=1, spo=1, rn=1, gssp=60),
            "I023/200": _range(200),
        })))

    # ---------------------------------------------- settlement 2: TWO Entities
    # Type 002 with I023/015, I023/101 (first part and extension) and I023/110. The test asserts
    # both entity_id values are on the event with the station FIRST, and that the service's id is
    # the PAIR and not the SID alone.
    out["service_status_report"] = block(record(_base(
        2, **{
            "I023/015": _service(sid=3, styp=2),
            "I023/101": _configuration(rp_raw=codec.to_raw("rp", 1.0), sc=1, ssrp=30),
            "I023/110": _status(4),
        })))

    # ---------------------------------------------- the severity ladder
    # Table 2 makes I023/101 M for type 002 as well as I023/110, so every type-002 fixture carries
    # both — which is settlement 4's mandatory half doing its job at BUILD time: the generator
    # cannot produce a type-002 record without a service configuration, because `parse_block` runs
    # over every fixture as it is written and refuses one.
    out["service_status_degraded"] = block(
        record(_base(2, **{"I023/015": _service(sid=3, styp=2),
                           "I023/101": _configuration(rp_raw=codec.to_raw("rp", 1.0), sc=1),
                           "I023/110": _status(3)})),
        record(_base(2, **{"I023/015": _service(sid=3, styp=2),
                           "I023/101": _configuration(rp_raw=codec.to_raw("rp", 1.0), sc=1),
                           "I023/110": _status(1)})),
    )

    # Two paths to ADVISORY, and the object has to distinguish them: `0` is a value the document
    # DEFINES as "Unknown", and `6` is a value the document does not define at all — so only the
    # second produces an unresolved_raw entry.
    out["service_status_unknown"] = block(
        record(_base(2, **{"I023/015": _service(sid=1, styp=5),
                           "I023/101": _configuration(rp_raw=codec.to_raw("rp", 2.0)),
                           "I023/110": _status(0)})),
        record(_base(2, **{"I023/015": _service(sid=1, styp=5),
                           "I023/101": _configuration(rp_raw=codec.to_raw("rp", 2.0)),
                           "I023/110": _status(6)})),
    )

    # ---------------------------------------------- the counters
    # REP = 4: one in the generic band, one in the per-message band, one DUPLICATE TYPE, and one
    # with REF = 0 against the others' REF = 1 — so the per-counter reference is visible.
    out["service_statistics_report"] = block(record(_base(
        3, **{
            "I023/015": _service(sid=3, styp=2),
            "I023/120": _statistics((3, 1, 1_234_567), (21, 1, 890), (21, 1, 12),
                                    (4, 0, 4_294_967_295)),
        })))

    # A TYPE of 7 — inside §5.2.8's reserved 0-to-19 generic band — and one of 40, outside the table
    # entirely. Both go to unresolved_raw and the reason recorded with each says WHICH BAND.
    out["service_statistics_reserved_type"] = block(record(_base(
        3, **{
            "I023/015": _service(sid=3, styp=2),
            "I023/120": _statistics((7, 1, 5), (40, 1, 9)),
        })))

    # ---------------------------------------------- settlement 6's sentinel
    # RP = 0 is "Data driven mode", not a period of zero seconds. The test asserts no 0.0 appears
    # anywhere in the object as a period.
    out["data_driven_report_period"] = block(record(_base(
        2, **{
            "I023/015": _service(sid=2, styp=9),
            "I023/101": _configuration(rp_raw=0, sc=1),
            "I023/110": _status(4),
        })))

    # ---------------------------------------------- one block, all three report types
    # THREE records for the same station with TWO different SIDs on the 002 and 003 records, so the
    # block produces one station Entity per record and TWO DISTINCT service Entities — and nothing
    # is merged, which is settlement 7's first refusal made visible.
    out["all_three_service_types"] = block(
        record(_base(1, **{"I023/100": _station_status(msc=1, gssp=60)})),
        record(_base(2, **{"I023/015": _service(sid=3, styp=2),
                           "I023/101": _configuration(rp_raw=codec.to_raw("rp", 0.5), sc=1,
                                                      ssrp=30),
                           "I023/110": _status(4)})),
        record(_base(3, **{"I023/015": _service(sid=5, styp=5),
                           "I023/120": _statistics((3, 1, 100), (4, 1, 99))})),
    )

    # ---------------------------------------------- the permitted absence
    # Type 001 with no I023/070 at all. §5.2.4's Encoding Rule permits it while Table 2 marks the
    # item M for all three types; the absence lands in attributes.unavailable_fields and observed_at
    # falls back to the injected clock.
    out["time_of_day_absent"] = block(record(_base(
        1, tod=None, **{"I023/100": _station_status(tsv=1)})))

    # ---------------------------------------------- the floor, and the geometry that is not derived
    out["operational_range_at_maximum"] = block(record(_base(
        1, **{"I023/100": _station_status(), "I023/200": _range(255)})))

    # ---------------------------------------------- settlement 4's asymmetry
    # Type 001 carrying I023/110, which Table 2 marks X for that type. Parked and named in
    # attributes.table_2_disposition, NOT refused.
    out["table_2_x_item_present"] = block(record(_base(
        1, **{"I023/100": _station_status(), "I023/110": _status(4)})))

    # ---------------------------------------------- the edition tripwire
    # A report type this edition does not define. Translated, STATUS_CHANGE/ADVISORY, raw value in
    # unresolved_raw, and NOT refused: §5.2.1 NOTE 2 says all values are reserved for common
    # standard use, so it is not a private extension point either.
    out["report_type_004"] = block(record(_base(4)))

    # ---------------------------------------------- FRN 13 and FRN 14
    out["reserved_and_special_purpose"] = block(record(_base(
        1, **{
            "I023/100": _station_status(),
            "RE": _explicit(bytes.fromhex("0102030405")),
            "SP": _explicit(bytes.fromhex("aabbcc")),
        })))

    # ---------------------------------------------- §4.3, and it is a NORMATIVE sentence
    # "Decoders of ASTERIX data shall NEVER ASSUME AND RELY on specific settings of spare or unused
    # bits. However in order to improve the readability of binary dumps of ASTERIX records, it is
    # RECOMMENDED to set all spare bits to zero." So zero is a recommendation and a decoder that
    # depends on it is non-conformant.
    #
    # THE CAT034 ROUND FOUND WHY THIS FIXTURE IS MANDATORY RATHER THAN THOROUGH: zeroing a spare bit
    # inside the decoder passed every test and every other fixture, because every other fixture's
    # spares are zero and a dropped zero re-encodes as a zero.
    #
    # Every reachable spare bit in this category is here: I023/101 octet 2 bits 5/2, I023/110 bits
    # 8/5, and I023/120's seven spare bits per block. There are no others — I023/015's two nibbles
    # are both defined fields, which is exactly why they are parked under explicit names.
    out["spare_bits_nonzero"] = block(record(_base(
        2, **{
            "I023/015": _service(sid=15, styp=9),
            "I023/101": _configuration(rp_raw=codec.to_raw("rp", 127.5), sc=1,
                                       spare=0b1111, ssrp=127),
            "I023/110": _status(4, spare=0b1111),
            "I023/120": _statistics((32, 1, 7), spare=0b1111111),
        })))

    # ---------------------------------------------- a legal but non-conventional FSPEC
    # FRNs 1, 2, 4 and 5 all fit in one octet; this record sets FX and follows it with an all-zero
    # second octet. §4.6.2 requires only that a present item's bit is set, so this is legal and the
    # round trip is byte-exact only because the octets are re-emitted as parked.
    out["non_minimal_fspec"] = block(record(
        _base(1, **{"I023/100": _station_status()}), fspec=bytes([0xD9, 0x00])))

    # ---------------------------------------------- the midnight wrap
    # TWO RECORDS, built so the wrap happens under the HARNESS'S OWN frozen clock rather than only
    # under one a test injects — the failure this package's README records for CAT048's two rollover
    # fixtures, which described times that resolved to the receipt date at the frozen instant.
    out["midnight_rollover_nearest"] = block(
        record(_base(1, tod=TOD_2359, **{"I023/100": _station_status()})),
        record(_base(1, tod=TOD_0000, **{"I023/100": _station_status()})),
    )

    return out


def refusals() -> dict[str, bytes]:
    """Blocks the adapter must refuse. No golden file: the refusal IS the expected output."""
    out: dict[str, bytes] = {}
    good = block(record(_base(1, **{"I023/100": _station_status()})))

    # A block whose CAT octet is 34. Decoded against the category 023 UAP it would yield a plausible
    # wrong ground station status rather than an error — and Part 2b is the DANGEROUS sibling: same
    # fourteen FRNs, same two-octet FSPEC ceiling, a different item at almost every position.
    out["wrong_category"] = bytes([34]) + good[1:]

    # LEN longer than the octets supplied.
    padded = bytearray(good)
    padded[1:3] = codec.write_unsigned(len(padded) + 4, 2)
    out["length_disagrees_with_buffer"] = bytes(padded)

    # No I023/000 — M in every column of Table 2.
    out["missing_mandatory_report_type"] = block(record(
        {"I023/010": _source(), "I023/070": _tod(TOD_0600)}))

    # Type 002 with no I023/110. Settlement 4's mandatory half: a Service Status report with no
    # service status states nothing, and there is no checksum behind it to have caught the
    # truncation.
    out["missing_mandatory_for_type"] = block(record(_base(
        2, **{"I023/015": _service(sid=3, styp=2),
              "I023/101": _configuration(rp_raw=2)})))

    # An FSPEC bit for FRN 11, which Table 3 marks '- spare -'. Assembled from octets, because
    # `codec.write_fspec` refuses a spare FRN: a presence bit for a spare slot announces content the
    # record does not carry, so a conforming encoder cannot produce this either. FRN 11 is octet 2,
    # bit 4.
    out["fspec_names_a_spare_frn"] = block(bytes([0xD1, 0x10]) + _mandatory_items())

    # A second FSPEC octet with FX set. There is no FRN 15.
    out["fspec_third_octet"] = block(bytes([0xD1, 0x01]) + _mandatory_items())

    # I023/100's First Extension with FX set — "Extension into Second Extension", and §5.2.5 defines
    # no Second Extension.
    status = _station_status(gssp=60)
    status["extension"]["fx"] = 1
    out["ground_station_status_second_extension"] = block(record(_base(
        1, **{"I023/100": status})))

    # I023/110 with FX set — the case where NO extension exists in any edition in hand, including
    # Edition 0.14. The strongest of this category's three such cases.
    out["service_status_extension"] = block(record(_base(
        2, **{"I023/015": _service(sid=3, styp=2),
              "I023/101": _configuration(rp_raw=2),
              "I023/110": _status(4, fx=1)})))

    # I023/120 with REP = 0, excluded by the item's own "at least one block of 6 octets". Assembled
    # from octets: `_encode_120` will happily emit it, so this one CAN go through `record()` — the
    # refusal is in the length rule on the way back in, which is where it belongs.
    out["service_statistics_rep_zero"] = block(record(_base(
        3, **{"I023/015": _service(sid=3, styp=2),
              "I023/120": {"rep": 0, "counters": []}})))

    # I023/100's extension with GSSP = 0, outside the stated 1..127 range. The field can express it
    # and the item cannot, and §4.5.1.1 makes the periodic send an obligation — so a zero is not a
    # way of turning it off.
    out["reporting_period_zero"] = block(record(_base(
        1, **{"I023/100": _station_status(gssp_raw=0)})))

    return out


def check_layouts() -> None:
    """Every encoder emits exactly the octet count the standard states for its item."""
    problems: list[str] = []
    samples: dict[str, dict] = {
        "I023/010": _source(0, 0),
        "I023/000": _report(0),
        "I023/015": _service(0, 0),
        "I023/070": _tod(0),
        "I023/200": _range(0),
    }
    for item, expected in _ITEM_OCTETS.items():
        if not isinstance(expected, int):
            continue
        emitted = len(cat023.ENCODERS[item](samples[item]))
        if emitted != expected:
            problems.append(f"{item}: the standard states {expected} octet(s), encoder emitted "
                            f"{emitted}")
    # The extensible, repetitive and explicit-length items, at a stated shape each. I023/101 is the
    # one to check hardest: §5.2.6's first part is TWO octets with the FX in the SECOND and its
    # extension is ONE, which is the only `2+` shape in any ASTERIX category pinned here — and a
    # length rule copied from I023/100's would be off by one on every record.
    checks = [
        ("I023/100", _station_status(), 1),
        ("I023/100", _station_status(gssp=1), 2),
        ("I023/101", _configuration(rp_raw=0), 2),
        ("I023/101", _configuration(rp_raw=0, ssrp=1), 3),
        ("I023/110", _status(0), 1),
        # §5.2.8: a one-octet REP then six octets per counter.
        ("I023/120", _statistics((0, 0, 0)), 7),
        ("I023/120", _statistics((0, 0, 0), (1, 1, 1), (2, 0, 2)), 19),
        # RE and SP: a one-octet length counting itself, then the contents.
        ("RE", _explicit(b"\x00\x01"), 3),
        ("SP", _explicit(b""), 1),
    ]
    for item, sample, expected in checks:
        emitted = len(cat023.ENCODERS[item](sample))
        if emitted != expected:
            problems.append(f"{item}: expected {expected} octet(s) for that shape, encoder emitted "
                            f"{emitted}")
    if problems:
        raise AssertionError("layout(s) disagree with the standard's own byte counts:\n  "
                             + "\n  ".join(problems))


def main() -> None:
    check_layouts()
    written = 0
    for name, octets in fixtures().items():
        (FIXTURES / f"{name}.cat023").write_bytes(octets)
        parsed = cat023.parse_block(octets)
        (FIXTURES / f"{name}.parsed.json").write_text(
            json.dumps(parsed, indent=2, sort_keys=True) + "\n")
        written += 1
    refusal_dir = FIXTURES / "refusals"
    refusal_dir.mkdir(exist_ok=True)
    for name, octets in refusals().items():
        (refusal_dir / f"{name}.cat023").write_bytes(octets)
        written += 1
    print(f"wrote {written} fixtures into {FIXTURES} "
          f"({len(fixtures())} translatable, {len(refusals())} refusals)")


if __name__ == "__main__":
    main()
