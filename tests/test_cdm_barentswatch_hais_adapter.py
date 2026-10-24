"""`barentswatch_hais`, #32 in the ordinal table: one AIS track file -> Entity, Track, Event.

One test per claim in the module's docstring and declaration, refusals included. Every expectation
is a literal written from the fixture's own document (`spec/build_fixtures.py`), never read back
from the adapter. Every payload is synthetic: MMSIs under MID 299 (the `ais` fixtures' convention),
EX names, positions inside CONTRIBUTING.md's Baltic rectangle.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/barentswatch_hais/` and
runs the packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import pathlib
import time

import pytest

import synapse_cdm
from synapse_cdm import harness, ids, times
from synapse_cdm.adapter import InputTooDeep, InputTooLarge, discover
from synapse_cdm.adapters import ais
from synapse_cdm.adapters import barentswatch_hais as bw
from synapse_cdm.adapters.barentswatch_hais import (
    BarentswatchHaisAdapter,
    BarentswatchHaisRefused,
)
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.manifest import ClaimStatus, LicenseClass, MaturityLevel, UnknownFields
from synapse_cdm.models import SourceHash
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "barentswatch_hais"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
CLOCK = times.frozen_clock(times.FROZEN_NOW)
BUILD = support.load_builder(FIXTURES / "spec" / "build_fixtures.py")
#: The five pairs: `<name>.hais` (octets) beside `<name>.parsed.json`.
CASES = sorted(p.name.removesuffix(".hais") for p in FIXTURES.glob("*.hais"))


def documents() -> list[pathlib.Path]:
    """The parsed twins the harness replays (the octet payloads are their other half)."""
    return [p for p in harness.select_fixtures(FIXTURES) if p.name.endswith(".parsed.json")]


def load(name: str):
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text())


def octets(name: str) -> bytes:
    return (FIXTURES / f"{name}.hais").read_bytes()


def run(raw, *, clock=CLOCK, synthetic=True):
    return BarentswatchHaisAdapter(clock=clock, synthetic=synthetic).to_cdm(raw)


def dump(objects):
    return [o.model_dump(mode="json") for o in objects]


def point(seconds=0, lat=57.0, lon=21.0, mmsi=299000901, **extra):
    return BUILD.element(mmsi, seconds, lat, lon, **extra)


def refused(raw, code):
    with pytest.raises(BarentswatchHaisRefused) as caught:
        run(raw)
    assert caught.value.code == code
    return caught.value


# ------------------------------------------------------------------ the declaration


def test_the_adapter_is_registered_and_claims_its_ordinal():
    cls = discover()["barentswatch_hais"]
    assert cls is BarentswatchHaisAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "barentswatch_hais",
        "1.2.0",
        "ingest",
        "BARENTSWATCH",
    )
    assert bw.__doc__.splitlines()[0] == (
        "`barentswatch_hais`, #32 in the ordinal table: BarentsWatch AIS track JSON -> CDM, "
        "ingest only."
    )
    assert cls.metadata.claim_status is ClaimStatus.VERIFIED


# ------------------------------------------------------------------ the fixture set itself


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert len(CASES) == 5 and {p.name for p in documents()} == {f"{c}.parsed.json" for c in CASES}


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_every_fixture_follows_the_mmsi_name_and_place_conventions(name):
    for element in load(name):
        assert support.mmsi_problems(str(element["mmsi"])) == []
        if element.get("name") is not None:
            assert element["name"].startswith("EX ")
    assert support.positions_outside_the_rectangle(dump(run(load(name)))) == []


@pytest.mark.parametrize("name", CASES)
def test_the_parse_of_each_payload_is_its_twin_and_both_translate_to_one_result(name):
    assert json.loads(octets(name).decode("utf-8")) == load(name)
    assert dump(run(octets(name))) == dump(run(load(name)))
    assert json.loads((GOLDEN / f"{name}.cdm.json").read_text()) == json.loads(
        (GOLDEN / f"{name}.parsed.cdm.json").read_text()
    )


def test_the_harness_passes_every_fixture_against_its_golden():
    adapter = BarentswatchHaisAdapter(clock=CLOCK, synthetic=True)
    report = harness.run(adapter, FIXTURES)
    assert report["failed"] == 0 and report["passed"] == 10
    for result in report["results"]:
        assert result["checks"]["golden"] == "PASS"
        if result["fixture"].endswith(".parsed.json"):
            assert result["checks"]["lossless"] == "PASS"
            assert result["preservation"]["counts"]["LOST"] == 0
        else:
            assert result["checks"]["lossless"] == "SKIP"  # octets: the twin carries the column


# ------------------------------------------------------------------ what a payload is


def test_octets_and_the_parsed_list_translate_identically():
    assert dump(run(octets("underway_newest_first"))) == dump(run(load("underway_newest_first")))


@pytest.mark.parametrize("raw", ['[{"mmsi": 1}]', {"track": []}, 42, None])
def test_json_text_a_dict_and_other_types_are_refused(raw):
    refused(raw, "unsupported-input")


def test_a_document_that_is_not_an_array_is_refused():
    refused(b'{"mmsi": 299000901}', "not-an-array")


def test_an_empty_array_is_refused():
    refused([], "empty-track")
    refused(b"[]", "empty-track")


@pytest.mark.parametrize(
    "name, code",
    [
        ("mixed_mmsi.json", "mixed-mmsi"),
        ("missing_msgtime.json", "missing-key"),
        ("missing_latitude.json", "missing-key"),
        ("msgtime_without_offset.json", "bad-msgtime"),
        ("empty_array.json", "empty-track"),
        ("top_level_object.json", "unsupported-input"),
        ("mmsi_as_text.json", "bad-mmsi"),
        ("latitude_out_of_range.json", "coordinate-out-of-range"),
        ("no_positioned_point.json", "no-positioned-point"),
        ("negative_speed.json", "bad-element"),
        ("element_not_object.json", "bad-point"),
        ("duplicate_key.hais", "duplicate-key"),
        ("nan_value.hais", "non-finite-number"),
        ("truncated.hais", "not-json"),
        ("not_utf8.hais", "not-utf-8"),
    ],
)
def test_every_malformed_fixture_is_refused_with_its_code(name, code):
    raw = harness.load_raw(MALFORMED / name)
    refused(raw, code)


def test_the_malformed_set_is_exactly_the_tested_set():
    tested = {
        "mixed_mmsi.json",
        "missing_msgtime.json",
        "missing_latitude.json",
        "msgtime_without_offset.json",
        "empty_array.json",
        "top_level_object.json",
        "mmsi_as_text.json",
        "latitude_out_of_range.json",
        "no_positioned_point.json",
        "negative_speed.json",
        "element_not_object.json",
        "duplicate_key.hais",
        "nan_value.hais",
        "truncated.hais",
        "not_utf8.hais",
    }
    assert {p.name for p in harness.select_fixtures(MALFORMED)} == tested


@pytest.mark.parametrize("key", bw.REQUIRED_KEYS)
def test_each_required_key_is_refused_when_missing_and_never_defaulted(key):
    element = point()
    del element[key]
    error = refused([point(60), element], "missing-key")
    assert "[1]" in str(error)


@pytest.mark.parametrize("value", [True, 0, -5, 1_000_000_000, 1.5, None])
def test_an_mmsi_that_is_not_a_nine_digit_integer_is_refused(value):
    refused([point() | {"mmsi": value}], "bad-mmsi")


def test_a_refusal_names_a_path_and_never_quotes_a_value():
    error = refused([point() | {"latitude": 95.123456}], "coordinate-out-of-range")
    assert "95.123456" not in str(error) and "[0].latitude" in str(error)


@pytest.mark.parametrize(
    "key, value",
    [
        ("speedOverGround", "fast"),
        ("trueHeading", True),
        ("name", 7),
        ("stream", ["terra"]),
        ("courseOverGround", float("inf")),
        ("latitude", "57.0"),
    ],
)
def test_a_value_of_the_wrong_type_is_refused(key, value):
    with pytest.raises(BarentswatchHaisRefused):
        run([point() | {key: value}])


def test_negative_course_is_refused():
    refused([point(courseOverGround=-0.5)], "bad-element")


def test_unknown_keys_are_preserved_in_the_residual_and_named():
    document = load("unknown_extra_key")
    entity = run(document)[0]
    assert entity.attributes["unknown_keys"] == ["extraBlock", "receiverHint"]
    assert entity.residual.data["points"] == document
    assert entity.residual.data["points"][0]["extraBlock"]["tags"][1] == "synthetic-b"


def test_an_element_with_only_the_required_keys_translates():
    entity, track, _ = run(
        [
            {
                "mmsi": 299000901,
                "msgtime": "2026-10-19T00:00:00+00:00",
                "latitude": 57.0,
                "longitude": 21.0,
            }
        ]
    )
    assert entity.kinematics is None and len(track.samples) == 1


# ------------------------------------------------------------------ what one file becomes


def test_a_file_becomes_entity_track_event_in_that_order():
    for name in CASES:
        assert [o.object_kind for o in run(load(name))] == ["entity", "track", "event"]


def test_the_entity_is_a_platform_of_unknown_affiliation():
    entity = run(load("underway_newest_first"))[0]
    assert entity.entity_type is EntityType.PLATFORM
    assert entity.affiliation is Affiliation.UNKNOWN


def test_the_entity_type_is_the_ais_adapters_mmsi_rule():
    # single_point is the aid to navigation 99|299|0010: a FACILITY, as `ais` types a buoy.
    buoy = run(load("single_point"))[0]
    assert buoy.attributes["mmsi_category"] == "aid to navigation"
    assert buoy.entity_type is EntityType.FACILITY
    assert buoy.entity_type is ais._entity_type({}, buoy.attributes["mmsi_category"])
    coast = run([point(mmsi=2990001)])[0]  # 00|299|0001, a coast station
    assert (coast.attributes["mmsi_category"], coast.entity_type) == (
        "coast station",
        EntityType.FACILITY,
    )
    ship = run(load("underway_newest_first"))[0]
    assert (ship.attributes["mmsi_category"], ship.entity_type) == (
        ais.MMSI_SHIP_STATION,
        EntityType.PLATFORM,
    )
    assert set(ais.MMSI_FACILITY_CATEGORIES) == {"coast station", "aid to navigation"}
    assert "FACILITY" in ship.attributes["entity_type_basis"]


def test_the_entity_id_is_the_one_the_ais_adapter_derives_for_the_same_mmsi():
    mmsi = 299000101
    entity = run(load("underway_newest_first"))[0]
    parsed = {
        "message": {
            "type": 1,
            "repeat_indicator": 0,
            "mmsi": f"{mmsi:09d}",
            "navigational_status": 0,
            "rate_of_turn_raw": 0,
            "sog_knots": 10.0,
            "position_accuracy": False,
            "lon": 21.0,
            "lat": 57.0,
            "cog_deg": 45.0,
            "true_heading_deg": 44,
            "utc_second": 20,
            "manoeuvre_indicator": 0,
            "spare": 0,
            "raim": False,
            "radio_status": 0,
        }
    }
    from_ais = ais.AisAdapter(clock=CLOCK).to_cdm(parsed)[0]
    assert entity.entity_id == from_ais.entity_id
    assert entity.entity_type is from_ais.entity_type
    assert [s.model_dump() for s in entity.source_ids] == [
        s.model_dump() for s in from_ais.source_ids
    ]


def test_an_mmsi_with_fewer_digits_is_rendered_as_nine_with_its_leading_zeros():
    entity = run([point(mmsi=2990001)])[0]
    assert entity.source_ids[0].external_id == "002990001"
    assert entity.source_ids[0].system == ais.SYSTEM
    assert entity.entity_id == ids.derive(ais.SYSTEM, "002990001", kind="entity")


def test_the_entity_takes_position_kinematics_and_validity_from_the_samples():
    entity, track, _ = run(load("underway_newest_first"))
    assert entity.position == track.samples[-1].position
    assert entity.valid_from == track.samples[0].observed_at
    assert entity.valid_to == track.samples[-1].observed_at
    # The newest element (file index 0) states 11.7 kn on course 52.5.
    assert entity.kinematics.speed_mps == round(11.7 * 1852 / 3600, 4)
    assert entity.kinematics.course_deg == 52.5


def test_the_whole_document_is_the_entity_residual_in_file_order():
    document = load("nulls_and_sentinels")
    entity = run(copy.deepcopy(document))[0]
    assert entity.residual.namespace == bw.FORMAT_NAME
    assert entity.residual.data == {"points": document}


def test_the_residual_is_a_copy_not_the_callers_list():
    document = load("single_point")
    entity = run(document)[0]
    document[0]["name"] = "CHANGED"
    assert entity.residual.data["points"][0]["name"] == "EX SOLO BUOY"


def test_per_sample_readings_are_keyed_by_sample_index_back_to_their_element():
    document = load("duplicate_instants_unordered")
    entity, track, _ = run(document)
    readings = entity.attributes["barentswatch_samples"]
    assert all(len(v) == len(track.samples) for v in readings.values())
    for k, sample in enumerate(track.samples):
        element = entity.residual.data["points"][readings["source_index"][k]]
        assert (sample.position.lat, sample.position.lon) == (
            element["latitude"],
            element["longitude"],
        )


def test_the_track_states_it_is_a_fragment_with_no_stated_total():
    _, track, _ = run(load("underway_newest_first"))
    completeness = track.attributes.completeness
    assert completeness.fragment is True
    assert completeness.stated_samples is None
    assert completeness.carried_samples == len(track.samples) == 6


def test_the_event_is_a_track_update_at_the_last_sample():
    entity, track, event = run(load("underway_newest_first"))
    assert event.event_type is EventType.TRACK_UPDATE
    assert event.severity is Severity.INFO
    assert event.observed_at == track.samples[-1].observed_at
    assert event.related_entities == [entity.entity_id]
    assert event.payload["track_id"] == str(track.track_id)


def test_a_distress_status_raises_no_alert():
    entity, _, event = run([point(navigationalStatus=14)])
    assert event.event_type is EventType.TRACK_UPDATE and event.severity is Severity.INFO
    assert entity.attributes["barentswatch_samples"]["navigational_status"] == [14]


# ------------------------------------------------------------------ order


def test_a_newest_first_file_becomes_exactly_its_reversal():
    document = load("underway_newest_first")
    entity, track, _ = run(document)
    assert entity.attributes["source_order"] == "descending"
    assert entity.attributes["barentswatch_samples"]["source_index"] == [5, 4, 3, 2, 1, 0]
    stamps = [s.observed_at for s in track.samples]
    assert stamps == sorted(stamps)
    assert [s.position.lat for s in track.samples] == [p["latitude"] for p in reversed(document)]


def test_the_reordering_is_declared_and_listed_in_the_transformations():
    assert bw.BarentswatchHaisAdapter.TRANSFORMS["[*]"] == bw.T_ORDER
    entity, track, _ = run(load("underway_newest_first"))
    assert bw.T_ORDER in entity.source.transformations
    assert bw.T_ORDER in track.source.transformations


@pytest.mark.parametrize(
    "arrangement, expected",
    [
        ([0, 1, 2], "ascending"),
        ([2, 1, 0], "descending"),
        ([1, 0, 2], "unordered"),
    ],
)
def test_any_input_order_is_accepted_sorted_and_recorded(arrangement, expected):
    document = [point(60 * k, lat=57.0 + k / 100) for k in arrangement]
    entity, track, _ = run(document)
    assert entity.attributes["source_order"] == expected
    assert [s.position.lat for s in track.samples] == [57.0, 57.01, 57.02]


def test_a_single_point_track_is_one_sample():
    entity, track, event = run(load("single_point"))
    assert len(track.samples) == 1
    assert entity.attributes["source_order"] == "single-instant"
    assert entity.valid_from == entity.valid_to == event.observed_at


# ------------------------------------------------------------------ duplicate instants


def test_duplicate_instants_are_all_kept_and_classified():
    entity, track, _ = run(load("duplicate_instants_unordered"))
    assert len(track.samples) == 6
    groups = entity.attributes["duplicate_instants"]
    assert [(g["sample_indices"], g["identical"]) for g in groups] == [
        ([0, 1], True),
        ([4, 5], False),
    ]


def test_ties_are_ordered_by_descending_file_index_so_the_newest_by_file_order_is_last():
    # File index 2 (57.32) precedes index 3 (57.33) and shares its instant: it comes last.
    entity, track, _ = run(load("duplicate_instants_unordered"))
    assert entity.attributes["barentswatch_samples"]["source_index"][4:] == [3, 2]
    assert entity.position.lat == 57.32


def test_the_order_is_a_pure_function_of_the_file():
    document = load("duplicate_instants_unordered")
    assert dump(run(document)) == dump(run(copy.deepcopy(document)))


# ------------------------------------------------------------------ sentinels


def test_ais_constants_are_reused_from_the_ais_adapter():
    assert (
        bw.LAT_UNAVAILABLE,
        bw.LON_UNAVAILABLE,
        bw.SOG_UNAVAILABLE,
        bw.COG_UNAVAILABLE,
        bw.HEADING_UNAVAILABLE,
        bw.ROT_UNAVAILABLE,
        bw.KNOT_MPS,
        bw.MMSI_SYSTEM,
    ) == (
        ais.LAT_UNAVAILABLE,
        ais.LON_UNAVAILABLE,
        ais.SOG_UNAVAILABLE,
        ais.COG_UNAVAILABLE,
        ais.HEADING_UNAVAILABLE,
        ais.ROT_UNAVAILABLE,
        ais.KNOT_MPS,
        ais.SYSTEM,
    )


def test_null_values_are_unknown_never_zero():
    entity = run(
        [point(speedOverGround=None, courseOverGround=None, trueHeading=None, rateOfTurn=None)]
    )[0]
    assert entity.kinematics is None
    readings = entity.attributes["barentswatch_samples"]
    assert readings["speed_mps"] == readings["course_deg"] == [None]
    assert readings["true_heading_deg"] == readings["rate_of_turn"] == [None]
    assert readings["null_fields"] == [
        ["courseOverGround", "rateOfTurn", "speedOverGround", "trueHeading"]
    ]


@pytest.mark.parametrize(
    "key, value",
    [
        ("speedOverGround", 102.3),
        ("courseOverGround", 360.0),
        ("courseOverGround", 361.5),
        ("trueHeading", 511),
        ("rateOfTurn", -128),
    ],
)
def test_each_ais_sentinel_becomes_absent_and_never_a_number(key, value):
    entity = run([point(**{key: value})])[0]
    readings = entity.attributes["barentswatch_samples"]
    field = {
        "speedOverGround": "speed_mps",
        "courseOverGround": "course_deg",
        "trueHeading": "true_heading_deg",
        "rateOfTurn": "rate_of_turn",
    }[key]
    assert readings[field] == [None]
    assert readings["sentinel_fields"] == [[key]]
    kinematics = entity.kinematics
    if key == "speedOverGround":
        assert kinematics.speed_mps is None
    if key == "courseOverGround":
        assert kinematics.course_deg is None


def test_the_sentinel_fixture_gives_a_position_and_no_kinematics():
    entity = run(load("nulls_and_sentinels"))[0]
    assert entity.position is not None and entity.kinematics is None
    assert entity.attributes["barentswatch_samples"]["sentinel_fields"][-1] == [
        "courseOverGround",
        "rateOfTurn",
        "speedOverGround",
        "trueHeading",
    ]


@pytest.mark.parametrize(
    "lat, lon", [(91.0, 21.0), (57.0, 181.0), (91.0, 181.0), (None, 21.0), (57.0, None)]
)
def test_an_unavailable_coordinate_yields_no_sample_and_is_listed(lat, lon):
    entity, track, event = run([point(0), point(60, lat=lat, lon=lon)])
    assert len(track.samples) == 1
    assert entity.attributes["points_without_position"] == [1]
    assert event.payload["element_count"] == 2 and event.payload["sample_count"] == 1
    assert bw.T_POSITION_SENTINEL in track.source.transformations


def test_zero_is_a_measurement_not_an_absence():
    entity = run(
        [
            point(
                lat=0.0,
                lon=0.0,
                speedOverGround=0.0,
                courseOverGround=0.0,
                trueHeading=0,
                rateOfTurn=0,
            )
        ]
    )[0]
    assert (entity.position.lat, entity.position.lon) == (0.0, 0.0)
    assert entity.kinematics.speed_mps == 0.0 and entity.kinematics.course_deg == 0.0
    readings = entity.attributes["barentswatch_samples"]
    assert readings["true_heading_deg"] == [0] and readings["rate_of_turn"] == [0]


def test_the_102_2_floor_is_kept_and_flagged():
    entity = run([point(speedOverGround=102.2)])[0]
    assert entity.kinematics.speed_mps == round(102.2 * 1852 / 3600, 4)
    assert entity.attributes["barentswatch_samples"]["speed_at_or_above_maximum"] == [True]


def test_a_file_with_no_usable_position_is_refused():
    refused([point(lat=91.0), point(60, lon=None)], "no-positioned-point")


# ------------------------------------------------------------------ units and position source


@pytest.mark.parametrize("knots, course", [(0.1, 0.0), (12.3, 359.9), (55.55, 180.0)])
def test_speed_and_course_match_the_ais_adapters_conversion(knots, course):
    entity = run([point(speedOverGround=knots, courseOverGround=course)])[0]
    expected = ais._kinematics({"sog_knots": knots, "cog_deg": course})
    assert entity.kinematics.speed_mps == expected.speed_mps
    assert entity.kinematics.course_deg == expected.course_deg


def test_rate_of_turn_is_carried_verbatim():
    entity = run([point(rateOfTurn=-37), point(60, rateOfTurn=4.5)])[0]
    assert entity.attributes["barentswatch_samples"]["rate_of_turn"] == [-37, 4.5]


def test_position_source_is_what_the_ais_adapter_states_for_an_unqualified_fix():
    _, track, _ = run(load("underway_newest_first"))
    expected, _ = ais._position_source({})
    assert expected is PositionSource.ESTIMATED
    assert {s.position.position_source for s in track.samples} == {expected}
    assert all(s.position.alt_m is None and s.position.accuracy_m is None for s in track.samples)


# ------------------------------------------------------------------ time


def test_msgtime_is_converted_to_utc_and_rendered_with_three_truncated_decimals():
    _, track, _ = run([point() | {"msgtime": "2026-10-19T07:33:20.1239+02:00"}])
    dumped = track.model_dump(mode="json")
    assert dumped["samples"][0]["observed_at"] == "2026-10-19T05:33:20.123Z"
    assert bw.T_INSTANT in track.source.transformations


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-19T00:00:00",
        "2026-10-19",
        "2026-10-19 00:00:00+00:00",
        "20261019T000000Z",
        "2026-13-19T00:00:00+00:00",
        "2026-10-19T00:00:00.1234567+00:00",
        1760832000,
    ],
)
def test_a_msgtime_without_an_explicit_offset_or_form_is_refused(text):
    refused([point() | {"msgtime": text}], "bad-msgtime")


def test_received_at_is_the_injected_clock_and_nothing_else_moves_with_it():
    document = load("underway_newest_first")
    later = _dt.datetime(2030, 1, 2, 3, 4, 5, tzinfo=_dt.timezone.utc)
    first = dump(run(document))
    second = dump(run(document, clock=times.frozen_clock(later)))
    assert second[2]["received_at"] == "2030-01-02T03:04:05.000Z"
    second[2]["received_at"] = first[2]["received_at"]
    assert first == second


def test_the_module_never_reads_the_system_clock():
    source = pathlib.Path(bw.__file__).read_text()
    assert "datetime.now" not in source and "utc_now" not in source and "time.time" not in source


# ------------------------------------------------------------------ provenance and identity


def test_synthetic_defaults_to_true_and_false_is_passed_through_to_every_object():
    document = load("single_point")
    assert all(o.source.synthetic is True for o in BarentswatchHaisAdapter().to_cdm(document))
    assert all(o.source.synthetic is False for o in run(document, synthetic=False))


def test_every_object_names_the_system_the_format_and_the_record():
    for obj in run(load("underway_newest_first")):
        assert obj.source.system == "BARENTSWATCH"
        assert obj.source.format_name == bw.FORMAT_NAME
        assert obj.source.original_id == "299000101"
        assert obj.source_ids[0].external_id == "299000101"


def test_ids_are_stable_across_instances_and_calls():
    document = load("duplicate_instants_unordered")
    a = run(document)
    b = BarentswatchHaisAdapter(clock=CLOCK).to_cdm(copy.deepcopy(document))
    assert (a[0].entity_id, a[1].track_id, a[2].event_id) == (
        b[0].entity_id,
        b[1].track_id,
        b[2].event_id,
    )
    for value in (a[0].entity_id, a[1].track_id, a[2].event_id):
        assert value.version == 5


def test_track_and_event_ids_name_the_mmsi_and_the_window():
    one = run([point(0), point(60)])
    same_span = run([point(0), point(30, lat=57.5), point(60)])
    other_span = run([point(0), point(120)])
    assert one[1].track_id == same_span[1].track_id and one[2].event_id == same_span[2].event_id
    assert one[1].track_id != other_span[1].track_id
    assert one[0].entity_id == other_span[0].entity_id
    assert one[1].track_id == ids.derive(
        ais.SYSTEM, "299000901@2026-10-19T00:00:00.000Z..2026-10-19T00:01:00.000Z", kind="track"
    )


def test_the_track_and_event_residuals_carry_the_mmsi_as_stated():
    _, track, event = run(load("underway_newest_first"))
    assert track.residual.data == event.residual.data == {"mmsi": 299000101}


# ------------------------------------------------------------------ bounds and performance


def test_one_octet_over_the_input_bound_is_refused_before_decode():
    oversized = b"[" + b" " * (bw.MAX_INPUT_BYTES - 1) + b"]"
    assert len(oversized) == bw.MAX_INPUT_BYTES + 1
    with pytest.raises(InputTooLarge):
        run(oversized)


def test_a_document_past_the_depth_bound_is_refused():
    deep: object = "x"
    for _ in range(bw.MAX_DEPTH + 1):
        deep = [deep]
    with pytest.raises(InputTooDeep):
        run([point() | {"extra": deep}])
    with pytest.raises(InputTooDeep):
        run(json.dumps([point() | {"extra": deep}]).encode())


def test_a_track_past_the_point_bound_is_refused_before_any_element_is_read():
    refused([None] * (bw.MAX_POINTS + 1), "too-many-points")


def test_a_realistic_5000_point_track_translates_within_bounds_and_quickly():
    document = BUILD.synthetic_track(5000)
    octets = json.dumps(document, separators=(",", ":")).encode()
    assert len(octets) < bw.MAX_INPUT_BYTES
    started = time.perf_counter()
    entity, track, event = run(octets)
    elapsed = time.perf_counter() - started
    assert len(track.samples) == 5000 and event.payload["element_count"] == 5000
    assert entity.attributes["source_order"] == "descending"
    assert elapsed < 21.0


# ------------------------------------------------------------------ the declaration


def test_the_declaration_is_what_the_evidence_supports():
    meta = BarentswatchHaisAdapter.metadata
    assert meta.id == BarentswatchHaisAdapter.name == "barentswatch_hais"
    assert meta.license_class is LicenseClass.PUBLIC_GOVERNMENT
    assert meta.maturity.level is MaturityLevel.L3
    # The 3.7.0 release commit (2026-10-24) flips the evidence declaration it landed with.
    assert meta.evidence.available is True
    limits = meta.capabilities.limits
    assert limits.max_input_bytes == 16 * 1024 * 1024 and limits.max_depth == 64
    assert meta.capabilities.unknown_fields is UnknownFields.PRESERVED
    ids_declared = {lim.id for lim in meta.limitations}
    assert {
        "open-data-coverage",
        "retention-window",
        "provider-satellite-filtering",
        "no-join-across-files",
        "rate-of-turn-unit-not-established",
        "entity-type-from-the-mmsi-category",
        "synthetic-evidence-only",
    } <= ids_declared


def test_every_named_bound_test_exists_where_the_declaration_says():
    for basis in BarentswatchHaisAdapter.metadata.capabilities.limits.declared_because.values():
        module, function = basis.test.split("::")
        text = (pathlib.Path(__file__).resolve().parents[1] / module).read_text()
        assert f"def {function}(" in text, basis.test


# ------------------------------------------------------------------ source hash (1.1.0)

DIGEST = "ab" * 32


def test_a_given_source_hash_lands_on_entity_track_and_event():
    raw = octets("underway_newest_first")
    for given in (
        {"algorithm": "sha256", "value": DIGEST},
        SourceHash(algorithm="sha256", value=DIGEST),
    ):
        objects = BarentswatchHaisAdapter(clock=CLOCK, source_hash=given).to_cdm(raw)
        assert [o.object_kind for o in objects] == ["entity", "track", "event"]
        for obj in objects:
            assert obj.source.source_hash == SourceHash(algorithm="sha256", value=DIGEST)
            assert obj.model_dump(mode="json")["source"]["source_hash"] == {
                "algorithm": "sha256",
                "value": DIGEST,
            }


def test_without_a_source_hash_none_is_stated():
    for obj in run(load("underway_newest_first")):
        assert obj.source.source_hash is None


def test_the_hash_is_carried_not_computed_and_changes_nothing_else():
    document = load("underway_newest_first")
    plain = dump(run(document))
    hashed = dump(
        BarentswatchHaisAdapter(
            clock=CLOCK, source_hash={"algorithm": "sha256", "value": DIGEST}
        ).to_cdm(document)
    )
    for obj in hashed:
        obj["source"]["source_hash"] = None
    assert hashed == plain
    assert "hashlib" not in pathlib.Path(bw.__file__).read_text()


@pytest.mark.parametrize(
    "given",
    [
        {"algorithm": "md5", "value": DIGEST},
        {"algorithm": "sha256", "value": "AB" * 32},
        {"algorithm": "sha256", "value": "ab" * 31},
        {"algorithm": "sha256"},
        "ab" * 32,
    ],
)
def test_a_malformed_source_hash_is_refused_at_construction(given):
    with pytest.raises(ValueError):
        BarentswatchHaisAdapter(source_hash=given)


def test_the_version_is_1_2_0_everywhere():
    assert BarentswatchHaisAdapter.version == "1.2.0"
    assert BarentswatchHaisAdapter.metadata.adapter_version == "1.2.0"
    assert all(o.source.adapter_version == "1.2.0" for o in run(load("single_point")))
