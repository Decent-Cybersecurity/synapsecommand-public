"""Audit remediation F07 — evidence categories, the snapshot, the exercise report, the gates.

WHAT THE BRIEF FOUND. An adapter's maturity rung was computed from check verdicts, and the
record named a commit with a `-dirty` suffix, but nothing said what KIND of evidence backed a
rung: a golden written by the code under test, a round trip through this package's own
encoder and decoder, and an exchange with somebody else's implementation all read as "the
suite passed". No mechanism existed to record an exchange with an independent implementation,
and a dirty tree was a label rather than a state.

WHAT IS PROVED HERE. The five categories are derived and not typed; every external one reads
ABSENT for every shipped adapter today and says why; a report is what makes one PRESENT, and
`verify` refuses a record whose cited report is missing or changed; a report whose peer is this
package is refused as not independent; a verdict is the two digests' and never typed; the
declared rung is held to the categories it requires, with local completion and outstanding
external validation reported separately; the snapshot names HEAD and a digest that tells two
dirty states apart, and never lists the record itself; and none of it needs a partner, a
credential or the network — the exercise below is a TEST DOUBLE in a temporary directory,
named as one, and nothing under `evidence/` ships.
"""
import json
import pathlib
import subprocess

import pytest

import synapse_cdm
from synapse_cdm import evidence, schemas, version
from synapse_cdm.adapter import roster
from synapse_cdm.manifest import MaturityLevel
from synapse_cdm.manifests import manifest

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PACKAGE.parents[2]

PRESENT, ABSENT, NA = (evidence.CategoryStatus.PRESENT, evidence.CategoryStatus.ABSENT,
                       evidence.CategoryStatus.NOT_APPLICABLE)
EXTERNAL = [c.value for c in evidence.EXTERNAL_CATEGORIES]


