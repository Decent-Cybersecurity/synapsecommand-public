"""The invariants. Each test here exists because breaking it puts a wrong thing on a map.

The null-never-zero family is inherited from the Track contract (chapters 8-9) and is the
reason this file is longer than the models it checks.
"""
import datetime as _dt
import uuid

import pytest
from pydantic import ValidationError

from synapse_cdm import times, version
from synapse_cdm.enums import (
    Affiliation, EntityType, EventType, InterferenceType, ObjectType, PositionSource, Severity,
)
from synapse_cdm.geo import LineString, Point, Polygon
from synapse_cdm.models import (
    Entity, Event, Integrity, Kinematics, PlanObject, Position, SourceId, SourceRef, Track,
    TrackSample,
)
from synapse_cdm.symbology import affiliation_from_cot, sidc_from_affiliation, standard_identity

SOURCE = SourceRef(system="TEST", adapter="test", adapter_version="1.0.0", synthetic=True)
IDS = [SourceId(system="TEST", external_id="X-1")]
T0 = "2026-04-29T06:00:00Z"


def _entity(**overrides):
    kwargs = dict(source=SOURCE, source_ids=IDS, entity_id=uuid.uuid4(),
                  entity_type=EntityType.UNIT, affiliation=Affiliation.UNKNOWN, valid_from=T0)
    kwargs.update(overrides)
    return Entity(**kwargs)


# --- the null-never-zero family --------------------------------------------------------------

def test_unknown_position_has_no_position_object_at_all():
    """Structural: there is no way to spell 'unknown' as zeros, because lat/lon are required."""
    assert _entity().position is None
    with pytest.raises(ValidationError):
        Position(position_source=PositionSource.GNSS)          # no coordinates
    with pytest.raises(ValidationError):
        Position(lat=57.5, position_source=PositionSource.GNSS)  # half a position


def test_coordinate_zero_is_a_real_coordinate_and_is_accepted():
    """The rule is 'unknown is null', NOT '(0,0) is illegal' — 0.0 is a latitude.

    A `if not lat` check anywhere on the path discards the equator and the Greenwich meridian.
    That is the mirror-image defect of null-to-zero and just as silent.
    """
    position = Position(lat=0.0, lon=0.0, position_source=PositionSource.GNSS)
    assert position.lat == 0.0 and position.lon == 0.0
    assert _entity(position=position).position.lon == 0.0


def test_unknown_scalars_are_none_never_zero():
    kinematics = Kinematics()
    assert kinematics.speed_mps is None and kinematics.course_deg is None
    # ... and zero remains expressible, because 0 kt is measured stillness.
    assert Kinematics(speed_mps=0.0, course_deg=0.0).speed_mps == 0.0
    assert _entity().confidence is None
    assert _entity(confidence=0.0).confidence == 0.0


def test_out_of_range_values_are_refused():
    for bad in ({"lat": 91.0, "lon": 0.0}, {"lat": 0.0, "lon": 181.0}):
        with pytest.raises(ValidationError):
            Position(position_source=PositionSource.GNSS, **bad)
    with pytest.raises(ValidationError):
        Kinematics(course_deg=360.0)     # [0, 360), 360 is 0
    with pytest.raises(ValidationError):
        Kinematics(speed_mps=-1.0)
    with pytest.raises(ValidationError):
        _entity(confidence=1.5)


# --- provenance and versioning ---------------------------------------------------------------

def test_every_kind_requires_source_ids():
    """The gap the harness found on its first run — see CDMBase's docstring."""
    for kind, kwargs in (
        (Entity, dict(entity_id=uuid.uuid4(), entity_type=EntityType.UNKNOWN,
                      affiliation=Affiliation.UNKNOWN, valid_from=T0)),
        (Event, dict(event_id=uuid.uuid4(), event_type=EventType.ALERT,
                     severity=Severity.INFO, observed_at=T0, received_at=T0)),
        (Track, dict(track_id=uuid.uuid4(), entity_id=uuid.uuid4(),
                     samples=[TrackSample(position=Position(
                         lat=1.0, lon=1.0, position_source=PositionSource.GNSS),
                         observed_at=T0)])),
        (PlanObject, dict(object_id=uuid.uuid4(), object_type=ObjectType.ROUTE,
                          geometry=Point(coordinates=[1.0, 2.0]))),
    ):
        with pytest.raises(ValidationError):
            kind(source=SOURCE, source_ids=[], **kwargs)
        assert kind(source=SOURCE, source_ids=IDS, **kwargs).source_ids == IDS


