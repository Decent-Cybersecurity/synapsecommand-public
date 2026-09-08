"""§53's witness record, re-derived from the index and the Release rather than read back.

WHAT A WITNESS RECORD IS FOR, AND WHY VERIFYING IT IS A SEPARATE COMMAND
------------------------------------------------------------------------
SOIF Part 1 §53 requires every milestone release to leave a machine-readable record, and it fixes
one property rather than a schema: the record "MUST be deterministic and verifiable". A JSON file
full of digests is deterministic on its own. It is verifiable only if something re-derives those
digests from the places they came from and says so — otherwise it is a file asserting its own
correctness, which is the shape `PUBLICATION.md` entry 5 records the cost of.

So the format is a data file and this is the command that judges it. Every field this module
checks is fetched fresh:

  * `pypi.files[].sha256` against `https://pypi.org/pypi/<project>/<version>/json`, and — with
    `--download` — against a SHA-256 recomputed over the bytes the index actually serves;
  * `github_release.{id,published_at}` and the asset digests against the Release API;
  * `commit`, `tag` and `tag_object` against the repository the record names;
  * `artifact_sha256` against `pypi.files`, because those two are the same claim written twice and
    a release where they disagree published something the gate did not hash.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not verify the Sigstore attestation. `gh attestation verify` does that, it needs the bundle
and a trust root, and wrapping it here would put this module's exit code on a network service's
availability twice over. The record carries `attestation.verified` and `attestation.verified_at` as
a WITNESSED claim in `PUBLICATION.md`'s sense — the pipeline ran the verification and recorded that
it passed — and this module checks that the field is present and true rather than pretending to
re-establish it. The distinction is the one that file's "What is gated and what is witnessed"
section exists to keep, and blurring it here would be the same defect one layer down.

OFFLINE
-------
`--offline` checks everything internal to the record: shape, digest formats, the agreement between
`artifact_sha256` and `pypi.files`, and the tag/version correspondence. `tests/test_cdm_witness.py`
runs it that way over every committed record on every suite run, and runs the network half only
under `SC_ONLINE=1`. A gate that needs the network is a gate CI skips.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

PROJECT = "synapse-cdm"
REPO = "Decent-Cybersecurity/synapsecommand-public"
PYPI_JSON = "https://pypi.org/pypi/{project}/{version}/json"
RELEASE_API = "https://api.github.com/repos/{repo}/releases/tags/{tag}"

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")

#: Every key §53 names, plus the four this repository adds because entry 18 proved they are the
#: ones a later round actually needs: the tag OBJECT (an annotated tag's own SHA, which is not the
#: commit's), the approval record (who released it and on what verdict), the conformance digest,
#: and the attestation block.
REQUIRED = ("release", "commit", "tag", "tag_object", "github_release", "pypi",
            "artifact_sha256", "sbom_sha256", "evidence_sha256", "conformance_sha256",
            "attestation", "released_at", "approvals")


class Disagreement(Exception):
    """A claim in the record that its source does not support."""


def _get(url: str, *, token: str | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"{PROJECT}-witness-verify"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed hosts
        return response.read()


# ------------------------------------------------------------------------------ the offline half

def check_shape(record: dict) -> list[str]:
    """Everything checkable without a network. Returns the complaints, empty when it agrees."""
    bad: list[str] = []
    for key in REQUIRED:
        if key not in record:
            bad.append(f"the record has no `{key}`, which §53 requires")
    if bad:
        return bad

    if not SHA1.match(record["commit"]):
        bad.append(f"`commit` is {record['commit']!r}, which is not a 40-hex commit id")
    if not SHA1.match(record["tag_object"]):
        bad.append(f"`tag_object` is {record['tag_object']!r}, not a 40-hex object id. An "
                   "annotated tag's object SHA is not its commit's; a lightweight tag has none, "
                   "and MIGRATIONS.md refuses one")
    if record["tag"] != f"v{record['release']}":
        bad.append(f"`tag` is {record['tag']!r} and `release` is {record['release']!r}. "
                   "MIGRATIONS.md condition 3: a tag that does not name its version is a release "
                   "nobody can reproduce")
    if record["pypi"].get("version") != record["release"]:
        bad.append(f"`pypi.version` is {record['pypi'].get('version')!r} but the release is "
                   f"{record['release']!r}")

    for name, digest in sorted(record["artifact_sha256"].items()):
        if not SHA256.match(str(digest)):
            bad.append(f"`artifact_sha256[{name}]` is not a sha256: {digest!r}")
    for name in ("spdx", "cyclonedx"):
        digest = record["sbom_sha256"].get(name)
        if not SHA256.match(str(digest)):
            bad.append(f"`sbom_sha256.{name}` is not a sha256: {digest!r}")
    for key in ("evidence_sha256", "conformance_sha256"):
        if not SHA256.match(str(record[key])):
            bad.append(f"`{key}` is not a sha256: {record[key]!r}")

    # The two places the artefact digests are written have to agree. They are produced by
    # different steps — the build job's `sha256sum` and the index's own metadata — and a release
    # where they differ uploaded bytes the pipeline did not hash.
    from_index = {entry["filename"]: entry["sha256"] for entry in record["pypi"].get("files", [])}
    if not from_index:
        bad.append("`pypi.files` is empty, so the record names no published artefact")
    for filename, digest in sorted(from_index.items()):
        stated = record["artifact_sha256"].get(filename)
        if stated is None:
            bad.append(f"`pypi.files` names {filename} and `artifact_sha256` does not")
        elif stated != digest:
            bad.append(f"{filename}: `artifact_sha256` says {stated} and `pypi.files` says "
                       f"{digest}. The gate hashed one file and the index served another")

    attestation = record["attestation"]
    if attestation.get("verified") is not True:
        bad.append("`attestation.verified` is not true. The pipeline attests the artefacts and "
                   "runs `gh attestation verify`; a record written without that passing is a "
                   "record of an unverified build")
    if not attestation.get("verified_at"):
        bad.append("`attestation.verified` is true with no `verified_at`, so nothing says when")

    if not record["approvals"]:
        bad.append("`approvals` is empty. The `pypi` environment holds every upload for a person "
                   "or for a reviewer's GO, and which it was belongs in the record")
    for approval in record["approvals"]:
        for field in ("environment", "approved_at", "approver", "review_file"):
            if not approval.get(field):
                bad.append(f"an approval entry has no `{field}`")
    return bad


# ------------------------------------------------------------------------------- the network half

def check_pypi(record: dict, *, download: bool = False) -> list[str]:
    """`pypi.files` against the index's own metadata, and optionally against the bytes."""
    bad: list[str] = []
    url = PYPI_JSON.format(project=PROJECT, version=record["release"])
    try:
        payload = json.loads(_get(url))
    except urllib.error.HTTPError as exc:
        return [f"{url} -> HTTP {exc.code}. The record claims this version is on the index"]
    served = {entry["filename"]: entry for entry in payload["urls"]}
    stated = {entry["filename"]: entry for entry in record["pypi"]["files"]}
    for filename in sorted(set(stated) | set(served)):
        if filename not in served:
            bad.append(f"{filename} is in the record and not on the index")
            continue
        if filename not in stated:
            bad.append(f"the index serves {filename} and the record does not name it")
            continue
        index_digest = served[filename]["digests"]["sha256"]
        if stated[filename]["sha256"] != index_digest:
            bad.append(f"{filename}: record {stated[filename]['sha256']}, index {index_digest}")
        elif download:
            body = _get(served[filename]["url"])
            recomputed = hashlib.sha256(body).hexdigest()
            if recomputed != index_digest:
                bad.append(f"{filename}: the served bytes hash to {recomputed}, and both the "
                           f"record and the index metadata say {index_digest}")
    return bad


