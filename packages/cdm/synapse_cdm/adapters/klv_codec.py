"""The UAS Datalink Local Set framing layer, complete: key, tag, length and the walk.

WHAT THIS MODULE IS, AND WHY IT NO LONGER REFUSES
--------------------------------------------------
A KLV stream is a sequence of key/length/value triplets, and reading one needs three rules: how a
key is written, how a tag is written, and how a length is written. Two rounds got them.

The first went to `fixtures/klv/spec/ST0601.14a.pdf` — SHA-256 `3d5f1ca1…ab212ce4`, the edition
MISP-2019.1's Appendix B ref [53] names — and asked for all three. **It answered two and delegated
the third.** `decode_ber_length`, `encode_ber_length` and `walk_local_set` shipped as refusals
naming the park that owned the rule, because a codec that refuses where its standard delegates is
worth more than one that guesses and works on the fixtures somebody wrote from the same guess.

The second followed the delegation. `ST 0601.8-03` — the live route, "All UAS Datalink LS metadata
shall be expressed in accordance with MISB ST 0107 [5]" — points at **MISB ST 0107.3, KLV Metadata
in Motion Imagery**, six pages, and that document is now held: `fixtures/klv/spec/ST0107.3.pdf`,
SHA-256 `500d6752…98b69794`. **It states the length grammar on its own account, and park 4 is
closed.** So the three refusals are gone and this module reads a local set end to end.

WHERE THE LENGTH RULE CAME FROM, STATED PRECISELY BECAUSE "BER IS OBVIOUS" IS THE TRAP
---------------------------------------------------------------------------------------
Everybody who has met KLV can recite the rule: a length below 128 is one octet, otherwise the first
octet is `0x80 | n` and `n` octets follow. **That recitation is correct, and this module is not
allowed to have supplied it from memory** — the whole point of the two-round shape is that the rule
below is transcribed from ST 0107.3 §6.3.2's own worked octets, and would have been transcribed the
same way had the document said something else. The derivation is set out at the `§6.3.2` banner
further down, example by example.

What ST 0601.14a contained, and why it was not enough, is kept here rather than deleted:

* §6.3.2, of the packs: "Lengths in BER short or long form precede each item's value" — the two
  forms **named** and neither **defined**.
* Figure 1's own labels for the packet: "Length of Value … BER Encoded … Variable Length", and
  "BER encoded Length's".
* `ST 0601.8-07`, the one sentence in that document stating a constraint on lengths — "All instances
  of item length fields within a UAS Datalink LS packet shall be BER Short form or BER Long form
  encoded using the fewest possible bytes in accordance with SMPTE ST 336 [2]" — and it is
  **(Deprecated)**, on PDF page 218, in Appendix A.
* 141 worked examples, whose length octets are exactly `01`–`09`, `0B`, `0E`, `13`, `14` and `24`.
  **Not one exceeds `0x24`**, so no example in 218 pages exercises long form at all. A codec built
  from them would have accepted 36 and had nothing to say about 200: a lookup table, not a grammar.

ST 0107.3 is where the deprecated requirement went. Its `ST 0107.3-05` is `ST 0601.8-07` with the
onward delegation removed and the scope widened, and ST 0601.14a's revision history says so in as
many words: the content moved "as they apply to all MISB KLV based metadata (not just ST 0601)".

WHAT IS STILL DELEGATED, AND IT IS NARROW
------------------------------------------
**Park 8 — SMPTE ST 336:2017 — remains OPEN**, and it is a purchase rather than a download. ST
0107.3's delegating sentence is `ST 0107.3-03`, "All Local Set KLV metadata shall be formatted in
compliance with SMPTE ST 336 [1]", and §6.2 says what kind of delegation it is: "The MISB standards
define requirements which incur limits on the full SMPTE 336, making the MISB standards a profile of
the SMPTE standards." So ST 0107.3 **restricts** ST 336 rather than deferring to it, and the
restriction is `ST 0107.3-05`'s minimality — which is why the length codec is complete and total
even with park 8 open.

Two things ST 336 still owns, both refused as `UnderivableFromPinnedCopy` and neither reachable from
a conforming stream:

* `0x80` as a first length octet — zero following octets, which is BER's indefinite-length form. **ST
  0107.3 never mentions it.**
* any ceiling on the count of length octets. **ST 0107.3 states none**; every maximum it states
  (§6.3.3, `ST 0107.3-07`) governs a Value's length, not a length field's width. The structural bound
  of 127 is the first octet's seven bits and is marked as structural where it is used.

WHAT THE TWO DOCUMENTS ESTABLISH ABOUT TAGS, AND THE BOUND THAT LIFTED
-----------------------------------------------------------------------
ST 0601.14a §7.1's bullet fixes the width transition: "The tag is an integer but encoded as a BER-OID
value when used. Single-byte tags can represent tag numbers from 1 through 127. Tag numbers greater
than 127 use two-bytes (or more)." Figure 67 on PDF page 212 supplies the bit pattern the prose does
not, drawing a two-octet value as an "MSB Byte" with a leading **1** carrying "(7 bits)" and an "LSB
Byte" with a leading **0** carrying "(7 bits)"; the paragraph beneath says "After decoding the
Weapons Status BER-OID value, a **14-bit** value remains", which is why `BER_OID_MAX` is 16383. The
tag examples confirm both by exhaustion over the assigned space: §8's "Example KLV Item (All Hex)"
rows use `01`–`7F` for tags 1–127 and `8100`–`810D` for tags 128–141.

**The "(or more)" is now defined, and that is ST 0107.3's doing too.** §6.3.1 gives the chain rule
for any width — "This pattern continues until the msb of a final byte in the chain is zero" — and
"Together the seven Least Signification Bits (lsb) of each byte in the chain form the tag number."
So `decode_ber_oid` follows the chain instead of refusing a third octet, and `BER_OID_MAX` is kept as
a named waypoint rather than a limit: it is what the delegating document could prove alone.

§6.3.1 also promotes the minimality refusal. `decode_ber_oid` refuses a leading `0x80`, and until
park 4 closed the only authority for that was `ST 0601.8-06` — "All instances of item Tags within a
UAS Datalink LS packet shall be BER-OID encoded using the fewest possible bytes in accordance with
SMPTE ST 336" — marked **(Deprecated)**, so the refusal was recorded as this module's decision on
deprecated authority. ST 0107.3 §6.3.1 states it directly: "To prevent BER-OID from including
leading zeros, ASN.1 forbids the use of 0x80 in the first byte of a BER-OID value." The behaviour did
not change; its provenance did, and `klv_pin.json` records the promotion rather than dropping the
caveat.

KLV-WIDE INVARIANTS ST 0107.3 ADDS, WHICH ARE NOT ABOUT LENGTHS AT ALL
-----------------------------------------------------------------------
ST 0107.3 is the retroactive baseline — §1: "It applies retroactively to all documents approved by
the Motion Imagery Standards Board (MISB)" — so two of its requirements bear on this module directly
and the rest bear on layers above it.

* `ST 0107.2-01` "Bit order shall be big-endian or msb" and `ST 0107.2-02` "Byte order shall be
  big-endian or MSB", §6.1. **These carry the 0107.2 prefix in edition 1.3**, because MISB stamps a
  requirement with the edition that introduced it; the revision history says this edition "Added
  requirements -03 through -13". Citing them as "ST 0107.3-01" would be citing a string the document
  does not contain. `decode_ber_length` reads its long-form payload big-endian on `ST 0107.2-02`.
* `ST 0107.3-04`, "Applications which decode MISB KLV Local Sets shall skip unknown Local Set values
  so as to not impact the decoding of known Local Set items within the same Local Set instance."
  `walk_local_set` satisfies it structurally: it knows no tags at all, so every item is equally
  unknown and the caller decides what it recognises.

The other seven requirements are Value-encoding rules — IEEE 754 for `float`, ST 1201 for `IMAPA`
and `IMAPB`, leading-zero removal for variable `int`/`uint`, and two on `utf8` strings — and this
module decodes no values. They are transcribed in `klv_pin.json` because ST 0107.3 is retroactive
and the round that writes a value decoder needs them, not because anything here uses them.

NO TAG SEMANTICS, NO CLOCK, NO ADAPTER
----------------------------------------
Nothing here knows what tag 2 means. `walk_local_set` yields tags and opaque octets; the 141-row tag
table lives in `klv_pin.json` and nothing in this file consults it. There is still no `Adapter`
subclass, so no registry entry, no ordinal and no roster row — reading a local set is not translating
one, and the parks that own the translation (3 for the epoch, 5 for the IMAPB ranges) are open. There
is therefore still no injected clock seam: in this package the clock is `Adapter.__init__`'s
parameter, codecs never take one — `gmtif_codec` and `cat048_codec` are the precedent — and the seam
is built when there is an adapter to build it on.
"""
from __future__ import annotations

