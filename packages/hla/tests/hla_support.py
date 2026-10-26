"""Test support for synapse-hla: resource paths, strict loaders, case binding, BLOCKED, the trace.

Nothing here is product code. It is imported by the test modules (through `pythonpath` in
pyproject.toml) and by `conftest.py`.

WHERE THINGS ARE READ FROM
--------------------------
The vendored contract — schemas, fixtures, `pins.json` — is read from the PACKAGE through
`importlib.resources`, never from the handoff bundle, so the tests run on a clean checkout with
the bundle nowhere in sight (D-05). The contract data of the tests themselves (`tests/contract/`)
and the example configurations (`examples/`) are not package data and are read from the tree.
The RPR FOM modules are in neither place: `fom_modules()` finds them through
`SYNAPSE_HLA_FOM_DIR` and checks each against `pins.json` before handing it out (D-07).

THE ONE SKIP
------------
`blocked()` is the only way a test of this package may skip, and it may skip only for a resource
that is genuinely absent; the reason always starts with `BLOCKED: `. The offline group needs
nothing but the FOM directory, so a skip there is a failure of the run, not a result.

THE TRACE
---------
`case()` binds a test to acceptance case ids; `trace_problems()` is the ratchet of D-11 as a pure
function over the contract data and the bindings a real collection produced. Its rules are listed
in its docstring, and each has a test of its own in `test_hla_trace.py`.

THE REDUCER'S CONTRACT, CHECKED ON EVERY RECORD
-----------------------------------------------
`reduce_checked` is how every test of round R4 calls `reduce_frame`: it asserts that neither input
changed and that the records share nothing with the new state, and it runs `check_frame_records`
on what came back: the output, snapshot and diagnostic schemas (format checker on) and the prose
the schemas are too loose for (RED-16, RED-03, R33, SPEC:283). `Scenario` builds a capture with
the capture builder below and reduces it frame by frame through `reduce_checked`, then holds the
whole stream to `check_stream`. `ReferenceConsumer` is RED-14's test-only consumer. None of this
is product code, and none of it borrows the product's rules: the catalogue, the reason
vocabulary and the ordering rules are written out here again.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import importlib.resources
import json
import math
import os
import pathlib
import re
import struct
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

TESTS_DIR = pathlib.Path(__file__).resolve().parent
PACKAGE_ROOT = TESTS_DIR.parent
CONTRACT_DIR = TESTS_DIR / "contract"
EXAMPLES_DIR = PACKAGE_ROOT / "examples"
SOCKGUARD_DIR = TESTS_DIR / "sockguard"

#: The environment variable naming the directory that holds the five RPR FOM modules (D-07).
FOM_DIR_VARIABLE = "SYNAPSE_HLA_FOM_DIR"

#: The five modules in the order R04 prescribes. Their digests come from the packaged pins.json.
FOM_MODULE_ORDER = (
    "RPR-Foundation_v2.0.xml",
    "RPR-Enumerations_v2.0.xml",
    "RPR-Base_v2.0.xml",
    "RPR-Physical_v2.0.xml",
    "RPR-Switches_v2.0.xml",
)

#: The rounds of the run, in order. Every round key of pending.json is one of these.
ROUNDS = tuple(f"R{i}" for i in range(10))


# ----------------------------------------------------------------------------- package resources

def package_resource(*parts: str):
    """A Traversable for a file inside the installed-or-imported `synapse_hla` package."""
    node = importlib.resources.files("synapse_hla")
    for part in parts:
        node = node.joinpath(part)
    return node


def package_bytes(*parts: str) -> bytes:
    return package_resource(*parts).read_bytes()


def package_dir_names(*parts: str) -> list[str]:
    """The names of the regular files directly inside a package directory, sorted."""
    return sorted(p.name for p in package_resource(*parts).iterdir() if p.is_file())


# --------------------------------------------------------------------------------- strict JSON

class StrictJsonError(ValueError):
    """A fixture or contract file that is not strict JSON."""


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise StrictJsonError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _no_constant(name):
    raise StrictJsonError(f"non-finite JSON number {name}")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise StrictJsonError("a JSON number overflows to a non-finite float")
    return value


def _no_lone_surrogate(value):
    """Walk a parsed document; refuse any string (key or value) holding a lone surrogate."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in item):
                raise StrictJsonError("a string holds a lone surrogate escape")
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def strict_json(data: bytes):
    """Parse UTF-8 JSON refusing what Python's `json` would let through and R07/R15 refuse.

    Refused: a BOM, invalid UTF-8, duplicate keys, the NaN/Infinity literals, a number that
    overflows to infinity (`1e999`), and a `\\uD800`-style escape that decodes to a lone
    surrogate (a string no UTF-8 writer can emit). A fixture that relied on any of these would
    be a fixture the product's own strict reader must refuse.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        raise StrictJsonError("byte order mark")
    text = data.decode("utf-8", errors="strict")
    value = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant,
                       parse_float=_finite_float)
    _no_lone_surrogate(value)
    return value


def canonical(obj) -> bytes:
    """The canonical serialisation of R15, written out here independently of the product."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonl_lines(data: bytes) -> list[bytes]:
    """The lines of a JSONL file: LF-terminated, none empty, the last one terminated too.

    A CR anywhere is refused: inside a JSON string it must be escaped, so a raw CR byte can only
    be a CRLF line end or stray whitespace, and the capture's hash chain covers exact line bytes.
    """
    if b"\r" in data:
        raise StrictJsonError("a carriage return")
    if not data.endswith(b"\n"):
        raise StrictJsonError("the last line is not LF-terminated")
    lines = data[:-1].split(b"\n")
    if any(not line for line in lines):
        raise StrictJsonError("blank line")
    return lines


def fixture_json(name: str):
    return strict_json(package_bytes("fixtures", name))


def fixture_jsonl(name: str) -> list[tuple[bytes, object]]:
    """`(raw line without LF, parsed object)` for every line of a packaged JSONL fixture."""
    return [(line, strict_json(line)) for line in jsonl_lines(package_bytes("fixtures", name))]


def contract_json(name: str):
    return strict_json((CONTRACT_DIR / name).read_bytes())


def example_json(name: str):
    return strict_json((EXAMPLES_DIR / name).read_bytes())


# ------------------------------------------------------------------------------------- schemas

def schema_names() -> list[str]:
    return [n for n in package_dir_names("schemas") if n.endswith(".schema.json")]


def schemas() -> dict[str, dict]:
    """Every packaged schema by file name."""
    return {name: strict_json(package_bytes("schemas", name)) for name in schema_names()}


def registry() -> Registry:
    """The bundle's schemas, resolvable by file name (their `$ref`s) and by `$id`."""
    reg = Registry()
    for name, schema in schemas().items():
        resource = Resource.from_contents(schema)
        reg = reg.with_resource(name, resource)
        reg = reg.with_resource(schema["$id"], resource)
    return reg


def local_schema(name: str) -> dict:
    """One of the product's own schemas (CR-L03), from `local_schemas/`."""
    return strict_json(package_bytes("local_schemas", name))


def local_validator(name: str) -> Draft202012Validator:
    """A validator of one product schema whose `$ref`s resolve among the bundle's schemas and the
    other product schemas (by `$id`), format checker on as in `validator`."""
    reg = registry()
    for other in package_dir_names("local_schemas"):
        schema = local_schema(other)
        reg = reg.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(local_schema(name), registry=reg, format_checker=FormatChecker())


def validator(schema_file: str) -> Draft202012Validator:
    """A Draft 2020-12 validator with the format checker on.

    The format checker checks `uuid` here and does NOT check `date-time` (no rfc3339-validator is
    installed; OPS-03). Dates are therefore never accepted on the strength of this validator:
    `check_utc_timestamp()` is the authority for every date the tests look at.
    """
    return Draft202012Validator(schemas()[schema_file], registry=registry(),
                                format_checker=FormatChecker())


_UTC_MICRO = re.compile(r"(?P<y>[0-9]{4})-(?P<mo>[0-9]{2})-(?P<d>[0-9]{2})T(?P<h>[0-9]{2}):"
                        r"(?P<mi>[0-9]{2}):(?P<s>[0-9]{2})\.(?P<f>[0-9]{6}|[0-9]{3})Z")


def check_utc_timestamp(value: str, *, digits: int) -> None:
    """Assert `value` is `YYYY-MM-DDTHH:MM:SS.<digits>Z`, a real UTC instant, years 1970-9998.

    Written as explicit integer checks rather than `datetime.strptime`, whose `%f` accepts one
    to six digits and whose `%Y` accepts years below 1970 (CR-L05, OPS-03).
    """
    m = _UTC_MICRO.fullmatch(value)
    assert m is not None and len(m.group("f")) == digits, f"{value!r} is not the {digits}-digit form"
    y, mo, d = int(m.group("y")), int(m.group("mo")), int(m.group("d"))
    h, mi, s = int(m.group("h")), int(m.group("mi")), int(m.group("s"))
    assert 1970 <= y <= 9998, f"{value!r}: year outside 1970-9998"
    assert 1 <= mo <= 12, f"{value!r}: month"
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[mo - 1]
    assert 1 <= d <= days, f"{value!r}: day"
    assert h <= 23 and mi <= 59 and s <= 59, f"{value!r}: time of day"


