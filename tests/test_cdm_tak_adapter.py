"""One test per claim in the TAK adapter's docstring, plus the round trips the harness cannot do.

WHY THIS FILE CARRIES THE ROUND-TRIP CHECKS
-------------------------------------------
The harness's `roundtrip` column reports SKIP for an adapter that emits XML, and says so out
loud: it compares structures, `from_cdm()` here returns CoT bytes, and a check it cannot run
must report SKIP rather than PASS. The README's instruction for that case is that the adapter
ships its own round-trip test — so the two directions are exercised here, with the same
value-presence comparison (`lossless.unrepresented`) and the same TRANSFORMS exemptions the
harness would have used. Byte equality is neither achievable nor the point: attribute order is
arbitrary, an omitted optional field comes back explicit, and a re-rendered timestamp is a
different string for the same instant.
"""
import json
import pathlib
import uuid

import pytest

import synapse_cdm
from synapse_cdm import lossless, times
from synapse_cdm.adapters import tak
from synapse_cdm.adapters.tak import TakAdapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import Entity, Event, PlanObject

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "tak"
GOLDEN = FIXTURES / "golden"
EGRESS = FIXTURES / "egress"
SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "schemas"

XML_FIXTURES = sorted(FIXTURES.glob("*.xml"))
EGRESS_FIXTURES = sorted(EGRESS.glob("*.json"))


def _adapter() -> TakAdapter:
    return TakAdapter(clock=times.frozen_clock())


def _translate(name: str) -> tuple[Entity, Event]:
    entity, event = _adapter().to_cdm((FIXTURES / name).read_bytes())
    return entity, event


def _plan(name: str) -> PlanObject:
    return PlanObject.model_validate(json.loads((EGRESS / name).read_text()))


# --------------------------------------------------------------- the fixture set


def test_the_fixture_set_is_not_silently_empty():
    """A parametrised suite over a glob that matches nothing passes while testing nothing."""
    assert len(XML_FIXTURES) >= 3, f"expected >=3 ingest fixtures, found {len(XML_FIXTURES)}"
    assert len(EGRESS_FIXTURES) >= 2, f"expected >=2 egress fixtures, found {len(EGRESS_FIXTURES)}"


@pytest.mark.parametrize("path", XML_FIXTURES, ids=lambda p: p.name)
def test_every_xml_fixture_ships_its_parsed_form_and_they_agree(path):
    """The `.parsed.json` twin must be EXACTLY what the parser produces from the `.xml`.

    The twin exists because the harness cannot run its lossless check on a non-JSON fixture —
    it has no leaf structure to harvest — so an XML-only adapter would show a green run with
    the never-drop rule never actually checked. That only works if the two forms are the same
    payload, which is what this asserts: hand-maintained, they would drift, and the drift would
    be invisible because both fixtures would still pass on their own.
    """
    twin = path.parent / f"{path.stem}.parsed.json"
    assert twin.is_file(), f"{path.name} has no .parsed.json twin — the lossless check would SKIP"
    assert json.loads(twin.read_text()) == tak._parse_cot(path.read_text()), (
        f"{twin.name} is not what {path.name} parses to. Regenerate it from the XML rather "
        "than editing it by hand."
    )


@pytest.mark.parametrize("path", XML_FIXTURES, ids=lambda p: p.name)
def test_the_xml_and_parsed_paths_produce_identical_output(path):
    """The parse is the ONLY difference between the two forms, so the goldens must be equal.

    This is what keeps `_parse_cot()` and the translation from disagreeing. If the dict path
    ever produced something the XML path did not, one of the two golden files would be a
    recorded lie about the adapter — and each would still pass its own golden check.
    """
    from_xml = json.loads((GOLDEN / f"{path.stem}.cdm.json").read_text())
    from_dict = json.loads((GOLDEN / f"{path.stem}.parsed.cdm.json").read_text())
    assert from_xml == from_dict


# --------------------------------------------------------- ingest: the CoT table


def test_uid_becomes_the_source_id_on_both_objects():
    entity, event = _translate("narva_patrol.xml")
    assert [(s.system, s.external_id) for s in entity.source_ids] == [
        ("TAK", "ANDROID-352629101234567")]
    # On the event too: source_ids is required on every kind, because an object that cannot be
    # traced back to an external identifier cannot be recognised as a redelivery.
    assert [(s.system, s.external_id) for s in event.source_ids] == [
        ("TAK", "ANDROID-352629101234567")]


