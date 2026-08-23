"""ASTERIX CAT048 — the adapter against the row set that specified it.

Every assertion here is scoped to a NAMED table or a NAMED fixture rather than to the document
as a whole, per the testing protocol: a section-wide substring check passes by luck when the
phrase happens to appear somewhere else, and the CAT048 section is 1 300 lines long.

The round trip is tested HERE and not by the harness. `_check_roundtrip` reports SKIP for an
adapter whose `from_cdm` returns non-JSON bytes and says in as many words that "the adapter must
ship its own round-trip test in tests/". This is it, and it is stronger than the harness's
value-presence comparison: it asserts BYTE EQUALITY on every fixture in the set.
"""
import datetime as dt
import json
import pathlib
import re
import uuid

import pytest

import synapse_cdm
from synapse_cdm import ids, times
from synapse_cdm.adapters import cat048_codec as codec
from synapse_cdm.adapters.asterix_cat048 import (
    AsterixCat048Adapter, Cat048ParseError, ENCODERS, FRN_BY_ITEM, ICAO_SYSTEM, MANDATORY_ITEMS,
    REPORT_SYSTEM, UAP, WARNING_ERROR_TEXT, build_block, parse_block,
)
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import Entity, Event, Track, TrackSample

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
DOC = PACKAGE / "FORMAT_COVERAGE.md"
FIXTURES = PACKAGE / "fixtures" / "cat048"
REFUSALS = FIXTURES / "refusals"

#: The frozen clock every fixture's golden file was written against.
CLOCK = times.frozen_clock(dt.datetime(2026, 4, 29, 6, 15, 0, tzinfo=dt.timezone.utc))

#: The site the geometry tests inject: the Gulf of Riga, matching the other fixture sets, at a
#: plausible radar-head elevation. CONFIGURATION, supplied by the caller, never in the payload.
SITE = (57.0500, 23.6000, 12.0)


def adapter(**kwargs):
    return AsterixCat048Adapter(clock=CLOCK, **kwargs)


def blocks():
    return sorted(FIXTURES.glob("*.cat048"))


def block_of(name: str) -> bytes:
    return (FIXTURES / f"{name}.cat048").read_bytes()


def translate(name: str, **kwargs):
    return adapter(**kwargs).to_cdm(block_of(name))


def entity_of(name: str, **kwargs) -> Entity:
    return next(o for o in translate(name, **kwargs) if isinstance(o, Entity))


def event_of(name: str, **kwargs) -> Event:
    return next(o for o in translate(name, **kwargs) if isinstance(o, Event))


def _section() -> str:
    """The CAT048 section, ending at the NEXT top-level heading.

    The rule `tests/test_cdm_format_coverage.py::_section` uses, and the rule the GMTIF tests
    were moved to after the CAT048 row set was written between them and GeoJSON. Not a named
    terminator: adapter #12 will land after this one too.
    """
    text = DOC.read_text()
    start = text.index("## ASTERIX Category 048")
    nxt = text.find("\n## ", start + 10)
    return text[start:nxt if nxt != -1 else len(text)]


def _table(heading: str) -> list[str]:
    """The data rows of the table(s) under one `###` heading, and nothing else.

    Scoped by heading so an assertion cannot pass on a row from a different table — the
    mutation the GMTIF resolution-table check was tightened for.
    """
    section = _section()
    start = section.index(heading)
    nxt = section.find("\n### ", start + len(heading))
    body = section[start:nxt if nxt != -1 else len(section)]
    return [line for line in body.splitlines()
            if line.startswith("|") and not line.startswith("|---")]


# ============================================================== the codec, form by form


@pytest.mark.parametrize("form,stated_max", [
    # Each figure is the one the document PRINTS, so the arithmetic is checkable against §5.2
    # rather than against the codec's own table.
    ("rho", 255.99609375),            # §5.2.4 "Max. range = 256-(1/256) NM"
    ("cartesian", 255.9921875),       # §5.2.5 "Max. range = 256 NM"; the field reaches this
    ("flight_level", 2047.75),        # 14 bits two's complement at 1/4 FL
    ("height_3d", 204775.0),          # 14 bits two's complement at 25 ft
    ("doppler", 511.0),               # 10 bits two's complement at 1 m/s
    ("track_number", 4095.0),         # §5.2.18 "(0..4095)"
    ("sigma_position", 1.9921875),    # §5.2.21 "0<= Sigma(X)<2 NM"
])
def test_every_form_bound_is_the_documents_own_arithmetic(form, stated_max):
    low, high, lsb = codec.bounds(form)
    assert high == stated_max, f"{form} tops out at {high}, the document states {stated_max}"


def test_the_time_of_day_bound_is_the_stated_range_and_not_the_field_width():
    """§5.2.17's "Acceptable Range of values: 0<= Time-of-Day<=24 hrs", not 24 bits."""
    low, high, lsb = codec.bounds("tod")
    assert high == 86400.0
    field_width_max = (2 ** 24 - 1) * lsb
    assert field_width_max == pytest.approx(131071.9921875)
    assert high < field_width_max, (
        "the field can express times of day the item's stated range excludes, which is the "
        "whole reason the bound is the range rather than the width"
    )


def test_snap_refuses_out_of_range_and_never_clamps():
    with pytest.raises(codec.CodecError) as excinfo:
        codec.snap("rho", 400.0)
    message = str(excinfo.value)
    assert "400.0" in message and "255.99609375" in message, "the refusal must quote both"
    assert "clamping" in message and "masking" in message, (
        "the message has to say what it is NOT doing, or the next reader adds a clamp"
    )


@pytest.mark.parametrize("form", sorted(codec.FORMS))
def test_snap_moves_a_value_no_further_than_half_an_lsb_and_lands_exactly(form):
    low, high, lsb = codec.bounds(form)
    span = high - low
    for step in range(0, 97):
        value = low + span * step / 96.0
        snapped = codec.snap(form, value)
        assert abs(snapped - value) <= lsb / 2 + 1e-9, (
            f"{form}: snap moved {value} to {snapped}, further than half an LSB ({lsb})"
        )
        # And the result is exactly representable, which is the point of snapping at all.
        assert codec.from_raw(form, codec.to_raw(form, snapped)) == pytest.approx(snapped)


def test_twos_complement_refuses_rather_than_wrapping():
    assert codec.twos_to_raw(-1, 14) == 0x3FFF
    with pytest.raises(codec.CodecError, match="Refusing rather than wrapping"):
        codec.twos_to_raw(8192, 14)


def test_the_fspec_geometry_is_derived_from_table_2_not_from_part_1():
    """28 defined FRNs + 4 FX bits = 32 bits = 4 octets, from §5.3.1's own interleaving."""
    assert codec.MAX_FRN == 28
    assert codec.FSPEC_GROUPS == 7
    assert codec.MAX_FSPEC_OCTETS == 4
    assert codec.MAX_FRN + codec.MAX_FSPEC_OCTETS == 8 * codec.MAX_FSPEC_OCTETS, (
        "the identity that makes the stride checkable against the document: four groups of "
        "seven plus four FX bits is exactly 32 bits"
    )


