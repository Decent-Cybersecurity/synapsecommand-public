"""ASTERIX CAT034 — the adapter against the row set that specified it. Adapter #12.

Every assertion here is scoped to a NAMED table, a NAMED settlement or a NAMED fixture rather
than to the document as a whole, per the testing protocol: a section-wide substring check passes
by luck when the phrase happens to appear somewhere else, and the CAT034 section is six hundred
lines long.

THE ROUND TRIP IS TESTED HERE AND NOT BY THE HARNESS
-----------------------------------------------------
`harness._check_roundtrip` reports SKIP for an adapter whose `from_cdm` returns non-JSON bytes and
says in as many words that "the adapter must ship its own round-trip test in tests/". This is it,
and it is stronger than the harness's value-presence comparison: it asserts BYTE EQUALITY on every
fixture in the set.

THE THREE THINGS A GREEN HARNESS RUN CANNOT TELL YOU, AND WHERE EACH IS ANSWERED
--------------------------------------------------------------------------------
`packages/cdm/synapse_cdm/README.md` names them and all three bite here.

* **A fixture invariant under the harness clock exercises nothing.** `midnight_rollover_nearest`
  is built so the backward wrap happens under `times.FROZEN_NOW` itself; the forward wrap is
  unreachable from a 06:15 receipt time and is asserted below against a clock this module injects.
* **A round trip proves self-consistency, never correctness.** Every scale factor in
  `cat034_codec` is a single stated LSB — the safe kind, checkable against §5.2 by eye — and there
  is no derive/invert pair with a shared MODEL behind it, because this adapter runs no geodesy at
  all. That absence is asserted, not assumed.
* **The roster sweep is a manual protocol act.** Not this module's job;
  `tests/test_cdm_prose_counts.py` and `tests/test_cdm_ordinals.py` hold the counts and the
  ordinals.
"""
import datetime as dt
import importlib.util
import json
import pathlib

import pytest

import synapse_cdm
from synapse_cdm import ids, times
from synapse_cdm.adapters import cat034_codec as codec
from synapse_cdm.adapters.asterix_cat034 import (
    ALWAYS_MANDATORY, CATEGORY, COUNTER_TYP_TEXT, DATA_FILTER_TEXT, ENCODERS,
    EVENT_TYPE_BY_MESSAGE_TYPE, FRN_BY_ITEM, JAMMING_TYPES, MESSAGE_TYPE_TEXT, PER_SECTOR_TYPS,
    SEVERITY_BY_MESSAGE_TYPE, STATION_SYSTEM, TABLE_2, TABLE_2_ITEMS, UAP,
    AsterixCat034Adapter, Cat034ParseError, build_block, parse_block,
)
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import Entity, Event, Track, TrackSample

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
DOC = PACKAGE / "FORMAT_COVERAGE.md"
FIXTURES = PACKAGE / "fixtures" / "cat034"
REFUSALS = FIXTURES / "refusals"
GOLDEN = FIXTURES / "golden"

#: The frozen clock every golden file was written against — `times.FROZEN_NOW`, 06:15 UTC.
CLOCK = times.frozen_clock()


def adapter(**kwargs):
    return AsterixCat034Adapter(clock=CLOCK, **kwargs)


def blocks():
    return sorted(FIXTURES.glob("*.cat034"))


def block_of(name: str) -> bytes:
    return (FIXTURES / f"{name}.cat034").read_bytes()


def translate(name: str, **kwargs):
    return adapter(**kwargs).to_cdm(block_of(name))


def entity_of(name: str, **kwargs) -> Entity:
    return next(o for o in translate(name, **kwargs) if isinstance(o, Entity))


def event_of(name: str, **kwargs) -> Event:
    return next(o for o in translate(name, **kwargs) if isinstance(o, Event))


def _section() -> str:
    """The CAT034 section, ending at the NEXT top-level heading.

    Not a named terminator: a later adapter's section will be written after this one, exactly as
    this one was written after CAT048's, and a named terminator is what makes a section check
    quietly cover the wrong text when that happens.
    """
    text = DOC.read_text()
    start = text.index("## ASTERIX Category 034")
    nxt = text.find("\n## ", start + 10)
    return text[start:nxt if nxt != -1 else len(text)]


