"""The parks table's set-claims, derived from the table instead of read off it.

WHY THIS EXISTS, AND IT IS THREE RECORDED DECAYS RATHER THAN A PRINCIPLE
-----------------------------------------------------------------------
`FORMAT_COVERAGE.md`'s parks table is this record's fastest-decaying surface, because its rows
cite the tree's most-moved parts: the held documents, the shipped adapters, the other rows. Three
instances are on record, each at its own site:

1. **A row denied its own artefact for a day.** `adapters/imapb_codec.py` landed and park 5's row
   went on saying the artefact was blocked, while the plan table's park 5 column had already
   recorded the landing. Two sites, one fact. Found by a disjunction sweep, not by a build.
2. **Four of the nine open rows had decayed in one pass** — parks 2, 3 and 6 and park 11's plan
   cell, each repaired with the reason stated in the row. One sweep, four rows.
3. **Park 12's partition outlived the closure of two of its own members**, unnoticed across the
   rounds that closed them. That is the failure this module is named for and the one it derives.

**THE THIRD IS A DIFFERENT SHAPE FROM THE FIRST TWO, AND IT IS THE SHAPE PROSE CANNOT CATCH.** The
first two are claims that went stale about *their own row's subject*, and re-reading the row finds
them. The third is a claim about a SET — a sentence in row 12 that names rows 1, 3, 4, 5, 8 and 11
— and **nothing in that sentence changes when one of those rows closes**. Re-reading row 12 as
carefully as you like cannot find it, because row 12 is not where the change happened. The cost is
`gates/pin_paths.py`'s recorded failure one class over: a claim whose parts nobody derives.

WHAT IS DERIVABLE HERE AND WHAT IS NOT, STATED RATHER THAN IMPLIED
-----------------------------------------------------------------
Derivable from the tree, and therefore checked here:

* which parks exist, which are closed, and on what date the row says so — from the table;
* whether a park's set-claim names a park that has closed, or one that does not exist — from the
  table, cross-referencing rows;
* whether the MISB series a park's `Parked` cell names is HELD — from the filenames under
  `fixtures/klv/spec/`, which is the existence half of "re-check each open row's blocker".

**AND IT CAUGHT A FOURTH INSTANCE ON ITS FIRST LIVE RUN, in a row nobody was looking at because it
is CLOSED.** Park 1's row listed park 4 among the parks still owning how an item is found in the
octets. Park 1 closed at 12:08 and park 4 at 14:04 the same day — 116 minutes — and the clause
stood for three days. It is the same shape as instance 3 and it is the argument for deriving rather
than reading: the sweep that repairs open rows would not have opened this one.

**NOT derivable, and the sweep entry says so rather than pretending:** whether a Reason cell's
quotation is what the pinned PDF actually says, whether a plan cell describes what its plan needs,
and whether a row's argument still follows. Those are readings of two documents, and sweep rule 11
names them as the human's half. This module refuses to give a green that covers them — `main()`
prints the unchecked surface on every run for that reason.

THE HELD-DOCUMENT CHECK IS AN EXISTENCE TEST AND NOTHING MORE
------------------------------------------------------------
It answers "is there a file under `spec/` whose name carries this series number", which is what
"re-checked for existence" means and is all a filename can support. It does **not** check the
edition, the digest or the contents — `gates/pin_paths.py` does that for pinned copies, and a
`Version required` cell naming `0902.8` against a held `ST0902.7.pdf` would pass here and fail
there. Reported as `held` / `not held` so a reader cannot mistake it for a pin check.

**A held series is not a lifted blocker and this module never says it is.** Parks 5 and 11 hold
every document their rows name and are blocked on their artefacts; park 8's blocker is a purchase.
So this reports a fact about the filesystem and leaves the verdict to the row.

**AND ON A FRESH CLONE IT REPORTS NOTHING RATHER THAN ABSENCE, which the clone verification caught
in this module's first pushed version.** Every pinned PDF is untracked by design, so a clone has
the records and not the documents — and the first draft printed `ST 0102 NOT held` beside a row
whose own cell says *held*, inviting a reader to "repair" a correct row from a measurement of their
checkout. **A wrong base is indistinguishable from a fresh clone** is the failure `gates/pin_paths.py`
is named for, and this is the same one on a different axis: when NO pinned PDF is present at all,
the state is `UNVERIFIABLE HERE`. The set-claim half needs no bytes and runs everywhere, which is
the split the round before this one had to make in `pin_paths` for the same reason.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Callable, Iterator, NamedTuple

REPO = pathlib.Path(__file__).resolve().parents[1]
PKG = REPO / "packages" / "cdm" / "synapse_cdm"
COVERAGE = PKG / "FORMAT_COVERAGE.md"
SPEC = PKG / "fixtures" / "klv" / "spec"

#: A parks-table row opens with its number as the first cell, bolded. **THIS PATTERN IS NOT A
#: SCOPE.** It ran over the WHOLE FILE until 2026-08-30 and matched exactly the thirteen rows of
#: the parks table, which is why nothing objected — but `FORMAT_COVERAGE.md` is thirteen thousand
#: lines and any SECOND bold-numbered table anywhere in it is absorbed into the parks set in
#: silence, inflating `rows`, `open_parks` and every set-claim derived over them. Found during the
#: 2026-08-29 adapter round and worked around by spelling that round's other table with lettered
#: rows — a convention nothing enforces. The pattern is now applied only inside `_table_span`.
ROW = re.compile(r"^\| \*\*(\d+)\*\* \|")
#: The parks table's own column header — THE SCOPE, and it is the header rather than a line number
#: because a line number is a fact about today's file. The `Reason, grounded in the delegation
#: table` cell is what makes it this table and not another: the parks table is MISB-only and every
#: row is a document MISP-2019.1 delegates to.
TABLE_HEADER = ("| # | Parked | Version required | Reason, grounded in the delegation table "
                "| Reopen condition |")
#: The `|---|---|` line under a header. Optional in the scan, so a table written without one is
#: read rather than silently dropped.
SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")
#: A row is closed when its `Parked` cell strikes the title through AND says so.
CLOSED = re.compile(r"\*\*CLOSED (\d{4}-\d{2}-\d{2})\*\*")
#: A set-claim names two or more parks in one breath: "parks 4, 5 and 8", "parks 1, 3, 11 and 12".
SET_CLAIM = re.compile(r"\bparks (\d+(?:\s*,\s*\d+)*(?:\s*,?\s*and\s+\d+)?)\b")
#: A MISB series number as a row's `Parked` cell names it: `MISB ST 0902`, `ST 1201 and ST 1303`.
#: FOUR DIGITS AND AN `ST`/`EG`/`RP` PREFIX, deliberately, and the two rows this misses are the
#: point rather than a gap: park 8 is `SMPTE ST 336`, a three-digit number from another custodian,
#: and park 10 is `MISP-2019.1`, a profile identifier and not a series at all. A pattern loose
#: enough to catch those catches `2017` out of `ST 336:2017` and `2018` out of "Nov 2018" as well,
#: and reports a year as a document. **They are reported as not derivable instead of guessed at** —
#: `gates/pin_paths.py` refuses an unknown convention for the same reason.
SERIES = re.compile(r"\b(?:ST|EG|RP)\s*(\d{4})\b")
#: A four-digit run in a filename. `ST0102.12.pdf` carries `0102`; the `\b` a first draft of this
#: used never matched, because `T0102` has no word boundary inside it and every MISB filename in
#: this tree is prefixed. It reported every held document as absent and the mutation check caught
#: it, which is the whole reason that check exists.
FILE_SERIES = re.compile(r"\d{4}")
#: A RETIRED claim: the same sentence, spelled with `rows` where it wrote `parks`. **THIS IS THE
#: TABLE'S OWN CONVENTION, READ BACK, AND NOT A NEW ONE.** Park 12's row states it: the `SET_CLAIM`
#: pattern "cannot read a tense, so a QUOTATION of a superseded claim must not spell it — but a LIVE
#: claim must, or the gate has nothing to derive", and "the one word that makes the string a claim
#: is the one word the quotation changes; the numbers, which are the part a reader checks, are
#: verbatim". Nothing read here is ever a problem or a green: a retired claim is a claim this table
#: once made, and `reversed_to` below needs exactly that — a REAL claim to put back beside a REAL
#: row when a closure has emptied a guard's domain.
RETIRED_CLAIM = re.compile(r"\brows (\d+(?:\s*,\s*\d+)*(?:\s*,?\s*and\s+\d+)?)\b")


class ParksTableNotFound(Exception):
    """The scope could not be resolved, which is refused rather than guessed at.

    Zero headers means the table was renamed or moved out of this file; two means there are two
    candidates and picking one is a coin toss. Both are louder failures than the file-global scan
    they replace, and that is the point — the defect this repair closes was silent.
    """


class Row(NamedTuple):
    """One parks-table row, as the table states it."""
    number: int
    line: int
    closed: bool
    closed_on: str | None
    title: str
    version_required: str
    reason: str
    reopen: str

    @property
    def state(self) -> str:
        return "closed" if self.closed else "open"


class SetClaim(NamedTuple):
    """A sentence in one row that names a SET of parks — the shape rule 11 exists for."""
    in_row: int
    line: int
    members: tuple[int, ...]
    text: str


class Parks(NamedTuple):
    """The parks table decomposed, derived from the table rather than narrated.

    WHY THIS IS A TYPE AND NOT A PARAGRAPH — the same reason `pin_paths.Decomposition` is. A row
    priced a park on a partition of seven other rows; two of the seven closed; the sentence went on
    reading as true because nothing in it had to change. A set nobody derives is a set nobody
    checks, and the total here does not even have a sum to fail to add up.
    """
    rows: dict[int, Row]
    set_claims: tuple[SetClaim, ...]
    #: The claims this table has WITHDRAWN, re-quoted with `rows` where they wrote `parks`. Never
    #: checked — a withdrawn claim cannot be stale — and read only by `reversed_to`.
    retired: tuple[SetClaim, ...] = ()

    @property
    def open_parks(self) -> tuple[int, ...]:
        return tuple(sorted(n for n, r in self.rows.items() if not r.closed))

    @property
    def closed_parks(self) -> tuple[int, ...]:
        return tuple(sorted(n for n, r in self.rows.items() if r.closed))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split(" | ")]


def _table_span(text: str) -> tuple[int, int]:
    """The half-open [start, end) line range of the parks table's BODY, 0-based.

    The body is the run of table lines after the header and its separator, ending at the first
    line that is not a table line. A row check that scans the whole file is a row check whose
    subject is "every bold-numbered table in a thirteen-thousand-line document", which is not what
    any caller here means.
    """
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines) if line.strip() == TABLE_HEADER]
    if len(heads) != 1:
        raise ParksTableNotFound(
            f"{len(heads)} line(s) match the parks table's column header, expected exactly 1. "
            f"The header this scopes on is:\n  {TABLE_HEADER}\n"
            "Zero means the table moved or its columns were renamed — repair this anchor rather "
            "than removing the scope, because an unscoped scan absorbs every other bold-numbered "
            "table in the file without saying so.")
    start = heads[0] + 1
    if start < len(lines) and SEPARATOR.match(lines[start].strip()):
        start += 1
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return start, end


def _unscoped_row_numbers(text: str) -> set[int]:
    """What `_rows` would yield with NO scope. Exists only so the scope's witness is honest.

    **THE FIVE-COLUMN NOTE.** `_cells`'s `len(cells) < 5` guard already excluded any second table
    with fewer than five columns, so a three-column synthetic table is absorbed by neither scan
    and witnesses nothing — the first draft of the scope's mutation used one and passed against
    the unrepaired parser. The absorbing shape is a second table with FIVE OR MORE columns, and
    that is what the witness has to build.
    """
    out: set[int] = set()
    for line in text.split("\n"):
        m = ROW.match(line)
        if m and len(_cells(line)) >= 5:
            out.add(int(m.group(1)))
    return out


def _rows(text: str) -> Iterator[Row]:
    start, end = _table_span(text)
    for i, line in enumerate(text.split("\n")[start:end], start=start + 1):
        m = ROW.match(line)
        if not m:
            continue
        cells = _cells(line)
        if len(cells) < 5:
            continue
        title, version, reason, reopen = cells[1], cells[2], cells[3], cells[4]
        closed = CLOSED.search(title)
        yield Row(number=int(m.group(1)), line=i,
                  closed=bool(closed and "~~" in title),
                  closed_on=closed.group(1) if closed else None,
                  title=title, version_required=version, reason=reason, reopen=reopen)


def _members(blob: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", blob))


def derive(path: pathlib.Path | None = None) -> Parks:
    """Every part of the parks table, counted from the table itself."""
    text = (path or COVERAGE).read_text(encoding="utf-8")
    rows = {r.number: r for r in _rows(text)}
    claims: list[SetClaim] = []
    retired: list[SetClaim] = []
    for row in rows.values():
        for cell in (row.reason, row.reopen):
            for pattern, into in ((SET_CLAIM, claims), (RETIRED_CLAIM, retired)):
                for m in pattern.finditer(cell):
                    members = _members(m.group(1))
                    if len(members) > 1:
                        into.append(SetClaim(in_row=row.number, line=row.line,
                                             members=members, text=m.group(0)))
    return Parks(rows=dict(sorted(rows.items())), set_claims=tuple(claims),
                 retired=tuple(retired))


def held_series(spec: pathlib.Path | None = None) -> frozenset[str]:
    """The series numbers a filename under `spec/` carries. An EXISTENCE test, not a pin check."""
    spec = spec or SPEC
    if not spec.is_dir():
        return frozenset()
    found: set[str] = set()
    for f in spec.glob("*.pdf"):
        found.update(FILE_SERIES.findall(f.name))
    return frozenset(found)


def check_set_claims(p: Parks | None = None) -> list[str]:
    """Every set-claim re-derived against current membership. THE guard.

    Three complaints, and the FIRST is the one no amount of re-reading the row can make:

    * **CLOSED MEMBER** — a claim names a park that has since closed. The recorded failure's shape
      exactly: the sentence is unchanged and untrue, and the change that made it untrue happened in
      a different row.
    * **PHANTOM MEMBER** — a claim names a park number the table does not have.

    **SELF-MEMBERSHIP WAS SPECCED AS A THIRD COMPLAINT AND IS REFUSED**, measured against the table
    rather than argued about. Park 12's partition names park 12, and always did: the row prices its
    own park by saying which parks together suffice, so its own membership is the claim's subject
    and not a slip. The rule would have fired three times on the one row it was written to protect.
    It is reported by `main()` as an observation and is not a problem, which is the treatment this
    record gives a formulation the tree refutes.
    """
    p = derive() if p is None else p
    problems: list[str] = []
    for claim in p.set_claims:
        for member in claim.members:
            row = p.rows.get(member)
            if row is None:
                problems.append(
                    f"PHANTOM MEMBER: park {claim.in_row}'s claim {claim.text!r} (line "
                    f"{claim.line}) names park {member}, which this table does not have")
            elif row.closed:
                problems.append(
                    f"CLOSED MEMBER: park {claim.in_row}'s claim {claim.text!r} (line "
                    f"{claim.line}) names park {member}, CLOSED {row.closed_on}. A statement of "
                    f"what is still needed that lists something no longer needed is stale on its "
                    f"face — and nothing in park {claim.in_row}'s row changed when park {member} "
                    f"closed, which is why re-reading the row cannot find this")
    return problems


def self_members(p: Parks | None = None) -> tuple[SetClaim, ...]:
    """Claims naming their own row. An OBSERVATION — see `check_set_claims`'s refusal note."""
    p = derive() if p is None else p
    return tuple(c for c in p.set_claims if c.in_row in c.members)


