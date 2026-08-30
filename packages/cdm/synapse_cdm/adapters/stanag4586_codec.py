"""STANAG 4586 Edition 3 — the DLI wire format. Decode only, and deliberately so.

Every constant, width, scale and enumeration in this module is read from the pinned copy of
STANAG 4586 Edition 3, `fixtures/stanag4586/spec/STANAG_4586_Ed3.pdf`, SHA-256 `a4fa6e54…c15da`,
509 pages, and each carries the section it came from. `fixtures/stanag4586/spec/stanag4586_pin.json`
is the record; this module is that record made executable, and where the two could disagree the
pin is the claim and `tests/test_cdm_stanag4586_codec.py` is what stops them parting.

THE EDITION IS NOT THE CURRENT ONE AND THAT IS A RULING, NOT AN OVERSIGHT
-------------------------------------------------------------------------
Edition 4 (2017-04-05, promulgated as AEP-84 Edition A) is current. It could not be acquired:
`nso.nato.int` answers HTTP 403 on every route, the Internet Archive holds no capture of any
STANAG 4586 PDF at any URL, and the commercial distributors that carry Edition 4 serve it behind a
paywall and a DRM wrapper — which is SMPTE ST 336's situation, the one park in this repository
whose reason is procurement rather than procedure. Edition 3 is what is obtainable and it is what
is pinned. **No sentence in this repository claims an Edition 3 decoder reads an Edition 4 feed**,
and Edition 4 is documented to have changed the vehicle identifier list and added mission-phase and
autonomy messages — changes that land on exactly the tables a telemetry row set tabulates. See
`edition_ruling` in the pin.

WHY THIS MODULE ONLY DECODES
----------------------------
The adapter is *STANAG 4586 telemetry ingest*, not *STANAG 4586 support*. It reads status messages
travelling from the air vehicle to the control station and emits CDM. It does not build DLI, and
this module therefore has no encoder: the synthetic frames the fixtures replay are built by
`fixtures/stanag4586/spec/build_fixtures.py`, which is a generator and not shipped surface.

That is not fastidiousness about a function's location. Emitting DLI is how software starts being a
UCS component — a CUCS or a VSM — and every command message in this format is an instruction to an
actuator: flight mode, waypoint upload, payload steering, link handover. The CDM has no object kind
for an instruction (entity, event, track, plan_object — none of them is a command), so there is
nothing for a command message to translate INTO, and inventing one is the deferred `ONTOLOGY.md`
decision rather than a side effect of an adapter.

THE WRAPPER, §3.3.1 AND FIGURE B1-7
------------------------------------
Sequence # (2) · Message Length (2) · Source ID (4) · Destination ID (4) · Message Type (2) ·
Message Properties (2) = **16 octets**, then Message Data, then an optional checksum of 0, 2 or 4
octets. §3.3.1.6 says "[s]ubtracting the message wrapper size of 20 bytes", and 16 + the largest
checksum is that 20 — the document's number and this one measure different things and both are
right, which is why the derivation is written down rather than the total copied.

Byte order is most significant first, §1.7.1, everywhere and without exception.

THE CHECKSUM LENGTH IS DERIVED FROM THE FRAME, NOT READ FROM THE FLAG
---------------------------------------------------------------------
§3.3.1.10 puts four subfields in Message Properties: the ACK bit at 15, the IDD version at 14:8,
a two-bit Checksum Length and a Reserved span. **Where the two-bit field sits inside bits 7:0 is not
recoverable from this copy's text layer** — Figure B1-8's bit-number row extracts as the scrambled
sequence `1 2 045 3 67910 812 13 11`, every label present and their order a property of the PDF's
text placement rather than of the figure. Ambiguity 1 in the pin.

So the trailing length is computed — `total - 16 - message_length`, which the format constrains to
exactly 0, 2 or 4 — and the subfield is read at bits 7:6 as a *second* statement of the same fact.
When they disagree the frame still decodes and the disagreement is recorded as a defect. A guess
would have been cheaper and would have made a decoder whose correctness nobody could check.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import math
from typing import Any, Iterator, Literal

#: §3.3.1, Figure B1-7. The six fixed header fields, in order, before the message data.
WRAPPER_OCTETS = 16

#: §3.3.1.5 — the field "is not used and shall contain '-1'". The section that introduces it also
#: declares every header entry a 16-bit *unsigned* integer, so -1 is only expressible as its
#: two's-complement pattern. Ambiguity 2 in the pin: the document never spells `0xFFFF`.
SEQUENCE_NOT_USED = 0xFFFF

#: Table B1-3, "IDD Version Identification": STANAG 4586 Edition 3 is version 30.
IDD_VERSION_EDITION_3 = 30

#: Table B1-4, "Checksum Length": 00 none, 01 two octets, 10 four octets. 11 is unassigned.
CHECKSUM_OCTETS_BY_CODE: dict[int, int] = {0b00: 0, 0b01: 2, 0b10: 4}

#: §3.3.1.6 — "The length shall be any number between 1 and 528."
MESSAGE_LENGTH_MIN = 1
MESSAGE_LENGTH_MAX = 528

#: §1.7.6 — "Two-hundred and fifty five (255 (hexadecimal FF)) shall be reserved" as an Owning ID,
#: which is the most significant octet of every 4-byte ID.
OWNING_ID_RESERVED = 0xFF

#: §1.7.2 — "All times shall be represented in Universal Time Coordinated (UTC) in seconds since
#: Jan 1, 2000 using a 5 byte unsigned integer where the least significant bit represents 0.001
#: seconds."
EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
TIME_STAMP_OCTETS = 5
TIME_STAMP_LSB_SECONDS = 0.001


class Stanag4586DecodeError(ValueError):
    """A frame this module refuses. Never raised for an *unknown message type*."""


def decode_unsigned(octets: bytes) -> int:
    """§4.1.2 Unsigned(n), n in 1..5, most significant octet first (§1.7.1)."""
    return int.from_bytes(octets, "big", signed=False)


def decode_integer(octets: bytes) -> int:
    """§4.1.2 Integer(n) — "signed integers, where n is 1, 2, 3, 4 or 5 bytes".

    Three- and five-octet signed integers are ordinary in this format — Altitude is `Integer 3`
    and every Time Stamp is `Unsigned 5` — and neither width has a `struct` format character. A
    codec built around `struct`'s widths could not express half of this document, so the sign
    extension is done here explicitly.
    """
    return int.from_bytes(octets, "big", signed=True)


def bam_to_radians(raw: int, octets: int) -> float:
    """§1.7.3 — "The fixed point scaling for BAM is … pi / 2^(n-1) radians, where n is the
    bit-width of the field".

    For an `Integer` field that gives a real range of -pi inclusive to pi exclusive, which is the
    document's own statement of it and is how the formula was read: the pi renders as a mojibake
    glyph in every text extraction of this copy, so the constant is taken from the stated RANGE
    rather than from the character.
    """
    bits = octets * 8
    return raw * (math.pi / (2 ** (bits - 1)))


def timestamp_to_utc(raw: int) -> dt.datetime:
    """§1.7.2's 5-octet millisecond count since 2000-01-01, as a UTC instant.

    THE ROLLOVER IS THE DOCUMENT'S OWN AND IT CHECKS OUT ARITHMETICALLY, which is worth one line
    because it is a free test of the reading: 2**40 - 1 milliseconds is 1 099 511 627 775 ms, and
    2000-01-01 plus that is in 2034 — exactly where §1.7.2 says "In 2034 and in subsequent years,
    when the maximum value of the five byte field is exceeded, the timestamp shall 'roll over'".
    A different epoch or a different LSB would not land on 2034.

    What this conversion does NOT settle is whether the count includes leap seconds. §1.7.2 calls
    it UTC and says nothing further, and a count of milliseconds since an epoch either steps at a
    leap second or does not. The adapter carries that on every object rather than resolving it.
    """
    return EPOCH + dt.timedelta(milliseconds=raw)


Kind = Literal["unsigned", "integer", "bam", "timestamp"]


@dataclasses.dataclass(frozen=True)
class FieldSpec:
    """One row of a message's field table, as the document prints it."""

    index: int
    unique_id: str
    name: str
    kind: Kind
    octets: int
    #: The "Units" cell's multiplier where it is a plain LSB, else None (BAM, enumerated, raw).
    scale: float | None = None
    #: The "Units" cell verbatim, so a reader never has to trust this module's paraphrase.
    units: str = ""
    #: Set for the fields whose Units cell reads "Enumerated", with the document's own value map.
    enumeration: dict[int, str] | None = None

    @property
    def is_enumerated(self) -> bool:
        return self.enumeration is not None


