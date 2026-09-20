"""The generated support matrix, held to the declarations it is rendered from — and to the other
three places that state the same boundary: the manifests, the CLI listing and the adapter classes.

Audit remediation F05 (2026-09-20). The page is a projection, like `manifests/` and `schemas/`,
and a projection is allowed to exist only while something mechanical keeps it identical to its
source. That is `test_the_published_page_is_current` here (the generator's `--check` reads the
same thing for the operator's `.remediation/bin/verify.sh full`; no CI step runs it); the mutation test
below is what proves the check is not vacuous — a registry changed under the renderer must change
the page, or the page is a literal with a table around it.

The page states no adapter count, on purpose, and a test holds it to that: a number before the
word "adapters" is the stale-count class `tests/test_cdm_prose_counts.py` guards, and a generated
page that spelled one would hand that gate a new site.
"""
import json
import pathlib
import re

import pytest

from synapse_cdm import adapter, evidence, harness, support_matrix
from synapse_cdm.adapters import stanag4676 as nits
from synapse_cdm.manifest import WireBinding
from synapse_cdm.normative_binding import BLOCKED_STATUS

from tests import probe_metadata

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE = REPO / support_matrix.DEFAULT_OUT
MANIFESTS = REPO / "manifests"

#: The stale-count shape, as `tests/test_cdm_prose_counts.py`'s `ROSTER_COUNT` reads it:
#: a number, spelled or in digits, within two words of "adapters".
COUNT_BEFORE_ADAPTERS = re.compile(
    r"(?<![\w-])(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
    r"(?:[ -][a-z]+){0,2}[ -](?:adapters|harnesses)(?![\w])", re.I)


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = [m.start() for m in re.finditer(r"(?m)^## ", text) if m.start() > start]
    return text[start:following[0]] if following else text[start:]


# ----------------------------------------------------------------------- the page is current


def test_the_published_page_is_current():
    assert PAGE.is_file(), f"{PAGE} is missing — run python -m synapse_cdm.support_matrix"
    problems = support_matrix.check(PAGE)
    assert not problems, (
        f"{problems}. The page is a projection of the adapter declarations: regenerate it with "
        f"`python -m synapse_cdm.support_matrix --out {support_matrix.DEFAULT_OUT}` rather than "
        "editing it, and never hand-edit a generated file")


def test_the_page_says_it_is_generated_and_names_the_command_that_regenerates_it():
    text = PAGE.read_text()
    assert "GENERATED FILE — DO NOT EDIT" in text
    assert "python -m synapse_cdm.support_matrix --out docs/docs/cdm/support-matrix.mdx" in text
    assert text.startswith("---\ntitle: Adapter support matrix\n")
    assert "sidebar_position: 8" in text.split("---", 2)[1]


def test_the_sidebar_position_is_not_taken_by_another_page_of_the_section():
    positions = {}
    for page in sorted(PAGE.parent.glob("*.mdx")):
        front = page.read_text().split("---", 2)[1]
        found = re.search(r"(?m)^sidebar_position:\s*(\d+)", front)
        assert found, f"{page.name} has no sidebar_position"
        positions.setdefault(int(found.group(1)), []).append(page.name)
    clashes = {k: v for k, v in positions.items() if len(v) > 1}
    assert not clashes, f"two pages share a sidebar position: {clashes}"


def test_the_check_reports_a_missing_and_a_stale_page(tmp_path):
    target = tmp_path / "support-matrix.mdx"
    assert support_matrix.check(target) and "missing" in support_matrix.check(target)[0]
    support_matrix.write(target)
    assert support_matrix.check(target) == []
    target.write_text(target.read_text().replace("provisional-internal-profile", "standard-encoding"))
    assert support_matrix.check(target) and "stale" in support_matrix.check(target)[0]
    assert support_matrix.main(["--check", "--out", str(target)]) == 1
    assert support_matrix.main(["--out", str(target)]) == 0
    assert support_matrix.main(["--check", "--out", str(target)]) == 0


def test_the_renderer_is_deterministic():
    assert support_matrix.render() == support_matrix.render()


# ------------------------------------------------------- the rows are the declarations, all of them


def test_every_shipped_adapter_has_a_row_a_section_and_nothing_else_does():
    text = PAGE.read_text()
    matrix = section(text, "## The matrix")
    names = list(adapter.shipped())
    assert names, "the shipped roster is empty; the registry did not load"
    for name in names:
        assert f"| `{name}` |" in matrix, f"{name} has no row in the matrix"
        assert f"### `{name}` — " in text, f"{name} has no per-adapter section"
    listed = re.findall(r"(?m)^\| `([a-z0-9_]+)` \|", matrix)
    assert listed == names, f"the matrix lists {listed}; the shipped roster is {names}"


