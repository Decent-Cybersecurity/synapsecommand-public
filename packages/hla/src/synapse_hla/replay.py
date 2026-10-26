"""`replay(capture_path, output_dir, *, allow_prefix=False)`: a recorded capture reduced and
projected again, offline, into a new directory (R35, SPEC:168).

FIRST THE WHOLE CAPTURE, THEN THE OUTPUT
----------------------------------------
Nothing is written before the capture has been judged from its first byte to its last
(`verify_capture`, R35). A capture with a hash, sequence, schema, configuration or limit fault
is refused whatever `allow_prefix` says; an incomplete one (no footer, or a last line that is
not whole) and one whose footer says FAILED are refused unless `allow_prefix` is given (OPS-16,
RED-06). A refusal raises the report's `HlaError`: its code and `line:<n>` path. A FAILED footer
has no fault of its own in the report, and the profile has one code whose behaviour is "refuse
normal replay" for a capture that is not complete evidence, so that refusal is
E_CAPTURE_INCOMPLETE at the footer's `/status`. A prefix needs at least the header: without the
recorded configuration there is nothing to replay with. Then the header's pin map must be the
packaged one, entry for entry (RED-V-03, E_DEPENDENCY_PIN under the file's name); the recorded
endpoint is never read, let alone contacted (SPEC:293). Only then is the output directory made.

WHAT IS WRITTEN, AND HOW
------------------------
`output_dir` must not exist, not even as a dangling symbolic link (E_OUTPUT_EXISTS), and its
parent must (E_IO otherwise); only its last component is judged (OPS-17), because ordinary
temporary paths pass through symbolic links on some systems. It is made with mode 0700, and three
files with fixed names are created inside it, relative to the directory's own descriptor,
exclusively and without following a link, with mode 0600: `capture.jsonl`, a byte copy of the
input (for a prefix replay the whole file, the unverified tail included, so the evidence stays
beside what was made of it); `observations.jsonl`, every record of every frame in order, one
canonical line each (RED-15); and `diagnostics.jsonl`, exactly the diagnostic lines of
`observations.jsonl`, byte for byte and in the same order (OPS-20). Paths in refusals are the
argument names, `capture_path` and `output_dir` (CR-L01; the command line maps them to its own).

The capture is read a second time to produce the output, by the same verified reader, and the
second reading must report exactly what the first did: a file that changed in between is E_IO,
and so is a tail that is no longer what the first reading saw. Every record comes from
`reducer.reduce_frame` on a state built from the recorded header, with `capture_complete` true
exactly for a COMPLETE capture verified to its end, whatever `allow_prefix` says, and false for
every record of a prefix replay (SPEC:158). No clock, sleep, network or environment is read,
so two replays of one capture by one build give byte-identical directories.

If anything fails once the directory exists (a write, a reducer defect, an interruption), the
files this call created and the directory are removed before the exception goes on: a refused
replay leaves nothing behind.

THE RESULT
----------
A summary (`local_schemas/replay-summary.schema.json`): the capture's status, `capture_complete`,
`verified_seq` and frame count, the records by kind, the snapshots suppressed by each reason, the
diagnostics by code (errors and warnings apart), each file's size and SHA-256, and the whole
verify report as `verification` (lead ruling CR-L08: how far verification read, and why it
stopped, travel with the result, so that nobody has to read the capture a third time to say it).

`replay_with` is the same replay for the command line (round R6): it tells its caller the verify
report and the header as soon as it knows them, so that a refused replay can still say how far
verification read (OPS-20), and it writes one more file, `run.json`, whose bytes the caller makes
from the summary and the header. That file is written last, into the same directory, by the same
exclusive create, and it goes with everything else if anything fails. It also calls the caller's
`check` before each line of both readings: the command line stops there when SIGINT or SIGTERM
has arrived, so an interrupted replay ends at a line boundary and takes back what it made.
"""

from __future__ import annotations

import contextlib
import hashlib
import os

from synapse_hla import _fom, capture, errors, projector, reducer
from synapse_hla.errors import HlaError
from synapse_hla.limits import V1

CAPTURE = "capture.jsonl"
OBSERVATIONS = "observations.jsonl"
DIAGNOSTICS = "diagnostics.jsonl"
#: The files of a replay directory, in the order the summary lists them.
FILES = (CAPTURE, OBSERVATIONS, DIAGNOSTICS)
#: The command line's manifest of a replay directory (SPEC:168, OPS-10), written by `replay_with`.
RUN_FILE = "run.json"
#: CR-L01: an I/O refusal names the argument; this is the API's name for the output directory.
OUTPUT_DIR = "output_dir"
SUMMARY_VERSION = 1

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW | _CLOEXEC
_CHANGED = "the capture changed while it was replayed"


