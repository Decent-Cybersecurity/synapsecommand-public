"""The dependency checks: the five FOM modules against their pins, the XML scan, the header pins.

The modules come from the directory `SYNAPSE_HLA_FOM_DIR` names, through the tests' one resolver
(`hla_support.fom_modules`, D-07): absent is BLOCKED, present with other bytes fails. Every test
that changes a module works on a temporary copy. The XML refusals are crafted files, one per
construct OPS-12 names, handed to the scanner directly: a changed module fails its pin before
the scanner could see it, so the scanner is reachable only that way (OPS-12).
"""

import dataclasses
import io
import os
import random
import shutil
import socket
import xml.etree.ElementTree as ElementTree

import pytest

from hla_support import (
    FOM_MODULE_ORDER, case, fixture_capture_records, fom_modules, packaged_pins,
)
from sockguard import sitecustomize as sockguard
from synapse_hla import HlaError, _fom, errors
from synapse_hla.limits import V1

R = "\N{REPLACEMENT CHARACTER}"
U_UMLAUT = "\N{LATIN SMALL LETTER U WITH DIAERESIS}"


@pytest.fixture
def fom_copy(tmp_path):
    """A writable copy of the five pinned modules, taken through the D-07 resolver."""
    target = tmp_path / "fom"
    target.mkdir()
    for path in fom_modules():
        shutil.copyfile(path, target / path.name)
    return target


def dependency_refusal(call, *args, **kwargs) -> HlaError:
    with pytest.raises(HlaError) as info:
        call(*args, **kwargs)
    assert type(info.value) is HlaError and info.value.code == errors.E_DEPENDENCY_PIN
    return info.value


# ============================================================================ the pinned modules

@case("G-R15")
def test_the_five_pinned_modules_pass_in_r04_order(fom_copy, monkeypatch):
    scanned = []
    real_scan = _fom.scan_fom_xml
    def recording_scan(name, data, **kw):
        scanned.append(name)
        return real_scan(name, data, **kw)

    monkeypatch.setattr(_fom, "scan_fom_xml", recording_scan)
    modules = _fom.check_fom_modules(fom_copy)
    pins = packaged_pins()
    assert [m.name for m in modules] == list(FOM_MODULE_ORDER) == [
        "RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml", "RPR-Base_v2.0.xml",
        "RPR-Physical_v2.0.xml", "RPR-Switches_v2.0.xml"]
    for module in modules:
        assert (module.sha256, module.size) == (pins[module.name]["sha256"],
                                                 pins[module.name]["bytes"])
        assert module.path == os.path.join(str(fom_copy), module.name)
    assert scanned == list(FOM_MODULE_ORDER)


@case("A-DEPENDENCY")
@pytest.mark.parametrize("name", FOM_MODULE_ORDER)
def test_one_changed_byte_in_a_local_fom_module(fom_copy, name, monkeypatch):
    """A-DEPENDENCY: one byte of one module flipped in a copy of the five; E_DEPENDENCY_PIN with
    that module's name, before anything else happens: no XML scan of any module, no socket."""
    path = fom_copy / name
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    activity = []
    monkeypatch.setattr(_fom, "scan_fom_xml", lambda *a, **k: activity.append("scan"))
    for function in sockguard.GUARDED:
        monkeypatch.setattr(socket, function, lambda *a, _f=function, **k: activity.append(_f))
    assert dependency_refusal(_fom.check_fom_modules, fom_copy).path == name
    assert activity == []


