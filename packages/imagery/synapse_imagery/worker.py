"""The isolated worker: every untrusted octet the host parses is parsed in a fresh child process.

THE PROTOCOL
------------
A job is one child, started with an argument list (never a shell), a scrubbed three-variable
environment, a private empty working directory and exactly the job's source descriptor
inherited. The parent writes one JSON request line on the child's stdin and reads one JSON answer
line on its stdout, followed for a window by exactly the stated number of sample octets. The
child is never given a path, a URI or a dimension: it reads the source through the descriptor,
verifies its length and SHA-256, parses it itself and applies the adapter's own window checks, so
a forged request cannot make it decode an unlimited raster. The parent re-checks every answer.

LIMITS
------
The child's first act is the 512 MiB address-space cap; only the standard library has been
imported at that point, so the adapter and pydantic load under it. Linux enforces the cap; macOS
refuses it and the child says so in every answer (`memory_enforcement: not_enforced`). Parsing
jobs have a 5 s and pixel jobs a 30 s wall-clock deadline, enforced by the parent with a kill and
one supervised retry; two jobs run at a time with 32 waiting, and a full queue answers E_BUSY at
once. After its imports the child installs an audit hook that refuses network, process creation,
library loading, every write and every read outside the interpreter's and the adapter's own
directories, so no sidecar, URL or configuration file is ever reached.

THE CODEC MATRIX
----------------
Every compressed and masked cell is disabled: only the native NC cell decodes, and every other
image answers the adapter's E_CODEC or E_PROFILE. No codec library is imported anywhere.

THE PREVIEW
-----------
`make_preview` decodes the whole native image through the same window function, draws the 8-bit
derivative with `synapse_imagery.preview` and writes the PNG only through the output descriptor
the parent handed over, in one piece once it is complete; the parent truncates that descriptor
after every failed or killed job, so no partial thumbnail survives, and checks the answer's size,
digest and provenance against what it asked for and what it knows of the image.

This module imports only the standard library at module level; the adapter, the policy types and
the rest of the package are imported inside the functions that need them, after the memory cap.
"""

from __future__ import annotations

import json
import logging
import os
import re
import selectors
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

_LOG = logging.getLogger("synapse_imagery")

PROTOCOL = "sc-imagery-worker/1"
MEMORY_EXIT_STATUS = 86
#: The child's whole environment. Nothing of the parent's is inherited (no GDAL, PROJ, PYTHON or
#: proxy variable); macOS adds `__CF_USER_TEXT_ENCODING` to every child and nothing here can stop it.
CHILD_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}
_CHILD_CODE = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from synapse_imagery.worker import _child_main; _child_main()"
)
#: The directory that holds the `synapse_imagery` package, handed to the child as `argv[1]`.
_PACKAGE_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REQUEST_BYTES = 65_536
_SHA256 = re.compile(r"[0-9a-f]{64}")

#: The stage a worker outcome is reported under, per operation.
_STAGE = {
    "inventory": "input",
    "translate": "cdm",
    "inspect_codec": "pixels",
    "decode_window": "pixels",
    "make_preview": "pixels",
}
_OP_FIELDS = {
    "inventory": ("registry",),
    "translate": ("context", "synthetic"),
    "inspect_codec": ("image_index",),
    "decode_window": ("image_index", "window", "bands", "ticket"),
    "make_preview": ("image_index", "rendering", "ticket", "output_fd"),
}
_COMMON_FIELDS = ("protocol", "op", "fd", "expected_sha256", "byte_count")
_PARSE_OPS = ("inventory", "translate", "inspect_codec")


# --------------------------------------------------------------------------- records


def _int(value: object) -> bool:
    return type(value) is int


@dataclass(frozen=True, slots=True)
class Window:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if not all(_int(value) for value in (self.x, self.y, self.width, self.height)):
            raise TypeError("window coordinates must be int")


@dataclass(frozen=True, slots=True)
class WorkerWindow:
    """A decoded window and its validity bitmap. `validity` is None for every image this release
    decodes (NC has no mask, so every returned sample is a source sample); a masked cell a later
    release enables answers one bit per returned sample, band-major, most significant bit first."""

    window: object
    validity: bytes | None


@dataclass(frozen=True, slots=True)
class CodecCapability:
    image_index: int
    ic: str
    pvtype: str
    nbpp: int
    abpp: int
    imode: str
    masked: bool
    cell: str
    enabled: bool
    path: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class Derivative:
    width: int
    height: int
    channels: int
    sha256: str
    byte_count: int
    provenance: dict


@dataclass(frozen=True, slots=True)
class CodecCell:
    ic: str
    family: str
    enabled: bool
    reason: str


_DISABLED = "no qualified backend in this release (L-03)"
CODEC_MATRIX = tuple(
    CodecCell(ic, family, False, _DISABLED)
    for ic, family in (
        ("NM", "candidate"),
        ("C3", "candidate"),
        ("M3", "candidate"),
        ("C8", "candidate"),
        ("M8", "candidate"),
        ("C1", "preservation_only"),
        ("M1", "preservation_only"),
        ("C4", "preservation_only"),
        ("M4", "preservation_only"),
        ("C5", "preservation_only"),
        ("M5", "preservation_only"),
    )
)
ENABLED_CODEC_CELLS: tuple[CodecCell, ...] = tuple(cell for cell in CODEC_MATRIX if cell.enabled)


@dataclass(frozen=True, slots=True)
class WorkerLimits:
    """The host-only limits. Every number may be lowered (for tests) and never raised."""

    workers: int = 2
    queue: int = 32
    parse_deadline: float = 5.0
    codec_deadline: float = 30.0
    memory_bytes: int = 536_870_912
    answer_bytes: int = 68_157_440
    require_memory_enforcement: bool = False

    def __post_init__(self) -> None:
        defaults = {
            "workers": (2, int),
            "queue": (32, int),
            "parse_deadline": (5.0, (int, float)),
            "codec_deadline": (30.0, (int, float)),
            "memory_bytes": (536_870_912, int),
            "answer_bytes": (68_157_440, int),
        }
        for name, (ceiling, kinds) in defaults.items():
            value = getattr(self, name)
            if type(value) is bool or not isinstance(value, kinds):
                raise TypeError(f"{name} must be a number")
            if not 0 < value <= ceiling:
                raise ValueError(f"{name} must be above 0 and at most {ceiling}")
        if type(self.require_memory_enforcement) is not bool:
            raise TypeError("require_memory_enforcement must be a bool")


