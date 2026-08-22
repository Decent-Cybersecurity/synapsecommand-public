"""One test per claim in the Legion adapter's docstring, and one per settled design decision.

WHAT IS DIFFERENT ABOUT THIS SUITE
----------------------------------
The other three bidirectional adapters put their strongest claim in a byte-exact round trip.
This adapter is INGEST ONLY — Legion's egress-shaped resource is Tasking, and a task has no
geometry while `PlanObject.geometry` is required — so there is no round trip to assert and the
weight moves elsewhere:

- **the coordinate reading**, because `crs` defaults to geocentric metres and the position object
  is shaped like GeoJSON. Getting this wrong produces well-formed CDM objects in the wrong place,
  which no schema check can catch. The transform is pinned against an independently written
  forward conversion rather than against itself;
- **the three kinds of absence**, because a JSON API can be silent in ways a wire format cannot;
- **the refusals**, because an adapter that guesses is worse than one that stops.
"""
import json
import math
import pathlib
import uuid

import pytest

import synapse_cdm
from synapse_cdm import ids, lossless, times
from synapse_cdm.adapters import legion
from synapse_cdm.adapters.legion import LegionAdapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import Entity, Event, Track

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "legion"
GOLDEN = FIXTURES / "golden"
SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "schemas"

DOCUMENTS = sorted(FIXTURES.glob("*.json"))


def _adapter() -> LegionAdapter:
    return LegionAdapter(clock=times.frozen_clock())


def _translate(name: str):
    return _adapter().to_cdm(json.loads((FIXTURES / name).read_text()))


def _edited(name: str, **changes):
    """A fixture with top-level keys replaced — how the negative cases are built.

    Editing a copy rather than shipping a fixture per refusal: a refusal fixture would have to be
    a document the adapter cannot read, which the harness would replay and fail on.
    """
    document = json.loads((FIXTURES / name).read_text())
    for key, value in changes.items():
        if value is _ABSENT:
            document.pop(key, None)
        else:
            document[key] = value
    return document


_ABSENT = object()


# --------------------------------------------------------------- the fixture set


def test_the_fixture_set_is_not_silently_empty():
    assert len(DOCUMENTS) >= 6, f"expected >=6 Legion fixtures, found {len(DOCUMENTS)}"
    kinds = {_adapter()._kind(json.loads(p.read_text())) for p in DOCUMENTS}
    assert kinds == {"entity", "location", "event", "locations_list"}, (
        f"the fixture set covers document kinds {sorted(kinds)}; all four in scope need one, "
        "because a kind with no fixture is a dispatch branch with no evidence"
    )


def test_the_reference_document_is_not_in_the_replay_path():
    """`harness.run()` feeds every FILE to `to_cdm()`, so the spec pin lives in a subdirectory.

    Pinned because the failure is confusing rather than obvious: the pin file is valid JSON, so
    it reaches the dispatcher and fails as an unrecognised document rather than as a misplaced
    file.
    """
    assert not (FIXTURES / "openapi_pin.json").exists()
    assert (FIXTURES / "spec" / "openapi_pin.json").is_file()


# ------------------------------------------------------ the coordinate transform


def test_the_ecef_transform_is_pinned_against_an_independent_forward_conversion():
    """The claim that matters most, checked against arithmetic written separately here.

    `ecef_to_geodetic` cannot be validated against itself, and no fixture can validate it either
    — a fixture is only ever as right as the conversion that made it. So the forward transform is
    written out from the published definition and the two are composed: geodetic -> ECEF ->
    geodetic must return the input.
    """
    def forward(lat, lon, h):
        la, lo = math.radians(lat), math.radians(lon)
        n = legion.WGS84_A / math.sqrt(1 - legion.WGS84_E2 * math.sin(la) ** 2)
        return ((n + h) * math.cos(la) * math.cos(lo),
                (n + h) * math.cos(la) * math.sin(lo),
                (n * (1 - legion.WGS84_E2) + h) * math.sin(la))

    worst = 0.0
    for lat in (-89.9, -60.0, -23.5, 0.0, 23.5, 56.9236, 89.9):
        for lon in (-179.9, -90.0, 0.0, 23.9711, 179.9):
            for height in (-400.0, 0.0, 8848.0, 400000.0):
                back = legion.ecef_to_geodetic(*forward(lat, lon, height))
                worst = max(worst,
                            abs(back[0] - lat) * 111320.0,
                            abs(back[1] - lon) * 111320.0 * math.cos(math.radians(lat)),
                            abs(back[2] - height))
    assert worst < 0.01, f"worst round-trip error {worst * 1000:.3f} mm exceeds 10 mm"