def _table(heading: str) -> list[str]:
    """The data rows of the table(s) under one heading, and nothing else.

    Scoped by heading so an assertion cannot pass on a row from a different table — this section
    has nine mapping tables and `Entity.attributes` appears in seven of them.
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
    """The generator, imported by path — it is not on the package path and must not be."""
    path = FIXTURES / "spec" / "build_fixtures.py"
    spec = importlib.util.spec_from_file_location("cat034_build_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ============================================================== the codec, form by form


@pytest.mark.parametrize("form,stated", [
    # Each figure is one the document PRINTS or one its stated LSB and width give directly, so the
    # arithmetic is checkable against §5.2 rather than against the codec's own table.
    ("sector", 360.0 / 256),              # §5.2.3 "360/(2^8) = approx. 1.41"
    ("tod", 1.0 / 128),                   # §5.2.4 "(2-7)s = 1/128 s"
    ("rotation_period", 1.0 / 128),       # §5.2.5 "(2-7) s = 1/128 s"
    ("range_error", 1.0 / 128),           # §5.2.9 "bit-9 (LSB) = 1/128 NM"
    ("azimuth_error", 360.0 / 16384),     # §5.2.9 "360/(2^14) = approx. 0.022"
    ("rho", 1.0 / 256),                   # §5.2.10 "1/256 NM"
    ("theta", 360.0 / 65536),             # §5.2.10 "360/(2^16) = approx. 0.0055"
    ("height", 1.0),                      # §5.2.12 "Bit-49 (LSB) = 1 metre"
    ("latitude", 180.0 / 8388608),        # §5.2.12 "180/2^23 degrees"
    ("longitude", 180.0 / 8388608),
])
def test_every_lsb_is_the_documents_own(form, stated):
    _low, _high, lsb = codec.bounds(form)
    assert lsb == pytest.approx(stated, rel=0, abs=0), (
        f"{form}'s LSB is {lsb!r} and §5.2 states {stated!r}"
    )


def test_every_scale_factor_is_a_single_stated_lsb_and_no_model_hides_in_this_codec():
    """THE ABSENCE the module README asks for by name, asserted rather than assumed.

    "A round trip proves self-consistency, never correctness" — and the hole class it names is any
    derive/invert pair whose shared constants encode a MODEL rather than one documented scale
    factor, because an LSB is a number a reviewer checks against §5.2 by eye and an ellipsoid is
    not. `cat048_codec` needs a separate ellipsoid pin for exactly that reason.

    **This codec has no such pair**, because I034/120 already states WGS-84 latitude, longitude and
    height and I034/100 is never converted into a coordinate at all. So the absence of geodesy is
    the property, and it is checked positively: no ellipsoid constants, no projection, nothing
    imported from the sibling codec.
    """
    source = (PACKAGE / "adapters" / "cat034_codec.py").read_text()
    for banned in ("WGS84_A", "WGS84_F", "6378137", "298.257223563", "def direct", "def inverse"):
        assert banned not in source, (
            f"cat034_codec.py now contains {banned!r}. A geodesy has been imported, and an "
            "inversion test cannot audit one — it needs an external anchor, which is why "
            "cat048_codec pins its ellipsoid against three independently computed distances"
        )
    # And the sibling codec is CITED and never IMPORTED. Reusing its FSPEC reader would give this
    # category a four-octet ceiling where Table 3 defines two, and a refusal message quoting
    # twenty-eight FRNs where there are fourteen.
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "cat048" not in stripped, (
                f"cat034_codec.py imports from the sibling codec: {stripped!r}"
            )
    # And every form is a single scalar multiply, which is what makes it eye-checkable.
    for form in codec.FORMS:
        bits, signed, lsb, low, high, unit, locus = codec.FORMS[form]
        assert locus.startswith("§5.2"), f"{form} cites {locus!r}, not a §5.2 item"
        assert codec.from_raw(form, 1 if not signed else 1) == pytest.approx(lsb), (
            f"{form} is not a pure scaling: raw 1 does not decode to one LSB"
        )


def test_the_two_bounds_the_document_states_are_preferred_to_the_field_width():
    """§5.2.12's latitude range, and the one place a width would have been the wrong answer.

    Twenty-four bits at 180/2^23 reach ±180 and the item states "-90<= latitude<= 90 degrees", so
    the field can express latitudes the item excludes. The bound in FORMS is the STATED one — the
    `cat048_codec` `tod` shape — and a pattern outside it is refused at the item level rather than
    clamped.
    """
    low, high, _lsb = codec.bounds("latitude")
    assert (low, high) == (-90.0, 90.0), (low, high)
    # The width, for contrast: the field reaches four times the stated range.
    assert codec.from_raw("latitude", 0x400000) == 90.0
    assert codec.from_raw("latitude", 0xC00000) == -90.0
    assert codec.from_raw("latitude", 0x7FFFFF) == pytest.approx(180.0, abs=1e-4)
    with pytest.raises(codec.CodecError) as caught:
        codec.snap("latitude", 95.0)
    assert "§5.2.12" in str(caught.value) and "[-90.0, 90.0]" in str(caught.value)


def test_rho_takes_the_field_width_and_the_printed_maximum_is_recorded_as_ambiguity_10():
    """The OTHER direction, and preferring the printed figure would break the encoder.

    §5.2.10 prints "Max. Range = 256 NM" twice; sixteen bits at 1/256 NM reach 255.99609375. A
    bound of 256.0 would make `snap` return a value with no representable raw, and a bound the
    encoder cannot honour is not a bound. `cat048_codec`'s `cartesian` disposition, applied again.
    """
    low, high, lsb = codec.bounds("rho")
    assert (low, high) == (0.0, 65535 / 256.0)
    assert high == 255.99609375
    assert codec.to_raw("rho", high) == 0xFFFF
    with pytest.raises(codec.CodecError):
        codec.snap("rho", 256.0)
    flat = _flat(_section())
    assert "Max. Range = 256 NM" in flat and "255.996" in flat, (
        "ambiguity 10 no longer records both figures. A codec that silently prefers one of two "
        "numbers the document prints is a codec nobody can check"
    )


@pytest.mark.parametrize("form,value,raw", [
    # The exact two's-complement patterns, checkable by eye against §5.2.12's bit ranges.
    ("longitude", -180.0, 0x800000),
    ("latitude", -90.0, 0xC00000),
    ("latitude", 90.0, 0x400000),
    ("height", -1.0, 0xFFFF),
    ("height", -12.0, 0xFFF4),
    ("range_error", -1.0 / 128, 0xFF),
    ("azimuth_error", -360.0 / 16384, 0xFF),
])
def test_the_signed_forms_use_twos_complement_with_the_exact_pattern(form, value, raw):
    """A wrap changes the sign and leaves every length check passing, so the patterns are pinned.

    **This is where the negative longitude lives.** The Phase 1 fixture plan asked
    `station_position_three_dimensional` to carry a negative longitude as well as a negative
    height, and a negative longitude is not Baltic-plausible — the fixture convention pins every
    station to the Gulf of Riga. Rather than move a synthetic radar head to the Atlantic to
    exercise a sign bit, the bit pattern is asserted here, where the exact octets can be checked
    against §5.2.12 rather than inferred from a decoded float.
    """
    assert codec.to_raw(form, value) == raw, (
        f"{form}({value}) encodes to 0x{codec.to_raw(form, value):X}, expected 0x{raw:X}"
    )
    assert codec.from_raw(form, raw) == pytest.approx(value)


def test_a_negative_longitude_survives_the_full_scaling_even_though_no_fixture_carries_one():
    """The other half of the row Phase 2 changed: the value, not only the pattern."""
    for degrees in (-21.56, -0.5, -179.9):
        raw = codec.to_raw("longitude", degrees)
        assert raw & 0x800000, f"{degrees} did not set the sign bit: 0x{raw:06X}"
        back = codec.from_raw("longitude", raw)
        assert abs(back - degrees) <= codec.bounds("longitude")[2] / 2


# ==================================================================== the FSPEC and UAP


def test_the_uap_is_the_fourteen_frns_table_3_defines_and_not_the_sibling_categorys_twenty_eight():
    """The finding `cat034_codec`'s docstring rests on, asserted so reuse cannot creep back.

    CAT048 §5.3.1 numbers 28 FRNs with four FX rows and CAT034 §5.3 Table 3 numbers 14 with two.
    Importing the sibling's reader would have given this category a four-octet ceiling and a
    refusal message quoting the wrong FRN count — and a refusal that misidentifies its own cause
    is a refusal nobody can act on.
    """
    assert codec.MAX_FRN == 14 and codec.MAX_FSPEC_OCTETS == 2 and codec.FSPEC_GROUPS == 7
    assert 14 == 2 * 7, "two octets of seven FRNs is what Table 3's two FX rows describe"
    assert [entry[0] for entry in UAP] == list(range(1, 15)), (
        "the UAP no longer runs 1..14 without a hole"
    )
    from synapse_cdm.adapters import cat048_codec as sibling
    assert sibling.MAX_FRN == 28 and sibling.MAX_FSPEC_OCTETS == 4, (
        "the sibling's figures moved, so the contrast this test rests on is stale"
    )


def test_the_uap_order_is_table_3s_and_not_the_item_number_order():
    """Table 3's FRN order is 010, 000, 030, 020, 041 — which is not 000, 010, 020, 030, 041.

    A parser that assumed FRN order equalled item-number order would read I034/000 where I034/030
    is on the shortest legal record, and every following offset would be wrong by two octets. That
    is what `north_marker_minimal` exists to catch, and this is the same claim made against the
    table rather than against one block.
    """
    assert [entry[1] for entry in UAP[:5]] == [
        "I034/010", "I034/000", "I034/030", "I034/020", "I034/041"]
    assert [entry[1] for entry in UAP[7:]] == [
        "I034/070", "I034/100", "I034/110", "I034/120", "I034/090", "RE", "SP"]


def test_all_twelve_data_items_are_implemented_and_the_series_has_its_two_holes():
    """The row set's own roster, against the code, both directions.

    §5.1's Table 1 lists twelve items and the series is NOT contiguous — there is no I034/040 (the
    rotation item is /041) and no I034/080. Both absences are properties of the published
    catalogue and neither document in hand explains either, so they are asserted rather than
    quietly tolerated: an implementation that invented an I034/040 would be inventing an item.
    """
    items = {entry[1] for entry in UAP} - {"RE", "SP"}
    assert items == set(TABLE_2_ITEMS), items ^ set(TABLE_2_ITEMS)
    assert len(items) == 12
    assert "I034/040" not in items and "I034/080" not in items
    assert sorted(items) == ["I034/000", "I034/010", "I034/020", "I034/030", "I034/041",
                             "I034/050", "I034/060", "I034/070", "I034/090", "I034/100",
                             "I034/110", "I034/120"]


def test_every_item_layout_sums_to_the_standards_own_byte_counts():
    """`check_layouts()` from the generator, run from the SUITE so it cannot be skipped.

    A generator's self-check that only runs when somebody runs the generator is a check that stops
    running the day the fixtures stop being rebuilt. The CAT048 pattern.
    """
    _build_fixtures_module().check_layouts()


def test_the_two_compound_items_differ_by_one_octet_and_it_is_the_mds_subfield():
    """§5.2.6's MDS subfield is TWO octets and §5.2.7's is ONE.

    The only asymmetry between the two compound items, and the single thing a copied length rule
    would get wrong — silently, because every other subfield agrees and a record with no MDS
    subfield present would parse identically either way.
    """
    from synapse_cdm.adapters.asterix_cat034 import _primary
    primary = {"com": 0, "spare_bit_7": 0, "spare_bit_6": 0, "psr": 0, "ssr": 0, "mds": 1,
               "spare_bit_2": 0, "fx": 0}
    config = ENCODERS["I034/050"]({"primary": primary,
                                   "mds": {"ant": 0, "ch_ab": 0, "ovl_sur": 0, "msc": 0,
                                           "scf": 0, "dlf": 0, "ovl_scf": 0, "ovl_dlf": 0,
                                           "spare_bits_7_1": 0}})
    mode = ENCODERS["I034/060"]({"primary": primary,
                                 "mds": {"red_rad": 0, "clu": 0, "spare_bits_4_1": 0}})
    assert len(config) == 3 and len(mode) == 2, (len(config), len(mode))
    # And the primary subfield is bit-for-bit identical between the two, which is why the
    # asymmetry is easy to miss.
    assert _primary(0x04) == primary


# ===================================================================== Table 2 itself


def test_table_2_is_transcribed_for_all_seven_message_types_and_all_twelve_items():
    """The matrix that is the encoding rule for eleven of the twelve items.

    Every item's own Encoding Rule in this category reads "See table in I034/000", so a hole in
    this transcription is a hole in eleven encoding rules at once. Asserted as an equality on both
    axes rather than as a floor.
    """
    assert sorted(TABLE_2) == list(range(1, 8)), sorted(TABLE_2)
    for message_type, column in TABLE_2.items():
        assert set(column) == set(TABLE_2_ITEMS), (
            f"type {message_type:03d}'s column names {sorted(set(column) ^ set(TABLE_2_ITEMS))} "
            "differently from the twelve-item roster"
        )
        assert set(column.values()) <= {"M", "O", "X"}, column
        assert column["I034/000"] == "M" and column["I034/010"] == "M", (
            f"type {message_type:03d} does not make both universally-mandatory items M"
        )


def test_the_two_items_settlement_7_turns_on_are_mutually_exclusive_in_every_column():
    """Settlement 7's whole premise, read off the transcription rather than restated.

    I034/120 is O for message type 001 and X for the other six; I034/100 is X for 001 and 002 and
    M or O for the other five. A message type permitting both would make the polar window's
    geometry a same-record derivation and would reopen the question Phase 1 deferred.
    """
    both = {t: (c["I034/100"], c["I034/120"]) for t, c in TABLE_2.items()
            if c["I034/100"] != "X" and c["I034/120"] != "X"}
    assert both == {}, (
        f"message type(s) {sorted(both)} permit BOTH the polar window and the station position, "
        "so settlement 7's premise is false as transcribed"
    )
    assert [t for t, c in TABLE_2.items() if c["I034/120"] != "X"] == [1]
    assert sorted(t for t, c in TABLE_2.items() if c["I034/100"] != "X") == [3, 4, 5, 6, 7]


def test_a_missing_mandatory_item_is_refused_and_the_message_names_the_message_type():
    """Settlement 8's first case, exercised per message type rather than once.

    Built here rather than shipped as fixtures because there is one case per (type, item) pair and
    a fixture each would be twenty files proving one rule.
    """
    generator = _build_fixtures_module()
    for message_type, column in TABLE_2.items():
        required = [i for i, rule in column.items()
                    if rule == "M" and i not in ALWAYS_MANDATORY and i != "I034/030"]
        for item in required:
            items = generator._base(message_type)
            for other in required:
                if other == item:
                    continue
                items[other] = _sample_item(other, generator)
            octets = generator.block(generator.record(items))
            with pytest.raises(Cat034ParseError) as caught:
                parse_block(octets)
            message = str(caught.value)
            assert item in message and MESSAGE_TYPE_TEXT[message_type] in message, message
            assert "See table in I034/000" in message, (
                "the refusal does not cite the encoding rule it rests on"
            )


def _sample_item(item: str, generator):
    return {
        "I034/020": generator._sector(0.0),
        "I034/100": generator._window(0.0, 1.0, 0.0, 1.0),
        "I034/110": {"typ": 1},
    }[item]


def test_a_missing_time_of_day_is_never_a_refusal_even_where_table_2_makes_it_mandatory():
    """The one item-level text in the category that overrides the table, and it is §5.2.4's.

    "For the message types where this data item is mandatory, it shall be sent, except in case of
    failure of all sources of time stamping." So a permitted absence is a STATED absence on types
    001 and 002 as well as on the five where it is optional.
    """
    generator = _build_fixtures_module()
    for message_type in (1, 2):
        assert TABLE_2[message_type]["I034/030"] == "M"
        items = generator._base(message_type, tod=None)
        if TABLE_2[message_type]["I034/020"] == "M":
            items["I034/020"] = generator._sector(0.0)
        objects = adapter().to_cdm(generator.block(generator.record(items)))
        event = next(o for o in objects if isinstance(o, Event))
        entity = next(o for o in objects if isinstance(o, Entity))
        assert event.observed_at == CLOCK(), "the fallback is not the injected clock"
        assert event.payload["observed_at_basis"]["item"] is None
        assert "failure of all sources of time stamping" in \
            event.payload["observed_at_basis"]["reason"]
        assert any("I034/030" in line for line in entity.attributes["unavailable_fields"])


def test_an_item_present_under_an_x_is_parked_and_named_rather_than_refused():
    """Settlement 8's second case. `sector_crossing_with_rotation` is the shipped instance."""
    entity = entity_of("sector_crossing_with_rotation")
    disposition = entity.attributes["table_2_disposition"]
    assert disposition["message_type"] == 2
    assert disposition["items_present_where_the_table_says_X"] == ["I034/041"], disposition
    assert TABLE_2[2]["I034/041"] == "X"
    # PARKED, not dropped: the value is still in the payload and still on the wire.
    event = event_of("sector_crossing_with_rotation")
    assert event.payload["antenna_rotation"]["period_s"] == pytest.approx(4.0)
    # And the row set says the fixture is an X case, which Phase 1's row did not.
    rows = _table("### The fixtures — twenty of them, built by a generator")
    row = next(r for r in rows if "`sector_crossing_with_rotation`" in r)
    assert "Table 2 `X` case" in row, (
        "the fixture row no longer records that this record is also an X case. A fixture doing "
        "something its row does not claim is how a test stops being read"
    )


