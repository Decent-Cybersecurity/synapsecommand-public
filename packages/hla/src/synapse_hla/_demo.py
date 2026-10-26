"""The orchestration behind `synapse-hla demo` (R38, R39, OPS-13, OPS-18; round R8).

WHAT RUNS
---------
The command line checks the FOM pins, makes the output directory and finds the three executables
(the worker, `rtinode`, the synthetic publisher); this module then runs the isolated synthetic
reference exercise and writes nothing but the run directories under it:

1. `rtinode`, bound explicitly to 127.0.0.1 on a port this module chose (R38), with `LC_ALL=C`
   so that its one start-up error is the C library's wording (NAT-18). A start that ends with
   status 1 and "Address already in use" on stderr within the start-up window is tried again on
   another port, at most five starts in all (R38's "at most five times" read so that both of its
   readings hold); any other early end fails the demo. Ready means a raw TCP connect to the port
   succeeded (polled for a bounded time, NAT-18) and rtinode was still running when its start-up
   window closed: a connect alone could have reached whoever else holds a busy port.
2. Two runs, each with a federation of its own named `SC_DEMO_` and 16 random lowercase
   hexadecimal digits (OPV-05; the name enters no golden value): `main`, the configuration of
   `examples/config-demo.json` with only `endpoint` and `federation_name` replaced (OPS-13, so
   the entity id is the fixture's `781e68de-166f-531c-b906-4a2d087f817e`), and `no-time`, the
   same with time policy `none` and session id `example-001-none` (R39). In each, the publisher
   creates the federation from the five hashed modules and reports their digests (R11), then
   the observer session runs through `host.run_session` in a child process of its own (the
   command line's host process, as observe runs it), and the publisher is paced through the
   barrier of R38: this module acknowledges each planned step on the publisher's stdin once the
   observer's capture shows it (the capture line is written and flushed before the reducer sees
   it, R34), never by a sleep. Every line the publisher writes is checked as it is read: one of
   its own event kinds with exactly its members, its fixed forms and vocabulary, in R38's order
   (modules, federation, object, then the barriers one by one); anything else fails the run at
   once with a fixed reason, and nothing such a line carried reaches demo.json. After the
   removal is captured the observer is stopped in order
   (SIGTERM to its host: resign, disconnect, COMPLETE), and only then is the publisher told that
   the observer has resigned, so that it can resign and destroy the federation it created (A
   destroy that succeeds is the evidence that the observer left and created nothing).
3. Each live capture is verified and replayed offline into its replay directory, and the
   semantic checkpoints of OPS-13 are judged against the packaged vectors (identity.json,
   session-checkpoints.json, the bundled capture's two Spatial values): identifier, PLATFORM,
   FRIENDLY, positions and course within section 9's tolerances, one entity id, the removed
   notice, non-decreasing `valid_from`, the replay byte-identical to the live output except the
   completion fields SPEC:158 names, and zero upserts with snapshots present in the `none` run.
   Transport and the frames' bytes against the bundled capture are never compared (NAT-16).
4. `rtinode` is stopped by its PID, and the demo checks that every process it started (and
   every worker the hosts reported) has been reaped and that the port no longer accepts a
   connection. Anything left behind is a failure (R39, SPEC:211); nothing is ever stopped by
   name.

`demo.json` (`local_schemas/demo.schema.json`) records the ports, names, PIDs, the module digests
the publisher reported, the steps and refresh reflections as the capture shows them, the
checkpoint results, the evidence class (development evidence on any build this round makes,
CR-L04) and `external_customer_interoperability` NOT_TESTED (OPS-01). It states that OpenRTI is
the tested reference and that neither a customer simulator nor a second RTI implementation was
tested (R39).

WHAT THIS MODULE MAY TOUCH
--------------------------
It starts and signals processes, reads the clocks for its bounds, reads the run directories the
hosts write, and opens loopback TCP sockets for two things only: choosing a free port and the
readiness probe of NAT-18. Every address it binds or connects to is 127.0.0.1. Every process is
started from an absolute path with an argument vector (never a shell, never a PATH search), in a
process group of its own, so a terminal's interrupt reaches the command alone, which then stops
everything in order.

Limits and timing values come from one frozen `DemoSeams` (`V1`); only tests pass another.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import platform
import secrets
import select
import signal
import socket
import stat
import time
from dataclasses import dataclass, field
from typing import Callable

from synapse_hla import _examples, _resources, _runfile, canonical, capture, config, errors, host
from synapse_hla.replay import replay_with

#: CR-L16: the publisher's one override and its fixed place beside the worker's.
PUBLISHER_VARIABLE = "SYNAPSE_HLA_PUBLISHER"
PUBLISHER_NAME = "sc-hla-publisher"
PUBLISHER_LOCATION = os.path.join(os.path.dirname(host.WORKER_LOCATION), PUBLISHER_NAME)
#: CR-L16: what `sc-hla-publisher --version` prints, exactly.
PUBLISHER_VERSION_LINE = (b'{"name":"sc-hla-publisher","profile":"SC-HLA-RPR2-OBS-1",'
                          b'"version":"1.0.0"}\n')
#: OPV-04: rtinode's one override and its fixed place beside the worker's.
RTINODE_VARIABLE = "SYNAPSE_HLA_RTINODE"
RTINODE_NAME = "rtinode"
RTINODE_LOCATION = os.path.join(os.path.dirname(host.WORKER_LOCATION), RTINODE_NAME)

#: The fixed layout of OPS-13 inside the demo's directory.
DEMO_FILE = "demo.json"
DIRECTORIES = ("main", "main-replay", "no-time", "no-time-replay")
SCHEMA = "demo.schema.json"
DEMO_VERSION = 1

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"

LOOPBACK = "127.0.0.1"
#: The pinned OpenRTI the exercise runs on (SPEC:20) and what was, and was not, tested (R39).
TESTED_REFERENCE = "OpenRTI 814a210978b7faafd65affbe70a2e25679921b23"
SCOPE = ("OpenRTI is the tested reference: the observer, the synthetic publisher and rtinode of "
         "this run all use it. Neither a customer simulator nor a second RTI implementation was "
         "tested.")
#: OPV-05: the demo federations' names.
FEDERATION_PREFIX = "SC_DEMO_"
#: SPEC:50: the class the publisher registers at, and the one the observer subscribes at (and so
#: is told of, NAT-04).
GROUND_VEHICLE = "HLAobjectRoot.BaseEntity.PhysicalEntity.Platform.GroundVehicle"
PHYSICAL_ENTITY = "HLAobjectRoot.BaseEntity.PhysicalEntity"
#: The publisher's own user tags (tools/publisher/publisher.cpp): which planned step a capture
#: line belongs to, or an answer to an update request.
REFRESH_TAG = b"refresh"

#: The publisher's stdout (tools/publisher/publisher.cpp): one ASCII JSON object per line, of
#: these kinds with exactly these members. Its longest line, `modules`, has 487 bytes; a line
#: longer than this bound is no event of it.
_EVENT_BYTES = 768
_EVENT_MEMBERS = {
    "modules": frozenset({"event", "sha256"}),
    "created": frozenset({"event", "federation"}),
    "ready": frozenset({"event", "class", "object_name", "objects"}),
    "waiting": frozenset({"event", "barrier"}),
    "acknowledged": frozenset({"event", "barrier"}),
    "sent": frozenset({"event", "step"}),
    "refresh": frozenset({"event", "attributes"}),
    "resigned": frozenset({"event"}),
    "destroyed": frozenset({"event", "federation"}),
    "disconnected": frozenset({"event"}),
    "failure": frozenset({"event", "stage", "reason"}),
    "cleanup": frozenset({"event", "stage", "reason"}),
}
#: The fixed vocabulary of its failure events: the stage it was in, and its own reason or the
#: type of an RTI exception (never the RTI's text). A test holds these to the publisher's source.
PUBLISHER_STAGES = frozenset({
    "start", "modules", "connect", "create", "join", "publish", "reserve", "register", "barrier",
    "step", "identity", "load", "remove", "resign", "destroy", "disconnect"})
PUBLISHER_EXCEPTIONS = frozenset({
    "FederationExecutionAlreadyExists", "FederationExecutionDoesNotExist",
    "FederatesCurrentlyJoined", "FederateNameAlreadyInUse", "ConnectionFailed", "CouldNotOpenFDD",
    "ErrorReadingFDD", "InconsistentFDD", "CouldNotCreateLogicalTimeFactory", "NameNotFound",
    "NotConnected", "RTIinternalError", "RTIexception"})
PUBLISHER_REASONS = PUBLISHER_EXCEPTIONS | frozenset({
    "barrier_pipe", "barrier_closed", "barrier_protocol", "barrier_timeout", "callback",
    "connection_lost", "stopped", "stdout", "module_unreadable", "module_pin", "module_encoding",
    "name_reservation", "registered_class"})
_CLEANUP_STAGES = frozenset({"resign", "destroy", "disconnect"})
#: The name the main scenario's object is reserved and registered under.
_OBJECT_NAME = "SYNTHETIC-001"
_NOT_AN_EVENT = "the publisher wrote a line that is not one of its events"
_OUT_OF_ORDER = "the publisher's events came out of their order"
_HEX = frozenset("0123456789abcdef")


def _bounded_int(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _word(value, vocabulary: frozenset) -> bool:
    return type(value) is str and value in vocabulary


def _is_sha256(value) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX


#: Section 9's validation tolerances (SPEC:144): degrees and metres; speeds are compared within
#: their own emission rounding (6 decimals, SPEC:146), which is stricter than the metre bound.
DEGREES = 1e-8
METRES = 1e-4
SPEEDS = 1e-6

_SECOND = 1_000_000_000
_MILLISECOND = 1_000_000
_READ_CHUNK = 1 << 16
#: The most a child may write on a channel this module reads before it is a fault, not data.
_CHANNEL_BYTES = 1 << 20
_TICK_MS = 10
_RTINODE_ADDRESS_IN_USE = b"Address already in use"


def _clock_monotonic_ns() -> int:
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC)


def _free_port() -> int:
    """A port the kernel considers free on 127.0.0.1 right now (R38: chosen by the orchestration;
    the window until rtinode binds it is what the address-in-use retry is for)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        return probe.getsockname()[1]


