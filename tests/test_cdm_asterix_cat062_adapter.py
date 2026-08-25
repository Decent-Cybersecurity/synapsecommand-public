"""ASTERIX CAT062 — the adapter against the row set that specified it. Adapter #13.

Every assertion here is scoped to a NAMED table, a NAMED settlement or a NAMED fixture rather than
to the document as a whole, per the testing protocol: a section-wide substring check passes by luck
when the phrase happens to appear somewhere else, and the CAT062 section is over a thousand lines
long — the largest in this document.

THE ROUND TRIP IS TESTED HERE AND NOT BY THE HARNESS
-----------------------------------------------------
`harness._check_roundtrip` reports SKIP for an adapter whose `from_cdm` returns non-JSON bytes and
says in as many words that "the adapter must ship its own round-trip test in tests/". This is it,
and it is stronger than the harness's value-presence comparison: it asserts BYTE EQUALITY on every
fixture in the set.

THE THREE THINGS A GREEN HARNESS RUN CANNOT TELL YOU, AND WHERE EACH IS ANSWERED
--------------------------------------------------------------------------------
`packages/cdm/synapse_cdm/README.md` names them and all three bite here.

* **A fixture invariant under the harness clock exercises nothing.** `midnight_rollover_nearest` is
  built so the backward wrap happens under `times.FROZEN_NOW` itself; the forward wrap is
  unreachable from a 06:15 receipt time and is asserted below against a clock this module injects.
* **A round trip proves self-consistency, never correctness.** This adapter has ONE derive/invert
  pair with a shared model behind it — `degrees_to_metres`, which turns two angular standard
  deviations into one metric scalar — and it is NOT inverted anywhere: egress re-emits the parked
  raw components. That absence is asserted rather than assumed, because a round trip through a
  shared model proves only that the model is self-consistent. Every other scale factor is a single
  stated LSB, checkable against §5.2 by eye.
* **The roster sweep is a manual protocol act.** Not this module's job.

WHAT THIS MODULE IS FOR THAT THE CAT034 ONE WAS NOT
----------------------------------------------------
Settlement 1. This is the first adapter whose input is already a fused product, and the whole risk
is that it quietly co-signs the upstream system's conclusions. Six named refusals are asserted
individually below, because every one of them is a thing that would pass every check in the harness
if it were violated: the values would all be present, the schema would validate, and the round trip
would hold.
"""
import datetime as dt
import json
import pathlib
import re
import types

import pytest

import synapse_cdm
from synapse_cdm import ids, times
from synapse_cdm.adapters import cat062_codec as codec
from synapse_cdm.adapters.asterix_cat062 import (
    ALWAYS_MANDATORY, CATEGORY, ECAT_TEXT, EMS_TEXT, ENCODERS, FRN_BY_ITEM, ICAO24_SYSTEM,
    IMPLEMENTATION_DEPENDENT, PS3_BACK_MAPPING, PS3_TEXT, REPORT_SYSTEM, SRC_TEXT, UAP,
    UAP_BY_FRN, VFI_TEXT, AsterixCat062Adapter, Cat062ParseError, build_block, parse_block,
)
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import Entity, Event, Track, TrackSample

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
DOC = PACKAGE / "FORMAT_COVERAGE.md"
FIXTURES = PACKAGE / "fixtures" / "cat062"
REFUSALS = FIXTURES / "refusals"
GOLDEN = FIXTURES / "golden"

#: The frozen clock every golden file was written against — `times.FROZEN_NOW`, 06:15 UTC.
CLOCK = times.frozen_clock()


def adapter(**kwargs):
    return AsterixCat062Adapter(clock=CLOCK, **kwargs)


def blocks():
    return sorted(FIXTURES.glob("*.cat062"))


def block_of(name: str) -> bytes:
    return (FIXTURES / f"{name}.cat062").read_bytes()


def translate(name: str, **kwargs):
    return adapter(**kwargs).to_cdm(block_of(name))


def entity_of(name: str, index: int = 0, **kwargs) -> Entity:
    return [o for o in translate(name, **kwargs) if isinstance(o, Entity)][index]


def event_of(name: str, index: int = 0, **kwargs) -> Event:
    return [o for o in translate(name, **kwargs) if isinstance(o, Event)][index]


def _section() -> str:
    """The CAT062 section, ending at the NEXT top-level heading.

    Not a named terminator: a later adapter's section will be written after this one, exactly as
    CAT023's was, and a named terminator is what makes a section check quietly cover the wrong text
    when that happens.
    """
    text = DOC.read_text()
    start = text.index("## ASTERIX Category 062")
    nxt = text.find("\n## ", start + 10)
    return text[start:nxt if nxt != -1 else len(text)]


def _table(heading: str) -> list[str]:
    """The data rows of the table(s) under one heading, and nothing else.

    Scoped by heading so an assertion cannot pass on a row from a different table — this section
    has seventeen mapping tables and `Entity.attributes` appears in fourteen of them.
    """
    section = _section()
    start = section.index(heading)
    nxt = section.find("\n### ", start + len(heading))
    body = section[start:nxt if nxt != -1 else len(section)]
    return [line for line in body.splitlines()
            if line.startswith("|") and not line.startswith("|---")]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _build_fixtures_module():
    """The generator, loaded from its SOURCE — never from bytecode.

    `spec_from_file_location` + `exec_module` runs the ordinary source loader, which consults and
    writes `__pycache__`, and a `.pyc` is revalidated on the source's mtime in whole seconds and
    its size — so a same-length edit reverted inside one second leaves a cache that validates
    against a file it was not compiled from. `tests/test_cdm_generator_loading.py` holds every site
    to this behaviour by poisoning a cache and requiring the source to win.
    """
    path = FIXTURES / "spec" / "build_fixtures.py"
    name = "cat062_build_fixtures"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


# ============================================================== the codec, form by form

#: (form, the LSB §5.2 states for it). Every scaled field in the category, checked against the
#: document's own figure rather than against the codec's arithmetic.
STATED_LSBS = [
    ("tod", 1.0 / 128.0), ("latitude_105", 180.0 / (1 << 25)), ("longitude_105", 180.0 / (1 << 25)),
    ("cartesian_m", 0.5), ("velocity_mps", 0.25), ("acceleration_mps2", 0.25),
    ("geometric_altitude", 6.25), ("barometric_altitude", 0.25), ("measured_flight_level", 0.25),
    ("rate_of_climb", 6.25), ("target_length_m", 1.0), ("target_orientation", 360.0 / 128.0),
    ("age_quarter_s", 0.25), ("age_quarter_s_16", 0.25), ("rho", 1.0 / 256.0),
    ("theta", 360.0 / (1 << 16)), ("measured_height", 25.0), ("measured_mode_c", 0.25),
    ("latitude_23", 180.0 / (1 << 23)), ("longitude_23", 180.0 / (1 << 23)),
    ("gnss_altitude", 25.0), ("time_offset", 1.0 / 128.0), ("heading_16", 360.0 / (1 << 16)),
    ("airspeed_nm_s", 2.0 ** -14), ("airspeed_mach", 0.001), ("true_airspeed", 1.0),
    ("selected_altitude", 25.0), ("tid_altitude", 10.0), ("tov", 1.0), ("turn_radius", 0.01),
    ("vertical_rate", 6.25), ("roll_angle", 0.01), ("rate_of_turn", 0.25),
    ("ground_speed", 2.0 ** -14), ("wind_speed", 1.0), ("wind_direction", 1.0),
    ("temperature", 0.25), ("turbulence", 1.0), ("indicated_airspeed", 1.0),
    ("mach_number", 0.008), ("barometric_pressure", 0.1), ("cleared_flight_level", 0.25),
    ("accuracy_position_m", 0.5), ("accuracy_covariance_m", 0.5),
    ("accuracy_position_deg", 180.0 / (1 << 25)), ("accuracy_geometric_altitude", 6.25),
    ("accuracy_barometric_altitude", 0.25), ("accuracy_velocity_mps", 0.25),
    ("accuracy_acceleration_mps2", 0.25), ("accuracy_rate_of_climb", 6.25),
    ("ref_velocity_mps", 0.25),
]


