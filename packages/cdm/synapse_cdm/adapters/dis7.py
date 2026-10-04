"""DIS 7 Entity State PDU <-> CDM `Entity`: caller time context, session rule, identity.
Adapter #21.

So far this module holds the caller-supplied time context (`TimeContext`), the session rule
(`validate_session`) and the identity derivation (`external_id`, `identity_system`,
`entity_uuid`). The translating class is not in it yet, so nothing here is registered.
"""
from __future__ import annotations

import dataclasses
import datetime
import re
import uuid

from synapse_cdm import ids
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

__all__ = [
    "BASIS_WHITESPACE", "TimeContext", "validate_session",
    "external_id", "identity_system", "entity_uuid",
    "Dis7Error", "Dis7InputTooLarge", "Dis7InputTooDeep", "CODES",
    "E_INPUT_TYPE", "E_INPUT_LIMIT", "E_CONTEXT_SESSION", "E_CONTEXT_SYNTHETIC",
    "E_CONTEXT_TIME", "E_CONTEXT_CONFLICT", "E_CONTEXT_HASH", "E_HEADER_UNSUPPORTED",
    "E_LENGTH_MISMATCH", "E_NONFINITE", "E_TWIN_SCHEMA", "E_TWIN_WIRE_MISMATCH",
    "E_VALUE_RANGE", "E_POSITION_DOMAIN", "E_PROJECTION", "E_REPLAY_SHAPE",
    "E_REPLAY_PROVENANCE", "E_REPLAY_CHANGED",
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
    if not isinstance(instant, str):
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
    if not isinstance(basis, str):
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


def validate_session(value: object) -> str:
    """Return `value` itself if it is 1 to 128 ASCII letters, digits, dots, underscores or hyphens."""
    if not isinstance(value, str) or _SESSION.fullmatch(value) is None:
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