@dataclasses.dataclass(frozen=True)
class MessageSpec:
    """A decoded message type: its table, its presence-vector width and its fields."""

    number: int
    name: str
    table: str
    presence_vector_octets: int
    fields: tuple[FieldSpec, ...]

    def presence_vector_is_wide_enough(self) -> bool:
        """§3.x — "a message containing ten fields would have a two-byte Presence Vector".

        Asserted rather than assumed for all four decoded messages: the document states the width
        per message in its own table AND states the rule that generates it, so the two are
        independent and either one being mistranscribed is visible.
        """
        return self.presence_vector_octets * 8 >= len(self.fields)


# ---------------------------------------------------------------- the enumerations, verbatim
#
# Each map below is transcribed from its field's own "Range" cell. Ranges that the document gives
# as a SPAN rather than a value — "5 - 9 = Reserved", "10 - 255 = VSM Specific" — are not expanded
# into individual keys: they are answered by `enumeration_text()`, so a reserved value stays
# distinguishable from an unassigned one and neither is mistaken for a name the document gives.

#: §4.4.3, field 0101.07 / 0104.05. "Defines altitude type (reference frame) for all altitude
#: related fields in this message."
#:
#: VALUE 3 IS THE AMBIGUOUS ONE AND IT IS THE ONLY ONE THE CDM COULD USE. "WGS-84 (geoid)" names
#: two different surfaces in four words — WGS-84 is an ellipsoid, the geoid is an equipotential
#: surface, and they differ by roughly -107 m to +85 m over the earth. `Position.alt_m` is
#: documented "Metres HAE". Ambiguity 3 in the pin; the adapter is what acts on it.
ALTITUDE_TYPE = {
    0: "Pressure Altitude",
    1: "Baro Altitude",
    2: "AGL",
    3: "WGS-84 (geoid)",
}