def shipped() -> dict:
    return {name: cls for name, cls in roster().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


@pytest.fixture(scope="module")
def ingest_record() -> evidence.EvidenceRecord:
    return evidence.generate("pntmap")


@pytest.fixture(scope="module")
def bidirectional_record() -> evidence.EvidenceRecord:
    return evidence.generate("adsb")


def write_spec(directory: pathlib.Path, *, peer: str = "test-double-decoder",
               category: str = "independent_endpoint", agree: bool = True) -> pathlib.Path:
    """A specification for the runner, over files this test writes. A TEST DOUBLE: the peer
    is named as one, the inputs say the test wrote them, and the limitation says so."""
    (directory / "in.bin").write_bytes(b"\x01\x02\x03")
    (directory / "expected.json").write_text('{"a": 1}\n')
    (directory / "observed.json").write_text('{"a": 1}\n' if agree else '{"a": 2}\n')
    spec = {
        "category": category,
        "peer": {"implementation": peer, "version": "0.0-test-double"},
        "edition": "test edition",
        "profile": None,
        "inputs": [{"path": "in.bin", "provenance": "synthetic bytes written by this test",
                    "authorised_by": "tests/test_cdm_evidence_categories.py"}],
        "directions": ["ingress"],
        "results": [{"direction": "ingress",
                     "command": "test-double-decoder --in in.bin > observed.json",
                     "expected": "expected.json", "observed": "observed.json",
                     "note": "a mechanism test, not a partner exchange"}],
        "limitations": ["a test double in a temporary directory; no partner system exists"],
    }
    path = directory / "spec.json"
    path.write_text(json.dumps(spec, indent=2))
    return path


# ======================================================================== the categories

def test_the_five_categories_are_the_briefs_five_in_its_order_and_every_record_carries_each(
        ingest_record):
    assert [c.value for c in evidence.EvidenceCategory] == [
        "internal_fixture", "self_round_trip", "independent_expected", "normative_schema",
        "independent_endpoint"]
    assert set(ingest_record.evidence_categories) == {c.value for c in evidence.EvidenceCategory}
    assert EXTERNAL == ["independent_expected", "normative_schema", "independent_endpoint"]


def test_internal_fixture_is_present_from_the_suite_and_names_itself_as_the_code_under_tests_own(
        ingest_record):
    reading = ingest_record.evidence_categories["internal_fixture"]
    assert reading.status is PRESENT
    assert reading.sources == []
    assert "code under test" in reading.basis and "synthetic" in reading.basis


def test_self_round_trip_reads_check_e_and_says_it_is_not_independence(
        ingest_record, bidirectional_record):
    ingest = ingest_record.evidence_categories["self_round_trip"]
    assert ingest.status is NA, "pntmap is ingest-only: E is a declared SKIP"
    assert "declared inapplicable" in ingest.basis
    both = bidirectional_record.evidence_categories["self_round_trip"]
    assert both.status is PRESENT
    assert "not independence" in both.basis


def test_a_failed_internal_check_reads_absent_and_not_present():
    provenance = evidence.ProvenanceSummary(directories=["x"], fixtures=3, synthetic=3,
                                            classifications=["PUBLIC"])
    checks = {"A": {"verdict": "PASS"}, "B": {"verdict": "FAIL"}, "C": {"verdict": "PASS"},
              "E": {"verdict": "FAIL"}}
    out = evidence.categories({"checks": checks}, provenance, [])
    assert out["internal_fixture"].status is ABSENT and "B" in out["internal_fixture"].basis
    assert out["self_round_trip"].status is ABSENT
    not_synthetic = evidence.ProvenanceSummary(directories=["x"], fixtures=3, synthetic=2,
                                               classifications=["PUBLIC"])
    checks["B"] = {"verdict": "PASS"}
    assert evidence.categories({"checks": checks}, not_synthetic, [])["internal_fixture"].status \
        is ABSENT


def test_every_external_category_is_absent_for_every_shipped_adapter_and_external_exercise_is_null():
    """The evidence state is OPEN, not invented: no report ships, no partner is named, no
    exercise date exists, and the manifest's `external_exercise` is null on every adapter."""
    for name, cls in sorted(shipped().items()):
        record = evidence.generate(name)
        for category in EXTERNAL:
            reading = record.evidence_categories[category]
            assert reading.status is ABSENT, (name, category, reading)
            assert reading.sources == [], (name, category)
            assert reading.basis, (name, category)
        assert manifest(cls).adapter.maturity.external_exercise is None, name
        assert record.maturity_support.external_outstanding == EXTERNAL, name
        assert record.maturity_support.local_complete is True, name
        assert record.maturity_support.satisfied is True, (name, record.maturity_support)


def test_normative_schema_says_check_b_is_the_cdms_own_schema(ingest_record):
    reading = ingest_record.evidence_categories["normative_schema"]
    assert reading.status is ABSENT
    assert "own published schema" in reading.basis


# ================================================================= the exercise report

def test_the_runner_derives_every_digest_and_verdict_and_generate_reads_the_report(tmp_path):
    spec = write_spec(tmp_path)
    report = evidence.exercise("pntmap", json.loads(spec.read_text()), base=tmp_path)
    assert report.category is evidence.EvidenceCategory.INDEPENDENT_ENDPOINT
    assert report.this_side.implementation == "synapse-cdm"
    assert report.this_side.version == version.PACKAGE_VERSION
    assert report.peer.implementation == "test-double-decoder"
    assert report.inputs[0].sha256 == evidence.digest(tmp_path / "in.bin")[0]
    assert report.inputs[0].bytes == 3
    assert report.results[0].verdict == evidence.AGREE
    assert report.results[0].expected_sha256 == report.results[0].observed_sha256
    assert report.snapshot.commit == evidence.snapshot().commit
    assert set(report.environment) >= {"python", "platform"}
    assert report.adapter_id == "pntmap"

    out = tmp_path / "out"
    written = evidence.write_exercise(report, out, "double-1")
    assert written == out / "pntmap" / "1.0.0" / "exercises" / "double-1.json"
    record = evidence.generate("pntmap", exercises=written.parent)
    reading = record.evidence_categories["independent_endpoint"]
    assert reading.status is PRESENT
    assert [s.path for s in reading.sources] == ["exercises/double-1.json"]
    assert reading.sources[0].sha256 == evidence.digest(written)[0]
    assert "test-double-decoder 0.0-test-double" in reading.basis
    assert "1 of 1 exercised direction(s) AGREE" in reading.basis
    assert record.maturity_support.external_outstanding == ["independent_expected",
                                                            "normative_schema"]
    # A report of a FAILED exchange is a valid report and reads PRESENT with its own count.
    (tmp_path / "f").mkdir()
    failed = write_spec(tmp_path / "f", agree=False)
    report2 = evidence.exercise("pntmap", json.loads(failed.read_text()), base=tmp_path / "f")
    assert report2.results[0].verdict == evidence.DIFFER


def test_verify_refuses_a_record_whose_cited_report_is_missing_or_changed(tmp_path):
    """THE GATE: a category PRESENT without its report is a claim, and `verify` says so."""
    spec = write_spec(tmp_path)
    out = tmp_path / "out"
    report = evidence.exercise("pntmap", json.loads(spec.read_text()), base=tmp_path)
    written = evidence.write_exercise(report, out, "double-1")
    record_path = evidence.write(evidence.generate("pntmap", exercises=written.parent), out)
    assert record_path.parent == written.parent.parent
    problems, _ = evidence.verify(record_path)
    assert problems == [], problems

    original = written.read_bytes()
    written.write_bytes(original.replace(b"test edition", b"another edition"))
    problems, _ = evidence.verify(record_path)
    assert any("does not hash to what the record cites" in p for p in problems), problems
    assert any(p.startswith("evidence_categories.independent_endpoint.sources") for p in problems)

    written.unlink()
    problems, _ = evidence.verify(record_path)
    assert any("cited and not beside the record" in p for p in problems), problems
    assert any("evidence_categories.independent_endpoint.status" in p and "ABSENT" in p
               for p in problems), problems
    assert evidence.main(["verify", str(record_path)]) == evidence.EXIT_FAILED


def test_a_peer_that_is_this_package_is_refused_as_not_independent(tmp_path):
    for name in ("synapse-cdm", "synapse_cdm", "SynapseCommand", "Synapse CDM"):
        spec = write_spec(tmp_path, peer=name)
        with pytest.raises(ValueError, match="not independence"):
            evidence.exercise("pntmap", json.loads(spec.read_text()), base=tmp_path)
    spec = write_spec(tmp_path, peer="   ")
    with pytest.raises(ValueError, match="unnamed implementation"):
        evidence.exercise("pntmap", json.loads(spec.read_text()), base=tmp_path)


def test_a_report_may_not_claim_an_internal_category(tmp_path):
    for category in ("internal_fixture", "self_round_trip"):
        spec = write_spec(tmp_path, category=category)
        with pytest.raises(ValueError, match="produced by the suite itself"):
            evidence.exercise("pntmap", json.loads(spec.read_text()), base=tmp_path)


def test_a_verdict_is_the_digests_and_a_typed_one_is_refused():
    with pytest.raises(ValueError, match="never typed"):
        evidence.ExerciseResult(direction="ingress", command="x", expected_sha256="a" * 64,
                                observed_sha256="b" * 64, verdict=evidence.AGREE, note="")
    with pytest.raises(ValueError, match="direction"):
        evidence.ExerciseResult(direction="sideways", command="x", expected_sha256="a" * 64,
                                observed_sha256="a" * 64, verdict=evidence.AGREE, note="")


def test_a_report_with_no_inputs_or_no_results_or_disagreeing_directions_is_refused(tmp_path):
    spec = write_spec(tmp_path)
    payload = json.loads(spec.read_text())
    for field, message in (("inputs", "inputs is empty"), ("results", "results is empty")):
        broken = dict(payload, **{field: []})
        with pytest.raises(ValueError, match=message):
            evidence.exercise("pntmap", broken, base=tmp_path)
    broken = dict(payload, directions=["ingress", "egress"])
    with pytest.raises(ValueError, match="do not agree with the results"):
        evidence.exercise("pntmap", broken, base=tmp_path)


def test_a_report_for_another_adapter_or_a_malformed_one_refuses_the_directory_whole(tmp_path):
    spec = write_spec(tmp_path)
    out = tmp_path / "out"
    report = evidence.exercise("pntmap", json.loads(spec.read_text()), base=tmp_path)
    written = evidence.write_exercise(report, out, "double-1")
    with pytest.raises(ValueError, match="reports pntmap 1.0.0, and this record is adsb"):
        evidence.generate("adsb", exercises=written.parent)
    (written.parent / "junk.json").write_text("{}")
    with pytest.raises(ValueError, match="junk.json: not a valid exercise report"):
        evidence.generate("pntmap", exercises=written.parent)


def test_the_cli_writes_a_report_generate_reads_it_by_default_and_the_badge_turns_green(
        tmp_path, capsys):
    spec = write_spec(tmp_path)
    out = tmp_path / "out"
    assert evidence.main(["exercise", "--adapter", "pntmap", "--spec", str(spec),
                          "--slug", "double-1", "--out", str(out)]) == evidence.EXIT_OK
    assert "independent_endpoint; 1 of 1 direction(s) AGREE" in capsys.readouterr().out
    assert evidence.main(["generate", "--adapter", "pntmap", "--out", str(out)]) == 0
    record = json.loads((out / "pntmap" / "1.0.0" / "evidence.json").read_text())
    assert record["evidence_categories"]["independent_endpoint"]["status"] == "PRESENT"
    badge = evidence.badges(record)["independent-evidence"]
    assert badge == {"schemaVersion": 1, "label": "Independent Evidence",
                     "message": "independent_endpoint", "color": "brightgreen"}
    # The refusals reach the CLI as usage errors, not tracebacks.
    (tmp_path / "bad").mkdir()
    bad = write_spec(tmp_path / "bad", peer="synapse-cdm")
    assert evidence.main(["exercise", "--adapter", "pntmap", "--spec", str(bad),
                          "--slug", "x", "--out", str(out)]) == evidence.EXIT_USAGE
    assert "not independence" in capsys.readouterr().err
    assert evidence.main(["exercise", "--adapter", "pntmap", "--spec", str(spec),
                          "--slug", "no/slashes", "--out", str(out)]) == evidence.EXIT_USAGE


def test_the_badge_is_amber_none_today_and_absent_without_its_field(ingest_record):
    payload = ingest_record.model_dump(mode="json")
    assert evidence.badges(payload)["independent-evidence"] == {
        "schemaVersion": 1, "label": "Independent Evidence", "message": "none",
        "color": "orange"}
    del payload["evidence_categories"]
    assert "independent-evidence" not in evidence.badges(payload)


# ================================================================== maturity support

def test_the_declared_rung_is_held_to_the_categories_it_requires(ingest_record,
                                                                bidirectional_record):
    ingest = ingest_record.maturity_support
    assert (ingest.declared, ingest.required) == ("L3", ["internal_fixture"])
    assert ingest.satisfied and ingest.local_complete
    assert ingest.eligible == ingest_record.conformance["maturity_eligible"]
    both = bidirectional_record.maturity_support
    assert (both.declared, both.required) == ("L4", ["internal_fixture", "self_round_trip"])
    assert both.satisfied and both.local_complete
    assert both.external_outstanding == EXTERNAL


def test_not_applicable_does_not_satisfy_a_requirement_and_l6_needs_the_endpoint(ingest_record):
    """A rung passed vacuously is not a rung declared (§3.6 rule 4, as the manifests gate
    reads it); and L6 is the one rung an outside party has to supply."""
    readings = ingest_record.evidence_categories
    assert readings["self_round_trip"].status is NA
    vacuous = evidence.maturity_support("L4", "L5", readings, conformant=True)
    assert vacuous.satisfied is False
    assert evidence.RUNG_CATEGORIES["L6"][-1] is evidence.EvidenceCategory.INDEPENDENT_ENDPOINT
    top = evidence.maturity_support("L6", "L5", readings, conformant=True)
    assert top.satisfied is False and "independent_endpoint" in top.external_outstanding
    assert [MaturityLevel(level) for level in evidence.RUNG_CATEGORIES] == list(MaturityLevel)


def test_local_completion_is_reported_apart_from_external_validation(ingest_record):
    readings = ingest_record.evidence_categories
    support = evidence.maturity_support("L3", "L5", readings, conformant=False)
    assert support.local_complete is False, "a non-conformant run is not locally complete"
    assert support.external_outstanding == EXTERNAL, "and that says nothing about the outside"


# ====================================================================== the snapshot

def test_the_snapshot_names_head_and_source_commit_is_read_off_it(ingest_record):
    snap = ingest_record.snapshot
    assert ingest_record.source_commit == snap.commit + ("-dirty" if snap.dirty else "")
    assert len(snap.commit) == 40 or snap.commit == "unknown"
    if snap.dirty:
        assert snap.digest and len(snap.digest) == 64
        assert snap.tracked_diff_sha256 or snap.untracked
    else:
        assert snap.digest is None and snap.tracked_diff_sha256 is None
        assert snap.untracked == []
    for entry in snap.untracked:
        assert not entry.path.startswith("/") and entry.path.split("/")[-1] != "evidence.json"
        assert len(entry.sha256) == 64


def _git(where: pathlib.Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          check=True, env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                                           "HOME": str(where), "PATH": "/usr/bin:/bin:/usr/local/bin"})
    return done.stdout


