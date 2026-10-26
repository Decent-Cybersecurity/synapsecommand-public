"""The distribution as packaged: version, metadata, dependencies, the bundled schema, the test
configuration and markers, and what its documents may and may not say. Reads only
`packages/imagery` and the installed `synapse_cdm`."""

from __future__ import annotations

import ast
import hashlib
import pathlib
import re
import tomllib

import synapse_imagery
from synapse_imagery import _version

DISTRIBUTION = pathlib.Path(synapse_imagery.__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((DISTRIBUTION / "pyproject.toml").read_text(encoding="utf-8"))
README = (DISTRIBUTION / "README.md").read_text(encoding="utf-8")
KIT_RESULT_SCHEMA_SHA256 = "9b9fa1c7e26e229a765d0fffbc8b1cb2f85bcd301767bc1651e6d0e64e60ef65"
TEST_COMMANDS = [
    "cd packages/imagery && python -m pytest -q -rs",
    "cd packages/imagery && python -m pytest -q -m linux",
    'cd packages/imagery && python -m pytest -q -m "not linux" --ignore=tests/test_imagery_repo.py',
    "ruff check --config packages/imagery/pyproject.toml packages/imagery",
]


def test_the_version_names_the_host_and_not_the_cdm():
    assert _version.__version__ == "1.0.0" == synapse_imagery.__version__
    assert synapse_imagery.__all__ == ["__version__"]


def test_the_project_table():
    project = PYPROJECT["project"]
    assert project["name"] == "synapse-imagery"
    assert project["dynamic"] == ["version"]
    assert project["dependencies"] == ["synapse-cdm>=3.10.0,<4", "jsonschema>=4.0"]
    assert project["scripts"] == {"sc-imagery": "synapse_imagery.cli:main"}
    assert "optional-dependencies" not in project
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    assert project["requires-python"] == ">=3.11"
    assert "Operating System :: POSIX :: Linux" in project["classifiers"]
    assert PYPROJECT["build-system"]["requires"] == ["setuptools>=77"]
    assert PYPROJECT["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "synapse_imagery._version.__version__"
    }
    assert PYPROJECT["tool"]["setuptools"]["package-data"] == {
        "synapse_imagery": ["contracts/*.json"]
    }


def test_the_bundled_result_schema_is_the_kits():
    data = (
        DISTRIBUTION / "synapse_imagery" / "contracts" / "ingest-result.schema.json"
    ).read_bytes()
    assert hashlib.sha256(data).hexdigest() == KIT_RESULT_SCHEMA_SHA256


def test_the_installed_cdm_carries_the_adapter_features_the_host_needs():
    from synapse_cdm.adapters.stanag4545 import (
        CORE1_LIMITS,
        assess_security,
        parse_container,
        security_labels,
    )

    assert callable(assess_security) and callable(security_labels) and callable(parse_container)
    assert CORE1_LIMITS.input_bytes == 16_777_216


def test_the_pytest_table_deselects_linux_and_registers_one_marker():
    table = PYPROJECT["tool"]["pytest"]["ini_options"]
    assert table["addopts"] == [
        "-p",
        "no:cacheprovider",
        "--strict-markers",
        "--strict-config",
        "-m",
        "not linux",
    ]
    assert table["filterwarnings"] == ["error"]
    assert table["testpaths"] == ["tests"] and table["pythonpath"] == ["."]
    assert [marker.split(":")[0] for marker in table["markers"]] == ["linux"]
    assert PYPROJECT["tool"]["ruff"] == {
        "line-length": 100,
        "target-version": "py311",
        "lint": {"select": ["E9", "F", "E7", "W"]},
    }


def _marked_linux(node: ast.AST) -> bool:
    return any(
        "linux" in ast.unparse(decorator) for decorator in getattr(node, "decorator_list", [])
    )


def test_every_linux_test_lives_in_the_linux_module():
    found = {}
    for path in sorted((DISTRIBUTION / "tests").glob("test_imagery_*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        module_marked = any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "pytestmark"
                for target in node.targets
            )
            and "linux" in ast.unparse(node.value)
            for node in module.body
        )
        tests = [
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        marked = {node.name for node in tests if module_marked or _marked_linux(node)}
        if marked:
            found[path.name] = (marked, {node.name for node in tests})
    assert list(found) == ["test_imagery_linux.py"]
    marked, everything = found["test_imagery_linux.py"]
    assert marked == everything and len(marked) >= 3


def test_the_readme_states_the_four_test_commands():
    block = re.search(r"## Tests\n\n```bash\n(.*?)```", README, re.S)
    assert block and block.group(1).splitlines() == TEST_COMMANDS


def test_the_readme_states_the_darwin_memory_sentence_and_the_tag_install():
    assert (
        "On macOS the worker's 512 MiB address-space cap is not enforced: the kernel refuses "
        "`RLIMIT_AS` at that value. Records and inspect output say `memory_enforcement: not_enforced` "
        "there; the deadlines, the single-threaded worker and the core caps still apply. On Linux the "
        "cap is set with `RLIMIT_AS` and enforced by the kernel."
    ) in README
    assert (
        'pip install "synapse-imagery @ git+https://github.com/Decent-Cybersecurity/'
        'synapsecommand-public@v3.10.0#subdirectory=packages/imagery"'
    ) in README
    writer = README.split("## The experimental writer", 1)[1].split("\n## ", 1)[0]
    assert "experimental" in writer


def _texts():
    for path in sorted(DISTRIBUTION.rglob("*")):
        if (
            path.is_file()
            and path.suffix in (".py", ".md", ".toml")
            and path.name not in ("LICENSE", "NOTICE")
        ):
            yield path, path.read_text(encoding="utf-8")


def test_no_document_makes_a_forbidden_claim_or_a_trap_phrase():
    # Every phrase is built from parts: the repository's own sweeps read this file too.
    claims = [
        "SC-OES " + "Certified",
        "Official SynapseCommand " + "Partner",
        "Approved by Decent " + "Cybersecurity",
        "NATO " + "Certified",
        "NATO " + "Approved",
    ]
    traps = [
        re.compile(r"\bun" + "published\\b", re.I),
        re.compile(r"not (yet )?on py" + "pi", re.I),
    ]
    spdx = re.compile("SPDX-" + "(License-Identifier|FileCopyrightText)")
    notice = re.compile(r"(?i)\bcopy" + r"right\b\s*(\(c\)|©|\d{4})")
    standard = re.compile("NATO " + "Standard(?!i)")
    for path, text in _texts():
        for claim in claims:
            assert claim not in text, (path.name, claim)
        assert not standard.search(text), path.name
        for trap in traps:
            assert not trap.search(text), (path.name, trap.pattern)
        assert not spdx.search(text) and not notice.search(text), path.name


def test_no_document_claims_compressed_support():
    phrases = [
        re.compile(pattern, re.I)
        for pattern in ("supports JPEG", "JPEG 2000 support", "JPEG2000 support")
    ]
    for path, text in _texts():
        if path.suffix == ".py":
            docstring = ast.get_docstring(ast.parse(text)) or ""
            text = docstring if "tests" not in path.parts else ""
        for phrase in phrases:
            assert not phrase.search(text), (path.name, phrase.pattern)


# --------------------------------------------------------------------------- the runbook

RUNBOOK = (DISTRIBUTION / "docs" / "runbook.md").read_text(encoding="utf-8")
CLAIM = (
    "Implements the SC4545-CORE-1 NSIF/NITF imagery ingestion profile, with byte-preserving "
    "metadata inventory, specified NC sample decoding and direct geographic footprints."
)
MEMORY_SENTENCE = (
    "On macOS the worker's 512 MiB address-space cap is not enforced: the kernel refuses "
    "`RLIMIT_AS` at that value. Records and inspect output say `memory_enforcement: not_enforced` "
    "there; the deadlines, the single-threaded worker and the core caps still apply. On Linux the "
    "cap is set with `RLIMIT_AS` and enforced by the kernel."
)


def test_the_runbook_has_its_ten_sections_in_order():
    headings = re.findall(r"(?m)^## (.+)$", RUNBOOK)
    assert headings == [
        "1. What this runs",
        "2. Install and the dependency floor",
        "3. The store",
        "4. The five commands",
        "5. Policy",
        "6. The worker and its limits",
        "7. Failure and recovery",
        "8. Replay, preview and the writer",
        "9. What is not claimed",
        "10. The permitted claim text",
    ]


def test_the_runbook_quotes_the_permitted_claim_and_the_memory_sentence_verbatim():
    assert CLAIM in RUNBOOK
    assert MEMORY_SENTENCE in RUNBOOK
    claim_section = RUNBOOK.split("## 10. The permitted claim text", 1)[1]
    assert claim_section.strip() == "> " + CLAIM
    # The claim is stated once, in its own section, and nowhere in the README.
    assert RUNBOOK.count(CLAIM) == 1 and CLAIM not in README


def test_the_runbook_states_the_store_boundary_and_the_lock_coverage():
    flat = " ".join(RUNBOOK.split())
    assert "the store is not a boundary against its own in-process caller" in flat
    assert (
        "so do the creation of a staging directory together with taking its own lock, the last "
        "removal of a staging directory, and the job pass of `recover()`; the lock is never held "
        "across a worker run or a policy call"
    ) in flat


def test_the_runbook_is_clean():
    claims = [
        "SC-OES " + "Certified",
        "Official SynapseCommand " + "Partner",
        "Approved by Decent " + "Cybersecurity",
        "NATO " + "Certified",
        "NATO " + "Approved",
    ]
    for claim in claims:
        assert claim not in RUNBOOK
    assert not re.search("NATO " + "Standard(?!i)", RUNBOOK)
    assert not re.search(r"\bun" + "published\\b", RUNBOOK, re.I)
    assert not re.search(r"not (yet )?on py" + "pi", RUNBOOK, re.I)
    assert not re.search("SPDX-" + "(License-Identifier|FileCopyrightText)", RUNBOOK)
    assert not re.search(r"(?i)\bcopy" + r"right\b\s*(\(c\)|©|\d{4})", RUNBOOK)
    # No measured duration: the only seconds are the two deadlines.
    assert sorted(set(re.findall(r"\b\d+(?:\.\d+)? ?(?:ms|s)\b", RUNBOOK))) == ["30 s", "5 s"]


def test_the_writer_is_experimental_wherever_it_is_named():
    from synapse_imagery import cli, export

    help_text = cli.build_parser()._subparsers._group_actions[0].choices["export-nc"].format_help()
    module_text = ast.get_docstring(
        ast.parse((DISTRIBUTION / "synapse_imagery" / "export.py").read_text())
    )
    writer_section = README.split("## The experimental writer", 1)[1].split("\n## ", 1)[0]
    runbook_section = RUNBOOK.split("## 8.", 1)[1].split("\n## ", 1)[0]
    for text in (help_text, module_text, writer_section, runbook_section):
        assert "experimental" in text.lower()
        assert "not independently qualified" in " ".join(text.split()) or (
            "not independently parsed" in text
        )
        for word in ("conforms", "certified", "compliant"):
            assert word not in text.lower()
    assert export.STATUS == "experimental"
    assert export.QUALIFICATION == (
        "experimental engineering output: not independently parsed, not checked clause by clause "
        "against a normative profile; a self-parse accepting its own file is necessary and "
        "insufficient"
    )


def test_the_readme_and_the_runbook_state_the_claim_boundary():
    readme = " ".join(README.split())
    runbook = " ".join(RUNBOOK.split())
    assert (
        "It is not a codec: only the native uncompressed NC cell decodes, and every compressed or "
        "masked cell is disabled, so no JPEG, JPEG 2000 or other compression is decoded."
    ) in readme
    assert (
        "No codec: only the native uncompressed NC cell decodes, and every compressed or masked "
        "cell is disabled."
    ) in runbook
    for text in (readme, runbook):
        assert "not a classification-policy engine" in text
        assert "cross-domain guard" in text
        assert "not independently qualified" in text
