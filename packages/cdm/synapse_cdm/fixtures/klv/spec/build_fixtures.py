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

from synapse_cdm.adapters import imapb_codec as imapb              # noqa: E402
from synapse_cdm.adapters import klv_codec as codec                # noqa: E402
from synapse_cdm.adapters import klv_pack_codec as packs           # noqa: E402
from synapse_cdm.adapters import klv_security_codec as security   # noqa: E402
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


# ======================================================================================
# THE ST 0102.12 SECURITY LOCAL SET FIXTURES — item 48, and every one is built from a CLAUSE
# ======================================================================================
#
# **THE DOCUMENT SUPPLIES NO WORKED EXAMPLE AND THAT IS WHY THIS BLOCK IS DIFFERENT.** Every other
# value-carrying fixture in this file borrows its octets from a printed Example KLV Value, so the
# decoder is checked against the document rather than against this repository. MISB ST 0102.12
# prints none — its only examples are two country codes at §6.1.2/§6.1.3 and one Tag 2 value at
# §6.9, and ST 0601.14a §8.48's own Example KLV Item row reads `30 - N/A`. So
# `check_against_the_documents_own_examples` HAS NO ANALOGUE HERE AND IS NOT SIMULATED. These
# fixtures are built from the ELEMENT RULES, each citing the clause it exercises, which is a
# weaker arrangement than the 26 items enjoy and is labelled as one.
#
# **NO FIXTURE CARRIES A REAL-WORLD MARKING.** Two kinds of value appear and they are kept apart
# deliberately:
#
# * codes the HELD DOCUMENT ITSELF PRINTS — `0x01` for UNCLASSIFIED// (§6.7's Allowed Values cell
#   and §6.3's `ST 0102.10-51`), `0x0C` for STANAG 1059 Mixed (§6.9's own worked Tag 2 value, the
#   only element value the document prints), `//CZE` and `//GB` (§6.1.3's own examples), `0x000C`
#   for the Version (§6.1.15's rule, "the version number of MISB ST 0102 referenced", applied to
#   this document);
# * everything else is a CLEARLY SYNTHETIC string — `SYNTHETIC-...`, and `ZZZ` where a second
#   country code is needed, `ZZ` being the ISO 3166 user-assigned range and unmistakably not a
#   state. **Not one caveat, compartment, handling instruction or releasability marking used in
#   the real world appears in any fixture below**, and no fixture pairs a coding method with a
#   code of the wrong length.
#
# A NOTE ON §6.1.2's AND §6.1.3's EXAMPLES, which do NOT pair: §6.1.2 prints "GENC Two Letter" and
# §6.1.3 prints "//CZE (Example of GENC code)", a THREE-letter code. They are two independent
# examples in two sections and not one worked set, so a fixture combining them verbatim would be
# internally incoherent. Each fixture below therefore pairs a document code with a coding method
# of the matching width — `//GB` with ISO-3166 Two Letter (0x01), `//CZE` with the Mixed method
# §6.9 prints — and this note records that the choice was made rather than found.

def _element(tag: int, octets: bytes) -> bytes:
    """One ST 0102 Local Set triplet: BER-OID tag, BER length, Value."""
    return codec.encode_ber_oid(tag) + codec.encode_ber_length(len(octets)) + octets


def _security_set(elements) -> str:
    """A whole item 48 Value from `[(tag, bytes), ...]`, as hex for `_packet`'s overrides.

    NO KEY AND NO OUTER LENGTH: ST 0601.14a §8.48, "The length field is the size of all MISB ST
    0102 metadata items to be packaged within item 48". What item 48 carries is the triplets.
    """
    return b"".join(_element(tag, octets) for tag, octets in elements).hex()


