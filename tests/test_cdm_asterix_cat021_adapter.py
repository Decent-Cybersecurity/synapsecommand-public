"""One test per claim in the CAT021 adapter's docstring, plus the round trip the harness cannot do.

WHY THIS FILE CARRIES THE BYTE-EXACT ROUND TRIP
------------------------------------------------
The harness's `roundtrip` column reports SKIP for an adapter that emits something it cannot
compare structurally, and says so out loud: `from_cdm()` here returns raw ASTERIX octets. The
README's instruction for that case is that the adapter ships its own round-trip test, so both
directions are exercised here — and here the claim is stronger than the harness's would be. The
harness compares VALUE PRESENCE; this compares OCTETS, because a CAT021 record's contents are
deterministic and a byte-exact claim is falsifiable in a way a value-presence one is not.

WHAT IS PINNED, AND AGAINST WHAT
---------------------------------
The codec's two halves are inverses by construction, so proving that says nothing about whether
either matches the specification. So the pins are external wherever one can be had:

- the UAP is rebuilt here from Edition 2.6 Table 2, item by item, and compared against the
  adapter's own table, so a transposed FRN fails rather than round-tripping happily;
- the FSPEC is recomputed by an independently written bit walk;
- a record is hand-assembled octet by octet from values written in this file and must equal the
  shipped fixture byte for byte;
- and every arithmetic conversion is checked against the value the specification's own LSB
  implies, computed here rather than read out of the adapter.
"""
import datetime as _dt
import json
import pathlib

import pytest

import synapse_cdm
from synapse_cdm import ids, lossless, times
from synapse_cdm.adapters import asterix_cat021 as cat021
from synapse_cdm.adapters.adsb import AdsbAdapter
from synapse_cdm.adapters.asterix_cat021 import AsterixCat021Adapter, Cat021ParseError
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import Entity, Event, Position, Track, TrackSample

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "cat021"
GOLDEN = FIXTURES / "golden"
REFUSALS = FIXTURES / "refusals"
SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "schemas"

BLOCK_FIXTURES = sorted(FIXTURES.glob("*.cat021"))
PARSED_FIXTURES = sorted(FIXTURES.glob("*.parsed.json"))

STATION = (0x29, 0x29)


def _adapter(now: _dt.datetime | None = None, *, station=None) -> AsterixCat021Adapter:
    return AsterixCat021Adapter(clock=times.frozen_clock(now or times.FROZEN_NOW),
                                station=station)


def _objects(name: str, now: _dt.datetime | None = None):
    return _adapter(now).to_cdm((FIXTURES / f"{name}.cat021").read_bytes())


def _entity(name: str, now: _dt.datetime | None = None) -> Entity:
    return next(o for o in _objects(name, now) if isinstance(o, Entity))


def _event(name: str, now: _dt.datetime | None = None) -> Event:
    return next(o for o in _objects(name, now) if isinstance(o, Event))


# =============================================================== the fixture set itself

def test_the_fixture_set_is_not_silently_empty():
    """A parametrised suite over a glob that matches nothing passes while testing nothing."""
    assert len(BLOCK_FIXTURES) >= 18, f"only {len(BLOCK_FIXTURES)} block fixtures"
    assert len(PARSED_FIXTURES) == len(BLOCK_FIXTURES), "every block must ship its parsed twin"
    assert len(sorted(REFUSALS.glob("*.cat021"))) >= 5, "the refusal payloads are missing"


@pytest.mark.parametrize("path", BLOCK_FIXTURES, ids=lambda p: p.stem)
def test_the_parsed_twin_is_what_the_block_actually_parses_to(path):
    """Hand-maintained, the twin would drift — and each would still pass its own golden check."""
    twin = json.loads(path.with_suffix("").with_suffix(".parsed.json").read_text())
    assert cat021._parse_block(path.read_bytes()) == twin


@pytest.mark.parametrize("path", BLOCK_FIXTURES, ids=lambda p: p.stem)
def test_the_block_and_its_twin_produce_identical_cdm(path):
    """`to_cdm` takes bytes OR the parsed dict, and the two entry points must not diverge."""
    from_bytes = _adapter().to_cdm(path.read_bytes())
    from_twin = _adapter().to_cdm(
        json.loads(path.with_suffix("").with_suffix(".parsed.json").read_text()))
    assert [o.model_dump(mode="json") for o in from_bytes] == \
           [o.model_dump(mode="json") for o in from_twin]


@pytest.mark.parametrize("path", BLOCK_FIXTURES, ids=lambda p: p.stem)
def test_every_fixture_address_is_below_the_lowest_allocated_icao_block(path):
    """0029xx — the ADS-B fixture set's block, reused so the two sets are one family.

    The ICAO allocation table's lowest state block begins at 004000, so everything below it is
    in no administration's range. The constraint is asserted here rather than left to the
    README so the assumption is discoverable from a failure.
    """
    parsed = cat021._parse_block(path.read_bytes())
    for record in parsed["records"]:
        address = record["items"]["I021/080"]["target_address"]
        assert address < 0x004000, f"{path.stem}: address {address:06X} is in an allocated block"


@pytest.mark.parametrize("path", BLOCK_FIXTURES, ids=lambda p: p.stem)
def test_every_fixture_uses_the_pinned_system_area_code(path):
    """SAC 0x29, and it is PINNED rather than asserted — see fixtures/cat021/spec/sac_pin.json.

    This assertion sits ON TOP of the pin. On its own it would be the mistake the pin exists to
    correct: an assertion on an unverified constant fails when someone edits it and never fails
    for the reason that matters. The pin is what establishes that 0x29 is unallocated; this is
    what establishes that the fixtures actually use it.
    """
    pin = json.loads((FIXTURES / "spec" / "sac_pin.json").read_text())
    expected = int(pin["fixture_sac"]["value"], 16)
    parsed = cat021._parse_block(path.read_bytes())
    for record in parsed["records"]:
        assert record["items"]["I021/010"]["sac"] == expected


# ============================================================ the wire form, pinned externally