# --------------------------------------------------------------------------- the protocol


class Worker(Protocol):
    isolation: str
    last_report: dict | None

    def inventory(
        self, asset_fd: int, *, expected_sha256: str, byte_count: int, registry
    ) -> dict: ...

    def translate(
        self, asset_fd: int, *, expected_sha256: str, byte_count: int, context, synthetic: bool
    ) -> list[dict]: ...

    def inspect_codec(
        self, asset_fd: int, image_index: int, *, expected_sha256: str, byte_count: int
    ) -> CodecCapability: ...

    def decode_window(
        self,
        asset_fd: int,
        image_index: int,
        window: Window,
        bands: tuple[int, ...],
        policy_ticket,
        *,
        expected_sha256: str,
        byte_count: int,
    ) -> WorkerWindow: ...

    def make_preview(
        self,
        asset_fd: int,
        image_index: int,
        rendering_spec,
        policy_ticket,
        *,
        expected_sha256: str,
        byte_count: int,
        output_fd: int,
    ) -> Derivative: ...


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _request(op: str, fd: int, expected_sha256: str, byte_count: int, **fields) -> dict:
    if not _int(fd) or fd < 0:
        raise TypeError("asset_fd must be a descriptor number")
    if type(expected_sha256) is not str or not _SHA256.fullmatch(expected_sha256):
        raise ValueError("expected_sha256 must be 64 lowercase hexadecimal digits")
    if not _int(byte_count) or byte_count < 0:
        raise TypeError("byte_count must be an int >= 0")
    return {
        "protocol": PROTOCOL,
        "op": op,
        "fd": fd,
        "expected_sha256": expected_sha256,
        "byte_count": byte_count,
        **fields,
    }


def _context_wire(context) -> dict:
    from synapse_cdm.adapters.stanag4545 import Stanag4545Context

    if type(context) is not Stanag4545Context:
        raise TypeError("context must be a Stanag4545Context")
    as_of = context.as_of
    return {
        "dataset_namespace": context.dataset_namespace,
        "product_key": context.product_key,
        "as_of": None
        if as_of is None
        else {"instant": as_of.instant.isoformat(), "basis": as_of.basis},
        "asset_ref": context.asset_ref,
        "verified_sha256": context.verified_sha256,
    }


class _WorkerBase:
    """The four operations, shared by the isolated pool and the in-process fake: both build the
    same request, and both re-check the answer the same way."""

    isolation = "none"

    def __init__(self) -> None:
        self._report_lock = threading.Lock()
        self.last_report: dict | None = None

    # A subclass supplies `_run(op, request, pass_fds) -> (answer, payload)`: a child process
    # for the pool, a direct call for the in-process fake.

    def _answer(self, op: str, request: dict, pass_fds: tuple[int, ...]) -> tuple[dict, bytes]:
        answer, payload = self._run(op, request, pass_fds)
        report = _check_answer(answer, _STAGE[op])
        with self._report_lock:
            self.last_report = report
        if answer["ok"] is not True:
            _raise_refusal(answer, _STAGE[op])
        return answer, payload

    def inventory(self, asset_fd, *, expected_sha256, byte_count, registry) -> dict:
        from synapse_imagery.policy import ExtensionRegistry, SecurityDescriptor

        if not isinstance(registry, ExtensionRegistry):
            raise TypeError("registry must be an ExtensionRegistry")
        request = _request(
            "inventory", asset_fd, expected_sha256, byte_count, registry=registry.wire()
        )
        answer, _ = self._answer("inventory", request, (asset_fd,))
        inventory = answer.get("inventory")
        if set(answer) != {"ok", "worker", "inventory"} or not _inventory_shape(inventory):
            raise _internal("inventory", "the worker's inventory answer is malformed")
        SecurityDescriptor.from_json(inventory["descriptor"])
        return inventory

    def translate(self, asset_fd, *, expected_sha256, byte_count, context, synthetic) -> list:
        if type(synthetic) is not bool:
            raise TypeError("synthetic must be a bool")
        request = _request(
            "translate",
            asset_fd,
            expected_sha256,
            byte_count,
            context=_context_wire(context),
            synthetic=synthetic,
        )
        answer, _ = self._answer("translate", request, (asset_fd,))
        objects = answer.get("objects")
        if (
            set(answer) != {"ok", "worker", "objects"}
            or type(objects) is not list
            or not objects
            or not all(type(item) is dict for item in objects)
        ):
            raise _internal("translate", "the worker's translation answer is malformed")
        return objects

    def inspect_codec(self, asset_fd, image_index, *, expected_sha256, byte_count):
        if not _int(image_index):
            raise TypeError("image_index must be an int")
        request = _request(
            "inspect_codec", asset_fd, expected_sha256, byte_count, image_index=image_index
        )
        answer, _ = self._answer("inspect_codec", request, (asset_fd,))
        fields = answer.get("capability")
        try:
            if set(answer) != {"ok", "worker", "capability"} or type(fields) is not dict:
                raise TypeError
            capability = CodecCapability(**fields)
        except TypeError:
            raise _internal(
                "inspect_codec", "the worker's capability answer is malformed"
            ) from None
        if capability.image_index != image_index:
            raise _internal("inspect_codec", "the worker answered for another image")
        return capability

    def decode_window(
        self, asset_fd, image_index, window, bands, policy_ticket, *, expected_sha256, byte_count
    ) -> WorkerWindow:
        from synapse_imagery.policy import Artefact, PolicyTicket
        from synapse_imagery.result import HostError

        if not isinstance(window, Window):
            raise TypeError("window must be a Window")
        if not _int(image_index):
            raise TypeError("image_index must be an int")
        if type(bands) is not tuple or not all(_int(band) for band in bands):
            raise HostError(
                "E_FIELD", "pixels", None, "/window/bands", "bands must be a tuple of int"
            )
        if not isinstance(policy_ticket, PolicyTicket):
            raise TypeError("policy_ticket must be a PolicyTicket")
        # Checked before the child starts and again before the samples are returned.
        policy_ticket.verify(
            artefact=Artefact.PIXELS, asset_id=policy_ticket.asset_id, tenant=policy_ticket.tenant
        )
        request = _request(
            "decode_window",
            asset_fd,
            expected_sha256,
            byte_count,
            image_index=image_index,
            window=[window.x, window.y, window.width, window.height],
            bands=list(bands),
            ticket={"artefact": "pixels", "asset_id": policy_ticket.asset_id},
        )
        answer, payload = self._answer("decode_window", request, (asset_fd,))
        result = WorkerWindow(_sample_window(answer, payload, request), None)
        policy_ticket.verify(
            artefact=Artefact.PIXELS, asset_id=policy_ticket.asset_id, tenant=policy_ticket.tenant
        )
        return result

    def make_preview(
        self,
        asset_fd,
        image_index,
        rendering_spec,
        policy_ticket,
        *,
        expected_sha256,
        byte_count,
        output_fd,
    ) -> Derivative:
        from synapse_imagery.policy import Artefact, PolicyTicket
        from synapse_imagery.preview import RenderingSpec

        if not _int(image_index):
            raise TypeError("image_index must be an int")
        if not isinstance(rendering_spec, RenderingSpec):
            raise TypeError("rendering_spec must be a RenderingSpec")
        if not isinstance(policy_ticket, PolicyTicket):
            raise TypeError("policy_ticket must be a PolicyTicket")
        if not _int(output_fd) or output_fd < 0:
            raise TypeError("output_fd must be a descriptor number")
        policy_ticket.verify(
            artefact=Artefact.THUMBNAIL,
            asset_id=policy_ticket.asset_id,
            tenant=policy_ticket.tenant,
        )
        bands = None if rendering_spec.bands is None else list(rendering_spec.bands)
        request = _request(
            "make_preview",
            asset_fd,
            expected_sha256,
            byte_count,
            image_index=image_index,
            rendering={"max_size": rendering_spec.max_size, "bands": bands},
            ticket={"artefact": "thumbnail", "asset_id": policy_ticket.asset_id},
            output_fd=output_fd,
        )
        try:
            answer, _ = self._answer("make_preview", request, (asset_fd, output_fd))
            derivative = _derivative(answer, request, rendering_spec)
        except BaseException:
            # A refused, malformed or interrupted job leaves no octet in the output.
            _discard_output(request)
            raise
        policy_ticket.verify(
            artefact=Artefact.THUMBNAIL,
            asset_id=policy_ticket.asset_id,
            tenant=policy_ticket.tenant,
        )
        return derivative