from typing import NamedTuple

# --------------------------------------------------------------- §6.2, the Universal Label
#
# ST 0601.14a §6.2, "UAS Local Set Universal Label", verbatim: "The UAS Local Set 16-Byte UL
# 'Key' is registered in MISB ST 0807 [3] as: 06.0E.2B.34.02.0B.01.01.0E.01.03.01.01.00.00.00
# (CRC 56773)". The deprecated `ST 0601.8-18` on PDF page 217 states the same sixteen octets in
# the same order, spaced into four groups — "06 0E 2B 34 - 02 0B 01 01 - 0E 01 03 01 - 01 00 00
# 00 (CRC 56773)" — which is the document agreeing with itself and is why this constant is not
# taken from one printing.
#
# The CRC is carried because the document prints it beside every key it states, and it is the
# only check on a transcription of sixteen otherwise meaningless octets that does not consist of
# reading them again. It is NOT verified here: the document never states the polynomial, so
# recomputing it would need a rule from a register this repository does not hold, and a "check"
# that has to invent its own algorithm checks the invention.
UAS_LOCAL_SET_KEY = bytes((
    0x06, 0x0E, 0x2B, 0x34, 0x02, 0x0B, 0x01, 0x01,
    0x0E, 0x01, 0x03, 0x01, 0x01, 0x00, 0x00, 0x00,
))
UAS_LOCAL_SET_KEY_CRC = 56773
KEY_LENGTH = 16