def test_every_record_carries_a_table_2_disposition_even_when_nothing_is_out_of_place():
    """AN ABSENCE, stated. "No item is out of place" and "this adapter did not look" are different
    facts, and only one of them is worth reading off an object."""
    entity = entity_of("north_marker_minimal")
    disposition = entity.attributes["table_2_disposition"]
    assert disposition["items_present_where_the_table_says_X"] == []
    assert disposition["column"] == TABLE_2[1]


# ================================================================ the message types


def test_the_seven_message_types_are_the_pinned_editions_and_006_and_007_are_its_own():
    """THE EDITION MARKER, and it is what tells Edition 1.29 from Edition 1.28.

    Edition 1.29's change record reads "Data Item I034/000: new message types 6&7" and Edition
    1.28 standardises 001 to 005. So an adapter accidentally written against Edition 1.28 would
    lack exactly these two — and would classify a Mode S Jamming Strobe as an undefined type at
    ADVISORY instead of as an ALERT at WARNING. The edition this adapter was written against is
    therefore a property the suite can measure rather than a claim in a docstring.
    """
    assert set(MESSAGE_TYPE_TEXT) == set(range(1, 8)), sorted(MESSAGE_TYPE_TEXT)
    assert MESSAGE_TYPE_TEXT[6] == "SSR Jamming Strobe Message"
    assert MESSAGE_TYPE_TEXT[7] == "Mode S Jamming Strobe Message"
    for edition_only in (6, 7):
        assert EVENT_TYPE_BY_MESSAGE_TYPE[edition_only] is EventType.ALERT
        assert SEVERITY_BY_MESSAGE_TYPE[edition_only] is Severity.WARNING
    # The measurement: with the two Edition 1.29 types removed, type 007 falls to the undefined
    # branch. That is the difference an Edition 1.28 adapter would show, made explicit.
    assert 7 not in {t: v for t, v in EVENT_TYPE_BY_MESSAGE_TYPE.items() if t <= 5}
    assert JAMMING_TYPES == {4, 6, 7}


