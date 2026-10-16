#!/usr/bin/env python3
"""Build the readsb_trace fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py            # writes every generated file under fixtures/readsb_trace/
    python -I -B build_fixtures.py --check    # builds everything in memory and compares it, byte
                                              # for byte, with the tree; prints CURRENT and exits
                                              # 0, or prints STALE: <names> and exits 1

Edit this file, never a `.trace`, a twin or a provenance record. `README.md` beside the payloads,
`malformed/README.md` and `spec/readsb_trace_pin.json` are the hand-written files of the set, and
`golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Every trace below is a literal document (`CASES`), written for this repository from the field
order of readsb's README-json.md, section "trace jsons" (pinned by URL and SHA-256 in
`readsb_trace_pin.json`, never carried). For each one the script writes `<name>.trace`, the
document as compact UTF-8 JSON inside one gzip member, as readsb writes a permanent trace behind
a `.json` name, and `<name>.parsed.json`, the same document as indented JSON, which is what the
harness's lossless ledger reads. `malformed/` holds payloads the adapter must refuse; each is a
literal document or literal octets with the one thing wrong with it named in `MALFORMED`.

DETERMINISM
-----------
The gzip member is assembled here rather than by the `gzip` module, whose header differs between
interpreters (3.12 lets zlib write the operating-system octet, 3.14 writes its own): a fixed
ten-octet header (no name, modification time 0, XFL 2 for maximum compression, OS 3 for Unix, as
zlib writes it on the systems readsb runs on), the raw deflate stream from `zlib` at level 9 with
its default window and memory level, then the CRC-32 and the length. The deflate octets depend
on the zlib build; the pin records the one these were written with, and a zlib that deflates
differently is a new pin, not a defect, and --check names every file that moved. No clock, host
name, random value or absolute path reaches an output.

EVERYTHING IS SYNTHETIC. Every address is in the `0029xx` block below the ICAO allocation table's
lowest state block, every callsign begins EX, every position lies in the Baltic rectangle of
CONTRIBUTING.md, the readsb version string names commit 0000000, no file states a registration,
a type, an owner or a year, and nothing derives from recorded data.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
import zlib

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
MALFORMED_DIR = FIXTURES / "malformed"

#: 2026-03-14T00:00:00Z and the next UTC midnight, in seconds since the epoch.
DAY_ONE = 1773446400.0
DAY_TWO = 1773532800.0
VERSION = "readsb 3.16.17 0000000"

ORIGIN = (
    "Synthetic readsb trace written on 2026-10-15 for the readsb_trace adapter's landing by "
    "fixtures/readsb_trace/spec/build_fixtures.py from a literal document in that script, after "
    "the field order of readsb's README-json.md (pinned by URL and SHA-256, never carried); the "
    "address is in the 0029xx block, positions are in the Baltic rectangle, nothing is recorded "
    "data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed readsb trace written on 2026-10-15 by "
    "fixtures/readsb_trace/spec/build_fixtures.py, from a literal in that script, for the "
    "conformance suite's check H; malformed/README.md names what is wrong with it and the "
    "refusal it expects. Nothing is recorded data."
)


def point(offset, lat, lon, altitude, gs, track, flags, vrate, aircraft=None, *rest):
    """One trace point, elements 0 to 8, then whatever the case adds (9 to 13, and past)."""
    return [offset, lat, lon, altitude, gs, track, flags, vrate, aircraft, *rest]


def aircraft(**fields):
    return dict(fields)


#: name -> the trace document. One case per row of README.md's table. Laid out by hand, one
#: point per line where it fits, which is why the formatter is told to leave it alone.
# fmt: off
CASES: dict[str, dict] = {
    # An airborne ADS-B track in the 2022+ form: fourteen elements, barometric altitude, an
    # aircraft object on the first and last points. The address is the adsb fixtures' 0029C1.
    "airborne_adsb_2022_form": {
        "icao": "0029c1",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(
                36000.12, 57.201234, 22.912345, 32000, 441.5, 87.3, 0, 0,
                aircraft(type="adsb_icao", flight="EXRCS01 ", squawk="1200", category="A3",
                         nic=8, rc=186, version=2, nac_p=9, sil=3, sil_type="perhour"),
                "adsb_icao", 32675, 0, 280, 0.2,
            ),
            point(36010.37, 57.20212, 22.93318, 32000, 441.3, 87.4, 0, -64, None,
                  "adsb_icao", 32675, -32, 281, -0.4),
            point(36021.5, 57.203011, 22.954001, 31975, 440.8, 87.2, 0, -192, None,
                  "adsb_icao", 32650, -224, 281, 0.0),
            point(
                36032.25, 57.2039, 22.97482, 31950, 440.6, 87.2, 0, -128,
                aircraft(type="adsb_icao", flight="EXRCS01 ", squawk="1200", nic=8, rc=186),
                "adsb_icao", 32625, -160, 282, 0.1,
            ),
        ],
    },
    # On the ground: element 3 is the string ground and element 5 is then a TRUE HEADING.
    "ground_heading_slot": {
        "icao": "0029d1",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(29000.0, 56.92361, 23.97111, "ground", 0.0, 182.4, 0, None, None,
                  "adsb_icao", None, None, None, None),
            point(29030.5, 56.92302, 23.97108, "ground", 12.3, 181.9, 0, None,
                  aircraft(type="adsb_icao", flight="EXHELO2 ", category="A7", nic=9, rc=75),
                  "adsb_icao_nt", None, None, None, None),
        ],
    },
    # Multilateration: the aggregator solved the position, so it is ESTIMATED.
    "mlat_positions": {
        "icao": "0029e3",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(43200.0, 57.391, 21.562, 4500, 165.0, 270.0, 0, 640, None,
                  "mlat", None, None, None, None),
            point(43215.75, 57.391105, 21.55112, 4650, 166.2, 270.3, 1, 704, None,
                  "mlat", None, None, None, None),
        ],
    },
    # TIS-B: a ground station's rebroadcast, ESTIMATED; one point from a track file.
    "tisb_positions": {
        "icao": "0029e4",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(50000.0, 57.75, 22.5, 2500, 98.0, 10.0, 0, 0, None,
                  "tisb_icao", None, None, None, None),
            point(50012.0, 57.7531, 22.5011, 2500, 98.4, 10.1, 0, 0, None,
                  "tisb_trackfile", None, None, None, None),
        ],
    },
    # Every flag bit, alone and together. Bit 3 makes element 3 a geometric altitude, which is
    # the one altitude that reaches alt_m (feet x 0.3048); bit 2 makes element 7 geometric.
    "every_flag_bit": {
        "icao": "0029e5",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(60000.0, 58.1, 23.4, 10000, 300.0, 45.0, 0, 0, None,
                  "adsb_icao", 10350, 0, 250, 0.0),
            point(60020.0, 58.102, 23.403, 10000, 300.0, 45.0, 1, 0, None,
                  "adsb_icao", 10350, 0, 250, 0.0),
            point(60040.0, 58.104, 23.406, 10000, 300.0, 45.0, 2, 0, None,
                  "adsb_icao", 10350, 0, 250, 0.0),
            point(60060.0, 58.106, 23.409, 10000, 300.0, 45.0, 4, 64, None,
                  "adsb_icao", 10350, 64, 250, 0.0),
            point(60080.0, 58.108, 23.412, 5000, 300.0, 45.0, 8, 0, None,
                  "adsb_icao", 5000, 0, 250, 0.0),
            point(60100.0, 58.11, 23.415, 12500, 301.0, 45.5, 15, 64, None,
                  "adsb_icao", 12500, 64, 251, 0.0),
        ],
    },
    # A non-ICAO address (`~`): the id system is ADSB_NONICAO, never ICAO24.
    "nonicao_address": {
        "icao": "~0029b2",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(39600.0, 57.5, 21.9, 8000, 210.0, 135.0, 0, 0, None,
                  "adsb_other", None, None, None, None),
            point(39612.4, 57.4991, 21.9022, 8000, 210.2, 135.1, 0, 0, None,
                  "adsb_other", None, None, None, None),
        ],
    },
    # A trace written before 2022: nine elements, no source, and no version key.
    "pre2022_nine_elements": {
        "icao": "0029e6",
        "noRegData": True,
        "timestamp": DAY_ONE,
        "trace": [
            point(20000.0, 56.5, 21.0, 6000, 180.0, 300.0, 0, 0, None),
            point(20030.0, 56.503, 20.992, 6100, 181.0, 300.2, 0, 128, None),
        ],
    },
    # A readsb built with TRACKS_UUID appends a receiver id: a fifteenth element, parked.
    "receiver_id_fifteen_elements": {
        "icao": "0029e8",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(54000.0, 57.95, 24.1, 15000, 330.0, 200.0, 0, 0, None,
                  "adsb_icao", 15400, 0, 260, 0.0, "00000001"),
            point(54010.0, 57.9485, 24.0975, 15000, 330.0, 200.0, 0, 0, None,
                  "adsb_icao", 15400, 0, 260, 0.0, "00000002"),
        ],
    },
    # Nulls stay nulls: no altitude, no speed, no track, no rate. Element 3 null with element 10
    # stated takes the geometric altitude; the last point states nothing, so no kinematics.
    "null_altitude_and_speed": {
        "icao": "0029e9",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(70000.0, 56.8, 22.2, None, None, None, 0, None, None,
                  None, 1250, None, None, None),
            point(70010.0, 56.801, 22.201, None, None, None, 0, None, None,
                  "adsb_icao", None, None, None, None),
        ],
    },
    # A flight across UTC midnight is two files: this day's ends at 23:59:58.750 ...
    "midnight_fragment_day_one": {
        "icao": "0029e7",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(86340.0, 56.95, 24.05, 3000, 140.0, 250.0, 0, -512, None,
                  "adsb_icao", 3350, -512, 150, 0.0),
            point(86398.75, 56.94, 24.0, 2500, 138.0, 250.0, 0, -512, None,
                  "adsb_icao", 2850, -512, 148, 0.0),
        ],
    },
    # ... and the next day's begins at 00:00:01.250, under the next midnight; nothing joins them.
    "midnight_fragment_day_two": {
        "icao": "0029e7",
        "noRegData": True,
        "version": VERSION,
        "timestamp": DAY_TWO,
        "trace": [
            point(1.25, 56.937, 23.985, 2000, 136.0, 250.0, 2, -512, None,
                  "adsb_icao", 2350, -512, 146, 0.0),
            point(30.0, 56.931, 23.975, 1500, 132.0, 250.0, 0, -448, None,
                  "adsb_icao", 1850, -448, 140, 0.0),
        ],
    },
    # A live trace's reference is its first point, not a midnight: the adapter adds, and never
    # assumes either.
    "reference_not_midnight": {
        "icao": "0029ea",
        "noRegData": True,
        "version": VERSION,
        "timestamp": 1773486000.512,
        "trace": [
            point(0.0, 57.3, 23.3, 20000, 380.0, 330.0, 0, 0, None,
                  "adsr_icao", 20500, 0, 270, 0.0),
            point(5.48, 57.3082, 23.2921, 20000, 380.0, 330.0, 0, 0, None,
                  "adsr_icao", 20500, 0, 270, 0.0),
        ],
    },
    # Two points at one instant (allowed), and database flags with no database string.
    "equal_instants_and_db_flags": {
        "icao": "0029eb",
        "dbFlags": 9,
        "version": VERSION,
        "timestamp": DAY_ONE,
        "trace": [
            point(46800.0, 58.3, 22.7, 18000, 350.0, 5.0, 0, 0, None,
                  "adsb_icao", 18450, 0, 265, 0.0),
            point(46800.0, 58.3002, 22.7001, 18000, 350.0, 5.0, 0, 0, None,
                  "mlat", None, None, None, None),
            point(46810.5, 58.3151, 22.7019, 18000, 350.2, 5.0, 0, 0, None,
                  "adsb_icao", 18450, 0, 265, 0.0),
        ],
    },
}
# fmt: on

_BASE = CASES["airborne_adsb_2022_form"]


def _variant(**changes) -> dict:
    """The airborne case with top-level changes; a change of None removes the key."""
    document = json.loads(json.dumps(_BASE))
    for key, value in changes.items():
        if value is None:
            document.pop(key, None)
        else:
            document[key] = value
    return document


def _points(*edits) -> list:
    """The airborne case's points, with (index, element, value) edits; value ... drops the tail."""
    points = json.loads(json.dumps(_BASE["trace"]))
    for index, element, value in edits:
        if value is Ellipsis:
            del points[index][element:]
        else:
            points[index][element] = value
    return points