#: The largest BER-OID value **ST 0601.14a alone** establishes an encoding for: two octets of seven
#: payload bits each, which Figure 67 draws and its paragraph states as "a 14-bit value". Kept as a
#: named waypoint and NOT as a codec limit — MISB ST 0107.3 §6.3.1 states the general chain rule for
#: any width, so the codec is no longer bounded here. This is what the delegating document could
#: prove on its own account, and the fixtures still exercise the boundary.
BER_OID_MAX = (1 << 14) - 1

#: The BER-OID width transition, and both held documents draw it in the same place. ST 0601.14a
#: §7.1: "Single-byte tags can represent tag numbers from 1 through 127. Tag numbers greater than 127
#: use two-bytes (or more)." MISB ST 0107.3 §6.3.1: "when the msb is set to zero in the first byte,
#: this forms a one-byte tag number ranging from 0x00 to 0x7F."
BER_OID_SINGLE_OCTET_MAX = 127


class KLVFramingError(ValueError):
    """A byte pattern this module refuses to interpret. Every message quotes the offset.

    The same contract `gmtif_codec.CodecError` keeps, for the same reason: a refusal that does not
    say WHERE leaves the caller to find the octet by bisection.
    """


class UnderivableFromPinnedCopy(NotImplementedError):
    """The rule needed here is not in the documents this repository holds.

    Distinct from `KLVFramingError` on purpose, and the distinction is the whole point of this
    module: a `KLVFramingError` says *these bytes are wrong*, and this says *nobody here knows
    whether they are wrong*. Conflating the two would report a park as a malformed stream.

    Every instance names the park that owns the rule and the exact sentence in ST 0601.14a that
    delegates it, so the message is a reopen condition rather than a complaint.
    """


# ------------------------------------------------------------------------------ the key


def is_local_set_key(buf: bytes, offset: int = 0) -> bool:
    """Do the sixteen octets at `offset` open a UAS Datalink Local Set packet?

    A predicate and not a parse: it answers False for a short buffer rather than raising, because
    "there are not sixteen octets left" is a legitimate answer to *is this a key* and an
    illegitimate one to *read the key*. `read_local_set_key` is the raising half.
    """
    return buf[offset:offset + KEY_LENGTH] == UAS_LOCAL_SET_KEY


def read_local_set_key(buf: bytes, offset: int = 0) -> int:
    """Consume the 16-octet UL at `offset`; return the offset just past it.

    Returns an OFFSET rather than the key, because the key is a constant — handing back sixteen
    octets the caller already knows would invite comparing them again somewhere else.
    """
    chunk = buf[offset:offset + KEY_LENGTH]
    if len(chunk) < KEY_LENGTH:
        raise KLVFramingError(
            f"offset {offset}: a UAS Datalink LS packet opens with a {KEY_LENGTH}-octet Universal "
            f"Label (ST 0601.14a §6.2) and only {len(chunk)} octet(s) remain"
        )
    if chunk != UAS_LOCAL_SET_KEY:
        differs = next(i for i in range(KEY_LENGTH) if chunk[i] != UAS_LOCAL_SET_KEY[i])
        raise KLVFramingError(
            f"offset {offset + differs}: octet {differs} of the Universal Label is "
            f"0x{chunk[differs]:02X} and ST 0601.14a §6.2 registers "
            f"0x{UAS_LOCAL_SET_KEY[differs]:02X}. The whole key it states is "
            f"{'.'.join(f'{b:02X}' for b in UAS_LOCAL_SET_KEY)} (CRC {UAS_LOCAL_SET_KEY_CRC})"
        )
    return offset + KEY_LENGTH


