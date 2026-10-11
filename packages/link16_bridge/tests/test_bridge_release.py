"""Release facts of the distribution: version, dependency floor, workflow, documents, licence
copies, the requirement matrix, and the claim boundary (REQ134, REQ180-182, REQ191)."""
import ast
import json
import pathlib
import re
import subprocess
import sys
import tomllib

import pytest

from helpers import REPO
from synapse_link16_bridge import _version, cli, contract

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
DOCUMENTS = [ROOT / "README.md", ROOT / "docs" / "requirements-matrix.md",
             ROOT / "docs" / "operations.md"]
SOURCES = sorted((ROOT / "synapse_link16_bridge").rglob("*.py"))
WORKFLOW = None if REPO is None else REPO / ".github" / "workflows" / "gateway-bridge.yml"
repo_bound = pytest.mark.skipif(REPO is None, reason="repository-bound: reads files that exist "
                                                     "only in a checkout of the repository")


def test_the_version_is_1_0_0_and_dynamic():
    assert _version.__version__ == "1.0.0"
    assert PYPROJECT["project"]["dynamic"] == ["version"]
    assert PYPROJECT["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "synapse_link16_bridge._version.__version__"}


def test_the_dependency_floor_and_the_absence_of_a_test_extra():
    project = PYPROJECT["project"]
    assert project["name"] == "synapse-link16-bridge"
    assert project["dependencies"] == ["synapse-cdm>=3.4.0,<4"]
    assert "optional-dependencies" not in project
    assert project["requires-python"] == ">=3.11"
    assert (project["license"], project["license-files"]) == ("Apache-2.0", ["LICENSE", "NOTICE"])
    assert project["scripts"] == {"synapse-link16-bridge": "synapse_link16_bridge.cli:main"}
    assert PYPROJECT["build-system"]["requires"] == ["setuptools>=77"]


def test_the_installed_cdm_is_held_to_features_never_to_its_number():
    from synapse_cdm.adapter import REGISTRY, discover
    from synapse_cdm.enums import PositionSource
    discover()
    assert (PositionSource.SENSOR.value, PositionSource.UNKNOWN.value) == ("SENSOR", "UNKNOWN")
    assert REGISTRY["link16_gateway"].__module__ == "synapse_cdm.adapters.link16_gateway"


def _readme_test_commands() -> list[str]:
    """The command block of the README's "Tests" section, line by line."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme.split("\n## Tests\n", 1)[1].split("```bash\n", 1)[1].split("```", 1)[0]
    return [line.strip() for line in block.splitlines() if line.strip()]


@repo_bound
def test_the_workflow_runs_the_readme_commands_with_the_pinned_actions():
    text = WORKFLOW.read_text(encoding="utf-8")
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    documented = _readme_test_commands()
    assert len(documented) == 5
    *installs_and_lint, last = documented
    workflow_lines = [line.strip().removeprefix("run: ") for line in text.splitlines()
                      if re.match(r"\s+(python -m pip install|run: ruff check)", line)]
    assert workflow_lines == installs_and_lint
    directory, command = last.split(" && ")
    assert f"working-directory: {directory.removeprefix('cd ')}\n        run: {command}\n" in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.index("pip install synapse-cdm\n") < readme.index(installs_and_lint[0])
    for pin in ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1",
                "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97  # v7.0.0"):
        assert pin in text and pin in ci
    assert "on:\n  push:\n    branches:\n      - main\n      - 'soif/**'\n\n" in text
    assert "permissions:\n  contents: read\n" in text and "persist-credentials: false" in text
    versions = re.search(r"python: \[([^\]]*)\]", text).group(1)
    classifiers = [c.rsplit(" ", 1)[1] for c in PYPROJECT["project"]["classifiers"]
                   if re.fullmatch(r"Programming Language :: Python :: 3\.[0-9]+", c)]
    assert [v.strip(" '") for v in versions.split(",")] == classifiers == \
        ["3.11", "3.12", "3.13", "3.14"]
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for banned in ("pull_request", "secrets.", "id-token", "schedule", "workflow_dispatch"):
        assert banned not in code
    for line in text.splitlines():
        if line.strip().startswith("run:") or line.startswith(("          python -m",
                                                                "          set ")):
            assert "${{" not in line


def _forbidden_claims() -> list[str]:
    """The forbidden claims, read from the conventions at run time and never quoted here."""
    text = (REPO / "spec" / "sc-oes" / "00-conventions.md").read_text(encoding="utf-8")
    block = text.split("Forbidden claims", 1)[1].split("```text", 1)[1].split("```", 1)[0]
    claims = [line.strip() for line in block.splitlines() if line.strip()]
    assert len(claims) >= 5
    return claims


@repo_bound
def test_documents_make_no_native_or_certification_claim():
    """REQ134: no forbidden claim in the documents, the sources or the CLI help; the limitation
    sentence is present."""
    claims = _forbidden_claims()
    help_text = subprocess.run([sys.executable, "-c",
                                "import sys; from synapse_link16_bridge import cli; "
                                "cli.parser().print_help(); sys.exit(0)"],
                               cwd=str(ROOT), capture_output=True, text=True).stdout
    texts = {str(p): p.read_text(encoding="utf-8") for p in DOCUMENTS + SOURCES}
    texts["--help"] = help_text
    for where, text in texts.items():
        for claim in claims:
            assert claim not in text, where
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert ("no claim of native interoperability, radio participation, encryption,\nanti-jam "
            "behaviour, spectrum authorisation, national accreditation or certification") in readme
    assert "not JREAP C and not Link 16" in readme
    assert "no native JREAP C or Link 16 codec" in help_text.replace("\n", " ").replace("  ", " ")


def test_no_numeric_score_anywhere():
    """REQ180: every mention of a score says that none is given."""
    for path in DOCUMENTS + SOURCES:
        text = re.sub(r"`[^`]*`", "", path.read_text(encoding="utf-8")).replace("\n", " ")
        for match in re.finditer(r"score", text, re.IGNORECASE):
            window = text[max(0, match.start() - 60):match.end() + 10].lower()
            assert "no numerical" in window or "not award" in window or "no score" in window, \
                (path.name, window)


def test_the_bridge_embeds_no_cdm_schema():
    for path in [p for p in ROOT.rglob("*") if p.is_file() and ".json" in p.suffixes]:
        raise AssertionError(f"a JSON file in the distribution: {path}")
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        assert "x-cdm-schema-version" not in text and "entity.schema.json" not in text, path.name
    assert contract.API_SCHEMA["$id"].startswith("urn:synapsecommand:sc-link16-gateway:")


@repo_bound
def test_the_licence_files_are_byte_copies():
    for name in ("LICENSE", "NOTICE"):
        assert (ROOT / name).read_bytes() == (REPO / name).read_bytes()


def _cited_tests(text: str) -> set[tuple[str, str]]:
    return set(re.findall(r"`(test_bridge_[a-z_0-9]+\.py)::(test_[a-z_0-9]+)`", text))


def test_every_test_the_matrix_cites_exists():
    text = (ROOT / "docs" / "requirements-matrix.md").read_text(encoding="utf-8")
    cited = _cited_tests(text)
    assert len(cited) > 120
    defined = {}
    for module in TESTS.glob("test_bridge_*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        defined[module.name] = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    missing = sorted(f"{m}::{t}" for m, t in cited if t not in defined.get(m, set()))
    assert missing == []


REQ_IDS = ("001 002 003 004 005 006 010 011 012 013 014 020 021 022 030 031 032 033 040 041 050 "
           "051 052 060 061 062 063 064 065 070 071 072 073 074 080 081 082 083 084 085 090 091 "
           "092 093 094 095 096 097 100 101 102 103 104 105 106 110 111 112 113 114 115 120 121 "
           "122 130 131 132 133 134 140 141 150 151 160 161 162 170 180 181 182 190 191 192")
ROWS = ("C01 C02 C03 C04 P01 P02 P03 P04 V01 V02 V03 I01 I02 I03 I04 A01 T01 T02 T03 T04 N01 N02 "
        "N03 N04 N05 N06 L01 L02 L03 E01 E02 E03 E04 E05 E06 R01 R02 R03 S01 S02 F01 F02 G01 G02 "
        "G03")


def test_the_matrix_has_every_requirement_and_acceptance_row_once():
    text = (ROOT / "docs" / "requirements-matrix.md").read_text(encoding="utf-8")
    requirement_rows = re.findall(r"^\| REQ([0-9]{3}) \|", text, re.MULTILINE)
    acceptance_rows = re.findall(r"^\| ([A-Z][0-9]{2}) \|", text, re.MULTILINE)
    assert requirement_rows == REQ_IDS.split() and len(requirement_rows) == 83
    assert acceptance_rows == ROWS.split() and len(acceptance_rows) == 45


def test_the_cli_names_every_subcommand_the_readme_documents():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    documented = re.findall(r"^synapse-link16-bridge ([a-z-]+)", readme, re.MULTILINE)
    commands = cli.parser()._subparsers._group_actions[0].choices
    assert sorted(documented) == sorted(commands)
    assert json.loads(json.dumps(sorted(commands))) == sorted(commands)