def test_entity_id_is_derived_from_the_uid_and_therefore_stable():
    entity, _ = _translate("narva_patrol.xml")
    assert entity.entity_id == uuid.uuid5(
        __import__("synapse_cdm.ids", fromlist=["NAMESPACE"]).NAMESPACE,
        "entity|TAK|ANDROID-352629101234567")
    assert entity.attributes["entity_id_basis"] == "event/@uid"


def test_two_reports_of_one_object_share_an_entity_id_and_do_not_share_an_event_id():
    """The reason the event id is keyed on (uid, time) and not on uid alone.

    A CoT uid identifies the OBJECT, and every position report repeats it. An event id derived
    from the uid alone would collapse a thousand reports into one event; keyed on the instant
    as well, a redelivery of the same report is idempotent and two genuine reports stay
    distinct. Both halves are asserted, because only checking the first would pass for an
    adapter that had made every report identical.
    """
    original = (FIXTURES / "narva_patrol.xml").read_text()
    later = original.replace('time="2026-04-29T06:11:20Z"', 'time="2026-04-29T06:12:20Z"')
    first_entity, first_event = _adapter().to_cdm(original)
    second_entity, second_event = _adapter().to_cdm(later)

    assert first_entity.entity_id == second_entity.entity_id, "one object, one entity id"
    assert first_event.event_id != second_event.event_id, "two reports, two event ids"

    redelivered_entity, redelivered_event = _adapter().to_cdm(original)
    assert redelivered_event.event_id == first_event.event_id, "a redelivery is the same event"
    assert redelivered_entity.entity_id == first_entity.entity_id


@pytest.mark.parametrize("fixture,letter,expected", [
    ("narva_patrol.xml", "f", Affiliation.FRIENDLY),
    ("air_track_due_north.xml", "h", Affiliation.HOSTILE),
    ("equator_zero_meridian.xml", "u", Affiliation.UNKNOWN),
    ("suspect_vessel_sentinels.xml", "s", Affiliation.UNKNOWN),
])
def test_the_affiliation_collapse_is_applied_and_recorded(fixture, letter, expected):
    """Gap 2: seven CoT letters collapse to four CDM members, recoverably.

    The `s` case is the one that matters. SUSPECT collapses to UNKNOWN and **not** to HOSTILE,
    because suspicion is not identification — an adapter that promoted it would be making an
    intelligence judgement inside a translator. The original letter and the full type string
    are both parked, which is what makes the collapse recoverable at all.
    """
    entity, _ = _translate(fixture)
    assert entity.affiliation == expected
    assert entity.attributes["cot_affiliation_letter"] == letter
    assert entity.attributes["cot_type"].split("-")[1] == letter


def test_suspect_is_not_translated_as_hostile():
    """Stated separately because it is the whole point of the collapse table."""
    entity, _ = _translate("suspect_vessel_sentinels.xml")
    assert entity.affiliation is Affiliation.UNKNOWN
    assert entity.affiliation is not Affiliation.HOSTILE


@pytest.mark.parametrize("fixture,expected", [
    ("narva_patrol.xml", EntityType.UNIT),              # a-f-G-U-C  ground
    ("air_track_due_north.xml", EntityType.PLATFORM),   # a-h-A-M-F-Q  air
    ("suspect_vessel_sentinels.xml", EntityType.PLATFORM),  # a-s-S-X-M  sea surface
    ("bridge_installation.xml", EntityType.FACILITY),   # a-f-G-I-...  ground INSTALLATION
])
def test_the_battle_dimension_becomes_the_entity_type(fixture, expected):
    entity, _ = _translate(fixture)
    assert entity.entity_type == expected


def test_a_ground_installation_is_a_facility_and_not_a_unit():
    """`G` alone would make a bridge a UNIT, which is a false statement rather than a coarse one.

    CoT states which in the function field, so the information to avoid the error is present and
    ignoring it would be a choice. Nothing further is inferred from the type hierarchy — the
    full string is parked for a consumer that wants to read it.
    """
    entity, _ = _translate("bridge_installation.xml")
    assert entity.entity_type is EntityType.FACILITY
    assert entity.attributes["cot_type"] == "a-f-G-I-B-A"