def _accepts(port: int) -> bool:
    """NAT-18's readiness probe: one raw TCP connect to 127.0.0.1:port, closed at once (a short
    timeout: a listener whose backlog is full must not hold up the start-up window)."""
    try:
        with socket.create_connection((LOOPBACK, port), timeout=0.2):
            return True
    except OSError:
        return False


@dataclass(frozen=True)
class DemoSeams:
    """Every bound and timing value of the demo, and its port chooser and clock. Construct only
    `V1`, or a test's variant of it."""

    #: R38: each barrier within 5 seconds (the publisher enforces it; this module waits a little
    #: longer for the publisher to say so before it calls the barrier stalled).
    barrier_ns: int = 5 * _SECOND
    #: R38 and NAT-18: rtinode starts in all, the retries being for address-in-use only.
    rtinode_starts: int = 5
    #: rtinode's start-up window: it is declared ready only once it has accepted a connect and is
    #: still running when the window closes; an end before that is a failed start.
    rtinode_window_ns: int = 500 * _MILLISECOND
    #: NAT-18: how long the raw-connect readiness poll may take.
    readiness_ns: int = 10 * _SECOND
    readiness_poll_ns: int = 20 * _MILLISECOND
    #: R14: the deadline for a process's orderly end before it is killed.
    deadline_ns: int = 10 * _SECOND
    #: The host's session bound (its --duration-seconds) beyond the demo's own end of it: a safety
    #: net only; every run ends by the demo's orderly stop long before.
    session_seconds: int = 600
    #: OPS-23's reading of the host child's RSS, and the bound it is held to.
    rss_poll_ns: int = 250 * _MILLISECOND
    choose_port: Callable = field(default=_free_port)
    monotonic_ns: Callable = field(default=_clock_monotonic_ns)
    rss_of: Callable = field(default=host._rss_of)

    def __post_init__(self) -> None:
        for name in ("barrier_ns", "rtinode_starts", "rtinode_window_ns", "readiness_ns",
                     "readiness_poll_ns", "deadline_ns", "session_seconds", "rss_poll_ns"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive int")
        for name in ("choose_port", "monotonic_ns", "rss_of"):
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")


V1 = DemoSeams()


# --- the executables (OPV-04, CR-L16) -------------------------------------------------------------

def locate(environ, variable: str, location: str) -> str | None:
    """The absolute path in `variable`, else the fixed place; None when the variable holds a
    relative path (never a PATH search)."""
    path = environ.get(variable)
    if path is None:
        return location
    return path if os.path.isabs(path) else None


def executable_problem(path: str | None, variable: str) -> str | None:
    """Why `path` cannot be run, or None."""
    if path is None:
        return f"{variable} is not an absolute path"
    try:
        regular = stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        regular = False
    if not regular or not os.access(path, os.X_OK):
        return "missing or not an executable file"
    return None


def check_publisher(path: str, environ, *, seams: DemoSeams = V1) -> str | None:
    """CR-L16's pre-flight: `--version` prints exactly `PUBLISHER_VERSION_LINE` and exits 0 within
    the deadline. Returns why not, or None."""
    problem = executable_problem(path, PUBLISHER_VARIABLE)
    if problem is not None:
        return problem
    child = _Child.start([path, "--version"], host.worker_environment(environ), stdin=False)
    deadline = seams.monotonic_ns() + seams.deadline_ns
    try:
        while not child.reaped and seams.monotonic_ns() < deadline:
            child.pump(_TICK_MS)
            child.poll()
            if len(child.stdout) > len(PUBLISHER_VERSION_LINE):
                break
    finally:
        child.end(seams, graceful=False)
    if child.status != 0 or bytes(child.stdout) != PUBLISHER_VERSION_LINE:
        return "the publisher does not answer --version as this build expects"
    return None


# --- child processes ------------------------------------------------------------------------------

def _pipe() -> tuple[int, int]:
    # NAT-09's rule for DUP2 sources applies to every child started here as well.
    read_end, write_end = os.pipe()
    return host._above_three(read_end), host._above_three(write_end)


class _Child:
    """A process started with posix_spawn (an absolute path, an argument vector, an explicit
    environment, its own process group), stdout and stderr on pipes this module reads without
    blocking, stdin a pipe this module writes (or the null device)."""

    def __init__(self, pid: int, stdin_fd: int | None, stdout_fd: int, stderr_fd: int) -> None:
        self.pid = pid
        self.stdin_fd = stdin_fd
        self.stdout_fd = stdout_fd
        self.stderr_fd = stderr_fd
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.status: int | None = None
        self.reaped = False
        self.overflow = False

    @classmethod
    def start(cls, argv: list[str], env: dict, *, stdin: bool) -> "_Child":
        out_read, out_write = _pipe()
        err_read, err_write = _pipe()
        in_read = in_write = None
        actions = [(os.POSIX_SPAWN_DUP2, out_write, 1), (os.POSIX_SPAWN_DUP2, err_write, 2)]
        if stdin:
            in_read, in_write = _pipe()
            actions.insert(0, (os.POSIX_SPAWN_DUP2, in_read, 0))
        else:
            actions.insert(0, (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0))
        try:
            pid = os.posix_spawn(argv[0], argv, env, file_actions=actions, setpgroup=0,
                                 setsigdef=host._DEFAULT_SIGNALS, setsigmask=())
        except BaseException:
            for fd in (out_read, out_write, err_read, err_write, in_read, in_write):
                if fd is not None:
                    os.close(fd)
            raise
        os.close(out_write)
        os.close(err_write)
        if in_read is not None:
            os.close(in_read)
        for fd in (out_read, err_read):
            os.set_blocking(fd, False)
        return cls(pid, in_write, out_read, err_read)

    def fds(self) -> list[int]:
        return [fd for fd in (self.stdin_fd, self.stdout_fd, self.stderr_fd) if fd is not None]

    def pump(self, timeout_ms: int) -> None:
        """Waits up to `timeout_ms` for output and reads whatever is there."""
        watched = [fd for fd in (self.stdout_fd, self.stderr_fd) if fd is not None]
        if not watched:
            if timeout_ms:
                select.select([], [], [], timeout_ms / 1000)
            return
        ready, _, _ = select.select(watched, [], [], timeout_ms / 1000)
        for fd in ready:
            self.read(fd)

    def read(self, fd: int) -> None:
        sink = self.stdout if fd == self.stdout_fd else self.stderr
        try:
            chunk = os.read(fd, _READ_CHUNK)
        except BlockingIOError:
            return
        if not chunk:
            os.close(fd)
            if fd == self.stdout_fd:
                self.stdout_fd = None
            else:
                self.stderr_fd = None
            return
        if len(sink) + len(chunk) > _CHANNEL_BYTES:
            self.overflow = True
            return
        sink.extend(chunk)

    def write(self, data: bytes) -> bool:
        if self.stdin_fd is None:
            return False
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(self.stdin_fd, view):]
        except OSError:
            return False
        return True

    def poll(self) -> bool:
        """True once the process has ended (and is reaped)."""
        if self.reaped:
            return True
        done, status = os.waitpid(self.pid, os.WNOHANG)
        if done:
            self.status = os.waitstatus_to_exitcode(status)
            self.reaped = True
        return self.reaped

    def signal(self, signum: int) -> None:
        if not self.reaped:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.pid, signum)

    def end(self, seams: DemoSeams, *, graceful: bool) -> None:
        """SIGTERM and up to the deadline for it to end (when `graceful`), then SIGKILL; reaped
        either way, what it wrote read up to the end of its pipes, every pipe closed. A pipe
        some other process still holds open (one the child left behind: this module never
        started it) is read for one more deadline at most, then closed: the end never waits on
        it."""
        if not self.poll() and graceful:
            self.signal(signal.SIGTERM)
            deadline = seams.monotonic_ns() + seams.deadline_ns
            while not self.poll() and seams.monotonic_ns() < deadline:
                self.pump(_TICK_MS)
        if not self.poll():
            self.signal(signal.SIGKILL)
            _, status = os.waitpid(self.pid, 0)
            self.status = os.waitstatus_to_exitcode(status)
            self.reaped = True
        deadline = seams.monotonic_ns() + seams.deadline_ns
        while (self.stdout_fd is not None or self.stderr_fd is not None) and \
                seams.monotonic_ns() < deadline:
            self.pump(_TICK_MS)
        for fd in (self.stdout_fd, self.stderr_fd):
            if fd is not None:
                os.close(fd)
        self.stdout_fd = self.stderr_fd = None
        self.close_stdin()

    def close_stdin(self) -> None:
        if self.stdin_fd is not None:
            os.close(self.stdin_fd)
            self.stdin_fd = None


