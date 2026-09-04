"""The adapter count, wherever it is stated in prose, against the registry that decides it.

WHY THIS EXISTS, AND WHY IT IS AN ALLOWLIST AND NOT A SCANNER
------------------------------------------------------------
The documents in `SITES` state how many adapters are shipped, and the rows carrying a
`translations_group` do the pair arithmetic as well. Nothing failed a build when those numbers
drifted, so they drifted: the roster sweep for
adapter #11 found `README.md` stale by six adapters, `synapse_cdm/__init__.py` stale by four,
two documents disagreeing about whether the translation count is `N×(N−1)` or `N(N−1)/2`, and
`FORMAT_COVERAGE.md`'s gap 1 undercounting its own tally by one adapter since adapter #6. Every
one of those was found by a human running `grep`, which is not a gate.

It is deliberately **not** a general prose-number scanner. A scanner over every number near the
word "adapter" would flag "two altitudes that are two different measurements" and "three
translations, nine rotations" and a dozen more, and the maintenance cost of its exemption list
would exceed the cost of the sweep it replaced. **The sweep stays a manual protocol act** —
see `packages/cdm/synapse_cdm/README.md`, "Four things the harness cannot check for you" — and
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
`docs/docs/cdm/entity.mdx` both carry the count TWICE in one clause — "so that fourteen adapters
cannot grow fourteen slightly different opinions" — and that is exactly the shape that half-edited
last time: commit 94c000a had to repair "seven adapters cannot grow six slightly different
opinions", a sentence that had been half-updated and read as prose either way.
"""
import os
import pathlib
import re
import subprocess

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


