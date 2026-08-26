"""Scripted edits that fail closed: a unique-anchor rule and a diff-stat bound.

WHY THIS EXISTS, AND IT IS AN INCIDENT RATHER THAN A PRINCIPLE
--------------------------------------------------------------
On 2026-08-26 the witnessed-set round rewrote a section of `FORMAT_COVERAGE.md` with a script
shaped like this:

    start = s.index("### The fixtures — planned here, before they exist")
    end   = s.index("## STANAG 5527 — NATO Friendly Force Tracking Systems", start)
    s = s[:start] + new + s[end:]

**That heading appears TWICE in the document** — the NITS row set has one and the KLV row set has
one — and `str.index` returns the first. The slice therefore ran from the NITS fixture plan to the
end of the KLV section and **~5 000 lines were deleted in one write**: the whole of GMTIF, CAT048,
CAT034, CAT062, CAT023 and the KLV section the edit was meant to touch. Nothing raised. The file was
still valid Markdown, the script reported success, and the deletion was caught only because the next
`git diff --stat` read `-5087` where a section rewrite should read tens of lines.

**The near-miss is the point.** Had the round committed before reading a diff stat, a green suite
would not have caught it either: the tests that failed afterwards failed for *unrelated* reasons and
would have been "fixed" against a mutilated document. The two properties that were missing are both
cheap and neither is a matter of care:

1. **an anchor that is not unique is a bug, not a coin flip** — `str.index`, `str.replace` and
   `re.sub` all silently pick one or all, and every one of those defaults is wrong for a
   surgical edit;
2. **a batch edit knows roughly how much it should delete**, and one that deletes two orders of
   magnitude more has failed whatever it was trying to do.

WHAT THIS MODULE IS NOT
-----------------------
It is not a resolution and it is not a linter over other people's scripts — nothing here can force
an editing script to import it. What it is: the two checks written once, correct, with the failure
messages that make the diagnosis immediate, so that reaching for them is easier than re-typing
`str.replace`. `tests/test_cdm_scripted_edits.py` holds them to their contract in both directions,
including the exact shape of the incident above.

USAGE

    from gates.scripted_edit import replace_unique, bounded_batch

    with bounded_batch(max_deleted_lines=80) as batch:
        replace_unique(DOC, old_paragraph, new_paragraph)
        replace_unique(DOC, old_table_row, new_table_row)
    print(batch.report)          # deletions actually observed, per file

`replace_unique` refuses unless the anchor occurs exactly once. `bounded_batch` reads
`git diff --numstat` before and after and raises if the deletions exceed the bound the caller
stated — after the writes, which is deliberate: the point is to stop a bad edit reaching a COMMIT,
and a working tree is recoverable with `git checkout` while a pushed commit is not.
"""
from __future__ import annotations

import contextlib
import dataclasses
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[1]


class AnchorNotUnique(ValueError):
    """An anchor that matched a number of times other than one. Fails closed, never writes."""


class BatchTooDestructive(RuntimeError):
    """A batch edit deleted more than the caller said it should. The tree is left for inspection."""


def occurrences(path: pathlib.Path | str, anchor: str) -> int:
    """How many times `anchor` occurs in `path`. Non-overlapping, like `str.count`."""
    return pathlib.Path(path).read_text().count(anchor)


def replace_unique(path: pathlib.Path | str, anchor: str, replacement: str) -> pathlib.Path:
    """Replace `anchor` with `replacement`, and refuse unless it occurs EXACTLY once.

    Both failure directions raise, and both matter:

    * **zero** means the anchor has drifted — the sentence was reflowed, a character was
      normalised — and a `str.replace` would have written the file back unchanged and reported
      success. A silent no-op is the failure mode that makes somebody re-run a script twice and
      then edit by hand;
    * **two or more** is the incident this module is named for. The message prints every match's
      line number, because "your anchor is ambiguous" is not actionable and "it matches at line
      4101 and line 9135" is.

    The file is only written on the unique path, so a refusal leaves the tree untouched.
    """
    path = pathlib.Path(path)
    text = path.read_text()
    count = text.count(anchor)
    if count != 1:
        lines = [i for i, line in enumerate(text.splitlines(), 1) if anchor.splitlines()[0] in line]
        head = anchor.splitlines()[0][:70] if anchor else ""
        raise AnchorNotUnique(
            f"{path.relative_to(REPO) if path.is_relative_to(REPO) else path}: the anchor occurs "
            f"{count} time(s) and a scripted edit needs exactly 1.\n"
            f"  anchor starts: {head!r}\n"
            f"  its first line appears at line(s): {lines[:12]}\n"
            + ("  ZERO matches means the anchor drifted — a str.replace here would have written "
               "the file back unchanged and reported success.\n" if count == 0 else
               "  TWO OR MORE is the 2026-08-26 incident: `str.index` took the first, the slice "
               "ran to the wrong section boundary, and ~5 000 lines went in one write.\n")
            + "  Widen the anchor until it is unique — include the line above or below it — "
              "rather than reaching for an index."
        )
    path.write_text(text.replace(anchor, replacement, 1))
    return path


