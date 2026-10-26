"""The guards of a command-line child process (round R6): no socket, and no write outside one root.

A test runs `synapse-hla` as a child with this directory first on PYTHONPATH, so Python imports
this file as `sitecustomize` at start-up, before the command runs a line. It installs the socket
guard of D-10 (the same file `tests/sockguard/sitecustomize.py`, loaded by its path, so the two
cannot disagree) - except for the `rti` group's demo runs (round R8), which set
`SC_HLA_SOCKETS=loopback`: the demo chooses a port and probes rtinode's readiness on 127.0.0.1
(NAT-18), so there an audit hook refuses every bind and connect to any other address instead, and
appends every address it sees to `SC_HLA_SOCKET_LOG` for the test to read. And, when
`SC_HLA_WRITE_ROOT` names a directory, an audit hook that refuses
every attempt to create, write, rename, remove or change a file outside that directory: brief
criterion 4 of round R6, "no command writes outside its --out directory", held in every child the
CLI tests start. A refused attempt raises `WriteGuardError` inside the command (a defect there:
exit 1 with a traceback the test sees) and is also appended to `SC_HLA_WRITE_LOG`, which the
test reads afterwards, so that even a refusal the command swallowed would be seen.

What the hook can see: `open` (Python's and `os.open`) with its flags, and the `os.*` events of
mkdir, rename, replace, remove, rmdir, symlink, link, chmod, chown, truncate and utime. `os.open`
relative to a directory descriptor reports only the relative name; such names are allowed when
they hold no separator (the product creates its fixed names that way inside its own --out), and
the test checks afterwards that nothing appeared outside the expected directories.
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_sc_hla_sockguard", os.path.join(os.path.dirname(_HERE), "sockguard", "sitecustomize.py"))
_sockguard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sockguard)


class LoopbackGuardError(RuntimeError):
    """A demo child tried to bind or connect a socket to an address other than 127.0.0.1."""


def _loopback(event, args):
    if event not in ("socket.bind", "socket.connect"):
        return
    address = args[1]
    log = os.environ.get("SC_HLA_SOCKET_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(f"{event} {address!r}\n")
    if not (isinstance(address, tuple) and address[:1] == ("127.0.0.1",)):
        raise LoopbackGuardError(f"{event} to {address!r} outside 127.0.0.1")


if os.environ.get("SC_HLA_SOCKETS") == "loopback":
    sys.addaudithook(_loopback)
else:
    _sockguard.install()

_ROOT = os.environ.get("SC_HLA_WRITE_ROOT")
_LOG = os.environ.get("SC_HLA_WRITE_LOG")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_ALLOWED_DEVICES = ("/dev/null",)
_PATH_EVENTS = {"os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir", "os.symlink",
                "os.link", "os.chmod", "os.chown", "os.truncate", "os.utime"}


class WriteGuardError(RuntimeError):
    """A command-line child tried to write outside the test's directory."""


def _text(path):
    if isinstance(path, bytes):
        return os.fsdecode(path)
    return path


def _inside(path) -> bool:
    if isinstance(path, int):
        return True
    text = _text(path)
    if not isinstance(text, str):
        return True
    if not os.path.isabs(text):
        if os.sep not in text:
            # A fixed name relative to a directory descriptor (or to the working directory,
            # which the test keeps empty and checks).
            return True
        text = os.path.join(os.getcwd(), text)
    real = os.path.realpath(text)
    if real in _ALLOWED_DEVICES:
        return True
    return real == _ROOT or real.startswith(_ROOT + os.sep)


_busy = []


def _hook(event, args):
    if _busy:
        return
    paths = ()
    if event == "open":
        path, _mode, flags = args
        if isinstance(flags, int) and flags & _WRITE_FLAGS:
            paths = (path,)
        elif isinstance(_mode, str) and any(c in _mode for c in "wax+"):
            paths = (path,)
    elif event in _PATH_EVENTS:
        paths = tuple(a for a in args[:2] if isinstance(a, (str, bytes)))
    for path in paths:
        if not _inside(path):
            _busy.append(1)
            try:
                if _LOG:
                    with open(_LOG, "a", encoding="utf-8") as log:
                        log.write(f"{event} {_text(path)!r}\n")
            finally:
                _busy.pop()
            raise WriteGuardError(f"write outside the test directory: {event} {_text(path)!r}")


if _ROOT:
    _ROOT = os.path.realpath(_ROOT)
    sys.addaudithook(_hook)
