"""The adapter ordinals, wherever they are stated, against the one table that decides them.

WHY THIS EXISTS
---------------
An adapter's ordinal is a fact stated at three dozen sites — this document's row-set sections, the
module docstrings, the module README, the fixture READMEs, `MIGRATIONS.md` and the suite's own
comments — and nothing failed a build when they disagreed. So they disagreed: `adapters/
stanag4676.py` and `adapters/gmtif.py` call themselves adapter #7 and #8 while
`FORMAT_COVERAGE.md`'s CAT048 preamble called the same two row sets "#9 and #10", four thousand
lines apart and both individually plausible. That is the same shape as the pin-row disjunction
80b38d1 found and the adapter-count drift `test_cdm_prose_counts.py` exists for: a fact stated at
many sites and checked at none.

THE RULE THIS ENCODES, AND THE ONE IT REPLACES
----------------------------------------------
**A parked ordinal is RESERVED, not skipped.** An adapter that was scoped and then parked keeps its
number and the next adapter takes the next free one, so #9 was held while STANAG 4609 took
#10 rather than #12. Two test docstrings had encoded the other rule — "one past the highest that
has shipped" — and both are amended, because that rule re-issues a reserved number the moment a park
is revisited, at which point an ordinal stops identifying an adapter.

THE RESERVATION HAS SINCE BEEN MADE GOOD, WHICH IS NOT THE SAME AS THE RULE BEING RETIRED
-----------------------------------------------------------------------------------------
#9 was reserved for `nffi`, a name that turned out to have no source: not in any document in hand
and nowhere in this repository except the row that reserved it, which said so itself. STANAG 5527's
covering document landed in the slot and the name was re-derived from it, so **the number did not
move and the name did** — #9 is `stanag5527`, at Phase 1. No row in the table is RESERVED any more.
The rule stands regardless, because it is the rule that gave `stanag4609` #10 rather than #12 and
the rule that held #9 open long enough for a document to arrive; and `series()` still classifies a
RESERVED cell, because the next park will need it.

WHAT IS CHECKED, AND WHAT DELIBERATELY IS NOT
---------------------------------------------
`FORMAT_COVERAGE.md`'s ordinal table is the authority; everything else is checked against it. The
sweep binds a site to a pairing only through forms it can read **unambiguously**:

* the canonical claim form, `adapter #N` / `Adapter #N`, on a line naming exactly one adapter;
* a tight adjacency, `` `name` `` within fourteen characters of a following `#N` — one
  direction only, and the reason is in the comment above `NEAR`;
* the ordinal table's own rows;
* an `adapters/<module>.py` docstring that opens by claiming an ordinal.

`#N` on its own is **not** swept, and that is a decision rather than an omission: this repository
writes "subfield #1", "item #28" and "Subfields #3/7" far more often than it writes an ordinal, so a
bare-`#N` sweep would be mostly noise and its exemption list would be longer than the thing it
checked. A line that states more than one pairing at once goes on a reviewed allowlist and a NEW one
fails the build — the same stance, and for the same reason, as
`test_cdm_prose_counts.py`'s "the sweep stays a manual protocol act".

One consequence is worth stating because it is a feature: a sentence the tight binder reads WRONGLY
is a sentence a human can read wrongly, so the repair is to reword the prose rather than to loosen
the binder. Four sentences were reworded during this round for exactly that reason — three that
paired an ordinal with the adapter mentioned *after* it, and one that quoted a retired forecast in
the claim form and so read as making it.
"""
import pathlib
import re

import pytest

import synapse_cdm
from synapse_cdm import adapter

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
DOC = PKG / "FORMAT_COVERAGE.md"

ORDINAL_TABLE_HEADING = "### The adapter ordinals, and the reserved-ordinal rule"