def test_the_ellipsoid_constants_are_wgs84():
    """A typo here moves every contact, so the published numbers are asserted literally."""
    assert legion.WGS84_A == 6378137.0
    assert legion.WGS84_INVERSE_FLATTENING == 298.257223563
    assert round(legion.WGS84_B, 6) == 6356752.314245
    assert abs(legion.WGS84_E2 - 0.0066943799901414) < 1e-15


def test_the_poles_and_the_equator_are_exact():
    """`atan2(0, 0)` on the polar axis is why this case is handled explicitly."""
    assert legion.ecef_to_geodetic(0.0, 0.0, legion.WGS84_B) == (90.0, 0.0, 0.0)
    assert legion.ecef_to_geodetic(0.0, 0.0, -legion.WGS84_B) == (-90.0, 0.0, 0.0)
    assert legion.ecef_to_geodetic(legion.WGS84_A, 0.0, 0.0) == (0.0, 0.0, 0.0)


def test_an_absent_crs_is_read_as_geocentric_metres():
    """The single mapping most likely to be got wrong, and the reason `crs` is parked.

    The fixture omits `crs` entirely. Read as `[lon, lat]` — the reasonable guess given the
    GeoJSON-shaped object — this mast would land at longitude 3 188 199, which `Position` would
    reject; read as ECEF it is the Riga coordinate it was built from.
    """
    entity, _ = _translate("entity_sensor_mast_riga.json")
    assert (entity.position.lat, entity.position.lon) == (56.9236, 23.9711)
    assert entity.attributes["legion_position"]["coordinates"] == [
        3188199.36, 1417551.34, 5321282.59]
    assert "crs" not in entity.attributes["legion_position"], (
        "an absent crs must not be recorded as null — this adapter insists absent and null are "
        "different facts and may not conflate them in its own output"
    )
    assert "crs ABSENT" in entity.attributes["position_basis"]
    assert "EPSG:4978" in entity.attributes["position_basis"]
    assert "Bowring/Ferrari" in entity.attributes["position_basis"]
    assert "6378137.0" in entity.attributes["position_basis"]


def test_a_stated_lla_crs_is_used_without_conversion_and_in_the_documented_axis_order():
    entity, _ = _translate("entity_location_lla_ventspils.json")
    assert (entity.position.lat, entity.position.lon) == (57.3908, 21.5606)
    assert entity.position.alt_m == 8.0
    assert "No conversion applied" in entity.attributes["position_basis"]
    assert entity.attributes["legion_position"]["crs"] == "EPSG:4326"


def test_the_position_is_a_derived_one_way_view_and_the_source_coordinates_are_the_record():
    """Settlement 1. The verbatim copy is why TRANSFORMS carries no coordinate exemption."""
    for name in ("entity_sensor_mast_riga.json", "entity_location_ecef_gulf_of_riga.json",
                 "entity_location_lla_ventspils.json"):
        objects = _translate(name)
        entity = next(o for o in objects if isinstance(o, Entity))
        verbatim = entity.attributes["legion_position"]["coordinates"]
        document = json.loads((FIXTURES / name).read_text())
        stated = ((document.get("location_latest") or document).get("position") or {}
                  ).get("coordinates")
        assert verbatim == stated, f"{name}: the source coordinates were not re-emitted verbatim"
    assert not any("position" in path or "coordinates" in path
                   for path in LegionAdapter.TRANSFORMS), (
        "a coordinate exemption in TRANSFORMS means the verbatim copy is not doing its job"
    )


def test_epsg_4979_is_refused_by_name():
    """In the enum, defined in no document, and its registry axis order is the reverse of 4326."""
    with pytest.raises(ValueError, match="defined in no document"):
        _adapter().to_cdm(_edited("entity_location_lla_ventspils.json", crs="EPSG:4979"))


def test_an_unknown_crs_is_refused_rather_than_assumed():
    with pytest.raises(ValueError, match="not in the API's enum"):
        _adapter().to_cdm(_edited("entity_location_lla_ventspils.json", crs="EPSG:3857"))