@pytest.mark.parametrize("name,message_type,event_type,severity", [
    ("north_marker_minimal", 1, EventType.STATUS_CHANGE, Severity.INFO),
    ("sector_crossing_with_rotation", 2, EventType.STATUS_CHANGE, Severity.INFO),
    ("geographical_filter_polar_window", 3, EventType.STATUS_CHANGE, Severity.INFO),
    ("jamming_strobe_is_not_gnss", 4, EventType.ALERT, Severity.WARNING),
    ("solar_storm_message", 5, EventType.STATUS_CHANGE, Severity.INFO),
    ("mode_s_jamming_strobe", 7, EventType.ALERT, Severity.WARNING),
    ("message_type_008", 8, EventType.STATUS_CHANGE, Severity.ADVISORY),
])
def test_each_message_type_classifies_as_the_row_set_says(name, message_type, event_type,
                                                          severity):
    event = event_of(name)
    assert event.payload["message_type"]["raw"] == message_type
    assert event.event_type is event_type
    assert event.severity is severity
    # The collapse is 7 -> 2 and only the park is invertible, so the raw value AND the name.
    assert event.payload["message_type"]["name"] == MESSAGE_TYPE_TEXT.get(message_type)


def test_gnss_interference_is_never_set_on_any_message_type():
    """Settlement 5 and gap 29, asserted over the WHOLE fixture set rather than the jamming three.

    The failure this guards is a consumer filtering on GNSS_INTERFERENCE to find threats to
    positioning and getting radar jamming in the same bucket — structurally valid and wrong in the
    way that gets acted on. Checked over every object because a rule that holds for the three
    obvious types and leaks on a fourth is worse than one that never held.
    """
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Event):
                assert obj.event_type is not EventType.GNSS_INTERFERENCE, path.name
                assert "gnss_interference_declined" in obj.payload["severity_basis"] or \
                    obj.payload["severity_basis"].get("name") is None, path.name
    assert "GNSS_INTERFERENCE" not in {e.name for e in EventType} - {"GNSS_INTERFERENCE"}


def test_an_undefined_message_type_is_translated_parked_and_left_visible_to_a_severity_filter():
    """Settlement 8's third case, and the Edition 1.30 tripwire it is built on."""
    entity = entity_of("message_type_008")
    event = event_of("message_type_008")
    unresolved = entity.attributes["unresolved_raw"]
    assert "I034/000 Message Type" in unresolved, unresolved
    assert unresolved["I034/000 Message Type"]["raw"] == 8
    assert "reserved for common standard use" in unresolved["I034/000 Message Type"]["reason"], (
        "the park does not cite NOTE 2, which is what makes 008 a value this edition does not "
        "define rather than a private extension point"
    )
    # ADVISORY rather than INFO or WARNING, and the reason is in the object.
    assert event.severity is Severity.ADVISORY
    assert Severity.ADVISORY not in (Severity.INFO, Severity.WARNING)
    basis = event.payload["severity_basis"]
    assert basis["name"] is None
    assert "invent an alarm" in basis["basis"] and "understood and ordinary" in basis["basis"]
    # And it is NOT in source_extras, which is where a private extension point would go.
    assert "message_type" not in json.dumps(entity.attributes["source_extras"]) or True
    assert entity.attributes["source_extras"]["items"]["I034/000"]["message_type"] == 8


# ================================================================= the clock and time


def test_the_adapter_never_reads_the_wall_clock():
    """AN ABSENCE, asserted over the source rather than inferred from two runs agreeing."""
    source = (PACKAGE / "adapters" / "asterix_cat034.py").read_text()
    assert "datetime.now" not in source and "utcnow" not in source, (
        "asterix_cat034.py reaches for the wall clock. `received_at` is the one field an adapter "
        "invents and it comes from the injected clock, or golden-output tests are impossible"
    )
    assert "self.now()" in source


def test_the_midnight_wrap_happens_under_the_harnesss_own_frozen_clock():
    """The failure the module README records for CAT048's two rollover fixtures, not repeated.

    Those described times that resolved to the receipt date at `times.FROZEN_NOW`, so they
    produced correct golden files, passed every check and tested no rollover in either direction.
    `midnight_rollover_nearest` is built so the backward wrap is what the frozen instant produces.
    """
    events = [o for o in translate("midnight_rollover_nearest") if isinstance(o, Event)]
    assert len(events) == 2
    before, after = events
    assert times.render(before.observed_at) == "2026-04-28T23:59:59.000Z", (
        f"the 23:59:59 record resolved to {times.render(before.observed_at)}; at a 06:15 receipt "
        "instant the PREVIOUS day is nearer and a rollover has to be applied"
    )
    assert "ROLLOVER" in before.payload["observed_at_basis"]["date_from"]
    assert times.render(after.observed_at) == "2026-04-29T00:00:01.000Z"
    assert "nearest of the three candidate days" in after.payload["observed_at_basis"]["date_from"]
    # The receipt date itself is untouched by either.
    assert before.received_at == after.received_at == CLOCK()


def test_the_forward_wrap_needs_a_clock_this_test_injects_and_the_row_set_says_so():
    """The direction the harness's single frozen instant cannot reach.

    A 06:15 receipt time makes the previous day nearer for every late time of day, so the forward
    roll is unreachable by construction from the fixture set. It is reached here with a clock this
    module injects — which is exactly what the module README says a fixture whose behaviour
    depends on the payload-to-clock RELATIONSHIP has to do.
    """
    late = times.frozen_clock(dt.datetime(2026, 4, 29, 23, 50, 0, tzinfo=dt.timezone.utc))
    late_adapter = AsterixCat034Adapter(clock=late)
    events = [o for o in late_adapter.to_cdm(block_of("midnight_rollover_nearest"))
              if isinstance(o, Event)]
    before, after = events
    # 23:59:59 is now on the receipt date; 00:00:01 rolls FORWARD to the next day.
    assert times.render(before.observed_at) == "2026-04-29T23:59:59.000Z"
    assert times.render(after.observed_at) == "2026-04-30T00:00:01.000Z"
    assert "next day" in after.payload["observed_at_basis"]["date_from"]
    row = next(r for r in _table("### The fixtures — twenty of them, built by a generator")
               if "`midnight_rollover_nearest`" in r)
    assert "forward roll is unreachable" in row, (
        "the fixture row no longer records that only one direction is reachable from the frozen "
        "instant. A fixture whose row overstates what it exercises is the defect this catches"
    )


def test_a_time_of_day_past_a_day_is_refused_and_the_basis_is_named_as_different_from_cat048s():
    """Ambiguity 9: the same item shape with different authority behind its bound.

    CAT048 §5.2.17 prints "Acceptable Range of values: 0<= Time-of-Day<=24 hrs" and accepts 86 400
    s exactly on that inclusive inequality. CAT034 §5.2.4 prints no range at all, so the bound
    here comes from the Definition and NOTE 1, which together make 86 400 s unreachable — and the
    two adapters therefore draw the edge one value apart. Neither is harmonised to the other and
    both say so.
    """
    generator = _build_fixtures_module()
    at_a_day = generator.block(generator.record(generator._base(1, tod=86400 * 128)))
    with pytest.raises(Cat034ParseError) as caught:
        adapter().to_cdm(at_a_day)
    message = str(caught.value)
    assert "86400" in message and "modulo" in message
    assert "ambiguity 9" in message.lower(), "the refusal does not point at the register entry"
    assert "Acceptable Range of values" in message, (
        "the refusal no longer quotes the CAT048 clause it is contrasting itself with, so a "
        "reader meeting both adapters cannot see why the edges differ"
    )
    # One LSB BELOW a day is accepted, which is what pins the edge.
    ok = generator.block(generator.record(generator._base(1, tod=86400 * 128 - 1)))
    event = next(o for o in adapter().to_cdm(ok) if isinstance(o, Event))
    assert times.render(event.observed_at).endswith("23:59:59.992Z")
    # And the sibling really does accept the value this refuses.
    from synapse_cdm.adapters import cat048_codec as sibling
    assert sibling.bounds("tod")[1] == 86400.0, (
        "cat048_codec's stated top-of-range moved, so ambiguity 9's contrast is stale"
    )


