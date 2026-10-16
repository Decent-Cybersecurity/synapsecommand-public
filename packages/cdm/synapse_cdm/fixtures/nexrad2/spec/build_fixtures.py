#!/usr/bin/env python3
"""Build the nexrad2 fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py            # writes every generated file under fixtures/nexrad2/
    python -I -B build_fixtures.py --check    # builds everything in memory and compares it, byte
                                              # for byte, with the tree; prints CURRENT and exits
                                              # 0, or prints STALE: <names> and exits 1

Edit this file, never an `.ar2v`, a twin or a provenance record. `README.md` beside the payloads,
`malformed/README.md` and `spec/nexrad2_pin.json` are the hand-written files of the set, and
`golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Every volume below is written from the byte layouts of two public ICDs, pinned by SHA-256 in
`nexrad2_pin.json` and never carried: 2620010J (Archive II/User, Build 23.0) Figure 1 for the
24-octet volume header, section 7.3.4 for the LDM compressed record (a four-octet signed,
big-endian control word and one bzip2 stream) and section 7.3.5 for the 134-segment metadata
record; 2620002Y (RDA/RPG, Build 23.0) Table II for the message header, Table XVII-A for the
message-31 data header, XVII-B for a moment block, XVII-E, -F and -H for the VOL, ELV and RAD
constant blocks, XVII-I for each moment's typical gate count, word size, scale and offset, and
Table III-C for the radial status. It is an ENCODER, written from the tables and sharing no code
with the adapter, and it writes each volume's twin from the same literals it encoded, never by
decoding what it wrote: the twin is the expectation the adapter is held to.

For each case the script writes `<name>.ar2v`, the volume as the archive stores it, and
`<name>.parsed.json`, its twin: the octets as `wire_hex`, then every field the volume states,
raw, under the names the adapter's parse uses (`volume_header`, `site`, `records`, `sweeps`, and
the gate codes of every moment of every radial as runs of `[code, count]` under `gates`).
`malformed/` holds volumes the adapter must refuse, each with the one thing wrong with it named
in `MALFORMED`.

DETERMINISM
-----------
bzip2 is deterministic: `bz2.compress(data, 9)` writes the same octets for the same input on every
run, and the libbz2 the three interpreters link wrote this set identically (the pin records the
reading). No clock, host name, random value or absolute path reaches an output.

EVERYTHING IS SYNTHETIC. The radar sites are `ZZZZ` and `XZZA` (CONTRIBUTING.md, "Identifiers
and places in observation fixtures"), every site lies in the Baltic rectangle, the day is
2026-04-29, and every value is written here from the ICD's tables, not taken from a volume.
"""

from __future__ import annotations

import argparse
import bz2
import datetime
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
MALFORMED_DIR = FIXTURES / "malformed"

ORIGIN = (
    "Synthetic NEXRAD Level II volume written on 2026-10-15 for the nexrad2 adapter's landing by "
    "fixtures/nexrad2/spec/build_fixtures.py from literals in that script, after the byte "
    "layouts of ICDs 2620010J and 2620002Y (pinned by SHA-256, never carried); the radar site is "
    "ZZZZ or XZZA in the Baltic rectangle and nothing is recorded data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed NEXRAD Level II volume written on 2026-10-15 by "
    "fixtures/nexrad2/spec/build_fixtures.py, from literals in that script, for the conformance "
    "suite's check H; malformed/README.md names what is wrong with it and the refusal it "
    "expects. Nothing is recorded data."
)

#: 2620010J 7.3.5: the metadata record's message types and the 2432-octet segments set aside for
#: each, in order. A message needing fewer segments leaves the rest with message type 0, so this
#: set writes the first segment of each message with its type and the others as type 0.
METADATA_LAYOUT = ((15, 77), (32, 1), (13, 48), (18, 5), (3, 1), (5, 1), (2, 1))
SEGMENT = 2432
CTM = b"\x00" * 12
FCS = b"\x00" * 4
CHANNEL = 8  # Table II: ORDA, single channel (bit 3 set)