#: The complete set's element values, one per row of §6.7's Table 2. Kept as a named table rather
#: than inline so the minimal and partial fixtures below draw from the same values and a reader
#: can see at one site that nothing here is a real marking.
_SECURITY_VALUES: tuple[tuple[int, bytes], ...] = (
    (1, bytes([0x01])),                                    # UNCLASSIFIED//, §6.7 and §6.3's -51
    (2, bytes([0x0C])),                                    # STANAG 1059 Mixed, §6.9's own example
    (3, "//CZE".encode("ascii")),                          # §6.1.3's own printed code
    (4, "SYNTHETIC-SCI-A/SYNTHETIC-SHI-B//".encode("ascii")),   # -09 separator, -10 terminator
    (5, "SYNTHETIC-CAVEAT-ONE//".encode("ascii")),         # §6.1.5, -08's double-slash ending
    (6, "CZE ZZZ".encode("ascii")),                        # -16's blank separator, -17's one entry
    (7, "SYNTHETIC CLASSIFICATION AUTHORITY".encode("ascii")),
    (8, "SYNTHETIC SOURCE DOCUMENT".encode("ascii")),
    (9, "SYNTHETIC CLASSIFICATION REASON".encode("ascii")),
    (10, "20301231".encode("ascii")),                      # -22's YYYYMMDD, stated Length 8
    (11, "SYNTHETIC MARKING SYSTEM".encode("ascii")),      # -21, free text
    (12, bytes([0x0E])),                                   # GENC Three Letter, tag 12's own table
    (13, "CZE;ZZZ".encode("utf-16-be")),                   # -24's semicolon; UTF-16BE, no BOM
    #        ^ the octets were always UTF-16BE and were CARRIED as hex until 2026-09-04, when
    #          RFC 2781 became a held document. They now DECODE, under §4.3's no-BOM default,
    #          which is why this fixture regenerated rather than being retired: the bytes are
    #          unchanged and the reading of them is what moved. `CZE` is §6.1.3's own printed
    #          code and `ZZZ` is in ISO 3166's user-assigned range, so neither names a real
    #          country claim.
    (14, "SYNTHETIC CLASSIFICATION COMMENT".encode("ascii")),
    (22, (12).to_bytes(2, "big")),                         # §6.1.15: this document's version, 12
    (23, "2016-07-08".encode("ascii")),                    # ref [6]'s own GENC 3.0.1 date
    (24, "2016-07-08".encode("ascii")),                    # the same, stated Length 10
)

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
    # ------------------------------------------------------------------ ST 0102.12, item 48
    dict(
        name="security_local_set_complete_from_the_element_rules",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (48, _security_set(_SECURITY_VALUES)),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "ALL SEVENTEEN ST 0102.12 elements in one Security Metadata Local Set, carried in ST "
            "0601 item 48. Every row of §6.7's Table 2 decodes once here — the three uint8 "
            "enumerations through their own tables, the uint16 Version, twelve ISO/IEC 646 "
            "strings, and tag 13 DECODED AS UTF-16 since 2026-09-04, when RFC 2781 became a "
            "held document. "
            "It is the fixture the confidentiality ruling is checked on: every value is either a "
            "code the document prints or a string beginning SYNTHETIC, and tag 1 is 0x01 "
            "UNCLASSIFIED//, which is the one classification §6.3 itself names in prose. **TAG 13'S OCTETS DID NOT MOVE AND THIS FIXTURE STILL REGENERATED**, which is the whole shape of what the text-pins round did: the bytes were UTF-16BE from the day they were written, they were carried as hex because no held document said which end came first, and they now read as `CZE;ZZZ` split into two codes. A fixture whose input is unchanged and whose golden moved is a reading that changed, and that is the only thing that changed here"),
        citation=("ST 0102.12 §6.7 Table 2 (all 17 rows), §6.1.1-§6.1.17, §6.8's three "
                  "conversions; §6.9's own Tag 2 value 0x0C; §6.1.3's own //CZE; ST 0601.14a "
                  "§8.48 and ST 0601.14-31 for the carrier"),
    ),
    dict(
        name="security_local_set_minimal_required_only",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),                        # UNCLASSIFIED//
                (2, bytes([0x01])),                        # ISO-3166 Two Letter
                (3, "//GB".encode("ascii")),               # §6.1.3's own ISO-3166 example
                (12, bytes([0x01])),                       # ISO-3166 Two Letter, tag 12's table
                (13, "GB".encode("utf-16-be")),
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "the six elements §6.7 marks `Required` and nothing else — the smallest set that is "
            "not partial under §6.4. It is the fixture that proves the eleven absences are "
            "absences: no caveats key, no releasing instructions key, no declassification date, "
            "and `security_metadata_basis.state` reading COMPLETE-ON-REQUIRED rather than the "
            "object merely having fewer keys. The coding method and the code AGREE IN WIDTH here "
            "— ISO-3166 Two Letter with //GB, which §6.1.3 prints as its ISO-3166 example"),
        citation=("ST 0102.12 §6.7's Required/Optional/Context column (tags 1, 2, 3, 12, 13, 22); "
                  "§6.4; §6.1.3's own //GB"),
    ),
    dict(
        name="security_local_set_partial_is_carried_as_partial",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (5, "SYNTHETIC-CAVEAT-ONE//".encode("ascii")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "§6.4's SHAPE: a set carrying three of the six `Required` elements and one `Context` "
            "element, which the document explicitly admits — 'For some operational situations or "
            "applications not all metadata elements in Section 6.1 may be required'. What must "
            "happen: the set DECODES, `partial` is true, `required_absent` names tags 12, 13 and "
            "22, and no element is completed or defaulted. What must NOT happen: the set refused "
            "for incompleteness, which would be enforcing a rule §6.4 declines to state. Note the "
            "absent Version: `ST 0102.10-57` says version three 'shall be assumed' and the "
            "advisory records that clause WITHOUT writing 3 into the decoded elements"),
        citation="ST 0102.12 §6.4; §6.7's presence column; §6.1.15's ST 0102.10-57",
    ),
    dict(
        name="no_security_local_set_is_unlabelled_not_unclassified",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (11, _EXAMPLE[11]), (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**§6.5's FIXTURE, AND IT IS THE ONE THIS ROUND EXISTS FOR AS MUCH AS THE COMPLETE "
            "SET.** A well-formed UAS Datalink LS packet carrying NO item 48. 'The absence of "
            "Security Metadata does not signify Motion Imagery Data as Unclassified', so what "
            "must happen is that the object carries NO `security_metadata` key at all — not an "
            "empty one, not a null classification — and carries "
            "`security_metadata_basis.state` reading UNLABELLED with §6.5 CITED beside it in "
            "`clauses` — the surface round of 2026-09-04 moved the sentence itself into the "
            "record and left the pointer on the wire. What must NOT happen is any of the three ways a decoder can quietly say "
            "unclassified: a default value, an empty object a reader can take for an empty "
            "marking, or silence. Item 48 is `Optional` in ST 0601.14a §8.48, so this packet is "
            "fully conformant and the absence is not a defect"),
        citation="ST 0102.12 §6.5, and §6.3 for the contrast; ST 0601.14a §8.48 'Required in LS? Optional'",
    ),
    dict(
        name="security_classification_outside_the_enumeration_carries_no_label",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x07])),                        # not one of §6.7's five listed values
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x01])),
                (13, "GB".encode("utf-16-be")),
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**THE CONFIDENTIALITY RULING'S SHARPEST CASE.** Tag 1 carries `0x07`, which §6.7's "
            "Allowed Values cell does not list — it enumerates 0x01 through 0x05 and no more. "
            "What must happen: the INTEGER is carried, NO label is produced, and an advisory "
            "names the clause. What must NOT happen: a nearest match (0x05 TOP SECRET// is the "
            "closest listed value and choosing it would be this adapter inventing a marking), a "
            "refusal that drops the element and makes the packet read as unlabelled when it is "
            "not, or a default. A classification is CARRIED AND NEVER INVENTED, and an integer "
            "with no name is exactly what carrying it looks like"),
        citation="ST 0102.12 §6.7 Table 2 tag 1 Allowed Values; §6.8.1; §6.1.1",
    ),
    dict(
        name="security_required_element_at_a_forbidden_length_is_refused",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01, 0x00])),                  # TWO octets where Table 2 states 1
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x01])),
                (13, "GB".encode("utf-16-be")),
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "A MALFORMED `Required` ELEMENT. Tag 1 Security Classification at two octets where "
            "§6.7's Length (Bytes) cell states 1 and its Data Type states uint8. What must "
            "happen: the ELEMENT is refused, its octets are parked verbatim, the refusal names "
            "the cell, and the other five elements decode — `klv_uas_codec`'s length policy "
            "reached by a second document, and §6.4 plus §6.5 are why it is safe here: a set that "
            "loses an element to a refusal is a shape §6.4 already admits, and the resulting gap "
            "cannot be mistaken for a claim because §6.5 says an absent marking is not "
            "'unclassified'. What must NOT happen: the first octet read as the value, the whole "
            "set refused, or the packet refused"),
        citation="ST 0102.12 §6.7 Table 2 tag 1 Length (Bytes) = 1, Data Type = uint8; §6.4; §6.5",
    ),
    dict(
        name="security_uint16_that_the_format_cannot_carry_is_refused",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x01])),
                (13, "GB".encode("utf-16-be")),
                (22, bytes([0x0C])),                       # ONE octet under a uint16 of Length 2
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "A LENGTH THE FORMAT CANNOT CARRY. Tag 22 Version at one octet where §6.7 states Data "
            "Type uint16 and Length 2 — a single octet cannot form a two-octet unsigned integer, "
            "so there is no reading of it that is not a guess. What must happen: the element is "
            "refused with `format_cannot_carry_the_octets`, the octet is parked, and the "
            "remaining five elements decode. What must NOT happen: zero-extension to 0x000C, "
            "which would produce a version number the packet did not state and which happens to "
            "be the RIGHT one for this document — the most dangerous possible near-miss, and the "
            "reason this fixture uses 0x0C rather than an arbitrary octet"),
        citation="ST 0102.12 §6.7 Table 2 tag 22 Data Type = uint16, Length (Bytes) = 2; §6.1.15",
    ),
    # ---------------------------------------------- tag 13's byte order, one fixture per clause
    #
    # Added 2026-09-04 by the text-pins round, once RFC 2781 was held and pinned. Each of the five
    # cites the clause it witnesses, and between them they cover every branch
    # `read_object_country_codes` has: a BOM in each direction, the no-BOM default, `-24`'s split,
    # and the two refusals. The codes are §6.1.3's own printed examples — `//CZE (Example of GENC
    # code)` and `//GB (Example of ISO-3166 code)` — so no fixture here asserts a country claim
    # this repository invented.
    dict(
        name="security_object_country_codes_big_endian_bom_is_honoured_and_stripped",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x0E])),                       # GENC Three Letter, tag 12's own table
                (13, b"\xfe\xff" + "CZE".encode("utf-16-be")),
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**RFC 2781 §4.3's FIRST BRANCH.** Tag 13 carries `0xFEFF` then `CZE` in UTF-16BE. "
            "What must happen: the byte order is read as big-endian FROM THE MARK rather than "
            "from the default, the mark is STRIPPED — §3.2's rationale, the signature is not part "
            "of the object — and `value` reads `CZE` with `byte_order_mark` naming which "
            "signature was found. What must NOT happen: the mark surviving into the value as a "
            "zero-width non-breaking space, which is what a decoder that honours §4.3 and ignores "
            "§3.2 produces, and which is invisible in every rendering a human will look at. THE "
            "FIXTURE IS NOT REDUNDANT WITH THE UNMARKED ONE even though both are big-endian: "
            "there the order comes from a default and here from the bytes, and only one of the "
            "two can be got wrong by assuming"),
        citation="RFC 2781 §4.3 first branch and §3.2; ST 0102.12 §6.7 Table 2 tag 13 Data Type",
    ),
    dict(
        name="security_object_country_codes_little_endian_bom_is_honoured_with_an_advisory",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x0E])),
                (13, b"\xff\xfe" + "CZE".encode("utf-16-le")),
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**THE ONE CASE WHERE THE TWO HELD DOCUMENTS PULL APART, AND THE FIXTURE THAT DECIDES "
            "IT.** Tag 13 carries `0xFFFE` then `CZE` in UTF-16LE. RFC 2781 §4.3 says such text "
            "can be interpreted as little-endian and MUST NOT be assumed otherwise without "
            "reading the first two octets; `ST 0107.2-02` says byte order shall be big-endian "
            "across all MISB documents. What must happen: the value DECODES to `CZE` under §4.3, "
            "and an advisory of class `byte_order_contradicts_st_0107_2_02` records that the "
            "producer broke the MISB baseline — the `ST 0102.10-57` precedent at tag 22, where a "
            "clause is recorded and not applied. What must NOT happen: a refusal, which would "
            "discard a value the packet carried because its producer broke a rule; or a "
            "big-endian read, which turns `CZE` into two ideographs and calls them country "
            "codes — the most dangerous outcome here, because it is a plausible-looking string"),
        citation="RFC 2781 §4.3 second branch; MISB ST 0107.3 §6.1 `ST 0107.2-02` and §1's scope",
    ),
    dict(
        name="security_object_country_codes_with_no_bom_are_big_endian_by_two_documents",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x0E])),
                (13, "CZE".encode("utf-16-be")),           # no BOM: §4.3's third branch
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**RFC 2781 §4.3's THIRD BRANCH, WHICH IS THE ORDINARY CASE AND THE ONE THAT WAS "
            "UNREADABLE FOR AS LONG AS RFC 2781 WAS UNHELD.** Tag 13 carries `CZE` in UTF-16BE "
            "with no mark. What must happen: `byte_order` reads `big` and `byte_order_mark` is "
            "null, so the object distinguishes an order that was DETERMINED from one that was "
            "DEFAULTED. **The default is not this layer's choice**: §4.3 says such text SHOULD be "
            "big-endian and `ST 0107.2-02` says it SHALL be, so two held documents agree and the "
            "second is the custodian of the document that cites the first. That agreement is the "
            "finding this fixture exists to fix in place — the round expected the byte order to "
            "rest on one SHOULD"),
        citation=("RFC 2781 §4.3 third branch; MISB ST 0107.3 §6.1 `ST 0107.2-02`; ST 0102.12 "
                  "§6.1.13, which states no byte order in its own voice"),
    ),
    dict(
        name="security_object_country_codes_multiple_are_split_on_the_semicolon",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x0E])),
                (13, "CZE;GB".encode("utf-16-be")),
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**`ST 0102.10-24` AND `-25`, APPLIED FOR THE FIRST TIME.** Tag 13 carries `CZE;GB` — "
            "both codes §6.1.3 prints as its own examples, one GENC and one ISO-3166. What must "
            "happen: `value` is the whole string, because `-25` makes multiple codes ONE entry, "
            "and `codes` is `[\"CZE\", \"GB\"]`, because `-24` makes the semi-colon the separator. "
            "Both are emitted, which is not redundancy: the entry is what the packet sent and the "
            "split is what the clause says it means. What must NOT happen: splitting on blanks — "
            "§6.1.13's own Note says the semi-colon was chosen 'instead of blanks or other "
            "characters' precisely so automated tools can split it — or validating either code, "
            "which would require registers this repository does not hold. **`-26` IS NOT "
            "APPLIED**: nothing here computes a country from a frame centre, so the ORDER of the "
            "two codes carries no claim about which region is under the centre"),
        citation=("ST 0102.12 §6.1.13's `ST 0102.10-24`, `-25` and `-26`, and its Note on the "
                  "separator; §6.1.3's own //CZE and //GB"),
    ),
    dict(
        name="security_object_country_codes_at_an_odd_octet_count_is_refused",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x0E])),
                (13, "CZE".encode("utf-16-be")[:-1]),      # five octets: a code unit cut in half
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**AN OCTET COUNT UTF-16 CANNOT CARRY, AND THE LENGTH CELL FORBIDS NOTHING.** Tag 13 "
            "carries five octets. §6.7's Length (Bytes) cell for this element reads `Variable`, "
            "so unlike tag 1 and tag 22 there is NO stated length to disagree with — the refusal "
            "comes from the ENCODING: RFC 2781 §3.1 serialises each 16-bit code unit as two "
            "octets, so an odd count is not a sequence of code units under either byte order. "
            "What must happen: refusal class `utf16_cannot_carry_an_odd_octet_count`, the five "
            "octets parked verbatim, and the other five elements decode. What must NOT happen: "
            "dropping the trailing octet and decoding four, which produces `CZ` — a shorter, "
            "entirely plausible country code that the packet did not send. That is the near-miss "
            "this fixture exists for, and it is the tag 22 zero-extension trap in a second place"),
        citation=("RFC 2781 §3.1 and §2.2; ST 0102.12 §6.7 Table 2 tag 13 Length (Bytes) = "
                  "Variable; §6.4 and §6.5 for why refusing one element is safe"),
    ),
    dict(
        name="security_object_country_codes_with_a_lone_surrogate_is_refused",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]),
            (48, _security_set((
                (1, bytes([0x01])),
                (2, bytes([0x01])),
                (3, "//GB".encode("ascii")),
                (12, bytes([0x0E])),
                (13, bytes.fromhex("0043d8000045")),       # 'C', a high surrogate alone, 'E'
                (22, (12).to_bytes(2, "big")),
            ))),
            (65, _EXAMPLE[65]), (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**RFC 2781 §2.2's ERROR CASES, WHICH ARE A SEPARATE REFUSAL FROM THE ODD COUNT AND "
            "ARE HERE SO THE SECOND CLASS IS NOT AN UNWITNESSED BRANCH.** Tag 13 carries six "
            "octets — a well-formed count — whose middle code unit is `0xD800`, a high surrogate "
            "with no low surrogate after it. §2.2 step 3: 'If there is no W2 ... or if W2 is not "
            "between 0xDC00 and 0xDFFF, the sequence is in error.' What must happen: refusal "
            "class `utf16_sequence_is_in_error`, distinct from the odd-count class because the "
            "REPAIRS differ — an odd count is a framing fault upstream and this is a content "
            "fault — and the octets parked verbatim. What must NOT happen: a replacement "
            "character, which is what a non-strict decode produces and which would put `\ufffd` "
            "into a country code; or error recovery of any kind, since §2.2 says 'Error recovery "
            "is not specified by this document' and inventing one would be reading a rule off "
            "nothing"),
        citation="RFC 2781 §2.2 steps 2 and 3; ST 0102.12 §6.7 Table 2 tag 13 Data Type",
    ),
)


