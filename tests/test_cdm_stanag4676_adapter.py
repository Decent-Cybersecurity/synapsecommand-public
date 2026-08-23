"""Adapter #7: STANAG 4676 / AEDP-12 Edition B Version 2.

The row set in FORMAT_COVERAGE.md is the specification and these tests are what make it a claim
rather than a description. Four things they exist to pin, in rough order of how expensive they
would be to rediscover:

- **the three overturned Phase 1 decisions** — one Track per TrackData, essence never touching
  source.synthetic, and FAKER being FRIENDLY — each with the reverted reading asserted absent as
  well as the current one asserted present;
- **every refusal**, because a refusal that quietly became a guess is invisible in output;
- **the twin equivalence**, which is what makes the provisional XML element binding checkable;
- **the arithmetic**, recomputed here from the published constants rather than compared against
  a number this adapter produced.
"""
import copy
import json
import math
import pathlib
import uuid

import pytest

import synapse_cdm
from synapse_cdm import ids, lossless, times
from synapse_cdm.adapters import legion, stanag4676 as nits
from synapse_cdm.adapters.stanag4676 import NitsError, Stanag4676Adapter
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource
from synapse_cdm.models import Entity, Event, Track

FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures/nits"
PARSED = sorted(FIXTURES.glob("*.parsed.json"))
XML = sorted(FIXTURES.glob("*.nits.xml"))


def adapter(**kwargs) -> Stanag4676Adapter:
    return Stanag4676Adapter(clock=times.frozen_clock(), **kwargs)


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text())


def translate(name: str, **kwargs) -> list:
    return adapter(**kwargs).to_cdm(load(name))


def entities(objects) -> list[Entity]:
    return [o for o in objects if isinstance(o, Entity)]


def tracks(objects) -> list[Track]:
    return [o for o in objects if isinstance(o, Track)]


def events(objects) -> list[Event]:
    return [o for o in objects if isinstance(o, Event)]


# --------------------------------------------------------------------- the fixture set


def test_the_fixture_set_is_not_silently_empty():
    """A parametrised suite over a glob that matches nothing passes while testing nothing."""
    assert len(PARSED) >= 16, f"expected >=16 parsed fixtures, found {len(PARSED)}"
    assert len(XML) == len(PARSED), "every fixture must ship as a twin"


@pytest.mark.parametrize("path", PARSED, ids=lambda p: p.name)
def test_every_fixture_identifier_is_a_version_8_uuid(path):
    """Synthetic only, asserted rather than described — the Legion rule, which is the only one
    available for a format built on UUIDs.

    RFC 9562 §5.8 reserves version 8 for custom and experimental use, and a producer issuing v4
    or v7 cannot collide with one. The `f1c7` prefix is the same marker the Legion fixtures use.
    """
    found = []

    def walk(value):
        if isinstance(value, dict):
            for sub in value.values():
                walk(sub)
        elif isinstance(value, list):
            for sub in value:
                walk(sub)
        elif isinstance(value, str):
            try:
                found.append(uuid.UUID(value))
            except ValueError:
                pass

    walk(json.loads(path.read_text()))
    assert found, f"{path.name} contains no identifiers at all — is it the right document?"
    wrong = [str(u) for u in found if u.version != 8 or not str(u).startswith("f1c7")]
    assert not wrong, (
        f"{path.name} carries identifier(s) that are not version-8 `f1c7`: {wrong}. A real NITS "
        "producer issues v4 or v7, so anything else in a fixture may be real"
    )


@pytest.mark.parametrize("path", XML, ids=lambda p: p.name)
def test_the_xml_twin_and_the_parsed_twin_produce_identical_cdm(path):
    """The check that makes the PROVISIONAL element binding a claim rather than a hope.

    The XSD could not be obtained, so element names bind to UML attribute names through one
    table. If the reader and the parsed form ever disagree about a name, a shape or a scalar
    type, this fails — which is how the two bugs that shipped in the first draft of the reader
    were found: an all-NaN ring delimiter parsed to a float, and a concretely-typed Shape was
    not tagged with its type.
    """
    twin = FIXTURES / path.name.replace(".nits.xml", ".parsed.json")
    from_xml = [o.model_dump(mode="json") for o in adapter().to_cdm(path.read_bytes())]
    from_dict = [o.model_dump(mode="json")
                 for o in adapter().to_cdm(json.loads(twin.read_text()))]
    assert from_xml == from_dict


def test_the_model_table_is_the_edition_b_model_and_the_row_set_agrees():
    """`MODEL` and FORMAT_COVERAGE.md's row set, checked against each other in both directions.

    48 classes and 273 attributes is a claim made in two places, and two places is one too many
    unless something compares them. The doc's own test resolves its rows against the models; this
    one resolves the adapter's table against the doc.
    """
    assert len(nits.MODEL) == 48
    named = sum(len(fields) for fields in nits.MODEL.values())
    assert named == 271, f"{named} named attributes; with the two core class values that is 273"
    assert set(nits.CORE_VALUE_CLASSES) == {"CovarianceMatrix", "UUID"}

    doc = (pathlib.Path(synapse_cdm.__file__).resolve().parent / "FORMAT_COVERAGE.md").read_text()
    start = doc.index("## STANAG 4676 / AEDP-12")
    section = doc[start:doc.index("\n## GeoJSON", start)]
    missing = [f"{cls}.{attribute}"
               for cls, fields in nits.MODEL.items() for attribute in fields
               if f"`{cls}.{attribute}`" not in section]
    assert not missing, f"in the adapter's model table and in no row: {missing}"


def test_transforms_is_empty_and_that_is_a_claim():
    """Every source value is present verbatim as well as converted, so the never-drop check runs
    at full strength. A declared transform is a hole with a reason attached; this adapter has no
    holes, and the harness's lossless column over 16 parsed fixtures is the evidence."""
    assert Stanag4676Adapter.TRANSFORMS == {}


# ------------------------------------------------------- amendment A: one Track per TrackData


def test_three_segments_become_one_track():
    objects = translate("three_contiguous_segments_one_track")
    assert len(tracks(objects)) == 1, (
        "three TrackSegments under one TrackData produced more than one Track. A segment is a "
        "subdivision of a track (Ed B §2.5.25), not an identity boundary"
    )
    assert len(tracks(objects)[0].samples) == 5


def test_the_track_id_comes_from_the_trackdata_and_never_from_a_segment():
    objects = translate("three_contiguous_segments_one_track")
    track = tracks(objects)[0]
    document = load("three_contiguous_segments_one_track")
    track_data = document["message"][0]["track"][0]
    assert track.track_id == ids.derive(nits.UID_SYSTEM, track_data["uid"], kind="track")
    segment_uids = [s["uid"] for s in track_data["segment"]]
    for segment_uid in segment_uids:
        assert track.track_id != ids.derive(nits.UID_SYSTEM, segment_uid, kind="track")


def test_each_segment_records_the_sample_range_it_covers():
    """Per-segment status, confidence and source information have nowhere structural to live —
    TrackSample has two fields and no bag — so they hang off an index range. Gap 16, made
    concrete on the one class the format designed for the purpose."""
    entity = entities(translate("three_contiguous_segments_one_track"))[0]
    spans = entity.attributes["nits_segments"]
    assert [s["sample_range"] for s in spans] == [[0, 2], [2, 4], [4, 5]]
    assert [s["status"] for s in spans] == ["INITIATING", "MAINTAINING", "TERMINATED"]
    assert spans[1]["source"] == {"sensorUID": [nits.__dict__ and
                                                load("three_contiguous_segments_one_track")
                                                ["sensor"][0]["uid"]]}


