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

import hashlib
import json
import os
import pathlib
import re
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
                   "comment": "2.0.0, approved by the runner after round-reviewer GO",
                   "review_file": ""}],
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
    """Who released it, on what verdict. The runner protocol makes this the record of an act."""
    bad = witness_verify.verify(mutate(approvals=[]), offline=True, download=False, token=None)
    assert any("approvals" in c for c in bad), bad


def test_an_approval_with_neither_a_review_file_nor_a_comment_is_refused():
    """What it was taken on: `review_file` in a record before 2026-09-16, `comment` since.

    Neither is an approval nobody can trace. Either alone is accepted — the 2.1.2 record carries
    only the first, and the builder now writes the second with the first empty unless the comment
    named a URL — so both shapes are asserted here, in both directions.
    """
    bare = {"environment": "pypi", "approved_at": "2026-09-07T11:55:47Z",
            "approver": "decentcybersecurity"}
    bad = witness_verify.verify(mutate(approvals=[dict(bare, review_file="", comment="")]),
                                offline=True, download=False, token=None)
    assert any("`review_file`" in c for c in bad), bad
    for alone in ({"review_file": "a verdict path, the shape the 2.1.2 record carries"},
                  {"comment": "approved on the reviewer's GO"}):
        assert witness_verify.verify(mutate(approvals=[dict(bare, **alone)]), offline=True,
                                     download=False, token=None) == [], alone


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
    """With `download=True` since 2026-09-16: the index's bytes, the Release's assets and its
    SHA256SUMS, the Release's copy of every digested asset re-hashed, and the wheel's attestation
    bundle where the record names one. The 2.1.2 record was read this way on 2026-09-16 and
    VERIFIED; it names no bundle, which the verifier reports and does not refuse."""
    record = json.loads(path.read_text(encoding="utf-8"))
    assert witness_verify.verify(record, offline=False, download=True,
                                 token=os.environ.get("GH_TOKEN")
                                 or os.environ.get("GITHUB_TOKEN")) == []


def test_the_witness_directory_exists_and_says_what_it_is_for():
    """`releases/witness/` is named by §53 (SOIF Part 1) and by the runner protocol's
    authorised-root list, a private document.

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


# --------------------------------- 2026-09-16: the asset digests are RE-DERIVED, offline and online
#
# Until this date the verifier regex-checked `sbom_sha256.*`, `evidence_sha256` and
# `conformance_sha256` for shape and read nothing from the Release's assets, while three documents
# said it "re-derives every digest". Every test below writes the bytes, computes the digest in the
# test, and requires the verifier to agree with a right record and to name the field or the file
# on a wrong one. The network half is exercised with `_get` monkeypatched to a captured shape.

def _assets(tmp_path, record, *, layout="pipeline"):
    """A directory in the pipeline's layout (`sbom/`, no wheel) or a Release download's (flat)."""
    version = record["release"]
    contents = {
        "synapse_cdm.spdx.json": b'{"spdx": true}',
        "synapse_cdm.cdx.json": b'{"cyclonedx": true}',
        f"evidence-{version}.tar.gz": b"an evidence bundle",
        f"conformance-{version}.json": b'{"adapters": {}}',
    }
    directory = tmp_path / "assets"
    (directory / "sbom").mkdir(parents=True)
    for name, body in contents.items():
        where = directory / "sbom" / name if layout == "pipeline" and name.startswith("synapse_cdm.") \
            else directory / name
        where.write_bytes(body)
    digests = {name: hashlib.sha256(body).hexdigest() for name, body in contents.items()}
    return directory, digests


def _agreeing(digests, version="2.0.0"):
    return mutate(**{"sbom_sha256.spdx": digests["synapse_cdm.spdx.json"],
                     "sbom_sha256.cyclonedx": digests["synapse_cdm.cdx.json"],
                     "evidence_sha256": digests[f"evidence-{version}.tar.gz"],
                     "conformance_sha256": digests[f"conformance-{version}.json"]})


def _sums(record, digests) -> str:
    """The build job's table, as `sha256sum "${WHEEL}" "${SDIST}" sbom/*.json …` writes it."""
    lines = [f"{digest}  dist/{name}" for name, digest in record["artifact_sha256"].items()]
    lines += [f"{digests['synapse_cdm.cdx.json']}  sbom/synapse_cdm.cdx.json",
              f"{digests['synapse_cdm.spdx.json']}  sbom/synapse_cdm.spdx.json",
              f"{digests['conformance-2.0.0.json']}  conformance-2.0.0.json",
              f"{digests['evidence-2.0.0.tar.gz']}  evidence-2.0.0.tar.gz"]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("layout", ["pipeline", "release"])
