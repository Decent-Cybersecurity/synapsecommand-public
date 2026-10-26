"""The command line `synapse-hla` (round R6): G-R36 clause by clause and OPS-29's list.

HOW EVERY TEST RUNS IT
----------------------
The binding rule of the round: G-R36 is held by tests that start the entry point as a child
process and assert its exit code, stdout, stderr and the files it wrote. `run_cli` starts
`python -m synapse_hla.cli` (the module entry point; the console script `synapse-hla` calls the
same `main`, and the installed form is exercised in the round report) with:
- `tests/cliguard/` first on PYTHONPATH: the socket guard of D-10, and an audit hook that refuses
  any write outside the test's own directory (`tmp_path`) and logs it (exit criterion 4 of the
  brief, held in every child of this module, the fake worker included);
- an empty working directory of its own, which must still be empty afterwards;
- a snapshot of `tmp_path` before and after: everything new must lie under the paths the test
  says the command creates (its `--out`, and the fake worker's work directory), nothing else.
Then every stdout is held to `local_schemas/cli-summary.schema.json` (exactly one line, its
`exit_code` the process's; export-capture prints nothing) and every stderr line to
`cli-diagnostic.schema.json`, all of it ASCII. `run.json`, `self-test.json` and `demo.json` are
held to their schemas wherever a test reads them.

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
Codes and paths from the rulings named in each docstring (OPS-02's classes are written out in
`CLASSES` below, from the ruling's text); file contents from the bundle's fixtures
(`session.capture.jsonl`, `expected.observations.jsonl`, the vendored pins); crafted captures from
the tests' own capture builder (`hla_support.CaptureBuilder`), never from the product.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

import pytest

from hla_support import (
    FIXTURE_HEADER_SHA256, PACKAGE_ROOT, TESTS_DIR, CaptureBuilder, case, connect_and_join,
    connect_refused, contract_json, encode_spatial, event_diagnostic, event_discover,
    event_generation_end, event_generation_start, event_reflect, event_remove, example_json,
    fail, fixture_capture_records, fom_modules, frame_step, header_with, local_validator,
    negative_hex, orderly_stop, package_bytes, positive_hex, process_gone, stage, strict_json,
    worker_executable,
)

SRC = PACKAGE_ROOT / "src"
GUARD = TESTS_DIR / "cliguard"
FOM_DIR_VARIABLE = "SYNAPSE_HLA_FOM_DIR"
SUMMARY = local_validator("cli-summary.schema.json")
DIAGNOSTIC = local_validator("cli-diagnostic.schema.json")
RUN_SCHEMA = local_validator("run.schema.json")
SELF_TEST_SCHEMA = local_validator("self-test.schema.json")
DEMO_SCHEMA = local_validator("demo.schema.json")

COMMANDS = ("validate-config", "observe", "replay", "verify", "inspect", "export-capture",
            "demo", "self-test")
#: OPS-02, written out from the ruling: the exit class of every E_ code.
CLASSES = {
    **dict.fromkeys(("E_CONFIG", "E_OUTPUT_EXISTS"), 2),
    **dict.fromkeys(("E_ATTRIBUTE_LENGTH", "E_NONFINITE", "E_BOOLEAN", "E_SPATIAL_VARIANT",
                     "E_UNSUBSCRIBED_ATTRIBUTE", "E_NULL_ID", "E_ECEF_RANGE", "E_GEODESY",
                     "E_TIME_REGRESSION", "E_IDENTITY_CHANGED", "E_IDENTITY_COLLISION",
                     "E_RETRACTION_UNSUPPORTED", "E_UNKNOWN_OBJECT", "E_CAPTURE_SCHEMA",
                     "E_CAPTURE_HASH", "E_CAPTURE_SEQUENCE", "E_CAPTURE_INCOMPLETE"), 3),
    "E_DEPENDENCY_PIN": 4,
    **dict.fromkeys(("E_FOM_PROFILE", "E_FEDERATE_NAME", "E_RTI_CONNECT", "E_RTI_TIMEOUT"), 5),
    **dict.fromkeys(("E_LIMIT", "E_QUEUE_OVERFLOW", "E_IO"), 6),
}
VERSION_LINE = b'{"name":"synapse-hla","version":"1.0.0","profile":"SC-HLA-RPR2-OBS-1"}\n'
FED = "SC_DEMO_0123456789abcdef"
CAPTURE_PIN = {e["path"]: e for e in contract_json("vendored-pins.json")["files"]}[
    "src/synapse_hla/fixtures/session.capture.jsonl"]
#: D-19: the SHA-256 of `expected.observations.jsonl` (the fixture's replay output).
OBSERVATIONS_SHA256 = "d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
HEX = positive_hex()
BAD = negative_hex()
FULL = (("EntityIdentifier", HEX["ID-123"]), ("EntityType", HEX["TYPE-PLATFORM"]),
        ("ForceIdentifier", HEX["FORCE-1"]), ("Spatial", HEX["SPATIAL-2"]))
SECOND = 1_000_000_000


# ============================================================================ running the CLI

@dataclass
class Ran:
    code: int
    stdout: bytes
    stderr: bytes
    summary: dict | None
    diagnostics: list[dict]


def environment(tmp_path: pathlib.Path, *, fom: bool = True, extra: dict | None = None) -> dict:
    """The child's environment: no SYNAPSE_HLA_* variable but those the test sets, the guards
    first on PYTHONPATH, then the package's source, no bytecode."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("SYNAPSE_HLA_") and key != "PYTHONPATH"}
    if fom:
        env[FOM_DIR_VARIABLE] = str(fom_modules()[0].parent)
    env["PYTHONPATH"] = os.pathsep.join([str(GUARD), str(SRC)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SC_HLA_WRITE_ROOT"] = str(tmp_path)
    env["SC_HLA_WRITE_LOG"] = str(tmp_path / "write-guard.log")
    env.update(extra or {})
    return env


def tree(root: pathlib.Path) -> set[str]:
    out = set()
    for directory, names, files in os.walk(root):
        for name in names + files:
            out.add(os.path.relpath(os.path.join(directory, name), root))
    return out


def command_line(*args) -> list[str]:
    return [sys.executable, "-m", "synapse_hla.cli", *map(str, args)]


def start(tmp_path, *args, env=None, prefix=()) -> tuple[subprocess.Popen, set]:
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    before = tree(tmp_path)
    argv = list(prefix) + (command_line(*args) if not prefix else [str(a) for a in args])
    proc = subprocess.Popen(argv, cwd=cwd, env=env if env is not None else environment(tmp_path),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc, before


def finish(tmp_path, proc, before, args, *, creates=(), shown=False, timeout=300,
           ended=None) -> Ran:
    stdout, stderr = proc.communicate(timeout=timeout)
    return checked(tmp_path, proc.returncode, stdout, stderr, before, args, creates=creates,
                   shown=shown, ended=ended)


def run_cli(tmp_path, *args, env=None, creates=(), shown=False, timeout=300, prefix=(),
            ended=None) -> Ran:
    proc, before = start(tmp_path, *args, env=env, prefix=prefix)
    return finish(tmp_path, proc, before, args, creates=creates, shown=shown, timeout=timeout,
                  ended=ended)


def checked(tmp_path, code, stdout, stderr, before, args, *, creates=(), shown=False,
            ended=None) -> Ran:
    """What every command-line run must satisfy, whatever its scenario (see the module text).
    `ended` is "defect" for a run that must end with Python's traceback and status 1 (CR-R3-07),
    or "interrupted" for one stopped by a signal (nothing on stdout or stderr)."""
    args = [str(a) for a in args]
    assert not (tmp_path / "write-guard.log").exists(), \
        (tmp_path / "write-guard.log").read_text()
    assert list((tmp_path / "cwd").iterdir()) == []
    new = tree(tmp_path) - before
    allowed = [str(pathlib.Path(c)) for c in creates]
    stray = sorted(p for p in new if not any(p == a or p.startswith(a + os.sep)
                                             for a in allowed))
    assert stray == [], f"created outside the expected paths: {stray}"
    assert stdout.isascii() and stderr.isascii()
    if shown:
        return Ran(code, stdout, stderr, None, [])
    if ended == "defect":
        assert code == 1 and stdout == b"", (code, stdout)
        assert stderr.startswith(b"Traceback (most recent call last):"), stderr[-2000:]
        return Ran(code, stdout, stderr, None, [])
    if ended == "interrupted":
        assert (stdout, stderr) == (b"", b""), (stdout, stderr)
        return Ran(code, stdout, stderr, None, [])
    debug = "--debug" in args
    diagnostics = []
    for line in stderr.splitlines():
        if debug and not line.startswith(b"{"):
            continue
        record = strict_json(line)
        errors_ = list(DIAGNOSTIC.iter_errors(record))
        assert not errors_, (record, errors_[0].message)
        diagnostics.append(record)
    if not debug:
        assert stderr == b"" or stderr.endswith(b"\n")
        assert b"Traceback" not in stderr
    summary = None
    if "export-capture" in args:
        assert stdout == b""
    else:
        lines = stdout.splitlines()
        assert len(lines) == 1 and stdout.endswith(b"\n"), stdout
        summary = strict_json(lines[0])
        errors_ = list(SUMMARY.iter_errors(summary))
        assert not errors_, (summary, errors_[0].message)
        assert summary["exit_code"] == code
        assert summary["codes"] == sorted(set(summary["codes"]))
        assert {d["code"] for d in diagnostics} <= set(summary["codes"])
    return Ran(code, stdout, stderr, summary, diagnostics)


def only(ran: Ran) -> tuple:
    """The one diagnostic of a run, as (code, path)."""
    assert len(ran.diagnostics) == 1, ran.diagnostics
    return ran.diagnostics[0]["code"], ran.diagnostics[0]["path"]


def write(path: pathlib.Path, data: bytes) -> pathlib.Path:
    path.write_bytes(data)
    return path


def fixture_capture(tmp_path) -> pathlib.Path:
    return write(tmp_path / "capture.jsonl", package_bytes("fixtures", "session.capture.jsonl"))


def flipped_fom(tmp_path) -> pathlib.Path:
    """A copy of the five FOM modules with one byte of RPR-Base flipped (A-DEPENDENCY)."""
    copy = tmp_path / "fom"
    copy.mkdir()
    for module in fom_modules():
        (copy / module.name).write_bytes(module.read_bytes())
    data = bytearray((copy / "RPR-Base_v2.0.xml").read_bytes())
    data[100] ^= 0x01
    (copy / "RPR-Base_v2.0.xml").write_bytes(bytes(data))
    return copy


# ============================================================================ --help, --version

@case("G-R36", "G-R35", paragraphs=("SPEC:174", "SPEC:166"))
@pytest.mark.parametrize("command", (None,) + COMMANDS)
@pytest.mark.parametrize("option", ["--help", "--version"])
def test_every_command_answers_help_and_version(tmp_path, command, option):
    """R36 "All commands support --version and --help" with OPS-09 as corrected: the program and
    each of the eight commands print the version object exactly, or a help text, on stdout, exit
    0, write nothing on stderr and create nothing. Every one of the nine helps states SPEC:166's
    distinction ("required in CLI help": a byte copy of a verified original, no HLA packets,
    nothing replayed into an RTI, a CDM record alone does not regenerate the session, CR-R6-F5);
    every help names the command's own options. The program's help says that observe stops its
    session in order once one exists and that a stop during its own pre-flight exits 130 or 143
    like the other commands (CR-R6-05, final review finding F-host-02)."""
    args = ([command] if command else []) + [option]
    ran = run_cli(tmp_path, *args, shown=True)
    assert (ran.code, ran.stderr) == (0, b"")
    if option == "--version":
        assert ran.stdout == VERSION_LINE
        return
    text = ran.stdout.decode("ascii")
    assert text.startswith(f"usage: synapse-hla {command or ''}".rstrip())
    flat = " ".join(text.split())
    assert "export-capture copies only a verified original capture, byte for byte." in flat
    assert "It does not edit, re-encode or re-export HLA data: it constructs no HLA packets and " \
           "replays no traffic into an RTI." in flat
    assert "A CDM record alone is not enough to regenerate its original federate session; keep " \
           "the capture and its outputs together through the run manifest run.json." in flat
    if command is None:
        assert ("130 or 143 stopped by SIGINT or SIGTERM before the command finished (observe "
                "stops its session in order once one exists, and a stop before that, during its "
                "own configuration and FOM pre-flight, exits 130 or 143 like the other commands; "
                "once a command has its result, a further signal changes nothing)") in flat
        assert "observe instead stops" not in flat
    options = {"validate-config": ["--config"], "observe": ["--config", "--out",
                                                            "--duration-seconds"],
               "replay": ["--capture", "--out", "--allow-prefix"], "verify": ["--capture"],
               "inspect": ["--capture", "--allow-prefix"],
               "export-capture": ["--capture", "--out"], "demo": ["--out"],
               "self-test": ["--out"], None: list(COMMANDS)}[command]
    assert all(name in text for name in options)


@case("G-R36", paragraphs=("SPEC:184",))
def test_help_and_version_come_before_anything_else_on_their_line(tmp_path):
    """The arguments are read left to right: --help after other options still shows the help
    (nothing is run), and --version after --debug the version."""
    ran = run_cli(tmp_path, "replay", "--capture", "x", "--out", "y", "--help", shown=True)
    assert ran.code == 0 and ran.stdout.startswith(b"usage: synapse-hla replay")
    ran = run_cli(tmp_path, "--debug", "--version", shown=True)
    assert (ran.code, ran.stdout) == (0, VERSION_LINE)
    assert not (tmp_path / "cwd" / "y").exists()


# ============================================================================ usage errors

USAGE = [
    # (arguments, command in the summary, path of the E_CONFIG diagnostic)
    ([], None, "COMMAND"),
    (["--debug"], None, "COMMAND"),
    (["frobnicate"], None, "COMMAND"),
    (["Replay", "--capture", "c"], None, "COMMAND"),
    (["--bogus", "verify"], None, "--bogus"),
    (["-h"], None, "-h"),
    (["verify"], "verify", "--capture"),
    (["verify", "--capture"], "verify", "--capture"),
    (["verify", "--capture", "a", "--capture", "b"], "verify", "--capture"),
    (["verify", "--capture=a"], "verify", "--capture=a"),
    (["verify", "--captur", "a"], "verify", "--captur"),
    (["verify", "--capture", "a", "extra"], "verify", "extra"),
    (["verify", "--capture", "a", ""], "verify", "ARGUMENT"),
    (["replay", "", "--capture", "a", "--out", "b"], "replay", "ARGUMENT"),
    (["verify", "--capture", "--out"], "verify", "--capture"),
    (["verify", "--capture", ""], "verify", "--capture"),
    (["verify", "--capture", "a", "--out", "b"], "verify", "--out"),
    (["verify", "--capture", "a", "--allow-prefix"], "verify", "--allow-prefix"),
    (["validate-config", "--config", "a", "--allow-prefix"], "validate-config",
     "--allow-prefix"),
    (["observe", "--config", "c"], "observe", "--out"),
    (["observe", "--config", "c", "--out", "o", "--allow-prefix"], "observe", "--allow-prefix"),
    (["replay", "--capture", "c"], "replay", "--out"),
    (["replay", "--capture", "c", "--out", "o", "--allow-prefix", "--allow-prefix"], "replay",
     "--allow-prefix"),
    (["replay", "--capture", "c", "--out", "o", "--duration-seconds", "5"], "replay",
     "--duration-seconds"),
    (["inspect", "--capture", "c", "--out", "o"], "inspect", "--out"),
    (["demo"], "demo", "--out"),
    (["demo", "--out", "d", "--allow-prefix"], "demo", "--allow-prefix"),
    (["self-test", "--out", "d", "--allow-prefix"], "self-test", "--allow-prefix"),
    (["self-test", "--allow-prefix", "--out", "d"], "self-test", "--allow-prefix"),
    (["export-capture", "--capture", "c"], "export-capture", "--out"),
    (["export-capture", "--capture", "c", "--out", "o", "--allow-prefix"], "export-capture",
     "--allow-prefix"),
]


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("args,command,path", USAGE, ids=[" ".join(u[0]) or "none" for u in USAGE])
def test_a_usage_error_is_a_structured_e_config_with_exit_2(tmp_path, args, command, path):
    """OPS-02 and OPS-09: anything the command table of SPEC:174-184 does not give (no command, an
    unknown one, a missing, repeated, abbreviated, `=`-joined or foreign option, an option
    without its value, a stray argument, --allow-prefix where SPEC:184 rejects it or does not give
    it) is one E_CONFIG diagnostic on stderr whose path names the argument, exit 2, never a
    parser's own text and never a traceback; stdout is the summary with no result (export-capture:
    nothing at all); nothing is created."""
    ran = run_cli(tmp_path, *args)
    assert ran.code == 2
    assert only(ran) == ("E_CONFIG", path)
    if command == "export-capture":
        assert ran.summary is None
    else:
        assert ran.summary == {"cli_summary_version": 1, "command": command, "exit_code": 2,
                               "codes": ["E_CONFIG"], "result": None}


DURATIONS_REFUSED = ["0", "86401", "99999", "+60", "060", "6_0", " 60", "60 ", "1e3", "60.0",
                     "-1", "\u0666\u0660", "\uff16\uff10", "0x3c", "600000"]


@case("G-R36", paragraphs=("SPEC:184",))
@pytest.mark.parametrize("value", DURATIONS_REFUSED,
                         ids=[v.encode("unicode_escape").decode() for v in DURATIONS_REFUSED])
def test_a_duration_outside_one_to_86400_ascii_digits_is_refused(tmp_path, value):
    """SPEC:184 and OPS-15: --duration-seconds is an integer 1 through 86400 written as plain
    ASCII digits (^[1-9][0-9]{0,4}$): 0, 86401, a sign, a leading zero, an underscore, a space,
    an exponent, a fraction, Arabic-Indic and full-width digits and hexadecimal are refused with
    E_CONFIG at --duration-seconds, exit 2, before anything runs (no run directory). Python's
    `int` reads several of these, which is why the form is matched first. "-1" is refused as a
    value that starts with '-' (the option then has no value): the same code and path."""
    ran = run_cli(tmp_path, "observe", "--config", "c.json", "--out", "run",
                  "--duration-seconds", value)
    assert (ran.code, only(ran)) == (2, ("E_CONFIG", "--duration-seconds"))
    assert not (tmp_path / "cwd" / "run").exists()


@case("G-R36", paragraphs=("SPEC:184",))
def test_the_duration_bounds_and_the_default_are_read_as_the_specification_gives_them():
    """SPEC:184: 1 and 86400 are accepted, 60 is the default; the parser of the module itself,
    in this process (the end-to-end runs below start observe with 1, 86400 and no option)."""
    from synapse_hla import cli
    base = ["observe", "--config", "c", "--out", "o"]
    assert cli.parse(base).duration_seconds == 60
    assert cli.parse(base + ["--duration-seconds", "1"]).duration_seconds == 1
    assert cli.parse(base + ["--duration-seconds", "86400"]).duration_seconds == 86400
    assert cli.parse(base + ["--duration-seconds", "9999"]).duration_seconds == 9999


# ============================================================================ escaping (R40)

@case("G-R36", paragraphs=("SPEC:184",))
@case("G-R40")
def test_a_hostile_argument_reaches_stderr_as_escaped_data(tmp_path):
    """R40 and CR-R1-04: an argument that becomes a diagnostic's path is made safe (each control,
    bidirectional control and line separator becomes U+FFFD, at most 64 characters) and then
    written as ASCII JSON, DEL escaped too: the escape sequence, the right-to-left override, the
    line break and the DEL of a hostile option reach the terminal as escapes in one line."""
    hostile = "--\x1b[31mred\u202eevil\nline\x7f" + "x" * 100
    ran = run_cli(tmp_path, "verify", "--capture", "c", hostile)
    assert ran.code == 2 and len(ran.stderr.splitlines()) == 1
    (code, path) = only(ran)
    replacement = "\N{REPLACEMENT CHARACTER}"
    assert code == "E_CONFIG"
    assert path == ("--" + replacement + "[31mred" + replacement + "evil" + replacement + "line"
                    + replacement + "x" * 100)[:64]
    assert b"\\ufffd" in ran.stderr and b"\x1b" not in ran.stderr and b"\x7f" not in ran.stderr


def test_the_output_writer_escapes_del_and_everything_past_it():
    from synapse_hla import cli
    line = cli._json_line({"m": "a\x7fb\x1b\u202e\u2028\U0001f600"})
    assert line == b'{"m":"a\\u007fb\\u001b\\u202e\\u2028\\ud83d\\ude00"}\n'
    assert json.loads(line) == {"m": "a\x7fb\x1b\u202e\u2028\U0001f600"}


def _json_escape(code_point: int) -> str:
    """One character as the command line's output must spell it inside a JSON string: RFC 8259
    section 7's escapes with R40's rule that nothing outside printable ASCII is written raw.
    Printable ASCII (U+0020 to U+007E) as itself except the quote and the backslash, the five
    short escapes, every other character below U+10000 (DEL and the lone surrogates included) as
    \\uXXXX in lowercase hex, and a character above it as its UTF-16 surrogate pair. Written out
    here, not taken from `json`."""
    short = {0x22: '\\"', 0x5C: "\\\\", 0x08: "\\b", 0x0C: "\\f", 0x0A: "\\n", 0x0D: "\\r",
             0x09: "\\t"}
    if code_point in short:
        return short[code_point]
    if 0x20 <= code_point <= 0x7E:
        return chr(code_point)
    if code_point < 0x10000:
        return "\\u%04x" % code_point
    offset = code_point - 0x10000
    return "\\u%04x\\u%04x" % (0xD800 + (offset >> 10), 0xDC00 + (offset & 0x3FF))


def test_the_output_writer_is_json_with_every_character_outside_printable_ascii_escaped():
    """R40 and R6-r1-F6: `_json_line` adds nothing to `json`'s ASCII writer, because that writer
    already escapes everything a terminal could act on, DEL included. Every code point from U+0000
    to U+10FFFF (lone surrogates included) inside a string comes out as RFC 8259's escape, and
    the line is ASCII with exactly one LF, at its end."""
    from synapse_hla import cli
    for start in range(0, 0x110000, 0x1000):
        text = "".join(chr(c) for c in range(start, start + 0x1000))
        line = cli._json_line({"m": text})
        expected = '{"m":"' + "".join(_json_escape(c) for c in range(start, start + 0x1000)) \
            + '"}\n'
        assert line == expected.encode("ascii"), hex(start)
        assert line.count(b"\n") == 1 and line.isascii()


# ============================================================================ OPS-21

@case("G-R36", paragraphs=("SPEC:174",))
def test_no_limit_or_timing_value_is_reachable_from_an_option_a_key_or_a_variable():
    """OPS-21 and D-09: the option table is exactly SPEC:174-184's (no limit or timing option),
    the configuration schema's keys are R07's (none of them a limit), the command line never
    builds or replaces a `HostSeams` and passes no `seams` or `limits` to anything, and it reads
    no environment variable but the three of D-07 and OPV-04 (which name files, not values)."""
    from synapse_hla import cli
    assert {name: (spec.values, spec.required, spec.flags) for name, spec in cli.COMMANDS.items()} \
        == {"validate-config": (("--config",), ("--config",), ()),
            "observe": (("--config", "--out", "--duration-seconds"), ("--config", "--out"), ()),
            "replay": (("--capture", "--out"), ("--capture", "--out"), ("--allow-prefix",)),
            "verify": (("--capture",), ("--capture",), ()),
            "inspect": (("--capture",), ("--capture",), ("--allow-prefix",)),
            "export-capture": (("--capture", "--out"), ("--capture", "--out"), ()),
            "demo": (("--out",), ("--out",), ()),
            "self-test": (("--out",), ("--out",), ())}
    schema = strict_json(package_bytes("schemas", "config.schema.json"))
    assert set(schema["properties"]) == {
        "profile", "session_id", "source_system", "synthetic", "mode", "endpoint",
        "allow_remote", "federation_name", "federate_name", "profile_declaration",
        "time_policy", "force_map"}
    source = (SRC / "synapse_hla" / "cli.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    calls = [node for node in ast.walk(module) if isinstance(node, ast.Call)]
    called = {call.func.attr if isinstance(call.func, ast.Attribute) else
              getattr(call.func, "id", None) for call in calls}
    assert "HostSeams" not in called
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "dataclasses"
                   and any(alias.name == "replace" for alias in node.names)
                   for node in ast.walk(module))
    assert not any(isinstance(call.func, ast.Attribute) and call.func.attr == "replace"
                   and isinstance(call.func.value, ast.Name)
                   and call.func.value.id in ("dataclasses", "host") for call in calls)
    assert not {kw.arg for call in calls for kw in call.keywords} & {"seams", "limits"}

    def reads_environment(call):
        func = call.func
        if not (isinstance(func, ast.Attribute) and func.attr in ("get", "__getitem__")):
            return False
        holder = func.value
        return (isinstance(holder, ast.Name) and holder.id == "environ") or (
            isinstance(holder, ast.Attribute) and holder.attr == "environ")
    read = [call.args[0] for call in calls if reads_environment(call)]
    assert all(isinstance(arg, ast.Name) for arg in read)
    assert {arg.id for arg in read} == {"FOM_DIR_VARIABLE", "RTINODE_VARIABLE"}
    assert not any(isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                   and node.value.attr == "environ" for node in ast.walk(module))
    assert (cli.FOM_DIR_VARIABLE, cli.WORKER_VARIABLE, cli.RTINODE_VARIABLE) == (
        "SYNAPSE_HLA_FOM_DIR", "SYNAPSE_HLA_WORKER", "SYNAPSE_HLA_RTINODE")
    for module_path in (SRC / "synapse_hla").glob("*.py"):
        if module_path.name in ("cli.py", "host.py"):
            continue
        text = module_path.read_text(encoding="utf-8")
        assert "os.environ" not in text and "getenv" not in text, module_path.name


@case("G-R36", paragraphs=("SPEC:174",))
def test_environment_variables_that_look_like_limits_change_nothing(tmp_path):
    """OPS-21 from the outside: variables named like the limits and timing values, set to values
    that would change the result if anything read them, leave a replay's directory byte for byte
    what it is without them."""
    capture_path = fixture_capture(tmp_path)
    plain = run_cli(tmp_path, "replay", "--capture", capture_path, "--out", tmp_path / "plain",
                    creates=["plain"])
    hostile = {f"SYNAPSE_HLA_{name}": "1" for name in (
        "LINE_BYTES", "CAPTURE_FILE_BYTES", "FRAMES_PER_SESSION", "DEADLINE_NS", "DRAIN_NS",
        "LIMITS", "ACTIVE_OBJECTS_PER_GENERATION", "ATTRIBUTE_VALUE_BYTES", "DURATION_SECONDS")}
    other = run_cli(tmp_path, "replay", "--capture", capture_path, "--out", tmp_path / "other",
                    env=environment(tmp_path, extra=hostile), creates=["other"])
    assert plain.code == other.code == 0
    for name in ("capture.jsonl", "observations.jsonl", "diagnostics.jsonl", "run.json"):
        assert (tmp_path / "plain" / name).read_bytes() == (tmp_path / "other" / name).read_bytes()


# ============================================================================ validate-config

def config_file(tmp_path, name="config-demo.json", **members) -> pathlib.Path:
    document = example_json(name)
    document.update(members)
    return write(tmp_path / f"in-{name}", json.dumps(document).encode("utf-8"))


@case("G-R36", "G-R07", paragraphs=("SPEC:174", "SPEC:38"))
@pytest.mark.parametrize("name", ["config-demo.json", "config-existing.json"])
def test_validate_config_accepts_both_example_configurations(tmp_path, name):
    """SPEC:175 and OPS-14: validate-config checks the configuration offline and the FOM pins;
    both modes are accepted (G-R07's carried clause: validate_config accepts both modes). The
    summary names the configuration's canonical digest (SHA-256 of its keys sorted, compact,
    ASCII, computed here with json) and the five module digests of the packaged pins."""
    path = PACKAGE_ROOT / "examples" / name
    ran = run_cli(tmp_path, "validate-config", "--config", path)
    document = example_json(name)
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("ascii")
    pins = {e["path"]: e["sha256"] for e in strict_json(package_bytes("pins.json"))["files"]}
    assert (ran.code, ran.diagnostics, ran.stderr) == (0, [], b"")
    assert ran.summary["result"] == {
        "config": {"status": "VALID", "sha256": hashlib.sha256(canonical).hexdigest(),
                   "session_id": document["session_id"], "mode": document["mode"],
                   "profile_declaration": document["profile_declaration"]},
        "dependencies": {"status": "PASS", "fom_sha256": {
            n: pins[n] for n in ("RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml",
                                 "RPR-Base_v2.0.xml", "RPR-Physical_v2.0.xml",
                                 "RPR-Switches_v2.0.xml")}}}
    assert ran.summary["codes"] == []


@case("G-R36", paragraphs=("SPEC:174",))
@pytest.mark.parametrize("data,path", [
    (b'{"profile": "SC-HLA-RPR2-OBS-1", "profile": "SC-HLA-RPR2-OBS-1"}', "/profile"),
    (json.dumps(dict(example_json("config-demo.json"),
                     endpoint="rti://0127.0.0.1:14321")).encode(), "/endpoint"),
    (json.dumps(dict(example_json("config-demo.json"), synthetic=False)).encode(), "/synthetic"),
    (b" " * 65_537, ""),
], ids=["duplicate-key", "octal-looking-endpoint", "demo-without-synthetic", "65537-bytes"])
def test_validate_config_refuses_a_configuration_with_exit_2(tmp_path, data, path):
    """R07: a duplicate key (refused while the document is read, at the repeated member, as
    test_hla_config's A-DUPLICATE-KEY rows say), a leading zero in an octet (OPS-04), demo
    without synthetic true (SPEC:38) and a file over 64 KiB (at the whole document) are E_CONFIG
    at their pointer, exit 2; the FOM pins still pass."""
    ran = run_cli(tmp_path, "validate-config", "--config", write(tmp_path / "c.json", data))
    assert (ran.code, only(ran)) == (2, ("E_CONFIG", path))
    assert ran.summary["result"]["config"]["status"] == "INVALID"
    assert ran.summary["result"]["dependencies"]["status"] == "PASS"


@case("G-R36", "A-DEPENDENCY", paragraphs=("SPEC:174", "SPEC:184"))
def test_validate_config_with_a_changed_or_absent_fom_module_is_exit_4(tmp_path):
    """OPS-11 and A-DEPENDENCY: one flipped byte of RPR-Base is E_DEPENDENCY_PIN at
    RPR-Base_v2.0.xml, exit 4; an unset SYNAPSE_HLA_FOM_DIR is E_DEPENDENCY_PIN at the first
    module (no directory was given); both checks run, so a bad configuration and a bad module
    give two diagnostics and the higher class, 4 (OPS-02's priority)."""
    good = PACKAGE_ROOT / "examples" / "config-existing.json"
    env = environment(tmp_path, extra={FOM_DIR_VARIABLE: str(flipped_fom(tmp_path))})
    ran = run_cli(tmp_path, "validate-config", "--config", good, env=env)
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml"))
    assert ran.summary["result"]["dependencies"] == {"status": "FAIL", "fom_sha256": None}
    bad = write(tmp_path / "bad.json", b"[]")
    ran = run_cli(tmp_path, "validate-config", "--config", bad,
                  env=environment(tmp_path, fom=False))
    assert ran.code == 4
    assert [(d["code"], d["path"]) for d in ran.diagnostics] == [
        ("E_CONFIG", ""), ("E_DEPENDENCY_PIN", "RPR-Foundation_v2.0.xml")]
    assert ran.summary["codes"] == ["E_CONFIG", "E_DEPENDENCY_PIN"]


@case("G-R36", paragraphs=("SPEC:174",))
def test_validate_config_of_a_file_that_cannot_be_read_is_e_io(tmp_path):
    """A --config that is not there, or is a directory, is E_IO at --config, exit 6 (CR-L01:
    the argument names the file; OPS-02: I/O is class 6); a URL is a file name like any other and
    nothing is fetched (R36: no implicit URL downloading; the socket guard would refuse)."""
    for target in (tmp_path / "missing.json", tmp_path, "https://example.invalid/config.json"):
        ran = run_cli(tmp_path, "validate-config", "--config", target)
        assert (ran.code, only(ran)) == (6, ("E_IO", "--config"))
        assert ran.summary["result"]["config"]["status"] == "UNREADABLE"


# ============================================================================ replay

def replay_dir(path: pathlib.Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.iterdir())}


def run_json(path: pathlib.Path) -> dict:
    data = (path / "run.json").read_bytes()
    document = strict_json(data)
    errors_ = list(RUN_SCHEMA.iter_errors(document))
    assert not errors_, errors_[0].message
    assert data == json.dumps(document, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True).encode("ascii") + b"\n"
    return document


@case("G-R36", "G-R35", paragraphs=("SPEC:174", "SPEC:168"))
def test_replay_of_the_bundled_capture_writes_four_files_and_exits_0(tmp_path):
    """SPEC:177 and SPEC:168 (G-R35's carried clause): replay writes the directory 0700 with
    capture.jsonl (a byte copy), observations.jsonl (the bundle's expected stream byte for
    byte), diagnostics.jsonl (empty) and run.json, each 0600. run.json (OPS-10 as corrected)
    holds the profile and package versions, a null source commit, the configuration's canonical
    digest, the five FOM digests and the nine-entry pin map of the header, the files with their
    sizes and digests, the record counts, completion true, the suppression counts, no error or
    warning, offline_replay PASS beside external_customer_interoperability NOT_TESTED (OPS-01,
    D-14), and null audit times: replay reads no clock."""
    capture_path = fixture_capture(tmp_path)
    ran = run_cli(tmp_path, "replay", "--capture", capture_path, "--out", tmp_path / "run",
                  creates=["run"])
    assert (ran.code, ran.diagnostics) == (0, [])
    out = tmp_path / "run"
    assert stat_mode(out) == 0o700
    assert sorted(p.name for p in out.iterdir()) == ["capture.jsonl", "diagnostics.jsonl",
                                                     "observations.jsonl", "run.json"]
    assert all(stat_mode(p) == 0o600 for p in out.iterdir())
    assert (out / "capture.jsonl").read_bytes() == capture_path.read_bytes()
    assert (out / "observations.jsonl").read_bytes() == package_bytes(
        "fixtures", "expected.observations.jsonl")
    document = run_json(out)
    header = fixture_capture_records()[0]
    config_canonical = json.dumps(header["config"], sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=True).encode("ascii")
    assert {k: v for k, v in document.items() if k != "capture"} == {
        "run_version": 1, "command": "replay", "profile": "SC-HLA-RPR2-OBS-1",
        "adapter_version": "1.0.0", "source_commit": None,
        # CR-L18: the synapse-cdm distribution installed beside the package, whatever its
        # version inside the declared floor (the child interpreter runs the same environment).
        "package_versions": {"synapse_hla": "1.0.0",
                             "synapse_cdm": importlib.metadata.version("synapse-cdm")},
        "session_id": "example-001",
        "config_sha256": hashlib.sha256(config_canonical).hexdigest(),
        "fom_sha256": {n: header["pins"][n] for n in (
            "RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml", "RPR-Base_v2.0.xml",
            "RPR-Physical_v2.0.xml", "RPR-Switches_v2.0.xml")},
        "pins": header["pins"],
        "outputs": [{"file": "observations.jsonl", "bytes": 10822,
                     "sha256": OBSERVATIONS_SHA256, "records": 7},
                    {"file": "diagnostics.jsonl", "bytes": 0, "sha256": EMPTY_SHA256,
                     "records": 0}],
        "record_counts": {"diagnostic": 0, "snapshot": 4, "upsert": 2, "removed": 1,
                          "invalidated": 0},
        "capture_complete": True,
        "suppression_counts": {"MISSING_ENTITY_IDENTIFIER": 0, "MISSING_ENTITY_TYPE": 0,
                               "MISSING_SPATIAL": 2, "INVALID_ENTITY_IDENTIFIER": 0,
                               "INVALID_ENTITY_TYPE": 0, "INVALID_SPATIAL": 0,
                               "INVALID_FORCE_IDENTIFIER": 0, "NULL_ID": 0, "QUARANTINED": 0,
                               "TIME_UNRESOLVED": 0, "GEOGRAPHY_UNPROJECTABLE": 0},
        "error_counts": {}, "warning_counts": {}, "session": None,
        "evidence": {"offline_replay": "PASS", "external_customer_interoperability": "NOT_TESTED"},
        "audit": {"started_at": None, "ended_at": None}}
    footer = fixture_capture_records()[-1]
    assert document["capture"] == {
        "file": "capture.jsonl", "bytes": CAPTURE_PIN["bytes"], "sha256": CAPTURE_PIN["sha256"],
        "status": "COMPLETE", "reason_code": None, "last_seq": 9, "frames": 8,
        "verification": {"verify_report_version": 1, "status": "COMPLETE", "code": None,
                         "path": None, "message": None, "verified_seq": 9,
                         "verified_bytes": CAPTURE_PIN["bytes"], "frames": 8,
                         "header_sha256": FIXTURE_HEADER_SHA256,
                         "last_sha256": footer["sha256"], "capture_complete": True,
                         "footer": footer}}
    result = ran.summary["result"]
    assert result["offline_replay"] == "PASS" and result["replay"]["status"] == "COMPLETE"
    assert result["verification"] == document["capture"]["verification"]


def stat_mode(path: pathlib.Path) -> int:
    return path.stat().st_mode & 0o777


@case("G-R36", "G-R35", paragraphs=("SPEC:168",))
def test_two_replays_give_byte_identical_directories_run_json_included(tmp_path):
    """OPS-10 (1): the replay command reads no clock, so two replays of one capture by one build
    give the same four files byte for byte, run.json included."""
    capture_path = fixture_capture(tmp_path)
    for name in ("one", "two"):
        assert run_cli(tmp_path, "replay", "--capture", capture_path, "--out", tmp_path / name,
                       creates=[name]).code == 0
    assert replay_dir(tmp_path / "one") == replay_dir(tmp_path / "two")


def truncated_capture(tmp_path) -> tuple[pathlib.Path, bytes]:
    """The bundled capture cut 40 bytes into line 8 (seq 7): verified are seq 1 to 6."""
    data = package_bytes("fixtures", "session.capture.jsonl")
    ends = [i for i, b in enumerate(data) if b == 0x0A]
    cut = data[:ends[6] + 1 + 40]
    return write(tmp_path / "cut.jsonl", cut), cut


@case("G-R36", "G-R17", "A-PREFIX", paragraphs=("SPEC:184",))
def test_a_prefix_replay_exits_3_and_its_evidence_is_prefix_only_never_pass(tmp_path):
    """R17 (G-R17's carried clause), A-PREFIX, OPS-16, OPS-20, CR-L08: without --allow-prefix the
    truncated capture is refused (E_CAPTURE_INCOMPLETE at line:8, exit 3, no directory; the
    summary carries the verification, offline_replay FAIL). With it, the verified prefix is
    replayed: exit 3, stderr E_CAPTURE_INCOMPLETE at line:8 (filled from the verification, no
    third pass), every record capture_complete false, run.json's evidence PREFIX_ONLY and
    capture_complete false, its capture block INCOMPLETE with last_seq 6, and the copy is the
    whole input file."""
    path, data = truncated_capture(tmp_path)
    ran = run_cli(tmp_path, "replay", "--capture", path, "--out", tmp_path / "run")
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_INCOMPLETE", "line:8"))
    assert not (tmp_path / "run").exists()
    result = ran.summary["result"]
    assert (result["offline_replay"], result["replay"]) == ("FAIL", None)
    assert (result["verification"]["status"], result["verification"]["verified_seq"]) == (
        "INCOMPLETE", 6)
    ran = run_cli(tmp_path, "replay", "--capture", path, "--out", tmp_path / "run",
                  "--allow-prefix", creates=["run"])
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_INCOMPLETE", "line:8"))
    result = ran.summary["result"]
    assert result["offline_replay"] == "PREFIX_ONLY"
    assert (result["replay"]["status"], result["replay"]["capture_complete"]) == (
        "INCOMPLETE", False)
    records = [strict_json(line) for line in
               (tmp_path / "run" / "observations.jsonl").read_bytes().splitlines()]
    assert len(records) == 6 and {r["capture_complete"] for r in records} == {False}
    document = run_json(tmp_path / "run")
    assert document["evidence"] == {"offline_replay": "PREFIX_ONLY",
                                    "external_customer_interoperability": "NOT_TESTED"}
    assert document["capture_complete"] is False
    assert (document["capture"]["status"], document["capture"]["last_seq"],
            document["capture"]["verification"]["path"]) == ("INCOMPLETE", 6, "line:8")
    assert (tmp_path / "run" / "capture.jsonl").read_bytes() == data


def failed_capture(tmp_path) -> pathlib.Path:
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start()).frame(1, 0, event_discover("o1"))
    builder.frame(1, SECOND, event_reflect("o1", FULL))
    builder.frame(1, SECOND, event_diagnostic("E_RTI_CONNECT", "the RTI went away"))
    builder.frame(1, SECOND, event_generation_end("connection_lost"))
    builder.footer("FAILED", "E_RTI_CONNECT", 1)
    return builder.write(tmp_path / "failed.jsonl")


@case("G-R36", "G-R17", paragraphs=("SPEC:184",))
def test_a_failed_capture_replays_only_as_a_prefix(tmp_path):
    """A FAILED footer (seq 6, line 7): refused without the flag (E_CAPTURE_INCOMPLETE at
    line:7#/status, CR-R4-05, exit 3); with it, a prefix replay with the same stderr, exit 3,
    PREFIX_ONLY, and the captured E_RTI_CONNECT among the codes."""
    path = failed_capture(tmp_path)
    ran = run_cli(tmp_path, "replay", "--capture", path, "--out", tmp_path / "run")
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_INCOMPLETE", "line:7#/status"))
    ran = run_cli(tmp_path, "replay", "--capture", path, "--out", tmp_path / "run",
                  "--allow-prefix", creates=["run"])
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_INCOMPLETE", "line:7#/status"))
    assert ran.summary["result"]["offline_replay"] == "PREFIX_ONLY"
    assert ran.summary["codes"] == ["E_CAPTURE_INCOMPLETE", "E_RTI_CONNECT"]
    assert run_json(tmp_path / "run")["capture"]["reason_code"] == "E_RTI_CONNECT"


def capture_with_bad_line(tmp_path) -> pathlib.Path:
    """The bundled capture with seq 3's sha256 changed: E_CAPTURE_HASH at line 4."""
    lines = package_bytes("fixtures", "session.capture.jsonl").split(b"\n")
    record = strict_json(lines[3])
    record["sha256"] = "0" * 64
    lines[3] = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return write(tmp_path / "bad.jsonl", b"\n".join(lines))


def past_9998_capture(tmp_path) -> pathlib.Path:
    """CR-L15: epoch 9998-12-31T23:59:59.000000Z and a frame one second later."""
    epoch = "9998-12-31T23:59:59.000000Z"
    builder = CaptureBuilder(header_with(time_policy={"mode": "external_elapsed", "epoch": epoch,
                                                      "basis": "b"}))
    builder.frame(1, 0, event_generation_start()).frame(1, SECOND, event_discover("o1"))
    builder.frame(1, SECOND, event_generation_end()).footer()
    return builder.write(tmp_path / "late.jsonl")


def long_line_capture(tmp_path) -> pathlib.Path:
    """A discover whose name makes the line longer than 65536 bytes (OPS-21: E_LIMIT, judged by
    its length before anything else)."""
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start())
    builder.frame(1, 0, event_discover("o1", name="N" * 70_000))
    builder.frame(1, 0, event_generation_end()).footer()
    return builder.write(tmp_path / "long.jsonl")


