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
from synapse_cdm.adapter import roster as adapter_roster
from synapse_cdm.version import PACKAGE_VERSION, SCHEMA_VERSION

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


def test_the_procedure_describes_the_publishing_mechanism_that_now_exists():
    """INVERTED. This test used to assert the ABSENCE of `.github/workflows`.

    Its earlier form required the procedure to say "there is no CI in this repository", and it
    carried its own instruction for the day that stopped being true: "a workflows directory now
    exists, so this test is asserting the absence of something that is present. Re-decide the
    procedure's 'What is deliberately not automated' section rather than deleting this check."
    `.github/workflows/publish.yml` landed, the check failed, and this is that re-decision.

    The reason it is inverted rather than removed is that the failure it guards is unchanged. It
    was written for the mistake `tests/test_cdm_deploy_workflow.py` found — a claim that a push
    deployed the documentation site, made in the one window where nothing could falsify it, left
    standing for a round. Deleting the check would restore exactly that window: prose describing an
    upload mechanism, with nothing comparing the prose to the mechanism. So the direction flips and
    the closure stays. Both halves are now required to hold:

    * the mechanism the procedure describes must EXIST — a named workflow file, on disk;
    * the procedure must not claim what the mechanism does not do, which is where "there is no CI"
      now lives: it is false, so it must be gone.

    `tests/test_cdm_trusted_publishing.py` holds the workflow's own properties — the SHA pins, the
    absent credential, the tag guard on the publish job. This test is only about the PROSE being
    true of it.
    """
    text = MIGRATIONS.read_text()
    section = text[text.index("## Releasing the package"):text.index("\n## History")]
    workflows = REPO / ".github" / "workflows"

    assert workflows.exists(), (
        "the .github/workflows directory is gone, so the procedure below describes a publishing "
        "mechanism that no longer exists. If automation was deliberately removed, this test goes "
        "back to its previous form — asserting the absence and requiring the procedure to say "
        "'there is no CI in this repository' — rather than being deleted"
    )

    named = re.findall(r"`(\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)`", section)
    assert named, (
        "the release procedure describes publishing but names no workflow file. A procedure that "
        "says 'CI publishes it' without saying WHICH file is a procedure nobody can check, and "
        "the file's name is load-bearing: PyPI matches the OIDC token against the workflow path"
    )
    missing = sorted({n for n in named if not (REPO / n).exists()})
    assert not missing, (
        f"the release procedure names workflow file(s) that do not exist: {missing}. This is the "
        "deploy-mechanism failure one artefact along — prose describing a trigger that no file "
        "provides"
    )

    assert "no CI in this repository" not in section, (
        "the release procedure still says there is no CI in this repository. There is: "
        f"{sorted(p.name for p in workflows.glob('*.y*ml'))}. The sentence was true and is now the "
        "most misleading line in the document, because it tells a reader not to look for the thing "
        "that will do the upload"
    )

    for forbidden, why in (
            ("no `.github/workflows`", "the same claim in its other wording"),
            ("a release is a sequence a person runs",
             "the whole sequence is no longer a person's; the upload is the workflow's")):
        assert forbidden not in section, (
            f"the release procedure still states {forbidden!r} — {why}"
        )


# ------------------------------------------------ what rides on `main` between two releases
#
# The SDK close-out round added a CLI affordance (`harness --list-adapters`) and deliberately did
# not tag or re-cut anything: `1.0.0` is on PyPI, a filename on that index can never be reused,
# and a re-release is a new version number or it is nothing. So `main` now carries package source
# that no release contains, while `PACKAGE_VERSION` still reads `1.0.0` — which is the ordinary
# state of a repository between releases and also the state in which a release's notes get
# written from memory.
#
# `MIGRATIONS.md` names that failure itself, as condition 4 of "What a release requires": "the
# notes are derived, not remembered. Every claim in a release's notes has to be readable off the
# tree at the tag." A change that rode on `main` for four months and was never written down is
# not readable off anything — it is exactly the claim that gets remembered wrongly or dropped.
#
# So the condition is made checkable: if the package tree has moved past the tag that names its
# own version, the file has to say what moved. Both directions, because an `Unreleased` section
# describing nothing is its own kind of wrong — it reads as pending work on a tree that has none.


