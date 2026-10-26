"""The native worker `sc-hla-federate` (round R7), as a child process: the `rti` group.

WHAT RUNS
---------
Every test here starts a native executable built from `src/native` (by `check.sh` step 8 into
the run's scratch directory, never into the tree) and reads what it did:
- the worker itself (`SYNAPSE_HLA_WORKER`): its start (version line, argument vector, status
  pipe), and its lifecycle against a closed loopback port, a silent listener and a real `rtinode`
  (`SYNAPSE_HLA_RTINODE`) that holds no federation;
- the test harness `sc-hla-harness` (`SYNAPSE_HLA_HARNESS`, NAT-07 a): the worker's own code with
  its event loop replaced by a scenario that calls the observer's callbacks directly, on an
  OpenRTI federation inside the harness process (thread://, no rtinode). It is the only way to
  produce the callbacks the pinned RTI never delivers (OPS-05, NAT-07: unknown attributes,
  retractions, empty maps, oversize values, names that are not Unicode, a full queue), and it
  wraps the observer's RTIambassador in the recording decorator of NAT-07 (b), so that each run
  also proves which RTI services the observer called.
Most runs go through the real host (`host.run_session`, in this process, the host's own clock),
so that the frames are held exactly as a live session holds them: schema, chain, capture,
reducer, outputs, then `check_session` (the tests' own reader, verify, replay against the live
records). A harness run under the host is started through a two-line shell script standing in
for `sc-hla-federate`, which adds the harness's own options to the host's argument vector. Runs
that need what the host does not do (a reader that stops reading, a parent that dies, an exact
count of frames) start the executable directly, the way the host does: `os.posix_spawn`, stdin
the null device, stdout and fd 3 on pipes, a process group of its own.

Absent executables are BLOCKED through `hla_support.native_executable` (D-07); `check.sh` step 8
supplies all three, so a skip there is a failure. Every process a test starts is stopped by PID
and asserted gone. Sockets are opened on 127.0.0.1 only.

EVIDENCE CLASS
--------------
Results on this Mac are development evidence, DEV-macOS-arm64 (CR-L04), against the OpenRTI
development build of NAT-02. Nothing here is release evidence and nothing claims compatibility
with any RTI installation.

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
The stimuli are written in `src/native/tests/harness.cpp`; the expected frames below are written
out by hand from those stimuli and the rulings (event.schema.json's shape, NAT-04's class name,
NAT-11's tokens, NAT-17's remove, R13's orders), byte values as hex literals (an IEEE double 5.0
is 4014000000000000), never read back from the product. Reducer outcomes are the codes RED-01,
RED-11 and R22 prescribe, in R33's order.
"""

from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import json
import os
import pathlib
import select
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

from hla_support import (
    AUDIT_US, FOM_DIR_VARIABLE, HARNESS_VARIABLE, RTINODE_VARIABLE, SMALL_RSS, WORKER_VARIABLE,
    capture_shape, case, check_session, example_json, fom_modules, native_executable,
    process_gone, strict_json, validator,
)
from synapse_hla import host

pytestmark = pytest.mark.rti

SECOND = 1_000_000_000
MS = 1_000_000
PE = "HLAobjectRoot.BaseEntity.PhysicalEntity"
#: config-existing.json's names: the observer joins an existing federation (R07, R10).
FED = "SC_DEMO_0123456789abcdef"
OBSERVER = "SC_OBSERVER"
#: CR-R5-02: what `sc-hla-federate --version` prints, written out here again.
VERSION_LINE = b'{"name":"sc-hla-federate","profile":"SC-HLA-RPR2-OBS-1","version":"1.0.0"}\n'
#: The worker's exit statuses (src/native/worker/process.h; README).
EXIT_STOPPED, EXIT_FAILURE, EXIT_USAGE, EXIT_STATUS_CHANNEL = 0, 1, 64, 70
EXIT_CHANNEL_LOST, EXIT_PARENT_GONE = 71, 72
#: CR-new-R7-15: the only two lines the worker ever writes on stderr (worker/main.cpp), written
#: out again.
USAGE_LINE = (b"sc-hla-federate: usage: sc-hla-federate --version | --endpoint=rti://ADDRESS:PORT "
              b"--federation-name=NAME --federate-name=NAME\n")
STATUS_PIPE_LINE = b"sc-hla-federate: file descriptor 3 is not the status pipe\n"

# The stimulus values of harness.cpp, written out again.
ENTITY_IDENTIFIER = "000100020003"
ENTITY_TYPE = "010100e101020304"
#: The bundled capture's first Spatial (DRM_FPW at 6378137, 0, 0; velocity 0, 10, 0) with its
#: uninterpreted bytes 1..7 set to a1..a7 and 33..35 to b1..b3.
SPATIAL_PADDED = ("02a1a2a3a4a5a6a7415854a6400000000000000000000000000000000000000000b1b2b3"
                  "000000000000000000000000000000004120000000000000")
EVERY_BYTE = "".join(f"{value:02x}" for value in range(256))
#: IEEE 754 binary64, big-endian (HLAfloat64Time's encoding): 5.0 = 1.25 * 2^2, 7.0 = 1.75 * 2^2.
TIME_5 = {"implementation": "HLAfloat64Time", "hex": "4014000000000000"}
TIME_7 = {"implementation": "HLAfloat64Time", "hex": "401c000000000000"}

FRAME_VALIDATOR = validator("worker-frame.schema.json")
STATUS_VALIDATOR = validator("worker-status.schema.json")


# ============================================================================ the executables

def worker() -> pathlib.Path:
    return native_executable(WORKER_VARIABLE)


def harness() -> pathlib.Path:
    return native_executable(HARNESS_VARIABLE)


def rtinode() -> pathlib.Path:
    return native_executable(RTINODE_VARIABLE)


def fom_dir() -> str:
    return str(fom_modules()[0].parent)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def plain_environment(**extra) -> dict:
    """This process's environment without any SYNAPSE_HLA_ variable, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYNAPSE_HLA_")}
    env.update(extra)
    return env


# ============================================================================ things on 127.0.0.1

class Rtinode:
    """An rtinode of the pinned OpenRTI listening on a free loopback port (LC_ALL=C, NAT-18),
    ready once a raw TCP connect succeeds; stopped by its PID and asserted gone."""

    def __init__(self, work: pathlib.Path, *, debug: bool = False) -> None:
        self.port = free_port()
        self.log = work / "rtinode.stdout"
        self.errors = work / "rtinode.stderr"
        env = plain_environment(LC_ALL="C")
        for name in ("OPENRTI_DEBUG_PRIORITY", "OPENRTI_DEBUG_CATEGORY"):
            env.pop(name, None)
        if debug:
            env["OPENRTI_DEBUG_PRIORITY"] = "9"
        with open(self.log, "wb") as log, open(self.errors, "wb") as errors_:
            self.proc = subprocess.Popen([str(rtinode()), "-i", f"127.0.0.1:{self.port}"],
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=errors_,
                                         env=env, start_new_session=True)
        deadline = time.monotonic() + 20
        while True:
            assert self.proc.poll() is None, self.errors.read_text(errors="replace")
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return
            except OSError:
                assert time.monotonic() < deadline, "rtinode did not listen"
                time.sleep(0.02)

    @property
    def endpoint(self) -> str:
        return f"rti://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        assert process_gone(self.proc.pid)


class SilentListener:
    """A loopback listener that accepts connections and never answers (A-TIMEOUT's stimulus:
    OpenRTI's connect then blocks well past any host deadline)."""

    def __init__(self) -> None:
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(16)
        self.port = self.server.getsockname()[1]
        self.accepted: list[socket.socket] = []
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            self.accepted.append(connection)

    @property
    def endpoint(self) -> str:
        return f"rti://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.close()
        self._thread.join(timeout=10)
        for connection in self.accepted:
            connection.close()


class HeldProxy:
    """A loopback proxy that accepts a connection and holds it, unanswered, until `release()`;
    then it connects to `upstream` and relays both ways, bytes sent meanwhile included. It lets a
    test hold the worker inside connect for as long as it wants and then let connect succeed."""

    def __init__(self, upstream: int) -> None:
        self.upstream = upstream
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        self.client: socket.socket | None = None
        self.peer: socket.socket | None = None
        self.accepted = threading.Event()
        self._released = threading.Event()
        self._threads = [threading.Thread(target=self._run, daemon=True)]
        self._threads[0].start()

    def _run(self) -> None:
        try:
            self.client, _ = self.server.accept()
        except OSError:
            return
        self.accepted.set()
        self._released.wait()
        self.peer = socket.create_connection(("127.0.0.1", self.upstream))
        for source, target in ((self.client, self.peer), (self.peer, self.client)):
            thread = threading.Thread(target=self._pump, args=(source, target), daemon=True)
            self._threads.append(thread)
            thread.start()

    @staticmethod
    def _pump(source: socket.socket, target: socket.socket) -> None:
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                target.sendall(data)
        except OSError:
            pass
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    @property
    def endpoint(self) -> str:
        return f"rti://127.0.0.1:{self.port}"

    def release(self) -> None:
        self._released.set()

    def close(self) -> None:
        self._released.set()
        self.server.close()
        for each in (self.client, self.peer):
            if each is not None:
                each.close()
        for thread in self._threads:
            thread.join(timeout=10)


# ============================================================================ direct runs

def _above(fd: int, floor: int = 10) -> int:
    # NAT-09: a pipe end numbered 0..3 would be its own DUP2 target.
    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, floor)
    os.close(fd)
    return moved


