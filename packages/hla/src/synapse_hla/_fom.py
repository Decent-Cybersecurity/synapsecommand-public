"""The dependency checks: the five RPR FOM modules against their pins, and what XML they may hold.

WHERE THE MODULES COME FROM
---------------------------
The modules are not in the package (OPV-03, OPS-11 as corrected): a caller names the directory
that holds them (the command line reads `SYNAPSE_HLA_FOM_DIR`; this module reads no environment),
and every module is checked against the packaged `pins.json` before anything else looks at it:
it must be a regular file of exactly the pinned size, read in full, with the pinned SHA-256.
Missing, unreadable, of another kind, of another size or of other bytes is E_DEPENDENCY_PIN with
the module's file name as the path (CR-L01). The size is compared before the file is read, so a
module replaced by something huge is refused without reading it (SPEC:233).

WHAT XML A MODULE MAY HOLD (R40, OPS-12)
----------------------------------------
Only after the pins hold is a module parsed, by expat, and the parse refuses on the first sight
of anything that could make an XML processor reach outside the file or expand without bound: a
document type declaration (and so any entity or other markup declaration), a reference to an
entity other than the five predefined ones, the XInclude namespace, a processing instruction
other than the XML declaration, more than 2 MiB, and elements nested deeper than 64. Each refusal
is E_DEPENDENCY_PIN. `xsi:schemaLocation` is allowed, because every pinned module carries one,
and it is an attribute like any other: nothing here fetches, resolves or opens anything it names.
The pinned modules can only fail here if the pins were wrong; the scan exists for the order of
R40 ("parse only pinned local FOM files") and for the day a pin is changed.

A module is UTF-8, as all five pinned ones declare: bytes that are not UTF-8, a NUL byte (which no
XML document holds, and which would let expat guess UTF-16 from the first characters) and an XML
declaration naming any other encoding are refused like the constructs above. Expat is told the
encoding instead of reading it from the file, because for a name it does not know itself it asks
Python's codec registry, which raises lookup and decoding errors of its own and answers
differently from one interpreter to the next; the scanner's verdict must not depend on either.

HEADER PINS (RED-V-03)
----------------------
A capture header records the whole packaged pin map, nine files by name and digest, whether or
not this run hashed all of them (the four that are not FOM modules are recorded, not re-hashed;
OPS-11). Replay compares a header's map with the packaged one for exact equality.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from xml.parsers import expat

from synapse_hla import _resources, errors
from synapse_hla.errors import HlaError
from synapse_hla.limits import V1, Limits

#: The five modules in the order R04 prescribes.
FOM_MODULES = (
    "RPR-Foundation_v2.0.xml",
    "RPR-Enumerations_v2.0.xml",
    "RPR-Base_v2.0.xml",
    "RPR-Physical_v2.0.xml",
    "RPR-Switches_v2.0.xml",
)

#: The namespace of XInclude 1.0, and the one its drafts used.
XINCLUDE_NAMESPACES = ("http://www.w3.org/2001/XInclude", "http://www.w3.org/2003/XInclude")

_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


@dataclass(frozen=True)
class Pin:
    """One entry of the packaged pins.json."""

    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class FomModule:
    """A module that passed its pin and the XML scan: its name, where it is, its digest."""

    name: str
    path: str
    sha256: str
    size: int


def packaged_pins() -> tuple[Pin, ...]:
    """The `files` of the packaged pins.json, in its order."""
    document = _resources.package_json("", _resources.PINS)
    return tuple(Pin(entry["path"], entry["sha256"], entry["bytes"])
                 for entry in document["files"])


def header_pins() -> dict[str, str]:
    """The pin map a capture header records: every packaged pin as {file name: sha256}."""
    return {pin.path: pin.sha256 for pin in packaged_pins()}


def check_header_pins(pins) -> None:
    """RED-V-03: a header's pin map must equal the packaged one, entry for entry.

    A missing or different entry is E_DEPENDENCY_PIN with that file's name as the path; an extra
    entry is refused under its own (made safe) name. Entries are examined in the packaged order,
    then the extra ones in sorted order, so the same map always gets the same answer.
    """
    if type(pins) is not dict:
        raise TypeError("a pin map is a dict")
    if any(type(name) is not str for name in pins):
        raise TypeError("the names of a pin map are str")
    expected = header_pins()
    for name, digest in expected.items():
        if name not in pins:
            raise HlaError(errors.E_DEPENDENCY_PIN, name, "the capture does not record this pin")
        if pins[name] != digest:
            raise HlaError(errors.E_DEPENDENCY_PIN, name,
                           "the capture records another digest for this pinned file")
    for name in sorted(n for n in pins if n not in expected):
        raise HlaError(errors.E_DEPENDENCY_PIN, errors.safe_text(name),
                       "the capture records a pin this build does not have")


def _read_pinned(path: str, pin: Pin) -> bytes:
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except OSError:
        raise HlaError(errors.E_DEPENDENCY_PIN, pin.path,
                       "the FOM module is missing or cannot be opened") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise HlaError(errors.E_DEPENDENCY_PIN, pin.path,
                           "the FOM module is not a regular file")
        if info.st_size != pin.size:
            raise HlaError(errors.E_DEPENDENCY_PIN, pin.path,
                           "the FOM module does not have its pinned size")
        chunks = []
        remaining = pin.size + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise HlaError(errors.E_DEPENDENCY_PIN, pin.path, "the FOM module cannot be read") from None
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) != pin.size:
        raise HlaError(errors.E_DEPENDENCY_PIN, pin.path,
                       "the FOM module changed size while it was read")
    return data


def check_fom_modules(fom_dir, *, limits: Limits = V1) -> tuple[FomModule, ...]:
    """The five modules in `fom_dir`, each pinned and then scanned; E_DEPENDENCY_PIN otherwise.

    All five are checked against their pins first, in R04 order, and only then scanned, so the
    scanner never sees bytes that are not the pinned ones. An empty directory name is refused
    rather than read as the current directory, and a name no directory can have (a NUL byte, or a
    lone surrogate the file-system encoding cannot write) is refused before anything is opened.
    `limits` is the OPS-21 seam (tests only).
    """
    root = os.fspath(fom_dir)
    if type(root) is not str:
        raise TypeError("the FOM directory is a str path")
    if not root:
        raise HlaError(errors.E_DEPENDENCY_PIN, FOM_MODULES[0], "no FOM directory was given")
    try:
        nameable = b"\x00" not in os.fsencode(root)
    except UnicodeEncodeError:
        nameable = False
    if not nameable:
        raise HlaError(errors.E_DEPENDENCY_PIN, FOM_MODULES[0],
                       "the FOM directory name cannot name a directory")
    pins = {pin.path: pin for pin in packaged_pins()}
    loaded = []
    for name in FOM_MODULES:
        pin = pins[name]
        path = os.path.join(root, name)
        data = _read_pinned(path, pin)
        if hashlib.sha256(data).hexdigest() != pin.sha256:
            raise HlaError(errors.E_DEPENDENCY_PIN, name,
                           "the FOM module does not have its pinned SHA-256")
        loaded.append((name, path, data))
    for name, _path, data in loaded:
        scan_fom_xml(name, data, limits=limits)
    return tuple(FomModule(name, path, pins[name].sha256, len(data))
                 for name, path, data in loaded)


class _Refusal(Exception):
    """Raised inside an expat handler to stop the parse at the construct it refuses."""


def _refuse(message: str):
    def handler(*_args):
        raise _Refusal(message)
    return handler


#: The one encoding a module may have, as expat and the XML declaration spell it.
_ENCODING = "UTF-8"


def _declaration(_version, encoding, _standalone):
    # XML compares encoding names without regard to case. Expat admits only ASCII letters,
    # digits, ".", "_" and "-" in the name (anything else is a malformed declaration, refused as
    # such), so this is a plain ASCII case fold.
    if encoding is not None and encoding.upper() != _ENCODING:
        raise _Refusal("the FOM module declares an encoding other than UTF-8")


def scan_fom_xml(name: str, data: bytes, *, limits: Limits = V1) -> None:
    """Refuse (E_DEPENDENCY_PIN, path `name`) any XML construct R40 and OPS-12 forbid.

    See the module text. Nothing is resolved or fetched: the parser is told never to read
    parameter entities or an external DTD, and every handler that could see a declaration, an
    external entity or an XInclude stops the parse instead.
    """
    if type(data) is not bytes:
        raise TypeError("a FOM module is bytes")
    where = errors.safe_text(name)
    if len(data) > limits.dependency_xml_bytes:
        raise HlaError(errors.E_DEPENDENCY_PIN, where,
                       "the FOM module is larger than the dependency XML size limit")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise HlaError(errors.E_DEPENDENCY_PIN, where, "the FOM module is not UTF-8") from None
    if b"\x00" in data:
        raise HlaError(errors.E_DEPENDENCY_PIN, where,
                       "the FOM module holds U+0000, which no XML document holds")
    # Told the encoding, expat never consults Python's codec registry, whatever the file
    # declares; the declaration is then checked by `_declaration` and refused unless it agrees.
    parser = expat.ParserCreate(encoding=_ENCODING, namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.XmlDeclHandler = _declaration
    parser.StartDoctypeDeclHandler = _refuse("the FOM module has a document type declaration")
    parser.EntityDeclHandler = _refuse("the FOM module declares an entity")
    parser.UnparsedEntityDeclHandler = _refuse("the FOM module declares an entity")
    parser.NotationDeclHandler = _refuse("the FOM module declares a notation")
    parser.ElementDeclHandler = _refuse("the FOM module declares an element type")
    parser.AttlistDeclHandler = _refuse("the FOM module declares attributes")
    parser.ExternalEntityRefHandler = _refuse("the FOM module refers to an external entity")
    parser.SkippedEntityHandler = _refuse("the FOM module refers to an undeclared entity")
    parser.ProcessingInstructionHandler = _refuse(
        "the FOM module has a processing instruction other than the XML declaration")
    depth = 0

    def namespace(_prefix, uri):
        if uri in XINCLUDE_NAMESPACES:
            raise _Refusal("the FOM module uses the XInclude namespace")

    def start(element, _attributes):
        nonlocal depth
        depth += 1
        if depth > limits.dependency_xml_depth:
            raise _Refusal("the FOM module nests elements deeper than the dependency XML limit")
        if element.split(" ", 1)[0] in XINCLUDE_NAMESPACES:
            raise _Refusal("the FOM module uses the XInclude namespace")

    def end(_element):
        nonlocal depth
        depth -= 1

    parser.StartNamespaceDeclHandler = namespace
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except _Refusal as refusal:
        raise HlaError(errors.E_DEPENDENCY_PIN, where, str(refusal)) from None
    except expat.ExpatError:
        raise HlaError(errors.E_DEPENDENCY_PIN, where,
                       "the FOM module is not well-formed XML of the allowed kind") from None
