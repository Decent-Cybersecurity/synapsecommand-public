"""`klv_vmti_codec`, held to MISB ST 0903.4's own tables and to its own worked examples.

WHAT THIS MODULE CHECKS, AND WHY THE DOCUMENT-SIDE HALF IS THE LOAD-BEARING ONE
--------------------------------------------------------------------------------
The pinned stream this repository holds carries **no item 74** — `fixtures/klv/streams/
day_flight.klv`'s 26 items stop at tag 65 — so nothing below is witnessed by a wire anybody has
met. That is the same footing park 5's rows stand on and it is stated rather than glossed: what
witnesses this layer is the document's own Appendix A, which prints an `Example Value` /
`Example Encoded LS Value` pair for each of its 75 entries.

`check_against_the_documents_own_examples()` decodes every one of those pairs that carries octets
and reports one line each. This module asserts the shape of that report — every line AGREE except
the two the ruling of 2026-09-05 names — so the codec cannot drift from the document without the
suite saying which clause it drifted from.

THE THREE DISAGREEMENTS ARE ASSERTED TO BE EXACTLY THREE
----------------------------------------------------------
A fourth would mean either this transcription or M's ruling has moved, and both are a person's.
The count is asserted in both directions for `test_cdm_prose_counts.py`'s reason: a check that
tolerates "at least the known ones" passes just as happily on a codec that has stopped decoding.
"""
import pytest

from synapse_cdm.adapters import klv_vmti_codec as vmti
from synapse_cdm.adapters.klv_vmti_codec import (
    FpaIndex, Location, MaskRun, VmtiError, decode_bit_mask, decode_location_pack,
    decode_series, decode_vmti_local_set, decode_vtarget_pack,
)

REPORT = vmti.check_against_the_documents_own_examples()


# ==================== the document-side witness


def test_every_printed_example_reproduces_except_the_two_that_are_ruled():
    disagreements = [line for line in REPORT[:-1] if line.startswith("DISAGREE")]
    assert len(disagreements) == 2, (
        "ST 0903.4's printed examples reproduce except for the two M ruled on 2026-09-05 — the "
        "VMask LS Bit Mask octets and the VTracker LS Track ID framing. This run found "
        f"{len(disagreements)}:\n" + "\n".join(disagreements)
    )
    assert all("Bit Mask" in line or "Track ID" in line for line in disagreements), disagreements


def test_the_report_covers_every_element_table_the_document_prints_an_example_for():
    """The report is not allowed to shrink quietly: 70 decodable printed examples, counted."""
    assert len(REPORT) == 71, REPORT[-1]           # 70 rows plus the summary line
    assert REPORT[-1].startswith("70 printed examples decoded, 68 AGREE and 2 DISAGREE")


def test_the_ruled_disagreements_are_three_and_each_names_what_arbitrates():
    assert len(vmti.PRINTED_EXAMPLE_DISAGREEMENTS) == 3
    for key, record in vmti.PRINTED_EXAMPLE_DISAGREEMENTS.items():
        assert set(record) == {"clause", "printed", "the_table_gives", "what_arbitrates", "so"}, key
        assert record["clause"].startswith("§"), key


# ==================== the two fixtures built from the derivation


def test_the_bit_mask_fixture_is_the_derivation_and_the_printed_octets_are_kept_beside_it():
    """Figure 12's 16x9 frame decides it: 74, 89 and 106 exist in a 144-pixel frame; 330 does not."""
    derived = vmti.VMASK_BIT_MASK_FROM_THE_DERIVATION
    runs = decode_bit_mask(bytes.fromhex(derived["octets"]))
    assert runs == (MaskRun(74, 2), MaskRun(89, 4), MaskRun(106, 2))
    assert tuple((run.pixel, run.run) for run in runs) == derived["runs"]
    # every derived pixel number is inside the frame the example's own figure draws
    assert all(1 <= run.pixel <= 16 * 9 for run in runs)
    # and the printed octets, kept beside it, are the ones that are not
    printed = decode_bit_mask(bytes.fromhex(derived["printed_and_refuted"]))
    assert [run.pixel for run in printed] == [330, 345, 362]
    assert all(run.pixel > 16 * 9 for run in printed)
    # the outer length does not move: only a high octet does
    assert len(bytes.fromhex(derived["octets"])) == 15 == len(
        bytes.fromhex(derived["printed_and_refuted"]))


def test_the_track_id_fixture_carries_the_framing_the_row_states():
    derived = vmti.VTRACKER_TRACK_ID_FROM_THE_DERIVATION
    octets = bytes.fromhex(derived["octets"])
    assert octets[0] == 0x01, "the row's own KLV Encoding block reads VTracker LS Tag 1"
    assert octets[1] == 0x10, "the row's own Length cell reads 16 Bytes"
    assert octets[2:].hex() == derived["uuid"]
    decoded = vmti._decode_nested("vtracker", octets)
    assert decoded.elements[1].value == derived["uuid"]
    # and the printed framing does not parse as the row it sits in
    printed = bytes.fromhex(derived["printed_and_refuted"])
    assert (printed[0], printed[1]) == (0x10, 0x04)