DAY = datetime.date(2026, 4, 29)
#: Table II note 2 / XVII-A note 4: the NEXRAD-modified Julian date, 1970-01-01 = day 1.
MJD = (DAY - datetime.date(1970, 1, 1)).days + 1
#: 06:10:00.000, milliseconds past midnight: the volume's start in every case.
START_MS = 6 * 3_600_000 + 10 * 60_000

#: Table XVII-I's typical values per moment: gate count, word size, scale, offset.
TYPICAL = {
    "REF": (1840, 8, 2.0, 66.0),
    "VEL": (1200, 8, 2.0, 129.0),
    "SW ": (1200, 8, 2.0, 129.0),
    "ZDR": (1200, 16, 32.0, 418.0),
    "PHI": (1200, 16, 2.8361, 2.0),
    "RHO": (1200, 8, 300.0, -60.5),
    "CFP": (1840, 8, 1.0, 8.0),
}
ORDER = ("REF", "VEL", "SW ", "ZDR", "PHI", "RHO", "CFP")


def f32(value: float) -> float:
    """The double a Real*4 field written with `value` reads back as."""
    return struct.unpack(">f", struct.pack(">f", value))[0]


# -- the parts of one radial, as raw field values -------------------------------------------------


def vol(**over) -> dict:
    """Table XVII-E's fields other than the site (which `site` holds), raw."""
    fields = {
        "version_major": 3,
        "version_minor": 1,
        "dbz0": -44.625,
        "horizontal_tx_power": 312.5,
        "vertical_tx_power": 312.5,
        "system_zdr": 0.25,
        "initial_system_phidp": 60.0,
        "vcp": 212,
        "processing_status": 0,
        "zdr_bias": 3,
    }
    fields.update(over)
    return fields


def elv(**over) -> dict:
    """Table XVII-F, raw: ATMOS in thousandths of a dB/km."""
    fields = {"atmospheric_attenuation": -12, "dbz0": -44.375}
    fields.update(over)
    return fields


def rad(**over) -> dict:
    """Table XVII-H, raw: unambiguous range in tenths of a km, Nyquist in hundredths of m/s."""
    fields = {
        "unambiguous_range": 1150,
        "noise_level_h": -80.5,
        "noise_level_v": -80.25,
        "nyquist_velocity": 2875,
        "radial_flags": 0,
        "calibration_h": -44.5,
        "calibration_v": -44.75,
    }
    fields.update(over)
    return fields


def moment(name: str, runs: list, **over) -> dict:
    """One moment block, raw (Table XVII-B), with its gate codes as runs of [code, count]."""
    gates, word_size, scale, offset = TYPICAL[name]
    fields = {
        "name": name,
        "reserved": 0,
        "gates": gates,
        "first_gate_range": 2125,
        "gate_interval": 250,
        "tover": 50,
        "snr_threshold": 16,
        "control_flags": 0,
        "word_size": word_size,
        "scale": scale,
        "offset": offset,
        "runs": runs,
    }
    fields.update(over)
    assert sum(count for _, count in fields["runs"]) == fields["gates"], name
    return fields


def every_moment(**runs_by_name) -> list[dict]:
    """All seven moments at their Table XVII-I gate counts. The default runs put one gate below
    threshold and one range folded first in each of the six coded moments, then a constant."""
    default = {
        "REF": [[0, 1], [1, 1], [130, 1838]],
        "VEL": [[0, 1], [1, 1], [129, 1198]],
        "SW ": [[0, 1], [1, 1], [131, 1198]],
        "ZDR": [[0, 1], [1, 1], [418, 1198]],
        "PHI": [[0, 1], [1, 1], [600, 1198]],
        "RHO": [[0, 1], [1, 1], [255, 1198]],
        "CFP": [[8, 1840]],
    }
    out = []
    for name in ORDER:
        given = runs_by_name.get(name.strip())
        if isinstance(given, dict):
            out.append(moment(name, given.pop("runs", default[name]), **given))
        else:
            out.append(moment(name, given if given is not None else default[name]))
    return out