#: Every alias a document might use for an adapter, keyed by the registry name the table uses.
#: Deliberately generous on the prose side and exact on the code side: `gmti` is the registered
#: name, `gmtif` is the module and GMTIF is the format, and all three refer to one adapter.
ALIASES: dict[str, tuple[str, ...]] = {
    "pntmap": ("pntmap", "PNTMAP"),
    "tak": ("tak", "TAK", "Cursor-on-Target"),
    "ais": ("ais", "AIS"),
    "adsb": ("adsb", "ADS-B"),
    "legion": ("legion", "Legion"),
    "cat021": ("cat021", "CAT021", "Category 021"),
    "stanag4676": ("stanag4676", "NITS", "STANAG 4676"),
    "gmti": ("gmti", "gmtif", "GMTIF", "STANAG 4607"),
    "stanag5527": ("stanag5527", "STANAG 5527"),
    "stanag4609": ("stanag4609", "STANAG 4609", "MISP-2019.1"),
    "cat048": ("cat048", "CAT048", "Category 048"),
    "cat034": ("cat034", "CAT034", "Category 034"),
    "cat062": ("cat062", "CAT062", "Category 062"),
    "cat023": ("cat023", "CAT023", "Category 023"),
}

#: Which module implements which registry name, for the docstring check. `pntmap` is absent from
#: the claim side on purpose: it never claims an ordinal, it is claimed BY one — see the table.
MODULES: dict[str, str] = {
    "tak": "tak", "ais": "ais", "adsb": "adsb", "legion": "legion",
    "asterix_cat021": "cat021", "stanag4676": "stanag4676", "gmtif": "gmti",
    "asterix_cat048": "cat048", "asterix_cat034": "cat034",
    "asterix_cat062": "cat062", "asterix_cat023": "cat023",
}

#: Files swept. Everything that states an ordinal, found by grepping the tree for the claim form
#: rather than guessed — and `test_the_swept_file_list_still_covers_every_claim_site` re-derives it.
SWEPT = (
    "packages/cdm/synapse_cdm/FORMAT_COVERAGE.md",
    "packages/cdm/synapse_cdm/MIGRATIONS.md",
    "packages/cdm/synapse_cdm/README.md",
    "packages/cdm/synapse_cdm/fixtures/cat034/README.md",
    "packages/cdm/synapse_cdm/fixtures/cat048/README.md",
    "packages/cdm/synapse_cdm/fixtures/cat023/README.md",
    "packages/cdm/synapse_cdm/fixtures/cat062/README.md",
    "packages/cdm/synapse_cdm/fixtures/fft/README.md",
    "packages/cdm/synapse_cdm/fixtures/fft/spec/fft_pin.json",
    "packages/cdm/synapse_cdm/fixtures/klv/README.md",
    "packages/cdm/synapse_cdm/fixtures/klv/spec/build_fixtures.py",
    "packages/cdm/synapse_cdm/fixtures/klv/spec/klv_pin.json",
    "docs/docs/writing-an-adapter.mdx",
    # RELEASE_NOTES.md joined the sweep when adapter #10 landed on `main` after 1.1.0 and the notes
    # grew a section saying so. A release note is the one document a consumer is most likely to
    # read, which makes it the worst place for an ordinal nothing checks.
    "RELEASE_NOTES.md",
)

CLAIM = re.compile(r"[Aa]dapters?\s+#(\d+)")
#: A backticked registry name within fourteen characters of an ordinal, either order. Fourteen
#: covers " at ", " keeps ", " is held for " and not much else, which is the point: a wider window
#: starts pairing an ordinal with whatever adapter the sentence mentions next.
NEAR = re.compile(r"`([a-z0-9]+)`[^`#\n]{0,14}#(\d+)")

#: ONE DIRECTION ONLY, adapter first. The reverse — `#N` then a backticked name — was tried and
#: removed: "which gave #12 after `cat048` at #11" contains both pairings and the reverse direction
#: reads the wrong one, and so does "`gmti`'s #8. `cat048` keeps #11". Rather than widen the binder
#: or exempt the sentences, the rule is now that a sentence pairing an adapter with an ordinal
#: WRITES THE ADAPTER FIRST. That is a constraint on prose, it is satisfied by every such sentence
#: in the tree, and it is the honest trade: a binder that guesses at "#9, and `stanag4609`" is a
#: binder that also guesses at "#8, and `cat048`", and only one of those guesses is right. The
#: sentences that used to state #9 the wrong way round were reworded when the ordinal was issued,
#: so the pairing is now bound rather than merely asserted.

