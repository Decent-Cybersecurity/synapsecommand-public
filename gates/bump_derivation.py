"""The bump kind, derived from the packaged diff rather than typed into a release brief.

WHY THIS EXISTS, AND IT IS AN INCIDENT RATHER THAN A PRINCIPLE
--------------------------------------------------------------
The 1.2.1 release round was specified as **1.3.0**. Nothing importable had changed since `v1.2.0`:
`pyproject.toml` and `adapter.py` moved on comment lines only, every other file that moved under
`packages/` is a shipped document, and `version.py`'s MINOR list — an adapter, a harness flag or
check, a fixture set, a new optional dependency — reached none of it. So the PATCH row governed
and the release renumbered itself to **1.2.1**, which is ledger entry 10 of `PUBLICATION.md`.

**The renumbering was a person reading a diff.** Nothing in the suite derived the bump kind, so
`PACKAGE_VERSION = "1.3.0"` would have gone green on every check in this repository:
`tests/test_cdm_release.py` requires a tag to NAME its tree's `PACKAGE_VERSION` and requires the
notes to describe that version, and both of those are satisfied by any number somebody types
consistently. A version number is the one claim in a release that can never be corrected — a PyPI
filename is permanent — and it was the one claim with no machine behind it.

THE CLAIM THIS GATE MAKES TRUE
------------------------------
    `PACKAGE_VERSION` is the bump kind that the diff over the distribution's own contents,
    classified against `version.py`'s PACKAGE_VERSION table, requires — no larger and no
    smaller — or the classification is refused with the file and the unruled unit named.

Three refusals follow from it, and all three are reachable:

* **UNDERSHOOT** — the arc adds a surface and the number does not move far enough. A new adapter
  numbered as a PATCH ships a distribution that denies its own contents.
* **EXCEED** — the arc adds nothing and the number moves anyway. **This is what happened.** A
  MINOR asserts a surface change to every consumer reading the number, and 1.3.0 would have been
  that assertion about an arc that changed no executable line.
* **UNRULED** — the diff moves a function's body and the table does not reach it. See below; this
  is the refusal that keeps the other two honest.

WHY "UNRULED" IS A REFUSAL AND NOT A DEFAULT
--------------------------------------------
`version.py`'s table is prose, and two of its rows overlap on exactly one case:

    PATCH  a translation fix, a message, a docstring. No surface change.
    MAJOR  an importable name is removed or its MEANING changes, …

A function whose body moved while its name stayed is in both rows at once, and no diff separates
them — "the meaning changed" is a claim about intent. A gate that picked one would be guessing,
and it would guess PATCH, because that is the cheap answer and the one a round in a hurry wants.
So the gate **refuses and names the unit**: the module, the function, and which two rows reach it.
A human then rules, in writing, in `MIGRATIONS.md`, and the ruling is what the gate reads next
time. That keeps the judgment where it belongs and keeps it dated — which is entry 5's rule, that
a record which quietly updates its own history is a record nobody can date.

**The gate must therefore be satisfiable, and that is not a small caveat.**
`tests/test_cdm_release.py::_package_tree_moved_since` carries this repository's scar from getting
it wrong: its two halves once read different trees, so there was a window where the gate demanded
a section and refused the tree that had one, and its message invited deleting the section — the
one wrong move. A gate whose only exit is "guess" is that failure with better manners. The exit
here is `**Bump ruling.**`, parsed out of `MIGRATIONS.md`, and it is checked in BOTH directions: a
ruling naming a unit that is not ambiguous is refused as stale, exactly as an unruled unit is.

WHAT IS DECISIVE, AND WHERE EACH SIGNAL COMES FROM
--------------------------------------------------
Every signal is read out of the tree at the two ends of the arc. Nothing is read out of a comment,
a changelog, or this file's own opinion.

| Signal | Kind | Read from |
| --- | --- | --- |
| an `Adapter` subclass's `name` appears | MINOR | the `name = "…"` literal, by AST, no import |
| … disappears | MAJOR | the same set, the other direction |
| a harness `--flag` appears / disappears | MINOR / MAJOR | `add_argument`'s first literal, by AST |
| a harness `_check_*` appears / disappears | MINOR / MAJOR | the function names in `harness.py` |
| a harness exit code appears / disappears | MINOR / MAJOR | `EXIT_*` module constants and `main`'s literal returns |
| a fixture set appears | MINOR | a new directory under `synapse_cdm/fixtures/` |
| a public top-level name appears / disappears | MINOR / MAJOR | module top level, by AST |
| `requires-python`'s floor rises | MAJOR | `pyproject.toml`, parsed |
| an optional dependency appears | MINOR | `[project.optional-dependencies]`, parsed |
| a console entry point appears / disappears | MINOR / MAJOR | `[project.scripts]`, parsed |
| `SCHEMA_VERSION` moves | MINOR | `version.py`, and the table says so outright |
| a shipped document, fixture payload or pin record moves | PATCH | the file's own bytes |
| a module moves on comments and docstrings ONLY | PATCH | the functional AST is unchanged |

**Comments are not stripped by a regex, and that is the whole reason this is mechanizable.** A
module is compared as its *functional AST* — parsed, docstring `Expr` nodes deleted, dumped
without line numbers. Comments are not in an AST at all, so "comment-only" is a property that
falls out of the parse rather than a line filter somebody has to keep correct. `pyproject.toml` is
compared the same way, through `tomllib`: a comment-only edit is invisible to a parsed mapping.
Both of the 1.2.1 arc's `.py`/`.toml` diffs are comment-only under this test, which is the
measurement entry 10 states in prose and this gate now derives.

**THE RULE OF SHAPE, because the table's two lists are not exhaustive.** A diff produces cases
neither row enumerates — a console entry point, a required dependency, a fixture set that
disappears. Treating every unlisted case as PATCH is how 1.3.0's mirror image ships: a
distribution that dropped an entry point, numbered as a docstring fix. So the rows are read for
the shape they state outright — MINOR is "… is added. Existing code keeps working", MAJOR is "… is
removed or its meaning changes" — and an unambiguous ADDITION of a declared surface is MINOR, an
unambiguous REMOVAL is MAJOR. The rule only ever fires on a set gaining or losing a member, never
on a body: a modification in place is the unruled case and goes to a human. The full statement is
the comment block above `_classify_pyproject`.

**`PACKAGE_VERSION`'s own assignment is excluded from the classification.** It is the declaration
under judgement, and a gate that counted it as evidence would find every bump self-justifying.
`SCHEMA_VERSION`'s is not excluded: it is evidence, and the table says a schema bump is always at
least a package MINOR.

WHICH ARC IS JUDGED, WHICH IS ONLY REPORTED
-------------------------------------------
Two arcs, and conflating them would make the gate wrong in the ordinary between-releases state.

* **The judged arc** ends at the number's own tag when one exists — `v1.2.0 → v1.2.1` today — and
  at the working tree when it does not. That second case is the release candidate, and it is the
  moment `1.3.0` gets refused, before the tag rather than after.
* **The pending arc** runs from the released tag to the working tree, and is REPORTED rather than
  refused. `PACKAGE_VERSION` is legitimately unbumped between releases, so a floor here is not a
  finding — it is the smallest number the next release may take, and printing it is how a round
  learns what it has committed the next one to.

The working tree is included, staged and unstaged, for `_package_tree_moved_since`'s reason: a
check whose halves read different trees is a check with an unsatisfiable window in it.

WHAT THIS GATE DOES NOT CLAIM
-----------------------------
That the floor is the true bump. It is the largest bump the diff **proves**, and a residue it
cannot attribute is refused rather than absorbed. Where a changed unit sits in a module whose
roster moved, the roster move explains it and the gate does not additionally prove that the roster
move is the WHOLE of the change — a function that adds a flag and also changes what an existing
flag means is ruled MINOR here, and only a reader would catch the second half. What the gate does
prove is that no unit changed with nothing in the table reaching it.

WHY IT IS A GATE WITH A SUITE MEMBER RATHER THAN ONLY ONE OR THE OTHER
----------------------------------------------------------------------
It needs git and nothing else — no network, no credential — so unlike `gates/deploy_record.py` it
belongs in the suite, and `tests/test_cdm_bump_derivation.py` runs it on the real arc and holds it
to both refusal directions on fixtures. It is also a command, because a release round needs to ask
it a question before typing a number, and `--mutation-check` is how a round proves it can still
fail.

USAGE

    python gates/bump_derivation.py                  # the verdict; exit 0 clean, 1 on any finding
    python gates/bump_derivation.py --json           # the measurement, for a round to quote
    python gates/bump_derivation.py --mutation-check  # both refusal directions, on fixtures
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import fnmatch
import json
import pathlib
import re
import subprocess
import sys
import tomllib

REPO = pathlib.Path(__file__).resolve().parents[1]
DIST = "packages/cdm"
PKG = "synapse_cdm"
MIGRATIONS = REPO / DIST / PKG / "MIGRATIONS.md"

#: Ordered weakest to strongest. `NONE` is a real verdict and not a missing one: an arc that
#: changes no file in the distribution warrants no release at all, and a number moved over it is
#: an EXCEED against nothing.
KINDS = ("NONE", "PATCH", "MINOR", "MAJOR")

#: The one assignment excluded from classification — the declaration under judgement.
DECLARATION = f"{PKG}/version.py:PACKAGE_VERSION"

#: Where a human's ruling on an unruled unit is read from. A paragraph in `MIGRATIONS.md`, in the
#: section describing the arc, of the shape:
#:
#:     **Bump ruling.** `synapse_cdm/harness.py:main` — PATCH: the wording of a refusal.
#:
#: Parsed rather than free prose because a ruling nothing reads is the habit this gate replaced.
RULING_MARKER = "**Bump ruling.**"
#: The unit is ONE backticked span and it is the id the derivation prints, verbatim —
#: `synapse_cdm/harness.py:main`, not `` `synapse_cdm/harness.py`:`main` ``. Two spans was the
#: first draft's spelling and the regex silently matched only the second of them, so a ruling read
#: as being about `main` in no particular file and was refused as stale. One span, one id, and the
#: message a refusal prints is the string a ruling has to name.
#:
#: **THE SPAN MAY CONTAIN SPACES, AND FORBIDDING THEM MADE THIS GATE UNSATISFIABLE FOR A WHOLE
#: CLASS OF UNIT — found 2026-09-04 by the park 2 round.** `_units` names an unnamed top-level
#: statement `<statement N>`, which contains a space, so `[^`\s]+` could never match the id the
#: gate itself had just printed. The refusal named four units and would accept a ruling for none
#: of them: the module docstring's own caveat — "the gate must therefore be satisfiable" — failed
#: on ids the gate generates. Any module-level `import` insertion produces them, because those
#: statements are keyed by POSITION where a named unit is keyed by name, so one inserted import
#: renumbers every unnamed statement below it.
#:
#: **LOOSENING IT COSTS NOTHING, because the unit is validated downstream and not here.**
#: `apply_rulings` refuses any ruling naming a unit the arc does not find ambiguous, so a span
#: that matches loosely and means nothing is refused as stale rather than silently honoured. The
#: closing backtick still bounds it and the kind still has to follow.
RULING_LINE = re.compile(
    r"`(?P<unit>[^`]+?)`\s*(?:—|-)\s*(?P<kind>PATCH|MINOR|MAJOR)\b", re.I)


class Finding(Exception):
    """A refusal. Every one of these is a number somebody has to re-derive or a ruling to write."""


def stronger(left: str, right: str) -> str:
    return left if KINDS.index(left) >= KINDS.index(right) else right


@dataclasses.dataclass(frozen=True)
class Signal:
    """One decisive reading of the diff: a kind, the unit it is about, and the table row."""

    kind: str
    unit: str
    reason: str


@dataclasses.dataclass(frozen=True)
class Ambiguity:
    """A changed unit the table does not decide. Named, never guessed at."""

    unit: str
    reason: str


@dataclasses.dataclass
class Derivation:
    """What an arc proves. `floor` is meaningless while `ambiguities` is non-empty."""

    signals: list[Signal] = dataclasses.field(default_factory=list)
    ambiguities: list[Ambiguity] = dataclasses.field(default_factory=list)

    @property
    def floor(self) -> str:
        kind = "NONE"
        for signal in self.signals:
            kind = stronger(kind, signal.kind)
        return kind

    def strongest(self) -> list[Signal]:
        return [s for s in self.signals if s.kind == self.floor]


# ------------------------------------------------------------------ what the distribution holds


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False)


def _git_text(*args: str) -> str:
    out = _git(*args)
    if out.returncode != 0:
        raise Finding(f"`git {' '.join(args)}` failed: {out.stderr.decode(errors='replace')[:300]}")
    return out.stdout.decode()


def _translate(pattern: str) -> re.Pattern[str]:
    """A setuptools package-data glob as a regex over a `/`-joined relative path.

    `**` crosses separators; `*` and `?` do not. Written out rather than taken from `glob` or
    `pathlib.PurePath.full_match` so that the semantics this gate depends on are visible here and
    are not a property of the interpreter it happens to run under.
    """
    out, index = [], 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif char == "*":
            out.append("[^/]*")
            index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile("".join(out) + r"\Z")


def distribution_paths(paths: set[str], pyproject: bytes | None) -> set[str]:
    """Of `paths` (relative to `packages/cdm/`), those the built distribution would carry.

    The two halves setuptools has, as `tests/test_cdm_packaging.py::shippable` reads them —
    modules found by `packages.find`, and data matched by `package-data` minus
    `exclude-package-data` — plus `license-files` and `pyproject.toml` itself. The globs are read
    from the pyproject at THAT END of the arc rather than from today's: a revision declares what it
    ships, and using one end's rules on the other end's tree would misreport a change to the rules
    as a change to the contents.

    `pyproject.toml` is in scope because the sdist carries it and because it is where the floor,
    the dependencies and the entry points are declared — three of the table's own rows. It is not
    in the wheel, and entry 10's verification table names it "sdist only" for that reason.
    """
    if pyproject is None:
        return set()
    config = tomllib.loads(pyproject.decode())
    setuptools = config.get("tool", {}).get("setuptools", {})
    data = [_translate(p) for p in setuptools.get("package-data", {}).get(PKG, [])]
    skip = [_translate(p) for p in setuptools.get("exclude-package-data", {}).get(PKG, [])]
    licences = set(config.get("project", {}).get("license-files", []))

    keep = set()
    for path in paths:
        if path == "pyproject.toml" or path in licences:
            keep.add(path)
            continue
        if not path.startswith(f"{PKG}/"):
            continue
        inner = path[len(PKG) + 1:]
        # The module half: `.py` under the package, but not under `fixtures/`, which is not a
        # package and reaches the distribution through the data half instead.
        if inner.endswith(".py") and not inner.startswith("fixtures/"):
            keep.add(path)
            continue
        if any(g.match(inner) for g in data) and not any(g.match(inner) for g in skip):
            keep.add(path)
    return keep


def _blobs_at(rev: str) -> dict[str, bytes]:
    """Every tracked file under `packages/cdm/` at `rev`, through ONE `git cat-file --batch`.

    The first version of this ran `git show rev:path` per file. The distribution carries close to
    seven hundred, the suite reads a dozen snapshots, and a `pytest` run over this module took
    long enough to be killed — nine thousand processes to read one tree twelve times. So the
    object names come out of `ls-tree` and the contents out of a single batch, which is what
    `cat-file --batch` exists for. It is also a stronger read: the blob is fetched by its OBJECT
    NAME rather than by a `rev:path` string, so nothing depends on how a path with an odd
    character round-trips through a revision expression.
    """
    listing = _git("ls-tree", "-r", "-z", "--format=%(objectname) %(path)", rev, "--", DIST)
    if listing.returncode != 0:
        raise Finding(f"`git ls-tree {rev}` failed: "
                      f"{listing.stderr.decode(errors='replace')[:300]}")
    entries = []
    for line in listing.stdout.decode().split("\0"):
        if not line:
            continue
        oid, path = line.split(" ", 1)
        if path.startswith(f"{DIST}/"):
            entries.append((oid, path[len(DIST) + 1:]))
    if not entries:
        return {}

    batch = subprocess.run(["git", "cat-file", "--batch"], cwd=REPO,
                           input="\n".join(oid for oid, _ in entries).encode(),
                           capture_output=True, check=False)
    if batch.returncode != 0:
        raise Finding("`git cat-file --batch` failed: "
                      f"{batch.stderr.decode(errors='replace')[:300]}")

    out, cursor = {}, 0
    stream = batch.stdout
    for _, name in entries:
        end = stream.index(b"\n", cursor)
        header = stream[cursor:end].decode()
        size = int(header.split()[2])
        start = end + 1
        out[name] = stream[start:start + size]
        cursor = start + size + 1          # the trailing newline cat-file writes after each blob
    return out


def snapshot_at(rev: str | None) -> dict[str, bytes]:
    """The distribution's contents at `rev`, or in the working tree when `rev` is None.

    Keyed on the path relative to `packages/cdm/`, which is the distribution root — so a key is
    the name a file has INSIDE the sdist, and the classification below never has to strip a
    prefix it might strip differently in two places.
    """
    if rev is None:
        listed = _git_text("ls-files", "-z", "--", DIST).split("\0")
        names = {n[len(DIST) + 1:] for n in listed if n}
        held: dict[str, bytes] = {}
        for name in names:
            try:
                held[name] = (REPO / DIST / name).read_bytes()
            except OSError:
                continue
    else:
        held = _blobs_at(rev)
        names = set(held)

    wanted = distribution_paths(names, held.get("pyproject.toml"))
    return {name: held[name] for name in sorted(wanted) if name in held}


# -------------------------------------------------------------------------- reading the surface


def _parse(blob: bytes) -> ast.Module | None:
    try:
        return ast.parse(blob.decode())
    except (SyntaxError, UnicodeDecodeError):
        return None


def _strip_docstrings(node: ast.AST) -> None:
    """Delete docstring `Expr` nodes in place, everywhere they can occur.

    Comments never reach an AST, so this is the whole of "prose" for a Python file: what survives
    is the functional content, and a round that edits only comments and docstrings produces an
    identical dump. That is how the PATCH row's "a docstring" becomes mechanizable rather than a
    regex over `#`.
    """
    for holder in ast.walk(node):
        if not isinstance(holder, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                   ast.AsyncFunctionDef)):
            continue
        body = holder.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            holder.body = body[1:] or [ast.Pass()]


def _unit_name(stmt: ast.stmt) -> str | None:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return stmt.name
    if isinstance(stmt, ast.Assign):
        targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        return targets[0] if targets else None
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    return None


def functional_units(blob: bytes) -> dict[str, str] | None:
    """Top-level units of a module as `name -> functional dump`, docstrings and comments gone.

    Units without a name — an `if`, an import, a bare call — are keyed by their position and shape
    so that they still compare, and so that a residue in one of them is still reported as a unit
    rather than silently dropped.
    """
    tree = _parse(blob)
    if tree is None:
        return None
    _strip_docstrings(tree)
    units: dict[str, str] = {}
    for index, stmt in enumerate(tree.body):
        name = _unit_name(stmt)
        dump = ast.dump(stmt, annotate_fields=True, include_attributes=False)
        units[name if name else f"<statement {index}>"] = dump
    return units


def _public(name: str) -> bool:
    """A name a consumer can reach by `from synapse_cdm.x import name`.

    A leading underscore is the declaration that it cannot, and this repository honours it —
    `harness.py`'s six checks are all `_check_*`, and they are a surface through the CLI rather
    than through an import, which is why they get a signal of their own below.
    """
    return not name.startswith("_") and not name.startswith("<")


def _adapter_names(tree: ast.Module) -> set[str]:
    """`name = "…"` on classes that subclass something called `Adapter`, by AST and no import.

    Importing would be the more accurate reading and is not available: the arc's other end is a
    git revision, not an importable tree. The shape is uniform across the whole shipped roster —
    `class XAdapter(Adapter):` with `name = "…"` as a class attribute — and `adapter.py`'s
    `__init_subclass__` is what turns that literal into the registry key. **The roster is stated
    as no number here**, on rule 7 of the sweep protocol: this reading is compared against
    `adapter.roster()` by `test_the_gates_adapter_roster_is_the_registry`, so a count in this
    docstring would be a second statement of a fact one test already derives, and a second
    statement re-drifts where a citation cannot.
    """
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
        bases |= {b.attr for b in node.bases if isinstance(b, ast.Attribute)}
        if "Adapter" not in bases:
            continue
        for stmt in node.body:
            if (isinstance(stmt, ast.Assign) and _unit_name(stmt) == "name"
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)):
                found.add(stmt.value.value)
    return found


def _harness_flags(tree: ast.Module) -> set[str]:
    flags = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("-")):
            flags.add(node.args[0].value)
    return flags


def _harness_exit_codes(tree: ast.Module) -> set[str]:
    """Named `EXIT_*` constants and the literal `return`s of `main`.

    Both, because this harness spells its codes both ways: `EXIT_NO_FIXTURES = 2` at module level
    and bare `return 0` / `return 1` inside `main`. A gate that read only the constants would miss
    the removal of a code that never got a name.
    """
    codes = set()
    for stmt in tree.body:
        name = _unit_name(stmt)
        if name and name.startswith("EXIT_") and isinstance(stmt, ast.Assign) \
                and isinstance(stmt.value, ast.Constant):
            codes.add(f"{name}={stmt.value.value}")
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name == "main"):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return) or inner.value is None:
                continue
            # EVERY integer constant inside the returned EXPRESSION, not just a bare `return 2`.
            # The first version tested `isinstance(inner.value, ast.Constant)` and therefore read
            # `return 0` and missed `return 1 if report["failed"] else 0` — so exit code 1, the one
            # a caller checks for "some fixture failed", was not in the roster at all and removing
            # it would have moved nothing. Same class as the `_check_*` subset above, found by the
            # same sweep, and the reason both are now derived from the shape rather than the name.
            for leaf in ast.walk(inner.value):
                if isinstance(leaf, ast.Constant) and isinstance(leaf.value, int) \
                        and not isinstance(leaf.value, bool):
                    codes.add(f"return {leaf.value}")
    return codes


def _harness_checks(tree: ast.Module) -> set[str]:
    """The harness's check roster, read from `_COLUMNS` — NOT from the `_check_*` function names.

    THIS WAS `_check_*` AND IT WAS A SUBSET, found by the round's own roster sweep before the gate
    had ever been asked about a harness change. `harness.py` runs **six** checks and only three of
    them are functions named `_check_*`: `translate`, `lossless` and `golden` are inline in `run()`.
    So a gate reading the function names would hold a roster of three, and adding a seventh check
    inline would move nothing it can see — the exact shape of the defect
    `tests/test_cdm_gate_rosters.py` exists for, where a gate's written-down roster replayed a
    SUBSET of the adapter roster and reported the subset's own count as a pass.

    `_COLUMNS` is the right roster because it is the one the REPORT renders, so it is what a
    consumer of the harness actually receives, and `tests/test_cdm_harness.py` already holds it to
    `run()`'s own output — a check missing from `_COLUMNS` is invisible in the report and that test
    fails. Reading it here means this gate and that test share one definition of "a harness check"
    instead of having two.
    """
    for stmt in tree.body:
        if _unit_name(stmt) != "_COLUMNS" or not isinstance(stmt, ast.Assign):
            continue
        if isinstance(stmt.value, (ast.Tuple, ast.List)):
            return {e.value for e in stmt.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


@dataclasses.dataclass(frozen=True)
class Surface:
    """Everything the table's rows are about, read off one snapshot."""

    modules: dict[str, dict[str, str]]     # path -> functional units
    public: dict[str, set[str]]            # path -> public top-level names
    adapters: set[str]
    flags: set[str]
    exit_codes: set[str]
    checks: set[str]
    fixture_sets: set[str]
    schema_version: str | None
    python_floor: str | None
    optional_deps: set[str]
    required_deps: set[str]
    entry_points: set[str]


