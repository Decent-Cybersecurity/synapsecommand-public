"""The lint stage: one pin, one rule set, and two workflows that read both from the same file.

WHY THIS MODULE EXISTS — 2026-09-16
-----------------------------------
Until this date ruff ran in exactly one place, `publish.yml`'s gate — a tag push or a dispatch —
with its version typed into that step (`pip install "ruff==0.16.6"`) and its rule set in
`packages/cdm/pyproject.toml`. Nothing in `ci.yml` ran it, nothing in the `test` extra installed it,
and CONTRIBUTING.md's documented path never mentioned it, so a contributor had no way to run the
gate the release would apply, and a finding surfaced at tag time and nowhere earlier. The
repository's own lint comment names that exposure: a stage added red is a stage somebody switches
off.

And the rule set did not do what its comments said. Under ruff 0.16.6, `select = ["E9"]` enables
exactly one rule — `io-error` (E902) — a syntax error is reported regardless of selection, and an
undefined name is pyflakes' F821, which `E9` never included; three sentences in three files said
"syntax errors and undefined names". The set became `E9,F821` that day and `E9,F,E7,W` on
2026-09-20 (audit remediation F09, `RULE_SET` below), and this module holds the four
things that were fixed together so that none of them drifts back alone:

1. the ruff version is pinned ONCE, in the `[lint]` extra, as `ruff==<version>`;
2. both workflows install that extra and neither types a `ruff==` of its own;
3. both workflows run the same command, `--config` and all three roots;
4. the rule set is the documented one.

REPOSITORY-BOUND: it reads `.github/workflows/` and the repository's `pyproject.toml`, none of
which ships in the wheel.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
PYPROJECT = REPO / "packages" / "cdm" / "pyproject.toml"

#: The two workflows that run the lint stage: the release gate, and CI on every push.
LINTING_WORKFLOWS = ("ci.yml", "publish.yml")

#: The command, verbatim. `--config` because there is no pyproject.toml at the repository root, so
#: `gates/` and `tests/` would otherwise be linted under ruff's DEFAULT rule set; the three roots
#: because the gate is over the package, the gates and the suite and not over the package alone.
LINT_COMMAND = "ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests"

#: The rule set, as a second copy on purpose — the same reason `tests/test_cdm_trusted_publishing.py`
#: states the environment name as a third copy: a test that derived this from pyproject.toml would
#: move with it and check nothing. Widening it is a ruling and an edit to both files — done once,
#: 2026-09-20 (audit remediation F09): `E9,F821` became `E9,F,E7,W` over an explicit per-file
#: legacy baseline, and the test below holds that baseline to files that exist and to one list per
#: file so that it can only shrink.
RULE_SET = ["E9", "F", "E7", "W"]

#: How the extra installs the linter: the version pinned exactly, never floored, because the rule
#: set above was measured against one version and a newer ruff can change what a rule sees.
RUFF_PIN = re.compile(r"^ruff==\d+\.\d+\.\d+$")


def _executable(text: str) -> str:
    """The workflow minus its comment lines: the header quotes `ruff==` to explain the refusal."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------- the one pin

def test_the_lint_extra_pins_ruff_exactly_once():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "lint" in extras, (
        "pyproject.toml declares no `[lint]` extra. That extra is the one place the ruff version "
        "is pinned; without it both workflows would have to type a version of their own")
    assert len(extras["lint"]) == 1 and RUFF_PIN.match(extras["lint"][0]), (
        f"the `[lint]` extra is {extras['lint']!r}; it should be exactly one requirement of the "
        "form `ruff==X.Y.Z`. A floor (`>=`) would let the rule set be read by a version it was "
        "never measured against, and a second requirement would make the extra something other "
        "than the linter's pin")


def test_the_rule_set_is_the_documented_one():
    """`E9,F,E7,W` — the set the release-pipeline page and pyproject.toml's comment describe."""
    select = _pyproject()["tool"]["ruff"]["lint"]["select"]
    assert select == RULE_SET, (
        f"[tool.ruff.lint] selects {select} and the documented set is {RULE_SET}. The lint "
        "comments in pyproject.toml and the release-pipeline page describe this set; change "
        "the set and the sentences in the same commit")
    assert "F821" in select or "F" in select, "the undefined-name rule left the set"