@dataclasses.dataclass
class BatchReport:
    """What a batch actually did, per file, as git measures it."""

    added: dict[str, int] = dataclasses.field(default_factory=dict)
    deleted: dict[str, int] = dataclasses.field(default_factory=dict)

    @property
    def total_deleted(self) -> int:
        return sum(self.deleted.values())

    @property
    def total_added(self) -> int:
        return sum(self.added.values())

    def __str__(self) -> str:
        if not self.deleted and not self.added:
            return "no tracked file changed"
        rows = sorted(set(self.added) | set(self.deleted))
        return "\n".join(f"  +{self.added.get(f, 0):<6} -{self.deleted.get(f, 0):<6} {f}"
                         for f in rows)


def _numstat() -> tuple[dict[str, int], dict[str, int]]:
    """`git diff HEAD --numstat` over the whole tree, staged and unstaged alike."""
    out = subprocess.run(["git", "diff", "HEAD", "--numstat"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    added: dict[str, int] = {}
    deleted: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        plus, minus, name = parts
        if plus == "-" or minus == "-":          # a binary file; git reports no line counts
            continue
        added[name] = int(plus)
        deleted[name] = int(minus)
    return added, deleted


@contextlib.contextmanager
def bounded_batch(max_deleted_lines: int, *, note: str = ""):
    """Run a batch of edits and raise if it deleted more lines than the caller expected.

    THE BOUND IS THE CALLER'S ESTIMATE AND THAT IS THE WHOLE MECHANISM. Nobody can compute how many
    lines an edit *should* delete, but everybody knows the order of magnitude before they start —
    "this rewrites one section, so tens" — and the incident this module exists for was three orders
    out. A stated bound turns that from something a reader might notice into something that stops.

    Measured against `HEAD`, not against the state at entry, so the number the caller reasons about
    is the number `git diff --stat` will show them — which is the number that actually caught the
    incident.

    **It raises AFTER the writes, deliberately.** Rolling back would need this module to own file
    restoration, and `git checkout -- <paths>` already does that correctly for tracked files. The
    job here is to stop a bad edit reaching a commit, and it does that by refusing to return.
    """
    before_added, before_deleted = _numstat()
    report = BatchReport()
    try:
        yield report
    finally:
        after_added, after_deleted = _numstat()
        report.added = {f: after_added[f] - before_added.get(f, 0)
                        for f in after_added if after_added[f] != before_added.get(f, 0)}
        report.deleted = {f: after_deleted[f] - before_deleted.get(f, 0)
                          for f in after_deleted if after_deleted[f] != before_deleted.get(f, 0)}
    if report.total_deleted > max_deleted_lines:
        raise BatchTooDestructive(
            f"this batch deleted {report.total_deleted} line(s) and stated a bound of "
            f"{max_deleted_lines}"
            + (f" ({note})" if note else "") + ".\n" + str(report) + "\n"
            "  The tree is LEFT AS IT IS so it can be inspected; `git checkout -- <path>` restores "
            "a tracked file.\n"
            "  On 2026-08-26 an edit of this shape deleted ~5 000 lines from FORMAT_COVERAGE.md "
            "because its anchor matched two sections; the diff stat was the only thing that "
            "noticed. If the bound is simply too low, raise it deliberately — the number is a "
            "claim about what the edit does."
        )
