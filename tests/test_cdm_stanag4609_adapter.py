"""Adapter #10 — STANAG 4609 / MISP-2019.1, the UAS Datalink Local Set. The harness for it.

WHAT THIS MODULE CHECKS THAT NOTHING ELSE CAN
---------------------------------------------
The harness checks the six generic properties over the ten fixtures — translate, schema,
provenance, lossless, round-trip and golden — and reports the round-trip one as SKIP for a binary
adapter, because `from_cdm` returns octets it cannot compare structurally. So the byte-exact
egress claim is unchecked unless a module like this one checks it, which is what `harness.py` says
in the message it prints: "the adapter must ship its own round-trip test in tests/".

FOUR THINGS ARE ASSERTED HERE AND EACH ONE IS A CLAIM MADE IN PROSE SOMEWHERE ELSE
----------------------------------------------------------------------------------
* **The transcription is the document's.** `klv_uas_codec`'s 26 items each carry the Example KLV
  Value their own §8.x block prints, and both self-checks run here on every suite run — over
  ST 0601.14a's 26 examples and over EG 0601.1's 23. A transcription checked only against a
  fixture written from the same reading proves nothing, and these are the checks that make the
  anchor external.
* **Egress is byte-exact, including over the defect.** Asserted against every fixture and against
  the PINNED REAL STREAM when it is present in the working tree — where "byte-exact" means all 977
  octets, tag 22's four non-conformant ones included. An egress that quietly re-encoded that item
  at its conformant length would pass a lossless check and would be this adapter correcting a
  stream it was asked to translate.
* **The length policy behaves as ruled, in all five of its cases.** One fixture per case, and the
  cases are the document's own distinctions rather than this repository's — a `shall`, a
  recommendation, and two readings of a length of zero.
* **The parsed twin and the binary payload produce the SAME CDM.** Asserted rather than assumed,
  because `stanag4676.py` had to add exactly this test after the two paths drifted.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
* **It states no counts about the tree.** The adapter count, the ordinal and the register bound
  live in `tests/test_cdm_prose_counts.py`, `tests/test_cdm_ordinals.py` and
  `tests/test_cdm_format_coverage.py`; a fourth statement of any of them here would be a fourth
  thing to keep in step.
* **It asserts nothing about the pinned stream that requires the stream.** Every check that needs
  those 977 octets is skipped with a reason when the file is absent, because `.gitignore` excludes
  `fixtures/klv/streams/` and a clone does not have it. A test that fails on a fresh clone teaches
  people to ignore the suite.
"""
import datetime as dt
import hashlib
import json
import pathlib

import pytest

import synapse_cdm
from synapse_cdm import lossless, times
from synapse_cdm.adapters import klv_codec as framing
from synapse_cdm.adapters import klv_uas_codec as uas
from synapse_cdm.adapters.stanag4609 import (
    EPOCH,
    OBSERVATION_SYSTEM,
    SYSTEM,
    Stanag4609Adapter,
    Stanag4609ParseError,
    parse_payload,
)
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import Entity, Event
from gates import pin_paths

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PACKAGE.parents[2]
FIXTURES = PACKAGE / "fixtures" / "klv"
GOLDEN = FIXTURES / "golden"

#: The pinned extraction the witnessed set was enumerated from. NOT in the index — `.gitignore`
#: excludes `fixtures/klv/streams/` as a directory — so every check that needs it is skipped with a
#: reason when it is absent rather than failing on a fresh clone.
#:
#: RESOLVED RATHER THAN SPELLED. This line used to read `REPO / "fixtures" / "klv" / "streams" /
#: "day_flight.klv"`, a third literal restatement of a path the pin already carries, against a
#: third spelling of the repository root. `gates/pin_paths.py` chooses the base from the pin's own
#: `local_path`, which is what keeps a stream from being looked for inside the package — the
#: failure that reads as a fresh clone rather than as an error.
STREAM = pin_paths.resolve("fixtures/klv/streams/day_flight.klv")
STREAM_SHA = "a810e4b60ff33b1bdc1831594201d8158655c0808bdef1b22d84a9eb26e22e51"
STREAM_BYTES = 977

needs_stream = pytest.mark.skipif(
    not STREAM.is_file(),
    reason=f"{STREAM} is not in the working tree; .gitignore excludes fixtures/klv/streams/",
)


def adapter(**kwargs) -> Stanag4609Adapter:
    return Stanag4609Adapter(clock=times.frozen_clock(), **kwargs)