def unwrapped(path: str, text: str) -> str:
    """`flat()`, plus the `#` markers stripped when the sentence lives in a comment BLOCK.

    `packages/cdm/pyproject.toml` states this count inside a hard-wrapped `#` block, so collapsing
    whitespace alone leaves a `#` sitting in the middle of the sentence at every wrap point — and a
    pattern written around that `#` is anchored to where the paragraph happens to wrap rather than
    to what it says. Re-flowing the comment by one word would then break the row for no reason,
    which is the opposite of what `flat()` is for. Applied by suffix rather than by path so a
    second `.toml` site needs no second decision.
    """
    if path.endswith(".toml"):
        text = re.sub(r"(?m)^\s*#\s?", "", text)
    return flat(text)


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
    # And the sweep protocol's QUOTATION of that sentence, which was two adapters behind the
    # sentence it quotes. Found by this round's disjunction sweep, in the document that tells the
    # next person how to run the sweep: step 3 is "read every sentence that states the count twice"
    # and it quoted its own example wrong. A quotation of a guarded site is an unguarded
    # restatement of the same fact — the defect this round found in `SELF_SITES`'s first row, in a
    # second file, on the same sentence.
    Site("packages/cdm/synapse_cdm/README.md", "the protocol's quotation of that sentence",
         r"both carry \"so that (?P<n>[a-z]+) adapters cannot grow (?P<n2>[a-z]+) slightly "
         r"different opinions\"",
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
    This closure stops the allowlist SHRINKING. It cannot notice a file OUTSIDE the list that starts
    stating an adapter count, because there is nothing here that reads the tree looking for one —
    the list is the input, so a site outside it is invisible by construction. Two counts have
    already escaped
    through that gap and both were found by a person reading rather than by a gate:

    * `MIGRATIONS.md`'s release condition 2 said "all ten harnesses" while twelve adapters shipped.
      The by-name patterns could not match it because the sentence says *harnesses*, not *adapters*;
    * `docs/docs/changelog.mdx`'s "twelve adapters have shipped so far" — which turned out to be
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
    swept = {
        "CONTRIBUTING.md",
        "README.md",
        "docs/docs/intro.mdx",
        "docs/docs/cdm/entity.mdx",
        "packages/cdm/synapse_cdm/README.md",
        "packages/cdm/synapse_cdm/__init__.py",
        "packages/cdm/synapse_cdm/symbology.py",
        "packages/cdm/synapse_cdm/version.py",
    }
    assert covered == swept, (
        f"the allowlist no longer matches the {len(swept)} files the roster sweeps have covered. "
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
     r"None of them is something the (?P<n>[a-z]+) checks"),
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
# Every shipped adapter but `pntmap` landed without a schema change — `pntmap` came with the schema,
# so it is not in that set. How many that is gets stated in prose, and the number is the whole
# argument for `PACKAGE_VERSION` and `SCHEMA_VERSION` being two numbers rather than one.
#
# WHERE it is stated is `NO_SCHEMA_CHANGE_SITES` below, and that tuple is the enumeration: nothing
# in this comment counts its rows or lists them a second time. The paragraph replaced here did
# both — it opened "Three documents state the eleven" over a list of exactly three — and it went
# false the moment the tuple widened, which is this module's own defect, committed in this module's
# own header, one roster along from the defect it was written to describe. A comment that counts the
# rows beneath it is a restated count like any other, and rule 7 of the sweep protocol applies to it
# too: cite the thing, do not re-state it.
#
# The rows do NOT go stale together, and that is what earned the widening. The four rows this tuple
# carried before that were all correct when it was written — checked by counting the section's
# bullets rather than assumed, which is why they were left alone instead of "fixed". The rest were
# added by one later sweep, in three different states at once: `packages/cdm/pyproject.toml`
# twice and `tests/test_cdm_packaging.py` once said NINE, `tests/test_cdm_changelog_claim.py` said
# EIGHT — three adapters behind — and `version.py`'s "would already be N minors apart" was RIGHT,
# one paragraph below a sentence this tuple already guarded, with nothing reading it. Same fact,
# same section, three wrong numbers and one correct-by-luck, none of them noticed by a green suite.
#
# That is the shape the sweep in this module exists for, one roster along: the adapter-count sweep
# above covers the count of SHIPPED adapters and could never see this one, because it is a count of
# a different set that happens to be spelled the same way.
#
# The section's bullets are the derivation. It is the same section every one of those sentences
# points at, so no new statement of the fact is introduced here — only a reading of the one that is
# already load-bearing.

#: The heading in `MIGRATIONS.md` whose bullets ARE this count.
NO_SCHEMA_CHANGE_HEADING = "### Adapters that landed with no schema change"

#: Where the count is stated, and the pattern that finds it. `docs/docs/changelog.mdx` is included
#: even though the page lists only nine of the twelve: `tests/test_cdm_changelog_claim.py` rules
#: that the page is a curated summary and that page-omits-an-entry is designed NOT to fail, so the
#: page's SENTENCE is a claim about the file's count and is checked against the file's count.
#:
#: Some of these sites are TEST modules and one is packaging metadata, which is not a category
#: error: an assertion message and a `pyproject.toml` comment are read by exactly the person the
#: number has to be right for, and neither is any less prose for living in a file the harness
#: executes. The assertion messages are the sharper case — one arguing the ruling from a number
#: three adapters stale weakens the ruling at the only moment anybody reads it.
NO_SCHEMA_CHANGE_SITES: tuple[tuple[str, str], ...] = (
    ("packages/cdm/synapse_cdm/version.py",
     r"it holds \*\*(?P<n>[a-z]+)\*\* entries"),
    ("packages/cdm/synapse_cdm/version.py",
     r"entries — (?P<n>[a-z]+) adapters, each of which"),
    # The counterfactual two paragraphs on: had the package been released before any of them, the
    # two numbers would already be this far apart. Correct when this row was added and unwatched,
    # which is the only reason it is a row rather than a repair.
    ("packages/cdm/synapse_cdm/version.py",
     r"The two numbers would already be (?P<n>[a-z]+) minors apart"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     r"\"Adapters that landed with no schema change\" is (?P<n>[a-z]+) entries long"),
    ("docs/docs/changelog.mdx",
     r"the two are allowed to diverge: (?P<n>[a-z]+) adapters have shipped so far"),
    # The packaging metadata states it twice in one sentence — the 94c000a half-edit shape, in a
    # file nothing here covered until this round. Read through `unwrapped()`, so these patterns are
    # anchored to the sentence and not to where the `#` block wraps.
    ("packages/cdm/pyproject.toml",
     r"section holds (?P<n>[a-z]+) entries"),
    ("packages/cdm/pyproject.toml",
     r"(?P<n>[a-z]+) releases' worth of shipped behaviour"),
    ("tests/test_cdm_packaging.py",
     r"MIGRATIONS\.md already lists (?P<n>[a-z]+) adapters that shipped without one"),
    ("tests/test_cdm_changelog_claim.py",
     r"(?P<n>[A-Z][a-z]+) adapters landed with no schema change"),
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
    at least one adapter is legitimately absent, because `pntmap` shipped WITH the schema.
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
    """Each stated count, against the bullets.

    These are not decorative. The number is the argument for two version numbers existing at all:
    twelve adapters' worth of shipped behaviour arriving at one unchanged `schema_version` is the
    evidence that the wire contract and the Python surface move independently. A wrong number here
    weakens the one claim `version.py` is written to make.
    """
    expected = len(adapters_that_landed_with_no_schema_change())
    text = unwrapped(path, (REPO / path).read_text())
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
    """The closure, so the collection cannot shrink by deletion.

    The failure this catches is not a wrong number — the parametrised test above catches those. It
    is a site quietly leaving the collection: someone rewords `version.py`'s sentence, the pattern
    stops matching, and the parametrised case for it fails loudly. Good. But someone REMOVING this
    module's entry for it, to make that failure go away, leaves the other sites guarded and that one
    free — and free is the state all of the documents added this round were already in.

    Written as a set of PATHS rather than a row count on purpose: rows get added, and a test that
    pinned their number would fail on every widening, which trains people to edit the expectation
    instead of reading it.
    """
    covered = {path for path, _ in NO_SCHEMA_CHANGE_SITES}
    assert covered == {
        "packages/cdm/synapse_cdm/version.py",
        "packages/cdm/synapse_cdm/MIGRATIONS.md",
        "docs/docs/changelog.mdx",
        "packages/cdm/pyproject.toml",
        "tests/test_cdm_packaging.py",
        "tests/test_cdm_changelog_claim.py",
    }, (
        f"the no-schema-change count is checked at {sorted(covered)}. Each of those documents "
        "states it for a different reader — the package's own argument for two version numbers, "
        "the changelog's, the public page's, the distribution metadata's, and the failure messages "
        "that argue the ruling to whoever broke it. Adding a site is fine; losing one is how this "
        "sweep's work gets undone")


# ------------------------------------- the same section, plus the release that came before it
#
# `version.py` runs the counterfactual one step past the count itself: had the package been released
# before any of those adapters, each would have been a package MINOR, and a scheme that derived one
# version number from the other could not have said so — every one of those releases would have gone
# out under the same label. That is a count of DISTRIBUTIONS rather than of adapters, and it is the
# section's bullets plus one, the release the counterfactual posits before any of them.
#
# It was right when it was written and it is not now, and the arithmetic is legible in the sentence
# it was written beside: the section held NINE bullets then, the same paragraph said "nine minors
# apart", and ten distributions is nine minors plus that first release. The bullets moved on. The
# statements of the count that this module already pins moved with the bullets; this one, sitting in
# the same paragraph as one of them, did not, because nothing read it. Same paragraph, same fact,
# one more statement of it — which is the disjunction protocol's whole argument for collecting
# rather than spot-fixing.

#: Where it is stated. Its own tuple rather than a row in `NO_SCHEMA_CHANGE_SITES`, because the
#: expected value is not that tuple's expected value and a row carrying a silent offset is worse
#: than a second row.
RELEASE_COUNT_SITES: tuple[tuple[str, str], ...] = (
    ("packages/cdm/synapse_cdm/version.py",
     r"ship (?P<n>[a-z]+) different distributions all labelled"),
)


def distributions_the_counterfactual_would_ship() -> int:
    """The section's bullets, plus the release the counterfactual puts before all of them.

    A named function rather than a `+ 1` at the assertion, because the plus-one IS the reading. The
    paragraph opens "Had this package been released before any of them", so that first release is
    one of the distributions a derived scheme would have had to label 1.0.0, and the adapters in the
    section are the others. Ruling the sentence to the bullet count alone would have made it say
    something the paragraph does not: that the first release is not one of the distributions.
    """
    return len(adapters_that_landed_with_no_schema_change()) + 1


@pytest.mark.parametrize("path,pattern", RELEASE_COUNT_SITES,
                         ids=[f"{p}::{i}" for i, (p, _) in enumerate(RELEASE_COUNT_SITES)])
def test_the_counterfactual_release_count_is_the_entries_plus_the_first_release(path, pattern):
    """The distribution count, against the section it is derived from.

    A pattern that stops matching is a FAILURE, for the reason the header gives — and here with one
    more reason: this site spent its whole life unread, so a row that silently stopped matching
    would put it back exactly where it started.
    """
    file = REPO / path
    assert file.exists(), f"{path} does not exist; this allowlist is stale"
    found = list(re.finditer(pattern, flat(file.read_text())))
    assert len(found) == 1, (
        f"{path}: the sentence this is anchored to matched {len(found)} times, expected 1.\n"
        f"  pattern: {pattern}\nRe-anchor it deliberately; do not delete the row"
    )
    stated = spelled(found[0].group("n"))
    expected = distributions_the_counterfactual_would_ship()
    assert stated == expected, (
        f"{path} says {found[0].group('n')!r} ({stated}) distributions and the counterfactual "
        f"would ship {expected}: {len(adapters_that_landed_with_no_schema_change())} adapters in "
        f"MIGRATIONS.md's no-schema-change section, each a package MINOR, plus the release the "
        f"sentence puts before all of them.\n  matched: {found[0].group(0)!r}\n"
        "This is the paragraph's third statement of one fact and the only one nothing read"
    )


# ============================================================== and now this module's own prose
#
# Every section above pins a count that lives in some other file. This module states counts too —
# the header quotes the double-count sentence verbatim, the check-count comment states how long
# `_COLUMNS` is, the `#:` note above `NO_SCHEMA_CHANGE_SITES` states both halves of what the curated
# page carries against what the file holds — and nothing read any of them. That is the same defect
# as every other one in this file, one file further in, and it is the structural one: the module that
# fails a build over a stale number elsewhere was the last place a stale number could sit and stay
# green.
#
# It had one. The header quotes `symbology.py`'s double-count sentence, and the quotation was two
# adapters behind the sentence it quotes — in the paragraph that names that sentence as THE shape
# this module exists to catch, and invisible to the row that pins the sentence itself, because a
# quotation of a site is not the site.
#
# The cheaper disposition first. Where the count sits somewhere Python can compute it — an assertion
# message, an f-string — it is now DERIVED and there is nothing left to guard: the closure above
# restated its own row count beside the literal set that decides it and now reads `len(swept)`, and
# the header counted the documents in `SITES` and now names `SITES`. What is left are
# counts in comments and docstrings, which cannot interpolate, so they are pinned the way every
# external site here is pinned: anchored to their own sentence, compared against a derivation.
#
# WHAT IS DELIBERATELY NOT PINNED, AND ON WHAT GROUND
# ---------------------------------------------------
# Most numbers in this file are history, and pinning them would falsify the record — the same ruling
# `HISTORICAL_SITE` carries for a changelog entry, applied to narrative instead. The
# classes below are exempt by structural location rather than by being unimportant:
#
# * **past-tense narrative about a named round, commit or release** — "stale by six adapters" about
#   the adapter #11 sweep; "21 for seven adapters, 28 for eight" about what `README.md` used to
#   state; "the count moved nine to ten at all eleven sites" about CAT034 Phase 2; and "`cat048`
#   had made it four" about the ICAO24 count before the SDK close-out sweep. Each was right at the
#   event it names, and ruling it to today's value would describe an event that did not happen;
# * **verbatim quotation of bytes as they stood before a named repair** — 94c000a's "seven adapters
#   cannot grow six slightly different opinions", and the sentence the SDK close-out sweep found in
#   `version.py`. These are exhibits, and an exhibit that gets updated stops being one.
#
# The second class gets a check rather than a promise, because an exhibit is exempt only while it is
# genuinely overtaken. `test_the_pre_repair_quotations_are_still_quotations_of_repaired_bytes`
# requires each quoted sentence to be ABSENT from the file it is quoted from: a quotation that
# matches the tree again is a live claim wearing an exemption written for a dead one, which is the
# failure `test_the_historical_statement_of_the_count_is_still_inside_the_history` catches in the
# other direction.
#
# THE GAP THAT STAYS OPEN, AND WHAT NOW STANDS WHERE IT WOULD BE CLOSED FROM
# --------------------------------------------------------------------------
# `SELF_SITES` is an allowlist and it has an allowlist's blind spot — the one recorded as debt in
# `test_the_allowlist_covers_every_site_the_sweep_had_to_fix`. A count added to this module's prose
# LATER is invisible to it, exactly as a document outside `SITES` stating the adapter count is
# invisible to that.
#
# The file-local form of the discovery sweep — every number in one file required to be pinned,
# derived, or exempt on a named ground — is what closes a gap of this shape, and it is no longer
# hypothetical. The last section of this module writes it, for `packages/cdm/synapse_cdm/README.md`,
# narrowed to numbers that grammatically qualify an adapter, a document or a site. It earned its
# place immediately: it found a stale count in the very document the sweep protocol is written down
# in, and two correctly-exempt sites that a hand sweep of the same file had walked straight past.
#
# It is still NOT written for THIS file, and the reason is a measurement rather than an
# unwillingness. The same shape finds several times as many hits here as it does in that README, and
# almost none of them would be pins. This module is the RECORD of every drift the sweep has ever
# repaired, so nearly every number in it is past-tense narrative, a pre-repair exhibit, or a
# quotation of a changelog entry — each needing its own exempt row carrying its own ground. That is
# the module header's objection to a general scanner arriving one file in: an exemption list that is
# almost the whole file does not gate the file, it restates it, and a restatement is the thing this
# module exists to refuse.
#
# So the gap stays open, and what it needs is now legible: a cheaper discriminator than grammar.
# Most likely the exempt GROUNDS themselves becoming structural — "inside a past-tense sentence",
# "inside a quoted span" — so the sweep decides them instead of a person asserting them row by row.
# Until something like that exists, this is debt and not an oversight. Nothing below covers it.

THIS_MODULE = pathlib.Path(__file__).resolve()


def own_prose() -> str:
    """This module's own source, comment markers stripped and whitespace collapsed.

    `flat()` alone is not enough here for the reason `unwrapped()` gives for `packages/cdm/
    pyproject.toml`, and with more force: most of this module's prose is a hard-wrapped `#` block, so
    collapsing whitespace alone leaves a `#` sitting mid-sentence at every wrap point, and a pattern
    written around it is anchored to where the comment happens to wrap rather than to what it says.
    Re-flowing a paragraph by one word would then break a row for no reason at all.
    """
    return flat(re.sub(r"(?m)^\s*#:?\s?", "", THIS_MODULE.read_text()))


class SelfSite:
    """One count stated in THIS module's prose, and the derivation that decides it.

    `derive` is a callable rather than a value because these are read at collection time and the
    derivations read the tree; a value captured at import would pin the number to whatever the tree
    looked like when pytest imported this file, which is the mistake `shipped_adapters()` documents.
    """

    def __init__(self, label: str, pattern: str, derive, *, groups: tuple[str, ...] = ("n",)):
        self.label = label
        self.pattern = pattern
        self.derive = derive
        self.groups = groups


#: This module's own count-bearing prose. Every pattern captures its number rather than spelling it,
#: which is what keeps a row from matching itself: the row's own pattern literal has `(?P<n>` where
#: the prose has a number word, so a search for the pattern finds the sentence and not the row.
SELF_SITES: tuple[SelfSite, ...] = (
    # The stale one, and the reason this section exists.
    SelfSite("the header's quotation of the double-count sentence",
             r"both carry the count TWICE in one clause — \"so that (?P<n>[a-z]+) adapters cannot "
             r"grow (?P<n2>[a-z]+) slightly different opinions\"",
             lambda: len(shipped_adapters()), groups=("n", "n2")),
    SelfSite("the check-count section's statement of how long _COLUMNS is",
             r"`harness\._COLUMNS` has (?P<n>[A-Z]+) entries",
             lambda: len(harness._COLUMNS)),
    SelfSite("the check-count closure's note on CONTRIBUTING.md's table",
             r"carries the (?P<n>[a-z]+)-row table",
             lambda: len(harness._COLUMNS)),
    SelfSite("what the curated page lists, on the page's side",
             r"the page lists only (?P<n>[a-z]+) of the",
             lambda: len(adapters_the_curated_page_lists())),
    SelfSite("what the curated page lists, on the file's side",
             r"the page lists only [a-z]+ of the (?P<n>[a-z]+):",
             lambda: len(adapters_that_landed_with_no_schema_change())),
    SelfSite("the no-schema-change count in the parametrised test's own docstring",
             r"(?P<n>[a-z]+) adapters' worth of shipped behaviour",
             lambda: len(adapters_that_landed_with_no_schema_change())),
    SelfSite("the changelog page's sentence, quoted in the recorded-debt note",
             r"\"(?P<n>[a-z]+) adapters have shipped so far\" — which turned out to be CORRECT",
             lambda: len(adapters_that_landed_with_no_schema_change())),
)

#: Sentences quoted here as they stood BEFORE a named repair, and the file each was repaired in.
#: Exempt from every count check above; the test below is what they pay for it.
PRE_REPAIR_QUOTATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("seven adapters cannot grow six slightly different opinions",
     ("packages/cdm/synapse_cdm/symbology.py", "docs/docs/cdm/entity.mdx")),
    ("ten adapters are shipped and harness-verified",
     ("packages/cdm/synapse_cdm/version.py",)),
)


def adapters_the_curated_page_lists() -> set[str]:
    """What `docs/docs/changelog.mdx` actually names, by the extractor that rules the page.

    Imported from `tests/test_cdm_changelog_claim.py` rather than reimplemented: that module owns
    the page's section heading and its adapter pattern, and a second extractor for the same set is a
    second thing to keep true. This module already borrows `tests/test_cdm_version_floor.py`'s
    virtualenv predicate in the check-count closure above on the same reasoning.

    It is also how "nine" was established rather than assumed. The `#:` note that states it is a
    claim about what a curated page carries, and reading a page by eye is how a curated page comes
    to be described by a number that was true of an earlier version of it.
    """
    from tests import test_cdm_changelog_claim as claim
    return set(claim.ADAPTER.findall(
        claim._section(claim.CHANGELOG.read_text(), claim.PAGE_HISTORY, r"^## ")))


def test_the_page_extraction_agrees_that_the_page_is_a_curated_subset():
    """The derivation, before anything is compared against it.

    An extractor that had stopped matching would return the empty set and the `#:` note's "nine"
    would fail against zero — a real failure with a message pointing at prose that is fine. And the
    relation the note asserts is a strict subset: a page that named everything the section holds
    would make "only" the wrong word, and `tests/test_cdm_changelog_claim.py` fails in that
    direction too, deliberately and with the instruction to re-rule rather than to trim the page.
    """
    listed = adapters_the_curated_page_lists()
    section = set(adapters_that_landed_with_no_schema_change())
    assert listed, (
        "the changelog page's adapter extraction found nothing. The `#:` note above "
        "NO_SCHEMA_CHANGE_SITES states how many of the section's entries that page carries, so an "
        "empty derivation fails that note for the wrong reason — check the page's heading first"
    )
    assert listed < section, (
        f"the page names {sorted(listed)} and the section holds {sorted(section)}. The note says "
        "the page lists SOME of them; if the page has caught up, the word 'only' is wrong and the "
        "note needs re-ruling rather than a new number"
    )


@pytest.mark.parametrize("site", SELF_SITES, ids=lambda s: s.label)
def test_every_count_this_module_states_about_the_tree_is_derived_from_the_tree(site):
    """This module's own prose, against the same derivations it holds other files to.

    The failure that earned this: the header's quotation of `symbology.py` said one number while the
    sentence it quotes said another, two adapters apart, and the row pinning that sentence could not
    see it. A quotation of a guarded site is an unguarded restatement of the same fact.
    """
    text = own_prose()
    found = list(re.finditer(site.pattern, text))
    assert len(found) == 1, (
        f"{site.label}: this module's own sentence matched {len(found)} times, expected 1.\n"
        f"  pattern: {site.pattern}\n"
        "A pattern that stops matching is a FAILURE here for the same reason it is everywhere else "
        "above — re-anchor it deliberately if the prose was rewritten; do not delete the row"
    )
    expected = site.derive()
    words = [found[0].group(g) for g in site.groups]
    assert len(set(w.lower() for w in words)) == 1, (
        f"{site.label}: this module states the count more than once in one sentence and the "
        f"statements disagree — {words}. That is the 94c000a shape, in the file that exists to "
        "catch it"
    )
    for word in words:
        assert spelled(word) == expected, (
            f"{site.label}: this module says {word!r} ({spelled(word)}) and the tree says "
            f"{expected}.\n  matched: {found[0].group(0)!r}\n"
            "This module's prose is prose like any other. It states counts about the tree, and "
            "until this row existed nothing read them"
        )


def test_the_self_guard_covers_every_count_this_module_states_about_the_tree():
    """The closure, in the one direction an allowlist can give itself: it cannot shrink.

    Same failure as every other closure here — a row deleted to make its failure go away leaves the
    site free, and free is the state every row here was in. It cannot notice a count added to this
    module later; that is the gap the section header states rather than implies.
    """
    covered = {site.label for site in SELF_SITES}
    assert covered == {
        "the header's quotation of the double-count sentence",
        "the check-count section's statement of how long _COLUMNS is",
        "the check-count closure's note on CONTRIBUTING.md's table",
        "what the curated page lists, on the page's side",
        "what the curated page lists, on the file's side",
        "the no-schema-change count in the parametrised test's own docstring",
        "the changelog page's sentence, quoted in the recorded-debt note",
    }, (
        f"the self-guard now covers {sorted(covered)}. Each of those is a count this module states "
        "about the tree — a quotation of a guarded sentence, a length, what a curated page carries, "
        "and the number the whole no-schema-change section exists to make. Adding a row is fine; "
        "losing one puts this module back where every file it guards started"
    )


@pytest.mark.parametrize("quotation,paths", PRE_REPAIR_QUOTATIONS,
                         ids=[q.split()[0] + "-" + q.split()[-1] for q, _ in PRE_REPAIR_QUOTATIONS])
def test_the_pre_repair_quotations_are_still_quotations_of_repaired_bytes(quotation, paths):
    """The exemption for exhibits, checked so that it cannot come to cover a live claim.

    An exhibit keeps its stale number because it is evidence of a repair, which is the ruling
    `HISTORICAL_SITE` carries for a changelog entry. That ruling holds only while the
    repair holds: if a file ever says again what its exhibit says it used to say, the exhibit has
    stopped being one and the sentence is a live count wearing a dead exemption.

    Occurrence count rather than membership, because the string is in the tuple above: a row whose
    prose had been deleted would otherwise satisfy this test against itself.
    """
    mine = own_prose()
    assert mine.count(quotation) >= 2, (
        f"{quotation!r} appears {mine.count(quotation)} time(s) in this module — the row above and "
        "nothing else, so the prose that quoted it is gone. Drop the row with it; an exemption "
        "covering no site reads as a live ruling"
    )
    for path in paths:
        file = REPO / path
        assert file.exists(), f"{path} does not exist; this exemption is stale"
        assert quotation not in flat(file.read_text()), (
            f"{path} says {quotation!r} again, which this module quotes as PRE-repair bytes. Either "
            "the repair was reverted, or the exhibit is now a live claim carrying an exemption "
            "written for a historical one — the same spread "
            "`test_the_historical_statement_of_the_count_is_still_inside_the_history` refuses"
        )


# ================== the package README's own count-bearing prose, swept FILE-LOCALLY
#
# Every section above is an allowlist, and each one records the same blind spot: it cannot find a
# site nobody has added to it. `SELF_SITES` states the file-local form of the closure that would
# fix that — every number in one file required to be pinned, derived, or exempt on a named ground —
# and states that it is not written. This section writes it, for ONE file and inside ONE
# fact-class, which is what makes the exemption list finite instead of larger than the sweep it
# replaces.
#
# The file is `packages/cdm/synapse_cdm/README.md`, which is where the roster sweep protocol is
# WRITTEN DOWN. That is the reason it goes first: the document instructing the next person to check
# every site that states a number was itself carrying a stale one. Step 2 worked the divergence
# between the two pair formulas at a roster of TEN — "At ten it is 90 against 45" — two adapters
# after the roster left ten, in the step whose whole subject is that a restated count decays. Both
# of its numbers were wrong, and so was the roster word it hung them on.
#
# THE SHAPE, AND WHY IT IS NARROW
# -------------------------------
# A number word DIRECTLY qualifying `adapter`, `document` or `site`. That is the roster fact-class
# and almost nothing else: it does not match "two altitudes that are two different measurements",
# "the six known gaps", or "ten such sentinels", which is the objection the module header raises to
# a general scanner and which stands. It is step 1 of the sweep protocol — grep every spelled
# number near the word "adapter" — narrowed from the tree to one file and from proximity to
# grammar, so that the result is small enough to adjudicate one hit at a time.
#
# It found two sites a hand sweep of this file had already missed — "Two documents disagreed" and
# "Two sites this round" — both correctly exempt, and both invisible to a reader who was looking
# for the word "adapters".
#
# WHAT THE SHAPE STILL CANNOT SEE, STATED RATHER THAN IMPLIED
# -----------------------------------------------------------
# A count that states the roster without naming it. Step 2's repaired sentence is caught at all
# only because it was rewritten to say "adapters"; the two DIGITS in it are matched by nothing here
# and are pinned by a row instead. Grammar is a proxy for subject matter and a proxy has a gap. The
# row is the belt; this sweep is the braces. Neither is quoted back here — a quotation of a guarded
# site is an unguarded restatement of it, which is the defect `SELF_SITES` above exists for.

PKG_README = "packages/cdm/synapse_cdm/README.md"

#: The number words this repository spells counts with, longest first so a hyphenated compound is
#: preferred over its own first half.
_NUMBER_WORD = "|".join(sorted([*_UNITS, *_TENS], key=len, reverse=True))

#: A number DIRECTLY qualifying one of the three nouns the roster fact-class is stated in.
COUNTED_NOUN = re.compile(
    rf"(?<![\w-])(?:{_NUMBER_WORD})(?:-(?:{_NUMBER_WORD}))?[ -](?:adapters?|documents?|sites?)"
    r"(?![\w])",
    re.I,
)


def stated(word: str) -> int:
    """A count as this repository writes it: spelled, or in digits.

    `spelled()` alone is not enough here. The pair arithmetic is written in DIGITS at every site
    that works it — "72 against 36" is how the sweep protocol states the divergence it found —
    because those numbers are arithmetic rather than prose, while the roster they are derived from
    is spelled. One sentence, both conventions.
    """
    return int(word) if word.isdigit() else spelled(word)


class ReadmeSite:
    """One count-bearing sentence in the package README, and a derivation per number it states."""

    def __init__(self, label: str, pattern: str, derivations: dict):
        self.label = label
        self.pattern = pattern
        self.derivations = derivations


def _roster() -> int:
    return len(shipped_adapters())


#: The counts this file states as live claims, each pinned to the structure that decides it.
PKG_README_SITES: tuple[ReadmeSite, ...] = (
    # Step 2 works the divergence between the two pair conventions at TODAY'S roster, and states
    # all three numbers. It is pinned to the roster rather than re-hardcoded, so the next adapter
    # moves it or fails the build — which is what the step it lives in tells the reader to do.
    #
    # `N×(N−1)` is derived here even though `pairs()` is the convention this repository harmonised
    # on. The sentence's whole subject is that the two formulas disagree, so the rejected one is
    # load-bearing prose and has to be as right as the accepted one.
    ReadmeSite(
        "step 2's worked divergence between the two pair conventions",
        r"At today's (?P<n>[a-z]+) adapters it is (?P<ordered>\d+) against (?P<unordered>\d+)\.",
        {
            "n": _roster,
            "ordered": lambda: _roster() * (_roster() - 1),
            "unordered": lambda: pairs(_roster()),
        },
    ),
    # The fourth register entry's reach: every adapter that declares an egress direction, which
    # is what makes `roundtrip` reachable at all. The number is the whole point of the entry — a
    # wheel-only conformance claim is short by exactly this many adapters — and it moves on the
    # next adapter like any roster count, so it is derived rather than written.
    ReadmeSite(
        "the fourth register entry's count of adapters with an egress direction",
        r"affected — (?P<n>[a-z]+) of the (?P<roster>[a-z]+) shipped adapters, every one of which",
        {
            "n": lambda: len([c for c in shipped_adapters().values()
                              if c.direction != "ingest"]),
            "roster": _roster,
        },
    ),
    # How many documents the allowlist above covers, stated in the paragraph that introduces it.
    # Derived from `SITES` itself, so widening the allowlist moves the prose or fails.
    ReadmeSite(
        "the allowlist's own document count",
        r"now pins the sites in (?P<n>[a-z]+) documents",
        {"n": lambda: len({site.path for site in SITES})},
    ),
)

#: Numbers in this file that qualify one of those nouns and are NOT live claims about today's
#: roster, each quoted as it stands with the ground it is exempt on. The grounds are the ones the
#: sweep protocol itself names in its step 6, plus the two the module header rules on above:
#: past-tense narrative, the "of the day" marker, a changelog entry, a pre-repair quotation — and
#: the one grammar alone cannot separate, a singular referent that is not a count at all.
PKG_README_EXEMPT: tuple[tuple[str, str], ...] = (
    ("it is the one adapter whose egress format has nowhere to park a field it cannot map",
     "singular referent, not a count — 'the one adapter' names AIS, it does not tally adapters"),
    ("they are here rather than in one adapter's notes",
     "singular referent, not a count"),
    ("it had been undercounting itself by one adapter since adapter #6",
     "past-tense narrative about a named drift, and 'one adapter' is its unit rather than a total"),
    ("folklore that produced a nine-adapter sweep reporting nine greens with one of them vacuous",
     "past-tense narrative about a specific past run — step 6's first exempt class"),
    ("which still said \"five adapters means ten translations\"",
     "verbatim quotation of pre-repair bytes in `synapse_cdm/__init__.py`; see "
     "PKG_README_PRE_REPAIR, which requires it to be absent from that file"),
    ("four adapters later",
     "past-tense narrative about how far that site had drifted by the adapter #11 sweep"),
    ("Two documents disagreed on whether it is",
     "past-tense narrative about the disagreement the sweep found and harmonised"),
    ("which for the nine adapters of the day was 72 against 36",
     "the 'of the day' marker — the convention step 6 names for a past count in the present tense"),
    ("half-updated — \"seven adapters cannot grow six\"",
     "verbatim quotation of the bytes 94c000a repaired; see PKG_README_PRE_REPAIR"),
    ("argued the 1.0.0-not-0.x ruling from \"ten adapters are shipped",
     "verbatim quotation of the bytes the SDK close-out sweep repaired in `version.py`; see "
     "PKG_README_PRE_REPAIR"),
    ("and `stanag4676.py` said three adapters share the `ICAO24` source-id namespace",
     "past-tense narrative about what that file said before the SDK close-out sweep"),
    ("both describe \"a gate sweep over all nine adapters\"",
     "quotation of a past-tense narrative in `harness.py` and `adapter.py` — the example step 6 "
     "gives for its own first exempt class"),
    ("where \"now serves three adapters\" means at that release",
     "quotation of a changelog entry — step 6's second exempt class, and the one "
     "`HISTORICAL_SITE` above rules on in the file it lives in"),
    ("Two sites this round said what gap 1's table already said",
     "past-tense narrative about what that round found"),
    ("`ais.py` at \"four keys across two adapters\"",
     "verbatim quotation of pre-repair bytes in `ais.py`; see PKG_README_PRE_REPAIR"),
)

#: Sentences this file quotes as they stood BEFORE a named repair, and the file each was repaired
#: in. Same discipline as `PRE_REPAIR_QUOTATIONS` above, applied to the README's exhibits rather
#: than to this module's: an exhibit is exempt only while it is genuinely overtaken.
PKG_README_PRE_REPAIR: tuple[tuple[str, str], ...] = (
    ("five adapters means ten translations", "packages/cdm/synapse_cdm/__init__.py"),
    ("seven adapters cannot grow six", "packages/cdm/synapse_cdm/symbology.py"),
    ("seven adapters cannot grow six", "docs/docs/cdm/entity.mdx"),
    ("ten adapters are shipped", "packages/cdm/synapse_cdm/version.py"),
    ("four keys across two adapters", "packages/cdm/synapse_cdm/adapters/ais.py"),
)


def pkg_readme() -> str:
    return flat((REPO / PKG_README).read_text())


@pytest.mark.parametrize("site", PKG_README_SITES, ids=lambda s: s.label)
def test_every_live_count_in_the_package_readme_is_derived_from_the_tree(site):
    """Each live count in the sweep protocol's own document, against what decides it.

    The failure this earned: step 2 stated the divergence at a roster of ten while twelve shipped,
    inside the step that tells the reader to check the arithmetic at every site that states a
    number. A pattern that stops matching is a FAILURE, for the reason the header gives.
    """
    text = pkg_readme()
    found = list(re.finditer(site.pattern, text))
    assert len(found) == 1, (
        f"{site.label}: the sentence this is anchored to matched {len(found)} times, expected 1.\n"
        f"  pattern: {site.pattern}\n"
        "Re-anchor it deliberately if the sentence was rewritten; do not delete the row"
    )
    for group, derive in site.derivations.items():
        word = found[0].group(group)
        expected = derive()
        assert stated(word) == expected, (
            f"{site.label}: {PKG_README} states {word!r} ({stated(word)}) for {group!r} and the "
            f"tree gives {expected}.\n  matched: {found[0].group(0)!r}\n"
            "This is the document the roster sweep is written down in. A stale number here is the "
            "instructions being wrong about the thing they instruct"
        )


def test_the_package_readme_states_no_adapter_count_this_module_neither_pins_nor_exempts():
    """The file-local discovery sweep, in the direction an allowlist cannot give itself.

    Every other closure here can only stop its list SHRINKING. This one reads the file and requires
    each hit to be accounted for, so a count ADDED to this README later fails a build until someone
    rules it — which is the debt `test_the_allowlist_covers_every_site_the_sweep_had_to_fix` records
    and `SELF_SITES` restates, closed for one file inside one fact-class.

    Accounted for means one of three things, and the third is why this is affordable: pinned by a
    row above, pinned by an existing `SITES` row for this path, or exempt on a ground stated beside
    the quotation. An exemption whose quotation has left the file fails too — an exemption covering
    no site reads as a live ruling, which is what
    `test_the_historical_statement_of_the_count_is_still_inside_the_history` refuses one section up.
    """
    text = pkg_readme()
    covered: list[tuple[int, int]] = []

    for site in PKG_README_SITES:
        found = list(re.finditer(site.pattern, text))
        assert len(found) == 1, f"{site.label}: matched {len(found)} times, expected 1"
        covered.append(found[0].span())

    for site in SITES:
        if site.path == PKG_README:
            covered.append(site.match().span())

    for quotation, ground in PKG_README_EXEMPT:
        assert ground.strip(), f"{quotation!r} is exempt on no stated ground, which is not an exemption"
        spans = [m.span() for m in re.finditer(re.escape(quotation), text)]
        assert spans, (
            f"{PKG_README} no longer contains {quotation!r}, which this list exempts on the ground "
            f"{ground!r}. Drop the row with the prose; an exemption pointing at nothing reads as a "
            "live ruling on a site that is gone"
        )
        covered.extend(spans)

    strays = []
    for m in COUNTED_NOUN.finditer(text):
        if not any(lo <= m.start() and m.end() <= hi for lo, hi in covered):
            strays.append(f"{m.group(0)!r} in …{text[max(0, m.start() - 90):m.end() + 90]}…")
    assert not strays, (
        f"{PKG_README} states {len(strays)} count(s) that nothing here pins and nothing here "
        "exempts:\n  " + "\n  ".join(strays) + "\n"
        "Rule each one: pin it to a derivation in PKG_README_SITES if it is a live claim about "
        "today's tree, or add it to PKG_README_EXEMPT with the ground it is exempt on. Leaving it "
        "unruled is the state every site in this module was in before it drifted"
    )


@pytest.mark.parametrize("quotation,path", PKG_README_PRE_REPAIR,
                         ids=[f"{q.split()[0]}-{p.rsplit('/', 1)[-1]}"
                              for q, p in PKG_README_PRE_REPAIR])
def test_the_readmes_pre_repair_quotations_are_still_quotations_of_repaired_bytes(quotation, path):
    """The README's exhibits, held to the discipline `PRE_REPAIR_QUOTATIONS` holds this module's.

    The README quotes sentences as they stood before a repair, and each carries a number today's
    roster has overtaken. They are exempt from every count check for the reason an exhibit always
    is — an exhibit that gets updated stops being one — and that ruling holds only while the repair
    does. If the source file ever says again what the README says it used to say, the exhibit has
    become a live count wearing a dead exemption.
    """
    assert quotation in pkg_readme(), (
        f"{PKG_README} no longer quotes {quotation!r}. Drop the row with the prose rather than "
        "leaving it pointing at nothing"
    )
    file = REPO / path
    assert file.exists(), f"{path} does not exist; this exemption is stale"
    assert quotation not in flat(file.read_text()), (
        f"{path} says {quotation!r} again, which {PKG_README} quotes as PRE-repair bytes. Either "
        "the repair was reverted, or the exhibit is now a live claim carrying an exemption written "
        "for a historical one"
    )


# ------------------------------------------- a count whose file set is the INDEX, not an allowlist
#
# RULE 8 OF THE SWEEP PROTOCOL, AND THE ONLY CHECK IN THIS MODULE WHOSE FILE SET IS `git ls-files`.
#
# WHY IT IS HERE, WHICH IS A REPEAT RATHER THAN A DRIFT. Two consecutive commits asserted an
# untouchable — "35" occurrences of one phrase across the repository — and each round's actual
# derivation was a `grep` over a hand-written list of extensions (`*.md`, `*.py`, `*.json`), which
# EXCLUDES `docs/docs/changelog.mdx` and yields 34. **The assertion was right and the derivation was
# wrong**, twice, identically, in two rounds that had each just diagnosed the same class of defect
# one layer over. That arrangement is worse than a stale number: nothing failed, so the wrong method
# was inherited rather than repaired, and the next person to re-derive it would have got 34 and
# "corrected" a correct claim.
#
# WHAT THE REPAIR IS. The file set is the git index and there is no extension list anywhere. One
# command, for a human:
#
#     git ls-files -z | xargs -0 grep -Ioh '1\.1\.0 candidate' | wc -l    # 35
#
# and one implementation, `occurrences_over_tracked_files()` below, which the guard CALLS. There is
# no second derivation for the check to disagree with, which is the whole point: a count whose
# derivation is a command somebody retypes each round is a count that will be re-derived
# differently.
#
# THE PHRASE IS BUILT RATHER THAN WRITTEN, and that is not a flourish. A module that spelled it out
# in a docstring or an assertion message would be counted by its own derivation and would move the
# number it exists to pin — the same reason `packages/cdm/synapse_cdm/README.md`'s rule 8 refers to
# it only as a regex. `PINNED_PHRASE` is assembled from parts, and
# `test_this_module_does_not_spell_the_phrase_it_counts` asserts the module's own source contains no
# literal occurrence, so the trap is closed rather than avoided by care.

#: Assembled, never written out. See the note above.
PINNED_PHRASE = "1.1.0" + " " + "candidate"

#: What the derivation yields today. THE ONE NUMBER, and it is here rather than in prose because
#: prose that spelled the phrase would break its own count — which is the constraint that made this
#: fact awkward to state anywhere at all, and is worth recording as the reason it lives in a guard.
PINNED_PHRASE_OCCURRENCES = 35


def tracked_text_files() -> list[pathlib.Path]:
    """Every file `git` tracks that is text. The file set, with no extension list in it.

    A file with a NUL in its first 8 KiB is skipped as binary, which is `grep -I`'s own rule and is
    the only filtering here — and it is a property of the bytes rather than of a suffix, so it
    cannot go stale the way a remembered list of extensions does.
    """
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout
    out = []
    for name in listed.split("\0"):
        if not name:
            continue
        path = REPO / name
        try:
            head = path.open("rb").read(8192)
        except OSError:
            continue
        if b"\0" in head:
            continue
        out.append(path)
    return out


def occurrences_over_tracked_files(phrase: str) -> dict[str, int]:
    """`{path: count}` for every tracked text file containing `phrase`. THE derivation."""
    found: dict[str, int] = {}
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count = text.count(phrase)
        if count:
            found[str(path.relative_to(REPO))] = count
    return found


def test_the_pinned_phrase_count_is_what_the_derivation_yields_over_the_index():
    """The check RUNS the derivation, so the two cannot disagree — there is only one of them.

    A failure here is not necessarily a defect: adding a genuine new occurrence of the phrase is
    ordinary work, and the fix is to move `PINNED_PHRASE_OCCURRENCES` in the same commit. What the
    guard prevents is the state that actually occurred twice — a number asserted from memory while
    the method that would have produced it produces a different one.
    """
    per_file = occurrences_over_tracked_files(PINNED_PHRASE)
    total = sum(per_file.values())
    assert total == PINNED_PHRASE_OCCURRENCES, (
        f"the derivation over `git ls-files` yields {total} and this module pins "
        f"{PINNED_PHRASE_OCCURRENCES}. Per file: {per_file}. If an occurrence was added or removed "
        "on purpose, move the constant in the same commit; if not, this is the drift the constant "
        "exists to catch"
    )


def test_the_derivations_file_set_is_the_index_and_not_a_list_of_extensions():
    """The property the two mis-derivations lacked, asserted rather than described.

    Both of them scoped a `grep` to `*.md`, `*.py` and `*.json`, and the one occurrence they missed
    is in an `.mdx` file. So the assertion is that the derivation's file set REACHES a suffix such a
    list would not, and that it reaches it because `git` tracks it rather than because anybody
    remembered it.
    """
    per_file = occurrences_over_tracked_files(PINNED_PHRASE)
    suffixes = {pathlib.Path(p).suffix for p in per_file}
    assert ".mdx" in suffixes, (
        f"no `.mdx` file carries the phrase any more; the suffixes are {sorted(suffixes)}. This "
        "test's subject is that the derivation is not extension-scoped, and the evidence for that "
        "was an occurrence in docs/docs/changelog.mdx that two extension-scoped greps missed. If "
        "the occurrence moved, re-anchor this on whichever suffix an extension list would omit — "
        "and if there is no longer such a suffix, say so here rather than deleting the check"
    )
    extension_scoped = sum(n for p, n in per_file.items()
                           if pathlib.Path(p).suffix in {".md", ".py", ".json"})
    assert extension_scoped < PINNED_PHRASE_OCCURRENCES, (
        "an `*.md`/`*.py`/`*.json` grep now yields the same total as the index does, so this "
        "check has stopped being able to tell the two apart. That is not a pass — re-anchor it"
    )


def test_this_module_does_not_spell_the_phrase_it_counts():
    """The trap closed rather than avoided by care.

    This module is tracked, so a literal occurrence of the phrase in its own source — in a
    docstring, a comment or an assertion message — would be counted by its own derivation and would
    move the number it exists to pin. `PINNED_PHRASE` is assembled from parts for that reason, and
    this asserts nobody has since written it out while explaining it.
    """
    source = pathlib.Path(__file__).read_text()
    assert PINNED_PHRASE not in source, (
        "this module's source now contains a literal occurrence of the phrase it counts, so the "
        "derivation counts this file too and the pinned total is one higher than the tree's real "
        "one. Refer to it as a regex or assemble it from parts, as PINNED_PHRASE does"
    )
    readme = (PKG / "README.md").read_text()
    assert PINNED_PHRASE not in readme, (
        "the module README's sweep rule 8 now spells out the phrase it describes, which changes "
        "the count that rule exists to pin. It refers to it as a regex for exactly that reason"
    )


# ------------------------------------------------- the package README's roster TABLE, as a set
#
# ADDED BY THE 1.2.0 RELEASE AUDIT, AND IT WAS ADDED BECAUSE IT WAS ALREADY WRONG.
#
# `packages/cdm/synapse_cdm/README.md` carries a "Shipped so far" table with one row per adapter,
# and adapter #10 shipped on 2026-08-26 without a row. Nothing failed. Every count in that file was
# guarded — the module has said "thirteen integration adapters are shipped" since that round — and
# the TABLE two lines below the sentence still listed twelve. That is this module's own subject
# arriving one level down: a count is a fact stated in prose and checked, and a table is a fact
# stated in prose and not.
#
# The release audit found it by enumerating registry names per file rather than by reading, which
# is the only way it could have been found — the row is absent, and an absence has nothing for a
# `grep` of the previous count to match. Recorded here so the next roster change moves it.
#
# WHY THIS IS A SET COMPARISON AND NOT A COUNT. A count would pass on a table that lists twelve
# adapters and names one of them twice, and it would give no clue which name is missing. Both
# directions, both named in the message.

PKG_README_PATH = "packages/cdm/synapse_cdm/README.md"

#: A roster row: `| [`name`](adapters/module.py) 1.0.0 | direction | prose |`.
ROSTER_ROW = re.compile(r"^\|\s*\[`([a-z0-9_]+)`\]\(adapters/[a-z0-9_]+\.py\)", re.MULTILINE)


def test_the_package_readmes_roster_table_is_the_registry():
    """Every shipped adapter has a row, and every row is a shipped adapter.

    The table is the first thing a reader of the installed package sees, and it ships INSIDE the
    wheel — so a missing row is not a documentation slip, it is the distribution under-reporting
    what it contains to the person who just installed it.
    """
    text = (REPO / PKG_README_PATH).read_text()
    tabled = set(ROSTER_ROW.findall(text))
    assert tabled, (
        f"no roster rows matched in {PKG_README_PATH}. If the table's shape changed, re-anchor "
        "ROSTER_ROW deliberately — a sweep that matches nothing reports clean, which is the "
        "failure this whole module is about"
    )
    shipped = set(shipped_adapters())
    missing = sorted(shipped - tabled)
    unknown = sorted(tabled - shipped)
    assert not missing and not unknown, (
        f"{PKG_README_PATH}'s roster table and the registry disagree.\n"
        f"  shipped but not in the table: {missing}\n"
        f"  in the table but not shipped: {unknown}\n"
        "This table ships inside the wheel, so a missing row under-reports the distribution to "
        "the reader most likely to trust it. `stanag4609` was missing for one release and the "
        "adapter COUNT beside the table was correct throughout, which is why the check is on the "
        "rows and not on their number"
    )


def test_the_roster_table_and_the_shipped_adapter_sentence_agree():
    """The sentence and the table are two statements of one fact, three lines apart.

    That proximity is exactly what made the drift invisible: a reader checking the count reads the
    sentence, and a reader checking the roster reads the table, and for one release they said
    different things. The count has its own row in `SITES` above; this asserts the two agree with
    each other as well as each with the registry.
    """
    text = (REPO / PKG_README_PATH).read_text()
    tabled = ROSTER_ROW.findall(text)
    assert len(tabled) == len(set(tabled)), (
        f"the roster table lists a name twice: "
        f"{sorted(n for n in set(tabled) if tabled.count(n) > 1)}"
    )
    match = re.search(r"(?P<n>[A-Za-z]+) integration adapters are shipped:", flat(text))
    assert match, "the shipped-adapter sentence has moved; SITES has the anchored form"
    assert spelled(match.group("n")) == len(tabled), (
        f"{PKG_README_PATH} says {match.group('n')!r} integration adapters are shipped and its "
        f"own table three lines later has {len(tabled)} rows"
    )


# ==================== the adapter count over the WHOLE INDEX, which is the recorded debt closed
#
# THE DEBT, IN THE WORDS IT WAS RECORDED IN. `test_the_allowlist_covers_every_site_the_sweep_had_
# to_fix` says: "A discovery sweep would close this: scan the tree for a spelled number adjacent to
# 'adapter', and require each hit to be in the allowlist, to name its subset, or to equal the
# registry. It is not written." This section writes it.
#
# WHAT MADE IT WORTH WRITING NOW, WHICH IS A MISS AND NOT A TIDY-UP. The 1.2.0 round repaired the
# adapter count in `packages/cdm/synapse_cdm/README.md` and in `PUBLICATION.md` and guarded both.
# The ROOT `README.md` shipped that same round saying "Thirteen integration adapters are shipped"
# in its intro and "the twelve shipped adapters" under Using it — one file, one fact, two numbers,
# live at HEAD. Six more sites were in the same state and nothing was looking at any of them:
# `docs/docs/intro.mdx`, `packages/cdm/pyproject.toml` twice, `synapse_cdm/MIGRATIONS.md`'s release
# condition 2, `synapse_cdm/adapter.py`, and — a roster away — `tests/test_cdm_pins.py`'s floor.
#
# The finding is the shape of the miss rather than any one of those numbers: **last round's guards
# covered the sites that had FAILED, not the fact.** Every row in `SITES` is a place a count once
# went wrong. A fact is not a list of places, and a guard built by repair has exactly the coverage
# its repair history bought it — which is why the seven sites above could sit at HEAD, in files the
# release ships, through a round whose subject was this very count.
#
# HOW THIS DIFFERS FROM EVERY ALLOWLIST ABOVE. It does not enumerate sites. It derives the roster
# ONCE, sweeps `git ls-files`, and rules every hit by comparison: a hit that STATES the roster
# count needs no row and can never go stale silently, because the next adapter fails it. Only a hit
# that states something else needs a row, and `TREE_EXEMPT` is therefore bounded by the number of
# NON-roster adapter counts in the tree rather than by the number of adapter counts — which is what
# keeps the exemption list from becoming the restatement the module header refuses.
#
# THE TWO NARROWINGS, BOTH MEASURED RATHER THAN ASSERTED
# ------------------------------------------------------
# 1. GRAMMAR. A number qualifying `adapters` or `harnesses`, with at most two words between. That
#    is `COUNTED_NOUN`'s discipline widened by the adjectives this fact is actually written with —
#    "twelve SHIPPED adapters", "thirteen INTEGRATION adapters" — and `harnesses` is here because
#    the count escaped through that word once already: `MIGRATIONS.md`'s release condition 2 said
#    "all ten harnesses" while twelve adapters shipped, and the by-name patterns could not see it.
# 2. MAGNITUDE. `ROSTER_FLOOR`. Below it the sweep does not look, and the ground is a measurement
#    over this tree: numbers under five qualifying `adapters` are relational without exception —
#    "two adapters agree", "one adapter's bug", "three adapters map FAKER" — and the roster has
#    never been stated below five, the lowest being `__init__.py`'s repaired "five adapters means
#    ten translations". A floor is a gap and this one is named rather than implied: a roster of
#    four would be invisible here, and a roster of four is a tree with nine adapters deleted.
#
# TWO FILES ARE OUT OF THE SWEEP AND BOTH GROUNDS ARE ALREADY WRITTEN ABOVE, not invented here:
# `packages/cdm/synapse_cdm/README.md` is swept file-locally by the section before this one, at a
# finer grain than this can manage, and sweeping it twice would put one fact under two lists.
# THIS module is excluded on the measurement its own section header states — nearly every number in
# it is past-tense narrative or a pre-repair exhibit, so a sweep of it would be an exemption list
# almost as long as the file. That gap stays open, and it stays recorded where it was recorded.

#: The lowest number this sweep will look at. See narrowing 2 above.
ROSTER_FLOOR = 5

#: A number qualifying the roster's noun, spelled or in digits. See narrowing 1 above.
ROSTER_COUNT = re.compile(
    rf"(?<![\w-])(?P<num>{_NUMBER_WORD}|\d{{1,3}})(?:[ -][a-z]+){{0,2}}[ -](?:adapters|harnesses)"
    r"(?![\w])",
    re.I,
)

#: Comment and bullet markers, stripped before flattening so a pattern is anchored to the sentence
#: rather than to where its comment block happens to wrap. `unwrapped()`'s reasoning, generalised
#: past `.toml` because this sweep reads `.py`, `.mjs` and `.md` in the same pass. `\*` requires a
#: following space so a markdown bold marker (`**Eight adapters`) is left alone.
COMMENT_MARKER = re.compile(r"(?m)^[ \t]*(?:#:|#|//|\*(?= ))[ \t]?")

#: Swept elsewhere, at a finer grain or not at all. Grounds in the section header above.
SWEEP_EXCLUDED = {
    "packages/cdm/synapse_cdm/README.md": "swept file-locally by PKG_README_SITES above",
    "tests/test_cdm_prose_counts.py": "ruled out by this module's own SELF_SITES header, on a "
                                      "measurement rather than an unwillingness",
}

#: Every adapter count in the tree that is NOT the roster, quoted as it stands with its ground.
#: A row here is a claim that the number means something other than "how many adapters ship", and
#: the grounds are the ones this module already rules on: a NAMED SUBSET, PAST-TENSE NARRATIVE
#: about a specific round or run, a VERBATIM QUOTATION of pre-repair or past output, or a count
#: PINNED BY ANOTHER SECTION of this module — which is a cross-reference, not a second guard.
TREE_EXEMPT: tuple[tuple[str, str, str], ...] = (
    # --- named subsets: a count of something narrower than the roster, and it says which ---
    ("PUBLICATION.md", "**Ten adapters, 298 fixture verdicts, 0 failed.**",
     "named subset — the roster OF 1.0.0, measured off the index. MIGRATIONS.md's stale-count "
     "sweep ruled explicitly that updating it would falsify the record"),
    ("PUBLICATION.md", "ten adapters, 298 fixture verdicts, the roster OF 1.0.0",
     "the same measurement, quoted one block later and carrying its own subset marker"),
    ("PUBLICATION.md", "12 adapters, 776 fixture verdicts",
     "the gated job's own output for the 1.1.0 run, transcribed. A record of what a run printed"),
    ("PUBLICATION.md", "all **twelve adapters replayed from the packaged fixtures — 388",
     "the 1.1.0 install measurement, which is a fact about 1.1.0 and not about the tree"),
    ("PUBLICATION.md", "**13 adapters**, `stanag4609` among them at `1.0.0`, fixtures resolving "
     "to `klv`",
     "the 1.2.0 release-verification block's own `--list-adapters` output, transcribed. A record "
     "of what that artefact printed, and it does not move when the tree does"),
    ("PUBLICATION.md", "**13 adapters**, unchanged from 1.2.0, `stanag4609` at `1.0.0` with "
     "fixtures in `klv`",
     "the 1.2.1 release-verification block's own output, same ground as the 1.2.0 row above"),
    ("PUBLICATION.md", "**13 adapters**, unchanged from 1.2.1, `stanag4609` at `1.0.0` with "
     "fixtures in `klv`",
     "the 1.3.0 release-verification block's own output, same ground again. THREE RELEASES NOW "
     "SHARE THIS SHAPE, which is why they are three rows and not one: each names the release it "
     "measured, and a single row quoting only the common prefix would exempt a future stale one"),
    ("PUBLICATION.md", "The intro serves thirteen adapters with STANAG 4609 named and the pair "
     "arithmetic reading seventy-eight and thirteen",
     "a record of what a PAST DEPLOYMENT served, byte-compared against a named build. Updating it "
     "would assert that the deployment served something it did not"),
    # RETIRED IN THE 1.4.0 ROUND, and the retirement is the interesting half. This exempted
    # RELEASE_NOTES.md's "across the thirteen adapters 1.3.0 shipped" — a named subset that had to
    # be exempt because the notes described an artefact smaller than the tree. The 1.4.0 notes
    # describe an artefact that IS the tree: fourteen adapters, 432 verdicts, no row marked as
    # postdating the release. So the sentence needs no exemption, and
    # `test_every_tree_exemption_still_points_at_prose_that_is_there` went red on the leftover row
    # the moment the notes were rewritten — which is the guard doing exactly its job. An exemption
    # outliving its prose is a licence nobody is using, and the next stale figure that lands on
    # those bytes would inherit it.
    ("packages/cdm/synapse_cdm/fixtures/stanag4586/spec/stanag4586_pin.json",
     "thirteen SHIPPED adapters occupied fourteen ordinals",
     "named subset and a PAST STATE — the roster as it stood before `stanag4586` existed, "
     "recorded to explain why the fourteenth adapter took the fifteenth ordinal. The sentence's "
     "next clause states today's fourteen"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     'across the thirteen adapters 1.3.0 shipped',
     "RULE 9 CLOSING ON ITSELF, and the loop is finite. The 1.4.0 round RETIRED the TREE_EXEMPT "
     "row that covered these bytes in RELEASE_NOTES.md, because the 1.4.0 notes no longer contain "
     "them — and then quoted the retired bytes in its own record of the retirement, which made "
     "MIGRATIONS.md a site of the figure. A quotation of bytes that no longer exist anywhere else "
     "is the purest form of the case this list is for: there is nothing left to update, and "
     "editing the quotation would misreport what was removed. It terminates here because a record "
     "of THIS exemption need not quote it"),
    # --- the acquisition round's own record, which is RULE 9's shape three times over ---
    #
    # "A record that discusses a token becomes a site of it." Each of these is either a QUOTATION
    # of bytes that exist elsewhere or a statement of a PAST state, and updating any of them would
    # falsify the thing being described.
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     'its "13 adapters" describes the 1.3.0 artefact',
     "a quotation of the v1.3.0 GitHub Release body, which is a dated version-figure site. The "
     "sentence's whole point is that this figure must NOT move with the tree"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     'the release procedure\'s "all thirteen harnesses"',
     "a quotation of the PRE-repair bytes, inside the list of sites that round repaired. The live "
     "sentence now reads fourteen; misquoting it would hide what was fixed"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "so thirteen shipped adapters occupied fourteen ordinals",
     "a PAST state — the roster before `stanag4586` existed — recorded to explain why the "
     "fourteenth adapter took the fifteenth ordinal. The clause before it states today's fourteen"),
    # --- dated round records in MIGRATIONS.md: each measured the tree ON ITS OWN DAY ---
    #
    # These are not stale sentences. A round record states what a round found, and this file's own
    # convention is that a later round ANNOTATES rather than tidies — so editing the number would
    # make the record assert a measurement nobody took. The live sites are elsewhere and are
    # checked by comparison; these are the archive.
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "The 13 adapters and 408 fixture verdicts were derived off `adapter.discover()`",
     "a dated round record of a derivation that round ran. The figure is what the command "
     "printed on the day"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     'saying "Thirteen integration adapters are shipped"',
     "a QUOTATION of bytes another file carried at the time, inside the record of the round that "
     "repaired them. Updating it would misquote the defect being described"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "affects eleven of the thirteen adapters, it is pre-existing across every version",
     "a dated round record of an egress-SKIP measurement. Its subject is a named subset — the "
     "egress-capable adapters — and its eleven is still eleven today"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "across the thirteen adapters' golden files",
     "a dated round record of a key census over the goldens as they stood that day"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "across the thirteen adapters' goldens",
     "the same census quoted one round later, carrying its own date"),
    ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md", "unanimous across five ASTERIX adapters",
     "named subset — the ASTERIX categories, not the roster"),
    ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md", "**Eight adapters, eleven private keys**",
     "named subset — gap 1's tally of adapters inventing a private key, derived from the table "
     "three lines above it"),
    ("tests/test_cdm_pins.py", "this repository has pinned standards for seven adapters",
     "named subset — adapters with a pinned specification on disk. It moved six to seven when "
     "`stanag4609` shipped into `fixtures/klv/spec/`, which is how it reached this list"),
    ("packages/cdm/synapse_cdm/adapters/stanag4676.py",
     "one airframe seen by five adapters derives one entity_id",
     "named subset, and pinned by ICAO24_SITES above — the adapters sharing that namespace"),
    ("tests/test_cdm_ordinals.py", "fewer than eight distinct adapters were bound anywhere",
     "a FLOOR on a sweep's own coverage, not a count of the roster"),
    # --- pinned by another section of this module: cross-references, not second guards ---
    ("docs/docs/changelog.mdx", "twelve adapters have shipped so far",
     "the no-schema-change count, pinned by NO_SCHEMA_CHANGE_SITES above"),
    ("packages/cdm/synapse_cdm/version.py", "entries — twelve adapters, each of which",
     "the no-schema-change count, pinned by NO_SCHEMA_CHANGE_SITES above"),
    ("tests/test_cdm_changelog_claim.py", "\"Twelve adapters landed with no schema change",
     "the no-schema-change count, pinned by NO_SCHEMA_CHANGE_SITES above"),
    ("tests/test_cdm_packaging.py", "MIGRATIONS.md already lists twelve adapters that shipped",
     "the no-schema-change count, pinned by NO_SCHEMA_CHANGE_SITES above"),
    # --- past-tense narrative about a named round, run or defect ---
    ("gates/wheel_install.py", "it replayed ten adapters out of twelve and printed the ten",
     "past-tense narrative about the defect this loop was rewritten to prevent"),
    ("packages/cdm/pyproject.toml", "every raw ASTERIX data block for two of the ten adapters",
     "past-tense narrative about the package-data defect, at the roster of the round that had it"),
    ("tests/test_cdm_packaging.py", "every raw ASTERIX data block for two of the ten adapters.",
     "the same narrative, in the module that gates what that defect broke"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md", "replayed ten of twelve adapters and reported the",
     "past-tense narrative about the written-down roster the gate replaced"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md", "Six sites said ten or nine adapters and now say",
     "past-tense narrative about what the adapter #11 stale-count sweep found"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md", "seven adapters and eight keys became **eight and",
     "past-tense narrative about gap 1's tally moving when `cat062` landed"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md", "`PUBLICATION.md`'s \"Ten adapters, 298 fixture",
     "quotation of PUBLICATION.md's named subset, in the sweep note that ruled it exempt"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md", "and `harness.py`'s \"nine adapters\" are "
                                               "descriptions of things that happened",
     "quotation of a past-tense narrative, and the sentence that rules it one"),
    ("packages/cdm/synapse_cdm/harness.py", "a gate sweep over all nine adapters reported nine",
     "past-tense narrative about the vacuous-run defect `NoFixturesFound` was written for"),
    ("packages/cdm/synapse_cdm/adapters/stanag4676.py",
     "a gate sweep over nine adapters reporting nine greens",
     "the same narrative, at the adapter it happened to"),
    ("tests/test_cdm_gate_rosters.py", "replayed ten of the twelve adapters and printed",
     "past-tense narrative about the two roster checks disagreeing on one run"),
    ("tests/test_cdm_gate_rosters.py", "reported ten of twelve adapters as a green run",
     "the same narrative, in the assertion message that argues it to whoever broke the rule"),
    # --- verbatim quotations of pre-repair bytes or of a run's own output ---
    ("packages/cdm/synapse_cdm/MIGRATIONS.md", "\"nine of the ten shipped adapters\" (now eleven",
     "verbatim quotation of pre-repair bytes in `adapter.py`, with the repair beside it"),
    ("gates/wheel_install.py", "`12 adapters resolved, expected 10`",
     "verbatim quotation of what the gate printed on the run that failed both ways"),
    ("gates/wheel_install.py", "`10 adapters x 2 schema modes, 596 fixture verdicts, 0 failed`",
     "verbatim quotation of the PASS line printed over a run that never touched two adapters"),
    ("tests/test_cdm_gate_rosters.py", "said `12 adapters resolved, expected 10`",
     "the same quotation, in the module that gates against its recurrence"),
    ("tests/test_cdm_gate_rosters.py", "printed `10 adapters x 2 schema modes, 596 fixture",
     "the same quotation, in the module that gates against its recurrence"),
    ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md", "read \"seven adapters and eight private keys\"",
     "verbatim quotation of gap 1's previous tally, correct until `cat062` landed"),
    ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md", "read \"five adapters and six private keys\"",
     "verbatim quotation of the tally before that, and of the undercount it carried"),
    # --- the ledger's exhibits: the four sentences that shipped INSIDE the 1.2.0 artefacts ---
    ("PUBLICATION.md", "release condition 2, reading `All twelve harnesses are green`",
     "verbatim quotation of what the published 1.2.0 wheel and sdist carry, recorded as a known "
     "defect against that artefact; repaired in the tree, see TREE_PRE_REPAIR"),
    ("PUBLICATION.md",
     "reading `eleven of the twelve shipped adapters — stanag4676 … is the only one`",
     "verbatim quotation of what the published 1.2.0 artefacts carry; see TREE_PRE_REPAIR"),
    ("PUBLICATION.md",
     "twice: `twelve adapters shipped and harness-verified`, and the SHIPS list's `the harness, "
     "twelve adapters`",
     "verbatim quotation of what the published 1.2.0 sdist carries; see TREE_PRE_REPAIR"),
    # --- the Unreleased section's exhibits: bytes this commit repaired, quoted as they stood ---
    ("packages/cdm/synapse_cdm/MIGRATIONS.md", "\"the twelve shipped adapters\" under Using it",
     "verbatim quotation of pre-repair bytes in the root `README.md`; see TREE_PRE_REPAIR"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "condition 2 (\"all twelve harnesses\", and the \"thirteenth adapter\" it hangs on",
     "verbatim quotation of pre-repair bytes in this same file; see TREE_PRE_REPAIR"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "\"pinned standards for six adapters\" became seven",
     "verbatim quotation of pre-repair bytes in `tests/test_cdm_pins.py`; see TREE_PRE_REPAIR"),
    ("packages/cdm/synapse_cdm/MIGRATIONS.md",
     "left unset by \"eleven of the twelve shipped adapters — `stanag4676` … is the only one",
     "verbatim quotation of pre-repair bytes in `adapter.py`; see TREE_PRE_REPAIR"),
)