# -------------------------------------------------------------------------- BER-OID tags


def decode_ber_oid(buf: bytes, offset: int = 0) -> tuple[int, int]:
    """Read one BER-OID value at `offset`; return `(value, next_offset)`.

    **Widened from two octets to the general chain when park 4 closed**, and the widening is a
    transcription rather than the extrapolation this module previously refused to make. MISB ST
    0107.3 §6.3.1 states the rule for any width, verbatim: "BER-OID tags are one or more bytes
    linked together in chain fashion. In BER-OID a zero in the Most Significant Bit (msb) position
    terminates the tag's chain. For example, when the msb is set to zero in the first byte, this
    forms a one-byte tag number ranging from 0x00 to 0x7F. When the msb of the first byte is set to
    one, the second successive byte becomes part of the BER-OID chain. In continued fashion, if the
    second byte's msb is set to one, the next byte becomes part of the chain. This pattern continues
    until the msb of a final byte in the chain is zero." And for the value: "Together the seven Least
    Signification Bits (lsb) of each byte in the chain form the tag number."

    That is the "(or more)" ST 0601.14a §7.1 named and never defined, and §6.3.1 adds the reason it
    is unbounded — "enables efficient tag encoding and unlimited future growth". So there is no
    third-octet refusal any more, and there is no ceiling: the chain runs until an octet with the
    msb clear, or until the buffer ends.

    Three refusals remain, and each names what it is refusing rather than which exception fires:

    * an empty slice — there is no value at `offset` at all;
    * a continuation bit set on the last octet available — the value runs off the end of the buffer,
      which is the "tag overrun" case and the only thing that now bounds the chain;
    * a leading `0x80` — refused on **live** authority since park 4 closed. ST 0107.3 §6.3.1's last
      sentence states it directly: "To prevent BER-OID from including leading zeros, ASN.1 forbids
      the use of 0x80 in the first byte of a BER-OID value." Until this document was held, the only
      authority for that refusal was `ST 0601.8-06`, which ST 0601.14a marks **(Deprecated)** — so
      the refusal was recorded as this module's decision on deprecated authority. It is now a
      transcribed prohibition, and `klv_pin.json` records the promotion rather than quietly
      dropping the caveat.
    """
    value = 0
    index = offset
    octet_number = 0
    while True:
        octet_number += 1
        if index >= len(buf):
            if octet_number == 1:
                raise KLVFramingError(
                    f"offset {offset}: no octets remain, so there is no BER-OID value to read"
                )
            raise KLVFramingError(
                f"offset {index}: a BER-OID value beginning at offset {offset} sets the "
                f"continuation bit on its last available octet, so it runs off the end of a "
                f"{len(buf)}-octet buffer"
            )
        octet = buf[index]
        # Seven payload bits of zero in the leading position contribute nothing, so `80 xx` and
        # `xx` would denote the same integer. MISB ST 0107.3 §6.3.1 forbids it by name.
        if octet_number == 1 and octet == 0x80:
            raise KLVFramingError(
                f"offset {offset}: 0x80 is a leading BER-OID octet carrying no value, so this "
                f"encoding includes a leading zero. MISB ST 0107.3 §6.3.1 forbids it in as many "
                f"words — 'To prevent BER-OID from including leading zeros, ASN.1 forbids the use "
                f"of 0x80 in the first byte of a BER-OID value' — which is the live successor to "
                f"ST 0601.14a's ST 0601.8-06, marked (Deprecated) there"
            )
        value = (value << 7) | (octet & 0x7F)
        index += 1
        if not octet & 0x80:
            return value, index


