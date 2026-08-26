"""The adapter count, wherever it is stated in prose, against the registry that decides it.

WHY THIS EXISTS, AND WHY IT IS AN ALLOWLIST AND NOT A SCANNER
------------------------------------------------------------
Eight documents state how many adapters are shipped, and four of them do the pair arithmetic as
well. Nothing failed a build when those numbers drifted, so they drifted: the roster sweep for
adapter #11 found `README.md` stale by six adapters, `synapse_cdm/__init__.py` stale by four,
two documents disagreeing about whether the translation count is `N×(N−1)` or `N(N−1)/2`, and
`FORMAT_COVERAGE.md`'s gap 1 undercounting its own tally by one adapter since adapter #6. Every
one of those was found by a human running `grep`, which is not a gate.

It is deliberately **not** a general prose-number scanner. A scanner over every number near the
word "adapter" would flag "two altitudes that are two different measurements" and "three
translations, nine rotations" and a dozen more, and the maintenance cost of its exemption list
would exceed the cost of the sweep it replaced. **The sweep stays a manual protocol act** —
see `packages/cdm/synapse_cdm/README.md`, "Three things the harness cannot check for you" — and
this module pins only the sites the sweep has ALREADY had to fix. Its job is narrow and worth
stating plainly: the next half-edit at a known site fails a build instead of waiting for
somebody to grep.

FAILING LOUDLY WHEN THE SENTENCE MOVES
--------------------------------------
Each site is anchored to its own sentence shape. A regex that silently matches nothing is worse
than no test at all — it reads as a passing check on a site nobody is checking any more — so a
pattern that stops matching is a FAILURE with the path and the pattern quoted, and the fix is to
re-anchor it deliberately rather than to delete the row.

The double-count sites are the ones this exists for most. `symbology.py` and
`docs/docs/cdm/entity.mdx` both carry the count TWICE in one clause — "so that ten adapters
cannot grow ten slightly different opinions" — and that is exactly the shape that half-edited
last time: commit 94c000a had to repair "seven adapters cannot grow six slightly different
opinions", a sentence that had been half-updated and read as prose either way.
"""
import os
import pathlib
import re

import pytest

import synapse_cdm
from synapse_cdm import adapter

REPO = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]


def shipped_adapters() -> dict:
    """The adapters this package SHIPS, which is not the same as the registry's length.

    `adapter.REGISTRY` is a module-level global and `__init_subclass__` adds to it, so any
    `Adapter` subclass defined anywhere — including the throwaway ones in
    `tests/test_cdm_adapter_contract.py` and `tests/test_cdm_harness.py` — is in it once that
    module has been imported. This test passed on its own and failed in the full suite until it
    was scoped, which is the honest definition anyway: the prose says "integration adapters are
    shipped", and a test double is not shipped.

    Computed on every call rather than at import time, for the same reason: what is in the
    registry depends on what has been imported, and a module-level constant would bake in
    whatever the collection order happened to be.
    """
    return {name: cls for name, cls in adapter.discover().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


# ------------------------------------------------------------------ spelled-out numbers

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}


def spelled(word: str) -> int:
    """`"thirty-six"` → 36. Raises on a word this repository does not spell numbers with.

    Only the forms actually used are supported, on purpose: a permissive parser here would
    quietly accept a typo as some other number, and the whole point of the module is that a
    wrong number is loud.
    """
    key = word.strip().lower()
    if key in _UNITS:
        return _UNITS[key]
    if key in _TENS:
        return _TENS[key]
    if "-" in key:
        tens, _, units = key.partition("-")
        if tens in _TENS and units in _UNITS and 1 <= _UNITS[units] <= 9:
            return _TENS[tens] + _UNITS[units]
    raise AssertionError(
        f"{word!r} is not a number word this test knows. Either it is a typo, or a count is "
        "now spelled a way nothing here parses — both need a human, which is the point"
    )


def pairs(n: int) -> int:
    """The translation count the documents state: unordered pairs, `N(N−1)/2`.

    The convention is pinned rather than assumed. `README.md` and `docs/docs/intro.mdx` used to
    state `N×(N−1)` while the module README stated `N(N−1)/2` with concrete numbers — 21 for
    seven adapters, 28 for eight — so applied to nine the two forms gave 72 and 36. The roster
    sweep harmonised on `N(N−1)/2`, the form with three commits of established numbers behind
    it, and this function is what stops the other one coming back.
    """
    return n * (n - 1) // 2