def read_surface(snapshot: dict[str, bytes]) -> Surface:
    modules, public = {}, {}
    adapters: set[str] = set()
    flags: set[str] = set()
    exits: set[str] = set()
    checks: set[str] = set()
    schema_version = None

    for path, blob in snapshot.items():
        if not path.endswith(".py"):
            continue
        units = functional_units(blob)
        if units is None:
            continue
        modules[path] = units
        public[path] = {n for n in units if _public(n)}
        tree = _parse(blob)
        adapters |= _adapter_names(tree)
        if path == f"{PKG}/harness.py":
            flags |= _harness_flags(tree)
            exits |= _harness_exit_codes(tree)
            checks |= _harness_checks(tree)
        if path == f"{PKG}/version.py":
            for stmt in tree.body:
                if (_unit_name(stmt) == "SCHEMA_VERSION" and isinstance(stmt, ast.Assign)
                        and isinstance(stmt.value, ast.Constant)):
                    schema_version = stmt.value.value

    fixture_sets = {path.split("/")[2] for path in snapshot
                    if path.startswith(f"{PKG}/fixtures/") and len(path.split("/")) > 3}

    floor = None
    optional: set[str] = set()
    required: set[str] = set()
    scripts: set[str] = set()
    if "pyproject.toml" in snapshot:
        config = tomllib.loads(snapshot["pyproject.toml"].decode())
        project = config.get("project", {})
        floor = project.get("requires-python")
        for extra, pins in project.get("optional-dependencies", {}).items():
            optional |= {f"{extra}:{p}" for p in pins}
        required = set(project.get("dependencies", []))
        scripts = set(project.get("scripts", {}))

    return Surface(modules=modules, public=public, adapters=adapters, flags=flags,
                   exit_codes=exits, checks=checks, fixture_sets=fixture_sets,
                   schema_version=schema_version, python_floor=floor,
                   optional_deps=optional, required_deps=required, entry_points=scripts)


