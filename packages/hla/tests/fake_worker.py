"""A scripted stand-in for the native worker `sc-hla-federate`: test support only (round R5).

It is a real child process that speaks the worker protocol of SPEC:273-279 the way a scenario
file says, so that the host's tests drive `synapse_hla.host` exactly as the native worker will
(round R7): an argument vector of `--key=value` tokens (OPS-08), status records on fd 3 (NAT-09,
NAT-15), worker frames on stdout stamped with CLOCK_MONOTONIC (OPV-02), and SIGTERM as the
orderly stop (SPEC:277: the handler only sets a flag).

HOW IT IS STARTED
-----------------
The host runs whatever `SYNAPSE_HLA_WORKER` names; the tests name a small executable script
whose first line is this interpreter (`hla_host_support.worker_executable`), so the fake worker
runs under the same Python as the test. It reads the scenario named by `SC_HLA_FAKE_SCENARIO`:

    {"log": "<file>", "clock": "<file>" | null, "version": {...} | null,
     "attempts": [[step, ...], ...], "self": "<the executable>", "watch": "<file>" | null}

Each start of the process claims the next attempt number (an exclusive `attempt-<n>` file beside
the log) and plays `attempts[n - 1]`. `--version` prints the version line (or what `version` says)
and exits; `version` may also stall, exit with another status, or answer `delay_ms` late (as a
loaded machine's slow start does, review finding R9-r1-F5). Every start appends one JSON line to the log: the attempt, pid, parent pid, process
group, argument vector, which OpenRTI debug variables it saw, whether fd 3 is a FIFO, whether
stdin is the null device, every other descriptor it inherited, its clock base and the size of
the `watch` file (the capture: R06's header comes before the worker); later lines record the stop
signal and the exit.

TIME
----
With `clock` null, `monotonic_ns` is `time.clock_gettime_ns(CLOCK_MONOTONIC)` when the frame is
written (OPV-02). With a clock file (the tests' frozen clock, `hla_host_support.FrozenClock`), the
process reads the frozen time once at start and stamps each frame with that time plus the
step's `dt`: the host's injected clock and this process then agree, and every elapsed_ns of the
capture is exact.

STEPS
-----
`{"do": ...}` with: `stage` (a status stage record), `fail` (a status failure record: `code`,
`message`), `status_raw` / `stdout_raw` / `stderr_raw` (bytes as `hex`), `frame` (`event`,
`dt`), `frames` (`count` copies of `event`, the object token numbered from o`first` (o1) when
`numbered`), `pairs` (`count` request_update/running pairs), `sleep` (`ms`), `wait_term` (logs
`waiting`, then waits for SIGTERM), `stall` (until killed), `exit` (`code`), `close` (`fd`),
`unlink_self`, `hold_pipes` (a child keeps the pipes open for `ms`). After the last step the
process exits 0. Any wait ends when the parent changes (the host is gone) or after `_SAFETY_S`
seconds, so a fake worker never outlives a test by long.
"""

import json
import os
import signal
import stat
import sys
import time

VERSION_LINE = b'{"name":"sc-hla-federate","profile":"SC-HLA-RPR2-OBS-1","version":"1.0.0"}\n'
SCENARIO_VARIABLE = "SC_HLA_FAKE_SCENARIO"
#: Exit codes of their own, so that a test can tell them apart.
NOT_A_FIFO = 70
BAD_ARGUMENTS = 64
SAFETY_EXIT = 99
_SAFETY_S = 60
_OPTIONS = ("--endpoint=", "--federation-name=", "--federate-name=")

_stop = {"flag": False}


def _on_term(_signum, _frame):
    _stop["flag"] = True


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except BrokenPipeError:
            # The host has gone or closed the channel: nothing to report to.
            os._exit(0)
        view = view[written:]


