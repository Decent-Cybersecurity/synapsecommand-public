"""`frost_observations`, #33 in the ordinal table: one Frost response -> Events, station Entities.

One test per claim in the module's docstring, refusals included. Every expectation is a literal
written from the fixture's own document (`spec/build_fixtures.py`) and Frost's documented time
rules, never read back from the adapter. Every payload is synthetic: stations in the SN0000x block,
positions (in the adapter's fixture station table) inside CONTRIBUTING.md's Baltic rectangle.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/frost_observations/` and
runs the packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import pathlib
import pickle
import time

import pytest

import synapse_cdm
from synapse_cdm import harness, ids, times
from synapse_cdm.adapter import InputTooDeep, InputTooLarge, discover
from synapse_cdm.adapters import frost_observations as frost
from synapse_cdm.adapters.frost_observations import FrostObservationsAdapter, FrostRefused
from synapse_cdm.manifest import ClaimStatus, LicenseClass, LimitKind, UnknownFields
from synapse_cdm.observation_contracts import contract_of
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "frost_observations"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
FROZEN = times.frozen_clock()
#: The five pairs: `<name>.jsonld` (octets) beside `<name>.parsed.json`.
CASES = sorted(p.name.removesuffix(".jsonld") for p in FIXTURES.glob("*.jsonld"))


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text())


def octets(name: str) -> bytes:
    return (FIXTURES / f"{name}.jsonld").read_bytes()


def adapter(**kwargs) -> FrostObservationsAdapter:
    # The station table by default; the element table only where a test passes it.
    kwargs.setdefault("station_table", frost.FIXTURE_STATIONS)
    return FrostObservationsAdapter(clock=FROZEN, **kwargs)


def translate(document, **kwargs):
    return adapter(**kwargs).to_cdm(document)


def dumped(objects):
    return [o.model_dump(mode="json") for o in objects]


def events(objects):
    return [o for o in objects if o.object_kind == "event"]


def entities(objects):
    return [o for o in objects if o.object_kind == "entity"]


def minimal(**observation) -> dict:
    """A one-item response at a non-midnight hour, the observation overridable."""
    base = {
        "elementId": "air_temperature",
        "value": 1.5,
        "unit": "degC",
        "timeOffset": "PT0H",
        "timeResolution": "PT1H",
        "timeSeriesId": 0,
    }
    base.update(observation)
    base = {k: v for k, v in base.items() if v is not _DROP}
    return {
        "@type": "ObservationResponse",
        "apiVersion": "v0",
        "license": "https://creativecommons.org/licenses/by/3.0/no/",
        "createdAt": "2026-10-20T07:00:00.000Z",
        "data": [
            {
                "sourceId": "SN00001:0",
                "referenceTime": "2026-10-19T05:00:00.000Z",
                "observations": [base],
            }
        ],
    }


_DROP = object()


def refused(document, code: str, **kwargs) -> FrostRefused:
    with pytest.raises(FrostRefused) as caught:
        translate(document, **kwargs)
    assert caught.value.code == code, str(caught.value)
    return caught.value


# -- the gate ------------------------------------------------------------------------------------


def test_the_adapter_is_registered_and_claims_its_ordinal():
    cls = discover()["frost_observations"]
    assert cls is FrostObservationsAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "frost_observations",
        "1.0.0",
        "ingest",
        "FROST",
    )
    assert frost.__doc__.splitlines()[0] == (
        "`frost_observations`, #33 in the ordinal table: MET Frost observations -> CDM, "
        "ingest only."
    )


def test_the_harness_passes_every_fixture_on_every_column():
    report = harness.run(FrostObservationsAdapter.fixture_instance(clock=FROZEN), FIXTURES)
    assert report["failed"] == 0 and report["passed"] == 10
    for result in report["results"]:
        checks = result["checks"]
        for column in ("translate", "schema", "provenance", "golden"):
            assert checks[column] == "PASS", (result["fixture"], column, result["problems"])
        assert checks["roundtrip"] == "SKIP"  # ingest-only: inapplicable, never passed
        if result["fixture"].endswith(".parsed.json"):
            assert checks["lossless"] == "PASS", (result["fixture"], result["problems"])
            assert result["preservation"]["basis"] == "ledger"
            assert result["preservation"]["counts"]["LOST"] == 0
        else:
            assert checks["lossless"] == "SKIP"  # octets: the twin carries the column


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []  # provenance_problems covers malformed/ too
    assert len(CASES) == 5


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_every_station_and_position_follows_the_identifier_convention(name):
    for item in load(name)["data"]:
        station = item["sourceId"].split(":")[0]
        assert support.station_id_problems(station, "frost-station") == []
    for row in frost.FIXTURE_STATIONS.rows:
        assert support.station_id_problems(row.station_id, "frost-station") == []
    assert support.positions_outside_the_rectangle(dumped(translate(load(name)))) == []


@pytest.mark.parametrize("name", CASES)
def test_the_parse_of_each_payload_is_its_twin_and_both_translate_to_one_result(name):
    assert json.loads(octets(name).decode("utf-8")) == load(name)
    adapter = FrostObservationsAdapter.fixture_instance(clock=FROZEN)
    assert dumped(adapter.to_cdm(octets(name))) == dumped(adapter.to_cdm(load(name)))
    assert json.loads((GOLDEN / f"{name}.cdm.json").read_text()) == json.loads(
        (GOLDEN / f"{name}.parsed.cdm.json").read_text()
    )


def test_every_malformed_fixture_is_refused_by_the_adapter():
    paths = harness.select_fixtures(FIXTURES / "malformed")
    assert len(paths) >= 10
    for path in paths:
        raw = harness.load_raw(path)
        with pytest.raises(FrostRefused):
            FrostObservationsAdapter.fixture_instance(clock=FROZEN).to_cdm(raw)


# -- what one document becomes -------------------------------------------------------------------


def test_one_event_per_item_in_data_order_then_one_entity_per_station_in_first_seen_order():
    document = load("station_missing_parallel_sensors")
    objects = translate(document)
    kinds = [o.object_kind for o in objects]
    assert kinds == ["event"] * 4 + ["entity"] * 3
    assert [e.source.record_index for e in events(objects)] == [0, 1, 2, 3]
    assert [e.source_ids[0].external_id for e in entities(objects)] == [
        "SN00009",
        "SN00001",
        "SN00002",
    ]
    for event in events(objects):
        assert event.event_type.value == "ENVIRONMENTAL_OBSERVATION"
        assert contract_of(event).contract == "point-observation/1"
    assert all(e.entity_type.value == "SENSOR" for e in entities(objects))


def test_octets_and_the_parsed_dict_translate_identically():
    document = load("two_stations_hourly")
    assert dumped(translate(document)) == dumped(translate(octets("two_stations_hourly")))


def test_element_id_value_and_unit_are_verbatim_with_the_element_table_namespace():
    objects = translate(load("two_stations_hourly"))
    readings = contract_of(objects[0]).readings
    assert [r.name for r in readings][4] == "sum(precipitation_amount PT1H)"
    precipitation = readings[4]
    assert precipitation.measurement.value == 0.4
    assert precipitation.measurement.unit == "mm"
    assert "elementtable" in precipitation.measurement.unit_namespace
    assert readings[2].measurement.unit == "degrees"
    assert readings[0].namespace.startswith(frost.ELEMENT_NAMESPACE)


def test_level_is_carried_as_stated_and_never_becomes_alt_m():
    objects = translate(load("two_stations_hourly"))
    readings = contract_of(objects[0]).readings
    level = readings[0].level
    assert (level.type, level.value, level.unit) == ("height_above_ground", 2.0, "m")
    assert readings[1].level.value == 10.0
    for entity in entities(objects):
        assert entity.position.alt_m is None and entity.position.vertical is None


def test_an_observation_without_level_has_a_reading_without_one():
    objects = translate(load("quality_codes_no_level_unknown_keys"))
    readings = contract_of(objects[0]).readings
    assert readings[0].name == "surface_snow_thickness" and readings[0].level is None
    assert readings[2].name == "sum(precipitation_amount PT1H)" and readings[2].level is None


def test_the_reading_namespace_states_the_series_and_keeps_two_series_of_one_element_apart():
    objects = translate(load("station_missing_parallel_sensors"))
    readings = contract_of(objects[1]).readings
    assert [r.name for r in readings] == ["air_temperature"] * 3
    assert readings[0].namespace.endswith("timeOffset=PT0H, timeResolution=PT1H, timeSeriesId=0")
    assert readings[1].namespace.endswith("timeOffset=PT6H, timeResolution=PT1H, timeSeriesId=1")
    assert readings[0].namespace == readings[2].namespace  # told apart by level
    assert readings[0].level != readings[2].level


def test_quality_flags_are_typed_and_verbatim_and_name_their_reading():
    objects = translate(load("quality_codes_no_level_unknown_keys"))
    flags = contract_of(objects[0]).quality_flags
    codes = [(f.value, f.applies_to) for f in flags if f.name == "qualityCode"]
    assert codes == [(2, "readings[0]"), (5, "readings[1]"), (7, "readings[2]")]
    assert {f.name for f in flags} == {"qualityCode", "performanceCategory", "exposureCategory"}
    assert all("dataclarifications" in f.namespace for f in flags)
    category = next(f for f in flags if f.name == "exposureCategory")
    assert category.value == "2" and isinstance(category.value, str)
    assert objects[0].quality is None  # never interpreted into a confidence


def test_an_item_with_no_flag_states_the_absence_with_its_basis():
    objects = translate(load("quality_codes_no_level_unknown_keys"))
    contract = contract_of(objects[2])
    assert contract.quality_flags == []
    assert contract.quality_flags_basis == frost.NO_FLAGS_BASIS
    partial = contract_of(objects[1])
    assert [(f.name, f.applies_to) for f in partial.quality_flags] == [
        ("qualityCode", "readings[1]")
    ]


def test_the_residual_holds_the_header_and_the_item_verbatim_with_unknown_keys():
    document = load("quality_codes_no_level_unknown_keys")
    objects = translate(document)
    header = {k: v for k, v in document.items() if k != "data"}
    for index, event in enumerate(events(objects)):
        assert event.residual.namespace == frost.FORMAT_NAME
        data = event.residual.data
        assert data[frost.DATA_ITEM_KEY] == document["data"][index]
        assert {k: v for k, v in data.items() if k != frost.DATA_ITEM_KEY} == header
    first = objects[0].residual.data
    assert first["syntheticTopLevelKey"] == {"origin": "an unknown header block", "version": 2}
    assert first["data_item"]["syntheticItemNote"] == "an item key Frost does not document"
    assert first["data_item"]["observations"][1]["syntheticObservationKey"]["count"] == 3
    assert first["license"] == "https://creativecommons.org/licenses/by/3.0/no/"


def test_created_at_is_a_product_version_and_never_an_at_time():
    document = load("two_stations_hourly")
    objects = translate(document)
    created = document["createdAt"]
    for event in events(objects):
        assert contract_of(event).product_version.production_time_verbatim == created

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "residual":
                    continue
                yield from walk(v, k)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v, key)
        else:
            yield key, node

    for obj in dumped(objects):
        for key, value in walk(obj):
            if key.endswith(("_at", "_from", "_to")):
                assert value != created, key


def test_a_response_without_created_at_has_no_product_version():
    document = minimal()
    del document["createdAt"]
    assert contract_of(translate(document)[0]).product_version is None


# -- time ----------------------------------------------------------------------------------------


def test_a_referencetime_not_at_midnight_is_the_observation_instant():
    objects = translate(load("quality_codes_no_level_unknown_keys"))
    event = objects[0]
    stamp = _dt.datetime(2026, 10, 19, 6, tzinfo=_dt.timezone.utc)
    assert event.observed_at == stamp
    assert event.validity.effective.start == event.validity.effective.end == stamp
    assert event.source.observed_at == stamp
    assert event.source.transformations[0] == frost.T_NOT_MIDNIGHT


def test_a_midnight_item_of_sub_daily_resolutions_is_case_1():
    objects = translate(load("two_stations_hourly"))
    event = objects[0]
    midnight = _dt.datetime(2026, 10, 19, tzinfo=_dt.timezone.utc)
    assert event.observed_at == midnight
    assert event.validity.effective.end == midnight
    assert event.source.transformations[0] == frost.T_SUB_DAILY


def test_time_offset_is_never_added():
    objects = translate(load("station_missing_parallel_sensors"))
    event = objects[1]  # holds a PT6H series at a midnight referenceTime
    assert event.observed_at == _dt.datetime(2026, 10, 19, tzinfo=_dt.timezone.utc)


def test_a_daily_resolution_at_a_non_midnight_referencetime_is_read_as_stated():
    objects = translate(load("station_missing_parallel_sensors"))
    event = objects[3]
    assert contract_of(event).readings[0].namespace.endswith("timeResolution=P1D, timeSeriesId=0")
    assert event.observed_at == _dt.datetime(2026, 10, 19, 12, 30, tzinfo=_dt.timezone.utc)
    assert event.source.transformations[0] == frost.T_NOT_MIDNIGHT


def test_the_accumulation_window_stays_in_the_element_id_and_the_validity_is_an_instant():
    objects = translate(load("two_stations_hourly"))
    effective = objects[1].validity.effective
    assert effective.start == effective.end


def midnight(**observation) -> dict:
    document = minimal(**observation)
    document["data"][0]["referenceTime"] = "2026-10-19T00:00:00.000Z"
    return document


def test_a_midnight_item_splits_into_an_instant_event_and_daily_events():
    objects = translate(load("midnight_mixed_daily"))
    ids_ = [e.source_ids[0].external_id for e in events(objects)]
    assert ids_[:3] == [
        "SN00001:0/2026-10-19T00:00:00.000Z",
        "SN00001:0/2026-10-19T00:00:00.000Z/P1D/PT0H",
        "SN00001:0/2026-10-19T00:00:00.000Z/P1D/PT6H",
    ]
    instant = contract_of(objects[0])
    assert [r.name for r in instant.readings] == [
        "air_temperature",
        "wind_speed",
        "air_pressure_at_sea_level",
        "sum(precipitation_amount PT3H)",
    ]
    assert objects[0].source.transformations[0] == frost.T_SUB_DAILY
    assert len({e.event_id for e in events(objects)}) == len(events(objects))
    for event in events(objects)[:3]:
        assert event.source.record_index == 0
        assert event.residual.data["data_item"] == load("midnight_mixed_daily")["data"][0]


def test_a_daily_value_with_offset_pt0h_covers_the_calendar_date_and_ends_its_period():
    event = translate(load("midnight_mixed_daily"))[1]
    day = _dt.datetime(2026, 10, 19, tzinfo=_dt.timezone.utc)
    assert event.validity.effective.start == day
    assert event.validity.effective.end == day + _dt.timedelta(days=1)
    assert event.observed_at == day + _dt.timedelta(days=1)
    assert event.source.observed_at == day  # the stamp as stated
    assert event.source.transformations[0] == frost.T_DAILY
    assert "Case 2.2" in frost.T_DAILY
    reading = contract_of(event).readings[0]
    assert reading.name == "surface_snow_thickness"
    assert [(f.name, f.value, f.applies_to) for f in contract_of(event).quality_flags][0] == (
        "qualityCode",
        2,
        "readings[0]",
    )


def test_a_daily_value_with_an_offset_covers_the_24_hours_ending_at_reference_plus_offset():
    event = translate(load("midnight_mixed_daily"))[2]
    end = _dt.datetime(2026, 10, 19, 6, tzinfo=_dt.timezone.utc)
    assert event.validity.effective.end == event.observed_at == end
    assert event.validity.effective.start == end - _dt.timedelta(days=1)


def test_an_item_of_only_a_daily_value_makes_only_a_daily_event():
    objects = translate(load("midnight_mixed_daily"))
    ids_ = [e.source_ids[0].external_id for e in events(objects)]
    assert "SN00003:0/2026-10-19T00:00:00.000Z/P1D/PT0H" in ids_
    assert "SN00003:0/2026-10-19T00:00:00.000Z" not in ids_


def test_a_longer_resolution_at_midnight_is_set_aside_on_the_entity_not_refused():
    objects = translate(load("midnight_mixed_daily"))
    station = next(e for e in entities(objects) if e.source_ids[0].external_id == "SN00001")
    [unresolved] = station.attributes["unresolved_observations"]
    assert unresolved["elementId"] == "mean(air_temperature P1M)"
    assert (unresolved["data_index"], unresolved["observation_index"]) == (0, 6)
    assert "Cases 2.1 to 2.5" in unresolved["reason"]
    names = [r.name for e in events(objects) for r in contract_of(e).readings]
    assert "mean(air_temperature P1M)" not in names
    # Still carried verbatim in the item's residual.
    assert objects[0].residual.data["data_item"]["observations"][6]["value"] == -4.0


@pytest.mark.parametrize(
    "observation, reason",
    [
        ({"timeResolution": _DROP}, "no timeResolution"),
        ({"timeResolution": "P1M"}, "other than P1D"),
        ({"timeResolution": "PT24H"}, "other than P1D"),
        ({"timeResolution": "P1D", "timeOffset": _DROP}, "without a timeOffset"),
        ({"timeResolution": "P1D", "timeOffset": "P1D"}, "without a timeOffset"),
    ],
)
def test_an_item_with_nothing_resolvable_is_carried_on_the_station_entity(observation, reason):
    document = midnight(**observation)
    objects = translate(document)
    assert events(objects) == []
    [station] = entities(objects)
    assert reason in station.attributes["unresolved_observations"][0]["reason"]
    assert station.residual.data["response_header"]["license"] == document["license"]
    assert station.residual.data["unresolved_items"] == [
        {"data_index": 0, "item": document["data"][0]}
    ]
    from synapse_cdm import lossless

    assert lossless.value_presence_heuristic(document, dumped(objects)) == {}


def test_no_stated_resolution_off_midnight_is_an_instant():
    objects = translate(minimal(timeResolution=_DROP))
    assert objects[0].source.transformations[0] == frost.T_NOT_MIDNIGHT


# -- units ---------------------------------------------------------------------------------------


def test_a_missing_unit_is_taken_from_the_caller_element_table_with_a_transformation():
    objects = translate(load("observation_without_unit"), element_table=frost.FIXTURE_ELEMENTS)
    event = objects[0]
    wind = contract_of(event).readings[0]
    assert (wind.name, wind.measurement.value, wind.measurement.unit) == ("wind_speed", 9.4, "m/s")
    assert frost.FIXTURE_ELEMENTS.name in wind.measurement.unit_namespace
    assert wind.level.value == 47.0
    notes = [t for t in event.source.transformations if "unit not stated" in t]
    assert len(notes) == 2 and notes[0].startswith("readings[0] (observations[0])")
    assert frost.FIXTURE_ELEMENTS.name in notes[0]
    stated = contract_of(event).readings[3]
    assert stated.measurement.unit_namespace == frost.UNIT_NAMESPACE  # a stated unit wins


def test_a_unit_neither_stated_nor_tabled_is_an_absence_and_the_value_stays_in_the_residual():
    objects = translate(load("observation_without_unit"), element_table=frost.FIXTURE_ELEMENTS)
    reading = contract_of(objects[0]).readings[2]
    assert reading.measurement is None
    assert reading.absence.cause == "unit_unknown"
    assert reading.absence.mechanism == frost.UNIT_UNKNOWN
    assert objects[0].residual.data["data_item"]["observations"][2]["value"] == 17.5


def test_without_an_element_table_every_unitless_reading_is_an_absence():
    objects = translate(load("observation_without_unit"))
    readings = contract_of(objects[0]).readings
    assert [r.absence is not None for r in readings] == [True, True, True, False]
    assert not [t for t in objects[0].source.transformations if "unit not stated" in t]


def test_element_table_from_elements_reads_id_and_unit():
    elements = {
        "data": [
            {"id": "wind_speed", "unit": "m/s", "name": "Wind speed"},
            {"id": "synthetic_no_unit"},
            {"id": "wind_speed", "unit": "m/s"},
        ]
    }
    table = frost.element_table_from_elements(elements, name="e", basis="synthetic elements")
    assert table.unit_of("wind_speed") == "m/s" and table.unit_of("synthetic_no_unit") is None
    with pytest.raises(FrostRefused):
        frost.element_table_from_elements(
            {"data": [{"id": "a", "unit": "m"}, {"id": "a", "unit": "km"}]}, name="e", basis="b"
        )
    with pytest.raises(FrostRefused):
        frost.element_table_from_elements({"data": [{"id": "a"}]}, name="e", basis="b")


def test_the_element_table_must_be_an_element_table_and_is_frozen():
    with pytest.raises(ValueError):
        FrostObservationsAdapter(element_table={"wind_speed": "m/s"})
    source = {"wind_speed": "m/s"}
    table = frost.ElementTable(name="e", basis="synthetic", units=source)
    source["wind_speed"] = "km/h"
    assert table.unit_of("wind_speed") == "m/s"
    with pytest.raises(ValueError):
        frost.ElementTable(name="e", basis="b", units={})


# -- stations ------------------------------------------------------------------------------------


def test_the_station_is_the_identity_and_parallel_sensors_are_one_entity():
    objects = translate(load("station_missing_parallel_sensors"))
    station = next(e for e in entities(objects) if e.source_ids[0].external_id == "SN00001")
    assert station.entity_id == ids.derive(frost.SYSTEM, "SN00001")
    assert station.residual.data == {"sourceIds": ["SN00001:0", "SN00001:1"]}
    sensor0, sensor1 = objects[1], objects[2]
    assert sensor0.related_entities == sensor1.related_entities == [station.entity_id]
    assert contract_of(sensor0).station_id == "SN00001:0"
    assert contract_of(sensor1).station_id == "SN00001:1"
    assert sensor1.source_ids[0].external_id == "SN00001:1/2026-10-19T00:00:00.000Z"
    assert sensor0.event_id != sensor1.event_id


def test_a_source_id_without_suffix_is_read_as_stated():
    objects = translate(load("station_missing_parallel_sensors"))
    assert contract_of(objects[3]).station_id == "SN00002"
    station = next(e for e in entities(objects) if e.source_ids[0].external_id == "SN00002")
    assert objects[3].related_entities == [station.entity_id]


def test_position_comes_from_the_caller_table():
    objects = translate(load("two_stations_hourly"))
    station = entities(objects)[0]
    assert (station.position.lat, station.position.lon) == (57.2, 21.3)
    assert station.position.position_source.value == "MANUAL"
    assert "frost-observations-fixture-stations" in station.attributes["position_basis"]
    assert objects[0].geometry.coordinates == [21.3, 57.2]


def test_a_station_absent_from_the_table_is_emitted_without_position():
    objects = translate(load("station_missing_parallel_sensors"))
    station = entities(objects)[0]
    assert station.source_ids[0].external_id == "SN00009"
    assert station.position is None
    assert "has no row for this station" in station.attributes["position_basis"]
    assert objects[0].geometry is None


def test_no_table_means_no_position_for_any_station():
    objects = translate(load("two_stations_hourly"), station_table=None)
    for station in entities(objects):
        assert station.position is None
        assert "no station table was supplied" in station.attributes["position_basis"]


def test_the_station_table_must_be_a_station_table():
    with pytest.raises(ValueError):
        FrostObservationsAdapter(station_table={"SN00001": (1.0, 2.0)})


def test_station_table_from_sources_reads_point_coordinates_lon_lat():
    sources = {
        "data": [
            {
                "@type": "SensorSystem",
                "id": "SN00001",
                "geometry": {"@type": "Point", "coordinates": [21.25, 57.75], "nearest": False},
            },
            {"@type": "SensorSystem", "id": "SN00005"},
        ]
    }
    table = frost.station_table_from_sources(sources, name="t", basis="synthetic sources")
    assert table.position_of("SN00001") == (57.75, 21.25)
    assert table.position_of("SN00005") is None
    with pytest.raises(FrostRefused):
        frost.station_table_from_sources(
            {"data": [{"id": "SN1", "geometry": {"@type": "Point", "coordinates": [1.0]}}]},
            name="t",
            basis="b",
        )


def test_the_caller_states_synthetic():
    live = translate(load("two_stations_hourly"), synthetic=False)
    assert all(o.source.synthetic is False for o in live)
    assert all(o.source.synthetic is True for o in translate(load("two_stations_hourly")))


def test_identity_is_stable_across_two_instances():
    document = load("two_stations_hourly")
    first = [str(getattr(o, "event_id", None) or o.entity_id) for o in translate(document)]
    second = [str(getattr(o, "event_id", None) or o.entity_id) for o in translate(document)]
    assert first == second


# -- refusals ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "octets, code",
    [
        (b"\xef\xbb\xbf{}", "byte-order-mark"),
        (b'{"a": "\xff"}', "not-utf8"),
        (b'{"a": ', "not-json"),
        (b'{"a": 1, "a": 2}', "duplicate-key"),
        (b'{"a": NaN}', "not-a-number-literal"),
        (b"[1, 2]", "not-an-observation-response"),
    ],
)
def test_octets_that_are_not_one_clean_json_object_are_refused(octets, code):
    refused(octets, code)


def test_unsupported_input_types_are_refused():
    refused("{}", "unsupported-input")
    refused(["not", "a", "dict"], "unsupported-input")


def test_text_no_utf8_serialisation_carries_is_refused():
    document = minimal()
    document["data"][0]["observations"][0]["elementId"] = "air\ud800"
    refused(document, "not-utf8-text")


def test_a_float_that_is_not_finite_is_refused_in_a_dict():
    document = minimal(value=float("nan"))
    refused(document, "bad-value")


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda d: d.__setitem__("@type", "SourceResponse"), "not-an-observation-response"),
        (lambda d: d.__delitem__("@type"), "not-an-observation-response"),
        (lambda d: d.__setitem__("apiVersion", "v1"), "unsupported-api-version"),
        (lambda d: d.__setitem__("data_item", 1), "reserved-key"),
        (lambda d: d.__setitem__("createdAt", 17), "bad-created-at"),
        (lambda d: d.__setitem__("data", {}), "not-an-observation-response"),
        (lambda d: d.__setitem__("data", []), "no-data-item"),
        (lambda d: d["data"].__setitem__(0, "item"), "bad-item"),
        (lambda d: d["data"][0].__setitem__("sourceId", "SN00001:x"), "bad-source-id"),
        (lambda d: d["data"][0].__setitem__("sourceId", 990001), "bad-source-id"),
        (
            lambda d: d["data"][0].__setitem__("referenceTime", "2026-10-19T05:00:00"),
            "bad-reference-time",
        ),
        (
            lambda d: d["data"][0].__setitem__("referenceTime", "2026-02-30T05:00:00.000Z"),
            "bad-reference-time",
        ),
        (
            lambda d: d["data"][0].__setitem__("referenceTime", "2026-10-19T07:00:00+02:00"),
            "bad-reference-time",
        ),
        (lambda d: d["data"][0].__setitem__("observations", []), "no-observation"),
        (lambda d: d["data"][0].__setitem__("observations", {}), "bad-item"),
        (lambda d: d["data"][0]["observations"].__setitem__(0, 5), "bad-observation"),
    ],
)
def test_a_malformed_header_or_item_is_refused(mutate, code):
    document = minimal()
    mutate(document)
    refused(document, code)


@pytest.mark.parametrize(
    "observation, code",
    [
        ({"elementId": _DROP}, "bad-element-id"),
        ({"elementId": " "}, "bad-element-id"),
        ({"value": _DROP}, "bad-value"),
        ({"value": "1.5"}, "bad-value"),
        ({"value": True}, "bad-value"),
        ({"unit": ""}, "bad-unit"),
        ({"level": "2 m"}, "bad-level"),
        ({"level": {"value": 2, "unit": "m"}}, "bad-level"),
        ({"level": {"levelType": "height_above_ground", "value": 2}}, "bad-level"),
        ({"level": {"levelType": "height_above_ground", "value": "2", "unit": "m"}}, "bad-level"),
        ({"timeOffset": "6 hours"}, "bad-duration"),
        ({"timeResolution": "PT0H"}, "bad-duration"),
        ({"timeResolution": "P"}, "bad-duration"),
        ({"timeResolution": 3600}, "bad-duration"),
        ({"timeSeriesId": "0"}, "bad-observation"),
        ({"qualityCode": True}, "bad-quality-flag"),
        ({"qualityCode": 0.5}, "bad-quality-flag"),
        ({"performanceCategory": ""}, "bad-quality-flag"),
    ],
)
def test_a_malformed_observation_is_refused(observation, code):
    refused(minimal(**observation), code)


def test_a_repeated_series_in_one_item_is_refused():
    document = minimal()
    document["data"][0]["observations"].append(
        copy.deepcopy(document["data"][0]["observations"][0])
    )
    refused(document, "repeated-series")


def test_a_repeated_item_is_refused_even_when_spelled_differently():
    document = minimal()
    twin = copy.deepcopy(document["data"][0])
    twin["referenceTime"] = "2026-10-19T05:00:00Z"  # the same instant, other spelling
    document["data"].append(twin)
    refused(document, "repeated-item")


def test_a_refusal_never_quotes_the_payload():
    document = minimal(unit="SECRET-UNIT-TEXT")
    document["data"][0]["sourceId"] = "SECRET-STATION"
    problem = refused(document, "bad-source-id")
    assert "SECRET" not in str(problem)


def test_a_refusal_survives_pickling_with_its_code():
    problem = refused(minimal(value="x"), "bad-value")
    again = pickle.loads(pickle.dumps(problem))
    assert again.code == "bad-value" and str(again) == str(problem)


# -- bounds and declaration ----------------------------------------------------------------------


def test_octets_past_the_input_bound_are_refused_before_decode():
    with pytest.raises(InputTooLarge):
        translate(b" " * (frost.MAX_INPUT_BYTES + 1))


def test_a_document_past_the_depth_bound_is_refused():
    document = minimal()
    nested: object = 0
    for _ in range(frost.MAX_DEPTH + 1):
        nested = [nested]
    document["deep"] = nested
    with pytest.raises(InputTooDeep):
        translate(document)
    with pytest.raises(InputTooDeep):
        translate(json.dumps(document).encode())


def test_a_document_past_the_object_bound_is_refused(monkeypatch):
    document = load("two_stations_hourly")  # 4 items + 2 stations = 6 objects
    monkeypatch.setattr(frost, "MAX_OBJECTS", 5)
    refused(document, "too-many-objects")
    monkeypatch.setattr(frost, "MAX_OBJECTS", 6)
    assert len(translate(document)) == 6


def test_the_declaration_states_caps_licence_and_an_honest_claim():
    metadata = FrostObservationsAdapter.metadata
    limits = metadata.capabilities.limits
    assert limits.max_input_bytes == 16 * 1024 * 1024
    assert limits.max_objects == 50_000 and limits.max_depth == 64
    for name in ("max_input_bytes", "max_depth", "max_objects"):
        assert limits.declared_because[name].kind is LimitKind.IMPLEMENTATION_CAP
        module, function = limits.declared_because[name].test.split("::")
        text = (pathlib.Path(__file__).resolve().parents[1] / module).read_text()
        assert f"def {function}(" in text, limits.declared_because[name].test
    assert metadata.license_class is LicenseClass.PUBLIC_GOVERNMENT
    assert metadata.evidence.available is False
    assert metadata.claim_status is ClaimStatus.VERIFIED
    assert metadata.capabilities.unknown_fields is UnknownFields.PRESERVED
    ids_ = {lim.id for lim in metadata.limitations}
    assert {
        "observation-time-cases",
        "station-position-from-the-caller",
        "data-licence-as-stated",
        "synthetic-fixtures-only",
    } <= ids_


def test_a_received_at_comes_from_the_injected_clock():
    later = _dt.datetime(2026, 10, 21, tzinfo=_dt.timezone.utc)
    objects = FrostObservationsAdapter(clock=times.frozen_clock(later)).to_cdm(minimal())
    assert events(objects)[0].received_at == later


# -- performance ---------------------------------------------------------------------------------


def synthetic_batch(stations: int = 20, hours: int = 150) -> dict:
    """A synthetic response of stations x hours items, seven observations each (~ a real batch)."""
    start = _dt.datetime(2026, 10, 1, tzinfo=_dt.timezone.utc)
    items = []
    for s in range(stations):
        for h in range(hours):
            stamp = times.render(start + _dt.timedelta(hours=h))
            lvl2 = {"levelType": "height_above_ground", "unit": "m", "value": 2}
            lvl10 = {"levelType": "height_above_ground", "unit": "m", "value": 10}
            common = {
                "timeOffset": "PT0H",
                "timeResolution": "PT1H",
                "timeSeriesId": 0,
                "performanceCategory": "C",
                "exposureCategory": "2",
                "qualityCode": 0,
            }
            items.append(
                {
                    "sourceId": f"SN{s + 1:05d}:0",
                    "referenceTime": stamp,
                    "observations": [
                        {
                            "elementId": "air_temperature",
                            "value": -5 + (h % 10) / 10,
                            "unit": "degC",
                            "level": lvl2,
                            **common,
                        },
                        {
                            "elementId": "wind_speed",
                            "value": 3.5,
                            "unit": "m/s",
                            "level": lvl10,
                            **common,
                        },
                        {
                            "elementId": "wind_from_direction",
                            "value": 200,
                            "unit": "degrees",
                            "level": lvl10,
                            **common,
                        },
                        {
                            "elementId": "air_pressure_at_sea_level",
                            "value": 1003.2,
                            "unit": "hPa",
                            **common,
                        },
                        {
                            "elementId": "sum(precipitation_amount PT1H)",
                            "value": 0.1,
                            "unit": "mm",
                            **common,
                        },
                        {
                            "elementId": "relative_humidity",
                            "value": 81,
                            "unit": "percent",
                            "level": lvl2,
                            **common,
                        },
                        {"elementId": "surface_snow_thickness", "value": 4, "unit": "cm", **common},
                    ],
                }
            )
    document = {
        "@context": "https://frost.met.no/schema",
        "@type": "ObservationResponse",
        "apiVersion": "v0",
        "license": "https://creativecommons.org/licenses/by/3.0/no/",
        "createdAt": "2026-10-20T07:00:00.000Z",
        "queryTime": 1.0,
        "currentItemCount": len(items),
        "itemsPerPage": len(items),
        "offset": 0,
        "totalItemCount": len(items),
        "currentLink": "https://frost.met.no/x",
        "data": items,
    }
    return document


def test_a_3000_item_document_translates_within_bounds_and_time():
    octets = json.dumps(synthetic_batch()).encode()
    assert len(octets) < frost.MAX_INPUT_BYTES
    began = time.perf_counter()
    objects = FrostObservationsAdapter(clock=FROZEN).to_cdm(octets)
    elapsed = time.perf_counter() - began
    assert len(events(objects)) == 3000 and len(entities(objects)) == 20
    assert elapsed < 30, elapsed


# -- source hash ---------------------------------------------------------------------------------

DIGEST = "0123456789abcdef" * 4


@pytest.mark.parametrize(
    "given",
    [
        {"algorithm": "sha256", "value": DIGEST},
        __import__("synapse_cdm.models", fromlist=["SourceHash"]).SourceHash(
            algorithm="sha256", value=DIGEST
        ),
    ],
)
def test_the_caller_source_hash_lands_on_every_entity_and_event(given):
    objects = translate(load("midnight_mixed_daily"), source_hash=given)
    assert events(objects) and entities(objects)
    for obj in objects:
        assert obj.source.source_hash is not None
        assert (obj.source.source_hash.algorithm, obj.source.source_hash.value) == (
            "sha256",
            DIGEST,
        )


def test_without_a_source_hash_no_object_carries_one():
    objects = translate(load("midnight_mixed_daily"))
    assert all(obj.source.source_hash is None for obj in objects)


@pytest.mark.parametrize(
    "given",
    [
        {"algorithm": "md5", "value": DIGEST},
        {"algorithm": "sha256", "value": DIGEST.upper()},
        {"algorithm": "sha256", "value": DIGEST[:-1]},
    ],
)
def test_a_source_hash_that_is_not_a_sha256_digest_is_refused(given):
    with pytest.raises(ValueError):
        FrostObservationsAdapter(source_hash=given)
