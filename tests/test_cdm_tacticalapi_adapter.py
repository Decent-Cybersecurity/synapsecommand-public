"""`TacticalapiAdapter`, held to the record's §4, §5 and §6 rule by rule. The record is
`docs/tacticalapi-implementation.md`, the adapter's specification; this module came from the
adapter's out-of-tree project on 2026-10-06, when the adapter landed as #22.

Every test asserts the specific value a rule produces, never only that something is present, so a
wrong mapping fails. Three kinds of evidence are used, and the adapter is the oracle for none:

* THE RECORD ITSELF — the expected values below are written from the specification's tables (the
  vertical reference and measurement code tables are restated here by contract value name, not
  read from the adapter's own tables).
* PROTOC'S READINGS — `fixtures/tacticalapi/independent/<case>.value.txtpb`, read with
  `gates.protoc_text`; `test_emitted_canonical_values_agree_with_protocs_readings` derives every
  canonical value it checks from protoc's printed numbers and names.
* THE LEDGER — `synapse_cdm.lossless.ledger` over every twin, plus two negative tests showing it
  catches a wrong mapping rather than blessing what the adapter emits.

Inputs that no fixture carries are dict-form twins built here (`message`, `force`) or bytes built
with `tests/tacticalapi_protowire.py`, which `test_cdm_tacticalapi_codec.py` holds to protoc's own
bytes.
"""
from __future__ import annotations

import ast
import copy
import datetime as dt
import enum
import json
import pathlib

import jsonschema
import pytest
from synapse_cdm import canonical, harness, ids, lossless, manifests, schemas, times
from synapse_cdm.adapter import (REGISTRY, InputTooDeep, InputTooLarge, container_depth,
                                 is_shipped, json_nesting_depth, load_adapter, shipped)
from synapse_cdm.enums import Affiliation, EventType
from synapse_cdm.manifest import (ClaimStatus, Direction, LicenseClass, Limitation, LimitKind,
                                  MaturityLevel, Residual, UnknownFields, WireBinding)

from synapse_cdm.adapters import tacticalapi as module
from synapse_cdm.adapters import tacticalapi_codec as codec
from synapse_cdm.adapters.tacticalapi import TacticalapiAdapter
from synapse_cdm.adapters.tacticalapi_codec import TacticalapiRefused

from gates import protoc_text
from tests import tacticalapi_protowire as pw

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = pathlib.Path(module.__file__).resolve().parents[1]
SET = PKG / "fixtures" / "tacticalapi"
GOLDEN = SET / "golden"
MODULE_SOURCE = PKG / "adapters" / "tacticalapi.py"
CODEC_SOURCE = PKG / "adapters" / "tacticalapi_codec.py"
#: The adapter's specification in the repository, read by the tests that hold its wording.
RECORD = ROOT / "docs" / "tacticalapi-implementation.md"
#: The residual every object carries when nothing is unknown (the record §5.9, since 2026-10-06).
EMPTY_RESIDUAL = {"namespace": "TacticalAPI", "data": {"unknown": []}}

HARNESS_FIXTURES = ("snapshot_three_forces", "delta_with_deletion", "awkward_zeros",
                    "awkward_symbols_and_codes", "snapshot_with_unknown_fields")
#: The harness fixtures with nothing unknown in them (all but the one added 2026-10-04, final
#: verification, to carry unknown fields through the harness).
WITHOUT_UNKNOWN = tuple(case for case in HARNESS_FIXTURES if case != "snapshot_with_unknown_fields")
#: cases/, by name, with what the record says each one does.
CASES = ("unknown_field_carried", "empty_geo_point", "empty_successful_response",
         "deleted_without_timestamps", "duplicate_identity", "d_code_second_set_zero",
         "unknown_fields_without_carrier", "error_message_without_carrier")
#: The cases/ payloads the adapter refuses (the record §4: no object to carry what they hold).
REFUSED_CASES = ("unknown_fields_without_carrier", "error_message_without_carrier")
TRANSLATED = [*HARNESS_FIXTURES, *(f"cases/{name}" for name in CASES
                                   if name not in REFUSED_CASES)]
#: malformed/, by name, with the refusal fixtures/tacticalapi/README.md names for each.
MALFORMED = {
    "truncated_varint.binpb": "truncated-varint",
    "length_past_end.binpb": "length-exceeds-input",
    "wire_type_mismatch.binpb": "wire-type-mismatch",
    "unsupported_message_type.binpb": "unsupported-message-type",
    "success_false.binpb": "response-not-successful",
    "blue_force_without_identity.binpb": "blue-force-without-identity",
    "two_oneof_members.binpb": "multiple-oneof-members",
    "latitude_91.binpb": "coordinate-out-of-range",
}

GET = "type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse"
SUBSCRIBE = "type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse"
FROZEN = times.FROZEN_NOW
OTHER = dt.datetime(2027, 1, 2, 3, 4, 5, 678000, tzinfo=dt.timezone.utc)
EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def adapter(clock_at: dt.datetime = FROZEN) -> TacticalapiAdapter:
    return TacticalapiAdapter(clock=times.frozen_clock(clock_at))


def payload(case: str) -> bytes:
    return (SET / f"{case}.binpb").read_bytes()


def twin_file(case: str) -> dict:
    return json.loads((SET / f"{case}.parsed.json").read_text(encoding="utf-8"))


def dump(raw, clock_at: dt.datetime = FROZEN) -> list[dict]:
    return harness._dump(adapter(clock_at).to_cdm(raw))


def refused(code: str, raw, clock_at: dt.datetime = FROZEN) -> TacticalapiRefused:
    with pytest.raises(TacticalapiRefused) as caught:
        adapter(clock_at).to_cdm(raw)
    assert caught.value.code == code, str(caught.value)
    assert str(caught.value).startswith(f"{code}: ")
    return caught.value


def message(*elements: dict, header: dict | None = None, url: str = GET, **extra) -> dict:
    """A dict-form twin: a successful header unless one is given, and the elements."""
    document: dict = {"@type": url, "header": {"success": True} if header is None else header}
    if elements:
        document["blue_forces" if url == GET else "updated_blue_forces"] = list(elements)
    document.update(extra)
    return document


def force(**fields) -> dict:
    """One element; a string identity unless the caller states the identity."""
    return {"identity": {"string_identity": "EXERCISE-T-1"}, **fields}


def at(lat: float | None = 57.25, lon: float | None = 21.5, **geo) -> dict:
    """A point_location holding a geo_point; `None` leaves a coordinate off the wire."""
    point = dict(geo)
    if lat is not None:
        point["latitude_coordinate"] = lat
    if lon is not None:
        point["longitude_coordinate"] = lon
    return {"location_time": "2026-09-29T07:00:00Z", "geo_point": point}


def entities(objects: list[dict]) -> list[dict]:
    return [obj for obj in objects if obj["object_kind"] == "entity"]


def events(objects: list[dict]) -> list[dict]:
    return [obj for obj in objects if obj["object_kind"] == "event"]


def only_entity(raw) -> dict:
    [entity] = entities(dump(raw))
    return entity


# ======================================================================= §2 the two input forms


@pytest.mark.parametrize("case", TRANSLATED)
def test_the_bytes_form_and_the_dict_form_give_identical_objects(case):
    from_bytes = canonical.serialise(dump(payload(case)))
    from_dict = canonical.serialise(dump(twin_file(case)))
    assert from_bytes == from_dict


@pytest.mark.parametrize("case", HARNESS_FIXTURES)
def test_the_goldens_of_both_forms_are_one_file_and_are_this_output(case):
    written = (GOLDEN / f"{case}.cdm.json").read_text(encoding="utf-8")
    assert (GOLDEN / f"{case}.parsed.cdm.json").read_text(encoding="utf-8") == written
    assert canonical.serialise(dump(payload(case))) == written


def test_bytearray_and_memoryview_translate_like_bytes():
    raw = payload("snapshot_three_forces")
    expected = canonical.serialise(dump(raw))
    assert canonical.serialise(dump(bytearray(raw))) == expected
    assert canonical.serialise(dump(memoryview(raw))) == expected


def test_a_value_that_is_neither_form_is_refused_as_not_the_envelope():
    refused("not-an-any-envelope", "not a payload")
    refused("not-an-any-envelope", [message(force())])


# ================================================================= §4 message-level rules


def test_success_must_be_true_and_its_absence_reads_false():
    error = refused("response-not-successful",
                    message(force(), header={"success": False, "error_message": "EXERCISE no"}))
    assert "header.success is false" in str(error) and "'EXERCISE no'" in str(error)
    error = refused("response-not-successful", message(force(), header={}))
    assert "absent from the wire, which reads false" in str(error)
    error = refused("response-not-successful", {"@type": GET, "blue_forces": [force()]})
    assert "has no header" in str(error)
    # protoc's own payload: success absent from the wire (protoc writes no false), one element.
    refused("response-not-successful", (SET / "malformed/success_false.binpb").read_bytes())


def test_an_error_message_on_a_successful_response_is_carried_in_the_message_member():
    entity = only_entity(message(force(), header={"success": True,
                                                  "error_message": "EXERCISE degraded"}))
    assert entity["attributes"]["tacticalapi"]["message"]["header"] == {
        "success": True, "error_message": "EXERCISE degraded"}
    # awkward_zeros: an empty error message on the wire is present and empty.
    first = entities(dump(payload("awkward_zeros")))[0]
    assert first["attributes"]["tacticalapi"]["message"]["header"] == {
        "success": True, "error_message": ""}


def test_zero_blue_forces_and_nothing_unknown_is_an_empty_list():
    assert adapter().to_cdm(payload("cases/empty_successful_response")) == []
    assert adapter().to_cdm(twin_file("cases/empty_successful_response")) == []
    assert adapter().to_cdm(message(url=SUBSCRIBE)) == []


def test_zero_blue_forces_with_unknown_fields_is_refused_for_want_of_a_carrier():
    for raw in (payload("cases/unknown_fields_without_carrier"),
                twin_file("cases/unknown_fields_without_carrier"),
                message(futureField=1)):
        error = refused("unknown-fields-without-carrier", raw)
    assert "no blue force" in str(error)


def test_message_and_header_level_unknown_fields_are_carried_on_every_entity_and_event():
    objects = dump(payload("cases/unknown_field_carried"))
    first, second = entities(objects)
    # Every Event carries them too since 2026-10-06 (the record §5.9).
    for carrier in objects:
        response = carrier["residual"]["data"]["response"]
        assert response == {
            "header": {"@unknown": [{"number": 3, "wire_type": 0, "hex": "02"}]},
            "@unknown": [{"number": 3, "wire_type": 2,
                          "hex": "4558455243495345204e4f544520414c504841"}]}
    assert not [event for event in events(objects) if "blue_force" in event["residual"]["data"]]
    # An element's own unknown field is carried on that element's entity only.
    assert first["residual"]["data"]["blue_force"] == {
        "@unknown": [{"number": 11, "wire_type": 0, "hex": "01"}]}
    assert second["residual"]["data"]["blue_force"] == {
        "point_location": {"geo_point": {"@unknown": [{"number": 6, "wire_type": 0,
                                                        "hex": "03"}]}}}


def test_two_elements_with_one_identity_are_both_translated_in_order():
    objects = dump(payload("cases/duplicate_identity"))
    assert [obj["object_kind"] for obj in objects] == ["entity", "event", "entity", "event"]
    first, second = entities(objects)
    expected = str(ids.derive("TacticalAPI", "string_identity:EXERCISE-VEH-305", kind="entity"))
    assert first["entity_id"] == second["entity_id"] == expected
    assert (first["position"]["lat"], second["position"]["lat"]) == (57.205, 57.2071)
    assert (first["valid_from"], second["valid_from"]) == ("2026-09-29T07:05:00.000Z",
                                                           "2026-09-29T07:05:10.000Z")
    one, two = events(objects)
    assert one["event_id"] != two["event_id"]


def test_each_element_is_an_entity_followed_by_its_event_in_list_order():
    objects = dump(payload("snapshot_three_forces"))
    assert [obj["object_kind"] for obj in objects] == ["entity", "event"] * 3
    externals = ["uuid_identity:7e0789f0-8823-5bcb-b121-3278650b625b",
                 "string_identity:EXERCISE-VEH-201", "int32_identity:30517"]
    for index, external in enumerate(externals):
        entity, event = objects[2 * index], objects[2 * index + 1]
        assert entity["source_ids"] == event["source_ids"] == [
            {"system": "TacticalAPI", "external_id": external}]
        assert entity["source"]["record_index"] == event["source"]["record_index"] == index
        assert event["related_entities"] == [entity["entity_id"]]
        assert entity["attributes"]["tacticalapi"]["message"]["index"] == index


# ================================================================= §5.1 the typed block


@pytest.mark.parametrize("case", TRANSLATED)
def test_the_typed_block_is_the_element_as_the_twin_states_it(case):
    twin = twin_file(case)
    type_name = twin["@type"].rsplit("/", 1)[1]
    list_name = "blue_forces" if "blue_forces" in twin else "updated_blue_forces"
    for index, entity in enumerate(entities(dump(payload(case)))):
        block = entity["attributes"]["tacticalapi"]
        assert block["contract"] == "tacticalapi-blueforce/1"
        assert block["message"] == {"type": type_name, "type_url": twin["@type"],
                                    "list": list_name, "index": index,
                                    "header": {key: value for key, value in twin["header"].items()
                                               if key != "@unknown"}}
        element = twin[list_name][index]
        assert block["blue_force"] == codec.known_only(element, module.BLUE_FORCE)
        if "@unknown" not in json.dumps(element):
            assert block["blue_force"] == element


def test_every_block_model_carries_exactly_the_field_tables_fields_in_its_order():
    for message_name, model in codec.BLOCK_MODELS.items():
        table = [field.name for field in codec.MESSAGES[message_name].values()]
        assert list(model.model_fields) == table, message_name


def test_the_typed_block_model_refuses_an_extra_key_a_null_and_a_coerced_value():
    block = adapter().to_cdm(payload("snapshot_three_forces"))[0].attributes["tacticalapi"]
    assert codec.TypedBlock.model_validate(block).model_dump(mode="json",
                                                              exclude_unset=True) == block
    for broken in (
        {**block, "extra": 1},
        {**block, "blue_force": {**block["blue_force"], "callsign": None}},
        {**block, "blue_force": {**block["blue_force"], "own_blue_force": 1}},
        {**block, "blue_force": {**block["blue_force"], "identity": {"int64_identity": 7}}},
        {**block, "blue_force": {**block["blue_force"], "last_contact_time": "2026-09-29"}},
        {**block, "contract": "tacticalapi-blueforce/2"},
    ):
        with pytest.raises(ValueError):
            codec.TypedBlock.model_validate(broken)


def test_every_basis_is_a_top_level_key_of_the_attributes_or_the_payload():
    objects = dump(payload("snapshot_three_forces"))
    assert set(objects[0]["attributes"]) == {
        "tacticalapi", "entity_id_basis", "valid_from_basis", "affiliation_basis",
        "entity_type_basis", "symbol_basis", "position_basis", "position_source_basis"}
    assert set(objects[1]["payload"]) == {"contract", "observed_at_basis", "event_id_basis",
                                          "severity_basis"}
    # No position, no position_source to explain.
    deleted = entities(dump(payload("delta_with_deletion")))[1]
    assert "position_source_basis" not in deleted["attributes"]
    # A course stated, a course_basis written (R5, 2026-10-06); the first element states none.
    assert set(objects[2]["attributes"]) == set(objects[0]["attributes"]) | {"course_basis"}


# ====================================================================== §5.2 identity


@pytest.mark.parametrize("identity,external", [
    ({"uuid_identity": "7e0789f0-8823-5bcb-b121-3278650b625b"},
     "uuid_identity:7e0789f0-8823-5bcb-b121-3278650b625b"),
    ({"string_identity": "EXERCISE-7"}, "string_identity:EXERCISE-7"),
    ({"int32_identity": -7}, "int32_identity:-7"),
    ({"int32_identity": 0}, "int32_identity:0"),
    ({"int64_identity": "9007199254740993"}, "int64_identity:9007199254740993"),
])
def test_the_identity_member_and_value_key_the_entity(identity, external):
    objects = dump(message(force(identity=identity)))
    entity, event = objects
    assert entity["source_ids"] == [{"system": "TacticalAPI", "external_id": external}]
    assert entity["entity_id"] == str(ids.derive("TacticalAPI", external, kind="entity"))
    member = next(iter(identity))
    assert entity["attributes"]["entity_id_basis"].startswith(f"identity.{member}:")
    assert event["related_entities"] == [entity["entity_id"]]


def test_the_text_7_and_the_integer_7_stay_two_identities():
    text = only_entity(message(force(identity={"string_identity": "7"})))
    number = only_entity(message(force(identity={"int32_identity": 7})))
    wide = only_entity(message(force(identity={"int64_identity": "7"})))
    assert len({text["entity_id"], number["entity_id"], wide["entity_id"]}) == 3


def test_a_blue_force_without_identity_or_with_no_member_set_is_refused():
    error = refused("blue-force-without-identity", message({"callsign": "EXERCISE X"}))
    assert "blue_forces[0] has no identity" in str(error)
    error = refused("blue-force-without-identity", message(force(), force(identity={})))
    assert "blue_forces[1].identity sets no member" in str(error)
    refused("blue-force-without-identity", message(force(identity={"futureMember": "x"})))
    refused("blue-force-without-identity",
            (SET / "malformed/blue_force_without_identity.binpb").read_bytes())


@pytest.mark.parametrize("member", ["uuid_identity", "string_identity"])
def test_a_string_member_holding_the_empty_string_is_refused(member):
    error = refused("empty-identity", message(force(identity={member: ""})))
    assert f"blue_forces[0].identity.{member} is the empty string" in str(error)


def test_mount_host_and_the_organisation_unit_are_typed_block_only():
    objects = dump(payload("snapshot_three_forces"))
    first, _, third = entities(objects)
    assert first["attributes"]["tacticalapi"]["blue_force"][
        "associated_organization_unit_identity"] == {"string_identity": "EXERCISE-BN-3"}
    assert third["attributes"]["tacticalapi"]["blue_force"]["mount_host"] == {
        "string_identity": "EXERCISE-VEH-201"}
    # No entity id is derived for either: the only identifiers are the three elements' own.
    externals = ["uuid_identity:7e0789f0-8823-5bcb-b121-3278650b625b",
                 "string_identity:EXERCISE-VEH-201", "int32_identity:30517"]
    entity_ids = [obj["entity_id"] for obj in entities(objects)]
    assert entity_ids == [str(ids.derive("TacticalAPI", external, kind="entity"))
                          for external in externals]
    organisation_unit = str(ids.derive("TacticalAPI", "string_identity:EXERCISE-BN-3",
                                       kind="entity"))
    assert organisation_unit not in json.dumps(objects)
    # The host is element 1, keyed by its own identity; the mounted element's objects never
    # name the host's id, because no relation is derived from mount_host.
    assert entity_ids[1] not in json.dumps(objects[4:6])


# ========================================================================== §5.3 time


def test_the_location_time_is_the_first_choice():
    entity, event = dump(payload("snapshot_three_forces"))[4:6]
    # location_time 05:59:19, last_contact_time 05:59:20.500: the location time wins.
    assert entity["valid_from"] == event["observed_at"] == "2026-09-29T05:59:19.000Z"
    assert entity["attributes"]["valid_from_basis"] == "point_location.location_time"
    assert event["payload"]["observed_at_basis"] == "point_location.location_time"


def test_the_last_contact_time_is_used_when_the_location_time_is_absent():
    entity, event = dump(payload("delta_with_deletion"))[2:4]
    assert entity["valid_from"] == event["observed_at"] == "2026-09-29T06:14:30.000Z"
    assert entity["attributes"]["valid_from_basis"] == (
        "last_contact_time: point_location.location_time is absent")
    assert event["payload"]["observed_at_basis"] == entity["attributes"]["valid_from_basis"]


