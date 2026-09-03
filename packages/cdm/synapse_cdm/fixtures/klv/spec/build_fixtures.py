#!/usr/bin/env python3
"""Build the KLV FRAMING fixture set. THE SOURCE OF TRUTH FOR BOTH ARTEFACTS.

    python build_fixtures.py            # from the directory this file is in

Edit this file, never the `.klvframe` octets and never the `.parsed.json` twins.

WHAT THESE ARE, AND WHAT THEY ARE NOT
--------------------------------------
They are NOT adapter fixtures. There is no `stanag4609` adapter, no CDM object comes out of any of
them, and `python -m synapse_cdm.harness` cannot replay one. They live in `../framing/` rather than
in `../` for exactly that reason: the harness selects "immediate children of the directory that are
files", so a run pointed at `fixtures/klv` still finds nothing and still fails with
`NoFixturesFound`, which is the state `../README.md` describes and which this round did not change.

What they ARE is the framing layer's evidence: byte strings exercising the rules that ST 0601.14a's
own text and worked examples establish, and the refusals at the edges of those rules. Every octet
below is derived from a sentence or a figure in the copy pinned at `ST0601.14a.pdf`, SHA-256
`3d5f1ca1…ab212ce4`, and `check_established_rules()` re-derives them from
`synapse_cdm.adapters.klv_codec`'s document-cited constants so a fixture cannot drift from the
document without failing.

THE FIXTURES THAT WERE ABSENT, AND WHAT DISCHARGED THEM
---------------------------------------------------------
The round that first wrote this file named three classes it could not write and would not guess,
because the protocol is that a fixture needing a rule the round could not establish is named in the
residue rather than invented. **All three are now here, and MISB ST 0107.3 is what discharged them:**

* **every length fixture**, including the truncated-length malformation. ST 0601.14a named "BER
  short or long form" and defined neither — the one sentence constraining a length, `ST 0601.8-07`,
  is marked **(Deprecated)**, and the live route `ST 0601.8-03` sent the rule to **MISB ST 0107.3**,
  park 4. That document is now held at `ST0107.3.pdf`, SHA-256 `500d6752…98b69794`, and its §6.3.2
  states the grammar with three worked octet strings. Nine length fixtures, four of them the
  document's own octets.
* **every key/length/value triple**, for the same reason one rule up: a triple needs a length. Two
  triplets and two whole packets, built by `_item` and `_packet` from the codec rather than typed.
* **the 16383 → 16384 tag transition**, where a BER-OID value takes a third octet. ST 0601.14a §7.1
  said "two-bytes (or more)" and never defined the "or more"; ST 0107.3 §6.3.1 states the chain rule
  for any width, so `tag_three_octet_lowest` replaces the refusal `tag_third_continuation_octet`.

**NO FIXTURE IN THIS SET IS A PARK ANY MORE, AND ONE STOPPED BEING ONE ON 2026-09-03.**
`length_indefinite_first_octet` — the octet `0x80`, declaring zero following octets — used to raise
`UnderivableFromPinnedCopy` because ST 0107.3 never mentions that form and the rule belonged to
SMPTE ST 336, park 8, which this record had priced as a purchase. **ST 336:2017 was obtained free
from the publisher and §5.3 states the form outright**, so the fixture is now an ordinary refusal:
the standard permits `0x80` only where an application document defines another way to find the end
of the Value, no held MISB document defines one, and the bytes are therefore wrong.

**The generator still asserts the exception TYPE, and now asserts it in both directions.** It was
guarding against a round that decided what `0x80` means without buying the document; it now also
guards the reverse — a round that quietly parks the question again after it has been answered. The
`ber_length_park` branch is gone rather than left empty, because a kind with no members is a
classification this fixture set no longer makes.

EVERYTHING IS SYNTHETIC, AND THERE IS NOTHING IN IT TO BE OTHERWISE
--------------------------------------------------------------------
No recorded KLV traffic and no real platform. That claim is cheaper here than anywhere else in this
repository: a framing fixture is a tag, a key or a checksum range, and none of those carries a
position, a callsign or a time. The one exception is borrowed FROM the standard — the eight octets
of the checksum vector are ST 0601.14a §8.1.1.2's own worked example, reproduced so that this
repository's `bcc_16` is checked against the document rather than against itself.

Fixture identities are UUID-v8 in the `f1c7` namespace this repository uses for synthetic
identifiers, and they identify the FIXTURE rather than anything in it, because a framing fixture's
payload has no identifiers at all to carry one.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
FIXTURES = HERE.parent.parent
FRAMING = FIXTURES / "framing"
sys.path.insert(0, str(FIXTURES.parent.parent.parent))

from synapse_cdm.adapters import klv_codec as codec                # noqa: E402
from synapse_cdm.adapters import klv_uas_codec as uas               # noqa: E402

#: UUID-v8, `f1c7` namespace, with the document this round read written into the second and third
#: groups. Version nibble `8` and RFC 9562 variant bits, so nothing issuing v4 or v7 can collide.
FIXTURE_ID = "f1c70601-14a0-8000-8000-{:012d}"

#: The adapter fixtures share the namespace and take a distinct third group, so a framing fixture
#: and a payload fixture can never collide on an index. Recorded in `fixtures/klv/README.md` rather
#: than inside a payload, for the reason the framing note gives and more so: a UAS Datalink LS
#: packet carries NO identifier of any kind — which is this round's identity finding — so there is
#: nothing in one of these payloads for a synthetic identity to stand in for.
ADAPTER_FIXTURE_ID = "f1c70601-14a0-8001-8000-{:012d}"

#: The pinned copy every citation below is read from. Stated here as well as in `klv_pin.json`
#: because a generator that cites sections without saying which copy is citing a memory.
SOURCE = ("MISB ST 0601.14a, SHA-256 "
          "3d5f1ca105befe6f48023a3cdd29262883d6b77c73c06ba915c4da91ab212ce4, "
          "fixtures/klv/spec/ST0601.14a.pdf; and MISB ST 0107.3, SHA-256 "
          "500d67522269e5fcbc39bec2521849dffdf2698ff40132552f3fd28998b69794, "
          "fixtures/klv/spec/ST0107.3.pdf")


def _tag(name, octets, value, cite, note):
    return dict(kind="ber_oid_tag", name=name, octets=octets, decodes_to=value,
                citation=cite, note=note)


def _refusal(name, kind, octets, cite, note):
    return dict(kind=kind, name=name, octets=octets, decodes_to=None,
                citation=cite, note=note)


def _length(name, octets, value, cite, note):
    return dict(kind="ber_length", name=name, octets=octets, decodes_to=value,
                citation=cite, note=note)


def _item(name, tag, value_hex, cite, note):
    """One Key-Length-Value triplet, BUILT from the codec so the octets cannot drift."""
    value = bytes.fromhex(value_hex)
    octets = (codec.encode_ber_oid(tag) + codec.encode_ber_length(len(value)) + value)
    return dict(kind="local_set_item", name=name, octets=octets.hex(),
                decodes_to=dict(tag=tag, length=len(value), value_hex=value_hex.upper()),
                citation=cite, note=note)


def _packet(name, items, cite, note):
    """A whole packet: the UL, the BER length of the Value, then the items. Built, never typed."""
    body = b"".join(
        codec.encode_ber_oid(tag) + codec.encode_ber_length(len(bytes.fromhex(v)))
        + bytes.fromhex(v)
        for tag, v in items
    )
    octets = codec.UAS_LOCAL_SET_KEY + codec.encode_ber_length(len(body)) + body
    return dict(kind="local_set_packet", name=name, octets=octets.hex(),
                decodes_to=dict(
                    value_length=len(body),
                    value_length_octets=codec.encode_ber_length(len(body)).hex().upper(),
                    items=[dict(tag=t, length=len(bytes.fromhex(v)), value_hex=v.upper())
                           for t, v in items]),
                citation=cite, note=note)


# --------------------------------------------------------------------------- the fixtures
#
# Ordered as the framing layer meets them: the key, then tags across every width transition the
# document establishes, then the refusals, then the checksum.

FIXTURES_SPEC = [
    dict(kind="universal_label", name="key_uas_local_set",
         octets=codec.UAS_LOCAL_SET_KEY.hex(), decodes_to=None,
         citation="§6.2, and the deprecated ST 0601.8-19 restating the same sixteen octets",
         note="The 16-byte UL §6.2 registers, verbatim: "
              "06.0E.2B.34.02.0B.01.01.0E.01.03.01.01.00.00.00 (CRC 56773). The CRC is carried "
              "and NOT recomputed: the document never states the polynomial."),

    dict(kind="universal_label_refusal", name="key_wrong_final_octet",
         octets=(codec.UAS_LOCAL_SET_KEY[:15] + b"\x01").hex(), decodes_to=None,
         citation="§6.2",
         note="Octet 15 is 0x01 where §6.2 registers 0x00. Refused at the differing offset, "
              "because a key that is wrong in its last octet is a different key and not a "
              "nearly-right one."),

    dict(kind="universal_label_refusal", name="key_truncated",
         octets=codec.UAS_LOCAL_SET_KEY[:15].hex(), decodes_to=None,
         citation="§6.2",
         note="Fifteen octets where a UL is sixteen. Distinguished from the wrong-octet case: "
              "this is a short buffer, and the message says so rather than naming an octet."),

    _tag("tag_single_octet_lowest", "01", 1,
         "§7.1, and §8.1's own example row `Tag Len Value / 01 02 8CED`",
         "Tag 1, Checksum — the lowest tag the local set assigns, and the one item ST "
         "0601.8-11 requires last in every instance."),

    _tag("tag_single_octet_highest", "7f", 127,
         "§7.1: 'Single-byte tags can represent tag numbers from 1 through 127'",
         "The low side of the only width transition the document states. 0x7F is 127 with the "
         "continuation bit clear."),

    _tag("tag_two_octet_lowest", "8100", 128,
         "§7.1, and §8.128's example row `Tag Len Value / 8100 0E …`",
         "The high side of the same transition, and the document works it: tag 128 is the two "
         "octets 81 00. 127 → 128 is where one octet becomes two."),

    _tag("tag_two_octet_highest_assigned", "810d", 141,
         "§8.141's example row `Tag Len Value / 810D - N/A`",
         "Tag 141, Waypoint List — the highest tag Table 1 assigns, and the top of the range the "
         "document's own examples cover. Table 1 has 141 items and this is the last of them."),

    _tag("tag_two_octet_ceiling", "ff7f", 16383,
         "Figure 67 (PDF page 212) and the paragraph beneath it: 'a 14-bit value remains'",
         "The largest value the established two-octet form can carry. Figure 67 draws the MSB "
         "byte with a leading 1 and seven payload bits and the LSB byte with a leading 0 and "
         "seven more; 14 payload bits is 16383. Above this the document says only "
         "'(or more)' — see the omitted fixtures in this generator's docstring."),

    _tag("tag_zero_octet", "00", 0,
         "§7.1 states the representable range as 1 through 127 and assigns no tag 0",
         "Framing-valid and semantically unassigned, and the split is deliberate: this layer "
         "decodes the octet and does not rule on whether a local set may carry tag 0, which is "
         "a tag-semantics question and out of this round's scope."),

    _refusal("tag_truncated_continuation", "ber_oid_refusal", "81",
             "§7.1; the overrun case",
             "A continuation bit set on the last octet in the buffer, so the value runs off the "
             "end. Refused quoting the offset the value would have continued at."),

    _tag("tag_three_octet_lowest", "818000", 16384,
         "MISB ST 0107.3 §6.3.1: 'This pattern continues until the msb of a final byte in the "
         "chain is zero' — and ST 0601.14a §7.1's undefined '(or more)'",
         "THE 16383 → 16384 TRANSITION, which the framing round named as an omitted fixture and "
         "park 4 supplied the rule for. It shipped as a REFUSAL (`tag_third_continuation_octet`, "
         "octets 818100) while the only text in hand was §7.1's '(or more)'; ST 0107.3 §6.3.1 "
         "states the chain rule for any width, so a third octet is now decoded rather than "
         "refused. 818000 is 16384: two continuation octets carrying 1 and 0, then a terminating "
         "octet carrying 0."),

    _refusal("tag_non_minimal_two_octets", "ber_oid_refusal", "8001",
             "ST 0601.8-06, Appendix A, marked (Deprecated)",
             "0x80 carries seven payload bits of zero, so `80 01` and `01` would denote the same "
             "tag. Refused per 'the fewest possible bytes', which the pinned copy states only in "
             "a deprecated requirement — a decision on deprecated authority, recorded as such."),

    # ------------------------------------------------- lengths, MISB ST 0107.3 §6.3.2
    #
    # THE FIXTURES THE FRAMING ROUND NAMED AS OMITTED. Every one of them was "every length
    # fixture, including the truncated-length malformation" until park 4 closed. Four of the nine
    # are the document's OWN octets: 0x02, 0x8180, 0x8102 and 0x8300 0080 are the four encodings
    # §6.3.2 prints while explaining which two are wasteful.

    _length("length_short_form_zero", "00", 0,
            "MISB ST 0107.3 §6.3: 'Lengths are usually positive numbers; however, a zero length "
            "is possible in unique cases'",
            "Length 0. The document admits it explicitly and says what it means — 'In the case of "
            "a zero Length, the Value is not a part of the item' — so this is framing-valid and "
            "carries no value octets. ST 0601.14a §6.5's Zero-Length Item is the same fact from "
            "the delegating document's side."),

    _length("length_short_form_document_example", "02", 2,
            "MISB ST 0107.3 §6.3.2: 'the short form one-byte (0x02) length'",
            "THE DOCUMENT'S OWN SHORT-FORM OCTET, printed while it explains that the long form "
            "0x8102 would be wasteful for the same value. The octet IS the length; there is no "
            "flag bit to strip below 0x80."),

    _length("length_short_form_highest", "7f", 127,
            "MISB ST 0107.3 §6.3.2, which names 'values less than 128' as the short form's range",
            "The low side of the 0x7F/0x80 transition. 127 is the largest length one octet "
            "carries, and 0x7F is the largest first octet that is not a long-form introducer."),

    _length("length_long_form_lowest", "8180", 128,
            "MISB ST 0107.3 §6.3.2: 'the optimized value with two bytes (0x8180)'",
            "THE DOCUMENT'S OWN LONG-FORM OCTETS, and the high side of the same transition. 0x81 "
            "declares one following octet and 0x80 is 128 big-endian per ST 0107.2-02. The "
            "document calls this 'two bytes', which is how the first octet is known to be counted "
            "in the total."),

    _length("length_long_form_two_octets", "82ffff", 65535,
            "MISB ST 0107.3 §6.3.2 for the form; ST 0107.2-02, §6.1, for the octet order",
            "0x82 declares two following octets and FFFF is 65535 big-endian. NOT a document "
            "example: the width is derived from the same first-octet rule 0x81 and 0x83 fix "
            "between them, which is why the two document examples sit beside it."),

    _refusal("length_non_minimal_long_form", "ber_length_refusal", "8102",
             "MISB ST 0107.3 §6.3.2 and ST 0107.3-05",
             "THE DOCUMENT'S FIRST NAMED INEFFICIENCY, verbatim: 'encoding the length of two (2), "
             "a value less than 128, with long form uses two bytes (0x8102) instead of the short "
             "form one-byte (0x02) length'. Refused because ST 0107.3-05 requires 'the fewest "
             "possible bytes' — a live numbered requirement, unlike the deprecated ST 0601.8-07 "
             "it replaced."),

    _refusal("length_non_minimal_padded_zeros", "ber_length_refusal", "83000080",
             "MISB ST 0107.3 §6.3.2 and ST 0107.3-05",
             "THE DOCUMENT'S SECOND NAMED INEFFICIENCY, verbatim: 'encoding the value 128 with "
             "padded zeros (0x8300 0080) instead of the optimized value with two bytes (0x8180)'. "
             "This is the fixture that fixes the length-of-length rule: 0x83 introduces THREE "
             "octets where 0x81 introduces one, so the first octet's low seven bits are a count."),

    _refusal("length_truncated_long_form", "ber_length_refusal", "82ff",
             "MISB ST 0107.3 §6.3.2; the overrun case",
             "THE TRUNCATED-LENGTH MALFORMATION the framing round could not write. 0x82 declares "
             "two following octets and one remains. A malformed stream and not a park: the rule "
             "is held, and these bytes break it."),

    _refusal("length_indefinite_first_octet", "ber_length_refusal", "80",
             "SMPTE ST 336:2017 §5.3; delegated by ST 0107.3-03",
             "0x80 declares ZERO following octets, and ST 0107.3 never mentions that form. SMPTE "
             "ST 336:2017 §5.3 does: the Length field 'shall be set to [0x80] which shall indicate "
             "a non-deterministic length of the Value field', usable only where an application "
             "document 'shall define an alternative method of locating the end of the Value "
             "field'. NO HELD MISB DOCUMENT DEFINES ONE, and ST 0107.3-05's fewest-possible-bytes "
             "rule makes every conforming length determinate — so a MISB local set carrying this "
             "octet cannot be terminated conformantly and the bytes are wrong. THIS FIXTURE WAS "
             "THE SET'S LAST PARK UNTIL 2026-09-03 and it raises KLVFramingError rather than "
             "UnderivableFromPinnedCopy since park 8 closed. The 0x7F/0x80 transition is still "
             "asymmetric: 0x7F is a length and 0x80 is a refusal."),

    # --------------------------------------------- triplets and packets, ST 0107.3 §6.3
    #
    # "A Local Set item is a Key-Length-Value triplet." These were the framing round's second
    # omitted class — "every key/length/value triple, which needs a length one rule up".

    _item("item_document_checksum_triple", 1, "8ced",
          "ST 0601.14a §8.1's own example row, 'Tag Len Value / 01 02 8CED'",
          "THE ONE TRIPLET THIS REPOSITORY DID NOT HAVE TO BUILD. Tag 1 is Checksum, the item ST "
          "0601.8-11 requires last in every instance, and the document prints the whole triplet. "
          "Its three fields exercise three separate rules — BER-OID tag, BER short-form length, "
          "opaque value — and the octets are the standard's, not this repository's."),

    _item("item_zero_length", 141, "",
          "MISB ST 0107.3 §6.3 for the zero length; ST 0601.14a §8.141's row 'Tag Len Value / "
          "810D - N/A' for the tag",
          "Tag 141, Waypoint List — the highest tag Table 1 assigns — with a zero length and no "
          "value octets. The triplet is two octets long. Confirms that a walk advances past an "
          "item whose Value 'is not a part of the item' without consuming anything for it."),

    _packet("packet_short_form_value_length",
            [(1, "8ced"), (2, "0001020304050607"), (129, "ff")],
            "ST 0601.14a §6.3 for the packet shape; MISB ST 0107.3 §6.3.2 for both length forms",
            "A WHOLE PACKET, SHORT FORM: the 16-octet UL, one length octet for a Value under 128, "
            "then three triplets — a one-octet tag, another one-octet tag, and a two-octet tag. "
            "THE TAGS ARE THE DOCUMENT'S AND THE VALUES ARE SYNTHETIC, which is the honest split: "
            "tag 1's value is §8.1's 8CED, and the other two payloads are arbitrary octets chosen "
            "to make the framing legible. Nothing here decodes a value, so no value needs to mean "
            "anything."),

    _packet("packet_long_form_value_length",
            [(1, "8ced"), (2, "aa" * 200), (141, "")],
            "ST 0601.14a §6.3 for the packet shape; MISB ST 0107.3 §6.3.2 for the long form",
            "THE FIRST FIXTURE IN THIS REPOSITORY WHERE A LONG-FORM LENGTH APPEARS IN SITU, and "
            "it appears twice — once for the 200-octet Value of tag 2, and once for the packet's "
            "own Value length, which the three items push past 127. That is what no worked example "
            "in ST 0601.14a's 218 pages does: the largest length octet in any of its 141 examples "
            "is 0x24. Values synthetic, tags the document's, lengths derived from the values."),

        dict(kind="checksum", name="checksum_document_worked_example",
         octets="060e2b34020081bb", decodes_to=0xB4FD,
         citation="§8.1.1.2, 'Sample Checksum Data'",
         note="The document's own vector, digit for digit: '64 bits to checksum: 060E 2B34 0200 "
              "81BB', then 060E + 2B34 = 3142, + 0200 = 3342, + 81BB = B4FD. It checks this "
              "repository's bcc_16 against the standard instead of against itself. NOTE the range "
              "is given rather than found: §6.6 defines the real range in terms of the checksum "
              "item's length field, and locating that needs the length grammar parks 4 and 8 own."),
]


def check_established_rules() -> None:
    """Re-derive every fixture from the codec's document-cited constants. Called by the suite.

    The point is that a fixture cannot drift from the document quietly. Each tag fixture is
    re-encoded from its stated value and each refusal is re-refused, so an octet edited by hand
    fails HERE with the rule named, rather than in a golden diff that says only that two hex
    strings differ.
    """
    for spec in FIXTURES_SPEC:
        octets = bytes.fromhex(spec["octets"])
        name = spec["name"]
        if spec["kind"] == "ber_oid_tag":
            value = spec["decodes_to"]
            assert codec.encode_ber_oid(value).hex() == spec["octets"], (
                f"{name}: encode_ber_oid({value}) is {codec.encode_ber_oid(value).hex()} and the "
                f"fixture says {spec['octets']}"
            )
            assert codec.decode_ber_oid(octets) == (value, len(octets)), (
                f"{name}: {spec['octets']} does not decode to ({value}, {len(octets)})"
            )
        elif spec["kind"] == "ber_oid_refusal":
            try:
                codec.decode_ber_oid(octets)
            except codec.KLVFramingError:
                pass
            else:
                raise AssertionError(f"{name}: {spec['octets']} was accepted and must be refused")
        elif spec["kind"] == "universal_label":
            assert codec.read_local_set_key(octets) == codec.KEY_LENGTH, name
        elif spec["kind"] == "universal_label_refusal":
            try:
                codec.read_local_set_key(octets)
            except codec.KLVFramingError:
                pass
            else:
                raise AssertionError(f"{name}: a non-key was read as the UAS Local Set key")
        elif spec["kind"] == "ber_length":
            value = spec["decodes_to"]
            assert codec.encode_ber_length(value).hex() == spec["octets"], (
                f"{name}: encode_ber_length({value}) is "
                f"{codec.encode_ber_length(value).hex()} and the fixture says {spec['octets']}"
            )
            assert codec.decode_ber_length(octets) == (value, len(octets)), (
                f"{name}: {spec['octets']} does not decode to ({value}, {len(octets)})"
            )
        elif spec["kind"] == "ber_length_refusal":
            # THE TYPE IS ASSERTED IN BOTH DIRECTIONS. Accepting these octets is the obvious
            # regression; parking them is the other one, and it became possible on 2026-09-03 when
            # `length_indefinite_first_octet` moved into this kind. A refusal that degrades back
            # into `UnderivableFromPinnedCopy` would be a round quietly un-reading ST 336:2017,
            # which reads as caution and is a retreat from a document on disk.
            try:
                codec.decode_ber_length(octets)
            except codec.UnderivableFromPinnedCopy as exc:        # pragma: no cover - regression
                raise AssertionError(
                    f"{name}: {spec['octets']} was parked rather than refused ({exc}). Every "
                    f"length refusal in this set has a held document behind it — ST 0107.3-05 for "
                    f"the non-minimal forms and §6.3.2 for the overrun, SMPTE ST 336:2017 §5.3 for "
                    f"0x80 — so none of them is a park"
                ) from exc
            except codec.KLVFramingError:
                pass
            else:
                raise AssertionError(
                    f"{name}: {spec['octets']} was accepted and a held document refuses it"
                )
        elif spec["kind"] == "local_set_item":
            expected = spec["decodes_to"]
            tag, after_tag = codec.decode_ber_oid(octets)
            length, after_length = codec.decode_ber_length(octets, after_tag)
            assert tag == expected["tag"], f"{name}: tag {tag} != {expected['tag']}"
            assert length == expected["length"], f"{name}: length {length} != {expected['length']}"
            assert octets[after_length:].hex().upper() == expected["value_hex"], name
            assert after_length + length == len(octets), (
                f"{name}: the triplet is {after_length + length} octets and the fixture holds "
                f"{len(octets)}"
            )
        elif spec["kind"] == "local_set_packet":
            expected = spec["decodes_to"]
            walked = list(codec.walk_local_set(octets))
            assert [i.tag for i in walked] == [i["tag"] for i in expected["items"]], name
            assert [i.length for i in walked] == [i["length"] for i in expected["items"]], name
            assert [i.value.hex().upper() for i in walked] == [
                i["value_hex"] for i in expected["items"]], name
            after_key = codec.read_local_set_key(octets)
            declared, _ = codec.decode_ber_length(octets, after_key)
            assert declared == expected["value_length"], (
                f"{name}: the packet declares {declared} and the fixture says "
                f"{expected['value_length']}"
            )
        elif spec["kind"] == "checksum":
            got = codec.bcc_16(octets)
            assert got == spec["decodes_to"], (
                f"{name}: bcc_16 gives 0x{got:04X} and §8.1.1.2 works it to "
                f"0x{spec['decodes_to']:04X}"
            )
        else:                                                     # pragma: no cover - closure
            raise AssertionError(f"{name}: unknown fixture kind {spec['kind']!r}")


def build() -> list[pathlib.Path]:
    """Write the octets and their twins. Returns every path written, for the caller to report."""
    check_established_rules()
    FRAMING.mkdir(parents=True, exist_ok=True)
    written = []
    for index, spec in enumerate(FIXTURES_SPEC, start=1):
        octets = bytes.fromhex(spec["octets"])
        payload = FRAMING / f"{spec['name']}.klvframe"
        payload.write_bytes(octets)
        twin = FRAMING / f"{spec['name']}.parsed.json"
        twin.write_text(json.dumps({
            "fixture_id": FIXTURE_ID.format(index),
            "name": spec["name"],
            "kind": spec["kind"],
            "octets_hex": spec["octets"].upper(),
            "octet_count": len(octets),
            "decodes_to": spec["decodes_to"],
            "refused": spec["kind"].endswith("refusal"),
            "source": SOURCE,
            "citation": spec["citation"],
            "note": spec["note"],
        }, indent=2) + "\n")
        written.extend((payload, twin))
    return written


# ======================================================================================
# THE ADAPTER FIXTURES — whole payloads for `adapters/stanag4609.py`, adapter #10
# ======================================================================================
#
# A DIFFERENT CLASS FROM THE TWENTY-SIX ABOVE, AND THE DIRECTORY SAYS SO. The framing fixtures in
# `framing/` are tags, lengths and keys; no CDM object comes out of one and the harness cannot
# replay them. These are UAS Datalink LS PAYLOADS in `fixtures/klv/` itself, where the harness looks
# — which is the sentence FORMAT_COVERAGE.md carried for two rounds ("There is still no `.klv`
# payload in `fixtures/klv/`") coming due.
#
# EVERY OCTET IS SYNTHETIC, AND THE ONE THING BORROWED IS BORROWED FROM THE STANDARD. Not one of
# these payloads contains a run from `fixtures/klv/streams/day_flight.klv`. What the value-carrying
# fixture uses instead is each item's OWN worked example from its §8.x block — the same borrowing
# `framing/`'s checksum vector makes, and for the same reason: a fixture whose values come from the
# document checks this repository's maps against the document rather than against themselves. The
# held stream decided WHICH tags to cover; it supplied no octets.
#
# WHY THE DEFECT FIXTURE IS NOT THE STREAM'S BYTES. The length-divergence fixture reproduces the
# CLASS — four octets under a Required Length of 2 — with a value the stream does not carry, because
# a golden file built from a real emitter's defective octets would make this repository's test suite
# a place where somebody else's stream lives. The class is what the policy rules on; the particular
# four octets are park 13's evidence and stay in the report.

#: One entry per adapter fixture: the packet's items in wire order, and what the fixture is FOR.
#: `ST 0601.8-09` and `-11` put item 2 first and item 1 last, and `encode_packet` enforces it.
_EXAMPLE = {tag: item.example_octets for tag, item in uas.ITEMS.items()}


def _payload(*packets) -> bytes:
    """Concatenate whole packets. A payload may hold several and the pinned stream holds six."""
    return b"".join(packets)


def _packet(items, *, checksum_override=None) -> bytes:
    """One packet from `[(tag, value_hex), ...]`, built by the codec and never typed.

    `checksum_override` writes a stated checksum that is NOT the computed one, which is the only
    way to build the fixture that asks what happens when §6.6's summation disagrees.
    """
    order = tuple(tag for tag, _ in items)
    # Tag 1 is deliberately NOT handed to `raw_overrides`: `encode_packet` REPLAYS a checksum it is
    # given and COMPUTES one it is not, so passing the §8.1 example octets `8CED` would build every
    # fixture with a stored checksum that does not validate over its own packet. The one fixture
    # that WANTS that carries `checksum_override` instead, which is the only way to state it on
    # purpose rather than by accident.
    overrides = {tag: bytes.fromhex(value) for tag, value in items if tag != 1}
    octets = uas.encode_packet({}, order=order, raw_overrides=overrides)
    if checksum_override is not None:
        octets = octets[:-2] + checksum_override.to_bytes(2, "big")
    return octets


ADAPTER_FIXTURES: tuple[dict, ...] = (
    dict(
        name="witnessed_set_from_the_documents_own_examples",
        octets=_payload(_packet(
            [(2, _EXAMPLE[2])]
            + [(tag, _EXAMPLE[tag]) for tag in uas.WITNESSED_TAGS if tag not in (1, 2)]
            + [(1, _EXAMPLE[1])])),
        what_it_is_for=(
            "all 26 witnessed items in one packet, each carrying the Example KLV Value its own "
            "§8.x block prints. Every affine map, every string and every identity conversion in "
            "`klv_uas_codec` runs once here, against values transcribed from the document rather "
            "than chosen by this repository. Tag 1's value is REPLACED on the way out — "
            "`encode_packet` computes §6.6's checksum over the packet it actually built, so the "
            "example checksum octets `8CED` are what the fixture asked for and the computed sum "
            "is what it carries"),
        citation="ST 0601.14a §8.1 through §8.65, each item's Example KLV Value row",
    ),
    dict(
        name="length_divergence_at_a_required_length",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (22, "00000FA0"),                    # four octets where §8.22 requires two
            (56, _EXAMPLE[56]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "THE POLICY FIXTURE. Tag 22 Target Width at FOUR octets where §8.22's Required Length "
            "cell says 2 — the divergence class park 13 adjudicated, reproduced with octets the "
            "held stream does not carry. What must happen: the ITEM is skipped, its octets are "
            "parked verbatim, a structured `LengthDivergence` names both bases of the ruling, and "
            "the other four items translate normally. What must NOT happen: the packet refused "
            "(candidate a), or `0x00000FA0` read as 4000 by a truncation rule no document states "
            "(candidate c)"),
        citation=("ST 0601.14a §8.22 Required Length 2; ST 0601.13-29 in §7; "
                  "FORMAT_COVERAGE.md, 'Park 13 adjudicated and CLOSED'"),
    ),
    dict(
        name="zero_length_item_is_an_explicit_unknown",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (56, ""),                            # a ZLI on an item where one is allowed
            (13, _EXAMPLE[13]), (14, _EXAMPLE[14]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "a Zero-Length Item on tag 56, which is NOT a defect: `ST 0601.14-33` says 'Where a "
            "UAS Data-link LS item has a length of zero, consumers shall interpret the value of "
            "the item as \"unknown\"'. So it decodes to an explicit unknown, `Kinematics` is None "
            "rather than a speed of zero, and no defect is recorded. The distinction this catches "
            "is the one that matters most in a never-drop model: a producer SAYING a value is now "
            "unknown, versus a producer not mentioning the item"),
        citation="ST 0601.14a §6.5 and ST 0601.14-33",
    ),
    dict(
        name="zero_length_item_on_a_required_item_is_a_defect",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (65, ""),                            # ST 0601.14-32 forbids a ZLI here
            (56, _EXAMPLE[56]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "the one zero-length case the document itself makes a defect. `ST 0601.14-32`: the "
            "required items '(Tag 1 - Checksum, Tag 2 - Precision Time Stamp, and Tag 65 - UAS "
            "Datalink LS Version Number) shall always be reported with positive lengths (i.e. "
            "Zero-Length Items (ZLI) are not allowed for these items)'. So a ZLI on tag 65 is "
            "reported as `zero_length_on_a_required_item` while the same octets on tag 56 above "
            "are an explicit unknown — which is the policy reading the document rather than "
            "applying one rule to a length of zero"),
        citation="ST 0601.14a §6.5 and ST 0601.14-32",
    ),
    dict(
        name="special_values_are_signals_and_not_measurements",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (6, "8000"),                         # §8.6: "Out of Range" indicator
            (13, "80000000"),                    # §8.13: "Reserved"
            (14, _EXAMPLE[14]),
            (23, "80000000"),                    # §8.23: "N/A (Off-Earth)" indicator
            (24, _EXAMPLE[24]),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "the three Special Values the witnessed set declares, each in an item that declares "
            "it. What must happen: none of them is run through its item's affine map, so no "
            "`Position` is built from a 'Reserved' latitude and no `Event.geometry` from an "
            "'N/A (Off-Earth)' frame centre — even though tag 14 and tag 24 are present and "
            "valid, which is the case where a half-built point is tempting. Run the map anyway "
            "and 0x80000000 becomes a latitude of -90.0000000419: a plausible-looking lie, which "
            "is the class of defect this repository's ellipsoid audit exists for"),
        citation="ST 0601.14a §8.6, §8.13 and §8.23, Special Values cells; §7's definition of the "
                 "Special Values column",
    ),
    dict(
        name="over_recommended_max_length_is_an_advisory",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (11, ("41" * 128)),                  # 128 octets where Max Length is 127
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "a variable-length item one octet past its Max Length. This is NOT the length-"
            "divergence class and the document is why: §7 defines Max Length as 'the recommended "
            "maximum length' and names a network guard as its consumer, so nothing here breaks a "
            "'shall'. The item is DECODED and carries an advisory. Treating it like a "
            "ST 0601.13-29 violation would enforce a requirement the document did not write, "
            "which is the mirror image of the mistake candidate (c) would have made"),
        citation="ST 0601.14a §7, the Max Length column definition; §8.11",
    ),
    dict(
        name="an_unwitnessed_tag_is_skipped_and_the_packet_translates",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (3, "4D5F3335"),                     # tag 3 Mission ID, outside the witnessed set
            (56, _EXAMPLE[56]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "`ST 0107.3-04` in the one place it can be tested from above the framing layer: "
            "'Applications which decode MISB KLV Local Sets shall skip unknown Local Set values "
            "so as to not impact the decoding of known Local Set items within the same Local Set "
            "instance'. Tag 3 is a real ST 0601 item that this round did not cover because the "
            "pinned stream does not carry it, so it is UNKNOWN to `klv_uas_codec` and its octets "
            "are parked at attributes.klv_unknown_items. The packet translates and no defect is "
            "recorded — an uncovered item is not a malformed one. It is also the fixture that "
            "would break if a later round widened the witnessed set without updating the scope "
            "contract, which is deliberate"),
        citation="MISB ST 0107.3 ST 0107.3-04; ST 0601.14a §8.3",
    ),
    dict(
        name="mandatory_items_only",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "the smallest conformant packet the standard admits: the three items ST 0601.14a "
            "makes Mandatory and nothing else. It is the fixture that proves the absences are "
            "absences — no Position, no Kinematics, no Event.geometry, and "
            "attributes.unavailable_fields saying so in words rather than the object simply "
            "having fewer keys"),
        citation="ST 0601.14a §6.4, §8.1, §8.65 and ST 0601.14-32",
    ),
    dict(
        name="two_packets_one_payload_are_two_statements",
        octets=_payload(
            _packet([(2, "000459F4A6AA4AA8"), (65, _EXAMPLE[65]),
                     (13, _EXAMPLE[13]), (14, _EXAMPLE[14]), (56, "8C"), (1, _EXAMPLE[1])]),
            _packet([(2, "000459F4A6B24AA8"), (65, _EXAMPLE[65]),
                     (13, _EXAMPLE[13]), (14, _EXAMPLE[14]), (56, "8D"), (1, _EXAMPLE[1])]),
        ),
        what_it_is_for=(
            "two packets in one payload, half a second apart, at the same position and one metre "
            "per second different in ground speed. Four objects come out, not two, and the two "
            "Entities have DIFFERENT entity_id values — which is the packet-scoped identity's "
            "cost made visible in a golden file rather than described in a docstring. Nothing is "
            "accumulated across the boundary: no velocity is differenced, no state is carried"),
        citation="ST 0601.14a §6.3; FORMAT_COVERAGE.md, the fusion refusal",
    ),
    dict(
        name="a_checksum_that_does_not_validate_is_flagged_not_refused",
        octets=_payload(_packet(
            [(2, _EXAMPLE[2]), (65, _EXAMPLE[65]), (56, _EXAMPLE[56]), (1, _EXAMPLE[1])],
            checksum_override=0x0000)),
        what_it_is_for=(
            "a packet whose stored tag 1 disagrees with §6.6's summation over its own octets. It "
            "TRANSLATES, and attributes.integrity_basis carries `valid: false`. The reasoning is "
            "the length policy's: the stored checksum is one item among the packet's items, and "
            "discarding the others because a 16-bit sum disagrees destroys the evidence a "
            "consumer needs. `valid: false` on an object is a statement; a missing object is not"),
        citation="ST 0601.14a §6.6 and §8.1",
    ),
)


def build_adapter_fixtures() -> list[pathlib.Path]:
    """Write the payloads, their parsed twins and nothing else. Goldens are the harness's job."""
    from synapse_cdm.adapters import stanag4609                        # noqa: PLC0415
    written = []
    for index, spec in enumerate(ADAPTER_FIXTURES, start=1):
        payload = FIXTURES / f"{spec['name']}.klv"
        payload.write_bytes(spec["octets"])
        # PURE SOURCE DATA, and the fixture's own documentation is deliberately NOT in it. The
        # four sibling binary adapters' parsed twins carry the payload and nothing else — `block`
        # and `records`, `header` and `segments` — because the harness's lossless check harvests
        # every leaf of a JSON fixture and requires each to appear in the CDM output, so a
        # `what_it_is_for` string in the twin would have to be echoed into an object to pass. Each
        # fixture's purpose, citation and UUID-v8 identity are in `fixtures/klv/README.md` instead.
        parsed = stanag4609.parse_payload(spec["octets"])
        twin = FIXTURES / f"{spec['name']}.parsed.json"
        twin.write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n")
        written.extend((payload, twin))
    return written


if __name__ == "__main__":
    paths = build() + build_adapter_fixtures()
    for path in paths:
        print(path.relative_to(FIXTURES.parent.parent.parent))
    print(f"{len(FIXTURES_SPEC)} framing fixtures, {len(ADAPTER_FIXTURES)} adapter fixtures, "
          f"{len(paths)} files")
