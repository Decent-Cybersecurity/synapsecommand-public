"""The adapter count, wherever it is stated in prose, against the registry that decides it.

WHY THIS EXISTS, AND WHY IT IS AN ALLOWLIST AND NOT A SCANNER
------------------------------------------------------------
Seven documents state how many adapters are shipped, and three of them do the pair arithmetic as
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
`docs/docs/cdm/entity.mdx` both carry the count TWICE in one clause — "so that nine adapters
cannot grow nine slightly different opinions" — and that is exactly the shape that half-edited
last time: commit 94c000a had to repair "seven adapters cannot grow six slightly different
opinions", a sentence that had been half-updated and read as prose either way.
"""
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
)


# ------------------------------------------------------------------------------- tests


def test_the_registry_is_the_authority_and_is_not_empty():
    """A count test that found no adapters would pass every comparison and prove nothing."""
    shipped = shipped_adapters()
    assert len(shipped) >= 9, f"only {len(shipped)} shipped adapters found: {sorted(shipped)}"
    assert set(shipped) <= set(adapter.discover()), "scoping cannot invent an adapter"
    # And the scoping is load-bearing rather than defensive: the raw registry is
    # larger than this whenever a test module defining an Adapter has been imported.
    assert all(not name.startswith("_") for name in shipped), \
        f"a test double reached the shipped set: {sorted(shipped)}"
    assert "cat048" in shipped, (
        "cat048 is not registered, so the roster this module guards is not the one that shipped"
    )


def test_the_allowlist_covers_every_site_the_sweep_had_to_fix():
    """The allowlist is the sweep's output, so it has to name each file the sweep touched.

    Six of the seven are files the adapter #11 roster sweep REPAIRED. The seventh,
    `CONTRIBUTING.md`, was added by the CAT034 round's sweep and had never been wrong — which is
    the more interesting way for a site to get here. That sweep went looking for a count that
    would have to MOVE and correctly found none: adapter #12 is Phase 1, the convention these
    sites state is SHIPPED adapters, and a Phase 1 ships nothing, so every "nine" in the tree is
    still nine. What it found instead was a seventh file making the same claim as `README.md`, in
    the first paragraph a contributor reads, guarded by nothing. A correct count with no gate on
    it is the state all six of the others were in before they drifted.
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
    }, (
        "the allowlist no longer matches the seven files the roster sweeps have covered. "
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