def test_the_fspec_round_trips_and_the_fifth_octet_is_a_refusal():
    for frns in ([1], [1, 2, 3], [1, 7, 8, 14, 15, 21, 22, 28], list(range(1, 29))):
        octets = codec.write_fspec(frns)
        assert codec.read_fspec(octets, 0)[0] == frns
        assert len(octets) == (max(frns) - 1) // 7 + 1
    with pytest.raises(codec.CodecError, match="there is no FRN 29"):
        codec.read_fspec(bytes([0x01, 0x01, 0x01, 0x01]), 0)


def test_the_six_bit_alphabet_round_trips_and_refuses_an_undefined_character():
    for text in ("EXRDR01", "EXHELO2", "A", "12345678"):
        assert codec.decode_six_bit(codec.encode_six_bit(text)) == text
    with pytest.raises(codec.CodecError, match="does not define"):
        codec.encode_six_bit("LOWER!")


# =========================================================== the geodesy, and its audit


def test_the_slant_correction_figures_the_row_set_quotes():
    """Settlement 3's numbers, pinned. The correction is worst at SHORT range."""
    fl350_m = 35000.0 * codec.FEET_TO_METRES
    assert fl350_m / codec.METRES_PER_NM == pytest.approx(5.76, abs=0.005), (
        "the row set states a target at FL350 is 5.76 NM above the site"
    )
    assert fl350_m == pytest.approx(10.7 * 1000, abs=60), "…which is 10.7 km"
    # Directly overhead: slant range equals the height, so the ground range is zero and a
    # zero-height assumption would paint the contact its own altitude away from the antenna.
    overhead = codec.ground_range_m(fl350_m / codec.METRES_PER_NM, fl350_m)
    assert overhead == pytest.approx(0.0, abs=1e-6)
    # At 10 NM the error is still 1.83 NM; at 200 NM it is 0.08 NM, which is where the
    # "it is a small correction" intuition comes from and where it does not matter.
    at_ten = codec.ground_range_m(10.0, fl350_m) / codec.METRES_PER_NM
    assert 10.0 - at_ten == pytest.approx(1.83, abs=0.01)
    at_two_hundred = codec.ground_range_m(200.0, fl350_m) / codec.METRES_PER_NM
    assert 200.0 - at_two_hundred == pytest.approx(0.083, abs=0.002)


def test_the_impossible_geometry_is_a_named_gap():
    """Gap 28. The ruling shipped as a call-site comment and that was the wrong home for it.

    A decision nobody can find later is not a decision — the principle the whole `*_basis`
    discipline serves — so the row and the call site have to agree, and this asserts that they
    do.
    """
    section = _section_of_doc("## Gaps, and what each one costs")
    start = section.index("28. **No way to say a measurement is geometrically impossible.**")
    nxt = section.find("\n29. **", start)
    row = section[start:nxt if nxt != -1 else len(section)]
    assert "pressure altitude stands in for a geometric height" in row, "the cause"
    assert "Refuse the record" in row and "Rejected" in row, "the first rejected alternative"
    assert "Clamp the ground range to zero" in row, "the second rejected alternative"
    assert "at the antenna" in row, "…and why it is the dangerous one"
    assert "**Shipped.**" in row, "and the choice actually made"
    source = (PACKAGE / "adapters" / "cat048_codec.py").read_text()
    assert "gap 28" in source, "the call-site flag has to cite the row it now lives in"


def test_an_impossible_geometry_is_named_in_the_basis_and_the_record_translates():
    """The behaviour gap 28 rules, end to end.

    A pressure altitude far enough from the geometric height that |Δh| exceeds the slant range —
    which is the case the gap says arises in practice, not a contrived one.
    """
    parsed = json.loads(
        (FIXTURES / "injected_site_pressure_height_only.parsed.json").read_text())
    items = parsed["records"][0]["items"]
    # RHO 0.5 NM with the target still reporting FL350: |Δh| is 5.76 NM, so no ground range
    # exists. A short-range high-altitude report is exactly where the slant term dominates.
    # BOTH fields, because the twin carries the raw integer AND the decoded value and the
    # adapter reads the decoded one. Editing one is what `spec/build_fixtures.py` exists to
    # prevent — and setting only `rho_raw` here silently left the position derived, which is
    # a small demonstration of why the README says to edit the generator and never the twin.
    items["I048/040"]["rho_raw"] = codec.to_raw("rho", 0.5)
    items["I048/040"]["rho_nm"] = 0.5
    objects = adapter(sensor_position=SITE).to_cdm(parsed)
    assert len(objects) == 2, "the record translates in full — refusing it would be filtering"
    entity = next(o for o in objects if isinstance(o, Entity))
    assert entity.position is None, "…and clamping to zero would put it at the antenna"
    reason = entity.attributes["position_basis"]["reason"]
    assert "geometry is impossible" in reason
    assert "PRESSURE altitude" in reason, "the cause has to be in the reason, not just the rule"
    # The measurement is still carried, as in every other non-derived branch.
    assert entity.attributes["cat048_measured_position"]["rho_nm"] == 0.5


def test_an_impossible_geometry_yields_no_ground_range():
    fl350_m = 35000.0 * codec.FEET_TO_METRES
    assert codec.ground_range_m(1.0, fl350_m) is None


def test_the_ellipsoid_is_wgs84_and_not_merely_self_consistent():
    """The check `inverse(direct(...))` CANNOT make, and a mutation found the hole.

    Replacing WGS-84's semi-major axis with its semi-minor — a 21 km error — passed every other
    test in this file, because `direct` and `inverse` share the constants: the inversion audit
    proves the two functions are mutual inverses and says nothing about whether the ellipsoid is
    the right one. So the ellipsoid is pinned two ways here.

    First the constants, because they are a published standard rather than a derivation, and
    §4.3.2.2 names the ellipsoid by name ("a plane tangential to the WGS-84 Ellipsoid at the
    location of the radar head") without giving its parameters.
    """
    assert codec.WGS84_A == 6378137.0, "WGS-84 semi-major axis, metres"
    assert 1.0 / codec.WGS84_F == pytest.approx(298.257223563, abs=1e-9), "inverse flattening"
    assert codec.WGS84_B == pytest.approx(6356752.314245, abs=1e-6), "semi-minor, derived"

    # Then three distances published independently of any implementation. A wrong ellipsoid —
    # or a spherical one — misses every one of them, which is what the mutation needed.
    for lat1, lon1, lat2, lon2, published, label in (
        (0.0, 0.0, 0.0, 1.0, 111319.491, "one degree of longitude at the equator"),
        (0.0, 0.0, 1.0, 0.0, 110574.389, "one degree of latitude at the equator"),
        (0.0, 0.0, 90.0, 0.0, 10001965.729, "the quarter meridian"),
    ):
        computed = codec.inverse(lat1, lon1, lat2, lon2)[0]
        assert computed == pytest.approx(published, abs=0.001), (
            f"{label}: computed {computed} m against the published WGS-84 figure {published} m"
        )


