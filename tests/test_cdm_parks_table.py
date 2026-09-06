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

    **AND WHEN THE REAL TABLE NO LONGER CARRIES THE SHAPE, IT IS RESTORED FROM THE TABLE AND NOT
    FROM A FIXTURE (M's ruling, 2026-09-06).** Park 7 closed on 2026-09-06 and took the last
    multi-member live claim with it — a claim naming one open park is not a set — so the domain
    this test mutates is empty on the table as it stands. `parks_table.reversed_to` reverses the
    most recent recorded closure in a copy, putting a real row back with the real claim this table
    withdrew when it closed; the mutation is then planted exactly as before. The refusal above is
    untouched: what is put back is this table's own sentence, derived at run time, and the reason
    is carried into every assertion below.
    """
    restored = parks_table.reversed_to("a set-claim naming an open park", parks)
    live = restored.parks
    named = sorted({m for c in live.set_claims for m in c.members if m in live.open_parks})
    assert named, restored.why
    assert parks_table.check_set_claims(live) == [], (restored.why, "the copy must start clean")
    for claim in restored.reinstated:
        assert claim in parks.retired, (claim, "a claim not withdrawn by this table")
    rows = dict(live.rows)
    victim = named[0]
    rows[victim] = rows[victim]._replace(closed=True, closed_on="2026-01-01")
    problems = parks_table.check_set_claims(live._replace(rows=rows))
    assert any("CLOSED MEMBER" in p for p in problems), (restored.why, problems)

    ghost = max(parks.rows) + 7
    claim = parks_table.SetClaim(in_row=min(parks.rows), line=0,
                                 members=(ghost,), text=f"parks {ghost}")
    problems = parks_table.check_set_claims(parks._replace(set_claims=(claim,)))
    assert any("PHANTOM MEMBER" in p for p in problems), problems


def test_self_membership_is_an_observation_and_never_a_problem(parks):
    """The formulation the table refuted: a partition may name its own row, and one did.

    **THE SUBJECT MOVED 2026-09-05 AND THE REFUSAL DID NOT.** This test was written when park 12's
    live claim read "the open members of this table are parks 7, 10 and 12" — a claim in park 12's
    row naming park 12 — and it asserted that `self_members` found it. Park 12 then CLOSED, its
    claim was re-quoted with `rows` and the live one replacing it names 7 and 10, so the table has
    no self-member today and `observed` is legitimately empty.

    So the assertion is inverted rather than deleted: what this module has to keep proving is that
    self-membership, WHEN IT OCCURS, is reported as an observation and never as a problem. That is
    now checked over whatever `self_members` returns — vacuously on today's table — plus a
    synthetic claim that guarantees the branch runs. Deleting the test would retire a refusal the
    table earned; asserting `observed` is non-empty would tie a rule about a shape to one row's
    passing membership.
    """
    for claim in parks_table.self_members(parks):
        assert not any(f"park {claim.in_row}" in p and "SELF" in p
                       for p in parks_table.check_set_claims(parks))
    # The branch, forced. A row whose claim names itself is not a complaint, whatever else is.
    # **THE CLAIM IT IS FORCED FROM IS THE TABLE'S, and after park 7's closure of 2026-09-06 the
    # table has no live one** — `reversed_to` reverses the closure that took it and hands back the
    # withdrawn claim beside its reopened row (M's ruling, 2026-09-06), which is the same refusal
    # this module's vacuity test states: a synthetic claim would be a fixture that can drift.
    restored = parks_table.reversed_to("a set-claim to observe", parks)
    assert restored.parks.set_claims, restored.why
    victim = restored.parks.set_claims[0]
    parks = restored.parks
    forged = parks_table.SetClaim(**{**victim._asdict(),
                                     "members": tuple(sorted({*victim.members, victim.in_row}))})
    forced = parks._replace(set_claims=(forged,))
    assert forced.set_claims[0].in_row in forced.set_claims[0].members
    assert parks_table.self_members(forced) == (forged,)
    assert not any("SELF" in p for p in parks_table.check_set_claims(forced))


def test_the_held_document_check_reads_filenames_and_not_word_boundaries():
    """The bug the gate's own mutation check caught: `\\b` never matches inside `ST0102.12.pdf`."""
    held = parks_table.held_series()
    if not held:
        pytest.skip("no pinned PDFs in this working tree — a fresh clone tracks none by design")
    assert "0102" in held, f"ST0102.12.pdf is on disk and its series is missing from {sorted(held)}"
    # **MOVED 2026-09-05 BY THE PARK 12 ROUND, WHICH IS THE ROUND THAT MADE IT HELD.** This line
    # read `assert "0902" not in held` and named ST 0902 as park 12's blocker. It was the last
    # unheld series in this repository's own spec directory; ST0902.8.pdf is on disk now and park
    # 12 is closed. The line is kept and inverted rather than dropped, because its job was never
    # the absence — it is the second half of the filename check, and a series that IS present is
    # the stronger witness that `held_series` reads filenames rather than word boundaries.
    assert "0902" in held, f"ST0902.8.pdf is on disk and its series is missing from {sorted(held)}"


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
    # **THE OPEN ROW THIS NEEDS IS ONE WHOSE BLOCKER A FILENAME DERIVES**, and park 7's closure on
    # 2026-09-06 left only park 10 open, whose blocker this table itself records as NOT DERIVABLE
    # — against which `UNVERIFIABLE HERE` can never fire, so the case would pass without running.
    # `reversed_to` reverses that closure in a copy and the row brings its own real blocker back
    # (M's ruling, 2026-09-06).
    restored = parks_table.reversed_to("an open row with a filename-derivable blocker", parks)
    states = [state for _, _, state in parks_table.blocker_existence(restored.parks, empty)]
    assert states, "no open rows would make this vacuous"
    assert not any("NOT held" in s for s in states), (restored.why, states)
    assert any("UNVERIFIABLE HERE" in s for s in states), (restored.why, states)


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

    # MISSING needs a SECOND open row to be left out of the stated groups, and park 7's closure on
    # 2026-09-06 left one. The copy `reversed_to` hands back reverses that closure (M's ruling,
    # 2026-09-06); the partition below is then a partition and not one group and one empty group.
    restored = parks_table.reversed_to("a MISSING to fire", parks)
    live = restored.parks
    first = live.open_parks[0]
    problems = parks_table.check_stated({"a": [first], "b": [first]}, live)
    assert any("OVERLAP" in p for p in problems), (restored.why, problems)
    assert any("MISSING" in p for p in problems), (restored.why, problems)

    half = len(live.open_parks) // 2
    whole = {"read": list(live.open_parks[:half]),
             "translate": list(live.open_parks[half:])}
    assert all(whole.values()), (restored.why, whole)
    assert parks_table.check_stated(whole, live) == []


# ------------------------------------------- the reversal, which is what a guard does at an
# emptying table. M's ruling, 2026-09-06, taken after round F put the fork up rather than guessing
# it: a guard whose shape the table no longer carries reverses the most recent recorded closure in
# its own copy — a real row, its real claim, its real blocker — and mutates that. The tests above
# each ask for one shape; these two are about the mechanism, and the second is the case the four
# above cannot reach today: THE TABLE ENDS ALL-CLOSED, and a repair that works at one open row and
# not at zero is a repair that has to be made twice.


def test_the_reversal_puts_back_this_tables_own_rows_and_its_own_withdrawn_claims(parks):
    """Nothing invented: every reopened row and every reinstated claim comes from the table."""
    for shape in parks_table.SHAPES:
        restored = parks_table.reversed_to(shape, parks)
        assert parks_table.SHAPES[shape](restored.parks), restored.why
        assert shape in restored.why, restored.why
        for number in restored.reopened:
            assert parks.rows[number].closed, f"park {number} was not a recorded closure"
            assert f"park {number}" in restored.why, restored.why
        for claim in restored.reinstated:
            assert claim in parks.retired, claim
            assert set(claim.members) <= set(restored.parks.open_parks), claim
        # A copy carrying the complaint already is a copy that witnesses nothing.
        assert parks_table.check_set_claims(restored.parks) == [], restored.why


def test_the_reversal_still_restores_every_shape_when_no_row_is_open_at_all(parks):
    """The table's own end state, which is the one no live reading can take yet.

    Every park closes eventually — that is what the table is for — and at zero open rows not one
    of the four shapes exists: no open park for a claim to name, no second open row for `MISSING`
    to be about, no multi-member live claim to observe, no open row to derive a blocker for. The
    closing dates here are the only invented thing and they are invented in a COPY, to order
    closures that have not happened; the rows, the claims and the blockers are the table's.
    """
    ended = parks._replace(
        rows={n: r._replace(closed=True, closed_on=r.closed_on or "2026-12-31")
              for n, r in parks.rows.items()},
        # A live set-claim cannot survive an all-closed table: every member it named would be a
        # closed row and `check_set_claims` would fail the sentence on its face, so this file's
        # `rows`-for-`parks` convention would have withdrawn it — which is where the copy puts it.
        set_claims=(),
        retired=parks.retired + parks.set_claims,
    )
    assert not ended.open_parks, ended.open_parks
    assert not ended.set_claims, ended.set_claims
    for shape, holds in parks_table.SHAPES.items():
        restored = parks_table.reversed_to(shape, ended)
        assert holds(restored.parks), restored.why
        assert restored.reopened, restored.why
        assert parks_table.check_set_claims(restored.parks) == [], restored.why
        for claim in restored.reinstated:
            assert claim in ended.retired, claim


# ------------------------------------------- the ROW pattern's SCOPE, which was the whole file
#
# THE DEFECT, RECORDED RATHER THAN DESCRIBED. `ROW` is `^\| \*\*(\d+)\*\* \|` and until
# 2026-08-30 `_rows` applied it to every line of `FORMAT_COVERAGE.md`. Exactly thirteen lines
# matched, the gate reported thirteen parks, and every check above was right for a reason nobody
# had checked: the file happened to hold one bold-numbered table. The 2026-08-29 adapter round
# found this and WORKED AROUND it, spelling its own new table with lettered rows — a convention
# that lives in a round record and in nothing executable. The next bold-numbered table inflates
# `rows`, and with it `open_parks`, `closed_parks` and the membership every set-claim is derived
# against, in silence and with no exit code.
#
# WHY A SILENT INFLATION IS WORSE THAN A CRASH HERE. The set-claim guard's whole subject is
# membership. A phantom park 14 in `rows` makes `PHANTOM MEMBER` unreachable for 14, and a
# fourteenth row read as open makes `check_stated`'s MISSING branch demand a group for a park that
# is not a park. The guard would go on passing while measuring the wrong set — the exact shape
# `gates/pin_paths.py` is named for.


def test_the_row_scan_is_scoped_to_the_parks_table_and_not_the_file(parks, tmp_path):
    """A second bold-numbered table is refused entry, and it could have got in.

    Built by APPENDING to the real document rather than from a fixture, so the subject is the
    parser against the file it actually reads — and both halves are asserted, because "the count
    did not move" proves nothing unless the mutation could have moved it.
    """
    text = parks_table.COVERAGE.read_text(encoding="utf-8")
    ghost = max(parks.rows) + 1
    mutated = text + (
        f"\n\n### Another table, bold-numbered\n\n"
        f"| # | Thing | Version | Note | Other |\n|---|---|---|---|---|\n"
        f"| **{ghost}** | not a park | v1 | not a delegation | none |\n")

    # THE MUTATION'S DOMAIN, and getting it wrong is on record. The unscoped scan must absorb
    # this row or the test proves nothing — and a three-column table does NOT get absorbed,
    # because `_cells`'s five-cell minimum drops it. The first draft used three columns and
    # passed against the unrepaired parser, which is a witness measuring nothing.
    assert parks_table._unscoped_row_numbers(mutated) == set(parks.rows) | {ghost}

    scoped = tmp_path / "FORMAT_COVERAGE.md"
    scoped.write_text(mutated, encoding="utf-8")
    derived = parks_table.derive(scoped)
    assert set(derived.rows) == set(parks.rows), (
        f"a row of another table was absorbed: {sorted(set(derived.rows) - set(parks.rows))}")
    assert derived.open_parks == parks.open_parks
    assert derived.closed_parks == parks.closed_parks


def test_the_five_cell_minimum_is_what_narrow_second_tables_hit_and_the_scope_is_the_rest(parks):
    """The exposure's real boundary, measured rather than assumed.

    `_cells` requires five cells, so a second bold-numbered table with fewer columns was already
    refused before the scope existed. Recording that here keeps the scope's witness from being
    "simplified" back into the shape that proves nothing, and keeps this module honest about how
    wide the original defect actually was: five-or-more-column tables only.
    """
    text = parks_table.COVERAGE.read_text(encoding="utf-8")
    ghost = max(parks.rows) + 1
    narrow = text + (f"\n\n| # | Thing | Note |\n|---|---|---|\n"
                     f"| **{ghost}** | not a park | not a delegation |\n")
    assert parks_table._unscoped_row_numbers(narrow) == set(parks.rows)


def test_the_scope_refuses_rather_than_guesses_when_its_anchor_does_not_resolve_once(tmp_path):
    """Zero headers and two headers are both refusals, and neither is a silent fallback.

    A scope that falls back to the whole file when it cannot find its table reintroduces the
    defect at exactly the moment somebody renames a column — which is the moment nobody is
    watching the parks table.
    """
    text = parks_table.COVERAGE.read_text(encoding="utf-8")
    for broken, why in ((text.replace(parks_table.TABLE_HEADER, "| # | Renamed |", 1), "zero"),
                        (text + "\n" + parks_table.TABLE_HEADER + "\n", "two")):
        with pytest.raises(parks_table.ParksTableNotFound):
            parks_table._table_span(broken)
        assert why  # named for the failure message


def test_the_scope_ends_at_the_table_and_not_at_the_next_blank_line(parks):
    """The span covers every row the table has and stops before the prose under it."""
    text = parks_table.COVERAGE.read_text(encoding="utf-8")
    start, end = parks_table._table_span(text)
    lines = text.split("\n")
    assert all(line.startswith("|") for line in lines[start:end]), "the span left the table"
    assert end < len(lines) and not lines[end].startswith("|"), "the span did not stop"
    assert len([1 for line in lines[start:end] if parks_table.ROW.match(line)]) == len(parks.rows)


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