@case("A-DEPENDENCY")
def test_every_way_a_module_can_be_wrong_is_e_dependency_pin(fom_copy):
    """OPS-11: missing, unreadable, of another kind, of another size; the first wrong module in
    R04 order is the one named."""
    base, physical = fom_copy / "RPR-Base_v2.0.xml", fom_copy / "RPR-Physical_v2.0.xml"
    physical.write_bytes(physical.read_bytes() + b" ")
    assert dependency_refusal(_fom.check_fom_modules, fom_copy).path == "RPR-Physical_v2.0.xml"
    base.unlink()
    assert dependency_refusal(_fom.check_fom_modules, fom_copy).path == "RPR-Base_v2.0.xml"
    base.mkdir()
    assert dependency_refusal(_fom.check_fom_modules, fom_copy).path == "RPR-Base_v2.0.xml"
    base.rmdir()
    os.mkfifo(base)
    assert dependency_refusal(_fom.check_fom_modules, fom_copy).path == "RPR-Base_v2.0.xml"
    base.unlink()
    switches = fom_copy / "RPR-Switches_v2.0.xml"
    base.symlink_to(switches)
    assert dependency_refusal(_fom.check_fom_modules, fom_copy).path == "RPR-Base_v2.0.xml"


@case("A-DEPENDENCY")
def test_a_module_of_another_size_is_refused_without_being_read(fom_copy, monkeypatch):
    """SPEC:233, check size before allocation: a module whose size differs from its pin is
    refused on its size alone; not one byte of it is read (a replaced module may be huge)."""
    switches = fom_copy / "RPR-Switches_v2.0.xml"
    switches.write_bytes(switches.read_bytes() + b"\n" * 4096)
    reads = []
    real_read = os.read

    def counting_read(fd, size):
        data = real_read(fd, size)
        reads.append(len(data))
        return data

    monkeypatch.setattr(_fom.os, "read", counting_read)
    assert dependency_refusal(_fom.check_fom_modules, fom_copy).path == "RPR-Switches_v2.0.xml"
    pins = packaged_pins()
    read_before = sum(pins[name]["bytes"] for name in FOM_MODULE_ORDER[:4])
    assert sum(reads) == read_before


def test_a_module_reached_through_a_symlink_is_judged_by_its_bytes(fom_copy, tmp_path):
    elsewhere = tmp_path / "elsewhere.xml"
    (fom_copy / "RPR-Base_v2.0.xml").rename(elsewhere)
    (fom_copy / "RPR-Base_v2.0.xml").symlink_to(elsewhere)
    assert len(_fom.check_fom_modules(fom_copy)) == 5


@pytest.mark.parametrize("directory", [
    "", "absent", "with\x00nul", chr(0xD800), "fom" + chr(0xDFFF), "n" * 5000,
], ids=["empty", "absent", "nul", "lone-high-surrogate", "lone-low-surrogate", "too-long"])
def test_no_directory_is_refused_under_the_first_modules_name(tmp_path, fom_copy, monkeypatch,
                                                              directory):
    """An empty name is never read as the current directory: the working directory holds the
    five valid modules here, and they are not found through it. A name no directory can have (a
    NUL byte, a lone surrogate the file-system encoding cannot write) and one too long for the
    file system are refused the same way, never with an interpreter exception."""
    monkeypatch.chdir(fom_copy)
    assert len(_fom.check_fom_modules(".")) == 5
    target = str(tmp_path / directory) if directory == "absent" else directory
    assert dependency_refusal(_fom.check_fom_modules, target).path == "RPR-Foundation_v2.0.xml"


@pytest.mark.parametrize("directory", [None, b"/tmp", 7])
def test_the_directory_must_be_a_str_path(directory):
    with pytest.raises(TypeError):
        _fom.check_fom_modules(directory)


# ===================================================================================== XML scan

