"""The DIS 7 acceptance trace: a two-way ratchet over the contract's 38 cases and R01-R30.

The contract is the handoff document `SC DIS7 SPEC 001 v1.0`, which is not in this repository.

A CASE is bound when a test function named `test_t<gg>_<case>_...` exists in a
`tests/test_cdm_dis7_*.py` module, or when a module-level dict literal `SWEEP_BUILDERS` in such
a module has the key `t<gg>_<case>` (the acceptance sweep); the group label must match the
case's group in the contract file. A REQUIREMENT that cases cite is bound when every citing case
is bound; the nine requirements no case cites are bound by an `R_EVIDENCE` entry. `PENDING`
lists the unbound ids only: the ratchet fails when a pending id is already bound (stale) and
when an unbound id is not pending. Only tests pytest collects bind: module-level functions and
methods of module-level classes whose name starts with `Test`. R_SUPPLEMENT attaches further test
ids to requirements that cases cite; it adds evidence and never binds. Case A12 must also be bound
in tests/test_cdm_gate_rosters.py, the wheel gate's half [CR-33].
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

import pytest

import synapse_cdm
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

PENDING = {}

R_EVIDENCE = {
    "R01": ("tests/test_cdm_dis7_trace.py::test_pending_is_exactly_the_set_of_unbound_ids",),
    "R02": (
        "tests/test_cdm_dis7_codec.py::test_r02_every_refused_category_is_refused_with_its_code_and_path",
        "tests/test_cdm_dis7_adapter.py::test_t15_bracket_leading_and_refused_format_samples_get_coded_errors",
    ),
    "R03": (
        "tests/test_cdm_dis7_schema.py::test_pin_every_vendored_file_matches_the_record_and_the_bundle_manifest",
        "tests/test_cdm_dis7_schema.py::test_r12_stage2_verdict_equals_the_envelope_schema_except_enumerated_divergences",
    ),
    "R07": (
        "tests/test_cdm_dis7_codec.py::test_r07_header_predicate_matrix",
        "tests/test_cdm_dis7_adapter.py::test_r07_validate_source_matrix",
        "tests/test_cdm_dis7_adapter.py::test_r07_detect_matrix",
    ),
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
    "R23": (
        "tests/test_cdm_dis7_benchmark.py::test_r23_quick_run_has_no_retained_growth",
        "RUN:reports/benchmark.json",
    ),
    "R25": (
        "tests/test_cdm_dis7_adapter.py::test_r25_index_walk_translates_each_wire_file_under_its_context_file",
        "tests/test_cdm_dis7_schema.py::test_vector_index_agrees_with_the_files",
    ),
    "R29": (
        "RUN:reports/R03-verify.md",
        "RUN:reports/R06-verify.md",
        "RUN:reports/R08-verify.md",
        "RUN:reports/R10-verify.md",
        "RUN:reports/R15-verify.md",
        "RUN:reports/R19-verify.md",
        "RUN:reports/R23-verify.md",
    ),
    "R30": (
        "tests/test_cdm_dis7_adapter.py::test_adapter_version_is_1_0_0",
        "tests/test_cdm_dis7_adapter.py::test_examples_is_never_imported",
        "tests/test_cdm_dis7_trace.py::test_completion_prototype_is_never_imported",
        "tests/test_cdm_dis7_trace.py::test_completion_adapter_reports_1_0_0",
    ),
}

R_SUPPLEMENT = {
    "R12": (
        "tests/test_cdm_dis7_schema.py::test_r12_emitted_entities_validate_against_the_profile_and_base_schemas",
        "tests/test_cdm_dis7_schema.py::test_r12_emitted_residuals_validate_and_rebuild_a_valid_envelope",
        "tests/test_cdm_dis7_schema.py::test_r12_schema_oracles_can_fail",
        "tests/test_cdm_dis7_schema.py::test_r12_stage2_verdict_equals_the_envelope_schema_except_enumerated_divergences",
    ),
    "R17": ("tests/test_cdm_dis7_adapter.py::test_r17_opaque_fields_never_become_status_confidence_or_quality",),
    "R22": (
        "tests/test_cdm_dis7_adapter.py::test_r22_duplicate_input_gives_duplicate_output_with_one_identity",
        "tests/test_cdm_dis7_adapter.py::test_r22_an_earlier_instant_after_a_later_one_keeps_its_own_instant",
        "tests/test_cdm_dis7_adapter.py::test_r22_marking_bytes_spelling_a_path_open_no_file",
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


def _bind_test_name(bindings, problems, name, site):
    match = TEST_NAME.match(name)
    if not match:
        return
    group_label = match.group(1)
    for token in re.findall(r"[an]\d\d", match.group(2)):
        _bind(bindings, problems, token, group_label, site)


def _defines_init(cls: ast.ClassDef) -> bool:
    """pytest does not collect a `Test*` class that defines `__init__`."""
    return any(isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
               and member.name == "__init__" for member in cls.body)


def scan_source(source: str, filename: str) -> tuple[dict[str, list[str]], list[str]]:
    bindings: dict[str, list[str]] = {}
    problems: list[str] = []
    tree = ast.parse(source, filename=filename)

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _bind_test_name(bindings, problems, stmt.name, f"tests/{filename}::{stmt.name}")
        elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test") \
                and not _defines_init(stmt):
            for member in stmt.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _bind_test_name(
                        bindings, problems, member.name,
                        f"tests/{filename}::{stmt.name}::{member.name}",
                    )
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
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


def _entry_problems(entry: str) -> list[str]:
    if RUN_ARTEFACT.match(entry):
        return []
    stripped = re.sub(r"\[[^\]]*\]$", "", entry)
    parts = stripped.split("::")
    if len(parts) != 2 or not parts[0].startswith("tests/"):
        return [f"{entry}: neither a RUN: artefact nor a tests/<file>::<function> id"]
    filename, funcname = parts[0][len("tests/"):], parts[1]
    file_path = REPO_ROOT / "tests" / filename
    if not file_path.is_file():
        return [f"{entry}: {parts[0]} does not exist"]
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    names = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if funcname not in names:
        return [f"{entry}: {funcname} is not defined in {parts[0]}"]
    if not funcname.startswith("test"):
        return [f"{entry}: not a test function"]
    return []


def evidence_problems(evidence) -> list[str]:
    problems: list[str] = []
    for key, entries in evidence.items():
        if key not in UNCITED:
            problems.append(f"{key}: not among the uncited requirements")
        if len(entries) == 0:
            problems.append(f"{key}: evidence tuple is empty")
        for entry in entries:
            problems.extend(_entry_problems(entry))
    return problems


def supplement_problems(supplement) -> list[str]:
    problems: list[str] = []
    for key, entries in supplement.items():
        if key not in REQUIREMENTS or not CITED_BY[key]:
            problems.append(f"{key}: not a cited requirement")
        if len(entries) == 0:
            problems.append(f"{key}: supplement tuple is empty")
        for entry in entries:
            if entry.startswith("RUN:"):
                problems.append(f"{entry}: a supplement names tests only")
                continue
            problems.extend(_entry_problems(entry))
    return problems


A12_WHEEL_GATE_SITES = frozenset({
    "tests/test_cdm_gate_rosters.py::test_t15_a12_the_gate_reads_a_scripts_output_as_bytes",
    "tests/test_cdm_gate_rosters.py::"
    "test_t15_a12_the_dis7_script_runs_inside_the_scripts_check_and_the_gate_keeps_thirteen_checks",
    "tests/test_cdm_gate_rosters.py::test_t15_a12_the_dis7_script_check_passes_against_this_environment",
})


def a12_wheel_gate_problems(roster_source: str) -> list[str]:
    bindings, problems = scan_source(roster_source, "test_cdm_gate_rosters.py")
    missing = sorted(A12_WHEEL_GATE_SITES - set(bindings.get("A12", [])))
    return problems + [f"{site}: missing" for site in missing]


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
        "class TestExample:\n"
        "    def test_t03_a02_all_records(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "class Example:\n"
        "    def test_t02_n03_x(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "def outer():\n"
        "    def test_t02_n04_x():\n"
        "        pass\n"
        "\n"
        "\n"
        "class TestWithInit:\n"
        "    def __init__(self):\n"
        "        pass\n"
        "\n"
        "    def test_t02_n05_x(self):\n"
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
    assert bindings["A02"] == ["tests/test_cdm_dis7_example.py::TestExample::test_t03_a02_all_records"]
    assert "N03" not in bindings and "N04" not in bindings
    assert "N05" not in bindings
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
    assert len(evidence_problems({"R07": ("tests/test_cdm_dis7_adapter.py::check",)})) == 1
    assert len(evidence_problems({"R07": ("tests/test_cdm_dis7_adapter.py::_envelope",)})) == 1

    def test_nested_only():
        """Named like a test, but nested, so pytest never collects it."""

    assert test_nested_only() is None
    assert len(evidence_problems(
        {"R07": ("tests/test_cdm_dis7_trace.py::test_nested_only",)}
    )) == 1


def test_the_supplement_names_only_cited_requirements_and_every_entry_resolves():
    assert supplement_problems(R_SUPPLEMENT) == []


def test_the_supplement_check_refuses_what_does_not_resolve():
    clean = R_SUPPLEMENT["R22"][:1]
    assert supplement_problems({"R22": clean}) == []
    assert len(supplement_problems({"R01": clean})) == 1
    assert len(supplement_problems({"R22": ()})) == 1
    assert len(supplement_problems({"R22": ("RUN:reports/benchmark.json",)})) == 1
    assert len(supplement_problems(
        {"R22": ("tests/test_cdm_dis7_adapter.py::test_does_not_exist",)}
    )) == 1
    assert len(supplement_problems({"R22": ("tests/test_cdm_dis7_adapter.py::_envelope",)})) == 1


def test_every_named_requirement_test_of_a_cited_requirement_is_in_the_supplement():
    missing = []
    for path in sorted(TESTS.glob("test_cdm_dis7_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for stmt in tree.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            match = re.match(r"^test_r(\d\d)_", stmt.name)
            if not match:
                continue
            requirement = f"R{match.group(1)}"
            if requirement in REQUIREMENTS and CITED_BY[requirement]:
                site = f"tests/{path.name}::{stmt.name}"
                if site not in R_SUPPLEMENT.get(requirement, ()):
                    missing.append(site)
    assert missing == []


# CR-33
def test_cr33_case_a12_is_bound_to_the_wheel_gate_as_well_as_the_cli():
    bindings, _ = scan_tree()
    assert any(site.startswith("tests/test_cdm_dis7_cli.py::") for site in bindings["A12"])
    roster = (TESTS / "test_cdm_gate_rosters.py").read_text(encoding="utf-8")
    assert a12_wheel_gate_problems(roster) == []


def test_cr33_the_wheel_gate_check_can_fail():
    assert len(a12_wheel_gate_problems("def test_other():\n    pass\n")) == 3


# D-28: a test that covers a contract resolution carries a comment naming it on the line above
# the test (above its first decorator where it has one).
RESOLUTIONS = tuple(f"CR-{number:02d}" for number in range(1, 36))
RESOLUTION_TAG = re.compile(r"^#.*\bCR-\d\d")


def tagged_resolutions(source: str) -> set[str]:
    """The resolutions tagged at column 0 on the line above a module-level test function, or
    above its first decorator; a tag above a fixture, a helper or a nested function counts not."""
    lines = source.split("\n")
    found: set[str] = set()
    for stmt in ast.parse(source).body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                or not stmt.name.startswith("test_"):
            continue
        first = min([stmt.lineno] + [decorator.lineno for decorator in stmt.decorator_list])
        if first >= 2 and RESOLUTION_TAG.match(lines[first - 2]):
            found.update(re.findall(r"\bCR-\d\d\b", lines[first - 2]))
    return found


def test_every_contract_resolution_is_tagged_above_a_test():
    found: set[str] = set()
    for path in sorted(TESTS.glob("test_*.py")):
        found |= tagged_resolutions(path.read_text(encoding="utf-8"))
    assert sorted(set(RESOLUTIONS) - found) == []


def test_the_resolution_tag_check_can_fail():
    assert tagged_resolutions("# CR-06, CR-29\n@pytest.mark.x\ndef test_a():\n    pass\n") == {
        "CR-06", "CR-29",
    }
    assert tagged_resolutions("# CR-14\n\ndef test_a():\n    pass\n") == set()
    assert tagged_resolutions("def test_a():\n    # CR-14\n    helper()\n") == set()
    assert tagged_resolutions(
        "# CR-34\n@pytest.fixture(scope=\"module\")\ndef gate():\n    pass\n") == set()
    assert tagged_resolutions(
        "def _not_a_test():\n    # CR-34\n    def test_never_collected():\n        pass\n") == set()
    assert tagged_resolutions(
        "# CR-34\n@pytest.mark.parametrize(\n    \"x\", [1])\ndef test_a(x):\n    pass\n") == {"CR-34"}


# ------------------------------------------------------------------------- completion checks
#
# The DIS 7 sources carry no placeholder and no empty function body, import only the standard
# library, pydantic and the package itself, and never import the handoff prototype. Each helper is
# a function of source text, so the checks are witnessed refusing before they judge the tree.

PACKAGE_DIR = pathlib.Path(synapse_cdm.__file__).resolve().parent
COMPLETION_SOURCES = (
    PACKAGE_DIR / "adapters" / "dis7.py",
    PACKAGE_DIR / "adapters" / "dis7_codec.py",
    PACKAGE_DIR / "dis7_host.py",
    *sorted((REPO_ROOT / "gates").glob("dis7_*.py")),
)
AUDITED_MODULES = {
    "dis7.py": PACKAGE_DIR / "adapters" / "dis7.py",
    "dis7_codec.py": PACKAGE_DIR / "adapters" / "dis7_codec.py",
    "dis7_host.py": PACKAGE_DIR / "dis7_host.py",
}
ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {"pydantic", "synapse_cdm"}
ADAPTER_FORBIDDEN = frozenset({"hashlib", "hmac", "secrets", "ssl", "socket", "urllib", "http",
                               "asyncio", "subprocess", "platform"})
HOST_FORBIDDEN = frozenset({"hashlib", "hmac", "secrets", "ssl", "socket", "urllib", "http",
                            "asyncio", "signal", "resource", "platform"})
PLACEHOLDER = re.compile(r"\b(TODO|FIXME|XXX)\b")
CLAIM_PHRASES = ("full dis 7 support", "ieee certified", "ieee-certified", "ieee compliant")
NEGATIONS = frozenset({"no", "not", "never", "without"})


def placeholder_markers(source: str) -> list[str]:
    """Every placeholder marker in the text, and `NotImplementedError` wherever it occurs."""
    found = [match.group(0) for match in PLACEHOLDER.finditer(source)]
    if "NotImplementedError" in source:
        found.append("NotImplementedError")
    return found


def _raises_not_implemented(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.Raise) or statement.exc is None:
        return False
    target = statement.exc.func if isinstance(statement.exc, ast.Call) else statement.exc
    return isinstance(target, ast.Name) and target.id == "NotImplementedError"


def empty_function_bodies(source: str) -> list[str]:
    """Functions whose body after a leading docstring is empty, only `pass`/`...`, or raises
    `NotImplementedError` anywhere. Classes are exempt."""
    flagged: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            trivial = all(
                isinstance(s, ast.Pass)
                or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and s.value.value is Ellipsis)
                for s in body
            )
            if trivial:
                flagged.append(f"{node.name} (line {node.lineno})")
        if _raises_not_implemented(node):
            flagged.append(f"raise NotImplementedError (line {node.lineno})")
    return flagged


def imported_roots(source: str) -> set[str]:
    """Top-level names a module imports; a relative import counts as `synapse_cdm`."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                roots.add("synapse_cdm")
            elif node.module:
                roots.add(node.module.split(".")[0])
    return roots


