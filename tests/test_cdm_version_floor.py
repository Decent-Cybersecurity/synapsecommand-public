"""The declared Python floor, asserted rather than declared.

WHY THIS EXISTS
---------------
`packages/cdm/pyproject.toml` declares ``requires-python = ">=3.11"``. Nothing checked it, so it
went stale the way unchecked declarations do: `adapters/legion.py` acquired a **PEP 701** f-string —
a replacement field spanning a newline — which is 3.12 grammar. Under a real 3.11 interpreter the
package did not *compile*, let alone run: one of 28 package files raised
``SyntaxError: unterminated string literal``, and the two test modules whose import chain reaches
that adapter could not be collected. A floor that the code does not meet is not a floor; it is a
sentence in a metadata file.

The repair was one expression hoisted out of an f-string, and the floor was NOT raised. That choice
is the reason this module exists: the package was otherwise 3.11-clean — 27 of 28 files and all 22
test modules compiled — so moving the declaration to dodge a one-line fix would have made the
declaration mean nothing at all.

WHAT THIS GATE CHECKS, AND THE LIMIT IT DOES NOT PRETEND TO EXCEED
------------------------------------------------------------------
**It asserts PARSEABILITY at the declared floor, and nothing more.** `ast.parse`'s
``feature_version`` and the scanner below both work on grammar. Neither knows anything about
runtime API availability: a module calling ``itertools.batched`` (3.12) parses cleanly at
``feature_version=(3, 11)`` and raises `AttributeError` on a 3.11 interpreter. This gate would pass
it. That limitation is real, it is not repaired here, and the honest mitigation is the corroboration
pass at the bottom — when a real floor interpreter is on this machine the files are compiled with
it, which still only covers syntax, and a full import would cover the rest but needs the
dependency tree installed for that version.

``feature_version`` IS NOT SUFFICIENT ON ITS OWN, AND THAT IS THE POINT OF THE SECOND SCANNER
----------------------------------------------------------------------------------------------
This was measured, not assumed, and it inverts the obvious design. ``ast.parse`` with
``feature_version=(3, 11)`` **accepts** every one of the PEP 701 constructs, including the exact
line that broke the build:

    ast.parse('''x = f"crs {'a' if c else 'b'\\n  'c'}"''', feature_version=(3, 11))   # PASSES

``feature_version`` gates the *parser*'s version-conditional productions — the walrus operator,
`match`, and so on, all of which it rejects correctly — but PEP 701 moved f-string handling into
the **tokenizer**, and the tokenizer is not versioned by that flag. So a gate built only on
``feature_version`` would have passed on the defect it was written for. Both checks run:

* ``feature_version`` catches versioned grammar (`match` before 3.10, walrus before 3.8, PEP 695
  generics before 3.12, the `type` alias statement before 3.12);
* `_pep701_violations` catches the three f-string relaxations 3.12 introduced, each of which was
  confirmed against a real 3.11 interpreter rather than taken from the PEP:

  ==============================================  ===============================================
  construct                                       what real 3.11 says
  ==============================================  ===============================================
  same quote reused inside a replacement field    ``SyntaxError: f-string: expecting '}'``
  a replacement field spanning a newline          ``SyntaxError: unterminated string literal``
  a backslash inside a replacement field          ``SyntaxError: f-string expression part cannot
                                                  include a backslash``
  ==============================================  ===============================================

  and three near-misses that are LEGAL at 3.11 and must not be flagged: single quotes inside a
  double-quoted f-string, a triple-quoted f-string spanning lines, and a nested f-string using the
  *other* quote character.

THE FLOOR IS READ, NEVER TYPED
------------------------------
`FLOOR` comes from `requires-python` in `pyproject.toml`. If the declaration moves, this gate moves
with it and the whole suite is re-checked against the new number — which is the property that makes
"raise the floor" a visible act rather than a quiet one. A `requires-python` this module cannot
interpret is a **failure and never a skip**: a gate that silently stops checking when its input
changes shape is worse than no gate, because the build stays green.

CLOSURE, BOTH DIRECTIONS
------------------------
The pin gate's property, applied to a file set. Every Python file under the package and under
`tests/` is parsed, and — the direction that catches the real mistake — a repo-wide sweep asserts
that no Python file exists anywhere that this gate does not reach. A gate over a list is a gate over
whatever somebody remembered to add to the list.
"""
import ast
import io
import pathlib
import re
import subprocess
import tokenize
import tomllib

