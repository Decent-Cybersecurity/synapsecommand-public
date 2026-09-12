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
    history** for WHEN. Under `PLAN.md`'s Autonomy section the approver can be the runner acting on
    a reviewer's GO, so the verdict file is part of the record — `witness_verify` requires
    `review_file` and this fills it from the approval comment, which is where the runner is
    instructed to name it.

    **2026-09-12 (round PW): the instant comes from the deployment and never from the approval.**
    `actions/runs/<id>/approvals` carries no timestamp at any level — an entry's only keys are
    `comment`, `environments`, `state` and `user`, confirmed against the live endpoint for run
    34687815710 — and the `created_at` on the nested environment object is when the ENVIRONMENT was
    created (2026-08-26) and not when the hold was released (2026-09-12T10:48:52Z). Round PR's
    `witness` job read that absent key, wrote an empty `approved_at`, and `gates/witness_verify.py`
    refused the record, which is the behaviour working: **an instant this script cannot read stays
    the empty string. It is never synthesised, never defaulted, never taken from a clock.** The
    instant it does read is the `queued` status of the deployment of THIS run and THIS environment.
  * **the assets on disk** for the SBOM, evidence and conformance digests, recomputed here rather
    than copied out of `SHA256SUMS` for the same reason as above.

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

#: The runner is told to name the reviewer's verdict file in the approval comment (RUNNER.md step
#: 7). This is how it comes back out. A comment with no such path leaves the field empty, and
#: `gates/witness_verify.py` refuses the record rather than accepting an approval nobody can trace.
_REVIEW_FILE = re.compile(r"(rounds/reports/[A-Za-z0-9._-]+\.review\.md)")


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


def approvals_from(payload, statuses, run_id: str) -> list[dict]:
    """The `pypi` hold: WHO and WHICH VERDICT from the runs API, WHEN from the deployment.

    An empty list is left empty rather than filled with a placeholder: `witness_verify` refuses a
    record with no approval, and a record that invented one would be worse than a refused release.
    The same holds one field down — an approval whose instant cannot be read keeps an empty
    `approved_at` and is refused with it.

    The environment of the status is matched to the environment of the approval, so a repository
    with two held environments cannot date one hold by the other's release.
    """
    out = []
    for approval in payload if isinstance(payload, list) else []:
        for environment in approval.get("environments", []):
            comment = approval.get("comment") or ""
            match = _REVIEW_FILE.search(comment)
            name = environment.get("name", "")
            out.append({
                "environment": name,
                # NOT `approval.get("created_at")` (there is none) and NOT
                # `environment.get("created_at")` (that is when the environment was created).
                "approved_at": approved_at_from(statuses, name, run_id),
                "approver": (approval.get("user") or {}).get("login", ""),
                "review_file": match.group(1) if match else "",
            })
    return out


def build(args) -> dict:
    assets = args.assets
    release = json.loads(args.release.read_text(encoding="utf-8"))
    statuses = json.loads(args.deployment_statuses.read_text(encoding="utf-8"))
    approvals = approvals_from(json.loads(args.approvals.read_text(encoding="utf-8")),
                               statuses, args.run_id)

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
            "bundle_sha256": args.attestation_sha256 or "",
            "verified": args.attestation_verified,
            "verified_at": args.attestation_verified_at or release["published_at"],
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
    ap.add_argument("--attestation-sha256", default="")
    # Default FALSE, and the `witness` job passes it because it runs only after `attest`
    # succeeded. A flag defaulting to true could not express an unverified build, and
    # `gates/witness_verify.py` refuses a record whose attestation is not verified — a
    # refusal that never fires is not a check.
    ap.add_argument("--attestation-verified", action="store_true", default=False)
    ap.add_argument("--attestation-verified-at", default="")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    record = build(args)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out} for {record['tag']} "
          f"({len(record['pypi']['files'])} files, {len(record['approvals'])} approval(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