def test_synthetic_has_no_default():
    """Neither direction is safe to guess, so the field must be stated."""
    with pytest.raises(ValidationError):
        SourceRef(system="S", adapter="a", adapter_version="1.0.0")


def test_schema_version_is_stamped_and_semver_checked():
    assert _entity().schema_version == version.SCHEMA_VERSION
    with pytest.raises(ValidationError):
        _entity(schema_version="1.0")
    assert version.compatible("1.2.0", "1.0.0"), "a MINOR from the future must still be read"
    assert not version.compatible("2.0.0", "1.0.0")


def test_integrity_is_all_three_fields_or_none():
    assert _entity().integrity is None
    block = Integrity(signature="sig", algorithm="ML-DSA-87", chain_hash="deadbeef")
    assert _entity(integrity=block).integrity.algorithm == "ML-DSA-87"
    with pytest.raises(ValidationError):
        Integrity(signature="sig")


def test_unknown_fields_are_refused_so_the_bag_is_used_instead():
    with pytest.raises(ValidationError):
        _entity(vessel_flag="LV")
    assert _entity(attributes={"vessel_flag": "LV"}).attributes["vessel_flag"] == "LV"


# --- time ------------------------------------------------------------------------------------

def test_timestamps_render_to_one_form_only():
    for written in ("2026-04-29T06:12:44Z", "2026-04-29T06:12:44.000Z",
                    "2026-04-29T08:12:44+02:00", "2026-04-29T06:12:44"):
        assert times.render(times.parse(written)) == "2026-04-29T06:12:44.000Z"
    assert times.TIMESTAMP_RE.match(times.render(times.FROZEN_NOW))


def test_render_truncates_rather_than_rounds():
    """Rounding 23:59:59.9995 forward moves an event into the next day's audit slice."""
    stamp = _dt.datetime(2026, 4, 29, 23, 59, 59, 999500, tzinfo=_dt.timezone.utc)
    assert times.render(stamp) == "2026-04-29T23:59:59.999Z"


def test_interval_may_not_run_backwards():
    with pytest.raises(ValidationError):
        _entity(valid_from="2026-04-29T07:00:00Z", valid_to="2026-04-29T06:00:00Z")


def test_serialised_timestamps_are_strings_in_the_pinned_form():
    dumped = _entity(valid_from="2026-04-29T06:12:44Z").model_dump(mode="json")
    assert dumped["valid_from"] == "2026-04-29T06:12:44.000Z"


# --- geometry --------------------------------------------------------------------------------

def test_geojson_is_lon_lat_and_a_swap_is_caught():
    point = Point(coordinates=[21.884, 57.512])
    assert (point.lon, point.lat) == (21.884, 57.512)
    with pytest.raises(ValidationError):
        Point(coordinates=[57.512, 121.884])   # swapped: 121.884 is not a latitude


def test_polygon_rings_must_be_closed():
    ring = [[21.6, 57.3], [22.1, 57.3], [22.1, 57.7], [21.6, 57.3]]
    assert Polygon(coordinates=[ring])
    with pytest.raises(ValidationError):
        Polygon(coordinates=[[[21.6, 57.3], [22.1, 57.3], [22.1, 57.7], [21.6, 57.7]]])
    with pytest.raises(ValidationError):
        Polygon(coordinates=[[[21.6, 57.3], [22.1, 57.3], [21.6, 57.3]]])   # too few


def test_unsupported_geometry_is_refused_not_passed_through():
    with pytest.raises(ValidationError):
        Event(source=SOURCE, source_ids=IDS, event_id=uuid.uuid4(),
              event_type=EventType.DETECTION, severity=Severity.INFO,
              observed_at=T0, received_at=T0,
              geometry={"type": "MultiPolygon", "coordinates": []})


def test_linestring_needs_two_positions():
    assert LineString(coordinates=[[21.0, 57.0], [21.5, 57.5]])
    with pytest.raises(ValidationError):
        LineString(coordinates=[[21.0, 57.0]])


# --- symbology -------------------------------------------------------------------------------

def test_sidc_is_twenty_digits_and_carries_the_standard_identity():
    for affiliation in Affiliation:
        sidc = sidc_from_affiliation(affiliation, synthetic=False)
        assert len(sidc) == 20 and sidc.isdigit()
        assert sidc[3] == standard_identity(affiliation)
    with pytest.raises(ValidationError):
        _entity(symbol="SFGPUCI-----")       # 2525C, not 2525D


