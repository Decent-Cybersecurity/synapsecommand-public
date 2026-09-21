"""`secure_xml.parse`: the four hostile documents refused with a diagnostic, the three bounds at
and one past, and a benign document parsed to the tree the standard library would build.

Every refusal is asserted on `XmlRefused.kind` AND on the message naming what was seen, because
the parser-safety policy asks for an EXPLICIT diagnostic: a refusal that read "malformed" for a
billion-laughs document would be a refusal a reader could not act on.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from synapse_cdm import secure_xml
from synapse_cdm.secure_xml import XmlLimits, XmlRefused, parse

LIMITS = XmlLimits(max_bytes=65_536, max_depth=16, max_elements=1_000)


def _bomb(levels: int = 6, fanout: int = 10) -> bytes:
    """The billion-laughs document: `levels` entity layers, each expanding to `fanout` of the
    layer below. Six layers of ten is a million copies of the leaf, from about 400 octets."""
    lines = ['<!ENTITY lol0 "lol">']
    for level in range(1, levels + 1):
        lines.append(f'<!ENTITY lol{level} "' + f"&lol{level - 1};" * fanout + '">')
    return ("<?xml version='1.0'?>\n<!DOCTYPE bomb [\n" + "\n".join(lines) +
            f"\n]>\n<bomb>&lol{levels};</bomb>").encode()


EXTERNAL_ENTITY = (b"<?xml version='1.0'?>\n"
                   b"<!DOCTYPE doc [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]>\n"
                   b"<doc>&xxe;</doc>")
XINCLUDE = (b"<doc xmlns:xi='http://www.w3.org/2001/XInclude'>"
            b"<xi:include href='file:///etc/passwd' parse='text'/></doc>")
EXTERNAL_DTD = b"<!DOCTYPE doc SYSTEM 'http://example.invalid/doc.dtd'><doc/>"


# ------------------------------------------------------------------ the four hostile documents


def test_a_billion_laughs_document_is_refused_at_its_doctype_before_any_expansion():
    with pytest.raises(XmlRefused) as raised:
        parse(_bomb(), LIMITS)
    assert raised.value.kind == "dtd"
    assert "DOCTYPE" in str(raised.value) and "root 'bomb'" in str(raised.value)
    assert "internal subset present" in str(raised.value)


def test_an_external_entity_document_is_refused_with_a_diagnostic():
    with pytest.raises(XmlRefused) as raised:
        parse(EXTERNAL_ENTITY, LIMITS)
    assert raised.value.kind == "dtd", "the DOCTYPE that declares the entity is refused first"
    assert "DOCTYPE" in str(raised.value)


def test_an_external_dtd_reference_is_refused_and_never_fetched():
    with pytest.raises(XmlRefused) as raised:
        parse(EXTERNAL_DTD, LIMITS)
    assert raised.value.kind == "dtd"
    assert "http://example.invalid/doc.dtd" in str(raised.value)


def test_an_xinclude_document_is_refused_at_the_include_element():
    with pytest.raises(XmlRefused) as raised:
        parse(XINCLUDE, LIMITS)
    assert raised.value.kind == "xinclude"
    assert "{http://www.w3.org/2001/XInclude}include" in str(raised.value)


def test_an_undefined_entity_reference_is_refused_as_an_entity_and_not_as_malformed():
    """Without a DTD every non-predefined entity is undefined; expat reports it as skipped and the
    handler refuses by name, so a document that DEPENDS on expansion cannot pass silently."""
    with pytest.raises(XmlRefused) as raised:
        parse(b"<doc>&custom;</doc>", LIMITS)
    assert raised.value.kind == "entity"
    assert "undefined entity" in str(raised.value) and "expansion is disabled" in str(raised.value)


def test_the_five_predefined_entities_and_character_references_still_work():
    parsed = parse(b"<doc a='&quot;x&quot;'>&lt;&amp;&gt;&apos;&#65;&#x42;</doc>", LIMITS)
    assert parsed.root.text == "<&>'AB" and parsed.root.get("a") == '"x"'


# --------------------------------------------------------------------- the three bounds


def _nested(depth: int) -> bytes:
    return b"<a>" * depth + b"</a>" * depth


def test_the_depth_bound_admits_a_document_at_it_and_refuses_one_level_past():
    limits = XmlLimits(max_bytes=65_536, max_depth=8, max_elements=1_000)
    assert parse(_nested(8), limits).depth == 8
    with pytest.raises(XmlRefused) as raised:
        parse(_nested(9), limits)
    assert raised.value.kind == "depth"
    assert "nests 9 deep" in str(raised.value) and "max_depth = 8" in str(raised.value)


def test_the_element_bound_admits_a_document_at_it_and_refuses_one_element_past():
    limits = XmlLimits(max_bytes=65_536, max_depth=8, max_elements=5)
    assert parse(b"<r><a/><b/><c/><d/></r>", limits).elements == 5
    with pytest.raises(XmlRefused) as raised:
        parse(b"<r><a/><b/><c/><d/><e/></r>", limits)
    assert raised.value.kind == "elements"
    assert "element 6" in str(raised.value) and "max_elements = 5" in str(raised.value)


def test_the_byte_bound_admits_a_document_at_it_and_refuses_one_octet_past():
    document = b"<r>" + b"x" * 10 + b"</r>"
    limits = XmlLimits(max_bytes=len(document), max_depth=8, max_elements=5)
    assert parse(document, limits).root.text == "x" * 10
    with pytest.raises(XmlRefused) as raised:
        parse(document + b" ", limits)
    assert raised.value.kind == "size"
    assert f"{len(document) + 1} octets" in str(raised.value)
    assert "before the parser was created" in str(raised.value)


def test_text_is_bounded_by_its_utf8_octets():
    limits = XmlLimits(max_bytes=8, max_depth=8, max_elements=5)
    with pytest.raises(XmlRefused) as raised:
        parse("<r>é</r>", limits)          # 8 characters, 9 octets
    assert raised.value.kind == "size"


def test_a_bound_past_which_the_document_is_refused_stops_the_parse_there(monkeypatch):
    """The refusal is raised AT the crossing element: the parser never builds the rest, which is
    what "before expansion" means for a bound. Observed through a counting `TreeBuilder` — the
    builder saw exactly the elements inside the bound and not one more."""
    counted = {"n": 0}

    class Counting(ET.TreeBuilder):
        def start(self, tag, attrs):
            counted["n"] += 1
            return super().start(tag, attrs)

    monkeypatch.setattr(secure_xml.ET, "TreeBuilder", Counting)
    with pytest.raises(XmlRefused) as raised:
        parse(b"<r>" + b"<a/>" * 100 + b"</r>",
              XmlLimits(max_bytes=65_536, max_depth=8, max_elements=10))
    assert raised.value.kind == "elements"
    assert counted["n"] == 10, "the builder saw exactly the elements inside the bound"


# ------------------------------------------------------------------- the benign document


BENIGN = (b"<?xml version='1.0' encoding='UTF-8'?>\n"
          b"<!-- a comment -->\n"
          b"<root xmlns='urn:x' xmlns:y='urn:y' id='1'>\n"
          b"  <y:child y:attr='v'>text<![CDATA[ & cdata ]]></y:child>\n"
          b"  <?pi ignored?>\n"
          b"  <empty/>\n"
          b"</root>")


def test_a_benign_document_parses_to_the_tree_the_standard_library_builds():
    ours = parse(BENIGN, LIMITS)
    theirs = ET.fromstring(BENIGN)
    assert ET.tostring(ours.root) == ET.tostring(theirs)
    assert ours.root.tag == "{urn:x}root" and ours.root.get("id") == "1"
    child = ours.root.find("{urn:y}child")
    assert child is not None and child.get("{urn:y}attr") == "v"
    assert child.text == "text & cdata "
    assert (ours.depth, ours.elements) == (2, 3)
    assert secure_xml.tree_depth(ours.root) == 2


def test_malformed_xml_is_refused_as_malformed_with_expats_own_message():
    with pytest.raises(XmlRefused) as raised:
        parse(b"<root><unclosed></root>", LIMITS)
    assert raised.value.kind == "malformed"
    assert "mismatched tag" in str(raised.value)
    with pytest.raises(XmlRefused) as empty:
        parse(b"", LIMITS)
    assert empty.value.kind == "malformed"


def test_the_refusal_is_a_value_error_with_a_known_kind():
    assert issubclass(XmlRefused, ValueError)
    with pytest.raises(ValueError):
        XmlRefused("unknown-kind", "x")
    with pytest.raises(TypeError):
        parse(123, LIMITS)          # type: ignore[arg-type]


def test_limits_are_positive_integers():
    for bad in ({"max_bytes": 0}, {"max_depth": -1}, {"max_elements": 1.5}, {"max_bytes": True}):
        with pytest.raises(ValueError):
            XmlLimits(**{"max_bytes": 1, "max_depth": 1, "max_elements": 1, **bad})
