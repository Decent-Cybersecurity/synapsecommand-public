"""The DIS 7 Entity State codec: its public error model, the PDU decoder and encoder, and the
WGS84 projection and ENU kinematics helpers.

Every refusal this codec and the `dis7` adapter raise is a `Dis7Error`, which prints as
`CODE at PATH: message`. `decode_pdu` reads one Entity State PDU into its decoded shape and
`looks_like_entity_state` judges the header triplet alone. The module also encodes a decoded PDU
back to its octets with `encode_pdu`. The code order below is the order of the code table in the handoff
document `SC DIS7 SPEC 001 v1.0`, which is not in this repository. The acceptance cases this
codec is held to ship in `fixtures/dis7/contract/acceptance-cases.json`. The projection
(`ecef_to_geodetic`) and the kinematics (`velocity_to_kinematics`) are the helpers the adapter
maps a decoded PDU with.
"""
from __future__ import annotations

import math
import struct

from synapse_cdm.adapter import InputTooDeep, InputTooLarge

E_INPUT_TYPE = "E_INPUT_TYPE"
E_INPUT_LIMIT = "E_INPUT_LIMIT"
E_CONTEXT_SESSION = "E_CONTEXT_SESSION"
E_CONTEXT_SYNTHETIC = "E_CONTEXT_SYNTHETIC"
E_CONTEXT_TIME = "E_CONTEXT_TIME"
E_CONTEXT_CONFLICT = "E_CONTEXT_CONFLICT"
E_CONTEXT_HASH = "E_CONTEXT_HASH"
E_HEADER_UNSUPPORTED = "E_HEADER_UNSUPPORTED"
E_LENGTH_MISMATCH = "E_LENGTH_MISMATCH"
E_NONFINITE = "E_NONFINITE"
E_TWIN_SCHEMA = "E_TWIN_SCHEMA"
E_TWIN_WIRE_MISMATCH = "E_TWIN_WIRE_MISMATCH"
E_VALUE_RANGE = "E_VALUE_RANGE"
E_POSITION_DOMAIN = "E_POSITION_DOMAIN"
E_PROJECTION = "E_PROJECTION"
E_REPLAY_SHAPE = "E_REPLAY_SHAPE"
E_REPLAY_PROVENANCE = "E_REPLAY_PROVENANCE"
E_REPLAY_CHANGED = "E_REPLAY_CHANGED"

CODES = (
    E_INPUT_TYPE,
    E_INPUT_LIMIT,
    E_CONTEXT_SESSION,
    E_CONTEXT_SYNTHETIC,
    E_CONTEXT_TIME,
    E_CONTEXT_CONFLICT,
    E_CONTEXT_HASH,
    E_HEADER_UNSUPPORTED,
    E_LENGTH_MISMATCH,
    E_NONFINITE,
    E_TWIN_SCHEMA,
    E_TWIN_WIRE_MISMATCH,
    E_VALUE_RANGE,
    E_POSITION_DOMAIN,
    E_PROJECTION,
    E_REPLAY_SHAPE,
    E_REPLAY_PROVENANCE,
    E_REPLAY_CHANGED,
)


class Dis7Error(ValueError):
    """Every coded refusal the codec and the `dis7` adapter raise."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(code, path, message)
        self.code = code
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"


class Dis7InputTooLarge(Dis7Error, InputTooLarge):
    """An `E_INPUT_LIMIT` refusal for a payload over the declared byte bound."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(E_INPUT_LIMIT, path, message)
        # Copy and pickle rebuild an exception as type(self)(*self.args).
        self.args = (path, message)