def test_a_geocentric_position_with_two_coordinates_is_refused():
    """Inferring the third would invent a location."""
    document = _edited("entity_location_ecef_gulf_of_riga.json")
    document["position"]["coordinates"] = [3133607.51, 1384778.07]
    with pytest.raises(ValueError, match="needs three"):
        _adapter().to_cdm(document)


def test_non_numeric_coordinates_are_refused_rather_than_coerced():
    document = _edited("entity_location_lla_ventspils.json")
    document["position"]["coordinates"] = ["21.5606", "57.3908"]
    with pytest.raises(ValueError, match="not all numbers"):
        _adapter().to_cdm(document)


def test_a_geometry_type_outside_the_schemas_pattern_is_refused():
    document = _edited("entity_location_lla_ventspils.json")
    document["position"]["type"] = "MultiPolygon"
    with pytest.raises(ValueError, match="not one of"):
        _adapter().to_cdm(document)


# ------------------------------------------------------------------- timestamps


def test_the_accepted_grammar_is_what_the_settlement_says_it_is():
    """Settlement 2, the accepting half: four forms in, one instant out."""
    base = "entity_location_lla_ventspils.json"
    for value, expected in (
            ("2026-04-29T06:09:30Z", "2026-04-29T06:09:30.000Z"),
            ("2026-04-29T08:09:30+02:00", "2026-04-29T06:09:30.000Z"),
            ("2026-04-29T06:09:30.123456Z", "2026-04-29T06:09:30.123Z"),
            ("2026-04-29T06:09:30", "2026-04-29T06:09:30.000Z"),
    ):
        _, event = _adapter().to_cdm(_edited(base, recorded_at=value))
        assert times.render(event.observed_at) == expected, value


def test_fractional_seconds_are_truncated_and_never_rounded():
    """Rounding 23:59:59.9995 forward moves an event into the next day's audit slice."""
    _, event = _adapter().to_cdm(_edited("entity_location_lla_ventspils.json",
                                         recorded_at="2026-04-29T23:59:59.9995Z"))
    assert times.render(event.observed_at) == "2026-04-29T23:59:59.999Z"


def test_a_naive_timestamp_is_assumed_utc_and_the_assumption_is_declared():
    """Silence here makes one document parse differently on a laptop and in the enclave."""
    _, event = _adapter().to_cdm(_edited("entity_location_lla_ventspils.json",
                                         recorded_at="2026-04-29T06:09:30"))
    assert "UTC assumed" in event.payload["observed_at_basis"]
    _, stated = _adapter().to_cdm(_edited("entity_location_lla_ventspils.json",
                                          recorded_at="2026-04-29T06:09:30Z"))
    assert "UTC assumed" not in stated.payload["observed_at_basis"]


@pytest.mark.parametrize("value", ["yesterday", "2026-13-45T99:99:99Z", "06:09:30", "",
                                   "29/04/2026 06:09"])
def test_an_unparseable_observed_at_parks_the_document_and_never_invents_an_instant(value):
    """Settlement 2, the refusing half — the whole point of the settlement.

    It must RAISE, and the message must name the value and the grammar. It must not fall back to
    the receipt clock: a fabricated instant is unfalsifiable downstream, where a refused document
    is visible to the caller.
    """
    with pytest.raises(ValueError) as raised:
        _adapter().to_cdm(_edited("entity_location_lla_ventspils.json", recorded_at=value))
    message = str(raised.value)
    assert repr(value) in message, "the refusal must quote the offending value"
    assert "accepted grammar" in message or "not a time" in message
    assert "invented instant" in message or "no honest substitute" in message


def test_an_absent_timestamp_falls_back_through_the_chain_and_records_which_link():
    """ABSENT is a different fact from UNPARSEABLE, and only one of them is a refusal."""
    _, event = _adapter().to_cdm(_edited("entity_location_lla_ventspils.json",
                                         recorded_at=_ABSENT))
    assert times.render(event.observed_at) == "2026-04-29T06:09:31.000Z"
    assert "created_at" in event.payload["observed_at_basis"]
    assert "recorded_at was absent" in event.payload["observed_at_basis"]


def test_a_null_timestamp_is_the_api_asserting_it_has_none_and_is_also_refused():
    """`null` is a claim, so falling back would substitute our clock for a stated absence."""
    with pytest.raises(ValueError, match="no honest substitute"):
        _adapter().to_cdm(_edited("event_gunshot_detection.json", event_timestamp=None))