def flat(text: str) -> str:
    """Whitespace collapsed, because every one of these sentences is hard-wrapped."""
    return " ".join(text.split())


# ------------------------------------------------------------------------ the allowlist


class Site:
    """One stated count, its file, and the sentence shape it lives in."""

    def __init__(self, path: str, label: str, pattern: str, *,
                 count_groups: tuple[str, ...] = ("n",),
                 translations_group: str | None = None):
        self.path = path
        self.label = label
        self.pattern = pattern
        self.count_groups = count_groups
        self.translations_group = translations_group

    @property
    def id(self) -> str:
        return f"{self.path}::{self.label}"

    def match(self) -> re.Match:
        file = REPO / self.path
        assert file.exists(), f"{self.path} does not exist; the allowlist is stale"
        text = flat(file.read_text())
        found = list(re.finditer(self.pattern, text))
        assert len(found) == 1, (
            f"{self.id}: the sentence this test is anchored to matched {len(found)} times, "
            f"expected exactly 1.\n  pattern: {self.pattern}\n"
            "A pattern that stops matching is a FAILURE and not a pass — it would otherwise "
            "read as a green check on a site nobody is checking. Re-anchor it deliberately if "
            "the sentence was rewritten; do not delete the row."
        )
        return found[0]


SITES: tuple[Site, ...] = (
    # The five arithmetic sites the sweep had to fix, in the order the sweep found them.
    Site("README.md", "the shipped-adapter sentence",
         r"\*\*(?P<n>[A-Za-z]+)\s+integration adapters are shipped and harness-verified\*\*"),
    Site("README.md", "the pair-arithmetic sentence",
         r"N adapters means N\(N−1\)/2 translations and N private notions of \"a contact\" — "
         r"(?P<t>[a-z-]+) and (?P<n>[a-z]+) as of today",
         translations_group="t"),
    Site("docs/docs/intro.mdx", "the shipped-adapter sentence",
         r"(?P<n>[A-Za-z]+) integration adapters are shipped and harness-verified —"),
    Site("docs/docs/intro.mdx", "the pair-arithmetic sentence",
         r"N adapters means N\(N−1\)/2 translations and N private notions of what "
         r"\"a contact\" is — (?P<t>[a-z-]+) and (?P<n>[a-z]+) as of today",
         translations_group="t"),
    Site("packages/cdm/synapse_cdm/README.md", "the shipped-adapter sentence",
         r"(?P<n>[A-Za-z]+) integration adapters are shipped: PNTMAP"),
    Site("packages/cdm/synapse_cdm/README.md", "the pair-arithmetic sentence",
         r"(?P<n>[a-z]+) adapters means (?P<t>[a-z-]+) translations and (?P<n2>[a-z]+) "
         r"private notions of \"a contact\"",
         count_groups=("n", "n2"), translations_group="t"),
    Site("packages/cdm/synapse_cdm/__init__.py", "the shipped-adapter sentence",
         r"(?P<n>[A-Za-z]+) integration adapters are shipped \(PNTMAP"),
    Site("packages/cdm/synapse_cdm/__init__.py", "the pair-arithmetic sentence",
         r"(?P<n>[a-z]+) adapters means (?P<t>[a-z-]+) translations and (?P<n2>[a-z]+) "
         r"private notions of \"a contact\"",
         count_groups=("n", "n2"), translations_group="t"),
    # The double-count sentence, in both files that carry it. THE reason this module exists:
    # 94c000a had to repair "seven adapters cannot grow six slightly different opinions".
    Site("docs/docs/cdm/entity.mdx", "the double-count opinions sentence",
         r"in one place so (?P<n>[a-z]+) adapters cannot grow (?P<n2>[a-z]+) slightly "
         r"different opinions",
         count_groups=("n", "n2")),
    Site("packages/cdm/synapse_cdm/symbology.py", "the double-count opinions sentence",
         r"so that (?P<n>[a-z]+) adapters cannot grow (?P<n2>[a-z]+) slightly different "
         r"opinions",
         count_groups=("n", "n2")),
    # A SEVENTH site, added by the CAT034 round's stale-count sweep rather than by a repair.
    # It had never drifted; it had simply never been guarded, and it is the first thing a
    # contributor reads. See the note above `test_the_allowlist_covers_every_site_the_sweep_...`.
    Site("CONTRIBUTING.md", "the shipped-adapter sentence",
         r"the contract layer that (?P<n>[a-z]+) integration adapters translate into"),
    # The EIGHTH, and this one arrived the way the first six did — by being WRONG. The SDK
    # close-out sweep found `version.py` arguing the 1.0.0-not-0.x ruling from "ten adapters are
    # shipped and harness-verified, the `Adapter` contract has been stable across all NINE of
    # them". One sentence, the count twice, half-updated: the 94c000a shape exactly, surviving
    # because it reads as prose either way and because nothing here covered the file. It is a
    # double-count site and it is registered as one.
    Site("packages/cdm/synapse_cdm/version.py", "the contract-stability sentence",
         r"(?P<n>[a-z]+) adapters are shipped and harness-verified, the ``Adapter`` contract "
         r"has been stable across all (?P<n2>[a-z]+) of them",
         count_groups=("n", "n2")),
)


