# Publication

This repository became public on **2026-08-25**. It is
<https://github.com/Decent-Cybersecurity/synapsecommand-public>.

## Why this file exists

Everything below was, until this file, recorded only in commit messages. A commit message is the
right place for *what a round did* and the wrong place for *what is true now*: it is addressed to
whoever reads that diff, it is not indexed by anything, and a reader looking for the publication
story has to know which commit to read. Facts here — the unsigned history, the
five unread front matters, the ruling that leaves `DCO` advisory — are ledger entries a future
round or a human has to act on or has now settled, and an entry of either kind that lives in a
closed commit message is an entry nobody will find.

So the publication story is in the tree. The mechanism-level facts stay where their mechanism is —
the deploy in [`docs/README.md`](docs/README.md), the sign-off procedure in
[`CONTRIBUTING.md`](CONTRIBUTING.md), the licence boundary in [`NOTICE`](NOTICE) — and this file
records the *state*, points at them, and does not restate them. That is deliberate: a fact stated
twice is a fact that can disagree with itself, and this repository's answer to that is either one
site or a gate requiring the sites to agree. Where a claim here is also enforced by a test, the
test is named beside it.

`tests/test_cdm_publication.py` gates the parts of this file that are decidable from the tree.
It cannot reach GitHub, and it does not pretend to — see "What is gated and what is witnessed".

## Proven by behaviour, not by a settings page

The protections below were verified by *doing the thing they forbid and being refused*. A settings
page shows what someone intended; a refusal shows what is enforced. Each entry names the probe.

### Visibility

`GET /repos/Decent-Cybersecurity/synapsecommand-public` **with no credentials** returns HTTP 200
with `"private": false` and `"visibility": "public"`. An anonymous `git clone` over HTTPS succeeds
and its `HEAD` matches the pushed tip of `main`. Both were run from a clean environment with the
credential helper disabled, because a probe that quietly authenticates proves nothing about what a
stranger can see.

### The `main-protection` ruleset, and its history is not what it looks like

Repository ruleset **`main-protection`** (id 21205830), target `branch`, condition
`ref_name.include = ["~DEFAULT_BRANCH"]`, `enforcement: active`, **`bypass_actors: []`**, rules
**`deletion`** and **`non_fast_forward`**.

The API's own version history says something the pre-flip round did not expect, and it is recorded
here rather than smoothed over:

| Version | When (UTC) | Rules |
| --- | --- | --- |
| 47325537 | 2026-08-22 18:36:54 — **while the repository was private** | `deletion`, `non_fast_forward`, `pull_request` |
| 47570967 | 2026-08-25 09:21:26 | `deletion`, `non_fast_forward`, `pull_request` |
| 47572109 | 2026-08-25 09:32:10 | `deletion`, `non_fast_forward` |

Two consequences, both worth stating plainly:

- **The ruleset was not created after publication.** It was created an hour after the repository
  was, three days before the flip, already `active`. The pre-flip ledger recorded that branch
  protection and rulesets "return HTTP 403 — *Upgrade to GitHub Pro or make this repository public
  to enable this feature*". That is true of the **classic branch-protection** API and is not true
  of the rulesets API, which accepted this ruleset while the repository was private. Whether it was
  *enforced* during those three days is a separate question and this file does not answer it: the
  repository is public now, so the experiment is no longer available. What is certain is that a
  direct push to `main` succeeded at 09:11:47 on the day of the flip while a `pull_request` rule
  was in force, which is consistent with the rule being stored and not applied — and is not proof
  of it.
- **The post-flip edit narrowed the ruleset rather than creating it.** The `pull_request` rule was
  **removed** at 09:32:10. That is what keeps this repository's actual workflow — commit locally,
  push to `main` — legal. It also means the shape recorded above is a deliberate choice against
  requiring pull requests, which is the fact the status-check ruling below turns on.

**The probe: a non-fast-forward push to `main` is refused.**

```
$ git push --force origin HEAD~1:refs/heads/main
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: Review all repository rules at .../rules?ref=refs%2Fheads%2Fmain
remote:
remote: - Cannot force-push to this branch
 ! [remote rejected] 4732429... -> main (push declined due to repository rule violations)
```

`main` was unchanged afterwards. Note what the refusal does and does not say: it names **the rule**
("Cannot force-push to this branch") and links to the rules page. **It does not name the ruleset.**
`GET /repos/{owner}/{repo}/rules/branches/main` is what maps the refusal back to a name, and it
attributes both `deletion` and `non_fast_forward` to ruleset 21205830, `main-protection`. Anyone
verifying this later should expect the rule text and not the ruleset name in the git output.

**The `deletion` rule is not observable on `main`, and this is a limit of the probe, not a gap in
the protection.** `git push origin --delete main` is refused with
`refusing to delete the current branch: refs/heads/main` — no `GH013`, no rule citation. That is
GitHub's default-branch guard, which is older than rulesets and fires first. So the deletion rule
is recorded from the API and is **unwitnessed by behaviour**; witnessing it would need a
non-default branch inside the ruleset's scope, and the scope is `~DEFAULT_BRANCH` alone. Stated
rather than quietly counted as proven.

**The workflow survives the ruleset.** A normal signed push to `main` — the commit that adds this
file — succeeded.

### The DCO check