#: Pre-repair bytes quoted somewhere in the tree, and the file each was repaired in. Same
#: discipline as `PRE_REPAIR_QUOTATIONS` and `PKG_README_PRE_REPAIR` above — an exhibit is exempt
#: only while it is genuinely overtaken — stated as a rule that also holds when the quoting file
#: and the repaired file are the SAME one, which is the case those two lists never had to meet.
TREE_PRE_REPAIR: tuple[tuple[str, str], ...] = (
    ("the twelve shipped adapters", "README.md"),
    ("all twelve harnesses", "packages/cdm/synapse_cdm/MIGRATIONS.md"),
    ("pinned standards for six adapters", "tests/test_cdm_pins.py"),
    ("eleven of the twelve shipped adapters", "packages/cdm/synapse_cdm/adapter.py"),
    ("twelve adapters shipped and harness-verified", "packages/cdm/pyproject.toml"),
    ("the harness, twelve adapters", "packages/cdm/pyproject.toml"),
)


@pytest.mark.parametrize("phrase,path", TREE_PRE_REPAIR,
                         ids=[f"{p.rsplit('/', 1)[-1]}::{i}"
                              for i, (_q, p) in enumerate(TREE_PRE_REPAIR)])
def test_the_trees_pre_repair_quotations_are_still_quotations_of_repaired_bytes(phrase, path):
    """The exhibits, checked so that none can quietly become a live claim again.

    The rule is stated once and covers both cases: every occurrence of the pre-repair phrase in the
    file it was repaired in must lie INSIDE a span this module exempts as a quotation. For a
    cross-file exhibit that means zero occurrences, which is what the two lists above assert. For a
    file that quotes its own repaired bytes — `MIGRATIONS.md`'s Unreleased section quoting release
    condition 2 — it means the only occurrence left is the quotation itself, which a bare absence
    check would call a failure and a bare presence check would call a pass either way.
    """
    file = REPO / path
    assert file.exists(), f"{path} does not exist; this exemption is stale"
    text = flat(COMMENT_MARKER.sub("", file.read_text(encoding="utf-8", errors="replace")))
    exempt = [m.span() for site, quotation, _g in TREE_EXEMPT if site == path
              for m in re.finditer(re.escape(quotation), text)]
    live = [m.span() for m in re.finditer(re.escape(phrase), text)
            if not any(lo <= m.start() and m.end() <= hi for lo, hi in exempt)]
    assert not live, (
        f"{path} contains {phrase!r} at {len(live)} place(s) outside any quotation this module "
        "exempts, and TREE_EXEMPT quotes it as bytes that were REPAIRED. Either the repair was "
        "reverted, or an exhibit has become a live claim wearing an exemption written for a "
        "historical one"
    )


