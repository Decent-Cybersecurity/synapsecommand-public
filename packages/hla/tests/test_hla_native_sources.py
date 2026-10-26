"""The native sources and the OpenRTI build wrapper, read and exercised without an RTI (round R7).

What a reading of the source can hold, and nothing a running worker shows better: the file types
of `src/native` and `tools` (D-04), the constructs R18 and R40 forbid in C++ that touches
untrusted bytes, the RTI services R02, R13 and R39 exclude (the worker's sources name none of
them), the headers and libraries R02 and R43 prescribe, the CMake project's flags and loader path
(R43, NAT-13), the worker's compile-time limits against the specification's table (SPEC:217-231)
and the build wrapper `tools/build_openrti.sh` run against recording stand-ins for cmake, tar,
uname and the compiler, so that its exact commands are checked without building anything.

These tests are in the offline group: they open no socket and start no RTI. The wrapper test
needs the pinned OpenRTI archive, which it finds beside the FOM modules (the handoff's references
directory holds both); absent, it is BLOCKED (D-07).
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import stat
import subprocess

import pytest

from hla_support import (
    PACKAGE_ROOT, blocked, case, fom_modules, packaged_pins, strict_json, package_bytes,
)
from synapse_hla import limits

NATIVE = PACKAGE_ROOT / "src" / "native"
WORKER_SOURCES = sorted((NATIVE / "worker").iterdir())
TEST_SOURCES = sorted((NATIVE / "tests").iterdir())
TOOLS = PACKAGE_ROOT / "tools"
WRAPPER = TOOLS / "build_openrti.sh"


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


#: One pass over C++ source, left to right: whichever of a numeric literal, a comment, a string
#: literal or a character literal starts first is one token, so a `//` inside a string is not a
#: comment, a quotation mark inside a comment or a character literal opens no string, and the
#: digit separator of C++14 (`1'000`, `0xFF'FF`) is part of its number, never the start of a
#: character literal (review finding R7-r2-F4). A number starts at a digit that does not continue
#: an identifier. Raw string literals (R"(...)") do not occur in the sources (a test below holds
#: that).
_CPP_TOKENS = re.compile(r"""(?<![\w.])\d(?:'?[0-9A-Za-z_.])*|//[^\n]*|/\*.*?\*/"""
                         r"""|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'""", re.S)


def code_of(source: str) -> str:
    """C++ without its comments and string and character literals: what the compiler reads as
    code (comments become a space, literals empty literals, numbers stay)."""
    def blank(match: re.Match) -> str:
        token = match.group(0)
        if token[0].isdigit():
            return token
        if token.startswith("/"):
            return " "
        return token[0] * 2
    return _CPP_TOKENS.sub(blank, source)


#: (source, what code_of must keep, what it must drop), written out by hand: review finding
#: R7-r1-F5's evasion (a `//` inside a string hid the rest of the line), and its relatives.
CODE_OF_CASES = [
    ('const char* u = "rti://"; system("ls");', 'system("")', "rti:"),
    ('f("/* not a comment */"); popen("x");', 'popen("")', "not a comment"),
    ("x = '\"'; system(y); // \"a comment\"", "system(y)", "a comment"),
    ("/* it's \"quoted\" */ getenv(z);", "getenv(z)", "quoted"),
    ('s = "a\\"b // c"; fork();', "fork()", "// c"),
    ("c = '/'; d = '/'; memcpy(a, b, 1);", "memcpy(a, b, 1)", "'/'"),
    # R7-r2-F4: a digit separator opened a character literal that ran to the next quotation
    # mark and hid the code between ("int n = 1''x';" was what the old pass kept).
    ("int n = 1'000; system(a); char c = 'x';", "system(a)", "'x'"),
    ("u = 0xFF'FF; popen(b); w = L'n'; k = 2'5;", "popen(b)", "'n'"),
]


@pytest.mark.parametrize("source,kept,dropped", CODE_OF_CASES,
                         ids=range(len(CODE_OF_CASES)))
def test_code_of_drops_comments_and_literals_without_hiding_code(source, kept, dropped):
    """The static checks below read `code_of` of each source: a forbidden construct after a
    string that contains `//` or `/*`, after a character literal holding a quotation mark, or
    after a comment holding one, is still seen; text inside literals and comments is not."""
    code = code_of(source)
    assert kept in code and dropped not in code, code


CPP_SOURCES = [p for p in WORKER_SOURCES + TEST_SOURCES if p.suffix in (".cpp", ".h")]