# ------------------------------------------------------------------------------- tests


def test_the_registry_is_the_authority_and_is_not_empty():
    """A count test that found no adapters would pass every comparison and prove nothing."""
    shipped = shipped_adapters()
    assert len(shipped) >= 10, f"only {len(shipped)} shipped adapters found: {sorted(shipped)}"
    assert set(shipped) <= set(adapter.discover()), "scoping cannot invent an adapter"
    # And the scoping is load-bearing rather than defensive: the raw registry is
    # larger than this whenever a test module defining an Adapter has been imported.
    assert all(not name.startswith("_") for name in shipped), \
        f"a test double reached the shipped set: {sorted(shipped)}"
    for name in ("cat048", "cat034"):
        assert name in shipped, (
            f"{name} is not registered, so the roster this module guards is not the one that "
            "shipped"
        )


def test_the_allowlist_covers_every_site_the_sweep_had_to_fix():
    """The allowlist is the sweep's output, so it has to name each file the sweep touched.

    Six of the seven are files the adapter #11 roster sweep REPAIRED. The seventh,
    `CONTRIBUTING.md`, was added by the CAT034 **Phase 1** round's sweep and had never been wrong —
    which is the more interesting way for a site to get here. That sweep went looking for a count
    that would have to MOVE and correctly found none: adapter #12 was at Phase 1, the convention
    these sites state is SHIPPED adapters, and a Phase 1 ships nothing, so every "nine" in the tree
    was still nine. What it found instead was a seventh file making the same claim as `README.md`,
    in the first paragraph a contributor reads, guarded by nothing. A correct count with no gate on
    it is the state all six of the others were in before they drifted.

    **And CAT034 Phase 2 is what paid for that.** The adapter shipped, the count moved nine to ten
    at all eleven sites across these seven files, and `CONTRIBUTING.md` was one of them — a site
    that would have gone stale silently on the very next round after it was added, which is what
    adding a correct-but-unguarded site to an allowlist is for.

    THE KNOWN GAP IN THIS ARRANGEMENT — RECORDED DEBT, STILL OPEN AS OF 1.1.0
    ------------------------------------------------------------------------
    This closure stops the allowlist SHRINKING. It cannot notice a NINTH file that starts stating an
    adapter count, because there is nothing here that reads the tree looking for one — the list is
    the input, so a site outside it is invisible by construction. Two counts have already escaped
    through that gap and both were found by a person reading rather than by a gate:

    * `MIGRATIONS.md`'s release condition 2 said "all ten harnesses" while twelve adapters shipped.
      The by-name patterns could not match it because the sentence says *harnesses*, not *adapters*;
    * `docs/docs/changelog.mdx`'s "eleven adapters have shipped so far" — which turned out to be
      CORRECT, being the count of adapters that landed with no schema change, a different set that
      happens to be spelled the same way. It is derived and gated now, but nothing had read it for
      three releases and the fact that it was right was luck rather than process.

    A discovery sweep would close this: scan the tree for a spelled number adjacent to "adapter",
    and require each hit to be in the allowlist, to name its subset, or to equal the registry. It is
    not written. The reason it is recorded here rather than in a commit message — where this debt
    spent its first round, and where nobody looking at this module would ever find it — is that this
    docstring is what the next person to extend the allowlist will read, and "add your site to the
    list" is exactly the moment to learn that the list cannot find sites for you.
    """
    covered = {site.path for site in SITES}
    assert covered == {
        "CONTRIBUTING.md",
        "README.md",
        "docs/docs/intro.mdx",
        "docs/docs/cdm/entity.mdx",
        "packages/cdm/synapse_cdm/README.md",
        "packages/cdm/synapse_cdm/__init__.py",
        "packages/cdm/synapse_cdm/symbology.py",
        "packages/cdm/synapse_cdm/version.py",
    }, (
        "the allowlist no longer matches the eight files the roster sweeps have covered. "
        "Adding a site is fine; losing one silently is how the sweep's work gets undone"
    )


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.id)
def test_every_stated_adapter_count_matches_the_registry(site):
    match = site.match()
    for group in site.count_groups:
        word = match.group(group)
        stated = spelled(word)
        shipped = len(shipped_adapters())
        assert stated == shipped, (
            f"{site.id}: prose says {word!r} ({stated}) adapters and the package ships "
            f"{shipped}.\n  matched: {match.group(0)!r}\n"
            "Update the prose — this is the drift the roster sweep exists to catch, now caught "
            "by a build instead of by a human running grep."
        )