@pytest.mark.parametrize("form,stated", STATED_LSBS)
def test_every_lsb_is_the_documents_own(form, stated):
    assert codec.bounds(form)[2] == stated, (
        f"{form}'s LSB is {codec.bounds(form)[2]!r} and §5.2 states {stated!r}"
    )


def test_the_lsb_table_covers_every_form_the_codec_defines():
    """The closure. A form added without a stated LSB is a scale factor nobody checked."""
    assert {form for form, _ in STATED_LSBS} == set(codec.FORMS), (
        "the LSB table and the codec disagree:\n"
        f"  only in the table: {sorted({f for f, _ in STATED_LSBS} - set(codec.FORMS))}\n"
        f"  only in the codec: {sorted(set(codec.FORMS) - {f for f, _ in STATED_LSBS})}\n"
        "A form with no stated LSB here is a scale factor checked against nothing"
    )


def test_the_four_coordinate_lsbs_are_two_different_quanta_and_are_not_interchangeable():
    """180/2^25 for the tracker's own position, 180/2^23 for everything the aircraft states.

    THE SINGLE EASIEST MISTAKE IN THIS CATEGORY. Four coordinate fields, two quanta a factor of
    four apart, and using the wrong one produces a position off by up to a kilometre that is
    otherwise perfectly well-formed.
    """
    fine = codec.bounds("latitude_105")[2]
    coarse = codec.bounds("latitude_23")[2]
    assert fine * 4 == coarse, (
        f"the two coordinate quanta are {fine!r} and {coarse!r}; §5.2.8 states 180/2^25 for "
        "I062/105 and §5.2.9 and §5.2.24 state 180/2^23 for the Mode 5 and ADS-B positions"
    )
    assert codec.bounds("longitude_105")[2] == fine
    assert codec.bounds("longitude_23")[2] == coarse
    assert codec.bounds("accuracy_position_deg")[2] == fine, (
        "I062/500 Subfield #3's components are at the SAME quantum as I062/105, which is what "
        "makes them commensurable with the position they qualify"
    )


def test_the_stated_ranges_are_preferred_to_the_field_width_where_the_document_prints_one():
    """The three-way bound rule, on the forms where the document's range is narrower."""
    for form, low, high in [("latitude_105", -90.0, 90.0),
                            ("geometric_altitude", -1500.0, 150000.0),
                            ("barometric_altitude", -15.0, 1500.0),
                            ("measured_flight_level", -15.0, 1500.0),
                            ("selected_altitude", -1300.0, 100000.0),
                            ("roll_angle", -180.0, 180.0),
                            ("rate_of_turn", -15.0, 15.0),
                            ("true_airspeed", 0.0, 2046.0),
                            ("wind_speed", 0.0, 300.0),
                            ("temperature", -100.0, 100.0),
                            ("cleared_flight_level", 0.0, 1500.0)]:
        assert codec.bounds(form)[:2] == (low, high), f"{form}'s bound is not the stated range"
        field_low, field_high = codec.width(form)
        assert (field_low, field_high) != (low, high), (
            f"{form}'s field width and its stated range agree, so this row proves nothing about "
            "which was preferred — pick a form where they differ"
        )


def test_wind_directions_low_bound_is_one_and_a_zero_is_refused_rather_than_read_as_north():
    """§5.2.24 SF#20 states `1 <= Wind Direction <= 360`, which excludes zero."""
    assert codec.bounds("wind_direction")[0] == 1.0
    with pytest.raises(codec.CodecError) as raised:
        codec.snap("wind_direction", 0.0)
    assert "the item's own range excludes" in str(raised.value), (
        "the refusal does not distinguish 'the item excludes this' from 'the field cannot express "
        "this', and for a zero in a sixteen-bit unsigned field the difference is the whole finding"
    )


def test_rho_takes_the_field_width_because_the_printed_maximum_is_one_lsb_above_it():
    """§5.2.23 prints "Maximum value = 256 NM" and the field reaches 255.996 093 75.

    The `cat034_codec` `rho` disposition, reached a third time: a bound the encoder cannot honour
    is not a bound. Asserted by showing that the printed figure has NO representable raw.
    """
    low, high, lsb = codec.bounds("rho")
    assert high == 65535 * lsb == 255.99609375
    assert codec.width("rho") == (low, high), "rho's bound is not its field width"
    with pytest.raises(codec.CodecError):
        codec.snap("rho", 256.0)


def test_the_covariance_is_the_one_signed_accuracy_and_its_printed_maximum_is_also_unreachable():
    """§5.2.26 SF#2 NOTE 2 prints 16.383 km and sixteen bits at 0.5 m reach 16 383.5 m."""
    nbits, signed, lsb, low, high, _unit, _locus = codec.FORMS["accuracy_covariance_m"]
    assert signed, "the XY covariance is stated 'in two's complement form'"
    assert (low, high) == codec.width("accuracy_covariance_m")
    assert high == 16383.5 and 16383.0 < high, (
        "the printed 16.383 km is the field's positive extreme minus one LSB, which is why the "
        "width is the bound"
    )
    for name in ("accuracy_position_m", "accuracy_position_deg", "accuracy_geometric_altitude",
                 "accuracy_barometric_altitude", "accuracy_velocity_mps",
                 "accuracy_acceleration_mps2", "accuracy_rate_of_climb"):
        assert not codec.FORMS[name][1], f"{name} is signed and §5.2.26 states no sign for it"


def test_the_time_of_day_bound_is_the_width_and_the_day_bound_is_applied_one_level_up():
    """Settlement 4: §5.2.5 prints NO range, so the codec cannot be the place the day is enforced."""
    assert codec.bounds("tod")[1] == 16777215 / 128.0
    assert codec.bounds("tod")[1] > codec.SECONDS_PER_DAY, (
        "the tod form's bound is already a day, so the item-level refusal below is unreachable "
        "and the CAT034-versus-CAT048 distinction is not being made anywhere"
    )
    # And it does NOT refuse at the day boundary, which is the whole point of the split.
    assert codec.snap("tod", 90000.0) == 90000.0


def test_the_only_model_in_this_codec_is_the_accuracy_combination_and_it_is_declared():
    """A round trip proves self-consistency; a shared model is where that stops being enough.

    Every other scale factor is one stated LSB. `degrees_to_metres` is the exception, and the check
    is that it is (a) the only one and (b) never used in the inverse direction — see the egress
    tests. The constant is asserted here against ICAO's own nautical mile.
    """
    assert codec.METRES_PER_DEGREE == 60.0 * 1852.0 == 111120.0
    assert codec.METRES_PER_NM == 1852.0
    source = (PACKAGE / "adapters" / "cat062_codec.py").read_text()
    # The WORD "Vincenty" is in the docstring, explaining that the arithmetic is not here — so
    # the check is for the arithmetic. A geodesy routine needs an ellipsoid constant and a
    # definition; neither may appear.
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    for marker in ("def vincenty", "FLATTENING", "SEMI_MAJOR", "SEMI_MINOR", "inverse_geodesic",
                   "298.257"):
        assert marker not in code, (
            f"this codec has acquired geodesy ({marker!r}). Settlement 6 declines to invert "
            "I062/100's projection and I062/105 needs none, so an ellipsoid here would be "
            "arithmetic nothing calls — which reads as a capability the adapter has"
        )
    # And the only trigonometry it may use is the one the accuracy combination needs.
    assert source.count("math.cos") == 1 and "math.sin" not in source and \
        "math.atan2" not in source, (
        "trigonometry beyond the cosine `degrees_to_metres` needs has appeared in the codec"
    )


def test_degrees_to_metres_scales_longitude_by_the_cosine_of_the_records_own_latitude():
    at_equator = codec.degrees_to_metres(0.0, 1.0, 0.0)
    at_sixty = codec.degrees_to_metres(0.0, 1.0, 60.0)
    assert round(at_sixty / at_equator, 6) == 0.5, (
        "a degree of longitude at 60° is half a degree at the equator; the cosine scaling is not "
        "being applied, or is being applied to the latitude component"
    )
    # And the two components combine as a hypotenuse rather than a sum or a maximum.
    assert round(codec.degrees_to_metres(3.0 / 111120.0, 4.0 / 111120.0, 0.0), 6) == 5.0