def test_assets_that_hash_to_the_records_digests_agree(tmp_path, layout):
    directory, digests = _assets(tmp_path, GOOD, layout=layout)
    record = _agreeing(digests)
    assert witness_verify.verify(record, offline=True, download=False, token=None,
                                 assets=directory) == []


def test_an_asset_whose_bytes_changed_is_refused_naming_the_field(tmp_path):
    directory, digests = _assets(tmp_path, GOOD)
    record = _agreeing(digests)
    with (directory / "sbom" / "synapse_cdm.spdx.json").open("ab") as handle:
        handle.write(b" ")
    bad = witness_verify.verify(record, offline=True, download=False, token=None,
                                assets=directory)
    assert len(bad) == 1 and "sbom_sha256.spdx" in bad[0], bad


def test_a_missing_asset_is_refused_naming_the_field(tmp_path):
    directory, digests = _assets(tmp_path, GOOD)
    (directory / "conformance-2.0.0.json").unlink()
    bad = witness_verify.verify(_agreeing(digests), offline=True, download=False, token=None,
                                assets=directory)
    assert any("conformance_sha256" in c and "holds no conformance-2.0.0.json" in c for c in bad), bad


def test_the_wheel_is_hashed_when_a_release_download_carries_it_and_not_demanded_otherwise(tmp_path):
    """The pipeline's assets/ has no wheel (it is the `dist` artefact); a Release download does."""
    directory, digests = _assets(tmp_path, GOOD, layout="release")
    record = _agreeing(digests)
    assert witness_verify.verify(record, offline=True, download=False, token=None,
                                 assets=directory) == [], "absent wheel must not be a complaint"
    (directory / "synapse_cdm-2.0.0.tar.gz").write_bytes(b"not the sdist the index served")
    bad = witness_verify.verify(record, offline=True, download=False, token=None,
                                assets=directory)
    assert len(bad) == 1 and "artifact_sha256[synapse_cdm-2.0.0.tar.gz]" in bad[0], bad


def test_a_sha256sums_that_agrees_is_read_by_basename(tmp_path):
    """`dist/…` and `sbom/…` in the table, bare names in the record: compared by basename."""
    directory, digests = _assets(tmp_path, GOOD)
    record = _agreeing(digests)
    (directory / "SHA256SUMS").write_text(_sums(record, digests), encoding="utf-8")
    assert witness_verify.verify(record, offline=True, download=False, token=None,
                                 assets=directory) == []


def test_a_sha256sums_with_one_wrong_line_is_refused_naming_the_file(tmp_path):
    directory, digests = _assets(tmp_path, GOOD)
    record = _agreeing(digests)
    table = _sums(record, digests).replace(digests["synapse_cdm.cdx.json"], "0" * 64)
    (directory / "SHA256SUMS").write_text(table, encoding="utf-8")
    bad = witness_verify.verify(record, offline=True, download=False, token=None,
                                assets=directory)
    assert len(bad) == 1 and bad[0].startswith("synapse_cdm.cdx.json:") and "SHA256SUMS" in bad[0], bad


def test_a_sha256sums_missing_a_line_or_carrying_an_extra_one_is_refused():
    record = _agreeing({"synapse_cdm.spdx.json": "1" * 64, "synapse_cdm.cdx.json": "2" * 64,
                        "evidence-2.0.0.tar.gz": "3" * 64, "conformance-2.0.0.json": "4" * 64})
    complete = witness_verify.check_sums(record, _sums(record, {
        "synapse_cdm.spdx.json": "1" * 64, "synapse_cdm.cdx.json": "2" * 64,
        "evidence-2.0.0.tar.gz": "3" * 64, "conformance-2.0.0.json": "4" * 64}))
    assert complete == []
    short = "\n".join(line for line in _sums(record, {
        "synapse_cdm.spdx.json": "1" * 64, "synapse_cdm.cdx.json": "2" * 64,
        "evidence-2.0.0.tar.gz": "3" * 64, "conformance-2.0.0.json": "4" * 64}).splitlines()
        if "evidence-" not in line)
    bad = witness_verify.check_sums(record, short)
    assert any("no line for evidence-2.0.0.tar.gz" in c and "evidence_sha256" in c for c in bad), bad
    extra = witness_verify.check_sums(record, _sums(record, {
        "synapse_cdm.spdx.json": "1" * 64, "synapse_cdm.cdx.json": "2" * 64,
        "evidence-2.0.0.tar.gz": "3" * 64, "conformance-2.0.0.json": "4" * 64})
        + f"{'5' * 64}  sbom/environment.cdx.json\n")
    assert any("lists environment.cdx.json" in c for c in extra), extra


