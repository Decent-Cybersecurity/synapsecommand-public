"""Replay every ref-dependent release step against a tag BEFORE that tag is pushed.

WHY THIS FILE EXISTS, AND WHAT IT COST TO LEARN
-----------------------------------------------
A tag is the one thing this repository cannot un-spend. `MIGRATIONS.md` and `RUNNER.md` both make a
pushed release tag permanent — "preserve the state for reviewed recovery rather than rewriting
history", M, 2026-09-10 — so every release gate that can only be evaluated once the tag exists is a
gate whose first execution is also its last chance. Two releases were burned that way in two days:

* **v2.1.0**, tagged on `b69a267` and pushed 2026-09-09. `Release` run 34332384035 died in `gate`
  at step 15, the pip-audit stage, because the audit included `synapse-cdm` itself and the version
  under release is by definition not yet on the index. Round PP repaired it.
* **v2.1.1**, tagged on `4409115` and pushed 2026-09-10T07:59:24Z. `Release` run 34452755466 got
  through step 15 — PP's repair worked — and died at step 16 of 17, the CodeQL gate, which asked
  `code-scanning/analyses?ref=${GITHUB_REF}`. On a tag push that ref is `refs/tags/v2.1.1`;
  `codeql.yml` triggers only on `push`/`pull_request` to `main` and `soif/**` and a weekly cron, so
  no ref of the form `refs/tags/*` can ever carry an analysis. The commit had two clean analyses on
  `refs/heads/main` and the gate excluded them by ref. Round PQ repaired that, and wrote this.

Both defects share one shape: **a step whose behaviour depends on the ref, first executed on a ref
nobody had ever run it on.** Neither was findable by the suite (the suite reads the workflow's
text, not the API's answer to it), by a `workflow_dispatch` run (its ref is a branch, which is the
ref that works), or by a re-run (the input that decides is `GITHUB_REF`, which a re-run does not
change). The only thing that would have caught either is asking the real API the question the real
release will ask, with `GITHUB_REF` set to the tag, while the tag is still local.

That is this module. It is not a workflow step: a workflow step runs after the push, and after the
push the verdict is a post-mortem. `MIGRATIONS.md`'s sequence names it as a MANDATORY act between
"tag" and "push", and a red rehearsal is a STOP with the tag still local and unspent.

WHAT IT IS NOT
--------------
It is not a rehearsal TAG and not a rehearsal MODE, both of which M declined on 2026-09-10 and
which are recorded here so no later round reopens them. A `v…rc…` tag does fire `publish.yml`
(`on: push: tags: ['v*']`) but dies nine steps early at Condition 3, because its name does not
name the tree's `PACKAGE_VERSION`; and `publish`/`release`/`witness` are guarded only by
`startsWith(github.ref, 'refs/tags/v')`, so a rehearsal tag satisfying Condition 3 would perform a
real PyPI upload. A `v*-rehearsal` conditional inside `publish.yml` is the "rule with one permitted
exception" that file's own header argues against.

It is also not a second copy of the gates. The CodeQL check hands the SARIFs it fetches to
`gates/codeql_gate.py` — the same module `codeql.yml` and `publish.yml` run — so this module cannot
disagree with the release about what blocks. What it reproduces is the *selection*: which analyses
the release will look at, which is the part that was wrong.

THE LAST CHECK IS THE POINT
---------------------------
The checks before it replay the ref-dependent behaviours `publish.yml` has today: the tag guard on
everything irreversible, Condition 3, the annotated-tag check, the CodeQL gate, the five
tag-derived versions, and the Release name the tag will take. The LAST one is what makes the module
survive the next round: it greps `publish.yml` for every use of `GITHUB_REF`,
`GITHUB_REF_NAME`, `github.ref` and `github.ref_name`, and requires each one to be named in
`COVERED_USES` below. **A use no entry covers is a FAILURE**, so a future round that adds a
ref-dependent step without deciding how it is rehearsed fails here — locally, before a tag — rather
than on a pushed tag at step 16 of 17. Line numbers are DERIVED by that grep and never written
down; three of the five sites moved between v2.1.0 and v2.1.1.

    python gates/release_ref_rehearsal.py                      # the tag `git describe` gives, HEAD
    python gates/release_ref_rehearsal.py --tag v2.1.1 --commit 4409115b…
    python gates/release_ref_rehearsal.py --json               # each check with its verdict

Exit 0 iff every check passes; 1 on the first that would fail in CI; 2 on a refusal (a missing
file, an unusable API answer) — the same three-way exit `gates/codeql_gate.py` uses, so a broken
rehearsal reads differently from a red one.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "publish.yml"
CODEQL_GATE = REPO / "gates" / "codeql_gate.py"

#: The endpoint the CodeQL gate reads, and the shape the repaired query has: no `ref=` parameter.
ANALYSES_PATH = "code-scanning/analyses?"

#: The selection that makes the query a statement about the release COMMIT. Round PQ's repair keeps
#: it and drops the ref filter; this module fails if the workflow it is rehearsing has neither.
COMMIT_SELECT = 'select(.commit_sha == \\"${GITHUB_SHA}\\")'

#: The bound on the paging, mirrored from the workflow so the rehearsal examines what CI examines.
MAX_PAGES = 5
PER_PAGE = 100

#: The tokens by which `publish.yml` can name the ref it was triggered by.
REF_TOKENS = ("GITHUB_REF_NAME", "GITHUB_REF", "github.ref_name", "github.ref")

#: **Check 5's table.** Every executable line of `publish.yml` that names the ref must be matched
#: by one of these literals, and each literal says in one line why the rehearsal's other checks
#: cover it. An unmatched line is a FAILURE: it is a ref-dependent behaviour nobody decided how to
#: rehearse, which is exactly the state v2.1.0 and v2.1.1 were released in.
COVERED_USES: tuple[tuple[str, str], ...] = (
    ("group: publish-${{ github.ref }}",
     "not an assertion: a concurrency key. Any distinct string serialises the run, so there is "
     "nothing here that can fail; the module PRINTS the group the run would take instead"),
    ("if: startsWith(github.ref, 'refs/tags/v')",
     "the tag guard on every step and job that is irreversible. Replayed by check 0: the tag name "
     "starts with `v`, or none of these steps runs at all"),
    ('tag="${GITHUB_REF_NAME}"',
     "Condition 3's left-hand side — replayed verbatim by check 1"),
    ('git cat-file -t "${GITHUB_REF_NAME}"',
     "the annotated-tag check — replayed verbatim by check 2"),
    ('echo "${GITHUB_REF_NAME} is a ${kind}"',
     "the annotated-tag check's own record of what it read — check 2 prints the same word"),
    ("${GITHUB_REF_NAME} is a lightweight tag",
     "the annotated-tag check's refusal message; check 2 is the condition it fires on"),
    ('git for-each-ref "refs/tags/${GITHUB_REF_NAME}"',
     "prints the tagger and subject of an annotated tag; check 2 runs it and requires both "
     "non-empty, because a tag object with no tagger records nobody"),
    ('echo "trigger ref: ${GITHUB_REF}',
     "the CodeQL gate PRINTS the trigger ref for the record and no longer filters on it — round "
     "PQ's repair, and check 3 is the query that replaced the filter"),
    ('version="${GITHUB_REF_NAME#v}"',
     "every version derived from the tag name. Replayed by check 4: `tag[1:]` == PACKAGE_VERSION, "
     "which makes all of them equal to the version the tree declares"),
    ('gh release create "${GITHUB_REF_NAME}"',
     "the ref as the NAME of the GitHub Release. Correct iff the tag exists, is annotated and "
     "names this tree's version — checks 1, 2 and 4 — and check 5 reads that no release of that "
     "name exists yet"),
    ('releases/tags/${GITHUB_REF_NAME}"',
     "the witness job reads back the Release it just created, by tag name; same three checks"),
    ('--tag "${GITHUB_REF_NAME}"',
     "the tag name handed to gates/witness_verify.py; same three checks"),
    ('--tag-object "$(git rev-parse "${GITHUB_REF_NAME}")"',
     "the tag OBJECT handed to gates/witness_verify.py. Check 2 runs the same `git rev-parse` and "
     "requires it to resolve to a tag object, not to the commit"),
    ('gh release upload "${GITHUB_REF_NAME}"',
     "the witness JSON uploaded to the Release named by the tag; same three checks"),
)


class Refused(Exception):
    """The rehearsal cannot be performed — distinct from a check that performed and failed."""


def scratch_outside_repo(prefix: str) -> pathlib.Path:
    """A temporary directory this module may DELETE, refused unless it lies outside the tree.

    M's standing rule of 2026-09-11, and it is the one rule in this file the repository paid for.
    On 2026-09-10 a red-then-green mutation bound `check_codeql`'s temporary directory to `REPO`,
    and the `finally: shutil.rmtree(...)` below then removed the working tree, `.git`, `.venv` and
    every untracked file beside them (`rounds/reports/PQ.attempt1.md`). The refusal lives HERE, in
    the code that deletes, and not only in a test: a test says what this module does today, and
    this says what it cannot be made to do tomorrow — including by a future mutation, a patched
    `tempfile.tempdir`, or a `TMPDIR` pointing inside a checkout.
    """
    path = pathlib.Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    if path == REPO or REPO in path.parents or path in REPO.parents:
        raise Refused(
            f"refusing {path} as this module's scratch directory: it is the repository at {REPO}, "
            "inside it, or a parent of it. Nothing in this file that deletes is ever pointed at a "
            "path the tree lives under")
    return path


def rmtree_outside_repo(path: pathlib.Path) -> None:
    """`shutil.rmtree`, with the same refusal read a second time at the moment of the delete.

    `scratch_outside_repo` already refused an unsafe path when it was made. This reads it again
    when it is destroyed, because the two moments are separated by every line of `check_codeql`
    and the rule is about the delete, not about the constructor.
    """
    resolved = pathlib.Path(path).resolve()
    if resolved == REPO or REPO in resolved.parents or resolved in REPO.parents:
        raise Refused(
            f"refusing to remove {resolved}: it is the repository at {REPO}, inside it, or a "
            "parent of it. This module deletes only the scratch directory it made itself")
    shutil.rmtree(resolved, ignore_errors=True)


def run(*argv: str, cwd: pathlib.Path | None = None) -> str:
    proc = subprocess.run(argv, cwd=str(cwd or REPO), capture_output=True, text=True)
    if proc.returncode != 0:
        raise Refused(f"`{' '.join(argv)}` exited {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def executable_lines(text: str) -> list[tuple[int, str]]:
    """`(1-based line number, line)` for every line that is not a comment.

    Comments are dropped because this file's comments quote the very strings the checks forbid —
    round PQ's dated paragraph names `code-scanning/analyses?ref=${GITHUB_REF}` in order to explain
    why it is gone. A sweep that read prose about a rule as a breach of it is a mistake
    `tests/test_cdm_trusted_publishing.py::_executable` already records.
    """
    return [(n, line) for n, line in enumerate(text.splitlines(), 1)
            if not line.lstrip().startswith("#")]


def package_version() -> str:
    """`PACKAGE_VERSION` read the way `publish.yml`'s Condition 3 reads it, in a subprocess.

    The workflow runs `python -c 'import sys; sys.path.insert(0, "packages/cdm"); …'`. Importing
    the module into this process instead would read whatever `sys.path` this process happens to
    have, which on a machine with `synapse-cdm` installed is not necessarily the tree.
    """
    return run(sys.executable, "-c",
               'import sys; sys.path.insert(0, "packages/cdm"); '
               'from synapse_cdm.version import PACKAGE_VERSION; print(PACKAGE_VERSION)')


def codeql_step(workflow: str) -> str:
    """The gate job's CodeQL step, so check 3 rehearses the query the tree carries."""
    marker = "- name: Security gate — CodeQL"
    if marker not in workflow:
        raise Refused(f"{WORKFLOW} has no step starting `{marker}`; the CodeQL gate this module "
                      "rehearses is not in the file")
    block = workflow[workflow.index(marker):]
    rest = block[1:]
    nxt = rest.find("\n      - name: ")
    return block[:1 + nxt] if nxt != -1 else block