def encode_ber_oid(value: int) -> bytes:
    """The fewest-possible-bytes BER-OID encoding of `value`, at any width the chain rule allows.

    The exact inverse of `decode_ber_oid`, which is what makes a round trip a claim about the wire
    rather than about this module. `tests/test_cdm_klv_framing.py` asserts it by exhaustion over
    `0 … BER_OID_MAX` — the range ST 0601.14a could establish alone, which happens to fit in a test
    — and by boundary vectors above it, where the domain is unbounded and exhaustion is not
    available.

    **No upper limit.** MISB ST 0107.3 §6.3.1 gives the chain rule for "one or more bytes" and calls
    the result "unlimited future growth", so the only thing that bounds an encoding here is the
    integer handed in.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise KLVFramingError(f"a BER-OID value is an integer; got {type(value).__name__}")
    if value < 0:
        raise KLVFramingError(
            f"{value}: BER-OID encodes unsigned integers. ST 0601.14a's Table 7, Table 13 and "
            f"Table 23 all give the type as 'uint (BER-OID)', and MISB ST 0107.3 §6.3.1 describes "
            f"the chain as forming a 'tag number' with no sign"
        )
    if value <= BER_OID_SINGLE_OCTET_MAX:
        return bytes((value,))
    groups = []
    remaining = value
    while remaining:
        groups.append(remaining & 0x7F)
        remaining >>= 7
    groups.reverse()
    # Every octet but the last carries the continuation bit; the last clears it, which is §6.3.1's
    # "This pattern continues until the msb of a final byte in the chain is zero".
    return bytes([0x80 | g for g in groups[:-1]] + [groups[-1]])


# ------------------------------------------------------------- §6.6, the packet checksum


def bcc_16(buf: bytes, length: int | None = None) -> int:
    """ST 0601.14a's own `bcc_16`, transcribed rather than reimplemented.

    §6.6 and §8.1.1.1 print the algorithm as C and this is that C, loop for loop::

        unsigned short bcc_16 (
          unsigned char * buff, //Pointer to the first byte in the 16-byte UAS Datalink LS key.
          unsigned short len )  //Length from 16-byte US key up to 1-byte checksum length.
        {
          unsigned short bcc = 0, i;  // Initialize Checksum and counter variables.
          for ( i = 0 ; i < len; i++)
            bcc += buff[i] << (8 * ((i + 1) % 2));
          return bcc;
        }

    `& 0xFFFF` is the `unsigned short` the C declares; Python's integers do not wrap on their own
    and dropping it would return a growing sum that agrees with the standard only for short
    buffers. §8.1's summary bullet calls the result the "Lower 16-bits of summation".

    **This function takes the range; it cannot find it.** §6.6 says the sum runs "through the
    entire packet beginning with the 16-byte Local Set Key and ending with the length field of the
    checksum LS item", and locating that end means walking the local set, which means the length
    grammar — see `walk_local_set`. So the caller passes `length`, exactly as the C caller does,
    and this module offers nothing that computes it.

    §8.1.1.2 works an example, and it is the test vector: the eight octets
    `060E 2B34 0200 81BB` sum to `0xB4FD`, shown as `060E + 2B34 = 3142`, `+ 0200 = 3342`,
    `+ 81BB = B4FD`.
    """
    if length is None:
        length = len(buf)
    if length < 0:
        raise KLVFramingError(f"{length}: a checksum range is not negative")
    if length > len(buf):
        raise KLVFramingError(
            f"the checksum range is {length} octet(s) and the buffer holds {len(buf)}"
        )
    bcc = 0
    for i in range(length):
        bcc += buf[i] << (8 * ((i + 1) % 2))
    return bcc & 0xFFFF


# ============================================================= ST 0107.3, the length grammar
#
# THE PARK 4 ROUND, 2026-08-26. Everything from here to the end of the file was
# `raise UnderivableFromPinnedCopy` until MISB ST 0107.3 was obtained, pinned by SHA-256
# `500d6752…98b69794` at `fixtures/klv/spec/ST0107.3.pdf`, and read. The docstring section above
# that explains why the rule was absent is kept rather than deleted, because the reason it was
# absent is the reason this section can be trusted: it is transcribed from a document, not recalled.
#
# THE DELEGATION CHAIN, FOLLOWED TO WHERE IT STOPS. ST 0601.14a's live route is `ST 0601.8-03`,
# "All UAS Datalink LS metadata shall be expressed in accordance with MISB ST 0107 [5]". ST 0107.3
# is that document. Its §6.3.2, "Length Encoding", is where the chain stops moving — it names both
# forms, works three examples that fix the long form's shape between them, and states the constraint
# as a LIVE numbered requirement where ST 0601.14a had only a deprecated one:
#
#     ST 0107.3-05  All instances of item Length fields within a MISB defined KLV Universal or
#                   Local Set shall be BER Short form or BER Long form encoded using the fewest
#                   possible bytes.
#
# That sentence is `ST 0601.8-07` with "in accordance with SMPTE ST 336 [2]" removed and "UAS
# Datalink LS packet" widened to "MISB defined KLV Universal or Local Set". ST 0601.14a's revision
# history said the content moved here; this is the content, and it moved without the onward
# delegation. **So park 4 answers the length question on its own account, and the answer to "may an
# encoder choose a form freely" is NO.**
#
# THE THREE WORKED EXAMPLES, AND WHY THEY ARE A GRAMMAR AND NOT A LOOKUP TABLE. §6.3.2, verbatim:
# "BER is an efficient encoding of a length; however, by either using the long form for values less
# than 128, or by prepending a long form value with zero-byte values, BER becomes less efficient.
# For example, encoding the length of two (2), a value less than 128, with long form uses two bytes
# (0x8102) instead of the short form one-byte (0x02) length. Another example is encoding the value
# 128 with padded zeros (0x8300 0080) instead of the optimized value with two bytes (0x8180)."
#
# Read as data, those are four encodings of two lengths:
#
#     0x02        -> 2     short form, one octet, the octet IS the length
#     0x81 0x02   -> 2     long form, ONE following octet          (non-minimal: 2 < 128)
#     0x81 0x80   -> 128   long form, ONE following octet           (the "optimized value")
#     0x83 0x00 0x00 0x80 -> 128  long form, THREE following octets (non-minimal: padded)
#
# `0x81` introduces one octet and `0x83` introduces three, so the first octet's low seven bits are
# the COUNT OF OCTETS THAT FOLLOW — and the document confirms it counts that way, calling `0x8180`
# "two bytes" and `0x8102` "two bytes", first octet included. The following octets are big-endian by
# ST 0107.2-02, "Byte order shall be big-endian or MSB", §6.1. That is the whole grammar, and it is
# read off the document's own octets rather than supplied from memory — which matters, because the
# familiar recitation happens to be the same rule, and a round that could not tell the two apart
# would have learned nothing by fetching the PDF.
#
# THE TWO REFUSALS ARE THE DOCUMENT'S TWO SENTENCES. `ST 0107.3-05` says "fewest possible bytes",
# and §6.3.2 names exactly two ways to spend more than the fewest: long form for a value short form
# can carry, and leading zero octets. `decode_ber_length` refuses one apiece, and each refusal
# quotes the example the document works against it. Nothing else is refused for non-minimality,
# because nothing else is named.

#: The largest length the short form carries. §6.3.2 draws the boundary twice — "the long form for
#: values less than 128" is the inefficiency it names, and 128 is the value whose "optimized"
#: encoding it shows as two bytes (`0x8180`). So 0..127 is one octet and 128 up is long form, and
#: the 0x7F/0x80 transition in the first octet is the same fact from the encoder's side.
BER_LENGTH_SHORT_FORM_MAX = 127

#: The most octets a long-form length can declare, and it is STRUCTURAL rather than cited. The first
#: octet carries the long-form flag in bit 7 and the count in the remaining seven bits — `0x81` is
#: one, `0x83` is three — so 127 is the largest count that octet can express. **ST 0107.3 states no
#: ceiling of its own**: §6.3.2 gives no maximum, and every "maximum" in the document (§6.3.3,
#: `ST 0107.3-07`) governs a Value's length and not the count of length octets. Whether ST 336
#: imposes a lower one is park 8's, and is why exceeding this raises `UnderivableFromPinnedCopy`
#: rather than `KLVFramingError`.
BER_LENGTH_OF_LENGTH_MAX = 127

#: `0x80` as a first length octet declares zero following octets. **ST 0107.3 never mentions it.**
#: In BER it is the indefinite-length form, which is a rule from a document this repository does not
#: hold — so it is named here, refused in `decode_ber_length`, and left to park 8.
BER_LENGTH_INDEFINITE_OCTET = 0x80

_INDEFINITE_RESIDUE = (
    "0x80 as a first length octet declares zero following octets, and MISB ST 0107.3 never "
    "mentions that form. §6.3.2 defines the short form (one octet, the octet is the length) and "
    "the long form (0x80 | n, then n octets big-endian) and says nothing about n = 0; every "
    "'maximum' in the document governs a Value's length, not a count of length octets. In BER this "
    "is the indefinite-length form, and BER is SMPTE ST 336 — PARK 8, a purchase, still OPEN. The "
    "delegating sentence is ST 0107.3-03: 'All Local Set KLV metadata shall be formatted in "
    "compliance with SMPTE ST 336 [1].' Whether ST 336 permits, forbids or reserves n = 0 is "
    "underivable from the bytes in hand, so this is not reported as a malformed stream."
)

_CEILING_RESIDUE = (
    "the long form's first octet carries the count of following octets in seven bits, so it can "
    f"declare at most {BER_LENGTH_OF_LENGTH_MAX}. That bound is STRUCTURAL and not cited: MISB ST "
    "0107.3 §6.3.2 states no ceiling on the number of length octets at all, and its only stated "
    "maxima (§6.3.3, ST 0107.3-07) govern a Value's length. Any ceiling ST 336 imposes is PARK 8's "
    "— 'All Local Set KLV metadata shall be formatted in compliance with SMPTE ST 336 [1]' "
    "(ST 0107.3-03) — and park 8 is a purchase and still OPEN."
)


def decode_ber_length(buf: bytes, offset: int = 0) -> tuple[int, int]:
    """Read one BER length at `offset`; return `(length, next_offset)`.

    ST 0107.3 §6.3.2 and `ST 0107.3-05`, with the octet order from `ST 0107.2-02`. Five outcomes:

    * an empty slice — there is no length at `offset` at all;
    * `0x00`–`0x7F` — short form, and the length is the octet;
    * `0x80` — refused as `UnderivableFromPinnedCopy`. Zero following octets is BER's
      indefinite-length form and §6.3.2 does not mention it. **This is the one place the 0x7F/0x80
      transition is not symmetric**: 0x7F is a length and 0x80 is a park;
    * `0x81`–`0xFF` — long form. The low seven bits are the count of following octets, which are the
      length big-endian. Refused as `KLVFramingError` if they run off the end of the buffer, or if
      the encoding is not the fewest possible bytes;
    * a count the buffer cannot satisfy — truncation, quoting the offset.

    **Non-minimal forms are refused, and the two refusals are the two the document names.** §6.3.2
    names exactly two ways to spend more than the fewest bytes and works an example against each:
    long form for a value below 128 (`0x8102` for 2, where `0x02` would do) and leading zero octets
    (`0x8300 0080` for 128, where `0x8180` is "the optimized value"). Both are `KLVFramingError` —
    *these bytes are wrong* — because `ST 0107.3-05` is a live "shall" and this edition is the one
    ST 0601.14a's live route points at.

    What `ST 0107.3-05` does not say is what a DECODER must do about a violation; it binds the
    encoding, not the reader. Refusing is therefore this module's decision, and it is a narrower one
    than the BER-OID minimality decision above was before park 4 closed: the authority here is live
    and numbered rather than deprecated. It is recorded as a decision in `klv_pin.json`, with the
    one sentence that pulls the other way — `ST 0107.3-04`, "Applications which decode MISB KLV
    Local Sets shall skip unknown Local Set values so as to not impact the decoding of known Local
    Set items" — which is a requirement about unknown TAGS and not about malformed lengths, and
    which a decoder cannot honour at all without first reading the length correctly.
    """
    if offset < 0:
        raise KLVFramingError(f"offset {offset}: a length is not read from a negative offset")
    if offset >= len(buf):
        raise KLVFramingError(
            f"offset {offset}: no octets remain, so there is no BER length to read"
        )
    first = buf[offset]
    if first <= BER_LENGTH_SHORT_FORM_MAX:
        # §6.3.2's short form. "encoding the length of two (2) … the short form one-byte (0x02)
        # length" — the octet IS the length, with no flag to strip.
        return first, offset + 1
    if first == BER_LENGTH_INDEFINITE_OCTET:
        raise UnderivableFromPinnedCopy(f"offset {offset}: " + _INDEFINITE_RESIDUE)
    count = first & 0x7F
    payload = buf[offset + 1:offset + 1 + count]
    if len(payload) < count:
        raise KLVFramingError(
            f"offset {offset}: a long-form length octet 0x{first:02X} declares {count} following "
            f"octet(s) (MISB ST 0107.3 §6.3.2, where 0x81 introduces one and 0x83 introduces "
            f"three) and only {len(payload)} remain in a {len(buf)}-octet buffer"
        )
    # ST 0107.2-02, §6.1: "Byte order shall be big-endian or MSB."
    length = int.from_bytes(payload, "big")
    if length <= BER_LENGTH_SHORT_FORM_MAX:
        raise KLVFramingError(
            f"offset {offset}: 0x{first:02X}{payload.hex().upper()} is the long form of {length}, "
            f"which the short form carries in one octet as 0x{length:02X}. MISB ST 0107.3 §6.3.2 "
            f"works this exact inefficiency — 'encoding the length of two (2), a value less than "
            f"128, with long form uses two bytes (0x8102) instead of the short form one-byte "
            f"(0x02) length' — and ST 0107.3-05 requires 'the fewest possible bytes'"
        )
    if payload[0] == 0x00:
        raise KLVFramingError(
            f"offset {offset + 1}: the long-form length of {length} beginning at offset {offset} "
            f"is padded with a leading zero octet. MISB ST 0107.3 §6.3.2 works this exact "
            f"inefficiency — 'encoding the value 128 with padded zeros (0x8300 0080) instead of "
            f"the optimized value with two bytes (0x8180)' — and ST 0107.3-05 requires 'the fewest "
            f"possible bytes'"
        )
    return length, offset + 1 + count


def encode_ber_length(value: int) -> bytes:
    """The fewest-possible-bytes BER encoding of `value`. The exact inverse of `decode_ber_length`.

    `ST 0107.3-05` makes this function total rather than a choice: for any length there is exactly
    one conforming encoding, so there is no `form=` parameter to pass and no way to ask for the long
    form of 2. That is the whole content of the park 4 ruling in one signature.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise KLVFramingError(f"a BER length is an integer; got {type(value).__name__}")
    if value < 0:
        raise KLVFramingError(
            f"{value}: a BER length is not negative. MISB ST 0107.3 §6.3 states the range it "
            f"admits — 'Lengths are usually positive numbers; however, a zero length is possible "
            f"in unique cases'"
        )
    if value <= BER_LENGTH_SHORT_FORM_MAX:
        return bytes((value,))
    count = (value.bit_length() + 7) // 8
    if count > BER_LENGTH_OF_LENGTH_MAX:
        raise UnderivableFromPinnedCopy(
            f"{value} needs {count} octets and " + _CEILING_RESIDUE
        )
    return bytes((0x80 | count,)) + value.to_bytes(count, "big")


