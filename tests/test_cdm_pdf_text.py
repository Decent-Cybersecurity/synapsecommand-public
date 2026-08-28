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

from gates.pdf_text import Match, count, findall, locate, normalized, per_page

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
