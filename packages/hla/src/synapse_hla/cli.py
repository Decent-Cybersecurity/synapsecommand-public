"""The command line `synapse-hla` (R36, section 12): eight commands, their output and their exits.

THE CONTRACT
------------
`synapse-hla COMMAND [OPTIONS]`, with exactly the commands and options of the table at
SPEC:174-182: validate-config, observe, replay, verify, inspect, export-capture, demo and
self-test. Every command, and the program itself, accepts `--help`, `--version` (OPS-09 as
corrected) and `--debug`. Options take their value as the next argument (`--out DIR`); nothing
else is read as an option: no abbreviation, no `--out=DIR`, no option given twice, no value that
starts with `-`, no stray argument. `--duration-seconds` is one to five ASCII digits without a
leading zero, from 1 to 86400 (OPS-15), so `+60`, `060`, `6_0`, ` 60`, `1e3` and digits of other
scripts are refused although Python's `int` reads them. `--allow-prefix` belongs to replay and
inspect; demo and self-test refuse it by name (SPEC:184). A usage error is an E_CONFIG
diagnostic with the argument as its path, exit 2, never a parser's own text (OPS-02).

stdout carries exactly one JSON object per command, the summary of
`local_schemas/cli-summary.schema.json`, except export-capture, whose result is the `--out` file
and the exit code alone (OPS-09). stderr carries one JSON diagnostic per line
(`local_schemas/cli-diagnostic.schema.json`). Both are ASCII: `json` itself escapes every
character outside the printable ASCII range when it is told to write ASCII (the C0 controls, DEL
and everything past it), so a capture's strings and a hostile argument reach the terminal as data
(R40); `message` and `path` come already bounded and made safe from `HlaError` (CR-L01,
CR-R1-04), and an argument that becomes a path goes through `errors.safe_text` here (an empty
stray argument is named `ARGUMENT`). No traceback is written unless `--debug` is given, except for
a defect: an exception that is not `HlaError` escapes with Python's own traceback and exit status
1, whatever `--debug` says (CR-R3-07, CR-R4-11).

Exit codes follow OPS-02: each E_ code has a class (`errors.EXIT_CLASS`: 2 configuration and
invocation, 3 data, 4 dependency, 5 RTI, 6 resource and I/O); the exit is the highest class
among the command's terminal failures, else 3 when an E_ diagnostic was emitted and 0 otherwise;
W_ codes never change it. verify, inspect and export-capture judge a capture: 0 only for a valid
COMPLETE capture, 3 for any other verdict whatever its code (OPS-16), 6 when the file cannot be
read. A command stopped by SIGINT or SIGTERM stops at its next safe point (before the next capture
line it reads, or between its steps: the handler only notes the signal), removes what it created
and exits 128 plus the signal number (130, 143) with nothing on stdout; observe stops its session
in order once one exists, as a stop is part of its operation (R14, OPS-25), and a stop before
that (during its own configuration and FOM pre-flight) exits the same way as the other commands
(CR-R6-05, final review finding F-host-02). Once a command has its exit code, a later SIGINT or
SIGTERM changes nothing: the program ignores both from then until it ends, so a summary that says
0 is never followed by a death by signal (CR-R6-F1, OPS-02).

WHAT EACH COMMAND DOES
----------------------
- validate-config: the configuration file by R07's rules (`config.load_config_bytes`) and the
  five FOM modules of `SYNAPSE_HLA_FOM_DIR` against the packaged pins (OPS-11). Both run; both
  modes are accepted (OPS-14). It starts no process.
- observe: the two checks of validate-config first, both run and both reported, the exit the
  higher class (CR-R6-F4, SPEC:184), before anything is created; a `mode` demo configuration is
  refused there (E_CONFIG at `/mode`, OPS-14). Then the host runs in a child process of its own
  process group, and this process stays its thin parent (OPS-23): it reads the host's resident
  memory every 250 ms and, above 512 MiB, stops the host, kills the workers the host reported
  (each in a process group of its own, CR-new-R5-04) and the host's group, writes E_LIMIT and
  exits 6, leaving an incomplete capture as the evidence. SIGINT and SIGTERM to this process are
  passed on to the host once its session is running (before that, the host's pre-flight is not
  interrupted: the stop reaches the session as soon as its first worker starts). The host writes
  `run.json` beside the three run files when the session ends (OPS-10: audit times from the wall
  clock), with `capture_complete` true for a COMPLETE footer and false otherwise (CR-R6-F8). If
  this process is killed from outside (SIGKILL, a closed terminal), the host sees its parent
  change at its next poll tick and stops the session in order, as a SIGTERM would; it then writes
  no `run.json`, whose absence marks such a run (CR-R6-F2). A host that ends without a result
  (killed from outside, or a defect of its own) makes this process kill the workers it was told
  about and fail as a defect, naming how the host ended: exit status 1 and a traceback (CR-R6-F3).
- replay: `replay.replay_with` into the new `--out`, with `run.json` written last into the same
  directory (no clock: the whole directory is byte-identical across repeats, OPS-10); a prefix
  replay (`--allow-prefix` on an incomplete or FAILED capture) exits 3 and its evidence is
  PREFIX_ONLY, never PASS (R17).
- verify and inspect: one verified pass over the capture; the summary lists the codes of the
  captured diagnostic frames, which do not change the exit (OPS-16). inspect adds the
  `_inspection` summary (OPS-26) for a COMPLETE capture, and with `--allow-prefix` for the
  verified prefix of an incomplete or FAILED one.
- export-capture: verify, then copy the verified file byte for byte to `--out`, created
  exclusively; a COMPLETE capture exits 0, a FAILED one is copied and exits 3, an invalid or
  incomplete one is refused and `--out` is never created (OPS-16). It builds no HLA data and
  sends nothing anywhere (SPEC:166).
- demo: the FOM pins first (E_DEPENDENCY_PIN, exit 4, before `--out` exists, OPS-11); then the
  directory, and the worker, rtinode and the synthetic publisher are looked for (OPV-04,
  CR-L16), the worker and the publisher each asked for its exact `--version` line. Any of them
  missing: `DIR/demo.json` with status BLOCKED, exit 4 (OPS-18). Otherwise `_demo.run_demo`
  runs the isolated exercise of R38 and R39 into DIR (main/, main-replay/, no-time/,
  no-time-replay/, each observer session in a host process of its own, forked here as observe
  forks its host) and `DIR/demo.json` says PASS or FAIL with every checkpoint (OPS-13). Exit 0
  for PASS; for FAIL the highest class among the catalogue codes it met (a session's terminal
  codes; E_RTI_CONNECT for an rtinode or publisher that failed; E_DEPENDENCY_PIN for module
  bytes the publisher refused), at least 3 when a semantic checkpoint failed and at least 6 when
  something it started was left behind. A stop signal stops everything it started, in order,
  and removes DIR (130, 143), as for the other commands.
- self-test: `_selftest.run` into the new `--out`: `self-test.json` and `fixture-replay/`
  (OPS-26). Exit 0 when every case passed; 4 when the pin check is BLOCKED (no
  `SYNAPSE_HLA_FOM_DIR`) or refused the modules; 3 when another case failed; the highest wins.

Output paths (OPS-17): only the last component of `--out` is judged; it must not exist, not even
as a dangling symbolic link (E_OUTPUT_EXISTS, exit 2); its parent must exist (E_IO otherwise).
Directories are made 0700 and files are created inside them by fixed names, exclusively, without
following a link, 0600 (OPS-08: no name is ever taken from a configuration or a capture). No
command writes anywhere else. Paths are local file names; nothing is downloaded (R36).

This is the only module that reads `sys.argv` and the environment variables of D-07
(`SYNAPSE_HLA_FOM_DIR`, `SYNAPSE_HLA_WORKER`, `SYNAPSE_HLA_RTINODE`, `SYNAPSE_HLA_PUBLISHER`);
the host, the demo and the self-test get them from here. It never builds a `host.HostSeams` or
a `_demo.DemoSeams`: no option, configuration key or environment variable reaches a limit or a
timing value (OPS-21, D-09).
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import re
import select
import signal
import stat
import sys
import threading
import time
import traceback
from dataclasses import dataclass

from synapse_hla import (
    _demo, _fom, _inspection, _runfile, _schema, _selftest, canonical, capture, config, errors,
    host,
)
from synapse_hla.replay import FILES as REPLAY_FILES
from synapse_hla.replay import OUTPUT_DIR as REPLAY_OUTPUT_DIR
from synapse_hla.replay import RUN_FILE, replay_with
from synapse_hla.errors import HlaError
from synapse_hla.limits import V1 as LIMITS

PROGRAM = "synapse-hla"
#: OPS-09: what `--version` prints, exactly.
VERSION_LINE = b'{"name":"synapse-hla","version":"1.0.0","profile":"SC-HLA-RPR2-OBS-1"}\n'
SUMMARY_VERSION = 1
DIAGNOSTIC_VERSION = 1

VALIDATE_CONFIG = "validate-config"
OBSERVE = "observe"
REPLAY = "replay"
VERIFY = "verify"
INSPECT = "inspect"
EXPORT_CAPTURE = "export-capture"
DEMO = "demo"
SELF_TEST = "self-test"

CONFIG = "--config"
OUT = "--out"
CAPTURE = "--capture"
DURATION = "--duration-seconds"
ALLOW_PREFIX = "--allow-prefix"
HELP = "--help"
VERSION = "--version"
DEBUG = "--debug"
#: CR-L01 has the argument's name as a CLI path; a missing or unknown command has this one.
COMMAND_PATH = "COMMAND"
#: The path of a stray argument that is empty and so has no name of its own (CR-R6-F9).
ARGUMENT_PATH = "ARGUMENT"


@dataclass(frozen=True)
class Command:
    """One row of SPEC:174-182: the options that take a value, the required ones, the flags."""

    values: tuple[str, ...]
    required: tuple[str, ...]
    flags: tuple[str, ...] = ()


#: The command table of SPEC:174-182 and the options of SPEC:184, and nothing more (OPS-21: no
#: option reaches a limit or a timing value).
COMMANDS = {
    VALIDATE_CONFIG: Command((CONFIG,), (CONFIG,)),
    OBSERVE: Command((CONFIG, OUT, DURATION), (CONFIG, OUT)),
    REPLAY: Command((CAPTURE, OUT), (CAPTURE, OUT), (ALLOW_PREFIX,)),
    VERIFY: Command((CAPTURE,), (CAPTURE,)),
    INSPECT: Command((CAPTURE,), (CAPTURE,), (ALLOW_PREFIX,)),
    EXPORT_CAPTURE: Command((CAPTURE, OUT), (CAPTURE, OUT)),
    DEMO: Command((OUT,), (OUT,)),
    SELF_TEST: Command((OUT,), (OUT,)),
}
#: SPEC:184: these two refuse --allow-prefix by name.
REFUSE_ALLOW_PREFIX = (DEMO, SELF_TEST)
#: SPEC:184 and OPS-15: --duration-seconds.
DEFAULT_DURATION_SECONDS = 60
MAX_DURATION_SECONDS = 86_400
_DURATION_FORM = re.compile(r"[1-9][0-9]{0,4}")

#: D-07 and OPV-04: the variables this module reads.
FOM_DIR_VARIABLE = host.FOM_DIR_VARIABLE
WORKER_VARIABLE = host.WORKER_VARIABLE
RTINODE_VARIABLE = _demo.RTINODE_VARIABLE
RTINODE_NAME = _demo.RTINODE_NAME
#: OPV-04: rtinode's one fixed place when the variable is not set, beside the worker's.
RTINODE_LOCATION = _demo.RTINODE_LOCATION
#: CR-L16: the demo's synthetic publisher, found like the worker.
PUBLISHER_VARIABLE = _demo.PUBLISHER_VARIABLE
PUBLISHER_NAME = _demo.PUBLISHER_NAME

#: Paths of the API's refusals, as the command line names its arguments (CR-L01, CR-R2-17).
_API_PATHS = {capture.CAPTURE_PATH: CAPTURE, REPLAY_OUTPUT_DIR: OUT, host._writer.OUTPUT_DIR: OUT}
DEMO_FILE = "demo.json"
SELF_TEST_FILE = "self-test.json"
DEMO_SCHEMA = "demo.schema.json"
#: A command stopped by SIGINT or SIGTERM exits 128 plus the signal number.
_SIGNAL_EXIT_BASE = 128
_STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW | _CLOEXEC
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | _CLOEXEC
_READ_CHUNK = 1 << 16
#: The most the observe parent keeps of what its host has not finished saying; the host says
#: little (worker pids, its stderr lines, one summary), so more is a defect, not data.
_HOST_MESSAGE_BYTES = 1 << 24
_MILLISECOND = 1_000_000

_TERMINAL_MESSAGE = "the session ended with this terminal failure"
_INCOMPLETE_CAPTURE = "the capture has no footer: it could not be completed"
_FAILED_CAPTURE = "the capture ends FAILED; it is not complete evidence"
_PREFIX_REPLAY = "a prefix replay: the capture ends FAILED and every output is incomplete"
_HOST_RSS = "the host's resident memory passed its limit; the host and its workers were killed"
_FORK = "the host process could not be started"
_MODE_DEMO = "observe joins an existing federation; a mode demo configuration runs only " \
             "through the demo command"
_RTINODE_ABSENT = "rtinode is missing or is not an executable file"
_RTINODE_RELATIVE = "SYNAPSE_HLA_RTINODE is not an absolute path"
_PUBLISHER_RELATIVE = "SYNAPSE_HLA_PUBLISHER is not an absolute path"
_PUBLISHER_ABSENT = "the synthetic publisher is missing or does not answer --version as this " \
                    "build expects"
_FOM_NOT_SET = "SYNAPSE_HLA_FOM_DIR is not set, so the FOM pin check is BLOCKED"


# --- help ------------------------------------------------------------------------------------------

_DISTINCTION = """\
export-capture copies only a verified original capture, byte for byte. It does not edit,
re-encode or re-export HLA data: it constructs no HLA packets and replays no traffic into an RTI.
A CDM record alone is not enough to regenerate its original federate session; keep the capture
and its outputs together through the run manifest run.json.
"""

_PROGRAM_HELP = f"""\
usage: {PROGRAM} [--debug] COMMAND [OPTIONS]
       {PROGRAM} --help | --version

