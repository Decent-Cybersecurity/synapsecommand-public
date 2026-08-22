"""One test per claim in the AIS adapter's docstring, plus the round trips the harness cannot do.

WHY THIS FILE CARRIES THE ROUND-TRIP CHECKS
-------------------------------------------
The harness's `roundtrip` column reports SKIP for an adapter that emits something it cannot
parse structurally, and says so out loud: `from_cdm()` here returns NMEA sentences, and a check
it cannot run must report SKIP rather than PASS. The README's instruction for that case is that
the adapter ships its own round-trip test — so both directions are exercised here, with the
same value-presence comparison (`lossless.unrepresented`) the harness would have used.

AND WHY THE PAYLOAD IS UNPACKED RATHER THAN EXEMPTED
-----------------------------------------------------
An AIS payload is one armoured string, so to `lossless` it is one leaf. A round-trip check that
compared the armoured strings would pass on any two payloads that happened to match and prove
nothing about the fields inside; one that declared the payload exempt would be measuring the
sentence envelope and calling it a translation test. So every comparison here runs over the
DECODED fields, both sides, and the strongest claim in the file is stronger still: for a
message this adapter ingested, re-emission reproduces the original sentences byte for byte.

THE CODEC IS PINNED INDEPENDENTLY
---------------------------------
`encode()` and `decode()` are inverses of each other by construction, so proving that says
nothing about whether either matches AIS. The armour alphabet, the checksum and one whole
message are therefore pinned against values computed in this file from the standard's own
definitions — a hand-assembled bit string, field by field, that must equal the shipped fixture.
"""
import functools
import json
import pathlib
import uuid

import pytest

import synapse_cdm
from synapse_cdm import lossless, times
from synapse_cdm.adapters import ais
from synapse_cdm.adapters.ais import AisAdapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import Entity, Event, Track

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "ais"
GOLDEN = FIXTURES / "golden"
EGRESS = FIXTURES / "egress"
SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "schemas"

NMEA_FIXTURES = sorted(FIXTURES.glob("*.nmea"))
EGRESS_FIXTURES = sorted(EGRESS.glob("*.json"))


def _adapter() -> AisAdapter:
    return AisAdapter(clock=times.frozen_clock())


def _translate(name: str) -> tuple[Entity, Event]:
    entity, event = _adapter().to_cdm((FIXTURES / name).read_bytes())
    return entity, event


def _object(name: str):
    raw = json.loads((EGRESS / name).read_text())
    return (Track if raw["object_kind"] == "track" else Entity).model_validate(raw)


def _parse_all(emitted: bytes) -> list[dict]:
    """Every message in an emitted burst, separately.

    `_parse_nmea` translates ONE message per payload by design, and a Track legitimately emits
    several. Grouping them here rather than relaxing the adapter keeps the refusal — which is
    what stops a feed's framing from becoming the translator's problem — intact.
    """
    lines = [line for line in emitted.decode("ascii").split(ais.SENTENCE_TERMINATOR) if line]
    messages, buffered = [], []
    for line in lines:
        buffered.append(line)
        head = ais._parse_sentence(line)
        if head["fragment_number"] == head["fragment_count"]:
            messages.append(ais._parse_nmea(ais.SENTENCE_TERMINATOR.join(buffered)))
            buffered = []
    assert not buffered, "emitted burst ends on an incomplete fragment"
    return messages


def _strip_tag_blocks(raw: bytes) -> bytes:
    """The sentences without the receiver's TAG annotations — see NOT_RETRANSMITTED."""
    lines = [line.rsplit("\\", 1)[-1]
             for line in raw.decode("ascii").split(ais.SENTENCE_TERMINATOR) if line]
    return (ais.SENTENCE_TERMINATOR.join(lines) + ais.SENTENCE_TERMINATOR).encode("ascii")


# --------------------------------------------------------------- the fixture set


def test_the_fixture_set_is_not_silently_empty():
    """A parametrised suite over a glob that matches nothing passes while testing nothing."""
    assert len(NMEA_FIXTURES) >= 8, f"expected >=8 ingest fixtures, found {len(NMEA_FIXTURES)}"
    assert len(EGRESS_FIXTURES) >= 3, f"expected >=3 egress fixtures, found {len(EGRESS_FIXTURES)}"
    covered = {ais._parse_nmea(p.read_bytes())["message"]["type"] for p in NMEA_FIXTURES}
    assert covered == set(ais.LAYOUTS), (
        f"the fixture set covers message types {sorted(covered)} but the adapter claims "
        f"{sorted(ais.LAYOUTS)} — a type in scope with no fixture is a claim with no evidence"
    )


@pytest.mark.parametrize("path", NMEA_FIXTURES, ids=lambda p: p.name)
def test_every_nmea_fixture_ships_its_parsed_form_and_they_agree(path):
    """The `.parsed.json` twin must be EXACTLY what the parser produces from the `.nmea`.

    The twin exists because the harness cannot run its lossless check on a non-JSON fixture —
    it has no leaf structure to harvest — so an AIS-only fixture set would show a green run
    with the never-drop rule never actually checked. That only works if the two forms are the
    same payload, which is what this asserts: hand-maintained, they would drift, and the drift
    would be invisible because both fixtures would still pass on their own.
    """
    twin = path.parent / f"{path.stem}.parsed.json"
    assert twin.is_file(), f"{path.name} has no .parsed.json twin — the lossless check would SKIP"
    assert json.loads(twin.read_text()) == ais._parse_nmea(path.read_bytes()), (
        f"{twin.name} is not what {path.name} parses to. Regenerate it from the sentences "
        "rather than editing it by hand."
    )


@pytest.mark.parametrize("path", NMEA_FIXTURES, ids=lambda p: p.name)
def test_the_nmea_and_parsed_paths_produce_identical_output(path):
    """The parse is the ONLY difference between the two forms, so the goldens must be equal.

    This is what keeps `_parse_nmea()` and the translation from disagreeing. If the dict path
    ever produced something the sentence path did not, one of the two golden files would be a
    recorded lie about the adapter — and each would still pass its own golden check.
    """
    from_nmea = json.loads((GOLDEN / f"{path.stem}.cdm.json").read_text())
    from_dict = json.loads((GOLDEN / f"{path.stem}.parsed.cdm.json").read_text())
    assert from_nmea == from_dict