#: Lines that state more than one pairing at once, each with the pairing a human read off it.
#: A line that the sweep cannot bind and that is not here FAILS — adding a row is a deliberate act
#: and is how a new multi-pairing sentence gets reviewed instead of silently skipped.
DISTRIBUTIVE: tuple[tuple[str, str, int, str], ...] = (
    ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md",
     "before adapter #5 and the NITS and GMTIF rows before #7 and #8", 5, "legion"),
    ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md",
     "were written before adapter #5, the NITS rows before", 5, "legion"),
    ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md",
     "| 12 | `cat034` | shipped |", 12, "cat034"),
    ("docs/docs/writing-an-adapter.mdx",
     "ships as adapter #2 and `adapters/ais.py` as #3", 2, "tak"),
    ("tests/test_cdm_format_coverage.py",
     "like the Legion one was before adapter #5 landed", 5, "legion"),
)


# --------------------------------------------------------------- the authority: the table itself

def series() -> dict[int, tuple[str, str]]:
    """`{ordinal: (registry name, state)}`, parsed from FORMAT_COVERAGE.md's ordinal table.

    Parsed rather than duplicated. A copy of the table in this file would be a second site stating
    the same fact, which is the defect the module exists to catch.
    """
    text = DOC.read_text()
    start = text.index(ORDINAL_TABLE_HEADING)
    end = text.find("\n## ", start)
    body = text[start:end if end != -1 else len(text)]
    out: dict[int, tuple[str, str]] = {}
    for line in body.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|(.*?)\|(.*?)\|", line)
        if not m:
            continue
        ordinal, name_cell, state_cell = int(m.group(1)), m.group(2), m.group(3)
        names = re.findall(r"`([a-z0-9]+)`", name_cell)
        assert len(names) == 1, f"ordinal row {ordinal} names {names}, expected exactly one"
        # RESERVED is tested FIRST and the order is load-bearing. No row carries it today — #9
        # was the only one and its reservation was made good — but the branch stays, because the
        # cell it was written for read "RESERVED, nothing shipped and nothing parked here yet" and
        # a "shipped" test running first would classify a reserved ordinal as shipped and then fail
        # against the registry: a real failure with a misleading cause, the kind that costs an
        # hour. test_no_ordinal_is_reserved_any_more asserts the absence rather than leaving a
        # reader to wonder whether this branch has stopped matching.
        state = ("reserved" if "RESERVED" in state_cell else
                 "shipped" if "shipped" in state_cell else "planned")
        out[ordinal] = (names[0], state)
    return out


SERIES = series()
BY_NAME = {name: n for n, (name, _state) in SERIES.items()}


def test_the_ordinal_table_was_actually_parsed():
    """A sweep whose authority is empty would agree with every site about nothing."""
    assert len(SERIES) >= 12, f"parsed only {len(SERIES)} ordinal rows from {DOC.name}"
    assert sorted(SERIES) == list(range(1, max(SERIES) + 1)), (
        f"the ordinal series has a hole: {sorted(SERIES)}. A reserved ordinal still gets a row — "
        "that is the whole point of reserving it rather than skipping it"
    )
    assert SERIES[1][0] == "pntmap" and SERIES[9][0] == "stanag5527", (
        f"the table's anchors moved: #1 is {SERIES[1][0]!r} and #9 is {SERIES[9][0]!r}"
    )


def test_the_table_is_a_bijection():
    """One adapter per ordinal, one ordinal per adapter. The invariant the whole module protects."""
    names = [name for name, _ in SERIES.values()]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, (
        f"an adapter holds two ordinals: {sorted(duplicates)}. An ordinal that can name two "
        "adapters names neither, which is the failure the reserved-ordinal rule exists to prevent"
    )
    assert len(set(SERIES)) == len(SERIES), "an ordinal appears twice in the table"


def test_the_shipped_rows_are_exactly_the_registered_adapters():
    """The table's `shipped` column against the registry, in both directions.

    A table is a claim about the code and the code is the fact. Checked both ways because the two
    failures are different: a shipped row for unregistered code advertises an adapter that does not
    exist, and a registered adapter with no shipped row is one the ordinal series has lost track of.
    """
    registered = {n for n, c in adapter.discover().items()
                  if c.__module__.startswith("synapse_cdm.adapters.")}
    claimed = {name for name, state in SERIES.values() if state == "shipped"}
    assert claimed == registered, (
        f"the ordinal table's shipped set and the registry disagree: only in the table "
        f"{sorted(claimed - registered)}, only in the registry {sorted(registered - claimed)}"
    )


