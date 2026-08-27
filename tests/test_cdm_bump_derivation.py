"""`gates/bump_derivation.py` held to its contract, in all three directions, on real arcs.

WHAT WAS MISSING, BECAUSE THE GUARD IS ONLY WORTH ITS LINES IF THE GAP IS ON THE RECORD
---------------------------------------------------------------------------------------
The 1.2.1 release round was specified as **1.3.0**, and nothing in this repository could have
said so. `tests/test_cdm_release.py` requires a tag to NAME its tree's `PACKAGE_VERSION`, requires
the notes to describe that version, and requires package source that moved past its tag to be
written down — every one of which is satisfied by any number typed consistently. The renumbering
to 1.2.1 was a person reading a diff and applying `version.py`'s table by hand, and `PUBLICATION.md`
entry 10 records the reasoning. **A version number is the one claim in a release that can never be
corrected** — a PyPI filename is permanent — and it was the one claim with no machine behind it.

WHAT IS ASSERTED HERE, AND WHY THE HISTORY IS THE MAIN WITNESS
--------------------------------------------------------------
The gate's own `--mutation-check` runs five synthetic fixtures, and this module runs them too. But
a synthetic fixture proves the classifier does what its author expected, which is the weaker
half. **The strong witness is that the gate, run over this repository's four releases, derives the
number each one actually shipped** — 1.1.0 and 1.2.0 as MINOR, 1.2.1 as PATCH — without being told
any of them. Three arcs, ruled by three different rounds, none of which had this gate.

`test_every_released_arc_derives_the_number_it_shipped` is that check. It also NAMES the one
historical arc the gate cannot rule on its own, rather than counting them: `v1.0.0 → v1.1.0`
changed `adapter.py`'s `load_adapter` on functional lines while adding a roster elsewhere in the
same file, and a body change with no roster of its own is the unruled case by construction. The
arc's number is not in doubt — two adapters and two fixture sets landed in it and the MINOR floor
is proved several times over — but the gate refuses to report a floor while any unit is unruled,
so the arc is listed here as a set of one. A second entry fails the build; so does dropping this
one while it is still ambiguous, which is `tests/test_cdm_prose_counts.py`'s treatment of an
exhibit whose repair was reverted.

WHY THE UNRULED DIRECTION GETS AS MUCH ATTENTION AS THE OTHER TWO
-----------------------------------------------------------------
A gate that guesses is worse than no gate, because its green is load-bearing. `version.py`'s PATCH
row ("a translation fix, a message, a docstring. No surface change") and its MAJOR row ("an
importable name is removed or its MEANING changes") both reach a function whose body moved and
whose name did not, and no diff separates them. So the gate refuses and names the unit — and it
must then be SATISFIABLE, which is the failure mode `tests/test_cdm_release.py`'s
`_package_tree_moved_since` docstring records from the other side: its two halves once read
different trees, so it demanded a section and refused the tree that had one. Both halves of the
ruling mechanism are asserted here: a recorded ruling resolves an ambiguity, and a ruling that
outlives its case is refused as stale.
"""
import json
import pathlib
import subprocess
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "bump_derivation.py"

#: The historical arcs whose floor the gate cannot report without a person's ruling. NAMED, never
#: counted — a ratio goes stale on the next release and a set does not. See the module docstring
#: for why `v1.0.0 → v1.1.0` is here and why its NUMBER was never in doubt.
UNRULED_HISTORICAL_ARCS = {("v1.0.0", "v1.1.0"): {"synapse_cdm/adapter.py:load_adapter"}}


