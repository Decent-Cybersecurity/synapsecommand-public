"""`coops_csv`, #27 in the ordinal table: one NOAA CO-OPS data response -> Events and a station.

Every expectation here is a literal written from the fixture builder's own literals
(`fixtures/coops_csv/spec/build_fixtures.py`, which shares no code with the adapter) and from the
layouts research-station-text F04 to F06 records, never read back from the adapter: an instant is
the row's stamp worked by hand under the request's time zone (the five-hour `lst` shift written
out), a value is the field's decimal read by hand, an identifier is the uuid5 of the documented
namespace and name built here, and every refusal is its code and its whole text.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/coops_csv/` and runs the
packaged builder's `--check`, all through `synapse_cdm.__file__`.
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
from synapse_cdm.adapters import coops_csv
from synapse_cdm.adapters.coops_csv import CoopsCsvAdapter, CoopsRefused, CoopsRequest
from synapse_cdm.manifest import LimitKind, UnknownFields
from synapse_cdm.observation_contracts import StationTable
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "coops_csv"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"
TESTS = "tests/test_cdm_coops_csv_adapter.py"

CSV_CASES = sorted(p.stem for p in FIXTURES.glob("*.csv"))
JSON_CASES = sorted(
    p.stem for p in FIXTURES.glob("*.json") if not p.name.endswith(".parsed.json")
    and p.name != "PROVENANCE.json"
)  # fmt: skip

WATER_LEVEL = "Date Time, Water Level, Sigma, O or I (for verified), F, R, L, Quality"
AIR_PRESSURE = "Date Time, Pressure, X, N, R "
WIND = "Date Time, Speed, Direction, Direction, Gust, X, R"

T_GMT = "the request's time_zone is gmt, so each stamp is read as UTC"
T_LST = (
    "the request's time_zone is lst, local standard time: each stamp is read as UTC by "
    "subtracting the caller's declared lst_offset"
)
T_NUMBER = "each value's decimal text is read as a binary floating-point number"
T_FLAGS = "each flag's decimal text is read as an integer"
FLAGS_NS = (
    "the CO-OPS response field definitions (api/prod/responseHelp.html): the product's quality "
    "flags"
)
QUALITY_NS = (
    "the CO-OPS response field definitions (api/prod/responseHelp.html): p preliminary, v verified"
)
UNITS_NS = "CO-OPS datagetter request parameter units"
DATUM = {"name": "MLLW", "namespace": "CO-OPS datagetter request parameter datum"}
GMT_BASIS = (
    "CoopsRequest.time_zone gmt, the request parameter the response does not echo "
    "(research-station-text F05): each stamp is read as UTC"
)
FIXTURE_REQUEST = {
    "datum": "MLLW",
    "interval": "6",
    "lst_offset": None,
    "product": "water_level",
    "station": "0000001",
    "time_zone": "gmt",
    "units": "metric",
}


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _request(**over) -> CoopsRequest:
    fields = {
        "station": "0000001",
        "product": "water_level",
        "datum": "MLLW",
        "units": "metric",
        "time_zone": "gmt",
    }
    fields.update(over)
    return CoopsRequest(**fields)


def _adapter(request=None, **kwargs) -> CoopsCsvAdapter:
    return CoopsCsvAdapter(times.frozen_clock(), request=request or _request(), **kwargs)


def _dump(objects) -> list[dict]:
    return [o.model_dump(mode="json") for o in objects]


def _payload(name: str):
    if name in JSON_CASES:
        return json.loads((FIXTURES / f"{name}.json").read_text())
    return (FIXTURES / f"{name}.csv").read_bytes()


def _translate(name: str, adapter=None) -> list[dict]:
    adapter = adapter or CoopsCsvAdapter.fixture_instance(times.frozen_clock())
    return _dump(adapter.to_cdm(_payload(name)))


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _refusal(payload, request=None, **kwargs) -> CoopsRefused:
    with pytest.raises(CoopsRefused) as raised:
        _adapter(request, **kwargs).to_cdm(payload)
    return raised.value


def _events(objects: list[dict]) -> list[dict]:
    return [o for o in objects if o["object_kind"] == "event"]


def _reading(name: str, value: float, unit: str = "metric", datum=None, namespace=None) -> dict:
    return {
        "absence": None,
        "datum": datum,
        "level": None,
        "measurement": {
            "unit": unit,
            "unit_namespace": UNITS_NS if unit in ("metric", "english") else namespace,
            "value": value,
        },
        "name": name,
        "namespace": "CO-OPS datagetter water_level",
    }


def _flag(name: str, value, applies_to: str = "Water Level") -> dict:
    namespace = QUALITY_NS if name == "Quality" else FLAGS_NS
    return {"applies_to": applies_to, "name": name, "namespace": namespace, "value": value}


def _flags(names: str, values: tuple, quality: str) -> list[dict]:
    return [_flag(n, v) for n, v in zip(names.split(), values)] + [
        _flag("Quality", quality, "record")
    ]


def _short(event: dict) -> tuple:
    observation = event["payload"]["observation"]
    return (
        event["observed_at"],
        [(r["name"], r["measurement"]["value"]) for r in observation["readings"]],
        [(f["name"], f["value"]) for f in observation["quality_flags"]],
    )


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["coops_csv"]
    assert cls is CoopsCsvAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "coops_csv",
        "1.0.0",
        "ingest",
        "CO-OPS",
    )
    assert coops_csv.__doc__.splitlines()[0] == (
        "`coops_csv`, #27 in the ordinal table: one NOAA CO-OPS data response -> CDM, ingest only."
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
        "NOAA CO-OPS data API response (datagetter)",
        "api.tidesandcurrents.noaa.gov/api/prod, read 2026-10-14",
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
    source = limits.declared_because["max_input_bytes"].source
    # U-07 and the API's request range limits (F05): one month of 6-minute samples is
    # 31 x 24 x 10 = 7 440 rows, one year of hourly ones at most 366 x 24 = 8 784.
    assert 31 * 24 * 10 == 7440 and 366 * 24 == 8784
    assert "6-minute data one month a request, hourly data one year" in source
    assert "7 440 rows" in source and "8 784" in source and "DECISIONS U-07" in source
    assert limits.declared_because["max_depth"].test == (
        "tests/test_cdm_parser_safety.py::"
        "test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it"
    )
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    assert [lim.id for lim in meta.limitations] == [
        "request-from-the-caller",
        "lst-ldt-refused",
        "products-read",
        "units-verbatim",
        "blank-values-refused",
        "direction-text-in-residual",
        "evidence-availability",
    ]
    assert coops_csv.HEADERS == {
        "water_level": WATER_LEVEL,
        "air_pressure": AIR_PRESSURE,
        "wind": WIND,
    }
    assert coops_csv.DATUMS == (
        "MLLW", "MLW", "MSL", "MHW", "MHHW", "NAVD", "STND", "CRD", "IGLD", "LWD", "MTL",
    )  # fmt: skip


def test_the_ledger_binds_each_row_to_its_own_event_and_the_metadata_to_the_station():
    assert {
        key: [(m.to, m.rule, m.kind) for m in (v if isinstance(v, tuple) else (v,))]
        for key, v in CoopsCsvAdapter.MAPPINGS.items()
    } == {
        "rows[*][1]": [
            ("#[*]:residual.data.row[1]", "identity", "residual"),
            ("#[*]:payload.observation.readings[0].measurement.value", "numeric_text", "field"),
        ],
        "rows[*]": [("#[*]:residual.data.row", "identity", "residual")],
        "data[*].v": [
            ("#[*]:residual.data.record.v", "identity", "residual"),
            ("#[*]:payload.observation.readings[0].measurement.value", "numeric_text", "field"),
        ],
        "data[*].s": [
            ("#[*]:residual.data.record.s", "identity", "residual"),
            ("#[*]:payload.observation.readings[1].measurement.value", "numeric_text", "field"),
        ],
        "data[*]": [("#[*]:residual.data.record", "identity", "residual")],
        "metadata.id": [
            ("entity:residual.data.metadata.id", "identity", "residual"),
            ("entity:source_ids[0].external_id", "identity", "field"),
        ],
        "metadata.lat": [
            ("entity:residual.data.metadata.lat", "identity", "residual"),
            ("entity:position.lat", "numeric_text", "field"),
        ],
        "metadata.lon": [
            ("entity:residual.data.metadata.lon", "identity", "residual"),
            ("entity:position.lon", "numeric_text", "field"),
        ],
        "metadata": [("entity:residual.data.metadata", "identity", "residual")],
    }


@pytest.mark.parametrize("name", CSV_CASES + JSON_CASES)
def test_every_leaf_is_mapped_or_parked_on_its_own_object(name):
    document = _twin(name) if name in CSV_CASES else _payload(name)
    objects = _dump(CoopsCsvAdapter.fixture_instance(times.frozen_clock()).to_cdm(document))
    book = lossless.ledger(
        document,
        objects,
        CoopsCsvAdapter.MAPPINGS,
        unsupported=manifest.unsupported_paths(CoopsCsvAdapter.metadata.limitations),
    )
    assert book.lost == ()
    if name in CSV_CASES:
        rows = len(document["rows"])
        # The header, `form`, and the eight fields of every row, the value (field 1) MAPPED.
        assert book.counts == {
            "MAPPED": rows,
            "RESIDUAL": 2 + 7 * rows,
            "DECLARED_LIMITATION": 0,
            "LOST": 0,
        }
    else:
        records = len(document["data"])
        # v and s of every record and the station's id, lat and lon are MAPPED; the name and
        # every other key are parked.
        assert book.counts == {
            "MAPPED": 2 * records + 3,
            "RESIDUAL": 1 + 3 * records,
            "DECLARED_LIMITATION": 0,
            "LOST": 0,
        }


# ================================================================== the fixture set


MALFORMED_REFUSALS = {
    "unknown_header.csv": (
        "unknown-header",
        "unknown-header: the CSV header is not the request's product's header",
    ),
    "air_pressure_header.csv": (
        "header-of-another-product",
        "header-of-another-product: the CSV header is another product's than the request's",
    ),
    "row_width_mismatch.csv": (
        "width-mismatch",
        "width-mismatch: row 1 has another number of fields than the header",
    ),
    "not_a_number.csv": (
        "not-a-number",
        "not-a-number: row 0, Water Level is not a decimal number",
    ),
    "stamp_with_seconds.csv": ("bad-time", "bad-time: row 0: the stamp is not YYYY-MM-DD HH:MM"),
    "blank_value.csv": ("blank-value", "blank-value: row 0, field 1 is blank"),
    "quality_not_p_or_v.csv": (
        "bad-quality",
        "bad-quality: row 0: the Quality field is not p or v",
    ),
    "cut_inside_a_row.csv": (
        "unterminated-line",
        "unterminated-line: the last line has no line end: the file is cut short or is not whole "
        "lines",
    ),
    "json_station_disagrees.json": (
        "station-disagrees",
        "station-disagrees: metadata.id is not the request's station",
    ),
    "json_unknown_key.json": (
        "not-a-response",
        "not-a-response: a JSON response holds exactly the keys metadata and data",
    ),
    "number_past_the_double_range.csv": (
        "number-out-of-range",
        "number-out-of-range: row 0, Water Level lies outside what a binary double holds",
    ),
    "flag_past_the_double_range.csv": (
        "flag-out-of-range",
        "flag-out-of-range: row 0, flag O is an integer no binary double holds",
    ),
}


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert CSV_CASES == [
        "water_level_below_datum_flagged",
        "water_level_preliminary",
        "water_level_verified",
    ]
    assert JSON_CASES == ["water_level_json_form"]
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert sorted(
        p.name for p in MALFORMED.iterdir() if p.name not in ("README.md", "PROVENANCE.json")
    ) == sorted(MALFORMED_REFUSALS)
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(
        [f"{n}{s}" for n in CSV_CASES for s in (".cdm.json", ".parsed.cdm.json")]
        + [f"{n}.cdm.json" for n in JSON_CASES]
    )


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CSV_CASES + JSON_CASES)
def test_every_station_and_position_follows_the_identifier_convention(name):
    objects = _translate(name)
    assert {e["payload"]["observation"]["station_id"] for e in _events(objects)} == {"0000001"}
    assert support.station_id_problems("0000001", "numeric-7") == []
    assert support.positions_outside_the_rectangle(objects) == []
    if name in JSON_CASES:
        # The JSON form states its position as strings, which the support walk does not read.
        metadata = _payload(name)["metadata"]
        assert (
            support.positions_outside_the_rectangle(
                {"lat": float(metadata["lat"]), "lon": float(metadata["lon"])}
            )
            == []
        )


@pytest.mark.parametrize("name", CSV_CASES)
def test_the_parse_of_each_response_is_the_twin_its_builder_wrote(name):
    assert coops_csv.parse_response((FIXTURES / f"{name}.csv").read_bytes()) == _twin(name)


@pytest.mark.parametrize("name", CSV_CASES)
def test_the_octets_and_the_twin_translate_to_one_result(name):
    adapter = CoopsCsvAdapter.fixture_instance(times.frozen_clock())
    assert _dump(adapter.to_cdm(_twin(name))) == _translate(name)


def test_the_json_form_reads_the_same_from_its_octets_and_from_its_document():
    adapter = CoopsCsvAdapter.fixture_instance(times.frozen_clock())
    octets = (FIXTURES / "water_level_json_form.json").read_bytes()
    assert _dump(adapter.to_cdm(octets)) == _translate("water_level_json_form")


@pytest.mark.parametrize("name", CSV_CASES + JSON_CASES)
def test_the_goldens_are_the_translation(name):
    payload = json.loads((GOLDEN / f"{name}.cdm.json").read_text())
    assert payload == _translate(name)
    if name in CSV_CASES:
        assert json.loads((GOLDEN / f"{name}.parsed.cdm.json").read_text()) == payload


@pytest.mark.parametrize("name", sorted(MALFORMED_REFUSALS))
def test_each_malformed_response_is_refused_with_its_code_and_its_whole_text(name):
    code, text = MALFORMED_REFUSALS[name]
    path = MALFORMED / name
    payload = json.loads(path.read_text()) if path.suffix == ".json" else path.read_bytes()
    with pytest.raises(CoopsRefused) as raised:
        CoopsCsvAdapter.fixture_instance(times.frozen_clock()).to_cdm(payload)
    assert (raised.value.code, str(raised.value)) == (code, text)


# ================================================================== the responses, by hand


def test_one_preliminary_sample_becomes_this_event_and_the_station_this_entity():
    objects = _translate("water_level_preliminary")
    assert [o["object_kind"] for o in objects] == ["event", "event", "event", "entity"]
    site = _uuid("entity", "CO-OPS", "0000001")
    stamp = "2026-04-28T00:12:00.000Z"
    source = {
        "adapter": "coops_csv",
        "adapter_version": "1.0.0",
        "format_name": "NOAA CO-OPS data API response (datagetter)",
        "format_version": "api.tidesandcurrents.noaa.gov/api/prod, read 2026-10-14",
        "original_id": None,
        "source_hash": None,
        "synthetic": True,
        "system": "CO-OPS",
    }
    # Row 2: 2026-04-28 00:12,0.447,0.024,3,0,0,0,p — under gmt the stamp is UTC as written.
    assert objects[2] == {
        "event_id": _uuid("event", "CO-OPS", f"0000001/water_level/MLLW/metric/6/{stamp}"),
        "event_type": "ENVIRONMENTAL_OBSERVATION",
        "geometry": None,
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
                    "header_lines": 1,
                    "kind": "table",
                    "row": 2,
                },
                "product_class": "observation",
                "product_version": None,
                "quality_flags": _flags("O F R L", (3, 0, 0, 0), "p"),
                "quality_flags_basis": None,
                "readings": [
                    _reading("Water Level", 0.447, datum=DATUM),
                    _reading("Sigma", 0.024),
                ],
                "station_id": "0000001",
                "station_namespace": "CO-OPS station identifier",
                "time": {
                    "forecast_offset": None,
                    "reference_time": None,
                    "reference_time_significance": None,
                    "source_time_system": {
                        "basis": GMT_BASIS,
                        "name": "gmt",
                        "stated_by": "caller",
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
                "form": "csv",
                "header": WATER_LEVEL,
                "request": FIXTURE_REQUEST,
                "row": ["2026-04-28 00:12", "0.447", "0.024", "3", "0", "0", "0", "p"],
            },
            "namespace": "NOAA CO-OPS data API response (datagetter)",
        },
        "schema_version": "3.2.0",
        "severity": "INFO",
        "source": {
            **source,
            "observed_at": stamp,
            "record_index": 2,
            "transformations": [T_GMT, T_NUMBER, T_FLAGS],
        },
        "source_ids": [
            {"external_id": f"0000001/water_level/MLLW/metric/6/{stamp}", "system": "CO-OPS"}
        ],
        "status": None,
        "validity": {
            "effective": {"end": stamp, "start": stamp},
            "observed_at": None,
            "valid_from": None,
            "valid_to": None,
        },
    }
    # The CSV form states no position and the fixture context supplies no table: none.
    assert objects[3] == {
        "affiliation": "UNKNOWN",
        "attributes": {
            "position_basis": "no position: the payload states none and no station table was "
            "supplied",
            "site_class": "tide_gauge",
            "valid_from_basis": "the earliest sample the response states",
        },
        "confidence": None,
        "entity_id": site,
        "entity_type": "SENSOR",
        "integrity": None,
        "kinematics": None,
        "object_kind": "entity",
        "ontology_types": [],
        "position": None,
        "quality": None,
        # The CSV form's header line is what the response states about itself.
        "residual": {
            "data": {"header": WATER_LEVEL},
            "namespace": "NOAA CO-OPS data API response (datagetter)",
        },
        "schema_version": "3.2.0",
        "source": {
            **source,
            "observed_at": "2026-04-28T00:00:00.000Z",
            "record_index": None,
            "transformations": [T_GMT],
        },
        "source_ids": [{"external_id": "0000001", "system": "CO-OPS"}],
        "status": None,
        "symbol": None,
        "valid_from": "2026-04-28T00:00:00.000Z",
        "valid_to": None,
    }


def test_verified_samples_name_their_flags_i_f_r_t_and_negative_levels_are_values():
    assert [_short(e) for e in _events(_translate("water_level_verified"))] == [
        (
            "2026-04-27T12:00:00.000Z",
            [("Water Level", 0.215), ("Sigma", 0.011)],
            [("I", 0), ("F", 0), ("R", 0), ("T", 0), ("Quality", "v")],
        ),
        (
            "2026-04-27T12:06:00.000Z",
            [("Water Level", 0.22), ("Sigma", 0.013)],
            [("I", 1), ("F", 0), ("R", 0), ("T", 0), ("Quality", "v")],
        ),
    ]
    assert [_short(e) for e in _events(_translate("water_level_below_datum_flagged"))] == [
        (
            "2026-04-28T06:00:00.000Z",
            [("Water Level", -0.118), ("Sigma", 0.03)],
            [("O", 0), ("F", 1), ("R", 0), ("L", 0), ("Quality", "p")],
        ),
        (
            "2026-04-28T06:06:00.000Z",
            [("Water Level", -0.142), ("Sigma", 0.045)],
            [("O", 0), ("F", 0), ("R", 1), ("L", 1), ("Quality", "p")],
        ),
        (
            "2026-04-28T06:12:00.000Z",
            [("Water Level", -0.15), ("Sigma", 0.02)],
            [("I", 0), ("F", 0), ("R", 0), ("T", 0), ("Quality", "v")],
        ),
    ]


def test_the_json_form_states_the_station_and_its_position_as_strings():
    objects = _translate("water_level_json_form")
    assert [_short(e) for e in _events(objects)] == [
        (
            "2026-04-28T03:00:00.000Z",
            [("Water Level", 0.512), ("Sigma", 0.018)],
            [("O", 0), ("F", 0), ("R", 0), ("L", 0), ("Quality", "p")],
        ),
        (
            "2026-04-28T03:06:00.000Z",
            [("Water Level", 0.508), ("Sigma", 0.016)],
            [("O", 1), ("F", 0), ("R", 0), ("L", 0), ("Quality", "p")],
        ),
    ]
    entity = objects[-1]
    assert (entity["position"]["lat"], entity["position"]["lon"]) == (57.0213, 21.0877)
    assert entity["attributes"]["position_basis"] == (
        "the JSON response's metadata lat and lon, decimal-degree strings read as numbers"
    )
    assert entity["residual"]["data"] == {
        "metadata": {
            "id": "0000001",
            "lat": "57.0213",
            "lon": "21.0877",
            "name": "EX synthetic gauge",
        }
    }
    assert [e["geometry"] for e in _events(objects)] == [
        {"coordinates": [21.0877, 57.0213], "type": "Point"}
    ] * 2
    assert [e["payload"]["observation"]["locator"]["header_lines"] for e in _events(objects)] == [
        0,
        0,
    ]
    assert _events(objects)[1]["residual"]["data"]["record"] == {
        "f": "1,0,0,0",
        "q": "p",
        "s": "0.016",
        "t": "2026-04-28 03:06",
        "v": "0.508",
    }


# ================================================================== the request decides time


def test_lst_is_read_with_the_declared_offset_five_hours_from_gmt():
    """The trap the brief names: one stamp, two zones. Under gmt `2026-04-28 00:00` is 00:00Z;
    under lst with lst_offset -05:00 it is local standard time five hours behind UTC, so 05:00Z;
    under +02:00 it is two hours ahead, so 22:00Z the day before."""
    octets = (FIXTURES / "water_level_preliminary.csv").read_bytes()
    gmt = _events(_dump(_adapter().to_cdm(octets)))
    lst = _events(_dump(_adapter(_request(time_zone="lst", lst_offset="-05:00")).to_cdm(octets)))
    east = _events(_dump(_adapter(_request(time_zone="lst", lst_offset="+02:00")).to_cdm(octets)))
    assert [e["observed_at"] for e in gmt] == [
        "2026-04-28T00:00:00.000Z",
        "2026-04-28T00:06:00.000Z",
        "2026-04-28T00:12:00.000Z",
    ]
    assert [e["observed_at"] for e in lst] == [
        "2026-04-28T05:00:00.000Z",
        "2026-04-28T05:06:00.000Z",
        "2026-04-28T05:12:00.000Z",
    ]
    assert [e["observed_at"] for e in east] == [
        "2026-04-27T22:00:00.000Z",
        "2026-04-27T22:06:00.000Z",
        "2026-04-27T22:12:00.000Z",
    ]
    assert lst[0]["validity"]["effective"] == {
        "end": "2026-04-28T05:00:00.000Z",
        "start": "2026-04-28T05:00:00.000Z",
    }
    assert lst[0]["source"]["observed_at"] == "2026-04-28T05:00:00.000Z"
    assert lst[0]["source"]["transformations"] == [T_LST, T_NUMBER, T_FLAGS]
    assert lst[0]["payload"]["observation"]["time"]["source_time_system"] == {
        "basis": "CoopsRequest.time_zone lst with the caller's lst_offset -05:00, the request "
        "parameter the response does not echo (research-station-text F05): each stamp is local "
        "standard time",
        "name": "lst",
        "stated_by": "caller",
    }
    assert lst[0]["residual"]["data"]["request"]["lst_offset"] == "-05:00"
    # The id is the UTC instant's, so one sample requested in two zones is one Event.
    assert lst[0]["event_id"] == _uuid(
        "event", "CO-OPS", "0000001/water_level/MLLW/metric/6/2026-04-28T05:00:00.000Z"
    )


REQUEST_REFUSALS = [
    ("lst_ldt", {"time_zone": "lst_ldt"}, "time_zone lst_ldt is refused by name: local time with daylight saving needs the switch dates of a time-zone database, which this package does not read (DECISIONS L-11)"),
    ("no zone", {"time_zone": None}, "the request states no time_zone: a CO-OPS stamp carries no zone, and read without one it would be taken as UTC"),
    ("an unknown zone", {"time_zone": "utc"}, "time_zone is gmt or lst"),
    ("lst without its offset", {"time_zone": "lst"}, "an lst request states its standard-time offset as lst_offset, +HH:MM or -HH:MM within 14 hours"),
    ("an offset past 14 hours", {"time_zone": "lst", "lst_offset": "-14:30"}, "an lst request states its standard-time offset as lst_offset, +HH:MM or -HH:MM within 14 hours"),
    ("an offset in hours only", {"time_zone": "lst", "lst_offset": "-5"}, "an lst request states its standard-time offset as lst_offset, +HH:MM or -HH:MM within 14 hours"),
    ("minute 60", {"time_zone": "lst", "lst_offset": "+01:60"}, "an lst request states its standard-time offset as lst_offset, +HH:MM or -HH:MM within 14 hours"),
    ("an offset under gmt", {"lst_offset": "-05:00"}, "lst_offset is stated with time_zone lst, and only then"),
    ("a six-digit station", {"station": "000001"}, "station is the seven-digit CO-OPS station identifier"),
    ("a numeric station", {"station": 1}, "station is the seven-digit CO-OPS station identifier"),
    ("another product", {"product": "predictions"}, "product is water_level, air_pressure or wind"),
    ("another unit system", {"units": "imperial"}, "units is metric or english"),
    ("no datum for water level", {"datum": None}, "a water_level request states one of the API's datum names"),
    ("a datum not the API's", {"datum": "NAVD88"}, "a water_level request states one of the API's datum names"),
    ("a datum for air pressure", {"product": "air_pressure"}, "only a water_level request states a datum"),
    ("an interval not the API's", {"interval": "60"}, "interval is 6 or h, or absent for the API's default"),
]  # fmt: skip


@pytest.mark.parametrize("label,over,text", REQUEST_REFUSALS, ids=[c[0] for c in REQUEST_REFUSALS])
def test_a_request_the_api_cannot_have_answered_is_refused(label, over, text):
    with pytest.raises(ValueError) as raised:
        _request(**over)
    assert str(raised.value) == text


def test_the_request_is_required_and_is_built_from_the_hosts_pairs():
    with pytest.raises(TypeError):
        CoopsCsvAdapter()
    with pytest.raises(ValueError, match="request is a CoopsRequest"):
        CoopsCsvAdapter(request=FIXTURE_REQUEST)
    pairs = (("station", "0000001"), ("product", "wind"), ("units", "english"),
             ("time_zone", "lst"), ("lst_offset", "-05:00"), ("interval", "h"))  # fmt: skip
    assert CoopsRequest.from_pairs(pairs).as_dict() == {
        "datum": None,
        "interval": "h",
        "lst_offset": "-05:00",
        "product": "wind",
        "station": "0000001",
        "time_zone": "lst",
        "units": "english",
    }
    with pytest.raises(ValueError, match="a request key is not a CoopsRequest field"):
        CoopsRequest.from_pairs((*pairs, ("begin_date", "20260428")))
    with pytest.raises(ValueError, match="time_zone lst_ldt is refused by name"):
        CoopsRequest.from_pairs((("station", "0000001"), ("product", "wind"),
                                 ("units", "metric"), ("time_zone", "lst_ldt")))  # fmt: skip


# ================================================================== the other products


def test_air_pressure_keeps_the_header_s_trailing_space_and_reads_x_n_r():
    request = _request(product="air_pressure", datum=None, units="english")
    text = AIR_PRESSURE + "\n2026-04-28 00:00,1012.4,0,1,0\n"
    events = _events(_dump(_adapter(request).to_cdm(text.encode())))
    observation = events[0]["payload"]["observation"]
    assert observation["readings"] == [
        {
            "absence": None,
            "datum": None,
            "level": None,
            "measurement": {"unit": "english", "unit_namespace": UNITS_NS, "value": 1012.4},
            "name": "Pressure",
            "namespace": "CO-OPS datagetter air_pressure",
        }
    ]
    assert observation["quality_flags"] == [
        _flag("X", 0, "Pressure"),
        _flag("N", 1, "Pressure"),
        _flag("R", 0, "Pressure"),
    ]
    assert events[0]["event_id"] == _uuid(
        "event", "CO-OPS", "0000001/air_pressure/-/english/6/2026-04-28T00:00:00.000Z"
    )
    # The same header without its trailing space is no product's header.
    stripped = AIR_PRESSURE.rstrip() + "\n2026-04-28 00:00,1012.4,0,1,0\n"
    assert str(_refusal(stripped.encode(), request)) == (
        "unknown-header: the CSV header is not the request's product's header"
    )
    assert str(_refusal(_payload("water_level_json_form"), request)) == (
        "json-form-not-read: the JSON form is read for water_level only; the record keys of the "
        "other products are not in the design record"
    )


def test_wind_reads_both_direction_columns_by_position():
    request = _request(product="wind", datum=None)
    text = WIND + "\n2026-04-28 00:00,4.2,135.0,SE,6.1,0,1\n"
    events = _events(_dump(_adapter(request).to_cdm(text.encode())))
    observation = events[0]["payload"]["observation"]
    namespace = (
        "the CO-OPS response field definitions (api/prod/responseHelp.html): wind Direction in "
        "degrees (research-station-text F06)"
    )
    assert [
        (r["name"], r["measurement"]["value"], r["measurement"]["unit"], r["namespace"])
        for r in observation["readings"]
    ] == [
        ("Speed", 4.2, "metric", "CO-OPS datagetter wind"),
        ("Direction", 135.0, "degrees", "CO-OPS datagetter wind"),
        ("Gust", 6.1, "metric", "CO-OPS datagetter wind"),
    ]
    assert observation["readings"][1]["measurement"]["unit_namespace"] == namespace
    assert observation["quality_flags"] == [_flag("X", 0, "record"), _flag("R", 1, "record")]
    # The compass point is text and stays in the residual row, where both columns sit.
    assert events[0]["residual"]["data"]["row"] == [
        "2026-04-28 00:00", "4.2", "135.0", "SE", "6.1", "0", "1",
    ]  # fmt: skip


def test_a_csv_station_takes_its_position_from_the_caller_s_table():
    table = StationTable(
        name="gauges", basis="a synthetic table", rows=[{"station_id": "0000001", "lat": 57.5, "lon": 22.0}]
    )  # fmt: skip
    objects = _dump(_adapter(station_table=table).to_cdm(_payload("water_level_verified")))
    assert objects[-1]["position"]["lat"] == 57.5
    assert objects[-1]["attributes"]["position_basis"] == "station table gauges: a synthetic table"
    assert {json.dumps(e["geometry"]) for e in _events(objects)} == {
        '{"type": "Point", "coordinates": [22.0, 57.5]}'
    }


def test_the_injected_digests_reach_every_stamp_and_every_locator():
    digest, frame = "c" * 64, "d" * 64
    adapter = _adapter(source_hash={"algorithm": "sha256", "value": digest}, frame_sha256=frame)
    objects = _dump(adapter.to_cdm(_payload("water_level_preliminary")))
    assert [o["source"]["source_hash"] for o in objects] == [
        {"algorithm": "sha256", "value": digest}
    ] * 4
    assert [e["payload"]["observation"]["locator"]["frame_sha256"] for e in _events(objects)] == [
        frame
    ] * 3
    for bad in (
        {"source_hash": {"algorithm": "sha1", "value": digest}},
        {"frame_sha256": "D" * 64},
        {"station_table": {"rows": []}},
    ):
        with pytest.raises(ValueError):
            _adapter(**bad)


def test_the_receipt_clock_reaches_received_at_and_nothing_else():
    later = CoopsCsvAdapter.fixture_instance(
        times.frozen_clock(dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc))
    )
    for name in CSV_CASES + JSON_CASES:
        for x, y in zip(_translate(name), _translate(name, later)):
            if x["object_kind"] == "event":
                assert (x["received_at"], y["received_at"]) == (FROZEN, "2026-05-01T00:00:00.000Z")
                x, y = {**x, "received_at": None}, {**y, "received_at": None}
            assert x == y


# ================================================================== the refusals


ROW = "2026-04-28 00:00,0.412,0.021,0,0,0,0,p"
METADATA = {"id": "0000001", "name": "EX", "lat": "57.0", "lon": "21.0"}
RECORD = {"t": "2026-04-28 00:00", "v": "0.412", "s": "0.021", "f": "0,0,0,0", "q": "p"}


def _csv(*rows: str) -> bytes:
    return (WATER_LEVEL + "\n" + "".join(r + "\n" for r in rows)).encode()


PAYLOAD_REFUSALS = [
    ("a quoted field left open", _csv('2026-04-28 00:00,"0.412,0.021,0,0,0,0,p'), "bad-csv-row: line 2 is not one CSV record"),
    ("30 February", _csv(ROW.replace("04-28", "02-30")), "bad-time: row 0: the stamp names no instant"),
    ("a stamp with a zone", _csv(ROW.replace("00:00,", "00:00Z,", 1)), "bad-time: row 0: the stamp is not YYYY-MM-DD HH:MM"),
    ("a flag that is not an integer", _csv(ROW.replace(",0,0,0,0,", ",0,1.0,0,0,")), "bad-flag: row 0, flag F is not a non-negative integer"),
    ("a negative flag", _csv(ROW.replace(",0,0,0,0,", ",-1,0,0,0,")), "bad-flag: row 0, flag O is not a non-negative integer"),
    ("a sigma that is not a number", _csv(ROW.replace("0.021", "n/a")), "not-a-number: row 0, Sigma is not a decimal number"),
    ("two samples at one instant", _csv(ROW, ROW), "repeated-instant: sample 1 states the instant of sample 0"),
    ("no sample", _csv(), "no-data-row: the response holds no sample"),
    ("JSON with a key twice", b'{"metadata":{},"metadata":{},"data":[]}', "repeated-key: a JSON object names one key twice"),
    ("JSON with NaN", b'{"metadata":NaN,"data":[]}', "not-json: the JSON text holds NaN or an infinity"),
    ("JSON that does not parse", b'{"metadata":', "not-json: the response opens with { and is not JSON"),
    ("JSON with a byte-order mark", b"\xef\xbb\xbf" + json.dumps({"metadata": METADATA, "data": [RECORD]}).encode(), "byte-order-mark: the file opens with a byte-order mark"),
    ("JSON not UTF-8", b'{"metadata":"\xff"}', "not-utf8: the response is not UTF-8 text"),
    ("a JSON array", b"[]\n", "unknown-header: the CSV header is not the request's product's header"),
    ("metadata with another key", {"metadata": {**METADATA, "x": "1"}, "data": [RECORD]}, "not-a-response: metadata holds exactly the keys id, name, lat and lon"),
    ("a record with another key", {"metadata": METADATA, "data": [{**RECORD, "x": "1"}]}, "not-a-response: data[0] holds exactly the keys t, v, s, f and q"),
    ("a value that is a number", {"metadata": METADATA, "data": [{**RECORD, "v": 0.412}]}, "not-text: data[0].v is not text a response could hold"),
    ("a lone surrogate", {"metadata": {**METADATA, "name": "\ud800"}, "data": [RECORD]}, "not-text: metadata.name is not text a response could hold"),
    ("data not a list", {"metadata": METADATA, "data": {}}, "not-a-response: data is not a list"),
    ("no record", {"metadata": METADATA, "data": []}, "no-data-row: the response holds no sample"),
    ("a latitude past 90", {"metadata": {**METADATA, "lat": "90.5"}, "data": [RECORD]}, "bad-position: metadata.lat is not decimal degrees within +/-90"),
    ("a longitude in words", {"metadata": {**METADATA, "lon": "21E"}, "data": [RECORD]}, "bad-position: metadata.lon is not decimal degrees within +/-180"),
    ("three flags", {"metadata": METADATA, "data": [{**RECORD, "f": "0,0,0"}]}, "bad-flag: data[0].f is not four comma-separated integers"),
    ("a quality level x", {"metadata": METADATA, "data": [{**RECORD, "q": "x"}]}, "bad-quality: data[0].q is not p or v"),
    ("a twin with another key", {"form": "csv", "header": WATER_LEVEL, "rows": [], "x": 1}, "not-a-twin: a CSV twin holds exactly form 'csv', header and rows"),
    ("a twin row that is text", {"form": "csv", "header": WATER_LEVEL, "rows": [ROW]}, "not-a-twin: rows[0] is not a list of fields"),
    ("text", ROW, "unsupported-input: a response is handed over as its octets, its parsed JSON document or its CSV twin; text and other types are not taken"),
]  # fmt: skip


@pytest.mark.parametrize(
    "label,payload,text", PAYLOAD_REFUSALS, ids=[c[0] for c in PAYLOAD_REFUSALS]
)
def test_a_response_this_module_cannot_read_is_refused_by_name(label, payload, text):
    assert str(_refusal(payload)) == text


NINES = "9" * 400
DIGITS = "1" * 5000
RANGE_REFUSALS = [
    ("a water level past the double range", _csv(ROW.replace("0.412", NINES + ".0")), "number-out-of-range: row 0, Water Level lies outside what a binary double holds"),
    ("a negative water level past the range", _csv(ROW.replace("0.412", "-" + NINES + ".5")), "number-out-of-range: row 0, Water Level lies outside what a binary double holds"),
    ("a sigma that reads as zero", _csv(ROW.replace("0.021", "0." + "0" * 400 + "1")), "number-out-of-range: row 0, Sigma lies outside what a binary double holds"),
    ("a CSV flag of 5000 digits", _csv(ROW.replace(",0,0,0,0,", f",0,{DIGITS},0,0,")), "flag-out-of-range: row 0, flag F is an integer no binary double holds"),
    ("a CSV flag of 310 digits", _csv(ROW.replace(",0,0,0,0,", ",1" + "0" * 309 + ",0,0,0,")), "flag-out-of-range: row 0, flag O is an integer no binary double holds"),
    ("a JSON value past the range", {"metadata": METADATA, "data": [{**RECORD, "v": NINES + ".0"}]}, "number-out-of-range: data[0].v lies outside what a binary double holds"),
    ("a JSON flag of 5000 digits", {"metadata": METADATA, "data": [{**RECORD, "f": f"0,0,0,{DIGITS}"}]}, "flag-out-of-range: data[0].f, flag L is an integer no binary double holds"),
    ("a JSON integer of 5000 digits", b'{"metadata":{"id":"0000001","name":"EX","lat":' + DIGITS.encode() + b',"lon":"21.0"},"data":[]}', "number-out-of-range: the JSON text holds an integer no binary double holds"),
    ("a negative JSON integer of 310 digits", b'{"metadata":-1' + b"0" * 309 + b',"data":[]}', "number-out-of-range: the JSON text holds an integer no binary double holds"),
    ("a latitude that reads as zero", {"metadata": {**METADATA, "lat": "0." + "0" * 400 + "1"}, "data": [RECORD]}, "bad-position: metadata.lat is not decimal degrees within +/-90"),
]  # fmt: skip


@pytest.mark.parametrize("label,payload,text", RANGE_REFUSALS, ids=[c[0] for c in RANGE_REFUSALS])
def test_a_number_or_a_flag_no_double_holds_is_this_adapter_s_refusal(label, payload, text):
    refusal = _refusal(payload)
    assert (type(refusal), refusal.code, str(refusal)) == (CoopsRefused, text.split(":")[0], text)


def test_a_json_integer_a_double_holds_still_parses_and_is_refused_as_not_text():
    """The digit bound refuses no integer a double holds: 309 digits reach the key-set checks."""
    big = b"1" + b"0" * 308
    payload = b'{"metadata":{"id":"0000001","name":"EX","lat":' + big + b',"lon":"21.0"},"data":[]}'
    assert str(_refusal(payload)) == "not-text: metadata.lat is not text a response could hold"


def test_one_sample_under_another_datum_units_or_interval_is_another_event():
    """A store keyed by event_id must not overwrite one reading with another: the datum, the
    units and the interval change the value, so each is in the identity; the zone does not (the
    instant is UTC), so one sample requested in two zones stays one Event."""
    octets = (FIXTURES / "water_level_preliminary.csv").read_bytes()
    ids = {}
    for label, request in {
        "fixture": _request(interval="6"),
        "default interval": _request(),
        "NAVD": _request(datum="NAVD", interval="6"),
        "english": _request(units="english", interval="6"),
        "hourly": _request(interval="h"),
    }.items():
        ids[label] = _events(_dump(_adapter(request).to_cdm(octets)))[0]["source_ids"][0]
    stamp = "2026-04-28T00:00:00.000Z"
    assert {label: sid["external_id"] for label, sid in ids.items()} == {
        "fixture": f"0000001/water_level/MLLW/metric/6/{stamp}",
        "default interval": f"0000001/water_level/MLLW/metric/6/{stamp}",
        "NAVD": f"0000001/water_level/NAVD/metric/6/{stamp}",
        "english": f"0000001/water_level/MLLW/english/6/{stamp}",
        "hourly": f"0000001/water_level/MLLW/metric/h/{stamp}",
    }


def test_an_lst_stamp_no_utc_instant_holds_is_refused_and_never_overflows():
    request = _request(time_zone="lst", lst_offset="+05:00")
    payload = _csv(ROW.replace("2026-04-28", "0001-01-01"))
    assert str(_refusal(payload, request)) == (
        "bad-time: row 0: the stamp leaves the years 1 to 9999"
    )


def test_a_refusal_is_a_value_error_that_survives_pickling():
    refusal = _refusal((MALFORMED / "blank_value.csv").read_bytes())
    again = pickle.loads(pickle.dumps(refusal))
    assert isinstance(again, ValueError)
    assert (type(again), again.code, str(again)) == (
        CoopsRefused,
        "blank-value",
        "blank-value: row 0, field 1 is blank",
    )


def test_a_twin_past_the_depth_bound_is_refused_before_decode():
    node: list = []
    for _ in range(63):
        node = [node]
    with pytest.raises(InputTooDeep, match="max_depth = 64"):
        _adapter().to_cdm({"form": "csv", "header": WATER_LEVEL, "rows": node})


def test_no_refusal_quotes_a_value_from_the_response():
    secret = "8765.4321"
    for payload in (
        _csv(ROW.replace("0.412", secret + "x")),
        {"metadata": {**METADATA, "id": secret[:7]}, "data": [RECORD]},
        {"metadata": {**METADATA, "lat": secret}, "data": [RECORD]},
    ):
        assert secret[:7] not in str(_refusal(payload))
