"""The installed package is the tested package.

WHY THIS GATE EXISTS
--------------------
`pytest.ini` puts `packages/cdm` on `sys.path`, deliberately: the suite's job is to judge the
code in this working tree, and a stale wheel silently passing for it is a green run that means
nothing. The cost of that choice is that **nothing in the suite ever exercises the artefact a
partner receives.** Everything it proves, it proves about a source tree with the repository
around it.

That gap is not theoretical. It hid three defects at once, and each of them was invisible from
inside a checkout:

* the built wheel was missing **72 of 692 files** — every raw ASTERIX data block for CAT048 and
  CAT034 — because `package-data` enumerated file extensions and two adapters had shipped since
  the list was last extended. The harness ran green against that wheel: the `.parsed.json` twins
  were present, so it was judging two adapters against half their evidence;
* the wheel carried `License-Expression: Apache-2.0` and **not one byte of licence text**, NOTICE
  included — and NOTICE is the file Apache-2.0 section 4(d) makes a condition of redistribution;
* `python -m synapse_cdm.harness` **could not be run at all** by anyone who had installed the
  package. `--fixtures` was required, and every document in the repository filled it in with
  `packages/cdm/synapse_cdm/fixtures/<name>` — a path that exists in a clone and nowhere else.
  `synapse_cdm/README.md` printed it one line below `pip install synapse_cdm`.

WHAT IT DOES
------------
Builds the distribution with `python -m build`, installs the WHEEL into a venv that has no part
of this repository on its path, and then runs everything from a working directory outside the
repository. Every check below is a property of the installed artefact:

    closure    every test module is decided: it judges the package, or it judges the repository
    manifest   the wheel's file set equals what git tracks under the package, both directions
    licences   LICENSE and NOTICE are in .dist-info/licenses/, byte-identical to the originals
    metadata   importlib.metadata reports the distribution and PACKAGE_VERSION
    import     synapse_cdm imports, from site-packages and not from the tree
    resources  every shipped adapter's fixtures resolve through importlib.resources
    schemas    the published schemas can be regenerated and re-checked from anywhere
    harness    every adapter the tree registers replays green with no --fixtures argument
               at all — the roster derived, never a count typed here
    scripts    the cdm-harness and cdm-schemas console entry points work
    prose      no shipped file hands the reader a repo-relative path
    slice      the package-only half of the suite passes against the INSTALLED package

Run it:

    python gates/wheel_install.py                      # the gate
    python gates/wheel_install.py --mutation-check     # and the proof that it can fail

THE MUTATION, WHICH IS NOT OPTIONAL
-----------------------------------
A gate nobody has seen fail is a gate nobody has seen. `--mutation-check` rebuilds the
distribution with `[tool.setuptools.package-data]` emptied — a wheel with the code and none of
the fixtures, which is precisely the defect above in its worst form — installs it, and requires
this gate to REFUSE it. If the mutated wheel passes, the gate is decoration and the run exits
non-zero saying so.

It needs a network for `pip` and it is therefore a protocol act rather than a suite member, the
same standing as the pin sweep. The half of it that IS decidable offline lives in
`tests/test_cdm_packaging.py` and runs on every `pytest`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[1]
DIST_SRC = REPO / "packages" / "cdm"

#: The suite modules that judge the PACKAGE rather than the repository around it. These run
#: TWICE — once against the source tree under `pytest`, once here against site-packages.
#:
#: The boundary is the point. A module that reaches for the repository root, for `/schemas`, for
#: `docs/` or for git history is asserting something about a CHECKOUT; running it against an
#: install would either fail for the wrong reason or quietly assert nothing. Those are named in
#: `REPO_BOUND_TESTS` with the same weight, because the two lists are checked for closure against
#: the directory below: a new test module belongs to one of them by a decision, not by whichever
#: list somebody remembered.
#:
#: `test_cdm_gmtif_adapter.py` earns its place here by a repair. It anchored its schemas directory
#: on the PACKAGE — `site-packages/../../schemas` once installed — and against the built wheel all
#: 32 of its fixtures failed with "unknown object_kind", a wall of failures whose cause was a
#: directory that was not there. Every other adapter module anchors on its own `__file__`; that
#: one now does too, and the harness refuses an empty `--schemas` directory outright.
PACKAGE_ONLY_TESTS = (
    "test_cdm_adapter_contract.py", "test_cdm_adsb_adapter.py", "test_cdm_ais_adapter.py",
    "test_cdm_asterix_cat021_adapter.py", "test_cdm_asterix_cat023_adapter.py",
    "test_cdm_asterix_cat034_adapter.py", "test_cdm_asterix_cat048_adapter.py",
    "test_cdm_asterix_cat062_adapter.py", "test_cdm_gmtif_adapter.py", "test_cdm_gmtif_codec.py",
    "test_cdm_harness.py", "test_cdm_legion_adapter.py", "test_cdm_list_adapters.py",
    "test_cdm_lossless.py", "test_cdm_models.py", "test_cdm_pntmap_adapter.py",
    "test_cdm_schemas.py", "test_cdm_stanag4609_adapter.py", "test_cdm_stanag4676_adapter.py",
    "test_cdm_tak_adapter.py",
    # `test_cdm_klv_framing.py` is package-only although it reads three prose documents and a pin
    # record, and the reason is worth a line because the obvious reading sends it the other way.
    # Every path it touches —
    # `FORMAT_COVERAGE.md`, `MIGRATIONS.md`, `fixtures/klv/README.md`, `klv_pin.json`,
    # `adapters/klv_codec.py` and `fixtures/klv/{framing,spec}/` — is INSIDE the package and ships
    # in the wheel, and all six are anchored on `synapse_cdm.__file__`. It reaches for the
    # repository root nowhere. `test_cdm_format_coverage.py` sits in the other list because it
    # compares that document against the repository's fixture tree; this one compares a ruling
    # against the artefacts the ruling produced, and those travel together.
    "test_cdm_klv_framing.py",
)

#: The other half, each with the repository fact it is about. Not "the rest" — naming the reason
#: is what stops a module drifting in here because it was easier than making it installable.
REPO_BOUND_TESTS = {
    "test_cdm_boundary.py": "AST over the package sources as files in the tree",
    "test_cdm_changelog_claim.py": "docs/docs/changelog.mdx against MIGRATIONS.md",
    "test_cdm_consumer_path.py": "README, docs and the fixture READMEs — prose outside the wheel",
    "test_cdm_deploy_workflow.py": "wrangler.toml and docs/README.md",
    "test_cdm_gate_rosters.py": "the rosters in gates/, which the wheel does not carry",
    "test_cdm_commit_message.py": "gates/commit_message.py and this history's messages",
    "test_cdm_scripted_edits.py": "gates/scripted_edit.py and git blobs — neither ships",
    "test_cdm_format_coverage.py": "FORMAT_COVERAGE.md against the repository's fixtures",
    "test_cdm_generator_loading.py": "how three test modules load a generator",
    "test_cdm_getting_started.py": "README.md and CONTRIBUTING.md against pyproject.toml",
    "test_cdm_landing_next.py": "the 'landing next' claim across repository documents",
    "test_cdm_ordinals.py": "adapter ordinals across repository prose",
    "test_cdm_packaging.py": "pyproject.toml's globs against git's index",
    "test_cdm_pins.py": "pinned specification documents, which the wheel does not carry",
    "test_cdm_prose_counts.py": "the adapter count in README, docs and CONTRIBUTING",
    "test_cdm_publication.py": "git history and the publication ledger",
    "test_cdm_release.py": "release tags against PACKAGE_VERSION",
    "test_cdm_trusted_publishing.py": ".github/workflows against PUBLICATION.md entry 6",
    "test_cdm_version_floor.py": "every Python file in the repository, gates included",
}

def source_roster() -> tuple[str, ...]:
    """The adapter names the REPOSITORY registers, asked of the source tree rather than typed.

    WHY THIS IS NOT A TUPLE OF NAMES ANY MORE
    -----------------------------------------
    It was one: ten strings, written down. Then `cat023` and `cat062` shipped, the tuple did not
    grow, and this gate's two roster checks failed in OPPOSITE ways on the same run.

    `check_resources` compared LENGTHS and said `12 adapters resolved, expected 10` — loud, and
    right. `check_harness` iterated the tuple, replayed ten of the twelve, and reported
    `10 adapters x 2 schema modes, 596 fixture verdicts, 0 failed`. That row is a PASS printed over
    a run that never touched either new adapter, and the count in it is the subset's own count,
    so nothing in the line admits that anything was skipped. The loud half was the harmless one.

    `tests/test_cdm_list_adapters.py` predicted this exact shape — "a tuple of ten names in
    `harness.py` that stays right until the eleventh adapter ships, and then reads as
    authoritative while being wrong". It landed HERE rather than in `harness.py`, and it landed
    because nothing read this file: the gate is a protocol act and not a suite member, so the one
    roster in the repository with no test over it was the one inside the gate.
    `tests/test_cdm_gate_rosters.py` is that test now, and it runs under `pytest` — where the
    drift would have been caught on the commit that caused it rather than on a release build.

    ASKED IN A SUBPROCESS, AND WHY
    ------------------------------
    `PYTHONPATH` set to `DIST_SRC`, because this file must not import the package it is about to
    build. An installed `synapse_cdm` on the gate runner's own path would answer for a different
    tree, which is the confusion every clean-venv arrangement below exists to prevent.
    """
    script = ("import json;from synapse_cdm.adapter import roster;"
              "print(json.dumps([n for n, c in roster().items() "
              "if c.__module__.startswith('synapse_cdm.adapters.')]))")
    env = {**os.environ, "PYTHONPATH": str(DIST_SRC)}
    names = json.loads(must(run([sys.executable, "-c", script], cwd=REPO, env=env),
                            "the source tree's roster"))
    if not names:
        raise Failed("the source tree registers no adapters at all, so every roster check below "
                     "would compare one empty set against another and pass. Something is wrong "
                     "with the tree, not with the wheel")
    return tuple(names)


class Failed(Exception):
    """A check that did not hold. Carries the reason; the runner prints and keeps going."""


class Gate:
    """Accumulates verdicts so a run reports EVERY failure rather than only the first.

    A gate that stops at the first problem makes the reader run it once per defect, and this one
    is expensive enough that they will instead fix one thing and hope. Checks that cannot even be
    attempted after a failure (the harness, if the install failed) are recorded as SKIP — never
    as a pass, which is the same rule the harness itself applies to its own unrun checks.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.results: list[tuple[str, str, str]] = []

    def check(self, name: str, fn) -> bool:
        try:
            detail = fn() or ""
        except Failed as e:
            self.results.append((name, "FAIL", str(e)))
            return False
        except Exception as e:                                       # noqa: BLE001
            self.results.append((name, "FAIL", f"{type(e).__name__}: {e}"))
            return False
        self.results.append((name, "PASS", detail))
        return True

    def skip(self, name: str, why: str) -> None:
        self.results.append((name, "SKIP", why))

    @property
    def failed(self) -> int:
        return sum(1 for _, verdict, _ in self.results if verdict == "FAIL")

    def render(self) -> str:
        width = max(len(n) for n, _, _ in self.results)
        lines = [f"=== {self.label} ==="]
        for name, verdict, detail in self.results:
            lines.append(f"  {name.ljust(width)}  {verdict}  {detail}")
        lines.append(f"  {len(self.results)} checks, {self.failed} failed")
        return "\n".join(lines)