def test_the_phase_one_ordinals_have_no_adapter_and_no_rival_claimant():
    """AN ABSENCE, and the one the reserved-ordinal rule rests on.

    #9 was held for `nffi` and is now `stanag5527`; #10 is `stanag4609`. Both are Phase 1, and
    holding an ordinal for one means two things must stay true: no code implements it, and no OTHER
    adapter claims the number. The second is the one that decays — the old "next past the highest
    shipped" rule would have handed #9 to whoever came after `gmti`, and a held ordinal with a rival
    claimant is worse than no reservation at all, because both sites read as correct.

    Generalised from #9 to every non-shipped ordinal when #9 was issued. The old form named #9
    directly, which meant the day the reservation was made good the check would have had to be
    rewritten to keep testing anything — and a check that has to be rewritten every time its
    subject changes is a check that eventually is not.
    """
    registered = set(adapter.discover())
    held = {n: name for n, (name, state) in SERIES.items() if state != "shipped"}
    assert held, (
        "no ordinal is held for an unshipped adapter, so this check is vacuous. Two ordinals are "
        "at Phase 1 — #9 and #10 — so either alone should keep it non-empty. #12 was the third "
        "until `cat034` shipped, which is the transition this check has to survive rather than "
        "be broken by"
    )
    for ordinal, name in sorted(held.items()):
        assert name not in registered, (
            f"{name!r} is registered and its row at #{ordinal} is not `shipped` — move the row and "
            "say so in the same commit"
        )
        for other_ordinal, (other, _state) in SERIES.items():
            assert other_ordinal == ordinal or other != name, (
                f"{name!r} claims #{ordinal} and #{other_ordinal}"
            )
        # And nothing anywhere claims this ordinal for something else. Lines on the reviewed
        # multi-pairing allowlist are read through it rather than through the name set, for the
        # reason the allowlist exists: #12's own table row mentions three adapters in one cell and
        # a human has already stated which pairing it makes.
        for path, line_no, line in _swept_lines():
            for m in CLAIM.finditer(line):
                if int(m.group(1)) != ordinal:
                    continue
                reviewed = [d for d in DISTRIBUTIVE if d[0] == path and d[1] in line]
                if reviewed:
                    for _p, _frag, stated_ordinal, stated_name in reviewed:
                        assert stated_ordinal != ordinal or stated_name == name, (
                            f"{path}:{line_no} is allowlisted as pairing #{stated_ordinal} with "
                            f"{stated_name!r} and the table gives #{ordinal} to {name!r}"
                        )
                    continue
                named = _adapters_named(line)
                assert named <= {name}, (
                    f"{path}:{line_no} claims adapter #{ordinal} for {sorted(named)}, and "
                    f"#{ordinal} is held by {name!r}: {line.strip()[:120]}"
                )