def fetch_analyses(repo: str, sha: str) -> tuple[list[int], int, int]:
    """The repaired query, run against the real API: `(matching ids, examined, pages)`.

    The URL and the selection are the workflow's, with `GITHUB_SHA` bound to the commit under
    rehearsal and no `ref` parameter — that absence IS the repair, and check 3 asserts the
    workflow's own line has the same shape before trusting this to represent it.
    """
    ids: list[int] = []
    examined = 0
    page = 0
    while page < MAX_PAGES:
        page += 1
        raw = run("gh", "api",
                  f"repos/{repo}/code-scanning/analyses?per_page={PER_PAGE}&page={page}",
                  "--jq", f'{{examined: length, matched: [.[] | select(.commit_sha == "{sha}") | .id]}}')
        try:
            answer = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise Refused(f"the analyses endpoint answered something that is not JSON: {exc}")
        examined += int(answer["examined"])
        ids += [int(i) for i in answer["matched"]]
        if int(answer["examined"]) < PER_PAGE:
            break
    return ids, examined, page


def fetch_sarif(repo: str, analysis_id: int, into: pathlib.Path) -> pathlib.Path:
    path = into / f"{analysis_id}.sarif"
    proc = subprocess.run(
        ("gh", "api", "-H", "Accept: application/sarif+json",
         f"repos/{repo}/code-scanning/analyses/{analysis_id}"),
        cwd=str(REPO), capture_output=True, text=True)
    if proc.returncode != 0:
        raise Refused(f"SARIF {analysis_id} could not be fetched: {proc.stderr.strip()}")
    path.write_text(proc.stdout)
    return path