class _Lines:
    """Complete LF-terminated lines from a growing buffer, parsed as JSON objects; a line that is
    not one is a protocol fault of the writer."""

    def __init__(self) -> None:
        self.offset = 0

    def take(self, buffer: bytearray) -> list:
        out = []
        while True:
            end = buffer.find(b"\n", self.offset)
            if end < 0:
                return out
            line = bytes(buffer[self.offset:end])
            self.offset = end + 1
            try:
                value = json.loads(line)
            except ValueError:
                value = None
            out.append(value if isinstance(value, dict) else None)


# --- rtinode (R38, NAT-18) ------------------------------------------------------------------------

class Rtinode:
    """The demo's own rtinode, on 127.0.0.1 and a port this module chose."""

    def __init__(self) -> None:
        self.child: _Child | None = None
        self.port: int | None = None
        self.attempts: list[dict] = []
        self.port_released: bool | None = None
        #: Every rtinode process started, one per attempt, in order.
        self.children: list[_Child] = []

    def start(self, path: str, environ, seams: DemoSeams, check: Callable) -> str | None:
        """Starts it; returns why it could not be started, or None once it accepts connections.
        Whatever leaves this method by an exception (a stop the command noted, which `check`
        raises) leaves no rtinode of it running: the start under way is ended by its PID and
        reaped first (SPEC:211)."""
        env = host.worker_environment(environ)
        env["LC_ALL"] = "C"
        for _ in range(seams.rtinode_starts):
            check()
            port = seams.choose_port()
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("choose_port returned no port")
            child = _Child.start([path, "-i", f"{LOOPBACK}:{port}"], env, stdin=False)
            self.children.append(child)
            attempt = {"port": port, "pid": child.pid, "outcome": None}
            self.attempts.append(attempt)
            try:
                outcome = self._settle(child, port, seams, check)
            except BaseException:
                # Nobody else holds this child yet, so nobody else would stop it. The attempt's
                # outcome stays None: a document naming it is never written after an exception.
                child.end(seams, graceful=True)
                raise
            attempt["outcome"] = outcome
            if outcome == "listening":
                self.child, self.port = child, port
                return None
            if outcome == "exited":
                return "rtinode ended during its start for a reason other than a busy port"
            if outcome == "not_ready":
                return "rtinode did not accept a connection within its start-up bound"
        return "every port tried for rtinode was in use"

    @staticmethod
    def _settle(child: _Child, port: int, seams: DemoSeams, check: Callable) -> str:
        """One start's outcome: `listening` (still running), or `address_in_use`, `exited` or
        `not_ready`, the process then ended and reaped."""
        window = seams.monotonic_ns() + seams.rtinode_window_ns
        ready_by = seams.monotonic_ns() + seams.readiness_ns
        accepted = False
        while True:
            check()
            child.pump(0)
            if child.poll():
                # Still in its start-up phase (it was never declared ready): status 1 with the
                # busy-address message is the only end that is retried (NAT-18).
                child.end(seams, graceful=False)
                if child.status == 1 and _RTINODE_ADDRESS_IN_USE in child.stderr:
                    return "address_in_use"
                return "exited"
            accepted = accepted or _accepts(port)
            if accepted and seams.monotonic_ns() >= window:
                return "listening"
            if seams.monotonic_ns() >= ready_by:
                child.end(seams, graceful=True)
                return "not_ready"
            child.pump(seams.readiness_poll_ns // _MILLISECOND)

    def stop(self, seams: DemoSeams) -> None:
        """By its PID (SPEC:211): SIGTERM, the deadline, SIGKILL, for every rtinode process this
        object started that is not yet ended (`_Child.end` is idempotent); then the port of the
        one that listened must refuse a connect."""
        for child in self.children:
            child.end(seams, graceful=True)
        if self.child is not None:
            self.port_released = not _accepts(self.port)

    def processes(self) -> list[dict]:
        """Every rtinode process started, as the clean-up reports it: reaped and its exit status
        as observed, never assumed."""
        return [{"role": "rtinode", "pid": child.pid, "reaped": child.reaped,
                 "exit_status": child.status} for child in self.children]


# --- the capture as the host writes it ------------------------------------------------------------

class _CaptureTail:
    """The live capture's complete lines as they appear (the host writes and flushes each line
    before reducing it, R34), counted by event and user tag."""

    def __init__(self, path: bytes) -> None:
        self.path = path
        self.fd: int | None = None
        self.buffer = bytearray()
        self.lines = _Lines()
        self.frames: list[dict] = []
        #: (event type, tag bytes or None, generation or None) -> capture seqs, in order.
        self.seqs: dict[tuple, list[int]] = {}

    def read(self) -> None:
        if self.fd is None:
            try:
                self.fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            except FileNotFoundError:
                return
        while True:
            chunk = os.read(self.fd, _READ_CHUNK)
            if not chunk:
                break
            self.buffer.extend(chunk)
        for record in self.lines.take(self.buffer):
            if record is None or record.get("type") != capture.FRAME:
                continue
            self.frames.append(record)
            event = record["event"]
            kind = event["type"]
            if kind in ("discover", "reflect", "remove"):
                tag = bytes.fromhex(event["tag_hex"]) if "tag_hex" in event else None
                tags = (None,) if tag is None else (None, tag)
                for each in tags:
                    for generation in (None, record["generation"]):
                        self.seqs.setdefault((kind, each, generation), []).append(record["seq"])

    def count(self, kind: str, tag: bytes | None, generation: int | None = None) -> int:
        return len(self.seqs.get((kind, tag, generation), ()))

    def nth(self, kind: str, tag: bytes | None, n: int, generation: int | None = None) -> int:
        return self.seqs[(kind, tag, generation)][n - 1]

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


# --- scenarios ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Barrier:
    """A barrier the publisher waits at: the capture shows `count` events of `event` with `tag`
    (None: any tag) in `generation` (None: any), or, for `event` "resigned", the observer
    session has ended in order."""

    number: int
    event: str
    tag: bytes | None
    count: int
    generation: int | None = None


@dataclass(frozen=True)
class Scenario:
    argument: str
    barriers: tuple
    #: The barrier after which the observer is stopped in order.
    stop_after: int


def main_scenario() -> Scenario:
    """R38's order; the step tags are the publisher's."""
    return Scenario("main", (
        Barrier(0, "discover", None, 1),
        Barrier(1, "reflect", b"step-1", 1),
        Barrier(2, "reflect", b"step-2", 1),
        Barrier(3, "reflect", b"step-3", 1),
        Barrier(4, "reflect", b"step-4", 1),
        Barrier(5, "remove", b"step-5", 1),
        Barrier(6, "resigned", None, 1),
    ), stop_after=5)


def perf_scenario(objects: int, hz: int, seconds: int) -> Scenario:
    """R42's load shape (`perf:O:H:S`): the discoveries, one identity reflection per object, the
    load, the removals."""
    for value, high in ((objects, 65535), (hz, 1000), (seconds, 86400)):
        if type(value) is not int or not 1 <= value <= high:
            raise ValueError("perf scenario values out of range")
    return Scenario(f"perf:{objects}:{hz}:{seconds}", (
        Barrier(0, "discover", None, objects),
        Barrier(1, "reflect", b"perf-identity", objects),
        Barrier(2, "reflect", b"perf", objects * hz * seconds),
        Barrier(3, "remove", b"perf-remove", objects),
        Barrier(4, "resigned", None, 1),
    ), stop_after=3)


# --- one run: publisher, observer session, barriers -----------------------------------------------

class RunFailure(Exception):
    """A run that cannot go on: its stage and a fixed reason (never a child's own text)."""

    def __init__(self, stage: str, reason: str, code: str | None = None) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.code = code


def new_federation_name() -> str:
    """OPV-05: SC_DEMO_ plus 16 random lowercase hexadecimal digits (R38: unique per run)."""
    return FEDERATION_PREFIX + secrets.token_hex(8)


def run_config(name: str, port: int, federation: str) -> dict:
    """OPS-13: config-demo.json with only `endpoint` and `federation_name` replaced; for the
    `no-time` run also time policy none and session id example-001-none (R39). Validated."""
    document = canonical.strict_loads(_examples.CONFIG_DEMO, floats=False, surrogates=False)
    document["endpoint"] = f"rti://{LOOPBACK}:{port}"
    document["federation_name"] = federation
    if name == "no-time":
        document["time_policy"] = {"mode": "none"}
        document["session_id"] = "example-001-none"
    return config.validate_config(document)


@dataclass
class HostChild:
    """The observer session's host, a child process (the command line forks it)."""

    pid: int
    messages_fd: int
    buffer: bytearray = field(default_factory=bytearray)
    lines: _Lines = field(default_factory=_Lines)
    result: dict | None = None
    workers: dict = field(default_factory=dict)
    stderr: list = field(default_factory=list)
    status: int | None = None
    reaped: bool = False
    closed: bool = False

    def read(self) -> None:
        try:
            chunk = os.read(self.messages_fd, _READ_CHUNK)
        except BlockingIOError:
            return
        if not chunk:
            self.closed = True
            return
        if len(self.buffer) + len(chunk) > _CHANNEL_BYTES:
            raise RunFailure("host", "the host wrote more than any message it writes")
        self.buffer.extend(chunk)
        for message in self.lines.take(self.buffer):
            if message is None:
                raise RunFailure("host", "the host wrote a line that is not a message")
            if "worker" in message:
                self.workers.setdefault(message["worker"], {"running": False, "reaped": False})
                if message["running"]:
                    self.workers[message["worker"]]["running"] = True
                else:
                    self.workers[message["worker"]]["reaped"] = True
            elif "stderr" in message:
                self.stderr.append(message["stderr"])
            elif "result" in message:
                self.result = message["result"]

    def poll(self) -> bool:
        if not self.reaped:
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                self.status = os.waitstatus_to_exitcode(status)
                self.reaped = True
        return self.reaped

    def kill(self) -> None:
        """No orderly end is possible: the host and each worker it still had (each a process
        group of its own) are killed, and the host is reaped."""
        for pid, worker in self.workers.items():
            if worker["running"] and not worker["reaped"]:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            os.kill(self.pid, signal.SIGKILL)
        if not self.reaped:
            _, status = os.waitpid(self.pid, 0)
            self.status = os.waitstatus_to_exitcode(status)
            self.reaped = True

    def drain(self) -> None:
        while not self.closed:
            ready, _, _ = select.select([self.messages_fd], [], [], 1)
            if not ready:
                return
            self.read()


class Run:
    """One run of a scenario: the publisher, the observer session, the barriers, the end."""

    def __init__(self, name: str, document: dict, out_path: bytes, scenario: Scenario, *,
                 publisher: str, fom_dir: str, pins: dict, environ: dict, start_host: Callable,
                 check: Callable, seams: DemoSeams, hook: Callable | None = None,
                 publisher_endpoint: str | None = None) -> None:
        self.name = name
        self.document = document
        self.out_path = out_path
        self.scenario = scenario
        self.publisher_path = publisher
        self.fom_dir = fom_dir
        self.pins = pins
        self.environ = environ
        self.start_host = start_host
        self.check = check
        self.seams = seams
        #: Called with the run after each turn (tests only: a fault injected at a moment the
        #: capture shows).
        self.hook = hook
        #: Where the publisher connects: the observer's endpoint, unless a test puts something
        #: between the observer and rtinode.
        self.publisher_endpoint = publisher_endpoint or document["endpoint"]
        self.publisher: _Child | None = None
        #: How far the publisher's stdout has been read as events.
        self.event_offset = 0
        self.host: HostChild | None = None
        self.tail = _CaptureTail(os.path.join(out_path, os.fsencode(_runfile.CAPTURE)))
        self.module_sha256: dict | None = None
        self.registered_class: str | None = None
        self.created = False
        self.destroyed = False
        self.refreshes = 0
        self.refresh_reflections = 0
        self.acknowledged: dict[int, int | None] = {}
        self.waiting: int | None = None
        self.waiting_since = 0
        self.stop_sent = False
        self.failure: RunFailure | None = None
        self.publisher_failure: dict | None = None
        self.next_rss = 0

    # -- the pieces

    def _publisher_argv(self, federation: str) -> list[str]:
        from synapse_hla import _fom
        return ([self.publisher_path, f"--endpoint={self.publisher_endpoint}",
                 f"--federation-name={federation}", f"--fom-dir={self.fom_dir}"]
                + [f"--module-sha256={self.pins[name]}" for name in _fom.FOM_MODULES]
                + [f"--scenario={self.scenario.argument}"])

    def _publisher_events(self):
        """The publisher's events not read yet, one complete line at a time, each checked as it
        is read (`_checked_event`). A generator, so that a line whose handling raises leaves the
        lines after it unread for `abort`."""
        while True:
            buffer = self.publisher.stdout
            end = buffer.find(b"\n", self.event_offset)
            if end < 0:
                if len(buffer) - self.event_offset > _EVENT_BYTES:
                    raise RunFailure("publisher", _NOT_AN_EVENT)
                return
            line = bytes(buffer[self.event_offset:end])
            self.event_offset = end + 1
            yield self._checked_event(line)

    def _checked_event(self, line: bytes) -> dict:
        """One line of the publisher's stdout as the event it must be: printable ASCII within the
        line bound, one JSON object read by the contract's strict reader (no duplicate key, no
        float, no integer beyond 2^53 - 1, no lone surrogate, nesting bounded), with exactly the
        members its kind has and values of the publisher's own fixed forms and vocabulary
        (tools/publisher/publisher.cpp). Anything else is a fault of the publisher, never a value
        that reaches demo.json (CR-R2-24, CR-R1-04)."""
        if len(line) > _EVENT_BYTES or not line.isascii() or \
                any(byte < 0x20 or byte == 0x7F for byte in line):
            raise RunFailure("publisher", _NOT_AN_EVENT)
        try:
            event = canonical.strict_loads(line, floats=False, surrogates=False)
        except ValueError:
            raise RunFailure("publisher", _NOT_AN_EVENT) from None
        if type(event) is not dict or not self._well_formed(event):
            raise RunFailure("publisher", _NOT_AN_EVENT)
        return event

    def _well_formed(self, event: dict) -> bool:
        kind = event.get("event")
        members = _EVENT_MEMBERS.get(kind) if type(kind) is str else None
        if members is None or set(event) != members:
            return False
        if kind == "modules":
            digests = event["sha256"]
            return (type(digests) is dict and set(digests) == set(self.pins)
                    and all(_is_sha256(value) for value in digests.values()))
        if kind in ("created", "destroyed"):
            return type(event["federation"]) is str and \
                event["federation"] == self.document["federation_name"]
        if kind == "ready":
            return (event["class"] in (PHYSICAL_ENTITY, GROUND_VEHICLE)
                    and event["object_name"] in (_OBJECT_NAME, None)
                    and _bounded_int(event["objects"], 1, 65535))
        if kind in ("waiting", "acknowledged"):
            return _bounded_int(event["barrier"], 0, len(self.scenario.barriers) - 1)
        if kind == "sent":
            return _bounded_int(event["step"], 1, 5)
        if kind == "refresh":
            return _bounded_int(event["attributes"], 0, 4)
        if kind == "failure":
            return _word(event["stage"], PUBLISHER_STAGES) and \
                _word(event["reason"], PUBLISHER_REASONS)
        if kind == "cleanup":
            return _word(event["stage"], _CLEANUP_STAGES) and \
                _word(event["reason"], PUBLISHER_EXCEPTIONS)
        return True

    def _on_event(self, event: dict) -> None:
        kind = event["event"]
        if kind == "modules":
            if self.module_sha256 is not None:
                raise RunFailure("publisher", _OUT_OF_ORDER)
            self.module_sha256 = event["sha256"]
            if self.module_sha256 != self.pins:
                raise RunFailure("publisher", "the publisher reported module digests other than "
                                 "the pinned ones", errors.E_DEPENDENCY_PIN)
        elif kind == "created":
            if self.module_sha256 is None or self.created:
                raise RunFailure("publisher", _OUT_OF_ORDER)
            self.created = True
        elif kind == "ready":
            if not self.created or self.registered_class is not None:
                raise RunFailure("publisher", _OUT_OF_ORDER)
            if event["class"] != GROUND_VEHICLE:
                raise RunFailure("publisher", "the publisher registered its objects at a class "
                                 "other than GroundVehicle")
            if event["objects"] != self.scenario.barriers[0].count:
                raise RunFailure("publisher", "the publisher registered another number of "
                                 "objects than its scenario has")
            self.registered_class = event["class"]
        elif kind == "destroyed":
            if not self.created:
                raise RunFailure("publisher", _OUT_OF_ORDER)
            self.destroyed = True
        elif kind == "refresh":
            self.refreshes += 1
            if event["attributes"]:
                self.refresh_reflections += 1
        elif kind == "waiting":
            # R38: the observer joins only a federation the publisher created from the hashed
            # modules and holds its object in; then the barriers come one by one, in order.
            if self.registered_class is None or self.waiting is not None or \
                    event["barrier"] != len(self.acknowledged):
                raise RunFailure("publisher", _OUT_OF_ORDER)
            self.waiting = event["barrier"]
            self.waiting_since = self.seams.monotonic_ns()
        elif kind == "failure":
            self.publisher_failure = {"stage": event["stage"], "reason": event["reason"]}
            code = errors.E_DEPENDENCY_PIN if event["reason"] == "module_pin" \
                else errors.E_RTI_CONNECT
            raise RunFailure("publisher", "the publisher failed", code)

    def refresh_seqs(self) -> list[int]:
        """The capture seqs of the reflections the publisher sent as answers to a request for
        values (its tag `refresh`), in order: the evidence of R38's extra refresh reflections."""
        return list(self.tail.seqs.get(("reflect", REFRESH_TAG, None), []))

    def _barrier(self, number: int) -> Barrier:
        for barrier in self.scenario.barriers:
            if barrier.number == number:
                return barrier
        raise RunFailure("publisher", "the publisher waits at a barrier the scenario has not")

    def _satisfied(self, barrier: Barrier) -> bool:
        if barrier.event == "resigned":
            return self._observer_resigned()
        return self.tail.count(barrier.event, barrier.tag, barrier.generation) >= barrier.count

    def _observer_resigned(self) -> bool:
        """The observer session ended in order: its host reported COMPLETE and every worker it
        started has been reaped."""
        host_child = self.host
        if host_child is None or not host_child.reaped or host_child.result is None:
            return False
        session = (host_child.result.get("result") or {}).get("session")
        return (session is not None and session["status"] == capture.COMPLETE
                and all(w["reaped"] for w in host_child.workers.values()))

    def _acknowledge(self) -> None:
        barrier = self._barrier(self.waiting)
        if not self._satisfied(barrier):
            if self.seams.monotonic_ns() - self.waiting_since > 2 * self.seams.barrier_ns:
                raise RunFailure("barrier", "the capture did not show the step of a barrier the "
                                 "publisher waits at")
            return
        if barrier.event != "resigned":
            self.acknowledged[barrier.number] = self.tail.nth(barrier.event, barrier.tag,
                                                              barrier.count, barrier.generation)
        else:
            self.acknowledged[barrier.number] = None
        if not self.publisher.write(f"{barrier.number}\n".encode("ascii")):
            raise RunFailure("publisher", "the publisher's barrier pipe is closed")
        self.waiting = None
        if barrier.number == self.scenario.stop_after and not self.stop_sent:
            # The observer's orderly stop (R14): the host passes SIGTERM to its worker, which
            # finishes its batch, resigns and disconnects.
            self.stop_sent = True
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.host.pid, signal.SIGTERM)

    def _watch_rss(self) -> None:
        now = self.seams.monotonic_ns()
        if self.host is None or self.host.reaped or now < self.next_rss:
            return
        self.next_rss = now + self.seams.rss_poll_ns
        rss = self.seams.rss_of(self.host.pid)
        if rss is not None and rss > host.V1.limits.host_rss_bytes:
            self.host.kill()
            raise RunFailure("host", "the host's resident memory passed its limit",
                             errors.E_LIMIT)

    def _turn(self) -> None:
        self.check()
        fds = [fd for fd in (self.publisher.stdout_fd, self.publisher.stderr_fd)
               if fd is not None]
        if self.host is not None and not self.host.closed:
            fds.append(self.host.messages_fd)
        ready, _, _ = select.select(fds, [], [], _TICK_MS / 1000)
        for fd in ready:
            if self.host is not None and fd == self.host.messages_fd:
                self.host.read()
            else:
                self.publisher.read(fd)
        if self.publisher.overflow:
            raise RunFailure("publisher", "the publisher wrote more than its events")
        self.tail.read()
        for event in self._publisher_events():
            self._on_event(event)
        if self.host is not None:
            self.host.poll()
            self._watch_rss()
        self.publisher.poll()
        if self.hook is not None:
            self.hook(self)

    # -- the run

    def execute(self) -> None:
        env = host.worker_environment(self.environ)
        self.publisher = _Child.start(self._publisher_argv(self.document["federation_name"]), env,
                                      stdin=True)
        ready_by = self.seams.monotonic_ns() + self.seams.deadline_ns
        ready = False
        while not ready:
            self._turn()
            ready = self.waiting == 0
            if self.publisher.reaped and not ready:
                raise RunFailure("publisher", "the publisher ended before it was ready")
            if self.seams.monotonic_ns() > ready_by and not ready:
                raise RunFailure("publisher", "the publisher was not ready within the deadline")
        # R38: the publisher has created the federation; now the observer joins it.
        pid, messages_fd = self.start_host(self.document, self.out_path,
                                           self.publisher.fds())
        os.set_blocking(messages_fd, False)
        self.host = HostChild(pid, messages_fd)
        while not (self.publisher.reaped and self.host.reaped):
            self._turn()
            if self.waiting is not None and not self.publisher.reaped:
                self._acknowledge()
            if self.host.reaped and not self.stop_sent:
                # A host ends early only by a failure of its session: the demo had not asked.
                raise RunFailure("observer", "the observer session ended before the scenario "
                                 "was complete")
            if self.publisher.reaped and not self.host.reaped:
                raise RunFailure("publisher", "the publisher ended while the observer ran")
        self.host.drain()
        if self.publisher.status != 0 or not self.destroyed:
            raise RunFailure("publisher", "the publisher did not end with its federation "
                             "destroyed")

    def abort(self) -> None:
        """After a failure or a stop: the observer first (so that the publisher's destroy can
        succeed), then the publisher, each in order, then by force; everything reaped."""
        if self.host is not None and not self.host.reaped:
            if not self.stop_sent:
                self.stop_sent = True
                with contextlib.suppress(ProcessLookupError):
                    os.kill(self.host.pid, signal.SIGTERM)
            deadline = self.seams.monotonic_ns() + 2 * self.seams.deadline_ns
            while not self.host.poll() and self.seams.monotonic_ns() < deadline:
                ready, _, _ = select.select([] if self.host.closed else
                                            [self.host.messages_fd], [], [], _TICK_MS / 1000)
                if ready:
                    self.host.read()
            if not self.host.reaped:
                self.host.kill()
            self.host.drain()
        if self.publisher is not None:
            self.publisher.end(self.seams, graceful=True)
            # What it wrote after the line that stopped the run (each still checked): did it
            # destroy the federation it created?
            with contextlib.suppress(RunFailure):
                for event in self._publisher_events():
                    if event["event"] == "destroyed" and self.created:
                        self.destroyed = True

    def close(self) -> None:
        self.tail.close()
        if self.host is not None:
            with contextlib.suppress(OSError):
                os.close(self.host.messages_fd)
        if self.publisher is not None:
            self.publisher.end(self.seams, graceful=False)

    def processes(self) -> list[dict]:
        out = []
        if self.publisher is not None:
            out.append({"role": "publisher", "pid": self.publisher.pid,
                        "reaped": self.publisher.reaped, "exit_status": self.publisher.status})
        if self.host is not None:
            out.append({"role": "host", "pid": self.host.pid, "reaped": self.host.reaped,
                        "exit_status": self.host.status})
            for pid in sorted(self.host.workers):
                worker = self.host.workers[pid]
                out.append({"role": "worker", "pid": pid, "reaped": worker["reaped"],
                            "exit_status": None})
        return out


