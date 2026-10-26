"""D-08 and R40, read off the source: what each module of the package may touch.

Every module under `src/synapse_hla` is classified here, and a module nobody classified fails
`test_every_module_is_classified`: adding one is the moment to decide what it may do.

PURE modules read no clock, file, environment variable, socket, process or random source. The
check is on each module's own source, by AST: forbidden imports, forbidden builtins and the
attribute names through which a clock, the environment or a random source is reached from an
allowed import (`datetime.now`, `uuid.uuid4`). It cannot see through a call into another module
of the package, which is why the classification is per module and closed.

FILE modules may open files; CLOCK_PROCESS modules may also read clocks and start or signal
processes (D-08 names capture, replay, host and cli, and the private helpers their rounds name).
No module of the package, pure or not, may use a socket - the native worker owns the RTI
connection - with one exception the round R8 brief makes: `_demo`, the demo's orchestration,
chooses rtinode's port and probes its readiness with raw TCP connects (R38, NAT-18), on
127.0.0.1 only (`test_only_the_demo_touches_a_socket_and_only_on_loopback`). And none may
evaluate code, run a shell, import dynamically or unpickle (R40).
"""

import ast
import pathlib

import pytest

import synapse_hla
from hla_support import case

SRC = pathlib.Path(synapse_hla.__file__).resolve().parent

#: D-08's pure modules present so far. Each round adds the pure modules it creates. `config`,
#: `_schema` and `projector` validate against packaged schemas, which `_resources` reads: pure is
#: a statement about each module's own source, as the module text says. `projector` also
#: constructs `synapse_cdm.models.Entity` and `_schema` builds the SDK's schema validator; that
#: neither opens a file, a socket or a process once the schemas are loaded is held at run time
#: by `test_hla_projector.py::test_projection_opens_nothing_once_warm` (an audit hook).
PURE = ("__init__", "errors", "limits", "codec", "geodesy", "canonical", "config", "_utc",
        "_schema", "projector", "_identity", "reducer", "_runfile", "_inspection", "_examples")
#: Round R6's pure helpers of the command line: `_runfile` builds run.json from what it is given
#: (the caller passes the audit times and the installed synapse-cdm version), `_inspection` counts
#: the lines the caller's verified reader hands it, `_examples` holds two configurations as bytes.
#: `reducer` (round R4) admits frames by `capture`'s line rules, logic only: that reduce_frame
#: opens nothing once warm is held at run time by
#: `test_hla_reducer.py::test_reduction_opens_nothing_once_warm` (an audit hook).
#: Modules that may touch files, with the reason.
FILE = {
    "capture": "verify_capture and the verified streaming reader read the capture file (D-08)",
    "_resources": "reads the package's own data files (schemas, pins.json) for the pure modules",
    "_fom": "reads the FOM modules from the directory a caller names, to check their pins",
    "replay": "reads the capture and writes the replay directory (D-08, R35)",
    "_writer": "creates the live run directory and writes and syncs the capture and the outputs "
               "for the host (R34, round R5)",
    "_selftest": "reads the packaged fixtures and the FOM modules of the directory the command "
                 "line names, and replays the packaged capture into the self-test directory "
                 "(OPS-26, round R6)",
}
#: Modules that may also read clocks and manage processes, with the reason (D-08).
CLOCK_PROCESS = {
    "host": "starts, signals and reaps the worker, reads its pipes, the clocks and the "
            "worker's RSS, and handles SIGINT and SIGTERM (round R5)",
    "cli": "the command line (round R6): reads argv and the environment variables of D-07, "
           "writes its output directories, forks the host and watches its RSS (OPS-23), reads "
           "the wall clock for observe's audit times, handles SIGINT and SIGTERM",
    "_demo": "the demo's orchestration (round R8): starts, signals and reaps rtinode and the "
             "synthetic publisher, reads the hosts' messages and run directories, the clocks "
             "for its bounds, and the random source for the federation names (R38)",
}
#: The modules that may use a socket, with the reason: the R8 brief's port choice and readiness
#: probe (R38, NAT-18).
SOCKET = {"_demo": "chooses rtinode's port and probes its readiness on 127.0.0.1"}

#: Import roots a pure module may not use: every way to a file, a clock, the environment, a
#: process, a socket, a random source, dynamic import or locale-dependent formatting.
PURE_FORBIDDEN_IMPORTS = {
    "os", "time", "socket", "subprocess", "random", "secrets", "pathlib", "io", "shutil",
    "tempfile", "glob", "fnmatch", "sys", "signal", "threading", "multiprocessing",
    "concurrent", "select", "selectors", "asyncio", "importlib", "ctypes", "fcntl", "resource",
    "mmap", "locale", "statistics", "platform", "getpass", "pwd", "grp", "sysconfig", "site",
    "zoneinfo", "logging", "warnings", "builtins",
}
#: Builtins a pure module may not call.
PURE_FORBIDDEN_CALLS = {"open", "input", "print", "breakpoint"}
#: Attribute names through which an allowed import reaches a clock, the environment or chance.
PURE_FORBIDDEN_ATTRIBUTES = {
    "now", "utcnow", "today", "fromtimestamp", "utcfromtimestamp", "timestamp", "astimezone",
    "uuid1", "uuid4", "environ", "getenv", "urandom", "getrandbits",
}