def payloads() -> list[pathlib.Path]:
    return sorted(FIXTURES.glob("*.klv"))


def dumped(objects) -> list[dict]:
    return [o.model_dump(mode="json") for o in objects]


def _build_fixtures_module():
    """Compile the generator IN MEMORY, never through the source loader.

    The name and the technique are the four sibling adapter harnesses' — see
    `tests/test_cdm_generator_loading.py`, which lists this module among the loaders and poisons the
    cache to prove the source on disk is what gets read. `exec_module` would consult and write
    `__pycache__`, and a `.pyc` is revalidated on the source's mtime in whole seconds and its size,
    which a same-length edit reverted inside one second defeats.
    """
    import types
    path = FIXTURES / "spec" / "build_fixtures.py"
    module = types.ModuleType("klv_build_fixtures")
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


# ------------------------------------------------------------------ the transcription's anchors


def test_the_item_table_decodes_the_pinned_editions_own_worked_examples():
    """26 of 26, and this is the check that makes the transcription trustworthy at all.

    Every §8.x block prints one Software Value beside the KLV octets that encode it, and §7's
    Programmer's Notes say why: "the 'Example Value' for a tag is shown in full precision, beyond a
    tag's resolution, so programmers can verify they are using the right formulas." So the
    invitation is the document's. A disagreement here means a cell was transcribed wrongly, and no
    fixture in this repository could catch that — a fixture written from the same reading of the
    same table agrees with the reading rather than with the table.
    """
    problems = uas.check_against_the_documents_own_examples()
    assert problems == [], "\n".join(problems)
    assert len(uas.ITEMS) == 26
    assert uas.WITNESSED_TAGS == (1, 2, 5, 6, 7, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
                                  23, 24, 25, 40, 41, 42, 56, 57, 65)


def test_edition_1s_own_examples_decode_under_the_pinned_editions_map():
    """23 of 23, and it answers a DIFFERENT question from the check above.

    Not "is the transcription right" but "did the map move between edition 1 and the pinned one".
    The two are independent sets of octets over the same 26 maps, and the second is what generalises
    park 13's finding from item 22's single Len cell to the whole witnessed set: twelve years and
    thirteen revisions, sampled at both ends, and the map did not move. Items 40, 41 and 42 have a
    §7.N section and no worked example, which is why 23 and not 26 — asserted here so the gap is a
    measured absence rather than a silently smaller loop.
    """
    problems = uas.check_against_edition_1s_examples()
    assert problems == [], "\n".join(problems)
    with_examples = [t for t, i in uas.ITEMS.items() if i.edition_1_example_octets is not None]
    assert len(with_examples) == 23
    assert sorted(set(uas.ITEMS) - set(with_examples)) == [40, 41, 42]


def test_the_two_editions_agree_on_every_witnessed_items_range_and_format():
    """Register entry KLV 17's other half: exactly ONE column moved, and this is which.

    Asserted from the transcribed cells rather than from prose, so "the only divergence is the
    string encoding on items 11 and 12" is a derived statement. A later round that finds a second
    divergence has to move this test deliberately, which is the register's own upper-guard shape.
    """
    diverged = []
    for tag, item in sorted(uas.ITEMS.items()):
        header = item.edition_1_header
        if header is None:
            continue
        if item.klv_format not in header:
            diverged.append((tag, item.klv_format, header))
    assert [d[0] for d in diverged] == [11, 12], (
        f"the editions diverge on {diverged}. Register entry KLV 17 records exactly two items — "
        "11 and 12, `ISO7` against `utf8` — and a third would be a finding this round did not make"
    )
    assert all("ISO7" in d[2] for d in diverged)


# ------------------------------------------------------------------ the length policy


@pytest.mark.parametrize("fixture,expect_defects,expect_advisories", [
    ("witnessed_set_from_the_documents_own_examples", [], []),
    ("length_divergence_at_a_required_length", [(22, uas.DIVERGENCE_REQUIRED_LENGTH)], []),
    ("zero_length_item_is_an_explicit_unknown", [], []),
    ("zero_length_item_on_a_required_item_is_a_defect",
     [(65, uas.DIVERGENCE_ZLI_ON_REQUIRED_ITEM)], []),
    ("over_recommended_max_length_is_an_advisory", [], [(11, uas.ADVISORY_OVER_MAX_LENGTH)]),
    ("mandatory_items_only", [], []),
])
def test_the_length_policy_disposes_of_each_case_the_document_distinguishes(
        fixture, expect_defects, expect_advisories):
    """One fixture per row of the policy table, and the rows are the DOCUMENT's distinctions.

    The point of parametrising it rather than writing six tests: the policy is one ruling with four
    branches, and four branches asserted in four places drift into four rules. Two of the branches
    turn on the difference between a `shall` (`ST 0601.13-29`) and a "recommended" maximum (§7's own
    word), and two on the two readings of a length of zero that `ST 0601.14-32` and `-33` state.
    """
    packets = uas.decode_stream((FIXTURES / f"{fixture}.klv").read_bytes())
    defects = [(d.tag, d.divergence_class) for p in packets for d in p.defects]
    advisories = [(a["tag"], a["class"]) for p in packets for a in p.advisories]
    assert defects == expect_defects
    assert advisories == expect_advisories


