"""The application reconnect backoff of REQ114, with the clock and the random source injected.

Delays 1, 2, 4, 8, 16, then 30 seconds for every later failure, each multiplied by a factor drawn
uniformly from [0.8, 1.2] (plus or minus 20 percent). The schedule restarts at 1 second once the
service has been stable for 60 seconds: the first failure after 60 seconds or more of success
starts again from the first step. Protocol retries, deadlines and sequence rollover of a native
transport come from its standard and are not this schedule (BLOCKED_EXTERNAL_EVIDENCE).
"""
from __future__ import annotations

import random

from synapse_link16_bridge.clock import Clock, now_ms

SCHEDULE = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
JITTER = 0.2
STABLE_RESET_SECONDS = 60.0


class Backoff:
    def __init__(self, clock: Clock, rng: random.Random) -> None:
        self._clock = clock
        self._rng = rng
        self._step = 0
        self._stable_since: int | None = None

    def success(self) -> None:
        """A successful exchange: start (or continue) the stable period."""
        if self._stable_since is None:
            self._stable_since = now_ms(self._clock)

    def failure(self) -> float:
        """A failed exchange: the next delay in seconds."""
        now = now_ms(self._clock)
        if self._stable_since is not None and \
                now - self._stable_since >= STABLE_RESET_SECONDS * 1000:
            self._step = 0
        self._stable_since = None
        base = SCHEDULE[min(self._step, len(SCHEDULE) - 1)]
        self._step += 1
        return base * self._rng.uniform(1.0 - JITTER, 1.0 + JITTER)

    @property
    def step(self) -> int:
        return self._step
