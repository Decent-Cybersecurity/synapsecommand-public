"""One test per claim in the ADS-B adapter's docstring, plus the round trips the harness cannot do.

WHY THIS FILE CARRIES THE ROUND-TRIP CHECKS
-------------------------------------------
The harness's `roundtrip` column reports SKIP for an adapter that emits something it cannot
parse structurally, and says so out loud: `from_cdm()` here returns hex frames. The README's
instruction for that case is that the adapter ships its own round-trip test, so both directions
are exercised here.

AND WHY THE EGRESS ROUND TRIP RE-INGESTS RATHER THAN COMPARING VALUES
---------------------------------------------------------------------
The AIS suite could compare CDM values against decoded wire fields directly, because its parsed
form holds degrees and knots — the units the standard talks in. ADS-B does not work that way:
a position is a pair of CPR zone offsets, a ground speed is two signed knot components, an
altitude is a 25-foot step count. Almost every field is a TRANSFORM of its wire value, so a
value-presence comparison would degenerate into an exclusion list naming nearly everything,
which is an exemption with no subject.

So the egress round trip goes CDM -> frames -> CDM and compares the two objects, with the
tolerances the format's own quantisation imposes. That is a stronger claim than value presence
and it is the one an operator on the receiving end depends on. The exclusion list then names
only what ADS-B genuinely cannot carry, which is what makes it worth reading.

THE CODEC IS PINNED FOUR WAYS, NONE OF THEM AGAINST ITSELF
-----------------------------------------------------------
`encode()` and `decode()` are inverses by construction, so proving that says nothing about
whether either matches the standard. So: the CRC generator is rebuilt here from the standard's
own exponent list rather than trusted as a hex constant; the CRC is recomputed by an
independently written long division and by its defining linearity property, which is what pins
the bit order and the absence of an init vector; one published frame anchors the whole chain
externally; and a hand-assembled frame, laid out field by field from values written in this
file, must equal the shipped fixture byte for byte.
"""
import json
import pathlib
import uuid

import pytest

import synapse_cdm
from synapse_cdm import ids, lossless, times
from synapse_cdm.adapters import adsb
from synapse_cdm.adapters.adsb import AdsbAdapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import Entity, Event, Track

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "adsb"
GOLDEN = FIXTURES / "golden"
LOCAL = FIXTURES / "local"
EGRESS = FIXTURES / "egress"
SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "schemas"

FRAME_FIXTURES = sorted(FIXTURES.glob("*.adsb"))
EGRESS_FIXTURES = sorted(EGRESS.glob("*.json"))

#: The receiver the `local/` goldens were decoded against — Riga, and the same value the
#: fixtures README states. A CPR local decode is measured FROM this point.
REFERENCE = (56.9236, 23.9711)

#: The ICAO allocation table's lowest state block. Every fixture address must be below it; see
#: the fixtures README for what that claim rests on and what would invalidate it.
LOWEST_ALLOCATED_BLOCK = 0x004000


def _adapter(reference=None) -> AdsbAdapter:
    return AdsbAdapter(clock=times.frozen_clock(), reference_position=reference)


def _translate(name: str, reference=None) -> tuple[Entity, Event]:
    entity, event = _adapter(reference).to_cdm((FIXTURES / name).read_bytes())
    return entity, event


def _object(name: str):
    raw = json.loads((EGRESS / name).read_text())
    return (Track if raw["object_kind"] == "track" else Entity).model_validate(raw)


def _parse_all(emitted: bytes) -> list[dict]:
    """Every frame in an emitted burst, separately.

    `_parse_frames` translates ONE frame per payload by design — a refusal that also closes the
    door on global CPR pairing — and an Entity holding both a position and a velocity, or a
    Track, legitimately emits several. Grouping them here rather than relaxing the adapter keeps
    that refusal intact.
    """
    return [adsb._parse_frames(line)
            for line in emitted.decode("ascii").split(adsb.FRAME_TERMINATOR) if line]


# --------------------------------------------------------------- the fixture set


def test_the_fixture_set_is_not_silently_empty():
    """A parametrised suite over a glob that matches nothing passes while testing nothing."""
    assert len(FRAME_FIXTURES) >= 14, f"expected >=14 ingest fixtures, found {len(FRAME_FIXTURES)}"
    assert len(EGRESS_FIXTURES) >= 3, f"expected >=3 egress fixtures, found {len(EGRESS_FIXTURES)}"
    covered = set()
    for path in FRAME_FIXTURES:
        message = adsb._parse_frames(path.read_bytes())["message"]
        covered.add(adsb.frame_kind(message["type_code"], message.get("subtype")))
    assert covered == set(adsb.ME_LAYOUTS), (
        f"the fixture set covers frame kinds {sorted(covered)} but the adapter claims "
        f"{sorted(adsb.ME_LAYOUTS)} — a frame kind in scope with no fixture is a claim with no "
        "evidence"
    )


def test_both_downlink_formats_have_a_fixture():
    """DF18 is not DF17 with a different number: it changes what a frame MEANS."""
    formats = {adsb._parse_frames(p.read_bytes())["message"]["df"] for p in FRAME_FIXTURES}
    assert formats == {adsb.DF_ADSB, adsb.DF_TISB}


@pytest.mark.parametrize("path", FRAME_FIXTURES, ids=lambda p: p.name)
def test_every_frame_fixture_ships_its_parsed_form_and_they_agree(path):
    """The `.parsed.json` twin must be EXACTLY what the parser produces from the `.adsb`.

    The twin exists because the harness cannot run its lossless check on a non-JSON fixture —
    it has no leaf structure to harvest — so an ADS-B-only fixture set would show a green run
    with the never-drop rule never actually checked. That only works if the two forms are the
    same payload, which is what this asserts: hand-maintained they would drift, and the drift
    would be invisible because both fixtures would still pass on their own.
    """
    twin = path.parent / f"{path.stem}.parsed.json"
    assert twin.is_file(), f"{path.name} has no .parsed.json twin — the lossless check would SKIP"
    assert json.loads(twin.read_text()) == adsb._parse_frames(path.read_bytes()), (
        f"{twin.name} is not what {path.name} parses to. Regenerate it from the frame rather "
        "than editing it by hand."
    )


@pytest.mark.parametrize("path", FRAME_FIXTURES, ids=lambda p: p.name)
def test_the_frame_and_parsed_paths_produce_identical_output(path):
    """The parse is the ONLY difference between the two forms, so the goldens must be equal.

    If the dict path ever produced something the frame path did not, one of the two golden files
    would be a recorded lie about the adapter — and each would still pass its own golden check.
    """
    from_frame = json.loads((GOLDEN / f"{path.stem}.cdm.json").read_text())
    from_dict = json.loads((GOLDEN / f"{path.stem}.parsed.cdm.json").read_text())
    assert from_frame == from_dict


@pytest.mark.parametrize("path", FRAME_FIXTURES, ids=lambda p: p.name)
def test_no_fixture_carries_an_allocated_icao_address(path):
    """Synthetic only. Every address is below the allocation table's lowest state block.

    Asserted here rather than left to the README so the assumption is discoverable from a
    failure: if ICAO ever allocates below 0x004000, this test is what says the fixtures must
    move.
    """
    address = adsb._parse_frames(path.read_bytes())["message"]["icao"]
    assert int(address, 16) < LOWEST_ALLOCATED_BLOCK, (
        f"{path.name} carries ICAO address {address}, which is at or above "
        f"{LOWEST_ALLOCATED_BLOCK:06X} — the lowest block the allocation table assigns to a "
        "state. Fixtures must use an address below it; see the fixtures README"
    )
    assert address.startswith("0029"), (
        f"{path.name} carries {address}; the fixture block is 0029xx, which echoes the AIS "
        "fixtures' MID 299 so a reader who has met one set recognises the other"
    )


# ------------------------------------------------------------------- the codec


def test_the_crc_generator_is_the_standards_polynomial_rebuilt_from_its_exponents():
    """Pinned from the standard's own coefficient list, not trusted as a magic hex constant.

    The Mode S generator is x^24 + x^23 + x^22 + x^21 + x^20 + x^19 + x^18 + x^17 + x^16 +
    x^15 + x^14 + x^13 + x^12 + x^10 + x^3 + 1. Rebuilding it here means a typo in the constant
    fails the build rather than silently rejecting every real frame.
    """
    exponents = (24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 10, 3, 0)
    assert adsb.CRC_GENERATOR == sum(1 << e for e in exponents)
    assert adsb.CRC_GENERATOR == 0x1FFF409
    assert adsb.CRC_GENERATOR >> 24 == 1, "a 24-bit CRC needs a 25-bit generator"


def test_the_crc_matches_an_independently_written_long_division():
    """A second implementation, written differently, is what pins the BIT ORDER.

    The module divides in place over an integer; this shifts a remainder register through the
    message one bit at a time. An MSB-first convention in one and LSB-first in the other would
    disagree on the first frame, which no amount of self-consistency would reveal.
    """
    def reference_crc(bits: str) -> int:
        remainder = 0
        for bit in bits + "0" * 24:
            remainder = (remainder << 1) | int(bit)
            if remainder >> 24 & 1:
                remainder ^= adsb.CRC_GENERATOR
        return remainder & 0xFFFFFF

    for path in FRAME_FIXTURES:
        bits = adsb._bits_of_hex(adsb._parse_frames(path.read_bytes())["frame"]["hex"])
        assert adsb.crc(bits[:88]) == reference_crc(bits[:88]), path.name