def run(argv: list[str], *, cwd: pathlib.Path | None = None,
        env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def must(result: subprocess.CompletedProcess, what: str) -> str:
    if result.returncode != 0:
        raise Failed(f"{what} exited {result.returncode}\n"
                     f"      stdout: {result.stdout.strip()[-2000:]}\n"
                     f"      stderr: {result.stderr.strip()[-2000:]}")
    return result.stdout


def make_venv(path: pathlib.Path) -> pathlib.Path:
    """A venv with pip, and the interpreter that runs this gate as its base.

    `with_pip=True` rather than reaching for `uv`: `pip` is what CONTRIBUTING.md tells a
    contributor to use and what a partner will have. A gate that needs a tool the documented path
    does not mention is a gate only the maintainer can run — which is the class of defect the
    whole round is about.
    """
    venv.EnvBuilder(with_pip=True, clear=True).create(path)
    return path / ("Scripts" if os.name == "nt" else "bin")


def build_distribution(source: pathlib.Path, outdir: pathlib.Path,
                       builder: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    must(run([str(builder / "python"), "-m", "build", "--outdir", str(outdir), str(source)]),
         "python -m build")
    wheels = list(outdir.glob("*.whl"))
    sdists = list(outdir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise Failed(f"expected one wheel and one sdist, got {wheels} and {sdists}")
    return wheels[0], sdists[0]


# --------------------------------------------------------------------------------- checks


def check_manifest(wheel: pathlib.Path) -> str:
    """The wheel's file set against git's, both directions — the 72, and the PDFs.

    Direction one catches a tracked file the globs miss. Direction two is the one that only bites
    on a maintainer's machine: the pinned specification PDFs are gitignored and present on disk
    here, under EUROCONTROL's, NATO's and MISB's own terms, and NOTICE says outright they are not
    part of the Work. One widened glob would put a NATO standard inside an Apache-2.0 wheel.
    """
    tracked = set(must(run(["git", "ls-files", "synapse_cdm"], cwd=DIST_SRC),
                       "git ls-files").split())
    with zipfile.ZipFile(wheel) as archive:
        shipped = {n for n in archive.namelist() if n.startswith("synapse_cdm/")}
    missing, extra = sorted(tracked - shipped), sorted(shipped - tracked)
    if missing:
        raise Failed(f"{len(missing)} tracked file(s) are NOT in the wheel, e.g. {missing[:5]}")
    if extra:
        raise Failed(f"{len(extra)} file(s) in the wheel that git does not track, e.g. "
                     f"{extra[:5]} — if any is a .pdf this is a licensing defect")
    return f"{len(shipped)} files, equal to git in both directions"


def check_licences(wheel: pathlib.Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in ("LICENSE", "NOTICE"):
            entries = [n for n in names if n.endswith(f".dist-info/licenses/{name}")]
            if not entries:
                raise Failed(f"the wheel carries no {name}. Apache-2.0 section 4(d) makes "
                             "carrying NOTICE a condition of redistributing this Work, and a "
                             "wheel on an index is a redistribution")
            if archive.read(entries[0]) != (REPO / name).read_bytes():
                raise Failed(f"the wheel's {name} differs from the repository's")
    return "LICENSE and NOTICE present and byte-identical"


def check_no_repo_paths(wheel: pathlib.Path) -> str:
    """Nothing the partner receives may name a path INSIDE this package by the repo's layout.

    THE RULE, AND WHY IT IS THIS ONE AND NOT "NEVER MENTION THE REPOSITORY"
    ----------------------------------------------------------------------
    The string that matters is `packages/cdm/synapse_cdm/` — a path into the package's own
    contents, written the way the development repository lays them out. It is always wrong for an
    installed reader, and wrong in the worst way: they HAVE that directory, under a different
    name, so the instruction looks correct, runs, and fails on a path they never chose. Every one
    of the fourteen sites this first caught was of that shape — `--fixtures packages/cdm/
    synapse_cdm/fixtures/<name>`, and `python packages/cdm/synapse_cdm/fixtures/*/spec/
    build_fixtures.py`.

    `pip install -e "packages/cdm[test]"` is deliberately NOT flagged. It names the distribution
    root, not the package's insides, it is the correct command, and it appears under a heading
    that says it is from a clone. A rule that banned every mention of the repository would have
    forced the contributor path out of the one document a contributor reads first, to buy nothing:
    that command cannot mislead an installed reader, because it does not resolve at all for them.
    """
    needle = "packages/cdm/synapse_cdm/"
    offenders, scanned = [], 0
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if not name.startswith("synapse_cdm/") or not name.endswith((".py", ".md")):
                continue
            scanned += 1
            text = archive.read(name).decode("utf-8", "replace")
            for number, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    offenders.append(f"{name}:{number}: {line.strip()[:90]}")
    if offenders:
        raise Failed(f"{len(offenders)} shipped line(s) name a path inside this package using "
                     "the repository's layout — a directory the reader has under another name:\n"
                     "      " + "\n      ".join(offenders[:12]))
    # A check that examined nothing must not report a pass. The mutation makes this reachable:
    # a wheel with `package-data` emptied carries no Markdown at all, and without this the prose
    # check would report green over a distribution with no prose in it. The expected number is
    # DERIVED from git rather than written down — a threshold typed as a literal here would be
    # the same stale count the package-data enumeration was.
    expected = len([f for f in must(run(["git", "ls-files", "synapse_cdm"], cwd=DIST_SRC),
                                    "git ls-files").split() if f.endswith((".py", ".md"))])
    if scanned != expected:
        raise Failed(f"{scanned} Python or Markdown files in the wheel, {expected} tracked. This "
                     "run read a fraction of the distribution's prose and its PASS would mean "
                     "nothing")
    return (f"{scanned} shipped .py/.md files, none naming the package's own contents by the "
            "repository's layout")


def check_metadata(python: pathlib.Path, outside: pathlib.Path) -> str:
    declared = json.loads(must(run([
        str(python), "-c",
        "import json,importlib.metadata as m,synapse_cdm.version as v;"
        "print(json.dumps({'dist': m.version('synapse-cdm'),"
        "'package': v.PACKAGE_VERSION, 'schema': v.SCHEMA_VERSION}))"], cwd=outside),
        "importlib.metadata"))
    if declared["dist"] != declared["package"]:
        raise Failed(f"the installed distribution reports {declared['dist']} and the package "
                     f"says PACKAGE_VERSION is {declared['package']}")
    return (f"synapse-cdm {declared['dist']} (schema_version {declared['schema']} — a different "
            "number by design)")


def check_import(python: pathlib.Path, outside: pathlib.Path, venv_dir: pathlib.Path) -> str:
    """Imported, and imported from the INSTALL — not from a tree that happened to be on the path.

    Asserted rather than assumed because it is exactly the accident that would make every check
    below meaningless: a run whose `synapse_cdm` came from `packages/cdm` would pass this gate
    while proving nothing at all about the wheel.
    """
    where = must(run([str(python), "-c", "import synapse_cdm;print(synapse_cdm.__file__)"],
                     cwd=outside), "import synapse_cdm").strip()
    resolved = pathlib.Path(where).resolve()
    if not resolved.is_relative_to(venv_dir.resolve()):
        raise Failed(f"synapse_cdm was imported from {resolved}, which is not inside the clean "
                     f"venv at {venv_dir}. Everything this gate reports would be about the "
                     "source tree rather than the wheel")
    if resolved.is_relative_to(REPO):
        raise Failed(f"synapse_cdm was imported from inside the repository ({resolved})")
    return "from site-packages, with no part of the repository on the path"


def check_resources(python: pathlib.Path, outside: pathlib.Path) -> str:
    """Every adapter's fixtures found through `importlib.resources`, from a foreign directory."""
    script = (
        "import json;from synapse_cdm.adapter import discover, packaged_fixtures\n"
        "out={}\n"
        "for n,c in discover().items():\n"
        "    if not c.__module__.startswith('synapse_cdm.adapters.'): continue\n"
        "    p=packaged_fixtures(c)\n"
        "    out[n]=[str(p), p.is_dir(), len([f for f in p.iterdir() "
        "if f.is_file() and f.name!='README.md']) if p.is_dir() else 0]\n"
        "print(json.dumps(out))"
    )
    found = json.loads(must(run([str(python), "-c", script], cwd=outside), "packaged_fixtures"))
    # Compared as SETS, in both directions, and not by length. The length comparison this
    # replaces could tell that the totals differed and nothing else — not WHICH adapter the wheel
    # was missing, and not which of the two possible faults it was looking at. Both are real: a
    # wheel short of the tree is a build that dropped a module, a wheel longer than the tree is a
    # wheel built from a tree that is not this one.
    expected = set(source_roster())
    if set(found) != expected:
        missing = sorted(expected - set(found))
        extra = sorted(set(found) - expected)
        raise Failed(
            f"the wheel's adapters are not the repository's ({len(found)} resolved, "
            f"{len(expected)} registered in the tree)"
            + (f"; in the tree but NOT in the wheel: {missing}" if missing else "")
            + (f"; in the wheel but NOT in the tree: {extra}" if extra else ""))
    empty = {n: v for n, v in found.items() if not v[1] or v[2] == 0}
    if empty:
        raise Failed(f"adapters whose packaged fixtures are missing or empty: {empty}")
    return f"{len(found)} adapters, {sum(v[2] for v in found.values())} fixture files"


def check_schemas(python: pathlib.Path, outside: pathlib.Path,
                  schema_dir: pathlib.Path) -> str:
    """Regenerate the publication from anywhere, then require it to match the repository's.

    The wheel deliberately carries no copy of `/schemas`: a third copy of a generated artefact is
    a third thing that can go stale, and `schemas.py` argues that case for the second one already.
    What it carries is the GENERATOR, so a consumer with no clone can produce the files. This
    check is that claim: written from outside the repository, then compared byte for byte with
    the publication in the tree.
    """
    must(run([str(python), "-m", "synapse_cdm.schemas", "--out", str(schema_dir)], cwd=outside),
         "python -m synapse_cdm.schemas")
    verdict = must(run([str(python), "-m", "synapse_cdm.schemas", "--check",
                        "--out", str(schema_dir)], cwd=outside), "schemas --check")
    if "CURRENT" not in verdict:
        raise Failed(f"schemas --check did not report CURRENT: {verdict.strip()}")
    published = sorted((REPO / "schemas").glob("*.schema.json"))
    written = sorted(schema_dir.glob("*.schema.json"))
    if [p.name for p in published] != [p.name for p in written]:
        raise Failed(f"the installed package generated {[p.name for p in written]}, the "
                     f"repository publishes {[p.name for p in published]}")
    differing = [a.name for a, b in zip(published, written) if a.read_bytes() != b.read_bytes()]
    if differing:
        raise Failed(f"the schemas generated from the installed package differ from the "
                     f"published ones: {differing}")
    return f"{len(written)} schemas regenerated from outside the repo, byte-identical"


def check_harness(python: pathlib.Path, outside: pathlib.Path,
                  schema_dir: pathlib.Path) -> str:
    """Every adapter the tree registers, with NO `--fixtures` argument — the invocation that used
    to be impossible.

    Run twice over: once letting the harness generate the schemas in-process, and once against
    the files it just wrote, because those are two different claims. The second is the one
    `--schemas` exists for and the one a partner validating against the published contract makes.

    The roster comes from `source_roster()` and not from a literal, because this loop is where a
    written-down one did its damage: it replayed ten adapters out of twelve and printed the ten as
    its verdict. The count in the returned line is now the length of what was actually iterated,
    which is the only count that cannot describe a run that did not happen.
    """
    adapters = source_roster()
    total = 0
    for name in adapters:
        for extra in ([], ["--schemas", str(schema_dir)]):
            result = run([str(python), "-m", "synapse_cdm.harness",
                          "--adapter", name, "--json", *extra], cwd=outside)
            if result.returncode != 0:
                raise Failed(f"--adapter {name} {' '.join(extra)} exited {result.returncode}: "
                             f"{(result.stderr or result.stdout).strip()[-800:]}")
            report = json.loads(result.stdout)
            if report["failed"] or not report["passed"]:
                raise Failed(f"--adapter {name}: {report['passed']} passed, "
                             f"{report['failed']} failed")
            # Resolved on both sides: on macOS the venv lives under `/var/...` and the path the
            # report carries comes back as `/private/var/...`, and an unresolved comparison would
            # fail every adapter for a symlink rather than for a defect.
            replayed = pathlib.Path(report["fixtures"]).resolve()
            if not replayed.is_relative_to(python.parents[1].resolve()):
                raise Failed(f"--adapter {name} replayed {replayed}, which is not inside the "
                             "clean venv — the fixtures came from somewhere other than the wheel")
            total += report["passed"]
    return (f"{len(adapters)} adapters x 2 schema modes, {total} fixture verdicts, 0 failed")


def check_console_scripts(scripts: pathlib.Path, outside: pathlib.Path,
                          schema_dir: pathlib.Path) -> str:
    must(run([str(scripts / "cdm-harness"), "--adapter", "pntmap", "--json"], cwd=outside),
         "cdm-harness")
    must(run([str(scripts / "cdm-schemas"), "--check", "--out", str(schema_dir)], cwd=outside),
         "cdm-schemas --check")
    return "cdm-harness and cdm-schemas both run"


def check_slice_closure() -> str:
    """Every test module belongs to exactly one of the two lists, and both name real files.

    The lists are what decides what runs against the installed package, so a module missing from
    both is a module nobody decided about — and the default for an undecided module is that it is
    never run this way, which is the silent narrowing this repository refuses everywhere else.
    """
    on_disk = {p.name for p in (REPO / "tests").glob("test_*.py")}
    listed = set(PACKAGE_ONLY_TESTS) | set(REPO_BOUND_TESTS)
    both = set(PACKAGE_ONLY_TESTS) & set(REPO_BOUND_TESTS)
    if both:
        raise Failed(f"in both lists: {sorted(both)}")
    undecided = sorted(on_disk - listed)
    if undecided:
        raise Failed(f"test modules in neither list: {undecided}. Decide: does it judge the "
                     "package (it runs against the wheel) or the repository (it does not)?")
    gone = sorted(listed - on_disk)
    if gone:
        raise Failed(f"listed but not on disk: {gone}")
    return (f"{len(on_disk)} modules: {len(PACKAGE_ONLY_TESTS)} judge the package, "
            f"{len(REPO_BOUND_TESTS)} judge the repository")


def check_test_slice(python: pathlib.Path, outside: pathlib.Path) -> str:
    """The package-only half of the suite, against the installed package.

    `-o pythonpath=` empties the setting `pytest.ini` uses to put `packages/cdm` on the path. That
    override is the whole point of the check and it is also its most fragile part, so a planted
    module asserts the import actually came from the venv — without it a green slice here could be
    the source tree passing under a different name.
    """
    planted = outside / "test_zzz_the_package_under_test_is_the_installed_one.py"
    planted.write_text(
        "import pathlib, sys, synapse_cdm\n"
        "def test_the_import_came_from_the_installed_wheel():\n"
        "    where = pathlib.Path(synapse_cdm.__file__).resolve()\n"
        "    assert 'site-packages' in where.parts, (\n"
        "        f'synapse_cdm was imported from {where}; the slice would be judging a source '\n"
        "        'tree while claiming to judge the wheel')\n"
    )
    targets = [str(REPO / "tests" / name) for name in PACKAGE_ONLY_TESTS] + [str(planted)]
    result = run([str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                  "-o", "pythonpath=", "-o", "addopts=", *targets], cwd=outside)
    tail = (result.stdout or result.stderr).strip().splitlines()[-1:] or [""]
    if result.returncode != 0:
        raise Failed(f"the slice failed: {tail[0]}\n{result.stdout[-3000:]}")
    return f"{len(PACKAGE_ONLY_TESTS)} modules + the plant: {tail[0]}"


# ------------------------------------------------------------------------------ the runner


def gate(source: pathlib.Path, workdir: pathlib.Path, *, label: str,
         slice_tests: bool = True, built: dict | None = None) -> Gate:
    """`built` is filled in with the artefacts this run judged, for `--export-dist`.

    Handed in rather than returned, because the caller needs the paths even when a later check
    fails: an export must be able to say "these are the bytes that were refused".
    """
    result = Gate(label)
    builder_scripts = make_venv(workdir / "builder")
    must(run([str(builder_scripts / "python"), "-m", "pip", "install", "-q",
              "--disable-pip-version-check", "build"]), "pip install build")

    dist = workdir / "dist"
    built = built if built is not None else {}
    if not result.check("build", lambda: _build_into(built, source, dist, builder_scripts)):
        for name in ("closure", "manifest", "licences", "prose", "install", "metadata",
                     "import", "resources", "schemas", "harness", "scripts", "slice"):
            result.skip(name, "the distribution did not build")
        return result

    wheel = built["wheel"]
    result.check("closure", check_slice_closure)
    result.check("manifest", lambda: check_manifest(wheel))
    result.check("licences", lambda: check_licences(wheel))
    result.check("prose", lambda: check_no_repo_paths(wheel))

    clean = workdir / "clean"
    scripts = make_venv(clean)
    python = scripts / "python"
    outside = workdir / "outside"
    outside.mkdir(exist_ok=True)
    schema_dir = workdir / "schemas"

    installed = result.check("install", lambda: _install(python, wheel))
    if not installed:
        for name in ("metadata", "import", "resources", "schemas", "harness", "scripts", "slice"):
            result.skip(name, "the wheel did not install")
        return result

    result.check("metadata", lambda: check_metadata(python, outside))
    if not result.check("import", lambda: check_import(python, outside, clean)):
        for name in ("resources", "schemas", "harness", "scripts", "slice"):
            result.skip(name, "the package did not import from the install")
        return result

    result.check("resources", lambda: check_resources(python, outside))
    schemas_ok = result.check("schemas", lambda: check_schemas(python, outside, schema_dir))
    result.check("harness", lambda: check_harness(python, outside, schema_dir))
    if schemas_ok:
        result.check("scripts", lambda: check_console_scripts(scripts, outside, schema_dir))
    else:
        result.skip("scripts", "the schemas were not written, so cdm-schemas --check has no input")

    if slice_tests:
        must(run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                  "pytest"]), "pip install pytest")
        result.check("slice", lambda: check_test_slice(python, outside))
    else:
        result.skip("slice", "not run in this mode")
    return result


def _build_into(store: dict, source: pathlib.Path, dist: pathlib.Path,
                builder: pathlib.Path) -> str:
    wheel, sdist = build_distribution(source, dist, builder)
    store["wheel"], store["sdist"] = wheel, sdist
    return f"{wheel.name} ({wheel.stat().st_size // 1024} KiB) and {sdist.name}"


def _install(python: pathlib.Path, wheel: pathlib.Path) -> str:
    must(run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check",
              str(wheel)]), "pip install the wheel")
    return "into a venv with nothing of this repository on its path"


