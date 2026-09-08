"""`docs/soif-part1-release-readiness.md` — SOIF spec §57's report, against the tree it describes.

REPOSITORY-BOUND. The file is at `docs/`, outside the distribution, and the facts it is checked
against — the bump gate's own derivation, `PACKAGE_VERSION`, the newest release tag,
`MIGRATIONS.md`'s pending section and `RELEASE_NOTES.md`'s heading — are read from the package and
from git but judged as repository state. An installed wheel has no readiness report to be right
about.

WHAT `blocked: []` MEANS, AND WHY IT IS NOT "THE RELEASE HAS ALREADY HAPPENED"
-----------------------------------------------------------------------------
M's ruling of 2026-09-08, on round P8 attempt 3's HOLD, carried by round PT's brief
(`rounds/briefs/PT-soif-readiness-rule.md`) and quoted here because this module is the rule:

    "amend `tests/test_cdm_readiness.py` so `blocked: []` means the tree is release-ready, not
    that PACKAGE_VERSION and release headings have already been moved to the final tagged state;
    preserve the requirements that bump derivation is MINOR, floor is 2.1.0, unruled is empty, all
    substantive blockers are empty, and the required suite is green; make no release-state edits."

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
asserts, in five parts: the derivation allows the release (MINOR, a floor one MINOR above the
newest tag, nothing unruled); `PACKAGE_VERSION` has not moved ahead of the newest tag; the arc is
still under `### Unreleased` with its round records; `RELEASE_NOTES.md` still opens at the released
version; and the report says so itself, in §57's sections 19 and 20. None of the five is a claim
that the release happened, and all five together are what "ready" means.

The converse direction is unchanged and is still the one a presence-only check would have missed:
a non-empty list obliges section 19 to say NO RELEASE, and obliges the version not to have moved
either — round P8 found two blockers, and a report that had listed them while quietly typing the
next number into `version.py` would have been a release-readiness report asserting readiness it
had itself refuted.

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


def _minor_above(version: str) -> str:
    """The MINOR successor of a release number. The floor a MINOR arc derives, spelled by no test.

    §55 fixes the milestone at 2.1.0 and this returns it from `2.0.0` — but as a derivation, so
    that the day the newest tag moves the floor moves with it and nobody edits a literal here.
    """
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


def _measured() -> dict:
    """`gates/bump_derivation.py --json`, the derivation the report quotes, re-taken."""
    out = subprocess.run([sys.executable, str(GATE), "--json"],
                         cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, (
        f"the bump gate exited {out.returncode} on a tree whose readiness report claims no "
        f"blockers:\n{out.stdout}\n{out.stderr}"
    )
    return json.loads(out.stdout)


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
    """
    from synapse_cdm.version import PACKAGE_VERSION

    if _blocked():
        pytest.skip(f"blocked is {_blocked()}, so this report does not claim readiness; the "
                    "converse direction is the test below")

    previous = _previous_release()
    floor = _minor_above(previous)

    # (a) the derivation allows the release. Quoted by section 19 of every report; re-taken here.
    measured = _measured()
    assert measured["derived_kind"] == "MINOR", (
        f"the readiness report says `blocked: []` and the bump gate derives "
        f"{measured['derived_kind']} over {measured['arc']} — §55's milestone is a MINOR"
    )
    pending = measured["pending"]
    assert pending is not None and pending["kind"] == "MINOR", (
        f"the readiness report says `blocked: []` and the gate reports no pending MINOR arc: "
        f"{pending!r}. A ready tree has work that is not in a release yet"
    )
    assert pending["number"] == floor, (
        f"the gate's floor for the pending arc is {pending['number']} and one MINOR above the "
        f"newest tag ({previous}) is {floor}. A report claiming readiness is claiming readiness "
        f"for the number the derivation names"
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

    # (e) the report's own verdict, in §57's two places.
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