def radial(
    *,
    elevation: int,
    azimuth: int,
    angle: float,
    status: int,
    ms: int,
    elevation_angle: float,
    moments: list[dict] | None = None,
    **over,
) -> dict:
    fields = {
        "collection_time": ms,
        "julian_date": MJD,
        "azimuth_number": azimuth,
        "azimuth_angle": angle,
        "compression": 0,
        "azimuth_spacing": 1,
        "radial_status": status,
        "elevation_number": elevation,
        "cut_sector": 1,
        "elevation_angle": elevation_angle,
        "spot_blanking": 0,
        "azimuth_indexing": 0,
        "vol": vol(),
        "elv": elv(),
        "rad": rad(),
        "moments": moments if moments is not None else every_moment(),
    }
    fields.update(over)
    return fields


# -- encoding ------------------------------------------------------------------------------------


def message_header(size_hw: int, msg_type: int, seq: int, date: int, ms: int) -> bytes:
    """Table II: size (halfwords), channel, type, sequence, Julian date, ms, segments, segment."""
    return struct.pack(">HBBHHIHH", size_hw, CHANNEL, msg_type, seq, date, ms, 1, 1)


def fixed_segment(msg_type: int, seq: int, ms: int) -> bytes:
    """A 2432-octet segment: CTM, header, 2400 octets of data (zeros here), FCS."""
    size_hw = (16 + 2400) // 2 if msg_type else 0
    return CTM + message_header(size_hw, msg_type, seq, MJD, ms) + b"\x00" * 2400 + FCS


def metadata_record(ms: int) -> tuple[bytes, dict]:
    segments, counts, seq = [], {}, 0
    for msg_type, count in METADATA_LAYOUT:
        for index in range(count):
            seq += 1
            written = msg_type if index == 0 else 0
            segments.append(fixed_segment(written, seq, ms))
            counts[str(written)] = counts.get(str(written), 0) + 1
    blob = b"".join(segments)
    assert len(blob) == 134 * SEGMENT == 325888
    return blob, counts


def _gate_octets(block: dict) -> bytes:
    codes = [code for code, count in block["runs"] for _ in range(count)]
    return struct.pack(">%d%s" % (len(codes), "B" if block["word_size"] == 8 else "H"), *codes)


def moment_octets(block: dict) -> bytes:
    """Table XVII-B: 'D', the name, then the 24 octets of fields, then the gate words."""
    header = (
        b"D"
        + block["name"].encode("ascii")
        + struct.pack(
            ">IHHHHhBBff",
            block["reserved"],
            block["gates"],
            block["first_gate_range"],
            block["gate_interval"],
            block["tover"],
            block["snr_threshold"],
            block["control_flags"],
            block["word_size"],
            block["scale"],
            block["offset"],
        )
    )
    assert len(header) == 28
    return header + _gate_octets(block)


def vol_octets(site: dict, v: dict) -> bytes:
    block = b"RVOL" + struct.pack(
        ">HBBffhHfffffHHH",
        52,
        v["version_major"],
        v["version_minor"],
        site["latitude"],
        site["longitude"],
        site["site_height"],
        site["tower_height"],
        v["dbz0"],
        v["horizontal_tx_power"],
        v["vertical_tx_power"],
        v["system_zdr"],
        v["initial_system_phidp"],
        v["vcp"],
        v["processing_status"],
        v["zdr_bias"],
    )
    block += b"\x00" * 6  # Table XVII-E octets 46 to 51, spare
    assert len(block) == 52
    return block


def elv_octets(e: dict) -> bytes:
    block = b"RELV" + struct.pack(">Hhf", 12, e["atmospheric_attenuation"], e["dbz0"])
    assert len(block) == 12
    return block


def rad_octets(r: dict) -> bytes:
    block = b"RRAD" + struct.pack(
        ">HHffHHff",
        28,
        r["unambiguous_range"],
        r["noise_level_h"],
        r["noise_level_v"],
        r["nyquist_velocity"],
        r["radial_flags"],
        r["calibration_h"],
        r["calibration_v"],
    )
    assert len(block) == 28
    return block