#: The shapes the guards need FROM THE TABLE, each a predicate over a derived `Parks`, and the
#: strings are M's ruling's own words for them (2026-09-06). **NAMED RATHER THAN INLINE BECAUSE A
#: GUARD AND ITS REPAIR MAY NOT SPELL THE SHAPE TWICE**: this module's `--mutation-check` and
#: `tests/test_cdm_parks_table.py` both ask for them by name, so a shape that changes changes once.
SHAPES: dict[str, Callable[[Parks], bool]] = {
    "a set-claim naming an open park":
        lambda p: any(m in p.open_parks for c in p.set_claims for m in c.members),
    "a MISSING to fire":
        lambda p: len(p.open_parks) > 1,
    "a set-claim to observe":
        lambda p: bool(p.set_claims),
    "an open row with a filename-derivable blocker":
        lambda p: any(SERIES.search(p.rows[n].title) for n in p.open_parks),
}


class Reversal(NamedTuple):
    """A temporary copy of the table with recorded closures reversed, and the sentence naming them.

    `why` is not decoration: every guard that asks for a reversal puts it in its own failure
    message, because a check that quietly re-shapes its subject is a check whose green means
    something other than it appears to.
    """
    parks: Parks
    reopened: tuple[int, ...]
    reinstated: tuple[SetClaim, ...]
    why: str


