"""The Synapse Conformance Suite — fifteen checks, A through O, over one adapter.

WHY A SECOND MODULE AND NOT A SIXTH COLUMN IN THE HARNESS
---------------------------------------------------------
`harness.py` judges an adapter FIXTURE BY FIXTURE: it replays every payload and reports six
verdicts per payload. That shape is right for what it does and wrong for what §17 asks for.
A conformance claim is a statement about an ADAPTER — "this adapter is deterministic", "this
adapter refuses malformed input" — and several of the nine new checks cannot be expressed per
fixture at all: G decodes one payload three times, H reads a directory the harness deliberately
cannot see, K decodes twice through two fresh instances, N feeds bytes no fixture contains.

So the harness stays the engine for A–F and is not rewritten. This module composes it: it calls
`harness.run` once, folds its per-fixture verdicts into six adapter-level ones, and implements
G–O beside them. `harness.py`'s own JSON gained exactly one key for it (`check_letters`) and its
text output was untouched, because `cdm-harness --json` has consumers and this is an addition to
a published surface rather than a re-keying of it. (A second added key, `roundtrip`, arrived on
2026-09-16 with the byte-exact round-trip comparison, on the same rule: added beside, never
re-keyed, and the text report gained a block only for an adapter that emits.)

THE ONE RULE THIS MODULE EXISTS TO KEEP
---------------------------------------
A check that did not run is SKIP, never PASS (ARCHITECTURE.md §4.7, §3.6 rule 5). Every SKIP
here carries the reason it was inapplicable, and every check entry carries
`declared_inapplicable` — the second half of the pair §3.6 rule 5 requires the eligibility layer
to read. An adapter is not credited for a rung nobody climbed, and it is not blocked by one that
does not exist for it (§3.6 rule 4): the difference between those two is the whole model, and it
is a boolean in the report rather than a judgement in a reader's head.

WHAT IS DELIBERATELY NOT ASSERTED, AND WHY
------------------------------------------
Two rules that read well in a specification are not sound as written against an INJECTED FROZEN
CLOCK, and stating that here is cheaper than a reader rediscovering it from a green report:

1. "a timestamp equal to the frozen clock came from `now()`" is false in this tree — `cat048`'s
   `fspec_longer_than_necessary` fixture carries I048/140 = 22500.0 s = 06:15:00 exactly, which
   IS the frozen instant and IS a source time. J therefore tests the property §27 actually
   forbids, by DIFFERENTIAL: decode the payload under a second, different clock and see whether
   the timestamp moves. One that moves came from `now()`; §27 permits that only where the object
   says so, and every one in this tree does (`payload.observed_at_basis`).
2. `observed_at <= received_at` compares a scenario's source time against a TEST PARAMETER when
   the clock is frozen, and three adapters' fixtures legitimately observe after 06:15. The
   comparison is made only where `received_at` is not the injected instant, and the number of
   objects exempted is reported rather than silently dropped.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as _dt
import json
import multiprocessing
import pathlib
import sys
import time
import uuid
from typing import Any

from synapse_cdm import canonical as _canonical
from synapse_cdm import harness, lossless, manifest, times, version
from synapse_cdm.adapter import (Adapter, is_shipped, load_adapter, packaged_fixtures, roster,
                                 shipped)
from synapse_cdm.manifest import UnknownFields
from synapse_cdm.version import PACKAGE_VERSION, SCHEMA_VERSION

PASS, FAIL, SKIP = harness.PASS, harness.FAIL, harness.SKIP

#: §40's four, spelled as `conformance.EXIT_OK`–`EXIT_INTERNAL` and `harness.EXIT_NO_FIXTURES`
#: spell them, so a caller who knows one tool's codes is not surprised by this one's.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

#: The subdirectory H reads. A SUBDIRECTORY and not a naming convention, because
#: `harness.select_fixtures` selects "immediate children of the directory that are FILES"
#: (`harness.FIXTURE_PATTERN`) — so every payload in here is invisible to A–F by construction
#: rather than by an exclusion somebody has to remember to keep in step.
MALFORMED_DIR = "malformed"

#: §21's bound on one refusal. A malformed payload that has not been refused in five seconds has
#: not been refused. Since the audit remediation's F03 (2026-09-19) the bound is ENFORCED: H and
#: N hand every adversarial payload to a spawned worker process (`ParserWorker`) and a case that
#: has not answered within this many seconds is killed — `terminate()`, `KILL_GRACE_S`, then
#: `kill()` — and recorded as `PARSER_TIMEOUT`, which is a FAIL and never a refusal. Until then
#: the check measured the wall clock after `to_cdm` returned, which reads a slow parser and
#: cannot read one that never returns: the sweep hung before any verdict existed.
DEFAULT_TIMEOUT_S = 5.0

#: F03's bound on the worker's own start-up: spawning the interpreter, importing the package,
#: resolving the adapter and constructing it once. A worker that has not said `ready` by then is
#: killed and every case it would have run is `WORKER_INIT_FAILED`.
DEFAULT_STARTUP_TIMEOUT_S = 30.0

#: How long `terminate()` is given before `kill()`. A parser that ignores SIGTERM meets SIGKILL
#: this many seconds later; the documented worst case for one case is therefore
#: `timeout_s + KILL_GRACE_S` plus the reap.
KILL_GRACE_S = 1.0

#: After this many killed or dead workers in one check the remaining cases are not run and are
#: counted in `cases_not_run`. The check has FAILED by then regardless; the cap keeps a sweep
#: over a parser that hangs on every offset from costing `offsets × timeout_s`.
DEFAULT_MAX_WORKER_RESTARTS = 8

#: The most bytes one message across the worker pipe may carry, either direction. The worker
#: never sends objects — a count, class names and a clipped message — and the parent reads with
#: `recv_bytes(maxlength=...)`, so an adapter that raises with a megabyte in its message cannot
#: make the harness hold it.
OUTPUT_CAP_BYTES = 4096

#: What the canonical evidence names as the isolation mechanism. `spawn` and not `fork`: fork is
#: unsafe after threads and `spawn` is the one start method macOS, Linux and Windows share.
ISOLATION = "spawn-subprocess"


class UnsupportedResourceLimit(ValueError):
    """A memory or CPU limit was REQUESTED and this platform cannot enforce it (F06).

    Raised before any worker is spawned, so a caller who asked for a guarantee is told plainly
    that they are not getting one — never a silent best effort, never a limit that reads as set
    in the report and holds nothing. The reasons are `resource_limit_support()`'s, per field.
    """


@dataclasses.dataclass(frozen=True)
class ResourceLimits:
    """The envelope a caller may ask the parser worker to run inside (F06, 2026-09-20).

    `memory_bytes` is applied as `RLIMIT_AS` (soft == hard) and `cpu_seconds` as `RLIMIT_CPU`
    with the hard limit ONE SECOND above the soft one, in the child before the adapter is
    imported. The gap is deliberate (S10, 2026-09-20): Linux's `check_process_timers` tests the
    hard CPU limit first and sends `SIGKILL`, and only a soft limit BELOW the hard one delivers
    `SIGXCPU`, so `(value, value)` would end the worker with -9 and the evidence would name the
    wrong signal; `(value, value + 1)` is SIGXCPU at the soft limit with SIGKILL one second later
    as the backstop. Neither is portable, and the package does
    not pretend otherwise: `resource_limit_support()` says what THIS platform enforces, and a
    request the platform cannot honour is refused by `ParserWorker` with
    `UnsupportedResourceLimit`. The default is no limit at all, which is what the report shows
    when none was requested — a limit that was not asked for is not written into the evidence.
    """

    memory_bytes: int | None = None
    cpu_seconds: int | None = None

    def requested(self) -> dict[str, int]:
        """The fields a caller actually set, in the report's key order."""
        return {name: value for name, value in (("memory_bytes", self.memory_bytes),
                                                ("cpu_seconds", self.cpu_seconds))
                if value is not None}

    def validate(self) -> None:
        """Refuse, clearly, any requested field this platform cannot enforce."""
        support = resource_limit_support()
        for name, value in self.requested().items():
            if value <= 0:
                raise UnsupportedResourceLimit(f"{name}={value}: a limit is a positive number")
            enforced, reason = support[name]
            if not enforced:
                raise UnsupportedResourceLimit(
                    f"{name}={value} was requested and this platform ({sys.platform}) cannot "
                    f"enforce it: {reason}. Refused rather than applied as a best effort — the "
                    f"conformance worker's isolation is `{ISOLATION}` with a per-case deadline on "
                    f"every platform, and the memory/CPU envelope is the hosting application's "
                    f"here (a container or cgroup limit, a job object, a VM)")


def resource_limit_support() -> dict[str, tuple[bool, str]]:
    """What this platform can enforce of `ResourceLimits`, per field: `(enforced, reason)`.

    Decided from the platform and not from a probe, because the probe that would settle it —
    reserve past the limit and see — costs address space at every worker start. The readings
    that decided the two `False` rows for macOS were taken on 2026-09-20 (macOS 26.5.2, CPython
    3.14.7, a spawned child): `setrlimit(RLIMIT_AS)` and `setrlimit(RLIMIT_DATA)` raised
    `ValueError: current limit exceeds maximum limit` for 64 MiB, 512 MiB and 2 GiB alike while
    the limit read back as infinite, and a 4 GiB reservation succeeded afterwards; `RLIMIT_CPU`
    was accepted, read back as `(1, 1)`, and a child then spent 4 s of CPU under it and exited
    0. Linux is the platform whose kernel documents both — `mmap` past `RLIMIT_AS` fails with
    `ENOMEM`, which the interpreter raises as `MemoryError`; `RLIMIT_CPU` delivers `SIGXCPU` at
    the soft limit when the hard limit sits above it, and `SIGKILL` at the hard one — and `tests/test_cdm_resource_envelope.py` asserts the enforcement on that
    platform and the refusal on every other. Windows has no `resource` module at all.
    """
    try:
        import resource  # noqa: F401 - the probe is the import
    except ImportError:
        reason = "no `resource` module on this platform: `setrlimit` does not exist here"
        return {"memory_bytes": (False, reason), "cpu_seconds": (False, reason)}
    if sys.platform.startswith("linux"):
        return {"memory_bytes": (True, "RLIMIT_AS: an allocation past the limit fails with "
                                       "ENOMEM and the interpreter raises MemoryError"),
                "cpu_seconds": (True, "RLIMIT_CPU: SIGXCPU at the soft limit ends the worker "
                                      "(hard limit one second above it, SIGKILL as the backstop)")}
    if sys.platform == "darwin":
        return {"memory_bytes": (False, "macOS refuses a finite RLIMIT_AS/RLIMIT_DATA with EINVAL "
                                        "(read 2026-09-20 on 26.5.2 / CPython 3.14.7)"),
                "cpu_seconds": (False, "macOS accepts RLIMIT_CPU and does not enforce it (read "
                                       "2026-09-20: 4 s of CPU spent under a 1 s limit)")}
    reason = f"{sys.platform}: rlimit enforcement not measured, so none is claimed"
    return {"memory_bytes": (False, reason), "cpu_seconds": (False, reason)}