def run_scenario(name: str, document: dict, out_path: bytes, scenario: Scenario, *,
                 publisher: str, fom_dir: str, pins: dict, environ: dict, start_host: Callable,
                 check: Callable, seams: DemoSeams = V1, hook: Callable | None = None,
                 publisher_endpoint: str | None = None) -> tuple[Run, RunFailure | None]:
    """One run, from the publisher's start to everything it started reaped. Returns the run and
    its failure (None when it went to the end). `hook` and `publisher_endpoint` are tests' (see
    `Run`)."""
    run = Run(name, document, out_path, scenario, publisher=publisher, fom_dir=fom_dir, pins=pins,
              environ=environ, start_host=start_host, check=check, seams=seams, hook=hook,
              publisher_endpoint=publisher_endpoint)
    failure = None
    try:
        try:
            run.execute()
        except RunFailure as error:
            failure = error
            run.abort()
        except BaseException:
            run.abort()
            raise
    finally:
        run.close()
    return run, failure


# --- what the runs must show (OPS-13, R39) --------------------------------------------------------

def _read(path: bytes) -> bytes:
    with open(path, "rb") as stream:
        return stream.read()


def _jsonl(path: bytes) -> list[dict]:
    return [canonical.strict_loads(line, floats=True, surrogates=False)
            for line in _read(path).split(b"\n")[:-1]]