def test_no_fixture_carries_a_real_world_mmsi_range():
    """Synthetic only. MID 299 is unallocated, and 970 is the SART prefix — see the README."""
    for path in NMEA_FIXTURES:
        mmsi = ais._parse_nmea(path.read_bytes())["message"]["mmsi"]
        _, mid = ais._mmsi_category(mmsi)
        assert mid in (None, "299"), (
            f"{path.name} carries MMSI {mmsi} with MID {mid}, which is an allocated "
            "administration — fixtures must use the unallocated MID 299"
        )


# ------------------------------------------------------------------- the codec


def test_the_six_bit_armour_matches_the_published_mapping():
    """Pinned against the standard's own table, not against the encoder.

    The gap at 40 is the whole difficulty: printable ASCII is not contiguous across the range
    the armour uses, and getting the discontinuity wrong shifts every field after the first
    character rather than failing outright.
    """
    for character, expected in (("0", 0), ("W", 39), ("`", 40), ("w", 63)):
        assert ais._bits_of(character, 0) == f"{expected:06b}", character
    every_value = "".join(f"{v:06b}" for v in range(64))
    payload, fill = ais._armour(every_value)
    assert fill == 0 and ais._bits_of(payload, fill) == every_value


def test_the_checksum_is_the_xor_of_the_sentence_body():
    body = "AIVDM,1,1,,A,14M9Q>h2B:Qe8fPPuCS7Dmr`0D7k,0"
    assert ais._checksum(body) == f"{functools.reduce(lambda a, c: a ^ ord(c), body, 0):02X}"


def test_a_hand_assembled_message_decodes_field_by_field_and_is_the_shipped_fixture():
    """The one test that ties this codec to AIS rather than to itself.

    Every field is laid out here at its published width, from values written in this file, and
    the resulting armoured payload must be character-for-character the payload in the shipped
    fixture. That pins the field ORDER, every field WIDTH, the signed encoding, the 1/10000
    minute scaling and the armour, none of which could be established by encoding and decoding
    with the same module.
    """
    bits = (f"{1:06b}{0:02b}{299000123:030b}"          # type, repeat, MMSI
            f"{0:04b}{9:08b}{138:010b}{1:01b}"          # status, ROT, SOG 13.8 kn, accuracy
            f"{14304720:028b}{34558860:027b}"           # lon 23.8412, lat 57.5981, 1/10000 min
            f"{1875:012b}{189:09b}{20:06b}"             # COG 187.5, heading, UTC second
            f"{0:02b}{0:03b}{0:01b}{82419:019b}")       # manoeuvre, spare, RAIM, radio state
    assert len(bits) == 168, "a type 1 message is 168 bits"

    decoded = ais.decode(bits)
    assert decoded["mmsi"] == "299000123"
    assert decoded["lat"] == 57.5981 and decoded["lon"] == 23.8412
    assert decoded["sog_knots"] == 13.8 and decoded["cog_deg"] == 187.5
    assert decoded["true_heading_deg"] == 189 and decoded["utc_second"] == 20
    assert decoded["rate_of_turn_raw"] == 9 and decoded["radio_status"] == 82419

    payload, fill = ais._armour(bits)
    shipped = ais._parse_nmea((FIXTURES / "class_a_underway_gulf_of_riga.nmea").read_bytes())
    assert (payload, fill) == (shipped["sentences"][0]["payload"],
                               shipped["sentences"][0]["fill_bits"])


def test_a_negative_rate_of_turn_uses_twos_complement():
    """Signed fields are two's complement, and reading one as unsigned yields 242, not -14."""
    assert ais._signed("11110010") == -14
    assert ais._twos_complement_bits(-14, 8) == "11110010"
    assert ais._signed(ais._twos_complement_bits(-128, 8)) == ais.ROT_UNAVAILABLE


@pytest.mark.parametrize("path", NMEA_FIXTURES, ids=lambda p: p.name)
def test_encode_is_the_exact_inverse_of_decode(path):
    """Every bit is decoded — spares and radio state included — so re-encoding is exact.

    Not a tidiness property. It is what makes the round-trip claim measurable instead of
    reviewable: if a field were skipped on the way in, re-encoding would have to invent it,
    and the payload would differ.
    """
    parsed = ais._parse_nmea(path.read_bytes())
    reassembled = "".join(
        ais._bits_of(s["payload"], s["fill_bits"] if s is parsed["sentences"][-1] else 0)
        for s in parsed["sentences"])
    assert ais.encode(parsed["message"]) == reassembled


def test_fill_bits_belong_to_the_last_fragment_only():
    """A two-fragment message pads once, at the end — counting it twice corrupts the middle."""
    parsed = ais._parse_nmea((FIXTURES / "static_voyage_two_fragments.nmea").read_bytes())
    assert [s["fill_bits"] for s in parsed["sentences"]] == [0, 2]
    assert parsed["message"]["vessel_name"] == "EXERCISE VESSEL ALFA"


# ---------------------------------------------------------- ingest: the AIS table


def test_the_mmsi_becomes_the_source_id_on_both_objects():
    entity, event = _translate("class_a_underway_gulf_of_riga.nmea")
    assert [(s.system, s.external_id) for s in entity.source_ids] == [("AIS", "299000123")]
    assert [(s.system, s.external_id) for s in event.source_ids] == [("AIS", "299000123")]


def test_the_entity_id_is_derived_from_the_mmsi_and_therefore_stable():
    entity, _ = _translate("class_a_underway_gulf_of_riga.nmea")
    assert entity.entity_id == uuid.uuid5(
        __import__("synapse_cdm.ids", fromlist=["NAMESPACE"]).NAMESPACE,
        "entity|AIS|299000123")
    assert entity.attributes["entity_id_basis"] == "message MMSI"