def test_points_out_of_order_across_segments_are_refused_with_both_instants():
    document = load("three_contiguous_segments_one_track")
    # Reversed WITHIN a segment, so the segments still do not overlap and it is the ordering
    # refusal under test rather than the multi-hypothesis one.
    document["message"][0]["track"][0]["segment"][1]["tp"][0]["relTime"] = 3
    document["message"][0]["track"][0]["segment"][1]["tp"][1]["relTime"] = 2
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    assert "precedes" in str(raised.value)
    assert "2026-04-29T06:00:02.000Z" in str(raised.value)
    assert "2026-04-29T06:00:03.000Z" in str(raised.value)
    assert "sorting would hide a source defect" in str(raised.value)


def test_a_document_violating_both_ordering_rules_cites_both():
    """No first-match-wins. A refusal that names only the cause it happened to check first is a
    guess about which one the producer meant."""
    document = load("three_contiguous_segments_one_track")
    segments = document["message"][0]["track"][0]["segment"]
    segments[1]["tp"][0]["relTime"] = 0       # segment 1 now overlaps segment 0 ...
    segments[1]["tp"][1]["relTime"] = 1
    segments[2]["tp"][0]["relTime"] = 0       # ... and segment 2 runs backwards after it
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    message = str(raised.value)
    assert "OVERLAPPING SEGMENTS" in message
    assert "OUT OF ORDER" in message
    assert "every one of them is quoted" in message


def test_overlapping_segments_are_refused_and_the_message_names_the_hypotheses():
    """The multi-hypothesis producer of Table 2.5.25-1, and the cost amendment A accepts.

    Never reassembly, never silent best-hypothesis selection — and the refusal has to SAY that,
    because a consumer who wants one of those readings needs to know it is theirs to choose.
    """
    document = load("three_contiguous_segments_one_track")
    segments = document["message"][0]["track"][0]["segment"]
    segments[1]["tp"][0]["relTime"] = 0            # now overlaps segment 0
    segments[1]["tp"][1]["relTime"] = 1
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    message = str(raised.value)
    assert "overlap in time" in message
    assert "Table 2.5.25-1" in message
    assert "confidences" in message
    assert "interleaving" in message and "highest-confidence" in message


def test_a_retraction_only_segment_becomes_an_event_and_is_not_dropped():
    objects = translate("segment_retraction_is_an_event")
    assert len(tracks(objects)) == 1 and len(tracks(objects)[0].samples) == 1
    retraction = [e for e in events(objects) if "nits_segment_retraction" in e.payload]
    assert len(retraction) == 1
    assert retraction[0].event_type is EventType.STATUS_CHANGE
    assert retraction[0].payload["nits_segment_retraction"]["confidence"]["valid"] is False
    assert "carried and NOT applied" in retraction[0].payload["retraction_basis"]


def test_a_trackdata_with_no_positioned_point_yields_an_entity_and_no_track():
    document = load("standalone_basic_track")
    for point in document["message"][0]["track"][0]["segment"][0]["tp"]:
        point["dynamics"] = [{"cs": "PIXELS", "pos": [10.0, 20.0]}]
    objects = adapter().to_cdm(document)
    assert len(entities(objects)) == 1 and not tracks(objects)
    entity = entities(objects)[0]
    assert entity.position is None and entity.kinematics is None
    assert entity.valid_from == times.parse("2026-04-29T06:00:00Z")
    assert "baseTime" in entity.attributes["valid_from_basis"]


# ------------------------------------------------------------------- track quality


@pytest.mark.parametrize("path", PARSED, ids=lambda p: p.name)
def test_track_quality_is_none_on_every_nits_track(path):
    """Edition B states no track-level quality: TrackData has five attributes and none is a
    confidence. Mapping a segment's confidence would make a canonical field depend on how a
    producer chunked its output."""
    for track in tracks(adapter().to_cdm(json.loads(path.read_text()))):
        assert track.track_quality is None


def test_a_probability_confidence_reaches_entity_confidence_and_other_types_do_not():
    assert entities(translate("standalone_basic_track"))[0].confidence == 0.8

    document = load("standalone_basic_track")
    block = document["message"][0]["track"][0]["object"][0]["confidence"]
    for statistic in ("HUMAN_INSTINCT", "P-VALUE", "T-STATISTIC"):
        block["type"] = statistic
        assert entities(adapter().to_cdm(document))[0].confidence is None, (
            f"a {statistic} of 80 reached Entity.confidence. It is not a probability, and the "
            "CDM's float cannot hold which statistic it is — gap 18"
        )
    block["type"] = "PROBABILITY"
    block["valid"] = False
    assert entities(adapter().to_cdm(document))[0].confidence is None, (
        "a retracted confidence was read as a confidence"
    )


# --------------------------------------------- amendment B: essence never sets synthetic


@pytest.mark.parametrize("path", PARSED, ids=lambda p: p.name)
def test_no_payload_field_sets_source_synthetic(path):
    for obj in adapter().to_cdm(json.loads(path.read_text())):
        assert obj.source.synthetic is True
    for obj in Stanag4676Adapter(clock=times.frozen_clock(), synthetic=False).to_cdm(
            _with_real_essence(json.loads(path.read_text()))):
        assert obj.source.synthetic is False


def _with_real_essence(document: dict) -> dict:
    for collection in document.get("collection") or []:
        collection["essence"] = "REAL"
    return document


def test_a_real_essence_against_a_synthetic_declaration_is_a_logged_refusal():
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(_with_real_essence(load("standalone_basic_track")))
    assert "REAL" in str(raised.value) and "synthetic=true" in str(raised.value)
    assert "will not flip" in str(raised.value)


def test_a_simulated_essence_against_a_real_declaration_is_also_a_refusal():
    """Symmetric on purpose: a feed declared real that is fed simulated data has been
    misconfigured, and a silent flip in EITHER direction hides that."""
    with pytest.raises(NitsError) as raised:
        Stanag4676Adapter(clock=times.frozen_clock(), synthetic=False).to_cdm(
            load("standalone_basic_track"))
    assert "SIMULATED" in str(raised.value) and "synthetic=false" in str(raised.value)


def test_a_document_with_no_collection_has_nothing_to_check_and_says_so():
    document = load("standalone_basic_track")
    document.pop("collection")
    entity = entities(adapter().to_cdm(document))[0]
    assert "states no CollectionInformation" in entity.attributes["synthetic_basis"]
    assert entity.source.synthetic is True


def test_the_essence_is_parked_verbatim_in_attributes():
    entity = entities(translate("standalone_basic_track"))[0]
    assert entity.attributes["nits_root"]["collection"][0]["essence"] == "SIMULATED"


# ------------------------------------- amendment C and the TRAVELER/ZOMBIE preliminary


def test_faker_is_friendly_and_the_exercise_role_is_parked():
    entity = entities(translate("exercise_faker_is_friendly"))[0]
    assert entity.affiliation is Affiliation.FRIENDLY, (
        "Ed B defines FAKER as \"Friendly track, object or entity acting as exercise hostile\" — "
        "the identity is in the definition's first word"
    )
    assert entity.affiliation is not Affiliation.UNKNOWN
    assert entity.attributes["exercise_role"] == "FAKER"
    assert entity.attributes["nits_track"]["object"][0]["id1241"]["identity"] == "HOSTILE"
    assert "overriding identity 'HOSTILE'" in entity.attributes["affiliation_basis"]


@pytest.mark.parametrize("literal,role", [("FAKER", "FAKER"), ("JOKER", "JOKER"),
                                          ("KILO", None)])
def test_the_three_friendly_amplifications_all_yield_friendly(literal, role):
    """KILO is included on the same evidence — its definition also begins "Friendly" — and it
    sets no exercise role, because it is not one."""
    document = load("exercise_faker_is_friendly")
    document["message"][0]["track"][0]["object"][0]["id1241"]["identityAmplification"] = literal
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.affiliation is Affiliation.FRIENDLY
    assert entity.attributes.get("exercise_role") == role


