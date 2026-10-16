#!/usr/bin/env python3
"""Build the coops_csv fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py            # writes every generated file under fixtures/coops_csv/
    python -I -B build_fixtures.py --check    # builds everything in memory and compares it, byte
                                              # for byte, with the tree; prints CURRENT and exits
                                              # 0, or prints STALE: <names> and exits 1

Edit this file, never a `.csv`, a `.json`, a twin or a provenance record. `README.md` beside the
payloads, `malformed/README.md` and `spec/coops_csv_pin.json` are the hand-written files of the
set, and `golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Each CSV fixture is a header line and rows of fields written below as literals, after the
response layouts research-station-text F04 to F06 records from the CO-OPS data API: the
water-level header `Date Time, Water Level, Sigma, O or I (for verified), F, R, L, Quality`, rows
of a `YYYY-MM-DD HH:MM` stamp, the value, sigma, four flags and the p/v quality level. The script
writes `<name>.csv` (the header line as written, each row's fields joined by commas, LF line ends)
and `<name>.parsed.json`, the twin, from the SAME literals: `form` "csv", the `header` line and
the `rows`. The JSON-form fixture is the response document itself (`metadata` and `data`, every
value a string), written with `json.dumps`; it is a `.json` payload, so it needs no twin. Nothing
is read back, and nothing is shared with the adapter, so the twin is the expectation the
adapter's parse is held to.

Every fixture is a response to ONE request — station `0000001`, product `water_level`, datum
MLLW, units metric, time zone gmt, interval 6 — the adapter's fixture context, because a response
does not state the request it answers (F05).

`malformed/` holds responses the adapter must refuse under that request, each with the one thing
wrong with it that `malformed/README.md` names.

EVERYTHING IS SYNTHETIC. The station is `0000001` (CONTRIBUTING.md, "Identifiers and places in
observation fixtures"), the JSON form's position lies in the Baltic rectangle, and every value
below is written here, not read from any CO-OPS response.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
MALFORMED_DIR = FIXTURES / "malformed"

ORIGIN = (
    "Synthetic NOAA CO-OPS data API response written on 2026-10-15 for the coops_csv adapter's "
    "landing by fixtures/coops_csv/spec/build_fixtures.py from literals in that script, after "
    "the response layouts the API's pages give (cited by URL, never carried); the station is "
    "0000001 and nothing is recorded data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed NOAA CO-OPS data API response written on 2026-10-15 by "
    "fixtures/coops_csv/spec/build_fixtures.py, from literals in that script, for the "
    "conformance suite's check H; malformed/README.md names what is wrong with it and the "
    "refusal it expects. Nothing is recorded data."
)

WATER_LEVEL = "Date Time, Water Level, Sigma, O or I (for verified), F, R, L, Quality"
AIR_PRESSURE = "Date Time, Pressure, X, N, R "


def rows(text: str) -> list[list[str]]:
    return [line.strip().split(",") for line in text.strip().splitlines()]


#: name -> (header line, rows). Each is one CSV response.
CASES: dict[str, tuple[str, list[list[str]]]] = {
    # Preliminary samples six minutes apart; the third's O flag counts three one-second samples
    # outside three sigma (a count, not a bit).
    "water_level_preliminary": (
        WATER_LEVEL,
        rows(
            """
            2026-04-28 00:00,0.412,0.021,0,0,0,0,p
            2026-04-28 00:06,0.430,0.019,0,0,0,0,p
            2026-04-28 00:12,0.447,0.024,3,0,0,0,p
            """
        ),
    ),
    # Verified samples: the fourth column is I (inferred) and the seventh T, and one is inferred.
    "water_level_verified": (
        WATER_LEVEL,
        rows(
            """
            2026-04-27 12:00,0.215,0.011,0,0,0,0,v
            2026-04-27 12:06,0.220,0.013,1,0,0,0,v
            """
        ),
    ),
    # Water below the datum (negative against MLLW), the flat, rate and limit flags set, and a
    # preliminary run followed by a verified sample.
    "water_level_below_datum_flagged": (
        WATER_LEVEL,
        rows(
            """
            2026-04-28 06:00,-0.118,0.030,0,1,0,0,p
            2026-04-28 06:06,-0.142,0.045,0,0,1,1,p
            2026-04-28 06:12,-0.150,0.020,0,0,0,0,v
            """
        ),
    ),
}

#: name -> the JSON response document. A `.json` payload, read by the harness as a dict.
JSON_CASES: dict[str, dict] = {
    "water_level_json_form": {
        "metadata": {
            "id": "0000001",
            "name": "EX synthetic gauge",
            "lat": "57.0213",
            "lon": "21.0877",
        },
        "data": [
            {"t": "2026-04-28 03:00", "v": "0.512", "s": "0.018", "f": "0,0,0,0", "q": "p"},
            {"t": "2026-04-28 03:06", "v": "0.508", "s": "0.016", "f": "1,0,0,0", "q": "p"},
        ],
    },
}


def csv_text(header: str, body: list[list[str]]) -> str:
    return header + "\n" + "".join(",".join(row) + "\n" for row in body)


def json_text(document: dict) -> str:
    return json.dumps(document, separators=(",", ":"), ensure_ascii=True) + "\n"


GOOD = "2026-04-28 00:00,0.412,0.021,0,0,0,0,p"

#: name -> (suffix, text) of a response the adapter must refuse. malformed/README.md states what
#: is wrong with each and the refusal code it expects.
MALFORMED: dict[str, tuple[str, str]] = {
    "unknown_header": (".csv", "Date Time, Prediction\n2026-04-28 00:00,0.412\n"),
    "air_pressure_header": (".csv", AIR_PRESSURE + "\n2026-04-28 00:00,1012.4,0,0,0\n"),
    "row_width_mismatch": (
        ".csv",
        csv_text(WATER_LEVEL, rows(GOOD + "\n2026-04-28 00:06,0.430,0.019,0,0,0,p")),
    ),
    "not_a_number": (".csv", csv_text(WATER_LEVEL, rows("2026-04-28 00:00,0.4l2,0.021,0,0,0,0,p"))),
    "stamp_with_seconds": (
        ".csv",
        csv_text(WATER_LEVEL, rows("2026-04-28 00:00:00,0.412,0.021,0,0,0,0,p")),
    ),
    "blank_value": (".csv", csv_text(WATER_LEVEL, rows("2026-04-28 00:00,,0.021,0,0,0,0,p"))),
    "quality_not_p_or_v": (
        ".csv",
        csv_text(WATER_LEVEL, rows("2026-04-28 00:00,0.412,0.021,0,0,0,0,x")),
    ),
    "cut_inside_a_row": (".csv", csv_text(WATER_LEVEL, rows(GOOD))[:-9]),
    "json_station_disagrees": (
        ".json",
        json_text(
            {
                "metadata": {
                    "id": "0000002",
                    "name": "EX synthetic gauge",
                    "lat": "57.0213",
                    "lon": "21.0877",
                },
                "data": [
                    {"t": "2026-04-28 03:00", "v": "0.512", "s": "0.018", "f": "0,0,0,0", "q": "p"}
                ],
            }
        ),
    ),
    "json_unknown_key": (
        ".json",
        json_text(
            {
                "metadata": {
                    "id": "0000001",
                    "name": "EX synthetic gauge",
                    "lat": "57.0213",
                    "lon": "21.0877",
                },
                "data": [
                    {"t": "2026-04-28 03:00", "v": "0.512", "s": "0.018", "f": "0,0,0,0", "q": "p"}
                ],
                "error": {"message": "EX"},
            }
        ),
    ),
    "number_past_the_double_range": (
        ".csv",
        csv_text(WATER_LEVEL, rows("2026-04-28 00:00," + "9" * 400 + ".0,0.021,0,0,0,0,p")),
    ),
    "flag_past_the_double_range": (
        ".csv",
        csv_text(WATER_LEVEL, rows("2026-04-28 00:00,0.412,0.021," + "9" * 400 + ",0,0,0,p")),
    ),
}


def twin_text(twin: dict) -> bytes:
    """Indented JSON, ASCII, with a final newline."""
    return (json.dumps(twin, indent=2, ensure_ascii=True) + "\n").encode("ascii")


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
                "standard_ref": "coops_csv/spec/coops_csv_pin.json",
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
    for name, (header, body) in CASES.items():
        out[FIXTURES / f"{name}.csv"] = csv_text(header, body).encode("ascii")
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(
            {"form": "csv", "header": header, "rows": body}
        )
    for name, document in JSON_CASES.items():
        out[FIXTURES / f"{name}.json"] = json_text(document).encode("ascii")
    for name, (suffix, text) in MALFORMED.items():
        out[MALFORMED_DIR / f"{name}{suffix}"] = text.encode("ascii")
    payloads = sorted(p.name for p in out if p.parent == FIXTURES)
    out[FIXTURES / "PROVENANCE.json"] = provenance("coops_csv", payloads, ORIGIN)
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "coops_csv/malformed",
        [f"{name}{suffix}" for name, (suffix, _) in MALFORMED.items()],
        MALFORMED_ORIGIN,
    )
    return out


def _generated_here(directory: pathlib.Path) -> set[pathlib.Path]:
    """Files under `directory` (not below it) this script owns: payloads, twins, provenance."""
    if not directory.is_dir():
        return set()
    return {p for p in directory.iterdir() if p.is_file() and p.suffix in (".csv", ".json")}


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
