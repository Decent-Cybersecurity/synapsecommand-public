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
`062` and `023` are backed. `FORMAT_COVERAGE.md`'s "Deliberately out of scope" tables carry a row
for each, saying what it is and why it is not here yet: CAT023 is the ground station's own service
status, CAT062 is where a fused air picture lives, and **"Both are deferred, not rejected; a
category is an adapter"**. A reader who wants to know what the promise means has somewhere to go.

**The simulation feed was backed by nothing at all.** It named no format, so there was no
specification to pin, no gap-table row to write, and nothing that could ever have become its
evidence — and it is not that the tree merely lacked one: the word "simulation" occurs in this
repository only as a PROPERTY of formats that already ship (ASTERIX P7 real/simulated, NITS
`SIMULATED` essence, the MIL-STD-2525 simulation context digit), never as a feed. It was imported
prose from the very first commit that lifted this package out — `965e939`, 2026-08-22 — and it
survived twelve rounds and a publication because no gate compared a roadmap item against the
tree's ability to justify it.

So it was removed from all three sites rather than given a row it could not earn. A published
roadmap item that the tree cannot back is the claim class this repository does not tolerate, and
inventing a gap-table entry to keep the sentence would be the same defect wearing the fix's
clothes.

WHAT THIS GATE ENFORCES
-----------------------
1. **Every site states the roster, and states the same one.** Anchored patterns, and a pattern
   that stops matching is a FAILURE — the `tests/test_cdm_prose_counts.py` rule, for the same
   reason: a silent non-match reads as a green check on a site nobody is checking.
2. **Every member is backed** by a row in `FORMAT_COVERAGE.md` that defers it. This is the half
   that would have caught the defect: the simulation feed cannot satisfy it under any wording.
3. **The retired claim does not come back**, swept over the whole tree rather than over the three
   sites — because the way it spread in the first place was by being copied.
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

#: The roster, as ASTERIX category numbers with the descriptor each site gives them.
#:
#: PINNED, and it is a ruling rather than a fact the tree computes: what is "landing next" is a
#: statement of intent, and no test can derive intent from a source tree. What a test CAN do is
#: require every member to be backed (below) and require the three sites to agree. Landing an
#: adapter, or adding a fourth promise, is a deliberate edit here in the same commit.
ROSTER = {"062": "system tracks", "023": "service status"}

#: One per site, and each must match exactly once. The clause is captured so its contents can be
#: checked; the surrounding sentence differs at every site on purpose, because these are three
#: audiences and not three copies.
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


def clause(rel: str) -> str:
    path = REPO / rel
    assert path.exists(), f"{rel} does not exist; this module's site list is stale"
    found = list(re.finditer(CLAUSES[rel], _flat(path.read_text())))
    assert len(found) == 1, (
        f"{rel}: the landing-next clause matched {len(found)} times, expected exactly 1.\n"
        f"  pattern: {CLAUSES[rel]}\n"
        "A pattern that stops matching is a FAILURE and not a pass. If the sentence was "
        "rewritten, re-anchor it deliberately; if the roadmap emptied because everything landed, "
        "remove the site from this module and say so in the same commit."
    )
    return found[0].group("roster")


@pytest.mark.parametrize("rel", sorted(CLAUSES))
def test_every_site_states_the_same_landing_next_roster(rel):
    """The disjunction. Three audiences, one roster."""
    stated = clause(rel)
    for number, descriptor in sorted(ROSTER.items()):
        assert f"{number} {descriptor}" in stated, (
            f"{rel} promises {stated!r} and does not name {number} {descriptor!r}. The three "
            "sites are read by three different people and a roadmap that differs between them is "
            "a roadmap the reader has to reconcile"
        )
    extra = re.sub(r"|".join(f"{n} {d}" for n, d in ROSTER.items()), "", stated)
    extra = extra.replace(",", "").strip()
    assert not extra, (
        f"{rel} promises something beyond the roster: {extra!r}. Every member has to be backed by "
        f"a deferral row in {COVERAGE} — see the ruling in this module's docstring, and the "
        "simulation feed, which was published for twelve rounds backed by nothing"
    )


@pytest.mark.parametrize("number", sorted(ROSTER))
def test_every_roster_member_is_backed_by_a_deferral_row(number):
    """THE HALF THAT WOULD HAVE CAUGHT IT. A promise needs somewhere for a reader to go.

    Checked against the sentence rather than against the bare number: `062` and `023` occur in
    this document as data-item numbers, bit ranges and LSB fractions, so a substring search would
    have declared anything at all backed. What has to be present is a row DEFERRING the category.
    """
    text = _flat((REPO / COVERAGE).read_text())
    rows = [row for row in text.split("|") if f"CAT{number}" in row or f"category {number}" in row]
    assert rows, (
        f"{COVERAGE} has no table cell mentioning CAT{number}, so the roadmap promises a category "
        "the coverage document has never heard of. Either write the deferral row — what it is and "
        "why it is not here — or take it out of the roster"
    )
    deferring = [row for row in rows if "deferred" in row.lower()]
    assert deferring, (
        f"{COVERAGE} mentions CAT{number} but no cell says it is deferred. A roadmap entry needs "
        "the coverage document to record it as deferred-not-rejected; a category merely named in "
        "passing is not a backing"
    )


def test_the_backing_check_can_fail():
    """A check that finds everything backed would pass a roster of anything.

    Asserted against a category this repository has never deferred — 240 is in the out-of-scope
    enumeration as one of the "every other ASTERIX category" list and has no row of its own — so
    a mutation that widened the search to any mention would show up here.
    """
    text = _flat((REPO / COVERAGE).read_text())
    rows = [row for row in text.split("|")
            if "CAT240" in row or "category 240" in row]
    assert not any("deferred" in row.lower() for row in rows), (
        "CAT240 now reads as a deferred category, so the backing check can no longer tell a "
        "roster member from a number in a list. Pick another unbacked category for this control, "
        "or the roster is checked against nothing"
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