def _released_tag_for_this_version() -> str | None:
    """The tag naming `PACKAGE_VERSION`, if this version has been released at all."""
    return f"v{PACKAGE_VERSION}" if f"v{PACKAGE_VERSION}" in tags() else None


def _package_tree_moved_since(tag: str) -> list[str]:
    """Package files that differ from the tagged commit — committed OR still in the working tree.

    Scoped to `packages/cdm` because that is the distribution: a documentation-only commit at the
    repository root changes nothing a release ships, and requiring a release note for it would
    make the gate noise.

    WHY THE WORKING TREE IS INCLUDED, HAVING ONCE BEEN DELIBERATELY EXCLUDED
    -----------------------------------------------------------------------
    This compared `tag..HEAD` only, on the reasoning that "the unit a release is cut from is a
    commit, and an uncommitted edit is not yet anything". The reasoning is sound and the
    consequence was not: the prose half of this check reads the WORKING TREE, so the two halves
    looked at different trees, and there was a window in which the gate was unsatisfiable.

    Edit a package file after a release, add the `### Unreleased` entry the gate demands, run the
    suite before committing — and it fails, because `tag..HEAD` is still empty while the section is
    already on disk. Its message then says the section "describes changes that are not there" and
    invites deleting it, which is precisely the wrong move and the one a contributor in a hurry
    would make. It happened on the commit that closed ledger entry 6.

    Both sources are now consulted, so the check is evaluable at every moment rather than only at
    the two ends of a commit. An uncommitted edit still is not a release — nothing here says it is —
    but it IS a change to the distribution, and a change to the distribution is what this gate is
    about.
    """
    committed = _git("diff", "--name-only", tag, "HEAD", "--", "packages/cdm")
    assert committed.returncode == 0, committed.stderr
    # `git diff <tag> -- <path>` with no second revision compares the tag to the working tree,
    # which covers staged and unstaged edits in one call.
    working = _git("diff", "--name-only", tag, "--", "packages/cdm")
    assert working.returncode == 0, working.stderr
    both = set(committed.stdout.splitlines()) | set(working.stdout.splitlines())
    return sorted(line.strip() for line in both if line.strip())


UNRELEASED = "### Unreleased"


def test_package_source_that_has_moved_past_its_released_tag_is_recorded_as_unreleased():
    """Condition 4 of the release procedure, enforced before the release rather than during it."""
    _require_git()
    tag = _released_tag_for_this_version()
    if tag is None:
        pytest.skip(f"PACKAGE_VERSION is {PACKAGE_VERSION} and there is no v{PACKAGE_VERSION} "
                    "tag, so this version has not been released and everything in the tree is "
                    "unreleased by construction")
    moved = _package_tree_moved_since(tag)
    text = MIGRATIONS.read_text()
    if moved:
        assert UNRELEASED in text, (
            f"{len(moved)} package file(s) have changed since {tag} — {moved[:6]} — and "
            f"MIGRATIONS.md has no `{UNRELEASED}` section. The distribution on the index is "
            f"{PACKAGE_VERSION} and this tree is not it. Write down what moved, now, while "
            "somebody knows: the release procedure's condition 4 is that the notes are derived "
            "rather than remembered, and a change nobody recorded is not derivable from anything"
        )
    else:
        assert UNRELEASED not in text, (
            f"the package tree is identical to {tag} and MIGRATIONS.md still carries an "
            f"`{UNRELEASED}` section. It describes changes that are not there — either the "
            "release absorbed them and the section should have gone with it, or the diff scope "
            "is wrong"
        )


def test_the_unreleased_section_is_the_first_thing_under_history():
    """Newest first, and nothing is newer than what has not shipped.

    A reader opening the history wants to know what is in the version they have; the entry that
    is NOT in any version they can install has to be the one they cannot miss.
    """
    text = MIGRATIONS.read_text()
    if UNRELEASED not in text:
        pytest.skip("nothing unreleased; the ordering has nothing to order")
    history = text.index("## History")
    entries = [(m.start(), m.group(0).strip())
               for m in re.finditer(r"\n### .+", text[history:])]
    assert entries, "the History section has no entries"
    assert entries[0][1].startswith(UNRELEASED), (
        f"the first entry under `## History` is {entries[0][1]!r}. `{UNRELEASED}` has to come "
        "first: it is the only entry describing something a reader cannot install"
    )


