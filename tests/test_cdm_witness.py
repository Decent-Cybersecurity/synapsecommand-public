"""`gates/witness_verify.py`, proved on synthetic records, and run over every committed one.

WHAT §53 ASKS FOR AND WHAT THIS MODULE HOLDS DOWN
--------------------------------------------------
SOIF Part 1 §53 fixes one property of the witness record rather than a schema: it "MUST be
deterministic and verifiable". A file of digests is deterministic by itself; VERIFIABLE is a claim
about a command existing and disagreeing when the record is wrong. So this module does two
different jobs and they should not be confused with each other:

1. **The verifier's own branches**, on records written here by hand. Every complaint
   `check_shape` can make is provoked by a record built to provoke it. This is where the gate's
   value lives, for the same reason `tests/test_cdm_codeql_gate.py` writes synthetic SARIF: the
   real records are expected to be correct, so a test that only reads real ones passes identically
   if `verify()` returns `[]` unconditionally.

2. **Every record actually committed under `releases/witness/`**, offline, on every suite run. That
   half is empty today — round P7 writes the format and the verifier, and the first record is
   written by the release round's `witness` job and committed by the witness round (PR2). An empty
   parametrization SKIPS, which is the honest report: there is nothing yet to check, and the day
   there is, these tests start checking it with no edit.

THE NETWORK HALF IS OPT-IN
--------------------------
`SC_ONLINE=1` runs the verifier against PyPI and the Release API. It is off by default because a
suite that needs the network is a suite that goes red when a service does, and this repository has
that rule written down in `docs/README.md`'s served-version precedent. Off, the record's internal
agreement is still fully checked — including the one cross-check that catches a real publish
defect without any network at all: `artifact_sha256` against `pypi.files`.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gates"))

import witness_verify  # noqa: E402

WITNESS_DIR = REPO / "releases" / "witness"
COMMITTED = sorted(WITNESS_DIR.glob("*.json"))
ONLINE = os.environ.get("SC_ONLINE") == "1"

#: A record that agrees with itself in every way the offline half can check. Every negative case
#: below is this document with exactly one field changed, so a test that fails names the field.
#: The values are the real 2.0.0 release's, because a synthetic record whose shape drifted from a
#: real one would prove the verifier against a format nothing produces.
GOOD = {
    "release": "2.0.0",
    "commit": "a0cc8967b72978a29f8cfb8ff9785c6ede3c827d",
    "tag": "v2.0.0",
    "tag_object": "a0ce1933e831830ec2642fc5a678673d8a6ca808",
    "github_release": {
        "id": 384058769,
        "url": "https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v2.0.0",
        "published_at": "2026-09-07T12:03:26Z",
    },
    "pypi": {
        "version": "2.0.0",
        "files": [
            {"filename": "synapse_cdm-2.0.0-py3-none-any.whl",
             "sha256": "4f0714f0015bec6309954016f7041b63c06b36539371f4495a4cfd2633d3c2e5",
             "upload_time": "2026-09-07T11:56:01.834740Z"},
            {"filename": "synapse_cdm-2.0.0.tar.gz",
             "sha256": "ab86ff396eda58d9d5c73a718f6bfd49b89001f7555fdb40bb7f16a9cc2ab8c5",
             "upload_time": "2026-09-07T11:56:03.752994Z"},
        ],
    },
    "artifact_sha256": {
        "synapse_cdm-2.0.0-py3-none-any.whl":
            "4f0714f0015bec6309954016f7041b63c06b36539371f4495a4cfd2633d3c2e5",
        "synapse_cdm-2.0.0.tar.gz":
            "ab86ff396eda58d9d5c73a718f6bfd49b89001f7555fdb40bb7f16a9cc2ab8c5",
    },
    "sbom_sha256": {"spdx": "a" * 64, "cyclonedx": "b" * 64},
    "evidence_sha256": "c" * 64,
    "conformance_sha256": "d" * 64,
    "attestation": {"bundle_sha256": "e" * 64, "verified": True,
                    "verified_at": "2026-09-07T11:56:06Z"},
    "released_at": "2026-09-07T12:03:26Z",
    "approvals": [{"environment": "pypi", "approved_at": "2026-09-07T11:55:47Z",
                   "approver": "decentcybersecurity",
                   "review_file": "rounds/reports/RL.review.md"}],
}


def mutate(_at: tuple[str, ...] | None = None, _to=None, **changes) -> dict:
    """`GOOD`, deep-copied, with one field replaced.

    Keys are dotted for the ordinary case, and `_at=(...)` is the escape hatch for the one place a
    dotted key cannot work: `artifact_sha256`'s keys are FILENAMES, and a filename contains dots.
    A splitter that did not notice would silently walk into `synapse_cdm-2`.
    """
    record = json.loads(json.dumps(GOOD))
    if _at is not None:
        target = record
        for part in _at[:-1]:
            target = target[part]
        target[_at[-1]] = _to
    for dotted, value in changes.items():
        parts = dotted.split(".")
        target = record
        for part in parts[:-1]:
            target = target[part]
        if value is _DROP:
            del target[parts[-1]]
        else:
            target[parts[-1]] = value
    return record


_DROP = object()


# --------------------------------------------------------------------- the verifier agrees when it should

def test_a_well_formed_record_raises_no_complaint():
    assert witness_verify.verify(GOOD, offline=True, download=False, token=None) == []


def test_the_required_field_list_is_exactly_what_section_53_and_this_repository_name():
    """The tuple is the contract; this test is what stops it being quietly shortened.

    §53's own example names nine fields. Four more are required here — `tag_object`,
    `conformance_sha256`, `attestation` and `approvals` — and each is a field `PUBLICATION.md`
    entry 18 had to state in prose because no record carried it.
    """
    assert set(witness_verify.REQUIRED) == set(GOOD), (
        "the verifier's REQUIRED tuple and this module's reference record disagree about what a "
        "witness holds; one of them was edited alone")


# --------------------------------------------------------- and disagrees when it should, field by field

@pytest.mark.parametrize("field", witness_verify.REQUIRED)
def test_every_required_field_is_actually_required(field):
    """Drop one field; the verifier must name it. A required list nothing enforces is a comment."""
    bad = witness_verify.verify(mutate(**{field: _DROP}), offline=True, download=False, token=None)
    assert any(f"`{field}`" in complaint for complaint in bad), (
        f"dropping `{field}` produced {bad!r}, which does not name it")


def test_a_tag_that_does_not_name_its_version_is_refused():
    bad = witness_verify.verify(mutate(tag="v1.9.9"), offline=True, download=False, token=None)
    assert any("condition 3" in c for c in bad), bad


def test_a_lightweight_tags_missing_object_is_refused():
    bad = witness_verify.verify(mutate(tag_object="not-an-object"), offline=True, download=False,
                                token=None)
    assert any("40-hex object id" in c for c in bad), bad


def test_the_gates_digest_and_the_indexs_digest_must_agree():
    """The one cross-check that catches a real publish defect with no network at all.

    `artifact_sha256` is what the build job hashed; `pypi.files[].sha256` is what the index says it
    served. They are the same claim written twice by two different steps, and a release where they
    differ uploaded bytes nothing gated.
    """
    corrupted = mutate(_at=("artifact_sha256", "synapse_cdm-2.0.0.tar.gz"), _to="0" * 64)
    bad = witness_verify.verify(corrupted, offline=True, download=False, token=None)
    assert any("The gate hashed one file and the index served another" in c for c in bad), bad


def test_an_unverified_attestation_is_refused():
    bad = witness_verify.verify(mutate(**{"attestation.verified": False}), offline=True,
                                download=False, token=None)
    assert any("unverified build" in c for c in bad), bad


def test_an_attestation_verified_with_no_instant_is_refused():
    bad = witness_verify.verify(mutate(**{"attestation.verified_at": ""}), offline=True,
                                download=False, token=None)
    assert any("no `verified_at`" in c for c in bad), bad


def test_an_empty_approval_list_is_refused():
    """Who released it, on what verdict. PLAN.md's Autonomy section makes this the record of an act."""
    bad = witness_verify.verify(mutate(approvals=[]), offline=True, download=False, token=None)
    assert any("approvals" in c for c in bad), bad


