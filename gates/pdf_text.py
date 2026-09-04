"""Counting over PDF-extracted text, held to one rule: normalise and join before you match.

WHY THIS EXISTS, AND IT IS TWO INCIDENTS RATHER THAN A PRINCIPLE
---------------------------------------------------------------
Two rounds in a row produced a false finding with the same cause, and neither was a careless
reading — both were regexes and substring tests run over `extract_text()` output *as extracted*:

1. **2026-08-27, the pins round.** A first pass reported that MISP-2019.1 carries no dated
   Appendix B citation for ST 1301, which would have been a real asymmetry among four documents.
   It was an artefact: reference [56]'s title wraps mid-phrase, so the page reads
   ``... Augmentation Identifiers Local \\nSet, Feb 2014.`` and a single-line pattern matched
   nothing.
2. **2026-08-28, the register round.** An entry recorded that ST 1303.1 prints Word's unresolved
   cross-reference placeholder *once*. It prints it twice. The second is
   ``Error! \\nReference source not found.`` — the same shape, one document over — so a substring
   test found one site and missed the other, and the entry named the wrong page for the site it
   did find.

**Neither failure announced itself.** Both returned a plausible number, and a number that is too
low reads exactly like a document that says less than expected. That is the property that makes
this worth a module: the defective method's output is indistinguishable from a true finding.

THE RULE
--------
**Any count over PDF-extracted text runs on text that has been joined across pages and had its
whitespace runs collapsed, before anything is matched.** Both halves are load-bearing and they
fail differently:

* **collapse** fixes the two incidents above, which are wraps *inside* a page;
* **join** fixes the shape neither incident was — a token split across a *page boundary*. Per-page
  normalisation cannot see that one at all, because neither page contains the token. It is
  included here as a prospective case rather than a witnessed one, and `tests/test_cdm_pdf_text.py`
  says so where it fixtures it: this record has not met it, and the reason to guard it anyway is
  that every round joins pages with a newline and then counts, which is precisely the arrangement
  that hides it.

PAGINATED TEXT IS THE SAME DEFECT WITH A DIFFERENT CONTAINER
------------------------------------------------------------
Added 2026-09-04 by the text-pins round, which pinned IETF RFC 2781 — a document served as
`text/plain` and paginated by the publisher, with 14 form feeds, a running header on every page
after the first and a `[Page N]` footer on all 14.

**AN RFC BREAKS A SENTENCE EXACTLY THE WAY PDF EXTRACTION DOES, and then inserts four lines of
furniture into the break.** A phrase that spans a page boundary in RFC 2781 does not merely acquire
a newline: between its two halves sit a blank run, the footer `Hoffman & Yergeau            
Informational                      [Page 5]`, a form feed, the running header `RFC 2781            
UTF-16, an encoding of ISO 10646       February 2000`, and another blank run. So `collapse` alone
is not enough here and neither is `join`: collapsing turns all of that into single spaces and
leaves the furniture's WORDS sitting inside the sentence, which is worse than the wrap it fixed
because the resulting string reads as prose and is not.

`text_pages` is therefore a THIRD operation and not a widening of the first two: it splits the
document on its own page breaks, strips the header and footer lines from each page, and hands the
result to `normalized`, which then joins and collapses under the unchanged rule. A count over the
result is a count over the document's sentences rather than over its layout.

**THE SHAPE OF THE FAILURE IS THE ONE THIS MODULE WAS BUILT FOR.** A pattern run over RFC 2781's
raw text matches nothing where a phrase crosses a page, and returns a plausible number. Nothing
announces it. That is the property recorded at the top of this docstring, met a third time in a
container nobody had considered when it was written.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
**It does not rejoin hyphenated words.** A trailing ``-`` before a line break may be a soft hyphen
the layout inserted or a real hyphen in the term, and nothing in the bytes distinguishes them —
so joining them would be a semantic guess dressed as normalisation, and a wrong guess would
manufacture tokens the document does not contain. Runs of whitespace become one space and nothing
else changes.

**It does not read PDFs.** It takes the page texts a reader already extracted, as a sequence of
strings. That is what lets `tests/test_cdm_pdf_text.py` witness both incident shapes with no PDF
library present — and no PDF library *is* present in the environment the suite judges, by the
standing rule that a round's tooling is installed outside `.venv`.

PAGE ATTRIBUTION
----------------
`locate` exists because "twice, on pages 4 and 13" is the claim a register entry actually makes,
and a joined string cannot answer it on its own. An offset map is built alongside the normalised
text, so a match is attributed to the page its **first character** came from — which is the only
answer that stays true for a match spanning a boundary.

USAGE

    from pdf_text import normalized, count, findall, locate, text_pages

    pages = [p.extract_text() or "" for p in PdfReader(path).pages]
    count(pages, "Error! Reference source not found")     # 2
    locate(pages, "Error! Reference source not found")    # [(4, ...), (13, ...)]

    pages = text_pages(pathlib.Path("rfc2781.txt").read_text())   # 14 pages, no furniture
    count(pages, "the text SHOULD be interpreted as being big-endian")     # 1
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple, Sequence

#: What separates one page's text from the next before collapsing. A single space, never a
#: newline: joining with a newline and *then* collapsing gives the same string, but joining with
#: nothing would weld the last token of one page to the first of the next and manufacture a token
#: neither page contains — the mirror of the defect this module exists for.
PAGE_JOIN = " "

_WHITESPACE = re.compile(r"\s+")


class Match(NamedTuple):
    """One match, with the page its first character came from.

    `page` is 1-based, because every claim in this repository's register cites pages the way a
    reader sees them. `spans_pages` is the honest half of the attribution: a match that begins on
    page 12 and ends on page 13 is reported at 12, and this flag is how a caller knows the single
    number is a simplification rather than the whole truth.
    """

    page: int
    start: int
    text: str
    spans_pages: bool


#: The page break in a paginated text document. A form feed, ASCII 0x0C, which is what the RFC
#: Editor emits and what `page_count_method`'s paginated-text variant counts.
FORM_FEED = "\f"

#: An RFC's page footer: authors, status, and the page number in square brackets, right-aligned.
#: Anchored to the LINE and to the bracketed number, not to the author names — a pattern keyed on
#: "Hoffman & Yergeau" would work on exactly one document and would look like it worked on all of
#: them, which is this module's founding defect wearing a different hat.
RFC_FOOTER = re.compile(r"^.*\[Page \d+\]\s*$")

#: An RFC's running header: the series line, the title, and the date, on the first non-blank line
#: of every page after the first. Recognised by SHAPE — `RFC <digits>` at the start of the line —
#: for the same reason the footer is.
RFC_HEADER = re.compile(r"^RFC\s+\d+\s+\S.*$")


def text_pages(document: str) -> list[str]:
    """A paginated text document as a page sequence, with its page furniture removed.

    The output goes straight into `normalized`, `count`, `findall` or `locate`, which then apply
    the unchanged join-and-collapse rule — so a count over paginated text is taken over the same
    kind of string as a count over PDF-extracted text, which is the whole point of routing it here
    instead of matching the raw file.

    WHAT IS STRIPPED AND WHAT IS NOT, because the line between them is the module's own rule about
    hyphens applied to a different artefact. **Stripped:** the form feed itself, any line matching
    `RFC_FOOTER`, and the first non-blank line of a page when it matches `RFC_HEADER`. **Not
    stripped:** anything else, including indentation, blank runs inside a page and section numbers.
    Removing furniture is not editing prose, and a stripper that guessed at content would
    manufacture the same class of false finding as a rejoiner that guessed at hyphens.

    THE HEADER IS ONLY STRIPPED IN FIRST POSITION, and this is a PROSPECTIVE guard rather than a
    witnessed one — said plainly, on the precedent this module already sets for its `join` half.
    Measured on RFC 2781: `RFC_HEADER` matches 13 lines, all 13 are running headers in first
    non-blank position, and the document contains **zero** other lines mentioning `RFC 2781`. So
    the position restriction costs nothing here and catches nothing here. It is applied anyway
    because the pattern's subject is a line beginning `RFC <digits>`, and an RFC that cites another
    RFC at the start of a reference-list line — which is ordinary — would have that line deleted
    from its own content by a stripper keyed on shape alone. The running header is distinguished
    from content by POSITION, so position is what the code uses, before a document arrives where it
    matters.

    A document with no form feed comes back as a one-page list, unmodified apart from footer and
    header stripping — which is the honest answer for an unpaginated text file and is why this does
    not raise on one.
    """
    pages: list[str] = []
    for raw in document.split(FORM_FEED):
        lines = [line for line in raw.split("\n") if not RFC_FOOTER.match(line)]
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            if RFC_HEADER.match(line):
                del lines[index]
            break
        pages.append("\n".join(lines))
    # A document ending in a form feed yields a final empty segment. It is dropped rather than
    # kept as a fifteenth page: `normalized` would skip it anyway, and `_offset_map`'s page
    # numbering must agree with the document's own `[Page N]` footers or `locate` starts lying.
    while pages and not pages[-1].strip():
        pages.pop()
    return pages


def normalized(pages: Sequence[str] | str) -> str:
    """The text every count in this repository is taken over.

    Accepts the page sequence a reader produces, or a single already-joined string for the callers
    that only have one. Runs of whitespace — spaces, newlines, tabs, the form feeds some
    extractors emit at page ends — collapse to one space, and the result is stripped.
    """
    if isinstance(pages, str):
        joined = pages
    else:
        joined = PAGE_JOIN.join(pages)
    return _WHITESPACE.sub(" ", joined).strip()


def _offset_map(pages: Sequence[str]) -> tuple[str, list[int]]:
    """Normalised text, plus for each of its characters the 1-based page it came from.

    Built by normalising page by page and remembering the boundaries, rather than by normalising
    the join and trying to work backwards — the second cannot be done, because collapsing is not
    invertible.
    """
    out: list[str] = []
    owner: list[int] = []
    for number, page in enumerate(pages, 1):
        piece = _WHITESPACE.sub(" ", page).strip()
        if not piece:
            continue
        if out:
            out.append(PAGE_JOIN)
            owner.append(number - 1)
        out.append(piece)
        owner.extend([number] * len(piece))
    return "".join(out), owner


def count(pages: Sequence[str] | str, needle: str) -> int:
    """How many times `needle` occurs in the normalised text. Non-overlapping, like `str.count`."""
    return normalized(pages).count(normalized(needle))


def findall(pages: Sequence[str] | str, pattern: str | re.Pattern[str]) -> list[str]:
    """`re.findall` over the normalised text, so a pattern cannot be defeated by a line break."""
    return re.findall(pattern, normalized(pages))


def locate(pages: Sequence[str], needle: str | re.Pattern[str]) -> list[Match]:
    """Every match, with the page it starts on — the form a register entry cites.

    `needle` may be a string or a compiled pattern. A string is normalised first, so a caller may
    pass a phrase spelled the way the document prints it across two lines.
    """
    text, owner = _offset_map(pages)
    if isinstance(needle, re.Pattern):
        finder: Iterable[re.Match[str]] = needle.finditer(text)
    else:
        finder = re.finditer(re.escape(normalized(needle)), text)
    found: list[Match] = []
    for m in finder:
        first, last = m.start(), max(m.start(), m.end() - 1)
        page = owner[first] if first < len(owner) else 0
        end_page = owner[last] if last < len(owner) else page
        found.append(Match(page, m.start(), m.group(0), end_page != page))
    return found


def per_page(pages: Sequence[str], needle: str) -> list[tuple[int, int]]:
    """`(page, hits)` for every page with at least one match, attribution as `locate` gives it."""
    tally: dict[int, int] = {}
    for m in locate(pages, needle):
        tally[m.page] = tally.get(m.page, 0) + 1
    return sorted(tally.items())