@pytest.mark.parametrize("how,expected", [
    ("m-g", PositionSource.GNSS),
    ("m-i", PositionSource.INERTIAL),
    ("m-f", PositionSource.ESTIMATED),
    ("h-e", PositionSource.MANUAL),
    ("h-t", PositionSource.MANUAL),
    ("h-g-i-g-o", PositionSource.MANUAL),      # unrecognised, but human -> MANUAL
    ("m-q-not-a-real-how", PositionSource.ESTIMATED),
    ("", PositionSource.ESTIMATED),
    (None, PositionSource.ESTIMATED),
])
def test_how_maps_to_position_source_and_understates_when_unsure(how, expected):
    """An unrecognised `how` resolves to ESTIMATED, never GNSS.

    `position_source` is the field a commander uses to tell a fix from a guess in a GNSS-denied
    environment. Understating a fix costs caution; overstating one gets acted on. The source's
    own word is kept at `attributes.cot_how` either way, so nothing is lost by being careful.
    """
    assert tak._position_source(how) is expected


def test_the_sentinel_becomes_null_and_never_a_measurement():
    """CoT spells unknown as 9999999, exactly as AIS spells unknown speed as 102.3.

    Forwarding it would put this vessel 9999 km up with 9999 km of circular error. The
    translation is declared in TRANSFORMS, so the exemption is a printed line in every harness
    report rather than a silent hole in the lossless check.
    """
    entity, _ = _translate("suspect_vessel_sentinels.xml")
    assert entity.position is not None, "the sentinel is on hae/ce/le, not on lat/lon"
    assert entity.position.alt_m is None
    assert entity.position.accuracy_m is None
    assert "vertical_error_m" not in entity.attributes
    assert entity.kinematics is None, "no <track> element at all means unknown, not zero"
    for path in ("event.point.@hae", "event.point.@ce", "event.point.@le"):
        assert path in TakAdapter.TRANSFORMS, f"{path} changes value and must be declared"


def test_a_real_le_is_parked_because_the_cdm_has_no_vertical_accuracy_field():
    """Gap 6, until Position.alt_accuracy_m lands in 1.1.0."""
    entity, _ = _translate("bridge_installation.xml")
    assert entity.attributes["vertical_error_m"] == 45.0
    assert entity.position.accuracy_m == 3.0, "accuracy_m is HORIZONTAL only"


def test_zero_zero_is_a_real_position_and_is_not_treated_as_absence():
    """The mirror-image defect. `if not lat` would discard this contact entirely.

    Coordinate 0/0 is a real point in the Gulf of Guinea, and some CoT implementations abuse it
    to mean "no position". Reading it as absence would be as wrong as null-to-zero: the test is
    for `is None`, never for falsiness. Altitude zero is asserted for the same reason — 0 m HAE
    is sea level, which is a measurement.
    """
    entity, _ = _translate("equator_zero_meridian.xml")
    assert entity.position is not None
    assert (entity.position.lat, entity.position.lon) == (0.0, 0.0)
    assert entity.position.alt_m == 0.0
    assert entity.position.accuracy_m == 25.0


def test_a_point_with_no_coordinates_yields_no_position():
    """What "we do not know where this is" looks like: the ABSENCE of a Position, not zeros."""
    entity, _ = _translate("degraded_no_position.xml")
    assert entity.position is None
    # The contact is still translated, still identified and still has an interval — a missing
    # position must not cost the whole report.
    assert entity.attributes["callsign"] == "DISMOUNT-19"
    assert entity.valid_to is not None


def test_course_360_becomes_zero_because_they_are_the_same_bearing():
    entity, _ = _translate("air_track_due_north.xml")
    assert entity.kinematics.course_deg == 0.0
    assert entity.kinematics.speed_mps == 247.2
    assert "event.detail.track.@course" in TakAdapter.TRANSFORMS


def test_stale_maps_to_valid_to_because_cot_staleness_is_an_interval_end():
    entity, _ = _translate("narva_patrol.xml")
    assert times.render(entity.valid_from) == "2026-04-29T06:11:20.000Z"
    assert times.render(entity.valid_to) == "2026-04-29T06:16:20.000Z"


