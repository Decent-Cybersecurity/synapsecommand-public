"""Module-level synthetic adapters for the parser-isolation tests (audit remediation F03).

They live in a module of their own, and not inside `tests/test_cdm_parser_isolation.py`, because
the conformance suite's parser worker is a SPAWNED process: it receives the adapter as a
`module:ClassName` reference and imports it, and a class defined inside a test function has no
importable name. Every class here behaves normally except on a payload that carries its MARKER,
so one fixture directory can hold the case that provokes the failure and a second, ordinary case
that proves the worker ran on after it.

Each misbehaviour is SELF-LIMITED. `NeverReturns` really does not return and really does ignore
SIGTERM — that is what proves the `terminate() → kill()` escalation — but it gives up after
`SELF_LIMIT_S` seconds, so a defect in the harness under test cannot leave a process behind that
outlives the test session. The limit is well above every deadline the tests configure and is
never what the assertions measure.
"""

from __future__ import annotations

import multiprocessing
import os
import signal
import time

from synapse_cdm import ids
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import Affiliation, EntityType
from synapse_cdm.models import Entity

from tests import probe_metadata

#: The byte sequence (or dict key) that makes an adapter misbehave. Everything else is refused.
MARKER = b"PROVOKE"

#: How long a "never returning" parser is allowed to not return before it exits on its own.
SELF_LIMIT_S = 30.0

#: What `HardCrashing` exits with, so the test can assert the worker's death was the one provoked.
CRASH_EXIT_CODE = 3


def _provoked(raw) -> bool:
    if isinstance(raw, dict):
        return bool(raw.get("provoke"))
    return MARKER in bytes(raw)


class Normal(Adapter):
    """Returns one entity for a provoked payload and refuses everything else with ValueError."""

    name = "synthetic-normal"
    version = "0.1.0"
    direction = "ingest"
    system = "synthetic"
    metadata = probe_metadata("synthetic-normal")

    def to_cdm(self, raw):
        if not _provoked(raw):
            raise ValueError("not a payload this synthetic adapter accepts")
        return [Entity(
            entity_id=ids.derive(self.system, "provoked", kind="entity"),
            source_ids=[{"system": self.system, "external_id": "provoked"}],
            entity_type=EntityType.UNKNOWN, affiliation=Affiliation.UNKNOWN,
            valid_from=self.now(), source=self.source_ref(),
        )]


class Refusing(Normal):
    """Refuses every payload with an ordinary exception: the expected, controlled outcome."""

    name = "synthetic-refusing"
    metadata = probe_metadata("synthetic-refusing")

    def to_cdm(self, raw):
        raise ValueError("refused on purpose")


class HardCrashing(Normal):
    """Takes the whole worker process down on a provoked payload — no exception to catch."""

    name = "synthetic-hard-crashing"
    metadata = probe_metadata("synthetic-hard-crashing")

    def to_cdm(self, raw):
        if _provoked(raw):
            os._exit(CRASH_EXIT_CODE)
        raise ValueError("refused")


class Slow(Normal):
    """Returns, but only after `delay_s`: exceeds a short deadline and honours SIGTERM."""

    name = "synthetic-slow"
    metadata = probe_metadata("synthetic-slow")
    delay_s = 2.0

    def to_cdm(self, raw):
        if _provoked(raw):
            time.sleep(self.delay_s)
        raise ValueError("refused, eventually")


class NeverReturns(Normal):
    """Ignores SIGTERM and never returns on a provoked payload (until its own self-limit)."""

    name = "synthetic-never-returns"
    metadata = probe_metadata("synthetic-never-returns")

    def to_cdm(self, raw):
        if _provoked(raw):
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            give_up = time.monotonic() + SELF_LIMIT_S
            while time.monotonic() < give_up:
                time.sleep(0.05)
            os._exit(99)
        raise ValueError("refused")


class LoudRefusing(Normal):
    """Refuses with a message far past the worker's output cap: the class must still arrive."""

    name = "synthetic-loud-refusing"
    metadata = probe_metadata("synthetic-loud-refusing")

    def to_cdm(self, raw):
        raise ValueError("x" * 1_000_000)