#: §4.4.3, field 0104.11. "Defines speed type (reference frame) for all speed related fields in
#: this message."
SPEED_TYPE = {
    0: "Indicated / Calibrated Airspeed",
    1: "True Airspeed",
    2: "Ground Speed",
    3: "Thrust",
}

#: §4.4.3, field 0104.19.
ALTITUDE_COMMAND_TYPE = {1: "Altitude", 2: "Vertical Speed", 3: "Rate-limited altitude"}

#: §4.4.3, field 0104.20.
HEADING_COMMAND_TYPE = {
    1: "Heading", 2: "Course", 3: "Heading and Course", 4: "Roll", 5: "Heading Rate",
}

#: §4.4.3, field 3002.01. "The reported flight phase of the air vehicle."
#:
#: THE ENUMERATION NAMES NO AIRBORNE STATE, which is the whole reason this map is worth reading
#: rather than glancing at. Every assigned value is a phase BEFORE flight — power up, pre-start,
#: pre-launch, launch abort — and everything from 10 upward is "VSM Specific". So an air vehicle
#: that is actually flying reports either `0 = Unknown` or a vendor-defined number that this
#: document does not name, and there is no conformant way to say "cruise" or "on approach".
#:
#: The consequence for the adapter is a refusal: AV State is NEVER read as a CDM semantic — not
#: into `entity_type`, not into an `Event`, not into a status the platform would act on. It parks
#: with its value and its text, and a value in 10-255 parks as VSM-specific rather than being
#: guessed at. Reading a vendor's private number as a flight phase would be inventing a fleet
#: model, which is the CAT034 platform-type refusal in a new costume.
AV_STATE = {
    0: "Unknown",
    1: "Power Up",
    2: "Pre-start",
    3: "Pre-launch",
    4: "Launch Abort",
}
AV_STATE_RESERVED = range(5, 10)
AV_STATE_VSM_SPECIFIC = range(10, 256)


def av_state_text(value: int) -> str:
    """The document's own word for an AV State value, including for the spans it does not name."""
    if value in AV_STATE:
        return AV_STATE[value]
    if value in AV_STATE_RESERVED:
        return "Reserved"
    if value in AV_STATE_VSM_SPECIFIC:
        return "VSM Specific"
    return "out of range"


def enumeration_text(spec: "FieldSpec", value: int) -> str:
    """The document's name for `value`, or an explicit statement that it does not give one."""
    if spec.enumeration is None:
        raise Stanag4586DecodeError(f"{spec.name} is not an enumerated field")
    if spec.unique_id == "3002.01":
        return av_state_text(value)
    return spec.enumeration.get(value, "not assigned by Edition 3")


# ------------------------------------------------------------------- the four decoded messages
#
# Field rows are transcribed from each message's own table with the Unique ID, the Field number,
# the Data Element Name, the Type and its octet count, and the Units cell. The Units cell is kept
# VERBATIM beside the machine-readable scale so a reader can check the multiplier against the
# document without opening this module's paraphrase — the arrangement `klv_uas_codec` uses.