def test_no_ordinal_is_reserved_any_more_and_the_retired_name_is_named_nowhere_as_current():
    """AN ABSENCE with two halves, and the second is the one that stops a name surviving by default.

    #9's reservation was made good in the STANAG 5527 round: the slot was held for a
    friendly-force-tracking adapter, a friendly-force-tracking covering document arrived, and the
    NAME was re-derived from that document because the reserved one had no source — not in any
    document in hand, and nowhere in this repository except the row that reserved it, which said so
    itself.

    So two things are asserted. First, that no row carries RESERVED, because `series()` still has a
    branch for it and a branch matching nothing reads as a passing check on nothing — recorded here
    rather than left for a reader to discover by mutating the parser. Second, and this is the half
    with teeth: `nffi` may appear in this repository ONLY where its retirement is recorded. A
    retired name that drifts back into a sentence as a current one is exactly the failure the
    re-derivation was for, and it would read as correct at every site.
    """
    reserved = {n: name for n, (name, state) in SERIES.items() if state == "reserved"}
    assert not reserved, (
        f"ordinals are RESERVED again: {reserved}. That is permitted by the rule — a scoped-then-"
        "parked adapter keeps its number — but the reservation has to be re-derived from a named "
        "source when it is issued, which is what retired `nffi`. Update this test deliberately"
    )
    RETIRED = "nffi"

    # It is not a row in the table, it is not registered code, and it is not a fixture directory.
    # Those three are what "current name" would mean, and each is checked positively.
    assert RETIRED not in {name for name, _state in SERIES.values()}, (
        f"{RETIRED!r} is back in the ordinal table. It was retired because it had no source"
    )
    assert RETIRED not in set(adapter.discover()), f"{RETIRED!r} is a registered adapter"
    assert not (PKG / "fixtures" / RETIRED).exists(), (
        f"fixtures/{RETIRED}/ exists. The fixture directory ruling went to `fft`, provisionally, "
        "and to the retired name never"
    )

    # WINDOWED rather than line-scoped or file-scoped, and both rejected alternatives are worth
    # naming because each fails in a different direction. Line-scoped reports the record of the
    # retirement AS the offence: prose here is hard-wrapped at 100 columns, so a sentence that
    # retires the name routinely puts the name on one line and the reason on the next. File-scoped
    # is too generous the other way — mutation showed it: dropping `nffi` into a large test module
    # passed, because that module happened to contain the word "reserved" four hundred lines away.
    # So each OCCURRENCE has to be accounted for within a window that hard-wrapped prose can span.
    WINDOW = 400
    # "filename pattern" is the one context word that is not about the retirement: two sites use
    # `nffi` as a SEARCH TERM in the record of what ~/Downloads was swept for, which is a use of
    # the string and not a use of the name. It is narrow enough that no sentence naming an adapter
    # could satisfy it by accident, which is the bar every word in this tuple has to clear.
    RECORDS_IT = ("retire", "no source", "reserved", "reservation", "never uses",
                  "appears nowhere", "not present", "zero occurrences", "does not occur",
                  "held for", "has since", "filename pattern")
    offenders = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md", ".mdx", ".json"}:
            continue
        if "node_modules" in path.parts or ".git" in path.parts:
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        low = text.lower()
        for m in re.finditer(RETIRED, low):
            around = low[max(0, m.start() - WINDOW):m.end() + WINDOW]
            if not any(w in around for w in RECORDS_IT):
                line_no = low.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(REPO)}:{line_no}")
    assert not offenders, (
        f"{RETIRED!r} is used at these sites with nothing nearby recording what happened to it: "
        f"{offenders}. The name has no source in any document and none in this repository. It may "
        "be named as a retired reservation and never as a current one"
    )
    # The sweep must find the name SOMEWHERE, or it is a check on an empty set: the retirement is
    # deliberately recorded rather than erased, so that a reader meeting `nffi` in the history has
    # somewhere to land.
    assert any(RETIRED in (REPO / s).read_text().lower()
               for s in ("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md",
                         "packages/cdm/synapse_cdm/fixtures/fft/spec/fft_pin.json")), (
        f"{RETIRED!r} is recorded nowhere. Erasing a retired reservation leaves the next reader of "
        "commit 1b0316b with a name and no explanation"
    )


# --------------------------------------------------------------------------- the sweep

#: This module is not swept, and the exclusion is not self-serving: its docstring and its allowlist
#: QUOTE the disagreement it exists to fix — "call themselves adapter #7 and #8 while ... #9 and
#: #10" — so sweeping it would flag the record of the defect as the defect. Every other file that
#: states an ordinal is swept, and `test_the_swept_file_list_still_covers_every_claim_site`
#: re-derives that list rather than trusting it.
SELF = "tests/test_cdm_ordinals.py"


def _swept_lines():
    for rel in SWEPT + tuple(f"tests/{p.name}" for p in sorted((REPO / "tests").glob("test_cdm_*.py"))
                             if f"tests/{p.name}" != SELF) \
            + tuple(f"packages/cdm/synapse_cdm/adapters/{p.name}"
                    for p in sorted((PKG / "adapters").glob("*.py"))):
        path = REPO / rel
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            yield rel, i, line


def _adapters_named(line: str) -> set[str]:
    return {name for name, aliases in ALIASES.items() if any(a in line for a in aliases)}


