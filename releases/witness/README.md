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
python gates/witness_verify.py releases/witness/2.1.2.json releases/witness/2.2.0.json releases/witness/3.0.1.json --offline  # every record here
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

**As of 2026-09-17 that job had never produced a committed record, and it had executed twice; on
2026-09-20 its third execution produced this directory's first pipeline-built record, `3.0.1.json`,
and the paragraph after this history says how.**
On the `v2.1.2` run it failed at its own verification step because the builder read an instant
off a key the approvals endpoint does not carry; the repair (round PW) was not an ancestor of
that tag, and `2.1.2.json` in this directory was built by hand with the repaired builder over
that run's inputs, under a ruling `PUBLICATION.md` entry 19 records. On the `v2.2.0` run
([35200069387](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/35200069387),
2026-09-17) the repaired job ran for the first time, and its build step succeeded: the read
grants (`actions: read`, `deployments: read`), the attestation fetch by the wheel's digest and
the builder's `--attestation-bundles` — all added on 2026-09-16 and, until that run, never
executed on a tag — read the approvals, the deployment's status history and the attestation
store and wrote `witness-2.2.0.json for v2.2.0 (2 files, 1 approval(s))`. Its verify step,
`--download --assets assets` with a token, then refused that record with *an approval entry has
neither a `review_file` nor a `comment`, so nothing says what it was taken on*, because the
`pypi` approval was given with an empty comment; the attach step was skipped, and the Release
carries no `witness-2.2.0.json`. `2.2.0.json` here was built by hand with the same builder over
that run's own inputs, plus the one argument the next section describes, and `PUBLICATION.md`
entry 20 records the ruling. The release procedure in `MIGRATIONS.md` says to confirm the job
succeeded before the witness round commits anything, and since 2026-09-17 also says what the
approval comment must carry so that it can — and on `v3.0.1` it did. `tests/test_cdm_witness.py`
holds this paragraph to the directory: it went red the day the third record landed, was rewritten
to say what that run did, and goes red again on a fourth.

**`3.0.1.json` is the pipeline's own record, 2026-09-20.** On the `v3.0.1` run
([35514833652](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/35514833652))
the `witness` job succeeded end to end, its third execution on a tag push. Its build step read the
run's one approval — given at 14:43:10Z with a comment naming the readiness report at the release
commit, so `review_file` is derived from the comment and designated by nobody — and the `pypi`
deployment's status history (`waiting` 14:19:09Z, `queued` 14:43:10Z, `in_progress` 14:43:12Z,
`success` 14:43:39Z), under the `actions: read` and `deployments: read` grants; fetched the
attestation store by the wheel's digest and handed the builder `--attestation-bundles`; and wrote
`witness-3.0.1.json for v3.0.1 (2 files, 1 approval(s))`. Its verify step, `--download --assets
assets` with a token, read `VERIFIED witness-3.0.1.json (3.0.1, against the index and Release and
the assets under assets)`. Its attach step uploaded the file to the Release, where it is the ninth
asset, 2 188 bytes, sha256 `32cd277e2f68157de29188a0d59ef136ebe19dc63b3b37788934ea5049292acd`.
`3.0.1.json` here is that asset byte for byte — the same digest, which `tests/test_cdm_witness.py`
holds — downloaded by the witness round and verified again, offline against the Release download
and online with `--download`, before it was committed. `PUBLICATION.md` entry 21 is the ledger's
account, and the run before it, 35200069387, is the refusal this success is measured against.
This is the first release whose committed record is the pipeline's own; the two before it say in
the paragraph above why theirs are not.

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
| `approvals` | `[{environment, approved_at, approver, comment, review_file}]` — the `pypi` hold: who released it, the approval comment verbatim, and the public reference the comment names — or, for 2.2.0, the reference the ledger's entry 20 designates — or the empty string |

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

**What `review_file` means for 2.2.0 — designated, not derived (2026-09-17).** The `pypi`
approval of the `v2.2.0` run carried an EMPTY comment: the API's `comment` is `""`, `2.2.0.json`
carries it as such, and the builder wrote `""` into `review_file` too, which is what the
pipeline's verify step refused. The value `2.2.0.json` carries instead —
`https://github.com/Decent-Cybersecurity/synapsecommand-public/blob/5c53e756b9aa31c2881bd4497b2e0b30b7730944/docs/soif-part1-release-readiness.md`,
the release-readiness report at the release commit, the document the release-readiness protocol
says an approval is taken on — was designated by the maintainer in the witness round, and not
named by the approval. It reached the record through the builder's `--review-file URL` flag,
added the same day so the designation is a command rather than an edit: the flag is accepted only
as an `https://` URL, applied only to an approval whose comment names no URL, refused when the
comment names a different one, and never passed by `publish.yml` — the pipeline's record is the
approval's own words or nothing. `PUBLICATION.md` entry 20 states the designation, states that
the comment was empty, and gives both digests: the refused shape's and the committed one's, which
differ in that one line.

**What `review_file` means for 3.0.1 — derived, as the design intends (2026-09-20).** The `pypi`
approval of the `v3.0.1` run carried the comment *Approved on the readiness report at the release
commit:* followed by the report's URL at `89d2c707`, so the builder lifted that URL into
`review_file` from the approval's own words; `--review-file` was not passed, `publish.yml` never
passes it, and the record's `comment` and `review_file` name the same document. It is the first
record in this directory whose `review_file` was derived rather than designated or private.

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
`not established` rather than refusing, because the absence is recorded as deliberate. `2.2.0.json`
is the first record to carry a digest — `9d78a520…`, over the one bundle the store serves for the
2.2.0 wheel — and `--download` reads it back and agrees.

`artifact_sha256` against `pypi.files` is the one cross-check that needs no network at all, and it
is the one most worth having: those are the same claim written by two different steps, and a
release where they disagree uploaded bytes nothing gated.