@pytest.mark.parametrize("rho_nm", [0.1, 1.0, 10.0, 55.5, 137.99609375, 255.99609375])
@pytest.mark.parametrize("theta_deg", [0.0, 45.0, 123.75, 271.23046875, 359.9945068359375])
def test_the_geodesy_inverts_far_inside_the_items_own_lsbs(rho_nm, theta_deg):
    """The only audit available on arithmetic the pinned document does not supply."""
    distance = rho_nm * codec.METRES_PER_NM
    lat, lon = codec.direct(SITE[0], SITE[1], theta_deg, distance)
    back_m, back_deg = codec.inverse(SITE[0], SITE[1], lat, lon)
    rho_lsb_m = codec.bounds("rho")[2] * codec.METRES_PER_NM
    theta_lsb = codec.bounds("theta")[2]
    assert abs(back_m - distance) < rho_lsb_m / 100, (
        f"range recovered {back_m} m against {distance} m; RHO's own LSB is {rho_lsb_m} m"
    )
    angular_error = abs((back_deg - theta_deg + 180.0) % 360.0 - 180.0)
    assert angular_error < theta_lsb / 100, (
        f"bearing recovered {back_deg} against {theta_deg}; THETA's own LSB is {theta_lsb}"
    )


def test_a_derived_position_inverts_to_the_polar_values_the_record_states():
    """`derived_position_inverts_to_the_polar_values`, end to end through the adapter."""
    entity = entity_of("derived_position_inverts_to_the_polar_values", sensor_position=SITE)
    basis = entity.attributes["position_basis"]
    assert basis["derived"] is True
    back_m, back_deg = codec.inverse(SITE[0], SITE[1], entity.position.lat, entity.position.lon)
    slant_nm = (back_m ** 2 + basis["delta_h_m"] ** 2) ** 0.5 / codec.METRES_PER_NM
    assert abs(slant_nm - basis["rho_nm"]) < codec.bounds("rho")[2], (
        "the derived position must return RHO to within the item's own LSB"
    )
    assert abs(back_deg - basis["theta_deg"]) < codec.bounds("theta")[2], (
        "…and THETA to within its own LSB"
    )


# ================================================== geometry: the two branches and no third


def test_no_site_means_no_position_and_the_polar_values_are_still_parked():
    entity = entity_of("mode_s_roll_call_track")
    assert entity.position is None
    basis = entity.attributes["position_basis"]
    assert basis["derived"] is False
    assert "no sensor_position was injected" in basis["reason"]
    parked = entity.attributes["cat048_measured_position"]
    assert parked["rho_raw"] and parked["theta_raw"], (
        "the measurement is carried losslessly in BOTH branches — egress re-emits from these"
    )


def test_a_site_and_a_height_derive_a_position_from_the_same_octets():
    """One fixture, two constructions. The octets are identical and the CDM differs."""
    without = entity_of("derived_position_inverts_to_the_polar_values")
    with_site = entity_of("derived_position_inverts_to_the_polar_values", sensor_position=SITE)
    assert without.position is None
    assert with_site.position is not None
    assert without.attributes["cat048_measured_position"] == \
        with_site.attributes["cat048_measured_position"], (
        "the parked measurement must not depend on whether a site was injected"
    )


def test_the_declared_conversion_is_recorded_in_full():
    basis = entity_of("derived_position_inverts_to_the_polar_values",
                      sensor_position=SITE).attributes["position_basis"]
    assert basis["earth_model"] == "WGS-84"
    assert "WGS-84 Ellipsoid" in basis["earth_model_basis"], "§4.3.2.2's own ellipsoid"
    assert "local geographical north" in basis["azimuth_reference"], "§4.3.1"
    assert "sqrt(RHO" in basis["slant_treatment"]
    assert basis["height"]["item"] == "I048/110"
    assert "mean sea level" in basis["height"]["datum"]
    assert "THIS ADAPTER, not the specification" in basis["arithmetic_source"], (
        "gap 24's counter-argument has to ride on every derived position"
    )


def test_a_site_with_no_height_item_derives_nothing_and_still_translates():
    objects = translate("injected_site_no_height_item", sensor_position=SITE)
    entity = next(o for o in objects if isinstance(o, Entity))
    assert len(objects) == 2, "the record is NOT refused — suppressing it would be filtering"
    assert entity.position is None
    assert "no usable height item" in entity.attributes["position_basis"]["reason"]
    assert "10.7 km" in entity.attributes["position_basis"]["reason"], (
        "the reason must carry the number that makes a zero-height assumption indefensible"
    )


def test_a_pressure_altitude_is_used_and_the_approximation_is_named():
    entity = entity_of("injected_site_pressure_height_only", sensor_position=SITE)
    assert entity.position is not None
    height = entity.attributes["position_basis"]["height"]
    assert height["item"] == "I048/090"
    assert "PRESSURE altitude" in height["approximation"]


def test_no_position_is_derived_from_a_floor():
    """ERR set with RHO all-ones is §5.2.4 NOTE 4's bound, and a bound is not a measurement."""
    entity = entity_of("injected_site_range_at_maximum", sensor_position=SITE)
    assert entity.position is None
    assert "FLOOR" in entity.attributes["position_basis"]["reason"]
    assert "I048/040 RHO" in entity.attributes["unresolved_raw"]


def test_alt_m_and_accuracy_m_stay_none_even_when_a_position_exists():
    entity = entity_of("derived_position_inverts_to_the_polar_values", sensor_position=SITE)
    assert entity.position.alt_m is None, "MSL is not the ellipsoid; the geoid needs a model"
    assert entity.position.accuracy_m is None, "a per-axis sigma in a local grid is not 1-sigma"
    assert entity.position.position_source is PositionSource.ESTIMATED
    assert "NONE of them names a sensor measurement" in \
        entity.attributes["position_source_basis"]


def test_event_geometry_is_never_populated():
    for name in ("mode_s_roll_call_track", "derived_position_inverts_to_the_polar_values"):
        assert event_of(name, sensor_position=SITE).geometry is None


def test_i048_042_is_never_a_position_even_with_a_site():
    entity = entity_of("plot_characteristics_all_subfields", sensor_position=SITE)
    parked = entity.attributes["cat048_calculated_position"]
    assert parked["x_nm"] == -12.5 and parked["y_nm"] == 44.25
    assert "TCC in I048/170" in parked["basis"], "the cross-item join is declined by name"


def test_the_cross_adapter_geometry_divergence_has_a_cat048_leg():
    """The GMTIF amendment's test, extended.

    Each adapter in this repository sets `Position` on a different basis, and the differences
    are load-bearing rather than incidental: CAT021's arrives already decoded, GMTIF's is an
    exact binary angle its own tables define, and CAT048's exists ONLY when the caller supplies
    a site the format never carries.
    """
    same_octets = block_of("derived_position_inverts_to_the_polar_values")
    assert adapter().to_cdm(same_octets)[0].position is None
    assert adapter(sensor_position=SITE).to_cdm(same_octets)[0].position is not None, (
        "CAT048 is the only adapter here whose Position depends on a constructor argument, and "
        "that is the divergence this test exists to pin"
    )


# ================================================================== time, and its boundary