# ----------------------------------------------------------------------------- the two readings
#
# THE RULE OF SHAPE, WRITTEN DOWN BECAUSE THE TABLE'S LISTS ARE NOT EXHAUSTIVE AND PRETENDING
# THEY ARE WOULD BE THE GUESS THIS GATE REFUSES TO MAKE.
#
# `version.py`'s MINOR row enumerates four things and its MAJOR row four more, and a diff produces
# cases neither list names — a console entry point, a required dependency, a fixture set that
# disappears. Two readings were available and only one of them is a reading:
#
#   * treat every unlisted case as PATCH, on the grounds that it is not in the MINOR or MAJOR
#     list. That is how 1.3.0's mirror image gets shipped: a distribution that dropped an entry
#     point numbered as a docstring fix.
#   * read the rows for their SHAPE, which both of them state plainly. MINOR is "… is added.
#     Existing code keeps working." MAJOR is "… is removed or its meaning changes."
#
# So: an unambiguous ADDITION of a declared surface is MINOR, an unambiguous REMOVAL is MAJOR, and
# a MODIFICATION IN PLACE of something whose meaning is the question is neither — it is the unruled
# case, and it goes to a human. That last clause is what stops the rule of shape from becoming a
# licence to classify anything: it only ever fires on a set membership changing, never on a body.
#
# The granularity is the table's own. It says "a fixture SET is added", so a fixture added inside
# an existing set is not that row — it is shipped evidence changing, which is the PATCH row, and
# the set appearing or disappearing is the MINOR/MAJOR event.


