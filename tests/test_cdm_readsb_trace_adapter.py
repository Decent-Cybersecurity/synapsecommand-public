"""`readsb_trace`, #24 in the ordinal table: one readsb globe trace -> Entity, Track, Event.

Every expectation here is a literal written from the fixture's own document (`spec/
build_fixtures.py`) and README-json.md's field order, never read back from the adapter: an
instant is the fixture's midnight plus its element 0 worked by hand, an identifier is the uuid5 of
the documented namespace and name built here, and every refusal is its code and its whole text.
The twins are held to their payloads with the standard library's own `gzip`, not with the
adapter's inflater, and the goldens of each pair to each other.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/readsb_trace/` and
`fixtures/adsb/`, and runs the packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

import copy
import gzip
import json
import pathlib
import pickle
import struct
import uuid

import pytest

import synapse_cdm
from synapse_cdm import harness, times
from synapse_cdm.adapter import InputTooDeep, discover
from synapse_cdm.adapters import readsb_trace
from synapse_cdm.adapters.adsb import AdsbAdapter
from synapse_cdm.adapters.readsb_trace import ReadsbTraceAdapter, ReadsbTraceRefused
from synapse_cdm.manifest import LimitKind, UnknownFields
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "readsb_trace"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
ADSB = PKG / "fixtures" / "adsb"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"

CASES = sorted(p.stem for p in FIXTURES.glob("*.trace"))


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _translate(name: str, clock=None) -> list[dict]:
    adapter = ReadsbTraceAdapter(clock=clock or times.frozen_clock())
    return [
        o.model_dump(mode="json") for o in adapter.to_cdm((FIXTURES / f"{name}.trace").read_bytes())
    ]


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _refusal(payload) -> ReadsbTraceRefused:
    with pytest.raises(ReadsbTraceRefused) as raised:
        ReadsbTraceAdapter(clock=times.frozen_clock()).to_cdm(payload)
    return raised.value


def _member(document) -> bytes:
    return gzip.compress(json.dumps(document).encode("utf-8"), mtime=0)


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["readsb_trace"]
    assert cls is ReadsbTraceAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "readsb_trace",
        "1.0.0",
        "ingest",
        "READSB",
    )
    assert readsb_trace.__doc__.splitlines()[0] == (
        "`readsb_trace`, #24 in the ordinal table: readsb trace JSON -> CDM, ingest only."
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
        "readsb trace JSON",
        "readsb v3.16.17",
        "standard-encoding",
        "OPEN",
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
    ) == (8388608, 64, None, 67108864, None)
    assert sorted(limits.absent_because) == ["max_objects", "max_parse_seconds"]
    assert sorted(limits.declared_because) == [
        "max_decompressed_bytes",
        "max_depth",
        "max_input_bytes",
    ]
    for basis in limits.declared_because.values():
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP
        assert "IMPLEMENTATION CAP and is NOT the format's normative maximum" in basis.source
    # Each bound quotes the design record's figure (research-readsb F9) and the ruling (L-09).
    for field in ("max_input_bytes", "max_decompressed_bytes"):
        source = limits.declared_because[field].source
        assert "research-readsb-globe-history F9" in source and "L-09" in source, field
    assert "23 KB of gzip and 140 KB of JSON" in limits.declared_because["max_input_bytes"].source
    assert limits.declared_because["max_decompressed_bytes"].test == (
        "tests/test_cdm_readsb_trace_adapter.py::"
        "test_inflation_is_held_to_the_declared_bound_and_one_octet_past_it_is_refused"
    )
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    assert [lim.id for lim in meta.limitations] == [
        "one-trace-per-call",
        "no-join-across-files",
        "per-sample-fields-on-the-entity",
        "barometric-altitude-not-hae",
        "db-strings-not-exercised",
        "evidence-availability",
    ]


def test_the_ledger_binds_the_address_and_time_base_on_every_object_and_the_coordinates():
    mappings = ReadsbTraceAdapter.MAPPINGS
    assert list(mappings) == [
        "icao",
        "timestamp",
        "trace[*][1]",
        "trace[*][2]",
        "trace",
        "r",
        "t",
        "dbFlags",
        "desc",
        "ownOp",
        "year",
        "noRegData",
        "version",
    ]
    assert [m.to for m in mappings["icao"]] == [
        "entity:residual.data.icao",
        "track:residual.data.icao",
        "event:residual.data.icao",
    ]
    assert [(m.to, m.kind) for m in mappings["trace[*][1]"]] == [
        ("entity:residual.data.trace[*][1]", "residual"),
        ("track:samples[*].position.lat", "field"),
    ]
    assert [(m.to, m.kind) for m in mappings["trace"]] == [
        ("entity:residual.data.trace", "residual")
    ]


# ================================================================== the fixture set


def test_the_set_is_thirteen_payloads_with_their_twins_and_twenty_three_refusals():
    assert CASES == [
        "airborne_adsb_2022_form",
        "equal_instants_and_db_flags",
        "every_flag_bit",
        "ground_heading_slot",
        "midnight_fragment_day_one",
        "midnight_fragment_day_two",
        "mlat_positions",
        "nonicao_address",
        "null_altitude_and_speed",
        "pre2022_nine_elements",
        "receiver_id_fifteen_elements",
        "reference_not_midnight",
        "tisb_positions",
    ]
    assert [p.name for p in harness.select_fixtures(FIXTURES)] == sorted(
        [f"{n}.trace" for n in CASES] + [f"{n}.parsed.json" for n in CASES]
    )
    assert len(list(MALFORMED.glob("*.trace"))) == 23
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(
        [f"{n}.cdm.json" for n in CASES] + [f"{n}.parsed.cdm.json" for n in CASES]
    )


def test_every_payload_is_listed_synthetic_and_every_binary_payload_has_its_twin():
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []


def test_the_builder_check_reads_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_each_twin_is_its_payload_inflated_by_the_standard_library(name):
    octets = (FIXTURES / f"{name}.trace").read_bytes()
    assert octets[:10] == bytes.fromhex("1f8b0800000000000203")
    assert json.loads(gzip.decompress(octets)) == _twin(name)


@pytest.mark.parametrize("name", CASES)
def test_the_two_goldens_of_a_pair_are_one_translation(name):
    from_octets = json.loads((GOLDEN / f"{name}.cdm.json").read_text(encoding="utf-8"))
    from_twin = json.loads((GOLDEN / f"{name}.parsed.cdm.json").read_text(encoding="utf-8"))
    assert from_octets == from_twin
    assert [o["object_kind"] for o in from_octets] == ["entity", "track", "event"]


@pytest.mark.parametrize("name", CASES)
def test_every_identifier_and_place_follows_the_fixture_convention(name):
    twin = _twin(name)
    assert support.aircraft_address_problems(twin["icao"].removeprefix("~")) == []
    assert support.positions_outside_the_rectangle(_translate(name)) == []
    stated = [{"lat": point[1], "lon": point[2]} for point in twin["trace"]]
    assert support.positions_outside_the_rectangle(stated) == []
    assert not {"r", "t", "desc", "ownOp", "year"} & set(twin), name


# ================================================================== one trace, every field


def test_the_airborne_trace_becomes_an_entity_a_track_and_an_event_as_written_by_hand():
    entity, track, event = _translate("airborne_adsb_2022_form")
    entity_id = _uuid("entity", "ICAO24", "0029C1")
    span = "0029C1@2026-03-14T10:00:00.120Z..2026-03-14T10:00:32.250Z"
    stamp = {
        "system": "READSB",
        "adapter": "readsb_trace",
        "adapter_version": "1.0.0",
        "synthetic": True,
        "format_name": "readsb trace JSON",
        "format_version": "readsb v3.16.17",
        "original_id": "0029c1",
        "source_hash": None,
        "record_index": None,
        "observed_at": "2026-03-14T00:00:00.000Z",
    }
    for obj in (entity, track, event):
        assert {k: v for k, v in obj["source"].items() if k != "transformations"} == stamp
        assert obj["source_ids"] == [{"system": "ICAO24", "external_id": "0029C1"}]
    assert [t.split(":", 1)[0] for t in entity["source"]["transformations"]] == [
        "icao",
        "trace[*][0]",
        "trace[-1][4]",
        "trace[-1][7]",
    ]
    assert [t.split(":", 1)[0] for t in track["source"]["transformations"]] == [
        "icao",
        "trace[*][0]",
    ]
    assert [t.split(":", 1)[0] for t in event["source"]["transformations"]] == [
        "icao",
        "trace[*][0]",
    ]

    assert entity["entity_id"] == entity_id
    assert (entity["entity_type"], entity["affiliation"]) == ("PLATFORM", "UNKNOWN")
    assert (entity["valid_from"], entity["valid_to"]) == (
        "2026-03-14T10:00:00.120Z",
        "2026-03-14T10:00:32.250Z",
    )
    assert entity["position"] == {
        "lat": 57.2039,
        "lon": 22.97482,
        "alt_m": None,
        "position_source": "GNSS",
        "accuracy_m": None,
        "vertical": {"value": 31950.0, "unit": "ft", "reference": "BARO", "uncertainty": None},
    }
    kinematics = entity["kinematics"]
    # 440.6 kt x 1852 m / 3600 s; 87.2 degrees is a course in the air; -128 ft/min x 0.00508.
    assert kinematics["speed_mps"] == pytest.approx(226.664222222, abs=1e-9)
    assert (kinematics["course_deg"], kinematics["climb_mps"]) == (87.2, pytest.approx(-0.65024))
    assert entity["quality"] == {
        "source_quality": "adsb_icao",
        "confidence": None,
        "accuracy_m": None,
        "uncertainty": {"rc_m": 186.0},
    }
    assert entity["attributes"]["readsb_samples"] == {
        "on_ground": [False, False, False, False],
        "element_5": ["track", "track", "track", "track"],
        "stale": [False, False, False, False],
        "new_leg": [False, False, False, False],
        "vertical_rate_geometric": [False, False, False, False],
        "altitude_geometric": [False, False, False, False],
        "elements": [14, 14, 14, 14],
    }
    assert "readsb_db_flags" not in entity["attributes"]
    assert entity["residual"] == {
        "namespace": "readsb trace JSON",
        "data": _twin("airborne_adsb_2022_form"),
    }

    assert track["track_id"] == _uuid("track", "ICAO24", span)
    assert track["entity_id"] == entity_id
    assert [s["observed_at"] for s in track["samples"]] == [
        "2026-03-14T10:00:00.120Z",
        "2026-03-14T10:00:10.370Z",
        "2026-03-14T10:00:21.500Z",
        "2026-03-14T10:00:32.250Z",
    ]
    assert [(s["position"]["lat"], s["position"]["lon"]) for s in track["samples"]] == [
        (57.201234, 22.912345),
        (57.20212, 22.93318),
        (57.203011, 22.954001),
        (57.2039, 22.97482),
    ]
    assert [s["position"]["vertical"]["value"] for s in track["samples"]] == [
        32000.0,
        32000.0,
        31975.0,
        31950.0,
    ]
    assert track["track_quality"] is None
    assert track["attributes"] == {
        "completeness": {
            "carried_samples": 4,
            "stated_samples": None,
            "fragment": True,
            "completeness_basis": (
                "carried_samples counts the trace's points; readsb writes one permanent trace per "
                "airframe per UTC day, so a file is a window of the airframe's history and never "
                "the whole of it; the trace states no total"
            ),
        }
    }
    assert track["residual"] == {
        "namespace": "readsb trace JSON",
        "data": {"icao": "0029c1", "timestamp": 1773446400.0},
    }

    assert event["event_id"] == _uuid("event", "ICAO24", span)
    assert (event["event_type"], event["severity"], event["geometry"]) == (
        "TRACK_UPDATE",
        "INFO",
        None,
    )
    assert event["related_entities"] == [entity_id]
    assert (event["observed_at"], event["received_at"], event["validity"]) == (
        "2026-03-14T10:00:32.250Z",
        FROZEN,
        None,
    )
    assert event["payload"]["track_id"] == track["track_id"]
    assert event["payload"]["sample_count"] == 4
    assert event["payload"]["observed_at_basis"] == (
        "the instant of the trace's last point: timestamp + element 0, on the aggregator's clock "
        "(readsb stamps a point with the system time at which the message reached it); the "
        "aircraft states no time"
    )
    assert event["residual"] == track["residual"]


def test_received_at_is_the_injected_clock_and_nothing_else_moves_with_it():
    import datetime as dt

    later = times.frozen_clock(dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.timezone.utc))
    first, second = _translate("mlat_positions"), _translate("mlat_positions", later)
    assert second[2]["received_at"] == "2026-05-01T12:00:00.000Z"
    second[2]["received_at"] = FROZEN
    assert first == second


# One row per fixture: the sample instants (each worked by hand from the fixture's midnight and
# element 0), each sample's position source and vertical, and the Entity's kinematics.
VERTICAL_BARO = "ft BARO"
ROWS = {
    "ground_heading_slot": (
        ["2026-03-14T08:03:20.000Z", "2026-03-14T08:03:50.500Z"],
        ["GNSS", "GNSS"],
        [None, None],
    ),
    "mlat_positions": (
        ["2026-03-14T12:00:00.000Z", "2026-03-14T12:00:15.750Z"],
        ["ESTIMATED", "ESTIMATED"],
        [(4500.0, VERTICAL_BARO, None), (4650.0, VERTICAL_BARO, None)],
    ),
    "tisb_positions": (
        ["2026-03-14T13:53:20.000Z", "2026-03-14T13:53:32.000Z"],
        ["ESTIMATED", "ESTIMATED"],
        [(2500.0, VERTICAL_BARO, None), (2500.0, VERTICAL_BARO, None)],
    ),
    "every_flag_bit": (
        [
            "2026-03-14T16:40:00.000Z",
            "2026-03-14T16:40:20.000Z",
            "2026-03-14T16:40:40.000Z",
            "2026-03-14T16:41:00.000Z",
            "2026-03-14T16:41:20.000Z",
            "2026-03-14T16:41:40.000Z",
        ],
        ["GNSS"] * 6,
        # Flag bit 3 makes element 3 geometric: 5000 ft = 1524.0 m and 12500 ft = 3810.0 m HAE,
        # and those are the only two that state alt_m.
        [
            (10000.0, VERTICAL_BARO, None),
            (10000.0, VERTICAL_BARO, None),
            (10000.0, VERTICAL_BARO, None),
            (10000.0, VERTICAL_BARO, None),
            (1524.0, "m HAE", 1524.0),
            (3810.0, "m HAE", 3810.0),
        ],
    ),
    "nonicao_address": (
        ["2026-03-14T11:00:00.000Z", "2026-03-14T11:00:12.400Z"],
        ["GNSS", "GNSS"],
        [(8000.0, VERTICAL_BARO, None), (8000.0, VERTICAL_BARO, None)],
    ),
    "pre2022_nine_elements": (
        ["2026-03-14T05:33:20.000Z", "2026-03-14T05:33:50.000Z"],
        ["ESTIMATED", "ESTIMATED"],
        [(6000.0, VERTICAL_BARO, None), (6100.0, VERTICAL_BARO, None)],
    ),
    "receiver_id_fifteen_elements": (
        ["2026-03-14T15:00:00.000Z", "2026-03-14T15:00:10.000Z"],
        ["GNSS", "GNSS"],
        [(15000.0, VERTICAL_BARO, None), (15000.0, VERTICAL_BARO, None)],
    ),
    # Element 3 null and element 10 1250 ft: 381.0 m HAE; the second point states no height.
    "null_altitude_and_speed": (
        ["2026-03-14T19:26:40.000Z", "2026-03-14T19:26:50.000Z"],
        ["ESTIMATED", "GNSS"],
        [(381.0, "m HAE", 381.0), None],
    ),
    "midnight_fragment_day_one": (
        ["2026-03-14T23:59:00.000Z", "2026-03-14T23:59:58.750Z"],
        ["GNSS", "GNSS"],
        [(3000.0, VERTICAL_BARO, None), (2500.0, VERTICAL_BARO, None)],
    ),
    "midnight_fragment_day_two": (
        ["2026-03-15T00:00:01.250Z", "2026-03-15T00:00:30.000Z"],
        ["GNSS", "GNSS"],
        [(2000.0, VERTICAL_BARO, None), (1500.0, VERTICAL_BARO, None)],
    ),
    # 1773486000.512 is 2026-03-14T11:00:00.512Z; + 5.48 s is 11:00:05.992.
    "reference_not_midnight": (
        ["2026-03-14T11:00:00.512Z", "2026-03-14T11:00:05.992Z"],
        ["GNSS", "GNSS"],
        [(20000.0, VERTICAL_BARO, None), (20000.0, VERTICAL_BARO, None)],
    ),
    "equal_instants_and_db_flags": (
        ["2026-03-14T13:00:00.000Z", "2026-03-14T13:00:00.000Z", "2026-03-14T13:00:10.500Z"],
        ["GNSS", "ESTIMATED", "GNSS"],
        [(18000.0, VERTICAL_BARO, None)] * 3,
    ),
}


def _vertical(position: dict):
    vertical = position["vertical"]
    if vertical is None:
        return None
    return (vertical["value"], f"{vertical['unit']} {vertical['reference']}", position["alt_m"])


@pytest.mark.parametrize("name", sorted(ROWS))
def test_each_trace_s_samples_are_its_points_in_file_order(name):
    instants, sources, verticals = ROWS[name]
    entity, track, event = _translate(name)
    assert [s["observed_at"] for s in track["samples"]] == instants
    assert [s["position"]["position_source"] for s in track["samples"]] == sources
    assert [_vertical(s["position"]) for s in track["samples"]] == verticals
    assert [(s["position"]["lat"], s["position"]["lon"]) for s in track["samples"]] == [
        (p[1], p[2]) for p in _twin(name)["trace"]
    ]
    assert all(s["position"]["accuracy_m"] is None for s in track["samples"])
    assert (entity["valid_from"], entity["valid_to"], event["observed_at"]) == (
        instants[0],
        instants[-1],
        instants[-1],
    )
    assert entity["position"] == track["samples"][-1]["position"]
    assert track["attributes"]["completeness"]["carried_samples"] == len(instants)
    assert event["payload"]["sample_count"] == len(instants)


def test_on_the_ground_element_5_is_a_true_heading_and_never_a_course():
    entity, track, _ = _translate("ground_heading_slot")
    assert entity["attributes"]["readsb_samples"]["on_ground"] == [True, True]
    assert entity["attributes"]["readsb_samples"]["element_5"] == ["true_heading", "true_heading"]
    assert entity["kinematics"]["course_deg"] is None
    assert entity["kinematics"]["climb_mps"] is None
    # 12.3 kt x 1852 / 3600: the ground speed while taxiing is still a speed.
    assert entity["kinematics"]["speed_mps"] == pytest.approx(6.327666667, abs=1e-9)
    assert [s["position"]["vertical"] for s in track["samples"]] == [None, None]
    assert entity["residual"]["data"]["trace"][1][5] == 181.9
    assert entity["attributes"]["vertical_basis"] == (
        "element 3 is ground: the aircraft is on the ground and no height is stated"
    )
    assert entity["quality"]["source_quality"] == "adsb_icao_nt"
    assert entity["quality"]["uncertainty"] == {"rc_m": 75.0}


def test_every_flag_bit_is_decoded_beside_its_raw_value_and_nothing_splits_on_a_new_leg():
    entity, track, _ = _translate("every_flag_bit")
    assert [p[6] for p in entity["residual"]["data"]["trace"]] == [0, 1, 2, 4, 8, 15]
    assert entity["attributes"]["readsb_samples"] == {
        "on_ground": [False] * 6,
        "element_5": ["track"] * 6,
        "stale": [False, True, False, False, False, True],
        "new_leg": [False, False, True, False, False, True],
        "vertical_rate_geometric": [False, False, False, True, False, True],
        "altitude_geometric": [False, False, False, False, True, True],
        "elements": [14] * 6,
    }
    assert len(track["samples"]) == 6
    # The last point's vertical rate is geometric by bit 2, and 64 ft/min is 0.32512 m/s.
    assert entity["kinematics"]["climb_mps"] == pytest.approx(0.32512)
    assert "geometric by flag bit 2" in entity["attributes"]["kinematics_basis"]
    assert [t.split(":", 1)[0] for t in track["source"]["transformations"]] == [
        "icao",
        "trace[*][0]",
        "trace[*][3], trace[*][10]",
    ]


def test_a_source_that_is_not_the_aircraft_s_own_fix_is_estimated_with_its_basis():
    expectations = {
        "mlat_positions": "element 9 is mlat: multilateration: the aggregator solved the position "
        "from arrival-time differences at several receivers; it is not the aircraft's own fix",
        "tisb_positions": "element 9 is tisb_trackfile: TIS-B track file: a ground station's "
        "track, typically from primary or Mode A/C radar",
        "pre2022_nine_elements": "the point has no element 9: a trace written before 2022 states "
        "no source for a position",
        "nonicao_address": "element 9 is adsb_other: the aircraft's own position report, received "
        "over ADS-B or rebroadcast over ADS-R, so the fix is its own navigation solution",
    }
    for name, basis in expectations.items():
        assert _translate(name)[0]["attributes"]["position_source_basis"] == basis, name


_OWN_FIX = (
    "the aircraft's own position report, received over ADS-B or rebroadcast over ADS-R, so the "
    "fix is its own navigation solution"
)
_TISB = "TIS-B: a ground station's rebroadcast of a track it derived by other means"

#: Element 9 -> (position_source, position_source_basis), written from README-json.md's list of
#: `type` strings and the brief's rule (ADS-B and ADS-R GNSS, everything else ESTIMATED).
SOURCE_TABLE = {
    "adsb_icao": ("GNSS", f"element 9 is adsb_icao: {_OWN_FIX}"),
    "adsb_icao_nt": ("GNSS", f"element 9 is adsb_icao_nt: {_OWN_FIX}"),
    "adsb_other": ("GNSS", f"element 9 is adsb_other: {_OWN_FIX}"),
    "adsr_icao": ("GNSS", f"element 9 is adsr_icao: {_OWN_FIX}"),
    "adsr_other": ("GNSS", f"element 9 is adsr_other: {_OWN_FIX}"),
    "mlat": (
        "ESTIMATED",
        "element 9 is mlat: multilateration: the aggregator solved the position from "
        "arrival-time differences at several receivers; it is not the aircraft's own fix",
    ),
    "tisb_icao": ("ESTIMATED", f"element 9 is tisb_icao: {_TISB}"),
    "tisb_other": ("ESTIMATED", f"element 9 is tisb_other: {_TISB}"),
    "tisb_trackfile": (
        "ESTIMATED",
        "element 9 is tisb_trackfile: TIS-B track file: a ground station's track, typically from "
        "primary or Mode A/C radar",
    ),
    "adsc": (
        "ESTIMATED",
        "element 9 is adsc: ADS-C received over a satellite downlink; the trace does not say how "
        "the report's position was obtained",
    ),
    "other": (
        "ESTIMATED",
        "element 9 is other: miscellaneous data the aggregator received in the Basestation/SBS "
        "form; the README states its quality and source are unknown",
    ),
    "mode_s": (
        "ESTIMATED",
        "element 9 is mode_s: Mode S data, which the README says transmits no position; the "
        "trace does not say where this point's position came from",
    ),
    "unknown": (
        "ESTIMATED",
        "element 9 is unknown: the aggregator states the source of the position is unknown",
    ),
}


def test_the_source_table_is_every_source_the_adapter_names():
    assert sorted(readsb_trace.POSITION_SOURCES) == sorted(SOURCE_TABLE)


@pytest.mark.parametrize("source", sorted(SOURCE_TABLE))
def test_every_listed_source_gives_its_member_and_basis_on_every_sample(source):
    document = _base()
    for point in document["trace"]:
        point[9] = source
    entity, track, _ = [o.model_dump(mode="json") for o in _adapter().to_cdm(document)]
    member, basis = SOURCE_TABLE[source]
    assert [s["position"]["position_source"] for s in track["samples"]] == [member] * 4
    assert entity["position"]["position_source"] == member
    assert entity["attributes"]["position_source_basis"] == basis
    assert entity["quality"]["source_quality"] == source


def test_a_null_and_an_absent_element_9_are_estimated_with_their_own_basis():
    nulled = _base()
    for point in nulled["trace"]:
        point[9] = None
    entity, track, _ = [o.model_dump(mode="json") for o in _adapter().to_cdm(nulled)]
    assert [s["position"]["position_source"] for s in track["samples"]] == ["ESTIMATED"] * 4
    assert entity["attributes"]["position_source_basis"] == (
        "the point's element 9 is null: the trace states no source for this position"
    )
    # The last point states rc 186, so Quality stands with no source quality.
    assert entity["quality"]["source_quality"] is None
    assert entity["quality"]["uncertainty"] == {"rc_m": 186.0}
    cut = _base()
    for point in cut["trace"]:
        del point[9:]
    entity, track, _ = [o.model_dump(mode="json") for o in _adapter().to_cdm(cut)]
    assert [s["position"]["position_source"] for s in track["samples"]] == ["ESTIMATED"] * 4
    assert entity["attributes"]["position_source_basis"] == (
        "the point has no element 9: a trace written before 2022 states no source for a position"
    )


def test_a_nine_element_trace_states_no_quality_and_its_points_are_kept_as_written():
    entity, _, _ = _translate("pre2022_nine_elements")
    assert entity["quality"] is None
    assert "version" not in entity["residual"]["data"]
    assert entity["attributes"]["readsb_samples"]["elements"] == [9, 9]
    assert entity["residual"]["data"]["trace"] == _twin("pre2022_nine_elements")["trace"]


def test_a_fifteenth_element_is_parked_whole_with_its_point():
    entity, _, _ = _translate("receiver_id_fifteen_elements")
    assert entity["attributes"]["readsb_samples"]["elements"] == [15, 15]
    assert [p[14] for p in entity["residual"]["data"]["trace"]] == ["00000001", "00000002"]


def test_nulls_stay_nulls_and_a_last_point_with_no_motion_has_no_kinematics():
    entity, _, _ = _translate("null_altitude_and_speed")
    assert entity["kinematics"] is None
    assert entity["position"]["vertical"] is None
    assert entity["residual"]["data"]["trace"][0][3:8] == [None, None, None, 0, None]
    assert entity["quality"] == {
        "source_quality": "adsb_icao",
        "confidence": None,
        "accuracy_m": None,
        "uncertainty": {},
    }


def test_database_flags_are_decoded_and_equal_instants_are_kept():
    entity, track, _ = _translate("equal_instants_and_db_flags")
    assert entity["attributes"]["readsb_db_flags"] == {
        "military": True,
        "interesting": False,
        "pia": False,
        "ladd": True,
        "unassigned_bits": 0,
    }
    assert track["samples"][0]["observed_at"] == track["samples"][1]["observed_at"]


def test_a_flight_across_utc_midnight_is_two_tracks_of_one_entity_and_nothing_is_stitched():
    day_one, day_two = (
        _translate("midnight_fragment_day_one"),
        _translate("midnight_fragment_day_two"),
    )
    entity_id = _uuid("entity", "ICAO24", "0029E7")
    assert day_one[0]["entity_id"] == day_two[0]["entity_id"] == entity_id
    assert day_one[1]["track_id"] == _uuid(
        "track", "ICAO24", "0029E7@2026-03-14T23:59:00.000Z..2026-03-14T23:59:58.750Z"
    )
    assert day_two[1]["track_id"] == _uuid(
        "track", "ICAO24", "0029E7@2026-03-15T00:00:01.250Z..2026-03-15T00:00:30.000Z"
    )
    assert [len(day_one[1]["samples"]), len(day_two[1]["samples"])] == [2, 2]
    assert day_one[1]["attributes"]["completeness"]["fragment"] is True
    assert day_two[1]["attributes"]["completeness"]["fragment"] is True
    # The new-leg flag on day two's first point is data, not a cut.
    assert day_two[0]["attributes"]["readsb_samples"]["new_leg"] == [True, False]


def test_two_files_of_one_airframe_over_one_span_share_their_ids_and_another_span_does_not():
    whole = _base()
    thinned = _base()
    del thinned["trace"][1]
    shorter = _base()
    del shorter["trace"][3]
    ids = [
        [o.model_dump(mode="json") for o in _adapter().to_cdm(d)] for d in (whole, thinned, shorter)
    ]
    span = "0029C1@2026-03-14T10:00:00.120Z..2026-03-14T10:00:32.250Z"
    assert ids[0][1]["track_id"] == ids[1][1]["track_id"] == _uuid("track", "ICAO24", span)
    assert ids[0][2]["event_id"] == ids[1][2]["event_id"] == _uuid("event", "ICAO24", span)
    assert [len(ids[0][1]["samples"]), len(ids[1][1]["samples"])] == [4, 3]
    other = "0029C1@2026-03-14T10:00:00.120Z..2026-03-14T10:00:21.500Z"
    assert ids[2][1]["track_id"] == _uuid("track", "ICAO24", other)
    assert ids[2][2]["event_id"] == _uuid("event", "ICAO24", other)
    limitation = {item.id: item.summary for item in ReadsbTraceAdapter.metadata.limitations}[
        "no-join-across-files"
    ]
    assert limitation == (
        "nothing is joined across files: a flight across UTC midnight is two files, two Tracks "
        "and one entity_id, and a new-leg flag is decoded as data and nothing is split on it. A "
        "Track's and its Event's ids derive from the address and the first and last instants, so "
        "two files of one airframe spanning the same two instants (two readsb instances' copies "
        "of one day, or a copy holding more points between them) give one track_id and one "
        "event_id: the id names the airframe's window, not the file, and files with different "
        "spans are different Tracks. Stitching, merging and leg-splitting are fusion's"
    )


# ================================================================== identity, across adapters


@pytest.mark.parametrize(
    ("frame", "trace", "system", "address"),
    [
        ("airborne_position_baro_gulf_of_riga", "airborne_adsb_2022_form", "ICAO24", "0029C1"),
        ("nonicao_anonymous_address", "nonicao_address", "ADSB_NONICAO", "0029B2"),
    ],
)
def test_a_frame_and_a_trace_of_one_airframe_have_one_entity_id(frame, trace, system, address):
    from_frame = AdsbAdapter(clock=times.frozen_clock()).to_cdm(
        (ADSB / f"{frame}.adsb").read_bytes()
    )
    from_trace = _translate(trace)
    assert from_frame[0].source_ids[0].system == system
    assert from_trace[0]["source_ids"] == [{"system": system, "external_id": address}]
    assert (
        str(from_frame[0].entity_id)
        == from_trace[0]["entity_id"]
        == _uuid("entity", system, address)
    )


# ================================================================== refusals


MALFORMED_REFUSALS = {
    "fewer_than_nine_elements": (
        "fewer-than-nine-elements",
        "trace[1] has 8 element(s); a point has at least 9",
    ),
    "offsets_not_monotonic": (
        "offsets-not-monotonic",
        "trace[2][0] is earlier than trace[1][0]; readsb writes a trace in time order and nothing "
        "here re-orders one",
    ),
    "negative_offset": ("negative-offset", "trace[0][0] is negative"),
    "latitude_out_of_range": (
        "coordinate-out-of-range",
        "trace[1][1] is outside [-90, 90] degrees",
    ),
    "longitude_out_of_range": (
        "coordinate-out-of-range",
        "trace[3][2] is outside [-180, 180] degrees",
    ),
    "ground_outside_element_three": (
        "ground-outside-element-3",
        "trace[2][4] is the string ground, which only element 3 may state",
    ),
    "timestamp_not_a_number": (
        "bad-timestamp",
        "timestamp is not a finite, non-negative number of seconds",
    ),
    "deflate_data_corrupt": (
        "does-not-inflate",
        "the gzip member does not inflate: its deflate data, its CRC or its length is wrong",
    ),
    "crc_mismatch": (
        "does-not-inflate",
        "the gzip member does not inflate: its deflate data, its CRC or its length is wrong",
    ),
    "truncated_gzip": (
        "truncated-gzip",
        "the gzip member ends before its deflate stream and trailer do",
    ),
    "trailing_octets_after_the_member": (
        "trailing-octets",
        "octets follow the gzip member; a trace file is exactly one member",
    ),
    "inflates_past_the_bound": (
        "inflates-past-the-bound",
        "the gzip member inflates past max_decompressed_bytes = 67108864; refused before the "
        "octet past the bound was kept",
    ),
    "truncated_json": ("not-json", "the inflated text is not one complete JSON document"),
    "not_gzip": (
        "not-gzip",
        "the octets do not begin with the gzip magic number; a trace file is one gzip member, "
        "and a decompressed document is handed over as a dict",
    ),
    "empty_trace": (
        "empty-trace",
        "trace holds no point, and a Track holds at least one sample",
    ),
    "unknown_top_level_key": (
        "unknown-key",
        "the document has 1 top-level key(s) outside the eleven readsb writes; an unknown key is "
        "refused rather than guessed at",
    ),
    "uppercase_address": (
        "bad-address",
        "icao is not six lower-case hexadecimal digits, with ~ first for a non-ICAO address",
    ),
    "flags_outside_four_bits": (
        "bad-flags",
        "trace[1][6] is not an integer holding only the four documented bits",
    ),
    "unknown_position_source": (
        "unknown-source",
        "trace[3][9] is not a position source README-json.md lists",
    ),
    "duplicate_key": (
        "duplicate-key",
        "an object states one key twice; readsb never writes that",
    ),
    "nan_literal": (
        "non-finite-number",
        "the text holds NaN or Infinity, which JSON does not define",
    ),
    "timestamp_past_a_double": (
        "bad-timestamp",
        "timestamp is not a finite, non-negative number of seconds",
    ),
    "lone_surrogate_in_version": (
        "not-unicode",
        "$.version holds a lone surrogate, which UTF-8 cannot carry",
    ),
}


def test_the_refusal_table_names_every_malformed_payload():
    assert sorted(MALFORMED_REFUSALS) == sorted(p.stem for p in MALFORMED.glob("*.trace"))


@pytest.mark.parametrize("name", sorted(MALFORMED_REFUSALS))
def test_each_malformed_payload_is_refused_with_its_code_and_its_whole_text(name):
    code, text = MALFORMED_REFUSALS[name]
    refusal = _refusal((MALFORMED / f"{name}.trace").read_bytes())
    assert refusal.code == code
    assert str(refusal) == f"{code}: {text}"


def _base() -> dict:
    return copy.deepcopy(_twin("airborne_adsb_2022_form"))


def _adapter() -> ReadsbTraceAdapter:
    return ReadsbTraceAdapter(clock=times.frozen_clock())


def _edit(path: tuple, value) -> dict:
    document = _base()
    node = document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return document


DICT_REFUSALS = [
    (
        "a point that is an object",
        _edit(("trace", 0), {"lat": 57.0}),
        "bad-point",
        "trace[0] is not an array",
    ),
    (
        "a text offset",
        _edit(("trace", 1, 0), "36010.37"),
        "bad-element",
        "trace[1][0] is not a finite number",
    ),
    (
        "a null latitude",
        _edit(("trace", 0, 1), None),
        "bad-element",
        "trace[0][1] is not a finite number",
    ),
    (
        "altitude text other than ground",
        _edit(("trace", 0, 3), "air"),
        "bad-element",
        "trace[0][3] is not a number, the string ground or null",
    ),
    (
        "a boolean ground speed",
        _edit(("trace", 0, 4), True),
        "bad-element",
        "trace[0][4] is not a finite number or null",
    ),
    (
        "a negative ground speed",
        _edit(("trace", 0, 4), -1.0),
        "bad-element",
        "trace[0][4] is a negative ground speed",
    ),
    (
        "a track past 360",
        _edit(("trace", 0, 5), 360.1),
        "bad-element",
        "trace[0][5] is outside [0, 360] degrees",
    ),
    (
        "a text roll",
        _edit(("trace", 0, 13), "left"),
        "bad-element",
        "trace[0][13] is not a finite number or null",
    ),
    (
        "a boolean flag",
        _edit(("trace", 0, 6), True),
        "bad-flags",
        "trace[0][6] is not an integer holding only the four documented bits",
    ),
    (
        "a negative flag",
        _edit(("trace", 0, 6), -1),
        "bad-flags",
        "trace[0][6] is not an integer holding only the four documented bits",
    ),
    (
        "an aircraft list",
        _edit(("trace", 0, 8), []),
        "bad-element",
        "trace[0][8] is not an object or null",
    ),
    (
        "a numeric source",
        _edit(("trace", 0, 9), 0),
        "bad-element",
        "trace[0][9] is not text or null",
    ),
    (
        "ground as a source",
        _edit(("trace", 0, 9), "ground"),
        "ground-outside-element-3",
        "trace[0][9] is the string ground, which only element 3 may state",
    ),
    (
        "a negative timestamp",
        _edit(("timestamp",), -1.0),
        "bad-timestamp",
        "timestamp is not a finite, non-negative number of seconds",
    ),
    (
        "a boolean timestamp",
        _edit(("timestamp",), True),
        "bad-timestamp",
        "timestamp is not a finite, non-negative number of seconds",
    ),
    (
        "a timestamp past 9999",
        _edit(("timestamp",), 253402300800.0),
        "instant-out-of-range",
        "trace[0]: timestamp + element 0 is not an instant between 1970 and 9999",
    ),
    (
        "a seven-digit address",
        _edit(("icao",), "0029c10"),
        "bad-address",
        "icao is not six lower-case hexadecimal digits, with ~ first for a non-ICAO address",
    ),
    (
        "a numeric address",
        _edit(("icao",), 10689),
        "bad-address",
        "icao is not six lower-case hexadecimal digits, with ~ first for a non-ICAO address",
    ),
    ("a numeric version", _edit(("version",), 3), "bad-header", "version is not text"),
    (
        "a negative dbFlags",
        _edit(("dbFlags",), -1),
        "bad-header",
        "dbFlags is not a non-negative integer",
    ),
    ("a text noRegData", _edit(("noRegData",), "true"), "bad-header", "noRegData is not a boolean"),
    ("a trace object", _edit(("trace",), {}), "bad-trace", "trace is not an array"),
    (
        "an injected unknown key",
        _edit(("__unknown",), 1),
        "unknown-key",
        "the document has 1 top-level key(s) outside the eleven readsb writes; an unknown key is refused rather than guessed at",
    ),
    (
        "no trace",
        {k: v for k, v in _base().items() if k != "trace"},
        "missing-key",
        "the document has no trace; every trace states them",
    ),
    (
        "a tuple in a parsed dict",
        _edit(("trace", 0, 8), {"nav_modes": ("althold",)}),
        "not-json-value",
        "$.trace[0][8].nav_modes is not a JSON value",
    ),
    (
        "NaN in a parsed dict",
        _edit(("trace", 0, 8), {"rc": float("nan")}),
        "not-json-value",
        "$.trace[0][8].rc is not a JSON value",
    ),
    (
        "a key that is not text",
        _edit(("trace", 0, 8), {1: "x"}),
        "not-json-value",
        "$.trace[0][8] (a key that is not text) is not a JSON value",
    ),
    (
        "a negative rc",
        _edit(("trace", 3, 8), {"rc": -1}),
        "bad-element",
        "trace[3][8].rc is not a non-negative finite number or null",
    ),
    (
        "a text rc on a point that is not the last",
        _edit(("trace", 0, 8), {"rc": "186"}),
        "bad-element",
        "trace[0][8].rc is not a non-negative finite number or null",
    ),
    (
        "a lone surrogate in a callsign",
        _edit(("trace", 0, 8), {"flight": "EX\udfff"}),
        "not-unicode",
        "$.trace[0][8].flight holds a lone surrogate, which UTF-8 cannot carry",
    ),
    (
        "a lone surrogate in a key",
        _edit(("trace", 0, 8), {"\ud800": 1}),
        "not-unicode",
        "$.trace[0][8] has a key holding a lone surrogate, which UTF-8 cannot carry",
    ),
]

#: An integer of 401 digits: JSON admits it, `json` reads it, and no double holds it.
HUGE = 10**400

#: (where, the edit, code, the whole text) for an integer past the double range in each place the
#: adapter reads a number; each is refused by the rule that element already has.
HUGE_REFUSALS = [
    (
        "timestamp",
        ("timestamp",),
        "bad-timestamp",
        "timestamp is not a finite, non-negative number of seconds",
    ),
    ("an offset", ("trace", 1, 0), "bad-element", "trace[1][0] is not a finite number"),
    ("a latitude", ("trace", 2, 1), "bad-element", "trace[2][1] is not a finite number"),
    ("a longitude", ("trace", 2, 2), "bad-element", "trace[2][2] is not a finite number"),
    (
        "an altitude",
        ("trace", 0, 3),
        "bad-element",
        "trace[0][3] is not a number, the string ground or null",
    ),
    (
        "a ground speed",
        ("trace", 3, 4),
        "bad-element",
        "trace[3][4] is not a finite number or null",
    ),
    ("a track", ("trace", 3, 5), "bad-element", "trace[3][5] is not a finite number or null"),
    (
        "a vertical rate",
        ("trace", 3, 7),
        "bad-element",
        "trace[3][7] is not a finite number or null",
    ),
    (
        "a geometric altitude",
        ("trace", 1, 10),
        "bad-element",
        "trace[1][10] is not a finite number or null",
    ),
    (
        "the last point's rc",
        ("trace", 3, 8, "rc"),
        "bad-element",
        "trace[3][8].rc is not a non-negative finite number or null",
    ),
    (
        "a negative one",
        ("trace", 0, 2),
        "bad-element",
        "trace[0][2] is not a finite number",
    ),
]


@pytest.mark.parametrize(
    ("path", "code", "text"),
    [row[1:] for row in HUGE_REFUSALS],
    ids=[row[0] for row in HUGE_REFUSALS],
)
@pytest.mark.parametrize("form", ["gzip", "dict"])
def test_an_integer_no_double_holds_is_refused_by_its_element_s_rule(form, path, code, text):
    value = -HUGE if path == ("trace", 0, 2) else HUGE
    document = _edit(path, value)
    payload = _member(document) if form == "gzip" else document
    if form == "gzip":
        # The integer reaches the adapter as JSON text, all 401 digits of it.
        assert (b"1" + b"0" * 400) in gzip.decompress(payload)
    refusal = _refusal(payload)
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")
    assert "0" * 400 not in str(refusal)


def test_a_large_integer_a_double_holds_is_still_read_by_its_rule():
    # 10**300 fits a double: the timestamp is a number and refused only as an instant past 9999.
    refusal = _refusal(_member(_edit(("timestamp",), 10**300)))
    assert (refusal.code, str(refusal)) == (
        "instant-out-of-range",
        "instant-out-of-range: trace[0]: timestamp + element 0 is not an instant between 1970 "
        "and 9999",
    )
    # An integer past the double range in a slot read for nothing stays carried as stated.
    document = _edit(("trace", 0, 8), {"rc": 186, "nic": HUGE})
    document["dbFlags"] = HUGE
    entity = _adapter().to_cdm(_member(document))[0]
    assert entity.residual.data["trace"][0][8]["nic"] == HUGE
    assert entity.attributes["readsb_db_flags"]["unassigned_bits"] == HUGE & ~15
    assert len(entity.model_dump_json()) > 400


@pytest.mark.parametrize(
    ("document", "code", "text"),
    [row[1:] for row in DICT_REFUSALS],
    ids=[row[0] for row in DICT_REFUSALS],
)
def test_a_parsed_document_is_held_to_the_same_grammar(document, code, text):
    refusal = _refusal(document)
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


@pytest.mark.parametrize(
    ("payload", "code", "text"),
    [
        (
            json.dumps({"icao": "0029c1"}),
            "unsupported-input",
            "a trace is handed over as its gzip octets or as the decompressed document in a dict; JSON text and other types are not taken",
        ),
        (
            [1, 2],
            "unsupported-input",
            "a trace is handed over as its gzip octets or as the decompressed document in a dict; JSON text and other types are not taken",
        ),
        (_member([1, 2]), "not-a-document", "the JSON document is not an object"),
        (gzip.compress(b"\xff\xfe", mtime=0), "not-utf-8", "the inflated octets are not UTF-8"),
        (
            gzip.compress(b"x", mtime=0) + gzip.compress(b"y", mtime=0),
            "trailing-octets",
            "octets follow the gzip member; a trace file is exactly one member",
        ),
    ],
    ids=["text", "a list", "an array document", "not utf-8", "two members"],
)
def test_what_is_not_one_trace_document_is_refused(payload, code, text):
    refusal = _refusal(payload)
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


def test_inflation_is_held_to_the_declared_bound_and_one_octet_past_it_is_refused():
    bound = ReadsbTraceAdapter.metadata.capabilities.limits.max_decompressed_bytes
    assert bound == readsb_trace.MAX_DECOMPRESSED_BYTES == 67108864
    at_bound = gzip.compress(b" " * bound, mtime=0)
    assert len(readsb_trace.inflate(at_bound)) == bound
    over = gzip.compress(b" " * (bound + 1), mtime=0)
    assert len(over) < ReadsbTraceAdapter.metadata.capabilities.limits.max_input_bytes
    with pytest.raises(ReadsbTraceRefused) as raised:
        ReadsbTraceAdapter(clock=times.frozen_clock()).to_cdm(over)
    assert str(raised.value) == (
        "inflates-past-the-bound: the gzip member inflates past max_decompressed_bytes = "
        "67108864; refused before the octet past the bound was kept"
    )
    # The same rule at a small bound, either side of it.
    assert readsb_trace.inflate(gzip.compress(b"0123456789", mtime=0), limit=10) == b"0123456789"
    with pytest.raises(ReadsbTraceRefused, match="^inflates-past-the-bound: .* = 9;"):
        readsb_trace.inflate(gzip.compress(b"0123456789", mtime=0), limit=9)


def _points(count: int) -> dict:
    """The airborne fixture's document with its first point repeated `count` times: equal
    instants are allowed (D-R2-4), so every copy is a point the grammar admits."""
    document = _base()
    document["trace"] = [copy.deepcopy(document["trace"][0]) for _ in range(count)]
    return document


def test_the_point_bound_is_declared_with_its_basis():
    assert readsb_trace.MAX_POINTS == 100000
    basis = readsb_trace.MAX_POINTS_BASIS
    assert basis.kind is LimitKind.IMPLEMENTATION_CAP
    assert "86 400 points" in basis.source and "L-24" in basis.source
    assert "IMPLEMENTATION CAP and is NOT the format's normative maximum" in basis.source
    assert basis.test == (
        "tests/test_cdm_readsb_trace_adapter.py::"
        "test_a_trace_past_the_point_bound_is_refused_before_any_point_is_read"
    )
    reason = ReadsbTraceAdapter.metadata.capabilities.limits.absent_because["max_objects"]
    assert "MAX_POINTS = 100000 per trace" in reason


TOO_MANY_POINTS = (
    "too-many-points",
    "too-many-points: trace holds more than max_points = 100000 points; refused before any "
    "point is read",
)


def test_a_trace_past_the_point_bound_is_refused_before_any_point_is_read():
    """DECISIONS L-24: 100 001 points, the first of them not even a point. The refusal is the
    bound's, so the count was compared before the first point was walked; the text states the
    bound and never the count."""
    document = _points(100001)
    document["trace"][0] = {"lat": 57.0}
    refusal = _refusal(document)
    assert (refusal.code, str(refusal)) == TOO_MANY_POINTS
    assert "100001" not in str(refusal)
    # The same through the gzip member, the form a trace file has.
    refusal = _refusal(_member(_points(100001)))
    assert (refusal.code, str(refusal)) == TOO_MANY_POINTS


def test_a_trace_at_the_point_bound_reaches_the_point_grammar():
    """100 000 points pass the bound: the last one, not a point, is refused by the grammar, which
    walks them all; no model is built for a trace this test does not let through."""
    document = _points(100000)
    document["trace"][99999] = {"lat": 57.0}
    refusal = _refusal(document)
    assert (refusal.code, str(refusal)) == ("bad-point", "bad-point: trace[99999] is not an array")


def test_the_level_is_not_read_and_any_level_inflates_to_the_same_objects():
    octets = json.dumps(_twin("mlat_positions")).encode("utf-8")
    translations = [
        [
            o.model_dump(mode="json")
            for o in ReadsbTraceAdapter(clock=times.frozen_clock()).to_cdm(
                gzip.compress(octets, compresslevel=level, mtime=0)
            )
        ]
        for level in (1, 5, 9)
    ]
    assert translations[0] == translations[1] == translations[2] == _translate("mlat_positions")


def test_an_inflated_document_past_the_depth_bound_is_refused_before_it_is_decoded():
    text = ("[" * 65 + "]" * 65).encode("ascii")
    with pytest.raises(InputTooDeep) as raised:
        ReadsbTraceAdapter(clock=times.frozen_clock()).to_cdm(gzip.compress(text, mtime=0))
    assert str(raised.value) == (
        "readsb_trace inflated a JSON document nesting 65 containers deep and declares "
        "max_depth = 64. Refused before json.loads: every walk that follows a parse descends "
        "one frame per level"
    )
    assert not isinstance(raised.value, RecursionError)


def test_a_gzip_member_with_a_wrong_length_does_not_inflate():
    member = (FIXTURES / "mlat_positions.trace").read_bytes()
    length = struct.unpack("<I", member[-4:])[0] + 1
    with pytest.raises(ReadsbTraceRefused, match="^does-not-inflate: "):
        readsb_trace.inflate(member[:-4] + struct.pack("<I", length))


def test_a_refusal_survives_a_copy_and_a_pickle_round_trip():
    refusal = _refusal((MALFORMED / "empty_trace.trace").read_bytes())
    for twin in (copy.copy(refusal), pickle.loads(pickle.dumps(refusal))):
        assert type(twin) is ReadsbTraceRefused
        assert (twin.code, str(twin)) == (refusal.code, str(refusal))
    assert isinstance(refusal, ValueError)