@pytest.mark.parametrize("path", CPP_SOURCES, ids=[p.name for p in CPP_SOURCES])
def test_the_native_sources_hold_no_raw_string_literal(path):
    """`code_of` does not tokenize C++11 raw string literals; none occurs in the C++ sources."""
    assert re.search(r'\bu?8?[LuU]?R"', text(path)) is None


# ============================================================================ file types (D-04)

def test_the_native_and_tool_trees_hold_only_cpp_cmake_and_shell():
    """D-04 and exit criterion 6 of the brief: under `src/native` and `tools` every file is C++
    (`.cpp`, `.h`), CMake (`CMakeLists.txt`, `.cmake`) or shell (`.sh`, starting with a shell
    line); no Python, no build output, nothing else."""
    found = []
    for root in (NATIVE, TOOLS):
        for directory, names, files in os.walk(root):
            assert not {"build", "dist", "CMakeFiles"} & set(names), directory
            for name in files:
                found.append(pathlib.Path(directory, name))
    assert found
    for path in found:
        name = path.name
        if name == "CMakeLists.txt" or path.suffix in (".cpp", ".h", ".cmake"):
            continue
        assert path.suffix == ".sh", path
        assert text(path).startswith(("#!/bin/sh\n", "#!/usr/bin/env bash\n")), path


# =============================================================== R18, R40: C++ that touches bytes

#: Constructs the worker must never use on input bytes or untrusted strings: a cast of bytes to a
#: structure, native packing (R18 clause 3), a shell or another program (R40), the environment
#: beyond clearing OpenRTI's two debug variables (NAV-01), formatted output (a format string from
#: data), and raw byte copies into structures.
FORBIDDEN_CONSTRUCTS = {
    "reinterpret_cast": r"\breinterpret_cast\b",
    "C-style cast to a pointer of a struct": r"\(\s*(?:const\s+)?struct\s+\w+\s*\*\s*\)",
    "packing": r"#\s*pragma\s+pack|__attribute__\s*\(\(\s*packed|alignas\s*\(\s*1\s*\)",
    "memcpy": r"\bmem(?:cpy|move)\b",
    "system": r"\bsystem\s*\(",
    "popen": r"\bpopen\s*\(",
    "exec": r"\bexec[lv]p?e?\s*\(|\bposix_spawnp?\s*\(|\bfork\s*\(",
    "getenv": r"\bgetenv\s*\(|\bsecure_getenv\s*\(|\benviron\b",
    "printf family": r"\b(?:v?[fs]?n?printf|wprintf|syslog)\s*\(",
    "iostream output": r"std::(?:cout|cerr|wcout|wcerr|clog)\b",
}


@case("G-R18", "G-R02")
@pytest.mark.parametrize("path", WORKER_SOURCES, ids=[p.name for p in WORKER_SOURCES])
def test_the_worker_source_uses_none_of_the_forbidden_constructs(path):
    """R18 clause 3 (the carried G-R18 clause: no structure cast of input bytes, no native packing,
    the bytes copied as they came), R40 (no shell execution or generated executable paths) and
    the brief's list (no getenv; unsetenv of the two OpenRTI variables only; no printf family on
    untrusted strings): none of these constructs occurs in the code of the worker's sources."""
    code = code_of(text(path))
    for what, pattern in FORBIDDEN_CONSTRUCTS.items():
        assert re.search(pattern, code) is None, f"{path.name}: {what}"
    for match in re.finditer(r"\bunsetenv\s*\(([^)]*)\)", text(path)):
        assert match.group(1) in ('"OPENRTI_DEBUG_PRIORITY"', '"OPENRTI_DEBUG_CATEGORY"'), match


def test_the_worker_clears_both_openrti_variables_first_thing_in_main():
    """NAV-01: `clear_openrti_debug_variables()` unsets exactly the two variables, and it is the
    first statement of the worker's main."""
    process = text(NATIVE / "worker" / "process.cpp")
    assert re.findall(r'unsetenv\("(\w+)"\)', process) == ["OPENRTI_DEBUG_PRIORITY",
                                                         "OPENRTI_DEBUG_CATEGORY"]
    main = code_of(text(NATIVE / "worker" / "main.cpp"))
    opening = "int main(int argc, char** argv) {"
    body = main[main.index(opening) + len(opening):]
    assert body.lstrip().startswith("sc_hla::clear_openrti_debug_variables();")


# ======================================================================== R02, R13, R39: services

def forbidden_services() -> set[str]:
    """Every RTIambassador service but the ten NAT-07 (b) allows, as the recording decorator
    lists them from the pinned header (each with its own `forbidden("<name>")`)."""
    calls = text(NATIVE / "tests" / "recording_ambassador_calls.h")
    return set(re.findall(r'forbidden\("(\w+)"\)', calls))


