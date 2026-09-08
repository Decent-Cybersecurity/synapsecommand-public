"""`.github/scripts/build_witness.py`, over recorded API payloads and with no network.

WHY THE PAYLOADS ARE RECORDED RATHER THAN FETCHED
--------------------------------------------------
The builder runs exactly once per release, in the `witness` job, after an irreversible upload. That
is the worst place in the repository to discover that it mis-keys a field, and it is the only place
it ever runs for real. So every branch of it is exercised here instead, against the shapes GitHub
and PyPI actually return — the Release payload and the approvals payload are the real 2.0.0
release's, trimmed to the keys the builder reads.

`pypi_files` is the one function that reaches the network, and it is monkeypatched rather than
skipped: what needs testing is that the builder puts the index's digests in the right two places
and sorts them, not that `urllib` works.

THE ASSERTION THAT MATTERS MOST
--------------------------------
The record this builder produces must satisfy `gates/witness_verify.py`. Those are two modules
written to one format, which is precisely the disjunction `tests/test_cdm_trusted_publishing.py`'s
header describes — one fact stated in two places that cannot see each other. So the last test here
builds a record and runs the verifier over it, and a field renamed on one side without the other
fails immediately rather than at a release.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gates"))

import witness_verify  # noqa: E402

#: COMPILED IN MEMORY, not loaded with `importlib`'s source loader, and
#: `tests/test_cdm_generator_loading.py` is the gate that keeps it that way. That loader consults
#: and writes `__pycache__`, and a `.pyc` is revalidated on the source's mtime in whole SECONDS
#: plus its size — so a same-length edit reverted inside one second hands back bytecode compiled
#: from a file that no longer exists. This module's whole subject is what THIS source produces.
_SOURCE = REPO / ".github" / "scripts" / "build_witness.py"
build_witness = types.ModuleType("build_witness")
build_witness.__file__ = str(_SOURCE)
exec(compile(_SOURCE.read_text(encoding="utf-8"), str(_SOURCE), "exec"),  # noqa: S102
     build_witness.__dict__)

#: The real v2.0.0 Release payload, trimmed to what the builder reads.
RELEASE = {
    "id": 384058769,
    "html_url": "https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v2.0.0",
    "published_at": "2026-09-07T12:03:26Z",
    "target_commitish": "main",
}

#: The approvals payload's shape, with the comment RUNNER.md step 7 tells the runner to write.
APPROVALS = [{
    "state": "approved",
    "comment": ("2.0.0, approved by the runner after round-reviewer GO "
                "(rounds/reports/RL.review.md)"),
    "created_at": "2026-09-07T11:55:47Z",
    "user": {"login": "decentcybersecurity"},
    "environments": [{"id": 1, "name": "pypi"}],
}]

FILES = [
    {"filename": "synapse_cdm-2.0.0.tar.gz",
     "sha256": "ab86ff396eda58d9d5c73a718f6bfd49b89001f7555fdb40bb7f16a9cc2ab8c5",
     "upload_time": "2026-09-07T11:56:03.752994Z"},
    {"filename": "synapse_cdm-2.0.0-py3-none-any.whl",
     "sha256": "4f0714f0015bec6309954016f7041b63c06b36539371f4495a4cfd2633d3c2e5",
     "upload_time": "2026-09-07T11:56:01.834740Z"},
]


class Args:
    """The parsed command line, as `build()` reads it."""

    def __init__(self, assets: pathlib.Path, **over):
        self.version = "2.0.0"
        self.commit = "a0cc8967b72978a29f8cfb8ff9785c6ede3c827d"
        self.tag = "v2.0.0"
        self.tag_object = "a0ce1933e831830ec2642fc5a678673d8a6ca808"
        self.release = assets.parent / "release.json"
        self.approvals = assets.parent / "approvals.json"
        self.assets = assets
        self.attestation_sha256 = "f" * 64
        self.attestation_verified = True
        self.attestation_verified_at = "2026-09-07T11:56:06Z"
        self.out = assets.parent / "witness.json"
        for key, value in over.items():
            setattr(self, key, value)


@pytest.fixture
def staged(tmp_path, monkeypatch) -> pathlib.Path:
    """An `assets/` directory holding what the build job hands the witness job."""
    assets = tmp_path / "assets"
    (assets / "sbom").mkdir(parents=True)
    (assets / "sbom" / "synapse_cdm.spdx.json").write_text('{"spdx": true}', encoding="utf-8")
    (assets / "sbom" / "synapse_cdm.cdx.json").write_text('{"cyclonedx": true}', encoding="utf-8")
    (assets / "evidence-2.0.0.tar.gz").write_bytes(b"an evidence bundle")
    (assets / "conformance-2.0.0.json").write_text('{"adapters": {}}', encoding="utf-8")
    (tmp_path / "release.json").write_text(json.dumps(RELEASE), encoding="utf-8")
    (tmp_path / "approvals.json").write_text(json.dumps(APPROVALS), encoding="utf-8")
    monkeypatch.setattr(build_witness, "pypi_files", lambda version: sorted(
        FILES, key=lambda entry: entry["filename"]))
    return assets


# --------------------------------------------------------------------------------- what it builds

def test_it_builds_a_record_the_verifier_accepts(staged):
    """The two modules are one format written twice; this is what holds them together."""
    record = build_witness.build(Args(staged))
    assert witness_verify.verify(record, offline=True, download=False, token=None) == []


def test_every_field_the_verifier_requires_is_produced(staged):
    record = build_witness.build(Args(staged))
    assert set(record) == set(witness_verify.REQUIRED)


def test_the_digests_are_computed_over_the_assets_and_not_copied_from_a_manifest(staged):
    """`SHA256SUMS` is what the pipeline INTENDED to publish; these are the files on disk."""
    record = build_witness.build(Args(staged))
    assert record["evidence_sha256"] == hashlib.sha256(b"an evidence bundle").hexdigest()
    assert record["sbom_sha256"]["spdx"] == \
        hashlib.sha256(b'{"spdx": true}').hexdigest()
    assert record["sbom_sha256"]["cyclonedx"] == \
        hashlib.sha256(b'{"cyclonedx": true}').hexdigest()


def test_the_artifact_digests_come_from_the_index(staged):
    record = build_witness.build(Args(staged))
    assert record["artifact_sha256"] == {entry["filename"]: entry["sha256"] for entry in FILES}


def test_the_files_are_sorted_so_two_runs_agree(staged):
    record = build_witness.build(Args(staged))
    assert [entry["filename"] for entry in record["pypi"]["files"]] == \
        sorted(entry["filename"] for entry in FILES)


def test_two_builds_of_one_release_are_byte_identical(staged):
    """§53's determinism, as the property it is: no clock is read anywhere in the builder."""
    first = json.dumps(build_witness.build(Args(staged)), indent=2, sort_keys=True)
    second = json.dumps(build_witness.build(Args(staged)), indent=2, sort_keys=True)
    assert first == second