The receive-only HLA observer of profile SC-HLA-RPR2-OBS-1: it subscribes to four attributes
of RPR FOM 2.0 PhysicalEntity objects in an existing federation, keeps the callbacks it receives
in a hash-chained capture, and replays captures offline into CDM Entity records. observe needs
the native worker sc-hla-federate, built from the package's native sources against the pinned
OpenRTI, beside the installed package or named by SYNAPSE_HLA_WORKER.

commands:
  validate-config --config FILE
      check a configuration offline, and the FOM modules against the packaged pins
  observe --config FILE --out DIR [--duration-seconds N]
      join an existing federation and record until SIGINT, SIGTERM, the duration
      (N from 1 to 86400 seconds, default 60) or a failure
  replay --capture FILE --out DIR [--allow-prefix]
      verify a capture and project its frames offline into a new directory
  verify --capture FILE
      check schema, canonical form, hash chain, lifecycle framing and footer
  inspect --capture FILE [--allow-prefix]
      verify, and summarize counts, profile, time coverage and classes
  export-capture --capture FILE --out FILE
      verify, then copy the capture byte for byte
  demo --out DIR
      the isolated synthetic reference run: a local rtinode, the synthetic
      publisher and two observer sessions, checked and replayed
  self-test --out DIR
      the packaged fixtures, offline, without an RTI