def other_pins_capture(tmp_path) -> pathlib.Path:
    header = fixture_capture_records()[0]
    header["pins"]["RPR-Base_v2.0.xml"] = "0" * 64
    builder = CaptureBuilder(header)
    builder.frame(1, 0, event_generation_start()).frame(1, 0, event_generation_end()).footer()
    return builder.write(tmp_path / "pins.jsonl")


@case("G-R36", "G-R35", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("make,code,path,status", [
    (capture_with_bad_line, 3, "line:4#/sha256", "E_CAPTURE_HASH"),
    (past_9998_capture, 2, "line:1#/config/time_policy/epoch", "E_CONFIG"),
    (long_line_capture, 6, "line:3", "E_LIMIT"),
    (other_pins_capture, 4, "RPR-Base_v2.0.xml", "E_DEPENDENCY_PIN"),
    (lambda tmp_path: other_federation_capture(tmp_path), 3, "line:2#/event/federation_name",
     "E_CAPTURE_SCHEMA"),
    (lambda tmp_path: gap_capture(tmp_path), 3, "line:3#/seq", "E_CAPTURE_SEQUENCE"),
], ids=["hash", "past-9998", "line-limit", "pins", "other-federation", "sequence"])
def test_a_refused_replay_exits_with_the_class_of_its_code(tmp_path, make, code, path, status):
    """OPS-02 for replay: a refusal exits with its code's class and creates nothing. A changed
    digest is E_CAPTURE_HASH (3); an effective time past 9998-12-31T23:59:59.999999Z is E_CONFIG
    at `line:1#/config/time_policy/epoch` (CR-L15: the capture's path form, not the projector's;
    2); a line over the line limit is E_LIMIT (6); a header whose pins differ from the packaged
    ones is E_DEPENDENCY_PIN under the file's name (RED-V-03, 4)."""
    ran = run_cli(tmp_path, "replay", "--capture", make(tmp_path), "--out", tmp_path / "run")
    assert (ran.code, only(ran)) == (code, (status, path))
    assert not (tmp_path / "run").exists()


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("kind", ["directory", "file", "dangling-symlink", "symlink-to-directory"])
def test_replay_refuses_an_existing_or_symlinked_out(tmp_path, kind):
    """R36 and OPS-17: an --out that exists in any form, a dangling symbolic link included, is
    E_OUTPUT_EXISTS at --out, exit 2, and nothing is written into or through it."""
    out = tmp_path / "out"
    target = tmp_path / "elsewhere"
    if kind == "directory":
        out.mkdir()
    elif kind == "file":
        out.write_bytes(b"")
    elif kind == "dangling-symlink":
        out.symlink_to(target)
    else:
        target.mkdir()
        out.symlink_to(target)
    ran = run_cli(tmp_path, "replay", "--capture", fixture_capture(tmp_path), "--out", out)
    assert (ran.code, only(ran)) == (2, ("E_OUTPUT_EXISTS", "--out"))
    assert not target.exists() or list(target.iterdir()) == []
    if kind == "directory":
        assert list(out.iterdir()) == []


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_replay_of_a_missing_capture_or_into_a_missing_parent_is_e_io(tmp_path):
    """The API's E_IO paths become the command's argument names (CR-R2-17): a missing capture is
    E_IO at --capture, an --out whose parent does not exist E_IO at --out; exit 6 (OPS-02)."""
    ran = run_cli(tmp_path, "replay", "--capture", tmp_path / "none.jsonl", "--out",
                  tmp_path / "run")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--capture"))
    assert ran.summary["result"] == {"verification": None, "replay": None,
                                     "offline_replay": "NOT_RUN"}
    ran = run_cli(tmp_path, "replay", "--capture", fixture_capture(tmp_path), "--out",
                  tmp_path / "no" / "run")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--out"))
    assert ran.summary["result"]["offline_replay"] == "NOT_RUN"


# ============================================================================ verify

def recovered_capture(tmp_path) -> pathlib.Path:
    """A COMPLETE capture with a recovered failure: generation 1 lost, a generation-0
    E_RTI_CONNECT between generations, generation 2 stopped in order."""
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start())
    builder.frame(1, 0, event_diagnostic("E_RTI_CONNECT", "connection lost"))
    builder.frame(1, 0, event_generation_end("connection_lost"))
    builder.frame(0, SECOND, event_diagnostic("E_RTI_CONNECT", "the RTI refused the connection"))
    builder.frame(2, 2 * SECOND, event_generation_start())
    builder.frame(2, 2 * SECOND, event_generation_end("stop"))
    return builder.footer("COMPLETE", None, 2).write(tmp_path / "recovered.jsonl")


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_verify_of_a_complete_capture_exits_0_and_lists_its_captured_codes(tmp_path):
    """SPEC:178 and OPS-16: a valid COMPLETE capture exits 0, nothing on stderr, the summary
    carries the verify report; E_ codes of captured diagnostic frames are listed (two
    E_RTI_CONNECT here) and do not change verify's exit."""
    ran = run_cli(tmp_path, "verify", "--capture", fixture_capture(tmp_path))
    assert (ran.code, ran.stderr) == (0, b"")
    report = ran.summary["result"]["verification"]
    assert (report["status"], report["verified_seq"], report["verified_bytes"],
            report["header_sha256"]) == ("COMPLETE", 9, CAPTURE_PIN["bytes"],
                                         FIXTURE_HEADER_SHA256)
    assert ran.summary["result"]["captured_codes"] == {}
    ran = run_cli(tmp_path, "verify", "--capture", recovered_capture(tmp_path))
    assert (ran.code, ran.stderr) == (0, b"")
    assert ran.summary["result"]["captured_codes"] == {"E_RTI_CONNECT": 2}
    assert ran.summary["codes"] == ["E_RTI_CONNECT"]