def swept_files() -> list[tuple[str, str]]:
    """`(path, normalised text)` for every tracked text file this sweep reads.

    The file set is `tracked_text_files()` — the git index, with no extension list in it, for the
    reason rule 8's section gives: an extension list is a second derivation, and a second
    derivation is a thing to be wrong. Two paths are dropped, each on a ground in `SWEEP_EXCLUDED`.
    """
    out = []
    for path in tracked_text_files():
        name = str(path.relative_to(REPO))
        if name in SWEEP_EXCLUDED:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        out.append((name, flat(COMMENT_MARKER.sub("", text))))
    return out


def test_the_sweeps_exclusions_are_two_files_that_exist_and_are_covered_elsewhere():
    """The exclusion list, before anything is swept with it.

    An exclusion is the one kind of row that makes a sweep report clean by looking away, so it is
    checked in both directions the module checks every other list: the file has to exist, and the
    ground has to be written down. `packages/cdm/synapse_cdm/README.md` must additionally still be
    swept by the section above — an exclusion pointing at a sweep that was deleted is a file
    nothing reads at all.
    """
    for name, ground in SWEEP_EXCLUDED.items():
        assert (REPO / name).exists(), f"{name} is excluded from the sweep and does not exist"
        assert ground.strip(), f"{name} is excluded on no stated ground, which is not an exclusion"
    assert PKG_README in SWEEP_EXCLUDED, (
        "the package README is no longer excluded here; if the file-local sweep was retired, drop "
        "the exclusion in the same commit rather than leaving the file swept twice"
    )
    assert PKG_README_SITES, (
        f"{PKG_README} is excluded from this sweep on the ground that the section above sweeps it, "
        "and that section now pins nothing. One of the two has to read the file"
    )