ALLOWED = {"connect", "joinFederationExecution", "getObjectClassHandle", "getAttributeHandle",
           "getAttributeName", "subscribeObjectClassAttributes", "requestAttributeValueUpdate",
           "evokeMultipleCallbacks", "resignFederationExecution", "disconnect"}


def test_the_decorator_overrides_every_service_and_allows_exactly_nat_07s_ten():
    """NAT-07 (b): the decorator's generated list holds 151 overrides, one per pure virtual
    member of the pinned RTIambassador (the compiler holds that none is missing: the class would
    be abstract). Ten are declared for the hand-written forwarding of the allowed calls (two of
    them one overload of two: the named join and the object-instance request); the 141 others each
    call `forbidden` with their own name."""
    calls = text(NATIVE / "tests" / "recording_ambassador_calls.h")
    declared = re.findall(r"\b(\w+)\((?:[^()]|\n)*\)(?:\s+const)?\s+RTI_THROW\(\((?:[^()]|\n)*\)\) "
                          r"override;", calls)
    assert sorted(declared) == sorted(ALLOWED)
    bodies = re.findall(r"\b(\w+)\((?:[^()]|\n)*\)(?:\s+const)?\s+RTI_THROW\(\((?:[^()]|\n)*\)\) "
                        r"override \{\n    forbidden\(\"(\w+)\"\);\n  \}", calls)
    assert len(bodies) == 141 and all(name == called for name, called in bodies)
    assert len(declared) + len(bodies) == 151
    assert {name for name, _ in bodies} == forbidden_services()
    assert {"joinFederationExecution", "requestAttributeValueUpdate"} <= forbidden_services()


@case("G-R02", "G-R13", "G-R10", "G-R07", paragraphs=("SPEC:50", "SPEC:38"))
@pytest.mark.parametrize("path", WORKER_SOURCES, ids=[p.name for p in WORKER_SOURCES])
def test_the_worker_names_no_service_a_receive_only_observer_must_not_call(path):
    """R02 (no interactions, publication, ownership, DDM, save/restore, time regulation or
    constrained advancement), R13 (no change of order or transportation, no interaction), R39
    (no update, no registration, no deletion), R10 and the carried G-R07 clause (SPEC:38: never
    create or destroy a federation, never a FOM module of its own), SPEC:50 (no subclass
    resolved, no class name asked for: NAT-04): no identifier of the worker's code is one of the
    141 services the decorator forbids. Only the ten allowed ones, and of the overloaded ones
    only the instance request and the named join (held by the decorator at run time)."""
    identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", code_of(text(path))))
    assert identifiers & (forbidden_services() - {"joinFederationExecution",
                                                  "requestAttributeValueUpdate"}) == set()
    used = identifiers & (forbidden_services() | ALLOWED)
    assert used <= ALLOWED


#: The rti1516e headers of the pinned OpenRTI the worker may include (R02: HLA Evolved through
#: the C++ rti1516e API; nothing of HLA 1.3 or IEEE 1516-2000).
RTI_HEADERS = {"RTI/Handle.h", "RTI/LogicalTime.h", "RTI/NullFederateAmbassador.h",
               "RTI/RTIambassador.h", "RTI/RTIambassadorFactory.h"}


@case("G-R02")
def test_the_worker_uses_the_rti1516e_api_and_links_its_libraries():
    """R02 and R43: the worker's RTI includes are rti1516e headers only (no RTI.hh of HLA 1.3,
    no rti1516 of IEEE 1516-2000), the include directory is the install's include/rti1516e, and
    the targets link rti1516e and fedtime1516e."""
    includes = set()
    for path in WORKER_SOURCES:
        includes |= set(re.findall(r"#include <(RTI/[^>]+)>", text(path)))
        assert not re.search(r"#include [<\"](?:RTI\.hh|rti1516/|hla13|RTI13)", text(path))
    assert includes == RTI_HEADERS
    cmake = text(NATIVE / "CMakeLists.txt")
    assert 'set(OPENRTI_INCLUDE "${OPENRTI_PREFIX}/include/rti1516e")' in cmake
    assert "target_link_libraries(openrti_rti1516e INTERFACE rti1516e fedtime1516e)" in cmake


#: The project's own C++ (the worker, its test programs and the synthetic publisher); the two
#: reference tools under tools/reference are the bundle's, vendored byte for byte, and include
#: RTIambassadorFactory.h (which includes <memory>) first.
OWN_CPP = sorted(CPP_SOURCES + [p for p in (TOOLS / "publisher").iterdir()
                                if p.suffix in (".cpp", ".h")])