def test_a_length_divergent_item_is_skipped_and_annotated_and_never_reinterpreted():
    """Candidate (b), asserted in all three of the ways it differs from (a) and (c)."""
    raw = (FIXTURES / "length_divergence_at_a_required_length.klv").read_bytes()
    objects = adapter().to_cdm(raw)
    entity = objects[0]
    assert isinstance(entity, Entity)

    # (a) is refused: the packet translated, and the items that were conformant are all here.
    assert len(objects) == 2
    assert set(entity.attributes["klv_item_octets"]) >= {"2", "65", "22", "56", "1"}

    # (b) is done: the value reaches no field, and the annotation names both bases.
    assert 22 not in {int(t) for t in entity.attributes["klv_items"]}
    policy = entity.attributes["length_divergence_policy"]
    assert policy["policy"] == uas.LENGTH_DIVERGENCE_POLICY
    defect, = policy["defects"]
    assert (defect["tag"], defect["observed_length"], defect["required_length"]) == (22, 4, 2)
    assert defect["octets"] == "00000fa0"
    assert "ST 0601.13-29" in defect["normative_basis"]
    assert "retroactivity is still unestablished" in defect["normative_basis"], (
        "the standing annotation has been shed. ST 0601.13-29 is stamped edition 13 and nothing "
        "held establishes that it reaches an emitter written against an earlier edition; a closure "
        "that tidies that away overstates what the ruling bought"
    )
    assert "edition 1" in defect["factual_basis"]

    # (c) is refused: no plausible number appeared anywhere in the output for tag 22.
    flat = json.dumps(dumped(objects))
    assert "4000" not in flat, (
        "4000 appears in the output, which is what `0x00000FA0` would decode to under a "
        "truncation rule no held document states. That is candidate (c), and it was rejected: "
        "the three available rules agree on the pinned stream's octets and disagree the moment a "
        "top octet is non-zero"
    )
    assert objects[1].payload["target_width_m"]["value"] is None


def test_a_zero_length_item_is_an_explicit_unknown_and_not_a_zero():
    """`ST 0601.14-33`, and the distinction a never-drop model exists to preserve."""
    raw = (FIXTURES / "zero_length_item_is_an_explicit_unknown.klv").read_bytes()
    objects = adapter().to_cdm(raw)
    entity = objects[0]
    assert entity.kinematics is None, (
        "a zero-length ground speed became a Kinematics. `ST 0601.14-33` says a consumer 'shall "
        "interpret the value of the item as \"unknown\"', and a speed of 0.0 m/s is a claim that "
        "the aircraft is stationary"
    )
    assert entity.attributes["klv_items"]["56"]["value"]["zero_length_item"] is True
    assert entity.attributes["length_divergence_policy"]["defects"] == []


def test_a_special_value_is_returned_as_a_signal_and_reaches_no_canonical_field():
    """The four Special Values the witnessed set declares, and the lie each one would have told.

    This fixture caught a real defect on its first run: the sentinel is written in the document as a
    hex BIT PATTERN, and `0x80000000` compared against the SIGNED reading of the same octets is
    -2147483648, so the comparison missed and the affine map returned a latitude of
    -90.00000004190952 — which pydantic then refused. The comparison is against the unsigned
    reading now, on §7's own framing: "The KLV Value bit pattern in each equation is interpretable
    in diverse ways."
    """
    raw = (FIXTURES / "special_values_are_signals_and_not_measurements.klv").read_bytes()
    entity, event = adapter().to_cdm(raw)
    assert entity.position is None, (
        "a Position was built even though tag 13 carries §8.13's 'Reserved' signal. Tag 14 is "
        "present and valid in this fixture precisely to make a half-built point tempting"
    )
    assert event.geometry is None
    assert entity.attributes["klv_items"]["6"]["value"]["special_value"] == "Out of Range"
    assert entity.attributes["klv_items"]["13"]["value"]["special_value"] == "Reserved"
    assert entity.attributes["klv_items"]["23"]["value"]["special_value"] == "N/A (Off-Earth)"
    flat = json.dumps(dumped([entity, event]))
    assert "-90.0000000419" not in flat


