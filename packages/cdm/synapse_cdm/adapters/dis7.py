"""DIS 7 Entity State PDU <-> CDM `Entity`: caller time context, session rule, identity.
Adapter #21.

This module holds the caller-supplied time context (`TimeContext`), the session rule
(`validate_session`), the identity derivation (`external_id`, `identity_system`, `entity_uuid`)
and `Dis7Adapter`, registered as `dis7`. One Entity State PDU, given as octets or as an envelope,
becomes one Entity; an unchanged Entity gives the original octets back; everything else is refused
with a coded `Dis7Error`.
"""
from __future__ import annotations

import dataclasses
import datetime
import functools
import math
import re
import uuid

import pydantic

from synapse_cdm import ids, lossless
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import dis7_codec as codec
from synapse_cdm.adapters.dis7_codec import (
    CODES,
    E_CONTEXT_CONFLICT,
    E_CONTEXT_HASH,
    E_CONTEXT_SESSION,
    E_CONTEXT_SYNTHETIC,
    E_CONTEXT_TIME,
    E_HEADER_UNSUPPORTED,
    E_INPUT_LIMIT,
    E_INPUT_TYPE,
    E_LENGTH_MISMATCH,
    E_NONFINITE,
    E_POSITION_DOMAIN,
    E_PROJECTION,
    E_REPLAY_CHANGED,
    E_REPLAY_PROVENANCE,
    E_REPLAY_SHAPE,
    E_TWIN_SCHEMA,
    E_TWIN_WIRE_MISMATCH,
    E_VALUE_RANGE,
    Dis7Error,
    Dis7InputTooDeep,
    Dis7InputTooLarge,
)
from synapse_cdm.enums import Affiliation, EntityType, PositionSource
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                   Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                   Limits, Maturity, MaturityLevel, Residual, UnknownFields,
                                   WireBinding)
from synapse_cdm.models import (
    Entity, Kinematics, Position, Residual as ResidualBlock, SourceHash, SourceId, SourceRef,
)

__all__ = [
    "BASIS_WHITESPACE", "TimeContext", "validate_session",
    "external_id", "identity_system", "entity_uuid",
    "Dis7Error", "Dis7InputTooLarge", "Dis7InputTooDeep", "CODES",
    "E_INPUT_TYPE", "E_INPUT_LIMIT", "E_CONTEXT_SESSION", "E_CONTEXT_SYNTHETIC",
    "E_CONTEXT_TIME", "E_CONTEXT_CONFLICT", "E_CONTEXT_HASH", "E_HEADER_UNSUPPORTED",
    "E_LENGTH_MISMATCH", "E_NONFINITE", "E_TWIN_SCHEMA", "E_TWIN_WIRE_MISMATCH",
    "E_VALUE_RANGE", "E_POSITION_DOMAIN", "E_PROJECTION", "E_REPLAY_SHAPE",
    "E_REPLAY_PROVENANCE", "E_REPLAY_CHANGED",
    "Dis7Adapter", "FIXTURE_SESSION", "FIXTURE_TIME_CONTEXT", "MAX_ENVELOPE_DEPTH",
]

#: The characters a basis may not consist of entirely (CR-07): the whitespace of Python 3.11 to
#: 3.14 plus U+FEFF, enumerated so that the verdict depends on no interpreter and no regex engine.
BASIS_WHITESPACE = frozenset(
    [chr(code) for code in range(0x0009, 0x000E)]
    + [chr(code) for code in range(0x001C, 0x0020)]
    + [chr(0x0020), chr(0x0085), chr(0x00A0), chr(0x1680)]
    + [chr(code) for code in range(0x2000, 0x200B)]
    + [chr(0x2028), chr(0x2029), chr(0x202F), chr(0x205F), chr(0x3000), chr(0xFEFF)]
)

_INSTANT = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]{1,3}))?(Z|[+-][0-9]{2}:[0-9]{2})"
)
_SESSION = re.compile(r"[A-Za-z0-9._-]{1,128}")
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_BASIS_MAX = 1024


def _instant_refused(message: str) -> Dis7Error:
    return Dis7Error(E_CONTEXT_TIME, "time_context.instant", message)