@pytest.mark.parametrize("site", [s for s in SITES if s.translations_group],
                         ids=lambda s: s.id)
def test_every_stated_translation_count_is_the_pair_arithmetic(site):
    match = site.match()
    word = match.group(site.translations_group)
    stated = spelled(word)
    shipped = len(shipped_adapters())
    assert stated == pairs(shipped), (
        f"{site.id}: prose says {word!r} ({stated}) translations; {shipped} adapters give "
        f"{pairs(shipped)} by N(N−1)/2.\n  matched: {match.group(0)!r}\n"
        f"Note that N×(N−1) would give {shipped * (shipped - 1)} — if that is what was meant, "
        "the convention changed and `pairs()` has to change with it, in one place, deliberately."
    )


@pytest.mark.parametrize("site", [s for s in SITES if len(s.count_groups) > 1],
                         ids=lambda s: s.id)
def test_a_sentence_stating_the_count_twice_states_it_the_same_way_twice(site):
    """The half-edit guard, aimed at the exact shape 94c000a had to repair.

    "seven adapters cannot grow six slightly different opinions" reads as prose either way,
    which is why it survived review. Both halves are compared to each other as well as to the
    registry, so a half-edit fails with the two words quoted.
    """
    match = site.match()
    words = [match.group(g) for g in site.count_groups]
    assert len(set(w.lower() for w in words)) == 1, (
        f"{site.id}: the sentence states the count more than once and the statements "
        f"disagree — {words}.\n  matched: {match.group(0)!r}\n"
        "This is the half-edit shape commit 94c000a had to repair by hand: it reads as prose "
        "either way, so nothing but a comparison catches it."
    )


# ============================================================== the harness's check count
#
# The same defect as the adapter count, in a different number. `harness._COLUMNS` has SIX entries
# and five documents said FIVE — the package's own README twice, the harness's own module
# docstring twice, and `README.md` once — while `docs/docs/writing-an-adapter.mdx` alone said six.
# Nobody had written anything false: the list predated `roundtrip`, which arrived as a sixth
# column with its own docstring and its own SKIP semantics and was never counted.
#
# It is the shape this module exists for and it was missed because this module was scoped to the
# ADAPTER count. So the scope widens by one number rather than by a general scanner — the
# objection to a scanner in the header stands — and the closure below is what stops the widening
# from being a one-off.

from synapse_cdm import harness                                                 # noqa: E402