class Dis7InputTooDeep(Dis7Error, InputTooDeep):
    """An `E_INPUT_LIMIT` refusal for an envelope nested past the declared depth bound."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(E_INPUT_LIMIT, path, message)
        # Copy and pickle rebuild an exception as type(self)(*self.args).
        self.args = (path, message)


MIN_PDU_BYTES = 144
MAX_PDU_BYTES = 4224
RECORD_BYTES = 16
MAX_RECORDS = 255

# The nine interpreted vector components in ascending offset: (offset, struct format).
_VECTOR_COMPONENTS = (
    (36, ">f"), (40, ">f"), (44, ">f"),
    (48, ">d"), (56, ">d"), (64, ">d"),
    (72, ">f"), (76, ">f"), (80, ">f"),
)


def _decode_records(raw: bytes, count: int) -> list[str]:
    """The `count` variable records after the fixed part, each as 32 lowercase hex characters."""
    return [
        raw[MIN_PDU_BYTES + RECORD_BYTES * k:MIN_PDU_BYTES + RECORD_BYTES * (k + 1)].hex()
        for k in range(count)
    ]


def decode_pdu(raw) -> dict:
    """Exactly one Entity State PDU as its decoded shape; every refusal is a `Dis7Error`.

    Checks run in contract order: input type, the size bound, the minimum length, the header
    octets 0, 2 and 3, the declared length, the record count, then the nine interpreted vector
    components. Octets inside the dead-reckoning record, the marking and the variable records
    are opaque and kept as they are.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise Dis7Error(E_INPUT_TYPE, "$", "input is not a byte sequence")
    # CR-29: a memoryview of any item size counts as its octets.
    try:
        data = bytes(raw)
    except (ValueError, TypeError, BufferError):
        raise Dis7Error(E_INPUT_TYPE, "$", "the buffer cannot be read") from None
    size = len(data)
    if size > MAX_PDU_BYTES:
        raise Dis7InputTooLarge("$", f"input is {size} octets; the limit is {MAX_PDU_BYTES}")
    if size < MIN_PDU_BYTES:
        raise Dis7Error(E_LENGTH_MISMATCH, f"byte[{size}]",
                        f"input is {size} octets; the minimum is {MIN_PDU_BYTES}")
    if data[0] != 7:
        raise Dis7Error(E_HEADER_UNSUPPORTED, "byte[0]", "protocol version is not 7")
    if data[2] != 1:
        raise Dis7Error(E_HEADER_UNSUPPORTED, "byte[2]", "PDU type is not 1")
    if data[3] != 1:
        raise Dis7Error(E_HEADER_UNSUPPORTED, "byte[3]", "protocol family is not 1")
    length = struct.unpack_from(">H", data, 8)[0]
    if size != length:
        raise Dis7Error(E_LENGTH_MISMATCH, "byte[8]",
                        f"declared length {length}, received {size} octets")
    count = data[19]
    if length != MIN_PDU_BYTES + RECORD_BYTES * count:
        raise Dis7Error(E_LENGTH_MISMATCH, "byte[19]",
                        f"declared length {length} does not hold {count} records")
    for offset, fmt in _VECTOR_COMPONENTS:
        if not math.isfinite(struct.unpack_from(fmt, data, offset)[0]):
            raise Dis7Error(E_NONFINITE, f"byte[{offset}]", "vector component is not finite")
    version, exercise, kind, family, timestamp, _, status, padding = struct.unpack_from(
        ">BBBBIHBB", data, 0)
    return {
        "header": {"protocol_version": version, "exercise_id": exercise, "pdu_type": kind,
                   "protocol_family": family, "timestamp": timestamp, "length": length,
                   "status": status, "padding": padding},
        "entity_id": list(struct.unpack_from(">HHH", data, 12)),
        "force_id": data[18],
        "entity_type": list(struct.unpack_from(">BBHBBBB", data, 20)),
        "alternative_entity_type": list(struct.unpack_from(">BBHBBBB", data, 28)),
        "velocity_mps": list(struct.unpack_from(">fff", data, 36)),
        "position_ecef_m": list(struct.unpack_from(">ddd", data, 48)),
        "orientation_radians": list(struct.unpack_from(">fff", data, 72)),
        "appearance": struct.unpack_from(">I", data, 84)[0],
        "dead_reckoning_hex": data[88:128].hex(),
        "marking_hex": data[128:140].hex(),
        "capabilities": struct.unpack_from(">I", data, 140)[0],
        "variable_parameters_hex": _decode_records(data, count),
    }


