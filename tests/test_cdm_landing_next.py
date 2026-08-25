"""The published roadmap, against what this repository can actually back.

WHY THIS EXISTS
---------------
Three documents told a reader what is coming next, and the three did not agree:

    README.md                      "…the other ASTERIX categories (062 system tracks,
                                    023 service status) and the simulation feed."
    docs/docs/intro.mdx            "…the other ASTERIX categories (062 system tracks,
                                    023 service status) and simulation feeds."
    synapse_cdm/__init__.py        "…with the other ASTERIX categories and the simulation
                                    feed landing next."

Singular at one site, plural at another, and the third naming no categories at all. Two of the
three are **rendered pages** — `README.md` is this repository's front door and `intro.mdx` is the
documentation site's — so the disagreement was published.

THE RULING, WHICH IS ABOUT BACKING AND NOT ABOUT WORDING
---------------------------------------------------------
`062` and `023` were backed. `FORMAT_COVERAGE.md`'s "Deliberately out of scope" tables carried a row
for each, saying what it is and why it is not here yet, so a reader who wanted to know what the
promise meant had somewhere to go.

**The simulation feed was backed by nothing at all.** It named no format, so there was no
specification to pin, no gap-table row to write, and nothing that could ever have become its
evidence. It was imported prose from the very first commit that lifted this package out —
`965e939`, 2026-08-22 — and it survived twelve rounds and a publication because no gate compared a
roadmap item against the tree's ability to justify it. It was removed from all three sites rather
than given a row it could not earn.

THE ROADMAP HAS NOW EMPTIED, BECAUSE BOTH MEMBERS LANDED
---------------------------------------------------------
`cat062` shipped as adapter #13 and `cat023` as adapter #14, in the round that also wrote their row
sets. So the roster this module pinned is empty, the three clauses are gone from the three sites,
and the deferral rows that backed them have become shipped row sets.

**That is the state this module's own instructions anticipated** — "if the roadmap emptied because
everything landed, remove the site from this module and say so in the same commit" — and it is
handled by INVERTING the gate rather than by deleting it. Three things are asserted now, and each
one is a way the empty state could go wrong:

1. **No site states a landing-next clause.** The three patterns are kept verbatim and must match
   ZERO times each. A clause coming back without a roster behind it is exactly the defect the
   simulation feed was, and re-adding one is now a deliberate act that fails a build.
2. **Neither former member reads as deferred any more.** A category with a shipped adapter and a
   row in a declines table saying it is "deferred, not rejected" is a document telling a reader to
   wait for something that arrived — which is the same class of stale promise, pointing backwards.
3. **The retired claim still does not come back**, swept over the whole tree. That half is
   unchanged and is independent of the roster: it was never about a category.

**The roster is retired rather than emptied to `{}`.** An empty dict with the machinery still
pointed at it would read as "nothing is planned yet" and would quietly start passing again the
moment somebody added a member without adding a site. What is asserted instead is the absence of
the clause, which is a property of the DOCUMENTS and cannot be satisfied by an empty constant.

WHAT A FUTURE ROADMAP DOES
--------------------------
Restore the three clause patterns to matching, restore a roster, and restore the
backed-by-a-deferral-row check — all of it is in this file's history, and the class of defect it
exists for is not one that stops being possible.
"""
import os
import pathlib
import re

import pytest

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
COVERAGE = "packages/cdm/synapse_cdm/FORMAT_COVERAGE.md"

SELF = "tests/test_cdm_landing_next.py"

#: The roster as it stood, and it is kept for the closure below rather than for a promise: these
#: are the two categories whose deferral rows must NOT still say "deferred", because both shipped.
#: A member here is now a former member.
LANDED = {"062": "cat062", "023": "cat023"}

#: One per site, kept verbatim from when they matched. They must now match ZERO times each.
CLAUSES = {
    "README.md":
        r"More are landing next: the other ASTERIX categories \((?P<roster>[^)]*)\)\.",
    "docs/docs/intro.mdx":
        r"with more landing next: the other ASTERIX categories \((?P<roster>[^)]*)\)\.",
    "packages/cdm/synapse_cdm/__init__.py":
        r"with the other ASTERIX categories \((?P<roster>[^)]*)\) landing next\.",
}

#: The claim that was published unbacked. Both numbers, because the two rendered sites disagreed
#: about exactly that and a ban on one spelling would have left the other standing.
RETIRED = re.compile(r"simulation feeds?", re.I)


def _flat(text: str) -> str:
    """Whitespace collapsed: every one of these sentences is hard-wrapped, differently."""
    return " ".join(text.split())


@pytest.mark.parametrize("rel", sorted(CLAUSES))
def test_no_site_states_a_landing_next_clause_any_more(rel):
    """The inversion. The roadmap emptied because both members landed, so the promise goes.

    The patterns are the ones that used to have to match EXACTLY ONCE. Keeping them and requiring
    zero is what makes the retirement checkable: a deleted test would leave the sentence free to
    come back, and a rewritten pattern would leave the OLD sentence free to come back.
    """
    path = REPO / rel
    assert path.exists(), f"{rel} does not exist; this module's site list is stale"
    found = list(re.finditer(CLAUSES[rel], _flat(path.read_text())))
    assert not found, (
        f"{rel} states a landing-next clause again: {[m.group(0) for m in found]}.\n"
        "The roster emptied when cat062 and cat023 shipped, so this promise has nothing behind it "
        "unless a NEW roster was written with it. If one was, restore the roster and the "
        "backed-by-a-deferral-row check together — a promise with no backing is the defect the "
        "simulation feed was, and it survived twelve rounds because nothing compared the two."
    )


