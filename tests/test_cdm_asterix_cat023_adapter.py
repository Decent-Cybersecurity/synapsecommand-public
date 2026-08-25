"""ASTERIX CAT023 — the adapter against the row set that specified it. Adapter #14.

Every assertion here is scoped to a NAMED table, a NAMED settlement or a NAMED fixture rather than
to the document as a whole, per the testing protocol.

THE ROUND TRIP IS TESTED HERE AND NOT BY THE HARNESS
-----------------------------------------------------
`harness._check_roundtrip` reports SKIP for an adapter whose `from_cdm` returns non-JSON bytes and
says in as many words that "the adapter must ship its own round-trip test in tests/". This is it,
and it asserts BYTE EQUALITY on every fixture in the set.

THE THREE THINGS A GREEN HARNESS RUN CANNOT TELL YOU
-----------------------------------------------------
* **A fixture invariant under the harness clock exercises nothing.** `midnight_rollover_nearest` is
  built so the backward wrap happens under `times.FROZEN_NOW` itself; the forward wrap is asserted
  below against a clock this module injects.
* **A round trip proves self-consistency, never correctness.** This adapter has NO derive/invert
  pair with a shared model behind it at all — **not one scaled value in this category becomes a
  canonical numeric field** — so every conversion is a one-way view sitting beside its own raw
  octet. That absence is asserted rather than assumed.
* **The roster sweep is a manual protocol act.** Not this module's job.

WHAT THIS MODULE IS FOR THAT THE CAT034 ONE WAS NOT
----------------------------------------------------
The second object. This is the first adapter here that emits TWO Entities from one record, and the
two ways of getting it wrong are both plausible: folding the service into the station's attributes
(which makes two services of one station read as one object changing its mind) and keying the
service on its four-bit SID alone (which merges two stations' services). Both are asserted against.
"""
import datetime as dt
import json
import pathlib
import re
import types

import pytest

import synapse_cdm
from synapse_cdm import ids, times
from synapse_cdm.adapters import cat023_codec as codec
from synapse_cdm.adapters.asterix_cat023 import (
    ALWAYS_MANDATORY, CATEGORY, COUNTER_GENERIC_BAND, COUNTER_TYPE_TEXT, ENCODERS, FRN_BY_ITEM,
    REPORT_TYPE_TEXT, SERVICE_REPORT_TYPES, SERVICE_STATUS_SEVERITY, SERVICE_STATUS_TEXT,
    SERVICE_SYSTEM, SERVICE_TYPE_TEXT, STATION_SYSTEM, TABLE_2, TABLE_2_ITEMS, TIME_ITEM, UAP,
    AsterixCat023Adapter, Cat023ParseError, build_block, parse_block,
)
from synapse_cdm.enums import Affiliation, EntityType, EventType, Severity
from synapse_cdm.models import Entity, Event, Track, TrackSample

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
DOC = PACKAGE / "FORMAT_COVERAGE.md"
FIXTURES = PACKAGE / "fixtures" / "cat023"
REFUSALS = FIXTURES / "refusals"
GOLDEN = FIXTURES / "golden"

CLOCK = times.frozen_clock()


def adapter(**kwargs):
    return AsterixCat023Adapter(clock=CLOCK, **kwargs)


def blocks():
    return sorted(FIXTURES.glob("*.cat023"))


def block_of(name: str) -> bytes:
    return (FIXTURES / f"{name}.cat023").read_bytes()


def translate(name: str, **kwargs):
    return adapter(**kwargs).to_cdm(block_of(name))


def entities(name: str, **kwargs):
    return [o for o in translate(name, **kwargs) if isinstance(o, Entity)]


def events(name: str, **kwargs):
    return [o for o in translate(name, **kwargs) if isinstance(o, Event)]


def stations(name: str, **kwargs):
    return [e for e in entities(name, **kwargs)
            if e.attributes.get("object_is") == "the GROUND STATION"]


def services(name: str, **kwargs):
    return [e for e in entities(name, **kwargs)
            if str(e.attributes.get("object_is", "")).startswith("the SERVICE")]


def _section() -> str:
    text = DOC.read_text()
    start = text.index("## ASTERIX Category 023")
    nxt = text.find("\n## ", start + 10)
    return text[start:nxt if nxt != -1 else len(text)]