def test_with_no_source_time_the_injected_clock_stands_in_and_the_basis_says_so():
    """The record §5.3's third row, for a deleted element (the case file) and a live one."""
    for raw in (payload("cases/deleted_without_timestamps"),
                message(force(point_location={"geo_point": {"latitude_coordinate": 57.0}}))):
        for clock_at in (FROZEN, OTHER):
            entity, event = dump(raw, clock_at)
            stamp = times.render(clock_at)
            assert entity["valid_from"] == event["observed_at"] == event["received_at"] == stamp
            assert entity["attributes"]["valid_from_basis"] == module.NO_TIME_BASIS
            assert event["payload"]["observed_at_basis"] == module.NO_TIME_BASIS
            assert "receipt instant" in module.NO_TIME_BASIS
            assert "injected clock" in module.NO_TIME_BASIS


def test_received_at_is_the_injected_clock_read_once_per_message():
    calls: list[int] = []

    def clock() -> dt.datetime:
        calls.append(1)
        return OTHER
    raw = payload("snapshot_three_forces")
    objects = harness._dump(TacticalapiAdapter(clock=clock).to_cdm(raw))
    assert calls == [1]
    assert {event["received_at"] for event in events(objects)} == {"2027-01-02T03:04:05.678Z"}


def test_instants_render_to_the_millisecond_and_the_text_stays_whole():
    entity = entities(dump(payload("snapshot_three_forces")))[1]
    assert entity["valid_from"] == "2026-09-29T06:00:01.987Z"
    assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"][
        "location_time"] == "2026-09-29T06:00:01.987654321Z"
    zeros = entities(dump(payload("awkward_zeros")))[0]
    assert zeros["valid_from"] == "2026-09-29T06:29:59.000Z"
    assert zeros["attributes"]["tacticalapi"]["blue_force"]["point_location"][
        "location_time"] == "2026-09-29T06:29:59.000000001Z"


# ============================================================ §5.4 affiliation, type, symbol


#: The record §5.4, R3 as ruled 2026-10-06: the default affiliation's basis, written out here.
UNKNOWN_BASIS = (
    "UNKNOWN: the message carries no affiliation field. The BlueForceTracking service's own "
    "definition names the members of this list blue forces, which is a statement about the "
    "service and not a field of the message, so the adapter asserts no affiliation from it or "
    "from the deployment context a message arrives in; nothing is read from a symbol code. A "
    "caller that knows the affiliation supplies it: TacticalapiAdapter(affiliation=...) (R3, "
    "ruled 2026-10-06)")


def supplied_basis(member: str) -> str:
    return (f"{member}: supplied by the caller, TacticalapiAdapter(affiliation=Affiliation."
            f"{member}); the message carries no affiliation field, and the adapter asserts none "
            "of its own and compares the supplied one with nothing in the message, a symbol code "
            "included (R3, ruled 2026-10-06)")


@pytest.mark.parametrize("case", TRANSLATED)
def test_affiliation_is_unknown_on_every_entity_by_default_and_never_read_from_a_symbol(case):
    """R3, ruled 2026-10-06 (FRIENDLY before): the message carries no affiliation field, and the
    adapter asserts none from the service's definition or from deployment context."""
    for raw in (payload(case), twin_file(case)):
        for entity in entities(dump(raw)):
            assert entity["affiliation"] == "UNKNOWN"
            assert entity["attributes"]["affiliation_basis"] == UNKNOWN_BASIS
    assert module.AFFILIATION_BASIS == UNKNOWN_BASIS


@pytest.mark.parametrize("member", list(Affiliation), ids=[member.name for member in Affiliation])
@pytest.mark.parametrize("case", TRANSLATED)
def test_an_affiliation_the_caller_supplies_is_on_every_entity_with_its_basis(case, member):
    """R3: each of the four members, supplied at construction, is every Entity's affiliation,
    with a basis saying the caller supplied it, in both forms. Nothing else of the output moves:
    the objects equal the default's once the affiliation and its basis are set aside."""
    for raw in (payload(case), twin_file(case)):
        supplied = harness._dump(TacticalapiAdapter(clock=times.frozen_clock(FROZEN),
                                                    affiliation=member).to_cdm(raw))
        default = dump(raw)
        for entity in entities(supplied):
            assert entity["affiliation"] == member.value
            assert entity["attributes"]["affiliation_basis"] == supplied_basis(member.name)
        for obj in (*entities(supplied), *entities(default)):
            del obj["affiliation"], obj["attributes"]["affiliation_basis"]
        assert supplied == default


def test_a_supplied_affiliation_is_compared_with_no_symbol():
    """R3: adapters do not judge. A caller's FRIENDLY or HOSTILE beside a 2525D code whose
    standard-identity digit is 2 (awkward_symbols_and_codes) stands as supplied, and
    validate_source says what it says with no caller affiliation: the digit observation is
    against the service's own definition, not against Entity.affiliation."""
    raw = payload("awkward_symbols_and_codes")
    lines = adapter().validate_source(raw)
    for member in (Affiliation.FRIENDLY, Affiliation.HOSTILE):
        probe = TacticalapiAdapter(clock=times.frozen_clock(FROZEN), affiliation=member)
        entity = entities(harness._dump(probe.to_cdm(raw)))[2]
        assert entity["symbol"][3] == "2" and entity["affiliation"] == member.value
        assert probe.validate_source(raw) == lines


class TextAffiliation(str):
    """A `str` subclass holding a member's text: still not the member."""


@pytest.mark.parametrize("value", [
    "FRIENDLY", "UNKNOWN", "friendly", TextAffiliation("HOSTILE"), "", 0, 1, True, False, 3.5,
    b"FRIENDLY", ["FRIENDLY"], {"affiliation": "FRIENDLY"}, (Affiliation.FRIENDLY,),
    Affiliation, EventType.TRACK_UPDATE, object(), "F" * 100_000, "EXERCISE\nFRIENDLY",
], ids=lambda value: type(value).__name__)
def test_an_affiliation_that_is_not_an_affiliation_member_is_refused_at_construction(value):
    """R3: anything but one of the four members (or None) is refused when the adapter is
    built — a ValueError whose text begins with its reason code, one bounded printable line —
    and not as a TacticalapiRefused, which names an input. Nothing is converted, a text that
    spells a member included."""
    with pytest.raises(ValueError) as caught:
        TacticalapiAdapter(affiliation=value)
    assert not isinstance(caught.value, TacticalapiRefused)
    text = str(caught.value)
    assert text.startswith("invalid-affiliation: the affiliation a caller supplies is one of the "
                           "four Affiliation members (FRIENDLY, HOSTILE, NEUTRAL, UNKNOWN) or "
                           "None, and ")
    assert text.endswith(", is neither; a text that spells a member is not the member, and "
                         "nothing is converted")
    assert text.isprintable() and "\n" not in text and len(text) < 600
    assert module.INVALID_AFFILIATION == "invalid-affiliation"
    assert module.INVALID_AFFILIATION not in codec.REASON_CODES


def test_no_affiliation_and_none_build_the_default():
    for probe in (TacticalapiAdapter(), TacticalapiAdapter(affiliation=None),
                  TacticalapiAdapter.fixture_instance()):
        assert probe._affiliation_of_every_entity() == (Affiliation.UNKNOWN, UNKNOWN_BASIS)


def test_the_affiliation_is_keyword_only():
    """R3 (§6): `TacticalapiAdapter(clock=None, *, synthetic=True, affiliation=None)`, as
    c2sim's `own_side` is; a member in the second or third position is a TypeError, not a
    silently accepted `synthetic`."""
    with pytest.raises(TypeError):
        TacticalapiAdapter(times.frozen_clock(FROZEN), Affiliation.HOSTILE)
    with pytest.raises(TypeError):
        TacticalapiAdapter(times.frozen_clock(FROZEN), True, Affiliation.HOSTILE)


def test_synthetic_false_still_reaches_the_base_class_beside_a_supplied_affiliation():
    """R3: the new `__init__` forwards `synthetic` unchanged; with `synthetic=False` every
    emitted object says so, with and without a caller affiliation."""
    raw = payload("snapshot_three_forces")
    for member in (None, Affiliation.HOSTILE):
        probe = TacticalapiAdapter(clock=times.frozen_clock(FROZEN), synthetic=False,
                                   affiliation=member)
        objects = harness._dump(probe.to_cdm(raw))
        assert objects and all(obj["source"]["synthetic"] is False for obj in objects)
        expected = (member or Affiliation.UNKNOWN).value
        assert {entity["affiliation"] for entity in entities(objects)} == {expected}
    assert all(obj["source"]["synthetic"] is True for obj in dump(raw))


@pytest.mark.parametrize("case", HARNESS_FIXTURES)
def test_the_goldens_are_what_fixture_instance_replays_with_no_caller_affiliation(case):
    """R3: `fixture_instance` is not overridden, so the harness, the suite and the evidence
    generator replay the packaged fixtures with no caller affiliation, and the goldens hold
    UNKNOWN; they are byte for byte what that instance writes, from both forms."""
    assert "fixture_instance" not in TacticalapiAdapter.__dict__
    probe = TacticalapiAdapter.fixture_instance(clock=times.frozen_clock(FROZEN))
    written = (GOLDEN / f"{case}.cdm.json").read_text(encoding="utf-8")
    for raw in (payload(case), twin_file(case)):
        assert canonical.serialise(harness._dump(probe.to_cdm(raw))) == written
    golden = json.loads(written)
    assert {obj["affiliation"] for obj in golden if obj["object_kind"] == "entity"} == {"UNKNOWN"}
    assert "FRIENDLY" not in written


@pytest.mark.parametrize("flags,expected,said", [
    ({"is_vehicle": True}, "PLATFORM", "PLATFORM: blue_force_type.is_vehicle true"),
    ({"is_unmanned": True}, "PLATFORM", "PLATFORM: blue_force_type.is_unmanned true"),
    ({"is_vehicle": True, "is_unmanned": True}, "PLATFORM",
     "PLATFORM: blue_force_type.is_vehicle and is_unmanned true"),
    ({"is_leader": True}, "UNKNOWN", "UNKNOWN: blue_force_type sets neither"),
    ({"is_vehicle": False, "is_unmanned": False}, "UNKNOWN",
     "UNKNOWN: blue_force_type sets neither"),
    ({}, "UNKNOWN", "UNKNOWN: blue_force_type sets neither"),
    (None, "UNKNOWN", "UNKNOWN: the element has no blue_force_type"),
])
def test_entity_type_is_platform_only_for_a_vehicle_or_an_unmanned_flag(flags, expected, said):
    element = force() if flags is None else force(blue_force_type=flags)
    entity = only_entity(message(element))
    assert entity["entity_type"] == expected
    assert entity["attributes"]["entity_type_basis"].startswith(said)


def test_a_2525d_numeric_code_becomes_the_symbol_unrewritten():
    entity = entities(dump(payload("snapshot_three_forces")))[0]
    assert entity["symbol"] == "10131000151211000000"
    assert entity["attributes"]["symbol_basis"].startswith(
        "symbol.numeric_identifier with symbol_catalog SYMBOL_CATALOG_MIL2525_D")


def test_an_absent_second_set_is_the_valid_value_zero():
    entity = only_entity(payload("cases/d_code_second_set_zero"))
    assert entity["symbol"] == "1013100015" + "0000000000"
    assert "second_ten_digits is absent from the wire and reads 0" in \
        entity["attributes"]["symbol_basis"]


def numeric(first: str | None, second: str | None) -> dict:
    out = {}
    if first is not None:
        out["first_ten_digits"] = first
    if second is not None:
        out["second_ten_digits"] = second
    return out


@pytest.mark.parametrize("symbol,said", [
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_C", "string_identifier": "SFGPEVC--------"},
     "symbol_catalog SYMBOL_CATALOG_MIL2525_C"),
    ({"symbol_catalog": "SYMBOL_CATALOG_APP6_D",
      "numeric_identifier": numeric("1013100015", "1211000000")},
     "symbol_catalog SYMBOL_CATALOG_APP6_D"),
    ({"symbol_catalog": "SYMBOL_CATALOG_RME", "string_identifier": "EXERCISE-RME-SYMBOL-77"},
     "symbol_catalog SYMBOL_CATALOG_RME"),
    ({"numeric_identifier": numeric("1013100015", "1211000000")},
     "symbol_catalog is absent from the wire"),
    ({"symbol_catalog": 9, "numeric_identifier": numeric("1013100015", "1211000000")},
     "symbol_catalog 9"),
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D", "string_identifier": "10131000151211000000"},
     "in the string form"),
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D", "numeric_identifier": numeric(None, "1")},
     "first_ten_digits is 0"),
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D", "numeric_identifier": numeric("0", "1")},
     "first_ten_digits is 0"),
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
      "numeric_identifier": numeric("999999999", "0")},
     "first_ten_digits is 999999999"),
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
      "numeric_identifier": numeric("10000000000", "0")}, "first_ten_digits is 10000000000"),
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
      "numeric_identifier": numeric("1013100015", "10000000000")},
     "second_ten_digits is 10000000000"),
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
      "numeric_identifier": numeric("1013100015", "-1")}, "second_ten_digits is -1"),
    # Neither identifier on the wire (2026-10-04, final verification, item 25): the basis said
    # "in the string form" for a symbol that holds no string.
    ({"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D"},
     "symbol_catalog SYMBOL_CATALOG_MIL2525_D and no identifier: the symbol sets neither "
     "string_identifier nor numeric_identifier"),
])
def test_every_other_symbol_is_carried_and_not_promoted(symbol, said):
    entity = only_entity(message(force(symbol=symbol)))
    assert entity["symbol"] is None
    basis = entity["attributes"]["symbol_basis"]
    assert basis.startswith("not promoted: ") and said in basis
    assert entity["attributes"]["tacticalapi"]["blue_force"]["symbol"] == symbol


def test_the_bounds_of_the_two_sets_are_promoted():
    low = only_entity(message(force(symbol={"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
                                            "numeric_identifier": numeric("1000000000", "0")})))
    high = only_entity(message(force(symbol={"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
                                             "numeric_identifier": numeric("9999999999",
                                                                           "9999999999")})))
    assert low["symbol"] == "10000000000000000000"
    assert high["symbol"] == "99999999999999999999"


def test_no_symbol_is_derived_when_the_element_states_none():
    entity = only_entity(message(force()))
    assert entity["symbol"] is None
    assert entity["attributes"]["symbol_basis"] == (
        "no symbol: the element states none, and none is derived from the affiliation "
        "(R4, ruled 2026-10-06)")


def test_a_promoted_symbol_with_another_identity_digit_is_carried_unchanged():
    entity = entities(dump(payload("awkward_symbols_and_codes")))[2]
    assert entity["symbol"] == "10121000151211000000"
    assert entity["symbol"][3] == "2"
    # UNKNOWN since 2026-10-06 (R3), and never read from the symbol.
    assert entity["affiliation"] == "UNKNOWN"


# ======================================================================= §5.5 position


def test_the_coordinates_are_the_position_and_the_event_geometry():
    entity, event = dump(payload("snapshot_three_forces"))[0:2]
    assert (entity["position"]["lat"], entity["position"]["lon"]) == (57.2154, 20.8732)
    assert event["geometry"] == {"type": "Point", "coordinates": [20.8732, 57.2154]}
    assert entity["attributes"]["position_basis"] == (
        "point_location.geo_point latitude_coordinate and longitude_coordinate, read as WGS 84 "
        "decimal degrees: the contract states the ellipsoid and no angular unit (limitation "
        "coordinate-unit-not-stated)")


def test_a_coordinate_absent_from_the_wire_reads_zero_and_the_basis_says_so():
    # The first element's two objects: awkward_zeros gained a second element on 2026-10-04
    # (final verification, a zero location_time), which this test does not read.
    entity, event = dump(payload("awkward_zeros"))[:2]
    assert (entity["position"]["lat"], entity["position"]["lon"]) == (0.0, 9.25)
    assert event["geometry"]["coordinates"] == [9.25, 0.0]
    assert entity["attributes"]["position_basis"].endswith(
        "; latitude_coordinate is absent from the wire and reads 0.0, proto3's default "
        "(limitation proto3-zero-indistinguishable)")
    lon_absent = only_entity(message(force(point_location=at(lat=-33.5, lon=None))))
    assert (lon_absent["position"]["lat"], lon_absent["position"]["lon"]) == (-33.5, 0.0)
    assert "longitude_coordinate is absent from the wire and reads 0.0" in \
        lon_absent["attributes"]["position_basis"]


def test_no_position_without_a_coordinate_on_the_wire():
    for raw, said in (
        (payload("cases/empty_geo_point"),
         "no position: point_location.geo_point carries neither latitude_coordinate nor "
         "longitude_coordinate on the wire"),
        (message(force(point_location={"geo_point": {"vertical_distance": 12.0,
                                                     "measurement_code": "MEASUREMENT_CODE_GPS"}})),
         "no position: point_location.geo_point carries neither"),
        (message(force(point_location={"location_time": "2026-09-29T07:00:00Z"})),
         "no position: point_location has no geo_point"),
        (message(force(point_location={})), "no position: point_location has no geo_point"),
        (message(force()), "no position: the element has no point_location"),
    ):
        entity, event = dump(raw)
        assert entity["position"] is None and event["geometry"] is None
        assert entity["attributes"]["position_basis"].startswith(said)
        assert "position_source_basis" not in entity["attributes"]


@pytest.mark.parametrize("lat,lon", [(90.0, 0.5), (-90.0, 0.5), (0.5, 180.0), (0.5, -180.0)])
def test_coordinates_at_their_bounds_are_accepted(lat, lon):
    entity = only_entity(message(force(point_location=at(lat, lon))))
    assert (entity["position"]["lat"], entity["position"]["lon"]) == (lat, lon)


@pytest.mark.parametrize("lat,lon,said", [
    (90.000001, 0.5, "latitude_coordinate is 90.000001"),
    (-91.0, 0.5, "latitude_coordinate is -91.0"),
    (0.5, 180.5, "longitude_coordinate is 180.5"),
    (0.5, -181.0, "longitude_coordinate is -181.0"),
])
def test_coordinates_out_of_range_are_refused(lat, lon, said):
    raw = message(force(point_location=at(lat, lon)))
    assert said in str(refused("coordinate-out-of-range", raw))


def test_protocs_latitude_91_is_refused():
    error = refused("coordinate-out-of-range", (SET / "malformed/latitude_91.binpb").read_bytes())
    assert "latitude_coordinate is 91.0" in str(error)


#: The record §5.5's vertical reference table, restated by contract value name.
VERTICAL = [
    ("VERTICAL_DISTANCE_REFERENCE_CODE_UNSPECIFIED", "UNKNOWN"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_UNKNOWN", "UNKNOWN"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_CHART_DATUM", "UNKNOWN"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_LOCAL_DATUM", "UNKNOWN"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_MEAN_SEA_LEVEL", "MSL"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_PRESSURE_DATUM_QFE", "BARO"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_PRESSURE_DATUM_QNH", "BARO"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_PRESSURE_DATUM_STANDARD_ATMOSPHERE", "BARO"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_TOPOGRAPHIC_SURFACE", "AGL"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_WATER_BOTTOM", "UNKNOWN"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_GEOID", "MSL"),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID", "HAE"),
]


@pytest.mark.parametrize("code,reference", VERTICAL + [(12, "UNKNOWN"), (-3, "UNKNOWN"),
                                                       (None, "UNKNOWN")])
def test_each_vertical_reference_code(code, reference):
    geo = {"vertical_distance": 123.25}
    if code is not None:
        geo["vertical_distance_reference_code"] = code
    position = only_entity(message(force(point_location=at(**geo))))["position"]
    assert position["vertical"] == {"value": 123.25, "unit": "m", "reference": reference,
                                    "uncertainty": None}
    assert position["alt_m"] == (123.25 if reference == "HAE" else None)


def test_the_vertical_table_covers_all_twelve_named_codes():
    assert [name for name, _ in VERTICAL] == [
        codec.ENUMS[module.VERTICAL_CODES][number] for number in range(12)]