_TIME_STAMP_UNITS = "0.001 s"

MESSAGES: dict[int, MessageSpec] = {}


def _register(spec: MessageSpec) -> MessageSpec:
    MESSAGES[spec.number] = spec
    return spec


INERTIAL_STATES = _register(MessageSpec(
    number=4000, name="Inertial States", table="B1-74", presence_vector_octets=3,
    fields=(
        FieldSpec(1, "0101.01", "Time Stamp", "timestamp", 5, None, _TIME_STAMP_UNITS),
        FieldSpec(2, "0101.04", "Latitude", "bam", 4, None, "BAM"),
        FieldSpec(3, "0101.05", "Longitude", "bam", 4, None, "BAM"),
        FieldSpec(4, "0101.06", "Altitude", "integer", 3, 0.02, "0.02 m"),
        FieldSpec(5, "0101.07", "Altitude Type", "unsigned", 1, None, "Enumerated", ALTITUDE_TYPE),
        FieldSpec(6, "0101.08", "U_Speed", "integer", 2, 0.05, "0.05 m/s"),
        FieldSpec(7, "0101.09", "V_Speed", "integer", 2, 0.05, "0.05 m/s"),
        FieldSpec(8, "0101.10", "W_Speed", "integer", 2, 0.05, "0.05 m/s"),
        FieldSpec(9, "0101.11", "U_Accel", "integer", 2, 0.005, "0.005 m/s2"),
        FieldSpec(10, "0101.12", "V_Accel", "integer", 2, 0.005, "0.005 m/s2"),
        FieldSpec(11, "0101.13", "W_Accel", "integer", 2, 0.005, "0.005 m/s2"),
        FieldSpec(12, "0101.14", "Roll", "bam", 2, None, "BAM"),
        FieldSpec(13, "0101.15", "Pitch", "bam", 2, None, "BAM"),
        FieldSpec(14, "0101.16", "Heading", "bam", 2, None, "BAM"),
        FieldSpec(15, "0101.17", "Roll Rate", "integer", 2, 0.005, "0.005 rad/s"),
        FieldSpec(16, "0101.18", "Pitch Rate", "integer", 2, 0.005, "0.005 rad/s"),
        FieldSpec(17, "0101.19", "Turn Rate", "integer", 2, 0.005, "0.005 rad/s"),
        FieldSpec(18, "0101.20", "Magnetic Variation", "bam", 2, None, "BAM"),
    ),
))

VEHICLE_OPERATING_STATES = _register(MessageSpec(
    number=3002, name="Vehicle Operating States", table="B1-60", presence_vector_octets=3,
    fields=(
        FieldSpec(1, "0104.01", "Time Stamp", "timestamp", 5, None, _TIME_STAMP_UNITS),
        FieldSpec(2, "0104.04", "Commanded Altitude", "integer", 3, 0.02, "0.02 m"),
        FieldSpec(3, "0104.05", "Altitude Type", "unsigned", 1, None, "Enumerated", ALTITUDE_TYPE),
        FieldSpec(4, "0104.06", "Commanded Heading", "bam", 2, None, "BAM"),
        FieldSpec(5, "0104.07", "Commanded Course", "bam", 2, None, "BAM"),
        FieldSpec(6, "0104.08", "Commanded Turn Rate", "integer", 2, 0.0001, "0.0001 rad/s"),
        FieldSpec(7, "0104.09", "Commanded Roll Rate", "integer", 2, 0.005, "0.005 rad/s"),
        FieldSpec(8, "0104.10", "Commanded Speed", "unsigned", 2, 0.5, "0.5 m/s"),
        FieldSpec(9, "0104.11", "Speed Type", "unsigned", 1, None, "Enumerated", SPEED_TYPE),
        FieldSpec(10, "0104.12", "Power Level", "integer", 1, None, "%"),
        FieldSpec(11, "0104.21", "Bingo Energy", "unsigned", 2, 0.0016, "0.0016 %"),
        FieldSpec(12, "0104.16", "Current Propulsion Energy Level", "unsigned", 2, 0.0016, "0.0016 %"),
        FieldSpec(13, "0104.17", "Current Propulsion Energy Usage Rate", "unsigned", 2, 0.0002, "0.0002 %/s"),
        FieldSpec(14, "0104.18", "Commanded Roll", "bam", 2, None, "BAM"),
        FieldSpec(15, "0104.19", "Altitude Command Type", "unsigned", 1, None, "Enumerated", ALTITUDE_COMMAND_TYPE),
        FieldSpec(16, "0104.20", "Heading Command Type", "unsigned", 1, None, "Enumerated", HEADING_COMMAND_TYPE),
        FieldSpec(17, "3002.01", "AV State", "unsigned", 1, None, "Enumerated", AV_STATE),
        FieldSpec(18, "3002.02", "Thrust Direction", "bam", 2, None, "BAM"),
        FieldSpec(19, "3002.03", "Thrust", "unsigned", 1, None, "%"),
    ),
))