@pytest.fixture(scope="module")
def gate():
    """The gate from its SOURCE, never from bytecode — `tests/test_cdm_gate_rosters.py`'s reason.

    `exec(compile(...))` rather than `spec.loader.exec_module`: the ordinary source loader writes
    and consults `__pycache__`, and a `.pyc` is revalidated on the source's mtime in whole seconds
    plus its size, so a same-length edit reverted inside one second validates against a file it was
    not compiled from. Mutating this gate and reverting is exactly how the assertions below get
    checked, which is the edit pattern that defeats.
    """
    module = types.ModuleType("_bump_derivation_gate")
    module.__file__ = str(GATE_PATH)
    # REGISTERED IN `sys.modules` FOR THE DURATION, AND THAT IS NOT OPTIONAL HERE.
    # `tests/test_cdm_gate_rosters.py` loads its gate without this and is fine, because that gate
    # holds no dataclass. This one holds five, and a `@dataclass` under `from __future__ import
    # annotations` resolves its own field annotations through `sys.modules[cls.__module__]` — which
    # is `None` for a module that was exec'd into a bare namespace. Every test in this file errored
    # with `'NoneType' object has no attribute '__dict__'` from inside `dataclasses` until the
    # registration was added. Removed again afterwards, so the suite's module table is unchanged by
    # having run this file.
    sys.modules[module.__name__] = module
    try:
        exec(compile(GATE_PATH.read_text(), str(GATE_PATH), "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(module.__name__, None)


def _require_git() -> None:
    """SKIP, never PASS, where there is no history to read.

    `tests/test_cdm_packaging.py`'s treatment: an sdist or an unpacked wheel has the package and no
    `.git`, and failing there would report a broken repository when what was found is a legitimate
    distribution form. Every check below reads revisions.
    """
    if not (REPO / ".git").exists():
        pytest.skip("no .git in this tree (an sdist or an unpacked wheel is the normal case), so "
                    "no arc can be read and NOTHING here is asserted")


def test_the_gate_imports_with_no_side_effects(gate):
    """Only `main()` acts. Reading the file with a tool that imports it must cost nothing."""
    assert callable(gate.derive)
    assert callable(gate.measure)
    assert gate.KINDS == ("NONE", "PATCH", "MINOR", "MAJOR")


# ------------------------------------------------------------------- the tree, judged for real


def test_this_trees_package_version_is_the_bump_its_own_diff_requires(gate):
    """The whole gate, on the real arc. This is the check 1.3.0 would have failed.

    Not a re-implementation of the derivation: it calls `measure()`, which is the same code path
    the command runs, so a release round and the suite cannot disagree about one tree.
    """
    _require_git()
    verdict = gate.measure()
    assert verdict.declared_kind == verdict.derived_kind, (
        f"{verdict.declared} is a {verdict.declared_kind} over {verdict.base_tag} and the diff "
        f"derives {verdict.derived_kind}"
    )
    assert not verdict.ambiguities


def test_every_released_arc_derives_the_number_it_shipped(gate):
    """Four releases, three arcs, and the gate was told none of the numbers.

    The strong witness. Each arc is classified from the two trees alone and compared against the
    bump the tags themselves record, so a classifier that quietly floored everything to PATCH
    would fail on 1.1.0 and 1.2.0, and one that inflated everything to MINOR would fail on 1.2.1.
    """
    _require_git()
    tags = gate.release_tags()
    ordered = sorted(tags)
    assert len(ordered) >= 2, "fewer than two releases; there is no arc to classify"

    for base, head in zip(ordered, ordered[1:]):
        base_tag, head_tag = tags[base], tags[head]
        derived = gate.derive(gate.snapshot_at(base_tag), gate.snapshot_at(head_tag))
        expected_unruled = UNRULED_HISTORICAL_ARCS.get((base_tag, head_tag), set())
        found_unruled = {a.unit for a in derived.ambiguities}
        assert found_unruled == expected_unruled, (
            f"the unruled units on {base_tag} → {head_tag} are {sorted(found_unruled)}; "
            f"UNRULED_HISTORICAL_ARCS names {sorted(expected_unruled)}. History does not change, "
            "so a difference here means the gate's reading of it did — either it learned to "
            "classify a unit, which is a repair and the set shrinks with it, or it stopped being "
            "able to, which is a regression"
        )
        if found_unruled:
            continue
        assert derived.floor == gate.single_step(base, head), (
            f"{base_tag} → {head_tag} shipped as a {gate.single_step(base, head)} and its own "
            f"diff derives {derived.floor}. Either that release was misnumbered — and it is on "
            "PyPI, so that is a finding and not a fix — or this gate's classification of the arc "
            "is wrong. The strongest evidence it found: "
            f"{[(s.kind, s.unit) for s in derived.strongest()[:4]]}"
        )


def test_the_declaration_is_not_evidence_for_itself(gate):
    """`PACKAGE_VERSION`'s own assignment is excluded, so no bump can justify itself.

    Without the exclusion every arc would carry a functional change to `version.py` — the version
    string — and the gate would find a PATCH floor in the act of declaring a version. It would
    then agree with any PATCH anybody typed, over an arc that changed nothing else.
    """
    before = {"synapse_cdm/version.py": b'PACKAGE_VERSION = "1.2.0"\nSCHEMA_VERSION = "1.0.0"\n'}
    after = {"synapse_cdm/version.py": b'PACKAGE_VERSION = "1.2.1"\nSCHEMA_VERSION = "1.0.0"\n'}
    derived = gate.derive(before, after)
    assert derived.floor == "NONE", (
        f"an arc whose only change is the version string derives {derived.floor}. The declaration "
        f"is evidence for itself: {[(s.kind, s.unit) for s in derived.signals]}"
    )
    assert not derived.ambiguities


def test_a_schema_version_bump_is_at_least_a_package_minor(gate):
    """`version.py` states the consequence itself; the gate reads it off the assignment."""
    before = {"synapse_cdm/version.py": b'PACKAGE_VERSION = "1.2.1"\nSCHEMA_VERSION = "1.0.0"\n'}
    after = {"synapse_cdm/version.py": b'PACKAGE_VERSION = "1.2.1"\nSCHEMA_VERSION = "1.1.0"\n'}
    derived = gate.derive(before, after)
    assert derived.floor == "MINOR", (
        f"a SCHEMA_VERSION move derives {derived.floor}. `version.py`: 'A SCHEMA_VERSION bump is "
        "ALWAYS at least a package MINOR, because the objects this package emits change shape'"
    )


def test_a_comment_only_edit_is_patch_and_is_derived_from_the_parse(gate):
    """The PATCH row's 'a docstring', as a property of the AST rather than of a line filter.

    Both files that moved on non-document lines in the real 1.2.1 arc are comment-only, and this
    is the property that establishes it. A regex over `#` would have to be right about strings
    containing a hash, about a docstring's own hashes, and about continuation lines; a parse is
    right about all three because comments are not in an AST at all.
    """
    before = {"synapse_cdm/adapter.py":
              b'"""The SDK."""\n\n\n# a comment, and a hash # inside it\n'
              b'def discover():\n    return "# not a comment"\n'}
    after = {"synapse_cdm/adapter.py":
             b'"""The SDK, restated at length."""\n\n\n# the same comment, reworded\ndef discover():\n'
             b'    return "# not a comment"\n'}
    derived = gate.derive(before, after)
    assert derived.floor == "PATCH", f"derived {derived.floor}"
    assert not derived.ambiguities
    assert any("functional AST is unchanged" in s.reason for s in derived.signals)


# ------------------------------------------------------------------------ the three refusals


@pytest.mark.parametrize("index", range(5))
def test_each_fixture_behaves_as_its_own_specification_says(gate, index):
    """The gate's fixtures, run by the suite as well as by `--mutation-check`.

    Parametrized per fixture rather than looped so that a failure names WHICH direction stopped
    working. A gate that only refused would pass every refusal case and fail the two that must
    pass; a gate that only passed would fail the three refusals.
    """
    name, before, after, base, declared, expected = gate.FIXTURES[index]
    got = gate.run_fixture(before, after, base, declared)
    assert got == expected, (
        f"fixture {name!r} expected {expected or 'PASS'} and got {got or 'PASS'}"
    )


def test_the_fixture_set_covers_every_refusal_and_both_passing_directions(gate):
    """The roster of outcomes, derived from the fixtures rather than trusted.

    A parametrized check over five fixtures still passes if all five test the same thing, so the
    coverage is asserted separately: all three refusals must be witnessed, and both a PATCH and a
    MINOR arc must be witnessed passing.
    """
    outcomes = {expected for *_, expected in gate.FIXTURES}
    assert {"UNDERSHOOT", "EXCEED", "UNRULED", None} <= outcomes, (
        f"the fixtures witness {outcomes}. All three refusal directions and at least one passing "
        "arc have to be there — a refusal nobody has seen is a refusal nobody has"
    )
    passing = [(base, declared) for _, _, _, base, declared, exp in gate.FIXTURES if exp is None]
    kinds = {gate.single_step(base, gate.parse_version(declared)) for base, declared in passing}
    assert {"PATCH", "MINOR"} <= kinds, (
        f"the passing fixtures only witness {kinds}. A gate that refused every MINOR would pass a "
        "fixture set whose only passing arc is a PATCH"
    )


def test_a_two_step_jump_is_refused_rather_than_approximated(gate):
    """`1.2.0 → 1.4.0` is not a bump kind, and calling it MINOR would let a release skip a number.

    Nothing in this repository's history does this. The check is here because the reason it has not
    happened is that four numbers were typed carefully, which is the same reason 1.3.0 nearly
    shipped.
    """
    with pytest.raises(gate.Finding) as refusal:
        gate.single_step((1, 2, 0), (1, 4, 0))
    assert "not one semver step" in str(refusal.value)
    for legal, kind in (((1, 2, 1), "PATCH"), ((1, 3, 0), "MINOR"), ((2, 0, 0), "MAJOR")):
        assert gate.single_step((1, 2, 0), legal) == kind


# --------------------------------------------------------- the ruling mechanism, both directions


def _migrations(gate, tmp_path, body: str) -> None:
    """Point the gate's ruling reader at a written section instead of the real MIGRATIONS.md."""
    path = tmp_path / "MIGRATIONS.md"
    path.write_text(body)
    gate.MIGRATIONS = path


def test_a_recorded_ruling_resolves_an_ambiguity_and_the_gate_becomes_satisfiable(gate, tmp_path,
                                                                                 monkeypatch):
    """The exit. A gate whose only exit is 'guess' is a gate that will be made to guess.

    `tests/test_cdm_release.py::_package_tree_moved_since` carries this repository's scar from an
    unsatisfiable gate: its halves read different trees, so it demanded a section, refused the tree
    that had one, and its message invited deleting the section — the one wrong move.
    """
    monkeypatch.setattr(gate, "MIGRATIONS", gate.MIGRATIONS)
    _migrations(gate, tmp_path, "## History\n\n### Unreleased\n\n"
                "**Bump ruling.** `synapse_cdm/adapter.py:translate` — PATCH: the wording of a "
                "refusal message, and no caller's behaviour moves.\n")
    before = {"synapse_cdm/adapter.py": b'def translate(value):\n    return value + 1\n'}
    after = {"synapse_cdm/adapter.py": b'def translate(value):\n    return value + 2\n'}
    raw = gate.derive(before, after)
    assert {a.unit for a in raw.ambiguities} == {"synapse_cdm/adapter.py:translate"}

    ruled, recorded = gate.apply_rulings(raw, "Unreleased")
    assert not ruled.ambiguities, "the recorded ruling did not resolve the ambiguity it names"
    assert ruled.floor == "PATCH"
    assert recorded == {"synapse_cdm/adapter.py:translate": "PATCH"}
    assert any("ruled PATCH by a person" in s.reason for s in ruled.signals), (
        "the resolved signal does not say that a person ruled it. A derivation that absorbs a "
        "human judgment silently is a derivation that claims to have derived it"
    )


def test_a_ruling_that_outlives_its_case_is_refused_as_stale(gate, tmp_path, monkeypatch):
    """The second direction, which is the one that keeps the mechanism from becoming a list.

    An exemption nobody re-derives is the habit this gate replaced. `PUBLICATION.md` entry 8 exists
    because a deploy record was a habit; the ruling paragraph would go the same way if a ruling
    could sit in the file after the unit it names stopped changing.
    """
    monkeypatch.setattr(gate, "MIGRATIONS", gate.MIGRATIONS)
    _migrations(gate, tmp_path, "## History\n\n### Unreleased\n\n"
                "**Bump ruling.** `synapse_cdm/adapter.py:gone` — PATCH: a unit that no longer "
                "moves.\n")
    clean = gate.derive(
        {"synapse_cdm/MIGRATIONS.md": b"twelve\n"},
        {"synapse_cdm/MIGRATIONS.md": b"thirteen\n"})
    with pytest.raises(gate.Finding) as refusal:
        gate.apply_rulings(clean, "Unreleased")
    assert "does not find ambiguous" in str(refusal.value)
    assert "synapse_cdm/adapter.py:gone" in str(refusal.value)


def test_the_rulings_this_tree_records_are_the_rulings_its_arcs_need(gate):
    """No ruling in the real MIGRATIONS.md may be stale, and that is asserted by `measure()`.

    Stated as its own check because the assertion is easy to lose: `measure()` calls
    `apply_rulings` for both arcs, so a stale ruling in either section is already a failure. This
    test names the property so that a future refactor which stops consulting the rulings fails
    something whose name says what went.
    """
    _require_git()
    verdict = gate.measure()
    for unit in verdict.ruled:
        assert ":" in unit or "/" in unit, (
            f"the ruling for {unit!r} names no file. A ruling has to say WHICH unit it is about"
        )


# ---------------------------------------------------------------------- the command, as a command


def test_the_gate_runs_clean_from_the_command_line_with_its_mutation_check():
    """The whole thing, as a release round would run it, including that it can still fail.

    `--mutation-check` before the verdict, in one process, because that is the invocation
    `MIGRATIONS.md`'s release procedure names and a documented command that nothing runs is the
    class this repository keeps finding.
    """
    _require_git()
    out = subprocess.run([sys.executable, str(GATE_PATH), "--mutation-check"],
                         cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    assert "0 failed" in out.stdout
    for direction in ("UNDERSHOOT", "EXCEED", "UNRULED"):
        assert direction in out.stdout, (
            f"the mutation check did not witness a {direction}. Its output is what a release round "
            f"reads to know the gate can still fail:\n{out.stdout}"
        )


def test_the_json_measurement_is_what_a_round_would_quote():
    """`--json`, because a round that has to quote a verdict should not re-derive it by hand."""
    _require_git()
    out = subprocess.run([sys.executable, str(GATE_PATH), "--json"],
                         cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    measured = json.loads(out.stdout)
    assert measured["declared_kind"] == measured["derived_kind"]
    assert measured["arc"]["from"].startswith("v")
    assert measured["pending"]["kind"] in gate_kinds()


def gate_kinds() -> tuple[str, ...]:
    return ("NONE", "PATCH", "MINOR", "MAJOR")


# ------------------------------------------------------------------- the spec, stated and checked


def test_the_gate_states_the_claim_it_makes_true(gate):
    """The docstring is the specification, and it has to still contain one.

    The repository's gates carry their reasoning in the file that does the work, so that a reader
    who opens the check meets the incident rather than a pointer to it. A gate whose docstring lost
    the claim is a gate whose scope nobody can bound.
    """
    # Whitespace-flattened before the search, because every fragment below is a phrase and the
    # docstring is hard-wrapped: "no larger and no smaller" spans a line break in the file. A check
    # that failed on the wrap would be a check about the column the text happens to reach.
    doc = " ".join((gate.__doc__ or "").split())
    for fragment, why in (
            ("no larger and no smaller", "the claim: the bump kind is exact, not a floor to beat"),
            ("UNDERSHOOT", "the first refusal direction"),
            ("EXCEED", "the second, which is what happened"),
            ("UNRULED", "the third, which keeps the other two honest"),
            ("1.3.0", "the number that nearly shipped"),
            ("rule of shape", "how the table's non-exhaustive lists are extended, deliberately"),
            ("does not claim", "what the gate cannot prove, stated by the gate itself")):
        assert fragment.lower() in doc.lower(), (
            f"the gate's docstring no longer states {why} (looked for {fragment!r})"
        )