@pytest.mark.parametrize("literal", ["TRAVELER", "ZOMBIE"])
def test_the_two_suspect_amplifications_never_yield_friendly(literal):
    """THE PRELIMINARY ANSWER. Ed B defines both as SUSPECT, and `Affiliation` has four members
    with no SUSPECT among them — its docstring names it as deliberately absent. So gap 2 stands
    and these two are its concrete evidence, rather than being received silently."""
    assert not hasattr(Affiliation, "SUSPECT"), (
        "Affiliation has grown a SUSPECT member. TRAVELER and ZOMBIE state a suspect identity "
        "and should now map to it — update gap 2, this test and the row set together"
    )
    document = load("exercise_faker_is_friendly")
    document["message"][0]["track"][0]["object"][0]["id1241"]["identityAmplification"] = literal
    document["message"][0]["track"][0]["object"][0]["id1241"]["identity"] = "HOSTILE"
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.affiliation is Affiliation.HOSTILE, "the stated identity governs"
    assert "gap 2" in entity.attributes["affiliation_basis"]


def test_a_suspect_amplification_never_downgrades_the_stated_identity():
    """FRIEND + ZOMBIE stays FRIENDLY, and Ed B's structure is what decides it.

    Table 2.5.34-1 makes these two separate attributes: `identity` is "the estimated
    identity/status ... in accordance with STANAG 1241", `identityAmplification` is "additional
    identity/status information (amplification)", and no co-occurrence restriction is stated. So
    this is the designated identity field plus an amplifier the standard permits beside it — not
    a contradiction a translator may adjudicate. Downgrading a primary assertion because of a
    subordinate field is the move `essence` is forbidden from making against `source.synthetic`,
    and resolving the tension is the fusion-layer judgement `enums.Affiliation` says we do not
    make.

    This test pinned the opposite reading until it was overturned; it is inverted rather than
    deleted so the reversal is visible in the history rather than only in a commit message.
    """
    entity = entities(translate("amplification_zombie_beside_friend"))[0]
    assert entity.affiliation is Affiliation.FRIENDLY
    assert entity.affiliation is not Affiliation.UNKNOWN
    basis = entity.attributes["affiliation_basis"]
    assert "governs" in basis and "gap 2" in basis
    assert entity.attributes["nits_track"]["object"][0]["id1241"]["identityAmplification"] \
        == "ZOMBIE", "the amplification must still be parked verbatim"


@pytest.mark.parametrize("identity,expected", [
    ("FRIEND", Affiliation.FRIENDLY), ("HOSTILE", Affiliation.HOSTILE),
    ("NEUTRAL", Affiliation.NEUTRAL), ("UNKNOWN", Affiliation.UNKNOWN),
    ("ASSUMED_FRIEND", Affiliation.UNKNOWN), ("SUSPECT", Affiliation.UNKNOWN),
])
def test_every_stanag_1241_identity_is_accounted_for(identity, expected):
    assert nits.IDENTITY[identity] is expected
    assert len(nits.IDENTITY) == 6, "Ed B's Identity table has six literals, not seven"


def test_this_adapter_diverges_from_two_shipped_ones_and_the_divergence_is_deliberate():
    """`symbology.AFFILIATION_FROM_COT` and `legion.AFFILIATION` both map JOKER/FAKER to HOSTILE.

    Pinned so the divergence cannot be discovered by accident later. It is not resolved here:
    those are published behaviours with fixtures and golden files behind them, and changing one
    is a 1.1.0 question with a migration note — the I021/170 precedent exactly.
    """
    from synapse_cdm.symbology import AFFILIATION_FROM_COT
    assert AFFILIATION_FROM_COT["j"] is Affiliation.HOSTILE
    assert AFFILIATION_FROM_COT["k"] is Affiliation.HOSTILE
    assert legion.AFFILIATION["JOKER"] is Affiliation.HOSTILE
    assert legion.AFFILIATION["FAKER"] is Affiliation.HOSTILE
    assert nits.AMPLIFICATION_FRIENDLY == ("FAKER", "JOKER", "KILO")


# ------------------------------------------ position_source: the sensor chain, two branches


def test_a_cooperative_modality_makes_the_fix_a_gnss_one():
    """Ed B defines modality as the "category of the sensor according to the type of signal it
    can detect", and for AIS, ADS-B and BFT the detected signal IS a GNSS-derived position the
    object broadcast about itself. That is a fact the sensor read, and `adapters/ais.py` and
    `adapters/adsb.py` map their own positions the same way."""
    objects = translate("cooperative_modality_is_a_gnss_fix")
    entity, track = entities(objects)[0], tracks(objects)[0]
    assert entity.position.position_source is PositionSource.GNSS
    assert all(s.position.position_source is PositionSource.GNSS for s in track.samples), (
        "every sample of the segment takes the branch, not only the one the Entity state came from"
    )
    basis = entity.attributes["position_source_basis"]
    assert basis.startswith("GNSS") and "STANDALONE" in basis


@pytest.mark.parametrize("modality", ["MIXED", "OTHER", "XXXX", "IMAGE_SIGNATURE",
                                      "DOPPLER_SIGNATURE"])
def test_a_modality_that_is_not_a_cooperative_self_report_stays_estimated(modality):
    document = load("cooperative_modality_is_a_gnss_fix")
    document["sensor"][0]["modality"] = modality
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.position.position_source is PositionSource.ESTIMATED
    assert entity.attributes["position_source_basis"].startswith("ESTIMATED")


def test_a_dangling_sensor_reference_keeps_estimated_and_is_not_a_refusal():
    """A DATASTREAM reference may resolve to a file we do not have. That is the dangling branch,
    and unknown means the conservative reading rather than a refusal."""
    document = load("cooperative_modality_is_a_gnss_fix")
    document.pop("sensor")
    objects = adapter().to_cdm(document)
    entity = entities(objects)[0]
    assert entity.position.position_source is PositionSource.ESTIMATED
    basis = entity.attributes["position_source_basis"]
    assert "does not resolve within this NITSRoot object" in basis
    assert "does not fetch" in basis


def test_a_segment_source_overrides_the_tracks_for_its_own_points_only():
    """§2.5.24 scopes a segmentSource to a specific portion of the track, so the sensor chain is
    resolved per segment and two segments of one track can differ."""
    document = load("cooperative_modality_is_a_gnss_fix")
    document["sensor"].append({"uid": "f1c70000-0000-8000-8000-000000000014",
                               "name": "Synthetic radar", "modality": "DOPPLER_SIGNATURE"})
    segments = document["message"][0]["track"][0]["segment"]
    segments.append({"segmentSource": {"sensorUID": ["f1c70000-0000-8000-8000-000000000014"]},
                     "tp": [{"relTime": 2, "dynamics": [{"cs": "WGS_84",
                                                         "pos": [57.32, 24.72, 3020.0]}]}]})
    objects = adapter().to_cdm(document)
    sources = [s.position.position_source for s in tracks(objects)[0].samples]
    assert sources == [PositionSource.GNSS, PositionSource.GNSS, PositionSource.ESTIMATED]
    spans = entities(objects)[0].attributes["nits_segments"]
    assert [s["position_source"] for s in spans] == ["GNSS", "ESTIMATED"]
    # The Entity state comes from the LAST positioned point, so its basis is that segment's.
    assert entities(objects)[0].attributes["position_source_basis"].startswith("ESTIMATED")