def other_federation_capture(tmp_path) -> pathlib.Path:
    """CR-L09: a generation_start naming another federation than the configured one."""
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start("SC_DEMO_ffffffffffffffff"))
    builder.frame(1, 0, event_generation_end()).footer()
    return builder.write(tmp_path / "other.jsonl")


def gap_capture(tmp_path) -> pathlib.Path:
    """seq 1, then seq 3 (chained, so only the sequence is wrong): E_CAPTURE_SEQUENCE at line 3."""
    from hla_support import capture_bytes, chain_lines
    records = CaptureBuilder().frame(1, 0, event_generation_start()).frame(
        1, 0, event_generation_end()).footer().records()
    records[2]["seq"] = 3
    records[3]["seq"] = 4
    return write(tmp_path / "gap.jsonl", capture_bytes(chain_lines(records)))


@case("G-R36", "G-R17", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("make,expected", [
    (capture_with_bad_line, ("E_CAPTURE_HASH", "line:4#/sha256")),
    (lambda tmp_path: truncated_capture(tmp_path)[0], ("E_CAPTURE_INCOMPLETE", "line:8")),
    (failed_capture, ("E_CAPTURE_INCOMPLETE", "line:7#/status")),
    (long_line_capture, ("E_LIMIT", "line:3")),
    (past_9998_capture, ("E_CONFIG", "line:1#/config/time_policy/epoch")),
    (other_federation_capture, ("E_CAPTURE_SCHEMA", "line:2#/event/federation_name")),
    (gap_capture, ("E_CAPTURE_SEQUENCE", "line:3#/seq")),
], ids=["hash", "truncated", "failed", "line-limit", "past-9998", "other-federation",
        "sequence"])
def test_verify_of_any_other_capture_exits_3_with_the_fault_on_stderr(tmp_path, make, expected):
    """OPS-16: verify exits 0 only for a valid COMPLETE capture and 3 for every other verdict,
    whatever its code's own class (E_LIMIT and E_CONFIG included); stderr names the fault and
    its path (OPS-20), for a FAILED footer E_CAPTURE_INCOMPLETE at its status (CR-R4-05), and for
    the year-9998 overflow the capture's path (CR-L15)."""
    ran = run_cli(tmp_path, "verify", "--capture", make(tmp_path))
    assert (ran.code, only(ran)) == (3, expected)


@case("G-R36", paragraphs=("SPEC:174",))
def test_verify_of_a_file_that_cannot_be_read_is_e_io(tmp_path):
    ran = run_cli(tmp_path, "verify", "--capture", tmp_path / "none.jsonl")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--capture"))
    assert ran.summary["result"] == {"verification": None, "captured_codes": {}}


# ============================================================================ inspect

#: The inspection of the bundled capture, read off the fixture by hand: eight frames in one
#: generation (seq 1 generation_start at 0 s, seq 2 discover, seq 3 and 4 reflects at 0 s, seq 5
#: and 6 reflects at 1 and 2 s, seq 7 remove and seq 8 generation_end stop at 3 s), one
#: PhysicalEntity discovered, no diagnostic, time policy external_elapsed from the epoch
#: 2026-01-01T00:00:00.000000Z, so the coverage runs from that instant to three seconds later.
FIXTURE_INSPECTION = {
    "profile": "SC-HLA-RPR2-OBS-1", "profile_declaration": "bundled-fom-created",
    "mode": "demo", "session_id": "example-001", "capture_sha256": CAPTURE_PIN["sha256"],
    "verified_bytes": CAPTURE_PIN["bytes"], "frames": 8,
    "generations": [{"generation": 1, "frames": 8, "first_elapsed_ns": "0",
                     "last_elapsed_ns": "3000000000", "end_reason": "stop"}],
    "between_generations": 0,
    "events": {"generation_start": 1, "discover": 1, "reflect": 4, "remove": 1, "diagnostic": 0,
               "generation_end": 1},
    "reported_classes": {"HLAobjectRoot.BaseEntity.PhysicalEntity": 1},
    "diagnostics": {},
    "time_coverage": {"policy": "external_elapsed", "epoch": "2026-01-01T00:00:00.000000Z",
                      "first_elapsed_ns": "0", "last_elapsed_ns": "3000000000",
                      "first_effective_at": "2026-01-01T00:00:00.000000Z",
                      "last_effective_at": "2026-01-01T00:00:03.000000Z"},
}


@case("G-R36", paragraphs=("SPEC:174",))
def test_inspect_summarizes_counts_profile_time_coverage_and_classes(tmp_path):
    """SPEC:179 and OPS-26: the inspection of the bundled capture, every member a literal derived
    from the fixture (above), the footer the fixture's own; exit 0."""
    ran = run_cli(tmp_path, "inspect", "--capture", fixture_capture(tmp_path))
    assert (ran.code, ran.stderr) == (0, b"")
    inspection = ran.summary["result"]["inspection"]
    assert inspection == dict(FIXTURE_INSPECTION, footer=fixture_capture_records()[-1])


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_inspect_of_generations_and_captured_diagnostics(tmp_path):
    """Two generations with a generation-0 frame between them: the spans, the frame between,
    the captured codes, and the coverage from the first generation_start to the last frame."""
    ran = run_cli(tmp_path, "inspect", "--capture", recovered_capture(tmp_path))
    assert ran.code == 0
    inspection = ran.summary["result"]["inspection"]
    assert inspection["generations"] == [
        {"generation": 1, "frames": 3, "first_elapsed_ns": "0", "last_elapsed_ns": "0",
         "end_reason": "connection_lost"},
        {"generation": 2, "frames": 2, "first_elapsed_ns": "2000000000",
         "last_elapsed_ns": "2000000000", "end_reason": "stop"}]
    assert inspection["between_generations"] == 1
    assert inspection["diagnostics"] == {"E_RTI_CONNECT": 2}
    assert inspection["time_coverage"]["last_effective_at"] == "2026-01-01T00:00:02.000000Z"
    assert ran.summary["codes"] == ["E_RTI_CONNECT"]


@case("G-R36", "G-R17", paragraphs=("SPEC:184",))
def test_inspect_summarizes_a_prefix_only_with_allow_prefix(tmp_path):
    """SPEC:184: inspect accepts --allow-prefix. A truncated capture exits 3 either way with
    E_CAPTURE_INCOMPLETE at line:8 (OPS-16); without the flag there is no inspection, with it the
    inspection covers the verified prefix: seq 1 to 6, so six frames, an open generation (no
    end reason), no footer, and the digest and length of the first seven lines."""
    path, data = truncated_capture(tmp_path)
    ran = run_cli(tmp_path, "inspect", "--capture", path)
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_INCOMPLETE", "line:8"))
    assert ran.summary["result"]["inspection"] is None
    ran = run_cli(tmp_path, "inspect", "--capture", path, "--allow-prefix")
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_INCOMPLETE", "line:8"))
    inspection = ran.summary["result"]["inspection"]
    prefix = data[:len(data) - 40]
    assert (inspection["frames"], inspection["footer"], inspection["verified_bytes"],
            inspection["capture_sha256"]) == (6, None, len(prefix),
                                              hashlib.sha256(prefix).hexdigest())
    assert inspection["generations"] == [{"generation": 1, "frames": 6, "first_elapsed_ns": "0",
                                          "last_elapsed_ns": "2000000000", "end_reason": None}]
    ran = run_cli(tmp_path, "inspect", "--capture", capture_with_bad_line(tmp_path),
                  "--allow-prefix")
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_HASH", "line:4#/sha256"))
    assert ran.summary["result"]["inspection"] is None
    ran = run_cli(tmp_path, "inspect", "--capture", tmp_path / "none.jsonl")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--capture"))


# ============================================================================ export-capture

@case("G-R36", "G-R35", paragraphs=("SPEC:174", "SPEC:166"))
def test_export_capture_copies_a_verified_capture_byte_for_byte_and_prints_nothing(tmp_path):
    """SPEC:180 and SPEC:166 (G-R35's carried clause): export-capture verifies and then copies the
    original capture byte for byte to the new --out file (0600); stdout stays empty (OPS-09 as
    corrected), exit 0; the copy verifies to the same report. A FAILED capture is copied too and
    exits 3 with E_CAPTURE_INCOMPLETE at its footer's status (OPS-16)."""
    source = fixture_capture(tmp_path)
    ran = run_cli(tmp_path, "export-capture", "--capture", source, "--out",
                  tmp_path / "copy.jsonl", creates=["copy.jsonl"])
    assert (ran.code, ran.stdout, ran.stderr) == (0, b"", b"")
    assert (tmp_path / "copy.jsonl").read_bytes() == source.read_bytes()
    assert stat_mode(tmp_path / "copy.jsonl") == 0o600
    source = failed_capture(tmp_path)
    ran = run_cli(tmp_path, "export-capture", "--capture", source, "--out",
                  tmp_path / "failed-copy.jsonl", creates=["failed-copy.jsonl"])
    assert (ran.code, only(ran)) == (3, ("E_CAPTURE_INCOMPLETE", "line:7#/status"))
    assert (tmp_path / "failed-copy.jsonl").read_bytes() == source.read_bytes()


@case("G-R36", "G-R35", paragraphs=("SPEC:174", "SPEC:166"))
@pytest.mark.parametrize("make,expected", [
    (capture_with_bad_line, ("E_CAPTURE_HASH", "line:4#/sha256")),
    (lambda tmp_path: truncated_capture(tmp_path)[0], ("E_CAPTURE_INCOMPLETE", "line:8")),
], ids=["invalid", "incomplete"])
def test_export_capture_refuses_an_invalid_or_incomplete_capture_without_creating_out(
        tmp_path, make, expected):
    """OPS-16: an invalid or incomplete capture is refused, exit 3, and --out is never created:
    only a verified original is exported (SPEC:166)."""
    ran = run_cli(tmp_path, "export-capture", "--capture", make(tmp_path), "--out",
                  tmp_path / "copy.jsonl")
    assert (ran.code, only(ran), ran.stdout) == (3, expected, b"")
    assert not (tmp_path / "copy.jsonl").exists()


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("kind", ["file", "dangling-symlink", "directory"])
def test_export_capture_refuses_an_existing_out(tmp_path, kind):
    """OPS-17: export-capture's --out is created exclusively without following a link: an
    existing file, directory or dangling symbolic link is E_OUTPUT_EXISTS, exit 2, untouched."""
    out = tmp_path / "copy.jsonl"
    if kind == "file":
        out.write_bytes(b"keep")
    elif kind == "directory":
        out.mkdir()
    else:
        out.symlink_to(tmp_path / "elsewhere.jsonl")
    ran = run_cli(tmp_path, "export-capture", "--capture", fixture_capture(tmp_path), "--out",
                  out)
    assert (ran.code, only(ran), ran.stdout) == (2, ("E_OUTPUT_EXISTS", "--out"), b"")
    assert not (tmp_path / "elsewhere.jsonl").exists()
    if kind == "file":
        assert out.read_bytes() == b"keep"


@case("G-R36", paragraphs=("SPEC:174",))
def test_export_capture_io_failures_are_exit_6(tmp_path):
    ran = run_cli(tmp_path, "export-capture", "--capture", tmp_path / "none.jsonl", "--out",
                  tmp_path / "copy.jsonl")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--capture"))
    ran = run_cli(tmp_path, "export-capture", "--capture", fixture_capture(tmp_path), "--out",
                  tmp_path / "no" / "copy.jsonl")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--out"))


# ============================================================================ demo

def demo_json(path: pathlib.Path) -> dict:
    document = strict_json((path / "demo.json").read_bytes())
    errors_ = list(DEMO_SCHEMA.iter_errors(document))
    assert not errors_, errors_[0].message
    return document


def fom_pins() -> dict:
    pins = {e["path"]: e["sha256"] for e in strict_json(package_bytes("pins.json"))["files"]}
    return {n: pins[n] for n in ("RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml",
                                 "RPR-Base_v2.0.xml", "RPR-Physical_v2.0.xml",
                                 "RPR-Switches_v2.0.xml")}


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_demo_without_its_dependencies_is_blocked_with_exit_4(tmp_path):
    """OPS-18 and OPS-13's layout: with the FOM pins holding but no worker, no rtinode and no
    publisher (this build has no demo orchestration and no publisher), demo makes DIR (0700)
    with DIR/demo.json (0600) saying BLOCKED, the three missing items, the five module digests,
    no source commit and external_customer_interoperability NOT_TESTED (OPS-01, D-14); one
    E_DEPENDENCY_PIN per item on stderr; exit 4 (SPEC:184: missing dependency)."""
    ran = run_cli(tmp_path, "demo", "--out", tmp_path / "demo", creates=["demo"])
    assert ran.code == 4
    assert [(d["code"], d["path"]) for d in ran.diagnostics] == [
        ("E_DEPENDENCY_PIN", "sc-hla-federate"), ("E_DEPENDENCY_PIN", "rtinode"),
        ("E_DEPENDENCY_PIN", "sc-hla-publisher")]
    assert ran.summary["result"] == {"status": "BLOCKED", "missing": [
        "sc-hla-federate", "rtinode", "sc-hla-publisher"]}
    assert sorted(p.name for p in (tmp_path / "demo").iterdir()) == ["demo.json"]
    assert (stat_mode(tmp_path / "demo"), stat_mode(tmp_path / "demo" / "demo.json")) == (
        0o700, 0o600)
    document = demo_json(tmp_path / "demo")
    assert {k: v for k, v in document.items() if k != "missing"} == {
        "demo_version": 1, "status": "BLOCKED", "profile": "SC-HLA-RPR2-OBS-1",
        "adapter_version": "1.0.0", "source_commit": None, "fom_sha256": fom_pins(),
        "external_customer_interoperability": "NOT_TESTED"}
    assert [m["item"] for m in document["missing"]] == ["sc-hla-federate", "rtinode",
                                                        "sc-hla-publisher"]


@case("G-R36", paragraphs=("SPEC:174",))
def test_demo_with_a_worker_and_rtinode_is_still_blocked_on_the_publisher(tmp_path):
    """OPV-04: the worker and rtinode are found through SYNAPSE_HLA_WORKER and
    SYNAPSE_HLA_RTINODE (absolute paths; the worker answers --version as CR-new-R5-02 says, here
    the fake worker); the publisher is not part of this build, so demo is BLOCKED on it alone.
    A relative SYNAPSE_HLA_RTINODE counts as missing (never a PATH search)."""
    work = tmp_path / "work"
    work.mkdir()
    worker = worker_executable(work)
    scenario = write(work / "scenario.json", json.dumps({
        "log": str(work / "worker.log"), "clock": None, "version": None, "attempts": [],
        "self": str(worker), "watch": None}).encode())
    rtinode = write(work / "rtinode", b"#!/bin/sh\nexit 0\n")
    rtinode.chmod(0o700)
    extra = {"SYNAPSE_HLA_WORKER": str(worker), "SC_HLA_FAKE_SCENARIO": str(scenario),
             "SYNAPSE_HLA_RTINODE": str(rtinode)}
    ran = run_cli(tmp_path, "demo", "--out", tmp_path / "demo",
                  env=environment(tmp_path, extra=extra), creates=["demo", "work"])
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", "sc-hla-publisher"))
    assert [m["item"] for m in demo_json(tmp_path / "demo")["missing"]] == ["sc-hla-publisher"]
    extra["SYNAPSE_HLA_RTINODE"] = "rtinode"
    ran = run_cli(tmp_path, "demo", "--out", tmp_path / "demo2",
                  env=environment(tmp_path, extra=extra), creates=["demo2", "work"])
    assert [(d["code"], d["path"]) for d in ran.diagnostics] == [
        ("E_DEPENDENCY_PIN", "rtinode"), ("E_DEPENDENCY_PIN", "sc-hla-publisher")]


@case("G-R36", "A-DEPENDENCY", paragraphs=("SPEC:174", "SPEC:184"))
def test_demo_checks_the_fom_pins_before_its_directory_exists(tmp_path):
    """OPS-11 as corrected: demo hashes the five FOM modules first; an unset variable or a changed
    module is E_DEPENDENCY_PIN, exit 4, and DIR is never made. An existing DIR is E_OUTPUT_EXISTS,
    exit 2."""
    ran = run_cli(tmp_path, "demo", "--out", tmp_path / "demo",
                  env=environment(tmp_path, fom=False))
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", "RPR-Foundation_v2.0.xml"))
    env = environment(tmp_path, extra={FOM_DIR_VARIABLE: str(flipped_fom(tmp_path))})
    ran = run_cli(tmp_path, "demo", "--out", tmp_path / "demo", env=env)
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml"))
    assert not (tmp_path / "demo").exists() and ran.summary["result"] is None
    (tmp_path / "demo").mkdir()
    ran = run_cli(tmp_path, "demo", "--out", tmp_path / "demo")
    assert (ran.code, only(ran)) == (2, ("E_OUTPUT_EXISTS", "--out"))
    ran = run_cli(tmp_path, "demo", "--out", tmp_path / "no" / "demo")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--out"))


# ============================================================================ self-test

#: The cases of the packaged runner, counted from the fixtures: 14 positive and 30 negative
#: vectors, 6 geodesy points, 1 identity, 2 example configurations, 13 bundle schemas and 8
#: product schemas (verify-report, replay-summary, session-summary, cli-summary,
#: cli-diagnostic, run, self-test, demo), 8 fixtures, the pin check, the replay and the first
#: upsert: 85.
SELF_TEST_CASES = 14 + 30 + 6 + 1 + 2 + 13 + 8 + 8 + 1 + 2


def self_test_json(path: pathlib.Path) -> dict:
    document = strict_json((path / "self-test.json").read_bytes())
    errors_ = list(SELF_TEST_SCHEMA.iter_errors(document))
    assert not errors_, errors_[0].message
    return document


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_self_test_passes_on_the_packaged_fixtures(tmp_path):
    """SPEC:182 and OPS-26: the packaged runner, without pytest, writes DIR/self-test.json and
    DIR/fixture-replay/ (the replay directory of the packaged capture, run.json included, its
    observations the expected stream byte for byte). Every case passes, each with the SHA-256 of
    its input; the global result is PASS; exit 0. A second run writes the same bytes: nothing in
    the report depends on a clock."""
    ran = run_cli(tmp_path, "self-test", "--out", tmp_path / "st", creates=["st"])
    assert (ran.code, ran.stderr) == (0, b"")
    report = self_test_json(tmp_path / "st")
    assert (report["result"], report["counts"]) == ("PASS", {
        "PASS": SELF_TEST_CASES, "FAIL": 0, "BLOCKED": 0})
    ids = [c["id"] for c in report["cases"]]
    assert len(ids) == len(set(ids)) == SELF_TEST_CASES
    vectors = [v["id"] for v in strict_json(package_bytes("fixtures",
                                                          "attributes-positive.json"))]
    assert ids[:14] == [f"V-{v}" for v in vectors]
    assert {"N-TRUNC-1", "N-BOOL-2", "GEO-origin", "GEO-north-pole", "IDENTITY",
            "CONFIG-config-demo.json", "CONFIG-config-existing.json", "SCHEMA-cli-summary.schema.json",
            "SCHEMA-cdm-entity.schema.json", "FIXTURE-session.capture.jsonl", "PINS-FOM",
            "REPLAY-session.capture.jsonl", "FIRST-UPSERT"} <= set(ids)
    by_id = {c["id"]: c for c in report["cases"]}
    raw = bytes.fromhex(strict_json(package_bytes("fixtures", "attributes-positive.json"))[0]["hex"])
    assert by_id["V-SPATIAL-1"]["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert by_id["REPLAY-session.capture.jsonl"]["expected"] == {
        "status": "COMPLETE", "observations_sha256": OBSERVATIONS_SHA256}
    assert by_id["PINS-FOM"]["actual"] == fom_pins()
    assert ran.summary["result"] == {"result": "PASS", "cases": SELF_TEST_CASES,
                                     "passed": SELF_TEST_CASES, "failed": 0, "blocked": 0,
                                     "failed_ids": [], "blocked_ids": []}
    replayed = tmp_path / "st" / "fixture-replay"
    assert sorted(p.name for p in replayed.iterdir()) == [
        "capture.jsonl", "diagnostics.jsonl", "observations.jsonl", "run.json"]
    assert (replayed / "observations.jsonl").read_bytes() == package_bytes(
        "fixtures", "expected.observations.jsonl")
    assert run_json(replayed)["evidence"]["offline_replay"] == "PASS"
    again = run_cli(tmp_path, "self-test", "--out", tmp_path / "st2", creates=["st2"])
    assert again.code == 0
    assert (tmp_path / "st2" / "self-test.json").read_bytes() == \
        (tmp_path / "st" / "self-test.json").read_bytes()
    assert replay_dir(tmp_path / "st2" / "fixture-replay") == replay_dir(replayed)


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_self_test_without_the_fom_directory_reports_the_pin_check_blocked_with_exit_4(tmp_path):
    """OPS-11 as corrected and R46: without SYNAPSE_HLA_FOM_DIR the pin check cannot run; its case
    is BLOCKED (not PASS, not FAIL), everything else still runs and passes, the global result is
    BLOCKED (D-14: no global PASS hides it), stderr says E_DEPENDENCY_PIN, exit 4."""
    ran = run_cli(tmp_path, "self-test", "--out", tmp_path / "st",
                  env=environment(tmp_path, fom=False), creates=["st"])
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", "RPR-Foundation_v2.0.xml"))
    report = self_test_json(tmp_path / "st")
    assert (report["result"], report["counts"]) == ("BLOCKED", {
        "PASS": SELF_TEST_CASES - 1, "FAIL": 0, "BLOCKED": 1})
    pins = {c["id"]: c for c in report["cases"]}["PINS-FOM"]
    assert (pins["result"], pins["actual"], pins["input_sha256"]) == ("BLOCKED", None, None)
    assert ran.summary["result"]["blocked_ids"] == ["PINS-FOM"]


@case("G-R36", "A-DEPENDENCY", paragraphs=("SPEC:174", "SPEC:184"))
def test_self_test_with_a_changed_fom_module_fails_its_pin_check_with_exit_4(tmp_path):
    env = environment(tmp_path, extra={FOM_DIR_VARIABLE: str(flipped_fom(tmp_path))})
    ran = run_cli(tmp_path, "self-test", "--out", tmp_path / "st", env=env, creates=["st"])
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml"))
    report = self_test_json(tmp_path / "st")
    pins = {c["id"]: c for c in report["cases"]}["PINS-FOM"]
    assert (pins["result"], pins["actual"]) == ("FAIL", {"code": "E_DEPENDENCY_PIN",
                                                         "path": "RPR-Base_v2.0.xml"})
    assert (report["result"], ran.summary["result"]["failed_ids"]) == ("FAIL", ["PINS-FOM"])


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_a_failing_self_test_case_is_exit_3_with_its_id(tmp_path):
    """OPS-19: a failed self-test case is exit 3 with the failed ids and no new code. A copy of
    the package whose positive vector FORCE-1 expects 2 instead of 1: that vector fails (the
    decoder still gives 1) and so does that fixture's provenance digest; nothing on stderr names
    a code for them."""
    copy = tmp_path / "pkg"
    shutil.copytree(SRC / "synapse_hla", copy / "synapse_hla")
    fixture = copy / "synapse_hla" / "fixtures" / "attributes-positive.json"
    data = fixture.read_bytes()
    entry = [v for v in strict_json(data) if v["id"] == "FORCE-1"][0]
    assert entry["expected"] == {"value": 1}
    marker = b'"id": "FORCE-1"'
    at = data.index(marker)
    end = data.index(b'"value": 1', at)
    fixture.write_bytes(data[:end] + b'"value": 2' + data[end + len(b'"value": 1'):])
    env = environment(tmp_path)
    env["PYTHONPATH"] = os.pathsep.join([str(GUARD), str(copy)])
    ran = run_cli(tmp_path, "self-test", "--out", tmp_path / "st", env=env, creates=["st"])
    assert (ran.code, ran.diagnostics) == (3, [])
    assert ran.summary["result"]["failed_ids"] == ["V-FORCE-1",
                                                   "FIXTURE-attributes-positive.json"]
    assert self_test_json(tmp_path / "st")["result"] == "FAIL"


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_self_test_refuses_an_existing_out_and_a_missing_parent(tmp_path):
    """OPS-17: a dangling symbolic link as --out is E_OUTPUT_EXISTS (2) and is not followed; an
    --out whose parent does not exist is E_IO at --out (6); nothing is created either way."""
    (tmp_path / "st").symlink_to(tmp_path / "nowhere")
    ran = run_cli(tmp_path, "self-test", "--out", tmp_path / "st")
    assert (ran.code, only(ran)) == (2, ("E_OUTPUT_EXISTS", "--out"))
    assert ran.summary["result"] is None and not (tmp_path / "nowhere").exists()
    ran = run_cli(tmp_path, "self-test", "--out", tmp_path / "no" / "st")
    assert (ran.code, only(ran)) == (6, ("E_IO", "--out"))


# ============================================================================ observe

STALL = {"do": "stall"}


def observe_setup(tmp_path, attempts, *, name="config-existing.json", members=None,
                  version=None) -> tuple[dict, pathlib.Path, pathlib.Path]:
    """The fake worker of round R5 behind SYNAPSE_HLA_WORKER, playing `attempts`; the
    configuration (an example with `members` replaced) in tmp_path/config.json. Returns the
    environment, the configuration's path and the worker's log."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    worker = worker_executable(work)
    scenario = write(work / "scenario.json", json.dumps({
        "log": str(work / "worker.log"), "clock": None, "version": version,
        "attempts": attempts, "self": str(worker),
        "watch": str(tmp_path / "run" / "capture.jsonl")}).encode())
    env = environment(tmp_path, extra={"SYNAPSE_HLA_WORKER": str(worker),
                                       "SC_HLA_FAKE_SCENARIO": str(scenario)})
    document = example_json(name)
    document.update(members or {})
    path = write(tmp_path / "config.json", json.dumps(document).encode())
    return env, path, work / "worker.log"


def log_of(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def shape(tmp_path) -> list[tuple]:
    from hla_support import capture_shape
    records = [strict_json(line) for line in
               (tmp_path / "run" / "capture.jsonl").read_bytes().splitlines()]
    return capture_shape(records[1:], elapsed=False)


def observed(tmp_path, attempts, *options, name="config-existing.json", members=None,
             env_extra=None, prefix=(), ended=None) -> tuple[Ran, list[dict]]:
    env, config, log = observe_setup(tmp_path, attempts, name=name, members=members)
    env.update(env_extra or {})
    ran = run_cli(tmp_path, "observe", "--config", config, "--out", tmp_path / "run", *options,
                  env=env, creates=["run", "work"], prefix=prefix, ended=ended)
    return ran, log_of(log)


def held_to_the_session_contract(tmp_path, ran: Ran, log: list[dict]) -> dict:
    """The run directory as every host test of round R5 holds it (`check_session`: the capture
    by the tests' reader, verify, replay against the live outputs, modes, the session summary
    against its schema, no surviving worker), and run.json against its schema and the summary;
    returns run.json. CR-R6-F8: written after live closure, run.json says whether the capture is
    complete: true for a COMPLETE footer, false for any other end (SPEC:158)."""
    from hla_support import check_session
    session = ran.summary["result"]["session"]
    pids = [entry["pid"] for entry in log if entry["event"] == "start"]
    (tmp_path / "check").mkdir()
    check_session(tmp_path / "run", session, pids, replay_root=tmp_path / "check")
    document = run_json(tmp_path / "run")
    assert document["command"] == "observe"
    assert document["capture_complete"] is (session["status"] == "COMPLETE")
    assert document["evidence"] == {"offline_replay": "NOT_RUN",
                                    "external_customer_interoperability": "NOT_TESTED"}
    assert document["capture"]["verification"] is None
    assert (document["capture"]["status"], document["capture"]["reason_code"],
            document["capture"]["last_seq"], document["capture"]["sha256"]) == (
        session["status"], session["reason_code"], session["last_seq"],
        session["files"]["capture.jsonl"]["sha256"])
    assert document["session"] == {"terminal_codes": session["terminal_codes"],
                                   "workers": session["workers"],
                                   "last_generation": session["last_generation"]}
    started = document["audit"]["started_at"]
    ended = document["audit"]["ended_at"]
    assert started <= ended
    assert stat_mode(tmp_path / "run" / "run.json") == 0o600
    assert ran.summary["result"]["run_json"] is True
    assert ran.summary["result"]["host"] == "EXITED"
    return document


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_observe_records_until_its_duration_and_exits_0(tmp_path):
    """SPEC:176 and OPS-15: observe joins (the fake worker of round R5), records, and after
    --duration-seconds 1 (counted from the header) stops in order: SIGTERM, resign, disconnect,
    generation_end stop, a COMPLETE footer, exit 0. W_FOM_UNVERIFIED (an existing federation's
    FOM, R11) is reported and does not change the exit (SPEC:184). The directory holds the four
    files, run.json with the audit times of the wall clock (OPS-10)."""
    ran, log = observed(tmp_path, [connect_and_join() + orderly_stop()],
                        "--duration-seconds", "1")
    assert (ran.code, ran.diagnostics) == (0, [])
    assert shape(tmp_path) == [("generation_start", 1, FED), ("generation_end", 1, "stop"),
                               ("footer", "COMPLETE", None, 1)]
    assert ran.summary["codes"] == ["W_FOM_UNVERIFIED"]
    assert held_to_the_session_contract(tmp_path, ran, log)["capture_complete"] is True
    assert sorted(p.name for p in (tmp_path / "run").iterdir()) == [
        "capture.jsonl", "diagnostics.jsonl", "observations.jsonl", "run.json"]
    assert [e["event"] for e in log if e.get("attempt") == 1][-2:] == ["sigterm", "exit"]


@case("G-R36", "A-SIGNAL", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_signal_to_the_command_stops_the_session_in_order_and_exits_0(tmp_path, signum):
    """A-SIGNAL through the command line (OPS-29's addition to R36): SIGINT or SIGTERM sent to
    the synapse-hla process while it records (the default duration, 60 s, would not end it)
    reaches the host through its thin parent, and the host stops in order: the worker gets
    SIGTERM, resigns and disconnects, generation_end stop, COMPLETE, exit 0 (OPS-02: a signalled
    COMPLETE session exits 0, never 130). SIGTERM does exactly what SIGINT does (SPEC:184)."""
    env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()])
    args = ("observe", "--config", config, "--out", tmp_path / "run")
    proc, before = start(tmp_path, *args, env=env)
    deadline = time.monotonic() + 60
    while not any(e["event"] == "waiting" for e in log_of(log)):
        assert time.monotonic() < deadline and proc.poll() is None
        time.sleep(0.01)
    proc.send_signal(signum)
    ran = finish(tmp_path, proc, before, args, creates=["run", "work"])
    assert (ran.code, ran.diagnostics) == (0, [])
    assert shape(tmp_path) == [("generation_start", 1, FED), ("generation_end", 1, "stop"),
                               ("footer", "COMPLETE", None, 1)]
    held_to_the_session_contract(tmp_path, ran, log_of(log))
    assert ("sigterm", 1) in [(e["event"], e.get("attempt")) for e in log_of(log)]


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_a_complete_session_with_an_e_diagnostic_exits_3(tmp_path):
    """SPEC:184 "3 is ... completed capture with E_ diagnostics": a reflection whose EntityType
    has two bytes instead of eight is E_ATTRIBUTE_LENGTH (a recovered data error); the session
    ends COMPLETE and the exit is 3 (OPS-02: no terminal failure, an E_ diagnostic emitted)."""
    steps = connect_and_join() + [frame_step(event_discover("o1")),
                                  frame_step(event_reflect("o1", (("EntityType", "0102"),)))]
    ran, log = observed(tmp_path, [steps + orderly_stop()], "--duration-seconds", "1")
    assert (ran.code, ran.diagnostics) == (3, [])
    assert ran.summary["codes"] == ["E_ATTRIBUTE_LENGTH", "W_FOM_UNVERIFIED"]
    session = ran.summary["result"]["session"]
    assert (session["status"], session["terminal_codes"], session["errors"]) == (
        "COMPLETE", [], {"E_ATTRIBUTE_LENGTH": 1})
    held_to_the_session_contract(tmp_path, ran, log)


@case("G-R36", "G-R07", paragraphs=("SPEC:174", "SPEC:38"))
def test_observe_refuses_a_demo_configuration_before_it_starts_anything(tmp_path):
    """OPS-14 (G-R07's carried clause, SPEC:38): observe joins existing federations only; a mode
    demo configuration (which validate-config accepts) is E_CONFIG at /mode, exit 2, before any
    process starts: no worker ran (not even its --version), no run directory exists."""
    ran, log = observed(tmp_path, [connect_and_join() + orderly_stop()],
                        name="config-demo.json")
    assert (ran.code, only(ran)) == (2, ("E_CONFIG", "/mode"))
    assert log == [] and not (tmp_path / "run").exists()
    assert ran.summary["result"] == {"session": None, "run_json": False, "host": None}


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_observe_refusals_before_the_session(tmp_path):
    """Before anything exists: a configuration that breaks R07 is E_CONFIG at its pointer (2),
    an unreadable --config E_IO (6), an existing --out E_OUTPUT_EXISTS (2, after the pre-flight,
    as run_session orders it); nothing is created and no worker starts recording."""
    env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()],
                                     members={"endpoint": "rti://8.8.8.8:14321"})
    ran = run_cli(tmp_path, "observe", "--config", config, "--out", tmp_path / "run", env=env,
                  creates=["work"])
    assert (ran.code, only(ran)) == (2, ("E_CONFIG", "/endpoint"))
    ran = run_cli(tmp_path, "observe", "--config", tmp_path / "none.json", "--out",
                  tmp_path / "run", env=env, creates=["work"])
    assert (ran.code, only(ran)) == (6, ("E_IO", "--config"))
    good = write(tmp_path / "good.json", (PACKAGE_ROOT / "examples" /
                                          "config-existing.json").read_bytes())
    (tmp_path / "run").mkdir()
    ran = run_cli(tmp_path, "observe", "--config", good, "--out", tmp_path / "run", env=env,
                  creates=["work"])
    assert (ran.code, only(ran)) == (2, ("E_OUTPUT_EXISTS", "--out"))
    assert list((tmp_path / "run").iterdir()) == []
    assert not any(e["event"] == "start" for e in log_of(log))


@case("G-R36", "A-DEPENDENCY", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("what,path", [
    ("missing-worker", "sc-hla-federate"), ("relative-worker", "sc-hla-federate"),
    ("unset-fom", "RPR-Foundation_v2.0.xml"), ("flipped-fom", "RPR-Base_v2.0.xml"),
])
def test_observe_without_its_dependencies_is_exit_4_before_the_run_directory(tmp_path, what,
                                                                            path):
    """OPS-11 and OPS-18: the pre-flight refuses a worker that is not there (or named by a
    relative SYNAPSE_HLA_WORKER, OPV-04) and FOM modules that are absent or changed:
    E_DEPENDENCY_PIN, exit 4, and the run directory never exists (SPEC:293: pins are mandatory
    for observation)."""
    extra = {"missing-worker": {"SYNAPSE_HLA_WORKER": str(tmp_path / "no-worker")},
             "relative-worker": {"SYNAPSE_HLA_WORKER": "sc-hla-federate"},
             "unset-fom": {},
             "flipped-fom": {FOM_DIR_VARIABLE: str(flipped_fom(tmp_path))
                             if what == "flipped-fom" else ""}}[what]
    env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()])
    if what == "unset-fom":
        del env[FOM_DIR_VARIABLE]
    env.update(extra)
    ran = run_cli(tmp_path, "observe", "--config", config, "--out", tmp_path / "run", env=env,
                  creates=["work", "fom"])
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", path))
    assert not (tmp_path / "run").exists()
    # CR-R6-F4: the FOM modules are refused by the command's own pre-flight, before any host
    # exists; the worker only by the host's (OPV-04: it is the session's dependency).
    host_state = None if what in ("unset-fom", "flipped-fom") else "EXITED"
    assert ran.summary["result"] == {"session": None, "run_json": False, "host": host_state}


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_a_worker_that_cannot_be_started_again_is_exit_4(tmp_path):
    """CR-R5-20: the worker is removed during the session (it unlinks itself, then its connection
    is refused): the retry cannot start it, the capture records E_DEPENDENCY_PIN and ends FAILED
    with it, and the exit is its class, 4."""
    steps = [stage("connect"), {"do": "unlink_self"}, fail("E_RTI_CONNECT", "refused"),
             frame_step(event_diagnostic("E_RTI_CONNECT", "refused")), {"do": "exit", "code": 1}]
    ran, log = observed(tmp_path, [steps], "--duration-seconds", "30")
    assert (ran.code, only(ran)) == (4, ("E_DEPENDENCY_PIN", None))
    assert shape(tmp_path)[-1] == ("footer", "FAILED", "E_DEPENDENCY_PIN", 0)
    held_to_the_session_contract(tmp_path, ran, log)


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("steps,code,end", [
    ([stage("connect"), stage("running"), stage("join"), fail("E_FEDERATE_NAME", "in use"),
      frame_step(event_diagnostic("E_FEDERATE_NAME", "in use")), {"do": "exit", "code": 1}],
     "E_FEDERATE_NAME", None),
    (connect_and_join() + [fail("E_FOM_PROFILE", "Spatial not found"),
                           frame_step(event_diagnostic("E_FOM_PROFILE", "Spatial not found")),
                           {"do": "exit", "code": 1}],
     "E_FOM_PROFILE", "failure"),
], ids=["federate-name", "fom-profile"])
def test_an_rti_failure_that_is_never_retried_is_exit_5(tmp_path, steps, code, end):
    """SPEC:62 and OPS-02: a name conflict or a profile error is never retried; the session ends
    FAILED with its code, which is class 5; stderr names the terminal failure. Started with the
    largest duration SPEC:184 admits, 86400, which the parser therefore accepts."""
    ran, log = observed(tmp_path, [steps], "--duration-seconds", "86400")
    assert (ran.code, only(ran)) == (5, (code, None))
    last = shape(tmp_path)[-2:]
    assert last[-1] == ("footer", "FAILED", code, 1 if end else 0)
    if end:
        assert last[0] == ("generation_end", 1, end)
    held_to_the_session_contract(tmp_path, ran, log)


@case("G-R36", "A-RECONNECT", paragraphs=("SPEC:174", "SPEC:184"))
def test_a_stop_during_a_reconnect_backoff_is_failed_with_the_connection_code(tmp_path):
    """OPS-15: the duration (1 s from the header) ends during the 1 s backoff after a refused
    connection: the session ends FAILED with the last connection code, E_RTI_CONNECT, exit 5;
    one worker, no generation."""
    ran, log = observed(tmp_path, [connect_refused(), connect_refused()],
                        "--duration-seconds", "1")
    assert (ran.code, only(ran)) == (5, ("E_RTI_CONNECT", None))
    assert shape(tmp_path) == [("diagnostic", 0, "E_RTI_CONNECT", None, None),
                               ("footer", "FAILED", "E_RTI_CONNECT", 0)]
    assert ran.summary["result"]["session"]["workers"] == 1
    held_to_the_session_contract(tmp_path, ran, log)


@case("G-R36", "A-TIMEOUT", paragraphs=("SPEC:174", "SPEC:184"))
def test_a_stop_that_needs_force_is_e_rti_timeout_and_exit_5(tmp_path):
    """SPEC:184 "forced termination cannot produce COMPLETE" (OPS-25): the worker ignores the
    orderly stop; after the 10 s host deadline it is killed: E_RTI_TIMEOUT, generation_end
    timeout, FAILED E_RTI_TIMEOUT, exit 5. (The real deadline: the command line has no seam.)"""
    ran, log = observed(tmp_path, [connect_and_join() + [{"do": "wait_term"}, STALL]],
                        "--duration-seconds", "1")
    assert (ran.code, only(ran)) == (5, ("E_RTI_TIMEOUT", None))
    assert shape(tmp_path) == [("generation_start", 1, FED),
                               ("diagnostic", 1, "E_RTI_TIMEOUT", None, None),
                               ("generation_end", 1, "timeout"),
                               ("footer", "FAILED", "E_RTI_TIMEOUT", 1)]
    assert held_to_the_session_contract(tmp_path, ran, log)["capture_complete"] is False


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("steps,code", [
    (connect_and_join() + [fail("E_LIMIT", "a value over 4096 bytes"),
                           frame_step(event_diagnostic("E_LIMIT", "a value over 4096 bytes")),
                           {"do": "exit", "code": 1}], "E_LIMIT"),
    (connect_and_join() + [fail("E_QUEUE_OVERFLOW", "the callback queue is full"),
                           {"do": "exit", "code": 1}], "E_QUEUE_OVERFLOW"),
], ids=["limit", "queue-overflow"])
def test_a_resource_failure_is_exit_6(tmp_path, steps, code):
    """OPS-02 class 6: a limit the worker reports and a queue overflow reported on the status
    channel alone end the session FAILED (generation_end limit, NAT-08), exit 6."""
    ran, log = observed(tmp_path, [steps], "--duration-seconds", "30")
    assert (ran.code, only(ran)) == (6, (code, None))
    assert shape(tmp_path)[-2:] == [("generation_end", 1, "limit"),
                                    ("footer", "FAILED", code, 1)]
    held_to_the_session_contract(tmp_path, ran, log)


#: The command line under a file-size limit of 16384 bytes (A-DISK's process-level stimulus).
FSIZE_DRIVER = (sys.executable, "-c",
                "import resource, runpy; "
                "resource.setrlimit(resource.RLIMIT_FSIZE, (16384, 16384)); "
                "runpy.run_module('synapse_hla.cli', run_name='__main__')")


@case("G-R36", "A-DISK", paragraphs=("SPEC:174", "SPEC:184"))
def test_a_capture_that_cannot_be_written_is_e_io_and_exit_6(tmp_path):
    """OPS-24 through the command line: under RLIMIT_FSIZE 16384 the capture stops growing
    (EFBIG) while discoveries arrive; the capture is broken, no footer is claimed (SPEC:293),
    the session summary is INCOMPLETE with E_IO, and the exit is 6 (OPS-02). The capture holds
    a verifiable prefix."""
    burst = {"do": "frames", "count": 200, "first": 1, "numbered": True,
             "event": event_discover("o1")}
    ran, log = observed(tmp_path, [connect_and_join() + [burst, STALL]], "--duration-seconds",
                        "30", prefix=FSIZE_DRIVER)
    assert (ran.code, only(ran)) == (6, ("E_IO", None))
    session = ran.summary["result"]["session"]
    assert (session["status"], session["terminal_codes"]) == ("INCOMPLETE", ["E_IO"])
    assert (tmp_path / "run" / "capture.jsonl").stat().st_size <= 16384
    assert held_to_the_session_contract(tmp_path, ran, log)["capture_complete"] is False


# ============================================================================ the thin RSS parent (OPS-23)

#: A stand-in for the host process: it starts a "worker" in a process group of its own, reports
#: it the way the host's child reports its workers, records what it does in a file, and either
#: waits to be killed, or, told to, waits for a forwarded signal and reports a result, or ends
#: without a result: killed by SIGKILL ("die") or exiting with status 3 ("exit").
FAKE_HOST = r"""
import json, os, signal, subprocess, sys, time
report, record, mode = int(sys.argv[1]), sys.argv[2], sys.argv[3]
def note(text):
    with open(record, "a") as stream:
        stream.write(text + "\n")
def send(message):
    os.write(report, (json.dumps(message) + "\n").encode())
got = []
signal.signal(signal.SIGTERM, lambda s, f: (got.append(s), note("signal %d" % s)))
time.sleep(0.4)
worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                          start_new_session=True)
note("worker %d" % worker.pid)
send({"worker": worker.pid, "running": True})
note("announced")
if mode == "die":
    os.kill(os.getpid(), signal.SIGKILL)
if mode == "exit":
    os._exit(3)
if mode == "wait":
    time.sleep(120)
deadline = time.monotonic() + 30
while not got and time.monotonic() < deadline:
    time.sleep(0.01)
worker.kill()
worker.wait()
send({"worker": worker.pid, "running": False})
send({"stderr": "{\"x\":1}\n"})
send({"result": {"exit_code": 0, "codes": [], "result": {"session": None, "run_json": False,
                                                          "host": "EXITED"}}})
"""


def fake_host(tmp_path, mode):
    from hla_support import child_environment
    read_fd, write_fd = os.pipe()
    record = tmp_path / "host.log"
    proc = subprocess.Popen([sys.executable, "-c", FAKE_HOST, str(write_fd), str(record), mode],
                            pass_fds=(write_fd,), start_new_session=True,
                            env=child_environment())
    os.close(write_fd)
    return proc, read_fd, record


@case("G-R36", "G-R41", paragraphs=("SPEC:184",))
def test_the_rss_parent_kills_the_host_and_its_workers_above_the_limit(tmp_path, capfd):
    """OPS-23 and R41: the command line's thin parent reads the host's resident memory (the
    probe of `host.HostSeams`, here a test's, every 20 ms) and, once it is above 512 MiB (here
    the third reading, one byte above), stops the host, kills the worker the host reported (a
    process group of its own, CR-new-R5-04) and the host's group, writes E_LIMIT on stderr and
    the summary on stdout, and returns 6. A reading of exactly 512 MiB is not above the limit.
    The real limit cannot be reached by a test (OPS-21: the seam, and only a test passes it)."""
    import dataclasses

    from synapse_hla import cli, host
    from synapse_hla.limits import V1 as LIMITS
    proc, read_fd, record = fake_host(tmp_path, "wait")
    readings = []

    def rss_of(pid):
        readings.append(pid)
        if len(readings) < 3 or not record.exists() or "announced" not in record.read_text():
            return LIMITS.host_rss_bytes
        return LIMITS.host_rss_bytes + 1
    seams = dataclasses.replace(host.V1, rss_of=rss_of, rss_poll_ns=20_000_000)
    try:
        code = cli.supervise_host(proc.pid, read_fd, cli._Output(), seams=seams)
    finally:
        os.close(read_fd)
        # supervise_host reaped the process itself; Popen learns it here (ECHILD).
        proc.wait()
    worker = int(record.read_text().split("worker ")[1].split()[0])
    assert code == 6
    assert set(readings) == {proc.pid} and len(readings) >= 3
    assert process_gone(proc.pid) and process_gone(worker)
    out, err = capfd.readouterr()
    diagnostic = strict_json(err.encode().splitlines()[0])
    assert (diagnostic["code"], diagnostic["path"]) == ("E_LIMIT", None)
    summary = strict_json(out.encode())
    assert not list(SUMMARY.iter_errors(summary))
    assert (summary["exit_code"], summary["codes"], summary["result"]) == (
        6, ["E_LIMIT"], {"session": None, "run_json": False, "host": "KILLED_FOR_RSS"})


@case("G-R36", paragraphs=("SPEC:184",))
def test_the_parent_holds_a_stop_until_the_session_runs_then_passes_it_on(tmp_path, capfd):
    """SIGTERM to the command line before the host's session has started a worker is held (the
    host's pre-flight is not interrupted; CR-new-R5-18: the session's handlers exist only while
    it runs); once the host reports its first worker the stop is passed on, and the host's result
    becomes the command's summary and exit. Here the signal comes 0.1 s after the start and the
    host announces its worker at 0.4 s: it must see the signal after the announcement."""
    import threading

    from synapse_hla import cli
    proc, read_fd, record = fake_host(tmp_path, "signal")
    timer = threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    previous = signal.signal(signal.SIGTERM, lambda *_: None)
    try:
        timer.start()
        code = cli.supervise_host(proc.pid, read_fd, cli._Output())
    finally:
        timer.join()
        signal.signal(signal.SIGTERM, previous)
        os.close(read_fd)
        proc.wait()
    assert code == 0
    lines = record.read_text().splitlines()
    assert lines[1:] == ["announced", "signal 15"], lines
    assert signal.getsignal(signal.SIGTERM) is previous
    out, err = capfd.readouterr()
    assert err == '{"x":1}\n'
    assert strict_json(out.encode())["exit_code"] == 0


# ============================================================================ defects and --debug

def driven(patch: str) -> tuple:
    """The command line's own module run as __main__ after `patch` (Python source) has injected a
    defect into the product: the real entry point, a broken product."""
    return (sys.executable, "-c",
            patch + "\nimport runpy\nrunpy.run_module('synapse_hla.cli', run_name='__main__')")


#: The Entity check both projector entries run (`_check_entity`, since CR-L17 the reducer's
#: entry no longer goes through `check_entity_payload`), broken.
PROJECTION_DEFECT = ("import synapse_hla.projector as p\n"
                     "def broken(payload, **_):\n"
                     "    raise p.ProjectionDefect('an injected defect')\n"
                     "p._check_entity = broken")


@case("G-R36", paragraphs=("SPEC:174",))
@pytest.mark.parametrize("debug", [False, True], ids=["plain", "debug"])
def test_a_defect_is_python_s_traceback_and_status_1_whatever_debug_says(tmp_path, debug):
    """CR-R3-07 and CR-R4-11: an exception that is not HlaError escaping a command is a defect;
    the command line does not turn it into a diagnostic: Python's traceback, exit status 1,
    nothing on stdout, with or without --debug. The replay's directory is removed (R35)."""
    args = ["replay", "--capture", fixture_capture(tmp_path), "--out", tmp_path / "run"]
    if debug:
        args.append("--debug")
    ran = run_cli(tmp_path, *args, prefix=driven(PROJECTION_DEFECT), ended="defect")
    assert b"ProjectionDefect: an injected defect" in ran.stderr
    assert not (tmp_path / "run").exists()


@case("G-R36", paragraphs=("SPEC:174",))
def test_a_defect_in_the_host_reaches_the_command_line_as_a_traceback(tmp_path):
    """The same for observe, whose host is a child process: a ReducerDefect inside the session
    (injected into the reducer's entry) is the host's traceback on stderr and exit 1, and no
    worker survives."""
    patch = ("import synapse_hla.reducer as r\n"
             "def broken(state, record):\n"
             "    raise r.ReducerDefect('an injected defect')\n"
             "r.reduce_admitted = broken")
    ran, log = observed(tmp_path, [connect_and_join() + orderly_stop()],
                        "--duration-seconds", "5", prefix=driven(patch), ended="defect")
    assert b"ReducerDefect: an injected defect" in ran.stderr
    assert all(process_gone(e["pid"]) for e in log if e["event"] == "start")


@case("G-R36", paragraphs=("SPEC:174",))
def test_debug_adds_the_traceback_of_a_refusal_and_nothing_else_does(tmp_path):
    """R36 "no tracebacks unless --debug is explicit": the same refusal (a missing capture, E_IO
    at --capture, exit 6) writes one JSON line without --debug and the JSON line followed by its
    traceback with it; stdout is the same summary either way."""
    missing = tmp_path / "none.jsonl"
    plain = run_cli(tmp_path, "verify", "--capture", missing)
    debug = run_cli(tmp_path, "--debug", "verify", "--capture", missing)
    flagged = run_cli(tmp_path, "verify", "--capture", missing, "--debug")
    assert plain.code == debug.code == flagged.code == 6
    assert len(plain.stderr.splitlines()) == 1 and b"Traceback" not in plain.stderr
    for ran in (debug, flagged):
        first, rest = ran.stderr.split(b"\n", 1)
        assert first + b"\n" == plain.stderr
        assert rest.startswith(b"Traceback (most recent call last):")
        assert b"HlaError: E_IO at capture_path" in rest
        assert ran.stdout == plain.stdout


# ============================================================================ interrupted commands

def long_capture(tmp_path) -> pathlib.Path:
    """2000 eligible reflections: long enough to be interrupted while it is replayed."""
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start()).frame(1, 0, event_discover("o1"))
    for n in range(2000):
        builder.frame(1, SECOND, event_reflect("o1", FULL))
    builder.frame(1, SECOND, event_generation_end()).footer()
    return builder.write(tmp_path / "long.jsonl")