def _reinstate(p: Parks) -> tuple[Parks, tuple[SetClaim, ...]]:
    """Retired claims every member of which is open in THIS COPY, live again in this copy only."""
    open_now = set(p.open_parks)
    live = {(c.in_row, c.members) for c in p.set_claims}
    back = tuple(c for c in p.retired
                 if set(c.members) <= open_now and (c.in_row, c.members) not in live)
    return p._replace(set_claims=tuple(p.set_claims) + back), back


def reversed_to(shape: str, p: Parks | None = None) -> Reversal:
    """The table with its most recent recorded closures reversed, until `shape` holds again.

    **WHY THIS EXISTS, AND IT IS A ROW CLOSING RATHER THAN A PRINCIPLE.** Every guard over this
    table is exercised BY MUTATING THE REAL TABLE, and each needs some shape to mutate: a set-claim
    naming an open park, a `MISSING` that can fire, a set-claim to observe, an open row whose
    blocker a filename derives. The table's whole purpose is to empty, and each closure takes one
    of those shapes away — park 7's closure on 2026-09-06 took the last multi-member live claim
    with it, because a claim naming one open park is not a set, and the table ends all-closed,
    where none of the four shapes exists at all.

    **THE REPAIR THAT IS REFUSED.** A synthetic claim spelling the shape is what
    `test_the_set_claim_guard_is_not_vacuous_in_either_direction`'s own docstring rules out, citing
    `synapse_cdm/README.md`'s sweep rule 1: a fixture stating a fact is itself a live site, and it
    can drift away from the table it stands for.

    **WHAT IS DONE INSTEAD (M's ruling, 2026-09-06).** A guard that finds its shape gone reverses,
    IN ITS OWN COPY ONLY, the most recent recorded closure — and then the next-most-recent, until
    the shape is back. A reopened row is a real row; the claims put back beside it are this table's
    own withdrawn claims, re-quoted with `rows` under the convention park 12's row records, and put
    back only when EVERY member of the claim is open again in the copy; the blocker is the one the
    row's own title carries. Nothing is invented, and which closure is reversed is derived here at
    run time — never typed in a guard, which would be the drifting fixture one level up.

    The copy is required to be CLEAN (`check_set_claims` empty) before it is handed back, because a
    copy that already carries the complaint a guard is about to provoke witnesses nothing.
    """
    p = derive() if p is None else p
    holds = SHAPES[shape]
    if holds(p):
        return Reversal(p, (), (), f"the table as it stands carries {shape}; no closure reversed")
    order = sorted((r for r in p.rows.values() if r.closed),
                   key=lambda r: (r.closed_on or "", r.number), reverse=True)
    rows = dict(p.rows)
    reopened: list[int] = []
    for row in order:
        rows[row.number] = row._replace(closed=False, closed_on=None)
        reopened.append(row.number)
        trial, back = _reinstate(p._replace(rows=dict(rows)))
        if holds(trial) and not check_set_claims(trial):
            named = "; ".join(f"park {n} (CLOSED {p.rows[n].closed_on})" for n in reopened)
            claims = ", ".join(f"{c.text!r} in row {c.in_row}" for c in back)
            return Reversal(trial, tuple(reopened), back, (
                f"the table as it stands does not carry {shape}, so this check reversed the most "
                f"recent recorded closure(s) in its own copy — {named}"
                + (f", putting back this table's own withdrawn claim(s) {claims}" if back else "")
                + ". The row, its claim and its blocker are the table's; nothing is invented, and "
                  "which closure this is was derived from the table just now, not typed here"))
    trial, back = _reinstate(p._replace(rows=rows))
    return Reversal(trial, tuple(reopened), back, (
        f"NO reversal of this table's recorded closures restores {shape}: every closed row was "
        f"reopened ({sorted(reopened)}) and the shape still does not hold. The guard asking for it "
        f"cannot be exercised against this table and is to be rewritten or retired with its "
        f"reason, never weakened into a synthetic fixture"))


