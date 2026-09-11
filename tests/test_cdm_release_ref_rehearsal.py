"""`gates/release_ref_rehearsal.py` — the pre-push replay, and each of its refusals.

WHY EVERY CHECK IS TESTED THROUGH ITS FAILURE
---------------------------------------------
The module exists because two releases were burned by gates whose first execution was on a ref
nobody had run them on (`v2.1.0` at pip-audit, `v2.1.1` at the CodeQL gate — `Release` runs
34332384035 and 34452755466). A rehearsal that passes everything is indistinguishable from a
rehearsal that checks nothing, and the second kind is worse than none: it would be quoted in a
release report as evidence. So every check here is exercised in the direction that must FAIL, on a
mutated scratch copy of `publish.yml`, on a scratch clone with a lightweight tag, or on a recorded
API answer — never against the tree's own green state alone.

WHY THE NETWORK CHECK IS A FIXTURE AND NOT A SKIP
--------------------------------------------------
`tests/test_cdm_codeql_gate.py` is the pattern this module follows: it builds synthetic SARIF in a
`tmp_path` and calls the gate's own functions, and it makes no network call at all — so the gate's
branches are proven on every machine, including one with no credential. `check_codeql` takes its
`fetch` and `sarif` callables as arguments for exactly that reason, and the tests below hand it
recorded answers. The live query is exercised by the round that runs the rehearsal, and its output
is quoted in that round's report; it is not a thing the suite can own, because a suite that needed
a token would go green only for whoever holds one.
"""
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gates"))

import release_ref_rehearsal as rehearsal  # noqa: E402

WORKFLOW = (REPO / ".github" / "workflows" / "publish.yml").read_text()

#: A commit and two analysis ids of the shape the endpoint returns. The values are `v2.1.1`'s, so
#: the fixture is a recording of a real answer rather than an invention.
COMMIT = "4409115ba9f762868a08244b97a0a64e55643744"
IDS = [1753266107, 1753264364]


def clean_sarif(_repo, analysis_id, into):
    """A SARIF with one run, no results — what a clean analysis of a commit looks like."""
    path = into / f"{analysis_id}.sarif"
    path.write_text(json.dumps({"version": "2.1.0", "runs": [
        {"tool": {"driver": {"name": "CodeQL", "rules": []}}, "results": []}]}))
    return path


def blocking_sarif(_repo, analysis_id, into):
    """A SARIF whose one result is above `gates/codeql_gate.py`'s 7.0 floor and not excepted."""
    path = into / f"{analysis_id}.sarif"
    path.write_text(json.dumps({"version": "2.1.0", "runs": [{
        "tool": {"driver": {"name": "CodeQL", "rules": [
            {"id": "py/sql-injection", "properties": {"security-severity": "9.8"}}]}},
        "results": [{"ruleId": "py/sql-injection", "message": {"text": "synthetic"},
                     "locations": [{"physicalLocation": {
                         "artifactLocation": {"uri": "packages/cdm/synapse_cdm/nothing.py"},
                         "region": {"startLine": 1}}}]}]}]}))
    return path


def found(ids):
    def fetch(_repo, _sha):
        return list(ids), 32, 1
    return fetch


# --------------------------------------------------------------------- check 6: the coverage table

def test_the_coverage_table_covers_every_ref_use_the_tree_has():
    """The tree's own state. If this fails, a ref-dependent step landed without a rehearsal."""
    ok, detail = rehearsal.check_coverage(WORKFLOW)
    assert ok, detail
    assert "0 uncovered" in detail


def test_the_coverage_table_rejects_an_added_ref_use():
    """The check that outlives this round, exercised on the mutation it exists to catch.

    A future round adding a step that names the ref — here, an artefact path built from the tag,
    which is the very defect round PS repaired in the SBOM stage — fails the rehearsal locally
    instead of failing gate step 16 of 17 on a tag nobody can un-push.
    """
    mutated = WORKFLOW.replace(
        "      - name: The published schemas are CURRENT",
        '      - name: A step nobody rehearsed\n'
        '        run: echo "sbom/synapse_cdm-${GITHUB_REF_NAME}.json"\n\n'
        "      - name: The published schemas are CURRENT")
    ok, detail = rehearsal.check_coverage(mutated)
    assert not ok
    assert "in no entry of COVERED_USES" in detail
    assert "sbom/synapse_cdm-${GITHUB_REF_NAME}.json" in detail, (
        f"the refusal does not quote the uncovered line, so a reader cannot act on it: {detail}")