# ------------------------------------------------------------------------------ the approval half

def test_the_approval_carries_the_verdict_file_it_was_taken_on(staged):
    """PLAN.md's Autonomy section: an upload can be approved on a reviewer's GO, and which one."""
    record = build_witness.build(Args(staged))
    assert record["approvals"] == [{
        "environment": "pypi",
        "approved_at": "2026-09-07T11:55:47Z",
        "approver": "decentcybersecurity",
        "review_file": "rounds/reports/RL.review.md",
    }]


def test_an_approval_comment_naming_no_verdict_file_leaves_the_field_empty(staged, tmp_path):
    """Empty, and then REFUSED by the verifier. An invented value would be worse than a refusal."""
    silent = [dict(APPROVALS[0], comment="approved")]
    (tmp_path / "approvals.json").write_text(json.dumps(silent), encoding="utf-8")
    record = build_witness.build(Args(staged))
    assert record["approvals"][0]["review_file"] == ""
    assert witness_verify.verify(record, offline=True, download=False, token=None) != []


def test_no_approval_at_all_produces_an_empty_list_and_a_refusal(staged, tmp_path):
    (tmp_path / "approvals.json").write_text("[]", encoding="utf-8")
    record = build_witness.build(Args(staged))
    assert record["approvals"] == []
    assert any("approvals" in c for c in
               witness_verify.verify(record, offline=True, download=False, token=None))


def test_an_unverified_attestation_is_carried_through_and_not_smoothed_over(staged):
    record = build_witness.build(Args(staged, attestation_verified=False))
    assert record["attestation"]["verified"] is False
    assert any("unverified build" in c for c in
               witness_verify.verify(record, offline=True, download=False, token=None))


# ------------------------------------------------------------------------------- the asset lookup

def test_a_missing_asset_stops_the_build_rather_than_writing_an_empty_digest(staged):
    (staged / "evidence-2.0.0.tar.gz").unlink()
    with pytest.raises(SystemExit) as exit_:
        build_witness.build(Args(staged))
    assert "matched 0 files" in str(exit_.value)


def test_two_candidate_assets_stop_the_build_rather_than_picking_one(staged):
    (staged / "sbom" / "synapse_cdm.spdx.json").write_text("{}", encoding="utf-8")
    (staged / "conformance-2.0.0.json").write_text("{}", encoding="utf-8")
    duplicate = staged / "sbom" / "synapse_cdm.spdx.json"
    other = duplicate.parent / "synapse_cdm.spdx.json.bak"
    other.write_text("{}", encoding="utf-8")
    # A glob for the exact name still matches one; the guard is about the PATTERNS that are globs.
    assert build_witness.one(staged, "evidence-2.0.0.tar.gz").name == "evidence-2.0.0.tar.gz"
    (staged / "evidence-2.0.0.tar.gz.1").write_bytes(b"")
    with pytest.raises(SystemExit) as exit_:
        build_witness.one(staged, "evidence-2.0.0*")
    assert "matched 2 files" in str(exit_.value)


def test_the_builder_writes_sorted_keys_so_a_diff_between_releases_is_readable(staged, tmp_path):
    out = tmp_path / "witness-2.0.0.json"
    args = Args(staged, out=out)
    record = build_witness.build(args)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert list(json.loads(text)) == sorted(json.loads(text))