def _apply_resource_limits(limits: dict[str, int]) -> None:
    """In the child, before the adapter is imported. A refusal here is the worker's init error."""
    if not limits:
        return
    import resource
    if "memory_bytes" in limits:
        value = limits["memory_bytes"]
        resource.setrlimit(resource.RLIMIT_AS, (value, value))
    if "cpu_seconds" in limits:
        value = limits["cpu_seconds"]
        # soft < hard, or Linux sends SIGKILL at the hard limit and never SIGXCPU (docstring of
        # `ResourceLimits`; S10 2026-09-20).
        resource.setrlimit(resource.RLIMIT_CPU, (value, value + 1))

#: F03's outcome codes: one per case, stable across machines, and the ONLY vocabulary the
#: canonical evidence uses for what happened to a case. `PARSER_REJECTED` is the controlled
#: refusal the checks want. Everything else fails the case, and a timeout is a failed robustness
#: test and not a successful rejection — the parser did not refuse anything, the harness stopped
#: waiting for it.
PARSER_REJECTED = "PARSER_REJECTED"
PARSER_ACCEPTED = "PARSER_ACCEPTED"
PARSER_TIMEOUT = "PARSER_TIMEOUT"
PARSER_CRASH = "PARSER_CRASH"
WORKER_INIT_FAILED = "WORKER_INIT_FAILED"
HARNESS_ERROR = "HARNESS_ERROR"
OUTCOME_CODES = (PARSER_REJECTED, PARSER_ACCEPTED, PARSER_TIMEOUT, PARSER_CRASH,
                 WORKER_INIT_FAILED, HARNESS_ERROR)
FAILING_OUTCOMES = frozenset(OUTCOME_CODES) - {PARSER_REJECTED}

#: F2.5. Every offset for a fixture under this size, evenly spaced up to this many for anything
#: larger. Stated in the report — a truncation sweep whose density is invisible is a number
#: nobody can reproduce.
DEFAULT_OFFSET_CAP = 4096

#: The four exception classes that are a CRASH rather than a refusal (F2.2). Everything else,
#: including a bare `Exception`, is a safe rejection with its class recorded. A declared
#: `SourceError` hierarchy is Part 2 and is written up as a limitation rather than assumed.
CRASH_CLASSES = (SystemExit, KeyboardInterrupt, MemoryError, RecursionError)

#: The CDM's own identity fields. `source.external_id` is deliberately NOT here: it is the
#: SOURCE's identifier, it is frequently a uuid4 drawn by somebody else, and asserting uuid5 over
#: it would fail three adapters for carrying their sources' identifiers faithfully.
IDENTITY_FIELDS = ("entity_id", "event_id", "track_id", "object_id")

#: Keys whose subtrees hold PARKED SOURCE VALUES rather than CDM fields. J does not walk into
#: them: a source timestamp parked verbatim in `attributes` is evidence that nothing was dropped,
#: and holding it to the CDM's serialisation rule would punish the adapter for keeping it.
PARKED = ("attributes", "payload", "source_extras")

#: The `Limitation.id` an adapter declares when its FORMAT states no instant for any object, so
#: that J's "no timestamp to judge" is a declared inapplicability and not an omission
#: (2026-09-20, adapter expansion phase 1; `check_temporal`).
NO_SOURCE_TIME_LIMITATION = "no-source-time"

_EPOCH = "1970-01-01T00:00:00.000Z"
_TOP_SENTINEL = "soifunknowntopsentinel"
_NESTED_SENTINEL = "soifunknownnestedsentinel"


@dataclasses.dataclass(frozen=True)
class Check:
    """One row of §18's table. `harness_key` is set for A–F and None for G–O."""

    letter: str
    name: str
    harness_key: str | None = None


#: §17's fifteen, in §17's order, with §18's spelling of each name. The letters are the
#: SUITE's namespace and are not the SC-OES tool's (ARCHITECTURE.md §8): a consumer merging two
#: reports finds these under `checks` and those under `dimensions`.
CHECKS: tuple[Check, ...] = (
    Check("A", "translate", "translate"),
    Check("B", "schema", "schema"),
    Check("C", "provenance", "provenance"),
    Check("D", "lossless", "lossless"),
    Check("E", "roundtrip", "roundtrip"),
    Check("F", "golden", "golden"),
    Check("G", "deterministic"),
    Check("H", "malformed-input"),
    Check("I", "unknown-preservation"),
    Check("J", "temporal"),
    Check("K", "identity"),
    Check("L", "version"),
    Check("M", "streaming"),
    Check("N", "parser robustness"),
    Check("O", "resource limits"),
)
CHECK_LETTERS: tuple[str, ...] = tuple(c.letter for c in CHECKS)
BY_LETTER: dict[str, Check] = {c.letter: c for c in CHECKS}

#: §3.6, step 2, as data. L0 is absent because it "requires no check — it requires a document",
#: and L5 is absent because its requirement is not a list: it is every check APPLICABLE to this
#: adapter, which is only knowable from the run. L6 is never computed here (§3.3).
LEVEL_REQUIREMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("L1", ("A",)),
    ("L2", ("A", "B")),
    ("L3", ("A", "B", "C")),
    ("L4", ("A", "B", "C", "E")),
)


def _verdict(verdict: str, *, reason: str | None = None, declared: bool = False,
             **details: Any) -> dict:
    """One check entry. `declared_inapplicable` is on EVERY entry, not just the SKIPs.

    §3.6 rule 5 requires the report to carry the pair (verdict, which declaration made it
    inapplicable) so that the eligibility computation can be a separate layer that reads it. A
    flag present only on SKIPs would make its absence mean two things.
    """
    entry: dict[str, Any] = {"verdict": verdict, "declared_inapplicable": bool(declared)}
    if reason:
        entry["reason"] = reason
    entry["details"] = details
    return entry


def canonical(objects: list[dict]) -> str:
    """ARCHITECTURE.md §6.2's one serialisation, quoted there and written once in `canonical.py`.

    This docstring said "written once here" until 2026-09-16, when the same expression was at
    six other sites; the module `synapse_cdm.canonical` is now the one place, and this is G's
    name for it.

    WHY G COMPARES THESE STRINGS AND DOES NOT HASH THEM — A COLLISION, RECORDED RATHER THAN
    RESOLVED IN PASSING
    --------------------------------------------------------------------------------------
    ARCHITECTURE.md §4.4 says "P2's determinism check parses one fixture repeatedly,
    canonicalises, serialises, HASHES and compares", and §6.2 fixes the hash as sha256 over these
    bytes. `tests/test_cdm_boundary.py:74` forbids every module under `synapse_cdm/` from
    importing `hashlib`, with a reason of its own — signing belongs to the ledger, which holds the
    keys and is audited, and a digest is a signature's raw material. The two are both in the tree
    and this is the round that makes them meet.

    Neither is edited here. G compares the canonical serialisations DIRECTLY, which decides §20's
    question — "all hashes MUST match" — strictly more strongly than comparing digests of them
    would: two different serialisations cannot compare equal as strings, and two different
    serialisations CAN in principle share a digest. Nothing is weakened and no hash is quoted, so
    §6.2's rule about the form a quoted hash takes is not engaged.

    What is owed to a person is the ruling, not this workaround: P4's evidence records are
    specified to CARRY a hash, and a record that quotes one has to compute one. That decision —
    a narrow, reasoned exemption in the boundary gate, or a hash computed outside the package —
    belongs to whoever rules on P4, and it is written up in this round's report rather than taken
    here.
    """
    return _canonical.serialise(objects)


#: The harness's, by name: one dump, so the objects G compares are the objects F judged.
_dump = harness._dump


def _fixtures(directory: pathlib.Path) -> list[pathlib.Path]:
    """`harness.select_fixtures`, under the name this module's callers and tests use.

    Until 2026-09-16 this restated the harness's four predicates and said the restatement was
    "kept identical by `tests/test_cdm_suite.py`" for "the reason the harness's own docstring
    gives" — and neither was so: the holding test is `tests/test_cdm_evidence.py`'s
    `test_the_harness_and_the_suite_both_stop_selecting_the_record`, and the harness gave no
    reason. It now calls the one definition. §33's `PROVENANCE.json` is therefore excluded here
    by the harness's own name for it: `check_malformed` reads `malformed/` through this
    function, and every `malformed/` directory carries a provenance record of its own.
    """
    return harness.select_fixtures(directory)


def _fresh(adapter: Adapter, clock: times.Clock) -> Adapter:
    """A NEW instance of the same class under a stated clock, carrying nothing from the last one.

    K's whole question is whether identity is derived or remembered, and reusing the instance
    would let an adapter answer it out of a cache.
    """
    return type(adapter)(clock=clock, synthetic=adapter._synthetic)