def test_the_floor_is_low_enough_to_see_a_roster_that_has_gone_stale():
    """The floor's own gate, so it cannot quietly rise past the fact it is filtering for.

    A floor at or above the roster would hide every stale statement of it — the previous roster
    value is what a stale site says, and the previous roster value is always below today's. This
    is the assertion that turns "five is low enough" from a claim in a comment into a check.
    """
    shipped = len(shipped_adapters())
    assert ROSTER_FLOOR < shipped, (
        f"the sweep ignores numbers below {ROSTER_FLOOR} and the roster is {shipped}. A floor that "
        "reaches the roster hides exactly the sites this sweep exists to find — every stale one "
        "states a number smaller than today's"
    )
    assert ROSTER_FLOOR >= 2, (
        "a floor below two makes 'one adapter' a hit, and 'one adapter's bug' is a referent rather "
        "than a count. The exemption list would then be the tree"
    )


@pytest.mark.parametrize("path,quotation,ground", TREE_EXEMPT,
                         ids=[f"{p.rsplit('/', 1)[-1]}::{i}"
                              for i, (p, _q, _g) in enumerate(TREE_EXEMPT)])
def test_every_tree_exemption_still_points_at_prose_that_is_there(path, quotation, ground):
    """An exemption covering no site reads as a live ruling, which is the failure every closure
    in this module refuses in its own direction.

    Checked per row so the failure names the row, and checked against the SAME normalisation the
    sweep uses — a quotation that matches the raw bytes but not the flattened text would exempt
    nothing while looking like it did.
    """
    assert ground.strip(), f"{path}: {quotation!r} is exempt on no stated ground"
    file = REPO / path
    assert file.exists(), f"{path} does not exist; this exemption is stale"
    text = flat(COMMENT_MARKER.sub("", file.read_text(encoding="utf-8", errors="replace")))
    assert quotation in text, (
        f"{path} no longer contains {quotation!r}, exempt here on the ground {ground!r}. Drop the "
        "row with the prose; an exemption pointing at nothing reads as a ruling on a site that is "
        "gone"
    )


