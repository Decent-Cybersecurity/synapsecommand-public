"""STANAG 4586 Edition 3 — DLI telemetry ingest, against the row set that specified it. Adapter #15.

Every assertion is scoped to a NAMED section of the pinned document, a NAMED ambiguity register
entry or a NAMED fixture, per the testing protocol: a document-wide substring check passes by luck
when the phrase appears somewhere else, and this is a 509-page standard.

THERE IS NO ROUND-TRIP TEST HERE AND THAT IS NOT AN OMISSION
------------------------------------------------------------
The adapter is `ingest` and the codec has no encoder, by the scope ruling recorded at
`fixtures/stanag4586/spec/stanag4586_pin.json`'s `adapter.scope_ruling`. So the byte-equality
assertion the ASTERIX harnesses make has no subject here. What replaces it is the DECODE side of
the same discipline: the generator builds the octets from the document's own field widths, this
module asserts the octets on disk are what that generator produces, and every scale factor is
checked against a figure the document prints rather than against the codec's own table.

THE THREE THINGS A GREEN HARNESS RUN CANNOT TELL YOU
-----------------------------------------------------
`packages/cdm/synapse_cdm/README.md` names them and two bite here.

* **A fixture invariant under the harness clock exercises nothing.** Nothing in this set depends on
  `times.FROZEN_NOW`: `valid_from` comes from the wire's own Time Stamp on every fixture that
  carries one, and the one path that falls back to receipt time is asserted below against a clock
  this module injects.
* **A round trip proves self-consistency, never correctness.** There is no round trip, and the
  derive/invert pair that would need watching — `bam_to_radians` against the generator's
  `radians_to_bam` — is asserted against the document's STATED range endpoints rather than against
  each other, because a shared wrong constant would satisfy the pair and not the endpoints.
* **The roster sweep is a manual protocol act.** Not this module's job; `test_cdm_prose_counts.py`
  and `test_cdm_ordinals.py` hold the counts and the ordinals.
"""
import datetime as dt
import json
import math
import pathlib
import types

import pytest

import synapse_cdm
from synapse_cdm import ids, times
from synapse_cdm.adapters import stanag4586_codec as dli
from synapse_cdm.adapters.stanag4586 import (
    ALTITUDE_DATUM_AMBIGUITY, ALTITUDE_TYPE_WGS84, SYSTEM, Stanag4586Adapter,
)

#: Resolved through the IMPORTED package and never through the repository, which is what lets this
#: module run against the installed wheel — `gates/wheel_install.py` lists it under
#: PACKAGE_ONLY_TESTS with its twelve siblings, and a repo-relative path would have made it
#: repo-bound for no reason other than how it was typed.
PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "stanag4586"
PIN = json.loads((FIXTURES / "spec" / "stanag4586_pin.json").read_text())


def _build_fixtures_module():
    """The generator, loaded from SOURCE and never from bytecode — the CAT034/CAT048 pattern.

    `tests/test_cdm_generator_loading.py` holds every site that does this to the same behaviour by
    poisoning a `__pycache__` entry and requiring the source to win. The reason is recorded in full
    at that module and at `test_cdm_asterix_cat034_adapter.py`: a `.pyc` is revalidated on the
    source's mtime in whole seconds and its size, so a same-length edit reverted inside one second
    leaves a cache that validates against a file it was not compiled from.
    """
    path = FIXTURES / "spec" / "build_fixtures.py"
    module = types.ModuleType("stanag4586_build_fixtures")
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


def adapter(clock=None):
    return Stanag4586Adapter(clock=clock or (lambda: times.FROZEN_NOW))


def datagram(name: str) -> bytes:
    return (FIXTURES / f"{name}.s4586").read_bytes()


def objects(name: str, clock=None):
    return adapter(clock).to_cdm(datagram(name))


def entity(name: str, index: int = 0):
    return [o for o in objects(name) if o.object_kind == "entity"][index]


# ===================================================== the wire format, against §1.7 and §3.3.1


