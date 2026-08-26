"""The rosters inside `gates/wheel_install.py`, which had no gate over them.

WHY THIS MODULE EXISTS
----------------------
`gates/wheel_install.py` is a protocol act rather than a suite member: it builds a wheel, makes a
venv and installs into it, so it is run deliberately before a release and not on every commit.
That is a defensible arrangement, and it had one consequence nobody had priced in — the gate holds
three rosters, and being outside the suite meant they were the only rosters in this repository
that nothing derived and nothing compared.

They drifted. `cat023` and `cat062` shipped with their tests, their fixtures and their prose
counts all updated, and `pytest` stayed green at 2867 passed because no test in it reads that
file. The gate went red on `main` and stayed red, unnoticed, because the thing that noticed was
the thing nobody runs. Two of its checks disagreed about the same tree on the same run:

* `resources` compared the installed adapter count against a written-down ten and said
  `12 adapters resolved, expected 10` — a real failure, correctly reported;
* `harness` iterated the same written-down ten, replayed ten of the twelve adapters and printed
  `10 adapters x 2 schema modes, 596 fixture verdicts, 0 failed`. A PASS, over a run that never
  touched either new adapter, whose count is the SUBSET's count — so the row does not read as
  partial. It reads as complete.

The quiet one is the defect. A gate that silently narrows what it checks and reports the narrowed
scope as its verdict is the exact failure the gate was built to catch in other people's code.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not build a wheel, install anything, or make a venv — that is the gate's job and this is
not a second copy of it. It checks only the part that can be wrong while sitting still: whether
the gate's rosters still describe this tree. Those are cheap, pure comparisons, and cheap is the
point, because a check that runs on every commit is what the gate needed and did not have.

`gates/wheel_install.py` is loaded by PATH rather than imported by name: `gates/` is not a
package, has no `__init__.py`, and is not on `sys.path` when the suite runs. Loading it also
proves the file is importable with no side effects, which is worth one assertion of its own —
a gate that only parses is a gate that fails at the end of a five-minute build.

It is loaded with `exec(compile(...))` and NOT with `spec.loader.exec_module`, and that is not a
style preference. The first draft of this module used `exec_module`, and
`tests/test_cdm_generator_loading.py` failed it on the commit — correctly. `exec_module` runs the
ordinary source loader, which consults and writes `__pycache__`, and a `.pyc` is revalidated on
the source's mtime in whole SECONDS plus its size: a same-length edit reverted inside one second
leaves a cache that validates against a file it was not compiled from. That matters more here than
almost anywhere, because the way you check the assertions below is by mutating this very gate and
reverting — which is exactly the edit pattern the stale `.pyc` defeats. The mutation run for this
module needed `__pycache__` cleared by hand between cases before it was moved to this form.
"""
import pathlib
import types

import pytest

from synapse_cdm import adapter

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "wheel_install.py"


@pytest.fixture(scope="module")
def gate():
    """The gate module, from its SOURCE — never from bytecode. See this module's docstring."""
    module = types.ModuleType("_wheel_install_gate")
    module.__file__ = str(GATE_PATH)
    exec(compile(GATE_PATH.read_text(), str(GATE_PATH), "exec"), module.__dict__)
    return module


def test_the_gate_imports_with_no_side_effects(gate):
    """Importing it must not build, install or write anything — only define.

    The gate's own `main()` is the only thing that acts. If module scope ever grows an action, a
    contributor who merely reads the file with a tool that imports it pays for a wheel build.
    """
    assert hasattr(gate, "main")
    assert callable(gate.source_roster)


def test_the_gate_derives_its_adapter_roster_rather_than_stating_one(gate):
    """The roster the gate replays must BE the registry, not a copy of it that was right once.

    This is the check whose absence let `harness` print ten of twelve as a pass. It is written
    against `source_roster()` rather than against a tuple of names on purpose: asserting that a
    literal equals the registry would just move the literal into this file.
    """
    registered = {name for name, cls in adapter.roster().items()
                  if cls.__module__.startswith("synapse_cdm.adapters.")}
    derived = set(gate.source_roster())
    assert derived == registered, (
        f"the gate's roster and the registry disagree: only in the gate {sorted(derived - registered)}, "
        f"only in the registry {sorted(registered - derived)}. `source_roster()` asks the source "
        "tree through a subprocess, so a disagreement here means the subprocess answered for a "
        "different tree — check PYTHONPATH and whether an installed synapse_cdm shadowed it")


def test_the_gate_states_no_adapter_roster_as_a_literal(gate):
    """No tuple of adapter names anywhere in the file.

    The repair replaced one; this is what stops the next one being added back as "just two more
    strings", which is how the first one grew to ten and then stopped growing.
    """
    text = GATE_PATH.read_text()
    names = sorted(adapter.roster())
    # Three or more adapter names quoted on one line is a roster being written down. Two is a
    # sentence naming the pair that broke this ("`cat023` and `cat062` shipped"), which is prose.
    offenders = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(("#:", "*", "#")) or '"""' in line:
            continue
        quoted = [n for n in names if f'"{n}"' in line or f"'{n}'" in line]
        if len(quoted) >= 3:
            offenders.append(f"{number}: {quoted}")
    assert not offenders, (
        "adapter names are listed as literals in gates/wheel_install.py at "
        f"{offenders}. Derive the roster with source_roster() — a written-down one is what "
        "reported ten of twelve adapters as a green run")


def test_every_test_module_is_decided_by_one_of_the_gates_two_lists(gate):
    """The gate's `closure` check, run without building a wheel to reach it.

    `closure` already makes this assertion. It makes it after `build`, which means a contributor
    adding a test module learns about it from a release build rather than from `pytest` — and the
    four modules this repair added had been undecided across two rounds for exactly that reason.
    Same rule, same lists, priced so it runs every time.
    """
    on_disk = {p.name for p in (REPO / "tests").glob("test_*.py")}
    package_only = set(gate.PACKAGE_ONLY_TESTS)
    repo_bound = set(gate.REPO_BOUND_TESTS)

    both = package_only & repo_bound
    assert not both, f"in both of the gate's lists: {sorted(both)}"

    undecided = sorted(on_disk - package_only - repo_bound)
    assert not undecided, (
        f"test modules in neither of gates/wheel_install.py's lists: {undecided}. Decide each "
        "one: does it judge the PACKAGE, in which case it is added to PACKAGE_ONLY_TESTS and runs "
        "against the installed wheel, or does it judge the REPOSITORY, in which case it goes into "
        "REPO_BOUND_TESTS with the repository fact it is about. The default for an undecided "
        "module is that it never runs against the wheel at all, which is a silent narrowing")

    gone = sorted((package_only | repo_bound) - on_disk)
    assert not gone, (
        f"the gate lists test modules that are not on disk: {gone}. A renamed or deleted module "
        "leaves the gate asserting over a file that cannot fail")


def test_the_repository_bound_list_names_a_reason_for_every_module(gate):
    """`REPO_BOUND_TESTS` is a mapping and not a set, and the values carry the weight.

    Its own comment says the reason is what stops a module drifting in here because it was easier
    than making it installable. An empty or placeholder reason would honour the type and lose the
    check.
    """
    thin = {name: why for name, why in gate.REPO_BOUND_TESTS.items() if len(why.strip()) < 15}
    assert not thin, (
        f"these entries name no real repository fact: {thin}. The value is the decision's "
        "justification — 'the repository' or '' is the module drifting in unexamined")
