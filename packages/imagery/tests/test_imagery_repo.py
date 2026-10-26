"""The one module that reads outside `packages/imagery`: the licence copies against the
repository root, the tracked tree against the distribution's ruled layout, the root documents
that name the distribution, and the README's test commands against the checkout they run in. It
runs only from a checkout."""

from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[3]
TOPICS = (
    "policy",
    "lattice",
    "assets",
    "ingest",
    "recovery",
    "result",
    "worker",
    "codec",
    "preview",
    "replay",
    "export",
    "cli",
    "presentation",
    "security",
    "static",
    "release",
    "repo",
    "linux",
)
TREE = {
    "pyproject.toml",
    "LICENSE",
    "NOTICE",
    "README.md",
    "docs/runbook.md",
    "synapse_imagery/__init__.py",
    "synapse_imagery/_version.py",
    "synapse_imagery/__main__.py",
    "synapse_imagery/policy.py",
    "synapse_imagery/assets.py",
    "synapse_imagery/ingest.py",
    "synapse_imagery/worker.py",
    "synapse_imagery/export.py",
    "synapse_imagery/cli.py",
    "synapse_imagery/result.py",
    "synapse_imagery/preview.py",
    "synapse_imagery/presentation.py",
    "synapse_imagery/fakes.py",
    "synapse_imagery/contracts/ingest-result.schema.json",
    "synapse_imagery/contracts/write-nc8-recipe.schema.json",
    "tests/conftest.py",
    "tests/helpers.py",
    "tests/crash_driver.py",
    "tests/sigint_driver.py",
    "tests/slow_child.py",
} | {f"tests/test_imagery_{topic}.py" for topic in TOPICS}


def test_this_is_a_checkout():
    assert (REPO / "packages" / "cdm" / "pyproject.toml").is_file()
    assert (REPO / "packages" / "imagery" / "pyproject.toml").is_file()


def test_the_licence_files_are_byte_copies_of_the_roots():
    for name in ("LICENSE", "NOTICE"):
        assert (REPO / "packages" / "imagery" / name).read_bytes() == (REPO / name).read_bytes()


def test_the_tracked_tree_is_exactly_the_ruled_tree():
    listed = subprocess.run(
        ["git", "ls-files", "packages/imagery"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    tracked = {name.removeprefix("packages/imagery/") for name in listed}
    assert tracked == TREE, (sorted(tracked - TREE), sorted(TREE - tracked))
    assert len(TREE) == 43
    assert not [name for name in tracked if "__pycache__" in name]


def test_the_readme_test_commands_run_from_the_repository_root():
    readme = (REPO / "packages" / "imagery" / "README.md").read_text(encoding="utf-8")
    block = re.search(r"## Tests\n\n```bash\n(.*?)```", readme, re.S)
    assert block, "the README has no Tests block"
    lines = block.group(1).splitlines()
    assert len(lines) == 4
    for line in lines[:3]:
        directory, command = line.split(" && ")
        assert directory == "cd packages/imagery"
        assert (REPO / "packages" / "imagery").is_dir()
        assert command.startswith("python -m pytest -q")
        for argument in command.split():
            if argument.startswith("--ignore="):
                assert (
                    REPO / "packages" / "imagery" / argument.removeprefix("--ignore=")
                ).is_file()
    ruff = lines[3].split()
    assert ruff[:3] == ["ruff", "check", "--config"]
    assert (REPO / ruff[3]).is_file() and (REPO / ruff[4]).is_dir()
    # The marker the second and third commands select is the one the pytest table registers.
    assert '"linux: ' in (REPO / ruff[3]).read_text(encoding="utf-8")


def test_the_root_documents_name_the_distribution_once_each():
    boundary = (REPO / "docs" / "docs" / "sc-oes" / "boundary.mdx").read_text(encoding="utf-8")
    security = (REPO / "SECURITY.md").read_text(encoding="utf-8")
    architecture = (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for text in (boundary, security, architecture):
        assert "synapse-imagery" in text
    assert "The first runtime published here" in boundary
    assert "The one runtime published here" not in boundary
    flat = " ".join(boundary.split())
    assert re.search(
        r"The second, added \d{4}-\d{2}-\d{2}, is the separate distribution `synapse-imagery` under "
        r"`packages/imagery/`: it stages, stores and relays STANAG 4545 imagery for the `stanag4545` "
        r"adapter",
        flat,
    )
    assert "**The imagery host lives outside the registry too (" in architecture
    floor = (REPO / "tests" / "test_cdm_version_floor.py").read_text(encoding="utf-8")
    assert 'REPO / "packages" / "imagery" / "synapse_imagery"' in floor
    assert 'REPO / "packages" / "imagery" / "tests"' in floor
