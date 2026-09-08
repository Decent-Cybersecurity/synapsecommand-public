"""`docs/soif-part1-release-readiness.md` — SOIF spec §57's report, against the tree it describes.

REPOSITORY-BOUND. The file is at `docs/`, outside the distribution, and the two facts it is
checked against — `PACKAGE_VERSION` and `MIGRATIONS.md`'s pending section — are read from the
package but judged as repository state. An installed wheel has no readiness report to be right
about.

WHAT THIS MODULE ASSERTS, AND WHY EACH DIRECTION
------------------------------------------------
§57 fixes twenty sections and a final machine-readable statement. Three of those are checkable
without reading a word of the prose — the sections exist, they are in the spec's order, and the
last `blocked:` line parses — and the fourth is the one the round exists to prevent going wrong:

    a report that says `blocked: []` while the tree still says the release did not happen.

So the version and the pending section are tied to the `blocked:` list IN BOTH DIRECTIONS. An
empty list obliges `PACKAGE_VERSION` to be the release number and obliges `### Unreleased` to be
gone; a non-empty list obliges section 19 to say NO RELEASE and obliges the version NOT to have
moved. The second direction is the one that is load-bearing today, and it is the one a
presence-only check would have missed: round P8 found two blockers, and a report that had listed
them while quietly typing 2.1.0 into `version.py` would have been a release-readiness report
asserting readiness it had itself refuted.

WHAT IT REFUSES TO CHECK
------------------------
Whether a blocker is real. That is a reading of the tree and of two CI runs, and a test that
re-took it would be a second opinion on a judgement rather than a gate on a record. The names in
the `blocked:` list are slugs, not claims this module can verify; what it does check is that a
list which is non-empty is accompanied everywhere by the consequences §57 attaches to one.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORT = REPO / "docs" / "soif-part1-release-readiness.md"
MIGRATIONS = REPO / "packages" / "cdm" / "synapse_cdm" / "MIGRATIONS.md"

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

#: The version this campaign's milestone release would carry (spec §55). Read as a literal
#: because the point of the check is to catch the version NOT having moved when the report says
#: it should have; deriving it from `version.py` would make the assertion vacuous.
RELEASE_VERSION = "2.1.0"

UNRELEASED = "### Unreleased"

BLOCKED_LINE = re.compile(r"^blocked:\s*\[(?P<items>.*)\]\s*$", re.M)


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


def test_an_empty_blocked_list_means_the_version_moved_and_the_pending_section_went_with_it():
    """`blocked: []` is a claim about the tree, so the tree is what answers it."""
    from synapse_cdm.version import PACKAGE_VERSION

    if _blocked():
        pytest.skip(f"blocked is {_blocked()}, so this report does not claim readiness; the "
                    "converse direction is the test below")
    assert PACKAGE_VERSION == RELEASE_VERSION, (
        f"the readiness report says `blocked: []` and PACKAGE_VERSION is {PACKAGE_VERSION}. A "
        f"report with no blockers is a report that the release number is typed: §55 fixes it at "
        f"{RELEASE_VERSION}"
    )
    assert UNRELEASED not in MIGRATIONS.read_text(encoding="utf-8"), (
        f"the readiness report says `blocked: []` and MIGRATIONS.md still carries an "
        f"`{UNRELEASED}` section. Either the arc was absorbed into a release entry and the "
        f"section should have gone with it, or the report is claiming a readiness the migration "
        f"record does not"
    )


def test_a_non_empty_blocked_list_means_no_release_and_a_version_that_did_not_move():
    """The direction that is load-bearing today, and the one a presence check cannot see."""
    from synapse_cdm.version import PACKAGE_VERSION

    blocked = _blocked()
    if not blocked:
        pytest.skip("blocked is empty; the obligations of a clean report are the test above")
    text = _text()
    status = text[text.index("## 19. Release status"):text.index("## 20. Blockers")]
    assert "NO RELEASE" in status, (
        f"{len(blocked)} blocker(s) are listed and section 19 does not say NO RELEASE. §57: "
        '"If blockers are non-empty: NO RELEASE"'
    )
    assert PACKAGE_VERSION != RELEASE_VERSION, (
        f"the readiness report lists {len(blocked)} blocker(s) and PACKAGE_VERSION is already "
        f"{RELEASE_VERSION}. The release number is typed by the round that can say ready; a "
        f"blocked report with the number already in version.py is the disagreement this file "
        f"exists to make impossible"
    )


def test_every_blocker_named_in_the_list_is_argued_in_section_20():
    """A slug with no argument behind it is a placeholder, and §57's section 20 is the argument."""
    blocked = _blocked()
    if not blocked:
        pytest.skip("no blockers to argue")
    text = _text()
    section = text[text.index("## 20. Blockers"):]
    for name in blocked:
        assert section.count(name) >= 1, (
            f"{name!r} is in the machine-readable list and section 20 never mentions it"
        )
        # The slug alone is not an argument: each blocker gets a heading of its own.
        assert re.search(r"^### Blocker \d+", section, re.M), (
            "section 20 lists blockers and carries no `### Blocker N` heading: the list is the "
            "index and the headings are the reasons"
        )


def test_the_report_names_the_commit_it_describes():
    """§57 item 18. Either a hash or the self-referential form; both are readable, silence is not."""
    text = _text()
    section = text[text.index("## 18. Commit"):text.index("## 19. Release status")]
    assert re.search(r"\b[0-9a-f]{40}\b", section) or "carries **this file**" in section, (
        "section 18 names neither a 40-character commit hash nor the commit that carries the file"
    )