def _basis_refused(message: str) -> Dis7Error:
    return Dis7Error(E_CONTEXT_TIME, "time_context.basis", message)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _normalise_instant(instant: object) -> str:
    if type(instant) is not str:
        raise _instant_refused("the instant is not a string")
    match = _INSTANT.fullmatch(instant)
    if match is None:
        raise _instant_refused(
            "the instant is not an RFC 3339 date-time with seconds, at most three fractional "
            "digits and an explicit Z or numeric offset"
        )
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction, offset = match.group(7), match.group(8)
    if not 1 <= year <= 9999:
        raise _instant_refused("the instant's year is outside 0001 to 9999")
    if not 1 <= month <= 12:
        raise _instant_refused("the instant's month is outside 1 to 12")
    month_days = 29 if month == 2 and _is_leap(year) else _MONTH_DAYS[month - 1]
    if not 1 <= day <= month_days:
        raise _instant_refused("the instant's day does not exist in its month")
    if hour > 23 or minute > 59 or second > 59:
        raise _instant_refused("the instant's time of day is out of range; leap seconds are refused")
    shift = datetime.timedelta(0)
    if offset != "Z":
        offset_hour, offset_minute = int(offset[1:3]), int(offset[4:6])
        if offset_hour > 23 or offset_minute > 59:
            raise _instant_refused("the instant's UTC offset is out of range")
        shift = datetime.timedelta(hours=offset_hour, minutes=offset_minute)
        if offset[0] == "-":
            shift = -shift
    millis = int((fraction or "").ljust(3, "0"))
    try:
        utc = datetime.datetime(year, month, day, hour, minute, second, millis * 1000) - shift
    except (OverflowError, ValueError):
        raise _instant_refused("the instant normalised to UTC leaves the years 0001 to 9999") from None
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T{utc.hour:02d}:{utc.minute:02d}:"
        f"{utc.second:02d}.{utc.microsecond // 1000:03d}Z"
    )


def _check_basis(basis: object) -> None:
    if type(basis) is not str:
        raise _basis_refused("the basis is not a string")
    if not 1 <= len(basis) <= _BASIS_MAX:
        raise _basis_refused("the basis is not 1 to 1024 characters long")
    if all(character in BASIS_WHITESPACE for character in basis):
        raise _basis_refused("the basis consists only of whitespace")
    try:
        basis.encode("utf-8")
    except UnicodeEncodeError:
        raise _basis_refused("the basis is not encodable as UTF-8") from None


@dataclasses.dataclass(frozen=True)
class TimeContext:
    """The caller's resolved state instant and the basis on which it was resolved.

    DIS's 32-bit timestamp carries no date and no hour, so the instant is never inferred: the
    caller supplies it. `instant` is stored normalised to UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`;
    `basis` is kept exactly as given.
    """

    instant: str
    basis: str

    def __post_init__(self) -> None:
        normalised = _normalise_instant(self.instant)
        _check_basis(self.basis)
        object.__setattr__(self, "instant", normalised)


#: The session the packaged fixtures were recorded under.
FIXTURE_SESSION = "unnamed"
#: The packaged fixtures' state instant and basis; never the clock.
FIXTURE_TIME_CONTEXT = TimeContext("2026-04-29T06:15:00.000Z",
                                   "Synthetic fixture scenario instant; not capture time")
#: The deepest envelope the coded guard admits, counting the root as one level.
MAX_ENVELOPE_DEPTH = 16

_MISSING = object()


def validate_session(value: object) -> str:
    """Return `value` itself if it is 1 to 128 ASCII letters, digits, dots, underscores or hyphens."""
    if type(value) is not str or _SESSION.fullmatch(value) is None:
        raise Dis7Error(
            E_CONTEXT_SESSION, "session",
            "the session is not 1 to 128 ASCII letters, digits, dots, underscores or hyphens",
        )
    return value


def external_id(entity_id) -> str:
    """Site, application and entity as unpadded decimals joined by colons."""
    return f"{entity_id[0]}:{entity_id[1]}:{entity_id[2]}"


def identity_system(session: str, exercise_id: int) -> str:
    """The source identity system, `DIS7:<session>:<exercise_id>`."""
    return f"DIS7:{session}:{exercise_id}"


def entity_uuid(session: str, exercise_id: int, entity_id) -> uuid.UUID:
    """The entity's UUID, derived through `ids.derive` from the system and the external id."""
    return ids.derive(identity_system(session, exercise_id), external_id(entity_id))


# The mutation seams (PLAN §4.10). Each is called by its bare name from the adapter's methods.

def _assemble_position(lat_deg, lon_deg, hae_m):
    return Position(lat=lat_deg, lon=lon_deg, alt_m=hae_m, position_source=PositionSource.ESTIMATED)


def _affiliation(force_id):
    return Affiliation.UNKNOWN


def _state_instant(adapter, context):
    text = context.instant
    return datetime.datetime(
        int(text[0:4]), int(text[5:7]), int(text[8:10]), int(text[11:13]), int(text[14:16]),
        int(text[17:19]), int(text[20:23]) * 1000, tzinfo=datetime.timezone.utc)


def _replay_bytes(wire_hex):
    return bytes.fromhex(wire_hex)


def _canonical_equal(provided, expected):
    return type(provided) is type(expected) and provided == expected


# Structure checks (stage 2 of an envelope, step 2 of replay). Each takes the value, its path and
# the code to refuse with; none echoes a value or a key the caller sent.