def test_the_legacy_baseline_names_files_that_exist_and_carries_no_blanket_entry():
    """The per-file baseline the 2026-09-20 widening was added green under.

    A baseline is only honest while every entry is a real file with a short list of rules: a glob,
    a directory, or an `ALL` entry would be the blanket suppression the finding forbids, and an
    entry for a file that no longer exists is a suppression waiting for a new file of that name.
    """
    baseline = _pyproject()["tool"]["ruff"]["lint"].get("per-file-ignores", {})
    assert baseline, "the baseline is gone; if every legacy finding was repaired, delete this test"
    for pattern, rules in baseline.items():
        if pattern.startswith("**/"):
            # The one shape a glob may take: a bare basename, because the file's directory is a
            # word `tests/test_cdm_scripted_edits.py` refuses in any directive of pyproject.toml.
            # It is still one file: the basename must resolve to exactly one file in the tree.
            basename = pattern[3:]
            assert "*" not in basename and "/" not in basename, f"{pattern!r} is a glob, not a file"
            matches = [p for p in REPO.rglob(basename)
                       if ".venv" not in p.parts and "node_modules" not in p.parts]
            assert len(matches) == 1, f"{pattern!r} names {len(matches)} files: {matches}"
        else:
            assert "*" not in pattern, f"{pattern!r} is a glob, not a file"
            # Repository-root relative, because that is the working directory of the one
            # documented invocation (`LINT_COMMAND`, run from the root) and ruff resolves a
            # `--config` file's globs against the working directory.
            assert (REPO / pattern).is_file(), f"{pattern!r} is not a file under the repository root"
        assert rules and all(re.fullmatch(r"[A-Z]+\d+", rule) for rule in rules), (
            f"{pattern!r} ignores {rules}; every entry names specific rule codes, never a prefix")
    assert len(baseline) <= 13, (
        f"the baseline has {len(baseline)} entries and was written with 13; it may only shrink")


# ------------------------------------------------------------- the workflows read the pin, never type it

@pytest.mark.parametrize("name", LINTING_WORKFLOWS)
def test_the_workflow_installs_the_extra_and_types_no_version(name):
    executable = _executable((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert 'pip install -e "packages/cdm[lint]"' in executable, (
        f"{name} does not install the `[lint]` extra, so it either runs no linter or installs one "
        "at a version pyproject.toml does not pin")
    typed = [line.strip() for line in executable.splitlines() if re.search(r"ruff==", line)]
    assert not typed, (
        f"{name} types a ruff version of its own: {typed}. The pin lives in pyproject.toml's "
        "`[lint]` extra and nowhere else — two pins drift at whichever site is edited alone")


@pytest.mark.parametrize("name", LINTING_WORKFLOWS)
def test_the_workflow_runs_the_one_command(name):
    executable = _executable((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert LINT_COMMAND in executable, (
        f"{name} does not run `{LINT_COMMAND}`. Both workflows run the same command so that a "
        "green on a push means what a green at the tag means; a command that dropped `--config` "
        "would lint gates/ and tests/ under ruff's defaults, and one that dropped a root would "
        "lint less than the release does")


def test_ci_lints_in_a_job_of_its_own_and_not_inside_the_matrix():
    """One reading, not four: the `suite` job is a Python matrix and ruff's verdict does not vary."""
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^  lint:$", ci, re.M), "ci.yml has no `lint` job"
    jobs = list(re.finditer(r"^  ([a-z][a-z0-9_-]*):[ \t]*$", ci, re.M))
    lint = next(m for m in jobs if m.group(1) == "lint")
    following = [m for m in jobs if m.start() > lint.start()]
    block = ci[lint.start():following[0].start() if following else len(ci)]
    assert LINT_COMMAND in _executable(block), "the `lint` job does not run the lint command"
    assert "matrix" not in _executable(block), (
        "the `lint` job carries a matrix; the linter's verdict does not depend on the interpreter "
        "and running it per leg is the same reading taken several times")


def test_the_contributor_path_names_the_lint_extra_and_the_command():
    """CONTRIBUTING.md's pre-pull-request block: the gate a release applies is runnable locally."""
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "[test,lint]" in contributing, (
        "CONTRIBUTING.md's install line no longer names the `[lint]` extra, so the documented "
        "path installs no linter and the release gate is once more unreproducible from the "
        "instructions")
    assert LINT_COMMAND in contributing, (
        "CONTRIBUTING.md does not carry the lint command, so a contributor has the linter and "
        "not the invocation — and the invocation is where `--config` matters")


def test_the_comment_filter_is_not_vacuous():
    """The refusal above must see an executable `ruff==` and must not see a quoted one."""
    assert "ruff==" not in _executable("# the old line was `pip install \"ruff==0.16.6\"`\n")
    assert "ruff==" in _executable('          python -m pip install "ruff==0.16.6"\n')
