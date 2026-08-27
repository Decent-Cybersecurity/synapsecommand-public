"""The KLV framing layer: the rules two documents establish, and the two absences that remain.

WHAT THIS MODULE GUARDS THAT NOTHING ELSE DOES
-----------------------------------------------
`tests/test_cdm_format_coverage.py` guards the STANAG 4609 section's pins, its 141-row tag table and
its park roster. It has nothing to say about the framing layer, because until 2026-08-26 there was
none: the section's own preamble said so — "parks 4 and 8 own how a key and a length are written".

**Three rounds that day took it apart.** The tag-table round closed park 1 and made the stream
*nameable*. The framing round asked whether ST 0601.14a states its own framing and found that **two
thirds of it does** — the Universal Label (§6.2), the BER-OID tag form (§7.1 and Figure 67) and the
checksum (§6.6, §8.1.1.1–2) — while the **length** grammar was delegated, so `decode_ber_length`,
`encode_ber_length` and `walk_local_set` shipped as refusals naming the park. The length round
followed the delegation: `ST 0601.8-03` points at **MISB ST 0107.3**, six pages, and that document
states the grammar. **Park 4 is closed, the three refusals are gone, and `klv_codec` walks a local set
end to end.**

THE FAILURE MODE IT IS SHAPED AROUND — AND IT INVERTED
-------------------------------------------------------
The framing round's hazard ran one way: somebody with BER in their fingers adds four lines to
`decode_ber_length`, every fixture still passes, the suite goes green, and this repository ships a
length grammar it read nowhere. So the refusals were asserted as positively as the acceptances.

**ST 0107.3's rule is the same rule everybody can recite, which is why that guard could not simply be
deleted.** A codec written from memory passes every test in this file. What the tests can still hold
is the **citation**: every length assertion here names the sentence or the worked octets it enforces,
and the two non-minimality refusals are the two inefficiencies §6.3.2 itself names rather than a
general policy somebody remembered. If a later edition of ST 0107 says something else, these tests are
where the disagreement surfaces rather than a place it hides.

**And the polarity of the park gate flipped with it.** The old
`test_parks_four_and_eight_are_stated_OPEN_wherever_this_round_names_them` forbade any site from
claiming a closure, because a narrowed park written up as a closed one was the framing round's most
likely error. The length round's most likely error is the reverse — a closure written up as settling
more than it did — so the gate now requires park 4 CLOSED, park 8 **OPEN**, and forbids any site from
claiming park 8 closed. Park 8 still owns `0x80` as a first length octet and any ceiling on the count
of length octets, and every ruling site is required to name at least one of them.

THE DISJUNCTION PROTOCOL, RUN OVER THE FACTS THESE ROUNDS STATE MORE THAN ONCE
-------------------------------------------------------------------------------
Six sites state the rulings: `FORMAT_COVERAGE.md`, `MIGRATIONS.md`, `klv_pin.json`,
`fixtures/klv/README.md`, `adapters/klv_codec.py` and `fixtures/klv/spec/build_fixtures.py`. Every
fact stated at more than one of them is collected **by regex from the files** and required to agree at
all of them — 80b38d1's finding, which is that an `in` check is satisfied by one site while a fact
stated at six sites can drift at five. The facts are **both** pinned copies' digests, the two park
states, the section citations behind every established rule in **both** rulings, the delegating
requirement identifiers on both sides of the move (`ST 0601.8-07` → `ST 0107.3-05`), and every count
either round introduced.

**The framing round's pin node is history and is not rewritten.** Its `park_4.state_after_this_round`
still reads `OPEN`, which was true of that round, and a test asserts it stays that way: editing it to
agree with a later round would destroy the only evidence that one document could not establish what
two can.
"""
import ast
import json
import pathlib
import re

import pytest

import synapse_cdm
from synapse_cdm.adapters import klv_codec as codec

#: Every path below is anchored on the PACKAGE and not on the repository root, which is what puts
#: this module in `gates/wheel_install.py`'s `PACKAGE_ONLY_TESTS`: the ruling and the artefacts it
#: produced ship together, so the same assertions hold against an installed wheel.
PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent

FIXTURES = PKG / "fixtures" / "klv"
FRAMING = FIXTURES / "framing"
GENERATOR = FIXTURES / "spec" / "build_fixtures.py"
PIN = FIXTURES / "spec" / "klv_pin.json"
README = FIXTURES / "README.md"
DOC = PKG / "FORMAT_COVERAGE.md"
MIGRATIONS = PKG / "MIGRATIONS.md"

#: The copy every citation in this round is read from. The pin record holds it as data; the prose
#: sites hold it abbreviated, and `test_the_pinned_copy_is_the_same_copy_at_every_site` ties the
#: two together rather than letting an abbreviation float free.
ST_0601_14A = "3d5f1ca105befe6f48023a3cdd29262883d6b77c73c06ba915c4da91ab212ce4"
ABBREVIATED = f"{ST_0601_14A[:8]}…{ST_0601_14A[-8:]}"

#: The copy park 4 was closed on. Added by the length round, and held to the same discipline: the
#: pin holds it as data, the prose sites hold it abbreviated, and the two are tied together rather
#: than left to agree by hand.
ST_0107_3 = "500d67522269e5fcbc39bec2521849dffdf2698ff40132552f3fd28998b69794"
ABBREVIATED_0107_3 = f"{ST_0107_3[:8]}…{ST_0107_3[-8:]}"

#: The framing section of FORMAT_COVERAGE.md, by its own heading.
FRAMING_HEADING = "### The framing layer — how a key, a tag and a length are written"


def _build_fixtures_module():
    """Compile the generator IN MEMORY. See `tests/test_cdm_generator_loading.py` for why.

    Not `spec_from_file_location` + `exec_module`: that is the ordinary source loader, it reads and
    writes `__pycache__`, and a `.pyc` is revalidated on the source's mtime in whole seconds and its
    size — which a same-length edit reverted inside one second defeats. This module's whole subject
    is what the SOURCE on disk produces.
    """
    import types
    module = types.ModuleType("klv_build_fixtures")
    module.__file__ = str(GENERATOR)
    exec(compile(GENERATOR.read_text(), str(GENERATOR), "exec"), module.__dict__)
    return module


def _framing_section() -> str:
    text = DOC.read_text()
    start = text.index(FRAMING_HEADING)
    return text[start:text.index("\n### The parks, each with a named reopen condition", start)]