def check_stated(stated: dict[str, list[int]], p: Parks | None = None) -> list[str]:
    """Compare a partition SOMEBODY STATED against the table's current membership.

    `pin_paths.check_stated`'s form, moved onto sets instead of counts, because that is the axis
    this failure moved on. PHANTOM for a member the table does not have, CLOSED for one it has and
    has closed, MISSING for an open park the statement leaves out of every group, and OVERLAP for
    a park claimed by two groups of what is offered as a partition.
    """
    p = derive() if p is None else p
    problems: list[str] = []
    claimed: dict[int, list[str]] = {}
    for group, members in sorted(stated.items()):
        for member in members:
            claimed.setdefault(member, []).append(group)
            row = p.rows.get(member)
            if row is None:
                problems.append(
                    f"PHANTOM in group {group!r}: park {member} is not a row of this table, whose "
                    f"rows are {sorted(p.rows)}")
            elif row.closed:
                problems.append(
                    f"CLOSED in group {group!r}: park {member} closed {row.closed_on}")
    for member, groups in sorted(claimed.items()):
        if len(groups) > 1:
            problems.append(
                f"OVERLAP: park {member} is claimed by {groups}, which a partition may not do")
    for member in p.open_parks:
        if member not in claimed:
            problems.append(
                f"MISSING: park {member} is open and no stated group names it")
    return problems