def test_two_reports_of_one_station_share_an_entity_id_and_do_not_share_an_event_id():
    """A position report and a static report from one vessel are one object and two events."""
    position_entity, position_event = _translate("class_a_underway_gulf_of_riga.nmea")
    static_entity, static_event = _translate("static_voyage_two_fragments.nmea")
    assert position_entity.entity_id == static_entity.entity_id
    assert position_event.event_id != static_event.event_id


def test_the_imo_number_is_a_second_source_id_and_not_a_replacement():
    """An MMSI changes with the flag; an IMO number is fixed for the life of the hull."""
    entity, _ = _translate("static_voyage_two_fragments.nmea")
    assert [(s.system, s.external_id) for s in entity.source_ids] == [
        ("AIS", "299000123"), ("IMO", "9284702")]


def test_a_message_without_an_imo_number_gets_no_imo_source_id_rather_than_zero():
    entity, _ = _translate("class_a_underway_gulf_of_riga.nmea")
    assert all(s.system != "IMO" for s in entity.source_ids)
    assert "imo_number" not in entity.attributes


@pytest.mark.parametrize("fixture,expected", [
    ("class_a_underway_gulf_of_riga.nmea", EntityType.PLATFORM),
    ("class_b_own_station_ventspils.nmea", EntityType.PLATFORM),
    ("base_station_liepaja.nmea", EntityType.FACILITY),
    ("aid_to_navigation_off_position.nmea", EntityType.FACILITY),
    ("aid_to_navigation_virtual.nmea", EntityType.OVERLAY_OBJECT),
])
def test_the_message_type_and_the_mmsi_decide_the_entity_type(fixture, expected):
    entity, _ = _translate(fixture)
    assert entity.entity_type == expected


def test_a_virtual_aid_is_an_overlay_object_and_not_a_facility():
    """Nothing physical floats there, and painting a chart symbol as a structure is a lie."""
    virtual, _ = _translate("aid_to_navigation_virtual.nmea")
    real, _ = _translate("aid_to_navigation_off_position.nmea")
    assert virtual.attributes["virtual_aid"] is True
    assert virtual.entity_type == EntityType.OVERLAY_OBJECT
    assert real.attributes["virtual_aid"] is False
    assert real.entity_type == EntityType.FACILITY


def test_the_mmsi_structure_is_read_and_the_flag_state_is_not_looked_up():
    for fixture, category, mid in (
            ("class_a_underway_gulf_of_riga.nmea", "ship station", "299"),
            ("base_station_liepaja.nmea", "coast station", "299"),
            ("aid_to_navigation_virtual.nmea", "aid to navigation", "299"),
            ("sart_active_distress.nmea", "AIS-SART (search and rescue transmitter)", None)):
        entity, _ = _translate(fixture)
        assert entity.attributes["mmsi_category"] == category, fixture
        assert entity.attributes.get("mmsi_mid") == mid, fixture
    # And nowhere does a country name appear: a flag of registration is not an affiliation.
    entity, _ = _translate("class_a_underway_gulf_of_riga.nmea")
    assert "country" not in json.dumps(entity.attributes).lower()


# ------------------------------------------------------------- ingest: sentinels


@pytest.mark.parametrize("field,sentinel", list(ais.UNAVAILABLE_WHEN))
def test_every_declared_sentinel_is_the_standards_value_and_not_a_guess(field, sentinel):
    """A sentinel table nobody checks drifts. Each entry is the value AIS actually reserves."""
    published = {
        "lat": 91.0, "lon": 181.0, "sog_knots": 102.3, "cog_deg": 360.0,
        "true_heading_deg": 511, "rate_of_turn_raw": -128, "utc_second": 60,
        "navigational_status": 15, "epfd": 0, "imo_number": 0, "ship_type": 0,
        "draught_m": 0.0, "dim_to_bow": 0, "dim_to_stern": 0, "dim_to_port": 0,
        "dim_to_starboard": 0, "eta_month": 0, "eta_day": 0, "eta_hour": 24,
        "eta_minute": 60, "call_sign": "", "vessel_name": "", "destination": "", "name": "",
    }
    assert published[field] == sentinel


def test_the_sentinels_become_absent_fields_and_never_measurements():
    """The fixture carrying all of them at once. Not one may reach the output as a number."""
    entity, _ = _translate("class_a_sentinels_no_position.nmea")
    assert entity.position is None, "latitude 91 / longitude 181 must not become a position"
    assert entity.kinematics is None, "speed 102.3 / course 360 must not become motion"
    assert "true_heading_deg" not in entity.attributes
    assert "rate_of_turn_deg_per_min" not in entity.attributes
    # The raw -128 IS kept, so the sentinel is recoverable rather than erased — that is the
    # difference between translating a sentinel and dropping the field.
    assert entity.attributes["rate_of_turn_raw"] == ais.ROT_UNAVAILABLE
    rendered = json.dumps(entity.model_dump(mode="json")["position"])
    assert "91" not in rendered and "181" not in rendered


def test_the_source_says_which_fields_it_could_not_supply():
    """The distinction between "the vessel does not know" and "we had nothing to say"."""
    entity, _ = _translate("class_a_sentinels_no_position.nmea")
    assert set(entity.attributes["unavailable_fields"]) >= {
        "lat", "lon", "sog_knots", "cog_deg", "true_heading_deg", "rate_of_turn_raw",
        "navigational_status"}
    populated, _ = _translate("class_a_underway_gulf_of_riga.nmea")
    assert populated.attributes["unavailable_fields"] == []


def test_a_draught_of_zero_is_not_a_draught():
    """The one sentinel that is also a plausible reading, so the one most likely forwarded."""
    entity, _ = _translate("static_voyage_two_fragments.nmea")
    assert "draught_m" not in entity.attributes
    assert "draught_m" in entity.attributes["unavailable_fields"]


def test_a_dimension_of_zero_is_absent_and_a_half_hull_yields_no_length():
    entity, _ = _translate("aid_to_navigation_virtual.nmea")
    for field in ("dim_to_bow", "dim_to_stern", "length_m", "beam_m"):
        assert field not in entity.attributes, field
    stated, _ = _translate("static_voyage_two_fragments.nmea")
    assert stated.attributes["length_m"] == 120 and stated.attributes["beam_m"] == 18