def _internal(op: str, message: str):
    from synapse_imagery.result import HostError

    return HostError("E_INTERNAL", _STAGE[op], None, "/worker", message)


_REPORT_KEYS = (
    "isolation",
    "memory_limit_bytes",
    "memory_enforcement",
    "cpu_affinity",
    "deadline_enforcement",
    "platform",
)


def _check_answer(answer: object, stage: str) -> dict:
    from synapse_imagery.result import HostError

    if (
        type(answer) is not dict
        or type(answer.get("ok")) is not bool
        or type(answer.get("worker")) is not dict
        or tuple(answer["worker"]) != _REPORT_KEYS
    ):
        raise HostError("E_INTERNAL", stage, None, "/worker", "the worker's answer is malformed")
    return dict(answer["worker"])


def _raise_refusal(answer: dict, stage: str):
    """An error answer becomes the adapter's NsifError for a refusal of the octets and a HostError
    for a host outcome; a refusal of the host's own request is a host defect."""
    from synapse_cdm.adapters.nsif_codec import NsifError

    from synapse_imagery.result import CORE_CODES, HostError

    keys = {"ok", "worker", "code", "stage", "offset", "path", "message"}
    if set(answer) != keys:
        raise HostError("E_INTERNAL", stage, None, "/worker", "the worker's refusal is malformed")
    code, path = answer["code"], answer["path"]
    if type(path) is str and path.startswith("/request"):
        raise HostError(
            "E_INTERNAL", stage, None, "/worker", "the worker refused the host's request"
        )
    if type(path) is str and path.startswith("/worker"):
        # Only the host names a worker outcome; a child that claims one is defective or forged,
        # and its answer must not become a refusal of the octets.
        raise HostError("E_INTERNAL", stage, None, "/worker", "the worker's refusal is malformed")
    try:
        if code in CORE_CODES:
            error = NsifError(code, answer["stage"], answer["offset"], path, answer["message"])
        else:
            error = HostError(code, answer["stage"], answer["offset"], path, answer["message"])
    except TypeError:
        raise HostError(
            "E_INTERNAL", stage, None, "/worker", "the worker's refusal is malformed"
        ) from None
    raise error


_DERIVATIVE_KEYS = {"width", "height", "channels", "sha256", "byte_count", "provenance"}
_PROVENANCE_KEYS = [
    "algorithm",
    "parameters",
    "selection",
    "bands",
    "image_index",
    "source_window",
    "size",
    "composition",
    "diagnostics",
    "parent_id",
    "parent_sha256",
    "software",
    "worker",
]