# ==================================================================== the FSPEC and UAP


def test_the_fspec_ceiling_is_five_octets_and_not_the_siblings_four_or_two():
    """Three parts, three ceilings, and importing either sibling's would refuse a legal record."""
    assert codec.MAX_FRN == 35 and codec.MAX_FSPEC_OCTETS == 5
    from synapse_cdm.adapters import cat034_codec, cat048_codec
    assert cat048_codec.MAX_FSPEC_OCTETS == 4 and cat034_codec.MAX_FSPEC_OCTETS == 2, (
        "a sibling's ceiling moved, so the argument in this module's docstring no longer holds"
    )
    # A five-octet FSPEC reaching FRN 34 is legal here and past CAT048's ceiling.
    frns, octets, end = codec.read_fspec(bytes([0x81, 0x01, 0x01, 0x01, 0x04]), 0)
    assert 34 in frns and len(octets) == 5


def test_a_sixth_fspec_octet_is_refused_and_the_message_quotes_this_categorys_own_count():
    with pytest.raises(codec.CodecError) as raised:
        codec.read_fspec(bytes([0x01, 0x01, 0x01, 0x01, 0x01, 0x00]), 0)
    message = str(raised.value)
    assert "35" in message and "FRN 36" in message, (
        f"the refusal does not quote category 062's own slot count: {message}"
    )
    assert "28" not in message and "14" not in message, (
        "the refusal quotes a sibling's FRN count, which is a refusal that misidentifies its own "
        f"cause: {message}"
    )


def test_the_six_spare_frns_are_refused_and_frn_2s_message_carries_the_documents_own_reason():
    """FRN 2 has a NOTE and FRNs 29–33 have none, and the refusal says which case it is."""
    assert codec.SPARE_FRNS == {2, 29, 30, 31, 32, 33}
    assert "previous releases" in codec.spare_frn_reason(2), (
        "FRN 2's refusal no longer quotes the UAP's own NOTE, which is the only thing that tells "
        "a reader debugging a legacy encoder why the slot is empty"
    )
    for frn in (29, 30, 31, 32, 33):
        assert "no note" in codec.spare_frn_reason(frn), (
            f"FRN {frn}'s reason claims an explanation the document does not give"
        )
    assert codec.spare_frn_reason(2) != codec.spare_frn_reason(30), (
        "the two spare classes give the same message, so the distinction the row set draws is not "
        "reaching anybody"
    )


def test_write_fspec_refuses_a_spare_frn_so_the_encoder_cannot_produce_one():
    with pytest.raises(codec.CodecError) as raised:
        codec.write_fspec([1, 2, 4])
    assert "Spare" in str(raised.value)


def test_the_uap_order_is_table_1s_and_not_the_item_number_order():
    """FRN 5 is I062/105 and FRN 6 is I062/100 — the higher item number comes FIRST."""
    order = [item for _frn, item, *_rest in UAP]
    assert order[:8] == ["I062/010", "I062/015", "I062/070", "I062/105", "I062/100", "I062/185",
                         "I062/210", "I062/060"], order[:8]
    assert order != sorted(order), "the UAP is in item-number order, which Table 1 is not"
    assert FRN_BY_ITEM["I062/105"] < FRN_BY_ITEM["I062/100"], (
        "I062/105 must precede I062/100 on the wire; Table 1 puts them at FRN 5 and FRN 6"
    )


def test_all_twenty_seven_data_items_are_implemented_plus_re_and_sp():
    items = [item for _frn, item, *_rest in UAP]
    data_items = [i for i in items if i.startswith("I062/")]
    assert len(data_items) == 27, f"{len(data_items)} data items: {data_items}"
    assert set(items) - set(data_items) == {"RE", "SP"}
    assert "I062/000" not in items and "I062/101" not in items and "I062/106" not in items, (
        "an item the change record says was deleted is being decoded"
    )


def test_every_item_layout_sums_to_the_standards_own_byte_counts():
    """The generator's own check, run here so it cannot be skipped by not running the generator."""
    _build_fixtures_module().check_layouts()


def test_the_ads_c_age_is_two_octets_where_the_other_nine_are_one():
    """The most dangerous uniformity assumption in the category, asserted directly."""
    from synapse_cdm.adapters.asterix_cat062 import _SUBFIELD_OCTETS
    widths = _SUBFIELD_OCTETS["I062/290"]
    assert widths["ads"] == 2, "I062/290 Subfield #5 is two octets — §5.2.20, max 16383.75 s"
    assert {name: w for name, w in widths.items() if name != "ads"} == {
        name: 1 for name in widths if name != "ads"}, (
        "another I062/290 subfield is not one octet, so the ADS-C exception is no longer the "
        "exception this test names"
    )


def test_all_thirty_one_track_data_ages_are_one_octet():
    from synapse_cdm.adapters.asterix_cat062 import _SUBFIELD_OCTETS
    widths = _SUBFIELD_OCTETS["I062/295"]
    assert len(widths) == 31 and set(widths.values()) == {1}


# ============================================ settlement 1 — the fused content, refusal by refusal


def test_the_fusion_provenance_key_exists_on_every_object_that_carries_a_track_status():
    """Settlement 1's collection point. Scattered through `attributes` these would read as facts."""
    for name in ("full_mask_track", "track_begin", "both_altitudes_disagreeing"):
        provenance = entity_of(name).attributes["fusion_provenance"]
        assert provenance["stated_by"]["external_id"] == "2929", (
            f"{name}: the provenance does not name the system that stated it, which is the whole "
            "point of collecting it under one key"
        )
        assert "translates that content and performs no fusion" in provenance["basis"]


def test_settlement_1_refusal_1_one_record_is_one_entity_and_one_event_and_never_a_track():
    for name in ("full_mask_track", "trajectory_intent_three_points", "two_records_one_block"):
        objects = translate(name)
        assert not any(isinstance(o, Track) for o in objects), (
            f"{name} produced a Track. A Track needs samples across time and one record is one "
            "state vector at one instant; I062/380 SF#9's points are PREDICTIONS, not observations"
        )
    objects = translate("two_records_one_block")
    assert len([o for o in objects if isinstance(o, Entity)]) == 2
    assert len([o for o in objects if isinstance(o, Event)]) == 2


def test_settlement_1_refusal_2_mrh_does_not_arbitrate_between_the_altitudes():
    """The fixture carries two records with MRH flipped and IDENTICAL altitudes.

    THE MUTATION THIS CATCHES: an adapter that read MRH and picked an altitude would pass every
    check in the harness. Both records must produce the same `alt_m`, from I062/130.
    """
    first, second = [o for o in translate("both_altitudes_disagreeing") if isinstance(o, Entity)]
    assert first.position is not None and second.position is not None
    assert first.position.alt_m == second.position.alt_m, (
        "flipping MRH moved Position.alt_m, so the tracker's opinion is arbitrating between the "
        "two altitude items — §5.2.6's fourth NOTE says they are transmitted 'independent from "
        "the value transmitted on I062/080 (MRH)'"
    )
    # And it came from the GEOMETRIC item, which is the one alt_m documents itself as.
    expected = codec.from_raw("geometric_altitude", codec.to_raw("geometric_altitude", 31000.0))
    assert round(first.position.alt_m, 6) == round(expected * 0.3048, 6)
    # The tracker's opinion is carried, and the two records disagree about it.
    flags = [e.attributes["fusion_provenance"]["track_status"]["mrh"]["raw"]
             for e in (first, second)]
    assert flags == [1, 0], "the MRH bit is not being carried, so nothing records the opinion"


def test_settlement_5_the_other_three_altitudes_are_parked_with_their_datums():
    entity = entity_of("three_altitudes_and_a_measured_height")
    event = event_of("three_altitudes_and_a_measured_height")
    assert entity.position is not None and entity.position.alt_m is not None
    payload = event.payload
    assert "calculated_barometric_altitude" in payload and "measured_flight_level" in payload
    measured = entity.attributes["fusion_provenance"]["measured_information"]["measured_height"]
    assert "reference level" in measured["basis"], (
        "I062/340 SF#3's unstated datum is not recorded, and it is the reason that item never "
        "reaches alt_m"
    )
    assert payload["mode_of_movement"]["altitude_discrepancy"] is True, (
        "ADF is set in this fixture and is not being carried — it is the tracker telling you two "
        "of the altitude items disagree"
    )