def test_zero_speed_and_zero_course_are_real_measurements():
    """The mirror of the sentinel rule, and the reason it cannot be done by truthiness.

    A life raft is stationary and 0.0 kn is what that measures; due north is 0.0 degrees. An
    adapter that treated either as "no data" would erase a fix, which is the same defect as
    forwarding a sentinel, pointed the other way.
    """
    entity, _ = _translate("sart_active_distress.nmea")
    assert entity.kinematics is not None
    assert entity.kinematics.speed_mps == 0.0
    assert entity.kinematics.course_deg == 0.0


def test_zero_zero_is_a_real_position_and_is_not_treated_as_absence():
    entity, _ = _translate("equator_zero_meridian.nmea")
    assert entity.position is not None
    assert (entity.position.lat, entity.position.lon) == (0.0, 0.0)


def test_a_rate_of_turn_of_zero_is_a_measurement_and_the_floor_is_not():
    assert ais._rate_of_turn(0) == 0.0
    assert ais._rate_of_turn(ais.ROT_UNAVAILABLE) is None
    assert ais._rate_of_turn(127) is None, "+-127 is a floor, not a rate"
    assert ais._rate_of_turn(9) == 3.6


def test_speed_at_the_maximum_is_kept_and_the_floor_is_recorded():
    """102.2 means "102.2 knots or higher": a floored measurement, not an absence."""
    parsed = ais._parse_nmea((FIXTURES / "class_a_underway_gulf_of_riga.nmea").read_bytes())
    parsed["message"]["sog_knots"] = ais.SOG_AT_OR_ABOVE_MAXIMUM
    entity, _ = _adapter().to_cdm(parsed)
    assert entity.kinematics.speed_mps == round(102.2 * ais.KNOT_MPS, 4)
    assert entity.attributes["sog_at_or_above_maximum"] is True


# --------------------------------------------------------- ingest: the translation


def test_knots_become_metres_per_second_and_the_conversion_is_exact():
    entity, _ = _translate("class_a_underway_gulf_of_riga.nmea")
    assert entity.kinematics.speed_mps == round(13.8 * 1852 / 3600, 4)
    assert entity.kinematics.course_deg == 187.5


def test_the_position_accuracy_flag_is_not_written_as_an_accuracy_in_metres():
    """A threshold is not a measurement. Writing 10.0 would state an error nobody measured."""
    entity, _ = _translate("class_a_underway_gulf_of_riga.nmea")
    assert entity.position.accuracy_m is None
    assert entity.attributes["position_accuracy_high"] is True


@pytest.mark.parametrize("fixture,expected", [
    ("class_a_underway_gulf_of_riga.nmea", PositionSource.GNSS),
    ("class_a_sentinels_no_position.nmea", PositionSource.ESTIMATED),
    ("base_station_liepaja.nmea", PositionSource.MANUAL),
    ("aid_to_navigation_virtual.nmea", PositionSource.MANUAL),
])
def test_the_position_source_is_read_and_understates_when_unsure(fixture, expected):
    entity, _ = _translate(fixture)
    source = entity.position.position_source if entity.position else \
        ais._position_source(ais._parse_nmea((FIXTURES / fixture).read_bytes())["message"])[0]
    assert source == expected
    assert entity.attributes["position_source_basis"]


def test_dead_reckoning_in_the_second_field_is_read_as_a_position_source():
    """`utc_second` 61-63 is the source saying the fix is not a GNSS fix, in a clock field."""
    for second, expected in ((61, PositionSource.MANUAL), (62, PositionSource.ESTIMATED),
                             (63, PositionSource.ESTIMATED)):
        assert ais._position_source({"utc_second": second})[0] == expected
    assert ais._position_source({"utc_second": 62, "epfd": 1})[0] == PositionSource.ESTIMATED, (
        "an explicit dead-reckoning statement must win over the EPFD the equipment carries")


def test_an_integrated_navigation_system_is_not_reported_as_inertial():
    """The dangerous direction: INERTIAL promises a fix that survives jamming."""
    assert ais.EPFD[6] == PositionSource.ESTIMATED
    assert ais.EPFD[7] == PositionSource.MANUAL


def test_the_affiliation_is_unknown_because_ais_states_no_identity():
    for path in NMEA_FIXTURES:
        entity, _ = _adapter().to_cdm(path.read_bytes())
        assert entity.affiliation == Affiliation.UNKNOWN, path.name
        assert "states no identity" in entity.attributes["affiliation_basis"]


def test_an_own_station_report_is_not_read_as_friendly():
    """AIVDO says whose transmitter it is, not whose side they are on.

    A feed relayed from a partner's receiver would make their ship ours by accident, and an
    affiliation invented in a translator is a judgement nobody can find later.
    """
    entity, _ = _translate("class_b_own_station_ventspils.nmea")
    assert entity.attributes["ais_talker"] == "AIVDO"
    assert entity.affiliation == Affiliation.UNKNOWN


def test_the_symbol_is_derived_and_marks_the_object_as_exercise_data():
    entity, _ = _translate("class_a_underway_gulf_of_riga.nmea")
    assert entity.symbol is not None and len(entity.symbol) == 20
    assert entity.symbol[2] == "2", "synthetic data must carry the simulation context digit"
    assert entity.symbol[3] == "1", "UNKNOWN is 2525D standard identity 1"
    live, _ = AisAdapter(clock=times.frozen_clock(), synthetic=False).to_cdm(
        (FIXTURES / "class_a_underway_gulf_of_riga.nmea").read_bytes())
    assert live.symbol[2] == "0"


def test_the_ship_type_does_not_become_the_entity_type():
    """A tanker, a tug and a pleasure craft are all PLATFORM. The wording is parked."""
    cargo, _ = _translate("static_voyage_two_fragments.nmea")
    pleasure, _ = _translate("class_b_extended_named.nmea")
    assert cargo.entity_type == pleasure.entity_type == EntityType.PLATFORM
    assert cargo.attributes["ship_type_text"] == "cargo (code 70)"
    assert pleasure.attributes["ship_type_text"] == "pleasure craft"