#: One crafted document per construct OPS-12 refuses. None of them may lead to any read or fetch.
REFUSED_XML = [
    ("doctype-internal", b'<?xml version="1.0"?><!DOCTYPE objectModel [<!ELEMENT objectModel '
                         b'ANY>]><objectModel/>'),
    ("doctype-external", b'<!DOCTYPE objectModel SYSTEM "http://example.invalid/fom.dtd">'
                         b'<objectModel/>'),
    ("doctype-public", b'<!DOCTYPE x PUBLIC "-//X//DTD X//EN" "http://example.invalid/x.dtd"><x/>'),
    ("entity-expansion", b'<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
                         b'<lolz>&lol2;</lolz>'),
    ("external-entity", b'<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]><x>&ext;</x>'),
    ("parameter-entity", b'<!DOCTYPE x [<!ENTITY % p SYSTEM "http://example.invalid/p.dtd"> %p;]>'
                         b'<x/>'),
    ("undeclared-entity", b"<x>&foo;</x>"),
    ("undeclared-entity-in-attribute", b'<x a="&foo;"/>'),
    ("xinclude-prefixed", b'<x xmlns:xi="http://www.w3.org/2001/XInclude">'
                          b'<xi:include href="http://example.invalid/other.xml"/></x>'),
    ("xinclude-default", b'<include xmlns="http://www.w3.org/2001/XInclude" href="a.xml"/>'),
    ("xinclude-declared-unused", b'<x xmlns:xi="http://www.w3.org/2001/XInclude"/>'),
    ("xinclude-2003", b'<x xmlns:xi="http://www.w3.org/2003/XInclude"><xi:include href="a"/></x>'),
    ("pi-stylesheet", b'<?xml version="1.0"?><?xml-stylesheet href="http://example.invalid/s.xsl"?>'
                      b"<x/>"),
    ("pi-inside", b"<x><?php echo 1; ?></x>"),
    ("pi-after-root", b"<x/><?tail?>"),
    ("depth-65", b"<a>" * 65 + b"</a>" * 65),
    ("not-well-formed", b"<x>"),
    ("two-roots", b"<x/><y/>"),
    ("empty", b""),
    # A module is UTF-8 (CR-new-R2-22). Names Python's codec registry does not know, knows as a
    # non-text codec, or decodes in ways expat cannot use: each once made the interpreter's own
    # exception escape the scanner (R2-F3).
    ("encoding-unknown-name", b'<?xml version="1.0" encoding="bogus"?><x/>'),
    ("encoding-x-sjis", b'<?xml version="1.0" encoding="x-sjis"?><x/>'),
    ("encoding-ucs-2", b'<?xml version="1.0" encoding="UCS-2"?><x/>'),
    ("encoding-rot13", b'<?xml version="1.0" encoding="rot13"?><x/>'),
    ("encoding-hex", b'<?xml version="1.0" encoding="hex"?><x/>'),
    ("encoding-base64", b'<?xml version="1.0" encoding="base64"?><x/>'),
    ("encoding-name-of-5000-letters", b'<?xml version="1.0" encoding="' + b"a" * 5000
     + b'"?><x/>'),
    ("encoding-utf-32", b'<?xml version="1.0" encoding="utf-32"?><x/>'),
    ("encoding-utf-7", b'<?xml version="1.0" encoding="utf-7"?><x/>'),
    ("encoding-idna", b'<?xml version="1.0" encoding="idna"?><x/>'),
    ("encoding-punycode", b'<?xml version="1.0" encoding="punycode"?><x/>'),
    # Encodings expat or Python would read: still not UTF-8.
    ("encoding-iso-8859-1", b'<?xml version="1.0" encoding="ISO-8859-1"?><x/>'),
    ("encoding-us-ascii", b'<?xml version="1.0" encoding="US-ASCII"?><x/>'),
    ("encoding-cp1252", b'<?xml version="1.0" encoding="cp1252"?><x/>'),
    ("encoding-utf8-without-hyphen", b'<?xml version="1.0" encoding="UTF8"?><x/>'),
    ("encoding-utf-16-declared", b'<?xml version="1.0" encoding="UTF-16"?><x/>'),
    ("encoding-name-not-ascii",
     f'<?xml version="1.0" encoding="{U_UMLAUT}tf-8"?><x/>'.encode("utf-8")),
    ("encoding-name-with-a-space", b'<?xml version="1.0" encoding="UTF-8 "?><x/>'),
    # Bytes that are not UTF-8, or hold U+0000: expat would guess UTF-16 from either form.
    ("utf-16-with-byte-order-mark", "<x/>".encode("utf-16")),
    ("utf-16-be-with-byte-order-mark", b"\xfe\xff" + "<x/>".encode("utf-16-be")),
    ("utf-16-le-without-byte-order-mark", "<x/>".encode("utf-16-le")),
    ("utf-16-declared-with-byte-order-mark",
     '<?xml version="1.0" encoding="UTF-16"?><x/>'.encode("utf-16")),
    ("latin-1-byte", b"<x>\xe9</x>"),
    ("encoded-surrogate", b"<x>\xed\xa0\x80</x>"),
    ("nul-byte", b"<x>\x00</x>"),
]