def replay(capture_path, output_dir, *, allow_prefix: bool = False) -> dict:
    """Replay the capture at `capture_path` into the new directory `output_dir`; see the module.

    Raises `HlaError` for a refused capture, an existing or unwritable output and an I/O
    failure; `TypeError` for an argument of the wrong type (a caller bug). Returns the summary.
    """
    return replay_with(capture_path, output_dir, allow_prefix=allow_prefix)


def replay_with(capture_path, output_dir, *, allow_prefix: bool = False,
                observed: dict | None = None, manifest=None, check=None) -> dict:
    """`replay` for the command line; see the module text.

    `observed`, a dict, receives `verification` (the verify report) as soon as the capture has
    been verified and `header` (the verified header record) as soon as it has been read, whether
    the replay then goes on or is refused. `manifest(summary, header)` returns the bytes of
    `run.json`; it is called once the three files are complete, with the summary including their
    digests, and must not raise for a reason of its own (a defect, which removes the directory
    like any other). `check()` is called before each line of both readings; whatever it raises
    ends the replay there, the directory removed.
    """
    if type(allow_prefix) is not bool:
        raise TypeError("allow_prefix is a bool")
    if observed is not None and type(observed) is not dict:
        raise TypeError("observed is a dict")
    check = _no_check if check is None else check
    target = _output_path(output_dir)
    report = _verified(capture_path, check)
    if observed is not None:
        observed["verification"] = report
    _refuse(report, allow_prefix)
    header = _first_record(capture_path)
    if observed is not None:
        observed["header"] = header
    _fom.check_header_pins(header["pins"])
    output = _Output(target)
    try:
        summary = _replayed(capture_path, report, output, check)
        output.close_files()
        summary["files"] = output.digests()
        if manifest is not None:
            data = manifest(summary, header)
            if type(data) is not bytes:
                raise TypeError("a manifest is bytes")
            output.add(RUN_FILE, data)
        output.close()
    except BaseException:
        output.discard()
        raise
    return summary


def _no_check() -> None:
    return None


def _verified(capture_path, check) -> dict:
    """`verify_capture`, line by line with `check` before each (the same reader, the same
    report)."""
    reader = capture.CaptureReader(capture_path)
    lines = reader.records()
    try:
        while True:
            check()
            if next(lines, None) is None:
                break
    finally:
        lines.close()
    return reader.report


def _output_path(output_dir) -> bytes:
    # As for the capture path: a name the file-system encoding cannot write, or one holding a
    # NUL byte, names no directory, and os.mkdir would raise ValueError for it, not OSError.
    try:
        target = os.fsencode(output_dir)
    except UnicodeEncodeError:
        raise HlaError(errors.E_IO, OUTPUT_DIR, "the output path cannot name a directory") from None
    if b"\x00" in target:
        raise HlaError(errors.E_IO, OUTPUT_DIR, "the output path cannot name a directory")
    return target


def _refuse(report: dict, allow_prefix: bool) -> None:
    status = report["status"]
    if status == capture.INVALID:
        raise HlaError(report["code"], report["path"], report["message"])
    if status == capture.INCOMPLETE and (not allow_prefix or report["verified_seq"] is None):
        raise HlaError(errors.E_CAPTURE_INCOMPLETE, report["path"], report["message"])
    if status == capture.FAILED and not allow_prefix:
        footer_line = report["verified_seq"] + 1
        raise HlaError(errors.E_CAPTURE_INCOMPLETE, f"line:{footer_line}#/status",
                       "the capture ends FAILED; only a prefix replay may read it")


def _first_record(capture_path) -> dict:
    lines = capture.CaptureReader(capture_path).records()
    try:
        first = next(lines, None)
    finally:
        lines.close()
    if first is None:
        raise HlaError(errors.E_IO, capture.CAPTURE_PATH, _CHANGED)
    return first.record


class _File:
    """One output file: its descriptor, and the size and SHA-256 of what was written to it."""

    def __init__(self, fd: int) -> None:
        self.stream = os.fdopen(fd, "wb")
        self.digest = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> None:
        try:
            self.stream.write(data)
        except OSError:
            raise HlaError(errors.E_IO, OUTPUT_DIR, "the output cannot be written") from None
        self.digest.update(data)
        self.size += len(data)