class InitFailing(Normal):
    """Cannot be constructed in a WORKER: the failure is the worker's start-up, not a parse.

    Constructing it in the test process succeeds, so the check can be handed an instance; the
    spawned interpreter is where it raises — the shape of an adapter that needs something the
    fresh process does not have."""

    name = "synthetic-init-failing"
    metadata = probe_metadata("synthetic-init-failing")

    def __init__(self, clock=None, *, synthetic=True):
        if multiprocessing.parent_process() is not None:
            raise RuntimeError("this adapter refuses to initialise in a worker")
        super().__init__(clock, synthetic=synthetic)


#: F06: what `MemoryHog` reserves on a provoked payload, in one `mmap` chunk at a time. Anonymous,
#: untouched pages: the reservation counts against `RLIMIT_AS` without a byte of it being written,
#: so the double costs address space and no memory wherever the limit is NOT enforced.
HOG_TOTAL_BYTES = 4 << 30
HOG_CHUNK_BYTES = 256 << 20

#: F06: how long `Spinning` burns CPU on a provoked payload before giving up on its own. Longer
#: than any CPU limit a test sets, shorter than the test's budget.
SPIN_LIMIT_S = 12.0


class CpuLimitReporting(Normal):
    """Refuses to initialise in a WORKER, with the worker's `RLIMIT_CPU` pair in the refusal.

    `suite._worker_main` applies the resource envelope BEFORE it constructs the adapter, so the
    pair this constructor reads is the pair `_apply_resource_limits` set — S10's `(value,
    value + 1)`, soft below hard so Linux sends `SIGXCPU` and not `SIGKILL` — and the init-error
    reply carries it to the parent on every platform that has `RLIMIT_CPU`, enforced or not.
    Constructs normally in the test process (`tests/test_cdm_resource_envelope.py`)."""

    name = "synthetic-cpu-limit-reporting"
    metadata = probe_metadata("synthetic-cpu-limit-reporting")

    def __init__(self, clock=None, *, synthetic=True):
        if multiprocessing.parent_process() is not None:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
            raise RuntimeError(f"RLIMIT_CPU soft={soft} hard={hard}")
        super().__init__(clock, synthetic=synthetic)


class MemoryHog(Normal):
    """Reserves `HOG_TOTAL_BYTES` of address space on a provoked payload, then answers normally.

    An allocator refusing under `RLIMIT_AS` is `ENOMEM`, which `mmap` surfaces as `OSError`;
    the double re-raises it as `MemoryError`, the crash class an oversubscribed interpreter
    raises on its own, so the worker reads what a real parser exhausting its envelope would
    produce. Where nothing enforces the limit the reservation succeeds, the payload is ACCEPTED,
    and the test that wanted a crash fails clearly instead of passing by accident.
    """

    name = "synthetic-memory-hog"
    metadata = probe_metadata("synthetic-memory-hog")

    def to_cdm(self, raw):
        if _provoked(raw):
            import errno
            import mmap
            held = []
            try:
                while len(held) * HOG_CHUNK_BYTES < HOG_TOTAL_BYTES:
                    held.append(mmap.mmap(-1, HOG_CHUNK_BYTES))
            except OSError as e:
                if e.errno == errno.ENOMEM:
                    raise MemoryError(f"address space exhausted after "
                                      f"{len(held) * HOG_CHUNK_BYTES} bytes") from e
                raise
            finally:
                for region in held:
                    region.close()
        return super().to_cdm(raw)


class Spinning(Normal):
    """Burns CPU for `SPIN_LIMIT_S` on a provoked payload — a live loop, not a sleep — so a CPU
    limit has something to end. Answers normally afterwards where nothing ends it."""

    name = "synthetic-spinning"
    metadata = probe_metadata("synthetic-spinning")

    def to_cdm(self, raw):
        if _provoked(raw):
            give_up = time.monotonic() + SPIN_LIMIT_S
            counter = 0
            while time.monotonic() < give_up:
                counter += 1
        return super().to_cdm(raw)