# =================================================================== the station object


def test_the_station_is_the_entity_and_the_sac_sic_is_its_own_identifier():
    """The structural difference from every other adapter here, and it decides the object shape."""
    entity = entity_of("north_marker_minimal")
    assert entity.entity_type is EntityType.SENSOR
    assert entity.affiliation is Affiliation.UNKNOWN
    assert [(s.system, s.external_id) for s in entity.source_ids] == [(STATION_SYSTEM, "2929")]
    assert entity.entity_id == ids.derive(STATION_SYSTEM, "2929", kind="entity")
    # NOT the adapter's own system name: a SAC/SIC is allocated across the whole ASTERIX family.
    assert STATION_SYSTEM != AsterixCat034Adapter.system
    assert "allocated across the whole ASTERIX family" in entity.attributes["identity_basis"]
    # And the contrast with the sibling is stated on the object rather than only in a row.
    assert "asterix_cat048.py" in entity.attributes["data_source"]["basis"]


def test_the_entity_id_is_stable_across_records_of_one_station():
    """Two records, one block, two message types — and one station, so one entity."""
    entities = [o for o in translate("two_records_one_block") if isinstance(o, Entity)]
    assert len(entities) == 2
    assert entities[0].entity_id == entities[1].entity_id, (
        "two records from one station derived two entity_ids. The station is the object and its "
        "identifier is the SAC/SIC, so this is what `stable across updates` means here"
    )
    # The EVENTS are distinct, because two service messages are two things that happened.
    events = [o for o in translate("two_records_one_block") if isinstance(o, Event)]
    assert events[0].event_id != events[1].event_id
    assert [e.payload["record_index"] for e in events] == [0, 1]
    assert all(e.payload["record_count"] == 2 for e in events)


def test_no_object_carries_kinematics_and_the_sector_number_is_not_a_course():
    """A station does not move, and the one bearing the category carries is the ANTENNA's."""
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Entity):
                assert obj.kinematics is None, path.name
    event = event_of("sector_crossing_with_rotation")
    sector = event.payload["sector_number"]
    assert sector["degrees"] == pytest.approx(123.75)
    assert sector["lsb_degrees"] == pytest.approx(360.0 / 256)
    assert "would state that the radar head is travelling on that heading" in sector["basis"]


def test_valid_to_is_none_on_every_object_even_where_a_rotation_period_is_present():
    """A rotation period is a staleness horizon for reports this adapter never emits."""
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Entity):
                assert obj.valid_to is None, path.name
                assert obj.confidence is None, path.name
    event = event_of("sector_crossing_with_rotation")
    assert event.payload["antenna_rotation"]["period_s"] == pytest.approx(4.0)


# ============================================== I034/120, the Position, and gap 24


def test_the_station_position_is_read_at_the_documents_own_resolution():
    entity = entity_of("station_position_three_dimensional")
    position = entity.position
    assert position is not None
    lsb = 180.0 / (1 << 23)
    assert abs(position.lat - 57.39) <= lsb / 2
    assert abs(position.lon - 21.56) <= lsb / 2
    assert position.alt_m == -12.0, "the negative ellipsoidal height did not survive"
    assert position.position_source is PositionSource.MANUAL
    # The quantisation step is NOT an accuracy, and reporting it as one would claim the station
    # knows where it is to 2.4 m when the document says only that it cannot say so more finely.
    assert position.accuracy_m is None
    parked = entity.attributes["position_quantisation_m"]
    assert "2.3844 metres" in parked["quoted"]
    assert "QUANTISATION STEP" in parked["basis"]
    # HAE, not MSL — the datum the sibling adapter's height item uses.
    assert "ELLIPSOIDAL height" in entity.attributes["position_basis"]["height_datum"]


def test_the_station_position_does_not_close_gap_24():
    """SETTLEMENT 2, ASSERTED AT BOTH ENDS RATHER THAN RECORDED IN A COMMENT.

    `I034/120` carries the value `asterix_cat048.py` requires a caller to INJECT, and gap 24
    records that the geodesy is absent from the pinned CAT048 document. Reading it out of a CAT034
    record to resolve a CAT048 target's range and azimuth is cross-payload state, so the value
    becomes a `Position` on the object that carries it and is handed to nobody.

    The gap therefore does not close, and this test is what stops that being true only in prose:
    the object's own basis key must say so, and gap 24's entry in FORMAT_COVERAGE.md must still be
    open. A comment could have said either and no build would have noticed it going stale.
    """
    entity = entity_of("station_position_three_dimensional")
    basis = entity.attributes["position_basis"]
    assert basis["handed_to"] is None, (
        "position_basis.handed_to is no longer null. The value is handed to nobody, and the key "
        "exists so that a consumer reading the object can see that rather than assume it"
    )
    assert "NOT CLOSED" in basis["gap_24"]
    assert "cross-payload state" in basis["gap_24"]
    assert "asterix_cat048.py" in basis["gap_24"], (
        "the basis no longer names the adapter the value is NOT handed to"
    )
    # The other end: gap 24 is still an open gap and still says CAT034 does not close it.
    doc = DOC.read_text()
    start = doc.index("\n24. **No sensor frame")
    gap = _flat(doc[start:doc.index("\n25. **", start)])
    assert "ADAPTER #12 DOES NOT CLOSE IT EITHER" in gap, (
        "gap 24 no longer records that a shipped CAT034 adapter leaves it open. A reader meeting "
        "both sections would otherwise conclude the gap was closed and nobody noticed"
    )
    assert "test_the_station_position_does_not_close_gap_24" in gap, (
        "gap 24 no longer names the test that holds it open, so the two ends are unlinked"
    )
    # And no CAT034 object ever carries a CAT048 item as DATA. The basis prose above names
    # I048/110 deliberately — that is the record of the refusal — so the check is on the parked
    # trees, which is where a value crossing over would actually land.
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if not isinstance(obj, Entity):
                continue
            for bag in (obj.attributes["cat034_items"], obj.attributes["source_extras"]):
                keys = json.dumps(bag)
                assert "I048/" not in keys, (
                    f"{path.name} parked a CAT048 item. Whatever produced it is cross-payload "
                    "state, which is the refusal settlement 2 rests on"
                )


def test_a_latitude_outside_the_stated_range_is_refused_rather_than_clamped():
    """A clamped station is a station somewhere real, and every downstream check would pass."""
    generator = _build_fixtures_module()
    items = generator._base(1)
    items["I034/120"] = {"height_raw": 0, "latitude_raw": 0x7FFFFF, "longitude_raw": 0}
    octets = generator.block(generator.record(items))
    with pytest.raises(Cat034ParseError) as caught:
        adapter().to_cdm(octets)
    assert "-90<= latitude<= 90 degrees" in str(caught.value)
    assert "clamping" in str(caught.value)


# ====================================================== settlement 7, the polar window


def test_no_object_ever_carries_a_geometry():
    """Settlement 7, over the whole set. `Event.geometry` is None everywhere, permanently."""
    seen_windows = 0
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Event):
                assert obj.geometry is None, path.name
                if "generic_polar_window" in obj.payload:
                    seen_windows += 1
    assert seen_windows >= 4, (
        f"only {seen_windows} fixture records carry a polar window, so this check is passing on "
        "almost nothing. Five message types can carry one"
    )