def _derivative(answer: dict, request: dict, spec) -> Derivative:
    """The parent's check of a preview answer: every field against the request it sent and the
    rules the derivative must follow, before anything of it is trusted."""
    from synapse_cdm.adapters.nsif_codec import Diagnostic

    from synapse_imagery import preview

    fields = answer.get("derivative")
    try:
        if set(answer) != {"ok", "worker", "derivative"} or type(fields) is not dict:
            raise TypeError
        if set(fields) != _DERIVATIVE_KEYS:
            raise TypeError
        width, height, channels = fields["width"], fields["height"], fields["channels"]
        provenance = fields["provenance"]
        if not all(_int(value) for value in (width, height, channels, fields["byte_count"])):
            raise TypeError
        if not (1 <= width <= spec.max_size and 1 <= height <= spec.max_size):
            raise TypeError
        if type(fields["sha256"]) is not str or not _SHA256.fullmatch(fields["sha256"]):
            raise TypeError
        if type(provenance) is not dict:
            raise TypeError
        keys = [key for key in provenance if key not in ("graphic_segments", "graphics_composed")]
        if keys != _PROVENANCE_KEYS:
            raise TypeError
        if ("graphic_segments" in provenance) != ("graphics_composed" in provenance):
            raise TypeError
        if "graphic_segments" in provenance and (
            not _int(provenance["graphic_segments"])
            or provenance["graphic_segments"] < 1
            or provenance["graphics_composed"] is not False
        ):
            raise TypeError
        algorithm, selection = provenance["algorithm"], provenance["selection"]
        bands = provenance["bands"]
        if spec.bands is not None:
            expected = (preview.ALGORITHM_LINEAR, "explicit", list(spec.bands))
            if (algorithm, selection, bands) != expected:
                raise TypeError
        elif selection == "lut":
            if (algorithm, bands) != (preview.ALGORITHM_LUT, [0]):
                raise TypeError
        elif selection != "automatic" or algorithm != preview.ALGORITHM_LINEAR:
            raise TypeError
        if type(bands) is not list or len(bands) not in (1, 3):
            raise TypeError
        if channels != (3 if selection == "lut" else len(bands)):
            raise TypeError
        if (
            provenance["parameters"] != preview.parameters(algorithm, spec.max_size)
            or provenance["image_index"] != request["image_index"]
            or provenance["size"] != [width, height]
            or provenance["composition"] != "segment_only"
            or provenance["parent_id"] != request["ticket"]["asset_id"]
            or provenance["parent_sha256"] != request["expected_sha256"]
            or provenance["software"] != preview.software()
            or provenance["worker"] != answer["worker"]
        ):
            raise TypeError
        window = provenance["source_window"]
        if type(window) is not list or len(window) != 4 or window[:2] != [0, 0]:
            raise TypeError
        found = provenance["diagnostics"]
        if type(found) is not list:
            raise TypeError
        for entry in found:
            if type(entry) is not dict or entry.get("code") != preview.UNRESOLVED:
                raise TypeError
            Diagnostic(**entry)
        return Derivative(
            width, height, channels, fields["sha256"], fields["byte_count"], provenance
        )
    except (TypeError, KeyError):
        raise _internal("make_preview", "the worker's preview answer is malformed") from None


def _inventory_shape(inventory: object) -> bool:
    keys = [
        "format",
        "signature",
        "clevel",
        "file_size",
        "header_length",
        "file_date",
        "segments",
        "images",
        "extension_counts",
        "composition_status",
        "descriptor",
        "diagnostics",
    ]
    return (
        type(inventory) is dict
        and list(inventory) == keys
        and inventory["format"] == "sc-imagery-inventory/1"
        and type(inventory["images"]) is list
        and all(type(image) is dict for image in inventory["images"])
        and type(inventory["diagnostics"]) is list
        and type(inventory["descriptor"]) is str
    )


def _sample_window(answer: dict, payload: bytes, request: dict):
    from synapse_cdm.adapters.nsif_codec import Diagnostic, SampleWindow

    fields = answer.get("window")
    x, y, width, height = request["window"]
    try:
        if set(answer) != {"ok", "worker", "window", "payload_bytes"} or type(fields) is not dict:
            raise TypeError
        size = 2 if fields["dtype"] in ("uint16", "int16") else 1
        expected = width * height * len(request["bands"]) * size
        if (
            fields["dtype"] not in ("uint8", "uint16", "int8", "int16")
            or fields["kind"] != "interpreted"
            or [fields["image_index"], fields["x"], fields["y"], fields["width"], fields["height"]]
            != [request["image_index"], x, y, width, height]
            or fields["bands"] != request["bands"]
            or answer["payload_bytes"] != expected
            or len(payload) != expected
        ):
            raise TypeError
        return SampleWindow(
            fields["image_index"],
            x,
            y,
            width,
            height,
            tuple(fields["bands"]),
            fields["kind"],
            fields["dtype"],
            bytes(payload),
            fields["fill_bits_nonzero"],
            fields["fill_bits_sign_extended"],
            tuple(Diagnostic(**entry) for entry in fields["diagnostics"]),
        )
    except (TypeError, KeyError):
        raise _internal("decode_window", "the worker's window answer is malformed") from None


# --------------------------------------------------------------------------- the pool


