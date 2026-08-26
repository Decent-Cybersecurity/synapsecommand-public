"""The UAS Datalink Local Set framing layer, as far as the pinned copy of ST 0601.14 establishes it.

WHAT THIS MODULE IS, AND WHY HALF OF IT REFUSES
------------------------------------------------
A KLV stream is a sequence of key/length/value triplets, and reading one needs three rules: how a
key is written, how a tag is written, and how a length is written. This round went to
`fixtures/klv/spec/ST0601.14a.pdf` — the copy pinned by SHA-256
`3d5f1ca1…ab212ce4`, the edition MISP-2019.1's Appendix B ref [53] names — and asked it for all
three. **It answers two of them and delegates the third**, and this module is that answer with the
delegation left visibly unfilled rather than reconstructed.

So `decode_ber_oid` parses and `encode_ber_oid` emits, `UAS_LOCAL_SET_KEY` is the 16 octets §6.2
prints, `bcc_16` is the checksum algorithm §6.6 gives as C and §8.1.1.2 works an example of — and
`decode_ber_length`, `encode_ber_length` and `walk_local_set` raise `UnderivableFromPinnedCopy`
naming the park that owns the rule. **A codec that refuses where its standard delegates is worth
more than one that guesses and works on the fixtures somebody wrote from the same guess.**

WHY THE LENGTH RULE IS NOT HERE, STATED PRECISELY BECAUSE "BER IS OBVIOUS" IS THE TRAP
--------------------------------------------------------------------------------------
Everybody who has met KLV can recite the rule: a length below 128 is one octet, otherwise the first
octet is `0x80 | n` and `n` octets follow. That recitation is not in the pinned copy, and this
module is not allowed to supply it from memory. What ST 0601.14a actually contains is:

* §6.3.2, of the packs: "Lengths in BER short or long form precede each item's value" — the two
  forms **named** and neither **defined**.
* Figure 1's own labels for the packet: "Length of Value … BER Encoded … Variable Length", and
  "BER encoded Length's".
* `ST 0601.8-07`, which is the one sentence in the document that states a constraint on lengths —
  "All instances of item length fields within a UAS Datalink LS packet shall be BER Short form or
  BER Long form encoded using the fewest possible bytes in accordance with SMPTE ST 336 [2]" — and
  it is **(Deprecated)**, on PDF page 218, in Appendix A. The live route is `ST 0601.8-03`, "All
  UAS Datalink LS metadata shall be expressed in accordance with MISB ST 0107 [5]".
* 141 worked examples, whose length octets are exactly `01`–`09`, `0B`, `0E`, `13`, `14` and `24`.
  **Not one of them exceeds `0x24`**, so no example in the document exercises long form at all, and
  none of them reaches even the 127 that a short form is usually said to stop at.

Two documents own the missing rule and this repository holds neither: **SMPTE ST 336:2017** (park
8, a purchase and not a download) and **MISB ST 0107.3** (park 4). ST 0601.14a's own reference list
pins both at exactly the versions the profile does — `[2] SMPTE ST 336:2017` and `[5] MISB ST
0107.3` — which corroborates the parks and closes neither.

WHAT THE DOCUMENT DOES ESTABLISH ABOUT TAGS, AND WHERE THAT STOPS
------------------------------------------------------------------
§7.1's bullet is the statement: "The tag is an integer but encoded as a BER-OID value when used.
Single-byte tags can represent tag numbers from 1 through 127. Tag numbers greater than 127 use
two-bytes (or more)." That fixes the width transition exactly, at 127/128.

Figure 67 on PDF page 212 supplies the bit pattern the prose does not: it draws a two-octet BER-OID
value as an "MSB Byte" whose leading bit is **1** carrying "(7 bits)", followed by an "LSB Byte"
whose leading bit is **0** carrying "(7 bits)", with both octets' payload bits labelled 6 down to 0.
The paragraph beneath it says "After decoding the Weapons Status BER-OID value, a **14-bit** value
remains", which is the same fact from the other side and is why `BER_OID_MAX` below is 16383 and
not something remembered.

And the tag examples confirm both, by exhaustion over the local set's whole assigned space: the
"Example KLV Item (All Hex)" rows across §8 use `01`–`7F` for tags 1–127 and `8100`–`810D` for tags
128–141. `0x8100` is 128 and `0x810D` is 141 under exactly the pattern Figure 67 draws.

**Three octets and beyond are NOT established, and this module refuses them.** §7.1 says "(or
more)" and §8.128's details say "the BER-OID format is self-describing providing the rules for
obtaining the number of bytes for the value" — but the pinned copy neither states the general rule
nor works an example above two octets, and ST 0601's own tag space stops at 142. Extending the
continuation pattern to a third octet is arithmetic anybody can do; it is also exactly the
reconstruction-from-memory this module exists to not do. A third octet is a refusal quoting the
offset and naming the residue, and the day park 4 or park 8 closes it becomes three lines.

THE MINIMALITY RULE IS ENFORCED, AND ITS PROVENANCE IS DEPRECATED TEXT
-----------------------------------------------------------------------
`decode_ber_oid` refuses `80 xx` — the one non-minimal two-octet form — and the honest reason is
worth the paragraph. The only sentence in the pinned copy that requires minimal encoding is
`ST 0601.8-06`, "All instances of item Tags within a UAS Datalink LS packet shall be BER-OID
encoded using the fewest possible bytes in accordance with SMPTE ST 336", and it is **(Deprecated)**
— the revision history says its content moved to ST 0107.3, "as they apply to all MISB KLV based
metadata (not just ST 0601)". So the requirement is real, it is in this document, and this document
no longer asserts it on its own account.

Refusing is a **decision**, not a derivation, and it is named as one here and in the pin. It runs in
the same direction as every one of the 141 examples, and the alternative — accepting `80 01` as tag
1 — would make two byte strings mean one tag, which is the property that makes a round trip a
statement about the wire instead of about this module. Whether refusal is *normatively required* is
underivable from the bytes in hand and is recorded as residue.

NO TAG SEMANTICS, NO CLOCK, NO ADAPTER
----------------------------------------
Nothing here knows what tag 2 means. There is no `Adapter` subclass, so there is no injected clock
seam either: in this package the clock is `Adapter.__init__`'s parameter, codecs never take one —
`gmtif_codec` and `cat048_codec` are the precedent — and creating an `Adapter` to hold a seam would
claim an ordinal and a roster row for something that cannot read a local set yet. The seam is named
here and built when there is an adapter to build it on.
"""
from __future__ import annotations

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

