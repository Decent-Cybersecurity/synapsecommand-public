"""`docs/soif-part1-release-readiness.md` — SOIF spec §57's report, against the tree it describes.

REPOSITORY-BOUND. The file is at `docs/`, outside the distribution, and the facts it is checked
against — the bump gate's own derivation, `PACKAGE_VERSION`, the newest release tag,
`MIGRATIONS.md`'s pending section and `RELEASE_NOTES.md`'s heading — are read from the package and
from git but judged as repository state. An installed wheel has no readiness report to be right
about.

WHAT `blocked: []` MEANS, AND WHY IT IS NOT "THE RELEASE HAS ALREADY HAPPENED"
-----------------------------------------------------------------------------
M's ruling of 2026-09-08, on round P8 attempt 3's HOLD, carried by round PT's brief
(`rounds/briefs/PT-soif-readiness-rule.md`): `blocked: []` means the tree is release-READY, not
that `PACKAGE_VERSION` and the release headings have already been moved to the final tagged state.
What it told this module to preserve was the derivation's verdict — that the gate derives a bump,
that the pending number is the one the gate's own floor names, that nothing is unruled — together
with an empty substantive blocker set and a green suite; and to make no release-state edits. The
ruling named that campaign's kind and number as literals and this file no longer does, for the
reason the corrective section at the end of this docstring gives.

The rule this module encoded before that ruling was the opposite one: an empty list obliged
`PACKAGE_VERSION` to carry the release number and obliged `### Unreleased` to be gone. That rule
is unsatisfiable outside a release round, and the reason is in the bump gate.
`gates/bump_derivation.py:1256` chooses the section it reads its rulings from as
`declared if released else "Unreleased"`, and `released` at `:1253` is `tags.get(version)` — the
tag that NAMES the declared version. So moving the version while no such tag exists leaves the
gate reading `### Unreleased`; renaming that section while no such tag exists makes `rulings()`
return `{}`, every unit of the arc unruled, and the gate refuse. The version and the heading can
only move WITH the tag, and the tag is the release round's (`rounds/templates/release-round.md`
lists both of them among the sites that round moves).

So readiness is a property of a tree BETWEEN releases, and that is what the empty-list branch
asserts, in five parts: the derivation allows the release (the gate derives a bump over the pending
arc, the pending number is that bump applied to the released version by the gate's own successor
function, nothing is unruled); `PACKAGE_VERSION` has not moved ahead of the newest tag; the arc is
still under `### Unreleased` with its round records; `RELEASE_NOTES.md` still opens at the released
version; and the report says so itself, in §57's sections 19 and 20. None of the five is a claim
that the release happened, and all five together are what "ready" means.

The converse direction is unchanged and is still the one a presence-only check would have missed:
a non-empty list obliges section 19 to say NO RELEASE, and obliges the version not to have moved
either — round P8 found two blockers, and a report that had listed them while quietly typing the
next number into `version.py` would have been a release-readiness report asserting readiness it
had itself refuted.

AND WHAT IT MEANS AFTER THE RELEASE IT CERTIFIED, WHICH IS A DIFFERENT QUESTION
------------------------------------------------------------------------------
The five parts above are all pre-release conditions, and the release round ends every one of them
in a single commit: the version moves, the pending section is rolled into a release section, the
notes are rewritten. Round PT ruled the pre-release side and nothing ruled the other, so on the
tagged tree this module refused the release it had just certified — assertion (a) first, because
the bump gate reads its rulings from the pending section until a tag names the declared version
and reports no pending arc once one does. Round PR found it and could not close it: no P round may
tag, so nothing before PR could reach the state.

M's ruling of 2026-09-09, fork FR.5 of round PR's brief under `rounds/briefs/`: before
`PACKAGE_VERSION` is tagged the readiness report is a live pre-release gate, it must end with
`blocked: []`, and the version and release-note invariants of a package between releases stay
enforced. Once a tag exists that exactly names `PACKAGE_VERSION`, the same report becomes the
historical certification of that release: the pre-release conditions are dropped — the version
having not moved, the notes still standing at the previous heading — and what stays required is
that the report exists, that it corresponds to the released version and commit, and that it ends
with the empty list. The transition is decided by the tag and never by a branch name or a date.

So there are two modes and ONE fact decides which: does a tag exist that exactly names this tree's
`PACKAGE_VERSION`. Not the branch — a release commit sits on `main` and a campaign branch is
fast-forwarded to it, so both names see the same tree. Not the date — a report is not a different
document tomorrow. The tag, and `_released_tag()` below is the whole of the decision.

What survives into the released mode is what a certification can be held to: the report exists, it
ends with an empty blocker list, it names the version that was released, and every commit it names
is one the release tag contains. What is dropped is dropped because it is a statement about a tree
BETWEEN releases and this tree is no longer one. What is NOT dropped is the report's own verdict —
section 19 saying `ready for PR` and section 20 arguing no blocker — because that is a property of
the document rather than of the tree, and a certification whose own verdict had been edited away
would be a certification of nothing.

WHAT IT REFUSES TO CHECK
------------------------
Whether a blocker is real. That is a reading of the tree and of two CI runs, and a test that
re-took it would be a second opinion on a judgement rather than a gate on a record. The names in
the `blocked:` list are slugs, not claims this module can verify; what it does check is that a
list which is non-empty is accompanied everywhere by the consequences §57 attaches to one.
"""
import json
import pathlib
import re
import subprocess
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORT = REPO / "docs" / "soif-part1-release-readiness.md"
MIGRATIONS = REPO / "packages" / "cdm" / "synapse_cdm" / "MIGRATIONS.md"
NOTES = REPO / "RELEASE_NOTES.md"
GATE = REPO / "gates" / "bump_derivation.py"