def release_exists(repo: str, tag: str) -> bool:
    """Whether a GitHub Release already carries this tag's name. Read-only; 404 is the good answer."""
    proc = subprocess.run(("gh", "api", f"repos/{repo}/releases/tags/{tag}"),
                          cwd=str(REPO), capture_output=True, text=True)
    return proc.returncode == 0


def default_repo() -> str:
    """`owner/name` from the `origin` remote, because the workflow's `GITHUB_REPOSITORY` is that."""
    url = run("git", "config", "--get", "remote.origin.url")
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    if match is None:
        raise Refused(f"origin's URL does not name an owner/repository: {url!r}")
    return match.group(1)


# ------------------------------------------------------------------ the checks, in the order CI hits them

def check_tag_guard(tag: str) -> tuple[bool, str]:
    """Check 0 — `startsWith(github.ref, 'refs/tags/v')`, the guard on everything irreversible."""
    ok = tag.startswith("v")
    return ok, (f"{tag} satisfies startsWith(github.ref, 'refs/tags/v')" if ok else
                f"{tag} does not start with `v`, so every tag-guarded step and both irreversible "
                "jobs would be SKIPPED and the release would report success having published "
                "nothing")


def check_condition_3(tag: str, version: str, workflow: str) -> tuple[bool, str]:
    """Check 1 — Condition 3, the comparison reproduced from the step rather than paraphrased."""
    spelling = '[ "${tag}" != "v${version}" ]'
    if spelling not in workflow:
        return False, (f"Condition 3 no longer spells its comparison {spelling!r}, so this check "
                       "is rehearsing a condition the workflow does not have any more")
    ok = tag == f"v{version}"
    return ok, (f"tag={tag}  PACKAGE_VERSION={version}" if ok else
                f"{tag} points at a tree whose PACKAGE_VERSION is {version}. Condition 3 fails and "
                "the release stops at gate step 7")


