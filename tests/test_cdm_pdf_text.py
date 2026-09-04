"""`gates/pdf_text.py` held to its rule, on the two incidents that produced it.

WHY THIS MODULE EXISTS, AND IT IS TWO FALSE FINDINGS RATHER THAN A STYLE PREFERENCE
-----------------------------------------------------------------------------------
Counting over `extract_text()` output *as extracted* produced a wrong number twice in two rounds,
and both times the wrong number was plausible enough to be written down:

* **2026-08-27** — a pass over MISP-2019.1 reported that the profile carries no dated Appendix B
  citation for ST 1301. Reference [56]'s title wraps mid-phrase, so a single-line pattern matched
  nothing and *the profile does not date this one* is exactly the kind of finding that reads as
  significant. Caught before it was recorded.
* **2026-08-28** — a register entry stated that ST 1303.1 prints Word's unresolved
  cross-reference placeholder once. It prints it twice, and the entry also named the wrong page
  for the site it found. **Not** caught before it was recorded; it was committed and then repaired.

**THE SHAPES ARE FIXTURED HERE VERBATIM**, taken from the documents rather than invented, so this
module witnesses the incidents instead of describing them. Both are wraps *inside* a page.

WHAT EACH DIRECTION IS FOR
--------------------------
A guard that only asserted the helper finds two would pass on a helper that returns 2 for
everything. So every incident fixture is asserted **twice**: the naive method must MISS it and the
helper must FIND it. If a fixture ever stops fooling the naive method it has stopped witnessing the
defect, and `test_every_incident_fixture_actually_defeats_the_naive_method` fails rather than
passing quietly — which is the failure mode the sweep-protocol modules already guard for counts.

THE ONE SHAPE THAT IS PROSPECTIVE AND IS LABELLED AS SUCH
----------------------------------------------------------
A token split across a **page boundary** has not been met in this repository. It is guarded because
per-page normalisation cannot see it *even after this module's rule is applied per page* — only
joining first can — and because every round so far has joined pages with a newline and then
counted, which is the arrangement that hides it. It is fixtured as a constructed case and says so.
"""
import pathlib
import re

import pytest

from gates.pdf_text import (Match, RFC_FOOTER, RFC_HEADER, count, findall, locate, normalized,
                            per_page, text_pages)

REPO = pathlib.Path(__file__).resolve().parents[1]
SPEC = REPO / "packages" / "cdm" / "synapse_cdm" / "fixtures" / "klv" / "spec"

PLACEHOLDER = "Error! Reference source not found"

#: ST 1303.1 page 13, verbatim from the pinned copy — the site the register entry missed. The
#: placeholder breaks after "Error!" and the entry that read this document said "once".
INCIDENT_PLACEHOLDER_WRAP = (
    "0x02 MISB ST 1201 Floating Point to Integer Mapping - See Error! \n"
    "Reference source not found. \n2 \n \nAppendix D.1 MISB ST 1201 Element Processing \n"
)

#: ST 1303.1 page 4, verbatim — the site the same pass *did* find, because it happens not to wrap.
#: Kept so the fixture pair reproduces the real asymmetry rather than only the failing half.
INCIDENT_PLACEHOLDER_INTACT = (
    "such an example is using MISB ST 1201 [2] (see Error! Reference source not found.) to \n"
    "compress floating point values before they are inserted into the Array. \n"
)

#: MISP-2019.1 page 65, verbatim — reference [56]'s title wrapping between "Local" and "Set".
INCIDENT_TITLE_WRAP = (
    "[56]  MISB ST 1301.2 Motion Imagery Identification System - Augmentation Identifiers Local \n"
    "Set, Feb 2014. \n[57]  MISB ST 0903.4 Video Moving Target Indicator and Track Metadata. \n"
)

#: CONSTRUCTED, NOT WITNESSED. No held document has been found doing this. See the module docstring.
PROSPECTIVE_PAGE_SPLIT = [
    "... Floating Point to Integer Mapping - See Error! Reference source not",
    "found. Appendix D.1 MISB ST 1201 Element Processing ...",
]

