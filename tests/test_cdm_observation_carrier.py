"""The CDM 3.2.0 observation carrier: one `EventType` member, `Event.validity`, `Track.attributes`.

Landed 2026-10-15 with `SCHEMA_VERSION` still 3.1.0, released as `v3.4.0` (corrected 2026-10-16,
at the replay onto that tag; the release commit types 3.2.0), so this module states the three
additions on their own terms and against the two contracts that matter
until then: the PUBLISHED schemas under `schemas/`, re-exported from the models, which must carry
them; and the FROZEN 3.0.0 contract under `tests/frozen/cdm/3.0.0/`, which must refuse them. The
second half is the consequence `MIGRATIONS.md` records for the landing — a reader at 3.0.0 refuses
the member, and refuses a `validity` or `attributes` key populated or null — shown on bytes here
rather than argued.

Every expectation below is a literal written by hand: the member list, the error locations, the
messages and the dumped blocks. Nothing is compared with output the code under test produced.
"""

import copy
import json
import pathlib
import pickle

import pytest
from pydantic import ValidationError

from synapse_cdm.enums import EventType
from synapse_cdm.models import Event, Track, TrackAttributes, TrackCompleteness
from synapse_cdm.schemas import validator_for

REPO = pathlib.Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "schemas"
FROZEN_3_0_0 = REPO / "tests" / "frozen" / "cdm" / "3.0.0"

T0 = "2026-04-29T06:00:00.000Z"
T1 = "2026-04-29T07:00:00.000Z"
T2 = "2026-04-29T07:10:00.000Z"
SOURCE = {"system": "TEST", "adapter": "test", "adapter_version": "1.0.0", "synthetic": True}
IDS = [{"system": "TEST", "external_id": "EX001"}]
SAMPLE_0 = {"observed_at": T0, "position": {"lat": 57.0, "lon": 21.0, "position_source": "GNSS"}}
SAMPLE_1 = {"observed_at": T1, "position": {"lat": 57.1, "lon": 21.1, "position_source": "GNSS"}}

#: The eight members in declaration order, typed out: the published enum lists them in that order
#: and `tests/test_cdm_schemas.py` reads a MINOR as positions 0..6 unchanged plus a new leaf.
MEMBERS = [
    "DETECTION",
    "GNSS_INTERFERENCE",
    "TRACK_UPDATE",
    "ALERT",
    "STATUS_CHANGE",
    "PLAN_INJECT",
    "SIM_RESULT",
    "ENVIRONMENTAL_OBSERVATION",
]


def event(**overrides) -> dict:
    doc = {
        "schema_version": "3.1.0",
        "object_kind": "event",
        "source": SOURCE,
        "source_ids": IDS,
        "event_id": "6f1c2a52-0b7e-5e0a-9a36-1b1f4c3c2d10",
        "event_type": "DETECTION",
        "severity": "INFO",
        "observed_at": T1,
        "received_at": T2,
    }
    doc.update(overrides)
    return doc


def track(**overrides) -> dict:
    doc = {
        "schema_version": "3.1.0",
        "object_kind": "track",
        "source": SOURCE,
        "source_ids": IDS,
        "track_id": "0d3e7b8a-4c1f-5a6e-8b2d-9e0f1a2b3c4d",
        "entity_id": "1a2b3c4d-5e6f-5a7b-8c9d-0e1f2a3b4c5d",
        "samples": [copy.deepcopy(SAMPLE_0), copy.deepcopy(SAMPLE_1)],
    }
    doc.update(overrides)
    return doc


def completeness(**overrides) -> dict:
    block = {
        "carried_samples": 2,
        "stated_samples": 5,
        "fragment": True,
        "completeness_basis": "the source's own page header states five samples in all",
    }
    block.update(overrides)
    return block


def _schema(directory: pathlib.Path, stem: str) -> dict:
    return json.loads((directory / f"{stem}.schema.json").read_text())


def _errors(directory: pathlib.Path, stem: str, doc: dict) -> list[tuple[str, str, str]]:
    """(path, validator keyword, message) for every finding, sorted — the whole outcome."""
    return sorted(
        ("/".join(str(p) for p in e.absolute_path), e.validator, e.message)
        for e in validator_for(_schema(directory, stem)).iter_errors(doc)
    )