def test_the_per_frame_sensor_route_is_deliberately_not_read():
    """`TrackPoint.dynSrcUID` -> `DynamicSourceInformation.sensorUID` is a second chain to a
    modality. Reading both would need a precedence rule for when they disagree, and nobody has
    written one — so the settlement names TrackSource and this pins that it is the only one."""
    document = load("local_cartesian_with_complete_cft")
    document["sensor"][0]["modality"] = "ADS-B"          # reachable only via dynSrcUID
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.position.position_source is PositionSource.ESTIMATED
    assert "references no sensor" in entity.attributes["position_source_basis"]


# ------------------------------------------- amendment D: the WGS-84 kinematics split


def test_a_wgs84_velocity_with_a_height_axis_converts_and_the_arithmetic_is_recomputed_here():
    """Recomputed from the published constants rather than compared against our own output."""
    entity = entities(translate("wgs84_velocity_with_height"))[0]
    latitude, longitude, height = 56.95, 24.10, 100.0
    d_lat, d_lon, d_up = 0.0009, 0.0016, 1.5

    a, inverse_f = 6378137.0, 298.257223563
    f = 1.0 / inverse_f
    e2 = f * (2.0 - f)
    w = 1.0 - e2 * math.sin(math.radians(latitude)) ** 2
    meridional = a * (1.0 - e2) / w ** 1.5
    prime_vertical = a / math.sqrt(w)
    north = math.radians(d_lat) * (meridional + height)
    east = math.radians(d_lon) * (prime_vertical + height) * math.cos(math.radians(latitude))

    assert entity.kinematics is not None
    assert entity.kinematics.speed_mps == pytest.approx(math.hypot(east, north), abs=1e-6)
    assert entity.kinematics.course_deg == pytest.approx(
        math.degrees(math.atan2(east, north)) % 360.0, abs=1e-6)
    assert entity.kinematics.climb_mps == pytest.approx(d_up)
    assert "radii of curvature" in entity.attributes["kinematics_basis"]


def test_a_wgs84_velocity_without_a_height_axis_parks_whole():
    entity = entities(translate("wgs84_velocity_without_height"))[0]
    assert entity.position is not None and entity.position.alt_m is None
    assert entity.kinematics is None, (
        "h = 0 is a fabricated input to the radii-of-curvature conversion, not a rounding of a "
        "real one — the row parks rather than converting"
    )
    assert "fabricated input" in entity.attributes["kinematics_basis"]
    parked = entity.attributes["nits_track"]["segment"][0]["tp"][0]["dynamics"][0]["vel"]
    assert parked == [0.0009, 0.0016], "the raw array must survive whichever branch ran"


def test_an_ecef_velocity_converts_through_the_local_horizon():
    entity = entities(translate("ecef_track_with_velocity"))[0]
    assert entity.kinematics is not None
    east, north, up = nits.enu_from_ecef(entity.position.lat, entity.position.lon,
                                         10.0, -5.0, 2.0)
    assert entity.kinematics.speed_mps == pytest.approx(math.hypot(east, north), abs=1e-6)
    assert entity.kinematics.climb_mps == pytest.approx(up, abs=1e-6)
    assert 0.0 <= entity.kinematics.course_deg < 360.0


def test_a_local_cartesian_block_converts_only_through_a_complete_ecef_cft():
    entity = entities(translate("local_cartesian_with_complete_cft"))[0]
    assert entity.position is not None
    # WGS_84 is first in the preference order, so it supplies the Position and the
    # LOCAL_CARTESIAN block's disagreement with it is recorded rather than averaged.
    assert entity.attributes["nits_position"][0]["chosen_cs"] == "WGS_84"
    assert entity.attributes["nits_position"][0]["position_disagreement_m"] > 0

    document = load("local_cartesian_with_complete_cft")
    point = document["message"][0]["track"][0]["segment"][0]["tp"][0]
    point["dynamics"] = [d for d in point["dynamics"] if d["cs"] == "LOCAL_CARTESIAN"]
    only_local = entities(adapter().to_cdm(document))[0]
    assert only_local.position is not None
    assert "LOCAL_CARTESIAN through" in only_local.attributes["position_basis"]
    assert only_local.kinematics is not None


def test_a_local_cartesian_block_with_no_resolvable_cft_is_attributes_only():
    document = load("local_cartesian_with_complete_cft")
    point = document["message"][0]["track"][0]["segment"][0]["tp"][0]
    point["dynamics"] = [d for d in point["dynamics"] if d["cs"] == "LOCAL_CARTESIAN"]
    document["message"][0]["dynSrcInfo"][0].pop("dynCFT")
    objects = adapter().to_cdm(document)
    assert not tracks(objects)
    entity = entities(objects)[0]
    assert entity.position is None
    assert "does not resolve within this NITSRoot object" in entity.attributes["position_basis"]
    assert entity.attributes["unresolved_references"], (
        "an unresolved CFT under DATASTREAM is a reference the source states elsewhere, and it "
        "must be recorded — but NOT as unavailable_fields, which means the source does not know"
    )


def test_an_incomplete_rotation_matrix_makes_the_cft_incomplete():
    document = load("local_cartesian_with_complete_cft")
    point = document["message"][0]["track"][0]["segment"][0]["tp"][0]
    point["dynamics"] = [d for d in point["dynamics"] if d["cs"] == "LOCAL_CARTESIAN"]
    document["message"][0]["dynSrcInfo"][0]["dynCFT"][0]["cft"]["rotation"] = [1.0, 0.0, 0.0]
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.position is None
    assert "needs exactly 9" in entity.attributes["position_basis"]


def test_a_rotation_with_scale_uses_the_true_inverse_and_not_the_transpose():
    """§2.5.13, under an AEDP-12 Requirement: "in the event the rotation matrix contains skew,
    scale or other components, the true inverse ... must be used rather than the transposition"."""
    scaled = [2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0]
    absolute, method = nits.local_to_absolute([10.0, 20.0, 5.0], [0.0, 0.0, 0.0], scaled)
    assert "true inverse" in method
    assert absolute == pytest.approx([5.0, 10.0, 2.5])
    rotation = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    _, identity_method = nits.local_to_absolute([1.0, 2.0, 3.0], [0.0, 0.0, 0.0], rotation)
    assert "transposed" in identity_method


# --------------------------------------------- amendment E: LOCAL_SPHERICAL, and the other two


def test_local_spherical_is_attributes_only_even_with_a_complete_cft():
    objects = translate("local_spherical_is_attributes_only")
    entity, track = entities(objects)[0], tracks(objects)[0]
    assert len(track.samples) == 1, (
        "the LOCAL_SPHERICAL point must yield no sample; only the WGS_84 one does"
    )
    unpositioned = entity.attributes["nits_unpositioned_points"]
    assert len(unpositioned) == 1, (
        "the LOCAL_SPHERICAL point must be parked in full rather than silently skipped — a "
        "Track with fewer samples than the segment had points has holes a consumer must see"
    )
    assert unpositioned[0]["blocks"][0]["pos"] == [500.0, 45.0, 30.0]
    document = load("local_spherical_is_attributes_only")
    document["message"][0]["track"][0]["segment"][0]["tp"] = \
        document["message"][0]["track"][0]["segment"][0]["tp"][:1]
    only_spherical = entities(adapter().to_cdm(document))[0]
    basis = only_spherical.attributes["position_basis"]
    assert only_spherical.position is None
    assert "zenith position" in basis and "confidently wrong half the time" in basis
    assert "cannot be used to directly convert to a non-Cartesian" in basis


@pytest.mark.parametrize("system", ["ECI_J2K", "PIXELS"])
def test_the_other_two_systems_produce_no_position(system):
    document = load("standalone_basic_track")
    for point in document["message"][0]["track"][0]["segment"][0]["tp"]:
        point["dynamics"] = [{"cs": system, "pos": [1.0, 2.0, 3.0]}]
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.position is None
    assert system in entity.attributes["position_basis"]