{_DISTINCTION}
options take their value as the next argument (--out DIR); no other spelling and no
abbreviation is read. Every command also accepts --help, --version and --debug. Paths are local
file names: a URL is read as a file name and nothing is downloaded. An --out must not exist
(not even as a symbolic link) and its parent must.

stdout carries one JSON summary per command (export-capture prints nothing), stderr one JSON
diagnostic per line; a traceback appears only with --debug, or for a defect of this program.

exit codes: 0 done without an E_ diagnostic; 2 invocation or configuration error; 3 invalid
data, or a completed capture or replay with E_ diagnostics; 4 missing dependency or unavailable
reference evidence; 5 RTI connection, profile or runtime error; 6 resource or I/O failure;
130 or 143 stopped by SIGINT or SIGTERM before the command finished (observe stops its session
in order once one exists, and a stop before that, during its own configuration and FOM
pre-flight, exits 130 or 143 like the other commands; once a command has its result, a further
signal changes nothing); 1 a defect of this program.

environment: SYNAPSE_HLA_FOM_DIR names the directory of the five RPR FOM modules, which are
checked against the packaged pins before use; SYNAPSE_HLA_WORKER, SYNAPSE_HLA_RTINODE and
SYNAPSE_HLA_PUBLISHER name the worker, rtinode and the synthetic publisher by absolute path,
otherwise they are looked for beside the installed package (never on PATH).
"""

_COMMAND_HELP = {
    VALIDATE_CONFIG: f"""\
usage: {PROGRAM} validate-config --config FILE

Check the configuration FILE (strict JSON, at most 64 KiB, config.schema.json and the semantic
rules) and the five FOM modules of SYNAPSE_HLA_FOM_DIR against the packaged pins. Both modes are
accepted. Exit 0, 2 (configuration), 4 (FOM modules) or 6 (FILE unreadable); the highest wins.

{_DISTINCTION}""",
    OBSERVE: f"""\
usage: {PROGRAM} observe --config FILE --out DIR [--duration-seconds N]

Check the configuration FILE and the FOM modules as validate-config does (both are reported; the
higher class wins), then join the existing federation the configuration names (mode existing; a
mode demo configuration is refused) and record into the new directory DIR: capture.jsonl,
observations.jsonl, diagnostics.jsonl and run.json. The session ends on SIGINT or SIGTERM (an
orderly stop), after N seconds from the capture header (1 to 86400, default 60), or on a failure.
Exit 0, 2, 3, 4, 5 or 6. If this command is killed from outside, the session still stops in
order, but run.json is not written. A run directory without run.json marks a session whose
command did not see its end: a command killed from outside, a host that ended without a result
or was stopped for its memory, or a run.json that could not be written.

{_DISTINCTION}""",
    REPLAY: f"""\
usage: {PROGRAM} replay --capture FILE --out DIR [--allow-prefix]

Verify the whole capture, then reduce and project it offline into the new directory DIR:
capture.jsonl (a byte copy), observations.jsonl, diagnostics.jsonl and run.json. An incomplete or
FAILED capture is refused unless --allow-prefix is given; a prefix replay marks every output
incomplete and exits 3. Exit 0, 2, 3, 4 (dependency pins differ) or 6.

{_DISTINCTION}""",
    VERIFY: f"""\
usage: {PROGRAM} verify --capture FILE

Check the capture's schemas, canonical serialization, hash chain, lifecycle framing and footer.
Exit 0 for a valid COMPLETE capture, 3 for any other verdict, 6 when FILE cannot be read.

{_DISTINCTION}""",
    INSPECT: f"""\
usage: {PROGRAM} inspect --capture FILE [--allow-prefix]

Verify the capture and summarize its counts, profile, generations, events, reported classes,
captured diagnostics and time coverage; with --allow-prefix also the verified prefix of an
incomplete or FAILED capture. Exit 0 for a valid COMPLETE capture, 3 otherwise, 6 when FILE
cannot be read.

{_DISTINCTION}""",
    EXPORT_CAPTURE: f"""\
usage: {PROGRAM} export-capture --capture FILE --out FILE

Verify the capture, then copy it byte for byte to the new file --out. Nothing is printed on
stdout. Exit 0 for a COMPLETE capture, 3 for a FAILED one (copied) or an invalid or incomplete
one (refused, --out not created), 2 when --out exists, 6 for an I/O failure.

{_DISTINCTION}""",
    DEMO: f"""\
usage: {PROGRAM} demo --out DIR

The isolated synthetic public-reference run. After checking the FOM pins it starts its own
rtinode on 127.0.0.1 and a port it chooses, and runs the synthetic publisher, which creates a
federation SC_DEMO_<16 hex digits> from the five pinned modules, and the observer twice: main/
with the external elapsed time of examples/config-demo.json and no-time/ with time policy none.
Each capture is replayed offline into main-replay/ and no-time-replay/. DIR/demo.json records
the ports, names, process ids, the module digests the publisher used, every semantic
checkpoint and the clean-up; everything it started is stopped by process id. OpenRTI is the
tested reference; no customer simulator and no second RTI implementation is tested. Without
the worker, rtinode or the publisher, demo.json says BLOCKED and the exit is 4. Exit 0 when
every checkpoint passed, otherwise 3 (a checkpoint failed), 4, 5 (an RTI process failed) or
6 (something it started was left behind). --allow-prefix is refused.

{_DISTINCTION}""",
    SELF_TEST: f"""\
usage: {PROGRAM} self-test --out DIR

Run the packaged fixtures offline, without an RTI or pytest: the attribute vectors, the geodesy
and identity vectors, both example configurations, the packaged schemas and fixtures, the FOM pin
check (BLOCKED without SYNAPSE_HLA_FOM_DIR), and the replay of the packaged capture against the
expected observations. Writes DIR/self-test.json and DIR/fixture-replay/. Exit 0, 3 (a case
failed) or 4 (the pin check is BLOCKED or refused the modules). --allow-prefix is refused.