def _flat(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------- what the document establishes


def test_the_universal_label_is_the_sixteen_octets_section_6_2_registers():
    """§6.2's key, octet for octet, and the CRC carried rather than recomputed.

    Written out as a literal here rather than imported and compared to itself. The codec's constant
    is the thing under test, so a test that spelled it `codec.UAS_LOCAL_SET_KEY == codec.UAS_LOCAL_
    SET_KEY` would be checking Python's `==`.
    """
    assert codec.UAS_LOCAL_SET_KEY == bytes.fromhex("060E2B34020B01010E01030101000000")
    assert codec.UAS_LOCAL_SET_KEY_CRC == 56773
    assert codec.KEY_LENGTH == 16 == len(codec.UAS_LOCAL_SET_KEY)
    assert codec.is_local_set_key(codec.UAS_LOCAL_SET_KEY)
    assert codec.read_local_set_key(codec.UAS_LOCAL_SET_KEY + b"\xff") == 16


def test_a_key_that_differs_or_runs_short_is_refused_and_the_two_refusals_are_different():
    """A wrong key and a short buffer are different facts, and the messages say which.

    The distinction matters to a caller downstream: a short buffer is a framing position that may
    become valid when more octets arrive, and a differing octet never will.
    """
    wrong = codec.UAS_LOCAL_SET_KEY[:15] + b"\x01"
    with pytest.raises(codec.KLVFramingError) as differs:
        codec.read_local_set_key(wrong)
    assert "octet 15" in str(differs.value)

    with pytest.raises(codec.KLVFramingError) as short:
        codec.read_local_set_key(codec.UAS_LOCAL_SET_KEY[:15])
    assert "15 octet(s) remain" in str(short.value)
    assert str(short.value) != str(differs.value)


def test_the_ber_oid_width_transition_is_where_section_7_1_puts_it():
    """127 in one octet, 128 in two — §7.1's boundary, asserted on both sides of it.

    §7.1: "Single-byte tags can represent tag numbers from 1 through 127. Tag numbers greater than
    127 use two-bytes (or more)." An off-by-one here would be invisible in ordinary traffic — ST
    0601's assigned tags cluster far below 127 and far below 141 — and catastrophic at exactly the
    two tags either side of the boundary.
    """
    assert codec.BER_OID_SINGLE_OCTET_MAX == 127
    for value in range(0, 128):
        assert len(codec.encode_ber_oid(value)) == 1, value
    for value in range(128, codec.BER_OID_MAX + 1):
        assert len(codec.encode_ber_oid(value)) == 2, value
    assert codec.encode_ber_oid(127) == b"\x7f"
    assert codec.encode_ber_oid(128) == b"\x81\x00"
    # The next transition, which only ST 0107.3 §6.3.1 can place: 16383 → 16384, two octets to
    # three. Seven payload bits per octet, so every transition sits at a power of 2**7.
    assert len(codec.encode_ber_oid(codec.BER_OID_MAX)) == 2
    assert len(codec.encode_ber_oid(codec.BER_OID_MAX + 1)) == 3
    for power in (3, 4, 5):
        assert len(codec.encode_ber_oid((1 << (7 * power)) - 1)) == power, power
        assert len(codec.encode_ber_oid(1 << (7 * power))) == power + 1, power


def test_the_ber_oid_ceiling_is_figure_67s_fourteen_bits_and_is_no_longer_a_limit():
    """16383, because Figure 67 draws two 7-bit payloads and its paragraph says "a 14-bit value".

    Read rather than remembered, which is the point: ST 0601.14a §7.1 states WHERE the width changes
    and never states HOW a multi-octet value is assembled, so without Figure 67 this number would
    have been a recollection with a section number pinned to it.

    **What changed when park 4 closed is what the number MEANS.** It used to be the codec's ceiling
    and `encode_ber_oid(16384)` raised. MISB ST 0107.3 §6.3.1 states the chain rule for any width —
    "This pattern continues until the msb of a final byte in the chain is zero" — so 16383 is now a
    waypoint: the largest value the *delegating* document could establish alone. The constant is kept
    for exactly that reason, and this test asserts both halves so neither can quietly drift.
    """
    assert codec.BER_OID_MAX == (1 << 14) - 1 == 16383
    assert codec.encode_ber_oid(16383) == b"\xff\x7f"

    # No longer a limit. Three octets, per §6.3.1, and the round trip closes.
    assert codec.encode_ber_oid(16384) == b"\x81\x80\x00"
    assert codec.decode_ber_oid(b"\x81\x80\x00") == (16384, 3)
    assert not hasattr(codec, "BER_OID_MAX_OCTETS"), (
        "the two-octet cap is still defined. It was the framing round's honest bound on the '(or "
        "more)' §7.1 never defined, and ST 0107.3 §6.3.1 defines it — a cap left in place beside a "
        "codec that no longer honours it is a constant nothing reads and a claim nobody checks"
    )


def test_the_documents_own_tag_examples_all_decode_to_the_tags_they_are_printed_beside():
    """The positive control, run over the whole assigned space rather than a sample.

    ST 0601.14a prints an "Example KLV Item (All Hex)" row for every one of Table 1's 141 items, and
    the tag field takes exactly `01`–`7F` for tags 1–127 and `8100`–`810D` for 128–141. If the
    continuation bit had been read backwards, or the payload width taken as eight bits rather than
    seven, this check would disagree with the document in the fourteen two-octet cases — which is
    what makes it a control and not a restatement.
    """
    for tag in range(1, 128):
        assert codec.encode_ber_oid(tag) == bytes((tag,))
    for tag in range(128, 142):
        assert codec.encode_ber_oid(tag) == bytes((0x81, tag - 128))
    assert codec.encode_ber_oid(141).hex() == "810d"


def test_the_tag_codec_round_trips_by_exhaustion_over_the_established_range():
    """`decode(encode(n)) == n` for all 16 384 values, and every encoding is the shortest one.

    By exhaustion rather than by sampling, because the whole established range fits in a test and a
    sampled claim about an encoding is weaker than the encoding deserves. `gmtif_codec` does the
    same for its 8- and 16-bit forms and samples only where the range is 2**32.
    """
    for value in range(codec.BER_OID_MAX + 1):
        octets = codec.encode_ber_oid(value)
        assert codec.decode_ber_oid(octets) == (value, len(octets)), value
        assert len(octets) == (1 if value <= 127 else 2), value

    # Above 16383 the domain is unbounded — ST 0107.3 §6.3.1 calls it "unlimited future growth" —
    # so exhaustion is not available and the boundaries stand in for it. Every octet either side of
    # each width transition, out to five.
    for power in range(2, 6):
        for value in ((1 << (7 * power)) - 1, 1 << (7 * power), (1 << (7 * power)) + 1):
            octets = codec.encode_ber_oid(value)
            assert codec.decode_ber_oid(octets) == (value, len(octets)), value
            assert not octets[-1] & 0x80 and all(o & 0x80 for o in octets[:-1]), value


def test_the_three_ber_oid_refusals_each_name_what_they_are_refusing():
    """An empty slice, truncation, and a non-minimal encoding. **There were four.**

    Asserted on the MESSAGE and not only on the type, because these are the boundary of what the two
    documents establish and a caller meeting one needs to know which side of it they are on — a
    malformed stream or a rule nobody here has read.

    The fourth refusal was a third continuation octet, and its removal is asserted below rather than
    simply deleted: a refusal that disappears from a test file leaves no trace of why.
    """
    with pytest.raises(codec.KLVFramingError) as empty:
        codec.decode_ber_oid(b"")
    assert "no octets remain" in str(empty.value)

    with pytest.raises(codec.KLVFramingError) as overrun:
        codec.decode_ber_oid(b"\x81")
    assert "runs off the end" in str(overrun.value)

    with pytest.raises(codec.KLVFramingError) as minimal:
        codec.decode_ber_oid(b"\x80\x01")
    assert "leading zero" in str(minimal.value)
    assert "ST 0107.3 §6.3.1" in str(minimal.value), (
        "the minimality refusal now rests on ST 0107.3 §6.3.1 — 'To prevent BER-OID from including "
        "leading zeros, ASN.1 forbids the use of 0x80 in the first byte of a BER-OID value' — "
        "which is LIVE text. It used to rest on ST 0601.8-06, marked (Deprecated), and the message "
        "said so because presenting a decision as a derivation is the error the framing round was "
        "shaped around. The behaviour did not change and the authority did; a message still citing "
        "only the deprecated requirement would understate what this repository now holds"
    )


def test_a_third_ber_oid_octet_decodes_where_it_used_to_be_refused():
    """THE ONE BEHAVIOUR PARK 4 CHANGED that was not simply an absence becoming a presence.

    `decode_ber_oid(b"\x81\x81\x00")` raised `KLVFramingError` naming parks 4 and 8, because ST
    0601.14a §7.1 said tags above 127 "use two-bytes (or more)" and never defined the "or more".
    Extending Figure 67's pattern by hand was arithmetic anybody could do, which is exactly what made
    it the tempting reconstruction — so it was refused.

    MISB ST 0107.3 §6.3.1 states the general rule, so it is now decoded. This test is the record of
    that flip, and it asserts the flip in both directions: the value is right, AND no refusal
    mentioning a park survives on this path. A codec still naming park 4 here would be naming a
    closed park as a blocker.
    """
    assert codec.decode_ber_oid(b"\x81\x81\x00") == (16384 + 128, 3)
    assert codec.encode_ber_oid(16512) == b"\x81\x81\x00"
    # 0x818100: payloads 1, 1, 0 → (1 << 14) | (1 << 7) | 0 = 16512.
    assert codec.decode_ber_oid(codec.encode_ber_oid(16512)) == (16512, 3)


def test_a_zero_octet_decodes_and_the_layer_does_not_rule_on_whether_tag_zero_is_legal():
    """Framing and semantics kept apart, deliberately, at the one place they are easy to conflate.

    §7.1 gives the representable range as 1 through 127 and Table 1 assigns no tag 0. Whether a
    local set may carry one is a tag-semantics question, and this round implements no tag semantics
    — so `0x00` decodes to 0 and the question is left where it belongs.
    """
    assert codec.decode_ber_oid(b"\x00") == (0, 1)


def test_the_checksum_matches_the_documents_own_worked_vector():
    """§8.1.1.2, digit for digit: 060E 2B34 0200 81BB sums to B4FD.

    THE ONLY EXTERNAL ANCHOR IN THIS MODULE, and that is why it is here rather than in a table of
    hand-computed values. Every other assertion checks that this repository transcribed a rule
    correctly by re-deriving it from the same reading; this one checks an implementation against a
    number the standard printed. §6.6's C is short enough to transcribe wrongly in a way that reads
    correctly — the `(8 * ((i + 1) % 2))` shift alternates high/low byte and swapping the parity
    gives a plausible 16-bit number for every input.
    """
    assert codec.bcc_16(bytes.fromhex("060E2B34020081BB")) == 0xB4FD
    # The document's own partial sums, which is what makes the transcription checkable stepwise
    # rather than only at the end.
    assert codec.bcc_16(bytes.fromhex("060E2B34")) == 0x3142
    assert codec.bcc_16(bytes.fromhex("060E2B340200")) == 0x3342


def test_the_checksum_is_masked_to_sixteen_bits_because_the_standard_declares_an_unsigned_short():
    """Python integers do not wrap where a C `unsigned short` does.

    Dropping `& 0xFFFF` leaves a function that agrees with the standard on short buffers and
    silently diverges on long ones — and a real UAS Datalink LS packet is long enough. §8.1's own
    summary bullet calls the result the "Lower 16-bits of summation".
    """
    assert codec.bcc_16(b"\xff" * 4096) < 1 << 16
    assert codec.bcc_16(b"\xff" * 512) == sum(0xFF << (8 * ((i + 1) % 2))
                                              for i in range(512)) & 0xFFFF


# ------------------------------------- the length grammar, MISB ST 0107.3 §6.3.2 and §6.3
#
# WHAT THIS BLOCK REPLACED. Until park 4 closed it was one parametrized negative,
# `test_the_delegated_half_raises_and_names_the_park`, asserting that `decode_ber_length`,
# `encode_ber_length` and `walk_local_set` all raise. Its docstring named the creeping failure it
# guarded: "somebody supplying the familiar BER length rule from memory: four lines in
# `decode_ber_length`, every framing fixture still green, and this repository ships a grammar it
# read nowhere."
#
# THAT HAZARD DID NOT GO AWAY WHEN THE RULE ARRIVED — it inverted. The familiar recitation and ST
# 0107.3 §6.3.2's rule are the same rule, so a codec written from memory passes every test below.
# What the tests can still hold is the CITATION: every assertion here names the sentence or the
# worked octets it enforces, and the two refusals are the two inefficiencies §6.3.2 itself names
# rather than a general minimality policy somebody remembered. If a later edition of ST 0107 says
# something else, these tests are where the disagreement surfaces.


def test_the_short_form_is_the_octet_itself_per_section_6_3_2():
    """§6.3.2's own octet: "the short form one-byte (0x02) length" for the length two.

    The short form has no flag bit to strip — the octet IS the length — and the document fixes the
    range as "values less than 128". Asserted across the whole range because it fits.
    """
    assert codec.BER_LENGTH_SHORT_FORM_MAX == 127
    assert codec.decode_ber_length(b"\x02") == (2, 1)          # §6.3.2, verbatim
    assert codec.encode_ber_length(2) == b"\x02"
    for value in range(0, 128):
        assert codec.encode_ber_length(value) == bytes((value,)), value
        assert codec.decode_ber_length(bytes((value,))) == (value, 1), value


def test_a_zero_length_is_admitted_because_section_6_3_says_so():
    """§6.3: "Lengths are usually positive numbers; however, a zero length is possible in unique cases".

    Worth its own test because a length codec that rejected 0 would be defensible on general
    grounds and wrong on this document's. §6.3 goes on to say what it means — "In the case of a zero
    Length, the Value is not a part of the item" — which `walk_local_set` has to honour.
    """
    assert codec.encode_ber_length(0) == b"\x00"
    assert codec.decode_ber_length(b"\x00") == (0, 1)


def test_the_long_form_shape_is_fixed_by_the_documents_own_three_examples():
    """0x8102, 0x8180 and 0x8300 0080 — the three long-form strings §6.3.2 prints.

    THE DERIVATION THIS TEST GUARDS, because it is the one that could have been a recollection.
    §6.3.2 never says "the low seven bits of the first octet are a count of following octets". It
    prints `0x81` introducing one octet and `0x83` introducing three, and it calls `0x8180` "two
    bytes" — so the count is in the first octet, the first octet is included in the total, and the
    following octets are big-endian by ST 0107.2-02. Two data points and an octet-order requirement
    fix the shape uniquely; nothing here is supplied from outside the document.
    """
    # 0x8180 → 128. §6.3.2 calls it "the optimized value with two bytes (0x8180)".
    assert codec.decode_ber_length(b"\x81\x80") == (128, 2)
    assert codec.encode_ber_length(128) == b"\x81\x80"
    # 0x81 introduces ONE octet and 0x83 introduces THREE — the count, read off the two examples.
    assert codec.decode_ber_length(b"\x81\xff") == (255, 2)
    assert codec.decode_ber_length(b"\x83\x01\x00\x00") == (65536, 4)
    # Big-endian, ST 0107.2-02 §6.1: "Byte order shall be big-endian or MSB."
    assert codec.decode_ber_length(b"\x82\x01\x00") == (256, 3)
    assert codec.decode_ber_length(b"\x82\x00\x01"[0:1] + b"\x01\x00") == (256, 3)
    assert codec.encode_ber_length(256) == b"\x82\x01\x00"


def test_the_length_codec_round_trips_by_exhaustion_where_the_domain_permits():
    """`decode(encode(n)) == n`, exhaustively to 131 071 and by boundary vector above.

    The domain is unbounded — §6.3.2 states no ceiling — so exhaustion runs as far as is useful and
    the widths either side of every octet boundary stand in for the rest. Every encoding is also
    asserted to be the shortest one, which is `ST 0107.3-05` rather than a preference.
    """
    for value in range(0, 1 << 17):
        octets = codec.encode_ber_length(value)
        assert codec.decode_ber_length(octets) == (value, len(octets)), value
    for value in (0, 127, 128, 255, 256, 65535, 65536, (1 << 24) - 1, 1 << 24,
                  (1 << 32) - 1, 1 << 32, (1 << 64) - 1, 1 << 64, 1 << 500):
        octets = codec.encode_ber_length(value)
        assert codec.decode_ber_length(octets) == (value, len(octets)), value
    # The width is the minimal big-endian byte count, which is what "fewest possible bytes" means.
    widths = {0: 1, 127: 1, 128: 2, 255: 2, 256: 3, 65535: 3, 65536: 4}
    for value, width in widths.items():
        assert len(codec.encode_ber_length(value)) == width, value


def test_the_two_non_minimal_refusals_are_the_two_inefficiencies_section_6_3_2_names():
    """`ST 0107.3-05` requires "the fewest possible bytes", and §6.3.2 names exactly two ways to spend more.

    THE FIXTURES ARE THE DOCUMENT'S OWN OCTETS. §6.3.2, verbatim: "by either using the long form for
    values less than 128, or by prepending a long form value with zero-byte values, BER becomes less
    efficient. For example, encoding the length of two (2), a value less than 128, with long form
    uses two bytes (0x8102) instead of the short form one-byte (0x02) length. Another example is
    encoding the value 128 with padded zeros (0x8300 0080) instead of the optimized value with two
    bytes (0x8180)."

    Both are `KLVFramingError` — *these bytes are wrong* — and not the park exception, because
    `ST 0107.3-05` is a live numbered "shall" in the edition ST 0601.14a's live route points at. It
    is the requirement that shipped as `ST 0601.8-07`, marked **(Deprecated)** there, with the onward
    delegation to ST 336 removed.

    Nothing else is refused for non-minimality, because §6.3.2 names nothing else — which is why this
    test asserts the two and not a general policy.
    """
    with pytest.raises(codec.KLVFramingError) as long_for_small:
        codec.decode_ber_length(b"\x81\x02")
    assert "0x8102" in str(long_for_small.value)
    assert "fewest possible bytes" in str(long_for_small.value)

    with pytest.raises(codec.KLVFramingError) as padded:
        codec.decode_ber_length(bytes.fromhex("83000080"))
    assert "0x8300 0080" in str(padded.value)
    assert "fewest possible bytes" in str(padded.value)

    # And the encoder cannot produce either, which is the same rule from the other side: there is no
    # `form=` parameter, so `ST 0107.3-05` is enforced by the signature and not by a check.
    assert codec.encode_ber_length(2) == b"\x02"
    assert codec.encode_ber_length(128) == b"\x81\x80"


def test_the_length_codec_is_total_because_st_0107_3_05_leaves_no_choice_of_form():
    """No `form=` parameter anywhere. THE WHOLE PARK 4 RULING, asserted as an API shape.

    The question this round was sent to answer about park 4 was whether ST 0107.3 constrains which
    form an encoder may emit or leaves it free. It constrains it: `ST 0107.3-05`, "shall be BER Short
    form or BER Long form encoded using the fewest possible bytes." So for every length there is
    exactly one conforming encoding, and an encoder that offered a choice would be offering to emit
    a non-conforming stream.
    """
    import inspect
    parameters = list(inspect.signature(codec.encode_ber_length).parameters)
    assert parameters == ["value"], (
        f"encode_ber_length takes {parameters}. ST 0107.3-05 makes the encoding a function of the "
        f"length alone; a form selector would make a non-minimal stream expressible"
    )


def test_the_0x7f_to_0x80_transition_is_asymmetric_and_0x80_is_still_park_8():
    """THE ONE PLACE THE GRAMMAR STOPS. 0x7F is a length; 0x80 is a blocker.

    `0x80` as a first length octet declares zero following octets, and **ST 0107.3 never mentions
    that form** — §6.3.2 defines the short form and the long form and says nothing about a count of
    zero. In BER it is the indefinite-length form, and BER is SMPTE ST 336:2017, park 8, a purchase.

    So this raises `UnderivableFromPinnedCopy` and not `KLVFramingError`, and the distinction is the
    point: *nobody here knows whether these bytes are wrong*. The message carries park 8 and the
    delegating sentence, `ST 0107.3-03`, so it is a reopen condition rather than a complaint.
    """
    assert codec.BER_LENGTH_INDEFINITE_OCTET == 0x80
    assert codec.decode_ber_length(b"\x7f") == (127, 1)          # the octet below it is a length

    with pytest.raises(codec.UnderivableFromPinnedCopy) as excinfo:
        codec.decode_ber_length(b"\x80")
    message = str(excinfo.value)
    assert "PARK 8" in message
    assert "ST 0107.3-03" in message, "the message does not carry the delegating requirement"
    assert "SMPTE ST 336" in message
    assert "indefinite" in message.lower()


def test_no_ceiling_on_length_octets_is_stated_so_the_structural_bound_is_the_park():
    """§6.3.2 states NO maximum, and the only maxima in the document govern Values.

    `ST 0107.3-07` — "Where a MISB standard defines a numeric maximum Length for a Local Set item's
    Value, the encoded Value shall not exceed the number of bytes defined by the maximum Length" — is
    about a Value's size, not a length field's width. So the 127-octet bound below is the first
    octet's seven bits and nothing else: **structural, not cited.**

    Which is why exceeding it raises the park exception rather than a framing error. A ceiling ST 336
    imposes would be lower, and this repository cannot know.
    """
    assert codec.BER_LENGTH_OF_LENGTH_MAX == 127
    widest = (1 << (8 * 127)) - 1
    assert len(codec.encode_ber_length(widest)) == 128           # one introducer plus 127 octets
    assert codec.decode_ber_length(codec.encode_ber_length(widest)) == (widest, 128)

    with pytest.raises(codec.UnderivableFromPinnedCopy) as excinfo:
        codec.encode_ber_length(1 << (8 * 127))
    message = str(excinfo.value)
    assert "PARK 8" in message and "ST 0107.3-03" in message
    assert "states no ceiling" in message


def test_a_truncated_long_form_length_is_a_malformed_stream_and_not_a_park():
    """THE MALFORMATION THE FRAMING ROUND COULD NOT WRITE, now that the rule is held.

    `0x82` declares two following octets and one remains. The rule is in hand and these bytes break
    it, so this is `KLVFramingError` and the message quotes the offset — the contract every refusal
    in this module keeps, because a refusal that does not say WHERE leaves the caller bisecting.
    """
    with pytest.raises(codec.KLVFramingError) as excinfo:
        codec.decode_ber_length(b"\x82\xff")
    message = str(excinfo.value)
    assert "offset 0" in message
    assert "declares 2 following octet(s)" in message

    with pytest.raises(codec.KLVFramingError) as empty:
        codec.decode_ber_length(b"")
    assert "no octets remain" in str(empty.value)


# ------------------------------------------------------------------- §6.3, the local-set walk


def _packet(items):
    """Build a packet the way `build_fixtures.py` does — from the codec, never typed."""
    body = b"".join(codec.encode_ber_oid(tag) + codec.encode_ber_length(len(value)) + value
                    for tag, value in items)
    return codec.UAS_LOCAL_SET_KEY + codec.encode_ber_length(len(body)) + body


def test_the_walk_composes_all_three_rules_and_yields_opaque_values():
    """Key (ST 0601.14a §6.2), tag (ST 0107.3 §6.3.1), length (ST 0107.3 §6.3.2), in that order.

    ST 0601.14a §6.3 gives the shape: "A packet is a combination of a UL Key, the Length of the
    Value, and the Value. UAS Datalink LS items are encapsulated within the Value portion of the
    packet." So the walk reads a key, reads the length of the Value, and then reads triplets until
    the Value is exhausted.

    The items below exercise every width the two documents establish at once: a one-octet tag, a
    two-octet tag, a short-form length, a long-form length, and a zero length whose Value "is not a
    part of the item".
    """
    items = [(1, bytes.fromhex("8ced")), (128, b"\xaa" * 200), (141, b"")]
    walked = list(codec.walk_local_set(_packet(items)))
    assert [(i.tag, i.value) for i in walked] == items
    assert [i.length for i in walked] == [2, 200, 0]
    # The offsets are carried so a caller can compute §6.6's checksum range, which `bcc_16` takes
    # and cannot find. Each value begins where its tag and length octets end.
    for item in walked:
        assert item.value_offset > item.tag_offset
    # The first tag sits just past the key and the packet's own length field. That field is LONG
    # form here — the three items total 211 octets, which is past the short form's 127 — so the
    # offset is derived from the encoding rather than typed, and it is 18 rather than 17.
    body_length = sum(len(codec.encode_ber_oid(t)) + len(codec.encode_ber_length(len(v))) + len(v)
                      for t, v in items)
    introducer = len(codec.encode_ber_length(body_length))
    assert body_length == 211 and introducer == 2
    assert walked[0].tag_offset == codec.KEY_LENGTH + introducer
    assert isinstance(walked[0], tuple)                          # a NamedTuple, so it destructures


def test_the_walk_knows_no_tags_which_is_how_it_satisfies_st_0107_3_04():
    """`ST 0107.3-04`, satisfied structurally rather than by a skip list.

    Verbatim: "Applications which decode MISB KLV Local Sets shall skip unknown Local Set values so
    as to not impact the decoding of known Local Set items within the same Local Set instance."
    §6.3 gives the reason — a decoder meeting a tag from a newer revision "simply ignores any item it
    does not understand", using the Length "to skip the correct number of bytes to the next item".

    This walk knows NO tags, so every item is equally unknown to it and the caller decides what it
    recognises. A tag far outside anything ST 0601 assigns walks exactly like tag 1.
    """
    items = [(1, b"\x01"), (99999, b"\x02\x03"), (2, b"\x04")]
    walked = list(codec.walk_local_set(_packet(items)))
    assert [(i.tag, i.value) for i in walked] == items
    assert len(codec.encode_ber_oid(99999)) == 3, (
        "the unknown tag no longer needs a third octet, so this no longer tests what it says it does"
    )


def test_the_walk_refuses_a_truncated_packet_and_an_item_that_overruns_its_packet():
    """Two faults that look alike and are not, reported apart.

    A truncated buffer is the packet being cut off from outside. An item declaring a Value longer
    than the packet's own declared Value is the packet being inconsistent from inside — the buffer is
    long enough and the packet is still wrong. Conflating them would send a caller looking for a
    transport problem when the fault is in the octets they already hold.
    """
    packet = _packet([(1, bytes.fromhex("8ced")), (2, b"\x00" * 8)])

    with pytest.raises(codec.KLVFramingError) as truncated:
        list(codec.walk_local_set(packet[:-1]))
    assert "declares a" in str(truncated.value) and "remain" in str(truncated.value)

    overrun = (codec.UAS_LOCAL_SET_KEY + codec.encode_ber_length(3)
               + codec.encode_ber_oid(1) + codec.encode_ber_length(9) + b"x" * 9)
    with pytest.raises(codec.KLVFramingError) as inside:
        list(codec.walk_local_set(overrun))
    assert "past the end of the packet's own declared Value" in str(inside.value)
    assert "tag 1" in str(inside.value)


def test_the_walk_is_a_generator_so_a_caller_can_stop_early():
    """Lazy on purpose: a caller wanting tag 1 should not decode two hundred octets to get it.

    Also why a malformed item raises where it is met rather than poisoning the items already
    yielded — the first item of the packet below is well formed and is delivered before the second
    one fails.
    """
    good = codec.encode_ber_oid(1) + codec.encode_ber_length(2) + b"\x8c\xed"
    bad = codec.encode_ber_oid(2) + b"\x82\xff"                 # a truncated long-form length
    packet = codec.UAS_LOCAL_SET_KEY + codec.encode_ber_length(len(good + bad)) + good + bad
    walk = codec.walk_local_set(packet)
    first = next(walk)
    assert (first.tag, first.value) == (1, bytes.fromhex("8ced"))
    with pytest.raises(codec.KLVFramingError):
        next(walk)


def test_the_underivable_exception_is_not_the_malformed_one():
    """"These bytes are wrong" and "nobody here knows whether they are wrong" are different claims.

    Conflating them would report a park as a malformed stream, which is the error that makes a
    blocker invisible: a caller sees a parse failure, retries with different bytes, and never learns
    that no bytes would have worked.
    """
    assert not issubclass(codec.UnderivableFromPinnedCopy, codec.KLVFramingError)
    assert not issubclass(codec.KLVFramingError, codec.UnderivableFromPinnedCopy)


def test_the_framing_codec_still_registers_no_adapter_and_still_knows_no_tags():
    """A codec, not an adapter — and now that an adapter EXISTS, this is the load-bearing half.

    THE PROPERTY, RESTATED FOR THE ROUND THAT SHIPPED ADAPTER #10. Until the witnessed-set round
    this test asserted that no adapter existed anywhere; `adapters/stanag4609.py` now registers one,
    so what is worth asserting has changed and the test says which:

    * **`klv_codec` still defines no `Adapter` subclass.** Checked by AST rather than by counting
      the registry, so it fails on the SOURCE that would do it.
    * **`klv_codec` still names no tag.** This is the property the whole two-layer split exists to
      protect: `walk_local_set`'s docstring claims "the walk knows no tags at all, so every item is
      equally unknown to it", which is how `ST 0107.3-04`'s skip-unknown requirement is satisfied
      structurally rather than by a skip list. A tag table imported into the framing layer would
      destroy that claim silently — the walk would still work — so the import is what is checked.

    The tag table lives one layer up, in `klv_uas_codec`, on the `cat048_codec` / `asterix_cat048`
    precedent.
    """
    tree = ast.parse((PKG / "adapters" / "klv_codec.py").read_text())
    bases = [b for node in ast.walk(tree) if isinstance(node, ast.ClassDef) for b in node.bases]
    names = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in bases}
    assert "Adapter" not in names, (
        "klv_codec defines an Adapter subclass. The framing layer cannot read a local set's "
        "VALUES, and a module that registers as an adapter claims it can — see the pin's "
        "framing_ruling_st_0601_14.what_was_implemented_and_what_deliberately_was_not"
    )
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {alias.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                 for alias in n.names}
    assert not any("klv_uas_codec" in name for name in imported), (
        "klv_codec imports the tag table. The framing layer is deliberately tag-blind — that is "
        "how ST 0107.3-04's 'skip unknown Local Set values' is satisfied structurally, since a "
        "walk that knows no tags treats every item as equally unknown. Whatever needs the table "
        "belongs in klv_uas_codec or in the adapter"
    )
    from synapse_cdm import adapter as adapter_module
    registry = adapter_module.discover()
    assert "klv" not in registry, (
        "an adapter named `klv` is registered. The registered name is `stanag4609` — the adapter "
        "is named for the covering document and `klv` is the fixture DIRECTORY, named for the "
        "bytes. See klv_pin.json's adapter.why_the_two_names_differ"
    )
    assert registry["stanag4609"].fixture_dir == "klv"


