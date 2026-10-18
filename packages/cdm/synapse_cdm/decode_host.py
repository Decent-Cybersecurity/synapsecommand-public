"""The offline host command `synapse-decode` (`python -m synapse_cdm.decode_host`).

One generic host for the observation adapters, on `synapse-dis7`'s shape: it reads ONE local
file with a bound, digests exactly the octets it read, checks that digest against the one the
caller expected, unwraps a declared container under its own bounds, frames the result, and hands
each frame to the adapter it names, constructed from VALUES the caller supplied. The adapter
stays a pure function of one payload and its constructor arguments — ARCHITECTURE.md §6.1's
determinism tuple — and everything that is not that (the file, the digest, the container, the
framing) happens here, where it is checked once instead of once per adapter.

    decode --adapter A --input F (--synthetic | --live)
           [--sha256 HEX | --manifest-row FILE]
           [--container gzip | --container tar --member NAME]
           [--at T --basis B] [--session S] [--received-at T]
           [--station-table FILE] [--request KEY=VALUE ...]
    list           the hosted adapters, the arguments each declares, and its bounds
    --version      the package version and the hosted adapters

WHAT IS REFUSED, AND WITH WHICH EXIT CODE
-----------------------------------------
0 success: the canonical UTF-8 JSON array of every object, in frame order, on stdout.
2 usage, or a context derived from the flags: a command line the argument parser refuses; an
  `--input` that names a remote locator (a `/vsicurl/` or other GDAL virtual path, an
  `http(s)://` URL, an `s3://` locator, a DAP locator, any other URL), at its start or behind a
  driver prefix or quotes — refused by name before anything is stat'ed; an adapter this host
  does not serve; an argument the adapter does not declare, or a declared one missing or
  malformed; a manifest row that is not one JSON object with a `sha256`, or that carries a
  credential in one of the shapes `_CREDENTIAL` names; a station table the contract refuses.
3 rejected data: a file over the adapter's bound; a SHA-256 that differs from the expected one;
  a container refused by its bounds or its shape; octets the adapter's framer cannot cut into
  frames; a frame the adapter refuses (`ValueError`).
4 I/O: an `--input` or context file that is absent or not a regular file (a FIFO or a device is
  refused without blocking), or stdout that cannot be written.

A symbolic link to a regular file is followed, and the file it names is what is read, bounded and
digested; `/dev/stdin` (or `/dev/fd/0`) is read the same way when the shell redirected a regular
file onto it. That is the recorded policy (2026-10-15), not an oversight: the type check runs on
what the path resolves to, so a link to a FIFO, a device or a directory is still exit 4.

Diagnostics go to stderr, one line each, and are fixed text: they name a flag, a bound, a byte
count, a frame ordinal or an exception class, and never a byte of the input, a key, a value, a
request parameter or a manifest URL. That holds for the argument parser's refusals too: its own
message quotes what was typed, so it is replaced by the class of the error and the declared flags
it names. Stdout carries only the result. Nothing here opens a
socket, reads the clock or writes a file.

WHAT THE DIGEST IS OF
---------------------
`source_hash` is the SHA-256 of the file exactly as read — before any container is unwrapped —
because that is what a collection manifest hashed and what a consumer can re-verify. It is
computed by `evidence.digest_bytes`, the one module allowed to digest, and it is injected only
into an adapter that declares a `source_hash` argument; for any other it is still checked
against `--sha256` or the manifest row, and `list` says it is not injected.

When the octets an adapter is handed are not the file — a container was unwrapped, or a framer
cut the file into several payloads — an adapter that declares a frame-digest argument
(`Hosted.frame_digest_argument`, since 2026-10-15) is also given the SHA-256 of the frame it is
handed, computed here by the same function, and records it as its locator's `frame_sha256`. When
the frame is the whole file, nothing is passed: `source_hash` already digests those octets.

A framer cuts the (unwrapped) octets into frames that lie end to end from the first octet, so a
frame's position is the sum of the frames before it; an adapter that declares a frame-offset
argument (`Hosted.frame_offset_argument`, since 2026-10-17, for `grib2`) is given the octet its
frame begins at in those octets, beside its ordinal. `grib_messages` is the GRIB2 framer: one
message per frame, cut at each Section 0's eight-octet total length, and a file that is not its
messages end to end — a stray octet between two, a length that runs past the end, an edition 1
message, whose length field is another — is exit 3.

Two raster adapters are served since 2026-10-17, each reading its file whole. `cog` takes a
GeoTIFF or a VRT index; what it must not be left to guess comes as request parameters — the file's
name `--request band_file=NAME` and its granule `--request granule=ID`, identifiers the host never
reads off a path — and `--at`/`--basis` comes only with `--request time=sensing_time` (a band
file whose metadata states no sensing time) or `--request time=as_of` (a DEM or a VRT), the
adapter's two injected instants, because which one applies is known only once the file is read.
`iem_n0q` takes one IEM N0Q composite PNG, and `--at`/`--basis` is the archive file name's slot,
refused (exit 2) unless it falls on IEM's five-minute grid.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import os
import re
import stat
import sys
import tarfile
import types
import zlib
from typing import Any, Callable, Mapping, Sequence

from synapse_cdm import canonical
from synapse_cdm.adapter import json_nesting_depth
from synapse_cdm.manifest import LimitBasis, LimitKind
from synapse_cdm.version import PACKAGE_VERSION

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REJECTED = 3
EXIT_IO = 4

PROG = "synapse-decode"

#: How far a container may inflate relative to the file read: a running total past
#: `MAX_UNWRAP_RATIO` times the file's size is refused before the next chunk is kept.
MAX_UNWRAP_RATIO = 256
#: How many headers a tar archive may hold before it is refused.
MAX_TAR_MEMBERS = 4096
#: The most a single decompression step may take in and the most it may produce.
UNWRAP_CHUNK = 65536
#: A manifest row or a station table: one small JSON document, read with this bound.
MAX_CONTEXT_FILE_BYTES = 1048576
#: How deep that document may nest, measured before it is decoded.
MAX_CONTEXT_DEPTH = 16
#: A request parameter: a lower-case key and a value of at most this many characters.
MAX_REQUEST_VALUE = 1024

_HOST_TESTS = "tests/test_cdm_decode_host.py::"

#: Why each host bound is the number it is, in the form an adapter declares a bound in
#: (`manifest.LimitBasis`). Every one is an implementation cap: none is a format's normative
#: maximum, and none is a bound an adapter declares, because the host applies them to every
#: adapter it serves. Amended 2026-10-15: until then these were prose, and three of the six had
#: none at all.
BOUNDS_BASIS: Mapping[str, LimitBasis] = types.MappingProxyType(
    {
        "MAX_UNWRAP_RATIO": LimitBasis(
            kind=LimitKind.IMPLEMENTATION_CAP,
            source=(
                "The design record measures no container's compression ratio, so the primary "
                "bound on unwrapped octets is the hosted adapter's own byte bound, and this ratio "
                "refuses a small file that would inflate far past its size before that total is "
                "reached. The nearest figures the rulings hold are the arc's two decompression "
                "bounds: readsb_trace 8 MiB of input to 64 MiB inflated (8x) and iem_n0q 8 MiB to "
                "80 MiB (10x, from a 12200 x 5400 paletted PNG's 65,880,000 octets of rows plus "
                "their filter bytes), DECISIONS U-07 and L-09. 256x sits above both, so it never "
                "refuses a container those bounds admit. This is an IMPLEMENTATION CAP and is "
                "NOT a format's normative maximum."
            ),
            enforced_at=(
                "decode_host.gunzip: the running total is held to min(the adapter's bound, "
                "MAX_UNWRAP_RATIO x the octets read) before each step's output is kept"
            ),
            test=_HOST_TESTS + "test_gzip_is_bounded_by_the_adapters_bound_and_by_the_ratio",
        ),
        "MAX_TAR_MEMBERS": LimitBasis(
            kind=LimitKind.IMPLEMENTATION_CAP,
            source=(
                "The host takes ONE named member, so the count only has to admit a real day "
                "archive's index while bounding the walk: 4096 headers of 512 octets are 2 MiB "
                "of headers alone, a quarter of the 8 MiB file bound geojson, readsb_trace and "
                "the three station-text adapters declare (dis7 declares 4224 octets and nexrad2 "
                "32 MiB). This is an IMPLEMENTATION CAP and is NOT a format's normative maximum."
            ),
            enforced_at="decode_host.untar: counted while the headers are walked",
            test=_HOST_TESTS
            + "test_a_tar_is_bounded_by_its_member_count_its_member_size_and_its_own_shape",
        ),
        "MAX_CONTEXT_FILE_BYTES": LimitBasis(
            kind=LimitKind.IMPLEMENTATION_CAP,
            source=(
                "A manifest row is one object holding a digest and a few columns, and a station "
                "table one row of an identifier and two coordinates per station; 1 MiB holds "
                "tens of thousands of such rows. This is an IMPLEMENTATION CAP and is NOT a "
                "format's normative maximum."
            ),
            enforced_at=(
                "decode_host._context_document: the file is read to one octet past the bound "
                "and refused at that octet, before it is decoded"
            ),
            test=_HOST_TESTS + "test_a_manifest_row_past_its_bound_is_exit_2",
        ),
        "MAX_CONTEXT_DEPTH": LimitBasis(
            kind=LimitKind.IMPLEMENTATION_CAP,
            source=(
                "A station table nests three containers (the table, its rows, a row) and a "
                "manifest row one; 16 leaves room for a register's own nesting and refuses a "
                "document built to exhaust a recursive walk. This is an IMPLEMENTATION CAP and "
                "is NOT a format's normative maximum."
            ),
            enforced_at=(
                "decode_host._context_document: adapter.json_nesting_depth measures the text "
                "before json.loads"
            ),
            test=_HOST_TESTS
            + "test_a_manifest_row_is_one_strict_object_with_a_digest_and_no_credential",
        ),
        "MAX_REQUEST_VALUE": LimitBasis(
            kind=LimitKind.IMPLEMENTATION_CAP,
            source=(
                "A request parameter names a datum, a time zone or a product the source was "
                "asked for. 1024 characters is the bound every caller-supplied basis text has "
                "in this layer (`--basis`, InjectedTime.basis), so no constructor argument a "
                "person types is longer than another. This is an IMPLEMENTATION CAP and is NOT "
                "a format's normative maximum."
            ),
            enforced_at="decode_host._context: each --request is checked before the input is read",
            test=_HOST_TESTS
            + "test_request_parameters_are_key_value_pairs_and_a_value_is_never_echoed",
        ),
        "UNWRAP_CHUNK": LimitBasis(
            kind=LimitKind.IMPLEMENTATION_CAP,
            source=(
                "One step of an unwrap: the octets handed to the inflater at once, and the most "
                "it may produce at once. Bounding both keeps each step's work and memory "
                "constant, so the total work is linear in the file and in what it inflates to; "
                "at 64 KiB the smallest hosted file (dis7's bound, 4224 octets) is one step and "
                "an 8 MiB file 128 steps of input. This is an IMPLEMENTATION CAP and is NOT a "
                "format's normative maximum."
            ),
            enforced_at=(
                "decode_host.gunzip feeds the input in slices of UNWRAP_CHUNK and asks for at "
                "most UNWRAP_CHUNK octets per step; decode_host.untar reads the member in steps "
                "of UNWRAP_CHUNK"
            ),
            test=_HOST_TESTS + "test_gzip_input_is_fed_in_bounded_steps_and_the_work_is_linear",
        ),
    }
)

#: A credential in a manifest string. The register forbids secrets in the manifest; a row that
#: has one is refused, so the host never handles it further. This is a check over named shapes,
#: not a proof that a string holds no secret:
#:   - a parameter or header whose name says it carries one, followed by `=` or `:`
#:     (`api_key=`, `Authorization:`, `X-Amz-Signature=`, `token :`);
#:   - `bearer` and a token of eight or more token characters (RFC 6750's scheme);
#:   - a query parameter named `key` or `sig`, or ending in either (`?key=`, `&subscription-key=`);
#:   - a password inside a URL (`scheme://user:password@`, `scheme://:password@`);
#:   - a cookie header (`Cookie:`, `Set-Cookie:`), since 2026-10-15: a session cookie is a
#:     credential however its own name reads.
#: Each string is matched as written and, when it holds a `%`, once more with every `%xx` escape
#: decoded (`_percent_decoded`), so `api%5Fkey=` and `%61pi_key=` are the names they spell.
#: The row is up to a megabyte, so every alternative is linear in the string: no repeated group
#: can split a run two ways (the URL user part excludes `:`, which is what separates it from the
#: password), and the bearer and query alternatives scan a run of one character class once.
_CREDENTIAL = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|access[_-]?token|authorization|auth|token|secret|"
    r"passw(or)?d|credential|signature|bearer|x-amz-security-token|cookie)\s*[=:]"
    r"|bearer\s+[a-z0-9._~+/\-]{8}"
    r"|[?&;][a-z0-9_.\-]*(key|sig)="
    r"|://[^/@\s:]*:[^/@\s]*@"
)

#: One `%xx` escape. Decoded once, as a URL parser decodes a query: a doubly encoded name
#: (`%2561`) is not decoded twice, because repeating the decode until nothing changes is not
#: linear in the row.
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")

#: Remote locators, by name, matched at the start of an argument before it is stat'ed. Each one
#: would fail `os.stat` anyway; refusing it by name says why, and keeps the refusal from depending
#: on what the local file system happens to hold.
_REMOTE = (
    (re.compile(r"(?i)/vsicurl(_streaming)?/"), "a GDAL /vsicurl/ path"),
    (re.compile(r"(?i)/vsi[a-z0-9_]*/"), "a GDAL virtual file system path"),
    (re.compile(r"(?i)s3://"), "an s3:// locator"),
    (re.compile(r"(?i)https?://"), "an http(s):// URL"),
    (re.compile(r"(?i)(dods|dap2|dap4)://"), "a DAP locator"),
    (re.compile(r"(?i)(\[[^\]]*\])+[a-z][a-z0-9+.\-]*://"), "a DAP locator"),
    (re.compile(r"(?i)[a-z][a-z0-9+.\-]*://"), "a URL"),
)

#: The same forms anywhere else in the argument: GDAL opens a remote locator behind a driver
#: prefix and quotes (`NETCDF:"/vsicurl/…":var`, `HDF5:"https://…"`, `GTIFF_DIR:1:/vsis3/…`), so
#: a check at the start alone would let those through to `os.stat`. A local path that contains
#: `/vsi…/` or `<scheme>://` is refused with them; that is the stricter reading. A scheme is
#: matched only where a run of scheme characters begins, so the search stays linear.
_SCHEME_START = r"(?<![a-z0-9+.\-])"
_REMOTE_INSIDE = (
    (re.compile(r"(?i)/vsicurl(_streaming)?/"), "a GDAL /vsicurl/ path"),
    (re.compile(r"(?i)/vsi[a-z0-9_]*/"), "a GDAL virtual file system path"),
    (re.compile(r"(?i)\[[^\[\]]*\][a-z][a-z0-9+.\-]*://"), "a DAP locator"),
    (re.compile(r"(?i)" + _SCHEME_START + r"s3://"), "an s3:// locator"),
    (re.compile(r"(?i)" + _SCHEME_START + r"https?://"), "an http(s):// URL"),
    (re.compile(r"(?i)" + _SCHEME_START + r"(dods|dap2|dap4)://"), "a DAP locator"),
    (re.compile(r"(?i)" + _SCHEME_START + r"[a-z][a-z0-9+.\-]*://"), "a URL"),
)

#: A key whose name says its value is a credential, at any depth of a manifest row, matched whole
#: as written and with its `%xx` escapes decoded. A bare `key` is not one: an object store names
#: the object's path so. Since 2026-10-15 an HTTP header's `x-` prefix is allowed in front of any
#: of the names (`x-api-key`, `x-auth-token`), `auth-token` is a name of its own, and so are the
#: two cookie headers. Since a later 2026-10-15 reading (R1b review N-1) the prefix is `x-` or
#: `x_`, and the names a provider spells its own way are names too: `amz-signature`,
#: `amz-security-token`, `api-token`, `goog-api-key`, `proxy-authorization` and `set_cookie`.
#: Every name is an alternative of fixed text, matched whole on a key, so the match is linear.
_CREDENTIAL_KEY = re.compile(
    r"(?i)(x[-_])?(api[_-]?key|access[_-]?key|access[_-]?token|auth([_-]?token)?|"
    r"(proxy[_-])?authorization|token|secret|passw(or)?d|credentials?|bearer|signature|"
    r"(set[_-])?cookie|amz[_-]signature|amz[_-]security[_-]token|api[_-]?token|"
    r"goog[_-]api[_-]?key)"
)

_SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
_REQUEST_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")


class Refused(Exception):
    """A refusal the host makes itself. Its message is fixed text and is printed as it is."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(status, message)
        self.status = status
        self.message = message

    def __str__(self) -> str:
        return self.message