def test_no_tracked_file_states_an_adapter_count_that_is_neither_the_roster_nor_ruled():
    """THE SWEEP. One derivation of the roster, every collected site checked against it.

    This is the check the seven stale sites of the 1.2.0 round would have failed. It needs no row
    per site and gains none when a site is repaired: a sentence that says the roster count is
    correct by comparison, today and after the next adapter, and nothing here has to know it
    exists. What needs a row is a number that is NOT the roster, and `TREE_EXEMPT` is that list.

    The message quotes the file, the phrase and the surrounding sentence, because the fix is
    usually one word and the hard part is finding which word.
    """
    shipped = len(shipped_adapters())
    strays = []
    for name, text in swept_files():
        exempt = [span for path, quotation, _g in TREE_EXEMPT if path == name
                  for span in (m.span() for m in re.finditer(re.escape(quotation), text))]
        for match in ROSTER_COUNT.finditer(text):
            word = match.group("num")
            if stated(word) < ROSTER_FLOOR or stated(word) == shipped:
                continue
            if any(lo <= match.start() and match.end() <= hi for lo, hi in exempt):
                continue
            context = text[max(0, match.start() - 110):match.end() + 90]
            strays.append(f"{name}: {match.group(0)!r} ({stated(word)})\n      …{context}…")
    assert not strays, (
        f"{len(strays)} site(s) state an adapter count that is not the {shipped} the registry "
        "ships and that nothing here rules:\n    " + "\n    ".join(strays) + "\n"
        "Each is one of two things. If it means the ROSTER, it is stale — fix the prose, and note "
        "that no row is needed here afterwards, because a sentence stating the roster is checked "
        "by comparison. If it means something else — a named subset, a past run, a quotation of "
        "bytes that were repaired — add it to TREE_EXEMPT with the ground, which is what makes "
        "that list short enough to read"
    )