def test_time_of_day_exactly_86400_is_accepted_on_the_stated_range():
    event = event_of("time_of_day_exactly_86400")
    basis = event.payload["observed_at_basis"]
    assert basis["time_of_day_s"] == 86400.0
    assert basis["time_of_day_raw"] == 11_059_200
    assert "INCLUSIVE stated range" in basis["boundary"]
    assert "ambiguity 1" in basis["boundary"] and "ambiguity 14" in basis["boundary"]
    # 86 400 s after some midnight IS a midnight, so the resolved instant is on a day boundary.
    assert event.observed_at.time() == dt.time(0, 0, 0)


def test_time_of_day_one_lsb_past_86400_is_refused():
    with pytest.raises(Cat048ParseError) as excinfo:
        adapter().to_cdm((REFUSALS / "time_of_day_one_lsb_past_86400.cat048").read_bytes())
    message = str(excinfo.value)
    assert "11059201" in message and "86400" in message
    assert "modulo" in message, "the refusal has to say what it is refusing to do instead"


def test_the_two_boundary_fixtures_are_one_lsb_apart():
    """Accept-and-refuse on adjacent raw values, so the edge is pinned and not the direction."""
    accepted = json.loads((FIXTURES / "time_of_day_exactly_86400.parsed.json").read_text())
    refused = parse_block(
        (REFUSALS / "time_of_day_one_lsb_past_86400.cat048").read_bytes())
    a = accepted["records"][0]["items"]["I048/140"]["time_of_day_raw"]
    b = refused["records"][0]["items"]["I048/140"]["time_of_day_raw"]
    assert b - a == 1, f"the fixtures are {b - a} units apart, not one LSB"


def test_the_midnight_rollover_runs_in_both_directions():
    """Each direction with the clock that makes it a rollover at all.

    The shared harness clock is 06:15, at which BOTH fixtures resolve to the receipt date and
    neither exercises anything — so the clock is injected here per direction. That is the point
    of an injectable clock, and it is why these two fixtures assert nothing under the harness
    beyond their golden files.
    """
    before = AsterixCat048Adapter(clock=times.frozen_clock(
        dt.datetime(2026, 4, 30, 0, 0, 1, 100000, tzinfo=dt.timezone.utc)))
    event = next(o for o in before.to_cdm(block_of("midnight_rollover_before"))
                 if isinstance(o, Event))
    assert "previous day" in event.payload["observed_at_basis"]["date_from"]
    assert event.observed_at.date() == dt.date(2026, 4, 29), (
        "23:59:58.500 delivered at 00:00:01.100 belongs to the PREVIOUS day — picking the "
        "receipt date would date it 24 hours late"
    )
    after = AsterixCat048Adapter(clock=times.frozen_clock(
        dt.datetime(2026, 4, 29, 23, 59, 59, 700000, tzinfo=dt.timezone.utc)))
    event = next(o for o in after.to_cdm(block_of("midnight_rollover_after"))
                 if isinstance(o, Event))
    assert "next day" in event.payload["observed_at_basis"]["date_from"]
    assert event.observed_at.date() == dt.date(2026, 4, 30), (
        "the same rule run the other way, which is the direction an adapter that special-cased "
        "'subtract a day' gets wrong"
    )


def test_a_record_with_no_time_item_falls_to_the_clock_and_is_not_refused():
    objects = translate("no_time_item_at_all")
    event = next(o for o in objects if isinstance(o, Event))
    basis = event.payload["observed_at_basis"]
    assert basis["item"] is None
    assert "failure of all sources of time-stamping" in basis["reason"]
    assert event.observed_at == event.received_at
    entity = next(o for o in objects if isinstance(o, Entity))
    assert any("I048/140" in field for field in entity.attributes["unavailable_fields"]), (
        "a STATED absence goes to unavailable_fields, not to unresolved_raw"
    )
    assert "I048/140" not in json.dumps(entity.attributes["unresolved_raw"])


def test_cat021s_guard_is_untouched():
    """Ambiguity 14 is recorded, not harmonised. This asserts the divergence still exists."""
    from synapse_cdm.adapters import asterix_cat021
    source = pathlib.Path(asterix_cat021.__file__).read_text()
    assert "if seconds >= SECONDS_PER_DAY:" in source, (
        "CAT021 refuses exactly 86 400.000 s and CAT048 accepts it, on different recorded "
        "bases. If this line changed, ambiguity 14 was silently harmonised — which the row "
        "explicitly says not to do"
    )
    assert codec.bounds("tod")[1] == float(asterix_cat021.SECONDS_PER_DAY), (
        "the two adapters agree on the NUMBER and disagree on whether it is admissible; if "
        "they stopped agreeing on the number the finding would need rewriting"
    )


# ============================================================================== identity


def test_identity_is_the_aircraft_address_when_present():
    entity = entity_of("mode_s_roll_call_track")
    assert [(s.system, s.external_id) for s in entity.source_ids] == [(ICAO_SYSTEM, "0029AB")]
    assert entity.entity_id == ids.derive(ICAO_SYSTEM, "0029AB", kind="entity")


def test_the_icao24_derivation_agrees_with_the_sibling_adapters_without_a_join():
    """Settlement 11. The same pure function, not a correlation."""
    from synapse_cdm.adapters import adsb, asterix_cat021
    assert ICAO_SYSTEM == adsb.ICAO_SYSTEM == asterix_cat021.ICAO_SYSTEM
    entity = entity_of("icao24_shared_with_cat021")
    assert entity.entity_id == ids.derive(adsb.ICAO_SYSTEM, "0029AB", kind="entity"), (
        "one airframe seen by a radar and by an ADS-B ground station derives the SAME "
        "entity_id, which is what lets fusion join them where the join is audited"
    )


def test_a_report_with_no_address_gets_a_report_scoped_identity():
    entity = entity_of("psr_only_plot_no_identity")
    system, external_id = entity.source_ids[0].system, entity.source_ids[0].external_id
    assert system == REPORT_SYSTEM
    assert "2525" in external_id, "the SAC/SIC scopes it"
    assert "not the I048/161 track number" in entity.attributes["identity_basis"].lower() or \
        "NOT the I048/161" in entity.attributes["identity_basis"]


def test_the_track_number_is_never_an_identity_key():
    """Settlement 9's reversal, pinned as a test rather than as prose."""
    entity = entity_of("psr_plot_with_track_number_only")
    assert entity.source_ids[0].system == REPORT_SYSTEM
    parked = entity.attributes["track_number"]
    assert parked["track_number"] == 199
    assert "NEVER AN IDENTITY KEY" in parked["basis"]
    assert "gap 27" in parked["basis"].lower()
    assert str(199) not in entity.source_ids[0].external_id.split("|")[0]


def test_two_scans_of_one_track_number_produce_two_different_entities():
    """The truncation gap 27 names, asserted as behaviour.

    This test asserts a LOSS on purpose: the radar states continuity and the CDM cannot carry
    it. The alternative — keying on the recycled number — would merge two airframes, which is a
    false statement, and this repository refuses false statements and names truncations.
    """
    objects = translate("psr_track_two_scans_same_track_number")
    entities = [o for o in objects if isinstance(o, Entity)]
    assert len(entities) == 2
    numbers = {e.attributes["track_number"]["track_number"] for e in entities}
    assert numbers == {199}, "both records state the same track number"
    assert entities[0].entity_id != entities[1].entity_id, (
        "and they must NOT collapse into one entity"
    )
    for entity in entities:
        assert any("ap 27" in field for field in entity.attributes["unavailable_fields"])