def claim_sentences(text: str) -> list[str]:
    """Sentences that claim more than the subset: a claim phrase with no negation before it."""
    claims: list[str] = []
    for chunk in re.split(r"[.;|]|\n[ \t]*\n", text):
        sentence = " ".join(chunk.split()).lower()
        for phrase in CLAIM_PHRASES:
            at = sentence.find(phrase)
            if at < 0:
                continue
            if not NEGATIONS & set(re.findall(r"[a-z]+", sentence[:at])):
                claims.append(sentence)
                break
    return claims


def _section(text: str, start: int) -> str:
    rest = text[start:]
    following = re.search(r"(?m)^## ", rest[1:])
    return rest if following is None else rest[:following.start() + 1]


def _claim_texts() -> dict[str, str]:
    readme = (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")
    heading = "\n## DIS 7 Entity State: the `dis7` adapter\n"
    coverage = (PACKAGE_DIR / "FORMAT_COVERAGE.md").read_text(encoding="utf-8")
    dis = re.search(r"(?m)^## .*DIS.*$", coverage)
    return {
        "README": _section(readme, readme.index(heading) + 1) if heading in readme else "",
        "dis7.mdx": (REPO_ROOT / "docs" / "docs" / "cdm" / "dis7.mdx").read_text(encoding="utf-8"),
        "FORMAT_COVERAGE": _section(coverage, dis.start()) if dis else "",
    }


def test_completion_sources_exist():
    names = {path.name for path in COMPLETION_SOURCES}
    assert {"dis7.py", "dis7_codec.py", "dis7_host.py", "dis7_mutation.py",
            "dis7_benchmark.py"} <= names
    for path in COMPLETION_SOURCES:
        assert path.is_file(), path


@pytest.mark.parametrize("path", COMPLETION_SOURCES, ids=lambda p: p.name)
def test_completion_no_placeholder_marker(path):
    assert placeholder_markers(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", COMPLETION_SOURCES, ids=lambda p: p.name)
def test_completion_no_empty_function_body(path):
    assert empty_function_bodies(path.read_text(encoding="utf-8")) == []


def test_completion_checks_can_fail():
    assert empty_function_bodies("def f():\n    pass\n")
    assert empty_function_bodies("def f():\n    '''d'''\n    ...\n")
    assert empty_function_bodies("def f():\n    return 1\n") == []
    assert placeholder_markers("# TODO later")
    assert placeholder_markers("todo = 1") == []


@pytest.mark.parametrize("name", sorted(AUDITED_MODULES))
def test_completion_import_audit(name):
    roots = imported_roots(AUDITED_MODULES[name].read_text(encoding="utf-8"))
    assert roots <= ALLOWED_ROOTS, sorted(roots - ALLOWED_ROOTS)
    forbidden = HOST_FORBIDDEN if name == "dis7_host.py" else ADAPTER_FORBIDDEN
    assert not roots & forbidden, sorted(roots & forbidden)


def test_completion_prototype_is_never_imported():
    importers = [path.relative_to(PACKAGE_DIR).as_posix() for path in sorted(PACKAGE_DIR.rglob("*.py"))
                 if "examples" in imported_roots(path.read_text(encoding="utf-8"))]
    assert importers == []
    for path in AUDITED_MODULES.values():
        text = path.read_text(encoding="utf-8")
        assert "examples.dis7" not in text and "examples/dis7" not in text, path.name


def test_completion_adapter_reports_1_0_0():
    from synapse_cdm.adapters.dis7 import Dis7Adapter

    assert Dis7Adapter.version == "1.0.0"
    assert Dis7Adapter.name == "dis7"


def test_completion_claims_guard():
    texts = _claim_texts()
    for where, text in texts.items():
        assert text.strip(), f"{where}: the DIS 7 text was not found"
    assert "Entity State subset" in texts["README"]
    assert "Entity State subset" in texts["dis7.mdx"]
    claims = {where: claim_sentences(text) for where, text in texts.items()}
    assert claims == {where: [] for where in texts}


AVAILABILITY = ("The `dis7` adapter and the `synapse-dis7` command are part of the distribution "
                "built from this tree; no release before 3.2.0 carries them.")


def test_completion_availability_is_stated():
    flat = {where: " ".join(text.split()) for where, text in _claim_texts().items()}
    assert AVAILABILITY in flat["dis7.mdx"]
    assert "part of the distribution built from this tree; no release before 3.2.0 carries them" in flat["README"]
    for path in (REPO_ROOT / "README.md", REPO_ROOT / "docs" / "docs" / "intro.mdx"):
        assert AVAILABILITY in " ".join(path.read_text(encoding="utf-8").split()), path


def test_completion_claims_guard_can_fail():
    assert claim_sentences("It provides full DIS 7 support.")
    assert claim_sentences("The adapter is IEEE certified.")
    assert claim_sentences("It is not full DIS 7 support.") == []
    assert claim_sentences("It carries no IEEE certification.") == []