def _leaves(directory: pathlib.Path, stem: str, doc: dict) -> list[tuple[str, str, str]]:
    """Every LEAF finding, descending into `anyOf` branches, as (path, keyword, message).

    An optional field publishes as `anyOf: [<block>, null]`, so the top-level finding for a bad
    block is the `anyOf` at the field and the reason is one of its branches. The `null` branch's
    own refusal ("... is not of type 'null'") is among the leaves too, and is filtered out here:
    it says only that the value was not null.
    """
    out = []

    def walk(error):
        if error.context:
            for child in error.context:
                walk(child)
        elif not (error.validator == "type" and error.validator_value == "null"):
            out.append(
                ("/".join(str(p) for p in error.absolute_path), error.validator, error.message)
            )

    for error in validator_for(_schema(directory, stem)).iter_errors(doc):
        walk(error)
    return sorted(out)


def _model_errors(model, doc: dict) -> list[tuple[tuple, str, str]]:
    """(loc, type, msg) for every finding on the JSON path, sorted; [] when the model accepts."""
    try:
        model.model_validate_json(json.dumps(doc))
    except ValidationError as e:
        return sorted((err["loc"], err["type"], err["msg"]) for err in e.errors())
    return []


# --------------------------------------------------------------------- the member, and its place


def test_the_member_is_appended_last_and_spelled_out():
    assert [member.value for member in EventType] == MEMBERS
    assert [member.name for member in EventType] == MEMBERS
    assert EventType.ENVIRONMENTAL_OBSERVATION.value == "ENVIRONMENTAL_OBSERVATION"
    # Never the bare word: it collides with SC-OES's `EventClass.OBSERVATION` and with the
    # EntityType name the gap-20 guard forbids.
    assert "OBSERVATION" not in EventType.__members__


@pytest.mark.parametrize("stem", ["event", "cdm_object"])
def test_the_published_enum_carries_the_member_last(stem):
    assert _schema(PUBLISHED, stem)["$defs"]["EventType"]["enum"] == MEMBERS


def test_the_frozen_3_0_0_enum_is_the_seven_and_refuses_the_member():
    assert _schema(FROZEN_3_0_0, "event")["$defs"]["EventType"]["enum"] == MEMBERS[:7]
    assert _errors(FROZEN_3_0_0, "event", event()) == []
    assert _errors(FROZEN_3_0_0, "event", event(event_type="ENVIRONMENTAL_OBSERVATION")) == [
        (
            "event_type",
            "enum",
            "'ENVIRONMENTAL_OBSERVATION' is not one of ['DETECTION', 'GNSS_INTERFERENCE', "
            "'TRACK_UPDATE', 'ALERT', 'STATUS_CHANGE', 'PLAN_INJECT', 'SIM_RESULT']",
        ),
    ]


def test_the_published_schema_and_the_model_accept_the_member():
    doc = event(event_type="ENVIRONMENTAL_OBSERVATION")
    assert _errors(PUBLISHED, "event", doc) == []
    assert Event.model_validate_json(json.dumps(doc)).event_type is (
        EventType.ENVIRONMENTAL_OBSERVATION
    )


# ------------------------------------------------------------------------------ Event.validity


def test_the_frozen_3_0_0_contract_refuses_a_validity_key_even_when_null():
    unexpected = "Additional properties are not allowed ('validity' was unexpected)"
    assert _errors(FROZEN_3_0_0, "event", event(validity=None)) == [
        ("", "additionalProperties", unexpected)
    ]
    instant = {"effective": {"start": T1, "end": T1}}
    assert _errors(FROZEN_3_0_0, "event", event(validity=instant)) == [
        ("", "additionalProperties", unexpected)
    ]


def test_an_event_states_no_validity_by_default_and_dumps_it_as_null():
    parsed = Event.model_validate_json(json.dumps(event()))
    assert parsed.validity is None
    assert parsed.model_dump(mode="json")["validity"] is None


def test_an_instant_is_an_effective_period_whose_end_equals_its_start():
    doc = event(
        event_type="ENVIRONMENTAL_OBSERVATION", validity={"effective": {"start": T1, "end": T1}}
    )
    assert _errors(PUBLISHED, "event", doc) == []
    parsed = Event.model_validate_json(json.dumps(doc))
    assert parsed.model_dump(mode="json")["validity"] == {
        "observed_at": None,
        "valid_from": None,
        "valid_to": None,
        "effective": {"start": "2026-04-29T07:00:00.000Z", "end": "2026-04-29T07:00:00.000Z"},
    }