def _table(heading: str) -> list[str]:
    """The data rows under one heading. Scoped so an assertion cannot pass on another table's row."""
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

    See `tests/test_cdm_generator_loading.py`, which poisons a cache at every site that does this
    and requires the source to win.
    """
    path = FIXTURES / "spec" / "build_fixtures.py"
    module = types.ModuleType("cat023_build_fixtures")
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


# ============================================================== the codec, form by form

STATED_LSBS = [("tod", 1.0 / 128.0), ("gssp", 1.0), ("ssrp", 1.0), ("rp", 0.5),
               ("operational_range", 1.0)]


@pytest.mark.parametrize("form,stated", STATED_LSBS)
def test_every_lsb_is_the_documents_own(form, stated):
    assert codec.bounds(form)[2] == stated


def test_the_lsb_table_covers_every_form_the_codec_defines():
    assert {form for form, _ in STATED_LSBS} == set(codec.FORMS)


def test_nothing_in_this_category_is_signed():
    """Nine items, four scaled fields, and not one two's-complement value — the opposite of Part 9.

    Asserted because a reader arriving from `cat062_codec` will look for the signed handling, and
    its absence should be a finding rather than something they conclude from not finding it.
    """
    for form, (_bits, signed, *_rest) in codec.FORMS.items():
        assert not signed, f"{form} is signed; no §5.2 item in this category states a sign"
    source = (PACKAGE / "adapters" / "cat023_codec.py").read_text()
    assert "twos_from_raw" not in source and "twos_to_raw" not in source, (
        "the codec carries two's-complement helpers for a category with no signed field, which is "
        "arithmetic nothing calls"
    )


def test_the_three_reporting_periods_are_three_forms_and_not_one():
    """Two LSBs and two incompatible readings of zero. A shared form is wrong for one of the three."""
    assert codec.bounds("gssp") == codec.bounds("ssrp") == (1.0, 127.0, 1.0)
    assert codec.bounds("rp") == (0.0, 127.5, 0.5)
    assert codec.bounds("gssp")[0] != codec.bounds("rp")[0], (
        "GSSP's stated minimum is 1 and RP's zero is a named mode, so the two low bounds cannot "
        "be the same number"
    )
    # And the seven-bit fields reach exactly their stated maximum, which is why only the bottom
    # of the range is narrower than the field.
    assert codec.width("gssp") == (0.0, 127.0)


def test_a_gssp_of_zero_is_refused_and_the_message_says_the_item_excludes_it():
    with pytest.raises(codec.CodecError) as raised:
        codec.snap("gssp", 0.0)
    assert "the item's own range excludes" in str(raised.value)


def test_the_time_of_day_bound_is_the_width_and_the_day_bound_is_applied_one_level_up():
    assert codec.bounds("tod")[1] > codec.SECONDS_PER_DAY
    assert codec.snap("tod", 90000.0) == 90000.0


def test_the_codec_carries_no_coordinate_arithmetic_because_the_category_has_no_coordinate():
    source = (PACKAGE / "adapters" / "cat023_codec.py").read_text()
    code = "\n".join(l for l in source.splitlines() if not l.strip().startswith("#"))
    for marker in ("def vincenty", "FLATTENING", "SEMI_MAJOR", "math.cos", "math.sin", "atan2",
                   "degrees_to_metres"):
        assert marker not in code, (
            f"{marker!r} appears in a codec for a category with nine items and no coordinate"
        )


# ==================================================================== the FSPEC and UAP


def test_the_fspec_ceiling_matches_part_2bs_by_coincidence_and_the_uap_does_not():
    """THE TRAP THIS MODULE EXISTS FOR. Same octet count, different item at almost every position."""
    from synapse_cdm.adapters import cat034_codec
    assert codec.MAX_FSPEC_OCTETS == cat034_codec.MAX_FSPEC_OCTETS == 2
    assert codec.MAX_FRN == cat034_codec.MAX_FRN == 14
    from synapse_cdm.adapters.asterix_cat034 import FRN_BY_ITEM as CAT034_FRNS
    ours = {frn: item for item, frn in FRN_BY_ITEM.items()}
    theirs = {frn: item for item, frn in CAT034_FRNS.items()}
    # FRN 3 and FRN 4 are where the shared table would decode a three-octet time of day into a
    # one-octet service identification — and the record would still tile.
    assert ours[3] == "I023/015" and theirs[3] == "I034/030"
    assert ours[4] == "I023/070" and theirs[4] == "I034/020"
    def number(item):
        return item.split("/")[1] if "/" in item else item

    differing = [frn for frn in set(ours) & set(theirs)
                 if number(ours[frn]) != number(theirs[frn])]
    assert len(differing) >= 6, (
        f"only {len(differing)} FRNs carry different item numbers between the two parts, so the "
        "hazard this module's codec docstring describes has changed shape"
    )


def test_a_third_fspec_octet_is_refused_and_the_message_quotes_this_categorys_own_count():
    with pytest.raises(codec.CodecError) as raised:
        codec.read_fspec(bytes([0x01, 0x01, 0x00]), 0)
    message = str(raised.value)
    assert "14" in message and "FRN 15" in message
    assert "12 items" not in message, "the refusal quotes Part 2b's item count"


def test_the_three_spare_frns_are_refused_and_the_reason_records_that_there_is_no_note():
    assert codec.SPARE_FRNS == {10, 11, 12}
    assert "no note" in codec.SPARE_FRN_REASON
    with pytest.raises(codec.CodecError):
        codec.write_fspec([1, 2, 11])


def test_the_uap_order_is_table_3s_and_i023_200_sits_between_101_and_110():
    """A parser in item-number order reads the range octet as the first octet of Service Status."""
    assert FRN_BY_ITEM["I023/101"] < FRN_BY_ITEM["I023/200"] < FRN_BY_ITEM["I023/110"], (
        "I023/200 must sit between I023/101 and I023/110 on the wire — Edition 0.13's change "
        "record says 'Sequence of items in UAP updated' and this is what it moved"
    )
    order = [item for _frn, item, *_rest in UAP]
    assert order != sorted(order)


def test_all_nine_data_items_are_implemented_plus_re_and_sp():
    items = [item for _frn, item, *_rest in UAP]
    data_items = [i for i in items if i.startswith("I023/")]
    assert len(data_items) == 9 and set(data_items) == set(TABLE_2_ITEMS)
    assert set(items) - set(data_items) == {"RE", "SP"}


def test_every_item_layout_sums_to_the_standards_own_byte_counts():
    _build_fixtures_module().check_layouts()


def test_i023_101_is_the_only_two_octet_first_part_and_its_length_rule_is_its_own():
    """A rule copied from I023/100's would be off by one on every record."""
    module = _build_fixtures_module()
    one_octet = ENCODERS["I023/100"](module._station_status())
    two_octet = ENCODERS["I023/101"](module._configuration(rp_raw=0))
    assert len(one_octet) == 1 and len(two_octet) == 2
    assert len(ENCODERS["I023/101"](module._configuration(rp_raw=0, ssrp=1))) == 3


# ===================================================================== Table 2 itself