AIR_AND_GROUND_RELATIVE_STATES = _register(MessageSpec(
    number=3009, name="Air and Ground Relative States", table="B1-67", presence_vector_octets=2,
    fields=(
        FieldSpec(1, "0102.01", "Time Stamp", "timestamp", 5, None, _TIME_STAMP_UNITS),
        FieldSpec(2, "0102.04", "Angle of Attack", "bam", 2, None, "BAM"),
        FieldSpec(3, "0102.05", "Angle of Sideslip", "bam", 2, None, "BAM"),
        FieldSpec(4, "0102.06", "True Airspeed", "unsigned", 2, 0.05, "0.05 m/s"),
        FieldSpec(5, "0102.07", "Indicated Airspeed", "unsigned", 2, 0.05, "0.05 m/s"),
        FieldSpec(6, "0102.08", "Outside Air Temp", "unsigned", 2, 0.5, "0.5 K"),
        FieldSpec(7, "0102.09", "U_Wind", "integer", 2, 0.05, "0.05 m/s"),
        FieldSpec(8, "0102.10", "V_Wind", "integer", 2, 0.05, "0.05 m/s"),
        FieldSpec(9, "0102.11", "Altimeter Setting", "unsigned", 2, 10.0, "10 Pa"),
        FieldSpec(10, "0102.12", "Barometric Altitude", "integer", 3, 0.02, "0.02 m"),
        FieldSpec(11, "0102.13", "Barometric Altitude Rate", "integer", 2, 0.05, "0.05 m/s"),
        FieldSpec(12, "0102.14", "Pressure Altitude", "integer", 3, 0.02, "0.02 m"),
        FieldSpec(13, "0102.15", "AGL Altitude", "integer", 3, 0.02, "0.02 m"),
        FieldSpec(14, "0102.16", "WGS-84 Altitude", "integer", 3, 0.02, "0.02 m"),
        FieldSpec(15, "0102.17", "U_Ground", "integer", 2, 0.05, "0.05 m/s"),
        FieldSpec(16, "0102.18", "V_Ground", "integer", 2, 0.05, "0.05 m/s"),
    ),
))

BODY_RELATIVE_SENSED_STATES = _register(MessageSpec(
    number=3010, name="Body-Relative Sensed States", table="B1-68", presence_vector_octets=1,
    fields=(
        FieldSpec(1, "0103.01", "Time Stamp", "timestamp", 5, None, _TIME_STAMP_UNITS),
        FieldSpec(2, "0103.04", "X_Body_Accel", "integer", 2, 0.005, "0.005 m/s2"),
        FieldSpec(3, "0103.05", "Y_Body_Accel", "integer", 2, 0.005, "0.005 m/s2"),
        FieldSpec(4, "0103.06", "Z_Body_Accel", "integer", 2, 0.005, "0.005 m/s2"),
        # 0.0001 rad/s and NOT #4000's 0.005 — full scale is +/-pi by construction here. The two
        # sets never share a CDM key; ambiguity 4 in the pin says why.
        FieldSpec(5, "0103.07", "Roll_Rate", "integer", 2, 0.0001, "0.0001 rad/s"),
        FieldSpec(6, "0103.08", "Pitch_Rate", "integer", 2, 0.0001, "0.0001 rad/s"),
        FieldSpec(7, "0103.09", "Yaw_Rate", "integer", 2, 0.0001, "0.0001 rad/s"),
    ),
))


# ------------------------------------------------------------------------------- the wrapper