def test_no_vertical_distance_means_no_vertical_whatever_the_code_says():
    geo = {"vertical_distance_reference_code":
           "VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID"}
    position = only_entity(message(force(point_location=at(**geo))))["position"]
    assert position["vertical"] is None and position["alt_m"] is None


def test_a_zero_height_on_the_wire_is_a_real_zero():
    position = entities(dump(payload("awkward_zeros")))[0]["position"]
    assert position["vertical"] == {"value": 0.0, "unit": "m", "reference": "AGL",
                                    "uncertainty": None}


@pytest.mark.parametrize("code,source,said", [
    ("MEASUREMENT_CODE_GPS", "GNSS", "GNSS: geo_point.measurement_code MEASUREMENT_CODE_GPS (2)"),
    ("MEASUREMENT_CODE_INS", "INERTIAL",
     "INERTIAL: geo_point.measurement_code MEASUREMENT_CODE_INS (3)"),
    ("MEASUREMENT_CODE_ESTIMATE", "MANUAL",
     "MANUAL: geo_point.measurement_code MEASUREMENT_CODE_ESTIMATE (4)"),
    ("MEASUREMENT_CODE_UNSPECIFIED", "ESTIMATED",
     "ESTIMATED: geo_point.measurement_code MEASUREMENT_CODE_UNSPECIFIED (0)"),
    ("MEASUREMENT_CODE_UNKNOWN", "ESTIMATED",
     "ESTIMATED: geo_point.measurement_code MEASUREMENT_CODE_UNKNOWN (1)"),
    ("MEASUREMENT_CODE_LRS", "ESTIMATED",
     "ESTIMATED: geo_point.measurement_code MEASUREMENT_CODE_LRS (5)"),
    (7, "ESTIMATED",
     "ESTIMATED: geo_point.measurement_code 7, a number the contract does not name"),
    (None, "ESTIMATED",
     "ESTIMATED: geo_point.measurement_code is absent from the wire and reads 0"),
])
def test_each_measurement_code(code, source, said):
    geo = {} if code is None else {"measurement_code": code}
    entity = only_entity(message(force(point_location=at(**geo))))
    assert entity["position"]["position_source"] == source
    basis = entity["attributes"]["position_source_basis"]
    assert basis.startswith(said)
    assert ("the understating ESTIMATED stands" in basis) == (source == "ESTIMATED")


# ===================================================================== §5.6 kinematics


def test_speed_is_metres_per_second_as_stated_and_a_present_zero_is_a_real_zero():
    # The course beside each speed is mapped since 2026-10-06 (R5); a present course of 0 is a
    # real course due north, as a present speed of 0 is real stillness.
    moving = entities(dump(payload("snapshot_three_forces")))[1]
    assert moving["kinematics"] == {"speed_mps": 8.75, "course_deg": 247.5, "climb_mps": None}
    still = entities(dump(payload("awkward_zeros")))[0]
    assert still["kinematics"] == {"speed_mps": 0.0, "course_deg": 0.0, "climb_mps": None}


@pytest.mark.parametrize("speed", [-0.5, -1e-9])
def test_a_negative_speed_is_refused(speed):
    point = {**at(), "speed": speed}
    error = refused("negative-speed", message(force(point_location=point)))
    assert f"speed is {speed!r}" in str(error)


#: The record §5.6 (R5, ruled 2026-10-06): the basis of a mapped course, written out here.
ASSUMED_TRUE = (
    "point_location.course in degrees as stated, read as degrees true: the contract states "
    "degrees and no north reference, so the north reference is ASSUMED true, which "
    "Kinematics.course_deg means (limitation course-reference-not-stated; R5, ruled 2026-10-06)")
#: What a basis and validate_source say of a course outside [0, 360), after the value.
NOT_MAPPED = (
    "outside [0, 360), the range Kinematics.course_deg holds, so it is not mapped and course_deg "
    "stays None; nothing normalises it (no modulo, no clamping), and the value stays in the "
    "typed block")


def course_payload(course: float, speed: float | None = None) -> bytes:
    """One element keyed `int32_identity: 5` whose point states `course` (and `speed`), as
    bytes: header (field 1) success, blue_forces (field 2) > identity (1) > int32_identity (3);
    point_location (7) > course (4) and speed (5), each a DoubleValue whose value is field 1."""
    point = pw.field_len(4, pw.field_double(1, course))
    if speed is not None:
        point += pw.field_len(5, pw.field_double(1, speed))
    element = pw.field_len(1, pw.field_varint(3, 5)) + pw.field_len(7, point)
    return pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element))


def course_twin(course, speed: float | None = None) -> dict:
    point = {"course": course} if speed is None else {"course": course, "speed": speed}
    return message(force(identity={"int32_identity": 5}, point_location=point))


@pytest.mark.parametrize("case,index,course", [
    ("snapshot_three_forces", 1, 247.5), ("delta_with_deletion", 0, 12.5),
    ("awkward_zeros", 0, 0.0)])
def test_a_course_in_range_is_course_deg_as_degrees_true_with_the_assumption_stated(
        case, index, course):
    """R5 (2026-10-06): every fixture course in [0, 360) is `course_deg` as stated, the typed
    block keeps it, and the basis on the Entity says the north reference is ASSUMED true."""
    for raw in (payload(case), twin_file(case)):
        entity = entities(dump(raw))[index]
        assert entity["kinematics"]["course_deg"] == course
        assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"][
            "course"] == course
        assert entity["attributes"]["course_basis"] == ASSUMED_TRUE == module.COURSE_ASSUMED_TRUE


@pytest.mark.parametrize("course", [0.0, 0.25, 180.0, 359.75, 359.99999999999994])
@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_course_at_or_inside_the_bounds_is_mapped(form, course):
    raw = course_payload(course) if form == "bytes" else course_twin(course)
    entity = only_entity(raw)
    assert entity["kinematics"] == {"speed_mps": None, "course_deg": course, "climb_mps": None}
    assert entity["attributes"]["course_basis"] == ASSUMED_TRUE


@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_course_with_no_speed_is_kinematics_of_its_own(form):
    """The record §5.6 as ruled 2026-10-06 (R5): kinematics exists when the speed or a mapped
    course is present. Until then a point stating a course and no speed had no kinematics."""
    raw = course_payload(90.0) if form == "bytes" else course_twin(90.0)
    entity = only_entity(raw)
    assert entity["kinematics"] == {"speed_mps": None, "course_deg": 90.0, "climb_mps": None}
    assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"] == {"course": 90.0}


def test_the_fixtures_course_of_360_is_not_mapped_and_is_reported():
    """awkward_zeros' second element (added 2026-10-06, R5): the full turn is outside [0, 360),
    so nothing maps it and nothing turns it to 0; with no speed there is no kinematics."""
    for raw in (payload("awkward_zeros"), twin_file("awkward_zeros")):
        entity = entities(dump(raw))[1]
        assert entity["kinematics"] is None
        assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"][
            "course"] == 360.0
        assert entity["attributes"]["course_basis"] == (
            f"point_location.course is 360.0, {NOT_MAPPED}; validate_source names it (R5, "
            "ruled 2026-10-06)")
        assert (f"blue_forces[1].point_location.course is 360.0, {NOT_MAPPED}"
                in adapter().validate_source(raw))


@pytest.mark.parametrize("course", [360.0, 360.5, 720.0, 1e308, -1e-300, -0.5, -90.0, -360.0,
                                    -1e308])
@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_course_of_360_or_more_or_a_negative_one_is_not_mapped_and_is_reported(form, course):
    """R5: 360, a negative and anything past 360 are not mapped (`course_deg` stays None), not
    normalised (no modulo, no clamping), stay in the typed block, and `validate_source` names
    each by its path. Beside a speed, kinematics holds the speed alone."""
    raw = course_payload(course, 3.5) if form == "bytes" else course_twin(course, 3.5)
    entity = only_entity(raw)
    assert entity["kinematics"] == {"speed_mps": 3.5, "course_deg": None, "climb_mps": None}
    assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"] == {
        "course": course, "speed": 3.5}
    assert entity["attributes"]["course_basis"] == (
        f"point_location.course is {course!r}, {NOT_MAPPED}; validate_source names it (R5, "
        "ruled 2026-10-06)")
    assert adapter().validate_source(raw) == [
        "blue_forces[0]: states no source time; valid_from and observed_at are the receipt "
        "instant from the injected clock",
        f"blue_forces[0].point_location.course is {course!r}, {NOT_MAPPED}"]
    alone = only_entity(course_payload(course) if form == "bytes" else course_twin(course))
    assert alone["kinematics"] is None and "course_basis" in alone["attributes"]


@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_negative_zero_course_compares_equal_to_zero_and_is_mapped_as_stated(form):
    """-0.0 is not below 0 ([0, 360) holds it, as the host's `ge=0.0` does), and nothing
    normalises a value, so it is mapped as stated, as a speed of -0.0 is."""
    raw = course_payload(-0.0) if form == "bytes" else course_twin(-0.0)
    entity = only_entity(raw)
    assert entity["kinematics"]["course_deg"] == 0.0
    assert str(entity["kinematics"]["course_deg"]) == "-0.0"
    assert entity["attributes"]["course_basis"] == ASSUMED_TRUE
    assert adapter().validate_source(raw) == [
        "blue_forces[0]: states no source time; valid_from and observed_at are the receipt "
        "instant from the injected clock"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_non_finite_course_is_refused_by_the_codec_before_the_course_rule(form, value):
    """The record §3.2: the codec refuses a NaN or an infinity in any double the table names,
    the course's DoubleValue included, in both forms, so R5's range rule never meets one and adds
    no second rule for it."""
    raw = course_payload(value) if form == "bytes" else course_twin(value)
    refused("non-finite-number", raw)
    [line] = adapter().validate_source(raw)
    assert line.startswith("TacticalapiRefused: non-finite-number: ")


def test_neither_speed_nor_course_is_no_kinematics():
    entity = entities(dump(payload("snapshot_three_forces")))[0]
    assert entity["kinematics"] is None and "course_basis" not in entity["attributes"]


# ======================================================================= §5.7 deletion


def test_a_deleted_element_is_a_status_and_a_status_change_with_no_valid_to():
    entity, event = dump(payload("delta_with_deletion"))[2:4]
    assert entity["status"] == {"state": "is_deleted", "namespace": "TacticalAPI", "since": None,
                                "attributes": {}}
    assert entity["valid_to"] is None
    assert event["event_type"] == "STATUS_CHANGE"
    # The deleted blue force is the snapshot's EXERCISE-VEH-201: one identity, one entity id.
    assert entity["entity_id"] == entities(dump(payload("snapshot_three_forces")))[1]["entity_id"]


def test_an_element_that_is_not_deleted_is_a_track_update_with_no_status():
    for element in (force(), force(is_deleted=False)):
        entity, event = dump(message(element))
        assert entity["status"] is None and event["event_type"] == "TRACK_UPDATE"


def test_a_deleted_element_with_no_timestamps_is_translated_like_any_other():
    entity, event = dump(payload("cases/deleted_without_timestamps"), OTHER)
    assert entity["status"]["state"] == "is_deleted" and event["event_type"] == "STATUS_CHANGE"
    assert entity["valid_from"] == event["observed_at"] == times.render(OTHER)
    assert entity["source_ids"][0]["external_id"] == \
        "uuid_identity:af3012b2-9c6e-5748-961b-48f15a82528b"


# ========================================================================== §5.8 event


@pytest.mark.parametrize("case", TRANSLATED)
def test_the_event_of_every_element(case):
    objects = dump(payload(case))
    for entity, event in zip(objects[0::2], objects[1::2]):
        external = entity["source_ids"][0]["external_id"]
        member = external.split(':', 1)[0]
        # The record §5.8 as changed 2026-10-04 (final verification, item 15): a deleted
        # element's id input ends `#is_deleted`, and its basis names the suffix; a live one's is
        # as it was.
        if entity["status"] is not None:
            assert entity["status"]["state"] == "is_deleted"
            expected_input = f"{external}@{event['observed_at']}#is_deleted"
            expected_basis = (f"identity.{member} + observed_at as rendered + #is_deleted: the "
                              "deletion report of one blue force at one instant, kept apart "
                              "from a live report at that instant")
        else:
            expected_input = f"{external}@{event['observed_at']}"
            expected_basis = (f"identity.{member} + observed_at as rendered: one report of one "
                              "blue force at one instant")
        assert event["event_id"] == str(ids.derive("TacticalAPI", expected_input, kind="event"))
        assert event["severity"] == "INFO"
        assert event["related_entities"] == [entity["entity_id"]]
        assert event["observed_at"] == entity["valid_from"]
        assert event["payload"] == {
            "contract": "tacticalapi-blueforce/1",
            "observed_at_basis": entity["attributes"]["valid_from_basis"],
            "event_id_basis": expected_basis,
            "severity_basis": "INFO: the contract carries no urgency field; INFO is the format's "
                              "silence",
        }
        # The record §5.9 since 2026-10-06: the Event carries the message-level part of its
        # Entity's residual — `response` when the Entity has one, and the message- and
        # header-level entries of `unknown`, in the Entity's order — and nothing of the element's.
        data = entity["residual"]["data"]
        part = {"response": data["response"]} if "response" in data else {}
        part["unknown"] = [entry for entry in data["unknown"] if entry["path"] in ("", "header")]
        assert event["residual"] == {"namespace": "TacticalAPI", "data": part}
        assert list(event["residual"]["data"]) == list(part)


# ======================================================================= §5.9 residual


@pytest.mark.parametrize("case", [*WITHOUT_UNKNOWN, "cases/empty_geo_point",
                                  "cases/deleted_without_timestamps", "cases/duplicate_identity",
                                  "cases/d_code_second_set_zero"])
def test_the_residual_is_an_empty_unknown_list_when_nothing_is_unknown(case):
    """The record §5.9 as changed 2026-10-06 (the landing): every Entity and every Event carries
    a residual whose `data` is never empty, so an object with nothing unknown carries `unknown`
    as an empty list and nothing else. Until then it carried `None`, which the host's lossless
    sweep refuses for a `structured` adapter (`tests/test_cdm_lossless.py`)."""
    for raw in (payload(case), twin_file(case)):
        objects = dump(raw)
        assert objects and [obj["residual"] for obj in objects] == [EMPTY_RESIDUAL] * len(objects)


def test_the_residual_of_the_unknown_field_carried_case_whole():
    first, second = entities(dump(payload("cases/unknown_field_carried")))
    header = {"path": "header", "number": 3, "wire_type": 0, "hex": "02"}
    top = {"path": "", "number": 3, "wire_type": 2,
           "hex": "4558455243495345204e4f544520414c504841"}
    assert first["residual"]["namespace"] == second["residual"]["namespace"] == "TacticalAPI"
    assert first["residual"]["data"]["unknown"] == [
        header, top, {"path": "blue_forces[0]", "number": 11, "wire_type": 0, "hex": "01"}]
    assert second["residual"]["data"]["unknown"] == [
        header, top, {"path": "blue_forces[1].point_location.geo_point", "number": 6,
                      "wire_type": 0, "hex": "03"}]
    # Each Event carries the message-level part: the response and header fields, in both places,
    # and neither element's own field (the record §5.9, since 2026-10-06).
    response = {"header": {"@unknown": [{"number": 3, "wire_type": 0, "hex": "02"}]},
                "@unknown": [{"number": 3, "wire_type": 2,
                              "hex": "4558455243495345204e4f544520414c504841"}]}
    for event in events(dump(payload("cases/unknown_field_carried"))):
        assert event["residual"] == {"namespace": "TacticalAPI",
                                     "data": {"response": response, "unknown": [header, top]}}


def test_dict_form_unknown_keys_are_carried_at_their_own_paths_and_listed():
    document = message(force(futureElement=[1, {"a": "b"}],
                             point_location={**at(), "futureKey": {}}),
                       force(identity={"int32_identity": 2}),
                       futureTop="EXERCISE-T")
    document["header"]["futureHeader"] = 4.5
    first, second = entities(dump(document))
    response = {"header": {"futureHeader": 4.5}, "futureTop": "EXERCISE-T"}
    assert first["residual"]["data"] == {
        "response": response,
        "blue_force": {"futureElement": [1, {"a": "b"}], "point_location": {"futureKey": {}}},
        # Message level first, then the element's, each in twin order (known fields by number,
        # then a message's unknown keys): point_location's key precedes the element's own.
        "unknown": [{"path": "header", "key": "futureHeader", "value": 4.5},
                    {"path": "", "key": "futureTop", "value": "EXERCISE-T"},
                    {"path": "blue_forces[0].point_location", "key": "futureKey", "value": {}},
                    {"path": "blue_forces[0]", "key": "futureElement", "value": [1, {"a": "b"}]}]}
    assert second["residual"]["data"] == {
        "response": response,
        "unknown": [{"path": "header", "key": "futureHeader", "value": 4.5},
                    {"path": "", "key": "futureTop", "value": "EXERCISE-T"}]}
    assert "futureElement" not in json.dumps(first["attributes"])
    # Both Events carry the message-level part alone (the record §5.9, since 2026-10-06).
    assert [event["residual"]["data"] for event in events(dump(document))] == [
        {"response": response,
         "unknown": [{"path": "header", "key": "futureHeader", "value": 4.5},
                     {"path": "", "key": "futureTop", "value": "EXERCISE-T"}]}] * 2


# ================================================================ the refusal codes, all of them


ADAPTER_REFUSALS = {
    "response-not-successful": message(force(), header={"success": False}),
    "unknown-fields-without-carrier": message(**{"@unknown": [{"number": 9, "wire_type": 0,
                                                               "hex": "01"}]}),
    "blue-force-without-identity": message({"is_deleted": True}),
    "empty-identity": message(force(identity={"string_identity": ""})),
    "coordinate-out-of-range": message(force(point_location=at(lat=0.5, lon=200.0))),
    "negative-speed": message(force(point_location={**at(), "speed": -2.0})),
    # Nine Entities each carrying a header of some two million characters: past 16 Mi.
    "carried-copies-too-large": message(*[force()] * 9, header={
        "success": True, "error_message": "EXERCISE" * 2 ** 18}),
    # A successful empty response whose header states a text (2026-10-04, final verification).
    "error-message-without-carrier": message(header={"success": True,
                                                     "error_message": "EXERCISE partial"}),
}


def test_every_adapter_refusal_code_of_sections_4_and_5_is_exercised():
    assert set(ADAPTER_REFUSALS) == set(codec.ADAPTER_CODES)
    for code, raw in ADAPTER_REFUSALS.items():
        refused(code, raw)


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_every_malformed_payload_is_refused_by_the_adapter_with_its_code(name):
    refused(MALFORMED[name], (SET / "malformed" / name).read_bytes())


def test_the_malformed_set_is_the_one_listed_here():
    assert sorted(p.name for p in harness.select_fixtures(SET / "malformed")) == sorted(MALFORMED)


def test_every_case_file_is_exercised_by_name_here():
    on_disk = sorted({p.name.split(".")[0] for p in harness.select_fixtures(SET / "cases")})
    assert on_disk == sorted(CASES)
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    for name in CASES:
        assert source.count(f'"cases/{name}"') >= 1, name


# ================================================================= protoc's own readings


def protoc_reading(case: str) -> tuple[str, list]:
    reading = protoc_text.parse((SET / f"independent/{pathlib.Path(case).name}.value.txtpb")
                                .read_text(encoding="utf-8"))
    list_name = ("blue_forces" if protoc_text.values(reading, "blue_forces")
                 else "updated_blue_forces")
    return list_name, protoc_text.values(reading, list_name)


def rendered(seconds: int, nanos: int) -> str:
    """The CDM's rendering of a protoc Timestamp, worked out here: whole milliseconds, truncated."""
    instant = EPOCH + dt.timedelta(seconds=seconds)
    return f"{instant:%Y-%m-%dT%H:%M:%S}.{nanos // 1_000_000:03d}Z"


VERTICAL_BY_NAME = dict(VERTICAL)
SOURCE_BY_NAME = {"MEASUREMENT_CODE_GPS": "GNSS", "MEASUREMENT_CODE_INS": "INERTIAL",
                  "MEASUREMENT_CODE_ESTIMATE": "MANUAL"}


def scalar(value) -> str | int | float:
    return value.decode("utf-8") if isinstance(value, bytes) else value


@pytest.mark.parametrize("case", TRANSLATED)
def test_emitted_canonical_values_agree_with_protocs_readings(case):
    """Every canonical value below is computed from what protoc printed for the payload, with
    the record's rules applied here, and compared with what the adapter emitted for the bytes."""
    _, elements = protoc_reading(case)
    objects = dump(payload(case), OTHER)
    assert len(objects) == 2 * len(elements)
    for element, entity, event in zip(elements, objects[0::2], objects[1::2]):
        [(member, value)] = protoc_text.single(element, "identity")
        external = f"{member}:{scalar(value)}"
        assert entity["source_ids"][0]["external_id"] == external

        point = protoc_text.single(element, "point_location", [])
        # The record §5.3 (as changed 2026-10-04, final verification, item 16): the first of the
        # two times that protoc printed with a non-zero seconds or nanos; a Timestamp it printed
        # as `{ }` (seconds 0, nanos 0) is passed over, and with none left the clock stands in.
        stamps = [protoc_text.single(point, "location_time"),
                  protoc_text.single(element, "last_contact_time")]
        stamp = next((stamp for stamp in stamps if stamp is not None
                      and (protoc_text.single(stamp, "seconds", 0),
                           protoc_text.single(stamp, "nanos", 0)) != (0, 0)), None)
        expected_time = (rendered(protoc_text.single(stamp, "seconds", 0),
                                  protoc_text.single(stamp, "nanos", 0))
                         if stamp is not None else times.render(OTHER))
        assert entity["valid_from"] == event["observed_at"] == expected_time

        geo = protoc_text.single(point, "geo_point")
        names = [name for name, _ in geo] if geo is not None else []
        if "latitude_coordinate" in names or "longitude_coordinate" in names:
            lat = float(protoc_text.single(geo, "latitude_coordinate", 0))
            lon = float(protoc_text.single(geo, "longitude_coordinate", 0))
            assert (entity["position"]["lat"], entity["position"]["lon"]) == (lat, lon)
            assert event["geometry"]["coordinates"] == [lon, lat]
            code = protoc_text.single(geo, "measurement_code")
            assert entity["position"]["position_source"] == SOURCE_BY_NAME.get(code, "ESTIMATED")
            height = protoc_text.single(geo, "vertical_distance")
            if height is None:
                assert entity["position"]["vertical"] is None
            else:
                reference_code = protoc_text.single(geo, "vertical_distance_reference_code")
                reference = VERTICAL_BY_NAME.get(reference_code, "UNKNOWN")
                value = float(protoc_text.single(height, "value", 0))
                assert entity["position"]["vertical"]["value"] == value
                assert entity["position"]["vertical"]["reference"] == reference
                assert entity["position"]["alt_m"] == (value if reference == "HAE" else None)
        else:
            assert entity["position"] is None and event["geometry"] is None

        speed = protoc_text.single(point, "speed")
        assert (entity["kinematics"] or {}).get("speed_mps") == (
            None if speed is None else float(protoc_text.single(speed, "value", 0)))
        # R5 (2026-10-06): a course in [0, 360) is course_deg; any other is not mapped.
        course = protoc_text.single(point, "course")
        stated = None if course is None else float(protoc_text.single(course, "value", 0))
        assert (entity["kinematics"] or {}).get("course_deg") == (
            stated if stated is not None and 0 <= stated < 360 else None)

        symbol = protoc_text.single(element, "symbol")
        expected_symbol = None
        if symbol is not None and protoc_text.single(symbol, "symbol_catalog") == \
                "SYMBOL_CATALOG_MIL2525_D" and protoc_text.single(symbol, "numeric_identifier"):
            sets = protoc_text.single(symbol, "numeric_identifier")
            first = protoc_text.single(sets, "first_ten_digits", 0)
            second = protoc_text.single(sets, "second_ten_digits", 0)
            if 10 ** 9 <= first < 10 ** 10:
                expected_symbol = f"{first}{second:010d}"
        assert entity["symbol"] == expected_symbol

        flags = protoc_text.single(element, "blue_force_type", [])
        platform = any(protoc_text.single(flags, name) == "true"
                       for name in ("is_vehicle", "is_unmanned"))
        assert entity["entity_type"] == ("PLATFORM" if platform else "UNKNOWN")
        deleted = protoc_text.single(element, "is_deleted") == "true"
        assert event["event_type"] == ("STATUS_CHANGE" if deleted else "TRACK_UPDATE")


# ============================================================ determinism and the clock


@pytest.mark.parametrize("case", TRANSLATED)
def test_translation_is_deterministic_under_a_frozen_clock(case):
    renderings = {canonical.serialise(dump(raw, FROZEN))
                  for raw in (payload(case), payload(case), twin_file(case))}
    assert len(renderings) == 1


def test_only_received_at_moves_with_the_clock_when_every_element_states_a_time():
    here = dump(payload("snapshot_three_forces"), FROZEN)
    there = dump(payload("snapshot_three_forces"), OTHER)
    for one, two in zip(here, there):
        if one["object_kind"] == "event":
            assert one["received_at"] == times.render(FROZEN)
            assert two["received_at"] == times.render(OTHER)
            one, two = dict(one, received_at=None), dict(two, received_at=None)
        assert one == two


# ================================================================================ limits


def input_of_size(size: int) -> bytes:
    """An Any of exactly `size` octets: a successful header and one keyed element whose callsign
    is padding. Lengths are varints, so the overhead is re-measured until it settles."""
    padding = size
    for _ in range(8):
        element = pw.field_len(1, pw.field_varint(3, 1)) + pw.field_len(
            3, pw.field_len(1, b"E" * padding))
        raw = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element))
        if len(raw) == size:
            return raw
        padding -= len(raw) - size
    raise AssertionError(f"no padding gives {size} octets")