def test_table_2_is_transcribed_for_all_three_report_types_and_all_nine_items():
    assert set(TABLE_2) == {1, 2, 3}
    for report_type, column in TABLE_2.items():
        assert set(column) == set(TABLE_2_ITEMS), report_type
        assert set(column.values()) <= {"M", "O", "X"}


def test_the_three_report_types_are_mutually_exclusive_in_what_they_carry():
    """`I023/100`, `I023/101`+`I023/110` and `I023/120` are each M for exactly one type."""
    for item in ("I023/100", "I023/101", "I023/110", "I023/120"):
        mandatory = [t for t, column in TABLE_2.items() if column[item] == "M"]
        never = [t for t, column in TABLE_2.items() if column[item] == "X"]
        assert len(mandatory) == 1 and len(never) == 2, (
            f"{item} is M for {mandatory} and X for {never}; the mutual exclusion settlement 4 "
            "turns on requires exactly one of each"
        )
    assert TABLE_2[1]["I023/200"] == TABLE_2[2]["I023/200"] == "O", (
        "I023/200 is the only optional item in the category"
    )


def test_a_missing_mandatory_item_is_refused_and_the_message_names_the_report_type():
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm((REFUSALS / "missing_mandatory_for_type.cat023").read_bytes())
    message = str(raised.value)
    assert "002 (Service Status report)" in message and "I023/110" in message
    assert "See Table 2" in message, (
        "the refusal does not say that Table 2 IS the encoding rule, which is why a missing M is "
        "a record that cannot be read as what it claims to be"
    )


def test_a_missing_time_of_day_is_never_a_refusal_even_though_table_2_makes_it_mandatory():
    assert all(column[TIME_ITEM] == "M" for column in TABLE_2.values())
    station = stations("time_of_day_absent")[0]
    event = events("time_of_day_absent")[0]
    assert event.observed_at == times.FROZEN_NOW
    assert any("I023/070" in f for f in station.attributes["unavailable_fields"])
    assert "failure of all sources of time-stamping" in \
        event.payload["observed_at_basis"]["reason"]


def test_an_item_present_under_an_x_is_parked_and_named_rather_than_refused():
    station = stations("table_2_x_item_present")[0]
    disposition = station.attributes["table_2_disposition"]
    assert disposition["report_type"] == 1
    assert disposition["items_present_where_the_table_says_X"] == ["I023/110"]
    assert "conformance fault in the ENCODER" in disposition["basis"]


def test_every_record_carries_a_table_2_disposition_even_when_nothing_is_out_of_place():
    disposition = stations("ground_station_status_minimal")[0].attributes["table_2_disposition"]
    assert disposition["items_present_where_the_table_says_X"] == []


def test_an_undefined_report_type_is_translated_and_left_visible_to_a_severity_filter():
    station = stations("report_type_004")[0]
    event = events("report_type_004")[0]
    assert event.event_type is EventType.STATUS_CHANGE
    assert event.severity is Severity.ADVISORY
    assert station.attributes["unresolved_raw"]["I023/000 Report Type"]["raw"] == 4
    assert "reserved for common standard use" in \
        station.attributes["unresolved_raw"]["I023/000 Report Type"]["reason"]
    assert station.attributes["table_2_disposition"]["column"] is None


# ======================================================= settlement 2 — the second object


def test_a_service_report_produces_two_entities_and_the_event_names_both_station_first():
    objects = translate("service_status_report")
    assert len(stations("service_status_report")) == 1
    assert len(services("service_status_report")) == 1
    station, service = stations("service_status_report")[0], services("service_status_report")[0]
    event = events("service_status_report")[0]
    assert event.related_entities == [station.entity_id, service.entity_id], (
        "the event does not carry both ids with the station first, which is how the relationship "
        "is recorded WITHOUT joining anything"
    )
    assert station.entity_id != service.entity_id


def test_a_station_status_report_produces_one_entity_and_names_the_station_alone():
    assert len(services("ground_station_status_full")) == 0
    event = events("ground_station_status_full")[0]
    assert event.related_entities == [stations("ground_station_status_full")[0].entity_id]
    assert TABLE_2[1]["I023/015"] == "X", (
        "Table 2 no longer makes the service identification absent on a station status report, so "
        "this assertion is about the wrong thing"
    )


def test_the_services_identity_is_the_pair_and_never_the_sid_alone():
    """THE MUTATION THIS CATCHES: keying on the four-bit SID merges two stations' services."""
    service = services("service_status_report")[0]
    assert service.source_ids[0].system == SERVICE_SYSTEM == "ASTERIX_CNS_SERVICE"
    assert service.source_ids[0].external_id == "2929|3"
    assert service.entity_id == ids.derive(SERVICE_SYSTEM, "2929|3", kind="entity")
    assert service.entity_id != ids.derive(SERVICE_SYSTEM, "3", kind="entity"), (
        "the service is keyed on the SID alone, which §5.2.3's NOTE 1 forbids in substance: 'the "
        "service identification is allocated by the system', so four bits mean nothing across "
        "stations"
    )
    assert "NEVER THE SID ALONE" in service.attributes["service"]["identity_basis"]


def test_two_services_of_one_station_are_two_entities_and_are_not_merged():
    """Settlement 7's first refusal, made visible: three report types in one block, two SIDs."""
    objects = translate("all_three_service_types")
    station_ids = {e.entity_id for e in stations("all_three_service_types")}
    service_ids = {e.entity_id for e in services("all_three_service_types")}
    assert len(station_ids) == 1, (
        "three records for one station produced more than one station entity_id, so the SAC/SIC "
        "is not the identity basis"
    )
    assert len(service_ids) == 2, (
        f"{len(service_ids)} service entities from two different SIDs. Folding a service into the "
        "station's attributes would make these read as one object changing its mind"
    )
    assert len(stations("all_three_service_types")) == 3, (
        "one station Entity per record, not one per block — two records about one station are two "
        "statements at two instants and merging them is the accumulation settlement 7 refuses"
    )


