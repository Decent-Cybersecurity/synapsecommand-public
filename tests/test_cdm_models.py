"""The invariants. Each test here exists because breaking it puts a wrong thing on a map.

The null-never-zero family is inherited from the Track contract (chapters 8-9) and is the
reason this file is longer than the models it checks.
"""
import datetime as _dt
import json
import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from synapse_cdm import times, version
from synapse_cdm.enums import (
    Affiliation, EntityType, EventType, InterferenceType, ObjectType, PositionSource, Severity,
    VerticalReference, VerticalUnit,
)
from synapse_cdm.geo import (
    BoundingBox, LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon,
    VerticalExtent, VerticalPosition,
)
from synapse_cdm.models import (
    Area, CDMObject, Entity, Event, Integrity, Kinematics, OperationalStatus, Period, PlanObject,
    Position, Quality, Residual, Route, RouteLeg, SourceHash, SourceId, SourceRef,
    TemporalValidity, Track, TrackSample, Waypoint,
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


# --- P3: the CDM foundation primitives (spec §23-§30) ----------------------------------------
#
# One section, and every test in it takes a reading or proves a refusal. The refusals are the
# half that matters: each one is a defect that would otherwise be silent, and a model that only
# proves its happy path proves that the fields exist, not that they mean anything.

_RING = [[21.0, 57.0], [22.0, 57.0], [22.0, 58.0], [21.0, 57.0]]
_LINE = LineString(coordinates=[[21.0, 57.0], [22.0, 58.0]])


def _track(**overrides):
    kwargs = dict(source=SOURCE, source_ids=IDS, track_id=uuid.uuid4(),
                  entity_id=uuid.uuid4(), samples=[_sample(T0)])
    kwargs.update(overrides)
    return Track(**kwargs)


def _plan_object(**overrides):
    kwargs = dict(source=SOURCE, source_ids=IDS, object_id=uuid.uuid4(),
                  object_type=ObjectType.ROUTE, geometry=_LINE)
    kwargs.update(overrides)
    return PlanObject(**kwargs)


def _hae(value=100.0):
    return VerticalPosition(value=value, unit=VerticalUnit.METRES,
                            reference=VerticalReference.HAE)


def _waypoint(sequence, lat=57.0, lon=21.0, **kw):
    return Waypoint(position=Position(lat=lat, lon=lon, position_source=PositionSource.GNSS),
                    sequence=sequence, **kw)


# --- geometry: the union widened, and what stayed out -----------------------------------------

def test_the_three_multi_geometries_are_in_the_union_and_carry_lon_lat():
    """§24's "multi-geometry where justified". Each is reached through `Event.geometry`."""
    for geometry in (MultiPoint(coordinates=[[21.0, 57.0], [22.0, 58.0]]),
                     MultiLineString(coordinates=[[[21.0, 57.0], [22.0, 58.0]]]),
                     MultiPolygon(coordinates=[[_RING]])):
        event = _event(geometry=geometry)
        assert event.geometry.type == geometry.type
        # The wire form is GeoJSON's, so the FIRST number is the longitude, everywhere.
        dumped = event.model_dump(mode="json")["geometry"]["coordinates"]
        assert json.dumps(dumped).find("21.0") < json.dumps(dumped).find("57.0")


def test_a_multi_geometry_catches_the_coordinate_swap_in_every_part():
    """The guard is `_check_lonlat` and it must reach INSIDE the parts, not just the outer list."""
    for bad in (lambda: MultiPoint(coordinates=[[21.0, 57.0], [57.5, 91.0]]),
                lambda: MultiLineString(coordinates=[[[21.0, 57.0], [57.5, 91.0]]]),
                lambda: MultiPolygon(coordinates=[[[[21.0, 57.0], [57.5, 91.0],
                                                    [22.0, 58.0], [21.0, 57.0]]]])):
        with pytest.raises(ValidationError, match=r"latitude 91.0 outside"):
            bad()


def test_a_multipolygon_ring_must_be_closed_in_every_part():
    """`Polygon`'s rule, enforced per part rather than inherited by hope."""
    open_ring = [[21.0, 57.0], [22.0, 57.0], [22.0, 58.0], [21.5, 57.5]]
    with pytest.raises(ValidationError, match=r"part 0 ring 0 is not closed"):
        MultiPolygon(coordinates=[[open_ring]])


def test_a_multilinestring_part_needs_two_positions():
    with pytest.raises(ValidationError, match=r"part 0 has 1 position"):
        MultiLineString(coordinates=[[[21.0, 57.0]]])


def test_geometrycollection_is_still_refused_rather_than_passed_through():
    """Excluded DELIBERATELY (P3 default 6). A refusal, not an omission — so it is proved."""
    with pytest.raises(ValidationError):
        _event(geometry={"type": "GeometryCollection", "geometries": []})


def test_a_bounding_box_is_named_and_min_may_not_exceed_max():
    box = BoundingBox(min_lon=21.0, min_lat=57.0, max_lon=22.0, max_lat=58.0)
    assert (box.min_lon, box.max_lat) == (21.0, 58.0)
    with pytest.raises(ValidationError, match=r"min_lat 58.0 exceeds max_lat 57.0"):
        BoundingBox(min_lon=21.0, min_lat=58.0, max_lon=22.0, max_lat=57.0)


def test_the_antimeridian_box_is_refused_and_the_message_says_why():
    """RFC 7946 §5.2 would read this as crossing 180°; the same numbers read as a huge box."""
    with pytest.raises(ValidationError, match=r"antimeridian"):
        BoundingBox(min_lon=170.0, min_lat=-10.0, max_lon=-170.0, max_lat=10.0)


# --- vertical position: value, unit, reference ------------------------------------------------

def test_a_vertical_position_states_its_unit_and_its_datum():
    v = VerticalPosition(value=8000.0, unit=VerticalUnit.FEET,
                         reference=VerticalReference.MSL, uncertainty=50.0)
    assert v.model_dump(mode="json") == {"value": 8000.0, "unit": "ft",
                                         "reference": "MSL", "uncertainty": 50.0}


def test_a_flight_level_is_a_scale_and_a_datum_and_must_be_both_or_neither():
    VerticalPosition(value=350.0, unit=VerticalUnit.FLIGHT_LEVEL,
                     reference=VerticalReference.FL)
    for unit, reference in ((VerticalUnit.FLIGHT_LEVEL, VerticalReference.MSL),
                            (VerticalUnit.FEET, VerticalReference.FL)):
        with pytest.raises(ValidationError, match=r"must appear in both or in neither"):
            VerticalPosition(value=350.0, unit=unit, reference=reference)


def test_alt_m_and_vertical_must_agree_when_the_datum_really_is_hae_metres():
    position = Position(lat=57.0, lon=21.0, position_source=PositionSource.GNSS,
                        alt_m=100.0, vertical=_hae(100.0))
    assert position.alt_m == position.vertical.value
    with pytest.raises(ValidationError, match=r"alt_m 101.0 disagrees with vertical 100.0 m HAE"):
        Position(lat=57.0, lon=21.0, position_source=PositionSource.GNSS,
                 alt_m=101.0, vertical=_hae(100.0))


def test_alt_m_stays_none_when_the_source_altitude_is_not_hae():
    """Rule 2 in its sharpest form: no silent MSL-to-HAE conversion, not even an exact one."""
    msl = VerticalPosition(value=1000.0, unit=VerticalUnit.FEET,
                           reference=VerticalReference.MSL)
    ok = Position(lat=57.0, lon=21.0, position_source=PositionSource.GNSS, vertical=msl)
    assert ok.alt_m is None
    with pytest.raises(ValidationError, match=r"alt_m means metres"):
        Position(lat=57.0, lon=21.0, position_source=PositionSource.GNSS,
                 alt_m=304.8, vertical=msl)


def test_a_vertical_extent_may_have_neither_bound_and_that_is_information():
    """"Surface to unlimited" is two absences; the block's PRESENCE is the fact it carries."""
    assert VerticalExtent().model_dump(mode="json") == {"lower": None, "upper": None}


def test_the_vertical_unit_vocabulary_has_no_unknown_and_the_reference_one_does():
    """The asymmetry is the unit policy (§26), so it is asserted rather than left to a docstring."""
    assert not hasattr(VerticalUnit, "UNKNOWN")
    assert VerticalReference.UNKNOWN


# --- temporal validity ------------------------------------------------------------------------

def test_the_four_times_are_separable_and_all_four_are_optional():
    empty = TemporalValidity()
    assert empty.model_dump(mode="json") == {"observed_at": None, "valid_from": None,
                                             "valid_to": None, "effective": None}
    full = TemporalValidity(observed_at=T0, valid_from=T0, valid_to="2026-04-29T07:00:00Z",
                            effective=Period(start="2026-04-29T06:30:00Z"))
    assert full.effective.end is None


def test_an_interval_that_runs_backwards_is_refused_in_both_models():
    with pytest.raises(ValidationError, match=r"precedes start"):
        Period(start="2026-04-29T07:00:00Z", end=T0)
    with pytest.raises(ValidationError, match=r"precedes valid_from"):
        TemporalValidity(valid_from="2026-04-29T07:00:00Z", valid_to=T0)


def test_the_epoch_sentinel_is_a_real_instant_and_is_not_refused_by_the_type():
    """F3.2: the §27 rule is DOCUMENTED, not validated. This test records which was chosen.

    `Timestamp` accepts 1970-01-01T00:00:00.000Z because it is a real instant some sources
    legitimately carry. The rule "unknown time MUST NOT become 1970-01-01" binds the ADAPTER,
    and refusing the instant here would refuse real data to catch a defect one layer up.
    """
    entity = _entity(valid_from="1970-01-01T00:00:00Z")
    assert times.render(entity.valid_from) == "1970-01-01T00:00:00.000Z"


# --- route ------------------------------------------------------------------------------------

def test_a_route_needs_two_waypoints():
    with pytest.raises(ValidationError, match=r"at least 2 items|too_short"):
        Route(waypoints=[_waypoint(0)])


def test_route_sequences_are_the_order_of_record_and_may_not_repeat():
    with pytest.raises(ValidationError, match=r"both carry sequence 1"):
        Route(waypoints=[_waypoint(1), _waypoint(1, lat=58.0)])


def test_a_leg_may_not_name_a_sequence_no_waypoint_carries():
    with pytest.raises(ValidationError, match=r"leg 0's to_seq is 9"):
        Route(waypoints=[_waypoint(0), _waypoint(1, lat=58.0)],
              legs=[RouteLeg(from_seq=0, to_seq=9)])


def test_a_leg_may_not_run_from_a_waypoint_to_itself():
    with pytest.raises(ValidationError, match=r"to itself"):
        RouteLeg(from_seq=2, to_seq=2)


def test_a_route_with_no_legs_is_legal_and_no_legs_are_invented():
    route = Route(waypoints=[_waypoint(0), _waypoint(1, lat=58.0)])
    assert route.legs == []


# --- area -------------------------------------------------------------------------------------

def test_an_area_takes_a_polygon_or_a_multipolygon_and_nothing_else():
    Area(geometry=Polygon(coordinates=[_RING]))
    Area(geometry=MultiPolygon(coordinates=[[_RING]]))
    with pytest.raises(ValidationError):
        Area(geometry=Point(coordinates=[21.0, 57.0]))


def test_an_areas_bounds_are_the_sources_own_and_are_not_computed():
    area = Area(geometry=Polygon(coordinates=[_RING]),
                bounds=BoundingBox(min_lon=0.0, min_lat=0.0, max_lon=1.0, max_lat=1.0))
    # Deliberately disjoint from the geometry: nothing cross-checks them, because a sensor's
    # declared coverage rectangle and its footprint's envelope are different facts.
    assert area.bounds.max_lon == 1.0


# --- quality, status, residual on every object ------------------------------------------------

def test_quality_status_and_residual_reach_every_kind():
    """F3.4: they attach to CDMBase, so all four schemas carry them."""
    for obj in (_entity(), _event(), _track(), _plan_object()):
        dumped = obj.model_dump(mode="json")
        assert dumped["quality"] is None and dumped["status"] is None
        assert dumped["residual"] is None


def test_an_operational_status_must_name_whose_vocabulary_it_is_in():
    OperationalStatus(state="SERVICEABLE", namespace="STANAG4586")
    with pytest.raises(ValidationError):
        OperationalStatus(state="SERVICEABLE", namespace="")


def test_a_residual_must_name_its_origin():
    """§28's first rule. An unnamespaced bag of leftovers is the dict this model replaces."""
    block = Residual(namespace="PNTMAP GNSS interference alert", data={"vendor": {"fw": "3.1"}})
    assert block.data["vendor"]["fw"] == "3.1"
    with pytest.raises(ValidationError):
        Residual(namespace="", data={})


def test_quality_uncertainty_is_named_components_and_the_unit_is_in_the_key():
    q = Quality(confidence=0.87, uncertainty={"along_track_m": 40.0, "cross_track_m": 12.0})
    assert q.uncertainty["along_track_m"] == 40.0
    assert q.source_quality is None and q.accuracy_m is None


# --- plan object: route, area, validity, and the projection that must not drift ---------------

def test_plan_object_geometry_stays_required_beside_route_and_area():
    """Every consumer written before routes existed still reads one required GeoJSON field."""
    with pytest.raises(ValidationError):
        _plan_object(geometry=None)
    plan = _plan_object(route=Route(waypoints=[_waypoint(0), _waypoint(1, lat=58.0)]))
    assert plan.geometry.type == "LineString" and plan.route is not None


def test_expires_at_is_the_projection_of_valid_to_and_may_not_disagree():
    end = "2026-04-29T07:00:00Z"
    _plan_object(expires_at=end, validity=TemporalValidity(valid_to=end))
    with pytest.raises(ValidationError, match=r"expires_at .* disagrees with validity.valid_to"):
        _plan_object(expires_at=end, validity=TemporalValidity(valid_to="2026-04-29T08:00:00Z"))


# --- Rule 5: the provenance fields ------------------------------------------------------------

def test_the_source_ref_carries_rule_5s_six_missing_items():
    ref = SourceRef(system="TEST", adapter="test", adapter_version="1.0.0", synthetic=True,
                    format_name="ASTERIX", format_version="Cat 062 ed 1.18",
                    original_id="REC-9", record_index=3, observed_at=T0,
                    source_hash=SourceHash(algorithm="sha256", value="ab" * 32),
                    transformations=["knots to metres per second"])
    dumped = ref.model_dump(mode="json")
    assert dumped["format_name"] == "ASTERIX" and dumped["record_index"] == 3
    assert dumped["transformations"] == ["knots to metres per second"]


def test_record_index_is_zero_based_and_never_negative():
    """0 is the FIRST record, not "unknown" — so a negative sentinel is refused outright."""
    assert SourceRef(system="T", adapter="t", adapter_version="1.0.0", synthetic=True,
                     record_index=0).record_index == 0
    with pytest.raises(ValidationError):
        SourceRef(system="T", adapter="t", adapter_version="1.0.0", synthetic=True,
                  record_index=-1)


# --- §29: backwards compatibility, proved on a real pre-round object --------------------------

#: A golden object as it stood at `v2.0.0`, pasted here as a FIXTURE OF THE CLAIM rather than
#: read from `fixtures/`: the files under `fixtures/` are regenerated by this very round, so a
#: test that read one would be asserting that 2.1.0 data validates under 2.1.0 models. This is
#: the bytes a consumer holding output from the previous tag actually has.
GOLDEN_AT_2_0_0 = {
    "affiliation": "HOSTILE",
    "attributes": {"entity_id_basis": "emitter.emitter_id", "interference_type": "jamming"},
    "confidence": 0.87,
    "entity_id": "2bcbebf2-45ac-511c-a635-f115c0b9b7ac",
    "entity_type": "INTERFERENCE_SOURCE",
    "integrity": None,
    "kinematics": None,
    "object_kind": "entity",
    "ontology_types": [],
    "position": {"accuracy_m": 2500.0, "alt_m": None, "lat": 57.512, "lon": 21.884,
                 "position_source": "ESTIMATED"},
    "schema_version": "2.0.0",
    "source": {"adapter": "pntmap", "adapter_version": "1.0.0", "synthetic": True,
               "system": "PNTMAP"},
    "source_ids": [{"external_id": "EMT-4471", "system": "PNTMAP"}],
    "symbol": "10260000000000000000",
    "valid_from": "2026-04-29T06:12:44.000Z",
    "valid_to": "2026-04-29T07:00:00.000Z",
}


def test_a_two_zero_zero_object_still_validates_against_the_two_one_zero_models():
    """§29's first clause, on the bytes rather than on the assertion that it holds."""
    revived = Entity.model_validate(GOLDEN_AT_2_0_0)
    assert revived.schema_version == "2.0.0"          # NOT rewritten to the current version
    assert revived.position.vertical is None and revived.quality is None
    assert revived.residual is None and revived.status is None
    assert revived.source.format_name is None         # the new provenance fields default absent


def test_a_two_zero_zero_reader_accepts_a_two_one_zero_object():
    """The other direction, which is what makes the additions safe to deploy one node at a time."""
    assert version.compatible(version.SCHEMA_VERSION, "2.0.0") is True
    assert version.compatible("2.0.0", version.SCHEMA_VERSION) is True
    assert version.compatible("1.0.0", version.SCHEMA_VERSION) is False


def test_the_union_still_discriminates_every_kind_after_the_widening():
    """`CDMObject` is what a mixed-stream consumer validates against; four kinds, still four."""
    adapter = TypeAdapter(CDMObject)
    for obj in (_entity(), _event(), _track(), _plan_object()):
        assert adapter.validate_python(obj.model_dump(mode="json")).object_kind == obj.object_kind