# ======================================================================================
# THE PARK 5 FIXTURES — the fifteen document-witnessed items, and every one cites a clause
# ======================================================================================
#
# **THESE ARE THE FIRST FIXTURES IN THIS FILE WHOSE ITEMS THE PINNED STREAM DOES NOT CARRY.** The
# 26-item block above draws its octets from the document AND those items are attested by
# `fixtures/klv/streams/day_flight.klv`; the ST 0102.12 block draws from element rules with no
# worked example anywhere. This block is a third arrangement and it is the one RULING 1
# (2026-09-04) licensed: **the octets are the DOCUMENT'S OWN PRINTED Example KLV Values, and no
# held stream carries any of these tags.** So the fixtures are as strong as the 26-item block on
# the only axis that separates a fixture from a guess — nobody here chose the octets — and weaker
# on the axis the scope contract cares about, which is whether anyone has met them on a wire.
#
# Nothing below is a real platform, a real airbase or a real sensor. The wavelength record is the
# document's own `NNIR` example; the coordinates in the HAE fixtures are §8.13/§8.14's own printed
# Example KLV Values, which is where every geographic octet in this file comes from.

#: Each of the fourteen IMAPB items' own printed Example KLV Value, keyed by tag. Read from the
#: codec's table rather than re-typed here, so a fixture cannot carry octets the codec's own
#: worked-example check has not already reproduced against the document.
_IMAPB_EXAMPLE = {tag: octets for tag, (_x, _len, octets) in imapb.IMAPB_WORKED_EXAMPLES.items()}