def test_the_source_timestamp_string_survives_verbatim():
    """The CDM re-renders to fixed milliseconds, so the exact form Legion sent is kept beside it."""
    entity, event = _translate("entity_sensor_mast_riga.json")
    assert entity.attributes["legion_updated_at"] == "2026-04-29T06:14:00Z"
    assert event.payload["legion_created_at"] == "2026-04-29T06:14:02Z"
    assert times.render(entity.valid_from) == "2026-04-29T06:14:00.000Z"


# --------------------------------------------------------- the three absences


def test_a_stated_null_is_unavailable_and_an_absent_key_is_not():
    """The JSON-native sentinel discipline, which has no wire-format analogue.

    `required` in OpenAPI constrains the document, not the world: a required-and-nullable field
    carrying null is the API asserting "you will always be told, and the answer is nothing".
    """
    entity = _translate("entity_exercise_affiliation_and_nulls.json")[0]
    stated = set(entity.attributes["unavailable_fields"])
    assert {"parent_id", "top_classification", "top_classification_probability",
            "deleted_at"} <= stated
    # Absent keys are NOT claims of ignorance and must not appear.
    assert "classification" not in stated and "metadata" not in stated


def test_the_six_structurally_absent_embedded_fields_are_not_unavailable_fields():
    """Settlement 4. Conflating the two would invent six assertions per document."""
    entity, _ = _translate("entity_location_lla_ventspils.json")
    stated = set(entity.attributes["unavailable_fields"])
    for field in legion.EMBEDDED_ENTITY_OMITS:
        assert field not in stated, (
            f"{field} is missing from the embedded entity SCHEMA, which is a fact about the "
            "API's shape and not a claim about the world"
        )
    basis = entity.attributes["embedded_entity_basis"]
    for field in legion.EMBEDDED_ENTITY_OMITS:
        assert field in basis, f"{field} is not named in embedded_entity_basis"
    assert "NOT a claim" in basis
    # And the standalone path must NOT carry the note, or it says nothing.
    standalone, _ = _translate("entity_sensor_mast_riga.json")
    assert "embedded_entity_basis" not in standalone.attributes


def test_the_omitted_field_list_is_what_the_pinned_spec_says_it_is():
    """The six are read off the pinned document rather than trusted as a constant."""
    pin = json.loads((FIXTURES / "spec" / "openapi_pin.json").read_text())
    standalone = {f for f in pin["resources"]["Entity"]["fields"] if "." not in f}
    embedded = {f.split(".", 1)[1] for f in pin["resources"]["Location"]["fields"]
                if f.startswith("entity.") and f.count(".") == 1}
    assert set(legion.EMBEDDED_ENTITY_OMITS) == standalone - embedded, (
        "EMBEDDED_ENTITY_OMITS disagrees with the pinned spec: "
        f"spec says {sorted(standalone - embedded)}"
    )


def test_an_empty_value_is_stated_and_empty_rather_than_unknown():
    """`{}` is ambiguous in the spec and is parked verbatim rather than read as absence."""
    entity, _ = _translate("entity_sensor_mast_riga.json")
    assert entity.attributes["legion_classification"] == {}
    assert "classification" not in entity.attributes["unavailable_fields"]


# ------------------------------------------------------------------ identity


def test_the_legion_id_becomes_the_source_id_and_the_entity_id_is_derived_from_it():
    entity, _ = _translate("entity_sensor_mast_riga.json")
    legion_id = "f1c70000-0001-8000-8000-000000000001"
    assert [(s.system, s.external_id) for s in entity.source_ids] == [("LEGION", legion_id)]
    assert entity.entity_id == ids.derive("LEGION", legion_id, kind="entity")
    assert entity.attributes["entity_id_basis"] == "Legion entity id"


def test_the_event_is_keyed_on_the_report_and_not_on_the_entity():
    """A location id is unique per report, so two fixes are two events on one entity."""
    entity, event = _translate("entity_location_ecef_gulf_of_riga.json")
    assert event.event_id == ids.derive(
        "LEGION", "f1c70000-0002-8000-8000-000000000002", kind="event")
    assert event.related_entities == [entity.entity_id]
    assert event.event_id != entity.entity_id