# -- the hosted adapters -------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Context:
    """The values the caller supplied, after the host checked their form."""

    synthetic: bool
    at: str | None = None
    basis: str | None = None
    session: str | None = None
    received_at: Any = None
    station_table: Any = None
    request: tuple[tuple[str, str], ...] = ()


def whole_file(data: bytes) -> list[bytes]:
    """The framer for a format whose payload unit is the whole (unwrapped) file."""
    return [data]


def grib_messages(data: bytes) -> list[bytes]:
    """The framer for GRIB2 (2026-10-17): one message per frame, cut at each Section 0's total
    length (octets 9-16), the messages end to end with nothing between them. A refusal is exit 3
    and names an octet position, never an octet of the input."""
    frames: list[bytes] = []
    position = 0
    while position < len(data):
        if len(data) - position < 16 or data[position : position + 4] != b"GRIB":
            raise Refused(
                EXIT_REJECTED,
                f"{PROG}: octet {position} of the input does not begin a GRIB message; a GRIB2 "
                "file is its messages end to end",
            )
        if data[position + 7] != 2:
            raise Refused(
                EXIT_REJECTED,
                f"{PROG}: the message at octet {position} is not GRIB edition 2, which is the only "
                "edition this host frames",
            )
        total = int.from_bytes(data[position + 8 : position + 16], "big")
        if total < 20 or total > len(data) - position:
            raise Refused(
                EXIT_REJECTED,
                f"{PROG}: the message at octet {position} states a total length shorter than "
                "Sections 0 and 8 or running past the end of the input",
            )
        frames.append(data[position : position + total])
        position += total
    if not frames:
        raise Refused(EXIT_REJECTED, f"{PROG}: the input holds no GRIB message")
    return frames