def test_settlement_1_refusal_5_no_age_becomes_an_instant():
    """The formula is recorded and not applied. An instant computed here would be indistinguishable
    in the output from one the source stated."""
    ages = entity_of("ads_c_age_two_octets").attributes["fusion_provenance"]["update_ages"]
    assert "Age = Time of track information" in ages["formula"]
    for name, entry in ages["ages"].items():
        assert set(entry) >= {"raw", "seconds", "definition"}, name
        assert "instant" not in entry and "at" not in {k.lower() for k in entry}, (
            f"{name} carries something instant-shaped; the ages are relative by construction"
        )
        assert isinstance(entry["seconds"], float)
    assert ages["ages"]["ads"]["seconds"] == 4000.0, (
        "the two-octet ADS-C age did not decode, which is exactly the desynchronisation this "
        "fixture exists to catch"
    )
    assert ages["ages"]["mlt"]["seconds"] == 63.75 and "maximum" in ages["ages"]["mlt"][
        "at_or_above_maximum"], "a saturated age is not flagged as a floor"


def test_settlement_1_refusal_4_the_contributing_sensors_become_no_object_and_no_join():
    objects = translate("contributing_sensors")
    entities = [o for o in objects if isinstance(o, Entity)]
    assert len(entities) == 1, (
        f"{len(entities)} Entities from one record. The REF names three contributing sensors by "
        "SAC/SIC and none of them may become an object"
    )
    event = event_of("contributing_sensors")
    ref = entities[0].attributes["reserved_expansion_field"]["items"]
    assert ref["cst"]["rep"] == 2 and ref["csn"]["rep"] == 1
    assert [s["local_track_number"] for s in ref["cst"]["sensors"]] == [4001, 4002]
    assert "joined to anything" in ref["cst"]["basis"]
    # The reserved TYP is recorded as unresolved rather than guessed.
    assert ref["csn"]["sensors"][0]["typ_text"] is None
    assert not event.related_entities or event.related_entities == [entities[0].entity_id]


def test_settlement_1_refusal_6_all_three_callsign_shaped_strings_park_and_none_is_promoted():
    entity = entity_of("target_identification_forbidden")
    downlinked = entity.attributes["aircraft_derived_data"]["target_identification"]["trimmed"]
    flight_plan = entity.attributes["flight_plan"]["callsign"]["trimmed"]
    forbidden = entity.attributes["encoder_conformance"]["I062/245_present"]["trimmed"]
    assert downlinked == flight_plan == forbidden == "BAW117"
    # Three strings, three keys, and nothing on the Entity that reads as "the" name.
    assert not hasattr(entity, "label"), "gap 1 appears to have closed; update this test"
    assert "SHALL not be used" in entity.attributes["encoder_conformance"][
        "I062/245_present"]["basis"]
    assert "I062/245_sti_invalid" in entity.attributes["encoder_conformance"], (
        "the fixture's STI is 11, which the item's own table spells 'Invalid', and it is not "
        "being recorded"
    )


def test_the_implementation_dependent_items_are_named_and_quote_section_4_8():
    attributes = entity_of("full_mask_track").attributes
    node = attributes["implementation_dependent"]
    assert node["items"] == list(IMPLEMENTATION_DEPENDENT)
    assert "Interface Control Document" in node["quoted"]
    assert "the document says the value's meaning is not standardised" in node["basis"].lower(), (
        "the note does not distinguish a park-because-the-CDM-has-no-home from a "
        "park-because-the-document-declines-to-say, which is the whole content of §4.8"
    )


# ================================================================ settlement 3 — identity


def test_the_mode_s_address_is_the_identity_basis_and_agrees_with_cat021_for_one_airframe():
    """The property that makes the shared `ICAO24` string worth anything."""
    entity = entity_of("mode_s_address_present")
    assert entity.source_ids[0].system == ICAO24_SYSTEM == "ICAO24"
    assert entity.source_ids[0].external_id == "F0A1C7"
    assert entity.entity_id == ids.derive("ICAO24", "F0A1C7", kind="entity"), (
        "the entity_id is not a pure function of the address, so a CAT021 record and a CAT062 "
        "track of one airframe will not agree"
    )
    from synapse_cdm.adapters.asterix_cat021 import ICAO_SYSTEM as CAT021_ICAO24
    from synapse_cdm.adapters.asterix_cat048 import ICAO_SYSTEM as CAT048_ICAO24
    from synapse_cdm.adapters.adsb import ICAO_SYSTEM as ADSB_ICAO24
    assert CAT021_ICAO24 == CAT048_ICAO24 == ADSB_ICAO24 == ICAO24_SYSTEM, (
        "the adapters no longer share the namespace string, so one airframe seen through "
        "two of them derives two entity_id values"
    )


def test_the_track_number_is_never_the_identity_basis_and_two_updates_get_different_ids():
    """Settlement 3, and the fixture is two records with the SAME track number.

    THE MUTATION THIS CATCHES: keying entity_id on `(SAC/SIC, track number)` would make these two
    records one entity, which is the reading settlement 3 declines — and it would look right.
    """
    first, second = [o for o in translate("track_number_only") if isinstance(o, Entity)]
    assert first.attributes["track_number"]["raw"] == second.attributes["track_number"]["raw"] == 777
    assert first.entity_id != second.entity_id, (
        "two records with one track number produced one entity_id, so the track number IS the "
        "basis — settlement 3 declines that because the number is recycled and entity_id has no "
        "expiry"
    )
    assert first.source_ids[0].system == REPORT_SYSTEM
    assert "gap 27" in first.attributes["identity_basis"], (
        "the record-scoped id does not name the truncation it causes"
    )
    assert "DECLINED" in first.attributes["identity_basis"], (
        "the id basis does not record that the (SAC/SIC, track number) alternative was considered"
    )


def test_the_identity_caveat_is_present_on_every_object_and_says_the_category_cannot_tell_you():
    """An absent caveat field reads as 'no conflict'. This category warns of no address duplication."""
    for name in ("mode_s_address_present", "track_number_only", "full_mask_track"):
        caveat = entity_of(name).attributes["identity_caveat"]
        assert "no duplicate-Mode-S-address indication" in caveat, name
        assert "AAC" in caveat and "DUPT" in caveat and "IDD" in caveat, (
            f"{name}: the caveat does not name the three bits that ARE about duplication, so a "
            "reader cannot check the claim"
        )


def test_the_emitting_system_is_parked_and_is_not_a_source_id():
    """The inverse of CAT034's disposition, and the difference is the whole reason both exist."""
    entity = entity_of("full_mask_track")
    assert all(s.system != "ASTERIX_CAT062" for s in entity.source_ids)
    data_source = entity.attributes["data_source"]
    assert data_source["external_id"] == "2929"
    assert "entity per processor" in data_source["basis"]


# ================================================================= the clock and time


def test_the_adapter_never_reads_the_wall_clock():
    source = (PACKAGE / "adapters" / "asterix_cat062.py").read_text()
    assert "datetime.now" not in source and "utcnow" not in source, (
        "the adapter reads the wall clock somewhere, which makes every golden file undiffable"
    )


def test_the_midnight_wrap_happens_under_the_harnesss_own_frozen_clock():
    """The backward roll, reachable from `times.FROZEN_NOW` at 06:15 and asserted with no injection."""
    first, second = [o for o in translate("midnight_rollover_nearest") if isinstance(o, Event)]
    assert first.observed_at.date() == times.FROZEN_NOW.date() - dt.timedelta(days=1), (
        "the 23:59:59 record did not roll back to the previous day under the frozen clock, so "
        "this fixture tests no rollover at all — the CAT048 failure this repository records"
    )
    assert second.observed_at.date() == times.FROZEN_NOW.date()
    assert "ROLLOVER" in first.payload["observed_at_basis"]["date_from"]
    assert "ROLLOVER" not in second.payload["observed_at_basis"]["date_from"]