_HEX = re.compile("[0-9a-f]*")
_STORED_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?(Z|[+-][0-9]{2}:[0-9]{2})")
_U32 = 0xFFFFFFFF
_HEADER_RULES = (
    ("protocol_version", 7, 7), ("exercise_id", 0, 0xFF), ("pdu_type", 1, 1),
    ("protocol_family", 1, 1), ("timestamp", 0, _U32), ("length", codec.MIN_PDU_BYTES,
                                                         codec.MAX_PDU_BYTES),
    ("status", 0, 0xFF), ("padding", 0, 0xFF),
)
_HEADER_KEYS = tuple(name for name, _, _ in _HEADER_RULES)
_PDU_KEYS = (
    "header", "entity_id", "force_id", "entity_type", "alternative_entity_type", "velocity_mps",
    "position_ecef_m", "orientation_radians", "appearance", "dead_reckoning_hex", "marking_hex",
    "capabilities", "variable_parameters_hex",
)
_TYPE_TOPS = (0xFF, 0xFF, 0xFFFF, 0xFF, 0xFF, 0xFF, 0xFF)
_ENVELOPE_KEYS = ("pdu", "wire_hex", "time_context")
_RESIDUAL_KEYS = ("pdu", "wire_hex", "time_context", "session", "synthetic", "source_hash")
_CONTEXT_KEYS = ("instant", "basis")
_HASH_KEYS = ("algorithm", "value")
_WIRE_HEX_MIN = 2 * codec.MIN_PDU_BYTES
_WIRE_HEX_MAX = 2 * codec.MAX_PDU_BYTES


def _member(path, name):
    return name if path == "$" else f"{path}.{name}"


def _is_integer(value):
    return type(value) is int or (type(value) is float and value.is_integer())


def _is_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _is_hex(value, width):
    return type(value) is str and len(value) == width and _HEX.fullmatch(value) is not None


def _check_object(value, path, code, keys):
    """Rules 1 to 3 at one object: a dict, no key outside `keys`, every key of `keys` present."""
    if not isinstance(value, dict):
        raise Dis7Error(code, path, "the member is not an object")
    for key in value:
        if type(key) is not str or key not in keys:
            raise Dis7Error(code, path, "the object has a member outside its schema")
    for key in keys:
        if key not in value:
            raise Dis7Error(code, _member(path, key), "the required member is absent")


def _check_integer(value, path, code, low, high):
    if not _is_integer(value) or not low <= value <= high:
        raise Dis7Error(code, path, f"the member is not an integer from {low} to {high}")


def _check_array(value, path, code, size):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise Dis7Error(code, path, f"the member is not an array of {size} items")


def _check_integer_array(value, path, code, tops):
    _check_array(value, path, code, len(tops))
    for index, top in enumerate(tops):
        _check_integer(value[index], f"{path}[{index}]", code, 0, top)


def _check_number_array(value, path, code):
    _check_array(value, path, code, 3)
    for index in range(3):
        if not _is_number(value[index]):
            raise Dis7Error(code, f"{path}[{index}]", "the item is not a finite number")


def _check_hex(value, path, code, width):
    if not _is_hex(value, width):
        raise Dis7Error(code, path, f"the member is not {width} lowercase hexadecimal characters")


def _check_pdu(pdu, path, code):
    _check_object(pdu, path, code, _PDU_KEYS)
    header_path = _member(path, "header")
    header = pdu["header"]
    _check_object(header, header_path, code, _HEADER_KEYS)
    for name, low, high in _HEADER_RULES:
        _check_integer(header[name], _member(header_path, name), code, low, high)
    _check_integer_array(pdu["entity_id"], _member(path, "entity_id"), code, (0xFFFF,) * 3)
    _check_integer(pdu["force_id"], _member(path, "force_id"), code, 0, 0xFF)
    for name in ("entity_type", "alternative_entity_type"):
        _check_integer_array(pdu[name], _member(path, name), code, _TYPE_TOPS)
    for name in ("velocity_mps", "position_ecef_m", "orientation_radians"):
        _check_number_array(pdu[name], _member(path, name), code)
    _check_integer(pdu["appearance"], _member(path, "appearance"), code, 0, _U32)
    _check_hex(pdu["dead_reckoning_hex"], _member(path, "dead_reckoning_hex"), code, 80)
    _check_hex(pdu["marking_hex"], _member(path, "marking_hex"), code, 24)
    _check_integer(pdu["capabilities"], _member(path, "capabilities"), code, 0, _U32)
    records_path = _member(path, "variable_parameters_hex")
    records = pdu["variable_parameters_hex"]
    if not isinstance(records, (list, tuple)) or len(records) > codec.MAX_RECORDS:
        raise Dis7Error(code, records_path,
                        f"the member is not an array of at most {codec.MAX_RECORDS} items")
    for index, record in enumerate(records):
        _check_hex(record, f"{records_path}[{index}]", code, 2 * codec.RECORD_BYTES)


def _check_wire_hex(value, path, code):
    if type(value) is not str or not _WIRE_HEX_MIN <= len(value) <= _WIRE_HEX_MAX \
            or len(value) % 2 or _HEX.fullmatch(value) is None:
        raise Dis7Error(code, path, f"the member is not {_WIRE_HEX_MIN} to {_WIRE_HEX_MAX} "
                                    "lowercase hexadecimal characters of whole octets")