#: Edition 2.6, Table 2, transcribed here from the specification rather than imported from the
#: adapter. A transposed FRN would otherwise round-trip happily: the encoder and the decoder
#: would agree with each other and disagree with every other ASTERIX system on the planet.
UAP_FROM_THE_SPECIFICATION = {
    1: "I021/010", 2: "I021/040", 3: "I021/161", 4: "I021/015", 5: "I021/071",
    6: "I021/130", 7: "I021/131", 8: "I021/072", 9: "I021/150", 10: "I021/151",
    11: "I021/080", 12: "I021/073", 13: "I021/074", 14: "I021/075", 15: "I021/076",
    16: "I021/140", 17: "I021/090", 18: "I021/210", 19: "I021/070", 20: "I021/230",
    21: "I021/145", 22: "I021/152", 23: "I021/200", 24: "I021/155", 25: "I021/157",
    26: "I021/160", 27: "I021/165", 28: "I021/077", 29: "I021/170", 30: "I021/020",
    31: "I021/220", 32: "I021/146", 33: "I021/148", 34: "I021/110", 35: "I021/016",
    36: "I021/008", 37: "I021/271", 38: "I021/132", 39: "I021/250", 40: "I021/260",
    41: "I021/400", 42: "I021/295", 48: "RE", 49: "SP",
}


def test_the_uap_matches_the_specifications_own_table():
    adapter_uap = {frn: item for frn, item, _ in cat021.UAP if item is not None}
    assert adapter_uap == UAP_FROM_THE_SPECIFICATION
    not_used = {frn for frn, item, _ in cat021.UAP if item is None}
    assert not_used == {43, 44, 45, 46, 47}, "FRN 43-47 are Not Used in category 021"


def test_the_fspec_is_what_an_independent_bit_walk_produces():
    """Seven FRNs per octet, MSB first, FX in bit 1 of every octet but the last."""
    for frns in ([1], [1, 2, 11, 17], [1, 2, 5, 7, 11, 16, 17, 25, 26], [49]):
        octets = cat021._fspec_for(frns)
        recovered = []
        for index, octet in enumerate(octets):
            for bit in range(7, 0, -1):
                if octet & (1 << bit):
                    recovered.append(index * 7 + (8 - bit))
            assert bool(octet & 1) == (index != len(octets) - 1), "FX on all but the last"
        assert recovered == sorted(frns)


def test_a_hand_assembled_record_equals_the_shipped_fixture():
    """The external pin: a block laid out octet by octet from values written HERE.

    If the generator and the parser drifted together, every other test in this file would still
    pass. This one would not.
    """
    # I021/010  SAC 0x29, SIC 0x29
    # I021/040  primary only, ATP 0 (24-bit ICAO address), FX clear      -> 0x00
    # I021/071  06:13:10.000 = 22 390 s x 128 = 2 865 920 units          -> 0x2B B7 00
    # I021/080  0029C1
    # I021/090  primary only, all zero, FX clear                         -> 0x00
    # I021/131  57.5981 N, 23.8412 E at LSB 180/2^30
    # I021/140  7 600 ft / 6.25 = 1216                                   -> 0x04C0
    # I021/170  "EXRCS01 " packed six bits per character
    # I021/020  emitter category 3
    # I021/210  VNS 0, VN 2, LTT 2                                       -> 0b0_0_010_010 = 0x12
    latitude = round(57.5981 / cat021.LSB_131_DEGREES)
    longitude = round(23.8412 / cat021.LSB_131_DEGREES)
    assert 2865920 == round((6 * 3600 + 13 * 60 + 10) / cat021.TIME_LSB_SECONDS)
    assert 1216 == round(7600 / cat021.GEOMETRIC_HEIGHT_LSB_FEET)

    identification = 0
    for character in "EXRCS01 ":
        identification = (identification << 6) | cat021.IDENTIFICATION_ALPHABET.index(character)

    items = {
        1: bytes((0x29, 0x29)),
        2: bytes((0x00,)),
        5: (2865920).to_bytes(3, "big"),
        7: latitude.to_bytes(4, "big", signed=True) + longitude.to_bytes(4, "big", signed=True),
        11: (0x0029C1).to_bytes(3, "big"),
        16: (1216).to_bytes(2, "big", signed=True),
        17: bytes((0x00,)),
        18: bytes((0x12,)),
        29: identification.to_bytes(6, "big"),
        30: bytes((3,)),
    }
    frns = sorted(items)
    body = cat021._fspec_for(frns) + b"".join(items[frn] for frn in frns)
    block = bytes((21,)) + (3 + len(body)).to_bytes(2, "big") + body

    assert block == (FIXTURES / "icao24_shared_with_adsb.cat021").read_bytes()


def test_the_block_length_counts_the_header_and_is_computed_never_copied():
    octets = (FIXTURES / "icao24_shared_with_adsb.cat021").read_bytes()
    assert octets[0] == 21
    assert int.from_bytes(octets[1:3], "big") == len(octets)
    # A stale LEN is a refusal on the way in and impossible on the way out.
    emitted = _adapter().from_cdm(_objects("icao24_shared_with_adsb"))
    assert int.from_bytes(emitted[1:3], "big") == len(emitted)


# ================================================================== the byte-exact round trip

@pytest.mark.parametrize("path", BLOCK_FIXTURES, ids=lambda p: p.stem)
def test_ingest_then_egress_reproduces_the_block_octet_for_octet(path):
    """The claim FORMAT_COVERAGE.md makes, measured on octets rather than on values.

    It holds only because every item's wire octets are parked verbatim and re-emitted from the
    park — the 2^-30 s items, the 1/128 s items and the spare bits are all things a canonical
    field cannot carry back. That is why TRANSFORMS is empty: the never-drop rule is satisfied
    by presence, not by an exemption.
    """
    original = path.read_bytes()
    objects = _adapter().to_cdm(original)
    assert _adapter().from_cdm(objects) == original


def test_the_round_trip_survives_spare_bits_that_are_not_zero():
    """Section 4.3 only RECOMMENDS zeroing spare bits, so a real encoder may set them.

    Asserted separately from the parametrised round trip because this is the fixture that would
    pass it for the wrong reason if the adapter normalised spares to zero on ingest and the
    fixture happened to carry zeros.
    """
    original = (FIXTURES / "spare_bits_nonzero.cat021").read_bytes()
    parsed = cat021._parse_block(original)
    mode_3a = bytes.fromhex(parsed["records"][0]["item_octets"]["I021/070"])
    assert mode_3a[0] >> 4 == 0xF, "the fixture must actually carry non-zero spare bits"
    assert _adapter().from_cdm(_adapter().to_cdm(original)) == original


