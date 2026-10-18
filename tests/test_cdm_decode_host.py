"""The offline host command `synapse-decode` (`synapse_cdm.decode_host`).

Every exit code and every refusal the module's docstring lists is bound here by a literal: the
status, the one stderr line, and an empty stdout. The command is driven as a child process
(`python -m synapse_cdm.decode_host`, the package the parent imported on `PYTHONPATH`) where the
process boundary is the subject — exit codes, a FIFO, the entry point — and in process where a
test needs a hosted adapter the roster does not have: a double, put in `decode_host.HOSTED` for
the test, exercises the station table, request parameters, the receipt clock and a framer.

Package-only: the inputs are the DIS 7 vectors the wheel carries, read through
`synapse_cdm.__file__`, and files this module writes under `tmp_path` from literals. Containers
are built with the standard library's `gzip` and `tarfile`, digests with `hashlib`; the expected
objects for `dis7` are the handoff's own `expected.json` vectors, which the host's output must
equal but for the `source_hash` it injects.
"""

import datetime as dt
import errno
import gzip
import hashlib
import io
import json
import os
import pathlib
import struct
import subprocess
import sys
import tarfile
import types
import uuid
import zlib

import pytest

import synapse_cdm
from synapse_cdm import decode_host
from synapse_cdm.enums import EventType, Severity
from synapse_cdm.manifest import LimitBasis, LimitKind
from synapse_cdm.models import Event, SourceId, SourceRef
from synapse_cdm.version import PACKAGE_VERSION

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
VECTORS = PKG / "fixtures" / "dis7" / "vectors"
ENV = {**os.environ, "PYTHONPATH": str(PKG.parent), "PYTHONDONTWRITEBYTECODE": "1"}
EQUATOR = VECTORS / "equator_eastbound.dis"
EQUATOR_SHA256 = "c958233bda22e82385788584e0297d0e264ee2a0db94dc32838141925155ef1a"
CONTEXT = [
    "--at",
    "2026-04-29T06:15:00.000Z",
    "--basis",
    "Synthetic fixture scenario instant; not capture time",
    "--session",
    "unnamed",
]
DIS7 = ["decode", "--adapter", "dis7", "--synthetic", *CONTEXT]
GEOJSON = ["decode", "--adapter", "geojson", "--synthetic"]
AS_OF = ["--at", "2026-09-11T10:00:00Z", "--basis", "dataset publication date, stated by hand"]
FEATURE = b'{"type":"Feature","id":"ex-1","geometry":null,"properties":{"name":"buoy"}}'
SECRET = "SECRETVALUE"


def _cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "synapse_cdm.decode_host", *args],
        capture_output=True,
        timeout=60,
        cwd=cwd,
        env=ENV,
    )


def _write(path: pathlib.Path, data: bytes) -> str:
    path.write_bytes(data)
    return str(path)


def _refused(result, status: int, line: str):
    assert result.returncode == status, result.stderr
    assert result.stdout == b""
    assert result.stderr == (line + "\n").encode("utf-8")


def _accepted(result) -> list:
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    return json.loads(result.stdout)


def _expected_equator(source_hash: str) -> list:
    """The handoff's expected Entity, with the digest the host injects in the two places the
    `dis7` adapter records an injected `source_hash`: the provenance stamp and its residual."""
    expected = json.loads((VECTORS / "equator_eastbound.expected.json").read_text())
    stated = {"algorithm": "sha256", "value": source_hash}
    assert expected[0]["source"]["source_hash"] is None
    assert expected[0]["residual"]["data"]["source_hash"] is None
    expected[0]["source"]["source_hash"] = stated
    expected[0]["residual"]["data"]["source_hash"] = stated
    return expected


# -- exit 0 --------------------------------------------------------------------------------------


def test_a_dis7_vector_decodes_to_its_expected_entity_with_the_files_digest_injected():
    result = _cli(*DIS7, "--input", str(EQUATOR))
    assert hashlib.sha256(EQUATOR.read_bytes()).hexdigest() == EQUATOR_SHA256
    assert _accepted(result) == _expected_equator(EQUATOR_SHA256)


def test_the_output_is_byte_identical_to_synapse_dis7_and_to_a_second_run():
    first = _cli(*DIS7, "--input", str(EQUATOR))
    second = _cli(*DIS7, "--input", str(EQUATOR))
    reference = subprocess.run(
        [
            sys.executable,
            "-m",
            "synapse_cdm.dis7_host",
            "decode",
            "--input",
            str(EQUATOR),
            *CONTEXT,
            "--synthetic",
        ],
        capture_output=True,
        timeout=60,
        env=ENV,
    )
    assert reference.returncode == 0, reference.stderr
    assert first.stdout == second.stdout == reference.stdout


@pytest.mark.parametrize(
    "spelling", [EQUATOR_SHA256, EQUATOR_SHA256.upper()], ids=["lower", "upper"]
)
def test_an_expected_digest_that_matches_is_accepted_in_either_case(spelling):
    assert _accepted(
        _cli(*DIS7, "--input", str(EQUATOR), "--sha256", spelling)
    ) == _expected_equator(EQUATOR_SHA256)


def test_a_manifest_row_supplies_the_expected_digest_and_nothing_else(tmp_path):
    row = {
        "sha256": EQUATOR_SHA256,
        "source name": "synthetic",
        "format": "dis",
        "acquisition interval": "2026-09-11T00:00Z/2026-09-12T00:00Z",
        "full download URL or query": "https://example.invalid/vectors/equator?format=dis",
    }
    path = _write(tmp_path / "row.json", json.dumps(row).encode())
    assert _accepted(
        _cli(*DIS7, "--input", str(EQUATOR), "--manifest-row", path)
    ) == _expected_equator(EQUATOR_SHA256)


def test_an_as_of_reaches_geojson_and_the_output_is_what_the_adapter_makes_of_those_values(
    tmp_path,
):
    from synapse_cdm.adapters.geojson import AsOf, GeojsonAdapter

    result = _accepted(_cli(*GEOJSON, *AS_OF, "--input", _write(tmp_path / "f.json", FEATURE)))
    assert len(result) == 1
    entity = result[0]
    assert (entity["object_kind"], entity["entity_type"], entity["position"]) == (
        "entity",
        "OVERLAY_OBJECT",
        None,
    )
    assert entity["valid_from"] == "2026-09-11T10:00:00.000Z"
    assert entity["source"]["source_hash"] is None
    assert entity["source"]["transformations"] == [
        "valid_from: the caller's as-of context — dataset publication date, stated by hand"
    ]
    adapter = GeojsonAdapter(
        synthetic=True,
        as_of=AsOf(
            dt.datetime(2026, 9, 11, 10, tzinfo=dt.timezone.utc),
            "dataset publication date, stated by hand",
        ),
    )
    assert result == [o.model_dump(mode="json") for o in adapter.to_cdm(FEATURE)]


def test_list_and_version_state_the_hosted_adapters():
    listed = _cli("list")
    assert listed.returncode == 0 and listed.stderr == b""
    assert listed.stdout == (
        b"dis7 arguments --session --at/--basis source_hash injected file-bound 4224 "
        b"unwrapped-bound 4224\n"
        b"geojson arguments --at/--basis? source_hash checked-only file-bound 8388608 "
        b"unwrapped-bound 8388608\n"
        b"readsb_trace arguments --received-at source_hash checked-only file-bound 8388608 "
        b"unwrapped-bound 8388608\n"
        b"nexrad2 arguments --received-at source_hash injected frame_sha256 injected "
        b"file-bound 33554432 unwrapped-bound 33554432\n"
        b"ndbc_stdmet arguments --received-at --request --station-table? source_hash injected "
        b"frame_sha256 injected file-bound 8388608 unwrapped-bound 8388608\n"
        b"coops_csv arguments --received-at --request --station-table? source_hash injected "
        b"frame_sha256 injected file-bound 8388608 unwrapped-bound 8388608\n"
        b"airnow_hourly arguments --received-at --station-table? source_hash injected "
        b"frame_sha256 injected file-bound 8388608 unwrapped-bound 8388608\n"
        b"grib2 arguments --received-at source_hash injected frame_sha256 injected framed by "
        b"message file-bound 8388608 unwrapped-bound 8388608\n"
        b"cog arguments --received-at --request? --at/--basis? source_hash injected "
        b"file-bound 268435456 unwrapped-bound 268435456\n"
        b"iem_n0q arguments --received-at --at/--basis source_hash injected frame_sha256 "
        b"injected file-bound 8388608 unwrapped-bound 8388608\n"
    )
    version = _cli("--version")
    assert version.returncode == 0 and version.stderr == b""
    assert (
        version.stdout
        == (
            f"synapse-decode synapse-cdm {PACKAGE_VERSION}\n"
            "hosted dis7 geojson readsb_trace nexrad2 ndbc_stdmet coops_csv airnow_hourly grib2 "
            "cog iem_n0q\n"
        ).encode()
    )


# -- exit 2: usage and context -------------------------------------------------------------------

REMOTE = [
    ("/vsicurl/https://example.invalid/a.tif", "a GDAL /vsicurl/ path"),
    ("/VSICURL_STREAMING/https://example.invalid/a.tif", "a GDAL /vsicurl/ path"),
    ("/vsis3/bucket/a.tif", "a GDAL virtual file system path"),
    (f"https://example.invalid/a.json?api_key={SECRET}", "an http(s):// URL"),
    ("http://example.invalid/a.json", "an http(s):// URL"),
    ("s3://bucket/key.grib2", "an s3:// locator"),
    ("dods://example.invalid/dodsC/x", "a DAP locator"),
    ("dap4://example.invalid/x", "a DAP locator"),
    ("[fillmismatch]https://example.invalid/dodsC/x", "a DAP locator"),
    ("file:///tmp/x.json", "a URL"),
    # Not at the start: a GDAL driver prefix, quotes, padding or a path in front of the locator.
    ("NETCDF:/vsicurl/https://example.invalid/a.nc", "a GDAL /vsicurl/ path"),
    ('HDF5:"/vsicurl/https://example.invalid/a.h5"', "a GDAL /vsicurl/ path"),
    ("x/vsicurl/y", "a GDAL /vsicurl/ path"),
    ("GTIFF_DIR:1:/vsis3/bucket/a.tif", "a GDAL virtual file system path"),
    ('NETCDF:"https://example.invalid/a.nc":var', "an http(s):// URL"),
    (" https://example.invalid/a.json", "an http(s):// URL"),
    ('NETCDF:"s3://bucket/a.nc":var', "an s3:// locator"),
    ('NETCDF:"dap4://example.invalid/x":var', "a DAP locator"),
    ('NETCDF:"[fillmismatch]https://example.invalid/dodsC/x":var', "a DAP locator"),
    ('HDF5:"file:///tmp/x.h5"', "a URL"),
]


@pytest.mark.parametrize("argument, what", REMOTE, ids=[w for w, _ in REMOTE])
def test_a_remote_locator_is_refused_by_name_before_anything_is_read(argument, what):
    result = _cli(*GEOJSON, "--input", argument)
    _refused(result, 2, f"synapse-decode: --input is {what}; only a local file is read")
    assert SECRET.encode() not in result.stderr


def test_a_remote_context_file_is_refused_the_same_way(tmp_path):
    feature = _write(tmp_path / "f.json", FEATURE)
    _refused(
        _cli(*GEOJSON, "--input", feature, "--manifest-row", "s3://bucket/row.json"),
        2,
        "synapse-decode: --manifest-row is an s3:// locator; only a local file is read",
    )