def _check_time_context(value, path, code, stored):
    _check_object(value, path, code, _CONTEXT_KEYS)
    instant_path, basis_path = _member(path, "instant"), _member(path, "basis")
    instant, basis = value["instant"], value["basis"]
    if type(instant) is not str:
        raise Dis7Error(code, instant_path, "the member is not a string")
    if stored and _STORED_INSTANT.fullmatch(instant) is None:
        raise Dis7Error(code, instant_path, "the member does not match the stored instant pattern")
    if type(basis) is not str:
        raise Dis7Error(code, basis_path, "the member is not a string")
    if stored and (not 1 <= len(basis) <= 1024
                   or all(character in BASIS_WHITESPACE for character in basis)):
        raise Dis7Error(code, basis_path,
                        "the member is not 1 to 1024 characters with one that is not white space")


def _check_hash(value, path, code):
    """`None`, or a plain dict of exactly `algorithm` "sha256" and a 64-character lowercase digest."""
    if value is None:
        return
    if type(value) is not dict or len(value) != 2 or any(key not in value for key in _HASH_KEYS):
        raise Dis7Error(code, path, "the source hash is not an object of algorithm and value")
    algorithm = value["algorithm"]
    if type(algorithm) is not str or algorithm != "sha256":
        raise Dis7Error(code, f"{path}.algorithm", "the algorithm is not sha256")
    if not _is_hex(value["value"], 64):
        raise Dis7Error(code, f"{path}.value",
                        "the digest is not 64 lowercase hexadecimal characters")


def _check_envelope(envelope):
    """Stage 2: the envelope's structure, refused as `E_TWIN_SCHEMA`."""
    _check_object(envelope, "$", E_TWIN_SCHEMA, _ENVELOPE_KEYS)
    _check_pdu(envelope["pdu"], "pdu", E_TWIN_SCHEMA)
    _check_wire_hex(envelope["wire_hex"], "wire_hex", E_TWIN_SCHEMA)
    _check_time_context(envelope["time_context"], "time_context", E_TWIN_SCHEMA, stored=False)


def _check_residual(data, path):
    """Replay step 2: a stored residual against the residual schema, refused as `E_REPLAY_SHAPE`."""
    _check_object(data, path, E_REPLAY_SHAPE, _RESIDUAL_KEYS)
    _check_pdu(data["pdu"], _member(path, "pdu"), E_REPLAY_SHAPE)
    _check_wire_hex(data["wire_hex"], _member(path, "wire_hex"), E_REPLAY_SHAPE)
    _check_time_context(data["time_context"], _member(path, "time_context"), E_REPLAY_SHAPE,
                        stored=True)
    session = data["session"]
    if type(session) is not str or _SESSION.fullmatch(session) is None:
        raise Dis7Error(E_REPLAY_SHAPE, _member(path, "session"),
                        "the member is not 1 to 128 ASCII letters, digits, dots, underscores "
                        "or hyphens")
    if type(data["synthetic"]) is not bool:
        raise Dis7Error(E_REPLAY_SHAPE, _member(path, "synthetic"), "the member is not a boolean")
    _check_hash(data["source_hash"], _member(path, "source_hash"), E_REPLAY_SHAPE)


def _twin_difference(twin_pdu, wire_pdu):
    """The first member, relative to the PDU, where a checked twin differs from the decoded wire,
    or `None`. Python values are compared, so 7.0 equals 7 and the two zeros are equal."""
    for name in _HEADER_KEYS:
        if twin_pdu["header"][name] != wire_pdu["header"][name]:
            return f"header.{name}"
    for name in _PDU_KEYS[1:]:
        twin, wire = twin_pdu[name], wire_pdu[name]
        if isinstance(wire, list):
            if len(twin) != len(wire):
                return name
            for index, (left, right) in enumerate(zip(twin, wire)):
                if left != right:
                    return f"{name}[{index}]"
        elif twin != wire:
            return name
    return None


# The coded guard (PLAN §4.3): size, then type, then depth and cycles. It runs before the SDK's
# wrapper, so every refusal at this stage carries a code and the path `$`.

def _containers(node):
    values = node.values() if isinstance(node, dict) else node
    return iter([value for value in values if isinstance(value, (dict, list, tuple))])


def _guard_depth(root):
    """An on-stack set finds cycles; a per-object memo of sub-heights means every distinct
    container is expanded once, so shared references are accepted and cost nothing."""
    heights = {}
    on_stack = {id(root)}
    stack = [[root, _containers(root), 0]]
    while stack:
        frame = stack[-1]
        descended = False
        for child in frame[1]:
            key = id(child)
            if key in on_stack:
                raise Dis7InputTooDeep("$", "the object refers to itself")
            known = heights.get(key)
            if known is not None:
                if len(stack) + known > MAX_ENVELOPE_DEPTH:
                    raise Dis7InputTooDeep("$", f"nesting exceeds {MAX_ENVELOPE_DEPTH} levels")
                frame[2] = max(frame[2], known)
                continue
            if len(stack) + 1 > MAX_ENVELOPE_DEPTH:
                raise Dis7InputTooDeep("$", f"nesting exceeds {MAX_ENVELOPE_DEPTH} levels")
            on_stack.add(key)
            stack.append([child, _containers(child), 0])
            descended = True
            break
        if descended:
            continue
        stack.pop()
        on_stack.discard(id(frame[0]))
        height = frame[2] + 1
        heights[id(frame[0])] = height
        if stack:
            stack[-1][2] = max(stack[-1][2], height)