def test_max_input_bytes_admits_the_bound_and_refuses_one_past():
    bound = TacticalapiAdapter.metadata.capabilities.limits.max_input_bytes
    assert bound == codec.MAX_INPUT_BYTES
    at_bound = input_of_size(bound)
    entity, _ = adapter().to_cdm(at_bound)
    assert entity.source_ids[0].external_id == "int32_identity:1"
    assert len(entity.attributes["tacticalapi"]["blue_force"]["callsign"]) > bound - 200
    past = input_of_size(bound + 1)
    for form in (past, bytearray(past), memoryview(past)):
        with pytest.raises(InputTooLarge) as caught:
            adapter().to_cdm(form)
        assert str(bound) in str(caught.value) and str(bound + 1) in str(caught.value)
    # The codec's own refusal stands behind the base class's for a direct caller.
    with pytest.raises(TacticalapiRefused) as caught:
        codec.decode(past)
    assert caught.value.code == "input-too-large"


def deep_twin(depth: int) -> dict:
    """A dict-form message `depth` containers deep: the top object (1), the header (2), and an
    unknown header key whose value nests lists for the rest; one keyed element to carry it."""
    value: list = []
    for _ in range(depth - 3):
        value = [value]
    return message(force(identity={"int32_identity": 5}),
                   header={"success": True, "futureField": value})


def test_max_depth_admits_the_bound_and_refuses_one_past():
    bound = TacticalapiAdapter.metadata.capabilities.limits.max_depth
    assert bound == codec.MAX_DEPTH
    at_bound = deep_twin(bound)
    assert container_depth(at_bound) == bound
    entity, _ = adapter().to_cdm(at_bound)
    assert container_depth(entity.residual.data["response"]["header"]["futureField"]) == bound - 2
    past = deep_twin(bound + 1)
    assert container_depth(past) == bound + 1
    with pytest.raises(InputTooDeep) as caught:
        adapter().to_cdm(past)
    assert f"nesting {bound + 1} containers deep" in str(caught.value)
    with pytest.raises(TacticalapiRefused) as refused_by_codec:
        codec.validate_twin(past)
    assert refused_by_codec.value.code == "nesting-too-deep"


def test_the_base_class_reads_a_bytes_payload_that_opens_like_json_as_json():
    """The record "Changes", adapter stage, item 3, recorded rather than worked around: an Any
    whose type_url is 123 octets long begins `\\n{`, so `adapter.enforce_depth_bound` measures it
    as JSON text, and a prefix of 73 `[` reads 74 containers deep. The decoder reads it, and the
    same payload with another prefix translates."""
    name = b"rheinmetall.tactical_api.v0.GetBlueForcesResponse"
    element = pw.field_len(1, pw.field_varint(3, 7))
    for opener, translates in ((b"[", False), (b"x", True)):
        url = opener * (123 - len(name) - 1) + b"/" + name
        raw = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element), url)
        assert raw[:2] == b"\x0a\x7b" and len(codec.decode(raw)["blue_forces"]) == 1
        if translates:
            assert len(adapter().to_cdm(raw)) == 2
        else:
            with pytest.raises(InputTooDeep):
                adapter().to_cdm(raw)


def test_max_objects_admits_the_bound_and_refuses_one_past():
    bound = TacticalapiAdapter.metadata.capabilities.limits.max_objects
    assert bound == codec.MAX_OBJECTS
    # One element keyed by int32_identity 1: 0x12 0x04 0x0a 0x02 0x18 0x01.
    keyed = pw.field_len(2, pw.field_len(1, pw.field_varint(3, 1)))
    header = b"\x0a\x02\x08\x01"
    objects = adapter().to_cdm(pw.any_of(header + keyed * bound))
    assert len(objects) == 2 * bound
    assert objects[-2].source.record_index == bound - 1
    refused("too-many-objects", pw.any_of(header + keyed * (bound + 1)))
    refused("too-many-objects", pw.any_of(header + keyed * (bound + 1), pw.SUBSCRIBE_URL))
    refused("too-many-objects", message(*[force()] * (bound + 1)))


def header_with_unknowns(count: int) -> bytes:
    """A successful header followed by `count` unknown varint fields (field 15: tag 0x78)."""
    return pw.field_len(1, b"\x08\x01" + b"\x78\x07" * count)


def test_max_unknown_fields_admits_the_bound_and_refuses_one_past():
    """The codec holds the unknown fields one input holds to the bound, and the adapter holds the
    copies its objects carry to it. An element's own field is carried once, on its Entity; a
    header-level field is carried on the Entity and on the Event (the record §5.9, since
    2026-10-06), so on one element half the bound of them is the bound."""
    bound = codec.MAX_UNKNOWN_FIELDS
    keyed = pw.field_len(2, pw.field_len(1, pw.field_varint(3, 1)))
    own = pw.field_len(2, pw.field_len(1, pw.field_varint(3, 1)) + b"\x78\x07" * bound)
    entity, event = adapter().to_cdm(pw.any_of(b"\x0a\x02\x08\x01" + own))
    assert len(entity.residual.data["unknown"]) == bound
    assert event.residual.data == {"unknown": []}
    # One past in the input itself: the codec refuses before the adapter counts anything.
    error = refused("too-many-unknown-fields", pw.any_of(header_with_unknowns(bound + 1) + keyed))
    assert "holds unknown field" in str(error)
    half = bound // 2
    entity, event = adapter().to_cdm(pw.any_of(header_with_unknowns(half) + keyed))
    assert len(entity.residual.data["unknown"]) == len(event.residual.data["unknown"]) == half
    assert len(entity.residual.data["response"]["header"]["@unknown"]) == half
    assert len(event.residual.data["response"]["header"]["@unknown"]) == half
    error = refused("too-many-unknown-fields", pw.any_of(header_with_unknowns(half + 1) + keyed))
    assert "carried on each of 1 entities and 1 events" in str(error)
    assert f"make {bound + 2} carried unknown fields" in str(error)


def test_the_carried_copies_of_message_level_unknown_fields_count_against_the_bound():
    """The record's "Changes", adapter stage, item 2: a header-level field is carried on every
    Entity, so two elements carry it twice; and since 2026-10-06 (the record §5.9) on every
    Event too, so two elements carry it four times."""
    bound = codec.MAX_UNKNOWN_FIELDS
    quarter, half = bound // 4, bound // 2
    keyed = pw.field_len(2, pw.field_len(1, pw.field_varint(3, 1)))
    objects = adapter().to_cdm(pw.any_of(header_with_unknowns(quarter) + keyed * 2))
    assert [len(obj.residual.data["unknown"]) for obj in objects] == [quarter] * 4
    error = refused("too-many-unknown-fields",
                    pw.any_of(header_with_unknowns(quarter + 1) + keyed * 2))
    assert "carried on each of 2 entities and 2 events" in str(error)
    assert f"make {bound + 4} carried unknown fields" in str(error)
    # Element-level fields are carried once, on their Entity: two elements of `half` each are at
    # the bound, and their Events carry none of them.
    own = pw.field_len(2, pw.field_len(1, pw.field_varint(3, 1)) + b"\x78\x07" * half)
    objects = adapter().to_cdm(pw.any_of(b"\x0a\x02\x08\x01" + own * 2))
    assert [len(obj.residual.data["unknown"]) for obj in objects] == [half, 0, half, 0]


def test_the_declared_limits_are_the_codec_constants_and_cite_tests_that_exist():
    limits = TacticalapiAdapter.metadata.capabilities.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects) == (
        codec.MAX_INPUT_BYTES, codec.MAX_DEPTH, codec.MAX_OBJECTS)
    assert (limits.max_decompressed_bytes, limits.max_parse_seconds) == (None, None)
    assert set(limits.absent_because) == {"max_decompressed_bytes", "max_parse_seconds"}
    assert set(limits.declared_because) == {"max_input_bytes", "max_depth", "max_objects"}
    # Since 2026-10-06 (the landing): `max_input_bytes` cites the host's one test of every
    # declared byte bound, which the host requires of every shipped adapter; the other two cite
    # this module. Each cited test exists.
    assert {name: basis.test.partition("::")[0]
            for name, basis in limits.declared_because.items()} == {
        "max_input_bytes": "tests/test_cdm_input_bounds.py",
        "max_depth": "tests/test_cdm_tacticalapi_adapter.py",
        "max_objects": "tests/test_cdm_tacticalapi_adapter.py"}
    for name, basis in limits.declared_because.items():
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP, name
        path, _, function = basis.test.partition("::")
        assert f"def {function}(" in (ROOT / path).read_text(encoding="utf-8"), name
    assert "MAX_UNKNOWN_FIELDS" in limits.declared_because["max_objects"].source


# ============================================================================ validate_source


def test_validate_source_names_every_unknown_field_with_its_path():
    assert adapter().validate_source(payload("cases/unknown_field_carried")) == [
        "header: field number 3 (wire type 0) is not in the pinned contract; carried in the "
        "residual",
        "blue_forces[0]: field number 11 (wire type 0) is not in the pinned contract; carried in "
        "the residual",
        "blue_forces[1].point_location.geo_point: field number 6 (wire type 0) is not in the "
        "pinned contract; carried in the residual",
        "the response: field number 3 (wire type 2) is not in the pinned contract; carried in the "
        "residual",
    ]


def test_validate_source_names_symbols_not_promoted_a_digit_disagreement_and_lengths():
    found = adapter().validate_source(payload("awkward_symbols_and_codes"))
    # Four since 2026-10-04 (final verification, item 26): the vendor catalog's 22-character
    # string was reported against the 15 the contract states for two other catalogs only.
    assert len(found) == 4
    assert found[0].startswith("updated_blue_forces[0].symbol: not promoted: symbol_catalog "
                               "SYMBOL_CATALOG_MIL2525_C")
    assert found[1] == ("updated_blue_forces[0].symbol.string_identifier is 14 characters; the "
                        "contract's string form is 15 (reported, not enforced)")
    assert found[2].startswith("updated_blue_forces[1].symbol: not promoted: symbol_catalog "
                               "SYMBOL_CATALOG_RME")
    assert not [line for line in found if "updated_blue_forces[1].symbol.string_identifier" in line]
    assert found[3].startswith("updated_blue_forces[2].symbol: the 2525D code's standard-identity "
                               "digit is '2', not the friend digit '3'")
    # Worded 2026-10-06 (R3): an observation against the service's own definition, not against
    # Entity.affiliation, which is UNKNOWN unless the caller supplies one and is never compared.
    assert found[3] == (
        "updated_blue_forces[2].symbol: the 2525D code's standard-identity digit is '2', not the "
        "friend digit '3', while the service's own definition names the members of this list "
        "blue forces; the symbol is carried unchanged, and Entity.affiliation is neither read "
        "from it nor compared with it")
    # The 2525C string of the snapshot is 15 characters: its non-promotion alone is named.
    basis = entities(dump(payload("snapshot_three_forces")))[1]["attributes"]["symbol_basis"]
    assert adapter().validate_source(payload("snapshot_three_forces")) == [
        f"blue_forces[1].symbol: {basis}"]


def test_validate_source_names_each_element_with_no_source_time():
    assert adapter().validate_source(payload("cases/deleted_without_timestamps")) == [
        "updated_blue_forces[0]: states no source time; valid_from and observed_at are the "
        "receipt instant from the injected clock"]


@pytest.mark.parametrize("case", ["delta_with_deletion", "cases/empty_geo_point",
                                  "cases/duplicate_identity", "cases/empty_successful_response"])
def test_validate_source_has_nothing_to_say_about_a_clean_message(case):
    assert adapter().validate_source(payload(case)) == []
    assert adapter().validate_source(twin_file(case)) == []


def test_validate_source_has_two_lines_about_awkward_zeros_its_zero_timestamp_and_its_360():
    """awkward_zeros was in the clean list above until 2026-10-04 (final verification, item 16),
    when it gained a second element whose location_time is the zero Timestamp; that element's
    course of 360 (2026-10-06, R5) is the second line. They are all validate_source says about
    it, in both forms; its first element, course 0 included, is still clean."""
    expected = [f"blue_forces[1].point_location.location_time {module.ZERO_PASSED_OVER}",
                f"blue_forces[1].point_location.course is 360.0, {NOT_MAPPED}"]
    assert adapter().validate_source(payload("awkward_zeros")) == expected
    assert adapter().validate_source(twin_file("awkward_zeros")) == expected
    assert "is the zero Timestamp (1970-01-01T00:00:00Z)" in expected[0]


def test_validate_source_reports_a_refusal_instead_of_raising():
    assert adapter().validate_source((SET / "malformed/success_false.binpb").read_bytes()) == [
        "TacticalapiRefused: response-not-successful: header.success is absent from the wire, "
        "which reads false; header.error_message: 'EXERCISE feed unavailable'; only a response "
        "whose header.success is true is translated"]
    [line] = adapter().validate_source(input_of_size(codec.MAX_INPUT_BYTES + 1))
    assert line.startswith("InputTooLarge: ")


# ===================================================================================== detect


def test_detect_answers_on_the_envelopes_type_name():
    probe = adapter()
    for case in HARNESS_FIXTURES:
        assert probe.detect(payload(case)) is True
        assert probe.detect(twin_file(case)) is True
    # A supported type name is enough; the payload's content is translate's business.
    assert probe.detect((SET / "malformed/success_false.binpb").read_bytes()) is True
    assert probe.detect({"@type": GET}) is True
    assert probe.detect((SET / "malformed/unsupported_message_type.binpb").read_bytes()) is False
    assert probe.detect({"@type": GET.replace("/", "|")}) is False
    assert probe.detect({"header": {"success": True}}) is False
    assert probe.detect({"@type": 7}) is False
    assert probe.detect(b"\xff\xff") is False
    assert probe.detect(input_of_size(codec.MAX_INPUT_BYTES + 1)) is False
    assert probe.detect("text") is None


# ================================================================================ §6 metadata