def test_the_forward_wrap_needs_a_clock_this_test_injects():
    late = times.frozen_clock(dt.datetime(2026, 4, 29, 23, 50, tzinfo=dt.timezone.utc))
    events = [o for o in AsterixCat062Adapter(clock=late).to_cdm(
        block_of("midnight_rollover_nearest")) if isinstance(o, Event)]
    assert events[1].observed_at.date() == dt.date(2026, 4, 30), (
        "00:00:01 did not roll FORWARD under a 23:50 receipt time, so the nearest-candidate rule "
        "is only being exercised in one direction"
    )


def test_a_time_of_day_past_a_day_is_refused_and_the_basis_names_the_cat048_difference():
    """The CAT034 disposition, not the CAT048 one, and the message has to say which."""
    module = _build_fixtures_module()
    over = module.block(module.record(module._base(tod=codec.SECONDS_PER_DAY * 128)))
    with pytest.raises(Cat062ParseError) as raised:
        adapter().to_cdm(over)
    message = str(raised.value)
    assert "86400" in message and "modulo" in message
    assert "I048/140" in message or "CAT048" in message, (
        "the refusal does not record that Part 4's printed inequality ACCEPTS 86400 s while this "
        "category's Definition and NOTE 2 make it unreachable — one value, three categories, and "
        "the difference is the whole finding"
    )
    # And exactly one LSB below is accepted, which is what makes the boundary a boundary.
    fine = module.block(module.record(module._base(tod=codec.SECONDS_PER_DAY * 128 - 1)))
    assert adapter().to_cdm(fine)


def test_the_mode_5_time_offset_substitutes_i062_070_and_says_so_in_the_object():
    """Settlement 4's ruling, stated beside the value rather than applied quietly."""
    first, second = [o for o in translate("mode5_time_offset") if isinstance(o, Event)]
    basis = first.payload["mode_5"]["time_basis"]
    assert basis["base_instant_from"] == "I062/070"
    assert "I048/140" in basis["substitution"], (
        "the object does not record that the specification named an item of another category, so "
        "a consumer cannot see that a substitution was made"
    )
    assert basis["offset_seconds"] == -0.5 and basis["offset_present"] is True
    # An absent Subfield #6 is a STATED ZERO, not an unknown.
    absent = second.payload["mode_5"]["time_basis"]
    assert absent["offset_present"] is False and absent["offset_seconds"] == 0.0
    assert "stated zero" in absent["absent_is_a_stated_zero"].lower()


def test_a_trajectory_point_resolves_a_time_only_when_toa_permits_it():
    points = event_of("trajectory_intent_three_points").payload[
        "kinematics_basis"] if False else entity_of(
        "trajectory_intent_three_points").attributes["aircraft_derived_data"][
        "trajectory_intent"]["points"]
    resolvable = [p for p in points if p["time_over_point_available"]]
    withheld = [p for p in points if not p["time_over_point_available"]]
    assert resolvable and withheld, "the fixture no longer carries both TOA cases"
    for point in resolvable:
        assert "time_over_point_seconds" in point
    for point in withheld:
        assert "time_over_point_seconds" not in point, (
            "a TOV was resolved under TOA = 1, and NOTE 6 says it 'is meaningful only if TOA is "
            "set to 0'"
        )


# ============================================ settlement 6 — position, and what is not one


def test_the_position_comes_from_i062_105_at_the_documents_own_resolution():
    entity = entity_of("mode_s_address_present")
    assert entity.position is not None
    assert entity.position.position_source is PositionSource.ESTIMATED, (
        "a tracker's filtered output is an estimate by construction — §3.1.2 defines a Calculated "
        "Item as one derived 'through an intermediate processing such as ... tracking'"
    )
    lsb = codec.bounds("latitude_105")[2]
    assert abs(entity.position.lat - 57.39) < lsb
    assert abs(entity.position.lon - 21.56) < lsb


def test_the_cartesian_position_is_parked_and_no_coordinate_is_derived_from_it():
    """Settlement 6, and the fixture carries BOTH items so the choice is visible."""
    entity = entity_of("cartesian_position_parked")
    event = event_of("cartesian_position_parked")
    assert entity.position is not None
    assert abs(entity.position.lat - 57.39) < 1e-4, (
        "the Position did not come from I062/105 — the Cartesian pair is a different frame"
    )
    cartesian = event.payload["cartesian_position"]
    assert cartesian["x_metres"] == -125000.5 and cartesian["y_metres"] == 88000.0
    assert "reference point" in cartesian["basis"] and "CATEGORY 065" in cartesian["basis"], (
        "the basis does not name the two unknowns, so a reader cannot tell a decline from an "
        "omission"
    )
    assert "stereographical" in cartesian["basis"]


def test_the_aircrafts_own_position_never_becomes_the_entitys():
    entity = entity_of("full_mask_track")
    parked = entity.attributes["aircraft_derived_data"]["position"]
    assert entity.position is not None
    assert parked["quantisation"] == codec.WGS84_23_QUANTISATION_NOTE
    assert "Never Entity.position" in parked["basis"]


def test_no_object_ever_carries_a_geometry():
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Event):
                assert obj.geometry is None, (
                    f"{path.name} produced an Event.geometry. The category carries no geometry: "
                    "I062/100 is in a frame settlement 6 declines to invert and I062/380 SF#9's "
                    "points are predictions"
                )


def test_the_accuracy_is_computed_from_subfield_3_and_the_arithmetic_is_in_the_object():
    entity = entity_of("estimated_accuracies_full")
    assert entity.position is not None and entity.position.accuracy_m is not None
    basis = entity.attributes["position_basis"]["accuracy"]
    assert basis["item"] == "I062/500 Subfield #3"
    assert "independence assumed" in "independence assumed" and "silence" in basis[
        "independence_assumed"].lower()
    assert "111120" in basis["arithmetic"] and "cos(latitude)" in basis["arithmetic"]
    expected = codec.degrees_to_metres(basis["latitude_component_deg"],
                                       basis["longitude_component_deg"], entity.position.lat)
    assert round(entity.position.accuracy_m, 9) == round(expected, 9)


def test_the_accuracy_is_absent_rather_than_derived_from_the_cartesian_subfield():
    """Subfield #1 is present in the fixture and Subfield #3 is what is used. Removing #3 must
    give `None`, not a fallback — the Cartesian frame is the one settlement 6 declines."""
    module = _build_fixtures_module()
    without = module.block(module.record(module._base(**{
        "I062/105": module._position(module.TRACK_LAT, module.TRACK_LON),
        "I062/500": module._compound("I062/500", {
            "apc": {"x_raw": codec.to_raw("accuracy_position_m", 45.0),
                    "y_raw": codec.to_raw("accuracy_position_m", 60.0)}}),
    })))
    entity = [o for o in adapter().to_cdm(without) if isinstance(o, Entity)][0]
    assert entity.position is not None and entity.position.accuracy_m is None, (
        "accuracy_m was derived from I062/500 Subfield #1, whose components are in the Cartesian "
        "frame this row set declines to invert"
    )
    assert "Cartesian frame" in entity.attributes["position_basis"]["accuracy"]["reason"]


def test_a_saturated_accuracy_is_flagged_as_a_floor():
    entity = entity_of("estimated_accuracies_full")
    accuracies = entity.attributes["fusion_provenance"]["estimated_accuracies"]
    assert accuracies["arc"]["at_or_above_maximum"]


# ================================================================== the kinematics


def test_the_velocity_vector_becomes_speed_and_course_in_the_documents_own_frame():
    """`atan2(Vx, Vy)` and not `atan2(Vy, Vx)`. The wrong one is plausible everywhere."""
    entity = entity_of("estimated_accuracies_full")
    assert entity.kinematics is not None
    basis = event_of("estimated_accuracies_full").payload["kinematics_basis"]["velocity"]
    vx, vy = basis["vx_mps"], basis["vy_mps"]
    import math
    assert round(entity.kinematics.speed_mps, 9) == round(math.hypot(vx, vy), 9)
    assert round(entity.kinematics.course_deg, 9) == round(
        math.degrees(math.atan2(vx, vy)) % 360.0, 9), (
        "the course is not measured from Vy toward Vx; §5.2.14's NOTE puts the y-axis at "
        "geographical north, so atan2(Vy, Vx) reflects every bearing about 45 degrees"
    )
    # A positive Vx and a negative Vy is a south-easterly course, which the wrong call reverses.
    assert 90.0 < entity.kinematics.course_deg < 180.0, entity.kinematics.course_deg