#: Each site anchored to its own sentence, with the count captured as `n`. Narrow on purpose: a
#: `\d+ checks` sweep would match the harness's exit-code prose and every fixture README.
CHECK_SITES: tuple[tuple[str, str], ...] = (
    ("README.md", r"(?P<n>[A-Z][a-z]+) checks per fixture — translate,"),
    ("packages/cdm/synapse_cdm/README.md",
     r"(?P<n>[A-Z][a-z]+) checks per fixture, and an unrun"),
    ("packages/cdm/synapse_cdm/README.md",
     r"None of the three is something the (?P<n>[a-z]+) checks"),
    ("packages/cdm/synapse_cdm/harness.py",
     r"applies the same (?P<n>[a-z]+) checks to all of them"),
    ("packages/cdm/synapse_cdm/harness.py", r"THE (?P<n>[A-Z]+) CHECKS, AND WHY EACH ONE"),
    ("docs/docs/writing-an-adapter.mdx",
     r"(?P<n>[A-Z][a-z]+) checks per fixture, and \*\*an unrun"),
)

#: The phrase that appears only where the count is stated. The closure sweeps on it.
CHECK_PHRASE = "checks per fixture"


@pytest.mark.parametrize("path,pattern", CHECK_SITES,
                         ids=[f"{p}::{i}" for i, (p, _) in enumerate(CHECK_SITES)])
def test_every_stated_check_count_is_the_number_of_columns_the_harness_renders(path, pattern):
    """The count, at every site, against `len(harness._COLUMNS)`.

    A pattern that stops matching is a FAILURE and not a pass, for the reason the header gives:
    it would otherwise read as a green check on a site nobody is checking.
    """
    file = REPO / path
    assert file.exists(), f"{path} does not exist; the allowlist is stale"
    found = list(re.finditer(pattern, flat(file.read_text())))
    assert len(found) == 1, (
        f"{path}: the sentence this is anchored to matched {len(found)} times, expected 1.\n"
        f"  pattern: {pattern}\nRe-anchor it deliberately; do not delete the row"
    )
    stated = spelled(found[0].group("n"))
    assert stated == len(harness._COLUMNS), (
        f"{path} says {stated} checks and the harness renders {len(harness._COLUMNS)}: "
        f"{harness._COLUMNS}. A check that exists and is not counted is a check nobody knows to "
        "look for in the report"
    )


def test_no_document_states_the_check_count_at_a_site_this_allowlist_does_not_know():
    """The closure, in the direction an allowlist cannot give itself.

    `CONTRIBUTING.md` carries the six-row table and states no count, which is why it is absent
    above; a count appearing there would have to be a decision rather than a copy.
    """
    # `.venv` used to be in a literal exclusion list here. It worked, and it worked for the reason
    # `tests/test_cdm_version_floor.py` retired the same list one module along: the local
    # environment happens to be called `.venv`. A reader whose is called anything else got every
    # site-packages copy of this package's README reported as a stray. The property, not the name.
    from tests.test_cdm_version_floor import NOT_OURS, is_virtualenv

    known = {path for path, _ in CHECK_SITES}
    strays = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        here = pathlib.Path(dirpath)
        if is_virtualenv(here):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in NOT_OURS)
        for name in sorted(filenames):
            path = here / name
            if path.suffix not in {".md", ".mdx", ".py"} or not path.is_file():
                continue
            rel = str(path.relative_to(REPO))
            if rel == "tests/test_cdm_prose_counts.py":
                continue                 # this module quotes the phrase in order to sweep for it
            if CHECK_PHRASE in path.read_text() and rel not in known:
                strays.append(rel)
    assert not strays, (
        f"these documents state the harness check count and this allowlist does not know them: "
        f"{strays}. Add each with an anchor to its own sentence — a site nobody checks is how "
        f"{len(harness._COLUMNS)} checks came to be documented as five in five places at once"
    )


# ======================================================= a count of a SUBSET, derived from code
#
# The third number, and it arrived the way the first two did — by being wrong. `stanag4676.py`
# said in two places that three adapters share the `ICAO24` source-id namespace; `cat048` had
# made it four, and nothing noticed because the sentence is not the ROSTER count and so looked
# like a different kind of statement.
#
# It is not. A subset count decays exactly like a roster count, and this one is worse than most,
# because the whole point of the sentence is that several adapters agree: "one airframe seen by N
# adapters derives one entity_id" is the single largest argument for the CDM in the tree, and it
# is stated as a number that nothing derives.
#
# So it is derived. `ICAO24` is a module-level constant in every adapter that files under it —
# `ICAO_SYSTEM = "ICAO24"`, `ICAO24_SYSTEM = "ICAO24"` — and reading the sources for it is a fact
# about the code rather than about the prose. The same AST-over-the-package treatment
# `tests/test_cdm_boundary.py` gives the dependency and crypto boundaries.

