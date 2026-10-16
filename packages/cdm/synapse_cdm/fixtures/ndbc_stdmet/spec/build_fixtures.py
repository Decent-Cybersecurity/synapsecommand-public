#!/usr/bin/env python3
"""Build the ndbc_stdmet fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py            # writes every generated file under fixtures/ndbc_stdmet/
    python -I -B build_fixtures.py --check    # builds everything in memory and compares it, byte
                                              # for byte, with the tree; prints CURRENT and exits
                                              # 0, or prints STALE: <names> and exits 1

Edit this file, never a `.stdmet`, a twin or a provenance record. `README.md` beside the payloads,
`malformed/README.md` and `spec/ndbc_stdmet_pin.json` are the hand-written files of the set, and
`golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Each fixture is a table of tokens written below as a literal: the header line, the units line
(or none, as NDBC files before 2007 have none) and the data rows, after the layouts the NDBC Web
Data Guide and NDBC's measurement descriptions give and research-station-text F01/F02 records —
the realtime file's 19 columns with `PTDY` and `MM` for a missing value, the historical file's 18
with runs of 9s, the 2004 file's 17 (`YYYY`, no minute, `BAR`, `TIDE`) and the 1998 file's 16
(`YY`, two-digit years). The script writes `<name>.stdmet` by padding every token of a column to
the column's widest and joining them with one space, LF line ends, and `<name>.parsed.json`, the
twin, from the SAME token lists: `header`, `units` (or null) and `rows`. It never reads what it
wrote back, and it shares no code with the adapter, so the twin is the expectation the adapter's
parse is held to.

`malformed/` holds files the adapter must refuse, each with the one thing wrong with it that
`malformed/README.md` names.

EVERYTHING IS SYNTHETIC. The station is `EX001` (CONTRIBUTING.md, "Identifiers and places in
observation fixtures"); a stdmet file states no station and no position, so neither appears in a
payload, and the position the adapter's fixture context gives the station lies in the Baltic
rectangle. Every value below is written here, not read from any NDBC file.
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
    "Synthetic NDBC standard meteorological file written on 2026-10-15 for the ndbc_stdmet "
    "adapter's landing by fixtures/ndbc_stdmet/spec/build_fixtures.py from a literal token table "
    "in that script, after the column layouts of the NDBC Web Data Guide and measurement "
    "descriptions (pinned or cited, never carried); the station is EX001 and nothing is recorded "
    "data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed NDBC standard meteorological file written on 2026-10-15 by "
    "fixtures/ndbc_stdmet/spec/build_fixtures.py, from literals in that script, for the "
    "conformance suite's check H; malformed/README.md names what is wrong with it and the "
    "refusal it expects. Nothing is recorded data."
)

REALTIME_HEADER = (
    "#YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE".split()
)
REALTIME_UNITS = "#yr mo dy hr mn degT m/s m/s m sec sec degT hPa degC degC degC nmi hPa ft".split()
HISTORICAL_HEADER = (
    "#YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS TIDE".split()
)
HISTORICAL_UNITS = "#yr mo dy hr mn degT m/s m/s m sec sec degT hPa degC degC degC mi ft".split()


def rows(text: str) -> list[list[str]]:
    return [line.split() for line in text.strip().splitlines()]


#: name -> (header, units or None, rows). Each is one file.
CASES: dict[str, tuple[list[str], list[str] | None, list[list[str]]]] = {
    # The realtime file: 19 columns with PTDY, newest row first, MM for every missing value, the
    # visibility in nautical miles, and the pressure tendency written with its sign, as the
    # realtime file gap-report-reconciliation R-05 saved prints it (read for its layout only): a
    # rising +0.3, a falling -0.5 and a signed zero +0.0.
    "realtime_newest_first": (
        REALTIME_HEADER,
        REALTIME_UNITS,
        rows(
            """
            2026 04 28 12 20 230  6.1  7.4    MM    MM    MM  MM 1012.4   9.8   8.6   6.9   MM +0.3    MM
            2026 04 28 12 10 225  5.8  7.0  0.90  5.00  3.90 210 1012.6   9.7   8.6   6.8   MM -0.5    MM
            2026 04 28 12 00 220  5.5  6.6    MM    MM    MM  MM 1012.8   9.6   8.6   6.8  4.8 +0.0    MM
            """
        ),
    ),
    # A historical file: 18 columns, no PTDY, oldest row first, a missing value as a run of 9s at
    # the width F02 documents for its column (WVHT, DPD, APD, TIDE 99.00; MWD 999; VIS 99.0;
    # WTMP 999.0), and the visibility's unit written mi.
    "historical_nine_runs": (
        HISTORICAL_HEADER,
        HISTORICAL_UNITS,
        rows(
            """
            2025 11 03 00 00 140 3.1 4.0 99.00 99.00 99.00 999 1018.2 11.4  12.9 9.0 99.0 99.00
            2025 11 03 00 10 145 3.3 4.2  1.10  7.00  5.20 150 1018.1 11.3  12.9 9.0 99.0 99.00
            2025 11 03 00 20 150 3.0 3.9  1.05  6.70  5.10 155 1018.0 11.3 999.0 8.9 99.0 99.00
            """
        ),
    ),
    # The 2004 layout: 17 columns, a four-digit YYYY, no minute column, BAR and WD, TIDE, and no
    # units line, so every value is a reading whose unit the file does not state.
    "before_2007_no_units_line": (
        "YYYY MM DD hh WD WSPD GST WVHT DPD APD MWD BAR ATMP WTMP DEWP VIS TIDE".split(),
        None,
        rows(
            """
            2004 09 01 18 310 7.9  9.8 1.60 6.20 5.00 300 1009.7 18.5 19.1 15.2 99.0 99.00
            2004 09 01 19 315 8.4 10.3 1.70 6.40 5.10 305 1009.9 18.2 19.1 15.0 99.0  0.75
            """
        ),
    ),
    # The 1998 layout: 16 columns, a two-digit YY, no minute column, BAR and WD, no units line.
    "two_digit_year_1998": (
        "YY MM DD hh WD WSPD GST WVHT DPD APD MWD BAR ATMP WTMP DEWP VIS".split(),
        None,
        rows(
            """
            98 06 15 00 200 4.2 5.1 0.80 5.00 4.10 190 1015.3 14.2 13.0 10.1 99.0
            98 06 15 01 205 4.6 5.6 0.85 5.30 4.20 195 1015.1 14.0 13.0 10.0 99.0
            """
        ),
    ),
}


def file_text(header: list[str], units: list[str] | None, body: list[list[str]]) -> str:
    """Columns padded to their widest token and joined with one space, LF line ends."""
    table = [header] + ([units] if units is not None else []) + body
    widths = [max(len(row[i]) for row in table if i < len(row)) for i in range(len(header))]
    lines = []
    for row in table:
        cells = [
            token.ljust(widths[i]) if i == 0 else token.rjust(widths[i])
            for i, token in enumerate(row)
        ]
        lines.append(" ".join(cells).rstrip() + "\n")
    return "".join(lines)


def _realtime(body: str) -> str:
    return file_text(REALTIME_HEADER, REALTIME_UNITS, rows(body))


def _historical(body: str) -> str:
    return file_text(HISTORICAL_HEADER, HISTORICAL_UNITS, rows(body))


GOOD_REALTIME_ROW = "2026 04 28 12 00 220 5.5 6.6 MM MM MM MM 1012.8 9.6 8.6 6.8 4.8 -0.3 MM"

#: name -> the text of a file the adapter must refuse. malformed/README.md states what is wrong
#: with each and the refusal code it expects.
MALFORMED: dict[str, str] = {
    "row_width_mismatch": _realtime(
        GOOD_REALTIME_ROW + "\n2026 04 28 11 50 215 5.2 6.2 MM MM MM MM 1013.0 9.5 8.6 6.7 4.9 -0.1"
    ),
    "undocumented_sentinel_width": _historical(
        "2025 11 03 00 00 140 3.1 4.0 1.10 7.00 5.20 150 9999.0 11.4 12.9 9.0 99.0 99.00"
    ),
    "documented_column_other_width": _historical(
        "2025 11 03 00 00 140 3.1 4.0 99.0 99.00 99.00 999 1018.2 11.4 12.9 9.0 99.0 99.00"
    ),
    "mm_in_historical_file": _historical(
        "2025 11 03 00 00 140 3.1 4.0 MM 99.00 99.00 999 1018.2 11.4 12.9 9.0 99.0 99.00"
    ),
    "not_a_number": _realtime(
        "2026 04 28 12 00 220 5,5 6.6 MM MM MM MM 1012.8 9.6 8.6 6.8 4.8 -0.3 MM"
    ),
    "unknown_column": file_text(
        "#YY MM DD hh mm WDIR WSPD SWH".split(),
        "#yr mo dy hr mn degT m/s m".split(),
        rows("2026 04 28 12 00 220 5.5 1.2"),
    ),
    "cut_inside_a_row": _realtime(GOOD_REALTIME_ROW)[:-12],
    "repeated_instant": _realtime(GOOD_REALTIME_ROW + "\n" + GOOD_REALTIME_ROW),
    "two_digit_year_under_yyyy": file_text(
        "YYYY MM DD hh WD WSPD".split(), None, rows("04 09 01 18 310 7.9")
    ),
    "two_digit_year_under_hash_yy": _realtime(
        "26 04 28 12 00 220 5.5 6.6 MM MM MM MM 1012.8 9.6 8.6 6.8 4.8 -0.3 MM"
    ),
    "two_digit_year_outside_the_record": file_text(
        "YY MM DD hh WD WSPD".split(), None, rows("05 06 15 00 200 4.2")
    ),
    "number_past_the_double_range": _realtime(
        "2026 04 28 12 00 220 " + "9" * 400 + ".0 6.6 MM MM MM MM 1012.8 9.6 8.6 6.8 4.8 -0.3 MM"
    ),
    "signed_value_outside_ptdy": _realtime(
        "2026 04 28 12 00 220 +5.5 6.6 MM MM MM MM 1012.8 9.6 8.6 6.8 4.8 -0.3 MM"
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
                "standard_ref": "ndbc_stdmet/spec/ndbc_stdmet_pin.json",
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
    for name, (header, units, body) in CASES.items():
        out[FIXTURES / f"{name}.stdmet"] = file_text(header, units, body).encode("ascii")
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(
            {"header": header, "units": units, "rows": body}
        )
    for name, text in MALFORMED.items():
        out[MALFORMED_DIR / f"{name}.stdmet"] = text.encode("ascii")
    payloads = sorted(p.name for p in out if p.parent == FIXTURES)
    out[FIXTURES / "PROVENANCE.json"] = provenance("ndbc_stdmet", payloads, ORIGIN)
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "ndbc_stdmet/malformed", [f"{name}.stdmet" for name in MALFORMED], MALFORMED_ORIGIN
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
        and (
            p.suffix == ".stdmet" or p.name.endswith(".parsed.json") or p.name == "PROVENANCE.json"
        )
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