def test_a_ref_use_inside_a_comment_is_not_a_finding():
    """Round PQ's own dated comment quotes `?ref=${GITHUB_REF}` in order to explain its removal."""
    mutated = WORKFLOW.replace(
        "      - name: The published schemas are CURRENT",
        "      # a paragraph about ${GITHUB_REF_NAME} and github.ref_name and nothing else\n"
        "      - name: The published schemas are CURRENT")
    ok, _ = rehearsal.check_coverage(mutated)
    assert ok


# ------------------------------------------------------------------------------ check 1: condition 3

def test_condition_3_fails_on_a_mismatched_tag():
    ok, detail = rehearsal.check_condition_3("v9.9.9", "2.1.1", WORKFLOW)
    assert not ok
    assert "PACKAGE_VERSION is 2.1.1" in detail
    assert "gate step 7" in detail


def test_condition_3_passes_on_the_tag_that_names_the_version():
    ok, detail = rehearsal.check_condition_3("v2.1.1", "2.1.1", WORKFLOW)
    assert ok, detail


def test_condition_3_refuses_to_rehearse_a_comparison_the_workflow_no_longer_makes():
    """Reproduced, not paraphrased: if the step's spelling changes, this check stops claiming."""
    mutated = WORKFLOW.replace('[ "${tag}" != "v${version}" ]', '[ "${tag}" = "anything" ]')
    ok, detail = rehearsal.check_condition_3("v2.1.1", "2.1.1", mutated)
    assert not ok
    assert "no longer spells its comparison" in detail


# --------------------------------------------------------------------------- check 2: annotated tag

def _scratch_clone(tmp_path):
    """A clone of this repository, so a lightweight tag can be made without touching the tree."""
    clone = tmp_path / "clone"
    subprocess.run(("git", "clone", "--quiet", "--no-tags", "--depth", "1",
                    f"file://{REPO}", str(clone)), check=True, capture_output=True)
    return clone


def test_the_annotated_check_fails_on_a_lightweight_tag(tmp_path, monkeypatch):
    clone = _scratch_clone(tmp_path)
    subprocess.run(("git", "tag", "v0.0.0-lightweight"), cwd=str(clone), check=True,
                   capture_output=True)
    monkeypatch.setattr(rehearsal, "REPO", clone)
    ok, detail = rehearsal.check_annotated("v0.0.0-lightweight")
    assert not ok
    assert "lightweight tag" in detail
    assert "records nobody" in detail