def radial_data(icao: str, site: dict, r: dict) -> bytes:
    """Table XVII-A's data header, one pointer per block, then the blocks in pointer order."""
    blocks = [vol_octets(site, r["vol"]), elv_octets(r["elv"]), rad_octets(r["rad"])]
    blocks += [moment_octets(m) for m in r["moments"]]
    header_length = 32 + 4 * len(blocks)
    pointers, offset = [], header_length
    for block in blocks:
        pointers.append(offset)
        offset += len(block)
    radial_length = r.get("radial_length_override", offset)
    header = icao.encode("ascii") + struct.pack(
        ">IHHfBBHBBBBfBBH",
        r["collection_time"],
        r["julian_date"],
        r["azimuth_number"],
        r["azimuth_angle"],
        r["compression"],
        0,
        radial_length,
        r["azimuth_spacing"],
        r["radial_status"],
        r["elevation_number"],
        r["cut_sector"],
        r["elevation_angle"],
        r["spot_blanking"],
        r["azimuth_indexing"],
        len(blocks),
    )
    header += struct.pack(">%dI" % len(pointers), *pointers)
    data = header + b"".join(blocks)
    assert len(data) == offset
    return data


def message_31(data: bytes, seq: int, ms: int, msg_type: int = 31) -> tuple[bytes, int]:
    """CTM, the Table II header, the radial (padded to a halfword). The message occupies
    12 + 2 x size octets in the record (no FCS for a variable-length message)."""
    padded = data + (b"\x00" if len(data) % 2 else b"")
    size_hw = (16 + len(padded)) // 2
    return CTM + message_header(size_hw, msg_type, seq, MJD, ms) + padded, size_hw


def ldm_record(blob: bytes, negative: bool = False) -> tuple[bytes, int]:
    """7.3.4: the signed control word (its absolute value is the stream's size), then bzip2."""
    stream = bz2.compress(blob, 9)
    word = -len(stream) if negative else len(stream)
    return struct.pack(">i", word) + stream, word


# -- one volume, encoded and stated -------------------------------------------------------------


def _f32_fields(fields: dict, names: tuple) -> dict:
    return {k: (f32(v) if k in names else v) for k, v in fields.items()}


VOL_FLOATS = (
    "dbz0",
    "horizontal_tx_power",
    "vertical_tx_power",
    "system_zdr",
    "initial_system_phidp",
)
RAD_FLOATS = ("noise_level_h", "noise_level_v", "calibration_h", "calibration_v")