def _input_bound(cls: type) -> int:
    return cls.capabilities().limits.max_input_bytes


@dataclasses.dataclass(frozen=True)
class Hosted:
    """One adapter this host serves, and how it is constructed.

    `arguments` are the flag groups the adapter declares — `time` (`--at` with `--basis`),
    `session`, `received_at`, `station_table`, `request` — and `required` those it cannot do
    without. `prepare` turns the checked `Context` into constructor keyword arguments, refusing
    a value the adapter would refuse (a `ValueError`, exit 2), before the input is read.
    `max_file_bytes` and `max_unwrapped_bytes` read the bounds off the adapter class.
    `frame_digest_argument` names the constructor argument that takes the SHA-256 of the frame
    when the frame is not the file as read, and `frame_offset_argument` the one that takes the
    octet the frame begins at (the module docstring's last paragraphs).
    """

    name: str
    load: Callable[[], type]
    arguments: frozenset[str]
    required: frozenset[str]
    prepare: Callable[[Context], dict]
    injects_source_hash: bool
    reads_clock: bool = False
    framer: Callable[[bytes], Sequence[bytes]] = whole_file
    frame_argument: str | None = None
    max_file_bytes: Callable[[type], int] = _input_bound
    max_unwrapped_bytes: Callable[[type], int] = _input_bound
    frame_digest_argument: str | None = None
    frame_offset_argument: str | None = None


def _load_dis7() -> type:
    from synapse_cdm.adapters.dis7 import Dis7Adapter

    return Dis7Adapter


def _prepare_dis7(context: Context) -> dict:
    from synapse_cdm.adapters.dis7 import TimeContext, validate_session

    return {
        "session": validate_session(context.session),
        "synthetic": context.synthetic,
        "time_context": TimeContext(context.at, context.basis),
    }


