"""The parks table's set-claims stay derived, and the guard that derives them can still fail.

Sweep rule 11 in `synapse_cdm/README.md` puts the parks table on the per-round sweep list. The
derivable half of that rule is `gates/parks_table.py`; this module is what keeps the derivation
honest between rounds.

**WHY A TEST AND NOT JUST THE GATE.** The recorded failure is a claim that stays true-looking
while a row somewhere else changes. Nothing about it is loud. A gate somebody remembers to run is
exactly the arrangement that let park 12's partition outlive two closures and park 1's clause
outlive one by 116 minutes, so the check runs in the suite as well.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gates"))

import parks_table  # noqa: E402


@pytest.fixture(scope="module")
def parks():
    return parks_table.derive()


def test_the_table_is_found_and_has_the_shape_a_row_check_needs(parks):
    """A parser that finds no rows passes every row check vacuously."""
    assert len(parks.rows) >= 13, parks.rows
    assert set(parks.rows) == set(range(1, len(parks.rows) + 1)), "park numbers must be contiguous"
    assert parks.open_parks, "a table with no open parks makes the blocker check vacuous"
    assert parks.closed_parks, "a table with no closed parks makes the CLOSED MEMBER check vacuous"


def test_every_closed_row_states_a_closing_date(parks):
    for number in parks.closed_parks:
        assert parks.rows[number].closed_on, f"park {number} is struck through with no date"


def test_no_set_claim_names_a_closed_or_absent_park(parks):
    """THE guard. A set-claim decays silently when its members move."""
    assert parks_table.check_set_claims(parks) == [], parks_table.check_set_claims(parks)


def test_the_set_claim_guard_is_not_vacuous_in_either_direction(parks):
    """It must be able to fail, and the table must be able to pass it.

    Mutating the real table rather than a synthetic one, because a fixture that spells the shape
    is a fixture that can drift away from it — and `synapse_cdm/README.md`'s sweep rule 1 records
    that a synthetic fixture stating a fact is itself a live site.
    """
    named = sorted({m for c in parks.set_claims for m in c.members if m in parks.open_parks})
    assert named, "no set-claim names an open park; this test would prove nothing"
    rows = dict(parks.rows)
    victim = named[0]
    rows[victim] = rows[victim]._replace(closed=True, closed_on="2026-01-01")
    problems = parks_table.check_set_claims(parks._replace(rows=rows))
    assert any("CLOSED MEMBER" in p for p in problems), problems

    ghost = max(parks.rows) + 7
    claim = parks_table.SetClaim(in_row=min(parks.rows), line=0,
                                 members=(ghost,), text=f"parks {ghost}")
    problems = parks_table.check_set_claims(parks._replace(set_claims=(claim,)))
    assert any("PHANTOM MEMBER" in p for p in problems), problems


def test_self_membership_is_an_observation_and_never_a_problem(parks):
    """The formulation the table refuted: park 12's partition names park 12, and means to."""
    observed = parks_table.self_members(parks)
    assert observed, "park 12's partition names its own row; if that changed, revisit the refusal"
    for claim in observed:
        assert not any(f"park {claim.in_row}" in p and "SELF" in p
                       for p in parks_table.check_set_claims(parks))


def test_the_held_document_check_reads_filenames_and_not_word_boundaries():
    """The bug the gate's own mutation check caught: `\\b` never matches inside `ST0102.12.pdf`."""
    held = parks_table.held_series()
    if not held:
        pytest.skip("no pinned PDFs in this working tree — a fresh clone tracks none by design")
    assert "0102" in held, f"ST0102.12.pdf is on disk and its series is missing from {sorted(held)}"
    assert "0902" not in held, "ST 0902 is park 12's blocker and is NOT held; see its row"


def test_every_open_row_reports_its_blocker_as_derived_or_as_a_human_read(parks):
    """No open row may go unreported, and an underivable one must SAY so rather than read clean."""
    reported = {number for number, _, _ in parks_table.blocker_existence(parks)}
    assert reported == set(parks.open_parks), f"{reported} vs {parks.open_parks}"
    states = {number: state for number, _, state in parks_table.blocker_existence(parks)}
    for number, state in states.items():
        # Three legitimate answers and no fourth: a reading, "a human reads this row", or "this
        # working tree cannot say". The last is what a fresh clone gets, so this assertion has to
        # admit it or the module fails everywhere its own gate is most careful.
        assert (("held" in state) or ("NOT DERIVABLE" in state)
                or ("UNVERIFIABLE HERE" in state)), (number, state)


def test_an_empty_spec_directory_reports_unverifiable_and_never_absence(parks, tmp_path):
    """The defect the fresh-clone verification caught in this module's first pushed version.

    Every pinned PDF is untracked by design, so a clone has the records and not the documents. A
    report that prints `NOT held` there is measuring the checkout and describing the park, beside a
    row whose own cell says *held* — which invites a reader to repair a correct row. `pin_paths` is
    named for that failure on a different axis.
    """
    empty = tmp_path / "spec"
    empty.mkdir()
    assert parks_table.held_series(empty) == frozenset()
    states = [state for _, _, state in parks_table.blocker_existence(parks, empty)]
    assert states, "no open rows would make this vacuous"
    assert not any("NOT held" in s for s in states), states
    assert any("UNVERIFIABLE HERE" in s for s in states), states


def test_the_set_claim_half_needs_no_bytes_at_all(parks, tmp_path):
    """The split: the record half runs everywhere, the bytes half says when it cannot."""
    empty = tmp_path / "spec"
    empty.mkdir()
    assert parks_table.check_set_claims(parks) == []
    reported = {n for n, _, _ in parks_table.blocker_existence(parks, empty)}
    assert reported == set(parks.open_parks)


def test_check_stated_refuses_a_partition_the_table_refutes(parks):
    """`pin_paths.check_stated`'s form, on sets. Each branch proven to fire."""
    closed = parks.closed_parks[0]
    problems = parks_table.check_stated({"g": [closed]}, parks)
    assert any("CLOSED" in p for p in problems), problems

    ghost = max(parks.rows) + 7
    problems = parks_table.check_stated({"g": [ghost]}, parks)
    assert any("PHANTOM" in p for p in problems), problems

    first = parks.open_parks[0]
    problems = parks_table.check_stated({"a": [first], "b": [first]}, parks)
    assert any("OVERLAP" in p for p in problems), problems
    assert any("MISSING" in p for p in problems), problems

    half = len(parks.open_parks) // 2
    whole = {"read": list(parks.open_parks[:half]),
             "translate": list(parks.open_parks[half:])}
    assert parks_table.check_stated(whole, parks) == []


def test_the_gate_names_what_it_does_not_check():
    """A green that reads as a clean bill is the defect rule 10 is about."""
    assert parks_table.NOT_DERIVABLE, "the unchecked surface must be stated, not implied"
    for item in parks_table.NOT_DERIVABLE:
        assert item.strip() and len(item) > 20, item


def test_the_gate_runs_clean_and_its_mutation_check_passes(capsys):
    assert parks_table.main([]) == 0
    out = capsys.readouterr().out
    assert "0 failed" in out, out
    assert "not derived" in out, "the run must print the surface it does not cover"
    assert parks_table.main(["--mutation-check"]) == 0