def _floor_number(spec: str | None) -> tuple[int, ...] | None:
    """`>=3.11` as `(3, 11)`. None when the spec is anything this gate should not interpret."""
    if not spec:
        return None
    found = re.fullmatch(r"\s*>=\s*(\d+(?:\.\d+)*)\s*", spec)
    return tuple(int(p) for p in found.group(1).split(".")) if found else None


def _classify_pyproject(before: bytes, after: bytes, derived: Derivation) -> None:
    """`pyproject.toml`, compared as a parsed mapping so a comment-only edit is invisible."""
    old, new = tomllib.loads(before.decode()), tomllib.loads(after.decode())
    if old == new:
        derived.signals.append(Signal(
            "PATCH", "pyproject.toml",
            "the parsed table is identical, so the edit is comments only — the PATCH row's "
            "'a docstring' one artefact along"))
        return

    old_project, new_project = old.get("project", {}), new.get("project", {})

    old_floor, new_floor = old_project.get("requires-python"), new_project.get("requires-python")
    if old_floor != new_floor:
        old_n, new_n = _floor_number(old_floor), _floor_number(new_floor)
        if old_n and new_n and new_n > old_n:
            derived.signals.append(Signal(
                "MAJOR", "pyproject.toml:requires-python",
                f"the Python floor rises from {old_floor!r} to {new_floor!r} — the MAJOR row "
                "names it in as many words"))
        elif old_n and new_n and new_n < old_n:
            derived.signals.append(Signal(
                "MINOR", "pyproject.toml:requires-python",
                f"the Python floor drops from {old_floor!r} to {new_floor!r}: interpreters are "
                "added and existing code keeps working, which is the MINOR row's shape"))
        else:
            derived.ambiguities.append(Ambiguity(
                "pyproject.toml:requires-python",
                f"the floor changes from {old_floor!r} to {new_floor!r} and this gate will not "
                "interpret a specifier it cannot order. Whether that raises the floor is the "
                "MAJOR row's own question and it needs a human"))

    for key, kind_added, kind_removed, what in (
            ("optional-dependencies", "MINOR", "MAJOR", "an optional dependency"),
            ("dependencies", "MINOR", "MAJOR", "a required dependency"),
            ("scripts", "MINOR", "MAJOR", "a console entry point")):
        if key == "optional-dependencies":
            old_set = {f"{e}:{p}" for e, ps in old_project.get(key, {}).items() for p in ps}
            new_set = {f"{e}:{p}" for e, ps in new_project.get(key, {}).items() for p in ps}
        elif key == "scripts":
            old_set, new_set = set(old_project.get(key, {})), set(new_project.get(key, {}))
        else:
            old_set, new_set = set(old_project.get(key, [])), set(new_project.get(key, []))
        added, removed = sorted(new_set - old_set), sorted(old_set - new_set)
        if added and removed:
            derived.ambiguities.append(Ambiguity(
                f"pyproject.toml:{key}",
                f"{what} is both added ({added}) and removed ({removed}) in one edit, which is a "
                "constraint moving in place rather than a set gaining or losing a member. "
                "Whether the new constraint breaks an existing install is the MAJOR row's "
                "'its meaning changes' and the diff does not answer it"))
            continue
        if added:
            derived.signals.append(Signal(kind_added, f"pyproject.toml:{key}",
                                          f"{what} is added: {added}"))
        if removed:
            derived.signals.append(Signal(kind_removed, f"pyproject.toml:{key}",
                                          f"{what} is removed: {removed}"))

    #: Keys whose movement states nothing about the Python surface. `tool` and `build-system`
    #: govern WHAT SHIPS, and a change there is deliberately PATCH here: its effect on the shipped
    #: set is measured by the file-level signals, which see files appear and disappear. A glob
    #: rewritten with no change to the set it matches really is a packaging edit and nothing else.
    prose = {"description", "keywords", "classifiers", "urls", "authors", "readme",
             "license", "license-files", "dynamic", "requires-python", "dependencies",
             "optional-dependencies", "scripts"}
    moved = {k for k in set(old_project) | set(new_project)
             if old_project.get(k) != new_project.get(k)} - prose
    for key in sorted(moved):
        if key == "name":
            derived.ambiguities.append(Ambiguity(
                "pyproject.toml:name",
                f"the distribution is renamed from {old_project.get(key)!r} to "
                f"{new_project.get(key)!r}. That is not a bump of this project at all — it is a "
                "different project on the index — and no row of the table reaches it"))
        else:
            derived.ambiguities.append(Ambiguity(
                f"pyproject.toml:{key}",
                f"`[project].{key}` moved and this gate has no reading for it. Add one "
                "deliberately or rule it, rather than letting an unrecognised metadata key set a "
                "version number by default"))
    for section in ("build-system", "tool"):
        if old.get(section) != new.get(section):
            derived.signals.append(Signal(
                "PATCH", f"pyproject.toml:{section}",
                f"`[{section}]` moved — a packaging rule. Its effect on the shipped SET is "
                "measured by the file signals, which see a file appear or disappear; a rule "
                "rewritten with no change to what it matches is a packaging edit and nothing more"))


