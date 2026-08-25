"""Every release tag, against the tree it points at.

WHY THIS EXISTS BEFORE THE FIRST RELEASE AND NOT AFTER THE SECOND
------------------------------------------------------------------
A tag is the only durable claim a release makes. `pip install synapse-cdm==1.0.0` resolves an
artefact on an index; `v1.0.0` in this repository is what says which source produced it, and the
two are connected by nothing but a person having typed the same number twice. Nothing checked
that, and there was nothing to check until this round — which is exactly when the check is cheap,
because the set of tags is empty and every rule is satisfiable.

The failure it forecloses is small to make and impossible to repair: a `v1.0.1` tag on a tree
whose `PACKAGE_VERSION` still says `1.0.0` cannot be reproduced from the repository, and a tag
cannot be moved once anyone has fetched it. The repair is a second tag and a note explaining the
first, forever.

WHAT IT DERIVES RATHER THAN TRUSTS
-----------------------------------
Nothing here enumerates tags. The set comes from `git tag`, and for each one the version is read
out of the TAGGED tree — `git show <tag>:packages/cdm/synapse_cdm/version.py` — rather than out
of the working tree. That distinction is the whole assertion: reading the working tree would
compare today's number with every historical tag and pass only while no release had ever been
made.

It also refuses a LIGHTWEIGHT tag. A release is a statement by a person, and an annotated tag is
the only kind that records one: a tagger, a date and a message. A lightweight tag is a branch
name that does not move.

WHAT IT DOES NOT CHECK
----------------------
Whether an artefact was ever published for a tag, and whether that artefact came from that tree.
Both need an index this suite must not reach for — the same objection `tests/test_cdm_publication.py`
makes to a test that would need a GitHub token. `gates/wheel_install.py` builds the artefact and
checks it end to end; the connection between a built artefact and an uploaded one is a protocol
act, recorded in MIGRATIONS.md's release procedure.
"""
import ast
import pathlib
import re
import subprocess

import pytest

import synapse_cdm
from synapse_cdm.version import PACKAGE_VERSION

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
VERSION_PATH = "packages/cdm/synapse_cdm/version.py"
MIGRATIONS = PKG / "MIGRATIONS.md"

#: `v` then a semver core. Deliberately narrow: no pre-release suffixes, no `release-` prefix, no
#: bare `1.0.0`. One spelling, because a repository with two tag conventions has no convention and
#: `git describe` starts answering a different question depending on which was used last.
TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def _require_git() -> None:
    if not (REPO / ".git").exists():
        pytest.skip("no .git in this tree (an sdist or an unpacked wheel is the normal case), so "
                    "there are no tags to read and nothing here is asserted")


def tags() -> list[str]:
    out = _git("tag", "--list")
    assert out.returncode == 0, out.stderr
    return sorted(line.strip() for line in out.stdout.splitlines() if line.strip())


def package_version_at(tag: str) -> str:
    """`PACKAGE_VERSION` as the TAGGED tree declares it, parsed rather than imported.

    `ast` and not `exec`: reading a version out of history must not run code out of history.
    """
    out = _git("show", f"{tag}:{VERSION_PATH}")
    assert out.returncode == 0, (
        f"{tag} has no {VERSION_PATH}. Either the tag predates the package layout — in which case "
        f"it is not a release of this distribution and should not match {TAG.pattern} — or the "
        f"file moved and this constant is stale"
    )
    for node in ast.parse(out.stdout).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PACKAGE_VERSION":
                    return ast.literal_eval(node.value)
    raise AssertionError(
        f"{tag}:{VERSION_PATH} declares no PACKAGE_VERSION. Before this round the packaging "
        "version was read from SCHEMA_VERSION; a tag from that era names a number this rule "
        "cannot check, and saying so is better than checking the wrong constant"
    )


# ------------------------------------------------------------------------------- the rules


def test_every_tag_in_this_repository_is_a_release_tag_in_the_one_spelling():
    """One convention, checked in both directions: no stray tags, and none in another spelling."""
    _require_git()
    strays = [t for t in tags() if not TAG.match(t)]
    assert not strays, (
        f"tags that are not release tags: {strays}. This repository tags releases and nothing "
        f"else, in exactly one spelling ({TAG.pattern}). A second convention makes "
        "`git describe` answer a different question depending on which was used last"
    )