def test_the_navigational_status_keeps_its_code_and_its_wording():
    entity, _ = _translate("class_a_sentinels_no_position.nmea")
    assert entity.attributes["navigational_status"] == 15
    assert entity.attributes["navigational_status_text"] == "undefined"


def test_the_names_are_parked_because_there_is_no_canonical_home():
    """gap 1, now confirmed by a second adapter under four different keys."""
    vessel, _ = _translate("static_voyage_two_fragments.nmea")
    assert vessel.attributes["vessel_name"] == "EXERCISE VESSEL ALFA"
    assert vessel.attributes["call_sign"] == "ZZ9001A"
    assert vessel.attributes["destination"] == "RIGA"
    aid, _ = _translate("aid_to_navigation_virtual.nmea")
    assert aid.attributes["aid_name"] == "EXERCISE SPECIAL MARK ALFA", (
        "the name extension exists because the base field is 20 characters")


def test_the_eta_is_four_numbers_and_not_a_fabricated_timestamp():
    """AIS states no year, so assembling a Timestamp would need one invented."""
    entity, _ = _translate("static_voyage_two_fragments.nmea")
    assert entity.attributes["eta"] == {"month": 4, "day": 29, "hour": 18, "minute": 30}


def test_fields_the_coverage_table_does_not_map_are_parked_with_their_structure():
    entity, _ = _translate("class_b_own_station_ventspils.nmea")
    extras = entity.attributes["source_extras"]
    assert extras["message"]["radio_status"] == 393222
    assert extras["message"]["dsc_flag"] is True
    assert extras["sentences"][0]["payload"], "the armoured payload is the auditor's evidence"
    assert isinstance(extras["sentences"], list), "a list must stay a list"


# ------------------------------------------------------------------ ingest: time


def test_a_second_of_the_minute_is_reconciled_against_the_reception_instant():
    entity, event = _translate("class_a_underway_gulf_of_riga.nmea")
    assert times.render(event.observed_at) == "2026-04-29T06:11:20.000Z"
    assert times.render(event.received_at) == "2026-04-29T06:11:21.000Z"
    assert "utc_second 20" in event.payload["observed_at_basis"]
    assert entity.attributes["utc_second_raw"] == 20


def test_the_reconciliation_crosses_the_minute_boundary_the_short_way():
    """A message stamped second 58, received at 06:12:01, was sent at 06:11:58 — not 06:12:58."""
    reference = times.parse("2026-04-29T06:12:01Z")
    assert times.render(ais._reconcile_second(58, reference)) == "2026-04-29T06:11:58.000Z"
    assert times.render(ais._reconcile_second(2, times.parse("2026-04-29T06:11:59Z"))) == \
        "2026-04-29T06:12:02.000Z"


def test_a_base_station_states_a_full_instant_and_nothing_is_reconciled():
    _, event = _translate("base_station_liepaja.nmea")
    assert times.render(event.observed_at) == "2026-04-29T06:09:30.000Z"
    assert "nothing is reconciled" in event.payload["observed_at_basis"]
    # Five and a half minutes before receipt, which reconciliation would have destroyed.
    assert event.observed_at < event.received_at


def test_a_message_with_no_time_field_says_so_rather_than_implying_one():
    _, event = _translate("static_voyage_two_fragments.nmea")
    assert "carries no time field at all" in event.payload["observed_at_basis"]


def test_a_second_that_is_not_a_second_falls_back_and_records_why():
    entity, event = _translate("class_a_sentinels_no_position.nmea")
    assert entity.attributes["utc_second_raw"] == 63
    assert entity.attributes["utc_second_meaning"] == "positioning system inoperative"
    assert "not a time" in event.payload["observed_at_basis"]


def test_the_tag_block_supplies_the_delivery_instant_and_its_absence_is_recorded():
    _, with_tag = _translate("class_a_underway_gulf_of_riga.nmea")
    assert with_tag.payload["received_at_unix"] == 1777443081
    assert "TAG block" in with_tag.payload["received_at_basis"]
    _, without = _translate("equator_zero_meridian.nmea")
    assert without.payload["received_at_unix"] is None
    assert times.render(without.received_at) == times.render(times.FROZEN_NOW)


# ----------------------------------------------------------------- ingest: events


def test_an_active_distress_transmission_is_the_only_thing_that_raises_severity():
    entity, event = _translate("sart_active_distress.nmea")
    assert event.event_type == EventType.ALERT
    assert event.severity == Severity.CRITICAL
    assert entity.attributes["navigational_status"] == ais.STATUS_DISTRESS


def test_an_aid_off_its_station_does_not_raise_severity():
    """A station condition, not a distress transmission. Grading it would be fusion's job."""
    entity, event = _translate("aid_to_navigation_off_position.nmea")
    assert entity.attributes["off_position"] is True
    assert event.severity == Severity.INFO
    assert event.event_type == EventType.TRACK_UPDATE


def test_a_static_data_broadcast_is_not_a_track_update():
    """It carries no position, and TRACK_UPDATE would claim one."""
    entity, event = _translate("static_voyage_two_fragments.nmea")
    assert event.event_type == EventType.STATUS_CHANGE
    assert entity.position is None


def test_the_event_points_at_the_entity_and_carries_both_timestamps():
    entity, event = _translate("class_b_extended_named.nmea")
    assert event.related_entities == [entity.entity_id]
    assert event.observed_at and event.received_at
    assert event.geometry is None, "the position belongs to the station, not to the report"


# ------------------------------------------------------------- ingest: refusals


def test_a_corrupted_checksum_is_refused_rather_than_decoded():
    """A bit flip in the payload moves a vessel; it does not fail to parse."""
    original = (FIXTURES / "class_a_underway_gulf_of_riga.nmea").read_text()
    corrupted = original.replace("14M9Q>h2", "14M9Q>h3")
    with pytest.raises(ValueError, match="checksum"):
        _adapter().to_cdm(corrupted.encode("ascii"))