#: Shipped bytes that carry no Python surface: the protocol documents, every fixture payload and
#: pin record, and the two licence files. Movement in any of them is the PATCH row.
def _is_document(path: str) -> bool:
    return (path.endswith(".md")
            or path.startswith(f"{PKG}/fixtures/")
            or path in ("LICENSE", "NOTICE"))


def derive(before: dict[str, bytes], after: dict[str, bytes]) -> Derivation:
    """What the arc between two snapshots proves, per the table and the rule of shape above."""
    derived = Derivation()
    old, new = read_surface(before), read_surface(after)

    for name in sorted(new.fixture_sets - old.fixture_sets):
        derived.signals.append(Signal("MINOR", f"{PKG}/fixtures/{name}",
                                      "a fixture set is added — the MINOR row, verbatim"))
    for name in sorted(old.fixture_sets - new.fixture_sets):
        derived.signals.append(Signal(
            "MAJOR", f"{PKG}/fixtures/{name}",
            "a fixture set is REMOVED. The MINOR row names its addition; a partner proving "
            "conformance against it loses the evidence, which is the MAJOR row's shape"))

    for path in sorted(set(before) | set(after)):
        old_blob, new_blob = before.get(path), after.get(path)
        if old_blob == new_blob:
            continue
        if path == "pyproject.toml":
            if old_blob is None or new_blob is None:
                derived.ambiguities.append(Ambiguity(
                    "pyproject.toml",
                    "the distribution's own metadata file appears or disappears across this arc. "
                    "That is not a bump, it is a distribution that did not exist or has stopped "
                    "existing, and no row reaches it"))
            else:
                _classify_pyproject(old_blob, new_blob, derived)
            continue
        if _is_document(path):
            fixture_set = path.split("/")[2] if path.startswith(f"{PKG}/fixtures/") else None
            if fixture_set and fixture_set in (new.fixture_sets ^ old.fixture_sets):
                continue          # already signalled as a set appearing or disappearing
            verb = "appears" if old_blob is None else "disappears" if new_blob is None else "moves"
            derived.signals.append(Signal(
                "PATCH", path,
                f"a shipped document or fixture payload {verb}: no importable name, no harness "
                "flag, no fixture set and no dependency, so the MINOR list does not reach it and "
                "the PATCH row does"))
            continue
        if path.endswith(".py"):
            _classify_module(path, old, new, derived,
                             had_before=old_blob is not None, had_after=new_blob is not None)
            continue
        derived.ambiguities.append(Ambiguity(
            path,
            "a shipped file this gate has no class for. Every path in the distribution is a "
            "module, a document, a fixture payload or the metadata; a fifth kind is a decision "
            "about what ships and it is not this gate's to make silently"))

    if old.schema_version != new.schema_version and None not in (old.schema_version,
                                                                 new.schema_version):
        derived.signals.append(Signal(
            "MINOR", f"{PKG}/version.py:SCHEMA_VERSION",
            f"SCHEMA_VERSION moves {old.schema_version} → {new.schema_version}. `version.py` "
            "states the consequence itself: a SCHEMA_VERSION bump is ALWAYS at least a package "
            "MINOR, because the objects this package emits change shape"))

    return derived


def _module_roster_moves(path: str, old: Surface, new: Surface) -> list[Signal]:
    """Roster changes attributable to `path`, strongest first. Empty means nothing explains a body.

    Attribution is by module, which is where this gate's honesty has a limit and the docstring says
    so: a roster move in `harness.py` explains a changed function in `harness.py`, and the gate
    does not additionally prove the roster move is the WHOLE of that function's change.
    """
    moves: list[Signal] = []
    if path == f"{PKG}/harness.py":
        for added, removed, what, word in (
                (new.flags - old.flags, old.flags - new.flags, "flag", "a harness flag"),
                (new.checks - old.checks, old.checks - new.checks, "check", "a harness check"),
                (new.exit_codes - old.exit_codes, old.exit_codes - new.exit_codes,
                 "exit code", "a harness exit code")):
            if added:
                moves.append(Signal("MINOR", f"{path}:{what}",
                                    f"{word} is added ({sorted(added)}) — the MINOR row, verbatim"))
            if removed:
                moves.append(Signal("MAJOR", f"{path}:{what}",
                                    f"{word} is removed ({sorted(removed)}) — the MAJOR row "
                                    "names a harness exit code or flag outright"))
    if path.startswith(f"{PKG}/adapters/"):
        added, removed = new.adapters - old.adapters, old.adapters - new.adapters
        if added:
            moves.append(Signal("MINOR", f"{path}:registry",
                                f"an adapter is added ({sorted(added)}) — the MINOR row, verbatim"))
        if removed:
            moves.append(Signal("MAJOR", f"{path}:registry",
                                f"an adapter is removed ({sorted(removed)}): an importable name "
                                "and a registry key both go, which is the MAJOR row"))
    return sorted(moves, key=lambda s: KINDS.index(s.kind), reverse=True)