def test_the_crc_is_linear_and_carries_no_init_vector():
    """The defining property of a plain CRC, and the likeliest way to get one wrong.

    Mode S extended squitter parity is the remainder with no preset and no final inversion. If
    an init vector had crept in, crc(a XOR b) would no longer equal crc(a) XOR crc(b) — and the
    frames would still round-trip through this module perfectly.
    """
    a = "1" + "0" * 87
    b = "0" * 43 + "1" + "0" * 44
    combined = "".join(str(int(x) ^ int(y)) for x, y in zip(a, b))
    assert adsb.crc(combined) == adsb.crc(a) ^ adsb.crc(b)
    assert adsb.crc("0" * 88) == 0, "an all-zero message with an init vector would not be zero"


def test_a_published_frame_anchors_the_codec_outside_this_repository():
    """The one external anchor, and it is a codec TEST VECTOR rather than a fixture.

    Everything else here pins the codec against the standard's own definitions as written down
    in this file, which cannot catch a convention I got wrong in both places. This frame is a
    published worked example, so it anchors the chain outside the repository. It is deliberately
    an IDENTIFICATION frame: it carries no position, so nothing about any real aircraft's
    movements enters this repository, and it lives here rather than in `fixtures/` because it is
    not synthetic and must not be mistaken for a fixture.
    """
    published = "8D4840D6202CC371C32CE0576098"
    bits = adsb._bits_of_hex(published)
    assert adsb.crc(bits[:88]) == int(bits[88:], 2), "the published frame's own parity"
    message = adsb.decode(bits)
    assert message["df"] == 17
    assert message["icao"] == "4840D6"
    assert message["type_code"] == 4
    assert message["callsign"] == "KLM1023"
    assert adsb._hex_of_bits(adsb.encode(message)) == published


def test_the_callsign_alphabet_matches_the_published_mapping():
    """Three discontinuous runs: A-Z at 1, a space at 32, digits at 48. The gaps are the point.

    Getting a run boundary wrong shifts one character rather than failing, so a callsign comes
    out looking like a callsign and naming a different aircraft.
    """
    assert len(adsb.CALLSIGN_ALPHABET) == 64
    for value, expected in ((1, "A"), (26, "Z"), (32, " "), (48, "0"), (57, "9")):
        assert adsb.CALLSIGN_ALPHABET[value] == expected, value
    for value in (0, 27, 31, 33, 47, 58, 63):
        assert adsb.CALLSIGN_ALPHABET[value] == adsb.CALLSIGN_UNDEFINED, value
    round_tripped = adsb._callsign_of(adsb._callsign_bits("EXRCS01", 48))
    assert round_tripped == "EXRCS01", "trailing pad stripped, the name intact"


def test_every_me_layout_is_exactly_fifty_six_bits():
    """A layout that is one bit short shifts every field after it rather than failing."""
    for kind, layout in adsb.ME_LAYOUTS.items():
        assert sum(width for _, width, _ in layout) == 56, kind
    assert sum(width for _, width, _ in adsb._HEADER) == adsb.ME_START
    assert adsb.FRAME_BITS == adsb.ME_END + adsb.PARITY_BITS


def test_a_hand_assembled_frame_decodes_field_by_field_and_is_the_shipped_fixture():
    """The test that ties this layout to ADS-B rather than to itself.

    Every field is laid out here at its published width, from values written in this file, and
    the resulting frame must be character for character the frame in the shipped fixture. That
    pins the field ORDER, every field WIDTH, the 25-foot altitude arithmetic and the CPR
    encoding, none of which could be established by encoding and decoding with the same module.
    """
    bits = (f"{17:05b}{0:03b}{0x0029C1:024b}"      # DF17, CA 0, address
            f"{11:05b}{0:02b}{1:01b}"               # type code 11, surveillance status, NIC-B
            # Altitude: 31 000 ft is (31000 + 1000) / 25 = 1280 twenty-five-foot steps, and
            # 1280 is 10100000000 in eleven bits. The Q bit goes at index 7 of the twelve,
            # splitting those eleven: 1010000 | 1 | 0000.
            f"{0b101000010000:012b}"
            f"{0:01b}{0:01b}"                       # time sync, CPR parity even
            f"{78602:017b}{15626:017b}")            # CPR latitude, CPR longitude
    assert len(bits) == 88, "a frame is 88 bits before its 24-bit parity"
    bits += f"{adsb.crc(bits):024b}"

    decoded = adsb.decode(bits)
    assert decoded["icao"] == "0029C1"
    assert decoded["type_code"] == 11 and decoded["nic_supplement_b"] is True
    assert decoded["cpr_lat"] == 78602 and decoded["cpr_lon"] == 15626
    assert adsb.baro_altitude_feet(decoded["altitude_raw"])[0] == 31000

    shipped = adsb._parse_frames(
        (FIXTURES / "airborne_position_baro_gulf_of_riga.adsb").read_bytes())
    assert adsb._hex_of_bits(bits) == shipped["frame"]["hex"]


@pytest.mark.parametrize("path", FRAME_FIXTURES, ids=lambda p: p.name)
def test_encode_is_the_exact_inverse_of_decode(path):
    """Every bit is decoded — reserved fields included — so re-encoding is exact.

    Not a tidiness property. It is what makes the round-trip claim measurable instead of
    reviewable: if a field were skipped on the way in, re-encoding would have to invent it and
    the frame would differ.
    """
    parsed = adsb._parse_frames(path.read_bytes())
    assert adsb._hex_of_bits(adsb.encode(parsed["message"])) == parsed["frame"]["hex"]


def test_the_parity_is_recomputed_on_egress_and_never_copied():
    """A frame carrying a stale parity field is discarded by every receiver, silently."""
    parsed = adsb._parse_frames(
        (FIXTURES / "airborne_position_baro_gulf_of_riga.adsb").read_bytes())
    message = dict(parsed["message"])
    message["parity"] = 0
    assert adsb._hex_of_bits(adsb.encode(message)) == parsed["frame"]["hex"], (
        "encode() must ignore the parity it was handed and compute one")
    moved = dict(parsed["message"])
    moved["cpr_lat"] = moved["cpr_lat"] + 1
    assert adsb.encode(moved)[88:] != adsb.encode(parsed["message"])[88:], (
        "changing a payload bit must change the parity")


# ---------------------------------------------------------------------- CPR


def test_the_longitude_zone_count_matches_the_published_special_cases():
    """59 at the equator, 2 at exactly 87 degrees, 1 beyond it. The standard's own three."""
    assert adsb.cpr_longitude_zones(0.0) == 59
    assert adsb.cpr_longitude_zones(87.0) == 2
    assert adsb.cpr_longitude_zones(-87.0) == 2
    assert adsb.cpr_longitude_zones(89.5) == 1
    # Monotone non-increasing away from the equator: the grid coarsens towards the poles.
    counts = [adsb.cpr_longitude_zones(lat) for lat in range(0, 87)]
    assert counts == sorted(counts, reverse=True)


def test_the_local_decode_reproduces_the_published_worked_example():
    """Pinned against published NUMBERS, with no frame and no aircraft attached to them.

    The worked example's even-frame CPR values, decoded against its reference position, must
    give its stated coordinate. This is the arithmetic the whole position row set rests on.
    """
    latitude, longitude = adsb.cpr_decode_local(
        93000, 51372, 0, (52.258, 3.918), span=adsb.CPR_SPAN_AIRBORNE)
    assert (latitude, longitude) == (52.2572021484375, 3.91937255859375)


def test_the_encode_is_the_exact_inverse_of_the_local_decode():
    """What makes a byte-exact egress possible at all: encoding needs no reference position."""
    for cpr_format in (0, 1):
        for span in (adsb.CPR_SPAN_AIRBORNE, adsb.CPR_SPAN_SURFACE):
            values = (78602, 15626)
            decoded = adsb.cpr_decode_local(*values, cpr_format, REFERENCE, span=span)
            assert adsb.cpr_encode(*decoded, cpr_format, span=span) == values, (
                cpr_format, span)


def test_a_position_is_absent_without_a_reference_and_the_cpr_fields_are_kept():
    """The default is the safe one, and it does not cost the data."""
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb")
    assert entity.position is None
    assert entity.attributes["cpr_lat"] == 78602
    assert entity.attributes["cpr_lon"] == 15626
    assert entity.attributes["cpr_format_text"] == "even"
    assert "no reference position is configured" in \
        entity.attributes["position_unavailable_reason"]
    assert "position_decode_basis" not in entity.attributes


def test_a_reference_position_decodes_the_fix_and_records_what_it_decoded_against():
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb", REFERENCE)
    assert entity.position is not None
    assert round(entity.position.lat, 4) == 57.5981
    assert round(entity.position.lon, 4) == 23.8412
    assert entity.attributes["position_reference"] == list(REFERENCE)
    assert "180 NM" in entity.attributes["position_decode_basis"]
    assert "position_unavailable_reason" not in entity.attributes


def test_a_surface_frame_states_the_tighter_range_its_smaller_zones_buy():
    entity, _ = _translate("surface_position_riga_taxiway.adsb", REFERENCE)
    assert "45 NM" in entity.attributes["position_decode_basis"]
    assert round(entity.position.lat, 4) == 56.9243