import pytest

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
PYPROJECT = REPO / "packages" / "cdm" / "pyproject.toml"

#: Directories a repo-wide Python sweep must not descend into. Each is a third party's tree or a
#: build artefact, and none of them is this package's code.
#:
#: PINNED BY A TEST, because this one set is applied to BOTH halves of the closure — discovery and
#: the repo-wide sweep — so adding a real directory to it hides those files from the check AND
#: from the check that the check is complete. Mutation found exactly that: adding `"adapters"`
#: here removed nine files from the gate and the closure test could not see them go, because it
#: was filtering by the same set. Widening it is now a deliberate act that fails until stated.
NOT_OURS = {".venv", "venv", "node_modules", "__pycache__", ".git", "build", "dist",
            ".pytest_cache", ".wrangler", ".docusaurus"}


# --------------------------------------------------------------------- the floor, read not typed

def read_floor() -> tuple[int, int]:
    """`(3, 11)` from ``requires-python = ">=3.11"``, or a loud failure.

    Deliberately narrow. Only the form this repository actually declares is accepted, because a
    permissive parser here would quietly turn `">=3.11,<4"` — or a typo — into some other floor and
    keep the build green while checking the wrong grammar. Widening it is a deliberate act, and the
    failure message says so.
    """
    assert PYPROJECT.exists(), f"{PYPROJECT} is missing; the floor has no declaration to read"
    data = tomllib.loads(PYPROJECT.read_text())
    declared = data.get("project", {}).get("requires-python")
    assert declared, (
        f"{PYPROJECT.relative_to(REPO)} declares no `requires-python` under [project]. This gate "
        "reads the floor from the declaration and has nothing to read"
    )
    match = re.fullmatch(r">=\s*(\d+)\.(\d+)", declared.strip())
    assert match, (
        f"`requires-python = {declared!r}` is not a form this gate can interpret. It reads exactly "
        '`">=X.Y"`, which is what this repository declares.\n'
        "This is a FAILURE and not a skip on purpose: a gate that stops checking when its input "
        "changes shape leaves the build green over an unchecked tree, which is the state this "
        "module was written to end. Widen `read_floor()` deliberately, and say in the same commit "
        "which forms it now accepts."
    )
    return int(match.group(1)), int(match.group(2))


FLOOR = read_floor()
FLOOR_STR = f"{FLOOR[0]}.{FLOOR[1]}"


def test_the_floor_was_read_from_the_declaration_and_is_plausible():
    """A floor of `(0, 0)` would make every check below vacuous, and so would one from memory."""
    assert FLOOR >= (3, 8), f"the declared floor {FLOOR_STR} predates every construct this gate knows"
    assert FLOOR <= (3, 20), f"the declared floor {FLOOR_STR} is not a released Python"
    # And it really came from the file. A hard-coded constant would satisfy every other test here.
    raw = PYPROJECT.read_text()
    assert f'requires-python = ">={FLOOR_STR}"' in raw, (
        f"the floor this gate is using ({FLOOR_STR}) is not the string in "
        f"{PYPROJECT.relative_to(REPO)}. Either `read_floor()` has stopped reading the declaration "
        "or somebody typed the version into this module"
    )


def test_the_exclusion_set_has_not_been_widened_to_hide_a_real_directory():
    """AN ABSENCE, and the one mutation found by NOT finding anything.

    `NOT_OURS` filters discovery AND the repo-wide closure sweep, so a name added to it disappears
    from both — the files stop being parsed and the check that every file is parsed stops being
    able to notice. Adding `"adapters"` removed nine modules from the gate and nothing failed.

    So the set is pinned. Every member is a third party's tree or a build artefact and none is a
    directory this repository writes Python into; anything else belongs in a per-file exemption
    with a reason beside it, not in a directory name that silently takes its neighbours with it.
    """
    assert NOT_OURS == {".venv", "venv", "node_modules", "__pycache__", ".git", "build", "dist",
                        ".pytest_cache", ".wrangler", ".docusaurus"}, (
        f"the Python-file exclusion set changed to {sorted(NOT_OURS)}. It is applied to both "
        "halves of the closure, so widening it hides files from the gate and from the check that "
        "the gate is complete. If a directory genuinely must be exempt, say which and why in the "
        "same commit that updates this assertion"
    )