def test_the_declaration_is_section_6():
    cls = TacticalapiAdapter
    meta = cls.metadata
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "tacticalapi", "1.0.0", "ingest", "TacticalAPI")
    assert (cls.__module__, cls.__qualname__) == ("synapse_cdm.adapters.tacticalapi",
                                                  "TacticalapiAdapter")
    assert meta.id == "tacticalapi" and meta.adapter_version == "1.0.0"
    assert meta.format.name == "TacticalAPI"
    assert meta.format.version == ("rheinmetall.tactical_api.v0, commit 58661c9 (2026-09-01); no "
                                   "tag or release exists")
    assert meta.direction is Direction.INGEST
    assert meta.binding is WireBinding.STANDARD
    # OPEN since 2026-10-06, the maintainer's ruling R7 (the record's rulings); LICENSED, a
    # placeholder, before.
    assert meta.license_class is LicenseClass.OPEN
    assert meta.maturity.level is MaturityLevel.L3 and meta.maturity.external_exercise is None
    # VERIFIED since 2026-10-04 (final verification, item 18): the claim the host's ruling (B)
    # pairs with standard-encoding and its in-tree gate requires; IMPLEMENTED before.
    assert meta.claim_status is ClaimStatus.VERIFIED and meta.claim_external_system is None
    assert meta.capabilities.wire is True
    assert meta.capabilities.directions_exercised == ["ingest"]
    assert meta.capabilities.message_types == [
        "rheinmetall.tactical_api.v0.GetBlueForcesResponse",
        "rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse"]
    assert meta.capabilities.unknown_fields is UnknownFields.PRESERVED
    assert "residual.data.unknown" in meta.capabilities.unknown_fields_basis
    assert meta.residual is Residual.STRUCTURED
    # True since 2026-10-07, the 3.3.0 release commit; false from the landing until then.
    assert meta.evidence.available is True
    assert (meta.profiles, meta.payload_adapter, meta.constituents,
            meta.limitations_empty_reason) == ([], None, [], None)
    assert cls.TRANSFORMS == {}
    assert cls.from_cdm is module.Adapter.from_cdm


def test_the_limitations_are_section_6s_structured_entries():
    limitations = TacticalapiAdapter.metadata.limitations
    assert all(isinstance(entry, Limitation) for entry in limitations)
    assert [entry.id for entry in limitations] == [
        "blue-force-read-side-only", "capture-envelope", "pinned-commit-v0",
        "coordinate-unit-not-stated", "course-reference-not-stated", "symbol-2525d-only",
        "proto3-zero-indistinguishable", "non-canonical-encoding-refused", "source-time-optional",
        "no-endpoint-exercised", "evidence-availability", "resource-limits"]
    assert all(entry.unsupported_paths == [] for entry in limitations)
    assert not [entry.id for entry in limitations if "provisional" in entry.summary.lower()]
    by_id = {entry.id: entry.summary for entry in limitations}
    # Renamed 2026-10-06 at the landing from `evidence-not-available`, which named the
    # out-of-tree project: the pre-release form `dis7` used until its release. Flipped
    # 2026-10-07 in the 3.3.0 release commit to the form `dis7`'s took at 3.2.0, which names no
    # version, so it stays true whatever happens to any one tag.
    assert by_id["evidence-availability"] == (
        "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
        "untracked and unpackaged, CI generates the set on every run, and the release pipeline "
        "generates the records for every shipped adapter and attaches them to the GitHub Release "
        "of the version it publishes. `evidence.available` is true because every published "
        "distribution that carries this adapter has that Release, so its records are retrievable "
        "by a third party; it says nothing about what the wheel contains")
    # Reworded 2026-10-06 (R5): the north reference is an assumption stated on every mapped
    # value, no longer a reason the course is unmapped.
    course = by_id["course-reference-not-stated"]
    assert "ASSUMED true" in course and "`course_basis`" in course and "never mapped" not in course
    assert "360 included, is not mapped and not normalised" in course
    assert "`max_input_bytes`, `max_depth` and `max_objects`" in by_id["resource-limits"]


def test_the_manifest_the_package_generates_for_this_class_is_the_published_one():
    """Inverted on 2026-10-06, when the adapter landed: out of tree, this held that the package's
    own publication (`manifests.generate`) did not include the class. Now the class is shipped,
    its manifest is among the package's, it validates against the published manifest schema,
    and it is byte for byte the committed `manifests/tacticalapi.json`."""
    published = manifests.manifest(TacticalapiAdapter).model_dump(mode="json")
    jsonschema.Draft202012Validator(schemas.manifest_schema()).validate(published)
    assert published["adapter"] == TacticalapiAdapter.metadata.model_dump(mode="json")
    assert published["adapter"]["maturity"]["level"] == "L3"
    assert published["adapter"]["evidence"] == {"available": True}
    assert is_shipped(TacticalapiAdapter)
    assert manifests.generate()["tacticalapi"] == published
    committed = json.loads((ROOT / "manifests" / "tacticalapi.json").read_text(encoding="utf-8"))
    assert committed == published


def test_the_harness_resolves_the_class_by_name_and_reference_and_the_registry_holds_it():
    assert load_adapter("tacticalapi") is TacticalapiAdapter
    assert load_adapter("synapse_cdm.adapters.tacticalapi:TacticalapiAdapter") is TacticalapiAdapter
    assert REGISTRY["tacticalapi"] is TacticalapiAdapter
    assert shipped()["tacticalapi"] is TacticalapiAdapter


# ================================================================================ the ledger


@pytest.mark.parametrize("case", [case for case in TRANSLATED
                                  if case != "cases/empty_successful_response"])
def test_the_ledger_binds_every_leaf_of_every_twin_with_no_loss(case):
    twin = twin_file(case)
    book = lossless.ledger(twin, dump(twin), TacticalapiAdapter.MAPPINGS)
    assert book.lost == (), book.problem_lines()
    assert book.counts["MAPPED"] + book.counts["RESIDUAL"] == book.total > 0


def test_the_empty_response_has_no_object_for_its_leaves_to_reach():
    """§4: a successful empty snapshot is `[]`, so its header leaves have no carrier at all; the
    harness never selects it, and this is the reading, stated."""
    twin = twin_file("cases/empty_successful_response")
    book = lossless.ledger(twin, dump(twin), TacticalapiAdapter.MAPPINGS)
    assert sorted(entry.source_path for entry in book.lost) == ["@type", "header.success"]


def test_negative_a_wrong_position_is_caught_by_the_ledger():
    twin = twin_file("snapshot_three_forces")
    objects = dump(twin)
    objects[0]["position"]["lat"] = objects[2]["position"]["lat"]
    lost = lossless.ledger(twin, objects, TacticalapiAdapter.MAPPINGS).lost
    assert [entry.source_path for entry in lost] == [
        "blue_forces[0].point_location.geo_point.latitude_coordinate"]


def test_negative_a_wrong_or_a_missing_course_is_caught_by_the_ledger():
    """The course's ledger row (R5, 2026-10-06) is no blessing of what the adapter emits: a
    course_deg that differs from the source, and one set for the course of 360, both read LOST."""
    twin = twin_file("snapshot_three_forces")
    objects = dump(twin)
    objects[2]["kinematics"]["course_deg"] = 248.5
    lost = lossless.ledger(twin, objects, TacticalapiAdapter.MAPPINGS).lost
    assert [entry.source_path for entry in lost] == ["blue_forces[1].point_location.course"]
    twin = twin_file("awkward_zeros")
    objects = dump(twin)
    for entity in entities(objects):
        entity["kinematics"] = {"speed_mps": 0.0, "course_deg": 0.0, "climb_mps": None}
    lost = lossless.ledger(twin, objects, TacticalapiAdapter.MAPPINGS).lost
    assert [entry.source_path for entry in lost] == ["blue_forces[1].point_location.course"]


def test_the_ledger_cannot_hold_an_unmapped_course_other_than_360():
    """A reading of the ledger grammar, recorded (the record "Typed block layout (as built)"):
    `absent_if` takes one sentinel and no rule takes a range, so the course's row holds 360 to
    an absent course_deg and every other value to course_deg by `number`. A negative course, or
    one past 360, is translated as R5 says — carried in the typed block, named by
    validate_source, not mapped — and the ledger reports that one leaf LOST all the same. No
    shipped fixture holds such a course."""
    for course in (-5.0, 400.0):
        twin = course_twin(course)
        book = lossless.ledger(twin, dump(twin), TacticalapiAdapter.MAPPINGS)
        assert [(entry.source_path, entry.loss) for entry in book.lost] == [
            ("blue_forces[0].point_location.course", "MISSING")]
    twin = course_twin(360.0)
    assert lossless.ledger(twin, dump(twin), TacticalapiAdapter.MAPPINGS).lost == ()


def test_negative_a_dropped_unknown_field_is_caught_by_the_ledger():
    twin = twin_file("cases/unknown_field_carried")
    objects = dump(twin)
    del objects[2]["residual"]["data"]["blue_force"]
    lost = lossless.ledger(twin, objects, TacticalapiAdapter.MAPPINGS).lost
    assert sorted(entry.source_path for entry in lost) == [
        "blue_forces[1].point_location.geo_point.@unknown[0].hex",
        "blue_forces[1].point_location.geo_point.@unknown[0].number",
        "blue_forces[1].point_location.geo_point.@unknown[0].wire_type"]


# ============================================================================ the module


def test_the_receipt_instant_comes_from_the_injected_clock_alone():
    """`self.now()` is the one clock the module reads (the promotion gates scan for the wall
    clock and for `json.loads` across the adapter's modules); here, that it is read at all, and
    only there."""
    tree = ast.parse(MODULE_SOURCE.read_text(encoding="utf-8"))
    calls = [f"{node.func.value.id}.{node.func.attr}" for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Name) and node.func.attr == "now"]
    assert calls == ["self.now"]


# ============================================ final verification, 2026-10-04: carried copies
#
# The record §4 and §6, and "Changes", final verification: the data every Entity of a message
# carries is measured once and, times the number of Entities, held to MAX_CARRIED_COPY_CHARS.


def measured(value) -> int:
    """The record §4's measure, as changed 2026-10-04 (final verification, item 14), written
    here from its words: the characters of the value's compact JSON text with ASCII escaping,
    which is what `json.dumps(value, separators=(",", ":"))` writes. (It was the characters of
    every string plus one for every number, boolean and container until that day.)"""
    return len(json.dumps(value, separators=(",", ":")))


def carried_by_all(objects) -> int:
    """The JSON text of every message-level copy the objects of a translation really carry: each
    Entity's `message` member, and each Entity's and each Event's `residual.data.response` and
    `residual.data.unknown` entries whose path is the response's or the header's (an Event
    carries those since 2026-10-06, the record §5.9). Read off the objects, not computed."""
    total = 0
    for obj in objects:
        if obj.object_kind == "entity":
            total += measured(obj.attributes["tacticalapi"]["message"])
        data = obj.residual.data
        total += measured(data["response"]) if "response" in data else 0
        total += sum(measured(entry) for entry in data["unknown"]
                     if entry["path"] in ("", "header"))
    return total


#: One element keyed by int32_identity 1: 0x12 0x04 0x0a 0x02 0x18 0x01.
KEYED = pw.field_len(2, pw.field_len(1, pw.field_varint(3, 1)))


def header_saying(length: int) -> bytes:
    """A successful header whose error_message is `length` characters of E."""
    return pw.field_len(1, b"\x08\x01" + pw.field_len(2, pw.field_len(1, b"E" * length)))


def message_member_size(length: int, index: int = 0) -> int:
    """The `message` member of a GetBlueForcesResponse's typed block whose header states success
    and an error_message of `length` characters, as compact JSON text, counted by hand:
    `{"type":"…","type_url":"…","list":"blue_forces","index":0,"header":{"success":true,
    "error_message":"…"}}` is 150 characters of punctuation, keys and fixed values around the
    type name (49) and the type_url (69) — 219 in all with an empty error_message — and the
    index's digits stand in for the 0."""
    return 219 + length + len(str(index)) - 1


def index_digits(count: int) -> int:
    """The digits of the indices 0 … count − 1, written out (the adapter adds them up)."""
    return sum(len(str(index)) for index in range(count))


def test_the_measure_is_mapping_sections_and_the_constant_its_basis():
    assert codec.MAX_CARRIED_COPY_CHARS == 16 * 2 ** 20 == 4 * 4 * 2 ** 20
    assert message_member_size(0) == measured(
        {"type": GET.rsplit("/", 1)[1], "type_url": GET, "list": "blue_forces", "index": 0,
         "header": {"success": True, "error_message": ""}}) == 219
    # The `message` member of an ordinary successful snapshot (no error_message): 200, and 230
    # for a stream update, of which the type_url and the header with their keys are 110, about
    # the hundred the basis states.
    ordinary = only_entity(message(force()))["attributes"]["tacticalapi"]["message"]
    assert measured(ordinary) == codec.carried_size(ordinary) == 200
    stream = only_entity(message(force(), url=SUBSCRIBE))["attributes"]["tacticalapi"]["message"]
    assert measured(stream) == codec.carried_size(stream) == 230
    assert measured({"type_url": GET, "header": {"success": True}}) == 110
    for value in ({"a": [1, 2.5, True, "xyz", {}]}, [], "", 0, {"": ""}, [1e300, -2 ** 63],
                  "\x00\x1f\"\\", "\U0001f600é", {"k\n": [2 ** 64 - 1, 0.1]}):
        assert codec.carried_size(value) == measured(value)
    # What the old measure missed: a number by its digits, an escape by its characters.
    assert codec.carried_size(2 ** 64 - 1) == 20 and codec.carried_size(1e300) == 6
    assert codec.carried_size("\x01") == 8 and codec.carried_size("\U0001f600") == 14


def test_the_basis_says_what_ten_thousand_ordinary_elements_use_of_the_bound():
    """N6 (the record "Changes", final verification, item 36): the basis said "between an
    eighth and a seventh", and a snapshot's 10 000 ordinary elements use less than an eighth.
    Read off the translated objects: about an eighth (under it) for a snapshot, just under a
    seventh for a stream update, as the record §6 and the codec's comment now say."""
    used = {}
    for url in (GET, SUBSCRIBE):
        objects = adapter().to_cdm(message(*[force()] * codec.MAX_OBJECTS, url=url))
        used[url] = carried_by_all(objects) / codec.MAX_CARRIED_COPY_CHARS
    assert 1 / 9 < used[GET] < 1 / 8 < used[SUBSCRIBE] < 1 / 7, used
    wording = "about an eighth of it (a snapshot) to just under a seventh (a stream update)"
    mapping = RECORD.read_text(encoding="utf-8")
    section = mapping.split("\n## 6. Declared metadata\n", 1)[1].split("\n## 7.", 1)[0]
    codec_source = CODEC_SOURCE.read_text(encoding="utf-8")
    for text in (section, codec_source):
        text = " ".join(text.replace("#:", " ").split())
        assert wording in text and "between an eighth and a seventh" not in text


def test_the_index_digits_are_added_up_exactly():
    """The adapter writes the first Entity's data once and adds every other index's digits
    without writing them: the sum is the written one at each decade's edge."""
    for count in (0, 1, 9, 10, 11, 99, 100, 101, 1000, 10_000):
        assert module._index_digits(count) == index_digits(count), count


@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_carried_copies_admit_the_bound_and_refuse_one_past(form):
    """Eight Entities whose message member is 2^21 characters each carry exactly 16 Mi and are
    translated, and their objects really hold that much; one character more is refused. 161
    Entities whose member is 104 205 characters at index 0 carry 16 Mi + 1 once each index's
    digits are counted (161 x 104 204 + 10 + 90 x 2 + 61 x 3 = 2^24 + 1) and are refused; one
    character shorter they are within the bound, and the copies they carry measure exactly what
    the adapter added up. Counted without the indices' digits, 161 x 104 205 would pass."""
    def raw(count: int, length: int):
        if form == "bytes":
            return pw.any_of(header_saying(length) + KEYED * count)
        return message(*[force(identity={"int32_identity": 1})] * count,
                       header={"success": True, "error_message": "E" * length})
    bound = codec.MAX_CARRIED_COPY_CHARS
    at_bound = 2 ** 21 - message_member_size(0)
    assert 8 * message_member_size(at_bound) == bound and index_digits(8) == 8
    objects = adapter().to_cdm(raw(8, at_bound))
    assert len(objects) == 16
    assert carried_by_all(objects) == bound
    refused("carried-copies-too-large", raw(8, at_bound + 1))

    one_past = 104_205 - message_member_size(0)
    assert 161 * (message_member_size(one_past) - 1) + index_digits(161) == bound + 1
    assert 161 * message_member_size(one_past) < bound
    error = refused("carried-copies-too-large", raw(161, one_past))
    assert f"161 entities and 161 events of the message would carry {bound + 1}; at most " \
        f"{bound}" in str(error)
    within = adapter().to_cdm(raw(161, one_past - 1))
    assert carried_by_all(within) == bound + 1 - 161 <= bound


@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_message_level_unknown_fields_count_in_every_place_an_entity_and_its_event_carry_them(
        form):
    """A header-level unknown field of `octets` octets sits under residual.data.response
    (`{"header":{"@unknown":[{"number":15,"wire_type":2,"hex":"…"}]}}`, 62 + 2 x octets) and in
    residual.data.unknown (`{"path":"header",…,"hex":"…"}`, 52 + 2 x octets) of the Entity, and
    of its Event since 2026-10-06 (the record §5.9), beside the Entity's message member of 219 +
    the error_message: on eight elements, 2^17 octets and an error_message of 1 048 129
    characters are 2^21 for each element and the bound in all. (Until 2026-10-06 the Event
    carried none of it, and the figures were 2^18 octets and 1 048 243 characters.)"""
    def raw(octets: int, length: int = 1_048_129):
        if form == "bytes":
            # 0x7a = field 15 << 3 | 2, an unknown field of the header.
            header = pw.field_len(1, b"\x08\x01" + pw.field_len(2, pw.field_len(1, b"E" * length))
                                  + pw.field_len(15, b"E" * octets))
            return pw.any_of(header + KEYED * 8)
        return message(*[force(identity={"int32_identity": 1})] * 8, header={
            "success": True, "error_message": "E" * length,
            "@unknown": [{"number": 15, "wire_type": 2, "hex": "45" * octets}]})
    octets = 2 ** 17
    assert 8 * (219 + 1_048_129 + 2 * (62 + 52 + 4 * octets)) == codec.MAX_CARRIED_COPY_CHARS
    objects = adapter().to_cdm(raw(octets))
    for carrier in objects[:2]:
        data = carrier.residual.data
        assert (measured(data["response"]), measured(data["unknown"][0])) == (62 + 2 * octets,
                                                                              52 + 2 * octets)
    assert carried_by_all(objects) == codec.MAX_CARRIED_COPY_CHARS
    # Two more characters in each of the four places: counted on the Entities alone, they would
    # still be inside the bound.
    assert 8 * (219 + 1_048_129 + 62 + 52 + 4 * (octets + 1)) < codec.MAX_CARRIED_COPY_CHARS
    refused("carried-copies-too-large", raw(octets + 1))


#: For the dict-form measure tests: one Entity and its Event, a header key the contract does not
#: name holding `value` (carried in residual.data.response and in residual.data.unknown of both,
#: the Event's since 2026-10-06), and an error_message of E padding the message member so the
#: whole is exactly `size`.
def one_entity_carrying(value, size: int) -> dict:
    response = measured({"header": {"futureKey": value}})
    entry = measured({"path": "header", "key": "futureKey", "value": value})
    length = size - message_member_size(0) - 2 * (response + entry)
    assert length >= 0
    return message(force(identity={"int32_identity": 1}), header={
        "success": True, "error_message": "E" * length, "futureKey": value})


