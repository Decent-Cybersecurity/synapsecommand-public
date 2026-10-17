"""`ndbc_stdmet`, #26 in the ordinal table: one NDBC stdmet file -> one Event per row and a station.

Every expectation here is a literal written from the fixture builder's own token tables
(`fixtures/ndbc_stdmet/spec/build_fixtures.py`, which shares no code with the adapter) and from the
layouts research-station-text F01/F02/F16 records, never read back from the adapter: an instant is
the row's year, month, day, hour and minute written out, a value is the token's decimal read by
hand, an identifier is the uuid5 of the documented namespace and name built here, and every
refusal is its code and its whole text. The twins the builder writes are the parse's expectation:
each is compared with what the adapter parses from its octets.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/ndbc_stdmet/` and runs
the packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

import datetime as dt
import json
import math
import pathlib
import pickle
import uuid

import pytest

import synapse_cdm
from synapse_cdm import lossless, manifest, times
from synapse_cdm.adapter import InputTooDeep, discover
from synapse_cdm.adapters import ndbc_stdmet
from synapse_cdm.adapters.ndbc_stdmet import NdbcStdmetAdapter, NdbcStdmetRefused
from synapse_cdm.manifest import LimitKind, UnknownFields
from synapse_cdm.observation_contracts import StationTable, contract_of
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "ndbc_stdmet"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"
TESTS = "tests/test_cdm_ndbc_stdmet_adapter.py"

CASES = sorted(p.stem for p in FIXTURES.glob("*.stdmet"))

REALTIME_HEADER = (
    "#YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE".split()
)
REALTIME_UNITS = "#yr mo dy hr mn degT m/s m/s m sec sec degT hPa degC degC degC nmi hPa ft".split()
HISTORICAL_HEADER = (
    "#YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS TIDE".split()
)
HISTORICAL_UNITS = "#yr mo dy hr mn degT m/s m/s m sec sec degT hPa degC degC degC mi ft".split()

T_INSTANT = (
    "the year, MM, DD, hh and mm columns are read as one UTC instant (NDBC's measurement "
    "descriptions (faq/measdes.shtml): times are UTC)"
)
T_TWO_DIGIT_YEAR = (
    "the two-digit year 98 under a YY header is read as 1998: the YY layout is recorded only in a "
    "1998 file, and the 2004 file writes YYYY (research-station-text F01); no other two-digit "
    "year is read"
)
T_ON_THE_HOUR = "the header has no mm column, so the instant is read on the hour (minute 0)"
T_NUMBER = "each value's decimal text is read as a binary floating-point number"
T_SENTINEL = "a missing-value marker is an Absence carrying the marker as written"
MM = (
    "a realtime file (its header holds PTDY) writes a missing value as MM (NDBC's measurement "
    "descriptions (faq/measdes.shtml); research-station-text F02)"
)
NO_UNITS = (
    "the file has no units line (NDBC files before 2007, research-station-text F01 and F16), so "
    "the value's unit is not stated and the number stays in the Event's residual"
)
TIDE_DATUM = {
    "name": "MLLW",
    "namespace": "NDBC's measurement descriptions (faq/measdes.shtml): TIDE is in feet relative "
    "to mean lower low water",
}
QUALITY_BASIS = (
    "NDBC prints no per-value quality flag in its text files: hard-flagged values are withheld "
    "from public release, soft flags are not printed, and the flags reach only the NOAA archive "
    "(NDBC T80-10, December 2023; research-station-text F12). A missing value is the absence its "
    "sentinel names."
)
TABLE_BASIS = (
    "station table ndbc-stdmet-fixture-stations: synthetic station positions written for the "
    "packaged fixtures on 2026-10-15 (fixtures/ndbc_stdmet/README.md); no real station is named"
)


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _adapter(**kwargs) -> NdbcStdmetAdapter:
    kwargs.setdefault("station_id", "EX001")
    return NdbcStdmetAdapter(times.frozen_clock(), **kwargs)


def _dump(objects) -> list[dict]:
    return [o.model_dump(mode="json") for o in objects]


def _translate(name: str, adapter=None) -> list[dict]:
    adapter = adapter or NdbcStdmetAdapter.fixture_instance(times.frozen_clock())
    return _dump(adapter.to_cdm((FIXTURES / f"{name}.stdmet").read_bytes()))


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _refusal(payload, **kwargs) -> NdbcStdmetRefused:
    with pytest.raises(NdbcStdmetRefused) as raised:
        _adapter(**kwargs).to_cdm(payload)
    return raised.value


def _measured(name: str, value: float, unit: str, datum=None) -> dict:
    return {
        "absence": None,
        "datum": datum,
        "level": None,
        "measurement": {"unit": unit, "unit_namespace": "NDBC stdmet units line", "value": value},
        "name": name,
        "namespace": "NDBC stdmet header line",
    }


def _absent(name: str, cause: str, mechanism: str, sentinel=None, datum=None) -> dict:
    return {
        "absence": {"cause": cause, "mechanism": mechanism, "sentinel": sentinel},
        "datum": datum,
        "level": None,
        "measurement": None,
        "name": name,
        "namespace": "NDBC stdmet header line",
    }


def _nine(column: str, token: str, datum=None) -> dict:
    mechanism = (
        f"a historical file writes a missing {column} as a run of 9s of this width (NDBC's "
        "measurement descriptions (faq/measdes.shtml); the width research-station-text F02 "
        "observed)"
    )
    return _absent(column, "sentinel", mechanism, token, datum)


def _short(reading: dict):
    """(name, value or marker, unit or absence cause) — one reading, compactly."""
    if reading["measurement"] is not None:
        m = reading["measurement"]
        return (reading["name"], m["value"], m["unit"])
    a = reading["absence"]
    return (reading["name"], a["sentinel"], a["cause"])


def _events(objects: list[dict]) -> list[dict]:
    return [o for o in objects if o["object_kind"] == "event"]


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["ndbc_stdmet"]
    assert cls is NdbcStdmetAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "ndbc_stdmet",
        "1.0.0",
        "ingest",
        "NDBC",
    )
    assert ndbc_stdmet.__doc__.splitlines()[0] == (
        "`ndbc_stdmet`, #26 in the ordinal table: one NDBC standard meteorological file -> CDM, "
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
        "NDBC standard meteorological data (stdmet)",
        "NDBC Web Data Guide, Version 2.0 (June 2023)",
        "standard-encoding",
        "PUBLIC_GOVERNMENT",
        "L3",
        "VERIFIED",
        "structured",
    )
    limits = meta.capabilities.limits
    # U-07: one station-text file <= 8 MiB; the twin's three levels under the loader's 64.
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
    assert "synapse-decode --container gzip" in limits.absent_because["max_decompressed_bytes"]
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
    # The basis quotes U-07, the realtime file's 45 days (F18) and the CO-OPS range limits (F05).
    assert "DECISIONS U-07" in source and "8 388 608 octets" in source
    assert "last 45 days at ten-minute rows (research-station-text F18)" in source
    assert "6-minute data one month a request, hourly one year" in source
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    assert [lim.id for lim in meta.limitations] == [
        "one-file-per-call",
        "station-from-the-caller",
        "sentinel-conventions",
        "two-digit-years",
        "no-units-line",
        "instant-not-window",
        "no-quality-flags",
        "evidence-availability",
    ]
    assert all(lim.unsupported_paths == [] for lim in meta.limitations)
    assert {k: (m.to, m.kind) for k, m in NdbcStdmetAdapter.MAPPINGS.items()} == {
        "rows[*]": ("#[*]:residual.data.row", "residual")
    }
    assert ndbc_stdmet.NINE_RUNS == {
        "WVHT": "99.00",
        "DPD": "99.00",
        "APD": "99.00",
        "TIDE": "99.00",
        "MWD": "999",
        "VIS": "99.0",
        "WTMP": "999.0",
    }


@pytest.mark.parametrize("name", CASES)
def test_every_twin_leaf_is_parked_on_its_own_event(name):
    twin = _twin(name)
    objects = _dump(NdbcStdmetAdapter.fixture_instance(times.frozen_clock()).to_cdm(twin))
    book = lossless.ledger(
        twin,
        objects,
        NdbcStdmetAdapter.MAPPINGS,
        unsupported=manifest.unsupported_paths(NdbcStdmetAdapter.metadata.limitations),
    )
    assert book.lost == ()
    leaves = len(twin["header"]) * (1 + len(twin["rows"])) + (
        len(twin["units"]) if twin["units"] is not None else 1
    )
    assert book.counts == {"MAPPED": 0, "RESIDUAL": leaves, "DECLARED_LIMITATION": 0, "LOST": 0}


# ================================================================== the fixture set


YEAR_WIDTH = (
    "bad-time: row 0: the year is not the width its header names (four digits under #YY and "
    "YYYY, two under YY)"
)
YEAR_WINDOW = (
    "a two-digit year other than 98: the YY layout is recorded only in a 1998 file "
    "(research-station-text F01), so no other two-digit year is read"
)
OUT_OF_RANGE = "the number lies outside what a binary double holds"

MALFORMED_REFUSALS = {
    "row_width_mismatch": (
        "width-mismatch",
        "width-mismatch: row 1 has another number of columns than the header",
    ),
    "undocumented_sentinel_width": (
        "undocumented-sentinel",
        "undocumented-sentinel: row 0, column PRES: a run of 9s at a width no document this "
        "module is written from gives for the column",
    ),
    "documented_column_other_width": (
        "undocumented-sentinel",
        "undocumented-sentinel: row 0, column WVHT: a run of 9s at a width no document this "
        "module is written from gives for the column",
    ),
    "mm_in_historical_file": (
        "mm-in-historical-file",
        "mm-in-historical-file: row 0, column WVHT: MM in a file whose header has no PTDY, where "
        "a missing value is a run of 9s",
    ),
    "not_a_number": (
        "not-a-number",
        "not-a-number: row 0, column WSPD: neither a number, MM nor a documented run of 9s",
    ),
    "unknown_column": (
        "unknown-column",
        "unknown-column: header column 8 is not a stdmet column this module reads",
    ),
    "cut_inside_a_row": (
        "unterminated-line",
        "unterminated-line: the last line has no line end: the file is cut short or is not whole "
        "lines",
    ),
    "repeated_instant": ("repeated-instant", "repeated-instant: row 1 states the instant of row 0"),
    "two_digit_year_under_yyyy": ("bad-time", YEAR_WIDTH),
    "two_digit_year_under_hash_yy": ("bad-time", YEAR_WIDTH),
    "two_digit_year_outside_the_record": (
        "undocumented-year",
        "undocumented-year: row 0: " + YEAR_WINDOW,
    ),
    "number_past_the_double_range": (
        "number-out-of-range",
        "number-out-of-range: row 0, column WSPD: " + OUT_OF_RANGE,
    ),
    "signed_value_outside_ptdy": (
        "not-a-number",
        "not-a-number: row 0, column WSPD: neither a number, MM nor a documented run of 9s",
    ),
}


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert CASES == [
        "before_2007_no_units_line",
        "historical_nine_runs",
        "realtime_newest_first",
        "two_digit_year_1998",
    ]
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert sorted(p.name for p in MALFORMED.iterdir() if p.suffix == ".stdmet") == sorted(
        f"{name}.stdmet" for name in MALFORMED_REFUSALS
    )
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(
        f"{name}{suffix}" for name in CASES for suffix in (".cdm.json", ".parsed.cdm.json")
    )


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_every_station_and_position_follows_the_identifier_convention(name):
    objects = _translate(name)
    stations = {o["payload"]["observation"]["station_id"] for o in _events(objects)}
    assert stations == {"EX001"}
    assert support.station_id_problems("EX001", "alphanumeric-5") == []
    assert support.positions_outside_the_rectangle(objects) == []
    assert objects[-1]["position"] is not None


@pytest.mark.parametrize("name", CASES)
def test_the_parse_of_each_file_is_the_twin_its_builder_wrote(name):
    octets = (FIXTURES / f"{name}.stdmet").read_bytes()
    assert ndbc_stdmet.parse_file(octets) == _twin(name)


@pytest.mark.parametrize("name", CASES)
def test_the_octets_and_the_twin_translate_to_one_result(name):
    adapter = NdbcStdmetAdapter.fixture_instance(times.frozen_clock())
    assert _dump(adapter.to_cdm(_twin(name))) == _translate(name)


@pytest.mark.parametrize("name", CASES)
def test_the_two_goldens_of_a_pair_are_one_translation(name):
    payload = json.loads((GOLDEN / f"{name}.cdm.json").read_text())
    twin = json.loads((GOLDEN / f"{name}.parsed.cdm.json").read_text())
    assert payload == twin == _translate(name)


@pytest.mark.parametrize("name", sorted(MALFORMED_REFUSALS))
def test_each_malformed_file_is_refused_with_its_code_and_its_whole_text(name):
    code, text = MALFORMED_REFUSALS[name]
    refusal = _refusal((MALFORMED / f"{name}.stdmet").read_bytes())
    assert (refusal.code, str(refusal)) == (code, text)


# ================================================================== the files, by hand


def test_one_realtime_row_becomes_this_event_and_the_station_this_entity():
    objects = _translate("realtime_newest_first")
    assert [o["object_kind"] for o in objects] == ["event", "event", "event", "entity"]
    site = _uuid("entity", "NDBC", "EX001")
    stamp = "2026-04-28T12:10:00.000Z"
    source = {
        "adapter": "ndbc_stdmet",
        "adapter_version": "1.0.0",
        "format_name": "NDBC standard meteorological data (stdmet)",
        "format_version": "NDBC Web Data Guide, Version 2.0 (June 2023)",
        "original_id": None,
        "source_hash": None,
        "synthetic": True,
        "system": "NDBC",
    }
    # Row 1: 2026 04 28 12 10 225 5.8 7.0 0.90 5.00 3.90 210 1012.6 9.7 8.6 6.8 MM -0.5 MM
    assert objects[1] == {
        "event_id": _uuid("event", "NDBC", f"EX001/{stamp}"),
        "event_type": "ENVIRONMENTAL_OBSERVATION",
        "geometry": {"coordinates": [21.5, 57.25], "type": "Point"},
        "integrity": None,
        "object_kind": "event",
        "observed_at": stamp,
        "oes": None,
        "payload": {
            "observation": {
                "contract": "point-observation/1",
                "locator": {
                    "frame_sha256": None,
                    "granule_id": None,
                    "header_lines": 2,
                    "kind": "table",
                    "row": 1,
                },
                "product_class": "observation",
                "product_version": None,
                "quality_flags": [],
                "quality_flags_basis": QUALITY_BASIS,
                "readings": [
                    _measured("WDIR", 225.0, "degT"),
                    _measured("WSPD", 5.8, "m/s"),
                    _measured("GST", 7.0, "m/s"),
                    _measured("WVHT", 0.9, "m"),
                    _measured("DPD", 5.0, "sec"),
                    _measured("APD", 3.9, "sec"),
                    _measured("MWD", 210.0, "degT"),
                    _measured("PRES", 1012.6, "hPa"),
                    _measured("ATMP", 9.7, "degC"),
                    _measured("WTMP", 8.6, "degC"),
                    _measured("DEWP", 6.8, "degC"),
                    _absent("VIS", "sentinel", MM, "MM"),
                    _measured("PTDY", -0.5, "hPa"),
                    _absent("TIDE", "sentinel", MM, "MM", TIDE_DATUM),
                ],
                "station_id": "EX001",
                "station_namespace": "NDBC station identifier",
                "time": {
                    "forecast_offset": None,
                    "reference_time": None,
                    "reference_time_significance": None,
                    "source_time_system": {
                        "basis": "NDBC's measurement descriptions (faq/measdes.shtml): 'Times are "
                        "in UTC'; the year, MM, DD, hh and mm columns",
                        "name": "UTC",
                        "stated_by": "source",
                    },
                    "statistical_process": None,
                },
            }
        },
        "quality": None,
        "received_at": FROZEN,
        "related_entities": [site],
        "residual": {
            "data": {
                "header": REALTIME_HEADER,
                "row": "2026 04 28 12 10 225 5.8 7.0 0.90 5.00 3.90 210 1012.6 9.7 8.6 6.8 MM "
                "-0.5 MM".split(),
                "units": REALTIME_UNITS,
            },
            "namespace": "NDBC standard meteorological data (stdmet)",
        },
        "schema_version": "3.2.0",
        "severity": "INFO",
        "source": {
            **source,
            "observed_at": stamp,
            "record_index": 1,
            "transformations": [T_INSTANT, T_NUMBER, T_SENTINEL],
        },
        "source_ids": [{"external_id": f"EX001/{stamp}", "system": "NDBC"}],
        "status": None,
        "validity": {
            "effective": {"end": stamp, "start": stamp},
            "observed_at": None,
            "valid_from": None,
            "valid_to": None,
        },
    }
    # The station: the caller's id, the fixture table's position, the EARLIEST row's instant
    # (the last row of a newest-first file).
    assert objects[3] == {
        "affiliation": "UNKNOWN",
        "attributes": {
            "position_basis": TABLE_BASIS,
            "site_class": "buoy",
            "station_id_basis": "the caller's station_id argument: a stdmet file does not state "
            "the station it was recorded at (research-station-text F03)",
            "valid_from_basis": "the earliest instant a row of the file states",
        },
        "confidence": None,
        "entity_id": site,
        "entity_type": "SENSOR",
        "integrity": None,
        "kinematics": None,
        "object_kind": "entity",
        "ontology_types": [],
        "position": {
            "accuracy_m": None,
            "alt_m": None,
            "lat": 57.25,
            "lon": 21.5,
            "position_source": "MANUAL",
            "vertical": None,
        },
        "quality": None,
        # What the file states about itself: its header and units lines.
        "residual": {
            "data": {"header": REALTIME_HEADER, "units": REALTIME_UNITS},
            "namespace": "NDBC standard meteorological data (stdmet)",
        },
        "schema_version": "3.2.0",
        "source": {
            **source,
            "observed_at": "2026-04-28T12:00:00.000Z",
            "record_index": None,
            "transformations": [T_INSTANT],
        },
        "source_ids": [{"external_id": "EX001", "system": "NDBC"}],
        "status": None,
        "symbol": None,
        "valid_from": "2026-04-28T12:00:00.000Z",
        "valid_to": None,
    }
    # File order is kept: newest first, and record_index is the data row, not a time order.
    assert [(e["observed_at"], e["source"]["record_index"]) for e in _events(objects)] == [
        ("2026-04-28T12:20:00.000Z", 0),
        ("2026-04-28T12:10:00.000Z", 1),
        ("2026-04-28T12:00:00.000Z", 2),
    ]
    rows = [[_short(r) for r in e["payload"]["observation"]["readings"]] for e in _events(objects)]
    assert rows[0] == [
        ("WDIR", 230.0, "degT"),
        ("WSPD", 6.1, "m/s"),
        ("GST", 7.4, "m/s"),
        ("WVHT", "MM", "sentinel"),
        ("DPD", "MM", "sentinel"),
        ("APD", "MM", "sentinel"),
        ("MWD", "MM", "sentinel"),
        ("PRES", 1012.4, "hPa"),
        ("ATMP", 9.8, "degC"),
        ("WTMP", 8.6, "degC"),
        ("DEWP", 6.9, "degC"),
        ("VIS", "MM", "sentinel"),
        ("PTDY", 0.3, "hPa"),
        ("TIDE", "MM", "sentinel"),
    ]
    assert rows[2][11:] == [("VIS", 4.8, "nmi"), ("PTDY", 0.0, "hPa"), ("TIDE", "MM", "sentinel")]


def test_a_historical_file_reads_its_documented_nine_runs_as_missing_and_mi_as_written():
    events = _events(_translate("historical_nine_runs"))
    assert [e["observed_at"] for e in events] == [
        "2025-11-03T00:00:00.000Z",
        "2025-11-03T00:10:00.000Z",
        "2025-11-03T00:20:00.000Z",
    ]
    first = events[0]["payload"]["observation"]["readings"]
    assert first == [
        _measured("WDIR", 140.0, "degT"),
        _measured("WSPD", 3.1, "m/s"),
        _measured("GST", 4.0, "m/s"),
        _nine("WVHT", "99.00"),
        _nine("DPD", "99.00"),
        _nine("APD", "99.00"),
        _nine("MWD", "999"),
        _measured("PRES", 1018.2, "hPa"),
        _measured("ATMP", 11.4, "degC"),
        _measured("WTMP", 12.9, "degC"),
        _measured("DEWP", 9.0, "degC"),
        _nine("VIS", "99.0"),
        _nine("TIDE", "99.00", TIDE_DATUM),
    ]
    third = [_short(r) for r in events[2]["payload"]["observation"]["readings"]]
    assert third[3:7] == [
        ("WVHT", 1.05, "m"),
        ("DPD", 6.7, "sec"),
        ("APD", 5.1, "sec"),
        ("MWD", 155.0, "degT"),
    ]
    # WTMP 999.0 is the documented run; VIS keeps the yearly file's `mi`, as written (F16).
    assert third[9] == ("WTMP", "999.0", "sentinel")
    second = [_short(r) for r in events[1]["payload"]["observation"]["readings"]]
    assert second[11] == ("VIS", "99.0", "sentinel")
    assert HISTORICAL_UNITS[16] == "mi" and events[1]["residual"]["data"]["units"][16] == "mi"
    assert events[1]["source"]["transformations"] == [T_INSTANT, T_NUMBER, T_SENTINEL]


def test_a_file_without_a_units_line_states_no_unit_and_the_two_digit_year_98_is_1998():
    events = _events(_translate("two_digit_year_1998"))
    assert [(e["observed_at"], e["validity"]["effective"]) for e in events] == [
        ("1998-06-15T00:00:00.000Z", {"end": "1998-06-15T00:00:00.000Z", "start": "1998-06-15T00:00:00.000Z"}),
        ("1998-06-15T01:00:00.000Z", {"end": "1998-06-15T01:00:00.000Z", "start": "1998-06-15T01:00:00.000Z"}),
    ]  # fmt: skip
    readings = events[0]["payload"]["observation"]["readings"]
    names = "WD WSPD GST WVHT DPD APD MWD BAR ATMP WTMP DEWP".split()
    assert readings == [_absent(n, "unit_unknown", NO_UNITS) for n in names] + [
        _nine("VIS", "99.0")
    ]
    assert events[0]["payload"]["observation"]["locator"]["header_lines"] == 1
    # The numbers whose unit is not stated stay in the residual row, as written.
    assert events[0]["residual"]["data"] == {
        "header": "YY MM DD hh WD WSPD GST WVHT DPD APD MWD BAR ATMP WTMP DEWP VIS".split(),
        "row": "98 06 15 00 200 4.2 5.1 0.80 5.00 4.10 190 1015.3 14.2 13.0 10.1 99.0".split(),
        "units": None,
    }
    # No number reached a measurement, so the number transformation is not claimed.
    assert events[0]["source"]["transformations"] == [
        T_INSTANT,
        T_TWO_DIGIT_YEAR,
        T_ON_THE_HOUR,
        T_SENTINEL,
    ]


def test_the_2004_layout_reads_yyyy_without_minutes_and_keeps_the_tide_datum():
    events = _events(_translate("before_2007_no_units_line"))
    assert [e["observed_at"] for e in events] == [
        "2004-09-01T18:00:00.000Z",
        "2004-09-01T19:00:00.000Z",
    ]
    last = events[1]["payload"]["observation"]["readings"]
    # TIDE 0.75 in a file with no units line: an absence, and still referred to MLLW.
    assert last[-1] == _absent("TIDE", "unit_unknown", NO_UNITS, None, TIDE_DATUM)
    assert events[0]["payload"]["observation"]["readings"][-1] == _nine("TIDE", "99.00", TIDE_DATUM)
    assert events[1]["source"]["transformations"] == [T_INSTANT, T_ON_THE_HOUR, T_SENTINEL]


def test_a_run_of_nines_in_a_realtime_file_is_a_value_and_crlf_reads_as_lf():
    text = (
        "#YY MM DD hh mm WDIR PRES PTDY\n#yr mo dy hr mn degT hPa hPa\n"
        "2026 04 28 12 00 99 999.0 99.0\n"
    )
    events = _events(_dump(_adapter().to_cdm(text.encode())))
    # In a realtime file (PTDY in the header) MM is the marker and a run of 9s is a reading.
    assert [_short(r) for r in events[0]["payload"]["observation"]["readings"]] == [
        ("WDIR", 99.0, "degT"),
        ("PRES", 999.0, "hPa"),
        ("PTDY", 99.0, "hPa"),
    ]
    crlf = _dump(_adapter().to_cdm(text.replace("\n", "\r\n").encode()))
    assert crlf == _dump(_adapter().to_cdm(text.encode()))


def test_without_a_station_table_or_a_row_for_the_station_the_position_is_null():
    octets = (FIXTURES / "realtime_newest_first.stdmet").read_bytes()
    alone = _dump(_adapter().to_cdm(octets))
    assert alone[-1]["position"] is None
    assert alone[-1]["attributes"]["position_basis"] == (
        "no position: the payload states none and no station table was supplied"
    )
    assert {e["geometry"] for e in _events(alone)} == {None}
    other = StationTable(
        name="t", basis="a table for another station", rows=[{"station_id": "EX002", "lat": 57.0, "lon": 21.0}]
    )  # fmt: skip
    missing = _dump(_adapter(station_table=other).to_cdm(octets))
    assert missing[-1]["position"] is None
    assert missing[-1]["attributes"]["position_basis"] == (
        "no position: the payload states none and the station table has no row for this station"
    )
    # Another station id is another Entity and other Event ids; nothing else moves.
    two = _dump(_adapter(station_id="EX002", station_table=other).to_cdm(octets))
    assert two[-1]["entity_id"] == _uuid("entity", "NDBC", "EX002")
    assert two[0]["event_id"] == _uuid("event", "NDBC", "EX002/2026-04-28T12:20:00.000Z")
    assert two[-1]["position"]["lat"] == 57.0


def test_the_injected_digests_reach_every_stamp_and_every_locator():
    digest, frame = "a" * 64, "b" * 64
    adapter = _adapter(source_hash={"algorithm": "sha256", "value": digest}, frame_sha256=frame)
    objects = _dump(adapter.to_cdm((FIXTURES / "historical_nine_runs.stdmet").read_bytes()))
    assert [o["source"]["source_hash"] for o in objects] == [
        {"algorithm": "sha256", "value": digest}
    ] * 4
    assert [e["payload"]["observation"]["locator"]["frame_sha256"] for e in _events(objects)] == [
        frame
    ] * 3
    for bad in (
        {"source_hash": {"algorithm": "md5", "value": digest}},
        {"source_hash": {"algorithm": "sha256", "value": "A" * 64}},
        {"frame_sha256": "b" * 63},
        {"frame_sha256": b"b" * 64},
    ):
        with pytest.raises(ValueError):
            _adapter(**bad)


def test_the_receipt_clock_reaches_received_at_and_nothing_else():
    later = NdbcStdmetAdapter.fixture_instance(
        times.frozen_clock(dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc))
    )
    for name in CASES:
        for x, y in zip(_translate(name), _translate(name, later)):
            if x["object_kind"] == "event":
                assert (x["received_at"], y["received_at"]) == (FROZEN, "2026-05-01T00:00:00.000Z")
                x, y = {**x, "received_at": None}, {**y, "received_at": None}
            assert x == y


def test_every_event_carries_a_contract_the_model_accepts():
    from synapse_cdm.models import Event

    for name in CASES:
        for obj in _events(_translate(name)):
            contract = contract_of(Event.model_validate(obj))
            assert contract.contract == "point-observation/1"


# ================================================================== the refusals


def test_the_constructor_refuses_a_station_it_cannot_name():
    for bad in ("ex001", "EX01", "EX0012", " EX001", 44, None):
        with pytest.raises(ValueError) as raised:
            NdbcStdmetAdapter(station_id=bad)
        assert str(raised.value) == (
            "station_id is five upper-case letters or digits, as NDBC writes one"
        )
    with pytest.raises(TypeError):
        NdbcStdmetAdapter()
    with pytest.raises(ValueError, match="station_table is a StationTable"):
        NdbcStdmetAdapter(station_id="EX001", station_table={"rows": []})


HEADER = "#YY MM DD hh mm WDIR PTDY\n#yr mo dy hr mn degT hPa\n"
ROW = "2026 04 28 12 00 220 -0.3\n"

TEXT_REFUSALS = [
    ("an empty file", b"", "empty-file: the file holds no line"),
    ("not UTF-8", HEADER.encode() + b"2026 04 28 12 00 22\xff -0.3\n", "not-utf8: the file is not UTF-8 text"),
    ("a byte-order mark", b"\xef\xbb\xbf" + (HEADER + ROW).encode(), "byte-order-mark: the file opens with a byte-order mark"),
    ("a tab", (HEADER + ROW.replace(" 220", "\t220")).encode(), "control-character: line 3 holds a control character"),
    ("a NUL", (HEADER + ROW.replace("220", "2\x000")).encode(), "control-character: line 3 holds a control character"),
    ("a bare CR", (HEADER + ROW.replace(" 220", "\r220")).encode(), "control-character: line 3 holds a control character"),
    ("mixed line ends", (HEADER.replace("\n", "\r\n", 1) + ROW).encode(), "mixed-line-ends: line 2 ends otherwise than line 1"),
    ("a blank line", (HEADER + "   \n" + ROW).encode(), "blank-line: line 3 is blank"),
    ("no last line end", (HEADER + ROW).encode()[:-1], "unterminated-line: the last line has no line end: the file is cut short or is not whole lines"),
    ("a # line among the rows", (HEADER + ROW + "#note\n").encode(), "comment-among-rows: line 4 is a # line after the data began"),
    ("no data row", HEADER.encode(), "no-data-row: the file holds no data row"),
]  # fmt: skip


@pytest.mark.parametrize("label,payload,text", TEXT_REFUSALS, ids=[c[0] for c in TEXT_REFUSALS])
def test_a_file_that_is_not_whole_lines_of_text_is_refused(label, payload, text):
    assert str(_refusal(payload)) == text


def _file(header: str, units: str | None, *rows: str) -> bytes:
    return (
        header + "\n" + (units + "\n" if units else "") + "".join(r + "\n" for r in rows)
    ).encode()


HEADER_REFUSALS = [
    ("the year column", _file("#YR MM DD hh WDIR", None, "2026 04 28 12 220"), "unknown-header: the header's first column is not #YY, YY or YYYY"),
    ("the time columns", _file("#YY DD MM hh WDIR", None, "2026 28 04 12 220"), "unknown-header: the header's second to fourth columns are not MM, DD and hh"),
    ("no data column", _file("#YY MM DD hh mm", None, "2026 04 28 12 00"), "unknown-header: the header names no data column"),
    ("a column twice", _file("#YY MM DD hh WDIR WDIR", None, "2026 04 28 12 220 221"), "repeated-column: the header names one column twice"),
    ("both WD and WDIR", _file("#YY MM DD hh WD WDIR", None, "2026 04 28 12 220 221"), "repeated-column: the header names both WDIR and WD, one quantity"),
    ("both BAR and PRES", _file("YYYY MM DD hh PRES BAR", None, "2004 04 28 12 1010.0 1010.1"), "repeated-column: the header names both PRES and BAR, one quantity"),
    ("the units line's width", _file("#YY MM DD hh WDIR", "#yr mo dy hr", "2026 04 28 12 220"), "width-mismatch: the units line states another number of columns than the header"),
    ("month 13", _file("#YY MM DD hh WDIR", None, "2026 13 28 12 220"), "bad-time: row 0: the date and time name no instant"),
    ("30 February", _file("#YY MM DD hh WDIR", None, "2026 02 30 12 220"), "bad-time: row 0: the date and time name no instant"),
    ("hour 24", _file("#YY MM DD hh WDIR", None, "2026 04 28 24 220"), "bad-time: row 0: the date and time name no instant"),
    ("minute 60", _file("#YY MM DD hh mm WDIR", None, "2026 04 28 12 60 220"), "bad-time: row 0: the date and time name no instant"),
    ("a one-digit hour", _file("#YY MM DD hh WDIR", None, "2026 04 28 9 220"), "bad-time: row 0: a month, day, hour or minute is not two digits"),
    ("MM for the hour", _file("#YY MM DD hh WDIR PTDY", None, "2026 04 28 MM 220 0.1"), "bad-time: row 0: a month, day, hour or minute is not two digits"),
    ("a three-digit year", _file("#YY MM DD hh WDIR", None, "026 04 28 12 220"), YEAR_WIDTH),
    ("a signed number", _file("#YY MM DD hh WDIR PTDY", None, "2026 04 28 12 +220 0.1"), "not-a-number: row 0, column WDIR: neither a number, MM nor a documented run of 9s"),
    ("an exponent", _file("#YY MM DD hh WDIR PTDY", None, "2026 04 28 12 2e2 0.1"), "not-a-number: row 0, column WDIR: neither a number, MM nor a documented run of 9s"),
]  # fmt: skip


@pytest.mark.parametrize("label,payload,text", HEADER_REFUSALS, ids=[c[0] for c in HEADER_REFUSALS])
def test_a_header_or_a_row_no_stdmet_layout_has_is_refused(label, payload, text):
    assert str(_refusal(payload)) == text


def test_the_realtime_tendency_is_read_with_its_sign_and_a_signed_zero_as_zero():
    events = _events(_translate("realtime_newest_first"))
    # PTDY is the 18th token of a row and the 13th reading; the tokens as the builder wrote them.
    assert [e["residual"]["data"]["row"][17] for e in events] == ["+0.3", "-0.5", "+0.0"]
    assert [e["payload"]["observation"]["readings"][12] for e in events] == [
        _measured("PTDY", 0.3, "hPa"),
        _measured("PTDY", -0.5, "hPa"),
        _measured("PTDY", 0.0, "hPa"),
    ]
    units = "#yr mo dy hr mn degT hPa"
    minus_zero = _file("#YY MM DD hh mm WDIR PTDY", units, "2026 04 28 12 00 220 -0.0")
    reading = _events(_dump(_adapter().to_cdm(minus_zero)))[0]["payload"]["observation"]
    value = reading["readings"][1]["measurement"]["value"]
    assert value == 0.0 and math.copysign(1.0, value) == -1.0


SIGN_REFUSALS = ["+", "-", "++0.3", "+-0.3", "-+0.3", "+.3", "+3.", "+0x1", "+1e2", "+0,3"]


@pytest.mark.parametrize("token", SIGN_REFUSALS)
def test_a_tendency_with_a_sign_and_no_decimal_after_it_is_not_a_number(token):
    payload = _file(
        "#YY MM DD hh mm WDIR PTDY", "#yr mo dy hr mn degT hPa", f"2026 04 28 12 00 220 {token}"
    )
    refusal = _refusal(payload)
    assert (refusal.code, str(refusal)) == (
        "not-a-number",
        "not-a-number: row 0, column PTDY: neither a number, MM nor a documented run of 9s",
    )


@pytest.mark.parametrize("year", ["00", "03", "05", "26", "97", "99"])
def test_a_two_digit_year_other_than_98_is_refused_never_read_as_19yy(year):
    refusal = _refusal(_file("YY MM DD hh WD", None, f"{year} 06 15 00 200"))
    assert (refusal.code, str(refusal)) == (
        "undocumented-year",
        "undocumented-year: row 0: " + YEAR_WINDOW,
    )


YEAR_WIDTHS = [
    ("two digits under #YY", "#YY", "26"),
    ("98 under #YY", "#YY", "98"),
    ("two digits under YYYY", "YYYY", "98"),
    ("four digits under YY", "YY", "1998"),
    ("2026 under YY", "YY", "2026"),
]


@pytest.mark.parametrize("label,label_column,year", YEAR_WIDTHS, ids=[c[0] for c in YEAR_WIDTHS])
def test_the_year_is_the_width_its_header_column_names(label, label_column, year):
    refusal = _refusal(_file(f"{label_column} MM DD hh WD", None, f"{year} 06 15 00 200"))
    assert (refusal.code, str(refusal)) == ("bad-time", YEAR_WIDTH)
    accepted = _events(_dump(_adapter().to_cdm(_file("YY MM DD hh WD", None, "98 06 15 00 200"))))
    assert accepted[0]["observed_at"] == "1998-06-15T00:00:00.000Z"


NINES = "9" * 400
RANGE_REFUSALS = [
    ("past the double range", _file("#YY MM DD hh mm WSPD PTDY", "#yr mo dy hr mn m/s hPa", f"2026 04 28 12 00 {NINES}.0 0.1"), "WSPD"),
    ("a non-zero value that reads as zero", _file("#YY MM DD hh mm WSPD PTDY", "#yr mo dy hr mn m/s hPa", "2026 04 28 12 00 0." + "0" * 400 + "1 0.1"), "WSPD"),
    ("a signed tendency past the range", _file("#YY MM DD hh mm WSPD PTDY", "#yr mo dy hr mn m/s hPa", f"2026 04 28 12 00 5.5 +{NINES}.0"), "PTDY"),
    ("a negative value past the range", _file("#YY MM DD hh mm WSPD PTDY", "#yr mo dy hr mn m/s hPa", f"2026 04 28 12 00 -{NINES}.5 0.1"), "WSPD"),
    ("past the range in a file without units", _file("YYYY MM DD hh WSPD", None, f"2004 09 01 18 {NINES}.5"), "WSPD"),
]  # fmt: skip


@pytest.mark.parametrize("label,payload,column", RANGE_REFUSALS, ids=[c[0] for c in RANGE_REFUSALS])
def test_a_number_no_double_holds_is_this_adapter_s_refusal(label, payload, column):
    refusal = _refusal(payload)
    assert (type(refusal), refusal.code, str(refusal)) == (
        NdbcStdmetRefused,
        "number-out-of-range",
        f"number-out-of-range: row 0, column {column}: {OUT_OF_RANGE}",
    )


def test_a_twin_is_held_to_its_keys_and_its_tokens():
    twin = _twin("realtime_newest_first")
    cases = {
        "an extra key": ({**twin, "station": "EX001"}, "not-a-twin: a twin holds exactly the keys header, units and rows"),
        "a missing key": ({"header": twin["header"], "rows": twin["rows"]}, "not-a-twin: a twin holds exactly the keys header, units and rows"),
        "an empty header": ({**twin, "header": []}, "not-a-twin: header is not a non-empty list of tokens"),
        "a token with a space": ({**twin, "rows": [["2026 04", *twin["rows"][0][1:]]]}, "not-a-twin: rows[0][0] is not one whitespace-free token"),
        "an empty token": ({**twin, "units": ["", *twin["units"][1:]]}, "not-a-twin: units[0] is not one whitespace-free token"),
        "a number": ({**twin, "rows": [[2026, *twin["rows"][0][1:]]]}, "not-a-twin: rows[0][0] is not one whitespace-free token"),
        "a lone surrogate": ({**twin, "header": ["#YY\ud800", *twin["header"][1:]]}, "not-a-twin: header[0] is not one whitespace-free token"),
        "rows not a list": ({**twin, "rows": {}}, "not-a-twin: rows is not a list"),
        "units without #": ({**twin, "units": ["yr", *twin["units"][1:]]}, "not-a-twin: a units line begins with #"),
    }  # fmt: skip
    for label, (document, text) in cases.items():
        assert str(_refusal(document)) == text, label
    assert str(_refusal("#YY MM DD hh WDIR\n")) == (
        "unsupported-input: a stdmet file is handed over as its octets or as its twin in a dict; "
        "text and other types are not taken"
    )


def test_a_twin_past_the_depth_bound_is_refused_before_decode():
    twin = _twin("realtime_newest_first")
    node: list = []
    for _ in range(63):
        node = [node]
    with pytest.raises(InputTooDeep, match="max_depth = 64"):
        _adapter().to_cdm({**twin, "rows": node})


def test_a_refusal_is_a_value_error_that_survives_pickling():
    refusal = _refusal((MALFORMED / "unknown_column.stdmet").read_bytes())
    assert isinstance(refusal, ValueError)
    again = pickle.loads(pickle.dumps(refusal))
    assert (type(again), again.code, str(again)) == (
        NdbcStdmetRefused,
        "unknown-column",
        "unknown-column: header column 8 is not a stdmet column this module reads",
    )


def test_no_refusal_quotes_a_value_from_the_file():
    secret = "8765.4321"
    for payload in (
        _file("#YY MM DD hh WDIR", None, f"2026 04 28 12 {secret}x"),
        _file("#YY MM DD hh PRES", None, "2026 04 28 12 9999.0"),
        _file(f"#YY MM DD hh X{secret}", None, "2026 04 28 12 1"),
    ):
        assert secret not in str(_refusal(payload)) and "9999.0" not in str(_refusal(payload))
