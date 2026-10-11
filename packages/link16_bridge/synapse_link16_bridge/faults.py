"""Named fault points, selectable by constructor only (the crash tests R01-R03 and REQ151).

The code calls `faults.hit(name)` at each named point and `faults.flag(name)` where a fault is a
condition rather than a crash. The production object, `NO_FAULTS`, does nothing. A test passes a
`CrashPoints` naming the points that crash (raising `SimulatedCrash`, a `BaseException` so that no
`except Exception` swallows it, or calling `os._exit(137)` in the process-level variant) and the
flags that hold. No environment variable and no configuration key selects a fault point.
"""
from __future__ import annotations

import os
from typing import Iterable

#: Points where a crash can be injected.
CRASH_POINTS = (
    "ingest.after_raw_store",
    "ingest.before_commit",
    "ingest.after_commit_before_ack",
    "ingest.after_ack",
    "outbox.before_mark_dispatched",
    "egress.after_job_commit_before_send",
    "egress.after_send_before_record",
)
#: Conditions a test can switch on: the lease expires at the next check, and a durable commit
#: fails (`sqlite3.OperationalError` raised in place of COMMIT).
FLAGS = ("lease.expire_now", "store.commit_fails")


class SimulatedCrash(BaseException):
    """A process death simulated in process. Never caught by the bridge."""

    def __init__(self, point: str) -> None:
        self.point = point
        super().__init__(f"simulated crash at {point}")


class CrashPoints:
    """`crash`: the points that crash; `exit_process`: crash by `os._exit(137)` instead of raising;
    `flags`: the conditions that hold. Unknown names are refused at construction."""

    def __init__(self, crash: Iterable[str] = (), *, flags: Iterable[str] = (),
                 exit_process: bool = False) -> None:
        self.crash = frozenset(crash)
        self.flags = set(flags)
        unknown = (self.crash - set(CRASH_POINTS)) | (self.flags - set(FLAGS))
        if unknown:
            raise ValueError("unknown fault point name")
        self.exit_process = exit_process
        self.hits: list[str] = []

    def hit(self, name: str) -> None:
        if name not in CRASH_POINTS:
            raise ValueError("unknown crash point name")
        self.hits.append(name)
        if name in self.crash:
            if self.exit_process:
                os._exit(137)
            raise SimulatedCrash(name)

    def flag(self, name: str) -> bool:
        if name not in FLAGS:
            raise ValueError("unknown fault flag name")
        return name in self.flags

    def clear(self, name: str) -> None:
        self.flags.discard(name)


class _NoFaults(CrashPoints):
    def hit(self, name: str) -> None:
        return None

    def flag(self, name: str) -> bool:
        return False


#: The production fault object: every point is a no-op.
NO_FAULTS = _NoFaults()