@case("A-XML")
@pytest.mark.parametrize("data", [r[1] for r in REFUSED_XML], ids=[r[0] for r in REFUSED_XML])
@case("G-R40")
def test_a_fom_with_a_dtd_an_external_reference_or_a_forbidden_construct_is_refused(
        data, monkeypatch):
    """A-XML and OPS-12: rejected before the RTI sees the file: the scan runs on bytes in memory
    and refuses with E_DEPENDENCY_PIN under the module's name; nothing reaches out (no socket
    call is attempted, and the file URL of the external entity is never opened)."""
    attempts = []
    for function in sockguard.GUARDED:
        monkeypatch.setattr(socket, function, lambda *a, _f=function, **k: attempts.append(_f))
    assert dependency_refusal(_fom.scan_fom_xml, "RPR-Base_v2.0.xml", data).path == (
        "RPR-Base_v2.0.xml")
    assert attempts == []


#: Accepted: the five predefined entities, character references, comments, CDATA, the XML
#: declaration, and xsi:schemaLocation naming a URL that is never fetched.
ACCEPTED_XML = [
    b'<?xml version="1.0" encoding="UTF-8"?><x a="&lt;&gt;&amp;&quot;&apos;">&#x41;&#66;</x>',
    b"<x><!-- a comment --><![CDATA[<not> &markup;]]></x>",
    b'<objectModel xmlns="http://standards.ieee.org/IEEE1516-2010" '
    b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation='
    b'"http://standards.ieee.org/IEEE1516-2010 http://example.invalid/IEEE1516-DIF-2010.xsd"/>',
    b"<a>" * 64 + b"</a>" * 64,
    b'<?xml version="1.0" encoding="utf-8"?><x/>',
    b'<?xml version="1.0" encoding="Utf-8" standalone="yes"?><x/>',
    b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?><x/>',
    "<x a='\N{LATIN SMALL LETTER E WITH ACUTE}'>\N{GREEK SMALL LETTER ALPHA}</x>".encode("utf-8"),
]


@case("A-XML")
@pytest.mark.parametrize("data", ACCEPTED_XML, ids=[f"ok{i}" for i in range(len(ACCEPTED_XML))])
def test_what_a_pinned_module_may_hold_is_accepted(data):
    assert _fom.scan_fom_xml("RPR-Base_v2.0.xml", data) is None


@case("A-XML")
def test_no_encoding_name_but_utf_8_is_read_whatever_the_codec_registry_knows():
    """Every name and alias of Python's codec registry, declared by a module, is refused: the
    scanner reads UTF-8 only and never asks the registry, so the verdict is the same on every
    interpreter. None of these names is spelled UTF-8 (the registry writes utf_8 and utf8)."""
    import encodings.aliases
    names = sorted(set(encodings.aliases.aliases) | set(encodings.aliases.aliases.values()))
    assert {"utf_8", "utf8", "latin_1", "ascii", "utf_16", "utf_32", "base64_codec"} <= set(names)
    others = ["UTF-16BE", "UTF-16LE", "UTF-32", "x-mac-roman", "Windows-1252", "idna", "punycode",
              "rot13", "hex", "base64", "undefined", "raw-unicode-escape", "unicode-escape"]
    for name in names + others:
        assert name.upper() != "UTF-8"
        data = f'<?xml version="1.0" encoding="{name}"?><x/>'.encode("ascii")
        assert dependency_refusal(_fom.scan_fom_xml, "m.xml", data).path == "m.xml"
    for name in ("UTF-8", "utf-8", "uTF-8"):
        assert _fom.scan_fom_xml("m.xml", f'<?xml version="1.0" encoding="{name}"?><x/>'
                                 .encode("ascii")) is None