def test_an_observation_over_an_interval_states_it_and_observed_at_is_its_end():
    doc = event(
        event_type="ENVIRONMENTAL_OBSERVATION",
        observed_at=T1,
        validity={"effective": {"start": T0, "end": T1}},
    )
    assert _errors(PUBLISHED, "event", doc) == []
    dumped = Event.model_validate_json(json.dumps(doc)).model_dump(mode="json")
    assert dumped["observed_at"] == "2026-04-29T07:00:00.000Z"
    assert dumped["validity"] == {
        "observed_at": None,
        "valid_from": None,
        "valid_to": None,
        "effective": {"start": "2026-04-29T06:00:00.000Z", "end": "2026-04-29T07:00:00.000Z"},
    }


def test_an_open_ended_interval_has_no_end_and_a_backward_one_is_refused():
    open_ended = event(validity={"effective": {"start": T0}})
    dumped = Event.model_validate_json(json.dumps(open_ended)).model_dump(mode="json")
    assert dumped["validity"]["effective"] == {"start": "2026-04-29T06:00:00.000Z", "end": None}
    backward = event(validity={"effective": {"start": T1, "end": T0}})
    assert _errors(PUBLISHED, "event", backward) == []
    assert _model_errors(Event, backward) == [
        (
            ("validity", "effective"),
            "value_error",
            "Value error, SEM-005: end 2026-04-29T06:00:00.000Z precedes start "
            "2026-04-29T07:00:00.000Z — an interval that runs backwards is a translation defect, "
            "not data",
        )
    ]


def test_an_unknown_key_inside_validity_is_refused_by_both_validators():
    doc = event(validity={"effective": {"start": T0, "end": T1}, "valid_at": T1})
    assert [(path, keyword) for path, keyword, _ in _errors(PUBLISHED, "event", doc)] == [
        ("validity", "anyOf")
    ]
    assert _leaves(PUBLISHED, "event", doc) == [
        (
            "validity",
            "additionalProperties",
            "Additional properties are not allowed ('valid_at' was unexpected)",
        )
    ]
    assert _model_errors(Event, doc) == [
        (("validity", "valid_at"), "extra_forbidden", "Extra inputs are not permitted")
    ]


# ---------------------------------------------------------------------------- Track.attributes


def test_the_frozen_3_0_0_contract_refuses_an_attributes_key_on_a_track_even_when_null():
    assert _errors(FROZEN_3_0_0, "track", track()) == []
    assert _errors(FROZEN_3_0_0, "track", track(attributes=None)) == [
        (
            "",
            "additionalProperties",
            "Additional properties are not allowed ('attributes' was unexpected)",
        )
    ]


def test_a_track_states_no_attributes_by_default_and_dumps_them_as_null():
    parsed = Track.model_validate_json(json.dumps(track()))
    assert parsed.attributes is None
    assert parsed.model_dump(mode="json")["attributes"] is None


def test_the_completeness_block_round_trips_with_every_figure_it_states():
    doc = track(attributes={"completeness": completeness()})
    assert _errors(PUBLISHED, "track", doc) == []
    dumped = Track.model_validate_json(json.dumps(doc)).model_dump(mode="json")
    assert dumped["attributes"] == {
        "completeness": {
            "carried_samples": 2,
            "stated_samples": 5,
            "fragment": True,
            "completeness_basis": "the source's own page header states five samples in all",
        }
    }


def test_a_source_that_states_nothing_leaves_two_figures_null_and_never_zero_or_false():
    doc = track(
        attributes={
            "completeness": {
                "carried_samples": 2,
                "completeness_basis": "the source states no total and no paging",
            }
        }
    )
    dumped = Track.model_validate_json(json.dumps(doc)).model_dump(mode="json")
    assert dumped["attributes"] == {
        "completeness": {
            "carried_samples": 2,
            "stated_samples": None,
            "fragment": None,
            "completeness_basis": "the source states no total and no paging",
        }
    }