@case("G-R36", paragraphs=("SPEC:184",))
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_an_interrupted_replay_takes_back_what_it_made(tmp_path, signum):
    """SPEC:184 "SIGTERM performs the same bounded orderly shutdown as SIGINT": a replay stopped
    by either signal while it writes removes its directory (R35: a refused replay leaves nothing
    behind), prints nothing, no traceback, and exits 128 plus the signal's number."""
    capture_path = long_capture(tmp_path)
    args = ("replay", "--capture", capture_path, "--out", tmp_path / "run")
    proc, before = start(tmp_path, *args)
    deadline = time.monotonic() + 60
    while not (tmp_path / "run" / "observations.jsonl").exists():
        assert time.monotonic() < deadline and proc.poll() is None
        time.sleep(0.005)
    proc.send_signal(signum)
    ran = finish(tmp_path, proc, before, args, ended="interrupted")
    assert ran.code == 128 + signum
    assert not (tmp_path / "run").exists()


# ============================================================================ the exit classes

@case("G-R36", paragraphs=("SPEC:184",))
def test_every_e_code_has_the_exit_class_ops_02_gives_it():
    """OPS-02 written out (`CLASSES`, from the ruling's text) against the product's table and the
    command line's rule: the highest class among terminal failures; with none, 3 when an E_
    diagnostic was emitted, else 0; W_ codes have no class and never change an exit."""
    from synapse_hla import cli, errors
    assert dict(errors.EXIT_CLASS) == CLASSES
    for code, cls in CLASSES.items():
        assert cli._exit_code([code], False) == cls
        assert cli._exit_code([code], True) == cls
    assert cli._exit_code([], False) == 0 and cli._exit_code([], True) == 3
    assert cli._exit_code(["E_CONFIG", "E_LIMIT", "E_RTI_CONNECT"], True) == 6
    assert cli._exit_code(["E_CAPTURE_SCHEMA", "E_DEPENDENCY_PIN"], False) == 4
    assert cli._exit_code(["E_RTI_TIMEOUT", "E_DEPENDENCY_PIN", "E_CONFIG"], False) == 5
    for code in ("W_FOM_UNVERIFIED", "W_TIME_UNRESOLVED", "W_FORCE_UNMAPPED",
                 "W_DUPLICATE_DISCOVERY", "W_DUPLICATE_REMOVE"):
        with pytest.raises(KeyError):
            cli._exit_code([code], False)


