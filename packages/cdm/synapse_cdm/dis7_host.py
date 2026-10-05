"""The host boundary of the DIS 7 adapter, holding the strict JSON text loader.

`parse_json_text` turns envelope text into a document for cases N18 and N20, which need an API
for JSON text that the contract does not name (resolution CR-11). It takes bytes and checks, in
this order, that they are bytes, that there are at most `MAX_JSON_BYTES` of them, that they hold
no NUL, that they are strict UTF-8 with no byte-order mark, and that the text nests no deeper
than `MAX_JSON_DEPTH` containers, before the decoder sees the decoded text — never the bytes,
which the decoder would read as UTF-16 or UTF-32 when they look like it. The decoder then
refuses the `NaN` and `Infinity` tokens, numbers that overflow to infinity, oversized integer
literals and repeated keys. Every refusal is a `Dis7Error`; its message is a fixed literal that
names at most the byte count and the two bounds, never a key, a value or a byte of the input.

The module is also the offline host command `synapse-dis7` (`python -m synapse_cdm.dis7_host`):

- `decode --input F --at T --basis B --session S (--synthetic | --live)` reads at most one octet
  more than the PDU bound, refuses an oversized file before anything interprets it, hashes exactly
  the file bytes with SHA-256 into `source_hash`, and writes the one-element Entity array as
  canonical UTF-8 JSON;
- `replay --input entity.json [--session S] [--synthetic | --live]` reads at most one octet more
  than the JSON bound, accepts only the canonical one-element Entity array, binds the session and
  the classification from the stored residual (a flag, when given, is asserted against it) and
  writes the original PDU octets and nothing else;
- `self-test` runs the packaged vectors and a sample of refusals offline and reports one line per
  check;
- `--version` prints the adapter, package and specification identifiers.

Exit codes: 0 success; 2 a usage error or a context derived from the flags (`--at`, `--basis`,
`--session`); 3 rejected data, every `Dis7Error` raised while processing `--input`, and a failed
self-test; 4 a file or output I/O failure, including a closed output pipe and an `--input` that is
not a regular file, which is refused without blocking, even for a FIFO renamed onto the path while
it is read. Diagnostics go to stderr, one line each; stdout carries only the result. A basis
beginning with `-` must be written `--basis=VALUE`. `--live` only sets the canonical flag; it
authenticates nothing. No file is written and no network is touched. The specification the
command implements is a handoff document identified by `SC DIS7 SPEC 001 v1.0`; it is not in this
repository.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import stat
import sys

from pydantic import TypeAdapter, ValidationError

from synapse_cdm import canonical
from synapse_cdm.adapter import json_nesting_depth, packaged_fixtures
from synapse_cdm.adapters.dis7 import Dis7Adapter, TimeContext, validate_session
from synapse_cdm.adapters.dis7_codec import (
    E_HEADER_UNSUPPORTED,
    E_INPUT_LIMIT,
    E_INPUT_TYPE,
    E_LENGTH_MISMATCH,
    E_REPLAY_SHAPE,
    E_TWIN_SCHEMA,
    MAX_PDU_BYTES,
    Dis7Error,
    Dis7InputTooDeep,
    Dis7InputTooLarge,
)
from synapse_cdm.models import Entity
from synapse_cdm.version import PACKAGE_VERSION

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REJECTED = 3
EXIT_IO = 4

SPECIFICATION_ID = "SC DIS7 SPEC 001"
SPECIFICATION_VERSION = "1.0"

MAX_JSON_BYTES = 65536
MAX_JSON_DEPTH = 16

# CPython's default integer-string limit, held here so the refusal does not depend on the
# interpreter's setting.
_MAX_INT_LITERAL = 4300

# A key is written into a diagnostic path only when it has this shape.
_SPELLABLE_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")


class _RepeatedKey:
    """The type of the one marker an object with a repeated key decodes to."""

    __slots__ = ()


_REPEATED = _RepeatedKey()


def _refuse_constant(_token: str) -> object:
    raise ValueError("a non-finite token")


def _finite_float(literal: str) -> float:
    value = float(literal)
    if not math.isfinite(value):
        raise ValueError("a number that overflows")
    return value


def _bounded_int(literal: str) -> int:
    if len(literal) > _MAX_INT_LITERAL:
        raise ValueError("an oversized integer literal")
    return int(literal)


def _pairs(pairs: list) -> object:
    keys = {key for key, _ in pairs}
    if len(keys) != len(pairs):
        return _REPEATED
    return dict(pairs)


def _repeated_key_path(document: object) -> str | None:
    """The path of the first object with a repeated key in document order, or None.

    Iterative, with an explicit stack: an object before its members, members in text order,
    array items by index. Below a key that is not spellable every container reports the path
    of the nearest ancestor reached through spellable keys.
    """
    stack = [(document, "$", False)]
    while stack:
        node, path, frozen = stack.pop()
        if node is _REPEATED:
            return path
        children = []
        if isinstance(node, dict):
            for key, value in node.items():
                if frozen or not _SPELLABLE_KEY.fullmatch(key):
                    children.append((value, path, True))
                else:
                    children.append((value, key if path == "$" else f"{path}.{key}", False))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if frozen:
                    children.append((value, path, True))
                else:
                    children.append((value, f"[{index}]" if path == "$" else f"{path}[{index}]",
                                     False))
        stack.extend(reversed(children))
    return None


def parse_json_text(data: bytes) -> object:
    """The JSON document `data` holds, or a `Dis7Error` naming the first check it fails."""
    if type(data) is not bytes:
        raise Dis7Error(E_INPUT_TYPE, "$", "JSON text must be given as bytes")
    if len(data) > MAX_JSON_BYTES:
        raise Dis7InputTooLarge("$", f"input is {len(data)} octets; the limit is {MAX_JSON_BYTES}")
    if b"\x00" in data:
        raise Dis7Error(E_TWIN_SCHEMA, "$", "the JSON text contains a NUL octet")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Dis7Error(E_TWIN_SCHEMA, "$", "the JSON text is not valid UTF-8") from None
    if text.startswith("\ufeff"):
        raise Dis7Error(E_TWIN_SCHEMA, "$", "the JSON text begins with a byte-order mark")
    if json_nesting_depth(text) > MAX_JSON_DEPTH:
        raise Dis7InputTooDeep("$", f"the text nests deeper than {MAX_JSON_DEPTH} containers")
    try:
        document = json.loads(text, object_pairs_hook=_pairs, parse_constant=_refuse_constant,
                              parse_float=_finite_float, parse_int=_bounded_int)
    except (ValueError, RecursionError):
        raise Dis7Error(E_TWIN_SCHEMA, "$", "the JSON text cannot be decoded") from None
    path = _repeated_key_path(document)
    if path is not None:
        raise Dis7Error(E_TWIN_SCHEMA, path, "an object repeats a key")
    return document


# -- the host command ------------------------------------------------------------------------

_NOT_CANONICAL = "the document is not a canonical one-element Entity array"


def _read_bounded(path: str, limit: int) -> bytes:
    """At most `limit + 1` octets of the regular file `path`; anything else is an `OSError`.

    The type is checked on the path before opening, so a FIFO or a device is not opened, and
    again on the descriptor actually read, which is opened without blocking, so a FIFO renamed
    onto the path between the two checks is refused instead of waiting for a writer. Each read
    asks for no more than the octets still wanted, so no more than `limit + 1` are read.
    """
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise OSError("not a regular file")
    flags = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)
             | getattr(os, "O_BINARY", 0))
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        chunks, wanted = [], limit + 1
        while wanted:
            chunk = os.read(fd, wanted)
            if not chunk:
                break
            chunks.append(chunk)
            wanted -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _emit(data: bytes) -> int:
    """Write `data` to stdout and flush it; a failed write is exit 4, never a traceback."""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        _diagnose("synapse-dis7: cannot write output: stdout is closed")
        return EXIT_IO
    try:
        stream.write(data)
        stream.flush()
        return EXIT_OK
    except (OSError, ValueError) as error:
        # Without the redirect the interpreter flushes the same buffer again at exit, reports
        # "Exception ignored" and exits 120.
        try:
            target = sys.stdout.fileno()
            fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(fd, target)
            finally:
                os.close(fd)
        except (OSError, ValueError, AttributeError):
            pass
        _diagnose("synapse-dis7: cannot write output: "
                  + (getattr(error, "strerror", None) or str(error)))
        return EXIT_IO


def _diagnose(line: str) -> None:
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(line + "\n")
        stream.flush()
    except (OSError, ValueError, AttributeError):
        # Without this the interpreter flushes the same line again at exit, fails and exits 120.
        sys.stderr = None


def _fixture_dir() -> pathlib.Path:
    """The installed package's `dis7` fixtures, looked up at call time."""
    return packaged_fixtures(Dis7Adapter)


