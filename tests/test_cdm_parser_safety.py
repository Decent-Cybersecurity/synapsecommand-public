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

A SIXTH READING, TAKEN 2026-09-17: ON CPYTHON 3.11 THE JSON DECODER IS A WALKER TOO
-----------------------------------------------------------------------------------
* The first push of the 3.11–3.14 matrix failed on 3.11 alone in this suite's own tak test (and
  on every leg in the evidence module's foreign-host test, a different defect): `json.loads` on
  CPython 3.11 recurses once per container and raises `RecursionError` a little under a thousand
  containers deep — the reading and its conditions are in `adapter.InputTooDeep`, and no
  interpreter in the matrix decodes an arbitrary depth — so a depth measured after the decode,
  which is what `tak` did for its JSON form, was a depth
  the decoder could fail before it was measured, and the test built its thousand-deep twin
  with the very call that fails. The bound now sits in the base class beside `max_input_bytes`
  (`adapter.enforce_depth_bound`): JSON text is measured off its characters in one pass, decoded
  the way the decoder would decode it, and a parsed dict off its containers, before any adapter's
  decoder runs, and every adapter that decodes JSON — the five
  below — declares `max_depth` with its basis. An XML tree is still the adapter's to measure,
  because expat builds it without recursing and only the adapter holds it.