def test_the_unreleased_section_states_that_it_is_in_no_release():
    """The section's whole job is to be un-mistakable for a released one.

    `### Unreleased` beside `### 1.0.0 — initial contract` is two headings of the same shape, and
    a reader skimming for what their installed version contains will read down the list. The
    heading has to say it, not merely be titled it.
    """
    text = MIGRATIONS.read_text()
    if UNRELEASED not in text:
        pytest.skip("nothing unreleased")
    section = text[text.index(UNRELEASED):]
    section = section[:section.index("\n### ", 1)]
    assert "no release" in section or "not in" in section, (
        "the Unreleased section does not say in its own words that nothing in it is in a "
        f"release. Found:\n{section[:300]}"
    )
    assert PACKAGE_VERSION in section, (
        f"the Unreleased section does not name {PACKAGE_VERSION}, which is the version a reader "
        "who ran `pip install synapse-cdm` actually has. Saying which release does NOT contain "
        "this is the entire point of the section"
    )


# ------------------------------------------- prose that names a version, or names a section of this file
#
# Two classes of staleness went into 1.1.0 that nothing in this suite could see, and both were
# found by reading rather than by a gate. They are different failures with the same cause — prose
# stating a fact about a RELEASE, which changes underneath it — so they get one collection each.


#: Documents a consumer or a contributor reads, which state release-scoped facts. `README.md` is
#: the repository's front door; the package README ships INSIDE the wheel, so its claims about
#: which version has what are read by exactly the people who can be misled by them.
VERSION_CLAIM_SITES = ("README.md", "packages/cdm/synapse_cdm/README.md")


def test_no_document_says_a_shipped_feature_is_still_unreleased():
    """`--list-adapters` shipped in 1.1.0. Three documents said it had not.

    Before this release, `README.md` and the package README both carried "**It is on `main` and is
    not in 1.0.0**", and the package README's command block marked the flag `NEXT RELEASE`. All
    three were true for exactly one release and all three were written by hand, so nothing was
    going to notice when they stopped being.

    The check is not "does the prose mention 1.1.0" — that would pass on a document that mentions
    it anywhere. It is the specific shape these three had: a claim that the CURRENT
    `PACKAGE_VERSION` lacks something. That sentence is a contradiction the moment the version bump
    lands, because `PACKAGE_VERSION` is by definition the version this tree IS.
    """
    offenders = []
    for name in VERSION_CLAIM_SITES:
        text = (REPO / name).read_text()
        flat = " ".join(text.split())
        for phrase in (f"is not in {PACKAGE_VERSION}",
                       f"not in {PACKAGE_VERSION}",
                       f"absent from {PACKAGE_VERSION}",
                       "NEXT RELEASE"):
            found = flat.find(phrase)
            if found != -1:
                offenders.append(f"{name}: {phrase!r} — ...{flat[max(0, found - 90):found + 60]}...")
    assert not offenders, (
        f"these documents say something is missing from {PACKAGE_VERSION}, which is the version "
        f"this tree IS:\n  " + "\n  ".join(offenders) + "\n"
        f"A feature absent from the CURRENT version cannot be on `main` — `main` is what "
        f"{PACKAGE_VERSION} was cut from. If the sentence is about an OLDER release, name that "
        "release: 'shipped in 1.1.0; on 1.0.0 it needed a clone' is durable, 'not in the current "
        "version' goes stale on the next bump and reads as authoritative while it does")


