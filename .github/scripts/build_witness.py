#!/usr/bin/env python3
"""Assemble §53's witness record from what a release ACTUALLY published.

WHY THIS IS A FILE AND NOT A `jq` EXPRESSION IN THE WORKFLOW
------------------------------------------------------------
The same argument `gates/codeql_gate.py`'s header makes: a record assembled by shell in a workflow
is a record nobody can build, inspect or test outside a release, and a release is the worst
possible place to debug one. This runs in the `witness` job, and `tests/test_cdm_witness_builder.py`
runs it over recorded API payloads with no network at all.

WHAT IT READS, AND WHY EACH SOURCE IS THE ONE IT IS
----------------------------------------------------
Every field is a reading of something that did not exist before the upload:

  * **PyPI's JSON API** for the filenames, digests and upload instants. NOT the `SHA256SUMS` the
    build job wrote — that is what the pipeline INTENDED to publish, and a witness assembled from
    intent agrees with itself by construction. `gates/witness_verify.py` then cross-checks the two,
    which is only a check because they come from different places.
  * **the Release API** for the id, url and published instant.
  * **the run's approvals** for WHO released the `pypi` hold, and **the deployment's own status
    history** for WHEN. Under the runner protocol — a private document, summarised in
    `PUBLICATION.md` entry 16 — the approver can be the runner acting on a reviewer's GO, so what
    the approval was taken on is part of the record: the approval `comment` is carried verbatim,
    and `review_file` holds the public reference the comment names, if it names one.

    **2026-09-16: `review_file` carries a public reference or nothing.** Until this date the field
    was filled from a `rounds/reports/<round>.review.md` path in the comment — the reviewer's
    verdict file in the runner's private, untracked round apparatus, which no reader of this
    repository can open, and which `releases/witness/2.1.2.json` still records, as the thing that
    was read. Now the comment is recorded whole under `comment`, `review_file` is the first
    `https://` URL in it or the empty string, and `gates/witness_verify.py` refuses an approval
    that carries neither. A private path is not dressed up as a public one: it stays in the
    comment, where the API put it.

    **2026-09-17: `--review-file URL` carries a reference the maintainer designates, for an
    approval whose comment names nothing.** The `pypi` approval of the v2.2.0 run (35200069387)
    was given with an EMPTY comment, so this script wrote `""` into both fields — which is what
    it must do, and `tests/test_cdm_witness_builder.py` holds it there — and the verifier's rule
    above refused the record the `witness` job built. The record that closes that release
    carries `review_file` by the maintainer's designation in the witness round: the readiness
    report at the release commit, the document the release-readiness protocol says an approval
    is taken on. The flag exists so that designation is a COMMAND — the same builder over the
    same inputs plus one argument — and not an edit to a JSON file after the fact. It is
    accepted only as an `https://` URL; it is applied only to an approval whose comment names
    no URL; and when the comment does name one, the flag must equal it or this script refuses,
    because two references for one approval would be a choice this script may not make. The
    comment stays as the API returned it, empty included, and the record says so. `publish.yml`
    never passes the flag: the pipeline's record is the approval's own words or nothing.

    **2026-09-12 (round PW): the instant comes from the deployment and never from the approval.**
    `actions/runs/<id>/approvals` carries no timestamp at any level — an entry's only keys are
    `comment`, `environments`, `state` and `user`, confirmed against the live endpoint for run
    34687815710 — and the `created_at` on the nested environment object is when the ENVIRONMENT was
    created (2026-08-26) and not when the hold was released (2026-09-12T10:48:52Z). Round PR's
    `witness` job read that absent key, wrote an empty `approved_at`, and `gates/witness_verify.py`
    refused the record, which is the behaviour working: **an instant this script cannot read stays
    the empty string. It is never synthesised, never defaulted, never taken from a clock.** The
    instant it does read is the `queued` status of the deployment of THIS run and THIS environment.

    **2026-09-16: the same rule now holds for `attestation.verified_at`, and it did not.** The
    `attestation` block's instant was written as `args.attestation_verified_at or
    release["published_at"]` — so an `attest` job output that resolved to the empty string was
    silently replaced by the RELEASE's instant, which is a different event, which `publish.yml`'s
    own comment on that job names as the thing §53's "verifiable" exists to rule out, and which
    made `gates/witness_verify.py`'s refusal of an empty `verified_at` unreachable for anything this
    script wrote. The `or` is gone: an empty input stays empty and the verifier refuses the record.
  * **the assets on disk** for the SBOM, evidence and conformance digests, recomputed here rather
    than copied out of `SHA256SUMS` for the same reason as above.
  * **the attestations API's response for the wheel** (`--attestation-bundles`, added 2026-09-16)
    for `attestation.bundle_sha256`: the SHA-256 over the canonical JSON of the one bundle
    `GET /repos/{repo}/attestations/sha256:<wheel digest>` serves — the same definition
    `gates/witness_verify.py` reads it back by. Exactly one bundle is required: none is a build
    nothing attested, and two is a choice this script must not make. Without the flag the field
    is the empty string, which is what every record before this date carries.

DETERMINISM
-----------
`json.dump(..., sort_keys=True, indent=2)` and no clock: every instant written comes from an API
response. Two runs of this script over the same inputs produce the same bytes, which is half of
what §53 means by "deterministic and verifiable"; `gates/witness_verify.py` is the other half.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import urllib.request

PYPI_JSON = "https://pypi.org/pypi/synapse-cdm/{version}/json"

#: The public reference an approval comment may carry — a URL a reader of the record can open.
#: The runner protocol tells the runner to name the reviewer's verdict in the approval comment; a
#: private path named there stays in `comment` and is NOT lifted into `review_file` (module
#: header, 2026-09-16). A comment naming no URL leaves the field empty, and an empty comment
#: leaves both empty, which `gates/witness_verify.py` refuses rather than accepting an approval
#: nobody can trace — unless `--review-file` designates one (module header, 2026-09-17).
_PUBLIC_REFERENCE = re.compile(r"https://[^\s<>()\"']+")


def designated_reference(value: str) -> str:
    """`--review-file`, checked: an `https://` URL or nothing (module header, 2026-09-17).

    The same shape `_PUBLIC_REFERENCE` lifts out of a comment, required of a value a person
    typed: a private path or a bare word here would be the 2.1.2 shape re-entering by the front
    door, and the field's whole meaning since 2026-09-16 is "a reference a reader can open".
    """
    if not value:
        return ""
    if not _PUBLIC_REFERENCE.fullmatch(value):
        raise SystemExit(f"build_witness: --review-file {value!r} is not an https:// URL of the "
                         f"shape a comment's reference is read by; `review_file` carries a public "
                         f"reference or nothing")
    return value


def _names_run(status: dict, run_id: str) -> bool:
    """Does this deployment status belong to the given workflow run?

    It is the only link there is. The deployment object carries no run id (`payload` is `{}` and
    `performed_via_github_app` says only `github-actions`), and the runs API carries no deployment
    once the hold is released — `actions/runs/<id>/pending_deployments` empties on approval. What
    ties the two together is the status's `log_url`/`target_url`, which name
    `.../actions/runs/<run id>/job/<job id>`. Matching on that is how ONE deployment is chosen for
    ONE run; "the most recent deployment of the environment" is not an answer a witness may carry.
    """
    pattern = re.compile(rf"/actions/runs/{re.escape(str(run_id))}(?:[/?#]|$)")
    return any(pattern.search(status.get(key) or "") for key in ("log_url", "target_url"))


def approved_at_from(statuses, environment: str, run_id: str) -> str:
    """The instant the hold was released: the `queued` status of this run's deployment.

    `waiting` is when the hold began, `in_progress` and `success` are the upload. `queued` is the
    transition the approval causes, and for run 34687815710 it reads 2026-09-12T10:48:52Z against a
    `waiting` of 10:28:09Z — the 20 min 43 s the record is supposed to show.

    Nothing matching leaves the field empty, and `gates/witness_verify.py` refuses the record. More
    than one deployment matching is an error rather than a choice: the script cannot know which
    release the approval belongs to, and a record that guessed would be worse than a refused one.
    """
    queued = [status for status in (statuses if isinstance(statuses, list) else [])
              if isinstance(status, dict)
              and status.get("state") == "queued"
              and status.get("environment") == environment
              and _names_run(status, run_id)]
    deployments = sorted({status.get("deployment_url") or "" for status in queued})
    if len(deployments) > 1:
        raise SystemExit(f"build_witness: run {run_id} has a `queued` status on {len(deployments)} "
                         f"deployments of environment {environment!r} ({deployments}); exactly one "
                         f"is required and the most recent is not the answer")
    instants = sorted({status.get("created_at") or "" for status in queued})
    if len(instants) > 1:
        raise SystemExit(f"build_witness: the {environment!r} deployment of run {run_id} has "
                         f"{len(instants)} distinct `queued` instants ({instants}); exactly one is "
                         f"required")
    return instants[0] if instants else ""


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_sha256_from(path: pathlib.Path | None) -> str:
    """`attestation.bundle_sha256` from the attestations API's response for the wheel, or "".

    The digest is over the canonical JSON of `attestations[].bundle` — sorted keys, no whitespace —
    which is the one form two readers of the same payload agree on byte for byte; the raw response
    is not, because `bundle_url` carries a signed, expiring query string. Exactly one bundle:
    zero is a wheel nothing attested, and more than one is a choice (the newest? the first?) that a
    witness may not make on the record's behalf — the same rule `approved_at_from` applies to two
    deployments of one run.
    """
    if path is None:
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    bundles = [entry["bundle"] for entry in (payload.get("attestations") or [])
               if isinstance(entry, dict) and isinstance(entry.get("bundle"), dict)]
    if len(bundles) != 1:
        raise SystemExit(f"build_witness: {path} carries {len(bundles)} attestation bundle(s) for "
                         f"the wheel; exactly one is required, and the most recent is not the "
                         f"answer")
    return hashlib.sha256(
        json.dumps(bundles[0], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def one(directory: pathlib.Path, pattern: str) -> pathlib.Path:
    """Exactly one match, or an error naming what was found.

    A glob that quietly took the first of two would put a digest of the wrong file into a record
    whose whole purpose is that its digests are right.
    """
    found = sorted(directory.glob(pattern))
    if len(found) != 1:
        raise SystemExit(f"build_witness: {directory}/{pattern} matched {len(found)} files "
                         f"({[p.name for p in found]}); exactly one is required")
    return found[0]


def pypi_files(version: str) -> list[dict]:
    url = PYPI_JSON.format(version=version)
    request = urllib.request.Request(url, headers={"User-Agent": "synapse-cdm-witness"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed host
        payload = json.load(response)
    return sorted(
        ({"filename": entry["filename"],
          "sha256": entry["digests"]["sha256"],
          "upload_time": entry["upload_time_iso_8601"]} for entry in payload["urls"]),
        key=lambda entry: entry["filename"])


def approvals_from(payload, statuses, run_id: str, review_file: str = "") -> list[dict]:
    """The `pypi` hold: WHO and WHICH VERDICT from the runs API, WHEN from the deployment.

    An empty list is left empty rather than filled with a placeholder: `witness_verify` refuses a
    record with no approval, and a record that invented one would be worse than a refused release.
    The same holds one field down — an approval whose instant cannot be read keeps an empty
    `approved_at` and is refused with it.

    The environment of the status is matched to the environment of the approval, so a repository
    with two held environments cannot date one hold by the other's release.

    `review_file` is the designated reference (`--review-file`, 2026-09-17), already checked by
    `designated_reference`: it fills the field only where the comment names no URL, and where the
    comment does name one the two must agree or the build stops.
    """
    out = []
    for approval in payload if isinstance(payload, list) else []:
        for environment in approval.get("environments", []):
            comment = approval.get("comment") or ""
            match = _PUBLIC_REFERENCE.search(comment)
            name = environment.get("name", "")
            if match and review_file and review_file != match.group(0):
                raise SystemExit(f"build_witness: the {name!r} approval comment names "
                                 f"{match.group(0)!r} and --review-file names {review_file!r}; "
                                 f"two references for one approval is a choice this script does "
                                 f"not make")
            out.append({
                "environment": name,
                # NOT `approval.get("created_at")` (there is none) and NOT
                # `environment.get("created_at")` (that is when the environment was created).
                "approved_at": approved_at_from(statuses, name, run_id),
                "approver": (approval.get("user") or {}).get("login", ""),
                "comment": comment,
                # The comment's own URL first; the designated one only where the comment has
                # none; the empty string where neither says anything, which the verifier refuses.
                "review_file": match.group(0) if match else review_file,
            })
    return out


def build(args) -> dict:
    assets = args.assets
    release = json.loads(args.release.read_text(encoding="utf-8"))
    statuses = json.loads(args.deployment_statuses.read_text(encoding="utf-8"))
    approvals = approvals_from(json.loads(args.approvals.read_text(encoding="utf-8")),
                               statuses, args.run_id, designated_reference(args.review_file))

    files = pypi_files(args.version)
    evidence = one(assets, f"evidence-{args.version}.tar.gz")
    conformance = one(assets, f"conformance-{args.version}.json")
    spdx = one(assets / "sbom", "synapse_cdm.spdx.json")
    cyclonedx = one(assets / "sbom", "synapse_cdm.cdx.json")

    return {
        "release": args.version,
        "commit": args.commit,
        "tag": args.tag,
        "tag_object": args.tag_object,
        "github_release": {
            "id": release["id"],
            "url": release["html_url"],
            "published_at": release["published_at"],
        },
        "pypi": {"version": args.version, "files": files},
        # The index's digests, restated under the filenames the build job produced. They are the
        # same values by construction HERE, and `witness_verify` compares them because in a
        # release that went wrong they would not be.
        "artifact_sha256": {entry["filename"]: entry["sha256"] for entry in files},
        "sbom_sha256": {"spdx": sha256_of(spdx), "cyclonedx": sha256_of(cyclonedx)},
        "evidence_sha256": sha256_of(evidence),
        "conformance_sha256": sha256_of(conformance),
        "attestation": {
            "bundle_sha256": bundle_sha256_from(args.attestation_bundles),
            "verified": args.attestation_verified,
            # No fallback. An empty instant stays empty and the verifier refuses the record —
            # the module header's dated sentence of 2026-09-16 says why the Release's instant is
            # not a substitute.
            "verified_at": args.attestation_verified_at,
        },
        "released_at": release["published_at"],
        "approvals": approvals,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--tag-object", required=True)
    ap.add_argument("--release", required=True, type=pathlib.Path,
                    help="the Release API payload, as `gh api` wrote it")
    ap.add_argument("--approvals", required=True, type=pathlib.Path,
                    help="the run's `approvals` payload")
    # REQUIRED, not optional, and so is `--run-id`. Optional inputs to a record are how a field
    # goes quietly empty: this one was empty for the whole of v2.1.2 because the key it read did
    # not exist. A release that cannot produce these two files should fail in the witness job.
    ap.add_argument("--deployment-statuses", required=True, type=pathlib.Path,
                    help="every deployment status for this commit, as `gh api` wrote them")
    ap.add_argument("--run-id", required=True,
                    help="GITHUB_RUN_ID — which of those statuses belong to THIS run")
    ap.add_argument("--assets", required=True, type=pathlib.Path,
                    help="the directory holding the SBOMs, the evidence bundle and the sweep")
    ap.add_argument("--attestation-bundles", default=None, type=pathlib.Path,
                    help="the attestations API's response for the wheel's digest, as `gh api` "
                         "wrote it; omitted, `attestation.bundle_sha256` is the empty string")
    # Default FALSE, and the `witness` job passes it because it runs only after `attest`
    # succeeded. A flag defaulting to true could not express an unverified build, and
    # `gates/witness_verify.py` refuses a record whose attestation is not verified — a
    # refusal that never fires is not a check.
    ap.add_argument("--attestation-verified", action="store_true", default=False)
    ap.add_argument("--attestation-verified-at", default="")
    # A witness ROUND's argument and never the workflow's (module header, 2026-09-17): the
    # reference the maintainer designates for an approval whose comment names nothing. An
    # `https://` URL or the build stops; ignored where the comment names the same URL; refused
    # where the comment names a different one.
    ap.add_argument("--review-file", default="",
                    help="a public https:// reference designated by the maintainer for an "
                         "approval whose comment names none; the comment itself is never changed")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    record = build(args)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out} for {record['tag']} "
          f"({len(record['pypi']['files'])} files, {len(record['approvals'])} approval(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