def test_global_even_odd_pairing_is_not_implemented_and_the_pair_is_refused():
    """The type 24 argument applied consistently: the join is fusion, so the framing refuses it.

    Two frames of opposite CPR parity in one payload are precisely what a global decode needs,
    so accepting them would smuggle fusion in through the feed reader's job.
    """
    even = (FIXTURES / "airborne_position_baro_gulf_of_riga.adsb").read_bytes()
    odd = (FIXTURES / "airborne_position_gnss_height_odd.adsb").read_bytes()
    with pytest.raises(ValueError, match="exactly one frame per payload"):
        _adapter().to_cdm(even + odd)
    assert not any(name.startswith("cpr_decode_global") for name in dir(adsb)), (
        "a global decoder appearing here means the CPR decision changed; FORMAT_COVERAGE.md "
        "and MIGRATIONS.md have to change with it"
    )


def test_a_reference_position_that_is_not_a_coordinate_is_refused_at_construction():
    """A bad reference silently moves every aircraft it decodes rather than failing."""
    with pytest.raises(ValueError, match="not a coordinate"):
        AdsbAdapter(clock=times.frozen_clock(), reference_position=(95.0, 24.0))


@pytest.mark.parametrize("path", FRAME_FIXTURES, ids=lambda p: p.name)
def test_the_reference_changes_positions_and_nothing_else(path):
    """A local golden for the frames a reference changes; byte-identical output for the rest.

    Both halves matter. The first is the referenced path's own golden gate, which the harness
    cannot provide because it constructs the adapter itself. The second is the claim that a
    reference position is not a general-purpose switch: it decodes a coordinate and touches
    nothing else in the object.
    """
    plain = [o.model_dump(mode="json") for o in _adapter().to_cdm(path.read_bytes())]
    local = [o.model_dump(mode="json")
             for o in _adapter(REFERENCE).to_cdm(path.read_bytes())]
    golden = LOCAL / f"{path.stem}.cdm.json"
    if golden.exists():
        assert local == json.loads(golden.read_text())
        assert local != plain, (
            f"{golden.name} exists but the reference changed nothing — delete the golden or "
            "fix the fixture")
    else:
        assert local == plain, (
            f"{path.name} changed under a reference position but has no local/ golden. Either "
            "it states a position and needs one, or the reference is reaching a field it "
            "should not")


def test_the_local_goldens_are_exactly_the_position_bearing_fixtures():
    """A missing golden would make the branch above silently assert the weaker half."""
    with_position = {p.stem for p in FRAME_FIXTURES
                     if _adapter(REFERENCE).to_cdm(p.read_bytes())[0].position is not None}
    assert {p.name.removesuffix(".cdm.json") for p in LOCAL.glob("*.cdm.json")} == with_position


# ------------------------------------------------------------- ingest: identity


def test_the_address_becomes_the_source_id_under_icao24_and_not_under_adsb():
    """The address is a registry identifier, so it is filed as one.

    That is what lets `ids.derive` agree with a future Mode S or ASTERIX adapter without any
    coordination — the property derived identity exists for.
    """
    entity, event = _translate("airborne_position_baro_gulf_of_riga.adsb")
    assert [(s.system, s.external_id) for s in entity.source_ids] == [("ICAO24", "0029C1")]
    assert [(s.system, s.external_id) for s in event.source_ids] == [("ICAO24", "0029C1")]
    assert entity.source.system == "ADSB", "the link this copy arrived over"


def test_the_entity_id_is_derived_from_the_address_and_therefore_stable():
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb")
    assert entity.entity_id == uuid.uuid5(ids.NAMESPACE, "entity|ICAO24|0029C1")
    assert entity.attributes["entity_id_basis"] == "frame address"


def test_two_frames_from_one_airframe_share_an_entity_id_and_not_an_event_id():
    """A position frame and a velocity frame from one aircraft are one object and two events."""
    position_entity, position_event = _translate("airborne_position_baro_gulf_of_riga.adsb")
    track = _object("track_air_patrol_three_samples.json")
    assert position_entity.entity_id == track.entity_id, (
        "the egress track fixture is keyed on the same address, so the ids must agree")
    velocity_entity, velocity_event = _translate("airborne_velocity_ground_speed.adsb")
    assert velocity_entity.entity_id != position_entity.entity_id, "different addresses"
    assert velocity_event.event_id != position_event.event_id


def test_an_anonymous_address_is_not_filed_as_an_icao_allocation():
    """A self-assigned number colliding with a real airframe must not become a fused track."""
    anonymous, _ = _translate("nonicao_anonymous_address.adsb")
    assert [(s.system, s.external_id) for s in anonymous.source_ids] == \
        [("ADSB_NONICAO", "0029B2")]
    assert anonymous.entity_id != uuid.uuid5(ids.NAMESPACE, "entity|ICAO24|0029B2"), (
        "the two id spaces must not collide, or fusion joins an anonymous device to an airframe")
    assert "anonymous or self-assigned" in anonymous.attributes["adsb_control_field_text"]


def test_a_squawk_is_parked_and_is_not_a_source_id():
    """ATC assigns it per flight, so a source id keyed on it would split one aircraft in two."""
    entity, _ = _translate("aircraft_status_unlawful_interference.adsb")
    assert entity.attributes["mode_a_code"] == "7500"
    assert entity.attributes["mode_a_code_raw"] == adsb.mode_a_raw("7500")
    assert all(s.system in ("ICAO24", "ADSB_NONICAO") for s in entity.source_ids)
    assert all(s.external_id != "7500" for s in entity.source_ids)


def test_the_mode_a_digits_come_from_three_non_adjacent_bits_each():
    """7500 and 7600 differ by one digit, so an off-by-one here is a plausible wrong squawk."""
    for code in ("7500", "7600", "7700", "1000", "0000", "7777"):
        assert adsb.mode_a_code(adsb.mode_a_raw(code)) == code, code
    assert adsb.mode_a_raw("7500") != adsb.mode_a_raw("7600")
    with pytest.raises(ValueError, match="four octal digits"):
        adsb.mode_a_raw("7800")
    # The X bit sits between the digits and belongs to none of them. Setting it would shift
    # nothing and mean nothing, but a receiver reads the field as thirteen bits.
    for code in ("7500", "0000", "7777"):
        assert f"{adsb.mode_a_raw(code):013b}"[adsb.MODE_A_SPARE_BIT] == "0", code
    assert adsb.MODE_A_SPARE_BIT not in {
        index for indices in adsb.MODE_A_BITS.values() for index in indices}


@pytest.mark.parametrize("fixture,expected", [
    ("airborne_position_baro_gulf_of_riga.adsb", EntityType.PLATFORM),
    ("surface_position_riga_taxiway.adsb", EntityType.PLATFORM),
    ("identification_light_aircraft.adsb", EntityType.PLATFORM),
    ("identification_point_obstacle.adsb", EntityType.FACILITY),
    ("tisb_fine_format_relayed_track.adsb", EntityType.PLATFORM),
])
def test_only_an_obstacle_category_refines_the_entity_type(fixture, expected):
    entity, _ = _translate(fixture)
    assert entity.entity_type == expected


def test_an_aircraft_category_does_not_become_an_entity_type():
    """A light aircraft and a rotorcraft are both PLATFORM. The wording is parked instead."""
    light, _ = _translate("identification_light_aircraft.adsb")
    assert light.entity_type == EntityType.PLATFORM
    assert light.attributes["emitter_category_text"] == "light (below 15 500 lb)"
    assert light.attributes["emitter_category_set"] == "A"
    obstacle, _ = _translate("identification_point_obstacle.adsb")
    assert obstacle.attributes["emitter_category_set"] == "C", (
        "the type code selects the category SET, so neither number means anything alone")
    assert obstacle.attributes["emitter_category_text"].startswith("point obstacle")


def test_the_affiliation_is_unknown_because_nothing_in_the_format_is_authenticated():
    """A stronger reason than AIS's silence, and the basis string says which one applies."""
    for path in FRAME_FIXTURES:
        entity, _ = _adapter().to_cdm(path.read_bytes())
        assert entity.affiliation == Affiliation.UNKNOWN, path.name
        assert "unauthenticated" in entity.attributes["affiliation_basis"], path.name
        assert "spoofable" in entity.attributes["affiliation_basis"], path.name


def test_a_callsign_is_not_read_as_an_identification():
    entity, _ = _translate("identification_light_aircraft.adsb")
    assert entity.attributes["callsign"] == "EXRCS01"
    assert entity.affiliation == Affiliation.UNKNOWN


def test_a_malformed_callsign_is_visible_rather_than_cleaned():
    """A `#` means a six-bit value the alphabet does not define, so the string is not a name."""
    parsed = adsb._parse_frames(
        (FIXTURES / "identification_light_aircraft.adsb").read_bytes())
    parsed["message"]["callsign"] = "EX#RCS1"
    entity, _ = _adapter().to_cdm(parsed)
    assert "callsign" not in entity.attributes, "a name with an undefined character is not a name"
    assert entity.attributes["callsign_raw"] == "EX#RCS1"


def test_the_symbol_is_derived_and_marks_the_object_as_exercise_data():
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb")
    assert entity.symbol is not None and len(entity.symbol) == 20
    assert entity.symbol[2] == "2", "synthetic data must carry the simulation context digit"
    assert entity.symbol[3] == "1", "UNKNOWN is 2525D standard identity 1"
    live, _ = AdsbAdapter(clock=times.frozen_clock(), synthetic=False).to_cdm(
        (FIXTURES / "airborne_position_baro_gulf_of_riga.adsb").read_bytes())
    assert live.symbol[2] == "0"


