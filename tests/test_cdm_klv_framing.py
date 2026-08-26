"""The KLV framing layer: the rules ST 0601.14a establishes, and the one it delegates.

WHAT THIS MODULE GUARDS THAT NOTHING ELSE DOES
-----------------------------------------------
`tests/test_cdm_format_coverage.py` guards the STANAG 4609 section's pins, its 141-row tag table and
its park roster. It has nothing to say about the framing layer, because until 2026-08-26 there was
none: the section's own preamble said so — "parks 4 and 8 own how a key and a length are written".

The framing round asked whether that was true of ST 0601.14 itself and found that **two thirds of it
is not**. The document states its own Universal Label (§6.2), its own BER-OID tag form (§7.1 and
Figure 67) and its own checksum (§6.6, §8.1.1.1–2), and delegates the **length** grammar alone. So
`adapters/klv_codec.py` exists, implements exactly that, and refuses exactly the rest — and this
module is what stops the two halves drifting into each other.

THE FAILURE MODE IT IS SHAPED AROUND
-------------------------------------
Not a wrong byte. The hazard here is a *creeping* one and it runs in one direction: somebody with
BER in their fingers adds four lines to `decode_ber_length`, every fixture in `framing/` still
passes, the suite goes green, and this repository now ships a length grammar it read nowhere. That
is the exact failure the round's document rule exists to prevent, so the refusals are asserted as
positively as the acceptances — `decode_ber_length` **must raise**, and it must raise something that
names the park.

THE DISJUNCTION PROTOCOL, RUN OVER THE FACTS THIS ROUND STATES MORE THAN ONCE
------------------------------------------------------------------------------
Six sites now state the framing ruling: `FORMAT_COVERAGE.md`, `MIGRATIONS.md`, `klv_pin.json`,
`fixtures/klv/README.md`, `adapters/klv_codec.py` and `fixtures/klv/spec/build_fixtures.py`. Every
fact stated at more than one of them is collected **by regex from the files** and required to agree
at all of them — 80b38d1's finding, which is that an `in` check is satisfied by one site while a
fact stated at six sites can drift at five. The facts are the pinned copy's digest, the two park
states, the section citations behind each established rule, and every count this round introduced.
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


def test_the_ber_oid_ceiling_is_figure_67s_fourteen_bits():
    """16383, because Figure 67 draws two 7-bit payloads and its paragraph says "a 14-bit value".

    Read rather than remembered, which is the point: §7.1 states WHERE the width changes and never
    states HOW a multi-octet value is assembled, so without Figure 67 this number would have been a
    recollection with a section number pinned to it.
    """
    assert codec.BER_OID_MAX == (1 << 14) - 1 == 16383
    assert codec.BER_OID_MAX_OCTETS == 2
    assert codec.encode_ber_oid(16383) == b"\xff\x7f"
    with pytest.raises(codec.KLVFramingError) as excinfo:
        codec.encode_ber_oid(16384)
    assert "14-bit value" in str(excinfo.value)


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


def test_the_four_ber_oid_refusals_each_name_what_they_are_refusing():
    """Truncation, a third octet, a non-minimal encoding, and an empty slice.

    Asserted on the MESSAGE and not only on the type, because these four are the boundary of what
    this round established and a caller meeting one needs to know which side of the boundary they
    are on — a malformed stream or a rule nobody here has read.
    """
    with pytest.raises(codec.KLVFramingError) as empty:
        codec.decode_ber_oid(b"")
    assert "no octets remain" in str(empty.value)

    with pytest.raises(codec.KLVFramingError) as overrun:
        codec.decode_ber_oid(b"\x81")
    assert "runs off the end" in str(overrun.value)

    with pytest.raises(codec.KLVFramingError) as third:
        codec.decode_ber_oid(b"\x81\x81\x00")
    assert "park 4" in str(third.value) and "park 8" in str(third.value)
    assert "or more" in str(third.value)

    with pytest.raises(codec.KLVFramingError) as minimal:
        codec.decode_ber_oid(b"\x80\x01")
    assert "fewest possible bytes" in str(minimal.value)
    assert "Deprecated" in str(minimal.value), (
        "the minimality refusal rests on ST 0601.8-06, which this edition marks (Deprecated). A "
        "message that did not say so would present a decision as a derivation"
    )


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


# ------------------------------------------------------- what the document does NOT establish


@pytest.mark.parametrize("call", [
    lambda: codec.decode_ber_length(b"\x02"),
    lambda: codec.encode_ber_length(2),
    lambda: codec.walk_local_set(b""),
], ids=["decode_ber_length", "encode_ber_length", "walk_local_set"])
def test_the_delegated_half_raises_and_names_the_park(call):
    """THE LOAD-BEARING NEGATIVE. These three must not work, and they must say why.

    The creeping failure this module exists for is somebody supplying the familiar BER length rule
    from memory: four lines in `decode_ber_length`, every framing fixture still green, and this
    repository ships a grammar it read nowhere. So the refusal is asserted as positively as any
    acceptance, and on the message as well as the type — a bare `NotImplementedError` would let the
    reopen condition be deleted without failing anything.

    `encode_ber_length` is in the list for a reason of its own: a module that could EMIT a length it
    cannot parse would let a fixture be written from the reconstructed rule, which is precisely what
    the fixture protocol forbids.
    """
    with pytest.raises(codec.UnderivableFromPinnedCopy) as excinfo:
        call()
    message = str(excinfo.value)
    assert "ST 0601.8-07" in message and "(Deprecated)" in message
    assert "ST 0601.8-03" in message
    assert "PARK 4" in message and "PARK 8" in message
    assert "0x24" in message, (
        "the message no longer carries the measured bound on the worked examples, which is the "
        "half of the residue that is evidence rather than citation"
    )


def test_the_underivable_exception_is_not_the_malformed_one():
    """"These bytes are wrong" and "nobody here knows whether they are wrong" are different claims.

    Conflating them would report a park as a malformed stream, which is the error that makes a
    blocker invisible: a caller sees a parse failure, retries with different bytes, and never learns
    that no bytes would have worked.
    """
    assert not issubclass(codec.UnderivableFromPinnedCopy, codec.KLVFramingError)
    assert not issubclass(codec.KLVFramingError, codec.UnderivableFromPinnedCopy)


def test_the_codec_registers_no_adapter():
    """A codec, not an adapter — asserted, because the difference is a roster claim.

    An `Adapter` subclass registers itself on definition, so a module that grew one would take an
    ordinal and a roster row for something that cannot read a local set. Checked by AST rather than
    by importing and counting the registry, so it fails on the SOURCE that would do it.
    """
    tree = ast.parse((PKG / "adapters" / "klv_codec.py").read_text())
    bases = [b for node in ast.walk(tree) if isinstance(node, ast.ClassDef) for b in node.bases]
    names = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in bases}
    assert "Adapter" not in names, (
        "klv_codec defines an Adapter subclass. The framing layer cannot read a local set, and a "
        "module that registers as an adapter claims it can — see the pin's "
        "framing_ruling_st_0601_14.what_was_implemented_and_what_deliberately_was_not"
    )
    from synapse_cdm import adapter as adapter_module
    assert "klv" not in adapter_module.discover()
    assert "stanag4609" not in adapter_module.discover()


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
    assert len(twins) == 13, f"{len(twins)} framing fixtures, expected 13"
    seen = set()
    for path in twins:
        record = json.loads(path.read_text())
        assert record["citation"].strip(), f"{path.name} cites no section"
        assert ST_0601_14A in record["source"], f"{path.name} does not name the pinned copy"
        identity = record["fixture_id"]
        assert re.fullmatch(r"f1c7[0-9a-f]{4}-[0-9a-f]{4}-8[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}",
                            identity), (
            f"{path.name}'s id {identity} is not a UUID-v8 in the f1c7 namespace"
        )
        assert identity not in seen, f"{identity} is used twice"
        seen.add(identity)


def test_no_framing_fixture_needed_a_rule_this_round_could_not_cite():
    """THE OMISSIONS, asserted as an absence — the half a fixture set cannot state about itself.

    Three classes were omitted rather than guessed: every length fixture, every key/length/value
    triple, and the 16383 → 16384 tag transition. An absence is invisible, so it is checked from
    both ends: nothing on disk exercises a length or a triple, and the residue is named in prose at
    the three sites that describe the fixture set.
    """
    for path in sorted(FRAMING.glob("*.parsed.json")):
        record = json.loads(path.read_text())
        assert record["kind"] in {
            "universal_label", "universal_label_refusal",
            "ber_oid_tag", "ber_oid_refusal", "checksum",
        }, (
            f"{path.name} is a {record['kind']} fixture. The framing round established the key, the "
            "tag and the checksum and nothing else — a fixture of any other kind needs a rule it "
            "could not cite"
        )
    for site in (_framing_section(), README.read_text(), GENERATOR.read_text()):
        flat = _flat(site)
        assert "omitted" in flat and "16383" in flat, (
            "a site describing the framing fixtures no longer names what was left out. An omitted "
            "fixture and a forgotten one look identical on disk"
        )


def test_the_framing_fixtures_are_not_reachable_as_adapter_fixtures():
    """The subdirectory is the mechanism, not the manners.

    `fixtures/klv/README.md` claims a harness run pointed at `fixtures/klv` still finds nothing, and
    `test_cdm_format_coverage.py::test_the_klv_fixture_directory_holds_no_fixtures_and_says_why`
    asserts it. That claim survives only while `framing/` stays a DIRECTORY: the harness selects
    "immediate children of the directory that are files", so one `.klvframe` copied up a level would
    silently turn thirteen citations into thirteen adapter fixtures for an adapter that does not
    exist.
    """
    from synapse_cdm import harness
    assert "immediate children" in harness.FIXTURE_PATTERN
    strays = [p.name for p in FIXTURES.iterdir()
              if p.is_file() and p.name != "README.md" and not p.name.startswith(".")]
    assert strays == [], f"fixtures/klv holds files: {strays}"
    assert FRAMING.is_dir()


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


def test_the_pinned_copy_is_the_same_copy_at_every_site_that_names_one():
    """The digest, full or abbreviated, and no third form anywhere.

    An abbreviation is where a hash drifts unnoticed, because eight characters at each end look
    right for any digest that starts and ends the same way — and nothing checks an ellipsis. So
    every abbreviated form found by regex must expand to the pinned digest.
    """
    pin = json.loads(PIN.read_text())
    assert pin["delegated_specifications_held"]["st_0601_14"]["sha256"] == ST_0601_14A
    found = {}
    for name, read in SITES.items():
        text = read()
        abbreviations = set(re.findall(r"\b([0-9a-f]{8})…([0-9a-f]{8})\b", text))
        for head, tail in abbreviations:
            if not (ST_0601_14A.startswith(head) or ST_0601_14A.endswith(tail)):
                continue                      # another document's pin, checked by its own gate
            found.setdefault(name, set()).add(f"{head}…{tail}")
    assert found, "no site abbreviates the pinned digest, so this check is vacuous"
    for name, abbreviations in found.items():
        assert abbreviations == {ABBREVIATED}, (
            f"{name} abbreviates the ST 0601.14a digest as {sorted(abbreviations)}, expected "
            f"{ABBREVIATED!r}"
        )


def test_parks_four_and_eight_are_stated_OPEN_wherever_this_round_names_them():
    """The park states, at every site, in both directions.

    The tempting error in a round that narrows a park is to write it up as progress and let a reader
    infer a closure. So the pin says OPEN as data, the prose says OPEN in words, and no site
    anywhere may say either park closed.
    """
    ruling = json.loads(PIN.read_text())["framing_ruling_st_0601_14"]["the_park_outcome"]
    for park in ("park_4", "park_8"):
        assert ruling[park]["state_after_this_round"] == "OPEN"
        assert ruling[park]["state_before_this_round"] == "OPEN"

    section = _flat(_framing_section())
    assert "Parks 4 and 8 both stay OPEN" in section
    for name, read in SITES.items():
        flat = _flat(read())
        for claim in ("park 4 is closed", "park 8 is closed", "parks 4 and 8 are closed",
                      "park 4 closed", "park 8 closed", "closes park 4", "closes park 8"):
            assert claim.lower() not in flat.lower(), (
                f"{name} states {claim!r}. No document was obtained this round, so no park state "
                "moved — and a narrowed park written up as a closed one is the failure the "
                "framing ruling is most exposed to"
            )


def test_every_established_rule_cites_the_same_section_at_the_pin_and_in_the_document():
    """The section citations, collected by regex from the pin and required in the prose.

    The pin is the machine-readable record and `FORMAT_COVERAGE.md` is where a reader arrives, and
    a citation that lives at only one of them is a citation nobody can check against the other. The
    loci come OUT of the pin rather than out of a list here, so a rule recorded with a new section
    is checked without anybody maintaining a roster of what is legal to cite.
    """
    ruling = json.loads(PIN.read_text())["framing_ruling_st_0601_14"]
    section = _flat(_framing_section())
    loci = set()
    for rule in ruling["established_from_the_pinned_copy"]:
        loci |= set(re.findall(r"SS (\d+(?:\.\d+)*)", rule["locus"]))
        loci |= set(re.findall(r"(Figure \d+)", rule["locus"]))
    assert loci, "no locus was parsed out of the pin, so this check is vacuous"
    missing = sorted(q for q in loci if q not in section and f"§{q}" not in section)
    assert not missing, (
        f"the framing section does not cite {missing}, and the pin records them as the loci of an "
        "established rule. Two statements of one reading have to name the same page"
    )


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


def test_every_count_this_round_states_twice_agrees_at_both_sites():
    """The counts, collected by regex and compared — the stale-count discipline as a gate.

    Five numbers are stated at more than one site by this round: the fixture count, the tag ceiling,
    the width transition, the largest length octet in any worked example, and the 141 rows that did
    not move. Each is asserted where it is DERIVABLE against where it is TYPED, so the typed one
    fails rather than drifting.
    """
    section = _flat(_framing_section())
    readme = _flat(README.read_text())
    generator = _flat(GENERATOR.read_text())
    pin = json.loads(PIN.read_text())

    # 1. The fixture count: derived from disk, typed in three prose sites.
    on_disk = len(sorted(FRAMING.glob("*.klvframe")))
    assert on_disk == 13
    assert "Thirteen framing fixtures" in section, section[:0] or "the count moved"
    assert "Thirteen byte-level fixtures" in readme
    assert "thirteen fixtures" in _flat(pin["framing_ruling_st_0601_14"][
        "what_was_implemented_and_what_deliberately_was_not"]["fixtures"])

    # 2. The BER-OID ceiling: derived from the codec, typed in prose.
    assert codec.BER_OID_MAX == 16383
    for name, text in (("FORMAT_COVERAGE.md", section), ("README", readme),
                       ("generator", generator)):
        assert "16383" in text, f"{name} does not state the established BER-OID ceiling"

    # 3. The width transition, in both its forms.
    assert codec.BER_OID_SINGLE_OCTET_MAX == 127
    assert "127/128" in section and "127/128" in readme

    # 4. The largest length octet in any worked example — the measured half of the residue.
    assert "0x24" in section and "0x24" in readme
    assert "0x24" in _flat(SITES["adapters/klv_codec.py"]())

    # 5. The 141 rows, which this round did not touch, stated as untouched at both sites.
    node = pin["tag_table_st_0601_14"]
    assert node["item_count"] == 141 and len(node["items"]) == 141
    assert all(i["cdm_field"] for i in node["items"])
    assert "141" in section and "141" in readme, (
        "a site describing the framing round no longer states that the 141 rows did not move. "
        "That the round changed nothing in the tag table is a claim, and an unstated claim reads "
        "as an unexamined one"
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