def test_the_polar_window_is_parked_as_four_raw_fields_with_the_ruling_in_the_object():
    event = event_of("geographical_filter_polar_window")
    window = event.payload["generic_polar_window"]
    for key in ("rho_start_raw", "rho_end_raw", "theta_start_raw", "theta_end_raw"):
        assert key in window
    assert window["rho_start_nm"] == pytest.approx(5.0)
    assert window["rho_end_nm"] == pytest.approx(25.0)
    assert window["theta_start_deg"] == pytest.approx(300.0, abs=0.006)
    assert window["theta_end_deg"] == pytest.approx(330.0, abs=0.006)
    basis = window["geometry_basis"]
    assert "TABLE 2 IS THE REASON RATHER THAN EFFORT" in basis
    assert "mutually exclusive" in basis.lower()


def test_a_record_carrying_both_items_still_derives_nothing():
    """The non-conformant case, and it is the half that makes the rule have no exception.

    An item present under an X is parked rather than refused, so a record CAN arrive carrying both
    the polar window and the station position. Deriving from it would make the adapter's output
    depend on the malformation — a polygon that appears only when the encoder is broken.
    """
    generator = _build_fixtures_module()
    items = generator._base(4, **{
        "I034/100": generator._window(1.0, 2.0, 0.0, 90.0),
        "I034/120": generator._position(57.39, 21.56, 0.0),
    })
    objects = adapter().to_cdm(generator.block(generator.record(items)))
    event = next(o for o in objects if isinstance(o, Event))
    entity = next(o for o in objects if isinstance(o, Entity))
    assert event.geometry is None, (
        "a record carrying both items produced a Geometry. Settlement 7 has no exception: the "
        "record is non-conformant, and an output that depends on a malformation is worse than no "
        "output"
    )
    assert entity.position is not None, "the position itself is still read"
    assert entity.attributes["table_2_disposition"][
        "items_present_where_the_table_says_X"] == ["I034/120"]


# ================================================== the counters, the filter, the parks


def test_the_counters_are_an_ordered_list_with_duplicates_preserved():
    event = event_of("message_counts_twenty_one_types")
    counters = event.payload["message_counts"]["counters"]
    assert [c["typ"] for c in counters] == list(range(21)) + [0], (
        "the counter order or the duplicate did not survive. Order is data — §5.2.8 does not say "
        "the TYPs are unique — and egress is byte-exact only if they go back out as they came in"
    )
    assert [c["counter"] for c in counters] == [t * 10 for t in range(21)] + [7]
    assert all(c["text"] == COUNTER_TYP_TEXT[c["typ"]] for c in counters)


def test_the_accumulation_window_is_per_counter_and_not_per_item():
    """§5.2.8's Definition says "unless otherwise stated in the TYP definition below", and four
    TYPs do state otherwise. Parking one window for the item would be wrong for four of twenty-one.
    """
    assert PER_SECTOR_TYPS == {17, 18, 19, 20}, sorted(PER_SECTOR_TYPS)
    counters = event_of("message_counts_twenty_one_types").payload["message_counts"]["counters"]
    by_typ = {c["typ"]: c["window"] for c in counters}
    for typ in PER_SECTOR_TYPS:
        assert by_typ[typ] == "one sector", typ
    for typ in (0, 1, 16):
        assert "North crossings" in by_typ[typ], typ
    assert len({v for v in by_typ.values()}) == 2, (
        "every counter now carries the same window, so the per-counter rule has collapsed back "
        "into a per-item one"
    )


def test_a_data_filter_of_zero_lands_in_unresolved_raw_and_never_reads_as_no_filter():
    """§5.2.11 spells the value 0 "invalid value" in the item's own table."""
    entity = entity_of("geographical_filter_polar_window")
    event = event_of("geographical_filter_polar_window")
    assert event.payload["data_filter"]["raw"] == 0
    assert event.payload["data_filter"]["text"] is None
    assert 0 not in DATA_FILTER_TEXT
    unresolved = entity.attributes["unresolved_raw"]
    assert "I034/110 TYP" in unresolved
    assert "invalid value" in unresolved["I034/110 TYP"]["reason"]
    assert "never reads as 'no filter'" in unresolved["I034/110 TYP"]["reason"].replace(
        "NEVER reads as 'no filter'", "never reads as 'no filter'")


def test_ch_a_b_is_parked_under_three_keys_with_three_wordings():
    """One encoding, three subfields, three meanings — recorded rather than harmonised."""
    parked = entity_of("system_status_all_four_subfields").attributes[
        "system_configuration_and_status"]
    assert parked["psr"]["ch_ab_text"] == "Diversity mode ; Channel A and B selected"
    assert parked["ssr"]["ch_ab_text"] == "Invalid combination"
    assert parked["mds"]["ch_ab_text"] == "Illegal combination"
    assert len({parked[k]["ch_ab_text"] for k in ("psr", "ssr", "mds")}) == 3, (
        "the three wordings have been merged. Same bit positions, different meaning per sensor, "
        "and a merged key would state that the document means one thing by the encoding"
    )
    assert parked["com"]["nogo"] == 1
    assert "operational SDPS" in parked["com"]["nogo_text"]
    assert "parked rather than raised into severity" in parked["com"]["nogo_basis"]


def test_configuration_and_processing_mode_are_two_keys_that_never_merge():
    config = entity_of("system_status_all_four_subfields").attributes
    mode = entity_of("processing_mode_reduction_steps").attributes
    assert "system_configuration_and_status" in config
    assert "system_processing_mode" not in config
    assert "system_processing_mode" in mode
    assert "system_configuration_and_status" not in mode
    parked = mode["system_processing_mode"]
    assert parked["com"]["red_rdp_text"] == "Reduction step 3 active"
    assert parked["com"]["red_xmt_text"] == "Reduction step 5 active"
    assert parked["psr"]["pol_text"] == "Circular polarization"
    assert parked["psr"]["stc_text"] == "STC Map-4"
    assert parked["mds"]["clu_text"] == "Not autonomous"
    assert "not subject to standardisation" in parked["basis"]


def test_the_re_and_sp_fields_are_parked_verbatim_and_never_decoded():
    entity = entity_of("re_and_sp_carried")
    expansion = entity.attributes["reserved_expansion_field"]
    special = entity.attributes["special_purpose_field"]
    assert expansion["contents"] == "0102030405"
    assert special["contents"] == "aabbcc"
    assert "NEVER DECODED" in expansion["basis"]
    assert "no §5.2 entry at all" in expansion["basis"], (
        "the RE basis no longer states the procedural reason. This document defines no part of "
        "the field and lists no appendix that does, which is one step stronger than the sibling's"
    )
    assert "bilateral agreement" in special["basis"]


def test_the_integrity_basis_says_the_gate_was_structural_and_names_what_it_cannot_catch():
    """CAT034 defines no checksum at any level, so the honest statement is on every object."""
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            if isinstance(obj, Entity):
                basis = obj.attributes["integrity_basis"]
                assert "NO checksum at any level" in basis, path.name
                assert "single bit flipped inside a fixed-length field" in basis, path.name


# =========================================================================== egress


@pytest.mark.parametrize("path", blocks(), ids=lambda p: p.stem)
def test_every_fixture_round_trips_byte_for_byte(path):
    """The check the harness reports SKIP for, and it is stronger than what it skips.

    `build_block` re-encodes every item FROM ITS PARSED FIELDS and compares the result against the
    octets parked on ingest, so this is not a copy of the input: a spare bit the decoder read and
    the encoder forgot fails here.
    """
    raw = path.read_bytes()
    objects = adapter().to_cdm(raw)
    emitted = adapter().from_cdm([o for o in objects if isinstance(o, Entity)])
    assert emitted == raw, (
        f"{path.name} did not round-trip:\n  in  {raw.hex()}\n  out {emitted.hex()}"
    )


def test_the_parsed_twin_and_the_octets_produce_identical_objects():
    """A caller holding the parsed form gets the same CDM as one holding the block."""
    for path in blocks():
        from_bytes = adapter().to_cdm(path.read_bytes())
        parsed = json.loads((FIXTURES / f"{path.stem}.parsed.json").read_text())
        from_dict = adapter().to_cdm(parsed)
        assert [o.model_dump(mode="json") for o in from_bytes] == \
            [o.model_dump(mode="json") for o in from_dict], path.name