def test_a_document_with_no_identifier_is_refused():
    for missing in ({"id": None}, {"id": ""}, {"id": _ABSENT}):
        with pytest.raises(ValueError, match="identifier is required"):
            _adapter().to_cdm(_edited("entity_sensor_mast_riga.json", **missing))


# --------------------------------------------------------------- affiliation


@pytest.mark.parametrize("raw,expected", sorted(
    (k, v) for k, v in legion.AFFILIATION.items()))
def test_every_legion_affiliation_maps_and_the_original_is_recoverable(raw, expected):
    entity = _translate("entity_exercise_affiliation_and_nulls.json")[0]
    document = _edited("entity_exercise_affiliation_and_nulls.json", affiliation=raw)
    entity = _adapter().to_cdm(document)[0]
    assert entity.affiliation == expected
    assert entity.attributes["legion_affiliation"] == raw, (
        "the collapse is recoverable only if the original survives"
    )


def test_the_collapse_does_not_round_towards_a_claim():
    """The two directions that matter: an assumption is not a fact, suspicion is not identity."""
    assert legion.AFFILIATION["ASSUMED_FRIEND"] is Affiliation.UNKNOWN
    assert legion.AFFILIATION["SUSPECT"] is Affiliation.UNKNOWN
    entity = _adapter().to_cdm(_edited("entity_exercise_affiliation_and_nulls.json",
                                       affiliation="SUSPECT"))[0]
    assert entity.affiliation is Affiliation.UNKNOWN
    assert "NOT HOSTILE" in entity.attributes["affiliation_basis"]


def test_the_exercise_marking_is_recorded_separately_and_never_rewrites_source_synthetic():
    """The split, and the line it must not cross.

    `source.synthetic` is a declaration about the FEED, set once at construction. Legion's
    EXERCISE_* is a fact about one CONTACT. Letting payload content rewrite a provenance flag
    would be an adapter deciding provenance, which adapters may not do.
    """
    entity = _translate("entity_exercise_affiliation_and_nulls.json")[0]
    assert entity.affiliation is Affiliation.FRIENDLY
    assert entity.attributes["affiliation_exercise"]["legion_affiliation"] == "EXERCISE_FRIEND"
    assert entity.source.synthetic is True          # the adapter default, not the payload

    live = LegionAdapter(clock=times.frozen_clock(), synthetic=False)
    entity = live.to_cdm(json.loads(
        (FIXTURES / "entity_exercise_affiliation_and_nulls.json").read_text()))[0]
    assert entity.source.synthetic is False, (
        "an EXERCISE_ affiliation must not flip source.synthetic — that flag describes the feed"
    )
    assert entity.attributes["affiliation_exercise"] is not None, (
        "the object-level exercise fact must still be recorded"
    )
    assert entity.symbol[2] == "0", "the symbol context digit follows the FEED declaration"


def test_a_plain_affiliation_carries_no_exercise_marking():
    entity, _ = _translate("entity_sensor_mast_riga.json")
    assert "affiliation_exercise" not in entity.attributes


def test_an_unknown_affiliation_value_is_read_as_unknown_rather_than_guessed():
    entity = _adapter().to_cdm(_edited("entity_exercise_affiliation_and_nulls.json",
                                       affiliation="ALLY_OF_CONVENIENCE"))[0]
    assert entity.affiliation is Affiliation.UNKNOWN
    assert "not one of the fifteen" in entity.attributes["affiliation_basis"]


# ------------------------------------------------------------------ category


@pytest.mark.parametrize("category,expected", sorted(legion.CATEGORY.items()))
def test_every_legion_category_maps_and_the_raw_value_is_parked(category, expected):
    entity = _adapter().to_cdm(_edited("entity_exercise_affiliation_and_nulls.json",
                                       category=category))[0]
    assert entity.entity_type == expected
    assert entity.attributes["legion_category"] == category
    assert entity.attributes["entity_type_basis"]


def test_the_report_like_categories_do_not_become_things_that_exist():
    """DETECTION, ALERT and TRACK name a report ABOUT something, not a thing on the map."""
    for category in ("DETECTION", "ALERT", "TRACK", "WEATHER", "DEVICE"):
        assert legion.CATEGORY[category] is EntityType.UNKNOWN, category


# --------------------------------------------------------------- kinematics