def check_annotated(tag: str) -> tuple[bool, str]:
    """Check 2 — the tag object, its tagger and its subject, exactly as gate steps 8 and 9 read them."""
    try:
        kind = run("git", "cat-file", "-t", tag)
    except Refused as exc:
        return False, f"{tag} does not resolve at all: {exc}"
    if kind != "tag":
        return False, (f"{tag} is a lightweight tag (git calls it a {kind}). The gate refuses it: a "
                       "release is a statement by a person, and a lightweight tag records nobody")
    fields = run("git", "for-each-ref", f"refs/tags/{tag}",
                 "--format=tagger: %(taggername) %(taggerdate:iso8601)%0asubject: %(contents:subject)")
    tagger, _, subject = fields.partition("\n")
    if tagger.strip() in ("tagger:", "tagger: ") or not subject.replace("subject:", "").strip():
        return False, f"{tag} is a tag object with no tagger or no subject: {fields!r}"
    obj = run("git", "rev-parse", tag)
    obj_kind = run("git", "cat-file", "-t", obj)
    if obj_kind != "tag":
        return False, (f"`git rev-parse {tag}` resolves to a {obj_kind} ({obj}), not to a tag "
                       "object, so the witness record's --tag-object would name the wrong thing")
    return True, f"{tag} is a tag object {obj[:8]}; {tagger}; {subject}"