@pytest.mark.parametrize(
    "carried, message",
    [
        (
            3,
            "Value error, SEM-014: attributes.completeness.carried_samples is 3 and the Track "
            "carries 2 samples — the block describes a different list from the one it rides on",
        ),
        (
            1,
            "Value error, SEM-014: attributes.completeness.carried_samples is 1 and the Track "
            "carries 2 samples — the block describes a different list from the one it rides on",
        ),
    ],
    ids=["more-than-carried", "fewer-than-carried"],
)
def test_a_completeness_count_that_is_not_the_sample_count_is_refused(carried, message):
    doc = track(attributes={"completeness": completeness(carried_samples=carried)})
    # The schema cannot relate a number to an array's length, so it accepts the document; the
    # model is where the relation is held.
    assert _errors(PUBLISHED, "track", doc) == []
    assert _model_errors(Track, doc) == [((), "value_error", message)]


def test_the_count_is_held_on_assignment_too():
    parsed = Track.model_validate_json(json.dumps(track()))
    with pytest.raises(ValidationError, match="carried_samples is 3 and the Track carries 2"):
        parsed.attributes = TrackAttributes(
            completeness=TrackCompleteness(
                carried_samples=3, completeness_basis="assigned after construction"
            )
        )


def test_a_sample_list_changed_in_place_is_not_held_until_the_track_is_validated_again():
    """The limit the validator's docstring states (2026-10-15): an append to
    the live list is not an assignment, so nothing re-checks the count until the Track is read
    back through the model — where the same SEM-014 refusal stands."""
    parsed = Track.model_validate_json(
        json.dumps(track(attributes={"completeness": completeness()}))
    )
    parsed.samples.append(parsed.samples[1].model_copy())
    assert len(parsed.samples) == 3
    assert parsed.attributes.completeness.carried_samples == 2
    assert _model_errors(Track, parsed.model_dump(mode="json")) == [
        (
            (),
            "value_error",
            "Value error, SEM-014: attributes.completeness.carried_samples is 2 and the Track "
            "carries 3 samples — the block describes a different list from the one it rides on",
        )
    ]


def test_a_projection_refusal_survives_a_copy_and_a_pickle_round_trip():
    """Since 2026-10-15 a `ProjectionRefused` rebuilt by `copy.copy` and by `pickle` keeps its
    target, path, since and message, where it raised `TypeError` before."""
    from synapse_cdm.projection import ProjectionRefused, dump_for

    doc = event(
        event_type="ENVIRONMENTAL_OBSERVATION",
        validity={"effective": {"start": T0, "end": T1}},
    )
    with pytest.raises(ProjectionRefused) as caught:
        dump_for(Event.model_validate_json(json.dumps(doc)), "3.0.0")
    message = (
        "validity: a populated property added in CDM 3.2.0, which the 3.0.0 contract cannot state"
    )
    for again in (copy.copy(caught.value), pickle.loads(pickle.dumps(caught.value))):
        assert type(again) is ProjectionRefused
        assert (again.target, again.path, again.since) == ("3.0.0", "validity", "3.2.0")
        assert str(again) == message
    assert str(caught.value) == message


@pytest.mark.parametrize(
    "attributes, location",
    [
        ({"completeness": completeness(), "crs": "EPSG:4326"}, ("attributes", "crs")),
        (
            {"completeness": completeness(total_count=5)},
            ("attributes", "completeness", "total_count"),
        ),
    ],
    ids=["beside-the-block", "inside-the-block"],
)
def test_an_unknown_key_in_the_block_is_refused_by_both_validators(attributes, location):
    doc = track(attributes=attributes)
    key = location[-1]
    assert [(path, keyword) for path, keyword, _ in _errors(PUBLISHED, "track", doc)] == [
        ("attributes", "anyOf")
    ]
    assert _leaves(PUBLISHED, "track", doc) == [
        (
            "/".join(location[:-1]),
            "additionalProperties",
            f"Additional properties are not allowed ('{key}' was unexpected)",
        )
    ]
    assert _model_errors(Track, doc) == [
        (location, "extra_forbidden", "Extra inputs are not permitted")
    ]


COMPLETENESS = ("attributes", "completeness")
BASIS_PATH = "attributes/completeness/completeness_basis"
#: The model's pattern refusal and the published schema's, for a basis that is blank: the model
#: reads `\S` with Python's `re` (2026-10-15), the engine `validator_for` uses, so both refuse the
#: same strings, the Unicode spaces and the C0 separators `str.strip` removes among them.
BLANK = (
    COMPLETENESS + ("completeness_basis",),
    "string_pattern_mismatch",
    "String should match pattern '\\S'",
)


