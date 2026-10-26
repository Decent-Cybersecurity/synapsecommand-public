"""The host of sections 3 and 20: one observation session, from the pre-flight to the footer.

`run_session(config, output_dir, *, environ, duration_ns=None, seams=V1)` validates the
configuration, checks the dependencies, creates the run directory, writes the capture header,
runs the native worker `sc-hla-federate` (and runs it again, within R14's retry rule), turns what
the worker reports into capture frames, reduces every frame as it is captured, and ends the
capture with its footer. It returns a summary for the command line (round R6), which owns the
argument vector, the environment, `run.json`, the exit code and the RSS parent of the host.

BEFORE ANYTHING EXISTS
----------------------
In this order, each a refusal (`HlaError`) before the run directory exists: the configuration
(E_CONFIG at its pointer); a run directory path no directory can have (E_IO `output_dir`); the
FOM modules of `SYNAPSE_HLA_FOM_DIR`, against the packaged pins and then scanned (OPS-11,
OPS-12: E_DEPENDENCY_PIN); the worker, located per OPV-04 (the absolute path in
`SYNAPSE_HLA_WORKER`, else one fixed place beside the package; never a PATH search) and asked
`--version`, which must print exactly `VERSION_LINE` and exit 0 within the deadline
(E_DEPENDENCY_PIN, path `sc-hla-federate`). Then the directory is made (E_OUTPUT_EXISTS, E_IO;
see `_writer`), and the header is written and synced before any worker starts (R06). Its `config`
is the validated configuration and its `pins` the packaged pin map (OPS-11, RED-V-03); nothing
changes either afterwards (R09). The variables are read from the `environ` mapping the caller
passes; this module reads no environment of its own.

THE WORKER PROCESS
------------------
One worker at a time (R06), started with `os.posix_spawn`, never a shell: an argument vector of
single `--key=value` tokens (OPS-08), an explicit environment (the caller's, without
`OPENRTI_DEBUG_PRIORITY` and `OPENRTI_DEBUG_CATEGORY`, NAV-01), stdin from the null device, its
stdout the frame pipe, fd 3 the status pipe (NAT-09: a pipe end whose number is 0 to 3 is first
moved to 10 or above, so that no DUP2 has equal source and target), stderr the host's own (never
read as protocol, R14), and no other descriptor (every descriptor the package opens is
close-on-exec). It runs in a process group of its own, so that a terminal's interrupt reaches the
host alone and the host decides how the worker stops; the signals Python changes or a parent may
have ignored are reset to their defaults in it.

TWO CHANNELS, NEITHER BLOCKS THE OTHER
-------------------------------------
Both pipes are read without blocking and polled together with the signal wake-up pipe, so a
burst on one never stalls the other (SPEC:277). Lines are cut at LF and bounded before they are
parsed: a frame or status line longer than the line limit is refused as it grows. A partial line
is never accepted (SPEC:277).
- stdout carries `worker-frame.schema.json` records, read by the strict reader (no float, no
  lone surrogate, no duplicate key; CR-R2-11/12). The protocol rules on top: the first frame that
  is not a diagnostic is the worker's one generation_start, whose federation is the configured
  one; the worker never writes generation_end (the host authors every boundary, SPEC:277); a
  worker diagnostic carries one of the codes OPS-30 lets a worker report (so no reducer-derived
  code is ever captured, RED-01, CR-R4-02), and E_RETRACTION_UNSUPPORTED only without object and
  attribute (the token-bearing one is the reducer's, RED-11). A frame that breaks any of this is
  E_CAPTURE_SCHEMA; a line over the limit is E_LIMIT (OPS-19).
- fd 3 carries `worker-status.schema.json` records, one per line, read the same way (NAT-15).
  Stages come in the order connect, running, join, running, resolve, running, then
  {request_update, running}*, then resign, running, disconnect, running; after the orderly stop
  has been asked for, the worker may leave that order to resign (or, before joining, to
  disconnect). A failure record names one of OPS-30's codes with a message within R37's 1024
  UTF-8 bytes. Anything else is E_CAPTURE_SCHEMA.
- Deadlines (R14, NAV-03): from the spawn to the first status record, and from each stage record
  to the `running` that follows it, at most `deadline_ns`; on expiry the worker is killed at once
  (SIGKILL) and the host records E_RTI_TIMEOUT, which only the host may author (OPS-30).

TIME (OPV-01, OPV-02, NAT-10)
-----------------------------
Frames before the first generation_start carry elapsed_ns 0. That frame's `monotonic_ns` is the
session origin, kept across reconnects and worker restarts; every later worker frame carries its
`monotonic_ns` minus the origin, and a worker frame earlier than the frame before it is refused
(E_CAPTURE_SCHEMA: elapsed time never decreases, R16). Frames the host writes itself carry its
own clock minus the origin (`seams.monotonic_ns`, CLOCK_MONOTONIC by default, the worker's clock),
never below the previous frame and never past the last instant the configured epoch admits.
Generation N is the Nth successful join; frames while no generation is open are generation-0
diagnostics. Under external_elapsed, a worker frame whose effective time would pass
9998-12-31T23:59:59.999999Z ends the session with E_CONFIG (SPEC:289).

ONE FRAME
---------
A worker frame is written (`_writer.CaptureWriter`: the chain's line, flushed to the kernel, the
fsync rule of OPS-24, the budget of SPEC:293) before the reducer sees it (R34); then
`reduce_frame` (with `capture_complete` null, SPEC:158) and the records are appended to
`observations.jsonl` and, the diagnostic ones, to `diagnostics.jsonl`. The reducer's terminal
flag is the only stop signal for a fatal fault it derives (CR-R4-03: E_LIMIT for objects, tokens
or cached bytes, RED-12; E_CAPTURE_SCHEMA for an inconsistent rediscovery, RED-07); those codes
are already in the output stream and are never captured again (RED-01).

WHEN A WORKER ENDS: ITS CONDITION
---------------------------------
The first terminal condition of a worker life decides how the worker ends:
- a failure the worker reports, on fd 3 or as a diagnostic frame (NAT-08): the host keeps
  capturing complete frames until stdout ends or `drain_ns` has passed, then kills the worker if
  it has not exited (SPEC:277);
- a condition the host establishes: a deadline (E_RTI_TIMEOUT), the worker's RSS over its limit
  (E_LIMIT, OPS-23; both kill at once and still capture what the worker wrote before, for at most
  `drain_ns`), a malformed or oversize line or a broken protocol (E_CAPTURE_SCHEMA, E_LIMIT), a
  frame the capture's budget cannot take (E_LIMIT, SPEC:293), an effective time past year 9998
  (E_CONFIG), an output file that cannot be written (E_IO) and the reducer's terminal flag (all
  kill at once and capture nothing more);
- an exit nobody asked for, or an unclean exit (not 0) during the orderly stop: E_RTI_CONNECT
  (OPS-19); a clean exit after the orderly stop that leaves a partial line: E_CAPTURE_SCHEMA;
- a worker that has closed both channels can report nothing more (SPEC:277): unless it has
  reported a failure or was asked to stop (each of which has its own bound), it is killed when
  it has not exited `drain_ns` after the second channel ended, and that is the exit nobody asked
  for (E_RTI_CONNECT).
A failure that is never retried and competes with a first condition that is retried (or with a
retraction) still ends the session (SPEC:62), whether the host finds it or the worker reports it
while its frames are still accepted; the first such failure becomes the session's terminal code
and is recorded as the life's second condition (OPS-02's competing failures). Then, in this
order: one diagnostic frame for each recorded condition unless the worker's own copy was captured
or the reducer derived it (NAT-08, RED-01); when a generation is open, exactly one generation_end
whose reason follows from the code that also names the footer (NAT-08): the second condition's
when there is one, else the first's: none (orderly) stop, E_RTI_CONNECT connection_lost,
E_RTI_TIMEOUT timeout, E_LIMIT and E_QUEUE_OVERFLOW limit, E_RETRACTION_UNSUPPORTED retraction,
anything else failure. Later competing failures are kept among the summary's terminal codes
only, so that the end of a session writes a bounded number of frames (`_writer.END_FRAMES`).

RETRY (SPEC:62, NAT-08, OPS-18)
-------------------------------
E_RTI_CONNECT and E_RTI_TIMEOUT are transient: unless a stop was asked for, the next worker is
started `retry_delays_ns[k]` (1, 2, 4 s) after the failure was recorded, for the k-th retry since
the last successful join; a successful join (a captured generation_start) resets the budget.
The host writes nothing while it waits, and the fsync timer of OPS-24 is not served during the
wait, so every line written before it is synced first. Nothing else is retried: profile, name,
capture, limit, resource and configuration failures end the session. An RTI that never answers
gives the shape of OPS-18: the header, one generation-0 diagnostic per attempt (elapsed 0), no
boundary, and a FAILED footer with the last code.

STOPPING AND THE FOOTER
-----------------------
SIGINT, SIGTERM and the end of `duration_ns` (counted from the header write, OPS-15) perform the
same orderly stop: SIGTERM to the worker, which finishes its batch, resigns and disconnects
(R14), and at most `deadline_ns` for it to exit; a second signal changes nothing (OPS-25). So
does a parent that has gone (CR-R6-F2): once per poll tick the session compares its parent's
pid with the one it was started for (`parent_pid`, by default its parent when it starts), and a
change means that the process it reports to was killed and nobody can stop the session any
more, so it stops now, in order. The
footer is COMPLETE, with no reason, when the session ends by that stop with a generation open
and the worker exited by itself with status 0, or ends by a requestRetraction (RED-08) whose
worker exited by itself. A stop that needs force is E_RTI_TIMEOUT: a diagnostic, generation_end
timeout and a FAILED footer (OPS-25, SPEC:184). A stop while no generation is open (before the
first join, during a backoff, during a reconnect attempt) ends FAILED with the last connection
code (OPS-15), or with an E_RTI_CONNECT diagnostic of its own when no attempt failed. Every other
end is FAILED with the code of its condition (R17, R41). The records that end the session may use
the capture's reserve (SPEC:293). After an I/O failure of the capture nothing more is written to
it, so no footer is ever claimed (SPEC:293); the summary says so.

The limits and every timing value come from one frozen `HostSeams` (OPS-21, D-09), with the
clocks, the sleep, the fsync, the capture opener, the RSS probe and the parent probe; `V1` is the
profile's, and only tests pass another.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from synapse_hla import _fom, _schema, _utc, _writer, canonical, capture, errors
from synapse_hla import config as config_rules
from synapse_hla import limits as limits_module
from synapse_hla import reducer
from synapse_hla.errors import HlaError
from synapse_hla.limits import Limits

_SECOND = 1_000_000_000
_MILLISECOND = 1_000_000
_MICROSECOND = 1_000

#: OPV-04: the two variables a caller's environment may set for the host, and the worker's name.
WORKER_VARIABLE = "SYNAPSE_HLA_WORKER"
FOM_DIR_VARIABLE = "SYNAPSE_HLA_FOM_DIR"
WORKER_NAME = "sc-hla-federate"
#: The one fixed place of the worker when no override is set: `bin/sc-hla-federate` inside the
#: installed package (the native build installs it there, rounds R7 and R9).
WORKER_LOCATION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", WORKER_NAME)
#: What `sc-hla-federate --version` prints, exactly: one canonical JSON line.
VERSION_LINE = (b'{"name":"sc-hla-federate","profile":"SC-HLA-RPR2-OBS-1",'
                b'"version":"1.0.0"}\n')
#: NAV-01: never in the worker's environment.
OPENRTI_DEBUG_VARIABLES = ("OPENRTI_DEBUG_PRIORITY", "OPENRTI_DEBUG_CATEGORY")
#: SPEC:277: the worker's status pipe.
STATUS_FD = 3

#: OPS-30: the only codes a worker may report, as a failure record or as a diagnostic frame.
WORKER_CODES = frozenset({errors.E_RTI_CONNECT, errors.E_FOM_PROFILE, errors.E_FEDERATE_NAME,
                          errors.E_QUEUE_OVERFLOW, errors.E_LIMIT, errors.E_CAPTURE_SCHEMA,
                          errors.E_RETRACTION_UNSUPPORTED})
#: SPEC:62: the failures that are retried.
TRANSIENT = frozenset({errors.E_RTI_CONNECT, errors.E_RTI_TIMEOUT})
#: NAT-08: the generation_end reason of a condition while a generation is open.
REASONS = {errors.E_RTI_CONNECT: "connection_lost", errors.E_RTI_TIMEOUT: "timeout",
           errors.E_LIMIT: "limit", errors.E_QUEUE_OVERFLOW: "limit",
           errors.E_RETRACTION_UNSUPPORTED: "retraction"}
STOP = "stop"
FAILURE = "failure"

#: Summary statuses: a footer's two, and INCOMPLETE when no footer could be written.
COMPLETE = capture.COMPLETE
FAILED = capture.FAILED
INCOMPLETE = capture.INCOMPLETE
SUMMARY_VERSION = 1

_WORKER_FRAME = "worker-frame.schema.json"
_WORKER_STATUS = "worker-status.schema.json"
_RUNNING = "running"
#: NAT-15: the stage each stage may follow (after its `running`), and the stages an orderly stop
#: adds: resign once joined, disconnect when only connected.
_NEXT = {None: ("connect",), "connect": ("join",), "join": ("resolve",),
         "resolve": ("request_update",), "request_update": ("request_update",),
         "resign": ("disconnect",), "disconnect": ()}
_WHEN_STOPPING = {"connect": ("disconnect",), "join": ("resign",), "resolve": ("resign",),
                  "request_update": ("resign",)}

#: The fixed messages of the diagnostics the host writes (R37: bounded, no input quoted).
_MESSAGES = {
    "unexpected_exit": "the worker exited although no stop was asked for and it reported no "
                       "failure",
    "unclean_stop": "the worker did not exit with status 0 after the orderly stop",
    "deadline": "the worker did not finish an RTI call or its orderly stop within the host "
                "deadline",
    "frame": "the worker wrote a line that is not a valid worker frame",
    "oversize": "the worker wrote a line longer than the frame limit",
    "status": "the worker wrote a status record that is not valid or out of the protocol's order",
    "protocol": "the worker wrote a frame the worker protocol does not allow there",
    "partial": "the worker exited with a partial line on a channel",
    "reserve": "the next frame would enter the capture's reserve or pass the session's frame "
               "limit",
    "line": "the frame would make a capture line longer than the line limit",
    "capture": "the worker wrote a frame the capture cannot hold",
    "rss": "the worker's resident memory passed its limit",
    "output": "the output files can no longer be written",
    "time": "the external effective time would pass 9998-12-31T23:59:59.999999Z",
    "spawn": "the worker could not be started",
    "before_join": "the session stopped before any worker joined the federation",
    "silent": "the worker closed both of its channels without exiting",
}
_KIB = 1 << 10
_PS = "/bin/ps"
#: How long the default RSS probe waits for `ps` before it reports no reading.
_PS_TIMEOUT_S = 5
#: The longest the host polls without looking at the worker's exit and the clock. Not a timing
#: value of the specification (those are all in `HostSeams`): the granularity at which an exit
#: is noticed while something still holds a pipe open; every deadline wakes the poll itself.
_TICK_NS = 100 * _MILLISECOND
#: The same while both pipes have ended and the process has not been reaped yet.
_REAP_TICK_NS = 5 * _MILLISECOND
_READ_CHUNK = 1 << 16
_OVERSIZE = object()
#: The signals reset to their default actions in the worker: the two Python and this host set
#: to be ignored (SIGPIPE at start-up, SIGXFSZ for OPS-24), and the two of the orderly stop, in
#: case the host itself was started with them ignored. Others keep what the host inherited.
_DEFAULT_SIGNALS = tuple(s for s in (signal.SIGPIPE, getattr(signal, "SIGXFSZ", None),
                                     signal.SIGINT, signal.SIGTERM) if s is not None)


# --- the seam (OPS-21, D-09) ----------------------------------------------------------------------

def _clock_monotonic_ns() -> int:
    # OPV-02: CLOCK_MONOTONIC, the worker's clock; on macOS time.monotonic_ns is another clock.
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC)


def _wall_clock_us() -> int:
    return time.time_ns() // _MICROSECOND


def _sleep(duration_ns: int, wake_fd: int) -> None:
    """Wait `duration_ns`, or less when `wake_fd` becomes readable (a signal arrived)."""
    if duration_ns > 0:
        select.select([wake_fd], [], [], duration_ns / _SECOND)


def rss_from_proc_status(data: bytes) -> int | None:
    """The VmRSS of a Linux `/proc/<pid>/status` text in bytes (the kernel writes kB, meaning
    KiB), or None when the line is not there or not a number."""
    for line in data.splitlines():
        fields = line.split()
        if fields[:1] == [b"VmRSS:"]:
            if len(fields) == 3 and fields[1].isdigit() and fields[2] == b"kB":
                return int(fields[1]) * _KIB
            return None
    return None


def _rss_of(pid: int) -> int | None:
    """The resident set of `pid` in bytes, or None when it cannot be read (OPS-23)."""
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/status", "rb") as status:
                return rss_from_proc_status(status.read())
        except OSError:
            return None
    try:
        result = subprocess.run([_PS, "-o", "rss=", "-p", str(pid)], capture_output=True,
                                timeout=_PS_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.strip()
    if result.returncode != 0 or not text.isdigit():
        return None
    return int(text) * _KIB


@dataclass(frozen=True)
class HostSeams:
    """Every limit and timing value of the host, and the clock, sleep, fsync, capture opener, RSS
    probe and parent probe it uses (OPS-21). Construct only `V1`, or a test's variant of it."""

    #: The fixed v1 limits (D-09).
    limits: Limits = limits_module.V1
    #: R14: connect, join, synchronous requests and graceful shutdown.
    deadline_ns: int = 10 * _SECOND
    #: SPEC:62: the delays before the first, second and third reconnect attempt.
    retry_delays_ns: tuple = (1 * _SECOND, 2 * _SECOND, 4 * _SECOND)
    #: SPEC:277: how long complete frames are still captured after a reported failure.
    drain_ns: int = 1 * _SECOND
    #: SPEC:162, OPS-24: fsync no later than the 100th unsynced line or 250 ms after the first.
    fsync_frames: int = 100
    fsync_interval_ns: int = 250 * _MILLISECOND
    #: OPS-23: how often the worker's RSS is read.
    rss_poll_ns: int = 250 * _MILLISECOND
    monotonic_ns: Callable = field(default=_clock_monotonic_ns)
    #: Microseconds since 1970-01-01T00:00:00Z: the header's audit time, nothing else (R15).
    wall_clock_us: Callable = field(default=_wall_clock_us)
    sleep: Callable = field(default=_sleep)
    fsync: Callable = field(default=_writer.fsync)
    open_capture: Callable = field(default=_writer.open_capture)
    rss_of: Callable = field(default=_rss_of)
    #: CR-R6-F2: the pid of this process's parent, read once per poll tick.
    getppid: Callable = field(default=os.getppid)

    def __post_init__(self) -> None:
        if type(self.limits) is not Limits:
            raise TypeError("limits must be a Limits")
        for name in ("deadline_ns", "drain_ns", "fsync_frames", "fsync_interval_ns",
                     "rss_poll_ns"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive int")
        delays = self.retry_delays_ns
        if type(delays) is not tuple or any(type(d) is not int or d < 0 for d in delays):
            raise ValueError("retry_delays_ns must be a tuple of non-negative ints")
        for name in ("monotonic_ns", "wall_clock_us", "sleep", "fsync", "open_capture",
                     "rss_of", "getppid"):
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")


#: The host of profile SC-HLA-RPR2-OBS-1, version 1.
V1 = HostSeams()


# --- the dependencies (OPS-11, OPV-04) ------------------------------------------------------------

def _environment_of(environ) -> dict:
    if not hasattr(environ, "items"):
        raise TypeError("environ is a mapping of str to str")
    out = {}
    for key, value in environ.items():
        if type(key) is not str or type(value) is not str:
            raise TypeError("environ is a mapping of str to str")
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ValueError("environ holds a name or value no process environment can hold")
        try:
            os.fsencode(key)
            os.fsencode(value)
        except UnicodeEncodeError:
            raise ValueError("environ holds a name or value no process environment can hold") \
                from None
        out[key] = value
    return out


def locate_worker(environ) -> str:
    """The worker's path: the absolute path in `SYNAPSE_HLA_WORKER` when the variable is set,
    otherwise `WORKER_LOCATION` (OPV-04). Never a PATH search. A set value that is not an
    absolute path is E_DEPENDENCY_PIN, path `sc-hla-federate`."""
    environment = _environment_of(environ)
    if WORKER_VARIABLE not in environment:
        return WORKER_LOCATION
    path = environment[WORKER_VARIABLE]
    if not os.path.isabs(path):
        raise HlaError(errors.E_DEPENDENCY_PIN, WORKER_NAME,
                       "SYNAPSE_HLA_WORKER is not an absolute path")
    return path


def worker_environment(environ) -> dict:
    """The worker's explicit environment: `environ` without the OpenRTI debug variables."""
    return {key: value for key, value in _environment_of(environ).items()
            if key not in OPENRTI_DEBUG_VARIABLES}


def worker_arguments(worker: str, config: dict) -> list[str]:
    """OPS-08: the worker's argument vector, one `--key=value` token per parameter."""
    return [worker, f"--endpoint={config['endpoint']}",
            f"--federation-name={config['federation_name']}",
            f"--federate-name={config['federate_name']}"]


def _above_three(fd: int) -> int:
    # NAT-09: a DUP2 whose source is its own target would not clear close-on-exec everywhere.
    if fd > STATUS_FD:
        return fd
    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10)
    os.close(fd)
    return moved


