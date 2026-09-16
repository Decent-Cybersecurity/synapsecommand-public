"""The XML posture Part 1 ships with, measured rather than recited — M's F5.5 ruling.

WHY THIS MODULE EXISTS
----------------------
M ruled that `defusedxml` may be deferred to Part 2 "provided TAK/XML parsing in P5: is bounded by
`max_input_bytes`; performs no external network retrieval; does not resolve external entities; has
malicious/malformed XML tests; records stdlib XML parsing as a known limitation. If P5 testing
shows those properties cannot be established with the current parser, STOP and harden it in P5
rather than deferring the risk."

So the four properties are TESTS and not sentences. Two adapters parse XML —
`adapters/tak.py` and `adapters/stanag4676.py`, both through `xml.etree.ElementTree` — and each
property is asserted against the real adapter where the adapter can be handed the case, and
against the stdlib parser directly where the case is about the parser itself.

WHAT THE READINGS ACTUALLY SAID, BECAUSE TWO OF THEM ARE NOT WHAT FOLKLORE SAYS
-------------------------------------------------------------------------------
* An EXTERNAL entity is not resolved. `ET.fromstring` raises `ParseError: undefined entity` — it
  never had the declaration, because it does not fetch the external subset. This is stronger than
  "does not resolve": the reference is an error rather than an empty string.
* An INTERNAL entity IS expanded, and a small one expands silently. That is the true half of the
  folklore and it is why `max_input_bytes` matters.
* An internal entity expanded past libexpat's own amplification limit is REFUSED, by the parser,
  with "limit on input amplification factor (from DTD and entities) breached". libexpat has
  carried that protection since 2.4.0 and it is on by default. `test_the_expat_build_this_runs_on
  _carries_the_amplification_limit` reads the linked version rather than assuming it, because THAT
  is the property the deferral rests on and it belongs to the runtime rather than to this package
  — which is exactly what the known limitation records, and what `defusedxml` would take out of
  the runtime's hands.

A FIFTH READING, TAKEN 2026-09-16: DEPTH IS NOT THE PARSER'S PROBLEM, IT IS THE WALKER'S
-------------------------------------------------------------------------------------
* `ET.fromstring` builds a tree of ANY depth without recursing — fifty thousand nested elements
  parse — and everything that walks the tree afterwards recurses once per level. So a valid
  document nesting a thousand empty elements, some 7 KB against a 1 MiB `max_input_bytes`, made
  both XML adapters raise `RecursionError`: one of `suite.CRASH_CLASSES`, the one class of
  failure §3.5's bounds exist to make impossible. Each adapter now declares `max_depth` and
  measures the tree with a stack, immediately after the parse and before either walker moves, and
  the tests below feed a document one past the bound and one a thousand deep and require the
  adapter's own `ValueError`. The bound is the adapter's and its number is the manifest's, which
  is why the tests read it from `capabilities.limits` rather than repeating it.
"""
import pathlib
import xml.etree.ElementTree as ET

import pyexpat
import pytest

import synapse_cdm
from synapse_cdm.adapter import InputTooLarge, discover

#: The two adapters that parse XML at all. Derived, so a third would be swept without an edit.
XML_ADAPTERS = ("stanag4676", "tak")

#: libexpat's billion-laughs protection landed in 2.4.0 and is enabled by default.
AMPLIFICATION_PROTECTION_SINCE = (2, 4, 0)


def _bomb(levels: int, fanout: int = 10) -> str:
    entities = ['<!ENTITY lol "lol">']
    for level in range(1, levels + 1):
        previous = "lol" if level == 1 else f"lol{level - 1}"
        entities.append(f'<!ENTITY lol{level} "{f"&{previous};" * fanout}">')
    return ('<?xml version="1.0"?>\n<!DOCTYPE lolz [\n' + "\n".join(entities)
            + f'\n]>\n<event>&lol{levels};</event>')