class WorkerPool(_WorkerBase):
    """Runs every job in a fresh isolated child, at most `workers` at a time with `queue`
    waiting. Thread-safe; it starts no thread of its own (a job runs in the caller's thread)."""

    isolation = "subprocess"

    def __init__(
        self,
        limits: WorkerLimits = WorkerLimits(),
        *,
        _child_command: Sequence[str] | None = None,
    ) -> None:
        super().__init__()
        if not isinstance(limits, WorkerLimits):
            raise TypeError("limits must be WorkerLimits")
        if limits.require_memory_enforcement:
            from synapse_cdm import suite

            enforced, reason = suite.resource_limit_support()["memory_bytes"]
            if not enforced:
                raise ValueError(reason)
        command = [sys.executable, "-I", "-B", "-c", _CHILD_CODE]
        if _child_command is not None:
            if isinstance(_child_command, (str, bytes)) or not all(
                type(part) is str for part in _child_command
            ):
                raise TypeError("_child_command must be an argument list")
            command = list(_child_command)
        self._command = command
        self._limits = limits
        self._cond = threading.Condition()
        self._running = 0
        self._waiting: deque = deque()
        self._live: set = set()
        self._closed = False

    @property
    def limits(self) -> WorkerLimits:
        return self._limits

    def counts(self) -> tuple[int, int]:
        """The running and the waiting job counts."""
        with self._cond:
            return self._running, len(self._waiting)

    def shutdown(self, kill: bool = False) -> None:
        """Refuse new jobs; kill the live children, or wait for them to finish."""
        with self._cond:
            self._closed = True
            if kill:
                for process in list(self._live):
                    _kill(process)
            while self._running or self._waiting:
                self._cond.wait()

    def _admit(self, stage: str) -> None:
        from synapse_imagery.result import HostError

        with self._cond:
            if self._closed:
                raise HostError(
                    "E_INTERNAL", stage, None, "/worker", "the worker pool is shut down"
                )
            if self._running < self._limits.workers and not self._waiting:
                self._running += 1
                return
            if len(self._waiting) >= self._limits.queue:
                raise HostError("E_BUSY", stage, None, "/worker", "the worker queue is full")
            token = object()
            self._waiting.append(token)
            while self._waiting[0] is not token or self._running >= self._limits.workers:
                self._cond.wait()
            self._waiting.popleft()
            self._running += 1
            self._cond.notify_all()

    def _release(self) -> None:
        with self._cond:
            self._running -= 1
            self._cond.notify_all()

    def _run(self, op: str, request: dict, pass_fds: tuple[int, ...]) -> tuple[dict, bytes]:
        deadline = self._limits.parse_deadline if op in _PARSE_OPS else self._limits.codec_deadline
        return self._exchange(request, pass_fds=pass_fds, stage=_STAGE[op], deadline=deadline)

    def _exchange(
        self, request: dict, *, pass_fds: tuple[int, ...], stage: str, deadline: float
    ) -> tuple[dict, bytes]:
        """One job: admission, a child, and the one supervised retry after a timeout. Returns the
        answer as a JSON object and the payload that followed it."""
        from synapse_imagery.result import HostError

        line = (_compact(request) + "\n").encode("ascii")
        self._admit(stage)
        try:
            for _attempt in (1, 2):
                outcome, exit_code, out = self._once(line, pass_fds, deadline)
                if outcome != "timeout":
                    break
                # Whatever a killed child wrote is deleted; the one supervised retry starts clean.
                _discard_output(request)
            else:
                _LOG.warning("worker job killed at its deadline twice: stage %s", stage)
                raise HostError(
                    "E_TIMEOUT", stage, None, "/worker", "the worker was killed at its deadline"
                )
        finally:
            self._release()
        error = None
        if outcome == "too_large":
            error = HostError(
                "E_LIMIT", stage, None, "/worker", "the worker's answer exceeds its bound"
            )
        elif exit_code == MEMORY_EXIT_STATUS:
            error = HostError("E_LIMIT", stage, None, "/worker", "worker memory cap reached")
        elif exit_code != 0:
            _LOG.warning("worker child ended with status %s", exit_code)
            error = HostError(
                "E_INTERNAL", stage, None, "/worker", "the worker ended without an answer"
            )
        answer = payload = None
        if error is None:
            end = out.find(b"\n")
            try:
                answer = json.loads(out[:end]) if end >= 0 else None
            except ValueError:
                answer = None
            payload = out[end + 1 :]
            stated = answer.get("payload_bytes", 0) if type(answer) is dict else 0
            if type(answer) is not dict or not _int(stated) or len(payload) != stated:
                error = HostError(
                    "E_INTERNAL", stage, None, "/worker", "the worker's answer is malformed"
                )
        if error is not None:
            _discard_output(request)
            raise error
        return answer, payload

    def _once(self, line: bytes, pass_fds: tuple[int, ...], deadline: float):
        """One child, read under the deadline and the answer bound: (outcome, status, stdout)."""
        directory = tempfile.mkdtemp(prefix="sc-imagery-job-")
        try:
            process = subprocess.Popen(
                [*self._command, _PACKAGE_PARENT, str(self._limits.memory_bytes)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=pass_fds,
                env=dict(CHILD_ENV),
                cwd=directory,
            )
            with self._cond:
                self._live.add(process)
            try:
                return self._converse(process, line, time.monotonic() + deadline)
            finally:
                with self._cond:
                    self._live.discard(process)
                _kill(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    try:
                        stream.close()
                    except OSError:
                        pass
        finally:
            try:
                os.rmdir(directory)
            except OSError:
                # Not empty means the child wrote despite its hook; never delete recursively.
                _LOG.warning("worker job directory left in place")

    def _converse(self, process, line: bytes, deadline: float):
        try:
            process.stdin.write(line)
            process.stdin.close()
        except OSError:
            pass
        out = bytearray()
        limit = self._limits.answer_bytes
        allowed = None
        searched = 0
        streams = {process.stdout.fileno(): "out", process.stderr.fileno(): "err"}
        with selectors.DefaultSelector() as selector:
            for descriptor in streams:
                selector.register(descriptor, selectors.EVENT_READ)
            while streams:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill(process)
                    return "timeout", None, bytes(out)
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65_536)
                    if not chunk:
                        selector.unregister(key.fd)
                        del streams[key.fd]
                        continue
                    if streams[key.fd] == "err":
                        # Drained so the child never blocks on it, and dropped unread: stderr
                        # is never logged or copied into a result.
                        continue
                    out += chunk
                    if allowed is None:
                        end = out.find(b"\n", searched)
                        if end < 0:
                            searched = len(out)
                            if len(out) > limit:
                                _kill(process)
                                return "too_large", None, b""
                            continue
                        if end > limit:
                            _kill(process)
                            return "too_large", None, b""
                        allowed = end + 1 + _stated_payload(out[:end])
                    if len(out) > allowed:
                        _kill(process)
                        return "too_large", None, b""
        try:
            exit_code = process.wait(max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _kill(process)
            return "timeout", None, bytes(out)
        return "exited", exit_code, bytes(out)


def _discard_output(request: dict) -> None:
    if "output_fd" in request:
        os.ftruncate(request["output_fd"], 0)
        os.lseek(request["output_fd"], 0, os.SEEK_SET)


def _stated_payload(header: bytes) -> int:
    try:
        answer = json.loads(header)
    except ValueError:
        return 0
    stated = answer.get("payload_bytes", 0) if type(answer) is dict else 0
    return stated if _int(stated) and stated >= 0 else 0


def _kill(process) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    process.wait()


# --------------------------------------------------------------------------- the child


def _apply_memory_cap(memory_bytes: int) -> str:
    """Set RLIMIT_AS; report what the kernel answered rather than what was asked."""
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (ValueError, OSError):
        return "not_enforced"
    return "rlimit_as"


def _limit_cpus() -> str:
    if not hasattr(os, "sched_setaffinity"):
        return "not_enforced"
    try:
        os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:2]))
    except OSError:
        return "not_enforced"
    return "two_cpus"


