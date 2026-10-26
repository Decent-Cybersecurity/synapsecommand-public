"""The four attribute decoders of profile SC-HLA-RPR2-OBS-1: `decode_attribute(name, value)`.

WHAT IS DECODED, AND FROM WHAT
------------------------------
The value of an HLA attribute is an HLA encoding of an RPR FOM 2.0 data type, not a DIS PDU
body (R18): EntityIdentifier, EntityType, ForceIdentifier and Spatial, laid out by the table at
SPEC:80-84 and the Spatial tables at SPEC:88-108. Every number is read with an explicit
big-endian `struct` format at an explicit offset; nothing is cast, nothing relies on the host's
byte order or on native packing, and no DIS offset appears anywhere. The Spatial variant table
below is the FOM's: the `DeadReckoningAlgorithmEnum8` discriminator in byte 0, seven bytes of
alignment padding, and from offset 8 the fixed record its alternative names. That the FOM's
semantics text calls the FV structure "FVW (5) and RVB (9)" is a typo R20 tells us to ignore:
algorithm 8 is RVB and carries acceleration and angular velocity, algorithm 9 is FVB and carries
acceleration only.

Binary32 fields are widened exactly (COD-04): `struct` unpacks `>f` to the double holding the
same value, so 0x3dcccccd decodes to 0.10000000149011612 and not to the 0.1 a shortest-repr
reading would give. Negative zero is kept (COD-15): only the geographic projection normalises
zero, and only in the numbers it computes. Padding bytes are preserved in wire order in
`padding_hex` and never interpreted, so a value with NaN-shaped or 0xff padding decodes like one
with zero padding. Enumerations are not checked against the FOM's enumerator lists: an unknown
kind, country or force value is data, not a defect (R19).

ONE ERROR, IN A FIXED ORDER
---------------------------
A value either decodes completely or raises exactly one `HlaError`; a partial result is never
returned (COD-06). Which error, when a value has several defects, is fixed by SPEC:281 and the
rulings that complete it:

1. the size bound: more than `V1.attribute_value_bytes` bytes is E_LIMIT, checked before
   anything else, the name included (COD-05) — the native worker is to refuse such a value
   before copying it (round R7), and a capture cannot hold one, so only a direct call reaches
   this;
2. the name: exactly one of the four, compared case-sensitively, else E_UNSUBSCRIBED_ATTRIBUTE;
3. for Spatial, the discriminator: 1 through 9, else E_SPATIAL_VARIANT; an empty value has no
   discriminator and is a length error instead (COD-07);
4. the exact length of the attribute or variant, else E_ATTRIBUTE_LENGTH — no end padding;
5. the frozen RPRboolean at offset 32: exactly 0 or 1, else E_BOOLEAN;
6. every interpreted float in ascending offset order: the first non-finite one is E_NONFINITE.

`path` is the attribute name, with `/<byte offset>` for E_BOOLEAN and E_NONFINITE (CR-L01). A
name that is not one of the four comes from the wire and may be anything; it goes into `path`
only through `errors.safe_text` (CR-R0-04), and no message quotes it. The reducer that will call
this (round R4) is to put the attribute name it passed, never `path`, into a diagnostic's
`attribute` field.

A `name` that is not a `str` or a `value` that is not `bytes` is not input from the wire but a
bug in the caller, and raises `TypeError`. Subclasses are refused too: a `str` subclass can
redefine equality and a `bytes` subclass can redefine indexing, and either would let a caller's
object decide what the decoder sees.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from synapse_hla import errors
from synapse_hla.errors import HlaError, safe_text
from synapse_hla.limits import V1

ENTITY_IDENTIFIER = "EntityIdentifier"
ENTITY_TYPE = "EntityType"
FORCE_IDENTIFIER = "ForceIdentifier"
SPATIAL = "Spatial"

#: The four attributes this profile decodes, sorted by name as SPEC:281 sorts attribute arrays.
NAMES: tuple[str, ...] = (ENTITY_IDENTIFIER, ENTITY_TYPE, FORCE_IDENTIFIER, SPATIAL)

#: Exact lengths of the three fixed-size attributes (SPEC:81-83).
FIXED_LENGTHS: Mapping[str, int] = MappingProxyType({
    ENTITY_IDENTIFIER: 6,
    ENTITY_TYPE: 8,
    FORCE_IDENTIFIER: 1,
})

# Every reader is big-endian by its format's first character; a test holds that for every
# struct format in this module.
_ENTITY_IDENTIFIER = struct.Struct(">HHH")
_ENTITY_TYPE = struct.Struct(">BBHBBBB")
_FLOAT64 = struct.Struct(">d")
_FLOAT32 = struct.Struct(">f")

# --- the Spatial layout, SPEC:88-97 ---------------------------------------------------------------

#: Offsets of ECEF x, y, z (binary64 metres).
POSITION_OFFSETS: tuple[int, int, int] = (8, 16, 24)
#: Offset of the frozen RPRboolean (one octet, 0 or 1).
FROZEN_OFFSET = 32
#: Offsets of psi, theta, phi (binary32 radians).
ORIENTATION_OFFSETS: tuple[int, int, int] = (36, 40, 44)
#: The uninterpreted bytes: 1-7 (before the body's eight-octet boundary) and 33-35 (after the
#: frozen octet, before the binary32 orientation), in wire order.
PADDING_SLICES: tuple[tuple[int, int], tuple[int, int]] = ((1, 8), (33, 36))

WORLD = "WORLD"
BODY = "BODY"


@dataclass(frozen=True)
class SpatialVariant:
    """One row of the variant table at SPEC:99-108: where each optional binary32 triple starts.

    `None` means the variant has no such field and the decoded value carries null for it. The
    triples follow each other in ascending offset order in every variant: velocity at 48, then
    acceleration at 60, then angular velocity at 60 when there is no acceleration or at 72 when
    there is.
    """

    algorithm: int
    frame: str
    total_bytes: int
    velocity_at: int | None
    acceleration_at: int | None
    angular_velocity_at: int | None


#: The nine variants by discriminator value. 0 (Other) and 10-255 are not here, so they are
#: E_SPATIAL_VARIANT (R20).
VARIANTS: Mapping[int, SpatialVariant] = MappingProxyType({
    1: SpatialVariant(1, WORLD, 48, None, None, None),  # Static
    2: SpatialVariant(2, WORLD, 60, 48, None, None),    # DRM_FPW
    3: SpatialVariant(3, WORLD, 72, 48, None, 60),      # DRM_RPW
    4: SpatialVariant(4, WORLD, 84, 48, 60, 72),        # DRM_RVW
    5: SpatialVariant(5, WORLD, 72, 48, 60, None),      # DRM_FVW
    6: SpatialVariant(6, BODY, 60, 48, None, None),     # DRM_FPB
    7: SpatialVariant(7, BODY, 72, 48, None, 60),       # DRM_RPB
    8: SpatialVariant(8, BODY, 84, 48, 60, 72),         # DRM_RVB
    9: SpatialVariant(9, BODY, 72, 48, 60, None),       # DRM_FVB
})


def decode_attribute(name: str, value: bytes) -> dict:
    """Decode one attribute value: `{"name": name, "value": <shape>}` or one `HlaError`.

    The shape is the one `decoded-attribute.schema.json` gives for `name`. Pure: no state is
    kept between calls and every call returns new objects.
    """
    if type(name) is not str:
        raise TypeError("decode_attribute name must be a str")
    if type(value) is not bytes:
        raise TypeError("decode_attribute value must be bytes")
    length = len(value)
    if length > V1.attribute_value_bytes:
        limit = V1.attribute_value_bytes
        raise HlaError(errors.E_LIMIT, safe_text(name),
                       f"an attribute value of {length} bytes exceeds the limit of {limit} bytes")
    if name == SPATIAL:
        return {"name": SPATIAL, "value": _spatial(value)}
    if name == ENTITY_IDENTIFIER:
        _exact_length(ENTITY_IDENTIFIER, value, FIXED_LENGTHS[ENTITY_IDENTIFIER])
        site, application, entity = _ENTITY_IDENTIFIER.unpack(value)
        return {"name": ENTITY_IDENTIFIER,
                "value": {"site": site, "application": application, "entity": entity}}
    if name == ENTITY_TYPE:
        _exact_length(ENTITY_TYPE, value, FIXED_LENGTHS[ENTITY_TYPE])
        kind, domain, country, category, subcategory, specific, extra = _ENTITY_TYPE.unpack(value)
        return {"name": ENTITY_TYPE,
                "value": {"kind": kind, "domain": domain, "country": country,
                          "category": category, "subcategory": subcategory,
                          "specific": specific, "extra": extra}}
    if name == FORCE_IDENTIFIER:
        _exact_length(FORCE_IDENTIFIER, value, FIXED_LENGTHS[FORCE_IDENTIFIER])
        # Every octet value is preserved: the FOM enumerates 0-30, the profile keeps 0-255.
        return {"name": FORCE_IDENTIFIER, "value": {"value": value[0]}}
    raise HlaError(errors.E_UNSUBSCRIBED_ATTRIBUTE, safe_text(name),
                   "the attribute is not one of the four this profile decodes")


def _exact_length(name: str, value: bytes, total: int) -> None:
    length = len(value)
    if length != total:
        raise HlaError(errors.E_ATTRIBUTE_LENGTH, name,
                       f"the value holds {length} bytes and must hold exactly {total}")


def _spatial(value: bytes) -> dict:
    if not value:
        # No discriminator to judge, so the defect is the length (COD-07).
        raise HlaError(errors.E_ATTRIBUTE_LENGTH, SPATIAL,
                       "the value is empty and has no dead-reckoning algorithm octet")
    algorithm = value[0]
    variant = VARIANTS.get(algorithm)
    if variant is None:
        raise HlaError(errors.E_SPATIAL_VARIANT, SPATIAL,
                       f"dead-reckoning algorithm {algorithm} is not one of 1 to 9")
    length = len(value)
    total = variant.total_bytes
    if length != total:
        raise HlaError(errors.E_ATTRIBUTE_LENGTH, SPATIAL,
                       f"algorithm {algorithm} needs exactly {total} bytes, the value holds {length}")
    flag = value[FROZEN_OFFSET]
    if flag > 1:
        raise HlaError(errors.E_BOOLEAN, f"{SPATIAL}/{FROZEN_OFFSET}",
                       f"the frozen octet is {flag}, and an RPRboolean is 0 or 1")
    # Read in ascending offset order, so that the first non-finite field found is the one at the
    # lowest offset (SPEC:281).
    position = _floats(value, _FLOAT64, POSITION_OFFSETS)
    orientation = _floats(value, _FLOAT32, ORIENTATION_OFFSETS)
    velocity = _triple(value, variant.velocity_at)
    acceleration = _triple(value, variant.acceleration_at)
    angular_velocity = _triple(value, variant.angular_velocity_at)
    (pad_a, pad_b), (pad_c, pad_d) = PADDING_SLICES
    return {
        "algorithm": algorithm,
        "frame": variant.frame,
        "frozen": flag == 1,
        "position_ecef_m": position,
        "orientation_rad": orientation,
        "velocity_mps": velocity,
        "acceleration_mps2": acceleration,
        "angular_velocity_radps": angular_velocity,
        "padding_hex": (value[pad_a:pad_b] + value[pad_c:pad_d]).hex(),
    }


def _triple(value: bytes, start: int | None) -> list[float] | None:
    if start is None:
        return None
    return _floats(value, _FLOAT32, (start, start + 4, start + 8))


def _floats(value: bytes, reader: struct.Struct, offsets: tuple[int, ...]) -> list[float]:
    out = []
    for offset in offsets:
        (number,) = reader.unpack_from(value, offset)
        if not math.isfinite(number):
            raise HlaError(errors.E_NONFINITE, f"{SPATIAL}/{offset}",
                           f"the float at byte offset {offset} is not finite")
        out.append(number)
    return out