def test_an_approval_missing_its_review_file_is_refused():
    bad = witness_verify.verify(
        mutate(approvals=[{"environment": "pypi", "approved_at": "2026-09-07T11:55:47Z",
                           "approver": "decentcybersecurity", "review_file": ""}]),
        offline=True, download=False, token=None)
    assert any("`review_file`" in c for c in bad), bad


def test_a_digest_that_is_not_a_sha256_is_refused():
    bad = witness_verify.verify(mutate(**{"sbom_sha256.spdx": "deadbeef"}), offline=True,
                                download=False, token=None)
    assert any("sbom_sha256.spdx" in c for c in bad), bad


def test_the_negative_cases_are_not_vacuous():
    """Every mutation above changes something. A `mutate()` that returned `GOOD` would pass them all."""
    assert mutate(tag="v1.9.9") != GOOD
    assert mutate(tag="v1.9.9")["release"] == GOOD["release"], "mutate changed more than one field"


# ------------------------------------------------------------------------- the committed records

@pytest.mark.skipif(not COMMITTED,
                    reason="no witness record is committed yet. Round P7 writes the format and "
                           "the verifier; the first record is produced by the release pipeline's "
                           "`witness` job and committed by the witness round (§53, P7 item 4).")
@pytest.mark.parametrize("path", COMMITTED, ids=[p.name for p in COMMITTED])
def test_every_committed_witness_agrees_with_itself(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    assert witness_verify.verify(record, offline=True, download=False, token=None) == []


@pytest.mark.skipif(not COMMITTED or not ONLINE,
                    reason="SC_ONLINE=1 is what asks for the network half; a suite that needs the "
                           "network goes red when a service does.")
@pytest.mark.parametrize("path", COMMITTED, ids=[p.name for p in COMMITTED])
def test_every_committed_witness_agrees_with_the_index_and_the_release(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    assert witness_verify.verify(record, offline=False, download=False,
                                 token=os.environ.get("GITHUB_TOKEN")) == []


def test_the_witness_directory_exists_and_says_what_it_is_for():
    """`releases/witness/` is named by §53 and by PLAN.md's authorised-root list.

    It is created by this round rather than by the release that first fills it, so that the
    verifier, these tests and the pipeline's `witness` job all name a path that exists.
    """
    assert WITNESS_DIR.is_dir(), f"{WITNESS_DIR} does not exist"
    readme = WITNESS_DIR / "README.md"
    assert readme.is_file(), "the directory carries no README saying what a record in it is"
    text = readme.read_text(encoding="utf-8")
    assert "gates/witness_verify.py" in text, (
        "the README does not name the verifier, so a reader holding a record has no command")
    for field in witness_verify.REQUIRED:
        assert f"`{field}`" in text, f"the README does not document the `{field}` field"