def test_two_dirty_states_are_told_apart_and_the_record_itself_is_never_listed(tmp_path):
    """The `-dirty` suffix could only say the tree was dirty; the digest says WHICH dirty.

    A throwaway repository, so the reading does not depend on this checkout's state: clean →
    no digest; a tracked edit → a digest; a different edit → a different digest; an untracked
    file → listed with its hash; an untracked `evidence.json` → not listed, because it is the
    output and a snapshot that hashed the record it lives in would be the circle F07 forbids.
    """
    repo = tmp_path / "r"
    (repo / "pkg").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "first")
    head = _git(repo, "rev-parse", "HEAD").strip()

    clean = evidence.snapshot(repo / "pkg")
    assert (clean.commit, clean.dirty, clean.digest, clean.untracked) == (head, False, None, [])
    assert evidence.source_commit(repo / "pkg") == head

    (repo / "a.txt").write_text("two\n")
    first = evidence.snapshot(repo / "pkg")
    assert first.dirty and first.tracked_diff_sha256 and first.digest
    assert evidence.source_commit(repo / "pkg") == head + "-dirty"
    (repo / "a.txt").write_text("three\n")
    second = evidence.snapshot(repo / "pkg")
    assert second.digest != first.digest and second.tracked_diff_sha256 != first.tracked_diff_sha256

    (repo / "new.bin").write_bytes(b"\x00")
    (repo / "evidence.json").write_text("{}")
    third = evidence.snapshot(repo / "pkg")
    assert [e.path for e in third.untracked] == ["new.bin"], "listed from the top, not from pkg/"
    assert third.untracked[0].sha256 == evidence.digest(repo / "new.bin")[0]
    assert third.digest not in (first.digest, second.digest)
    assert evidence.snapshot(repo / "pkg") == third, "the snapshot is a function of the state"