@pytest.mark.parametrize("value", [
    [1.0e+300] * 4096,                              # six characters each, counted one before
    "\x01" * 65_536,                                # control characters: six each when written
    "\U0001f600" * 32_768,                          # astral: a surrogate pair, twelve each
    [-(2 ** 63), 2 ** 64 - 1] * 2048,               # the widest integers ProtoJSON writes
], ids=["floats", "control characters", "astral characters", "64-bit integers"])
def test_the_measure_counts_what_json_writes_at_the_bound_and_one_past(value):
    """robustness-4 (2026-10-04, final verification): the measure is the JSON text, so a value
    whose text is longer than its characters or its count of numbers is held to what it writes.
    At the bound the message-level copies of the one Entity and its Event measure exactly 16 Mi;
    one past is refused. Under the earlier measure the one-past input was far inside the bound."""
    bound = codec.MAX_CARRIED_COPY_CHARS
    objects = adapter().to_cdm(one_entity_carrying(value, bound))
    assert carried_by_all(objects) == bound
    error = refused("carried-copies-too-large", one_entity_carrying(value, bound + 1))
    assert f"1 entities and 1 events of the message would carry {bound + 1}; at most " \
        f"{bound}" in str(error)


def test_carried_copies_are_refused_after_the_unknown_field_count_and_before_any_object():
    def raw(header_keys: int, *elements):
        header = {"success": True, "error_message": "E" * 2 ** 23}
        header.update({f"futureKey{index}": 1 for index in range(header_keys)})
        return message(*elements, header=header)
    keyed = force(identity={"int32_identity": 1})
    # 16 385 header keys on two Entities and their two Events are 65 540 carried unknown fields:
    # that count refuses (32 769 keys on the two Entities alone until 2026-10-06, when the Events
    # came to carry them too).
    refused("too-many-unknown-fields", raw(16_385, keyed, keyed))
    # One fewer key passes the count, and the 8 Mi error_message on two Entities fails the
    # carried bound.
    calls: list[int] = []

    def clock() -> dt.datetime:
        calls.append(1)
        return FROZEN
    # The second element has no identity, which the adapter refuses while building objects:
    # the carried bound refuses first, before the clock is read for the first object.
    with pytest.raises(TacticalapiRefused) as caught:
        TacticalapiAdapter(clock=clock).to_cdm(raw(16_384, keyed, {"callsign": "EXERCISE"}))
    assert caught.value.code == "carried-copies-too-large"
    assert calls == []


def test_the_carried_copy_bound_is_declared_beside_max_objects_and_in_the_limitation():
    limits = TacticalapiAdapter.metadata.capabilities.limits
    basis = limits.declared_because["max_objects"]
    assert "`MAX_CARRIED_COPY_CHARS` (16 777 216)" in basis.source
    assert "`carried-copies-too-large`" in basis.enforced_at
    by_id = {entry.id: entry.summary for entry in TacticalapiAdapter.metadata.limitations}
    assert "`MAX_CARRIED_COPY_CHARS` (16 777 216 characters" in by_id["resource-limits"]
    assert "a tag written in more than five octets" in by_id["non-canonical-encoding-refused"]


# ====================================================== final verification: what each Entity owns


def test_every_entity_owns_the_containers_it_carries():
    """The record §5.9: changing one Entity's residual or typed block changes no other Entity,
    no other place in the same Entity, and not the input. All Entities of a message shared the
    message-level residual containers, and an unknown key's value was one object at its path
    and in `unknown`."""
    document = message(
        force(futureElement={"a": [1]}, point_location={**at(), "futureKey": {"b": []}}),
        force(identity={"int32_identity": 2}),
        header={"success": True, "error_message": "EXERCISE", "futureHeader": [{"c": 1}]},
        futureTop={"d": [2]}, **{"@unknown": [{"number": 9, "wire_type": 0, "hex": "01"}]})
    pristine = copy.deepcopy(document)
    first, first_event, second, second_event = adapter().to_cdm(document)
    untouched = harness._dump([first_event, second, second_event])
    data = first.residual.data
    assert [entry.get("key", entry.get("number")) for entry in data["unknown"]] == [
        "futureHeader", "futureTop", 9, "futureKey", "futureElement"]
    assert data["unknown"][1]["value"] is not data["response"]["futureTop"]
    assert data["unknown"][4]["value"] is not data["blue_force"]["futureElement"]
    data["response"]["futureTop"]["d"].append(3)
    data["response"]["header"]["futureHeader"][0]["c"] = 9
    data["response"]["@unknown"][0]["hex"] = "ff"
    data["unknown"][0]["value"].append("changed")
    data["unknown"][2]["hex"] = "ff"
    data["blue_force"]["futureElement"]["a"].append(9)
    data["blue_force"]["point_location"]["futureKey"]["b"].append(9)
    block = first.attributes["tacticalapi"]
    block["message"]["header"]["error_message"] = "changed"
    block["blue_force"]["identity"]["string_identity"] = "changed"
    assert harness._dump([first_event, second, second_event]) == untouched
    assert document == pristine
    assert data["unknown"][1]["value"] == {"d": [2]}
    assert data["unknown"][4]["value"] == {"a": [1]}
    # Each Event owns its residual too (since 2026-10-06, the record §5.9): changing one changes
    # no other Event, no Entity and not the input.
    others = harness._dump([second, second_event])
    carried = first_event.residual.data
    assert carried["unknown"][1]["value"] is not carried["response"]["futureTop"]
    carried["response"]["futureTop"]["d"].append(4)
    carried["response"]["header"]["futureHeader"][0]["c"] = 8
    carried["unknown"][0]["value"].append("changed")
    assert harness._dump([second, second_event]) == others
    assert document == pristine
    assert carried["unknown"][1]["value"] == {"d": [2]}


def test_entities_translated_from_bytes_own_their_residuals_too():
    first, first_event, second, second_event = adapter().to_cdm(
        payload("cases/unknown_field_carried"))
    untouched = harness._dump([first_event, second, second_event])
    first.residual.data["response"]["header"]["@unknown"][0]["hex"] = "ff"
    first.residual.data["response"]["@unknown"].clear()
    first.residual.data["unknown"][0]["hex"] = "ff"
    assert harness._dump([first_event, second, second_event]) == untouched
    # And each Event its own (since 2026-10-06).
    first_event.residual.data["response"]["@unknown"].clear()
    first_event.residual.data["unknown"][0]["hex"] = "ff"
    assert harness._dump([second, second_event]) == untouched[1:]


# ================================================== final verification: event ids, refusal text


def test_two_elements_with_one_identity_at_one_instant_share_an_event_id():
    """The record §5.8: one report of one blue force at one instant. The adapter neither
    disambiguates the two nor merges them; both are emitted, in order. The instant is the one
    rendered, so nanoseconds below the millisecond do not tell two reports apart."""
    late = {**at(57.31, 21.52), "location_time": "2026-09-29T07:00:00.000000500Z"}
    objects = dump(message(force(point_location=at(57.3, 21.5)), force(point_location=late)))
    assert [obj["object_kind"] for obj in objects] == ["entity", "event", "entity", "event"]
    first, second = entities(objects)
    one, two = events(objects)
    external = "string_identity:EXERCISE-T-1"
    assert first["entity_id"] == second["entity_id"] == str(ids.derive(
        "TacticalAPI", external, kind="entity"))
    assert one["event_id"] == two["event_id"] == str(ids.derive(
        "TacticalAPI", f"{external}@2026-09-29T07:00:00.000Z", kind="event"))
    assert (one["geometry"]["coordinates"], two["geometry"]["coordinates"]) == (
        [21.5, 57.3], [21.52, 57.31])


def test_an_adapter_refusal_quotes_a_huge_value_briefly():
    """The record §3.2: the adapter's refusals quote what they read through the codec's helper,
    so a 4 MiB error_message is not a 4 MiB refusal."""
    huge = "EXERCISE " * (2 ** 22 // 9)
    error = refused("response-not-successful", message(force(), header={"error_message": huge}))
    assert len(str(error)) <= 400 and str(error).isprintable()
    assert "more characters)" in str(error)
    raw = pw.any_of(pw.field_len(1, pw.field_len(2, pw.field_len(1, huge.encode("ascii"))))
                    + KEYED)
    assert len(str(refused("response-not-successful", raw))) <= 400
    # A type_url filling the declared bound reaches the codec (the base class admits it) and is
    # quoted once.
    url = b"a/" + b"b" * (codec.MAX_INPUT_BYTES - 7)
    at_bound = b"\x0a" + pw.varint(len(url)) + url
    assert len(at_bound) == codec.MAX_INPUT_BYTES
    assert len(str(refused("unsupported-message-type", at_bound))) <= 400


def test_the_base_class_reads_a_91_octet_type_url_as_json_too():
    """The record §2.1 and "Changes", adapter stage, item 3, for the other length: a 91-octet
    type_url makes the payload begin `\\n[`. The prefix before the '/' holds at most 41 octets,
    so here it takes the payload's later octets, a callsign of thirty '[', to nest past 64; the
    host measures the octets as JSON text and refuses what the decoder reads."""
    name = b"rheinmetall.tactical_api.v0.GetBlueForcesResponse"
    url = b"[" * 41 + b"/" + name
    assert len(url) == 91
    for callsign, translates in ((b"[" * 30, False), (b"x" * 30, True)):
        element = (pw.field_len(1, pw.field_varint(3, 7))
                   + pw.field_len(3, pw.field_len(1, callsign)))
        raw = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element), url)
        assert raw[:2] == b"\x0a\x5b" and len(codec.decode(raw)["blue_forces"]) == 1
        depth = json_nesting_depth(raw.decode("utf-8"))
        assert depth == (72 if not translates else 42)
        if translates:
            assert len(adapter().to_cdm(raw)) == 2
        else:
            with pytest.raises(InputTooDeep) as caught:
                adapter().to_cdm(raw)
            assert "nesting 72 containers deep" in str(caught.value)


# ================================ final verification, 2026-10-04: the second review's findings
#
# Each test below names the finding it holds (the record "Changes", final verification, items 11
# to 30) and fails on the tree the second review read.


ERROR_TEXT = "EXERCISE partial: 3 units unreachable"


def test_a_successful_empty_response_with_an_error_message_is_refused_by_name():
    """robustness-1 / mapping-1 (item 11): the text was dropped without a word; it is refused
    `error-message-without-carrier`, in both forms, with the text quoted."""
    for raw in (payload("cases/error_message_without_carrier"),
                twin_file("cases/error_message_without_carrier"),
                message(header={"success": True, "error_message": ERROR_TEXT}),
                message(header={"success": True, "error_message": ERROR_TEXT}, url=SUBSCRIBE)):
        error = refused("error-message-without-carrier", raw)
        assert codec.quote(ERROR_TEXT) in str(error) and "no blue force" in str(error)
        assert adapter().detect(raw) is True
        assert adapter().validate_source(raw) == [f"TacticalapiRefused: {error}"]
    assert twin_file("cases/error_message_without_carrier") == codec.decode(
        payload("cases/error_message_without_carrier"))


def test_an_empty_error_message_on_an_empty_response_holds_no_text_and_is_still_an_empty_list():
    """Item 11: an error_message present and empty is no text to carry, in either form."""
    present_empty = pw.any_of(pw.field_len(1, b"\x08\x01" + pw.field_len(2, b"")))
    assert codec.decode(present_empty)["header"] == {"success": True, "error_message": ""}
    for raw in (present_empty, message(header={"success": True, "error_message": ""})):
        assert adapter().to_cdm(raw) == []
        assert adapter().validate_source(raw) == []


def test_the_message_level_refusals_come_in_the_stated_order():
    """The record §4: success first, then unknown fields, then the error message."""
    refused("response-not-successful", message(header={"success": False,
                                                       "error_message": ERROR_TEXT}))
    refused("unknown-fields-without-carrier",
            message(header={"success": True, "error_message": ERROR_TEXT, "futureKey": 1}))
    refused("unknown-fields-without-carrier",
            message(header={"success": True, "error_message": ERROR_TEXT},
                    **{"@unknown": [{"number": 9, "wire_type": 0, "hex": "01"}]}))
    refused("error-message-without-carrier",
            message(header={"success": True, "error_message": ERROR_TEXT}))


def test_an_error_message_without_a_carrier_is_quoted_briefly():
    huge = "EXERCISE " * (2 ** 22 // 9)
    error = refused("error-message-without-carrier",
                    message(header={"success": True, "error_message": huge}))
    assert len(str(error)) <= 400 and str(error).isprintable()
    assert "more characters)" in str(error)


def test_a_nested_type_key_is_carried_at_its_own_path_and_listed():
    """robustness-2 / mapping-4 (item 12): `@type` in the header, an element and a geo_point is
    a key the contract does not name. It was listed and left out of its own path, so the ledger
    lost it; an element whose only unknown key it was had no `blue_force` member at all."""
    document = message(
        force(**{"@type": "EXERCISE element"},
              point_location={**at(), "geo_point": {"latitude_coordinate": 57.25,
                                                    "@type": "EXERCISE geo"}}),
        force(identity={"int32_identity": 2}, **{"@type": "EXERCISE only"}),
        header={"success": True, "@type": "EXERCISE header"})
    first, second = entities(dump(document))
    assert first["residual"]["data"]["response"] == {"header": {"@type": "EXERCISE header"}}
    assert first["residual"]["data"]["blue_force"] == {
        "point_location": {"geo_point": {"@type": "EXERCISE geo"}}, "@type": "EXERCISE element"}
    assert second["residual"]["data"]["blue_force"] == {"@type": "EXERCISE only"}
    assert [(entry["path"], entry["key"]) for entry in first["residual"]["data"]["unknown"]] == [
        ("header", "@type"), ("blue_forces[0].point_location.geo_point", "@type"),
        ("blue_forces[0]", "@type")]
    book = lossless.ledger(document, dump(document), TacticalapiAdapter.MAPPINGS)
    assert book.lost == (), book.problem_lines()
    assert book.counts["RESIDUAL"] >= 4
    # The response's own @type is the envelope's type_url and stays out of the residual.
    assert "@type" not in first["residual"]["data"]["response"]


class Text(str, enum.Enum):
    """The standard `(str, Enum)` idiom: `str()` of a member is `Text.NAME`, not its text."""

    URL = GET
    IDENTITY = "EXERCISE ALPHA"
    CATALOG = "SYMBOL_CATALOG_MIL2525_C"
    SYMBOL = "SFGPEVC--------"
    STAMP = "2026-09-29T07:00:00.500Z"
    NOTE = "note"
    WIDE = "9007199254740993"


class Loud(str):
    """A str subclass whose own `__str__` says something else."""

    def __str__(self) -> str:
        return "LOUD"


class Twice(int):
    def __int__(self) -> int:
        return 2 * int.__int__(self)


class Half(float):
    def __float__(self) -> float:
        return float.__float__(self) / 2


def test_subclass_values_translate_as_the_plain_values_they_hold():
    """robustness-3 (item 13): plain values are taken with the base type's own conversion, so
    a `(str, Enum)` member given for a string field, an enum name, `@type`, a Timestamp, an
    int64 text and an unknown key, and subclasses overriding `__str__`, `__int__` or
    `__float__`, translate exactly as the plain values that compare equal to them."""
    def document(text, url, catalog, stamp, note, wide, number, real, loud):
        return {"@type": url, "header": {"success": True, "error_message": loud},
                "blue_forces": [
                    {"identity": {"string_identity": text}, "callsign": text,
                     "symbol": {"symbol_catalog": catalog, "string_identifier": Text.SYMBOL},
                     "point_location": {"location_time": stamp,
                                        "geo_point": {"latitude_coordinate": real,
                                                      "longitude_coordinate": 21.5},
                                        "speed": real},
                     "mount_host": {"int64_identity": wide}, note: loud},
                    {"identity": {"int32_identity": number}}]}
    given = document(Text.IDENTITY, Text.URL, Text.CATALOG, Text.STAMP, Text.NOTE, Text.WIDE,
                     Twice(7), Half(57.25), Loud("EXERCISE LOUD"))
    plain = document("EXERCISE ALPHA", GET, "SYMBOL_CATALOG_MIL2525_C",
                     "2026-09-29T07:00:00.500Z", "note", "9007199254740993", 7, 57.25,
                     "EXERCISE LOUD")
    assert given == plain
    assert canonical.serialise(dump(given)) == canonical.serialise(dump(plain))
    first = entities(dump(given))[0]
    assert first["source_ids"][0]["external_id"] == "string_identity:EXERCISE ALPHA"
    assert first["residual"]["data"]["blue_force"] == {"note": "EXERCISE LOUD"}
    assert adapter().detect(given) is True


class Hashed(str):
    """A key that hashes otherwise than its text, so a dict can hold it beside the plain key."""

    def __hash__(self) -> int:
        return 7

    def __eq__(self, other) -> bool:
        return self is other


def test_two_keys_holding_one_text_are_refused_rather_than_one_dropped():
    """Item 13: made plain, two keys of one object would be one; the adapter refuses rather
    than keep one of them."""
    def with_keys(*pairs) -> dict:
        element = {"identity": {"string_identity": "EXERCISE-T-1"}}
        for key, value in pairs:
            element[key] = value
        return message(element)
    for document in (
        with_keys(("callsign", "EXERCISE A"), (Hashed("callsign"), "EXERCISE B")),
        with_keys(("futureKey", 1), (Hashed("futureKey"), 2)),
        with_keys(("futureKey", {"a": 1, Hashed("a"): 2})),
        {**message(force()), Hashed("@type"): GET},
    ):
        error = refused("invalid-twin-value", document)
        assert "twice" in str(error)


def test_detect_finds_the_type_key_by_its_text_as_to_cdm_does():
    """N4 (item 35): `detect` looked `@type` up with `raw.get`, which misses a key that hashes
    otherwise than its text, while `to_cdm` reads keys by their text and translated the dict.
    The two read the type through one function now, and agree on each input below."""
    keyed = {Hashed("@type"): GET, "header": {"success": True}, "blue_forces": [force()]}
    assert keyed.get("@type") is None
    assert adapter().detect(keyed) is True
    assert len(adapter().to_cdm(keyed)) == 2
    twice = {**message(force()), Hashed("@type"): GET}
    assert adapter().detect(twice) is False
    refused("invalid-twin-value", twice)
    assert adapter().detect(message(force(), url=Text.URL)) is True
    surrogate = message(force(), url=GET.replace("/", "\ud800/"))
    assert adapter().detect(surrogate) is False
    refused("invalid-utf8", surrogate)
    assert adapter().detect({"@type": None}) is False
    refused("null-in-twin", {"@type": None})


def test_an_integer_outside_the_64_bit_range_under_an_unknown_key_is_refused():
    """robustness-4 (a) / robustness-11 (item 14): such an integer was carried, and the Entity
    could then be neither written by `json.dumps` nor read back."""
    for value in (2 ** 64, -(2 ** 63) - 1, 10 ** 5000, [1, {"deep": [2 ** 70]}]):
        error = refused("invalid-twin-value", message(force(futureKey=value)))
        assert "outside -2^63" in str(error) and len(str(error)) <= 400
    for value in (2 ** 64 - 1, -(2 ** 63), [0, {"deep": [2 ** 63]}]):
        entity = only_entity(message(force(futureKey=value)))
        assert entity["residual"]["data"]["blue_force"] == {"futureKey": value}
        json.loads(json.dumps(entity))


def test_a_deleted_report_and_a_live_one_at_one_instant_have_two_event_ids():
    """mapping-2 (item 15): the deletion of a blue force that stated the same times as its last
    live report got that report's event id. A deleted element's input ends `#is_deleted`."""
    stated = {"last_contact_time": "2026-09-29T06:14:30Z"}
    live = dump(message(force(**stated), url=SUBSCRIBE))[1]
    dead = dump(message(force(**stated, is_deleted=True), url=SUBSCRIBE))[1]
    external = "string_identity:EXERCISE-T-1"
    assert (live["event_type"], dead["event_type"]) == ("TRACK_UPDATE", "STATUS_CHANGE")
    assert live["observed_at"] == dead["observed_at"] == "2026-09-29T06:14:30.000Z"
    assert live["event_id"] == str(ids.derive(
        "TacticalAPI", f"{external}@2026-09-29T06:14:30.000Z", kind="event"))
    assert dead["event_id"] == str(ids.derive(
        "TacticalAPI", f"{external}@2026-09-29T06:14:30.000Z#is_deleted", kind="event"))
    assert live["event_id"] != dead["event_id"]
    assert "#is_deleted" in dead["payload"]["event_id_basis"]
    assert "#is_deleted" not in live["payload"]["event_id_basis"]
    # The delta fixture's deletion: its id is the suffixed one, and its live element's is not.
    deleted = dump(payload("delta_with_deletion"))[3]
    assert deleted["event_id"] == str(ids.derive(
        "TacticalAPI", "string_identity:EXERCISE-VEH-201@2026-09-29T06:14:30.000Z#is_deleted",
        kind="event"))


ZERO = "1970-01-01T00:00:00Z"


@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_zero_location_time_beside_a_real_last_contact_time_is_passed_over(form):
    """mapping-3 (item 16): a present Timestamp of seconds 0 and nanos 0 was valid_from
    1970-01-01 and took precedence over a real last_contact_time. Bytes: an empty Timestamp
    message on the wire, what a default-constructed one serialises to."""
    if form == "bytes":
        element = (pw.field_len(1, pw.field_len(2, b"EXERCISE-T-1"))
                   + pw.field_len(2, pw.field_varint(1, 1790663460))
                   + pw.field_len(7, pw.field_len(2, b"")))
        raw = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element))
        assert codec.decode(raw)["blue_forces"][0]["point_location"] == {"location_time": ZERO}
    else:
        raw = message(force(last_contact_time="2026-09-29T06:31:00Z",
                            point_location={"location_time": ZERO}))
    entity, event = dump(raw)
    assert entity["valid_from"] == event["observed_at"] == "2026-09-29T06:31:00.000Z"
    basis = entity["attributes"]["valid_from_basis"]
    assert basis == event["payload"]["observed_at_basis"]
    assert basis.startswith("last_contact_time: point_location.location_time is the zero "
                            "Timestamp (1970-01-01T00:00:00Z)")
    assert "proto3-zero-indistinguishable" in basis
    assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"] == {
        "location_time": ZERO}
    assert adapter().validate_source(raw) == [
        f"blue_forces[0].point_location.location_time {module.ZERO_PASSED_OVER}"]