def _walk(node: Any, path: str = "") -> Any:
    """Every leaf of the CDM's own structure, skipping the parked-source subtrees."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in PARKED:
                continue
            yield from _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    else:
        yield path, node


def _leaf_key(path: str) -> str:
    return path.rsplit(".", 1)[-1].split("[")[0]


def _fold(report: dict, letter: str, key: str) -> dict:
    """A–F: one adapter-level verdict from the harness's per-fixture ones.

    FAIL if any fixture failed the check; else PASS if any fixture passed it; else SKIP, carrying
    the harness's own reasons. The order matters and is the conservative one — an adapter with
    one failing fixture is not credited for the ten that passed.
    """
    verdicts = [result["checks"].get(key, "-") for result in report["results"]]
    counts = {v: verdicts.count(v) for v in (PASS, FAIL, SKIP)}
    reasons = sorted({problem for result in report["results"]
                      for problem in result["problems"] if problem.startswith(f"{key}:")})
    details = {"fixtures": len(verdicts), **{k.lower(): v for k, v in counts.items()},
               "problems": reasons[:8]}
    if counts[FAIL]:
        return _verdict(FAIL, reason=(reasons[0] if reasons else None), **details)
    if counts[PASS]:
        return _verdict(PASS, **details)
    return _verdict(SKIP, reason=(reasons[0] if reasons else
                                  "every fixture reported SKIP for this check"), **details)


def _roundtrip_declaration(adapter: Adapter) -> tuple[bool, str]:
    """Is E's SKIP a DECLARED inapplicability (§3.6 rule 4) or an absence of evidence (rule 6)?

    Declared exactly once: an ingest-only adapter has no egress direction, which is §3.6's own
    standing example. Any other SKIP the harness produces for E is NOT a declared inapplicability.
    It is the tool saying it could not measure, and rule 6 blocks the rung on exactly that.

    UNTIL 2026-09-16 THAT OTHER SKIP WAS THE ORDINARY CASE, NOT THE EXCEPTION. The harness
    reported it for every one of the eleven emitters in this repository — `from_cdm` returned
    non-JSON bytes the structural comparison could not read — and each declared L4 on the
    strength of a round-trip test in `tests/` this suite could not see, so every record read
    "declared L4, eligible L3". The harness now compares the emitted octets itself under the
    tolerance the class declares (`Adapter.ROUNDTRIP_TOLERANCE`), so L4 is COMPUTED for the
    eleven and this function has one declared case left. A SKIP here for an emitting adapter
    means no fixture was comparable, and blocking on it is right.
    """
    if adapter.direction == "ingest":
        return True, ("the adapter declares `direction: ingest`; there is no egress direction "
                      "for information to be lost in, so the check is inapplicable rather than "
                      "unrun (ARCHITECTURE.md §3.6 rule 4)")
    return False, ""


def check_deterministic(adapter: Adapter, payloads: list[tuple[str, Any]], *,
                        clock: times.Clock, repeats: int = 3) -> dict:
    """G, §20: parse, canonicalise, serialise, hash, compare. Applicable to every adapter."""
    compared: dict[str, list[str]] = {}
    undecodable = []
    for name, raw in payloads:
        renderings = []
        for _ in range(repeats):
            try:
                renderings.append(canonical(_dump(_fresh(adapter, clock).to_cdm(raw))))
            except Exception as e:                             # noqa: BLE001 - A's verdict, not G's
                undecodable.append(f"{name}: {type(e).__name__}")
                break
        else:
            compared[name] = renderings
    unstable = {name: len(set(rs)) for name, rs in compared.items() if len(set(rs)) != 1}
    details = {"fixtures_compared": len(compared), "repeats": repeats,
               "undecodable": undecodable[:8], "serialisation": "ARCHITECTURE.md §6.2",
               "bytes_compared": sum(len(rs[0].encode("utf-8")) for rs in compared.values()),
               "unstable": unstable}
    if unstable:
        return _verdict(FAIL, reason=f"{len(unstable)} fixture(s) serialised differently across "
                                     f"{repeats} decodes under one frozen clock", **details)
    if not compared:
        return _verdict(SKIP, reason="no fixture decoded, so nothing could be compared; see "
                                     "check A", **details)
    return _verdict(PASS, **details)


# --- F03: the parser worker ---------------------------------------------------------------------
#
# H and N feed a parser input that is malformed on purpose, so they are the two places where the
# parser may hang, and a hang in the same process as the harness is a hang of the harness. Both
# checks now run every case through one `ParserWorker`: a `spawn`ed interpreter that resolves the
# adapter by reference, constructs it once to prove it can, and then answers one case at a time
# over a pipe. The parent waits `timeout_s` for each answer and no longer. The worker sends a
# count, class names and a clipped message; it never sends a CDM object and the parent never
# unpickles anything from it — every message is JSON under `OUTPUT_CAP_BYTES`.


def _qualified(exc: BaseException) -> str:
    return f"{type(exc).__module__}.{type(exc).__name__}"


def _clip(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[:cap] + "…"


def adapter_reference(adapter: Adapter) -> str:
    """How the adapter travels to the worker: a registry name where the package ships it, and a
    `module:ClassName` import reference otherwise (a partner's adapter, a test double). Never a
    pickled instance — the worker builds its own under its own frozen clock."""
    cls = type(adapter)
    if is_shipped(cls) and roster().get(cls.name) is cls:
        return cls.name
    return f"{cls.__module__}:{cls.__qualname__}"


def _send(conn, message: dict, cap: int) -> None:
    encoded = json.dumps(message, sort_keys=True).encode()
    if len(encoded) > cap:
        # Clip the one free-text field and try once more; the fixed fields are small by design.
        message = dict(message, detail=None)
        encoded = json.dumps(message, sort_keys=True).encode()
    conn.send_bytes(encoded[:cap])


def _worker_main(inbox, outbox, reference: str, frozen_iso: str, synthetic: bool,
                 cap: int, limits: dict[str, int] | None = None) -> None:
    """The worker's whole life. Module-level so `spawn` can import it by name.

    Two simplex connections and not one duplex one: `Pipe(duplex=True)` is `socket.socketpair()`
    on Unix, and §41's no-network gate (`tests/test_cdm_no_network.py`) takes `socket.socket`
    away and runs the whole roster — a worker built on a socket pair failed it on the first full
    run. `Pipe(duplex=False)` is `os.pipe()`, which is what a harness that makes no network call
    should be built on anyway.
    """
    detail_cap = cap // 4
    try:
        _apply_resource_limits(limits or {})    # F06: the envelope, before anything is imported
        cls = load_adapter(reference)
        clock = times.frozen_clock(_dt.datetime.fromisoformat(frozen_iso))
        cls(clock=clock, synthetic=synthetic)
    except BaseException as e:                                # noqa: BLE001 - reported, then exit
        _send(outbox, {"init_error": _qualified(e), "detail": _clip(str(e), detail_cap)}, cap)
        return
    _send(outbox, {"ready": True}, cap)
    cached: tuple[pathlib.Path, bytes] | None = None
    while True:
        try:
            request = json.loads(inbox.recv_bytes(cap))
        except (EOFError, OSError):
            return
        if request.get("stop"):
            return
        path, offset = pathlib.Path(request["path"]), request.get("offset")
        reply: dict[str, Any] = {"outcome": None, "layer": "adapter", "exception": None,
                                 "objects": None, "detail": None}
        try:
            if offset is None:
                raw: Any = harness.load_raw(path)
            else:
                if cached is None or cached[0] != path:
                    cached = (path, path.read_bytes())
                raw = cached[1][:offset]
        except CRASH_CLASSES as e:
            reply.update(outcome=PARSER_CRASH, layer="loader", exception=_qualified(e))
        except Exception as e:                                 # noqa: BLE001 - the loader refused
            reply.update(outcome=PARSER_REJECTED, layer="loader", exception=_qualified(e),
                         detail=_clip(str(e), detail_cap))
        if reply["outcome"] is None:
            try:
                objects = cls(clock=clock, synthetic=synthetic).to_cdm(raw)
            except CRASH_CLASSES as e:
                reply.update(outcome=PARSER_CRASH, exception=_qualified(e))
            except Exception as e:                             # noqa: BLE001 - the refusal itself
                reply.update(outcome=PARSER_REJECTED, exception=_qualified(e),
                             detail=_clip(str(e), detail_cap))
            else:
                reply.update(outcome=PARSER_ACCEPTED, objects=len(objects))
        _send(outbox, reply, cap)


class ParserWorker:
    """One adapter's killable parser, reused across the cases of a check (and across H and N when
    `run()` hands both the same instance), restarted after every kill or death.

    `diagnostics` is where the VOLATILE facts go — pids, exit codes, durations, whether the kill
    escalated — so the canonical `details` can carry codes and bounds only and stay byte-identical
    between two runs of one tree. Nothing here hides a timeout: the code reaches the verdict, the
    seconds reach the diagnostics.
    """

    def __init__(self, adapter: Adapter, *, clock: times.Clock,
                 timeout_s: float = DEFAULT_TIMEOUT_S,
                 startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
                 max_restarts: int = DEFAULT_MAX_WORKER_RESTARTS,
                 output_cap: int = OUTPUT_CAP_BYTES, diagnostics: dict | None = None,
                 limits: ResourceLimits | None = None) -> None:
        self.reference = adapter_reference(adapter)
        self.frozen_iso = clock().isoformat()
        self.synthetic = adapter._synthetic
        self.timeout_s = timeout_s
        self.startup_timeout_s = startup_timeout_s
        self.max_restarts = max_restarts
        self.output_cap = output_cap
        self.limits = limits or ResourceLimits()
        self.limits.validate()      # F06: an unavailable guarantee is refused here, before a spawn
        self.diagnostics = diagnostics if diagnostics is not None else {}
        self.diagnostics.update({"isolation": ISOLATION, "reference": self.reference,
                                 "workers": [], "cases": [], "restarts": 0, "init_failure": None,
                                 "resource_limits": self.limits.requested(),
                                 "resource_limit_support": {
                                     name: {"enforced": enforced, "reason": reason}
                                     for name, (enforced, reason)
                                     in resource_limit_support().items()}})
        self._ctx = multiprocessing.get_context("spawn")
        self._proc = None
        self._reader = None      # replies from the worker
        self._writer = None      # requests to the worker
        self._record: dict | None = None
        self._started_at = 0.0
        self.init_failure: str | None = None    # once set, no further start is attempted

    # -- lifecycle ------------------------------------------------------------------------------

    def __enter__(self) -> "ParserWorker":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _start(self) -> bool:
        # Two `os.pipe()`-backed simplex connections; see `_worker_main` for why not one duplex.
        inbox_r, inbox_w = self._ctx.Pipe(duplex=False)      # parent writes, worker reads
        outbox_r, outbox_w = self._ctx.Pipe(duplex=False)    # worker writes, parent reads
        proc = self._ctx.Process(target=_worker_main, name=f"parser-worker:{self.reference}",
                                 args=(inbox_r, outbox_w, self.reference, self.frozen_iso,
                                       self.synthetic, self.output_cap,
                                       self.limits.requested()), daemon=True)
        self._started_at = time.monotonic()
        try:
            proc.start()
        except Exception as e:                                 # noqa: BLE001 - infrastructure
            self.init_failure = f"{HARNESS_ERROR}: the worker could not be started: {_qualified(e)}"
            self.diagnostics["init_failure"] = self.init_failure
            for end in (inbox_r, inbox_w, outbox_r, outbox_w):
                end.close()
            return False
        inbox_r.close()
        outbox_w.close()
        self._proc, self._reader, self._writer = proc, outbox_r, inbox_w
        self._record = {"pid": proc.pid, "exit_code": None, "duration_s": None,
                        "terminated": False, "killed": False, "ended_by": None}
        self.diagnostics["workers"].append(self._record)
        try:
            handshake = self._receive(self.startup_timeout_s)
        except EOFError:
            handshake = {"init_error": "the worker exited before its handshake"}
        except OSError as e:
            handshake = {"harness_error": _qualified(e)}
        if handshake is None:
            self._stop("startup-timeout")
            self.init_failure = (f"{WORKER_INIT_FAILED}: no handshake within "
                                 f"{self.startup_timeout_s}s")
        elif "init_error" in handshake:
            self._stop("init-error")
            self.init_failure = (f"{WORKER_INIT_FAILED}: {handshake['init_error']}: "
                                 f"{handshake.get('detail') or ''}".rstrip(": "))
        elif handshake.get("ready") is not True:
            self._stop("bad-handshake")
            self.init_failure = (f"{HARNESS_ERROR}: "
                                 f"{handshake.get('harness_error') or f'unexpected handshake {handshake!r}'}")
        if self.init_failure:
            self.diagnostics["init_failure"] = self.init_failure
            return False
        return True

    def _receive(self, timeout: float) -> dict | None:
        """One message, or None on timeout. Raises EOFError when the worker is gone, OSError
        when it sent more than the cap and ValueError when what it sent is not JSON — all three
        are the CALLER's to classify."""
        assert self._reader is not None
        if not self._reader.poll(timeout):
            return None
        return json.loads(self._reader.recv_bytes(self.output_cap))

    def _stop(self, reason: str) -> None:
        """join → terminate → kill → join, then reap and record. Idempotent."""
        proc, record = self._proc, self._record
        if proc is None:
            return
        try:
            if proc.is_alive():
                proc.terminate()
                record["terminated"] = True
                proc.join(KILL_GRACE_S)
            if proc.is_alive():
                proc.kill()
                record["killed"] = True
                proc.join()
        finally:
            proc.join(0)   # reaps a process that exited on its own between the checks above
            record.update(exit_code=proc.exitcode, ended_by=reason,
                          duration_s=round(time.monotonic() - self._started_at, 3))
            for end in (self._reader, self._writer):
                if end is not None:
                    end.close()
            proc.close()
            self._proc = self._reader = self._writer = self._record = None

    def close(self) -> None:
        if self._proc is not None and self._writer is not None:
            try:
                self._writer.send_bytes(b'{"stop": true}')
                self._proc.join(KILL_GRACE_S)
            except (OSError, ValueError):
                pass
        self._stop("closed")

    # -- one case ---------------------------------------------------------------------------------

    def run_case(self, case: str, path: pathlib.Path, offset: int | None = None) -> dict:
        """`{"outcome", "layer", "exception", "objects", "detail"}` for one payload, always."""
        started = time.monotonic()
        result = self._run_case(path, offset)
        self.diagnostics["cases"].append(
            {"case": case, "outcome": result["outcome"],
             "duration_s": round(time.monotonic() - started, 3)})
        return result

    def _run_case(self, path: pathlib.Path, offset: int | None) -> dict:
        blank = {"layer": None, "exception": None, "objects": None, "detail": None, "ran": True}
        if self.init_failure:
            code = HARNESS_ERROR if self.init_failure.startswith(HARNESS_ERROR) else WORKER_INIT_FAILED
            return {**blank, "outcome": code, "detail": self.init_failure, "ran": False}
        if self._proc is None:
            if self.diagnostics["restarts"] >= self.max_restarts:
                return {**blank, "outcome": HARNESS_ERROR, "ran": False,
                        "detail": f"max_worker_restarts={self.max_restarts} exhausted"}
            if not self._start():
                return self._run_case(path, offset)
        try:
            request = {"path": str(path), "offset": offset}
            self._writer.send_bytes(json.dumps(request).encode())
            reply = self._receive(self.timeout_s)
        except EOFError:
            reply = False
        except OSError as e:
            self._stop("oversize-or-broken-pipe")
            self.diagnostics["restarts"] += 1
            return {**blank, "outcome": HARNESS_ERROR, "detail": _qualified(e)}
        except ValueError as e:
            # A reply under the cap that is not JSON (S10, 2026-09-20: `_send`'s last resort clips
            # the encoded reply to the cap, and a clipped document does not decode). The case is
            # the harness's, not the parser's, and the worker is restarted like any bad reply.
            self._stop("undecodable-reply")
            self.diagnostics["restarts"] += 1
            return {**blank, "outcome": HARNESS_ERROR,
                    "detail": f"undecodable worker reply: {_qualified(e)}"}
        if reply is None:
            self._stop("timeout")
            self.diagnostics["restarts"] += 1
            return {**blank, "outcome": PARSER_TIMEOUT,
                    "detail": f"no answer within {self.timeout_s}s; worker killed"}
        if reply is False:
            self._stop("died")
            self.diagnostics["restarts"] += 1
            return {**blank, "outcome": PARSER_CRASH,
                    "detail": "the worker process exited during the case"}
        if reply.get("outcome") not in OUTCOME_CODES:
            self._stop("bad-reply")
            self.diagnostics["restarts"] += 1
            return {**blank, "outcome": HARNESS_ERROR, "detail": "unrecognised worker reply"}
        return {**blank, **reply}