{_DISTINCTION}""",
}


# --- output ----------------------------------------------------------------------------------------

def _json_line(value) -> bytes:
    # ASCII only, and nothing a terminal acts on: with ensure_ascii, json escapes every character
    # outside ' ' to '~' (the C0 controls, DEL and everything past it), so no other step is needed.
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode("ascii")


def _write(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except BrokenPipeError:
            # Nobody reads any more; the exit code is still the result.
            return
        view = view[written:]


class _Output:
    """stdout and stderr of one command, and every code it has reported so far."""

    def __init__(self) -> None:
        self.debug = False
        self.codes: set[str] = set()
        #: Where stderr goes: written at once, or handed to a parent (the observe host).
        self.stderr = lambda data: _write(2, data)

    def diagnostic(self, code: str, message: str, path: str | None, *, error=None) -> None:
        line = {"cli_diagnostic_version": DIAGNOSTIC_VERSION, "severity": errors.severity(code),
                "code": code, "message": message, "path": path}
        self.stderr(_json_line(line))
        self.codes.add(code)
        if self.debug and error is not None:
            text = "".join(traceback.format_exception(error))
            self.stderr(text.encode("ascii", "backslashreplace"))

    def error(self, error: HlaError) -> None:
        self.diagnostic(error.code, error.message, _API_PATHS.get(error.path, error.path),
                        error=error)

    def summary(self, command: str | None, exit_code: int, result, codes=()) -> None:
        self.codes.update(codes)
        _write(1, _json_line({"cli_summary_version": SUMMARY_VERSION, "command": command,
                              "exit_code": exit_code, "codes": sorted(self.codes),
                              "result": result}))


def _exit_code(terminal, errors_emitted: bool) -> int:
    """OPS-02: the highest class among the terminal failures, else 3 with an E_ diagnostic."""
    classes = [errors.EXIT_CLASS[code] for code in terminal]
    if classes:
        return max(classes)
    return 3 if errors_emitted else 0


# --- the argument vector ---------------------------------------------------------------------------

class _Usage(Exception):
    def __init__(self, command: str | None, path: str, message: str) -> None:
        super().__init__(message)
        self.command = command
        self.path = path
        self.message = message


class _Shown(Exception):
    """--help or --version: print `text` and exit 0."""

    def __init__(self, text: bytes) -> None:
        super().__init__("shown")
        self.text = text


@dataclass(frozen=True)
class Request:
    command: str
    options: dict
    flags: frozenset
    debug: bool

    @property
    def duration_seconds(self) -> int:
        return self.options.get(DURATION, DEFAULT_DURATION_SECONDS)


def _token(text: str) -> str:
    # An argument that becomes a diagnostic's path is input: made safe as every producer makes it
    # (CR-R0-04, CR-R1-04), then escaped on output like everything else.
    return errors.safe_text(text)


def parse(argv) -> Request:
    """The request of an argument vector (the program's arguments, without the program name).

    Raises `_Usage` for anything SPEC:174-184 does not give, and `_Shown` for --help and
    --version; see the module text for the grammar.
    """
    tokens = list(argv)
    debug = False
    index = 0
    while index < len(tokens) and tokens[index].startswith("-"):
        token = tokens[index]
        if token == HELP:
            raise _Shown(_PROGRAM_HELP.encode("ascii"))
        if token == VERSION:
            raise _Shown(VERSION_LINE)
        if token == DEBUG:
            debug = True
            index += 1
            continue
        raise _Usage(None, _token(token), "the program does not take this option")
    if index == len(tokens):
        raise _Usage(None, COMMAND_PATH, "no command was given")
    name = tokens[index]
    if name not in COMMANDS:
        raise _Usage(None, COMMAND_PATH, "there is no such command")
    command = COMMANDS[name]
    options: dict = {}
    flags: set = set()
    index += 1
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == HELP:
            raise _Shown(_COMMAND_HELP[name].encode("ascii"))
        if token == VERSION:
            raise _Shown(VERSION_LINE)
        if token == DEBUG:
            debug = True
            continue
        if token == ALLOW_PREFIX and name in REFUSE_ALLOW_PREFIX:
            raise _Usage(name, ALLOW_PREFIX, f"{name} refuses --allow-prefix")
        if token in command.flags:
            if token in flags:
                raise _Usage(name, token, "the option is given twice")
            flags.add(token)
            continue
        if token in command.values:
            if token in options:
                raise _Usage(name, token, "the option is given twice")
            if index == len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                raise _Usage(name, token, "the option needs a value as the next argument")
            options[token] = tokens[index]
            index += 1
            continue
        if token.startswith("-"):
            raise _Usage(name, _token(token), f"{name} does not take this option")
        raise _Usage(name, _token(token) or ARGUMENT_PATH,
                     f"{name} takes no argument without an option")
    for required in command.required:
        if required not in options:
            raise _Usage(name, required, "a required option is missing")
    if DURATION in options:
        text = options[DURATION]
        if _DURATION_FORM.fullmatch(text) is None or int(text) > MAX_DURATION_SECONDS:
            raise _Usage(name, DURATION, "the duration is a whole number of seconds from 1 to "
                                         "86400, in ASCII digits without a sign or leading zero")
        options[DURATION] = int(text)
    return Request(name, options, frozenset(flags), debug)


# --- signals ---------------------------------------------------------------------------------------

class _Interrupted(BaseException):
    """SIGINT or SIGTERM reached a command that stops where it is (everything but observe)."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


#: The first stop signal of this command, once one arrived.
_STOPPED: dict = {"signum": None}


def _note_stop(signum, _frame) -> None:
    # The handler only notes the stop. Raising from it would end the command wherever it happens
    # to be (inside a library's callback, between creating a file and recording it) and leave
    # behind what the command made; the command stops instead at its next safe point.
    if _STOPPED["signum"] is None:
        _STOPPED["signum"] = signum


def check_stop() -> None:
    """The safe point of an offline command: raises `_Interrupted` once SIGINT or SIGTERM has
    arrived. Called before each capture line a command reads, and between the steps of the
    others, inside the code that removes what the command made."""
    if _STOPPED["signum"] is not None:
        raise _Interrupted(_STOPPED["signum"])


@contextlib.contextmanager
def _stoppable(*, program: bool):
    """SIGTERM does what SIGINT does (SPEC:184): both make the command stop at its next safe
    point (`check_stop`), so that every command's own cleanup runs and none prints a traceback.
    Only the main thread can have handlers.

    When the block ends the command has its exit code, and nothing may change it any more
    (CR-R6-F1). For the program itself (`program`: the console script and `python -m`) both
    signals are then ignored until the process ends: Python's own handlers would end it by the
    signal after its summary said otherwise, and a Python-level handler is no shield either,
    because the interpreter resets those to the default while it shuts down. A caller that runs
    a command in its own process gets its handlers back."""
    saved = {}
    _STOPPED["signum"] = None
    if _main_thread():
        saved = {signum: signal.signal(signum, _note_stop) for signum in _STOP_SIGNALS}
    try:
        yield
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, signal.SIG_IGN if program else handler)


def _main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


# --- files -----------------------------------------------------------------------------------------

def _name(path: str, option: str) -> bytes:
    try:
        name = os.fsencode(path)
    except UnicodeEncodeError:
        raise HlaError(errors.E_IO, option, "the path cannot name a file") from None
    if b"\x00" in name:
        raise HlaError(errors.E_IO, option, "the path cannot name a file")
    return name


def _read_bounded(path: str, option: str, limit: int) -> bytes:
    """At most `limit` + 1 bytes of the regular file `path`: one more than a reader accepts, so
    that the reader sees the excess and refuses it by its own rule."""
    name = _name(path, option)
    try:
        fd = os.open(name, _READ_FLAGS)
    except OSError:
        raise HlaError(errors.E_IO, option, "the file cannot be opened") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise HlaError(errors.E_IO, option, "the file is not a readable regular file")
        chunks = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise HlaError(errors.E_IO, option, "the file cannot be read") from None
    finally:
        os.close(fd)
    return b"".join(chunks)


def _write_all(fd: int, data: bytes, option: str) -> None:
    view = memoryview(data)
    try:
        while view:
            view = view[os.write(fd, view):]
    except OSError:
        raise HlaError(errors.E_IO, option, "the output cannot be written") from None


def _create(directory_fd: int, name: str, data: bytes, option: str) -> None:
    """A file of fixed name in an open directory: exclusive, no link followed, 0600, synced."""
    try:
        fd = os.open(name, _CREATE_FLAGS, _FILE_MODE, dir_fd=directory_fd)
    except OSError:
        raise HlaError(errors.E_IO, option, "the output file cannot be created") from None
    try:
        _write_all(fd, data, option)
        os.fsync(fd)
    except OSError:
        raise HlaError(errors.E_IO, option, "the output cannot be written") from None
    finally:
        os.close(fd)