def _run_guarded(fn: Callable[[], int]) -> int:
    """Run `fn`; a MemoryError anywhere in it is the memory status, with nothing more written."""
    try:
        return fn()
    except MemoryError:
        return MEMORY_EXIT_STATUS


_REFUSED_EVENTS = frozenset(
    (
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
        "pty.spawn",
        "ctypes.dlopen",
        "urllib.Request",
        "webbrowser.open",
    )
)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _install_hook() -> None:
    import synapse_cdm

    roots = [entry for entry in sys.path if entry]
    roots += [sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix]
    roots.append(os.path.dirname(os.path.abspath(synapse_cdm.__file__)))
    allowed = tuple(sorted({os.path.realpath(root) for root in roots}))
    exact = "/dev/null"

    def inside(path: str) -> bool:
        if path == exact:
            return True
        real = os.path.realpath(path)
        return any(real == root or real.startswith(root.rstrip("/") + "/") for root in allowed)

    def hook(event: str, args: tuple) -> None:
        if event.startswith("socket.") or event.startswith("os.exec") or event in _REFUSED_EVENTS:
            raise PermissionError("refused in the worker")
        if event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                return
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & _WRITE_FLAGS
            )
            if writing or not inside(os.fsdecode(path)):
                raise PermissionError("refused in the worker")

    sys.addaudithook(hook)


def _child_setup(memory_bytes: int) -> dict:
    """The child's setup, in order: the memory cap, the CPU limit, every import a job can need,
    then the audit hook (its allowlist is taken after the imports, so the adapter's own directory
    is on it in an editable install). Returns the worker report every answer carries."""
    memory = _apply_memory_cap(memory_bytes)
    cpus = _limit_cpus()
    import base64  # noqa: F401
    import hashlib  # noqa: F401
    import struct  # noqa: F401

    import synapse_cdm.adapters.geojson  # noqa: F401
    import synapse_cdm.adapters.stanag4545  # noqa: F401
    import synapse_cdm.canonical  # noqa: F401
    import synapse_cdm.times  # noqa: F401

    import synapse_cdm.version  # noqa: F401
    import synapse_imagery._version  # noqa: F401
    import synapse_imagery.policy  # noqa: F401
    import synapse_imagery.preview  # noqa: F401
    import synapse_imagery.result  # noqa: F401

    _install_hook()
    return {
        "isolation": "subprocess",
        "memory_limit_bytes": memory_bytes,
        "memory_enforcement": memory,
        "cpu_affinity": cpus,
        "deadline_enforcement": "parent_kill",
        "platform": sys.platform,
    }


def _child_job(report: dict) -> int:
    from synapse_imagery.result import HostError

    line = sys.stdin.buffer.readline(_REQUEST_BYTES + 1)
    try:
        if len(line) > _REQUEST_BYTES:
            raise ValueError
        request = json.loads(line)
    except ValueError:
        error = HostError("E_FIELD", "input", None, "/request", "the request is not one JSON line")
        answer, payload = _refusal(error, report), b""
    else:
        answer, payload = _serve(request, report)
    sys.stdout.buffer.write((_compact(answer) + "\n").encode("ascii") + payload)
    sys.stdout.buffer.flush()
    return 0


def _child_main() -> None:
    arguments = sys.argv[2:3]
    memory_bytes = int(arguments[0]) if arguments and arguments[0].isdigit() else 0
    if memory_bytes <= 0:
        os._exit(2)
    status = _run_guarded(lambda: _child_job(_child_setup(memory_bytes)))
    os._exit(status)


# --------------------------------------------------------------------------- one job


def _refusal(error, report: dict) -> dict:
    message = getattr(error, "explanation", None)
    if message is None:
        message = error.message
    return {
        "ok": False,
        "worker": report,
        "code": error.code,
        "stage": error.stage,
        "offset": error.offset,
        "path": error.path,
        "message": message,
    }


def _serve(request: object, report: dict, limits=None) -> tuple[dict, bytes]:
    """One job in the process that runs it: the request's shape, the source's length and digest,
    the job's own parse, then the operation. Coded refusals become error answers; anything else
    escapes, because an unexpected exception is a defect and never an empty success."""
    from synapse_cdm.adapters import nsif_codec

    from synapse_imagery.result import HostError

    if limits is None:
        limits = nsif_codec.CORE1_LIMITS
    try:
        parsed = _check_request(request)
        parsed["report"] = report
        octets = _read_source(request, limits)
        container = nsif_codec.parse_container(octets, limits)
        body, payload = _OPS[request["op"]](parsed, octets, container)
    except (nsif_codec.NsifError, HostError) as error:
        return _refusal(error, report), b""
    return {"ok": True, "worker": report, **body}, payload


def _bad_request(message: str):
    from synapse_imagery.result import HostError

    return HostError("E_FIELD", "input", None, "/request", message)