def _load_geojson() -> type:
    from synapse_cdm.adapters.geojson import GeojsonAdapter

    return GeojsonAdapter


def _prepare_geojson(context: Context) -> dict:
    from synapse_cdm.adapters.geojson import AsOf
    from synapse_cdm.observation_contracts import parse_instant

    as_of = None
    if context.at is not None:
        as_of = AsOf(parse_instant(context.at), context.basis)
    return {"synthetic": context.synthetic, "as_of": as_of}


def _load_readsb_trace() -> type:
    from synapse_cdm.adapters.readsb_trace import ReadsbTraceAdapter

    return ReadsbTraceAdapter


def _prepare_readsb_trace(context: Context) -> dict:
    # The adapter inflates the trace file's own gzip member itself, so the file (or the tar
    # member a day archive holds it in) is handed over as read; its only context is the receipt.
    return {"synthetic": context.synthetic}


def _load_nexrad2() -> type:
    from synapse_cdm.adapters.nexrad2 import Nexrad2Adapter

    return Nexrad2Adapter


def _prepare_nexrad2(context: Context) -> dict:
    # A volume is one file; its digest and, when a container was unwrapped around it, the
    # digest of the volume itself are injected by `decode`, and its context is the receipt.
    return {"synthetic": context.synthetic}


def _load_ndbc_stdmet() -> type:
    from synapse_cdm.adapters.ndbc_stdmet import NdbcStdmetAdapter

    return NdbcStdmetAdapter


def _prepare_ndbc_stdmet(context: Context) -> dict:
    # A stdmet file states neither its station nor the station's position: the station is the
    # one request parameter (`--request station=...`), the position the caller's station table.
    from synapse_cdm.adapters.ndbc_stdmet import checked_station_id

    request = dict(context.request)
    if set(request) != {"station"}:
        raise ValueError("ndbc_stdmet takes exactly one request parameter, station")
    return {
        "synthetic": context.synthetic,
        "station_id": checked_station_id(request["station"]),
        "station_table": context.station_table,
    }


def _load_coops_csv() -> type:
    from synapse_cdm.adapters.coops_csv import CoopsCsvAdapter

    return CoopsCsvAdapter


def _prepare_coops_csv(context: Context) -> dict:
    # A response echoes none of the parameters it was requested with, so they are the request
    # the caller restates, refused here (exit 2) exactly as the adapter's CoopsRequest refuses
    # them: lst_ldt by name, a request with no time zone, a datum outside the API's list.
    from synapse_cdm.adapters.coops_csv import CoopsRequest

    return {
        "synthetic": context.synthetic,
        "request": CoopsRequest.from_pairs(context.request),
        "station_table": context.station_table,
    }


def _load_airnow_hourly() -> type:
    from synapse_cdm.adapters.airnow_hourly import AirnowHourlyAdapter

    return AirnowHourlyAdapter


def _prepare_airnow_hourly(context: Context) -> dict:
    # A HourlyData line states no position: the caller's station table, keyed by AQSID, is the
    # site table.
    return {"synthetic": context.synthetic, "site_table": context.station_table}


def _load_grib2() -> type:
    from synapse_cdm.adapters.grib2 import Grib2Adapter

    return Grib2Adapter


def _prepare_grib2(context: Context) -> dict:
    # A message is one frame of the file: its ordinal, its first octet and, when the file held
    # more than one message or a gzip was unwrapped, its own digest are given by `decode`; its
    # context is the receipt.
    return {"synthetic": context.synthetic}


def _load_cog() -> type:
    from synapse_cdm.adapters.cog import CogAdapter

    return CogAdapter


#: The request parameters `cog` takes (2026-10-17), and the two roles `--at` may play for it.
COG_REQUEST_KEYS = ("band_file", "granule", "time")
COG_TIME_ROLES = ("sensing_time", "as_of")


def _prepare_cog(context: Context) -> dict:
    # A GeoTIFF or a VRT is one file, read whole. What the host must not guess is handed over as
    # request parameters: the file's name (`band_file`) and the granule its band files share
    # (`granule`), both identifiers only, because the host never reads a name off a path; and,
    # when `--at` is given, which of the adapter's two injected instants it is (`time=sensing_time`
    # for a band file whose metadata states no sensing time, `time=as_of` for a DEM or a VRT),
    # because the adapter cannot tell before it has read the file and the host does not read it.
    # The adapter's constructor is run here, reading no clock, so a value it refuses is exit 2.
    from synapse_cdm.observation_contracts import InjectedTime, parse_instant

    request = dict(context.request)
    if set(request) - set(COG_REQUEST_KEYS):
        raise ValueError("cog takes the request parameters band_file, granule and time only")
    role = request.get("time")
    if (role is None) != (context.at is None):
        raise ValueError("--request time=... names the role of --at, and is given with it only")
    if role is not None and role not in COG_TIME_ROLES:
        raise ValueError("--request time is sensing_time or as_of")
    kwargs: dict = {
        "synthetic": context.synthetic,
        "band_file": request.get("band_file"),
        "granule_id": request.get("granule"),
    }
    if role is not None:
        kwargs[role] = InjectedTime(parse_instant(context.at), context.basis)
    _load_cog()(_no_clock, **kwargs)
    return kwargs


def _load_iem_n0q() -> type:
    from synapse_cdm.adapters.iem_n0q import IemN0qAdapter

    return IemN0qAdapter


def _prepare_iem_n0q(context: Context) -> dict:
    # A PNG states no time: the archive file name's slot is `--at`, with its basis, parsed by the
    # caller from the name (2026-10-17). A slot off IEM's five-minute grid is refused here, exit 2,
    # before the file is read.
    from synapse_cdm.adapters.iem_n0q import checked_slot
    from synapse_cdm.observation_contracts import InjectedTime, parse_instant

    return {
        "synthetic": context.synthetic,
        "slot": checked_slot(InjectedTime(parse_instant(context.at), context.basis)),
    }