def _same_json(a: object, b: object) -> bool:
    """Equality of two parsed JSON values in which a boolean equals only a boolean."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is bool and type(b) is bool and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same_json(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same_json(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _cmd_decode(args: argparse.Namespace) -> int:
    try:
        session = validate_session(args.session)
        context = TimeContext(args.at, args.basis)
    except Dis7Error as error:
        _diagnose(str(error))
        return EXIT_USAGE
    try:
        raw = _read_bounded(args.input, MAX_PDU_BYTES)
    except OSError as error:
        _diagnose("synapse-dis7: cannot read --input: " + (error.strerror or str(error)))
        return EXIT_IO
    try:
        if len(raw) > MAX_PDU_BYTES:
            raise Dis7InputTooLarge(
                "$", f"input is at least {len(raw)} octets; the limit is {MAX_PDU_BYTES}")
        from synapse_cdm import evidence

        value = evidence.digest_bytes(raw)[0]
        adapter = Dis7Adapter(session=session, synthetic=args.synthetic, time_context=context,
                              source_hash={"algorithm": "sha256", "value": value})
        objects = adapter.to_cdm(raw)
    except Dis7Error as error:
        _diagnose(str(error))
        return EXIT_REJECTED
    return _emit(canonical.serialise([o.model_dump(mode="json") for o in objects]).encode("utf-8"))


def _replayed(data: bytes, session: str | None, synthetic: bool | None) -> bytes:
    """The PDU octets of the canonical Entity document `data`, or a `Dis7Error`."""
    try:
        document = parse_json_text(data)
    except Dis7Error as error:
        if error.code == E_TWIN_SCHEMA:
            raise Dis7Error(E_REPLAY_SHAPE, error.path, error.message) from None
        raise
    try:
        entities = TypeAdapter(list[Entity]).validate_json(data)
    except ValidationError:
        # Never the validation error's text: it echoes the input.
        raise Dis7Error(E_REPLAY_SHAPE, "$", _NOT_CANONICAL) from None
    if not _same_json([e.model_dump(mode="json") for e in entities], document):
        raise Dis7Error(E_REPLAY_SHAPE, "$", _NOT_CANONICAL)
    if len(entities) != 1:
        raise Dis7Error(E_REPLAY_SHAPE, "$", _NOT_CANONICAL)
    residual = entities[0].residual
    if residual is None or residual.namespace != "DIS":
        raise Dis7Error(E_REPLAY_SHAPE, "[0].residual",
                        "the Entity carries no residual of this format")
    stored_session = residual.data.get("session")
    if type(stored_session) is not str:
        raise Dis7Error(E_REPLAY_SHAPE, "[0].residual.data.session",
                        "the stored session is not a string")
    try:
        validate_session(stored_session)
    except Dis7Error:
        raise Dis7Error(E_REPLAY_SHAPE, "[0].residual.data.session",
                        "the stored session is not a valid session") from None
    stored_synthetic = residual.data.get("synthetic")
    if type(stored_synthetic) is not bool:
        raise Dis7Error(E_REPLAY_SHAPE, "[0].residual.data.synthetic",
                        "the stored classification is not a boolean")
    adapter = Dis7Adapter(session=stored_session if session is None else session,
                          synthetic=stored_synthetic if synthetic is None else synthetic)
    return adapter.from_cdm(entities)


def _cmd_replay(args: argparse.Namespace) -> int:
    if args.session is not None:
        try:
            validate_session(args.session)
        except Dis7Error as error:
            _diagnose(str(error))
            return EXIT_USAGE
    try:
        data = _read_bounded(args.input, MAX_JSON_BYTES)
    except OSError as error:
        _diagnose("synapse-dis7: cannot read --input: " + (error.strerror or str(error)))
        return EXIT_IO
    if len(data) > MAX_JSON_BYTES:
        # The read stops one octet past the bound, so the file's size is only known as a floor.
        _diagnose(str(Dis7InputTooLarge(
            "$", f"input is at least {len(data)} octets; the limit is {MAX_JSON_BYTES}")))
        return EXIT_REJECTED
    try:
        raw = _replayed(data, args.session, args.synthetic)
    except Dis7Error as error:
        _diagnose(str(error))
        return EXIT_REJECTED
    return _emit(raw)


def _refuses(call, code: str, path: str) -> bool:
    """Does `call()` raise a `Dis7Error` with exactly this code and path?"""
    try:
        call()
    except Dis7Error as error:
        return error.code == code and error.path == path
    return False


def _self_test_checks() -> list[tuple[str, object]]:
    """The self-test's checks in report order, each a name and a callable returning a bool."""
    root = _fixture_dir()

    def read_json(name: str) -> object:
        return parse_json_text(_read_bounded(str(root / name), MAX_JSON_BYTES))

    def read_wire(name: str) -> bytes:
        return _read_bounded(str(root / name), MAX_PDU_BYTES)

    def built(row: dict) -> Dis7Adapter:
        context = read_json(row["context_file"])
        return Dis7Adapter(session=context["session"], synthetic=context["synthetic"],
                           time_context=TimeContext(context["time_context"]["instant"],
                                                    context["time_context"]["basis"]),
                           source_hash=context["source_hash"])

    def dumped(objects) -> list:
        return [o.model_dump(mode="json") for o in objects]

    def index_check(row):
        return lambda: (len(read_wire(row["wire_file"])) == row["bytes"]
                        and row["expected_status"] == "ACCEPT" and row["replay"] == "byte_exact")

    def decode_check(row):
        return lambda: _same_json(dumped(built(row).to_cdm(read_wire(row["wire_file"]))),
                                  read_json(row["expected_file"]))

    def replay_check(row):
        def check():
            adapter, wire = built(row), read_wire(row["wire_file"])
            return adapter.from_cdm(adapter.to_cdm(wire)) == wire
        return check

    def envelope_check(row):
        def check():
            adapter = built(row)
            objects = adapter.to_cdm(read_json(row["envelope_file"]))
            return (_same_json(dumped(objects), read_json(row["expected_file"]))
                    and adapter.from_cdm(objects) == read_wire(row["wire_file"]))
        return check

    rows = read_json("vectors/index.json")
    checks: list[tuple[str, object]] = []
    for row in rows:
        checks.append((f"index {row['id']}", index_check(row)))
        checks.append((f"decode {row['id']}", decode_check(row)))
        checks.append((f"replay {row['id']}", replay_check(row)))
        checks.append((f"envelope {row['id']}", envelope_check(row)))

    first = rows[0]

    def refusal(make, code, path):
        def check():
            adapter, wire = built(first), read_wire(first["wire_file"])
            return _refuses(lambda: make(adapter, wire), code, path)
        return check

    checks.append(("refusal header", refusal(
        lambda adapter, wire: adapter.to_cdm(b"\x06" + wire[1:]), E_HEADER_UNSUPPORTED,
        "byte[0]")))
    checks.append(("refusal truncated", refusal(
        lambda adapter, wire: adapter.to_cdm(wire[:143]), E_LENGTH_MISMATCH, "byte[143]")))
    checks.append(("refusal oversize", refusal(
        lambda adapter, wire: adapter.to_cdm(bytes(MAX_PDU_BYTES + 1)), E_INPUT_LIMIT, "$")))
    checks.append(("refusal empty replay", refusal(
        lambda adapter, wire: adapter.from_cdm([]), E_REPLAY_SHAPE, "$")))
    return checks