def _session(*events) -> CaptureBuilder:
    builder = CaptureBuilder().frame(1, 0, event_generation_start())
    builder.frame(1, 0, event_discover("o1")).frame(1, 0, event_discover("o2"))
    for event in events:
        builder.frame(1, SECOND, event)
    return builder.frame(1, SECOND, event_generation_end()).footer()


def _reflect(token="o1", **replaced):
    attributes = dict(FULL)
    attributes.update(replaced)
    return event_reflect(token, tuple(sorted(attributes.items())))


DATA_CODES = [
    ("E_ATTRIBUTE_LENGTH", _session(_reflect(EntityType="0102"))),
    ("E_NONFINITE", _session(_reflect(Spatial=BAD["NONFINITE-8"]))),
    ("E_BOOLEAN", _session(_reflect(Spatial=BAD["BOOL-2"]))),
    ("E_SPATIAL_VARIANT", _session(_reflect(Spatial=BAD["ALG-10"]))),
    ("E_UNSUBSCRIBED_ATTRIBUTE", _session(event_reflect("o1", (("Marking", "00"),)))),
    ("E_NULL_ID", _session(_reflect(EntityIdentifier="000000000000"))),
    ("E_ECEF_RANGE", _session(_reflect(Spatial=encode_spatial(1, (0.0, 0.0, 0.0)).hex()))),
    ("E_IDENTITY_CHANGED", _session(_reflect(), _reflect(EntityIdentifier="000100020004"))),
    ("E_IDENTITY_COLLISION", _session(_reflect("o1"), _reflect("o2"))),
    ("E_RETRACTION_UNSUPPORTED", _session(event_reflect("o1", FULL, retractable=True))),
    ("E_UNKNOWN_OBJECT", _session(event_reflect("o9", FULL))),
    ("E_RTI_CONNECT", _session(event_diagnostic("E_RTI_CONNECT", "connection lost"))),
]
WARNING_CODES = [
    ("W_FOM_UNVERIFIED", CaptureBuilder(header_with(
        mode="existing", profile_declaration="external-fom-unverified", synthetic=True))
     .frame(1, 0, event_generation_start()).frame(1, 0, event_generation_end()).footer()),
    ("W_TIME_UNRESOLVED", CaptureBuilder(header_with(time_policy={"mode": "none"}))
     .frame(1, 0, event_generation_start()).frame(1, 0, event_discover("o1"))
     .frame(1, 0, event_reflect("o1", FULL)).frame(1, 0, event_generation_end()).footer()),
    ("W_FORCE_UNMAPPED", _session(_reflect(ForceIdentifier="02"))),
    ("W_DUPLICATE_DISCOVERY", _session(event_discover("o1"))),
    ("W_DUPLICATE_REMOVE", _session(event_remove("o1"), event_remove("o1"))),
]