def test_a_missing_start_falls_back_to_time_and_says_so():
    """A stated fallback, not a silent one — the same discipline as entity_id_basis."""
    entity, _ = _translate("suspect_vessel_sentinels.xml")
    assert times.render(entity.valid_from) == "2026-04-29T05:58:02.000Z"
    assert entity.attributes["valid_from_basis"] == "event/@time (event/@start absent)"


def test_the_callsign_and_remarks_are_parked_because_there_is_no_canonical_home():
    """Gap 1: no Entity.label until 1.1.0, so the string an operator reads lands here."""
    entity, _ = _translate("narva_patrol.xml")
    assert entity.attributes["callsign"] == "NARVA-2"
    assert "Foot patrol north bank" in entity.attributes["remarks"]


def test_the_group_is_a_colour_team_and_never_an_affiliation():
    """A meaning encoded in a colour is a meaning that can be dropped, so it is not one."""
    entity, _ = _translate("narva_patrol.xml")
    assert entity.attributes["group_name"] == "Cyan"
    assert entity.affiliation is Affiliation.FRIENDLY  # from @type, not from the colour


def test_fields_the_coverage_table_does_not_map_are_parked_with_their_structure():
    entity, _ = _translate("narva_patrol.xml")
    extras = entity.attributes["source_extras"]["event"]
    assert extras["@version"] == "2.0"
    assert extras["detail"]["contact"]["@endpoint"] == "192.168.20.14:4242:tcp"
    assert extras["detail"]["__group"]["@role"] == "Team Member"
    assert extras["detail"]["status"]["@battery"] == "72"
    assert extras["detail"]["precisionlocation"] == {"@geopointsrc": "GPS", "@altsrc": "GPS"}
    # And the consumed ones are NOT duplicated into the bag.
    assert "@uid" not in extras
    assert "point" not in extras


def test_the_event_is_a_track_update_at_info_and_says_why():
    """CoT carries no urgency field, so INFO is the format's silence rather than a misread.

    That is a different case from a source whose severity IS present and unreadable, which is
    refused — so the reason is recorded in the payload rather than left to be inferred.
    """
    _, event = _translate("narva_patrol.xml")
    assert event.event_type is EventType.TRACK_UPDATE
    assert event.severity is Severity.INFO
    assert "no urgency field" in event.payload["severity_basis"]


def test_the_event_points_at_the_entity_and_carries_both_timestamps():
    entity, event = _translate("narva_patrol.xml")
    assert event.related_entities == [entity.entity_id]
    assert times.render(event.observed_at) == "2026-04-29T06:11:20.000Z"
    # From the injected clock, never datetime.now() — which is what makes the golden stable.
    assert times.render(event.received_at) == "2026-04-29T06:15:00.000Z"
    assert event.geometry is None, "CoT carries one point and it belongs to the object"


def test_the_symbol_is_derived_and_marks_the_object_as_exercise_data():
    """Position 3 of the SIDC is the CONTEXT digit: 2 = simulation, because synthetic=True.

    An exercise object must not render identically to a live one on a commander's map, which
    is why sidc_from_affiliation() takes `synthetic` as a required keyword rather than
    defaulting it.
    """
    entity, _ = _translate("narva_patrol.xml")
    assert entity.symbol == "10230000000000000000"
    assert entity.symbol[2] == "2", "simulation context"
    assert entity.symbol[3] == "3", "2525D standard identity for FRIENDLY"

    live = TakAdapter(clock=times.frozen_clock(), synthetic=False)
    live_entity, _ = live.to_cdm((FIXTURES / "narva_patrol.xml").read_bytes())
    assert live_entity.symbol[2] == "0", "reality context"


# ------------------------------------------------------------- ingest: refusals


@pytest.mark.parametrize("attribute", ["uid", "type", "time"])
def test_a_missing_required_attribute_is_refused_not_defaulted(attribute):
    text = (FIXTURES / "narva_patrol.xml").read_text()
    # Rename the attribute so the document stays well-formed and only the field is absent.
    broken = text.replace(f'{attribute}="', f'not_{attribute}="', 1)
    with pytest.raises(ValueError, match=f"@{attribute}"):
        _adapter().to_cdm(broken)