import ast                                                                      # noqa: E402

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent

#: The shared source-id system name whose sharer count is stated in prose.
SHARED_SYSTEM = "ICAO24"


def icao24_adapters() -> set[str]:
    """Adapter modules that file a source id under the shared `ICAO24` system name.

    By AST rather than by `grep`, so a mention inside a docstring or a comment — `cat034.py` has
    one, explaining what it is NOT doing — cannot inflate the count. Only a module-level
    assignment of the literal counts, which is how every adapter that really uses it declares it.
    """
    found = set()
    for path in sorted((PKG / "adapters").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and node.value.value == SHARED_SYSTEM:
                found.add(path.stem)
    return found


#: Sites stating how many adapters share it, anchored to their own sentences.
SHARED_SITES: tuple[tuple[str, str], ...] = (
    ("packages/cdm/synapse_cdm/adapters/stanag4676.py",
     r"including the one (?P<n>[a-z]+) adapters share"),
    ("packages/cdm/synapse_cdm/adapters/stanag4676.py",
     r"so one airframe seen by (?P<n>[a-z]+) adapters derives # one entity_id"),
)

#: `MIGRATIONS.md` states the count too and is deliberately NOT checked against today's value.
#: It is a CHANGELOG entry: "the `ICAO24` namespace now serves three adapters" sits inside the
#: `stanag4676` release entry, where "now" means "at that release", and three was right then —
#: `cat048` shipped two entries later. Updating it would falsify the record the file exists to
#: keep, which is the same ruling `PUBLICATION.md` makes about its unsigned history. Allowlisted
#: by path, and required below to still BE a history entry, so the exemption cannot quietly come
#: to cover a live claim.
HISTORICAL_SITE = "packages/cdm/synapse_cdm/MIGRATIONS.md"


def test_the_shared_namespace_is_shared_by_more_than_one_adapter():
    """A derivation that found nothing, or one, would make every comparison below vacuous."""
    found = icao24_adapters()
    assert len(found) >= 2, (
        f"the AST derivation found {sorted(found)} filing under {SHARED_SYSTEM!r}. The sentences "
        "this guards are about several adapters agreeing, so a derivation that finds fewer than "
        "two is broken rather than informative — check whether the constant was renamed"
    )
    assert "stanag4676" in found, (
        f"{sorted(found)} does not include stanag4676, which is the module carrying the prose "
        "this section checks"
    )


@pytest.mark.parametrize("path,pattern", SHARED_SITES,
                         ids=[f"{p.rsplit('/', 1)[-1]}::{i}"
                              for i, (p, _) in enumerate(SHARED_SITES)])
def test_every_stated_sharer_count_is_the_number_of_adapters_that_share_it(path, pattern):
    file = REPO / path
    assert file.exists(), f"{path} does not exist; this allowlist is stale"
    found = list(re.finditer(pattern, flat(file.read_text())))
    assert len(found) == 1, (
        f"{path}: the sentence this is anchored to matched {len(found)} times, expected 1.\n"
        f"  pattern: {pattern}\nRe-anchor it deliberately; do not delete the row"
    )
    stated = spelled(found[0].group("n"))
    actual = icao24_adapters()
    assert stated == len(actual), (
        f"{path} says {stated} adapters share the {SHARED_SYSTEM!r} namespace and "
        f"{len(actual)} do: {sorted(actual)}.\n  matched: {found[0].group(0)!r}\n"
        "This is the count the SDK close-out sweep found stale — cat048 joined and the sentence "
        "did not. It is the CDM's own headline argument stated as a number nothing derived"
    )


def test_the_historical_statement_of_the_count_is_still_inside_the_history():
    """The one exemption, checked so that it cannot spread.

    `MIGRATIONS.md` keeps `three` because a changelog entry describes a release rather than
    today: "the `ICAO24` namespace now serves three adapters" sits in the `stanag4676` entry,
    where "now" means that release, and three was right then — `cat048` shipped two entries
    later. That justification holds only while the sentence is still in a history entry. If it
    moved into the file's live prose it would be a present-tense claim wearing an exemption
    written for a past one.
    """
    text = flat((REPO / HISTORICAL_SITE).read_text())
    needle = f"**`{SHARED_SYSTEM}` namespace** now serves"
    assert needle in text, (
        f"{HISTORICAL_SITE} no longer carries the sentence this exemption is written for "
        f"(looked for {needle!r}). If the entry was rewritten, drop the exemption rather than "
        "leaving it pointing at nothing — an exemption covering no site reads as a live ruling"
    )
    history = flat((REPO / HISTORICAL_SITE).read_text().split("## History", 1)[1])
    assert needle in history, (
        f"the {SHARED_SYSTEM} count in {HISTORICAL_SITE} has moved OUT of `## History`. A "
        "changelog entry may keep a count that was right at its release; live prose may not"
    )
    stated = re.search(rf"{re.escape(needle)} (?P<n>[a-z]+) adapters", text)
    assert stated, "the historical sentence no longer states a count at all"
    assert spelled(stated.group("n")) < len(icao24_adapters()), (
        f"the historical entry says {stated.group('n')!r} and {len(icao24_adapters())} adapters "
        f"share {SHARED_SYSTEM!r} today. It is exempt because it was RIGHT AT ITS RELEASE and "
        "has been overtaken; if the two numbers ever meet, the exemption is doing nothing and "
        "the site should simply be checked like the others"
    )


# --------------------------------------- the OTHER roster: adapters that landed with no schema change
#
# Twelve adapters ship and ELEVEN of them landed without a schema change — `pntmap` came with the
# schema, so it is not in that set. Three documents state the eleven, and the number is the whole
# argument for `PACKAGE_VERSION` and `SCHEMA_VERSION` being two numbers rather than one:
#
#   packages/cdm/synapse_cdm/version.py   "it holds **eleven** entries — eleven adapters"
#   packages/cdm/synapse_cdm/MIGRATIONS.md  "is eleven entries long"
#   docs/docs/changelog.mdx               "eleven adapters have shipped so far"
#
# Nothing derived it. All three were correct when this was written — checked by counting the
# section's bullets rather than assumed, which is why they were left alone instead of "fixed" — and
# all three would go stale together, silently, on the next adapter that lands with no schema change.
# That is the shape the sweep in this module exists for, one roster along: the adapter-count sweep
# above covers the count of SHIPPED adapters and could never see this one, because it is a count of
# a different set that happens to be spelled the same way.
#
# The section's bullets are the derivation. It is the same section all three sentences point at, so
# there is no fourth statement of the fact introduced here — only a reading of the one that is
# already load-bearing.

#: The heading in `MIGRATIONS.md` whose bullets ARE this count.
NO_SCHEMA_CHANGE_HEADING = "### Adapters that landed with no schema change"

#: Where the count is stated, and the pattern that finds it. `docs/docs/changelog.mdx` is included
#: even though the page lists only nine of the eleven: `tests/test_cdm_changelog_claim.py` rules
#: that the page is a curated summary and that page-omits-an-entry is designed NOT to fail, so the
#: page's SENTENCE is a claim about the file's count and is checked against the file's count.
NO_SCHEMA_CHANGE_SITES: tuple[tuple[str, str], ...] = (
    ("packages/cdm/synapse_cdm/version.py",
     r"it holds \*\*(?P<n>[a-z]+)\*\* entries"),
    ("packages/cdm/synapse_cdm/version.py",
     r"entries — (?P<n>[a-z]+) adapters, each of which"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     r"\"Adapters that landed with no schema change\" is (?P<n>[a-z]+) entries long"),
    ("docs/docs/changelog.mdx",
     r"the two are allowed to diverge: (?P<n>[a-z]+) adapters have shipped so far"),
)


def adapters_that_landed_with_no_schema_change() -> list[str]:
    """The bullets under the heading, which is what every one of those sentences means.

    Scoped to the section by finding the next heading of any level, not by a fixed length: the
    entries are long, they grow, and a byte window would silently start reading the section after
    it.
    """
    text = (REPO / "packages/cdm/synapse_cdm/MIGRATIONS.md").read_text()
    start = text.index(NO_SCHEMA_CHANGE_HEADING)
    after = text[start + len(NO_SCHEMA_CHANGE_HEADING):]
    following = re.search(r"\n#{1,3} ", after)
    section = after[:following.start()] if following else after
    return re.findall(r"\n- \*\*`adapters/(\w+)\.py`", section)


def test_the_no_schema_change_section_is_not_empty_and_is_a_subset_of_the_roster():
    """The derivation itself, before anything is compared against it.

    A section whose bullet pattern stopped matching would return an empty list, and then every
    site below would be compared against zero — which each of them would fail, but for the wrong
    reason and with a message pointing at the prose rather than at the parser. And the set must be
    a subset of the registry: a bullet naming an adapter that does not exist is a stale entry, and
    one adapter is legitimately absent, because `pntmap` shipped WITH the schema.
    """
    landed = adapters_that_landed_with_no_schema_change()
    assert landed, (
        f"no bullets matched under {NO_SCHEMA_CHANGE_HEADING!r} in MIGRATIONS.md. The entries are "
        "written as `- **`adapters/<name>.py` ...`; if that form changed, re-anchor the pattern "
        "deliberately — an empty derivation would fail every site below for the wrong reason")
    modules = {cls.__module__.rsplit(".", 1)[-1] for cls in shipped_adapters().values()}
    unknown = sorted(set(landed) - modules)
    assert not unknown, (
        f"the section names adapter modules that are not in the registry: {unknown}. Either the "
        "adapter was renamed and the entry was not, or the entry describes something that never "
        "shipped")
    assert len(landed) < len(modules), (
        f"the section lists {len(landed)} adapters and the registry has {len(modules)}. At least "
        "one adapter shipped WITH the schema — `pntmap`, the founding one — so these two numbers "
        "meeting means either a new adapter's entry was filed in the wrong section, or pntmap "
        "acquired an entry claiming it changed no schema, which is true only in the sense that "
        "there was no schema to change")


@pytest.mark.parametrize("path,pattern", NO_SCHEMA_CHANGE_SITES,
                         ids=[f"{p}::{i}" for i, (p, _) in enumerate(NO_SCHEMA_CHANGE_SITES)])
def test_every_stated_no_schema_change_count_is_the_number_of_entries(path, pattern):
    """Each of the three documents, against the bullets.

    These are not decorative. The number is the argument for two version numbers existing at all:
    eleven adapters' worth of shipped behaviour arriving at one unchanged `schema_version` is the
    evidence that the wire contract and the Python surface move independently. A wrong number here
    weakens the one claim `version.py` is written to make.
    """
    expected = len(adapters_that_landed_with_no_schema_change())
    text = flat((REPO / path).read_text())
    found = re.search(pattern, text)
    assert found, (
        f"{path} no longer states this count where it did (looked for {pattern!r}). If the sentence "
        "was rewritten, re-anchor it here in the same commit — a site that drops out of this list "
        "silently is a site that goes stale next round")
    stated = spelled(found.group("n"))
    assert stated == expected, (
        f"{path} says {found.group('n')!r} ({stated}) adapters landed with no schema change; "
        f"MIGRATIONS.md's section holds {expected} entries: "
        f"{adapters_that_landed_with_no_schema_change()}. The section is the fact; this sentence "
        "is a restatement of it")


def test_the_no_schema_change_claim_is_stated_at_every_site_that_carries_it():
    """The closure, so the trio cannot become a pair by deletion.

    The failure this catches is not a wrong number — the parametrised test above catches those. It
    is a site quietly leaving the collection: someone rewords `version.py`'s sentence, the pattern
    stops matching, and the parametrised case for it fails loudly. Good. But someone REMOVING this
    module's entry for it, to make that failure go away, leaves two guarded sites and one free one.
    """
    covered = {path for path, _ in NO_SCHEMA_CHANGE_SITES}
    assert covered == {
        "packages/cdm/synapse_cdm/version.py",
        "packages/cdm/synapse_cdm/MIGRATIONS.md",
        "docs/docs/changelog.mdx",
    }, (
        f"the no-schema-change count is checked at {sorted(covered)}. Those three documents each "
        "state it for a different reader — the package's own argument for two version numbers, the "
        "changelog's, and the public page's. Adding a site is fine; losing one is how this sweep's "
        "work gets undone")
