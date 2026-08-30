"""What the built distribution carries — decided here, rather than discovered by a partner.

WHY THIS EXISTS, AND THE DEFECT IS A COUNT
-------------------------------------------
`pyproject.toml` used to declare what ships as a hand-written list of file EXTENSIONS —
`fixtures/**/*.json`, `*.xml`, `*.nmea`, `*.adsb`, `*.cat021`, `*.gmti`, `*.md`, `*.py` — each
one with a paragraph beside it explaining why the raw bytes matter as much as the parsed twin.
The paragraphs were right. The list still went stale, twice, in the way an enumeration does:
CAT048 shipped and nobody added `*.cat048`; CAT034 shipped and nobody added `*.cat034`.

The built wheel was missing **72 of the 692 files** the package tracks — every raw ASTERIX data
block for two of the ten adapters. Nothing caught it, and nothing would have: the harness still
ran green against that wheel, because the `.parsed.json` twins were present. It was measuring two
adapters against half their evidence, which is the exact failure the comment beside the list
existed to prevent, committed by the list itself.

This is the same shape as `tests/test_cdm_pins.py`'s eight-versus-nine, and it takes the same
repair: **delete the enumeration, derive the set, and close it in both directions.** The include
rule is now one recursive glob and the two things that must never ship are named positively.

THE CLOSURE, WHICH IS THE PART WITH TEETH
------------------------------------------
The set of files the distribution would carry must EQUAL the set of files git tracks under
`packages/cdm/synapse_cdm/`. Both directions:

* a tracked file the globs miss FAILS — that is the 72;
* a shippable file git does not track FAILS — and that is the one that matters on a maintainer's
  machine, because the pinned specification PDFs are gitignored and sitting on disk. A build here
  was one widened glob away from redistributing a EUROCONTROL specification and three NATO
  standards inside an Apache-2.0 wheel, against what `NOTICE` says outright.

WHAT THIS MODULE CANNOT CHECK, AND WHAT DOES
---------------------------------------------
It does not build anything. It reads the globs and applies them to the tree with the same
`glob(..., recursive=True)` semantics setuptools uses, which was verified against a real built
wheel (692 = 692, no difference in either direction) and is re-verified on every run of
`gates/wheel_install.py`, which compares a REAL wheel's manifest against this same derivation.
The division is deliberate and is the one `tests/test_cdm_getting_started.py` already makes: the
suite asserts the agreement between declarations, and the end-to-end claim is a gate that
installs the artefact.
"""
import glob
import pathlib
import re
import subprocess
import tomllib

import pytest

import synapse_cdm
from synapse_cdm.version import PACKAGE_VERSION, SCHEMA_VERSION

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
DIST = PKG.parent                      # packages/cdm — the distribution root
REPO = PKG.parents[2]
PYPROJECT = DIST / "pyproject.toml"


def config() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def _expand(patterns: list[str], root: pathlib.Path) -> set[str]:
    """Setuptools' package-data semantics: `glob(pattern, recursive=True)` under the package dir.

    Directories are dropped rather than followed. `fixtures/**/*` matches `fixtures/tak` itself as
    well as the files under it, and a directory in a package-data list contributes its files
    through the same recursion rather than as an entry of its own.
    """
    found: set[str] = set()
    for pattern in patterns:
        for match in glob.glob(pattern, root_dir=root, recursive=True):
            if (root / match).is_file():
                found.add(match)
    return found


def shippable() -> set[str]:
    """Every path the built distribution would carry, relative to `packages/cdm/`.

    The two halves setuptools has: modules found by `packages.find` (every `.py` inside a
    directory that is a package) and data matched by `package-data` minus `exclude-package-data`.
    `fixtures/` is not a package — it has no `__init__.py` — so `fixtures/*/spec/build_fixtures.py`
    arrives through the data half, which is why the data half has to be allowed to carry `.py`.
    """
    setuptools = config()["tool"]["setuptools"]
    data = (_expand(setuptools["package-data"]["synapse_cdm"], PKG)
            - _expand(setuptools["exclude-package-data"]["synapse_cdm"], PKG))
    modules = {str(p.relative_to(PKG)) for p in PKG.rglob("*.py")
               if "__pycache__" not in p.parts and p.relative_to(PKG).parts[0] != "fixtures"}
    return {f"synapse_cdm/{path}" for path in data | modules}