def test_the_declared_floor_is_still_the_one_this_round_ruled_for():
    """AN ABSENCE about a POLICY rather than about the code, and it is permitted to change.

    The gate above asserts the tree meets whatever floor is declared, which is the right job for
    it — and it means raising the declaration is a way to make the gate pass. That is legitimate:
    a floor should be raisable. It is also exactly the move this round rejected. `adapters/legion.py`
    had acquired one 3.12 construct in an otherwise 3.11-clean package — 27 of 28 files and all 22
    test modules already compiled at 3.11 — so raising `requires-python` to dodge a one-line repair
    would have abandoned a floor the code very nearly met, and made the declaration decorative.

    This fails if the number moves. It is not a veto: it is the requirement that the move be
    deliberate and be stated, the same shape as the reserved-ordinal rule's "update this test
    deliberately". A round that has a real reason — a dependency dropping 3.11, a construct worth
    more than the workaround — edits this assertion and says so in its commit message.
    """
    assert FLOOR == (3, 11), (
        f"`requires-python` now declares {FLOOR_STR} and this round ruled for 3.11. Raising the "
        "floor is allowed and must be deliberate: state what forced it, confirm it is not being "
        "raised to make a 3.12 construct legal that could have been rewritten, and update this "
        "assertion in the same commit"
    )


# ------------------------------------------------------------------------------ file discovery

def discover() -> list[pathlib.Path]:
    """Every Python file this gate parses: the package and the test suite."""
    out = []
    for root in (PKG, REPO / "tests"):
        for path in sorted(root.rglob("*.py")):
            if NOT_OURS & set(path.parts):
                continue
            out.append(path)
    return out


FILES = discover()


def test_the_discovery_found_the_tree_and_not_a_corner_of_it():
    assert len(FILES) >= 45, (
        f"discovery found only {len(FILES)} Python files. The package alone holds 28 and the "
        "suite holds more than 20, so the walk has stopped descending"
    )


def test_no_python_file_in_this_repository_escapes_the_gate():
    """CLOSURE, and it is the direction that catches the real mistake.

    Parsing a list is easy; the failure is a file nobody put on the list. So the list is checked
    against the repository rather than trusted — every `*.py` outside a third party's tree must be
    one this gate parses. A new top-level `scripts/` holding a Python file fails here, which is the
    moment to decide whether it belongs in the floor or outside it.
    """
    reachable = {p.resolve() for p in FILES}
    stray = []
    for path in REPO.rglob("*.py"):
        if NOT_OURS & set(path.parts):
            continue
        if path.resolve() not in reachable:
            stray.append(str(path.relative_to(REPO)))
    assert not stray, (
        f"these Python files exist and this gate does not parse them: {sorted(stray)}. Either add "
        "their root to `discover()` — and say why they are in scope for the floor — or add their "
        "directory to NOT_OURS with the reason. A gate over a list is a gate over whatever "
        "somebody remembered to add to the list"
    )


# ----------------------------------------------------------- PEP 701, which feature_version misses