def test_the_station_identity_is_the_same_derivation_cat034_uses():
    from synapse_cdm.adapters.asterix_cat034 import STATION_SYSTEM as CAT034_STATION
    assert STATION_SYSTEM == CAT034_STATION == "ASTERIX_SAC_SIC", (
        "one station seen through Part 16 and Part 2b would no longer be one entity"
    )
    station = stations("ground_station_status_minimal")[0]
    assert station.entity_id == ids.derive("ASTERIX_SAC_SIC", "2929", kind="entity")
    assert "§4.4.1" in station.attributes["identity_basis"], (
        "the identity basis does not cite the clause that supports it here and not in Part 2b"
    )


def test_the_service_entity_type_is_recorded_as_the_least_wrong_of_eight():
    service = services("service_status_report")[0]
    assert service.entity_type is EntityType.SENSOR
    assert "LEAST-WRONG OF EIGHT" in service.attributes["service"]["entity_type_basis"]


def test_the_cross_category_join_is_named_and_declined():
    service = services("service_status_report")[0]
    declined = service.attributes["service"]["cross_category_join_declined"]
    assert "I021/015" in declined and "TWO PAYLOADS" in declined


# ======================================================== what this category does not carry


def test_no_object_ever_carries_a_position_or_a_geometry_or_kinematics():
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Entity):
                assert obj.position is None, (
                    f"{path.name} produced a Position. Nine items and not one coordinate: "
                    "I023/200 is a radius with no centre"
                )
                assert obj.kinematics is None
            if isinstance(obj, Event):
                assert obj.geometry is None, f"{path.name} produced an Event.geometry"


def test_the_position_basis_says_why_and_names_the_cross_payload_refusal():
    basis = stations("ground_station_status_full")[0].attributes["position_basis"]
    assert "NINE ITEMS AND NOT ONE COORDINATE" in basis
    assert "cross-payload state" in basis and "cat034" in basis
    geometry = stations("ground_station_status_full")[0].attributes["geometry_basis"]
    assert "PERMANENTLY" in geometry and "no centre" in geometry


def test_the_operational_range_at_its_maximum_is_a_floor_and_still_no_geometry():
    station = stations("operational_range_at_maximum")[0]
    parked = station.attributes["operational_range"]
    assert parked["nautical_miles"] == 255.0
    assert "maximum value or above" in parked["at_or_above_maximum"]
    assert events("operational_range_at_maximum")[0].geometry is None


def test_valid_to_is_none_on_every_object_even_where_a_reporting_period_is_present():
    for name in ("ground_station_status_full", "service_status_report"):
        for entity in entities(name):
            assert entity.valid_to is None, (
                f"{name}: a reporting period became a staleness horizon, which is this adapter "
                "reasoning about reports it has not seen"
            )


# ================================================================= the clock and time


def test_the_adapter_never_reads_the_wall_clock():
    source = (PACKAGE / "adapters" / "asterix_cat023.py").read_text()
    assert "datetime.now" not in source and "utcnow" not in source


def test_the_midnight_wrap_happens_under_the_harnesss_own_frozen_clock():
    first, second = events("midnight_rollover_nearest")
    assert first.observed_at.date() == times.FROZEN_NOW.date() - dt.timedelta(days=1)
    assert second.observed_at.date() == times.FROZEN_NOW.date()
    assert "ROLLOVER" in first.payload["observed_at_basis"]["date_from"]


def test_the_forward_wrap_needs_a_clock_this_test_injects():
    late = times.frozen_clock(dt.datetime(2026, 4, 29, 23, 50, tzinfo=dt.timezone.utc))
    got = [o for o in AsterixCat023Adapter(clock=late).to_cdm(
        block_of("midnight_rollover_nearest")) if isinstance(o, Event)]
    assert got[1].observed_at.date() == dt.date(2026, 4, 30)


def test_a_time_of_day_past_a_day_is_refused_and_the_basis_names_the_cat048_difference():
    module = _build_fixtures_module()
    over = module.block(module.record(module._base(
        1, tod=codec.SECONDS_PER_DAY * 128, **{"I023/100": module._station_status()})))
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm(over)
    message = str(raised.value)
    assert "86400" in message and "modulo" in message
    assert "CAT048" in message and "three categories" in message, (
        "the refusal does not record that Part 4's printed inequality ACCEPTS 86400 s while this "
        "category's Definition and NOTE make it unreachable"
    )
    fine = module.block(module.record(module._base(
        1, tod=codec.SECONDS_PER_DAY * 128 - 1, **{"I023/100": module._station_status()})))
    assert adapter().to_cdm(fine)


# ======================================================= settlement 5 — the three FX bits


FX_REFUSALS = {
    "ground_station_status_second_extension": ("I023/100", "Second Extension"),
    "service_status_extension": ("I023/110", "any edition in hand"),
}


@pytest.mark.parametrize("name,expected", sorted(FX_REFUSALS.items()))
def test_an_fx_naming_an_undefined_extension_is_refused(name, expected):
    item, phrase = expected
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm((REFUSALS / f"{name}.cat023").read_bytes())
    message = str(raised.value)
    assert item in message and phrase in message


def test_the_i023_110_refusal_is_the_strongest_of_the_three_and_says_so():
    """Its FX names no extension at all, in any edition in hand — including 0.14."""
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm((REFUSALS / "service_status_extension.cat023").read_bytes())
    message = str(raised.value)
    assert "Edition 0.14" in message
    assert "Second Extension" not in message, (
        "I023/110's refusal quotes a phrase that belongs to the other two items, which are the "
        "cases where a later edition COULD define the continuation"
    )


