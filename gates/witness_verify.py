"""§53's witness record, re-derived from the index and the Release rather than read back.

WHAT A WITNESS RECORD IS FOR, AND WHY VERIFYING IT IS A SEPARATE COMMAND
------------------------------------------------------------------------
SOIF Part 1 §53 requires every milestone release to leave a machine-readable record, and it fixes
one property rather than a schema: the record "MUST be deterministic and verifiable". A JSON file
full of digests is deterministic on its own. It is verifiable only if something re-derives those
digests from the places they came from and says so — otherwise it is a file asserting its own
correctness, which is the shape `PUBLICATION.md` entry 5 records the cost of.

So the format is a data file and this is the command that judges it. What is re-derived, and from
where — stated per mode, because until 2026-09-16 this paragraph said "the asset digests against
the Release API" and the module compared the Release's id and instant and nothing else:

  * OFFLINE, always: shape, digest formats, the agreement between `artifact_sha256` and
    `pypi.files`, and the tag/version correspondence. With `--assets DIR` — the pipeline's `assets/`
    directory, or a `gh release download` of the Release — the SBOM, evidence and conformance files
    on disk are re-hashed against the record, and a `SHA256SUMS` in it is read line by line against
    every digest the record names.
  * ONLINE, the default: `pypi.files[].sha256` against `https://pypi.org/pypi/<project>/<version>/json`;
    `github_release.{id,published_at}` against the Release API; that the Release CARRIES every file
    the record digests, plus `SHA256SUMS`; and `SHA256SUMS` itself, fetched from the Release and
    read against the record the same way as offline.
  * WITH `--download`: a SHA-256 recomputed over the bytes the index serves for the wheel and the
    sdist; over the Release's own copy of every digested asset, which is a second upload of the same
    bytes and not the same file; and the wheel's Sigstore bundle fetched from the attestations API
    and hashed, against `attestation.bundle_sha256` — see below for what that is and is not.
  * `commit`, `tag` and `tag_object` are checked for shape here and against the repository by
    `tests/test_cdm_witness.py` and the witness round, which have the checkout this module does not.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not verify the Sigstore attestation. `gh attestation verify` does that, it needs the bundle
and a trust root, and wrapping it here would put this module's exit code on a network service's
availability twice over. The record carries `attestation.verified` and `attestation.verified_at` as
a WITNESSED claim in `PUBLICATION.md`'s sense — the pipeline ran the verification and recorded that
it passed — and this module checks that the field is present and true rather than pretending to
re-establish it. The distinction is the one that file's "What is gated and what is witnessed"
section exists to keep, and blurring it here would be the same defect one layer down.

`attestation.bundle_sha256` — defined 2026-09-16 — is the SHA-256 over the canonical JSON
(`json.dumps(bundle, sort_keys=True, separators=(",", ":"))`) of the wheel's Sigstore bundle as
`GET /repos/{repo}/attestations/sha256:<wheel digest>` returns it under `attestations[].bundle`.
With `--download` this module fetches the same endpoint and requires the record's value to be among
the bundles served; that is a check that the record names the bundle the store holds, not a
verification of the bundle. The empty string means the builder was given no bundle — the value in
`releases/witness/2.1.2.json`, written before the pipeline passed one — and is reported as
`not established` rather than refused, because `PUBLICATION.md` entry 19 records the absence as
deliberate.

OFFLINE
-------
`--offline` never touches the network. `tests/test_cdm_witness.py` runs it that way over every
committed record on every suite run, and runs the network half only under `SC_ONLINE=1`. A gate
that needs the network is a gate CI skips.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

PROJECT = "synapse-cdm"
REPO = "Decent-Cybersecurity/synapsecommand-public"
PYPI_JSON = "https://pypi.org/pypi/{project}/{version}/json"
RELEASE_API = "https://api.github.com/repos/{repo}/releases/tags/{tag}"
ATTESTATIONS_API = "https://api.github.com/repos/{repo}/attestations/sha256:{digest}"

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")

#: The two SBOM assets, by the names the build job gives them (`sbom/` in the pipeline's assets
#: directory and in `SHA256SUMS`; flat on the Release).
SPDX_NAME = "synapse_cdm.spdx.json"
CYCLONEDX_NAME = "synapse_cdm.cdx.json"
SUMS_NAME = "SHA256SUMS"

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


def canonical_bundle_sha256(bundle: dict) -> str:
    """The definition of `attestation.bundle_sha256`, shared with `.github/scripts/build_witness.py`."""
    return hashlib.sha256(
        json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def digests_named(record: dict) -> dict[str, tuple[str, str]]:
    """Every digest the record states, keyed by the asset's BASENAME: `{name: (field, digest)}`.

    The wheel and sdist from `artifact_sha256`, the two SBOMs, the evidence bundle and the
    conformance sweep. This is the one place the record's six digests are enumerated, so the
    offline `--assets` read, the `SHA256SUMS` comparison and the Release-asset checks all judge the
    same set and none of them can quietly judge fewer.
    """
    version = record["release"]
    named = {name: (f"artifact_sha256[{name}]", str(digest))
             for name, digest in record["artifact_sha256"].items()}
    named[SPDX_NAME] = ("sbom_sha256.spdx", str(record["sbom_sha256"].get("spdx")))
    named[CYCLONEDX_NAME] = ("sbom_sha256.cyclonedx", str(record["sbom_sha256"].get("cyclonedx")))
    named[f"evidence-{version}.tar.gz"] = ("evidence_sha256", str(record["evidence_sha256"]))
    named[f"conformance-{version}.json"] = ("conformance_sha256", str(record["conformance_sha256"]))
    return named


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
    bundle = attestation.get("bundle_sha256")
    if bundle and not SHA256.match(str(bundle)):
        bad.append(f"`attestation.bundle_sha256` is neither empty nor a sha256: {bundle!r}")

    if not record["approvals"]:
        bad.append("`approvals` is empty. The `pypi` environment holds every upload for a person "
                   "or for a reviewer's GO, and which it was belongs in the record")
    for approval in record["approvals"]:
        for field in ("environment", "approved_at", "approver", "review_file"):
            if not approval.get(field):
                bad.append(f"an approval entry has no `{field}`")
    return bad


def check_sums(record: dict, text: str, *, source: str = SUMS_NAME) -> list[str]:
    """`SHA256SUMS` — the build job's table over the six release files — against the record.

    Every line is `<hex>  <path>`, compared by the path's basename because the table names
    `dist/…` and `sbom/…` where the record and the Release name the bare file. Three things can be
    wrong and each is named: a line whose digest is not the record's, a record digest with no line
    (the table was taken over fewer files than the record claims), and a line the record does not
    digest (the table was taken over more, and the record is silent about a published file).
    """
    bad: list[str] = []
    listed: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not SHA256.match(parts[0]):
            bad.append(f"{source} line {number} is not `<sha256>  <path>`: {line.strip()!r}")
            continue
        listed[pathlib.PurePosixPath(parts[1].strip().lstrip("*")).name] = parts[0]
    named = digests_named(record)
    for name, (field, digest) in sorted(named.items()):
        if name not in listed:
            bad.append(f"{source} has no line for {name}, which the record digests as `{field}`")
        elif listed[name] != digest:
            bad.append(f"{name}: {source} says {listed[name]} and the record's `{field}` says "
                       f"{digest}")
    for name in sorted(set(listed) - set(named)):
        bad.append(f"{source} lists {name}, which the record does not digest")
    return bad


def _find_asset(directory: pathlib.Path, name: str) -> pathlib.Path | None:
    """The pipeline keeps the SBOMs under `sbom/`; a Release download is flat. Either is fine."""
    for candidate in (directory / "sbom" / name, directory / name):
        if candidate.is_file():
            return candidate
    return None


def check_assets(record: dict, directory: pathlib.Path) -> list[str]:
    """The files on disk, re-hashed against the record — the offline half of "asset digests".

    The four non-PyPI assets are REQUIRED to be present: this is the pipeline's `assets/` layout
    and a Release download's, and a directory missing one is not the directory the flag is for.
    The wheel and the sdist are hashed when present and not demanded, because the pipeline's
    `assets/` never holds them (they are the `dist` artefact) while a Release download does. A
    `SHA256SUMS` beside them is read with `check_sums`.
    """
    bad: list[str] = []
    if not directory.is_dir():
        return [f"--assets {directory} is not a directory"]
    for name, (field, digest) in sorted(digests_named(record).items()):
        path = _find_asset(directory, name)
        if path is None:
            if name in record["artifact_sha256"]:
                continue
            bad.append(f"{directory} holds no {name}, which the record digests as `{field}`")
            continue
        recomputed = hashlib.sha256(path.read_bytes()).hexdigest()
        if recomputed != digest:
            bad.append(f"{path.name}: the file on disk hashes to {recomputed} and the record's "
                       f"`{field}` says {digest}")
    sums = directory / SUMS_NAME
    if sums.is_file():
        bad += check_sums(record, sums.read_text(encoding="utf-8"), source=str(sums))
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


def check_release(record: dict, *, token: str | None = None,
                  download: bool = False) -> list[str]:
    """`github_release`, the Release's asset set and its `SHA256SUMS` against the Release API.

    Until 2026-09-16 this compared the id, the instant and the target and read nothing from the
    payload's `assets`, while the module's own header said it checked "the asset digests". It now
    requires every file the record digests to be a Release asset, fetches the Release's own
    `SHA256SUMS` (a few hundred bytes) and reads it against the record, and with `--download`
    fetches every digested asset from the Release and re-hashes it — the Release copy is a second
    upload, so agreement with the index copy is a reading and not a tautology.
    """
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

    assets = {asset["name"]: asset for asset in payload.get("assets") or []}
    named = digests_named(record)
    for name, (field, _digest) in sorted(named.items()):
        if name not in assets:
            bad.append(f"the Release carries no asset {name}, which the record digests as "
                       f"`{field}`")
    if SUMS_NAME not in assets:
        bad.append(f"the Release carries no {SUMS_NAME}; the build job attaches its digest table "
                   "and the record is verified against it")
    else:
        bad += check_sums(record, _get(assets[SUMS_NAME]["browser_download_url"],
                                       token=token).decode("utf-8"),
                          source=f"the Release's {SUMS_NAME}")
    if download:
        for name, (field, digest) in sorted(named.items()):
            if name not in assets:
                continue
            recomputed = hashlib.sha256(
                _get(assets[name]["browser_download_url"], token=token)).hexdigest()
            if recomputed != digest:
                bad.append(f"{name}: the Release's copy hashes to {recomputed} and the record's "
                           f"`{field}` says {digest}")
    return bad


def check_attestation(record: dict, *, token: str | None = None) -> list[str]:
    """`attestation.bundle_sha256` against the bundles the attestations API serves for the wheel.

    Only with `--download` (the caller decides), because it is a further network read; and only a
    check that the record NAMES a bundle the store holds. An empty value is not a complaint — it is
    reported by `main` as `not established` — for the reason the module header gives.
    """
    stated = record["attestation"].get("bundle_sha256") or ""
    if not stated:
        return []
    wheels = [name for name in record["artifact_sha256"] if name.endswith(".whl")]
    if len(wheels) != 1:
        return [f"`artifact_sha256` names {len(wheels)} wheel(s); the bundle is the wheel's and "
                "exactly one is expected"]
    url = ATTESTATIONS_API.format(repo=REPO, digest=record["artifact_sha256"][wheels[0]])
    try:
        payload = json.loads(_get(url, token=token))
    except urllib.error.HTTPError as exc:
        return [f"{url} -> HTTP {exc.code}. The record names a bundle the store does not serve"]
    served = [canonical_bundle_sha256(entry["bundle"]) for entry in payload.get("attestations") or []
              if isinstance(entry.get("bundle"), dict)]
    if stated not in served:
        return [f"`attestation.bundle_sha256` is {stated} and the attestations API serves "
                f"{len(served)} bundle(s) for {wheels[0]}: {served}"]
    return []


def verify(record: dict, *, offline: bool, download: bool, token: str | None,
           assets: pathlib.Path | None = None) -> list[str]:
    bad = check_shape(record)
    if not bad and assets is not None:
        bad += check_assets(record, assets)
    if bad or offline:
        return bad
    bad = check_pypi(record, download=download) + check_release(record, token=token,
                                                                 download=download)
    if download:
        bad += check_attestation(record, token=token)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("witness", nargs="+", type=pathlib.Path,
                    help="one or more releases/witness/<version>.json")
    ap.add_argument("--offline", action="store_true",
                    help="shape and internal agreement only; no network")
    ap.add_argument("--download", action="store_true",
                    help="also recompute the sha256 over the bytes the index and the Release "
                         "serve, and read the wheel's attestation bundle back from the store")
    ap.add_argument("--assets", type=pathlib.Path, default=None,
                    help="a directory holding the SBOMs, the evidence bundle, the conformance "
                         "sweep and optionally SHA256SUMS, the wheel and the sdist — the "
                         "pipeline's assets/ or a `gh release download` — re-hashed offline")
    # The environment is read here rather than in `_get` so that a test can call the check
    # functions with `token=None` and get an anonymous request, whatever the shell holds.
    ap.add_argument("--token", default=None,
                    help="a GitHub token, for the Release API's rate limit; defaults to "
                         "$GH_TOKEN, then $GITHUB_TOKEN")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    token = args.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None

    failed = 0
    for path in args.witness:
        if not path.is_file():
            print(f"  MISSING     {path}")
            failed += 1
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        try:
            bad = verify(record, offline=args.offline, download=args.download, token=token,
                         assets=args.assets)
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
            if args.assets is not None:
                where += f" and the assets under {args.assets}"
            print(f"  VERIFIED    {path}  ({record['release']}, against the {where})")
        if isinstance(record.get("attestation"), dict) and not record["attestation"].get(
                "bundle_sha256"):
            print("              attestation bundle: not established (the record carries no "
                  "`bundle_sha256`; see the module header)")
    print(f"{len(args.witness)} witness record(s), {failed} disagreeing")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