class _Directory:
    """An output directory this command makes (OPS-17) and what it puts there, so that a
    command that does not finish can take back exactly what it made."""

    def __init__(self, path: str) -> None:
        self.target = _name(path, OUT)
        try:
            os.mkdir(self.target, _DIRECTORY_MODE)
        except FileExistsError:
            raise HlaError(errors.E_OUTPUT_EXISTS, OUT,
                           "the output directory already exists") from None
        except OSError:
            raise HlaError(errors.E_IO, OUT, "the output directory cannot be created") from None
        try:
            self.fd = os.open(self.target, _DIRECTORY_FLAGS)
        except OSError:
            with contextlib.suppress(OSError):
                os.rmdir(self.target)
            raise HlaError(errors.E_IO, OUT, "the output directory cannot be opened") from None
        self.files: list[str] = []
        self.replay_dirs: list[str] = []

    def create(self, name: str, data: bytes) -> None:
        self.files.append(name)
        _create(self.fd, name, data, OUT)

    def path(self, name: str) -> bytes:
        return os.path.join(self.target, os.fsencode(name))

    def close(self) -> None:
        os.close(self.fd)

    def discard(self) -> None:
        # Only what this command made, by its fixed names; then the directory, which rmdir removes
        # only when nothing else appeared in it. The exception that brought us here matters more
        # than a failure to tidy up.
        for name in self.replay_dirs:
            with contextlib.suppress(OSError):
                inner = os.open(name, _DIRECTORY_FLAGS, dir_fd=self.fd)
                try:
                    for file in REPLAY_FILES + (RUN_FILE,):
                        with contextlib.suppress(OSError):
                            os.unlink(file, dir_fd=inner)
                finally:
                    os.close(inner)
                os.rmdir(name, dir_fd=self.fd)
        for name in self.files:
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=self.fd)
        with contextlib.suppress(OSError):
            os.close(self.fd)
        with contextlib.suppress(OSError):
            os.rmdir(self.target)


def _synapse_cdm_version() -> str | None:
    try:
        return importlib.metadata.version("synapse-cdm")
    except importlib.metadata.PackageNotFoundError:
        return None


# --- validate-config -------------------------------------------------------------------------------

def _validate_config(request: Request, out: _Output) -> int:
    terminal = []
    checked = {"status": "UNREADABLE", "sha256": None, "session_id": None, "mode": None,
               "profile_declaration": None}
    try:
        data = _read_bounded(request.options[CONFIG], CONFIG, LIMITS.config_file_bytes)
        try:
            document = config.load_config_bytes(data)
        except HlaError:
            checked["status"] = "INVALID"
            raise
        checked = {"status": "VALID",
                   "sha256": canonical.sha256_hex(canonical.canonical_bytes(document)),
                   "session_id": document["session_id"], "mode": document["mode"],
                   "profile_declaration": document["profile_declaration"]}
    except HlaError as error:
        out.error(error)
        terminal.append(error.code)
    dependencies = {"status": "PASS", "fom_sha256": None}
    try:
        modules = _fom.check_fom_modules(os.environ.get(FOM_DIR_VARIABLE, ""))
        dependencies["fom_sha256"] = {module.name: module.sha256 for module in modules}
    except HlaError as error:
        out.error(error)
        terminal.append(error.code)
        dependencies["status"] = "FAIL"
    check_stop()
    code = _exit_code(terminal, False)
    out.summary(VALIDATE_CONFIG, code, {"config": checked, "dependencies": dependencies})
    return code


# --- observe ---------------------------------------------------------------------------------------

def _observe(request: Request, out: _Output) -> int:
    started_us = time.time_ns() // 1000
    # CR-R6-F4: validate-config's two checks, in its order, both run and both reported, so that
    # competing failures give the higher class (SPEC:184) whichever command meets them. The
    # host's own pre-flight (the FOM modules again, then the worker) follows in the session.
    terminal = []
    try:
        data = _read_bounded(request.options[CONFIG], CONFIG, LIMITS.config_file_bytes)
        document = config.load_config_bytes(data)
        if document["mode"] == config.DEMO:
            # OPS-14: bundled-fom-created would claim module evidence observe never produced.
            raise HlaError(errors.E_CONFIG, "/mode", _MODE_DEMO)
    except HlaError as error:
        out.error(error)
        terminal.append(error.code)
    try:
        _fom.check_fom_modules(os.environ.get(FOM_DIR_VARIABLE, ""))
    except HlaError as error:
        out.error(error)
        terminal.append(error.code)
    if terminal:
        code = _exit_code(terminal, False)
        out.summary(OBSERVE, code, {"session": None, "run_json": False, "host": None})
        return code
    check_stop()
    environ = dict(os.environ)
    return _run_host(document, request.options[OUT], request.duration_seconds, environ,
                     started_us, out)


def _send(fd: int, message: dict) -> None:
    """One message of the host to its parent. A parent that is gone hears nothing; the session
    notices that at its next poll tick and stops in order (CR-R6-F2)."""
    data = _json_line(message)
    with contextlib.suppress(OSError):
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]


def _run_host(document: dict, out_path: str, duration_seconds: int, environ: dict,
              started_us: int, out: _Output) -> int:
    # The host's parent as the host must keep seeing it: a change means this process is gone.
    command = os.getpid()
    read_fd, write_fd = os.pipe()
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _STOP_SIGNALS)
    try:
        pid = os.fork()
    except OSError:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        os.close(read_fd)
        os.close(write_fd)
        out.diagnostic(errors.E_IO, _FORK, None)
        out.summary(OBSERVE, errors.EXIT_CLASS[errors.E_IO], {"session": None, "run_json": False,
                                                             "host": None})
        return errors.EXIT_CLASS[errors.E_IO]
    if pid == 0:
        os.close(read_fd)
        _host_process(document, out_path, duration_seconds, environ, started_us, write_fd,
                      out.debug, command)
    os.close(write_fd)
    with contextlib.suppress(OSError):
        os.setpgid(pid, pid)
    try:
        return supervise_host(pid, read_fd, out, unblock=previous_mask)
    finally:
        os.close(read_fd)


def _host_process(document: dict, out_path: str, duration_seconds: int, environ: dict,
                  started_us: int, write_fd: int, debug: bool, command: int):
    """The child: the host of OPS-23, in a process group of its own, `command` its parent.
    Never returns."""
    status = 1
    try:
        with contextlib.suppress(OSError):
            os.setpgid(0, 0)
        # The fork happened with both stop signals blocked, and they stay blocked until the
        # session's own handlers exist (`host._signals` unblocks them then): a stop sent to this
        # process in that window - the demo's SIGTERM right after the fork, say - stays pending
        # and reaches the session, which stops in order (CR-R8-06), where an ignored one would
        # be lost. Their action meanwhile is the default, not the command's Python handlers,
        # which are not this process's to run.
        signal.pthread_sigmask(signal.SIG_BLOCK, _STOP_SIGNALS)
        for signum in _STOP_SIGNALS:
            signal.signal(signum, signal.SIG_DFL)
        out = _Output()
        out.debug = debug
        out.stderr = lambda data: _send(write_fd, {"stderr": data.decode("ascii")})
        result = _host_session(document, out_path, duration_seconds, environ, started_us,
                               write_fd, out, command)
        if result is not None:
            _send(write_fd, {"result": result})
        status = 0
    except BaseException:
        # A defect of the host (CR-R3-07): its traceback, whatever --debug says, and status 1.
        _send(write_fd, {"stderr": traceback.format_exc()})
    finally:
        os._exit(status)