def build_volume(spec: dict) -> tuple[bytes, dict]:
    """(octets, twin) for one volume `spec`:

    version, extension, icao, site, records (each a list of ("radial", r) or ("status",) items,
    with `negative` naming the records whose control word is written negative)."""
    icao = spec["icao"]
    site = spec["site"]
    header = (
        b"AR2V00"
        + spec.get("version", "06").encode("ascii")
        + b"."
        + spec.get("extension", "001").encode("ascii")
        + struct.pack(">II", MJD, START_MS)
        + icao.encode("ascii")
    )
    assert len(header) == 24
    out = [header]
    records_twin = []
    sweeps: dict[int, list] = {}
    gates_twin = []
    meta_blob, meta_counts = metadata_record(START_MS)
    record, word = ldm_record(meta_blob)
    out.append(record)
    records_twin.append(
        {
            "control_word": word,
            "compressed_bytes": abs(word),
            "decompressed_bytes": len(meta_blob),
            "messages": 134,
            "message_types": dict(sorted(meta_counts.items(), key=lambda kv: int(kv[0]))),
        }
    )
    seq = 134
    for record_index, items in enumerate(spec["records"], start=1):
        parts, counts = [], {}
        for message_index, item in enumerate(items):
            seq += 1
            if item[0] == "status":
                parts.append(fixed_segment(2, seq, START_MS))
                counts["2"] = counts.get("2", 0) + 1
                continue
            r = item[1]
            data = radial_data(icao, site, r)
            msg_type = r.get("message_type", 31)
            octets, size_hw = message_31(data, seq, r["collection_time"], msg_type)
            parts.append(octets)
            counts[str(msg_type)] = counts.get(str(msg_type), 0) + 1
            stated = {
                "ldm_record": record_index,
                "message": message_index,
                "message_header": {
                    "size": size_hw,
                    "channel": CHANNEL,
                    "sequence": seq,
                    "julian_date": MJD,
                    "milliseconds": r["collection_time"],
                    "segments": 1,
                    "segment_number": 1,
                },
                "collection_time": r["collection_time"],
                "julian_date": r["julian_date"],
                "azimuth_number": r["azimuth_number"],
                "azimuth_angle": f32(r["azimuth_angle"]),
                "compression": r["compression"],
                "radial_length": len(data),
                "azimuth_spacing": r["azimuth_spacing"],
                "radial_status": r["radial_status"],
                "elevation_number": r["elevation_number"],
                "cut_sector": r["cut_sector"],
                "elevation_angle": f32(r["elevation_angle"]),
                "spot_blanking": r["spot_blanking"],
                "azimuth_indexing": r["azimuth_indexing"],
                "block_count": 3 + len(r["moments"]),
                "vol": _f32_fields(r["vol"], VOL_FLOATS),
                "elv": _f32_fields(r["elv"], ("dbz0",)),
                "rad": _f32_fields(r["rad"], RAD_FLOATS),
                "moments": [
                    {
                        **{k: v for k, v in m.items() if k != "runs"},
                        "scale": f32(m["scale"]),
                        "offset": f32(m["offset"]),
                    }
                    for m in r["moments"]
                ],
            }
            sweeps.setdefault(r["elevation_number"], []).append(stated)
            for m in r["moments"]:
                gates_twin.append(
                    {
                        "elevation_number": r["elevation_number"],
                        "azimuth_number": r["azimuth_number"],
                        "moment": m["name"],
                        "runs": m["runs"],
                    }
                )
        blob = b"".join(parts)
        record, word = ldm_record(blob, negative=record_index in spec.get("negative", ()))
        out.append(record)
        records_twin.append(
            {
                "control_word": word,
                "compressed_bytes": abs(word),
                "decompressed_bytes": len(blob),
                "messages": len(items),
                "message_types": dict(sorted(counts.items(), key=lambda kv: int(kv[0]))),
            }
        )
    octets = b"".join(out)
    twin = {
        "wire_hex": octets.hex(),
        "volume_header": {
            "tape": "AR2V00" + spec.get("version", "06") + ".",
            "extension": spec.get("extension", "001"),
            "julian_date": MJD,
            "milliseconds": START_MS,
            "icao": icao,
        },
        "site": {
            "latitude": f32(site["latitude"]),
            "longitude": f32(site["longitude"]),
            "site_height": site["site_height"],
            "tower_height": site["tower_height"],
        },
        "records": records_twin,
        "sweeps": [
            {"elevation_number": number, "radials": sweeps[number]} for number in sorted(sweeps)
        ],
        "gates": gates_twin,
    }
    return octets, twin


# -- the cases -----------------------------------------------------------------------------------

SITE = {"latitude": 57.25, "longitude": 22.5, "site_height": 120, "tower_height": 30}
SITE_B = {"latitude": 56.75, "longitude": 21.25, "site_height": -5, "tower_height": 25}


def _ms(seconds: float) -> int:
    return START_MS + int(round(seconds * 1000))


