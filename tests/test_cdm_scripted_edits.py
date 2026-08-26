"""`gates/scripted_edit.py` held to its contract, in both directions, on the incident itself.

WHAT HAPPENED, BECAUSE THE TEST IS ONLY WORTH ITS LINES IF THE INCIDENT IS ON THE RECORD
----------------------------------------------------------------------------------------
On 2026-08-26 the witnessed-set round rewrote a section of `FORMAT_COVERAGE.md` with

    start = s.index("### The fixtures — planned here, before they exist")
    end   = s.index("## STANAG 5527 — NATO Friendly Force Tracking Systems", start)
    s = s[:start] + new + s[end:]

and that heading occurred **twice** — the NITS row set had one and the KLV row set had one.
`str.index` took the first, so the slice ran from the NITS fixture plan to the end of the KLV
section and **~5 000 lines were deleted in a single write**. Nothing raised: the result was valid
Markdown, the script reported success, and the only thing that noticed was a `git diff --stat`
reading `-5087` where a section rewrite should read tens.

**The historical fact is checked here rather than described**, out of git, so this module cannot
drift into folklore: `test_the_incident_is_reproducible_from_git` reads the blob at `c5cf212` and
asserts the anchor occurred twice there and occurs once now.

WHAT IS ASSERTED, AND WHY EACH DIRECTION IS HERE
------------------------------------------------
A guard that only checked the refusal would pass on a module that refused everything. So both
directions, for both mechanisms:

* `replace_unique` writes on exactly one match, and refuses on zero and on two — **and leaves the
  file untouched when it refuses**, which is the property that makes a failure recoverable;
* `bounded_batch` returns quietly under its bound and raises over it, **and reports what it
  actually did** either way.

AND ONE THING THIS MODULE DOES NOT CLAIM
----------------------------------------
Nothing here can force an editing script to use either helper — they are tools, not a sandbox. The
claim is narrower and is the one worth making: the two checks exist, they are correct, and reaching
for them is cheaper than re-typing `str.replace`. The first live use of `replace_unique` in this
repository proved the limit in the same minute: the anchor was unique, the call went through, and it
wrote a replacement the author had not meant — caught by `git diff --numstat` reading `1 1`. A
unique anchor is a necessary condition and not a sufficient one, which is exactly why the diff-stat
bound is the second half and not an optional extra.
"""
import pathlib
import subprocess

import pytest