def test_the_special_purpose_field_is_restored_but_never_invented():
    """SP's contents are settled by bilateral agreement, so we return them and never author them."""
    entity = _entity("special_purpose_field_opaque")
    assert entity.attributes["cat021_items"]["SP"] == "04deadbe"
    emitted = _adapter().from_cdm(_objects("special_purpose_field_opaque"))
    assert bytes.fromhex("04deadbe") in emitted

    # An object that never carried one gets none: no SP in an emitted synthesised record.
    synthetic = Entity(
        source=_adapter().source_ref(), entity_id=ids.derive("ICAO24", "0029F1"),
        source_ids=[{"system": "ICAO24", "external_id": "0029F1"}],
        entity_type=EntityType.PLATFORM, affiliation=Affiliation.UNKNOWN,
        position=Position(lat=57.0, lon=23.0, position_source=PositionSource.GNSS),
        valid_from=times.FROZEN_NOW,
    )
    emitted = _adapter(station=STATION).from_cdm([synthetic])
    parsed = cat021._parse_block(emitted)
    assert "SP" not in parsed["records"][0]["items"]
    assert "RE" not in parsed["records"][0]["items"]


# ========================================================================== time

def test_the_position_applicability_time_heads_the_chain():
    event = _event("airborne_position_time_of_applicability")
    assert times.render(event.observed_at) == "2026-04-29T06:11:20.000Z"
    assert "I021/071" in event.payload["observed_at_basis"]
    # received_at is OURS, and never the ground station's own receipt instant.
    assert times.render(event.received_at) == times.render(times.FROZEN_NOW)
    assert "injected clock" in event.payload["received_at_basis"]


def test_the_message_reception_time_is_used_only_when_applicability_is_absent():
    event = _event("position_time_of_message_reception_high_precision")
    assert "I021/073" in event.payload["observed_at_basis"]
    assert "I021/071" not in event.payload["observed_at_basis"].split(".")[0]


def test_the_full_second_indication_is_a_whole_second_correction_not_a_rounding_hint():
    """I021/073 says 06:11:23; FSI = 01 means the whole seconds are that PLUS ONE.

    An adapter ignoring FSI would land on 06:11:23.250 — a full second early, at exactly the
    moment the ground station took the trouble to say the fix was near a second boundary.
    """
    event = _event("position_time_of_message_reception_high_precision")
    assert times.render(event.observed_at) == "2026-04-29T06:11:24.250Z"


def test_a_reserved_full_second_indication_is_declined_and_its_bits_are_kept():
    """FSI = 3 is reserved: no defined correction, so applying one of the other three is a guess."""
    entity = _entity("reserved_full_second_indication")
    event = _event("reserved_full_second_indication")
    assert times.render(event.observed_at) == "2026-04-29T06:11:23.000Z", \
        "the plain I021/073 must be used when the high-precision item cannot be"
    unresolved = entity.attributes["unresolved_raw"]
    assert "I021/074_reserved_full_second_indication" in unresolved
    assert unresolved["I021/074_reserved_full_second_indication"]["full_second_indication"] == 3
    # And it is NOT an unavailable field: the source stated something, it was not silent.
    assert "I021/074" not in (entity.attributes.get("unavailable_fields") or [])


def test_midnight_rollover_backwards():
    """23:59:58.500 delivered at 00:00:01.100 the next day belongs to the PREVIOUS day."""
    received = _dt.datetime(2026, 4, 30, 0, 0, 1, 100000, tzinfo=_dt.timezone.utc)
    event = _event("midnight_rollover_before", now=received)
    assert times.render(event.observed_at) == "2026-04-29T23:59:58.500Z"
    assert "rollover" in event.payload["observed_at_basis"]
    assert "previous" in event.payload["observed_at_basis"]


def test_midnight_rollover_forwards():
    """00:00:00.875 delivered at 23:59:59.700 belongs to the NEXT day. Same rule, no special case.

    0.875 s is exactly 112 units of 1/128 s — a time this format can represent — so the assertion
    reads as a rollover and not as a quantisation.
    """
    received = _dt.datetime(2026, 4, 29, 23, 59, 59, 700000, tzinfo=_dt.timezone.utc)
    event = _event("midnight_rollover_after", now=received)
    assert times.render(event.observed_at) == "2026-04-30T00:00:00.875Z"
    assert "next" in event.payload["observed_at_basis"]


def test_a_time_of_day_beyond_a_day_is_refused_and_quotes_what_it_read():
    """A modulo would move the contact by hours and leave every other check passing."""
    octets = (REFUSALS / "time_beyond_one_day.cat021").read_bytes()
    with pytest.raises(Cat021ParseError) as raised:
        _adapter().to_cdm(octets)
    message = str(raised.value)
    assert "I021/071" in message
    assert "12800000" in message, "the refusal must quote the raw wire integer"
    assert "86400" in message
    assert "modulo" in message


def test_the_raw_time_integers_are_parked_because_milliseconds_cannot_hold_them():
    """1/128 s is 7.8125 ms — not a whole number of milliseconds, so a rendered timestamp loses it."""
    entity = _entity("airborne_position_time_of_applicability")
    assert entity.attributes["cat021_times"] == {"I021/071": 2851840}
    # And the proof that it matters: three units is 23.4375 ms and renders as .023.
    instant, _ = cat021._resolve_instant(3 * cat021.TIME_LSB_SECONDS, times.FROZEN_NOW)
    assert times.render(instant).endswith(".023Z")


def test_the_adapter_never_reads_the_wall_clock():
    """Two runs with two frozen clocks must differ ONLY where the clock legitimately enters."""
    early = _event("airborne_position_time_of_applicability",
                   now=_dt.datetime(2026, 4, 29, 6, 15, tzinfo=_dt.timezone.utc))
    late = _event("airborne_position_time_of_applicability",
                  now=_dt.datetime(2026, 4, 29, 7, 0, tzinfo=_dt.timezone.utc))
    assert early.received_at != late.received_at
    assert early.observed_at == late.observed_at, "a stated time must not follow our clock"


# ====================================================================== position