def test_a_doctype_is_refused_before_the_parser_sees_it():
    """Internal entity expansion is an amplification attack against any parser that allows it.

    A CoT event has no legitimate use for a DTD, so refusing costs nothing real. The
    alternative is an adapter that can be made to exhaust memory by a message that looks
    well-formed — and this is the first adapter that will be handed bytes off a network.
    """
    payload = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE event [<!ENTITY a "aaaaaaaaaa">]>'
        '<event uid="X" type="a-f-G" time="2026-04-29T06:00:00Z"><point lat="1" lon="1"/></event>'
    )
    with pytest.raises(ValueError, match="DOCTYPE"):
        _adapter().to_cdm(payload)


def test_malformed_xml_is_refused_with_a_readable_message():
    with pytest.raises(ValueError, match="not well-formed"):
        _adapter().to_cdm("<event uid='X'><point")


def test_a_payload_with_no_event_element_is_refused():
    with pytest.raises(ValueError, match="no <event> element"):
        _adapter().to_cdm({"cot": {"@uid": "X"}})


def test_the_adapter_refuses_a_type_it_cannot_take():
    with pytest.raises(TypeError, match="TAK adapter takes"):
        _adapter().to_cdm(42)


# ----------------------------------------------------------------- the parser


def test_repeated_sibling_elements_become_a_list():
    """A parser where the last sibling wins is data loss no later check can see.

    It matters for exactly the construct this adapter emits: a drawing's vertices are many
    `<link>` elements, and collapsing them to one would turn a polygon into a point.
    """
    parsed = tak._parse_cot(
        '<event uid="X"><detail><link point="1,2,3"/><link point="4,5,6"/></detail></event>')
    links = parsed["event"]["detail"]["link"]
    assert isinstance(links, list) and len(links) == 2
    assert [l["@point"] for l in links] == ["1,2,3", "4,5,6"]


def test_an_xml_comment_is_not_mistaken_for_content():
    """Every fixture opens with a SYNTHETIC banner comment; it must not enter the output."""
    parsed = tak._parse_cot(
        '<event uid="X"><!-- a comment --><point lat="1" lon="2"/></event>')
    assert parsed == {"event": {"@uid": "X", "point": {"@lat": "1", "@lon": "2"}}}


# -------------------------------------------------------------------- egress


@pytest.mark.parametrize("path", EGRESS_FIXTURES, ids=lambda p: p.name)
def test_every_egress_fixture_matches_its_golden(path):
    emitted = _adapter().from_cdm([_plan(path.name)]).decode("utf-8") + "\n"
    golden = (EGRESS / "golden" / f"{path.stem}.cot.xml").read_text()
    assert emitted == golden, (
        f"{path.name} no longer emits its recorded expectation. Regenerate ONLY after reading "
        "the diff — a golden updated without being read is how a defect becomes the expectation."
    )


def test_a_plan_object_becomes_a_u_d_f_drawing_with_its_vertices():
    xml = _adapter().from_cdm([_plan("coa_sketch_polygon.json")]).decode("utf-8")
    assert 'type="u-d-f"' in xml
    # Authored, not sensed: claiming a machine origin for a commander's sketch would misstate
    # its provenance on the receiving client.
    assert 'how="h-e"' in xml
    assert 'callsign="EA VIPER"' in xml
    # CoT link points are lat,lon — the reverse of GeoJSON's [lon, lat]. Getting this wrong is
    # the single most common defect in an integration layer and its symptom is a shape in the
    # wrong hemisphere, so the order is asserted rather than assumed.
    assert 'point="59.36,28.15,9999999.0"' in xml
    assert xml.count("<link ") == 5, "the closed ring's five positions, including the repeat"
    assert 'closed="true"' in xml


def test_the_polygon_outer_ring_is_used_and_holes_are_not_drawn_as_outline():
    """An interior ring has no `u-d-f` representation, and emitting it as more links would
    draw the hole as part of the outline — a shape that means something else."""
    plan = _plan("coa_sketch_polygon.json")
    ring = plan.geometry.coordinates[0]
    assert tak._vertices(plan.geometry) == [list(p) for p in ring]


