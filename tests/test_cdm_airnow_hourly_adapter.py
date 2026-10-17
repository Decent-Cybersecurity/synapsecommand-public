"""`airnow_hourly`, #28 in the ordinal table: one AirNow hourly file -> Events and site Entities.

Every expectation here is a literal written from the fixture builder's own literals
(`fixtures/airnow_hourly/spec/build_fixtures.py`, which shares no code with the adapter) and from
the two AirNow fact sheets' layouts (research-station-text F08/F09), never read back from the
adapter: an instant is the line's GMT hour START and its END one hour later, written out (the
hour-start rule), a value is the field's decimal read by hand, an identifier is the uuid5 of the
documented namespace and name built here, and every refusal is its code and its whole text.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/airnow_hourly/` and
runs the packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

import datetime as dt
import json
import pathlib
import pickle
import uuid

import pytest

import synapse_cdm
from synapse_cdm import lossless, manifest, times
from synapse_cdm.adapter import InputTooDeep, discover
from synapse_cdm.adapters import airnow_hourly
from synapse_cdm.adapters.airnow_hourly import AirnowHourlyAdapter, AirnowRefused
from synapse_cdm.manifest import LimitKind, UnknownFields
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "airnow_hourly"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"
TESTS = "tests/test_cdm_airnow_hourly_adapter.py"

CASES = sorted(p.stem for p in FIXTURES.glob("*.dat"))

AQOBS_HEADER = (
    "AQSID SiteName Status EPARegion Latitude Longitude Elevation GMTOffset CountryCode "
    "StateName ValidDate ValidTime DataSource ReportingArea_PipeDelimited OZONE_AQI PM10_AQI "
    "PM25_AQI NO2_AQI OZONE_Measured PM10_Measured PM25_Measured NO2_Measured PM25 PM25_Unit "
    "OZONE OZONE_Unit NO2 NO2_Unit CO CO_Unit SO2 SO2_Unit PM10 PM10_Unit"
).split()
FORMAT = "EPA AirNow hourly observation files (HourlyData, HourlyAQObs)"
T_HOUR = (
    "the valid date and time are read as the GMT start of a one-hour period; observed_at is its "
    "end, one hour later"
)
T_TWO_DIGIT_YEAR = "a two-digit year is read as 20YY: AirNow's hourly files begin in 2019"
T_NUMBER = "each value's decimal text is read as a binary floating-point number"
QUALITY_BASIS = (
    "AirNow's hourly files carry no per-value quality flag: only valid data are reported, a "
    "missing value is a line or a field that is not there, and every value is preliminary (the "
    "Hourly Data and Hourly AQ Obs fact sheets; research-station-text F08, F09). HourlyAQObs's "
    "*_Measured fields say whether a site measures a pollutant and stay in the residual."
)
AQI_NS = (
    "the Hourly AQ Obs fact sheet: the field is the NowCast Air Quality Index (NO2's the hourly "
    "AQI), an index of 0 to 500 with no other unit"
)
UNIT_UNKNOWN = (
    "the line states the concentration and leaves its unit field blank, so the value's unit is "
    "not stated and the number stays in the Event's residual"
)
TABLE_BASIS = (
    "station table airnow-hourly-fixture-sites: synthetic site positions written for the "
    "packaged fixtures on 2026-10-15 (fixtures/airnow_hourly/README.md); no real site is named"
)
STATED_BASIS = "the HourlyAQObs line's Latitude and Longitude, decimal degrees"
AGENCY = "EX synthetic agency"


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _adapter(**kwargs) -> AirnowHourlyAdapter:
    return AirnowHourlyAdapter(times.frozen_clock(), **kwargs)


def _dump(objects) -> list[dict]:
    return [o.model_dump(mode="json") for o in objects]


def _translate(name: str, adapter=None) -> list[dict]:
    adapter = adapter or AirnowHourlyAdapter.fixture_instance(times.frozen_clock())
    return _dump(adapter.to_cdm((FIXTURES / f"{name}.dat").read_bytes()))


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _refusal(payload, **kwargs) -> AirnowRefused:
    with pytest.raises(AirnowRefused) as raised:
        _adapter(**kwargs).to_cdm(payload)
    return raised.value


def _events(objects: list[dict]) -> list[dict]:
    return [o for o in objects if o["object_kind"] == "event"]


def _entities(objects: list[dict]) -> list[dict]:
    return [o for o in objects if o["object_kind"] == "entity"]


def _short(reading: dict) -> tuple:
    if reading["measurement"] is not None:
        m = reading["measurement"]
        return (reading["name"], m["value"], m["unit"])
    return (reading["name"], None, reading["absence"]["cause"])


def _aqobs(**fields: str) -> list[str]:
    return [fields.get(name, "") for name in AQOBS_HEADER]


def _aqobs_file(*rows: list[str], header=AQOBS_HEADER) -> bytes:
    lines = [header, *rows]
    return "".join(",".join(f'"{f}"' for f in line) + "\r\n" for line in lines).encode()


SITE = dict(
    AQSID="000000001", Status="Active", Latitude="56.95", Longitude="24.1", ValidDate="04/28/2026",
    ValidTime="10:00", OZONE_Measured="1", PM10_Measured="0", PM25_Measured="0",
    NO2_Measured="0", OZONE_AQI="29",
)  # fmt: skip


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["airnow_hourly"]
    assert cls is AirnowHourlyAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "airnow_hourly",
        "1.0.0",
        "ingest",
        "AirNow",
    )
    assert airnow_hourly.__doc__.splitlines()[0] == (
        "`airnow_hourly`, #28 in the ordinal table: one EPA AirNow hourly observation file -> CDM, "
        "ingest only."
    )
    meta = cls.metadata
    assert (
        meta.format.name,
        meta.format.version,
        meta.binding.value,
        meta.license_class.value,
        meta.maturity.level.value,
        meta.claim_status.value,
        meta.residual.value,
    ) == (
        FORMAT,
        "AirNow Hourly Data File fact sheet (last updated August 2025) and Hourly AQ Obs File "
        "fact sheet (updated March 2023)",
        "standard-encoding",
        "PUBLIC_GOVERNMENT",
        "L3",
        "VERIFIED",
        "structured",
    )
    limits = meta.capabilities.limits
    assert (
        limits.max_input_bytes,
        limits.max_depth,
        limits.max_objects,
        limits.max_decompressed_bytes,
        limits.max_parse_seconds,
    ) == (8388608, 64, None, None, None)
    assert sorted(limits.absent_because) == [
        "max_decompressed_bytes",
        "max_objects",
        "max_parse_seconds",
    ]
    assert sorted(limits.declared_because) == ["max_depth", "max_input_bytes"]
    for field, basis in limits.declared_because.items():
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP, field
        assert basis.source.endswith(
            "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
        ), field
        module, _, test = basis.test.partition("::")
        if module == TESTS:
            assert callable(globals().get(test)), (field, test)
    source = limits.declared_because["max_input_bytes"].source
    assert "one HourlyData file of 7878 lines for one hour" in source
    assert "research-station-text F08" in source and "DECISIONS U-07" in source
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    assert [lim.id for lim in meta.limitations] == [
        "hourly-files-only",
        "site-position-from-the-caller",
        "hour-start-stamps",
        "aqi-unit",
        "no-empty-lines",
        "no-quality-flags",
        "evidence-availability",
    ]
    assert airnow_hourly.HOURLY_AQOBS_FIELDS == tuple(AQOBS_HEADER)
    assert {
        key: [(m.to, m.rule, m.kind) for m in (v if isinstance(v, tuple) else (v,))]
        for key, v in AirnowHourlyAdapter.MAPPINGS.items()
    } == {
        "records[*][2]": [
            ("#[*]:residual.data.record[2]", "identity", "residual"),
            ("#[*]:payload.observation.station_id", "identity", "field"),
        ],
        "records[*][7]": [
            ("#[*]:residual.data.record[7]", "identity", "residual"),
            ("#[*]:payload.observation.readings[0].measurement.value", "numeric_text", "field"),
        ],
        "records[*]": [("#[*]:residual.data.record", "identity", "residual")],
        "rows[*][0]": [
            ("#[*]:residual.data.row[0]", "identity", "residual"),
            ("#[*]:payload.observation.station_id", "identity", "field"),
        ],
        "rows[*]": [("#[*]:residual.data.row", "identity", "residual")],
    }


@pytest.mark.parametrize("name", CASES)
def test_every_twin_leaf_is_mapped_or_parked_on_its_own_event(name):
    twin = _twin(name)
    objects = _dump(AirnowHourlyAdapter.fixture_instance(times.frozen_clock()).to_cdm(twin))
    book = lossless.ledger(
        twin,
        objects,
        AirnowHourlyAdapter.MAPPINGS,
        unsupported=manifest.unsupported_paths(AirnowHourlyAdapter.metadata.limitations),
    )
    assert book.lost == ()
    if twin["form"] == "HourlyData":
        lines = len(twin["records"])
        # The AQSID and the value of every line are MAPPED; `form` and the other seven fields
        # are parked on the line's own Event.
        expected = {"MAPPED": 2 * lines, "RESIDUAL": 1 + 7 * lines}
    else:
        lines = len(twin["rows"])
        expected = {"MAPPED": lines, "RESIDUAL": 1 + 34 + 33 * lines}
    assert book.counts == {**expected, "DECLARED_LIMITATION": 0, "LOST": 0}


# ================================================================== the fixture set


HEADER_REFUSAL = "unknown-header: the HourlyAQObs header is not the 34 names the files write"
OUT_OF_RANGE = "lies outside what a binary double holds"

MALFORMED_REFUSALS = {
    "two_digit_year_out_of_range": (
        "bad-date",
        "bad-date: record 0: the valid date and time name no hour",
    ),
    "four_digit_year_in_hourly_data": (
        "bad-date",
        "bad-date: record 0: the valid date is not mm/dd/yy",
    ),
    "not_on_the_hour": ("not-an-hour", "not-an-hour: record 0: the valid time is not on the hour"),
    "width_mismatch": ("width-mismatch", "width-mismatch: record 0 does not hold the nine fields"),
    "not_a_number": ("not-a-number", "not-a-number: record 0: the value is not a decimal number"),
    "bad_aqsid": (
        "bad-aqsid",
        "bad-aqsid: record 0: the AQSID is not nine or twelve letters and digits",
    ),
    "repeated_record": (
        "repeated-record",
        "repeated-record: record 1 states the site, parameter and hour of record 0",
    ),
    "cut_inside_a_line": (
        "unterminated-line",
        "unterminated-line: the last line has no line end: the file is cut short or is not whole "
        "lines",
    ),
    "unknown_header": ("unknown-header", HEADER_REFUSAL),
    "fact_sheet_measured_spelling": ("unknown-header", HEADER_REFUSAL),
    "number_past_the_double_range": (
        "number-out-of-range",
        f"number-out-of-range: record 0: the value {OUT_OF_RANGE}",
    ),
}


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert CASES == [
        "hourly_aqobs_fact_sheet_date_blank_unit",
        "hourly_aqobs_two_sites",
        "hourly_data_site_without_position",
        "hourly_data_two_sites",
    ]
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert sorted(p.name for p in MALFORMED.iterdir() if p.suffix == ".dat") == sorted(
        f"{name}.dat" for name in MALFORMED_REFUSALS
    )
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(
        f"{name}{suffix}" for name in CASES for suffix in (".cdm.json", ".parsed.cdm.json")
    )


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_every_site_and_position_follows_the_identifier_convention(name):
    objects = _translate(name)
    for event in _events(objects):
        station = event["payload"]["observation"]["station_id"]
        form = "air-quality-9" if len(station) == 9 else "air-quality-12"
        assert support.station_id_problems(station, form) == []
    assert support.positions_outside_the_rectangle(objects) == []
    for row in _twin(name).get("rows", []):
        if row[4]:
            assert support.positions_outside_the_rectangle(
                {"lat": float(row[4]), "lon": float(row[5])}
            ) == []  # fmt: skip


@pytest.mark.parametrize("name", CASES)
def test_the_parse_of_each_file_is_the_twin_its_builder_wrote(name):
    assert airnow_hourly.parse_file((FIXTURES / f"{name}.dat").read_bytes()) == _twin(name)


@pytest.mark.parametrize("name", CASES)
def test_the_octets_and_the_twin_translate_to_one_result(name):
    adapter = AirnowHourlyAdapter.fixture_instance(times.frozen_clock())
    assert _dump(adapter.to_cdm(_twin(name))) == _translate(name)


@pytest.mark.parametrize("name", CASES)
def test_the_two_goldens_of_a_pair_are_one_translation(name):
    payload = json.loads((GOLDEN / f"{name}.cdm.json").read_text())
    twin = json.loads((GOLDEN / f"{name}.parsed.cdm.json").read_text())
    assert payload == twin == _translate(name)


@pytest.mark.parametrize("name", sorted(MALFORMED_REFUSALS))
def test_each_malformed_file_is_refused_with_its_code_and_its_whole_text(name):
    code, text = MALFORMED_REFUSALS[name]
    refusal = _refusal((MALFORMED / f"{name}.dat").read_bytes())
    assert (refusal.code, str(refusal)) == (code, text)


# ================================================================== the files, by hand


def test_a_stamp_is_the_start_of_its_hour_and_observed_at_its_end():
    """The fact sheets: "a data value with a time of 17:00 represents a sample measured from 17:00
    to 17:59 GMT". `04/28/26|10:00` is therefore the hour 2026-04-28T10:00Z to 11:00Z: the
    validity runs over it, observed_at is its END (DJ-04), and the record's own stamp, its start,
    stays in SourceRef.observed_at."""
    objects = _translate("hourly_data_two_sites")
    assert [o["object_kind"] for o in objects] == ["event"] * 4 + ["entity"] * 2
    one, two = _uuid("entity", "AirNow", "000000001"), _uuid("entity", "AirNow", "000000002")
    start, end = "2026-04-28T10:00:00.000Z", "2026-04-28T11:00:00.000Z"
    # Line 1: 04/28/26|10:00|000000001|EX site one|2|PM2.5|UG/M3|-1.4|EX synthetic agency
    assert objects[1] == {
        "event_id": _uuid("event", "AirNow", f"000000001/PM2.5/{start}"),
        "event_type": "ENVIRONMENTAL_OBSERVATION",
        "geometry": {"coordinates": [24.1, 56.95], "type": "Point"},
        "integrity": None,
        "object_kind": "event",
        "observed_at": end,
        "oes": None,
        "payload": {
            "observation": {
                "contract": "point-observation/1",
                "locator": {
                    "frame_sha256": None,
                    "granule_id": None,
                    "header_lines": 0,
                    "kind": "table",
                    "row": 1,
                },
                "product_class": "observation",
                "product_version": None,
                "quality_flags": [],
                "quality_flags_basis": QUALITY_BASIS,
                "readings": [
                    {
                        "absence": None,
                        "datum": None,
                        "level": None,
                        "measurement": {
                            "unit": "UG/M3",
                            "unit_namespace": "AirNow HourlyData reporting units field",
                            "value": -1.4,
                        },
                        "name": "PM2.5",
                        "namespace": "AirNow HourlyData parameter name",
                    }
                ],
                "station_id": "000000001",
                "station_namespace": "EPA AQS site identifier (AQSID)",
                "time": {
                    "forecast_offset": None,
                    "reference_time": None,
                    "reference_time_significance": None,
                    "source_time_system": {
                        "basis": "the AirNow fact sheets: the valid date and valid time are GMT "
                        "and mark the beginning of a one-hour measurement period "
                        "(research-station-text F08)",
                        "name": "GMT",
                        "stated_by": "source",
                    },
                    "statistical_process": None,
                },
            }
        },
        "quality": None,
        "received_at": FROZEN,
        "related_entities": [one],
        "residual": {
            "data": {
                "form": "HourlyData",
                "record": [
                    "04/28/26",
                    "10:00",
                    "000000001",
                    "EX site one",
                    "2",
                    "PM2.5",
                    "UG/M3",
                    "-1.4",
                    AGENCY,
                ],
            },
            "namespace": FORMAT,
        },  # fmt: skip
        "schema_version": "3.2.0",
        "severity": "INFO",
        "source": {
            "adapter": "airnow_hourly",
            "adapter_version": "1.0.0",
            "format_name": FORMAT,
            "format_version": "AirNow Hourly Data File fact sheet (last updated August 2025) and "
            "Hourly AQ Obs File fact sheet (updated March 2023)",
            "observed_at": start,
            "original_id": None,
            "record_index": 1,
            "source_hash": None,
            "synthetic": True,
            "system": "AirNow",
            "transformations": [T_HOUR, T_TWO_DIGIT_YEAR, T_NUMBER],
        },
        "source_ids": [{"external_id": f"000000001/PM2.5/{start}", "system": "AirNow"}],
        "status": None,
        "validity": {
            "effective": {"end": end, "start": start},
            "observed_at": None,
            "valid_from": None,
            "valid_to": None,
        },
    }
    # The negative raw value is a value, never clamped (F09); one Event a line, in file order.
    assert [
        (e["payload"]["observation"]["station_id"], _short(e["payload"]["observation"]["readings"][0]))
        for e in _events(objects)
    ] == [
        ("000000001", ("OZONE", 31.0, "PPB")),
        ("000000001", ("PM2.5", -1.4, "UG/M3")),
        ("000000002", ("NO2", 5.6, "PPB")),
        ("000000002", ("BARPR", 1013.2, "MILLIBAR")),
    ]  # fmt: skip
    # One Entity a site, in the order sites first appear, placed by the fixture table, valid
    # from the END of the earliest hour a line states for it.
    assert [
        (e["entity_id"], e["position"]["lat"], e["position"]["lon"], e["valid_from"],
         e["attributes"], e["status"], e["source"]["observed_at"], e["source"]["transformations"])
        for e in _entities(objects)
    ] == [
        (one, 56.95, 24.1, end, {"position_basis": TABLE_BASIS, "site_class": "air_quality_site",
         "valid_from_basis": "the end of the earliest hour a line states for the site"}, None,
         end, [T_HOUR]),
        (two, 57.4, 21.6, end, {"position_basis": TABLE_BASIS, "site_class": "air_quality_site",
         "valid_from_basis": "the end of the earliest hour a line states for the site"}, None,
         end, [T_HOUR]),
    ]  # fmt: skip


def test_each_site_s_residual_is_its_fields_as_the_first_line_naming_it_states_them():
    data = _entities(_translate("hourly_data_two_sites"))
    assert [e["residual"] for e in data] == [
        {
            "data": {
                "first_record": 0,
                "site": {"AQSID": "000000001", "GMT offset": "2", "data source": AGENCY,
                         "sitename": "EX site one"},
            },
            "namespace": FORMAT,
        },
        {
            "data": {
                "first_record": 2,
                "site": {"AQSID": "000000002", "GMT offset": "2", "data source": AGENCY,
                         "sitename": "EX site two"},
            },
            "namespace": FORMAT,
        },
    ]  # fmt: skip
    aqobs = _entities(_translate("hourly_aqobs_fact_sheet_date_blank_unit"))
    assert aqobs[0]["residual"]["data"] == {
        "first_record": 0,
        "site": {
            "AQSID": "000000002", "CountryCode": "XX", "DataSource": AGENCY, "EPARegion": "R0",
            "Elevation": "", "GMTOffset": "2.0", "Latitude": "", "Longitude": "",
            "ReportingArea_PipeDelimited": "", "SiteName": "EX site two", "StateName": "EX",
            "Status": "Inactive",
        },
    }  # fmt: skip


def test_a_site_the_table_does_not_place_has_no_position_and_a_twelve_digit_id_is_read():
    objects = _translate("hourly_data_site_without_position")
    events, entities = _events(objects), _entities(objects)
    assert [(e["observed_at"], e["validity"]["effective"]["start"]) for e in events] == [
        ("2026-04-28T12:00:00.000Z", "2026-04-28T11:00:00.000Z"),
        ("2026-04-28T12:00:00.000Z", "2026-04-28T11:00:00.000Z"),
    ]
    assert [_short(e["payload"]["observation"]["readings"][0]) for e in events] == [
        ("RWS", 3.2, "M/S"),
        ("CO", 0.21, "PPM"),
    ]
    assert [(e["source_ids"][0]["external_id"], e["position"]) for e in entities] == [
        ("000000000011", {"accuracy_m": None, "alt_m": None, "lat": 56.5, "lon": 21.0,
                          "position_source": "MANUAL", "vertical": None}),
        ("000000003", None),
    ]  # fmt: skip
    assert entities[1]["attributes"]["position_basis"] == (
        "no position: the payload states none and the station table has no row for this station"
    )
    assert events[1]["geometry"] is None


def test_a_hourlyaqobs_line_is_one_event_of_its_aqis_and_concentrations():
    objects = _translate("hourly_aqobs_two_sites")
    events, entities = _events(objects), _entities(objects)
    readings = [[_short(r) for r in e["payload"]["observation"]["readings"]] for e in events]
    # Blank fields state nothing; AQIs first in the file's order, then the concentrations.
    assert readings == [
        [("OZONE_AQI", 29.0, "AQI"), ("PM25_AQI", 12.0, "AQI"), ("PM25", 2.9, "UG/M3"),
         ("OZONE", 31.0, "PPB")],
        [("OZONE_AQI", 33.0, "AQI"), ("PM10_AQI", 8.0, "AQI"), ("PM25_AQI", 15.0, "AQI"),
         ("NO2_AQI", 4.0, "AQI"), ("PM25", 3.6, "UG/M3"), ("OZONE", 35.0, "PPB"),
         ("NO2", 4.1, "PPB"), ("CO", 0.2, "PPM"), ("SO2", -0.4, "PPB"), ("PM10", 9.0, "UG/M3")],
    ]  # fmt: skip
    first = events[0]["payload"]["observation"]["readings"]
    assert first[0]["measurement"]["unit_namespace"] == AQI_NS
    assert first[2]["measurement"]["unit_namespace"] == "AirNow HourlyAQObs PM25_Unit field"
    assert {r["namespace"] for r in first} == {"AirNow HourlyAQObs field"}
    # The four-digit date is read as written; no two-digit-year transformation is claimed.
    assert [(e["observed_at"], e["source"]["transformations"]) for e in events] == [
        ("2026-04-28T11:00:00.000Z", [T_HOUR, T_NUMBER]),
        ("2026-04-28T11:00:00.000Z", [T_HOUR, T_NUMBER]),
    ]
    assert [e["payload"]["observation"]["locator"]["header_lines"] for e in events] == [1, 1]
    assert events[1]["source_ids"] == [
        {"external_id": "000000000011/2026-04-28T10:00:00.000Z", "system": "AirNow"}
    ]
    # The line's own position is stated, with its basis; the status is the line's, namespaced.
    assert [
        (e["position"]["lat"], e["position"]["lon"], e["attributes"]["position_basis"], e["status"])
        for e in entities
    ] == [
        (56.95, 24.1, STATED_BASIS, {"attributes": {}, "namespace": "AirNow HourlyAQObs Status",
                                     "since": None, "state": "Active"}),
        (56.5, 21.0, STATED_BASIS, {"attributes": {}, "namespace": "AirNow HourlyAQObs Status",
                                    "since": None, "state": "Active"}),
    ]  # fmt: skip
    assert events[0]["residual"]["data"]["header"] == AQOBS_HEADER
    assert events[0]["residual"]["data"]["row"][13] == "EX area one|EX area two"


def test_a_blank_unit_is_an_absence_and_a_line_without_a_position_takes_the_table_s():
    objects = _translate("hourly_aqobs_fact_sheet_date_blank_unit")
    event, entity = objects
    assert event["payload"]["observation"]["readings"] == [
        {
            "absence": None,
            "datum": None,
            "level": None,
            "measurement": {"unit": "AQI", "unit_namespace": AQI_NS, "value": 6.0},
            "name": "NO2_AQI",
            "namespace": "AirNow HourlyAQObs field",
        },
        {
            "absence": None,
            "datum": None,
            "level": None,
            "measurement": {
                "unit": "PPB",
                "unit_namespace": "AirNow HourlyAQObs NO2_Unit field",
                "value": 6.8,
            },
            "name": "NO2",
            "namespace": "AirNow HourlyAQObs field",
        },
        {
            "absence": {"cause": "unit_unknown", "mechanism": UNIT_UNKNOWN, "sentinel": None},
            "datum": None,
            "level": None,
            "measurement": None,
            "name": "CO",
            "namespace": "AirNow HourlyAQObs field",
        },
    ]
    # The CO concentration whose unit is blank stays in the residual, as written.
    assert event["residual"]["data"]["row"][28:30] == ["0.3", ""]
    # The fact sheet's two-digit date: 04/28/26 12:00 is 2026-04-28T12:00Z to 13:00Z.
    assert (event["observed_at"], event["validity"]["effective"]) == (
        "2026-04-28T13:00:00.000Z",
        {"end": "2026-04-28T13:00:00.000Z", "start": "2026-04-28T12:00:00.000Z"},
    )
    assert event["source"]["transformations"] == [T_HOUR, T_TWO_DIGIT_YEAR, T_NUMBER]
    assert (entity["position"]["lat"], entity["position"]["lon"]) == (57.4, 21.6)
    assert entity["attributes"]["position_basis"] == TABLE_BASIS
    assert entity["status"]["state"] == "Inactive"


def test_without_a_site_table_hourlydata_states_no_position():
    objects = _dump(_adapter().to_cdm((FIXTURES / "hourly_data_two_sites.dat").read_bytes()))
    assert [e["position"] for e in _entities(objects)] == [None, None]
    assert {e["attributes"]["position_basis"] for e in _entities(objects)} == {
        "no position: the payload states none and no station table was supplied"
    }


def test_an_aqsid_of_letters_and_digits_is_read_and_lf_reads_as_crlf():
    """The fact sheets call the AQSID numeric, and their own sample records state one with
    letters; nine or twelve upper-case letters and digits are read."""
    line = f"04/28/26|10:00|EX0000001|EX site|2|OZONE|PPB|31|{AGENCY}"
    lf = _dump(_adapter().to_cdm((line + "\n").encode()))
    crlf = _dump(_adapter().to_cdm((line + "\r\n").encode()))
    assert lf == crlf
    assert lf[0]["payload"]["observation"]["station_id"] == "EX0000001"


def test_the_injected_digests_reach_every_stamp_and_every_locator():
    digest, frame = "e" * 64, "f" * 64
    adapter = _adapter(source_hash={"algorithm": "sha256", "value": digest}, frame_sha256=frame)
    objects = _dump(adapter.to_cdm((FIXTURES / "hourly_data_two_sites.dat").read_bytes()))
    assert [o["source"]["source_hash"] for o in objects] == [
        {"algorithm": "sha256", "value": digest}
    ] * 6
    assert [e["payload"]["observation"]["locator"]["frame_sha256"] for e in _events(objects)] == [
        frame
    ] * 4
    for bad in (
        {"source_hash": {"algorithm": "sha256", "value": digest[:-1]}},
        {"frame_sha256": 7},
        {"site_table": [("000000001", 56.0, 21.0)]},
    ):
        with pytest.raises(ValueError):
            _adapter(**bad)


def test_the_receipt_clock_reaches_received_at_and_nothing_else():
    later = AirnowHourlyAdapter.fixture_instance(
        times.frozen_clock(dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc))
    )
    for name in CASES:
        for x, y in zip(_translate(name), _translate(name, later)):
            if x["object_kind"] == "event":
                assert (x["received_at"], y["received_at"]) == (FROZEN, "2026-05-01T00:00:00.000Z")
                x, y = {**x, "received_at": None}, {**y, "received_at": None}
            assert x == y


# ================================================================== the refusals


def _hd(*lines: str) -> bytes:
    return "".join(line + "\r\n" for line in lines).encode()


GOOD = f"04/28/26|10:00|000000001|EX site one|2|OZONE|PPB|31|{AGENCY}"

REFUSALS = [
    ("a lower-case AQSID", _hd(GOOD.replace("000000001", "ex0000001")), "bad-aqsid: record 0: the AQSID is not nine or twelve letters and digits"),
    ("a ten-digit AQSID", _hd(GOOD.replace("000000001", "0000000001")), "bad-aqsid: record 0: the AQSID is not nine or twelve letters and digits"),
    ("a one-digit month", _hd(GOOD.replace("04/28/26", "4/28/26")), "bad-date: record 0: the valid date is not mm/dd/yy"),
    ("30 February", _hd(GOOD.replace("04/28/26", "02/30/26")), "bad-date: record 0: the valid date and time name no hour"),
    ("hour 24", _hd(GOOD.replace("10:00", "24:00")), "bad-date: record 0: the valid date and time name no hour"),
    ("a time with seconds", _hd(GOOD.replace("10:00", "10:00:00")), "bad-time: record 0: the valid time is not hh:mm"),
    ("a blank unit", _hd(GOOD.replace("|PPB|", "||")), "blank-value: record 0: the reporting units is blank"),
    ("a blank value", _hd(GOOD.replace("|31|", "| |")), "blank-value: record 0: the value is blank"),
    ("a blank parameter", _hd(GOOD.replace("|OZONE|", "||")), "blank-value: record 0: the parameter name is blank"),
    ("a GMT offset in words", _hd(GOOD.replace("|2|", "|EET|")), "not-a-number: record 0: the GMT offset is not a number"),
    ("a value with an exponent", _hd(GOOD.replace("|31|", "|3e1|")), "not-a-number: record 0: the value is not a decimal number"),
    ("no pipe and no header", _hd("04/28/26 10:00 000000001"), "unknown-form: line 1 is neither the HourlyAQObs header nor a HourlyData line"),
    ("an AQObs quote left open", _aqobs_file()[:-2] + b',"x\r\n', "bad-csv-line: line 1 is not one CSV record"),
    ("an AQObs line of 33 fields", _aqobs_file(_aqobs(**SITE)[:-1]), "width-mismatch: row 0 does not hold the 34 fields"),
    ("an AQObs date in neither form", _aqobs_file(_aqobs(**{**SITE, "ValidDate": "2026-04-28"})), "bad-date: row 0: the valid date is not mm/dd/yy or mm/dd/yyyy"),
    ("one of the two coordinates", _aqobs_file(_aqobs(**{**SITE, "Longitude": ""})), "bad-position: row 0 states one of Latitude and Longitude"),
    ("a latitude past 90", _aqobs_file(_aqobs(**{**SITE, "Latitude": "91.0"})), "bad-position: row 0: Latitude is not decimal degrees within +/-90"),
    ("an elevation in words", _aqobs_file(_aqobs(**{**SITE, "Elevation": "high"})), "not-a-number: row 0: Elevation is not a number"),
    ("a measured flag of 2", _aqobs_file(_aqobs(**{**SITE, "PM10_Measured": "2"})), "bad-measured-flag: row 0: PM10_Measured is not 0 or 1"),
    ("an AQI in words", _aqobs_file(_aqobs(**{**SITE, "OZONE_AQI": "good"})), "not-a-number: row 0: OZONE_AQI is not a decimal number"),
    ("a line with no reading", _aqobs_file(_aqobs(**{**SITE, "OZONE_AQI": ""})), "no-reading: row 0 states no AQI and no concentration"),
    ("a site with two statuses", _aqobs_file(_aqobs(**SITE), _aqobs(**{**SITE, "Status": "Inactive", "ValidTime": "11:00"})), "site-disagrees: record 1 states another position or status for a site an earlier record states"),
    ("a site at two positions", _aqobs_file(_aqobs(**SITE), _aqobs(**{**SITE, "Latitude": "57.0", "ValidTime": "11:00"})), "site-disagrees: record 1 states another position or status for a site an earlier record states"),
    ("an hour past the last one", _aqobs_file(_aqobs(**{**SITE, "ValidDate": "12/31/9999", "ValidTime": "23:00"})), "bad-date: row 0: the hour ends after 9999-12-31"),
    ("a header and no line", _aqobs_file(), "no-data-line: the file holds no data line"),
    ("text", GOOD + "\n", "unsupported-input: a file is handed over as its octets or as its twin in a dict; text and other types are not taken"),
]  # fmt: skip


@pytest.mark.parametrize("label,payload,text", REFUSALS, ids=[c[0] for c in REFUSALS])
def test_a_file_this_module_cannot_read_is_refused_by_name(label, payload, text):
    assert str(_refusal(payload)) == text


NINES = "9" * 400
RANGE_REFUSALS = [
    ("a HourlyData value past the double range", _hd(GOOD.replace("|31|", f"|{NINES}.0|")), f"number-out-of-range: record 0: the value {OUT_OF_RANGE}"),
    ("a negative HourlyData value past the range", _hd(GOOD.replace("|31|", f"|-{NINES}.5|")), f"number-out-of-range: record 0: the value {OUT_OF_RANGE}"),
    ("a HourlyData value that reads as zero", _hd(GOOD.replace("|31|", "|0." + "0" * 400 + "1|")), f"number-out-of-range: record 0: the value {OUT_OF_RANGE}"),
    ("an AQI past the range", _aqobs_file(_aqobs(**{**SITE, "OZONE_AQI": NINES})), f"number-out-of-range: row 0: OZONE_AQI {OUT_OF_RANGE}"),
    ("a concentration past the range", _aqobs_file(_aqobs(**{**SITE, "PM25": NINES + ".0", "PM25_Unit": "UG/M3"})), f"number-out-of-range: row 0: PM25 {OUT_OF_RANGE}"),
    ("a concentration with a blank unit past the range", _aqobs_file(_aqobs(**{**SITE, "PM25": NINES + ".0"})), f"number-out-of-range: row 0: PM25 {OUT_OF_RANGE}"),
    ("a latitude that reads as zero", _aqobs_file(_aqobs(**{**SITE, "Latitude": "0." + "0" * 400 + "1"})), "bad-position: row 0: Latitude is not decimal degrees within +/-90"),
]  # fmt: skip


@pytest.mark.parametrize("label,payload,text", RANGE_REFUSALS, ids=[c[0] for c in RANGE_REFUSALS])
def test_a_number_no_double_holds_is_this_adapter_s_refusal(label, payload, text):
    refusal = _refusal(payload)
    assert (type(refusal), refusal.code, str(refusal)) == (AirnowRefused, text.split(":")[0], text)


def test_the_header_is_the_files_spelling_and_the_fact_sheet_s_ozone_measured_is_refused():
    """The fact sheet's field list spells `Ozone_Measured`; the files write `OZONE_Measured`, as
    every other name of the list is written. The closed header is the files' spelling."""
    assert "OZONE_Measured" in AQOBS_HEADER and "Ozone_Measured" not in AQOBS_HEADER
    sheet = [("Ozone_Measured" if n == "OZONE_Measured" else n) for n in AQOBS_HEADER]
    refusal = _refusal(_aqobs_file(_aqobs(**SITE), header=sheet))
    assert (refusal.code, str(refusal)) == ("unknown-header", HEADER_REFUSAL)