def _pep701_violations(source: str, filename: str) -> list[str]:
    """The three f-string relaxations 3.12 introduced, found at the TOKEN level.

    Token-level rather than AST-level because by the time an f-string is an AST node its quoting is
    gone — `ast` records the expression, not how it was delimited — and quoting is the entire
    question. Returns a list of human-readable findings, each with a line number.

    Only called when the floor is below 3.12. Above it these constructs are legal and the scanner
    would be reporting correct code.
    """
    findings: list[str] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        # The file does not tokenize on THIS interpreter, which is a different and louder problem
        # than the one this scanner is for. `test_every_file_parses_at_the_declared_floor` reports
        # it with the real message; returning nothing here avoids a confusing second failure.
        return findings

    fstring_start = getattr(tokenize, "FSTRING_START", None)
    if fstring_start is None:                       # pragma: no cover - only on 3.11 itself
        # Running ON the floor: the interpreter's own tokenizer already rejects these, so a file
        # that got this far has nothing for this scanner to find.
        return findings
    fstring_middle, fstring_end = tokenize.FSTRING_MIDDLE, tokenize.FSTRING_END

    for index, token in enumerate(tokens):
        if token.type != fstring_start:
            continue
        quote = token.string[len(token.string.rstrip('"\'')):]
        depth, end_index = 0, None
        for j in range(index, len(tokens)):
            if tokens[j].type == fstring_start:
                depth += 1
            elif tokens[j].type == fstring_end:
                depth -= 1
                if depth == 0:
                    end_index = j
                    break
        if end_index is None:
            continue
        end = tokens[end_index]
        inner = tokens[index + 1:end_index]
        line = token.start[0]

        # (1) A replacement field spanning a newline. Legal inside a TRIPLE-quoted f-string at
        #     3.11, which is why the quote length is part of the test rather than the line span
        #     alone — `f"""...{x}\n..."""` is not a violation and must not be reported as one.
        if len(quote) < 3 and end.end[0] != token.start[0]:
            findings.append(
                f"{filename}:{line}: an f-string replacement field spans a newline. Legal from "
                f"3.12 (PEP 701) and a SyntaxError at {FLOOR_STR} — 'unterminated string literal'. "
                "Hoist the expression into a local above the f-string"
            )
        # (2) The delimiter's own quote character reused inside a replacement field. Catches both
        #     a plain nested string and a nested f-string, since both arrive as tokens here.
        for tok in inner:
            if tok.type in (fstring_middle, fstring_end):
                continue
            text = tok.string
            if tok.type in (tokenize.STRING, fstring_start) and \
                    text[len(text.rstrip('"\'')):].startswith(quote[0]):
                findings.append(
                    f"{filename}:{tok.start[0]}: a replacement field reuses the f-string's own "
                    f"{quote[0]!r} quote ({text[:24]!r}). Legal from 3.12 (PEP 701) and a "
                    f"SyntaxError at {FLOOR_STR} — \"f-string: expecting '}}'\". Use the other "
                    "quote character inside, or hoist the expression out"
                )
        # (3) A backslash anywhere inside a replacement field. FSTRING_MIDDLE is excluded because
        #     that is the LITERAL text, where `\n` has always been legal.
        for tok in inner:
            if tok.type in (fstring_middle,):
                continue
            if "\\" in tok.string:
                findings.append(
                    f"{filename}:{tok.start[0]}: a replacement field contains a backslash "
                    f"({tok.string[:24]!r}). Legal from 3.12 (PEP 701) and a SyntaxError at "
                    f"{FLOOR_STR} — 'f-string expression part cannot include a backslash'. Bind "
                    "the value to a local above the f-string"
                )
    return findings


def test_the_pep701_scanner_agrees_with_a_real_interpreter_on_known_cases():
    """The scanner is calibrated against ground truth, not against the PEP's wording.

    Six cases, three that a real 3.11 rejects and three it accepts. The three ACCEPTED ones are the
    half that matters most: a scanner that flags single quotes inside a double-quoted f-string, or
    a triple-quoted f-string spanning lines, would fail this repository's existing code everywhere
    and be switched off within a day.

    Run at every floor, because the scanner's correctness does not depend on what this repository
    happens to declare today.
    """
    violates = {
        "same-quote nesting": 'x = f"crs {"a" + b}"\n',
        "newline in a replacement field": 'x = (f"crs {\'a\' if c else \'b\' +\n  \'c\'}; t "\n  "u")\n',
        "backslash in a replacement field": 'x = f"a {b.split(\'\\\\n\')}"\n',
    }
    legal = {
        "single quotes inside a double-quoted f-string": 'x = f"crs {\'a\' + b if c else \'d\'}"\n',
        "triple-quoted f-string spanning lines": 'x = f"""line {a}\nline2"""\n',
        "nested f-string using the other quote": 'x = f"a {f\'b {c}\'}"\n',
    }
    for label, src in violates.items():
        assert _pep701_violations(src, "<sample>"), (
            f"the PEP 701 scanner did not flag {label!r}. A real 3.11 interpreter rejects it, so "
            "the scanner has stopped matching and the gate's second half is checking nothing"
        )
    for label, src in legal.items():
        found = _pep701_violations(src, "<sample>")
        assert not found, (
            f"the PEP 701 scanner flagged {label!r}, which a real 3.11 interpreter ACCEPTS: "
            f"{found}. A scanner with false positives on ordinary code gets switched off"
        )