def _guard_input(raw):
    """Returns what the decoder may read: a bytes copy, or the caller's dict."""
    limit = codec.MAX_PDU_BYTES
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            octets = bytes(raw)          # one copy: a memoryview of any item size is its octets
        except (ValueError, TypeError, BufferError):      # a released memoryview
            raise Dis7Error(E_INPUT_TYPE, "$", "the buffer cannot be read") from None
        if len(octets) > limit:
            raise Dis7InputTooLarge("$", f"input is {len(octets)} octets; the limit is {limit}")
        return octets
    if isinstance(raw, str):
        size = len(raw.encode("utf-8", "surrogatepass"))   # never leaks UnicodeEncodeError
        if size > limit:
            raise Dis7InputTooLarge("$", f"input is {size} octets; the limit is {limit}")
        raise Dis7Error(E_INPUT_TYPE, "$", "text is not accepted; pass PDU octets or an envelope")
    if not isinstance(raw, dict):
        raise Dis7Error(E_INPUT_TYPE, "$", "pass PDU octets or an envelope object")
    _guard_depth(raw)
    return raw


_INPUT_BOUND_TEST = ("tests/test_cdm_input_bounds.py::"
                     "test_every_adapter_refuses_one_octet_over_its_declared_bound")
_REPLAY_ROOT = "[0].residual.data"
_SOURCE_FIELDS = ("system", "adapter", "adapter_version", "format_name", "format_version",
                  "synthetic", "original_id", "record_index", "observed_at", "source_hash",
                  "transformations")