def test_i023_101s_extension_fx_is_the_third_case_and_the_length_rule_covers_it():
    module = _build_fixtures_module()
    configuration = module._configuration(rp_raw=2, ssrp=30)
    configuration["extension"]["fx"] = 1
    payload = module.block(module.record(module._base(
        2, **{"I023/015": module._service(3, 2), "I023/101": configuration,
              "I023/110": module._status(4)})))
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm(payload)
    assert "I023/101" in str(raised.value) and "Second Extension" in str(raised.value)


def test_the_general_asterix_fx_semantics_are_not_what_is_being_refused():
    """CAT062's I062/510 IS an unbounded chain, and the difference decides this ruling."""
    from synapse_cdm.adapters.asterix_cat062 import _len_510
    octets = bytes([0x11, 0x00, 0x03, 0x22, 0x00, 0x02])
    assert _len_510(octets, 0) == 6, (
        "a sibling's genuinely repeating FX chain no longer accepts a second extent, so the "
        "contrast this settlement rests on has changed"
    )


# =============================================== settlement 6 — the three reporting periods


def test_the_report_period_zero_is_a_named_mode_and_never_a_number():
    """THE MUTATION THIS CATCHES: reaching a consumer as 0.0 s is the AIS sentinel defect."""
    station = stations("data_driven_report_period")[0]
    service = services("data_driven_report_period")[0]
    parked = service.attributes["service_configuration"]["report_period"]
    assert parked["raw"] == 0 and parked["data_driven_mode"] is True
    assert parked["seconds"] is None, (
        "a zero report period reached the object as a number of seconds"
    )
    dumped = json.dumps(service.model_dump(mode="json"))
    assert '"seconds": 0.0' not in dumped and '"seconds": 0' not in dumped


def test_the_report_period_is_about_another_categorys_feed_and_is_not_applied_here():
    parked = services("data_driven_report_period")[0].attributes[
        "service_configuration"]["report_period"]
    assert "Category 021" in parked["definition"]
    assert "NOT applied as a staleness horizon" in parked["basis"]


def test_a_reporting_period_of_zero_is_refused_where_the_item_states_a_minimum_of_one():
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm((REFUSALS / "reporting_period_zero.cat023").read_bytes())
    message = str(raised.value)
    assert "GSSP = 0" in message
    assert "obligation" in message.lower() and "4.5.1.1" in message, (
        "the refusal does not say why a zero cannot mean 'no periodic reporting'"
    )


def test_gssp_and_ssrp_are_parked_separately_even_though_they_are_identical_fields():
    station = stations("ground_station_status_full")[0]
    service = services("service_status_report")[0]
    assert station.attributes["ground_station_status"]["reporting_period"]["seconds"] == 60.0
    assert service.attributes["service_configuration"][
        "service_status_reporting_period"]["seconds"] == 30.0


# ================================================================== severity, bit by bit


def test_every_service_status_takes_the_severity_the_row_set_rules():
    assert SERVICE_STATUS_SEVERITY == {
        0: Severity.ADVISORY, 1: Severity.CRITICAL, 2: Severity.WARNING, 3: Severity.WARNING,
        4: Severity.INFO, 5: Severity.INFO,
    }
    degraded, failed = events("service_status_degraded")
    assert degraded.severity is Severity.WARNING and failed.severity is Severity.CRITICAL
    assert degraded.event_type is failed.event_type is EventType.STATUS_CHANGE, (
        "a service status produced an ALERT; no report type in this category does"
    )


def test_the_two_paths_to_advisory_are_distinguishable_in_the_object():
    """`0` is a value the document DEFINES as Unknown; `6` is one it does not define at all."""
    defined, undefined = events("service_status_unknown")
    assert defined.severity is undefined.severity is Severity.ADVISORY
    stations_ = stations("service_status_unknown")
    assert "I023/110 STAT" not in stations_[0].attributes["unresolved_raw"], (
        "STAT = 0 is 'Unknown', which the document defines — recording it as unresolved would "
        "make a stated unknown indistinguishable from an undefined value"
    )
    assert stations_[1].attributes["unresolved_raw"]["I023/110 STAT"]["raw"] == 6


def test_the_spoofing_bit_raises_warning_and_is_not_a_gnss_interference_event():
    event = events("ground_station_status_full")[0]
    assert event.severity is Severity.WARNING
    assert event.event_type is EventType.STATUS_CHANGE, (
        "SPO produced a GNSS_INTERFERENCE or an ALERT. That enum member is paired with "
        "GnssInterferencePayload, whose fields exist for the PNTMAP adapter"
    )
    raised = event.payload["severity_basis"]["raised_by"]
    spo = next(r for r in raised if r["item"] == "I023/100 SPO")
    assert "gap 29" in spo["reason"]


def test_the_nogo_bit_is_parked_rather_than_raised_and_says_why():
    station = stations("ground_station_status_full")[0]
    nogo = station.attributes["ground_station_status"]["nogo"]
    assert nogo["raw"] == 1
    assert "Data must not be used operationally" in nogo["text"]
    assert "judging data it has never been shown" in nogo["basis"]
    # And it is not among the things that raised severity.
    raised = {r["item"] for r in events("ground_station_status_full")[0].payload[
        "severity_basis"]["raised_by"]}
    assert "I023/100 NOGO" not in raised


