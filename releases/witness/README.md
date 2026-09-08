# Witness records

One JSON document per milestone release, named `<version>.json`. SOIF Part 1 §53 requires the
record; it fixes one property rather than a schema — the record **MUST be deterministic and
verifiable** — and this directory's whole design follows from taking that literally.

**Deterministic** means the same release produces the same bytes. Nothing in a record is a
measurement of the machine that wrote it: every digest is over an artefact, every instant comes
from an API rather than from a local clock, and the record is written with sorted keys.

**Verifiable** means there is a command that disagrees when the record is wrong:

```bash
python gates/witness_verify.py releases/witness/2.1.0.json            # index + Release
python gates/witness_verify.py releases/witness/2.1.0.json --offline  # no network
python gates/witness_verify.py releases/witness/2.1.0.json --download # also re-hash the bytes
```

A record that asserts its own correctness is not evidence of anything. `PUBLICATION.md` ledger
entry 5 is what that costs once it reaches an index: a step everybody believed had run, discovered
missing afterwards from a 404.

## Who writes one, and who commits it

The release pipeline's `witness` job produces the record **after** the upload, from readings of
PyPI's JSON API and the Release API — the two sources that can only be read once the release
exists. It uploads it as the Release asset `witness-<version>.json`.

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
| `approvals` | `[{environment, approved_at, approver, review_file}]` — the `pypi` hold, and the verdict file that released it |

Four of these are beyond §53's example, and each is here because `PUBLICATION.md` entry 18 had to
state it in prose for want of a field: the tag object, the conformance digest, the attestation
block, and the approval — including `review_file`, because under `PLAN.md`'s Autonomy section an
upload can be approved on a reviewer's verdict, and which verdict is part of what happened.

## What the verifier does not do

It does not re-establish the Sigstore attestation; `gh attestation verify` does that, and it needs
the bundle and a trust root. The record carries `attestation.verified` as a **witnessed** claim in
`PUBLICATION.md`'s sense — the pipeline ran the verification and recorded that it passed — and the
verifier checks the field is present and true rather than pretending to have re-derived it. That
file's "What is gated and what is witnessed" section is the reason the distinction is kept sharp.

`artifact_sha256` against `pypi.files` is the one cross-check that needs no network at all, and it
is the one most worth having: those are the same claim written by two different steps, and a
release where they disagree uploaded bytes nothing gated.
