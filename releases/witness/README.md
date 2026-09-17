# Witness records

One JSON document per milestone release, named `<version>.json`. SOIF Part 1 §53 requires the
record; it fixes one property rather than a schema — the record **MUST be deterministic and
verifiable** — and this directory's whole design follows from taking that literally.

**Deterministic** means the same release produces the same bytes. Nothing in a record is a
measurement of the machine that wrote it: every digest is over an artefact, every instant comes
from an API rather than from a local clock, and the record is written with sorted keys.

**Verifiable** means there is a command that disagrees when the record is wrong:

```bash
python gates/witness_verify.py releases/witness/2.1.2.json            # index + Release, and its SHA256SUMS
python gates/witness_verify.py releases/witness/2.1.2.json --offline  # no network
python gates/witness_verify.py releases/witness/2.1.2.json --download # also re-hash the bytes, index and Release
python gates/witness_verify.py releases/witness/2.1.2.json --offline --assets <dir>  # re-hash a `gh release download`
```

What each mode re-derives is stated in the verifier's own header, mode by mode, and on the
release-pipeline page. (Until 2026-09-16 the example paths above named `2.1.0.json`, a record
that never existed — `v2.1.0` was refused by its own gates — and the verifier compared no asset
digest at all; `tests/test_cdm_witness.py` now requires every path quoted here to be a file.)

A record that asserts its own correctness is not evidence of anything. `PUBLICATION.md` ledger
entry 5 is what that costs once it reaches an index: a step everybody believed had run, discovered
missing afterwards from a 404.

## Who writes one, and who commits it

The release pipeline's `witness` job produces the record **after** the upload, from readings of
PyPI's JSON API and the Release API — the two sources that can only be read once the release
exists. It uploads it as the Release asset `witness-<version>.json`.

**As of 2026-09-16 that job has never produced a committed record.** It has executed once, on the
`v2.1.2` run, and failed at its own verification step because the builder read an instant off a
key the approvals endpoint does not carry; the repair (round PW) is not an ancestor of the tag.
`2.1.2.json` in this directory was built by hand with the repaired builder over that run's inputs,
under a ruling `PUBLICATION.md` entry 19 records. The next tag push is the first execution of the
repaired job, and the release procedure in `MIGRATIONS.md` now says to confirm it succeeded
before the witness round commits anything. Nor is that job the job `v2.1.2` ran plus one
repair: the read grants (`actions: read`, `deployments: read`), the attestation fetch by the
wheel's digest and the builder's `--attestation-bundles`, and the verifier's
`--download --assets assets` with a token were all added on 2026-09-16, are held to the
workflow text by `tests/test_cdm_witness.py` and `tests/test_cdm_witness_builder.py`, and have
never run on a tag. The same test module holds this paragraph to the directory: a second
record here makes it red until the paragraph says what that run did.

**A workflow does not commit to `main`.** The file lands in this directory in the witness round
that follows the release, by the runner, alongside `PUBLICATION.md`'s human-readable ledger entry.
The two are the same facts for two different readers and neither replaces the other: the ledger
entry is prose a person reads once, and the record is what a machine re-checks forever.

## The fields

`gates/witness_verify.py`'s `REQUIRED` tuple is the contract, and
`tests/test_cdm_witness.py::test_the_required_field_list_is_exactly_what_section_53_and_this_repository_name`
holds this list and that tuple together.

| field | what it is |
| --- | --- |
| `release` | the version, without a leading `v` |
| `commit` | the commit the tag points at, 40 hex |
| `tag` | the annotated tag, `v<release>` |
| `tag_object` | the **tag object's** own SHA, which is not the commit's. A lightweight tag has none, and `MIGRATIONS.md` refuses one |
| `github_release` | `{id, url, published_at}` from the Release API |
| `pypi` | `{version, files: [{filename, sha256, upload_time}]}` from the index's JSON API |
| `artifact_sha256` | what the build job hashed, filename → sha256 |
| `sbom_sha256` | `{spdx, cyclonedx}` |
| `evidence_sha256` | the evidence bundle attached to the Release |
| `conformance_sha256` | the sweep `synapse conformance run --all --format json` produced |
| `attestation` | `{bundle_sha256, verified, verified_at}` — the pipeline's own `gh attestation verify` result |
| `released_at` | when the Release was published |
| `approvals` | `[{environment, approved_at, approver, comment, review_file}]` — the `pypi` hold: who released it, the approval comment verbatim, and the public reference the comment names, or the empty string |

Four of these are beyond §53's example, and each is here because `PUBLICATION.md` entry 18 had to
state it in prose for want of a field: the tag object, the conformance digest, the attestation
block, and the approval — including what it was taken on, because under the runner protocol (a
private document, not in this repository; `PUBLICATION.md` entry 16 summarises it) an upload can
be approved on a reviewer's verdict, and which verdict is part of what happened.

**What `review_file` meant for 2.1.2, and what it means since 2026-09-16.** `2.1.2.json` records
`review_file: rounds/reports/PR.review.md`. That value is a path in the runner's private, untracked
round apparatus — the reviewer's verdict the approval comment named — and it names what was read,
not a file this repository keeps: `rounds/` has no tracked file, and the record is left as written
because its bytes are the Release asset `witness-2.1.2.json` (`PUBLICATION.md` entry 19 records
the digest). A record the builder writes from this date on carries the approval `comment`
verbatim and puts in `review_file` only a reference a reader of this repository can open — the
first `https://` URL the comment names — or the empty string when it names none; a private path
in the comment stays there and is never lifted into `review_file`. The verifier refuses an
approval with neither field filled, which is what keeps both shapes traceable and the 2.1.2
record valid.

## What the verifier does not do

It does not re-establish the Sigstore attestation; `gh attestation verify` does that, and it needs
the bundle and a trust root. The record carries `attestation.verified` as a **witnessed** claim in
`PUBLICATION.md`'s sense — the pipeline ran the verification and recorded that it passed — and the
verifier checks the field is present and true rather than pretending to have re-derived it. That
file's "What is gated and what is witnessed" section is the reason the distinction is kept sharp.

`attestation.bundle_sha256` — defined 2026-09-16 — is the SHA-256 over the canonical JSON of the
wheel's Sigstore bundle as the attestations API serves it (`attestations[].bundle`, sorted keys, no
whitespace). The `witness` job passes the API's answer to the builder; with `--download` the
verifier reads the same endpoint and requires the record's value to be among the bundles served —
a check that the record names the bundle the store holds, not a verification of it. The empty
string means no bundle was handed to the builder: `2.1.2.json` carries it, and the verifier reports
`not established` rather than refusing, because the absence is recorded as deliberate.

`artifact_sha256` against `pypi.files` is the one cross-check that needs no network at all, and it
is the one most worth having: those are the same claim written by two different steps, and a
release where they disagree uploaded bytes nothing gated.