@pytest.mark.parametrize("element,said,zeros", [
    (force(last_contact_time=ZERO, point_location={"location_time": ZERO}),
     "point_location.location_time is the zero Timestamp", ["point_location.location_time",
                                                             "last_contact_time"]),
    (force(point_location={"location_time": "1970-01-01T00:00:00.000Z"}),
     "point_location.location_time is the zero Timestamp", ["point_location.location_time"]),
    (force(last_contact_time="1970-01-01T00:00:00.000000000Z"),
     "point_location.location_time is absent, and last_contact_time is the zero Timestamp",
     ["last_contact_time"]),
])
def test_with_only_zero_timestamps_the_injected_clock_stands_in(element, said, zeros):
    """Item 16: both zero, or the only one stated zero (in any of §2.2's spellings): the
    receipt instant, never 1970, and validate_source names each zero and the missing time."""
    for clock_at in (FROZEN, OTHER):
        entity, event = dump(message(element), clock_at)
        assert entity["valid_from"] == event["observed_at"] == times.render(clock_at)
        basis = entity["attributes"]["valid_from_basis"]
        assert basis == event["payload"]["observed_at_basis"]
        assert basis.startswith("the receipt instant: ") and said in basis
        assert basis.endswith("so the injected clock stands in")
    assert adapter().validate_source(message(element)) == [
        *(f"blue_forces[0].{field} {module.ZERO_PASSED_OVER}" for field in zeros),
        "blue_forces[0]: states no source time but the zero Timestamp; valid_from and "
        "observed_at are the receipt instant from the injected clock"]


def test_the_suites_temporal_check_passes_on_every_zero_timestamp_case():
    """Item 16, held to the host's own reading: the conformance suite's check J failed each of
    these when a zero Timestamp became valid_from 1970-01-01 (§27 of the host package)."""
    from synapse_cdm import suite
    cases = [("zero location, real last contact",
              message(force(last_contact_time="2026-09-29T06:31:00Z",
                            point_location={"location_time": ZERO}))),
             ("both zero", message(force(last_contact_time=ZERO,
                                         point_location={"location_time": ZERO}))),
             ("zero last contact only", message(force(last_contact_time=ZERO))),
             ("awkward_zeros, bytes", payload("awkward_zeros")),
             ("awkward_zeros, twin", twin_file("awkward_zeros"))]
    result = suite.check_temporal(adapter(), cases, clock=times.frozen_clock(),
                                  frozen_at=times.FROZEN_NOW)
    assert result["verdict"] == "PASS", result


def test_a_real_location_time_beside_a_zero_last_contact_time_is_the_source_time():
    entity = only_entity(message(force(last_contact_time=ZERO,
                                       point_location={"location_time": "2026-09-29T07:00:00Z"})))
    assert entity["valid_from"] == "2026-09-29T07:00:00.000Z"
    assert entity["attributes"]["valid_from_basis"] == "point_location.location_time"


def test_the_earliest_timestamp_is_a_stated_time_and_is_reported_once():
    """Item 16: 0001-01-01T00:00:00Z is a value the Timestamp states, not proto3's default; it
    is the source time, and validate_source reports it in one line."""
    raw = message(force(point_location={"location_time": "0001-01-01T00:00:00Z"}))
    entity, event = dump(raw)
    assert entity["valid_from"] == event["observed_at"] == "0001-01-01T00:00:00.000Z"
    assert entity["attributes"]["valid_from_basis"] == "point_location.location_time"
    [line] = adapter().validate_source(raw)
    assert line.startswith("blue_forces[0].point_location.location_time is 0001-01-01T00:00:00Z")


def stamped(nanos: int) -> bytes:
    """A Timestamp message of seconds 0 (absent from the wire, as protobuf writes a zero) and
    `nanos`."""
    return pw.field_varint(2, nanos)


@pytest.mark.parametrize("nanos", [1, 500_000, 999_999])
@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_location_time_less_than_a_millisecond_after_the_epoch_is_the_source_time(form, nanos):
    """N2 (item 33): seconds 0 and nanos 1 … 999 999 is a stated value, not proto3's default,
    so it is the source time, ahead of a real last_contact_time, and renders as the epoch's
    text; validate_source names it in one line. A mutant that passes over every Timestamp of
    seconds 0, whatever its nanos, takes the last_contact_time here and fails."""
    text = codec.render_timestamp(0, nanos, "test")
    if form == "bytes":
        element = (pw.field_len(1, pw.field_len(2, b"EXERCISE-T-1"))
                   + pw.field_len(2, pw.field_varint(1, 1790663460))
                   + pw.field_len(7, pw.field_len(2, stamped(nanos))))
        raw = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element))
        assert codec.decode(raw)["blue_forces"][0]["point_location"] == {"location_time": text}
        assert codec.decode(raw)["blue_forces"][0]["last_contact_time"] == "2026-09-29T06:31:00Z"
    else:
        raw = message(force(last_contact_time="2026-09-29T06:31:00Z",
                            point_location={"location_time": text}))
    entity, event = dump(raw)
    assert entity["valid_from"] == event["observed_at"] == module.EPOCH_TEXT
    assert entity["attributes"]["valid_from_basis"] == event["payload"]["observed_at_basis"] == (
        "point_location.location_time")
    assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"] == {
        "location_time": text}
    assert event["event_id"] == str(ids.derive(
        "TacticalAPI", "string_identity:EXERCISE-T-1@1970-01-01T00:00:00.000Z", kind="event"))
    assert adapter().validate_source(raw) == [
        f"blue_forces[0].point_location.location_time is {text}, {module.BELOW_A_MILLISECOND}"]


@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_a_last_contact_time_less_than_a_millisecond_after_the_epoch_is_the_source_time(form):
    """N2 (item 33), the other field: with no location time it is the source time, never the
    receipt instant; and beside a real location time it is not used but still named."""
    if form == "bytes":
        element = (pw.field_len(1, pw.field_len(2, b"EXERCISE-T-1"))
                   + pw.field_len(2, stamped(1)))
        alone = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element))
        beside = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element + pw.field_len(
            7, pw.field_len(2, pw.field_varint(1, 1790665200)))))
    else:
        alone = message(force(last_contact_time="1970-01-01T00:00:00.000000001Z"))
        beside = message(force(last_contact_time="1970-01-01T00:00:00.000000001Z",
                               point_location={"location_time": "2026-09-29T07:00:00Z"}))
    line = (f"blue_forces[0].last_contact_time is 1970-01-01T00:00:00.000000001Z, "
            f"{module.BELOW_A_MILLISECOND}")
    for clock_at in (FROZEN, OTHER):
        entity, event = dump(alone, clock_at)
        assert entity["valid_from"] == event["observed_at"] == "1970-01-01T00:00:00.000Z"
        assert entity["attributes"]["valid_from_basis"] == (
            "last_contact_time: point_location.location_time is absent")
    assert adapter().validate_source(alone) == [line]
    entity = only_entity(beside)
    assert entity["valid_from"] == "2026-09-29T07:00:00.000Z"
    assert entity["attributes"]["valid_from_basis"] == "point_location.location_time"
    assert adapter().validate_source(beside) == [line]


def test_the_suites_temporal_check_cannot_tell_a_sub_millisecond_time_from_an_unknown_one():
    """N2 (item 33), recorded as the record §5.3 states it: the output is the epoch's text, and
    the host's check J reports it as it would an unknown time made 1970-01-01. One millisecond
    is the first instant whose text is not the epoch's."""
    from synapse_cdm import suite

    def checked(text: str) -> dict:
        case = message(force(point_location={"location_time": text}))
        return suite.check_temporal(adapter(), [(text, case)], clock=times.frozen_clock(),
                                    frozen_at=times.FROZEN_NOW)
    below = checked("1970-01-01T00:00:00.000999999Z")
    assert below["verdict"] == "FAIL"
    assert "forbids an unknown time becoming 1970-01-01" in json.dumps(below)
    assert checked("1970-01-01T00:00:00.001Z")["verdict"] == "PASS"
    # And validate_source has nothing to say from the first millisecond on.
    for text in ("1970-01-01T00:00:00.001Z", "1970-01-01T00:00:01Z"):
        assert adapter().validate_source(message(force(
            point_location={"location_time": text}))) == [], text


def test_the_awkward_zeros_fixture_holds_a_zero_location_time_and_no_1970_instant():
    for raw in (payload("awkward_zeros"), twin_file("awkward_zeros")):
        objects = dump(raw)
        assert len(objects) == 4
        assert "1970-01-01T00:00:00.000Z" not in canonical.serialise(objects)
        second = entities(objects)[1]
        assert second["valid_from"] == "2026-09-29T06:31:00.000Z"
        assert second["attributes"]["tacticalapi"]["blue_force"]["point_location"][
            "location_time"] == ZERO


def test_the_event_id_instant_is_written_by_the_adapter_with_a_four_digit_year():
    """mapping-5 (item 17): the id's instant does not go through `strftime`."""
    utc = dt.timezone.utc
    assert module._id_instant(dt.datetime(1, 1, 1, tzinfo=utc)) == "0001-01-01T00:00:00.000Z"
    assert module._id_instant(dt.datetime(999, 12, 31, 23, 59, 59, 999_999, tzinfo=utc)) == (
        "0999-12-31T23:59:59.999Z")
    assert module._id_instant(dt.datetime(2026, 9, 29, 7, 0, 0, 500_000, tzinfo=utc)) == (
        times.render(dt.datetime(2026, 9, 29, 7, 0, 0, 500_000, tzinfo=utc)))
    # Another zone is read as its UTC instant.
    plus_two = dt.timezone(dt.timedelta(hours=2))
    assert module._id_instant(dt.datetime(2026, 9, 29, 9, 0, tzinfo=plus_two)) == (
        "2026-09-29T07:00:00.000Z")
    for text, stamp in (("0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000Z"),
                        ("0999-12-31T23:59:59.999999999Z", "0999-12-31T23:59:59.999Z")):
        _, event = dump(message(force(point_location={"location_time": text})))
        assert event["event_id"] == str(ids.derive(
            "TacticalAPI", f"string_identity:EXERCISE-T-1@{stamp}", kind="event"))


def test_the_base_class_reads_a_payload_with_a_1_491_650_octet_type_url_as_json_too():
    """robustness-7 (item 19): the length varint c2 85 5b decodes to U+0085, white space to
    `str.lstrip`, and then `[`; so the host reads the payload as JSON text whatever the
    type_url holds, and refuses it when its prefix nests past the bound."""
    name = b"rheinmetall.tactical_api.v0.GetBlueForcesResponse"
    length = 1_491_650
    assert pw.varint(length) == b"\xc2\x85\x5b"
    element = pw.field_len(1, pw.field_varint(3, 7))
    for opener, translates in ((b"[", False), (b"x", True)):
        url = opener * 70 + b"x" * (length - 70 - 1 - len(name)) + b"/" + name
        raw = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, element), url)
        assert raw[:4] == b"\x0a\xc2\x85\x5b" and len(codec.decode(raw)["blue_forces"]) == 1
        if translates:
            assert len(adapter().to_cdm(raw)) == 2
        else:
            with pytest.raises(InputTooDeep):
                adapter().to_cdm(raw)


class Mute:
    """An in-process value whose repr raises."""

    def __repr__(self) -> str:
        raise RuntimeError("EXERCISE no repr")


def test_a_value_whose_repr_raises_is_still_refused_by_name():
    """robustness-9 (item 20): `quote` caught only ValueError, so this left `to_cdm` as a
    RuntimeError; it is described by its type and the refusal is the one raised."""
    error = refused("invalid-twin-value", message(header={"success": Mute()}))
    assert "a Mute whose repr raised RuntimeError" in str(error)
    assert adapter().validate_source(message(header={"success": Mute()}))[0].startswith(
        "TacticalapiRefused: invalid-twin-value: ")


def test_a_str_holding_a_lone_surrogate_meets_the_hosts_measure_first():
    """Item 20, recorded: the host measures a `str` as UTF-8 before this adapter runs, so one
    holding a lone surrogate raises UnicodeEncodeError there (the record, opening paragraph);
    the codec itself refuses any str as not the envelope."""
    with pytest.raises(UnicodeEncodeError):
        adapter().to_cdm("\ud800")
    with pytest.raises(TacticalapiRefused) as caught:
        codec.twin_of("\ud800")
    assert caught.value.code == "not-an-any-envelope"


def test_each_entity_and_each_event_owns_its_provenance_stamp():
    """robustness-12 (item 22): an Entity and its Event held one SourceRef, and all the stamps
    of a message one `transformations` list. Equal values, separate objects."""
    objects = adapter().to_cdm(payload("snapshot_three_forces"))
    stamps = [obj.source for obj in objects]
    assert len({id(stamp) for stamp in stamps}) == len(objects) == 6
    assert len({id(stamp.transformations) for stamp in stamps}) == 6
    assert [stamp.record_index for stamp in stamps] == [0, 0, 1, 1, 2, 2]
    untouched = harness._dump(objects[1:])
    objects[0].source.transformations.append("EXERCISE note on Entity 0 only")
    objects[0].source.record_index = 4242
    assert harness._dump(objects[1:]) == untouched
    assert objects[1].source.record_index == 0 and objects[1].source.transformations == []


def test_the_other_responses_list_name_is_an_unknown_key_carried_at_its_path():
    """robustness-13 (item 23): in a GetBlueForcesResponse, `updated_blue_forces` is a key this
    message's contract does not name: carried at its path and listed. (The ledger, which binds
    both list names for every message, reads it as lost; the record records that reading.)"""
    other = [{"identity": {"string_identity": "EXERCISE-OTHER"}, "is_deleted": False}]
    document = message(force(), updated_blue_forces=other)
    entity = only_entity(document)
    assert entity["residual"]["data"]["response"] == {"updated_blue_forces": other}
    assert entity["residual"]["data"]["unknown"] == [
        {"path": "", "key": "updated_blue_forces", "value": other}]
    assert adapter().validate_source(document)[0] == (
        "the response: key 'updated_blue_forces' is not a field the pinned contract names; "
        "carried in the residual")


def test_validate_source_lines_are_bounded_like_refusals():
    """robustness-14 (item 24): a mebibyte key made a line of a mebibyte."""
    key = "k" * 2 ** 20
    lines = adapter().validate_source(message(force(**{key: 1})))
    assert lines and all(len(line) <= 400 and line.isprintable() for line in lines)
    assert "more characters)" in lines[0]
    [line] = adapter().validate_source(message(force(point_location=at(), **{"a\nb": 1})))
    assert "'a\\nb'" in line and line.isprintable()


class TwoLines(str):
    """A str subclass that writes itself as two long lines wherever it is formatted."""

    def __str__(self) -> str:
        return "line one\nline two " + "z" * 5000


class ReprTwoLines:
    """An in-process value whose `__repr__` returns a `TwoLines`, which `repr` accepts."""

    def __repr__(self) -> str:
        return TwoLines("short")


LONG_NAMED = type("N" * 100_000, (), {})
BREAK_NAMED = type("a\nb", (), {})


def test_a_refusal_naming_an_in_process_object_is_one_bounded_printable_line():
    """N3 (item 34), the three cases the review showed and the input itself: a repr that is a
    str subclass formatting itself as two long lines (given for a bool), an object of a class
    with a 100 000-character name (under an unknown key), and one whose class name holds a line
    break (given for a Timestamp, and as the whole input). Each refusal, and the
    validate_source line that repeats it, is one printable line of a few hundred characters."""
    for code, raw in (("invalid-twin-value", message(force(), header={"success": ReprTwoLines()})),
                      ("invalid-twin-value", message(force(futureKey=LONG_NAMED()))),
                      ("invalid-twin-value", message(force(last_contact_time=BREAK_NAMED()))),
                      ("not-an-any-envelope", BREAK_NAMED())):
        error = refused(code, raw)
        assert str(error).isprintable() and len(str(error)) <= 400, str(error)[:300]
        assert adapter().validate_source(raw) == [f"TacticalapiRefused: {error}"]
    text = str(refused("invalid-twin-value", message(force(), header={"success": ReprTwoLines()})))
    assert "header.success is short; " in text and "line one" not in text
    assert "the input is a a\\nb; " in str(refused("not-an-any-envelope", BREAK_NAMED()))


def test_validate_source_names_the_class_of_what_it_caught_through_quote_type(monkeypatch):
    """N3 (item 34): the one type name `validate_source` writes itself, the class of what
    `to_cdm` raised, goes through `quote_type` like every type name a refusal writes. No input
    of either form reaches `to_cdm` with such a class, so the codec's entry is replaced."""
    oddly_named = type("Odd\n" + "e" * 1000, (ValueError,), {})

    def raise_it(raw, **limits):
        raise oddly_named("EXERCISE")
    monkeypatch.setattr(codec, "twin_of", raise_it)
    [line] = adapter().validate_source(message(force()))
    assert line == f"{codec.quote_type(oddly_named())}: EXERCISE"
    assert line.isprintable() and len(line) <= 200 and line.startswith("Odd\\neee")


@pytest.mark.parametrize("catalog,length,reported", [
    ("SYMBOL_CATALOG_APP6_B", 14, True), ("SYMBOL_CATALOG_MIL2525_C", 16, True),
    ("SYMBOL_CATALOG_MIL2525_C", 15, False), ("SYMBOL_CATALOG_RME", 22, False),
    ("SYMBOL_CATALOG_APP6_D", 14, False), ("SYMBOL_CATALOG_MIL2525_E", 3, False),
])
def test_the_string_length_is_reported_only_under_the_catalogs_the_contract_ties_it_to(
        catalog, length, reported):
    """mapping-12 (item 26): the contract states 15 characters for APP6-B and 2525C only."""
    symbol = {"symbol_catalog": catalog, "string_identifier": "S" * length}
    lines = adapter().validate_source(message(force(point_location=at(), symbol=symbol)))
    named = [line for line in lines if "string_identifier is" in line]
    assert named == ([f"blue_forces[0].symbol.string_identifier is {length} characters; the "
                      "contract's string form is 15 (reported, not enforced)"] if reported else [])