def test_an_over_max_length_item_is_decoded_because_max_length_is_a_recommendation():
    """The mirror image of candidate (c)'s mistake, and §7's own word is what decides it."""
    raw = (FIXTURES / "over_recommended_max_length_is_an_advisory.klv").read_bytes()
    entity, _ = adapter().to_cdm(raw)
    assert entity.attributes["klv_items"]["11"]["value"] == "A" * 128, (
        "a 128-octet item 11 was skipped. §7 defines Max Length as 'the recommended maximum "
        "length' and names a network guard as its consumer, so nothing here breaks a `shall`; "
        "applying ST 0601.13-29 to a recommendation enforces a rule the document did not write"
    )
    advisory, = entity.attributes["length_divergence_policy"]["advisories"]
    assert (advisory["tag"], advisory["observed_length"], advisory["max_length"]) == (11, 128, 127)
    assert "recommended" in advisory["basis"]
    assert entity.attributes["length_divergence_policy"]["defects"] == []


def test_an_unwitnessed_tag_is_skipped_and_the_packet_still_translates():
    """`ST 0107.3-04`, tested from above the framing layer for the first time.

    The framing layer satisfies it structurally, by knowing no tags at all. THIS layer knows 26, so
    it is the first place where a skip list could exist and a skip could go wrong.
    """
    raw = (FIXTURES / "an_unwitnessed_tag_is_skipped_and_the_packet_translates.klv").read_bytes()
    entity, _ = adapter().to_cdm(raw)
    assert entity.attributes["klv_unknown_tags"] == [3]
    assert entity.attributes["klv_unknown_items"] == {"3": "4d5f3335"}
    assert "ST 0107.3-04" in entity.attributes["klv_unknown_basis"]
    assert entity.attributes["length_divergence_policy"]["defects"] == [], (
        "an uncovered item was reported as a defect. Tag 3 is a real ST 0601 item this round did "
        "not cover because the pinned stream does not carry it; unknown is not malformed"
    )


# ------------------------------------------------------------------ the object shape


def test_the_mandatory_only_packet_states_its_absences_in_words():
    """Three items, and the absences are the assertion.

    An object with fewer keys and an object that says which fields it could not fill are different
    artefacts, and only the second is auditable.
    """
    entity, event = adapter().to_cdm((FIXTURES / "mandatory_items_only.klv").read_bytes())
    assert entity.position is None and entity.kinematics is None and event.geometry is None
    assert entity.entity_type is EntityType.PLATFORM
    assert entity.affiliation is Affiliation.UNKNOWN
    assert entity.confidence is None and entity.valid_to is None
    assert event.event_type is EventType.STATUS_CHANGE and event.severity is Severity.INFO
    unavailable = entity.attributes["unavailable_fields"]
    assert any("Position" in u for u in unavailable)
    assert any("Kinematics" in u for u in unavailable)
    assert entity.attributes["klv_tag_order"] == [2, 65, 1], (
        "`ST 0601.8-09` and `-11` put item 2 first and item 1 last, and the generator builds the "
        "packet through the codec so the order cannot be typed wrongly"
    )


def test_the_identity_is_packet_scoped_and_says_so_on_every_object():
    """The hardest call in the adapter, asserted with the cost it carries.

    Consecutive packets of one platform get DIFFERENT entity_ids. That is a truncation and it is
    named — here and in gap 30 — rather than avoided by keying on something unstable. The fixture
    two_packets_one_payload proves the cost rather than describing it.
    """
    objects = adapter().to_cdm(
        (FIXTURES / "two_packets_one_payload_are_two_statements.klv").read_bytes())
    assert len(objects) == 4
    first, second = objects[0], objects[2]
    assert first.entity_id != second.entity_id, (
        "two packets produced one entity_id, so state crossed a packet boundary or the id stopped "
        "being packet-scoped. Either would be a stronger claim than the format supports"
    )
    for entity in (first, second):
        assert [s.system for s in entity.source_ids] == [OBSERVATION_SYSTEM]
        basis = entity.attributes["identity_basis"]
        assert "PACKET-SCOPED" in basis and "THIS OBSERVATION" in basis
        assert "'EON'" in basis and "'IR'" in basis, (
            "the identity basis no longer records WHY item 11 cannot key an entity. It is "
            "disqualified by the bytes rather than by argument, and the bytes are the evidence"
        )
        assert "Park 11" in basis
    assert first.source.system == SYSTEM
    assert first.source.adapter == "stanag4609"