def test_a_duplicated_address_code_becomes_an_identity_caveat():
    parsed = json.loads((FIXTURES / "mode_s_roll_call_track.parsed.json").read_text())
    parsed["records"][0]["items"]["I048/030"] = {
        "codes": [{"code": 16, "text": WARNING_ERROR_TEXT[16]}]}
    entity = next(o for o in adapter().to_cdm(parsed) if isinstance(o, Entity))
    assert "may not be unique" in entity.attributes["identity_caveat"]


# ================================================== entity type, affiliation, severity


@pytest.mark.parametrize("name,expected", [
    ("psr_only_plot_no_identity", EntityType.UNKNOWN),      # TYP 1, a primary echo
    ("no_detection_track_only", EntityType.UNKNOWN),        # TYP 0, no detection
    ("mode_s_roll_call_track", EntityType.PLATFORM),        # TYP 5, a transponder replied
])
def test_entity_type_comes_from_the_mandatory_descriptor(name, expected):
    assert entity_of(name).entity_type is expected


def test_the_classification_codes_do_not_refine_the_entity_type():
    """I048/030's own Note 7 makes the item implementation-specific."""
    entity = entity_of("helicopter_classification_not_read_as_a_type")
    assert entity.entity_type is EntityType.PLATFORM
    assert any(c["code"] == 24 for c in entity.attributes["cat048_warning_error_codes"])
    assert "implementation specific" in entity.attributes["entity_type_basis"]


def test_affiliation_is_unknown_and_the_iff_decline_rides_on_every_object():
    entity = entity_of("mode_4_result_in_ref")
    assert entity.affiliation is Affiliation.UNKNOWN
    assert entity.symbol is not None and len(entity.symbol) == 20
    basis = entity.attributes["affiliation_basis"]
    assert "Friendly target" in basis and "IFF authority" in basis
    assert entity.attributes["mode_4_foe_fri"]["value"] == 0
    assert "ambiguous" in entity.attributes["mode_4_foe_fri"]["basis"]


def test_military_emergency_is_the_only_bit_that_raises_severity():
    event = event_of("military_emergency")
    assert event.severity is Severity.CRITICAL
    assert event.event_type is EventType.ALERT
    assert "Military emergency" in event.payload["severity_basis"]["raised_by"]


def test_a_mode_s_alert_and_an_active_advisory_do_not_raise_severity():
    event = event_of("mode_s_alert_is_not_an_emergency")
    assert event.severity is Severity.INFO
    declined = " ".join(event.payload["severity_basis"]["declined"])
    assert "STAT = 2" in declined
    assert "generated in the LAST SCAN" in declined, (
        "the I048/260 decline must carry the Definition/Encoding Rule tension, which is a "
        "weaker and more specific ground than CAT021's judgement argument"
    )
    assert "I021/008" in declined, "and it must name the divergence from CAT021 explicitly"


@pytest.mark.parametrize("name,expected", [
    ("mode_s_roll_call_track", EventType.DETECTION),
    ("no_detection_track_only", EventType.TRACK_UPDATE),
    ("end_of_track_full_items", EventType.STATUS_CHANGE),
])
def test_event_type_is_read_from_typ_and_overridden_by_tre(name, expected):
    assert event_of(name).event_type is expected


def test_confidence_and_track_quality_stay_none():
    entity = entity_of("track_quality_vector")
    assert entity.confidence is None
    parked = entity.attributes["cat048_track_quality"]
    assert parked["sigma_x_nm"] > 0, "the vector is carried in the source's own units"
    assert "not a probability" in parked["basis"]


# ============================================================== the End of Track Message


def test_a_track_end_record_does_not_close_the_entity():
    """Settlement 8's reversal. A first draft set `valid_to` here and it was wrong."""
    entity = entity_of("end_of_track_full_items")
    assert entity.valid_to is None, (
        "TRE ends 'a track record within a particular track file' (§5.2.18), not the airframe "
        "the entity_id names. Closing the interval would be a false statement"
    )
    assert entity.attributes["track_end"]["tre"] is True
    assert "gap 26" in entity.attributes["track_end"]["basis"].lower()


def test_no_cat048_fixture_ever_sets_valid_to():
    """A negative assertion over the whole set, which is stronger than one fixture."""
    for path in blocks():
        for obj in adapter(sensor_position=SITE).to_cdm(path.read_bytes()):
            if isinstance(obj, Entity):
                assert obj.valid_to is None, f"{path.name} closed an entity's interval"


def test_the_edition_1_30_relaxation_is_a_permitted_absence_and_not_a_refusal():
    entity = entity_of("end_of_track_items_omitted")
    fields = " ".join(entity.attributes["unavailable_fields"])
    for item in ("I048/220", "I048/230", "I048/240", "I048/250"):
        assert item in fields, f"{item}'s permitted absence must be recorded"
    assert "PERMITTED absence" in fields
    assert "I048/220" not in json.dumps(entity.attributes["unresolved_raw"])


def test_a_mode_s_record_without_tre_still_requires_the_address():
    with pytest.raises(Cat048ParseError) as excinfo:
        adapter().to_cdm((REFUSALS / "mode_s_target_missing_address.cat048").read_bytes())
    assert "End of Track Message" in str(excinfo.value)


def test_egress_never_adds_a_relaxed_item_that_did_not_arrive():
    """The recommendation is honoured by FIDELITY, not by policy."""
    original = block_of("end_of_track_items_omitted")
    objects = adapter().to_cdm(original)
    emitted = adapter().from_cdm([o for o in objects if isinstance(o, Entity)])
    assert emitted == original
    for item in ("I048/220", "I048/230", "I048/240", "I048/250"):
        assert item not in parse_block(emitted)["records"][0]["items"]


# ================================================================== items and their rows


def test_i048_030_is_an_ordered_set_with_duplicates_preserved():
    entity = entity_of("warning_error_code_series")
    codes = [entry["code"] for entry in entity.attributes["cat048_warning_error_codes"]]
    assert codes == [0, 15, 33, 34, 9, 96], "WIRE ORDER, never sorted and never deduplicated"
    assert "WIRE ORDER" in entity.attributes["cat048_warning_error_basis"]


def test_code_0_is_accepted_and_the_manufacturer_range_is_unresolved():
    entity = entity_of("warning_error_code_series")
    assert any("code 0" in field for field in entity.attributes["unavailable_fields"])
    assert "I048/030 code 96" in entity.attributes["unresolved_raw"]
    assert "manufacturer range" in entity.attributes["unresolved_raw"]["I048/030 code 96"][
        "reason"]


def test_codes_33_or_34_without_15_is_a_non_conformance_and_not_a_refusal():
    parsed = json.loads((FIXTURES / "mode_s_roll_call_track.parsed.json").read_text())
    parsed["records"][0]["items"]["I048/030"] = {
        "codes": [{"code": c, "text": WARNING_ERROR_TEXT[c]} for c in (33,)]}
    entity = next(o for o in adapter().to_cdm(parsed) if isinstance(o, Entity))
    assert "also Code 15 shall be sent" in entity.attributes[
        "cat048_warning_error_nonconformance"]


