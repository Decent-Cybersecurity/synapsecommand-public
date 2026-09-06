"""The conformance implementation and the normative documents are one fact, stated twice.

`synapse_cdm/conformance.py` implements what `spec/sc-oes/13-conformance.md`,
`spec/sc-oes/00-conventions.md`, `docs/adr/0009-conformance-model.md` and the seven profile
documents under `spec/sc-oes/profiles/` fix. None of those files ships in the wheel — they are
the repository's normative tree, not the distribution's — so this module is REPOSITORY-BOUND
(`gates/wheel_install.py`) and its package-only counterpart is `tests/test_cdm_conformance.py`,
which exercises the same rules against objects. The split is `test_cdm_registry.py` /
`test_cdm_ontology.py`'s exactly: a check against the artefacts travels with them, a check
against the authority stays where the authority is.

THE PROFILE CHECK IS THE ONE THAT MATTERS. Dimension D is `SKIP` for all seven profiles in
v0.1.0 because every profile document says a D assessment against it has no rules to check. The
day a profile acquires normative content, `PROFILE_RULES` must acquire its rules — and without
the test below, the tool would go on reporting `SKIP` with a detail line that had quietly become
false. A verdict that cannot change is the shape this repository treats as a defect.
"""
import pathlib
import re

import pytest

from synapse_cdm.conformance import (
    DIMENSIONS,
    EXIT_FAILED,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_USAGE,
    FAIL,
    PASS,
    PROFILE_RULES,
    SKIP,
    UNASSESSED_THIRD_PARTY_TERM,
)
from synapse_cdm.oes_registry import PROFILES

REPO = pathlib.Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "sc-oes"
CONFORMANCE_DOC = SPEC / "13-conformance.md"
CONVENTIONS_DOC = SPEC / "00-conventions.md"
ADR = REPO / "docs" / "adr" / "0009-conformance-model.md"
PROFILE_DOCS = {name: SPEC / "profiles" / f"{name.lower()}.md" for name in PROFILES}

#: The sentence every profile stub carries in its "Conformance" section. When one of them stops
#: carrying it, that profile has normative content and `PROFILE_RULES` owes it rules.
NO_RULES_SENTENCE = "has no rules to check"


def test_the_documents_this_module_judges_are_all_present():
    """A prose gate whose files have moved passes vacuously; this is what stops that."""
    for path in [CONFORMANCE_DOC, CONVENTIONS_DOC, ADR, *PROFILE_DOCS.values()]:
        assert path.is_file(), path


def test_the_normative_document_names_the_same_five_dimensions_in_the_same_order():
    text = CONFORMANCE_DOC.read_text()
    block = re.search(r"## The five dimensions\n\n```text\n(.*?)```", text, re.S)
    assert block, "13-conformance.md no longer states the dimension list as a text block"
    listed = [line.split("—")[0].strip() for line in block.group(1).strip().splitlines()]
    assert listed == [d.key for d in DIMENSIONS]
    for d in DIMENSIONS:
        assert f"## Dimension {d.key} —" in text


def test_the_normative_document_states_the_same_three_verdicts():
    block = re.search(r"## The three verdicts\n\n```text\n(.*?)```",
                      CONFORMANCE_DOC.read_text(), re.S)
    assert block
    assert block.group(1).split() == [PASS, FAIL, SKIP]


def test_the_exit_codes_in_the_document_are_the_modules_constants():
    text = CONFORMANCE_DOC.read_text()
    block = re.search(r"## Exit codes\n\n.*?```text\n(.*?)```", text, re.S)
    assert block
    stated = {int(line.split()[0]): line.split(maxsplit=1)[1].strip()
              for line in block.group(1).strip().splitlines() if line.strip()}
    assert sorted(stated) == [EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERNAL]
    assert "no requested dimension FAILed" in stated[EXIT_OK]
    assert "requested dimensions FAILed" in stated[EXIT_FAILED]
    assert "usage error" in stated[EXIT_USAGE]
    assert "internal execution error" in stated[EXIT_INTERNAL]


