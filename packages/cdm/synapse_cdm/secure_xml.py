"""One guarded XML parse for every XML adapter that follows the first two.

WHAT THIS IS FOR
----------------
`tak.py` and `stanag4676.py` each hardened their own parse — `tak` by refusing a `<!DOCTYPE`
substring before `ET.fromstring`, `stanag4676` by driving `pyexpat` directly so an external entity
reference fails the parse. Both leave INTERNAL entity expansion to libexpat's amplification limit,
and both say so in their manifests. The adapter expansion arc (2026-09-20) brings three more XML
formats — C2SIM, AIXM 5.1.1 and 5.2, Digital NOTAM — and the parser-safety policy
(`docs/docs/security/parser-safety.mdx` §2) asks each of them for the same four properties. Four
copies of one guard is four places one of them drifts, so the guard is written once here and the
two shipped adapters are left as they are (the arc does not modify them).

THE FOUR PROPERTIES, AND HOW EACH IS OBTAINED RATHER THAN ASSERTED
--------------------------------------------------------------------
1. **DTDs are rejected.** expat's `StartDoctypeDeclHandler` fires the moment the declaration is
   seen, and the handler raises. No internal subset is read, no entity is declared, and the
   "billion laughs" document is refused at its second line — BEFORE any expansion, which is what
   the policy asks for and what a substring test on the whole document cannot promise (it reads
   the whole document first).
2. **Entity expansion is disabled.** With no DTD admitted, no entity can be declared, so every
   reference other than the five the XML specification predefines is undefined and expat reports
   it through `SkippedEntityHandler` — the handler raises. `EntityDeclHandler` raises too, as a
   second line behind the first: there is no path by which an entity declaration reaches the
   parser without a DOCTYPE, and if one existed it would be refused.
3. **No external resource, no XInclude.** Parameter-entity parsing is off
   (`XML_PARAM_ENTITY_PARSING_NEVER`), `ExternalEntityRefHandler` refuses, and an element in the
   XInclude namespace (`http://www.w3.org/2001/XInclude`) is refused where it starts. The
   standard library never resolves XInclude unless `xml.etree.ElementInclude` is called, which
   nothing here calls; the refusal makes the property explicit rather than a matter of which
   function was not invoked.
4. **Declared limits apply before expansion.** The byte bound is checked on the octets before the
   parser sees them; the depth and element bounds are checked in `StartElementHandler`, on the
   element that crosses the bound, so a document past either is refused at that element rather
   than after the whole tree exists.

Every refusal is `XmlRefused`, a `ValueError` (the class the conformance suite reads as "refused
without crashing"), carrying `kind` — one of `KINDS` — and a diagnostic that names what was seen
and which bound or rule refused it.

WHAT IT DOES NOT DO
-------------------
It does not validate against a schema — that is `normative_validation.py`'s job, behind the
optional `validate` extra — and it does not measure the parsed form: an adapter that also takes a
parsed twin holds it to `max_depth` through `adapter.enforce_depth_bound`, as the JSON adapters
do. The tree it returns is `xml.etree.ElementTree`'s own, built through `TreeBuilder` exactly as
`ET.fromstring` would build it, with namespaced tags in the `{uri}local` form.
"""
from __future__ import annotations

import dataclasses
import pyexpat
import xml.etree.ElementTree as ET
from typing import Any

#: The XInclude namespace, W3C XML Inclusions 1.0.
XINCLUDE_NAMESPACE = "http://www.w3.org/2001/XInclude"

#: The refusal kinds a caller can branch on. `size`, `depth` and `elements` are the three declared
#: bounds; the other five are the properties the parser-safety policy names.
KINDS = ("size", "depth", "elements", "dtd", "entity", "external", "xinclude", "malformed")


class XmlRefused(ValueError):
    """An XML payload this module declines to parse, with the KIND of refusal on the exception.

    A `ValueError` and not a new hierarchy, for `adapter.InputTooLarge`'s reason: the conformance
    suite's checks H and N read "refused without crashing" from the exception class.
    """

    def __init__(self, kind: str, message: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"{kind!r} is not one of {KINDS}")
        self.kind = kind
        super().__init__(f"XML refused ({kind}): {message}")


@dataclasses.dataclass(frozen=True)
class XmlLimits:
    """The three bounds this parser applies. Every one is required — an adapter that wants no
    bound says so by passing a large number it has declared, not by leaving one out, because a
    bound nobody stated is a bound nobody can read off the manifest."""

    max_bytes: int
    max_depth: int
    max_elements: int

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_depth", "max_elements"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"XmlLimits.{name} must be a positive integer, got {value!r}")


@dataclasses.dataclass(frozen=True)
class Parsed:
    """The tree and the two figures the parse measured while building it."""

    root: ET.Element
    depth: int
    elements: int