def test_a_twin_is_held_to_its_keys_and_its_fields():
    data, aqobs = _twin("hourly_data_two_sites"), _twin("hourly_aqobs_two_sites")
    shape = "not-a-twin: a twin is {form: HourlyData, records} or {form: HourlyAQObs, header, rows}"
    cases = {
        "another form": ({**data, "form": "Forecast"}, shape),
        "an extra key": ({**data, "header": []}, shape),
        "AQObs without its header": ({"form": "HourlyAQObs", "rows": aqobs["rows"]}, shape),
        "records not a list": ({**data, "records": {}}, "not-a-twin: records is not a list"),
        "a line that is text": ({**data, "records": [GOOD]}, "not-a-twin: records[0] is not a list of fields"),
        "a field that is a number": ({**data, "records": [[31, *data["records"][0][1:]]]}, "not-a-twin: records[0][0] is not a field a file could hold"),
        "a field with a line end": ({**aqobs, "header": ["AQSID\n", *AQOBS_HEADER[1:]]}, "not-a-twin: header[0] is not a field a file could hold"),
        "a renamed header": ({**aqobs, "header": [*AQOBS_HEADER[:-1], "PM10_UNIT"]}, HEADER_REFUSAL),
    }  # fmt: skip
    for label, (document, text) in cases.items():
        assert str(_refusal(document)) == text, label


def test_a_twin_past_the_depth_bound_is_refused_before_decode():
    node: list = []
    for _ in range(63):
        node = [node]
    with pytest.raises(InputTooDeep, match="max_depth = 64"):
        _adapter().to_cdm({"form": "HourlyData", "records": node})


def test_a_refusal_is_a_value_error_that_survives_pickling():
    refusal = _refusal((MALFORMED / "not_on_the_hour.dat").read_bytes())
    again = pickle.loads(pickle.dumps(refusal))
    assert isinstance(again, ValueError)
    assert (type(again), again.code, str(again)) == (
        AirnowRefused,
        "not-an-hour",
        "not-an-hour: record 0: the valid time is not on the hour",
    )


def test_no_refusal_quotes_a_value_from_the_file():
    secret = "8765.4321"
    for payload in (
        _hd(GOOD.replace("|31|", f"|{secret}x|")),
        _hd(GOOD.replace("000000001", secret)),
        _aqobs_file(_aqobs(**{**SITE, "Latitude": secret})),
    ):
        assert secret not in str(_refusal(payload))