#: §57's twenty sections, in §57's order and numbering. The words are the spec's own.
SECTIONS = (
    "1. Baseline",
    "2. Resulting architecture",
    "3. Adapter API",
    "4. CDM changes",
    "5. Manifests",
    "6. Maturity model",
    "7. Conformance",
    "8. Evidence",
    "9. Security",
    "10. Dependencies",
    "11. SBOM",
    "12. Build provenance",
    "13. Release procedure",
    "14. Existing-adapter regressions",
    "15. Known limitations",
    "16. Intentionally deferred work",
    "17. Test commands",
    "18. Commit",
    "19. Release status",
    "20. Blockers",
)

#: §57's own words for the clean verdict, and the phrase the report must carry instead of the
#: blocked one. The release round is what acts on it, so the report names it.
READY = "ready for PR"

UNRELEASED = "### Unreleased"

#: The same heading with its `### ` stripped: what `gates/bump_derivation.py` calls a section when
#: it looks up rulings. Derived from `UNRELEASED` so the two can never be edited apart.
UNRELEASED_HEADING = UNRELEASED.removeprefix("### ")

BLOCKED_LINE = re.compile(r"^blocked:\s*\[(?P<items>.*)\]\s*$", re.M)

#: A round's record inside the pending section. Both spellings the arc actually uses, because the
#: sweep is for "the section is not empty prose" and a case rule would be a rule about typography.
ROUND_RECORD = re.compile(r"^\*\*(?:ROUND|Round)\s+\w+", re.M)

BLOCKER_HEADING = re.compile(r"^### Blocker \d+", re.M)


def _text() -> str:
    return REPORT.read_text(encoding="utf-8")


def _blocked() -> list[str]:
    """§57's final machine-readable statement, parsed.

    The LAST match in the file, deliberately: section 20 explains the list in prose above it and
    a future round may quote a previous round's list there. The statement is the final one.
    """
    matches = list(BLOCKED_LINE.finditer(_text()))
    assert matches, (
        "§57 requires a final machine-readable statement `blocked: [...]` and no line in "
        f"{REPORT.name} parses as one"
    )
    items = matches[-1].group("items").strip()
    return [part.strip() for part in items.split(",") if part.strip()]


def _report_section(heading: str, until: str | None) -> str:
    text = _text()
    start = text.index(f"## {heading}")
    return text[start:text.index(f"## {until}")] if until else text[start:]


def _previous_release() -> str:
    """The number of the newest release tag — the version the tree is still ON.

    Read from git rather than from `version.py`, because the assertion it serves is that the two
    AGREE. Deriving the comparand from the constant under test is how that check goes vacuous.
    """
    tags = subprocess.run(["git", "tag", "--sort=-v:refname"],
                          cwd=REPO, capture_output=True, text=True)
    assert tags.returncode == 0, tags.stderr
    newest = tags.stdout.splitlines()
    assert newest, "no release tag in this repository, so there is no released version to be on"
    return newest[0].lstrip("v")