#: Every adapter this host serves. An observation adapter adds its row here when it lands, with its
#: framer when its payload unit is smaller than the file.
HOSTED: Mapping[str, Hosted] = types.MappingProxyType(
    {
        "dis7": Hosted(
            name="dis7",
            load=_load_dis7,
            arguments=frozenset({"time", "session"}),
            required=frozenset({"time", "session"}),
            prepare=_prepare_dis7,
            injects_source_hash=True,
        ),
        "geojson": Hosted(
            name="geojson",
            load=_load_geojson,
            arguments=frozenset({"time"}),
            required=frozenset(),
            prepare=_prepare_geojson,
            injects_source_hash=False,
        ),
        "readsb_trace": Hosted(
            name="readsb_trace",
            load=_load_readsb_trace,
            arguments=frozenset({"received_at"}),
            required=frozenset({"received_at"}),
            prepare=_prepare_readsb_trace,
            injects_source_hash=False,
            reads_clock=True,
        ),
        "nexrad2": Hosted(
            name="nexrad2",
            load=_load_nexrad2,
            arguments=frozenset({"received_at"}),
            required=frozenset({"received_at"}),
            prepare=_prepare_nexrad2,
            injects_source_hash=True,
            reads_clock=True,
            frame_digest_argument="frame_sha256",
        ),
        "ndbc_stdmet": Hosted(
            name="ndbc_stdmet",
            load=_load_ndbc_stdmet,
            arguments=frozenset({"received_at", "request", "station_table"}),
            required=frozenset({"received_at", "request"}),
            prepare=_prepare_ndbc_stdmet,
            injects_source_hash=True,
            reads_clock=True,
            frame_digest_argument="frame_sha256",
        ),
        "coops_csv": Hosted(
            name="coops_csv",
            load=_load_coops_csv,
            arguments=frozenset({"received_at", "request", "station_table"}),
            required=frozenset({"received_at", "request"}),
            prepare=_prepare_coops_csv,
            injects_source_hash=True,
            reads_clock=True,
            frame_digest_argument="frame_sha256",
        ),
        "airnow_hourly": Hosted(
            name="airnow_hourly",
            load=_load_airnow_hourly,
            arguments=frozenset({"received_at", "station_table"}),
            required=frozenset({"received_at"}),
            prepare=_prepare_airnow_hourly,
            injects_source_hash=True,
            reads_clock=True,
            frame_digest_argument="frame_sha256",
        ),
        "grib2": Hosted(
            name="grib2",
            load=_load_grib2,
            arguments=frozenset({"received_at"}),
            required=frozenset({"received_at"}),
            prepare=_prepare_grib2,
            injects_source_hash=True,
            reads_clock=True,
            framer=grib_messages,
            frame_argument="message_ordinal",
            frame_digest_argument="frame_sha256",
            frame_offset_argument="byte_offset",
        ),
        "cog": Hosted(
            name="cog",
            load=_load_cog,
            arguments=frozenset({"received_at", "time", "request"}),
            required=frozenset({"received_at"}),
            prepare=_prepare_cog,
            injects_source_hash=True,
            reads_clock=True,
        ),
        "iem_n0q": Hosted(
            name="iem_n0q",
            load=_load_iem_n0q,
            arguments=frozenset({"received_at", "time"}),
            required=frozenset({"received_at", "time"}),
            prepare=_prepare_iem_n0q,
            injects_source_hash=True,
            reads_clock=True,
            frame_digest_argument="frame_sha256",
        ),
    }
)

#: Each argument group and the flags that spell it, for the diagnostics.
_FLAGS = {
    "time": "--at/--basis",
    "session": "--session",
    "received_at": "--received-at",
    "station_table": "--station-table",
    "request": "--request",
}


# -- reading -------------------------------------------------------------------------------------


def remote_locator(argument: str) -> str | None:
    """What kind of remote locator `argument` is, or None for a plain path.

    The start of the argument is judged first, so a locator keeps the name its leading form
    gives it; then the same forms anywhere inside it (after a driver prefix, a quote, a space).
    """
    for pattern, what in _REMOTE:
        if pattern.match(argument):
            return what
    for pattern, what in _REMOTE_INSIDE:
        if pattern.search(argument):
            return what
    return None


def _read_bounded(path: str, limit: int) -> bytes:
    """At most `limit + 1` octets of the regular file `path`; anything else is an `OSError`.

    `dis7_host._read_bounded`'s discipline: the type is checked on the path before opening and
    again on the descriptor, which is opened without blocking, so a FIFO is never waited on.
    """
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise OSError("not a regular file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOCTTY", 0)
        | getattr(os, "O_BINARY", 0)
    )
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


def _read_file(flag: str, path: str, limit: int) -> bytes:
    what = remote_locator(path)
    if what is not None:
        raise Refused(EXIT_USAGE, f"{PROG}: {flag} is {what}; only a local file is read")
    try:
        return _read_bounded(path, limit)
    except OSError as error:
        raise Refused(
            EXIT_IO, f"{PROG}: cannot read {flag}: " + (error.strerror or "not a regular file")
        ) from None


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for key, value in node.items() for s in [key, *_strings(value)]]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item)]
    return []


def _percent_decoded(text: str) -> str:
    """`text` with every `%xx` escape replaced by the character of that code, once."""
    return _PERCENT_ESCAPE.sub(lambda escape: chr(int(escape.group(1), 16)), text)


def _spellings(text: str) -> tuple[str, ...]:
    """The string as written, and as decoded when it holds an escape: a name is matched in both."""
    return (text, _percent_decoded(text)) if "%" in text else (text,)


def _credential_keys(node: Any) -> bool:
    if isinstance(node, dict):
        return any(
            any(_CREDENTIAL_KEY.fullmatch(name) for name in _spellings(key))
            or _credential_keys(value)
            for key, value in node.items()
        )
    if isinstance(node, list):
        return any(_credential_keys(item) for item in node)
    return False


def _credential_string(text: str) -> bool:
    return any(_CREDENTIAL.search(spelling) for spelling in _spellings(text))


def _refuse_constant(_token: str) -> object:
    raise ValueError("a non-finite token")


def _pairs(pairs: list) -> dict:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("a repeated key")
    return dict(pairs)


def _context_document(flag: str, path: str) -> Any:
    """A small strict JSON document: bounded, UTF-8 without a BOM, shallow, no NaN, no repeated
    key. A refusal names the flag and the check, never the content."""
    data = _read_file(flag, path, MAX_CONTEXT_FILE_BYTES)
    if len(data) > MAX_CONTEXT_FILE_BYTES:
        raise Refused(EXIT_USAGE, f"{PROG}: {flag} is more than {MAX_CONTEXT_FILE_BYTES} octets")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(EXIT_USAGE, f"{PROG}: {flag} is not UTF-8") from None
    if text.startswith("﻿") or json_nesting_depth(text) > MAX_CONTEXT_DEPTH:
        raise Refused(EXIT_USAGE, f"{PROG}: {flag} is not a strict JSON document")
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        raise Refused(EXIT_USAGE, f"{PROG}: {flag} is not a strict JSON document") from None


def manifest_sha256(path: str) -> str:
    """The SHA-256 a manifest row states for the file, lower-cased.

    The row is one JSON object; the host reads its `sha256` member and nothing else, and passes
    nothing from it to the adapter (the row is not a constructor argument: it may hold a URL).
    A row with a credential in any string is refused outright; `_CREDENTIAL` lists the shapes
    that count as one, and a key named like one counts at any depth.
    """
    row = _context_document("--manifest-row", path)
    if not isinstance(row, dict):
        raise Refused(EXIT_USAGE, f"{PROG}: --manifest-row is not one JSON object")
    if _credential_keys(row) or any(_credential_string(s) for s in _strings(row)):
        raise Refused(
            EXIT_USAGE,
            f"{PROG}: --manifest-row carries a credential in a string; a manifest holds none, "
            "and the row is refused",
        )
    value = row.get("sha256")
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise Refused(EXIT_USAGE, f"{PROG}: --manifest-row states no sha256 of 64 hex digits")
    return value.lower()