def blocker_existence(p: Parks | None = None, spec: pathlib.Path | None = None
                      ) -> list[tuple[int, str, str]]:
    """For every OPEN row, whether the series its `Version required` cell names is held on disk.

    The existence half of "re-check each open row's blocker", and no more than that. A held series
    does NOT mean the park's blocker has lifted — parks 5 and 11 hold every document they name and
    are blocked on their artefacts — so this reports a fact and never a verdict.
    """
    p = derive() if p is None else p
    held = held_series(spec)
    out: list[tuple[int, str, str]] = []
    for number in p.open_parks:
        row = p.rows[number]
        series = sorted(set(SERIES.findall(row.title)))
        if not series:
            out.append((number, row.version_required,
                        "NOT DERIVABLE from a filename — this row's document is not a MISB "
                        "four-digit series, so a human reads it"))
        elif not held:
            out.append((number, row.version_required,
                        "UNVERIFIABLE HERE — no pinned PDF is in this working tree at all, so an "
                        "absence measures the clone and not the park"))
        else:
            out.append((number, row.version_required,
                        ", ".join(f"ST {s} {'held' if s in held else 'NOT held'}"
                                  for s in series)))
    return out


#: The part of a parks row that no derivation reaches, printed on every run so a green cannot be
#: mistaken for a clean bill. Sweep rule 11 names these as the human's half.
NOT_DERIVABLE = (
    "a Reason cell's quotation, against the pinned document's own bytes",
    "a plan cell, against what that plan actually needs",
    "whether a row's argument still follows from what it cites",
)