def test_the_bearing_becomes_a_course_and_a_full_circle_is_reduced_to_zero():
    """`course_deg` is [0, 360) and the schema admits 360 inclusive — the CoT reduction."""
    entity, _ = _translate("entity_location_lla_ventspils.json")
    assert entity.kinematics.course_deg == 0.0, "bearing 360 must become 0, the same bearing"
    entity, _ = _translate("entity_location_ecef_gulf_of_riga.json")
    assert entity.kinematics.course_deg == 187.5


def test_the_speed_is_parked_and_never_written_as_metres_per_second():
    """Its units are undocumented and the spec's own speed and velocity examples disagree.

    This is the ADS-B altitude lesson applied before the fact rather than after it.
    """
    entity, _ = _translate("entity_location_ecef_gulf_of_riga.json")
    assert entity.kinematics.speed_mps is None
    extras = entity.attributes["source_extras"]
    assert extras["speed"] == 7.1, "the value must survive even though it cannot be mapped"
    for vector in ("velocity", "acceleration", "angular_velocity", "orientation", "covariance"):
        assert vector in extras, f"{vector} must be parked, not dropped"
    assert extras["orientation"] == [0.707, 0, 0, 0.707]


def test_a_bearing_outside_the_schemas_range_is_refused_rather_than_wrapped():
    document = _edited("entity_location_ecef_gulf_of_riga.json", bearing=451.0)
    with pytest.raises(ValueError, match="refusing to wrap"):
        _adapter().to_cdm(document)


def test_no_bearing_means_no_kinematics_rather_than_a_zero_course():
    document = _edited("entity_location_ecef_gulf_of_riga.json", bearing=_ABSENT)
    entity, _ = _adapter().to_cdm(document)
    assert entity.kinematics is None, "0.0 is due north, which is a measurement"


# --------------------------------------------------------------- confidence


def test_the_classification_probability_becomes_confidence_and_the_label_is_parked():
    """gap 12: the number has a home, the label does not."""
    entity, _ = _translate("entity_sensor_mast_riga.json")
    assert entity.confidence == 0.91
    assert entity.attributes["legion_top_classification"] == "STRUCTURE"


def test_an_absent_probability_is_unknown_and_not_zero():
    """confidence 0 is certainty-that-not, which is a claim nobody made."""
    entity = _translate("entity_exercise_affiliation_and_nulls.json")[0]
    assert entity.confidence is None


@pytest.mark.parametrize("value", [1.4, -0.1])
def test_a_probability_outside_the_unit_interval_is_refused_rather_than_clamped(value):
    """A clamped 1.4 becomes a confident maximum and hides the source defect."""
    with pytest.raises(ValueError, match="Refusing to clamp"):
        _adapter().to_cdm(_edited("entity_sensor_mast_riga.json",
                                  top_classification_probability=value))


# ------------------------------------------------------------------ intervals


def test_a_deletion_beats_an_expiry_and_the_basis_says_which_won():
    """A deletion is a fact; an expiry is a schedule."""
    entity = _translate("entity_exercise_affiliation_and_nulls.json")[0]
    assert times.render(entity.valid_to) == "2026-04-29T18:00:00.000Z"
    assert "expires_at" in entity.attributes["valid_to_basis"]

    both = _adapter().to_cdm(_edited("entity_exercise_affiliation_and_nulls.json",
                                     deleted_at="2026-04-29T07:00:00Z"))[0]
    assert times.render(both.valid_to) == "2026-04-29T07:00:00.000Z"
    assert "wins over the expires_at" in both.attributes["valid_to_basis"]


def test_no_end_at_all_leaves_valid_to_open():
    entity, _ = _translate("entity_sensor_mast_riga.json")
    assert entity.valid_to is None
    assert "valid_to_basis" not in entity.attributes


# --------------------------------------------------------------- the event doc


def test_a_legion_event_class_is_not_a_cdm_event_type():
    """The name collides and the meaning does not: GUNSHOT says WHAT, not what kind of report."""
    event, = _translate("event_gunshot_detection.json")
    assert event.event_type is EventType.DETECTION
    assert event.payload["legion_event_class"] == "GUNSHOT"
    assert event.payload["legion_event_class_is_a_detection_class"] is True
    assert "names the detected CLASS" in event.payload["event_type_basis"]


