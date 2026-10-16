#!/usr/bin/env python3
"""Build the airnow_hourly fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py            # writes every generated file under fixtures/airnow_hourly/
    python -I -B build_fixtures.py --check    # builds everything in memory and compares it, byte
                                              # for byte, with the tree; prints CURRENT and exits
                                              # 0, or prints STALE: <names> and exits 1

Edit this file, never a `.dat`, a twin or a provenance record. `README.md` beside the payloads,
`malformed/README.md` and `spec/airnow_hourly_pin.json` are the hand-written files of the set,
and `golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Each fixture is a list of lines of fields written below as literals, after the two AirNow fact
sheets (pinned by SHA-256, never carried) and research-station-text F08/F09:

- a HourlyData file: no header, nine `|`-delimited fields a line (valid date `mm/dd/yy`, valid
  time, AQSID, site name, GMT offset, parameter name, reporting units, value, data source), CRLF
  line ends, as the fact sheet and F08 describe;
- a HourlyAQObs file: the 34-name header and one line a site, every field quoted, CRLF line ends.

The script writes `<name>.dat` from the field lists and `<name>.parsed.json`, the twin, from the
SAME lists: `form` and `records` (HourlyData) or `form`, `header` and `rows` (HourlyAQObs).
Nothing is read back, and nothing is shared with the adapter, so the twin is the expectation the
adapter's parse is held to.

`malformed/` holds files the adapter must refuse, each with the one thing wrong with it that
`malformed/README.md` names.

EVERYTHING IS SYNTHETIC. Sites are `000000001` to `000000003` and `000000000011`
(CONTRIBUTING.md, "Identifiers and places in observation fixtures"), named `EX site ...`, every
stated position lies in the Baltic rectangle, the hour is 2026-04-28, and every value is written
here, not read from any AirNow file.
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
    "Synthetic EPA AirNow hourly observation file written on 2026-10-15 for the airnow_hourly "
    "adapter's landing by fixtures/airnow_hourly/spec/build_fixtures.py from literals in that "
    "script, after the AirNow fact sheets' layouts (pinned by SHA-256, never carried); the sites "
    "are in the 000000001 and 000000000011 blocks and nothing is recorded data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed EPA AirNow hourly observation file written on 2026-10-15 by "
    "fixtures/airnow_hourly/spec/build_fixtures.py, from literals in that script, for the "
    "conformance suite's check H; malformed/README.md names what is wrong with it and the "
    "refusal it expects. Nothing is recorded data."
)

AQOBS_HEADER = [
    "AQSID", "SiteName", "Status", "EPARegion", "Latitude", "Longitude", "Elevation",
    "GMTOffset", "CountryCode", "StateName", "ValidDate", "ValidTime", "DataSource",
    "ReportingArea_PipeDelimited", "OZONE_AQI", "PM10_AQI", "PM25_AQI", "NO2_AQI",
    "OZONE_Measured", "PM10_Measured", "PM25_Measured", "NO2_Measured", "PM25", "PM25_Unit",
    "OZONE", "OZONE_Unit", "NO2", "NO2_Unit", "CO", "CO_Unit", "SO2", "SO2_Unit", "PM10",
    "PM10_Unit",
]  # fmt: skip

AGENCY = "EX synthetic agency"


def records(text: str) -> list[list[str]]:
    return [line.strip().split("|") for line in text.strip().splitlines()]


def aqobs(**fields: str) -> list[str]:
    """One HourlyAQObs line: every field blank unless named."""
    unknown = set(fields) - set(AQOBS_HEADER)
    if unknown:
        raise SystemExit(f"not a HourlyAQObs field: {sorted(unknown)}")
    return [fields.get(name, "") for name in AQOBS_HEADER]


SITE_ONE = dict(
    AQSID="000000001", SiteName="EX site one", Status="Active", EPARegion="R0",
    Latitude="56.950000", Longitude="24.100000", Elevation="12.0", GMTOffset="2.0",
    CountryCode="XX", StateName="EX", DataSource=AGENCY,
    ReportingArea_PipeDelimited="EX area one|EX area two",
)  # fmt: skip
SITE_ELEVEN = dict(
    AQSID="000000000011", SiteName="EX site eleven", Status="Active", EPARegion="R0",
    Latitude="56.500000", Longitude="21.000000", Elevation="3.5", GMTOffset="2.0",
    CountryCode="XX", StateName="EX", DataSource=AGENCY, ReportingArea_PipeDelimited="EX area one",
)  # fmt: skip

#: name -> the twin. HourlyData twins are {form, records}; HourlyAQObs twins {form, header, rows}.
CASES: dict[str, dict] = {
    # Two sites the fixture site table places, several parameters each, and a negative raw
    # concentration (the fact sheet: valid raw concentrations may be negative).
    "hourly_data_two_sites": {
        "form": "HourlyData",
        "records": records(
            f"""
            04/28/26|10:00|000000001|EX site one|2|OZONE|PPB|31|{AGENCY}
            04/28/26|10:00|000000001|EX site one|2|PM2.5|UG/M3|-1.4|{AGENCY}
            04/28/26|10:00|000000002|EX site two|2|NO2|PPB|5.6|{AGENCY}
            04/28/26|10:00|000000002|EX site two|2|BARPR|MILLIBAR|1013.2|{AGENCY}
            """
        ),
    },
    # A twelve-digit AQSID the table places, a parameter the fact sheet's table does not list
    # (the vocabulary is open, F09), and a site the table does not have: no position.
    "hourly_data_site_without_position": {
        "form": "HourlyData",
        "records": records(
            f"""
            04/28/26|11:00|000000000011|EX site eleven|2|RWS|M/S|3.2|{AGENCY}
            04/28/26|11:00|000000003|EX site three|2|CO|PPM|0.21|{AGENCY}
            """
        ),
    },
    # The real files' form of the HourlyAQObs date (four digits), positions stated in the file,
    # blank fields for what a site does not measure.
    "hourly_aqobs_two_sites": {
        "form": "HourlyAQObs",
        "header": AQOBS_HEADER,
        "rows": [
            aqobs(
                **SITE_ONE,
                ValidDate="04/28/2026",
                ValidTime="10:00",
                OZONE_AQI="29",
                PM25_AQI="12",
                OZONE_Measured="1",
                PM10_Measured="0",
                PM25_Measured="1",
                NO2_Measured="0",
                PM25="2.9",
                PM25_Unit="UG/M3",
                OZONE="31.0",
                OZONE_Unit="PPB",
            ),
            aqobs(
                **SITE_ELEVEN,
                ValidDate="04/28/2026",
                ValidTime="10:00",
                OZONE_AQI="33",
                PM10_AQI="8",
                PM25_AQI="15",
                NO2_AQI="4",
                OZONE_Measured="1",
                PM10_Measured="1",
                PM25_Measured="1",
                NO2_Measured="1",
                PM25="3.6",
                PM25_Unit="UG/M3",
                OZONE="35.0",
                OZONE_Unit="PPB",
                NO2="4.1",
                NO2_Unit="PPB",
                CO="0.2",
                CO_Unit="PPM",
                SO2="-0.4",
                SO2_Unit="PPB",
                PM10="9.0",
                PM10_Unit="UG/M3",
            ),
        ],  # fmt: skip
    },
    # The fact sheet's form of the date (two digits), a site with no stated position (the table
    # places it), an inactive status, and a concentration whose unit field is blank.
    "hourly_aqobs_fact_sheet_date_blank_unit": {
        "form": "HourlyAQObs",
        "header": AQOBS_HEADER,
        "rows": [
            aqobs(
                AQSID="000000002",
                SiteName="EX site two",
                Status="Inactive",
                EPARegion="R0",
                Elevation="",
                GMTOffset="2.0",
                CountryCode="XX",
                StateName="EX",
                ValidDate="04/28/26",
                ValidTime="12:00",
                DataSource=AGENCY,
                NO2_AQI="6",
                OZONE_Measured="0",
                PM10_Measured="0",
                PM25_Measured="0",
                NO2_Measured="1",
                NO2="6.8",
                NO2_Unit="PPB",
                CO="0.3",
            ),
        ],  # fmt: skip
    },
}


def dat_text(twin: dict) -> str:
    if twin["form"] == "HourlyData":
        return "".join("|".join(line) + "\r\n" for line in twin["records"])
    lines = [twin["header"], *twin["rows"]]
    return "".join(",".join(f'"{field}"' for field in line) + "\r\n" for line in lines)


def _hourly_data(text: str) -> str:
    return dat_text({"form": "HourlyData", "records": records(text)})


GOOD = f"04/28/26|10:00|000000001|EX site one|2|OZONE|PPB|31|{AGENCY}"

#: name -> the text of a file the adapter must refuse. malformed/README.md states what is wrong
#: with each and the refusal code it expects.
MALFORMED: dict[str, str] = {
    "two_digit_year_out_of_range": _hourly_data(
        f"13/28/26|10:00|000000001|EX site one|2|OZONE|PPB|31|{AGENCY}"
    ),
    "four_digit_year_in_hourly_data": _hourly_data(
        f"04/28/2026|10:00|000000001|EX site one|2|OZONE|PPB|31|{AGENCY}"
    ),
    "not_on_the_hour": _hourly_data(
        f"04/28/26|10:30|000000001|EX site one|2|OZONE|PPB|31|{AGENCY}"
    ),
    "width_mismatch": _hourly_data("04/28/26|10:00|000000001|EX site one|2|OZONE|PPB|31"),
    "not_a_number": _hourly_data(f"04/28/26|10:00|000000001|EX site one|2|OZONE|PPB|3l|{AGENCY}"),
    "bad_aqsid": _hourly_data(f"04/28/26|10:00|00000001|EX site one|2|OZONE|PPB|31|{AGENCY}"),
    "repeated_record": _hourly_data(GOOD + "\n" + GOOD),
    "cut_inside_a_line": _hourly_data(GOOD)[:-12],
    "unknown_header": dat_text(
        {
            "form": "HourlyAQObs",
            "header": [("Ozone_AQI" if name == "OZONE_AQI" else name) for name in AQOBS_HEADER],
            "rows": [
                aqobs(
                    **SITE_ONE,
                    ValidDate="04/28/2026",
                    ValidTime="10:00",
                    OZONE_AQI="29",
                    OZONE_Measured="1",
                    PM10_Measured="0",
                    PM25_Measured="0",
                    NO2_Measured="0",
                )
            ],
        }
    ),  # fmt: skip
    "number_past_the_double_range": _hourly_data(
        f"04/28/26|10:00|000000001|EX site one|2|OZONE|PPB|{'9' * 400}.0|{AGENCY}"
    ),
    "fact_sheet_measured_spelling": dat_text(
        {
            "form": "HourlyAQObs",
            "header": [
                ("Ozone_Measured" if name == "OZONE_Measured" else name) for name in AQOBS_HEADER
            ],
            "rows": [
                aqobs(
                    **SITE_ONE,
                    ValidDate="04/28/2026",
                    ValidTime="10:00",
                    OZONE_AQI="29",
                    OZONE_Measured="1",
                    PM10_Measured="0",
                    PM25_Measured="0",
                    NO2_Measured="0",
                )
            ],
        }
    ),  # fmt: skip
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
                "standard_ref": "airnow_hourly/spec/airnow_hourly_pin.json",
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
    for name, twin in CASES.items():
        out[FIXTURES / f"{name}.dat"] = dat_text(twin).encode("ascii")
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(twin)
    for name, text in MALFORMED.items():
        out[MALFORMED_DIR / f"{name}.dat"] = text.encode("ascii")
    payloads = sorted(p.name for p in out if p.parent == FIXTURES)
    out[FIXTURES / "PROVENANCE.json"] = provenance("airnow_hourly", payloads, ORIGIN)
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "airnow_hourly/malformed", [f"{name}.dat" for name in MALFORMED], MALFORMED_ORIGIN
    )
    return out


def _generated_here(directory: pathlib.Path) -> set[pathlib.Path]:
    """Files under `directory` (not below it) this script owns: payloads, twins, provenance."""
    if not directory.is_dir():
        return set()
    return {p for p in directory.iterdir() if p.is_file() and p.suffix in (".dat", ".json")}


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