# ---------------------------------------------------------------------------- the fixtures


def test_the_generator_is_the_only_thing_that_writes_the_framing_fixtures():
    """Every octet and every twin on disk is what the source in `spec/` produces, today.

    The house rule for every fixture set here, applied to the first one that is not an adapter's.
    A hand-edited `.klvframe` would be a byte nothing cites.
    """
    module = _build_fixtures_module()
    module.check_established_rules()
    for spec in module.FIXTURES_SPEC:
        payload = FRAMING / f"{spec['name']}.klvframe"
        twin = FRAMING / f"{spec['name']}.parsed.json"
        assert payload.read_bytes() == bytes.fromhex(spec["octets"]), (
            f"{payload.name} on disk is not what build_fixtures.py produces"
        )
        assert json.loads(twin.read_text())["octets_hex"] == spec["octets"].upper()


def test_every_framing_fixture_cites_a_section_and_carries_a_synthetic_identity():
    """A fixture with no citation is a byte somebody chose, which is the thing this round forbids."""
    twins = sorted(FRAMING.glob("*.parsed.json"))
    assert len(twins) == 26, f"{len(twins)} framing fixtures, expected 26"
    seen = set()
    for path in twins:
        record = json.loads(path.read_text())
        assert record["citation"].strip(), f"{path.name} cites no section"
        # BOTH pinned copies, at every fixture. The set now rests on two documents and a fixture
        # naming only one of them would leave a reader unable to check half the citations.
        assert ST_0601_14A in record["source"], f"{path.name} does not name ST 0601.14a"
        assert ST_0107_3 in record["source"], f"{path.name} does not name ST 0107.3"
        identity = record["fixture_id"]
        assert re.fullmatch(r"f1c7[0-9a-f]{4}-[0-9a-f]{4}-8[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}",
                            identity), (
            f"{path.name}'s id {identity} is not a UUID-v8 in the f1c7 namespace"
        )
        assert identity not in seen, f"{identity} is used twice"
        seen.add(identity)