def _check_request(request: object) -> dict:
    if type(request) is not dict or request.get("op") not in _OP_FIELDS:
        raise _bad_request("the request names no operation")
    op = request["op"]
    if set(request) != set(_COMMON_FIELDS + _OP_FIELDS[op]):
        raise _bad_request("the request does not carry exactly its operation's fields")
    if request["protocol"] != PROTOCOL:
        raise _bad_request("the request names another protocol")
    if not _int(request["fd"]) or request["fd"] < 0:
        raise _bad_request("fd is not a descriptor number")
    sha = request["expected_sha256"]
    if type(sha) is not str or not _SHA256.fullmatch(sha):
        raise _bad_request("expected_sha256 is not 64 lowercase hexadecimal digits")
    if not _int(request["byte_count"]) or request["byte_count"] < 0:
        raise _bad_request("byte_count is not an int >= 0")
    parsed: dict = {"op": op}
    try:
        if op == "inventory":
            parsed["registry"] = _registry(request["registry"])
        elif op == "translate":
            if type(request["synthetic"]) is not bool:
                raise ValueError
            parsed["synthetic"] = request["synthetic"]
            parsed["context"] = _context(request["context"])
        else:
            if not _int(request["image_index"]):
                raise ValueError
            parsed["image_index"] = request["image_index"]
        if op == "decode_window":
            window, bands, ticket = request["window"], request["bands"], request["ticket"]
            if type(window) is not list or len(window) != 4 or not all(map(_int, window)):
                raise ValueError
            if type(bands) is not list or not all(map(_int, bands)):
                raise ValueError
            if (
                type(ticket) is not dict
                or set(ticket) != {"artefact", "asset_id"}
                or ticket["artefact"] != "pixels"
                or type(ticket["asset_id"]) is not str
            ):
                raise ValueError
            parsed["window"] = window
            parsed["bands"] = tuple(bands)
        if op == "make_preview":
            parsed.update(_preview_fields(request))
    except (TypeError, ValueError):
        raise _bad_request("an operation field does not have its shape") from None
    return parsed


def _preview_fields(request: dict) -> dict:
    from synapse_imagery.preview import RenderingSpec

    rendering, ticket, output_fd = request["rendering"], request["ticket"], request["output_fd"]
    if type(rendering) is not dict or set(rendering) != {"max_size", "bands"}:
        raise ValueError
    bands = rendering["bands"]
    if bands is not None and type(bands) is not list:
        raise ValueError
    spec = RenderingSpec(rendering["max_size"], None if bands is None else tuple(bands))
    if (
        type(ticket) is not dict
        or set(ticket) != {"artefact", "asset_id"}
        or ticket["artefact"] != "thumbnail"
        or type(ticket["asset_id"]) is not str
    ):
        raise ValueError
    if not _int(output_fd) or output_fd < 0:
        raise ValueError
    return {"spec": spec, "parent_id": ticket["asset_id"], "output_fd": output_fd}


def _registry(wire: object):
    from synapse_imagery.policy import ExtensionRegistry

    if type(wire) is not dict or set(wire) != {"version", "security_neutral"}:
        raise ValueError
    entries = wire["security_neutral"]
    if type(entries) is not list or not all(
        type(entry) is list and len(entry) == 2 for entry in entries
    ):
        raise ValueError
    return ExtensionRegistry(wire["version"], frozenset(tuple(entry) for entry in entries))


def _context(wire: object):
    from synapse_cdm.adapters.geojson import AsOf
    from synapse_cdm.adapters.stanag4545 import Stanag4545Context

    keys = {"dataset_namespace", "product_key", "as_of", "asset_ref", "verified_sha256"}
    if type(wire) is not dict or set(wire) != keys:
        raise ValueError
    as_of = wire["as_of"]
    if as_of is not None:
        if (
            type(as_of) is not dict
            or set(as_of) != {"instant", "basis"}
            or type(as_of["instant"]) is not str
        ):
            raise ValueError
        as_of = AsOf(instant=as_of["instant"], basis=as_of["basis"])
    return Stanag4545Context(
        dataset_namespace=wire["dataset_namespace"],
        product_key=wire["product_key"],
        as_of=as_of,
        asset_ref=wire["asset_ref"],
        verified_sha256=wire["verified_sha256"],
    )


def _read_source(request: dict, limits) -> bytes:
    import hashlib
    import stat

    from synapse_imagery.result import HostError

    def integrity(message: str):
        return HostError("E_INTEGRITY", "input", None, "/asset", message)

    fd, count = request["fd"], request["byte_count"]
    try:
        status = os.fstat(fd)
    except OSError:
        raise integrity("the source descriptor cannot be read") from None
    if not stat.S_ISREG(status.st_mode) or status.st_size != count:
        raise integrity("the source is not a regular file of the stated length")
    if count > limits.input_bytes:
        raise HostError(
            "E_LIMIT",
            "input",
            None,
            "/input",
            f"the input is larger than {limits.input_bytes} octets",
        )
    chunks = []
    done = 0
    while done < count:
        chunk = os.pread(fd, min(count - done, 1_048_576), done)
        if not chunk:
            raise integrity("the source ended before its stated length")
        chunks.append(chunk)
        done += len(chunk)
    octets = b"".join(chunks)
    if hashlib.sha256(octets).hexdigest() != request["expected_sha256"]:
        raise integrity("the source differs from its stated digest")
    return octets


def _date(value) -> dict:
    from synapse_cdm import times

    return {
        "status": value.status,
        "utc": times.render(value.value) if value.status == "valid" else None,
    }


def _diagnostic(entry) -> dict:
    return {
        "code": entry.code,
        "stage": entry.stage,
        "offset": entry.offset,
        "path": entry.path,
        "message": entry.message,
    }


def _op_inventory(parsed: dict, octets: bytes, container) -> tuple[dict, bytes]:
    from synapse_imagery.policy import SecurityDescriptor

    descriptor = SecurityDescriptor.from_container(container, parsed["registry"])
    inventory = {
        "format": "sc-imagery-inventory/1",
        "signature": container.signature,
        "clevel": container.clevel,
        "file_size": container.file_size,
        "header_length": container.header_length,
        "file_date": _date(container.file_header.fdt),
        "segments": [
            {
                "kind": segment.kind,
                "index": segment.index,
                "subheader": {
                    "offset": segment.subheader.offset,
                    "length": segment.subheader.length,
                },
                "data": {"offset": segment.data.offset, "length": segment.data.length},
            }
            for segment in container.segments
        ],
        "images": [
            {
                "index": image.index,
                "nrows": image.nrows,
                "ncols": image.ncols,
                "bands": image.band_count,
                "nbpp": image.nbpp,
                "abpp": image.abpp,
                "pvtype": image.pvtype,
                "imode": image.imode,
                "ic": image.ic,
                "irep": image.irep,
                "icat": image.icat,
                "masked": image.ic.startswith("M") or image.ic == "NM",
                "pixel_status": image.pixel_status,
                "pixel_reason": image.pixel_reason,
                "geometry_status": image.geometry_status,
                "capture_date": _date(image.idatim),
            }
            for image in container.images
        ],
        "extension_counts": {
            "tre": len(container.extensions),
            "des": len(container.des),
            "res": len(container.res),
        },
        "composition_status": container.composition_status,
        "descriptor": descriptor.json_text,
        "diagnostics": [_diagnostic(entry) for entry in container.diagnostics],
    }
    return {"inventory": inventory}, b""