def test_the_annotated_check_passes_on_an_annotated_tag(tmp_path, monkeypatch):
    clone = _scratch_clone(tmp_path)
    subprocess.run(("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "tag", "-a", "v0.0.0-annotated", "-m", "a subject"),
                   cwd=str(clone), check=True, capture_output=True)
    monkeypatch.setattr(rehearsal, "REPO", clone)
    ok, detail = rehearsal.check_annotated("v0.0.0-annotated")
    assert ok, detail
    assert "is a tag object" in detail
    assert "a subject" in detail


def test_the_annotated_check_fails_on_a_tag_object_with_no_subject(tmp_path, monkeypatch):
    """The branch between "is a tag object" and "records a person", and it had no test.

    `git tag -a -m ""` makes a real tag object with a tagger and an empty message. `git cat-file
    -t` says `tag`, so the lightweight check above passes it; the gate's reason for demanding an
    annotated tag — that a release is a statement by a person — is not satisfied by one. Round PQ
    attempt 2 found this branch by mutating the refusal on a scratch copy and watching nothing go
    red, which is what a red-then-green pass is for.
    """
    clone = _scratch_clone(tmp_path)
    subprocess.run(("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "tag", "-a", "v0.0.0-no-subject", "-m", ""),
                   cwd=str(clone), check=True, capture_output=True)
    monkeypatch.setattr(rehearsal, "REPO", clone)
    assert rehearsal.run("git", "cat-file", "-t", "v0.0.0-no-subject", cwd=clone) == "tag", (
        "the subject of this test is not a tag object, so it is testing the lightweight branch")
    ok, detail = rehearsal.check_annotated("v0.0.0-no-subject")
    assert not ok, detail
    assert "no tagger or no subject" in detail


def test_the_annotated_check_fails_on_a_tag_that_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "REPO", _scratch_clone(tmp_path))
    ok, detail = rehearsal.check_annotated("v0.0.0-absent")
    assert not ok
    assert "does not resolve at all" in detail


# ---------------------------------------------------------------------------- check 3: the CodeQL gate

def test_the_codeql_check_fails_on_a_commit_with_no_analysis():
    ok, detail = rehearsal.check_codeql(
        "owner/name", COMMIT, WORKFLOW,
        fetch=lambda _repo, _sha: ([], 32, 1), sarif=clean_sarif)
    assert not ok
    assert "has produced no analysis" in detail
    assert "32 record(s) examined" in detail, (
        f"the refusal does not say how far it looked, so `no analysis` is not falsifiable: {detail}")
    assert "branch that contains this commit" in detail


def test_the_codeql_check_passes_on_a_clean_analysis_and_runs_the_shared_gate():
    ok, detail = rehearsal.check_codeql(
        "owner/name", COMMIT, WORKFLOW, fetch=found(IDS), sarif=clean_sarif)
    assert ok, detail
    assert "0 result(s), 0 blocking" in detail, (
        f"the verdict quoted is not gates/codeql_gate.py's own last line: {detail}")


def test_the_codeql_check_fails_on_a_blocking_finding():
    """The gate half. A commit with an analysis is not the same as a commit with a clean one."""
    ok, detail = rehearsal.check_codeql(
        "owner/name", COMMIT, WORKFLOW, fetch=found(IDS), sarif=blocking_sarif)
    assert not ok
    assert "gates/codeql_gate.py over the 2 analysis/analyses" in detail


def test_the_codeql_check_fails_if_the_ref_filter_comes_back():
    mutated = WORKFLOW.replace("code-scanning/analyses?per_page=",
                               "code-scanning/analyses?ref=${GITHUB_REF}&per_page=")
    ok, detail = rehearsal.check_codeql(
        "owner/name", COMMIT, mutated, fetch=found(IDS), sarif=clean_sarif)
    assert not ok
    assert "still filters the analyses by ref" in detail
    assert "34452755466" in detail, (
        "the refusal does not name the run that is the reading for this defect")


def test_the_codeql_check_fails_if_the_commit_match_is_dropped():
    mutated = WORKFLOW.replace(rehearsal.COMMIT_SELECT, ".id")
    ok, detail = rehearsal.check_codeql(
        "owner/name", COMMIT, mutated, fetch=found(IDS), sarif=clean_sarif)
    assert not ok
    assert "does not select on the commit SHA" in detail


def test_the_codeql_check_leaves_nothing_behind(tmp_path):
    """The SARIFs go outside the repository and are removed. A gate that littered would move the
    untouchables it exists to protect — `git ls-files '*.sarif'` is 0 and stays 0."""
    written: list[pathlib.Path] = []

    def record(repo, analysis_id, into):
        path = clean_sarif(repo, analysis_id, into)
        written.append(path)
        return path

    ok, detail = rehearsal.check_codeql(
        "owner/name", COMMIT, WORKFLOW, fetch=found(IDS), sarif=record)
    assert ok, detail
    assert written, "the check fetched no SARIF at all"
    for path in written:
        assert REPO not in path.parents, f"{path} is inside the repository"
        assert not path.exists(), f"{path} survived the check"


# ------------------------------------------------------------------------- check 4: the version sites

def test_the_version_sites_are_found_by_grep_and_covered_by_one_equality():
    ok, detail = rehearsal.check_version_sites("v2.1.1", "2.1.1", WORKFLOW)
    assert ok, detail
    assert "site(s) derive" in detail


def test_the_version_sites_fail_when_the_tag_does_not_name_the_version():
    ok, detail = rehearsal.check_version_sites("v2.1.2", "2.1.1", WORKFLOW)
    assert not ok
    assert "'2.1.2'" in detail and "'2.1.1'" in detail


def test_the_version_site_check_refuses_a_file_with_no_such_site():
    mutated = WORKFLOW.replace('version="${GITHUB_REF_NAME#v}"', 'version="2.1.1"')
    ok, detail = rehearsal.check_version_sites("v2.1.1", "2.1.1", mutated)
    assert not ok
    assert "no step derives a version from the tag name" in detail


# ------------------------------------------------------------- checks 0 and 5: the guard and the name

def test_the_tag_guard_fails_on_a_tag_that_is_not_a_v_tag():
    ok, detail = rehearsal.check_tag_guard("2.1.1")
    assert not ok
    assert "SKIPPED" in detail, (
        "the refusal does not say what a non-`v` tag actually does, which is the dangerous part: "
        f"the irreversible jobs are skipped and the run reports success: {detail}")


def test_the_release_name_check_fails_when_the_name_is_taken():
    ok, detail = rehearsal.check_release_name_free(
        "owner/name", "v2.1.1", exists=lambda _repo, _tag: True)
    assert not ok
    assert "after the PyPI upload had already happened" in detail


def test_the_release_name_check_passes_when_it_is_free():
    ok, detail = rehearsal.check_release_name_free(
        "owner/name", "v2.1.1", exists=lambda _repo, _tag: False)
    assert ok, detail


# ------------------------------------------------------------------------------- the module as a whole

def test_the_rehearsal_stops_at_the_first_failure():
    """CI stops at the first red step, so a rehearsal that reported all seven would be lying about
    what the release will do — and the later checks read state the earlier ones prove."""
    checks = rehearsal.rehearse("2.1.1", COMMIT, "owner/name",
                                fetch=found(IDS), sarif=clean_sarif,
                                exists=lambda _repo, _tag: False)
    assert [c["check"] for c in checks] == ["tag guard"]
    assert checks[0]["verdict"] == "FAIL"


def test_every_check_in_the_plan_is_reachable_and_named_once():
    checks = rehearsal.rehearse("v2.1.1", COMMIT, "owner/name",
                                fetch=found(IDS), sarif=clean_sarif,
                                exists=lambda _repo, _tag: False)
    names = [c["check"] for c in checks]
    assert names == ["tag guard", "condition 3", "annotated tag", "codeql gate",
                     "version sites", "release name free", "ref use coverage"], names
    assert all(c["verdict"] == "PASS" for c in checks), checks


def test_every_covered_use_entry_carries_a_reason():
    for literal, reason in rehearsal.COVERED_USES:
        assert literal.strip(), "an empty literal covers every line and therefore nothing"
        assert len(reason.split()) >= 8, (
            f"{literal!r}'s entry is not a reason, it is a label: {reason!r}. The table is the "
            "module's argument that each ref use is rehearsed, and a label argues nothing")


def test_the_module_is_runnable_and_its_help_names_the_tag_and_the_commit():
    proc = subprocess.run((sys.executable, str(REPO / "gates" / "release_ref_rehearsal.py"),
                           "--help"), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    for flag in ("--tag", "--commit", "--json"):
        assert flag in proc.stdout, f"{flag} is not in the module's --help"


def test_the_module_writes_nothing_into_the_tree():
    """Every write this module makes is into the temporary directory it then removes.

    `test_the_codeql_check_leaves_nothing_behind` proves the behaviour on the one code path that
    writes. This is the source-level companion, and it exists because a later round adding a
    `--report` flag that dropped a file next to the gate would break the untouchable
    (`git ls-files '*.sarif'` is 0) without failing any behavioural test.
    """
    source = (REPO / "gates" / "release_ref_rehearsal.py").read_text()
    assert "mkdtemp" in source, "the SARIFs are not fetched into a temporary directory"
    assert "shutil.rmtree" in source, "the temporary directory is never removed"
    writes = [line.strip() for line in source.splitlines() if ".write_text(" in line]
    assert writes, "nothing in this module writes, so this test is checking the wrong file"
    for line in writes:
        assert line.startswith("path.write_text("), (
            f"a write in this module is not `path.write_text(...)` into the temporary directory, "
            f"so it cannot be read off the source that the tree is untouched: {line!r}")


# --------------------------------------- M's standing rule of 2026-09-11: the delete refuses the tree

def test_the_scratch_directory_refuses_to_be_the_repository(monkeypatch):
    """`scratch_outside_repo` reads the path before anything can be pointed at it.

    This is the refusal round PQ's first attempt did not have. `tempfile.mkdtemp` is made to hand
    back the repository root — the state a mutated `into = REPO` produced on 2026-09-10 — and the
    constructor must refuse it. Nothing here deletes: `scratch_outside_repo` only compares.
    """
    monkeypatch.setattr(rehearsal.tempfile, "mkdtemp", lambda prefix: str(REPO))
    with pytest.raises(rehearsal.Refused, match="refusing .* as this module's scratch directory"):
        rehearsal.scratch_outside_repo("release-ref-rehearsal-")


def test_the_scratch_directory_refuses_a_parent_of_the_repository(monkeypatch):
    monkeypatch.setattr(rehearsal.tempfile, "mkdtemp", lambda prefix: str(REPO.parent))
    with pytest.raises(rehearsal.Refused, match="parent of it"):
        rehearsal.scratch_outside_repo("release-ref-rehearsal-")


def test_the_scratch_directory_is_real_outside_the_repository_and_removable():
    path = rehearsal.scratch_outside_repo("release-ref-rehearsal-test-")
    try:
        assert path.is_dir(), f"{path} was not created"
        assert REPO not in path.parents and path != REPO, f"{path} is inside the repository"
    finally:
        rehearsal.rmtree_outside_repo(path)
    assert not path.exists(), f"{path} survived rmtree_outside_repo"


def test_the_delete_refuses_a_path_inside_the_repository():
    """The refusal is read AGAIN at the moment of the delete, not only when the path was made.

    The subject is a path that does NOT exist, deliberately. `shutil.rmtree(..., ignore_errors=True)`
    over a missing directory is a no-op, so this test cannot damage the tree even if the guard it
    is testing were removed — M's rule of 2026-09-11: a destructive behaviour is proven by its own
    assertion, never by pointing the delete at something real and watching.
    """
    victim = REPO / "no-such-directory-pq-guard-subject"
    assert not victim.exists(), "the subject of this test must not exist"
    with pytest.raises(rehearsal.Refused, match="refusing to remove"):
        rehearsal.rmtree_outside_repo(victim)


def test_the_delete_refuses_the_repository_itself_by_the_same_reading(tmp_path, monkeypatch):
    """The `path == REPO` branch, proven on a SCRATCH repository root rather than the real one.

    `REPO` is rebound to a directory under `tmp_path`, so the equality branch is exercised against
    a tree this test made and may lose. The real repository is never the argument.
    """
    scratch_repo = tmp_path / "scratch-repo"
    (scratch_repo / "keep").mkdir(parents=True)
    monkeypatch.setattr(rehearsal, "REPO", scratch_repo)
    with pytest.raises(rehearsal.Refused, match="refusing to remove"):
        rehearsal.rmtree_outside_repo(scratch_repo)
    assert (scratch_repo / "keep").is_dir(), "the refusal did not stop the delete"


def test_the_module_guards_its_delete_in_the_code_and_not_only_in_a_test():
    """M's standing rule names the source, not the suite: read it off the file, by its syntax.

    The module is PARSED rather than grepped, because this file's own prose quotes
    `shutil.rmtree(...)` in order to explain why it is guarded, and a check that counted prose as
    code would be satisfiable by a comment. Every call to `shutil.rmtree` and to `tempfile.mkdtemp`
    must live inside the two guarded helpers, and `check_codeql` — the code path that destroyed
    the working tree on 2026-09-10 — must reach them only through those helpers.
    """
    import ast

    source = (REPO / "gates" / "release_ref_rehearsal.py").read_text()
    tree = ast.parse(source)
    callers: dict[str, list[str]] = {"shutil.rmtree": [], "tempfile.mkdtemp": []}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = ast.unparse(inner.func)
            if name in callers:
                callers[name].append(node.name)

    assert callers["shutil.rmtree"] == ["rmtree_outside_repo"], (
        "every delete in this module must be the one inside `rmtree_outside_repo`, which refuses a "
        f"target inside the repository before it runs; found calls in {callers['shutil.rmtree']}")
    assert callers["tempfile.mkdtemp"] == ["scratch_outside_repo"], (
        "every temporary directory must be made by `scratch_outside_repo`, which refuses a path "
        f"inside the repository; found calls in {callers['tempfile.mkdtemp']}")

    body = source[source.index("def check_codeql("):source.index("def check_version_sites(")]
    assert "scratch_outside_repo(" in body and "rmtree_outside_repo(" in body, (
        "check_codeql no longer goes through the guarded helpers")