def check_codeql(repo: str, commit: str, workflow: str,
                 fetch=fetch_analyses, sarif=fetch_sarif) -> tuple[bool, str]:
    """Check 3 — the repaired query against the real API, then the shared gate over the SARIFs.

    Two halves, and both are needed. The query half is the one that refused v2.1.1: it asserts the
    workflow's line has the repaired shape and then asks the same question of the same endpoint.
    The gate half runs `gates/codeql_gate.py`, which is the module CI runs, over the very SARIFs CI
    would fetch — so a commit whose analysis is clean today and blocking tomorrow is caught here.

    The SARIFs go to a temporary directory OUTSIDE the repository and are removed: a gate that left
    files in the tree would move the untouchables it is meant to protect. The directory is made by
    `scratch_outside_repo` and removed by `rmtree_outside_repo`, both of which REFUSE a path
    inside `REPO` in the code itself — M's standing rule of 2026-09-11.
    """
    step = codeql_step(workflow)
    queries = [line for _, line in executable_lines(step) if ANALYSES_PATH in line]
    if not queries:
        return False, f"the CodeQL step does not query {ANALYSES_PATH!r} any more"
    for line in queries:
        if "ref=" in line:
            return False, (f"the CodeQL step still filters the analyses by ref: {line.strip()!r}. "
                           "On a tag push that ref is refs/tags/<tag> and codeql.yml never runs on "
                           "one, which is how run 34452755466 refused v2.1.1")
    if COMMIT_SELECT not in step:
        return False, (f"the CodeQL step does not select on the commit SHA ({COMMIT_SELECT!r}); a "
                       "query with neither filter is not a statement about the release commit")
    ids, examined, pages = fetch(repo, commit)
    if not ids:
        return False, (f"CodeQL has produced no analysis of {commit}: {examined} record(s) examined "
                       f"over {pages} page(s), bound {MAX_PAGES} x {PER_PAGE}. Let codeql.yml "
                       "finish on a branch that contains this commit before the tag is pushed")
    into = scratch_outside_repo("release-ref-rehearsal-")
    try:
        paths = [sarif(repo, i, into) for i in ids]
        proc = subprocess.run((sys.executable, str(CODEQL_GATE), *[str(p) for p in paths]),
                              cwd=str(REPO), capture_output=True, text=True)
        verdict = (proc.stdout + proc.stderr).strip().splitlines()
        last = verdict[-1] if verdict else "(no output)"
        if proc.returncode != 0:
            return False, (f"gates/codeql_gate.py over the {len(ids)} analysis/analyses of {commit} "
                           f"exited {proc.returncode}: {last}")
        return True, (f"analyses on {commit}: {len(ids)} ({', '.join(str(i) for i in ids)}); "
                      f"examined {examined} record(s) over {pages} page(s); codeql_gate: {last}")
    finally:
        rmtree_outside_repo(into)


def check_version_sites(tag: str, version: str, workflow: str) -> tuple[bool, str]:
    """Check 4 — every `${GITHUB_REF_NAME#v}` in the file, found by grep and covered by one equality.

    The five sites at this reading are four jobs' worth of `version=` assignments, and they moved
    between v2.1.0 and v2.1.1. Their line numbers are derived here and deliberately not recorded
    anywhere: a written-down line number is a figure that goes stale in the silent direction.
    """
    sites = [n for n, line in executable_lines(workflow) if 'version="${GITHUB_REF_NAME#v}"' in line]
    if not sites:
        return False, ("no step derives a version from the tag name any more, so this check is "
                       "rehearsing a behaviour the file does not have")
    ok = tag[1:] == version
    return ok, (f"{len(sites)} site(s) derive ${{GITHUB_REF_NAME#v}} (lines {sites}); "
                f"{tag}[1:] == {version}" if ok else
                f"{len(sites)} site(s) at lines {sites} would derive {tag[1:]!r} from the tag while "
                f"the tree declares {version!r}: every artefact name, release title and witness "
                "record in the release would carry a version the package does not have")