def test_the_six_digests_the_record_names_are_the_six_the_checks_judge():
    """One enumeration for three checks; a digest left out of it would be a digest nothing reads."""
    named = witness_verify.digests_named(GOOD)
    assert set(named) == {"synapse_cdm-2.0.0-py3-none-any.whl", "synapse_cdm-2.0.0.tar.gz",
                          "synapse_cdm.spdx.json", "synapse_cdm.cdx.json",
                          "evidence-2.0.0.tar.gz", "conformance-2.0.0.json"}
    assert {field for field, _ in named.values()} == {
        "artifact_sha256[synapse_cdm-2.0.0-py3-none-any.whl]",
        "artifact_sha256[synapse_cdm-2.0.0.tar.gz]", "sbom_sha256.spdx", "sbom_sha256.cyclonedx",
        "evidence_sha256", "conformance_sha256"}


# ------------------------------------------------- the Release's assets, over a captured payload

#: The v2.1.2 Release payload's asset list, trimmed to the two keys the verifier reads. Nine
#: assets: the six the record digests, SHA256SUMS, and the two expected extras.
_ASSET_NAMES = ("synapse_cdm-2.0.0-py3-none-any.whl", "synapse_cdm-2.0.0.tar.gz",
                "synapse_cdm.spdx.json", "synapse_cdm.cdx.json", "evidence-2.0.0.tar.gz",
                "conformance-2.0.0.json", "SHA256SUMS", "witness-2.0.0.json",
                "release-notes-2.0.0.md")


def _release_payload(names=_ASSET_NAMES) -> dict:
    return {"id": GOOD["github_release"]["id"], "published_at": GOOD["github_release"]["published_at"],
            "target_commitish": "main",
            "assets": [{"name": name, "browser_download_url": f"https://dl.test/{name}"}
                       for name in names]}


def _fake_get(monkeypatch, payload: dict, bodies: dict[str, bytes]):
    """`_get` answering the Release API with `payload` and each download URL from `bodies`."""
    calls = []

    def get(url, *, token=None):
        calls.append(url)
        if url.startswith("https://api.github.com/repos/"):
            return json.dumps(payload).encode()
        name = url.rsplit("/", 1)[-1]
        if name not in bodies:
            raise witness_verify.urllib.error.HTTPError(url, 404, "no such asset", {}, None)
        return bodies[name]
    monkeypatch.setattr(witness_verify, "_get", get)
    return calls


def test_the_release_must_carry_every_asset_the_record_digests(monkeypatch):
    digests = {"synapse_cdm.spdx.json": "1" * 64, "synapse_cdm.cdx.json": "2" * 64,
               "evidence-2.0.0.tar.gz": "3" * 64, "conformance-2.0.0.json": "4" * 64}
    record = _agreeing(digests)
    _fake_get(monkeypatch, _release_payload(n for n in _ASSET_NAMES if n != "evidence-2.0.0.tar.gz"),
              {"SHA256SUMS": _sums(record, digests).encode()})
    bad = witness_verify.check_release(record)
    assert any("no asset evidence-2.0.0.tar.gz" in c and "evidence_sha256" in c for c in bad), bad