def _outcome_counts(cases: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["outcome"]] = counts.get(case["outcome"], 0) + 1
    return dict(sorted(counts.items()))


def _worker_bounds(worker: ParserWorker) -> dict:
    bounds = {"timeout_s": worker.timeout_s, "startup_timeout_s": worker.startup_timeout_s,
              "max_worker_restarts": worker.max_restarts, "isolation": ISOLATION}
    # F06: only a limit that WAS requested is written into the canonical details — the key's
    # absence is the statement that the run applied none, and a default run's bytes do not move.
    if worker.limits.requested():
        bounds["resource_limits"] = worker.limits.requested()
    return bounds


def check_malformed(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock,
                    timeout_s: float = DEFAULT_TIMEOUT_S,
                    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
                    worker: ParserWorker | None = None, diagnostics: dict | None = None) -> dict:
    """H, §21: every payload under `malformed/` must be REFUSED, and refused safely.

    "Safely" is F2.2: any exception except the four crash classes, inside the time bound, with no
    object returned. The class is recorded because "it raised" and "it raised a KeyError from
    three frames down" are different facts about a parser, and Part 2's declared `SourceError`
    hierarchy is the repair — a limitation here, not an assumption.

    The REFUSING LAYER is recorded too. A malformed JSON document is refused by the fixture
    loader (`harness.load_raw`) before the adapter is asked, because the loader is what parses
    JSON — that is a true and useful fact about the pipeline and it is not the parser being
    exercised, so the check requires at least one payload to be refused by the ADAPTER itself.

    THE TIME BOUND IS ENFORCED AND ITS READING IS NOT PUBLISHED (round PB, 2026-09-08). Each
    refusal carries `over_time_bound`, a boolean, and `details` carries `timeout_s`, the bound
    the run was given; neither varies between two runs of one tree. The elapsed seconds are
    measured — that is how the boolean is decided — and they stay in this frame, because
    `--format json` is evidence whose digest is written into `SHA256SUMS` and read back by
    `gates/witness_verify.py`, and a machine-load-dependent byte makes that digest a number
    nobody can re-derive.

    AND SINCE F03 (2026-09-19) IT IS ENFORCED BY A KILL, NOT A COMPARISON. Every payload — the
    loader included — runs in `ParserWorker`'s spawned process; a case that has not answered in
    `timeout_s` is killed and recorded as `PARSER_TIMEOUT`, which is a FAIL. `details["cases"]`
    carries every case's outcome code in order; `details["refusals"]` keeps round PB's row shape
    and holds the `PARSER_REJECTED` cases only, so a timeout can no longer sit in it (its
    `over_time_bound` is therefore always false now, and stays for the shape). The bounds the
    run was given are in `details`; the seconds, pids and exit codes are in `diagnostics`. The
    elapsed reading that decided the old boolean is gone with the comparison: what reaches the
    report is the code, and the code is decided by the kill.
    """
    directory = fixtures / MALFORMED_DIR
    if not directory.is_dir():
        return _verdict(SKIP, reason="no malformed fixtures declared: "
                                     f"{directory} does not exist", declared=True,
                        directory=str(directory))
    payloads = _fixtures(directory)
    if not payloads:
        return _verdict(FAIL, reason=f"{directory} exists and is empty; a declared malformed set "
                                     "with nothing in it reads as a passed check over an empty "
                                     "set", directory=str(directory))
    own = worker is None
    if own:
        worker = ParserWorker(adapter, clock=clock, timeout_s=timeout_s,
                              startup_timeout_s=startup_timeout_s, diagnostics=diagnostics)
    try:
        cases = [(path, worker.run_case(path.name, path)) for path in payloads]
    finally:
        if own:
            worker.close()
    refusals, accepted, crashed, slow, broken, not_run = [], [], [], [], [], 0
    for path, result in cases:
        code = result["outcome"]
        if not result["ran"]:
            not_run += 1
        if code == PARSER_REJECTED:
            refusals.append({"fixture": path.name, "refused_by": result["layer"],
                             "exception": result["exception"], "over_time_bound": False})
        elif code == PARSER_ACCEPTED:
            accepted.append(f"{path.name}: returned {result['objects']} object(s)")
        elif code == PARSER_CRASH:
            crashed.append(f"{path.name}: {result['exception'] or PARSER_CRASH}")
        elif code == PARSER_TIMEOUT:
            slow.append(path.name)
        else:
            broken.append(f"{path.name}: {code}: {result['detail']}")
    by_adapter = [r for r in refusals if r["refused_by"] == "adapter"]
    details = {"payloads": len(payloads), "refusals": refusals, "accepted": accepted,
               "crashed": crashed, "over_time_bound": slow,
               "cases": [{"fixture": path.name, "outcome": result["outcome"]}
                         for path, result in cases],
               "outcomes": _outcome_counts([result for _, result in cases]),
               "cases_not_run": not_run, **_worker_bounds(worker),
               "refused_by_adapter": len(by_adapter),
               "exception_classes": sorted({r["exception"] for r in refusals})}
    if broken:
        return _verdict(FAIL, reason=f"the parser could not be exercised: {broken[0]}",
                        **details)
    if accepted:
        return _verdict(FAIL, reason=f"{len(accepted)} malformed payload(s) were ACCEPTED: "
                                     f"{accepted[0]}", **details)
    if crashed:
        return _verdict(FAIL, reason=f"a malformed payload raised a crash class: {crashed[0]}",
                        **details)
    if slow:
        return _verdict(FAIL, reason=f"{PARSER_TIMEOUT}: {slow[0]} was not answered within "
                                     f"{timeout_s}s and the worker was killed; a timeout is a "
                                     "failed robustness test, not a rejection", **details)
    if not by_adapter:
        return _verdict(FAIL, reason="every malformed payload was refused by the fixture loader "
                                     "and none reached the adapter, so the parser was never "
                                     "asked to refuse anything", **details)
    return _verdict(PASS, **details)


def _inject(document: dict) -> tuple[dict, bool]:
    """One unknown scalar at the top level and one nested, into a copy."""
    payload = copy.deepcopy(document)
    payload["__soif_unknown_top"] = _TOP_SENTINEL
    target = None
    for value in payload.values():
        if isinstance(value, dict):
            target = value
            break
    if target is None:
        for value in payload.values():
            if isinstance(value, list):
                nested = [v for v in value if isinstance(v, dict)]
                if nested:
                    target = nested[0]
                    break
    if target is not None:
        target["__soif_unknown_nested"] = _NESTED_SENTINEL
    return payload, target is not None


def check_unknown_fields(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock) -> dict:
    """I: inject an unknown scalar the adapter has never seen and look for it in the output.

    The check READS THE DECLARATION rather than deciding applicability itself
    (`capabilities.unknown_fields`), because whether a format has a carrier for a field nobody
    defined is a fact about the format and not something a probe can establish: a probe that
    finds nothing has found either a format with no carrier or an adapter that drops what it
    carries, and those are opposite verdicts.

    Presence is `lossless._present_forms` — the same harvest check D uses — so "preserved" means
    what it means everywhere else in this repository.
    """
    declared = adapter.metadata.capabilities.unknown_fields
    if declared is UnknownFields.NONE:
        return _verdict(SKIP, reason="format has no unknown-field carrier: the adapter declares "
                                     "`capabilities.unknown_fields: none` — "
                        + adapter.metadata.capabilities.unknown_fields_basis,
                        declared=True, declaration="capabilities.unknown_fields")
    documents = [p for p in _fixtures(fixtures) if p.suffix.lower() == ".json"]
    missing, probed, no_nested = [], 0, 0
    for path in documents:
        document = json.loads(path.read_text())
        if not isinstance(document, dict):
            continue
        payload, nested = _inject(document)
        if not nested:
            no_nested += 1
        try:
            forms = lossless._present_forms(_dump(_fresh(adapter, clock).to_cdm(payload)))
        except Exception as e:                                 # noqa: BLE001 - reported, not raised
            missing.append(f"{path.name}: to_cdm raised {type(e).__name__} on a payload carrying "
                           f"one extra key: {e}")
            continue
        probed += 1
        if _TOP_SENTINEL not in forms:
            missing.append(f"{path.name}: the top-level unknown field was dropped")
        if nested and _NESTED_SENTINEL not in forms:
            missing.append(f"{path.name}: the nested unknown field was dropped")
    details = {"documents_probed": probed, "documents_without_a_nested_object": no_nested,
               "declaration": "preserved", "dropped": missing[:8]}
    if not documents:
        return _verdict(SKIP, reason="the adapter declares `unknown_fields: preserved` but ships "
                                     "no dict-form fixture to inject into; a bytes fixture has "
                                     "no generic carrier for an injected key", **details)
    if missing:
        return _verdict(FAIL, reason=missing[0], **details)
    return _verdict(PASS, **details)