#: The exact phrase the deferral rows used. Specific on purpose: "not merely deferred" and
#: "deferred to a per-deployment ICD" both contain the word and neither is a roadmap promise, so a
#: bare `"deferred" in row` reader reports prose as a stale roster entry. This phrase only ever
#: appears where a category is being held for a future adapter.
DEFERRAL_PHRASE = "deferred, not rejected"


def _table_lines() -> list[str]:
    """Every markdown TABLE ROW in the coverage document, whole.

    Rows and not cells: a declines row states the subject in its first cell and the disposition in
    its second, so splitting on `|` separates the two halves of the fact being checked — which is
    what made the first version of this reader miss its own control.
    """
    return [line for line in (REPO / COVERAGE).read_text().splitlines()
            if line.startswith("|") and not line.startswith("|---")]


@pytest.mark.parametrize("number,name", sorted(LANDED.items()))
def test_a_landed_category_no_longer_reads_as_deferred(number, name):
    """The other direction of the same staleness: a shipped category still described as pending.

    A reader meeting `CAT062` in a declines row that says "deferred, not rejected" is being told to
    wait for something that arrived two commits ago, which is the roadmap defect pointing
    backwards. Matched on the PHRASE rather than the word: "not merely deferred" and "deferred to a
    per-deployment ICD" both contain "deferred" and neither is a promise.
    """
    from synapse_cdm import adapter
    assert name in adapter.roster(), (
        f"{name} is not registered, so this category has not in fact landed and this test is "
        "asserting the wrong thing. Either the adapter was removed — in which case a deferral row "
        "and a roster entry both have to come back — or the registry name changed"
    )
    stale = [line for line in _table_lines()
             if DEFERRAL_PHRASE in line.lower()
             and (f"CAT{number}" in line or f"category {number}" in line
                  or f"Category {number}" in line)]
    assert not stale, (
        f"{COVERAGE} still describes CAT{number} as {DEFERRAL_PHRASE!r} in {len(stale)} row(s), "
        f"and `{name}` is a registered adapter:\n  "
        + "\n  ".join(line.strip()[:180] for line in stale)
        + "\nA category with a shipped adapter that a declines table still defers is a document "
        "telling a reader to wait for something that arrived"
    )


def test_the_deferred_check_can_fail():
    """A reader that found nothing deferred anywhere would pass a roster of anything.

    Asserted against categories this repository HAS deferred and has not shipped — 063 and 065 are
    named in the CAT062 declines table as an SDPS's other two output categories, and 065's REF is
    where `I062/100`'s reference point lives — so a mutation that stopped reading the document, or
    that narrowed the phrase past matching, shows up here rather than as a clean run.
    """
    deferred = [line for line in _table_lines() if DEFERRAL_PHRASE in line.lower()]
    assert deferred, (
        f"no table row in {COVERAGE} contains {DEFERRAL_PHRASE!r} any more, so the reader above is "
        "looking at a document it can no longer find a deferral in — and would report every landed "
        "category clean whether or not it was"
    )
    assert any("063" in line and "065" in line for line in deferred), (
        "categories 063 and 065 are no longer deferred in a row this reader can see. If they "
        "shipped, they belong in LANDED; if the row was reworded, pick another deferred category "
        "for this control — an unbacked control is a control that proves nothing"
    )


def test_the_retired_claim_does_not_come_back_anywhere_in_the_tree():
    """Swept over the tree, because copying is how it reached three sites.

    Not restricted to the three roadmap documents: the sentence travelled from the package
    docstring to the README to the documentation site, and a ban that only watched the places it
    had already reached would not have stopped the next copy.
    """
    # `is_virtualenv` is IMPORTED rather than reimplemented. A reader's environment can be called
    # anything and sits inside the clone; a sweep that keyed on `.venv` would be the same defect
    # tests/test_cdm_version_floor.py just repaired, one module along.
    from tests.test_cdm_version_floor import NOT_OURS, is_virtualenv

    offenders = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        here = pathlib.Path(dirpath)
        if is_virtualenv(here):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in NOT_OURS)
        for name in sorted(filenames):
            path = here / name
            if path.suffix not in {".md", ".mdx", ".py", ".ts", ".json"}:
                continue
            rel = str(path.relative_to(REPO))
            if rel == SELF:
                continue                  # this module quotes the retired claim, on purpose
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for match in RETIRED.finditer(text):
                offenders.append(f"{rel}: {text[max(0, match.start() - 60):match.end() + 20]!r}")
    assert not offenders, (
        f"the retired roadmap claim is back at {len(offenders)} site(s):\n  "
        + "\n  ".join(offenders[:5])
        + f"\nIt names no format, so nothing in {COVERAGE} can ever back it. If a simulation "
        "adapter is genuinely coming, name the format it speaks and give it a deferral row — "
        "then it is a roster member and this ban is the thing to edit"
    )


def test_the_retired_claim_sweep_is_not_vacuous():
    """A pattern matching nothing would report the tree clean forever."""
    assert RETIRED.search("and the simulation feed."), "the singular form is no longer matched"
    assert RETIRED.search("and simulation feeds."), "the plural form is no longer matched"
    assert not RETIRED.search("no simulation indicator at any level"), (
        "the pattern now fires on the word 'simulation' alone, which occurs legitimately all over "
        "this repository as a property of formats that already ship"
    )