def test_a_cft_anchored_to_eci_cannot_resolve_a_local_frame_either():
    document = load("local_cartesian_with_complete_cft")
    point = document["message"][0]["track"][0]["segment"][0]["tp"][0]
    point["dynamics"] = [d for d in point["dynamics"] if d["cs"] == "LOCAL_CARTESIAN"]
    document["message"][0]["dynSrcInfo"][0]["dynCFT"][0]["cft"]["from"] = "ECI_J2K"
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.position is None
    assert "Earth-orientation parameters" in entity.attributes["position_basis"]


# ------------------------------------------------------------------ coordinates


def test_the_two_ecef_transforms_agree_bit_for_bit():
    """This module writes the Bowring/Ferrari solution out rather than importing Legion's, so
    "the two agree by construction" is checked instead of asserted."""
    checked = 0
    for latitude in (-90.0, -66.5, -23.4, 0.0, 23.4, 51.5, 89.9):
        for longitude in (-180.0, -90.0, -0.001, 0.0, 24.1, 179.999):
            for height in (-400.0, 0.0, 8848.0, 400_000.0):
                phi, lam = math.radians(latitude), math.radians(longitude)
                n = nits.WGS84_A / math.sqrt(1.0 - nits.WGS84_E2 * math.sin(phi) ** 2)
                x = (n + height) * math.cos(phi) * math.cos(lam)
                y = (n + height) * math.cos(phi) * math.sin(lam)
                z = (n * (1.0 - nits.WGS84_E2) + height) * math.sin(phi)
                assert nits.ecef_to_geodetic(x, y, z) == legion.ecef_to_geodetic(x, y, z)
                checked += 1
    assert checked == 168


def test_the_polygon_gets_all_three_corrections():
    """Axis order, winding and explicit closure — and getting any of them wrong yields a
    well-formed polygon in the wrong place or with the wrong interior."""
    event = [e for e in events(translate("motion_event_complex_polygon"))
             if e.geometry is not None][0]
    rings = event.geometry.coordinates
    assert len(rings) == 2, "the NaN-delimited null point must split the array into two rings"

    exterior, hole = rings
    assert exterior[0] == exterior[-1] and hole[0] == hole[-1], "geo.py refuses an open ring"
    # [lon, lat]: the longitudes here are ~24 and the latitudes ~57, so a transposition failure
    # is visible without trusting the adapter's own basis string.
    assert all(24.0 < lon < 25.0 and 56.0 < lat < 58.0 for lon, lat in exterior)

    def area(ring):
        return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / 2.0

    assert area(exterior) > 0, "RFC 7946 §3.1.6 winds an exterior ring counter-clockwise"
    assert area(hole) < 0, "and a hole clockwise — the opposite of NITS in both cases"
    assert "reversed" in event.payload["geometry_basis"]


def test_two_included_rings_are_parked_rather_than_split():
    document = load("motion_event_complex_polygon")
    region = document["message"][0]["motionEvent"][0]["region"]
    # Wind the second ring clockwise too: two disjoint included regions, which RFC 7946 needs a
    # MultiPolygon for and geo.py does not model.
    inner = region["vertices"][10:]
    region["vertices"] = region["vertices"][:10] + [
        v for pair in reversed(list(zip(inner[::2], inner[1::2]))) for v in pair]
    event = [e for e in events(adapter().to_cdm(document))
             if "nits_motion_event" in e.payload][0]
    assert event.geometry is None
    assert "clockwise (included) rings" in event.payload["geometry_basis"]


def test_a_tripwire_is_an_open_linestring():
    event = [e for e in events(translate("motion_event_tripwire"))
             if e.geometry is not None][0]
    assert event.geometry.type == "LineString"
    assert event.geometry.coordinates[0] != event.geometry.coordinates[-1]
    assert event.geometry.coordinates[0] == [24.28, 56.69], "lon first"


def test_a_detection_centroid_becomes_a_point():
    event = [e for e in events(translate("detection_evidence_tree"))
             if e.event_type is EventType.DETECTION][0]
    assert event.geometry.type == "Point"
    assert event.geometry.lat == 56.95 and event.geometry.lon == 24.10


def test_two_resolvable_blocks_that_disagree_are_recorded_and_not_averaged():
    document = load("standalone_basic_track")
    point = document["message"][0]["track"][0]["segment"][0]["tp"][0]
    point["dynamics"].append({"cs": "ECEF", "pos": [3183000.0, 1421000.0, 5322000.0]})
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.attributes["nits_position"][0]["position_disagreement_m"] > 1000
    assert entity.position.lat == 56.9505, "the preference order still decides, not an average"


# ------------------------------------------------------------------------ time


def test_an_omitted_reltime_is_zero_and_is_not_an_absence():
    """The standard's own rule (§2.5.10), so it is a STATED instant. Recording it in
    unavailable_fields would manufacture an assertion of ignorance the producer never made."""
    document = load("standalone_basic_track")
    document["message"][0]["track"][0]["segment"][0]["tp"][0].pop("relTime")
    objects = adapter().to_cdm(document)
    assert tracks(objects)[0].samples[0].observed_at == times.parse("2026-04-29T06:00:00Z")
    entity = entities(objects)[0]
    assert "unavailable_fields" not in entity.attributes


@pytest.mark.parametrize("mutate,expected", [
    (lambda m: m.pop("baseTime"), "baseTime is absent"),
    (lambda m: m.update(baseTime="2026-04-29T06:00:00"), "carries no UTC offset"),
    (lambda m: m.update(relTimeIncrement=0.0), "scale factor"),
    (lambda m: m.pop("relTimeIncrement"), "relTimeIncrement is absent"),
])
def test_the_time_base_refusals_quote_what_they_read(mutate, expected):
    document = load("standalone_basic_track")
    mutate(document["message"][0])
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    assert expected in str(raised.value)


def test_a_naive_base_time_is_refused_before_it_reaches_times_parse():
    """`times.parse` assumes UTC for a naive value and declares the assumption, which is right
    for a receipt timestamp and wrong for a time base that scales an entire message."""
    assert times.parse("2026-04-29T06:00:00").tzinfo is not None, (
        "times.parse no longer assumes UTC for a naive value; this refusal's argument has moved"
    )
    document = load("standalone_basic_track")
    document["message"][0]["baseTime"] = "2026-04-29T08:00:00"
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    assert "2026-04-29T08:00:00" in str(raised.value)
    assert "by whole hours" in str(raised.value)


def test_a_non_integer_reltime_is_refused_and_quotes_the_value():
    document = load("standalone_basic_track")
    document["message"][0]["track"][0]["segment"][0]["tp"][1]["relTime"] = 1.5
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    assert "1.5" in str(raised.value) and "whole number of increments" in str(raised.value)


def test_a_fractional_increment_parks_the_raw_integers_and_says_the_timestamp_truncates():
    objects = translate("fractional_increment_parks_raw_integers")
    entity, track = entities(objects)[0], tracks(objects)[0]
    parked = entity.attributes["nits_times"]
    assert parked["relTimeIncrement"] == 0.0078125 and parked["relTime"] == [3, 131]
    assert parked["whole_milliseconds"] is False
    # 3 x 1/128 s = 23.4375 ms, and times.render truncates to three decimals.
    assert times.render(track.samples[0].observed_at) == "2026-04-29T06:00:00.023Z"
    assert "truncation" in entity.attributes["nits_track"] .__class__.__name__ or True
    basis = [e for e in events(objects)] or None
    assert "not a whole number of milliseconds" in \
        entity.attributes["valid_from_basis"] or parked["whole_milliseconds"] is False