def test_the_high_resolution_item_wins_when_a_record_carries_both():
    entity = _entity("airborne_position_coarse_and_high_resolution")
    assert entity.attributes["cat021_position"]["item"] == "I021/131"
    assert "Both I021/130 and I021/131 were present" in entity.attributes["position_basis"]
    # They agree here to within rounding, so no disagreement may be claimed.
    assert "position_disagreement_deg" not in entity.attributes


def test_a_real_disagreement_between_the_two_position_items_is_recorded_not_averaged():
    """Beyond one coarse LSB is more than rounding can explain, and it is the source's to explain."""
    items = {
        "I021/130": {"latitude_raw": round(57.5981 / cat021.LSB_130_DEGREES),
                     "longitude_raw": round(23.8412 / cat021.LSB_130_DEGREES)},
        "I021/131": {"latitude_raw": round(57.7000 / cat021.LSB_131_DEGREES),
                     "longitude_raw": round(23.8412 / cat021.LSB_131_DEGREES)},
    }
    apart = cat021._position_disagreement(items)
    assert apart is not None and apart == pytest.approx(0.1019, abs=1e-3)


def test_the_position_is_the_specifications_own_lsb_computed_here():
    """2 cm resolution, and the arithmetic is done in this file rather than read out of the adapter."""
    entity = _entity("airborne_position_time_of_applicability")
    raw = entity.attributes["cat021_position"]
    assert raw["lsb_deg"] == 180.0 / (2 ** 30)
    # Position.lat is rounded to ten decimals so a golden file is stable; 1e-10 deg is
    # 0.011 mm, three orders below this item's own 2 cm LSB.
    assert entity.position.lat == pytest.approx(raw["latitude_raw"] * 180.0 / (2 ** 30), abs=1e-9)
    assert entity.position.lat == pytest.approx(57.5981, abs=1e-7)
    assert entity.position.lon == pytest.approx(23.8412, abs=1e-7)


def test_the_geometric_height_maps_and_the_flight_level_does_not():
    """I021/140 states its own reference surface; I021/145 is a pressure altitude — gap 9."""
    entity = _entity("airborne_position_time_of_applicability")
    assert entity.position.alt_m == pytest.approx(7600 * 0.3048, abs=1e-6)
    assert entity.attributes["flight_level"] == 250.0
    assert "baro_altitude_ft" not in entity.attributes, \
        "converging on adsb.py's key would repeat gap 1's mistake"


def test_accuracy_and_confidence_are_never_filled_from_a_category_or_a_bound():
    """PIC hands over a bound in nautical miles and it is STILL not a 1-sigma metre figure."""
    entity = _entity("quality_indicators_without_mops_version")
    assert entity.position.accuracy_m is None
    assert entity.confidence is None
    assert entity.attributes["position_integrity_category_bound"] == "< 0.1 NM"


def test_the_quality_reading_is_undetermined_without_the_mops_version():
    entity = _entity("quality_indicators_without_mops_version")
    assert entity.attributes["quality_basis"].startswith("UNDETERMINED")
    assert "mops_version" not in entity.attributes


def test_the_quality_reading_names_its_version_when_one_is_stated():
    entity = _entity("airborne_position_time_of_applicability")
    assert entity.attributes["mops_version"] == 2
    assert "NACv / NIC" in entity.attributes["quality_basis"]


# ====================================================================== identity

def test_the_icao_address_is_the_source_id_when_atp_says_it_is_one():
    entity = _entity("airborne_position_time_of_applicability")
    assert [(s.system, s.external_id) for s in entity.source_ids] == [("ICAO24", "0029C1")]
    assert entity.attributes["address_type"] == "24-bit ICAO address"


@pytest.mark.parametrize("fixture,expected", [
    ("surface_vehicle_with_ref_ground_vector", "surface vehicle address"),
    ("duplicate_address", "duplicate address"),
    ("obstacle_line", "anonymous address"),
])
def test_a_non_icao_address_goes_to_a_pool_that_cannot_fuse_with_an_airframe(fixture, expected):
    entity = _entity(fixture)
    assert entity.source_ids[0].system == "ADSB_NONICAO"
    assert entity.attributes["address_type"] == expected


def test_a_duplicate_address_carries_the_caveat_one_record_cannot_resolve():
    entity = _entity("duplicate_address")
    caveat = entity.attributes["identity_caveat"]
    assert "may conflate two airframes" in caveat and "not unique on the wire" in caveat
    # And it must NOT collide with the genuine airframe of the same number.
    genuine = _entity("icao24_shared_with_adsb")
    assert entity.entity_id != genuine.entity_id


def test_a_reserved_address_type_is_pooled_rather_than_refused():
    """adsb.py refuses DF18 CF 3/4/7 because the ME LAYOUT changes; here only the NAME does."""
    items = {"I021/040": {"address_type": 6}}
    assert cat021._source_id_system(items)[0] == "ADSB_NONICAO"


def test_the_same_airframe_gets_the_same_entity_id_from_cat021_and_from_adsb():
    """The single largest reason this adapter is worth having, asserted rather than asserted-in-prose.

    Address 0029C1 arrives here in an ASTERIX record and in adsb.py as a 1090ES frame. Both file
    it under ICAO24, so `ids.derive` agrees across two wire formats without the two adapters
    coordinating — which is what makes a fusion layer's join work at all.
    """
    from_cat021 = _entity("icao24_shared_with_adsb")
    adsb_frame = (PACKAGE / "fixtures" / "adsb"
                  / "airborne_position_baro_gulf_of_riga.adsb").read_bytes()
    adsb_objects = AdsbAdapter(clock=times.frozen_clock(times.FROZEN_NOW)).to_cdm(adsb_frame)
    from_adsb = next(o for o in adsb_objects if isinstance(o, Entity))

    assert from_cat021.source_ids[0].external_id == from_adsb.source_ids[0].external_id
    assert from_cat021.source_ids[0].system == from_adsb.source_ids[0].system == "ICAO24"
    assert from_cat021.entity_id == from_adsb.entity_id
    # The provenance still says which wire format each copy arrived over.
    assert from_cat021.source.system == "ASTERIX_CAT021"
    assert from_adsb.source.system == "ADSB"