def check_temporal(adapter: Adapter, payloads: list[tuple[str, Any]], *, clock: times.Clock,
                   frozen_at: _dt.datetime) -> dict:
    """J, §27. Three hard rules, one differential rule, one comparison that is not made.

    See this module's docstring for why the equality-to-the-clock proxy is not used and why the
    ordering comparison is conditional. The differential rule is the one that carries §27: a
    timestamp that MOVES when the injected clock moves came from `now()`, and §27 forbids an
    unknown time becoming `now()` — silently. Every one in this tree says so in the object
    itself, at `payload.observed_at_basis`, so the rule is testable rather than aspirational.

    `valid_from` / `valid_to` are OUTSIDE the differential rule and reported as a count instead.
    They are the entity's validity window, not the observation instant §27 speaks about, and
    temporal validity is the primitive P3 owes (ARCHITECTURE.md §9). Reporting the count keeps
    the fact visible; asserting on it here would rule a question this round was not given.
    """
    alternative = frozen_at + _dt.timedelta(days=2, hours=5, minutes=45)
    frozen_text = times.render(frozen_at)
    malformed, epochs, undeclared, ordering = [], [], [], []
    exempted_ordering = 0
    validity_tracks_clock = 0
    stamps = 0
    for name, raw in payloads:
        try:
            here = _dump(_fresh(adapter, clock).to_cdm(raw))
            there = _dump(_fresh(adapter, times.frozen_clock(alternative)).to_cdm(raw))
        except Exception:                                      # noqa: BLE001 - A's verdict, not J's
            continue
        for index, obj in enumerate(here):
            other = there[index] if index < len(there) else {}
            carrier = {**(obj.get("payload") or {}), **(obj.get("attributes") or {})}
            moved = {path for path, value in _walk(other)}
            other_values = dict(_walk(other))
            for path, value in _walk(obj):
                if not isinstance(value, str) or "T" not in value or not value.endswith("Z"):
                    continue
                key = _leaf_key(path)
                if not (key.endswith("_at") or key.endswith("_from") or key.endswith("_to")):
                    continue
                stamps += 1
                if not times.TIMESTAMP_RE.match(value):
                    malformed.append(f"{name}: {path} = {value!r} is not RFC 3339 UTC with "
                                     "exactly three decimals and a trailing Z")
                if value == _EPOCH:
                    epochs.append(f"{name}: {path} = {value!r}; §27 forbids an unknown time "
                                  "becoming 1970-01-01")
                if key == "received_at" or path not in moved:
                    continue
                if other_values.get(path) == value:
                    continue
                if key in ("valid_from", "valid_to"):
                    validity_tracks_clock += 1
                    continue
                if not carrier.get(f"{key}_basis"):
                    undeclared.append(
                        f"{name}: {path} moved with the injected clock, so it came from "
                        f"now(), and the object declares no `{key}_basis` for it (§27)")
            observed, received = obj.get("observed_at"), obj.get("received_at")
            if isinstance(observed, str) and isinstance(received, str):
                if received == frozen_text:
                    exempted_ordering += 1
                elif observed > received:
                    ordering.append(f"{name}: observed_at {observed} is after received_at "
                                    f"{received}")
    details = {"timestamps": stamps, "alternative_clock": times.render(alternative),
               "ordering_exempted_frozen_receipt": exempted_ordering,
               "validity_window_tracks_the_clock": validity_tracks_clock,
               "problems": (malformed + epochs + undeclared + ordering)[:8]}
    if malformed or epochs or undeclared or ordering:
        return _verdict(FAIL, reason=(malformed + epochs + undeclared + ordering)[0], **details)
    if not stamps:
        # A DECLARED absence, since 2026-09-20 (adapter expansion phase 1): a format that states
        # no instant for any object — a static GeoJSON layer is the first — emits no timestamp
        # unless its caller supplies an as-of context, which the suite's fresh instances never
        # carry. The adapter says so in a structured limitation with the id below, read here the
        # way I reads `capabilities.unknown_fields`: the SKIP then carries the declaration, §3.6
        # rule 4 lets it through, and an adapter that emits stamps is judged on them regardless.
        declared = next((lim for lim in adapter.metadata.limitations
                         if not isinstance(lim, str) and lim.id == NO_SOURCE_TIME_LIMITATION),
                        None)
        if declared is not None:
            return _verdict(SKIP, reason="the adapter emitted no CDM timestamp to judge, and "
                                         "declares that its format states no instant: "
                            + declared.summary, declared=True,
                            declaration=f"limitations[id={NO_SOURCE_TIME_LIMITATION}]", **details)
        return _verdict(SKIP, reason="the adapter emitted no CDM timestamp to judge", **details)
    return _verdict(PASS, **details)


def check_identity(adapter: Adapter, payloads: list[tuple[str, Any]], *,
                   clock: times.Clock) -> dict:
    """K, Rule 3: derived identity is stable, and it is DERIVED.

    Two fresh instances, same configuration, same payload: every `entity_id`, `event_id`,
    `track_id` and `object_id` must be equal. And each must be a uuid5 — `ids.derive` is uuid5
    under a fixed namespace (`ids.py:28–41`), so a value that is not one was drawn rather than
    derived, whatever it looks like.
    """
    unstable, undrawn = [], []
    identifiers = 0
    for name, raw in payloads:
        try:
            first = _dump(_fresh(adapter, clock).to_cdm(raw))
            second = _dump(_fresh(adapter, clock).to_cdm(raw))
        except Exception:                                      # noqa: BLE001 - A's verdict, not K's
            continue
        for index, obj in enumerate(first):
            twin = second[index] if index < len(second) else {}
            for path, value in _walk(obj):
                if _leaf_key(path) not in IDENTITY_FIELDS or not isinstance(value, str):
                    continue
                identifiers += 1
                if dict(_walk(twin)).get(path) != value:
                    unstable.append(f"{name}: {path} differs between two decodes of one payload")
                try:
                    if uuid.UUID(value).version != 5:
                        undrawn.append(f"{name}: {path} = {value} is a uuid"
                                       f"{uuid.UUID(value).version}, not the uuid5 `ids.derive` "
                                       "produces")
                except ValueError:
                    undrawn.append(f"{name}: {path} = {value!r} is not a UUID at all")
    details = {"identifiers": identifiers, "fields": list(IDENTITY_FIELDS),
               "problems": (unstable + undrawn)[:8]}
    if unstable or undrawn:
        return _verdict(FAIL, reason=(unstable + undrawn)[0], **details)
    if not identifiers:
        return _verdict(SKIP, reason="the adapter emitted no CDM identifier to judge", **details)
    return _verdict(PASS, **details)


def check_version(adapter: Adapter, payloads: list[tuple[str, Any]], *, clock: times.Clock,
                  supported: str) -> dict:
    """L: what the objects say they are written to, against what this package and this manifest
    say they support. Three statements that can disagree, checked as three."""
    wrong, incompatible, outside = [], [], []
    objects = 0
    major = supported.split(".", 1)[0]
    for name, raw in payloads:
        try:
            dumped = _dump(_fresh(adapter, clock).to_cdm(raw))
        except Exception:                                      # noqa: BLE001 - A's verdict, not L's
            continue
        for obj in dumped:
            written = obj.get("schema_version")
            if not isinstance(written, str):
                continue
            objects += 1
            if written != SCHEMA_VERSION:
                wrong.append(f"{name}: schema_version {written!r} is not this package's "
                             f"{SCHEMA_VERSION!r}")
            try:
                assessed = version.assess(written, SCHEMA_VERSION)
            except ValueError as e:                            # the model refuses these; L says why
                incompatible.append(f"{name}: schema_version {e}")
                continue
            if not assessed:
                incompatible.append(f"{name}: version.assess({written!r}, {SCHEMA_VERSION!r}) "
                                    f"is {assessed.verdict.value} ({assessed.direction.value}): "
                                    f"{assessed.reason} — basis: {assessed.basis}")
            if written.split(".", 1)[0] != major:
                outside.append(f"{name}: schema_version {written!r} is outside the manifest's "
                               f"declared `cdm.supported` {supported!r}")
    details = {"objects": objects, "schema_version": SCHEMA_VERSION, "cdm_supported": supported,
               "problems": (wrong + incompatible + outside)[:8]}
    if wrong or incompatible or outside:
        return _verdict(FAIL, reason=(wrong + incompatible + outside)[0], **details)
    if not objects:
        return _verdict(SKIP, reason="the adapter emitted no object to judge", **details)
    return _verdict(PASS, **details)


#: F06 (2026-09-20): the four properties a streaming contract would consist of, each with the
#: status this package can honestly state. None is implemented, none is advertised, and check M
#: prints the four so that "SKIP" reads as a statement of what is absent and not as an omission.
#: `to_cdm` is handed ONE complete payload; a caller that reads a socket or a file in pieces does
#: the framing, the reassembly of a partial message and the backpressure itself, and hands over a
#: whole message inside `max_input_bytes`. KLV's framing layer (`stanag4609`) is the grammar of
#: one packet's key, tag and length, not a stream reader — `tests/test_cdm_klv_framing.py`.
STREAMING_STATUS: dict[str, str] = {
    "chunk_framing": "not implemented: `to_cdm` takes one complete payload; the caller frames",
    "partial_messages": "not implemented: a truncated payload is REFUSED, never buffered "
                        "(check N exercises exactly this)",
    "reassembly": "not implemented: no adapter holds state between two `to_cdm` calls",
    "backpressure": "not applicable: nothing here reads from a source, so nothing can slow one",
}


def check_streaming(adapter: Adapter) -> dict:
    """M: SKIP unless the adapter declares a streaming capability — and today none can.

    No adapter in this repository declares one and `Capabilities` has no field for it at manifest
    schema 1.0.0, so the absence is a closed model's declaration rather than an omission — which
    is why this is a DECLARED inapplicability and does not block a rung. The verdict model (ADR
    0009) has `PASS`/`FAIL`/`SKIP` and no fourth word, so "not applicable" is spelled `SKIP` with
    `declared_inapplicable: true` and the four statuses in `STREAMING_STATUS` beside it; it is
    never `PASS`, because nothing was fed in two chunks and nothing could be.
    """
    return _verdict(SKIP, reason="the adapter declares no streaming capability; `Capabilities` "
                                 "carries no `streaming` field at manifest schema "
                                 f"{version.MANIFEST_SCHEMA_VERSION}, so no adapter can declare "
                                 "one and the check has nothing to feed in two chunks",
                    declared=True, declaration="capabilities (no streaming field)",
                    streaming=dict(STREAMING_STATUS))