def test_the_aircrafts_own_speed_heading_and_vertical_rates_never_reach_kinematics():
    entity = entity_of("full_mask_track")
    parked = entity.attributes["aircraft_derived_data"]
    assert entity.kinematics is not None
    assert "ground_speed" in parked and "track_angle" in parked
    assert "barometric_vertical_rate" in parked and "geometric_vertical_rate" in parked
    assert "arbitrate between three numbers" in parked["barometric_vertical_rate"]["basis"]
    # And the magnetic heading opens gap 7 rather than filling a field.
    assert "gap 7" in parked["magnetic_heading"]["basis"]
    assert not hasattr(entity.kinematics, "heading_deg"), "gap 7 closed; update this test"


def test_the_rate_of_climb_converts_exactly_and_keeps_the_source_figure_beside_it():
    entity = entity_of("estimated_accuracies_full")
    basis = event_of("estimated_accuracies_full").payload["kinematics_basis"]["rate_of_climb"]
    assert entity.kinematics is not None
    assert basis["feet_per_minute"] == 1875.0
    assert round(entity.kinematics.climb_mps, 9) == round(1875.0 * 0.3048 / 60.0, 9)


# ======================================================= the emergencies, all three of them


def test_the_ref_priority_status_wins_over_the_lossy_core_item_and_the_mapping_is_quoted():
    """Settlement 2's whole reason, and the fixture is the back-mapping's worst case."""
    event = event_of("adsb_version_3_emergency")
    basis = event.payload["emergency_basis"]
    assert basis["preferred"] == "I062/REF/PS3"
    assert event.severity is Severity.CRITICAL and event.event_type is EventType.ALERT
    ps3 = next(s for s in basis["statements"] if s["source"] == "I062/REF/PS3")
    assert ps3["raw"] == 7 and ps3["text"] == PS3_TEXT[7]
    assert ps3["back_maps_to"] == PS3_BACK_MAPPING[7] == 1, (
        "the object does not record what the core item's value would have been, so a consumer "
        "cannot see that the core item is legally correct AND lossy"
    )
    core = next(s for s in basis["statements"] if s["source"] == "I062/380 SF#11 STAT")
    assert core["raw"] == 1 and core["text"] == EMS_TEXT[1]


def test_the_version_number_finding_is_recorded_because_the_cited_field_does_not_exist():
    basis = event_of("adsb_version_3_emergency").payload["emergency_basis"]
    assert "THERE IS NO VN FIELD" in basis["version_number_finding"]
    assert "ambiguity 13" in basis["version_number_finding"]


def test_two_disagreeing_core_statements_take_the_more_severe_and_record_the_disagreement():
    event = event_of("emergency_disagreement")
    basis = event.payload["emergency_basis"]
    severities = {s["source"]: s["severity"] for s in basis["statements"]}
    assert len(set(severities.values())) > 1, "the fixture no longer carries a disagreement"
    assert event.severity is Severity.CRITICAL, (
        "the more severe statement did not win; taking either by position would make the field's "
        "meaning depend on which item the record happened to carry"
    )
    assert "disagreement" in basis
    iec = entity_of("emergency_disagreement").attributes["fusion_provenance"]["track_status"][
        "iec"]
    assert iec["raw"] == 1, "the tracker's own inconsistency bit is not being carried"


def test_a_ps3_under_a_clear_element_populated_bit_raises_nothing():
    """Appendix A's convention, honoured rather than flattened."""
    module = _build_fixtures_module()
    payload = module.block(module.record(module._base(**{
        "RE": module._ref(items={"v3": module._v3(ps3=(0, 5))})})))
    event = [o for o in adapter().to_cdm(payload) if isinstance(o, Event)][0]
    assert event.severity is Severity.INFO and event.event_type is EventType.TRACK_UPDATE, (
        "an unpopulated PS3 raised a severity. Appendix A's Element Populated bit says the three "
        "value bits are NOT A STATEMENT, and flattening it turns every zero into a meaning"
    )
    statement = next(s for s in event.payload["emergency_basis"]["statements"]
                     if s["source"] == "I062/REF/PS3")
    assert statement["severity"] is None and "not_populated" in statement


def test_five_candidate_bits_are_declined_and_each_says_why():
    entity = entity_of("full_mask_track")
    flags = entity.attributes["fusion_provenance"]["track_status"]
    assert "does NOT raise Event.severity" in flags["military"]["military_emergency"]["basis"]
    assert "local matter" in flags["pft"]["basis"].lower()
    assert "gap 29" in flags["pft"]["basis"]
    parked = entity.attributes["aircraft_derived_data"]["communications_capability"]
    assert "DO NOT RAISE SEVERITY" in parked["basis"]
    # SPI, ME and PFT are all set in this fixture and none of them is what raised the severity:
    # the REF's PS3 = 2 (UAS/RPAS Lost Link) is, and the object says so.
    event = event_of("full_mask_track")
    assert event.severity is Severity.WARNING
    assert event.payload["emergency_basis"]["preferred"] == "I062/REF/PS3", (
        "the severity on this fixture came from something other than the three emergency items, "
        "which is exactly what the five declines above exist to prevent"
    )


# ============================================ the vocabularies that are NOT read as affiliation


def test_no_object_is_ever_anything_but_unknown_and_the_three_declines_are_named():
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Entity):
                assert obj.affiliation is Affiliation.UNKNOWN, path.name
    basis = entity_of("full_mask_track").attributes["affiliation_basis"]
    for phrase in ("Friendly target", "Operational Air Traffic", "highly manoeuvrable"):
        assert phrase in basis, (
            f"the affiliation basis does not name the {phrase!r} inference it declines"
        )


def test_the_emitter_category_and_the_fleet_refine_entity_type_and_nothing_else():
    vehicle, undefined, obstruction = [
        o for o in translate("emitter_category_and_fleet") if isinstance(o, Entity)]
    assert vehicle.entity_type is EntityType.PLATFORM
    assert vehicle.attributes["entity_type_basis"]["vehicle_fleet"]["text"] == VFI_TEXT[5]
    assert vehicle.attributes["entity_type_basis"]["emitter_category"]["text"] == ECAT_TEXT[21]
    assert obstruction.entity_type is EntityType.FACILITY, (
        "'fixed ground or tethered obstruction' is the one emitter category that is not a vehicle"
    )
    # A reserved code and an undefined fleet value refine nothing and land in unresolved_raw.
    assert undefined.entity_type is EntityType.PLATFORM
    assert "I062/380 SF#21 ECAT" in undefined.attributes["unresolved_raw"]
    assert "I062/300 VFI" in undefined.attributes["unresolved_raw"]


def test_no_payload_field_sets_source_synthetic():
    """Three bits in this category describe the track and none of them decides the deployment."""
    entity = entity_of("full_mask_track", synthetic=False)
    assert entity.source.synthetic is False
    flags = entity.attributes["fusion_provenance"]["track_status"]["simulated_flag"]
    assert "does NOT set SourceRef.synthetic" in flags["basis"]
    report = entity.attributes["fusion_provenance"]["measured_information"]["report_type"]
    assert "NEITHER SIM NOR TST" in report["basis"]


# ============================================================ ambiguity 10 and the small items


def test_the_target_size_length_means_two_different_things_and_both_readings_survive():
    length_only, with_width = [o for o in translate("target_size_length_only")
                               if isinstance(o, Event)]
    a = length_only.payload["target_size_and_orientation"]
    b = with_width.payload["target_size_and_orientation"]
    assert a["width_present"] is False and b["width_present"] is True
    assert "LARGEST DIMENSION" in a["length_means"]
    assert "LENGTH" in b["length_means"] and "LARGEST" not in b["length_means"]
    assert a["length_raw"] == b["length_raw"], (
        "the two fixtures no longer carry the same raw field, so the test is comparing two "
        "measurements rather than two readings of one"
    )
    assert "orientation_degrees" in b and "orientation_degrees" not in a