def _log(path: str, record: dict) -> None:
    line = (json.dumps(record, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        _write_all(fd, line)
    finally:
        os.close(fd)


def _claim_attempt(directory: str) -> int:
    number = 1
    while True:
        try:
            os.close(os.open(os.path.join(directory, f"attempt-{number}"),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            return number
        except FileExistsError:
            number += 1


def _inherited() -> list:
    found = []
    for fd in range(4, 256):
        try:
            os.fstat(fd)
        except OSError:
            continue
        found.append(fd)
    return found


def _wait(parent: int, until) -> None:
    deadline = time.monotonic() + _SAFETY_S
    while not until():
        if os.getppid() != parent:
            os._exit(0)
        if time.monotonic() > deadline:
            os._exit(SAFETY_EXIT)
        time.sleep(0.002)


def _status(record: dict) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()


class _Clock:
    def __init__(self, path):
        self.base = None
        if path is not None:
            with open(path, "rb") as handle:
                self.base = int(handle.read())

    def stamp(self, dt: int) -> str:
        if self.base is None:
            return str(time.clock_gettime_ns(time.CLOCK_MONOTONIC))
        return str(self.base + dt)


def _frame(clock: _Clock, event: dict, dt: int) -> bytes:
    record = {"event": event, "monotonic_ns": clock.stamp(dt)}
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main(argv: list) -> int:
    inherited = _inherited()
    signal.signal(signal.SIGTERM, _on_term)
    with open(os.environ[SCENARIO_VARIABLE], "rb") as handle:
        scenario = json.loads(handle.read())
    log = scenario["log"]
    if argv[1:] == ["--version"]:
        version = scenario.get("version") or {}
        _log(log, {"event": "version", "pid": os.getpid()})
        if version.get("stall"):
            _wait(os.getppid(), lambda: False)
        if version.get("delay_ms"):
            time.sleep(version["delay_ms"] / 1000)
        _write_all(1, bytes.fromhex(version["hex"]) if "hex" in version else VERSION_LINE)
        return version.get("exit", 0)
    parent = os.getppid()
    attempt = _claim_attempt(os.path.dirname(log))
    try:
        fifo = stat.S_ISFIFO(os.fstat(3).st_mode)
    except OSError:
        fifo = False
    stdin_null = os.path.samestat(os.fstat(0), os.stat(os.devnull))
    clock = _Clock(scenario.get("clock"))
    watched = None
    if scenario.get("watch"):
        try:
            watched = os.stat(scenario["watch"]).st_size
        except OSError:
            watched = -1
    _log(log, {"event": "start", "attempt": attempt, "pid": os.getpid(), "ppid": parent,
               "pgid": os.getpgrp(), "argv": argv[1:], "fd3_fifo": fifo, "stdin_null": stdin_null,
               "inherited": inherited, "clock": clock.base, "watched": watched,
               "openrti_debug": sorted(k for k in os.environ if k.startswith("OPENRTI_DEBUG"))})
    options = argv[1:]
    if len(options) != len(_OPTIONS) or any(not token.startswith(prefix) for token, prefix
                                            in zip(options, _OPTIONS)):
        return BAD_ARGUMENTS
    if not fifo:
        return NOT_A_FIFO
    attempts = scenario["attempts"]
    steps = attempts[attempt - 1] if attempt <= len(attempts) else [{"do": "exit", "code": 98}]
    noted_term = False
    for step in steps:
        if _stop["flag"] and not noted_term:
            _log(log, {"event": "sigterm", "attempt": attempt})
            noted_term = True
        action = step["do"]
        if action == "stage":
            _write_all(3, _status({"type": "stage", "stage": step["stage"]}))
        elif action == "fail":
            _write_all(3, _status({"type": "failure", "code": step["code"],
                                   "message": step.get("message", "the worker failed")}))
        elif action == "status_raw":
            _write_all(3, bytes.fromhex(step["hex"]))
        elif action == "stdout_raw":
            _write_all(1, bytes.fromhex(step["hex"]))
        elif action == "stderr_raw":
            _write_all(2, bytes.fromhex(step["hex"]))
        elif action == "frame":
            _write_all(1, _frame(clock, step["event"], step.get("dt", 0)))
        elif action == "frames":
            chunk = []
            first = step.get("first", 1)
            for number in range(first, first + step["count"]):
                event = dict(step["event"])
                if step.get("numbered"):
                    event["object_token"] = f"o{number}"
                chunk.append(_frame(clock, event, step.get("dt", 0)))
            _write_all(1, b"".join(chunk))
        elif action == "pairs":
            pair = _status({"type": "stage", "stage": "request_update"}) + \
                _status({"type": "stage", "stage": "running"})
            _write_all(3, pair * step["count"])
        elif action == "sleep":
            end = time.monotonic() + step["ms"] / 1000
            _wait(parent, lambda: time.monotonic() >= end)
        elif action == "wait_term":
            _log(log, {"event": "waiting", "attempt": attempt})
            _wait(parent, lambda: _stop["flag"])
            _log(log, {"event": "sigterm", "attempt": attempt})
            noted_term = True
        elif action == "await_capture":
            # Until the host has captured a line holding `contains` (it writes and flushes each
            # line before it acts on it): what follows then reaches the host after it has acted on
            # that line, whatever order its poll reports the two pipes in.
            marker = step["contains"].encode()

            def captured() -> bool:
                try:
                    with open(scenario["watch"], "rb") as handle:
                        return marker in handle.read()
                except OSError:
                    return False
            _wait(parent, captured)
        elif action == "stall":
            _wait(parent, lambda: False)
        elif action == "exit":
            _log(log, {"event": "exit", "attempt": attempt, "code": step["code"]})
            return step["code"]
        elif action == "close":
            os.close(step["fd"])
        elif action == "unlink_self":
            os.unlink(scenario["self"])
        elif action == "hold_pipes":
            # A child that keeps stdout and fd 3 open after this process has exited, for
            # `ms` milliseconds; it logs its pid so that the test can end it.
            child = os.fork()
            if child == 0:
                time.sleep(step["ms"] / 1000)
                os._exit(0)
            _log(log, {"event": "holder", "attempt": attempt, "holder": child})
        else:
            raise ValueError(f"unknown step {action!r}")
    _log(log, {"event": "exit", "attempt": attempt, "code": 0})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