def check_parser_robustness(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock,
                            offset_cap: int = DEFAULT_OFFSET_CAP,
                            timeout_s: float = DEFAULT_TIMEOUT_S,
                            startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
                            worker: ParserWorker | None = None,
                            diagnostics: dict | None = None) -> dict:
    """N, F2.5: truncate a byte fixture at every offset (evenly spaced above the cap) and require
    raise-not-crash.

    A truncated payload that DECODES is not a failure. Some formats are self-delimiting and a
    prefix of a valid payload is a valid shorter payload; requiring a refusal would be requiring
    a parser to reject something well-formed. What must not happen is a crash class or a hang,
    and those are what this measures.

    Since F03 (2026-09-19) every offset is one case in `ParserWorker`'s spawned process: the
    parent sends the path and the offset, the worker slices the bytes it read once, and a case
    that has not answered within `timeout_s` is killed and recorded as `PARSER_TIMEOUT`. The
    offset generation, `offsets_tried`, `offset_cap_per_fixture` and `decoded_without_raising`
    are what they were; `over_time_bound` names the offset and the code, and no longer the
    seconds it took — a reading that reached canonical evidence whenever the check failed.
    """
    byte_fixtures = [p for p in _fixtures(fixtures) if p.suffix.lower() != ".json"]
    if not byte_fixtures:
        return _verdict(SKIP, reason="not a byte stream: every fixture this adapter ships is a "
                                     "parsed dict, so there is nothing to truncate",
                        declared=True, declaration="the adapter's fixture set")
    own = worker is None
    if own:
        worker = ParserWorker(adapter, clock=clock, timeout_s=timeout_s,
                              startup_timeout_s=startup_timeout_s, diagnostics=diagnostics)
    crashed, slow, broken, results = [], [], [], []
    attempts = decoded = not_run = 0
    try:
        for path in byte_fixtures:
            size = path.stat().st_size
            if size < 2:
                continue
            if size - 1 <= offset_cap:
                offsets: Any = range(1, size)
            else:
                step = (size - 1) / offset_cap
                offsets = sorted({max(1, int(1 + index * step)) for index in range(offset_cap)})
            for offset in offsets:
                attempts += 1
                case = f"{path.name}[:{offset}]"
                result = worker.run_case(case, path, offset)
                results.append(result)
                code = result["outcome"]
                if not result["ran"]:
                    not_run += 1
                if code == PARSER_ACCEPTED:
                    decoded += 1
                elif code == PARSER_CRASH:
                    crashed.append(f"{case}: {result['exception'] or PARSER_CRASH}")
                elif code == PARSER_TIMEOUT:
                    slow.append(f"{case}: {PARSER_TIMEOUT}")
                elif code != PARSER_REJECTED:
                    broken.append(f"{case}: {code}: {result['detail']}")
    finally:
        if own:
            worker.close()
    details = {"byte_fixtures": len(byte_fixtures), "offsets_tried": attempts,
               "offset_cap_per_fixture": offset_cap, "decoded_without_raising": decoded,
               "crashed": crashed[:8], "over_time_bound": slow[:8],
               "outcomes": _outcome_counts(results), "cases_not_run": not_run,
               **_worker_bounds(worker)}
    if broken:
        return _verdict(FAIL, reason=f"the parser could not be exercised: {broken[0]}",
                        **details)
    if crashed:
        return _verdict(FAIL, reason=f"a truncated payload raised a crash class: {crashed[0]}",
                        **details)
    if slow:
        return _verdict(FAIL, reason=f"{PARSER_TIMEOUT}: {slow[0]} was not answered within "
                                     f"{timeout_s}s and the worker was killed; a timeout is a "
                                     "failed robustness test, not a rejection", **details)
    return _verdict(PASS, **details)