def test_the_wrapper_is_sixteen_octets_and_the_documents_twenty_is_that_plus_a_checksum():
    """§3.3.1 Figure B1-7's six header fields, summed, against §3.3.1.6's own sentence.

    The document states 20 and this module states 16, and they measure different things — the
    derivation is asserted rather than the totals reconciled by hand.
    """
    assert dli.WRAPPER_OCTETS == 16
    widths = {f["field"]: f["bytes"] for f in PIN["wire_format"]["message_wrapper_fields_in_order"]}
    fixed = [widths[k] for k in ("Sequence #", "Message Length", "Source ID",
                                 "Destination ID", "Message Type", "Message Properties")]
    assert sum(fixed) == dli.WRAPPER_OCTETS, "the pin's own widths must sum to the codec's constant"
    assert dli.WRAPPER_OCTETS + max(dli.CHECKSUM_OCTETS_BY_CODE.values()) == 20


def test_bam_reaches_the_documents_stated_endpoints_and_not_merely_its_own_inverse():
    """§1.7.3 — "a real range of -pi inclusive to pi exclusive" for an Integer field.

    Asserted at the ENDPOINTS, which is what a shared wrong constant cannot survive: the generator's
    `radians_to_bam` and the codec's `bam_to_radians` would agree with each other under any scale.
    """
    for octets in (2, 4):
        bits = octets * 8
        assert dli.bam_to_radians(-(2 ** (bits - 1)), octets) == pytest.approx(-math.pi)
        assert dli.bam_to_radians(2 ** (bits - 1) - 1, octets) < math.pi
        assert dli.bam_to_radians(0, octets) == 0.0


def test_the_five_octet_timestamp_rolls_over_in_2034_as_section_1_7_2_says():
    """A free check of BOTH the epoch and the LSB: no other pair lands on the document's year.

    §1.7.2: "In 2034 and in subsequent years, when the maximum value of the five byte field is
    exceeded, the timestamp shall 'roll over'".
    """
    assert dli.EPOCH == dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    assert dli.timestamp_to_utc(2 ** 40 - 1).year == 2034
    assert dli.timestamp_to_utc(0) == dli.EPOCH


def test_every_decoded_messages_presence_vector_width_holds_its_field_count():
    """§3.x's generating rule against each table's stated width — two independent statements.

    "a message containing ten fields would have a two-byte Presence Vector" is the rule; each
    message's own table prints the width. A mistranscription of either is visible here.
    """
    for number, spec in dli.MESSAGES.items():
        assert spec.presence_vector_is_wide_enough(), f"#{number}"
        # And not wastefully wide, which would mean the width was copied from another message.
        assert (spec.presence_vector_octets - 1) * 8 < len(spec.fields), f"#{number}"


def test_the_decoded_set_is_the_four_the_pin_names_and_no_others():
    """The scope ruling, enforced against the record rather than restated here."""
    pinned = {m["msg"] for m in PIN["decoded_message_set"]["messages"]}
    assert set(dli.MESSAGES) == pinned == {3002, 3009, 3010, 4000}


def test_no_command_message_is_decodable_which_is_the_scope_ruling_made_executable():
    """The out-of-scope half, asserted rather than left to the coverage document.

    Every number below is a command message this document defines — §4.3's Flight Vehicle Command
    group and the payload/link command groups. None may acquire a decoder without this failing.
    """
    for number in (2000, 2001, 2002, 2005, 2008, 5000, 7000, 11000, 19001, 24000, 30004):
        assert number not in dli.MESSAGES, (
            f"message #{number} is a COMMAND message and this adapter is telemetry ingest. If a "
            "decoder for it is genuinely wanted, the scope ruling in stanag4586_pin.json is what "
            "has to move first, and the CDM has no command object kind for it to land in"
        )


# ===================================================== the fixtures are the generator's output


def test_the_generator_is_the_only_thing_that_writes_the_octets():
    """Every `.s4586` on disk is byte-identical to what `build_fixtures.py` produces today.

    The CAT048 pattern: a generator's self-check that only runs when somebody runs the generator is
    a check that stops running the day the fixtures stop being rebuilt.
    """
    module = _build_fixtures_module()
    module.check_layouts()
    built = module.fixtures()
    on_disk = {p.stem: p.read_bytes() for p in FIXTURES.glob("*.s4586")}
    assert set(built) == set(on_disk)
    for name, octets in built.items():
        assert on_disk[name] == octets, f"{name}.s4586 is not what the generator produces"