# ==================== the grammars, each against the clause that states it


def test_a_series_is_length_value_pairs_to_the_end_of_the_span():
    """`ST 0903.4-06` and footnote 5: no key, a BER length and a value, member count discovered."""
    assert decode_series(bytes.fromhex("0239AA0239BF023B0B")) == (
        bytes.fromhex("39AA"), bytes.fromhex("39BF"), bytes.fromhex("3B0B"))
    assert decode_series(b"") == ()


def test_a_series_member_may_not_run_past_its_pack():
    with pytest.raises(VmtiError, match="Series member"):
        decode_series(bytes.fromhex("0439AA"))


def test_a_vtarget_pack_is_a_tagless_ber_oid_identifier_then_triplets():
    """§9.1's own smallest case: "a VTarget Pack can consist of just the Target ID Number and the
    Target Centroid Pixel Number." Built from the document's own two worked examples."""
    pack = decode_vtarget_pack(bytes.fromhex("1B" + "0103064000"))
    assert pack.target_id == 27
    assert pack.elements[1].value == 409600
    assert pack.order == (1,)
    assert pack.refusals == ()


def test_a_multi_octet_target_id_is_read_as_ber_oid_and_not_as_an_integer():
    """The document's own 1234 -> [0x89 52], which as a plain integer would read 35154."""
    pack = decode_vtarget_pack(bytes.fromhex("8952" + "0103064000"))
    assert pack.target_id == 1234


def test_an_empty_vtarget_pack_is_refused_by_the_two_requirements_that_forbid_it():
    with pytest.raises(VmtiError, match="ST 0903.4-09"):
        decode_vtarget_pack(b"")


def test_the_vmti_local_set_lifts_its_targets_out_of_tag_101():
    """One VMTI LS carrying the frame's own counts and a VTargetSeries of two packs."""
    target_one = "1B" + "0103064000"
    target_two = "1C" + "0103064001"
    series = f"{len(target_one) // 2:02X}{target_one}{len(target_two) // 2:02X}{target_two}"
    octets = bytes.fromhex(
        "050102"          # tag 5, Total Number of Targets Detected in the Frame = 2
        "060102"          # tag 6, Number of Reported Targets = 2
        "0802" "0780"     # tag 8, Frame Width  = 1920
        "0902" "0438"     # tag 9, Frame Height = 1080
        f"65{len(series) // 2:02X}{series}"
    )
    decoded = decode_vmti_local_set(octets)
    assert decoded.elements[5].value == 2
    assert decoded.elements[8].value == 1920
    assert [target.target_id for target in decoded.targets] == [27, 28]
    assert decoded.targets[0].elements[1].value == 409600
    assert decoded.refusals == ()
    assert decoded.order == (5, 6, 8, 9, 101)


def test_an_unlisted_tag_is_carried_and_skipped_rather_than_refusing_the_set():
    """ST 0107.3-04, applied one document over — the octets survive and the set still decodes."""
    decoded = decode_vmti_local_set(bytes.fromhex("0802" "0780" "6402" "DEAD"))
    assert decoded.elements[8].value == 1920
    assert decoded.unlisted == (100,)
    assert decoded.refusals[0].octets == "dead"
    assert "ST 0107.3-04" in decoded.refusals[0].clause


def test_a_variable_length_integer_longer_than_its_maximum_is_refused():
    """`ST 0903.4-04`. Frame Width is V3; four octets is a malformed element, not a bigger number."""
    decoded = decode_vmti_local_set(bytes.fromhex("0804" "00000780"))
    assert decoded.elements == {}
    assert decoded.refusals[0].refusal_class == vmti.LENGTH_EXCEEDS_THE_STATED_MAXIMUM
    assert "ST 0903.4-04" in decoded.refusals[0].clause


def test_zero_in_more_than_one_octet_is_refused_by_the_requirement_that_names_it():
    """`ST 0903.4-05`, which exists precisely so that this case is not a matter of taste."""
    decoded = decode_vmti_local_set(bytes.fromhex("0802" "0000"))
    assert decoded.refusals[0].refusal_class == vmti.ZERO_NOT_ENCODED_IN_ONE_BYTE


def test_a_fixed_length_element_at_the_wrong_length_is_refused():
    """Target Priority is F1. §8.3's variable-length allowance does not reach an Fn element."""
    pack = decode_vtarget_pack(bytes.fromhex("1B" + "0402" + "001B"))
    assert pack.elements == {}
    assert pack.refusals[0].refusal_class == vmti.LENGTH_IS_NOT_THE_FIXED_LENGTH


# ==================== the truncation packs, at their group boundaries