def _qualified(name: str) -> str:
    """expat's `uri}local` (namespace separator `}`) -> ElementTree's `{uri}local`."""
    return "{" + name if "}" in name else name


def parse(payload: bytes | bytearray | memoryview | str, limits: XmlLimits) -> Parsed:
    """One XML document -> its element tree, or `XmlRefused`.

    The byte bound is read off the octets first — text is counted as UTF-8, which is what it
    would have been on the wire — and the parser is only created once the size is inside it.
    """
    if isinstance(payload, str):
        octets = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        octets = bytes(payload)
    else:
        raise TypeError(f"secure_xml.parse takes bytes or text, got {type(payload).__name__}")
    if len(octets) > limits.max_bytes:
        raise XmlRefused("size", f"{len(octets)} octets against max_bytes = {limits.max_bytes}; "
                                 "refused before the parser was created")

    parser = pyexpat.ParserCreate(None, "}")
    parser.buffer_text = True
    parser.SetParamEntityParsing(pyexpat.XML_PARAM_ENTITY_PARSING_NEVER)
    builder = ET.TreeBuilder()
    state = {"depth": 0, "deepest": 0, "elements": 0}

    def doctype(name: str, system_id: Any, public_id: Any, has_internal_subset: int) -> None:
        raise XmlRefused("dtd", f"a DOCTYPE declaration (root {name!r}, system id {system_id!r}, "
                                f"public id {public_id!r}, internal subset "
                                f"{'present' if has_internal_subset else 'absent'}) is refused "
                                "before any of it is read: no format this package parses has a "
                                "legitimate use for a DTD, and an entity declared in one is the "
                                "amplification attack this parser exists to refuse")

    def entity_decl(name: str, *rest: Any) -> None:
        raise XmlRefused("entity", f"entity declaration {name!r} is refused; entity expansion is "
                                   "disabled in this parser")

    def external(context: Any, base: Any, system_id: Any, public_id: Any) -> int:
        raise XmlRefused("external", f"external entity reference (system id {system_id!r}, "
                                     f"public id {public_id!r}) is refused; this parser resolves "
                                     "no external resource")

    def skipped(name: str, is_parameter_entity: int) -> None:
        raise XmlRefused("entity", f"reference to entity &{name};, which is undefined because no "
                                   "DTD is admitted; entity expansion is disabled in this parser")

    def start(name: str, attributes: dict) -> None:
        tag = _qualified(name)
        if tag.startswith("{" + XINCLUDE_NAMESPACE + "}"):
            raise XmlRefused("xinclude", f"element {tag} is refused: XInclude is not resolved "
                                         "by this parser and an include that silently stayed "
                                         "unexpanded would be a document with a hole in it")
        state["elements"] += 1
        if state["elements"] > limits.max_elements:
            raise XmlRefused("elements", f"the document's element {state['elements']} ({tag}) "
                                         f"crosses max_elements = {limits.max_elements}; refused "
                                         "at that element, before the rest is parsed")
        state["depth"] += 1
        if state["depth"] > limits.max_depth:
            raise XmlRefused("depth", f"element {tag} nests {state['depth']} deep against "
                                      f"max_depth = {limits.max_depth}; refused at that element, "
                                      "before anything recurses into the tree")
        state["deepest"] = max(state["deepest"], state["depth"])
        builder.start(tag, {_qualified(k): v for k, v in attributes.items()})

    def end(name: str) -> None:
        state["depth"] -= 1
        builder.end(_qualified(name))

    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = entity_decl
    parser.ExternalEntityRefHandler = external
    parser.SkippedEntityHandler = skipped
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(octets, True)
    except pyexpat.ExpatError as e:
        # A reference to an entity no DTD declared is what expat reports for `&custom;` in a
        # document with no DOCTYPE — through the error and not through `SkippedEntityHandler`,
        # which fires only under a DTD (read 2026-09-20 on libexpat 2.7). Named as the entity
        # refusal it is, so a document that depends on expansion is not reported as a typo.
        if "undefined entity" in str(e):
            raise XmlRefused("entity", f"{e}: no DTD is admitted, so no entity beyond the five "
                                       "the XML specification predefines can be declared, and "
                                       "entity expansion is disabled in this parser") from e
        raise XmlRefused("malformed", f"not well-formed XML: {e}") from e
    root = builder.close()
    if root is None:
        raise XmlRefused("malformed", "not well-formed XML: no root element")
    return Parsed(root=root, depth=state["deepest"], elements=state["elements"])


def tree_depth(root: ET.Element) -> int:
    """Element nesting of a tree, counted with a stack — the reading `parse` takes while
    building, available for a tree that arrived some other way."""
    deepest, pending = 1, [(root, 1)]
    while pending:
        element, depth = pending.pop()
        deepest = max(deepest, depth)
        pending.extend((child, depth + 1) for child in element)
    return deepest