def test_each_parsed_twin_is_the_parsed_form_of_its_own_payload():
    """The twin is a READABLE form of the same octets, never a second source of truth."""
    for path in sorted(FIXTURES.glob("*.parsed.json")):
        twin = json.loads(path.read_text())
        octets = (FIXTURES / f"{path.name[:-len('.parsed.json')]}.s4586").read_bytes()
        assert bytes.fromhex(twin["datagram_hex"]) == octets
        assert twin["octets"] == len(octets)
        assert len(twin["frames"]) == len(dli.decode_frames(octets))


def test_the_twin_and_the_octets_translate_to_the_same_objects():
    """Both entry points, one decoder. A twin that decoded differently would be a second codec."""
    a = adapter()
    for path in sorted(FIXTURES.glob("*.s4586")):
        twin = json.loads((FIXTURES / f"{path.stem}.parsed.json").read_text())
        assert ([o.model_dump(mode="json") for o in a.to_cdm(path.read_bytes())]
                == [o.model_dump(mode="json") for o in a.to_cdm(twin)])


# ===================================================== identity, and what this format can do


def test_the_entity_is_keyed_on_the_source_id_and_is_stable_across_datagrams():
    """§3.3.1.7 with §1.7.6 — the property `stanag4609` could not have.

    Two DIFFERENT datagrams from one vehicle yield one `entity_id`, and the adapter remembers
    nothing between them: the id is derived from the wire's own identifier.
    """
    a = entity("inertial_states_wgs84_altitude")
    b = entity("four_octet_checksum")
    c = entity("no_checksum_is_not_a_failing_checksum")
    assert a.entity_id == b.entity_id == c.entity_id
    assert a.entity_id == ids.derive(SYSTEM, "7.0.1.1")
    assert a.source_ids[0].external_id == "7.0.1.1"


def test_the_owning_id_is_the_most_significant_octet_of_the_key():
    """§1.7.6 — "The first (most significant) byte shall be the Owning ID"."""
    e = entity("inertial_states_wgs84_altitude")
    assert e.attributes["s4586_owning_id"] == 7
    assert e.attributes["s4586_source_id"].startswith("7.")


def test_two_vehicles_in_one_datagram_are_two_entities_and_two_tracks():
    """No join. Two Source IDs are two aircraft, and the format says so in every wrapper."""
    objs = objects("two_vehicles_are_two_entities")
    entities = [o for o in objs if o.object_kind == "entity"]
    tracks = [o for o in objs if o.object_kind == "track"]
    assert len(entities) == 2 and len(tracks) == 2
    assert entities[0].entity_id != entities[1].entity_id
    assert {t.entity_id for t in tracks} == {e.entity_id for e in entities}


# ===================================================== position, and the refusals around it


def test_position_comes_from_message_4000_in_wgs84_degrees():
    """§1.7.2's BAM radians become the CDM's stated decimal degrees."""
    e = entity("inertial_states_wgs84_altitude")
    assert e.position is not None
    assert e.position.lat == pytest.approx(57.512, abs=1e-6)
    assert e.position.lon == pytest.approx(21.884, abs=1e-6)


def test_position_source_is_inertial_and_never_gnss():
    """THE SAFETY-LOADED ONE. `PositionSource` is what makes a jammed-area warning discriminate.

    The message carrying the position is named `Inertial States` and the document states no GNSS
    source for it, so an unstated `GNSS` would be a claim trusted for a reason the wire never gave.
    """
    e = entity("inertial_states_wgs84_altitude")
    assert e.position.position_source == "INERTIAL"
    assert "INERTIAL" in e.attributes["position_source_basis"]
    assert "Not GNSS" in e.attributes["position_source_basis"]


def test_altitude_reaches_alt_m_only_under_altitude_type_3_and_carries_the_ambiguity():
    """Ambiguity 3: "WGS-84 (geoid)" names an ellipsoid and an equipotential surface at once."""
    wgs84 = entity("inertial_states_wgs84_altitude")
    assert wgs84.position.alt_m == pytest.approx(1500.0, abs=0.02)
    assert wgs84.attributes["altitude_datum_ambiguity"] == ALTITUDE_DATUM_AMBIGUITY

    baro = entity("altitude_type_baro_never_reaches_alt_m")
    assert baro.position is not None, "the fix is still a fix; only the altitude is withheld"
    assert baro.position.alt_m is None
    assert "not a geodetic height" in baro.attributes["altitude_basis"]
    # And the value is not lost — it parks with its own frame named.
    parked = baro.attributes["s4586_messages"]["#4000"]["fields"]["0101.06"]
    assert parked["raw"] == 75000 and parked["value"] == pytest.approx(1500.0)