from gates.scripted_edit import (
    AnchorNotUnique,
    BatchTooDestructive,
    bounded_batch,
    occurrences,
    replace_unique,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
DOC = REPO / "packages/cdm/synapse_cdm/FORMAT_COVERAGE.md"

#: The anchor that matched twice. Kept verbatim, because a paraphrase would not reproduce it.
INCIDENT_ANCHOR = "### The fixtures — planned here, before they exist"
#: The commit whose blob still carries the two-occurrence state.
INCIDENT_BEFORE = "c5cf212"


def test_the_incident_is_reproducible_from_git():
    """The two-occurrence state is a fact in the repository's own history, not a story about one.

    Read out of the blob rather than asserted, so that this module's motivation cannot decay into
    something nobody can check. The heading was renamed by the round that hit it — the KLV section's
    copy is now "The fixtures — ten payloads, and the plan they replaced" — so the anchor is unique
    today and the danger it represents is not.
    """
    blob = subprocess.run(
        ["git", "show", f"{INCIDENT_BEFORE}:packages/cdm/synapse_cdm/FORMAT_COVERAGE.md"],
        cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert blob.count(INCIDENT_ANCHOR) == 2, (
        f"the blob at {INCIDENT_BEFORE} no longer carries the anchor twice, so the incident this "
        "module exists for is no longer reproducible from history. Do not delete this test — "
        "re-anchor it on whatever commit does, or record that the evidence is gone"
    )
    assert DOC.read_text().count(INCIDENT_ANCHOR) == 1, (
        "the anchor is ambiguous in FORMAT_COVERAGE.md again. That is not itself a defect — two "
        "sections may legitimately share a heading — but it is the state the incident happened in, "
        "and any scripted edit touching it must go through replace_unique"
    )


def test_a_unique_anchor_is_replaced(tmp_path):
    target = tmp_path / "doc.md"
    target.write_text("alpha\nbeta\ngamma\n")
    replace_unique(target, "beta", "BETA")
    assert target.read_text() == "alpha\nBETA\ngamma\n"


def test_an_absent_anchor_refuses_and_writes_nothing(tmp_path):
    """Zero is a failure, not a no-op — and the no-op is the insidious half.

    `str.replace` on a drifted anchor writes the file back unchanged and reports success, which is
    how somebody comes to run a script twice and then edit by hand.
    """
    target = tmp_path / "doc.md"
    target.write_text("alpha\nbeta\n")
    before = target.read_text()
    with pytest.raises(AnchorNotUnique) as caught:
        replace_unique(target, "delta", "DELTA")
    assert "occurs 0 time(s)" in str(caught.value)
    assert "drifted" in str(caught.value)
    assert target.read_text() == before, "a refusal must leave the file untouched"


def test_a_repeated_anchor_refuses_and_names_every_line(tmp_path):
    """The incident's own shape, and the message has to be actionable.

    "Your anchor is ambiguous" is not actionable; "it appears at lines 2 and 4" is.
    """
    target = tmp_path / "doc.md"
    target.write_text("head\n### Section\nbody\n### Section\ntail\n")
    before = target.read_text()
    with pytest.raises(AnchorNotUnique) as caught:
        replace_unique(target, "### Section", "### Renamed")
    message = str(caught.value)
    assert "occurs 2 time(s)" in message
    assert "[2, 4]" in message, f"the message does not name the matching lines: {message}"
    assert "5 000 lines" in message, "the message no longer names the incident it comes from"
    assert target.read_text() == before, "a refusal must leave the file untouched"


def test_the_incidents_own_edit_would_now_refuse(tmp_path):
    """End to end, on the real bytes: the 2026-08-26 edit, replayed against the 2026-08-26 tree.

    THE POINT OF USING THE REAL BLOB. A synthetic two-heading file proves the mechanism; this proves
    the mechanism would have stopped THE edit, on the document it damaged, at the commit it ran
    against. Without it this module asserts a property and not a repair.
    """
    blob = subprocess.run(
        ["git", "show", f"{INCIDENT_BEFORE}:packages/cdm/synapse_cdm/FORMAT_COVERAGE.md"],
        cwd=REPO, capture_output=True, text=True, check=True).stdout
    target = tmp_path / "FORMAT_COVERAGE.md"
    target.write_text(blob)

    # What the round actually did: index(), which silently takes the first of two.
    naive_start = blob.index(INCIDENT_ANCHOR)
    naive_end = blob.index("## STANAG 5527 — NATO Friendly Force Tracking Systems", naive_start)
    damaged = blob[:naive_start] + "REPLACEMENT\n" + blob[naive_end:]
    lost = len(blob.splitlines()) - len(damaged.splitlines())
    assert lost > 4000, (
        f"the naive slice loses {lost} lines; the incident lost about 5 000. If this number has "
        "moved a lot, the blob or the section boundaries are not what this test thinks"
    )

    # What the tool does with the same anchor.
    with pytest.raises(AnchorNotUnique):
        replace_unique(target, INCIDENT_ANCHOR, "REPLACEMENT")
    assert target.read_text() == blob, "the refusal must have left the document whole"


def test_occurrences_counts_without_writing(tmp_path):
    target = tmp_path / "doc.md"
    target.write_text("a\na\nb\n")
    assert occurrences(target, "a") == 2
    assert occurrences(target, "z") == 0
    assert target.read_text() == "a\na\nb\n"


def test_a_batch_under_its_bound_returns_quietly_and_reports_what_it_did():
    """The passing direction, on the real tree, and it must leave the tree as it found it.

    Deliberately a NO-OP batch. A test that edited a tracked file to prove the bound works would
    leave the working tree dirty for whatever ran next, and this suite has to be runnable in any
    order.
    """
    with bounded_batch(max_deleted_lines=0, note="a batch that changes nothing") as report:
        pass
    assert report.total_deleted == 0
    assert report.total_added == 0
    assert str(report) == "no tracked file changed"


def test_a_batch_over_its_bound_raises_and_leaves_the_tree_for_inspection(tmp_path):
    """The failing direction, on a real tracked file, restored by this test rather than by git.

    `RELEASE_NOTES.md` is chosen because it is tracked, is text, and is not read by any other test
    in this module — and the original bytes are put back in a `finally`, so a failure here does not
    poison the rest of the run.
    """
    victim = REPO / "RELEASE_NOTES.md"
    original = victim.read_text()
    try:
        with pytest.raises(BatchTooDestructive) as caught:
            with bounded_batch(max_deleted_lines=3, note="a deliberately over-large edit"):
                victim.write_text("\n".join(original.splitlines()[:5]) + "\n")
        message = str(caught.value)
        assert "stated a bound of 3" in message
        assert "RELEASE_NOTES.md" in message
        assert "git checkout" in message, "the message has to say how to recover"
        assert "2026-08-26" in message, "the message no longer names the incident"
        assert victim.read_text() != original, (
            "the batch is documented as raising AFTER the writes, so the damaged file is there to "
            "be inspected. If that changed, this assertion is the record of the old contract"
        )
    finally:
        victim.write_text(original)
    assert victim.read_text() == original


def test_the_helpers_are_reachable_from_the_repository_root():
    """`gates/` is repo tooling and ships in no wheel — asserted, because it names the boundary.

    `gates/wheel_install.py` is the sibling and the same rule applies: these judge the repository
    from outside the package, so shipping them inside the distribution would put a git-dependent
    module in a consumer's site-packages.
    """
    assert (REPO / "gates" / "scripted_edit.py").is_file()
    tracked = subprocess.run(["git", "ls-files", "gates"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.split()
    assert "gates/scripted_edit.py" in tracked
    # `gates` DOES appear in packages/cdm/pyproject.toml — inside the comment block that lists
    # what the distribution deliberately excludes, which is the opposite of a defect. So the
    # assertion is on the packaging DIRECTIVES rather than on the file's prose: the first draft of
    # this test asserted the string was absent and failed on the sentence explaining its absence.
    manifest = (REPO / "packages/cdm/pyproject.toml").read_text()
    directives = [line for line in manifest.splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
    assert not any("gates" in line for line in directives), (
        "a packaging directive in packages/cdm/pyproject.toml now names `gates`. These modules run "
        "`git` and judge the repository from outside the package; a consumer's site-packages is "
        "the wrong place for either.\nDirectives naming it: "
        + str([line for line in directives if "gates" in line])
    )
    assert "gates/" in manifest, (
        "pyproject.toml no longer records `gates/` among what the distribution excludes. The "
        "exclusion is deliberate and the comment is where it is stated"
    )