# ------------------------------------------------------------------------------ BLOCKED and FOM

def blocked(resource: str):
    """Report the calling test as BLOCKED on an absent external resource. The only skip (D-07)."""
    pytest.skip(f"BLOCKED: {resource}")


def packaged_pins() -> dict[str, dict]:
    """The packaged pins.json, by file name."""
    doc = strict_json(package_bytes("pins.json"))
    return {entry["path"]: entry for entry in doc["files"]}


def fom_modules(environ=None) -> list[pathlib.Path]:
    """The five FOM modules in R04 order, each checked against pins.json before it is returned.

    An unset variable, a directory that is not there or a module that is not in it is an absent
    resource: BLOCKED. A module that IS there with other bytes is not absent, it is wrong, and
    fails the test.
    """
    env = os.environ if environ is None else environ
    raw = env.get(FOM_DIR_VARIABLE, "")
    if not raw:
        blocked(f"{FOM_DIR_VARIABLE} is not set")
    root = pathlib.Path(raw)
    if not root.is_dir():
        blocked(f"{FOM_DIR_VARIABLE} does not name a directory")
    pins = packaged_pins()
    out = []
    for name in FOM_MODULE_ORDER:
        path = root / name
        if not path.is_file():
            blocked(f"FOM module {name} is not in {FOM_DIR_VARIABLE}")
        data = path.read_bytes()
        assert len(data) == pins[name]["bytes"] and sha256_hex(data) == pins[name]["sha256"], (
            f"FOM module {name} in {FOM_DIR_VARIABLE} does not match pins.json")
        out.append(path)
    return out


# ------------------------------------------------------------- external tools at fixed places

#: The external programs some tests run, each looked for at fixed places only, never through
#: PATH (the rule OPV-04 sets for the product's own executables): the first place that holds
#: an executable file. macOS keeps lsof in /usr/sbin, Ubuntu's lsof package in /usr/bin; cs2cs
#: is Homebrew's on the development Mac (/opt/homebrew/bin, /usr/local/bin on Intel) and the
#: proj-bin package's on Ubuntu; cmake likewise (Homebrew, or the cmake package); uv is
#: Homebrew's or the one its own installer puts in ~/.local/bin. The Linux reference run's
#: finding F3: the Mac-only places of R8 made these tests fail or report BLOCKED on Ubuntu.
TOOL_PLACES = {
    "lsof": ("/usr/sbin/lsof", "/usr/bin/lsof"),
    "cs2cs": ("/opt/homebrew/bin/cs2cs", "/usr/local/bin/cs2cs", "/usr/bin/cs2cs"),
    "cmake": ("/opt/homebrew/bin/cmake", "/usr/local/bin/cmake", "/usr/bin/cmake"),
    "uv": ("/opt/homebrew/bin/uv", "/usr/local/bin/uv", "~/.local/bin/uv"),
}


def tool_place(name: str) -> pathlib.Path | None:
    """The first fixed place of `name` that holds an executable file, or None."""
    for place in TOOL_PLACES[name]:
        path = pathlib.Path(place).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


#: Homebrew's prefix on Apple silicon. A document names a place under it by Homebrew's own
#: variable, `$HOMEBREW_PREFIX`: R49 admits no machine's absolute path in a document.
HOMEBREW_PREFIX = "/opt/homebrew"


def place_text(name: str, path: pathlib.Path) -> str:
    """The fixed place of `name` that `path` is, as a document may print it: as TOOL_PLACES
    writes it, with Homebrew's prefix spelled `$HOMEBREW_PREFIX`."""
    for place in TOOL_PLACES[name]:
        if pathlib.Path(place).expanduser() == path:
            if place.startswith(HOMEBREW_PREFIX + "/"):
                return "$HOMEBREW_PREFIX" + place[len(HOMEBREW_PREFIX):]
            return place
    raise ValueError(f"{path} is not a fixed place of {name}")


def fixed_tool(name: str) -> pathlib.Path:
    """`tool_place(name)`, or the calling test reported BLOCKED when it is at none (D-07)."""
    path = tool_place(name)
    if path is None:
        blocked(f"{name} is at none of its fixed places {', '.join(TOOL_PLACES[name])}")
    return path


# ------------------------------------------------------------------------ native executables (R7)

#: OPV-04 and D-20: the executables the `rti` group needs, each named by an absolute path. The
#: worker's variable is the host's own (`WORKER_VARIABLE` below); the harness's is a test-only
#: variable of round R7 (NAT-07 a), never read by the package.
HARNESS_VARIABLE = "SYNAPSE_HLA_HARNESS"
RTINODE_VARIABLE = "SYNAPSE_HLA_RTINODE"


def native_executable(variable: str, environ=None) -> pathlib.Path:
    """The executable `variable` names. Unset, or naming no file, is an absent resource: BLOCKED
    (D-07). A relative path, or a file that is not executable, is not absent but wrong, and fails
    the test."""
    env = os.environ if environ is None else environ
    raw = env.get(variable, "")
    if not raw:
        blocked(f"{variable} is not set")
    path = pathlib.Path(raw)
    assert path.is_absolute(), f"{variable} is not an absolute path"
    if not path.is_file():
        blocked(f"{variable} names no file")
    assert os.access(path, os.X_OK), f"{variable} is not executable"
    return path


# --------------------------------------------------------------------------- child processes

def child_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment of a child interpreter: the socket guard first on PYTHONPATH, no bytecode."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SOCKGUARD_DIR) + (os.pathsep + existing if existing else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def run_python(args: list[str], *, cwd: pathlib.Path, extra_env: dict[str, str] | None = None,
               timeout: float = 300) -> subprocess.CompletedProcess:
    """Run this interpreter on `args` (an argument vector, never a shell line) under the guard."""
    return subprocess.run([sys.executable, *args], cwd=cwd, env=child_environment(extra_env),
                          capture_output=True, text=True, timeout=timeout, check=False)


# ------------------------------------------------------------------- strict values and encodings

def assert_strict_equal(got, expected, where: str = "$") -> None:
    """Equality that `==` is too lenient for: types exactly, dict keys in order, the sign of zero.

    `==` says `True == 1`, `1 == 1.0` and `-0.0 == 0.0`, and a decoder that returned any of
    those in place of the other would pass it. Here a bool is not an int, an int is not a float,
    a dict must have the same keys in the same order, and a zero must have the same sign. NaN is
    never an expected value in this package, so it is never equal to anything.
    """
    assert type(got) is type(expected), f"{where}: {type(got).__name__} != {type(expected).__name__}"
    if isinstance(expected, dict):
        assert list(got) == list(expected), f"{where}: keys {list(got)} != {list(expected)}"
        for key in expected:
            assert_strict_equal(got[key], expected[key], f"{where}.{key}")
    elif isinstance(expected, list):
        assert len(got) == len(expected), f"{where}: length {len(got)} != {len(expected)}"
        for i, (g, e) in enumerate(zip(got, expected)):
            assert_strict_equal(g, e, f"{where}[{i}]")
    elif isinstance(expected, float):
        assert got == expected and math.copysign(1.0, got) == math.copysign(1.0, expected), (
            f"{where}: {got!r} != {expected!r}")
    else:
        assert got == expected, f"{where}: {got!r} != {expected!r}"


#: The Spatial variant table of SPEC:99-108 as the tests read it, independently of the product:
#: algorithm -> (frame, total bytes, offset of velocity, of acceleration, of angular velocity),
#: None where the variant has no such field. Offsets from SPEC:88-97: velocity at 48, the next
#: triple at 60, angular velocity at 72 in the RV variants.
SPATIAL_TABLE = {
    1: ("WORLD", 48, None, None, None),
    2: ("WORLD", 60, 48, None, None),
    3: ("WORLD", 72, 48, None, 60),
    4: ("WORLD", 84, 48, 60, 72),
    5: ("WORLD", 72, 48, 60, None),
    6: ("BODY", 60, 48, None, None),
    7: ("BODY", 72, 48, None, 60),
    8: ("BODY", 84, 48, 60, 72),
    9: ("BODY", 72, 48, 60, None),
}


def spatial_float_offsets(algorithm: int) -> list[int]:
    """Every interpreted float offset of a variant, ascending: the order SPEC:281 checks them."""
    _, _, v_at, a_at, w_at = SPATIAL_TABLE[algorithm]
    offsets = [8, 16, 24, 36, 40, 44]
    for start in (v_at, a_at, w_at):
        if start is not None:
            offsets += [start, start + 4, start + 8]
    return sorted(offsets)