def test_code_37_records_that_its_meaning_is_a_pointer_into_the_unpinned_ref():
    entity = entity_of("warning_error_code_37")
    assert "I048/030 code 37" in entity.attributes["unresolved_raw"]
    assert "Reserved Expansion Field" in \
        entity.attributes["unresolved_raw"]["I048/030 code 37"]["reason"]
    exposed = entity.attributes["reserved_expansion_basis"]["exposed_to"]
    assert any("code 37" in item for item in exposed)


def test_the_ic_conflict_codes_record_that_the_area_lives_in_cat034():
    entity = entity_of("ic_conflict_codes")
    assert "Message Type 008" in entity.attributes["ic_conflict_basis"]
    assert "target acquisition phase" in entity.attributes["ic_conflict_basis"]


def test_the_three_altitudes_are_three_quantities_and_none_reaches_alt_m():
    entity = entity_of("three_altitudes_disagreeing", sensor_position=SITE)
    assert entity.attributes["flight_level"]["flight_level"] == 350.0
    assert entity.attributes["height_3d_ft"]["height_ft"] == 35600.0
    assert "mean sea level" in entity.attributes["height_3d_ft"]["datum"]
    disagreement = entity.attributes["cat048_altitude_disagreement"]
    assert disagreement["difference_ft"] == pytest.approx(600.0)
    assert "NEVER ADJUDICATED" in disagreement["basis"]
    assert "BARE NUMERIC COMPARISON IS ITSELF A DEFECT" in disagreement["basis"]
    # The source's own codes for the disagreement, named rather than re-derived.
    stated = entity.attributes["altitude_basis"]["source_stated_disagreement"]
    assert set(stated) == {12, 18}
    assert entity.position.alt_m is None


def test_the_mode_c_reply_is_never_gray_decoded():
    entity = entity_of("three_altitudes_disagreeing")
    unresolved = entity.attributes["unresolved_raw"]["I048/100 Mode-C reply"]
    assert unresolved["gray_raw"] == 0b101010101010
    assert "EXISTS TO REPORT THAT THE ALTITUDE COULD NOT BE ESTABLISHED" in unresolved["reason"]


def test_a_negative_flight_level_needs_the_two_s_complement_reading():
    entity = entity_of("flight_level_negative")
    assert entity.attributes["flight_level"]["flight_level"] == -12.5, (
        "an unsigned read of the same 14 bits puts the aircraft near FL 4000"
    )


def test_i048_200_becomes_course_deg_on_the_definition_and_the_note():
    entity = entity_of("mode_s_roll_call_track")
    assert entity.kinematics.course_deg == pytest.approx(91.5, abs=0.006)
    assert entity.kinematics.speed_mps == pytest.approx(0.13 * codec.METRES_PER_NM, abs=0.01)
    assert entity.kinematics.climb_mps is None, "CAT048 states no vertical rate anywhere"
    basis = entity.attributes["course_basis"]["course_basis"]
    assert "DEFINITION" in basis and "geographical North at the aircraft position" in basis
    assert "does not govern" in basis, "the field label must be named as non-governing"


def test_the_groundspeed_lsb_is_exact_in_float64():
    assert codec.bounds("groundspeed")[2] * codec.METRES_PER_NM == 0.113037109375


def test_i048_120_parks_and_reaches_no_kinematics_field():
    entity = entity_of("radial_doppler_calculated")
    assert entity.kinematics is None, "this fixture carries no I048/200"
    parked = entity.attributes["radial_doppler"]
    assert parked["calculated"]["calculated_doppler_mps"] == -142.0
    assert parked["calculated"]["doubtful"] is True
    assert "implementation dependent" in parked["sign_basis"]
    assert "NOT applied as an assumption" in parked["sign_basis"]
    assert "gap 25" in parked["basis"].lower()


def test_both_doppler_subfields_is_a_non_conformance_and_not_a_refusal():
    entity = entity_of("radial_doppler_both_subfields")
    parked = entity.attributes["radial_doppler"]
    assert "only one secondary subfield shall be present" in parked["nonconformance"]
    assert "NEITHER IS A PROPERTY OF THE TARGET" in parked["raw_basis"]


def test_a_spare_presence_bit_in_the_doppler_primary_is_a_refusal():
    with pytest.raises(Cat048ParseError, match="Spare"):
        adapter().to_cdm((REFUSALS / "radial_doppler_spare_presence_bit.cat048").read_bytes())


def test_the_plot_characteristics_maxima_are_floors():
    entity = entity_of("plot_characteristics_all_subfields")
    parked = entity.attributes["plot_characteristics"]
    assert parked["sam"]["ssr_amplitude_dbm"] == -71.0, "two's complement per its own note"
    for flag in ("rpd", "apd"):
        assert "FLOOR" in parked[flag]["at_or_beyond_maximum"]
    assert "copy-paste from subfield #6" in parked["apd_note_wording"]


def test_the_bds_registers_are_parked_and_zero_zero_is_not_register_zero():
    event = event_of("bds_registers_comm_b_broadcast")
    registers = event.payload["cat048_bds_registers"]
    assert registers[0]["extraction"] == "Comm-B broadcast, register unidentified"
    assert registers[1]["extraction"] == "GICB register 4,0"
    entity = entity_of("bds_registers_comm_b_broadcast")
    assert "NOT register 0,0" in entity.attributes["bds_registers"]["basis"]


def test_the_acas_advisory_is_carried_undecoded_with_both_of_its_sentences():
    entity = entity_of("acas_ra_active_undecoded")
    parked = entity.attributes["acas_ra_active"]
    assert parked["acas_ra"] == "3141592653589a"
    assert "Currently active" in parked["definition"]
    assert "generated in the last scan" in parked["encoding_rule"]
    assert "ASSERT DIFFERENT THINGS" in parked["basis"]
    assert "ICAO Draft SARPs" in parked["decode_declined"]
    assert "SPLIT ACROSS TWO ITEMS" in parked["acas_xu_split"]
    assert "I048/260 ACASRA" in entity.attributes["unresolved_raw"]


def test_the_reserved_expansion_field_is_parked_for_a_procedural_reason():
    entity = entity_of("reserved_expansion_field_carried")
    parked = entity.attributes["reserved_expansion_field"]
    assert parked["contents"] == "0102030405"
    assert "PROCEDURAL" in parked["basis"]
    assert "public download that was identified and simply not acquired" in parked["basis"]
    assert "Weaker than GMTIF" in parked["basis"], (
        "the park must say it is weaker than the two precedents it resembles"
    )


def test_a_record_carrying_an_re_field_round_trips_without_being_interpreted():
    original = block_of("reserved_expansion_field_carried")
    parsed = parse_block(original)
    assert set(parsed["records"][0]["items"]) >= {"RE", "SP"}
    objects = adapter().to_cdm(original)
    assert adapter().from_cdm([o for o in objects if isinstance(o, Entity)]) == original