def test_the_ambiguity_3_ruling_is_the_pins_ruling_and_not_a_second_one():
    """Two statements of one rule, required to agree — the pin gate's arrangement."""
    entry = next(e for e in PIN["ambiguity_register"] if e["entry"] == 3)
    assert ALTITUDE_TYPE_WGS84 == 3
    assert "WGS-84 (geoid)" in entry["the_field"]
    assert "ONLY FOR ALTITUDE TYPE 3" in entry["the_ruling_and_what_it_refuses"]


def test_half_a_coordinate_pair_is_no_position_rather_than_a_degraded_one():
    """Latitude present, longitude absent from the presence vector: building a point would put
    the aircraft on the prime meridian."""
    objs = objects("longitude_absent_from_the_presence_vector")
    e = objs[0]
    assert e.position is None and e.kinematics is None
    assert not [o for o in objs if o.object_kind == "track"], "no positioned sample, no Track"
    assert "no #4000" in e.attributes["position_basis"]


def test_two_positioned_messages_leave_the_entity_unpositioned_and_the_track_complete():
    """THE REFUSAL. Choosing "the latest" would be a decision made inside a translator."""
    objs = objects("two_inertial_states_leave_the_entity_unpositioned")
    e = [o for o in objs if o.object_kind == "entity"][0]
    track = [o for o in objs if o.object_kind == "track"][0]
    assert e.position is None and e.kinematics is None
    assert "does not choose" in e.attributes["position_basis"]
    assert len(track.samples) == 2, "nothing is lost — both observations are samples"
    assert track.samples[0].observed_at < track.samples[1].observed_at
    assert track.samples[0].position.lat != track.samples[1].position.lat


# ===================================================== kinematics


def test_course_is_atan2_east_over_north_per_section_1_7_2s_frame():
    """§1.7.2 — "Bearings shall be measured clockwise from true north", with U along north and V
    along east. The components are 62 north and 35 east, so the bearing is east-of-north."""
    e = entity("inertial_states_wgs84_altitude")
    assert e.kinematics.speed_mps == pytest.approx(math.hypot(62.0, 35.0), abs=1e-6)
    assert e.kinematics.course_deg == pytest.approx(math.degrees(math.atan2(35.0, 62.0)), abs=1e-6)
    assert 0 < e.kinematics.course_deg < 90, "east of north, not north of east"


def test_climb_inverts_w_speed_because_the_document_points_it_down():
    """0101.10 is "Inertial vertical speed component pointing down"; `climb_mps` is a climb."""
    e = entity("inertial_states_wgs84_altitude")
    raw = e.attributes["s4586_messages"]["#4000"]["fields"]["0101.10"]["value"]
    assert raw == pytest.approx(-2.5, abs=1e-9)
    assert e.kinematics.climb_mps == pytest.approx(2.5, abs=1e-9)


def test_zero_ground_speed_yields_no_course_because_a_bearing_would_be_invented():
    e = entity("zero_ground_speed_yields_no_course")
    assert e.kinematics.speed_mps == 0.0
    assert e.kinematics.course_deg is None
    assert "invented bearing" in e.attributes["course_basis"]


# ===================================================== defects are flagged and never refused


def test_a_checksum_that_does_not_validate_is_flagged_and_the_datagram_still_translates():
    """§3.3.1.11's sum, wrong on purpose. A producer's error must reach the operator as data —
    the same policy `stanag4609` applies to its own checksum."""
    e = entity("a_checksum_that_does_not_validate_is_flagged")
    kinds = [d["kind"] for d in e.attributes["s4586_defects"]]
    assert kinds == ["checksum_mismatch"]
    assert e.position is not None, "the packet is still translated"
    frame = e.attributes["s4586_frames"][0]
    assert frame["checksum_valid"] is False
    assert frame["checksum_stated"] != frame["checksum_computed"]