def _bindings():
    """Every (path, line, ordinal, adapter) the sweep can bind, plus the lines it cannot."""
    bound, unbound = [], []
    for path, line_no, line in _swept_lines():
        claims = {int(m.group(1)) for m in CLAIM.finditer(line)}
        near = {(m.group(1), int(m.group(2))) for m in NEAR.finditer(line)}
        near = {(n, o) for n, o in near if n in BY_NAME}
        for name, ordinal in sorted(near):
            bound.append((path, line_no, ordinal, name, line))
        if claims:
            named = _adapters_named(line)
            if len(claims) == 1 and len(named) == 1:
                bound.append((path, line_no, next(iter(claims)), next(iter(named)), line))
            elif not near:
                unbound.append((path, line_no, sorted(claims), sorted(named), line))
    return bound, unbound


BOUND, UNBOUND = _bindings()


def test_the_sweep_bound_something():
    """A sweep that binds nothing passes every agreement check and proves nothing."""
    assert len(BOUND) >= 20, f"the sweep bound only {len(BOUND)} pairings"
    assert len({n for _p, _l, _o, n, _line in BOUND}) >= 8, (
        "fewer than eight distinct adapters were bound anywhere, so most of the series is "
        "unchecked and the binder has probably stopped matching"
    )


@pytest.mark.parametrize("case", BOUND, ids=lambda c: f"{c[0].split('/')[-1]}:{c[1]}:{c[3]}#{c[2]}")
def test_every_bound_site_agrees_with_the_table(case):
    path, line_no, ordinal, name, line = case
    assert ordinal in SERIES, (
        f"{path}:{line_no} states adapter #{ordinal}, which is not in the ordinal series "
        f"{sorted(SERIES)}: {line.strip()[:120]}"
    )
    expected, _state = SERIES[ordinal]
    assert expected == name, (
        f"ORDINALS DISAGREE.\n"
        f"  {path}:{line_no} pairs #{ordinal} with {name!r}\n"
        f"  FORMAT_COVERAGE.md's ordinal table gives #{ordinal} to {expected!r}, and {name!r} to "
        f"#{BY_NAME.get(name, '(no ordinal)')}\n"
        f"  line: {line.strip()[:140]}\n"
        "One of the two is wrong. The table is the authority, so either the site is stale or the "
        "table has to change deliberately and every other site with it."
    )


def test_every_unbindable_claim_line_is_on_the_reviewed_allowlist():
    """A line stating several pairings at once has to be read by a person, once.

    The allowlist is the record of that reading. Its value is entirely in the failure: a NEW
    multi-pairing sentence — the exact shape that produced the "#9 and #10" defect — stops the
    build until somebody states what it means.
    """
    unreviewed = []
    for path, line_no, claims, named, line in UNBOUND:
        if not named:
            continue                      # no adapter on the line: nothing to disagree about
        matched = [d for d in DISTRIBUTIVE if d[0] == path and d[1] in line]
        if not matched:
            unreviewed.append(f"{path}:{line_no} claims {claims} near {named}: {line.strip()[:110]}")
    assert not unreviewed, (
        "these lines state an ordinal beside more than one adapter and are not on the reviewed "
        "allowlist:\n  " + "\n  ".join(unreviewed) +
        "\nRead each one, then add it to DISTRIBUTIVE with the pairing it actually states."
    )


@pytest.mark.parametrize("path,fragment,ordinal,name", DISTRIBUTIVE,
                         ids=lambda x: str(x)[:40])
def test_every_allowlisted_line_still_exists_and_still_states_its_pairing(path, fragment, ordinal,
                                                                         name):
    """A pattern that silently matches nothing reads as a passing check on nothing.

    The same failure mode `test_cdm_prose_counts.py` guards, and the same repair: a fragment that
    stops matching is a FAILURE, and re-anchoring it is a deliberate act.
    """
    text = (REPO / path).read_text()
    assert text.count(fragment) == 1, (
        f"{path}: the allowlisted fragment matched {text.count(fragment)} times, expected 1\n"
        f"  fragment: {fragment!r}\n"
        "Re-anchor it deliberately if the sentence was rewritten; do not delete the row."
    )
    assert SERIES[ordinal][0] == name, (
        f"the allowlist says {path} pairs #{ordinal} with {name!r} and the table gives that "
        f"ordinal to {SERIES[ordinal][0]!r}"
    )