def test_the_renumbering_bit_is_carried_and_cites_the_cat062_ruling_it_is_evidence_for():
    rn = stations("ground_station_status_full")[0].attributes["ground_station_status"]["rn"]
    assert rn["raw"] == 1
    assert "I021/161" in rn["definition"]
    assert "CAT062" in rn["basis"] and "settlement 3" in rn["basis"], (
        "the bit no longer records that it is cited as evidence in another row set, which is the "
        "only thing that makes a Part 16 status bit interesting to a Part 9 reader"
    )


def test_the_time_source_validity_bit_does_not_suppress_the_time_of_day():
    station = stations("time_of_day_absent")[0]
    assert station.attributes["ground_station_status"]["tsv"]["raw"] == 1
    assert "does NOT change how I023/070 is read" in \
        station.attributes["ground_station_status"]["tsv"]["basis"]


# ================================================================== the counters


def test_the_counters_are_an_ordered_list_with_duplicates_preserved():
    parked = events("service_statistics_report")[0].payload["service_statistics"]
    assert parked["rep"] == 4
    types = [c["type"] for c in parked["counters"]]
    assert types == [3, 21, 21, 4], (
        "the counters were reordered or de-duplicated; order is data and the document does not "
        "say the TYPE values are unique"
    )
    assert parked["counters"][0]["counter"] == 1_234_567
    assert parked["counters"][3]["counter"] == 4_294_967_295


def test_the_reference_bit_is_per_counter_and_not_once_for_the_item():
    counters = events("service_statistics_report")[0].payload["service_statistics"]["counters"]
    references = {c["reference"] for c in counters}
    assert len(references) == 2, (
        "one record's counters no longer carry two different references, so the per-counter "
        "reading is not being exercised"
    )


def test_the_definition_and_the_ref_bit_disagree_and_the_field_is_preferred():
    parked = events("service_statistics_report")[0].payload["service_statistics"]
    assert "THE FIELD IS PREFERRED over the Definition" in parked["reference_basis"]
    assert "ambiguity 7" in parked["reference_basis"]


def test_a_reserved_type_and_an_undefined_one_are_recorded_in_different_bands():
    station = stations("service_statistics_reserved_type")[0]
    unresolved = station.attributes["unresolved_raw"]
    assert unresolved["I023/120 TYPE in the reserved generic band"]["raw"] == [7]
    assert unresolved["I023/120 TYPE outside the table"]["raw"] == [40]
    assert 7 in COUNTER_GENERIC_BAND and 40 not in COUNTER_GENERIC_BAND
    assert "documented reservation" in \
        unresolved["I023/120 TYPE in the reserved generic band"]["reason"].lower()


def test_a_zero_repetition_statistics_item_is_refused_on_the_items_own_words():
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm((REFUSALS / "service_statistics_rep_zero.cat023").read_bytes())
    assert "AT LEAST ONE block of 6 octets" in str(raised.value)


def test_no_counter_becomes_a_detection_and_no_rate_is_computed():
    objects = translate("service_statistics_report")
    assert len([o for o in objects if isinstance(o, Event)]) == 1, (
        "a counter produced an Event, which would invent target reports this document does not "
        "carry"
    )
    parked = events("service_statistics_report")[0].payload["service_statistics"]
    assert "A COUNT IS NOT A DETECTION" in parked["basis"]
    assert "no rate is computed" in parked["basis"]


# ================================================================== the service type


def test_the_two_nibbles_are_parked_under_explicit_names_because_a_transposition_is_legal():
    payload = events("service_status_report")[0].payload["service"]
    assert payload["sid"] == 3 and payload["styp"] == 2
    assert payload["styp_text"] == SERVICE_TYPE_TEXT[2]
    assert "THE NAME IS IN THE OTHER ORDER FROM THE BITS" in payload["nibble_basis"]


def test_an_undefined_service_type_lands_in_unresolved_raw():
    module = _build_fixtures_module()
    payload = module.block(module.record(module._base(
        2, **{"I023/015": module._service(sid=1, styp=12),
              "I023/101": module._configuration(rp_raw=2),
              "I023/110": module._status(4)})))
    station = next(o for o in adapter().to_cdm(payload)
                   if isinstance(o, Entity)
                   and o.attributes.get("object_is") == "the GROUND STATION")
    assert station.attributes["unresolved_raw"]["I023/015 STYP"]["raw"] == 12
    assert "no 'unknown' or 'other' value" in station.attributes[
        "unresolved_raw"]["I023/015 STYP"]["reason"]


def test_the_scope_sentence_and_the_table_count_differently_and_the_object_says_so():
    payload = events("service_status_report")[0].payload["service"]
    assert "five" in payload["scope_note"].lower() and "nine" in payload["scope_note"].lower()
    assert len(SERVICE_TYPE_TEXT) == 9


# =========================================================================== egress


@pytest.mark.parametrize("path", blocks(), ids=lambda p: p.stem)
def test_every_fixture_round_trips_byte_for_byte(path):
    """THE ROUND TRIP THE HARNESS SKIPS, and it is byte equality rather than value presence."""
    raw = path.read_bytes()
    objects = adapter().to_cdm(raw)
    emitted = adapter().from_cdm(objects)
    assert emitted == raw, (
        f"{path.name} did not round-trip:\n  in : {raw.hex()}\n  out: {emitted.hex()}"
    )


def test_the_parsed_twin_and_the_octets_produce_identical_objects():
    for path in blocks():
        twin = json.loads((FIXTURES / f"{path.stem}.parsed.json").read_text())
        assert [o.model_dump(mode="json") for o in adapter().to_cdm(path.read_bytes())] == \
               [o.model_dump(mode="json") for o in adapter().to_cdm(twin)], path.name