def test_synthetic_objects_get_the_simulation_context_digit():
    """An exercise contact must not render identically to a live one."""
    assert sidc_from_affiliation(Affiliation.HOSTILE, synthetic=True)[2] == "2"
    assert sidc_from_affiliation(Affiliation.HOSTILE, synthetic=False)[2] == "0"


def test_cot_affiliation_never_overstates_what_is_known():
    assert affiliation_from_cot("a-f-G-U-C") == Affiliation.FRIENDLY
    assert affiliation_from_cot("a-h-A-M-F") == Affiliation.HOSTILE
    # A suspect is not hostile and an assumed friend is not a friend.
    assert affiliation_from_cot("a-s-G") == Affiliation.UNKNOWN
    assert affiliation_from_cot("a-a-G") == Affiliation.UNKNOWN
    # Malformed input yields UNKNOWN rather than losing the contact.
    assert affiliation_from_cot("") == Affiliation.UNKNOWN
    assert affiliation_from_cot("nonsense") == Affiliation.UNKNOWN


def test_every_vocabulary_can_say_unknown_without_using_null():
    assert Affiliation.UNKNOWN and EntityType.UNKNOWN and InterferenceType.UNKNOWN


# --- tracks and plan objects -----------------------------------------------------------------

def _sample(when, lat=57.0):
    return TrackSample(position=Position(lat=lat, lon=21.0,
                                         position_source=PositionSource.GNSS), observed_at=when)


def test_track_samples_must_be_in_time_order():
    ordered = [_sample("2026-04-29T06:00:00Z"), _sample("2026-04-29T06:01:00Z")]
    assert Track(source=SOURCE, source_ids=IDS, track_id=uuid.uuid4(),
                 entity_id=uuid.uuid4(), samples=ordered)
    with pytest.raises(ValidationError):
        Track(source=SOURCE, source_ids=IDS, track_id=uuid.uuid4(), entity_id=uuid.uuid4(),
              samples=list(reversed(ordered)))


def test_equal_sample_timestamps_are_allowed():
    """Two sensors reporting the same instant is real data, not a defect."""
    same = [_sample("2026-04-29T06:00:00Z"), _sample("2026-04-29T06:00:00Z", lat=57.1)]
    assert len(Track(source=SOURCE, source_ids=IDS, track_id=uuid.uuid4(),
                     entity_id=uuid.uuid4(), samples=same).samples) == 2


def test_plan_object_requires_geometry():
    with pytest.raises(ValidationError):
        PlanObject(source=SOURCE, source_ids=IDS, object_id=uuid.uuid4(),
                   object_type=ObjectType.ROUTE)


def test_plan_object_label_is_never_an_empty_string():
    with pytest.raises(ValidationError):
        PlanObject(source=SOURCE, source_ids=IDS, object_id=uuid.uuid4(),
                   object_type=ObjectType.ANNOTATION, label="",
                   geometry=Point(coordinates=[21.0, 57.0]))


# --- event payloads --------------------------------------------------------------------------

def _event(**overrides):
    kwargs = dict(source=SOURCE, source_ids=IDS, event_id=uuid.uuid4(),
                  event_type=EventType.GNSS_INTERFERENCE, severity=Severity.WARNING,
                  observed_at=T0, received_at=T0,
                  payload={"frequency_band": "L1", "interference_type": "JAMMING"})
    kwargs.update(overrides)
    return Event(**kwargs)


def test_registered_payload_is_validated_but_not_rewritten():
    event = _event(payload={"frequency_band": "L1", "interference_type": "SPOOFING",
                            "vendor_field": 7})
    assert event.payload["vendor_field"] == 7, "extra keys must survive byte-identically"
    assert event.typed_payload().interference_type is InterferenceType.SPOOFING


def test_a_bad_registered_payload_is_refused():
    with pytest.raises(ValidationError):
        _event(payload={"interference_type": "JAMMING"})            # no frequency_band
    with pytest.raises(ValidationError):
        _event(payload={"frequency_band": "L1", "interference_type": "MICROWAVE"})


def test_an_unregistered_event_type_keeps_a_free_payload():
    event = _event(event_type=EventType.SIM_RESULT, payload={"anything": [1, 2, 3]})
    assert event.typed_payload() is None and event.payload["anything"] == [1, 2, 3]