def test_every_prose_reference_to_a_section_of_this_file_resolves_to_a_real_heading():
    """A quoted MIGRATIONS.md section name must be a heading MIGRATIONS.md has.

    THE DEFECT THIS CLOSES
    ----------------------
    Four documents pointed a reader at `MIGRATIONS.md`, "Unreleased". The release renamed that
    section to `### 1.1.0` — which the release-condition test above REQUIRES it to do, so the
    rename is not a mistake and the dangling pointers were the guaranteed consequence of doing the
    right thing. Nobody had to get anything wrong for four cross-references to break at once.

    That is the whole argument for the check: the section names in this file are not stable, by
    design. `### Unreleased` exists between releases and is absorbed by each one, so any prose
    citing it has a shelf life of one release. A reference by name is fine — it is much more useful
    than "see MIGRATIONS.md" — provided something notices when the name goes.

    Scoped to citations of THIS file, by requiring `MIGRATIONS` within 120 characters of the quoted
    name. A bare quoted phrase anywhere in the tree is not a citation, and sweeping those would
    match every ordinary use of quotation marks.
    """
    headings = {m.group(1).strip()
                for m in re.finditer(r"\n#{2,3} (.+)", MIGRATIONS.read_text())}
    # A citation may name the heading's leading phrase rather than the whole of it: the 1.1.0
    # heading carries a subtitle after an em dash, and "1.1.0" is the useful way to cite it.
    leading = {h.split(" — ")[0].strip() for h in headings}
    known = headings | leading

    # A WINDOW, not one regex. The first form of this check was
    # `MIGRATIONS[^.]{0,120}?[",]\s*"([^"]+)"` and it matched nothing at all — `[^.]` cannot cross
    # the dot in `MIGRATIONS.md`, which is present in every real citation in the tree. It passed,
    # and it would have passed on the four dangling pointers this test exists for. Two mutations
    # caught it: restoring the "Unreleased" citation, and renaming the 1.1.0 heading. A sweep whose
    # pattern matches nothing reports clean, which is the failure this whole repository is about.
    offenders = []
    for path in sorted(REPO.glob("*.md")) + sorted((REPO / "packages/cdm/synapse_cdm").glob("*.md")):
        flat = " ".join(path.read_text().split())
        for match in re.finditer(r'"([^"]{1,60})"', flat):
            before = flat[max(0, match.start() - 120):match.start()]
            if "MIGRATIONS" not in before:
                continue
            cited = match.group(1).strip().rstrip(".")
            if cited not in known:
                offenders.append(f"{path.relative_to(REPO)}: cites \"{cited}\"")
    assert not offenders, (
        "these cite a MIGRATIONS.md section that does not exist:\n  " + "\n  ".join(offenders)
        + f"\nHeadings it has: {sorted(known)}.\nThe section names in that file are deliberately "
        "unstable — `### Unreleased` is absorbed by every release — so a citation by name has a "
        "shelf life of one release and this is what notices when it expires")


def test_the_proposed_section_does_not_name_a_release_it_could_miss():
    """"Proposed for <version>" is a scheduling promise nothing in the tree can keep.

    THE DEFECT THIS CLOSES
    ----------------------
    `MIGRATIONS.md` and `docs/docs/changelog.mdx` both carried `## Proposed for 1.1.0 (MINOR — not
    yet implemented)`, and 1.1.0 shipped without a line of it. The heading was not wrong when it
    was written and nobody had to make a mistake: it went false at the release, which is precisely
    the moment a reader opens the section to find out what is coming.

    Both now name no version. The number is dropped rather than advanced to 1.2.0, on the same
    reasoning this file records about three pin records that stated one practice as three different
    numbers — the durable statement is the property, and "the next MINOR" is what these items have
    always meant. Advancing it would only re-arm the same failure for one release.

    So this test forbids a version number in either heading. It deliberately does NOT accept "a
    version greater than PACKAGE_VERSION", which was the obvious alternative: that form is true on
    the commit that writes it and false one release later, and a gate that permits a claim with a
    one-release shelf life is a gate that has to be re-satisfied by hand every time. Which release
    these land in is a decision, and a decision belongs in a commit message or an issue, not in a
    heading that ships inside a wheel.
    """
    sites = (("packages/cdm/synapse_cdm/MIGRATIONS.md", "## Proposed for"),
             ("docs/docs/changelog.mdx", "## Proposed for"))
    offenders = []
    for name, prefix in sites:
        text = (REPO / name).read_text()
        for line in text.splitlines():
            if not line.startswith(prefix):
                continue
            if re.search(r"\d+\.\d+\.\d+", line):
                offenders.append(f"{name}: {line.strip()}")
    assert offenders == [], (
        "these headings name a release for work that is not implemented:\n  "
        + "\n  ".join(offenders) + "\n"
        f"`PACKAGE_VERSION` is {PACKAGE_VERSION}, and the last heading of this shape named the "
        "release that then shipped without any of its contents. Name no version: 'Proposed for the "
        "next MINOR' cannot go stale, and which release they land in is a decision that does not "
        "belong in a heading shipped inside a wheel")