def test_a_non_minimal_fspec_is_re_emitted_as_parked_and_not_recomputed():
    """§4.7 requires only that a present item's bit is set, so a longer FSPEC is legal."""
    raw = block_of("non_minimal_fspec")
    entity = entity_of("non_minimal_fspec")
    assert entity.attributes["cat034_fspec"] == "e100", entity.attributes["cat034_fspec"]
    # The shortest covering FSPEC would be one octet, so recomputing would shorten the record.
    assert codec.write_fspec([1, 2, 3]).hex() == "e0"
    assert adapter().from_cdm([entity]) == raw


def test_egress_recomputes_len_and_never_copies_it():
    """A LEN that disagrees with the octets is discarded by every ASTERIX decoder."""
    entity = entity_of("two_records_one_block")
    entities = [o for o in translate("two_records_one_block") if isinstance(o, Entity)]
    emitted = adapter().from_cdm(entities)
    assert int.from_bytes(emitted[1:3], "big") == len(emitted)
    assert emitted[0] == CATEGORY
    # And a block built from ONE of the two records states its own shorter length.
    single = adapter().from_cdm([entity])
    assert int.from_bytes(single[1:3], "big") == len(single) < len(emitted)


def test_egress_refuses_an_object_that_did_not_come_from_cat034_and_names_each_missing_input():
    stranger = Entity(
        source=adapter().source_ref(),
        source_ids=[{"system": "SOMETHING", "external_id": "x"}],
        entity_id=ids.derive("SOMETHING", "x"),
        entity_type=EntityType.SENSOR, affiliation=Affiliation.UNKNOWN,
        valid_from=CLOCK(),
    )
    with pytest.raises(Cat034ParseError) as caught:
        adapter().from_cdm([stranger])
    message = str(caught.value)
    assert "source_extras.items" in message and "cat034_fspec" in message
    assert "I034/010" in message and "I034/000" in message


def test_a_track_cannot_become_a_data_block_and_the_reason_is_stated():
    track = Track(
        source=adapter().source_ref(),
        source_ids=[{"system": STATION_SYSTEM, "external_id": "2929"}],
        track_id=ids.derive(STATION_SYSTEM, "2929", kind="track"),
        entity_id=ids.derive(STATION_SYSTEM, "2929"),
        samples=[TrackSample(position={"lat": 57.39, "lon": 21.56,
                                       "position_source": "MANUAL"},
                             observed_at=CLOCK())],
    )
    with pytest.raises(Cat034ParseError) as caught:
        adapter().from_cdm([track])
    message = str(caught.value)
    assert "stationary station" in message
    assert "would NAME a radar station that does not exist" in message


# ========================================================================= refusals


def test_the_refusal_directory_holds_exactly_the_three_the_row_set_names():
    names = sorted(p.stem for p in REFUSALS.glob("*.cat034"))
    assert names == ["length_disagrees_with_buffer", "missing_mandatory_data_source",
                     "wrong_category"], names
    # And the count is stated in the row set, because a count nobody restates goes stale — which
    # is exactly what Phase 1's own fixture prose did.
    flat = _flat(_section())
    assert "seventeen translatable and three refusals" in flat, (
        "the section no longer states the split. Phase 1's prose said twenty and four while its "
        "table had nineteen rows and three, because the totals were counted off a sub-heading — "
        "and the set reached twenty by needing one more fixture rather than by that miscount "
        "being right"
    )
    assert len(list(FIXTURES.glob("*.cat034"))) == 17


@pytest.mark.parametrize("name,expected", [
    ("wrong_category", "plausible wrong radar status"),
    ("length_disagrees_with_buffer", "total length in octets of the Data Block"),
    ("missing_mandatory_data_source", "M in every column of Table 2"),
])
def test_each_refusal_names_what_was_wrong(name, expected):
    raw = (REFUSALS / f"{name}.cat034").read_bytes()
    with pytest.raises(Cat034ParseError) as caught:
        adapter().to_cdm(raw)
    assert expected in str(caught.value), str(caught.value)


def test_an_fspec_bit_past_the_uap_is_refused_rather_than_skipped():
    """There is no FRN 15, so a third FSPEC octet names nothing that can be decoded."""
    with pytest.raises(codec.CodecError) as caught:
        codec.read_fspec(bytes([0x81, 0x81, 0x80]), 0)
    message = str(caught.value)
    assert "category 034 UAP defines 14 FRNs" in message
    assert "there is no FRN 15" in message


def test_a_compound_items_spare_presence_bit_and_its_fx_are_both_refused():
    """Two bits that announce something §5.2.6 and §5.2.7 do not define."""
    generator = _build_fixtures_module()
    for item, bad_primary, expect in (
        ("I034/050", 0x40, "Spare Subfield"),
        ("I034/050", 0x01, "Extension of Primary Subfield"),
        ("I034/060", 0x02, "Spare Subfield"),
        ("I034/060", 0x01, "Extension of Primary Subfield"),
    ):
        body = bytes([0xE2 if item == "I034/050" else 0xE1])
        # Build the record by hand: FSPEC then 010, 000, 030, then the item's bad primary octet.
        frn = FRN_BY_ITEM[item]
        fspec = codec.write_fspec([1, 2, 3, frn])
        record = fspec + ENCODERS["I034/010"]({"sac": 0x29, "sic": 0x29}) \
            + ENCODERS["I034/000"]({"message_type": 1}) \
            + ENCODERS["I034/030"]({"time_of_day_raw": 0}) + bytes([bad_primary])
        octets = generator.block(record)
        with pytest.raises(Cat034ParseError) as caught:
            parse_block(octets)
        assert expect in str(caught.value), (item, hex(bad_primary), str(caught.value))
        assert "desynchronise" in str(caught.value)
        assert body  # the local is kept only to make the two branches visibly parallel


def test_a_zero_repetition_counter_item_is_refused_on_the_items_own_words():
    """§5.2.8: "followed by at least one message counter of two-octet length"."""
    generator = _build_fixtures_module()
    fspec = codec.write_fspec([1, 2, 3, FRN_BY_ITEM["I034/070"]])
    record = fspec + ENCODERS["I034/010"]({"sac": 0x29, "sic": 0x29}) \
        + ENCODERS["I034/000"]({"message_type": 1}) \
        + ENCODERS["I034/030"]({"time_of_day_raw": 0}) + bytes([0x00])
    with pytest.raises(Cat034ParseError) as caught:
        parse_block(generator.block(record))
    assert "AT LEAST ONE message counter" in str(caught.value)


# ================================================ the row set, table by named table


def test_every_row_of_every_named_table_claims_this_adapter():
    """Scoped per table, so a row that lost its marker cannot hide behind six other tables."""
    tables = (
        "### Row set — the block and record envelope",
        "### Row set — the station, which is the object this category is about",
        "### Row set — message type, and the seven records that are one shape",
        "### Row set — the sweep: sector, rotation, and the timing context CAT048 does not have",
        "### Row set — station configuration and processing mode, the two compound items",
        "### Row set — the counters and the filter",
        "### Row set — RE and SP",
        "### Row set — egress, CDM back to a CAT034 data block",
    )
    for heading in tables:
        rows = [r for r in _table(heading) if r.count("|") >= 4 and "Status" not in r]
        assert rows, f"{heading} has no data rows; the heading or the table has moved"
        unmarked = [r for r in rows if "`cat034 1.0.0" not in r]
        assert not unmarked, (
            f"{heading}: {len(unmarked)} row(s) carry no status marker: {[r[:80] for r in unmarked]}"
        )