#: The largest BER-OID value the pinned copy establishes an encoding for: two octets of seven
#: payload bits each, which Figure 67 draws and its paragraph states as "a 14-bit value".
BER_OID_MAX = (1 << 14) - 1

#: The widest BER-OID encoding the pinned copy establishes. §7.1 says tags above 127 use "two-bytes
#: (or more)" and the document never shows or defines the "or more".
BER_OID_MAX_OCTETS = 2

#: The tag-width transition §7.1 states: 1 through 127 in one octet, 128 and up in two.
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

    Established from the pinned copy for one and two octets, and refusing beyond that — see the
    module docstring for which sentence and which figure carries each half.

    Four refusals, and each one names what it is refusing rather than which exception fires:

    * an empty slice — there is no value at `offset` at all;
    * a continuation bit set on the last octet available — the value runs off the end of the
      buffer, which is the "tag overrun" case;
    * a continuation bit still set after two octets — a three-octet form, which §7.1 says exists
      ("or more") and neither states nor exemplifies;
    * a leading `0x80` — the one non-minimal two-octet form, refused per the deprecated
      `ST 0601.8-06`, a decision the module docstring names as a decision.
    """
    value = 0
    index = offset
    for octet_number in range(1, BER_OID_MAX_OCTETS + 1):
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
        # The one non-minimal two-octet form: seven payload bits of zero in the leading position
        # contribute nothing, so `80 xx` and `xx` denote the same integer.
        if octet_number == 1 and octet == 0x80:
            raise KLVFramingError(
                f"offset {offset}: 0x80 is a leading BER-OID octet carrying no value, so this "
                f"encoding is not the fewest possible bytes. ST 0601.14a states that requirement "
                f"as ST 0601.8-06, in Appendix A and marked (Deprecated) — refusing is this "
                f"module's decision on deprecated authority, recorded as such in klv_pin.json"
            )
        value = (value << 7) | (octet & 0x7F)
        index += 1
        if not octet & 0x80:
            return value, index
    raise KLVFramingError(
        f"offset {index}: a BER-OID value beginning at offset {offset} sets the continuation bit "
        f"on its {BER_OID_MAX_OCTETS}nd octet, so it needs at least three. ST 0601.14a §7.1 says "
        f"tags above {BER_OID_SINGLE_OCTET_MAX} 'use two-bytes (or more)' and the pinned copy "
        f"neither defines nor exemplifies the 'or more' — park 4 (MISB ST 0107.3) and park 8 "
        f"(SMPTE ST 336:2017) own it"
    )


def encode_ber_oid(value: int) -> bytes:
    """The fewest-possible-bytes BER-OID encoding of `value`, in the established width range.

    The exact inverse of `decode_ber_oid` over `0 … BER_OID_MAX`, which is what makes a round trip
    a claim about the wire: `decode_ber_oid(encode_ber_oid(n))[0] == n` for every one of the 16 384
    values, and `tests/test_cdm_klv_framing.py` asserts it by exhaustion rather than by sampling
    because the whole range fits in a test.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise KLVFramingError(f"a BER-OID value is an integer; got {type(value).__name__}")
    if value < 0:
        raise KLVFramingError(
            f"{value}: BER-OID encodes unsigned integers. ST 0601.14a's Table 7, Table 13 and "
            f"Table 23 all give the type as 'uint (BER-OID)'"
        )
    if value > BER_OID_MAX:
        raise KLVFramingError(
            f"{value}: the pinned copy establishes BER-OID for at most {BER_OID_MAX_OCTETS} "
            f"octets, which Figure 67 draws as two 7-bit payloads and its paragraph states as 'a "
            f"14-bit value' — so {BER_OID_MAX} is the largest value this module will emit. A "
            f"third octet needs park 4 or park 8"
        )
    if value <= BER_OID_SINGLE_OCTET_MAX:
        return bytes((value,))
    return bytes((0x80 | (value >> 7), value & 0x7F))


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