def check_release_name_free(repo: str, tag: str, exists=release_exists) -> tuple[bool, str]:
    """Check 5 — the Release the tag will name does not exist yet. Read-only, and it has bitten.

    `gh release create "${GITHUB_REF_NAME}"` fails on a name already taken, in the `release` job,
    which runs AFTER the PyPI upload — the one point in the pipeline where a failure leaves a
    published version with no Release.
    """
    taken = exists(repo, tag)
    return (not taken), (f"no GitHub Release is named {tag} yet" if not taken else
                         f"a GitHub Release named {tag} already exists, so `gh release create` "
                         "would fail after the PyPI upload had already happened")


def check_coverage(workflow: str) -> tuple[bool, str]:
    """Check 6 — every ref use in the file is in `COVERED_USES`. The check that outlives this round."""
    uncovered: list[tuple[int, str]] = []
    covered = 0
    for n, line in executable_lines(workflow):
        if not any(token in line for token in REF_TOKENS):
            continue
        if any(literal in line for literal in (entry[0] for entry in COVERED_USES)):
            covered += 1
        else:
            uncovered.append((n, line.strip()))
    if uncovered:
        listing = "; ".join(f"{n}: {line!r}" for n, line in uncovered)
        return False, (f"{len(uncovered)} ref-dependent use(s) of publish.yml are in no entry of "
                       f"COVERED_USES — {listing}. Each is a behaviour that depends on the ref and "
                       "that nothing rehearses before the tag is pushed, which is the state v2.1.0 "
                       "and v2.1.1 were released in. Add the use to COVERED_USES with the check "
                       "that replays it, or add the check")
    return True, (f"{covered} ref use(s) over {len(COVERED_USES)} covered-use entries, "
                  "0 uncovered")


def rehearse(tag: str, commit: str, repo: str, *,
             fetch=fetch_analyses, sarif=fetch_sarif,
             exists=release_exists) -> list[dict]:
    """Every check, in the order CI hits the behaviour, stopping at the first failure."""
    workflow = WORKFLOW.read_text()
    version = package_version()
    plan = (
        ("tag guard", lambda: check_tag_guard(tag)),
        ("condition 3", lambda: check_condition_3(tag, version, workflow)),
        ("annotated tag", lambda: check_annotated(tag)),
        ("codeql gate", lambda: check_codeql(repo, commit, workflow, fetch=fetch, sarif=sarif)),
        ("version sites", lambda: check_version_sites(tag, version, workflow)),
        ("release name free", lambda: check_release_name_free(repo, tag, exists=exists)),
        ("ref use coverage", lambda: check_coverage(workflow)),
    )
    out: list[dict] = []
    for name, thunk in plan:
        ok, detail = thunk()
        out.append({"check": name, "verdict": "PASS" if ok else "FAIL", "detail": detail})
        if not ok:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", default=None,
                    help="the tag about to be pushed (default: `git describe --exact-match HEAD`)")
    ap.add_argument("--commit", default=None,
                    help="the commit the tag points at (default: HEAD)")
    ap.add_argument("--repo", default=None, metavar="OWNER/NAME",
                    help="the repository to query (default: the `origin` remote's)")
    ap.add_argument("--json", action="store_true", help="print each check with its verdict as JSON")
    args = ap.parse_args(argv)

    try:
        tag = args.tag or run("git", "describe", "--exact-match", "--tags", "HEAD")
        commit = args.commit or run("git", "rev-parse", "HEAD")
        if args.commit:
            commit = run("git", "rev-parse", commit)
        repo = args.repo or default_repo()
        checks = rehearse(tag, commit, repo)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    failed = [c for c in checks if c["verdict"] == "FAIL"]
    if args.json:
        print(json.dumps({"tag": tag, "commit": commit, "repository": repo,
                          "concurrency_group": f"publish-refs/tags/{tag}",
                          "checks": checks,
                          "failed": len(failed)}, indent=2))
    else:
        print(f"tag {tag}  commit {commit}  repository {repo}")
        print(f"concurrency group the run would take: publish-refs/tags/{tag}")
        for check in checks:
            print(f"{check['verdict']:4}  {check['check']:18}  {check['detail']}")
        print(f"{len(checks)} check(s) run, {len(failed)} failed"
              + ("" if not failed else "  — the tag is still local; do NOT push it"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
