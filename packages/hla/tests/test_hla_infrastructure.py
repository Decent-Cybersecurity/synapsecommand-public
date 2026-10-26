"""The test infrastructure itself: the socket guard, BLOCKED, the FOM resolver, strict loaders.

A guard nobody proved and a helper nobody exercised are the two ways a green offline run can mean
nothing, so each is held here against both its success and its refusal.
"""

import json
import socket

import pytest

import conftest
import hla_support
from hla_support import (
    FOM_DIR_VARIABLE, FOM_MODULE_ORDER, PACKAGE_ROOT, StrictJsonError, check_utc_timestamp,
    jsonl_lines, run_python, strict_json,
)
from sockguard import sitecustomize as sockguard

# ------------------------------------------------------------------------------- socket guard

#: How each guarded function is called in the proofs. No call reaches the network: each is
#: refused before it does anything.
CALLS = {
    "socket": lambda s: s.socket(),
    "create_connection": lambda s: s.create_connection(("127.0.0.1", 9)),
    "getaddrinfo": lambda s: s.getaddrinfo("localhost", 80),
    "socketpair": lambda s: s.socketpair(),
    "gethostbyname": lambda s: s.gethostbyname("localhost"),
    "gethostbyname_ex": lambda s: s.gethostbyname_ex("localhost"),
    "gethostbyaddr": lambda s: s.gethostbyaddr("127.0.0.1"),
    "getnameinfo": lambda s: s.getnameinfo(("127.0.0.1", 80), 0),
}


def test_the_guard_covers_the_four_functions_of_d10():
    assert {"socket", "create_connection", "getaddrinfo", "socketpair"} <= set(sockguard.GUARDED)
    assert set(CALLS) == set(sockguard.GUARDED)


@pytest.mark.parametrize("name", sorted(CALLS))
def test_every_guarded_function_is_refused_in_an_offline_test(name):
    with pytest.raises(sockguard.SocketGuardError):
        CALLS[name](socket)


def test_the_refusal_is_not_an_os_error():
    """Network error handling catches OSError; the guard must not be mistaken for a network fault."""
    assert not issubclass(sockguard.SocketGuardError, OSError)


_CHILD = """
import json, socket
calls = {
    "socket": lambda: socket.socket(),
    "create_connection": lambda: socket.create_connection(("127.0.0.1", 9)),
    "getaddrinfo": lambda: socket.getaddrinfo("localhost", 80),
    "socketpair": lambda: socket.socketpair(),
    "gethostbyname": lambda: socket.gethostbyname("localhost"),
    "gethostbyname_ex": lambda: socket.gethostbyname_ex("localhost"),
    "gethostbyaddr": lambda: socket.gethostbyaddr("127.0.0.1"),
    "getnameinfo": lambda: socket.getnameinfo(("127.0.0.1", 80), 0),
}
out = {}
for name, call in calls.items():
    try:
        call()
        out[name] = "NOT REFUSED"
    except Exception as exc:
        out[name] = type(exc).__module__ + "." + type(exc).__name__
print(json.dumps(out, sort_keys=True))
"""


def test_a_child_interpreter_started_by_a_test_has_the_same_guard():
    proc = run_python(["-c", _CHILD], cwd=PACKAGE_ROOT)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result == {name: "sitecustomize.SocketGuardError" for name in sockguard.GUARDED}


@pytest.mark.parametrize("markers,offline", [
    ((), True),
    (("parametrize",), True),
    (("hla_case",), True),
    (("rti",), False),
    (("perf",), False),
    (("reference",), False),
    (("parametrize", "rti"), False),
])
def test_only_the_offline_group_is_guarded(markers, offline):
    assert conftest.is_offline(markers) is offline


# ------------------------------------------------------------------------------------- BLOCKED

def test_blocked_is_a_skip_whose_reason_starts_with_blocked():
    with pytest.raises(pytest.skip.Exception) as info:
        hla_support.blocked("the thing")
    assert info.value.msg == "BLOCKED: the thing"


# ------------------------------------------------------------------------------- FOM resolver

def _blocked_reason(environ):
    with pytest.raises(pytest.skip.Exception) as info:
        hla_support.fom_modules(environ)
    return info.value.msg


def test_an_unset_fom_directory_is_blocked():
    assert _blocked_reason({}) == f"BLOCKED: {FOM_DIR_VARIABLE} is not set"
    assert _blocked_reason({FOM_DIR_VARIABLE: ""}) == f"BLOCKED: {FOM_DIR_VARIABLE} is not set"


def test_a_fom_directory_that_is_not_there_is_blocked(tmp_path):
    reason = _blocked_reason({FOM_DIR_VARIABLE: str(tmp_path / "absent")})
    assert reason == f"BLOCKED: {FOM_DIR_VARIABLE} does not name a directory"


