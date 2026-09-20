"""Audit F04: the semantic-rule corpus, replayed through conformance, and its three registers.

Three lists of rule identifiers must be one set: the table in `docs/cdm-semantic-rules.md`, the corpus
files under `tests/semantic_corpus/`, and the identifiers the package's validators spell at the
head of their messages (plus SEM-001, which `conformance.py` assigns to pydantic's missing-tag
error because no validator of ours raises it). A rule in one register and not the others is a
rule nobody can replay, or a corpus case for a rule nobody documents.

Every corpus case is run through `synapse_cdm.conformance.assess` and the STRUCTURAL and
SEMANTIC verdicts are read separately from dimension A's report — a case may not pass by the
other class failing, and a semantic finding may not be counted as structural or the reverse.
"""
import json
import pathlib
import re

import pytest

from synapse_cdm import conformance
from synapse_cdm.conformance import SEMANTIC, STRUCTURAL

REPO = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = REPO / "packages" / "cdm" / "synapse_cdm"
#: Beside the ADRs and the readiness reports, not in the package: the SC-OES specification the
#: conformance module cites is likewise outside the wheel (`spec/` is excluded package data),
#: and a shipped file the tree does not yet track reds `tests/test_cdm_packaging.py`.
SPEC = REPO / "docs" / "cdm-semantic-rules.md"
CORPUS = REPO / "tests" / "semantic_corpus"

RULE_ID = re.compile(r"\bSEM-\d{3}\b")


def _corpus_files() -> list[pathlib.Path]:
    return sorted(CORPUS.glob("*.json"))


def _cases():
    for path in _corpus_files():
        body = json.loads(path.read_text())
        for case in body["cases"]:
            yield pytest.param(body["rule"], case, id=f"{path.stem}:{case['name']}")


def _spec_rules() -> list[str]:
    """The identifiers the specification's table declares, in table order."""
    rows = [line for line in SPEC.read_text().splitlines() if line.startswith("| SEM-")]
    return [line.split("|")[1].strip() for line in rows]


def _rules_in_source() -> set[str]:
    found: set[str] = set()
    for path in sorted(PACKAGE.glob("*.py")):
        found |= set(RULE_ID.findall(path.read_text()))
    return found


# ------------------------------------------------------------------- the three registers

def test_the_specification_declares_each_rule_once_with_consecutive_identifiers():
    rules = _spec_rules()
    assert rules, "docs/cdm-semantic-rules.md has no `| SEM-` table rows"
    assert rules == [f"SEM-{n:03d}" for n in range(1, len(rules) + 1)], rules


def test_every_specified_rule_has_a_corpus_file_and_every_corpus_file_a_rule():
    spec = set(_spec_rules())
    corpus = {p.stem for p in _corpus_files()} - {"STRUCTURAL"}
    assert corpus == spec, {"spec_only": sorted(spec - corpus), "corpus_only": sorted(corpus - spec)}


def test_every_rule_the_validators_spell_is_specified_and_the_reverse():
    assert _rules_in_source() == set(_spec_rules())


def test_every_rule_has_at_least_one_passing_and_one_failing_case():
    for path in _corpus_files():
        body = json.loads(path.read_text())
        verdicts = {c["expected"]["semantic" if body["rule"] != "STRUCTURAL" else "structural"]
                    for c in body["cases"]}
        assert verdicts == {"PASS", "FAIL"}, (path.name, verdicts)
        for case in body["cases"]:
            assert case["document"].get("object_kind") in conformance.KINDS, (path.name, case["name"])
            assert set(case["expected"]) >= {"structural", "semantic"}, (path.name, case["name"])
            if "FAIL" in case["expected"].values():
                assert case["expected"].get("finding_contains"), (path.name, case["name"])


def test_a_failing_semantic_case_names_its_own_rule():
    for path in _corpus_files():
        body = json.loads(path.read_text())
        for case in body["cases"]:
            if case["expected"]["semantic"] == "FAIL":
                assert case["expected"]["finding_contains"] == body["rule"], (path.name, case["name"])


# ------------------------------------------------------------------- the replay

def _classes(document: dict) -> dict:
    return conformance.assess(document)["dimensions"]["A"]


@pytest.mark.parametrize("rule, case", list(_cases()))
def test_the_corpus_case_gets_the_expected_verdict_in_each_class(rule, case):
    report = _classes(case["document"])
    structural, semantic = report[STRUCTURAL], report[SEMANTIC]
    expected = case["expected"]
    assert ("FAIL" if structural else "PASS") == expected["structural"], structural + semantic
    assert ("FAIL" if semantic else "PASS") == expected["semantic"], structural + semantic
    if "FAIL" in (expected["structural"], expected["semantic"]):
        failing = semantic if expected["semantic"] == "FAIL" else structural
        assert any(expected["finding_contains"] in f for f in failing), failing
        assert report["verdict"] == conformance.FAIL
        assert report["detail"].endswith(f"{len(structural)} structural, {len(semantic)} semantic")
    else:
        assert report["verdict"] == conformance.PASS


def test_the_two_classes_partition_the_findings_and_carry_their_prefix():
    for path in _corpus_files():
        for case in json.loads(path.read_text())["cases"]:
            report = _classes(case["document"])
            assert sorted(report[STRUCTURAL] + report[SEMANTIC]) == sorted(report["findings"])
            assert all(f.startswith(f"{STRUCTURAL}: ") for f in report[STRUCTURAL])
            assert all(f.startswith(f"{SEMANTIC}: ") and RULE_ID.search(f)
                       for f in report[SEMANTIC])
            assert not any(RULE_ID.search(f) for f in report[STRUCTURAL]), report[STRUCTURAL]


def test_the_geometry_tag_rule_is_the_one_assigned_by_conformance_not_raised_by_a_validator():
    """SEM-001 is pydantic's `union_tag_not_found` on a geometry, named by `conformance.py`."""
    assert "SEM-001" not in set(RULE_ID.findall((PACKAGE / "geo.py").read_text()))
    assert "SEM-001" in (PACKAGE / "conformance.py").read_text()
    body = json.loads((CORPUS / "SEM-001.json").read_text())
    failing = [c for c in body["cases"] if c["expected"]["semantic"] == "FAIL"]
    assert failing
    for case in failing:
        report = _classes(case["document"])
        assert report[STRUCTURAL] == [], "the schema accepts a type-less geometry; SEM-001 is why"
        assert any("SEM-001" in f and "geometry" in f for f in report[SEMANTIC])