@pytest.mark.parametrize(
    "override, model, schema",
    [
        (
            {"carried_samples": 0},
            [
                (
                    COMPLETENESS + ("carried_samples",),
                    "greater_than_equal",
                    "Input should be greater than or equal to 1",
                )
            ],
            [
                (
                    "attributes/completeness/carried_samples",
                    "minimum",
                    "0 is less than the minimum of 1",
                )
            ],
        ),
        (
            {"stated_samples": -1},
            [
                (
                    COMPLETENESS + ("stated_samples",),
                    "greater_than_equal",
                    "Input should be greater than or equal to 1",
                )
            ],
            [
                (
                    "attributes/completeness/stated_samples",
                    "minimum",
                    "-1 is less than the minimum of 1",
                )
            ],
        ),
        # D-R0-2: "never 0" — a source that states no total is None, so 0 is refused (2026-10-15).
        (
            {"stated_samples": 0},
            [
                (
                    COMPLETENESS + ("stated_samples",),
                    "greater_than_equal",
                    "Input should be greater than or equal to 1",
                )
            ],
            [
                (
                    "attributes/completeness/stated_samples",
                    "minimum",
                    "0 is less than the minimum of 1",
                )
            ],
        ),
        (
            {"completeness_basis": ""},
            [
                (
                    COMPLETENESS + ("completeness_basis",),
                    "string_too_short",
                    "String should have at least 1 character",
                )
            ],
            [
                (BASIS_PATH, "minLength", "'' should be non-empty"),
                (BASIS_PATH, "pattern", "'' does not match '\\\\S'"),
            ],
        ),
        (
            {"completeness_basis": "   "},
            [BLANK],
            [(BASIS_PATH, "pattern", "'   ' does not match '\\\\S'")],
        ),
        (
            {"completeness_basis": "\t\n"},
            [BLANK],
            [(BASIS_PATH, "pattern", "'\\t\\n' does not match '\\\\S'")],
        ),
        (
            {"completeness_basis": "  "},
            [BLANK],
            [(BASIS_PATH, "pattern", "'\\xa0\\u2003' does not match '\\\\S'")],
        ),
        (
            {"completeness_basis": "\x1c"},
            [BLANK],
            [(BASIS_PATH, "pattern", "'\\x1c' does not match '\\\\S'")],
        ),
    ],
    ids=[
        "no-carried-sample",
        "negative-stated-total",
        "zero-stated-total",
        "empty-basis",
        "spaces-basis",
        "tab-newline-basis",
        "unicode-spaces-basis",
        "separator-basis",
    ],
)
def test_the_figures_are_bounded_and_the_basis_is_not_blank(override, model, schema):
    doc = track(attributes={"completeness": completeness(**override)})
    assert _model_errors(Track, doc) == model
    with pytest.raises(ValidationError) as caught:
        Track(**doc)
    assert [(err["loc"], err["type"], err["msg"]) for err in caught.value.errors()] == model
    assert _leaves(PUBLISHED, "track", doc) == schema


def test_a_basis_with_one_character_that_is_not_blank_is_kept_as_written():
    block = completeness(completeness_basis=" \tone file of one day ")
    doc = track(attributes={"completeness": block})
    assert _model_errors(Track, doc) == []
    assert _leaves(PUBLISHED, "track", doc) == []
    parsed = Track.model_validate_json(json.dumps(doc))
    assert parsed.attributes.completeness.completeness_basis == " \tone file of one day "
    assert completeness(stated_samples=1)["stated_samples"] == 1
    assert (
        _model_errors(Track, track(attributes={"completeness": completeness(stated_samples=1)}))
        == []
    )


def test_the_basis_is_required():
    block = completeness()
    del block["completeness_basis"]
    doc = track(attributes={"completeness": block})
    assert _model_errors(Track, doc) == [
        (("attributes", "completeness", "completeness_basis"), "missing", "Field required")
    ]
    assert _leaves(PUBLISHED, "track", doc) == [
        ("attributes/completeness", "required", "'completeness_basis' is a required property")
    ]


# --------------------------------------------------------------------- a timestamp that is not text

#: The one message both validation paths give a timestamp that is neither text nor a datetime
#: (2026-10-15): it names the type and never the value.
NOT_A_TIMESTAMP = (
    "Value error, a timestamp is RFC 3339 text or a datetime, and a value of type {} is "
    "neither; the value is not repeated here"
)


