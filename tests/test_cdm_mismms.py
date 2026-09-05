"""MISB ST 0902.8's minimum set, held to the three counts the document states about its own tables.

**A TRANSCRIPTION IS ONLY AS GOOD AS THE FIGURE THAT CHECKS IT.** `klv_mismms.ROWS` is 33 rows of
cells typed off pages 4 and 6 of ST 0902.8, and a typing error in a Tag cell, a dropped row or a
duplicated alternate would all leave a table that reads plausibly. The document prints its own
answer in Table 2's footer row — **"39 Tags  Total 797"** — and that footer is what the first three
tests below re-derive: 39 tag numbers across the rows, and 797 as the sum of the Max Length column.
Neither number is stated in `ROWS`; both are computed from it and compared with the constants,
which are the document's.

The rest of this module is about the state vocabulary, and specifically about the pair
`klv_mismms.NOT_DECODED_BASIS` exists for: `absent` is a statement about the STREAM and
`present_not_decoded` is a statement about THIS REPOSITORY, and a consumer who cannot tell them
apart cannot use either.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from synapse_cdm.adapters import klv_mismms as mismms
from synapse_cdm.adapters import klv_security_codec as security
from synapse_cdm.adapters import klv_uas_codec as uas

FIXTURES = pathlib.Path(mismms.__file__).resolve().parent.parent / "fixtures" / "klv"


def _packet(name: str) -> uas.DecodedPacket:
    return uas.decode_stream((FIXTURES / f"{name}.klv").read_bytes())[0]


# ==================== the document's own three figures


def test_the_transcription_has_the_thirty_three_rows_the_document_draws():
    assert len(mismms.ROWS) == mismms.ROW_COUNT


def test_the_transcription_has_the_thirty_nine_tags_table_2s_footer_counts():
    """Table 2's footer reads `39 Tags`, and 39 is a count of TAG NUMBERS across 33 ROWS.

    The two numbers differ by exactly the eleven extra members of the five alternates rows —
    6|90, 7|91, 15|75|104, 22|96 and 25|78 — which is the arithmetic a dropped alternate breaks
    and a dropped row does not.
    """
    assert sum(len(row.tags) for row in mismms.ROWS) == mismms.TAG_COUNT == 39
    alternates = [row for row in mismms.ROWS if len(row.tags) > 1]
    assert len(alternates) == 5
    assert mismms.TAG_COUNT - mismms.ROW_COUNT == sum(len(r.tags) - 1 for r in alternates)


def test_the_max_length_column_sums_to_the_797_the_footer_states():
    """`Total 797`, with the `*` cells read as the numbers they qualify.

    Four cells print a trailing `*` — 48/3's `6*`, 48/4's and 48/6's `40*`, 48/5's `32*` and
    48/13's `40*` — which ST 0102.12 uses for a maximum rather than a fixed size. They are kept
    as printed in `max_lengths` and stripped only here, because the footer's own total includes
    them: 797 does not come out otherwise.
    """
    total = sum(int(cell.rstrip("*")) for row in mismms.ROWS for cell in row.max_lengths)
    assert total == mismms.TABLE_2_TOTAL_MAX_BYTES == 797


def test_every_row_is_internally_arity_consistent():
    """A row's names, types, lengths and max lengths are one per tag. A typo shows up here."""
    for row in mismms.ROWS:
        arity = len(row.tags)
        assert arity >= 1
        assert (len(row.names) == len(row.klv_types) == len(row.lengths)
                == len(row.max_lengths) == arity), row.key


def test_the_row_keys_are_unique_and_spell_the_documents_own_tag_cells():
    keys = [row.key for row in mismms.ROWS]
    assert len(set(keys)) == len(keys)
    assert "6|90" in keys and "15|75|104" in keys and "48/13" in keys


def test_the_nine_security_rows_are_the_ones_the_document_writes_as_48_slash_n():
    rows = [row for row in mismms.ROWS if row.security_set]
    assert [row.tags[0] for row in rows] == [1, 2, 3, 4, 5, 6, 12, 13, 22]
    assert all(len(row.tags) == 1 for row in rows), "no 48/n row carries an alternate"


# ==================== the two states that must not be conflated


def test_the_not_decoded_set_is_derived_from_the_codec_and_not_typed():
    """The five, and the check that they really are outside the adapter's 44-tag tables.

    Derived at import rather than listed, so wiring one of them later retires it from this set
    without an edit here. The assertion is the derivation's result, which is what a reader wants.
    """
    assert mismms.NOT_DECODED_BY_THIS_ADAPTER == (3, 10, 78, 90, 91)
    covered = set(uas.ITEMS) | set(uas.DOCUMENT_WITNESSED_TAGS)
    assert len(covered) == 44
    for tag in mismms.NOT_DECODED_BY_THIS_ADAPTER:
        assert tag not in covered
        assert tag not in uas.NESTED_SETS and tag != uas.CORE_IDENTIFIER_TAG