def test_the_composed_track_number_is_ordered_and_no_slave_is_joined():
    payload = entity_of("composed_track_number_three_units").attributes[
        "fusion_provenance"]["composed_track_number"]
    assert [u["system_unit"] for u in payload["units"]] == [0x11, 0x22, 0x33]
    assert "responsible for the track amalgamation" in payload["basis"]
    assert "joined to anything" in payload["basis"]


def test_the_two_opaque_registers_are_parked_whole_and_never_decoded():
    parked = entity_of("full_mask_track").attributes["aircraft_derived_data"]
    assert parked["acas_resolution_advisory"]["octets"] == "30" * 7
    assert "Draft SARPs" in parked["acas_resolution_advisory"]["basis"]
    assert parked["bds_registers"]["rep"] == 2
    assert all(len(bytes.fromhex(r["bds_data"])) == 7 for r in parked["bds_registers"]["registers"])


def test_the_special_purpose_field_is_parked_and_the_ref_is_decoded():
    entity = entity_of("reserved_and_extension_fields")
    assert entity.attributes["special_purpose_field"]["contents"] == "aabbccdd"
    assert "NEVER WRITTEN TO" in entity.attributes["special_purpose_field"]["basis"]
    ref = entity.attributes["reserved_expansion_field"]
    assert set(ref["items"]) == {"cst", "tvs", "sts"}
    assert len(ref["eight_containers_the_core_text_names_and_this_edition_does_not_define"]) == 9, (
        "the dangling-pointer list changed size; settlement 2 names them individually and the "
        "declines table has to match"
    )
    assert "SPARE and not a Field Extension Indicator" in ref["no_fx_finding"]


def test_the_ref_lnav_sense_is_carried_verbatim_because_it_is_inverted():
    sts = entity_of("reserved_and_extension_fields").attributes[
        "reserved_expansion_field"]["items"]["sts"]
    assert sts["lnav_populated"] is True and sts["lnav_val_raw"] == 0
    assert sts["lnav_engaged"] is True, (
        "LNAV#VAL = 0 is 'LNAV Mode Engaged' — the sense is inverted relative to every other flag "
        "in either document, and flattening it reverses the meaning"
    )
    assert "INVERTED" in sts["basis"]


# =========================================================================== egress


@pytest.mark.parametrize("path", blocks(), ids=lambda p: p.stem)
def test_every_fixture_round_trips_byte_for_byte(path):
    """THE ROUND TRIP THE HARNESS SKIPS, and it is byte equality rather than value presence."""
    raw = path.read_bytes()
    objects = adapter().to_cdm(raw)
    emitted = adapter().from_cdm([o for o in objects if isinstance(o, Entity)])
    assert emitted == raw, (
        f"{path.name} did not round-trip:\n  in : {raw.hex()}\n  out: {emitted.hex()}"
    )


def test_the_parsed_twin_and_the_octets_produce_identical_objects():
    for path in blocks():
        twin = json.loads((FIXTURES / f"{path.stem}.parsed.json").read_text())
        assert [o.model_dump(mode="json") for o in adapter().to_cdm(path.read_bytes())] == \
               [o.model_dump(mode="json") for o in adapter().to_cdm(twin)], path.name


def test_a_non_minimal_fspec_is_re_emitted_as_parked_and_not_recomputed():
    raw = block_of("non_minimal_fspec")
    parsed = parse_block(raw)
    assert len(bytes.fromhex(parsed["records"][0]["fspec"])) == 3, (
        "the fixture no longer carries a longer-than-necessary FSPEC"
    )
    assert len(codec.write_fspec(sorted(FRN_BY_ITEM[i] for i in parsed["records"][0]["items"]))) == 2
    assert build_block(parsed["records"]) == raw


def test_egress_never_inverts_the_accuracy_combination_or_the_velocity_vector():
    """The one shared model in this adapter, and the one place a round trip could lie.

    Both derived values are edited on the CDM object and the emitted block must be UNCHANGED —
    which is what proves the parked raw fields are the source of the octets.
    """
    raw = block_of("estimated_accuracies_full")
    objects = adapter().to_cdm(raw)
    entity = next(o for o in objects if isinstance(o, Entity))
    entity.position = entity.position.model_copy(update={"accuracy_m": 999.0})
    entity.kinematics = entity.kinematics.model_copy(
        update={"speed_mps": 1.0, "course_deg": 1.0, "climb_mps": 1.0})
    assert adapter().from_cdm([entity]) == raw, (
        "editing the derived scalars changed the emitted octets, so egress is re-deriving them — "
        "and sqrt(a²+b²) has no unique inverse, so any components it chose would be invented"
    )


def test_egress_recomputes_len_and_never_copies_it():
    raw = block_of("full_mask_track")
    parsed = parse_block(raw)
    parsed["block"]["length"] = 9999
    assert build_block(parsed["records"]) == raw


def test_egress_refuses_an_object_that_did_not_come_from_cat062_and_names_each_missing_input():
    stray = Entity(
        source=adapter().source_ref(), source_ids=[{"system": "X", "external_id": "1"}],
        entity_id=ids.derive("X", "1"), entity_type=EntityType.PLATFORM,
        affiliation=Affiliation.UNKNOWN, valid_from=times.FROZEN_NOW)
    with pytest.raises(Cat062ParseError) as raised:
        adapter().from_cdm([stray])
    message = str(raised.value)
    assert "cat062_fspec" in message and "source_extras.items" in message
    assert "I062/040" in message and "I062/070" in message and "I062/080" in message


def test_a_track_cannot_become_a_data_block_and_the_reason_is_stated():
    track = Track(source=adapter().source_ref(),
                  source_ids=[{"system": "X", "external_id": "1"}],
                  track_id=ids.derive("X", "1", kind="track"),
                  entity_id=ids.derive("X", "1"),
                  samples=[TrackSample(position={"lat": 0.0, "lon": 0.0,
                                                 "position_source": "ESTIMATED"},
                                       observed_at=times.FROZEN_NOW)])
    with pytest.raises(Cat062ParseError) as raised:
        adapter().from_cdm([track])
    assert "never emits a Track" in str(raised.value)


# ========================================================================= refusals

REFUSAL_REASONS = {
    "wrong_category": "CAT octet is 48",
    "length_disagrees_with_buffer": "LEN says",
    "missing_mandatory_track_number": "I062/040",
    "fspec_names_a_spare_frn": "'- Spare -'",
    "fspec_sixth_octet": "FRN 36",
    "track_status_seventh_extent": "Sixth Extent sets its FX bit",
    "compound_spare_presence_bit": "marks spare",
    "repetitive_rep_zero": "REP = 0",
    "ref_length_disagrees": "Reserved Expansion Field states a length",
}


def test_the_refusal_directory_holds_exactly_the_nine_the_row_set_names():
    on_disk = {p.stem for p in REFUSALS.glob("*.cat062")}
    assert on_disk == set(REFUSAL_REASONS), (
        f"only on disk: {sorted(on_disk - set(REFUSAL_REASONS))}\n"
        f"only in this test: {sorted(set(REFUSAL_REASONS) - on_disk)}"
    )
    section = _flat(_section())
    assert "nine refusals" in section, (
        "the row set no longer says how many refusals there are, so the count here is checked "
        "against nothing"
    )


@pytest.mark.parametrize("name,expected", sorted(REFUSAL_REASONS.items()))
def test_each_refusal_names_what_was_wrong(name, expected):
    with pytest.raises(Cat062ParseError) as raised:
        adapter().to_cdm((REFUSALS / f"{name}.cat062").read_bytes())
    assert expected in str(raised.value), (
        f"{name} was refused for a reason that does not mention {expected!r}:\n"
        f"  {raised.value}"
    )


def test_the_two_fspec_refusals_are_distinguishable_from_each_other():
    """A spare slot inside the table and an FRN above 35 are different faults with different fixes."""
    def message(name):
        with pytest.raises(Cat062ParseError) as raised:
            adapter().to_cdm((REFUSALS / f"{name}.cat062").read_bytes())
        return str(raised.value)
    spare = message("fspec_names_a_spare_frn")
    beyond = message("fspec_sixth_octet")
    assert "Spare" in spare and "Spare" not in beyond
    assert "FRN 36" in beyond and "FRN 36" not in spare