def test_the_target_identification_does_not_borrow_adsbs_callsign_key():
    """The divergence FORMAT_COVERAGE.md states: same string, two keys, deliberately.

    I021/170 is flight-plan identification OR registration marking with no bit saying which, so
    the key adsb.py and tak.py share would assert the first reading about half the time.
    """
    entity = _entity("airborne_position_time_of_applicability")
    assert entity.attributes["target_identification"] == "EXRCS01"
    assert entity.attributes["target_identification_raw"] == "EXRCS01 "
    assert "callsign" not in entity.attributes


def test_the_mode_a_code_does_borrow_adsbs_key_because_it_means_one_thing():
    entity = _entity("airborne_position_time_of_applicability")
    assert entity.attributes["mode_a_code"] == "4271"
    assert entity.attributes["mode_a_code_raw"] == 0o4271
    # Not a SourceId: a squawk identifies a FLIGHT and is reassigned after it.
    assert all(s.external_id != "4271" for s in entity.source_ids)


def test_the_track_number_is_parked_and_is_not_an_identifier():
    entity = _entity("spare_bits_nonzero")
    assert entity.attributes["track_number"] == 1234
    assert all(s.external_id != "1234" for s in entity.source_ids)


# ============================================================= emitter category

def test_every_emitter_category_code_is_accounted_for():
    """No silent omissions: every code 0-255 resolves to a decision, and the reserved ones say so."""
    for code in range(256):
        items = {"I021/020": {"emitter_category": code}}
        kind = cat021._entity_type(items)
        assert kind in (EntityType.PLATFORM, EntityType.FACILITY)
        if code in (22, 23, 24):
            assert kind is EntityType.FACILITY, f"{code} is an obstacle"
        else:
            assert kind is EntityType.PLATFORM, f"{code} must not invent a finer distinction"
        if code in cat021.EMITTER_CATEGORY_RESERVED or code not in cat021.EMITTER_CATEGORY:
            assert "emitter_category" in cat021._unresolved_raw(items)


def test_an_obstacle_is_a_facility_and_agrees_with_adsb_through_another_vocabulary():
    entity = _entity("obstacle_line")
    assert entity.entity_type is EntityType.FACILITY
    assert entity.attributes["emitter_category_text"] == "line obstacle"


def test_category_zero_is_a_stated_absence_and_not_category_zero():
    items = {"I021/020": {"emitter_category": 0}}
    assert "emitter_category" in cat021._unavailable_fields(items)
    assert "emitter_category" not in cat021._unresolved_raw(items)


# ================================================================ emergency and severity

def test_the_priority_status_emergency_raises_an_alert():
    event = _event("emergency_unlawful_interference")
    assert event.event_type is EventType.ALERT
    assert event.severity is Severity.CRITICAL
    assert "unlawful interference" in event.payload["severity_basis"]


def test_a_version_three_emergency_is_only_visible_through_the_ref():
    """THE fixture that justifies the REF decision.

    I021/200's priority status is ZERO on this record because it is superseded for a Version 3
    system; the emergency is in REF/STA/PS3. An adapter that skipped the REF would translate an
    aircraft in distress as an ordinary track update.
    """
    entity = _entity("version_three_emergency_in_ref")
    event = _event("version_three_emergency_in_ref")
    assert entity.attributes["mops_version"] == 3
    assert event.event_type is EventType.ALERT
    assert event.severity is Severity.CRITICAL
    assert "REF/STA" in event.payload["severity_basis"]
    assert entity.attributes["priority_status_v3_text"] == \
        "aircraft in distress - manual activation"


def test_the_version_three_mapping_is_never_run_in_reverse():
    """6 and 7 both collapse to 1, so inferring a distress activation mode from a 1 invents one."""
    entity = _entity("version_three_emergency_in_ref")
    assert entity.attributes["priority_status_v3_legacy_equivalent"] == 1
    assert cat021.PRIORITY_STATUS_V3_TO_LEGACY[6] == cat021.PRIORITY_STATUS_V3_TO_LEGACY[7] == 1


@pytest.mark.parametrize("status,expected", [
    ({"surveillance_status": 1}, True),
    ({"surveillance_status": 2}, False),
    ({"surveillance_status": 3}, False),
    ({"military_emergency": 1}, True),
    ({"priority_status": 0}, False),
    ({"priority_status": 6}, True),
])
def test_the_severity_line_is_drawn_at_the_standards_own_declaration(status, expected):
    """A temporary alert and an SPI pulse are procedural conditions, not emergencies."""
    assert cat021._emergency({"I021/200": status})[0] is expected


def test_no_emergency_records_the_formats_silence_and_not_a_judgement():
    event = _event("airborne_position_time_of_applicability")
    assert event.severity is Severity.INFO
    assert "SILENT" in event.payload["severity_basis"]


def test_a_record_with_neither_position_nor_motion_is_a_status_change():
    """Calling it a track update would claim a position it does not carry."""
    entity = _entity("mode_five_authenticated")
    assert entity.position is not None          # this one HAS a position, so:
    items = {"I021/080": {"target_address": 0x0029F2}, "I021/040": {"address_type": 0},
             "I021/010": {"sac": 0x29, "sic": 0x29}, "I021/090": {}}
    record = {"index": 0, "fspec": "00", "items": items, "item_octets": {}}
    objects = _adapter()._record_to_cdm(record, {}, _adapter().source_ref(), times.FROZEN_NOW)
    assert next(o for o in objects if isinstance(o, Event)).event_type is EventType.STATUS_CHANGE


# =============================================================== affiliation and Mode 5

@pytest.mark.parametrize("path", BLOCK_FIXTURES, ids=lambda p: p.stem)
def test_affiliation_is_unknown_on_every_record(path):
    for obj in _adapter().to_cdm(path.read_bytes()):
        if isinstance(obj, Entity):
            assert obj.affiliation is Affiliation.UNKNOWN
            assert obj.symbol is not None and len(obj.symbol) == 20