def _report(p: Parks, problems: list[str]) -> int:
    print(f"rows          {len(p.rows)} — {len(p.open_parks)} open {list(p.open_parks)}, "
          f"{len(p.closed_parks)} closed {list(p.closed_parks)}")
    print(f"set-claims    {len(p.set_claims)} across "
          f"{len(sorted({c.in_row for c in p.set_claims}))} row(s)")
    for claim in p.set_claims:
        members = ", ".join(
            f"{m}{'' if m in p.open_parks else '(closed)'}" for m in claim.members)
        print(f"    park {claim.in_row:>2}  {claim.text!r} -> {members}")
    observed = self_members(p)
    if observed:
        print(f"self-members  {len(observed)} claim(s) naming their own row — an observation and "
              f"not a problem, see check_set_claims")
        for claim in observed:
            print(f"    park {claim.in_row:>2}  {claim.text!r}")
    print("blockers      existence only, by series number under fixtures/klv/spec/")
    for number, cell, state in blocker_existence(p):
        print(f"    park {number:>2}  {cell:<28} {state}")
    print("not derived   the sweep's human half, unchecked here and not covered by this exit code:")
    for item in NOT_DERIVABLE:
        print(f"    - {item}")
    for problem in problems:
        print(f"PROBLEM       {problem}")
    print(f"{len(p.rows)} rows, {len(p.set_claims)} set-claims, {len(problems)} failed")
    return 1 if problems else 0