def _host_session(document: dict, out_path: str, duration_seconds: int, environ: dict,
                  started_us: int, write_fd: int, out: _Output, command: int) -> dict | None:
    """The session and its run.json; the result for the parent, or None when the parent is gone
    (nobody to report to; CR-R6-F2)."""
    def on_worker(pid: int, running: bool) -> None:
        _send(write_fd, {"worker": pid, "running": running})

    try:
        summary = host.run_session(document, out_path, environ=environ,
                                   duration_ns=duration_seconds * 1_000_000_000,
                                   on_worker=on_worker, parent_pid=command)
    except HlaError as error:
        out.error(error)
        return {"exit_code": errors.EXIT_CLASS[error.code], "codes": sorted(out.codes),
                "result": {"session": None, "run_json": False, "host": "EXITED"}}
    if os.getppid() != command:
        # CR-R6-F2: the command was killed from outside and the session stopped in order. run.json
        # is the command's account of a run it saw to the end; this one it did not see, so there
        # is none, and its absence is the mark of such a run.
        return None
    terminal = list(summary["terminal_codes"])
    for code in terminal:
        out.diagnostic(code, _TERMINAL_MESSAGE if summary["status"] != host.INCOMPLETE
                       else _INCOMPLETE_CAPTURE, None)
    run_json = True
    try:
        data = _runfile.observe_run(summary, document, _fom.header_pins(),
                                    started_at_us=started_us,
                                    ended_at_us=time.time_ns() // 1000,
                                    synapse_cdm_version=_synapse_cdm_version())
        _write_run_file(out_path, data)
    except HlaError as error:
        out.error(error)
        terminal.append(error.code)
        run_json = False
    codes = set(out.codes) | set(summary["errors"]) | set(summary["warnings"])
    return {"exit_code": _exit_code(terminal, bool(summary["errors"])), "codes": sorted(codes),
            "result": {"session": summary, "run_json": run_json, "host": "EXITED"}}


def _write_run_file(out_path: str, data: bytes) -> None:
    target = _name(out_path, OUT)
    try:
        directory = os.open(target, _DIRECTORY_FLAGS)
    except OSError:
        raise HlaError(errors.E_IO, OUT, "run.json cannot be written") from None
    try:
        _create(directory, RUN_FILE, data, OUT)
    finally:
        os.close(directory)


class HostEndedWithoutResult(RuntimeError):
    """The observe host ended without telling its result: killed from outside, or a defect of its
    own (whose traceback it passed on first). A defect of the command line's (CR-R6-F3)."""


def _wait_status(status: int) -> str:
    """How a process ended, from its `os.waitpid` status."""
    if os.WIFSIGNALED(status):
        number = os.WTERMSIG(status)
        try:
            name = signal.Signals(number).name
        except ValueError:
            name = "a signal without a name"
        return f"killed by signal {number} ({name})"
    if os.WIFEXITED(status):
        return f"exit status {os.WEXITSTATUS(status)}"
    return f"wait status {status}"


def supervise_host(child: int, read_fd: int, out: _Output, *, unblock=None,
                   seams: host.HostSeams = host.V1) -> int:
    """The thin RSS parent of OPS-23 around the host process `child`, which reports on `read_fd`;
    returns the exit code. `seams` is OPS-21's: only tests pass another (its RSS probe, its
    poll interval and its limits); the command line never builds one. A host that ends without
    a result raises `HostEndedWithoutResult` after the workers it reported are killed."""
    state = {"buffer": bytearray(), "result": None, "live": set(), "started": False,
             "closed": False}
    # A stop noted just before the host started is held like one that comes later.
    pending: list[int] = [] if _STOPPED["signum"] is None else [_STOPPED["signum"]]
    wake_read, wake_write = os.pipe()
    os.set_blocking(wake_read, False)
    os.set_blocking(wake_write, False)
    os.set_blocking(read_fd, False)
    main = _main_thread()
    saved = {}
    old_wakeup = None
    if main:
        for signum in _STOP_SIGNALS:
            saved[signum] = signal.signal(signum, lambda s, _f: pending.append(s))
        old_wakeup = signal.set_wakeup_fd(wake_write, warn_on_full_buffer=False)
    if unblock is not None:
        signal.pthread_sigmask(signal.SIG_SETMASK, unblock)
    try:
        poller = select.poll()
        poller.register(read_fd, select.POLLIN)
        poller.register(wake_read, select.POLLIN)
        next_rss = seams.monotonic_ns()
        while not state["closed"]:
            now = seams.monotonic_ns()
            if now >= next_rss:
                next_rss = now + seams.rss_poll_ns
                rss = seams.rss_of(child)
                if rss is not None and rss > seams.limits.host_rss_bytes:
                    return _kill_host(child, read_fd, state, out)
            if pending and state["started"]:
                for signum in pending:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(child, signum)
                pending.clear()
            timeout = -(-max(0, next_rss - seams.monotonic_ns()) // _MILLISECOND)
            for fd, _event in poller.poll(timeout):
                if fd == wake_read:
                    with contextlib.suppress(BlockingIOError):
                        while os.read(wake_read, _READ_CHUNK):
                            pass
                elif not state["closed"]:
                    _read_host(read_fd, state, out)
                    if state["closed"]:
                        poller.unregister(read_fd)
        _pid, status = os.waitpid(child, 0)
    finally:
        if main:
            signal.set_wakeup_fd(old_wakeup if old_wakeup is not None else -1)
            for signum, handler in saved.items():
                signal.signal(signum, handler)
        os.close(wake_read)
        os.close(wake_write)
    result = state["result"]
    if result is None:
        # CR-R6-F3: no summary can be given, and the workers the host still had are nobody's
        # now: each is a process group of its own, outside the host's.
        live = sorted(state["live"])
        for pid in live:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGKILL)
        raise HostEndedWithoutResult(
            f"the host process ended without a result ({_wait_status(status)}); "
            f"{len(live)} worker process group(s) it reported were killed")
    out.summary(OBSERVE, result["exit_code"], result["result"], result["codes"])
    return result["exit_code"]


def _read_host(read_fd: int, state: dict, out: _Output) -> bool:
    """Read what the host has written and act on each complete message; False when there was
    nothing to read."""
    try:
        chunk = os.read(read_fd, _READ_CHUNK)
    except BlockingIOError:
        return False
    if not chunk:
        state["closed"] = True
        return False
    buffer = state["buffer"]
    buffer += chunk
    if len(buffer) > _HOST_MESSAGE_BYTES:
        raise RuntimeError("the host's message is longer than any message it writes")
    while True:
        end = buffer.find(b"\n")
        if end < 0:
            return True
        message = json.loads(bytes(buffer[:end]))
        del buffer[:end + 1]
        if "worker" in message:
            if message["running"]:
                state["live"].add(message["worker"])
                state["started"] = True
            else:
                state["live"].discard(message["worker"])
        elif "stderr" in message:
            _write(2, message["stderr"].encode("ascii", "backslashreplace"))
        else:
            state["result"] = message["result"]
    return True


def _kill_host(child: int, read_fd: int, state: dict, out: _Output) -> int:
    """OPS-23 above the host's limit: stop the host so that it can reap nothing more, learn the
    workers it still had, kill them (each is a process group of its own) and the host's group,
    and say so: E_LIMIT on stderr, exit 6. The capture stays as the host left it, incomplete."""
    with contextlib.suppress(ProcessLookupError):
        os.kill(child, signal.SIGSTOP)
    with contextlib.suppress(ChildProcessError):
        os.waitpid(child, os.WUNTRACED)
    with contextlib.suppress(OSError):
        while _read_host(read_fd, state, out):
            pass
    for pid in sorted(state["live"]):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        os.kill(child, signal.SIGKILL)
    with contextlib.suppress(ChildProcessError):
        os.waitpid(child, 0)
    out.diagnostic(errors.E_LIMIT, _HOST_RSS, None)
    code = errors.EXIT_CLASS[errors.E_LIMIT]
    out.summary(OBSERVE, code, {"session": None, "run_json": False, "host": "KILLED_FOR_RSS"})
    return code