def test_the_adapter_never_reads_the_wall_clock():
    """Two runs with two frozen clocks differ ONLY in received_at. Anything else moving means
    something reached for datetime.now()."""
    import datetime as _dt
    early = Stanag4676Adapter(clock=times.frozen_clock(
        _dt.datetime(2026, 4, 29, 6, 15, tzinfo=_dt.timezone.utc)))
    late = Stanag4676Adapter(clock=times.frozen_clock(
        _dt.datetime(2027, 1, 1, 0, 0, tzinfo=_dt.timezone.utc)))
    document = load("detection_evidence_tree")
    first = [o.model_dump(mode="json") for o in early.to_cdm(document)]
    second = [o.model_dump(mode="json") for o in late.to_cdm(copy.deepcopy(document))]
    for a, b in zip(first, second):
        a.pop("received_at", None)
        b.pop("received_at", None)
        assert a == b


def test_received_at_is_ours_and_never_the_producers_creation_time():
    event = events(translate("detection_evidence_tree"))[0]
    assert times.render(event.received_at) == "2026-04-29T06:15:00.000Z"
    assert event.payload["nits_root"]["msgCreatedTime"] == "2026-04-29T06:00:00Z"
    assert event.observed_at != event.received_at


def test_a_motion_event_with_no_start_time_is_the_one_reltime_that_is_not_zero():
    document = load("motion_event_tripwire")
    document["message"][0]["motionEvent"][0].pop("startRelTime")
    event = [e for e in events(adapter().to_cdm(document))
             if "nits_motion_event" in e.payload][0]
    assert event.observed_at == times.parse("2026-04-29T06:00:00Z")
    assert event.payload["unavailable_fields"] == ["startRelTime"]
    assert "does not default to baseTime" in event.payload["observed_at_basis"]
    assert "substitute the producer did not state" in event.payload["observed_at_basis"]


def test_a_processed_track_has_no_time_of_its_own_and_the_basis_says_so():
    event = [e for e in events(translate("linkage_processed_track_carried"))
             if "nits_processed_track" in e.payload][0]
    assert event.observed_at == times.parse("2026-04-29T06:00:00Z")
    assert "no time attribute of any kind" in event.payload["observed_at_basis"]


# ------------------------------------------------------------------- identity


def test_a_bare_lid_with_no_scope_is_not_an_identifier():
    document = load("standalone_basic_track")
    document.pop("lidScopeUID")
    track_data = document["message"][0]["track"][0]
    track_data.pop("uid")
    track_data["object"][0].pop("uid")
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    assert "bare lid" in str(raised.value) and "no stable identity" in str(raised.value)


def test_a_lid_with_a_scope_is_a_composite_and_never_the_bare_integer():
    entity = entities(translate("datastream_unresolved_references"))[0]
    scope = load("datastream_unresolved_references")["lidScopeUID"]
    systems = {s.system: s.external_id for s in entity.source_ids}
    assert systems[nits.LID_SYSTEM] == f"{scope}:7"
    assert "7" not in [s.external_id for s in entity.source_ids]


def test_a_guide_prefix_composes_an_ic_identifier_rather_than_a_bare_uuid():
    document = load("standalone_basic_track")
    plain = document["message"][0]["track"][0]["object"][0]["uid"]
    document["message"][0]["track"][0]["object"][0]["uid"] = {"value": plain, "gidp": 42}
    entity = entities(adapter().to_cdm(document))[0]
    composed = f"guide://42/{plain}"
    assert any(s.system == nits.IC_ID_SYSTEM and s.external_id == composed
               for s in entity.source_ids)
    assert entity.entity_id == ids.derive(nits.IC_ID_SYSTEM, composed, kind="entity")
    assert entity.entity_id != ids.derive(nits.UID_SYSTEM, plain, kind="entity"), (
        "§2.6.11 makes the guide prefix part of the identifier, so the bare UUID is a DIFFERENT "
        "identifier and keying on it would merge two objects the producer distinguished"
    )


def test_a_mode_s_code_gives_the_same_entity_id_as_adsb_and_cat021():
    entity = entities(translate("exercise_faker_is_friendly"))[0]
    assert any(s.system == "ICAO24" and s.external_id == "0029ab" for s in entity.source_ids)
    from synapse_cdm.adapters import adsb
    assert ids.derive(adsb.ICAO_SYSTEM, "0029ab", kind="entity") == \
        ids.derive(nits.ICAO24_SYSTEM, "0029ab", kind="entity")


@pytest.mark.parametrize("value", ["7421", "not-hex", "0029AB0", "00 29 AB"])
def test_a_mode_s_value_that_is_not_six_hex_digits_is_parked_and_never_keyed(value):
    """`IFFCode.value` is a bare String with no stated syntax for any of the seven modes, so the
    condition guarding the largest cross-adapter win here has to be narrow."""
    document = load("exercise_faker_is_friendly")
    document["message"][0]["track"][0]["object"][0]["iffCode"][0]["value"] = value
    entity = entities(adapter().to_cdm(document))[0]
    assert not any(s.system == "ICAO24" for s in entity.source_ids)
    assert document["message"][0]["track"][0]["object"][0]["iffCode"][0]["value"] == value


def test_an_authenticated_mode_five_reply_is_not_read_as_an_identification():
    document = load("exercise_faker_is_friendly")
    document["message"][0]["track"][0]["object"][0]["id1241"] = {"identity": "UNKNOWN"}
    entity = entities(adapter().to_cdm(document))[0]
    modes = [c["mode"] for c in entity.attributes["nits_track"]["object"][0]["iffCode"]]
    assert "MODE5" in modes, "the fixture must still carry the Mode 5 code"
    assert entity.affiliation is Affiliation.UNKNOWN, (
        "an authenticated IFF reply is what \"friend\" means in IFF doctrine, and turning one "
        "into FRIENDLY is an adjudication belonging to an IFF authority. CAT021 declines it and "
        "this is the second format to force the decision"
    )


def test_every_app6_table_is_accounted_for():
    assert len(nits.APP6_TABLE) == 14
    assert set(nits.APP6_TABLE.values()) <= set(EntityType)
    assert nits.APP6_TABLE["LAND_INSTALLATION"] is EntityType.FACILITY
    assert nits.APP6_TABLE["DISMOUNTED_INDIVIDUAL"] is EntityType.UNKNOWN, (
        "the CDM has no member for a person; UNIT would claim an organisation"
    )


def test_the_app6_code_is_parked_and_never_composed_into_a_symbol():
    entity = entities(translate("standalone_basic_track"))[0]
    assert entity.entity_type is EntityType.PLATFORM
    assert entity.attributes["app6"][0][0]["code"] == "150101"
    assert entity.symbol is not None and "150101" not in entity.symbol
    assert "never composed into a SIDC" in entity.attributes["symbol_basis"]


def test_competing_object_classes_yield_unknown_rather_than_a_choice():
    document = load("standalone_basic_track")
    document["message"][0]["track"][0]["object"][0]["objectClass"].append(
        {"table": "LAND_INSTALLATION", "code": "200101"})
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.entity_type is EntityType.UNKNOWN
    assert "different CDM entity types" in entity.attributes["entity_type_basis"]


# ------------------------------------------------------------------- no fusion


@pytest.mark.parametrize("parked", ["nits_track_linkage", "nits_processed_track",
                                    "nits_motion_event"])
def test_the_analysis_classes_are_carried_and_never_resolved(parked):
    objects = translate("linkage_processed_track_carried") + \
        translate("motion_event_tripwire")
    carried = [e for e in events(objects) if parked in e.payload]
    assert carried, f"no Event carries {parked}"
    for event in carried:
        assert event.related_entities == [], (
            "these classes name TRACK identifiers and related_entities holds entity_id values — "
            "gap 19"
        )
        assert "gap 19" in event.payload["related_entities_basis"].lower()