#: ST 1201.3 §7.2.3 Table 2's eight patterns, one per tag and each at a DIFFERENT length, so the
#: fixture also proves what §7.4 requires: the special-value test is on the top two bits of the
#: value at the width the wire supplied, and is not a comparison against a fixed sentinel. The top
#: five bits are the pattern; the remainder is Table 2's `bn-5 … b0`, which it gives a meaning to
#: for the two SNaN rows ("Remaining bits are used as the signal value") and for `UserDefined`.
_IMAPB_SPECIALS: tuple[tuple[int, str, str], ...] = (
    (96,  "C80000",   "+Inf"),
    (103, "E80000",   "-Inf"),
    (105, "D00000",   "+QNaN"),
    (109, "F000",     "-QNaN"),
    (113, "D8002A",   "+SNaN, with 42 as Table 2's own signal value"),
    (114, "F800002A", "-SNaN, with 42 as the signal value at a fourth octet"),
    (117, "E000",     "Reserved"),
    (118, "C00007",   "UserDefined, with 7 in the user-defined remainder"),
)

_PARK_5_FIXTURES: tuple[dict, ...] = (
    dict(
        name="imapb_items_from_the_documents_own_examples",
        octets=_payload(_packet(
            [(2, _EXAMPLE[2]), (65, _EXAMPLE[65])]
            + [(tag, _IMAPB_EXAMPLE[tag]) for tag in sorted(_IMAPB_EXAMPLE)]
            + [(1, _EXAMPLE[1])])),
        what_it_is_for=(
            "all fourteen IMAPB items in one packet, each carrying the Example KLV Value its own "
            "§8.x block prints. It is the adapter-level twin of "
            "`imapb_codec`'s worked-example check: that check runs the map, this one runs the map "
            "THROUGH the item layer, the adapter and the schema, so a tag wired to the wrong "
            "range, decoded at a fixed width instead of the wire's, or landing in the wrong "
            "attribute fails here. Two of the fourteen reach canonical fields — tag 104 fills "
            "Position.alt_m and tag 112 fills Kinematics.course_deg — and the other twelve land at "
            "attributes.document_witnessed_items under the names the document gives them. Note "
            "what is NOT here: no Position is built, because tags 13 and 14 are absent and an "
            "altitude with no coordinates is not a fix"),
        citation="ST 0601.14a §8.96 … §8.134, each item's Example KLV Item row; ST 1201.3 §7.1.2",
    ),
    dict(
        name="hae_is_tag_104_and_never_tag_15s_msl",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (13, _EXAMPLE[13]), (14, _EXAMPLE[14]),
            (15, _EXAMPLE[15]),                  # 14 190.7195 m MSL, §8.15's own example
            (104, _IMAPB_EXAMPLE[104]),          # 23 456.24 m HAE, §8.104's own example
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**RULING 4's FIXTURE (2026-09-04): ONE PACKET CARRYING BOTH ALTITUDES.** Tag 15 "
            "Sensor True Altitude is MSL and stream-witnessed; tag 104 Sensor Ellipsoid Height "
            "Extended is HAE and document-witnessed. `ST 0601.8-17` requires a decoder that "
            "understands HAE to 'use the HAE representation and ignore the Mean Sea Level (MSL) "
            "representation when both exist in the same UAS Datalink LS packet', and §8.104.1, "
            "§8.75.1 and §8.15.1 each state 'preference for Tag 75 | Tag 104'. What must happen: "
            "Position.alt_m is 104's 23 456.234375 m and NOT 15's 14 190.72 m, and the MSL figure "
            "is still parked whole at attributes.sensor_true_altitude_msl_m. **What must NOT "
            "happen is a precedence rule firing**: alt_m is an HAE field and tag 15 was never a "
            "candidate for it, so the right answer here comes out of the field's definition rather "
            "than out of a comparison — which is the whole of RULING 4. The two values are 9 265 m "
            "apart, deliberately: a fixture where the two altitudes were close would pass under a "
            "wiring that read the wrong one"),
        citation=("ST 0601.14a §8.15, §8.104 and their Details subsections; ST 0601.8-17; "
                  "FORMAT_COVERAGE.md, RULING 4 of the park 5 round"),
    ),
    dict(
        name="tag_104_carrying_a_signal_emits_no_altitude",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (13, _EXAMPLE[13]), (14, _EXAMPLE[14]),
            (104, "D00000"),                     # +QNaN, ST 1201.3 §7.2.3 Table 2
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "RULING 4's second fixture: tag 104 present and carrying a ST 1201.3 §7.2.3 signal "
            "rather than a height. What must happen: a Position IS emitted — tags 13 and 14 are "
            "measurements — with alt_m None, the signal recorded at "
            "attributes.position_basis.alt_not_measured naming which of Table 2's eight patterns "
            "it was, and attributes.unavailable_fields saying Position.alt_m is unavailable "
            "BECAUSE the item was present and not a measurement, which is a different statement "
            "from the item being absent. What must NOT happen: 0xD00000 run through §7.2.2's "
            "reverse map, which yields 40 038 m — a plausible-looking altitude above the item's "
            "own stated maximum, and the same class of defect item 13's 0x80000000 got"),
        citation="ST 1201.3 §7.2.3 Tables 1 and 2; ST 0601.14a §8.104",
    ),
    dict(
        name="imapb_special_values_are_signals_and_not_measurements",
        octets=_payload(_packet(
            [(2, _EXAMPLE[2]), (65, _EXAMPLE[65])]
            + [(tag, octets) for tag, octets, _name in _IMAPB_SPECIALS]
            + [(1, _EXAMPLE[1])])),
        what_it_is_for=(
            "**ALL EIGHT of ST 1201.3 §7.2.3 Table 2's patterns in one packet, each on a different "
            "item and each at a different length** — two, three and four octets — because §7.4 "
            "makes the width the wire's and a special-value test written against a fixed sentinel "
            "would pass at one width and fail at another. The two SNaN rows and UserDefined carry "
            "a non-zero remainder, which Table 2 gives a meaning to ('Remaining bits are used as "
            "the signal value'), so the fixture also proves the payload survives. What must "
            "happen: eight signals, no numbers, each rendered with its Table 2 name and its "
            "remainder. **The twin of the witnessed set's own "
            "`special_values_are_signals_and_not_measurements`**, one document down: there the "
            "sentinels are integers ST 0601.14a's own Special Values cells declare, here they are "
            "bit patterns ST 1201.3 reserves in every IMAPB value regardless of what the §8.x "
            "Special Values cell says — and every one of these fourteen cells says 'None', which "
            "is exactly why this fixture is not redundant"),
        citation="ST 1201.3 §7.2.3 Table 1 and Table 2; §7.4 on the KLV-supplied length",
    ),
    dict(
        name="a_wavelengths_list_from_the_documents_own_example",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (128, str(packs.WAVELENGTHS_LIST_EXAMPLE["value_octets"])),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "tag 128 Wavelengths List, carrying §8.128's own printed Example KLV Value — "
            "`0D 15 0000 07D0 0000 0FA0 4E4E 4952` against the Software Value "
            "'21,1000, 2000, NNIR (Narrow NIR)'. It is the only pack fixture in this file whose "
            "octets the document prints, and **the only pack in park 5's sixteen that has an "
            "example at all**: §8.130's Example Software Value cell reads 'N/A', which is one of "
            "the two reasons tag 130 stays `not yet`. Four things must come out right and each "
            "would fail differently — the VLP's BER length (§6.3), the BER-OID Wavelength ID, two "
            "IMAPB(0, 1e9, 4) members in NANOMETRES, and a utf8 name whose length is found by the "
            "FLP subtraction §8.128.1 prints, 'Namelen = Length1 - (BEROIDlen + 8)'"),
        citation="ST 0601.14a §6.3 (the VLP/DLP/FLP grammar), §8.128 and §8.128.1 with Table 15",
    ),
    dict(
        name="a_short_wavelength_record_is_refused_and_the_packet_translates",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (56, _EXAMPLE[56]),
            # A record declaring nine octets: a one-octet BER-OID id and EIGHT for two four-octet
            # IMAPB members needs nine exactly, so this is one short of the minimum and there is
            # no room for a name. §8.128.1's own rule gives Namelen = 8 - (1 + 8) = -1.
            (128, "0815000007D000000F"),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "a malformed pack, and the fixture that fixes the POLICY for one. The wavelength "
            "record declares eight octets where its own layout needs at least nine, so "
            "§8.128.1's name-length rule yields a NEGATIVE length. What must happen: **the ITEM "
            "is refused and the PACKET is not** — the ST 0102.12 element precedent and the "
            "length-divergence ruling's own ground, that discarding well-formed items over one "
            "malformed one destroys the evidence a consumer needs. So tag 56's ground speed still "
            "reaches Kinematics.speed_mps, the pack's octets are parked verbatim at "
            "attributes.klv_item_octets['128'], and a structured refusal at "
            "attributes.pack_refusals names the clause. What must NOT happen: the packet refused, "
            "or the eight octets read as a record with an empty name — which is the same "
            "truncation-by-guessing that candidate (c) was rejected for at tag 22"),
        citation="ST 0601.14a §8.128.1's Namelen rule and Table 15's Mandatory members; §6.3",
    ),
    dict(
        name="a_course_of_360_degrees_is_the_documents_own_zero",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (56, _EXAMPLE[56]),
            (112, "5A00"),                       # IMAPB(0, 360, 2) maps 360.0 to exactly 0x5A00
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "the one value tag 112 can carry that the CDM's own field cannot hold as it stands. "
            "§8.112's range is IMAPB(0, 360) — CLOSED at both ends — so 360.0 is conformant and "
            "encodes to exactly `5A00` at two octets, while Kinematics.course_deg is documented "
            "'[0, 360)' and declares lt=360.0. What must happen: course_deg is 0.0, and "
            "attributes.kinematics_basis.course_360_folded_to_0 says so and quotes the sentence "
            "that licenses it — §8.112's own bullet, '0 (or 360) is true north, east is 90, south "
            "is 180, west is 270'. **The document states the identity, so the fold applies its "
            "sentence rather than this adapter's judgement.** What must NOT happen: a "
            "ValidationError on a conforming packet, a silent clamp to 359.99, or a schema change "
            "— the last was this round's brief's explicit STOP"),
        citation="ST 0601.14a §8.112 and its bullets; models.Kinematics.course_deg",
    ),
    dict(
        name="a_zero_length_imapb_item_is_an_explicit_unknown",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (13, _EXAMPLE[13]), (14, _EXAMPLE[14]),
            (104, ""),                           # a ZLI on a document-witnessed item
            (112, ""),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "`ST 0601.14-33` reaching the fifteen document-witnessed items, which is the length "
            "policy applying to them unchanged rather than being re-decided for them. A "
            "zero-length tag 104 and tag 112 are the producer SAYING those values are now "
            "unknown, not a defect: neither is among the three items `ST 0601.14-32` forbids a "
            "ZLI on, so no defect is recorded, alt_m and course_deg are None, and the explicit "
            "unknown is carried as itself. It also exercises the one branch of `imapb_codec` that "
            "REFUSES rather than decodes — `decode` raises on empty octets, calling a "
            "zero-length item 'ST 0601.14a §6.5's explicit unknown and the caller's to handle' — "
            "so this fixture proves the item layer handles it above the codec and the codec is "
            "never asked"),
        citation="ST 0601.14a §6.5, ST 0601.14-33 and ST 0601.14-32; ST 1201.3 §7.4",
    ),
    dict(
        name="an_imapb_item_past_its_max_length_is_an_advisory",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            # Tag 120's Max Length cell says 3; four octets is one past it, and §7 makes Max
            # Length "the recommended maximum length" rather than a `shall`.
            (120, "48000000"),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "the Max Length advisory on a document-witnessed item, which is the third branch of "
            "`_length_verdict` — the only one an IMAPB item can reach, since all fifteen state "
            "`Length` Variable and `Required Length` N/A and `ST 0601.13-29` therefore reaches "
            "none of them. What must happen: the value is DECODED at four octets — §7.4's rule, "
            "'it is important to compute the constants needed to do the forward and reverse "
            "mapping based on the KLV supplied length', so the constants differ from the "
            "three-octet case and the answer is still right — and an advisory records that the "
            "item is past its recommendation. What must NOT happen: a defect, a refusal, or a "
            "decode at the recommended width, which is the mutation "
            "`test_cdm_imapb_codec.py` already fixtures for tag 112"),
        citation="ST 0601.14a §7's Max Length column definition, §8.120; ST 1201.3 §7.4",
    ),
)