def test_a_message_type_out_of_scope_is_refused_by_name():
    """Type 24 in particular, so the structural reason is discoverable from the error."""
    bits = f"{24:06b}{0:02b}{299000123:030b}" + "0" * 130
    payload, fill = ais._armour(bits)
    body = f"AIVDM,1,1,,A,{payload},{fill}"
    with pytest.raises(ValueError, match="not in this adapter's scope"):
        _adapter().to_cdm(f"!{body}*{ais._checksum(body)}".encode("ascii"))


def test_a_truncated_payload_is_refused_rather_than_read_into_the_padding():
    payload, fill = ais._armour(f"{1:06b}{0:02b}{299000123:030b}")
    body = f"AIVDM,1,1,,A,{payload},{fill}"
    with pytest.raises(ValueError, match="too short"):
        _adapter().to_cdm(f"!{body}*{ais._checksum(body)}".encode("ascii"))


def test_two_messages_in_one_payload_are_refused_rather_than_half_translated():
    """Framing a stream into messages is the feed reader's job — see the type 24 argument."""
    doubled = ((FIXTURES / "equator_zero_meridian.nmea").read_bytes()
               + (FIXTURES / "sart_active_distress.nmea").read_bytes())
    with pytest.raises(ValueError, match="exactly one whole message per payload"):
        _adapter().to_cdm(doubled)


def test_a_missing_fragment_is_refused_rather_than_reassembled_from_what_arrived():
    # read_bytes, not read_text: universal newlines would fold CRLF to LF and hand the whole
    # two-fragment payload back, so the test would pass while testing nothing.
    raw = (FIXTURES / "static_voyage_two_fragments.nmea").read_bytes()
    first = raw.split(ais.SENTENCE_TERMINATOR.encode())[0] + ais.SENTENCE_TERMINATOR.encode()
    with pytest.raises(ValueError, match="exactly one whole message per payload"):
        _adapter().to_cdm(first)


def test_a_corrupted_tag_block_is_refused_because_it_carries_the_clock():
    line = "\\s:SC-RX,c:1777443081*00\\!AIVDM,1,1,,A,ABC,0*00"
    with pytest.raises(ValueError, match="TAG block checksum"):
        ais._parse_tag_block(line)