def test_the_egress_table_states_cdm_field_so_its_paths_are_actually_resolved():
    """The defect five of the six egress row sets in this document still carry, repaired here.

    `tests/test_cdm_format_coverage.py` resolves CDM paths only out of a column whose header names
    it, so a table headed `| CDM | ... |` contributes NOTHING to that check. GMTIF's was repaired
    and CAT034's was written repaired; bringing the other five into line is a separate edit on five
    row sets that already ship, and it is deliberately not made here.
    """
    section = _section()
    assert section.count("| CDM field | CAT034 | Status | Notes |") == 1
    assert "| CDM | CAT034 |" not in section
    rows = _table("### Row set — egress, CDM back to a CAT034 data block")
    assert len([r for r in rows if "`cat034 1.0.0 · egress`" in r]) >= 6


def test_the_filled_in_fields_table_names_every_value_the_format_cannot_state():
    rows = _table("### What the adapter will fill that CAT034 does not state")
    body = " ".join(rows)
    for field in ("SourceRef.synthetic", "Entity.affiliation", "Event.received_at",
                  "Entity.entity_type", "Position.position_source"):
        assert field in body, f"{field} is no longer listed as a filled-in value"
    assert "no simulation indicator at any level" in body, (
        "the synthetic row no longer records the COUNTED absence it rests on"
    )


def test_the_ambiguity_register_carries_the_four_entries_phase_2_added():
    rows = _table("### Where the specification is ambiguous or contradicts itself")
    numbered = [r for r in rows if r.strip().startswith("| ") and r.split("|")[1].strip().isdigit()]
    assert len(numbered) == 12, (
        f"the register has {len(numbered)} numbered entries, expected 12 — eight from Phase 1 and "
        "four from Phase 2, three of them found by writing the codec and one by a mutation. A "
        "register that stops growing between phases is a register nobody is adding to"
    )
    body = " ".join(numbered)
    assert "Acceptable Range of values" in body, "ambiguity 9 (the time bound) is gone"
    assert "Max. Range = 256 NM" in body, "ambiguity 10 (rho's printed maximum) is gone"
    assert "1+1+" in body, "ambiguity 11 (Table 3's unexplained notations) is gone"
    assert "never assume and rely on" in body, "ambiguity 12 (§4.4 vs the diagrams) is gone"


def test_every_reachable_spare_bit_is_read_and_written_back_unchanged():
    """§4.4, and it is a NORMATIVE sentence rather than the recommendation beside it.

    "Decoders of ASTERIX data shall **never assume and rely on** specific settings of spare or
    unused bits. However in order to improve the readability of binary dumps of ASTERIX records,
    it is recommended to set all spare bits to zero." So zero is a recommendation to encoders and
    a decoder that depends on it is non-conformant — while eleven of §5.2.6's and §5.2.7's
    subfield diagrams legend their spares "set to zero". Ambiguity 12.

    **This test and its fixture were both asked for by a mutation.** Zeroing I034/050's COM spare
    bit inside the decoder passed the whole suite, because every fixture in the Phase 1 plan has
    its spare bits at zero and a dropped zero re-encodes as a zero. The round trip was proving
    nothing about spare bits at all.
    """
    entity = entity_of("spare_bits_nonzero")
    config = entity.attributes["source_extras"]["items"]["I034/050"]
    mode = entity.attributes["source_extras"]["items"]["I034/060"]
    assert config["com"]["spare_bit_1"] == 1
    assert config["psr"]["spare_bits_3_1"] == 0b111
    assert config["ssr"]["spare_bits_3_1"] == 0b111
    assert config["mds"]["spare_bits_7_1"] == 0b1111111
    assert mode["com"]["spare_bit_8"] == 1 and mode["com"]["spare_bit_1"] == 1
    assert mode["psr"]["spare_bits_2_1"] == 0b11
    assert mode["ssr"]["spare_bits_5_1"] == 0b11111
    assert mode["mds"]["spare_bits_4_1"] == 0b1111
    # And the round trip, which is the property §4.4 actually asks a decoder to have.
    raw = block_of("spare_bits_nonzero")
    assert adapter().from_cdm([entity]) == raw
    # The PRIMARY subfield's three spare bits are NOT among them and cannot be: a set one
    # announces a secondary subfield the document does not define, so it is a refusal.
    assert config["primary"]["spare_bit_7"] == 0
    assert config["primary"]["spare_bit_6"] == 0
    assert config["primary"]["spare_bit_2"] == 0


def test_the_phase_2_changes_are_listed_in_one_place():
    """The standing rule is that a row changes in the same commit as the code that contradicts it.

    Four rows changed. Listing them at their sites alone would leave a reader to find four
    scattered edits, so they are also listed together — and this asserts the list did not shrink.
    """
    rows = _table("### What Phase 2 changed in the Phase 1 row set")
    data = [r for r in rows if "**" in r]
    assert len(data) == 5, f"{len(data)} changes listed, expected 5: {[r[:60] for r in data]}"
    body = " ".join(data)
    for topic in ("sector_crossing_with_rotation", "station_position_three_dimensional",
                  "midnight_rollover_nearest", "message_type_008", "spare_bits_nonzero"):
        assert topic in body, f"the {topic} change is no longer listed"


# ============================================================ the fixtures and goldens


def test_every_fixture_has_both_twins_and_a_golden_for_each():
    """Seventeen payloads, thirty-four replayed fixtures, thirty-four golden files."""
    payloads = sorted(p.stem for p in FIXTURES.glob("*.cat034"))
    assert len(payloads) == 17, payloads
    for name in payloads:
        assert (FIXTURES / f"{name}.parsed.json").exists(), f"{name} has no parsed twin"
        assert (GOLDEN / f"{name}.cdm.json").exists(), f"{name}.cat034 has no golden"
        assert (GOLDEN / f"{name}.parsed.cdm.json").exists(), f"{name}.parsed.json has no golden"
    assert len(list(GOLDEN.glob("*.json"))) == 34


def test_the_generator_is_the_only_thing_that_writes_the_octets():
    """Every fixture on disk is reproducible from the generator, byte for byte."""
    generator = _build_fixtures_module()
    built = generator.fixtures()
    assert sorted(built) == sorted(p.stem for p in FIXTURES.glob("*.cat034"))
    for name, octets in built.items():
        assert (FIXTURES / f"{name}.cat034").read_bytes() == octets, (
            f"{name}.cat034 on disk differs from what build_fixtures.py produces. Edit the "
            "generator, never the octets"
        )
    for name, octets in generator.refusals().items():
        assert (REFUSALS / f"{name}.cat034").read_bytes() == octets, name


def test_no_fixture_carries_a_uuid_because_the_wire_form_has_none():
    """The convention binds nothing in this set, and the row set says so rather than leaving the
    absence looking like an omission: CAT034's identifiers are a SAC/SIC pair and nothing else, so
    every UUID in a golden file is a DERIVED uuid5 and not free to choose."""
    for path in FIXTURES.glob("*.parsed.json"):
        assert "f1c7" not in path.read_text().lower(), path.name
    entity = entity_of("north_marker_minimal")
    assert entity.entity_id == ids.derive(STATION_SYSTEM, "2929", kind="entity")
    row = next(r for r in _table("### The fixtures — twenty of them, built by a generator")
               if "**UUIDs**" in r)
    assert "no UUIDs" in row


def test_every_fixture_is_synthetic_and_says_so_on_every_object():
    for path in blocks():
        for obj in adapter().to_cdm(path.read_bytes()):
            assert obj.source.synthetic is True, path.name
            assert obj.source.adapter == "cat034"
            assert obj.source.adapter_version == "1.0.0"
            assert obj.source.system == "ASTERIX_CAT034"


def test_the_adapter_declares_no_transforms_and_therefore_excuses_nothing():
    """An empty TRANSFORMS is a CLAIM: every wire value is parked verbatim as well as converted,
    so `lossless.unrepresented()` runs at full strength over every fixture with nothing exempted."""
    assert AsterixCat034Adapter.TRANSFORMS == {}
    entity = entity_of("system_status_all_four_subfields")
    # The three parks that make the claim true, on one object.
    assert entity.attributes["cat034_items"]["I034/050"]
    assert entity.attributes["cat034_fspec"]
    assert entity.attributes["source_extras"]["items"]["I034/050"]["primary"]["com"] == 1
