"""§41: the package makes NO network call, proved twice — statically and by taking sockets away.

WHY TWO PROOFS AND NOT ONE
--------------------------
The static half sweeps every module under `synapse_cdm` for an import of a networking module. It
is cheap, it is total, and it is the one that catches the change: a call cannot appear without an
import, and an import is visible in the syntax tree whether it sits at module level or inside a
function body (`ast.walk`, the same reading `tests/test_cdm_boundary.py` takes of `hashlib`).

The static half alone would still be a claim about spelling. So the dynamic half REMOVES the
capability — `socket.socket` is replaced with something that raises — and runs the conformance
suite over the whole roster underneath it. Fourteen adapters translate every fixture they ship,
the fifteen checks run, and the sweep exits 0 with no socket in the process able to be opened.

WHAT IS DELIBERATELY NOT ASSERTED
---------------------------------
That no DEPENDENCY opens a socket. `pydantic` is a dependency and this test does not audit it.
The claim §41 makes and SECURITY.md publishes is about this package's own code, and a test whose
name promised more than it checked would be worse than one that checks less.
"""
import ast
import pathlib
import socket

import pytest

import synapse_cdm
from synapse_cdm import suite
from synapse_cdm.adapter import discover, roster

PACKAGE = pathlib.Path(synapse_cdm.__file__).parent
SOURCES = sorted(PACKAGE.rglob("*.py"))

#: Every stdlib and third-party root that could reach the network. `ssl` is here AND in
#: `tests/test_cdm_boundary.py`'s `FORBIDDEN_CRYPTO`, which is not duplication: there it is
#: forbidden because it is a crypto primitive in the translation layer, here because a TLS socket
#: is a socket. Two rules can forbid one name for two reasons and both should keep saying so.
NETWORKING = {"socket", "socketserver", "ssl", "urllib", "urllib2", "urllib3", "http",
              "httplib", "ftplib", "telnetlib", "smtplib", "poplib", "imaplib", "xmlrpc",
              "asyncio", "requests", "httpx", "aiohttp", "websockets", "grpc", "boto3",
              "paramiko", "pycurl"}


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_sweep_found_the_package():
    """A sweep over an empty file list passes and proves nothing."""
    assert len(SOURCES) >= 10, f"expected the CDM package, found {len(SOURCES)} modules"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_module_imports_a_networking_module(path):
    """§41, statically. The failure names the module and the import, because that is the repair."""
    found = sorted(_imported_roots(path) & NETWORKING)
    assert not found, (
        f"{path.name} imports {found}. §41: the package makes NO network call — no telemetry, no "
        "licence check, no remote registry, no update ping — and SECURITY.md publishes that as a "
        "statement a consumer may rely on. An adapter that needs data from a network takes it as "
        "a payload from its caller, who is the one entitled to decide what to connect to")


def test_the_static_sweep_can_fail(tmp_path):
    """The mutation. A sweep that could not fail would be prose with a green tick beside it."""
    planted = tmp_path / "planted.py"
    planted.write_text("def fetch():\n    import urllib.request\n    return urllib.request\n")
    assert sorted(_imported_roots(planted) & NETWORKING) == ["urllib"]


def test_the_whole_roster_conforms_with_no_socket_available(monkeypatch, capsys):
    """§41, dynamically: take the capability away and run the suite over every adapter.

    `socket.socket` is the constructor every higher-level client in the standard library reaches
    for eventually, so replacing it removes the capability rather than one spelling of it. The
    sweep is the same required set CI uses, and the assertion is on the EXIT STATUS: a check that
    silently degraded to SKIP without a socket would still be a check nobody could rely on.
    """
    discover()                      # before the sockets go, since import is not the subject

    def refuse(*args, **kwargs):
        raise AssertionError("synapse_cdm opened a socket; §41 says it makes no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    # The SHIPPED adapters, not `roster()`: every `Adapter` subclass registers itself, so in a
    # full run the registry also holds the doubles four other modules define, and a sweep over
    # those would depend on pytest's import order.
    names = sorted(name for name, cls in roster().items()
                   if cls.__module__.startswith("synapse_cdm.adapters."))
    assert len(names) == 14, names
    for name in names:
        assert suite.main(["conformance", "run", "--adapter", name,
                           "--require", "A,B,C,D,F,G,H,J,K,L,O"]) == suite.EXIT_OK, name
    capsys.readouterr()


def test_taking_the_socket_away_is_a_real_deprivation(monkeypatch):
    """The mutation for the dynamic half: with the patch installed, a socket cannot be made."""
    def refuse(*args, **kwargs):
        raise AssertionError("no sockets here")

    monkeypatch.setattr(socket, "socket", refuse)
    with pytest.raises(AssertionError, match="no sockets here"):
        socket.socket()
