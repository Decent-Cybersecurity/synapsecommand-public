"""REQ114: the application reconnect backoff — 1, 2, 4, 8, 16, then 30 s, uniform jitter of
plus or minus 20 percent, reset after 60 s of stable service, clock and random source injected."""
import random

import pytest

from synapse_link16_bridge.backoff import Backoff
from synapse_link16_bridge.clock import ManualClock


class Edge:
    """A random source that always draws one end of the interval."""

    def __init__(self, high: bool) -> None:
        self.high = high

    def uniform(self, low: float, high: float) -> float:
        return high if self.high else low


@pytest.mark.parametrize("high, expected", [
    (False, [0.8, 1.6, 3.2, 6.4, 12.8, 24.0, 24.0, 24.0]),
    (True, [1.2, 2.4, 4.8, 9.6, 19.2, 36.0, 36.0, 36.0]),
])
def test_schedule_1_2_4_8_16_30_with_jitter_bounds(high, expected):
    backoff = Backoff(ManualClock(), Edge(high))
    assert [round(backoff.failure(), 9) for _ in expected] == expected


def test_seeded_draws_stay_within_twenty_percent_of_the_schedule():
    backoff = Backoff(ManualClock(), random.Random(20261011))
    bases = [1, 2, 4, 8, 16] + [30] * 45
    for base in bases:
        delay = backoff.failure()
        assert base * 0.8 <= delay <= base * 1.2


def test_reset_after_60_seconds_stable():
    clock = ManualClock()
    backoff = Backoff(clock, Edge(False))
    assert [backoff.failure() for _ in range(3)] == [0.8, 1.6, 3.2]
    backoff.success()
    clock.advance(59.999)
    assert backoff.failure() == 6.4            # not yet stable for 60 s: the schedule continues
    backoff.success()
    clock.advance(60)
    assert backoff.failure() == 0.8            # 60 s of stable service: back to the first step
    assert backoff.step == 1


def test_a_failure_with_no_success_in_between_never_resets():
    clock = ManualClock()
    backoff = Backoff(clock, Edge(True))
    backoff.failure()
    clock.advance(3600)
    assert backoff.failure() == 2.4