def test_a_line_that_is_not_an_encapsulation_sentence_is_refused():
    with pytest.raises(ValueError, match="does not start with"):
        _adapter().to_cdm(b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,,,,*47\r\n")


def test_the_adapter_refuses_a_type_it_cannot_take():
    with pytest.raises(TypeError, match="AIS adapter takes"):
        _adapter().to_cdm(42)


def test_a_position_outside_the_world_that_is_not_a_sentinel_is_refused():
    parsed = ais._parse_nmea((FIXTURES / "equator_zero_meridian.nmea").read_bytes())
    parsed["message"]["lat"] = 95.0
    with pytest.raises(ValueError, match="outside the valid range"):
        _adapter().to_cdm(parsed)


# --------------------------------------------------------------------- egress


@pytest.mark.parametrize("path", EGRESS_FIXTURES, ids=lambda p: p.name)
def test_every_egress_fixture_matches_its_golden(path):
    emitted = _adapter().from_cdm([_object(path.name)])
    golden = (EGRESS / "golden" / f"{path.stem}.ais.nmea").read_bytes()
    assert emitted == golden, (
        f"{path.name} no longer emits its golden sentences:\n"
        f"  golden  {golden!r}\n  emitted {emitted!r}")


def test_a_track_becomes_one_position_report_per_sample_in_its_own_order():
    track = _object("track_patrol_three_samples.json")
    messages = _parse_all(_adapter().from_cdm([track]))
    assert len(messages) == len(track.samples)
    for sample, parsed in zip(track.samples, messages):
        assert parsed["message"]["lat"] == sample.position.lat
        assert parsed["message"]["lon"] == sample.position.lon
        assert parsed["message"]["utc_second"] == sample.observed_at.second


def test_what_a_track_cannot_state_goes_out_as_sentinels_and_never_as_zeros():
    """The null-to-zero defect running outbound is the same defect."""
    messages = _parse_all(_adapter().from_cdm([_object("track_patrol_three_samples.json")]))
    for parsed in messages:
        assert parsed["message"]["sog_knots"] == ais.SOG_UNAVAILABLE
        assert parsed["message"]["cog_deg"] == ais.COG_UNAVAILABLE
        assert parsed["message"]["true_heading_deg"] == ais.HEADING_UNAVAILABLE


def test_an_entity_with_no_position_emits_the_sentinels_rather_than_the_equator():
    entity = _object("entity_fused_elsewhere.json")
    blanked = entity.model_copy(update={"position": None, "kinematics": None})
    message = _parse_all(_adapter().from_cdm([blanked]))[0]["message"]
    assert message["lat"] == ais.LAT_UNAVAILABLE and message["lon"] == ais.LON_UNAVAILABLE
    assert message["sog_knots"] == ais.SOG_UNAVAILABLE


def test_an_object_with_no_mmsi_is_refused_rather_than_given_a_derived_one():
    """Deriving one would put a station on the VHF data link under a number nobody allocated."""
    raw = json.loads((EGRESS / "track_patrol_three_samples.json").read_text())
    raw["source_ids"] = [{"system": "FUSION", "external_id": "T-1"}]
    orphan = Track.model_validate(raw)
    with pytest.raises(ValueError, match="no AIS source id"):
        _adapter().from_cdm([orphan])


def test_a_name_too_long_or_unrepresentable_is_refused_rather_than_corrupted():
    """A name cut short on the wire reads as the vessel's real name to every receiver."""
    entity = _object("entity_static_voyage_no_position.json")
    long_name = entity.model_copy(update={
        "attributes": {**entity.attributes, "vessel_name": "A" * 21}})
    with pytest.raises(ValueError, match="refusing to truncate"):
        _adapter().from_cdm([long_name])
    accented = entity.model_copy(update={
        "attributes": {**entity.attributes, "vessel_name": "KURZEMĒ"}})
    with pytest.raises(ValueError, match="six-bit alphabet cannot carry"):
        _adapter().from_cdm([accented])


def test_from_cdm_emits_one_objects_sentences_and_refuses_to_invent_a_container():
    with pytest.raises(ValueError, match="ONE object"):
        _adapter().from_cdm([_object("entity_fused_elsewhere.json"),
                             _object("track_patrol_three_samples.json")])
    with pytest.raises(ValueError, match="ONE object"):
        _adapter().from_cdm([])


def test_an_event_alone_is_not_emittable_but_supplies_the_second_of_the_minute():
    entity, event = _translate("class_a_underway_gulf_of_riga.nmea")
    with pytest.raises(ValueError, match="ONE object"):
        _adapter().from_cdm([event])
    stripped = entity.model_copy(update={
        "attributes": {k: v for k, v in entity.attributes.items() if k != "utc_second_raw"}})
    message = _parse_all(_adapter().from_cdm([stripped, event]))[0]["message"]
    assert message["utc_second"] == event.observed_at.second == 20


def test_the_canonical_value_wins_over_the_parked_one():
    """Egress must be a translation and not a replay: an edited position has to reach the wire."""
    entity, event = _translate("class_a_underway_gulf_of_riga.nmea")
    moved = entity.model_copy(update={
        "position": entity.position.model_copy(update={"lat": 57.1234})})
    message = _parse_all(_adapter().from_cdm([moved, event]))[0]["message"]
    assert message["lat"] == 57.1234


# --------------------------------------------------------------- round trips

#: Source paths that legitimately do NOT survive a re-emission, with the reason. Distinct from
#: TRANSFORMS, which is about the ingest translation: the TAG block IS carried into the CDM
#: (Event.payload.received_at_unix), and what it does not survive is being retransmitted — it
#: is the receiver's annotation, added by the delivery path, and this adapter emitting one
#: would be inventing a receipt time for a message nobody has received yet.
NOT_RETRANSMITTED = {
    "sentences[0].tag": "the NMEA TAG block is the receiver's own annotation, not part of the "
                        "AIS message; a re-emission is a new transmission and stamping it "
                        "with the original receipt time would misstate when it was received",
}


@pytest.mark.parametrize("path", NMEA_FIXTURES, ids=lambda p: p.name)
def test_the_ingest_round_trip_is_byte_exact(path):
    """The strongest claim available: sentences in, the same sentences out.

    Achievable because every bit is decoded, including the spares and the radio state, and
    because the parked source fields are read back on the way out. It is asserted rather than
    hoped for, and it subsumes any value-presence check — but the value-presence check below
    runs anyway, because it is the one that keeps working when a future message type cannot be
    re-encoded exactly.
    """
    emitted = _adapter().from_cdm(_adapter().to_cdm(path.read_bytes()))
    assert emitted == _strip_tag_blocks(path.read_bytes())


@pytest.mark.parametrize("path", NMEA_FIXTURES, ids=lambda p: p.name)
def test_the_ingest_round_trip_loses_no_source_value(path):
    """AIS -> CDM -> AIS, measured the way the harness would if it could parse sentences.

    Over the DECODED fields on both sides, not the armoured strings: an armoured payload is
    one leaf to `lossless`, so comparing those would test whether two strings match and prove
    nothing about the 168 bits inside.
    """
    original = ais._parse_nmea(path.read_bytes())
    adapter = _adapter()
    emitted = ais._parse_nmea(adapter.from_cdm(adapter.to_cdm(path.read_bytes())))

    missing = lossless.unrepresented(original, [emitted],
                                     {**AisAdapter.TRANSFORMS, **NOT_RETRANSMITTED})
    assert not missing, "\n".join(
        f"{p} = {v!r} was in the AIS source and is absent from what from_cdm() emitted"
        for p, v in sorted(missing.items()))


#: CDM facts with no AIS field to put them in, excluded from the egress comparison BY NAME so
#: that adding a field to a model cannot silently join the list.
#:
#: This list is long, and its length is the finding rather than a shortcut. CoT's `<detail>` is
#: an open bag, so the TAK adapter can graft what it could not map onto an extension element.
#: **AIS has no extension point at all** — every bit of every message type is allocated, and a
#: bit this adapter invented would be read by a receiver as the field the standard says lives
#: there. So these do not reach the wire, and the honest thing is to name each one.
EGRESS_NO_AIS_FIELD = {
    "object_kind": "the CDM's own discriminator",
    "schema_version": "the CDM's own version; AIS messages are versioned by message type",
    "source": "our provenance. Deliberately not transmitted — source.synthetic in particular "
              "is ours to know and not a fact about the station",
    "integrity": "the signature block, which is designed and unpopulated",
    "source_ids": "the MMSI IS the AIS address and is asserted directly below; the IMO number "
                  "is asserted with it",
    "entity_id": "AIS identity is the MMSI. A CDM uuid has nowhere to go",
    "track_id": "same, and a track is not an object AIS models at all",
    "track_quality": "AIS states no track quality; the position-accuracy bit is a different "
                     "claim and is carried separately",
    "entity_type": "AIS states a message type and a ship type, not what the CDM decided",
    "affiliation": "AIS carries no identity field. Emitting one would be inventing a claim",
    "symbol": "there is no symbol field in any AIS message",
    "valid_from": "an AIS position report carries a second of the minute and no date",
    "valid_to": "AIS has no staleness field",
    "confidence": "AIS states no confidence",
    "observed_at": "a Track sample's instant: only its SECOND can be transmitted, and that "
                   "second is asserted directly in the per-sample test above",
    "position_source": "types 1/2/3/18 carry no EPFD field, so there is nowhere to put it",
    "alt_m": "AIS position reports carry no altitude",
    "accuracy_m": "AIS states a one-bit threshold, not a metre figure",
    "climb_mps": "no vertical rate in any AIS message",
    "speed_mps": "carried, as knots — the declared inverse of the ingest unit conversion",
}


def _prune(value, names):
    if isinstance(value, dict):
        return {k: _prune(v, names) for k, v in value.items() if k not in names}
    if isinstance(value, list):
        return [_prune(v, names) for v in value]
    return value


def test_every_egress_exclusion_names_a_field_that_is_actually_there():
    """An exclusion for a field nothing emits is an exemption with no subject.

    It would silence the round-trip check for a field that never existed, which is the one way
    this list can rot without anybody noticing.
    """
    present = set()
    for path in EGRESS_FIXTURES:
        for leaf in lossless.leaves(_object(path.name).model_dump(mode="json")):
            present |= {part.split("[")[0] for part in leaf.split(".")}
    unused = set(EGRESS_NO_AIS_FIELD) - present
    assert not unused, f"declared but never emitted by any egress fixture: {sorted(unused)}"


@pytest.mark.parametrize("path", EGRESS_FIXTURES, ids=lambda p: p.name)
def test_the_egress_round_trip_loses_no_object_value(path):
    """CDM -> AIS -> decoded fields, checked the same way as the ingest direction.

    Run with no TRANSFORMS exemptions at all — only the named EGRESS_NO_AIS_FIELD list — so a
    value the adapter could have carried and did not shows up here.
    """
    subject = _object(path.name)
    emitted = _parse_all(_adapter().from_cdm([subject]))
    carried = _prune(subject.model_dump(mode="json"), set(EGRESS_NO_AIS_FIELD))

    missing = lossless.unrepresented(carried, emitted)
    assert not missing, "\n".join(
        f"{p} = {v!r} was on the {subject.object_kind} and is absent from the emitted AIS"
        for p, v in sorted(missing.items()))


def test_the_mmsi_and_the_imo_number_reach_the_wire():
    """Asserted directly because the round trip excludes `source_ids` wholesale."""
    entity = _object("entity_static_voyage_no_position.json")
    message = _parse_all(_adapter().from_cdm([entity]))[0]["message"]
    assert message["mmsi"] == "299000654"
    assert message["imo_number"] == 9284702
    track = _object("track_patrol_three_samples.json")
    for parsed in _parse_all(_adapter().from_cdm([track])):
        assert parsed["message"]["mmsi"] == "299000123"


@pytest.mark.parametrize("fixture,dropped,expected_loss", [
    ("entity_static_voyage_no_position.json", "vessel_name", "attributes.vessel_name"),
    ("entity_static_voyage_no_position.json", "draught_m", "attributes.draught_m"),
    ("entity_static_voyage_no_position.json", "eta_hour", "attributes.eta.hour"),
    ("entity_static_voyage_no_position.json", "call_sign", "attributes.call_sign"),
    ("entity_fused_elsewhere.json", "true_heading_deg", "attributes.true_heading_deg"),
    ("track_patrol_three_samples.json", "lat", "samples[0].position.lat"),
])
def test_the_egress_round_trip_would_notice_each_kind_of_loss(fixture, dropped, expected_loss):
    """The check above is only worth running if it can fail — so make it fail, five ways.

    A round-trip test that passes because it compares nothing is the failure mode this guards
    against. Each field the emitter writes is removed from the DECODED form in turn, and the
    same assertion must report the corresponding CDM value as missing.
    """
    subject = _object(fixture)
    lossy = _parse_all(_adapter().from_cdm([subject]))
    del lossy[0]["message"][dropped]

    carried = _prune(subject.model_dump(mode="json"), set(EGRESS_NO_AIS_FIELD))
    missing = lossless.unrepresented(carried, lossy)
    assert expected_loss in missing, (
        f"removing {dropped!r} should have lost {expected_loss}; the check reported {missing}")


# ------------------------------------------------------------------- harness


def test_the_harness_passes_every_fixture_against_the_published_schemas():
    """The gate, run against `/schemas` rather than the models — that is what consumers read."""
    from synapse_cdm import harness

    report = harness.run(_adapter(), FIXTURES, schema_dir=SCHEMAS)
    assert report["failed"] == 0, harness.render_report(report)
    assert report["passed"] >= 16

    for result in report["results"]:
        checks = result["checks"]
        assert checks["translate"] == "PASS", result
        assert checks["schema"] == "PASS", result
        assert checks["provenance"] == "PASS", result
        assert checks["golden"] == "PASS", result
        # The lossless check runs on the parsed form and can only SKIP on the sentences,
        # because the harness has no leaf structure to harvest from bytes. Asserting the split
        # rather than accepting "not FAIL" is what stops a sentences-only fixture set from
        # quietly turning the never-drop check off for this adapter.
        expected = "SKIP" if result["fixture"].endswith(".nmea") else "PASS"
        assert checks["lossless"] == expected, result
        # roundtrip is SKIP for every fixture BY DESIGN: from_cdm returns NMEA, which the
        # harness cannot compare structurally. That is why this file carries the round trips.
        assert checks["roundtrip"] == "SKIP", result


def test_the_adapter_is_registered_and_declares_itself_bidirectional():
    from synapse_cdm.adapter import discover

    registry = discover()
    assert registry["ais"] is AisAdapter
    assert AisAdapter.direction == "bidirectional"
    assert AisAdapter.system == "AIS"


def test_every_declared_transform_names_a_path_the_adapter_consumes():
    """A TRANSFORMS entry for a path nothing reads is an exemption with no subject."""
    consumed = set(AisAdapter.CONSUMED)
    for path in AisAdapter.TRANSFORMS:
        assert path in consumed, (
            f"TRANSFORMS declares {path!r}, which is not in CONSUMED — either the adapter "
            "stopped reading it or the declaration is a leftover")


def test_every_consumed_path_is_actually_present_in_some_fixture():
    """A CONSUMED entry nothing sends over-prunes the residual for a field that never arrives.

    Harmless today and wrong the moment the path is real: `residual()` would drop it from the
    parked bag while nothing mapped it, which is a silent hole in the never-drop rule.
    """
    seen = set()
    for path in NMEA_FIXTURES:
        seen |= set(lossless.leaves(ais._parse_nmea(path.read_bytes())))
    unused = [c for c in AisAdapter.CONSUMED
              if not any(leaf == c or leaf.startswith(f"{c}.") for leaf in seen)]
    assert not unused, f"CONSUMED paths no fixture exercises: {unused}"
