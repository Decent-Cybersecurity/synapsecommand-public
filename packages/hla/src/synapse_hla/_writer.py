"""The run directory of a live session and the durable capture in it (R34, OPS-17, OPS-24,
SPEC:293), for the host (`host.py`, round R5).

THE DIRECTORY
-------------
A session writes into a directory it creates itself, exclusively (R07, OPS-17): the last
component of the path must not exist, not even as a dangling symbolic link (E_OUTPUT_EXISTS),
and its parent must (E_IO otherwise). It is made with mode 0700, and its files are created
relative to the directory's own descriptor, exclusively, without following a link, with mode
0600 and with fixed names only (OPS-08: no name is ever derived from the configuration or the
capture). The three files are `capture.jsonl`, `observations.jsonl` and `diagnostics.jsonl`; the
command line adds `run.json` (round R6). The directory is synced once its files exist (OPS-24),
so that the names survive a crash as well as the bytes.

THE CAPTURE
-----------
Every line comes from R2's `CaptureChain`, so a line the reader would refuse is refused before it
is written, with the reader's code. The writer adds what the chain leaves to it:
- the bytes go to the file with `os.write` semantics (a write may take part of the data; the
  rest is written after it), so that a frame is in the kernel before the reducer sees it (R34);
- fsync (OPS-24): immediately after the header, every generation_start and generation_end and
  the footer, and otherwise no later than the 100th unsynced line or 250 ms after the first one;
  that time is checked whenever a line is written (a long run of frames from one read) and by
  the host's timer in between: `due()` tells the host when the next timed sync is owed, so that
  it wakes for it, and the host syncs before any wait in which it does not serve the timer;
- the file budget (SPEC:293, OPS-21): the capture never passes the file limit, and the last
  65536 bytes of it are kept for the records that end the session (its terminal diagnostics,
  the generation_end and the footer). A frame that is not part of that end, written where it would
  enter the reserve, is refused with `CaptureFull` before anything is written, and so is one
  that would leave fewer than `END_FRAMES` frames of the session's frame limit, because the
  verifier counts the end's frames against that limit too; a frame of the end itself is refused
  the same way when it would pass the file limit or the frame limit, so that the end of a
  session is never refused by the chain. The size is judged before the content (R41: size before
  anything else), on the exact line the chain would write;
- an I/O failure (an `OSError` from a write or an fsync) leaves the capture broken: nothing more is
  written to it, so a partial last line stays the last thing in the file (an incomplete capture,
  RED-06) and no footer is ever claimed after it (SPEC:293).

The output files are derived (R34): they are written with the same `os.write` semantics and
never synced, and a failure to write them breaks only them.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os

from synapse_hla import canonical, capture, errors, projector, reducer
from synapse_hla.capture import CaptureChain
from synapse_hla.errors import HlaError
from synapse_hla.limits import Limits

CAPTURE = "capture.jsonl"
OBSERVATIONS = "observations.jsonl"
DIAGNOSTICS = "diagnostics.jsonl"
#: The files a session creates, in the order its summary lists them.
FILES = (CAPTURE, OBSERVATIONS, DIAGNOSTICS)
#: CR-L01: an I/O refusal names the argument; this is the API's name for the run directory.
OUTPUT_DIR = "output_dir"
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
#: The most frames the end of a session writes (`host`): the diagnostic of the worker's first
#: condition, that of a never-retried failure competing with it, E_RTI_TIMEOUT when a worker
#: that ended its generation by retraction had to be killed (OPS-25), generation_end, and a
#: generation-0 E_IO when the outputs fail while those are written. All five can meet: a
#: retraction, then a failure the worker only reports (which kills nothing), then the kill.
END_FRAMES = 5

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW | _CLOEXEC
_BOUNDARIES = (capture.GENERATION_START, capture.GENERATION_END)


class FileStream:
    """A file descriptor with `os.write` semantics: `write` returns how many bytes it took."""

    def __init__(self, fd: int) -> None:
        self.fd = fd

    def write(self, data: bytes) -> int:
        return os.write(self.fd, data)

    def fileno(self) -> int:
        return self.fd

    def close(self) -> None:
        os.close(self.fd)


def open_capture(directory_fd: int, name: str) -> FileStream:
    """The default `open_capture` seam: `name` created in the directory, exclusively, 0600."""
    return FileStream(os.open(name, _FILE_FLAGS, FILE_MODE, dir_fd=directory_fd))


def fsync(fd: int) -> None:
    """The default `fsync` seam."""
    os.fsync(fd)


def output_path(output_dir) -> bytes:
    """`output_dir` as the operating system's bytes, or E_IO for a name no directory can have."""
    # As in replay: a name the file-system encoding cannot write, or one holding a NUL byte,
    # names no directory, and os.mkdir would raise ValueError for it rather than OSError.
    try:
        target = os.fsencode(output_dir)
    except UnicodeEncodeError:
        raise HlaError(errors.E_IO, OUTPUT_DIR, "the output path cannot name a directory") from None
    if b"\x00" in target:
        raise HlaError(errors.E_IO, OUTPUT_DIR, "the output path cannot name a directory")
    return target