def test_feature_version_alone_would_not_have_caught_the_defect_this_module_exists_for():
    """THE MEASUREMENT behind this module's design, asserted so it cannot quietly stop being true.

    If a future CPython makes ``feature_version`` gate the tokenizer too, this fails — and that is
    the right outcome: the second scanner would then be redundant, and finding that out from a
    failing test is better than carrying it forever because nobody re-measured.
    """
    nested = 'x = f"crs {\'a\' if c else \'b\' +\n  \'c\'}; tail "\n'
    try:
        ast.parse(nested, feature_version=(3, 11))
        gated = False
    except SyntaxError:
        gated = True
    assert not gated, (
        "ast.parse(feature_version=(3, 11)) now REJECTS a PEP 701 f-string. It did not when this "
        "module was written, which is why `_pep701_violations` exists at all. Re-read the module "
        "docstring and decide whether the scanner is still earning its place"
    )


# ------------------------------------------------------------------------------- the gate itself

def problems_at_floor(source: str, filename: str) -> list[str]:
    """Everything wrong with one file at the declared floor: BOTH checks, in one place.

    Factored out rather than inlined into the parametrised test, and the reason is a mutation that
    survived: deleting the scanner call from the test body left the suite green, because the tree
    was clean and the scanner's own calibration tests call it directly. The two halves of the gate
    were correct and one of them was not wired to anything.

    With both behind one function, `test_the_gate_would_fail_on_the_construct_that_prompted_it`
    exercises the SAME entry point the parametrised test uses, so a scanner that stops being
    called stops being called for that test too.
    """
    problems: list[str] = []
    try:
        ast.parse(source, filename=filename, feature_version=FLOOR)
    except SyntaxError as error:
        problems.append(
            f"{filename}:{error.lineno} does not parse at the declared floor {FLOOR_STR}: "
            f"{error.msg}"
        )
    if FLOOR < (3, 12):
        problems += _pep701_violations(source, filename)
    return problems


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.name))
def test_every_file_parses_at_the_declared_floor(path):
    """`ast.parse` at the floor, plus the PEP 701 scan the flag does not cover."""
    relative = str(path.relative_to(REPO))
    problems = problems_at_floor(path.read_text(), relative)
    assert not problems, (
        f"{relative} does not meet the declared floor {FLOOR_STR}:\n  " + "\n  ".join(problems)
        + f"\n`requires-python = \">={FLOOR_STR}\"` is a promise this file breaks. Repair the "
        "construct, or raise the declaration deliberately and say why in the commit. Note that "
        "`ast.parse(feature_version=...)` does NOT catch the PEP 701 cases — it gates the parser "
        "and PEP 701 moved f-strings into the tokenizer — which is why the scanner exists."
    )


def test_the_gate_would_fail_on_the_construct_that_prompted_it():
    """AN ABSENCE made positive: the gate is exercised against the original defect, verbatim.

    `adapters/legion.py:324` is repaired, so nothing in the tree triggers the scanner any more —
    and a check whose every case passes proves only that it found nothing. The offending expression
    is therefore kept here as a string and run through the gate, so the day the scanner stops
    matching, this fails instead of the tree silently going unchecked.
    """
    original = (
        'basis = (\n'
        '    f"crs {\'stated as \' + stated if crs else \'ABSENT, so \' + CRS_DEFAULT + \' by the \'\n'
        '     \'schema default\'}; coordinates read as geocentric [X, Y, Z] metres and converted "\n'
        '    f"to geodetic on the WGS84 ellipsoid")\n'
    )
    findings = problems_at_floor(original, "adapters/legion.py")
    assert findings, (
        "the scanner no longer flags the exact expression that broke the 3.11 build. That "
        "expression is quoted here verbatim from the pre-repair source, so this failing means the "
        "scanner has regressed — not that the code is fine"
    )
    assert any("spans a newline" in f for f in findings), findings
    # And `feature_version` still lets it through, which is the whole argument for the scanner.
    ast.parse(original, feature_version=FLOOR)


# ------------------------------------------- RULING 0's proof: the repair changed no rendered byte