#: Pieces a mutation may splice into a document: markup that must be refused, an encoding that
#: must be refused, bytes that are not UTF-8, and harmless text.
_SPLICES = [
    b"<!DOCTYPE x>", b"&a;", b"&lt;", b"<?p?>", b"]]>", b"<![CDATA[", b"<y>", b"</y>", b"<y/>",
    b'xmlns:xi="http://www.w3.org/2001/XInclude"', b'<?xml version="1.0" encoding="bogus"?>',
    b'<?xml version="1.0" encoding="utf-32"?>', b'<?xml version="1.0" encoding="idna"?>',
    b'<?xml version="1.0" encoding="UTF-8"?>', b"\x00", b"\xff", b"\xc3", b"\xef\xbb\xbf", b" ",
    b"text", b'"', b"'", b"=", b"<", b">", b"&", b";", b"%",
]


@case("A-XML")
def test_any_bytes_give_acceptance_or_e_dependency_pin_and_nothing_else():
    """A deterministic fuzz of the scanner (seeded; 4000 documents): accepted and refused
    documents of this file with pieces spliced in, bytes changed and tails cut. The scanner
    returns None or raises HlaError E_DEPENDENCY_PIN under the module's name; never any other
    exception (R2-F3)."""
    rng = random.Random(20261010)
    seeds = ACCEPTED_XML + [data for _, data in REFUSED_XML if len(data) < 4096]
    for _ in range(4000):
        data = bytearray(rng.choice(seeds))
        for _ in range(rng.randint(1, 4)):
            roll = rng.random()
            where = rng.randint(0, len(data))
            if roll < 0.5:
                data[where:where] = rng.choice(_SPLICES)
            elif roll < 0.8 and data:
                data[min(where, len(data) - 1)] = rng.randrange(256)
            else:
                del data[where:]
        try:
            result = _fom.scan_fom_xml("RPR-Base_v2.0.xml", bytes(data))
        except HlaError as error:
            assert (type(error), error.code, error.path) == (
                HlaError, errors.E_DEPENDENCY_PIN, "RPR-Base_v2.0.xml")
        else:
            assert result is None


@case("A-XML")
def test_the_size_bound_is_2_mib_inclusive():
    """SPEC:231: 2 MiB per file; a document of exactly 2097152 bytes is scanned, one more is
    refused before parsing."""
    body = b"<x>" + b" " * (2 * 1024 * 1024 - 7) + b"</x>"
    assert len(body) == 2097152
    assert _fom.scan_fom_xml("m.xml", body) is None
    assert dependency_refusal(_fom.scan_fom_xml, "m.xml", body + b" ").path == "m.xml"


def _depth(data: bytes) -> int:
    """Maximum element depth, counted by the standard library's ElementTree, independently."""
    depth = deepest = 0
    for event, _ in ElementTree.iterparse(io.BytesIO(data), events=("start", "end")):
        depth += 1 if event == "start" else -1
        deepest = max(deepest, depth)
    return deepest


@case("A-XML")
@pytest.mark.parametrize("name", FOM_MODULE_ORDER)
def test_each_pinned_module_passes_at_its_own_depth_and_size_and_not_one_below(name):
    """The pinned modules hold an xsi:schemaLocation and no DTD, entity or XInclude: they pass.
    With the seam set to each module's own depth and size (counted by ElementTree and len) it
    still passes; one less and it is refused, so the bounds are applied to real files."""
    path = {p.name: p for p in fom_modules()}[name]
    data = path.read_bytes()
    depth = _depth(data)
    assert b"schemaLocation" in data
    assert _fom.scan_fom_xml(path.name, data) is None
    exact = dataclasses.replace(V1, dependency_xml_depth=depth, dependency_xml_bytes=len(data))
    assert _fom.scan_fom_xml(path.name, data, limits=exact) is None
    for lower in (dataclasses.replace(exact, dependency_xml_depth=depth - 1),
                  dataclasses.replace(exact, dependency_xml_bytes=len(data) - 1)):
        assert dependency_refusal(_fom.scan_fom_xml, path.name, data, limits=lower).path == (
            path.name)