def _op_translate(parsed: dict, octets: bytes, container) -> tuple[dict, bytes]:
    import hashlib

    from synapse_cdm.adapters.stanag4545 import Stanag4545Adapter

    from synapse_imagery.result import HostError

    context = parsed["context"]
    # The digest in the context must be the digest of the octets translated here.
    if context.verified_sha256 not in (None, hashlib.sha256(octets).hexdigest()):
        raise HostError(
            "E_INTEGRITY", "input", None, "/asset", "the context's digest is not this source's"
        )
    adapter = Stanag4545Adapter(synthetic=parsed["synthetic"], context=context)
    objects = adapter.to_cdm(octets)
    return {"objects": [item.model_dump(mode="json") for item in objects]}, b""


def _no_such_image(container, index: int):
    from synapse_cdm.adapters.nsif_codec import NsifError

    if not 0 <= index < len(container.images):
        raise NsifError("E_FIELD", "pixels", None, "/window/image_index", "no such image")
    return container.images[index]


def _op_inspect_codec(parsed: dict, octets: bytes, container) -> tuple[dict, bytes]:
    index = parsed["image_index"]
    image = _no_such_image(container, index)
    masked = image.ic.startswith("M") or image.ic == "NM"
    enabled = image.pixel_status == "native_supported"
    capability = {
        "image_index": index,
        "ic": image.ic,
        "pvtype": image.pvtype,
        "nbpp": image.nbpp,
        "abpp": image.abpp,
        "imode": image.imode,
        "masked": masked,
        "cell": (
            f"IC={image.ic};PVTYPE={image.pvtype};NBPP={image.nbpp};ABPP={image.abpp};"
            f"IMODE={image.imode};MASK={'yes' if masked else 'no'}"
        ),
        "enabled": enabled,
        "path": "native" if enabled else "none",
        "reason": None if enabled else image.pixel_reason,
    }
    return {"capability": capability}, b""


def _op_decode_window(parsed: dict, octets: bytes, container) -> tuple[dict, bytes]:
    from synapse_cdm.adapters import nsif_codec

    x, y, width, height = parsed["window"]
    window = nsif_codec.decode_nc_window(
        container, parsed["image_index"], x, y, width, height, parsed["bands"]
    )
    fields = {
        "image_index": window.image_index,
        "x": window.x,
        "y": window.y,
        "width": window.width,
        "height": window.height,
        "bands": list(window.bands),
        "kind": window.kind,
        "dtype": window.dtype,
        "fill_bits_nonzero": window.fill_bits_nonzero,
        "fill_bits_sign_extended": window.fill_bits_sign_extended,
        "diagnostics": [_diagnostic(entry) for entry in window.diagnostics],
    }
    return {"window": fields, "payload_bytes": len(window.data)}, window.data


def _op_make_preview(parsed: dict, octets: bytes, container) -> tuple[dict, bytes]:
    """The whole native image, decoded once with the chosen bands, drawn and written through the
    output descriptor in one piece. The answer carries the derivative's facts and provenance;
    the parent adds nothing it has not checked."""
    import hashlib

    from synapse_cdm.adapters import nsif_codec

    from synapse_imagery import preview

    index, spec = parsed["image_index"], parsed["spec"]
    image = _no_such_image(container, index)
    facts = preview.facts_of(image)
    chosen = preview.select(facts, spec)
    # The adapter's own checks decide first: E_CODEC or E_PROFILE outside the native cell, then
    # the bands, then the window cap.
    window = nsif_codec.decode_nc_window(
        container, index, 0, 0, image.ncols, image.nrows, chosen.bands
    )
    tables = ()
    if chosen.selection == "lut":
        if not preview.lut_index_ok(window, image.bands[0].neluts):
            raise nsif_codec.NsifError(
                "E_FIELD",
                "pixels",
                facts.lut_offset,
                f"/segments/image[{index}]/band[0]/LUTD",
                preview.LUT_INDEX_MESSAGE,
            )
        tables = preview.lut_tables(container.raw, image)
    width, height, channels, rows = preview.render(window, facts, chosen, spec.max_size, tables)
    png = preview.png_bytes(width, height, channels, rows)
    found = []
    if chosen.unresolved:
        note = nsif_codec.Diagnostic(
            preview.UNRESOLVED,
            "pixels",
            facts.irep_offset,
            f"/segments/image[{index}]/IREP",
            preview.UNRESOLVED_MESSAGE,
        )
        found.append(_diagnostic(note))
    provenance = {
        "algorithm": chosen.algorithm,
        "parameters": preview.parameters(chosen.algorithm, spec.max_size),
        "selection": chosen.selection,
        "bands": list(chosen.bands),
        "image_index": index,
        "source_window": [0, 0, image.ncols, image.nrows],
        "size": [width, height],
        "composition": "segment_only",
    }
    if container.graphics:
        # Retained, never rendered: the preview says so.
        provenance["graphic_segments"] = len(container.graphics)
        provenance["graphics_composed"] = False
    provenance.update(
        diagnostics=found,
        parent_id=parsed["parent_id"],
        parent_sha256=hashlib.sha256(octets).hexdigest(),
        software=preview.software(),
        worker=parsed["report"],
    )
    view = memoryview(png)
    while view:
        view = view[os.write(parsed["output_fd"], view) :]
    derivative = {
        "width": width,
        "height": height,
        "channels": channels,
        "sha256": hashlib.sha256(png).hexdigest(),
        "byte_count": len(png),
        "provenance": provenance,
    }
    return {"derivative": derivative}, b""


_OPS = {
    "inventory": _op_inventory,
    "translate": _op_translate,
    "inspect_codec": _op_inspect_codec,
    "decode_window": _op_decode_window,
    "make_preview": _op_make_preview,
}