def test_time_comes_from_item_2_and_carries_its_own_caveats():
    """The epoch is a held document's; the timescale's NAME is still park 3's."""
    entity, event = adapter().to_cdm(
        (FIXTURES / "witnessed_set_from_the_documents_own_examples.klv").read_bytes())
    # §8.2's own worked example: "Oct. 24, 2008. 00:13:29.913" <-> 0004 59F4 A6AA 4AA8
    assert times.render(event.observed_at) == "2008-10-24T00:13:29.913Z"
    assert entity.valid_from == event.observed_at
    assert entity.attributes["precision_time_stamp_us"] == 1224807209913000
    basis = entity.attributes["time_basis"]
    assert "1970-01-01T00:00:00Z" in basis["epoch"]
    assert "does not represent UTC" in basis["timescale"]
    assert "POSIX" in basis["timescale"]
    assert "park 3" in basis["timescale"]
    assert "milliseconds" in basis["precision"]
    # The injected clock, and nothing else, decides received_at.
    assert times.render(event.received_at) == times.render(times.FROZEN_NOW)
    later = Stanag4609Adapter(clock=times.frozen_clock(dt.datetime(2030, 1, 2, 3, 4, 5,
                                                                   tzinfo=dt.timezone.utc)))
    _, other = later.to_cdm((FIXTURES / "mandatory_items_only.klv").read_bytes())
    assert times.render(other.received_at) == "2030-01-02T03:04:05.000Z"
    assert other.observed_at == event.observed_at, (
        "observed_at moved with the clock. It comes from item 2 and the clock decides received_at "
        "alone — the one field an adapter invents"
    )


def test_a_packet_with_no_usable_timestamp_is_refused_and_the_refusal_quotes_the_document():
    """The NITS `baseTime` refusal reached a second time, and by a different route.

    `Event.observed_at` is required and the Local Set has nothing else to read it from, so a packet
    without a usable item 2 cannot become an object. Refused rather than filled from the injected
    clock, which is what makes this different from the CAT021 and CAT034 time-of-day cases: there
    the wire states a time and omits the date, here the wire states nothing.
    """
    body = (framing.encode_ber_oid(65) + framing.encode_ber_length(1) + b"\x0d"
            + framing.encode_ber_oid(1) + framing.encode_ber_length(2))
    prefix = framing.UAS_LOCAL_SET_KEY + framing.encode_ber_length(len(body) + 2)
    packet = prefix + body + framing.bcc_16(prefix + body).to_bytes(2, "big")
    with pytest.raises(Stanag4609ParseError) as caught:
        adapter().to_cdm(packet)
    message = str(caught.value)
    assert "Precision Time Stamp" in message and "§6.4" in message
    assert "ST 0601.14-32" in message


def test_the_frame_centre_is_the_geometry_and_the_target_location_never_is():
    """Two stated points, and choosing between them per packet would be a decision."""
    entity, event = adapter().to_cdm(
        (FIXTURES / "witnessed_set_from_the_documents_own_examples.klv").read_bytes())
    assert event.geometry is not None and event.geometry.type == "Point"
    frame = event.payload["frame_centre"]
    assert event.geometry.coordinates == [frame["lon"], frame["lat"]], (
        "Event.geometry is not the frame centre. §8.40 makes the target location conditional on "
        "its own face — 'if different from frame center' — and the frame centre is unconditional"
    )
    assert len(event.geometry.coordinates) == 2, (
        "the geometry gained a third coordinate. Tag 25 is MSL and Position.alt_m is HAE; an "
        "unlabelled third element would carry the same mismatch with nothing to name it"
    )
    assert event.payload["target_location"]["lat"] is not None
    assert "never reconciled" in event.payload["target_location"]["basis"].lower() \
        or "NEVER reconciled" in event.payload["target_location"]["basis"]


