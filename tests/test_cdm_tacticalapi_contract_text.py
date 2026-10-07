"""The `tacticalapi` adapter's own gates on what may enter the repository from the contract it
reads.

Moved on 2026-10-06, when the adapter landed, from the out-of-tree project's promotion gates
(`tests/test_promotion_gates.py` there), which held the project to the repository's gates before it
moved. The gates the repository already applies to every adapter were dropped with the move, since
the repository's own run them now: the text licence sweep and the SPDX sweep
(`tests/test_cdm_publication.py`), the JSON-parse and parser-name rules
(`tests/test_cdm_parser_safety.py`, `tests/test_cdm_security_policy.py`), the manifest rules
(`tests/test_cdm_manifests.py`, `tests/test_cdm_evidence.py`), the caching-loader ban
(`tests/test_cdm_generator_loading.py`), the socket-free suite run (`tests/test_cdm_no_network.py`)
and the grammar floor (`tests/test_cdm_version_floor.py`). What stays here is what the repository
has no gate for, each scoped to the adapter's own files and never to the whole tree:

1. FORBIDDEN IMPORTS, NARROWED. The two adapter modules and the fixture builder import no
   networking, RPC, protobuf-runtime, hashing, cryptographic or platform-probing module, and none
   of the roots and runtimes the repository keeps out of its contract layer, found by walking each
   file's AST — `import x`, `from x import y`, and `__import__("x")` /
   `importlib.import_module("x")` with a literal name, which the repository's boundary gate does
   not read. The forbidden set is the adapter's own list joined with the module sets of the
   repository's gates, read from those gates rather than restated, so a module a gate adds is
   forbidden here the same day. `subprocess` is allowed in the fixture builder (it runs protoc)
   and in neither adapter module. `hashlib` is held further, to every Python file of the adapter
   (its gates and its tests included): every hash goes through `synapse_cdm.evidence`.
2. RUNTIME DEPENDENCIES. The two adapter modules import the standard library, `pydantic` and
   `synapse_cdm`, and nothing else.
3. NO WALL CLOCK. The two adapter modules never read the current time; the adapter uses the clock
   it is given.
4. NO COMMENT LITERALS. No file of the adapter holds a literal the contract has only inside its
   comments (an example identifier, a reference, an address): its names and numbers come in, the
   values its comments mention do not. CI has no pinned files, so the scan compares SHA-256
   fingerprints that `gates/tacticalapi_contract_comments.py` wrote into
   `tests/tacticalapi_comment_digests.json`. The files are the ones that tool's `ARC_FILES` names:
   the adapter's modules, fixtures, gates, tests and helpers, its record
   (`docs/tacticalapi-implementation.md`), its documentation page and both `NOTICE` copies. The
   files the landing changed elsewhere are scanned at each exit of the round that changes them, fed
   the changed paths; copied prose is held by the same tool's `--check-prose`, run by hand where the
   pinned files are.
5. LICENCE HYGIENE ON THE OCTETS. No file of the adapter but the two `NOTICE` copies, which are
   licence files and carry the repository's own notice, holds a licence-identifier tag or a
   copyright notice line, looked for on the octets as well as on the text: the repository's sweep
   reads only files that decode as UTF-8, and the binary payloads of the fixture set do not.
6. THE RULINGS AND THE PIN. The maintainer's rulings of 2026-10-06 (R1 to R10) are recorded in
   `docs/tacticalapi-implementation.md`, and the shipped pin record's `terms` state R8 to R10
   beside what the upstream says. Both are read here, as they were out of tree.

Each scanner is first shown to find what it looks for, on a synthetic source, so a scan that
silently matched nothing could not pass.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

import pytest

import synapse_cdm
from gates import tacticalapi_contract_comments as contract_comments
from tests import test_cdm_boundary, test_cdm_conformance, test_cdm_no_network

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
ADAPTER = PKG / "adapters" / "tacticalapi.py"
CODEC = PKG / "adapters" / "tacticalapi_codec.py"
BUILDER = PKG / "fixtures" / "tacticalapi" / "spec" / "build_fixtures.py"
PIN = PKG / "fixtures" / "tacticalapi" / "spec" / "tacticalapi_pin.json"
RECORD = ROOT / "docs" / "tacticalapi-implementation.md"
RUNTIME_FILES = (ADAPTER, CODEC)

# ----------------------------------------------------------------------- 1. forbidden imports

#: The adapter's own list: no RPC, protobuf runtime, networking, hashing or platform probing.
ADAPTER_FORBIDDEN = frozenset({
    "grpc", "socket", "asyncio", "http", "urllib", "requests", "ssl", "httpx", "aiohttp",
    "websockets", "hashlib", "platform", "google.protobuf",
})
#: The repository's gates over the same files, read from the gates themselves:
#: `tests/test_cdm_no_network.py` NETWORKING, `tests/test_cdm_boundary.py` FORBIDDEN_ROOTS (less
#: "synapse-data", a directory name and no importable module name; "synapse_data" is in it),
#: FORBIDDEN_CRYPTO and FORBIDDEN_RUNTIME, and `tests/test_cdm_conformance.py` FORBIDDEN_ROOTS.
HOST_SETS = {
    "networking": frozenset(test_cdm_no_network.NETWORKING),
    "roots": frozenset(test_cdm_boundary.FORBIDDEN_ROOTS) - {"synapse-data"},
    "crypto": frozenset(test_cdm_boundary.FORBIDDEN_CRYPTO),
    "runtime": frozenset(test_cdm_boundary.FORBIDDEN_RUNTIME),
    "conformance": frozenset(test_cdm_conformance.FORBIDDEN_ROOTS),
}
FORBIDDEN_MODULES = tuple(sorted(ADAPTER_FORBIDDEN.union(*HOST_SETS.values())))
RUNTIME_ALLOWED = ("pydantic", "synapse_cdm", "__future__")


def imported_names(source: str) -> list[tuple[int, str]]:
    """Every module name a source imports, with its line: `import a.b` gives `a.b`, `from a
    import b` gives `a` and `a.b` (so `from google import protobuf` is seen), and a call to
    `__import__` or `importlib.import_module` with a literal first argument gives that name."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
            found.extend((node.lineno, f"{node.module}.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call) and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            function = node.func
            name = function.id if isinstance(function, ast.Name) else (
                function.attr if isinstance(function, ast.Attribute) else None)
            if name in ("__import__", "import_module"):
                found.append((node.lineno, node.args[0].value))
    return found


def matches(name: str, module: str) -> bool:
    return name == module or name.startswith(module + ".")


def forbidden_in(source: str, *, subprocess_allowed: bool) -> list[str]:
    bad = []
    for line, name in imported_names(source):
        if any(matches(name, module) for module in FORBIDDEN_MODULES):
            bad.append(f"line {line}: {name}")
        if not subprocess_allowed and matches(name, "subprocess"):
            bad.append(f"line {line}: {name}")
    return bad


def test_the_import_scan_finds_what_it_looks_for():
    source = "\n".join([
        "import json", "import socket", "import http.client", "from google import protobuf",
        "from google.protobuf import descriptor_pb2", "import subprocess",
        "x = __import__('ssl')", "import importlib", "y = importlib.import_module('hashlib')",
        "import platformdirs",
    ])
    assert forbidden_in(source, subprocess_allowed=False) == [
        "line 2: socket", "line 3: http.client", "line 4: google.protobuf",
        "line 5: google.protobuf", "line 5: google.protobuf.descriptor_pb2", "line 6: subprocess",
        "line 7: ssl", "line 9: hashlib",
    ]
    assert "line 6: subprocess" not in forbidden_in(source, subprocess_allowed=True)


def test_the_import_scan_finds_the_names_the_repositorys_gates_forbid():
    """The standard-library networking and crypto modules the repository forbids and the adapter's
    own list does not, a forbidden root, a third-party runtime and the one name only the
    conformance gate lists."""
    source = "\n".join([
        "import socketserver, smtplib, xmlrpc.client, hmac, secrets", "import ftplib, hmac",
        "from poplib import POP3", "import imaplib as mail", "from core import thing",
        "import rdflib.graph", "x = __import__('webbrowser')", "import json, struct, re",
        "import pydantic_core", "import corelib",
    ])
    assert forbidden_in(source, subprocess_allowed=False) == [
        "line 1: socketserver", "line 1: smtplib", "line 1: xmlrpc.client", "line 1: hmac",
        "line 1: secrets", "line 2: ftplib", "line 2: hmac", "line 3: poplib",
        "line 3: poplib.POP3", "line 4: imaplib", "line 5: core", "line 5: core.thing",
        "line 6: rdflib.graph", "line 7: webbrowser",
    ]


def test_the_forbidden_set_holds_every_gate_set_and_the_adapters_own():
    held = set(FORBIDDEN_MODULES)
    assert ADAPTER_FORBIDDEN <= held
    for name, members in HOST_SETS.items():
        assert members, f"the repository's {name} set read as empty: the scan would hold nothing"
        assert members <= held, (name, sorted(members - held))
    assert all(re.fullmatch(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*", name) for name in held)


def test_the_scans_reach_the_adapters_modules_and_its_builder():
    for path in (*RUNTIME_FILES, BUILDER):
        assert path.is_file(), path
    # The builder is the only Python file of the fixture set.
    assert sorted((PKG / "fixtures" / "tacticalapi").rglob("*.py")) == [BUILDER]


@pytest.mark.parametrize("path", [*RUNTIME_FILES, BUILDER], ids=lambda path: path.name)
def test_the_adapters_modules_and_builder_import_nothing_forbidden(path):
    bad = forbidden_in(path.read_text(encoding="utf-8"), subprocess_allowed=path == BUILDER)
    assert not bad, f"{path.name} imports {bad}"


def adapter_python_files() -> list[pathlib.Path]:
    """Every Python file of the adapter: its modules, its builder, its gates, its tests and its
    test helper, as `ARC_FILES` names them."""
    return [path for path in contract_comments.arc_files(ROOT) if path.suffix == ".py"]


def test_the_hashlib_scan_reaches_the_gates_and_the_tests():
    names = {path.relative_to(ROOT).as_posix() for path in adapter_python_files()}
    assert {"gates/tacticalapi_contract_comments.py", "gates/tacticalapi_field_table.py",
            "gates/protoc_text.py", "tests/test_cdm_tacticalapi_contract_text.py",
            "tests/tacticalapi_protowire.py",
            "packages/cdm/synapse_cdm/fixtures/tacticalapi/spec/build_fixtures.py",
            "packages/cdm/synapse_cdm/adapters/tacticalapi_codec.py"} <= names


@pytest.mark.parametrize("path", adapter_python_files(),
                         ids=lambda path: path.relative_to(ROOT).as_posix())
def test_no_python_file_of_the_adapter_imports_hashlib(path):
    """Every hash goes through `synapse_cdm.evidence`, which keeps `hashlib` to itself; the
    adapter's gates hash through it too (`gates/tacticalapi_contract_comments.py` hands it the
    literal's octets), so no file of the adapter needs `hashlib`. The repository's own boundary
    gate holds the package; this holds the adapter's gates and tests as well, which the
    repository's other tests may not be held to."""
    bad = [f"line {line}: {name}" for line, name in imported_names(path.read_text(encoding="utf-8"))
           if matches(name, "hashlib")]
    assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


# ------------------------------------------------------------------ 2. runtime dependencies


@pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda path: path.name)
def test_the_adapters_modules_import_the_standard_library_pydantic_and_the_package_only(path):
    outside = []
    for line, name in imported_names(path.read_text(encoding="utf-8")):
        top = name.split(".")[0]
        if top in sys.stdlib_module_names or top in RUNTIME_ALLOWED:
            continue
        outside.append(f"line {line}: {name}")
    assert not outside, f"{path.name} imports {outside}"


# ------------------------------------------------------------------------ 3. no wall clock

#: Calls that read the current time, as `<module alias>.<function>`. `self.now()` — the adapter's
#: injected clock — is not among them, because its base is `self`.
WALL_CLOCK = {
    ("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"), ("date", "today"),
    ("time", "time"), ("time", "time_ns"), ("time", "monotonic"), ("time", "monotonic_ns"),
    ("time", "perf_counter"), ("time", "perf_counter_ns"), ("time", "localtime"),
    ("time", "gmtime"), ("time", "ctime"),
}


def wall_clock_reads(source: str) -> list[str]:
    """`<x>.<f>()` and `<m>.<x>.<f>()` calls where `<x>.<f>` is in WALL_CLOCK (any alias of the
    datetime module counts: `dt.datetime.now()` is `datetime.now`)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        base = node.func.value
        owner = base.attr if isinstance(base, ast.Attribute) else (
            base.id if isinstance(base, ast.Name) else None)
        if (owner, node.func.attr) in WALL_CLOCK:
            found.append(f"line {node.lineno}: {owner}.{node.func.attr}()")
    return found


def test_the_wall_clock_scan_finds_what_it_looks_for():
    source = "\n".join([
        "import datetime as dt", "import time", "a = dt.datetime.now(dt.timezone.utc)",
        "b = time.time()", "c = self.now()", "d = dt.date.today()", "e = dt.timedelta(1)",
    ])
    assert wall_clock_reads(source) == [
        "line 3: datetime.now()", "line 4: time.time()", "line 6: date.today()"]


@pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda path: path.name)
def test_the_adapters_modules_never_read_the_wall_clock(path):
    reads = wall_clock_reads(path.read_text(encoding="utf-8"))
    assert not reads, f"{path.name} reads the clock: {reads}"


# --------------------------------------------------------------- 4. the comment literals


def test_the_file_listing_reads_the_adapters_files_and_passes_over_caches(tmp_path):
    """`arc_files` lists what `ARC_FILES` names under a root and nothing else: no file outside
    those patterns, and none of the caches a test run may leave beside them."""
    for relative in ("packages/cdm/synapse_cdm/adapters/tacticalapi.py",
                     "packages/cdm/synapse_cdm/adapters/__pycache__/tacticalapi.cpython-314.pyc",
                     "packages/cdm/synapse_cdm/adapters/dis7.py",
                     "packages/cdm/synapse_cdm/fixtures/tacticalapi/golden/a.cdm.json",
                     "packages/cdm/synapse_cdm/fixtures/tacticalapi/spec/__pycache__/b.pyc",
                     "packages/cdm/synapse_cdm/fixtures/dis7/README.md",
                     "tests/test_cdm_tacticalapi_x.py", "tests/__pycache__/t.pyc",
                     "tests/test_cdm_dis7_adapter.py", "gates/tacticalapi_y.py",
                     "gates/wheel_install.py", "NOTICE", "README.md", "docs/other.md",
                     "docs/tacticalapi-implementation.md", ".pytest_cache/v/cache/nodeids"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_bytes(b"x")
    assert [path.relative_to(tmp_path).as_posix()
            for path in contract_comments.arc_files(tmp_path)] == [
        "NOTICE", "docs/tacticalapi-implementation.md", "gates/tacticalapi_y.py",
        "packages/cdm/synapse_cdm/adapters/tacticalapi.py",
        "packages/cdm/synapse_cdm/fixtures/tacticalapi/golden/a.cdm.json",
        "tests/test_cdm_tacticalapi_x.py"]


def test_the_comment_literal_scan_finds_what_it_looks_for():
    """On a synthetic interface definition: a long literal with a digit that occurs only in
    comments is fingerprinted and then found in a file in any case. One the code also holds, one
    after `//` inside a quoted string, a short one and a digit-free one are not fingerprinted."""
    source = "\n".join([
        "// See EXERCISE-REF-0001 and EXERCISE-WORDS, revision 2.",
        'syntax = "proto3";',
        'option go_package = "EXERCISE-PKG-0002"; // EXERCISE-PKG-0002 again',
        'option java_package = "a//EXERCISE-IN-STRING-0006";',
        "message Exercise0003Name { string a = 1; } /* EXERCISE-BLOCK-0004 */",
        "enum E { E_0 = 0; } // Exercise0003Name, named in a comment too",
        '/* "EXERCISE-QUOTED-0005" is inside a comment, so it counts */',
    ])
    found = contract_comments.comment_only([source])
    assert found == {"exercise-ref-0001", "exercise-block-0004", "exercise-quoted-0005"}
    digests = [contract_comments.fingerprint(literal) for literal in found]
    assert contract_comments.matches(b'uuid: "exercise-REF-0001"\n', digests) == \
        ["exercise-ref-0001"]
    assert contract_comments.matches(b"\xff EXERCISE-BLOCK-0004\xfe", digests) == \
        ["exercise-block-0004"]
    # A literal is matched whole and by every run of its joined parts: `x-EXERCISE-QUOTED-0005`
    # holds the fingerprinted run, and `EXERCISE-REF-00011` holds none, since its last part is
    # another.
    assert contract_comments.matches(b"EXERCISE-REF-00011", digests) == []
    assert contract_comments.matches(b"x-EXERCISE-QUOTED-0005", digests) == ["exercise-quoted-0005"]


def test_the_comment_literal_scan_finds_a_value_inside_a_longer_literal():
    """The value as the adapter writes an external id (`<member>:<value>`), behind a URN prefix,
    as a file name and inside a URL's path; and a shortened form. A comment literal that is a run
    of a code literal is a part of one of the contract's names and is not fingerprinted, so a
    name the adapter takes from the code is never a hit."""
    source = "\n".join([
        "// The example EXERCISE-UUID-0001-0002 and Run-0007 are named here.",
        'option csharp_namespace = "Exercise.Run-0007.Name";',
    ])
    found = contract_comments.comment_only([source])
    assert found == {"exercise-uuid-0001-0002"}
    digests = [contract_comments.fingerprint(literal) for literal in found]
    for octets in (b"uuid_identity:EXERCISE-UUID-0001-0002", b"urn:uuid:exercise-uuid-0001-0002",
                   b"EXERCISE-UUID-0001-0002.json",
                   b"https://example.test/a/EXERCISE-UUID-0001-0002/b",
                   b"x.EXERCISE-UUID-0001-0002:7"):
        assert contract_comments.matches(octets, digests) == ["exercise-uuid-0001-0002"], octets
    for octets in (b"EXERCISE-UUID-0001-00022", b"EXERCISE-UUID-0001", b"Exercise.Run-0007.Name",
                   b"EXERCISE_UUID-0001-0002"):
        assert contract_comments.matches(octets, digests) == [], octets
    generated = contract_comments.fingerprinted([source])
    assert generated == {"exercise-uuid-0001-0002", "exercise-uuid-0001", "uuid-0001-0002",
                         "uuid-0001", "0001-0002"}
    digests = [contract_comments.fingerprint(literal) for literal in generated]
    assert contract_comments.matches(b"id EXERCISE-UUID-0001", digests) == [
        "exercise-uuid-0001", "uuid-0001"]
    assert contract_comments.matches(b"Exercise.Run-0007.Name EXERCISE-UUID", digests) == []


def test_the_prose_check_finds_six_words_of_comment_text_and_not_five():
    """`gates/tacticalapi_contract_comments.py --check-prose`, which reads the pinned files and is
    run by hand, on a synthetic source: six consecutive words of comment text are found in any
    case and across punctuation and line breaks, with the line they start on; five are not; words
    of the code are not comment text."""
    source = "\n".join([
        "// The EXERCISE relay reports every unit it can reach,",
        "// once a minute.",
        'message ExerciseRelayReportsEveryUnitItCan { string can_reach_once = 1; }',
    ])
    windows = contract_comments.comment_windows([source])
    assert ("exercise", "relay", "reports", "every", "unit", "it") in windows
    assert contract_comments.shared_windows(b"x\nthe exercise RELAY reports\n every unit, it",
                                            windows) == [2]
    assert contract_comments.shared_windows(b"the exercise relay reports every", windows) == []
    assert contract_comments.shared_windows(
        b"ExerciseRelayReportsEveryUnitItCan { string can_reach_once = 1", windows) == []
    assert contract_comments.WINDOW == 6


def digests_record() -> dict:
    return json.loads((ROOT / contract_comments.DIGESTS).read_text(encoding="utf-8"))


def test_the_comment_digests_are_well_formed_and_from_the_tables_pin():
    """The digests file is what `gates/tacticalapi_contract_comments.py` writes, and it was taken
    from the commit the codec's field table was generated from, which the descriptor test holds to
    the pin. A new pin therefore fails here until the digests are taken again."""
    text = (ROOT / contract_comments.DIGESTS).read_text(encoding="utf-8")
    record = digests_record()
    assert text == json.dumps(record, indent=2) + "\n"
    assert set(record) == {"commit", "sha256"}
    table_commit = re.findall(r"^# upstream commit ([0-9a-f]{40})\.",
                              CODEC.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert table_commit == [record["commit"]]
    assert record["sha256"], "no fingerprint at all: the scan below would match nothing"
    assert record["sha256"] == sorted(set(record["sha256"]))
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in record["sha256"])


def test_the_scans_reach_every_file_of_the_adapter_golden_and_payloads_included():
    names = {path.relative_to(ROOT).as_posix() for path in contract_comments.arc_files(ROOT)}
    fixtures = "packages/cdm/synapse_cdm/fixtures/tacticalapi"
    for expected in ("packages/cdm/synapse_cdm/adapters/tacticalapi.py",
                     "packages/cdm/synapse_cdm/adapters/tacticalapi_codec.py",
                     f"{fixtures}/golden/snapshot_with_unknown_fields.cdm.json",
                     f"{fixtures}/snapshot_with_unknown_fields.binpb",
                     f"{fixtures}/spec/tacticalapi_pin.json", f"{fixtures}/README.md",
                     "docs/tacticalapi-implementation.md", "docs/docs/cdm/tacticalapi.mdx",
                     "NOTICE", "packages/cdm/NOTICE", "tests/tacticalapi_comment_digests.json",
                     "tests/test_cdm_tacticalapi_adapter.py"):
        assert expected in names, expected
    tracked = sorted((PKG / "fixtures" / "tacticalapi").rglob("*"))
    assert len([path for path in tracked if path.is_file()]) == 112


def test_no_file_of_the_adapter_holds_a_literal_the_contract_has_only_in_a_comment():
    digests = digests_record()["sha256"]
    offenders = {}
    for path in contract_comments.arc_files(ROOT):
        found = contract_comments.matches(path.read_bytes(), digests)
        if found:
            offenders[path.relative_to(ROOT).as_posix()] = found
    assert not offenders, offenders


# ------------------------------------------------------------------ 5. licence hygiene, octets

#: Built from parts so that this file, which is scanned too, does not contain them whole.
LICENCE_TAGS = (b"SPDX-" + b"License-Identifier", b"SPDX-" + b"FileCopyrightText")
#: The word, then "(c)", a copyright sign, a four-digit year or the licence appendix template's
#: "[yyyy]", as a notice line begins, on the octets (so a file that is not UTF-8 is read too).
COPYRIGHT_NOTICE = re.compile(b"(?i)" + b"copy" + b"right"
                              + rb"\s*(?:\(c\)|\xc2\xa9|[0-9]{4}|\[yyyy\])")
#: The same on the text the octets decode to, as `tests/test_cdm_publication.py` reads it: white
#: space is Unicode's and a digit is any decimal digit.
COPYRIGHT_NOTICE_TEXT = re.compile("(?i)" + "copy" + "right"
                                   + r"\s*(?:\(c\)|©|\d{4}|\[yyyy\])")
#: The two licence files among the adapter's files: they carry the repository's own notice, which
#: is where `tests/test_cdm_publication.py` requires it to be.
LICENCE_FILES = ("NOTICE", "packages/cdm/NOTICE")


def licence_findings(octets: bytes) -> list[str]:
    found = [tag.decode("ascii") for tag in LICENCE_TAGS if tag in octets]
    found += [match.group().decode("utf-8", "replace")
              for match in COPYRIGHT_NOTICE.finditer(octets)]
    found += [match.group() for match in COPYRIGHT_NOTICE_TEXT.finditer(
        octets.decode("utf-8", "replace")) if match.group() not in found]
    return found


def test_the_licence_scan_finds_what_it_looks_for():
    tag = b"SPDX-" + b"License-Identifier"
    assert licence_findings(b"// " + tag + b": X") == [tag.decode("ascii")]
    word = b"Copy" + b"right"
    for line in (word + b"(c) 2026 Someone", word + b" 2026 Someone", word + b" \xc2\xa9 Someone",
                 word.lower() + b" (C) Someone", word + b" [yyyy] [name of owner]",
                 word + b"\xc2\xa02026 Someone", word + " ".encode() + b"2026",
                 b"\xff" + word + b" [YYYY] \xfe"):
        assert licence_findings(line), line
    assert licence_findings(b"no file here contains a " + word.lower() + b" notice line") == []


def test_no_file_of_the_adapter_but_the_licence_files_carries_a_licence_tag_or_a_notice():
    offenders = {}
    scanned = 0
    for path in contract_comments.arc_files(ROOT):
        name = path.relative_to(ROOT).as_posix()
        if name in LICENCE_FILES:
            continue
        scanned += 1
        found = licence_findings(path.read_bytes())
        if found:
            offenders[name] = found
    assert scanned > 112, "the scan reached fewer files than the fixture set alone holds"
    assert not offenders, offenders


# ------------------------------------------------------------------- 6. the rulings and the pin


def record_section(heading: str) -> str:
    text = RECORD.read_text(encoding="utf-8")
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


RULINGS = "The maintainer's rulings (2026-10-06)"


def ruling_rows() -> dict[str, list[str]]:
    section = record_section(RULINGS)
    return {cells[0]: cells[1:] for cells in (
        [cell.strip() for cell in line.strip("|").split(" | ")]
        for line in section.splitlines() if re.match(r"^\| R\d+ \|", line))}


def test_every_ruling_is_dated_and_states_whether_it_changed_or_confirmed_what_was_built():
    """The maintainer's rulings of 2026-10-06 ("Changes", item 40, of the record): the table that
    held the out-of-tree project's defaults holds the ruled value of each row and its date. R3, R5
    and R7 changed the adapter; R2, R4 and R6 confirmed it. Re-anchored on 2026-10-06 from the
    project's README to the record, which holds the table now."""
    rows = ruling_rows()
    assert list(rows) == [f"R{number}" for number in range(1, 11)]
    assert all(len(cells) == 3 for cells in rows.values()), rows
    dated = {row: cells[2] for row, cells in rows.items()}
    assert all(when.endswith(" 2026-10-06") for when in dated.values()), dated
    assert {row for row, when in dated.items() if when.startswith("changed")} == {
        "R3", "R5", "R7"}
    assert {row for row, when in dated.items() if when.startswith("confirmed")} == {
        "R2", "R4", "R6"}
    assert {row for row, when in dated.items() if when.startswith("ruled")} == {
        "R1", "R8", "R9", "R10"}
    assert rows["R2"][1].startswith("Confirmed:") and "`VERIFIED`" in rows["R2"][1]
    assert "Defaults taken on rulings" not in RECORD.read_text(encoding="utf-8")


def test_the_rulings_table_states_r7_open_and_r8_to_r10_as_ruled():
    """R7 is `OPEN` on the repository's own definition, R8 names the Eclipse Public License 2.0,
    and R9 and R10 are ruled; the export-control note stays recorded beside its ruling, and §8
    of the record marks questions 6, 7 and 8 ruled, not asked."""
    rows = ruling_rows()
    question, ruling, _ = rows["R7"]
    assert question == "`license_class`"
    assert ruling.startswith("Changed: `OPEN`.") and "ARCHITECTURE.md §3.2" in ruling
    assert "publicly available under terms permitting free implementation" in ruling
    question, ruling, _ = rows["R8"]
    assert ruling.startswith("Ruled: the Eclipse Public License 2.0")
    assert "BSD three-clause licence, is not taken" in ruling
    question, ruling, _ = rows["R9"]
    assert ruling.startswith("Ruled: the name") and "no written consent is sought" in ruling
    assert "§8, question 7, is ruled, not asked" in ruling
    question, ruling, _ = rows["R10"]
    assert question == "Export control"
    assert ruling.startswith("Ruled unaffected:") and "not a controlled item" in ruling
    assert "export-control law" in ruling and "§8, question 8" in ruling
    mapping = RECORD.read_text(encoding="utf-8")
    questions = mapping.split("## 8. Questions for the upstream publisher", 1)[1]
    questions = questions.split("\n## ", 1)[0]
    items = {match.group(1): match.group(2) for match in re.finditer(
        r"^(\d)\. (.*?)(?=^\d\. |\Z)", questions, flags=re.MULTILINE | re.DOTALL)}
    assert sorted(items) == [str(number) for number in range(1, 9)]
    ruled = "*Ruled by the maintainer on\n   2026-10-06, not asked:*"
    for number in ("6", "7", "8"):
        assert " ".join(items[number].split()).count(" ".join(ruled.split())) == 1, number
    assert items["8"].startswith("Which export-control regime") and "the rulings, R10" in items["8"]
    assert items["6"].startswith("Which licence statement governs")
    assert items["7"].startswith("Consent to use the interface name.")
    assert "R5 (the rulings, ruled 2026-10-06)\n   assumes true north" in items["2"]
    for number in ("1", "2", "3", "4", "5"):
        assert "not asked" not in items[number], number


def test_the_pin_record_states_the_r8_to_r10_rulings_beside_what_upstream_says():
    """R8, R9 and R10 (2026-10-06) in the shipped pin record's own `terms`, whose shape is
    unchanged: the licence the headers offer and the one the licence file holds, the names
    reservation and the export-control note, each with its ruling. Re-anchored on 2026-10-06 to
    the shipped pin; the citation of the rulings names the record, every other phrase is the one
    the out-of-tree project asserted."""
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    terms = pin["contract"]["terms"]
    assert set(pin["contract"]) == {"package", "edition", "files", "terms", "carried_here",
                                    "why_not_carried"}
    for said in ("The maintainer ruled on 2026-10-06 that the Eclipse Public License 2.0 governs "
                 "the files", "the headers' BSD-style alternative is not taken",
                 "(docs/tacticalapi-implementation.md of the repository, R8)",
                 "reserves the publisher's names", "without seeking written consent", "(R9)",
                 "export-control law may apply to using the files", "is not a controlled item",
                 "nothing here is classified (R10)"):
        assert said in terms, said
    assert "still open" not in terms
    assert pin["contract"]["carried_here"] is False
    assert pin["adapter"]["ordinal"] == 22 and pin["adapter"]["name"] == "tacticalapi"


def test_the_record_states_the_field_tables_licence():
    """R8 (2026-10-06): the record's section on the field table's licence, facts and the ruling
    only, and where the repository states it."""
    notice = " ".join(record_section("Licence of the embedded field table").split())
    for said in ("The field table in `pkg/adapters/tacticalapi_codec.py` is derived from the "
                 "interface definition files of github.com/Rheinmetall/tacticalapi at commit "
                 "`58661c9`.", "The maintainer ruled on 2026-10-06 that the Eclipse Public "
                 "License 2.0 (EPL-2.0) governs those files (R8).", "field names, field numbers "
                 "and enum values only, and no text of the files", "Both copies of `NOTICE` "
                 "state the derivation"):
        assert said in notice, said