def test_egress_reassembles_from_the_station_and_refuses_a_service_entity_alone():
    """The one rule the two-Entity shape needs, and the refusal names what is missing."""
    raw = block_of("service_status_report")
    service = services("service_status_report")[0]
    with pytest.raises(Cat023ParseError) as raised:
        adapter().from_cdm([service])
    message = str(raised.value)
    assert "no station Entity" in message and "contributes no octet of its own" in message
    assert "inventing an FSPEC" in message
    # And the station alone is sufficient.
    assert adapter().from_cdm([stations("service_status_report")[0]]) == raw


def test_a_non_minimal_fspec_is_re_emitted_as_parked_and_not_recomputed():
    raw = block_of("non_minimal_fspec")
    parsed = parse_block(raw)
    assert len(bytes.fromhex(parsed["records"][0]["fspec"])) == 2
    assert len(codec.write_fspec(sorted(FRN_BY_ITEM[i] for i in parsed["records"][0]["items"]))) == 1
    assert build_block(parsed["records"]) == raw


def test_egress_recomputes_len_and_never_copies_it():
    raw = block_of("ground_station_status_full")
    parsed = parse_block(raw)
    parsed["block"]["length"] = 9999
    assert build_block(parsed["records"]) == raw


def test_no_scaled_value_is_ever_the_source_of_an_emitted_octet():
    """The claim that makes this the easiest round trip in the family, asserted by editing.

    Every derived figure is a one-way view. Editing them all and re-emitting must change nothing.
    """
    raw = block_of("ground_station_status_full")
    station = stations("ground_station_status_full")[0]
    station.attributes["ground_station_status"]["reporting_period"]["seconds"] = 999.0
    station.attributes["operational_range"]["nautical_miles"] = 1.0
    assert adapter().from_cdm([station]) == raw


def test_egress_refuses_an_object_that_did_not_come_from_cat023_and_names_each_missing_input():
    stray = Entity(
        source=adapter().source_ref(), source_ids=[{"system": "X", "external_id": "1"}],
        entity_id=ids.derive("X", "1"), entity_type=EntityType.SENSOR,
        affiliation=Affiliation.UNKNOWN, valid_from=times.FROZEN_NOW,
        attributes={"object_is": "the GROUND STATION"})
    with pytest.raises(Cat023ParseError) as raised:
        adapter().from_cdm([stray])
    message = str(raised.value)
    assert "cat023_fspec" in message and "source_extras.items" in message
    assert "I023/010" in message and "I023/000" in message


def test_a_track_cannot_become_a_data_block_and_the_reason_is_stated():
    track = Track(source=adapter().source_ref(),
                  source_ids=[{"system": "X", "external_id": "1"}],
                  track_id=ids.derive("X", "1", kind="track"),
                  entity_id=ids.derive("X", "1"),
                  samples=[TrackSample(position={"lat": 0.0, "lon": 0.0,
                                                 "position_source": "MANUAL"},
                                       observed_at=times.FROZEN_NOW)])
    with pytest.raises(Cat023ParseError) as raised:
        adapter().from_cdm([track])
    assert "stationary ground station" in str(raised.value)


# ========================================================================= refusals

REFUSAL_REASONS = {
    "wrong_category": "CAT octet is 34",
    "length_disagrees_with_buffer": "LEN says",
    "missing_mandatory_report_type": "I023/000",
    "missing_mandatory_for_type": "Table 2 makes I023/110 mandatory",
    "fspec_names_a_spare_frn": "'- spare -'",
    "fspec_third_octet": "FRN 15",
    "ground_station_status_second_extension": "Second Extension",
    "service_status_extension": "defines NO extension",
    "service_statistics_rep_zero": "REP = 0",
    "reporting_period_zero": "GSSP = 0",
}


def test_the_refusal_directory_holds_exactly_the_ten_the_row_set_names():
    on_disk = {p.stem for p in REFUSALS.glob("*.cat023")}
    assert on_disk == set(REFUSAL_REASONS), (
        f"only on disk: {sorted(on_disk - set(REFUSAL_REASONS))}\n"
        f"only in this test: {sorted(set(REFUSAL_REASONS) - on_disk)}"
    )
    assert "ten refusals" in _flat(_section())


@pytest.mark.parametrize("name,expected", sorted(REFUSAL_REASONS.items()))
def test_each_refusal_names_what_was_wrong(name, expected):
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm((REFUSALS / f"{name}.cat023").read_bytes())
    assert expected in str(raised.value), (
        f"{name} was refused for a reason that does not mention {expected!r}:\n  {raised.value}"
    )


def test_nine_refuse_in_the_parser_and_one_refuses_in_translation():
    """A caller does not care which layer said no, and the test covers both through one door."""
    parse_level, translate_level = [], []
    for name in REFUSAL_REASONS:
        octets = (REFUSALS / f"{name}.cat023").read_bytes()
        try:
            parse_block(octets)
        except Cat023ParseError:
            parse_level.append(name)
            continue
        with pytest.raises(Cat023ParseError):
            adapter().to_cdm(octets)
        translate_level.append(name)
    assert translate_level == ["reporting_period_zero"], (
        f"the value-range refusals are {translate_level}; a range the ITEM states is checked where "
        "the reasoning that produces it can be written beside it, which is not the byte parser"
    )
    assert len(parse_level) == 9


def test_the_wrong_category_fixture_uses_part_2b_because_it_is_the_dangerous_sibling():
    octets = (REFUSALS / "wrong_category.cat023").read_bytes()
    assert octets[0] == 34, "the fixture no longer carries Part 2b's CAT octet"
    with pytest.raises(Cat023ParseError) as raised:
        adapter().to_cdm(octets)
    assert "Part 2b is the dangerous one" in str(raised.value)


# =============================================================== the row set itself