def expectations() -> dict:
    """The expected semantic values, from the packaged vectors (R39): the identity fixture, the
    session checkpoints keyed by the Spatial bytes the bundled capture carried at their seqs (the
    publisher sends those very bytes), the decoded identifier and entity type of V-ID-123 and
    V-TYPE-PLATFORM, and the demo configuration's force map."""
    identity = _resources.package_json("fixtures", "identity.json")
    checkpoints = _resources.package_json("fixtures", "session-checkpoints.json")
    lines = _resources.package_bytes("fixtures", "session.capture.jsonl").split(b"\n")[:-1]
    frames = {}
    for line in lines[1:]:
        record = canonical.strict_loads(line, floats=False, surrogates=False)
        if record["type"] == capture.FRAME:
            frames[record["seq"]] = record
    by_spatial = {}
    for upsert in checkpoints["upserts"]:
        event = frames[upsert["seq"]]["event"]
        hexes = [a["hex"] for a in event["attributes"] if a["name"] == "Spatial"]
        by_spatial[hexes[0]] = upsert
    positive = {entry["id"]: entry
                for entry in _resources.package_json("fixtures", "attributes-positive.json")}
    demo = canonical.strict_loads(_examples.CONFIG_DEMO, floats=False, surrogates=False)
    return {"entity_id": identity["entity_id"], "external_id": identity["external_id"],
            "by_spatial": by_spatial, "identifier": positive["ID-123"]["expected"],
            "entity_type": positive["TYPE-PLATFORM"]["expected"],
            "affiliation": demo["force_map"]["1"]}