@pytest.mark.parametrize(
    "extra, line",
    [
        (["--sha256", "c958"], "synapse-decode: --sha256 is not 64 hexadecimal digits"),
        (["--sha256", "g" * 64], "synapse-decode: --sha256 is not 64 hexadecimal digits"),
        (["--session", "x"], "synapse-decode: --session is not an argument geojson declares"),
        (
            ["--received-at", "2026-09-11T10:00:00Z"],
            "synapse-decode: --received-at is not an argument geojson declares",
        ),
        (
            ["--station-table", "t.json"],
            "synapse-decode: --station-table is not an argument geojson declares",
        ),
        (
            [f"--request=api_key={SECRET}"],
            "synapse-decode: --request is not an argument geojson declares",
        ),
        (["--at", "2026-09-11T10:00:00Z"], "synapse-decode: --at and --basis are given together"),
        (
            ["--at", "2026-09-11T10:00:00", "--basis", "a stated basis"],
            "synapse-decode: --at is not an RFC 3339 instant with seconds and a zone",
        ),
        (
            ["--at", "2026-09-11T10:00:00Z", "--basis", "   "],
            "synapse-decode: --basis is blank or longer than 1024 characters",
        ),
        (
            ["--at", "2026-09-11T10:00:00Z", "--basis", "short"],
            "synapse-decode: geojson refuses the context the flags describe",
        ),
        (
            ["--container", "tar"],
            "synapse-decode: --member is given with --container tar, and only then",
        ),
        (
            ["--member", "a.json"],
            "synapse-decode: --member is given with --container tar, and only then",
        ),
        (
            ["--container", "tar", "--member", "../a.json"],
            "synapse-decode: --member is absolute or climbs out with ..; it names a member",
        ),
        (
            ["--container", "tar", "--member", "/a.json"],
            "synapse-decode: --member is absolute or climbs out with ..; it names a member",
        ),
    ],
    ids=[
        "short-digest",
        "non-hex-digest",
        "undeclared-session",
        "undeclared-received-at",
        "undeclared-station-table",
        "undeclared-request",
        "at-without-basis",
        "naive-at",
        "blank-basis",
        "basis-geojson-refuses",
        "tar-without-member",
        "member-without-tar",
        "climbing-member",
        "absolute-member",
    ],
)
def test_a_flag_the_adapter_does_not_declare_or_a_malformed_value_is_exit_2(tmp_path, extra, line):
    result = _cli(*GEOJSON, "--input", _write(tmp_path / "f.json", FEATURE), *extra)
    _refused(result, 2, line)
    assert SECRET.encode() not in result.stderr


#: Four instants the grammar admits, each a real local time, whose UTC reading falls a day (or a
#: minute) outside the years 0001 to 9999: +14:00 and +00:01 at the first instant move it back,
#: -14:00 and -00:01 at the last move it forward (checkpoint finding H-02, 2026-10-15).
INSTANTS_PAST_UTC = [
    "0001-01-01T00:00:00+14:00",
    "0001-01-01T00:00:00+00:01",
    "9999-12-31T23:59:59-14:00",
    "9999-12-31T23:59:59.999999-00:01",
]


@pytest.mark.parametrize("instant", INSTANTS_PAST_UTC)
def test_an_instant_utc_cannot_state_is_exit_2_on_its_own_flag_and_never_a_traceback(
    tmp_path, instant
):
    feature = _write(tmp_path / "f.json", FEATURE)
    _refused(
        _cli(*GEOJSON, "--input", feature, "--at", instant, "--basis", "a stated basis"),
        2,
        "synapse-decode: --at is not an RFC 3339 instant with seconds and a zone",
    )
    _refused(
        _cli(*READSB_DECODE, "--input", str(READSB_FILE), "--received-at", instant),
        2,
        "synapse-decode: --received-at is not an RFC 3339 instant with seconds and a zone",
    )


@pytest.mark.parametrize(
    "drop, line",
    [
        ("--session", "synapse-decode: dis7 requires --session"),
        ("--at", "synapse-decode: dis7 requires --at/--basis"),
    ],
)
def test_a_declared_argument_the_adapter_requires_is_exit_2_when_missing(drop, line):
    flags = list(CONTEXT)
    index = flags.index(drop)
    del flags[index : index + 2]
    if drop == "--at":
        index = flags.index("--basis")
        del flags[index : index + 2]
    _refused(
        _cli("decode", "--adapter", "dis7", "--synthetic", *flags, "--input", str(EQUATOR)), 2, line
    )


def test_a_session_dis7_refuses_and_an_unknown_adapter_are_exit_2():
    flags = [f if f != "unnamed" else "has space" for f in CONTEXT]
    _refused(
        _cli("decode", "--adapter", "dis7", "--synthetic", *flags, "--input", str(EQUATOR)),
        2,
        "synapse-decode: dis7 refuses the context the flags describe",
    )
    _refused(
        _cli("decode", "--adapter", f"tak{SECRET}", "--synthetic", "--input", str(EQUATOR)),
        2,
        "synapse-decode: --adapter names no adapter this host serves; "
        "`synapse-decode list` prints them",
    )


def test_the_classification_is_required_and_is_one_of_the_two():
    _refused(
        _cli("decode", "--adapter", "geojson", "--input", str(EQUATOR)),
        2,
        "synapse-decode: one of these flags is required: --synthetic, --live; "
        "see synapse-decode --help",
    )
    _refused(
        _cli(*GEOJSON, "--live", "--input", str(EQUATOR)),
        2,
        "synapse-decode: two flags that exclude each other are given: --live, --synthetic; "
        "see synapse-decode --help",
    )
    _refused(
        _cli(),
        2,
        "synapse-decode: a command is required: decode or list; see synapse-decode --help",
    )


#: Command lines the argument parser itself refuses. Its own messages quote what was typed (an
#: unknown flag and its value, a choice that is not one), so each is replaced by one fixed line
#: naming the class of the error and only flags the command declares.
PARSER_REFUSALS = [
    (
        ["--requests", f"api_key={SECRET}"],
        "synapse-decode: an argument is not one this command accepts; see synapse-decode --help",
    ),
    (
        [f"--api_key={SECRET}"],
        "synapse-decode: an argument is not one this command accepts; see synapse-decode --help",
    ),
    (
        [SECRET],
        "synapse-decode: an argument is not one this command accepts; see synapse-decode --help",
    ),
    (
        ["--container", SECRET],
        "synapse-decode: a value is not one of its choices: --container; see synapse-decode --help",
    ),
    (
        [f"--container={SECRET}"],
        "synapse-decode: a value is not one of its choices: --container; see synapse-decode --help",
    ),
    (
        [f"--synthetic={SECRET}"],
        "synapse-decode: a flag that takes no value is given one: --synthetic; "
        "see synapse-decode --help",
    ),
    (
        ["--at"],
        "synapse-decode: a flag is given without its value: --at; see synapse-decode --help",
    ),
    (
        ["--sha256", "0" * 64, "--manifest-row", "row.json"],
        "synapse-decode: two flags that exclude each other are given: --manifest-row, --sha256; "
        "see synapse-decode --help",
    ),
]


@pytest.mark.parametrize(
    "extra, line",
    PARSER_REFUSALS,
    ids=[
        "misspelt-request",
        "unknown-flag-with-value",
        "stray-positional",
        "container-choice",
        "container-choice-joined",
        "value-on-a-switch",
        "flag-without-value",
        "exclusive-pair",
    ],
)
def test_a_command_line_the_parser_refuses_is_one_fixed_line_that_quotes_nothing_typed(extra, line):
    result = _cli(*GEOJSON, "--input", str(EQUATOR), *extra)
    _refused(result, 2, line)
    assert SECRET.encode() not in result.stderr


def test_a_missing_required_flag_and_an_unknown_command_are_fixed_lines_too():
    _refused(
        _cli("decode", "--input", str(EQUATOR), "--synthetic"),
        2,
        "synapse-decode: a required flag is missing: --adapter; see synapse-decode --help",
    )
    result = _cli(f"decode{SECRET}")
    _refused(
        result, 2, "synapse-decode: the command is not decode or list; see synapse-decode --help"
    )
    assert SECRET.encode() not in result.stderr
    result = _cli("list", f"--{SECRET}")
    _refused(
        result,
        2,
        "synapse-decode: an argument is not one this command accepts; see synapse-decode --help",
    )
    assert SECRET.encode() not in result.stderr


@pytest.mark.parametrize(
    "content, line",
    [
        (b"[]", "synapse-decode: --manifest-row is not one JSON object"),
        (b'{"format": "dis"}', "synapse-decode: --manifest-row states no sha256 of 64 hex digits"),
        (b'{"sha256": 7}', "synapse-decode: --manifest-row states no sha256 of 64 hex digits"),
        (
            b'{"sha256": "a", "sha256": "b"}',
            "synapse-decode: --manifest-row is not a strict JSON document",
        ),
        (b'{"sha256": NaN}', "synapse-decode: --manifest-row is not a strict JSON document"),
        (b'{"sha256": ', "synapse-decode: --manifest-row is not a strict JSON document"),
        (b"\xef\xbb\xbf{}", "synapse-decode: --manifest-row is not a strict JSON document"),
        (b'{"a": "\xff"}', "synapse-decode: --manifest-row is not UTF-8"),
        (b"[" * 17 + b"]" * 17, "synapse-decode: --manifest-row is not a strict JSON document"),
        (
            json.dumps(
                {"sha256": EQUATOR_SHA256, "url": f"https://example.invalid/x?API_KEY={SECRET}"}
            ).encode(),
            "synapse-decode: --manifest-row carries a credential in a string; a manifest holds "
            "none, and the row is refused",
        ),
        (
            json.dumps(
                {"sha256": EQUATOR_SHA256, "url": f"https://user:{SECRET}@example.invalid/x"}
            ).encode(),
            "synapse-decode: --manifest-row carries a credential in a string; a manifest holds "
            "none, and the row is refused",
        ),
        (
            json.dumps({"sha256": EQUATOR_SHA256, "headers": {"Token": SECRET}}).encode(),
            "synapse-decode: --manifest-row carries a credential in a string; a manifest holds "
            "none, and the row is refused",
        ),
    ],
    ids=[
        "array",
        "no-digest",
        "number-digest",
        "repeated-key",
        "nan",
        "truncated",
        "bom",
        "not-utf8",
        "too-deep",
        "key-in-query",
        "password-in-url",
        "token-key",
    ],
)
def test_a_manifest_row_is_one_strict_object_with_a_digest_and_no_credential(
    tmp_path, content, line
):
    path = _write(tmp_path / "row.json", content)
    result = _cli(*DIS7, "--input", str(EQUATOR), "--manifest-row", path)
    _refused(result, 2, line)
    assert SECRET.encode() not in result.stderr
    assert b"example.invalid" not in result.stderr


def test_a_manifest_row_past_its_bound_is_exit_2(tmp_path):
    padded = b'{"sha256": "' + EQUATOR_SHA256.encode() + b'", "pad": "' + b"x" * 1048576 + b'"}'
    _refused(
        _cli(
            *DIS7, "--input", str(EQUATOR), "--manifest-row", _write(tmp_path / "row.json", padded)
        ),
        2,
        "synapse-decode: --manifest-row is more than 1048576 octets",
    )