@pytest.mark.parametrize("module,name", sorted(MODULES.items()))
def test_every_adapter_module_that_claims_an_ordinal_claims_the_right_one(module, name):
    """The module docstrings, which are where a reader looks first and where two were right.

    `adapters/stanag4676.py` and `adapters/gmtif.py` were the correct sites in the "#9 and #10"
    disagreement, so the check is not that they agree with the document — it is that the document
    and they agree, and this is the half that reads the code.
    """
    path = PKG / "adapters" / f"{module}.py"
    head = path.read_text()[:1200]
    found = CLAIM.findall(head)
    if not found:
        pytest.skip(f"{module}.py claims no ordinal; the table records which modules do not")
    assert len(set(found)) == 1, f"{module}.py claims several ordinals: {sorted(set(found))}"
    claimed = int(found[0])
    assert claimed == BY_NAME[name], (
        f"adapters/{module}.py claims adapter #{claimed} and the ordinal table gives {name!r} "
        f"#{BY_NAME[name]}"
    )


def test_the_two_modules_that_claim_no_ordinal_are_the_two_the_table_names():
    """AN ABSENCE, and the table has to be honest about it.

    `pntmap` never claims a number (it says to read it "before writing adapter #2") and
    `asterix_cat048.py` states none either — which is a real inconsistency in the tree, recorded in
    the ordinal table rather than repaired here. If a third module stops claiming one, or one of
    these two starts, the table's own notes are stale and this fails.
    """
    silent = set()
    for module in list(MODULES) + ["pntmap"]:
        head = (PKG / "adapters" / f"{module}.py").read_text()[:1200]
        if not re.search(r"^\s*Adapter #\d+|Adapter #\d+\.$", head, re.M):
            silent.add(module)
    assert silent == {"pntmap", "asterix_cat048"}, (
        f"the modules stating no ordinal of their own are {sorted(silent)}; the ordinal table says "
        "they are pntmap and asterix_cat048. Update the table's notes in the same commit"
    )
    table = DOC.read_text()
    start = table.index(ORDINAL_TABLE_HEADING)
    body = table[start:table.find("\n## ", start)]
    assert "states no ordinal of its own" in body, (
        "the table no longer records that a shipped adapter claims no ordinal — an absence nobody "
        "wrote down is one the next reader re-derives"
    )


def test_no_site_claims_an_ordinal_past_the_series():
    """AN ABSENCE. A fifteenth adapter cannot arrive by writing a number in a comment.

    This is the check that stops the whole question reopening: the next adapter has to extend the
    table, and extending the table is where the reserved-ordinal rule gets applied on purpose.
    """
    highest = max(SERIES)
    for path, line_no, line in _swept_lines():
        for m in CLAIM.finditer(line):
            ordinal = int(m.group(1))
            assert ordinal <= highest, (
                f"{path}:{line_no} claims adapter #{ordinal} and the series stops at #{highest}. "
                f"Extend FORMAT_COVERAGE.md's ordinal table first, applying the reserved-ordinal "
                f"rule: {line.strip()[:120]}"
            )


def test_the_swept_file_list_still_covers_every_claim_site():
    """The allowlist-of-files problem: a file that starts claiming ordinals must not go unswept.

    Re-derived rather than trusted. Every `*.py`, `*.md` and `*.mdx` in the package, the tests and
    the docs is grepped for the claim form, and any file holding one that is not swept fails.
    """
    swept = set(SWEPT)
    swept |= {f"tests/{p.name}" for p in (REPO / "tests").glob("test_cdm_*.py")}
    swept.add(SELF)
    swept |= {f"packages/cdm/synapse_cdm/adapters/{p.name}" for p in (PKG / "adapters").glob("*.py")}
    missed = []
    for root in ("packages/cdm/synapse_cdm", "tests", "docs/docs", "."):
        base = REPO / root
        for pattern in ("*.py", "*.md", "*.mdx"):
            for path in base.glob(pattern) if root == "." else base.rglob(pattern):
                if "node_modules" in path.parts:
                    continue
                rel = str(path.relative_to(REPO))
                if rel in swept:
                    continue
                try:
                    text = path.read_text()
                except (OSError, UnicodeDecodeError):
                    continue
                if CLAIM.search(text):
                    missed.append(rel)
    assert not missed, (
        f"these files state an adapter ordinal and are not swept: {sorted(set(missed))}. Add them "
        "to SWEPT — an unswept claim site is exactly the state this module was written to end"
    )