def _close(value, expected, tolerance) -> bool:
    return isinstance(value, (int, float)) and abs(value - expected) <= tolerance


def _course_close(value, expected) -> bool:
    if not isinstance(value, (int, float)):
        return False
    return abs((value - expected + 180.0) % 360.0 - 180.0) <= DEGREES


def _normalised(records: list[dict]) -> list[bytes]:
    """SPEC:158: live and replay outputs differ in the completion fields only; everything else
    must be identical, so each record is compared with those two fields set to null."""
    out = []
    for record in records:
        record = copy.deepcopy(record)
        record["capture_complete"] = None
        if record["kind"] == "upsert":
            record["payload"]["attributes"]["hla"]["capture_complete"] = None
        out.append(canonical.canonical_bytes(record, floats=True))
    return out


def _spatial_hex(run: Run, seq: int) -> str | None:
    for frame in run.tail.frames:
        if frame["seq"] == seq:
            for attribute in frame["event"].get("attributes", ()):
                if attribute["name"] == "Spatial":
                    return attribute["hex"]
    return None


def checkpoints(name: str, run: Run, live: bytes, replayed: bytes | None,
                replay_summary: dict | None) -> list[dict]:
    """The semantic checkpoints of one run, each PASS or FAIL (OPS-13). Ids and order are fixed,
    so two demos agree on them exactly when their results agree."""
    expected = expectations()
    results = []

    def judge(identifier: str, condition: Callable) -> None:
        try:
            passed = bool(condition())
        except (KeyError, IndexError, TypeError, ValueError):
            passed = False
        results.append({"id": identifier, "result": PASS if passed else FAIL})

    observations = _jsonl(os.path.join(live, b"observations.jsonl"))
    upserts = [r for r in observations if r["kind"] == "upsert"]
    snapshots = [r for r in observations if r["kind"] == "snapshot"]
    removed = [r for r in observations if r["kind"] == "removed"]
    capture_barriers = [b for b in run.scenario.barriers if b.event != "resigned"]
    step_seqs = [run.acknowledged.get(b.number) for b in capture_barriers]

    judge("capture_verified", lambda: capture.verify_capture(
        os.path.join(live, os.fsencode(_runfile.CAPTURE)))["status"] == capture.COMPLETE)
    judge("steps_in_order", lambda: len(run.acknowledged) == len(run.scenario.barriers)
          and None not in step_seqs and step_seqs == sorted(set(step_seqs)))
    # A-CLASS, SPEC:50: the publisher registered its object at GroundVehicle; the observer
    # reports the class the RTI reported at its subscription, PhysicalEntity, everywhere, and the
    # leaf class appears nowhere it did not come from.
    judge("reported_class", lambda: run.registered_class == GROUND_VEHICLE and all(
        f["event"]["reported_class"] == PHYSICAL_ENTITY for f in run.tail.frames
        if f["event"]["type"] == "discover") and all(
        r["payload"]["reported_class"] == PHYSICAL_ENTITY for r in snapshots) and all(
        u["payload"]["attributes"]["hla"]["reported_class"] == PHYSICAL_ENTITY for u in upserts)
        and GROUND_VEHICLE.encode("ascii") not in _read(os.path.join(
            live, os.fsencode(_runfile.CAPTURE))) + _read(os.path.join(
            live, b"observations.jsonl")))
    entity_ids = {r["entity_id"] for r in observations if r["entity_id"] is not None}
    judge("one_entity_id", lambda: len(entity_ids) == 1
          and (name != "main" or entity_ids == {expected["entity_id"]}))
    if name == "main":
        judge("identifier", lambda: upserts and all(
            u["payload"]["attributes"]["hla"]["identifier"] == expected["identifier"]
            and u["entity_id"] == expected["entity_id"]
            and u["payload"]["source_ids"][0]["external_id"] == expected["external_id"]
            for u in upserts))
        judge("platform", lambda: upserts and all(
            u["payload"]["entity_type"] == "PLATFORM"
            and u["payload"]["attributes"]["hla"]["entity_type"] == expected["entity_type"]
            for u in upserts))
        judge("affiliation", lambda: upserts and all(
            u["payload"]["affiliation"] == expected["affiliation"] for u in upserts))
        for check_id, index in (("position_equator", 0), ("position_second", 1)):
            spatial_hex = list(expected["by_spatial"])[index]
            want = expected["by_spatial"][spatial_hex]

            def at(u):
                seq = u["payload"]["attributes"]["hla"]["attribute_sequences"]["Spatial"]
                return _spatial_hex(run, seq)
            judge(check_id, lambda h=spatial_hex, w=want: [
                u for u in upserts if at(u) == h] and all(
                _close(u["payload"]["position"]["lat"], w["lat"], DEGREES)
                and _close(u["payload"]["position"]["lon"], w["lon"], DEGREES)
                and _close(u["payload"]["position"]["alt_m"], w["alt_m"], METRES)
                for u in upserts if at(u) == h))
        judge("course_east", lambda: upserts and all(
            _close(u["payload"]["kinematics"]["speed_mps"],
                   expected["by_spatial"][at(u)]["speed_mps"], SPEEDS)
            and _course_close(u["payload"]["kinematics"]["course_deg"],
                              expected["by_spatial"][at(u)]["course_deg"])
            and _close(u["payload"]["kinematics"]["climb_mps"],
                       expected["by_spatial"][at(u)]["climb_mps"], SPEEDS)
            for u in upserts))
        judge("revisions", lambda: [u["revision"] for u in upserts]
              == list(range(1, len(upserts) + 1)))
        judge("valid_from_nondecreasing", lambda: [u["payload"]["valid_from"] for u in upserts]
              == sorted(u["payload"]["valid_from"] for u in upserts))
        judge("no_diagnostics", lambda: not [r for r in observations
                                             if r["kind"] in ("diagnostic", "invalidated")])
    else:
        judge("identifier", lambda: snapshots and all(
            s["payload"]["identity"] == expected["identifier"] for s in snapshots
            if s["payload"]["identity"] is not None))
        judge("snapshots_present", lambda: all(
            any(s["seq"] == seq for s in snapshots) for seq in step_seqs[1:-1]))
        judge("no_entity", lambda: not upserts)
        judge("time_unresolved", lambda: any(
            r["kind"] == "diagnostic" and r["payload"]["code"] == errors.W_TIME_UNRESOLVED
            for r in observations) and "TIME_UNRESOLVED" in [
            s for s in snapshots if s["seq"] == step_seqs[3]][0]["payload"][
            "suppression_reasons"])
    judge("removed_notice", lambda: len(removed) == 1 and removed[0]["seq"] == step_seqs[-1]
          and removed[0]["payload"]["last_revision"] == len(upserts)
          and all(u["seq"] < removed[0]["seq"] for u in upserts))

    def identical() -> bool:
        if replayed is None or replay_summary is None:
            return False
        if replay_summary["status"] != capture.COMPLETE:
            return False
        for file_name in (b"observations.jsonl", b"diagnostics.jsonl"):
            if _normalised(_jsonl(os.path.join(live, file_name))) != \
                    _normalised(_jsonl(os.path.join(replayed, file_name))):
                return False
        return True
    judge("replay_identical", identical)
    return results