def _gate_module():
    """`gates/bump_derivation.py` as an importable module, loaded from SOURCE.

    `exec(compile(...))` rather than the ordinary loader, and registered in `sys.modules` while it
    runs: `tests/test_cdm_bump_derivation.py`'s fixture gives both reasons — a `.pyc` is
    revalidated on mtime in whole seconds, and a `@dataclass` under `from __future__ import
    annotations` resolves its field annotations through `sys.modules[cls.__module__]`, which is
    `None` for a module exec'd into a bare namespace. This gate holds five dataclasses.

    WHY THE MODULE AND NOT MORE ARITHMETIC HERE. What this file used to carry was a
    `_minor_above()` that spelled one kind of bump and one way of stepping a version — a second
    implementation of `_successor()`, correct only for the campaign it was written in. M's ruling
    of 2026-09-09 removed the assumption behind it (that §55's milestone is always the next
    release, and always exactly one minor step above the newest tag), and the honest replacement
    is not a more general arithmetic of our own but the gate's own function: the floor a release
    must carry is whatever `gates/bump_derivation.py` says it is, computed by the code that says
    it.
    """
    module = types.ModuleType("_bump_derivation_for_readiness")
    module.__file__ = str(GATE)
    sys.modules[module.__name__] = module
    try:
        exec(compile(GATE.read_text(encoding="utf-8"), str(GATE), "exec"), module.__dict__)
    finally:
        sys.modules.pop(module.__name__, None)
    return module


def _derived_pending(gate) -> tuple[str, str] | None:
    """`(kind, number)` for the arc since the released tag, re-derived rather than read.

    The same three lines `measure()` runs for its `pending` block, executed here in this process
    so that the JSON the report is judged against has a second, independent derivation behind it.
    Read from the gate's own JSON alone, the assertions below would be the gate agreeing with
    itself; re-derived, they catch a reporting path that has drifted from the derivation it
    reports — which is a live class of defect in a gate whose JSON and human summary are separate
    code, and was one in this repository's history.

    `None` when no tag names `PACKAGE_VERSION`: there is no released end to measure from, and the
    caller is in a mode where that cannot happen.
    """
    tags = gate.release_tags()
    version = gate.parse_version(gate.declared_version())
    released = tags.get(version)
    if released is None:
        return None
    pending, _ = gate.apply_rulings(
        gate.derive(gate.snapshot_at(released), gate.snapshot_at(None)), UNRELEASED_HEADING)
    return pending.floor, gate._successor(version, pending.floor)