def test_the_country_of_registration_is_not_looked_up():
    """A state of registry is not an affiliation, and the lookup would be enrichment."""
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb")
    assert entity.attributes["icao_address"] == "0029C1"
    rendered = json.dumps(entity.attributes).lower()
    assert "country" not in rendered and "registration" not in rendered


# ------------------------------------------------------------- ingest: altitude


def test_a_barometric_altitude_does_not_become_a_height_above_the_ellipsoid():
    """gap 9. `alt_m` means HAE, and a pressure altitude is a different measurement."""
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb", REFERENCE)
    assert entity.position is not None
    assert entity.position.alt_m is None
    assert entity.attributes["baro_altitude_ft"] == 31000
    assert "gnss_altitude_m" not in entity.attributes
    assert entity.attributes["altitude_type"].startswith("barometric")


def test_a_gnss_height_is_the_one_altitude_that_maps():
    """And it needs no conversion at all: the field is already metres above the ellipsoid."""
    entity, _ = _translate("airborne_position_gnss_height_odd.adsb", REFERENCE)
    assert entity.position.alt_m == 3200.0
    assert entity.attributes["gnss_altitude_m"] == 3200
    assert "baro_altitude_ft" not in entity.attributes
    assert entity.attributes["altitude_type"].startswith("GNSS height")


def test_the_gnss_height_field_is_plain_metres_and_not_the_barometric_encoding():
    """Pinned against mode-s.org's airborne position chapter: "the decimal value of all 12
    bits translates into the height of aircraft in meters".

    This is the assertion that would have caught the defect it was written for. An earlier
    version applied the barometric arithmetic to this field, and because the fixture was encoded
    the same wrong way the round trip stayed byte-exact and every other check passed — the frame
    simply did not mean what the adapter said. Reading a real frame carrying 1039 in this field
    would have reported 24 975 ft instead of 1039 m: a 7.3x overstatement, and a plausible one.
    """
    for raw in (1, 500, 1039, 3200, adsb.GNSS_HEIGHT_MAX_M):
        assert adsb.gnss_height_m(raw)[0] == raw, raw
        assert adsb.gnss_height_raw(raw) == raw, raw
    # The two encodings must not agree anywhere it matters, or this test proves nothing.
    assert adsb.baro_altitude_feet(3200)[0] != 3200
    # Twelve bits of metres saturate at 4095 m — about 13 435 ft — which is the property that
    # makes type codes 20-22 unusable at cruise and made the wrong reading look plausible.
    assert adsb.GNSS_HEIGHT_MAX_M == 4095
    assert round(adsb.GNSS_HEIGHT_MAX_M / adsb.FOOT_M) == 13435


def test_a_gnss_height_above_the_field_range_is_an_encode_error_and_never_saturated():
    """A cruise level clipped to 4095 m reads as a real low altitude to every consumer."""
    for metres in (4096, 7620, 12000):
        with pytest.raises(ValueError, match="does not fit the ADS-B twelve-bit field"):
            adsb.gnss_height_raw(metres)
    with pytest.raises(ValueError, match="does not fit"):
        adsb.gnss_height_raw(-1)
    entity, _ = _translate("airborne_position_gnss_height_odd.adsb", REFERENCE)
    too_high = entity.model_copy(update={
        "position": entity.position.model_copy(update={"alt_m": 10000.0})})
    with pytest.raises(ValueError, match="does not fit"):
        _adapter(REFERENCE).from_cdm([too_high])


def test_a_gnss_height_survives_a_frame_whose_position_could_not_be_decoded():
    """The defect the byte-exact round trip found: `Position` requires a coordinate.

    An altitude with no horizontal fix has no canonical home at all, so parking it beside
    `Position.alt_m` is what keeps it. See the note under gap 9.
    """
    entity, _ = _translate("airborne_position_gnss_height_odd.adsb")
    assert entity.position is None
    assert entity.attributes["gnss_altitude_m"] == 3200


def test_a_gillham_altitude_is_declined_and_its_bits_are_kept():
    """Declining to decode and losing the data are different outcomes."""
    entity, _ = _translate("airborne_position_gillham_above_50175.adsb", REFERENCE)
    assert entity.position is not None
    assert entity.position.alt_m is None
    assert "baro_altitude_ft" not in entity.attributes
    assert entity.attributes["unresolved_raw"]["altitude_raw"] == 0b101101000110
    assert "Gillham" in entity.attributes["altitude_basis"]


def test_the_barometric_altitude_arithmetic_matches_the_published_encoding():
    """25-foot steps offset by 1000, so the field can express below the datum."""
    assert adsb.baro_altitude_feet(0)[0] is None, \
        "an all-zero field is not an altitude of -1000 ft"
    for feet in (-1000, -975, 0, 25, 7000, 31000, 38000, 50175):
        assert adsb.baro_altitude_feet(adsb.baro_altitude_raw(feet))[0] == feet, feet
    with pytest.raises(ValueError, match="Gillham"):
        adsb.baro_altitude_raw(60000)


def test_an_all_zero_gnss_height_is_read_as_absent_and_says_that_was_a_decision():
    """The reference documents this sentinel for the BAROMETRIC field and is silent for this one.

    So the reading is the adapter's, taken in the safe direction, and it has to say so — 0 m
    would place an airborne aircraft exactly on the ellipsoid, and an absent altitude is
    recoverable where a false one is not.
    """
    metres, basis = adsb.gnss_height_m(0)
    assert metres is None
    assert "the adapter's decision" in basis and "safe direction" in basis


def test_an_absent_altitude_is_not_an_altitude_of_zero():
    parsed = adsb._parse_frames(
        (FIXTURES / "airborne_position_gnss_height_odd.adsb").read_bytes())
    parsed["message"]["altitude_raw"] = 0
    entity, _ = _adapter(REFERENCE).to_cdm(parsed)
    assert entity.position.alt_m is None
    assert "gnss_altitude_m" not in entity.attributes
    assert "altitude_raw" in entity.attributes["unavailable_fields"]


# ------------------------------------------------------------- ingest: sentinels


@pytest.mark.parametrize("field,sentinel", list(adsb.UNAVAILABLE_WHEN))
def test_every_declared_sentinel_is_zero_or_the_empty_string(field, sentinel):
    """The whole ADS-B family shares one shape, and a table nobody checks drifts.

    Unlike AIS, where each sentinel was a different implausible number, here every one is zero
    in a field that is otherwise offset by one — which is why forgetting the offset is the
    characteristic bug and why the offset lives in one function.
    """
    assert sentinel in (0, ""), (field, sentinel)


def test_the_offset_by_one_family_never_reports_a_value_one_too_high():
    assert adsb._offset_by_one(0) is None
    assert adsb._offset_by_one(1) == 0.0, "wire value 1 is a measurement of zero"
    assert adsb._offset_by_one(160) == 159.0
    assert adsb._offset_by_one(160, multiplier=4) == 636.0
    assert adsb._offset_by_one(14, step=64) == 832.0


def test_the_velocity_sentinels_become_absent_motion_and_never_a_zero_vector():
    """The fixture carrying all of them at once."""
    entity, _ = _translate("airborne_velocity_all_unavailable.adsb")
    assert entity.kinematics is None, "four zero sentinels must not become a stationary aircraft"
    assert set(entity.attributes["unavailable_fields"]) >= {
        "ew_velocity_raw", "ns_velocity_raw", "vertical_rate_raw", "gnss_baro_diff_raw"}
    assert "unresolved_raw" not in entity.attributes, (
        "nothing was said, so there is nothing unresolved to keep")


def test_a_missing_velocity_component_yields_no_speed_and_no_course():
    """A speed from one axis understates; a course from one axis is exactly 000 or 090."""
    parsed = adsb._parse_frames(
        (FIXTURES / "airborne_velocity_ground_speed.adsb").read_bytes())
    parsed["message"]["ns_velocity_raw"] = 0
    entity, _ = _adapter().to_cdm(parsed)
    assert entity.kinematics.speed_mps is None and entity.kinematics.course_deg is None
    assert entity.kinematics.climb_mps is not None, "the vertical rate is a separate field"
    # And the axis that WAS stated is not the price of that refusal.
    assert entity.attributes["unresolved_raw"]["ew_velocity_raw"] == 214


def test_a_cleared_validity_bit_is_a_different_absence_from_a_zero_sentinel():
    """Two mechanisms, kept apart, and both feed unavailable_fields."""
    entity, _ = _translate("surface_position_stopped_no_track.adsb", REFERENCE)
    assert entity.kinematics.course_deg is None
    assert entity.attributes["ground_track_valid"] is False
    assert "ground_track_raw" in entity.attributes["unavailable_fields"]
    # The real-looking number the aircraft says not to read is neither a measurement nor
    # something to throw away.
    assert entity.attributes["unresolved_raw"]["ground_track_raw"] == 64


def test_a_stopped_aircraft_is_a_measurement_and_not_an_absence():
    """The mirror of the sentinel rule, and why it cannot be done by truthiness."""
    entity, _ = _translate("surface_position_stopped_no_track.adsb", REFERENCE)
    assert entity.kinematics.speed_mps == 0.0
    assert entity.attributes["movement_text"] == "stopped (below 0.125 kt)"
    assert "movement_raw" not in entity.attributes["unavailable_fields"]