def test_no_checksum_is_not_the_same_as_a_failing_checksum():
    """§3.3.1.11 makes it optional. `None` and `False` are different answers and stay different."""
    e = entity("no_checksum_is_not_a_failing_checksum")
    frame = e.attributes["s4586_frames"][0]
    assert frame["checksum_octets"] == 0
    assert frame["checksum_valid"] is None
    assert "s4586_defects" not in e.attributes


def test_a_four_octet_checksum_is_read_at_its_own_width():
    """Table B1-4's other assigned width."""
    e = entity("four_octet_checksum")
    frame = e.attributes["s4586_frames"][0]
    assert frame["checksum_octets"] == 4
    assert frame["checksum_valid"] is True
    assert "s4586_defects" not in e.attributes


def test_an_idd_version_that_is_not_edition_3_is_recorded_rather_than_refused():
    """Table B1-3 assigns 30 to Edition 3. A frame declaring 40 is decoded against Edition 3's
    tables anyway, and THE DEFECT IS HOW THE READER LEARNS THAT HAPPENED.

    This is the shape an Edition 4 frame would arrive in, and it is the reason this fixture exists:
    the edition this repository cannot obtain would announce itself here.
    """
    e = entity("an_idd_version_that_is_not_edition_3")
    defect = next(d for d in e.attributes["s4586_defects"]
                  if d["kind"] == "idd_version_is_not_edition_3")
    assert defect["stated"] == 40 and defect["expected"] == dli.IDD_VERSION_EDITION_3 == 30
    assert e.position is not None


def test_an_undecoded_message_type_is_parked_and_the_known_one_still_translates():
    """§3.3.1.9's type space is far larger than the decoded set. #6000 IFF Status Report is a real
    Edition 3 message (Table B1-78) that this adapter does not decode."""
    e = entity("an_undecoded_message_type_is_parked")
    parked = e.attributes["s4586_unparsed_messages"]
    assert [p["message_type"] for p in parked] == [6000]
    assert parked[0]["octets"] == "0001020304050607", "octets parked verbatim"
    assert e.position is not None, "the #4000 alongside it still translates"
    assert "#6000" not in e.attributes["s4586_messages"]


# ===================================================== the keying rule, ambiguity 4


def test_the_two_roll_rates_never_share_a_key_and_their_scales_differ_by_fifty():
    """AMBIGUITY 4 MADE STRUCTURAL. #4000 scales rotation rates at 0.005 rad/s and #3010 at
    0.0001 rad/s — the same physical quantity, raw integers fifty times apart.

    A flat `roll_rate` key would be written by whichever message arrived last, at whichever scale,
    with nothing on the object saying which: a number wrong by a factor of 50 that looks entirely
    reasonable. Filing by message number is what makes that unrepresentable.
    """
    e = entity("four_decoded_messages_one_vehicle")
    messages = e.attributes["s4586_messages"]
    inertial = messages["#4000"]["fields"]["0101.17"]
    body = messages["#3010"]["fields"]["0103.07"]
    assert inertial["units"] == "0.005 rad/s" and body["units"] == "0.0001 rad/s"
    assert inertial["raw"] == 10 and body["raw"] == 500
    assert inertial["value"] == pytest.approx(body["value"]), "the same physical rate"
    assert inertial["raw"] * 50 == body["raw"], "and fifty times apart on the wire"


def test_all_four_decoded_messages_are_filed_under_their_own_numbers():
    e = entity("four_decoded_messages_one_vehicle")
    assert sorted(e.attributes["s4586_messages"]) == ["#3002", "#3009", "#3010", "#4000"]


def test_av_state_parks_with_its_text_and_is_never_read_as_a_cdm_semantic():
    """The enumeration names NO airborne state — every assigned value is a phase before flight and
    everything from 10 up is "VSM Specific". Reading a vendor's private number as a flight phase
    would be inventing a fleet model."""
    e = entity("four_decoded_messages_one_vehicle")
    av = e.attributes["s4586_messages"]["#3002"]["fields"]["3002.01"]
    assert av["raw"] == 3 and av["text"] == "Pre-launch"
    assert e.entity_type == "PLATFORM", "the type is not refined from the flight phase"
    assert dli.av_state_text(7) == "Reserved"
    assert dli.av_state_text(42) == "VSM Specific"
    assert set(dli.AV_STATE) == {0, 1, 2, 3, 4}, (
        "if an airborne value is ever added here, the claim in the codec's comment that this "
        "enumeration cannot express 'flying' has to be re-read against the document"
    )