def test_the_special_purpose_field_is_never_written_for_an_object_without_one():
    without = adapter().to_cdm(block_of("mode_s_roll_call_track"))
    entity = next(o for o in without if isinstance(o, Entity))
    assert "special_purpose_field" not in entity.attributes
    emitted = adapter().from_cdm([entity])
    assert "SP" not in parse_block(emitted)["records"][0]["items"]


def test_the_mode_code_l_bit_means_different_things_per_item():
    entity = entity_of("mode_1_and_mode_2_with_confidence")
    assert "not extracted during the last scan" in entity.attributes["mode_3a_code"]["basis"]
    assert entity.attributes["mode_2_code"]["l"] == 1
    assert entity.attributes["mode_1_code"]["l"] == 1
    assert "code_confidence" in entity.attributes


def test_the_aircraft_identification_records_that_the_alphabet_is_not_this_documents():
    entity = entity_of("mode_s_roll_call_track")
    assert entity.attributes["aircraft_identification"] == "EXRDR01"
    basis = entity.attributes["aircraft_identification_basis"]
    assert "THIS DOCUMENT STATES NO CHARACTER TABLE" in basis
    assert "ED-73F/DO-181F" in basis and "gap 1" in basis


def test_a_ghost_target_is_translated_in_full():
    objects = translate("ghost_target_still_translated")
    assert len(objects) == 2, "suppressing it would be the filtering the contract refuses"
    entity = next(o for o in objects if isinstance(o, Entity))
    assert entity.attributes["ghost_target"]["gho"] is True
    assert "IN FULL" in entity.attributes["ghost_target"]["basis"]


def test_invalid_and_unknown_track_codes_land_in_different_bags():
    entity = entity_of("radial_ambiguity_rad_invalid")
    assert "I048/170 RAD" in entity.attributes["unresolved_raw"], "'Invalid' is unresolved_raw"
    assert any("CDM" in field for field in entity.attributes["unavailable_fields"]), \
        "'Unknown' is a stated absence"


def test_the_data_source_row_carries_the_5_2_1_grounding():
    """The Phase 1 close-out asked for the Definition and the Encoding Rule in the prose."""
    basis = entity_of("mode_s_roll_call_track").attributes["data_source"]["basis"]
    assert "from which the data is received" in basis, "§5.2.1's Definition"
    assert "present in every ASTERIX record" in basis, "§5.2.1's Encoding Rule"
    assert "NOT a SourceId" in basis


# ================================================================ framing and the gate


def test_the_mandatory_items_are_the_two_the_document_names():
    assert MANDATORY_ITEMS == ("I048/010", "I048/020")


@pytest.mark.parametrize("name,fragment", [
    ("wrong_category", "not 48"),
    ("length_disagrees_with_buffer", "LEN says"),
    ("missing_mandatory_data_source", "I048/010"),
    ("trailing_fspec_fx_set", "no FRN 29"),
    ("track_status_second_extent", "§5.2.19"),
    ("descriptor_sixth_extension", "§5.2.2"),
    ("plot_characteristics_second_primary_octet", "§5.2.16"),
    ("records_do_not_tile_len", "block has"),
])
def test_every_structural_refusal_quotes_its_own_cause(name, fragment):
    with pytest.raises(Cat048ParseError) as excinfo:
        adapter().to_cdm((REFUSALS / f"{name}.cat048").read_bytes())
    assert fragment in str(excinfo.value), (
        f"{name} raised, but for the wrong stated reason: {excinfo.value}"
    )


def test_a_failed_block_emits_no_partial_set_of_objects():
    """A partial SET that looks complete is forbidden exactly as a partial object is."""
    data = (REFUSALS / "records_do_not_tile_len.cat048").read_bytes()
    with pytest.raises(Cat048ParseError):
        adapter().to_cdm(data)
    # And the good record inside it would have translated on its own, so the refusal is a
    # decision about the BLOCK rather than a failure to parse anything at all.
    good = parse_block(block_of("mode_s_roll_call_track"))
    assert len(good["records"]) == 1


def test_the_integrity_basis_says_there_is_no_checksum():
    basis = entity_of("mode_s_roll_call_track").attributes["integrity_basis"]
    assert "NO checksum at any level" in basis
    assert "weaker than a CRC" in basis, "the difference has to be named, not smoothed over"


def test_spare_bits_survive_the_round_trip_unnormalised():
    original = block_of("spare_bits_nonzero")
    parsed = parse_block(original)
    items = parsed["records"][0]["items"]
    assert items["I048/161"]["spare_bits_16_13"] == 0b1011
    assert items["I048/170"]["extent"]["spare_bits_4_2"] == 0b101
    assert items["I048/050"]["spare_bit_13"] == 1
    assert items["I048/230"]["spare_bit_9"] == 1
    objects = adapter().to_cdm(original)
    assert adapter().from_cdm([o for o in objects if isinstance(o, Entity)]) == original, (
        "§4.4 only RECOMMENDS zeroing spare bits, so normalising would break the round trip "
        "on exactly the traffic most worth investigating"
    )


def test_a_longer_than_necessary_fspec_is_re_emitted_as_read():
    original = block_of("fspec_longer_than_necessary")
    parsed = parse_block(original)
    assert len(bytes.fromhex(parsed["records"][0]["fspec"])) == 4, (
        "four octets for three FRNs — legal, and not what write_fspec would produce"
    )
    objects = adapter().to_cdm(original)
    assert adapter().from_cdm([o for o in objects if isinstance(o, Entity)]) == original


