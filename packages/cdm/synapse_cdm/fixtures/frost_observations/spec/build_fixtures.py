"""Write the SYNTHETIC fixtures of `frost_observations` from the literals in this script.

Every station id is in the SN0000x block CONTRIBUTING.md reserves for Frost station fixtures and
every value is invented; nothing is copied from a Frost response. The shapes follow Frost's
documented `GET /observations/v0.jsonld` response (https://frost.met.no/concepts2.html).

Each valid fixture is a pair: `<name>.jsonld`, the response's octets (compact UTF-8 JSON), and
`<name>.parsed.json`, the same document parsed, which is what the harness's `lossless` column
reads. The station positions live in the adapter's `FIXTURE_STATIONS`, not in any fixture: a
Frost response states none.

    python -I -B fixtures/frost_observations/spec/build_fixtures.py          # write
    python -I -B fixtures/frost_observations/spec/build_fixtures.py --check  # compare only

Edit this script and run it; never edit a fixture by hand.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MALFORMED = ROOT / "malformed"


def header(count: int, created: str = "2026-10-20T07:00:00.000Z") -> dict:
    return {
        "@context": "https://frost.met.no/schema",
        "@type": "ObservationResponse",
        "apiVersion": "v0",
        "license": "https://creativecommons.org/licenses/by/3.0/no/",
        "createdAt": created,
        "queryTime": 0.123,
        "currentItemCount": count,
        "itemsPerPage": count,
        "offset": 0,
        "totalItemCount": count,
        "currentLink": "https://frost.met.no/observations/v0.jsonld?sources=SYNTHETIC",
    }


def level(height: float) -> dict:
    return {"levelType": "height_above_ground", "unit": "m", "value": height}


def obs(
    element,
    value,
    unit,
    *,
    lvl=None,
    offset="PT0H",
    resolution="PT1H",
    series=0,
    perf="C",
    expo="2",
    quality=0,
    **extra,
) -> dict:
    observation = {"elementId": element, "value": value, "unit": unit}
    if lvl is not None:
        observation["level"] = lvl
    observation.update(
        {
            "timeOffset": offset,
            "timeResolution": resolution,
            "timeSeriesId": series,
            "performanceCategory": perf,
            "exposureCategory": expo,
            "qualityCode": quality,
        }
    )
    observation.update(extra)
    return observation


def _no_unit(observation: dict) -> dict:
    del observation["unit"]
    return observation


def response(items: list[dict], **top) -> dict:
    document = header(len(items))
    document.update(top)
    document["data"] = items
    return document


# -- 1: two stations in the table, two hours each, the seven requested elements -------------------

TWO_STATIONS = response(
    [
        {
            "sourceId": "SN00001:0",
            "referenceTime": "2026-10-19T00:00:00.000Z",
            "observations": [
                obs("air_temperature", -3.4, "degC", lvl=level(2)),
                obs("wind_speed", 7.1, "m/s", lvl=level(10)),
                obs("wind_from_direction", 215, "degrees", lvl=level(10)),
                obs("air_pressure_at_sea_level", 1002.7, "hPa"),
                obs("sum(precipitation_amount PT1H)", 0.4, "mm", perf="C", expo="1"),
                obs("relative_humidity", 88, "percent", lvl=level(2)),
            ],
        },
        {
            "sourceId": "SN00001:0",
            "referenceTime": "2026-10-19T01:00:00.000Z",
            "observations": [
                obs("air_temperature", -3.9, "degC", lvl=level(2)),
                obs("wind_speed", 6.4, "m/s", lvl=level(10)),
                obs("sum(precipitation_amount PT1H)", 0, "mm", expo="1"),
            ],
        },
        {
            "sourceId": "SN00002:0",
            "referenceTime": "2026-10-19T00:00:00.000Z",
            "observations": [
                obs("air_temperature", 1.2, "degC", lvl=level(2), perf="A", expo="1"),
                obs("air_pressure_at_sea_level", 998.1, "hPa", perf="A", expo="1"),
            ],
        },
        {
            "sourceId": "SN00002:0",
            "referenceTime": "2026-10-19T01:00:00.000Z",
            "observations": [
                obs("air_temperature", 0.8, "degC", lvl=level(2), perf="A", expo="1"),
            ],
        },
    ]
)

# -- 2: quality codes, no level, snow thickness hourly, unknown keys at three depths --------------

QUALITY_AND_UNKNOWN = response(
    [
        {
            "sourceId": "SN00003:0",
            "referenceTime": "2026-10-19T06:00:00.000Z",
            "syntheticItemNote": "an item key Frost does not document",
            "observations": [
                obs("surface_snow_thickness", 12, "cm", quality=2),
                obs(
                    "air_temperature",
                    -11.6,
                    "degC",
                    lvl=level(2),
                    quality=5,
                    syntheticObservationKey={"nested": True, "count": 3},
                ),
                obs("sum(precipitation_amount PT1H)", 1.3, "mm", quality=7),
            ],
        },
        {
            "sourceId": "SN00003:0",
            "referenceTime": "2026-10-19T07:00:00.000Z",
            # An observation stating none of the three flags, beside one that states only one.
            "observations": [
                {
                    "elementId": "relative_humidity",
                    "value": 73,
                    "unit": "percent",
                    "level": level(2),
                    "timeOffset": "PT0H",
                    "timeResolution": "PT1H",
                    "timeSeriesId": 0,
                },
                {
                    "elementId": "wind_speed",
                    "value": 12.5,
                    "unit": "m/s",
                    "level": level(10),
                    "timeOffset": "PT0H",
                    "timeResolution": "PT10M",
                    "timeSeriesId": 0,
                    "qualityCode": 1,
                },
            ],
        },
        {
            "sourceId": "SN00003:0",
            "referenceTime": "2026-10-19T08:00:00.000Z",
            # No flag anywhere in the item: the contract states quality_flags_basis instead.
            "observations": [
                {
                    "elementId": "air_pressure_at_sea_level",
                    "value": 1011.0,
                    "unit": "hPa",
                    "timeOffset": "PT0H",
                    "timeResolution": "PT1H",
                    "timeSeriesId": 0,
                },
            ],
        },
    ],
    syntheticTopLevelKey={"origin": "an unknown header block", "version": 2},
)

# -- 3: a station the table does not place, parallel sensors, two series of one element ----------

STATION_MISSING_AND_SENSORS = response(
    [
        {
            "sourceId": "SN00009:0",
            "referenceTime": "2026-10-19T12:00:00.000Z",
            "observations": [
                obs("air_temperature", 4.5, "degC", lvl=level(2), perf="D", expo="4"),
            ],
        },
        {
            "sourceId": "SN00001:0",
            "referenceTime": "2026-10-19T00:00:00.000Z",
            # One element in two series (two time offsets), both sub-daily: kept apart by the
            # reading's namespace.
            "observations": [
                obs("air_temperature", -2.0, "degC", lvl=level(2)),
                obs("air_temperature", -2.25, "degC", lvl=level(2), offset="PT6H", series=1),
                obs("air_temperature", -2.5, "degC", lvl=level(0.5)),
            ],
        },
        {
            "sourceId": "SN00001:1",
            "referenceTime": "2026-10-19T00:00:00.000Z",
            "observations": [
                obs("air_temperature", -2.1, "degC", lvl=level(2), perf="B"),
            ],
        },
        {
            # A sourceId without the sensor suffix, which Frost documents as SN<n>:0's alias;
            # read as stated, never rewritten.
            "sourceId": "SN00002",
            "referenceTime": "2026-10-19T12:30:00.000Z",
            # timeResolution of one day at a referenceTime that is not midnight: Frost's note
            # makes the referenceTime the observation time.
            "observations": [
                obs("surface_snow_thickness", 0, "cm", resolution="P1D", offset="PT6H"),
            ],
        },
    ]
)


# -- 4: a midnight item mixing sub-daily and daily (P1D) observations -----------------------------

MIDNIGHT_MIXED_DAILY = response(
    [
        {
            "sourceId": "SN00001:0",
            "referenceTime": "2026-10-19T00:00:00.000Z",
            "observations": [
                obs("air_temperature", -6.3, "degC", lvl=level(2)),
                obs("wind_speed", 4.2, "m/s", lvl=level(10), resolution="PT10M"),
                obs("air_pressure_at_sea_level", 1009.9, "hPa", resolution="PT1M"),
                obs("sum(precipitation_amount PT3H)", 0.6, "mm", resolution="PT3H"),
                # Case 2.2, timeOffset PT0H: the calendar date.
                obs("surface_snow_thickness", 21, "cm", resolution="P1D", quality=2),
                # Case 2.2, timeOffset PT6H: the 24 h ending at 06:00 on the date.
                obs("sum(precipitation_amount P1D)", 3.1, "mm", resolution="P1D", offset="PT6H"),
                # Longer than P1D at midnight: unresolved, set aside on the station Entity.
                obs("mean(air_temperature P1M)", -4.0, "degC", lvl=level(2), resolution="P1M"),
            ],
        },
        {
            # A station that reports only a daily value at midnight: a daily Event alone.
            "sourceId": "SN00003:0",
            "referenceTime": "2026-10-19T00:00:00.000Z",
            "observations": [
                obs("surface_snow_thickness", 48, "cm", resolution="P1D"),
            ],
        },
        {
            "sourceId": "SN00003:0",
            "referenceTime": "2026-10-19T01:00:00.000Z",
            "observations": [
                obs("air_temperature", -14.2, "degC", lvl=level(2)),
            ],
        },
    ]
)

# -- 5: observations without a unit, with and without an element-table row ----------------------

WITHOUT_UNIT = response(
    [
        {
            "sourceId": "SN00002:0",
            "referenceTime": "2026-10-19T03:00:00.000Z",
            "observations": [
                _no_unit(obs("wind_speed", 9.4, "m/s", lvl=level(47), resolution="PT10M")),
                _no_unit(
                    obs("wind_from_direction", 284, "degrees", lvl=level(47), resolution="PT10M")
                ),
                # Not in the fixture element table: carried as unit_unknown.
                _no_unit(obs("synthetic_element_x", 17.5, "x", resolution="PT10M")),
                obs("air_temperature", -0.7, "degC", lvl=level(2)),
            ],
        },
    ]
)

FIXTURES = {
    "two_stations_hourly": TWO_STATIONS,
    "quality_codes_no_level_unknown_keys": QUALITY_AND_UNKNOWN,
    "station_missing_parallel_sensors": STATION_MISSING_AND_SENSORS,
    "midnight_mixed_daily": MIDNIGHT_MIXED_DAILY,
    "observation_without_unit": WITHOUT_UNIT,
}

# -- malformed: every one must be REFUSED by the adapter ------------------------------------------


def _with(document: dict, mutate) -> dict:
    copied = copy.deepcopy(document)
    mutate(copied)
    return copied


def _resolution_not_duration(d):
    d["data"][0]["observations"][0]["timeResolution"] = "hourly"


def _blank_unit(d):
    d["data"][0]["observations"][0]["unit"] = ""


def _bad_source(d):
    d["data"][0]["sourceId"] = "XX00001:0"


def _naive_time(d):
    d["data"][0]["referenceTime"] = "2026-10-19T00:00:00"


def _repeat(d):
    d["data"].append(copy.deepcopy(d["data"][0]))


def _wrong_type(d):
    d["@type"] = "SourceResponse"


def _empty(d):
    d["data"] = []


def _value_text(d):
    d["data"][0]["observations"][0]["value"] = "-3.4"


def _level_without_unit(d):
    del d["data"][0]["observations"][0]["level"]["unit"]


def _bool_quality(d):
    d["data"][0]["observations"][0]["qualityCode"] = True


MALFORMED_FIXTURES = {
    "time_resolution_not_a_duration.json": _with(TWO_STATIONS, _resolution_not_duration),
    "observation_with_blank_unit.json": _with(TWO_STATIONS, _blank_unit),
    "source_id_not_a_station.json": _with(TWO_STATIONS, _bad_source),
    "reference_time_without_zone.json": _with(TWO_STATIONS, _naive_time),
    "repeated_item.json": _with(TWO_STATIONS, _repeat),
    "not_an_observation_response.json": _with(TWO_STATIONS, _wrong_type),
    "no_data_item.json": _with(TWO_STATIONS, _empty),
    "value_as_text.json": _with(TWO_STATIONS, _value_text),
    "level_value_without_unit.json": _with(TWO_STATIONS, _level_without_unit),
    "quality_code_boolean.json": _with(TWO_STATIONS, _bool_quality),
}

#: Octet fixtures under malformed/: the loader hands these over as bytes.
MALFORMED_OCTETS = {
    # Two equal keys in one object: json.loads would silently keep the second.
    "duplicate_key.jsonld": (
        b'{"@type": "ObservationResponse", "apiVersion": "v0", "apiVersion": "v0", "data": []}\n'
    ),
    "cut_short.jsonld": json.dumps(TWO_STATIONS).encode("utf-8")[:-40],
}


PIN = "frost_observations/spec/frost_observations_pin.json"
ORIGIN = (
    "Synthetic MET Norway Frost ObservationResponse written for the frost_observations adapter by "
    "fixtures/frost_observations/spec/build_fixtures.py from literals in that script, after the "
    "response shape Frost documents at https://frost.met.no/concepts2.html; stations are in the "
    "synthetic SN0000x block, every value is invented, and nothing is recorded data."
)


def render(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def octets(document: dict) -> bytes:
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def provenance(directory: str, names: list[str]) -> bytes:
    entries = [
        {
            "classification": "PUBLIC",
            "file": name,
            "operational_data": False,
            "origin": ORIGIN,
            "personal_data": False,
            "standard_ref": PIN,
            "synthetic": True,
        }
        for name in sorted(names)
    ]
    record = {
        "schema_id": "synapse.fixture-provenance/v1",
        "directory": directory,
        "fixtures": entries,
    }
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def planned() -> dict[pathlib.Path, bytes]:
    files: dict[pathlib.Path, bytes] = {}
    for name, doc in FIXTURES.items():
        files[ROOT / f"{name}.jsonld"] = octets(doc)
        files[ROOT / f"{name}.parsed.json"] = render(doc).encode("utf-8")
    files.update(
        {MALFORMED / name: render(doc).encode("utf-8") for name, doc in MALFORMED_FIXTURES.items()}
    )
    files.update({MALFORMED / name: data for name, data in MALFORMED_OCTETS.items()})
    files[ROOT / "PROVENANCE.json"] = provenance(
        "frost_observations", [p.name for p in files if p.parent == ROOT]
    )
    files[MALFORMED / "PROVENANCE.json"] = provenance(
        "frost_observations/malformed", [p.name for p in files if p.parent == MALFORMED]
    )
    return files


def main(argv: list[str]) -> int:
    files = planned()
    if "--check" in argv:
        stale = [p for p, b in files.items() if not p.exists() or p.read_bytes() != b]
        print("CURRENT" if not stale else "STALE: " + ", ".join(p.name for p in stale))
        return 0 if not stale else 1
    MALFORMED.mkdir(parents=True, exist_ok=True)
    for path, data in files.items():
        path.write_bytes(data)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
