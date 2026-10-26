"""The socket guard of the offline test group (D-10), for child processes and for conftest.

A child interpreter started by a test gets this directory first on PYTHONPATH
(`hla_support.run_python` does that), so Python's start-up imports this file as `sitecustomize`
and the guard is in place before the child runs a line of its own. `conftest.py` imports the same
file under another name and applies the same refusals to the test process through `monkeypatch`,
so there is one list of guarded functions and one refusal, not two copies that could drift.

The refusal is a `RuntimeError` subclass and deliberately not an `OSError`: code that handles a
network failure (an `OSError`) must not be able to mistake the guard for one, retry, and pass.

`socket.socket` is a class that the standard library subclasses at import time (`ssl.SSLSocket`,
imported by `asyncio`, which pdb and therefore pytest import). Its replacement is therefore a
subclass of the real class whose constructor refuses, not a function: a function in its place
breaks `class SSLSocket(socket)` before any test runs. The refusal comes before the real
constructor, so no file descriptor is ever created.
"""

import socket

#: The functions refused. The first four are D-10's list; the resolver functions are added because
#: a name lookup is network traffic even when no connection follows it.
GUARDED = (
    "socket",
    "create_connection",
    "getaddrinfo",
    "socketpair",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
    "getnameinfo",
)

_REAL_SOCKET = socket.socket


class SocketGuardError(RuntimeError):
    """Raised by every guarded socket function while the offline guard is active."""


class GuardedSocket(_REAL_SOCKET):
    """Stands in for `socket.socket`: subclassable like it, impossible to construct."""

    def __init__(self, *args, **kwargs):
        raise SocketGuardError("offline test group: socket.socket is refused")


def refusal(name):
    """The object that replaces `socket.<name>` while the guard is active."""
    if name == "socket":
        return GuardedSocket

    def refuse(*args, **kwargs):
        raise SocketGuardError(f"offline test group: socket.{name} is refused")

    refuse.__name__ = f"refused_{name}"
    return refuse


def install():
    for name in GUARDED:
        setattr(socket, name, refusal(name))


if __name__ == "sitecustomize":
    install()