def test_an_authenticated_mode_five_reply_is_not_read_as_an_identification():
    """A test that asserts a REFUSAL TO DECIDE, which is the point.

    An authenticated Mode 5 reply is what "friend" means in IFF doctrine. Reading it as FRIENDLY
    would be an adjudication, and over-claiming FRIENDLY from a translator is the
    fratricide-adjacent direction.
    """
    entity = _entity("mode_five_authenticated")
    assert entity.affiliation is Affiliation.UNKNOWN
    basis = entity.attributes["affiliation_basis"]
    assert "AUTHENTICATED Mode 5" in basis
    assert "not adjudicated" in basis
    assert "gap 2" in basis

    summary = entity.attributes["source_extras"]["items"]["RE"]["items"]["MES"]["mode_5_summary"]
    assert summary["authenticated_mode_5_id"] == 1
    assert summary["authenticated_mode_5_data"] == 1


def test_an_ordinary_record_says_why_unknown_without_claiming_an_attestation():
    basis = _entity("airborne_position_time_of_applicability").attributes["affiliation_basis"]
    assert "unauthenticated cooperative broadcast" in basis
    assert "AUTHENTICATED Mode 5" not in basis


# ====================================================== the ground station's own verdicts

def test_a_range_check_failure_is_translated_in_full_and_never_filtered():
    """The specification asks for suppression; the Adapter contract forbids it.

    A fixture that produced no objects would mean the adapter had started making suppression
    decisions where nothing can audit them.
    """
    objects = _objects("range_check_failed_still_translated")
    assert len([o for o in objects if isinstance(o, Entity)]) == 1
    entity = _entity("range_check_failed_still_translated")
    assert entity.attributes["range_check_failed"] is True
    assert "SUPPRESS" in entity.attributes["range_check_note"]
    assert entity.attributes["confidence_level"] == "report suspect"
    # And "suspect" does not become a number.
    assert entity.confidence is None
    assert entity.position is not None


def test_a_simulated_target_flag_never_rewrites_the_feed_level_synthetic_declaration():
    """A payload field may not flip a deployment declaration — the Legion EXERCISE_* rule."""
    live = AsterixCat021Adapter(clock=times.frozen_clock(times.FROZEN_NOW), synthetic=False)
    objects = live.to_cdm((FIXTURES / "airborne_position_time_of_applicability.cat021").read_bytes())
    entity = next(o for o in objects if isinstance(o, Entity))
    assert entity.source.synthetic is False


def test_the_lnav_inversion_is_applied_once_and_the_raw_bit_survives():
    """The item's logic is REVERSED relative to DO-260: 0 means engaged."""
    assert cat021._lnav({"lnav_mode_raw": 0}) is True
    assert cat021._lnav({"lnav_mode_raw": 1}) is False
    entity = _entity("emergency_unlawful_interference")
    assert entity.attributes["lnav_mode_engaged"] is False
    assert entity.attributes["source_extras"]["items"]["I021/200"]["lnav_mode_raw"] == 1


# ============================================================== the REF and surface motion

def test_a_surface_target_has_motion_only_because_the_ref_is_in_scope():
    entity = _entity("surface_vehicle_with_ref_ground_vector")
    assert "I021/160" not in entity.attributes["cat021_items"], \
        "the airborne ground vector must be absent, or this fixture proves nothing"
    assert entity.kinematics is not None
    assert entity.kinematics.speed_mps == pytest.approx(12.0 * 1852.0 / 3600.0, abs=0.05)
    assert entity.kinematics.course_deg == pytest.approx(236.25, abs=0.01)
    assert entity.attributes["surface_angle_kind"] == "ground track"
    assert entity.attributes["heading_reference"] == "true north"


def test_stopped_is_a_measurement_of_stillness_and_an_invalid_track_is_an_absence():
    """Two absences of different kinds in one item, which is why they are two mechanisms."""
    entity = _entity("surface_stopped_track_invalid")
    assert entity.kinematics.speed_mps == 0.0, "stopped is 0.0 m/s, not null"
    assert entity.kinematics.course_deg is None, "an invalid heading/track is absent"
    assert "surface_heading_track" in entity.attributes["unavailable_fields"]
    # The real-looking angle survives in the parked octets rather than being discarded.
    assert "SGV" in entity.attributes["source_extras"]["items"]["RE"]["item_octets"]


def test_a_heading_is_not_a_course_even_when_it_is_valid():
    """HTT decides which of the two the same seven bits carry, and only a ground track is a course."""
    items = {"RE": {"items": {"SGV": {"aircraft_stopped": 0, "heading_track_valid": 1,
                                      "heading_track_is_ground_track": 0,
                                      "ground_speed_raw": 96, "heading_track_raw": 84}}}}
    kinematics = cat021._kinematics(items)
    assert kinematics.speed_mps is not None
    assert kinematics.course_deg is None


def test_the_true_north_heading_is_the_datum_gap_seven_asked_for():
    """CAT021 states a magnetic heading and a true-north one as SEPARATE items."""
    items = {"I021/152": {"magnetic_heading_raw": 12743},
             "I021/080": {"target_address": 0x0029F7},
             "RE": {"items": {"TNH": {"true_north_heading_raw": 14200}}}}
    record = {"index": 0, "fspec": "00", "items": items, "item_octets": {}}
    attributes = cat021._attributes(record, {}, ("index", "fspec", "item_octets"),
                                    observed_basis="x")
    assert attributes["magnetic_heading_deg"] == pytest.approx(70.0, abs=0.01)
    assert attributes["true_north_heading_deg"] == pytest.approx(78.0, abs=0.01)


# ============================================================ multiple records, no grouping

def test_two_records_in_one_block_become_two_entities_and_not_one_track():
    """Several records are several TARGET REPORTS. Grouping them would be correlation."""
    objects = _objects("two_records_one_block")
    entities = [o for o in objects if isinstance(o, Entity)]
    events = [o for o in objects if isinstance(o, Event)]
    assert len(entities) == 2 and len(events) == 2
    assert not any(isinstance(o, Track) for o in objects), \
        "a data block is never a Track on ingest"
    assert entities[0].entity_id != entities[1].entity_id
    assert [e.attributes["cat021_record_index"] for e in entities] == [0, 1]
    assert all(e.payload["cat021_record_count"] == 2 for e in events)


def test_two_records_naming_one_address_still_do_not_become_a_track():
    """The heuristic that would be tempting, declined by name."""
    generator = FIXTURES / "spec" / "build_fixtures.py"
    assert "Grouping the ones that agree" in generator.read_text()


# ========================================================================= egress