def test_position_takes_the_sensor_angles_and_leaves_altitude_empty():
    """MSL against HAE, and the decline is on the object rather than in a comment."""
    entity, _ = adapter().to_cdm(
        (FIXTURES / "witnessed_set_from_the_documents_own_examples.klv").read_bytes())
    assert entity.position is not None
    assert entity.position.alt_m is None, (
        "Position.alt_m was filled from tag 15, which §8.15 measures 'from Mean Sea Level (MSL)' "
        "while the field is documented as 'Metres HAE'. Items 75 and 104 are the HAE twins and "
        "neither is witnessed"
    )
    assert entity.position.accuracy_m is None
    assert entity.position.position_source is PositionSource.GNSS
    basis = entity.attributes["position_basis"]
    assert "Metres HAE" in basis["alt_m"] and "Tag 75" in basis["alt_m"]
    assert "lever arm" in basis["what_this_position_IS"]
    assert "GPS/INS" in basis["position_source"]
    assert entity.attributes["sensor_true_altitude_msl_m"] is not None
    assert entity.kinematics is not None
    assert entity.kinematics.course_deg is None, (
        "course_deg was filled from tag 5, which is a HEADING. Tag 112 is the Platform Course "
        "Angle and it is neither witnessed nor free of park 5"
    )
    assert entity.attributes["platform_heading_deg"] is not None


def test_the_checksum_is_verified_and_a_failure_is_flagged_rather_than_refused():
    """The first REAL integrity gate in a binary adapter here, and the first flagged failure."""
    good, _ = adapter().to_cdm((FIXTURES / "mandatory_items_only.klv").read_bytes())
    assert good.attributes["integrity_basis"]["valid"] is True
    bad, bad_event = adapter().to_cdm(
        (FIXTURES / "a_checksum_that_does_not_validate_is_flagged_not_refused.klv").read_bytes())
    integrity = bad.attributes["integrity_basis"]
    assert integrity["valid"] is False
    assert integrity["stored"] == 0 and integrity["computed"] != 0
    assert bad_event.payload["integrity"]["checksum_valid"] is False
    assert "§6.6" in integrity["range"]
    assert "one item among 26" in integrity["why_a_failure_is_not_a_refusal"]


# ------------------------------------------------------------------ egress, and the twins


@pytest.mark.parametrize("path", payloads(), ids=lambda p: p.stem)
def test_egress_reproduces_every_fixture_byte_for_byte(path):
    """raw -> CDM -> raw, byte-exact, which the harness reports as SKIP for a binary adapter.

    Byte-exactness rather than value-equality, and the difference matters twice here: a value that
    arrived quantised would come back rounded to its item's Resolution, and the length-divergent
    item has no value at all to re-encode. Egress replays the octets ingest parked, so both cases
    are exact and the test can actually fail.
    """
    raw = path.read_bytes()
    instance = adapter()
    assert instance.from_cdm(instance.to_cdm(raw)) == raw


@pytest.mark.parametrize("path", payloads(), ids=lambda p: p.stem)
def test_the_parsed_twin_and_the_payload_produce_the_same_cdm(path):
    """Asserted, not assumed — `stanag4676.py` had to add this after the two paths drifted.

    Here they cannot drift by construction: the parsed form carries the Universal Label, the BER
    length octets and every item's Value verbatim, so the dict path reassembles the packet and
    hands it to the same decoder. This test is what keeps that construction from being replaced by
    a field-by-field translation that looks equivalent.
    """
    parsed = json.loads((FIXTURES / f"{path.stem}.parsed.json").read_text())
    assert dumped(adapter().to_cdm(path.read_bytes())) == dumped(adapter().to_cdm(parsed))


@pytest.mark.parametrize("path", payloads(), ids=lambda p: p.stem)
def test_every_fixture_is_lossless_over_its_parsed_form_with_nothing_excused(path):
    """`TRANSFORMS` is empty, so the never-drop check runs at full strength.

    Restated here rather than left to the harness because the harness's verdict for these fixtures
    is a PASS on an empty exemption list, and an empty exemption list is the claim.
    """
    assert Stanag4609Adapter.TRANSFORMS == {}
    parsed = json.loads((FIXTURES / f"{path.stem}.parsed.json").read_text())
    missing = lossless.unrepresented(parsed, dumped(adapter().to_cdm(parsed)),
                                     Stanag4609Adapter.TRANSFORMS)
    assert missing == {}, f"{path.stem}: {missing}"