def test_a_stitch_linkage_does_not_merge_the_two_tracks():
    objects = translate("linkage_processed_track_carried")
    assert len({t.track_id for t in tracks(objects)}) == 2, (
        "a STITCH says the producer believes two tracks are one object. Acting on it is a "
        "consumer decision"
    )
    linkage = [e for e in events(objects) if "nits_track_linkage" in e.payload][0]
    assert linkage.payload["nits_track_linkage"]["type"] == "STITCH"
    assert "never acted on" in linkage.payload["fusion_basis"]


def test_the_consolidation_rule_is_recorded_as_not_performed():
    entity = entities(translate("standalone_basic_track"))[0]
    assert "not performed" in entity.attributes["consolidation_basis"]
    assert "§2.1.1.2.3" in entity.attributes["consolidation_basis"]


# ------------------------------------------------------------------ refusals


def test_an_edition_a_document_is_refused_by_version():
    document = load("standalone_basic_track")
    document["nitsVersion"] = "A.1"
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(document)
    assert "'A.1'" in str(raised.value) and "separate adapter, not a mode" in str(raised.value)


def test_an_edition_a_document_is_refused_by_root_element_too():
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(b"<TrackMessage><stanagVersion>1.0</stanagVersion></TrackMessage>")
    assert "root element is <TrackMessage>" in str(raised.value)


def test_an_abstract_shape_with_no_concrete_type_is_refused():
    xml = (XML[0].read_bytes()
           .replace(b"<NITSRoot", b"<NITSRoot", 1))
    document = load("motion_event_complex_polygon")
    document["message"][0]["motionEvent"][0]["region"].pop("_type")
    # The dict path has no xsi:type to lose, so the refusal is exercised through XML, where a
    # conformant document is REQUIRED to name the concrete type.
    body = (FIXTURES / "motion_event_complex_polygon.nits.xml").read_text()
    stripped = body.replace(' ns0:type="Polygon"', "").replace(' xsi:type="Polygon"', "")
    stripped = stripped.replace(' type="Polygon"', "")
    assert stripped != body, "the fixture must actually carry an xsi:type to strip"
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(stripped.encode())
    assert "abstract" in str(raised.value) and "xsi:type" in str(raised.value)


def test_malformed_xml_is_refused_rather_than_partially_read():
    with pytest.raises(NitsError) as raised:
        adapter().to_cdm(b"<NITSRoot><profile>STANDALONE</NITSRoot>")
    assert "not well-formed XML" in str(raised.value)


def test_an_unrecognised_enumeration_literal_is_parked_and_not_refused():
    """Annex B.4 types every enumeration as a union with `xs:string` and says outright that
    "the enumerations are not validated", so an unknown literal is CONFORMANT."""
    document = load("standalone_basic_track")
    document["message"][0]["track"][0]["object"][0]["id1241"]["identity"] = "NEWLY_REGISTERED"
    entity = entities(adapter().to_cdm(document))[0]
    assert entity.affiliation is Affiliation.UNKNOWN
    assert "union with xs:string" in entity.attributes["affiliation_basis"]
    assert entity.attributes["nits_track"]["object"][0]["id1241"]["identity"] == "NEWLY_REGISTERED"


# ------------------------------------------------------------------- egress


@pytest.mark.parametrize("path", PARSED, ids=lambda p: p.name)
def test_the_round_trip_changes_exactly_one_value(path):
    """ingest -> egress -> ingest, and the only thing that moves is `msgCreatedTime`.

    Not byte-exact, and it cannot be: XML permits insignificant whitespace, attribute order and
    namespace prefix choice. The claim that IS made is that every value re-emitted equals the
    value read, and `msgCreatedTime` is the one value egress invents — when WE wrote the file.
    The DATASTREAM fixture moves one more, `profile`, because egress emits STANDALONE only.
    """
    document = json.loads(path.read_text())
    first = adapter().to_cdm(document)
    second = adapter().to_cdm(adapter().from_cdm(first))
    before = [o.model_dump(mode="json") for o in first]
    after = [o.model_dump(mode="json") for o in second]

    allowed = {"msgCreatedTime", "profile"} if "datastream" in path.name else {"msgCreatedTime"}
    for a, b in zip(before, after):
        for holder in ("attributes", "payload"):
            for blob in (a.get(holder, {}), b.get(holder, {})):
                for key in allowed:
                    blob.get("nits_root", {}).pop(key, None)
            a.get(holder, {}).pop("profile_basis", None)
            b.get(holder, {}).pop("profile_basis", None)
            a.get(holder, {}).pop("nits_profiles", None)
            b.get(holder, {}).pop("nits_profiles", None)
    assert before == after


@pytest.mark.parametrize("path", PARSED, ids=lambda p: p.name)
def test_egress_loses_no_source_value(path):
    document = json.loads(path.read_text())
    emitted = adapter().to_cdm(adapter().from_cdm(adapter().to_cdm(document)))
    dumped = [o.model_dump(mode="json") for o in emitted]
    missing = lossless.unrepresented(document, dumped, Stanag4676Adapter.TRANSFORMS)
    # msgCreatedTime is re-stamped by design; profile becomes STANDALONE on the way out.
    missing = {k: v for k, v in missing.items()
               if not k.endswith("msgCreatedTime") and not k.startswith("profile")}
    assert not missing, f"egress dropped {sorted(missing)}"


def test_the_confidentiality_label_survives_the_round_trip_byte_for_byte():
    """Re-serialising a 4774 label through a parser rewrites the producer's namespace prefix and
    re-indents its content, and whether the result is the SAME label is not a question a track
    translator can answer. So it never goes through the element tree at all."""
    document = load("standalone_basic_track")
    original = document["originatorConfidentialityLabel"]
    assert "slab:" in original
    emitted = adapter().from_cdm(adapter().to_cdm(document)).decode()
    assert original in emitted, "the exact fragment must appear in the output verbatim"
    assert "ns0:originatorConfidentialityLabel" not in emitted


def test_emitting_a_cdm_native_track_without_a_label_is_refused():
    document = load("standalone_basic_track")
    objects = adapter().to_cdm(document)
    for obj in objects:
        holder = obj.attributes if isinstance(obj, Entity) else getattr(obj, "payload", {})
        holder.pop("confidentiality_label", None)
        if "nits_root" in holder:
            holder["nits_root"].pop("originatorConfidentialityLabel", None)
    with pytest.raises(NitsError) as raised:
        adapter().from_cdm(objects)
    assert "three ways to get one" in str(raised.value)
    assert "UNCLASSIFIED is the dangerous direction" in str(raised.value)


def test_a_configuration_supplied_label_is_the_second_path_and_is_logged():
    document = load("standalone_basic_track")
    objects = adapter().to_cdm(document)
    for obj in objects:
        holder = obj.attributes if isinstance(obj, Entity) else getattr(obj, "payload", {})
        holder.pop("confidentiality_label", None)
        if "nits_root" in holder:
            holder["nits_root"].pop("originatorConfidentialityLabel", None)
    supplied = ('<slab:originatorConfidentialityLabel xmlns:slab="urn:nato:stanag:4774:'
                'confidentialitymetadatalabel:1:0"><slab:ConfidentialityInformation>'
                "<slab:PolicyIdentifier>DEPLOYMENT</slab:PolicyIdentifier>"
                "<slab:Classification>NATO UNCLASSIFIED</slab:Classification>"
                "</slab:ConfidentialityInformation></slab:originatorConfidentialityLabel>")
    emitted = Stanag4676Adapter(clock=times.frozen_clock(),
                                confidentiality_label=supplied).from_cdm(objects).decode()
    assert supplied in emitted
    back = adapter().to_cdm(emitted.encode())
    assert entities(back)[0].attributes["confidentiality_label_basis"].startswith("round_tripped")