@dataclasses.dataclass(frozen=True)
class Wrapper:
    """§3.3.1's sixteen octets, decoded. Every field is kept, including the unused ones."""

    sequence: int
    message_length: int
    source_id: int
    destination_id: int
    message_type: int
    properties: int

    @property
    def ack_requested(self) -> bool:
        """§3.3.1.10 — bit 15. "When the bit is '1,' an acknowledgement shall be sent"."""
        return bool(self.properties & 0x8000)

    @property
    def idd_version(self) -> int:
        """§3.3.1.10 — "The next seven bits (bits 14:8) shall indicate the IDD version number"."""
        return (self.properties >> 8) & 0x7F

    @property
    def checksum_code(self) -> int:
        """The Checksum Length subfield READ AT BITS 7:6 — one of two independent statements.

        The bit position is not recoverable from this copy's text layer (ambiguity 1), so this is
        the reading Figure B1-8's column order supports and NOT a fact the document spells. It is
        never used to size the checksum; `decode_frame` derives that from the frame arithmetic and
        compares the two. Exposed so the comparison is checkable from outside this module.
        """
        return (self.properties >> 6) & 0b11

    @property
    def source_owning_id(self) -> int:
        """§1.7.6 — "The first (most significant) byte shall be the Owning ID"."""
        return (self.source_id >> 24) & 0xFF

    @property
    def sequence_is_conformant(self) -> bool:
        """§3.3.1.5 — the field "shall contain '-1'", i.e. `0xFFFF` unsigned (ambiguity 2)."""
        return self.sequence == SEQUENCE_NOT_USED


@dataclasses.dataclass(frozen=True)
class Frame:
    """One wrapped DLI message as it sat on the wire, with what was wrong with it recorded."""

    wrapper: Wrapper
    data: bytes
    checksum_octets: int
    checksum_stated: int | None
    checksum_computed: int | None
    #: Structured, never raised: a frame with a defect still decodes. Same policy as
    #: `stanag4609`'s length divergence — a producer's error must reach the operator as data.
    defects: tuple[dict[str, Any], ...] = ()

    @property
    def total_octets(self) -> int:
        return WRAPPER_OCTETS + self.wrapper.message_length + self.checksum_octets

    @property
    def checksum_valid(self) -> bool | None:
        """None when the frame carries no checksum — which is not the same as a failing one."""
        if self.checksum_octets == 0:
            return None
        return self.checksum_stated == self.checksum_computed


def compute_checksum(octets: bytes, width: int) -> int:
    """§3.3.1.11 — "simple, byte-wise unsigned binary addition of all data contained in the
    message excluding the checksum, and truncated to 2 or 4 bytes"."""
    return sum(octets) & ((1 << (width * 8)) - 1)