CASES: dict[str, dict] = {
    # The F10 shape: one elevation of two radials, every moment at its Table XVII-I gate count,
    # beginning (3) then end (4) of the volume.
    "all_moments_one_elevation": {
        "icao": "ZZZZ",
        "site": SITE,
        "records": [
            [
                (
                    "radial",
                    radial(
                        elevation=1, azimuth=1, angle=0.25, status=3, ms=_ms(0), elevation_angle=0.5
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=2,
                        angle=0.75,
                        status=4,
                        ms=_ms(0.027),
                        elevation_angle=0.5,
                    ),
                ),
            ]
        ],
    },
    # Two elevations in two LDM records, an RDA status message (type 2) in the first, and the
    # second record's control word written NEGATIVE (7.3.4: its absolute value is the size).
    "two_elevations_two_records": {
        "icao": "ZZZZ",
        "site": SITE,
        "negative": (2,),
        "records": [
            [
                (
                    "radial",
                    radial(
                        elevation=1, azimuth=1, angle=0.25, status=3, ms=_ms(0), elevation_angle=0.5
                    ),
                ),
                ("status",),
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=2,
                        angle=0.75,
                        status=2,
                        ms=_ms(0.5),
                        elevation_angle=0.5,
                    ),
                ),
            ],
            [
                (
                    "radial",
                    radial(
                        elevation=2,
                        azimuth=1,
                        angle=0.5,
                        status=0,
                        ms=_ms(12.0),
                        elevation_angle=1.5,
                        azimuth_spacing=2,
                        rad=rad(unambiguous_range=1750, nyquist_velocity=2650),
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=2,
                        azimuth=2,
                        angle=1.5,
                        status=4,
                        ms=_ms(12.25),
                        elevation_angle=1.5,
                        azimuth_spacing=2,
                        rad=rad(unambiguous_range=1750, nyquist_velocity=2650),
                    ),
                ),
            ],
        ],
    },
    # SAILS: the lowest angle (0.5) is scanned again as elevation 3 inside the volume. Three
    # elevation NUMBERS, three sweeps, two of them at one angle. A second site, XZZA.
    "sails_repeated_lowest_angle": {
        "icao": "XZZA",
        "site": SITE_B,
        "version": "07",
        "extension": "002",
        "records": [
            [
                (
                    "radial",
                    radial(
                        elevation=1, azimuth=1, angle=0.25, status=3, ms=_ms(0), elevation_angle=0.5
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=2,
                        angle=0.75,
                        status=2,
                        ms=_ms(0.03),
                        elevation_angle=0.5,
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=2,
                        azimuth=1,
                        angle=0.25,
                        status=0,
                        ms=_ms(20.0),
                        elevation_angle=0.875,
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=2,
                        azimuth=2,
                        angle=0.75,
                        status=2,
                        ms=_ms(20.03),
                        elevation_angle=0.875,
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=3,
                        azimuth=1,
                        angle=0.25,
                        status=5,
                        ms=_ms(40.0),
                        elevation_angle=0.5,
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=3,
                        azimuth=2,
                        angle=0.75,
                        status=4,
                        ms=_ms(40.03),
                        elevation_angle=0.5,
                    ),
                ),
            ]
        ],
    },
    # Coded gates kept apart: below-threshold (0) and range-folded (1) counts that differ per
    # radial and per moment; CFP's own codes 0 to 7; a bad-data radial (0x81); spot blanking that
    # varies; a VEL scale that changes between radials (Table XVII-I note 20); and an elevation
    # angle that differs per radial, as an antenna's measured angle does.
    "coded_gates_and_bad_radial": {
        "icao": "ZZZZ",
        "site": SITE,
        "records": [
            [
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=1,
                        angle=0.25,
                        status=3,
                        ms=_ms(0),
                        elevation_angle=0.4921875,
                        spot_blanking=6,
                        moments=every_moment(
                            REF=[[0, 5], [1, 3], [2, 1], [130, 1831]],
                            VEL=[[1, 4], [127, 2], [131, 1194]],
                            CFP=[[0, 2], [1, 3], [2, 4], [3, 1], [7, 1], [8, 1829]],
                        ),
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=2,
                        angle=0.75,
                        status=0x81,
                        ms=_ms(0.025),
                        elevation_angle=0.5,
                        spot_blanking=6,
                        moments=every_moment(
                            REF=[[1, 7], [255, 1833]],
                            VEL=[[0, 2], [129, 1198]],
                        ),
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=3,
                        angle=1.25,
                        status=4,
                        ms=_ms(0.05),
                        elevation_angle=0.5078125,
                        spot_blanking=7,
                        moments=every_moment(
                            REF=[[0, 2], [100, 1838]],
                            VEL={"runs": [[129, 1200]], "scale": 1.0},
                        ),
                    ),
                ),
            ]
        ],
    },
    # One sweep across two LDM records: radials 1 and 2 in record 1, radial 3 in record 2, so the
    # sweep's locator names record 1 and message 0 and the residual names each radial's own.
    "one_sweep_across_two_records": {
        "icao": "ZZZZ",
        "site": SITE,
        "records": [
            [
                (
                    "radial",
                    radial(
                        elevation=1, azimuth=1, angle=0.25, status=3, ms=_ms(0), elevation_angle=0.5
                    ),
                ),
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=2,
                        angle=0.75,
                        status=1,
                        ms=_ms(0.02),
                        elevation_angle=0.5,
                    ),
                ),
            ],
            [
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=3,
                        angle=1.25,
                        status=4,
                        ms=_ms(0.04),
                        elevation_angle=0.5,
                    ),
                ),
            ],
        ],
    },
}