class _Output:
    """The replay directory: made exclusively, its files created exclusively, removed on failure."""

    def __init__(self, target: bytes) -> None:
        try:
            os.mkdir(target, _DIRECTORY_MODE)
        except FileExistsError:
            raise HlaError(errors.E_OUTPUT_EXISTS, OUTPUT_DIR,
                           "the output directory already exists") from None
        except OSError:
            raise HlaError(errors.E_IO, OUTPUT_DIR,
                           "the output directory cannot be created") from None
        self.target = target
        self.directory: int | None = None
        self.files: dict[str, _File] = {}
        self.created: list[str] = []
        try:
            self.directory = os.open(target, _DIRECTORY_FLAGS)
            for name in FILES:
                # Named before it exists: discard() may then try to remove a name that was never
                # made (harmless), but never misses one that was.
                self.created.append(name)
                fd = os.open(name, _FILE_FLAGS, _FILE_MODE, dir_fd=self.directory)
                self.files[name] = _File(fd)
        except OSError:
            self.discard()
            raise HlaError(errors.E_IO, OUTPUT_DIR,
                           "the output files cannot be created") from None
        except BaseException:
            self.discard()
            raise

    def write(self, name: str, data: bytes) -> None:
        self.files[name].write(data)

    def close_files(self) -> None:
        for file in self.files.values():
            try:
                file.stream.close()
            except OSError:
                raise HlaError(errors.E_IO, OUTPUT_DIR,
                               "the output cannot be written") from None

    def add(self, name: str, data: bytes) -> None:
        """One more file of fixed name, created and written whole, then closed."""
        self.created.append(name)
        try:
            fd = os.open(name, _FILE_FLAGS, _FILE_MODE, dir_fd=self.directory)
        except OSError:
            raise HlaError(errors.E_IO, OUTPUT_DIR, "the output files cannot be created") \
                from None
        extra = _File(fd)
        try:
            extra.write(data)
        finally:
            try:
                extra.stream.close()
            except OSError:
                raise HlaError(errors.E_IO, OUTPUT_DIR,
                               "the output cannot be written") from None

    def close(self) -> None:
        self.close_files()
        os.close(self.directory)
        self.directory = None

    def digests(self) -> dict:
        return {name: {"bytes": self.files[name].size,
                       "sha256": self.files[name].digest.hexdigest()} for name in FILES}

    def discard(self) -> None:
        # Best effort, and only what this call made: the files it created by their fixed names,
        # relative to the directory it opened, then the directory, which rmdir removes only when
        # nothing else has appeared in it. The exception that brought us here is the one that
        # matters, so a failure to tidy up does not replace it.
        for file in self.files.values():
            with contextlib.suppress(OSError):
                file.stream.close()
        if self.directory is not None:
            for name in self.created:
                with contextlib.suppress(OSError):
                    os.unlink(name, dir_fd=self.directory)
            with contextlib.suppress(OSError):
                os.close(self.directory)
            self.directory = None
        with contextlib.suppress(OSError):
            os.rmdir(self.target)


def _replayed(capture_path, report: dict, output: _Output, check) -> dict:
    complete = report["status"] == capture.COMPLETE
    kinds = dict.fromkeys(reducer.KINDS, 0)
    suppressions = dict.fromkeys(projector.REASONS, 0)
    codes = dict.fromkeys(errors.CODES, 0)
    reader = capture.CaptureReader(capture_path)
    state = None
    for line in reader.records():
        check()
        record = line.record
        output.write(CAPTURE, line.raw + b"\n")
        if line.number == 1:
            state = reducer.initial_state(record, complete)
            continue
        if record["type"] != capture.FRAME:
            continue
        # The reader has just verified this frame by the reducer's own rules (CR-L07).
        state, records = reducer.reduce_admitted(state, record)
        for out in records:
            data = reducer.output_line(out)
            output.write(OBSERVATIONS, data)
            kinds[out["kind"]] += 1
            if out["kind"] == reducer.DIAGNOSTIC:
                output.write(DIAGNOSTICS, data)
                codes[out["payload"]["code"]] += 1
            elif out["kind"] == reducer.SNAPSHOT:
                for reason in out["payload"]["suppression_reasons"]:
                    suppressions[reason] += 1
    if reader.report != report:
        raise HlaError(errors.E_IO, capture.CAPTURE_PATH, _CHANGED)
    if report["status"] == capture.INCOMPLETE:
        output.write(CAPTURE, _tail(capture_path, report["verified_bytes"]))
    return {
        "replay_summary_version": SUMMARY_VERSION,
        "status": report["status"],
        "capture_complete": complete,
        "verified_seq": report["verified_seq"],
        "frames": report["frames"],
        "records": kinds,
        "suppressions": suppressions,
        "errors": {code: n for code, n in codes.items() if n and code.startswith("E_")},
        "warnings": {code: n for code, n in codes.items() if n and code.startswith("W_")},
        "verification": report,
    }


def _tail(capture_path, verified_bytes: int) -> bytes:
    """The bytes of an incomplete capture after its verified prefix: the partial last line, or
    nothing when only the footer is missing. Verification bounded it by the line limit and saw
    no LF in it; anything else means the file changed."""
    bound = V1.line_bytes
    with capture._open_capture(capture_path) as stream:
        try:
            size = os.fstat(stream.fileno()).st_size
            stream.seek(verified_bytes)
            tail = stream.read(bound + 1)
        except OSError:
            raise HlaError(errors.E_IO, capture.CAPTURE_PATH,
                           "the capture cannot be read") from None
    if len(tail) > bound or b"\n" in tail or verified_bytes + len(tail) != size:
        raise HlaError(errors.E_IO, capture.CAPTURE_PATH, _CHANGED)
    return tail
