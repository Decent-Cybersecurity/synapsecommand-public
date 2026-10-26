"""The `sc-imagery` command: five local subcommands over the host's Python API.

    sc-imagery inspect INPUT --json OUTPUT [--replace]
    sc-imagery ingest INPUT --store STORE --dataset NAME --synthetic true|false
                     [--product-key KEY] [--as-of INSTANT --as-of-basis TEXT]
    sc-imagery preview RECORD_ID --image N --store STORE --output OUTPUT.png
                       [--bands B[,B,B]] [--replace]
    sc-imagery replay RECORD_ID --store STORE --output OUTPUT.ntf [--replace]
    sc-imagery export-nc RECIPE.json --store STORE --output OUTPUT.ntf [--replace]
    sc-imagery --version

Every command runs as the one local principal (tenant `local`, subject `local-operator`) under
the default policy, the isolated worker pool and, with `--store`, the local store after its
recovery pass; no option selects another policy, a fake, a tenant or a registry. The live or
synthetic choice of `ingest` has no default. Stdout carries only the command's document, in the
canonical JSON form; `inspect` writes its document only to the output it is given (`-` is stdout).

PATHS
-----
A path argument that is empty, names a URI scheme (`file:`, `http:`, `s3:`, a drive letter like
`C:`) or a `/vsi` virtual path is refused before anything is opened; a local name with a colon is
given as `./name`. Inputs must be regular files (a symlink to one is followed); a FIFO, a device
or a directory is refused without blocking. An existing output is replaced only with `--replace`,
and every output is written under a temporary name beside it, flushed and linked into place.

EXIT CODES AND STDERR
---------------------
0 success; 2 a command or configuration error; 3 malformed input; 4 an operation this
deployment does not perform; 5 a policy denial; 6 a resource cap, a timeout or a full queue;
7 an I/O or internal failure; 130 an interrupt, after which nothing uncommitted is left behind.
Stderr carries fixed lines only, with identifiers and codes, never a path, title, label value,
coordinate, extension tag or source text: `sc-imagery: WORKER_MEMORY_NOT_ENFORCED` first when the
worker reported that its memory cap is not enforced on this platform, then one outcome line.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import stat
import sys
from collections.abc import Callable, Sequence

from synapse_cdm import canonical
from synapse_cdm.adapters.nsif_codec import NsifError

from synapse_imagery._version import __version__
from synapse_imagery.result import HostError

SUBCOMMANDS = ("inspect", "ingest", "preview", "replay", "export-nc")
USAGE = "usage: sc-imagery {inspect,ingest,preview,replay,export-nc} ... | sc-imagery --version"
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_DECIMAL = re.compile(r"[0-9]{1,9}")
_BANDS = re.compile(r"[0-9]{1,5}(,[0-9]{1,5}){0,2}")

#: The exit status of a coded outcome, `(code, stages, path prefix, status)`, first match wins;
#: `None` matches anything. A command error that has no code (a usage error, a refused option,
#: a URI path, an output that exists or has no directory, a store that is not a store) is 2.
EXIT_CODES = (
    ("E_FIELD", ("storage",), None, 2),
    ("E_CONTEXT", None, None, 2),
    ("E_FIELD", ("pixels",), "/window", 2),
    ("E_MAGIC", None, None, 3),
    ("E_DIGITS", None, None, 3),
    ("E_LENGTH", None, None, 3),
    ("E_OVERFLOW", None, None, 3),
    ("E_FIELD", ("input", "header", "segment", "extension"), None, 3),
    ("E_PROFILE", ("input", "header", "segment", "extension"), None, 3),
    ("E_FIELD", ("pixels",), "/segments/", 3),
    ("E_FIELD", ("export",), None, 3),
    ("E_CODEC", None, None, 4),
    ("E_ENCRYPTED", None, None, 4),
    ("E_PROFILE", ("pixels", "export"), None, 4),
    ("E_POLICY", None, None, 5),
    ("E_LIMIT", None, None, 6),
    ("E_TIMEOUT", None, None, 6),
    ("E_BUSY", None, None, 6),
    ("E_IO", None, None, 7),
    ("E_INTEGRITY", None, None, 7),
    ("E_INTERNAL", None, None, 7),
    ("E_GEOMETRY", None, None, 7),
)
INTERRUPTED = 130


def exit_status(code: str, stage: str, path: str) -> int:
    for row_code, stages, prefix, status in EXIT_CODES:
        if row_code != code or (stages is not None and stage not in stages):
            continue
        if prefix is None or path.startswith(prefix):
            return status
    return 7


class _Usage(Exception):
    """A command error: exit 2 with fixed stderr lines."""

    def __init__(self, *lines: str) -> None:
        super().__init__("usage error")
        self.lines = lines


def _usage(option: str, text: str) -> _Usage:
    return _Usage(f"sc-imagery: usage error: {option} {text}")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        # argparse's own message quotes what was typed; only the class of error is printed.
        raise _Usage("sc-imagery: usage error", USAGE)


def _image_index(text: str) -> int:
    if not _DECIMAL.fullmatch(text):
        raise argparse.ArgumentTypeError("not an image index")
    return int(text)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="sc-imagery", allow_abbrev=False, add_help=True)
    parser.add_argument("--version", action="store_true")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    inspect = commands.add_parser(
        "inspect", allow_abbrev=False, help="inventory one file; structural output only"
    )
    inspect.add_argument("input", metavar="INPUT")
    inspect.add_argument("--json", required=True, metavar="OUTPUT")
    inspect.add_argument("--replace", action="store_true")

    ingest = commands.add_parser("ingest", allow_abbrev=False, help="ingest one file into a store")
    ingest.add_argument("input", metavar="INPUT")
    ingest.add_argument("--store", required=True)
    ingest.add_argument("--dataset", required=True, metavar="NAME")
    ingest.add_argument("--synthetic", required=True, choices=("true", "false"))
    ingest.add_argument("--product-key", metavar="KEY")
    ingest.add_argument("--as-of", metavar="INSTANT")
    ingest.add_argument("--as-of-basis", metavar="TEXT")

    preview = commands.add_parser(
        "preview", allow_abbrev=False, help="an 8-bit, segment-only preview of one image"
    )
    preview.add_argument("record_id", metavar="RECORD_ID")
    preview.add_argument("--image", required=True, type=_image_index, metavar="N")
    preview.add_argument("--store", required=True)
    preview.add_argument("--output", required=True, metavar="OUTPUT.png")
    preview.add_argument("--bands", metavar="B[,B,B]")
    preview.add_argument("--replace", action="store_true")

    replay = commands.add_parser(
        "replay", allow_abbrev=False, help="relay the stored original octets unchanged"
    )
    replay.add_argument("record_id", metavar="RECORD_ID")
    replay.add_argument("--store", required=True)
    replay.add_argument("--output", required=True, metavar="OUTPUT.ntf")
    replay.add_argument("--replace", action="store_true")

    export = commands.add_parser(
        "export-nc",
        allow_abbrev=False,
        help="experimental: write one new NC8 image from an explicit recipe",
        description=(
            "Experimental: the SC4545-WRITE-NC8-1 writer writes one new single-image NC8 file "
            "from an explicit recipe. Its output is experimental engineering output and is not "
            "independently qualified."
        ),
    )
    export.add_argument("recipe", metavar="RECIPE.json")
    export.add_argument("--store", required=True)
    export.add_argument("--output", required=True, metavar="OUTPUT.ntf")
    export.add_argument("--replace", action="store_true")
    return parser


# --------------------------------------------------------------------------- argument checks


def _local_path(option: str, value: str) -> str:
    if not value or _URI.match(value) or value.startswith("/vsi"):
        raise _usage(option, "names a URI")
    return value


def _output(option: str, value: str, replace: bool) -> str:
    path = os.path.abspath(value)
    try:
        directory = os.stat(os.path.dirname(path))
    except (OSError, ValueError):
        raise _usage(option, "names no directory") from None
    if not stat.S_ISDIR(directory.st_mode):
        raise _usage(option, "names no directory")
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return path
    except (OSError, ValueError):
        raise _usage(option, "cannot be checked") from None
    if not replace:
        raise _usage(option, "exists; it is replaced only with --replace")
    if not (stat.S_ISREG(status.st_mode) or stat.S_ISLNK(status.st_mode)):
        raise _usage(option, "is not a file")
    return path


def _record_id(value: str) -> str:
    from synapse_imagery.ingest import is_canonical_uuid

    if not is_canonical_uuid(value):
        raise HostError(
            "E_FIELD",
            "storage",
            None,
            "/record_id",
            "no committed record with this id for this principal",
        )
    return value


def _bands(value: str | None) -> tuple[int, ...] | None:
    from synapse_imagery.preview import RenderingSpec

    if value is None:
        return None
    if not _BANDS.fullmatch(value):
        raise _usage("--bands", "is one band or three distinct bands")
    bands = tuple(int(part) for part in value.split(","))
    try:
        RenderingSpec(bands=bands)
    except ValueError:
        raise _usage("--bands", "is one band or three distinct bands") from None
    return bands


def _context(args) -> tuple[str | None, object]:
    from synapse_cdm.adapters.geojson import AsOf
    from synapse_cdm.adapters.stanag4545 import Stanag4545Context

    try:
        Stanag4545Context(dataset_namespace=args.dataset)
    except (TypeError, ValueError):
        raise _usage("--dataset", "is not a dataset name the adapter accepts") from None
    if args.product_key is not None:
        try:
            Stanag4545Context(dataset_namespace=args.dataset, product_key=args.product_key)
        except (TypeError, ValueError):
            raise _usage("--product-key", "is not a product key the adapter accepts") from None
    if (args.as_of is None) != (args.as_of_basis is None):
        raise _usage("--as-of", "and --as-of-basis are given together")
    as_of = None
    if args.as_of is not None:
        try:
            as_of = AsOf(instant=args.as_of, basis=args.as_of_basis)
            Stanag4545Context(dataset_namespace=args.dataset, as_of=as_of)
        except (TypeError, ValueError):
            raise _usage("--as-of", "is not an instant and basis the adapter accepts") from None
    return args.product_key, as_of


# --------------------------------------------------------------------------- one run


class _Run:
    def __init__(self, fault: Callable[[str], None] | None) -> None:
        self.fault = fault
        self.pool = None
        self.lines: list[str] = []
        self.command = "sc-imagery"

    # The pieces every command shares.

    def worker(self):
        from synapse_imagery.worker import WorkerPool

        if self.pool is None:
            self.pool = WorkerPool()
        return self.pool

    def service(self, store_path: str):
        from synapse_imagery.assets import LocalAssetStore
        from synapse_imagery.ingest import IngestService
        from synapse_imagery.policy import DefaultPolicy

        try:
            store = LocalAssetStore(store_path)
        except ValueError:
            raise _usage("--store", "is not a store") from None
        store.recover()
        return IngestService(store, policy=DefaultPolicy(), worker=self.worker(), _fault=self.fault)

    def principal(self):
        from synapse_imagery.policy import Principal

        return Principal("local", "local-operator")

    def emit(self, document: dict) -> None:
        sys.stdout.write(canonical.serialise(document))
        sys.stdout.flush()

    def close(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(kill=True)

    def stderr(self, outcome: list[str]) -> None:
        lines = []
        report = None if self.pool is None else self.pool.last_report
        if report is not None and report.get("memory_enforcement") == "not_enforced":
            lines.append("sc-imagery: WORKER_MEMORY_NOT_ENFORCED")
        for line in lines + outcome:
            sys.stderr.write(line + "\n")
        sys.stderr.flush()

    # The commands.

    def execute(self, argv: list[str]) -> int:
        try:
            args = build_parser().parse_args(argv)
        except _Usage as usage:
            self.lines = list(usage.lines)
            return 2
        except SystemExit as done:
            # --help: argparse printed it.
            return done.code if type(done.code) is int else 2
        if args.version:
            if args.command is not None or argv != ["--version"]:
                self.lines = ["sc-imagery: usage error", USAGE]
                return 2
            sys.stdout.write(f"sc-imagery {__version__}\n")
            return 0
        if args.command is None:
            self.lines = ["sc-imagery: usage error", USAGE]
            return 2
        self.command = args.command
        try:
            return getattr(self, "_" + args.command.replace("-", "_"))(args)
        except _Usage as usage:
            self.lines = list(usage.lines)
            return 2
        except FileExistsError:
            # An output that appeared after the check: still never overwritten.
            self.lines = [
                "sc-imagery: usage error: --output exists; it is replaced only with --replace"
            ]
            return 2
        except (HostError, NsifError) as error:
            self.lines = [f"sc-imagery: {self.command} {error.code}"]
            return exit_status(error.code, error.stage, error.path)
        except OSError:
            # The operating system refused something no coded outcome covers (an output that
            # cannot be written): an I/O failure.
            self.lines = [f"sc-imagery: {self.command} E_IO"]
            return 7
        except Exception:
            # An unexpected exception is a defect of this package: reported as one, never as
            # a result.
            self.lines = [f"sc-imagery: {self.command} E_INTERNAL"]
            return 7

    def _inspect(self, args) -> int:
        from synapse_imagery.ingest import _deliver, inspect_source
        from synapse_imagery.policy import DefaultPolicy

        source = _local_path("INPUT", args.input)
        target = None
        if args.json != "-":
            target = _output("--json", _local_path("--json", args.json), args.replace)
        document = inspect_source(source, worker=self.worker(), policy=DefaultPolicy())
        text = canonical.serialise(document)
        if target is None:
            sys.stdout.write(text)
            sys.stdout.flush()
        else:
            _deliver(target, text.encode("utf-8"), replace=args.replace)
        if document["valid"]:
            self.lines = ["sc-imagery: inspect ok"]
            return 0
        (entry,) = document["diagnostics"]
        self.lines = [f"sc-imagery: inspect {entry['code']}"]
        return exit_status(entry["code"], entry["stage"], entry["path"])

    def _ingest(self, args) -> int:
        source = _local_path("INPUT", args.input)
        store = _local_path("--store", args.store)
        product_key, as_of = _context(args)
        service = self.service(store)
        result = service.ingest(
            source,
            principal=self.principal(),
            dataset_namespace=args.dataset,
            synthetic=args.synthetic == "true",
            product_key=product_key,
            as_of=as_of,
        )
        self.emit(result)
        state = result["state"]
        self.lines = [f"sc-imagery: ingest {state} {result['record_id']}"]
        if state == "committed":
            return 0
        if state == "policy_blocked":
            return 5
        (entry,) = [entry for entry in result["diagnostics"] if entry["code"].startswith("E_")]
        return exit_status(entry["code"], entry["stage"], entry["path"])

    def _preview(self, args) -> int:
        store = _local_path("--store", args.store)
        output = _output("--output", _local_path("--output", args.output), args.replace)
        bands = _bands(args.bands)
        record_id = _record_id(args.record_id)
        receipt = self.service(store).preview(
            record_id,
            args.image,
            output,
            principal=self.principal(),
            bands=bands,
            replace=args.replace,
        )
        self.emit(receipt)
        self.lines = [f"sc-imagery: preview ok {receipt['derivative_id']}"]
        return 0

    def _replay(self, args) -> int:
        store = _local_path("--store", args.store)
        output = _output("--output", _local_path("--output", args.output), args.replace)
        record_id = _record_id(args.record_id)
        receipt = self.service(store).replay_original(
            record_id, output, principal=self.principal(), replace=args.replace
        )
        self.emit(receipt)
        self.lines = [f"sc-imagery: replay ok {record_id}"]
        return 0

    def _export_nc(self, args) -> int:
        recipe = _local_path("RECIPE.json", args.recipe)
        store = _local_path("--store", args.store)
        output = _output("--output", _local_path("--output", args.output), args.replace)
        receipt = self.service(store).export_nc(
            recipe, output, principal=self.principal(), replace=args.replace
        )
        self.emit(receipt)
        self.lines = [f"sc-imagery: export-nc ok {receipt['export_id']}"]
        return 0


def main(argv: Sequence[str] | None = None, *, _fault: Callable[[str], None] | None = None) -> int:
    """Run one command; returns its exit status. `_fault` is the interrupt test's seam and is
    reachable only from Python."""
    from synapse_imagery.ingest import _remove_live_parts

    # The package logs fixed text for an operator's handler; the command itself prints only its
    # stderr lines, so nothing reaches the interpreter's last-resort handler.
    logger = logging.getLogger("synapse_imagery")
    if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        logger.addHandler(logging.NullHandler())
    run = _Run(_fault)
    try:
        try:
            status = run.execute(list(sys.argv[1:] if argv is None else argv))
        finally:
            run.close()
    except KeyboardInterrupt:
        # Live children are killed by the close above; what an unwinding stack left of a
        # temporary output goes now. A job's staging was removed by its own unwinding, and a
        # committed record stays for the next recovery to publish.
        _remove_live_parts()
        run.stderr(["sc-imagery: interrupted"])
        return INTERRUPTED
    run.stderr(run.lines)
    return status