#: Strings shaped to make a backtracking credential pattern quadratic: a long run the pattern can
#: split at every position and that ends without the octet it needs. Each fills a row to just under
#: the 1 MiB bound; none is a credential, so the row reaches the digest comparison.
HOSTILE_ROW_STRINGS = {
    "userinfo-colons": lambda n: "://" + "a:" * (n // 2),
    "userinfo-only-colons": lambda n: "://" + ":" * n,
    "user-then-colons": lambda n: "://a" + ":" * n,
    "name-then-spaces": lambda n: "token" + " " * n,
    "bearer-then-spaces": lambda n: "bearer" + " " * n,
    "query-name-run": lambda n: "?" + "a" * n,
    "query-name-runs": lambda n: "&a" * (n // 2),
    # Since 2026-10-15 a string holding `%` is matched again with its escapes decoded.
    "percent-signs": lambda n: "%" * n,
    "escaped-percent-signs": lambda n: "%25" * (n // 3),
    "escaped-query-name-run": lambda n: "?" + "%61" * (n // 3),
    "header-prefixes": lambda n: "x-" * (n // 2),
}


@pytest.mark.parametrize("shape", sorted(HOSTILE_ROW_STRINGS))
def test_the_credential_check_is_linear_in_the_size_of_a_row_at_its_bound(tmp_path, shape):
    head = b'{"sha256": "' + b"0" * 64 + b'", "note": "'
    room = 1048576 - len(head) - len(b'"}')
    note = HOSTILE_ROW_STRINGS[shape](room - 8).encode()
    row = head + note + b'"}'
    assert 1048576 - 16 <= len(row) <= 1048576
    # `_cli` gives the child 60 seconds; a pattern that backtracks over every split of a
    # megabyte does not finish in that, and the test then fails with the timeout.
    _refused(
        _cli(*DIS7, "--input", str(EQUATOR), "--manifest-row", _write(tmp_path / "row.json", row)),
        3,
        "synapse-decode: the SHA-256 of --input is not the expected one",
    )


CREDENTIAL_SHAPES = [
    f"curl -H 'Authorization: Bearer {SECRET}0123'",
    f"Authorization=Bearer {SECRET}",
    f"bearer {SECRET}",
    f"https://example.invalid/a?key={SECRET}",
    f"https://example.invalid/a?sig={SECRET}",
    f"https://example.invalid/a?x=1&subscription-key={SECRET}",
    f"https://example.invalid/a?X-Amz-Signature={SECRET}",
    f"https://:{SECRET}@example.invalid/a",
    f"https://user:{SECRET}@example.invalid/a",
    f"https://example.invalid/a?auth_token={SECRET}",
    # 2026-10-15 (checkpoint H-06): a cookie header, and a parameter name spelled with `%xx`.
    f"Cookie: session={SECRET}",
    f"set-cookie : id={SECRET}",
    f"https://example.invalid/a?api%5Fkey={SECRET}",
    f"https://example.invalid/a?%61pi_key={SECRET}",
    f"https://example.invalid/a?x=1%26sig%3D{SECRET}",
]


#: Keys that name a credential, at any depth of a row, and why each is one since 2026-10-15: an
#: HTTP header's `x-` prefix (H-06), `auth-token` as a name of its own, the two cookie headers,
#: and a key spelled with `%xx` escapes.
CREDENTIAL_KEYS = [
    "x-api-key",
    "X-Auth-Token",
    "auth_token",
    "x-token",
    "Cookie",
    "set-cookie",
    "api%5Fkey",
    "%74oken",
    # a later reading the same day (R1b review N-1): the names providers spell their own way
    "x-amz-signature",
    "X-Amz-Security-Token",
    "x_api_key",
    "x-api-token",
    "x-goog-api-key",
    "Proxy-Authorization",
    "set_cookie",
]


@pytest.mark.parametrize("key", CREDENTIAL_KEYS)
def test_each_named_credential_key_refuses_the_row_without_quoting_it(tmp_path, key):
    row = json.dumps({"sha256": EQUATOR_SHA256, "headers": {key: SECRET}}).encode()
    result = _cli(
        *DIS7, "--input", str(EQUATOR), "--manifest-row", _write(tmp_path / "r.json", row)
    )
    _refused(
        result,
        2,
        "synapse-decode: --manifest-row carries a credential in a string; a manifest holds none, "
        "and the row is refused",
    )
    assert SECRET.encode() not in result.stderr


@pytest.mark.parametrize(
    "row",
    [
        {"key": "traces/2026/09/11/a.json"},
        {"x-key": "traces/a.json"},
        {"note": "%6Bey=traces/a.json"},
        {"url": "https://example.invalid/a?format=json%26station%3DEX001"},
        {"cookies-policy": "none"},
        {"x-amz-date": "20260911T100000Z"},
        {"proxy-host": "relay.example.invalid"},
        {"x_goog_project": "none"},
    ],
    ids=[
        "key",
        "x-key",
        "escaped-key-without-query",
        "escaped-query",
        "cookies-policy",
        "x-amz-date",
        "proxy-host",
        "x_goog_project",
    ],
)
def test_a_bare_key_and_a_name_that_only_resembles_one_still_reach_the_digest(tmp_path, row):
    document = json.dumps({"sha256": EQUATOR_SHA256, **row}).encode()
    result = _cli(
        *DIS7, "--input", str(EQUATOR), "--manifest-row", _write(tmp_path / "r.json", document)
    )
    assert _accepted(result) == _expected_equator(EQUATOR_SHA256)


@pytest.mark.parametrize("text", CREDENTIAL_SHAPES)
def test_each_named_credential_shape_refuses_the_row_without_quoting_it(tmp_path, text):
    row = json.dumps({"sha256": EQUATOR_SHA256, "url": text}).encode()
    result = _cli(
        *DIS7, "--input", str(EQUATOR), "--manifest-row", _write(tmp_path / "r.json", row)
    )
    _refused(
        result,
        2,
        "synapse-decode: --manifest-row carries a credential in a string; a manifest holds none, "
        "and the row is refused",
    )
    assert SECRET.encode() not in result.stderr


@pytest.mark.parametrize(
    "text",
    [
        "https://example.invalid/data/2026/09/11/a.json?format=json&station=EX001",
        "s3://bucket/key.grib2",
        "the bearer of this note",
        "keyed by station",
    ],
)
def test_a_row_without_a_credential_shape_reaches_the_digest(tmp_path, text):
    row = json.dumps({"sha256": EQUATOR_SHA256, "url": text}).encode()
    result = _cli(
        *DIS7, "--input", str(EQUATOR), "--manifest-row", _write(tmp_path / "r.json", row)
    )
    assert _accepted(result) == _expected_equator(EQUATOR_SHA256)


# -- exit 3: rejected data -----------------------------------------------------------------------


def test_a_digest_that_differs_is_exit_3_whether_given_or_read_from_the_row(tmp_path):
    other = "0" * 64
    line = "synapse-decode: the SHA-256 of --input is not the expected one"
    _refused(_cli(*DIS7, "--input", str(EQUATOR), "--sha256", other), 3, line)
    row = _write(tmp_path / "row.json", json.dumps({"sha256": other}).encode())
    _refused(_cli(*DIS7, "--input", str(EQUATOR), "--manifest-row", row), 3, line)


def test_a_file_past_the_adapters_bound_is_refused_before_it_is_interpreted(tmp_path):
    _refused(
        _cli(*DIS7, "--input", _write(tmp_path / "big.dis", bytes(4225))),
        3,
        "synapse-decode: --input is at least 4225 octets; the bound for dis7 is 4224",
    )


def test_a_frame_the_adapter_refuses_is_exit_3_and_names_only_the_class(tmp_path):
    truncated = EQUATOR.read_bytes()[:143]
    _refused(
        _cli(*DIS7, "--input", _write(tmp_path / "t.dis", truncated)),
        3,
        "synapse-decode: frame 0 refused by dis7: Dis7Error",
    )
    hostile = b'{"type":"Feature","id":"' + SECRET.encode() + b'","geometry":null}'
    result = _cli(*GEOJSON, "--input", _write(tmp_path / "f.json", hostile))
    _refused(result, 3, "synapse-decode: frame 0 refused by geojson: ValueError")
    assert SECRET.encode() not in result.stderr


# -- readsb_trace: the adapter inflates its own gzip member; the host hands the file over -------

READSB = PKG / "fixtures" / "readsb_trace"
READSB_FILE = READSB / "mlat_positions.trace"
READSB_DECODE = ["decode", "--adapter", "readsb_trace", "--synthetic"]
READSB_RECEIVED = "2026-03-15T06:00:00Z"


def _readsb_in_process(octets: bytes) -> list:
    from synapse_cdm.adapters.readsb_trace import ReadsbTraceAdapter

    clock = lambda: dt.datetime(2026, 3, 15, 6, 0, tzinfo=dt.timezone.utc)  # noqa: E731
    return [o.model_dump(mode="json") for o in ReadsbTraceAdapter(clock).to_cdm(octets)]


def test_a_readsb_trace_file_decodes_with_the_receipt_instant_it_is_given():
    octets = READSB_FILE.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    result = _accepted(
        _cli(
            *READSB_DECODE,
            "--input",
            str(READSB_FILE),
            "--received-at",
            READSB_RECEIVED,
            "--sha256",
            digest,
        )
    )
    assert [o["object_kind"] for o in result] == ["entity", "track", "event"]
    assert result[2]["received_at"] == "2026-03-15T06:00:00.000Z"
    assert result[2]["observed_at"] == "2026-03-14T12:00:15.750Z"
    # checked-only: the digest is compared with --sha256 and never stamped on the output
    assert all(o["source"]["source_hash"] is None for o in result)
    assert result == _readsb_in_process(octets)


def test_a_readsb_trace_inside_a_day_archive_is_taken_by_its_member_name(tmp_path):
    member = "2026/03/14/traces/e3/trace_full_0029e3.json"
    archive = _tar([(member, READSB_FILE.read_bytes(), tarfile.REGTYPE)])
    result = _accepted(
        _cli(
            *READSB_DECODE,
            "--input",
            _write(tmp_path / "day.tar", archive),
            "--container",
            "tar",
            "--member",
            member,
            "--received-at",
            READSB_RECEIVED,
        )
    )
    assert result == _readsb_in_process(READSB_FILE.read_bytes())


def test_readsb_trace_requires_its_receipt_instant_and_refuses_a_malformed_trace_by_class():
    _refused(
        _cli(*READSB_DECODE, "--input", str(READSB_FILE)),
        2,
        "synapse-decode: readsb_trace requires --received-at",
    )
    _refused(
        _cli(
            *READSB_DECODE,
            "--input",
            str(READSB_FILE),
            "--at",
            "2026-03-14T00:00:00Z",
            "--basis",
            "a time context the adapter does not declare",
            "--received-at",
            READSB_RECEIVED,
        ),
        2,
        "synapse-decode: --at/--basis is not an argument readsb_trace declares",
    )
    _refused(
        _cli(
            *READSB_DECODE,
            "--input",
            str(READSB / "malformed" / "offsets_not_monotonic.trace"),
            "--received-at",
            READSB_RECEIVED,
        ),
        3,
        "synapse-decode: frame 0 refused by readsb_trace: ReadsbTraceRefused",
    )


@pytest.mark.parametrize("name", ["timestamp_past_a_double", "lone_surrogate_in_version"])
def test_a_readsb_trace_no_double_or_no_utf_8_can_hold_is_exit_3_and_never_a_traceback(name):
    # A 401-digit timestamp once escaped the adapter as OverflowError (exit 1, a traceback), and
    # a lone surrogate translated and then could not be written; both are now refused by class.
    result = _cli(
        *READSB_DECODE,
        "--input",
        str(READSB / "malformed" / f"{name}.trace"),
        "--received-at",
        READSB_RECEIVED,
    )
    # The whole of stderr is the one fixed line: no traceback, no value from the payload.
    _refused(result, 3, "synapse-decode: frame 0 refused by readsb_trace: ReadsbTraceRefused")


# -- nexrad2: the volume is the file; the frame's own digest when a container held it ----------

NEXRAD = PKG / "fixtures" / "nexrad2"
NEXRAD_FILE = NEXRAD / "two_elevations_two_records.ar2v"
NEXRAD_DECODE = ["decode", "--adapter", "nexrad2", "--synthetic"]
NEXRAD_RECEIVED = "2026-04-29T06:20:00Z"


def _nexrad_in_process(octets: bytes, source_hash: str, frame_sha256=None) -> list:
    from synapse_cdm.adapters.nexrad2 import Nexrad2Adapter

    clock = lambda: dt.datetime(2026, 4, 29, 6, 20, tzinfo=dt.timezone.utc)  # noqa: E731
    adapter = Nexrad2Adapter(
        clock,
        synthetic=True,
        source_hash={"algorithm": "sha256", "value": source_hash},
        frame_sha256=frame_sha256,
    )
    return [o.model_dump(mode="json") for o in adapter.to_cdm(octets)]


def _locators(objects: list) -> list:
    """Every radar locator the sweeps state: the contract's and each moment's."""
    found = []
    for o in objects:
        if o["object_kind"] != "event":
            continue
        observation = o["payload"]["observation"]
        found.append(observation["locator"])
        found += [m["values"]["locator"] for m in observation["moments"]]
    return found


def test_a_nexrad2_volume_decodes_with_the_files_digest_injected_and_no_frame_digest():
    octets = NEXRAD_FILE.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    result = _accepted(
        _cli(
            *NEXRAD_DECODE,
            "--input",
            str(NEXRAD_FILE),
            "--received-at",
            NEXRAD_RECEIVED,
            "--sha256",
            digest,
        )
    )
    assert [o["object_kind"] for o in result] == ["event", "event", "entity"]
    assert {o["received_at"] for o in result if o["object_kind"] == "event"} == {
        "2026-04-29T06:20:00.000Z"
    }
    assert [o["source"]["source_hash"] for o in result] == [
        {"algorithm": "sha256", "value": digest}
    ] * 3
    # The frame is the file, so source_hash already digests it: no frame digest is passed.
    assert len(_locators(result)) == 16
    assert {loc["frame_sha256"] for loc in _locators(result)} == {None}
    assert result == _nexrad_in_process(octets, digest)


def test_a_nexrad2_volume_inside_a_gzip_or_a_tar_carries_the_volumes_own_digest(tmp_path):
    octets = NEXRAD_FILE.read_bytes()
    volume_digest = hashlib.sha256(octets).hexdigest()
    packed = gzip.compress(octets, mtime=0)
    outer = hashlib.sha256(packed).hexdigest()
    assert outer != volume_digest
    result = _accepted(
        _cli(
            *NEXRAD_DECODE,
            "--input",
            _write(tmp_path / "v.ar2v.gz", packed),
            "--container",
            "gzip",
            "--received-at",
            NEXRAD_RECEIVED,
            "--sha256",
            outer,
        )
    )
    assert {o["source"]["source_hash"]["value"] for o in result} == {outer}
    assert {loc["frame_sha256"] for loc in _locators(result)} == {volume_digest}
    assert result == _nexrad_in_process(octets, outer, volume_digest)
    member = "2026/04/29/ZZZZ/ZZZZ20260429_061000_V06"
    archive = _tar([(member, octets, tarfile.REGTYPE)])
    archived = _accepted(
        _cli(
            *NEXRAD_DECODE,
            "--input",
            _write(tmp_path / "day.tar", archive),
            "--container",
            "tar",
            "--member",
            member,
            "--received-at",
            NEXRAD_RECEIVED,
        )
    )
    tar_digest = hashlib.sha256(archive).hexdigest()
    assert {loc["frame_sha256"] for loc in _locators(archived)} == {volume_digest}
    assert archived == _nexrad_in_process(octets, tar_digest, volume_digest)


def test_nexrad2_requires_its_receipt_instant_and_refuses_a_malformed_volume_by_class():
    _refused(
        _cli(*NEXRAD_DECODE, "--input", str(NEXRAD_FILE)),
        2,
        "synapse-decode: nexrad2 requires --received-at",
    )
    for name in ("message_29_model_data_record", "decompresses_past_the_bound"):
        _refused(
            _cli(
                *NEXRAD_DECODE,
                "--input",
                str(NEXRAD / "malformed" / f"{name}.ar2v"),
                "--received-at",
                NEXRAD_RECEIVED,
            ),
            3,
            "synapse-decode: frame 0 refused by nexrad2: Nexrad2Refused",
        )


# -- grib2: a file is its messages; each is framed with its ordinal, offset and digest ---------

GRIB = PKG / "fixtures" / "grib2"
GRIB_DECODE = ["decode", "--adapter", "grib2", "--synthetic"]
GRIB_RECEIVED = "2026-04-29T06:20:00Z"
#: Two fixture messages end to end: two fields in the first, one in the second.
GRIB_FIRST = (GRIB / "two_fields_one_message.grb2").read_bytes()
GRIB_SECOND = (GRIB / "simple_packing_latlon.grb2").read_bytes()


def _grib_in_process(octets: bytes, source_hash: str, **frame) -> list:
    from synapse_cdm.adapters.grib2 import Grib2Adapter

    clock = lambda: dt.datetime(2026, 4, 29, 6, 20, tzinfo=dt.timezone.utc)  # noqa: E731
    adapter = Grib2Adapter(
        clock, synthetic=True, source_hash={"algorithm": "sha256", "value": source_hash}, **frame
    )
    return [o.model_dump(mode="json") for o in adapter.to_cdm(octets)]


def test_a_two_message_grib2_file_is_framed_into_two_payloads_with_ordinals_0_and_1(tmp_path):
    file = GRIB_FIRST + GRIB_SECOND
    assert (len(GRIB_FIRST), len(GRIB_SECOND)) == (259, 196)
    digest = hashlib.sha256(file).hexdigest()
    first, second = (hashlib.sha256(m).hexdigest() for m in (GRIB_FIRST, GRIB_SECOND))
    result = _accepted(
        _cli(
            *GRIB_DECODE,
            "--input",
            _write(tmp_path / "two.grib2", file),
            "--received-at",
            GRIB_RECEIVED,
            "--sha256",
            digest,
        )
    )
    locators = [o["payload"]["observation"]["locator"] for o in result]
    assert [o["source"]["record_index"] for o in result] == [0, 0, 1]
    assert [(loc["message"], loc["field"], loc["byte_offset"]) for loc in locators] == [
        (0, 0, 0),
        (0, 1, 0),
        (1, 0, 259),
    ]
    assert [loc["frame_sha256"] for loc in locators] == [first, first, second]
    assert {o["source"]["source_hash"]["value"] for o in result} == {digest}
    assert {o["received_at"] for o in result} == {"2026-04-29T06:20:00.000Z"}
    assert result == _grib_in_process(
        GRIB_FIRST, digest, frame_sha256=first, message_ordinal=0, byte_offset=0
    ) + _grib_in_process(
        GRIB_SECOND, digest, frame_sha256=second, message_ordinal=1, byte_offset=259
    )


def test_a_one_message_grib2_file_is_its_own_frame_and_a_gzip_around_it_is_unwrapped(tmp_path):
    digest = hashlib.sha256(GRIB_SECOND).hexdigest()
    result = _accepted(
        _cli(
            *GRIB_DECODE,
            "--input",
            str(GRIB / "simple_packing_latlon.grb2"),
            "--received-at",
            GRIB_RECEIVED,
        )
    )
    # The frame is the file: no frame digest, message 0 at octet 0.
    assert result == _grib_in_process(GRIB_SECOND, digest)
    assert result[0]["payload"]["observation"]["locator"]["frame_sha256"] is None
    packed = gzip.compress(GRIB_FIRST + GRIB_SECOND, mtime=0)
    outer = hashlib.sha256(packed).hexdigest()
    unwrapped = _accepted(
        _cli(
            *GRIB_DECODE,
            "--input",
            _write(tmp_path / "two.grib2.gz", packed),
            "--container",
            "gzip",
            "--received-at",
            GRIB_RECEIVED,
        )
    )
    first = hashlib.sha256(GRIB_FIRST).hexdigest()
    assert unwrapped == _grib_in_process(
        GRIB_FIRST, outer, frame_sha256=first, message_ordinal=0, byte_offset=0
    ) + _grib_in_process(GRIB_SECOND, outer, frame_sha256=digest, message_ordinal=1, byte_offset=259)


GRIB_FRAMING = [
    ("a stray octet between two messages", GRIB_FIRST + b"\x00" + GRIB_SECOND,
     "synapse-decode: octet 259 of the input does not begin a GRIB message; a GRIB2 file is its "
     "messages end to end"),
    ("an edition 1 message", GRIB_FIRST[:7] + b"\x01" + GRIB_FIRST[8:],
     "synapse-decode: the message at octet 0 is not GRIB edition 2, which is the only edition this "
     "host frames"),
    ("a length past the end", GRIB_FIRST + GRIB_SECOND[:-1],
     "synapse-decode: the message at octet 259 states a total length shorter than Sections 0 and "
     "8 or running past the end of the input"),
    ("a length of zero", GRIB_FIRST[:8] + b"\x00" * 8 + GRIB_FIRST[16:],
     "synapse-decode: the message at octet 0 states a total length shorter than Sections 0 and 8 "
     "or running past the end of the input"),
    ("fifteen octets", GRIB_FIRST[:15],
     "synapse-decode: octet 0 of the input does not begin a GRIB message; a GRIB2 file is its "
     "messages end to end"),
    ("an empty file", b"", "synapse-decode: the input holds no GRIB message"),
]  # fmt: skip


@pytest.mark.parametrize("label, data, line", GRIB_FRAMING, ids=[r[0] for r in GRIB_FRAMING])
def test_a_grib2_file_that_is_not_its_messages_end_to_end_is_exit_3(tmp_path, label, data, line):
    _refused(
        _cli(*GRIB_DECODE, "--input", _write(tmp_path / "f.grib2", data), "--received-at",
             GRIB_RECEIVED),
        3,
        line,
    )  # fmt: skip


def test_the_grib_framer_cuts_at_each_total_length_and_nothing_else():
    assert decode_host.grib_messages(GRIB_FIRST + GRIB_SECOND) == [GRIB_FIRST, GRIB_SECOND]
    assert decode_host.grib_messages(GRIB_SECOND) == [GRIB_SECOND]
    with pytest.raises(decode_host.Refused) as raised:
        decode_host.grib_messages(GRIB_SECOND + b"GRIB")
    assert (raised.value.status, raised.value.message) == (
        3,
        "synapse-decode: octet 196 of the input does not begin a GRIB message; a GRIB2 file is "
        "its messages end to end",
    )


def test_grib2_requires_its_receipt_instant_and_refuses_a_malformed_message_by_class(tmp_path):
    _refused(
        _cli(*GRIB_DECODE, "--input", str(GRIB / "simple_packing_latlon.grb2")),
        2,
        "synapse-decode: grib2 requires --received-at",
    )
    for name in ("png_crc_failure", "repeated_grid_section"):
        _refused(
            _cli(
                *GRIB_DECODE,
                "--input",
                str(GRIB / "malformed" / f"{name}.grb2"),
                "--received-at",
                GRIB_RECEIVED,
            ),
            3,
            "synapse-decode: frame 0 refused by grib2: Grib2Refused",
        )
    # The second message of a file refused: its ordinal is named, the first one's objects are
    # not printed.
    bad = (GRIB / "malformed" / "png_crc_failure.grb2").read_bytes()
    result = _cli(
        *GRIB_DECODE, "--input", _write(tmp_path / "f.grib2", GRIB_SECOND + bad),
        "--received-at", GRIB_RECEIVED,
    )  # fmt: skip
    _refused(result, 3, "synapse-decode: frame 1 refused by grib2: Grib2Refused")


# -- cog and iem_n0q (2026-10-17): one raster file, read whole ---------------------------------

N0Q = PKG / "fixtures" / "iem_n0q"
N0Q_FILE = N0Q / "echo_patch_split_idat.png"
N0Q_BASIS = "IEM archive filename slot, UTC, composite nominal time"
N0Q_DECODE = ["decode", "--adapter", "iem_n0q", "--synthetic"]
N0Q_SLOT = ["--at", "2026-04-29T06:05:00Z", "--basis", N0Q_BASIS]
RECEIVED = "2026-04-29T06:20:00Z"
COG = PKG / "fixtures" / "cog"
COG_DEM = COG / "navd88_dem_deflate.tif"
COG_DECODE = ["decode", "--adapter", "cog", "--synthetic"]


def _receipt():
    return dt.datetime(2026, 4, 29, 6, 20, tzinfo=dt.timezone.utc)


def _n0q_in_process(octets: bytes, source_hash: str, **kwargs) -> list:
    from synapse_cdm.adapters.iem_n0q import IemN0qAdapter
    from synapse_cdm.observation_contracts import InjectedTime

    adapter = IemN0qAdapter(
        _receipt,
        synthetic=True,
        slot=InjectedTime("2026-04-29T06:05:00Z", N0Q_BASIS),
        source_hash={"algorithm": "sha256", "value": source_hash},
        **kwargs,
    )
    return [o.model_dump(mode="json") for o in adapter.to_cdm(octets)]


def _cog_in_process(octets: bytes, source_hash: str, **kwargs) -> list:
    from synapse_cdm.adapters.cog import CogAdapter

    adapter = CogAdapter(
        _receipt, synthetic=True, source_hash={"algorithm": "sha256", "value": source_hash},
        **kwargs,
    )  # fmt: skip
    return [o.model_dump(mode="json") for o in adapter.to_cdm(octets)]


def test_iem_n0q_is_given_its_slot_its_receipt_and_the_file_s_digest():
    octets = N0Q_FILE.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    result = _accepted(
        _cli(*N0Q_DECODE, "--input", str(N0Q_FILE), *N0Q_SLOT, "--received-at", RECEIVED)
    )
    assert result == _n0q_in_process(octets, digest)
    (event,) = result
    assert (event["observed_at"], event["received_at"]) == (
        "2026-04-29T06:05:00.000Z",
        "2026-04-29T06:20:00.000Z",
    )
    assert event["source"]["source_hash"] == {"algorithm": "sha256", "value": digest}
    assert event["source_ids"] == [
        {"system": "IEM_N0Q", "external_id": f"N0Q composite 2026-04-29T06:05:00.000Z sha256 {digest}"}
    ]
    # The frame is the file: no frame digest.
    assert event["payload"]["observation"]["locator"]["frame_sha256"] is None


def test_iem_n0q_unwrapped_from_a_gzip_is_given_the_png_s_own_digest(tmp_path):
    octets = N0Q_FILE.read_bytes()
    packed = gzip.compress(octets, mtime=0)
    result = _accepted(
        _cli(
            *N0Q_DECODE, "--input", _write(tmp_path / "n0q.png.gz", packed), "--container", "gzip",
            *N0Q_SLOT, "--received-at", RECEIVED,
        )
    )  # fmt: skip
    frame = hashlib.sha256(octets).hexdigest()
    assert result == _n0q_in_process(
        octets, hashlib.sha256(packed).hexdigest(), frame_sha256=frame
    )
    assert result[0]["payload"]["observation"]["locator"]["frame_sha256"] == frame


def test_iem_n0q_requires_its_slot_on_the_five_minute_grid_and_refuses_a_malformed_png():
    _refused(
        _cli(*N0Q_DECODE, "--input", str(N0Q_FILE), *N0Q_SLOT),
        2,
        "synapse-decode: iem_n0q requires --received-at",
    )
    _refused(
        _cli(*N0Q_DECODE, "--input", str(N0Q_FILE), "--received-at", RECEIVED),
        2,
        "synapse-decode: iem_n0q requires --at/--basis",
    )
    for at, basis in (
        ("2026-04-29T06:07:00Z", N0Q_BASIS),
        ("2026-04-29T06:05:30Z", N0Q_BASIS),
        ("2026-04-29T06:05:00Z", "slot"),
    ):
        _refused(
            _cli(
                *N0Q_DECODE, "--input", str(N0Q_FILE), "--at", at, "--basis", basis,
                "--received-at", RECEIVED,
            ),
            2,
            "synapse-decode: iem_n0q refuses the context the flags describe",
        )  # fmt: skip
    _refused(
        _cli(
            *N0Q_DECODE, "--input", str(N0Q_FILE), *N0Q_SLOT, "--received-at", RECEIVED,
            "--request", "slot=202604290605",
        ),
        2,
        "synapse-decode: --request is not an argument iem_n0q declares",
    )  # fmt: skip
    for name in ("idat_crc_failure", "wrong_image_size", "gentime_twice"):
        _refused(
            _cli(
                *N0Q_DECODE, "--input", str(N0Q / "malformed" / f"{name}.png"), *N0Q_SLOT,
                "--received-at", RECEIVED,
            ),
            3,
            "synapse-decode: frame 0 refused by iem_n0q: IemN0qRefused",
        )  # fmt: skip


def test_cog_is_given_its_identifiers_as_request_parameters_and_the_file_s_digest():
    octets = COG_DEM.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    result = _accepted(
        _cli(
            *COG_DECODE, "--input", str(COG_DEM), "--request", "band_file=dem_band.tif",
            "--request", "granule=EX-granule-01", "--received-at", RECEIVED,
        )
    )  # fmt: skip
    assert result == _cog_in_process(
        octets, digest, band_file="dem_band.tif", granule_id="EX-granule-01"
    )
    (plan,) = result
    assert plan["source"]["source_hash"] == {"algorithm": "sha256", "value": digest}
    assert plan["source"]["original_id"] == "dem_band.tif"
    assert plan["source_ids"] == [{"system": "COG", "external_id": "EX-granule-01/dem_band.tif"}]
    # Without a band file the identity is the descriptor followed by the injected digest
    # (D-R6-14 as amended), so two files of one grid are told apart.
    bare = _accepted(_cli(*COG_DECODE, "--input", str(COG_DEM), "--received-at", RECEIVED))
    assert bare == _cog_in_process(octets, digest)
    assert bare[0]["source_ids"][0]["external_id"].endswith(f" sha256 {digest}")


def test_cog_s_instant_comes_with_its_role_and_only_with_it():
    octets = COG_DEM.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    from synapse_cdm.observation_contracts import InjectedTime

    instant = ["--at", "2026-04-29T00:00:00Z", "--basis", "the tile's publication date, by hand"]
    result = _accepted(
        _cli(
            *COG_DECODE, "--input", str(COG_DEM), *instant, "--request", "time=as_of",
            "--received-at", RECEIVED,
        )
    )  # fmt: skip
    as_of = InjectedTime("2026-04-29T00:00:00Z", "the tile's publication date, by hand")
    assert result == _cog_in_process(octets, digest, as_of=as_of)
    assert result[0]["validity"]["observed_at"] == "2026-04-29T00:00:00.000Z"
    # The same DEM given its instant as a sensing time becomes an imagery-product/1 Event.
    sensed = _accepted(
        _cli(
            *COG_DECODE, "--input", str(COG_DEM), *instant, "--request", "time=sensing_time",
            "--received-at", RECEIVED,
        )
    )  # fmt: skip
    assert [o["object_kind"] for o in sensed] == ["event"]
    assert sensed[0]["observed_at"] == "2026-04-29T00:00:00.000Z"
    for extra in (
        [*instant],
        ["--request", "time=as_of"],
        [*instant, "--request", "time=valid_at"],
        ["--request", "tile=EX01"],
        ["--request", "band_file=sub/dem.tif"],
    ):
        _refused(
            _cli(*COG_DECODE, "--input", str(COG_DEM), *extra, "--received-at", RECEIVED),
            2,
            "synapse-decode: cog refuses the context the flags describe",
        )
    _refused(
        _cli(*COG_DECODE, "--input", str(COG_DEM)), 2, "synapse-decode: cog requires --received-at"
    )
    _refused(
        _cli(
            *COG_DECODE, "--input", str(COG / "malformed" / "jpeg_compression.tif"),
            "--received-at", RECEIVED,
        ),
        3,
        "synapse-decode: frame 0 refused by cog: CogRefused",
    )  # fmt: skip


# -- the station-text adapters: a request, a station table, the receipt instant ---------------

STATION_TEXT = PKG / "fixtures"
TEXT_RECEIVED = "2026-04-29T06:20:00Z"
TEXT_CLOCK = dt.datetime(2026, 4, 29, 6, 20, tzinfo=dt.timezone.utc)


def _station_text_in_process(cls, octets: bytes, source_hash: str, frame=None, **kwargs) -> list:
    adapter = cls(
        lambda: TEXT_CLOCK,
        synthetic=True,
        source_hash={"algorithm": "sha256", "value": source_hash},
        frame_sha256=frame,
        **kwargs,
    )
    return [o.model_dump(mode="json") for o in adapter.to_cdm(octets)]


def _table_file(tmp_path, rows: list) -> str:
    table = {"name": "host-table", "basis": "a synthetic table for the host test", "rows": rows}
    return _write(tmp_path / "table.json", json.dumps(table).encode())


def test_ndbc_stdmet_takes_its_station_as_a_request_and_its_position_from_a_table(tmp_path):
    from synapse_cdm.adapters.ndbc_stdmet import NdbcStdmetAdapter
    from synapse_cdm.observation_contracts import StationTable

    path = STATION_TEXT / "ndbc_stdmet" / "realtime_newest_first.stdmet"
    octets = path.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    rows = [{"station_id": "EX001", "lat": 57.25, "lon": 21.5}]
    decode = ["decode", "--adapter", "ndbc_stdmet", "--synthetic", "--input", str(path)]
    result = _accepted(
        _cli(
            *decode,
            "--received-at",
            TEXT_RECEIVED,
            "--request",
            "station=EX001",
            "--station-table",
            _table_file(tmp_path, rows),
            "--sha256",
            digest,
        )
    )
    table = StationTable(name="host-table", basis="a synthetic table for the host test", rows=rows)
    assert result == _station_text_in_process(
        NdbcStdmetAdapter, octets, digest, station_id="EX001", station_table=table
    )
    assert [o["object_kind"] for o in result] == ["event", "event", "event", "entity"]
    assert result[-1]["position"]["lat"] == 57.25
    assert {o["source"]["source_hash"]["value"] for o in result} == {digest}
    assert {o["payload"]["observation"]["locator"]["frame_sha256"] for o in result[:3]} == {None}
    assert {o["received_at"] for o in result[:3]} == {"2026-04-29T06:20:00.000Z"}
    _refused(
        _cli(*decode, "--received-at", TEXT_RECEIVED),
        2,
        "synapse-decode: ndbc_stdmet requires --request",
    )
    _refused(
        _cli(*decode, "--request", "station=EX001"),
        2,
        "synapse-decode: ndbc_stdmet requires --received-at",
    )
    for request in (
        ["--request", "station=ex001"],
        ["--request", "station=EX001", "--request", "datum=MLLW"],
    ):
        _refused(
            _cli(*decode, "--received-at", TEXT_RECEIVED, *request),
            2,
            "synapse-decode: ndbc_stdmet refuses the context the flags describe",
        )
    _refused(
        _cli(
            "decode", "--adapter", "ndbc_stdmet", "--synthetic", "--input",
            str(STATION_TEXT / "ndbc_stdmet" / "malformed" / "undocumented_sentinel_width.stdmet"),
            "--received-at", TEXT_RECEIVED, "--request", "station=EX001",
        ),
        3,
        "synapse-decode: frame 0 refused by ndbc_stdmet: NdbcStdmetRefused",
    )  # fmt: skip


def test_a_gzipped_yearly_stdmet_file_carries_the_text_s_own_digest(tmp_path):
    from synapse_cdm.adapters.ndbc_stdmet import NdbcStdmetAdapter

    octets = (STATION_TEXT / "ndbc_stdmet" / "historical_nine_runs.stdmet").read_bytes()
    packed = gzip.compress(octets, mtime=0)
    outer, inner = hashlib.sha256(packed).hexdigest(), hashlib.sha256(octets).hexdigest()
    result = _accepted(
        _cli(
            "decode", "--adapter", "ndbc_stdmet", "--synthetic",
            "--input", _write(tmp_path / "EX001h2025.txt.gz", packed), "--container", "gzip",
            "--received-at", TEXT_RECEIVED, "--request", "station=EX001", "--sha256", outer,
        )
    )  # fmt: skip
    assert {o["source"]["source_hash"]["value"] for o in result} == {outer}
    assert {o["payload"]["observation"]["locator"]["frame_sha256"] for o in result[:3]} == {inner}
    assert result == _station_text_in_process(
        NdbcStdmetAdapter, octets, outer, inner, station_id="EX001"
    )
    assert result[-1]["position"] is None


def test_coops_csv_takes_its_request_from_the_flags_and_refuses_lst_ldt_by_name():
    from synapse_cdm.adapters.coops_csv import CoopsCsvAdapter, CoopsRequest

    path = STATION_TEXT / "coops_csv" / "water_level_preliminary.csv"
    octets = path.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    decode = ["decode", "--adapter", "coops_csv", "--synthetic", "--input", str(path)]
    base = ["--received-at", TEXT_RECEIVED]
    request = ["--request", "station=0000001", "--request", "product=water_level",
               "--request", "datum=MLLW", "--request", "units=metric"]  # fmt: skip
    lst = _accepted(
        _cli(*decode, *base, *request, "--request", "time_zone=lst", "--request",
             "lst_offset=-05:00")
    )  # fmt: skip
    expected = CoopsRequest(
        station="0000001", product="water_level", datum="MLLW", units="metric",
        time_zone="lst", lst_offset="-05:00",
    )  # fmt: skip
    assert lst == _station_text_in_process(CoopsCsvAdapter, octets, digest, request=expected)
    # 2026-04-28 00:00 local standard time at -05:00 is 05:00Z.
    assert [o["observed_at"] for o in lst[:3]] == [
        "2026-04-28T05:00:00.000Z",
        "2026-04-28T05:06:00.000Z",
        "2026-04-28T05:12:00.000Z",
    ]
    refusal = "synapse-decode: coops_csv refuses the context the flags describe"
    for extra in (
        ["--request", "time_zone=lst_ldt"],
        [],
        ["--request", "time_zone=gmt", "--request", "begin_date=20260428"],
        ["--request", "time_zone=lst"],
    ):
        _refused(_cli(*decode, *base, *request, *extra), 2, refusal)
    _refused(_cli(*decode, *base), 2, "synapse-decode: coops_csv requires --request")
    _refused(
        _cli(
            "decode", "--adapter", "coops_csv", "--synthetic", "--input",
            str(STATION_TEXT / "coops_csv" / "malformed" / "air_pressure_header.csv"),
            *base, *request, "--request", "time_zone=gmt",
        ),
        3,
        "synapse-decode: frame 0 refused by coops_csv: CoopsRefused",
    )  # fmt: skip


def test_airnow_hourly_takes_its_site_table_as_a_station_table(tmp_path):
    from synapse_cdm.adapters.airnow_hourly import AirnowHourlyAdapter
    from synapse_cdm.observation_contracts import StationTable

    path = STATION_TEXT / "airnow_hourly" / "hourly_data_two_sites.dat"
    octets = path.read_bytes()
    digest = hashlib.sha256(octets).hexdigest()
    rows = [{"station_id": "000000002", "lat": 57.4, "lon": 21.6}]
    decode = ["decode", "--adapter", "airnow_hourly", "--synthetic", "--input", str(path)]
    result = _accepted(
        _cli(*decode, "--received-at", TEXT_RECEIVED, "--station-table", _table_file(tmp_path, rows))
    )  # fmt: skip
    table = StationTable(name="host-table", basis="a synthetic table for the host test", rows=rows)
    assert result == _station_text_in_process(AirnowHourlyAdapter, octets, digest, site_table=table)
    assert [o["position"] for o in result[4:]] == [
        None,
        {"accuracy_m": None, "alt_m": None, "lat": 57.4, "lon": 21.6,
         "position_source": "MANUAL", "vertical": None},
    ]  # fmt: skip
    _refused(
        _cli(*decode, "--received-at", TEXT_RECEIVED, "--request", "station=000000001"),
        2,
        "synapse-decode: --request is not an argument airnow_hourly declares",
    )
    _refused(
        _cli(
            "decode", "--adapter", "airnow_hourly", "--synthetic", "--input",
            str(STATION_TEXT / "airnow_hourly" / "malformed" / "not_on_the_hour.dat"),
            "--received-at", TEXT_RECEIVED,
        ),
        3,
        "synapse-decode: frame 0 refused by airnow_hourly: AirnowRefused",
    )  # fmt: skip


def test_gzip_is_unwrapped_and_the_digest_is_of_the_file_as_read(tmp_path):
    packed = gzip.compress(EQUATOR.read_bytes(), mtime=0)
    path = _write(tmp_path / "e.dis.gz", packed)
    outer = hashlib.sha256(packed).hexdigest()
    assert outer != EQUATOR_SHA256
    assert _accepted(
        _cli(*DIS7, "--input", path, "--container", "gzip", "--sha256", outer)
    ) == _expected_equator(outer)
    _refused(
        _cli(*DIS7, "--input", path, "--container", "gzip", "--sha256", EQUATOR_SHA256),
        3,
        "synapse-decode: the SHA-256 of --input is not the expected one",
    )


def _gzip_cases(data: bytes) -> dict:
    packed = gzip.compress(data, mtime=0)
    corrupt = bytearray(packed)
    corrupt[-8] ^= 0xFF  # the CRC-32 the trailer states
    return {
        "truncated": packed[:-4],
        "corrupt": bytes(corrupt),
        "trailing": packed + b"\x00",
        "two-members": packed + packed,
        "not-gzip": data,
    }


@pytest.mark.parametrize(
    "case, line",
    [
        ("truncated", "synapse-decode: the gzip stream is truncated"),
        ("corrupt", "synapse-decode: the gzip stream is corrupt"),
        ("trailing", "synapse-decode: octets follow the gzip member; one member is accepted"),
        ("two-members", "synapse-decode: octets follow the gzip member; one member is accepted"),
        ("not-gzip", "synapse-decode: the input is not a gzip stream"),
    ],
)
def test_a_gzip_stream_is_one_whole_member_or_is_refused(tmp_path, case, line):
    data = _gzip_cases(EQUATOR.read_bytes())[case]
    _refused(
        _cli(*DIS7, "--input", _write(tmp_path / "e.gz", data), "--container", "gzip"), 3, line
    )


def test_gzip_is_bounded_by_the_adapters_bound_and_by_the_ratio(tmp_path):
    over = gzip.compress(bytes(4225), mtime=0)
    _refused(
        _cli(*DIS7, "--input", _write(tmp_path / "z.gz", over), "--container", "gzip"),
        3,
        f"synapse-decode: the gzip stream inflates past 4224 octets (the bound is 4224 "
        f"octets and 256 times the {len(over)} read)",
    )
    document = b'{"type":"Feature","id":"ex-1","geometry":null' + b" " * 200000 + b"}"
    bomb = gzip.compress(document, mtime=0)
    assert 256 * len(bomb) < len(document) < 8388608
    _refused(
        _cli(*GEOJSON, *AS_OF, "--input", _write(tmp_path / "b.gz", bomb), "--container", "gzip"),
        3,
        f"synapse-decode: the gzip stream inflates past {256 * len(bomb)} octets (the bound "
        f"is 8388608 octets and 256 times the {len(bomb)} read)",
    )


def _stored_gzip(payload: bytes) -> bytes:
    """One gzip member written by hand: RFC 1952's ten-octet header (no flags, mtime 0, OS 255),
    the payload as deflate STORED blocks of at most 65 535 octets (RFC 1951 §3.2.4: one octet
    whose low bit is BFINAL, LEN and its complement NLEN little-endian, the octets), then CRC-32
    and ISIZE. Every zlib reads it alike and its size is exact: 18 + 5 per block + the payload."""
    blocks = []
    for start in range(0, len(payload), 65535):
        piece = payload[start : start + 65535]
        final = 1 if start + 65535 >= len(payload) else 0
        blocks.append(bytes([final]) + struct.pack("<HH", len(piece), len(piece) ^ 0xFFFF) + piece)
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload))
    return b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff" + b"".join(blocks) + trailer


class _CountingInflater:
    """zlib's inflater, recording the octets each step is handed and what it gives back."""

    def __init__(self, calls: list, **kwargs) -> None:
        self._inner = zlib.decompressobj(**kwargs)
        self._calls = calls

    def decompress(self, data, max_length=0):
        out = self._inner.decompress(data, max_length)
        self._calls.append((len(data), len(out)))
        return out

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_gzip_input_is_fed_in_bounded_steps_and_the_work_is_linear(monkeypatch):
    """Checkpoint finding H-03 (2026-10-15): the whole file was handed to zlib at once, and every
    64 KiB step then copied the input it had not consumed, ~63 times an 8 MiB file in all. Fed in
    slices of 65 536 octets, no step is handed more than one slice, and the octets handed over
    in all are at most the file once plus one slice per step that stopped for output room."""
    payload = bytes(range(256)) * 32768
    assert len(payload) == 8388608
    member = _stored_gzip(payload)
    # 128 blocks of 65 535 octets and one of 128 (8 388 480 + 128), each with its 5-octet head.
    assert len(member) == 10 + 129 * 5 + 8388608 + 8 == 8389271
    calls: list[tuple[int, int]] = []
    counting = types.SimpleNamespace(
        decompressobj=lambda **kwargs: _CountingInflater(calls, **kwargs), error=zlib.error
    )
    monkeypatch.setattr(decode_host, "zlib", counting)
    assert decode_host.gunzip(member, 8388608) == payload
    handed = [given for given, _ in calls]
    assert max(handed) <= 65536
    # ceil(8 389 271 / 65 536) = 129 slices fed, 8 388 608 / 65 536 = 128 steps that can stop
    # for output room, and at most a final flush with nothing left to feed: 258 steps at most.
    assert len(calls) <= 129 + 128 + 1
    assert sum(handed) <= 8389271 + 128 * 65536
    assert sum(out for _, out in calls) == 8388608


def test_a_member_that_ends_on_a_slice_boundary_is_still_one_member_or_refused(tmp_path):
    exact = _stored_gzip(bytes(65513))
    assert len(exact) == 65536
    # The member fills the first slice exactly; anything after it is a slice never fed.
    for tail, line in [
        (b"\x00", "synapse-decode: octets follow the gzip member; one member is accepted"),
        (exact, "synapse-decode: octets follow the gzip member; one member is accepted"),
    ]:
        with pytest.raises(decode_host.Refused) as refused:
            decode_host.gunzip(exact + tail, 8388608)
        assert (refused.value.status, refused.value.message) == (3, line)
    assert decode_host.gunzip(exact, 8388608) == bytes(65513)
    big = _stored_gzip(bytes(200000))
    for cut, line in [
        (4, "synapse-decode: the gzip stream is truncated"),
        (65536, "synapse-decode: the gzip stream is truncated"),
    ]:
        with pytest.raises(decode_host.Refused) as refused:
            decode_host.gunzip(big[:-cut], 8388608)
        assert (refused.value.status, refused.value.message) == (3, line)


UNSAFE_NAME = (
    "synapse-decode: the archive holds a member whose name is absolute or climbs out with .."
)


def _tar(members: list[tuple[str, bytes | None, bytes]]) -> bytes:
    """An uncompressed tar of (name, data or None, type) members, written by `tarfile`."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:", format=tarfile.PAX_FORMAT) as archive:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.mtime = 0
            if kind == tarfile.SYMTYPE:
                info.linkname = "elsewhere"
            if data is not None:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                archive.addfile(info)
    return buffer.getvalue()


def test_one_named_tar_member_is_taken_and_decoded(tmp_path):
    archive = _tar(
        [
            ("traces/a.json", FEATURE, tarfile.REGTYPE),
            ("traces/b.dis", EQUATOR.read_bytes(), tarfile.REGTYPE),
        ]
    )
    result = _accepted(
        _cli(
            *GEOJSON,
            *AS_OF,
            "--input",
            _write(tmp_path / "t.tar", archive),
            "--container",
            "tar",
            "--member",
            "traces/a.json",
        )
    )
    assert [o["source"]["original_id"] for o in result] == ['"ex-1"']


@pytest.mark.parametrize(
    "members, line",
    [
        (
            [("traces/b.json", FEATURE, tarfile.REGTYPE)],
            "synapse-decode: --member names no member of the archive",
        ),
        (
            [
                ("traces/a.json", FEATURE, tarfile.REGTYPE),
                ("traces/a.json", FEATURE, tarfile.REGTYPE),
            ],
            "synapse-decode: --member names 2 members of the archive",
        ),
        (
            [("traces/a.json", None, tarfile.SYMTYPE)],
            "synapse-decode: the named member is not a regular file",
        ),
        (
            [("traces/a.json", None, tarfile.DIRTYPE)],
            "synapse-decode: the named member is not a regular file",
        ),
        (
            [
                ("traces/a.json", FEATURE, tarfile.REGTYPE),
                ("../evil.json", FEATURE, tarfile.REGTYPE),
            ],
            UNSAFE_NAME,
        ),
        (
            [
                ("/etc/evil.json", FEATURE, tarfile.REGTYPE),
                ("traces/a.json", FEATURE, tarfile.REGTYPE),
            ],
            UNSAFE_NAME,
        ),
    ],
    ids=["absent", "twice", "symlink", "directory", "climbing-neighbour", "absolute-neighbour"],
)
def test_a_tar_member_is_one_regular_file_in_an_archive_with_no_unsafe_name(
    tmp_path, members, line
):
    archive = _write(tmp_path / "t.tar", _tar(members))
    _refused(
        _cli(
            *GEOJSON, *AS_OF, "--input", archive, "--container", "tar", "--member", "traces/a.json"
        ),
        3,
        line,
    )


def test_a_tar_is_bounded_by_its_member_count_its_member_size_and_its_own_shape(tmp_path):
    many = _tar([(f"m/{i:04d}", b"", tarfile.REGTYPE) for i in range(4097)])
    assert len(many) < 8388608
    _refused(
        _cli(
            *GEOJSON,
            "--input",
            _write(tmp_path / "many.tar", many),
            "--container",
            "tar",
            "--member",
            "m/0000",
        ),
        3,
        "synapse-decode: the archive holds more than 4096 members",
    )
    small = _tar([("a.dis", bytes(3000), tarfile.REGTYPE)])
    head = small[: 512 + 1000]
    _refused(
        _cli(
            *DIS7,
            "--input",
            _write(tmp_path / "cut.tar", head),
            "--container",
            "tar",
            "--member",
            "a.dis",
        ),
        3,
        "synapse-decode: a tar header is corrupt or the archive is truncated",
    )
    _refused(
        _cli(
            *DIS7,
            "--input",
            _write(tmp_path / "x.tar", EQUATOR.read_bytes()),
            "--container",
            "tar",
            "--member",
            "a.dis",
        ),
        3,
        "synapse-decode: the input is not a tar archive",
    )


MEMBER = b"traces/a.json"


def _header(name: bytes, size: bytes, kind: bytes, extra: bytes = b"", magic=b"ustar\x0000"):
    """One 512-octet tar header from literals (POSIX ustar layout: name at 0, mode 100, uid 108,
    gid 116, size 124, mtime 136, checksum 148, type 156, magic 257, and from 386 the old GNU
    sparse map and its `isextended` octet at 482), with the checksum POSIX defines: the sum of
    the header's octets with the checksum field read as eight spaces, six octal digits, NUL,
    space."""
    block = bytearray(512)
    block[0 : len(name)] = name
    block[100:108] = b"0000644\x00"
    block[108:116] = b"0000000\x00"
    block[116:124] = b"0000000\x00"
    block[124:136] = size
    block[136:148] = b"00000000000\x00"
    block[148:156] = b" " * 8
    block[156:157] = kind
    block[257:265] = magic
    block[386 : 386 + len(extra)] = extra
    block[148:156] = b"%06o\x00 " % sum(block)
    return bytes(block)


def _octal(size: int) -> bytes:
    return b"%011o\x00" % size


def _padded(data: bytes) -> bytes:
    return data + bytes(-len(data) % 512)


def _record(text: bytes) -> bytes:
    """A pax record, `<length> <keyword>=<value>\\n`, whose length counts its own digits."""
    length = len(text) + 2
    while len(b"%d " % length) + len(text) != length:
        length += 1
    return b"%d " % length + text


def _pax(records: bytes, size: int = 2, data: bytes = b"{}", end: bytes = bytes(1024)) -> bytes:
    """A pax extended header holding `records`, then the member it describes, then `end`."""
    return (
        _header(b"PaxHeaders/a", _octal(len(records)), b"x")
        + _padded(records)
        + _header(MEMBER, _octal(size), b"0")
        + _padded(data)
        + end
    )


_SPARSE_1_0 = _record(b"GNU.sparse.major=1\n") + _record(b"GNU.sparse.minor=0\n")

#: The checkpoint's seven archives (finding H-01, 2026-10-15), each a few blocks: `tarfile` reads
#: each header's checksum as valid and then fails inside its own record parsing, with
#: `ValueError`, `IndexError` or `OverflowError` rather than `TarError`. Until 2026-10-15 each
#: was an exit-1 traceback; each is now the corrupt-header refusal.
TAR_HEADERS_TARFILE_CANNOT_PARSE = {
    # GNU sparse 0.1: the map is two integers per region, and these are not integers.
    "pax-sparse-map-not-numbers": _pax(_record(b"GNU.sparse.map=abc,def\n")),
    # GNU sparse 1.0: the map heads the member's data, one number per line; no newline at all.
    "pax-sparse-1.0-no-newline": _pax(_SPARSE_1_0, 512, b"Z" * 512),
    # The same map whose region count is not a number.
    "pax-sparse-1.0-count-not-a-number": _pax(_SPARSE_1_0, 512, b"zz\n1\n2\n"),
    # A count of 999 999 999 regions and 2 000 numbers, then the end of the file.
    "pax-sparse-1.0-count-past-the-file": _pax(
        _SPARSE_1_0, 4096, b"999999999\n" + b"1\n" * 2000, end=b""
    ),
    # Old GNU sparse member, type S, `isextended` set, and no extension block after it.
    "gnu-sparse-extended-then-end": _header(
        MEMBER, _octal(0), b"S", extra=bytes(96) + b"\x01", magic=b"ustar  \x00"
    ),
    # A pax `size` of 23 digits: past what a file offset can hold.
    "pax-size-past-an-offset": _pax(_record(b"size=99999999999999999999999\n")),
    # A base-256 size field (high bit set) of 0x7f7f...: past what a file offset can hold.
    "base-256-size-past-an-offset": _header(MEMBER, b"\x80" + b"\x7f" * 11, b"0") + bytes(1024),
}


def test_the_seven_archives_are_the_sizes_their_blocks_add_up_to():
    # A pax archive: its header, one block of records, the member's header, one block of data
    # and the two end blocks, six blocks; the base-256 one: a header and the two end blocks.
    assert {name: len(data) for name, data in TAR_HEADERS_TARFILE_CANNOT_PARSE.items()} == {
        "pax-sparse-map-not-numbers": 6 * 512,
        "pax-sparse-1.0-no-newline": 6 * 512,
        "pax-sparse-1.0-count-not-a-number": 6 * 512,
        # Three header blocks, then 10 + 4 000 octets of map padded to 4 096; no end blocks.
        "pax-sparse-1.0-count-past-the-file": 3 * 512 + 4096,
        "gnu-sparse-extended-then-end": 512,
        "pax-size-past-an-offset": 6 * 512,
        "base-256-size-past-an-offset": 3 * 512,
    }


@pytest.mark.parametrize("name", sorted(TAR_HEADERS_TARFILE_CANNOT_PARSE))
def test_a_tar_header_tarfile_cannot_parse_is_the_corrupt_header_refusal(tmp_path, name):
    archive = _write(tmp_path / "t.tar", TAR_HEADERS_TARFILE_CANNOT_PARSE[name])
    _refused(
        _cli(
            *GEOJSON, *AS_OF, "--input", archive, "--container", "tar", "--member", "traces/a.json"
        ),
        3,
        "synapse-decode: a tar header is corrupt or the archive is truncated",
    )


def test_a_tar_member_past_the_unwrapped_bound_is_refused_from_its_header(
    tmp_path, monkeypatch, capsysbinary
):
    """The dis7 file bound (4224) admits no tar holding a member past it, so the bound on the
    member is shown with the double, whose file bound is larger than its unwrapped bound."""
    _host_the_double(monkeypatch, file_bound=65536, unwrapped_bound=64)
    archive = _write(tmp_path / "t.tar", _tar([("a.txt", b"x" * 65, tarfile.REGTYPE)]))
    status = decode_host.main(
        [
            "decode",
            "--adapter",
            "double",
            "--synthetic",
            "--input",
            archive,
            "--received-at",
            "2026-09-11T10:05:00Z",
            "--container",
            "tar",
            "--member",
            "a.txt",
        ]
    )
    captured = capsysbinary.readouterr()
    assert (status, captured.out) == (3, b"")
    assert captured.err == b"synapse-decode: the named member is 65 octets; the bound is 64\n"


# -- exit 4: I/O ---------------------------------------------------------------------------------


def test_an_absent_file_a_directory_and_a_fifo_are_exit_4_and_the_fifo_is_not_waited_on(tmp_path):
    _refused(
        _cli(*GEOJSON, "--input", str(tmp_path / "absent.json")),
        4,
        "synapse-decode: cannot read --input: No such file or directory",
    )
    _refused(
        _cli(*GEOJSON, "--input", str(tmp_path)),
        4,
        "synapse-decode: cannot read --input: not a regular file",
    )
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    _refused(
        _cli(*GEOJSON, "--input", str(fifo)),
        4,
        "synapse-decode: cannot read --input: not a regular file",
    )
    feature = _write(tmp_path / "f.json", FEATURE)
    _refused(
        _cli(*GEOJSON, "--input", feature, "--manifest-row", str(tmp_path / "absent")),
        4,
        "synapse-decode: cannot read --manifest-row: No such file or directory",
    )


class _Unwritable:
    """A stdout whose binary buffer refuses every write with a broken pipe."""

    class _Buffer:
        def write(self, data):
            raise BrokenPipeError(errno.EPIPE, "Broken pipe")

        def flush(self):
            pass

    buffer = _Buffer()

    def fileno(self):
        # What a stream with no descriptor raises: argparse on 3.14 asks it whether to colour.
        raise io.UnsupportedOperation("no descriptor")

    def flush(self):
        pass


def test_output_that_cannot_be_written_is_exit_4(tmp_path, monkeypatch, capsys):
    feature = _write(tmp_path / "f.json", FEATURE)
    monkeypatch.setattr(sys, "stdout", _Unwritable())
    assert decode_host.main([*GEOJSON, *AS_OF, "--input", feature]) == 4
    assert capsys.readouterr().err == "synapse-decode: cannot write output: Broken pipe\n"
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace())
    assert decode_host.main([*GEOJSON, *AS_OF, "--input", feature]) == 4
    assert capsys.readouterr().err == "synapse-decode: cannot write output: stdout is closed\n"


# -- the generic machinery, with a hosted double -------------------------------------------------

T_RECEIVED = "2026-09-11T10:05:00Z"
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")


class DoubleAdapter:
    """Not an `Adapter` subclass, so it registers nothing: what the host needs of a class, and an
    Event per frame that shows every value the host handed it."""

    file_bound = 64
    unwrapped_bound = 64

    @classmethod
    def capabilities(cls):
        return types.SimpleNamespace(limits=types.SimpleNamespace(max_input_bytes=cls.file_bound))

    def __init__(
        self, clock, *, synthetic, station_table=None, request=(), frame=None, frame_sha256=None
    ):
        self._clock, self._synthetic = clock, synthetic
        self._table, self._request, self._frame = station_table, request, frame
        self._frame_sha256 = frame_sha256

    def to_cdm(self, raw: bytes):
        if raw.startswith(b"bad"):
            raise ValueError(f"refused {raw!r}")
        key = raw.decode("ascii")
        return [
            Event(
                source=SourceRef(
                    system="DOUBLE",
                    adapter="double",
                    adapter_version="1.0.0",
                    synthetic=self._synthetic,
                    record_index=self._frame,
                ),
                source_ids=[SourceId(system="DOUBLE", external_id=key)],
                event_id=uuid.uuid5(NAMESPACE, key),
                event_type=EventType.DETECTION,
                severity=Severity.INFO,
                observed_at="2026-09-11T10:00:00.000Z",
                received_at=self._clock(),
                payload={
                    "frame_sha256": self._frame_sha256,
                    "request": dict(self._request),
                    "stations": None
                    if self._table is None
                    else [row.station_id for row in self._table.rows],
                },
            )
        ]


def _host_the_double(
    monkeypatch, file_bound=64, unwrapped_bound=64, reads_clock=True, frame_digest=None
):
    double = type("Bounded", (DoubleAdapter,), {"file_bound": file_bound})
    entry = decode_host.Hosted(
        name="double",
        load=lambda: double,
        arguments=frozenset({"received_at", "station_table", "request"}),
        required=frozenset({"received_at"}) if reads_clock else frozenset(),
        prepare=lambda c: {
            "synthetic": c.synthetic,
            "station_table": c.station_table,
            "request": c.request,
        },
        injects_source_hash=False,
        reads_clock=reads_clock,
        framer=lambda data: data.split(b"\n"),
        frame_argument="frame",
        max_unwrapped_bytes=lambda cls: unwrapped_bound,
        frame_digest_argument=frame_digest,
    )
    monkeypatch.setattr(decode_host, "HOSTED", types.MappingProxyType({"double": entry}))


def _run_double(capsysbinary, *extra) -> tuple[int, bytes, bytes]:
    status = decode_host.main(["decode", "--adapter", "double", "--synthetic", *extra])
    captured = capsysbinary.readouterr()
    return status, captured.out, captured.err


def test_frames_are_decoded_in_order_with_their_ordinal_and_the_injected_receipt_instant(
    tmp_path, monkeypatch, capsysbinary
):
    _host_the_double(monkeypatch)
    path = _write(tmp_path / "frames", b"f0\nf1\nf2")
    status, out, err = _run_double(capsysbinary, "--input", path, "--received-at", T_RECEIVED)
    assert (status, err) == (0, b"")
    objects = json.loads(out)
    assert [o["source_ids"][0]["external_id"] for o in objects] == ["f0", "f1", "f2"]
    assert [o["source"]["record_index"] for o in objects] == [0, 1, 2]
    assert {o["received_at"] for o in objects} == {"2026-09-11T10:05:00.000Z"}


def test_a_frame_digest_is_passed_exactly_when_the_frame_is_not_the_file(
    tmp_path, monkeypatch, capsysbinary
):
    # 2026-10-15 (R3): `frame_sha256` was documented as the host's and nothing computed it. An
    # entry that names a frame-digest argument is given each frame's SHA-256 when a framer cut
    # the file or a container was unwrapped, and nothing when the frame is the file as read.
    _host_the_double(monkeypatch, frame_digest="frame_sha256")
    cut = _write(tmp_path / "frames", b"f0\nf1")
    status, out, err = _run_double(capsysbinary, "--input", cut, "--received-at", T_RECEIVED)
    assert (status, err) == (0, b"")
    assert [o["payload"]["frame_sha256"] for o in json.loads(out)] == [
        hashlib.sha256(b"f0").hexdigest(),
        hashlib.sha256(b"f1").hexdigest(),
    ]
    whole = _write(tmp_path / "one", b"f0")
    status, out, err = _run_double(capsysbinary, "--input", whole, "--received-at", T_RECEIVED)
    assert (status, err) == (0, b"")
    assert [o["payload"]["frame_sha256"] for o in json.loads(out)] == [None]
    packed = _write(tmp_path / "one.gz", gzip.compress(b"f0", mtime=0))
    status, out, err = _run_double(
        capsysbinary, "--input", packed, "--container", "gzip", "--received-at", T_RECEIVED
    )
    assert (status, err) == (0, b"")
    assert [o["payload"]["frame_sha256"] for o in json.loads(out)] == [
        hashlib.sha256(b"f0").hexdigest()
    ]
    # An entry that names no frame-digest argument is never handed one.
    _host_the_double(monkeypatch)
    status, out, err = _run_double(capsysbinary, "--input", cut, "--received-at", T_RECEIVED)
    assert (status, err) == (0, b"")
    assert [o["payload"]["frame_sha256"] for o in json.loads(out)] == [None, None]


def test_a_frame_refused_names_its_ordinal_and_never_its_bytes(tmp_path, monkeypatch, capsysbinary):
    _host_the_double(monkeypatch)
    path = _write(tmp_path / "frames", b"f0\nbad-" + SECRET.encode())
    status, out, err = _run_double(capsysbinary, "--input", path, "--received-at", T_RECEIVED)
    assert (status, out) == (3, b"")
    assert err == b"synapse-decode: frame 1 refused by double: ValueError\n"


def test_an_adapter_that_reads_the_clock_requires_the_receipt_instant(
    tmp_path, monkeypatch, capsysbinary
):
    _host_the_double(monkeypatch)
    path = _write(tmp_path / "frames", b"f0")
    assert _run_double(capsysbinary, "--input", path) == (
        2,
        b"",
        b"synapse-decode: double requires --received-at\n",
    )
    assert _run_double(capsysbinary, "--input", path, "--received-at", "2026-09-11T10:05:00") == (
        2,
        b"",
        b"synapse-decode: --received-at is not an RFC 3339 instant with seconds and a zone\n",
    )


def test_an_entry_that_says_its_adapter_reads_no_clock_is_a_defect_when_it_does(
    tmp_path, monkeypatch, capsysbinary
):
    _host_the_double(monkeypatch, reads_clock=False)
    path = _write(tmp_path / "frames", b"f0")
    with pytest.raises(RuntimeError, match="the adapter read the clock"):
        decode_host.main(["decode", "--adapter", "double", "--synthetic", "--input", path])


def test_a_station_table_is_loaded_as_the_contract_states_it_or_refused_without_its_content(
    tmp_path, monkeypatch, capsysbinary
):
    _host_the_double(monkeypatch)
    frames = _write(tmp_path / "frames", b"f0")
    table = {
        "name": "synthetic table",
        "basis": "written for this test",
        "rows": [{"station_id": "EX001", "lat": 57.25, "lon": 21.5}],
    }
    good = _write(tmp_path / "table.json", json.dumps(table).encode())
    status, out, err = _run_double(
        capsysbinary, "--input", frames, "--received-at", T_RECEIVED, "--station-table", good
    )
    assert (status, err) == (0, b"")
    assert json.loads(out)[0]["payload"]["stations"] == ["EX001"]
    twice = dict(table, rows=table["rows"] * 2)
    bad = _write(tmp_path / "bad.json", json.dumps(twice).encode())
    assert _run_double(
        capsysbinary, "--input", frames, "--received-at", T_RECEIVED, "--station-table", bad
    ) == (2, b"", b"synapse-decode: --station-table is not a station table the contract accepts\n")


@pytest.mark.parametrize(
    "requests, status",
    [
        ([f"api_key={SECRET}", "datum=MLLW"], 0),
        (["Datum=MLLW"], 2),
        (["datum"], 2),
        (["datum=MLLW", "datum=NAVD"], 2),
        ([f"datum={'x' * 1025}"], 2),
    ],
    ids=["declared", "upper-case-key", "no-value", "twice", "long-value"],
)
def test_request_parameters_are_key_value_pairs_and_a_value_is_never_echoed(
    tmp_path, monkeypatch, capsysbinary, requests, status
):
    _host_the_double(monkeypatch)
    frames = _write(tmp_path / "frames", b"f0")
    flags = [f"--request={r}" for r in requests]
    result = _run_double(capsysbinary, "--input", frames, "--received-at", T_RECEIVED, *flags)
    assert result[0] == status
    if status == 0:
        assert json.loads(result[1])[0]["payload"]["request"] == {
            "api_key": SECRET,
            "datum": "MLLW",
        }
        assert result[2] == b""
    else:
        assert result[1] == b""
        assert result[2] in (
            b"synapse-decode: a --request is not KEY=VALUE with a lower-case key and a value of "
            b"at most 1024 characters\n",
            b"synapse-decode: a --request key is given twice\n",
        )
        assert b"MLLW" not in result[2] and b"NAVD" not in result[2]


def test_the_hosted_table_and_the_bounds_are_the_ones_documented():
    assert sorted(decode_host.HOSTED) == [
        "airnow_hourly",
        "cog",
        "coops_csv",
        "dis7",
        "geojson",
        "grib2",
        "iem_n0q",
        "ndbc_stdmet",
        "nexrad2",
        "readsb_trace",
    ]
    # cog and iem_n0q (2026-10-17): the receipt instant always and the file's digest injected;
    # cog's identifiers and the role of its optional instant as request parameters; iem_n0q's
    # archive slot as --at/--basis, required, and the frame's own digest when it is not the file.
    cog_row, n0q_row = decode_host.HOSTED["cog"], decode_host.HOSTED["iem_n0q"]
    assert [
        (
            row.arguments,
            row.required,
            row.injects_source_hash,
            row.reads_clock,
            row.framer,
            row.frame_argument,
            row.frame_digest_argument,
            row.frame_offset_argument,
        )
        for row in (cog_row, n0q_row)
    ] == [
        (
            frozenset({"received_at", "time", "request"}),
            frozenset({"received_at"}),
            True,
            True,
            decode_host.whole_file,
            None,
            None,
            None,
        ),
        (
            frozenset({"received_at", "time"}),
            frozenset({"received_at", "time"}),
            True,
            True,
            decode_host.whole_file,
            None,
            "frame_sha256",
            None,
        ),
    ]
    assert (decode_host.COG_REQUEST_KEYS, decode_host.COG_TIME_ROLES) == (
        ("band_file", "granule", "time"),
        ("sensing_time", "as_of"),
    )
    # grib2 (2026-10-17): the receipt instant; the file's digest injected; the file cut into its
    # messages, each given its ordinal, its first octet and, when it is not the file, its digest.
    grib = decode_host.HOSTED["grib2"]
    assert (
        grib.arguments,
        grib.required,
        grib.injects_source_hash,
        grib.reads_clock,
        grib.framer,
        grib.frame_argument,
        grib.frame_digest_argument,
        grib.frame_offset_argument,
    ) == (
        frozenset({"received_at"}),
        frozenset({"received_at"}),
        True,
        True,
        decode_host.grib_messages,
        "message_ordinal",
        "frame_sha256",
        "byte_offset",
    )
    assert grib.prepare(decode_host.Context(synthetic=True)) == {"synthetic": True}
    assert [
        decode_host.HOSTED[n].frame_offset_argument for n in sorted(decode_host.HOSTED) if n != "grib2"
    ] == [None] * 9
    # The three station-text adapters (2026-10-15): the receipt instant always, the digest and
    # the frame's own digest injected; a request for the two whose payload does not state it, and
    # a station table for the position no payload of the three states.
    station_text = {
        name: (
            decode_host.HOSTED[name].arguments,
            decode_host.HOSTED[name].required,
            decode_host.HOSTED[name].injects_source_hash,
            decode_host.HOSTED[name].reads_clock,
            decode_host.HOSTED[name].frame_argument,
            decode_host.HOSTED[name].frame_digest_argument,
        )
        for name in ("ndbc_stdmet", "coops_csv", "airnow_hourly")
    }
    assert station_text == {
        "ndbc_stdmet": (
            frozenset({"received_at", "request", "station_table"}),
            frozenset({"received_at", "request"}),
            True,
            True,
            None,
            "frame_sha256",
        ),
        "coops_csv": (
            frozenset({"received_at", "request", "station_table"}),
            frozenset({"received_at", "request"}),
            True,
            True,
            None,
            "frame_sha256",
        ),
        "airnow_hourly": (
            frozenset({"received_at", "station_table"}),
            frozenset({"received_at"}),
            True,
            True,
            None,
            "frame_sha256",
        ),
    }
    dis7, geojson = decode_host.HOSTED["dis7"], decode_host.HOSTED["geojson"]
    readsb = decode_host.HOSTED["readsb_trace"]
    nexrad2 = decode_host.HOSTED["nexrad2"]
    assert (
        nexrad2.arguments,
        nexrad2.required,
        nexrad2.injects_source_hash,
        nexrad2.reads_clock,
        nexrad2.frame_argument,
        nexrad2.frame_digest_argument,
    ) == (frozenset({"received_at"}), frozenset({"received_at"}), True, True, None, "frame_sha256")
    assert nexrad2.prepare(decode_host.Context(synthetic=True)) == {"synthetic": True}
    assert [decode_host.HOSTED[n].frame_digest_argument for n in ("dis7", "geojson")] == [
        None,
        None,
    ]
    assert readsb.frame_digest_argument is None
    assert (
        readsb.arguments,
        readsb.required,
        readsb.injects_source_hash,
        readsb.reads_clock,
        readsb.frame_argument,
    ) == (frozenset({"received_at"}), frozenset({"received_at"}), False, True, None)
    assert readsb.prepare(decode_host.Context(synthetic=False)) == {"synthetic": False}
    assert (dis7.arguments, dis7.required, dis7.injects_source_hash) == (
        frozenset({"time", "session"}),
        frozenset({"time", "session"}),
        True,
    )
    assert (geojson.arguments, geojson.required, geojson.injects_source_hash) == (
        frozenset({"time"}),
        frozenset(),
        False,
    )
    assert dis7.framer(b"abc") == [b"abc"]
    assert (
        decode_host.MAX_UNWRAP_RATIO,
        decode_host.MAX_TAR_MEMBERS,
        decode_host.MAX_CONTEXT_FILE_BYTES,
        decode_host.MAX_CONTEXT_DEPTH,
        decode_host.MAX_REQUEST_VALUE,
        decode_host.UNWRAP_CHUNK,
    ) == (256, 4096, 1048576, 16, 1024, 65536)
    # Every host bound has its basis, as a LimitBasis (checkpoint H-07, 2026-10-15): until then
    # three had a prose basis and three had none.
    assert sorted(decode_host.BOUNDS_BASIS) == [
        "MAX_CONTEXT_DEPTH",
        "MAX_CONTEXT_FILE_BYTES",
        "MAX_REQUEST_VALUE",
        "MAX_TAR_MEMBERS",
        "MAX_UNWRAP_RATIO",
        "UNWRAP_CHUNK",
    ]
    tests = {}
    for name, basis in decode_host.BOUNDS_BASIS.items():
        assert type(basis) is LimitBasis, name
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP, name
        assert basis.source.endswith(
            "This is an IMPLEMENTATION CAP and is NOT a format's normative maximum."
        ), name
        module, _, test = basis.test.partition("::")
        assert module == "tests/test_cdm_decode_host.py", name
        assert callable(globals().get(test)), (name, test)
        tests[name] = test
    assert tests == {
        "MAX_CONTEXT_DEPTH": "test_a_manifest_row_is_one_strict_object_with_a_digest_and_no_credential",
        "MAX_CONTEXT_FILE_BYTES": "test_a_manifest_row_past_its_bound_is_exit_2",
        "MAX_REQUEST_VALUE": "test_request_parameters_are_key_value_pairs_and_a_value_is_never_echoed",
        "MAX_TAR_MEMBERS": "test_a_tar_is_bounded_by_its_member_count_its_member_size_and_its_own_shape",
        "MAX_UNWRAP_RATIO": "test_gzip_is_bounded_by_the_adapters_bound_and_by_the_ratio",
        "UNWRAP_CHUNK": "test_gzip_input_is_fed_in_bounded_steps_and_the_work_is_linear",
    }
    # R1b review F-1: the tar count's basis quotes the file bounds the hosted adapters declare,
    # each as it is, rather than one bound "every hosted adapter declares".
    assert (
        "4096 headers of 512 octets are 2 MiB of headers alone, a quarter of the 8 MiB file bound "
        "geojson, readsb_trace and the three station-text adapters declare (dis7 declares 4224 "
        "octets and nexrad2 32 MiB)."
    ) in decode_host.BOUNDS_BASIS["MAX_TAR_MEMBERS"].source
    assert "every hosted adapter" not in decode_host.BOUNDS_BASIS["MAX_TAR_MEMBERS"].source
    # The ratio's basis quotes the two decompression bounds the rulings hold, which it sits above.
    ratio = decode_host.BOUNDS_BASIS["MAX_UNWRAP_RATIO"].source
    assert "readsb_trace 8 MiB of input to 64 MiB inflated (8x)" in ratio
    assert "iem_n0q 8 MiB to 80 MiB (10x" in ratio
    assert 256 > 64 // 8 and 256 > 80 // 8
    assert (
        decode_host.EXIT_OK,
        decode_host.EXIT_USAGE,
        decode_host.EXIT_REJECTED,
        decode_host.EXIT_IO,
    ) == (0, 2, 3, 4)