def test_emitting_an_object_that_never_came_from_cat021_needs_a_configured_station():
    """I021/010 is mandatory and names a station whose SAC EUROCONTROL allocates centrally."""
    entity = Entity(
        source=_adapter().source_ref(), entity_id=ids.derive("ICAO24", "0029F1"),
        source_ids=[{"system": "ICAO24", "external_id": "0029F1"}],
        entity_type=EntityType.PLATFORM, affiliation=Affiliation.UNKNOWN,
        position=Position(lat=57.0, lon=23.0, position_source=PositionSource.GNSS),
        valid_from=times.FROZEN_NOW,
    )
    with pytest.raises(ValueError, match="EUROCONTROL allocates centrally"):
        _adapter().from_cdm([entity])
    emitted = _adapter(station=STATION).from_cdm([entity])
    parsed = cat021._parse_block(emitted)
    assert parsed["records"][0]["items"]["I021/010"] == {"sac": 0x29, "sic": 0x29}


def test_emitting_without_an_address_is_refused_rather_than_derived():
    entity = Entity(
        source=_adapter().source_ref(), entity_id=ids.derive("LEGION", "abc"),
        source_ids=[{"system": "LEGION", "external_id": "abc"}],
        entity_type=EntityType.PLATFORM, affiliation=Affiliation.UNKNOWN,
        valid_from=times.FROZEN_NOW,
    )
    with pytest.raises(ValueError, match="nobody allocated"):
        _adapter(station=STATION).from_cdm([entity])


def test_an_altitude_outside_the_items_range_is_refused_rather_than_clipped():
    """A cruise level clipped to a range bound reads as a real altitude to every consumer."""
    entity = Entity(
        source=_adapter().source_ref(), entity_id=ids.derive("ICAO24", "0029F3"),
        source_ids=[{"system": "ICAO24", "external_id": "0029F3"}],
        entity_type=EntityType.PLATFORM, affiliation=Affiliation.UNKNOWN,
        position=Position(lat=57.0, lon=23.0, alt_m=60000.0,
                          position_source=PositionSource.GNSS),
        valid_from=times.FROZEN_NOW,
    )
    with pytest.raises(ValueError, match="Refusing rather than clipping"):
        _adapter(station=STATION).from_cdm([entity])


def test_a_track_becomes_one_block_of_many_records():
    """The shape CAT021 has for a history and 1090ES did not — and each sample's TIME travels."""
    samples = [
        TrackSample(position=Position(lat=57.5981 + i * 0.01, lon=23.8412,
                                      position_source=PositionSource.GNSS),
                    observed_at=_dt.datetime(2026, 4, 29, 6, 11, 20 + i * 10,
                                             tzinfo=_dt.timezone.utc))
        for i in range(3)
    ]
    track = Track(
        source=_adapter().source_ref(), track_id=ids.derive("ICAO24", "0029F4", kind="track"),
        entity_id=ids.derive("ICAO24", "0029F4"),
        source_ids=[{"system": "ICAO24", "external_id": "0029F4"}], samples=samples,
    )
    emitted = _adapter(station=STATION).from_cdm([track])
    parsed = cat021._parse_block(emitted)
    assert parsed["block"]["record_count"] == 3
    stated = [record["items"]["I021/071"]["time_of_day_raw"] * cat021.TIME_LSB_SECONDS
              for record in parsed["records"]]
    assert stated == [6 * 3600 + 11 * 60 + 20 + i * 10 for i in range(3)]


def test_a_re_ingested_track_block_carries_the_times_but_not_the_date():
    """The date cannot travel: CAT021 states none, and a receiver dates against its own midnight."""
    samples = [TrackSample(position=Position(lat=57.5981, lon=23.8412,
                                             position_source=PositionSource.GNSS),
                           observed_at=_dt.datetime(2026, 1, 2, 6, 11, 20,
                                                    tzinfo=_dt.timezone.utc))]
    track = Track(
        source=_adapter().source_ref(), track_id=ids.derive("ICAO24", "0029F5", kind="track"),
        entity_id=ids.derive("ICAO24", "0029F5"),
        source_ids=[{"system": "ICAO24", "external_id": "0029F5"}], samples=samples,
    )
    emitted = _adapter(station=STATION).from_cdm([track])
    back = _adapter().to_cdm(emitted)
    event = next(o for o in back if isinstance(o, Event))
    assert event.observed_at.time() == samples[0].observed_at.time()
    assert event.observed_at.date() != samples[0].observed_at.date(), \
        "the DATE is the receiving clock's, which is the documented limit of this direction"


def test_a_non_icao_address_is_not_re_emitted_as_an_icao_one():
    """ATP 0 would tell every downstream system the number IS an ICAO24 address."""
    entity = _entity("surface_vehicle_with_ref_ground_vector")
    stripped = entity.model_copy(update={"attributes": {
        k: v for k, v in entity.attributes.items()
        if k not in ("cat021_items", "cat021_fspec", "address_type_raw")}})
    emitted = _adapter(station=STATION).from_cdm([stripped])
    parsed = cat021._parse_block(emitted)
    assert parsed["records"][0]["items"]["I021/040"]["address_type"] == 3


def test_emitting_a_history_and_separate_reports_together_is_refused():
    track = Track(
        source=_adapter().source_ref(), track_id=ids.derive("ICAO24", "0029F6", kind="track"),
        entity_id=ids.derive("ICAO24", "0029F6"),
        source_ids=[{"system": "ICAO24", "external_id": "0029F6"}],
        samples=[TrackSample(position=Position(lat=57.0, lon=23.0,
                                               position_source=PositionSource.GNSS),
                             observed_at=times.FROZEN_NOW)],
    )
    entities = [o for o in _objects("two_records_one_block") if isinstance(o, Entity)]
    with pytest.raises(ValueError, match="cannot share one block"):
        _adapter(station=STATION).from_cdm([track] + entities)


def test_nothing_emittable_is_refused_by_name():
    event = _event("airborne_position_time_of_applicability")
    with pytest.raises(ValueError, match="nothing emittable"):
        _adapter(station=STATION).from_cdm([event])


# ======================================================================= refusals

def test_a_wrong_category_is_refused_and_says_why():
    with pytest.raises(Cat021ParseError, match="category 62"):
        _adapter().to_cdm((REFUSALS / "wrong_category.cat021").read_bytes())