#: Import roots no module of the package may use.
EVERYWHERE_FORBIDDEN_IMPORTS = {
    "socket", "ssl", "socketserver", "http", "ftplib", "smtplib", "imaplib", "poplib",
    "telnetlib", "xmlrpc", "pickle", "marshal", "shelve", "dbm",
}
#: Dotted imports no module may use even where the root is allowed.
EVERYWHERE_FORBIDDEN_DOTTED = {"urllib.request", "importlib.import_module"}
#: Builtins no module may call.
EVERYWHERE_FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}


def modules() -> dict[str, pathlib.Path]:
    out = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).with_suffix("")
        out[".".join(rel.parts)] = path
    return out


def tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported(module: ast.Module) -> set[str]:
    """Every imported dotted name, including `from x import y` as `x.y` and `x`."""
    names = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names |= {f"{node.module}.{alias.name}" for alias in node.names}
    return names


def roots(names: set[str]) -> set[str]:
    return {n.split(".")[0] for n in names}


def called_names(module: ast.Module) -> set[str]:
    return {node.func.id for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def attribute_names(module: ast.Module) -> set[str]:
    names = {node.attr for node in ast.walk(module) if isinstance(node, ast.Attribute)}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.name for alias in node.names}
    return names


def shell_true(module: ast.Module) -> bool:
    return any(isinstance(node, ast.keyword) and node.arg == "shell"
               and not (isinstance(node.value, ast.Constant) and node.value.value is False)
               for node in ast.walk(module))


def test_every_module_is_classified():
    found = set(modules())
    classified = set(PURE) | set(FILE) | set(CLOCK_PROCESS)
    assert found == classified, {"unclassified": sorted(found - classified),
                                 "missing": sorted(classified - found)}
    assert not (set(PURE) & (set(FILE) | set(CLOCK_PROCESS)))


@pytest.mark.parametrize("name", PURE)
def test_a_pure_module_reaches_no_file_clock_environment_process_socket_or_chance(name):
    module = tree(modules()[name])
    bad_imports = roots(imported(module)) & PURE_FORBIDDEN_IMPORTS
    bad_calls = called_names(module) & PURE_FORBIDDEN_CALLS
    bad_attributes = attribute_names(module) & PURE_FORBIDDEN_ATTRIBUTES
    assert not (bad_imports or bad_calls or bad_attributes), {
        "imports": sorted(bad_imports), "calls": sorted(bad_calls),
        "attributes": sorted(bad_attributes)}


#: What only CLOCK_PROCESS modules may import: clocks, timers, signals, threads and processes,
#: and chance (D-08: clocks and processes are the host's and the command line's alone). A FILE
#: module such as `replay` reads files and nothing that would make two runs differ (R35).
CLOCK_PROCESS_IMPORTS = {
    "time", "signal", "subprocess", "threading", "multiprocessing", "concurrent", "asyncio",
    "sched", "random", "secrets", "select", "selectors", "resource", "zoneinfo", "locale",
}


@pytest.mark.parametrize("name", sorted(FILE))
def test_a_file_module_reads_no_clock_environment_or_chance_and_starts_no_process(name):
    module = tree(modules()[name])
    bad_imports = roots(imported(module)) & CLOCK_PROCESS_IMPORTS
    bad_attributes = attribute_names(module) & PURE_FORBIDDEN_ATTRIBUTES
    assert not (bad_imports or bad_attributes), {"imports": sorted(bad_imports),
                                                 "attributes": sorted(bad_attributes)}


@pytest.mark.parametrize("source", ["import time\n", "from time import monotonic_ns\n",
                                    "import subprocess\n", "import random\n",
                                    "import os\nx = os.environ\n",
                                    "from datetime import datetime\nx = datetime.now()\n"])
def test_the_file_module_rule_fires_on_a_violation(source):
    module = ast.parse(source)
    assert (roots(imported(module)) & CLOCK_PROCESS_IMPORTS) or (
        attribute_names(module) & PURE_FORBIDDEN_ATTRIBUTES)


@pytest.mark.parametrize("name", sorted(modules()))
@case("G-R40", "G-R03")
def test_no_module_uses_a_socket_evaluates_code_runs_a_shell_or_unpickles(name):
    module = tree(modules()[name])
    names = imported(module)
    if name in SOCKET:
        names = {n for n in names if n != "socket"}
    bad = sorted((roots(names) & EVERYWHERE_FORBIDDEN_IMPORTS)
                 | (names & EVERYWHERE_FORBIDDEN_DOTTED)
                 | (called_names(module) & EVERYWHERE_FORBIDDEN_CALLS)
                 | ({"import_module"} & attribute_names(module)))
    assert not bad, bad
    assert not shell_true(module), "a call passes shell=..."