# -- malformed -----------------------------------------------------------------------------------


def _one_radial_volume(**radial_over) -> bytes:
    spec = {
        "icao": "ZZZZ",
        "site": SITE,
        "records": [
            [
                (
                    "radial",
                    radial(
                        elevation=1,
                        azimuth=1,
                        angle=0.25,
                        status=3,
                        ms=_ms(0),
                        elevation_angle=0.5,
                        **radial_over,
                    ),
                ),
            ]
        ],
    }
    return build_volume(spec)[0]


def _record_offsets(octets: bytes) -> list[tuple[int, int]]:
    """(offset of the control word, size of the stream) of every LDM record."""
    out, pos = [], 24
    while pos < len(octets):
        size = abs(struct.unpack(">i", octets[pos : pos + 4])[0])
        out.append((pos, size))
        pos += 4 + size
    return out


def _replace_record(octets: bytes, index: int, blob: bytes) -> bytes:
    pos, size = _record_offsets(octets)[index]
    record, _ = ldm_record(blob)
    return octets[:pos] + record + octets[pos + 4 + size :]


def _radial_blob(msg_type: int = 31, **radial_over) -> bytes:
    r = radial(
        elevation=1, azimuth=1, angle=0.25, status=3, ms=_ms(0), elevation_angle=0.5, **radial_over
    )
    return message_31(radial_data("ZZZZ", SITE, r), 135, r["collection_time"], msg_type)[0]


def _tiny_radial_blob() -> bytes:
    """The research's 623-octet form: one REF moment of four gates, so the Radial Length (196)
    is far below Table XVII-A's 9,360."""
    r = radial(
        elevation=1,
        azimuth=1,
        angle=0.25,
        status=3,
        ms=_ms(0),
        elevation_angle=0.5,
        moments=[moment("REF", [[0, 1], [1, 1], [2, 1], [130, 1]], gates=4)],
    )
    return message_31(radial_data("ZZZZ", SITE, r), 135, r["collection_time"])[0]


def _crc_flipped(octets: bytes) -> bytes:
    """The radial record's bzip2 block CRC (stream octets 10 to 13, after 'BZh9' and the block
    magic 31 41 59 26 53 59) with one bit flipped."""
    pos, _ = _record_offsets(octets)[1]
    at = pos + 4 + 10
    return octets[:at] + bytes([octets[at] ^ 0x01]) + octets[at + 1 :]


def _stream_cut_short(octets: bytes) -> bytes:
    """The radial record's stream cut by 20 octets and its control word rewritten to match, so
    the record is whole and its bzip2 stream ends before its end-of-stream marker."""
    pos, size = _record_offsets(octets)[1]
    stream = octets[pos + 4 : pos + 4 + size - 20]
    return octets[:pos] + struct.pack(">i", len(stream)) + stream


def _status_flood() -> bytes:
    """The declared max_decompressed_bytes passed by well-formed records: the metadata record,
    then 193 records each holding 862 RDA status segments (2,096,384 octets, under the per-record
    bound of 2 MiB). 325,888 + 193 x 2,096,384 = 404,928,000 octets, past 402,979,072, so the
    193rd record is refused before its last octet is kept. One record, repeated, so the file
    stays small."""
    octets = _one_radial_volume()
    pos, size = _record_offsets(octets)[1]
    blob = fixed_segment(2, 135, START_MS) * 862
    record, _ = ldm_record(blob)
    return octets[:pos] + record * 193


VALID = build_volume(CASES["all_moments_one_elevation"])[0]
META_BLOB = metadata_record(START_MS)[0]