def test_every_framing_fixture_kind_is_a_rule_one_of_the_two_documents_states():
    """THE CENSUS THAT USED TO BE AN ABSENCE, and the inversion is the round's whole shape.

    This test used to be `test_no_framing_fixture_needed_a_rule_this_round_could_not_cite`, and it
    asserted that **nothing** on disk exercised a length or a triple, because ST 0601.14a delegated
    the length grammar and the framing round would not guess it. Three classes were named as omitted:
    every length fixture including the truncated-length malformation, every key/length/value triple,
    and the 16383 → 16384 tag transition.

    MISB ST 0107.3 discharged all three, so the check inverts: the kinds are now an allow-list of
    rules one of the two held documents states, and the prose sites are required to say what
    discharged the omissions rather than what the omissions were. An absence that becomes a presence
    with no site recording the transition reads as though the fixtures had always been there.
    """
    kinds = {json.loads(path.read_text())["kind"] for path in FRAMING.glob("*.parsed.json")}
    assert kinds == {
        "universal_label", "universal_label_refusal",
        "ber_oid_tag", "ber_oid_refusal",
        "ber_length", "ber_length_refusal", "ber_length_park",
        "local_set_item", "local_set_packet",
        "checksum",
    }, f"unexpected fixture kinds: {sorted(kinds)}"

    # EXACTLY ONE fixture is still a park, and it is 0x80. Asserted as a count so that a later
    # round cannot quietly decide what an indefinite length means and leave the set looking the same.
    parks = [json.loads(p.read_text()) for p in FRAMING.glob("*.parsed.json")
             if json.loads(p.read_text())["kind"] == "ber_length_park"]
    assert len(parks) == 1, f"{len(parks)} park fixtures, expected exactly one"
    assert parks[0]["octets_hex"] == "80"
    assert "PARK 8" in parks[0]["note"]

    for name, site in (("FORMAT_COVERAGE.md", _framing_section()),
                       ("README", README.read_text()),
                       ("generator", GENERATOR.read_text())):
        flat = _flat(site)
        assert "16383" in flat, f"{name} no longer states the transition park 4 unblocked"
        assert "ST 0107.3" in flat, f"{name} does not name the document that discharged the omissions"