def test_style_keys_with_a_cot_element_get_one_and_the_rest_still_survive():
    """Dropping an unrecognised style key would make egress lossy in the way ingest may not be.

    `<detail>` is an open bag in CoT and a client ignores an unknown child rather than
    rejecting it, so parking the remainder there uses the documented extension point.
    """
    xml = _adapter().from_cdm([_plan("coa_sketch_polygon.json")]).decode("utf-8")
    assert '<strokeColor value="-65536" />' in xml
    assert '<strokeWeight value="3.0" />' in xml
    assert '<fillColor value="-1761607680" />' in xml
    assert '<synapse_style opacity="0.35" />' in xml, "an unmapped style key must not vanish"


def test_stale_is_omitted_rather_than_emptied_when_there_is_no_expiry():
    """`stale=""` is not "no expiry" to a client — it is an unparseable timestamp, and clients
    differ on whether that means now, never, or a dropped event. Computing one instead would
    invent an expiry the plan never stated."""
    xml = _adapter().from_cdm([_plan("patrol_route_linestring.json")]).decode("utf-8")
    assert "stale=" not in xml
    with_expiry = _adapter().from_cdm([_plan("coa_sketch_polygon.json")]).decode("utf-8")
    assert 'stale="2026-04-29T18:00:00.000Z"' in with_expiry


def test_an_unlabelled_plan_object_emits_no_contact_element():
    """`label: None` means unlabelled. An empty callsign renders as a blank callout, which
    reads as a broken client rather than as an unlabelled object."""
    xml = _adapter().from_cdm([_plan("annotation_point_unlabelled.json")]).decode("utf-8")
    assert "<contact" not in xml
    assert 'callsign=""' not in xml


def test_from_cdm_emits_one_document_and_refuses_to_invent_a_container():
    """A CoT event document holds exactly one event; several drawings are several messages."""
    two = [_plan("coa_sketch_polygon.json"), _plan("patrol_route_linestring.json")]
    with pytest.raises(ValueError, match="emits ONE CoT event document"):
        _adapter().from_cdm(two)

    _, event = _translate("narva_patrol.xml")
    with pytest.raises(ValueError, match="An Event alone is not"):
        _adapter().from_cdm([event])

    with pytest.raises(ValueError, match="emits ONE CoT event document"):
        _adapter().from_cdm([])


def test_a_geometry_with_no_vertices_would_be_refused():
    """The guard exists for a geometry the CDM has not got yet (MultiPolygon is a MINOR bump).

    An overlay that silently fails to appear on a TAK client is the worst outcome, because
    everyone assumes it arrived — so the failure belongs at the adapter, where somebody is
    looking. Exercised through the helper because no current Geometry can reach the branch.
    """
    class _Unsupported:
        type = "MultiPolygon"
        coordinates = [[[[0.0, 0.0]]]]

    assert tak._vertices(_Unsupported()) == []


def test_the_held_cot_type_wins_over_a_derived_one():
    """Reconstructing `a-f-G-U-C` from FRIENDLY + UNIT yields `a-f-G` and drops what the source
    actually stated. So the parked original is preferred and derivation is only the fallback."""
    entity, event = _translate("narva_patrol.xml")
    xml = _adapter().from_cdm([entity, event]).decode("utf-8")
    assert 'type="a-f-G-U-C"' in xml

    stripped = entity.model_copy(update={
        "attributes": {k: v for k, v in entity.attributes.items() if k != "cot_type"}})
    derived = _adapter().from_cdm([stripped, event]).decode("utf-8")
    assert 'type="a-f-G"' in derived, "the fallback states only what the CDM actually knows"


def test_an_unknown_position_omits_the_coordinates_rather_than_faking_them():
    """9999999 is not a latitude and 0 would be the null-to-zero defect running outbound."""
    entity, event = _translate("degraded_no_position.xml")
    xml = _adapter().from_cdm([entity, event]).decode("utf-8")
    assert "lat=" not in xml and "lon=" not in xml
    # hae/ce/le DO go out as CoT's sentinel — that is how CoT spells unknown for those three.
    assert 'hae="9999999.0"' in xml


def test_the_atoms_time_comes_from_the_events_observed_at():
    """The `event/@time -> Event.observed_at` row, read in the egress direction."""
    entity, event = _translate("narva_patrol.xml")
    with_event = _adapter().from_cdm([entity, event]).decode("utf-8")
    assert 'time="2026-04-29T06:11:20.000Z"' in with_event

    # With no Event to correlate, the entity's own interval start is the honest answer rather
    # than the emission instant, which would claim an observation time nothing observed.
    without_event = _adapter().from_cdm([entity]).decode("utf-8")
    assert 'time="2026-04-29T06:11:20.000Z"' in without_event