# ----------------------------------------------------- the half the pinned copy delegates
#
# These three exist, are importable, and raise. That is deliberate and is the shape of the round's
# finding: a reader who reaches for a length decoder gets the park number and the sentence that
# delegates it, where a missing name would get an AttributeError and a guess.

_LENGTH_RESIDUE = (
    "ST 0601.14a names BER short form and BER long form (§6.3.2, Figure 1) and defines neither. "
    "The only sentence stating a constraint on lengths is ST 0601.8-07 — 'All instances of item "
    "length fields within a UAS Datalink LS packet shall be BER Short form or BER Long form "
    "encoded using the fewest possible bytes in accordance with SMPTE ST 336 [2]' — and it is "
    "(Deprecated), PDF page 218. The live route is ST 0601.8-03, 'All UAS Datalink LS metadata "
    "shall be expressed in accordance with MISB ST 0107 [5]'. The 141 worked examples use length "
    "octets 01-09, 0B, 0E, 13, 14 and 24 and never exceed 0x24, so not one of them exercises long "
    "form. PARK 4 (MISB ST 0107.3) and PARK 8 (SMPTE ST 336:2017) own the rule and neither "
    "document is held."
)


def decode_ber_length(buf: bytes, offset: int = 0) -> tuple[int, int]:
    """Not derivable from the documents in hand. Raises, and says which park owns the rule."""
    raise UnderivableFromPinnedCopy(_LENGTH_RESIDUE)


def encode_ber_length(value: int) -> bytes:
    """Not derivable from the documents in hand. Raises, and says which park owns the rule.

    Emitting is refused on the same footing as parsing, and the symmetry is the point: a module
    that could emit a length it cannot parse would let a fixture be written from a rule this round
    ruled unavailable, which is the exact failure the fixture protocol exists to prevent.
    """
    raise UnderivableFromPinnedCopy(_LENGTH_RESIDUE)


def walk_local_set(buf: bytes, offset: int = 0):
    """Not derivable from the documents in hand. Raises, and says which park owns the rule.

    The triple-walk is what a framing layer is FOR, and it is one rule away. Everything else it
    needs is in this module: the key at §6.2, the tag codec at §7.1 and Figure 67, and — once the
    walk exists — the checksum range §6.6 defines in terms of it. What is missing is how to read
    the length between the tag and the value.
    """
    raise UnderivableFromPinnedCopy(
        _LENGTH_RESIDUE + " Every other rule a local-set walk needs is implemented in this module."
    )