def test_a_missing_module_is_blocked(tmp_path):
    reason = _blocked_reason({FOM_DIR_VARIABLE: str(tmp_path)})
    assert reason == f"BLOCKED: FOM module RPR-Foundation_v2.0.xml is not in {FOM_DIR_VARIABLE}"


def test_a_module_with_other_bytes_fails_rather_than_blocks(tmp_path):
    (tmp_path / "RPR-Foundation_v2.0.xml").write_bytes(b"<not-the-pinned-module/>")
    with pytest.raises(AssertionError, match="does not match pins.json"):
        hla_support.fom_modules({FOM_DIR_VARIABLE: str(tmp_path)})


def test_the_fom_directory_yields_the_five_pinned_modules_in_r04_order():
    """Needs the real directory; check.sh supplies it, so this is never BLOCKED in that run."""
    paths = hla_support.fom_modules()
    assert [p.name for p in paths] == list(FOM_MODULE_ORDER)
    assert list(FOM_MODULE_ORDER) == ["RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml",
                                      "RPR-Base_v2.0.xml", "RPR-Physical_v2.0.xml",
                                      "RPR-Switches_v2.0.xml"]


# ---------------------------------------------------------------------------- strict loaders

@pytest.mark.parametrize("data", [
    b'{"a":1,"a":2}',
    b'{"a":NaN}',
    b'{"a":Infinity}',
    b'{"a":-Infinity}',
    b'\xef\xbb\xbf{"a":1}',
    b'{"a":"\xff"}',
])
def test_strict_json_refuses_what_python_json_would_accept(data):
    with pytest.raises((StrictJsonError, UnicodeDecodeError)):
        strict_json(data)


def test_strict_json_accepts_plain_json():
    assert strict_json(b'{"a":[1,2.5,"x",null,true]}') == {"a": [1, 2.5, "x", None, True]}


@pytest.mark.parametrize("data", [b'{"a":1e999}', b'{"a":-1e999}', b'[1E400]', b'1e999'])
def test_strict_json_refuses_a_number_that_overflows_to_infinity(data):
    """Python's json turns 1e999 into inf without complaint (review finding R0-r1-F3)."""
    assert json.loads(b'{"a":1e999}') == {"a": float("inf")}
    with pytest.raises(StrictJsonError):
        strict_json(data)


@pytest.mark.parametrize("data", [b'{"a":"\\ud800"}', b'{"\\udfff":1}', b'["ok","x\\udbff"]',
                                  b'"\\ud83d"'])
def test_strict_json_refuses_a_lone_surrogate_escape(data):
    with pytest.raises(StrictJsonError):
        strict_json(data)


def test_strict_json_keeps_a_surrogate_pair_escape_and_large_finite_numbers():
    # A pair escape is one astral character, not a lone surrogate; 1e308 is finite.
    assert strict_json(b'{"a":"\\ud83d\\ude00","b":1e308}') == {"a": "\U0001f600", "b": 1e308}


@pytest.mark.parametrize("data", [b"{}\r\n{}\r\n", b"{}\r\n", b"{}\n\r{}\n", b'{"a":1}\r\n'])
def test_jsonl_lines_refuses_a_carriage_return(data):
    with pytest.raises(StrictJsonError):
        jsonl_lines(data)


@pytest.mark.parametrize("data", [b"", b"{}", b"{}\n\n{}\n", b"\n"])
def test_jsonl_lines_refuses_blank_or_unterminated_lines(data):
    with pytest.raises(StrictJsonError):
        jsonl_lines(data)


def test_jsonl_lines_splits_terminated_lines():
    assert jsonl_lines(b"{}\n[]\n") == [b"{}", b"[]"]


@pytest.mark.parametrize("value,digits", [
    ("2026-01-01T00:00:00.000000Z", 6),
    ("1970-01-01T00:00:00.000000Z", 6),
    ("9998-12-31T23:59:59.999999Z", 6),
    ("2024-02-29T12:00:00.000Z", 3),
    ("2000-02-29T00:00:00.000Z", 3),
])
def test_explicit_timestamp_check_accepts(value, digits):
    check_utc_timestamp(value, digits=digits)