# --------------------------------------------------------------- round trips


@pytest.mark.parametrize("path", XML_FIXTURES, ids=lambda p: p.name)
def test_ingest_round_trip_loses_no_source_value(path):
    """CoT -> CDM -> CoT, measured the way the harness would if it could parse XML.

    Value presence, not byte equality: attribute order is arbitrary, an omitted optional field
    comes back explicit, and a re-rendered timestamp is a different string for the same
    instant. What must hold is that no VALUE from the original went missing on the way out,
    which is the property an operator on the receiving TAK client actually depends on.

    The TRANSFORMS exemptions are the adapter's own, so a value this test lets through is one
    the harness prints a reason for on every run.
    """
    original = tak._parse_cot(path.read_text())
    adapter = _adapter()
    emitted = tak._parse_cot(adapter.from_cdm(adapter.to_cdm(path.read_bytes())).decode("utf-8"))

    missing = lossless.unrepresented(original, [emitted], TakAdapter.TRANSFORMS)
    assert not missing, "\n".join(
        f"{p} = {v!r} was in the CoT source and is absent from what from_cdm() emitted"
        for p, v in sorted(missing.items()))


#: CDM bookkeeping with no CoT representation, excluded from the egress comparison BY NAME so
#: that adding a field to PlanObject cannot silently join the list. `source` in particular must
#: not be inferable from a drawing on someone else's map — `source.synthetic` is ours to know.
#: `source_ids` is excluded because the uid carries the TAK entry and only that entry; the uid
#: is asserted directly instead, in test_the_uid_is_the_objects_own_tak_identifier.
EGRESS_BOOKKEEPING = ("object_kind", "schema_version", "source", "integrity", "source_ids")


def _unpack_link_points(parsed: dict) -> dict:
    """Expand CoT's packed `link/@point="lat,lon,hae"` into its three numbers.

    Not the test doing the adapter's job — it is the test reading CoT's own format so it can
    compare VALUES at all. `lossless` harvests scalar leaves, and a packed delimited string is
    one leaf: without this, `28.1975` is reported missing while sitting in plain sight inside
    it, and the only alternative would be declaring the whole geometry exempt. An exemption
    over every coordinate would mean this test could no longer tell whether the vertices reach
    the wire, which is the one thing it exists to check.
    """
    detail = parsed.get("event", {}).get("detail")
    if not isinstance(detail, dict):
        return parsed
    links = detail.get("link")
    if links is None:
        return parsed
    for link in links if isinstance(links, list) else [links]:
        if isinstance(link, dict) and "@point" in link:
            link["_unpacked"] = [float(part) for part in link["@point"].split(",")]
    return parsed


@pytest.mark.parametrize("path", EGRESS_FIXTURES, ids=lambda p: p.name)
def test_egress_round_trip_loses_no_plan_object_value(path):
    """PlanObject -> CoT -> parsed, checked the same way as the ingest direction.

    A full inverse (CoT drawing -> PlanObject) is deliberately not implemented — ingesting a
    drawing would invert PlanObject's definition as "what we push OUT" — so the round trip is
    measured against the parsed XML rather than against a reconstructed object. That still
    answers the question that matters: did any value the plan stated fail to reach the wire?

    Run with NO transform exemptions at all, which is why it earned its keep: it found three
    real losses (`object_id`, the geometry kind, and every vertex beyond the first) that a
    reading of the emitted XML had not.
    """
    plan = _plan(path.name)
    emitted = _unpack_link_points(
        tak._parse_cot(_adapter().from_cdm([plan]).decode("utf-8")))

    carried = plan.model_dump(mode="json")
    for bookkeeping in EGRESS_BOOKKEEPING:
        carried.pop(bookkeeping, None)

    missing = lossless.unrepresented(carried, [emitted])
    assert not missing, "\n".join(
        f"{p} = {v!r} was on the PlanObject and is absent from the emitted CoT"
        for p, v in sorted(missing.items()))