def _cmd_self_test(args: argparse.Namespace) -> int:
    lines = []
    failed = 0
    try:
        checks = _self_test_checks()
    except Exception as error:  # an unreadable index is a failed self-test
        checks = [("index", _raiser(error))]
    for name, check in checks:
        try:
            outcome = "PASS" if check() else "mismatch"
        except Exception as error:  # every exception inside a check is its FAIL
            outcome = type(error).__name__
        if outcome == "PASS":
            lines.append(f"PASS {name}")
        else:
            failed += 1
            lines.append(f"FAIL {name}: {outcome}")
    lines.append(f"self-test: {len(checks)} checks, {failed} failed")
    if _emit(("\n".join(lines) + "\n").encode("utf-8")) != EXIT_OK:
        return EXIT_IO
    return EXIT_OK if failed == 0 else EXIT_REJECTED


def _raiser(error: Exception):
    def check():
        raise error
    return check


class _Parser(argparse.ArgumentParser):
    """A parser that keeps stdout for the result and stderr for diagnostics (PLAN 4.8).

    With stdout closed it writes no help, and `main` exits 4; argparse would write the help to
    stderr instead. With stderr closed a usage error writes nothing and exits 2; argparse would
    write the usage to stdout instead. The sub-parsers take this class from their parent through
    `add_subparsers`.
    """

    def print_help(self, file=None):
        if file is None and sys.stdout is None:
            return
        super().print_help(file)

    def error(self, message):
        if sys.stderr is None:
            self.exit(EXIT_USAGE)
        super().error(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="synapse-dis7", allow_abbrev=False,
        description="Offline host command of the DIS 7 Entity State adapter: decode, replay, "
                    "self-test. decode and replay read the one --input file and self-test the "
                    "packaged vectors; it writes stdout and writes no file.")
    parser.add_argument("--version", action="store_true",
                        help="print the adapter, package and specification identifiers")
    commands = parser.add_subparsers(dest="command", metavar="{decode,replay,self-test}")

    def classification(sub, required):
        group = sub.add_mutually_exclusive_group(required=required)
        group.add_argument("--synthetic", action="store_const", const=True, dest="synthetic",
                           help="classify the data as synthetic")
        group.add_argument("--live", action="store_const", const=False, dest="synthetic",
                           help="classify the data as live; this only sets the canonical flag "
                                "and authenticates nothing")

    decode = commands.add_parser("decode", allow_abbrev=False,
                                 help="one PDU file to a canonical one-element Entity array")
    decode.add_argument("--input", required=True, help="the PDU file")
    decode.add_argument("--at", required=True, help="the state instant, RFC 3339")
    decode.add_argument("--basis", required=True,
                        help="how the instant was resolved; a basis beginning with - must be "
                             "written --basis=VALUE")
    decode.add_argument("--session", required=True, help="the session name")
    classification(decode, True)

    replay = commands.add_parser("replay", allow_abbrev=False,
                                 help="a canonical one-element Entity array back to its PDU octets")
    replay.add_argument("--input", required=True, help="the Entity document")
    replay.add_argument("--session", default=None,
                        help="assert the stored session; by default it is taken from the document")
    classification(replay, False)

    commands.add_parser("self-test", allow_abbrev=False,
                        help="run the packaged vectors and a sample of refusals offline")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if not args.version and args.command is None:
            parser.error("a command is required: decode, replay or self-test")
    except SystemExit as stop:
        if stop.code != 0:
            # argparse wrote the usage through the text-mode stderr; flush it here, so a failed
            # write keeps exit 2 and is not the interpreter's exit-time failure with exit 120.
            try:
                if sys.stderr is not None:
                    sys.stderr.flush()
            except (OSError, ValueError):
                sys.stderr = None
            raise
        if sys.stdout is None:
            _diagnose("synapse-dis7: cannot write output: stdout is closed")
            return EXIT_IO
        # argparse wrote the help through the text-mode stdout; flush it here, so a failed write
        # is exit 4 and not the interpreter's exit-time "Exception ignored" with exit 120.
        try:
            sys.stdout.flush()
        except (OSError, ValueError) as error:
            sys.stdout = None
            _diagnose("synapse-dis7: cannot write output: "
                      + (getattr(error, "strerror", None) or str(error)))
            return EXIT_IO
        raise
    if args.version:
        return _emit((f"adapter {Dis7Adapter.name} {Dis7Adapter.version}\n"
                      f"package synapse-cdm {PACKAGE_VERSION}\n"
                      f"specification {SPECIFICATION_ID} {SPECIFICATION_VERSION}\n")
                     .encode("utf-8"))
    handlers = {"decode": _cmd_decode, "replay": _cmd_replay, "self-test": _cmd_self_test}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
