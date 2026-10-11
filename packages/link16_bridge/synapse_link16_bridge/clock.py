"""Time, waiting and chance, each injected.

Every time the bridge reads goes through one wall clock (`synapse_cdm.times.Clock`, a callable
returning an aware UTC datetime), every wait through one sleeper, and every random draw through
one `random.Random`. Tests pass `ManualClock`, `RecordingSleeper` and a seeded `Random`, so ages,
expiry, retention, lease expiry and backoff are asserted as values, never measured.

The store keeps instants as integer UTC milliseconds; the API edge speaks the contract's
`YYYY-MM-DDTHH:mm:ss.sssZ`.
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Callable

from synapse_cdm import times
from synapse_cdm.adapters.link16_gateway import instant

#: The wall clock type: a callable returning an aware UTC datetime.
Clock = times.Clock
#: A sleeper: called with a number of seconds.
Sleeper = Callable[[float], None]

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def ms(stamp: _dt.datetime) -> int:
    """An aware datetime as integer UTC milliseconds (sub-millisecond parts truncated)."""
    delta = times.parse(stamp) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def from_ms(value: int) -> _dt.datetime:
    """Integer UTC milliseconds as an aware datetime."""
    return _EPOCH + _dt.timedelta(milliseconds=value)


def render_ms(value: int) -> str:
    """Integer UTC milliseconds in the contract's timestamp form."""
    return times.render(from_ms(value))


def parse_ms(text: str, path: str = "timestamp") -> int:
    """A contract timestamp (strict calendar, ASCII digits) as integer UTC milliseconds.

    Raises the adapter's `Link16GatewayRefusal` (TIME_UNRESOLVED) on a malformed instant."""
    return ms(instant(text, path))


def now_ms(clock: Clock) -> int:
    return ms(clock())


class ManualClock:
    """A clock that moves only when told to. `advance(seconds)` and `set(datetime)`."""

    def __init__(self, start: _dt.datetime | None = None) -> None:
        self._now = start or _dt.datetime(2026, 10, 4, 12, 0, 0, tzinfo=_dt.timezone.utc)

    def __call__(self) -> _dt.datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + _dt.timedelta(seconds=seconds)

    def set(self, stamp: _dt.datetime) -> None:
        self._now = times.parse(stamp)


class RecordingSleeper:
    """A sleeper that records the delays it is asked for and does not wait."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def real_sleeper(seconds: float) -> None:
    """The production sleeper."""
    if seconds > 0:
        time.sleep(seconds)