def decode_frame(raw: bytes, offset: int = 0) -> Frame:
    """One frame starting at `offset`. Raises only where the octets cannot be a frame at all.

    THE CHECKSUM WIDTH IS DERIVED AND THEN CROSS-EXAMINED, which is this module's one real design
    decision. `trailing = len(raw) - offset - 16 - message_length` is fixed by the octets and the
    format allows exactly 0, 2 or 4. The Message Properties subfield is then read at bits 7:6 and
    a disagreement is recorded as a defect rather than resolved — because resolving it would mean
    preferring one of two readings on no evidence, and the ambiguity is real.

    That only works on a buffer holding ONE frame. `decode_frames` handles the multi-frame
    datagram §3.3.1.6 contemplates and does not have this freedom; see its own note.
    """
    if len(raw) - offset < WRAPPER_OCTETS:
        raise Stanag4586DecodeError(
            f"{len(raw) - offset} octets from offset {offset} cannot hold a {WRAPPER_OCTETS}-octet "
            "STANAG 4586 message wrapper (Annex B Appendix 1 §3.3.1, Figure B1-7)"
        )
    view = raw[offset:offset + WRAPPER_OCTETS]
    wrapper = Wrapper(
        sequence=decode_unsigned(view[0:2]),
        message_length=decode_unsigned(view[2:4]),
        source_id=decode_unsigned(view[4:8]),
        destination_id=decode_unsigned(view[8:12]),
        message_type=decode_unsigned(view[12:14]),
        properties=decode_unsigned(view[14:16]),
    )
    defects: list[dict[str, Any]] = []
    if not (MESSAGE_LENGTH_MIN <= wrapper.message_length <= MESSAGE_LENGTH_MAX):
        raise Stanag4586DecodeError(
            f"message length {wrapper.message_length} is outside §3.3.1.6's stated range "
            f"{MESSAGE_LENGTH_MIN}..{MESSAGE_LENGTH_MAX}"
        )
    body_end = offset + WRAPPER_OCTETS + wrapper.message_length
    if body_end > len(raw):
        raise Stanag4586DecodeError(
            f"wrapper declares {wrapper.message_length} octets of message data but only "
            f"{len(raw) - offset - WRAPPER_OCTETS} remain after the wrapper"
        )
    data = raw[offset + WRAPPER_OCTETS:body_end]

    trailing = len(raw) - body_end
    if trailing not in CHECKSUM_OCTETS_BY_CODE.values():
        raise Stanag4586DecodeError(
            f"{trailing} octets follow the message data; §3.3.1.11 allows a checksum of 0, 2 or 4 "
            "only, so this buffer is not a single well-formed frame"
        )
    stated_code = wrapper.checksum_code
    implied = CHECKSUM_OCTETS_BY_CODE.get(stated_code)
    if implied is None:
        defects.append({
            "kind": "checksum_length_code_unassigned",
            "code": stated_code,
            "detail": "Table B1-4 assigns 00, 01 and 10 only; 11 is not a stated width",
            "ambiguity": "pin ambiguity 1 — the subfield's bit position is itself unrecovered",
        })
    elif implied != trailing:
        defects.append({
            "kind": "checksum_length_disagreement",
            "octets_from_frame_arithmetic": trailing,
            "octets_from_properties_bits_7_6": implied,
            "detail": (
                "the frame's own length and the Message Properties subfield state different "
                "checksum widths; the arithmetic is used because it is determined by the octets, "
                "and the disagreement is carried rather than resolved"
            ),
            "ambiguity": "pin ambiguity 1",
        })
    stated = decode_unsigned(raw[body_end:]) if trailing else None
    computed = compute_checksum(raw[offset:body_end], trailing) if trailing else None
    if trailing and stated != computed:
        defects.append({
            "kind": "checksum_mismatch",
            "stated": stated,
            "computed": computed,
            "detail": "§3.3.1.11's byte-wise sum over the wrapper and data does not match",
        })
    if not wrapper.sequence_is_conformant:
        defects.append({
            "kind": "sequence_not_the_unused_value",
            "sequence": wrapper.sequence,
            "detail": "§3.3.1.5 says the field is not used and shall contain '-1' (0xFFFF)",
            "ambiguity": "pin ambiguity 2",
        })
    if wrapper.idd_version != IDD_VERSION_EDITION_3:
        defects.append({
            "kind": "idd_version_is_not_edition_3",
            "stated": wrapper.idd_version,
            "expected": IDD_VERSION_EDITION_3,
            "detail": (
                "Table B1-3 assigns 30 to Edition 3, which is the only edition this repository "
                "holds. A frame declaring another version is decoded against Edition 3's tables "
                "anyway and this defect is how the reader learns that happened"
            ),
        })
    if wrapper.source_owning_id == OWNING_ID_RESERVED:
        defects.append({
            "kind": "source_owning_id_is_reserved",
            "detail": "§1.7.6 reserves 255 (0xFF) as an Owning ID",
        })
    return Frame(wrapper=wrapper, data=data, checksum_octets=trailing,
                 checksum_stated=stated, checksum_computed=computed, defects=tuple(defects))


def decode_frames(raw: bytes) -> list[Frame]:
    """Every frame in a datagram, in wire order.

    §3.3.1.6 contemplates more than one message per datagram — "Extra care should be taken when
    packing multiple messages in the same datagram" — so this exists, and it is where ambiguity 1
    stops being free.

    **A single-frame buffer is sized by arithmetic; a multi-frame one cannot be.** With two frames
    in a datagram there is no unique trailing count to solve for, so the checksum width of every
    frame but the last has to come from the Message Properties subfield — the reading this module
    does not claim the document fixes. That dependency is RECORDED on each such frame rather than
    left implicit.

    What makes it tolerable is that a wrong reading is loud, not silent: mis-sizing one checksum
    shifts the next frame's wrapper, and the next wrapper's message length then almost always
    falls outside §3.3.1.6's 1..528 or overruns the buffer, so `decode_frame`'s refusals fire.
    Framing breaks visibly instead of a frame decoding into plausible wrong numbers.
    """
    frames: list[Frame] = []
    offset = 0
    while offset < len(raw):
        remaining = len(raw) - offset
        if remaining < WRAPPER_OCTETS:
            raise Stanag4586DecodeError(
                f"{remaining} trailing octets at offset {offset} are too few for a wrapper; the "
                "datagram does not divide into whole frames"
            )
        peek = Wrapper(
            sequence=decode_unsigned(raw[offset:offset + 2]),
            message_length=decode_unsigned(raw[offset + 2:offset + 4]),
            source_id=decode_unsigned(raw[offset + 4:offset + 8]),
            destination_id=decode_unsigned(raw[offset + 8:offset + 12]),
            message_type=decode_unsigned(raw[offset + 12:offset + 14]),
            properties=decode_unsigned(raw[offset + 14:offset + 16]),
        )
        width = CHECKSUM_OCTETS_BY_CODE.get(peek.checksum_code, 0)
        end = offset + WRAPPER_OCTETS + peek.message_length + width
        is_last = end >= len(raw)
        frame = decode_frame(raw[offset:end if not is_last else len(raw)])
        if not is_last:
            frame = dataclasses.replace(frame, defects=frame.defects + ({
                "kind": "checksum_width_taken_from_the_properties_subfield",
                "octets": width,
                "detail": (
                    "this frame is not the last in its datagram, so its checksum width could not "
                    "be derived from the buffer length and was read at Message Properties bits "
                    "7:6 instead"
                ),
                "ambiguity": "pin ambiguity 1",
            },))
        frames.append(frame)
        offset = end
    if not frames:
        raise Stanag4586DecodeError("empty payload: no STANAG 4586 frame present")
    return frames