def test_the_divergent_fixture_dirs_are_what_the_registry_declares():
    """`adapter.py`'s note on `fixture_dir`, both halves, against the registry.

    THE FAILURE THIS EARNED, and it is a new shape for this module. The note said "true of eleven
    of the twelve shipped adapters — `stanag4676` … is the only one where the two differ". When
    `stanag4609` shipped declaring `fixture_dir = "klv"`, the roster went twelve to thirteen AND
    the divergent set went one to two — so the count "eleven" stayed arithmetically correct while
    "is the only one" went false, in the same sentence. A count guard reads numbers; the half that
    broke was a claim of UNIQUENESS, which has no number in it at all.

    So both halves are derived here: how many declare nothing, and exactly which ones do.
    """
    shipped = shipped_adapters()
    divergent = {name for name, cls in shipped.items() if cls.fixture_dir is not None}
    same = len(shipped) - len(divergent)
    note = flat(COMMENT_MARKER.sub("", (PKG / "adapter.py").read_text()))
    match = re.search(
        r"which is true of (?P<n>[a-z]+) of the (?P<roster>[a-z]+) shipped adapters — "
        r"(?P<list>.*?), and the split below",
        note)
    assert match, (
        "`adapter.py`'s fixture_dir note no longer states how many adapters leave it unset, or no "
        "longer names the ones that do. If the sentence was rewritten, re-anchor this deliberately "
        "— it carries both halves, and only one of them has a number in it"
    )
    assert spelled(match.group("n")) == same, (
        f"`adapter.py` says {match.group('n')!r} of the adapters leave `fixture_dir` unset and "
        f"{same} of {len(shipped)} do. Divergent: {sorted(divergent)}"
    )
    assert spelled(match.group("roster")) == len(shipped), (
        f"`adapter.py` states the roster as {match.group('roster')!r} and {len(shipped)} ship"
    )
    # THE SET, read from the naming clause ALONE and not from the file. Reading the file would let
    # a name mentioned anywhere else in the module satisfy this — including in the paragraph below
    # that explains the failure — which is the check passing because of prose about the check.
    named = {n for n in re.findall(r"`([a-z0-9_]+)`", match.group("list")) if n in shipped}
    assert named == divergent, (
        f"`adapter.py`'s note names {sorted(named)} as the adapters whose fixture directory is not "
        f"their name, and the registry says {sorted(divergent)}.\n"
        f"  matched: {match.group('list')!r}\n"
        "This is the half that has no number in it. `stanag4609` shipped into `fixtures/klv` and "
        "made the sentence's 'is the only one' false while its count stayed right, so the set is "
        "compared here and not merely counted"
    )


