"""UTC timestamps of the profile as integer microseconds: parsed and written by explicit code.

WHY NOT datetime OR THE SCHEMA
------------------------------
Every timestamp the profile reads or writes has one form, `YYYY-MM-DDTHH:MM:SS.ffffffZ` (six
fractional digits; three in the CDM's `valid_from`), in calendar years 1970 through 9998 (R08).
The schemas say `format: date-time`, which the installed jsonschema does not check at all
(OPS-03), and `datetime.strptime` accepts one to six fractional digits, years before 1970 and
Unicode digits. So the form is matched here digit by digit, the date is checked against the real
calendar (the Gregorian leap rule, no 24:00, no leap second), and the instant becomes an integer
count of microseconds since 1970-01-01T00:00:00Z. Arithmetic on it stays integral, as lead ruling
CR-L05 requires: effective time is epoch plus elapsed nanoseconds integer-divided by 1000, with
no float seconds anywhere and no overflow error to catch.
"""

from __future__ import annotations

import re

#: The only accepted form. `[0-9]` and not `\d`: Python's `\d` also matches other scripts' digits.
_FORM = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
                   r"\.([0-9]{6})Z")
#: The CDM's form of the same instant, three fractional digits (`valid_from`, R32). Only the
#: projector's check of its own output reads it.
_FORM_MILLISECOND = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):"
                               r"([0-9]{2})\.([0-9]{3})Z")

MIN_YEAR = 1970
MAX_YEAR = 9998

MICROSECONDS_PER_SECOND = 1_000_000
SECONDS_PER_DAY = 86_400
_MICROSECONDS_PER_DAY = SECONDS_PER_DAY * MICROSECONDS_PER_SECOND

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if month == 2 and is_leap_year(year):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def days_from_civil(year: int, month: int, day: int) -> int:
    """Days from 1970-01-01 to the given proleptic Gregorian date (negative before it).

    The era arithmetic of H. Hinnant's `days_from_civil`: shift the year to start in March so the
    leap day is last, count whole 400-year eras of 146097 days, then days within the era.
    """
    year -= 1 if month <= 2 else 0
    era = (year if year >= 0 else year - 399) // 400
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def civil_from_days(days: int) -> tuple[int, int, int]:
    """The inverse of `days_from_civil`: (year, month, day) of a day count from 1970-01-01."""
    days += 719468
    era = (days if days >= 0 else days - 146096) // 146097
    day_of_era = days - era * 146097
    year_of_era = (day_of_era - day_of_era // 1460 + day_of_era // 36524
                   - day_of_era // 146096) // 365
    day_of_year = day_of_era - (365 * year_of_era + year_of_era // 4 - year_of_era // 100)
    shifted_month = (5 * day_of_year + 2) // 153
    day = day_of_year - (153 * shifted_month + 2) // 5 + 1
    month = shifted_month + (3 if shifted_month < 10 else -9)
    year = year_of_era + era * 400 + (1 if month <= 2 else 0)
    return year, month, day


#: 1970-01-01T00:00:00.000000Z.
MIN_MICROSECOND = 0
#: 9998-12-31T23:59:59.999999Z, the last instant an externally assigned effective time may name
#: (SPEC:289): one microsecond before the first day of year 9999.
MAX_MICROSECOND = days_from_civil(MAX_YEAR + 1, 1, 1) * _MICROSECONDS_PER_DAY - 1


def parse_microsecond(text: str) -> int:
    """Microseconds since 1970-01-01T00:00:00Z of `text`, or ValueError if it is not one.

    Refused: any other form, a month or day the calendar does not have, an hour above 23, a
    minute or second above 59, and a year outside 1970-9998. A non-str is a caller bug
    (TypeError).
    """
    return _parsed(text, _FORM, 1, "not of the form YYYY-MM-DDTHH:MM:SS.ffffffZ")


def parse_millisecond(text: str) -> int:
    """Microseconds since 1970-01-01T00:00:00Z of a `YYYY-MM-DDTHH:MM:SS.fffZ` text.

    The CDM's timestamp form (R32's valid_from), with the same calendar and year rules as
    `parse_microsecond`; the result is a whole number of milliseconds, in microseconds.
    """
    return _parsed(text, _FORM_MILLISECOND, 1000, "not of the form YYYY-MM-DDTHH:MM:SS.fffZ")


def _parsed(text: str, form: re.Pattern, unit: int, form_message: str) -> int:
    if type(text) is not str:
        raise TypeError("a timestamp is a str")
    match = form.fullmatch(text)
    if match is None:
        raise ValueError(form_message)
    year, month, day, hour, minute, second, digits = (int(g) for g in match.groups())
    fraction = digits * unit
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError("the year is outside 1970-9998")
    if not 1 <= month <= 12:
        raise ValueError("there is no such month")
    if not 1 <= day <= days_in_month(year, month):
        raise ValueError("the month has no such day")
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("there is no such time of day")
    seconds = days_from_civil(year, month, day) * SECONDS_PER_DAY + hour * 3600 + minute * 60
    return (seconds + second) * MICROSECONDS_PER_SECOND + fraction


def _fields(microsecond: int) -> tuple[int, int, int, int, int, int, int]:
    if type(microsecond) is not int:
        raise TypeError("an instant is an int count of microseconds")
    if not MIN_MICROSECOND <= microsecond <= MAX_MICROSECOND:
        raise ValueError("the instant is outside 1970-01-01 to 9998-12-31")
    days, within = divmod(microsecond, _MICROSECONDS_PER_DAY)
    seconds, fraction = divmod(within, MICROSECONDS_PER_SECOND)
    year, month, day = civil_from_days(days)
    return year, month, day, seconds // 3600, seconds // 60 % 60, seconds % 60, fraction


def format_microsecond(microsecond: int) -> str:
    """`YYYY-MM-DDTHH:MM:SS.ffffffZ` of an instant inside 1970-9998 (ValueError outside)."""
    year, month, day, hour, minute, second, fraction = _fields(microsecond)
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{fraction:06d}Z"


def format_millisecond(microsecond: int) -> str:
    """`YYYY-MM-DDTHH:MM:SS.fffZ`: the instant truncated, never rounded, to milliseconds.

    CR-L05: the CDM's valid_from keeps three fractional digits, cut from the six.
    """
    year, month, day, hour, minute, second, fraction = _fields(microsecond)
    millis = fraction // 1000
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{millis:03d}Z"