def test_a_registry_changed_under_the_renderer_changes_the_page(monkeypatch):
    """THE load-bearing test: the page has to be a function of the registry, not a literal."""
    before = support_matrix.render()
    victim = "cat021"
    trimmed = {k: v for k, v in adapter.shipped().items() if k != victim}
    monkeypatch.setattr(support_matrix, "shipped", lambda: trimmed)
    after = support_matrix.render()
    assert after != before and f"| `{victim}` |" not in after and f"| `{victim}` |" in before

    class Probe(adapter.Adapter):
        name = "zz_probe_f05"
        version = "0.1.0"
        direction = "ingest"
        system = "PROBE"
        metadata = probe_metadata("zz_probe_f05")

        def to_cdm(self, raw):
            return []

    try:
        added = dict(adapter.shipped())
        added[Probe.name] = Probe
        monkeypatch.setattr(support_matrix, "shipped", lambda: added)
        grown = support_matrix.render()
        assert f"| `{Probe.name}` |" in grown and "`standard-encoding`" in grown
        assert "NOT_APPLICABLE — ingest only" in section(grown, "## Evidence scope")
    finally:
        adapter.REGISTRY.pop(Probe.name, None)


@pytest.mark.parametrize("name", sorted(adapter.shipped()))
def test_every_cell_of_a_row_is_the_declaration(name):
    cls = adapter.shipped()[name]
    row = next(r for r in support_matrix.rows() if r["id"] == name)
    meta = cls.metadata
    assert row["binding"] == meta.binding.value
    assert row["direction"] == meta.direction.value
    assert row["directions_exercised"] == list(meta.capabilities.directions_exercised)
    assert row["message_types"] == list(meta.capabilities.message_types)
    assert len(row["limitations"]) == len(meta.limitations)
    assert row["maturity"] == meta.maturity.level.value
    assert row["edition"] == (meta.format.version or "not stated — see the limitations")
    forms = support_matrix.replayed_forms(cls)
    replayed = harness.select_fixtures(adapter.packaged_fixtures(cls))
    assert forms == sorted({"".join(p.suffixes) for p in replayed}), (
        f"{name}: the page lists {forms} and the harness replays {sorted(set(p.name for p in replayed))}")
    assert forms, f"{name}: no replayed form, so the harness would replay nothing"


# -------------------------------------------------- one boundary, stated the same way everywhere


@pytest.mark.parametrize("name", sorted(adapter.shipped()))
def test_the_page_the_manifest_the_listing_and_the_class_agree_on_the_binding(name):
    cls = adapter.shipped()[name]
    declared = cls.metadata.binding.value
    published = json.loads((MANIFESTS / f"{name}.json").read_text())["adapter"]["binding"]
    assert published == declared, f"{name}: manifests/{name}.json says {published}"
    matrix = section(PAGE.read_text(), "## The matrix")
    row = next(line for line in matrix.splitlines() if line.startswith(f"| `{name}` |"))
    assert f"`{declared}`" in row, f"{name}: the matrix row does not carry {declared}"
    listing = harness.render_roster(adapter.roster())
    line = next(line for line in listing.splitlines() if line.startswith(name + " "))
    assert line.rstrip().endswith(declared), f"{name}: --list-adapters ends its row with {line!r}"


def test_stanag4676_is_provisional_and_every_other_shipped_adapter_is_the_standard_encoding():
    """Derived, not typed: an adapter whose limitations say "provisional" declares the provisional
    binding and the reverse — the model enforces one direction, this test the other."""
    from synapse_cdm.manifest import limitation_text
    bindings = {name: cls.metadata.binding for name, cls in adapter.shipped().items()}
    says_provisional = {name for name, cls in adapter.shipped().items()
                        if any("provisional" in limitation_text(line).lower()
                               for line in cls.metadata.limitations)}
    declares_provisional = {name for name, b in bindings.items()
                            if b is WireBinding.PROVISIONAL_INTERNAL_PROFILE}
    assert says_provisional == declares_provisional == {"stanag4676"}
    assert not [name for name, b in bindings.items() if b is WireBinding.NORMATIVE_VERIFIED], (
        "an adapter declares normative-verified; tests/test_cdm_manifests.py holds that to an "
        "exercise report and this page's status paragraph would have to move")


# ------------------------------------------------------------------------ the evidence-scope table