def _classify_module(path: str, old: Surface, new: Surface, derived: Derivation,
                    had_before: bool, had_after: bool) -> None:
    """One shipped module, unit by unit. A changed body with no roster behind it is unruled.

    `had_before` / `had_after` say whether the FILE was in the distribution at each end, which is
    a different fact from whether it parsed — and conflating them was this gate's first defect,
    found by its own fixtures before it had ever run on the tree. A module that APPEARS has every
    unit added, which is the MINOR row when any of them is public; a module that fails to PARSE
    has no readable surface at all and is unruled. Reading `Surface.modules` alone cannot tell the
    two apart, so both fixtures that add an adapter came back UNRULED — a new adapter, refused as
    an unclassifiable syntax error.
    """
    before, after = old.modules.get(path), new.modules.get(path)
    if (had_before and before is None) or (had_after and after is None):
        derived.ambiguities.append(Ambiguity(
            path,
            "this module does not parse at one end of the arc, so its surface cannot be read and "
            "no classification of it means anything. Fix the parse, or the arc is not measurable"))
        return
    before, after = before or {}, after or {}
    if before == after:
        derived.signals.append(Signal(
            "PATCH", path,
            "the functional AST is unchanged, so the edit is comments and docstrings only — "
            "which is the PATCH row's 'a docstring', derived from the parse rather than from a "
            "line filter somebody has to keep correct"))
        return

    roster = _module_roster_moves(path, old, new)
    is_harness = path == f"{PKG}/harness.py"

    for unit in sorted(set(after) - set(before)):
        if is_harness and unit.startswith("_check_"):
            derived.signals.append(Signal("MINOR", f"{path}:{unit}",
                                          "a harness check is added — the MINOR row, verbatim"))
        elif _public(unit):
            derived.signals.append(Signal(
                "MINOR", f"{path}:{unit}",
                "a public top-level name appears, so an importable surface is added and existing "
                "code keeps working — the MINOR row's shape"))
        else:
            derived.signals.append(Signal(
                "PATCH", f"{path}:{unit}",
                "a private name appears. A leading underscore is the declaration that no "
                "consumer can reach it, so nothing importable changed"))

    for unit in sorted(set(before) - set(after)):
        if is_harness and unit.startswith("_check_"):
            derived.signals.append(Signal("MAJOR", f"{path}:{unit}",
                                          "a harness check is removed: the MINOR row names its "
                                          "addition, and a check that stops running is a verdict "
                                          "a consumer was relying on"))
        elif _public(unit):
            derived.signals.append(Signal(
                "MAJOR", f"{path}:{unit}",
                "a public top-level name is removed — the MAJOR row's first clause, verbatim"))
        else:
            derived.signals.append(Signal(
                "PATCH", f"{path}:{unit}",
                "a private name is removed; no consumer could reach it, so no surface moved"))

    for unit in sorted(set(before) & set(after)):
        if before[unit] == after[unit]:
            continue
        full = f"{path}:{unit}"
        if full == DECLARATION:
            continue              # the declaration under judgement; see the module docstring
        if path == f"{PKG}/version.py" and unit == "SCHEMA_VERSION":
            continue              # signalled once, from the surface, above
        if roster:
            explanation = roster[0]
            derived.signals.append(Signal(
                explanation.kind, full,
                f"changed on functional lines, and explained by a roster move in the same "
                f"module: {explanation.reason}"))
            continue
        derived.ambiguities.append(Ambiguity(
            full,
            "changed on functional lines with NO name added or removed and no roster behind it. "
            "The table reaches this unit twice and decides nothing: PATCH says 'a translation "
            "fix, a message, a docstring. No surface change', and MAJOR says 'an importable name "
            "is removed or its MEANING changes'. Whether the meaning changed is a claim about "
            "intent, which no diff carries. Rule it in MIGRATIONS.md — see RULING_MARKER"))


# --------------------------------------------------------------- the human's half, read not asked


def _section(text: str, heading: str) -> str | None:
    """One `### …` section of `MIGRATIONS.md`, by the prefix of its heading."""
    found = re.search(rf"^### {re.escape(heading)}.*$", text, re.M)
    if not found:
        return None
    rest = text[found.end():]
    nxt = re.search(r"\n#{2,3} ", rest)
    return rest[:nxt.start()] if nxt else rest


def rulings(heading: str) -> dict[str, str]:
    """`unit -> KIND` from the `**Bump ruling.**` paragraphs of one MIGRATIONS.md section.

    The section is the one describing the arc: `### Unreleased` while the arc ends in the working
    tree, and `### <version>` once a release has absorbed it. So a ruling travels with the entry it
    was written for and is dated by it, rather than accumulating in a file of exemptions nobody
    re-reads — which is entry 5's rule about records that quietly update their own history.
    """
    if not MIGRATIONS.exists():
        return {}
    section = _section(MIGRATIONS.read_text(), heading)
    if not section:
        return {}
    found: dict[str, str] = {}
    for start in [m.start() for m in re.finditer(re.escape(RULING_MARKER), section)]:
        paragraph = section[start:].split("\n\n", 1)[0]
        for line in RULING_LINE.finditer(paragraph):
            found[line.group("unit")] = line.group("kind").upper()
    return found


def apply_rulings(derived: Derivation, heading: str) -> tuple[Derivation, dict[str, str]]:
    """Fold recorded rulings into a derivation. Both directions, and the second one matters.

    A ruling that names a unit this arc does not find ambiguous is REFUSED as stale — the same
    treatment `tests/test_cdm_prose_counts.py` gives an exhibit whose repair was reverted. An
    exemption outliving the case it was written for is how a gate turns into a list of things
    nobody re-derives.
    """
    ruled = rulings(heading)
    ambiguous = {a.unit for a in derived.ambiguities}
    stale = sorted(set(ruled) - ambiguous)
    if stale:
        raise Finding(
            f"MIGRATIONS.md's `### {heading}` section carries {len(stale)} bump ruling(s) for "
            f"unit(s) this arc does not find ambiguous: {stale}.\n"
            "  Either the unit stopped changing — in which case the ruling is an exemption for a "
            "case that no longer exists and goes with the prose — or this gate learned to "
            "classify it, in which case the ruling is now a second opinion on a decided question. "
            "A ruling nobody re-derives is the habit this gate was written to replace."
        )
    kept = Derivation(signals=list(derived.signals), ambiguities=[])
    for ambiguity in derived.ambiguities:
        if ambiguity.unit in ruled:
            kept.signals.append(Signal(
                ruled[ambiguity.unit], ambiguity.unit,
                f"UNRULED by the table and ruled {ruled[ambiguity.unit]} by a person, recorded in "
                f"MIGRATIONS.md's `### {heading}` section"))
        else:
            kept.ambiguities.append(ambiguity)
    return kept, ruled


# ------------------------------------------------------------------------------ which arc, and why


def parse_version(text: str) -> tuple[int, int, int]:
    major, minor, patch = (int(p) for p in text.split("."))
    return major, minor, patch


def release_tags() -> dict[tuple[int, int, int], str]:
    out = {}
    for line in _git_text("tag", "-l").split():
        found = re.fullmatch(r"v(\d+\.\d+\.\d+)", line)
        if found:
            out[parse_version(found.group(1))] = line
    return out


def declared_version() -> str:
    """`PACKAGE_VERSION`, read out of the file's own assignment rather than by importing it.

    Read the same way at both ends of every arc, so the number under judgement and the numbers in
    history are obtained by one method. Importing would work here and would be a second method.
    """
    source = (REPO / DIST / PKG / "version.py").read_bytes()
    for stmt in _parse(source).body:
        if (_unit_name(stmt) == "PACKAGE_VERSION" and isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Constant)):
            return stmt.value.value
    raise Finding(f"{PKG}/version.py carries no PACKAGE_VERSION assignment")


def single_step(base: tuple[int, int, int], declared: tuple[int, int, int]) -> str:
    """The bump kind from `base` to `declared`, or a refusal if it is not one step of semver.

    Refused rather than approximated: `1.2.0 → 1.4.0` is two minors, and calling it "a MINOR" would
    let a release skip a number while passing a gate about numbers. Nothing in this repository's
    history does it and the check is here because the reason it has not happened is that four
    releases were typed carefully.
    """
    bmaj, bmin, bpatch = base
    if declared == (bmaj, bmin, bpatch + 1):
        return "PATCH"
    if declared == (bmaj, bmin + 1, 0):
        return "MINOR"
    if declared == (bmaj + 1, 0, 0):
        return "MAJOR"
    raise Finding(
        f"{'.'.join(map(str, declared))} is not one semver step from the previous release "
        f"{'.'.join(map(str, base))}. A bump kind is what this gate compares, and a jump of more "
        "than one step in any component is not a kind — it is a number nobody can classify. The "
        "three legal successors are "
        f"{bmaj}.{bmin}.{bpatch + 1}, {bmaj}.{bmin + 1}.0 and {bmaj + 1}.0.0"
    )