# ======================================================================================
# THE PARK 3 FIXTURES — items 136 and 137, and the arithmetic §6.4 states as two equations
# ======================================================================================
#
# **THE OCTETS ARE THE DOCUMENT'S OWN, THE SAME ARRANGEMENT THE PARK 5 BLOCK USES**, and the same
# limit applies: no held stream carries either tag, so these fixtures are as strong as the 26-item
# block on the axis of who chose the octets and weaker on the axis of who has met them on a wire.
# §8.136 prints `30 seconds` against `8108 01 1E`; §8.137 prints `1:23:45.678901` against
# `8109 05 012B 8DC6 35`. Both are read out of `klv_uas_codec.TIME_ADJUSTMENT_ITEMS` rather than
# re-typed, so a fixture cannot carry octets the worked-example check has not already reproduced.
#
# **WHAT THIS BLOCK EXISTS TO PIN IS AN ARITHMETIC AND NOT A DECODE.** Two of the five carry a
# value the document does not print — a negative adjustment, and an explicit unknown — and each is
# there because the document's own printed example cannot reach the case: `012B8DC635` has a clear
# top bit, so it decodes to the same integer signed or unsigned and cannot witness §8.137's
# contradiction between its Format cells and its `Softval = KLVuint` conversion line (KLV 23); and
# no printed example is zero-length, so nothing else here would catch a round that let an absent
# leap-second count become a silent `+0`.

