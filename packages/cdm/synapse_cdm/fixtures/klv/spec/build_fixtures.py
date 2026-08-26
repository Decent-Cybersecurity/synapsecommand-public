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

**One fixture is still a park, and it is the only one.** `length_indefinite_first_octet` — the octet
`0x80`, declaring zero following octets — raises `UnderivableFromPinnedCopy`, because ST 0107.3 never
mentions that form and BER's indefinite length is **SMPTE ST 336:2017**, park 8, a purchase. The
generator asserts the exception TYPE for it, so a later round that decides what `0x80` means without
buying the document fails here.

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

#: UUID-v8, `f1c7` namespace, with the document this round read written into the second and third
#: groups. Version nibble `8` and RFC 9562 variant bits, so nothing issuing v4 or v7 can collide.
FIXTURE_ID = "f1c70601-14a0-8000-8000-{:012d}"

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

    _refusal("length_indefinite_first_octet", "ber_length_park", "80",
             "MISB ST 0107.3 §6.3.2, by SILENCE; delegated by ST 0107.3-03",
             "0x80 declares ZERO following octets, and ST 0107.3 never mentions that form. In BER "
             "it is the indefinite-length form, and BER is SMPTE ST 336 — PARK 8, a purchase, "
             "still OPEN. THE ONE FIXTURE IN THIS SET THAT IS STILL A PARK, and it raises "
             "UnderivableFromPinnedCopy rather than KLVFramingError because nobody here knows "
             "whether these bytes are wrong. The 0x7F/0x80 transition is asymmetric for exactly "
             "this reason: 0x7F is a length and 0x80 is a blocker."),

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
            try:
                codec.decode_ber_length(octets)
            except codec.KLVFramingError:
                pass
            else:
                raise AssertionError(
                    f"{name}: {spec['octets']} was accepted and ST 0107.3-05 refuses it"
                )
        elif spec["kind"] == "ber_length_park":
            # A PARK AND NOT A MALFORMATION, and the assertion is on which exception fires. If this
            # ever raises KLVFramingError instead, somebody has decided what 0x80 means without
            # buying ST 336, and the fixture is the thing that says so.
            try:
                codec.decode_ber_length(octets)
            except codec.UnderivableFromPinnedCopy:
                pass
            except codec.KLVFramingError as exc:                  # pragma: no cover - regression
                raise AssertionError(
                    f"{name}: {spec['octets']} was refused as a malformed stream "
                    f"({exc}). MISB ST 0107.3 is silent on this form, so it is park 8's and must "
                    f"raise UnderivableFromPinnedCopy"
                ) from exc
            else:
                raise AssertionError(
                    f"{name}: {spec['octets']} was DECODED. ST 0107.3 never mentions a zero "
                    f"length-of-length, so a value here is a reconstruction"
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


if __name__ == "__main__":
    paths = build()
    for path in paths:
        print(path.relative_to(FIXTURES.parent.parent.parent))
    print(f"{len(FIXTURES_SPEC)} framing fixtures, {len(paths)} files")