#: The one header of the pinned rti1516e API (C++14) that names std::auto_ptr through
#: RTI_UNIQUE_PTR while no header in its own include closure includes <memory>, read off the
#: pinned OpenRTI install by hand: SpecificConfig.h defines the macro, RTIambassador.h uses it in
#: getTimeFactory and includes only SpecificConfig.h, <string>, Typedefs.h and the handle and
#: exception headers. The other users (LogicalTimeFactory.h, RTIambassadorFactory.h, the encoding
#: and time-factory headers) include <memory> themselves.
NEEDS_MEMORY = "<RTI/RTIambassador.h>"
_INCLUDE = re.compile(r"^\s*#\s*include\s*([<\"][^>\"]+[>\"])", re.M)


def include_sequence(path: pathlib.Path, seen: set | None = None) -> list[str]:
    """The includes of `path` in the order the compiler meets them, the project's own quoted
    headers expanded where they are included (each once, as their include guards make it)."""
    seen = set() if seen is None else seen
    out = []
    for name in _INCLUDE.findall(code_of(text(path))):
        if name.startswith('"'):
            own = name.strip('"')
            for directory in (path.parent, NATIVE / "worker"):
                if (directory / own).is_file():
                    if own not in seen:
                        seen.add(own)
                        out += include_sequence(directory / own, seen)
                    break
            else:
                pytest.fail(f"{path.name}: {name} is none of the project's headers")
        else:
            out.append(name)
    return out


def memory_problem(sequence: list[str]) -> bool:
    """True when RTIambassador.h comes before any <memory> in the sequence."""
    if NEEDS_MEMORY not in sequence:
        return False
    return "<memory>" not in sequence[:sequence.index(NEEDS_MEMORY)]


@case("G-R43", paragraphs=("SPEC:241",))
@pytest.mark.parametrize("path", OWN_CPP, ids=[p.name for p in OWN_CPP])
def test_memory_is_included_before_the_rti_ambassador_header(path):
    """CR-L19 (the Linux reference run's finding F1): below C++17 RTIambassador.h names
    std::auto_ptr without including <memory>; libc++ declares it through another header, GCC
    13's libstdc++ does not, and R43's reference compiler stops at the first use. In every
    source of the project, <memory> comes before RTIambassador.h in the order the compiler meets
    the includes, and each of the five that include it directly includes <memory> first of all,
    so a build on this Mac cannot regress what only the reference compiler would show."""
    sequence = include_sequence(path)
    assert not memory_problem(sequence), (path.name, sequence)
    own = _INCLUDE.findall(code_of(text(path)))
    if NEEDS_MEMORY in own:
        assert own[0] == "<memory>" and own.count("<memory>") == 1, (path.name, own)


def test_the_include_order_rule_sees_memory_after_the_ambassador_header():
    """The rule above, against what it forbids: <memory> after RTIambassador.h, <memory> only
    in a comment, and nothing at all; and what it allows."""
    assert memory_problem(["<RTI/NullFederateAmbassador.h>", "<RTI/RTIambassador.h>",
                           "<memory>"])
    assert memory_problem(["<RTI/RTIambassador.h>"])
    assert memory_problem(_INCLUDE.findall(code_of(
        "// #include <memory>\n#include <RTI/RTIambassador.h>\n")))
    assert not memory_problem(["<memory>", "<RTI/NullFederateAmbassador.h>",
                               "<RTI/RTIambassador.h>"])
    assert not memory_problem(["<RTI/Handle.h>", "<cstdint>"])


# ========================================================== the CMake project (R43, NAT-13, D-20)