class Dis7Adapter(Adapter):
    """One DIS 7 Entity State PDU to one Entity, and the original octets back."""

    name = "dis7"
    version = "1.0.0"
    direction = "bidirectional"
    system = "DIS7"
    metadata = AdapterMetadata(
        id="dis7",
        name="DIS 7 Entity State PDU",
        adapter_version="1.0.0",
        format=FormatRef(name="DIS", version="7 / IEEE 1278.1-2012 Entity State subset"),
        binding=WireBinding.STANDARD,
        direction=Direction.BIDIRECTIONAL,
        license_class=LicenseClass.LICENSED,
        maturity=Maturity(
            level=MaturityLevel.L4,
            basis="L4 ROUND-TRIP VERIFIED on this repository's own evidence. The harness's "
                  "`translate`, `schema` and `provenance` checks are PASS on every packaged "
                  "fixture (L1 to L3). The `lossless` column rests on the PATH-BOUND LEDGER: "
                  "`MAPPINGS` binds `pdu`, `wire_hex` and `time_context` of an envelope to "
                  "`residual.data` as residual subtrees and the ledger reports no LOST leaf. "
                  "`from_cdm(to_cdm(raw))` reproduces every byte fixture octet for octet under "
                  "the declared `bytes` tolerance (`ROUNDTRIP_TOLERANCE`), so `synapse "
                  "conformance run --adapter dis7` computes E = PASS with D on the ledger basis. "
                  "The adapter's own statement of the round-trip claim is "
                  "tests/test_cdm_dis7_adapter.py::test_t01_a01_vectors_replay_byte_exact. "
                  "L5 is NOT declared: the rung above L4 rests on `M` (streaming) being "
                  "inapplicable, and a rung passed vacuously is not a rung declared "
                  "(ARCHITECTURE.md §3.6, rule 4). No independent implementation has been "
                  "exercised for a published record and no certification is claimed.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest", "egress"],
            message_types=[
                "Entity State PDU (protocol version 7, PDU type 1, protocol family 1), "
                "144 octets plus 0 to 255 variable parameter records of 16 octets; ingest",
                "replay of the original octets from an unchanged Entity produced by this "
                "adapter; egress",
            ],
            limits=Limits(
                max_input_bytes=4224,
                max_depth=None,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_depth":
                        "octets are one PDU and never JSON text; the envelope is held to 16 "
                        "levels and acyclicity by the adapter's coded guard",
                    "max_objects":
                        "one payload is exactly one PDU and yields exactly one Entity; the "
                        "record count is fixed by the byte bound",
                    "max_decompressed_bytes":
                        "this adapter accepts no archived or compressed payload, so there is "
                        "no expansion to bound",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced by this adapter; every walk is linear "
                        "in an input the byte bound and the coded guard have already limited",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The Entity State subset this adapter accepts is 144 octets plus "
                            "at most 255 variable parameter records of 16 octets, which is "
                            "4224 octets (`MAX_PDU_BYTES`, `adapters/dis7_codec.py`); a longer "
                            "payload cannot be one PDU of this subset. This is an "
                            "IMPLEMENTATION CAP chosen for this subset and is NOT the format's "
                            "normative maximum."),
                        enforced_at=(
                            "the adapter's coded guard, installed on `to_cdm` after the class "
                            "statement, measures the payload first and refuses with "
                            "`E_INPUT_LIMIT`; behind it `Adapter.__init_subclass__` wraps the "
                            "same method with `enforce_input_bound` at class-definition time "
                            "(`adapter.py`, `_bind_input_bound`), and `decode_pdu` refuses the "
                            "same size again"),
                        test=_INPUT_BOUND_TEST,
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the envelope has a closed key set at every level and an unknown key is "
                "refused with `E_TWIN_SCHEMA`; octets this subset does not interpret (dead "
                "reckoning parameters, marking, variable parameter records) are kept as "
                "hexadecimal in the structured residual and replayed unchanged"),
        ),
        limitations=[
            "Entity State subset only: protocol version 7, PDU type 1, protocol family 1. "
            "Every other PDU type, protocol family and DIS version is refused, and no network "
            "transport, capture file or multi-PDU datagram is read",
            "no IEEE certification is claimed, and acceptance under this subset is not "
            "validation of every reserved bit of the standard",
            "the IEEE 1278.1-2012 text was not consulted: the layout authority is "
            "open-dis-python (https://github.com/open-dis/open-dis-python, BSD-2-Clause) at "
            "commit 732b6655bb47e34ccc73722eefe0f4706fd0032f. A comparison with it exists as "
            "an opt-in test and an exercise report; no report ships in the distribution",
            "the state instant is supplied by the caller with its basis; the DIS timestamp is "
            "preserved and never converted. Affiliation is UNKNOWN for every force ID, and "
            "velocity is projected only for dead reckoning algorithms 2 to 5",
            "egress replays the original octets of an unchanged Entity only; a fresh or "
            "edited Entity is refused",
            "`fixture_instance` supplies the packaged fixtures' context (session `unnamed`, "
            "synthetic, the vectors' state instant and basis) and refuses `synthetic=False`. "
            "The harness and the conformance suite construct through it, so their verdict is "
            "defined for the packaged fixtures only; PDUs from another exercise need a "
            "caller-built adapter",
            "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
            "untracked and unpackaged. `evidence.available` is false because no published "
            "Release carries this adapter's records yet; it becomes true at the first release "
            "that attaches them",
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    ROUNDTRIP_TOLERANCE = "bytes"

    MAPPINGS = {
        "pdu": lossless.Mapping("entity:residual.data.pdu", kind="residual"),
        "wire_hex": lossless.Mapping("entity:residual.data.wire_hex", kind="residual"),
        "time_context": lossless.Mapping("entity:residual.data.time_context", kind="residual"),
    }

    def __init__(self, clock=None, *, session=_MISSING, synthetic=_MISSING, time_context=None,
                 source_hash=None):
        if session is _MISSING:
            raise Dis7Error(E_CONTEXT_SESSION, "session", "the session is required")
        validate_session(session)
        if synthetic is _MISSING or type(synthetic) is not bool:
            raise Dis7Error(E_CONTEXT_SYNTHETIC, "synthetic",
                            "the synthetic flag is required and must be a boolean")
        if time_context is not None and not isinstance(time_context, TimeContext):
            raise Dis7Error(E_CONTEXT_TIME, "time_context",
                            "the time context is neither absent nor a TimeContext")
        _check_hash(source_hash, "source_hash", E_CONTEXT_HASH)
        super().__init__(clock=clock, synthetic=synthetic)
        self._session = session
        self._time_context = time_context
        self._digest = None if source_hash is None else source_hash["value"]

    @property
    def session(self):
        return self._session

    @property
    def synthetic(self):
        return self._synthetic

    @property
    def time_context(self):
        return self._time_context

    @property
    def source_hash(self):
        return None if self._digest is None else {"algorithm": "sha256", "value": self._digest}

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        """The packaged fixtures' context: these constants, never the clock (CR-21)."""
        if synthetic is not True:
            raise Dis7Error(E_CONTEXT_SYNTHETIC, "synthetic",
                            "the packaged fixtures' context is synthetic only")
        return cls(clock=clock, session=FIXTURE_SESSION, synthetic=True,
                   time_context=FIXTURE_TIME_CONTEXT)

    def to_cdm(self, raw):
        if isinstance(raw, bytes):
            pdu = codec.decode_pdu(raw)
            if self._time_context is None:
                raise Dis7Error(E_CONTEXT_TIME, "time_context",
                                "octets carry no state instant and the adapter has no time context")
            return [self._entity(pdu, raw.hex(), self._time_context, self._digest)]
        if isinstance(raw, dict):
            _check_envelope(raw)
            wire = bytes.fromhex(raw["wire_hex"])
            pdu = codec.decode_pdu(wire)
            difference = _twin_difference(raw["pdu"], pdu)
            if difference is not None:
                raise Dis7Error(E_TWIN_WIRE_MISMATCH, f"pdu.{difference}",
                                "the twin disagrees with the decoded wire")
            stated = raw["time_context"]
            context = TimeContext(stated["instant"], stated["basis"])
            own = self._time_context
            if own is not None:
                if own.instant != context.instant:
                    raise Dis7Error(E_CONTEXT_CONFLICT, "time_context.instant",
                                    "the envelope's instant differs from the adapter's")
                if own.basis != context.basis:
                    raise Dis7Error(E_CONTEXT_CONFLICT, "time_context.basis",
                                    "the envelope's basis differs from the adapter's")
            return [self._entity(pdu, wire.hex(), context, self._digest)]
        raise Dis7Error(E_INPUT_TYPE, "$", "pass PDU octets or an envelope object")

    def _entity(self, pdu, wire_hex, context, digest):
        """The canonical mapping of one decoded PDU (PLAN §4.4, stages 9 and 10)."""
        exercise = pdu["header"]["exercise_id"]
        original = external_id(pdu["entity_id"])
        algorithm = int(pdu["dead_reckoning_hex"][:2], 16)
        notes = ["DIS timestamp preserved; state instant supplied by caller: " + context.basis,
                 "Force ID preserved; affiliation UNKNOWN without exercise viewpoint."]
        try:
            projected = codec.ecef_to_geodetic(*pdu["position_ecef_m"])
            position = kinematics = None
            if projected is None:
                notes.append("Zero ECEF vector has no geodetic projection; retained, position "
                             "absent.")
            else:
                position = _assemble_position(*projected)
                notes.append("ECEF metres -> WGS84 degrees/HAE.")
                if algorithm in codec.WORLD_ALGORITHMS:
                    kinematics = Kinematics(**codec.velocity_to_kinematics(
                        pdu["velocity_mps"], projected[0], projected[1]))
                    notes.append("World-coordinate velocity -> local horizontal speed/course/up.")
                else:
                    notes.append(f"Dead reckoning algorithm {algorithm}: velocity retained "
                                 "without projection.")
            instant = _state_instant(self, context)
            stamp = self.source_ref()
            source = SourceRef(
                system=stamp.system, adapter=stamp.adapter, adapter_version=stamp.adapter_version,
                synthetic=stamp.synthetic, format_name=stamp.format_name,
                format_version=stamp.format_version, original_id=original,
                source_hash=None if digest is None else SourceHash(algorithm="sha256",
                                                                   value=digest),
                record_index=0, observed_at=instant, transformations=notes)
            residual = ResidualBlock(namespace=self.metadata.format.name, data={
                "pdu": pdu,
                "wire_hex": wire_hex,
                "time_context": {"instant": context.instant, "basis": context.basis},
                "session": self._session,
                "synthetic": self._synthetic,
                "source_hash": None if digest is None else {"algorithm": "sha256",
                                                            "value": digest},
            })
            return Entity(
                entity_id=entity_uuid(self._session, exercise, pdu["entity_id"]),
                source_ids=[SourceId(system=identity_system(self._session, exercise),
                                     external_id=original)],
                entity_type=EntityType.PLATFORM if pdu["entity_type"][0] == 1
                else EntityType.UNKNOWN,
                affiliation=_affiliation(pdu["force_id"]),
                position=position,
                kinematics=kinematics,
                valid_from=instant,
                valid_to=None,
                attributes={},
                ontology_types=[],
                source=source,
                residual=residual,
            )
        except pydantic.ValidationError:
            raise Dis7Error(E_PROJECTION, "$",
                            "the mapped Entity is not a valid CDM object") from None

    def from_cdm(self, objects):
        """The original octets of one unchanged Entity this adapter produced (PLAN §4.5)."""
        # Step 2: shape.
        if not isinstance(objects, list) or len(objects) != 1 \
                or type(objects[0]) is not Entity:
            raise Dis7Error(E_REPLAY_SHAPE, "$", "pass a list of exactly one Entity")
        entity = objects[0]
        fields = vars(entity)
        for name in Entity.model_fields:
            if name not in fields:
                raise Dis7Error(E_REPLAY_SHAPE, f"[0].{name}", "the Entity lacks a field")
        residual = fields["residual"]
        if not isinstance(residual, ResidualBlock) or "namespace" not in vars(residual) \
                or "data" not in vars(residual) or type(residual.namespace) is not str \
                or residual.namespace != self.metadata.format.name:
            raise Dis7Error(E_REPLAY_SHAPE, "[0].residual",
                            "the Entity carries no residual of this format")
        data = residual.data
        _check_residual(data, _REPLAY_ROOT)
        source = fields["source"]
        if not isinstance(source, SourceRef) \
                or any(name not in vars(source) for name in _SOURCE_FIELDS):
            raise Dis7Error(E_REPLAY_SHAPE, "[0].source", "the provenance is not a valid record")
        stored_pdu, stored_wire = data["pdu"], data["wire_hex"]
        stored_context, stored_hash = data["time_context"], data["source_hash"]
        stored_digest = None if stored_hash is None else stored_hash["value"]

        # Step 3: the stored context, needing no wire.
        if data["session"] != self._session:
            raise Dis7Error(E_REPLAY_PROVENANCE, f"{_REPLAY_ROOT}.session",
                            "the stored session differs from the adapter's")
        if data["synthetic"] is not self._synthetic:
            raise Dis7Error(E_REPLAY_PROVENANCE, f"{_REPLAY_ROOT}.synthetic",
                            "the stored classification differs from the adapter's")
        own = self._time_context
        if own is not None:
            if own.instant != stored_context["instant"]:
                raise Dis7Error(E_REPLAY_PROVENANCE, f"{_REPLAY_ROOT}.time_context.instant",
                                "the stored instant differs from the adapter's")
            if own.basis != stored_context["basis"]:
                raise Dis7Error(E_REPLAY_PROVENANCE, f"{_REPLAY_ROOT}.time_context.basis",
                                "the stored basis differs from the adapter's")
        if self._digest is not None and stored_digest != self._digest:
            raise Dis7Error(E_REPLAY_PROVENANCE, f"{_REPLAY_ROOT}.source_hash",
                            "the stored source hash differs from the adapter's")
        try:
            context = TimeContext(stored_context["instant"], stored_context["basis"])
        except Dis7Error as error:
            raise Dis7Error(E_REPLAY_PROVENANCE, f"{_REPLAY_ROOT}.{error.path}",
                            "the stored time context is not valid") from None
        if context.instant != stored_context["instant"]:
            raise Dis7Error(E_REPLAY_PROVENANCE, f"{_REPLAY_ROOT}.time_context.instant",
                            "the stored instant is not in its normalised form")

        # Step 4: the residual's consistency with its own wire.
        try:
            decoded = codec.decode_pdu(bytes.fromhex(stored_wire))
        except Dis7Error:
            raise Dis7Error(E_REPLAY_CHANGED, f"{_REPLAY_ROOT}.wire_hex",
                            "the stored wire is not one decodable PDU") from None
        difference = _twin_difference(stored_pdu, decoded)
        if difference is not None:
            raise Dis7Error(E_REPLAY_CHANGED, f"{_REPLAY_ROOT}.pdu.{difference}",
                            "the stored PDU disagrees with the stored wire")
        try:
            expected = self._entity(decoded, stored_wire, context, stored_digest)
        except Dis7Error:
            raise Dis7Error(E_REPLAY_CHANGED, f"{_REPLAY_ROOT}.wire_hex",
                            "the stored wire no longer maps to an Entity") from None

        # Step 5: the source block against the reconstruction.
        for name in _SOURCE_FIELDS:
            if not _canonical_equal(getattr(entity.source, name), getattr(expected.source, name)):
                raise Dis7Error(E_REPLAY_PROVENANCE, f"[0].source.{name}",
                                "the provenance differs from the stored record's")
        if not _canonical_equal(entity.source_ids, expected.source_ids):
            raise Dis7Error(E_REPLAY_PROVENANCE, "[0].source_ids",
                            "the source identities differ from the stored record's")

        # Step 6: every remaining canonical field.
        for name in Entity.model_fields:
            if name in ("source", "source_ids", "residual"):
                continue
            if not _canonical_equal(getattr(entity, name), getattr(expected, name)):
                raise Dis7Error(E_REPLAY_CHANGED, f"[0].{name}",
                                "the Entity was edited after translation")
        return _replay_bytes(stored_wire)

    def detect(self, raw):
        """Cheap and bounded; never raises (CR-28)."""
        try:
            if isinstance(raw, (bytes, bytearray, memoryview)):
                size = raw.nbytes if isinstance(raw, memoryview) else len(raw)
                if size > codec.MAX_PDU_BYTES:
                    return False
                return codec.looks_like_entity_state(bytes(raw))
            if isinstance(raw, dict):
                if len(raw) != len(_ENVELOPE_KEYS) or any(key not in raw for key in _ENVELOPE_KEYS):
                    return False
                _guard_depth(raw)
                pdu = raw["pdu"]
                if not isinstance(pdu, dict) or not isinstance(pdu.get("header"), dict):
                    return False
                header = pdu["header"]
                for key, want in (("protocol_version", 7), ("pdu_type", 1),
                                  ("protocol_family", 1)):
                    value = header.get(key)
                    if not _is_integer(value) or value != want:
                        return False
                return True
            return False
        except Exception:
            return False

    def validate_source(self, raw):
        """`[]`, or exactly one `"CODE at PATH: message"` string (CR-31)."""
        try:
            self.to_cdm(raw)
        except Dis7Error as error:
            return [str(error)]
        return []


_sdk_to_cdm = Dis7Adapter.to_cdm          # the SDK wrapper; its __wrapped__ is the method above


@functools.wraps(_sdk_to_cdm)
def _guarded_to_cdm(self, raw):
    return _sdk_to_cdm(self, _guard_input(raw))


Dis7Adapter.to_cdm = _guarded_to_cdm