# --- replay ----------------------------------------------------------------------------------------

def _replay(request: Request, out: _Output) -> int:
    observed: dict = {}
    version = _synapse_cdm_version()
    try:
        summary = replay_with(
            request.options[CAPTURE], request.options[OUT],
            allow_prefix=ALLOW_PREFIX in request.flags, observed=observed,
            manifest=lambda done, header: _runfile.replay_run(done, header,
                                                              synapse_cdm_version=version),
            check=check_stop)
    except HlaError as error:
        out.error(error)
        verification = observed.get("verification")
        refused = verification is not None and verification["status"] != capture.COMPLETE \
            and "header" not in observed
        code = errors.EXIT_CLASS[error.code]
        out.summary(REPLAY, code, {"verification": verification, "replay": None,
                                   "offline_replay": _runfile.FAIL if refused
                                   else _runfile.NOT_RUN})
        return code
    verification = summary["verification"]
    prefix = summary["status"] != capture.COMPLETE
    if prefix:
        _capture_verdict(verification, out, failed_message=_PREFIX_REPLAY)
    code = 3 if prefix or summary["errors"] else 0
    out.summary(REPLAY, code, {"verification": verification, "replay": summary,
                               "offline_replay": _runfile.PREFIX_ONLY if prefix
                               else _runfile.PASS},
                set(summary["errors"]) | set(summary["warnings"]))
    return code


def _capture_verdict(report: dict, out: _Output, *, failed_message: str = _FAILED_CAPTURE) -> int:
    """stderr for a capture that is not COMPLETE (OPS-20): the fault verification stopped at, or,
    for a FAILED footer, E_CAPTURE_INCOMPLETE at the footer's status (CR-R4-05). Returns the exit
    class OPS-16 gives such a verdict: 0 for COMPLETE, 3 otherwise."""
    status = report["status"]
    if status == capture.COMPLETE:
        return 0
    if status == capture.FAILED:
        out.diagnostic(errors.E_CAPTURE_INCOMPLETE, failed_message,
                       f"line:{report['verified_seq'] + 1}#/status")
    else:
        out.diagnostic(report["code"], report["message"], report["path"])
    return 3


# --- verify and inspect ----------------------------------------------------------------------------

def _read_capture(path: str, inspection: _inspection.Inspection | None):
    """One verified pass: the report and the codes of the captured diagnostic frames."""
    reader = capture.CaptureReader(path)
    captured: dict[str, int] = {}
    for line in reader.records():
        check_stop()
        record = line.record
        if inspection is not None:
            inspection.add(line)
        if line.number > 1 and record["type"] == capture.FRAME and \
                record["event"]["type"] == capture.DIAGNOSTIC:
            code = record["event"]["diagnostic"]["code"]
            captured[code] = captured.get(code, 0) + 1
    return reader.report, {code: captured[code] for code in sorted(captured)}


def _verify(request: Request, out: _Output) -> int:
    try:
        report, captured = _read_capture(request.options[CAPTURE], None)
    except HlaError as error:
        out.error(error)
        code = errors.EXIT_CLASS[error.code]
        out.summary(VERIFY, code, {"verification": None, "captured_codes": {}})
        return code
    code = _capture_verdict(report, out)
    out.summary(VERIFY, code, {"verification": report, "captured_codes": captured}, captured)
    return code


def _inspect(request: Request, out: _Output) -> int:
    inspection = _inspection.Inspection()
    try:
        report, captured = _read_capture(request.options[CAPTURE], inspection)
    except HlaError as error:
        out.error(error)
        code = errors.EXIT_CLASS[error.code]
        out.summary(INSPECT, code, {"verification": None, "inspection": None})
        return code
    code = _capture_verdict(report, out)
    status = report["status"]
    shown = status == capture.COMPLETE or (
        ALLOW_PREFIX in request.flags and status in (capture.FAILED, capture.INCOMPLETE))
    out.summary(INSPECT, code, {"verification": report,
                                "inspection": inspection.result() if shown else None}, captured)
    return code


# --- export-capture --------------------------------------------------------------------------------

def _export_capture(request: Request, out: _Output) -> int:
    source = request.options[CAPTURE]
    try:
        report, _captured = _read_capture(source, None)
        if report["status"] in (capture.INVALID, capture.INCOMPLETE):
            return _capture_verdict(report, out)
        _copy_capture(source, request.options[OUT], report)
    except HlaError as error:
        out.error(error)
        return errors.EXIT_CLASS[error.code]
    return _capture_verdict(report, out, failed_message="the capture ends FAILED; it was copied "
                                                         "as it is, and is not complete evidence")


def _copy_capture(source: str, destination: str, report: dict) -> None:
    target = _name(destination, OUT)
    try:
        fd = os.open(target, _CREATE_FLAGS, _FILE_MODE)
    except FileExistsError:
        raise HlaError(errors.E_OUTPUT_EXISTS, OUT, "the output file already exists") from None
    except OSError:
        raise HlaError(errors.E_IO, OUT, "the output file cannot be created") from None
    try:
        reader = capture.CaptureReader(source)
        for line in reader.records():
            check_stop()
            _write_all(fd, line.raw + b"\n", OUT)
        if reader.report != report:
            raise HlaError(errors.E_IO, CAPTURE, "the capture changed while it was copied")
        try:
            os.fsync(fd)
        except OSError:
            raise HlaError(errors.E_IO, OUT, "the output cannot be written") from None
    except BaseException:
        _remove_created(target, fd)
        raise
    os.close(fd)


def _remove_created(target: bytes, fd: int) -> None:
    # The file this command created, and only if the name still leads to it.
    with contextlib.suppress(OSError):
        mine = os.fstat(fd)
        there = os.lstat(target)
        if (mine.st_dev, mine.st_ino) == (there.st_dev, there.st_ino):
            os.unlink(target)
    with contextlib.suppress(OSError):
        os.close(fd)


# --- demo ------------------------------------------------------------------------------------------

def _rtinode_problem(environ) -> str | None:
    path = environ.get(RTINODE_VARIABLE)
    if path is None:
        path = RTINODE_LOCATION
    elif not os.path.isabs(path):
        return _RTINODE_RELATIVE
    try:
        regular = stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        regular = False
    if not regular or not os.access(path, os.X_OK):
        return _RTINODE_ABSENT
    return None


def _publisher_problem(environ) -> str | None:
    path = _demo.locate(environ, PUBLISHER_VARIABLE, _demo.PUBLISHER_LOCATION)
    if path is None:
        return _PUBLISHER_RELATIVE
    if _demo.check_publisher(path, environ) is not None:
        return _PUBLISHER_ABSENT
    return None