# ------------------------------------------------------------------- the release notes, as a claim
#
# `RELEASE_NOTES.md` is new in 1.1.0. 1.0.0's notes existed only as the body of a GitHub release,
# which means nothing could ever compare them to the tree they claimed to describe — and condition 4
# of the release procedure is precisely that every claim in them is readable off the tree at the tag.
# A notes file in the repository makes that condition checkable instead of aspirational.

NOTES = REPO / "RELEASE_NOTES.md"


def test_the_release_notes_describe_this_version():
    """The notes' two version numbers are the tree's two version numbers.

    The failure this catches is the ordinary one: notes copied forward from the previous release
    and edited in the places somebody remembered. Both numbers are stated in the notes' own second
    paragraph, and both are derivable here.
    """
    text = NOTES.read_text()
    assert f"# synapse-cdm {PACKAGE_VERSION}" in text, (
        f"RELEASE_NOTES.md does not open with `# synapse-cdm {PACKAGE_VERSION}`. It describes "
        "whatever release it was last written for, and the version bump did not reach it")
    assert f"Package version {PACKAGE_VERSION}" in text, (
        f"the notes do not state package version {PACKAGE_VERSION}")
    assert f"`schema_version` {SCHEMA_VERSION}" in text, (
        f"the notes do not state schema_version {SCHEMA_VERSION}. These are two different facts "
        "and the notes are one of the few documents that states both, so it is one of the few "
        "places they can be made to disagree")


def test_the_release_notes_roster_table_is_the_registry():
    """Every adapter in the notes' table is registered, and every registered adapter is in it.

    Both directions. A table missing an adapter under-sells a release and, worse, tells a reader
    the roster is smaller than it is — which is the thing `--list-adapters` was added to stop. A
    table naming an adapter that does not exist is a release note for software nobody received.
    """
    text = NOTES.read_text()
    registered = {name for name, cls in adapter_roster().items()
                  if cls.__module__.startswith("synapse_cdm.adapters.")}
    # The table's first column, as ``| `name` |``.
    tabled = set(re.findall(r"^\|\s*\*{0,2}`([a-z0-9_]+)`\*{0,2}\s*\|", text, re.MULTILINE))
    assert tabled, (
        "no adapter rows were found in RELEASE_NOTES.md. If the table's shape changed, re-anchor "
        "this pattern — a sweep that matches nothing reports clean")
    missing = sorted(registered - tabled)
    unknown = sorted(tabled - registered)
    assert not missing and not unknown, (
        f"the notes' roster table and the registry disagree — in the registry but not the table: "
        f"{missing}; in the table but not the registry: {unknown}. The table is the release's "
        "public statement of what a consumer gets")


def test_the_release_notes_name_the_mechanism_that_published_them():
    """The notes claim OIDC and name the workflow; the workflow has to exist and carry no secret.

    This is the same closure `tests/test_cdm_trusted_publishing.py` applies to the other documents,
    applied to the one document a consumer is most likely to read: a release note is where a
    supply-chain claim is actually made to the public, so it is the worst place for one that is no
    longer true.
    """
    text = NOTES.read_text()
    named = re.findall(r"`(\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)`", text)
    assert named, (
        "RELEASE_NOTES.md describes how the release was published but names no workflow file. "
        "'published by CI' is not a checkable claim")
    for path in named:
        assert (REPO / path).exists(), (
            f"the notes name {path}, which does not exist. The notes would be telling a reader "
            "their artefact was built by a file that is not in the repository")
        body = (REPO / path).read_text()
        live = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        assert "secrets." not in live and not re.search(r"^\s*password:", live, re.MULTILINE), (
            f"{path} now carries a credential, and RELEASE_NOTES.md claims this release was "
            "published with none. One of the two has to change, and it should not be the workflow")