def test_an_event_carries_no_geometry_and_the_actor_is_not_the_subject():
    """A USER is not a CDM object, so an actor id must never join related_entities."""
    event, = _translate("event_gunshot_detection.json")
    assert event.geometry is None
    assert event.related_entities == [
        ids.derive("LEGION", "f1c70000-0001-8000-8000-000000000001", kind="entity")]
    assert len(event.related_entities) == 1
    assert event.payload["legion_actor_type"] == "ENTITY"


def test_severity_stays_info_because_legion_states_none():
    """Grading a GUNSHOT would be this translator judging operational significance."""
    event, = _translate("event_gunshot_detection.json")
    assert event.severity is Severity.INFO
    assert "belongs to fusion" in event.payload["severity_basis"]


# ------------------------------------------------------------- the list -> Track


def test_a_locations_list_becomes_one_track_with_the_samples_in_payload_order():
    entity, track = _translate("locations_list_patrol_three.json")
    assert isinstance(track, Track) and isinstance(entity, Entity)
    assert len(track.samples) == 3
    assert [times.render(s.observed_at) for s in track.samples] == [
        "2026-04-29T06:11:00.000Z", "2026-04-29T06:13:00.000Z", "2026-04-29T06:15:00.000Z"]
    assert track.entity_id == entity.entity_id
    assert track.track_quality is None, "Legion states no track quality"


def test_the_completeness_of_a_partial_page_is_machine_visible():
    """Settlement 3. Three of nine, and a consumer can read that without parsing prose."""
    entity, track = _translate("locations_list_patrol_three.json")
    completeness = entity.attributes["legion_track_completeness"]
    assert completeness["total_count"] == 9
    assert completeness["carried_samples"] == 3
    assert completeness["complete"] is False
    assert completeness["track_id"] == str(track.track_id), (
        "the figures must name the Track they describe, or the association is lost when they "
        "are read off the Entity"
    )
    assert completeness["paging"]["has_more"] is True


def test_completeness_is_null_rather_than_false_when_it_cannot_be_established():
    """"We cannot tell" and "we can tell it is partial" are different answers."""
    document = _edited("locations_list_patrol_three.json", total_count=_ABSENT)
    document["paging"] = {"next": None, "previous": None}
    entity, _ = _adapter().to_cdm(document)
    assert entity.attributes["legion_track_completeness"]["complete"] is None

    whole = _edited("locations_list_patrol_three.json", total_count=3)
    whole["paging"] = {"has_more": False, "next": None, "previous": None}
    entity, _ = _adapter().to_cdm(whole)
    assert entity.attributes["legion_track_completeness"]["complete"] is True


def test_the_track_id_spans_the_page_so_two_pages_do_not_collapse():
    """An id keyed on the entity alone would make every page of a history one track."""
    first, second = (_edited("locations_list_patrol_three.json"),
                     _edited("locations_list_patrol_three.json"))
    for index, result in enumerate(second["results"]):
        result["recorded_at"] = f"2026-04-29T07:1{index}:00Z"
    _, track_one = _adapter().to_cdm(first)
    _, track_two = _adapter().to_cdm(second)
    assert track_one.track_id != track_two.track_id


def test_a_list_spanning_two_entities_is_refused():
    """A Track addresses one entity; a mixed page would merge two objects into one history."""
    document = _edited("locations_list_patrol_three.json")
    document["results"][1]["entity_id"] = "f1c70000-0001-8000-8000-0000000000ff"
    with pytest.raises(ValueError, match="spans 2 entity ids"):
        _adapter().to_cdm(document)


def test_an_empty_page_is_refused_rather_than_becoming_an_empty_track():
    document = _edited("locations_list_patrol_three.json", results=[])
    with pytest.raises(ValueError, match="empty `results`"):
        _adapter().to_cdm(document)


def test_the_list_entity_states_unknown_and_says_why():
    """A list asserts these fixes belong to this id and nothing else about the object."""
    entity, _ = _translate("locations_list_patrol_three.json")
    assert entity.entity_type is EntityType.UNKNOWN
    assert entity.affiliation is Affiliation.UNKNOWN
    assert "states nothing else about the object" in entity.attributes["entity_type_basis"]
    assert "second request and therefore fusion" in entity.attributes["entity_type_basis"]


def test_the_per_sample_metadata_survives_the_list_translation():
    """The defect the harness caught: pruning `results` dropped every sample's id and source."""
    entity, _ = _translate("locations_list_patrol_three.json")
    extras = entity.attributes["source_extras"]
    assert len(extras["results"]) == 3
    for index, result in enumerate(extras["results"], start=11):
        assert result["id"].endswith(f"0000000000{index}")
        assert result["source"] == "Synthetic Track Fusion"
        assert result["position"]["type"] == "Point"