#: §8.136's and §8.137's own printed Example KLV Values, keyed by tag, read from the codec's table.
_TIME_EXAMPLE = {tag: spec.example_octets
                 for tag, spec in uas.TIME_ADJUSTMENT_ITEMS.items()}

_PARK_3_FIXTURES: tuple[dict, ...] = (
    dict(
        name="the_time_adjustments_from_the_documents_own_examples",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (136, _TIME_EXAMPLE[136]),           # 30 seconds, §8.136's own example
            (137, _TIME_EXAMPLE[137]),           # 1:23:45.678901, §8.137's own example
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**BOTH TERMS OF ST 0601.14a §6.4 EQUATION 2 IN ONE PACKET, each carrying the Example "
            "KLV Value its own §8.x block prints.** Equation 2 reads `TCorrected = TPrecision + "
            "TCorrection + (LSeconds * 1,000,000)`, and with §8.2's printed stamp of "
            "1 224 807 209 913 000 µs, §8.137's 5 025 678 901 µs and §8.136's 30 s the instant is "
            "1 224 812 265 591 901 µs — 2008-10-24T01:37:45.591Z once times.render truncates to a "
            "millisecond. What must happen: observed_at is that instant, "
            "attributes.precision_time_stamp_us is still the RAW 1 224 807 209 913 000 because "
            "§6.4's own reason for the Correction Offset is that the stamp is NOT rewritten, and "
            "attributes.time_basis records both terms as applied with the clause each came from. "
            "What must NOT happen: either term applied twice, the correction multiplied by "
            "1 000 000 (which is the leap-second term's rule and not its own), or the raw stamp "
            "moved"),
        citation=("ST 0601.14a §6.4 Equations 1 and 2, §8.136 and §8.137 Example KLV Item rows; "
                  "MISB ST 0603.5 §6"),
    ),
    dict(
        name="leap_seconds_alone_convert_the_stamp_toward_utc",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (136, _TIME_EXAMPLE[136]),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**EQUATION 2 WITH ITS CORRECTION TERM ABSENT, which is the case a real packet is far "
            "likeliest to be.** Tag 137 is a post-mission item and tag 136 is not, so a live feed "
            "carrying one carries this one. What must happen: observed_at is "
            "2008-10-24T00:13:59.913Z, thirty seconds past the raw stamp; "
            "time_basis.leap_second_adjustment says applied with §8.136's bullet quoted; and "
            "time_basis.correction_offset says NOT applied because the packet carries no tag 137 "
            "— not applied as zero, which is the distinction RULING 2 of the park 3 round exists "
            "to hold. **And what the object still does not claim**: MISB ST 0603.5 §6 derives UTC "
            "'using its correct offset and inclusion of leap seconds', and this is the leap "
            "seconds only, so time_basis.relation_to_UTC names the 82-microsecond residue rather "
            "than letting the object read as UTC on the nose"),
        citation="ST 0601.14a §6.4 Equation 2 and §8.136; MISB ST 0603.5 §6 and its footnote 2",
    ),
    dict(
        name="a_correction_offset_is_applied_and_the_raw_stamp_is_kept",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (137, _TIME_EXAMPLE[137]),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**EQUATION 1 ALONE, and it is the fixture RULING 2(c) turns on.** That ruling applies "
            "the Correction Offset to the instant ONLY IF a held document says the receiver "
            "applies it, and §6.4 does: 'To compute the Corrected Time (TCorrected) for display or "
            "other uses, add the Correction Offset (TCorrection) to the Precision Time Stamp "
            "(TPrecision)'. What must happen: observed_at is 2008-10-24T01:37:15.591Z and "
            "attributes.precision_time_stamp_us is unchanged at 1 224 807 209 913 000. **The two "
            "together are the point**, and §6.4 gives the reason in its own words — 'The "
            "Correction Offset eliminates the need to do a post-mission change of the Precision "
            "Time Stamp value, which if changed can cause synchronization issues with the Motion "
            "Imagery frames' — so an adapter that corrected the stamp instead of the instant would "
            "break the correlation the item exists to preserve. **And this object is still not "
            "UTC**: §8.137's own bullet says 'This value DOES NOT INCLUDE leap seconds offset', "
            "there is no tag 136 here, and time_basis says the adjustment was not available"),
        citation="ST 0601.14a §6.4 Equation 1 and §8.137; ST 0601.14a §8.2.1",
    ),
    dict(
        name="a_negative_time_adjustment_is_read_signed",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (136, "FF"),                         # -1 second,  int32 per §8.136's Format cells
            (137, "FFF85EE0"),                   # -500 000 µs, int64 per §8.137's Format cells
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**THE CASE THE DOCUMENT'S OWN EXAMPLES CANNOT WITNESS, and it is a live disagreement "
            "inside one §8.x block.** §8.137 states Format `int64` / `int` with a Min of -(2^63) "
            "in its drawn table and then prints 'KLV Value To Software Value: Softval = KLVuint' "
            "one line below — while §8.136, the sibling item with the identical shape, prints "
            "'Softval = KLVint'. The printed example cannot separate the two readings: "
            "`012B8DC635` has a clear top bit. This fixture does. What must happen: tag 136 "
            "decodes to -1 and tag 137 to -500 000, and observed_at is "
            "2008-10-24T00:13:28.413Z — 1.5 s BEFORE the raw stamp. Under the `KLVuint` reading "
            "the same octets would give 255 and 4 294 467 296, putting the instant more than an "
            "hour and four minutes late and four thousand years past that on the leap term. "
            "Registered at **KLV 23** and decided on the Format cells, which is two of the "
            "block's drawn facts against one of its conversion lines"),
        citation=("ST 0601.14a §8.136 and §8.137 Format rows and conversion lines; "
                  "FORMAT_COVERAGE.md register entry KLV 23"),
    ),
    dict(
        name="a_zero_length_leap_seconds_item_is_not_a_zero_adjustment",
        octets=_payload(_packet([
            (2, _EXAMPLE[2]), (65, _EXAMPLE[65]),
            (136, ""),                           # ST 0601.14-33's explicit unknown
            (137, ""),
            (1, _EXAMPLE[1]),
        ])),
        what_it_is_for=(
            "**AN EXPLICIT UNKNOWN IS NOT A ZERO, and on a time term the difference is a wrong "
            "instant rather than a missing one.** `ST 0601.14-33` says a consumer shall interpret "
            "a zero-length item's value as 'unknown', and §6.5 makes a ZLI the producer's way of "
            "saying a value has become Unknown 'immediately'. So a producer sending a ZLI for tag "
            "136 has WITHDRAWN the leap-second count, and adding zero seconds on its behalf would "
            "assert the very number it just withdrew. What must happen: neither term is applied, "
            "observed_at is the raw stamp's instant 2008-10-24T00:13:29.913Z, time_basis says for "
            "each term that the packet carries no usable item, and both zero-length items are "
            "carried as themselves. What must NOT happen: a defect — neither tag is among the "
            "three `ST 0601.14-32` forbids a ZLI on — or a +0 recorded as an applied adjustment"),
        citation="ST 0601.14a §6.5, ST 0601.14-33 and ST 0601.14-32; §8.136, §8.137",
    ),
)


#: The park 5 fixtures are APPENDED rather than interleaved, so every fixture that existed before
#: 2026-09-04 keeps the index `enumerate` gives it and therefore the UUID-v8 identity
#: `fixtures/klv/README.md` records for it. Inserting in tag order would renumber sixteen
#: fixtures to no purpose. **The park 3 fixtures are appended after them for the same reason and
#: it now holds twice over**: park 3's round is later in the day than park 5's, so its five go
#: after park 5's nine and both the twenty-three that existed before 2026-09-04 and those nine
#: keep the indices they had. 23 + 9 + 5 = 37.
ADAPTER_FIXTURES = ADAPTER_FIXTURES + _PARK_5_FIXTURES + _PARK_3_FIXTURES


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