#: Every fixture that must defeat a naive substring test, with the phrase it hides.
INCIDENT_FIXTURES = {
    "ST 1303.1 p13 placeholder wrap": ([INCIDENT_PLACEHOLDER_WRAP], PLACEHOLDER),
    "MISP-2019.1 p65 title wrap": ([INCIDENT_TITLE_WRAP], "Augmentation Identifiers Local Set"),
    "constructed page-boundary split": (PROSPECTIVE_PAGE_SPLIT, PLACEHOLDER),
}


def _naive(pages, needle):
    """What both rounds actually ran: count the needle per page, over raw extracted text."""
    return sum(page.count(needle) for page in pages)


# ------------------------------------------------------------------ the incidents, both directions

@pytest.mark.parametrize("name", sorted(INCIDENT_FIXTURES))
def test_every_incident_fixture_actually_defeats_the_naive_method(name):
    """NON-VACUITY, and it is the assertion that keeps the rest of this module honest.

    A fixture that the naive method already handles witnesses nothing. If normalising a fixture
    ever stops changing the answer — someone "tidied" the newline out of a verbatim quotation, say
    — this fails, rather than the helper silently being asserted against a case it never had to
    solve.
    """
    pages, needle = INCIDENT_FIXTURES[name]
    assert _naive(pages, needle) == 0, (
        f"{name}: the naive per-page substring count already finds this, so the fixture no longer "
        "reproduces the defect. Either the quotation lost the line break it was kept for, or the "
        "needle changed — check it against the pinned document before relaxing this"
    )


@pytest.mark.parametrize("name", sorted(INCIDENT_FIXTURES))
def test_the_helper_finds_what_the_naive_method_missed(name):
    """The other direction. Both are needed: the fixture must be hard AND the helper must solve it."""
    pages, needle = INCIDENT_FIXTURES[name]
    assert count(pages, needle) == 1, (
        f"{name}: normalised counting must find the occurrence the raw text hides. This is the "
        "whole rule — collapse whitespace and join pages before matching"
    )


def test_the_two_st_1303_1_sites_count_as_two_and_the_naive_method_says_one():
    """THE INCIDENT ITSELF, reproduced end to end: one wrapped site, one intact, and the entry said one.

    This is the register defect in miniature. The naive count is 1 and is wrong, and it is wrong in
    the direction that reads like a document saying less than expected.
    """
    pages = [INCIDENT_PLACEHOLDER_INTACT, INCIDENT_PLACEHOLDER_WRAP]
    assert _naive(pages, PLACEHOLDER) == 1, "the intact site is found and the wrapped one is not"
    assert count(pages, PLACEHOLDER) == 2, "normalised, both sites are found"


def test_page_attribution_survives_a_wrap_and_names_both_pages():
    """`locate` answers the claim a register entry actually makes: *twice, on pages 4 and 13*."""
    pages = [INCIDENT_PLACEHOLDER_INTACT, INCIDENT_PLACEHOLDER_WRAP]
    assert [m.page for m in locate(pages, PLACEHOLDER)] == [1, 2]
    assert per_page(pages, PLACEHOLDER) == [(1, 1), (2, 1)]


def test_a_match_spanning_a_page_boundary_is_attributed_to_where_it_starts_and_says_so():
    """The one honest answer for a boundary-spanning match, and the flag that admits it is partial."""
    found = locate(PROSPECTIVE_PAGE_SPLIT, PLACEHOLDER)
    assert len(found) == 1
    assert found[0].page == 1, "a match is attributed to the page its first character came from"
    assert found[0].spans_pages is True, (
        "a caller citing one page number for a match that crosses a boundary is entitled to know "
        "the number is a simplification"
    )


def test_a_match_inside_one_page_is_not_flagged_as_spanning():
    """The mirror. Without this the flag could be hard-wired True and every test above would pass."""
    found = locate([INCIDENT_PLACEHOLDER_WRAP], PLACEHOLDER)
    assert len(found) == 1 and found[0].spans_pages is False


