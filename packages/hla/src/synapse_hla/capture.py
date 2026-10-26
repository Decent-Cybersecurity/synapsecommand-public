"""The durable capture of section 5: its records, the hash chain, and `verify_capture`.

WHAT A CAPTURE IS
-----------------
UTF-8 JSONL, one canonical JSON object per LF-terminated line (R15): a header, frames, one
footer. The header carries the validated configuration, the pin map and an audit time. Every
frame and the footer carry `seq` (1, 2, 3 ... without a gap), `prev_sha256` (for seq 1 the SHA-256
of the exact header line bytes, otherwise the previous record's `sha256`) and `sha256` (of the
canonical record without it; RED-20 extends this to the footer). The chain detects accidental
modification of the evidence. It is not authentication and not a signature: anyone who can write
the file can also recompute every digest.

ONE SET OF RULES FOR WRITING AND READING
----------------------------------------
`_LineRules` holds every rule a line must meet, with the state the rules need between lines, and
both directions use it. `CaptureReader` (and `verify_capture`, which only drives it) feeds it the
lines of a file; `CaptureChain` builds each record, serialises it canonically and feeds it the
line before handing it out, so a line the chain produces is by construction one the reader
accepts, and a record that would break a rule is refused before it is ever written.

The checks on one line run in the order of RED-06, and the first line that fails decides the
result: the line bound (E_LIMIT, OPS-21); UTF-8, no byte order mark, no CR; JSON with no
duplicate key; no float token, no integer beyond 2^53 - 1 and no lone surrogate (RED-04); the
canonical spelling; the schema of the record type, with the checks the schema is too loose for
(attribute names strictly ascending, RED-04; names, classes and messages bounded in UTF-8 bytes,
SPEC:289; a diagnostic's code one of the catalogue's and its severity the one the code's prefix
gives, OPS-19 and RED-03; `record_created_at` a real instant, OPS-03); `seq` (E_CAPTURE_SEQUENCE);
`prev_sha256` and `sha256` (E_CAPTURE_HASH); then the line's place in the session. For the
header that is the full semantic validation of its configuration (RED-V-01, E_CONFIG). For a
frame it is lifecycle framing (RED-05 as amended, OPV-01): frames written while no generation is
open are generation-0 diagnostics; generations are 1, 2, 3 ..., each opened by exactly one
generation_start and closed by exactly one generation_end; a generation_start names the configured
federation (CR-L09); `elapsed_ns` is 0 up to and including
the first generation_start and never decreases; under external_elapsed, epoch plus elapsed time
never passes 9998-12-31T23:59:59.999999Z (SPEC:289, E_CONFIG). For the footer it is no generation
left open, `last_generation` the highest generation started, and COMPLETE with a null reason or
FAILED with a catalogue E_ code. Finally the frame count (OPS-21, E_LIMIT). Nothing after the
footer is admitted.

What verify does not look at: discover metadata (RED-07: an inconsistent rediscovery is the
reducer's E_CAPTURE_SCHEMA, so that the capture stays replayable as a prefix), token numbering
(RED-05: tokens are labels), and the pins (OPS-11: only replay compares them, RED-V-03). It never
reads the endpoint a header names, let alone contacts it (SPEC:293).

THE REPORT
----------
`verify_capture` raises `HlaError` only when it cannot open or read the file (E_IO, path
`capture_path`). Every fault of the capture itself is a result, returned as the report of RED-06,
which `local_schemas/verify-report.schema.json` describes: `status` (COMPLETE, FAILED,
INCOMPLETE or INVALID), the `code`, `path` (CR-L01: `line:<n>`, optionally `#<pointer>`; for
E_CAPTURE_INCOMPLETE the first line that is not there or not whole) and `message` of the fault,
`verified_seq` (0 when only the header verified, null when not even the header did),
`verified_bytes` (the length of the verified prefix, LFs included), `frames`, the header digest
and the chain head, `capture_complete` (true exactly for a COMPLETE capture verified to its end)
and the verified footer.

The reader streams: one line at a time, each bounded by the line limit before it is parsed, with
no list of records kept, so verifying a capture takes memory for one line whatever its length.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass

from synapse_hla import _schema, _utc, canonical, config, errors
from synapse_hla.errors import HlaError
from synapse_hla.limits import V1, Limits

# --- the record model ---------------------------------------------------------------------------

HEADER = "header"
FRAME = "frame"
FOOTER = "footer"
CAPTURE_VERSION = 1
ADAPTER_VERSION = "1.0.0"
PROFILE = "SC-HLA-RPR2-OBS-1"

GENERATION_START = "generation_start"
DISCOVER = "discover"
REFLECT = "reflect"
REMOVE = "remove"
DIAGNOSTIC = "diagnostic"
GENERATION_END = "generation_end"
EVENT_TYPES = (GENERATION_START, DISCOVER, REFLECT, REMOVE, DIAGNOSTIC, GENERATION_END)

#: Footer statuses.
COMPLETE = "COMPLETE"
FAILED = "FAILED"

#: Report statuses: the two footer statuses of a capture verified to its end, and the two ways
#: verification stops short.
INCOMPLETE = "INCOMPLETE"
INVALID = "INVALID"
REPORT_VERSION = 1

#: CR-L01: an I/O refusal names the argument; this is the API's.
CAPTURE_PATH = "capture_path"

_SCHEMAS = {HEADER: "header.schema.json", FRAME: "frame.schema.json",
            FOOTER: "footer.schema.json"}

#: The largest elapsed_ns the frame schema admits: 24 decimal digits.
MAX_ELAPSED_NS = 10 ** 24 - 1
_NANOSECONDS_PER_MICROSECOND = 1000

_PARSE_REASONS = {
    canonical.INVALID_UTF8: "the line is not valid UTF-8",
    canonical.BYTE_ORDER_MARK: "the line starts with a byte order mark",
    canonical.CARRIAGE_RETURN: "the line holds a carriage return",
    canonical.TOO_DEEP: "the line nests deeper than any capture record can",
    canonical.NOT_JSON: "the line is not one JSON value",
    canonical.DUPLICATE_KEY: "the line repeats a member name",
    canonical.NON_FINITE: "the line holds a non-finite number",
    canonical.FLOAT: "the line holds a float; a capture holds only integers and strings",
    canonical.INTEGER_RANGE: "the line holds an integer beyond 2^53 - 1",
    canonical.LONE_SURROGATE: "the line holds a lone surrogate code point",
}


def header_record(config_document: dict, *, pins: dict, record_created_at: str) -> dict:
    """The header of R15 for a validated configuration, the pin map and an audit time."""
    return {"type": HEADER, "capture_version": CAPTURE_VERSION, "profile": PROFILE,
            "adapter_version": ADAPTER_VERSION, "config": config_document, "pins": pins,
            "record_created_at": record_created_at}


# --- one line's verdict ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fault:
    """Why verification stopped: the code, the CR-L01 path, the line it stopped at, a message."""

    code: str
    path: str
    line: int
    message: str


def _at(line: int, tokens: tuple = ()) -> str:
    return f"line:{line}" + (f"#{canonical.json_pointer(tokens)}" if tokens else "")


def _utf8_over(text: str, bound: int) -> bool:
    # A str of n code points is at most 4n UTF-8 bytes, so most strings need no encoding at all.
    return len(text) * 4 > bound and len(text.encode("utf-8")) > bound


class _LineRules:
    """Every rule of a capture line, and the state between lines; see the module text.

    `elapsed_may_decrease` exists for one caller, the reducer (R4): `reduce_frame` admits what a
    capture can hold at its position, except that it lets elapsed_ns decrease, because RED-09
    keeps a defensive time-regression check in the reducer that only such a frame can reach. The
    reader and the chain never set it. Two rule sets compare equal when their state is equal, so
    a reducer state holding one can be compared with a copy of itself.
    """

    def __init__(self, limits: Limits, *, elapsed_may_decrease: bool = False) -> None:
        if type(limits) is not Limits:
            raise TypeError("limits must be a Limits")
        if type(elapsed_may_decrease) is not bool:
            raise TypeError("elapsed_may_decrease must be a bool")
        self.elapsed_may_decrease = elapsed_may_decrease
        self.limits = limits
        self.lines = 0
        self.header: dict | None = None
        self.header_sha256: str | None = None
        self.last_sha256: str | None = None
        self.next_seq = 1
        self.frames = 0
        self.footer: dict | None = None
        #: The header's configuration, validated once (CR-L07), and its epoch.
        self.session: config.ValidatedConfig | None = None
        self.epoch: int | None = None
        self.open_generation: int | None = None
        self.last_generation = 0
        self.started = False
        self.last_elapsed = 0

    def __eq__(self, other: object) -> bool:
        if type(other) is not _LineRules:
            return NotImplemented
        return vars(self) == vars(other)

    __hash__ = None

    # The checks of one line. Each returns a Fault or None and changes no state; `take` commits.

    def check(self, number: int, raw: bytes) -> tuple[Fault | None, dict | None]:
        """Check line `number` (1-based, the header is 1) without its LF; commit it if it passes."""
        if len(raw) > self.limits.line_bytes:
            return Fault(errors.E_LIMIT, _at(number), number,
                         "the line is longer than the capture line limit"), None
        if self.footer is not None:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number), number,
                         "a line follows the footer"), None
        try:
            record = canonical.strict_loads(raw, floats=False, surrogates=False, staged=True)
        except canonical.StrictJsonError as refusal:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, refusal.tokens), number,
                         _PARSE_REASONS[refusal.reason]), None
        if type(record) is not dict:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number), number,
                         "the line is not a JSON object"), None
        if canonical.canonical_bytes(record) != raw:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number), number,
                         "the line is not in canonical form"), None
        session = None
        if number == 1:
            fault, session = self._header_fault(record)
        else:
            fault = self._record_fault(number, raw, record)
        if fault is not None:
            return fault, None
        self._take(number, raw, record, session)
        return None, record

    def _header_fault(self, record: dict) -> tuple[Fault | None, config.ValidatedConfig | None]:
        problem = _schema.first_problem(_SCHEMAS[HEADER], record)
        if problem is not None:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(1, problem.tokens), 1,
                         f"the header does not satisfy its schema ({problem.keyword})"), None
        try:
            _utc.parse_microsecond(record["record_created_at"])
        except ValueError:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(1, ("record_created_at",)), 1,
                         "record_created_at is not a real UTC instant in the years "
                         "1970-9998"), None
        try:
            session = config.validated_config(record["config"])
        except HlaError as refusal:
            return Fault(errors.E_CONFIG, f"line:1#/config{refusal.path}", 1,
                         refusal.message), None
        return None, session

    def _record_fault(self, number: int, raw: bytes, record: dict) -> Fault | None:
        kind = record.get("type")
        if kind not in (FRAME, FOOTER):
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("type",)), number,
                         "only frames and one footer may follow the header")
        problem = _schema.first_problem(_SCHEMAS[kind], record)
        if problem is not None:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, problem.tokens), number,
                         f"the {kind} does not satisfy its schema ({problem.keyword})")
        if kind == FRAME:
            fault = self._event_fault(number, record["event"])
            if fault is not None:
                return fault
        if record["seq"] != self.next_seq:
            return Fault(errors.E_CAPTURE_SEQUENCE, _at(number, ("seq",)), number,
                         "seq does not follow the previous record's")
        if record["prev_sha256"] != self.last_sha256:
            return Fault(errors.E_CAPTURE_HASH, _at(number, ("prev_sha256",)), number,
                         "prev_sha256 is not the previous record's digest")
        if record["sha256"] != canonical.record_sha256(record):
            return Fault(errors.E_CAPTURE_HASH, _at(number, ("sha256",)), number,
                         "sha256 is not the digest of the record")
        if kind == FRAME:
            fault = self._framing_fault(number, record)
            if fault is None and self.frames + 1 > self.limits.frames_per_session:
                fault = Fault(errors.E_LIMIT, _at(number), number,
                              "the capture holds more frames than a session may")
            return fault
        return self._footer_fault(number, record)

    def _event_fault(self, number: int, event: dict) -> Fault | None:
        """The rules the event schema is too loose for (RED-04, SPEC:72, SPEC:289)."""
        kind = event["type"]
        if kind == REFLECT:
            names = [attribute["name"] for attribute in event["attributes"]]
            for index in range(1, len(names)):
                if not names[index - 1] < names[index]:
                    return Fault(errors.E_CAPTURE_SCHEMA,
                                 _at(number, ("event", "attributes", index, "name")), number,
                                 "attribute names are not strictly ascending")
        elif kind == DISCOVER:
            if _utf8_over(event["name"], self.limits.object_name_utf8_bytes):
                return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("event", "name")), number,
                             "the object name is longer than its UTF-8 byte limit")
            if _utf8_over(event["reported_class"], self.limits.class_name_utf8_bytes):
                return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("event", "reported_class")),
                             number, "the reported class is longer than its UTF-8 byte limit")
        elif kind == DIAGNOSTIC:
            # The schema admits any ^[EW]_[A-Z_]+$ code and either severity. A captured
            # diagnostic becomes one output diagnostic as it stands (RED-01), so a code outside
            # the closed catalogue, or a severity its prefix contradicts (OPS-19, RED-03), would
            # reach the output stream; it is refused here, where replay can still refuse the
            # capture before writing anything (R35). Checked in the line's member order.
            diagnostic = event["diagnostic"]
            if not errors.is_code(diagnostic["code"]):
                return Fault(errors.E_CAPTURE_SCHEMA,
                             _at(number, ("event", "diagnostic", "code")), number,
                             "the diagnostic code is not one of the catalogue's")
            if _utf8_over(diagnostic["message"], self.limits.diagnostic_message_utf8_bytes):
                return Fault(errors.E_CAPTURE_SCHEMA,
                             _at(number, ("event", "diagnostic", "message")), number,
                             "the diagnostic message is longer than its UTF-8 byte limit")
            if diagnostic["severity"] != errors.severity(diagnostic["code"]):
                return Fault(errors.E_CAPTURE_SCHEMA,
                             _at(number, ("event", "diagnostic", "severity")), number,
                             "the diagnostic severity is not the one its code's prefix gives")
        return None

    def _framing_fault(self, number: int, frame: dict) -> Fault | None:
        generation = frame["generation"]
        elapsed = int(frame["elapsed_ns"])
        kind = frame["event"]["type"]
        if not self.started and elapsed != 0:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("elapsed_ns",)), number,
                         "elapsed_ns is not 0 up to the first generation_start")
        if elapsed < self.last_elapsed and not self.elapsed_may_decrease:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("elapsed_ns",)), number,
                         "elapsed_ns decreases")
        if self.open_generation is None:
            if kind not in (GENERATION_START, DIAGNOSTIC):
                return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("event", "type")), number,
                             "only diagnostics and generation_start may come between generations")
            expected = self.last_generation + 1 if kind == GENERATION_START else 0
        else:
            if kind == GENERATION_START:
                return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("event", "type")), number,
                             "generation_start inside an open generation")
            expected = self.open_generation
        if generation != expected:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("generation",)), number,
                         "the frame carries another generation than the lifecycle gives it")
        if kind == GENERATION_START and \
                frame["event"]["federation_name"] != self.session.document["federation_name"]:
            # CR-L09: a generation is a join of the configured federation and of no other. The
            # host always writes the configured name, so only a crafted capture differs here.
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("event", "federation_name")),
                         number, "generation_start names another federation than the "
                         "configured one")
        if self.epoch is not None and \
                self.epoch + elapsed // _NANOSECONDS_PER_MICROSECOND > _utc.MAX_MICROSECOND:
            return Fault(errors.E_CONFIG, "line:1#/config/time_policy/epoch", number,
                         "epoch plus elapsed time passes 9998-12-31T23:59:59.999999Z")
        return None

    def _footer_fault(self, number: int, footer: dict) -> Fault | None:
        if footer["last_generation"] != self.last_generation:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("last_generation",)), number,
                         "last_generation is not the highest generation started")
        reason = footer["reason_code"]
        if footer["status"] == COMPLETE:
            agrees = reason is None
        else:
            agrees = errors.is_code(reason) and errors.severity(reason) == errors.ERROR
        if not agrees:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("reason_code",)), number,
                         "a COMPLETE footer has no reason and a FAILED one an E_ catalogue code")
        if self.open_generation is not None:
            return Fault(errors.E_CAPTURE_SCHEMA, _at(number, ("type",)), number,
                         "the footer comes while a generation is open")
        return None

    def _take(self, number: int, raw: bytes | None, record: dict,
              session: config.ValidatedConfig | None) -> None:
        # `raw` is read for the header only (its digest is of the exact bytes); a frame or the
        # footer is taken by its record, which is how the reducer takes a frame its caller's
        # own rules admitted (`reducer.reduce_admitted`).
        self.lines = number
        if number == 1:
            self.header = record
            self.header_sha256 = canonical.sha256_hex(raw)
            self.last_sha256 = self.header_sha256
            self.session = session
            self.epoch = session.epoch_microsecond
            return
        self.last_sha256 = record["sha256"]
        self.next_seq += 1
        if record["type"] == FOOTER:
            # A copy: the reader hands `record` itself to its consumer, and nothing the consumer
            # does to it may change the status or the footer the report gives.
            self.footer = dict(record)
            return
        self.frames += 1
        kind = record["event"]["type"]
        self.started = self.started or kind == GENERATION_START
        self.last_elapsed = int(record["elapsed_ns"])
        if kind == GENERATION_START:
            self.open_generation = record["generation"]
            self.last_generation = record["generation"]
        elif kind == GENERATION_END:
            self.open_generation = None


# --- reading ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class VerifiedLine:
    """One line that passed every rule: its number, its record and its exact bytes (no LF)."""

    number: int
    record: dict
    raw: bytes


#: Opening without blocking matters for a FIFO named as the capture: a plain open would wait for
#: a writer forever. The flags do not exist everywhere, and where they do not, neither do FIFOs
#: that block in this way.
_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


def _open_capture(capture_path):
    # A file name is bytes to the operating system. Encoding a str path here, rather than letting
    # os.open do it, keeps the two names no file can have on the E_IO path: a NUL byte, and a lone
    # surrogate that the file-system encoding cannot write (os.open would raise
    # UnicodeEncodeError, a ValueError, for it instead of an OSError).
    try:
        path = os.fsencode(capture_path)
    except UnicodeEncodeError:
        raise HlaError(errors.E_IO, CAPTURE_PATH, "the capture path cannot name a file") from None
    if b"\x00" in path:
        raise HlaError(errors.E_IO, CAPTURE_PATH, "the capture path cannot name a file")
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except OSError:
        raise HlaError(errors.E_IO, CAPTURE_PATH, "the capture cannot be opened") from None
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:
        os.close(fd)
        raise HlaError(errors.E_IO, CAPTURE_PATH, "the capture is not a readable regular file")
    return os.fdopen(fd, "rb")


class CaptureReader:
    """A verified streaming reader of one capture file.

    `records()` yields a `VerifiedLine` for every line that passed every rule, header first, in
    file order, and stops at the first that did not; `report` then holds the verify report. The
    reader keeps no record it has yielded, and `limits` is the OPS-21 seam (tests only).
    """

    def __init__(self, capture_path, *, limits: Limits = V1) -> None:
        self._path = capture_path
        self._rules = _LineRules(limits)
        self._report: dict | None = None
        self._used = False

    @property
    def report(self) -> dict:
        if self._report is None:
            raise RuntimeError("the report exists once records() has been read to its end")
        return self._report

    def records(self):
        if self._used:
            raise RuntimeError("a CaptureReader reads its capture once")
        self._used = True
        rules = self._rules
        limits = rules.limits
        fault = None
        verified_bytes = 0
        with _open_capture(self._path) as stream:
            number = 0
            while fault is None:
                try:
                    chunk = stream.readline(limits.line_bytes + 1)
                except OSError:
                    raise HlaError(errors.E_IO, CAPTURE_PATH,
                                   "the capture cannot be read") from None
                if not chunk:
                    break
                number += 1
                if verified_bytes + len(chunk) > limits.capture_file_bytes:
                    fault = Fault(errors.E_LIMIT, _at(number), number,
                                  "the capture is larger than the capture file limit")
                elif not chunk.endswith(b"\n"):
                    if len(chunk) > limits.line_bytes:
                        fault = Fault(errors.E_LIMIT, _at(number), number,
                                      "the line is longer than the capture line limit")
                    else:
                        # RED-06: bytes after the last LF are a partial final line, and it is
                        # never parsed: a cut can split a UTF-8 sequence or a record anywhere.
                        fault = (Fault(errors.E_CAPTURE_SCHEMA, _at(number), number,
                                       "a line follows the footer")
                                 if rules.footer is not None else
                                 Fault(errors.E_CAPTURE_INCOMPLETE, _at(number), number,
                                       "the capture ends inside a line"))
                else:
                    fault, record = rules.check(number, chunk[:-1])
                    if fault is None:
                        verified_bytes += len(chunk)
                        yield VerifiedLine(number, record, chunk[:-1])
        if fault is None and rules.footer is None:
            missing = rules.lines + 1
            fault = Fault(errors.E_CAPTURE_INCOMPLETE, _at(missing), missing,
                          "the capture has no footer" if rules.header is not None
                          else "the capture has no header")
        self._report = _report(rules, fault, verified_bytes)


def _report(rules: _LineRules, fault: Fault | None, verified_bytes: int) -> dict:
    if fault is None:
        status = rules.footer["status"]
    elif fault.code == errors.E_CAPTURE_INCOMPLETE:
        status = INCOMPLETE
    else:
        status = INVALID
    if rules.header is None:
        verified_seq = None
    else:
        verified_seq = rules.next_seq - 1
    return {
        "verify_report_version": REPORT_VERSION,
        "status": status,
        "code": None if fault is None else fault.code,
        "path": None if fault is None else fault.path,
        "message": None if fault is None else fault.message,
        "verified_seq": verified_seq,
        "verified_bytes": verified_bytes,
        "frames": rules.frames,
        "header_sha256": rules.header_sha256,
        "last_sha256": rules.last_sha256,
        "capture_complete": status == COMPLETE,
        "footer": rules.footer,
    }


def verify_capture(capture_path) -> dict:
    """Verify the capture at `capture_path` from its first byte to its last; return the report.

    See the module text for the rules and the report. Raises `HlaError` E_IO only when the file
    cannot be opened or read, or is not a regular file.
    """
    reader = CaptureReader(capture_path)
    for _ in reader.records():
        pass
    return reader.report


# --- writing ------------------------------------------------------------------------------------

class CaptureChain:
    """The hash chain as an object: a header, then frames, then a footer become canonical lines.

    Pure: it holds the chain state and returns each line's bytes, LF included, for a writer to
    put on disk (R5's durable writer owns files, fsync and the size reserve). Every line passes
    the reader's rules before it is returned; a record that would not raises `HlaError` with the
    code and the `line:<n>` path the reader would have reported, and the chain is left as it was.
    Arguments of the wrong Python type are caller bugs (TypeError, ValueError).
    """

    def __init__(self, *, limits: Limits = V1) -> None:
        self._rules = _LineRules(limits)

    @property
    def next_seq(self) -> int:
        return self._rules.next_seq

    @property
    def last_sha256(self) -> str | None:
        return self._rules.last_sha256

    @property
    def open_generation(self) -> int | None:
        return self._rules.open_generation

    @property
    def last_generation(self) -> int:
        """The highest generation started so far: what the footer's `last_generation` must say."""
        return self._rules.last_generation

    @property
    def frames(self) -> int:
        return self._rules.frames

    def _emit(self, record: dict) -> bytes:
        number = self._rules.lines + 1
        try:
            raw = canonical.canonical_bytes(record)
        except canonical.StrictJsonError as refusal:
            raise HlaError(errors.E_CAPTURE_SCHEMA, _at(number, refusal.tokens),
                           _PARSE_REASONS[refusal.reason]) from None
        fault, _ = self._rules.check(number, raw)
        if fault is not None:
            raise HlaError(fault.code, fault.path, fault.message)
        return raw + b"\n"

    def header(self, record: dict) -> bytes:
        """The header line. `record` is the whole header object (see `header_record`)."""
        if self._rules.lines != 0:
            raise ValueError("the header is the first line and comes once")
        if type(record) is not dict:
            raise TypeError("the header is a dict")
        return self._emit(record)

    def frame(self, generation: int, elapsed_ns: int, event: dict) -> bytes:
        """The next frame line, from its generation, elapsed nanoseconds and event."""
        if self._rules.header is None or self._rules.footer is not None:
            raise ValueError("frames come after the header and before the footer")
        if type(generation) is not int or type(elapsed_ns) is not int:
            raise TypeError("generation and elapsed_ns are ints")
        if not 0 <= elapsed_ns <= MAX_ELAPSED_NS:
            raise ValueError("elapsed_ns is outside 0 to 10^24 - 1")
        if type(event) is not dict:
            raise TypeError("the event is a dict")
        record = {"type": FRAME, "seq": self._rules.next_seq, "generation": generation,
                  "elapsed_ns": str(elapsed_ns), "event": event,
                  "prev_sha256": self._rules.last_sha256}
        return self._emit(self._sealed(record))

    def footer(self, status: str, reason_code: str | None, last_generation: int) -> bytes:
        """The footer line, which ends the chain."""
        if self._rules.header is None or self._rules.footer is not None:
            raise ValueError("the footer comes once, after the header")
        record = {"type": FOOTER, "seq": self._rules.next_seq, "status": status,
                  "reason_code": reason_code, "last_generation": last_generation,
                  "prev_sha256": self._rules.last_sha256}
        return self._emit(self._sealed(record))

    def _sealed(self, record: dict) -> dict:
        number = self._rules.lines + 1
        try:
            digest = canonical.record_sha256(record)
        except canonical.StrictJsonError as refusal:
            raise HlaError(errors.E_CAPTURE_SCHEMA, _at(number, refusal.tokens),
                           _PARSE_REASONS[refusal.reason]) from None
        return {**record, "sha256": digest}