def _mutation_check() -> int:
    """Prove each branch can fail, on the real table, by mutating it in the recorded direction.

    A guard nobody has seen fail is a guard nobody has tested. Each mutation is asserted to have a
    non-empty domain before it is applied, because a mutation that changes nothing is a case that
    passes without running — `gates/pin_paths.py` records that lesson and this module inherits it.
    """
    p = derive()
    cases = 0
    reversals: list[str] = []

    # 1. CLOSED MEMBER — reopen nothing, but close a park some claim names. The domain is asserted
    #    non-empty AFTER the reversal, because at one open row the table has no live set-claim at
    #    all and the reversal is what makes this case exercisable — see `reversed_to`.
    one = reversed_to("a set-claim naming an open park", p)
    q = one.parks
    named = sorted({m for c in q.set_claims for m in c.members if m in q.open_parks})
    assert named, one.why
    victim = named[0]
    rows = dict(q.rows)
    rows[victim] = rows[victim]._replace(closed=True, closed_on="2026-01-01")
    problems = check_set_claims(q._replace(rows=rows))
    assert any("CLOSED MEMBER" in x and f"park {victim}," in x for x in problems), (one.why,
                                                                                   problems)
    cases += 1
    if one.reopened:
        reversals.append(f"case 1: {one.why}")

    # 2. PHANTOM MEMBER — a claim naming a row the table does not have.
    ghost = max(p.rows) + 7
    assert ghost not in p.rows
    claim = SetClaim(in_row=min(p.rows), line=0, members=(ghost, min(p.rows)),
                     text=f"parks {ghost} and {min(p.rows)}")
    problems = check_set_claims(p._replace(set_claims=(claim,)))
    assert any("PHANTOM MEMBER" in x for x in problems), problems
    cases += 1

    # 3. The guard is not vacuous in the other direction: the real table passes once repaired.
    assert check_set_claims(p) == [], check_set_claims(p)
    cases += 1

    # 4. check_stated — OVERLAP and MISSING, on the axis a partition fails on. MISSING needs a
    #    SECOND open row to be left out; one open row is claimed by both halves and nothing is
    #    missing, so the reversal supplies the shape rather than the case going quiet.
    four = reversed_to("a MISSING to fire", p)
    r = four.parks
    groups = {"a": [r.open_parks[0]], "b": [r.open_parks[0]]}
    problems = check_stated(groups, r)
    assert any("OVERLAP" in x for x in problems), (four.why, problems)
    assert any("MISSING" in x for x in problems), (four.why, problems)
    cases += 1

    # 5. check_stated accepts the table's own open set partitioned once. On the same copy as case
    #    4: a partition of one row is two groups one of which is empty, which accepts for the wrong
    #    reason.
    half = len(r.open_parks) // 2
    whole = {"read": list(r.open_parks[:half]), "translate": list(r.open_parks[half:])}
    assert all(whole.values()), (four.why, whole)
    assert check_stated(whole, r) == [], (four.why, check_stated(whole, r))
    cases += 1
    if four.reopened:
        reversals.append(f"cases 4 and 5: {four.why}")

    # 6. THE SCOPE, witnessed against the defect it closes: a SECOND bold-numbered table in the
    #    same file. The unscoped scan absorbs its rows and says nothing; the scoped one does not
    #    see them at all. Both halves are asserted, because "the count did not move" is only
    #    evidence if the mutation could have moved it.
    text = COVERAGE.read_text(encoding="utf-8")
    ghost = max(p.rows) + 1
    wide = text + (f"\n\n### A second table that is not the parks table\n\n"
                   f"| # | Thing | Version | Note | Other |\n|---|---|---|---|---|\n"
                   f"| **{ghost}** | not a park | v1 | not a delegation | none |\n")
    assert ghost in _unscoped_row_numbers(wide), (
        "the synthetic second table is not absorbed by the unscoped scan, so this mutation "
        "proves nothing about the scope — see the FIVE-COLUMN note above")
    assert _unscoped_row_numbers(wide) == set(p.rows) | {ghost}
    assert {r.number for r in _rows(wide)} == set(p.rows), (
        f"the scope absorbed a row of another table: "
        f"{sorted({r.number for r in _rows(wide)} - set(p.rows))}")
    cases += 1

    # 6b. And the narrower shape, which `_cells` already refused before the scope existed. Kept
    #     as a case so a later round cannot "simplify" the five columns out of case 6 and leave a
    #     witness that passes against the unscoped scan — which is what the first draft did.
    narrow = text + (f"\n\n| # | Thing | Note |\n|---|---|---|\n"
                     f"| **{ghost}** | not a park | not a delegation |\n")
    assert _unscoped_row_numbers(narrow) == set(p.rows), (
        "the five-cell minimum no longer excludes a three-column table; case 6's note is stale")
    cases += 1

    # 7. And the scope REFUSES rather than guesses when its anchor does not resolve once.
    for broken, why in ((text.replace(TABLE_HEADER, "| # | Renamed |", 1), "zero"),
                        (text + "\n" + TABLE_HEADER + "\n", "two")):
        try:
            _table_span(broken)
        except ParksTableNotFound:
            pass
        else:
            raise AssertionError(f"the scope resolved with {why} header(s) instead of refusing")
    cases += 1

    for note in reversals:
        print(f"reversal      {note}")
    print(f"{cases} mutations, no survivors")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mutation-check", action="store_true",
                    help="prove each branch can fail, on the real table")
    args = ap.parse_args(argv)
    if args.mutation_check:
        return _mutation_check()
    p = derive()
    return _report(p, check_set_claims(p))


if __name__ == "__main__":
    sys.exit(main())
