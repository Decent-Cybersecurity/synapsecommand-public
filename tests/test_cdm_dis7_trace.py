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


def test_completion_claims_guard_can_fail():
    assert claim_sentences("It provides full DIS 7 support.")
    assert claim_sentences("The adapter is IEEE certified.")
    assert claim_sentences("It is not full DIS 7 support.") == []
    assert claim_sentences("It carries no IEEE certification.") == []
