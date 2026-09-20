"""The current-contracts page, against the package it summarises.

WHY THIS EXISTS
---------------
Audit finding F09 (2026-09-20): a new implementer could not find the current contract without
reading thousands of lines of history, and the current documents stated figures — counts, line
citations, version readings — that went stale silently. `docs/docs/current-contracts.mdx` is the
entry page that answers the first half, and this module is what keeps it from becoming the second:

1. The page exists, is in the sidebar, and its generated block is byte-for-byte what
   `gates/current_contracts.py` renders from the installed package (the same arrangement as the
   support matrix — a rendered page and a `--check` that refuses drift).
2. The check can fail: a page whose block was edited by hand, a page with no block, and a missing
   page are each reported, so a PASS above is not a pass by finding nothing.
3. Every relative link the page makes resolves to a page in the tree, and every root document it
   routes to exists. A routing page with a dead link is the defect it exists to fix.
4. The page states no line citation and no adapter count. Both are the brittle figures the finding
   named, and the page's job is to route to derived values, not to add typed ones.
"""
import pathlib
import re
import subprocess
import sys

import pytest

from gates import current_contracts as cc

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCS = REPO / "docs" / "docs"
PAGE = DOCS / "current-contracts.mdx"

#: The sections the brief requires the entry page to route to, each by a heading it must carry.
REQUIRED_SECTIONS = (
    "## Version policy",
    "## Validation levels and the semantic corpus",
    "## Parser limits and the deployment envelope",
    "## Evidence definitions",
    "## Support matrix",
    "## Where the history lives",
)

RELATIVE_LINK = re.compile(r"\]\((\./[^)#]+)(?:#[^)]*)?\)")
ROOT_LINK = re.compile(
    r"https://github\.com/Decent-Cybersecurity/synapsecommand-public/(?:blob|tree)/main/([^)#]+)")


def body() -> str:
    assert PAGE.exists(), f"{PAGE.relative_to(REPO)} is missing"
    return PAGE.read_text(encoding="utf-8")


# ------------------------------------------------------------------------ the page and its block


def test_the_page_carries_the_sections_the_finding_requires():
    text = body()
    missing = [heading for heading in REQUIRED_SECTIONS if heading not in text]
    assert not missing, f"current-contracts.mdx no longer carries {missing}"


def test_the_generated_block_is_what_the_package_renders_today():
    """THE CHECK: the same one `verify.sh full` and a contributor run from the command line."""
    assert cc.check(PAGE) == [], "\n".join(cc.check(PAGE))


def test_the_rendered_block_states_every_version_constant_by_name_and_reading():
    from synapse_cdm import version
    block = cc.render()
    for _axis, const in cc.AXES:
        assert f"`{const}` | `{getattr(version, const)}`" in block, (
            f"the rendered block does not carry {const}'s reading beside its name")


def test_the_rendered_block_is_platform_independent():
    """No `sys.platform` reading may reach the block: a block rendered on macOS and one rendered
    on Linux CI must compare equal, or `--check` would fail on whichever platform did not render
    the committed page."""
    block = cc.render()
    for word in ("darwin", "linux", "win32", sys.platform, "macOS", "Windows"):
        assert word not in block, f"the block carries the platform-specific word {word!r}"


# --------------------------------------------------------------------------- the check can fail


def test_the_check_reports_a_missing_page_a_markerless_page_and_a_stale_block(tmp_path):
    missing = tmp_path / "current-contracts.mdx"
    assert cc.check(missing) and "missing" in cc.check(missing)[0]

    markerless = tmp_path / "markerless.mdx"
    markerless.write_text("# No block here\n", encoding="utf-8")
    assert cc.check(markerless) and "no generated block" in cc.check(markerless)[0]

    stale = tmp_path / "stale.mdx"
    stale.write_text("intro\n\n" + cc.BEGIN + "\nhand-typed figure\n" + cc.END + "\n\noutro\n",
                     encoding="utf-8")
    assert cc.check(stale) and "not what the package renders" in cc.check(stale)[0]

    cc.write(stale)
    assert cc.check(stale) == []
    text = stale.read_text(encoding="utf-8")
    assert text.startswith("intro\n\n") and text.endswith("\n\noutro\n"), (
        "--write touched the prose outside the markers")


