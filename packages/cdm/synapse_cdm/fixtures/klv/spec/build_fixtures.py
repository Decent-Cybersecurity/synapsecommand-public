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

THE FIXTURES THAT ARE ABSENT, AND WHY THEY ARE NAMED HERE RATHER THAN MISSING
-------------------------------------------------------------------------------
The round that wrote this asked for boundary values at every encoding-width transition and for
malformed streams including a truncated length. **Three of those cannot be written from the
documents in hand and are omitted rather than guessed** — the protocol is that a fixture needing a
rule this round could not establish is named in the residue, not invented:

* **every length fixture** — short form, long form, the width transition between them, and the
  truncated-length malformation. ST 0601.14a names "BER short or long form" and defines neither: the
  one sentence that constrains a length, `ST 0601.8-07`, is marked **(Deprecated)**, and the live
  route `ST 0601.8-03` sends the rule to **MISB ST 0107.3** — park 4 — which in turn stands on
  **SMPTE ST 336:2017**, park 8. Neither is held. See `klv_codec`'s module docstring and
  `klv_pin.json`'s `framing_ruling_st_0601_14`.
* **every key/length/value triple**, for the same reason one rule up: a triple needs a length.
* **the 16383 → 16384 tag transition**, where a BER-OID value would take a third octet. §7.1 says
  "two-bytes (or more)" and the pinned copy never defines or exemplifies the "or more".

Writing any of them would mean writing the rule first, from memory, and then testing this
repository's memory against itself.

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
          "fixtures/klv/spec/ST0601.14a.pdf")


def _tag(name, octets, value, cite, note):
    return dict(kind="ber_oid_tag", name=name, octets=octets, decodes_to=value,
                citation=cite, note=note)


def _refusal(name, kind, octets, cite, note):
    return dict(kind=kind, name=name, octets=octets, decodes_to=None,
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

    _refusal("tag_third_continuation_octet", "ber_oid_refusal", "818100",
             "§7.1: 'Tag numbers greater than 127 use two-bytes (or more)'",
             "Three octets. The continuation pattern would extend, and extending it is the "
             "reconstruction this round is not permitted to make — parks 4 and 8 own the 'or "
             "more'. Refused, not decoded as 16384."),

    _refusal("tag_non_minimal_two_octets", "ber_oid_refusal", "8001",
             "ST 0601.8-06, Appendix A, marked (Deprecated)",
             "0x80 carries seven payload bits of zero, so `80 01` and `01` would denote the same "
             "tag. Refused per 'the fewest possible bytes', which the pinned copy states only in "
             "a deprecated requirement — a decision on deprecated authority, recorded as such."),

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