def test_a_parsed_fixture_whose_stated_verdict_disagrees_with_its_octets_is_refused():
    """Two independent statements of one fact, each checkable against the other.

    The pin gate's arrangement, applied to a fixture. A hand-edited twin that claims no defect over
    octets that carry one would otherwise teach a golden file a falsehood.
    """
    parsed = json.loads(
        (FIXTURES / "length_divergence_at_a_required_length.parsed.json").read_text())
    assert parsed["packets"][0]["defects"], "the fixture under test states no defect to remove"
    parsed["packets"][0]["defects"] = []
    with pytest.raises(Stanag4609ParseError, match="length policy derives"):
        adapter().to_cdm(parsed)

    parsed = json.loads((FIXTURES / "mandatory_items_only.parsed.json").read_text())
    parsed["packets"][0]["checksum"]["computed"] += 1
    with pytest.raises(Stanag4609ParseError, match="§6.6"):
        adapter().to_cdm(parsed)


def test_egress_refuses_an_entity_that_did_not_come_from_this_adapter():
    """Egress replays parked octets and does not synthesise a packet from canonical fields.

    Stated as a refusal because the alternative is worse than an error: 26 items reach four CDM
    fields, so a packet rebuilt from the fields alone would be a packet this adapter invented.
    """
    entity, _ = adapter().to_cdm((FIXTURES / "mandatory_items_only.klv").read_bytes())
    stripped = entity.model_copy(update={"attributes": {}})
    with pytest.raises(Stanag4609ParseError, match="did not come from this adapter"):
        adapter().from_cdm([stripped])
    with pytest.raises(Stanag4609ParseError, match="at least one Entity"):
        adapter().from_cdm([])


# ------------------------------------------------------------------ the pinned real stream


@needs_stream
def test_the_pinned_stream_still_hashes_to_its_pin():
    raw = STREAM.read_bytes()
    assert len(raw) == STREAM_BYTES
    assert hashlib.sha256(raw).hexdigest() == STREAM_SHA


@needs_stream
def test_the_witnessed_set_is_what_the_pinned_stream_actually_carries():
    """The scope contract, re-derived from the octets on every suite run.

    This is the assertion that keeps "the witnessed set" a measurement rather than a list somebody
    typed: the codec's `WITNESSED_TAGS` has to be exactly the distinct tags the stream carries, in
    both directions. A round that widened the table without a second stream fails here.
    """
    packets = uas.decode_stream(STREAM.read_bytes())
    assert len(packets) == 6
    assert all(len(p.order) == 26 for p in packets)
    assert sum(len(p.order) for p in packets) == 156
    assert len({p.order for p in packets}) == 1
    assert tuple(sorted({t for p in packets for t in p.order})) == uas.WITNESSED_TAGS
    assert all(p.checksum_valid for p in packets)
    assert all(p.unknown_tags == () for p in packets)
    defects = [(d.tag, d.divergence_class, d.observed_length) for p in packets for d in p.defects]
    assert defects == [(22, uas.DIVERGENCE_REQUIRED_LENGTH, 4)] * 6, (
        "the pinned stream's only length divergence is item 22 at four octets, at all six sites. "
        "Park 13 ruled it a stream defect and 155 of the 156 items are conformant"
    )


@needs_stream
def test_egress_reproduces_the_pinned_stream_including_the_defective_item():
    """977 octets, byte for byte, tag 22's four non-conformant ones included.

    The strongest available statement that nothing moved — and the one that would fail if egress
    "helpfully" re-encoded the defect at its conformant length, which would be this adapter
    correcting a stream it was asked to translate.
    """
    raw = STREAM.read_bytes()
    instance = adapter()
    objects = instance.to_cdm(raw)
    assert len(objects) == 12
    assert instance.from_cdm(objects) == raw
    entity = objects[0]
    assert entity.attributes["klv_item_octets"]["22"] == "000001c9"


@needs_stream
def test_the_pinned_streams_values_are_all_inside_their_own_stated_ranges():
    """The standing rule, applied rather than assumed.

    "A witnessed tag whose observed values contradict the held documents' declared semantics stops
    the round for adjudication before mapping." It did not fire, and this is the check that says so
    on every run rather than once in a report: every decoded value is inside the Min/Max its own
    §8.x block states, and no Special Value occurs anywhere in the stream.
    """
    for packet in uas.decode_stream(STREAM.read_bytes()):
        for tag, entry in packet.items.items():
            item = uas.ITEMS[tag]
            assert not isinstance(entry.value, uas.SpecialValue), (
                f"tag {tag} carries its Special Value in the pinned stream, which no round has "
                "recorded"
            )
            if item.klv_format == "utf8" or item.software_format == item.klv_format:
                continue
            assert item.software_min <= entry.value <= item.software_max, (
                f"tag {tag} decodes to {entry.value} outside §{item.section}'s stated "
                f"[{item.software_min}, {item.software_max}]"
            )