def check_resource_limits(adapter: Adapter, payloads: list[tuple[str, Any]], *,
                          clock: times.Clock) -> dict:
    """O: live only where `capabilities.limits.max_input_bytes` is declared (F2.3 → P5).

    The SKIP is a DECLARED inapplicability and not an omission, because `Limits` refuses an
    absent bound that carries no reason (`manifest.Limits._every_absent_limit_has_a_reason`): every
    one of the fourteen states in its own manifest why it enforces none, and that sentence is what
    this quotes.
    """
    limits = adapter.metadata.capabilities.limits
    if limits.max_input_bytes is None:
        return _verdict(SKIP, reason="no limit declared: "
                        + limits.absent_because["max_input_bytes"],
                        declared=True, declaration="capabilities.limits.absent_because")
    if not payloads:
        return _verdict(SKIP, reason="no fixture to repeat up to the declared bound",
                        max_input_bytes=limits.max_input_bytes)
    seed = next((raw for _, raw in payloads if isinstance(raw, (bytes, bytearray))), None)
    if seed is None:
        # A DICT-ONLY ADAPTER IS STILL BOUNDED, AND ROUND P5 IS WHERE THAT STOPPED BEING A SKIP.
        # `legion` and `pntmap` ship no byte fixture, but both reach `json.loads` on a byte or
        # text payload — the bound is about the octets a caller hands over, and those two accept
        # octets like the other twelve. So the twin is serialised back to the compact JSON a
        # caller would have sent and THAT is repeated up to the bound. Skipping here instead
        # would have left the only two adapters whose parser is a general-purpose JSON reader as
        # the only two whose bound nothing exercised.
        document = next((raw for _, raw in payloads if isinstance(raw, (dict, list))), None)
        if document is not None:
            seed = json.dumps(document, separators=(",", ":"), default=str).encode("utf-8")
    if seed is None:
        return _verdict(SKIP, reason="the declared bound is a byte count and this adapter ships "
                                     "no fixture at all to repeat", declared=False,
                        max_input_bytes=limits.max_input_bytes)
    bound = limits.max_input_bytes
    oversized = (bytes(seed) * (bound // max(1, len(seed)) + 2))[:bound + 1]
    try:
        objects = _fresh(adapter, clock).to_cdm(oversized)
    except CRASH_CLASSES as e:
        return _verdict(FAIL, reason=f"an oversized payload raised a crash class: "
                                     f"{type(e).__name__}", max_input_bytes=bound)
    except Exception as e:                                     # noqa: BLE001 - the refusal itself
        return _verdict(PASS, max_input_bytes=bound, bytes_fed=len(oversized),
                        refusal=f"{type(e).__module__}.{type(e).__name__}")
    return _verdict(FAIL, reason=f"{len(oversized)} bytes is one more than the declared "
                                 f"max_input_bytes {bound} and the adapter accepted it, "
                                 f"returning {len(objects)} object(s)", max_input_bytes=bound)


#: Worst-wins order for the per-adapter aggregate (§34). One source path may be PRESERVED in one
#: fixture and DROPPED in another — the two fixtures exercise different branches of one parser —
#: and a report that listed the path twice would let a reader take the kinder line. The adapter is
#: accountable for the worst outcome any of its own fixtures produced, so that is what is reported.
LOSS_SEVERITY: tuple[str, ...] = ("DROPPED", "UNSUPPORTED", "RESIDUAL", "DERIVED", "NORMALIZED",
                                  "PRESERVED")


def ledger_summary(base: dict | None) -> dict:
    """F02: the path-bound ledger's reading over every fixture the harness ran it on.

    Counts are summed per category and per loss kind across fixtures; the diagnostics are the
    union of LOST lines, de-duplicated on (source path, loss kind) and capped, and never carry a
    value. `basis` is the harness's own reading — `ledger` where the adapter declares
    `MAPPINGS`, `heuristic` otherwise — so a consumer cannot mistake an absence of ledger
    findings for a ledger that found nothing.
    """
    preservation = (base or {}).get("preservation") or {}
    counts = {name: 0 for name in lossless.LEDGER_CATEGORIES}
    losses = {kind: 0 for kind in lossless.LOSS_KINDS}
    seen: dict[tuple[str, str | None], dict] = {}
    fixtures = 0
    for result in (base or {}).get("results", []):
        book = result.get("preservation") or {}
        if book.get("basis") != "ledger":
            continue
        fixtures += 1
        for name, n in book.get("counts", {}).items():
            counts[name] = counts.get(name, 0) + n
        for kind, n in book.get("losses", {}).items():
            losses[kind] = losses.get(kind, 0) + n
        for diagnostic in book.get("diagnostics", []):
            if diagnostic["category"] == "LOST":
                seen.setdefault((diagnostic["source_path"], diagnostic["loss"]), diagnostic)
    return {"basis": preservation.get("basis", "heuristic"),
            "declared_mappings": preservation.get("declared_mappings", 0),
            "fixtures": fixtures, "counts": counts, "losses": losses,
            "diagnostics": list(seen.values())[:harness.DIAGNOSTIC_LIMIT],
            "diagnostics_truncated": max(0, len(seen) - harness.DIAGNOSTIC_LIMIT)}


def loss_report(adapter: Adapter, payloads: list[tuple[str, Any]],
                base: dict | None = None) -> dict:
    """§34's six categories over every classifiable fixture, aggregated per source path, and —
    since F02 — the ledger's reading under `ledger` (`ledger_summary`), from the harness report
    `base` when the caller has one.

    THE GUARD IS `harness.run`'s LOSSLESS SKIP AND NOT A NEW ONE. The lossless comparison needs a leaf
    structure, so a non-JSON payload has nothing to classify — the harness SKIPs check D for
    exactly those fixtures and says so. Classifying them anyway would put the whole byte string
    in DROPPED and report a catastrophic loss for every binary format in the repository, which is
    the false positive `lossless.py`'s own docstring warns is the expensive kind. `skipped` counts
    them, so the number is visible rather than hidden in a smaller denominator.

    UNSUPPORTED IS READ FROM THE MANIFEST AND NOWHERE ELSE. `manifest.unsupported_paths()` returns
    only the paths a STRUCTURED `Limitation` declares; a prose limitation contributes nothing, on
    §34's own words — an "explicit documented exception" a classifier cannot read is not one.
    """
    declared = manifest.unsupported_paths(adapter.metadata.limitations)
    worst: dict[str, str] = {}
    classified = skipped = 0
    for _name, raw in payloads:
        if not isinstance(raw, (dict, list)):
            skipped += 1
            continue
        try:
            objects = _dump(list(adapter.to_cdm(raw)))
        except Exception:                               # noqa: BLE001 - A already reported it
            skipped += 1
            continue
        classified += 1
        report = lossless.classify(raw, objects, type(adapter).TRANSFORMS, declared)
        for category in lossless.CATEGORIES:
            rank = LOSS_SEVERITY.index(category)
            for path in getattr(report, category):
                if path not in worst or rank < LOSS_SEVERITY.index(worst[path]):
                    worst[path] = category
    paths = {category: sorted(p for p, c in worst.items() if c == category)
             for category in lossless.CATEGORIES}
    return {"paths": paths,
            "counts": {category: len(paths[category]) for category in lossless.CATEGORIES},
            "total": len(worst),
            "fixtures": {"classified": classified, "skipped": skipped,
                         "skipped_because": "a non-JSON payload has no comparable leaf structure "
                                            "(harness.run's lossless SKIP, the same guard check D "
                                            "uses)"},
            "unsupported_declared": list(declared),
            "ledger": ledger_summary(base)}


def loss_lines(report: dict) -> list[str]:
    """§34's six-line summary for `--format text`. Always six lines, in §34's order."""
    counts = report["counts"]
    width = max(len(name) for name in lossless.CATEGORIES)
    return [f"  {name.ljust(width)}  {counts[name]}" for name in lossless.CATEGORIES]


def eligible_level(checks: dict[str, dict]) -> str:
    """ARCHITECTURE.md §3.6, steps 2–7, and nothing else.

    Rule 3 satisfies a requirement with PASS. Rule 4 lets a SKIP with a declared inapplicability
    through. Rule 6 blocks on FAIL and on an undeclared SKIP, and blocks every rung above. L5 is
    "every check APPLICABLE to this adapter". L0 needs a document rather than a check, so it is
    what remains when L1 is blocked; L6 is never computed here (rule 7).
    """
    def satisfied(letter: str) -> bool:
        entry = checks[letter]
        if entry["verdict"] == PASS:
            return True
        return entry["verdict"] == SKIP and entry["declared_inapplicable"]

    reached = "L0"
    for level, required in LEVEL_REQUIREMENTS:
        if not all(satisfied(letter) for letter in required):
            return reached
        reached = level
    if all(satisfied(letter) for letter in CHECK_LETTERS):
        return "L5"
    return reached


def run(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock | None = None,
        frozen_at: _dt.datetime | None = None, schema_dir: pathlib.Path | None = None,
        offset_cap: int = DEFAULT_OFFSET_CAP, timeout_s: float = DEFAULT_TIMEOUT_S,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
        diagnostics: dict | None = None, limits: ResourceLimits | None = None) -> dict:
    """Every check, once, over one adapter. Raises `harness.NoFixturesFound` on a bad invocation.

    H and N share ONE `ParserWorker` (F03): one spawn per adapter rather than two, the same
    per-case deadline and the same clean per-case instance either way. `diagnostics`, when the
    caller passes a dict, receives the worker's volatile record — pids, exit codes, durations —
    which the report itself never carries. `limits` (F06) is the memory/CPU envelope for that
    worker; `UnsupportedResourceLimit` is raised before anything runs where the platform cannot
    enforce a requested field.
    """
    frozen_at = frozen_at or times.FROZEN_NOW
    clock = clock or times.frozen_clock(frozen_at)
    base = harness.run(adapter, fixtures, schema_dir=schema_dir)
    payloads = [(path.name, harness.load_raw(path)) for path in _fixtures(fixtures)]

    with ParserWorker(adapter, clock=clock, timeout_s=timeout_s,
                      startup_timeout_s=startup_timeout_s, diagnostics=diagnostics,
                      limits=limits) as worker:
        return _run_checks(adapter, fixtures, payloads=payloads, base=base, clock=clock,
                           frozen_at=frozen_at, offset_cap=offset_cap, timeout_s=timeout_s,
                           worker=worker)


def _run_checks(adapter: Adapter, fixtures: pathlib.Path, *, payloads, base, clock, frozen_at,
                offset_cap, timeout_s, worker: ParserWorker) -> dict:
    checks: dict[str, dict] = {}
    for check in CHECKS:
        if check.harness_key is not None:
            entry = _fold(base, check.letter, check.harness_key)
            if check.letter == "E" and entry["verdict"] == SKIP:
                declared, reason = _roundtrip_declaration(adapter)
                entry["declared_inapplicable"] = declared
                entry["reason"] = reason or entry.get(
                    "reason", "the harness could not compare the emitted form structurally")
            if check.letter == "D":
                # F02: which basis the verdict rests on. The harness folded the ledger into
                # the same column, so a LOST leaf is already a FAIL here; what this adds is
                # the reading a consumer needs to weigh a PASS — proof or heuristic. Under
                # `details`, because §18 fixes the entry's own keys.
                entry["details"]["basis"] = (base.get("preservation") or {}).get(
                    "basis", "heuristic")
            checks[check.letter] = entry
    checks["G"] = check_deterministic(adapter, payloads, clock=clock)
    checks["H"] = check_malformed(adapter, fixtures, clock=clock, timeout_s=timeout_s,
                                  worker=worker)
    checks["I"] = check_unknown_fields(adapter, fixtures, clock=clock)
    checks["J"] = check_temporal(adapter, payloads, clock=clock, frozen_at=frozen_at)
    checks["K"] = check_identity(adapter, payloads, clock=clock)
    checks["L"] = check_version(adapter, payloads, clock=clock,
                                supported=f"{version.parse(SCHEMA_VERSION)[0]}.x")
    checks["M"] = check_streaming(adapter)
    checks["N"] = check_parser_robustness(adapter, fixtures, clock=clock, offset_cap=offset_cap,
                                          timeout_s=timeout_s, worker=worker)
    checks["O"] = check_resource_limits(adapter, payloads, clock=clock)

    failed = [letter for letter in CHECK_LETTERS if checks[letter]["verdict"] == FAIL]
    return {
        "loss_report": loss_report(adapter, payloads, base),
        "adapter": {"id": adapter.metadata.id, "name": adapter.name,
                    "adapter_version": adapter.metadata.adapter_version,
                    "direction": adapter.direction, "system": adapter.system,
                    "declared_maturity": adapter.metadata.maturity.level.value,
                    "fixtures": str(fixtures)},
        "checks": {letter: checks[letter] for letter in CHECK_LETTERS},
        "result": "NON-CONFORMANT" if failed else "CONFORMANT",
        "maturity_eligible": eligible_level(checks),
        "generated_with": {"package": PACKAGE_VERSION, "schema": SCHEMA_VERSION,
                           "adapter_api": version.ADAPTER_API_VERSION},
    }


def exit_status(report: dict, required: tuple[str, ...] = (), *, strict: bool = False) -> int:
    """§19: a required check that FAILs or SKIPs makes the INVOCATION unsuccessful.

    `conformance.py:754`'s idiom exactly, one namespace over: nothing here rewrites a verdict.
    `--require M` against an adapter that declares no streaming leaves `M = SKIP` in the report
    and returns non-zero, because collapsing the first into the second would put the caller's
    command line into the conformance record.

    `strict` IS A THIRD REASON TO EXIT NON-ZERO AND NOT A FOURTH VERDICT (F4.4, default). A
    DROPPED path is a fact the loss report states; check D's verdict stays the harness's, exactly
    as the paragraph above says no verdict is rewritten here. The two are not the same test and
    the difference is live: an adapter that DECLARES a source path unsupported still fails check
    D — the value really did vanish — while its DROPPED count is 0, because the exception was
    documented in a form a machine can read. `--strict` asks the second question.
    """
    for letter in (required or CHECK_LETTERS):
        if report["checks"][letter]["verdict"] == FAIL:
            return EXIT_FAILED
    for letter in required:
        if report["checks"][letter]["verdict"] == SKIP:
            return EXIT_FAILED
    if strict and report["loss_report"]["counts"]["DROPPED"]:
        return EXIT_FAILED
    return EXIT_OK


def render_report(report: dict) -> str:
    """§18's layout exactly, then the reasons §17 requires a SKIP to carry.

    §18 fixes the block down to `MATURITY ELIGIBLE:`. It does not forbid saying why a check was
    inapplicable, and §17 requires it ("the report says WHY it was inapplicable"), so the reasons
    follow the block rather than being interleaved with it — the fixed shape stays parseable and
    the obligation is met.
    """
    lines = ["Synapse Conformance Suite", f"Adapter: {report['adapter']['id']}", ""]
    for check in CHECKS:
        entry = report["checks"][check.letter]
        lines.append(f"{check.letter} {check.name}".ljust(28) + entry["verdict"])
    lines += ["", f"RESULT: {report['result']}",
              f"MATURITY ELIGIBLE: {report['maturity_eligible']}"]
    loss = report.get("loss_report")
    if loss:
        lines += ["", "LOSS REPORT (§34), source paths by category, worst outcome across "
                      f"{loss['fixtures']['classified']} classifiable fixture(s):"]
        lines += loss_lines(loss)
        if loss["fixtures"]["skipped"]:
            lines.append(f"  ({loss['fixtures']['skipped']} fixture(s) not classified: "
                         f"{loss['fixtures']['skipped_because']})")
        book = loss.get("ledger") or {}
        if book.get("basis") == "ledger":
            lines += ["", f"PRESERVATION LEDGER (F02), {book['declared_mappings']} declared "
                          f"mapping(s) over {book['fixtures']} fixture(s), source leaves by "
                          "category:"]
            width = max(len(name) for name in lossless.LEDGER_CATEGORIES)
            lines += [f"  {name.ljust(width)}  {book['counts'][name]}"
                      for name in lossless.LEDGER_CATEGORIES]
            lines += [f"  {d['source_path']}: {d['loss']} — expected {d['expected']['destination']}"
                      f" by rule {d['expected']['rule']}; observed "
                      f"{d['observed']['destination'] or 'nothing'} ({d['observed']['type']})"
                      for d in book.get("diagnostics", [])]
        else:
            lines += ["", "PRESERVATION LEDGER (F02): not run — the adapter declares no MAPPINGS; "
                          "check D above is the value-presence heuristic and is not proof of "
                          "preservation"]
    reasons = [(c, report["checks"][c.letter]) for c in CHECKS
               if report["checks"][c.letter]["verdict"] != PASS]
    if reasons:
        lines += ["", "why, for every check that is not PASS "
                      "(a SKIP is never a PASS — ARCHITECTURE.md §4.7):"]
        for check, entry in reasons:
            declared = " [declared inapplicable]" if entry["declared_inapplicable"] else ""
            lines.append(f"  {check.letter} {entry['verdict']}{declared}  "
                         f"{entry.get('reason', '(no reason recorded)')}")
    return "\n".join(lines)


def render_roster(adapters: dict[str, type[Adapter]]) -> str:
    """`synapse conformance list`: the roster with what a conformance caller needs from it."""
    if not adapters:
        return ("no adapters are registered. synapse_cdm.adapters failed to import — this is a "
                "broken installation rather than an empty inventory")
    width = max(len(name) for name in adapters)
    lines = [f"{len(adapters)} adapters registered. Run one with "
             f"`synapse conformance run --adapter <name>`.", "",
             f"{'name'.ljust(width)}  {'version'.ljust(7)}  {'direction'.ljust(13)}  "
             f"{'maturity'.ljust(8)}  {'claim'.ljust(11)}  unknown-fields",
             "-" * (width + 2 + 7 + 2 + 13 + 2 + 8 + 2 + 11 + 2 + 14)]
    for name, cls in adapters.items():
        metadata = cls.metadata
        lines.append(f"{name.ljust(width)}  {cls.version.ljust(7)}  "
                     f"{cls.direction.ljust(13)}  {metadata.maturity.level.value.ljust(8)}  "
                     f"{metadata.claim_status.value.ljust(11)}  "
                     f"{metadata.capabilities.unknown_fields.value}")
    lines += ["", "The maturity column is what the adapter DECLARES. What the suite computes "
                  "from a run is `MATURITY ELIGIBLE`, and the two are different statements: one "
                  "is a claim about evidence, the other is this repository's evidence today."]
    return "\n".join(lines)


def _required(value: str, parser: argparse.ArgumentParser) -> tuple[str, ...]:
    letters = tuple(part.strip().upper() for part in value.split(",") if part.strip())
    unknown = [letter for letter in letters if letter not in BY_LETTER]
    if unknown:
        parser.error(f"--require names {unknown}, which are not checks. The checks are "
                     f"{','.join(CHECK_LETTERS)} (see `synapse conformance list`)")
    return letters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command")
    conformance = commands.add_parser("conformance", help="the Synapse Conformance Suite")
    actions = conformance.add_subparsers(dest="action")

    run_parser = actions.add_parser("run", help="run every check over one adapter")
    run_parser.add_argument("--adapter", default=None,
                            help="registered name (pntmap) or module:ClassName")
    # §50's pipeline runs the sweep as ONE stage and hands ONE artefact to the release notes and
    # to the witness. Fourteen separate invocations produce fourteen files whose combination is
    # the caller's problem, and a combination assembled by a shell loop is not something
    # `gates/witness_verify.py` can hash. `--all` exists so that the sweep has a single output
    # with a single digest.
    run_parser.add_argument("--all", action="store_true",
                            help="every adapter this package ships, as one report (§50). "
                                 "Mutually exclusive with --adapter")
    run_parser.add_argument("--fixtures", type=pathlib.Path, default=None,
                            help="directory of payloads. Omitted, the fixtures that came with "
                                 "the installed package are used")
    run_parser.add_argument("--schemas", type=pathlib.Path, default=None,
                            help="validate against the published schemas in this directory")
    run_parser.add_argument("--format", default="text", choices=("text", "json"),
                            help="report shape (default text)")
    run_parser.add_argument("--require", default=None,
                            help="comma-separated letters that MUST pass; a FAIL or a SKIP among "
                                 "them exits non-zero (§19)")
    run_parser.add_argument("--strict", action="store_true", default=None,
                            help="a non-empty DROPPED category in the loss report exits non-zero "
                                 "(§34). Implied by --require naming D; pass --no-strict to ask "
                                 "for D's verdict without the loss report's")
    run_parser.add_argument("--no-strict", dest="strict", action="store_false",
                            help=argparse.SUPPRESS)
    run_parser.add_argument("--now", default=None,
                            help="freeze received_at at this RFC 3339 instant "
                                 f"(default {times.render(times.FROZEN_NOW)})")
    run_parser.add_argument("--synthetic", default="true", choices=("true", "false"))
    run_parser.add_argument("--offset-cap", type=int, default=DEFAULT_OFFSET_CAP,
                            help=f"check N's truncation offsets per fixture (default "
                                 f"{DEFAULT_OFFSET_CAP}, F2.5)")
    run_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                            help="seconds one adversarial case may take before its worker is "
                                 f"killed and the case is PARSER_TIMEOUT (default "
                                 f"{DEFAULT_TIMEOUT_S})")
    run_parser.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT_S,
                            help="seconds the parser worker may take to start and construct the "
                                 f"adapter (default {DEFAULT_STARTUP_TIMEOUT_S})")
    run_parser.add_argument("--diagnostics", type=pathlib.Path, default=None,
                            help="write the parser workers' volatile record (pids, exit codes, "
                                 "durations) to this JSON file; it never enters the report")
    run_parser.add_argument("--memory-limit-bytes", type=int, default=None,
                            help="RLIMIT_AS for each parser worker (F06); refused with exit "
                                 f"{EXIT_USAGE} where this platform cannot enforce it — Linux "
                                 "enforces it, macOS and Windows do not")
    run_parser.add_argument("--cpu-limit-seconds", type=int, default=None,
                            help="RLIMIT_CPU for each parser worker (F06); refused with exit "
                                 f"{EXIT_USAGE} where this platform cannot enforce it — Linux "
                                 "enforces it, macOS and Windows do not")

    actions.add_parser("list", help="the registered adapters, with declared maturity")

    # `synapse evidence …` and `synapse badges …` attach HERE rather than growing two more
    # console scripts, because `synapse` is the one entry point ARCHITECTURE.md §8 names and a
    # third script would be a third thing to document, package and keep in step. The evidence
    # module owns its own parser; this delegates to it with the remaining argv, which keeps the
    # two commands' help text where their code is.
    commands.add_parser("evidence", help="generate, verify and inspect evidence records (§31)",
                        add_help=False)
    commands.add_parser("badges", help="write shields.io endpoint JSON from evidence (§35)",
                        add_help=False)
    commands.add_parser("release-notes", help="render §52's ten fields for a release",
                        add_help=False)
    return parser