def load_station_table(path: str) -> Any:
    from pydantic import ValidationError

    from synapse_cdm.observation_contracts import StationTable

    document = _context_document("--station-table", path)
    try:
        return StationTable.model_validate(document)
    except ValidationError:
        # Never the validation error's text: it quotes the input.
        raise Refused(
            EXIT_USAGE, f"{PROG}: --station-table is not a station table the contract accepts"
        ) from None


# -- containers ----------------------------------------------------------------------------------


def gunzip(data: bytes, limit: int) -> bytes:
    """The one gzip member `data` holds, inflated in bounded steps.

    The running total is held to `limit` and to `MAX_UNWRAP_RATIO` times the octets read before
    each step's output is kept; a header's own size field is not trusted. A second member, or
    any octet after the first, is refused: one stream is one payload.

    The input is fed in slices of `UNWRAP_CHUNK`, the `gzip` module's own pattern, and each step
    asks for at most `UNWRAP_CHUNK` octets out. Feeding the whole file at once would be one call
    too, but zlib hands back the input a step did not consume as a new `unconsumed_tail` object,
    so every step would copy the rest of the file: quadratic in the file bound (half a gigabyte
    of copying for an 8 MiB file, 2026-10-15). Fed in slices, no step copies more than one slice.
    """
    if data[:2] != b"\x1f\x8b":
        raise Refused(EXIT_REJECTED, f"{PROG}: the input is not a gzip stream")
    inflater = zlib.decompressobj(wbits=31)
    ceiling = min(limit, MAX_UNWRAP_RATIO * len(data))
    out, total, fed, pending = [], 0, 0, b""
    try:
        while True:
            if not pending and fed < len(data):
                pending = data[fed : fed + UNWRAP_CHUNK]
                fed += len(pending)
            # With `pending` empty and every octet fed, the call flushes what zlib still holds.
            chunk = inflater.decompress(pending, UNWRAP_CHUNK)
            total += len(chunk)
            if total > ceiling:
                raise Refused(
                    EXIT_REJECTED,
                    f"{PROG}: the gzip stream inflates past {ceiling} octets (the bound is "
                    f"{limit} octets and {MAX_UNWRAP_RATIO} times the {len(data)} read)",
                )
            out.append(chunk)
            pending = inflater.unconsumed_tail
            if inflater.eof:
                break
            if not chunk and not pending and fed == len(data):
                raise Refused(EXIT_REJECTED, f"{PROG}: the gzip stream is truncated")
    except zlib.error:
        raise Refused(EXIT_REJECTED, f"{PROG}: the gzip stream is corrupt") from None
    # Past the member's end, zlib keeps what remained of the last slice in `unused_data`; the
    # slices never fed are octets after the member too.
    if inflater.unused_data or fed < len(data):
        raise Refused(
            EXIT_REJECTED, f"{PROG}: octets follow the gzip member; one member is accepted"
        )
    return b"".join(out)


#: What `tarfile` raises, besides its own `TarError`, on a header it cannot parse (`untar`).
_TAR_HEADER_FAILURES = (ValueError, IndexError, OverflowError)
_CORRUPT_TAR = f"{PROG}: a tar header is corrupt or the archive is truncated"


def unsafe_member_name(name: str) -> bool:
    """Absolute, drive-qualified, NUL-bearing, or climbing out with `..`."""
    if not name or "\x00" in name or name.startswith(("/", "\\")):
        return True
    if re.match(r"[A-Za-z]:", name):
        return True
    return any(part == ".." for part in re.split(r"[/\\]", name))