def test_outside_a_checkout_the_snapshot_is_unknown_and_clean(tmp_path):
    snap = evidence.snapshot(tmp_path)
    assert snap == evidence.Snapshot(commit="unknown", dirty=False, tracked_diff_sha256=None,
                                     untracked=[], digest=None)
    assert evidence.source_commit(tmp_path) == "unknown"


def test_a_change_of_snapshot_is_a_difference_verify_reports(ingest_record):
    recorded = ingest_record.model_dump(mode="json")
    other = json.loads(json.dumps(recorded))
    other["snapshot"]["digest"] = "0" * 64
    other["snapshot"]["dirty"] = True
    problems = evidence.compare(recorded, other)
    assert any(p.startswith("snapshot.digest") for p in problems), problems
    assert not any(p.startswith("source_commit") for p in problems) or not recorded[
        "source_commit"].endswith("-dirty"), "a dirty source_commit stays masked; the snapshot is not"


# ================================================================ the published shapes

def test_both_evidence_schemas_are_published_current_and_on_the_evidence_axis():
    assert schemas.check(REPO / "schemas") == []
    assert schemas.EXERCISE_STEM == "evidence/exercise"
    published = json.loads((REPO / "schemas" / "evidence" / "exercise.schema.json").read_text())
    assert published["x-evidence-schema-version"] == version.EVIDENCE_SCHEMA_VERSION
    assert published["$id"].endswith(":exercise")
    assert set(published["required"]) >= {"this_side", "peer", "edition", "inputs", "directions",
                                          "results", "limitations", "environment", "snapshot",
                                          "category"}
    record_schema = json.loads(
        (REPO / "schemas" / "evidence" / "evidence.schema.json").read_text())
    assert {"snapshot", "evidence_categories", "maturity_support"} <= set(record_schema["required"])
    assert record_schema["$defs"]["CategoryStatus"]["enum"] == ["PRESENT", "ABSENT",
                                                                "NOT_APPLICABLE"]
    assert published["$defs"]["EvidenceCategory"]["enum"] == [
        c.value for c in evidence.EvidenceCategory]


def test_a_written_report_validates_against_its_published_schema(tmp_path):
    import jsonschema
    spec = write_spec(tmp_path)
    report = evidence.exercise("pntmap", json.loads(spec.read_text()), base=tmp_path)
    published = json.loads((REPO / "schemas" / "evidence" / "exercise.schema.json").read_text())
    jsonschema.validate(report.model_dump(mode="json"), published)


# ======================================================================= the documents

def test_interoperability_md_states_the_categories_and_the_acceptance_procedure():
    text = (REPO / "INTEROPERABILITY.md").read_text()
    for category in evidence.EvidenceCategory:
        assert f"`{category.value}`" in text, category.value
    assert "python -m synapse_cdm.evidence exercise" in text
    assert "external_exercise" in text and "null" in text
    assert "not independence" in text