def test_the_framing_fixtures_are_still_not_reachable_as_adapter_fixtures():
    """The subdirectory is the mechanism, not the manners — and now it has something to separate.

    Until the witnessed-set round `fixtures/klv` held no files at all, so this test asserted an
    empty directory and the separation was free. Adapter #10's ten payload fixtures now live there,
    which is what makes the subdirectory load-bearing rather than tidy: the harness selects
    "immediate children of the directory that are files", so one `.klvframe` copied up a level would
    silently become an eleventh adapter fixture — and the harness would try to translate a bare BER
    length as a UAS Datalink LS payload and report a FAIL that blames the adapter for a file that
    was never a payload.

    So what is asserted is the PARTITION rather than an emptiness: `framing/` stays a directory,
    every immediate file child is one of the adapter fixtures the generator writes, and no framing
    fixture's extension appears at the top level.
    """
    from synapse_cdm import harness
    assert "immediate children" in harness.FIXTURE_PATTERN
    module = _build_fixtures_module()
    expected = set()
    for spec in module.ADAPTER_FIXTURES:
        expected |= {f"{spec['name']}.klv", f"{spec['name']}.parsed.json"}
    present = {p.name for p in FIXTURES.iterdir()
               if p.is_file() and p.name != "README.md" and not p.name.startswith(".")}
    assert present == expected, (
        f"fixtures/klv's immediate files are {sorted(present)} and the generator writes "
        f"{sorted(expected)}. Every payload there is replayed by the harness as adapter #10's, so "
        "a file the generator does not write is a fixture nothing cites"
    )
    assert not any(name.endswith(".klvframe") for name in present), (
        "a framing fixture has been copied to the top level, where the harness will try to "
        "translate a bare tag or length as a whole UAS Datalink LS payload"
    )
    assert FRAMING.is_dir()
    assert len(list(FRAMING.glob("*.klvframe"))) == len(module.FIXTURES_SPEC)