class DirectRun:
    """An executable started as the host starts the worker (`os.posix_spawn`: stdin the null
    device, stdout and fd 3 on pipes, no other descriptor, a process group of its own), its two
    channels read by threads of this test. `read_frames=False` leaves stdout unread until
    `read_frames_now()`: a host that does not read; `read_status=False` leaves fd 3 unread, for a
    test to take with `take_status_fd()`. `status_pipe=False` leaves fd 3 closed; `status_file`
    puts a regular file there instead. Unlike the host's worker, stderr is a pipe too, read by a
    thread, so that a test can hold what the process writes there (CR-new-R7-15)."""

    def __init__(self, argv: list[str], *, env: dict | None = None, read_frames: bool = True,
                 read_status: bool = True, status_pipe: bool = True,
                 status_file: pathlib.Path | None = None) -> None:
        stdout_read, stdout_write = (_above(fd) for fd in os.pipe())
        stderr_read, stderr_write = (_above(fd) for fd in os.pipe())
        actions = [(os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
                   (os.POSIX_SPAWN_DUP2, stdout_write, 1),
                   (os.POSIX_SPAWN_DUP2, stderr_write, 2)]
        status_read = status_write = None
        if status_pipe:
            status_read, status_write = (_above(fd) for fd in os.pipe())
            actions.append((os.POSIX_SPAWN_DUP2, status_write, 3))
        elif status_file is not None:
            actions.append((os.POSIX_SPAWN_OPEN, 3, str(status_file),
                            os.O_WRONLY | os.O_CREAT, 0o600))
        self.pid = os.posix_spawn(argv[0], argv, plain_environment() if env is None else env,
                                  file_actions=actions, setpgroup=0)
        os.close(stdout_write)
        os.close(stderr_write)
        if status_write is not None:
            os.close(status_write)
        self._stdout = bytearray()
        self._status = bytearray()
        self._stderr = bytearray()
        self._frames_fd = stdout_read
        self._status_fd = None
        self._threads = []
        self._start(stderr_read, self._stderr)
        if status_read is not None:
            if read_status:
                self._start(status_read, self._status)
            else:
                self._status_fd = status_read
        if read_frames:
            self.read_frames_now()
        self.exit_code: int | None = None

    def _start(self, fd: int, sink: bytearray) -> None:
        def pump():
            try:
                while True:
                    chunk = os.read(fd, 1 << 16)
                    if not chunk:
                        return
                    sink.extend(chunk)
            finally:
                os.close(fd)
        thread = threading.Thread(target=pump, daemon=True)
        self._threads.append(thread)
        thread.start()

    def read_frames_now(self) -> None:
        if self._frames_fd is not None:
            self._start(self._frames_fd, self._stdout)
            self._frames_fd = None

    def take_frames_fd(self) -> int:
        """This test's end of stdout, unread so far; the test reads and closes it itself."""
        fd, self._frames_fd = self._frames_fd, None
        assert fd is not None
        return fd

    def take_status_fd(self) -> int:
        """This test's end of fd 3 (`read_status=False`); the test reads and closes it itself."""
        fd, self._status_fd = self._status_fd, None
        assert fd is not None
        return fd

    def wait(self, timeout: float = 120) -> int:
        """The exit code (minus the signal number for a signal), once both channels ended."""
        deadline = time.monotonic() + timeout
        while self.exit_code is None:
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                self.exit_code = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic() > deadline:
                self.kill()
                raise AssertionError(f"process {self.pid} did not end within {timeout} s")
            time.sleep(0.005)
        self.read_frames_now()
        for thread in self._threads:
            thread.join(timeout=30)
            assert not thread.is_alive(), "a channel stayed open after the process ended"
        assert process_gone(self.pid)
        return self.exit_code

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        if self.exit_code is None:
            _, status = os.waitpid(self.pid, 0)
            self.exit_code = os.waitstatus_to_exitcode(status)
        self.read_frames_now()

    def alive(self) -> bool:
        if self.exit_code is not None:
            return False
        done, status = os.waitpid(self.pid, os.WNOHANG)
        if done:
            self.exit_code = os.waitstatus_to_exitcode(status)
            return False
        return True

    def status_bytes(self) -> bytes:
        return bytes(self._status)

    def frame_bytes(self) -> bytes:
        return bytes(self._stdout)

    def stderr_bytes(self) -> bytes:
        return bytes(self._stderr)

    def status(self) -> list[dict]:
        return status_records(self.status_bytes())

    def frames(self) -> list[dict]:
        return worker_frames(self.frame_bytes())


def read_lines_then_close(fd: int, count: int, timeout: float = 60) -> bytes:
    """Reads `fd` until `count` whole lines arrived, closes it (this test's end of the pipe goes
    away: the writer's next write fails with EPIPE) and returns those lines; whatever came after
    them is dropped with the pipe."""
    data = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while data.count(b"\n") < count:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "the lines did not arrive in time"
            ready, _, _ = select.select([fd], [], [], remaining)
            if ready:
                chunk = os.read(fd, 1 << 16)
                assert chunk, "the channel ended before the lines arrived"
                data.extend(chunk)
    finally:
        os.close(fd)
    return b"".join(line + b"\n" for line in bytes(data).split(b"\n")[:count])


def _lines(data: bytes) -> list[bytes]:
    assert data == b"" or data.endswith(b"\n"), "a partial last line"
    return data.split(b"\n")[:-1] if data else []


def worker_frames(data: bytes) -> list[dict]:
    """Every stdout line strict JSON (UTF-8, no duplicate key, no NaN) and a worker frame
    (worker-frame.schema.json); nothing else is ever on stdout (R06)."""
    out = []
    for line in _lines(data):
        record = strict_json(line)
        problems = list(FRAME_VALIDATOR.iter_errors(record))
        assert not problems, (line[:300], problems[0].message)
        out.append(record)
    return out


def status_records(data: bytes) -> list[dict]:
    """Every fd 3 line strict JSON, within 65536 bytes, and a status record (NAT-15)."""
    out = []
    for line in _lines(data):
        assert len(line) <= 65536
        record = strict_json(line)
        problems = list(STATUS_VALIDATOR.iter_errors(record))
        assert not problems, (line, problems[0].message)
        out.append(record)
    return out


def stages(records: list[dict]) -> list[str]:
    """The status channel as a list: stage names, and `failure:<code>` for a failure record."""
    return [r["stage"] if r["type"] == "stage" else f"failure:{r['code']}" for r in records]


def check_failure_message(record: dict) -> None:
    """R37 and CR-R5-06: one line, at most 1024 UTF-8 bytes; the worker quotes no input, so its
    messages are ASCII."""
    message = record["message"]
    assert message and message.isascii() and "\n" not in message
    assert len(message.encode("utf-8")) <= 1024


def worker_args(endpoint: str, federation: str = FED, federate: str = OBSERVER) -> list[str]:
    return [f"--endpoint={endpoint}", f"--federation-name={federation}",
            f"--federate-name={federate}"]


# ============================================================================ the harness

def harness_argv(scenario: str, log: pathlib.Path, *rest: str) -> list[str]:
    return [str(harness()), f"--scenario={scenario}", f"--fom-dir={fom_dir()}", f"--log={log}",
            *rest]


def harness_worker(directory: pathlib.Path, scenario: str, log: pathlib.Path) -> pathlib.Path:
    """An executable `sc-hla-federate` for the host: it replaces itself with the harness playing
    `scenario`, passing on the host's own argument vector (`--version` or the three tokens)."""
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "sc-hla-federate"
    command = " ".join(shlex.quote(part) for part in harness_argv(scenario, log))
    shim.write_text(f'#!/bin/sh\nexec {command} "$@"\n', encoding="utf-8")
    shim.chmod(0o700)
    return shim


def log_entries(log: pathlib.Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def calls(log: pathlib.Path) -> list[dict]:
    """The decorator's call log: one entry per RTI call of the observer, in order."""
    return [e for e in log_entries(log) if "call" in e]


def call_names(log: pathlib.Path) -> list[str]:
    return [e["call"] for e in calls(log)]


def lifecycle_calls(federation: str = FED, federate: str = OBSERVER,
                    designator: str = "thread://") -> list[dict]:
    """What the decorator logs from connect to subscribe, written out from R10 and NAT-07."""
    return [
        {"call": "connect", "designator": designator, "model": "HLA_EVOKED"},
        {"call": "joinFederationExecution", "federate_name": federate,
         "federate_type": "SynapseCommandObserver", "federation": federation, "modules": 0},
        {"call": "getObjectClassHandle", "name": PE},
        {"call": "getAttributeHandle", "name": "EntityIdentifier"},
        {"call": "getAttributeHandle", "name": "EntityType"},
        {"call": "getAttributeHandle", "name": "Spatial"},
        {"call": "getAttributeHandle", "name": "ForceIdentifier"},
        {"active": True, "attributes": 4, "call": "subscribeObjectClassAttributes",
         "class": PE, "update_rate": ""},
    ]


CLOSE_CALLS = [{"action": "NO_ACTION", "call": "resignFederationExecution"},
               {"call": "disconnect"}]

#: What NAT-07 (b) lets the observer call; anything else aborts the harness.
ALLOWED_CALLS = {"connect", "joinFederationExecution", "getObjectClassHandle",
                 "getAttributeHandle", "getAttributeName", "subscribeObjectClassAttributes",
                 "requestAttributeValueUpdate", "evokeMultipleCallbacks",
                 "resignFederationExecution", "disconnect"}


def assert_only_allowed_calls(log: pathlib.Path) -> None:
    for entry in calls(log):
        assert entry["call"] in ALLOWED_CALLS and "forbidden" not in entry, entry
    for entry in calls(log):
        if entry["call"] == "evokeMultipleCallbacks" and "injected" not in entry:
            assert (entry["minimum"], entry["maximum"]) == (0.0, 0.05)


def call_trace(log: pathlib.Path) -> list[str]:
    """The decorator's log as call names, evoke calls left out, a fault the decorator injected
    (harness.cpp faults()) shown as `<call>!<what it threw>` after the call it failed."""
    return [c["call"] + (f"!{c['injected']}" if "injected" in c else "") for c in calls(log)
            if c["call"] != "evokeMultipleCallbacks" or "injected" in c]


# ============================================================================ events, written out

def discover_event(token: str, name: str) -> dict:
    return {"type": "discover", "object_token": token, "name": name, "reported_class": PE}


def reflect_event(token: str, attributes, *, tag: str = "", sent: str = "RECEIVE",
                  received: str = "RECEIVE", transport: str = "RELIABLE", time_=None,
                  retractable: bool = False) -> dict:
    return {"type": "reflect", "object_token": token,
            "attributes": [{"name": name, "hex": hex_} for name, hex_ in attributes],
            "tag_hex": tag, "sent_order": sent, "received_order": received,
            "transport": transport, "logical_time": time_, "retractable": retractable}


def remove_event(token: str, *, tag: str = "", received: str = "RECEIVE", time_=None,
                 retractable: bool = False) -> dict:
    return {"type": "remove", "object_token": token, "tag_hex": tag,
            "received_order": received, "logical_time": time_, "retractable": retractable}


def worker_diagnostic(code: str) -> tuple:
    """A worker's diagnostic frame as (type, code, token, attribute, severity): the message is
    not compared (R37: wording may vary)."""
    return ("diagnostic", code, None, None, "ERROR")


def event_key(event: dict):
    """An event, with a diagnostic reduced to its structured facts."""
    if event["type"] == "diagnostic":
        d = event["diagnostic"]
        return ("diagnostic", d["code"], event["object_token"], d["attribute"], d["severity"])
    return event


# ============================================================================ host sessions

class NativeSession:
    """One live session of the real host in this process, with a native executable as its
    worker: the host's own clock (CLOCK_MONOTONIC, the worker's), the audit time and the RSS
    reading fixed, and the reconnect wait recorded instead of slept (the seam clock: `sleeps`
    holds each delay the host asked for, in nanoseconds)."""

    def __init__(self, root: pathlib.Path, worker_path: pathlib.Path, *, config: dict | None = None,
                 **seams) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.out = root / "run"
        self.config = example_json("config-existing.json") if config is None else config
        self.environ = plain_environment(**{FOM_DIR_VARIABLE: fom_dir(),
                                            WORKER_VARIABLE: str(worker_path)})
        self.sleeps: list[int] = []
        self.pids: list[int] = []
        defaults = {"wall_clock_us": lambda: AUDIT_US, "rss_of": lambda _pid: SMALL_RSS,
                    "sleep": lambda duration, _wake: self.sleeps.append(duration)}
        defaults.update(seams)
        self.seams = dataclasses.replace(host.V1, **defaults)
        self.summary: dict | None = None

    def _on_worker(self, pid: int, running: bool) -> None:
        if running:
            self.pids.append(pid)

    def run(self, *, stop_when=None, during=None) -> "NativeSession":
        """`run_session`; with `stop_when`, a thread sends SIGINT to this process (the host's own
        orderly stop) once it returns true; `during` runs in that thread first."""
        done = threading.Event()

        def watch():
            if during is not None:
                during()
            deadline = time.monotonic() + 120
            while not done.is_set() and time.monotonic() < deadline:
                if stop_when():
                    os.kill(os.getpid(), signal.SIGINT)
                    return
                time.sleep(0.005)
        thread = threading.Thread(target=watch, daemon=True) if stop_when is not None else None
        previous = signal.signal(signal.SIGINT, lambda *_: None)
        try:
            if thread is not None:
                thread.start()
            self.summary = host.run_session(self.config, self.out, environ=self.environ,
                                            seams=self.seams, on_worker=self._on_worker)
        finally:
            done.set()
            if thread is not None:
                thread.join()
            signal.signal(signal.SIGINT, previous)
        return self

    def records(self) -> list[dict]:
        data = (self.out / "capture.jsonl").read_bytes()
        return [strict_json(line) for line in data.split(b"\n")[:-1]]

    def frames(self) -> list[dict]:
        return [r for r in self.records()[1:] if r["type"] == "frame"]

    def events(self, generation: int | None = None) -> list:
        """The captured events of the worker (generation_start and generation_end excluded,
        diagnostics as their facts), in capture order."""
        return [event_key(f["event"]) for f in self.frames()
                if f["event"]["type"] not in ("generation_start", "generation_end")
                and (generation is None or f["generation"] == generation)]

    def shape(self) -> list[tuple]:
        return capture_shape(self.records()[1:], elapsed=False)

    def observations(self) -> list[dict]:
        data = (self.out / "observations.jsonl").read_bytes()
        return [strict_json(line) for line in data.split(b"\n")[:-1]]

    def codes(self) -> list[str]:
        return [r["payload"]["code"] for r in self.observations() if r["kind"] == "diagnostic"]

    def check(self) -> dict:
        report = check_session(self.out, self.summary, self.pids, replay_root=self.root)
        for pid in self.pids:
            assert process_gone(pid), f"worker {pid} survived"
        return report


#: How long a session that should end by itself (a terminal condition) may run before the host is
#: asked to stop it anyway: a worker that wrongly went on then ends COMPLETE, and the test's
#: assertions fail instead of the run waiting for ever.
GIVE_UP_S = 60


def harness_session(tmp_path: pathlib.Path, scenario: str, *, stop: bool = True,
                    **seams) -> tuple[NativeSession, pathlib.Path]:
    """The scenario played by the harness as the host's worker; with `stop`, the host is asked
    for its orderly stop once the harness says it is ready (the scenario has been played);
    without it, only after GIVE_UP_S seconds."""
    log = tmp_path / "harness.log"
    shim = harness_worker(tmp_path / "bin", scenario, log)
    session = NativeSession(tmp_path, shim, **seams)
    if stop:
        def ready() -> bool:
            return any(e.get("event") == "ready" for e in log_entries(log))
    else:
        give_up = time.monotonic() + GIVE_UP_S

        def ready() -> bool:
            return time.monotonic() > give_up
    session.run(stop_when=ready)
    return session, log


def START(generation=1):
    return ("generation_start", generation, FED)


def END(generation, reason):
    return ("generation_end", generation, reason)


def DIAG(generation, code, token=None, attribute=None):
    return ("diagnostic", generation, code, token, attribute)


def FOOT(status, code, last_generation):
    return ("footer", status, code, last_generation)


#: OPS-02's classes of the codes a native session can end with, written out from the ruling.
CLASSES = {"E_CONFIG": 2, "E_CAPTURE_SCHEMA": 3, "E_RETRACTION_UNSUPPORTED": 3,
           "E_DEPENDENCY_PIN": 4, "E_FOM_PROFILE": 5, "E_FEDERATE_NAME": 5, "E_RTI_CONNECT": 5,
           "E_RTI_TIMEOUT": 5, "E_LIMIT": 6, "E_QUEUE_OVERFLOW": 6, "E_IO": 6}


def exit_class(summary: dict) -> int:
    """OPS-02's exit, from the session summary: the highest class among the terminal codes;
    else 3 when any E_ diagnostic was emitted; else 0."""
    classes = [CLASSES[code] for code in summary["terminal_codes"]]
    if classes:
        return max(classes)
    return 3 if summary["errors"] else 0


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ============================================================================ the worker's start

@case("G-R06")
def test_the_worker_prints_its_version_line_without_a_status_channel():
    """CR-R5-02: `sc-hla-federate --version` prints exactly the host's version line on stdout and
    exits 0, with fd 3 closed (the host's pre-flight gives it none) and nothing on fd 3 or
    stderr; the host's own pre-flight accepts it."""
    run = DirectRun([str(worker()), "--version"], status_pipe=False)
    assert run.wait() == EXIT_STOPPED
    assert run.frame_bytes() == VERSION_LINE
    assert run.stderr_bytes() == b""
    host.check_worker(str(worker()), plain_environment())


#: OPS-08, CR-R5-03: exactly `--version`, or exactly the three tokens in the host's order with
#: values the configuration schema admits; nothing else is read as anything.
REFUSED_ARGUMENTS = [
    [],
    ["--help"],
    ["--version", "--version"],
    ["--version", "--endpoint=rti://127.0.0.1:1"],
    ["--federation-name=F", "--endpoint=rti://127.0.0.1:1", "--federate-name=N"],
    ["--endpoint=rti://127.0.0.1:1", "--federation-name=F"],
    ["--endpoint=rti://127.0.0.1:1", "--federation-name=F", "--federate-name=N", "--extra"],
    ["--endpoint=--help", "--federation-name=F", "--federate-name=N"],
    ["--endpoint=rti://localhost:1", "--federation-name=F", "--federate-name=N"],
    ["--endpoint=rti://127.0.0.1:", "--federation-name=F", "--federate-name=N"],
    ["--endpoint=rti://127.0.0.1:1:2", "--federation-name=F", "--federate-name=N"],
    ["--endpoint=tcp://127.0.0.1:1", "--federation-name=F", "--federate-name=N"],
    ["--endpoint=rti://127.0.0.1:1", "--federation-name=", "--federate-name=N"],
    ["--endpoint=rti://127.0.0.1:1", "--federation-name=F G", "--federate-name=N"],
    ["--endpoint=rti://127.0.0.1:1", "--federation-name=F", "--federate-name=" + "N" * 65],
    ["--endpoint=rti://127.0.0.1:1", "--federation-name=F", "--federate-name=Né"],
    ["--endpoint rti://127.0.0.1:1", "--federation-name=F", "--federate-name=N"],
]


@case("G-R06")
@pytest.mark.parametrize("arguments", REFUSED_ARGUMENTS, ids=range(len(REFUSED_ARGUMENTS)))
def test_the_worker_refuses_any_other_argument_vector_before_anything_else(arguments):
    """R06 and OPS-08: the worker reads its parameters only from the host's argument tokens and
    refuses any vector that is not exactly theirs with its usage status (64), printing nothing
    on stdout and writing nothing on fd 3; with fd 3 a pipe and a listener on 127.0.0.1:1's
    place, no connection is attempted. On stderr: its one fixed usage line and nothing else,
    never the refused argument (CR-new-R7-15)."""
    listener = SilentListener()
    try:
        arguments = [a.replace("127.0.0.1:1", f"127.0.0.1:{listener.port}") for a in arguments]
        run = DirectRun([str(worker()), *arguments])
        assert run.wait() == EXIT_USAGE
        assert (run.frame_bytes(), run.status_bytes()) == (b"", b"")
        assert run.stderr_bytes() == USAGE_LINE
        assert listener.accepted == []
    finally:
        listener.close()


@case("G-R06", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("fd3", ["closed", "regular-file"])
def test_without_a_pipe_on_fd_3_the_worker_exits_70_before_any_rti_call(tmp_path, fd3):
    """NAT-09: the worker checks at start that fd 3 is open and a pipe, and otherwise exits with
    its own status (70) before any RTI call: the listener at the configured endpoint sees no
    connection, stdout stays empty, and a regular file on fd 3 stays empty. On stderr: its one
    fixed line (CR-new-R7-15)."""
    listener = SilentListener()
    try:
        target = tmp_path / "fd3"
        run = DirectRun([str(worker()), *worker_args(listener.endpoint)], status_pipe=False,
                        status_file=target if fd3 == "regular-file" else None)
        assert run.wait() == EXIT_STATUS_CHANNEL
        assert run.frame_bytes() == b""
        assert run.stderr_bytes() == STATUS_PIPE_LINE
        assert listener.accepted == []
        if fd3 == "regular-file":
            assert target.read_bytes() == b""
    finally:
        listener.close()


@case("G-R06", paragraphs=("SPEC:277",))
def test_the_openrti_debug_variables_never_reach_the_frame_channel(tmp_path):
    """NAV-01: the pinned OpenRTI writes its log to stdout when OPENRTI_DEBUG_PRIORITY asks for
    Info or more: rtinode, started here with it, prints its refusal of the join on its stdout
    (the control). The worker clears both variables first thing, so with both set in its own
    environment its stdout holds nothing but frames: the one diagnostic of that refused join.
    The RTI's exception for the refusal carries its own text, which the worker writes nowhere:
    stderr stays empty and the failure is the fixed message (CR-new-R7-15)."""
    node = Rtinode(tmp_path, debug=True)
    try:
        noisy = plain_environment(OPENRTI_DEBUG_PRIORITY="9", OPENRTI_DEBUG_CATEGORY="Assert")
        run = DirectRun([str(worker()), *worker_args(node.endpoint)], env=noisy)
        assert run.wait() == EXIT_FAILURE
        assert [event_key(f["event"]) for f in run.frames()] == [
            worker_diagnostic("E_RTI_CONNECT")]
        assert stages(run.status()) == ["connect", "running", "join", "running",
                                        "failure:E_RTI_CONNECT", "disconnect", "running"]
        assert run.stderr_bytes() == b""
        check_failure_message(run.status()[4])
    finally:
        node.stop()
    assert b"JoinFederationExecutionRequestMessage" in node.log.read_bytes()


# =============================================================== harness scenarios under the host

BYTES_EVENTS = [
    discover_event("o1", "bytes-object"),
    reflect_event("o1", [("EntityIdentifier", ENTITY_IDENTIFIER), ("Spatial", SPATIAL_PADDED)],
                  tag=EVERY_BYTE, transport="BEST_EFFORT"),
    reflect_event("o1", [("EntityType", EVERY_BYTE)], sent="TIMESTAMP"),
    reflect_event("o1", [("ForceIdentifier", "01")], tag="ff", sent="TIMESTAMP",
                  received="TIMESTAMP", time_=TIME_5),
    reflect_event("o1", [("EntityType", ENTITY_TYPE)], transport="BEST_EFFORT",
                  time_={"implementation": "Harness-Time", "hex": EVERY_BYTE}),
    remove_event("o1", tag="beef", received="TIMESTAMP", time_=TIME_7),
    discover_event("o2", "bytes-object-2"),
    remove_event("o2", tag="00"),
]


@case("G-R12", "G-R13", "G-R16", "G-R18", "G-R06",
      paragraphs=("SPEC:279", "SPEC:281", "SPEC:72", "SPEC:275", "SPEC:32"))
def test_every_byte_the_callbacks_supply_reaches_the_capture_unchanged(tmp_path):
    """R12, R13, R16, R18 (the carried clause 3: no structure cast, no packing, only the 4096-byte
    bound checked) and NAT-17, through every overload of the pinned headers:
    - the 4-argument discovery (the producing federate is not kept) and the 3-argument one, at
      PhysicalEntity, named by the qualified class name the observer resolved (NAT-04);
    - a reflection without a received order (RECEIVE, R13) whose tag holds every byte value and
      whose Spatial keeps its padding bytes a1..a7 and b1..b3, its two attributes sorted by name
      although the map gave Spatial first; the map and the tag of that callback are overwritten
      by the harness after it returned and before the batch ended, and the frame still holds
      what the callback was given (copied in the callback, R12);
    - an attribute value of every byte value (the worker does not judge content; the decoder
      refuses its length: E_ATTRIBUTE_LENGTH);
    - timestamped reflections with sent and received order as supplied, an HLAfloat64Time (5.0 is
      4014000000000000) and a time of the harness's own implementation whose 256 encoded bytes
      are every byte value, kept as name and opaque bytes (R13);
    - a timestamped removal (7.0, received TIMESTAMP) and a removal without time, whose sent order
      is not kept (NAT-17) and whose received order is RECEIVE.
    The session ends by the host's orderly stop: COMPLETE. Every frame is a worker frame under the
    schema, the capture verifies and replays to the live records (SPEC:32's verify_capture and
    replay), and generation_start precedes everything (SPEC:275); the decoded Spatial of the
    first snapshot keeps the padding in wire order (padding_hex, R18)."""
    session, log = harness_session(tmp_path, "bytes")
    report = session.check()
    assert report["status"] == "COMPLETE"
    assert session.shape()[0] == START() and session.shape()[-2:] == [END(1, "stop"),
                                                                      FOOT("COMPLETE", None, 1)]
    assert session.events() == BYTES_EVENTS
    assert session.summary["terminal_codes"] == [] and session.summary["workers"] == 1
    # RED-01, R22, RED-17, RED-02: W_FOM_UNVERIFIED for the existing federation's generation, the
    # decoder's refusal of the 256-byte EntityType, W_FORCE_UNMAPPED for force 1 under the empty
    # force map, W_TIME_UNRESOLVED once everything required is valid under time policy none; no
    # upsert (never eligible without time).
    assert session.codes() == ["W_FOM_UNVERIFIED", "E_ATTRIBUTE_LENGTH", "W_FORCE_UNMAPPED",
                               "W_TIME_UNRESOLVED"]
    kinds = [r["kind"] for r in session.observations()]
    assert kinds.count("upsert") == 0 and kinds.count("removed") == 2
    spatial = next(r for r in session.observations() if r["kind"] == "snapshot")
    assert spatial["payload"]["attributes"]["Spatial"]["hex"] == SPATIAL_PADDED
    assert spatial["payload"]["attributes"]["Spatial"]["value"]["padding_hex"] == \
        "a1a2a3a4a5a6a7b1b2b3"
    assert session.frames()[0]["elapsed_ns"] == "0"
    entries = log_entries(log)
    assert [e["event"] for e in entries if "event" in e] == ["start", "ready", "exit"]
    assert calls(log) == lifecycle_calls() + [
        {"attributes": 4, "call": "requestAttributeValueUpdate",
         "outcome": "ObjectInstanceNotKnown", "tag_bytes": 0},
        {"attributes": 4, "call": "requestAttributeValueUpdate",
         "outcome": "ObjectInstanceNotKnown", "tag_bytes": 0},
    ] + [c for c in calls(log) if c["call"] == "evokeMultipleCallbacks"] + CLOSE_CALLS
    assert_only_allowed_calls(log)


#: Every scenario that ends in a terminal condition of the worker: its code (OPS-30), the
#: request_update/running pairs on fd 3 before the failure record (lookups and requests of
#: NAT-15), and the events captured before it, written out from harness.cpp's stimuli.
TERMINAL = {
    "limit-value": ("E_LIMIT", 1, [
        discover_event("o1", "limit-object"),
        reflect_event("o1", [("EntityIdentifier", "5a" * 4096)])]),
    "limit-tag-reflect": ("E_LIMIT", 1, [
        discover_event("o1", "limit-object"),
        reflect_event("o1", [("ForceIdentifier", "01")], tag="7e" * 4096)]),
    "limit-tag-remove": ("E_LIMIT", 1, [
        discover_event("o1", "limit-object"), remove_event("o1", tag="7e" * 4096)]),
    "limit-time": ("E_LIMIT", 1, [
        discover_event("o1", "limit-object"),
        reflect_event("o1", [("ForceIdentifier", "01")], sent="TIMESTAMP", received="TIMESTAMP",
                      time_={"implementation": "Harness-Time", "hex": "11" * 256})]),
    "limit-name": ("E_LIMIT", 1, [discover_event("o1", "é" * 512)]),
    "limit-attributes": ("E_LIMIT", 0, [discover_event("o1", "limit-object")]),
    "retraction-request": ("E_RETRACTION_UNSUPPORTED", 0, [
        discover_event("o1", "retract-object")]),
    "name-surrogate": ("E_CAPTURE_SCHEMA", 1, [discover_event("o1", "valid-name")]),
    "name-beyond": ("E_CAPTURE_SCHEMA", 0, []),
    "attribute-name-refused": ("E_CAPTURE_SCHEMA", 1, [discover_event("o1", "named-object")]),
    "attribute-name-long": ("E_CAPTURE_SCHEMA", 1, [
        discover_event("o1", "named-object"), reflect_event("o1", [("ForceIdentifier", "01")])]),
    "attribute-name-invalid": ("E_CAPTURE_SCHEMA", 1, [
        discover_event("o1", "named-object"), reflect_event("o1", [("ForceIdentifier", "01")])]),
    "attribute-name-collision": ("E_CAPTURE_SCHEMA", 1, [
        discover_event("o1", "named-object"), reflect_event("o1", [("ForceIdentifier", "01")])]),
    "time-name-long": ("E_CAPTURE_SCHEMA", 1, [
        discover_event("o1", "timed-object"),
        reflect_event("o1", [("ForceIdentifier", "01")], sent="TIMESTAMP", received="TIMESTAMP",
                      time_={"implementation": "T" * 128, "hex": "0102"})]),
    "time-name-invalid": ("E_CAPTURE_SCHEMA", 0, [discover_event("o1", "timed-object")]),
    "class-other": ("E_CAPTURE_SCHEMA", 0, []),
    "order-invalid": ("E_CAPTURE_SCHEMA", 0, [discover_event("o1", "ordered-object")]),
    "connection-lost": ("E_RTI_CONNECT", 0, [discover_event("o1", "lost-object")]),
    "missing-name": ("E_FOM_PROFILE", None, []),
    # CR-new-R7-06: one callback with two faults; the check that comes first decides the code.
    # Reflect: the attribute count before the enumerations; every size (value, tag, the encoded
    # time) before the time's implementation name and the enumerations. Discover: the class
    # before the name's size. Remove: the tag before the received order.
    "precedence-count-order": ("E_LIMIT", 0, [discover_event("o1", "precedence-object")]),
    "precedence-value-time-name": ("E_LIMIT", 0, [discover_event("o1", "precedence-object")]),
    "precedence-tag-transport": ("E_LIMIT", 0, [discover_event("o1", "precedence-object")]),
    "precedence-time-length-name": ("E_LIMIT", 0, [discover_event("o1", "precedence-object")]),
    "precedence-class-name": ("E_CAPTURE_SCHEMA", 0, []),
    "precedence-remove-tag-order": ("E_LIMIT", 0, [discover_event("o1", "precedence-object")]),
    # CR-new-R7-13: a naming fault (an unknown attribute named with 129 bytes after the evoke
    # call) in a record before the callback that raised E_LIMIT is the condition reported: the
    # discover before it is written, nothing after; the other order is E_LIMIT, and the
    # reflection after it is never captured, so its name is never looked up (no lookup pair).
    "naming-then-limit": ("E_CAPTURE_SCHEMA", 1, [discover_event("o1", "named-object")]),
    "limit-then-naming": ("E_LIMIT", 0, [discover_event("o1", "named-object")]),
    # CR-new-R7-08: a transportation type, a reflection's received order and a removal's received
    # order outside the HLA enumerations.
    "transport-invalid": ("E_CAPTURE_SCHEMA", 0, [discover_event("o1", "ordered-object")]),
    "received-order-invalid": ("E_CAPTURE_SCHEMA", 0, [discover_event("o1", "ordered-object")]),
    "remove-order-invalid": ("E_CAPTURE_SCHEMA", 0, [discover_event("o1", "ordered-object")]),
    # CR-new-R7-07: a logical time that cannot encode itself (encode refuses, or writes one byte
    # fewer than it announced).
    "time-encode-refused": ("E_CAPTURE_SCHEMA", 1, [discover_event("o1", "timed-object")]),
    "time-encode-short": ("E_CAPTURE_SCHEMA", 1, [discover_event("o1", "timed-object")]),
    # CR-new-R7-10: an exception escaping the callback's own code (thrown by the logical time it
    # was given): std::bad_alloc is E_LIMIT, anything else E_CAPTURE_SCHEMA.
    "callback-no-memory": ("E_LIMIT", 1, [discover_event("o1", "timed-object")]),
    "callback-other-exception": ("E_CAPTURE_SCHEMA", 1, [discover_event("o1", "timed-object")]),
}

#: NAT-08 with CR-R5-01: the generation_end reason the host derives from the code.
REASON = {"E_LIMIT": "limit", "E_CAPTURE_SCHEMA": "failure", "E_FOM_PROFILE": "failure",
          "E_RETRACTION_UNSUPPORTED": "retraction", "E_RTI_CONNECT": "connection_lost"}


def direct_harness(tmp_path: pathlib.Path, scenario: str, *, stop_when_ready: bool = False,
                   read_frames: bool = True, read_status: bool = True,
                   env: dict | None = None) -> DirectRun:
    log = tmp_path / f"{scenario}.log"
    extra = ["--stop-when-ready"] if stop_when_ready else []
    return DirectRun(harness_argv(scenario, log, *extra, *worker_args("rti://127.0.0.1:1")),
                     read_frames=read_frames, read_status=read_status, env=env)


@case("G-R06", "G-R41", "G-R16", paragraphs=("SPEC:277", "SPEC:275"))
@pytest.mark.parametrize("scenario", sorted(TERMINAL))
def test_a_terminal_condition_is_one_failure_record_then_resign_and_disconnect(tmp_path,
                                                                                scenario):
    """NAT-08, NAT-15, CR-R5-06, OPS-30 on the worker's own channels: the stage records of the
    lifecycle in NAT-15's order (generation_start written after join's running), then exactly one
    failure record with the condition's code and a message of at most 1024 bytes, then resign and
    disconnect, each answered by running; the worker exits 1 by itself. On stdout: the frames
    accepted before the condition in callback order, then the same code as a diagnostic frame
    with no token and no attribute (the queue had room). A condition before the generation's
    first record leaves nothing but generation_start and the diagnostic."""
    code, pairs, events = TERMINAL[scenario]
    run = direct_harness(tmp_path, scenario)
    assert run.wait() == EXIT_FAILURE
    records = run.status()
    expected = ["connect", "running", "join", "running", "resolve", "running"]
    expected += ["request_update", "running"] * (pairs or 0)
    expected += [f"failure:{code}", "resign", "running", "disconnect", "running"]
    assert stages(records) == expected
    failures = [r for r in records if r["type"] == "failure"]
    assert len(failures) == 1
    check_failure_message(failures[0])
    frames = run.frames()
    assert frames[0]["event"] == {"type": "generation_start", "federation_name": FED}
    assert [event_key(f["event"]) for f in frames[1:]] == events + [worker_diagnostic(code)]
    assert frames[-1]["event"]["diagnostic"]["message"] == failures[0]["message"]
    stamps = [int(f["monotonic_ns"]) for f in frames]
    assert stamps == sorted(stamps)
    # CR-new-R7-15: nothing on stderr, and no text the RTI or the callback's arguments carried
    # (connectionLost's description, the logical time's exception) anywhere.
    assert run.stderr_bytes() == b""
    for text in (b"dropped the connection", b"injected"):
        assert text not in run.frame_bytes() + run.status_bytes()


@case("G-R06", "G-R41", "G-R12", paragraphs=("SPEC:277", "SPEC:56"))
@pytest.mark.parametrize("scenario", sorted(TERMINAL))
def test_a_terminal_condition_ends_the_hosts_session_with_its_code(tmp_path, scenario):
    """The same scenarios as the host's worker: one diagnostic frame per condition (the worker's
    copy, NAT-08), generation_end with the reason the code gives (E_LIMIT limit, E_CAPTURE_SCHEMA
    and E_FOM_PROFILE failure, E_RETRACTION_UNSUPPORTED retraction, E_RTI_CONNECT
    connection_lost), and the footer: FAILED with the code, except a requestRetraction, which
    ends COMPLETE (CR-R5-01). Nothing is retried but E_RTI_CONNECT (SPEC:62), whose next worker
    plays nothing and is stopped in order. The capture verifies and replays to the live
    records; the exit class follows OPS-02."""
    code, _pairs, events = TERMINAL[scenario]
    session, _log = harness_session(tmp_path, scenario, stop=scenario == "connection-lost")
    session.check()
    shape = session.shape()
    assert shape[0] == START(1)
    assert session.events(generation=1) == events + [worker_diagnostic(code)]
    if scenario == "connection-lost":
        assert shape[-5:] == [DIAG(1, code), END(1, "connection_lost"), START(2), END(2, "stop"),
                              FOOT("COMPLETE", None, 2)]
        assert session.sleeps == [1 * SECOND] and session.summary["workers"] == 2
        assert session.summary["terminal_codes"] == []
        assert exit_class(session.summary) == 3
        return
    assert session.summary["workers"] == 1 and session.sleeps == []
    if code == "E_RETRACTION_UNSUPPORTED":
        assert shape[-3:] == [DIAG(1, code), END(1, "retraction"), FOOT("COMPLETE", None, 1)]
        assert session.summary["terminal_codes"] == [] and exit_class(session.summary) == 3
    else:
        assert shape[-3:] == [DIAG(1, code), END(1, REASON[code]), FOOT("FAILED", code, 1)]
        assert session.summary["terminal_codes"] == [code]
        assert exit_class(session.summary) == CLASSES[code]


@case("G-R15", "G-R07", paragraphs=("SPEC:289",))
@pytest.mark.parametrize("scenario", ["name-surrogate", "name-beyond", "attribute-name-invalid",
                                      "time-name-invalid"])
def test_a_wide_string_no_utf8_can_carry_ends_the_session_with_e_capture_schema(tmp_path,
                                                                                scenario):
    """The carried G-R15 clause (SPEC:289): a wide string from the RTI that cannot convert to
    valid UTF-8 (an object name with U+D800 or a unit beyond U+10FFFF, an attribute name with a
    surrogate, a logical time's implementation name with U+DFFF) is never replaced by something
    the RTI did not send: the worker ends the session with E_CAPTURE_SCHEMA, nothing of that
    callback captured, and the host ends FAILED E_CAPTURE_SCHEMA with generation_end failure.
    The byte counting of SPEC:289 is test_a_terminal_condition_*[limit-name] (512 two-byte
    letters are 1024 bytes and pass; one more byte does not)."""
    session, _log = harness_session(tmp_path / "host", scenario, stop=False)
    session.check()
    assert session.shape()[-3:] == [DIAG(1, "E_CAPTURE_SCHEMA"), END(1, "failure"),
                                    FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)]
    assert session.events()[:-1] == TERMINAL[scenario][2]
    for frame in session.frames():
        assert "\\ufffd" not in json.dumps(frame["event"])
    # The worker itself refused the string (the host did not have to refuse a malformed line):
    # its stdout is strict UTF-8 JSON throughout, and the condition is its own failure record.
    run = direct_harness(tmp_path, scenario, stop_when_ready=True)
    assert run.wait() == EXIT_FAILURE
    run.frames()
    assert [r["code"] for r in run.status() if r["type"] == "failure"] == ["E_CAPTURE_SCHEMA"]


@case("A-ATTRIBUTE-LIMIT", "G-R41", "G-R18", paragraphs=("SPEC:277",))
def test_a_4096_byte_value_is_captured_and_a_4097_byte_value_is_never_copied(tmp_path):
    """A-ATTRIBUTE-LIMIT: the 4096-byte EntityIdentifier is captured as it came (the worker checks
    nothing but the bound; the decoder then refuses the length: E_ATTRIBUTE_LENGTH, the attribute
    INVALID with the frame's bytes); the 4097-byte one is refused before it is copied: no frame
    holds it, the session ends E_LIMIT (OPS-22: session FAILED), generation_end limit."""
    session, _log = harness_session(tmp_path, "limit-value", stop=False)
    session.check()
    assert session.shape() == [START(1), ("discover", 1, "o1"), ("reflect", 1, "o1"),
                               DIAG(1, "E_LIMIT"), END(1, "limit"), FOOT("FAILED", "E_LIMIT", 1)]
    reflect = session.frames()[2]["event"]
    assert reflect["attributes"] == [{"name": "EntityIdentifier", "hex": "5a" * 4096}]
    assert all(len(json.dumps(f)) < 20000 for f in session.frames())
    assert session.codes() == ["W_FOM_UNVERIFIED", "E_ATTRIBUTE_LENGTH", "E_LIMIT"]
    snapshot = [r for r in session.observations() if r["kind"] == "snapshot"][-1]
    entity_identifier = snapshot["payload"]["attributes"]["EntityIdentifier"]
    assert (entity_identifier["status"], entity_identifier["hex"]) == ("INVALID", "5a" * 4096)
    assert exit_class(session.summary) == 6


@case("A-TAG-LIMIT", "G-R41", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("scenario,kind", [("limit-tag-reflect", "reflect"),
                                           ("limit-tag-remove", "remove")])
def test_a_4096_byte_tag_is_captured_and_a_4097_byte_tag_ends_the_session(tmp_path, scenario,
                                                                           kind):
    """A-TAG-LIMIT on both callbacks that carry a tag: the boundary tag (4096 bytes of 7e) is
    captured whole, the next one (4097) is E_LIMIT and is not captured; FAILED E_LIMIT."""
    session, _log = harness_session(tmp_path, scenario, stop=False)
    session.check()
    assert session.shape() == [START(1), ("discover", 1, "o1"), (kind, 1, "o1"),
                               DIAG(1, "E_LIMIT"), END(1, "limit"), FOOT("FAILED", "E_LIMIT", 1)]
    assert session.frames()[2]["event"]["tag_hex"] == "7e" * 4096
    assert session.summary["terminal_codes"] == ["E_LIMIT"]


@case("A-UNSUBSCRIBED", "G-R12", "G-R02", "G-R41", paragraphs=("SPEC:283", "SPEC:56"))
def test_an_unsubscribed_attribute_is_captured_under_its_name_and_rejects_the_reflection(
        tmp_path):
    """A-UNSUBSCRIBED, the native half (NAT-06, OPS-05), and R02's "unknown extensions are not
    silently decoded": an attribute handle the observer did not subscribe to (DamageState, a
    real handle of the five-module federation) beside EntityIdentifier is captured, named after
    the evoke call by getAttributeName at PhysicalEntity, sorted by name; the reducer rejects the
    whole reflection (E_UNSUBSCRIBED_ATTRIBUTE for DamageState; EntityIdentifier INVALID with the
    frame's bytes; changed_attributes the known names only, SPEC:283). Four supplied attributes
    with one unknown among them are captured too (more than four would not be, NAT-06 (1)). The
    second lookup of the same handle is answered from the worker's cache: one getAttributeName
    in the call log. The session ends COMPLETE by the orderly stop."""
    session, log = harness_session(tmp_path, "unsubscribed")
    session.check()
    assert session.events() == [
        discover_event("o1", "unsubscribed-object"),
        reflect_event("o1", [("DamageState", "00000001"), ("EntityIdentifier", ENTITY_IDENTIFIER)]),
        reflect_event("o1", [("DamageState", "00000002"), ("EntityType", ENTITY_TYPE),
                             ("ForceIdentifier", "01"), ("Spatial", SPATIAL_PADDED)]),
    ]
    assert session.shape()[-2:] == [END(1, "stop"), FOOT("COMPLETE", None, 1)]
    unsubscribed = [r["payload"] for r in session.observations() if r["kind"] == "diagnostic"
                    and r["payload"]["code"] == "E_UNSUBSCRIBED_ATTRIBUTE"]
    assert [(d["attribute"], d["object_token"], d["seq"]) for d in unsubscribed] == [
        ("DamageState", "o1", 3), ("DamageState", "o1", 4)]
    first = [r for r in session.observations() if r["kind"] == "snapshot"][0]["payload"]
    assert first["changed_attributes"] == ["EntityIdentifier"]
    assert "DamageState" not in first["attributes"]
    assert (first["attributes"]["EntityIdentifier"]["status"],
            first["attributes"]["EntityIdentifier"]["hex"],
            first["attributes"]["EntityIdentifier"]["value"]) == (
        "INVALID", ENTITY_IDENTIFIER, None)
    assert [r["kind"] for r in session.observations()].count("upsert") == 0
    lookups = [c for c in calls(log) if c["call"] == "getAttributeName"]
    assert lookups == [{"call": "getAttributeName", "name": "DamageState",
                        "outcome": "forwarded"}]
    assert_only_allowed_calls(log)


@case("A-UNSUBSCRIBED", "G-R12", "G-R41", paragraphs=("SPEC:56",))
def test_more_than_four_supplied_attributes_end_the_session_with_nothing_copied(tmp_path):
    """NAT-06 (1), OPS-22: the count first; five supplied attributes (the four and DamageState)
    are E_LIMIT, no reflect frame is written and no name is looked up; FAILED E_LIMIT."""
    session, log = harness_session(tmp_path, "limit-attributes", stop=False)
    session.check()
    assert session.shape() == [START(1), ("discover", 1, "o1"), DIAG(1, "E_LIMIT"),
                               END(1, "limit"), FOOT("FAILED", "E_LIMIT", 1)]
    assert "getAttributeName" not in call_names(log)


@case("A-RETRACT", "G-R13", paragraphs=("SPEC:281",))
def test_both_retraction_handle_overloads_are_captured_retractable_and_quarantine(tmp_path):
    """A-RETRACT, the native half (R13, OPS-05, NAT-07): the reflection and the removal that
    carry a MessageRetractionHandle are captured with retractable true, their logical times and
    orders kept; the reducer emits E_RETRACTION_UNSUPPORTED for each and quarantines the object
    without applying the reflection (ForceIdentifier stays ABSENT) and without deleting it (no
    removed record; SPEC:281). The session goes on and ends COMPLETE by the orderly stop."""
    session, _log = harness_session(tmp_path, "retract")
    session.check()
    assert session.events() == [
        discover_event("o1", "retract-object"),
        reflect_event("o1", [("ForceIdentifier", "01")], sent="TIMESTAMP", received="TIMESTAMP",
                      transport="BEST_EFFORT", time_={"implementation": "HLAfloat64Time",
                                                      "hex": "3ff8000000000000"},
                      retractable=True),
        remove_event("o1", received="TIMESTAMP", retractable=True,
                     time_={"implementation": "HLAfloat64Time", "hex": "4004000000000000"}),
    ]
    assert session.shape()[-2:] == [END(1, "stop"), FOOT("COMPLETE", None, 1)]
    assert session.codes() == ["W_FOM_UNVERIFIED", "E_RETRACTION_UNSUPPORTED",
                               "E_RETRACTION_UNSUPPORTED"]
    kinds = [r["kind"] for r in session.observations()]
    assert "removed" not in kinds
    snapshot = [r for r in session.observations() if r["kind"] == "snapshot"][-1]["payload"]
    assert snapshot["lifecycle"] == "QUARANTINED"
    assert snapshot["attributes"]["ForceIdentifier"]["status"] == "ABSENT"


@case("A-RETRACT", "G-R13", paragraphs=("SPEC:281",))
def test_request_retraction_ends_the_generation_with_reason_retraction(tmp_path):
    """A-RETRACT, requestRetraction (R13, SPEC:281, CR-R5-01): it has no object mapping; the
    worker reports E_RETRACTION_UNSUPPORTED (no token, no attribute) on fd 3 and as a frame,
    resigns, disconnects and exits by itself; the host ends the generation with reason
    retraction, does not reconnect, and the footer is COMPLETE; the exit is 3 (an E_
    diagnostic)."""
    session, log = harness_session(tmp_path, "retraction-request", stop=False)
    session.check()
    assert session.shape() == [START(1), ("discover", 1, "o1"),
                               DIAG(1, "E_RETRACTION_UNSUPPORTED"), END(1, "retraction"),
                               FOOT("COMPLETE", None, 1)]
    assert session.summary["terminal_codes"] == [] and exit_class(session.summary) == 3
    assert calls(log)[-2:] == CLOSE_CALLS


@case("A-EMPTY", "G-R12", paragraphs=("SPEC:279",))
def test_an_empty_map_is_a_captured_empty_reflection_with_no_state_output(tmp_path):
    """A-EMPTY, the native half (SPEC:279, OPS-05): an empty attribute map is captured as a
    reflection with no attributes; the reducer emits nothing for it (no snapshot, no upsert, no
    diagnostic beyond the generation's W_FOM_UNVERIFIED)."""
    session, _log = harness_session(tmp_path, "empty")
    session.check()
    assert session.events() == [discover_event("o1", "empty-object"), reflect_event("o1", [])]
    assert [(r["kind"], r["seq"]) for r in session.observations()] == [("diagnostic", 1)]


@case("G-R25", "G-R12", "G-R10", paragraphs=("SPEC:291", "SPEC:56", "SPEC:50"))
def test_a_handle_keeps_its_token_after_removal_and_a_new_discovery_is_a_new_object(tmp_path):
    """NAT-11 and the carried G-R25 clause, with the reducer's half (RED-13): handle 1 is
    discovered (o1), removed, then reflected and removed again under its retired token (the
    reducer: E_UNKNOWN_OBJECT, then W_DUPLICATE_REMOVE); discovered again it is a new object with
    the next token (o2), and the same discovery repeated keeps o2 (W_DUPLICATE_DISCOVERY); a
    reflection of handle 2, never discovered, takes the next token (o3, E_UNKNOWN_OBJECT), and
    its later discovery is a new object again (o4). Tokens follow handle equality, never a
    handle's number (R10): nothing in the capture is a handle value."""
    session, log = harness_session(tmp_path, "reuse")
    session.check()
    assert session.events() == [
        discover_event("o1", "first-life"),
        remove_event("o1"),
        reflect_event("o1", [("ForceIdentifier", "01")]),
        remove_event("o1"),
        discover_event("o2", "second-life"),
        discover_event("o2", "second-life"),
        remove_event("o2"),
        reflect_event("o3", [("ForceIdentifier", "02")]),
        discover_event("o4", "late-discovery"),
    ]
    assert session.codes() == ["W_FOM_UNVERIFIED", "E_UNKNOWN_OBJECT", "W_DUPLICATE_REMOVE",
                               "W_DUPLICATE_DISCOVERY", "E_UNKNOWN_OBJECT"]
    assert [c["outcome"] for c in calls(log) if c["call"] == "requestAttributeValueUpdate"] == [
        "ObjectInstanceNotKnown"] * 3
    assert session.shape()[-2:] == [END(1, "stop"), FOOT("COMPLETE", None, 1)]


@case("G-R12", paragraphs=("SPEC:56", "SPEC:291"))
def test_each_new_object_is_asked_for_its_values_once_after_the_callbacks(tmp_path):
    """R12 and NAV-04: after the batch's callbacks returned, one requestAttributeValueUpdate per
    object newly discovered in it (the four attributes, an empty tag), none for a repeated
    discovery; an object removed in the same batch makes the RTI answer ObjectInstanceNotKnown,
    which is no failure (the handles of this scenario are unknown to the RTI, so both requests
    are answered so). The session ends COMPLETE."""
    session, log = harness_session(tmp_path, "requests")
    session.check()
    assert session.events() == [discover_event("o1", "requested-1"),
                                discover_event("o2", "requested-2"), remove_event("o2"),
                                discover_event("o1", "requested-1")]
    requests = [c for c in calls(log) if c["call"] == "requestAttributeValueUpdate"]
    assert requests == [{"attributes": 4, "call": "requestAttributeValueUpdate",
                         "outcome": "ObjectInstanceNotKnown", "tag_bytes": 0}] * 2
    assert session.summary["status"] == "COMPLETE" and session.summary["terminal_codes"] == []


@case("G-R12", paragraphs=("SPEC:56",))
def test_object_names_are_data_and_reach_the_capture_exactly(tmp_path):
    """Names are data (R40): control characters, a quotation mark, a reverse solidus, DEL, an
    accented letter, a character beyond the BMP and a line feed reach the frame exactly, as JSON
    escapes where JSON needs them; the line stays one line."""
    session, _log = harness_session(tmp_path, "name-text")
    session.check()
    assert session.events() == [
        discover_event("o1", "a\u0001\u001f\"q\\\u007fé\U0001F600\n")]


@case("A-UNSUBSCRIBED", "G-R12", paragraphs=("SPEC:56",))
def test_an_attribute_name_of_128_utf8_bytes_is_kept(tmp_path):
    """NAT-06 (2): an unknown attribute's name of exactly 128 UTF-8 bytes (64 two-byte letters,
    given by the decorator in place of DamageState's) is captured under that name; 129 bytes
    (attribute-name-long in TERMINAL) is E_CAPTURE_SCHEMA."""
    session, _log = harness_session(tmp_path, "attribute-name-128")
    session.check()
    assert session.events()[-1] == reflect_event("o1", [("é" * 64, "01")])


@case("G-R12", paragraphs=("SPEC:291",))
def test_a_changed_rediscovery_keeps_its_token_and_is_the_reducers_fatal_fault(tmp_path):
    """NAT-11, SPEC:291: a still-active handle discovered again under another name keeps its
    token; the reducer judges the changed metadata: E_CAPTURE_SCHEMA, the generation stops
    (CR-R4-03), FAILED. The worker reports nothing itself (its diagnostic would be RED-01's
    derived code)."""
    session, _log = harness_session(tmp_path, "rediscover-changed", stop=False)
    session.check()
    assert session.events() == [discover_event("o1", "first-name"),
                                discover_event("o1", "second-name")]
    assert session.shape()[-2:] == [END(1, "failure"), FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)]
    assert session.codes() == ["W_FOM_UNVERIFIED", "E_CAPTURE_SCHEMA"]


@case("G-R02", "G-R10", "G-R13", "G-R14", "G-R07", "G-R16",
      paragraphs=("SPEC:8", "SPEC:50", "SPEC:281", "SPEC:62", "SPEC:38", "SPEC:72"))
def test_the_observer_calls_only_what_a_receive_only_federate_may(tmp_path):
    """A-NO-PUBLISH's native half (NAT-07 b; the real-RTI half is round R8's case), R02, R10,
    R13 and the carried G-R07 and G-R14 clauses, through the recording decorator around the
    observer's RTIambassador for a whole session under the host: connect with HLA_EVOKED and the
    designator (thread:// in the harness); join by name with federate type
    SynapseCommandObserver and no FOM module (never the local FOM, never a create); the class
    PhysicalEntity and its four attributes by name, then one active subscription of exactly those
    four, without regions or a rate; evokeMultipleCallbacks(0.0, 0.05) only (R12, NAT-05); and,
    on the host's orderly stop (SIGTERM), resign with NO_ACTION and disconnect, the worker
    exiting 0 by itself (COMPLETE). No publication, update, interaction, ownership, time
    management, DDM, save/restore, create or destroy call: the decorator aborts on any of them
    (test_the_decorator_aborts_on_a_call_the_observer_must_never_make), and on a call made inside
    a callback (R12)."""
    session, log = harness_session(tmp_path, "idle")
    session.check()
    assert session.shape() == [START(1), END(1, "stop"), FOOT("COMPLETE", None, 1)]
    observed = calls(log)
    evokes = [c for c in observed if c["call"] == "evokeMultipleCallbacks"]
    assert observed == lifecycle_calls() + evokes + CLOSE_CALLS
    assert sum(c["count"] for c in evokes) >= 1
    assert_only_allowed_calls(log)
    assert [e["event"] for e in log_entries(log) if "event" in e][-1] == "exit"
    assert log_entries(log)[-1] == {"event": "exit", "status": EXIT_STOPPED}


@case("G-R02", paragraphs=("SPEC:8",))
@pytest.mark.parametrize("scenario,call", [("decorator-forbidden", "publishObjectClassAttributes"),
                                           ("decorator-arguments", "resignFederationExecution")])
def test_the_decorator_aborts_on_a_call_the_observer_must_never_make(tmp_path, scenario, call):
    """The decorator is not vacuous: a publication (a service the observer never calls), and an
    allowed service with arguments the observer never uses (resign with DELETE_OBJECTS), are
    logged as forbidden and abort the process (SIGABRT)."""
    run = direct_harness(tmp_path, scenario)
    assert run.wait() == -signal.SIGABRT
    log = tmp_path / f"{scenario}.log"
    assert calls(log)[-1] == {"call": call, "forbidden": True}


@case("G-R12", "G-R13", "G-R10", paragraphs=("SPEC:56", "SPEC:281", "SPEC:50"))
def test_the_rti_itself_delivers_into_the_observer_inside_the_harness(tmp_path):
    """The RTI's own callbacks (in the harness process, thread://): the setup federate publishes
    the four attributes at PhysicalEntity and registers an object; the worker's event loop
    receives the discovery (the 3-argument overload, at PhysicalEntity, the RTI's own name
    HLAobjectInstance<n>), asks for the object's values after the callback returned, and the
    setup federate is asked for exactly the four attributes with an empty tag (R12); its update
    arrives receive ordered and best effort (the RPR FOM's declarations, NAT-16, R13), its deletion
    as a removal with the tag it sent. The session ends COMPLETE."""
    session, log = harness_session(tmp_path, "live")
    session.check()
    events = session.events()
    assert len(events) == 3
    assert events[0]["type"] == "discover" and events[0]["object_token"] == "o1"
    assert events[0]["reported_class"] == PE
    assert events[0]["name"].startswith("HLAobjectInstance")
    assert events[1:] == [
        reflect_event("o1", [("EntityIdentifier", ENTITY_IDENTIFIER), ("EntityType", ENTITY_TYPE),
                             ("ForceIdentifier", "01")], tag="cafe", transport="BEST_EFFORT"),
        remove_event("o1", tag="beef"),
    ]
    provided = [e for e in log_entries(log) if e.get("setup") == "provideAttributeValueUpdate"]
    assert provided == [{"attributes": 4, "setup": "provideAttributeValueUpdate",
                         "tag_bytes": 0}]
    assert [c["outcome"] for c in calls(log) if c["call"] == "requestAttributeValueUpdate"] == [
        "forwarded"]
    assert_only_allowed_calls(log)


# ============================================================================ the queue (R41)

def _numbered(events: list, token: str, attributes) -> int:
    """How many reflections `events` holds, after checking that they are the scenario's numbered
    reflections 0, 1, 2 ... in order, each with its number as a 4-byte big-endian tag: an
    unbroken run from the first, nothing skipped, reordered or evicted."""
    for number, event in enumerate(events):
        assert event == reflect_event(token, attributes, tag=f"{number:08x}"), (number, event)
    return len(events)


@case("A-OVERFLOW", "G-R41", paragraphs=("SPEC:277", "SPEC:279"))
@pytest.mark.parametrize("scenario,kept,attributes", [
    # 4096 frames: the discover and 4095 reflections; the 4096th reflection (number 4095) is
    # refused.
    ("overflow-count", 4095, [("ForceIdentifier", "01")]),
    # 16 MiB = 16777216 bytes: 1 (the discover's name "b") + 1023 * 16388 (four 4096-byte values
    # and a 4-byte tag) = 16764925 fit; one more reflection (16781313) does not. 1024 frames, far
    # below the frame bound, and 12291 bytes left: room a diagnostic frame would have had.
    ("overflow-bytes", 1023, [("EntityIdentifier", "01" * 4096), ("EntityType", "02" * 4096),
                              ("ForceIdentifier", "03" * 4096), ("Spatial", "04" * 4096)]),
], ids=["frames", "bytes"])
def test_a_batch_beyond_the_queue_bound_overflows_keeping_everything_accepted(tmp_path, scenario,
                                                                               kept, attributes):
    """A-OVERFLOW (R41, NAT-06): one evoke batch of more records than the queue may hold (counted
    as the callbacks append them, before anything is copied into the batch). The records that fit
    are all written, in callback order, nothing dropped, sampled or evicted; the first that does
    not fit is refused and the worker reports E_QUEUE_OVERFLOW on fd 3 only (the queue that has
    just refused a record carries no diagnostic frame, SPEC:277), then resigns, disconnects and
    exits 1. The counts are hand-derived from the bounds (4096 frames, 16 MiB of copied bytes)."""
    run = direct_harness(tmp_path, scenario)
    assert run.wait() == EXIT_FAILURE
    assert stages(run.status()) == ["connect", "running", "join", "running", "resolve", "running",
                                    "failure:E_QUEUE_OVERFLOW", "resign", "running",
                                    "disconnect", "running"]
    frames = run.frames()
    assert frames[0]["event"]["type"] == "generation_start"
    assert frames[1]["event"] == discover_event("o1", "c" if scenario == "overflow-count" else "b")
    assert _numbered([f["event"] for f in frames[2:]], "o1", attributes) == kept


@case("A-OVERFLOW", "G-R41", "G-R12", "G-R16", "G-R06",
      paragraphs=("SPEC:279", "SPEC:277", "SPEC:275"))
def test_a_host_that_stops_reading_fills_the_queue_and_never_blocks_a_callback(tmp_path):
    """A-OVERFLOW with a reader that does not read (R41: the kernel pipe is flow control, not
    the bound): one reflection per batch, each handed to the writer thread, while nobody reads
    stdout. The pipe fills and the writer blocks; the callbacks do not (SPEC:279): they go on
    appending until the queue's own bound refuses one, and E_QUEUE_OVERFLOW arrives on fd 3
    while stdout is still unread. Reading then gets every accepted record, in order, with no gap:
    the discover and an unbroken run of reflections. Each frame was stamped with CLOCK_MONOTONIC
    in its callback (SPEC:275): every stamp lies between this test's readings of that clock
    before the start and when it began to read, although most were written after."""
    before = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    run = direct_harness(tmp_path, "overflow-stalled", read_frames=False)
    deadline = time.monotonic() + 60
    while b"E_QUEUE_OVERFLOW" not in run.status_bytes():
        assert time.monotonic() < deadline and run.alive(), run.status_bytes()
        time.sleep(0.01)
    reading = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    assert run.alive()
    run.read_frames_now()
    assert run.wait() == EXIT_FAILURE
    assert stages(run.status()) == ["connect", "running", "join", "running", "resolve", "running",
                                    "request_update", "running", "failure:E_QUEUE_OVERFLOW",
                                    "resign", "running", "disconnect", "running"]
    frames = run.frames()
    assert frames[1]["event"] == discover_event("o1", "stalled-object")
    kept = _numbered([f["event"] for f in frames[2:]], "o1", [("ForceIdentifier", "01")])
    # At least the queue's 4096 frames less the two written before the stall began.
    assert kept >= 4094
    stamps = [int(f["monotonic_ns"]) for f in frames]
    assert stamps == sorted(stamps)
    assert before <= stamps[0] and stamps[-1] <= reading


@case("A-OVERFLOW", "G-R41", paragraphs=("SPEC:277",))
def test_an_overflow_under_the_host_ends_failed_with_the_failure_from_fd_3(tmp_path):
    """A-OVERFLOW through the host (R41, NAT-08): the failure the worker reports on fd 3 becomes
    the session's condition; the host writes its diagnostic frame from that record (the worker
    sent none), closes the generation with reason limit and writes FAILED E_QUEUE_OVERFLOW,
    whose reason identifies the lost evidence; exit class 6. What the host captured of the
    accepted records is an unbroken prefix of them (it captures for at most one second after the
    failure, SPEC:277)."""
    session, _log = harness_session(tmp_path, "overflow-count", stop=False)
    session.check()
    shape = session.shape()
    assert shape[-3:] == [DIAG(1, "E_QUEUE_OVERFLOW"), END(1, "limit"),
                          FOOT("FAILED", "E_QUEUE_OVERFLOW", 1)]
    events = session.events()
    assert events[0] == discover_event("o1", "c")
    reflections = _numbered(events[1:-1], "o1", [("ForceIdentifier", "01")])
    assert reflections <= 4095
    assert events[-1] == worker_diagnostic("E_QUEUE_OVERFLOW")
    assert session.summary["terminal_codes"] == ["E_QUEUE_OVERFLOW"]
    assert exit_class(session.summary) == 6


@case("G-R12", "G-R41", paragraphs=("SPEC:291",))
def test_the_worker_allocates_100000_tokens_and_refuses_the_next(tmp_path):
    """NAT-11 at its real value (OPS-21: native limits are tested at real values): reflections of
    100000 distinct handles nobody discovered take o1 .. o100000; the next handle would be token
    100001 and is E_LIMIT, nothing of it captured. SPEC:291's removed-token set is bounded by the
    same count: every handle the worker maps holds one of those tokens."""
    run = direct_harness(tmp_path, "tokens")
    assert run.wait(timeout=300) == EXIT_FAILURE
    frames = run.frames()
    assert len(frames) == 1 + 100000 + 1
    tokens = [f["event"]["object_token"] for f in frames[1:-1]]
    assert tokens == [f"o{n}" for n in range(1, 100001)]
    assert event_key(frames[-1]["event"]) == worker_diagnostic("E_LIMIT")
    assert stages(run.status())[-5:] == ["failure:E_LIMIT", "resign", "running", "disconnect",
                                         "running"]


#: The four maximal values of overflow-bytes and its relatives (harness.cpp four_maximal_values).
MAXIMAL = [("EntityIdentifier", "01" * 4096), ("EntityType", "02" * 4096),
           ("ForceIdentifier", "03" * 4096), ("Spatial", "04" * 4096)]
GENERATION_START = {"type": "generation_start", "federation_name": FED}
RESOLVED = ["connect", "running", "join", "running", "resolve", "running"]
CLOSED = ["resign", "running", "disconnect", "running"]


#: HLAfloat64Time(1.0): IEEE 754 binary64 1.0 = 0x3FF0000000000000, big-endian.
TIME_1 = {"implementation": "HLAfloat64Time", "hex": "3ff0000000000000"}
#: The record after the 1023 maximal reflections in each edge scenario (review finding
#: R7-r2-F3), hand-derived in harness.cpp: what is captured after them when the record fits.
_FILL = [("EntityIdentifier", "01" * 4096), ("EntityType", "02" * 4096)]
BYTE_EDGE_AFTER = {
    # 8192 + 4073 value bytes + 4-byte tag + 8-byte time + 14-byte name = 12291 bytes left.
    "overflow-bytes-time-exact": [reflect_event(
        "o1", _FILL + [("ForceIdentifier", "03" * 4073)], tag="000003ff", sent="TIMESTAMP",
        received="TIMESTAMP", time_=TIME_1)],
    "overflow-bytes-time-over": [],
    # The 8269-byte reflection leaves 4022: a 4000-byte tag + 8 + 14 fills it, 4001 does not.
    "overflow-bytes-remove-exact": [
        reflect_event("o1", _FILL + [("ForceIdentifier", "03" * 73)], tag="000003ff"),
        remove_event("o1", tag="7e" * 4000, received="TIMESTAMP", time_=TIME_1)],
    "overflow-bytes-remove-over": [
        reflect_event("o1", _FILL + [("ForceIdentifier", "03" * 73)], tag="000003ff")],
}


@case("A-OVERFLOW", "G-R41", paragraphs=("SPEC:279",))
@pytest.mark.parametrize("scenario", sorted(BYTE_EDGE_AFTER))
def test_a_logical_time_and_a_removals_tag_count_toward_the_byte_bound(tmp_path, scenario):
    """CR-new-R7-05 counts a logical time's encoding and implementation name and a removal's tag
    toward the 16 MiB bound, each held one byte either side of the remainder: after the 16764925
    bytes of the byte-bound test, a timed reflection of 4096 + 4096 + 4073 value bytes, a 4-byte
    tag and HLAfloat64Time(1.0) (8 encoded bytes, 14 bytes of name) is exactly 12291 and is
    captured, the 1-byte empty reflection after it refused; with 4074 it is refused itself. A
    reflection of 8269 bytes leaves 4022, which a timed removal with a 4000-byte tag fills (the
    empty reflection after it refused) and one with a 4001-byte tag does not. E_QUEUE_OVERFLOW on
    fd 3 in every row; a mutant that left the time or the removal's tag out of the sum captures
    the record that must be refused."""
    run = direct_harness(tmp_path, scenario)
    assert run.wait() == EXIT_FAILURE
    assert stages(run.status()) == RESOLVED + ["failure:E_QUEUE_OVERFLOW"] + CLOSED
    events = [f["event"] for f in run.frames()]
    assert events[0] == GENERATION_START and events[1] == discover_event("o1", "b")
    assert _numbered(events[2:1025], "o1", MAXIMAL) == 1023
    assert events[1025:] == BYTE_EDGE_AFTER[scenario]


@case("A-OVERFLOW", "G-R41", paragraphs=("SPEC:279",))
@pytest.mark.parametrize("scenario,last", [("overflow-bytes-exact", 4095),
                                           ("overflow-bytes-over", 4096)],
                         ids=["fits-exactly", "one-byte-more"])
def test_the_byte_bound_admits_a_record_that_fills_it_exactly_and_refuses_one_byte_more(
        tmp_path, scenario, last):
    """R41 and NAT-06, the 16 MiB bound from both sides, hand-derived: the discover's name "b" (1
    byte) and 1023 reflections of four 4096-byte values and a 4-byte tag (16388 bytes each) hold
    1 + 1023 * 16388 = 16764925 bytes, which leaves 16777216 - 16764925 = 12291. The next
    reflection carries 4096 + 4096 + `last` value bytes and a 4-byte tag: with 4095 that is
    12291, exactly what is left, and it is captured; the empty reflection after it with a 1-byte
    tag is one byte over the bound and is refused (E_QUEUE_OVERFLOW on fd 3). With 4096 it is
    12292, one byte more than is left, and that reflection is the one refused. All in one batch,
    far below the 4096-frame bound."""
    run = direct_harness(tmp_path, scenario)
    assert run.wait() == EXIT_FAILURE
    assert stages(run.status()) == RESOLVED + ["failure:E_QUEUE_OVERFLOW"] + CLOSED
    events = [f["event"] for f in run.frames()]
    assert events[0] == GENERATION_START and events[1] == discover_event("o1", "b")
    assert _numbered(events[2:1025], "o1", MAXIMAL) == 1023
    exact = reflect_event("o1", [("EntityIdentifier", "01" * 4096), ("EntityType", "02" * 4096),
                                 ("ForceIdentifier", "03" * 4095)], tag="000003ff")
    assert events[1025:] == ([exact] if last == 4095 else [])


#: What follows a terminal condition in its batch (R41, A-OVERFLOW: no record after the refused
#: one, no silent gap): each scenario makes three callbacks the observer accepts on their own
#: (harness.cpp acceptable_after: an empty reflection of o1 tagged 0000270f, a discovery named
#: "after", a removal of o1 tagged 0000270f) right after the refusing one. The code, the
#: request_update/running pairs before the failure record, and the events written before the
#: condition, hand-derived from the scenarios.
AFTER = {
    # 1 + 1023 * 16388 bytes fit, the 1024th maximal reflection does not; the three would fit
    # the 12291 bytes left.
    "after-overflow-bytes": ("E_QUEUE_OVERFLOW", 0, [discover_event("o1", "b")] + [
        reflect_event("o1", MAXIMAL, tag=f"{number:08x}") for number in range(1023)]),
    "after-limit-value": ("E_LIMIT", 1, [discover_event("o1", "limit-object")]),
    "after-limit-tag": ("E_LIMIT", 1, [discover_event("o1", "limit-object")]),
    "after-limit-name": ("E_LIMIT", 1, [discover_event("o1", "limit-object")]),
}


def assert_no_record_after(frames: list[dict]) -> None:
    """None of acceptable_after's three records reached stdout."""
    for frame in frames:
        event = frame["event"]
        assert event.get("tag_hex") != "0000270f" and event.get("name") != "after", event


@case("A-OVERFLOW", "G-R41", paragraphs=("SPEC:277", "SPEC:279"))
@pytest.mark.parametrize("scenario", sorted(AFTER))
def test_nothing_after_the_refused_callback_of_a_batch_is_captured(tmp_path, scenario):
    """R41 ("explicit failure, no silent dropping"), A-OVERFLOW and NAT-08: once a callback has
    raised a terminal condition (the queue refusing by bytes; E_LIMIT for a value, a tag, an
    object name), no later callback of the same evoke batch is captured, although each of the
    three that follow would fit: the frames end with the records accepted before the condition
    (and the worker's diagnostic frame, except after an overflow), and the one failure record
    names the first condition."""
    code, pairs, events = AFTER[scenario]
    run = direct_harness(tmp_path, scenario)
    assert run.wait() == EXIT_FAILURE
    assert stages(run.status()) == (RESOLVED + ["request_update", "running"] * pairs +
                                    [f"failure:{code}"] + CLOSED)
    frames = run.frames()
    diagnostic = [] if code == "E_QUEUE_OVERFLOW" else [worker_diagnostic(code)]
    assert [event_key(f["event"]) for f in frames] == [GENERATION_START] + events + diagnostic
    assert_no_record_after(frames)
    assert run.stderr_bytes() == b""


@case("A-OVERFLOW", "G-R41", paragraphs=("SPEC:277", "SPEC:279"))
def test_nothing_after_a_refusal_by_frames_is_captured_once_the_queue_has_room_again(tmp_path):
    """The same rule for the frame bound, where the queue gets room back while a batch is still
    open: one numbered reflection per batch while this test does not read stdout, until the
    4097th outstanding record is refused (frames, not bytes: each copies 5 bytes); the harness
    logs that number and keeps the batch open, this test then reads everything, and only once
    the writer has written all it accepted (the queue empty again) does the harness make the
    three acceptable callbacks in that batch. None is captured: the frames are the discover and
    the unbroken run of reflections 0 .. number-1, and the failure is E_QUEUE_OVERFLOW on fd 3
    only."""
    log = tmp_path / "after-overflow-frames.log"
    run = direct_harness(tmp_path, "after-overflow-frames", read_frames=False)
    deadline = time.monotonic() + 60
    while not (refused := [e for e in log_entries(log) if e.get("event") == "refused"]):
        assert time.monotonic() < deadline and run.alive()
        time.sleep(0.01)
    run.read_frames_now()
    assert run.wait() == EXIT_FAILURE
    assert stages(run.status()) == (RESOLVED + ["request_update", "running",
                                                "failure:E_QUEUE_OVERFLOW"] + CLOSED)
    frames = run.frames()
    assert frames[0]["event"] == GENERATION_START
    assert frames[1]["event"] == discover_event("o1", "stalled-object")
    number = refused[0]["number"]
    # At the refusal 4096 records were outstanding, at most two of them not reflections.
    assert number >= 4094
    assert _numbered([f["event"] for f in frames[2:]], "o1", [("ForceIdentifier", "01")]) == number
    assert_no_record_after(frames)


#: CR-new-R7-06 on a full queue (the discover of o1 and 4095 numbered reflections, 4096 frames):
#: the enumerations and an object name's size come before the queue. The failure record is
#: deterministic; the worker's own diagnostic frame goes through the queue only when it has room
#: by then (NAT-08), which depends on how far the writer got, so the frames may end with it.
FULL_QUEUE = [discover_event("o1", "c")] + [
    reflect_event("o1", [("ForceIdentifier", "01")], tag=f"{number:08x}")
    for number in range(4095)]
ON_A_FULL_QUEUE = {
    "precedence-order-queue": "E_CAPTURE_SCHEMA",
    "precedence-remove-order-queue": "E_CAPTURE_SCHEMA",
    "precedence-name-queue": "E_LIMIT",
}


@case("G-R41", "G-R13", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("scenario", sorted(ON_A_FULL_QUEUE))
def test_a_callback_refused_on_a_full_queue_reports_its_own_fault_first(tmp_path, scenario):
    """CR-new-R7-06: with 4096 frames in the queue, a reflection or removal whose received order
    is outside the enumeration is E_CAPTURE_SCHEMA and a discovery under a 1025-byte name is
    E_LIMIT, not E_QUEUE_OVERFLOW: a callback's own checks come before the queue's room."""
    code = ON_A_FULL_QUEUE[scenario]
    run = direct_harness(tmp_path, scenario)
    assert run.wait() == EXIT_FAILURE
    assert stages(run.status()) == RESOLVED + [f"failure:{code}"] + CLOSED
    events = [event_key(f["event"]) for f in run.frames()]
    assert events[0] == GENERATION_START and events[1:4097] == FULL_QUEUE
    assert events[4097:] in ([], [worker_diagnostic(code)])


def token_bound_frames(data: bytes) -> list[dict]:
    """The frames of a scenario that first spends the 100000 tokens: the 100000 reflections of
    o1 .. o100000 checked line by line as text (each the same frame but for its token and
    stamp), every other frame parsed and held to the schema."""
    lines = _lines(data)
    assert len(lines) > 100001
    head = worker_frames(lines[0] + b"\n")
    for number, line in enumerate(lines[1:100001], start=1):
        assert b'"object_token":"o%d"' % number in line and b'"type":"reflect"' in line, number
    return head + worker_frames(b"".join(line + b"\n" for line in lines[100001:]))


#: The scenarios at the token bound: the code, and whether 4096 reflections of o1 fill the queue
#: before the refused callback. The reflect arm (R7), then the discover and remove arms (review
#: finding R7-r2-F2), each with the pairs of CR-new-R7-06 that apply to it.
TOKEN_BOUND = {
    "precedence-order-token": ("E_CAPTURE_SCHEMA", False),
    "precedence-token-queue": ("E_LIMIT", True),
    "token-bound-discover": ("E_LIMIT", False),
    "token-bound-discover-queue": ("E_LIMIT", True),
    "token-bound-remove": ("E_LIMIT", False),
    "token-bound-remove-order": ("E_CAPTURE_SCHEMA", False),
    "token-bound-remove-queue": ("E_LIMIT", True),
}


@case("G-R12", "G-R41", paragraphs=("SPEC:291",))
@pytest.mark.parametrize("scenario", sorted(TOKEN_BOUND))
def test_at_the_token_bound_the_enumerations_come_before_it_and_the_queue_after(tmp_path,
                                                                                scenario):
    """CR-new-R7-06 around NAT-11's token budget, at its real value: 100000 tokens spent by
    reflections of handles nobody discovered (as the tokens scenario), the queue drained; then,
    on each arm that can allocate a token: a reflection of a new handle whose received order is
    outside the enumeration is E_CAPTURE_SCHEMA (the enumerations first), and one while 4096
    reflections of o1 fill the queue is E_LIMIT (the token budget before the queue's room); a
    discovery of a new handle is E_LIMIT, with the queue full too; a removal of a new handle is
    E_LIMIT, with the queue full too, and a timed one with a received order outside the
    enumeration is E_CAPTURE_SCHEMA. Nothing of the refused callback is captured (the 100001st
    token is never allocated). Run with --stop-when-ready, so a worker that let the callback
    through ends 0 at once instead of idling."""
    code, filled_first = TOKEN_BOUND[scenario]
    run = direct_harness(tmp_path, scenario, stop_when_ready=True)
    assert run.wait(timeout=300) == EXIT_FAILURE
    assert stages(run.status()) == RESOLVED + [f"failure:{code}"] + CLOSED
    frames = token_bound_frames(run.frame_bytes())
    tail = [event_key(f["event"]) for f in frames[1:]]
    if not filled_first:
        assert tail == [worker_diagnostic(code)]
    else:
        filled = [reflect_event("o1", [("ForceIdentifier", "01")], tag=f"{number:08x}")
                  for number in range(4096)]
        assert tail[:4096] == filled and tail[4096:] in ([], [worker_diagnostic(code)])


# ===================================================================== RTI calls that fail

LIFECYCLE = ["connect", "joinFederationExecution", "getObjectClassHandle"] + \
    ["getAttributeHandle"] * 4 + ["subscribeObjectClassAttributes"]
RESIGN_DISCONNECT = ["resignFederationExecution", "disconnect"]


def _joined(call: str) -> list[str]:
    return ["connect", "joinFederationExecution", f"joinFederationExecution!{call}",
            "disconnect"]


#: CR-new-R7-10 row by row, and CR-new-R7-16: the decorator fails one of the observer's RTI calls
#: with an exception of that service's own specification (harness.cpp faults()), or sends
#: SIGTERM while the call runs; name-in-use is the real RTI refusing the join (the harness's
#: setup federate holds the observer's federate name). Per scenario: the code (None: no
#: condition, an orderly end), the status records, the frames, the decorator's call trace
#: (call_trace) and whether the harness raises SIGTERM once the scenario has been played.
FAULTS = {
    "name-in-use": (
        "E_FEDERATE_NAME", ["connect", "running", "join", "running", "failure:E_FEDERATE_NAME",
                            "disconnect", "running"],
        [worker_diagnostic("E_FEDERATE_NAME")],
        ["connect", "joinFederationExecution", "disconnect"], False),
    # A stop that arrives while connect blocks: disconnect, no join; while join blocks:
    # generation_start is still written, then resign and disconnect, no resolve.
    "fault-connect-stop": (
        None, ["connect", "running", "disconnect", "running"], [],
        ["connect", "connect!SIGTERM", "disconnect"], False),
    "fault-join-stop": (
        None, ["connect", "running", "join", "running"] + CLOSED, [GENERATION_START],
        ["connect", "joinFederationExecution", "joinFederationExecution!SIGTERM"] +
        RESIGN_DISCONNECT, False),
    # R7-r2-F5: the RTIambassador factory itself refusing (an RTI exception from create()) is
    # E_RTI_CONNECT before any stage record: no RTI call is made at all, nothing to close.
    "fault-create": (
        "E_RTI_CONNECT", ["failure:E_RTI_CONNECT"], [worker_diagnostic("E_RTI_CONNECT")], [],
        False),
}
for _fault, _code in [("time-factory", "E_FOM_PROFILE"), ("inconsistent-fdd", "E_FOM_PROFILE"),
                      ("error-reading-fdd", "E_FOM_PROFILE"),
                      ("could-not-open-fdd", "E_FOM_PROFILE"), ("other", "E_RTI_CONNECT")]:
    _thrown = {"time-factory": "CouldNotCreateLogicalTimeFactory",
               "inconsistent-fdd": "InconsistentFDD", "error-reading-fdd": "ErrorReadingFDD",
               "could-not-open-fdd": "CouldNotOpenFDD", "other": "RTIinternalError"}[_fault]
    # join refused: no generation is open, nothing to resign.
    FAULTS[f"fault-join-{_fault}"] = (
        _code, ["connect", "running", "join", "running", f"failure:{_code}", "disconnect",
                "running"],
        [worker_diagnostic(_code)], _joined(_thrown), False)
for _scenario, _call, _thrown, _code, _before in [
        ("fault-class-name", "getObjectClassHandle", "NameNotFound", "E_FOM_PROFILE",
         ["connect", "joinFederationExecution", "getObjectClassHandle"]),
        ("fault-attribute-other", "getAttributeHandle", "InvalidObjectClassHandle",
         "E_RTI_CONNECT",
         ["connect", "joinFederationExecution", "getObjectClassHandle", "getAttributeHandle"]),
        ("fault-subscribe-class", "subscribeObjectClassAttributes", "ObjectClassNotDefined",
         "E_FOM_PROFILE", LIFECYCLE),
        ("fault-subscribe-attribute", "subscribeObjectClassAttributes", "AttributeNotDefined",
         "E_FOM_PROFILE", LIFECYCLE),
        ("fault-subscribe-other", "subscribeObjectClassAttributes", "RTIinternalError",
         "E_RTI_CONNECT", LIFECYCLE)]:
    # resolve refused: inside the generation join opened.
    FAULTS[_scenario] = (
        _code, RESOLVED + [f"failure:{_code}"] + CLOSED,
        [GENERATION_START, worker_diagnostic(_code)],
        _before + [f"{_call}!{_thrown}"] + RESIGN_DISCONNECT, False)
FAULTS.update({
    "fault-evoke": (
        "E_RTI_CONNECT", RESOLVED + ["failure:E_RTI_CONNECT"] + CLOSED,
        [GENERATION_START, worker_diagnostic("E_RTI_CONNECT")],
        LIFECYCLE + ["evokeMultipleCallbacks!RTIinternalError"] + RESIGN_DISCONNECT, False),
    "fault-request-attribute": (
        "E_FOM_PROFILE", RESOLVED + ["request_update", "running", "failure:E_FOM_PROFILE"] + CLOSED,
        [GENERATION_START, discover_event("o1", "requested-object"),
         worker_diagnostic("E_FOM_PROFILE")],
        LIFECYCLE + ["requestAttributeValueUpdate!AttributeNotDefined"] + RESIGN_DISCONNECT,
        False),
    "fault-request-other": (
        "E_RTI_CONNECT", RESOLVED + ["request_update", "running", "failure:E_RTI_CONNECT"] + CLOSED,
        [GENERATION_START, discover_event("o1", "requested-object"),
         worker_diagnostic("E_RTI_CONNECT")],
        LIFECYCLE + ["requestAttributeValueUpdate!RTIinternalError"] + RESIGN_DISCONNECT, False),
    # After the orderly stop, a failing resign or disconnect is the session's condition, reported
    # right after the running of its stage (CR-new-R7-11).
    "fault-resign-after-stop": (
        "E_RTI_CONNECT", RESOLVED + ["resign", "running", "failure:E_RTI_CONNECT", "disconnect",
                                     "running"],
        [GENERATION_START, worker_diagnostic("E_RTI_CONNECT")],
        LIFECYCLE + ["resignFederationExecution", "resignFederationExecution!RTIinternalError",
                     "disconnect"], True),
    "fault-disconnect-after-stop": (
        "E_RTI_CONNECT", RESOLVED + CLOSED + ["failure:E_RTI_CONNECT"],
        [GENERATION_START, worker_diagnostic("E_RTI_CONNECT")],
        LIFECYCLE + RESIGN_DISCONNECT + ["disconnect!RTIinternalError"], True),
    # After an earlier condition (E_LIMIT), the failing call reports nothing more.
    "fault-resign-after-condition": (
        "E_LIMIT", RESOLVED + ["failure:E_LIMIT"] + CLOSED,
        [GENERATION_START, discover_event("o1", "limit-object"), worker_diagnostic("E_LIMIT")],
        LIFECYCLE + ["resignFederationExecution", "resignFederationExecution!RTIinternalError",
                     "disconnect"], False),
    "fault-disconnect-after-condition": (
        "E_LIMIT", RESOLVED + ["failure:E_LIMIT"] + CLOSED,
        [GENERATION_START, discover_event("o1", "limit-object"), worker_diagnostic("E_LIMIT")],
        LIFECYCLE + RESIGN_DISCONNECT + ["disconnect!RTIinternalError"], False),
})


@case("G-R10", "G-R06", "G-R14", paragraphs=("SPEC:50", "SPEC:277", "SPEC:62"))
@pytest.mark.parametrize("scenario", sorted(FAULTS))
def test_each_rti_exception_maps_to_its_code_and_the_worker_ends_in_order(tmp_path, scenario):
    """CR-new-R7-10, row by row, for the exceptions no compliant RTI raises on demand (the
    decorator throws them in place of the call; resign and disconnect fail after they were
    made): join refused for its logical time factory or its FDD is E_FOM_PROFILE, for anything
    else E_RTI_CONNECT, and for a name in use (the real RTI's refusal) E_FEDERATE_NAME, with no
    generation open and nothing to resign; a resolve refused with NameNotFound,
    ObjectClassNotDefined or AttributeNotDefined is E_FOM_PROFILE, with anything else
    E_RTI_CONNECT; evoke failing is E_RTI_CONNECT; the post-callback request refused with
    AttributeNotDefined is E_FOM_PROFILE, with anything else E_RTI_CONNECT; a resign or
    disconnect failing after the orderly stop is E_RTI_CONNECT, after an earlier condition it
    reports nothing more. CR-new-R7-16: a stop seen once connect returns disconnects without a
    join; once join returns, generation_start is still written, then resign and disconnect,
    nothing resolved; both exit 0. Every condition is exactly one failure record (with the same
    code as a diagnostic frame), then the close, and exit 1; the exception's own text (it says
    "injected") reaches no channel (CR-new-R7-15)."""
    code, expected_stages, events, trace, stop = FAULTS[scenario]
    log = tmp_path / f"{scenario}.log"
    run = direct_harness(tmp_path, scenario, stop_when_ready=stop)
    assert run.wait() == (EXIT_STOPPED if code is None else EXIT_FAILURE)
    records = run.status()
    assert stages(records) == expected_stages
    for failure in (r for r in records if r["type"] == "failure"):
        check_failure_message(failure)
    assert [event_key(f["event"]) for f in run.frames()] == events
    assert call_trace(log) == trace
    assert_only_allowed_calls(log)
    assert run.stderr_bytes() == b""
    assert b"injected" not in run.frame_bytes() + run.status_bytes()
    factory = [e for e in log_entries(log) if "factory" in e]
    assert factory == ([{"factory": "create", "injected": "RTIinternalError"}]
                       if scenario == "fault-create" else [])


# ======================================================================= broken channels (NAT-09)

@case("G-R06", "G-R14", paragraphs=("SPEC:277",))
def test_a_reader_that_closes_stdout_ends_the_worker_with_status_71(tmp_path):
    """NAT-09 and SPEC:277: EPIPE on stdout is terminal (SIGPIPE is ignored). The worker's own
    event loop (Observer::step) carries one numbered reflection per turn (harness scenario
    stream-frames); this test reads the first three frames and closes its end of stdout. The
    writer's next write fails, the next turn ends the loop, and the worker, which can report
    nothing on a channel nobody reads, writes no failure record: it resigns with NO_ACTION and
    disconnects (on fd 3 and in the decorator's log) and exits 71 (CR-new-R7-01) by itself, its
    PID gone within the bounded wait. A worker that went on writing, or ended another way, fails
    here."""
    log = tmp_path / "stream-frames.log"
    run = direct_harness(tmp_path, "stream-frames", read_frames=False)
    read = read_lines_then_close(run.take_frames_fd(), 3)
    assert run.wait(timeout=60) == EXIT_CHANNEL_LOST
    assert [f["event"] for f in worker_frames(read)] == [
        GENERATION_START, discover_event("o1", "streaming-object"),
        reflect_event("o1", [("ForceIdentifier", "01")], tag="00000000")]
    assert stages(run.status()) == RESOLVED + ["request_update", "running"] + CLOSED
    assert calls(log)[-2:] == CLOSE_CALLS
    assert log_entries(log)[-1] == {"event": "exit", "status": EXIT_CHANNEL_LOST}
    assert run.stderr_bytes() == b""


@case("G-R06", "G-R14", paragraphs=("SPEC:277",))
def test_a_reader_that_closes_fd_3_ends_the_worker_with_status_71(tmp_path):
    """NAT-09 and SPEC:277: EPIPE on fd 3 is terminal too. One new object per turn of the event
    loop (stream-objects), so that each turn writes request_update and running on fd 3; this
    test reads the status records up to the first such pair and closes its end of fd 3. The next
    stage record fails, the event loop ends, and the worker resigns and disconnects (the
    decorator's log; their stage records go nowhere) and exits 71 by itself. Everything it
    accepted reaches stdout: generation_start and an unbroken run of discoveries o1, o2 ...,
    no diagnostic."""
    log = tmp_path / "stream-objects.log"
    run = direct_harness(tmp_path, "stream-objects", read_status=False)
    read = read_lines_then_close(run.take_status_fd(), 8)
    assert run.wait(timeout=60) == EXIT_CHANNEL_LOST
    assert stages(status_records(read)) == RESOLVED + ["request_update", "running"]
    events = [f["event"] for f in run.frames()]
    assert events[0] == GENERATION_START and len(events) >= 2
    assert events[1:] == [discover_event(f"o{number}", "streaming-object")
                          for number in range(1, len(events))]
    assert calls(log)[-2:] == CLOSE_CALLS
    assert log_entries(log)[-1] == {"event": "exit", "status": EXIT_CHANNEL_LOST}
    assert run.stderr_bytes() == b""


# ============================================================================ stopping

@case("G-R14", "G-R06", paragraphs=("SPEC:277",))
def test_sigterm_in_the_middle_of_a_batch_finishes_the_batch_then_resigns(tmp_path):
    """R14 and the carried G-R14 clause (SPEC:277: the handler only sets a flag): SIGTERM arrives
    between two callbacks of one batch; the rest of the batch is still captured (both
    reflections and the removal), its request is made, and only then does the observer resign
    with NO_ACTION, disconnect and exit 0 by itself; no generation_end from the worker."""
    log = tmp_path / "stop-mid-batch.log"
    run = direct_harness(tmp_path, "stop-mid-batch")
    assert run.wait() == EXIT_STOPPED
    assert [f["event"] for f in run.frames()[1:]] == [
        discover_event("o1", "stopping-object"),
        reflect_event("o1", [("ForceIdentifier", "01")]),
        reflect_event("o1", [("ForceIdentifier", "02")]),
        remove_event("o1"),
    ]
    assert stages(run.status()) == ["connect", "running", "join", "running", "resolve", "running",
                                    "request_update", "running", "resign", "running",
                                    "disconnect", "running"]
    assert calls(log)[-2:] == CLOSE_CALLS


@case("G-R06", "G-R14", paragraphs=("SPEC:277",))
def test_the_parent_rule_sees_any_other_parent_not_only_init(tmp_path):
    """The worker's parent rule (CR-new-R7): "gone" means getppid() differs from the parent
    recorded at start, so a subreaper's pid (4243 after 4242, what a Linux orphan of a session
    with a subreaper sees) counts as well as init's 1; the recorded parent itself does not. The
    rule is called by the harness and its answers logged."""
    run = direct_harness(tmp_path, "parent-rule", stop_when_ready=True)
    assert run.wait() == EXIT_STOPPED
    rule = [e for e in log_entries(tmp_path / "parent-rule.log") if e.get("event") == "parent-rule"]
    assert rule == [{"changed": [True, True, False, False], "event": "parent-rule"}]


@case("G-R12", paragraphs=("SPEC:56",))
def test_an_idle_worker_does_not_keep_a_processor_busy(tmp_path):
    """NAT-05: with nothing to deliver, evokeMultipleCallbacks(0.0, 0.05) returns at once, and
    without the 5 ms pause after such a call the event loop would spin a whole core. The harness
    idles in the worker's event loop for two seconds (the test's own wall clock), then gets
    SIGTERM; the CPU time the process used (its rusage) is well under half of that; the
    decorator logged hundreds, not millions, of evoke calls, all with R12's parameters."""
    log = tmp_path / "idle.log"
    run = DirectRun(harness_argv("idle", log, *worker_args("rti://127.0.0.1:1")))
    deadline = time.monotonic() + 60
    while not any(e.get("event") == "ready" for e in log_entries(log)):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    time.sleep(2)
    os.kill(run.pid, signal.SIGTERM)
    _, status, usage = os.wait4(run.pid, 0)
    run.exit_code = os.waitstatus_to_exitcode(status)
    assert run.wait() == EXIT_STOPPED
    assert usage.ru_utime + usage.ru_stime < 1.0
    evokes = sum(c["count"] for c in calls(log) if c["call"] == "evokeMultipleCallbacks")
    assert 10 <= evokes <= 4000
    assert_only_allowed_calls(log)


PARENT = r"""
import os, sys, time
pid = os.posix_spawn(sys.argv[1], sys.argv[1:], dict(os.environ),
                     file_actions=[(os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
                                   (os.POSIX_SPAWN_DUP2, int(os.environ["SC_HLA_OUT"]), 1),
                                   (os.POSIX_SPAWN_DUP2, int(os.environ["SC_HLA_STATUS"]), 3)],
                     setpgroup=0)
print(pid, flush=True)
time.sleep(600)
"""


@case("G-R06", "G-R14", paragraphs=("SPEC:277",))
def test_a_worker_whose_parent_has_gone_resigns_disconnects_and_exits(tmp_path):
    """The worker's own parent-death check (DECISIONS C.6, CR-new-R7): its parent (here a small
    interpreter standing for the host) is killed while the worker idles in its event loop; at
    its next idle pause the worker sees another parent than the one it started with, resigns
    with NO_ACTION, disconnects and exits with its own status (72). This test holds the pipes'
    read ends, so no EPIPE tells the worker anything: the parent check alone ends it."""
    log = tmp_path / "idle.log"
    out_read, out_write = os.pipe()
    status_read, status_write = os.pipe()
    for fd in (out_write, status_write):
        os.set_inheritable(fd, True)
    env = plain_environment(SC_HLA_OUT=str(out_write), SC_HLA_STATUS=str(status_write))
    parent = subprocess.Popen([sys.executable, "-B", "-c", PARENT,
                               *harness_argv("idle", log, *worker_args("rti://127.0.0.1:1"))],
                              stdout=subprocess.PIPE, env=env, pass_fds=(out_write, status_write))
    os.close(out_write)
    os.close(status_write)
    try:
        child = int(parent.stdout.readline())
        deadline = time.monotonic() + 60
        while not any(e.get("event") == "ready" for e in log_entries(log)):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        parent.kill()
        parent.wait(timeout=10)
        assert process_gone(child, within_s=30), "the worker outlived its parent"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        parent.stdout.close()
    status = status_records(_drain(status_read))
    frames = worker_frames(_drain(out_read))
    assert stages(status)[-4:] == ["resign", "running", "disconnect", "running"]
    assert [f["event"]["type"] for f in frames] == ["generation_start"]
    assert calls(log)[-2:] == CLOSE_CALLS
    assert log_entries(log)[-1] == {"event": "exit", "status": EXIT_PARENT_GONE}


def _drain(fd: int) -> bytes:
    data = bytearray()
    try:
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                return bytes(data)
            data.extend(chunk)
    finally:
        os.close(fd)


# ================================================================= the worker against the network

def config_at(endpoint: str) -> dict:
    config = example_json("config-existing.json")
    config["endpoint"] = endpoint
    return config


@case("G-R10", "G-R06", "G-R14", paragraphs=("SPEC:62",))
def test_a_refused_connection_is_retried_after_1_2_4_seconds_and_ends_failed(tmp_path):
    """The worker under the host against a closed loopback port (nothing listens there): connect
    fails at once (ConnectionFailed); the worker reports E_RTI_CONNECT on fd 3 and as a frame and
    exits; the host retries after 1, 2 and 4 s (the seam clock records the waits, SPEC:62),
    never opens a generation (no join), and after the fourth failure writes FAILED E_RTI_CONNECT:
    four generation-0 diagnostics at elapsed 0, the workers' own copies (NAT-08, NAT-10). Exit
    class 5. The configured endpoint is the designator connect used (R10)."""
    session = NativeSession(tmp_path, worker(), config=config_at(f"rti://127.0.0.1:{free_port()}"))
    session.run()
    report = session.check()
    assert capture_shape(session.records()[1:]) == [
        ("diagnostic", 0, 0, "E_RTI_CONNECT", None, None)] * 4 + [
        FOOT("FAILED", "E_RTI_CONNECT", 0)]
    assert session.sleeps == [1 * SECOND, 2 * SECOND, 4 * SECOND]
    assert (session.summary["workers"], session.summary["terminal_codes"]) == (
        4, ["E_RTI_CONNECT"])
    assert exit_class(session.summary) == 5 and report["status"] == "FAILED"
    messages = {f["event"]["diagnostic"]["message"] for f in session.frames()}
    assert len(messages) == 1


@case("A-TIMEOUT", "G-R14", "G-R10", paragraphs=("SPEC:62",))
def test_a_listener_that_never_answers_is_the_host_deadline(tmp_path):
    """A-TIMEOUT with the real worker (R14, NAV-03): the configured endpoint accepts the TCP
    connection and never answers, so OpenRTI's connect blocks; the worker has written its connect
    stage and nothing after it; at the host's deadline (2 s here, the seam) the host kills it at
    once and records E_RTI_TIMEOUT, retries after 1, 2 and 4 s, and ends FAILED E_RTI_TIMEOUT with
    one diagnostic per attempt, all generation 0. Each attempt reached the listener: R10's
    designator is the configured endpoint."""
    listener = SilentListener()
    try:
        session = NativeSession(tmp_path, worker(), config=config_at(listener.endpoint),
                                deadline_ns=2 * SECOND)
        session.run()
        session.check()
    finally:
        listener.close()
    assert capture_shape(session.records()[1:]) == [
        ("diagnostic", 0, 0, "E_RTI_TIMEOUT", None, None)] * 4 + [
        FOOT("FAILED", "E_RTI_TIMEOUT", 0)]
    assert session.sleeps == [1 * SECOND, 2 * SECOND, 4 * SECOND]
    assert session.summary["workers"] == 4 and len(listener.accepted) == 4
    assert exit_class(session.summary) == 5


@case("G-R10", "G-R07", "G-R14", paragraphs=("SPEC:38", "SPEC:62"))
def test_a_federation_that_does_not_exist_is_e_rti_connect_at_generation_0(tmp_path):
    """The worker under the host against a real rtinode that holds no federation: connect
    succeeds, join is refused (FederationExecutionDoesNotExist), which NAT-08 maps to
    E_RTI_CONNECT with no generation open: a generation-0 diagnostic and no generation_end; the
    host retries after 1, 2 and 4 s and ends FAILED E_RTI_CONNECT, exit class 5. The observer never
    creates the federation it was told to join (SPEC:38, the carried G-R07 clause): every one of
    the four attempts is refused the same way, and the rtinode's own log names the federation it
    did not find four times."""
    node = Rtinode(tmp_path, debug=True)
    try:
        session = NativeSession(tmp_path, worker(), config=config_at(node.endpoint))
        session.run()
        session.check()
    finally:
        node.stop()
    assert capture_shape(session.records()[1:]) == [
        ("diagnostic", 0, 0, "E_RTI_CONNECT", None, None)] * 4 + [
        FOOT("FAILED", "E_RTI_CONNECT", 0)]
    assert session.sleeps == [1 * SECOND, 2 * SECOND, 4 * SECOND]
    assert exit_class(session.summary) == 5
    refusals = node.log.read_bytes().count(f'unknown federation named "{FED}"'.encode())
    assert refusals == 4


@case("G-R14", "G-R06", paragraphs=("SPEC:277", "SPEC:62"))
def test_sigterm_while_connect_blocks_only_sets_the_flag_and_the_host_kills_at_its_deadline(
        tmp_path):
    """SPEC:277 and NAV-03: the host's orderly stop arrives while the worker is blocked inside
    connect (a listener that never answers). SIGTERM only sets the worker's flag, so the worker
    stays where it is; the host kills it at the deadline of its connect stage, records
    E_RTI_TIMEOUT, does not reconnect (a stop was asked for) and ends FAILED E_RTI_TIMEOUT."""
    listener = SilentListener()
    try:
        session = NativeSession(tmp_path, worker(), config=config_at(listener.endpoint),
                                deadline_ns=3 * SECOND)
        session.run(stop_when=lambda: len(listener.accepted) == 1)
        session.check()
    finally:
        listener.close()
    assert capture_shape(session.records()[1:]) == [
        ("diagnostic", 0, 0, "E_RTI_TIMEOUT", None, None), FOOT("FAILED", "E_RTI_TIMEOUT", 0)]
    assert session.summary["workers"] == 1 and session.sleeps == []


@case("G-R14", "G-R06", paragraphs=("SPEC:277",))
def test_sigterm_during_connect_is_honoured_once_connect_returns(tmp_path):
    """SPEC:277: the worker is held inside connect by a proxy to a real rtinode, gets SIGTERM
    there, and the proxy then lets the connection through. connect returns, the worker sees its
    flag, disconnects (it never joined) and exits 0 by itself: connect, running, disconnect,
    running on fd 3, nothing on stdout (CR-new-R7-16's first half; the second, a stop seen after
    join, is test_each_rti_exception_*[fault-join-stop])."""
    node = Rtinode(tmp_path)
    proxy = HeldProxy(node.port)
    try:
        run = DirectRun([str(worker()), *worker_args(proxy.endpoint)])
        assert proxy.accepted.wait(timeout=30)
        os.kill(run.pid, signal.SIGTERM)
        time.sleep(0.3)
        assert run.alive()
        assert stages(run.status()) == ["connect"]
        proxy.release()
        assert run.wait() == EXIT_STOPPED
    finally:
        proxy.close()
        node.stop()
    assert stages(run.status()) == ["connect", "running", "disconnect", "running"]
    assert (run.frame_bytes(), run.stderr_bytes()) == (b"", b"")


@case("G-R36", "G-R10", paragraphs=("SPEC:174", "SPEC:184"))
def test_observe_through_the_native_worker_exits_5_when_the_rti_refuses(tmp_path):
    """The carried G-R36 clause (SPEC:174), the RTI's refusals: `synapse-hla observe` with the
    native worker and a real rtinode that holds no federation ends the session FAILED
    E_RTI_CONNECT after its three retries and exits 5 (SPEC:184, OPS-02), with run.json beside
    the capture saying the capture is not complete."""
    from test_hla_cli import environment, held_to_the_session_contract, run_cli
    node = Rtinode(tmp_path)
    try:
        config = tmp_path / "config.json"
        config.write_text(json.dumps(config_at(node.endpoint)), encoding="utf-8")
        env = environment(tmp_path, extra={WORKER_VARIABLE: str(worker())})
        ran = run_cli(tmp_path, "observe", "--config", config, "--out", tmp_path / "run",
                      env=env, creates=["run"])
    finally:
        node.stop()
    assert ran.code == 5
    session = ran.summary["result"]["session"]
    assert (session["status"], session["reason_code"], session["workers"]) == (
        "FAILED", "E_RTI_CONNECT", 4)
    document = held_to_the_session_contract(tmp_path, ran, [])
    assert document["capture_complete"] is False