def test_the_evidence_scope_columns_are_the_five_categories_in_the_enums_order():
    scope = section(PAGE.read_text(), "## Evidence scope")
    header = next(line for line in scope.splitlines() if line.startswith("| adapter |"))
    assert header == "| adapter | " + " | ".join(f"`{c.value}`" for c in evidence.EvidenceCategory) + " |"


@pytest.mark.parametrize("name", sorted(adapter.shipped()))
def test_the_evidence_scope_follows_the_declaration(name):
    cls = adapter.shipped()[name]
    scope = support_matrix.evidence_scope(cls)
    assert set(scope) == {c.value for c in evidence.EvidenceCategory}
    assert scope["internal_fixture"].startswith("internal")
    if "egress" in cls.metadata.capabilities.directions_exercised:
        assert scope["self_round_trip"].startswith("internal") and "not independence" in scope[
            "self_round_trip"]
    else:
        assert scope["self_round_trip"].startswith("NOT_APPLICABLE")
    for category in evidence.EXTERNAL_CATEGORIES:
        assert scope[category.value] == "ABSENT — " + evidence.EXTERNAL_ABSENT_BASIS[category], (
            f"{name}: {category.value} reads {scope[category.value]!r}; no exercise report "
            "exists and external_exercise is null, so the reading is ABSENT with the record's "
            "own basis")


def test_the_scope_would_move_with_a_declared_external_exercise_or_a_verified_binding():
    from synapse_cdm.manifest import AdapterMetadata, ExternalExercise, Maturity, MaturityLevel
    base = probe_metadata("zz_scope").model_dump()

    class Shell:
        pass

    verified = dict(base)
    verified["binding"] = WireBinding.NORMATIVE_VERIFIED
    Shell.metadata = AdapterMetadata(**verified)
    assert support_matrix.evidence_scope(Shell)["normative_schema"].startswith("declared")

    exercised = dict(base)
    # L6 is the one rung an `external_exercise` may sit on (the model refuses it lower down).
    exercised["maturity"] = Maturity(
        level=MaturityLevel.L6, basis="a probe",
        external_exercise=ExternalExercise(system="an independent implementation",
                                           date="2026-01-01", record="docs/exercise.md"))
    Shell.metadata = AdapterMetadata(**exercised)
    assert "declared — exercised against an independent implementation" in \
        support_matrix.evidence_scope(Shell)["independent_endpoint"]


# -------------------------------------------------------------- the STANAG 4676 section, derived


def test_the_stanag4676_section_states_the_profile_the_mode_the_hook_and_the_procedure():
    text = section(PAGE.read_text(), "## STANAG 4676")
    assert f"`binding: {nits.BINDING_PROVISIONAL}`" in text
    assert f"`{nits.BINDING_ENV}={nits.BINDING_NORMATIVE}`" in text
    assert f"`{nits.XSD_DIR_ENV}`" in text and f"`{nits.XSD_RECORD_NAME}`" in text
    for name in nits.XSD_FILES:
        assert f"`{name}`" in text
    for field in nits.XSD_RECORD_FIELDS:
        assert f"`{field}`" in text
    assert f"`{BLOCKED_STATUS}`" in text and BLOCKED_STATUS == "BLOCKED_EXTERNAL_EVIDENCE"
    for index, (step, _) in enumerate(nits.NORMATIVE_PROCEDURE, 1):
        assert f"{index}. **`{step}`**" in text, f"step {step} is not in the procedure list"
    assert "never falls back" in text
    assert "`normative_schema`" in text and "`normative-verified`" in text


def test_the_page_states_no_adapter_count():
    text = PAGE.read_text()
    hits = [m.group(0) for m in COUNT_BEFORE_ADAPTERS.finditer(text)]
    assert not hits, (
        f"the generated page states an adapter count {hits}; a count in prose is the stale-count "
        "class tests/test_cdm_prose_counts.py guards, and the page lists what ships instead")


def test_mdx_escaping_leaves_code_spans_alone_and_neutralises_jsx_outside_them():
    assert support_matrix.mdx("`<NITSRoot>` and {x}") == "`<NITSRoot>` and &#123;x&#125;"
    assert support_matrix.mdx("<b> a | b") == "&lt;b&gt; a \\| b"
    assert support_matrix.mdx("`a | b`") == "`a \\| b`"
    for line in PAGE.read_text().splitlines():
        if line.startswith("|"):
            outside = re.sub(r"`[^`]*`", "", line)
            assert "<" not in outside and "{" not in outside, f"unescaped JSX in a table cell: {line[:80]}"