def test_the_two_xml_adapters_are_the_ones_this_module_covers():
    """Derived from the tree: a third XML adapter must not slip past this module silently."""
    root = pathlib.Path(synapse_cdm.__file__).parent / "adapters"
    parsing = sorted(p.stem for p in root.glob("*.py")
                     if "ET.fromstring" in p.read_text())
    assert parsing == ["stanag4676", "tak"], parsing


def test_the_expat_build_this_runs_on_carries_the_amplification_limit():
    """The deferral rests on the RUNTIME's expat, not on this package. Read it, do not assume."""
    assert pyexpat.version_info >= AMPLIFICATION_PROTECTION_SINCE, (
        f"libexpat {pyexpat.version_info} predates {AMPLIFICATION_PROTECTION_SINCE}, which is "
        "where the input-amplification limit was added. On this build an internal entity bomb is "
        "not refused by the parser, and M's F5.5 deferral does not hold: harden with defusedxml "
        "rather than shipping")


def test_an_external_entity_is_not_resolved():
    """The XXE case. Not merely unresolved — undefined, because the external subset is not read."""
    document = ('<?xml version="1.0"?>\n'
                '<!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>\n'
                "<event>&xxe;</event>")
    with pytest.raises(ET.ParseError, match="undefined entity"):
        ET.fromstring(document)


def test_an_external_dtd_is_not_fetched():
    """A DOCTYPE naming an unreachable host parses fine, which is what "no retrieval" looks like.

    `example.invalid` cannot resolve by RFC 2606. A parser that fetched the external subset would
    raise a name-resolution error or hang; this one returns the document.
    """
    document = ('<?xml version="1.0"?>\n'
                '<!DOCTYPE foo SYSTEM "http://example.invalid/x.dtd">\n'
                "<event/>")
    assert ET.fromstring(document).tag == "event"


def test_a_small_internal_entity_is_expanded_and_a_bomb_is_refused():
    """Both halves in one test, because the pair is the fact — one without the other misleads."""
    modest = ET.fromstring(_bomb(3))
    assert len(modest.text) == 3000                     # 10^3 x "lol", expanded silently

    with pytest.raises(ET.ParseError, match="amplification"):
        ET.fromstring(_bomb(6))


@pytest.mark.parametrize("name", XML_ADAPTERS)
def test_the_xml_adapters_refuse_an_oversized_document_before_parsing_it(name):
    """F5.5's first property, on the adapter rather than on the parser."""
    cls = discover()[name]
    bound = cls.metadata.capabilities.limits.max_input_bytes
    document = b"<event>" + b"x" * (bound + 1) + b"</event>"
    with pytest.raises(InputTooLarge):
        cls().to_cdm(document)


@pytest.mark.parametrize("name", XML_ADAPTERS)
def test_the_xml_adapters_refuse_an_external_entity_and_a_bomb(name):
    """F5.5's "malicious/malformed XML tests", through the adapters' own entry points.

    The assertion is that the payload is REFUSED — with the parser's error or the adapter's — and
    never that it translates to something. A `SystemExit`, a `MemoryError` or a hang would be the
    failure; an exception naming the problem is the adapter behaving.
    """
    cls = discover()[name]
    xxe = ('<?xml version="1.0"?>\n'
           '<!DOCTYPE event [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>\n'
           '<event uid="x" type="a-f-G" time="2026-01-01T00:00:00Z" '
           'start="2026-01-01T00:00:00Z" stale="2026-01-01T00:01:00Z" how="m-g">&xxe;</event>')
    with pytest.raises(Exception) as raised:
        cls().to_cdm(xxe.encode())
    assert not isinstance(raised.value, (MemoryError, RecursionError, SystemExit))

    with pytest.raises(Exception) as bombed:
        cls().to_cdm(_bomb(6).encode())
    assert not isinstance(bombed.value, (MemoryError, RecursionError, SystemExit))