"""
import ast
import json
import pathlib
import time
import xml.etree.ElementTree as ET

import pyexpat
import pytest

import synapse_cdm
from synapse_cdm.adapter import (InputTooDeep, InputTooLarge, container_depth, discover,
                                 enforce_depth_bound, json_nesting_depth)

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


# ------------------------------------------------------ JSON: depth before the decoder

#: The adapters whose `to_cdm` decodes JSON text. Derived below, from the syntax tree, so a sixth
#: would be swept without an edit here and a comment that mentions the call would not.
JSON_ADAPTERS = ("adsb", "ais", "legion", "pntmap", "tak")


def _decodes_json(tree: ast.Module) -> bool:
    """`json.loads(...)` / `json.load(...)`, or `loads(...)` / `load(...)` imported from `json`."""
    from_json = {alias.asname or alias.name for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module == "json" for alias in node.names}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id == "json" and func.attr in {"loads", "load"}):
            return True
        if isinstance(func, ast.Name) and func.id in from_json and func.id in {"loads", "load"}:
            return True
    return False


def test_the_json_decoding_adapters_are_the_ones_this_module_covers():
    """Derived from the tree by parsing it, not by grepping it: an adapter that starts decoding
    JSON must not slip past this module, and a docstring that names the call must not pull one in."""
    root = pathlib.Path(synapse_cdm.__file__).parent / "adapters"
    decoding = sorted(p.stem for p in root.glob("*.py") if _decodes_json(ast.parse(p.read_text())))
    assert decoding == list(JSON_ADAPTERS), decoding


def _nested_json(depth: int) -> str:
    """Exactly `depth` nested objects, as text — never through `json.dumps`, which recurses."""
    return ('{"n":' * (depth - 1)) + "{}" + ("}" * (depth - 1))


def _nested_dict(depth: int) -> dict:
    """Exactly `depth` nested dicts, built with a loop for the same reason."""
    node: dict = {}
    for _ in range(depth - 1):
        node = {"n": node}
    return node


def _shipped_json(name: str) -> list[pathlib.Path]:
    """Every JSON document under the adapter's fixture directory, goldens included — the set the
    four bases describe when they say "shipped beside the fixtures"."""
    cls = discover()[name]
    directory = pathlib.Path(synapse_cdm.__file__).parent / "fixtures" / (cls.fixture_dir or name)
    return sorted(p for p in directory.rglob("*.json")
                  if p.name != "PROVENANCE.json" and "spec" not in p.parts
                  and "malformed" not in p.parts)


def test_the_nesting_depth_is_read_off_the_characters_and_agrees_with_the_decoder():
    """`json_nesting_depth` counts what `container_depth` would count after a decode — on every
    shipped JSON document — and counts it where the decoder cannot follow."""
    assert json_nesting_depth("{}") == 1
    assert json_nesting_depth('{"a": [1, {"b": []}]}') == 4
    assert json_nesting_depth('{"a": "[[[[{{{{"}') == 1, "brackets inside a string are text"
    assert json_nesting_depth('{"a": "\\"[", "b": [[]]}') == 3, "an escaped quote does not end it"
    assert json_nesting_depth('{"a": "\\\\", "b": [[]]}') == 3, "an escaped backslash is not an escape"
    assert json_nesting_depth('{"a": "\\n[[["}') == 1, "an escaped letter hides nothing but itself"
    assert json_nesting_depth("]]]]") == 0, "a close with nothing open is the decoder's to refuse"
    assert json_nesting_depth('"never closed [[[') == 0, "an unterminated string swallows the rest"
    assert json_nesting_depth(_nested_json(50_000)) == 50_000, "any depth, on any interpreter"
    assert container_depth(_nested_dict(1000)) == 1000
    compared = 0
    for name in JSON_ADAPTERS:
        for path in _shipped_json(name):
            text = path.read_text()
            assert json_nesting_depth(text) == container_depth(json.loads(text)), path
            compared += 1
    assert compared > 100, compared


def test_the_scan_is_linear_on_the_shape_that_made_the_first_draft_quadratic():
    """The review of 2026-09-17 read the first draft — a regular expression that blanked string
    literals before counting — at seven seconds for 64 KiB of an unterminated run of escaped
    quotes, and half an hour for a mebibyte: the engine restarted at every quote. One pass over a
    full mebibyte of either shape is milliseconds; the bound here is generous so the test measures
    the shape and not the machine."""
    one_mebibyte = 512 * 1024
    started = time.perf_counter()
    assert json_nesting_depth("[" + '\\"' * one_mebibyte) == 1
    assert json_nesting_depth("[" + '"\\' * one_mebibyte) == 1
    assert json_nesting_depth("[" * one_mebibyte) == one_mebibyte
    assert time.perf_counter() - started < 3.0


@pytest.mark.parametrize("name", JSON_ADAPTERS)
def test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it(name):
    """The sixth reading, on the adapter: the parsed form is refused past the declared bound
    BEFORE any decoder runs, always; JSON text is refused the same way wherever text past the
    bound fits the size bound, and where it cannot — adsb, whose 64 octets hold no sixty-five
    nested containers — the test says the size bound spoke rather than skipping the case.
    `pytest.raises(InputTooDeep)` catches no `RecursionError`, and on CPython 3.11 `json.loads`
    raises one a little under a thousand containers deep, so a bound measured after the decode
    is a red test here on that interpreter and never a green one."""
    cls = discover()[name]
    limits = cls.metadata.capabilities.limits
    assert limits.max_depth is not None, f"{name} declares no max_depth"
    assert "max_depth" in limits.declared_because, "a declared bound carries its basis (F5.4)"
    assert "max_depth" not in limits.absent_because
    text_reached_the_depth_check = False
    for depth in (limits.max_depth + 1, 1000, 50_000):
        with pytest.raises(InputTooDeep, match=f"nesting {depth} containers deep") as raised:
            cls().to_cdm(_nested_dict(depth))
        assert f"max_depth = {limits.max_depth}" in str(raised.value)
        text = _nested_json(depth).encode()
        if len(text) > limits.max_input_bytes:
            with pytest.raises(InputTooLarge):
                cls().to_cdm(text)
            continue
        with pytest.raises(InputTooDeep, match=f"nesting {depth} containers deep") as raised:
            cls().to_cdm(text)
        assert f"max_depth = {limits.max_depth}" in str(raised.value)
        text_reached_the_depth_check = True
    tightest = 2 * (limits.max_depth + 1)  # '[' * 65 + ']' * 65, the shortest text past the bound
    if tightest > limits.max_input_bytes:
        assert name == "adsb" and not text_reached_the_depth_check, name
    else:
        assert text_reached_the_depth_check, f"{name}: no text case reached the depth check"


@pytest.mark.parametrize("name", JSON_ADAPTERS)
def test_a_byte_order_mark_or_a_wide_encoding_does_not_walk_past_the_bound(name):
    """The review of 2026-09-17 read the first draft's guard decoding bytes as UTF-8 and looking
    at the first character as it found it, so a document opening with a byte-order mark, or in
    UTF-16 or UTF-32, went past the guard into `json.loads` — which detects those encodings on
    bytes — unmeasured. The guard now decodes the way the decoder will. Each payload is a
    thousand deep; where it cannot fit the size bound, that bound speaks first and the test
    says so."""
    cls = discover()[name]
    limits = cls.metadata.capabilities.limits
    document = _nested_json(1000)
    for label, payload in (("utf-8 with a byte-order mark", b"\xef\xbb\xbf" + document.encode()),
                           ("utf-16-be", document.encode("utf-16-be")),
                           ("utf-16 with a byte-order mark", document.encode("utf-16")),
                           ("utf-32-be", document.encode("utf-32-be"))):
        if len(payload) > limits.max_input_bytes:
            with pytest.raises(InputTooLarge):
                cls().to_cdm(payload)
            continue
        with pytest.raises(InputTooDeep, match="nesting 1000 containers deep") as raised:
            cls().to_cdm(payload)
        assert not isinstance(raised.value, RecursionError), label


@pytest.mark.parametrize("name", JSON_ADAPTERS)
def test_the_deepest_shipped_json_is_inside_the_declared_bound(name):
    """The bound is a cap and not a hair trigger: a document AT it passes the depth check in both
    forms, and the deepest JSON document shipped beside the adapter's fixtures, goldens included,
    sits far below it — read from the files, not asserted."""
    cls = discover()[name]
    bound = cls.metadata.capabilities.limits.max_depth
    assert enforce_depth_bound(cls, _nested_json(bound)) is None
    assert enforce_depth_bound(cls, _nested_dict(bound)) is None
    shipped = _shipped_json(name)
    assert shipped, f"{name} ships no JSON document"
    deepest = max(container_depth(json.loads(p.read_text())) for p in shipped)
    assert deepest * 8 <= bound, (
        f"{name}'s deepest JSON document nests {deepest} against a bound of {bound}; the margin "
        "the bound was chosen with is gone and the number wants re-deriving, not a wider assertion")


@pytest.mark.parametrize("name", XML_ADAPTERS)
def test_the_stdlib_parser_is_recorded_as_a_known_limitation(name):
    """F5.5's fifth property. The limitation is DATA in the manifest, not a line in a doc page."""
    limitations = discover()[name].metadata.limitations
    text = " ".join(entry if isinstance(entry, str) else entry.summary for entry in limitations)
    assert "xml.etree.ElementTree" in text, text
    assert "defusedxml" in text, text