@dataclasses.dataclass
class Verdict:
    """The whole measurement, for a round to quote and for the suite to assert on."""

    declared: str
    base_tag: str
    judged_end: str
    declared_kind: str
    derived_kind: str
    signals: list[Signal]
    ambiguities: list[Ambiguity]
    ruled: dict[str, str]
    pending_kind: str | None
    pending_number: str | None
    pending_ambiguities: list[Ambiguity]

    def as_dict(self) -> dict:
        return {
            "declared": self.declared,
            "arc": {"from": self.base_tag, "to": self.judged_end},
            "declared_kind": self.declared_kind,
            "derived_kind": self.derived_kind,
            "signals": [dataclasses.asdict(s) for s in self.signals],
            "ruled": self.ruled,
            "pending": {"kind": self.pending_kind, "number": self.pending_number,
                        "unruled": [a.unit for a in self.pending_ambiguities]},
        }


def _successor(base: tuple[int, int, int], kind: str) -> str:
    major, minor, patch = base
    return {"NONE": f"{major}.{minor}.{patch}",
            "PATCH": f"{major}.{minor}.{patch + 1}",
            "MINOR": f"{major}.{minor + 1}.0",
            "MAJOR": f"{major + 1}.0.0"}[kind]



def refuse_unless_clean(derived: Derivation, base: tuple[int, int, int], base_tag: str,
                        judged_end: str, declared: str, declared_kind: str, heading: str) -> None:
    """The three refusals, in one place so a fixture meets the same sentences a release would.

    `--mutation-check` calls this with synthetic arcs. If the messages lived inside `measure()` the
    fixtures would be proving that *some* refusal happens rather than that THE refusal happens, and
    the two texts would be two sites to keep in agreement — which is the defect the round behind
    this gate spent itself on.
    """
    if derived.ambiguities:
        lines = [f"    {a.unit}\n        {a.reason}" for a in derived.ambiguities]
        raise Finding(
            f"UNRULED — {len(derived.ambiguities)} changed unit(s) between {base_tag} and "
            f"{judged_end} that {PKG}/version.py's table does not decide:\n"
            + "\n".join(lines) + "\n"
            f"  No bump kind is derivable while any of these stands, so {declared} is neither "
            "confirmed nor refused — it is UNCHECKED, which is the state this gate exists to end.\n"
            f"  Rule each one in MIGRATIONS.md's `### {heading}` section, as:\n"
            f"      {RULING_MARKER} `<unit>` — PATCH: <why>.\n"
            "  A ruling is a person's, deliberately: 'the meaning changed' is a claim about intent "
            "and no diff carries it. It is dated by the entry it sits in, and this gate refuses a "
            "ruling that outlives its case."
        )

    if declared_kind != derived.floor:
        direction = ("EXCEED" if KINDS.index(declared_kind) > KINDS.index(derived.floor)
                     else "UNDERSHOOT")
        evidence = ("\n".join(f"    {s.kind:<6} {s.unit}\n        {s.reason}"
                              for s in derived.strongest())
                    or "    (no file in the distribution changed across this arc at all)")
        story = {
            "EXCEED":
                f"{declared} asserts a {declared_kind} to every consumer who reads the number, "
                f"and the diff over the distribution proves only {derived.floor}. THIS IS THE "
                "DEFECT THIS GATE WAS WRITTEN FOR: the 1.2.1 round was specified as 1.3.0 over an "
                "arc that changed no executable line, and every check in this repository would "
                "have passed it. A PyPI filename is permanent — this is the one claim in a "
                "release that can never be corrected.",
            "UNDERSHOOT":
                f"the diff proves {derived.floor} and {declared} is only a {declared_kind}, so "
                "the distribution would ship a surface its own number denies. A consumer pinning "
                f"~={declared} gets the new surface without asking for it, and one reading the "
                "number is told nothing was added.",
        }[direction]
        raise Finding(
            f"{direction} — {PACKAGE_LABEL} says {declared}; the arc {base_tag} → {judged_end} "
            f"derives {derived.floor}.\n"
            f"  declared  {declared_kind}  ({base_tag[1:]} → {declared})\n"
            f"  derived   {derived.floor}\n"
            f"  the strongest evidence, which is what sets the floor:\n{evidence}\n"
            f"  {story}\n"
            f"  The number this arc supports is {_successor(base, derived.floor)}."
        )


def measure() -> Verdict:
    """The judged arc, refused where it must be; and the pending arc, reported."""
    declared = declared_version()
    version = parse_version(declared)
    tags = release_tags()
    earlier = sorted(v for v in tags if v < version)
    if not earlier:
        raise Finding(
            f"there is no release tag earlier than {declared}, so there is no arc to classify. "
            "The first release has nothing to be a bump FROM — its number is a ruling (see "
            f"{PKG}/version.py's 'WHERE 1.0.0 CAME FROM'), not a derivation, and this gate has "
            "nothing to say about it"
        )
    base = earlier[-1]
    base_tag = tags[base]
    released = tags.get(version)

    judged_end = released if released else "the working tree"
    heading = declared if released else "Unreleased"
    derived = derive(snapshot_at(base_tag), snapshot_at(released))
    derived, ruled = apply_rulings(derived, heading)

    pending_kind = pending_number = None
    pending_ambiguities: list[Ambiguity] = []
    if released:
        pending = derive(snapshot_at(released), snapshot_at(None))
        pending, _ = apply_rulings(pending, "Unreleased")
        pending_kind = pending.floor
        pending_number = _successor(version, pending_kind)
        pending_ambiguities = pending.ambiguities

    declared_kind = single_step(base, version)
    verdict = Verdict(
        declared=declared, base_tag=base_tag, judged_end=judged_end,
        declared_kind=declared_kind, derived_kind=derived.floor,
        signals=derived.signals, ambiguities=derived.ambiguities, ruled=ruled,
        pending_kind=pending_kind, pending_number=pending_number,
        pending_ambiguities=pending_ambiguities)

    refuse_unless_clean(derived, base, base_tag, judged_end, declared,
                        declared_kind, heading)

    return verdict


PACKAGE_LABEL = f"{PKG}/version.py's PACKAGE_VERSION"


# ---------------------------------------------------------------------- fixtures, and both directions
#
# THE FIXTURES ARE SYNTHETIC DISTRIBUTIONS AND NOT THIS REPOSITORY'S HISTORY, DELIBERATELY.
#
# The arc that motivated this gate is `v1.2.0 → v1.2.1` and it is in the history, so a mutation
# check could have replayed it with the number changed to 1.3.0. It does not, for two reasons. A
# replay proves the gate refuses ONE arc, and rewriting a real arc's declared number means writing
# a number the tree never carried and then asserting about it — a fixture pretending to be
# provenance. These four are the smallest trees that exhibit each case, they say what they are, and
# the fifth check is the one that keeps the other four honest: a correct arc must PASS.
#
# The real `v1.2.0 → v1.2.1` arc is asserted on separately and for real, in
# `tests/test_cdm_bump_derivation.py`, against the tags themselves.

_PYPROJECT = b'''# a comment, which is the point of two of the fixtures below
[project]
name = "synapse-cdm"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.6"]
[project.optional-dependencies]
test = ["pytest>=8.0"]
[project.scripts]
cdm-harness = "synapse_cdm.harness:main"
'''


def _adapter(class_name: str, wire_name: str) -> bytes:
    return (f'"""A fixture adapter."""\n\n\nclass {class_name}(Adapter):\n'
            f'    name = "{wire_name}"\n    version = "1.0.0"\n').encode()