def encode_spatial(algorithm: int, position=(6378137.0, 0.0, 0.0), orientation=(0.0, 0.0, 0.0),
                   velocity=None, acceleration=None, angular_velocity=None, *, frozen: int = 0,
                   padding: bytes = bytes(10)) -> bytes:
    """A Spatial value written by the tests' own encoder from SPEC:88-108, never by the product.

    Floats go in with explicit big-endian `>d`/`>f`; a value that is not a binary32 is rounded to
    one by `struct`, which is what a publisher's encoder would do. `padding` is the ten
    uninterpreted bytes in wire order: bytes 1-7, then 33-35.
    """
    frame, total, v_at, a_at, w_at = SPATIAL_TABLE[algorithm]
    out = bytearray(total)
    out[0] = algorithm
    assert len(padding) == 10
    out[1:8] = padding[:7]
    out[33:36] = padding[7:]
    out[32] = frozen
    for i, number in enumerate(position):
        struct.pack_into(">d", out, 8 + 8 * i, number)
    for i, number in enumerate(orientation):
        struct.pack_into(">f", out, 36 + 4 * i, number)
    for start, triple in ((v_at, velocity), (a_at, acceleration), (w_at, angular_velocity)):
        if start is None:
            assert triple is None, "this variant has no such field"
            continue
        assert triple is not None, "this variant needs the field"
        for i, number in enumerate(triple):
            struct.pack_into(">f", out, start + 4 * i, number)
    return bytes(out)


def reencode_spatial(value: dict) -> bytes:
    """The wire bytes a decoded Spatial value stands for, rebuilt by the tests' encoder.

    Exact widening makes this a true inverse: every decoded binary32 is a binary32, so packing it
    again gives the original four bytes, and padding comes back from `padding_hex`. A decoder
    that normalised a zero, a padding byte or a float's last bits would not survive the trip.
    """
    padding = bytes.fromhex(value["padding_hex"])
    return encode_spatial(value["algorithm"], value["position_ecef_m"], value["orientation_rad"],
                          value["velocity_mps"], value["acceleration_mps2"],
                          value["angular_velocity_radps"], frozen=int(value["frozen"]),
                          padding=padding)


# ------------------------------------------------------------------------------------ identity

def rfc4122_uuid5(namespace: str, name: str) -> str:
    """A name-based UUID by RFC 4122 section 4.3, written out here and not taken from `uuid`.

    SHA-1 of the namespace's 16 octets followed by the name's UTF-8 octets; the first 16 octets
    of the digest, with the version nibble set to 5 (octet 6) and the variant bits to 10
    (octet 8); written as lowercase 8-4-4-4-12 hexadecimal. The tests derive an expected
    `entity_id` with it, so that the product's `uuid.uuid5` and the SDK's `ids.derive` are each
    held to a third, independent spelling of R26.
    """
    octets = bytearray(hashlib.sha1(bytes.fromhex(namespace.replace("-", ""))
                                    + name.encode("utf-8")).digest()[:16])
    octets[6] = (octets[6] & 0x0F) | 0x50
    octets[8] = (octets[8] & 0x3F) | 0x80
    h = octets.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


# --------------------------------------------------------------------------------- case binding