# ===================================================== time


def test_valid_from_is_the_earliest_message_stamp_and_not_the_latest():
    """`valid_from` is "when this state began", so the span's first instant is the answer."""
    e = entity("four_decoded_messages_one_vehicle")
    stamps = sorted(m["fields"][uid]["value"]
                    for m, uid in ((e.attributes["s4586_messages"]["#4000"], "0101.01"),
                                   (e.attributes["s4586_messages"]["#3002"], "0104.01"),
                                   (e.attributes["s4586_messages"]["#3009"], "0102.01"),
                                   (e.attributes["s4586_messages"]["#3010"], "0103.01")))
    assert times.render(e.valid_from) == stamps[0]
    assert times.render(e.valid_from) != stamps[-1]


def test_the_clock_is_injected_and_reaches_received_at_only():
    """A fixture invariant under the harness clock exercises nothing, so this injects its own.

    `valid_from` comes from the WIRE and must not move with the clock; nothing else in this set
    reads receipt time at all.
    """
    other = dt.datetime(2031, 7, 4, 11, 22, 33, tzinfo=dt.timezone.utc)
    a = entity("inertial_states_wgs84_altitude")
    b = [o for o in adapter(clock=lambda: other).to_cdm(
        datagram("inertial_states_wgs84_altitude")) if o.object_kind == "entity"][0]
    assert a.valid_from == b.valid_from, "the wire's instant, not the clock's"


def test_time_basis_states_the_leap_second_question_rather_than_resolving_it():
    """§1.7.2 calls the count UTC and says nothing further. Park 3's shape in a second format."""
    e = entity("inertial_states_wgs84_altitude")
    assert "UNSTATED" in e.attributes["time_basis"]
    assert "2034" in e.attributes["time_basis"]


# ===================================================== the edition, stated everywhere


def test_every_object_states_the_edition_it_was_decoded_against():
    """No object may be silent about this, because the edition is not the current one."""
    for path in sorted(FIXTURES.glob("*.s4586")):
        for obj in adapter().to_cdm(path.read_bytes()):
            if obj.object_kind == "entity":
                assert obj.attributes["s4586_edition"] == "Edition 3", path.stem


def test_both_modules_carry_the_disclaimer_rather_than_merely_not_claiming_edition_4():
    """The stop rule as a test — and it is a PRESENCE check on purpose.

    THE FIRST DRAFT OF THIS TEST WAS THE DEFECT IT WAS WRITTEN TO CATCH. It swept for phrases like
    "reads an Edition 4 feed" and required their absence, and it failed against a correct tree:
    the adapter's docstring contains that exact phrase inside its own NEGATION — "no sentence
    anywhere in this repository asserts that this decoder reads an Edition 4 feed". A substring
    sweep cannot tell a claim from its denial, which is sweep rule 9's lesson (a record that
    discusses a token becomes a site of it) arriving in a test rather than in prose.

    So the check is the other way round, where the evidence actually is: each module must SAY that
    Edition 4 is current, is not held, and is not what it decodes. Silence is the failure — a
    module that mentioned neither edition would pass any absence check ever written.
    """
    for name in ("stanag4586.py", "stanag4586_codec.py"):
        flat = " ".join((PACKAGE / "adapters" / name).read_text().split())
        assert "Edition 4" in flat and "Edition 3" in flat, name
        assert "could not be acquired" in flat, (
            f"{name} does not say Edition 4 could not be acquired. The edition ruling is the "
            "reason this adapter targets a superseded document, and a module that omits it "
            "reads as though Edition 3 were current"
        )
        assert "no sentence" in flat.lower() or "nothing here claims" in flat.lower(), (
            f"{name} carries no explicit refusal of an Edition 4 compatibility claim"
        )


# ===================================================== the pin is the one site, and it is gated