def shipped_adapters() -> dict[str, type[Adapter]]:
    """The adapters this PACKAGE ships — not everything `REGISTRY` happens to hold.

    Every `Adapter` subclass registers itself at class-definition time, so `roster()` also carries
    any adapter a caller has merely IMPORTED: a third party's class, or a test double. A release's
    conformance sweep must not grow or shrink with what else is in the interpreter, so `--all`
    reads this and not `roster()`. `tests/test_cdm_suite.py` had already written the same filter
    for its own parametrisation and its docstring names the hazard; the rule lives in
    `adapter.shipped`, beside `roster()`, since 2026-09-16, and this is the suite's name for it.
    """
    return shipped()


def packaged_label(adapter_class: type[Adapter]) -> str:
    """`<packaged>/<directory>`: the fixture root's name for a packaged directory, path-free.

    The DIRECTORY and not the adapter's name, because the two differ for `stanag4609` (`klv`) and
    `stanag4676` (`nits`) and `evidence.FileHash.path` is already spelled relative to the fixture
    root as `klv/…`. Until 2026-09-16 the sweep wrote the adapter name here, so one record named
    its fixtures two different ways.
    """
    return f"<packaged>/{adapter_class.fixture_dir or adapter_class.name}"


def portable(report: dict, label: str) -> dict:
    """A COPY of `run()`'s report with the fixtures path replaced by `label`.

    `run()` reports the directory it actually read, which is an absolute path and is the right
    thing for a person debugging one adapter. It is the wrong thing for any artefact two machines
    have to agree on: the `--all` sweep, whose SHA-256 goes into a witness record, and — since
    2026-09-16 — an evidence record, which `verify` reproduces from another checkout. Both call
    this; `run()` itself is not changed, and `tests/test_cdm_suite.py` pins that the single-adapter
    CLI still names the directory it read.
    """
    report = copy.deepcopy(report)
    report["adapter"]["fixtures"] = label
    return report


def _write_diagnostics(target: pathlib.Path | None, diagnostics: dict[str, dict]) -> None:
    """The parser workers' volatile record, to the file the caller asked for and NOT to stdout:
    stdout is the evidence, and a pid or a duration in it would make its digest a function of
    the machine. A restart — a killed or dead worker — is announced on stderr regardless, one
    line per adapter, because it is the one fact here a person running the sweep should see."""
    for name, record in diagnostics.items():
        if record.get("restarts"):
            print(f"synapse conformance: {name}: parser worker restarted "
                  f"{record['restarts']} time(s) — see the H/N outcome codes", file=sys.stderr)
    if target is not None:
        target.write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n")


def _sweep(args, required: tuple[str, ...], *, strict: bool, frozen,
           limits: ResourceLimits | None = None) -> int:
    """`--all`: every shipped adapter, one document, one exit code.

    THE FIXTURES PATH IS RELATIVISED HERE AND IN `evidence.generate`, THROUGH `portable`. `run()`
    reports the directory it actually read, which is an absolute path and is the right thing for
    a person debugging one adapter. It is the wrong thing for an artefact whose SHA-256 goes into
    a witness record: two runners with different checkout paths would produce two digests for one
    tree, and §53's "deterministic and verifiable" would be false by construction. `run()` is not
    changed, so `cdm-harness`'s and `synapse conformance run --adapter`'s output does not move.
    """
    reports: dict[str, dict] = {}
    diagnostics: dict[str, dict] = {}
    worst = EXIT_OK
    for name, adapter_class in sorted(shipped_adapters().items()):
        adapter = adapter_class(clock=times.frozen_clock(frozen),
                                synthetic=args.synthetic == "true")
        diagnostics[name] = {}
        try:
            report = run(adapter, packaged_fixtures(adapter_class),
                         clock=times.frozen_clock(frozen), frozen_at=frozen,
                         schema_dir=args.schemas, offset_cap=args.offset_cap,
                         timeout_s=args.timeout, startup_timeout_s=args.startup_timeout,
                         diagnostics=diagnostics[name], limits=limits)
        except (harness.NoFixturesFound, harness.NoSchemasFound) as e:
            print(f"synapse conformance: {name}: {e}", file=sys.stderr)
            return EXIT_USAGE
        report = portable(report, packaged_label(adapter_class))
        reports[name] = report
        status = exit_status(report, required, strict=strict)
        worst = worst or status
    document = {
        "sweep": "synapse conformance run --all",
        "required": list(required),
        "strict": strict,
        "generated_with": {"package": PACKAGE_VERSION, "schema": SCHEMA_VERSION,
                           "adapter_api": version.ADAPTER_API_VERSION},
        "adapters": reports,
        "conformant": sorted(n for n, r in reports.items() if r.get("result") == "CONFORMANT"),
    }
    _write_diagnostics(args.diagnostics, diagnostics)
    if args.format == "json":
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        for name in sorted(reports):
            print(render_report(reports[name]))
        print(f"\n{len(document['conformant'])}/{len(reports)} CONFORMANT")
    return worst


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "release-notes":
        # Deferred for the same reason `evidence` is: the renderer imports nothing from here, but
        # keeping the import inside the branch means `synapse conformance` costs nothing for it.
        from synapse_cdm import release_notes
        return release_notes.main(argv[1:])
    if argv and argv[0] in ("evidence", "badges"):
        # Deferred, and the reason is the same cycle `schemas.evidence_schema()` names: the
        # evidence module imports this one. Importing it at the top would be a cycle; importing
        # it here costs nothing until somebody asks for the command.
        from synapse_cdm import evidence as evidence_module
        if argv[0] == "badges":
            return evidence_module.main(["badges", *argv[1:]])
        return evidence_module.main(argv[1:])
    args = parser.parse_args(argv)
    if args.command != "conformance" or getattr(args, "action", None) is None:
        parser.error("usage: synapse conformance run --adapter <name> | synapse conformance list")
    if args.action == "list":
        print(render_roster(roster()))
        return EXIT_OK

    if args.all and args.adapter:
        parser.error("--all and --adapter name two different sweeps; pass one of them")
    if not args.all and not args.adapter:
        parser.error("pass --adapter <name> for one adapter, or --all for every shipped adapter")

    required = _required(args.require, parser) if args.require else ()
    # F4.4's default, spelled as one line: strictness is ON when the caller asked for D and OFF
    # otherwise, and an explicit --strict/--no-strict overrides both. `None` is what
    # "the caller did not say" looks like, which is why the flag's default is not `False`.
    strict = ("D" in required) if args.strict is None else args.strict
    frozen = times.parse(args.now) if args.now else times.FROZEN_NOW
    limits = ResourceLimits(memory_bytes=args.memory_limit_bytes,
                            cpu_seconds=args.cpu_limit_seconds)
    try:
        limits.validate()       # F06: before any adapter is loaded or any worker spawned
    except UnsupportedResourceLimit as e:
        print(f"synapse conformance: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.all:
        return _sweep(args, required, strict=strict, frozen=frozen, limits=limits)

    try:
        adapter_class = load_adapter(args.adapter)
    except LookupError as e:
        print(f"synapse conformance: {e}", file=sys.stderr)
        return EXIT_USAGE
    adapter = adapter_class(clock=times.frozen_clock(frozen), synthetic=args.synthetic == "true")

    fixtures = args.fixtures
    if fixtures is None:
        if not is_shipped(adapter_class):
            print("synapse conformance: "
                  f"{harness.fixtures_required_message(args.adapter, adapter_class)}",
                  file=sys.stderr)
            return EXIT_USAGE
        fixtures = packaged_fixtures(adapter_class)

    diagnostics: dict[str, dict] = {args.adapter: {}}
    try:
        report = run(adapter, fixtures, clock=times.frozen_clock(frozen), frozen_at=frozen,
                     schema_dir=args.schemas, offset_cap=args.offset_cap,
                     timeout_s=args.timeout, startup_timeout_s=args.startup_timeout,
                     diagnostics=diagnostics[args.adapter], limits=limits)
    except (harness.NoFixturesFound, harness.NoSchemasFound) as e:
        print(f"synapse conformance: {e}", file=sys.stderr)
        return EXIT_USAGE
    _write_diagnostics(args.diagnostics, diagnostics)
    print(json.dumps(report, indent=2, sort_keys=True) if args.format == "json"
          else render_report(report))
    return exit_status(report, required, strict=strict)


if __name__ == "__main__":
    raise SystemExit(main())