The [DCO GitHub App](https://github.com/apps/dco) (app id 1861, slug `dco`) is installed on the
**Decent-Cybersecurity** organisation with `repository_selection: selected`, installation id
156427530, created **2026-08-25 09:32:51 UTC**.

**Status-check name, as GitHub reports it: `DCO`.** That is the value the ruleset's
"Require status checks to pass" needs, with the integration set to the **DCO** app (id 1861). It is
a *check run* on the Checks API, not a legacy commit status: the combined-status endpoint reports
`"state": "pending", "total_count": 0` for the same commit, so anything wired against commit
statuses would see nothing at all.

**The probe, which was also this check's first-ever run.** Branch `dco-probe`, one commit with no
`Signed-off-by`, pushed, and pull request #1 opened against `main`. The check ran at
2026-08-25 09:37:25 UTC and refused it — conclusion **`action_required`**, not `failure`:

> There is one commit incorrectly signed off. This means that the author of this commit failed to
> include a Signed-off-by line in the commit message.
>
> […]
>
> ### Summary
>
> Commit sha: 1be8247, Author: Matej Michalko, Committer: Matej Michalko; The sign-off is missing.

The commit was then amended with `git commit --amend -s --no-edit` and force-pushed to the scratch
branch. The check re-ran at 09:37:58 UTC and passed:

> All commits are signed off!

Pull request #1 was closed and `dco-probe` deleted. **The closed pull request is the artefact and
it stays**: it is the only durable public evidence that the failing state was observed, and
deleting it to make the pull-request list read zero would be tidying away the proof. `main` never
carried the probe commit, and `DCO_PROBE.md` exists in no commit reachable from `main`.

That `action_required` rather than `failure` is worth recording, and it outlives the ruling below
that declines to require the check: a required check treats `action_required` as not-passing, so it
would block — but any automation wired to look for `failure` finds this check green on a commit it
just refused. The value is what a reopening would need to be correct about, and it is what anybody
reading the check's conclusion today has to know.

## Open ledger

Six entries, and the set does not move — entries change **state**, they are not deleted. Three are
**settled**: entry 1 is a ruling, and entries 5 and 6 are closed by acts. Entry 5 records the 1.0.0
upload a human performed, what was measured off the index afterwards, and which step of its own
sequence was skipped. Entry 6 is the one that retired the way entry 5 worked: it was written open,
before the configuration it specified existed, and it closed in three acts — a trusted publisher
registered on PyPI, 1.1.0 published through the workflow over OIDC, and the 1.0.0 API token revoked.
Reading the two in order is the whole story of how publishing this package stopped needing a
credential. Entries 2, 3 and 4 are open. None blocks anything.

### 1. `DCO` stays advisory — RULED, and the wiring is deliberately not done

**The ruling.** `main-protection` carries **no `required_status_checks` rule** and will not
acquire one; the `pull_request` rule stays removed; direct pushes to `main` continue. The `DCO`
check runs, reports, and does not gate. This closes the decision the pre-flip round left open, and
it is recorded here — beside the state it describes — rather than in the commit message that made
it, which is the mistake this whole file exists to stop repeating.

`CONTRIBUTING.md` says so in the contributor's terms; it must keep saying so, and
`tests/test_cdm_publication.py` requires the two files to agree about it and now also requires both
to state that this is settled rather than pending.

**Ground 1: requiring the check would refuse every push this repository makes, and that half is
measured.** A required status check in a branch ruleset gates **pushes to the branch**, not merges
alone; the DCO app produces check runs on **pull-request** events only. The commit that added this
file, `f916ba2`, was pushed directly to `main`, and `GET /commits/f916ba2/check-runs` returns
`total_count: 0` — no check run at all, because there was no pull request. A commit that can never
acquire a `DCO` check can never acquire a passing one. The `pull_request` rule was removed at
09:32:10 deliberately, to keep direct pushes legal, so requiring the check without restoring that
rule is a deadlock and requiring it *with* that rule is a different repository — one where every
contribution including the maintainer's goes through a pull request. Both were on the table; the
second was declined because nothing about this project's actual working shape wants it.

What is *still* inferred, and is stated as inferred: that the ruleset would then refuse the push.
Testing it means making the change being declined, so it stays a reason rather than a claim.
Nothing in this ruling rests on it — ground 1 stands on the measured zero.

**Ground 2: sign-off is already enforced, earlier, by something that cannot be bypassed by not
opening a pull request.** `tests/test_cdm_publication.py` recomputes the unsigned-commit set from
the actual history on every suite run and requires it to equal the three named in entry 2. A fourth
unsigned commit fails the build before the push, not after it. It reads trailers through git's own
`%(trailers:key=Signed-off-by,valueonly)` — **the same notion of a trailer the DCO app applies**,
so a line that looks like a sign-off in the middle of a paragraph is not one to either of them.
The platform check and the local gate therefore agree about what they are checking, and the local
one runs first and covers the direct-push path the platform check cannot see.

**Ground 3: the check keeps its whole value for the people it was installed for.** It runs on any
outside pull request whether or not it is required, and reports there — `action_required` on an
unsigned commit, as witnessed above. Making it required would add nothing for an outside
contributor; it would only take something away from the maintainer's workflow. And the guide is
explicit that a pull request carrying an unsigned commit will not be merged: what changed is who
refuses it, not whether it is refused.

**Reopening this is allowed and is an act, not a drift.** If direct pushes to `main` ever stop
being the working shape, the honest sequence is: restore `pull_request`, then require `DCO`, then
probe the result the way the protections above were probed — and update both sites in the same
commit, which the gate will insist on.

### 2. Unsigned history: three commits, known and accepted

Three commits carry no `Signed-off-by` trailer:

| Commit | Subject |
| --- | --- |
| `d7986017` | Initial commit |
| `2a51871f` | Update README.md |
| `965e939d` | synapse_cdm standalone package: CDM, harness, PNTMAP reference adapter |

The first two were made in the GitHub web UI, which does not offer a sign-off. **DCO enforcement
is forward-looking and must not be read as a claim about the history.** No history rewrite is
contemplated: rewriting three commits to satisfy a check that was installed afterwards would
falsify the record of how this repository was actually built, and the check exists to make
provenance legible rather than tidy.

This is stated as a **set of three named commits** and not as a ratio. "44 of 47 are signed" was
the pre-flip phrasing and it is a number that moves on every commit — a stale count with a
guaranteed expiry date. The set does not move, and
`tests/test_cdm_publication.py` computes the unsigned set from the actual history and requires it
to be exactly these three: a fourth unsigned commit fails the build, and so does removing one of
these three from this table while it is still unsigned.

### 3. Five distribution statements, pending a human read

Five pinned documents yield **no distribution statement** from their extractable text, so none has
been read: the two **AEDP-4607s** (Ed. A v1 and AEDP-4607.1 Ed. A v1), **MISP-2019.1**, and the two
**AEDP-12s** (Ed. B v2 and AEDP-12.1 Ed. A v1). AEDP-12 Ed. B v2 yields 802 characters across eight
front pages, which is what "the front matter is image-only" means in practice — the text layer is
not there to read.

**No bytes ship either way, and that is what makes this a deferral rather than a risk.** No pinned
document is in the tree or in the history; the pin records carry SHA-256, byte count, page count,
edition and source URL and nothing else. `NOTICE` states the licence boundary and
`tests/test_cdm_pins.py` enforces the mechanism — every pinned PDF untracked, and `.gitignore`
refusing to stage one before the gate has to. This entry is a **human read of five front matters**,
not a guess a round is entitled to make.

### 4. What publication newly exposed — reported, not acted on

- **GitHub attributes almost none of this repository to anyone.** `GET /contributors` returns a
  single contributor with **2** contributions. Those two are `d7986017` and `2a51871f` — the two
  unsigned web-UI commits. The other 46 commits are authored by `m@decentcybersecurity.eu`, which
  is not associated with a GitHub account, so `commit.author.login` is `null` and Insights →
  Contributors shows the repository as very nearly unwritten. The address is real and reachable,
  which is what `CONTRIBUTING.md` requires of a sign-off, and the DCO check accepts it — GitHub's
  attribution views are a separate system from the sign-off and are not evidence about it. Adding
  the address to the account would populate them. Nothing here is broken; it is simply a surprising
  thing for a first visitor to see, and it is the sort of surprise that gets misread as "nobody
  works on this".
- No commit in the history is GPG/SSH-signed (`verification.verified` is `false` throughout).
  Sign-off and cryptographic signing are different claims and only the first is required here.
- **Dependency graph:** not enabled — the SBOM endpoint returns 404. **Secret scanning:** disabled.
  **Dependabot security updates:** disabled. All three are available to a public repository and all
  three are off; none is asserted anywhere to be on.
- **Code search** returns `total_count: 0` for terms that certainly occur in the tree: GitHub has
  not indexed the repository yet. Expected shortly after a flip, and worth knowing before anyone
  reads a zero as an absence.
- **Community Standards** reads 50%: `README`, `LICENSE` and `CONTRIBUTING` present; no code of
  conduct, no issue template, no pull-request template. A newly visible page, listed here so the
  absences are on the record as absences rather than oversights.

### 5. `synapse-cdm` 1.0.0 is on PyPI — CLOSED, and one step of the sequence it named did not run

The SDK round built and verified a publishable distribution and stopped short of publishing it.
A human with credentials did the upload on **2026-08-25**: `twine check --strict` on both
artefacts, then `twine upload packages/cdm/dist/*`. The entry stays here in its closed state
rather than being deleted, and it keeps the six-step sequence it was written around — because the
sequence is now a record of what was and was not done, which is worth more than the instruction
was.

**What is on the index, measured rather than reported.** `GET https://pypi.org/pypi/synapse-cdm/json`
and `GET https://pypi.org/simple/synapse-cdm/`, both HTTP 200 on 2026-08-25:

| | |
| --- | --- |
| project | `synapse-cdm`, **1.0.0 and no other release** |
| wheel | `synapse_cdm-1.0.0-py3-none-any.whl`, 2 271 091 bytes, uploaded `14:53:12Z` |
| sdist | `synapse_cdm-1.0.0.tar.gz`, 1 172 220 bytes, uploaded `14:53:14Z` |
| metadata | author `Decent Cybersecurity s.r.o.`, licence `Apache-2.0`, `Requires-Python >=3.11` |
| dependencies | `pydantic>=2.6` and `jsonschema>=4.0`, with `pytest>=8.0` behind the `test` extra |
| project URLs | all five present — Homepage, Documentation, Source, Issues, Changelog |

Every one of those is the metadata `tests/test_cdm_packaging.py` asserts against `pyproject.toml`,
now read back off the index instead: the gate said what the distribution would claim, and this is
the claim as strangers receive it.

**The uploaded files are the files the gate verified, and that is a hash comparison and not a
belief.** PyPI serves both artefacts under their SHA-256, and both digests equal
`shasum -a 256 packages/cdm/dist/*` on the machine that built them:

```
03b5df15aeb215f8bfb32c4004be29c62b5ec98b98200a6859cc98ac85dad688  synapse_cdm-1.0.0-py3-none-any.whl
61892843561f794bf8298427df6d4df7883e5f18d084a2124fbd88975ff4db4e  synapse_cdm-1.0.0.tar.gz
```

That is the one connection `tests/test_cdm_release.py` names as beyond it — "whether an artefact
was ever published for a tag, and whether that artefact came from that tree" — made by hand once
and written down. `gates/wheel_install.py` proves the local wheel installs clean and passes the
harness; these two digests are what carry that proof onto the artefact a stranger downloads. The
tag `v1.0.0` was created at `14:30:06Z` and points at `1a62104`, whose `PACKAGE_VERSION` is
`1.0.0`; the upload followed it by twenty-three minutes.

**The second upload attempt returned 403, the first had succeeded, and nothing was duplicated.**
A filename on PyPI can never be reused, even after a release is deleted, so a 403 naming files
that already exist is the index refusing a re-upload rather than rejecting a credential — it is
evidence the first upload completed. The index corroborates it from the other side and that is
the half worth recording: **one** release, **two** files, one of each package type. A duplicate
upload would have had to appear as a second release or a third file, and there is neither.

**Verified from the index, in an environment with no clone in it.** A fresh virtualenv,
`pip install synapse-cdm`, and then every registered adapter run through the harness with no
`--fixtures` — so the fixtures were resolved through `importlib.resources` out of site-packages,
which is the property the SDK round added and the only one that could not be tested from a
checkout:

| | | | | |
| --- | --- | --- | --- | --- |
| `adsb` 32 | `ais` 22 | `cat021` 40 | `cat034` 34 | `cat048` 82 |
| `gmti` 32 | `legion` 6 | `pntmap` 4 | `stanag4676` 34 | `tak` 12 |

**Ten adapters, 298 fixture verdicts, 0 failed.** The per-adapter figures are written out because
298 is a number nobody can check and ten numbers that sum to it are.

**Ten is the roster OF 1.0.0 and not of `main`.** `cat062` and `cat023` landed afterwards and
are in `MIGRATIONS.md`'s history, so the tree ships thirteen adapters and the
release this block verifies carries ten. The table above is what a `pip install synapse-cdm`
gets, which is the whole point of the block: it is a measurement of the artefact a stranger
downloads, and it does not move when `main` does. The stale-count sweep names this sentence
as the subset it belongs to rather than updating the number, because updating it would
falsify the record.

**Step 3 did not run.** `synapse-cdm` returns **404 on TestPyPI**, measured in the same minute as
the two 200s above, so there was no TestPyPI upload and the project page was never previewed
before an upload that cannot be undone. It is recorded rather than dropped for the reason this
whole file exists: a written sequence whose steps are quietly skipped becomes a description of
what somebody meant to do. The risk it was guarding — a long description that renders wrongly on
a page nobody can amend — was covered from the other direction by `twine check --strict`, which
passed on both artefacts, so what was lost was the visual preview and not the rendering check.

**What the index cannot show, and is therefore not claimed here.** Steps 1, 2 and 4 — the account's
two-factor status, whether the owner is the company or a person, and whether the API token is
project-scoped — are invisible to an anonymous reader: the JSON API carries no maintainer field
for this project, and `author` is metadata the uploader typed rather than an identity the index
vouches for. One inference is available and is stated as an inference: PyPI has required 2FA for
uploads since 2024, so an upload that succeeded came from an account that has it.

**A correction to how the name was checked.** The open form of this entry called `synapse-cdm`,
`synapse_cdm` and `synapsecdm` "one name checked three ways rather than three names". Two of them
are one name: `synapse_cdm` now answers `301` to the canonical `synapse-cdm`, which is PEP 503
normalisation working. `synapsecdm` is **not** that name — normalisation collapses runs of `-`, `_`
and `.` to a single `-`, it does not delete them — and it is still 404, still unclaimed, and always
was a different project. Nothing rested on the error; it is corrected here rather than left in a
sentence that reads as measured.

**The accepted limitation is now a live page rather than a forecast.** The long description is the
package's own `README.md` and its fifteen links are relative, so they do not resolve on the project
page. That was ruled deliberate before the upload and the ruling stands: the links are correct in
all three places the file actually lives — the repository, the sdist and the installed package —
and absolute `blob/main` URLs baked into a released wheel would point a 1.0.0 reader at whatever
`main` says years later. The five `project.urls` entries are the navigation, and all five are on
the page.

**What closing this does not close.** There is still no CI, no `.github/workflows` and no Trusted
Publishing: the next release is another human act, and MIGRATIONS.md's release procedure is still
the whole of the mechanism. Nothing here was automated to close the entry, which was the failure
mode the open form of it named.

> **Superseded by entry 6, and left standing.** The paragraph above was true when this entry
> closed and is false now: `.github/workflows/publish.yml` exists, and the mechanism is no longer
> only a sequence a person runs. It is not edited, because a closed entry is a record of what was
> known at the time it closed and a ledger that quietly updates its history is a ledger nobody can
> date. The pointer is the correction. What entry 6 does *not* yet supersede is the last clause:
> until the configuration entry 6 specifies exists on pypi.org, the next release is still a human
> act, because a workflow with no trusted publisher on the other side cannot upload anything.
>
> **And one pointer in this entry no longer resolves.** The paragraph above about the 1.0.0 roster
> sends a reader to `MIGRATIONS.md`'s `### Unreleased` section; that section was renamed to
> `### 1.1.0` when the release absorbed it, which is what the release-condition test requires it to
> do. The measurement it accompanies — ten adapters, 298 fixture verdicts, the roster OF 1.0.0 — is
> unchanged and is still what a `pip install synapse-cdm==1.0.0` gets. Corrected here rather than
> in the sentence, for the reason this whole block exists.

**The sequence as written, and what happened to each step.**

| # | Step | Outcome |
| --- | --- | --- |
| 1 | PyPI account with 2FA | not observable; inferred from an upload that succeeded |
| 2 | Decide the owner — organisation, not individual | not observable from the index |
| 3 | **TestPyPI first**, install from it, preview the page | **DID NOT RUN** — 404 on TestPyPI |
| 4 | Project-scoped API token | not observable from the index |
| 5 | `build`, `twine upload`, verify from a clean venv | ran; the verification is the table above |
| 6 | Update `README.md`, `docs/docs/intro.mdx` and this entry | this commit and the one after it |

### 6. Trusted Publishing is the only way in — CLOSED, and the old door is revoked rather than unused

`.github/workflows/publish.yml` publishes `synapse-cdm` to PyPI over OIDC, with no password, no
token and no secret in the file. That workflow is on `main` and it **cannot upload anything yet**:
OIDC publishing needs a trusted publisher registered on the PyPI project, and nothing in this
repository can create one. A file in a repository cannot grant itself an identity on an index.

So this entry is the human half, and it is written **before** the machine half rather than after —
the arrangement entry 5 got right and then failed to benefit from, because entry 5 named a
six-step sequence and step 3 was discovered to have been skipped only when an anonymous reader
went looking for it on TestPyPI afterwards. A step that exists only in somebody's memory of the
plan is a step that can be skipped without leaving a mark. These have marks.

**Two things must happen, and this entry closes when both have.** They are not the same act and
the second is not implied by the first: registering the publisher makes an OIDC upload *possible*,
and revoking the token is what makes it the *only* way in. A repository with both a working trusted
publisher and a live long-lived token has not retired anything — it has two doors and one of them
is still the one that was used for 1.0.0.

> **Both have happened.** Written when neither had. The publisher was registered, 1.1.0 published
> through it on 2026-08-26, and the token was revoked the same day — in that order, which the step
> C section explains was the only safe one. There is one door.

#### Step A — register the trusted publisher on PyPI

Nobody but a maintainer of the `synapse-cdm` project can do this. Signed in on `pypi.org`:

**Your projects → `synapse-cdm` → Manage → Publishing → GitHub → Add**

Four values. They are not guesses and they are not defaults — each one is a fact about this
repository, and PyPI matches the OIDC token's claims against all four, so a single wrong character
is a refused upload rather than a warning:

| Field on the PyPI form | Value | Where the value comes from |
| --- | --- | --- |
| Owner | `Decent-Cybersecurity` | the first sentence of this file, which `tests/test_cdm_publication.py::canonical_owner` derives and sweeps the tree against |
| Repository name | `synapsecommand-public` | same sentence |
| Workflow name | `publish.yml` | the **filename** under `.github/workflows/`, not the `name:` inside it — PyPI matches the path, and `Publish to PyPI` would be refused |
| Environment name | `pypi` | the `environment:` of the workflow's publish job, and step B below |

The Environment name field is optional on the form and is **required here**. Leaving it blank
would let any workflow run in this repository that reaches the publish job assume the publisher's
identity; filling it in means PyPI refuses a token whose `environment` claim is not `pypi`, and
`pypi` is a protected environment whose only job is that upload. An optional field left blank is
how the narrowest possible grant becomes a broad one silently.

#### Step B — the environment, and the reviewers on it

`pypi` exists as a GitHub environment on this repository, created this round at
`2026-08-26T06:46:16Z`. Unlike steps A and C, this one is **done**, and it is observable — the
environment and its rules are public API on a public repository:

| Rule | Value | Why |
| --- | --- | --- |
| required reviewers | `decentcybersecurity` | the human confirmation step, below |
| deployment branch policy | tag pattern `v*` only | a second lock, described below |
| `prevent_self_review` | `false` | there is one maintainer; see the note |
| `wait_timer` | `0` | a delay is not a decision, and this gate wants a decision |

**The branch policy is deliberate belt-and-braces.** The workflow's publish job already refuses to
run on anything but a tag, by its `if:`. The environment refuses *independently*, at a layer the
workflow cannot edit: even a `publish.yml` whose tag guard was deleted could not deploy to `pypi`
from a branch, because the environment would decline the deployment. Two locks on the irreversible
act, and the outer one is not in the file that a mistaken edit would be in.

**`prevent_self_review: false`, named because it is the weak point.** GitHub can forbid the person
who triggered a deployment from approving it. That is the stronger setting and it is *off*, because
this repository has one maintainer: with it on, the only person who can push a tag is the only
person who could approve it, and the gate would be a deadlock rather than a review. So the honest
description of this gate is **a confirmation prompt, not a second pair of eyes** — it defends
against a mistaken or automatic tag, not against a determined maintainer. It should be turned on
the moment a second maintainer exists, and that is the trigger to watch for rather than a periodic
review.

The reviewer requirement is the ruling, and the reasons are stated because the opposite ruling is
defensible and someone will reconsider it:

* an upload to PyPI **cannot be undone**. A yanked release still occupies its filename forever, and
  `synapse_cdm-1.1.0-py3-none-any.whl` can never be re-uploaded once any bytes have held that name.
  Every other act in a release is revocable — a tag can be moved, a GitHub release deleted, a
  commit reverted. This one is not, and it is the one that was about to become automatic;
* the tag is a human act, but it is not the *same* human act. `git push --follow-tags` also pushes
  commits, so a tag can reach the remote as a side effect of pushing a branch. The reviewer prompt
  is the first point at which a person is asked specifically about the upload;
* the cost is one click on a release, and the benefit is that a workflow defect — a bad `if:`, a
  trigger that matches more than `v*` — cannot reach the index before a person sees it.

The ruling **against** it, recorded so it is not re-argued from scratch: a required reviewer who
approves every time approves without reading, and a gate that is always approved teaches people to
approve. That is real, and it loses to irreversibility. Revisit it if the approval ever becomes
routine enough to be automatic, and if it is revisited, the ruling changes here rather than in
somebody's settings page.

#### Step C — retire the token, which is the point of the round

After the **first successful OIDC publish** — the 1.1.0 release, not before, because a token
revoked while it is still the only working path is a release nobody can cut:

**`pypi.org` → Account settings → API tokens → the token used for the 1.0.0 upload → Remove token**

**Revoked, not merely unused.** An unused token is a credential that still works, held by whoever
holds it, with no expiry and no record of where it has been copied. "We do not use it any more" is
a statement about intent; a revoked token is a statement about capability, and only the second one
survives the laptop it was pasted into. Entry 5 could not observe whether that token was
project-scoped and this entry cannot either — which is itself an argument for removing it rather
than reasoning about its blast radius.

#### What this entry does not claim

* ~~**Not that the publish lane works.** It has never run.~~ **It has now.** `synapse-cdm` 1.1.0
  was published by the workflow on **2026-08-26**, and the details are in "The publish, measured"
  below. The sentence is struck rather than deleted because the entry was written to be read in
  order, and "this had never run when it was written" is the fact that makes the rest of it
  legible.

  The build half **has** been run, three times, and the first two failed. That is the record:

  | Run | Outcome | What it found |
  | --- | --- | --- |
  | [32939921536](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/32939921536) | FAILED in 25s | all 35 test modules failed collection on `No module named 'pydantic'`. The install step installed `pytest twine` and never installed the package — the workflow had been written from what the suite needs to run, not from what a clean machine needs to run it |
  | [32940039945](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/32940039945) | FAILED in 1m20s | suite, gate and `twine check --strict` green; the schema check failed with six `missing` lines because the step ran in `packages/cdm` and the published `schemas/` are at the repository root. The same wrong assumption had the derivations step listing a path that does not exist — which would not have failed the build, only put an error into a release-notes summary |
  | [32940226037](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/32940226037) | **SUCCESS in 1m21s** | `13 checks, 0 failed`; 12 adapters, 776 fixture verdicts; mutation caught by five checks; `twine check --strict` PASSED on both artefacts; the publish job **skipped**, and the two tag-only steps skipped |

  Both failures were defects in the workflow rather than in the tree, and neither was reachable by
  reading the file. A workflow whose build half had never been executed would have carried them to
  the 1.1.0 release, where the first thing to discover them would have been the release itself.
  This is the whole argument for `workflow_dispatch` existing.

* **Not that a CI green equals a maintainer's green.** The successful run reports `2857 passed, 31
  skipped`; a maintainer's machine reports `2886 passed, 2 skipped`. The total is identical and the
  29 extra skips are by design — the pinned specification documents are gitignored and never
  committed, so a fresh clone holds the pin records and not the PDFs, and those tests skip saying
  so. It is recorded because the same shape is what a real defect looks like: a test that quietly
  stops running reports as a pass. The workflow now runs the suite with `-rs` so the list is in the
  log rather than inside a single number.
* **Step A is now observable, indirectly, which is the best this could ever have been.** The PyPI
  project's publishing settings are not public, so no stranger can read the trusted publisher off
  the index. But an OIDC upload that SUCCEEDED is evidence that one exists: there is no other way
  those files reached the index, because no API token was used and none was present to use. The
  forecast in this bullet — "the only evidence that A happened will be a successful 1.1.0 publish"
  — is what actually happened, and it is now the evidence.
* ~~**Not that the old token is gone.** It is live as this is written.~~ **It is gone.** Revoked
  2026-08-26; see step C. The sentence is struck rather than deleted for the same reason as the one
  above it — this entry was written forwards, and the state it was written in is what makes it
  readable.

#### The publish, measured

`synapse-cdm` **1.1.0** was published on **2026-08-26** by
[run 32944124955](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/32944124955),
triggered by the `v1.1.0` tag. Both jobs succeeded. This was the publish lane's first execution
ever — the release was the test.

| | |
| --- | --- |
| Trigger | `push` of the annotated tag `v1.1.0` |
| Job 1, on the tagged tree | suite 2872 passed / 33 skipped; `tag=v1.1.0 PACKAGE_VERSION=1.1.0`; the tag confirmed annotated with its tagger; the wheel gate **13 checks, 0 failed**; mutation refused by five checks; `twine check --strict` PASSED on both artefacts |
| The reviewer gate | Job 2 held at the `pypi` environment and approved by `decentcybersecurity`, 14 minutes after Job 1 finished. The pause is the design, not a fault |
| Credential | none. `id-token: write` on the publish job, a minted OIDC token, no `password:` and no `secrets.*` anywhere in the workflow |
| Attestations | generated and uploaded alongside the artefacts |

SHA-256, as the workflow's `--export-dist` handed them to the publish job:

```
745e8b641d715fd5988f1e5f219c8f8f83f38925c20408376c95e813d7a22d98  synapse_cdm-1.1.0-py3-none-any.whl
7987b4f40186ca313dfa11ba73505e8a9aeca7e48396e6655c7e74d6ed374579  synapse_cdm-1.1.0.tar.gz
```

**Both equal what PyPI serves**, read back from `https://pypi.org/pypi/synapse-cdm/1.1.0/json`
after publication, and equal again in files downloaded from the index. That closes the chain the
`--export-dist` argument was made for: ONE build, gated as that build, uploaded as those bytes,
served as those bytes. The point is not abstract — the same tree built locally during this round's
verification produced `8bb3d8e1…` for the sdist, different bytes for identical content, so a
workflow that rebuilt instead of handing over what it gated would have shipped a file the 13 checks
never saw.

**Verified from the index, as 1.0.0 was.** `pip install synapse-cdm==1.1.0` into a fresh
virtualenv with no part of this repository on its path: version `1.1.0`, `schema_version` `1.0.0`,
imported from `site-packages`, all **twelve adapters replayed from the packaged fixtures — 388
verdicts, 0 failed**, all six schemas regenerated byte-identical to the published set, and both
console scripts working. The GitHub release for `v1.1.0` carries the notes and both artefacts.

**Where this stands.** Two of the three closing conditions are met:

| Step | State | Who can verify it |
| --- | --- | --- |
| A — trusted publisher registered on pypi.org | **done** | not readable from the index, but proven indirectly: an OIDC upload succeeded and no token was used |
| B — the `pypi` environment with reviewers | **done** 2026-08-26T06:46:16Z | anyone; it is public API on a public repository |
| — a tag published through the workflow | **done** | run 32944124955, digests above |
| C — the 1.0.0 API token revoked | **NOT DONE** | only the maintainer |

#### 1.2.0, verified from the index — and the digest comparison nobody had run for it

`synapse-cdm` **1.2.0** was published on **2026-08-26** by
[run 33023449211](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/33023449211),
triggered by the `v1.2.0` tag. Both jobs succeeded. This block is the **re-verification**, run on
2026-08-27 in an environment with no clone on its path, and it exists because the digest comparison
below had not been made for this release — 1.0.0 and 1.1.0 each carry one and 1.2.0 did not.

**Installed from the index, not from the local wheel.** A fresh virtualenv, `pip install
synapse-cdm==1.2.0` with `--no-cache-dir`, resolving only the declared dependency surface —
`pydantic`, `jsonschema` and their transitive closure, nothing else. Read back from the installed
copy in `site-packages`:

| | |
| --- | --- |
| `PACKAGE_VERSION` | `1.2.0`, and `Version:` in the installed `METADATA` agrees |
| `SCHEMA_VERSION` | `1.0.0` — unmoved, which is the claim the release was made to test |
| `--list-adapters` | **13 adapters**, `stanag4609` among them at `1.0.0`, fixtures resolving to `klv` |
| harness | `--adapter stanag4609` against the installed copy: **20 passed, 0 failed**, fixtures resolved from `site-packages/synapse_cdm/fixtures/klv` |

The SKIPs in that run are the expected binary-adapter pattern and not a shortfall: `lossless` skips
on a raw `.klv` fixture and runs — and passes — on each `.parsed.json` sibling, and `roundtrip`
skips wherever `from_cdm()` returns bytes the check cannot parse as JSON. **The second of those is
now a register entry** rather than a footnote; see below.

**The digests, which is the comparison this block was written for.** Three readings of the same two
files: what the gated job hashed before handing them over, what the publish job hashed immediately
before uploading, and what the index serves now — the last read back from
`https://pypi.org/pypi/synapse-cdm/1.2.0/json` **and** recomputed over the downloaded bytes rather
than trusted from the API.

```
3d3810f2c54b2c66458e4f0a1fa006ba2dafea97a0e2bff5e4feca293b74227c  synapse_cdm-1.2.0-py3-none-any.whl
30a7960d9e19017b56ba6e492ccb9806fdce9a43b96c4292dc45706f667af43a  synapse_cdm-1.2.0.tar.gz
```

**All three readings agree, and the sizes agree with them** — 3 738 692 bytes for the wheel and
1 920 469 for the sdist, identical in the gate's own `ls -l`, in PyPI's metadata, and in the files
downloaded from the index. The handover between the two jobs is separately hashed and separately
equal: the gate uploaded artefact `b614be97034d96c1b387d4dc6a8ee3b7d10a85aef335460191bf070d0d9c188d`
and the publish job recorded the same digest on download. The attestations name the same two
SHA-256 values in their in-toto subjects. That is the `--export-dist` chain closed for a third
release: one build, gated as that build, uploaded as those bytes, served as those bytes.

**The `v1.2.0` push carried fifteen commits to the remote at once, and it was their first time
there.** The last recorded push to `main` left it at `d2c1eb9`, and `d2c1eb9..8a382b1` is exactly
the fifteen commits of the KLV arc — the profile pin, the four park closures, the two guard rounds
and the release commit. So the whole arc reached the remote in the same push that triggered the
publish, and the gate saw all fifteen for the first time on the run that shipped them. Nothing was
wrong with that and it is recorded because it is unusual: the failure mode it invites is a review
surface fifteen commits deep arriving at the moment of least appetite for reading it, and the gate
is the only thing that read them.

**Two independent logs, both incomplete, agree — so this is corroborated rather than proved.** The
sentence above says "the last RECORDED push" and it keeps saying that, because neither source is a
guaranteed-complete history of the remote. GitHub's events feed is capped and lossy. `git reflog
show origin/main` is a record of what this clone observed, so a push from anywhere else would be
invisible to it. What raises the confidence is that they are wrong in different ways and still
agree on the same two facts: the last observed state before the arc is `d2c1eb9`, and the next
observed state is `8a382b1`, adjacent, with none of the fourteen intervening commits ever appearing
as a remote state in either. **They also agree on the clock**, which is the part neither was
constructed to do — the feed puts the `d2c1eb9` push at `08:18:40Z` and the reflog at `08:18:39Z`,
one second apart, and the reflog puts the arc's push at `23:27:59Z`, two seconds before the publish
run this entry cites was triggered at `23:28:01Z`. A third source would still be better; what would
settle it is a log neither of these is a copy of, and neither this repository nor a stranger can
reach one.

**A KNOWN DEFECT IN THE PUBLISHED ARTEFACTS, recorded rather than re-released.** The adapter count
disagreed with itself at seven sites in the tree, and four of those sentences were **inside** the
files on the index:

| Artefact | File | What it says |
| --- | --- | --- |
| wheel **and** sdist | `synapse_cdm/MIGRATIONS.md` | release condition 2, reading `All twelve harnesses are green` |
| wheel **and** sdist | `synapse_cdm/adapter.py` | the `fixture_dir` note, reading `eleven of the twelve shipped adapters — stanag4676 … is the only one` |
| sdist only | `pyproject.toml` | twice: `twelve adapters shipped and harness-verified`, and the SHIPS list's `the harness, twelve adapters` |

**The long description is not among them, and neither is the root `README.md`.** `pyproject.toml`
points `readme` at `synapse_cdm/README.md`, whose count was repaired in the 1.2.0 round itself, so
the page a stranger reads on PyPI says thirteen. The root `README.md` — where the disjunction was
found, saying thirteen in its intro and twelve under Using it — is packaged in neither artefact.
This was determined by reading the downloaded `.whl` and `.tar.gz`, not by reasoning about what
`pyproject.toml` includes.

**Why this is not a reason to re-release.** All four are prose, in two Python comments and one
packaged document; nothing executable reads any of them, no model, schema, adapter, fixture or
version constant is affected, and every functional claim above was verified against these exact
bytes. A filename on PyPI can never be reused, so correcting them means a new version number for a
comment — and `SCHEMA_VERSION` and `PACKAGE_VERSION` both staying put is the thing 1.2.0 exists to
demonstrate. They are repaired in the tree, recorded here against the artefact that carries them,
and they will ship corrected in whatever release comes next. The correction is in `MIGRATIONS.md`'s
Unreleased section, which is where a reader who installed 1.2.0 is told what their copy does not
have.

**And the guard that should have caught them is now a different kind of guard.** The one this
missed with was an allowlist built out of repairs — every row a place a count had once gone
wrong — so it had exactly the coverage its own history bought it, and seven sites sat outside it
at HEAD through a round whose subject was that count. `tests/test_cdm_prose_counts.py` now derives
the roster once and sweeps `git ls-files`, ruling every site it collects by comparison. Its
recorded debt since 1.1.0 was that a discovery sweep "is not written"; it is written.

#### Step C — done. The token is revoked, not merely unused

**Revoked on 2026-08-26**, at `pypi.org` → Account settings → API tokens, by the maintainer, after
1.1.0 had already published without it. OIDC is now the only way to upload to this project.

The order mattered and is worth recording as the reason this step waited: a token revoked while it
is still the only working path is a release nobody can cut. So the sequence was register the
publisher, publish once through it, and only then revoke — each step leaving a working path behind
it. The reverse order would have been a self-inflicted outage with no way back except issuing
another token, which is the thing being retired.

**Revoked and not merely unused, which was the whole point.** An unused token is a credential that
still works: no expiry, held by whoever holds it, with no record of where it has been copied. "We
do not use it any more" is a statement about intent; revocation is a statement about capability, and
only the second one survives the laptop it was pasted into. Entry 5 could not observe whether that
token was project-scoped and neither could this entry — which was an argument for removing it rather
than reasoning about its blast radius, and is now moot.

**What is verifiable, and by whom.** Nothing in this tree can see a revoked token, and neither can
a stranger: PyPI does not publish account token state. This rests on the maintainer's word, as step
A did before an upload proved it. What a stranger CAN check is the half that matters more — that
1.0.0 and 1.1.0 are both on the index, that 1.1.0's digests match a public Actions run, and that
the workflow which produced it contains no credential. The claim being made here is narrower than
"this project cannot be uploaded to by anyone else"; it is that the one long-lived credential this
repository knows about has been withdrawn.

**CLOSED 2026-08-26.** All three steps are done: the publisher is registered, a tag has published
through the workflow, and the token is revoked. What this entry set out to change is changed — the
next release needs a tag and a reviewer, and no credential at all.

**What closing this does not close.** The failure path has still never run. A refused upload — a
publisher that stops matching, a renamed workflow file, an environment renamed on one side only —
has not been observed, because the configuration was correct the first time, so the recovery
procedure is written down and unexercised. If an upload is ever refused, the fix is the four values
on this page; there is no longer a token to fall back to, and that is the intended state rather than
a gap. `.github/workflows/publish.yml`'s header carries the same warning at the point somebody
would be tempted.

## The deployment was not affected

The documentation site is deployed by explicit upload and **the Pages project has no Git
integration**, so the flip changed nothing about it: `wrangler pages project list` still reports
none for `synapsecommand-docs`, and no integration appeared as a side effect of the repository
becoming public.

The mechanism itself is stated in [`docs/README.md`](docs/README.md) and in `wrangler.toml`, and
`tests/test_cdm_deploy_workflow.py` requires those two to agree. **This file deliberately does not
restate it** — that gate's closure sweep treats any file describing the mechanism as a site it must
check, and a third site would be a third thing to keep in agreement for no gain. What is recorded
here is the post-flip *measurement*: the live site at <https://docs.synapsecommand.com> returns
HTTP 200 and is **byte-identical**, across five pages, to deployment `e08d2ea7` — whose recorded
source commit is `e116148`, the tip of `main` at the flip — and **differs** from the deployment
before it. The second half of that is the part that makes it a measurement rather than a
tautology: identical to the current deployment and different from the previous one is the only pair
of facts that distinguishes "serving the last deployed state" from "serving something".

## What is gated and what is witnessed

Three kinds of claim appear above and they are not equally strong. Reading them as equal is the
mistake this section exists to prevent.

| Kind | Example | How it can go stale |
| --- | --- | --- |
| **Gated** | the three unsigned commits; the two files agreeing about the required status | it cannot — a test fails |
| **Witnessed** | the force-push refusal; the DCO check failing then passing; the byte-identical pages | someone changes the setting afterwards and nothing notices |
| **Recorded from the API** | the `deletion` rule; the ruleset version history; the app install time | same, and it was never observed in action |

The suite cannot reach GitHub or Cloudflare, and it must not want to: a test that needs
credentials is a test that fails for every outsider and turns green only for whoever holds the
token. Re-witnessing is therefore a **protocol act**, like the stale-count sweep — the probes in
this file are written out in full so that re-running them is copying, not designing.