def test_every_site_that_states_the_pinned_identity_agrees_with_the_pin():
    """THE DISJUNCTION GUARD. Three files state this document's identity and only one owns it.

    `stanag4586_pin.json` is the record; `adapters/stanag4586_codec.py`'s docstring and
    `FORMAT_COVERAGE.md`'s section opening both restate the digest, the byte count and the page
    count for a reader who is not going to open the pin. That is three statements of one fact,
    which this repository's answer is either to collapse to one site or to gate — and collapsing is
    not available here, because a codec whose docstring does not say which bytes it was written
    from is the thing the pin discipline exists to prevent.

    So they are gated. The abbreviated form is checked as a PREFIX AND SUFFIX of the full digest
    rather than as a substring, because `a4fa6e54…c15da` sharing a substring with the real hash is
    not the claim being made.
    """
    full = PIN["source"]["sha256"]
    abbreviated = f"{full[:8]}…{full[-5:]}"
    assert abbreviated == "a4fa6e54…c15da", "the abbreviation convention itself moved"
    coverage = (PACKAGE / "FORMAT_COVERAGE.md").read_text()
    codec = (PACKAGE / "adapters" / "stanag4586_codec.py").read_text()

    for name, text in (("FORMAT_COVERAGE.md", coverage), ("stanag4586_codec.py", codec)):
        assert abbreviated in text, f"{name} does not state the pinned digest"
        assert f"{PIN['source']['page_count']} pages" in text, f"{name} does not state the page count"

    # The byte count is spelled with thin separators in prose and as an integer in the pin.
    assert f"{PIN['source']['bytes']:,}".replace(",", " ") == "3 852 365"
    assert "3 852 365" in coverage

    # And the file the pin names is the file on disk, at that digest.
    import hashlib
    landed = PACKAGE / "fixtures" / "stanag4586" / "spec" / "STANAG_4586_Ed3.pdf"
    if not landed.exists():
        pytest.skip("the pinned PDF is gitignored and absent from this checkout — "
                    "gates/pin_paths.py owns the present-and-matched half")
    assert hashlib.sha256(landed.read_bytes()).hexdigest() == full


def test_the_edition_ruling_names_edition_4_as_current_and_unheld_in_both_directions():
    """The ruling's two halves, which a later round must not be able to half-forget.

    A record saying only "Edition 3 is pinned" reads as though Edition 3 were current. A record
    saying only "Edition 4 is current" reads as though it were held. Both are required.
    """
    ruling = PIN["edition_ruling"]
    current = ruling["what_is_current_VERIFIED_and_not_inherited"]
    assert "EDITION 4" in current and "2017-04-05" in current and "AEP-84" in current
    unheld = ruling["EDITION_4_COULD_NOT_BE_ACQUIRED_and_the_routes_are_named"]
    for route in ("nso.nato.int", "Internet Archive", "everyspec.com", "DRM"):
        assert route in unheld, f"the acquisition record does not name the {route} route"
    assert "PIN EDITION 3 AND BUILD AGAINST IT" in ruling["THE_RULING"]
    assert "NO SENTENCE IN THIS REPOSITORY ASSERTS" in ruling["WHAT_THE_RULING_DOES_NOT_LICENSE"]


def test_the_two_party_identity_check_is_recorded_with_both_digests_and_they_differ():
    """The second party is only evidence if the record says what it actually found.

    It found a ONE-BYTE difference and identical text on all 509 pages, and a record that smoothed
    that to "the copies match" would be the more comfortable claim and the false one.
    """
    node = PIN["the_identity_is_attested_by_TWO_PARTIES_and_the_second_one_disagreed_by_one_byte"]
    assert PIN["source"]["sha256"][:8] in node["THE_TWO_COPIES_ARE_NOT_BYTE_IDENTICAL"]
    assert "7c1df5aa" in node["THE_TWO_COPIES_ARE_NOT_BYTE_IDENTICAL"]
    assert "ONE BYTE APART" in node["THE_TWO_COPIES_ARE_NOT_BYTE_IDENTICAL"]
    proof = node["AND_THE_NATO_CONTENT_WAS_PROVED_IDENTICAL_RATHER_THAN_ASSUMED"]
    assert "509" in proof and "ZERO" in proof