# ------------------------------------------------------------ export review


def test_metadata_is_flagged_for_export_review_and_never_filtered():
    """Tagged in the coverage doc and tagged in the object. A translator may not release-decide."""
    entity, _ = _translate("entity_sensor_mast_riga.json")
    assert entity.attributes["export_review"]["keys"] == ["metadata"]
    assert "does not filter" in entity.attributes["export_review"]["basis"]
    # Flagged, and STILL present in full — the never-drop rule is not negotiable.
    assert entity.attributes["legion_metadata"]["model"] == "SYN-1448"
    assert entity.attributes["source_extras"]["metadata"]["model"] == "SYN-1448"


def test_an_object_with_no_reviewable_keys_is_not_flagged():
    """A flag on everything is a flag on nothing."""
    entity = _translate("entity_exercise_affiliation_and_nulls.json")[0]
    assert "export_review" not in entity.attributes


# ---------------------------------------------------------------- dispatch


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: p.name)
def test_every_fixture_dispatches_to_exactly_one_kind(path):
    assert _adapter()._kind(json.loads(path.read_text())) in (
        "entity", "location", "event", "locations_list")


def test_an_out_of_scope_document_is_refused_and_names_what_is_out():
    """Tasking, feeds, video and the rest are named in the error, not just in the document."""
    with pytest.raises(ValueError, match="matches none of the four shapes"):
        _adapter().to_cdm({"task_id": "f1c70000-0000-8000-8000-000000000009",
                           "command_name": "Restart", "status": "PENDING"})


def test_the_adapter_takes_no_transport_and_says_so():
    for payload in (42, ["a", "b"], None):
        with pytest.raises((TypeError, ValueError)):
            _adapter().to_cdm(payload)
    with pytest.raises(TypeError, match="transport stays with the caller"):
        _adapter().to_cdm(42)


def test_a_bare_json_array_is_refused():
    with pytest.raises(ValueError, match="not an object"):
        _adapter().to_cdm(b'[{"id": "x"}]')


def test_the_adapter_is_ingest_only_and_declares_it():
    """There is no from_cdm(): a task has no geometry and PlanObject.geometry is required."""
    assert LegionAdapter.direction == "ingest"
    with pytest.raises(NotImplementedError, match="ingest-only"):
        _adapter().from_cdm([])


# ------------------------------------------------------------------- harness


def test_the_harness_passes_every_fixture_against_the_published_schemas():
    from synapse_cdm import harness

    report = harness.run(_adapter(), FIXTURES, schema_dir=SCHEMAS)
    assert report["failed"] == 0, harness.render_report(report)
    assert report["passed"] >= 6
    for result in report["results"]:
        checks = result["checks"]
        for gate in ("translate", "schema", "provenance", "lossless", "golden"):
            assert checks[gate] == "PASS", result
        # Ingest-only, so the harness reports SKIP rather than PASS — an unrun check must never
        # read as a passed one.
        assert checks["roundtrip"] == "SKIP", result


def test_the_adapter_is_registered():
    from synapse_cdm.adapter import discover

    assert discover()["legion"] is LegionAdapter
    assert LegionAdapter.system == "LEGION"


def test_every_declared_transform_names_a_path_the_adapter_consumes_or_a_nested_one():
    """A TRANSFORMS entry for a path nothing reads is an exemption with no subject."""
    consumed = set(LegionAdapter.CONSUMED)
    for path in LegionAdapter.TRANSFORMS:
        leaf = path.split(".")[-1].replace("[]", "")
        assert leaf in consumed or path in consumed, (
            f"TRANSFORMS declares {path!r}, whose leaf {leaf!r} is not in CONSUMED"
        )


def test_every_consumed_path_is_present_in_some_fixture():
    """A CONSUMED entry nothing sends over-prunes the residual for a field that never arrives."""
    seen = set()
    for path in DOCUMENTS:
        seen |= {leaf.split(".")[-1] for leaf in
                 lossless.leaves(json.loads(path.read_text()))}
    unused = [c for c in LegionAdapter.CONSUMED if c.split(".")[-1] not in seen]
    assert not unused, f"CONSUMED paths no fixture exercises: {unused}"