def test_a_tag_on_the_wire_that_this_adapter_cannot_decode_is_NOT_reported_as_absent():
    """Ruling 4's whole subject, on the fixture built for it.

    Tags 3 and 10 are in the packet and outside the codec's tables. `present_not_decoded` says
    the item was reported and its value is out of reach; `absent` would say the producer never
    sent it. The two are different claims about a third party's stream.
    """
    reading = mismms.read_packet(_packet("every_row_of_the_minimum_set_reported_in_one_packet"))
    for key in ("3", "10"):
        member = reading["rows"][key]["tags"][key]
        assert member["state"] == mismms.STATE_PRESENT_NOT_DECODED
        assert member["octet_length"] > 0
        assert reading["rows"][key]["state"] == mismms.ROW_REPORTED


def test_a_security_sub_tag_is_never_read_through_the_top_level_not_decoded_set():
    """The collision this module found: `48/3` is not ST 0601 tag 3.

    `NOT_DECODED_BY_THIS_ADAPTER` numbers ST 0601 items; the nine security rows number ST 0102.12
    elements, and 3 is in both spaces. Unqualified, the membership test reported `48/3`
    Classifying Country as undecodable while `klv_security_codec` was decoding it.
    """
    assert 3 in mismms.NOT_DECODED_BY_THIS_ADAPTER
    assert 3 in security.ELEMENTS
    reading = mismms.read_packet(_packet("every_row_of_the_minimum_set_reported_in_one_packet"))
    assert reading["rows"]["48/3"]["tags"]["3"]["state"] == mismms.STATE_PRESENT
    for row in (r for r in mismms.ROWS if r.security_set):
        state = reading["rows"][row.key]["tags"][str(row.tags[0])]["state"]
        assert state != mismms.STATE_PRESENT_NOT_DECODED, row.key


def test_a_zero_length_item_is_read_and_is_not_counted_as_reported():
    """`ST 0902.8-05`, and the two readings of one item that disagree and are both right."""
    packet = _packet("a_zero_length_minimum_item_does_not_meet_the_reporting_requirement")
    assert isinstance(packet.items[11].value, uas.ZeroLength), "the codec still decodes it"
    reading = mismms.read_packet(packet)
    row = reading["rows"]["11"]
    assert row["state"] == mismms.ROW_NOT_REPORTED
    assert row["tags"]["11"]["state"] == mismms.STATE_ZERO_LENGTH
    assert "Zero-Length" in row["not_reported_because"]


# ==================== the readings themselves


def test_the_full_minimum_set_fixture_reports_every_one_of_the_thirty_three_rows():
    reading = mismms.read_packet(_packet("every_row_of_the_minimum_set_reported_in_one_packet"))
    assert reading["rows_reported"] == 33
    assert reading["rows_not_reported"] == 0
    assert reading["exclusive_or_violation"] is None


def test_an_alternates_row_is_reported_by_any_one_member_and_its_others_stay_absent():
    """Note 1's inclusive or: a ROW's state and a TAG's state are different questions."""
    reading = mismms.read_packet(_packet("every_row_of_the_minimum_set_reported_in_one_packet"))
    for key, present, absent in (("6|90", "6", "90"), ("7|91", "7", "91"),
                                 ("22|96", "22", "96"), ("25|78", "25", "78")):
        row = reading["rows"][key]
        assert row["state"] == mismms.ROW_REPORTED
        assert row["tags"][present]["state"] == mismms.STATE_PRESENT
        assert row["tags"][absent]["state"] == mismms.STATE_ABSENT
    hae = reading["rows"]["15|75|104"]
    assert hae["tags"]["15"]["state"] == mismms.STATE_PRESENT
    assert hae["tags"]["75"]["state"] == hae["tags"]["104"]["state"] == mismms.STATE_ABSENT


def test_the_documents_own_dynamic_only_packet_is_short_of_the_set_and_still_translates():
    """The advisory's reason for existing, stated by the document itself.

    ST 0902.8 §10 prints this packet as a legal MISMMS transmission and Annex A says a packet
    need not carry every item. Fourteen rows read `not_reported` and every one is `absent`, and
    nothing about the packet is refused.
    """
    name = "the_documents_own_dynamic_only_packet_reports_nineteen_of_the_thirty_three_rows"
    packet = _packet(name)
    reading = mismms.read_packet(packet)
    assert reading["rows_reported"] == 19
    assert reading["rows_not_reported"] == 14
    not_reported = [k for k, v in reading["rows"].items() if v["state"] == mismms.ROW_NOT_REPORTED]
    assert not_reported == ["3", "10", "11", "12", "48/1", "48/2", "48/3", "48/4", "48/5",
                            "48/6", "48/12", "48/13", "48/22", "94"]
    assert all(member["state"] == mismms.STATE_ABSENT
               for key in not_reported
               for member in reading["rows"][key]["tags"].values())