def test_a_location_pack_may_end_at_any_of_its_three_group_boundaries():
    """`ST 0903.4-62`: truncation "shall be allowed only at a group boundary"."""
    coordinates = "42800000" "48800000" "2A94"
    sigmas = "2580" "1900" "0C80"
    rhos = "7000" "6000" "5000"
    short = decode_location_pack(bytes.fromhex(coordinates))
    assert (short.latitude, short.longitude, short.height) == (43.0, 110.0, 10000.0)
    assert short.sigma_east is None and short.rho_east_north is None
    middle = decode_location_pack(bytes.fromhex(coordinates + sigmas))
    assert (middle.sigma_east, middle.sigma_north, middle.sigma_up) == (300.0, 200.0, 100.0)
    assert middle.rho_east_north is None
    full = decode_location_pack(bytes.fromhex(coordinates + sigmas + rhos))
    assert (full.rho_east_north, full.rho_east_up, full.rho_north_up) == (0.75, 0.50, 0.25)
    assert isinstance(full, Location)


def test_a_location_pack_truncated_off_a_group_boundary_is_refused():
    with pytest.raises(VmtiError, match="ST 0903.4-62"):
        decode_location_pack(bytes.fromhex("42800000" "48800000" "2A94" "2580"))


def test_a_boundary_series_is_a_series_of_location_packs():
    """Table 12: "A Series of Location data elements, one for each vertex of a bounding area"."""
    member = "42800000" "48800000" "2A94"
    octets = bytes.fromhex(f"0A{member}0A{member}")
    vertices = vmti.decode_boundary_series(octets)
    assert len(vertices) == 2
    assert vertices[0].latitude == 43.0


def test_the_fpa_index_pack_is_row_then_column_as_its_own_table_orders_it():
    assert vmti.decode_fpa_index(bytes.fromhex("0203")) == FpaIndex(row=2, column=3)
    with pytest.raises(VmtiError, match="F2"):
        vmti.decode_fpa_index(bytes.fromhex("02"))


# ==================== what this layer refuses to say, and what it is not


def test_no_cdm_object_is_built_anywhere_in_this_module():
    """The round's own boundary, asserted rather than promised in a docstring.

    Park 6's mapping question is what a VTarget BECOMES, and this layer does not answer it. The
    check is structural: the module imports nothing from `synapse_cdm.models`, so it could not
    build an Entity, an Event or a Track even by accident.
    """
    source = (vmti.__file__ or "")
    assert source.endswith("klv_vmti_codec.py")
    text = open(source).read()
    for forbidden in ("from ..models", "from synapse_cdm.models", "import models",
                      "EventType", "Entity(", "Event(", "Track("):
        assert forbidden not in text, f"{forbidden!r} appears in the VMTI codec"


def test_the_external_ontologies_are_carried_and_never_resolved():
    decoded = vmti._decode_nested("vobject", bytes.fromhex(
        "010B" + "687474703A2F2F612E62"[:20] + "01" + "0223" +
        "4469736D6F756E742F4E6F6E2D636F6D626174616E742F46656D616C652F4368696C64"))
    assert decoded.elements[2].value == "Dismount/Non-combatant/Female/Child"
    assert isinstance(decoded.elements[1].value, str)
    assert "EXTERNAL_CODE_LISTS_NOT_HELD" in vmti.EXTERNAL_ONTOLOGIES_NOT_RESOLVED


def test_the_vtrack_local_set_is_recorded_as_out_of_item_74s_reach():
    """§9.1's sentence, and §10's preference for the carrier item 74 cannot deliver."""
    assert "always independent of MISB ST 0601" in vmti.VTRACK_LS_IS_OUT_OF_ITEM_74S_REACH
    assert "Use of VTracker is discouraged" in vmti.VTRACK_LS_IS_OUT_OF_ITEM_74S_REACH
    assert 13 not in vmti.VMTI_LS or vmti.VMTI_LS[13].name == "Motion Imagery ID"


def test_the_tables_are_the_sizes_the_document_prints():
    """Tables 1-7 by their row counts, which is the transcription's cheapest cross-check."""
    assert len(vmti.VMTI_LS) == 14                      # Table 1: 15 UL rows = 1 key + 14 elements
    # Table 2: 28 UL rows = 1 key + 27 tagged elements. The Target ID Number is a 29th ROW with no
    # UL and no tag at all — its Tag ID and Key Value cells both read `N/A`, matching Appendix A's
    # `Universal Label NA` — so it is a field of `VTargetPack` rather than an entry in this table.
    assert len(vmti.VTARGET_PACK) == 27
    assert len(vmti.VMASK_LS) == 2 and len(vmti.VOBJECT_LS) == 2 and len(vmti.VFEATURE_LS) == 2
    assert len(vmti.VTRACKER_LS) == 11                  # Table 6: 12 rows = 1 key + 11 elements
    assert len(vmti.VCHIP_LS) == 3                      # Table 7: 4 rows = 1 key + 3 elements
    assert len(vmti.LOCATION_PACK) == len(vmti.VELOCITY_PACK) == 9
    assert set(vmti.TRACK_STATUS_VALUES) == {0, 1, 2, 3}
    assert len(vmti.LOCAL_SET_KEYS) == 7
    for key, _crc in vmti.LOCAL_SET_KEYS.values():
        assert len(bytes.fromhex(key)) == 16