def _measured() -> dict:
    """`gates/bump_derivation.py --json`, the derivation the report quotes, re-taken."""
    out = subprocess.run([sys.executable, str(GATE), "--json"],
                         cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, (
        f"the bump gate exited {out.returncode} on a tree whose readiness report claims no "
        f"blockers:\n{out.stdout}\n{out.stderr}"
    )
    return json.loads(out.stdout)


def _certified_commits() -> list[str]:
    """Every 40-character hash §57's section 18 names. The report's own subject, as it writes it."""
    return re.findall(r"\b[0-9a-f]{40}\b", _report_section("18. Commit", "19. Release status"))


def _released_tag() -> str | None:
    """The tag that names this tree's `PACKAGE_VERSION` AND contains the commit this report
    certifies — or None, which is the pre-release mode.

    M's FR.5: the transition is read from the tag and from nothing else. `git tag -l <name>` is
    exact-match by name and prints nothing for a tag that does not exist, so the answer starts
    from that output being non-empty — no parsing of a tag list, no ordering, no `--sort`, and no
    chance of a prefix match putting a `v<version>-rc1` in the way.

    THE NAME IS NOT ENOUGH, AND A TAG THAT EXISTS TAUGHT US SO. M's corrective ruling of
    2026-09-09: "A tag such as [the one naming this version] that exists but does NOT contain the
    new report's commit is a tagged-but-unpublished historical tag and MUST NOT switch the new
    readiness report into released mode." That is a state this repository is actually in — a
    release tag was cut, its own pipeline refused it at a security gate, nothing reached the
    index, and the corrective release is a later number from a later commit. A name-only test
    would read the tag, call the corrective campaign's fresh readiness report a historical
    certification, and drop every pre-release condition the corrective release still has to meet.
    So the tag must CONTAIN what the report describes before it can decide what the report is.

    Note what this still deliberately does NOT ask: whether the tag points at HEAD. A release tag
    names a commit, `main` may move on afterwards, and the report stays the certification of that
    release either way. Containment is the relation; identity is not.

    A report that names no commit at all is pre-release by the same rule, and that is not a gap.
    §57 lets section 18 be self-referential — "the commit that carries this file" — which is the
    only honest form BEFORE the commit exists, and it is exactly the form a report written for a
    release that has not happened takes. Nothing can be shown to contain it, so nothing does.
    """
    from synapse_cdm.version import PACKAGE_VERSION

    out = subprocess.run(["git", "tag", "-l", f"v{PACKAGE_VERSION}"],
                         cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    tag = out.stdout.strip() or None
    if tag is None:
        return None
    commits = _certified_commits()
    if not commits:
        return None
    return tag if all(_tag_contains(tag, commit) for commit in commits) else None


def _tag_contains(tag: str, commit: str) -> bool:
    out = subprocess.run(["git", "merge-base", "--is-ancestor", commit, tag],
                         cwd=REPO, capture_output=True, text=True)
    assert out.returncode in (0, 1), out.stderr
    return out.returncode == 0


def _unreleased_section() -> str | None:
    """The pending section's body, by the rule `gates/bump_derivation.py:_section()` uses."""
    text = MIGRATIONS.read_text(encoding="utf-8")
    found = re.search(rf"^{re.escape(UNRELEASED)}.*$", text, re.M)
    if not found:
        return None
    rest = text[found.end():]
    nxt = re.search(r"\n#{2,3} ", rest)
    return rest[:nxt.start()] if nxt else rest


def test_the_readiness_report_exists_at_the_path_the_spec_fixes():
    assert REPORT.is_file(), (
        "SOIF §57 fixes the path: docs/soif-part1-release-readiness.md. A report at another path "
        "is a document the spec does not ask for"
    )


@pytest.mark.parametrize("heading", SECTIONS)
def test_every_section_the_spec_requires_is_present(heading):
    assert f"## {heading}" in _text(), f"§57 requires a section {heading!r}"


def test_the_sections_are_in_the_specs_own_order():
    """Present-and-in-order, because §57 numbers them and a renumbered report is a different one."""
    text = _text()
    positions = [text.index(f"## {heading}") for heading in SECTIONS]
    assert positions == sorted(positions), (
        "the sections appear out of §57's order: "
        f"{[SECTIONS[i] for i in range(len(SECTIONS)) if i and positions[i] < positions[i - 1]]}"
    )


def test_the_final_statement_is_the_last_thing_in_the_file():
    """`blocked:` is the report's conclusion, so nothing may follow it but the fence and a newline."""
    text = _text()
    tail = text[list(BLOCKED_LINE.finditer(text))[-1].end():]
    assert tail.strip() in ("", "```"), (
        f"{tail.strip()[:80]!r} follows §57's final machine-readable statement. The statement is "
        "final: a section after it is a section the machine-readable answer does not cover"
    )


def test_the_blocked_list_parses_and_its_entries_are_slugs():
    for name in _blocked():
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), (
            f"{name!r} is not a slug. The list is read by a machine; prose in it is a sentence "
            "that will be parsed as an identifier"
        )


# ------------------------------------------- the two facts the report and the tree must agree on


def test_an_empty_blocked_list_means_the_tree_is_release_ready_and_not_that_it_was_released():
    """`blocked: []` is a claim about the tree, so the tree is what answers it.

    M's rule of 2026-09-08, in the module docstring: what an empty list obliges is a tree the
    release round can run ON, not a tree the release round has already run on. So the version and
    the headings are asserted UNMOVED here, and the derivation is asserted to allow the move.

    AND, since M's FR.5 of 2026-09-09, only while that is still the tree in front of it. Once a
    tag exactly names `PACKAGE_VERSION` the release has happened and the same five assertions
    would refuse it; the released mode below is what the report is held to then. Both modes share
    the report's own verdict, which is the last block of this test.
    """
    from synapse_cdm.version import PACKAGE_VERSION

    if _blocked():
        pytest.skip(f"blocked is {_blocked()}, so this report does not claim readiness; the "
                    "converse direction is the test below")

    released = _released_tag()
    if released is not None:
        _certifies_the_release(released)
    else:
        _certifies_readiness()

    # (e) the report's own verdict, in §57's two places. BOTH modes: a released report is still a
    # report, and its verdict is what it certified rather than a reading of today's tree.
    status = _report_section("19. Release status", "20. Blockers")
    assert READY in status, (
        f"no blockers are listed and section 19 does not say {READY!r}. The empty list is a "
        f"verdict and section 19 is where §57 puts it"
    )
    assert "NO RELEASE" not in status, (
        "no blockers are listed and section 19 still says NO RELEASE. §57 attaches that phrase to "
        "a non-empty list"
    )
    blockers = _report_section("20. Blockers", None)
    assert not BLOCKER_HEADING.search(blockers), (
        "the machine-readable list is empty and section 20 still argues a `### Blocker N`. The "
        "list is the index and the headings are the reasons: an argued blocker that is not in the "
        "list is a blocker the machine-readable answer hides"
    )


def _certifies_the_release(tag: str) -> None:
    """THE RELEASED MODE, M's FR.5. Three obligations and not one of them about today's tree.

    Existence, correspondence, and the empty list. CORRESPONDENCE IS NOT ASSERTED HERE ANY MORE,
    and its absence is the point rather than an omission: since M's corrective ruling of
    2026-09-09 it is what SELECTS this mode. `_released_tag()` returns a tag only when the tag
    contains every commit section 18 names, so by the time this function runs the correspondence
    has already been established — asserting it again would be a branch that can never be taken,
    and a check nobody has ever seen fail is not a check. The failure it used to catch is caught
    strictly earlier and harder: a report describing a commit the tag does not reach no longer
    fails an assertion inside the released mode, it never enters the released mode at all, and is
    held to the pre-release conditions instead. Which is right — that report is a claim about a
    tree between releases, whatever tags happen to exist beside it.
    """
    from synapse_cdm.version import PACKAGE_VERSION

    assert REPORT.is_file(), (
        f"{tag} names this tree's PACKAGE_VERSION, so this report is the certification of a "
        f"release, and it is not there. §57's report is not consumed by the release it certifies"
    )
    assert _blocked() == [], (
        f"{tag} exists and the report's final statement is not the empty list. A release was cut "
        f"from a tree whose own readiness report lists blockers"
    )
    assert PACKAGE_VERSION in _text(), (
        f"the report never names {PACKAGE_VERSION}, which is the version {tag} released. A "
        f"certification that does not name what it certifies corresponds to nothing"
    )


def _certifies_readiness() -> None:
    """THE PRE-RELEASE MODE, round PT's rule, unchanged in substance by FR.5.

    Five parts, and all five are statements about a tree BETWEEN releases: the derivation allows
    the release, the version has not moved, the arc is still pending with its records, and the
    notes still open at the released version. The fifth — the report's own verdict — is shared
    with the released mode and asserted by the caller.
    """
    from synapse_cdm.version import PACKAGE_VERSION

    previous = _previous_release()

    # (a) the derivation allows the release, and BOTH of its numbers come from the derivation.
    # Section 19 of every report quotes them; they are re-taken here, twice and by two routes —
    # the gate's JSON, and the gate's own functions run in this process.
    measured = _measured()
    pending = measured["pending"]
    assert pending is not None and pending["kind"] is not None, (
        f"the readiness report says `blocked: []` and the gate reports no pending arc: {pending!r} "
        f"over {measured['arc']}. The gate measures the pending arc from the tag that NAMES the "
        f"declared version, so this is the shape of PACKAGE_VERSION ({PACKAGE_VERSION}) having "
        f"moved ahead of every tag: the number moves in the release round, with the tag, and a "
        f"readiness report is not the release"
    )
    derived = _derived_pending(_gate_module())
    assert derived is not None, (
        "the gate's JSON reports a pending arc and the same derivation re-run in this process "
        "finds no released tag to measure one from. The two disagree about the tree they are "
        "reading, which is a defect in the gate and not in the report"
    )
    kind, floor = derived
    assert kind != "NONE", (
        f"the readiness report says `blocked: []` and the arc since v{previous} derives {kind}: "
        f"nothing in the distribution has moved since the last release. A report claiming "
        f"readiness for a release with no content is claiming readiness for nothing"
    )
    assert pending["kind"] == kind, (
        f"the gate's JSON reports a pending {pending['kind']} arc and the same derivation re-run "
        f"in this process yields {kind}. The number a release carries is decided by the "
        f"derivation, so the two have to be one answer"
    )
    assert pending["number"] == floor, (
        f"the gate's floor for the pending arc is {pending['number']} and applying the derived "
        f"{kind} to the released version ({previous}) gives {floor}. A report claiming readiness "
        f"is claiming readiness for the number the derivation names — which is the derived kind "
        f"applied to the released version, and never a number a test spelled in advance"
    )
    assert pending["unruled"] == [], (
        f"the readiness report says `blocked: []` and the gate leaves "
        f"{len(pending['unruled'])} unit(s) unruled: {pending['unruled']}. Unruled units are a "
        f"rulings round, and the release procedure's own pre-check refuses them"
    )

    # (b) the version has NOT moved. It moves in the release round, with the tag, because the
    # gate above reads `### Unreleased` until the tag for the declared number exists.
    assert PACKAGE_VERSION == previous, (
        f"the readiness report says `blocked: []` and PACKAGE_VERSION is {PACKAGE_VERSION} while "
        f"the newest release tag is v{previous}. Readiness is not the release: the number moves in "
        f"the release round, atomically with the tag, and a number ahead of every tag makes the "
        f"bump gate read a section that is not there yet"
    )

    # (c) the arc is still pending, with its records under the heading the gate reads.
    section = _unreleased_section()
    assert section is not None, (
        f"the readiness report says `blocked: []` and MIGRATIONS.md carries no `{UNRELEASED}` "
        f"section. The arc being released is the one under that heading; the release round is "
        f"what renames it, and until then the bump gate reads its rulings from it"
    )
    records = ROUND_RECORD.findall(section)
    assert records, (
        f"`{UNRELEASED}` is present and carries no round record. A ready arc is an arc whose "
        f"rounds wrote themselves down: the section is what the gate reads its rulings from"
    )

    # (d) the notes still open at the released version. The release round rewrites them.
    first_line = NOTES.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == f"# synapse-cdm {previous}", (
        f"{NOTES.name} opens {first_line!r} and the newest release tag is v{previous}. The notes "
        f"are rewritten by the release round; a readiness report is not the release"
    )


def test_a_non_empty_blocked_list_means_no_release_and_a_version_that_did_not_move():
    """The direction that is load-bearing today, and the one a presence check cannot see."""
    from synapse_cdm.version import PACKAGE_VERSION

    blocked = _blocked()
    if not blocked:
        pytest.skip("blocked is empty; the obligations of a clean report are the test above")
    status = _report_section("19. Release status", "20. Blockers")
    assert "NO RELEASE" in status, (
        f"{len(blocked)} blocker(s) are listed and section 19 does not say NO RELEASE. §57: "
        '"If blockers are non-empty: NO RELEASE"'
    )
    previous = _previous_release()
    assert PACKAGE_VERSION == previous, (
        f"the readiness report lists {len(blocked)} blocker(s) and PACKAGE_VERSION is "
        f"{PACKAGE_VERSION} while the newest release tag is v{previous}. The release number is "
        f"typed by the round that tags it; a blocked report with a version ahead of every tag is "
        f"the disagreement this file exists to make impossible"
    )


def test_every_blocker_named_in_the_list_is_argued_in_section_20():
    """A slug with no argument behind it is a placeholder, and §57's section 20 is the argument."""
    blocked = _blocked()
    if not blocked:
        pytest.skip("no blockers to argue")
    section = _report_section("20. Blockers", None)
    for name in blocked:
        assert section.count(name) >= 1, (
            f"{name!r} is in the machine-readable list and section 20 never mentions it"
        )
        # The slug alone is not an argument: each blocker gets a heading of its own.
        assert BLOCKER_HEADING.search(section), (
            "section 20 lists blockers and carries no `### Blocker N` heading: the list is the "
            "index and the headings are the reasons"
        )


def test_the_report_names_the_commit_it_describes():
    """§57 item 18. Either a hash or the self-referential form; both are readable, silence is not."""
    section = _report_section("18. Commit", "19. Release status")
    assert re.search(r"\b[0-9a-f]{40}\b", section) or "carries **this file**" in section, (
        "section 18 names neither a 40-character commit hash nor the commit that carries the file"
    )