def test_the_annex_c_packets_own_checksum_validates_over_the_octets_as_printed():
    """**THE DOCUMENT ADJUDICATES ITS OWN MISPRINT AND THIS IS THE DERIVATION.**

    ST 0902.8 §10 prints the "Dynamic Only" packet twice and the two printings disagree at Tag 20:
    Table 11's row reads `14 04 7D C5 5E CE`, the complete-packet hex reads `14 04 00 00 00 00`.
    Both printings state the same Tag 1 Checksum, `0xC850`. ST 0601.14a §6.6's sum recomputes to
    `0xC850` over the octets as the complete packet prints them, so the complete packet is
    self-consistent and Table 11's row is the misprint. The fixture carries the former.

    This is not M's tables-beat-examples ruling: Annex C is titled "Informative" throughout, so
    both printings are illustrations and nothing normative is in tension. It is recorded because
    it was checkable, and the checksum is what checked it.
    """
    name = "the_documents_own_dynamic_only_packet_reports_nineteen_of_the_thirty_three_rows"
    packet = _packet(name)
    assert packet.checksum_stored == packet.checksum_computed == 0xC850
    assert packet.value_length == 0x61 == 97, "the BER short-form length the document states"
    assert packet.items[20].raw == bytes(4), "Tag 20 as the complete-packet hex prints it"


def test_an_item_the_length_policy_skipped_is_still_reported_and_says_so():
    """Presence and populated-correctly are two questions and the annotation keeps them apart."""
    packet = _packet("length_divergence_at_a_required_length")
    assert 22 not in packet.items, "the length policy skipped it"
    row = mismms.read_packet(packet)["rows"]["22|96"]
    assert row["state"] == mismms.ROW_REPORTED
    assert row["tags"]["22"]["length_policy_skipped"] == uas.DIVERGENCE_REQUIRED_LENGTH
    assert "ST 0902.3-03" in row["tags"]["22"]["length_policy_note"]


# ==================== the annotation, where a consumer meets it


@pytest.mark.parametrize("name", [
    "every_row_of_the_minimum_set_reported_in_one_packet",
    "the_documents_own_dynamic_only_packet_reports_nineteen_of_the_thirty_three_rows",
    "a_zero_length_minimum_item_does_not_meet_the_reporting_requirement",
    "mandatory_items_only",
])
def test_the_reading_rides_on_every_entity_and_never_refuses_a_packet(name):
    """`length_divergence_policy`'s precedent: on every object, not only the ones that fell short.

    And the packet always translates — the assertion that this is an ADVISORY is that an Entity
    exists at all for the fixture that reports 5 of 33 rows.
    """
    golden = json.loads((FIXTURES / "golden" / f"{name}.cdm.json").read_text())
    entities = [o for o in golden if o["object_kind"] == "entity"]
    assert entities, "the packet translated"
    for entity in entities:
        reading = entity["attributes"]["mismms_conformance"]
        assert reading["rows_total"] == 33
        assert len(reading["rows"]) == 33
        assert reading["rows_reported"] + reading["rows_not_reported"] == 33
        assert "never a refusal" in reading["advisory_and_never_a_refusal"].lower() \
            or "NOT A CONFORMANCE VERDICT" in reading["advisory_and_never_a_refusal"]


def test_the_annotation_carries_the_requirement_it_is_about_and_not_a_paraphrase():
    reading = mismms.read_packet(_packet("mandatory_items_only"))
    assert reading["requirement"] == mismms.REQUIREMENTS["ST 0902.3-04"]
    assert "no less than once every thirty (30) seconds" in reading["requirement"]
    assert reading["not_decoded_by_this_adapter"] == [3, 10, 78, 90, 91]


def test_the_five_requirement_ids_are_contiguous_and_carry_two_edition_prefixes():
    """The `st_0107_3` finding a third time: an ID names the edition that INTRODUCED it.

    Four of the five read `ST 0902.3-` inside a document whose cover says 0902.8, and only -05 —
    the one this edition's Revision History records as added — reads `ST 0902.8-`.
    """
    ids = sorted(mismms.REQUIREMENTS)
    assert [i.rsplit("-", 1)[1] for i in ids] == ["01", "02", "03", "04", "05"]
    assert sum(i.startswith("ST 0902.3-") for i in ids) == 4
    assert [i for i in ids if i.startswith("ST 0902.8-")] == ["ST 0902.8-05"]
    assert "DEPRECATED" in mismms.REQUIREMENTS["ST 0902.3-02"]


def test_the_exclusive_or_note_fires_only_when_both_75_and_104_are_carried():
    """Note 1's one exception, recorded and NOT refused. No fixture here carries both."""
    for name in ("mandatory_items_only", "every_row_of_the_minimum_set_reported_in_one_packet"):
        assert mismms.read_packet(_packet(name))["exclusive_or_violation"] is None