# --- the whole demo -------------------------------------------------------------------------------

@dataclass
class Outcome:
    """What the command line reports: the demo.json document, the diagnostics for stderr (already
    rendered lines from the hosts, and (code, message, path) of the demo's own), the codes and the
    exit code."""

    document: dict
    host_lines: list
    diagnostics: list
    codes: set
    exit_code: int


def evidence_class() -> str:
    """CR-L04: every result a build of this round produces is development evidence; the release
    evidence of the reference platform is stamped by its own run (R9), never inferred here."""
    system = {"Darwin": "macOS"}.get(platform.system(), platform.system()) or "unknown"
    machine = platform.machine() or "unknown"
    return f"DEV-{system}-{machine}"


def _session_block(result: dict | None) -> dict | None:
    session = None if result is None else (result.get("result") or {}).get("session")
    if session is None:
        return None
    return {"status": session["status"], "reason_code": session["reason_code"],
            "terminal_codes": list(session["terminal_codes"]), "frames": session["frames"],
            "last_seq": session["last_seq"], "last_generation": session["last_generation"],
            "workers": session["workers"], "records": dict(session["records"])}


def _sha256_file(path: bytes) -> str | None:
    try:
        with open(path, "rb") as stream:
            return canonical.sha256_hex(stream.read())
    except OSError:
        return None