@pytest.mark.parametrize("value,digits", [
    ("2026-02-30T00:00:00.000000Z", 6),
    ("2025-02-29T00:00:00.000000Z", 6),
    ("1900-02-29T00:00:00.000000Z", 6),
    ("1969-12-31T23:59:59.999999Z", 6),
    ("9999-01-01T00:00:00.000000Z", 6),
    ("2026-13-01T00:00:00.000000Z", 6),
    ("2026-00-01T00:00:00.000000Z", 6),
    ("2026-01-00T00:00:00.000000Z", 6),
    ("2026-01-01T24:00:00.000000Z", 6),
    ("2026-01-01T00:60:00.000000Z", 6),
    ("2026-01-01T00:00:60.000000Z", 6),
    ("2026-01-01T00:00:00.000Z", 6),
    ("2026-01-01T00:00:00.000000Z", 3),
    ("2026-01-01T00:00:00.000000+00:00", 6),
    ("2026-01-01 00:00:00.000000Z", 6),
    ("2026-01-01T00:00:00.000000Z\n", 6),
])
def test_explicit_timestamp_check_refuses(value, digits):
    with pytest.raises(AssertionError):
        check_utc_timestamp(value, digits=digits)


# ------------------------------------------------------------ hostile code points in the source

#: The code points an `HlaError` message refuses (CR-R0-04), written out here by number so that
#: this test does not take its rule from the module it guards; a test below holds the two equal.
REFUSED_RANGES = ((0x0000, 0x001F), (0x007F, 0x009F), (0x061C, 0x061C), (0x200E, 0x200F),
                  (0x2028, 0x202E), (0x2066, 0x2069), (0xD800, 0xDFFF))

#: What counts as a text file of this distribution: the suffixes of every kind of source the
#: rounds write (Python, Markdown, TOML, JSON, and the C++, CMake and shell of the native rounds),
#: and the dotfiles and fixed names that carry no suffix.
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".cpp", ".cc", ".h", ".hpp", ".cmake", ".sh",
                 ".txt", ".cfg", ".ini", ".yml", ".yaml", ".in"}
TEXT_NAMES = {".gitignore", ".gitattributes", "LICENSE", "NOTICE"}

#: Byte copies of the handoff bundle, held to their pins instead (D-05).
VENDORED_DIRS = (PACKAGE_ROOT / "src" / "synapse_hla" / "schemas",
                 PACKAGE_ROOT / "src" / "synapse_hla" / "fixtures")


def _refused_point(point: int) -> bool:
    return any(lo <= point <= hi for lo, hi in REFUSED_RANGES)


def hostile_points(text: str) -> list[tuple[int, str]]:
    """`(line number, U+XXXX)` for every refused code point in `text` other than LF.

    Lines are counted by LF alone: `str.splitlines()` would also break at U+2028, U+2029 and the
    C1 separators, which are exactly what this looks for.
    """
    found = []
    for number, line in enumerate(text.split("\n"), start=1):
        for ch in line:
            if _refused_point(ord(ch)):
                found.append((number, f"U+{ord(ch):04X}"))
    return found


def text_files() -> list:
    """Every text file of the distribution on disk, outside the vendored bundle copies.

    The disk is walked rather than the git index, so that a file nobody has staged yet is held
    too, and so that the test needs no git at run time; byte-code caches are not text and are
    skipped by kind.
    """
    out = []
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        if not path.is_file() or any(path.is_relative_to(d) for d in VENDORED_DIRS):
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            out.append(path)
    return out


def test_the_refused_ranges_are_the_message_rules():
    from synapse_hla import errors
    assert REFUSED_RANGES == errors._REFUSED_IN_MESSAGE


def test_no_text_file_of_the_distribution_holds_a_hostile_code_point():
    """CR-R1-07 (review finding R1-r1-F2): a bidirectional control, a line or paragraph separator,
    a C0 or C1 control (other than LF) or a lone surrogate written raw in a source file reorders
    or splits what a reader of the file sees. Sources spell them as escapes."""
    files = text_files()
    names = {p.relative_to(PACKAGE_ROOT).as_posix() for p in files}
    # The walk is not vacuous: it reaches the sources, the tests, the contract and the examples.
    assert {"pyproject.toml", "README.md", "src/synapse_hla/errors.py",
            "tests/test_hla_infrastructure.py", "tests/test_hla_codec.py",
            "tests/test_hla_errors.py", "tests/contract/case-index.json",
            "examples/config-demo.json", ".gitattributes"} <= names
    problems = {}
    for path in files:
        found = hostile_points(path.read_bytes().decode("utf-8"))
        if found:
            problems[path.relative_to(PACKAGE_ROOT).as_posix()] = found[:5]
    assert problems == {}


@pytest.mark.parametrize("text,expected", [
    ("plain\nlines\n", []),
    ("a\U0000202eb", [(1, "U+202E")]),
    ("x\ny\U00002028", [(2, "U+2028")]),
    ("\t", [(1, "U+0009")]),
    ("\r\n", [(1, "U+000D")]),
    ("\U0000061c\u0085", [(1, "U+061C"), (1, "U+0085")]),
    ("ok \U00002014 \U0000fffd \U000000e9", []),
])
def test_the_source_scan_finds_exactly_the_refused_points(text, expected):
    assert hostile_points(text) == expected