# ------------------------------------------------------------------------- what the rule refuses

def test_hyphenated_line_breaks_are_not_rejoined():
    """A DELIBERATE NON-FEATURE, asserted so it cannot be added as a convenience.

    Whether a trailing hyphen before a break is the layout's or the term's is not decidable from
    the bytes, so rejoining would manufacture tokens the document does not contain — the same class
    of error as the one this module exists to stop, pointing the other way.
    """
    assert normalized(["multi-\ndimensional array"]) == "multi- dimensional array"
    assert count(["multi-\ndimensional array"], "multidimensional") == 0


def test_pages_are_joined_with_a_separator_and_never_welded():
    """Joining with nothing would fuse the last token of one page to the first of the next."""
    assert normalized(["ends in ST", "1201 begins"]) == "ends in ST 1201 begins"
    assert count(["Appendix", "D.1"], "AppendixD.1") == 0


def test_every_flavour_of_whitespace_collapses():
    """Form feeds and tabs are what some extractors emit at page ends; newlines are the incident."""
    assert normalized(["a\n\n b\tc\x0cd  e"]) == "a b c d e"


def test_normalized_accepts_an_already_joined_string():
    """Callers that only hold one string should not have to fake a page list to use the rule."""
    assert normalized("Error! \nReference source not found") == PLACEHOLDER


def test_findall_is_not_defeated_by_a_wrap():
    """The regex door into the same rule — the shape both incidents actually came through."""
    assert findall([INCIDENT_TITLE_WRAP], r"Augmentation Identifiers \w+") == [
        "Augmentation Identifiers Local"
    ]
    assert findall([INCIDENT_TITLE_WRAP], r"\[56\]\s+MISB ST (\d+\.\d)") == ["1301.2"]


def test_empty_pages_do_not_shift_attribution():
    """A blank page between two others must not renumber the pages after it."""
    pages = ["", INCIDENT_PLACEHOLDER_INTACT, "   \n ", INCIDENT_PLACEHOLDER_WRAP]
    assert [m.page for m in locate(pages, PLACEHOLDER)] == [2, 4]


def test_locate_accepts_a_compiled_pattern():
    assert [m.text for m in locate([INCIDENT_TITLE_WRAP], re.compile(r"Feb \d{4}"))] == ["Feb 2014"]


def test_a_needle_that_is_absent_is_absent():
    """The trivial direction, which stops the helper from being a function that returns 1."""
    assert count([INCIDENT_TITLE_WRAP], PLACEHOLDER) == 0
    assert locate([INCIDENT_TITLE_WRAP], PLACEHOLDER) == []
    assert per_page([INCIDENT_TITLE_WRAP], PLACEHOLDER) == []


def test_the_match_tuple_is_the_documented_shape():
    """`Match` is what callers destructure; its field order is part of the contract."""
    assert Match._fields == ("page", "start", "text", "spans_pages")


# ------------------------------------------------------- against the pinned documents when held

@pytest.mark.skipif(not (SPEC / "ST1303.1.pdf").exists(),
                    reason="no pinned ST 1303.1 in this working tree; .gitignore excludes *.pdf, "
                           "so a fresh clone has the record and not the document")
def test_the_repaired_figure_re_derives_from_the_pinned_document():
    """THE LIVE SUBJECT. The entry now says two sites, pages 4 and 13, and this is where that is checked.

    Skipped in a fresh clone by design — the PDFs are not tracked, and a hash plus an origin URL is
    what reproduces them. Where the document *is* held, the figure the register states must come
    back out of it through the rule, not through whatever the round that wrote it happened to run.
    """
    pypdf = pytest.importorskip(
        "pypdf", reason="no PDF reader in this environment; the standing rule installs one outside "
                        "`.venv`, so the suite must not require it")
    pages = [p.extract_text() or "" for p in pypdf.PdfReader(str(SPEC / "ST1303.1.pdf")).pages]
    assert per_page(pages, PLACEHOLDER) == [(4, 1), (13, 1)], (
        "the register records two sites at pages 4 and 13. A disagreement here means either the "
        "entry or this rule is wrong, and per the round's stop rule that is an adjudication rather "
        "than a fix"
    )
    assert _naive(pages, PLACEHOLDER) == 1, (
        "the naive method must still return the wrong answer on the real document — if it does "
        "not, this document is no longer the witness this module claims it is"
    )