def untar(data: bytes, member: str, limit: int) -> bytes:
    """The one regular member named `member` in the uncompressed tar archive `data`.

    Every header is walked (at most `MAX_TAR_MEMBERS`), and the archive is refused if any member
    name is absolute or climbs out with `..`, if the name is absent or appears twice, or if the
    member is not a regular file — a link, a directory, a device or a sparse file is never
    followed. Nothing is extracted to disk; the member is read in bounded steps.

    `tarfile` refuses most broken headers with its own `TarError`, but not all of them: a pax or
    GNU sparse record that is not the numbers it should be, an old GNU sparse header cut off
    before its extension block, or a size past what an index can hold reach parsing code below
    that net and raise `ValueError`, `IndexError` or `OverflowError` instead (Python 3.11 to
    3.14, 2026-10-15). Each is a header this host cannot read, so each is the corrupt-header
    refusal, wherever `tarfile` raises it; the host never needed a sparse record anyway.
    """
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.TarError:
        raise Refused(EXIT_REJECTED, f"{PROG}: the input is not a tar archive") from None
    except _TAR_HEADER_FAILURES:
        raise Refused(EXIT_REJECTED, _CORRUPT_TAR) from None
    found = []
    count = 0
    while True:
        try:
            info = archive.next()
        except (tarfile.TarError, *_TAR_HEADER_FAILURES):
            raise Refused(EXIT_REJECTED, _CORRUPT_TAR) from None
        if info is None:
            break
        count += 1
        if count > MAX_TAR_MEMBERS:
            raise Refused(
                EXIT_REJECTED, f"{PROG}: the archive holds more than {MAX_TAR_MEMBERS} members"
            )
        if unsafe_member_name(info.name):
            raise Refused(
                EXIT_REJECTED,
                f"{PROG}: the archive holds a member whose name is absolute or climbs out with ..",
            )
        if info.name == member:
            found.append(info)
    if not found:
        raise Refused(EXIT_REJECTED, f"{PROG}: --member names no member of the archive")
    if len(found) > 1:
        raise Refused(EXIT_REJECTED, f"{PROG}: --member names {len(found)} members of the archive")
    info = found[0]
    if not info.isreg() or info.issparse():
        raise Refused(EXIT_REJECTED, f"{PROG}: the named member is not a regular file")
    if info.size > limit:
        raise Refused(
            EXIT_REJECTED, f"{PROG}: the named member is {info.size} octets; the bound is {limit}"
        )
    out, total = [], 0
    try:
        stream = archive.extractfile(info)
        while True:
            chunk = stream.read(UNWRAP_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise Refused(EXIT_REJECTED, f"{PROG}: the named member exceeds {limit} octets")
            out.append(chunk)
    except (tarfile.TarError, *_TAR_HEADER_FAILURES):
        raise Refused(EXIT_REJECTED, f"{PROG}: the named member is truncated") from None
    if total != info.size:
        raise Refused(EXIT_REJECTED, f"{PROG}: the named member is truncated")
    return b"".join(out)


# -- the command ---------------------------------------------------------------------------------


def _diagnose(line: str) -> None:
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(line + "\n")
        stream.flush()
    except (OSError, ValueError, AttributeError):
        sys.stderr = None


def _emit(data: bytes) -> int:
    """Write `data` to stdout; a failed write is exit 4, never a traceback."""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        _diagnose(f"{PROG}: cannot write output: stdout is closed")
        return EXIT_IO
    try:
        stream.write(data)
        stream.flush()
        return EXIT_OK
    except (OSError, ValueError) as error:
        try:
            target = sys.stdout.fileno()
            fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(fd, target)
            finally:
                os.close(fd)
        except (OSError, ValueError, AttributeError):
            pass
        _diagnose(
            f"{PROG}: cannot write output: " + (getattr(error, "strerror", None) or "write failed")
        )
        return EXIT_IO


def _given(args: argparse.Namespace) -> set[str]:
    given = set()
    if args.at is not None or args.basis is not None:
        given.add("time")
    if args.session is not None:
        given.add("session")
    if args.received_at is not None:
        given.add("received_at")
    if args.station_table is not None:
        given.add("station_table")
    if args.request:
        given.add("request")
    return given


def _context(args: argparse.Namespace, hosted: Hosted) -> Context:
    """The flags, checked for form and against what the adapter declares. Exit 2 on any."""
    from synapse_cdm.observation_contracts import parse_instant

    given = _given(args)
    undeclared = sorted(given - hosted.arguments)
    if undeclared:
        raise Refused(
            EXIT_USAGE, f"{PROG}: {_FLAGS[undeclared[0]]} is not an argument {hosted.name} declares"
        )
    missing = sorted(hosted.required - given)
    if missing:
        raise Refused(EXIT_USAGE, f"{PROG}: {hosted.name} requires {_FLAGS[missing[0]]}")
    if hosted.reads_clock and args.received_at is None:
        raise Refused(EXIT_USAGE, f"{PROG}: {hosted.name} requires --received-at")
    if (args.at is None) != (args.basis is None):
        raise Refused(EXIT_USAGE, f"{PROG}: --at and --basis are given together")
    if args.at is not None:
        try:
            parse_instant(args.at)
        except ValueError:
            raise Refused(
                EXIT_USAGE, f"{PROG}: --at is not an RFC 3339 instant with seconds and a zone"
            ) from None
        if not args.basis.strip() or len(args.basis) > 1024:
            raise Refused(EXIT_USAGE, f"{PROG}: --basis is blank or longer than 1024 characters")
    received_at = None
    if args.received_at is not None:
        try:
            received_at = parse_instant(args.received_at)
        except ValueError:
            raise Refused(
                EXIT_USAGE,
                f"{PROG}: --received-at is not an RFC 3339 instant with seconds and a zone",
            ) from None
    request: list[tuple[str, str]] = []
    for item in args.request or ():
        key, sep, value = item.partition("=")
        if not sep or _REQUEST_KEY.fullmatch(key) is None or len(value) > MAX_REQUEST_VALUE:
            raise Refused(
                EXIT_USAGE,
                f"{PROG}: a --request is not KEY=VALUE with a lower-case key and a value of at "
                f"most {MAX_REQUEST_VALUE} characters",
            )
        if any(key == seen for seen, _ in request):
            raise Refused(EXIT_USAGE, f"{PROG}: a --request key is given twice")
        request.append((key, value))
    table = load_station_table(args.station_table) if args.station_table is not None else None
    return Context(
        synthetic=args.synthetic,
        at=args.at,
        basis=args.basis,
        session=args.session,
        received_at=received_at,
        station_table=table,
        request=tuple(request),
    )


def _no_clock() -> Any:
    raise RuntimeError(
        f"{PROG}: the adapter read the clock, and its host entry says it does not; the entry is "
        "wrong, and --received-at is how a hosted adapter that reads it is given an instant"
    )


def decode(args: argparse.Namespace) -> list[dict]:
    """Every object the frames of `--input` translate to, dumped, in frame order."""
    what = remote_locator(args.input)
    if what is not None:
        raise Refused(EXIT_USAGE, f"{PROG}: --input is {what}; only a local file is read")
    hosted = HOSTED.get(args.adapter)
    if hosted is None:
        raise Refused(
            EXIT_USAGE,
            f"{PROG}: --adapter names no adapter this host serves; `{PROG} list` prints them",
        )
    if (args.container == "tar") != (args.member is not None):
        raise Refused(EXIT_USAGE, f"{PROG}: --member is given with --container tar, and only then")
    if args.member is not None and unsafe_member_name(args.member):
        raise Refused(
            EXIT_USAGE, f"{PROG}: --member is absolute or climbs out with ..; it names a member"
        )
    expected = None
    if args.sha256 is not None:
        if _SHA256.fullmatch(args.sha256) is None:
            raise Refused(EXIT_USAGE, f"{PROG}: --sha256 is not 64 hexadecimal digits")
        expected = args.sha256.lower()
    elif args.manifest_row is not None:
        expected = manifest_sha256(args.manifest_row)
    context = _context(args, hosted)
    cls = hosted.load()
    try:
        kwargs = hosted.prepare(context)
    except ValueError:
        raise Refused(
            EXIT_USAGE, f"{PROG}: {hosted.name} refuses the context the flags describe"
        ) from None
    file_bound = hosted.max_file_bytes(cls)
    raw = _read_file("--input", args.input, file_bound)
    if len(raw) > file_bound:
        raise Refused(
            EXIT_REJECTED,
            f"{PROG}: --input is at least {len(raw)} octets; the bound for {hosted.name} is "
            f"{file_bound}",
        )
    from synapse_cdm import evidence

    digest = evidence.digest_bytes(raw)[0]
    if expected is not None and digest != expected:
        raise Refused(EXIT_REJECTED, f"{PROG}: the SHA-256 of --input is not the expected one")
    unwrapped_bound = hosted.max_unwrapped_bytes(cls)
    if args.container == "gzip":
        data = gunzip(raw, unwrapped_bound)
    elif args.container == "tar":
        data = untar(raw, args.member, unwrapped_bound)
    else:
        data = raw
    frames = hosted.framer(data)
    if hosted.frame_argument is None and len(frames) != 1:
        raise RuntimeError(
            f"{PROG}: {hosted.name} declares no frame argument and was framed "
            f"into {len(frames)} payloads"
        )
    clock = (lambda: context.received_at) if context.received_at is not None else _no_clock
    if hosted.injects_source_hash:
        kwargs = {**kwargs, "source_hash": {"algorithm": "sha256", "value": digest}}
    # The frame is not the file as read when a container was unwrapped or the file was cut.
    framed = args.container is not None or len(frames) != 1
    dumped: list[dict] = []
    offset = 0
    for index, frame in enumerate(frames):
        frame_kwargs = dict(kwargs)
        if hosted.frame_argument is not None:
            frame_kwargs[hosted.frame_argument] = index
        if hosted.frame_offset_argument is not None:
            frame_kwargs[hosted.frame_offset_argument] = offset
        offset += len(frame)
        if hosted.frame_digest_argument is not None and framed:
            frame_kwargs[hosted.frame_digest_argument] = evidence.digest_bytes(frame)[0]
        adapter = cls(clock, **frame_kwargs)
        try:
            objects = adapter.to_cdm(frame)
        except ValueError as error:
            raise Refused(
                EXIT_REJECTED,
                f"{PROG}: frame {index} refused by {hosted.name}: {type(error).__name__}",
            ) from None
        dumped += [o.model_dump(mode="json") for o in objects]
    return dumped


def _cmd_decode(args: argparse.Namespace) -> int:
    try:
        dumped = decode(args)
    except Refused as refusal:
        _diagnose(refusal.message)
        return refusal.status
    return _emit(canonical.serialise(dumped).encode("utf-8"))


def listing() -> str:
    """One line per hosted adapter: its arguments, whether the digest is injected, its bounds."""
    lines = []
    for name, hosted in HOSTED.items():
        cls = hosted.load()
        flags = (
            " ".join(
                _FLAGS[g] + ("" if g in hosted.required else "?") for g in sorted(hosted.arguments)
            )
            or "-"
        )
        frame = " frame_sha256 injected" if hosted.frame_digest_argument is not None else ""
        if hosted.frame_offset_argument is not None:
            frame += " framed by message"
        lines.append(
            f"{name} arguments {flags} source_hash "
            f"{'injected' if hosted.injects_source_hash else 'checked-only'}{frame} "
            f"file-bound {hosted.max_file_bytes(cls)} unwrapped-bound "
            f"{hosted.max_unwrapped_bytes(cls)}"
        )
    return "\n".join(lines) + "\n"


#: The argument parser's own refusals, by the English text of its messages (Python 3.11 to 3.14),
#: and the fixed words each is reported with. Its messages quote what was typed — an unknown flag
#: and its value, a choice that is not one, a value given to a switch — and a hand-typed command
#: line carries request parameters and keys, so the message itself is never printed.
_PARSER_ERRORS = (
    (re.compile(r"unrecognized arguments: "), "an argument is not one this command accepts"),
    (
        re.compile(r"argument \{decode,list\}: invalid choice: "),
        "the command is not decode or list",
    ),
    (re.compile(r"argument \S+: invalid choice: "), "a value is not one of its choices"),
    (
        re.compile(r"argument \S+: ignored explicit argument "),
        "a flag that takes no value is given one",
    ),
    (re.compile(r"argument \S+: expected one argument"), "a flag is given without its value"),
    (
        re.compile(r"argument \S+: not allowed with argument "),
        "two flags that exclude each other are given",
    ),
    (re.compile(r"one of the arguments .* is required"), "one of these flags is required"),
    (re.compile(r"the following arguments are required: "), "a required flag is missing"),
)
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def _parser_error_line(message: str, declared: frozenset[str]) -> str:
    """One fixed line for an argument-parser refusal: the class of the error, and the flags the
    message names that this command declares — never a word the operator typed otherwise."""
    what = "the command line is not one this command accepts"
    for pattern, words in _PARSER_ERRORS:
        if pattern.match(message):
            what = words
            break
    flags = list(dict.fromkeys(f for f in _FLAG.findall(message) if f in declared))
    named = f": {', '.join(flags)}" if flags else ""
    return f"{PROG}: {what}{named}; see {PROG} --help"


class _Parser(argparse.ArgumentParser):
    """stdout for the result, stderr for diagnostics, as `dis7_host._Parser` keeps them; an error
    is one fixed line (`_parser_error_line`), not argparse's usage and message."""

    def print_help(self, file=None):
        if file is None and sys.stdout is None:
            return
        super().print_help(file)

    def error(self, message):
        _diagnose(_parser_error_line(message, _declared_flags()))
        self.exit(EXIT_USAGE)


def _declared_flags() -> frozenset[str]:
    """Every option string the command and its subcommands declare."""
    found: set[str] = set()
    pending = [_parser()]
    while pending:
        parser = pending.pop()
        for action in parser._actions:
            found.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())
    return frozenset(found)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=PROG,
        allow_abbrev=False,
        description="Offline host command of the observation adapters: decode reads the one "
        "--input file and writes canonical JSON to stdout; it writes no file and opens no socket.",
    )
    parser.add_argument("--version", action="store_true", help="print the package version")
    commands = parser.add_subparsers(dest="command", metavar="{decode,list}")
    decode_ = commands.add_parser(
        "decode", allow_abbrev=False, help="one local file to a canonical JSON array"
    )
    decode_.add_argument("--adapter", required=True, help="a hosted adapter (see list)")
    decode_.add_argument("--input", required=True, help="the local file")
    group = decode_.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--synthetic",
        action="store_const",
        const=True,
        dest="synthetic",
        help="classify the data as synthetic",
    )
    group.add_argument(
        "--live",
        action="store_const",
        const=False,
        dest="synthetic",
        help="classify the data as live; this only sets the canonical flag",
    )
    expected = decode_.add_mutually_exclusive_group()
    expected.add_argument("--sha256", help="the SHA-256 the file must have")
    expected.add_argument("--manifest-row", help="a JSON object whose sha256 the file must have")
    decode_.add_argument("--container", choices=("gzip", "tar"), help="unwrap the file first")
    decode_.add_argument("--member", help="the tar member to take (with --container tar)")
    decode_.add_argument("--at", help="a time context or as-of instant, RFC 3339 with a zone")
    decode_.add_argument("--basis", help="how --at was resolved; write --basis=VALUE for -VALUE")
    decode_.add_argument("--session", help="the session name, for an adapter that declares one")
    decode_.add_argument("--received-at", help="the receipt instant, for an adapter that reads it")
    decode_.add_argument("--station-table", help="a station table JSON file")
    decode_.add_argument("--request", action="append", help="a request parameter, KEY=VALUE")
    commands.add_parser("list", allow_abbrev=False, help="the hosted adapters and their bounds")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        if stop.code != 0:
            try:
                if sys.stderr is not None:
                    sys.stderr.flush()
            except (OSError, ValueError):
                sys.stderr = None
            raise
        if sys.stdout is None:
            _diagnose(f"{PROG}: cannot write output: stdout is closed")
            return EXIT_IO
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            sys.stdout = None
            _diagnose(f"{PROG}: cannot write output: write failed")
            return EXIT_IO
        raise
    if not args.version and args.command is None:
        _diagnose(f"{PROG}: a command is required: decode or list; see {PROG} --help")
        return EXIT_USAGE
    if args.version:
        hosted = " ".join(HOSTED)
        return _emit(f"{PROG} synapse-cdm {PACKAGE_VERSION}\nhosted {hosted}\n".encode("utf-8"))
    if args.command == "list":
        return _emit(listing().encode("utf-8"))
    return _cmd_decode(args)


if __name__ == "__main__":
    raise SystemExit(main())