def test_every_release_tag_names_the_package_version_of_the_tree_it_points_at():
    """The assertion, re-derived per tag from the tagged tree rather than from this one."""
    _require_git()
    mismatched = []
    for tag in tags():
        match = TAG.match(tag)
        if not match:
            continue                                  # reported by the test above, not here
        declared = package_version_at(tag)
        if declared != match.group("version"):
            mismatched.append(f"{tag} points at a tree whose PACKAGE_VERSION is {declared}")
    assert not mismatched, (
        f"{mismatched}. A tag cannot be moved once anyone has fetched it, so the repair is a "
        "second tag and a permanent note about the first. Bump PACKAGE_VERSION in the commit you "
        "tag, not after it"
    )


def test_every_release_tag_is_annotated():
    """A release is a statement by a person; only an annotated tag records one."""
    _require_git()
    lightweight = []
    for tag in tags():
        kind = _git("cat-file", "-t", tag)
        if kind.stdout.strip() != "tag":
            lightweight.append(f"{tag} is {kind.stdout.strip() or 'unreadable'}, not an "
                               "annotated tag object")
    assert not lightweight, (
        f"{lightweight}. Use `git tag -a`: an annotated tag carries a tagger, a date and a "
        "message, and `git describe` prefers it. A lightweight tag is a branch name that does "
        "not move and it records nobody"
    )


def test_the_newest_tag_is_not_ahead_of_the_working_trees_package_version():
    """A tag from the future means the version was bumped in the tag and not in the branch.

    Behind is legal and normal — that is an unreleased commit. AHEAD is not: it means `main` is
    describing itself as older than something already released from it, and the next release
    would reuse a number the index has already seen.
    """
    _require_git()
    versions = [tuple(int(p) for p in TAG.match(t).group("version").split("."))
                for t in tags() if TAG.match(t)]
    if not versions:
        pytest.skip("no release tags yet; there is no ordering to assert. This is the state "
                    "before the first release and it is legal")
    here = tuple(int(p) for p in PACKAGE_VERSION.split("."))
    newest = max(versions)
    assert newest <= here, (
        f"the newest tag is v{'.'.join(str(p) for p in newest)} and the working tree says "
        f"PACKAGE_VERSION is {PACKAGE_VERSION}. `main` is describing itself as older than a "
        "release already made from it"
    )


# ----------------------------------------------------------------------- the written procedure


def test_the_release_procedure_is_written_down_and_states_its_four_conditions():
    """Recorded so the SECOND release follows a procedure rather than the first one's memory.

    Anchored on the four conditions rather than on the heading alone, because a section that
    survives as a heading with its requirements edited out is the failure this is written against.
    """
    text = MIGRATIONS.read_text()
    assert "## Releasing the package — the procedure" in text, (
        "MIGRATIONS.md has no release procedure section. The package version is governed by "
        "ordinary semver rather than by this document's table, but WHAT A RELEASE REQUIRES has "
        "to be written somewhere, and beside the other versioning document is where a person "
        "making one will look"
    )
    section = text[text.index("## Releasing the package"):text.index("\n## History")]
    for fragment, why in (
            ("The suite is green", "condition 1: the suite"),
            ("harnesses are green", "condition 2: the harnesses, including against the wheel"),
            ("gates/wheel_install.py", "the gate that makes condition 2 checkable"),
            ("names the package version of the tree it points at", "condition 3: the tag"),
            ("derived, not remembered", "condition 4: the notes"),
            ("annotated", "the tag is annotated and not lightweight")):
        assert fragment in section, (
            f"the release procedure no longer states {why} (looked for {fragment!r}). A procedure "
            "that loses a condition is how the next release skips it"
        )


def test_the_procedure_does_not_promise_a_publishing_mechanism_that_does_not_exist():
    """No CI here, so no step may read as though something runs by itself.

    The same failure `tests/test_cdm_deploy_workflow.py` was written for: a claim that a push
    deploys, made in the one window where nothing could falsify it. A release procedure that says
    "the tag triggers the upload" would be that claim again, one artefact along.
    """
    text = MIGRATIONS.read_text()
    section = text[text.index("## Releasing the package"):text.index("\n## History")]
    assert not (REPO / ".github" / "workflows").exists(), (
        "a workflows directory now exists, so this test is asserting the absence of something "
        "that is present. Re-decide the procedure's 'What is deliberately not automated' section "
        "rather than deleting this check"
    )
    for forbidden in ("triggers the upload", "on push", "automatically publishes"):
        assert forbidden not in section.lower(), (
            f"the release procedure says {forbidden!r}. There is no CI in this repository — no "
            ".github/workflows — so a push runs nothing at all, and a procedure claiming "
            "otherwise repeats the mistake tests/test_cdm_deploy_workflow.py was written for, "
            "one artefact along"
        )
    assert "no CI in this repository" in section, (
        "the procedure has to SAY that nothing is automated. Silence on the point is what let "
        "the deploy mechanism be wrong for a whole round"
    )