# ------------------------------------------------------- paginated text, the third incident shape
#
# Added 2026-09-04 by the text-pins round. RFC 2781 is served as `text/plain` and paginated by the
# publisher: 14 form feeds, a `[Page N]` footer on every page, a running header on all but the
# first. A phrase that crosses a page boundary is separated from itself by five lines of furniture,
# so `normalized` alone welds the furniture's words INTO the sentence — which is worse than the
# wrap it was built to fix, because the result reads as prose and is not.

#: RFC 2781's page 5 / page 6 boundary, verbatim from the pinned copy. The sentence "the resulting
#: string may contain an unintended "ZERO WIDTH NON-BREAKING SPACE" at the connection point" is
#: split across it, with the footer, the form feed and the running header in between.
RFC_PAGE_BREAK = (
    "   strings, it is important to strip out those signatures, because\n"
    "   otherwise the resulting string may contain an unintended \"ZERO WIDTH\n"
    "\n\n\n"
    "Hoffman & Yergeau            Informational                      [Page 5]\n"
    "\f\n"
    "RFC 2781            UTF-16, an encoding of ISO 10646       February 2000\n"
    "\n\n"
    "   NON-BREAKING SPACE\" at the connection point. Also, some\n"
    "   specifications mandate an initial 0xFEFF character in objects\n"
)

RFC_SPANNING_PHRASE = ('the resulting string may contain an unintended "ZERO WIDTH '
                       'NON-BREAKING SPACE" at the connection point')


def test_the_page_break_fixture_defeats_the_unrouted_method():
    """The witness, and it must fail the naive way before the helper is allowed to mean anything.

    This is the same discipline `test_every_incident_fixture_actually_defeats_the_naive_method`
    applies to the two PDF incidents: a fixture that the plain method already handles proves
    nothing about the fix.
    """
    assert normalized(RFC_PAGE_BREAK).count(RFC_SPANNING_PHRASE) == 0, (
        "the raw text already yields the phrase, so this fixture is not the incident it claims to "
        "be — check that the furniture is still between the two halves"
    )
    # And the specific way it fails: the furniture's words are welded into the sentence.
    assert "ZERO WIDTH Hoffman & Yergeau" in normalized(RFC_PAGE_BREAK), (
        "the failure mode has changed shape. The point of routing paginated text is that collapsing "
        "it puts the footer and the header INSIDE the sentence"
    )


def test_text_pages_recovers_a_phrase_split_across_a_page_boundary():
    """The fix, on the fixture the test above proved is a real witness."""
    pages = text_pages(RFC_PAGE_BREAK)
    assert count(pages, RFC_SPANNING_PHRASE) == 1
    found = locate(pages, RFC_SPANNING_PHRASE)
    assert [(m.page, m.spans_pages) for m in found] == [(1, True)], (
        f"attribution is {[(m.page, m.spans_pages) for m in found]}. A match that begins on the "
        "first of the two pages is reported there and flagged as spanning — the honest half of the "
        "attribution, exactly as for a PDF page boundary"
    )


def test_text_pages_strips_furniture_and_nothing_else():
    """The line between removing layout and editing prose, asserted in both directions."""
    pages = text_pages(RFC_PAGE_BREAK)
    joined = "\n".join(pages)
    assert "[Page 5]" not in joined and "Hoffman & Yergeau" not in joined, "footer survived"
    assert "UTF-16, an encoding of ISO 10646" not in joined, "running header survived"
    assert "\f" not in joined, "form feed survived"
    # Not stripped: indentation, blank runs inside a page, and every word of the prose.
    assert "   strings, it is important to strip out those signatures" in joined, (
        "indentation was altered. Removing furniture is not reflowing text"
    )
    assert "specifications mandate an initial 0xFEFF character" in joined