# ------------------------------------------------------------------------ the message payload


@dataclasses.dataclass(frozen=True)
class DecodedField:
    """One present field, with the raw integer kept beside the scaled value.

    Both are kept for the reason `klv_uas_codec` keeps both: the scaled value is what a consumer
    wants and the raw integer is what a dispute is settled against. A float that came out wrong
    cannot be un-multiplied once the integer is gone.
    """

    spec: FieldSpec
    raw: int
    value: float | int | dt.datetime
    text: str | None = None


@dataclasses.dataclass(frozen=True)
class DecodedMessage:
    """A message whose type is in `MESSAGES`, decoded field by field."""

    spec: MessageSpec
    presence_vector: int
    fields: dict[int, DecodedField]
    trailing_octets: bytes = b""

    def get(self, unique_id: str) -> DecodedField | None:
        """By Unique ID — the document's own key, and stable where field numbers are not."""
        for field in self.fields.values():
            if field.spec.unique_id == unique_id:
                return field
        return None

    @property
    def absent_indices(self) -> tuple[int, ...]:
        return tuple(f.index for f in self.spec.fields if f.index not in self.fields)


def presence_bits(presence_vector: int, spec: MessageSpec) -> Iterator[int]:
    """The field indices the vector marks present.

    §3.x — "The least significant bit indicates the presence of the time stamp (field 1); the next
    more significant bit indicates the presence of the second field, etc." So bit `k` selects field
    `k + 1`, and there is no bit for field 0, the presence vector itself, which is always present.
    """
    for field in spec.fields:
        if presence_vector & (1 << (field.index - 1)):
            yield field.index


def decode_message(frame: Frame) -> DecodedMessage:
    """The message data of a frame whose type this module knows.

    Raises `KeyError` for an unknown type ON PURPOSE — an unknown message is not an error and the
    adapter parks it; making that a *decode* refusal here would force the adapter to catch a
    ValueError to implement its normal path.
    """
    spec = MESSAGES[frame.wrapper.message_type]
    data = frame.data
    pv_width = spec.presence_vector_octets
    if len(data) < pv_width:
        raise Stanag4586DecodeError(
            f"message #{spec.number} declares a {pv_width}-octet presence vector "
            f"(Table {spec.table}) but the message data is {len(data)} octets"
        )
    presence_vector = decode_unsigned(data[:pv_width])
    by_index = {field.index: field for field in spec.fields}
    fields: dict[int, DecodedField] = {}
    cursor = pv_width
    for index in presence_bits(presence_vector, spec):
        field = by_index[index]
        end = cursor + field.octets
        if end > len(data):
            raise Stanag4586DecodeError(
                f"message #{spec.number} field {index} ({field.name}, {field.unique_id}) needs "
                f"{field.octets} octets at offset {cursor} but the message data ends at {len(data)}"
            )
        octets = data[cursor:end]
        cursor = end
        fields[index] = _decode_field(field, octets)
    return DecodedMessage(spec=spec, presence_vector=presence_vector, fields=fields,
                          trailing_octets=data[cursor:])


def _decode_field(spec: FieldSpec, octets: bytes) -> DecodedField:
    if spec.kind == "timestamp":
        raw = decode_unsigned(octets)
        return DecodedField(spec, raw, timestamp_to_utc(raw))
    if spec.kind == "bam":
        raw = decode_integer(octets)
        return DecodedField(spec, raw, bam_to_radians(raw, spec.octets))
    raw = decode_integer(octets) if spec.kind == "integer" else decode_unsigned(octets)
    if spec.is_enumerated:
        return DecodedField(spec, raw, raw, enumeration_text(spec, raw))
    if spec.scale is None:
        return DecodedField(spec, raw, raw)
    return DecodedField(spec, raw, raw * spec.scale)