# ------------------------------------------------------------------ the disjunction protocol

#: Every site that states any part of the framing ruling. Named rather than globbed, because the
#: value of the protocol is that adding a seventh site is a deliberate act.
SITES = {
    "FORMAT_COVERAGE.md": lambda: DOC.read_text(),
    "MIGRATIONS.md": lambda: MIGRATIONS.read_text(),
    "fixtures/klv/spec/klv_pin.json": lambda: PIN.read_text(),
    "fixtures/klv/README.md": lambda: README.read_text(),
    "adapters/klv_codec.py": lambda: (PKG / "adapters" / "klv_codec.py").read_text(),
    "fixtures/klv/spec/build_fixtures.py": lambda: GENERATOR.read_text(),
}


#: MEASUREMENTS THIS ROUND PUT AT MORE THAN ONE SITE, collected the moment they were multiplied
#: rather than after one of them drifted — which is the disjunction protocol's whole argument. Each
#: row is (what it is, the value verbatim, the sites required to carry it). The sites are NAMED and
#: not globbed, for `SITES`' own reason: adding a fourth site is a deliberate act.
#:
#: The KLV 16 rows are read out of EG 0601.1's PDF document-information dictionary, and they are
#: guarded HERE and not re-derived by this suite for a reason worth stating: the pinned PDFs are
#: gitignored and no PDF library is installed in the environment the suite judges, so a test that
#: parsed them would skip everywhere and assert nothing. What CAN be asserted for free is that the
#: three prose statements of one measurement are the same statement, which is the half that
#: actually rots. The derivation itself is recorded in `FORMAT_COVERAGE.md` beside the value, with
#: the calibration that makes it meaningful.
MULTIPLIED_FACTS = (
    ("EG 0601.1's PDF /CreationDate, KLV 16's third corroboration of the cover date",
     "D:20080515125829",
     ("FORMAT_COVERAGE.md", "MIGRATIONS.md", "fixtures/klv/spec/klv_pin.json")),
    ("the initial release's PDF /CreationDate, which calibrates the field's four-day lag",
     "D:20060116085414",
     ("FORMAT_COVERAGE.md", "fixtures/klv/spec/klv_pin.json")),
    ("EG 0601.1's source-document filename, the second date stamp inside /Title",
     "EG0601.1_UAS_Local_Data_Set_20080515.doc",
     ("FORMAT_COVERAGE.md", "MIGRATIONS.md", "fixtures/klv/spec/klv_pin.json")),
    # MIGRATIONS.md JOINED THIS ROW when the second retry was recorded there. The row named two
    # sites and the value is now at three, so the third is added deliberately rather than left
    # unguarded — which is this table's stated rule about adding a site, applied in the direction
    # that is easy to skip: a site that starts carrying a measurement is as much a change as a
    # site that stops.
    ("park 9's retry: the rate-limit header the archive answered with",
     "X-RL: 1",
     ("FORMAT_COVERAGE.md", "MIGRATIONS.md", "fixtures/klv/spec/klv_pin.json")),
    # COLLECTED THE MOMENT IT WAS MULTIPLIED, which is the whole protocol. The second retry's
    # timestamp is the identifier of the observation the three sites are describing; if one site
    # is later re-dated and the others are not, the record carries two retries where there was
    # one, and nothing else in the suite would notice. The BYTE COUNT of the 429 body is
    # deliberately NOT a row: it is written "162 bytes" at two sites and "162-byte" at a third,
    # which is one measurement in two grammars, and pinning a string would force a spelling
    # rather than guard a value — the same judgement the timezone suffixes above get.
    ("park 9's second retry: the timestamp all three sites date the observation to",
     "2026-08-27T14:51Z",
     ("FORMAT_COVERAGE.md", "MIGRATIONS.md", "fixtures/klv/spec/klv_pin.json")),
    # TWO ROWS THIS GUARD COLLECTED RATHER THAN THIS ROUND CREATING THEM, and both were load-bearing
    # and unguarded. Each is the /CreationDate that establishes that a pinned copy is NOT the
    # pristine edition its cover claims — ST 0601.14a as amended through 19 August 2021 but
    # generated 17 December 2021, and ST 0601.19 as amended through 11 June 2025 but generated
    # 2 July 2025. They are stated at one site each, so the row above them asserts nothing new; what
    # the row does is put them inside the SET the second direction below closes, so a retyped digit
    # in either fails a build. Timezone suffixes are deliberately not part of the value: the pin
    # writes `-05'00'` after both and the regex reads the fourteen digits, which is the part that
    # dates the file.
    ("ST 0601.14a's own /CreationDate — the copy is amended past its 1 May 2020 cover",
     "D:20211217145743",
     ("fixtures/klv/spec/klv_pin.json",)),
    ("ST 0601.19's own /CreationDate — the copy is amended past its 2 March 2023 cover",
     "D:20250702122555",
     ("fixtures/klv/spec/klv_pin.json",)),
    # ADDED BY THE OFF-PEAK ROUND, WITH ST 1402.2 — park 9's document, and the pin records its
    # /CreationDate and /ModDate as the same value. It goes in for the SET's sake rather than
    # for a cross-site comparison: one site states it, so the row above asserts nothing new,
    # and what it buys is that the closure direction below stops treating it as an unknown
    # timestamp. The CALIBRATION is the part worth reading and it lives beside the value in the
    # pin: this file post-dates its own cover by 47 days, where the four held 0601 documents
    # gave 0, 0, 0 and 4 — so it corroborates the YEAR and nothing finer, and the pin says so
    # rather than quoting the field as if it dated the edition.
    ("ST 1402.2's own /CreationDate — 47 days after its 27 October 2016 cover",
     "D:20161213145428",
     ("fixtures/klv/spec/klv_pin.json",)),
)


@pytest.mark.parametrize("label,value,required", MULTIPLIED_FACTS,
                         ids=[v for _l, v, _s in MULTIPLIED_FACTS])
def test_a_measurement_stated_at_more_than_one_site_is_the_same_measurement(label, value, required):
    """Every site required to carry a multiplied measurement carries it, verbatim.

    The direction that catches a half-edit. A round that corrects one of three statements of one
    timestamp leaves two documents disagreeing about a file's own bytes, and nothing reads prose.
    """
    for name in required:
        assert name in SITES, f"{name} is not a known site; add it to SITES deliberately"
        assert value in SITES[name](), (
            f"{name} no longer states {value!r} — {label}. Either the measurement was corrected at "
            f"one site and not the others, which is the half-edit this row exists to catch, or it "
            f"was withdrawn, in which case it goes from every site and from this row together"
        )


def test_no_site_states_a_second_pdf_timestamp_for_a_document_that_has_one():
    """The other direction: no THIRD form of a value the rows above pin.

    `test_the_pinned_copy_is_the_same_copy_at_every_site_that_names_one` does this for digests,
    where an abbreviation is how a hash drifts unnoticed. A PDF timestamp drifts the other way —
    it is short enough to retype, and a retyped `D:2008...` differing in one digit reads correctly
    at every site that carries it. So the SET of timestamps stated anywhere must be exactly the
    set these rows pin, and a new one is a row somebody has to add.
    """
    pinned = {value for _l, value, _s in MULTIPLIED_FACTS if value.startswith("D:")}
    for name, read in SITES.items():
        found = set(re.findall(r"\bD:\d{14}\b", read()))
        unknown = sorted(found - pinned)
        assert not unknown, (
            f"{name} states PDF timestamp(s) {unknown} that MULTIPLIED_FACTS does not pin. A "
            "timestamp is short enough to retype and a wrong digit reads correctly, so each one "
            "gets a row naming which document it is from and which sites carry it"
        )