def test_the_uid_is_the_objects_own_tak_identifier():
    """So a drawing pushed to TAK updates the same object next time instead of duplicating it.

    Asserted directly because the round-trip check excludes `source_ids` wholesale, and "the
    uid is right" is the half of that block which genuinely has to reach the wire.
    """
    for name in ("coa_sketch_polygon.json", "patrol_route_linestring.json"):
        plan = _plan(name)
        expected = next(s.external_id for s in plan.source_ids if s.system == "TAK")
        xml = _adapter().from_cdm([plan]).decode("utf-8")
        assert f'uid="{expected}"' in xml
        # And the CDM's own id still travels, or a consumer holding the drawing cannot get
        # back to the object it came from.
        assert f'object_id="{plan.object_id}"' in xml


@pytest.mark.parametrize("dropped,expected_loss", [
    ("synapse_style", "style.opacity"),
    ("synapse_plan", "object_id"),
    # A polygon's coordinates are ring-nested, hence the extra index. Note that deleting
    # every <link> loses only SOME vertices: the first also appears on the <point> anchor
    # and a closed ring repeats it, which is why the expected path names an interior one.
    ("link", "geometry.coordinates[0][2][0]"),
])
def test_the_egress_round_trip_would_notice_each_kind_of_loss(dropped, expected_loss):
    """The check above is only worth running if it can fail — so make it fail, three ways.

    A round-trip test that passes because it compares nothing is the failure mode this guards
    against, and it is not hypothetical: the vertex case is exactly the loss that WAS invisible
    until link points were unpacked. Each element the emitter writes is removed in turn and the
    same assertion must report the corresponding value as missing.
    """
    plan = _plan("coa_sketch_polygon.json")
    lossy = _unpack_link_points(tak._parse_cot(_adapter().from_cdm([plan]).decode("utf-8")))
    del lossy["event"]["detail"][dropped]

    carried = plan.model_dump(mode="json")
    for bookkeeping in EGRESS_BOOKKEEPING:
        carried.pop(bookkeeping, None)

    missing = lossless.unrepresented(carried, [lossy])
    assert expected_loss in missing, (
        f"removing <{dropped}> should have lost {expected_loss}; the check reported {missing}")


# ------------------------------------------------------------------- harness


def test_the_harness_passes_every_fixture_against_the_published_schemas():
    """The gate, run against `/schemas` rather than the models — that is what consumers read."""
    from synapse_cdm import harness

    report = harness.run(_adapter(), FIXTURES, schema_dir=SCHEMAS)
    assert report["failed"] == 0, harness.render_report(report)
    assert report["passed"] >= 6

    for result in report["results"]:
        checks = result["checks"]
        assert checks["translate"] == "PASS", result
        assert checks["schema"] == "PASS", result
        assert checks["provenance"] == "PASS", result
        assert checks["golden"] == "PASS", result
        # The lossless check runs on the parsed form and can only SKIP on the XML one, because
        # the harness has no leaf structure to harvest from bytes. Asserting the split rather
        # than accepting "not FAIL" is what stops an XML-only fixture set from quietly turning
        # the never-drop check off for this adapter.
        expected = "SKIP" if result["fixture"].endswith(".xml") else "PASS"
        assert checks["lossless"] == expected, result
        # roundtrip is SKIP for every fixture BY DESIGN: from_cdm returns XML, which the
        # harness cannot compare structurally. That is why this file carries the round trips.
        assert checks["roundtrip"] == "SKIP", result


def test_the_adapter_is_registered_and_declares_itself_bidirectional():
    from synapse_cdm.adapter import discover

    registry = discover()
    assert registry["tak"] is TakAdapter
    assert TakAdapter.direction == "bidirectional"
    assert TakAdapter.system == "TAK"


def test_every_declared_transform_names_a_path_the_adapter_consumes():
    """A TRANSFORMS entry for a path nothing reads is an exemption with no subject.

    It would silence the lossless check for a field this adapter never touches, which is the
    one way the escape hatch can be devalued without anybody noticing.
    """
    consumed = set(TakAdapter.CONSUMED)
    for path in TakAdapter.TRANSFORMS:
        assert path in consumed, (
            f"TRANSFORMS declares {path!r}, which is not in CONSUMED — either the adapter "
            "stopped reading it or the declaration is a leftover")