def _pipe() -> tuple[int, int]:
    read_end, write_end = os.pipe()
    return _above_three(read_end), _above_three(write_end)


def _spawn(path: str, argv: list[str], env: dict, stdout_fd: int, status_fd: int | None) -> int:
    actions = [(os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
               (os.POSIX_SPAWN_DUP2, stdout_fd, 1)]
    if status_fd is not None:
        actions.append((os.POSIX_SPAWN_DUP2, status_fd, STATUS_FD))
    return os.posix_spawn(path, argv, env, file_actions=actions, setpgroup=0,
                          setsigdef=_DEFAULT_SIGNALS, setsigmask=())


def _kill(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def _reap(pid: int) -> int:
    """Wait for `pid` (killed or exiting) and return its exit code (minus the signal number)."""
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def _poll_exit(pid: int) -> int | None:
    """The exit code of `pid` if it has ended (and reap it), else None, without blocking."""
    done, status = os.waitpid(pid, os.WNOHANG)
    return os.waitstatus_to_exitcode(status) if done else None


def _milliseconds(duration_ns: int) -> int:
    # poll() takes whole milliseconds; round up so that a deadline is never woken for early.
    return max(0, -(-duration_ns // _MILLISECOND))


def check_worker(worker: str, environ, *, seams: HostSeams = V1) -> None:
    """The pre-flight `sc-hla-federate --version` (OPS-11): exactly `VERSION_LINE` on stdout and
    exit status 0 within the deadline, else E_DEPENDENCY_PIN with path `sc-hla-federate`."""
    refusal = HlaError(errors.E_DEPENDENCY_PIN, WORKER_NAME,
                       "the worker is missing or does not answer --version as this build expects")
    if type(worker) is not str:
        raise TypeError("the worker path is a str")
    try:
        info = os.stat(worker)
    except (OSError, ValueError):
        raise refusal from None
    if not stat.S_ISREG(info.st_mode):
        raise refusal
    env = worker_environment(environ)
    read_end, write_end = _pipe()
    try:
        try:
            pid = _spawn(worker, [worker, "--version"], env, write_end, None)
        except OSError:
            raise refusal from None
        os.close(write_end)
        write_end = -1
        try:
            output, status = _version_probe(pid, read_end, seams)
        except BaseException:
            # Whatever interrupted the probe, the probe does not outlive it (it may already have
            # been reaped, which is all this wants).
            with contextlib.suppress(ChildProcessError):
                if _poll_exit(pid) is None:
                    _kill(pid)
                    _reap(pid)
            raise
    finally:
        os.close(read_end)
        if write_end >= 0:
            os.close(write_end)
    if status != 0 or output != VERSION_LINE:
        raise refusal


def _version_probe(pid: int, read_end: int, seams: HostSeams) -> tuple[bytes, int | None]:
    """What the probe printed and its exit code; None when it had to be killed (it overran the
    deadline or printed more than the version line)."""
    os.set_blocking(read_end, False)
    poller = select.poll()
    poller.register(read_end, select.POLLIN)
    deadline = seams.monotonic_ns() + seams.deadline_ns
    output = bytearray()
    ended = False
    status = None
    while True:
        if status is None:
            status = _poll_exit(pid)
        if status is not None and ended:
            return bytes(output), status
        now = seams.monotonic_ns()
        if now >= deadline or len(output) > len(VERSION_LINE):
            if status is None:
                _kill(pid)
                _reap(pid)
            return bytes(output), None
        if ended:
            # stdout has ended and the process is about to: look again shortly.
            poller.poll(_milliseconds(min(deadline - now, _REAP_TICK_NS)))
            continue
        poller.poll(_milliseconds(min(deadline - now, _TICK_NS)))
        try:
            chunk = os.read(read_end, _READ_CHUNK)
        except BlockingIOError:
            continue
        if chunk:
            output += chunk
        else:
            ended = True
            poller.unregister(read_end)


def preflight(environ, *, seams: HostSeams = V1) -> str:
    """OPS-11's pre-flight: the FOM modules, then the worker; returns the worker's path."""
    environment = _environment_of(environ)
    _fom.check_fom_modules(environment.get(FOM_DIR_VARIABLE, ""), limits=seams.limits)
    worker = locate_worker(environment)
    check_worker(worker, environment, seams=seams)
    return worker


# --- reading the two channels ---------------------------------------------------------------------

class _Lines:
    """LF-cut lines of one pipe, each bounded as it grows: a line longer than `limit` bytes is
    reported once as `_OVERSIZE` and skipped to its LF, never held whole in memory."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.buffer = bytearray()
        self.skipping = False

    def feed(self, data: bytes) -> list:
        out = []
        self.buffer += data
        while True:
            end = self.buffer.find(b"\n")
            if end < 0:
                if len(self.buffer) > self.limit:
                    if not self.skipping:
                        out.append(_OVERSIZE)
                        self.skipping = True
                    self.buffer.clear()
                return out
            line = bytes(self.buffer[:end])
            del self.buffer[:end + 1]
            if self.skipping:
                self.skipping = False
            elif len(line) > self.limit:
                out.append(_OVERSIZE)
            else:
                out.append(line)

    @property
    def partial(self) -> bool:
        """Bytes after the last LF: a line that never ended."""
        return bool(self.buffer) or self.skipping


def _strict_record(line: bytes, schema: str) -> dict | None:
    """`line` read by the strict reader and held to `schema`, or None."""
    try:
        record = canonical.strict_loads(line, floats=False, surrogates=False, staged=True)
    except canonical.StrictJsonError:
        return None
    if type(record) is not dict or _schema.first_problem(schema, record) is not None:
        return None
    return record


def _utf8_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


@dataclass
class _Condition:
    """A terminal condition of a worker life: its code, the message of the diagnostic frame the
    host writes for it (None when no frame is written: the worker's copy was captured, the
    reducer derived it, or the capture can take nothing more)."""

    code: str
    message: str | None


class _Worker:
    """One worker process and what the host knows about it."""

    def __init__(self, pid: int, stdout_fd: int, status_fd: int, now: int,
                 limits: Limits) -> None:
        self.pid = pid
        self.fds = {"stdout": stdout_fd, "status": status_fd}
        self.lines = {"stdout": _Lines(limits.line_bytes), "status": _Lines(limits.line_bytes)}
        self.spawned_at = now
        self.exit_code: int | None = None
        self.reaped_at: int | None = None
        self.killed = False
        self.term_sent = False
        self.stop_kill_at: int | None = None
        self.kill_at: int | None = None
        self.accept_until: int | None = None
        self.accepting = True
        #: The first condition, which decides how the worker ends, and at most one never-retried
        #: failure that competes with it (see the module text).
        self.conditions: list[_Condition] = []
        self.forced = False
        self.joined = False
        self.status_seen = False
        self.stage: str | None = None
        self.pending: tuple[str, int] | None = None
        self.next_rss = now
        #: When the second of the two channels ended while the process was alive, and whether
        #: it was killed for staying alive without them.
        self.silent_since: int | None = None
        self.silent = False

    @property
    def condition(self) -> _Condition | None:
        return self.conditions[0] if self.conditions else None

    @property
    def alive(self) -> bool:
        return self.exit_code is None

    @property
    def done(self) -> bool:
        return self.exit_code is not None and not self.fds

    def accepts(self, now: int) -> bool:
        return self.accepting and (self.accept_until is None or now <= self.accept_until)

    def kill(self) -> None:
        if self.alive and not self.killed:
            _kill(self.pid)
            self.killed = True

    def close(self, name: str) -> None:
        fd = self.fds.pop(name, None)
        if fd is not None:
            os.close(fd)


# --- the session ----------------------------------------------------------------------------------

class _Session:
    def __init__(self, config: dict, worker: str, environment: dict, duration_ns: int | None,
                 seams: HostSeams, on_worker=None, parent_pid: int | None = None) -> None:
        self.config = config
        self.on_worker = on_worker
        self.parent_pid = parent_pid
        self.orphaned = False
        self.worker_path = worker
        self.worker_env = worker_environment(environment)
        self.argv = worker_arguments(worker, config)
        self.seams = seams
        self.limits = seams.limits
        self.duration_ns = duration_ns
        self.duration_end: int | None = None
        epoch = config_rules.epoch_microsecond(config)
        if epoch is None:
            self.max_elapsed = capture.MAX_ELAPSED_NS
        else:
            self.max_elapsed = min(capture.MAX_ELAPSED_NS,
                                   (_utc.MAX_MICROSECOND - epoch) * _MICROSECOND
                                   + _MICROSECOND - 1)
        self.origin: int | None = None
        self.last_elapsed = 0
        self.retries_used = 0
        self.last_connection_code: str | None = None
        self.stop_requested = False
        self.signalled: int | None = None
        self.failure: str | None = None
        self.terminal_codes: list[str] = []
        self.workers = 0
        self.output_failed = False
        self.output_recorded = False
        self.writer: _writer.CaptureWriter | None = None
        self.outputs: _writer.OutputWriter | None = None
        self.state = None
        self.wake_read = -1
        self.wake_write = -1

    # -- time

    def now(self) -> int:
        return self.seams.monotonic_ns()

    def _host_elapsed(self, now: int) -> int:
        if self.origin is None:
            return 0
        return min(max(now - self.origin, self.last_elapsed), self.max_elapsed)

    # -- the terminal record of the session

    def _terminal(self, code: str) -> None:
        if self.failure is None:
            self.failure = code
        if code not in self.terminal_codes:
            self.terminal_codes.append(code)

    # -- writing one frame: capture, reduce, outputs

    def _write(self, generation: int, elapsed: int, event: dict, *, end: bool) -> list:
        """Write a frame, reduce it and append its records; returns the records. Raises
        `_writer.CaptureFull`, `_writer.CaptureBroken` or the chain's `HlaError`."""
        record = self.writer.frame(generation, elapsed, event, self.now(), end=end)
        self.last_elapsed = elapsed
        # The writer's chain has just admitted this frame by the reducer's own rules (CR-L07).
        self.state, records = reducer.reduce_admitted(self.state, record)
        if not self.outputs.broken:
            try:
                self.outputs.write(records)
            except _writer.OutputBroken:
                self.output_failed = True
        return records

    def _host_frame(self, event: dict, *, end: bool) -> list | None:
        """A frame the host authors, stamped with its own clock; None when the capture cannot
        take it (broken, or full for the end of the session: both are recorded here)."""
        generation = self.writer.open_generation or 0
        elapsed = self._host_elapsed(self.now())
        try:
            return self._write(generation, elapsed, event, end=end)
        except _writer.CaptureBroken:
            self._terminal(errors.E_IO)
            return None
        except _writer.CaptureFull:
            if not end:
                raise
            self._terminal(errors.E_LIMIT)
            self.writer.broken = True
            return None

    @staticmethod
    def _diagnostic(code: str, message: str) -> dict:
        return {"type": capture.DIAGNOSTIC, "object_token": None,
                "diagnostic": {"severity": errors.severity(code), "code": code,
                               "message": message, "attribute": None}}

    # -- signals

    def _on_signal(self, signum, _frame) -> None:
        if self.signalled is None:
            self.signalled = signum

    def _drain_wake(self) -> None:
        with contextlib.suppress(BlockingIOError):
            while os.read(self.wake_read, _READ_CHUNK):
                pass

    def _note_stop(self, now: int) -> None:
        if self.signalled is not None:
            self.stop_requested = True
        if self.duration_end is not None and now >= self.duration_end:
            self.stop_requested = True
        if not self.orphaned and self.seams.getppid() != self.parent_pid:
            # CR-R6-F2: the process this session reports to was killed (it would have stopped
            # the session itself otherwise), so nothing else will ever stop it.
            self.orphaned = True
            self.stop_requested = True

    # -- the session

    def run(self, run_dir: _writer.RunDirectory) -> None:
        streams = run_dir.streams
        self.writer = _writer.CaptureWriter(
            streams[_writer.CAPTURE], limits=self.limits, fsync=self.seams.fsync,
            fsync_frames=self.seams.fsync_frames, fsync_interval_ns=self.seams.fsync_interval_ns)
        self.outputs = _writer.OutputWriter(streams[_writer.OBSERVATIONS],
                                            streams[_writer.DIAGNOSTICS])
        audit = _utc.format_microsecond(self.seams.wall_clock_us())
        header = capture.header_record(self.config, pins=_fom.header_pins(),
                                       record_created_at=audit)
        try:
            self.writer.header(header, self.now())
        except _writer.CaptureBroken:
            raise HlaError(errors.E_IO, _writer.OUTPUT_DIR,
                           "the capture header cannot be written") from None
        except _writer.CaptureFull:
            raise HlaError(errors.E_LIMIT, _writer.OUTPUT_DIR,
                           "the capture header does not fit the capture file limit") from None
        self.state = reducer.initial_state(header, None, limits=self.limits)
        if self.duration_ns is not None:
            self.duration_end = self.now() + self.duration_ns
        while self._attempt() and self._backoff():
            pass
        self._finish()

    def _backoff(self) -> bool:
        """Wait before the next attempt; False when a stop came first (OPS-15)."""
        delay = self.seams.retry_delays_ns[self.retries_used]
        self.retries_used += 1
        start = self.now()
        wake_at = start + delay
        if self.duration_end is not None:
            wake_at = min(wake_at, self.duration_end)
        if not self.stop_requested:
            # OPS-24: the timer that bounds how long a line stays unsynced is served only while a
            # worker is supervised, and nothing is written during the wait, so what the failed
            # attempt left (its diagnostic) is made durable before the wait begins.
            try:
                self.writer.sync()
            except _writer.CaptureBroken:
                self._capture_broken(None)
                return False
            self.seams.sleep(max(0, wake_at - start), self.wake_read)
            self._drain_wake()
        self._note_stop(self.now())
        if self.stop_requested:
            self._end_without_generation()
            return False
        return True

    def _end_without_generation(self) -> None:
        """A stop while no generation is open: FAILED with the last connection code (OPS-15),
        or with an E_RTI_CONNECT diagnostic of its own when no attempt has failed yet."""
        if self.failure is not None or self.writer.broken:
            return
        if self.last_connection_code is not None:
            self._terminal(self.last_connection_code)
            return
        self._host_frame(self._diagnostic(errors.E_RTI_CONNECT, _MESSAGES["before_join"]),
                         end=True)
        self._terminal(errors.E_RTI_CONNECT)

    def _finish(self) -> None:
        writer = self.writer
        if self.output_failed and not self.output_recorded and not writer.broken:
            self._host_frame(self._diagnostic(errors.E_IO, _MESSAGES["output"]), end=True)
            self.output_recorded = True
        if self.output_failed:
            self._terminal(errors.E_IO)
        if writer.broken:
            return
        status = FAILED if self.failure is not None else COMPLETE
        try:
            writer.footer(status, self.failure, self.now())
        except _writer.CaptureBroken:
            self._terminal(errors.E_IO)
        except _writer.CaptureFull:
            self._terminal(errors.E_LIMIT)
            writer.broken = True

    # -- one worker

    def _attempt(self) -> bool:
        """Run one worker to its end and record its condition; True when the next attempt is to
        be made."""
        self._note_stop(self.now())
        if self.stop_requested:
            self._end_without_generation()
            return False
        stdout_read, stdout_write = _pipe()
        status_read, status_write = _pipe()
        try:
            pid = _spawn(self.worker_path, self.argv, self.worker_env, stdout_write,
                         status_write)
        except OSError:
            for fd in (stdout_read, stdout_write, status_read, status_write):
                os.close(fd)
            self._spawn_failed()
            return False
        os.close(stdout_write)
        os.close(status_write)
        self.workers += 1
        worker = _Worker(pid, stdout_read, status_read, self.now(), self.limits)
        try:
            self._tell(pid, True)
            for fd in worker.fds.values():
                os.set_blocking(fd, False)
            self._supervise(worker)
        finally:
            if worker.alive:
                _kill(pid)
                worker.exit_code = _reap(pid)
                self._tell(pid, False)
            for name in list(worker.fds):
                worker.close(name)
        return self._after(worker)

    def _tell(self, pid: int, running: bool) -> None:
        # The command line's RSS parent (OPS-23) must be able to end a worker it did not start:
        # the worker has a process group of its own, so killing the host's group misses it.
        if self.on_worker is not None:
            self.on_worker(pid, running)

    def _spawn_failed(self) -> None:
        code = errors.E_DEPENDENCY_PIN
        self._host_frame(self._diagnostic(code, _MESSAGES["spawn"]), end=True)
        self._terminal(code)

    def _supervise(self, worker: _Worker) -> None:
        poller = select.poll()
        for fd in worker.fds.values():
            poller.register(fd, select.POLLIN)
        poller.register(self.wake_read, select.POLLIN)

        def close(name: str) -> None:
            poller.unregister(worker.fds[name])
            worker.close(name)
            if not worker.fds and worker.alive:
                worker.silent_since = self.now()

        while not worker.done:
            now = self.now()
            self._tick(worker, now)
            if worker.reaped_at is not None and now >= worker.reaped_at + self.seams.drain_ns:
                # The process is gone, and something it left holds a pipe open: stop reading.
                for name in list(worker.fds):
                    close(name)
            if worker.done:
                break
            for fd, _event in poller.poll(_milliseconds(self._timeout(worker, now))):
                if fd == self.wake_read:
                    self._drain_wake()
                    continue
                name = next((n for n, f in worker.fds.items() if f == fd), None)
                if name is None:
                    continue
                try:
                    chunk = os.read(fd, _READ_CHUNK)
                except BlockingIOError:
                    continue
                if chunk:
                    self._feed(worker, name, chunk)
                else:
                    close(name)
            if worker.alive:
                code = _poll_exit(worker.pid)
                if code is not None:
                    worker.exit_code = code
                    worker.reaped_at = self.now()
                    self._tell(worker.pid, False)

    def _timeout(self, worker: _Worker, now: int) -> int:
        moments = [now + _TICK_NS]
        if worker.alive and not worker.killed:
            if worker.pending is not None:
                moments.append(worker.pending[1] + self.seams.deadline_ns)
            elif not worker.status_seen:
                moments.append(worker.spawned_at + self.seams.deadline_ns)
            for moment in (worker.kill_at, worker.stop_kill_at):
                if moment is not None:
                    moments.append(moment)
            if self._silent_bound(worker):
                moments.append(worker.silent_since + self.seams.drain_ns)
            moments.append(worker.next_rss)
        if worker.alive and not worker.fds:
            moments.append(now + _REAP_TICK_NS)
        if worker.reaped_at is not None:
            moments.append(worker.reaped_at + self.seams.drain_ns)
        if self.duration_end is not None and not self.stop_requested:
            moments.append(self.duration_end)
        due = self.writer.due()
        if due is not None:
            moments.append(due)
        return max(0, min(moments) - now)

    def _tick(self, worker: _Worker, now: int) -> None:
        self._note_stop(now)
        if worker.alive and not worker.killed:
            if self.stop_requested and worker.condition is None and not worker.term_sent:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(worker.pid, signal.SIGTERM)
                worker.term_sent = True
                worker.stop_kill_at = now + self.seams.deadline_ns
            since = None
            if worker.pending is not None:
                since = worker.pending[1]
            elif not worker.status_seen:
                since = worker.spawned_at
            if since is not None and now - since >= self.seams.deadline_ns:
                self._deadline(worker, now)
            elif worker.stop_kill_at is not None and now >= worker.stop_kill_at:
                self._deadline(worker, now)
            elif worker.kill_at is not None and now >= worker.kill_at:
                if worker.condition is not None and \
                        worker.condition.code == errors.E_RETRACTION_UNSUPPORTED:
                    worker.forced = True
                worker.kill()
            elif self._silent_bound(worker) and \
                    now >= worker.silent_since + self.seams.drain_ns:
                worker.silent = True
                worker.kill()
            elif now >= worker.next_rss:
                worker.next_rss = now + self.seams.rss_poll_ns
                rss = self.seams.rss_of(worker.pid)
                if rss is not None and rss > self.limits.worker_rss_bytes:
                    self._establish(worker, errors.E_LIMIT, _MESSAGES["rss"], now,
                                    kill=True, drain=True)
        try:
            self.writer.sync_if_due(now)
        except _writer.CaptureBroken:
            self._capture_broken(worker)

    @staticmethod
    def _silent_bound(worker: _Worker) -> bool:
        """Whether the bound on a worker alive without its channels applies: both ended, and
        neither a reported failure (`kill_at`) nor the orderly stop (`stop_kill_at`) bounds the
        worker already."""
        return worker.silent_since is not None and worker.condition is None and \
            not worker.term_sent

    def _deadline(self, worker: _Worker, now: int) -> None:
        """R14, NAV-03: kill at once and record E_RTI_TIMEOUT (unless a condition came first)."""
        if worker.condition is None:
            self._establish(worker, errors.E_RTI_TIMEOUT, _MESSAGES["deadline"], now,
                            kill=True, drain=True)
        else:
            if worker.condition.code == errors.E_RETRACTION_UNSUPPORTED:
                worker.forced = True
            worker.kill()

    def _establish(self, worker: _Worker, code: str, message: str | None, now: int, *,
                   kill: bool, drain: bool) -> None:
        """Make `code` the worker's condition (the first one stays), stop accepting frames now
        or after the drain window, and kill the worker now or after it. A code that is never
        retried ends the session whatever came first, so it is a terminal code of the session
        even when it is not the worker's condition (OPS-02: competing terminal failures); the
        first such code of the session, when it competes with a condition that is retried or a
        retraction, is recorded as the worker's second condition, with its own diagnostic frame
        and the generation_end reason (NAT-08: the footer's code comes from the same code)."""
        never_retried = code not in TRANSIENT and code != errors.E_RETRACTION_UNSUPPORTED
        if worker.condition is None:
            worker.conditions.append(_Condition(code, message))
        elif never_retried and self.failure is None and \
                all(c.code != code for c in worker.conditions):
            worker.conditions.append(_Condition(code, message))
        if never_retried:
            self._terminal(code)
        if drain:
            limit = now + self.seams.drain_ns
            worker.accept_until = limit if worker.accept_until is None \
                else min(worker.accept_until, limit)
        else:
            worker.accepting = False
        if kill:
            worker.kill()
        elif worker.kill_at is None:
            worker.kill_at = now + self.seams.drain_ns

    def _reported(self, worker: _Worker, code: str, message: str | None, now: int) -> None:
        """A failure the worker reports (NAT-08): on fd 3 with its message, or as a diagnostic
        frame that was captured (`message` None: that frame is the condition's diagnostic). A
        code it already reported in this life is the same condition, and a captured copy means
        the host writes no frame of its own for it."""
        for condition in worker.conditions:
            if condition.code == code:
                if message is None:
                    condition.message = None
                return
        self._establish(worker, code, message, now, kill=False, drain=True)

    def _host_fault(self, worker: _Worker, code: str, message: str | None) -> None:
        """A fault the host found in what the worker sent or in what it could capture: nothing
        more is accepted from this worker, which is killed at once."""
        self._establish(worker, code, message, self.now(), kill=True, drain=False)

    def _status_fault(self, worker: _Worker, now: int) -> None:
        """A status record outside the protocol (E_CAPTURE_SCHEMA): the worker is killed at once,
        but the frame channel is not at fault, and the two channels keep no order between
        them, so the complete frames it had already written are still drained (SPEC:277)."""
        self._establish(worker, errors.E_CAPTURE_SCHEMA, _MESSAGES["status"], now, kill=True,
                        drain=True)

    def _capture_broken(self, worker: _Worker | None) -> None:
        self._terminal(errors.E_IO)
        if worker is not None:
            self._establish(worker, errors.E_IO, None, self.now(), kill=True, drain=False)

    # -- the channels

    def _feed(self, worker: _Worker, name: str, chunk: bytes) -> None:
        for line in worker.lines[name].feed(chunk):
            if name == "stdout":
                self._frame_line(worker, line)
            else:
                self._status_line(worker, line)

    def _status_line(self, worker: _Worker, line) -> None:
        now = self.now()
        record = None if line is _OVERSIZE else _strict_record(line, _WORKER_STATUS)
        if worker.condition is not None:
            # A dying worker's stages only tell the host what it is blocked in; a failure it
            # reports while its frames are still accepted is a report like the first one (a
            # never-retried one competes, see `_establish`). Anything else changes nothing now.
            if record is None:
                return
            if record["type"] == "stage":
                stage = record["stage"]
                worker.pending = None if stage == _RUNNING else (stage, now)
            elif worker.accepts(now) and record["code"] in WORKER_CODES and \
                    _utf8_bytes(record["message"]) <= self.limits.diagnostic_message_utf8_bytes:
                self._reported(worker, record["code"], record["message"], now)
            return
        if record is None:
            self._status_fault(worker, now)
            return
        worker.status_seen = True
        if record["type"] == "failure":
            code, message = record["code"], record["message"]
            if code not in WORKER_CODES or \
                    _utf8_bytes(message) > self.limits.diagnostic_message_utf8_bytes:
                self._status_fault(worker, now)
                return
            self._reported(worker, code, message, now)
            return
        stage = record["stage"]
        if stage == _RUNNING:
            if worker.pending is None:
                self._status_fault(worker, now)
                return
            worker.stage = worker.pending[0]
            worker.pending = None
            return
        allowed = _NEXT[worker.stage]
        if worker.term_sent:
            allowed = allowed + _WHEN_STOPPING.get(worker.stage, ())
        if worker.pending is not None or stage not in allowed:
            self._status_fault(worker, now)
            return
        worker.pending = (stage, now)

    def _frame_line(self, worker: _Worker, line) -> None:
        if not worker.accepts(self.now()):
            return
        if line is _OVERSIZE:
            self._host_fault(worker, errors.E_LIMIT, _MESSAGES["oversize"])
            return
        record = _strict_record(line, _WORKER_FRAME)
        if record is None:
            self._host_fault(worker, errors.E_CAPTURE_SCHEMA, _MESSAGES["frame"])
            return
        event = record["event"]
        kind = event["type"]
        monotonic = int(record["monotonic_ns"])
        if not self._allowed(worker, event):
            self._host_fault(worker, errors.E_CAPTURE_SCHEMA, _MESSAGES["protocol"])
            return
        origin = self.origin
        if origin is None and kind == capture.GENERATION_START:
            origin = monotonic
        if origin is None:
            elapsed = 0
        else:
            elapsed = monotonic - origin
            if elapsed < self.last_elapsed:
                self._host_fault(worker, errors.E_CAPTURE_SCHEMA, _MESSAGES["protocol"])
                return
        if kind == capture.GENERATION_START:
            generation = self.writer.next_generation
        else:
            generation = self.writer.open_generation or 0
        terminal_before = self.state.terminal
        try:
            records = self._write(generation, elapsed, event, end=False)
        except _writer.CaptureFull:
            self._host_fault(worker, errors.E_LIMIT, _MESSAGES["reserve"])
            return
        except _writer.CaptureBroken:
            self._capture_broken(worker)
            return
        except HlaError as refusal:
            # The chain refused the frame: a line over the limit, a value the capture cannot
            # hold, or an effective time past year 9998 (SPEC:289).
            self._host_fault(worker, refusal.code, {
                errors.E_LIMIT: _MESSAGES["line"], errors.E_CONFIG: _MESSAGES["time"],
            }.get(refusal.code, _MESSAGES["capture"]))
            return
        if kind == capture.GENERATION_START:
            self.origin = origin
            worker.joined = True
            self.retries_used = 0
        if self.output_failed and worker.condition is None:
            self._host_fault(worker, errors.E_IO, _MESSAGES["output"])
            return
        if not terminal_before and self.state.terminal:
            self._reducer_terminal(worker, records)
            return
        if kind == capture.DIAGNOSTIC:
            self._reported(worker, event["diagnostic"]["code"], None, self.now())

    def _allowed(self, worker: _Worker, event: dict) -> bool:
        """The worker protocol's rules for a frame at this point (see the module text)."""
        kind = event["type"]
        if kind == capture.GENERATION_END:
            return False
        if kind == capture.GENERATION_START:
            return not worker.joined and \
                event["federation_name"] == self.config["federation_name"]
        if kind == capture.DIAGNOSTIC:
            diagnostic = event["diagnostic"]
            if diagnostic["code"] not in WORKER_CODES:
                return False
            if diagnostic["code"] == errors.E_RETRACTION_UNSUPPORTED:
                return event["object_token"] is None and diagnostic["attribute"] is None
            return True
        return worker.joined

    def _reducer_terminal(self, worker: _Worker, records: list) -> None:
        """CR-R4-03: the reducer derived a fatal fault (RED-07, RED-12); its diagnostic is already
        in the output stream, so the host writes none (RED-01)."""
        codes = [r["payload"]["code"] for r in records if r["kind"] == reducer.DIAGNOSTIC
                 and r["payload"]["code"] in (errors.E_LIMIT, errors.E_CAPTURE_SCHEMA)]
        if not codes:
            raise RuntimeError("the reducer set its terminal flag without a terminal diagnostic")
        self._host_fault(worker, codes[0], None)

    # -- after the worker

    def _after(self, worker: _Worker) -> bool:
        conditions = list(worker.conditions)
        condition = worker.condition
        partial = any(lines.partial for lines in worker.lines.values())
        if condition is None:
            clean = worker.exit_code == 0 and not worker.killed
            if worker.silent:
                condition = _Condition(errors.E_RTI_CONNECT, _MESSAGES["silent"])
            elif not self.stop_requested:
                condition = _Condition(errors.E_RTI_CONNECT, _MESSAGES["unexpected_exit"])
            elif not clean:
                condition = _Condition(errors.E_RTI_CONNECT, _MESSAGES["unclean_stop"])
            elif partial:
                condition = _Condition(errors.E_CAPTURE_SCHEMA, _MESSAGES["partial"])
            if condition is not None:
                conditions = [condition]
        code = None if condition is None else condition.code
        if code in TRANSIENT:
            self.last_connection_code = code
        retry = (code in TRANSIENT and self.failure is None and not self.stop_requested
                 and not self.writer.broken and not self.output_failed
                 and self.retries_used < len(self.seams.retry_delays_ns))
        forced = worker.forced and code == errors.E_RETRACTION_UNSUPPORTED
        events = [self._diagnostic(each.code, each.message) for each in conditions
                  if each.message is not None]
        if forced:
            events.append(self._diagnostic(errors.E_RTI_TIMEOUT, _MESSAGES["deadline"]))
        opened = self.writer.open_generation is not None
        if opened:
            # NAT-08: the reason and the footer come from the same code, the competing
            # never-retried failure's when one was recorded.
            deciding = conditions[-1].code if len(conditions) > 1 else code
            reason = STOP if deciding is None else REASONS.get(deciding, FAILURE)
            events.append({"type": capture.GENERATION_END, "reason": reason})
        if retry:
            try:
                for event in events:
                    if self._host_frame(event, end=False) is None:
                        return False
            except _writer.CaptureFull:
                self._limit_at_end()
                return False
            return True
        for event in events:
            if self._host_frame(event, end=True) is None:
                return False
            if event["type"] == capture.DIAGNOSTIC and \
                    event["diagnostic"]["code"] == errors.E_IO:
                self.output_recorded = True
        if code is None:
            if not opened:
                self._end_without_generation()
        elif forced:
            self._terminal(errors.E_RTI_TIMEOUT)
        elif code != errors.E_RETRACTION_UNSUPPORTED or not opened:
            # RED-08's COMPLETE needs the generation the retraction ended; without one it is
            # an ordinary failure.
            self._terminal(code)
        return False

    def _limit_at_end(self) -> None:
        """A retry's frames do not fit the reserve: the session ends with E_LIMIT (SPEC:293)."""
        self._host_frame(self._diagnostic(errors.E_LIMIT, _MESSAGES["reserve"]), end=True)
        if self.writer.open_generation is not None and not self.writer.broken:
            self._host_frame({"type": capture.GENERATION_END, "reason": REASONS[errors.E_LIMIT]},
                             end=True)
        self._terminal(errors.E_LIMIT)

    # -- the result

    def summary(self) -> dict:
        writer = self.writer
        footer = writer.written_footer
        if footer is None:
            status, reason = INCOMPLETE, None
        else:
            status, reason = footer["status"], footer["reason_code"]
        outputs = self.outputs
        files = {_writer.CAPTURE: writer.entry()}
        files.update(outputs.entries())
        return {
            "session_summary_version": SUMMARY_VERSION,
            "status": status,
            "reason_code": reason,
            "terminal_codes": list(self.terminal_codes),
            "capture_complete": None,
            "last_seq": writer.last_seq,
            "frames": writer.frames,
            "last_generation": writer.last_generation,
            "workers": self.workers,
            "records": dict(outputs.kinds),
            "suppressions": dict(outputs.reasons),
            "errors": {code: n for code, n in outputs.codes.items()
                       if n and code.startswith("E_")},
            "warnings": {code: n for code, n in outputs.codes.items()
                         if n and code.startswith("W_")},
            "files": files,
        }


# --- the entry point ------------------------------------------------------------------------------

def run_session(config, output_dir, *, environ, duration_ns: int | None = None,
                seams: HostSeams = V1, on_worker=None, parent_pid: int | None = None) -> dict:
    """One live session; see the module text. Returns the summary.

    Raises `HlaError` only before the worker first starts (configuration, dependencies, the run
    directory, the header); a fault of the session itself is in the capture and the summary.
    `TypeError` and `ValueError` are caller bugs. `ReducerDefect` and `ProjectionDefect` (and any
    other exception that is not `HlaError`) are defects: the worker is killed and the exception
    propagates, leaving the capture without its footer.

    `on_worker(pid, running)`, when given, is told each worker process as it starts (`True`, the
    session's signal handlers are in place by then) and as it is reaped (`False`): the command
    line's RSS parent (OPS-23) ends the workers of a host it has to kill. An exception it raises
    is a defect like any other.

    `parent_pid` is the process the session reports to (CR-R6-F2): when this process's parent is
    another one at a poll tick, the session stops in order. By default it is the parent this
    process has when the call starts; the command line passes its own pid from before the fork,
    so that a parent killed even before the call is noticed.
    """
    if type(seams) is not HostSeams:
        raise TypeError("seams must be a HostSeams")
    if on_worker is not None and not callable(on_worker):
        raise TypeError("on_worker must be callable")
    if parent_pid is None:
        parent_pid = seams.getppid()
    elif type(parent_pid) is not int:
        raise TypeError("parent_pid is an int or None")
    elif parent_pid < 1:
        raise ValueError("parent_pid is a process id, 1 or more")
    if duration_ns is not None and (type(duration_ns) is not int or duration_ns < 1):
        raise ValueError("duration_ns is a positive int or None")
    environment = _environment_of(environ)
    validated = config_rules.validate_config(config)
    target = _writer.output_path(output_dir)
    worker = preflight(environment, seams=seams)
    run_dir = _writer.RunDirectory(target, open_capture=seams.open_capture, fsync=seams.fsync)
    session = _Session(validated, worker, environment, duration_ns, seams, on_worker, parent_pid)
    try:
        with _signals(session):
            session.run(run_dir)
    finally:
        run_dir.close()
    return session.summary()


@contextlib.contextmanager
def _signals(session: _Session):
    """SIGINT and SIGTERM ask for the orderly stop, through a wake-up pipe the session polls;
    SIGXFSZ is ignored so that a file-size limit is an I/O error, not the end of the process
    (OPS-24). Restored afterwards. Signal handlers exist only in the main thread; elsewhere the
    session runs without them and stops by its duration or by failure.

    Once the handlers exist the two stop signals are unblocked, and the signal mask found is put
    back first when the session ends. A caller that kept them blocked until now (the command
    line's host process, from its fork) thereby hands a stop that arrived meanwhile to the
    session: it was pending, and it is delivered to the handler here, so the session stops in
    order at its first poll instead of losing it (CR-R8-06)."""
    read_end, write_end = _pipe()
    os.set_blocking(read_end, False)
    os.set_blocking(write_end, False)
    session.wake_read, session.wake_write = read_end, write_end
    main = threading.current_thread() is threading.main_thread()
    saved = {}
    old_wakeup = None
    old_mask = None
    try:
        if main:
            for signum in (signal.SIGINT, signal.SIGTERM):
                saved[signum] = signal.signal(signum, session._on_signal)
            if hasattr(signal, "SIGXFSZ"):
                saved[signal.SIGXFSZ] = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            old_wakeup = signal.set_wakeup_fd(write_end, warn_on_full_buffer=False)
            old_mask = signal.pthread_sigmask(signal.SIG_UNBLOCK,
                                              (signal.SIGINT, signal.SIGTERM))
        yield
    finally:
        if main:
            if old_mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
            signal.set_wakeup_fd(old_wakeup if old_wakeup is not None else -1)
            for signum, handler in saved.items():
                signal.signal(signum, handler)
        os.close(read_end)
        os.close(write_end)