def test_the_movement_floor_is_kept_and_recorded_as_a_floor():
    """175 kt or above is a floor, not a speed — AIS's 102.2 knots, in another format."""
    assert adsb.movement_knots(adsb.MOVEMENT_NOT_AVAILABLE)[0] is None
    assert adsb.movement_knots(adsb.MOVEMENT_AT_OR_ABOVE_MAXIMUM) == (175.0, "175 kt or above", True)
    parsed = adsb._parse_frames((FIXTURES / "surface_position_riga_taxiway.adsb").read_bytes())
    parsed["message"]["movement_raw"] = adsb.MOVEMENT_AT_OR_ABOVE_MAXIMUM
    entity, _ = _adapter(REFERENCE).to_cdm(parsed)
    assert entity.attributes["movement_at_or_above_maximum"] is True
    assert entity.kinematics.speed_mps == round(175.0 * adsb.KNOT_MPS, 4)


def test_the_movement_bucket_boundaries_are_continuous():
    """A gap or an overlap between two buckets is a speed that is wrong by a whole step."""
    previous = 0.0
    for raw in range(2, adsb.MOVEMENT_AT_OR_ABOVE_MAXIMUM):
        knots = adsb.movement_knots(raw)[0]
        assert knots is not None and knots > previous, raw
        previous = knots
    for raw in adsb.MOVEMENT_RESERVED:
        assert adsb.movement_knots(raw)[0] is None, raw
    assert adsb.movement_raw(15.0) == 39 and adsb.movement_knots(39)[0] == 15.0


def test_a_reserved_movement_value_keeps_its_bits():
    parsed = adsb._parse_frames((FIXTURES / "surface_position_riga_taxiway.adsb").read_bytes())
    parsed["message"]["movement_raw"] = 126
    entity, _ = _adapter(REFERENCE).to_cdm(parsed)
    assert entity.kinematics.speed_mps is None
    assert entity.attributes["unresolved_raw"]["movement_raw"] == 126


def test_a_frame_with_no_position_information_does_not_land_on_the_equator():
    """Zero CPR values are the absence of a position, not a position at 0/0.

    The mirror of the rule that a real 0/0 coordinate must survive: checked by TYPE CODE and
    not by falsiness, because falsiness cannot tell the two apart.
    """
    for reference in (None, REFERENCE, (0.0, 0.0)):
        entity, _ = _translate("airborne_position_no_position_information.adsb", reference)
        assert entity.position is None, reference
        assert set(entity.attributes["unavailable_fields"]) >= {"cpr_lat", "cpr_lon"}
        assert "NO POSITION INFORMATION" in entity.attributes["position_unavailable_reason"]
    # And the altitude it DOES state still arrives.
    entity, _ = _translate("airborne_position_no_position_information.adsb", REFERENCE)
    assert entity.attributes["baro_altitude_ft"] == 7000


def test_the_source_says_which_fields_it_could_not_supply():
    populated, _ = _translate("airborne_velocity_ground_speed.adsb")
    assert populated.attributes["unavailable_fields"] == []
    blind, _ = _translate("airborne_velocity_all_unavailable.adsb")
    assert blind.attributes["unavailable_fields"]


# ------------------------------------------------------------- ingest: velocity


def test_the_ground_velocity_becomes_one_speed_and_one_course():
    entity, _ = _translate("airborne_velocity_ground_speed.adsb")
    assert entity.kinematics.speed_mps == round((213.0 ** 2 + 158.0 ** 2) ** 0.5
                                                * adsb.KNOT_MPS, 4)
    assert entity.kinematics.course_deg == 126.5674
    assert entity.kinematics.climb_mps == round(-1216 * adsb.FEET_PER_MINUTE_MPS, 4)
    assert entity.attributes["velocity_subtype_text"] == "velocity over ground, subsonic"


def test_an_airspeed_is_not_written_into_the_ground_speed_field():
    """gap 10. The difference between airspeed and ground speed is the wind."""
    entity, _ = _translate("airborne_velocity_airspeed_and_heading.adsb")
    assert entity.kinematics.speed_mps is None
    assert entity.kinematics.course_deg is None
    assert entity.attributes["airspeed_kt"] == 411.0
    assert entity.attributes["airspeed_type"] == "true airspeed"


def test_a_heading_is_parked_and_its_datum_is_in_a_different_frame():
    """gap 7, and what ADS-B adds to it: a heading with no stated datum is two measurements."""
    entity, _ = _translate("airborne_velocity_airspeed_and_heading.adsb")
    assert entity.attributes["heading_deg"] == round(816 * 360 / 1024, 4) == 286.875
    assert "heading_reference" not in entity.attributes, (
        "the HRD bit is in a type 31 frame, not this one — that is the cross-frame join gap 7 "
        "inherits, and inventing a datum here would be worse than leaving it absent")
    status, _ = _translate("operational_status_magnetic_heading.adsb")
    assert status.attributes["heading_reference"] == "magnetic north"
    assert status.attributes["horizontal_reference_direction"] == 1


def test_a_vertical_rate_of_zero_is_not_level_flight():
    parsed = adsb._parse_frames(
        (FIXTURES / "airborne_velocity_ground_speed.adsb").read_bytes())
    parsed["message"]["vertical_rate_raw"] = 0
    entity, _ = _adapter().to_cdm(parsed)
    assert entity.kinematics.climb_mps is None
    assert "vertical_rate_raw" in entity.attributes["unavailable_fields"]
    # 1 IS level flight: the wire value is offset by one, so 1 decodes to 0 ft/min.
    parsed["message"]["vertical_rate_raw"] = 1
    level, _ = _adapter().to_cdm(parsed)
    assert level.kinematics.climb_mps == 0.0


def test_the_gnss_barometric_difference_is_kept_as_the_bridge_between_the_two_altitudes():
    entity, _ = _translate("airborne_velocity_ground_speed.adsb")
    assert entity.attributes["gnss_baro_difference_ft"] == 575
    negative, _ = _translate("airborne_velocity_airspeed_and_heading.adsb")
    assert negative.attributes["gnss_baro_difference_ft"] == -125


def test_the_vertical_rate_source_is_recorded_because_only_one_survives_jamming():
    geometric, _ = _translate("airborne_velocity_ground_speed.adsb")
    assert geometric.attributes["vertical_rate_source"] == "GNSS (geometric)"
    barometric, _ = _translate("airborne_velocity_airspeed_and_heading.adsb")
    assert barometric.attributes["vertical_rate_source"] == "barometric"


def test_a_surface_ground_track_is_a_course_over_the_ground():
    entity, _ = _translate("surface_position_riga_taxiway.adsb", REFERENCE)
    assert entity.kinematics.course_deg == 118.125
    assert entity.kinematics.speed_mps == round(15.0 * adsb.KNOT_MPS, 4)


# ------------------------------------------------------- ingest: position source


@pytest.mark.parametrize("fixture,expected", [
    ("airborne_position_baro_gulf_of_riga.adsb", PositionSource.GNSS),
    ("surface_position_riga_taxiway.adsb", PositionSource.GNSS),
    ("nonicao_anonymous_address.adsb", PositionSource.GNSS),
    ("tisb_fine_format_relayed_track.adsb", PositionSource.ESTIMATED),
])
def test_the_position_source_understates_a_relayed_surveillance_track(fixture, expected):
    entity, _ = _translate(fixture, REFERENCE)
    assert entity.position.position_source == expected
    assert entity.attributes["position_source_basis"]


def test_fine_format_tisb_is_not_reported_as_a_gnss_fix():
    """The dangerous direction: GNSS promises a fix that survives jamming."""
    entity, _ = _translate("tisb_fine_format_relayed_track.adsb", REFERENCE)
    assert entity.position.position_source == PositionSource.ESTIMATED
    assert "not the aircraft's own GNSS fix" in entity.attributes["position_source_basis"]
    for control in adsb.CF_TISB_SURVEILLANCE:
        assert adsb._position_source({"df": 18, "capability": control})[0] == \
            PositionSource.ESTIMATED


@pytest.mark.parametrize("control", adsb.CF_RELAY)
def test_a_rebroadcast_keeps_its_gnss_origin_and_records_the_relay(control):
    """ADS-R relays a genuine ADS-B message, so the original fix IS the aircraft's own.

    Built by hand rather than shipped as a fixture: the control field changes what a frame MEANS
    and nothing about how it decodes, so a seventeenth fixture would add a file and no coverage.
    The attribute is asserted here because FORMAT_COVERAGE.md has a row for it, and a row with no
    assertion behind it is the kind of claim this suite exists to stop.
    """
    source, basis = adsb._position_source({"df": 18, "capability": control})
    assert source == PositionSource.GNSS
    assert "rebroadcast" in basis

    parsed = adsb._parse_frames(
        (FIXTURES / "tisb_fine_format_relayed_track.adsb").read_bytes())
    parsed["message"]["capability"] = control
    entity, _ = _adapter(REFERENCE).to_cdm(parsed)
    assert entity.attributes["adsb_relay"] is True
    assert entity.position.position_source == PositionSource.GNSS
    # And it is absent rather than False on a frame that did not arrive by a relay.
    direct, _ = _translate("airborne_position_baro_gulf_of_riga.adsb", REFERENCE)
    assert "adsb_relay" not in direct.attributes


def test_the_position_accuracy_is_not_invented_from_the_type_code():
    """A containment radius is an integrity bound, not the 1-sigma metre figure that field holds."""
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb", REFERENCE)
    assert entity.position.accuracy_m is None
    status, _ = _translate("operational_status_magnetic_heading.adsb")
    assert status.attributes["source_extras"]["message"]["nac_position"] == 9, (
        "NACp is parked, in a different frame from the position it would qualify")