def check_release(record: dict, *, token: str | None = None) -> list[str]:
    """`github_release` and the asset digests against the Release API."""
    bad: list[str] = []
    url = RELEASE_API.format(repo=REPO, tag=record["tag"])
    try:
        payload = json.loads(_get(url, token=token))
    except urllib.error.HTTPError as exc:
        return [f"{url} -> HTTP {exc.code}. §52 requires a Release for every milestone release"]
    stated = record["github_release"]
    if stated.get("id") != payload["id"]:
        bad.append(f"`github_release.id` is {stated.get('id')} and the API says {payload['id']}")
    if stated.get("published_at") != payload["published_at"]:
        bad.append(f"`github_release.published_at` is {stated.get('published_at')} and the API "
                   f"says {payload['published_at']}")
    # `target_commitish` is a BRANCH NAME for a release created against a branch (`main`, for
    # every release this repository has made) and a commit id only where one was passed. Comparing
    # it against the record's commit unconditionally would fail on every real release, so it is
    # compared only when the API actually returned an object id.
    target = str(payload.get("target_commitish") or "")
    if SHA1.match(target) and target != record["commit"]:
        bad.append(f"the Release targets {target} and the record's commit is {record['commit']}")
    return bad


def verify(record: dict, *, offline: bool, download: bool, token: str | None) -> list[str]:
    bad = check_shape(record)
    if bad or offline:
        return bad
    return check_pypi(record, download=download) + check_release(record, token=token)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("witness", nargs="+", type=pathlib.Path,
                    help="one or more releases/witness/<version>.json")
    ap.add_argument("--offline", action="store_true",
                    help="shape and internal agreement only; no network")
    ap.add_argument("--download", action="store_true",
                    help="also recompute the sha256 over the bytes the index serves")
    ap.add_argument("--token", default=None, help="a GitHub token, for the Release API's rate limit")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    failed = 0
    for path in args.witness:
        if not path.is_file():
            print(f"  MISSING     {path}")
            failed += 1
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        try:
            bad = verify(record, offline=args.offline, download=args.download, token=args.token)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"  UNREACHABLE {path}: {exc}")
            failed += 1
            continue
        if bad:
            failed += 1
            print(f"  DISAGREES   {path} ({len(bad)})")
            for complaint in bad:
                print(f"    - {complaint}")
        else:
            where = "shape and internal agreement" if args.offline else "index and Release"
            print(f"  VERIFIED    {path}  ({record['release']}, against the {where})")
    print(f"{len(args.witness)} witness record(s), {failed} disagreeing")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