def _start_demo_host(document: dict, out_path: bytes, close_fds, environ: dict,
                     debug: bool) -> tuple[int, int]:
    """The host of one demo run, forked as observe forks its host (`_host_process`), in a
    process group of its own; returns its pid and the read end of its message pipe. The child
    first closes `close_fds` (the publisher's pipes are the demo's, not the host's)."""
    command = os.getpid()
    read_fd, write_fd = os.pipe()
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _STOP_SIGNALS)
    try:
        pid = os.fork()
    except OSError:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        os.close(read_fd)
        os.close(write_fd)
        raise HlaError(errors.E_IO, OUT, _FORK) from None
    if pid == 0:
        os.close(read_fd)
        for fd in close_fds:
            with contextlib.suppress(OSError):
                os.close(fd)
        _host_process(document, out_path, _demo.V1.session_seconds, environ,
                      time.time_ns() // 1000, write_fd, debug, command)
    os.close(write_fd)
    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    with contextlib.suppress(OSError):
        os.setpgid(pid, pid)
    return pid, read_fd


def _demo_summary(document: dict) -> dict:
    """The demo's result on stdout: its status, each run's result and failed checkpoints, the
    failures and the clean-up."""
    return {"status": document["status"],
            "runs": [{"name": run["name"], "result": run["result"],
                      "failed_checkpoints": [c["id"] for c in run["checkpoints"]
                                             if c["result"] != _demo.PASS]}
                     for run in document["runs"]],
            "failures": [{"stage": f["stage"], "run": f["run"]} for f in document["failures"]],
            "cleanup": document["cleanup"]["result"]}


def _demo_command(request: Request, out: _Output) -> int:
    environ = dict(os.environ)
    code = errors.EXIT_CLASS[errors.E_DEPENDENCY_PIN]
    try:
        modules = _fom.check_fom_modules(environ.get(FOM_DIR_VARIABLE, ""))
        directory = _Directory(request.options[OUT])
    except HlaError as error:
        out.error(error)
        code = errors.EXIT_CLASS[error.code]
        out.summary(DEMO, code, None)
        return code
    try:
        missing = []
        try:
            host.check_worker(host.locate_worker(environ), environ)
        except HlaError as error:
            missing.append((host.WORKER_NAME, error.message))
        problem = _rtinode_problem(environ)
        if problem is not None:
            missing.append((RTINODE_NAME, problem))
        problem = _publisher_problem(environ)
        if problem is not None:
            missing.append((PUBLISHER_NAME, problem))
        check_stop()
        if missing:
            document = {"demo_version": 1, "status": "BLOCKED", "profile": capture.PROFILE,
                        "adapter_version": capture.ADAPTER_VERSION, "source_commit": None,
                        "fom_sha256": {module.name: module.sha256 for module in modules},
                        "missing": [{"item": item, "code": errors.E_DEPENDENCY_PIN,
                                     "message": message} for item, message in missing],
                        "external_customer_interoperability": _runfile.NOT_TESTED}
            outcome = None
        else:
            directory.replay_dirs.extend(_demo.DIRECTORIES)
            outcome = _demo.run_demo(
                directory.target, environ, modules,
                rtinode=environ.get(RTINODE_VARIABLE, RTINODE_LOCATION),
                publisher=_demo.locate(environ, PUBLISHER_VARIABLE, _demo.PUBLISHER_LOCATION),
                start_host=lambda document_, out_path, close_fds: _start_demo_host(
                    document_, out_path, close_fds, environ, out.debug),
                check=check_stop, synapse_cdm_version=_synapse_cdm_version())
            document = outcome.document
        problem = next(iter(_schema.checked_validator(DEMO_SCHEMA).iter_errors(document)), None)
        if problem is not None:
            raise RuntimeError(f"demo.json fails {DEMO_SCHEMA} ({problem.validator})")
        check_stop()
        directory.create(DEMO_FILE, canonical.canonical_bytes(document) + b"\n")
        directory.close()
    except HlaError as error:
        directory.discard()
        out.error(error)
        code = errors.EXIT_CLASS[error.code]
        out.summary(DEMO, code, None)
        return code
    except BaseException:
        directory.discard()
        raise
    if outcome is None:
        for item, message in missing:
            out.diagnostic(errors.E_DEPENDENCY_PIN, message, item)
        out.summary(DEMO, code, {"status": "BLOCKED", "missing": [item for item, _ in missing]})
        return code
    for line in outcome.host_lines:
        out.stderr(line.encode("ascii", "backslashreplace"))
    for diagnostic_code, message, path in outcome.diagnostics:
        out.diagnostic(diagnostic_code, message, path)
    out.summary(DEMO, outcome.exit_code, _demo_summary(document), outcome.codes)
    return outcome.exit_code


# --- self-test -------------------------------------------------------------------------------------

def _self_test(request: Request, out: _Output) -> int:
    fom_dir = os.environ.get(FOM_DIR_VARIABLE) or None
    try:
        directory = _Directory(request.options[OUT])
    except HlaError as error:
        out.error(error)
        code = errors.EXIT_CLASS[error.code]
        out.summary(SELF_TEST, code, None)
        return code
    try:
        directory.replay_dirs.append(_selftest.FIXTURE_REPLAY)
        report, pins_error = _selftest.run(directory.path(_selftest.FIXTURE_REPLAY), fom_dir,
                                           synapse_cdm_version=_synapse_cdm_version(),
                                           check=check_stop)
        check_stop()
        directory.create(SELF_TEST_FILE, canonical.canonical_bytes(report, floats=True) + b"\n")
        directory.close()
    except HlaError as error:
        directory.discard()
        out.error(error)
        code = errors.EXIT_CLASS[error.code]
        out.summary(SELF_TEST, code, None)
        return code
    except BaseException:
        directory.discard()
        raise
    cases = report["cases"]
    failed = [case["id"] for case in cases if case["result"] == _selftest.FAIL]
    blocked = [case["id"] for case in cases if case["result"] == _selftest.BLOCKED]
    classes = []
    if pins_error is not None:
        out.error(pins_error)
        classes.append(errors.EXIT_CLASS[pins_error.code])
    if blocked:
        out.diagnostic(errors.E_DEPENDENCY_PIN, _FOM_NOT_SET, _fom.FOM_MODULES[0])
        classes.append(errors.EXIT_CLASS[errors.E_DEPENDENCY_PIN])
    if any(identifier != "PINS-FOM" for identifier in failed):
        # OPS-19: a failed self-test case is exit 3 with the failed ids, and no new code.
        classes.append(3)
    code = max(classes, default=0)
    out.summary(SELF_TEST, code, {"result": report["result"], "cases": len(cases),
                                  "passed": report["counts"][_selftest.PASS],
                                  "failed": len(failed), "blocked": len(blocked),
                                  "failed_ids": failed, "blocked_ids": blocked})
    return code


# --- the entry point -------------------------------------------------------------------------------

_HANDLERS = {
    VALIDATE_CONFIG: _validate_config,
    OBSERVE: _observe,
    REPLAY: _replay,
    VERIFY: _verify,
    INSPECT: _inspect,
    EXPORT_CAPTURE: _export_capture,
    DEMO: _demo_command,
    SELF_TEST: _self_test,
}


def main(argv=None) -> int:
    """`synapse-hla`: run one command and return its exit code; see the module text.

    Without `argv` this is the program (the console script, `python -m`): it reads `sys.argv`,
    and from the moment the exit code is decided SIGINT and SIGTERM are ignored until the process
    ends (CR-R6-F1). With `argv`, the caller's signal handlers are restored on return."""
    arguments = sys.argv[1:] if argv is None else list(argv)
    out = _Output()
    with _stoppable(program=argv is None):
        try:
            try:
                request = parse(arguments)
            except _Shown as shown:
                _write(1, shown.text)
                return 0
            except _Usage as usage:
                out.diagnostic(errors.E_CONFIG, usage.message, usage.path)
                if usage.command != EXPORT_CAPTURE:
                    out.summary(usage.command, errors.EXIT_CLASS[errors.E_CONFIG], None)
                return errors.EXIT_CLASS[errors.E_CONFIG]
            out.debug = request.debug
            return _HANDLERS[request.command](request, out)
        except _Interrupted as stop:
            return _SIGNAL_EXIT_BASE + stop.signum


if __name__ == "__main__":
    sys.exit(main())