def test_a_frame_with_no_position_fields_states_no_position_source_at_all():
    """A basis string about a fix that does not exist reads as a fix that does."""
    entity, _ = _translate("identification_light_aircraft.adsb", REFERENCE)
    assert entity.position is None
    assert "position_source_basis" not in entity.attributes
    assert "carries no position fields" in entity.attributes["position_unavailable_reason"]


# ------------------------------------------------------------------ ingest: time


def test_the_format_states_no_time_and_the_basis_says_so():
    entity, event = _translate("airborne_position_baro_gulf_of_riga.adsb")
    assert times.render(event.observed_at) == times.render(times.FROZEN_NOW)
    assert event.observed_at == event.received_at
    assert "carries no time field at all" in event.payload["observed_at_basis"]
    assert entity.attributes["valid_from_basis"] == event.payload["observed_at_basis"]


def test_the_receiver_counter_is_parked_and_never_read_as_a_clock():
    """It is a free-running 12 MHz counter; read as an epoch it would date the frame to 1970.

    The exact mirror of the NMEA TAG block, which IS a wall clock and IS read as one.
    """
    entity, event = _translate("airborne_position_baro_gulf_of_riga.adsb")
    assert entity.attributes["source_extras"]["frame"]["timestamp_raw"] == "1A2B3C4D5E6F"
    assert times.render(event.received_at) == times.render(times.FROZEN_NOW)
    assert "receiver counter" in event.payload["received_at_basis"]
    bare, bare_event = _translate("airborne_velocity_ground_speed.adsb")
    assert "timestamp_raw" not in bare.attributes["source_extras"]["frame"]
    assert times.render(bare_event.received_at) == times.render(times.FROZEN_NOW)


# ---------------------------------------------------------------- ingest: events


def test_the_only_things_that_raise_severity_are_the_formats_own_emergencies():
    alerted, alert_event = _translate("airborne_position_permanent_alert.adsb")
    assert alert_event.event_type == EventType.ALERT
    assert alert_event.severity == Severity.CRITICAL
    assert alerted.attributes["surveillance_status_text"].startswith("permanent alert")

    emergency, emergency_event = _translate("aircraft_status_unlawful_interference.adsb")
    assert emergency_event.event_type == EventType.ALERT
    assert emergency_event.severity == Severity.CRITICAL
    assert emergency.attributes["emergency_state_text"] == "unlawful interference"


@pytest.mark.parametrize("status", [2, 3])
def test_an_ident_change_or_an_spi_pulse_does_not_raise_severity(status):
    """Procedural conditions. Grading them would be the translator judging significance."""
    parsed = adsb._parse_frames(
        (FIXTURES / "airborne_position_baro_gulf_of_riga.adsb").read_bytes())
    parsed["message"]["surveillance_status"] = status
    _, event = _adapter().to_cdm(parsed)
    assert event.severity == Severity.INFO
    assert event.event_type == EventType.TRACK_UPDATE


def test_a_frame_carrying_neither_position_nor_motion_is_not_a_track_update():
    """It carries no position, and TRACK_UPDATE would claim one."""
    for fixture in ("identification_light_aircraft.adsb",
                    "operational_status_magnetic_heading.adsb"):
        entity, event = _translate(fixture, REFERENCE)
        assert event.event_type == EventType.STATUS_CHANGE, fixture
        assert entity.position is None, fixture


def test_the_event_points_at_the_entity_and_carries_both_timestamps():
    entity, event = _translate("airborne_position_gnss_height_odd.adsb")
    assert event.related_entities == [entity.entity_id]
    assert event.observed_at and event.received_at
    assert event.geometry is None, "the position belongs to the aircraft, not to the report"
    assert event.payload["frame_parity"] == \
        adsb._parse_frames(
            (FIXTURES / "airborne_position_gnss_height_odd.adsb").read_bytes())["message"]["parity"]


# ------------------------------------------------------------- ingest: refusals


def test_a_failed_crc_is_refused_rather_than_decoded():
    """A bit flip in the ME field moves an aircraft; it does not fail to parse."""
    original = (FIXTURES / "airborne_position_baro_gulf_of_riga.adsb").read_text()
    corrupted = original.replace("880029C159A1", "880029C159A2")
    assert corrupted != original
    with pytest.raises(ValueError, match="parity"):
        _adapter().to_cdm(corrupted.encode("ascii"))


def test_the_crc_gate_catches_a_single_bit_flip_anywhere_in_the_payload():
    bits = adsb._bits_of_hex(adsb._parse_frames(
        (FIXTURES / "airborne_position_baro_gulf_of_riga.adsb").read_bytes())["frame"]["hex"])
    for index in range(0, 88, 7):
        flipped = bits[:index] + ("1" if bits[index] == "0" else "0") + bits[index + 1:]
        assert adsb.crc(flipped[:88]) != int(flipped[88:], 2), index


def test_a_downlink_format_that_is_not_an_extended_squitter_is_refused():
    """The rest of Mode S overlays its parity with the address, so it is a different adapter."""
    bits = f"{11:05b}{5:03b}{0x0029C1:024b}" + "0" * 80
    with pytest.raises(ValueError, match="not an extended squitter"):
        adsb.decode(bits[:88] + f"{adsb.crc(bits[:88]):024b}")


@pytest.mark.parametrize("control", adsb.CF_REFUSED)
def test_a_df18_control_field_out_of_scope_is_refused_by_name(control):
    """CF 3 has a DIFFERENT layout: decoding it as fine format yields a wrong position."""
    bits = f"{18:05b}{control:03b}{0x0029C1:024b}" + f"{11:05b}" + "0" * 51
    with pytest.raises(ValueError, match="not in this adapter's scope"):
        adsb.decode(bits + f"{adsb.crc(bits):024b}")


@pytest.mark.parametrize("type_code,subtype", [(29, None), (23, None), (19, 0), (19, 5),
                                               (28, 2), (31, 1)])
def test_a_type_code_out_of_scope_is_refused_by_name(type_code, subtype):
    """Each of these is a decision recorded in FORMAT_COVERAGE.md, not an omission."""
    me = f"{type_code:05b}" + (f"{subtype:03b}" if subtype is not None else "")
    me = me.ljust(56, "0")
    bits = f"{17:05b}{5:03b}{0x0029C1:024b}{me}"
    with pytest.raises(ValueError, match="not in this adapter's scope"):
        adsb.decode(bits + f"{adsb.crc(bits):024b}")


def test_a_frame_of_the_wrong_length_is_refused_rather_than_read_into_the_padding():
    with pytest.raises(ValueError, match="expected exactly 28"):
        _adapter().to_cdm(b"*8D0029C1202CC3;\n")
    with pytest.raises(ValueError, match="exactly 112"):
        adsb.decode("1" * 56)


def test_an_unterminated_avr_line_is_refused():
    with pytest.raises(ValueError, match="not terminated"):
        _adapter().to_cdm(b"*880029C159A10266143D0A713484\n")


def test_a_line_that_is_not_hexadecimal_is_refused():
    with pytest.raises(ValueError, match="not hexadecimal"):
        _adapter().to_cdm(b"*ZZ0029C159A10266143D0A71348Z;\n")


def test_the_adapter_refuses_a_type_it_cannot_take():
    with pytest.raises(TypeError, match="ADS-B adapter takes"):
        _adapter().to_cdm(42)


def test_an_empty_payload_is_refused():
    with pytest.raises(ValueError, match="empty"):
        _adapter().to_cdm(b"\n\n")


# --------------------------------------------------------------------- egress


@pytest.mark.parametrize("path", EGRESS_FIXTURES, ids=lambda p: p.name)
def test_every_egress_fixture_matches_its_golden(path):
    emitted = _adapter().from_cdm([_object(path.name)])
    golden = (EGRESS / "golden" / f"{path.stem}.adsb").read_bytes()
    assert emitted == golden, (
        f"{path.name} no longer emits its golden frames:\n"
        f"  golden  {golden!r}\n  emitted {emitted!r}")


@pytest.mark.parametrize("path", EGRESS_FIXTURES, ids=lambda p: p.name)
def test_every_emitted_frame_carries_a_valid_crc(path):
    """Generated, not copied — and a receiver silently discards a frame that fails."""
    for parsed in _parse_all(_adapter().from_cdm([_object(path.name)])):
        bits = adsb._bits_of_hex(parsed["frame"]["hex"])
        assert adsb.crc(bits[:88]) == int(bits[88:], 2)


def test_a_track_becomes_one_position_frame_per_sample_in_its_own_order():
    track = _object("track_air_patrol_three_samples.json")
    frames = _parse_all(_adapter().from_cdm([track]))
    assert len(frames) == len(track.samples)
    for sample, parsed in zip(track.samples, frames):
        message = parsed["message"]
        assert message["type_code"] == adsb.DEFAULT_TYPE_CODE_WITH_ALTITUDE
        assert (message["cpr_lat"], message["cpr_lon"]) == adsb.cpr_encode(
            sample.position.lat, sample.position.lon, 0, span=adsb.CPR_SPAN_AIRBORNE)
        # Type code 22's altitude field is metres, so the sample's own alt_m goes in
        # unconverted — no foot round trip to lose a step in.
        assert adsb.gnss_height_m(message["altitude_raw"])[0] == round(sample.position.alt_m)


def test_a_tracks_frames_are_all_even_so_no_receiver_can_globally_pair_them():
    """Two samples minutes apart, paired globally, yield a position the aircraft was never at.

    So the one frame shape that cannot be misused is the one that is emitted. This is the CPR
    decision showing up in the egress direction.
    """
    frames = _parse_all(_adapter().from_cdm([_object("track_air_patrol_three_samples.json")]))
    assert {parsed["message"]["cpr_format"] for parsed in frames} == {0}


