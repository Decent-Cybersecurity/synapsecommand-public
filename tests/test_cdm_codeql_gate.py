"""`gates/codeql_gate.py`, proved on synthetic SARIF: one blocking, one below, one excepted.

WHY THIS MODULE EXISTS AND WHY THE SARIF IS SYNTHETIC
-----------------------------------------------------
`gates/codeql_gate.py` is the CodeQL gate SOIF Part 1 §44 requires ("high-confidence critical
findings SHALL fail the relevant security gate"), and its whole value is that it BLOCKS. A gate
that has never blocked in a test is a gate whose blocking branch has never run — and this
repository's own record has the shape twice over: `gates/wheel_install.py`'s roster drifted
because nothing read it (`tests/test_cdm_gate_rosters.py`), and `gates/parks_table.py`'s
mutation check exists because a pattern that never matched reported every held document as absent.

The SARIF here is written by hand, in this file, for a reason no live analysis can substitute:
**the repository's real SARIF is expected to be clean.** A test that ran CodeQL and asserted
"0 blocking" would pass identically if the threshold were 900.0, if the rule lookup resolved
nothing, or if `_report` returned 0 unconditionally. The synthetic logs put a CVSS 9.8, a 7.5, a
6.5 and an unclassified result through the same code path and check which of them come out
blocking — which is the assertion that has content.

The three SARIF spellings of a rule reference are all exercised, because CodeQL uses more than
one and the failure mode of missing one is silent: an unresolved rule id classifies as
`unclassified`, which does not block, so a gate that could not read a positional reference would
report a CVSS 9.8 finding as unclassifiable and exit 0.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gates"))

import codeql_gate  # noqa: E402

TODAY = dt.date(2026, 9, 8)

#: One rule per band, plus one with no `security-severity` at all. The property names and value
#: types are CodeQL's own: `security-severity` is a STRING holding a decimal, not a number, which
#: is why the gate parses rather than compares.
RULES = [
    {"id": "py/sql-injection",
     "properties": {"security-severity": "9.8", "precision": "high",
                    "tags": ["security", "external/cwe/cwe-089"]}},
    {"id": "py/weak-sensitive-data-hashing",
     "properties": {"security-severity": "7.5", "precision": "medium", "tags": ["security"]}},
    {"id": "py/clear-text-logging",
     "properties": {"security-severity": "6.5", "precision": "high", "tags": ["security"]}},
    {"id": "py/unused-import",
     "properties": {"problem.severity": "recommendation", "precision": "very-high"}},
]


def sarif(*results: dict) -> dict:
    """A minimal CodeQL-shaped log: the rules in an EXTENSION, which is where CodeQL puts them."""
    return {
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "CodeQL", "rules": []},
                     "extensions": [{"name": "codeql/python-queries", "rules": RULES}]},
            "results": list(results),
        }],
    }


def result(rule_id: str, *, line: int = 7, uri: str = "packages/cdm/synapse_cdm/models.py") -> dict:
    return {"ruleId": rule_id, "message": {"text": f"synthetic finding for {rule_id}"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri},
                                                "region": {"startLine": line}}}]}


def exception_file(directory: pathlib.Path, identifier: str, expiry: str) -> pathlib.Path:
    path = directory / f"{identifier.replace('/', '_')}.json"
    path.write_text(json.dumps({
        "identifier": identifier,
        "affected_package": "synapse-cdm",
        "version_range": "*",
        "risk": "a synthetic finding in a test fixture, exploitable by nobody",
        "reason": "written by tests/test_cdm_codeql_gate.py to prove the excepted branch",
        "owner": "the-test-suite",
        "expiry": expiry,
        "created": "2026-09-08",
        "references": ["https://example.invalid/synthetic"],
    }))
    return path


def classify(log: dict, directory: pathlib.Path, day: dt.date = TODAY) -> dict[str, list[str]]:
    exemptions = codeql_gate.load_exceptions(directory)
    found = codeql_gate.findings(log, exemptions, day)
    out: dict[str, list[str]] = {"blocking": [], "excepted": [], "below": [], "unclassified": []}
    for finding in found:
        if finding.blocking:
            out["blocking"].append(finding.rule)
        elif finding.excepted_by is not None:
            out["excepted"].append(finding.rule)
        else:
            out[finding.band].append(finding.rule)
    return out


# --------------------------------------------------------------------------------------------
# The three cases the round's brief names, in one test each.
# --------------------------------------------------------------------------------------------

def test_a_critical_finding_blocks(tmp_path):
    verdict = classify(sarif(result("py/sql-injection")), tmp_path)
    assert verdict["blocking"] == ["py/sql-injection"], verdict


def test_a_high_finding_blocks_too_which_is_the_ruling_that_amended_the_default(tmp_path):
    """M, 2026-09-07T21:53:40Z, verbatim: a 9.0 threshold "MUST NOT mean that HIGH findings
    between 7.0 and 8.9 are ignored when the security source classifies them as HIGH".

    This is the assertion that would have failed under the brief's own pre-ruled default of
    `security-severity >= 9.0`, so it is the one that records the amendment rather than restating
    it. `precision` here is `medium` deliberately: had precision stayed part of the blocking test,
    a CVSS 7.5 at medium precision would pass and this test says it must not.
    """
    verdict = classify(sarif(result("py/weak-sensitive-data-hashing")), tmp_path)
    assert verdict["blocking"] == ["py/weak-sensitive-data-hashing"], verdict


def test_a_finding_below_the_threshold_is_reported_and_does_not_block(tmp_path):
    verdict = classify(sarif(result("py/clear-text-logging")), tmp_path)
    assert verdict["blocking"] == [], verdict
    assert verdict["below"] == ["py/clear-text-logging"], verdict


def test_a_valid_exception_excepts_and_the_gate_exits_zero(tmp_path):
    exception_file(tmp_path, "py/sql-injection", "2026-12-31")
    verdict = classify(sarif(result("py/sql-injection")), tmp_path)
    assert verdict["blocking"] == [], verdict
    assert verdict["excepted"] == ["py/sql-injection"], verdict


# --------------------------------------------------------------------------------------------
# Expiry, which is the half §45 is actually about.
# --------------------------------------------------------------------------------------------

def test_an_expired_exception_does_not_except(tmp_path):
    """§45: "no permanent undocumented exemptions". An expired file is not an exemption.

    Note what this does NOT do: it does not make the gate refuse. The gate reports the finding as
    blocking and prints the expiry beside it, and the SUITE is what fails on the expired file
    (`tests/test_cdm_security_exceptions.py`). Two independent failures, so neither depends on
    the other having been run.
    """
    exception_file(tmp_path, "py/sql-injection", "2026-09-07")
    verdict = classify(sarif(result("py/sql-injection")), tmp_path)
    assert verdict["blocking"] == ["py/sql-injection"], verdict
    assert verdict["excepted"] == [], verdict


def test_expiry_is_inclusive_of_its_own_day(tmp_path):
    """An `expiry` of the 8th covers the 8th, and the 9th is when it stops.

    Stated as a test because the two sides of this boundary are enforced in two files, and an
    off-by-one between them would make the gate honour an exception the suite has already failed
    on — or the reverse, which is worse: a run in which the gate blocks and the suite is green.
    """
    exception_file(tmp_path, "py/sql-injection", "2026-09-08")
    assert classify(sarif(result("py/sql-injection")), tmp_path,
                    dt.date(2026, 9, 8))["excepted"] == ["py/sql-injection"]
    assert classify(sarif(result("py/sql-injection")), tmp_path,
                    dt.date(2026, 9, 9))["blocking"] == ["py/sql-injection"]


# --------------------------------------------------------------------------------------------
# The parts a hand-written SARIF reader gets wrong.
# --------------------------------------------------------------------------------------------

def test_a_rule_with_no_security_severity_is_unclassified_and_never_silently_dropped(tmp_path):
    """`security-extended` runs quality queries too, and they carry no `security-severity`.

    Blocking on them would red every run and the predictable response is that the gate gets
    deleted, so they do not block — but they are COUNTED and PRINTED, because an unclassifiable
    security result is the hole a green would hide.
    """
    verdict = classify(sarif(result("py/unused-import")), tmp_path)
    assert verdict["unclassified"] == ["py/unused-import"], verdict
    assert verdict["blocking"] == [], verdict


def test_a_positional_rule_reference_resolves(tmp_path):
    """`{"rule": {"index": 0, "toolComponent": {"index": 0}}}` is CodeQL's other spelling.

    A reader that missed it would classify a CVSS 9.8 finding as `unclassified` and exit 0 — a
    gate reporting a hole as a pass. Index 0 of the extension is `py/sql-injection`.
    """
    log = sarif({"rule": {"index": 0, "toolComponent": {"index": 0}},
                 "message": {"text": "positional reference"}})
    verdict = classify(log, tmp_path)
    assert verdict["blocking"] == ["py/sql-injection"], verdict


def test_a_severity_that_is_not_a_number_is_unclassified_rather_than_crashing(tmp_path):
    log = {"version": "2.1.0", "runs": [{
        "tool": {"driver": {"name": "CodeQL",
                            "rules": [{"id": "py/odd", "properties": {"security-severity": "n/a"}}]}},
        "results": [result("py/odd")]}]}
    verdict = classify(log, tmp_path)
    assert verdict["unclassified"] == ["py/odd"], verdict


# --------------------------------------------------------------------------------------------
# Refusals: the gate must not report a green for an analysis that did not happen.
# --------------------------------------------------------------------------------------------

def test_a_missing_sarif_is_a_refusal_and_not_an_empty_result(tmp_path):
    with pytest.raises(codeql_gate.Failed):
        codeql_gate.read_sarif(tmp_path / "nothing.sarif")


def test_a_file_without_runs_is_a_refusal(tmp_path):
    path = tmp_path / "not.sarif"
    path.write_text(json.dumps({"version": "2.1.0"}))
    with pytest.raises(codeql_gate.Failed):
        codeql_gate.read_sarif(path)


def test_a_malformed_exception_is_a_refusal_rather_than_no_exception(tmp_path):
    """Ambiguity is the thing being refused here.

    A file that says `identifier` and nothing else could mean "this rule is excepted" or "this
    file is broken, so nothing is excepted", and both readings are wrong to act on silently. The
    gate refuses; exit status 2 distinguishes it from a finding, which is 1.
    """
    (tmp_path / "broken.json").write_text(json.dumps({"identifier": "py/sql-injection"}))
    with pytest.raises(codeql_gate.Failed):
        codeql_gate.load_exceptions(tmp_path)


def test_the_schema_and_the_readme_are_not_read_as_exceptions():
    """`security/exceptions/` holds `schema.json`, and it is not an exception.

    Taken against the REAL directory, so this is also the assertion that the live directory
    parses at all — the gate refuses on a malformed file there, and this test is where that
    refusal would surface under `pytest` rather than on a CodeQL run.
    """
    live = codeql_gate.load_exceptions()
    assert [e.identifier for e in live if e.identifier == "Security exception"] == []
    assert all(e.path.name != "schema.json" for e in live)


# --------------------------------------------------------------------------------------------
# The pip-audit half: one source, two consumers.
# --------------------------------------------------------------------------------------------

def test_the_pip_audit_flags_are_derived_from_the_directory(tmp_path, monkeypatch, capsys):
    exception_file(tmp_path, "GHSA-aaaa-bbbb-cccc", "2026-12-31")
    exception_file(tmp_path, "PYSEC-2026-9", "2026-09-01")  # expired: must not be ignored
    monkeypatch.setattr(codeql_gate, "EXCEPTIONS", tmp_path)
    assert codeql_gate.emit_pip_audit_ignores(TODAY) == 0
    printed = capsys.readouterr()
    assert printed.out.strip() == "--ignore-vuln GHSA-aaaa-bbbb-cccc"
    assert "PYSEC-2026-9.json expired 2026-09-01" in printed.err


def test_an_empty_directory_derives_an_empty_allowlist(tmp_path, monkeypatch, capsys):
    """The state today, and the reason this is not implemented as "if the file exists".

    `pip-audit --strict $(...)` with an empty expansion is `pip-audit --strict`, which is the
    correct invocation when nothing is excepted. A mechanism that only worked once an exception
    existed would be untested on the day it was first needed.
    """
    monkeypatch.setattr(codeql_gate, "EXCEPTIONS", tmp_path)
    assert codeql_gate.emit_pip_audit_ignores(TODAY) == 0
    assert capsys.readouterr().out.strip() == ""


def test_the_live_directory_derives_the_flags_the_workflow_will_run_with(capsys):
    """Against `security/exceptions/` as it stands, which is the reading the CI step takes."""
    assert codeql_gate.emit_pip_audit_ignores(dt.date.today()) == 0
    assert capsys.readouterr().out.strip() == ""


# --------------------------------------------------------------------------------------------
# Exit statuses, through main(), because that is what a workflow reads.
# --------------------------------------------------------------------------------------------

def test_main_exits_one_on_a_blocking_finding_and_zero_when_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(codeql_gate, "EXCEPTIONS", tmp_path / "none")
    blocking = tmp_path / "blocking.sarif"
    blocking.write_text(json.dumps(sarif(result("py/sql-injection"))))
    clean = tmp_path / "clean.sarif"
    clean.write_text(json.dumps(sarif(result("py/clear-text-logging"))))
    assert codeql_gate.main([str(blocking), "--today", "2026-09-08"]) == 1
    assert codeql_gate.main([str(clean), "--today", "2026-09-08"]) == 0


def test_main_exits_two_on_a_refusal_which_is_neither_a_pass_nor_a_finding(tmp_path):
    assert codeql_gate.main([str(tmp_path / "absent.sarif"), "--today", "2026-09-08"]) == 2