def looks_like_entity_state(raw) -> bool:
    """True when octets 0, 2 and 3 of a byte sequence are 7, 1 and 1. Never raises.

    Judges neither the length nor the record count, and has no upper size bound.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        return False
    try:
        head = bytes(raw[:12])
    except (ValueError, TypeError, BufferError):   # e.g. a released memoryview
        return False
    return len(head) >= 12 and head[0] == 7 and head[2] == 1 and head[3] == 1


# The decoded shape, in decode order.
_TOP_KEYS = (
    "header", "entity_id", "force_id", "entity_type", "alternative_entity_type", "velocity_mps",
    "position_ecef_m", "orientation_radians", "appearance", "dead_reckoning_hex", "marking_hex",
    "capabilities", "variable_parameters_hex",
)
_HEADER_KEYS = (
    "protocol_version", "exercise_id", "pdu_type", "protocol_family", "timestamp", "length",
    "status", "padding",
)
# Integer members judged at stage 5: (header member, top).
_HEADER_RANGES = (("exercise_id", 0xFF), ("timestamp", 0xFFFFFFFF), ("status", 0xFF),
                  ("padding", 0xFF))
_TYPE_TOPS = (0xFF, 0xFF, 0xFFFF, 0xFF, 0xFF, 0xFF, 0xFF)
_VECTORS = (("velocity_mps", ">f"), ("position_ecef_m", ">d"), ("orientation_radians", ">f"))
_HEX_DIGITS = frozenset("0123456789abcdef")
_U32 = 0xFFFFFFFF


def _is_integer(value) -> bool:
    """An `int`, or a finite `float` with no fractional part (CR-06); never a `bool`."""
    kind = type(value)
    return kind is int or (kind is float and math.isfinite(value) and value.is_integer())


def _is_number(value) -> bool:
    """An `int` or a `float`; never a `bool`. Non-finite floats are judged at stage 4."""
    return type(value) is int or type(value) is float


def _is_array(value, size: int) -> bool:
    return type(value) in (list, tuple) and len(value) == size


def _schema(path: str, message: str) -> Dis7Error:
    return Dis7Error(E_TWIN_SCHEMA, path, message)


def _check_integer_array(pdu: dict, name: str, size: int) -> None:
    value = pdu[name]
    if not _is_array(value, size):
        raise _schema(name, f"expected an array of {size} integers")
    for i, item in enumerate(value):
        if not _is_integer(item):
            raise _schema(f"{name}[{i}]", "expected an integer")


def _check_structure(pdu) -> None:
    """Stage 1: keys, types, array sizes, hex widths and the record count."""
    if type(pdu) is not dict:
        raise _schema("$", "the argument is not an object")
    for name in _TOP_KEYS:
        if name not in pdu:
            raise _schema(name, "a decoded PDU member is missing")
    if len(pdu) != len(_TOP_KEYS):
        raise _schema("$", "the object has a member that is not part of a decoded PDU")
    header = pdu["header"]
    if type(header) is not dict:
        raise _schema("header", "the header is not an object")
    for name in _HEADER_KEYS:
        if name not in header:
            raise _schema(f"header.{name}", "a header member is missing")
    if len(header) != len(_HEADER_KEYS):
        raise _schema("header", "the header has a member that is not part of a decoded header")
    for name in _HEADER_KEYS:
        if not _is_integer(header[name]):
            raise _schema(f"header.{name}", "expected an integer")
    _check_integer_array(pdu, "entity_id", 3)
    if not _is_integer(pdu["force_id"]):
        raise _schema("force_id", "expected an integer")
    _check_integer_array(pdu, "entity_type", 7)
    _check_integer_array(pdu, "alternative_entity_type", 7)
    for name, _ in _VECTORS:
        value = pdu[name]
        if not _is_array(value, 3):
            raise _schema(name, "expected an array of 3 numbers")
        for i, item in enumerate(value):
            if not _is_number(item):
                raise _schema(f"{name}[{i}]", "expected a number")
    if not _is_integer(pdu["appearance"]):
        raise _schema("appearance", "expected an integer")
    for name, width in (("dead_reckoning_hex", 80), ("marking_hex", 24)):
        value = pdu[name]
        if type(value) is not str or len(value) != width:
            raise _schema(name, f"expected a string of {width} hex characters")
    if not _is_integer(pdu["capabilities"]):
        raise _schema("capabilities", "expected an integer")
    records = pdu["variable_parameters_hex"]
    # N10: the count is judged before any record is looked at, so 256 is never wrapped.
    if type(records) not in (list, tuple) or len(records) > MAX_RECORDS:
        raise _schema("variable_parameters_hex",
                      f"expected an array of at most {MAX_RECORDS} records")
    for k, record in enumerate(records):
        if type(record) is not str or len(record) != 2 * RECORD_BYTES:
            raise _schema(f"variable_parameters_hex[{k}]",
                          f"expected a string of {2 * RECORD_BYTES} hex characters")


def _out_of_range(path: str, top: int) -> Dis7Error:
    return Dis7Error(E_VALUE_RANGE, path, f"expected an integer from 0 to {top}")


def _bad_hex(path: str) -> Dis7Error:
    return Dis7Error(E_VALUE_RANGE, path, "expected lowercase hex digits only")


def _survives(value, fmt: str) -> bool:
    """True when `value` packs into the wire width and unpacks to an equal value."""
    try:
        packed = struct.pack(fmt, value)
    except (OverflowError, struct.error):
        return False
    return struct.unpack(fmt, packed)[0] == value


def _check_values(pdu: dict) -> None:
    """Stage 5: integer ranges, wire-width representability and hex characters."""
    header = pdu["header"]
    for name, top in _HEADER_RANGES:
        if not 0 <= header[name] <= top:
            raise _out_of_range(f"header.{name}", top)
    for i, item in enumerate(pdu["entity_id"]):
        if not 0 <= item <= 0xFFFF:
            raise _out_of_range(f"entity_id[{i}]", 0xFFFF)
    if not 0 <= pdu["force_id"] <= 0xFF:
        raise _out_of_range("force_id", 0xFF)
    for name in ("entity_type", "alternative_entity_type"):
        for i, (item, top) in enumerate(zip(pdu[name], _TYPE_TOPS)):
            if not 0 <= item <= top:
                raise _out_of_range(f"{name}[{i}]", top)
    for name, fmt in _VECTORS:
        width = 32 if fmt == ">f" else 64
        for i, item in enumerate(pdu[name]):
            if not _survives(item, fmt):
                raise Dis7Error(E_VALUE_RANGE, f"{name}[{i}]",
                                f"the value is not exactly representable in binary{width}")
    if not 0 <= pdu["appearance"] <= _U32:
        raise _out_of_range("appearance", _U32)
    for name in ("dead_reckoning_hex", "marking_hex"):
        if not set(pdu[name]) <= _HEX_DIGITS:
            raise _bad_hex(name)
    if not 0 <= pdu["capabilities"] <= _U32:
        raise _out_of_range("capabilities", _U32)
    for k, record in enumerate(pdu["variable_parameters_hex"]):
        if not set(record) <= _HEX_DIGITS:
            raise _bad_hex(f"variable_parameters_hex[{k}]")


def encode_pdu(pdu) -> bytes:
    """The octets of one decoded Entity State PDU; the lossless inverse of `decode_pdu`.

    Every member is required. Checks run in five stages, each finished over every member in
    decode order before the next begins (CR-04): structure (`E_TWIN_SCHEMA`), the header
    constants (`E_HEADER_UNSUPPORTED`), the declared length against the record count
    (`E_LENGTH_MISMATCH`), finite vector components (`E_NONFINITE`), then integer ranges,
    exact representability in the wire width and hex characters (`E_VALUE_RANGE`). Arrays may
    be lists or tuples (CR-29); integer members take an integral float (CR-06). The argument is
    never modified.
    """
    _check_structure(pdu)
    header = pdu["header"]
    if header["protocol_version"] != 7:
        raise Dis7Error(E_HEADER_UNSUPPORTED, "header.protocol_version",
                        "protocol version is not 7")
    if header["pdu_type"] != 1:
        raise Dis7Error(E_HEADER_UNSUPPORTED, "header.pdu_type", "PDU type is not 1")
    if header["protocol_family"] != 1:
        raise Dis7Error(E_HEADER_UNSUPPORTED, "header.protocol_family",
                        "protocol family is not 1")
    records = pdu["variable_parameters_hex"]
    count = len(records)
    if header["length"] != MIN_PDU_BYTES + RECORD_BYTES * count:
        raise Dis7Error(E_LENGTH_MISMATCH, "header.length",
                        f"the declared length does not hold {count} records")
    for name, _ in _VECTORS:
        for i, item in enumerate(pdu[name]):
            if type(item) is float and not math.isfinite(item):
                raise Dis7Error(E_NONFINITE, f"{name}[{i}]", "vector component is not finite")
    _check_values(pdu)
    return b"".join((
        struct.pack(">BBBBIHBB", *(int(header[name]) for name in _HEADER_KEYS)),
        struct.pack(">HHHBB", *(int(v) for v in pdu["entity_id"]), int(pdu["force_id"]), count),
        struct.pack(">BBHBBBB", *(int(v) for v in pdu["entity_type"])),
        struct.pack(">BBHBBBB", *(int(v) for v in pdu["alternative_entity_type"])),
        struct.pack(">fff", *pdu["velocity_mps"]),
        struct.pack(">ddd", *pdu["position_ecef_m"]),
        struct.pack(">fff", *pdu["orientation_radians"]),
        struct.pack(">I", int(pdu["appearance"])),
        bytes.fromhex(pdu["dead_reckoning_hex"]),
        bytes.fromhex(pdu["marking_hex"]),
        struct.pack(">I", int(pdu["capabilities"])),
        b"".join(bytes.fromhex(record) for record in records),
    ))


# WGS84 ellipsoid. Heights are ellipsoidal (HAE); no geoid or terrain model is involved.
WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
WGS84_B = WGS84_A * (1 - WGS84_F)
# The reference iteration's cap, read at call time so a test can lower it and reach E_PROJECTION.
PROJECTION_MAX_ITERATIONS = 15
# Dead-reckoning algorithms whose velocity is world (ECEF) coordinates (case A04); a mutation seam.
WORLD_ALGORITHMS = frozenset({2, 3, 4, 5})


def _positive_zero(value: float) -> float:
    return 0.0 if value == 0 else value


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float] | None:
    """`(lat_deg, lon_deg, hae_m)` for an ECEF position in metres, or `None` for the origin.

    The origin, also when written with negative zeros, has no projection (CR-35). Other radii
    below b/2 or above 1e9 metres, and a non-finite radius, are `E_POSITION_DOMAIN` (case N11).
    A point on the polar axis takes the pole branch; every other point runs the reference
    iteration, which must converge within `PROJECTION_MAX_ITERATIONS` steps or the position is
    `E_PROJECTION`. Outputs equal to zero are returned as positive zero.
    """
    if x == 0 and y == 0 and z == 0:
        return None
    r = math.hypot(x, y, z)
    if not math.isfinite(r) or r < WGS84_B / 2 or r > 1e9:
        raise Dis7Error(E_POSITION_DOMAIN, "byte[48]",
                        "the location's radius is outside the projectable domain")
    p = math.hypot(x, y)
    if p == 0:
        lat = math.copysign(90.0, z)
        lon = 0.0
        h = abs(z) - WGS84_B
    else:
        phi = math.atan2(z, p * (1 - WGS84_E2))
        converged = False
        for _ in range(PROJECTION_MAX_ITERATIONS):
            n = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(phi) ** 2)
            next_phi = math.atan2(z + WGS84_E2 * n * math.sin(phi), p)
            converged = abs(next_phi - phi) < 1e-14
            phi = next_phi
            if converged:
                break
        if not converged:
            raise Dis7Error(E_PROJECTION, "byte[48]",
                            "the reference iteration did not converge for the location")
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(phi) ** 2)
        h = p * math.cos(phi) + z * math.sin(phi) - n * (1 - WGS84_E2 * math.sin(phi) ** 2)
        lat = math.degrees(phi)
        # The sign of 180 at the antimeridian is whatever atan2 returns for the untouched y.
        lon = math.degrees(math.atan2(y, x))
    if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(h)) \
            or not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise Dis7Error(E_PROJECTION, "byte[48]",
                        "the location's projection is not finite or out of range")
    return _positive_zero(lat), _positive_zero(lon), _positive_zero(h)


def velocity_to_kinematics(velocity, lat_deg: float, lon_deg: float) -> dict:
    """Horizontal speed, course and climb for an ECEF velocity at a projected position (A05).

    The velocity is rotated into local east, north and up. `speed_mps` is the horizontal speed,
    `climb_mps` is the up component, and `course_deg` is `None` at zero speed or at exactly
    either pole; a course that rounds to 360 is 0. Outputs equal to zero are positive zero. The
    caller decides from the dead-reckoning algorithm whether the velocity is world coordinates.
    """
    vx, vy, vz = velocity
    phi = math.radians(lat_deg)
    lam = math.radians(lon_deg)
    east = -math.sin(lam) * vx + math.cos(lam) * vy
    north = (-math.sin(phi) * math.cos(lam) * vx - math.sin(phi) * math.sin(lam) * vy
             + math.cos(phi) * vz)
    up = (math.cos(phi) * math.cos(lam) * vx + math.cos(phi) * math.sin(lam) * vy
          + math.sin(phi) * vz)
    speed = math.hypot(east, north)
    if not (math.isfinite(speed) and math.isfinite(up)):
        raise Dis7Error(E_PROJECTION, "byte[48]", "the velocity's projection is not finite")
    if speed == 0 or lat_deg == 90 or lat_deg == -90:
        course = None
    else:
        course = math.degrees(math.atan2(east, north)) % 360.0
        if course >= 360.0:
            course = 0.0
        course = _positive_zero(course)
    return {"speed_mps": _positive_zero(speed), "course_deg": course,
            "climb_mps": _positive_zero(up)}