def test_the_command_line_check_exits_nonzero_on_a_stale_page(tmp_path):
    stale = tmp_path / "stale.mdx"
    stale.write_text(cc.BEGIN + "\nstale\n" + cc.END + "\n", encoding="utf-8")
    run = subprocess.run([sys.executable, "gates/current_contracts.py", "--check",
                          "--page", str(stale)], cwd=REPO, capture_output=True, text=True)
    assert run.returncode == 1 and "not what the package renders" in run.stderr
    ok = subprocess.run([sys.executable, "gates/current_contracts.py", "--check"], cwd=REPO,
                        capture_output=True, text=True)
    assert ok.returncode == 0 and "CURRENT" in ok.stdout, ok.stderr


# ------------------------------------------------------------------------------- the links hold


def test_every_relative_link_on_the_page_resolves_to_a_page_in_the_tree():
    dead = [link for link in RELATIVE_LINK.findall(body()) if not (DOCS / link).exists()]
    assert not dead, f"current-contracts.mdx links to pages that do not exist: {dead}"


def test_every_root_document_the_page_routes_to_exists():
    dead = [rel for rel in ROOT_LINK.findall(body()) if not (REPO / rel).exists()]
    assert not dead, f"current-contracts.mdx routes to repository paths that do not exist: {dead}"


def test_the_link_sweeps_are_not_vacuous():
    text = body()
    assert len(RELATIVE_LINK.findall(text)) >= 8, "the page no longer links into the docs tree"
    assert len(ROOT_LINK.findall(text)) >= 5, "the page no longer routes to the root documents"


# ------------------------------------------------------------- no brittle figure of its own


def test_the_page_states_no_line_citation():
    cited = re.findall(r"\b[\w/]+\.py:\d+", body())
    assert not cited, (
        f"current-contracts.mdx cites source lines {cited}; a line citation is the figure that "
        "goes stale silently, and the page routes to derived values instead")


def test_the_page_states_no_adapter_count():
    words = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|" \
            "fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
    counted = re.findall(rf"(?<![\w-])(?:{words}|\d{{1,3}})(?:[ -][a-z]+){{0,2}}[ -]adapters\b",
                         body(), re.I)
    assert not counted, (
        f"current-contracts.mdx states an adapter count {counted}; the roster is the support "
        "matrix's to render, not this page's to type")


def test_the_page_is_in_the_sidebar_at_a_position_no_top_level_page_shares():
    front = body().split("---", 2)[1]
    found = re.search(r"(?m)^sidebar_position:\s*([\d.]+)", front)
    assert found, "current-contracts.mdx has no sidebar_position"
    mine = float(found.group(1))
    others = {}
    for page in DOCS.glob("*.mdx"):
        if page == PAGE:
            continue
        head = page.read_text(encoding="utf-8").split("---", 2)[1]
        match = re.search(r"(?m)^sidebar_position:\s*([\d.]+)", head)
        if match:
            others[page.name] = float(match.group(1))
    for name, position in others.items():
        assert position != mine, f"{name} shares sidebar position {mine}"
    assert mine < min(p for n, p in others.items() if n != "intro.mdx"), (
        "the entry page sits below the first section; it is the page a new reader opens second")


@pytest.mark.parametrize("marker", [cc.BEGIN, cc.END])
def test_the_markers_are_mdx_comments_and_not_html_ones(marker):
    assert marker.startswith("{/*") and marker.endswith("*/}"), (
        "an HTML comment is not MDX and would fail the site build; the markers must be MDX ones")