def test_the_pinned_copy_is_the_same_copy_at_every_site_that_names_one():
    """The digest, full or abbreviated, and no third form anywhere.

    An abbreviation is where a hash drifts unnoticed, because eight characters at each end look
    right for any digest that starts and ends the same way — and nothing checks an ellipsis. So
    every abbreviated form found by regex must expand to the pinned digest.
    """
    pin = json.loads(PIN.read_text())
    held = pin["delegated_specifications_held"]
    assert held["st_0601_14"]["sha256"] == ST_0601_14A
    assert held["st_0107_3"]["sha256"] == ST_0107_3, (
        "the pin's ST 0107.3 digest is not the copy park 4 was closed on. Everything in "
        "length_ruling_st_0107_3 is quoted from ONE file, and the digest is the only thing that "
        "says which"
    )
    # EVERY held copy, in one sweep, and the pairs are DERIVED FROM THE PIN rather than listed.
    #
    # THIS COMMENT USED TO SAY "generalised rather than duplicated" ABOUT A HARD-CODED PAIR, and
    # the defect it warned about had already recurred by the time anyone re-read it: it said the
    # framing round "hard-coded one digest and a second document would have slipped past it
    # abbreviated any way it liked", and then hard-coded TWO. A third document did slip past —
    # ST 1402.2 landed on 2026-08-27 abbreviated at two sites, and the `continue` below skipped it
    # as "another document's pin, checked by its own gate" when no such gate existed. Generalising
    # to a LIST is not generalising; the list is the thing that goes stale. So the pairs now come
    # from `delegated_specifications_held`, and a document cannot be held without being swept.
    held_digests = [(e["sha256"], e.get("document", key))
                    for key, e in sorted(held.items())
                    if isinstance(e, dict) and isinstance(e.get("sha256"), str)]
    assert len(held_digests) >= 3, (
        f"only {len(held_digests)} held documents carry a sha256 in the pin; this sweep derives "
        "its subjects from that node and a short count means the derivation stopped matching"
    )
    for full, label in held_digests:
        abbreviated = f"{full[:8]}…{full[-8:]}"
        found = {}
        for name, read in SITES.items():
            for head, tail in set(re.findall(r"\b([0-9a-f]{8})…([0-9a-f]{8})\b", read())):
                if not (full.startswith(head) or full.endswith(tail)):
                    continue                  # another document's pin, checked by its own gate
                found.setdefault(name, set()).add(f"{head}…{tail}")
        assert found, f"no site abbreviates the {label} digest, so this check is vacuous"
        for name, abbreviations in found.items():
            assert abbreviations == {abbreviated}, (
                f"{name} abbreviates the {label} digest as {sorted(abbreviations)}, expected "
                f"{abbreviated!r}"
            )


def test_park_four_is_stated_CLOSED_and_park_eight_OPEN_at_every_site_that_names_them():
    """The park states, at every site, in both directions — and the polarity FLIPPED this round.

    This test used to be `test_parks_four_and_eight_are_stated_OPEN_wherever_this_round_names_them`,
    and it forbade any site from saying park 4 was closed. That was the right gate then: the framing
    round narrowed park 4 without obtaining anything, and "the tempting error in a round that narrows
    a park is to write it up as progress and let a reader infer a closure."

    **The length round obtained the document, so the tempting error inverted.** It is now to write up
    a closure as though it settled more than it did — park 4 closing does not close park 8, and park 8
    is where the two remaining residues live. So the gate runs the other way: park 4 must be stated
    CLOSED as data and in words, park 8 must still be stated OPEN at every site, and **no site may
    claim park 8 closed**.
    """
    pin = json.loads(PIN.read_text())

    # 1. The new ruling's own outcome node, as data.
    outcome = pin["length_ruling_st_0107_3"]["the_park_outcome"]
    assert outcome["park_4"]["state_before_this_round"] == "OPEN"
    assert outcome["park_4"]["state_after_this_round"] == "CLOSED"
    assert outcome["park_8"]["state_before_this_round"] == "OPEN"
    assert outcome["park_8"]["state_after_this_round"] == "OPEN"

    # 2. The framing round's node is HISTORY and is not rewritten. Its park_4 still reads OPEN,
    #    because that was true of that round — and it must carry a forward pointer, so a reader who
    #    lands there is not left believing a superseded state.
    framing = pin["framing_ruling_st_0601_14"]
    assert framing["the_park_outcome"]["park_4"]["state_after_this_round"] == "OPEN", (
        "the framing round's record was rewritten. It states what ONE document could establish "
        "alone, which is the finding that sent somebody to fetch the second one; editing it to "
        "agree with a later round would destroy the only evidence that the two rounds differed"
    )
    pointer = _flat(json.dumps(framing.get("SUPERSEDED_IN_PART_BY_THE_LENGTH_RULING", "")))
    assert "length_ruling_st_0107_3" in pointer and "CLOSED" in pointer, (
        "the framing round's node states park 4 OPEN and does not point at the round that closed it"
    )

    # 3. The parks table itself.
    parks = pin["parks"]
    assert parks["the_ones_that_closed"]["park_4"]["park"] == 4
    assert parks["the_ones_that_closed"]["park_1"]["park"] == 1
    assert "the_one_that_closed" not in parks, (
        "the singular field survives beside the plural one. Two parks have closed and a singular "
        "field can only record one of them"
    )

    # 4. Every site, in words. Park 4 closed, park 8 open, and never the reverse.
    section = _flat(_framing_section())
    assert "Park 4 is CLOSED" in section and "Park 8 stays OPEN" in section
    for name, read in SITES.items():
        flat = _flat(read())
        for claim in ("park 8 is closed", "park 8 closed", "closes park 8",
                      "parks 4 and 8 are closed", "park 8 is now closed"):
            assert claim.lower() not in flat.lower(), (
                f"{name} states {claim!r}. ST 336 was not obtained — park 8 is a purchase, it "
                "still owns 0x80 and the ceiling, and a park narrowed to two absences written up "
                "as a closed one is the failure this round is most exposed to"
            )


def test_the_two_residues_park_eight_still_owns_are_named_at_every_ruling_site():
    """0x80 and the ceiling, in prose, wherever the round is described.

    A residue that shrinks is easy to stop mentioning, and a codec that walks a stream end to end
    reads as complete. These two are the reason `UnderivableFromPinnedCopy` still exists in the
    module, so every site that rules has to say what is still missing — the same discipline the
    framing round applied to the length grammar, applied to what is left of it.
    """
    for name, read in SITES.items():
        flat = _flat(read())
        assert "0x80" in flat, f"{name} does not name the indefinite-length octet"
        assert "ST 0107.3-03" in flat or "SMPTE ST 336" in flat, (
            f"{name} does not name the delegation park 8's residue sits behind"
        )
    section = _flat(_framing_section())
    assert "ceiling" in section.lower()
    assert "structural, not cited" in section, (
        "the section no longer marks the 127-octet bound as structural. It is arithmetic on the "
        "first octet's seven bits and NOT a citation, and a bound presented as cited is the "
        "reconstruction this module's whole shape exists to prevent"
    )


def test_every_established_rule_cites_the_same_section_at_the_pin_and_in_the_document():
    """The section citations, collected by regex from the pin and required in the prose.

    The pin is the machine-readable record and `FORMAT_COVERAGE.md` is where a reader arrives, and
    a citation that lives at only one of them is a citation nobody can check against the other. The
    loci come OUT of the pin rather than out of a list here, so a rule recorded with a new section
    is checked without anybody maintaining a roster of what is legal to cite.
    """
    pin = json.loads(PIN.read_text())
    section = _flat(_framing_section())
    # BOTH rulings, and the second is the one this round added. Iterated over the node names rather
    # than hard-coded to one, so a third ruling is covered the day it is written.
    for node in ("framing_ruling_st_0601_14", "length_ruling_st_0107_3"):
        loci = set()
        for rule in pin[node]["established_from_the_pinned_copy"]:
            loci |= set(re.findall(r"SS (\d+(?:\.\d+)*)", rule["locus"]))
            loci |= set(re.findall(r"(Figure \d+)", rule["locus"]))
        assert loci, f"no locus was parsed out of {node}, so this check is vacuous"
        missing = sorted(q for q in loci if q not in section and f"§{q}" not in section)
        assert not missing, (
            f"the framing section does not cite {missing}, and {node} records them as the loci of "
            "an established rule. Two statements of one reading have to name the same page"
        )
    # AND THE RESIDUE'S loci, which the framing round's version of this test did not collect. The
    # two things park 8 still owns are ABSENCES, so their locus is where the document is silent —
    # and a silence nobody can navigate to is a silence nobody can check.
    residue = pin["length_ruling_st_0107_3"]["underivable_from_the_bytes_in_hand"]
    assert len(residue) == 3, f"{len(residue)} residue entries, expected 3"
    assert "6.3.2" in section, "the section does not cite the length-encoding section at all"