def gzip_member(data: bytes) -> bytes:
    """One gzip member with a fixed header (see the module docstring)."""
    deflater = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS, 8, zlib.Z_DEFAULT_STRATEGY)
    body = deflater.compress(data) + deflater.flush()
    header = b"\x1f\x8b\x08\x00" + b"\x00\x00\x00\x00" + b"\x02\x03"
    trailer = struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF)
    return header + body + trailer


def compact(document: dict) -> bytes:
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def twin(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _member_of(text: bytes) -> bytes:
    return gzip_member(text)


def _corrupt_deflate() -> bytes:
    member = gzip_member(compact(_BASE))
    # The first octet of the deflate stream set to 0xFF: block type 3, which RFC 1951 reserves.
    return member[:10] + b"\xff" + member[11:]


def _crc_mismatch() -> bytes:
    member = gzip_member(compact(_BASE))
    crc = struct.unpack("<I", member[-8:-4])[0] ^ 1
    return member[:-8] + struct.pack("<I", crc) + member[-4:]


#: name -> the octets of a payload the adapter must refuse. README.md in `malformed/` states what
#: is wrong with each and the code it is refused with.
# fmt: off
MALFORMED: dict[str, bytes] = {
    "fewer_than_nine_elements": gzip_member(compact(_variant(trace=_points((1, 8, ...))))),
    "offsets_not_monotonic": gzip_member(compact(_variant(trace=_points((2, 0, 36005.0))))),
    "negative_offset": gzip_member(compact(_variant(trace=_points((0, 0, -0.5))))),
    "latitude_out_of_range": gzip_member(compact(_variant(trace=_points((1, 1, 91.0))))),
    "longitude_out_of_range": gzip_member(compact(_variant(trace=_points((3, 2, 180.5))))),
    "ground_outside_element_three": gzip_member(
        compact(_variant(trace=_points((2, 4, "ground"))))
    ),
    "timestamp_not_a_number": gzip_member(compact(_variant(timestamp="1773446400.0"))),
    "deflate_data_corrupt": _corrupt_deflate(),
    "crc_mismatch": _crc_mismatch(),
    "truncated_gzip": gzip_member(compact(_BASE))[:200],
    "trailing_octets_after_the_member": gzip_member(compact(_BASE)) + b"\x00",
    "inflates_past_the_bound": gzip_member(b" " * (64 * 1024 * 1024 + 1)),
    "truncated_json": gzip_member(compact(_BASE)[:300]),
    "not_gzip": compact(_BASE),
    "empty_trace": gzip_member(compact(_variant(trace=[]))),
    "unknown_top_level_key": gzip_member(compact(_variant(squawk="1200"))),
    "uppercase_address": gzip_member(compact(_variant(icao="0029C1"))),
    "flags_outside_four_bits": gzip_member(compact(_variant(trace=_points((1, 6, 16))))),
    "unknown_position_source": gzip_member(
        compact(_variant(trace=_points((3, 9, "satellite"))))
    ),
    "duplicate_key": gzip_member(compact(_BASE).replace(b'{"icao":"0029c1",', b'{"icao":"0029c1","icao":"0029c1",', 1)),
    "nan_literal": gzip_member(compact(_BASE).replace(b'"timestamp":1773446400.0', b'"timestamp":NaN', 1)),
    "timestamp_past_a_double": gzip_member(compact(_BASE).replace(b'"timestamp":1773446400.0', b'"timestamp":1' + b"0" * 400, 1)),
    "lone_surrogate_in_version": gzip_member(compact(_BASE).replace(b'"version":"readsb 3.16.17 0000000"', b'"version":"readsb \\ud800 0000000"', 1)),
}
# fmt: on


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
                "standard_ref": "readsb_trace/spec/readsb_trace_pin.json",
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
    for name, document in CASES.items():
        out[FIXTURES / f"{name}.trace"] = gzip_member(compact(document))
        out[FIXTURES / f"{name}.parsed.json"] = twin(document)
    for name, octets in MALFORMED.items():
        out[MALFORMED_DIR / f"{name}.trace"] = octets
    payloads = sorted(p.name for p in out if p.parent == FIXTURES)
    out[FIXTURES / "PROVENANCE.json"] = provenance("readsb_trace", payloads, ORIGIN)
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "readsb_trace/malformed", [f"{name}.trace" for name in MALFORMED], MALFORMED_ORIGIN
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
        and (p.suffix == ".trace" or p.name.endswith(".parsed.json") or p.name == "PROVENANCE.json")
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