def test_the_item_layouts_sum_to_the_standards_own_byte_counts():
    """The generator's own check, run from the suite so it cannot be skipped."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cat048_build_fixtures", FIXTURES / "spec" / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.check_layouts()


# ================================================================= both directions, all


@pytest.mark.parametrize("path", blocks(), ids=lambda p: p.stem)
def test_every_fixture_round_trips_byte_exactly(path):
    """The check the harness reports as SKIP for a binary adapter. Byte equality, not values."""
    original = path.read_bytes()
    objects = adapter(sensor_position=SITE).to_cdm(original)
    entities = [o for o in objects if isinstance(o, Entity)]
    emitted = adapter(sensor_position=SITE).from_cdm(entities)
    assert emitted == original, (
        f"{path.name}: round trip differs\n  in:  {original.hex()}\n  out: {emitted.hex()}"
    )


@pytest.mark.parametrize("path", blocks(), ids=lambda p: p.stem)
def test_the_twin_parses_to_what_the_octets_parse_to(path):
    twin = json.loads(path.with_suffix(".parsed.json").read_text())
    assert parse_block(path.read_bytes()) == twin, (
        f"{path.name}: the twin has drifted from the octets. Edit the generator, not either"
    )


@pytest.mark.parametrize("path", blocks(), ids=lambda p: p.stem)
def test_the_octets_and_the_twin_produce_identical_cdm(path):
    twin = json.loads(path.with_suffix(".parsed.json").read_text())
    from_bytes = adapter(sensor_position=SITE).to_cdm(path.read_bytes())
    from_twin = adapter(sensor_position=SITE).to_cdm(twin)
    assert [o.model_dump(mode="json") for o in from_bytes] == \
        [o.model_dump(mode="json") for o in from_twin]


def test_egress_refuses_a_cdm_native_track_on_the_re_grounded_basis():
    track = Track(
        source=adapter().source_ref(),
        source_ids=[{"system": "X", "external_id": "1"}],
        track_id=uuid.uuid4(), entity_id=uuid.uuid4(),
        samples=[TrackSample(position={"lat": 57.0, "lon": 23.0,
                                       "position_source": PositionSource.ESTIMATED},
                             observed_at=CLOCK())],
    )
    with pytest.raises(Cat048ParseError) as excinfo:
        adapter(sensor_position=SITE).from_cdm([track])
    message = str(excinfo.value)
    assert "NARROWS the reason" in message, "settlement 3 changed why, not whether"
    assert "invertible" in message, "the transform is no longer the obstacle"
    assert "no SAC/SIC anywhere in a Track" in message
    assert "delta-h" in message
    assert "locates a system" in message and "NAME one" in message


def test_egress_refuses_a_foreign_entity_and_names_the_missing_inputs():
    foreign = Entity(
        source=adapter().source_ref(),
        source_ids=[{"system": "X", "external_id": "1"}],
        entity_id=uuid.uuid4(), entity_type=EntityType.PLATFORM,
        affiliation=Affiliation.UNKNOWN, valid_from=CLOCK(),
    )
    with pytest.raises(Cat048ParseError) as excinfo:
        adapter(sensor_position=SITE).from_cdm([foreign])
    message = str(excinfo.value)
    assert "did not come from CAT048" in message
    assert "cat048_fspec" in message
    assert "the site position, which a caller may now supply" in message, (
        "the refusal must say what is NOT on the missing list any more"
    )


def test_egress_re_encodes_from_the_parsed_items_and_checks_the_parked_octets():
    """The self-check that makes byte-exactness a proven property rather than a copy."""
    parsed = parse_block(block_of("mode_s_roll_call_track"))
    record = parsed["records"][0]
    record["items"]["I048/010"]["sac"] = 0x26          # change a value, not the parked octets
    with pytest.raises(Cat048ParseError, match="re-encoding I048/010 produced"):
        build_block([record])


def test_the_derived_position_is_not_the_source_of_any_emitted_byte():
    """Egress re-emits the parked integers, so a conversion defect cannot reach the wire."""
    original = block_of("derived_position_inverts_to_the_polar_values")
    objects = adapter(sensor_position=SITE).to_cdm(original)
    entity = next(o for o in objects if isinstance(o, Entity))
    assert entity.position is not None
    entity.attributes["position_basis"]["derived"] = "tampered"
    assert adapter().from_cdm([entity]) == original


# =========================================================== the row set claims the code


def test_the_row_set_claims_this_adapter():
    """The inverted Phase 1 test: it fails if a row still says `not yet`."""
    rows = [line for line in _section().splitlines()
            if line.startswith("|") and not line.startswith("|---")]
    stale = [line for line in rows if "`not yet`" in line]
    assert not stale, (
        f"{len(stale)} CAT048 row(s) still say `not yet` while adapters/asterix_cat048.py "
        f"implements the row set: {[r[:90] for r in stale[:3]]}"
    )
    mapped = [line for line in rows if "`cat048 1.0.0" in line]
    assert len(mapped) >= 130, (
        f"the CAT048 row set is down to {len(mapped)} claimed rows, below the 28-FRN roster it "
        "transcribes"
    )


def test_the_status_column_legend_names_this_adapters_markers():
    legend = _section_of_doc("## The status column")
    for marker in ("`cat048 1.0.0`", "`cat048 1.0.0 · parked`", "`cat048 1.0.0 · egress`"):
        assert marker in legend, f"{marker} is used in the row set and not defined in the legend"


def _section_of_doc(heading: str) -> str:
    text = DOC.read_text()
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start:nxt if nxt != -1 else len(text)]


@pytest.mark.parametrize("entry", UAP, ids=lambda e: e[1])
def test_every_uap_item_has_a_disposition_row(entry):
    """All 28 FRNs, keyed on §5.3.1's Table 2 — the sole item roster in Edition 1.32."""
    frn, item, _name, _uap_name, _rule, _decode, _encode = entry
    section = _section()
    needle = item if item.startswith("I048/") else f"`{item}`"
    assert needle in section, f"FRN {frn} ({item}) has no row in the CAT048 section"


def test_the_uap_is_the_whole_roster_and_nothing_more():
    assert [e[0] for e in UAP] == list(range(1, 29))
    assert len({e[1] for e in UAP}) == 28
    assert set(FRN_BY_ITEM) == {e[1] for e in UAP}
    assert set(ENCODERS) == {e[1] for e in UAP}


def test_the_i048_030_table_is_complete_from_0_to_37():
    assert sorted(WARNING_ERROR_TEXT) == list(range(0, 38)), (
        "the table is transcribed from Edition 1.32's own text; a lossy transcription of a "
        "38-row table shows as missing integers"
    )
    assert "REF" in WARNING_ERROR_TEXT[37], "code 37 is 1.32's own addition"
    assert "no conflict currently detected" in WARNING_ERROR_TEXT[36]


def test_the_settlements_are_each_referenced_from_the_code():
    """A settlement nobody cites from the implementation is prose, not a ruling."""
    source = (PACKAGE / "adapters" / "asterix_cat048.py").read_text()
    source += (PACKAGE / "adapters" / "cat048_codec.py").read_text()
    for number in range(1, 12):
        assert f"ettlement {number}" in source or f"ettlements {number}" in source, (
            f"settlement {number} is in the row set and cited nowhere in the adapter"
        )


@pytest.mark.parametrize("gap", [1, 9, 14, 17, 24, 25, 26, 27])
def test_every_gap_the_row_set_names_is_cited_from_the_code(gap):
    source = (PACKAGE / "adapters" / "asterix_cat048.py").read_text()
    source += (PACKAGE / "adapters" / "cat048_codec.py").read_text()
    assert re.search(rf"[Gg]aps? {gap}\b", source) or re.search(rf"\b{gap}\b(?= and )", source), (
        f"gap {gap} is named in the CAT048 row set and cited nowhere in the adapter"
    )


def test_the_transforms_bag_is_empty_and_says_why():
    assert AsterixCat048Adapter.TRANSFORMS == {}, (
        "a declared transform is an EXEMPTION from the never-drop check, and this adapter "
        "parks every wire value verbatim as well as converting it"
    )


def test_the_adapter_shares_no_code_with_cat021():
    """The Part 1 finding, enforced. CAT048's FSPEC is its own."""
    for module in ("asterix_cat048.py", "cat048_codec.py"):
        source = (PACKAGE / "adapters" / module).read_text()
        imports = re.findall(r"^\s*(?:from|import)\s+\S*asterix_cat021\S*", source, re.M)
        assert not imports, (
            f"{module} imports from asterix_cat021: {imports}. The FSPEC mechanics were "
            "re-derived from CAT048's own Table 2, and importing CAT021's would create the "
            "appearance of a common Part 1 basis that this repository does not have"
        )