def tracked() -> set[str]:
    """What git holds under the package, which is the honest definition of "the package"."""
    out = subprocess.run(["git", "ls-files", "synapse_cdm"], cwd=DIST,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return set(out.stdout.split())


def _require_git() -> None:
    """SKIP, never PASS, where there is no index to read — and say which case it is.

    Same treatment as `tests/test_cdm_publication.py`: an sdist or an unpacked wheel has the
    package and no `.git`, and failing there would report a broken repository when what was found
    was a legitimate distribution form.
    """
    if not (REPO / ".git").exists():
        pytest.skip("no .git in this tree (an sdist or an unpacked wheel is the normal case), so "
                    "the tracked file set cannot be read and the closure is NOT asserted here")


# --------------------------------------------------------------------------- the closure


def test_the_distribution_would_carry_exactly_the_files_git_tracks_under_the_package():
    """Equality, both directions, derived on both sides. The 72 is what direction one catches."""
    _require_git()
    ships, in_git = shippable(), tracked()
    missing = sorted(in_git - ships)
    assert not missing, (
        f"{len(missing)} tracked file(s) would NOT be in the built distribution, starting with "
        f"{missing[:6]}. This is the defect this module exists for: the wheel was once short by "
        "72 raw ASTERIX blocks and the harness still reported green against it, because the "
        "parsed twins were there. Widen the package-data glob — do not add an extension to a list"
    )
    extra = sorted(ships - in_git)
    assert not extra, (
        f"{len(extra)} file(s) would be shipped that git does not track, starting with "
        f"{extra[:6]}. On a maintainer's machine the untracked files under this package are the "
        "pinned specification PDFs — EUROCONTROL's and NATO's, under their own terms, which "
        "NOTICE states outright are not part of the Work. Shipping one inside an Apache-2.0 "
        "wheel is a licensing defect, not an oversight"
    )


def test_no_specification_document_is_shippable():
    """The exclusion, asserted as a property of the RESULT rather than of the pattern.

    A pattern test would pass on `fixtures/*/spec/*.pdf` after somebody moved the documents one
    directory deeper. This asks what the globs actually select, which is the question.
    """
    ships = shippable()
    pdfs = sorted(p for p in ships if p.lower().endswith(".pdf"))
    assert not pdfs, f"specification documents would be shipped: {pdfs}"
    stray = sorted(p for p in ships if "/spec/" in p
                   and pathlib.PurePosixPath(p).name != "build_fixtures.py"
                   and not pathlib.PurePosixPath(p).name.endswith("_pin.json"))
    assert not stray, (
        f"{stray} would be shipped from a spec/ directory. Only two classes belong in a "
        "distribution from there: `build_fixtures.py`, which is the reviewable form of a fixture "
        "set an ASTERIX block cannot document itself, and `*_pin.json`, which NOTICE points at "
        "for each pinned document's terms. Anything else in spec/ is somebody else's document"
    )


def test_the_specification_exclusion_bites_on_a_tree_that_actually_has_one(tmp_path):
    """The mutation, run rather than reasoned about — and it has to be run on a SYNTHETIC tree.

    In a fresh clone the PDFs are absent (they are gitignored and none of their bytes is in the
    history), so the closure above passes whether the exclusion works or not. That makes the whole
    protection conditional on a maintainer's local disk, which is the same accident the floor gate
    was found keying on. So the rule is exercised against a tree built here to contain exactly the
    shapes that must be refused.
    """
    setuptools = config()["tool"]["setuptools"]
    root = tmp_path / "synapse_cdm"
    planted = ["fixtures/demo/README.md",
               "fixtures/demo/payload.weirdext",          # a format nobody has thought of yet
               "fixtures/demo/golden/payload.cdm.json",
               "fixtures/demo/spec/build_fixtures.py",
               "fixtures/demo/spec/demo_pin.json",
               "fixtures/demo/spec/nato-something-edition-a.pdf",
               "fixtures/demo/spec/history/nato-something-edition-a-v0.pdf"]
    for rel in planted:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")

    selected = (_expand(setuptools["package-data"]["synapse_cdm"], root)
                - _expand(setuptools["exclude-package-data"]["synapse_cdm"], root))

    assert "fixtures/demo/spec/nato-something-edition-a.pdf" not in selected, \
        "a current-edition specification document would be shipped"
    assert "fixtures/demo/spec/history/nato-something-edition-a-v0.pdf" not in selected, \
        "a superseded specification document would be shipped — spec/history/ needs its own " \
        "exclusion pattern, and this is the case that proves it"
    # And the positive half, which is what stops the exclusion being widened into a hole: the
    # include rule has to carry a format that did not exist when it was written. `.weirdext`
    # stands in for `.cat048` and `.cat034`, which is how the 72 went missing.
    assert "fixtures/demo/payload.weirdext" in selected, \
        "an unheard-of fixture extension must ship; that is the whole reason the include rule " \
        "is a recursive glob rather than a list of extensions"
    assert {"fixtures/demo/README.md", "fixtures/demo/golden/payload.cdm.json",
            "fixtures/demo/spec/build_fixtures.py",
            "fixtures/demo/spec/demo_pin.json"} <= selected


# ----------------------------------------------------------------- licence text in the wheel


def test_the_licence_and_notice_travel_with_the_distribution():
    """A wheel that says `License-Expression: Apache-2.0` and carries no licence text.

    That is what was built before this: an SPDX identifier and nothing to identify. `LICENSE` and
    `NOTICE` are at the repository root, outside `packages/cdm/`, and `license-files` globs are
    resolved relative to the distribution root — so setuptools found neither and said nothing.

    NOTICE is the one with legal weight rather than tidiness: Apache-2.0 section 4(d) requires a
    redistributor of a Work that includes a NOTICE file to carry its attribution notices forward,
    and a wheel on an index IS a redistribution. NOTICE also carries the sentence that keeps the
    pinned specifications outside the licence, which a wheel shipping pin records needs beside it.
    """
    declared = config()["project"].get("license-files")
    assert declared == ["LICENSE", "NOTICE"], (
        f"license-files is {declared!r}. Both, and NOTICE is not optional: section 4(d) makes "
        "carrying it a condition of redistributing this Work"
    )
    for name in declared:
        assert (DIST / name).is_file(), (
            f"packages/cdm/{name} is missing, so the built distribution would carry no {name} — "
            "the globs resolve against the distribution root, not the repository root"
        )


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_the_copy_beside_the_package_is_byte_identical_to_the_original(name):
    """The copy is allowed to exist only because this makes drift impossible.

    Two files with one text is exactly what `schemas.py` argues against for the schemas and what
    the repository does for CLAUDE.md/AGENTS.md: permitted when a test forbids divergence. The
    alternatives were worse. A symlink is not portable to a Windows clone and setuptools would
    resolve it into the archive anyway; moving the originals down into `packages/cdm/` would take
    `LICENSE` out of the repository root, where GitHub's licence detection and every SPDX scanner
    look for it.
    """
    original = (REPO / name).read_bytes()
    copy = (DIST / name).read_bytes()
    assert copy == original, (
        f"packages/cdm/{name} has drifted from {name} at the repository root. The copy exists "
        "only to be packaged; the root file is the original. Re-copy it rather than editing "
        "either half — a wheel carrying a different licence text from the repository it came "
        "from is worse than one carrying none"
    )


# ------------------------------------------------------------------ the two version numbers


def test_the_packaging_version_is_the_packages_own_and_not_the_schemas():
    """The ruling, asserted at the one site that could quietly undo it.

    `pyproject.toml` used to read `SCHEMA_VERSION`, and the reasoning for it was written out at
    length above the line. It was defending a real failure — a wheel labelled 1.0.0 shipping
    objects that say 1.1.0 — by a means that made a second release of the same contract
    unexpressible. See `synapse_cdm/version.py` for the full ruling.
    """
    attr = config()["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "synapse_cdm.version.PACKAGE_VERSION", (
        f"the packaging version is read from {attr!r}. It must be PACKAGE_VERSION: reading "
        "SCHEMA_VERSION ties every release of this distribution to a change in the WIRE "
        "CONTRACT, and MIGRATIONS.md already lists twelve adapters that shipped without one"
    )


def test_the_two_versions_are_independent_and_nothing_derives_one_from_the_other():
    """The sweep. Neither number may be computed from the other, anywhere in the package.

    THEY HAVE NOW PARTED, AND THAT CHANGES WHAT THIS TEST IS WORTH
    -------------------------------------------------------------
    This docstring used to say they were both `1.0.0`, "which is precisely when this is cheap to
    get wrong and impossible to notice: any expression that derived one from the other would
    produce the right answer on every run until the first release that moved them apart."

    1.1.0 is that release. `PACKAGE_VERSION` is now `1.4.0` and `SCHEMA_VERSION` is `1.0.0`,
    because every entry in both releases added a surface and touched no schema. So the sweep below
    has teeth it did not have when it was written: a derivation of either number from the other now
    produces a WRONG answer at runtime rather than a right one by coincidence, and would be caught
    by the schema tests, the packaging metadata and this sweep at once.

    **1.2.0 is the release that put the arrangement to a real test**, which is worth a line because
    the first parting was almost free — 1.1.0 added two adapters and nobody thought a schema had
    moved. 1.2.0 ships a new KIND of output, a structured defect annotation, and the question was
    put explicitly and answered from the schema files themselves: the annotation lives inside
    `Entity.attributes` and `Event.payload`, which the published schemas declare
    `additionalProperties: true` while the objects carrying them are `additionalProperties: false`.
    `MIGRATIONS.md`'s 1.2.0 section holds the evidence with file and line. Two numbers were what
    made "new output, same contract" expressible at all.

    The sweep is kept anyway, and not as ceremony. It is cheaper than the failure it prevents, it
    names the reason in its message, and the window it was written for reopens on the day a schema
    change makes the two numbers equal again — which will happen, because a `SCHEMA_VERSION` bump
    is always at least a package MINOR.
    """
    offenders = []
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "version.py":
            continue
        text = path.read_text()
        for line in text.splitlines():
            if re.search(r"PACKAGE_VERSION\s*=\s*.*SCHEMA_VERSION", line) or \
                    re.search(r"SCHEMA_VERSION\s*=\s*.*PACKAGE_VERSION", line):
                offenders.append(f"{path.relative_to(REPO)}: {line.strip()}")
    assert not offenders, (
        f"one version number is derived from the other: {offenders}. They are different facts — "
        "MIGRATIONS.md governs schema_version, ordinary semver governs the package — and an "
        "assignment linking them reads as correct for exactly as long as they happen to be equal"
    )
    # Both pinned as literals, so every bump is a deliberate edit here as well as in version.py.
    # The instruction the previous form of this assertion carried — "that is the expected event,
    # and the fix is to update this assertion to the two numbers you now mean, not to re-link
    # them" — is what was followed to get these values, and it still applies to the next bump.
    assert (PACKAGE_VERSION, SCHEMA_VERSION) == ("1.4.0", "1.0.0"), (
        f"the two versions are {PACKAGE_VERSION} and {SCHEMA_VERSION}; this test pins them at "
        "1.4.0 and 1.0.0. They are no longer equal and have not been since 1.1.0, which is the "
        "release that made their independence a measured fact rather than an argument. If you are "
        "reading this because you bumped one of them: that is the expected event, and the fix is "
        "to update this assertion to the two numbers you now mean, not to re-link them"
    )
    assert PACKAGE_VERSION != SCHEMA_VERSION or SCHEMA_VERSION != "1.0.0", (
        "the two numbers are equal at 1.0.0 again, which is the state this sweep was written for "
        "and cannot happen by a package bump alone. If a schema change brought them back level, "
        "say so in MIGRATIONS.md and re-pin above — the sweep above is load-bearing again, "
        "because a derivation of one from the other would once more produce the right answer"
    )


def test_version_py_is_the_only_place_the_distinction_is_explained():
    """Stated once. Every other site points at it rather than restating it.

    A rule explained in four places is a rule with four chances to be explained differently, and
    the failure mode here is a document that tells a partner the two numbers are the same thing.
    Sites are allowed to NAME both numbers — MIGRATIONS.md's release procedure has to — but the
    reasoning lives in one file.
    """
    # This module has to quote the heading in order to look for it, so sweeping itself would
    # flag the checker — the exemption `tests/test_cdm_deploy_workflow.py` makes for the same
    # reason. Exempted by identity rather than by name so a rename cannot silently widen it.
    marker = "WHY THEY MUST BE ALLOWED TO DIVERGE"
    this_file = pathlib.Path(__file__).resolve()
    holders = [p.relative_to(REPO) for p in REPO.rglob("*.py")
               if ".venv" not in p.parts and "node_modules" not in p.parts
               and "__pycache__" not in p.parts and p.resolve() != this_file
               and marker in p.read_text()]
    assert holders == [pathlib.Path("packages/cdm/synapse_cdm/version.py")], (
        f"the divergence ruling is stated in {holders}. It belongs in version.py and nowhere "
        "else; other sites route to it"
    )


# ----------------------------------------------------------- metadata a published wheel needs


def test_the_distribution_is_named_the_way_an_index_will_normalise_it():
    """`synapse-cdm` on the index, `synapse_cdm` on the import line, and the two differing is fine.

    Declared in the normalised form (PEP 503) because that is the string that appears on the
    project page and in every `pip install` line anybody will ever type. The underscore form is
    legal and would have resolved identically; it would also have put a name into the metadata
    that no reader is ever shown.
    """
    assert config()["project"]["name"] == "synapse-cdm"
    assert synapse_cdm.__name__ == "synapse_cdm", \
        "the import name is a Python identifier and cannot carry a hyphen; only the " \
        "distribution name is normalised"


def test_the_metadata_a_publishable_distribution_needs_is_complete():
    """The pre-publication checklist, as assertions rather than as a paragraph somebody rereads.

    Each of these was missing or wrong before this round, and each is invisible until the project
    page renders: an author that is not the legal entity, a Documentation link that led back to
    the page the reader was already on, no Issues URL, and classifiers that said nothing about
    which Pythons the floor gate actually defends.
    """
    project = config()["project"]
    assert project["authors"] == [{"name": "Decent Cybersecurity s.r.o."}], (
        f"authors is {project['authors']}. The legal entity, spelled as NOTICE spells it — the "
        "copyright holder and the author of a published distribution are the same party here"
    )
    assert project["license"] == "Apache-2.0", "an SPDX expression, matching LICENSE and NOTICE"
    assert project["readme"] == "synapse_cdm/README.md", \
        "the long description PyPI renders. It has to be a file inside the distribution"
    assert (DIST / project["readme"]).is_file()

    urls = project["urls"]
    for key in ("Homepage", "Documentation", "Source", "Issues", "Changelog"):
        assert key in urls, f"project.urls is missing {key}"
        assert urls[key].startswith("https://"), f"{key} is not https"
    assert urls["Documentation"] == "https://docs.synapsecommand.com/", (
        f"Documentation points at {urls['Documentation']}. It used to point at the raw "
        "synapse_cdm/README.md on GitHub — which is the very file PyPI renders as this project's "
        "long description, so the link led back to the page the reader was standing on"
    )

    classifiers = project["classifiers"]
    assert "Development Status :: 5 - Production/Stable" in classifiers, (
        "the same claim version.py rules 1.0.0 on. Beta here and 1.0.0 there would be two "
        "answers to one question, on the same page"
    )
    floor = project["requires-python"]
    assert floor == ">=3.11", f"requires-python is {floor}; tests/test_cdm_version_floor.py " \
                              "asserts the package parses at the floor it declares"
    assert "Programming Language :: Python :: 3.11" in classifiers, (
        "the declared floor has to appear as a classifier too, or the project page and "
        "requires-python disagree about the oldest supported interpreter"
    )
    # No `License ::` classifier: PEP 639 deprecated them in favour of the SPDX expression, and
    # declaring both is how a project ends up with two licences on its page.
    assert not [c for c in classifiers if c.startswith("License ::")], (
        "a License:: classifier alongside a license expression is the deprecated form; PyPI "
        "rejects the combination"
    )


# ------------------------- the repository's layout, named inside the distribution it does not fit
#
# THE INCIDENT, AND IT IS WHY THIS IS HERE RATHER THAN ONLY IN THE WHEEL GATE.
# `gates/wheel_install.py`'s `check_no_repo_paths` refuses a built distribution whose shipped
# `.py`/`.md` name the package's own contents the way the development repository lays them out.
# The rule is not "never mention the repository": what is always wrong for an installed reader is a
# path INTO the package's insides, because they have that directory under a different name, so the
# instruction looks right, resolves, and fails on a path they never chose.
#
# On 2026-08-28 a round record explaining the two-base pin defect spelled that layout while
# explaining it. The gate went red and **stayed red on `main` for a day**, because condition 2's
# actor is the release workflow and the workflow runs on a tag — so the only gate that reads the
# built artefact is also the only one nothing exercises between releases. It was found on
# 2026-08-29 by a release round that ran the gate its Act 4 requires and then REFUSED the release
# for an unrelated reason — so the gate that would have caught this at the tag was never going to
# be reached, and the finding survives its round. That is the argument for moving the check here.
#
# WHAT THIS ADDS AND WHAT IT DELIBERATELY DOES NOT REPLACE. The wheel gate stays authoritative: it
# reads the ZIP, so it sees what a consumer receives, including anything `package-data` sweeps in
# that `git` does not track. This runs the same needle over the TRACKED distribution — no wheel, no
# venv, no network — so it costs milliseconds and fires on the commit that writes the sentence
# rather than on the tag that would have shipped it. The needle is spelled once, here, and this
# module is excluded from its own scan for the reason the pinned-phrase guard states about itself:
# a check that counted its own source would refuse the file that defines it.

#: The path shape that is always wrong inside a shipped file. Same string as the wheel gate's.
REPO_LAYOUT_NEEDLE = "packages/cdm/synapse_cdm/"


def test_no_shipped_file_names_the_packages_own_contents_by_the_repository_layout():
    """`gates/wheel_install.py`'s prose rule, over the tracked tree, on every commit."""
    listed = subprocess.run(["git", "ls-files", "synapse_cdm"], cwd=DIST,
                            capture_output=True, text=True, check=True).stdout.split()
    offenders = []
    scanned = 0
    for name in listed:
        if not name.endswith((".py", ".md")):
            continue
        scanned += 1
        path = DIST / name
        for number, line in enumerate(path.read_text(encoding="utf-8",
                                                     errors="replace").splitlines(), 1):
            if REPO_LAYOUT_NEEDLE in line:
                offenders.append(f"{name}:{number}: {line.strip()[:90]}")
    assert scanned, (
        "no tracked .py/.md was scanned under the distribution, so a PASS here would mean nothing "
        "— the same non-vacuity the wheel gate asserts by deriving its own expected count"
    )
    assert not offenders, (
        f"{len(offenders)} shipped line(s) name a path inside this package using the repository's "
        "layout, which is a directory an installed reader has under another name:\n  "
        + "\n  ".join(offenders)
        + "\nWrite it as the package directory, or name the gate that derives the base. "
          "`gates/wheel_install.py` refuses the built artefact for this and is condition 2 of the "
          "release procedure; this test exists so the refusal does not wait for a tag"
    )