def _nested(name: str, depth: int) -> bytes:
    """A document the adapter would otherwise accept, nested to a total element depth of `depth`.

    Shaped per adapter, because the depth refusal must be the ONLY reason the document is
    refused: a payload refused for a missing attribute proves nothing about nesting.
    """
    if name == "tak":
        inner = "<n>" * (depth - 2) + "</n>" * (depth - 2)
        return ('<event uid="x" type="a-f-G" time="2026-01-01T00:00:00Z" '
                'start="2026-01-01T00:00:00Z" stale="2026-01-01T00:01:00Z" how="m-g">'
                f'<point lat="1" lon="2"/><detail>{inner}</detail></event>').encode()
    fixtures = pathlib.Path(synapse_cdm.__file__).parent / "fixtures" / "nits"
    body = (fixtures / "standalone_basic_track.nits.xml").read_text()
    chain = "<extension>" * (depth - 1) + "</extension>" * (depth - 1)
    return body.replace("</NITSRoot>", chain + "</NITSRoot>").encode()


def _tree_depth(root: ET.Element) -> int:
    """Counted with a stack, for the reason the adapters count it that way."""
    deepest, pending = 1, [(root, 1)]
    while pending:
        element, depth = pending.pop()
        deepest = max(deepest, depth)
        pending.extend((child, depth + 1) for child in element)
    return deepest


@pytest.mark.parametrize("name", XML_ADAPTERS)
def test_the_xml_adapters_declare_a_depth_bound_and_refuse_a_document_past_it(name):
    """The fifth reading, on the adapter: one past the declared bound and a thousand deep are both
    refused with the adapter's own `ValueError` — `pytest.raises(ValueError)` does not catch a
    `RecursionError`, so the old crash is a red test here and never a green one."""
    cls = discover()[name]
    limits = cls.metadata.capabilities.limits
    assert limits.max_depth is not None, f"{name} declares no max_depth"
    assert "max_depth" in limits.declared_because, "a declared bound carries its basis (F5.4)"
    for depth in (limits.max_depth + 1, 1000):
        document = _nested(name, depth)
        assert len(document) < limits.max_input_bytes, "the case is depth, not size"
        with pytest.raises(ValueError, match=f"{depth} elements deep") as raised:
            cls().to_cdm(document)
        assert not isinstance(raised.value, RecursionError)
        assert f"max_depth = {limits.max_depth}" in str(raised.value)


@pytest.mark.parametrize("name", XML_ADAPTERS)
def test_the_deepest_shipped_document_is_inside_the_declared_bound_and_translates(name):
    """The bound is a cap and not a hair trigger: a document AT it translates, and the deepest
    fixture the adapter ships sits far below it — read from the tree, not asserted."""
    cls = discover()[name]
    bound = cls.metadata.capabilities.limits.max_depth
    assert cls().to_cdm(_nested(name, bound)), "a document at the bound is accepted"
    directory = pathlib.Path(synapse_cdm.__file__).parent / "fixtures" / (cls.fixture_dir or name)
    shipped = sorted(p for p in directory.glob("*.xml"))
    assert shipped, f"{name} ships no XML fixture at {directory}"
    deepest = max(_tree_depth(ET.fromstring(p.read_bytes())) for p in shipped)
    assert deepest * 8 <= bound, (
        f"{name}'s deepest fixture nests {deepest} against a bound of {bound}; the margin the "
        "bound was chosen with is gone and the number wants re-deriving, not a wider assertion")


@pytest.mark.parametrize("name", XML_ADAPTERS)
def test_the_stdlib_parser_is_recorded_as_a_known_limitation(name):
    """F5.5's fifth property. The limitation is DATA in the manifest, not a line in a doc page."""
    limitations = discover()[name].metadata.limitations
    text = " ".join(entry if isinstance(entry, str) else entry.summary for entry in limitations)
    assert "xml.etree.ElementTree" in text, text
    assert "defusedxml" in text, text