class CaptureFull(Exception):
    """A record does not fit the capture's budget (SPEC:293): nothing of it was written."""


class CaptureBroken(Exception):
    """The capture can no longer be written (an I/O failure); nothing is written to it again."""


class OutputBroken(Exception):
    """An output file can no longer be written; the outputs are not written again."""


class _Sink:
    """One open file: what reached it (size and SHA-256), written with `os.write` semantics."""

    def __init__(self, stream) -> None:
        self.stream = stream
        self.size = 0
        self.digest = hashlib.sha256()

    def write(self, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            taken = self.stream.write(data[offset:])
            if type(taken) is not int or taken < 0 or taken > len(data) - offset:
                raise RuntimeError("a capture stream's write returned an impossible count")
            if taken == 0:
                # No progress and no error: treated as the failure it is, never retried forever.
                raise OSError(errno.EIO, "the file took no bytes")
            self.digest.update(data[offset:offset + taken])
            self.size += taken
            offset += taken

    def entry(self) -> dict:
        return {"bytes": self.size, "sha256": self.digest.hexdigest()}


class RunDirectory:
    """The session's directory and its three files, created as the module text says.

    Raises `HlaError` E_OUTPUT_EXISTS when the path exists and E_IO when it cannot be made; if a
    file cannot be created or the directory cannot be synced, whatever this call made is removed
    again (nothing has been captured yet) before E_IO is raised.
    """

    def __init__(self, target: bytes, *, open_capture, fsync) -> None:
        try:
            os.mkdir(target, DIRECTORY_MODE)
        except FileExistsError:
            raise HlaError(errors.E_OUTPUT_EXISTS, OUTPUT_DIR,
                           "the output directory already exists") from None
        except OSError:
            raise HlaError(errors.E_IO, OUTPUT_DIR,
                           "the output directory cannot be created") from None
        self.target = target
        self.directory: int | None = None
        self.streams: dict = {}
        try:
            self.directory = os.open(target, _DIRECTORY_FLAGS)
            self.streams[CAPTURE] = open_capture(self.directory, CAPTURE)
            for name in (OBSERVATIONS, DIAGNOSTICS):
                self.streams[name] = FileStream(
                    os.open(name, _FILE_FLAGS, FILE_MODE, dir_fd=self.directory))
            fsync(self.directory)
        except OSError:
            self._discard()
            raise HlaError(errors.E_IO, OUTPUT_DIR,
                           "the output files cannot be created") from None
        except BaseException:
            self._discard()
            raise

    def _discard(self) -> None:
        # Only what this call made, by its fixed names, relative to the directory it opened; the
        # directory goes only when nothing else has appeared in it. The exception that brought us
        # here is the one that matters, so a failure to tidy up does not replace it.
        for stream in self.streams.values():
            with contextlib.suppress(OSError):
                stream.close()
        if self.directory is not None:
            for name in self.streams:
                with contextlib.suppress(OSError):
                    os.unlink(name, dir_fd=self.directory)
            with contextlib.suppress(OSError):
                os.close(self.directory)
            self.directory = None
        with contextlib.suppress(OSError):
            os.rmdir(self.target)

    def close(self) -> None:
        """Close every file and the directory; a failure to close is ignored, because nothing is
        written after this and what was written was already counted and, for the capture,
        synced."""
        for stream in self.streams.values():
            with contextlib.suppress(OSError):
                stream.close()
        if self.directory is not None:
            with contextlib.suppress(OSError):
                os.close(self.directory)
            self.directory = None


class CaptureWriter:
    """The durable capture: the chain's lines, the fsync rule and the budget; see the module."""

    def __init__(self, stream, *, limits: Limits, fsync, fsync_frames: int,
                 fsync_interval_ns: int) -> None:
        self.chain = CaptureChain(limits=limits)
        self.limits = limits
        self._sink = _Sink(stream)
        self._fsync = fsync
        self._fsync_frames = fsync_frames
        self._fsync_interval_ns = fsync_interval_ns
        self._unsynced = 0
        self._unsynced_since: int | None = None
        self.broken = False
        #: The footer's status and reason once it has been written.
        self.written_footer: dict | None = None
        #: What reached the file: the chain may hold one record more when its write failed.
        self.last_seq = 0
        self.frames = 0
        self.last_generation = 0

    # -- what has been written

    @property
    def open_generation(self) -> int | None:
        return self.chain.open_generation

    @property
    def next_generation(self) -> int:
        """The number the next generation_start takes (the chain's: generations are 1, 2, 3 ...)."""
        return self.chain.last_generation + 1

    def entry(self) -> dict:
        return self._sink.entry()

    # -- writing

    def header(self, record: dict, now: int) -> None:
        if self.broken:
            raise CaptureBroken()
        line = self.chain.header(record)
        if len(line) > self.limits.capture_file_bytes - self.limits.capture_reserve_bytes:
            raise CaptureFull()
        self._write(line)
        self._synced(now, boundary=True)

    def frame(self, generation: int, elapsed_ns: int, event: dict, now: int, *,
              end: bool) -> dict:
        """Write the next frame and return it as written. `end` marks a frame of the records
        that end the session, which may use the reserve; any other frame may not."""
        if self.broken:
            raise CaptureBroken()
        chain = self.chain
        record = {"type": capture.FRAME, "seq": chain.next_seq, "generation": generation,
                  "elapsed_ns": str(elapsed_ns), "event": event, "prev_sha256": chain.last_sha256}
        try:
            record["sha256"] = canonical.record_sha256(record)
            line = canonical.canonical_bytes(record) + b"\n"
        except canonical.StrictJsonError:
            # Not a capture value at all: the chain below refuses it with its own code.
            line = None
        if not end:
            frames = self.limits.frames_per_session - END_FRAMES
            budget = self.limits.capture_file_bytes - self.limits.capture_reserve_bytes
        else:
            frames = self.limits.frames_per_session
            budget = self.limits.capture_file_bytes
        if chain.frames + 1 > frames:
            raise CaptureFull()
        if line is not None and self._sink.size + len(line) > budget:
            raise CaptureFull()
        written = chain.frame(generation, elapsed_ns, event)
        if written != line:
            raise RuntimeError("the writer's line differs from the chain's")
        self._write(written)
        self.last_seq = record["seq"]
        self.frames += 1
        if event["type"] == capture.GENERATION_START:
            self.last_generation = generation
        self._synced(now, boundary=event["type"] in _BOUNDARIES)
        return record

    def footer(self, status: str, reason_code: str | None, now: int) -> None:
        if self.broken:
            raise CaptureBroken()
        seq = self.chain.next_seq
        line = self.chain.footer(status, reason_code, self.chain.last_generation)
        if self._sink.size + len(line) > self.limits.capture_file_bytes:
            raise CaptureFull()
        self._write(line)
        self.last_seq = seq
        self.written_footer = {"status": status, "reason_code": reason_code}
        self._synced(now, boundary=True)

    def _write(self, line: bytes) -> None:
        try:
            self._sink.write(line)
        except OSError:
            self.broken = True
            raise CaptureBroken() from None

    def _synced(self, now: int, *, boundary: bool) -> None:
        """The fsync rule after one more line reached the file (which the counts above record
        before any fsync can fail: a line in the file is written, durable or not)."""
        self._unsynced += 1
        if self._unsynced_since is None:
            self._unsynced_since = now
        if boundary or self._unsynced >= self._fsync_frames or \
                now >= self._unsynced_since + self._fsync_interval_ns:
            self.sync()

    # -- fsync (OPS-24)

    def due(self) -> int | None:
        """The monotonic instant by which the unsynced lines must be synced, or None."""
        if self._unsynced_since is None:
            return None
        return self._unsynced_since + self._fsync_interval_ns

    def sync_if_due(self, now: int) -> None:
        due = self.due()
        if due is not None and now >= due:
            self.sync()

    def sync(self) -> None:
        if self.broken or self._unsynced == 0:
            return
        try:
            self._fsync(self._sink.stream.fileno())
        except OSError:
            self.broken = True
            raise CaptureBroken() from None
        self._unsynced = 0
        self._unsynced_since = None


class OutputWriter:
    """observations.jsonl and diagnostics.jsonl: every record in order, and the diagnostic ones
    again, byte for byte (OPS-20). After a failure nothing more is written to either. `kinds`,
    `codes` and `reasons` count the records whose line reached observations.jsonl whole: what
    the file holds, which is what a run manifest describes."""

    def __init__(self, observations, diagnostics) -> None:
        self._observations = _Sink(observations)
        self._diagnostics = _Sink(diagnostics)
        self.broken = False
        self.kinds = dict.fromkeys(reducer.KINDS, 0)
        self.codes = dict.fromkeys(errors.CODES, 0)
        self.reasons = dict.fromkeys(projector.REASONS, 0)

    def write(self, records: list) -> None:
        if self.broken:
            raise OutputBroken()
        try:
            for record in records:
                line = reducer.output_line(record)
                self._observations.write(line)
                kind = record["kind"]
                self.kinds[kind] += 1
                if kind == reducer.DIAGNOSTIC:
                    self.codes[record["payload"]["code"]] += 1
                    self._diagnostics.write(line)
                elif kind == reducer.SNAPSHOT:
                    for reason in record["payload"]["suppression_reasons"]:
                        self.reasons[reason] += 1
        except OSError:
            self.broken = True
            raise OutputBroken() from None

    def entries(self) -> dict:
        return {OBSERVATIONS: self._observations.entry(), DIAGNOSTICS: self._diagnostics.entry()}