def test_the_releases_sha256sums_is_read_against_the_record(monkeypatch):
    digests = {"synapse_cdm.spdx.json": "1" * 64, "synapse_cdm.cdx.json": "2" * 64,
               "evidence-2.0.0.tar.gz": "3" * 64, "conformance-2.0.0.json": "4" * 64}
    record = _agreeing(digests)
    calls = _fake_get(monkeypatch, _release_payload(), {"SHA256SUMS": _sums(record, digests).encode()})
    assert witness_verify.check_release(record) == []
    assert any(url.endswith("/SHA256SUMS") for url in calls), "SHA256SUMS was never fetched"
    wrong = _sums(record, digests).replace("1" * 64, "f" * 64).encode()
    _fake_get(monkeypatch, _release_payload(), {"SHA256SUMS": wrong})
    bad = witness_verify.check_release(record)
    assert len(bad) == 1 and bad[0].startswith("synapse_cdm.spdx.json:") and "Release's SHA256SUMS" in bad[0], bad


def test_a_release_without_sha256sums_is_refused(monkeypatch):
    record = _agreeing({"synapse_cdm.spdx.json": "1" * 64, "synapse_cdm.cdx.json": "2" * 64,
                        "evidence-2.0.0.tar.gz": "3" * 64, "conformance-2.0.0.json": "4" * 64})
    _fake_get(monkeypatch, _release_payload(n for n in _ASSET_NAMES if n != "SHA256SUMS"), {})
    assert any("carries no SHA256SUMS" in c for c in witness_verify.check_release(record))


def test_download_rehashes_the_releases_copy_of_every_digested_asset(monkeypatch):
    bodies = {"synapse_cdm.spdx.json": b"s", "synapse_cdm.cdx.json": b"c",
              "evidence-2.0.0.tar.gz": b"e", "conformance-2.0.0.json": b"k",
              "synapse_cdm-2.0.0-py3-none-any.whl": b"w", "synapse_cdm-2.0.0.tar.gz": b"t"}
    digests = {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}
    record = _agreeing(digests)
    record["artifact_sha256"] = {n: digests[n] for n in ("synapse_cdm-2.0.0-py3-none-any.whl",
                                                         "synapse_cdm-2.0.0.tar.gz")}
    record["pypi"]["files"] = [{"filename": n, "sha256": d, "upload_time": "x"}
                               for n, d in record["artifact_sha256"].items()]
    sums = _sums(record, digests).encode()
    calls = _fake_get(monkeypatch, _release_payload(), {**bodies, "SHA256SUMS": sums})
    assert witness_verify.check_release(record, download=True) == []
    assert sum(1 for url in calls if not url.endswith("/SHA256SUMS")
               and not url.startswith("https://api.")) == 6, calls
    bodies["synapse_cdm-2.0.0.tar.gz"] = b"a second upload that is not the same bytes"
    _fake_get(monkeypatch, _release_payload(), {**bodies, "SHA256SUMS": sums})
    bad = witness_verify.check_release(record, download=True)
    assert len(bad) == 1 and "Release's copy" in bad[0] and "synapse_cdm-2.0.0.tar.gz" in bad[0], bad


# ------------------------------------------------------------------- the attestation bundle

def _bundle_payload(*bundles: dict) -> dict:
    return {"attestations": [{"bundle": b, "bundle_url": "https://blob.test/x?sig=expiring",
                              "repository_id": 1} for b in bundles]}