NAMED_TABLES = [
    "### Row set — the block and record envelope",
    "### Row set — the station, and the service that is a second object",
    "### Row set — report type",
    "### Row set — time",
    "### Row set — `I023/100` Ground Station Status",
    "### Row set — `I023/101` Service Configuration",
    "### Row set — `I023/110` Service Status",
    "### Row set — `I023/120` Service Statistics",
    "### Row set — `I023/200` Operational Range",
    "### Row set — RE and SP",
    "### Row set — egress, CDM back to a CAT023 data block",
]


@pytest.mark.parametrize("heading", NAMED_TABLES)
def test_every_row_of_every_named_table_claims_this_adapter(heading):
    rows = [r for r in _table(heading) if "| CDM field |" not in r and "| CAT023 |" not in r]
    assert rows, f"{heading} has no data rows"
    stale = [r for r in rows if "`not yet`" in r]
    assert not stale, (
        f"{len(stale)} row(s) under {heading!r} still say `not yet`:\n  "
        + "\n  ".join(r[:150] for r in stale)
    )
    unclaimed = [r for r in rows if "`cat023 1.0.0" not in r]
    assert not unclaimed, (
        f"{len(unclaimed)} row(s) under {heading!r} claim no adapter:\n  "
        + "\n  ".join(r[:150] for r in unclaimed)
    )


def test_the_egress_table_states_cdm_field_so_its_paths_are_actually_resolved():
    rows = _table("### Row set — egress, CDM back to a CAT023 data block")
    assert rows[0].startswith("| CDM field | CAT023 | Status | Notes |")


def test_the_table_2_transcription_in_the_row_set_matches_the_adapters():
    """Two statements of one matrix, each checkable against the other."""
    rows = _table("### Settlement 4 — Table 2, and the presence gate this category does have")
    body = [r for r in rows if r.startswith("| `I023/")]
    assert len(body) == 9, f"{len(body)} item rows in the row set's Table 2"
    for row in body:
        cells = [c.strip() for c in row.strip("|").split("|")]
        item = cells[0].split("`")[1]
        stated = cells[1:4]
        assert [TABLE_2[t][item] for t in (1, 2, 3)] == stated, (
            f"{item}: the row set says {stated} and the adapter says "
            f"{[TABLE_2[t][item] for t in (1, 2, 3)]}"
        )


def test_the_ambiguity_register_carries_ten_entries_and_agrees_with_the_pin():
    rows = _table("### Where the specification is ambiguous or contradicts itself")
    numbered = [r for r in rows if r.startswith("| ") and r.split("|")[1].strip().isdigit()]
    assert len(numbered) == 10
    pin = json.loads((FIXTURES / "spec" / "cat023_pin.json").read_text())
    assert set(pin["ambiguity_register"]["entries"]) == {str(i) for i in range(1, 11)}


def test_the_unfinished_back_cover_is_recorded_in_both_the_row_set_and_the_pin():
    """The strongest single argument in this repository for pinning a hash rather than an edition."""
    section = _flat(_section())
    for phrase in ("EUROCONTROL-SPEC-0149-8", "11 May 2020", "Roboto"):
        assert phrase in section, f"the row set no longer records {phrase!r}"
    pin = json.loads((FIXTURES / "spec" / "cat023_pin.json").read_text())
    node = pin["the_back_cover_is_an_UNFINISHED_TEMPLATE_and_this_is_the_strongest_finding_in_the_record"]
    assert len(node["three_separate_defects_on_one_page"]) == 3
    assert "not claimed" in " ".join(node).lower() or "what_is_NOT_claimed" in node


def test_the_adapter_declares_no_transforms_and_therefore_excuses_nothing():
    assert AsterixCat023Adapter.TRANSFORMS == {}


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
    assert {p.stem for p in REFUSALS.glob("*.cat023")} == set(refusals)
    for name, octets in refusals.items():
        assert (REFUSALS / f"{name}.cat023").read_bytes() == octets, name


def test_the_generator_cannot_write_a_type_002_record_without_its_mandatory_items():
    """What Phase 2 changed, and the generator is what caught it: `parse_block` runs per fixture."""
    module = _build_fixtures_module()
    with pytest.raises(Cat023ParseError):
        parse_block(module.block(module.record(module._base(
            2, **{"I023/015": module._service(3, 2), "I023/110": module._status(4)}))))
    assert "What Phase 2 changed" in _flat(_section()) or "refused them at BUILD time" in \
        _flat(_section()), "the row set no longer records the fixture correction"


def test_every_reachable_spare_bit_is_read_and_written_back_unchanged():
    """§4.3 is normative, and a set with all-zero spares tests nothing."""
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
    assert len(nonzero) == len(spares) >= 3, (
        f"only {len(nonzero)} of {len(spares)} spare fields are non-zero in the fixture that "
        f"exists to set them: {spares}"
    )
    assert build_block(parsed["records"]) == raw


def test_no_fixture_carries_a_uuid_because_the_wire_form_has_none():
    for path in blocks():
        twin = (FIXTURES / f"{path.stem}.parsed.json").read_text()
        found = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", twin)
        assert not found, f"{path.stem}.parsed.json carries a UUID ({found and found.group(0)})"


def test_every_fixture_is_synthetic_and_says_so_on_every_object():
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            assert obj.source.synthetic is True, path.name
            assert obj.source.adapter == "cat023" and obj.source.system == "ASTERIX_CAT023"


def test_this_category_has_no_simulation_flag_at_all_so_there_is_no_candidate_to_decline():
    source = (PACKAGE / "adapters" / "asterix_cat023.py").read_text()
    assert "SIM" not in source.replace("SIMULAT", "").replace("simulation", ""), (
        "a simulation flag appeared; Part 16 has none, which is why `synthetic` has no candidate "
        "here to decline"
    )