@case("G-R36", paragraphs=("SPEC:184",))
@pytest.mark.parametrize("code,builder", DATA_CODES, ids=[c for c, _ in DATA_CODES])
def test_a_complete_capture_whose_records_hold_an_e_code_replays_with_exit_3(tmp_path, code,
                                                                             builder):
    """SPEC:184 and OPS-02 for every code a COMPLETE capture can produce in replay: a decoder,
    projection or quarantine error, an unknown object, or a recovered RTI failure the capture
    holds, is an E_ diagnostic of the output; the replay completes (PASS evidence: the capture is
    complete) and exits 3. E_TIME_REGRESSION and E_GEODESY cannot come from a verified capture
    (RED-09, COD-12); their class is held by the table test above."""
    capture_path = builder.write(tmp_path / "capture.jsonl")
    ran = run_cli(tmp_path, "replay", "--capture", capture_path, "--out", tmp_path / "run",
                  creates=["run"])
    assert (ran.code, ran.diagnostics) == (3, [])
    assert code in ran.summary["result"]["replay"]["errors"]
    assert ran.summary["result"]["offline_replay"] == "PASS"
    assert code in run_json(tmp_path / "run")["error_counts"]


@case("G-R36", paragraphs=("SPEC:184",))
@pytest.mark.parametrize("code,builder", WARNING_CODES, ids=[c for c, _ in WARNING_CODES])
def test_w_codes_alone_allow_exit_0(tmp_path, code, builder):
    """SPEC:184 "W_ diagnostics alone allow 0": each warning, alone in a COMPLETE capture."""
    capture_path = builder.write(tmp_path / "capture.jsonl")
    ran = run_cli(tmp_path, "replay", "--capture", capture_path, "--out", tmp_path / "run",
                  creates=["run"])
    assert (ran.code, ran.diagnostics) == (0, [])
    assert ran.summary["result"]["replay"]["errors"] == {}
    assert code in ran.summary["result"]["replay"]["warnings"]
    assert ran.summary["codes"] == sorted(ran.summary["result"]["replay"]["warnings"])


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
def test_a_run_json_that_cannot_be_written_is_e_io_and_exit_6(tmp_path):
    """OPS-10 with OPS-02: the session ended COMPLETE, but its manifest cannot be written (the
    writer is made to fail here): E_IO at --out, exit 6 (the highest class), and the summary
    says run.json was not written."""
    # The console script's own call, `main()`, on the module with its writer replaced (runpy
    # would execute a fresh copy of the module and lose the replacement).
    patch = ("import sys\n"
             "import synapse_hla.cli as c\n"
             "from synapse_hla.errors import HlaError\n"
             "def broken(out_path, data):\n"
             "    raise HlaError('E_IO', '--out', 'run.json cannot be written')\n"
             "c._write_run_file = broken\n"
             "sys.exit(c.main(sys.argv[1:]))")
    ran, log = observed(tmp_path, [connect_and_join() + orderly_stop()], "--duration-seconds",
                        "1", prefix=(sys.executable, "-c", patch))
    assert (ran.code, only(ran)) == (6, ("E_IO", "--out"))
    assert ran.summary["result"]["run_json"] is False
    assert ran.summary["result"]["session"]["status"] == "COMPLETE"
    assert not (tmp_path / "run" / "run.json").exists()