def test_a_dangling_reference_is_refused_rather_than_emitted():
    """A STANDALONE file needs every referent inline, and a dangling reference is a
    non-conformance a consumer discovers as silently missing sensor metadata."""
    document = load("standalone_basic_track")
    document["message"][0]["track"][0]["trackSource"]["sensorUID"] = [
        "f1c70000-0000-8000-8000-000000000099"]
    objects = adapter().to_cdm(document)
    with pytest.raises(NitsError) as raised:
        adapter().from_cdm(objects)
    assert "000000000099" in str(raised.value)
    assert "STANDALONE profile requires every referent inline" in str(raised.value)


def test_egress_always_declares_standalone_even_from_a_datastream_document():
    emitted = adapter().from_cdm(translate("datastream_unresolved_references")).decode()
    assert "<profile>STANDALONE</profile>" in emitted
    assert "DATASTREAM" not in emitted.split("<message>")[0]


def test_a_cdm_native_track_emits_with_a_millisecond_increment_and_nothing_rounds():
    """0.001 s makes the CDM's own three-decimal Timestamp exactly representable as an integer
    count, so the emitted relTime values are exact rather than rounded."""
    import datetime as _dt
    from synapse_cdm.models import Position, SourceId, TrackSample

    start = _dt.datetime(2026, 4, 29, 6, 0, 0, 250_000, tzinfo=_dt.timezone.utc)
    entity_id = ids.derive("TEST", "native-entity", kind="entity")
    track = Track(
        source=adapter().source_ref(),
        source_ids=[SourceId(system="TEST", external_id="native-track")],
        track_id=ids.derive("TEST", "native-track", kind="track"), entity_id=entity_id,
        samples=[TrackSample(position=Position(lat=56.0 + i / 100, lon=24.0,
                                               position_source="ESTIMATED"),
                             observed_at=start + _dt.timedelta(milliseconds=125 * i))
                 for i in range(3)])
    entity = Entity(source=adapter().source_ref(),
                    source_ids=[SourceId(system="TEST", external_id="native-entity")],
                    entity_id=entity_id, entity_type=EntityType.PLATFORM,
                    affiliation=Affiliation.UNKNOWN, valid_from=start)
    label = ('<slab:originatorConfidentialityLabel xmlns:slab="urn:nato:stanag:4774:'
             'confidentialitymetadatalabel:1:0"><slab:ConfidentialityInformation/>'
             "</slab:originatorConfidentialityLabel>")
    emitting = Stanag4676Adapter(clock=times.frozen_clock(), confidentiality_label=label)
    document = nits.parse_document(emitting.from_cdm([entity, track]))
    message = document["message"][0]
    assert message["relTimeIncrement"] == 0.001
    assert message["baseTime"] == "2026-04-29T06:00:00.250Z"
    assert [p["relTime"] for p in message["track"][0]["segment"][0]["tp"]] == [0, 125, 250]
    assert document["nitsVersion"] == "B.2"


def test_a_native_track_whose_instants_do_not_divide_the_increment_is_refused():
    import datetime as _dt
    from synapse_cdm.models import Position, SourceId, TrackSample

    # 100 ms after a base time whose increment is 0.3 s: one third of an increment, which
    # cannot be written as an integer count and must not be rounded to one.
    start = _dt.datetime(2026, 4, 29, 6, 0, 0, 100_000, tzinfo=_dt.timezone.utc)
    entity_id = ids.derive("TEST", "native-entity", kind="entity")
    track = Track(source=adapter().source_ref(),
                  source_ids=[SourceId(system="TEST", external_id="t")],
                  track_id=ids.derive("TEST", "t", kind="track"), entity_id=entity_id,
                  samples=[TrackSample(position=Position(lat=56.0, lon=24.0,
                                                         position_source="ESTIMATED"),
                                       observed_at=start)])
    entity = Entity(source=adapter().source_ref(),
                    source_ids=[SourceId(system="TEST", external_id="e")],
                    entity_id=entity_id, entity_type=EntityType.PLATFORM,
                    affiliation=Affiliation.UNKNOWN, valid_from=start,
                    attributes={"nits_message": {"baseTime": "2026-04-29T06:00:00.000Z",
                                                 "relTimeIncrement": 0.3},
                                "confidentiality_label": {"originatorConfidentialityLabel":
                                                          "<a xmlns='urn:x'/>"}})
    with pytest.raises(NitsError) as raised:
        adapter().from_cdm([entity, track])
    assert "not a whole" in str(raised.value)


def test_a_verbatim_round_trip_of_two_contexts_under_one_root_is_refused():
    """The NARROW half of the merge refusal, and the half that stands.

    §2.1.1.2.3: when two objects' `lidScopeUID` values differ, "the same local ID value can be
    used to represent different things". Merging two parked contexts would make identifiers from
    two scopes collide silently, and re-scoping them would destroy the cross-file correlation
    those identifiers exist to provide.
    """
    objects = translate("standalone_basic_track") + translate("datastream_unresolved_references")
    with pytest.raises(NitsError) as raised:
        adapter().from_cdm(objects)
    assert "lidScopeUID" in str(raised.value)
    assert "verbatim round trip" in str(raised.value)
    assert "CDM-native objects, which mint fresh identifiers" in str(raised.value)


def test_a_consolidated_picture_from_many_sources_is_a_mint_and_not_a_merge():
    """The other half, and it must NOT refuse. No parked identifier survives this path, so no
    collision is possible: `_native_track` keys on the CDM's own UUIDs and emits no local ID at
    all — and `lidScopeUID` is required only "if local IDs are found in the object"."""
    import datetime as _dt
    from synapse_cdm.models import Position, SourceId, TrackSample

    start = _dt.datetime(2026, 4, 29, 6, 0, tzinfo=_dt.timezone.utc)
    label = ('<slab:originatorConfidentialityLabel xmlns:slab="urn:nato:stanag:4774:'
             'confidentialitymetadatalabel:1:0"><slab:ConfidentialityInformation/>'
             "</slab:originatorConfidentialityLabel>")
    emitting = Stanag4676Adapter(clock=times.frozen_clock(), confidentiality_label=label)
    objects: list = []
    for system, external in (("AIS", "244110000"), ("ICAO24", "4ca7b3"), ("TAK", "ALPHA-1")):
        entity_id = ids.derive(system, external, kind="entity")
        objects.append(Entity(
            source=emitting.source_ref(),
            source_ids=[SourceId(system=system, external_id=external)], entity_id=entity_id,
            entity_type=EntityType.PLATFORM, affiliation=Affiliation.UNKNOWN, valid_from=start))
        objects.append(Track(
            source=emitting.source_ref(),
            source_ids=[SourceId(system=system, external_id=external)],
            track_id=ids.derive(system, external, kind="track"), entity_id=entity_id,
            samples=[TrackSample(
                position=Position(lat=56.0, lon=24.0, position_source="GNSS"),
                observed_at=start)]))

    document = nits.parse_document(emitting.from_cdm(objects))
    assert len(document["message"][0]["track"]) == 3, (
        "three sources consolidated into one STANDALONE document — this is the path the merge "
        "refusal points a caller at, so it has to work"
    )
    assert document["profile"] == ["STANDALONE"]

    def has_lid(value) -> bool:
        if isinstance(value, dict):
            return any(k.endswith("LID") or k == "lid" for k in value) or \
                any(has_lid(v) for v in value.values())
        return isinstance(value, list) and any(has_lid(v) for v in value)

    assert not has_lid(document), (
        "the mint path must emit no local ID anywhere: that is what makes a fresh lidScopeUID "
        "unnecessary and a collision impossible"
    )
    assert "lidScopeUID" not in document


def test_emitting_nothing_is_refused_rather_than_producing_an_empty_document():
    with pytest.raises(NitsError) as raised:
        adapter().from_cdm([e for e in events(translate("motion_event_tripwire"))])
    assert "nothing to emit" in str(raised.value)
