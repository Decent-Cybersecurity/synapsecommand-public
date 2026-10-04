"""The DIS 7 acceptance trace: a two-way ratchet over the contract's 38 cases and R01-R30.

The contract is the handoff document `SC DIS7 SPEC 001 v1.0`, which is not in this repository.

A CASE is bound when a test function named `test_t<gg>_<case>_...` exists in a
`tests/test_cdm_dis7_*.py` module, or when a module-level dict literal `SWEEP_BUILDERS` in such
a module has the key `t<gg>_<case>` (the acceptance sweep); the group label must match the
case's group in the contract file. A REQUIREMENT that cases cite is bound when every citing case
is bound; the nine requirements no case cites are bound by an `R_EVIDENCE` entry. `PENDING`
lists the unbound ids only: the ratchet fails when a pending id is already bound (stale) and
when an unbound id is not pending.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re

from tests import dis7_support

TESTS = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TESTS.parent
SWEEP_TABLE = "SWEEP_BUILDERS"
TEST_NAME = re.compile(r"^test_t(\d\d)((?:_[an]\d\d)+)_")
SWEEP_KEY = re.compile(r"^t(\d\d)_([an]\d\d)$")
RUN_ARTEFACT = re.compile(r"^RUN:[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")
OWNER = re.compile(r"^run R(?:0[3-9]|1[0-9])$")
CASES = json.loads((dis7_support.CONTRACT / "acceptance-cases.json").read_text(encoding="utf-8"))["cases"]
CASE_GROUP = {case["id"]: case["group"] for case in CASES}            # "N20" -> "T03"
REQUIREMENTS = tuple(f"R{number:02d}" for number in range(1, 31))
CITED_BY = {r: tuple(c["id"] for c in CASES if r in c["requirements"]) for r in REQUIREMENTS}
UNCITED = tuple(r for r in REQUIREMENTS if not CITED_BY[r])

PENDING = {
    # run R11
    "N18": "run R11", "N20": "run R11",
    "R12": "run R11",
    # run R14
    "N15": "run R14", "N16": "run R14", "N17": "run R14", "N19": "run R14",
    # run R15
    "N12": "run R15", "N14": "run R15", "A08": "run R15", "A09": "run R15", "A10": "run R15",
    "A11": "run R15", "N21": "run R15",
    "R04": "run R15", "R05": "run R15", "R06": "run R15", "R10": "run R15", "R13": "run R15",
    "R18": "run R15", "R19": "run R15", "R20": "run R15",
    "R02": "run R15", "R03": "run R15", "R07": "run R15", "R25": "run R15", "R30": "run R15",
    # run R16
    "A12": "run R16",
    "R24": "run R16", "R28": "run R16",
    # run R17
    "A13": "run R17",
    "R26": "run R17",
    # run R18
    "A14": "run R18",
    "R27": "run R18",
    # run R19
    "R01": "run R19", "R23": "run R19", "R29": "run R19",
}

R_EVIDENCE = {
    "R21": (
        "tests/test_cdm_dis7_codec.py::test_r21_codes_are_the_contract_table_in_order",
        "tests/test_cdm_dis7_codec.py::test_r21_every_code_an_acceptance_case_expects_is_in_the_table",
        "tests/test_cdm_dis7_codec.py::test_r21_error_exposes_code_path_message_and_prints_them",
        "tests/test_cdm_dis7_codec.py::test_r21_too_large_carries_the_limit_code_and_both_base_classes",
        "tests/test_cdm_dis7_codec.py::test_r21_too_deep_carries_the_limit_code_and_both_base_classes",
        "tests/test_cdm_dis7_codec.py::test_r21_errors_survive_copy_and_pickle",
        "tests/test_cdm_dis7_codec.py::test_r21_no_foreign_exception_escapes_decode_pdu",
        "tests/test_cdm_dis7_codec.py::test_r21_no_foreign_exception_escapes_encode_pdu",
    ),
}


def _bind(bindings, problems, case_token, group_label, site):
    case = case_token.upper()
    group = "T" + group_label
    if case not in CASE_GROUP:
        problems.append(f"{site} binds unknown case {case}")
        return
    if CASE_GROUP[case] != group:
        problems.append(
            f"{site} binds {case} as {group}, but the contract has it in group {CASE_GROUP[case]}"
        )
        return
    bindings.setdefault(case, []).append(site)


def scan_source(source: str, filename: str) -> tuple[dict[str, list[str]], list[str]]:
    bindings: dict[str, list[str]] = {}
    problems: list[str] = []
    tree = ast.parse(source, filename=filename)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            match = TEST_NAME.match(node.name)
            if not match:
                continue
            group_label = match.group(1)
            tokens = re.findall(r"[an]\d\d", match.group(2))
            site = f"tests/{filename}::{node.name}"
            for token in tokens:
                _bind(bindings, problems, token, group_label, site)
        elif isinstance(node, ast.Module):
            for stmt in node.body:
                if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                if SWEEP_TABLE not in names:
                    continue
                value = stmt.value
                if not isinstance(value, ast.Dict):
                    problems.append(f"tests/{filename}::{SWEEP_TABLE} is not a dict literal")
                    continue
                for key_node in value.keys:
                    key = (
                        key_node.value
                        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)
                        else None
                    )
                    if key is None:
                        problems.append(f"tests/{filename}::{SWEEP_TABLE} has a non-string key")
                        continue
                    key_match = SWEEP_KEY.match(key)
                    if not key_match:
                        problems.append(f"tests/{filename}::{SWEEP_TABLE}[{key}] is malformed")
                        continue
                    site = f"tests/{filename}::{SWEEP_TABLE}[{key}]"
                    _bind(bindings, problems, key_match.group(2), key_match.group(1), site)

    return bindings, problems


def scan_tree() -> tuple[dict[str, list[str]], list[str]]:
    bindings: dict[str, list[str]] = {}
    problems: list[str] = []
    for path in sorted(TESTS.glob("test_cdm_dis7_*.py")):
        source = path.read_text(encoding="utf-8")
        file_bindings, file_problems = scan_source(source, path.name)
        for case, sites in file_bindings.items():
            bindings.setdefault(case, []).extend(sites)
        problems.extend(file_problems)
    return bindings, problems


def evidence_problems(evidence) -> list[str]:
    problems: list[str] = []
    for key, entries in evidence.items():
        if key not in UNCITED:
            problems.append(f"{key}: not among the uncited requirements")
        if len(entries) == 0:
            problems.append(f"{key}: evidence tuple is empty")
        for entry in entries:
            if RUN_ARTEFACT.match(entry):
                continue
            stripped = re.sub(r"\[[^\]]*\]$", "", entry)
            parts = stripped.split("::")
            if len(parts) != 2 or not parts[0].startswith("tests/"):
                problems.append(f"{entry}: neither a RUN: artefact nor a tests/<file>::<function> id")
                continue
            filename, funcname = parts[0][len("tests/"):], parts[1]
            file_path = REPO_ROOT / "tests" / filename
            if not file_path.is_file():
                problems.append(f"{entry}: {parts[0]} does not exist")
                continue
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
            names = {
                n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if funcname not in names:
                problems.append(f"{entry}: {funcname} is not defined in {parts[0]}")
    return problems


def bound_ids(bindings, evidence) -> set[str]:
    bound = set(bindings)
    for requirement in REQUIREMENTS:
        citing = CITED_BY[requirement]
        if citing and all(case in bindings for case in citing):
            bound.add(requirement)
    for requirement, entries in evidence.items():
        if requirement in UNCITED and len(entries) > 0:
            bound.add(requirement)
    return bound


def ratchet_problems(pending, bound, known) -> list[str]:
    problems: list[str] = []
    for pid in sorted(pid for pid in pending if pid not in known):
        problems.append(f"{pid}: not a known id")
    for pid in sorted(pid for pid in pending if pid in bound):
        problems.append(f"{pid}: stale; remove it from PENDING")
    for kid in sorted(k for k in known if k not in pending and k not in bound):
        problems.append(f"{kid}: unbound")
    return problems


def test_the_contract_lists_38_cases_in_16_groups_and_leaves_nine_requirements_uncited():
    assert len(CASES) == 38
    for case in CASES:
        assert re.fullmatch(r"[AN]\d\d", case["id"]), case["id"]
    assert set(CASE_GROUP.values()) == {f"T{n:02d}" for n in range(1, 17)}
    assert UNCITED == ("R01", "R02", "R03", "R07", "R21", "R23", "R25", "R29", "R30")


def test_every_case_test_carries_the_group_label_of_its_case():
    _, problems = scan_tree()
    assert problems == []


def test_the_evidence_map_names_only_uncited_requirements_and_every_entry_resolves():
    assert evidence_problems(R_EVIDENCE) == []


def test_pending_is_exactly_the_set_of_unbound_ids():
    bindings, _ = scan_tree()
    bound = bound_ids(bindings, R_EVIDENCE)
    known = set(CASE_GROUP) | set(REQUIREMENTS)
    problems = ratchet_problems(PENDING, bound, known)
    assert problems == [], "\n".join(problems)


def test_every_pending_id_names_the_run_that_binds_it():
    for value in PENDING.values():
        assert OWNER.match(value), value


def test_the_binder_reads_function_names_methods_and_the_sweep_table():
    source = (
        "def test_t02_n01_n02_header_octets():\n"
        "    pass\n"
        "\n"
        "\n"
        "class Example:\n"
        "    def test_t03_a02_all_records(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "def test_t16_oracle_grid():\n"
        "    pass\n"
        "\n"
        "\n"
        "def helper_t02_n03_x():\n"
        "    pass\n"
        "\n"
        "\n"
        "SWEEP_BUILDERS = {'t04_n36': None, 't09_n12': None}\n"
    )
    bindings, problems = scan_source(source, "test_cdm_dis7_example.py")
    assert problems == []
    assert bindings["N01"] == ["tests/test_cdm_dis7_example.py::test_t02_n01_n02_header_octets"]
    assert bindings["N02"] == ["tests/test_cdm_dis7_example.py::test_t02_n01_n02_header_octets"]
    assert bindings["A02"] == ["tests/test_cdm_dis7_example.py::test_t03_a02_all_records"]
    assert bindings["N36"] == ["tests/test_cdm_dis7_example.py::SWEEP_BUILDERS[t04_n36]"]
    assert bindings["N12"] == ["tests/test_cdm_dis7_example.py::SWEEP_BUILDERS[t09_n12]"]


def test_the_binder_refuses_a_wrong_group_an_unknown_case_and_a_malformed_sweep_key():
    source = (
        "def test_t03_n18_duplicate_key():\n"
        "    pass\n"
        "\n"
        "\n"
        "def test_t02_n99_nothing():\n"
        "    pass\n"
        "\n"
        "\n"
        "SWEEP_BUILDERS = {'t12_n18': None, 'n19': None}\n"
    )
    bindings, problems = scan_source(source, "test_cdm_dis7_example2.py")
    assert bindings == {"N18": ["tests/test_cdm_dis7_example2.py::SWEEP_BUILDERS[t12_n18]"]}
    assert len(problems) == 3
    assert any("N18" in p and "T03" in p and "T12" in p for p in problems)

    bindings2, problems2 = scan_source("SWEEP_BUILDERS = []\n", "test_cdm_dis7_example3.py")
    assert bindings2 == {}
    assert len(problems2) == 1


def test_a_requirement_is_bound_only_when_every_case_citing_it_is():
    assert CITED_BY["R15"] == ("A03", "N11")
    assert CITED_BY["R14"] == ("A01",)
    assert bound_ids({"A03": ["x"]}, {}) == {"A03"}
    assert bound_ids({"A03": ["x"], "N11": ["y"]}, {}) == {"A03", "N11", "R15"}
    assert bound_ids({"A01": ["x"]}, {}) == {"A01", "R14"}
    assert bound_ids({}, {"R23": ("RUN:reports/benchmark.json",)}) == {"R23"}
    assert bound_ids({}, {"R23": ()}) == set()


def test_the_ratchet_refuses_a_stale_id_an_unlisted_id_and_an_unknown_id():
    known = {"A01", "A02", "R14"}
    bound = {"A01", "R14"}

    pending = {"A02": "run R07"}
    assert ratchet_problems(pending, bound, known) == []

    with_stale = {"A02": "run R07", "A01": "run R07"}
    problems = ratchet_problems(with_stale, bound, known)
    assert len(problems) == 1
    assert problems[0].startswith("A01: stale")

    problems = ratchet_problems({}, bound, known)
    assert len(problems) == 1
    assert problems[0].startswith("A02: unbound")

    with_unknown = {"A02": "run R07", "Z99": "run R07"}
    problems = ratchet_problems(with_unknown, bound, known)
    assert len(problems) == 1
    assert problems[0].startswith("Z99:")


def test_the_evidence_check_refuses_what_does_not_resolve():
    clean = {
        "R01": (
            "tests/test_cdm_dis7_trace.py::test_pending_is_exactly_the_set_of_unbound_ids",
            "RUN:reports/benchmark.json",
        ),
    }
    assert evidence_problems(clean) == []

    assert len(evidence_problems({"R08": clean["R01"]})) == 1
    assert len(evidence_problems({"R01": ()})) == 1
    assert len(evidence_problems(
        {"R01": ("tests/test_cdm_dis7_trace.py::test_does_not_exist",)}
    )) == 1
    assert len(evidence_problems(
        {"R01": ("tests/test_cdm_dis7_does_not_exist.py::test_x",)}
    )) == 1
    assert len(evidence_problems({"R01": ("RUN:../outside",)})) == 1