@needs_stream
def test_the_two_observations_the_round_filed_are_still_true_of_the_bytes():
    """Both are observations rather than findings, and both are measured here.

    Filed on the walk round's PES footing: a measured case waiting for whoever wants it. Asserted
    so that "the emitter reports the target location as the frame centre" stays a fact about these
    octets and does not drift into a general claim about the format.
    """
    for packet in uas.decode_stream(STREAM.read_bytes()):
        assert packet.raw_items[40] == packet.raw_items[23]
        assert packet.raw_items[41] == packet.raw_items[24]
        assert packet.raw_items[42] == packet.raw_items[25]
    first = uas.decode_stream(STREAM.read_bytes())[0]
    # The frame-centre elevation disagrees with the geometry the other items imply, by ~700 m.
    # Recorded, NOT acted on: reaching it means combining five items into a quantity neither
    # document asks a translator to compute, and every one of the five is inside its stated range.
    assert first.items[25].value < 0 < first.items[15].value


@needs_stream
def test_no_fixture_carries_a_VALUE_that_only_the_pinned_stream_states():
    """The claim is about VALUES, and the first draft of this test asserted something false.

    It compared raw eight-octet runs and failed immediately on the Universal Label — sixteen octets
    that ST 0601.14a §6.2 registers and that every conformant packet in the world carries. A run
    shared with the stream is not evidence of anything; a *value* that only the stream states is.

    So the check is per item and it has one licensed exception, which is the interesting case rather
    than a loophole: a fixture item may carry the same octets as the stream's item of the same tag
    when those octets are the DOCUMENT's own Example KLV Value. Item 12 is exactly that — §8.12
    prints `Geodetic WGS84` and the pinned stream carries it at all six sites, byte-identical — and
    excluding it would mean the value-carrying fixture could not use the document's own example for
    one of its 26 items.
    """
    assert STREAM.parent.name == "streams"
    assert not (FIXTURES / "day_flight.klv").exists()
    stream_values = {tag: octets
                     for packet in uas.decode_stream(STREAM.read_bytes())
                     for tag, octets in packet.raw_items.items()}
    licensed = []
    for path in sorted(FIXTURES.glob("*.klv")):
        for packet in uas.decode_stream(path.read_bytes()):
            for tag, octets in packet.raw_items.items():
                if stream_values.get(tag) != octets:
                    continue
                item = uas.ITEMS.get(tag)
                assert item is not None and octets.upper() == item.example_octets.upper(), (
                    f"{path.name} carries tag {tag} with the octets {octets!r} that the pinned "
                    "stream carries, and they are not §%s's own Example KLV Value. Every fixture "
                    "octet is synthetic or the standard's; a real emitter's value in a golden file "
                    "makes this suite a place where somebody else's stream lives"
                    % (item.section if item else "?")
                )
                licensed.append((path.stem, tag))
    assert {tag for _, tag in licensed} == {12}, (
        f"the licensed coincidences are {sorted(set(licensed))}. Exactly one item's Example KLV "
        "Value is also what the pinned stream carries — item 12, 'Geodetic WGS84' — and a second "
        "one appearing is a fact about the stream worth recording rather than waving through"
    )


def test_the_generator_is_the_only_thing_that_writes_these_payloads():
    """A hand-edited `.klv` is a byte nothing cites — the house rule, applied to the tenth set."""
    module = _build_fixtures_module()
    assert len(module.ADAPTER_FIXTURES) == 10
    for spec in module.ADAPTER_FIXTURES:
        payload = FIXTURES / f"{spec['name']}.klv"
        assert payload.read_bytes() == spec["octets"], (
            f"{payload.name} on disk is not what build_fixtures.py produces"
        )
        twin = json.loads((FIXTURES / f"{spec['name']}.parsed.json").read_text())
        assert twin == parse_payload(spec["octets"]), (
            f"{spec['name']}.parsed.json is not the parsed form of its own payload"
        )
        assert set(twin) == {"payload", "packets"}, (
            "the parsed twin carries something besides the payload. The lossless check harvests "
            "every leaf of a JSON fixture and requires each to appear in the CDM output, so a "
            "purpose string here would have to be echoed into an object to pass — which is why "
            "each fixture's purpose lives in fixtures/klv/README.md"
        )


def test_the_epoch_constant_is_the_one_the_document_states():
    assert EPOCH == dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