#: name -> the octets of a volume the adapter must refuse. malformed/README.md states what is
#: wrong with each and the code it is refused with.
MALFORMED: dict[str, bytes] = {
    "truncated_record": VALID[:-40],
    "short_volume_header": VALID[:20],
    "bzip2_crc_corrupt": _crc_flipped(VALID),
    "bzip2_stream_cut_short": _stream_cut_short(VALID),
    "negative_control_word_past_the_file": VALID[:24] + struct.pack(">i", -(10**9)) + VALID[28:],
    "message_1_legacy_radial": _replace_record(VALID, 1, _radial_blob(msg_type=1)),
    "message_29_model_data_record": VALID
    + ldm_record(CTM + message_header(1208, 29, 200, MJD, START_MS) + b"\x00" * 2400)[0],
    "compression_indicator_bzip2": _replace_record(VALID, 1, _radial_blob(compression=1)),
    "compression_indicator_zlib": _replace_record(VALID, 1, _radial_blob(compression=2)),
    "radial_length_out_of_range": _replace_record(VALID, 1, _tiny_radial_blob()),
    "decompresses_past_the_bound": _status_flood(),
    "metadata_record_past_its_size": _replace_record(VALID, 0, META_BLOB + b"\x00" * SEGMENT),
    "azimuth_number_zero": _replace_record(VALID, 1, _radial_blob(azimuth_number=0)),
    "unexpected_message_type": _replace_record(
        VALID, 1, _radial_blob() + fixed_segment(3, 136, START_MS)
    ),
    "archive_version_05": VALID[:6] + b"05" + VALID[8:],
    "not_an_archive_ii_volume": b"BZh91AY&SY" + VALID[10:400],
}


# -- writing -------------------------------------------------------------------------------------


def twin_text(twin: dict) -> bytes:
    """Indented JSON, ASCII, with a final newline."""
    text = json.dumps(twin, indent=2, ensure_ascii=True)
    return (text + "\n").encode("ascii")


def provenance(directory: str, files: list[str], origin: str) -> bytes:
    record = {
        "directory": directory,
        "fixtures": [
            {
                "classification": "PUBLIC",
                "file": name,
                "operational_data": False,
                "origin": origin,
                "personal_data": False,
                "standard_ref": "nexrad2/spec/nexrad2_pin.json",
                "synthetic": True,
            }
            for name in sorted(files)
        ],
        "schema_id": "synapse.fixture-provenance/v1",
    }
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build() -> dict[pathlib.Path, bytes]:
    """Every generated file and its octets."""
    out: dict[pathlib.Path, bytes] = {}
    for name, spec in CASES.items():
        octets, twin = build_volume(spec)
        out[FIXTURES / f"{name}.ar2v"] = octets
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(twin)
    for name, octets in MALFORMED.items():
        out[MALFORMED_DIR / f"{name}.ar2v"] = octets
    payloads = sorted(p.name for p in out if p.parent == FIXTURES)
    out[FIXTURES / "PROVENANCE.json"] = provenance("nexrad2", payloads, ORIGIN)
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "nexrad2/malformed", [f"{name}.ar2v" for name in MALFORMED], MALFORMED_ORIGIN
    )
    return out


def _generated_here(directory: pathlib.Path) -> set[pathlib.Path]:
    """Files under `directory` (not below it) this script owns: payloads, twins, provenance."""
    if not directory.is_dir():
        return set()
    return {
        p
        for p in directory.iterdir()
        if p.is_file()
        and (p.suffix == ".ar2v" or p.name.endswith(".parsed.json") or p.name == "PROVENANCE.json")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    args = parser.parse_args(argv)
    built = build()
    if args.check:
        on_disk = _generated_here(FIXTURES) | _generated_here(MALFORMED_DIR)
        stale = sorted(
            {
                str(p.relative_to(FIXTURES))
                for p in built
                if not p.is_file() or p.read_bytes() != built[p]
            }
            | {str(p.relative_to(FIXTURES)) for p in on_disk - set(built)}
        )
        if stale:
            print("STALE: " + ", ".join(stale))
            return 1
        print("CURRENT")
        return 0
    MALFORMED_DIR.mkdir(exist_ok=True)
    for path, octets in built.items():
        path.write_bytes(octets)
    print(f"wrote {len(built)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