def test_the_encoder_refuses_to_produce_the_two_fixtures_that_were_assembled_by_hand():
    """The refusals that a conforming encoder cannot emit either. That is the check, not a gap."""
    module = _build_fixtures_module()
    with pytest.raises(codec.CodecError):
        codec.write_fspec([1, 4, 12, 13, 30])
    ages = module._ages("I062/290", trk=1.0)
    presence = bytearray(bytes.fromhex(ages["presence"]))
    presence[0] |= codec.FX
    presence.append(0b00001000)
    ages["presence"] = bytes(presence).hex()
    with pytest.raises(Cat062ParseError):
        ENCODERS["I062/290"](ages)


# =============================================================== the row set itself

NAMED_TABLES = [
    "### Row set — the block and record envelope",
    "### Row set — identity, the track number, and the system that formed the opinion",
    "### Row set — time",
    "### Row set — position, and the Cartesian items that are never converted",
    "### Row set — the four altitudes, the two vertical rates, and the mode of movement",
    "### Row set — velocity, acceleration, and the one vector that becomes scalars",
    "### Row set — `I062/080` Track Status, six extents and forty-two flags",
    "### Row set — the Mode codes, and `I062/110` Mode 5",
    "### Row set — `I062/290` System Track Update Ages",
    "### Row set — `I062/295` Track Data Ages",
    "### Row set — `I062/340` Measured Information",
    "### Row set — `I062/380` Aircraft Derived Data",
    "### Row set — `I062/390` Flight Plan Related Data",
    "### Row set — the small items",
    "### Row set — the Reserved Expansion Field",
    "### Row set — SP",
    "### Row set — egress, CDM back to a CAT062 data block",
]


@pytest.mark.parametrize("heading", NAMED_TABLES)
def test_every_row_of_every_named_table_claims_this_adapter(heading):
    """The inverted test, per table rather than per section."""
    rows = [r for r in _table(heading) if "| CDM field |" not in r and "| CAT062 |" not in r]
    assert rows, f"{heading} has no data rows, so this assertion covers nothing"
    stale = [r for r in rows if "`not yet`" in r]
    assert not stale, (
        f"{len(stale)} row(s) under {heading!r} still say `not yet` while "
        f"adapters/asterix_cat062.py implements them:\n  " + "\n  ".join(r[:150] for r in stale)
    )
    unclaimed = [r for r in rows if "`cat062 1.0.0" not in r]
    assert not unclaimed, (
        f"{len(unclaimed)} row(s) under {heading!r} claim no adapter:\n  "
        + "\n  ".join(r[:150] for r in unclaimed)
    )


def test_the_egress_table_states_cdm_field_so_its_paths_are_actually_resolved():
    rows = _table("### Row set — egress, CDM back to a CAT062 data block")
    assert rows[0].startswith("| CDM field | CAT062 | Status | Notes |"), (
        f"the egress header is {rows[0]!r}; a column headed anything else contributes ZERO paths "
        "to test_cdm_format_coverage's resolver"
    )


def test_the_phase_2_change_is_listed_in_one_place_and_it_is_the_transforms_row():
    section = _flat(_section())
    assert "### What Phase 2 changed in the Phase 1 row set" in _section()
    changes = _table("### What Phase 2 changed in the Phase 1 row set")
    assert len(changes) >= 3, "the Phase 2 changes table has no rows"
    assert any("TRANSFORMS` is EMPTY" in row for row in changes)
    assert "zero losses either way" in section, (
        "the correction is asserted rather than measured; the claim is that the check was RE-RUN "
        "with TRANSFORMS emptied"
    )


def test_the_adapter_declares_no_transforms_and_therefore_excuses_nothing():
    assert AsterixCat062Adapter.TRANSFORMS == {}, (
        "a transform was declared. It is an exemption from the never-drop check and the Phase 2 "
        "correction measured that this adapter needs none"
    )


def test_the_declines_table_names_the_nine_unreachable_ref_containers():
    rows = _table("### Deliberately out of scope, and why — each named individually")
    dangling = [r for r in rows if "STS/CSX" in r]
    assert dangling, "the declines table no longer names the REF containers that cannot be reached"
    for container in ("MOI/SCT", "MOI/AM5I", "MOI/AM5L2S", "MOI/CTBA", "MOI/ALTQCMFL",
                      "MOI/FPVHR", "MOI/SI#10", "MTI/EXM3A"):
        assert container in dangling[0], f"{container} is not named in the declines row"


def test_the_ambiguity_register_carries_thirteen_entries():
    rows = _table("### Where the specification is ambiguous or contradicts itself")
    numbered = [r for r in rows if r.startswith("| ") and r.split("|")[1].strip().isdigit()]
    assert len(numbered) == 13, (
        f"{len(numbered)} numbered ambiguities; the pin record's register and this table are two "
        "statements of one set and must agree"
    )
    pin = json.loads((FIXTURES / "spec" / "cat062_pin.json").read_text())
    assert set(pin["ambiguity_register"]["entries"]) == {str(i) for i in range(1, 14)}


# ================================================================= the fixtures themselves


def test_every_fixture_has_both_twins_and_a_golden_for_each():
    for path in blocks():
        assert (FIXTURES / f"{path.stem}.parsed.json").exists(), path.name
        assert (GOLDEN / f"{path.stem}.cdm.json").exists(), path.name
        assert (GOLDEN / f"{path.stem}.parsed.cdm.json").exists(), path.name


def test_the_generator_is_the_only_thing_that_writes_the_octets():
    module = _build_fixtures_module()
    built = module.fixtures()
    on_disk = {p.stem: p.read_bytes() for p in blocks()}
    assert set(built) == set(on_disk), (
        f"only built: {sorted(set(built) - set(on_disk))}\n"
        f"only on disk: {sorted(set(on_disk) - set(built))}"
    )
    for name, octets in built.items():
        assert octets == on_disk[name], f"{name} on disk is not what the generator produces"
    refusals = module.refusals()
    assert {p.stem for p in REFUSALS.glob("*.cat062")} == set(refusals)
    for name, octets in refusals.items():
        assert (REFUSALS / f"{name}.cat062").read_bytes() == octets, name


def test_every_reachable_spare_bit_is_read_and_written_back_unchanged():
    """§4.5 is normative, and a set with all-zero spares tests nothing.

    THE MUTATION THIS CATCHES: zeroing a spare inside a decoder re-encodes as a zero and passes
    every other fixture. This one sets every reachable spare bit to 1.
    """
    raw = block_of("spare_bits_nonzero")
    parsed = parse_block(raw)
    spares = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.startswith("spare"):
                    spares.append((f"{path}.{key}", value))
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(parsed["records"][0]["items"])
    nonzero = [(p, v) for p, v in spares if v]
    assert len(nonzero) >= 15, (
        f"only {len(nonzero)} of {len(spares)} spare fields are non-zero in the fixture that "
        "exists to set them: " + str(spares[:8])
    )
    assert build_block(parsed["records"]) == raw


def test_no_fixture_carries_a_uuid_because_the_wire_form_has_none():
    """Asserted against the PARSED form, not the octets, and the difference is the point.

    `f1c7` is two bytes, and in a 400-octet binary fixture two bytes appear by coincidence — the
    ICAO24 `F0A1C7` alone puts `f0a1c7` on the wire, and `full_mask_track` contains `f1c7` inside
    an unrelated field. A hex search over a binary format is a search that cannot fail informatively.
    What is checkable is that the parser produces no identifier-shaped string, which is the actual
    claim: a CAT062 data block has no UUID field, so nothing in the parsed form may look like one.
    """
    for path in blocks():
        twin = (FIXTURES / f"{path.stem}.parsed.json").read_text()
        found = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", twin)
        assert not found, (
            f"{path.stem}.parsed.json carries a UUID ({found.group(0)}), and a CAT062 data block "
            "has no field for one — the parsed form is the wire form's fields and nothing else"
        )


def test_every_fixture_is_synthetic_and_says_so_on_every_object():
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            assert obj.source.synthetic is True, path.name
            assert obj.source.adapter == "cat062" and obj.source.system == "ASTERIX_CAT062"