# ============================================================================ the guards themselves

def test_the_write_guard_refuses_a_write_outside_the_test_directory(tmp_path):
    """Exit criterion 4's guard checked: a child with the guard refuses to open a file for
    writing, make a directory or rename into a place outside the test's directory (the attempt
    never happens), logs each attempt, and lets the same operations through inside it."""
    from hla_support import child_environment
    outside = tmp_path.parent / f"guard-probe-{os.getpid()}-{tmp_path.name}"
    inside = tmp_path / "inside"
    log = tmp_path / "write-guard.log"
    env = environment(tmp_path)
    probe = (f"import os\n"
             f"open({str(inside)!r}, 'w').close()\n"
             f"os.mkdir({str(inside) + '-dir'!r})\n"
             f"for attempt in (lambda: open({str(outside)!r}, 'w'),\n"
             f"                lambda: os.open({str(outside)!r}, os.O_WRONLY | os.O_CREAT),\n"
             f"                lambda: os.mkdir({str(outside)!r}),\n"
             f"                lambda: os.rename({str(inside)!r}, {str(outside)!r})):\n"
             f"    try:\n"
             f"        attempt()\n"
             f"    except RuntimeError as error:\n"
             f"        print(type(error).__name__)\n")
    proc = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["WriteGuardError"] * 4
    assert not outside.exists() and inside.exists() and (tmp_path / "inside-dir").exists()
    assert [line.split()[0] for line in log.read_text().splitlines()] == [
        "open", "open", "os.mkdir", "os.rename"]
    assert child_environment  # the plain child environment has no write guard at all


def test_the_examples_travel_in_the_package_byte_for_byte():
    """self-test reads the two example configurations from the package (`_examples`), since an
    installed package has no `examples/` directory; they are the files of `examples/` byte for
    byte, which test_hla_contract holds to the bundle."""
    from synapse_hla import _examples
    assert _examples.EXAMPLES == (
        ("config-demo.json", (PACKAGE_ROOT / "examples" / "config-demo.json").read_bytes()),
        ("config-existing.json",
         (PACKAGE_ROOT / "examples" / "config-existing.json").read_bytes()))


def test_the_run_files_have_the_names_replay_and_the_host_give_them():
    from synapse_hla import _runfile, _writer
    from synapse_hla.replay import FILES, RUN_FILE
    assert (_runfile.CAPTURE, _runfile.OBSERVATIONS, _runfile.DIAGNOSTICS) == FILES == \
        _writer.FILES == ("capture.jsonl", "observations.jsonl", "diagnostics.jsonl")
    assert RUN_FILE == "run.json"


# ============================================================================ R6F: the review's findings
#
# The fix pass after the R6 review (`DECISIONS.md` C.8): CR-R6-F1 (a decided exit code stays),
# CR-R6-F2 (the host stops when the command is killed), CR-R6-F3 (a host without a result is a
# defect), CR-R6-F4 (observe's pre-flight), R6-r1-F7 (the cleanup of interrupted commands). The
# children that must be held at a moment run under GATE: the command line imported as a module
# and its `main()` called as the console script calls it, with one patch that writes a marker
# file when the moment has come and holds there (the stimulus, a real signal, comes from the
# test).

GATE = (sys.executable, "-c", r"""
import atexit, os, pathlib, sys, time
mark = pathlib.Path(os.environ["SC_HLA_GATE_MARK"])
moment = os.environ["SC_HLA_GATE_AT"]
import synapse_hla.cli as cli


def noted():
    # The command's own handler noted the test's signal (it only notes, CR-new-R6-05).
    end = time.monotonic() + 60
    while cli._STOPPED["signum"] is None:
        if time.monotonic() > end:
            raise SystemExit("the gate waited for a signal that never came")
        time.sleep(0.005)


def told():
    # The test says it is done (it created the file named by SC_HLA_GATE_GO).
    go = pathlib.Path(os.environ["SC_HLA_GATE_GO"])
    end = time.monotonic() + 60
    while not go.exists() and time.monotonic() < end:
        time.sleep(0.005)


if moment == "exit":
    def at_exit():
        mark.write_text(moment)
        told()
    atexit.register(at_exit)
elif moment in ("self-test-after-replay", "self-test-during-replay"):
    import synapse_hla._selftest as selftest
    real = selftest.run

    def run(target, fom_dir, *, synapse_cdm_version, check):
        if moment == "self-test-after-replay":
            report = real(target, fom_dir, synapse_cdm_version=synapse_cdm_version, check=check)
            mark.write_text(moment)
            noted()
            return report

        def gate():
            if not mark.exists() and os.path.exists(os.path.join(target, b"observations.jsonl")):
                mark.write_text(moment)
                noted()
            check()
        return real(target, fom_dir, synapse_cdm_version=synapse_cdm_version, check=gate)
    selftest.run = run
elif moment == "demo":
    import synapse_hla.host as host
    real = host.locate_worker

    def locate_worker(environ):
        mark.write_text(moment)
        noted()
        return real(environ)
    host.locate_worker = locate_worker
elif moment == "export":
    real = cli._write_all
    calls = []

    def write_all(fd, data, option):
        calls.append(1)
        if len(calls) == 3:
            mark.write_text(moment)
            noted()
        return real(fd, data, option)
    cli._write_all = write_all
sys.exit(cli.main())
""")


def gated(tmp_path, moment: str, env: dict | None = None) -> tuple[dict, pathlib.Path,
                                                                 pathlib.Path]:
    """The environment of a GATE child held at `moment`; its marker and go files."""
    mark, go = tmp_path / "gate.mark", tmp_path / "gate.go"
    env = dict(env if env is not None else environment(tmp_path))
    env.update({"SC_HLA_GATE_MARK": str(mark), "SC_HLA_GATE_GO": str(go),
                "SC_HLA_GATE_AT": moment})
    return env, mark, go


def wait_for(condition, proc, what: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, f"no {what}"
        assert proc.poll() is None, f"the command ended before {what}: {proc.returncode}"
        time.sleep(0.005)


def waiting(log: pathlib.Path):
    return lambda: any(e["event"] == "waiting" for e in log_of(log))


# --- CR-R6-F1: once the exit code is decided, a stop signal changes nothing

@case("G-R36", "A-SIGNAL", paragraphs=("SPEC:184",))
def test_stop_signals_through_the_end_of_an_observe_session_leave_its_exit_0(tmp_path):
    """CR-R6-F1 as the lead rules the test: from the moment the worker waits until the command
    has ended, SIGINT and SIGTERM in turn every 2 ms: the first stops the session in order, the
    later ones reach the host (which notes only the first, OPS-25) and the command after its
    summary; the exit is 0, as the summary says, and the session is COMPLETE (OPS-02: a
    signal-terminated COMPLETE session exits 0, never 130)."""
    env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()])
    args = ("observe", "--config", config, "--out", tmp_path / "run")
    proc, before = start(tmp_path, *args, env=env)
    wait_for(waiting(log), proc, "waiting worker")
    sent = 0
    while proc.poll() is None:
        proc.send_signal((signal.SIGINT, signal.SIGTERM)[sent % 2])
        sent += 1
        time.sleep(0.002)
    ran = finish(tmp_path, proc, before, args, creates=["run", "work"])
    assert sent >= 2
    assert (ran.code, ran.summary["exit_code"], ran.diagnostics) == (0, 0, [])
    assert shape(tmp_path) == [("generation_start", 1, FED), ("generation_end", 1, "stop"),
                               ("footer", "COMPLETE", None, 1)]
    assert held_to_the_session_contract(tmp_path, ran, log_of(log))["capture_complete"] is True


@case("G-R36", paragraphs=("SPEC:184",))
@pytest.mark.parametrize("scenario", ["validate-config", "observe", "replay-interrupted"])
def test_a_stop_signal_after_the_exit_code_is_decided_changes_nothing(tmp_path, scenario):
    """CR-R6-F1, deterministically: the program is held at its very end (an atexit hook of the
    GATE child, after `main` has returned its code and while the interpreter shuts down), then
    gets SIGTERM and SIGINT. Python's default handlers would end it by SIGTERM there; the
    program ignores both once its code is decided, so the exit is the decided one: 0 for a
    validate-config of the example configuration, 0 for an observe session stopped in order by
    a SIGTERM before, and 130 for a replay interrupted by SIGINT before (nothing printed, nothing
    left)."""
    if scenario == "validate-config":
        config = write(tmp_path / "config.json", (PACKAGE_ROOT / "examples" /
                                                  "config-demo.json").read_bytes())
        env, mark, go = gated(tmp_path, "exit")
        args = ("validate-config", "--config", config)
        proc, before = start(tmp_path, *args, env=env, prefix=GATE)
        creates, decided, ended = ["gate.mark", "gate.go"], 0, None
    elif scenario == "observe":
        env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()])
        env, mark, go = gated(tmp_path, "exit", env)
        args = ("observe", "--config", config, "--out", tmp_path / "run")
        proc, before = start(tmp_path, *args, env=env, prefix=GATE)
        wait_for(waiting(log), proc, "waiting worker")
        proc.send_signal(signal.SIGTERM)
        creates, decided, ended = ["gate.mark", "gate.go", "run", "work"], 0, None
    else:
        capture_path = long_capture(tmp_path)
        env, mark, go = gated(tmp_path, "exit")
        args = ("replay", "--capture", capture_path, "--out", tmp_path / "run")
        proc, before = start(tmp_path, *args, env=env, prefix=GATE)
        wait_for(lambda: (tmp_path / "run" / "observations.jsonl").exists(), proc,
                 "replay output")
        proc.send_signal(signal.SIGINT)
        creates, decided, ended = ["gate.mark", "gate.go"], 128 + signal.SIGINT, "interrupted"
    wait_for(mark.exists, proc, "program at its end")
    proc.send_signal(signal.SIGTERM)
    proc.send_signal(signal.SIGINT)
    time.sleep(0.2)
    go.write_text("go")
    ran = finish(tmp_path, proc, before, args, creates=creates, ended=ended)
    assert ran.code == decided
    if ended is None:
        assert ran.summary["exit_code"] == decided
    if scenario == "observe":
        assert ran.summary["result"]["session"]["status"] == "COMPLETE"
    if scenario == "replay-interrupted":
        assert not (tmp_path / "run").exists()


# --- CR-R6-F2: a command killed from outside; CR-R6-F3: a host that ends without a result

def capture_ended(path: pathlib.Path) -> bool:
    """Whether the capture's last complete line is a footer."""
    if not path.exists():
        return False
    lines = path.read_bytes().split(b"\n")[:-1]
    return bool(lines) and strict_json(lines[-1]).get("type") == "footer"


@case("G-R36", paragraphs=("SPEC:184",))
def test_a_command_killed_from_outside_leaves_a_session_stopped_in_order_without_run_json(
        tmp_path):
    """CR-R6-F2 (the reviewer's orphan probe as a test): observe records with a duration of 30 s;
    the command itself is killed by SIGKILL. Its host sees its parent change at the next poll
    tick and stops in order, as a SIGTERM would: the worker gets SIGTERM, resigns, disconnects and
    exits 0; generation_end stop and a COMPLETE footer within 10 s (the duration would have taken
    30); the host and the worker are gone; and there is no run.json, the mark of a run whose
    command did not see its end. The capture verifies COMPLETE."""
    env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()])
    args = ("observe", "--config", config, "--out", tmp_path / "run", "--duration-seconds", "30")
    proc, before = start(tmp_path, *args, env=env)
    wait_for(waiting(log), proc, "waiting worker")
    (started,) = [e for e in log_of(log) if e["event"] == "start"]
    host_pid, worker_pid = started["ppid"], started["pid"]
    proc.kill()
    assert proc.wait(timeout=30) == -signal.SIGKILL
    capture_path = tmp_path / "run" / "capture.jsonl"
    deadline = time.monotonic() + 10
    while not capture_ended(capture_path):
        assert time.monotonic() < deadline, "the session went on without its command"
        time.sleep(0.02)
    assert process_gone(host_pid) and process_gone(worker_pid)
    stdout, stderr = proc.communicate(timeout=30)
    assert (stdout, stderr) == (b"", b"")
    assert shape(tmp_path) == [("generation_start", 1, FED), ("generation_end", 1, "stop"),
                               ("footer", "COMPLETE", None, 1)]
    assert sorted(p.name for p in (tmp_path / "run").iterdir()) == [
        "capture.jsonl", "diagnostics.jsonl", "observations.jsonl"]
    assert [(e["event"], e.get("code")) for e in log_of(log) if e.get("attempt") == 1][-2:] == [
        ("sigterm", None), ("exit", 0)]
    from synapse_hla import verify_capture
    assert verify_capture(capture_path)["status"] == "COMPLETE"
    assert not (tmp_path / "write-guard.log").exists()
    assert list((tmp_path / "cwd").iterdir()) == []
    new = tree(tmp_path) - before
    assert all(p.split(os.sep)[0] in ("run", "work") for p in new), sorted(new)