@case("G-R02")
def test_the_cmake_project_is_cxx14_with_warnings_as_errors_and_a_relative_loader_path():
    """R43 and the brief: CMake 3.28 or later; C++14 required, without extensions; the OpenRTI
    install given only as OPENRTI_PREFIX (nothing searched elsewhere: no find_package of an RTI,
    no pkg-config); -Wall -Wextra -Werror for the project's sources with the two deprecation
    groups of the C++14 rti1516e API allowed and the RTI headers included as system headers; the
    loader path relative, @loader_path/../lib on macOS and $ORIGIN/../lib elsewhere (NAT-13),
    the same in the build tree and the install; sc-hla-federate and (round R8) the synthetic
    publisher sc-hla-publisher installed into bin/; the harness, the test federate and the two
    reference tools never installed, the reference tools compiled as the bundle's commands
    compile them (someone else's sources: no -Werror)."""
    cmake = text(NATIVE / "CMakeLists.txt")
    assert cmake.count("cmake_minimum_required(VERSION 3.28)") == 1
    for line in ("set(CMAKE_CXX_STANDARD 14)", "set(CMAKE_CXX_STANDARD_REQUIRED ON)",
                 "set(CMAKE_CXX_EXTENSIONS OFF)",
                 'set(OPENRTI_PREFIX "" CACHE PATH "Install tree of the pinned OpenRTI build")',
                 "set(SC_HLA_WARNINGS -Wall -Wextra -Werror -Wno-deprecated "
                 "-Wno-deprecated-declarations)",
                 'set(SC_HLA_LOADER_PATH "@loader_path/../lib")',
                 'set(SC_HLA_LOADER_PATH "$ORIGIN/../lib")',
                 "set(CMAKE_BUILD_WITH_INSTALL_RPATH ON)",
                 'set(CMAKE_INSTALL_RPATH "${SC_HLA_LOADER_PATH}")',
                 "target_include_directories(openrti_rti1516e SYSTEM INTERFACE "
                 '"${OPENRTI_INCLUDE}")',
                 "install(TARGETS sc-hla-federate RUNTIME DESTINATION bin)",
                 "install(TARGETS sc-hla-publisher RUNTIME DESTINATION bin)",
                 # R9 (the installed form): the OpenRTI libraries, rtinode and the licence
                 # texts beside them, nothing test-only.
                 'install(DIRECTORY "${CMAKE_BINARY_DIR}/lib/" DESTINATION lib '
                 "USE_SOURCE_PERMISSIONS)",
                 'install(PROGRAMS "${OPENRTI_PREFIX}/bin/rtinode" DESTINATION bin)',
                 'install(DIRECTORY "${SC_HLA_TOOLS}/../licences/" DESTINATION licences)'):
        assert line in cmake, line
    assert cmake.count("install(") == 5
    for target in ("sc_hla_worker", "sc-hla-federate", "sc-hla-harness", "sc-hla-publisher",
                   "sc-hla-test-federate"):
        assert f"target_compile_options({target} PRIVATE ${{SC_HLA_WARNINGS}})" in cmake
    for target in ("sc-hla-reference-encode", "sc-hla-reference-fom-check"):
        assert (f"target_compile_options({target} PRIVATE -Wno-deprecated\n"
                f"                       -Wno-deprecated-declarations)") in cmake
        assert f"target_link_libraries({target} PRIVATE openrti_rti1516e)" in cmake
    assert not re.search(r"find_package\((?!Threads)|pkg_check_modules|find_library", cmake)


def _table(source: str, function: str) -> list[str]:
    """The names a `static const std::map<std::string, ...> table = {...}` of `function` holds."""
    body = source[source.index(function):]
    body = body[body.index("table = {"):body.index("};")]
    return re.findall(r'^\s*\{"([a-z0-9-]+)",', body, flags=re.M)


def test_every_harness_scenario_has_a_ctest_smoke_run():
    """The brief's "register a smoke run of each scenario with ctest": the scenario table of
    harness.cpp and the scenario list of smoke.cmake name the same scenarios, each once, and
    every scenario the decorator fails a call for (faults()) is one of them."""
    harness = text(NATIVE / "tests" / "harness.cpp")
    scenarios = _table(harness, "scenarios() {")
    faults = _table(harness, "faults() {")
    smoke = text(NATIVE / "tests" / "smoke.cmake")
    listed = smoke[smoke.index("set(SC_HLA_SCENARIOS"):smoke.index("foreach(entry")]
    registered = re.findall(r'"([a-z0-9-]+) (?:0|1|71|134) \d+(?: (?:frames|status):\d+)?"',
                            listed)
    assert len(scenarios) == len(set(scenarios)) and len(registered) == len(set(registered))
    assert sorted(registered) == sorted(scenarios)
    assert faults and set(faults) <= set(scenarios)


# ====================================================================== the limits (SPEC:217-231)

#: The worker's compile-time limits, as SPEC:217-231 states them (and NAT-05's pause, NAT-06's
#: name bound, R12's evoke parameters), written out here again.
NATIVE_LIMITS = {
    "kMaxAttributesPerReflection": "4",
    "kMaxAttributeValueBytes": "4096",
    "kMaxUserTagBytes": "4096",
    "kMaxObjectNameBytes": "1024",
    "kMaxLogicalTimeBytes": "256",
    "kMaxAttributeNameBytes": "128",
    "kMaxImplementationNameBytes": "128",
    "kMaxQueueFrames": "4096",
    "kMaxQueueBytes": "16u * 1024u * 1024u",
    "kMaxObjectTokens": "100000",
    "kMaxLineBytes": "65536",
    "kMaxMessageBytes": "1024",
    "kEvokeMinimumSeconds": "0.0",
    "kEvokeMaximumSeconds": "0.05",
    "kIdlePauseNanoseconds": "5000000",
}