def test_an_empty_bundle_digest_is_not_established_and_not_refused(monkeypatch):
    """`releases/witness/2.1.2.json` carries "", and PUBLICATION.md entry 19 records why."""
    monkeypatch.setattr(witness_verify, "_get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("nothing may be fetched for an empty bundle digest")))
    assert witness_verify.check_attestation(mutate(**{"attestation.bundle_sha256": ""})) == []
    assert witness_verify.verify(mutate(**{"attestation.bundle_sha256": ""}), offline=True,
                                 download=False, token=None) == []


def test_a_bundle_digest_the_store_serves_agrees_and_one_it_does_not_is_refused(monkeypatch):
    bundle = {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
              "verificationMaterial": {"tlogEntries": [{"logIndex": "1"}]},
              "dsseEnvelope": {"payload": "e30="}}
    digest = witness_verify.canonical_bundle_sha256(bundle)
    calls = []

    def get(url, *, token=None):
        calls.append(url)
        return json.dumps(_bundle_payload(bundle)).encode()
    monkeypatch.setattr(witness_verify, "_get", get)
    assert witness_verify.check_attestation(mutate(**{"attestation.bundle_sha256": digest})) == []
    assert calls == [witness_verify.ATTESTATIONS_API.format(
        repo=witness_verify.REPO,
        digest=GOOD["artifact_sha256"]["synapse_cdm-2.0.0-py3-none-any.whl"])], calls
    bad = witness_verify.check_attestation(mutate(**{"attestation.bundle_sha256": "e" * 64}))
    assert len(bad) == 1 and "attestation.bundle_sha256" in bad[0] and "1 bundle(s)" in bad[0], bad


def test_the_bundle_digest_is_over_canonical_json_and_not_over_the_response():
    """Key order and whitespace must not change it; the signed, expiring `bundle_url` is outside it."""
    one = {"b": 1, "a": {"y": [1, 2], "x": "z"}}
    other = json.loads('{"a": {"x": "z", "y": [1, 2]},   "b": 1}')
    assert witness_verify.canonical_bundle_sha256(one) == witness_verify.canonical_bundle_sha256(other)
    assert witness_verify.canonical_bundle_sha256(one) != witness_verify.canonical_bundle_sha256(
        {**one, "b": 2})


def test_a_malformed_bundle_digest_is_refused_by_shape():
    bad = witness_verify.verify(mutate(**{"attestation.bundle_sha256": "not-a-digest"}),
                                offline=True, download=False, token=None)
    assert any("attestation.bundle_sha256" in c for c in bad), bad


# ------------------------------------------------------------------------ the token and the CLI

def test_the_cli_reads_the_token_from_the_environment_when_none_is_passed(monkeypatch, tmp_path):
    """`GH_TOKEN`, then `GITHUB_TOKEN`: the witness job sets the first, and until 2026-09-16 the
    CLI ignored both and the pipeline's own verification went out anonymously."""
    seen = {}

    def fake_verify(record, *, offline, download, token, assets=None):
        seen["token"] = token
        return []
    monkeypatch.setattr(witness_verify, "verify", fake_verify)
    path = tmp_path / "w.json"
    path.write_text(json.dumps(GOOD), encoding="utf-8")
    monkeypatch.setenv("GH_TOKEN", "from-gh-token")
    monkeypatch.setenv("GITHUB_TOKEN", "from-github-token")
    assert witness_verify.main([str(path)]) == 0 and seen["token"] == "from-gh-token"
    monkeypatch.delenv("GH_TOKEN")
    assert witness_verify.main([str(path)]) == 0 and seen["token"] == "from-github-token"
    assert witness_verify.main([str(path), "--token", "typed"]) == 0 and seen["token"] == "typed"
    monkeypatch.delenv("GITHUB_TOKEN")
    assert witness_verify.main([str(path)]) == 0 and seen["token"] is None


def test_the_cli_reports_an_unestablished_bundle_and_still_verifies(tmp_path, capsys):
    path = tmp_path / "w.json"
    path.write_text(json.dumps(mutate(**{"attestation.bundle_sha256": ""})), encoding="utf-8")
    assert witness_verify.main([str(path), "--offline"]) == 0
    out = capsys.readouterr().out
    assert "VERIFIED" in out and "not established" in out


def test_the_workflow_hands_the_verifier_the_assets_and_a_token():
    """`--assets assets` and GH_TOKEN on the verify step; `--download` as before."""
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    verify_step = workflow[workflow.index("- name: Verify it"):]
    verify_step = verify_step[:verify_step.index("- name: Attach it")]
    assert 'witness_verify.py "witness-${version}.json" --download --assets assets' in verify_step
    assert "GH_TOKEN: ${{ github.token }}" in verify_step, (
        "the verify step runs with no token; the Release and attestation reads go out anonymously "
        "from a shared runner address, which is the state the pipeline was in until 2026-09-16")


def test_every_witness_path_the_documents_quote_exists():
    """`releases/witness/2.1.0.json` was quoted by two documents and never existed (2.1.0 was
    refused by its gates); every quoted path is now required to be a file."""
    quoted = []
    for path in (WITNESS_DIR / "README.md",
                 REPO / "docs" / "docs" / "security" / "release-pipeline.mdx"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"releases/witness/(\d+\.\d+\.\d+\.json)", text):
            quoted.append((path.relative_to(REPO), match.group(1)))
    assert quoted, "neither document quotes a record path any more; the command has no example"
    missing = [f"{where} quotes releases/witness/{name}" for where, name in quoted
               if not (WITNESS_DIR / name).is_file()]
    assert not missing, missing