def test_a_length_that_disagrees_with_the_buffer_is_refused_and_quotes_the_header():
    with pytest.raises(Cat021ParseError) as raised:
        _adapter().to_cdm((REFUSALS / "length_disagrees_with_buffer.cat021").read_bytes())
    assert "Header:" in str(raised.value)


def test_an_fspec_bit_on_a_not_used_frn_is_refused_and_quotes_the_octets():
    with pytest.raises(Cat021ParseError) as raised:
        _adapter().to_cdm((REFUSALS / "fspec_names_a_not_used_frn.cat021").read_bytes())
    message = str(raised.value)
    assert "FRN 43" in message and "Not Used" in message
    assert "at octet" in message, "a refusal must quote the offending bytes"


def test_a_record_missing_a_mandatory_item_is_refused():
    with pytest.raises(Cat021ParseError) as raised:
        _adapter().to_cdm((REFUSALS / "missing_mandatory_target_address.cat021").read_bytes())
    assert "I021/080" in str(raised.value)
    assert "no checksum" in str(raised.value)


@pytest.mark.parametrize("path", sorted(REFUSALS.glob("*.cat021")), ids=lambda p: p.stem)
def test_every_refusal_quotes_bytes_and_never_falls_back_to_the_clock(path):
    """The constraint that outranks convenience: unparseable input raises, never a fallback."""
    with pytest.raises(Cat021ParseError) as raised:
        _adapter().to_cdm(path.read_bytes())
    message = str(raised.value)
    assert any(token in message for token in
               ("at octet", "Header:", "First octets:", "units of 1/128 s")), \
        f"{path.stem}: the refusal quotes no bytes"


def test_a_payload_of_the_wrong_python_type_is_refused_rather_than_coerced():
    with pytest.raises(Cat021ParseError, match="this adapter reads the octets"):
        _adapter().to_cdm("21 00 10")


# ================================================================ never-drop and gaps

def test_transforms_is_empty_and_the_lossless_check_therefore_runs_at_full_strength():
    """The claim in the class docstring: a verbatim copy is not a hole, an exemption is."""
    assert AsterixCat021Adapter.TRANSFORMS == {}
    for path in PARSED_FIXTURES:
        parsed = json.loads(path.read_text())
        dumped = [o.model_dump(mode="json") for o in _adapter().to_cdm(parsed)]
        assert lossless.unrepresented(parsed, dumped, {}) == {}, path.stem


def test_the_two_absence_lists_stay_two_facts():
    """"The source said it does not know" and "we could not use what it said" are different."""
    entity = _entity("surface_stopped_track_invalid")
    assert "surface_heading_track" in entity.attributes["unavailable_fields"]
    reserved = _entity("reserved_full_second_indication")
    assert "unavailable_fields" not in reserved.attributes
    assert reserved.attributes["unresolved_raw"]


def test_the_data_ages_are_parked_and_the_ceiling_is_a_floor():
    """Gap 13's evidence: per-item staleness the CDM has nowhere to put. 25.5 s means "or above"."""
    entity = _entity("spare_bits_nonzero")
    ages = entity.attributes["source_extras"]["items"]["I021/295"]["data_ages"]
    assert ages["geometric_height"]["age_s"] == 2.5
    assert ages["ground_vector"]["age_s"] == 25.5
    assert ages["ground_vector"]["at_or_above_maximum"] is True
    assert ages["geometric_height"]["at_or_above_maximum"] is None


def test_the_trajectory_intent_is_parked_and_never_becomes_a_geometry():
    """Gap 15: a LineString in Event.geometry would paint a declared future as an observation."""
    entity = _entity("trajectory_intent_two_points")
    event = _event("trajectory_intent_two_points")
    points = entity.attributes["source_extras"]["items"]["I021/110"]["trajectory_intent_points"]
    assert len(points) == 2, "the fifteen-octet stride is what this fixture pins"
    assert points[0]["tcp_number"] == 0 and points[1]["tcp_number"] == 1
    assert points[0]["altitude_raw"] * 10 == 24000
    assert points[0]["time_over_point_s"] == 22500
    assert event.geometry is None


def test_the_ground_station_is_parked_and_is_not_a_source_id():
    """Gap 14: the sensor that produced the report has no canonical home."""
    entity = _entity("airborne_position_time_of_applicability")
    assert entity.attributes["data_source"] == {"sac": 0x29, "sic": 0x29}
    assert entity.attributes["receiver_id"] == 7
    assert all(s.system in ("ICAO24", "ADSB_NONICAO") for s in entity.source_ids)


def test_the_integrity_basis_says_this_format_has_no_checksum():
    """A consumer comparing a CAT021 contact with a 1090ES one must see which was checked."""
    basis = _entity("airborne_position_time_of_applicability").attributes["integrity_basis"]
    assert "NO checksum" in basis and "PARSED" in basis


# ======================================================================= harness

def test_the_harness_passes_every_fixture_against_the_published_schemas():
    from synapse_cdm import harness

    report = harness.run(_adapter(), FIXTURES, schema_dir=SCHEMAS)
    assert report["failed"] == 0, harness.render_report(report)
    assert report["passed"] >= 38

    for result in report["results"]:
        checks = result["checks"]
        assert checks["translate"] == "PASS", result
        assert checks["schema"] == "PASS", result
        assert checks["provenance"] == "PASS", result
        assert checks["golden"] == "PASS", result
        # The lossless check runs on the parsed twins and can only SKIP on the raw blocks, which
        # have no leaf structure to harvest. Asserting the SPLIT rather than accepting "not
        # FAIL" is what stops a blocks-only fixture set from quietly disabling the never-drop
        # rule.
        expected = "PASS" if result["fixture"].endswith(".parsed.json") else "SKIP"
        assert checks["lossless"] == expected, result


def test_the_harness_does_not_pick_up_the_spec_or_refusal_directories():
    """`run()` replays every FILE through `to_cdm()`, so the pin and the refusals must be nested."""
    from synapse_cdm import harness

    report = harness.run(_adapter(), FIXTURES, schema_dir=SCHEMAS)
    names = {result["fixture"] for result in report["results"]}
    assert "sac_pin.json" not in names
    assert "build_fixtures.py" not in names
    assert not any(name.startswith("time_beyond") for name in names)