def run_demo(target: bytes, environ: dict, modules, *, rtinode: str, publisher: str,
             start_host: Callable, check: Callable, synapse_cdm_version: str | None,
             seams: DemoSeams = V1) -> Outcome:
    """The exercise of the module text, into the existing directory `target`. `modules` are the
    FOM modules the command line checked against the pins (their directory is the publisher's);
    `start_host(document, out_path, close_fds)` forks the observer's host and returns its pid
    and the read end of its message pipe; `check()` raises when the command was asked to stop.
    Whatever is raised, everything started here has been stopped and reaped first."""
    pins = {module.name: module.sha256 for module in modules}
    fom_dir = os.path.dirname(modules[0].path)
    node = Rtinode()
    failures: list[dict] = []
    runs: list[dict] = []
    host_lines: list[str] = []
    codes: set[str] = set()
    every_run: list[Run] = []
    try:
        problem = node.start(rtinode, environ, seams, check)
        if problem is not None:
            failures.append({"stage": "rtinode", "reason": problem, "run": None,
                             "code": errors.E_RTI_CONNECT})
        else:
            for name in ("main", "no-time"):
                record, run, failure = _one_run(name, target, node.port, environ, pins, fom_dir,
                                                publisher, start_host, check, seams,
                                                synapse_cdm_version)
                every_run.append(run)
                runs.append(record)
                if run.host is not None:
                    host_lines.extend(run.host.stderr)
                    if run.host.result is not None:
                        codes.update(run.host.result.get("codes", ()))
                if failure is not None:
                    failures.append({"stage": failure.stage, "reason": failure.reason,
                                     "run": name, "code": failure.code})
                    break
    finally:
        node.stop(seams)
    processes = node.processes()
    for run in every_run:
        processes.extend(run.processes())
    cleanup_ok = all(p["reaped"] for p in processes) and node.port_released is not False
    cleanup = {"result": PASS if cleanup_ok else FAIL, "processes": processes,
               "port_released": node.port_released}
    checkpoint_failed = any(c["result"] == FAIL for r in runs for c in r["checkpoints"])
    status = PASS if (not failures and cleanup_ok and len(runs) == 2 and not checkpoint_failed
                      and all(r["result"] == PASS for r in runs)) else FAIL
    diagnostics = []
    for failure in failures:
        if failure["code"] is not None:
            diagnostics.append((failure["code"], failure["reason"],
                                {"rtinode": RTINODE_NAME, "publisher": PUBLISHER_NAME}.get(
                                    failure["stage"])))
    codes.update(code for code, _message, _path in diagnostics)
    document = {
        "demo_version": DEMO_VERSION, "status": status, "profile": capture.PROFILE,
        "adapter_version": capture.ADAPTER_VERSION, "source_commit": _runfile.SOURCE_COMMIT,
        "evidence_class": evidence_class(), "tested_reference": TESTED_REFERENCE,
        "scope": SCOPE, "external_customer_interoperability": _runfile.NOT_TESTED,
        "profile_declaration": "bundled-fom-created", "fom_sha256": pins,
        "rtinode": {"address": LOOPBACK, "port": node.port,
                    "pid": None if node.child is None else node.child.pid,
                    "attempts": node.attempts,
                    "exit_status": None if node.child is None else node.child.status},
        "runs": runs, "cleanup": cleanup,
        "failures": [{k: v for k, v in f.items()} for f in failures],
    }
    classes = [errors.EXIT_CLASS[code] for code in codes if code.startswith("E_")]
    if checkpoint_failed:
        classes.append(3)
    if not cleanup_ok:
        classes.append(errors.EXIT_CLASS[errors.E_IO])
    if status == FAIL and not classes:
        classes.append(errors.EXIT_CLASS[errors.E_RTI_CONNECT])
    exit_code = 0 if status == PASS else max(classes)
    return Outcome(document, host_lines, diagnostics, codes, exit_code)


def _one_run(name: str, target: bytes, port: int, environ: dict, pins: dict, fom_dir: str,
             publisher: str, start_host: Callable, check: Callable, seams: DemoSeams,
             synapse_cdm_version: str | None) -> tuple[dict, Run, RunFailure | None]:
    document = run_config(name, port, new_federation_name())
    live = os.path.join(target, os.fsencode(name))
    replayed = os.path.join(target, os.fsencode(f"{name}-replay"))
    run, failure = run_scenario(name, document, live, main_scenario(), publisher=publisher,
                                fom_dir=fom_dir, pins=pins, environ=environ,
                                start_host=start_host, check=check, seams=seams)
    replay_summary = None
    results: list[dict] = []
    if failure is None:
        try:
            replay_summary = replay_with(
                os.path.join(live, os.fsencode(_runfile.CAPTURE)), replayed,
                manifest=lambda done, header: _runfile.replay_run(
                    done, header, synapse_cdm_version=synapse_cdm_version),
                check=check)
        except errors.HlaError:
            replay_summary = None
        results = checkpoints(name, run, live, replayed if replay_summary else None,
                              replay_summary)
    steps = []
    for barrier in run.scenario.barriers:
        steps.append({"barrier": barrier.number, "event": barrier.event,
                      "tag": None if barrier.tag is None else barrier.tag.decode("ascii"),
                      "seq": run.acknowledged.get(barrier.number),
                      "acknowledged": barrier.number in run.acknowledged})
    passed = failure is None and results and all(c["result"] == PASS for c in results)
    record = {
        "name": name, "directory": name, "replay_directory": f"{name}-replay",
        "session_id": document["session_id"], "time_policy": document["time_policy"]["mode"],
        "federation_name": document["federation_name"],
        "federate_name": document["federate_name"], "endpoint": document["endpoint"],
        "config_sha256": canonical.sha256_hex(canonical.canonical_bytes(document)),
        "publisher": {"pid": None if run.publisher is None else run.publisher.pid,
                      "exit_status": None if run.publisher is None else run.publisher.status,
                      "module_sha256": run.module_sha256,
                      "registered_class": run.registered_class, "created": run.created,
                      "destroyed": run.destroyed, "refreshes": run.refreshes,
                      "refresh_reflections": run.refresh_reflections,
                      "failure": run.publisher_failure},
        "host": None if run.host is None else {"pid": run.host.pid,
                                                "exit_status": run.host.status},
        "steps": steps,
        "refresh_seqs": run.refresh_seqs(),
        "session": _session_block(None if run.host is None else run.host.result),
        "capture_sha256": _sha256_file(os.path.join(live, os.fsencode(_runfile.CAPTURE))),
        "replay": None if replay_summary is None else {
            "status": replay_summary["status"],
            "observations_sha256": _sha256_file(os.path.join(replayed,
                                                             b"observations.jsonl"))},
        "checkpoints": results,
        "result": PASS if passed else FAIL,
    }
    return record, run, failure