@case("G-R41", "G-R12", paragraphs=("SPEC:279", "SPEC:56"))
def test_the_worker_limits_are_the_specification_table_at_their_real_values():
    """OPS-21 ("native limits stay compile-time constants tested at real values") and D-09: each
    constant of `worker/constants.h` is the table's value, the same as `limits.V1`'s for the
    limits both sides hold; R12's literal evoke parameters and NAT-05's 5 ms pause are named
    constants."""
    header = text(NATIVE / "worker" / "constants.h")
    found = dict(re.findall(r"constexpr (?:std::size_t|double|std::int64_t) (k\w+) = ([^;]+);",
                            header))
    assert found == NATIVE_LIMITS
    v1 = limits.V1
    assert (v1.attributes_per_reflection, v1.attribute_value_bytes, v1.user_tag_bytes,
            v1.object_name_utf8_bytes, v1.logical_time_bytes, v1.queue_frames, v1.queue_bytes,
            v1.object_tokens_per_session, v1.line_bytes, v1.diagnostic_message_utf8_bytes) == (
        4, 4096, 4096, 1024, 256, 4096, 16 * 1024 * 1024, 100000, 65536, 1024)


def test_the_version_line_and_the_stage_names_are_the_protocols():
    """CR-R5-02: the worker's version line is the host's, byte for byte; every stage the worker
    writes is one of worker-status.schema.json's (NAT-15: no stage of its own)."""
    process = text(NATIVE / "worker" / "process.cpp")
    assert ('"{\\"name\\":\\"sc-hla-federate\\",\\"profile\\":\\"SC-HLA-RPR2-OBS-1\\",'
            '\\"version\\":\\"1.0.0\\"}\\n";') in process
    schema = strict_json(package_bytes("schemas", "worker-status.schema.json"))
    allowed = set(schema["oneOf"][0]["properties"]["stage"]["enum"])
    written = set()
    for path in WORKER_SOURCES:
        written |= set(re.findall(r'stage\("(\w+)"\)', text(path)))
    assert written == allowed


# =========================================== tools/build_openrti.sh (R43, NAT-12, NAT-13, NAT-02)

#: The configure, build and install commands of the bundle's tools/build_openrti.sh, word for
#: word (R43; the bundle is not in this repository), with B the build directory.
BUNDLE_CONFIGURE = [
    "cmake", "-S", "B/source/OpenRTI-814a210978b7faafd65affbe70a2e25679921b23",
    "-B", "B/build", "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_STANDARD=14",
    "-DOPENRTI_ENABLE_RTI13=OFF", "-DOPENRTI_ENABLE_RTI1516=OFF",
    "-DOPENRTI_ENABLE_RTI1516E=ON", "-DOPENRTI_ENABLE_PYTHON_BINDINGS=OFF",
    "-DOPENRTI_BUILD_SHARED=ON", "-DCMAKE_INSTALL_PREFIX=B/install",
]
BUNDLE_BUILD = ["cmake", "--build", "B/build", "--parallel", "4"]
BUNDLE_INSTALL = ["cmake", "--install", "B/build"]

STUB_CMAKE = r"""#!/bin/sh
# A stand-in for cmake: records its argument vector, one argument per line, then a blank line.
for argument in "$@"; do printf '%s\n' "$argument"; done >>"$STUB_LOG"
printf '\n' >>"$STUB_LOG"
case "$1" in
  --version) echo "cmake version $STUB_CMAKE_VERSION"; echo; echo "CMake suite";;
  -S)
    build=""
    while [ "$#" -gt 0 ]; do [ "$1" = -B ] && build=$2; shift; done
    mkdir -p "$build"
    printf 'CMAKE_CXX_COMPILER:FILEPATH=%s\nCMAKE_CXX_STANDARD:UNINITIALIZED=%s\n' \
      "$STUB_COMPILER" "$STUB_STANDARD" >"$build/CMakeCache.txt";;
esac
"""
STUB_TAR = r"""#!/bin/sh
for argument in "$@"; do printf '%s\n' "$argument"; done >>"$STUB_LOG"
printf '\n' >>"$STUB_LOG"
mkdir -p "$4/OpenRTI-814a210978b7faafd65affbe70a2e25679921b23"
"""
STUB_UNAME = r"""#!/bin/sh
case "$1" in -s) echo "$STUB_SYSTEM";; -m) echo "$STUB_MACHINE";; esac
"""
STUB_COMPILER = r"""#!/bin/sh
echo "$STUB_COMPILER_LINE"
"""
#: First lines of `c++ --version`: Ubuntu 24.04's GCC 13 (the reference run's), a GCC 14 of the
#: same distribution, and Apple's clang of the development Mac.
GCC13 = "c++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
GCC14 = "c++ (Ubuntu 14.2.0-4ubuntu2~24.04) 14.2.0"
CLANG = "Apple clang version 21.0.0 (clang-2100.1.1.101)"