@pytest.mark.parametrize(
    "value, type_name",
    [(5, "int"), (1773446400.25, "float"), (True, "bool"), (["2026"], "list")],
    ids=["int", "float", "bool", "list"],
)
def test_a_timestamp_that_is_not_text_is_a_validation_error_on_both_paths(value, type_name):
    doc = event(observed_at=value)
    expected = [(("observed_at",), "value_error", NOT_A_TIMESTAMP.format(type_name))]
    assert _model_errors(Event, doc) == expected
    with pytest.raises(ValidationError) as caught:
        Event(**doc)
    found = [(err["loc"], err["type"], err["msg"]) for err in caught.value.errors()]
    assert found == expected
    assert all(str(value) not in msg for _, _, msg in found)


#: The message for an instant whose UTC reading leaves the years 0001 to 9999 (2026-10-15,
#: checkpoint H-02): the conversion raised `OverflowError` out of the validator until then.
NOT_IN_UTC = (
    "Value error, a timestamp read in UTC falls before 0001-01-01 or after 9999-12-31, which no "
    "timestamp holds; the value is not repeated here"
)


def _instants_past_utc():
    import datetime as dt

    plus_14 = dt.timezone(dt.timedelta(hours=14))
    minus_14 = dt.timezone(dt.timedelta(hours=-14))
    return [
        "0001-01-01T00:00:00+14:00",
        "0001-01-01T00:00:00+00:01",
        "9999-12-31T23:59:59-14:00",
        "9999-12-31T23:59:59.999999-00:01",
        dt.datetime(1, 1, 1, tzinfo=plus_14),
        dt.datetime(9999, 12, 31, 23, 59, 59, tzinfo=minus_14),
    ]


@pytest.mark.parametrize(
    "value",
    _instants_past_utc(),
    ids=[
        "text-first-day-plus-14",
        "text-first-day-plus-1-minute",
        "text-last-day-minus-14",
        "text-last-microsecond-minus-1-minute",
        "datetime-first-day-plus-14",
        "datetime-last-day-minus-14",
    ],
)
def test_a_timestamp_utc_cannot_state_is_a_validation_error_on_the_python_path(value):
    doc = event(observed_at=value)
    expected = [(("observed_at",), "value_error", NOT_IN_UTC)]
    for validate in (lambda: Event(**doc), lambda: Event.model_validate(doc)):
        with pytest.raises(ValidationError) as caught:
            validate()
        assert [(err["loc"], err["type"], err["msg"]) for err in caught.value.errors()] == expected
    sample = dict(SAMPLE_0, observed_at=value)
    with pytest.raises(ValidationError) as caught:
        Track(**track(samples=[sample]))
    assert [(err["loc"], err["type"], err["msg"]) for err in caught.value.errors()] == [
        (("samples", 0, "observed_at"), "value_error", NOT_IN_UTC)
    ]


def test_the_last_instants_a_timestamp_holds_are_still_read():
    import datetime as dt

    first = Event(**event(observed_at="0001-01-01T00:00:00+00:00"))
    last = Event(**event(observed_at="9999-12-31T09:59:59.999-14:00"))
    assert first.model_dump(mode="json")["observed_at"] == "0001-01-01T00:00:00.000Z"
    assert last.model_dump(mode="json")["observed_at"] == "9999-12-31T23:59:59.999Z"
    assert first.observed_at == dt.datetime(1, 1, 1, tzinfo=dt.timezone.utc)


def test_text_and_a_datetime_still_reach_the_timestamp_parsers():
    import datetime as dt

    assert (
        Event(**event(observed_at=dt.datetime(2026, 4, 29, 6, tzinfo=dt.timezone.utc))).model_dump(
            mode="json"
        )["observed_at"]
        == T0
    )
    assert (
        Event(**event(observed_at="2026-04-29T08:00:00+02:00")).model_dump(mode="json")[
            "observed_at"
        ]
        == T0
    )
    assert _model_errors(Event, event(observed_at="2026-04-29T06:00:00Z")) == [
        (
            ("observed_at",),
            "value_error",
            "Value error, a timestamp on the wire is RFC 3339 UTC with exactly three decimal places "
            "and Z, e.g. 2026-04-29T06:12:44.000Z; got '2026-04-29T06:00:00Z'. A source's own form "
            "is parsed with times.parse() at the adapter, and the model receives the datetime",
        )
    ]