#: The register heading other files quote by name. Built from a part and the word, so this module's
#: own quotation of it — in the header, where the sweep protocol is cited — is the thing checked
#: rather than a second copy of it.
REGISTER_HEADING_TAIL = "things the harness cannot check for you"

#: Every file that cites the register by its heading, this module included.
REGISTER_CITERS = (
    "packages/cdm/synapse_cdm/fixtures/klv/README.md",
    "tests/test_cdm_prose_counts.py",
)


def test_every_citation_of_the_register_quotes_the_heading_that_is_there():
    """A quotation of a heading is a restatement of it, and headings that carry a count move.

    THE FAILURE THIS EARNED, in this commit. The register gained a fourth entry, its heading went
    "Three things" to "Four things", and two files went on quoting the old one — one of them THIS
    module, in the paragraph that cites the register as the reason the roster sweep is manual. The
    tree sweep above could not see it: the count qualifies "things", not "adapters", and this file
    is excluded from that sweep on a ground written above. So it is checked here, by reading the
    heading rather than by anyone remembering to.
    """
    readme = (PKG / "README.md").read_text()
    headings = re.findall(rf"^#+ (\w+) {re.escape(REGISTER_HEADING_TAIL)}$", readme, re.MULTILINE)
    assert len(headings) == 1, (
        f"{PKG_README} has {len(headings)} heading(s) ending {REGISTER_HEADING_TAIL!r}, expected "
        "1. If the register was renamed, re-anchor this deliberately — the citations below quote "
        "it by name"
    )
    live = f"{headings[0]} {REGISTER_HEADING_TAIL}"
    for path in REGISTER_CITERS:
        file = REPO / path
        assert file.exists(), f"{path} does not exist; this citation list is stale"
        text = file.read_text()
        quoted = re.findall(rf"\"(\w+) {re.escape(REGISTER_HEADING_TAIL)}\"", text)
        assert quoted, (
            f"{path} no longer quotes the register's heading. Drop it from REGISTER_CITERS in the "
            "same commit rather than leaving a list that checks nothing"
        )
        stale = sorted({q for q in quoted if f"{q} {REGISTER_HEADING_TAIL}" != live})
        assert not stale, (
            f"{path} quotes the register as {stale} and the heading reads {live!r}. A quotation of "
            "a heading that carries a count is a restatement of that count, and it goes stale on "
            "the event — a new register entry — that makes anybody read it"
        )