@case("G-R36", paragraphs=("SPEC:184",))
def test_a_host_killed_from_outside_is_a_defect_of_the_command_and_its_worker_is_killed(
        tmp_path):
    """CR-R6-F3 (the reviewer's host-kill probe as a test): the observe host is killed by SIGKILL
    while its worker waits. The command cannot give a summary: it kills the worker it was told
    about and fails as a defect (CR-R3-07's path): exit status 1, nothing on stdout, a traceback
    on stderr naming HostEndedWithoutResult and how the host ended (SIGKILL). The capture has no
    footer."""
    env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()])
    args = ("observe", "--config", config, "--out", tmp_path / "run")
    proc, before = start(tmp_path, *args, env=env)
    wait_for(waiting(log), proc, "waiting worker")
    (started,) = [e for e in log_of(log) if e["event"] == "start"]
    os.kill(started["ppid"], signal.SIGKILL)
    ran = finish(tmp_path, proc, before, args, creates=["run", "work"], ended="defect")
    assert b"HostEndedWithoutResult: the host process ended without a result (killed by " \
           b"signal 9 (SIGKILL))" in ran.stderr
    assert process_gone(started["pid"])
    assert not capture_ended(tmp_path / "run" / "capture.jsonl")
    assert not (tmp_path / "run" / "run.json").exists()


@case("G-R36", paragraphs=("SPEC:184",))
@pytest.mark.parametrize("mode,how", [("die", b"killed by signal 9 (SIGKILL)"),
                                      ("exit", b"exit status 3")])
def test_a_host_without_a_result_makes_the_parent_kill_its_workers_and_raise(tmp_path, capfd,
                                                                              mode, how):
    """CR-R6-F3 at the thin parent itself: a stand-in host that reports one worker (a process
    group of its own) and then dies by SIGKILL, or exits with status 3, without a result: the
    parent kills the worker's group and raises HostEndedWithoutResult naming the wait status; it
    prints nothing itself."""
    from synapse_hla import cli
    proc, read_fd, record = fake_host(tmp_path, mode)
    try:
        with pytest.raises(cli.HostEndedWithoutResult) as caught:
            cli.supervise_host(proc.pid, read_fd, cli._Output())
    finally:
        os.close(read_fd)
        proc.wait()
    assert type(caught.value) is cli.HostEndedWithoutResult
    assert isinstance(caught.value, RuntimeError)
    assert how in str(caught.value).encode("ascii")
    assert "1 worker process group(s) it reported were killed" in str(caught.value)
    worker = int(record.read_text().split("worker ")[1].split()[0])
    assert process_gone(worker)
    assert capfd.readouterr() == ("", "")


# --- CR-R6-F4: observe's pre-flight is validate-config's

PREFLIGHT = [
    # (what, configuration bytes or None for a missing file, FOM directory, observe's exit and
    #  diagnostics (code, path), validate-config's, or None where validate-config accepts it)
    ("not-an-object-and-no-fom", b"[]", "unset",
     (4, [("E_CONFIG", ""), ("E_DEPENDENCY_PIN", "RPR-Foundation_v2.0.xml")]),
     (4, [("E_CONFIG", ""), ("E_DEPENDENCY_PIN", "RPR-Foundation_v2.0.xml")])),
    ("unreadable-and-changed-fom", None, "flipped",
     (6, [("E_IO", "--config"), ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml")]),
     (6, [("E_IO", "--config"), ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml")])),
    ("bad-endpoint-and-changed-fom", "endpoint", "flipped",
     (4, [("E_CONFIG", "/endpoint"), ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml")]),
     (4, [("E_CONFIG", "/endpoint"), ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml")])),
    ("demo-mode-and-no-fom", "demo", "unset",
     (4, [("E_CONFIG", "/mode"), ("E_DEPENDENCY_PIN", "RPR-Foundation_v2.0.xml")]),
     (4, [("E_DEPENDENCY_PIN", "RPR-Foundation_v2.0.xml")])),
    ("good-config-and-changed-fom", "existing", "flipped",
     (4, [("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml")]),
     (4, [("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml")])),
]


@case("G-R36", paragraphs=("SPEC:174", "SPEC:184"))
@pytest.mark.parametrize("what,data,fom,observe,validate", PREFLIGHT, ids=[p[0] for p in PREFLIGHT])
def test_observe_runs_validate_config_s_two_checks_and_exits_by_the_higher_class(
        tmp_path, what, data, fom, observe, validate):
    """CR-R6-F4 (SPEC:184 "for competing terminal failures use priority 6,5,4,3,2"): observe runs
    the configuration check and then the FOM pin check, as validate-config does, reports both on
    stderr in that order, and exits by the higher class: a configuration that is not an object
    (E_CONFIG at the document, 2) with SYNAPSE_HLA_FOM_DIR unset (E_DEPENDENCY_PIN under the first
    module, 4) is 4; an unreadable --config (E_IO, 6) with a changed RPR-Base is 6; a demo
    configuration (E_CONFIG at /mode, which only observe refuses) with no FOM directory is 4. No
    process starts (not even the worker's --version), no directory is created, and the summary
    names no host. validate-config gives the same diagnostics and exit for the same faults."""
    env, config, log = observe_setup(tmp_path, [connect_and_join() + orderly_stop()])
    if data is None:
        config = tmp_path / "missing.json"
    elif data == "endpoint":
        document = example_json("config-existing.json")
        document["endpoint"] = "rti://8.8.8.8:14321"
        write(config, json.dumps(document).encode())
    elif data == "demo":
        write(config, (PACKAGE_ROOT / "examples" / "config-demo.json").read_bytes())
    elif data == "existing":
        write(config, (PACKAGE_ROOT / "examples" / "config-existing.json").read_bytes())
    else:
        write(config, data)
    if fom == "unset":
        del env[FOM_DIR_VARIABLE]
    else:
        env[FOM_DIR_VARIABLE] = str(flipped_fom(tmp_path))
    ran = run_cli(tmp_path, "observe", "--config", config, "--out", tmp_path / "run", env=env,
                  creates=["work", "fom"])
    assert (ran.code, [(d["code"], d["path"]) for d in ran.diagnostics]) == observe
    assert ran.summary["result"] == {"session": None, "run_json": False, "host": None}
    assert not (tmp_path / "run").exists() and log_of(log) == []
    ran = run_cli(tmp_path, "validate-config", "--config", config, env=env, creates=["work", "fom"])
    assert (ran.code, [(d["code"], d["path"]) for d in ran.diagnostics]) == validate


HOSTILE_CONFIGS = [
    b"\xef\xbb\xbf{}", b"{}\r\n", b"{\"a\":\x00}", b"[" * 40 + b"]" * 40, b"1" * 5000,
    b"{\"session_id\": 1e999}", b"{\"session_id\": NaN}", b"{\"session_id\": \"\\ud800\"}",
    b"{\"session_id\": \"\\udcff\"}", b"{\"\\u202e\": 1}", "{\"\u202e\x1b[31m\": 1}".encode(),
    b"{\"a\": 1, \"a\": 2}", b"\"text\"", b"null", b"\xff\xfe", b" " * 65537, b"{\"" + b"k" * 100000
    + b"\": 1}", b"", b"{", b"{\"profile\": \"SC-HLA-RPR2-OBS-1\"}",
]
HOSTILE_FOM_DIRS = ["", "relative/fom", "/nonexistent/fom", "/dev/null",
                    "/tmp/\x1b[31m\u202e\u2028" + "x" * 300, "\udcff/fom"]


@case("G-R36", paragraphs=("SPEC:184",))
def test_observe_s_preflight_meets_hostile_configurations_and_fom_directories(tmp_path, capfd,
                                                                             monkeypatch):
    """CR-R2-24 next to the refusal paths CR-R6-F4 added: 20 hostile configuration files (BOM,
    CRLF, NUL, nesting 40, a 5000-digit number, 1e999, NaN, lone surrogates in both spellings,
    bidirectional and escape characters in member names, a duplicate key, a string, null, invalid
    UTF-8, 65537 bytes, a 100000-byte key, empty, truncated, incomplete) against six hostile FOM
    directory names, through observe in this process: always exactly two diagnostics, the
    configuration's (E_CONFIG, or E_IO for nothing readable) first and E_DEPENDENCY_PIN second,
    each valid ASCII JSON whose path is already safe text, the exit the higher class, the summary
    valid with no host, nothing forked and nothing created. A fork here would be a defect, so
    `os.fork` raises."""
    from synapse_hla import cli, errors

    def no_fork():
        raise AssertionError("observe forked a host although its pre-flight failed")
    monkeypatch.setattr(os, "fork", no_fork)
    for index, data in enumerate(HOSTILE_CONFIGS):
        config = write(tmp_path / f"config-{index}.json", data)
        for fom in HOSTILE_FOM_DIRS:
            monkeypatch.setenv(FOM_DIR_VARIABLE, fom)
            code = cli.main(["observe", "--config", str(config), "--out", str(tmp_path / "run")])
            out, err = capfd.readouterr()
            assert out.isascii() and err.isascii()
            diagnostics = [strict_json(line.encode()) for line in err.splitlines()]
            assert all(not list(DIAGNOSTIC.iter_errors(d)) for d in diagnostics), diagnostics
            assert [d["code"] for d in diagnostics][1:] == ["E_DEPENDENCY_PIN"], diagnostics
            assert diagnostics[0]["code"] in ("E_CONFIG", "E_IO"), diagnostics
            assert all(d["path"] is None or errors.safe_text(d["path"]) == d["path"]
                       for d in diagnostics)
            summary = strict_json(out.encode())
            assert not list(SUMMARY.iter_errors(summary))
            assert code == summary["exit_code"] == max(CLASSES[d["code"]] for d in diagnostics)
            assert summary["result"] == {"session": None, "run_json": False, "host": None}
            assert not (tmp_path / "run").exists()


# --- CR-R6-F9: the argument vector meets hostile tokens

def test_the_parser_meets_hostile_argument_vectors_with_a_safe_named_refusal():
    """CR-R2-24 next to CR-R6-F9: 20,000 seeded random argument vectors of real options and
    commands, empty tokens, control and bidirectional characters, lone surrogates, an
    over-long token and lone dashes. `parse` answers each with a request, a help or version text,
    or a usage refusal whose path is never empty and is already safe text (CR-R0-04); nothing
    else ever escapes."""
    import random

    from synapse_hla import cli, errors
    pool = list(cli.COMMANDS) + ["--config", "--out", "--capture", "--duration-seconds",
                                 "--allow-prefix", "--help", "--version", "--debug", "", " ",
                                 "-", "--", "--out=", "60", "0", "x", "\x1b[31m", "\u202e",
                                 "\u2028", "\ud800", "\udcff", "\x00", "\x7f", "y" * 300,
                                 "-\u202e", "--\x1b", "COMMAND", "ARGUMENT"]
    rng = random.Random(6)
    kinds = set()
    for _ in range(20_000):
        argv = [rng.choice(pool) for _ in range(rng.randint(0, 7))]
        try:
            request = cli.parse(argv)
        except cli._Usage as usage:
            assert type(usage.path) is str and usage.path, argv
            assert errors.safe_text(usage.path) == usage.path, argv
            kinds.add("usage")
        except cli._Shown as shown:
            assert shown.text.isascii()
            kinds.add("shown")
        else:
            assert request.command in cli.COMMANDS
            kinds.add("request")
    assert kinds == {"usage", "shown", "request"}


# --- R6-r1-F7: every offline command that creates something takes it back when stopped

INTERRUPTED = [
    ("self-test-during-replay", "self-test"), ("self-test-after-replay", "self-test"),
    ("demo", "demo"), ("export", "export-capture"),
]


@case("G-R36", paragraphs=("SPEC:184",))
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
@pytest.mark.parametrize("moment,command", INTERRUPTED, ids=[i[0] for i in INTERRUPTED])
def test_an_interrupted_command_takes_back_what_it_made(tmp_path, moment, command, signum):
    """R6-r1-F7 (CR-new-R6-05 for every command that creates something): the command is held
    (GATE) at a moment when its output exists in part, and gets SIGINT or SIGTERM from outside:
    self-test while its fixture replay writes, and after the fixture replay is complete, before
    self-test.json; demo after its directory exists, before demo.json; export-capture after two
    lines are copied. Each stops at its next safe point, removes everything it made (the --out
    directory or file is gone), prints nothing, and exits 128 plus the signal's number."""
    env, mark, go = gated(tmp_path, moment)
    target = tmp_path / "made"
    if command == "export-capture":
        args = ("export-capture", "--capture", fixture_capture(tmp_path), "--out", target)
    else:
        args = (command, "--out", target)
    proc, before = start(tmp_path, *args, env=env, prefix=GATE)
    wait_for(mark.exists, proc, "the gate")
    if moment == "self-test-during-replay":
        assert (target / "fixture-replay" / "observations.jsonl").exists()
    elif moment == "self-test-after-replay":
        assert sorted(p.name for p in (target / "fixture-replay").iterdir()) == [
            "capture.jsonl", "diagnostics.jsonl", "observations.jsonl", "run.json"]
        assert not (target / "self-test.json").exists()
    elif moment == "demo":
        assert target.is_dir() and list(target.iterdir()) == []
    else:
        assert target.read_bytes() == b"".join(
            line + b"\n" for line in package_bytes("fixtures", "session.capture.jsonl")
            .split(b"\n")[:2])
    proc.send_signal(signum)
    ran = finish(tmp_path, proc, before, args, creates=["gate.mark", "capture.jsonl"],
                 ended="interrupted")
    assert ran.code == 128 + signum
    assert not target.exists()


# ============================================================================ R7: carry-in from the R6F review
#
# DECISIONS.md C.9: R6F-r1-F1 (an embedding caller keeps its signal handlers) and R6F-r1-F4 (the
# run.json schema's completion clause refuses what it must). R6F-r1-F2 is in test_hla_host.py.


def _sentinel_sigint(_signum, _frame):
    """A handler of the test's own; only its identity matters."""


def _sentinel_sigterm(_signum, _frame):
    """A second one, so that the two signals cannot be swapped unnoticed."""


def test_main_with_an_argument_vector_leaves_the_callers_signal_handlers_in_place(
        tmp_path, capfd):
    """R6F-r1-F1 (CR-R6-F1, CR-new-R6F-03): only the program itself (`main()` without `argv`,
    the console script) ignores SIGINT and SIGTERM once its exit code is decided; a caller that
    runs `cli.main(argv)` in its own process gets its own handlers back, whether the command
    succeeded (verify of the bundled capture, 0), was a usage error (2) or printed its help (0).
    Under the mutant `_stoppable(program=True)` both handlers come back as SIG_IGN."""
    from synapse_hla import cli
    capture = fixture_capture(tmp_path)
    previous = {signal.SIGINT: signal.signal(signal.SIGINT, _sentinel_sigint),
                signal.SIGTERM: signal.signal(signal.SIGTERM, _sentinel_sigterm)}
    try:
        for argv, code in ((["verify", "--capture", str(capture)], 0),
                           (["verify"], 2),
                           (["--help"], 0)):
            assert cli.main(argv) == code, argv
            assert signal.getsignal(signal.SIGINT) is _sentinel_sigint, argv
            assert signal.getsignal(signal.SIGTERM) is _sentinel_sigterm, argv
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    out, _err = capfd.readouterr()
    lines = out.splitlines()
    # verify's summary, the usage error's summary, then the help text.
    assert strict_json(lines[0].encode())["exit_code"] == 0
    assert strict_json(lines[1].encode())["exit_code"] == 2
    assert lines[2].startswith("usage: synapse-hla")


def _coupling(document: dict, status: str, complete, offline: str | None = None) -> bool:
    """Whether run.schema.json accepts `document` with the capture status and completion (and,
    for a replay, the offline evidence) replaced."""
    changed = json.loads(json.dumps(document))
    changed["capture"]["status"] = status
    changed["capture_complete"] = complete
    if offline is not None:
        changed["evidence"]["offline_replay"] = offline
    return RUN_SCHEMA.is_valid(changed)


def test_run_json_completion_is_held_to_the_capture_status_for_both_commands(tmp_path):
    """R6F-r1-F4 (CR-R6-F8, CR-new-R6F-07): in run.json `capture_complete` is true exactly when
    the capture's status is COMPLETE, for observe and for replay alike, and a prefix replay never
    says PASS. Real documents of both commands (a replay of the bundled capture; an observe run
    with the scripted worker of R5 that ends COMPLETE) are changed one member at a time: COMPLETE
    with false or null, FAILED or INCOMPLETE with true, and PASS for a prefix are refused; the
    same documents with the matching values are accepted, so each refusal is the clause's."""
    replayed = run_cli(tmp_path, "replay", "--capture", fixture_capture(tmp_path), "--out",
                       tmp_path / "replayed", creates=["replayed", "capture.jsonl"])
    assert replayed.code == 0
    replay_doc = run_json(tmp_path / "replayed")
    live = tmp_path / "live"
    live.mkdir()
    ran, log = observed(live, [connect_and_join() + orderly_stop()], "--duration-seconds", "1")
    assert ran.code == 0
    live_doc = run_json(live / "run")
    assert (replay_doc["command"], live_doc["command"]) == ("replay", "observe")
    for document, offline_complete, offline_prefix in (
            (replay_doc, "PASS", "PREFIX_ONLY"), (live_doc, None, None)):
        assert _coupling(document, "COMPLETE", True, offline_complete)
        assert not _coupling(document, "COMPLETE", False, offline_complete)
        assert not _coupling(document, "COMPLETE", None, offline_complete)
        for status in ("FAILED", "INCOMPLETE"):
            assert _coupling(document, status, False, offline_prefix)
            assert not _coupling(document, status, True, offline_prefix)
    for status in ("FAILED", "INCOMPLETE"):
        assert not _coupling(replay_doc, status, False, "PASS")