def test_the_document_and_the_adr_both_carry_the_third_party_reporting_string():
    """§39 fixes it, so it is part of the report's surface and moving it is consumer-visible."""
    assert UNASSESSED_THIRD_PARTY_TERM in CONFORMANCE_DOC.read_text()
    assert UNASSESSED_THIRD_PARTY_TERM in ADR.read_text()


def test_the_normative_verdict_table_for_dimension_e_has_all_seven_rows():
    rows = [line for line in CONFORMANCE_DOC.read_text().splitlines()
            if line.startswith("| ") and line.count("|") == 4
            and any(f"`{v}`" in line for v in (PASS, FAIL, SKIP))]
    assert len(rows) == 7, [r[:60] for r in rows]
    verdicts = [next(v for v in (PASS, FAIL, SKIP) if f"`{v}`" in row) for row in rows]
    assert verdicts == [SKIP, SKIP, PASS, PASS, FAIL, FAIL, FAIL]


def test_the_document_forbids_an_aggregate_score_and_the_module_produces_none():
    # Whitespace-normalised: the sentence wraps, and a literal that depends on where a line
    # break falls is a test that fails on a reflow rather than on a change of meaning.
    text = " ".join(CONFORMANCE_DOC.read_text().replace("> ", " ").split())
    assert "There is no aggregate." in text
    assert "single combined compatibility score, grade or percentage" in text
    assert "MUST NOT be displayed, reported, exported or aggregated as `PASS`" in text


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_document_still_says_a_d_assessment_has_no_rules_to_check(profile):
    """The gate for the ruling that makes dimension D `SKIP` in v0.1.0. See the module docstring."""
    text = PROFILE_DOCS[profile].read_text()
    assert NO_RULES_SENTENCE in text, (
        f"{PROFILE_DOCS[profile].relative_to(REPO)} no longer says a D assessment has no rules "
        f"to check, so this profile has normative content and PROFILE_RULES[{profile!r}] owes "
        "it rules — dimension D must stop reporting SKIP with a detail line that has become "
        "false")
    assert PROFILE_RULES[profile] == ()


def test_the_profiles_the_module_knows_are_the_documents_that_exist():
    on_disk = {path.stem for path in (SPEC / "profiles").glob("*.md")}
    assert on_disk == {name.lower() for name in PROFILES}


def test_the_forbidden_claims_the_tool_output_is_swept_for_are_the_documents_own_list():
    """`test_cdm_conformance.py` sweeps the rendered output for these; here is where they live."""
    block = re.search(r"Forbidden claims.*?```text\n(.*?)```", CONVENTIONS_DOC.read_text(), re.S)
    assert block
    forbidden = [line.strip() for line in block.group(1).strip().splitlines() if line.strip()]
    assert forbidden == ["SC-OES Certified", "Official SynapseCommand Partner",
                         "Approved by Decent Cybersecurity", "NATO Certified", "NATO Approved",
                         "NATO Standard"]
    swept = (REPO / "tests" / "test_cdm_conformance.py").read_text()
    for claim in forbidden:
        assert f'"{claim}"' in swept, (
            f"{claim!r} is forbidden by 00-conventions.md and the output sweep in "
            "test_cdm_conformance.py does not look for it")


def test_the_conformance_module_makes_no_forbidden_claim_anywhere_in_its_source():
    """The documents quote the forbidden list in order to forbid it; the tool never uses it."""
    source = (REPO / "packages" / "cdm" / "synapse_cdm" / "conformance.py").read_text()
    for claim in ("SC-OES Certified", "Official SynapseCommand Partner",
                  "Approved by Decent Cybersecurity", "NATO Certified", "NATO Approved",
                  "NATO Standard"):
        assert claim not in source


def test_the_adr_and_the_module_agree_that_require_scopes_the_exit_status():
    text = ADR.read_text()
    assert "one or more **requested** dimensions" in text
    assert "--require A,B,C" in text and "--require A,B,C" in CONFORMANCE_DOC.read_text()


def test_the_console_entry_point_is_declared_for_the_conformance_module():
    pyproject = (REPO / "packages" / "cdm" / "pyproject.toml").read_text()
    assert 'cdm-conformance = "synapse_cdm.conformance:main"' in pyproject