def test_an_entity_holding_a_position_and_a_velocity_becomes_two_frames():
    """1090ES has no frame that carries both, so one frame would mean dropping a measurement."""
    frames = _parse_all(_adapter().from_cdm([_object("entity_fused_elsewhere.json")]))
    assert [parsed["message"]["type_code"] for parsed in frames] == [
        adsb.DEFAULT_TYPE_CODE_NO_ALTITUDE, adsb.TC_VELOCITY]
    assert frames[1]["message"]["subtype"] == 1, (
        "subtype 1 is velocity over ground, which is what speed_mps means; subtype 3 would "
        "restate it as an airspeed")


def test_the_default_type_codes_claim_no_navigation_integrity():
    """The type code IS an accuracy claim, so a default of 9 or 20 asserts a measured bound."""
    assert adsb.DEFAULT_TYPE_CODE_NO_ALTITUDE == 18
    assert adsb.DEFAULT_TYPE_CODE_WITH_ALTITUDE == 22
    no_altitude = _parse_all(_adapter().from_cdm([_object("entity_fused_elsewhere.json")]))
    assert no_altitude[0]["message"]["type_code"] == 18
    assert no_altitude[0]["message"]["altitude_raw"] == 0, "a null altitude is not -1000 ft"


def test_an_entity_that_arrived_from_adsb_re_emits_exactly_its_own_frame():
    """A surface frame carries movement and ground track in the same 56 bits.

    Synthesising a velocity frame beside it would invent a transmission the aircraft never made
    — and would break the byte-exact round trip.
    """
    entity, _ = _translate("surface_position_riga_taxiway.adsb", REFERENCE)
    assert entity.position is not None and entity.kinematics is not None
    frames = _parse_all(_adapter(REFERENCE).from_cdm([entity]))
    assert len(frames) == 1
    assert frames[0]["message"]["type_code"] == 6


def test_an_object_with_no_address_is_refused_rather_than_given_a_derived_one():
    """Deriving one would put an aircraft on 1090 MHz under a number nobody allocated."""
    raw = json.loads((EGRESS / "track_air_patrol_three_samples.json").read_text())
    raw["source_ids"] = [{"system": "FUSION", "external_id": "T-1"}]
    with pytest.raises(ValueError, match="no ICAO24 source id"):
        _adapter().from_cdm([Track.model_validate(raw)])


def test_an_entity_stating_nothing_transmissible_is_refused():
    """A frame of pure not-available values says nothing about the aircraft it names."""
    entity = _object("entity_fused_elsewhere.json").model_copy(
        update={"position": None, "kinematics": None})
    with pytest.raises(ValueError, match="states no position, no motion"):
        _adapter().from_cdm([entity])


def test_a_callsign_too_long_or_unrepresentable_is_refused_rather_than_corrupted():
    """A callsign cut short on the wire reads as the aircraft's real callsign to every receiver."""
    entity = _object("entity_identification_no_position.json")
    for value, message in (("TOOLONGCALLSIGN", "refusing to truncate"),
                           ("EX-RCS1", "cannot carry"),
                           ("EX#RCS1", "cannot carry")):
        broken = entity.model_copy(
            update={"attributes": {**entity.attributes, "callsign": value}})
        with pytest.raises(ValueError, match=message):
            _adapter().from_cdm([broken])


def test_from_cdm_emits_one_objects_frames_and_refuses_to_invent_a_container():
    with pytest.raises(ValueError, match="ONE object"):
        _adapter().from_cdm([_object("entity_fused_elsewhere.json"),
                             _object("track_air_patrol_three_samples.json")])
    with pytest.raises(ValueError, match="ONE object"):
        _adapter().from_cdm([])


def test_an_event_alone_is_not_emittable_and_supplies_no_time_either():
    """Unlike AIS, where an Event supplied the second of the minute: no frame has a time field."""
    _, event = _translate("airborne_position_baro_gulf_of_riga.adsb")
    with pytest.raises(ValueError, match="ONE object"):
        _adapter().from_cdm([event])


def test_the_canonical_value_wins_over_the_parked_one():
    """Egress must be a translation and not a replay: an edited position has to reach the wire."""
    entity, _ = _translate("airborne_position_baro_gulf_of_riga.adsb", REFERENCE)
    moved = entity.model_copy(update={
        "position": entity.position.model_copy(update={"lat": 57.1234})})
    message = _parse_all(_adapter(REFERENCE).from_cdm([moved]))[0]["message"]
    assert message["cpr_lat"] != entity.attributes["cpr_lat"]
    reingested, _ = _adapter(REFERENCE).to_cdm(_adapter(REFERENCE).from_cdm([moved]))
    assert round(reingested.position.lat, 4) == 57.1234


def test_an_edited_gnss_altitude_reaches_the_wire_over_the_parked_figure():
    entity, _ = _translate("airborne_position_gnss_height_odd.adsb", REFERENCE)
    raised = entity.model_copy(update={
        "position": entity.position.model_copy(update={"alt_m": 3900.0})})
    message = _parse_all(_adapter(REFERENCE).from_cdm([raised]))[0]["message"]
    assert adsb.gnss_height_m(message["altitude_raw"])[0] == 3900
    assert entity.attributes["gnss_altitude_m"] == 3200, "the parked figure is not what won"


# --------------------------------------------------------------- round trips


@pytest.mark.parametrize("path", FRAME_FIXTURES, ids=lambda p: p.name)
@pytest.mark.parametrize("reference", [None, REFERENCE], ids=["no-reference", "referenced"])
def test_the_ingest_round_trip_is_byte_exact(path, reference):
    """The strongest claim available: a frame in, the same frame out, CRC included.

    Achievable because every bit is decoded — reserved fields included — and because the parked
    fields are read back on the way out. Run under BOTH reference settings on purpose: with a
    reference the position round-trips through the CDM and back through CPR, without one it
    round-trips through the parked CPR values, and those are two different code paths that must
    both be exact.
    """
    adapter = _adapter(reference)
    assert adapter.from_cdm(adapter.to_cdm(path.read_bytes())) == path.read_bytes()


#: CDM facts with no ADS-B field to put them in, excluded from the egress comparison BY NAME so
#: that adding a field to a model cannot silently join the list.
#:
#: AIS had no extension point; ADS-B has none and then some. All 56 ME bits are allocated per
#: type code and the parity is a CRC over the other 88, so a bit invented here would either be
#: read as the field the standard says lives there or would break the CRC and be dropped by
#: every receiver. These do not reach the wire, and the honest thing is to name each one.
EGRESS_NO_ADSB_FIELD = {
    "object_kind": "the CDM's own discriminator",
    "schema_version": "the CDM's own version; ADS-B frames are versioned by type code, and by "
                      "the DO-260 version in a type 31 frame",
    "source": "our provenance. Deliberately not transmitted — source.synthetic in particular "
              "is ours to know and not a fact about the aircraft",
    "integrity": "the signature block, which is designed and unpopulated",
    "source_ids": "the ICAO address IS the frame's address field and is asserted directly "
                  "below; there is no second identifier to carry",
    "entity_id": "ADS-B identity is the 24-bit address. A CDM uuid has nowhere to go",
    "track_id": "same, and a track is not an object ADS-B models at all",
    "track_quality": "ADS-B states navigation integrity and accuracy CATEGORIES, which are a "
                     "different claim and are carried separately",
    "entity_type": "ADS-B states a type code and an emitter category, not what the CDM decided",
    "affiliation": "there is no identity field in any frame. Emitting one would invent a claim",
    "symbol": "there is no symbol field in any frame",
    "valid_from": "no frame in this format carries a time field",
    "valid_to": "ADS-B has no staleness field",
    "confidence": "ADS-B states no confidence",
    "observed_at": "a Track sample's instant. No frame has a time field to put it in, which "
                   "is the one thing this direction simply cannot do",
    "position_source": "the frame's own downlink format and control field imply it; there is "
                       "no field to write it into",
    "accuracy_m": "ADS-B states an integrity category, not a metre figure",
}

#: Fields that DO travel but arrive transformed, so a value-presence check cannot see them.
#: Each one is asserted directly by a test named beside it — the point of listing them here is
#: that "transformed" and "dropped" must not be the same entry.
EGRESS_TRANSFORMED = {
    "lat": "carried as a CPR zone offset — test_the_egress_round_trip_returns_every_value",
    "lon": "carried as a CPR zone offset — same test",
    "alt_m": "carried as whole metres in a GNSS-height frame — same test",
    "speed_mps": "carried as two signed knot components — same test",
    "course_deg": "carried as two signed knot components — same test",
    "climb_mps": "carried as 64 ft/min steps — same test",
}


def test_every_egress_exclusion_names_a_field_that_is_actually_there():
    """An exclusion for a field nothing emits is an exemption with no subject.

    It would silence the round-trip check for a field that never existed, which is the one way
    these lists can rot without anybody noticing.
    """
    present = set()
    for path in EGRESS_FIXTURES:
        for leaf in lossless.leaves(_object(path.name).model_dump(mode="json")):
            present |= {part.split("[")[0] for part in leaf.split(".")}
    unused = (set(EGRESS_NO_ADSB_FIELD) | set(EGRESS_TRANSFORMED)) - present
    assert not unused, f"declared but never emitted by any egress fixture: {sorted(unused)}"
    assert not set(EGRESS_NO_ADSB_FIELD) & set(EGRESS_TRANSFORMED), (
        "a field is either carried-transformed or not carried; it cannot be both")