#: name, before, after, base, declared, expected — where expected is the refusal's first word, or
#: None for the arcs that must pass.
FIXTURES: tuple[tuple[str, dict[str, bytes], dict[str, bytes],
                      tuple[int, int, int], str, str | None], ...] = (
    (
        "a MINOR arc numbered PATCH — an adapter added and the number moved by one patch",
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/adapters/tak.py": _adapter("TakAdapter", "tak")},
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/adapters/tak.py": _adapter("TakAdapter", "tak"),
         f"{PKG}/adapters/newfmt.py": _adapter("NewfmtAdapter", "newfmt")},
        (1, 0, 0), "1.0.1", "UNDERSHOOT",
    ),
    (
        "a PATCH arc numbered MINOR — comments and a shipped document, and nothing else. "
        "THIS IS THE ARC THAT JUST HAPPENED, in its smallest form",
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/adapter.py": b'"""The SDK."""\n\n\n# a comment\ndef discover():\n'
                              b'    return REGISTRY\n',
         f"{PKG}/MIGRATIONS.md": b"# History\n\na shipped document, before\n"},
        {"pyproject.toml": _PYPROJECT.replace(b"which is the point", b"which is still the point"),
         f"{PKG}/adapter.py": b'"""The SDK, restated."""\n\n\n# the same comment, reworded\ndef discover():\n'
                              b'    return REGISTRY\n',
         f"{PKG}/MIGRATIONS.md": b"# History\n\na shipped document, after\n"},
        (1, 2, 0), "1.3.0", "EXCEED",
    ),
    (
        "an unruled arc — a function body moved with no name added, removed or rostered",
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/adapter.py": b'def translate(value):\n    return value + 1\n'},
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/adapter.py": b'def translate(value):\n    return value + 2\n'},
        (1, 2, 0), "1.2.1", "UNRULED",
    ),
    (
        "a PATCH arc numbered PATCH — the arc this repository actually shipped, in miniature",
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/MIGRATIONS.md": b"# History\n\na shipped document, before\n"},
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/MIGRATIONS.md": b"# History\n\na shipped document, after\n"},
        (1, 2, 0), "1.2.1", None,
    ),
    (
        "a MINOR arc numbered MINOR — an adapter added and the number moved by one minor",
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/adapters/tak.py": _adapter("TakAdapter", "tak")},
        {"pyproject.toml": _PYPROJECT,
         f"{PKG}/adapters/tak.py": _adapter("TakAdapter", "tak"),
         f"{PKG}/adapters/newfmt.py": _adapter("NewfmtAdapter", "newfmt")},
        (1, 2, 0), "1.3.0", None,
    ),
)


def run_fixture(before: dict[str, bytes], after: dict[str, bytes],
                base: tuple[int, int, int], declared: str) -> str | None:
    """Judge one synthetic arc. Returns the refusal's first word, or None when it passes.

    Rulings are NOT read here: `MIGRATIONS.md` describes this repository's arcs and a fixture that
    could be silenced by a ruling written for the real tree would be a fixture that stops
    witnessing anything the day somebody rules on an unrelated unit.
    """
    derived = derive(before, after)
    version = parse_version(declared)
    try:
        refuse_unless_clean(derived, base, f"v{'.'.join(map(str, base))}", "the working tree",
                            declared, single_step(base, version), "Unreleased")
    except Finding as finding:
        return str(finding).split(maxsplit=1)[0]
    return None


def pending_summary(declared: str, kind: str, number: str, unruled: int) -> str:
    """The `pending` line of the human summary, as one string, so a check can read it.

    **IT PRINTS THE UNRULED COUNT BESIDE THE KIND, and the console said less than the JSON until
    2026-09-05.** `measure()` derives the pending arc and only reports it, so `refuse_unless_clean`
    — which runs on the JUDGED arc — never sees a pending ambiguity and the exit code stays `0`.
    The units were always printed, indented under this line, and the 1.6.0 release round's first
    issue read the clean exit code as a statement about them and skimmed past the indented block.
    The JSON never hid them: `pending.unruled` carried every one. So the fix is not a new refusal,
    which would fire on an arc nobody is releasing; it is that this line now says HOW MANY, in the
    place a reader is already looking, and the two routes read the same.

    Separated from `main()` because a line nothing can render twice is a line nothing can check —
    `summary_check()` renders it over synthetic verdicts and proves the count is not a constant.
    """
    return (f"pending       the arc since {declared} derives {kind} with {unruled} unruled, "
            f"so the next release is at least {number}")


#: What `summary_check()` renders: `(name, unruled_count, what the line must carry)`. The empty
#: case and a populated one, because a renderer that hard-codes either reads correctly on the other
#: half of its input and this gate's whole subject is a figure that was right by accident.
SUMMARY_FIXTURES = (
    ("a pending arc with nothing left to rule", 0, "with 0 unruled"),
    ("a pending arc the table refuses to decide", 3, "with 3 unruled"),
)


def summary_check() -> int:
    """Prove the human summary's unruled count is read from the arc and not written into the line.

    Both directions, for the reason `mutation_check()` runs both: a line that prints `0 unruled`
    unconditionally passes the empty case, and the empty case is the one every clean release round
    sees.
    """
    failed = 0
    for name, unruled, needle in SUMMARY_FIXTURES:
        line = pending_summary("1.0.0", "NONE", "1.0.0", unruled)
        if needle in line:
            print(f"summary   {needle:<10} {name}")
        else:
            failed += 1
            print(f"FAIL      expected {needle!r} in the pending line, got {line!r}: {name}",
                  file=sys.stderr)
    if failed:
        print(f"FAIL  the human summary did not state the unruled count as measured, so the "
              f"console reading of a pending arc proves nothing", file=sys.stderr)
    return 1 if failed else 0


def mutation_check() -> int:
    """Every fixture, both directions. A gate nobody has seen fail is a gate nobody has seen."""
    failed = summary_check()
    for name, before, after, base, declared, expected in FIXTURES:
        got = run_fixture(before, after, base, declared)
        want = expected or "PASS"
        have = got or "PASS"
        if have == want:
            print(f"mutation  {want:<10} {name}")
        else:
            failed += 1
            print(f"FAIL      expected {want}, got {have}: {name}", file=sys.stderr)
    if failed:
        print(f"FAIL  {failed} fixture(s) did not behave as specified, so the verdict this gate "
              "reports on the real arc proves nothing", file=sys.stderr)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the measurement as JSON")
    parser.add_argument("--mutation-check", action="store_true",
                        help="prove both refusal directions and the unruled case, on fixtures")
    args = parser.parse_args(argv)

    if args.mutation_check and mutation_check() != 0:
        return 1

    try:
        verdict = measure()
    except Finding as finding:
        print(f"FAIL  {finding}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(verdict.as_dict(), indent=2))
        return 0

    print(f"declared      {verdict.declared} — a {verdict.declared_kind} over "
          f"{verdict.base_tag}")
    print(f"derived       {verdict.derived_kind}, from the diff over the distribution between "
          f"{verdict.base_tag} and {verdict.judged_end}")
    for signal in verdict.signals:
        if signal.kind == verdict.derived_kind:
            print(f"              {signal.kind:<6} {signal.unit}")
    if verdict.ruled:
        print(f"ruled         {len(verdict.ruled)} unit(s) ruled by a person: "
              f"{sorted(verdict.ruled)}")
    if verdict.pending_kind is not None:
        print(pending_summary(verdict.declared, verdict.pending_kind, verdict.pending_number,
                              len(verdict.pending_ambiguities)))
        for ambiguity in verdict.pending_ambiguities:
            print(f"              UNRULED  {ambiguity.unit}")
    print("1 check, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