def test_only_the_demo_touches_a_socket_and_only_on_loopback():
    """The exception of SOCKET, held to its letter: `_demo` imports `socket` and nothing else of
    the network; it calls exactly `socket.socket` (an IPv4 stream socket, bound to
    (LOOPBACK, 0) to learn a free port) and `socket.create_connection` (the readiness probe, to
    (LOOPBACK, port)), with LOOPBACK the constant "127.0.0.1"; every bind and connect names
    LOOPBACK. The `rti` tests run the demo under an audit hook that refuses any other address."""
    module = tree(modules()["_demo"])
    assert {n for n in imported(module) if n.split(".")[0] in EVERYWHERE_FORBIDDEN_IMPORTS} \
        == {"socket"}
    calls = sorted(ast.unparse(node.func) for node in ast.walk(module)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and isinstance(node.func.value, ast.Name) and node.func.value.id == "socket")
    assert calls == ["socket.create_connection", "socket.socket"]
    addresses = [ast.unparse(node.args[0]) for node in ast.walk(module)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in ("bind", "create_connection")]
    assert addresses == ["(LOOPBACK, 0)", "(LOOPBACK, port)"]
    assignments = [node for node in ast.walk(module) if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "LOOPBACK" for t in node.targets)]
    assert [ast.literal_eval(node.value) for node in assignments] == ["127.0.0.1"]


@pytest.mark.parametrize("name", sorted(modules()))
def test_no_module_imports_a_sibling_distribution(name):
    """R44: decoding is not borrowed from the DIS7 or KML work, nor from any other synapse_*."""
    others = {r for r in roots(imported(tree(modules()[name])))
              if r.startswith("synapse_") and r not in ("synapse_hla", "synapse_cdm")}
    assert not others, sorted(others)


# The checker checked: each rule above must fire on a module that breaks it, or a green run
# would say nothing.
VIOLATIONS = (
    ("import os\n", "imports"),
    ("from time import monotonic\n", "imports"),
    ("import pathlib\n", "imports"),
    ("import datetime\nx = datetime.datetime.now()\n", "attributes"),
    ("from datetime import datetime\nx = datetime.utcnow()\n", "attributes"),
    ("import uuid\nx = uuid.uuid4()\n", "attributes"),
    ("from uuid import uuid4\n", "attributes"),
    ("x = open('f')\n", "calls"),
    ("print('x')\n", "calls"),
    ("import importlib.resources\n", "imports"),
)


@pytest.mark.parametrize("source,rule", VIOLATIONS, ids=[v[0].split("\n")[0] for v in VIOLATIONS])
def test_the_pure_rules_fire_on_a_violation(source, rule):
    module = ast.parse(source)
    found = {"imports": roots(imported(module)) & PURE_FORBIDDEN_IMPORTS,
             "calls": called_names(module) & PURE_FORBIDDEN_CALLS,
             "attributes": attribute_names(module) & PURE_FORBIDDEN_ATTRIBUTES}
    assert found[rule]


EVERYWHERE_VIOLATIONS = (
    "import socket\n",
    "from socket import create_connection\n",
    "import urllib.request\n",
    "from urllib.request import urlopen\n",
    "import pickle\n",
    "x = eval('1')\n",
    "exec('x = 1')\n",
    "import importlib\nm = importlib.import_module('x')\n",
    "import subprocess\nsubprocess.run('ls', shell=True)\n",
)


@pytest.mark.parametrize("source", EVERYWHERE_VIOLATIONS)
def test_the_package_wide_rules_fire_on_a_violation(source):
    module = ast.parse(source)
    names = imported(module)
    hit = ((roots(names) & EVERYWHERE_FORBIDDEN_IMPORTS) or (names & EVERYWHERE_FORBIDDEN_DOTTED)
           or (called_names(module) & EVERYWHERE_FORBIDDEN_CALLS)
           or ({"import_module"} & attribute_names(module)) or shell_true(module))
    assert hit


def test_the_allowed_pure_imports_pass():
    """The rules do not refuse what pure modules legitimately use."""
    source = ("import hashlib, json, math, re, struct, uuid\nfrom datetime import datetime\n"
              "from dataclasses import dataclass\nx = uuid.uuid5(uuid.NAMESPACE_URL, 'a')\n"
              "y = datetime.strptime('2026', '%Y')\n")
    module = ast.parse(source)
    assert not roots(imported(module)) & PURE_FORBIDDEN_IMPORTS
    assert not attribute_names(module) & PURE_FORBIDDEN_ATTRIBUTES