# ------------------------------------------------------------------- §6.3, the local-set walk


class LocalSetItem(NamedTuple):
    """One Key-Length-Value triplet inside a local set's Value, with the offsets it was read at.

    ST 0107.3 §6.3: "A Local Set item is a Key-Length-Value triplet. The 'Key' in a Local Set is
    represented as a 'Tag' … The Length defines the number of bytes used by the Value."

    The offsets are carried because `bcc_16` takes a range it cannot find: ST 0601.14a §6.6 defines
    the checksum range as running from the key "up to 1-byte checksum length", which is
    `tag_offset` of the checksum item plus its length octets — a caller holding these fields can
    compute it, and this module still does not do it for them.
    """

    tag: int
    length: int
    value: bytes
    tag_offset: int
    value_offset: int


def walk_local_set(buf: bytes, offset: int = 0):
    """Walk the packet at `offset`, yielding one `LocalSetItem` per Local Set item.

    A generator, so a caller can stop at the item it wants without decoding the rest — and so a
    malformed item raises where it is met rather than poisoning items already yielded.

    The three rules it composes are now all held: the 16-octet key from ST 0601.14a §6.2, the
    BER-OID tag from ST 0107.3 §6.3.1, and the BER length from ST 0107.3 §6.3.2. ST 0601.14a §6.3
    gives the packet shape — "A packet is a combination of a UL Key, the Length of the Value, and
    the Value. UAS Datalink LS items are encapsulated within the Value portion of the packet" — so
    the walk reads a key, reads the length of the value, and then reads triplets until the value is
    exhausted.

    **Values are opaque octets and no tag is looked up.** `ST 0107.3-04` — "Applications which
    decode MISB KLV Local Sets shall skip unknown Local Set values so as to not impact the decoding
    of known Local Set items within the same Local Set instance" — is satisfied structurally rather
    than by a skip list: this walk knows no tags at all, so every item is equally unknown to it and
    the caller decides which ones it recognises. The tag table is 141 rows in `klv_pin.json` and
    nothing here consults it.

    Two refusals are the walk's own, and neither is a length or a tag error:

    * a declared Value length that runs past the end of the buffer — the packet is truncated;
    * an item whose Value would run past the end of the declared Value — the item overruns its
      packet, which is a different fault from a truncated buffer and is reported as one.
    """
    cursor = read_local_set_key(buf, offset)
    declared, cursor = decode_ber_length(buf, cursor)
    end = cursor + declared
    if end > len(buf):
        raise KLVFramingError(
            f"offset {cursor}: the packet declares a {declared}-octet Value (ST 0601.14a §6.3, "
            f"'A packet is a combination of a UL Key, the Length of the Value, and the Value') and "
            f"only {len(buf) - cursor} octet(s) remain in a {len(buf)}-octet buffer"
        )
    while cursor < end:
        tag_offset = cursor
        tag, cursor = decode_ber_oid(buf, cursor)
        length, cursor = decode_ber_length(buf, cursor)
        if cursor + length > end:
            raise KLVFramingError(
                f"offset {cursor}: the item with tag {tag} at offset {tag_offset} declares a "
                f"{length}-octet Value, which runs {cursor + length - end} octet(s) past the end "
                f"of the packet's own declared Value at offset {end}. The buffer is long enough "
                f"and the packet is not — MISB ST 0107.3 §6.3's 'block of data' is overrun from "
                f"inside"
            )
        yield LocalSetItem(tag, length, buf[cursor:cursor + length], tag_offset, cursor)
        cursor += length