def test_the_delegating_requirements_are_quoted_by_their_identifier_at_every_site_that_rules():
    """`ST 0601.8-07`, `ST 0601.8-03` and `ST 0601.8-06`, and the (Deprecated) marking with them.

    The identifier is the checkable half. "The standard delegates the length" is a claim a reader
    cannot verify against a 218-page PDF; "ST 0601.8-07, Appendix A, marked (Deprecated)" is one
    they can, in about a minute — and the deprecation is what makes the ruling non-obvious, because
    a requirement that reads as live and is not would have settled the question the wrong way.
    """
    for name in ("FORMAT_COVERAGE.md", "fixtures/klv/spec/klv_pin.json",
                 "adapters/klv_codec.py"):
        flat = _flat(SITES[name]())
        for requirement in ("ST 0601.8-07", "ST 0601.8-03", "ST 0601.8-06"):
            assert requirement in flat, f"{name} does not name {requirement}"
        assert "Deprecated" in flat, f"{name} does not mark the deprecation"
        # AND THE LIVE SUCCESSORS, which is the half the length round added. ST 0601.8-07's content
        # is ST 0107.3-05 and ST 0601.8-03's destination is ST 0107.3-03 — the identifiers are what
        # let a reader check the claim "the requirement moved" against six pages instead of taking it.
        for requirement in ("ST 0107.3-05", "ST 0107.3-03"):
            assert requirement in flat, (
                f"{name} does not name {requirement}. A site that says the length constraint moved "
                f"to ST 0107.3 without naming the requirement it moved to has stated an "
                f"unverifiable claim in place of a checkable one"
            )


def test_every_count_this_round_states_twice_agrees_at_both_sites():
    """The counts, collected from where they are DERIVABLE and compared against where they are TYPED.

    The stale-count discipline as a gate. Six numbers are stated at more than one site across the two
    rounds: the fixture count, the BER-OID waypoint, the width transition, the largest length octet in
    any ST 0601.14a worked example, the length-of-length bound, and the 141 rows that have not moved.
    Each is asserted where it is derivable against where it is typed, so the typed one fails rather
    than drifting — which is what happened to `.gitignore`'s own comment, corrected the same week.
    """
    section = _flat(_framing_section())
    readme = _flat(README.read_text())
    generator = _flat(GENERATOR.read_text())
    pin = json.loads(PIN.read_text())

    # 1. The fixture count: derived from disk, typed in three prose sites. 13 -> 26 this round.
    on_disk = len(sorted(FRAMING.glob("*.klvframe")))
    assert on_disk == 26
    assert len(sorted(FRAMING.glob("*.parsed.json"))) == on_disk, "a fixture is missing its twin"
    assert "Twenty-six framing fixtures" in section
    assert "Twenty-six byte-level fixtures" in readme
    assert "TWENTY-SIX fixtures" in _flat(pin["length_ruling_st_0107_3"][
        "what_was_implemented_and_what_deliberately_was_not"]["fixtures"])
    assert "twenty-six" in _flat(MIGRATIONS.read_text()).lower()

    # 2. The BER-OID waypoint: derived from the codec, typed in prose. No longer a limit — see
    #    test_the_ber_oid_ceiling_is_figure_67s_fourteen_bits_and_is_no_longer_a_limit.
    assert codec.BER_OID_MAX == 16383
    for name, text in (("FORMAT_COVERAGE.md", section), ("README", readme),
                       ("generator", generator)):
        assert "16383" in text, f"{name} does not state the BER-OID waypoint"

    # 3. The width transition, in both its forms.
    assert codec.BER_OID_SINGLE_OCTET_MAX == 127
    assert "127/128" in section and "127/128" in readme

    # 4. The largest length octet in any ST 0601.14a worked example — the measured half of the
    #    residue that USED to be the whole residue. Kept at every site, because it is the evidence
    #    that 218 pages could not have established the long form.
    assert "0x24" in section and "0x24" in readme
    assert "0x24" in _flat(SITES["adapters/klv_codec.py"]())

    # 5. The length-of-length bound: derived from the codec, typed in the section. STRUCTURAL, and
    #    the sites are required to say so rather than to state the number bare.
    assert codec.BER_LENGTH_OF_LENGTH_MAX == 127
    assert codec.BER_LENGTH_SHORT_FORM_MAX == 127
    assert "127" in section

    # 6. The 141 rows, which no round has touched, stated as untouched at both sites.
    node = pin["tag_table_st_0601_14"]
    assert node["item_count"] == 141 and len(node["items"]) == 141
    assert all(i["cdm_field"] for i in node["items"])
    assert "141" in section and "141" in readme, (
        "a site describing the round no longer states that the 141 rows did not move. That a "
        "framing round changed nothing in the tag table is a claim, and an unstated claim reads "
        "as an unexamined one"
    )

    # 7. The park arithmetic, DERIVED from the record's own closure entries rather than typed here,
    #    and then required at the prose sites. Thirteen parks, FOUR closed (1, 4, 13 and 9), nine
    #    open, eight of them downloads and one a purchase.
    #
    #    PARK 9 CLOSED 2026-08-27 and moved every term at once: closures 3 -> 4, open 10 -> 9,
    #    downloads 9 -> 8. Nothing here was retyped from the prose — the arithmetic is still
    #    DERIVED from the pin's own closure entries and the words are looked up from it, which
    #    is why closing a park is three edits to the derivation's inputs and none to its logic.
    #
    #    THE SUBSTRING FORM THIS REPLACED WAS NOT A CHECK. It read `"two" in text and "ten" in text`
    #    over the whole flattened node, which passes on any prose containing the word "two"
    #    anywhere — and it DID pass, for the whole interval in which `parks.honest_strength` said
    #    "ten that remain open" while `parks.how_many` said "Eleven remain open". Two fields of one
    #    node disagreed by one and this assertion reported agreement. The count is now derived and
    #    the two fields are required to agree with the derivation, so the same drift fails.
    parks = pin["parks"]
    closed = sorted(k for k in parks["the_ones_that_closed"] if k.startswith("park_"))
    assert closed == ["park_1", "park_13", "park_4", "park_9"], closed
    n_closed, n_total = len(closed), 13
    n_open = n_total - n_closed
    n_downloads = n_open - 1                 # park 8 is the purchase, and the only one
    assert (n_closed, n_open, n_downloads) == (4, 9, 8)
    words = {4: "four", 9: "nine", 8: "eight"}
    how_many, honest = _flat(parks["how_many"]).lower(), _flat(parks["honest_strength"]).lower()
    assert words[n_closed] in how_many and "closed" in how_many, (
        f"parks.how_many does not state {words[n_closed]!r} closures"
    )
    for field, text in (("how_many", how_many), ("honest_strength", honest)):
        assert words[n_open] in text, (
            f"parks.{field} does not state {words[n_open]!r} open parks. This is the exact field "
            "pair that drifted apart once: both state the arithmetic, so both are checked"
        )
    assert words[n_downloads] in honest, (
        f"parks.honest_strength does not state {words[n_downloads]!r} public downloads"
    )
    for text, where in ((_flat(json.dumps(parks)), "the pin's parks node"),
                        (_flat(MIGRATIONS.read_text()), "MIGRATIONS.md"),
                        (_flat(README.read_text()), "the KLV README")):
        assert "park 13" in text.lower(), f"{where} no longer mentions park 13"
    mig = _flat(MIGRATIONS.read_text()).lower()
    assert f"{words[n_closed]} closed" in mig and f"the {words[n_open]} still open" in mig, (
        "MIGRATIONS.md does not state the park arithmetic after this round's closure"
    )


def test_the_ruling_is_stated_at_every_site_and_says_the_same_thing_about_what_is_missing():
    """One sentence, six sites: the length is the residue, and it is the only one of its size.

    The shape this guards is a site that describes the round as "framing implemented" without the
    qualifier. Each site is required to name the length as the thing that is absent, so a reader
    arriving at any of them learns the same limit.
    """
    for name, read in SITES.items():
        flat = _flat(read())
        assert "length" in flat.lower()
        assert "ST 0107" in flat, f"{name} does not name the document the live route delegates to"
        assert "336" in flat, f"{name} does not name SMPTE ST 336"
        # AND WHAT IS STILL MISSING, which is now two absences rather than a whole grammar. Every
        # site has to name at least one of them, because a codec that walks a stream end to end
        # reads as complete and the reason it is not is easy to stop repeating.
        assert "0x80" in flat or "indefinite" in flat.lower() or "ceiling" in flat.lower(), (
            f"{name} describes the round and names neither residue park 8 still owns"
        )