#: The shape of an acceptance case id: G-R01..G-R50 and the A-, V- and N- families.
CASE_ID = re.compile(r"[GAVN]-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
#: The shape of a paragraph key of paragraph-map.json.
PARAGRAPH_KEY = re.compile(r"SPEC:[1-9][0-9]*")


def case(*ids: str, paragraphs: tuple[str, ...] = ()):
    """Bind the decorated test (or a `pytest.param`, via `marks=`) to acceptance case ids.

    `paragraphs` names the continuation paragraphs of `paragraph-map.json` the test holds for the
    gates among `ids`; a gate counts as covering a paragraph only through a test that names it.
    Malformed arguments raise at import time, so a typo never reaches the trace as a silent miss.
    """
    if not ids:
        raise ValueError("case() needs at least one case id")
    for value in ids:
        if type(value) is not str or CASE_ID.fullmatch(value) is None:
            raise ValueError(f"malformed case id {value!r}")
    if len(set(ids)) != len(ids):
        raise ValueError("case() names an id twice")
    if type(paragraphs) is not tuple:
        raise ValueError("paragraphs must be a tuple")
    for value in paragraphs:
        if type(value) is not str or PARAGRAPH_KEY.fullmatch(value) is None:
            raise ValueError(f"malformed paragraph key {value!r}")
    if paragraphs and not any(i.startswith("G-") for i in ids):
        raise ValueError("paragraphs are held for gates; name the G- id they belong to")
    return pytest.mark.hla_case(*ids, paragraphs=paragraphs)


def collected_bindings(work_dir: pathlib.Path) -> dict[str, dict[str, list[str]]]:
    """`{node id: {"ids": [...], "paragraphs": [...]}}` from a real collection of the whole suite.

    A fresh `pytest --collect-only` over `tests/` in a child process, whatever subset the current
    session was asked to run, so that "bound by a collected test" means the same thing on every
    invocation. Tests deselected by `-m` are still collected, which is the point: a case bound by
    an `rti` test is bound even in the offline group.
    """
    target = work_dir / "trace-bindings.json"
    proc = run_python(["-m", "pytest", "--collect-only", "-q", str(TESTS_DIR)], cwd=PACKAGE_ROOT,
                      extra_env={"SYNAPSE_HLA_TRACE_EXPORT": str(target)})
    assert proc.returncode == 0, f"collection failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    return strict_json(target.read_bytes())


def _clause_paragraph(clause: str) -> str | None:
    m = re.match(r"(SPEC:[1-9][0-9]*)(?![0-9])", clause)
    return m.group(1) if m else None


def trace_problems(index: list[dict], pending_doc: dict, carried: list, paragraph_map: dict,
                   bindings: dict[str, dict[str, list[str]]]) -> list[tuple[str, str]]:
    """Every violation of the D-11 ratchet, as sorted `(rule, subject)` pairs; `[]` when clean.

    Rules, by name:
      index-duplicate          an id appears twice in case-index.json
      round-keys               pending.json's `assignment` or `pending` is not keyed R0..R9, or
                               `finished_through` is not a round
      assignment-unknown-id    the assignment names an id that is not in the index
      assignment-duplicate     the assignment names an id twice
      assignment-missing       an index id is in no round of the assignment
      pending-unknown-id       a pending id is not in the index
      pending-duplicate        a pending id is listed twice
      pending-wrong-round      a pending id is listed under a round its assignment does not name
      finished-round-pending   a round up to `finished_through` still has pending ids
      bound-unknown-id         a collected test binds an id that is not in the index
      bound-and-pending        an id is bound by a collected test and still pending
      unbound-not-pending      an id is neither bound nor pending
      paragraph-unknown        a test names a paragraph key paragraph-map.json does not have
      paragraph-not-of-gate    a test names a paragraph that maps to none of the gates it binds
      paragraph-uncovered      a bound gate has a mapped paragraph that no test bound to it
                               names and no carried entry carries
      carried-malformed        a carried entry is not exactly {gate, clause, due} with text values
      carried-duplicate        the same carried entry twice
      carried-unknown-gate     a carried entry names an id that is not a G- id of the index
      carried-unknown-round    a carried entry is due in a round that does not exist
      carried-gate-not-bound   a carried entry names a gate no collected test binds
      carried-due-not-later    a carried entry is due no later than its gate's own round
      carried-due-empty-round  a carried entry is due in a round whose pending list is empty
    """
    problems: set[tuple[str, str]] = set()
    ids = [entry["id"] for entry in index]
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        problems.add(("index-duplicate", i))
    known = set(ids)
    requirement = {entry["id"]: entry["requirement"] for entry in index}
    gates = {i for i in known if i.startswith("G-")}

    assignment = pending_doc.get("assignment")
    pending = pending_doc.get("pending")
    finished = pending_doc.get("finished_through")
    shape_ok = (isinstance(assignment, dict) and isinstance(pending, dict)
                and list(assignment) == list(ROUNDS) and list(pending) == list(ROUNDS)
                and all(isinstance(v, list) for v in assignment.values())
                and all(isinstance(v, list) for v in pending.values()) and finished in ROUNDS)
    if not shape_ok:
        problems.add(("round-keys", "pending.json"))
        return sorted(problems)

    round_of: dict[str, str] = {}
    for rnd, members in assignment.items():
        for i in members:
            if i not in known:
                problems.add(("assignment-unknown-id", i))
            if i in round_of:
                problems.add(("assignment-duplicate", i))
            round_of.setdefault(i, rnd)
    for i in sorted(known - set(round_of)):
        problems.add(("assignment-missing", i))

    pending_ids: list[str] = [i for members in pending.values() for i in members]
    for rnd, members in pending.items():
        for i in members:
            if i not in known:
                problems.add(("pending-unknown-id", i))
            elif round_of.get(i) != rnd:
                problems.add(("pending-wrong-round", i))
    for i in sorted({i for i in pending_ids if pending_ids.count(i) > 1}):
        problems.add(("pending-duplicate", i))
    for rnd in ROUNDS[:ROUNDS.index(finished) + 1]:
        if pending[rnd]:
            problems.add(("finished-round-pending", rnd))

    bound: set[str] = set()
    by_gate_paragraphs: dict[str, set[str]] = {}
    for node, binding in bindings.items():
        node_ids = set(binding.get("ids", []))
        bound |= node_ids
        for p in binding.get("paragraphs", []):
            if p not in paragraph_map:
                problems.add(("paragraph-unknown", f"{node} {p}"))
                continue
            reqs = set(paragraph_map[p]["requirements"])
            owners = {g for g in node_ids if g in gates and requirement[g] in reqs}
            if not owners:
                problems.add(("paragraph-not-of-gate", f"{node} {p}"))
            for g in owners:
                by_gate_paragraphs.setdefault(g, set()).add(p)
    for i in sorted(bound - known):
        problems.add(("bound-unknown-id", i))
    pending_set = set(pending_ids)
    for i in sorted(bound & pending_set):
        problems.add(("bound-and-pending", i))
    for i in sorted(known - bound - pending_set):
        problems.add(("unbound-not-pending", i))

    carried_paragraphs: dict[str, set[str]] = {}
    seen: list = []
    for entry in carried:
        if (not isinstance(entry, dict) or set(entry) != {"gate", "clause", "due"}
                or not all(type(entry[k]) is str and entry[k] for k in ("gate", "clause", "due"))):
            problems.add(("carried-malformed", json.dumps(entry, sort_keys=True)))
            continue
        if entry in seen:
            problems.add(("carried-duplicate", f"{entry['gate']} {entry['clause']}"))
        seen.append(entry)
        gate, due = entry["gate"], entry["due"]
        subject = f"{gate} {entry['clause']}"
        if gate not in gates:
            problems.add(("carried-unknown-gate", subject))
            continue
        if due not in ROUNDS:
            problems.add(("carried-unknown-round", subject))
            continue
        if gate not in bound:
            problems.add(("carried-gate-not-bound", subject))
        if gate in round_of and ROUNDS.index(due) <= ROUNDS.index(round_of[gate]):
            problems.add(("carried-due-not-later", subject))
        if not pending[due]:
            problems.add(("carried-due-empty-round", subject))
        para = _clause_paragraph(entry["clause"])
        if para is not None:
            carried_paragraphs.setdefault(gate, set()).add(para)

    for gate in sorted(gates & bound):
        req = requirement[gate]
        for p, row in paragraph_map.items():
            if req in row["requirements"]:
                held = by_gate_paragraphs.get(gate, set()) | carried_paragraphs.get(gate, set())
                if p not in held:
                    problems.add(("paragraph-uncovered", f"{gate} {p}"))
    return sorted(problems)


# ----------------------------------------------------------------------------- capture builder

# The tests' own hand for capture files (D-12): it assembles records, numbers them and chains
# them with `json` and `hashlib` alone, never with the product's `capture` or `canonical`, so a
# capture the product accepts or refuses was not made by the code that judges it. Rounds R2 and
# R4 craft their inputs with it.

#: The bundled capture's header digest, SHA-256 of line 1 without its LF (FACTS.md, reducer).
FIXTURE_HEADER_SHA256 = "a25ac911b880672d587205e5c48e710b69a47767f9b3af11dc65c136cb65b657"


def fixture_capture_records() -> list[dict]:
    """The bundled capture's records, header first, parsed by the tests' strict reader."""
    return [obj for _, obj in fixture_jsonl("session.capture.jsonl")]


def record_digest(record: dict) -> str:
    """SHA-256 of the canonical record without its `sha256` member (SPEC:68, RED-20)."""
    return sha256_hex(canonical({k: v for k, v in record.items() if k != "sha256"}))


def chain_lines(records: list[dict], *, header_line: bytes | None = None,
                keep: frozenset = frozenset()) -> list[bytes]:
    """Canonical lines for `records` (header first) with the chain recomputed.

    `seq` is kept as each record gives it, so a test can write a gap or a repeat on purpose. Each
    later record gets `prev_sha256` = the digest of the line before (the header's exact bytes for
    the first) and its own `sha256`, except the record indexes in `keep`, whose two digests are
    left as given (a broken link on purpose). `header_line`, when given, stands verbatim as line
    1 and is chained from its exact bytes, canonical or not.
    """
    first = header_line if header_line is not None else canonical(records[0])
    lines = [first]
    previous = sha256_hex(first)
    for index, record in enumerate(records[1:], start=1):
        record = dict(record)
        if index not in keep:
            record.pop("sha256", None)
            record["prev_sha256"] = previous
            record["sha256"] = record_digest(record)
        lines.append(canonical(record))
        previous = record["sha256"]
    return lines


def capture_bytes(lines: list[bytes], *, tail: bytes = b"\n") -> bytes:
    """The file of `lines`: LF between them and `tail` after the last (b"" for no final LF)."""
    return b"\n".join(lines) + tail


def event_generation_start(federation_name: str = "SC_DEMO_0123456789abcdef") -> dict:
    return {"type": "generation_start", "federation_name": federation_name}


def event_generation_end(reason: str = "stop") -> dict:
    return {"type": "generation_end", "reason": reason}


def event_discover(token: str = "o1", name: str = "SYNTHETIC-001",
                   reported_class: str = "HLAobjectRoot.BaseEntity.PhysicalEntity") -> dict:
    return {"type": "discover", "object_token": token, "name": name,
            "reported_class": reported_class}


def event_reflect(token: str = "o1", attributes=(("ForceIdentifier", "01"),), *,
                  tag_hex: str = "", logical_time=None, retractable: bool = False) -> dict:
    return {"type": "reflect", "object_token": token,
            "attributes": [{"name": n, "hex": h} for n, h in attributes], "tag_hex": tag_hex,
            "sent_order": "RECEIVE", "received_order": "RECEIVE", "transport": "RELIABLE",
            "logical_time": logical_time, "retractable": retractable}


def event_remove(token: str = "o1", *, tag_hex: str = "") -> dict:
    return {"type": "remove", "object_token": token, "tag_hex": tag_hex,
            "received_order": "RECEIVE", "logical_time": None, "retractable": False}


def event_diagnostic(code: str = "E_RTI_CONNECT", message: str = "the RTI refused the connection",
                     *, token=None, attribute=None) -> dict:
    severity = "ERROR" if code.startswith("E_") else "WARNING"
    return {"type": "diagnostic", "object_token": token,
            "diagnostic": {"severity": severity, "code": code, "message": message,
                           "attribute": attribute}}


class CaptureBuilder:
    """A capture assembled record by record: header, frames, footer, numbered from seq 1.

    The default header is the bundled capture's (demo mode, external_elapsed from
    2026-01-01T00:00:00.000000Z); `header` replaces it. Frames and the footer are numbered in the
    order they are added; `records()` gives them chained, `data()` gives the file.
    """

    def __init__(self, header: dict | None = None) -> None:
        self.header = header if header is not None else fixture_capture_records()[0]
        self.body: list[dict] = []

    def frame(self, generation: int, elapsed_ns, event: dict) -> "CaptureBuilder":
        self.body.append({"type": "frame", "generation": generation,
                          "elapsed_ns": str(elapsed_ns), "event": event})
        return self

    def footer(self, status: str = "COMPLETE", reason_code=None,
               last_generation: int | None = None) -> "CaptureBuilder":
        if last_generation is None:
            last_generation = max([f["generation"] for f in self.body if f["type"] == "frame"]
                                  or [0])
        self.body.append({"type": "footer", "status": status, "reason_code": reason_code,
                          "last_generation": last_generation})
        return self

    def records(self) -> list[dict]:
        numbered = [dict(record, seq=seq) for seq, record in enumerate(self.body, start=1)]
        lines = chain_lines([self.header] + numbered)
        return [json.loads(line) for line in lines]

    def lines(self) -> list[bytes]:
        return [canonical(record) for record in self.records()]

    def data(self, *, tail: bytes = b"\n") -> bytes:
        return capture_bytes(self.lines(), tail=tail)

    def write(self, path: pathlib.Path, *, tail: bytes = b"\n") -> pathlib.Path:
        path.write_bytes(self.data(tail=tail))
        return path


def one_generation(builder: CaptureBuilder | None = None) -> CaptureBuilder:
    """A small valid session: one generation, one object reflected and removed, COMPLETE."""
    builder = builder if builder is not None else CaptureBuilder()
    return (builder.frame(1, 0, event_generation_start())
            .frame(1, 0, event_discover())
            .frame(1, 1000, event_reflect())
            .frame(1, 2000, event_remove())
            .frame(1, 2000, event_generation_end())
            .footer())


# ------------------------------------------------------------------- reducer scenarios (round R4)

#: The 32 codes of SPEC:190-199, written out again for the contract checker.
CATALOGUE = (
    "E_CONFIG", "E_DEPENDENCY_PIN", "E_OUTPUT_EXISTS", "E_FOM_PROFILE", "E_FEDERATE_NAME",
    "E_RTI_CONNECT", "E_RTI_TIMEOUT", "E_ATTRIBUTE_LENGTH", "E_NONFINITE", "E_BOOLEAN",
    "E_SPATIAL_VARIANT", "E_UNSUBSCRIBED_ATTRIBUTE", "E_NULL_ID", "E_ECEF_RANGE", "E_GEODESY",
    "E_TIME_REGRESSION", "E_IDENTITY_CHANGED", "E_IDENTITY_COLLISION",
    "E_RETRACTION_UNSUPPORTED", "E_UNKNOWN_OBJECT", "E_LIMIT", "E_QUEUE_OVERFLOW", "E_IO",
    "E_CAPTURE_SCHEMA", "E_CAPTURE_HASH", "E_CAPTURE_SEQUENCE", "E_CAPTURE_INCOMPLETE",
    "W_FOM_UNVERIFIED", "W_TIME_UNRESOLVED", "W_FORCE_UNMAPPED", "W_DUPLICATE_DISCOVERY",
    "W_DUPLICATE_REMOVE",
)
#: SPEC:285's vocabulary of suppression reasons.
SUPPRESSION_REASONS = (
    "MISSING_ENTITY_IDENTIFIER", "MISSING_ENTITY_TYPE", "MISSING_SPATIAL",
    "INVALID_ENTITY_IDENTIFIER", "INVALID_ENTITY_TYPE", "INVALID_SPATIAL",
    "INVALID_FORCE_IDENTIFIER", "NULL_ID", "QUARANTINED", "TIME_UNRESOLVED",
    "GEOGRAPHY_UNPROJECTABLE",
)
#: The four subscribed attributes, in the ASCII order SPEC:72 sorts them.
ATTRIBUTE_NAMES = ("EntityIdentifier", "EntityType", "ForceIdentifier", "Spatial")
#: The required attributes and the reasons their ABSENT and INVALID states give (R23, SPEC:285).
REQUIRED_REASONS = {"EntityIdentifier": ("MISSING_ENTITY_IDENTIFIER", "INVALID_ENTITY_IDENTIFIER"),
                    "EntityType": ("MISSING_ENTITY_TYPE", "INVALID_ENTITY_TYPE"),
                    "Spatial": ("MISSING_SPATIAL", "INVALID_SPATIAL")}
#: R33's order within one frame: diagnostics, invalidations, the removal notice, the snapshot,
#: the upsert.
KIND_RANK = {"diagnostic": 0, "invalidated": 1, "removed": 2, "snapshot": 3, "upsert": 4}


@functools.cache
def positive_hex() -> dict[str, str]:
    """The positive vectors of the bundle by id: the bytes scenarios are built from."""
    return {vector["id"]: vector["hex"] for vector in fixture_json("attributes-positive.json")}


@functools.cache
def negative_hex() -> dict[str, str]:
    return {vector["id"]: vector["hex"] for vector in fixture_json("attributes-negative.json")}


def header_with(**config_members) -> dict:
    """The bundled capture's header (config-demo's configuration) with members replaced."""
    header = copy.deepcopy(fixture_capture_records()[0])
    header["config"].update(copy.deepcopy(config_members))
    return header


@functools.cache
def _validators():
    return (validator("output.schema.json"), validator("snapshot.schema.json"),
            validator("diagnostic.schema.json"))


def token_number(token) -> int:
    """RED-03: tokens order by their number, a null token first."""
    return -1 if token is None else int(token[1:])


def diagnostic_key(payload: dict) -> tuple:
    """RED-03's order of diagnostics in a frame: code, attribute (null first), token number."""
    return (payload["code"], payload["attribute"] is not None, payload["attribute"] or "",
            token_number(payload["object_token"]))


def _schema_clean(validator_, instance, what: str) -> None:
    problems = sorted(validator_.iter_errors(instance), key=lambda e: list(e.absolute_path))
    assert not problems, f"{what}: {problems[0].message} at {list(problems[0].absolute_path)}"


def _check_snapshot(record: dict, payload: dict) -> None:
    reasons, changed = payload["suppression_reasons"], payload["changed_attributes"]
    assert reasons == sorted(set(reasons)) and set(reasons) <= set(SUPPRESSION_REASONS), reasons
    assert changed == sorted(set(changed)), changed
    assert (payload["projection_status"] == "ELIGIBLE") == (reasons == [])
    assert ("QUARANTINED" in reasons) == (payload["lifecycle"] == "QUARANTINED")
    assert (payload["identity"] is None) == (payload["incarnation"] is None) \
        == (record["entity_id"] is None)
    slots = payload["attributes"]
    for name in ATTRIBUTE_NAMES:
        slot = slots[name]
        sourced = (slot["hex"], slot["seq"], slot["elapsed_ns"])
        if slot["status"] == "ABSENT":
            assert sourced == (None, None, None) and slot["value"] is None \
                and slot["effective_at"] is None, name
        else:
            assert None not in sourced and slot["seq"] <= record["seq"], name
            assert (slot["value"] is None) == (slot["status"] == "INVALID"), name
        if slot["effective_at"] is not None:
            check_utc_timestamp(slot["effective_at"], digits=6)
    for name, (missing, invalid) in REQUIRED_REASONS.items():
        assert (missing in reasons) == (slots[name]["status"] == "ABSENT"), (name, reasons)
        assert (invalid in reasons) == (slots[name]["status"] == "INVALID"), (name, reasons)
    assert ("INVALID_FORCE_IDENTIFIER" in reasons) == (
        slots["ForceIdentifier"]["status"] == "INVALID")
    identifier = slots["EntityIdentifier"]
    null = identifier["status"] == "VALID" and identifier["value"] == {
        "site": 0, "application": 0, "entity": 0}
    assert ("NULL_ID" in reasons) == null
    if payload["lifecycle"] == "ACTIVE" and identifier["status"] == "VALID" and not null:
        # R24: an active object's VALID non-null identifier is the identity it claimed.
        assert payload["identity"] == identifier["value"], payload["identity"]


def check_record(record: dict) -> None:
    """One output record against the output, snapshot and diagnostic schemas and the prose."""
    output, snapshot, diagnostic = _validators()
    _schema_clean(output, record, "output.schema.json")
    kind, payload = record["kind"], record["payload"]
    assert record["output_version"] == 1
    assert (record["revision"] is not None) == (kind == "upsert"), "RED-16 revision"
    if kind == "diagnostic":
        _schema_clean(diagnostic, payload, "diagnostic.schema.json")
        assert payload["code"] in CATALOGUE, payload["code"]
        assert payload["severity"] == ("ERROR" if payload["code"].startswith("E_") else "WARNING")
        assert (payload["seq"], payload["generation"], payload["object_token"]) == (
            record["seq"], record["generation"], record["object_token"])
        assert len(payload["message"].encode("utf-8")) <= 1024
        if record["object_token"] is None:
            assert record["entity_id"] is None
    elif kind == "snapshot":
        _schema_clean(snapshot, payload, "snapshot.schema.json")
        _check_snapshot(record, payload)
    elif kind == "upsert":
        assert record["entity_id"] == payload["entity_id"], "RED-16 upsert entity_id"
        hla = payload["attributes"]["hla"]
        assert hla["capture_complete"] == record["capture_complete"]
        assert (hla["session_id"], hla["generation"], hla["object_token"]) == (
            record["session_id"], record["generation"], record["object_token"])
        source = payload["source"]
        assert source["original_id"] == (f"{record['session_id']}/{record['generation']}/"
                                         f"{record['object_token']}/{record['seq']}")
        assert source["record_index"] == record["seq"] - 1
        check_utc_timestamp(payload["valid_from"], digits=3)
        check_utc_timestamp(hla["time"]["effective_at"], digits=6)
        assert payload["valid_from"] == hla["time"]["effective_at"][:23] + "Z"
        assert payload["valid_to"] is None
    else:
        assert set(payload) == {"reason", "last_revision"}
        assert record["object_token"] is not None
        if kind == "removed":
            assert payload["reason"] == "removed", "RED-16 removed reason"
        else:
            assert payload["reason"] != "removed", "RED-16 invalidated reason"
            assert record["entity_id"] is not None


def check_frame_records(frame: dict, records: list) -> None:
    """The records of one frame: each by `check_record`, then R33's order and the event's rules."""
    event = frame["event"]
    kinds = [record["kind"] for record in records]
    for ordinal, record in enumerate(records):
        assert record["ordinal"] == ordinal
        assert (record["seq"], record["generation"]) == (frame["seq"], frame["generation"])
        check_record(record)
    assert [KIND_RANK[k] for k in kinds] == sorted(KIND_RANK[k] for k in kinds), kinds
    diagnostics = [r["payload"] for r in records if r["kind"] == "diagnostic"]
    assert diagnostics == sorted(diagnostics, key=diagnostic_key)
    invalidated = [r["object_token"] for r in records if r["kind"] == "invalidated"]
    assert invalidated == sorted(invalidated, key=token_number)
    assert kinds.count("snapshot") <= 1 and kinds.count("upsert") <= 1 \
        and kinds.count("removed") <= 1
    if "upsert" in kinds:
        snapshot, upsert = records[-2], records[-1]
        assert snapshot["kind"] == "snapshot" and upsert["kind"] == "upsert"
        assert snapshot["object_token"] == upsert["object_token"]
        assert snapshot["entity_id"] == upsert["entity_id"]
        assert snapshot["payload"]["projection_status"] == "ELIGIBLE"
        assert snapshot["payload"]["lifecycle"] == "ACTIVE"
        assert upsert["revision"] == snapshot["payload"]["last_revision"] + 1
        assert snapshot["payload"]["changed_attributes"], "an upsert needs a known attribute"
    kind = event["type"]
    if kind == "generation_end":
        assert all(r["kind"] == "invalidated" and r["payload"]["reason"] == "generation_end"
                   for r in records)
    else:
        assert not any(r["kind"] == "invalidated" and r["payload"]["reason"] == "generation_end"
                       for r in records)
    if kind == "generation_start":
        assert [(r["kind"], r["payload"]["code"]) for r in records] in (
            [], [("diagnostic", "W_FOM_UNVERIFIED")])
    if kind == "diagnostic":
        expected = dict(event["diagnostic"], seq=frame["seq"], generation=frame["generation"],
                        object_token=event["object_token"])
        assert [(r["kind"], r["payload"]) for r in records] == [("diagnostic", expected)]
    if kind in ("discover", "generation_start", "diagnostic"):
        assert set(kinds) <= {"diagnostic"} and len(records) <= 1
    if "removed" in kinds:
        assert kind == "remove" and kinds == ["removed"] and not event["retractable"]
    if kind == "reflect" and "snapshot" in kinds:
        supplied = [a["name"] for a in event["attributes"] if a["name"] in ATTRIBUTE_NAMES]
        snapshot = next(r for r in records if r["kind"] == "snapshot")
        assert snapshot["payload"]["changed_attributes"] == supplied
        assert snapshot["object_token"] == event["object_token"]
        assert event["attributes"], "no empty reflection produces a snapshot"


def check_stream(frames_records: list) -> None:
    """Invariants across the frames of one session: revisions per entity_id run 1, 2, 3 ...;
    every snapshot and lifecycle record names its entity's last revision; an entity_id stays
    with one token inside a generation; the completion flag never changes."""
    revisions: dict[str, int] = {}
    owner: dict[tuple, str] = {}
    flags = set()
    for records in frames_records:
        for record in records:
            flags.add(record["capture_complete"])
            entity_id, kind = record["entity_id"], record["kind"]
            if entity_id is None:
                continue
            key = (record["generation"], entity_id)
            assert owner.setdefault(key, record["object_token"]) == record["object_token"], key
            last = revisions.get(entity_id, 0)
            if kind == "upsert":
                assert record["revision"] == last + 1, (entity_id, record["revision"], last)
                revisions[entity_id] = record["revision"]
            elif kind == "snapshot":
                assert record["payload"]["last_revision"] == last
            elif kind in ("removed", "invalidated"):
                assert record["payload"]["last_revision"] == last
    assert len(flags) <= 1, flags


def _scramble(value) -> None:
    if type(value) is dict:
        for item in value.values():
            _scramble(item)
        value.clear()
    elif type(value) is list:
        for item in value:
            _scramble(item)
        value.clear()


def reduce_checked(state, frame):
    """`reduce_frame(state, frame)` as every R4 test calls it.

    Asserts that neither argument changed (equal to a deep copy taken before, and the same
    `repr`, which tells -0.0 from 0.0), that every record meets the contract, and that the
    records share no object with the new state: they are emptied in place afterwards and the new
    state must still equal its own copy. Returns the new state and a copy of the records.
    """
    from synapse_hla import reducer
    state_copy, frame_copy = copy.deepcopy(state), copy.deepcopy(frame)
    state_text, frame_text = repr(state), repr(frame)
    new_state, records = reducer.reduce_frame(state, frame)
    assert state == state_copy and repr(state) == state_text, "reduce_frame changed its state"
    assert frame == frame_copy and repr(frame) == frame_text, "reduce_frame changed its frame"
    check_frame_records(frame, records)
    kept = copy.deepcopy(records)
    new_copy, new_text = copy.deepcopy(new_state), repr(new_state)
    _scramble(records)
    assert new_state == new_copy and repr(new_state) == new_text, "records alias the state"
    return new_state, kept


def refused_frame(state, frame, exception=None):
    """`reduce_frame(state, frame)` expected to raise `exception` (HlaError by default): the
    exception, after asserting that neither argument changed, like `reduce_checked`."""
    from synapse_hla import HlaError, reducer
    exception = HlaError if exception is None else exception
    state_copy, frame_copy = copy.deepcopy(state), copy.deepcopy(frame)
    state_text, frame_text = repr(state), repr(frame)
    with pytest.raises(exception) as info:
        reducer.reduce_frame(state, frame)
    assert type(info.value) is exception, type(info.value)
    assert state_copy == state and repr(state) == state_text, "reduce_frame changed its state"
    assert frame_copy == frame and repr(frame) == frame_text, "reduce_frame changed its frame"
    return info.value


class Scenario:
    """A capture built with `CaptureBuilder` and reduced frame by frame through `reduce_checked`.

    `reduce()` returns one list of records per frame (frame k carries seq k), keeps the states
    (`states[k]` is the state after frame k; `states[0]` the initial one) and the chained
    records, and holds the whole stream to `check_stream`.
    """

    def __init__(self, header: dict | None = None) -> None:
        self.builder = CaptureBuilder(header)
        self.states: list = []
        self.chained: list[dict] = []

    def frame(self, generation: int, elapsed_ns, event: dict) -> "Scenario":
        self.builder.frame(generation, elapsed_ns, event)
        return self

    def footer(self, *args, **kwargs) -> "Scenario":
        self.builder.footer(*args, **kwargs)
        return self

    def reduce(self, *, capture_complete=True, limits=None) -> list[list[dict]]:
        from synapse_hla import reducer
        self.chained = self.builder.records()
        options = {} if limits is None else {"limits": limits}
        state = reducer.initial_state(self.chained[0], capture_complete, **options)
        self.states = [state]
        out = []
        for record in self.chained[1:]:
            if record["type"] != "frame":
                continue
            state, records = reduce_checked(state, record)
            self.states.append(state)
            out.append(records)
        check_stream(out)
        return out

    def write(self, path: pathlib.Path, *, tail: bytes = b"\n") -> pathlib.Path:
        return self.builder.write(path, tail=tail)


def brief(record: dict) -> tuple:
    """The facts of a record a behaviour test compares: kind, token, entity_id, then code and
    attribute (diagnostic), lifecycle, reasons, changed attributes and last revision (snapshot),
    revision (upsert), or reason and last revision (removed, invalidated)."""
    kind, payload = record["kind"], record["payload"]
    head = (kind, record["object_token"], record["entity_id"])
    if kind == "diagnostic":
        return head + (payload["code"], payload["attribute"])
    if kind == "snapshot":
        return head + (payload["lifecycle"], tuple(payload["suppression_reasons"]),
                       tuple(payload["changed_attributes"]), payload["last_revision"])
    if kind == "upsert":
        return head + (record["revision"],)
    return head + (payload["reason"], payload["last_revision"])


def briefs(frames_records: list) -> dict[int, list[tuple]]:
    """`{seq: [brief, ...]}` for every frame that emitted something."""
    return {records[0]["seq"]: [brief(r) for r in records] for records in frames_records
            if records}


def without_completion(record: dict) -> dict:
    """A record with SPEC:158's completion fields taken out: the envelope's capture_complete and,
    in an upsert, attributes.hla.capture_complete. Live and replay records differ only there."""
    out = copy.deepcopy(record)
    del out["capture_complete"]
    if out["kind"] == "upsert":
        del out["payload"]["attributes"]["hla"]["capture_complete"]
    return out


class ReferenceConsumer:
    """RED-14's reference consumer, test-only (OPS-28): applies upsert, removed and invalidated
    records keyed by (session_id, seq, ordinal) and ignores a key it has applied before.

    `entities` maps an entity_id to its current view: the last upsert's Entity and revision, or
    the notice that ended it. `deliver` returns whether the record changed anything.
    """

    def __init__(self) -> None:
        self.seen: set[tuple] = set()
        self.entities: dict[str, dict] = {}

    def deliver(self, record: dict) -> bool:
        key = (record["session_id"], record["seq"], record["ordinal"])
        if key in self.seen:
            return False
        self.seen.add(key)
        kind, entity_id = record["kind"], record["entity_id"]
        if kind == "upsert":
            self.entities[entity_id] = {"state": "current", "revision": record["revision"],
                                        "entity": copy.deepcopy(record["payload"])}
        elif kind in ("removed", "invalidated") and entity_id is not None:
            view = self.entities.setdefault(entity_id, {"revision": 0, "entity": None})
            view["state"] = kind
            view["reason"] = record["payload"]["reason"]
        return True


# ------------------------------------------------------------------- host sessions (round R5)
#
# `Session` runs `synapse_hla.host.run_session` in this process against `fake_worker.py`, a real
# child process started through the host's own spawn (the executable `worker_executable` writes
# runs this interpreter). Time is `FrozenClock` by default: frozen except when the host sleeps,
# shared with every fake worker through a file, so delays and every elapsed_ns are exact. A
# session with `frozen=False` uses the host's real CLOCK_MONOTONIC with shortened timing values.
# `check_session` is what every host test runs on what a session left (R5's brief: verify, replay
# against the live outputs, the summary, the modes, and no surviving worker).

FAKE_WORKER = TESTS_DIR / "fake_worker.py"
SCENARIO_VARIABLE = "SC_HLA_FAKE_SCENARIO"
WORKER_VARIABLE = "SYNAPSE_HLA_WORKER"
#: An arbitrary CLOCK_MONOTONIC-like start for the frozen clock: 7000 s.
FROZEN_START_NS = 7_000_000_000_000
#: The header audit time of every frozen session: 2026-10-10T00:00:00Z as microseconds since
#: 1970 (20,736 days: 56 years with 14 leap days to 2026-01-01, plus 282 days of 2026).
AUDIT_US = 20_736 * 86_400 * 1_000_000
AUDIT_TEXT = "2026-10-10T00:00:00.000000Z"
#: What the tests' RSS probe reports unless a test says otherwise: 4 MiB.
SMALL_RSS = 4 * 1024 * 1024
SECOND_NS = 1_000_000_000


class FrozenClock:
    """The injected monotonic clock and sleep of a host test: the time stands still except when
    the host sleeps (or `advance` is called), and every change is written to `path`, where a fake
    worker reads it when it starts. `sleeps` lists (time when asked, duration) per sleep."""

    def __init__(self, path: pathlib.Path, start: int = FROZEN_START_NS) -> None:
        self.path = path
        self.now = start
        self.sleeps: list[tuple[int, int]] = []
        self._write()

    def _write(self) -> None:
        self.path.write_text(str(self.now), encoding="ascii")

    def monotonic_ns(self) -> int:
        return self.now

    def sleep(self, duration_ns: int, _wake_fd: int) -> None:
        self.sleeps.append((self.now, duration_ns))
        self.now += duration_ns
        self._write()

    def advance(self, duration_ns: int) -> None:
        self.now += duration_ns
        self._write()


def worker_executable(directory: pathlib.Path) -> pathlib.Path:
    """An executable that runs `fake_worker.py` under this interpreter (no bytecode written)."""
    path = directory / "sc-hla-federate"
    path.write_text(f"#!{sys.executable} -B\nimport runpy\n"
                    f"runpy.run_path({str(FAKE_WORKER)!r}, run_name='__main__')\n",
                    encoding="utf-8")
    path.chmod(0o700)
    return path


# The worker's side of the protocol, as scenario steps (fake_worker.py's STEPS).

def stage(name: str) -> dict:
    return {"do": "stage", "stage": name}


def fail(code: str, message: str = "the RTI call failed") -> dict:
    return {"do": "fail", "code": code, "message": message}


def frame_step(event: dict, dt: int = 0) -> dict:
    return {"do": "frame", "event": event, "dt": dt}


def connect_and_join(federation: str = "SC_DEMO_0123456789abcdef", dt: int = 0) -> list[dict]:
    """A successful join as NAT-15 orders it: connect, join, generation_start right after the
    join (SPEC:275), then resolve; each stage answered by running."""
    return [stage("connect"), stage("running"), stage("join"), stage("running"),
            frame_step(event_generation_start(federation), dt),
            stage("resolve"), stage("running")]


def orderly_stop() -> list[dict]:
    """What the worker does on SIGTERM (R14): resign, disconnect, exit 0."""
    return [{"do": "wait_term"}, stage("resign"), stage("running"), stage("disconnect"),
            stage("running")]


def connect_refused(message: str = "the RTI refused the connection") -> list[dict]:
    """ConnectionFailed in connect (NAT-08): a failure record and its diagnostic copy, exit 1."""
    return [stage("connect"), fail("E_RTI_CONNECT", message),
            frame_step(event_diagnostic("E_RTI_CONNECT", message)),
            {"do": "exit", "code": 1}]


def example_config(name: str = "config-demo.json", **members) -> dict:
    config = example_json(name)
    config.update(members)
    return config


class Session:
    """One host session in this process: the scenario, the worker, the clock, the seams; `run()`
    calls `run_session` and keeps the summary. See the section text."""

    def __init__(self, root: pathlib.Path, attempts: list, *, config: dict | None = None,
                 frozen: bool = True, version: dict | None = None,
                 duration_ns: int | None = None, extra_env: dict | None = None,
                 probe_deadline_ns: int | None = None, **seams) -> None:
        import dataclasses

        from synapse_hla import host
        self.root = root
        work = root / "work"
        work.mkdir(parents=True)
        self.work = work
        self.log = work / "worker.log"
        self.worker = worker_executable(work)
        self.clock = FrozenClock(work / "clock") if frozen else None
        self.config = example_config() if config is None else config
        self.duration_ns = duration_ns
        self.out = root / "run"
        scenario = {"log": str(self.log), "clock": None if self.clock is None
                    else str(self.clock.path), "version": version, "attempts": attempts,
                    "self": str(self.worker), "watch": str(self.out / "capture.jsonl")}
        scenario_path = work / "scenario.json"
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        fom_dir = str(fom_modules()[0].parent)
        environ = {FOM_DIR_VARIABLE: fom_dir, WORKER_VARIABLE: str(self.worker),
                   SCENARIO_VARIABLE: str(scenario_path)}
        environ.update(extra_env or {})
        self.environ = child_environment(environ)
        defaults = {"wall_clock_us": lambda: AUDIT_US, "rss_of": lambda _pid: SMALL_RSS}
        if self.clock is not None:
            defaults.update(monotonic_ns=self.clock.monotonic_ns, sleep=self.clock.sleep)
        defaults.update(seams)
        self.seams = dataclasses.replace(host.V1, **defaults)
        #: The deadline of the pre-flight's version probe when it is not the session's: a row
        #: that shortens `deadline_ns` to measure the session's deadline gives the probe another
        #: one, so that the probe never shares the deadline the row measures (review finding
        #: R9-r1-F5). None: the probe uses the session's seams, as the host does.
        self.probe_deadline_ns = probe_deadline_ns
        self.summary: dict | None = None

    def run(self, *, stop_on_waiting: int | None = None, signum=None,
            advance_on_waiting: tuple[int, int] | None = None, on_worker=None) -> "Session":
        """Run the session. With `stop_on_waiting`, a thread sends `signum` (SIGINT) to this
        process once that attempt's worker logs `waiting` (fake_worker's `wait_term`): the
        worker is then alive and blocked until the host stops it, so the signal always reaches
        the host's own handler (round R5: the orderly stop, in-process). With
        `advance_on_waiting` = (attempt, ns) the thread advances the frozen clock instead, by
        `ns`, at the same moment (a duration that ends while the worker waits)."""
        import signal
        import threading
        import time

        from synapse_hla import host
        done = threading.Event()
        thread = None
        if stop_on_waiting is not None or advance_on_waiting is not None:
            attempt = stop_on_waiting if stop_on_waiting is not None else advance_on_waiting[0]

            def watch():
                while not done.is_set():
                    if any(e["event"] == "waiting" and e["attempt"] == attempt
                           for e in self.log_entries()):
                        if advance_on_waiting is not None:
                            self.clock.advance(advance_on_waiting[1])
                        else:
                            os.kill(os.getpid(), signum or signal.SIGINT)
                        return
                    time.sleep(0.005)
            thread = threading.Thread(target=watch, daemon=True)
        # The host installs its own handler and puts back whatever was there; a no-op one here
        # means a signal that arrives after the session (a host that ended too early) cannot
        # interrupt the test run itself.
        sent = signum or signal.SIGINT
        previous = signal.signal(sent, lambda *_: None)
        preflight = host.preflight
        if self.probe_deadline_ns is not None:
            import dataclasses
            deadline_ns = self.probe_deadline_ns

            def probe_preflight(environ, *, seams=host.V1):
                # The session itself keeps `seams` and its deadline: only the pre-flight (the
                # FOM check and the version probe) sees the other deadline.
                return preflight(environ, seams=dataclasses.replace(seams,
                                                                    deadline_ns=deadline_ns))
            host.preflight = probe_preflight
        try:
            if thread is not None:
                thread.start()
            self.summary = host.run_session(self.config, self.out, environ=self.environ,
                                            duration_ns=self.duration_ns, seams=self.seams,
                                            on_worker=on_worker)
        finally:
            host.preflight = preflight
            done.set()
            if thread is not None:
                thread.join()
            signal.signal(sent, previous)
        return self

    # -- what the session left

    def capture_bytes(self) -> bytes:
        return (self.out / "capture.jsonl").read_bytes()

    def records(self) -> list[dict]:
        """The capture's complete lines, parsed by the tests' strict reader (header first)."""
        data = self.capture_bytes()
        return [strict_json(line) for line in data.split(b"\n")[:-1]]

    def shape(self, *, elapsed: bool = True) -> list[tuple]:
        return capture_shape(self.records()[1:], elapsed=elapsed)

    def observations(self) -> list[dict]:
        return [strict_json(line) for line in output_lines(
            (self.out / "observations.jsonl").read_bytes())]

    def log_entries(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def starts(self) -> list[dict]:
        return [e for e in self.log_entries() if e["event"] == "start"]


def output_lines(data: bytes) -> list[bytes]:
    """`jsonl_lines`, except that an empty output file has no lines."""
    return jsonl_lines(data) if data else []


def capture_shape(records: list[dict], *, elapsed: bool = True) -> list[tuple]:
    """The facts of each frame and of the footer a host test compares: (kind, generation,
    elapsed_ns as int, then the reason, the federation, the code with token and attribute, or
    the token), and ("footer", status, reason_code, last_generation)."""
    out = []
    for record in records:
        if record["type"] == "footer":
            out.append(("footer", record["status"], record["reason_code"],
                        record["last_generation"]))
            continue
        event = record["event"]
        kind = event["type"]
        head = (kind, record["generation"]) + ((int(record["elapsed_ns"]),) if elapsed else ())
        if kind == "generation_start":
            out.append(head + (event["federation_name"],))
        elif kind == "generation_end":
            out.append(head + (event["reason"],))
        elif kind == "diagnostic":
            d = event["diagnostic"]
            out.append(head + (d["code"], event["object_token"], d["attribute"]))
        else:
            out.append(head + (event["object_token"],))
    return out


def chain_check(data: bytes) -> tuple[list[dict], bytes]:
    """The tests' own reading of a capture file: every complete line canonical, seq 1, 2, 3 ...
    and each record's prev_sha256 and sha256 by the tests' own digest (SPEC:66-68); returns the
    records and the bytes after the last LF (a partial last line)."""
    *lines, tail = data.split(b"\n")
    records = []
    previous = None
    for number, line in enumerate(lines, start=1):
        record = strict_json(line)
        assert canonical(record) == line, f"line {number} is not canonical"
        if number == 1:
            assert record["type"] == "header", "line 1 is not the header"
        else:
            assert record["seq"] == number - 1, f"line {number}: seq {record['seq']}"
            assert record["prev_sha256"] == previous, f"line {number}: prev_sha256"
            assert record["sha256"] == record_digest(record), f"line {number}: sha256"
        previous = sha256_hex(line) if number == 1 else record["sha256"]
        records.append(record)
    return records, tail


#: RED-01: the codes the reducer derives from frames, which no capture frame may carry (the host
#: never writes one, CR-R4-02, and a worker may report none, OPS-30). Written out from the
#: ruling's list.
DERIVED_CODES = frozenset({
    "E_ATTRIBUTE_LENGTH", "E_NONFINITE", "E_BOOLEAN", "E_SPATIAL_VARIANT",
    "E_UNSUBSCRIBED_ATTRIBUTE", "E_NULL_ID", "E_ECEF_RANGE", "E_GEODESY", "E_TIME_REGRESSION",
    "E_IDENTITY_CHANGED", "E_IDENTITY_COLLISION", "E_UNKNOWN_OBJECT", "W_FOM_UNVERIFIED",
    "W_TIME_UNRESOLVED", "W_FORCE_UNMAPPED", "W_DUPLICATE_DISCOVERY", "W_DUPLICATE_REMOVE",
})


def process_gone(pid: int, *, within_s: float = 5.0) -> bool:
    """True when no process `pid` exists (a reparented zombie is given `within_s` to be reaped)."""
    import time
    end = time.monotonic() + within_s
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() > end:
            return False
        time.sleep(0.01)


@functools.lru_cache(maxsize=1)
def _session_summary_validator() -> Draft202012Validator:
    schema = strict_json(package_bytes("local_schemas", "session-summary.schema.json"))
    return Draft202012Validator(schema, registry=Registry(), format_checker=FormatChecker())


def check_session(run_dir: pathlib.Path, summary: dict | None, pids=(), *,
                  replay_root: pathlib.Path) -> dict:
    """What every host test asserts about a session's run directory, whatever the scenario:
    - the capture by the tests' own reader (`chain_check`): never a hash or schema fault, and no
      captured diagnostic carries a code the reducer derives (RED-01, CR-R4-02);
    - `verify_capture` agrees: COMPLETE or FAILED with the footer the file holds, or INCOMPLETE
      (E_CAPTURE_INCOMPLETE) at the first line that is not there or not whole;
    - `replay` (with `allow_prefix` unless COMPLETE) gives the live records, completion fields
      aside (SPEC:158): all of them, or, when the outputs or the capture broke, the live records
      as a prefix; every live record carries capture_complete null;
    - a FAILED footer's reason_code is the code of a diagnostic of the session (NAT-08: every
      condition has its diagnostic, captured or derived by the reducer, and the footer's code
      is a condition's), so the replay's diagnostics hold it;
    - diagnostics.jsonl is the diagnostic lines of observations.jsonl (OPS-20), or a prefix of
      them when a write of the outputs failed (only whole lines count then);
    - the directory is 0700 and its files 0600 (R34); the summary (when there is one) satisfies
      `session-summary.schema.json`, names each file's size and SHA-256, and counts the records
      and codes the observations file holds;
    - no worker process of the session survives (`pids`).
    Returns the verify report."""
    import stat as stat_module

    from synapse_hla import replay, verify_capture
    data = (run_dir / "capture.jsonl").read_bytes()
    records, tail = chain_check(data)
    for record in records[1:]:
        if record["type"] == "frame" and record["event"]["type"] == "diagnostic":
            event = record["event"]
            assert event["diagnostic"]["code"] not in DERIVED_CODES, record
            if event["diagnostic"]["code"] == "E_RETRACTION_UNSUPPORTED":
                assert event["object_token"] is None, record
    report = verify_capture(run_dir / "capture.jsonl")
    last = records[-1] if records else None
    if last is not None and last["type"] == "footer" and not tail:
        assert report["status"] == last["status"] and report["code"] is None, report
    else:
        assert report["status"] == "INCOMPLETE", report
        assert report["code"] == "E_CAPTURE_INCOMPLETE", report
        assert report["path"] == f"line:{len(records) + 1}", report
        assert report["verified_seq"] == (len(records) - 1 if records else None), report
    outputs_broke = summary is not None and "E_IO" in summary["terminal_codes"]
    live_data = (run_dir / "observations.jsonl").read_bytes()
    diagnostics = (run_dir / "diagnostics.jsonl").read_bytes()
    if outputs_broke:
        # A write that failed may have left part of a line; only the whole lines are records.
        live_data = live_data[:live_data.rfind(b"\n") + 1]
        diagnostics = diagnostics[:diagnostics.rfind(b"\n") + 1]
    live = [strict_json(line) for line in output_lines(live_data)]
    assert all(r["capture_complete"] is None for r in live)
    expected_diagnostics = b"".join(line + b"\n" for line in output_lines(live_data)
                                    if strict_json(line)["kind"] == "diagnostic")
    if outputs_broke:
        assert expected_diagnostics.startswith(diagnostics)
    else:
        assert diagnostics == expected_diagnostics
    if records:
        complete = report["status"] == "COMPLETE"
        target = replay_root / "replay"
        replay(run_dir / "capture.jsonl", target, allow_prefix=not complete)
        replayed = [strict_json(line) for line in output_lines(
            (target / "observations.jsonl").read_bytes())]
        assert all(r["capture_complete"] is complete for r in replayed)
        mine = [without_completion(r) for r in live]
        theirs = [without_completion(r) for r in replayed]
        broken = summary is None or summary["status"] == "INCOMPLETE" or outputs_broke
        if broken:
            assert theirs[:len(mine)] == mine
        else:
            assert theirs == mine
        if last["type"] == "footer" and last["status"] == "FAILED":
            codes = {r["payload"]["code"] for r in replayed if r["kind"] == "diagnostic"}
            assert last["reason_code"] in codes, (last["reason_code"], sorted(codes))
    assert stat_module.S_IMODE(run_dir.stat().st_mode) == 0o700
    for name in ("capture.jsonl", "observations.jsonl", "diagnostics.jsonl"):
        assert stat_module.S_IMODE((run_dir / name).stat().st_mode) == 0o600, name
    if summary is not None:
        problems = list(_session_summary_validator().iter_errors(summary))
        assert not problems, problems[0].message
        for name in ("capture.jsonl", "observations.jsonl", "diagnostics.jsonl"):
            body = (run_dir / name).read_bytes()
            assert summary["files"][name] == {"bytes": len(body), "sha256": sha256_hex(body)}
        assert summary["capture_complete"] is None
        assert summary["last_seq"] == (len(records) - 1 if records else 0)
        kinds = dict.fromkeys(("diagnostic", "snapshot", "upsert", "removed", "invalidated"), 0)
        codes: dict[str, int] = {}
        for record in live:
            kinds[record["kind"]] += 1
            if record["kind"] == "diagnostic":
                code = record["payload"]["code"]
                codes[code] = codes.get(code, 0) + 1
        assert summary["records"] == kinds
        assert {**summary["errors"], **summary["warnings"]} == codes
    for pid in pids:
        assert process_gone(pid), f"worker {pid} survived"
    return report


def finished(session: Session) -> dict:
    """`check_session` on an in-process session, with every worker it started."""
    pids = [e["pid"] for e in session.log_entries() if "pid" in e]
    return check_session(session.out, session.summary, pids, replay_root=session.root)