def test_the_denested_crs_clause_renders_identically_to_the_form_it_replaced():
    """The repair is asserted byte-for-byte, in BOTH branches, rather than reviewed by eye.

    The old form could not be written into this file as source — it is a SyntaxError below 3.12 and
    this module has to parse at the floor like everything else — so it is built with the same
    string concatenation the original performed and compared against the live adapter's output.
    The comparison is against `legion.py`'s actual rendered `basis`, not against a copy of the new
    expression, so a later edit to the adapter's wording fails here too.
    """
    from synapse_cdm.adapters.legion import CRS_DEFAULT, CRS_ECEF

    def old_form(crs, stated):
        # Exactly the original replacement field, evaluated rather than parsed:
        #   'stated as ' + stated if crs else 'ABSENT, so ' + CRS_DEFAULT + ' by the ' 'schema default'
        # The trailing pair was an implicit concatenation across the newline that broke the build.
        return ('stated as ' + stated if crs
                else 'ABSENT, so ' + CRS_DEFAULT + ' by the ' 'schema default')

    def new_form(crs, stated):
        return ('stated as ' + stated if crs
                else 'ABSENT, so ' + CRS_DEFAULT + ' by the schema default')

    for crs, stated in ((CRS_ECEF, CRS_ECEF), (None, CRS_DEFAULT), ("", CRS_DEFAULT)):
        assert old_form(crs, stated) == new_form(crs, stated), (
            f"the de-nested crs clause renders differently for crs={crs!r}: "
            f"{old_form(crs, stated)!r} became {new_form(crs, stated)!r}"
        )
    # BOTH branches are actually exercised above, which a two-case loop over one truthy value
    # would not do — and an identity that only holds on one branch is not the claim.
    assert old_form(CRS_ECEF, CRS_ECEF) != old_form(None, CRS_DEFAULT)

    # And the live adapter emits exactly the new form, so this is a check on the code and not on a
    # transcription of it.
    from synapse_cdm.adapters.legion import _coordinates_of

    geometry = {"type": "Point", "coordinates": [4000000.0, 1000000.0, 4800000.0]}
    for crs, expected in ((CRS_ECEF, new_form(CRS_ECEF, CRS_ECEF)),
                          (None, new_form(None, CRS_DEFAULT))):
        *_unused, basis = _coordinates_of(geometry, crs)
        assert basis.startswith(f"crs {expected};"), (
            f"legion.py's rendered basis for crs={crs!r} starts {basis[:90]!r}, and the de-nested "
            f"clause says it should start with 'crs {expected};'"
        )
    # The two branches produce DIFFERENT bases, which is what the conditional is for. A repair
    # that collapsed them would satisfy every equality above.
    assert _coordinates_of(geometry, CRS_ECEF)[-1] != _coordinates_of(geometry, None)[-1]


# --------------------------------------------------------- corroboration, when the floor is on disk

def _floor_interpreter() -> str | None:
    """A real interpreter at the declared floor, if this machine happens to have one."""
    import shutil
    candidates = [shutil.which(f"python{FLOOR_STR}")]
    uv_root = pathlib.Path.home() / ".local/share/uv/python"
    if uv_root.is_dir():
        candidates += [str(p) for p in sorted(uv_root.glob(
            f"cpython-{FLOOR_STR}*/bin/python{FLOOR_STR}"))]
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).exists():
            return candidate
    return None


def test_a_real_floor_interpreter_compiles_the_tree_when_this_machine_has_one():
    """CORROBORATION, and it is allowed to skip — unlike everything above it.

    The distinction is deliberate. The checks above are the gate and must run everywhere, so they
    use only the running interpreter. This one asks a real 3.x to compile the tree, which is
    stronger evidence and cannot be a requirement: CI images do not carry every floor. It skips
    when absent and says so, rather than being written as an assertion nobody can satisfy.

    Note it still only proves SYNTAX. Compiling is not importing, and importing would need the
    dependency tree installed for that version.
    """
    interpreter = _floor_interpreter()
    if interpreter is None:
        pytest.skip(f"no CPython {FLOOR_STR} on this machine; the gate above ran without it")
    script = (
        "import pathlib, sys\n"
        "bad = []\n"
        "for raw in sys.argv[1:]:\n"
        "    p = pathlib.Path(raw)\n"
        "    try: compile(p.read_text(), raw, 'exec')\n"
        "    except SyntaxError as e: bad.append(f'{raw}:{e.lineno} {e.msg}')\n"
        "print('\\n'.join(bad))\n"
    )
    result = subprocess.run([interpreter, "-c", script, *[str(p) for p in FILES]],
                            capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, f"the {FLOOR_STR} corroboration run failed: {result.stderr}"
    assert not result.stdout.strip(), (
        f"a real CPython {FLOOR_STR} rejects files this gate passed:\n{result.stdout}\n"
        "The gate is under-approximating the floor — add the construct to `_pep701_violations` or "
        "widen the check, and record what was missed"
    )