def test_the_release_notes_keep_an_artefacts_section_that_says_where_the_digests_are():
    """The notes must NOT carry digests, and must say where they are instead.

    A CORRECTION TO THIS TEST'S FIRST FORM, WHICH WOULD HAVE BLOCKED THE RELEASE
    ---------------------------------------------------------------------------
    It first required the digests to be filled in once a `v{PACKAGE_VERSION}` tag existed, on the
    reasoning that a published Artefacts section listing nothing reads as "there is nothing to
    verify". The hinge was wrong, and wrong in the direction that stops a release: the tag exists
    BEFORE the workflow builds anything, so on the tagged tree the digests cannot exist — and the
    workflow runs `pytest -q` on exactly that tree. The test failed at the tag, which would have
    failed condition 1 and published nothing.

    The deeper error was putting them in the tree at all. Condition 4 requires every claim in the
    notes to be **readable off the tree at the tag**, and a digest is not: it is a property of one
    build, and two builds of one tree are not the same bytes. A digest committed here would either
    be a local build's — different bytes from what PyPI serves, so a false claim — or it would have
    to be written back after publication, which makes the tagged tree's notes permanently unable to
    satisfy their own gate.

    So digests live where measured facts about published artefacts already live in this repository:
    `PUBLICATION.md`'s ledger, which carries 1.0.0's in entry 5. The notes point there and to the
    release body. What this test defends is that the pointer survives — an Artefacts section
    quietly deleted is how a release stops being verifiable.
    """
    text = NOTES.read_text()
    assert "## Artefacts" in text, (
        "RELEASE_NOTES.md has no `## Artefacts` section. It is where a reader is told how to check "
        "that what they installed is what was published, and its absence reads as nothing to check")
    section = text[text.index("## Artefacts"):]
    assert "PUBLICATION.md" in section, (
        "the Artefacts section does not point at PUBLICATION.md, where this repository records the "
        "SHA-256 of every published artefact — entry 5 does it for 1.0.0")
    local = re.findall(r"\b[0-9a-f]{64}\b", text)
    assert not local, (
        f"RELEASE_NOTES.md carries {len(local)} SHA-256 digest(s) inline. Do not commit them here: "
        "a digest is a property of one BUILD, not of the tree, and two builds of one tree differ in "
        "their generated metadata. A digest in the tagged tree is either a local rebuild's — which "
        "is not what PyPI serves — or a value that can only be written after the tag, which no "
        "tagged tree can contain. They belong in PUBLICATION.md and in the release body")


def test_every_documented_tag_command_names_this_trees_package_version():
    """A copy-pasteable `git tag -a vX.Y.Z` has to name the tag a reader should actually push.

    THE DEFECT THIS CLOSES, FOUND BY THE 1.2.0 RELEASE AUDIT. `README.md` and `MIGRATIONS.md` both
    print the release procedure as two shell lines, and both still read `git tag -a v1.1.0` after
    1.1.0 had shipped. A reader following the procedure would have pushed a tag that already exists:
    git refuses it locally, and had they forced it the workflow's own tag-names-the-version check
    would have refused the upload. So the failure was recoverable — and it is exactly the class this
    repository guards everywhere else, a fact restated in prose and checked nowhere.

    Deliberately anchored on the COMMAND rather than on every `v1.1.0` in the tree. The documents
    are full of correct historical references to released tags — `PUBLICATION.md` records the v1.1.0
    run, `test_cdm_trusted_publishing.py` names it as the release it published — and a sweep over
    the bare string would have to exempt all of them. What must be current is the instruction.
    """
    offenders = []
    for path in sorted(REPO.glob("*.md")) + sorted((REPO / "packages/cdm/synapse_cdm").glob("*.md")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            for match in re.finditer(r"git tag -a v(\d+\.\d+\.\d+)", line):
                if match.group(1) != PACKAGE_VERSION:
                    offenders.append(
                        f"{path.relative_to(REPO)}:{number} says v{match.group(1)}")
    assert not offenders, (
        f"these documented tag commands do not name {PACKAGE_VERSION}, which is the version this "
        f"tree IS:\n  " + "\n  ".join(offenders) + "\n"
        "A reader copying one would push a tag that already exists. The command is an instruction, "
        "not a record — historical references to a released tag are fine and are not swept here"
    )