@pytest.mark.parametrize("catalog", [
    "SYMBOL_CATALOG_MIL2525_D", "SYMBOL_CATALOG_APP6_E", "SYMBOL_CATALOG_UNSPECIFIED", 42, None])
def test_no_length_is_reported_under_2525d_app6_e_unspecified_an_unnamed_number_or_none(catalog):
    """N5 (mapping-new-2): the catalogs the test above leaves out, each with a 14-character
    string: 2525D (whose string form is not promoted either), APP6-E, UNSPECIFIED, a number the
    contract does not name, and no catalog on the wire. A mutant that adds 2525D to the two
    catalogs the contract ties the length to passed every test."""
    symbol = {"string_identifier": "S" * 14}
    if catalog is not None:
        symbol["symbol_catalog"] = catalog
    lines = adapter().validate_source(message(force(point_location=at(), symbol=symbol)))
    assert [line for line in lines if "string_identifier is" in line] == []
    assert len(lines) == 1 and lines[0].startswith("blue_forces[0].symbol: not promoted: ")


@pytest.mark.parametrize("text", ["0001-01-01T00:00:01Z", "0001-01-01T00:00:00.001Z",
                                  "0001-01-01T00:00:00.000000001Z", "0001-01-01T23:59:59Z"])
def test_only_the_earliest_instant_itself_is_reported(text):
    """N5 (mapping-new-2): the 0001-01-01T00:00:00Z line is for that one instant, not for any
    time of the first day of year 1; each of these is a source time with nothing to report. A
    mutant that reported every time of that day passed every test."""
    raw = message(force(point_location={"location_time": text}))
    assert only_entity(raw)["attributes"]["valid_from_basis"] == "point_location.location_time"
    assert adapter().validate_source(raw) == []


def test_an_identity_is_keyed_verbatim_so_uuid_letter_case_makes_two_entities():
    """mapping-7 (item 27): nothing is case-folded; an upper-case uuid_identity is its own key."""
    lower = "7e0789f0-8823-5bcb-b121-3278650b625b"
    upper = only_entity(message(force(identity={"uuid_identity": lower.upper()})))
    plain = only_entity(message(force(identity={"uuid_identity": lower})))
    assert upper["source_ids"] == [{"system": "TacticalAPI",
                                    "external_id": f"uuid_identity:{lower.upper()}"}]
    assert upper["entity_id"] == str(ids.derive("TacticalAPI", f"uuid_identity:{lower.upper()}",
                                                kind="entity"))
    assert upper["entity_id"] != plain["entity_id"]
    assert upper["attributes"]["tacticalapi"]["blue_force"]["identity"] == {
        "uuid_identity": lower.upper()}
    padded = only_entity(message(force(identity={"string_identity": " EXERCISE-T-1 "})))
    assert padded["source_ids"][0]["external_id"] == "string_identity: EXERCISE-T-1 "


def test_mapping_states_the_record_index_and_the_events_source_ids():
    """mapping-10 (item 28): the code stamped both from the start and §5.8 named neither."""
    mapping = RECORD.read_text(encoding="utf-8")
    section = mapping.split("### 5.8 Event", 1)[1].split("### 5.9", 1)[0]
    assert "`source.record_index`" in section and "`source_ids`" in section
    objects = dump(payload("snapshot_three_forces"))
    for index, (entity, event) in enumerate(zip(objects[0::2], objects[1::2])):
        assert event["source"]["record_index"] == entity["source"]["record_index"] == index
        assert event["source_ids"] == entity["source_ids"]


def test_the_measurement_code_wording_is_the_adapters_own():
    """licence-14 (item 30): the nearest echo of a contract comment, a run of its words about
    the ESTIMATE code, is gone from the specification and the module."""
    echo = " ".join(("estimated", "manually"))
    for path in (RECORD, MODULE_SOURCE):
        assert echo not in path.read_text(encoding="utf-8"), path


# ============================== final verification, 2026-10-04, fix stage B: the test gaps
#
# The shipped code was right on each input below and no test held it: a mutant that changed the
# value passed every test, the harness and the suite. Each test names the finding and the mutant
# it fails.


@pytest.mark.parametrize("url", [GET, SUBSCRIBE])
def test_an_unsuccessful_response_with_no_blue_force_is_refused_not_an_empty_list(url):
    """robustness-5 (mutant M15, success checked only when there are elements): the record §4
    refuses an absent header, an absent `success` or `false` before its empty-list row, and a
    failed call that returns no blue force is the ordinary shape of a failure. Each is refused
    `response-not-successful` in both forms, with and without an error_message, never `[]`."""
    said = "EXERCISE the server failed"
    stated = pw.field_len(2, pw.field_len(1, said.encode()))
    for header, twin_header, phrase in (
        (pw.field_varint(1, 0), {"success": False}, "header.success is false"),
        (pw.field_varint(1, 0) + stated, {"success": False, "error_message": said},
         "header.success is false"),
        (b"", {}, "header.success is absent from the wire, which reads false"),
        (stated, {"error_message": said},
         "header.success is absent from the wire, which reads false"),
        (None, None, "the response has no header"),
    ):
        octets = pw.any_of(b"" if header is None else pw.field_len(1, header), url.encode())
        document = {"@type": url} if twin_header is None else {"@type": url, "header": twin_header}
        assert codec.decode(octets) == document
        for raw in (octets, document):
            error = refused("response-not-successful", raw)
            assert phrase in str(error)
            assert (codec.quote(said) in str(error)) is ("error_message" in (twin_header or {}))
            assert adapter().validate_source(raw) == [f"TacticalapiRefused: {error}"]


@pytest.mark.parametrize("text", ["2026-04-29T06:15:00.999999500Z",
                                  "2026-04-29T06:15:00.999999999Z",
                                  "2026-04-29T06:15:00.999500Z"])
def test_a_source_time_is_truncated_to_the_millisecond_never_rounded_up(text):
    """robustness-6 (mutant M23, nanoseconds rounded to microseconds): the record §5.3 and §5.8
    write the instant to the millisecond, truncated. Rounded, .999999500 would carry into the
    next second and move valid_from, observed_at and the event id with it."""
    entity, event = dump(message(force(identity={"int32_identity": 7}, last_contact_time=text)))
    assert entity["valid_from"] == event["observed_at"] == "2026-04-29T06:15:00.999Z"
    assert event["event_id"] == str(ids.derive(
        "TacticalAPI", "int32_identity:7@2026-04-29T06:15:00.999Z", kind="event"))
    assert entity["attributes"]["tacticalapi"]["blue_force"]["last_contact_time"] == text


#: Every catalog the contract names but SYMBOL_CATALOG_MIL2525_D, restated by contract value name.
OTHER_CATALOGS = ["SYMBOL_CATALOG_UNSPECIFIED", "SYMBOL_CATALOG_RME", "SYMBOL_CATALOG_APP6_B",
                  "SYMBOL_CATALOG_APP6_D", "SYMBOL_CATALOG_MIL2525_C", "SYMBOL_CATALOG_APP6_E",
                  "SYMBOL_CATALOG_MIL2525_E"]


def test_the_other_catalogs_are_every_named_catalog_but_2525d():
    named = set(codec.ENUMS["rheinmetall.tactical_api.v0.SymbolCatalog"].values())
    assert set(OTHER_CATALOGS) == named - {"SYMBOL_CATALOG_MIL2525_D"}
    assert len(OTHER_CATALOGS) == len(named) - 1


@pytest.mark.parametrize("catalog", OTHER_CATALOGS)
def test_an_in_range_numeric_code_under_any_other_catalog_is_not_promoted(catalog):
    """robustness-6 (mutant M39, a SYMBOL_CATALOG_MIL2525_E code promoted too): the record §5.4
    promotes a numeric code under SYMBOL_CATALOG_MIL2525_D alone; under every other catalog the
    same in-range code is carried in the typed block and Entity.symbol is None."""
    symbol = {"symbol_catalog": catalog,
              "numeric_identifier": numeric("1003100000", "1211000000")}
    entity = only_entity(message(force(symbol=symbol)))
    assert entity["symbol"] is None
    assert entity["attributes"]["symbol_basis"].startswith(
        f"not promoted: symbol_catalog {catalog}; only a SYMBOL_CATALOG_MIL2525_D numeric code "
        "becomes Entity.symbol")
    assert entity["attributes"]["tacticalapi"]["blue_force"]["symbol"] == symbol


@pytest.mark.parametrize("first,second,symbol", [
    ("1013100015", "5", "10131000150000000005"),
    ("1003100000", "1", "10031000000000000001"),
    ("1003100000", "12", "10031000000000000012"),
    ("1003100000", "123", "10031000000000000123"),
    ("1003100000", "1234", "10031000000000001234"),
    ("1003100000", "12345", "10031000000000012345"),
    ("1003100000", "123456", "10031000000000123456"),
    ("1003100000", "1234567", "10031000000001234567"),
    ("1003100000", "12345678", "10031000000012345678"),
    ("1003100000", "123456789", "10031000000123456789"),
])
def test_a_short_second_set_is_zero_padded_on_the_left_to_ten_digits(first, second, symbol):
    """robustness-6 (mutant M41) and mapping-6 (mutants M16 and N03: the second set not padded,
    or padded on the right): the record §5.4 writes the first set followed by the second set
    zero-padded to ten digits. Every other promoted symbol of the tests has a second set of ten
    digits or 0, so only a short non-zero one, of each length from one to nine digits, tells
    the three apart. The expected symbols are written out, not computed."""
    entity = only_entity(message(force(symbol={"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
                                               "numeric_identifier": numeric(first, second)})))
    assert entity["symbol"] == symbol
    assert len(symbol) == 20 and symbol.startswith(first) and symbol.endswith(second)
    assert entity["attributes"]["symbol_basis"].startswith(
        "symbol.numeric_identifier with symbol_catalog SYMBOL_CATALOG_MIL2525_D")


@pytest.mark.parametrize("code,reference,alt_m", [
    ("VERTICAL_DISTANCE_REFERENCE_CODE_MEAN_SEA_LEVEL", "MSL", None),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID", "HAE", -12.25),
    ("VERTICAL_DISTANCE_REFERENCE_CODE_TOPOGRAPHIC_SURFACE", "AGL", None),
])
def test_a_negative_vertical_distance_keeps_its_sign(code, reference, alt_m):
    """robustness-6 (mutant M74, the absolute value taken): the record §5.5 maps the value as
    stated, with no datum conversion, and sets alt_m to the value only under code 11. A point
    below the reference (12.25 m below mean sea level, below the ellipsoid, below the surface)
    keeps its sign in Position.vertical, in alt_m and in the typed block."""
    geo = {"vertical_distance": -12.25, "vertical_distance_reference_code": code}
    entity = only_entity(message(force(point_location=at(**geo))))
    assert entity["position"]["vertical"] == {"value": -12.25, "unit": "m",
                                              "reference": reference, "uncertainty": None}
    assert entity["position"]["alt_m"] == alt_m
    assert entity["attributes"]["tacticalapi"]["blue_force"]["point_location"]["geo_point"][
        "vertical_distance"] == -12.25


# ================================= final verification, 2026-10-04: the fourth review (item 37)


def claiming(name: str, claimed: type) -> object:
    """An object of a class called `name` whose `__class__` names `claimed`, which it is not:
    `isinstance(obj, claimed)` is true and `type(obj)` is the class itself."""
    return type(name, (), {"__class__": property(lambda self: claimed)})()


class ClassRaises:
    """An in-process object whose `__class__` raises, which `isinstance` asks for."""

    @property
    def __class__(self):
        raise RuntimeError("EXERCISE class raised")


def test_an_object_claiming_to_be_text_is_refused_by_name_and_detect_answers_as_before():
    """R1-1 (the record "Changes", final verification, item 37), the review's two inputs: an
    object whose `__class__` says `str` passed the codec's `isinstance` test and `str.__str__`
    then left `to_cdm` as a TypeError, and `validate_source` wrote that error's text, which
    holds the class name raw, as an entry of two lines. As a key it made `detect` raise since
    item 35, where it answered True before. The codec reads `type(value)` now."""
    value = message(force(identity={"string_identity": claiming("Fa\nke", str)}))
    error = refused("invalid-twin-value", value)
    assert str(error) == ("invalid-twin-value: blue_forces[0].identity.string_identity is a "
                          "Fa\\nke; a string is text")
    assert adapter().detect(value) is True
    assert adapter().validate_source(value) == [f"TacticalapiRefused: {error}"]
    for key in (claiming("K\ney", str), ClassRaises()):
        keyed = message(force()) | {key: 1}
        assert adapter().detect(keyed) is True
        error = refused("invalid-twin-value", keyed)
        assert str(error).startswith("invalid-twin-value: the response has the key <")
        assert str(error).endswith("; twin keys are text") and str(error).isprintable()
        assert adapter().validate_source(keyed) == [f"TacticalapiRefused: {error}"]
    assert "K\\ney object at" in str(refused("invalid-twin-value",
                                             message(force()) | {claiming("K\ney", str): 1}))


@pytest.mark.parametrize("claimed,build,detected", [
    (int, lambda obj: message(force(identity={"int32_identity": obj})), True),
    (float, lambda obj: message(force(point_location={"speed": obj})), True),
    (bool, lambda obj: message(force(), header={"success": obj}), True),
    (bool, lambda obj: message(force(is_deleted=obj)), True),
    (bool, lambda obj: message(force(futureKey=obj)), True),
    (str, lambda obj: message(force(last_contact_time=obj)), True),
    (str, lambda obj: message(force(), **{"@type": obj}), False),
], ids=["int32", "double", "success", "is_deleted", "unknown key's value", "Timestamp", "@type"])
def test_a_scalar_claiming_its_type_is_refused_through_to_cdm_in_one_line(
        claimed, build, detected):
    """R1-1 (item 37): each left `to_cdm` as something other than a refusal — a TypeError from
    the base type's conversion, a TypeError from the JSON writer for a claimed bool under an
    unknown key, a validation error of six lines from the typed block for a claimed
    `is_deleted` — or, for a claimed `success`, as the wrong refusal (`success` is false). The
    host's measure passes a scalar by, so the codec meets it and refuses it by name; `detect`
    reads `@type` only, so it answers True unless the claim is the `@type` itself."""
    raw = build(claiming("EXERCISE\nclass", claimed))
    error = refused("invalid-twin-value", raw)
    assert "EXERCISE\\nclass" in str(error) and str(error).isprintable()
    assert adapter().validate_source(raw) == [f"TacticalapiRefused: {error}"]
    assert adapter().detect(raw) is detected


#: Where the host's measure meets an object that claims a type it is not, before this adapter
#: runs: the claimed type, and where the object sits.
HOST_MEASURE_MEETS = {
    "nested, claiming a dict": (dict, lambda obj: message(force(), header=obj)),
    "nested, claiming a list": (list, lambda obj: message(force(futureKey=obj))),
    "the input, claiming octets": (bytes, lambda obj: obj),
    "the input, claiming a view": (memoryview, lambda obj: obj),
    "the input, claiming text": (str, lambda obj: obj),
    "the input, claiming a dict": (dict, lambda obj: obj),
}


@pytest.mark.parametrize("site", sorted(HOST_MEASURE_MEETS))
@pytest.mark.parametrize("name", ["EXERCISE\nclass", "N" * 100_000], ids=["line break", "long"])
def test_where_the_hosts_measure_meets_such_an_object_validate_source_writes_one_line(
        site, name):
    """R1-1 (item 37), recorded as the record's opening paragraph states it: the host measures
    the input with `isinstance` and the container's own methods before this adapter runs, so an
    object claiming to be a container, octets or text raises there, in `wire_size` or
    `container_depth`, as whatever it raises. `validate_source` writes that text through
    `quote_error`: one printable line, where it was two. `detect` answers None for an input
    that is neither form by its own type, and True when the dict around the object states a
    supported type."""
    claimed, build = HOST_MEASURE_MEETS[site]
    raw = build(claiming(name, claimed))
    with pytest.raises(Exception) as caught:
        adapter().to_cdm(raw)
    assert not isinstance(caught.value, TacticalapiRefused)
    frames = [(entry.path.name, entry.name) for entry in caught.traceback]
    assert frames[-1] in {("adapter.py", "wire_size"), ("adapter.py", "container_depth")}, frames
    assert not any(path.startswith("tacticalapi") for path, _ in frames), frames
    [line] = adapter().validate_source(raw)
    assert line == f"{type(caught.value).__name__}: {codec.quote_error(caught.value)}"
    assert line.isprintable() and len(line) <= 200, line[:300]
    assert adapter().detect(raw) is (True if type(raw) is dict else None)


def test_validate_source_writes_a_refusals_text_whole_and_bounds_any_other(monkeypatch):
    """R1-1 (item 37): the base class's refusals are bounded where they are written, so their
    text is written whole (an InputTooDeep text is longer than a quote is cut to); any other
    exception's text goes through `quote_error`, escaped, cut, and described when it raises."""
    deep: list = []
    for _ in range(70):
        deep = [deep]
    raw = message(force(futureKey=deep))
    with pytest.raises(InputTooDeep) as caught:
        adapter().to_cdm(raw)
    assert len(str(caught.value)) > codec.QUOTE_LIMIT
    assert adapter().validate_source(raw) == [f"InputTooDeep: {caught.value}"]
    with pytest.raises(InputTooLarge) as caught:
        adapter().to_cdm(input_of_size(codec.MAX_INPUT_BYTES + 1))
    assert adapter().validate_source(input_of_size(codec.MAX_INPUT_BYTES + 1)) == [
        f"InputTooLarge: {caught.value}"]

    class Mum(Exception):
        def __str__(self) -> str:
            raise KeyError("EXERCISE")
    for raised, expected in (
            (RuntimeError("line one\n" + "z" * 500),
             "RuntimeError: line one\\n" + "z" * 110 + "... (390 more characters)"),
            (Mum(), "Mum: a Mum whose text raised KeyError")):
        def raise_it(raw, **limits):
            raise raised
        monkeypatch.setattr(codec, "twin_of", raise_it)
        assert adapter().validate_source(message(force())) == [expected]


def test_the_sub_millisecond_line_says_in_words_what_the_cdm_writes():
    """R1-2 (item 33): the tests compared this line with the constant that writes it, so a
    mutant that emptied the constant passed every test. The line is held to its words: the time
    is read as stated, and the CDM writes the epoch's text, which check J cannot tell apart."""
    raw = message(force(point_location={"location_time": "1970-01-01T00:00:00.000000001Z"}))
    assert adapter().validate_source(raw) == [
        "blue_forces[0].point_location.location_time is 1970-01-01T00:00:00.000000001Z, less "
        "than a millisecond after the epoch: a stated time, not what a default-constructed "
        "Timestamp serialises to, so it is read as the instant stated; the CDM renders it to the "
        "millisecond as 1970-01-01T00:00:00.000Z, the text it forbids for an unknown time, and "
        "the host's check J cannot tell the two apart"]


def test_an_exception_an_in_process_objects_own_method_raises_is_one_validate_source_line():
    """R1-1 (item 37), the limit the record's opening paragraph states: code an in-process object
    runs of its own while it is read, here a `dict` subclass's `items`, may raise anything, and
    `to_cdm` leaves with it; `validate_source` still writes it as one line, cut."""
    class Loud(dict):
        def items(self):
            raise RuntimeError("EXERCISE\nsecond line " + "x" * 500)
    raw = message(force(), header=Loud(success=True))
    with pytest.raises(RuntimeError):
        adapter().to_cdm(raw)
    assert adapter().validate_source(raw) == [
        "RuntimeError: EXERCISE\\nsecond line " + "x" * 98 + "... (402 more characters)"]