def mutated_source(workdir: pathlib.Path) -> pathlib.Path:
    """A copy of the distribution with `package-data` emptied: the code, none of the fixtures.

    This is the 72-file defect in its worst form and it is the one shape a partner could never
    diagnose — the package imports, the models work, and the harness reports that it found no
    fixtures for an adapter it can name. The `tests/` half of this repository would not notice:
    `pytest.ini` points it at the source tree.
    """
    target = workdir / "mutant"
    shutil.copytree(DIST_SRC, target, ignore=shutil.ignore_patterns(
        "__pycache__", "*.egg-info", "build", "dist"))
    pyproject = target / "pyproject.toml"
    text = pyproject.read_text()
    marker = "[tool.setuptools.package-data]\nsynapse_cdm = [\n    \"fixtures/**/*\",\n    \"*.md\",\n]"
    if marker not in text:
        raise SystemExit("gates/wheel_install.py: the package-data block this mutation edits has "
                         "been reworded. Re-anchor the mutation deliberately — a mutation that "
                         "silently stops mutating is a gate that stops being checked")
    pyproject.write_text(text.replace(marker, "[tool.setuptools.package-data]\nsynapse_cdm = []"))
    return target


def export_dist(built: dict, destination: pathlib.Path) -> str:
    """Copy the artefacts this gate JUDGED to `destination`, and print their digests.

    WHY THIS EXISTS, AND WHY THE WORKFLOW DOES NOT BUILD ITS OWN
    -----------------------------------------------------------
    `.github/workflows/publish.yml` has to publish the bytes these 13 checks passed, and the
    obvious arrangement — the workflow runs `python -m build`, then runs this gate — does not
    achieve that. This gate builds its own distribution, so that arrangement produces TWO builds,
    and two builds of one tree are not the same file:

        build 1  synapse_cdm-1.0.0-py3-none-any.whl  7fced22ebf9de490...
        build 2  synapse_cdm-1.0.0-py3-none-any.whl  5e0a8ecf02adf550...

    The payloads are byte-identical — unzipped, the two trees `diff -r` clean. What differs is the
    embedded timestamps on the entries the build itself generates (`.dist-info/METADATA`, `WHEEL`,
    `RECORD`, and the gzip header of the sdist), and a zip stores those to a two-second resolution,
    so two builds seconds apart differ. Nothing is wrong; wheels are simply not reproducible here.

    That is enough to break the claim. A gate that passes build 1 while build 2 is uploaded has
    checked a file that nobody will ever install, and the difference between the two is exactly the
    metadata a consumer verifies. So there is ONE build: this one, and the workflow publishes what
    it hands over.

    THE GUARD
    ---------
    `--mutation-check` deliberately builds a second, broken distribution with `package-data`
    emptied — a 559 KiB wheel with no fixtures in it. Exporting THAT would hand the publish job a
    distribution this gate exists to refuse. Structurally it cannot happen: the export reads the
    dict the non-mutant run filled. Structure is not a check, so the fixture assertion below is,
    because "the export is wired to the right dict" is precisely the kind of thing that stays true
    until someone refactors the runner.
    """
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(built["wheel"]) as archive:
        fixtures = [n for n in archive.namelist() if "/fixtures/" in n and not n.endswith("/")]
    if not fixtures:
        raise Failed(
            f"refusing to export {built['wheel'].name}: it carries no fixture files at all. That "
            "is the shape of the wheel --mutation-check builds ON PURPOSE, so either the export is "
            "reading the mutant's artefacts or the real build has developed the defect this gate "
            "was written for. Either way it must not reach an index")
    lines = []
    for path in (built["sdist"], built["wheel"]):
        shutil.copy2(path, destination / path.name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"  {digest}  {path.name}")
    return (f"exported to {destination} — {len(fixtures)} fixture files in the wheel\n"
            + "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mutation-check", action="store_true",
                        help="also build a wheel with no fixtures in it and require this gate "
                             "to refuse it")
    parser.add_argument("--keep", action="store_true",
                        help="do not delete the working directory (for inspection)")
    parser.add_argument("--export-dist", metavar="DIR", default=None,
                        help="copy the sdist and wheel THIS RUN judged into DIR, and print their "
                             "SHA-256 digests. Only on a run with no failures — see export_dist()")
    args = parser.parse_args(argv)

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="cdm-wheel-gate-"))
    status = 0
    try:
        built: dict[str, pathlib.Path] = {}
        real = gate(DIST_SRC, workdir / "real", label="the wheel built from packages/cdm",
                    built=built)
        print(real.render())
        status = 1 if real.failed else 0

        if args.export_dist:
            # Refused on a failing run, and refused LOUDLY. An export that quietly produced
            # nothing would leave the publish job with an empty artefact directory and a message
            # about that instead of about the checks that failed here.
            if real.failed:
                print(f"\nnot exporting: {real.failed} of this run's checks failed, and the "
                      "artefact a gate refused must not be the artefact a workflow uploads")
                status = 1
            else:
                try:
                    print("\n" + export_dist(built, pathlib.Path(args.export_dist)))
                except Failed as refusal:
                    print(f"\nexport refused: {refusal}")
                    status = 1

        if args.mutation_check:
            print()
            mutant = gate(mutated_source(workdir), workdir / "mutant",
                          label="MUTATION: the same wheel with package-data emptied",
                          slice_tests=False)
            print(mutant.render())
            expected = {"manifest", "resources", "harness"}
            actually_failed = {n for n, verdict, _ in mutant.results if verdict == "FAIL"}
            print()
            if not expected <= actually_failed:
                print("MUTATION NOT CAUGHT: a wheel carrying no fixtures at all was accepted by "
                      f"{sorted(expected - actually_failed)}. Those checks are decoration until "
                      "they can refuse this.")
                status = 1
            else:
                print(f"mutation caught: {sorted(actually_failed)} refused the fixture-less "
                      "wheel, so this gate can fail")
    finally:
        if args.keep:
            print(f"\nworking directory kept at {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