@pytest.mark.parametrize("path", EGRESS_FIXTURES, ids=lambda p: p.name)
def test_the_egress_round_trip_returns_every_value_the_format_can_carry(path):
    """CDM -> frames -> CDM, compared with the tolerances the format's quantisation imposes.

    Measured this way rather than by value presence because almost every ADS-B field is a
    TRANSFORM of its CDM value — a position is a pair of CPR zone offsets, a ground speed is two
    signed knot components. A value-presence comparison would have to exempt nearly everything,
    which is an exclusion list that proves nothing.

    A Track is compared sample by sample; an Entity's two frames are re-ingested and merged the
    way a fusion layer would, which is the honest reading of "one object, two transmissions".
    """
    subject = _object(path.name)
    adapter = _adapter(REFERENCE)
    reingested = [adapter.to_cdm(line.encode("ascii") + b"\n")[0]
                  for line in adapter.from_cdm([subject]).decode().split("\n") if line]

    if isinstance(subject, Track):
        assert len(reingested) == len(subject.samples)
        for sample, entity in zip(subject.samples, reingested):
            _assert_position_survived(sample.position, entity.position)
        return

    checked = 0
    if subject.position is not None:
        positions = [e.position for e in reingested if e.position is not None]
        assert positions, "the position frame did not come back with a position"
        _assert_position_survived(subject.position, positions[0])
        checked += 1
    if subject.kinematics is not None:
        motion = [e.kinematics for e in reingested if e.kinematics is not None]
        assert motion, "the velocity frame did not come back with kinematics"
        _assert_kinematics_survived(subject.kinematics, motion[0])
        checked += 1
    # An object stating neither is not a free pass: it still has to carry SOMETHING back, or
    # this test would silently assert nothing for the identification fixture.
    for key in ("callsign", "emitter_category"):
        if subject.attributes.get(key) is not None:
            assert any(e.attributes.get(key) == subject.attributes[key] for e in reingested), (
                f"{key} did not survive the round trip")
            checked += 1
    assert checked, (
        f"{path.name} carries no position, no motion and no parked identity, so this test "
        "compared nothing — give it something to compare or drop the fixture")


def _assert_position_survived(original, returned):
    """CPR quantisation is about 5.1 m in latitude for an airborne frame; altitude is 25 ft."""
    assert returned is not None
    assert abs(returned.lat - original.lat) < 1e-4, (original.lat, returned.lat)
    assert abs(returned.lon - original.lon) < 1e-4, (original.lon, returned.lon)
    if original.alt_m is None:
        assert returned.alt_m is None
    else:
        # One metre: the GNSS-height field's own resolution, since every egress fixture that
        # states an altitude states it on a type code 22 frame. A barometric carrier would
        # quantise to 25 ft instead, and would need its own tolerance rather than this one.
        assert abs(returned.alt_m - original.alt_m) <= 1.0


def _assert_kinematics_survived(original, returned):
    """A velocity component is a whole knot; a vertical rate is 64 ft/min.

    Each field is compared only where the original stated one, and an original that stated
    nothing at all is a fixture bug rather than a pass — otherwise a Kinematics of three Nones
    would satisfy this silently.
    """
    tolerances = (("speed_mps", 2 * adsb.KNOT_MPS), ("course_deg", 1.0),
                  ("climb_mps", 64 * adsb.FEET_PER_MINUTE_MPS))
    compared = 0
    for field, tolerance in tolerances:
        expected = getattr(original, field)
        if expected is None:
            continue
        actual = getattr(returned, field)
        assert actual is not None, f"{field} was stated and did not come back"
        assert abs(actual - expected) <= tolerance, (field, expected, actual)
        compared += 1
    assert compared, "the original Kinematics stated nothing, so nothing was compared"


@pytest.mark.parametrize("fixture,dropped,expected", [
    ("track_air_patrol_three_samples.json", "cpr_lat", "lat"),
    ("track_air_patrol_three_samples.json", "altitude_raw", "alt_m"),
    ("entity_fused_elsewhere.json", "cpr_lon", "lon"),
    ("entity_fused_elsewhere.json", "ew_velocity_raw", "speed"),
    ("entity_fused_elsewhere.json", "vertical_rate_raw", "climb"),
    ("entity_identification_no_position.json", "callsign", "callsign"),
])
def test_the_egress_round_trip_would_notice_each_kind_of_loss(fixture, dropped, expected):
    """The check above is only worth running if it can fail — so make it fail, six ways.

    A round-trip test that passes because it compares nothing is the failure mode this guards
    against. Each field the emitter writes is zeroed in the DECODED form in turn, and the value
    it carried must stop coming back.
    """
    subject = _object(fixture)
    adapter = _adapter(REFERENCE)
    frames = _parse_all(adapter.from_cdm([subject]))
    target = next(parsed for parsed in frames if dropped in parsed["message"])
    target["message"][dropped] = 0 if dropped != "callsign" else ""
    entity, _ = adapter.to_cdm(target)

    if expected == "lat":
        assert entity.position is None or abs(entity.position.lat -
                                              subject.samples[0].position.lat) > 1e-4
    elif expected == "lon":
        assert entity.position is None or abs(entity.position.lon - subject.position.lon) > 1e-4
    elif expected == "alt_m":
        assert entity.position is None or entity.position.alt_m is None
    elif expected == "speed":
        assert entity.kinematics is None or entity.kinematics.speed_mps is None
    elif expected == "climb":
        assert entity.kinematics is None or entity.kinematics.climb_mps is None
    else:
        assert "callsign" not in entity.attributes


def test_the_address_reaches_the_wire_on_every_emitted_frame():
    """Asserted directly because the round trip excludes `source_ids` wholesale."""
    for path in EGRESS_FIXTURES:
        subject = _object(path.name)
        expected = next(s.external_id for s in subject.source_ids if s.system == "ICAO24")
        for parsed in _parse_all(_adapter().from_cdm([subject])):
            assert parsed["message"]["icao"] == expected, path.name


def test_the_callsign_and_emitter_category_reach_the_wire():
    entity = _object("entity_identification_no_position.json")
    message = _parse_all(_adapter().from_cdm([entity]))[0]["message"]
    assert message["type_code"] == 4
    assert message["callsign"] == "EXHELO2"
    assert message["emitter_category"] == 7


# ------------------------------------------------------------------- harness


def test_the_harness_passes_every_fixture_against_the_published_schemas():
    """The gate, run against `/schemas` rather than the models — that is what consumers read."""
    from synapse_cdm import harness

    report = harness.run(_adapter(), FIXTURES, schema_dir=SCHEMAS)
    assert report["failed"] == 0, harness.render_report(report)
    assert report["passed"] >= 30

    for result in report["results"]:
        checks = result["checks"]
        assert checks["translate"] == "PASS", result
        assert checks["schema"] == "PASS", result
        assert checks["provenance"] == "PASS", result
        assert checks["golden"] == "PASS", result
        # The lossless check runs on the parsed form and can only SKIP on the frames, because
        # the harness has no leaf structure to harvest from bytes. Asserting the split rather
        # than accepting "not FAIL" is what stops a frames-only fixture set from quietly
        # turning the never-drop check off for this adapter.
        expected = "SKIP" if result["fixture"].endswith(".adsb") else "PASS"
        assert checks["lossless"] == expected, result
        # roundtrip is SKIP for every fixture BY DESIGN: from_cdm returns hex frames, which the
        # harness cannot compare structurally. That is why this file carries the round trips.
        assert checks["roundtrip"] == "SKIP", result


def test_the_harness_does_not_pick_up_the_local_or_egress_directories():
    """`run()` replays every fixture through `to_cdm()`, so a CDM payload beside the frames
    would be fed to the frame parser and fail. Both live in subdirectories for that reason."""
    from synapse_cdm import harness

    report = harness.run(_adapter(), FIXTURES, schema_dir=SCHEMAS)
    names = {result["fixture"] for result in report["results"]}
    assert not any(name.endswith(".cdm.json") for name in names)
    assert "README.md" not in names


def test_the_adapter_is_registered_and_declares_itself_bidirectional():
    from synapse_cdm.adapter import discover

    registry = discover()
    assert registry["adsb"] is AdsbAdapter
    assert AdsbAdapter.direction == "bidirectional"
    assert AdsbAdapter.system == "ADSB"


def test_every_declared_transform_names_a_path_the_adapter_consumes():
    """A TRANSFORMS entry for a path nothing reads is an exemption with no subject."""
    consumed = set(AdsbAdapter.CONSUMED)
    for path in AdsbAdapter.TRANSFORMS:
        assert path in consumed, (
            f"TRANSFORMS declares {path!r}, which is not in CONSUMED — either the adapter "
            "stopped reading it or the declaration is a leftover")


def test_every_consumed_path_is_actually_present_in_some_fixture():
    """A CONSUMED entry nothing sends over-prunes the residual for a field that never arrives.

    Harmless today and wrong the moment the path is real: `residual()` would drop it from the
    parked bag while nothing mapped it, which is a silent hole in the never-drop rule.
    """
    seen = set()
    for path in FRAME_FIXTURES:
        seen |= set(lossless.leaves(adsb._parse_frames(path.read_bytes())))
    unused = [c for c in AdsbAdapter.CONSUMED
              if not any(leaf == c or leaf.startswith(f"{c}.") for leaf in seen)]
    assert not unused, f"CONSUMED paths no fixture exercises: {unused}"