def openrti_archive() -> pathlib.Path:
    """The pinned OpenRTI archive, beside the FOM modules (the handoff's references directory)."""
    path = fom_modules()[0].parent / "openrti-814a210.tar.gz"
    if not path.is_file():
        blocked("the pinned OpenRTI archive is not beside the FOM modules")
    pin = packaged_pins()["openrti-814a210.tar.gz"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin["sha256"]
    return path


def stubs(tmp_path: pathlib.Path, *, cmake_version: str, system: str, machine: str = "stubarch",
          compiler_line: str = "stub c++ 1.0") -> dict:
    """A PATH whose cmake, tar, uname and compiler are the recording stand-ins above, and the
    environment that steers them."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for name, body in (("cmake", STUB_CMAKE), ("tar", STUB_TAR), ("uname", STUB_UNAME),
                       ("stub-c++", STUB_COMPILER)):
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(stat.S_IRWXU)
    standard = "98" if system == "Darwin" else "14"
    return {"PATH": f"{bin_dir}:/usr/bin:/bin", "STUB_LOG": str(tmp_path / "commands.log"),
            "STUB_CMAKE_VERSION": cmake_version, "STUB_SYSTEM": system,
            "STUB_MACHINE": machine, "STUB_COMPILER_LINE": compiler_line,
            "STUB_COMPILER": str(bin_dir / "stub-c++"), "STUB_STANDARD": standard}


def recorded(log: pathlib.Path, build: str) -> list[list[str]]:
    commands = [block.split("\n") for block in log.read_text(encoding="utf-8").split("\n\n")
                if block]
    return [[word.replace(build, "B") for word in command] for command in commands]


def _host_is_the_reference_distribution() -> bool:
    """Whether the machine running the test is Ubuntu 24.04 (read here, by the test)."""
    try:
        lines = pathlib.Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return "ID=ubuntu" in lines and 'VERSION_ID="24.04"' in lines


DARWIN_EVIDENCE = "development evidence only (macOS: OpenRTI configured as C++98, NAT-02)"
REFERENCE_EVIDENCE = ("the reference configuration: Linux x86_64, Ubuntu 24.04, GCC 13, "
                      "CMake 3.28 to 3.31")


def dev_linux(machine: str) -> str:
    return (f"DEV-linux-{machine}: development evidence only (not the reference configuration: "
            "Linux x86_64, Ubuntu 24.04, GCC 13, CMake 3.28 to 3.31)")


#: (CMake version, uname -s, uname -m, the compiler's first line, the evidence line expected).
WRAPPER_CASES = [
    ("4.4.2", "Darwin", "arm64", CLANG, DARWIN_EVIDENCE),
    ("3.30.0", "Darwin", "arm64", CLANG, DARWIN_EVIDENCE),
    # CMake 4 is development use only (NAT-12), whatever else the machine is.
    ("4.0.0", "Linux", "x86_64", GCC13, dev_linux("x86_64")),
    # The reference configuration only on Ubuntu 24.04 itself (this test reads /etc/os-release).
    ("3.28.3", "Linux", "x86_64", GCC13,
     REFERENCE_EVIDENCE if _host_is_the_reference_distribution() else dev_linux("x86_64")),
    # CR-L21: the reference run's aarch64 VM, which the old line called the reference.
    ("3.28.3", "Linux", "aarch64", GCC13, dev_linux("aarch64")),
    ("3.31.9", "Linux", "x86_64", GCC14, dev_linux("x86_64")),
]


@case("G-R02", "G-R43", paragraphs=("SPEC:20", "SPEC:241"))
@pytest.mark.parametrize("cmake_version,system,machine,compiler_line,evidence", WRAPPER_CASES,
                         ids=["darwin-cmake4", "darwin-cmake3", "linux-x86_64-cmake4",
                              "linux-x86_64-gcc13", "linux-aarch64-gcc13", "linux-x86_64-gcc14"])
def test_the_openrti_wrapper_runs_the_bundles_commands_with_only_the_ruled_additions(
        tmp_path, cmake_version, system, machine, compiler_line, evidence):
    """R43, SPEC:20 (OpenRTI from the pinned commit's archive, a pinned baseline), NAT-12, NAT-13
    and NAT-02, with recording stand-ins for cmake, tar, uname and the compiler: the archive is
    checked against its pin and unpacked into the new build directory; configure is the bundle's
    command word for word, followed by -DCMAKE_POLICY_VERSION_MINIMUM=3.5 only when CMake reports
    4.0 or later, by the relocatable-install options with the platform's loader path, and on macOS
    only by -DCMAKE_CXX_STANDARD=98; build and install are the bundle's. The build record names
    the commands, the versions, the archive's digest and the variant, and says that a macOS build
    is development evidence. CR-L21: the record's evidence line names the reference
    configuration only on Linux x86_64 with Ubuntu 24.04, GCC 13 and CMake 3.28 to 3.31, and
    any other Linux build as development evidence of its machine (DEV-linux-<machine>); a fake
    uname, compiler and cmake on PATH steer the branch."""
    archive = openrti_archive()
    env = stubs(tmp_path, cmake_version=cmake_version, system=system, machine=machine,
                compiler_line=compiler_line)
    build = tmp_path / "openrti"
    result = subprocess.run(["/bin/bash", str(WRAPPER), str(archive), str(build)], env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    added = []
    if not cmake_version.startswith("3."):
        added.append("-DCMAKE_POLICY_VERSION_MINIMUM=3.5")
    loader = "@loader_path/../lib" if system == "Darwin" else "$ORIGIN/../lib"
    added += ["-DOPENRTI_INSTALL_WITH_RPATH=OFF", f"-DCMAKE_INSTALL_RPATH={loader}"]
    if system == "Darwin":
        added.append("-DCMAKE_CXX_STANDARD=98")
    assert recorded(tmp_path / "commands.log", str(build)) == [
        ["--version"],
        ["-xzf", str(archive), "-C", "B/source"],
        BUNDLE_CONFIGURE[1:] + added,
        BUNDLE_BUILD[1:],
        BUNDLE_INSTALL[1:],
    ]
    record = dict(line.split("=", 1) for line in
                  (build / "build-record.txt").read_text(encoding="utf-8").splitlines())
    pin = packaged_pins()["openrti-814a210.tar.gz"]
    assert record["archive_sha256"] == pin["sha256"]
    assert record["openrti_commit"] == "814a210978b7faafd65affbe70a2e25679921b23"
    assert record["cmake"] == f"cmake version {cmake_version}"
    assert record["compiler"] == f"{env['STUB_COMPILER']}: {compiler_line}"
    assert record["platform"] == f"{system} {machine}"
    assert record["evidence"] == evidence
    assert result.stdout.splitlines()[-1] == f"Evidence: {evidence}"
    assert record["policy_version_minimum_added"] == ("no" if cmake_version.startswith("3.")
                                                      else "yes")
    assert record["cxx_standard_in_cache"] == env["STUB_STANDARD"]
    assert record["configure"].split() == [w.replace("B/", f"{build}/") for w in
                                           BUNDLE_CONFIGURE] + [
        a.replace("$ORIGIN", "\\$ORIGIN") for a in added]
    if system == "Darwin":
        assert "This build is development evidence only (NAT-02, CR-L04);" in result.stdout


@case("G-R02", paragraphs=("SPEC:20",))
@pytest.mark.parametrize("problem", ["arguments", "relative", "exists", "no-archive",
                                     "other-archive"])
def test_the_openrti_wrapper_refuses_before_it_touches_anything(tmp_path, problem):
    """The wrapper keeps the bundle script's refusals (exit 2: wrong argument count, a relative
    or an existing build directory) and adds two: no archive at the given path, and an archive
    whose SHA-256 is not the pinned one. Nothing is unpacked or configured (the stand-in cmake
    and tar record no call)."""
    env = stubs(tmp_path, cmake_version="4.4.2", system="Darwin")
    other = tmp_path / "other.tar.gz"
    other.write_bytes(b"not the pinned archive")
    build = str(tmp_path / "openrti")
    arguments = {
        "arguments": [str(other)],
        "relative": [str(other), "relative/openrti"],
        "exists": [str(other), str(tmp_path)],
        "no-archive": [str(tmp_path / "missing.tar.gz"), build],
        "other-archive": [str(other), build],
    }[problem]
    result = subprocess.run(["/bin/bash", str(WRAPPER), *arguments], env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 2, result
    assert not (tmp_path / "commands.log").exists()
    assert not pathlib.Path(build).exists()
    assert result.stdout == ""