@pytest.mark.parametrize("name,path", [
    ("\x1b[2J.xml", f"{R}[2J.xml"), ("\N{RIGHT-TO-LEFT OVERRIDE}lmx.xml", f"{R}lmx.xml"),
    ("m" * 100, "m" * 64),
])
def test_a_hostile_module_name_reaches_the_path_only_as_safe_text(name, path):
    # An undeclared entity, a document that is not well formed, a refused declaration, a byte
    # that is not UTF-8, a NUL byte, and 4097 bytes against a 4096-byte bound.
    limits = dataclasses.replace(V1, dependency_xml_bytes=4096)
    for data in (b"<x>&foo;</x>", b"<x>" * 3, b'<?xml version="1.0" encoding="bogus"?><x/>',
                 b"<x>\xff</x>", b"<x>\x00</x>", b"<x/>" + b" " * 4093):
        assert dependency_refusal(_fom.scan_fom_xml, name, data, limits=limits).path == path
    assert len(b"<x/>" + b" " * 4093) == 4097
    assert _fom.scan_fom_xml(name, b"<x/>" + b" " * 4092, limits=limits) is None


@pytest.mark.parametrize("data", ["<x/>", bytearray(b"<x/>"), None])
def test_the_scanner_reads_bytes_only(data):
    with pytest.raises(TypeError):
        _fom.scan_fom_xml("m.xml", data)


# ================================================================================= header pins

@case("G-R15")
def test_the_header_pin_map_is_the_packaged_pin_list():
    """R15 'dependency and FOM digests' and RED-V-03: the nine entries of pins.json as
    {name: sha256}, which is exactly what the bundled capture's header records."""
    expected = {name: entry["sha256"] for name, entry in packaged_pins().items()}
    assert _fom.header_pins() == expected == fixture_capture_records()[0]["pins"]
    assert len(expected) == 9
    _fom.check_header_pins(fixture_capture_records()[0]["pins"])


@pytest.mark.parametrize("change,path", [
    (lambda p: p.pop("NOTICES.txt"), "NOTICES.txt"),
    (lambda p: p.update({"RPR-Base_v2.0.xml": "0" * 64}), "RPR-Base_v2.0.xml"),
    (lambda p: p.update({"zz-extra.txt": "0" * 64}), "zz-extra.txt"),
    (lambda p: p.update({"\x1b[2J": "0" * 64}), f"{R}[2J"),
    (lambda p: p.update({chr(0xD800) + "x" * 100: "0" * 64}), R + "x" * 63),
    (lambda p: p.clear(), "CDM-LICENSE.txt"),
    # missing before extra, in the packaged order
    (lambda p: (p.pop("openrti-814a210.tar.gz"), p.update({"a-extra": "0" * 64})),
     "openrti-814a210.tar.gz"),
])
def test_a_header_pin_map_that_differs_is_e_dependency_pin(change, path):
    """RED-V-03: missing, extra or different, each refused under the file's (safe) name."""
    pins = dict(fixture_capture_records()[0]["pins"])
    change(pins)
    assert dependency_refusal(_fom.check_header_pins, pins).path == path


def test_a_pin_map_is_a_dict():
    with pytest.raises(TypeError):
        _fom.check_header_pins([("NOTICES.txt", "0" * 64)])


@pytest.mark.parametrize("name", [1, 10 ** 5000, b"NOTICES.txt", None],
                         ids=["int", "int-python-cannot-print", "bytes", "none"])
def test_the_names_of_a_pin_map_are_str(name):
    """A pin map comes from a parsed header, whose names are str; any other name is a caller
    bug (TypeError) before any entry is compared, alone or beside the nine real entries, and
    never a refusal that would have to print the name."""
    for pins in ({name: "0" * 64}, {**fixture_capture_records()[0]["pins"], name: "0" * 64}):
        with pytest.raises(TypeError) as info:
            _fom.check_header_pins(pins)
        assert type(info.value) is TypeError


def test_the_packaged_pins_are_read_from_the_package():
    expected = packaged_pins()
    assert [(p.path, p.sha256, p.size) for p in _fom.packaged_pins()] == [
        (name, entry["sha256"], entry["bytes"]) for name, entry in expected.items()]