def test_an_unpaginated_text_document_comes_back_as_one_page_rather_than_raising():
    """The honest answer for a text file with no page breaks, and it is why this does not raise."""
    pages = text_pages("one line\nand another")
    assert len(pages) == 1, f"an unpaginated document came back as {len(pages)} pages"
    assert count(pages, "one line and another") == 1
    # A trailing form feed must not manufacture a final empty page: `locate`'s numbering has to
    # agree with the document's own footers, and a phantom page shifts every attribution after it.
    assert len(text_pages("page one\n\fpage two\n\f")) == 2


def test_a_running_header_is_stripped_by_POSITION_and_not_by_SHAPE():
    """The prospective guard, and the reason it is position and not pattern.

    `RFC_HEADER` matches a line beginning `RFC <digits>`. An RFC that cites another RFC at the
    start of a reference-list line has such a line as CONTENT, and a stripper keyed on shape alone
    would delete it. RFC 2781 itself contains no such line — measured, and recorded in
    `text_pages`'s docstring as a prospective case rather than a witnessed one — so the guard is
    checked here on a synthetic document that does have one.
    """
    document = ("RFC 9999            A Title                                  January 2030\n"
                "\n"
                "   The following is cited:\n"
                "RFC 2781 UTF-16, an encoding of ISO 10646, February 2000.\n")
    pages = text_pages(document)
    joined = "\n".join(pages)
    assert "A Title" not in joined, (
        "the running header in first position was not stripped"
    )
    assert "RFC 2781 UTF-16, an encoding of ISO 10646, February 2000." in joined, (
        "a content line matching RFC_HEADER was deleted. The running header is distinguished from "
        "content by POSITION, and a shape-only stripper eats the document's own citations"
    )


def test_the_furniture_patterns_are_not_vacuous():
    """A pattern that matches everything is as useless as one that matches nothing."""
    assert RFC_FOOTER.match("Hoffman & Yergeau            Informational           [Page 12]")
    assert RFC_HEADER.match("RFC 2781            UTF-16, an encoding of ISO 10646   February 2000")
    for negative in ("   NON-BREAKING SPACE at the connection point.",
                     "3.2 Byte order mark (BOM)",
                     "   the page number is 5",
                     ""):
        assert not RFC_FOOTER.match(negative), f"RFC_FOOTER wrongly matched {negative!r}"
        assert not RFC_HEADER.match(negative), f"RFC_HEADER wrongly matched {negative!r}"


@pytest.mark.skipif(not (SPEC / "rfc2781.txt").exists(),
                    reason="no pinned RFC 2781 in this working tree; .gitignore excludes *.txt, "
                           "so a fresh clone has the record and not the document")
def test_the_pinned_rfc_routes_through_the_helper_and_the_raw_text_does_not():
    """THE LIVE SUBJECT, on the real 29 870 bytes rather than on a fixture cut out of them.

    Both directions, because only the pair is evidence: the phrase must be absent from the served
    text and present through `text_pages`. And the page count the helper derives must equal the
    14 the pin records, or the helper and `page_count_method`'s paginated-text variant disagree
    about what a page is.
    """
    raw = (SPEC / "rfc2781.txt").read_text()
    pages = text_pages(raw)
    assert len(pages) == 14, (
        f"`text_pages` finds {len(pages)} pages and `klv_pin.json`'s `rfc_2781.pages` records 14"
    )
    assert normalized(raw).count(RFC_SPANNING_PHRASE) == 0, (
        "the served text already yields the cross-page phrase, so this document is no longer the "
        "witness this module claims it is"
    )
    assert count(pages, RFC_SPANNING_PHRASE) == 1
    assert not any("[Page" in page for page in pages), "a footer survived on the real document"
    # The byte-order rule the tag 13 ruling quotes, findable because it does NOT cross a boundary —
    # asserted so the quotation in `klv_security_codec` is checkable against the pinned copy.
    assert count(pages, "the text SHOULD be interpreted as being big-endian") == 1
