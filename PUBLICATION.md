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

**Both halves re-read 2026-09-03, 10:28:40Z and 10:31:06Z, and both hold.**
`GET /repos/Decent-Cybersecurity/synapsecommand-public` **with no credentials** returns HTTP 200
with `"private": false` and `"visibility": "public"`. An anonymous `git clone` over HTTPS succeeds
and its `HEAD` matches the pushed tip of `main` — `e48f3ee` on both sides at that second reading.
Both were run from a clean environment with the
credential helper disabled, because a probe that quietly authenticates proves nothing about what a
stranger can see.

**THE DATES ARE THE REPAIR AND THE PROBE NAMES WERE NEVER THE PROBLEM.** This entry stated both
readings in the present tense with no instant on either, in the section that opens by promising
each entry names its probe — it named them, and said nothing about when either was run. Found by
the sweep rule 12 owes, and repaired by re-reading rather than by attaching a date to a recollection:
a date on an inherited reading is a second claim nobody checked.

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

Thirteen entries, and the set does not move — entries change **state**, they are not deleted. Ten
are **settled**: entry 1 is a ruling, entries 5, 6, 10, 11, 12 and 13 are closed by acts, entry 7 is
a disposition, entry 8 is a reconciliation, and entry 9 is a correction. Entry 5 records the 1.0.0 upload a human performed, what was measured
off the index afterwards, and which step of its own sequence was skipped. Entry 6 is the one that
retired the way entry 5 worked: it was written open, before the configuration it specified existed,
and it closed in three acts — a trusted publisher registered on PyPI, 1.1.0 published through the
workflow over OIDC, and the 1.0.0 API token revoked. Reading the two in order is the whole story of
how publishing this package stopped needing a credential. Entry 7 records a defect in the history
that is being left in the history, on entry 2's precedent, and mechanized so there is not a second.
Entry 8 is the one this file's own structure argued for and did not have: a record of what has been
served, read back against what the file says. Entry 9 is the tense sweep's finding about this file:
two claims that were never true, in a document whose subject is claims that stop being true. Entry
10 is the 1.2.1 release, and it is the third entry closed by an act rather than by a ruling: the
release that renumbered itself from 1.3.0 on the evidence of its own diff, and the one that
discharges entry 6's promise that the four prose defects in the 1.2.0 artefacts would ship
corrected. Entry 11 is the 1.3.0 release, the fourth closed by an act: the release a maintainer
refused on 2026-08-28 and an operator reversed on 2026-08-29, re-derived forward rather than
restored, and the first whose number a machine ruled **before** it was typed rather than after.
Entry 12 is the 1.4.0 release, the fifth closed by an act, and the first written days after the act
rather than beside it: the release the `pypi` environment held for six and a half hours, and the
one whose close-out found that the readings taken during that hold were **true when taken** and had
merely been carried across three days without their dates. Entry 13 is the 1.4.1 release, the sixth
closed by an act and the first whose upload reading found **nothing** that differed from the
previous one's pattern — six agreeing digests, agreeing sizes, the provenance trap unchanged at its
fourth reading — so its subject is what the round found while looking elsewhere: the documentation
site has served 1.2.1's changelog across three releases, which is the no-Git-integration claim below
confirmed and its consequence measured for the first time. Entries 2, 3 and 4 are open. None blocks
anything.

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
  unsigned web-UI commits. **Every other commit in the history** is authored by
  `m@decentcybersecurity.eu`, which
  is not associated with a GitHub account, so `commit.author.login` is `null` and Insights →
  Contributors shows the repository as very nearly unwritten. The address is real and reachable,
  which is what `CONTRIBUTING.md` requires of a sign-off, and the DCO check accepts it — GitHub's
  attribution views are a separate system from the sign-off and are not evidence about it. Adding
  the address to the account would populate them. Nothing here is broken; it is simply a surprising
  thing for a first visitor to see, and it is the sort of surprise that gets misread as "nobody
  works on this".
- ~~No commit in the history is GPG/SSH-signed (`verification.verified` is `false` throughout).~~
  **Never true — see ledger entry 9.** Measured 2026-08-27 over the whole history: **exactly two
  commits are `verified: true` with `reason: valid`**, and the set is `d7986017` and `2a51871f` —
  *the same two the
  entry above names as carrying no sign-off*, because the web UI signs what it commits with
  GitHub's own key and offers no sign-off checkbox. Struck rather than rewritten, because it was
  false when it was written and a "true as of" date on it would be a second false statement about
  the first. Sign-off and cryptographic signing are different claims and only the first is required
  here — that sentence stands, and being right is why the count beside it went unchecked.
- **Dependency graph:** not enabled — the SBOM endpoint returns 404. **Secret scanning:** disabled.
  **Dependabot security updates:** disabled. All three are available to a public repository and all
  three are off; none is asserted anywhere to be on. **Re-read 2026-09-03 at 10:28:43Z and
  unchanged**, the SBOM endpoint answering 404 and the API reporting `disabled` for secret scanning,
  its push protection and Dependabot alike. The date is here because it was not: this bullet sat
  between two neighbours that each carry their measurement date and carried none of its own, which
  is the shape rule 12's sweep was looking for.
- ~~**Code search** returns `total_count: 0` for terms that certainly occur in the tree: GitHub has
  not indexed the repository yet.~~ **Indexed — measured 2026-08-27**: `synapse_cdm` returns 103
  results, and `AnchorNotUnique`, a name this repository did not contain until 2026-08-26, returns
  2. The bullet forecast this in its own words — "expected shortly after a flip" — so it is struck
  and dated rather than deleted: the zero was real, and the reason to keep the sentence is that a
  reader who sees a zero here *again* should read it as an absence after all.
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
are in `MIGRATIONS.md`'s history, so the tree ships fourteen adapters and the
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

**Where this stood when this section was written — superseded four paragraphs below, and see
ledger entry 9.** Two of the three closing conditions were met at the time of writing. Step C was
done on **2026-08-26** and this entry is CLOSED; the table is kept in its as-written state, on the
precedent the two struck bullets above it set, because the entry was written forwards and the state
it was written in is what makes it readable. **What it lacked is this sentence.** An undated
snapshot reading `NOT DONE` four paragraphs above a heading reading "Step C — done" is a
contradiction a reader resolves by guessing which half is current, and the mechanism for marking
supersession already existed in this entry and was simply not applied to a table.

| Step | State | Who can verify it |
| --- | --- | --- |
| A — trusted publisher registered on pypi.org | **done** | not readable from the index, but proven indirectly: an OIDC upload succeeded and no token was used |
| B — the `pypi` environment with reviewers | **done** 2026-08-26T06:46:16Z | anyone; it is public API on a public repository |
| — a tag published through the workflow | **done** | run 32944124955, digests above |
| C — the 1.0.0 API token revoked | ~~**NOT DONE**~~ **done 2026-08-26** — as-written value struck, see below | only the maintainer |

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

### 7. A malformed trailer block: one commit, recorded and left in place

`c4a1071f`'s message ends with **two** lines git parses as `Signed-off-by` trailers:

| Trailer, as git parses it | What it is |
| --- | --- |
| `Signed-off-by: nothing else changed; the suite is unmoved at 3151 passed, 2 skipped.` | a sentence of prose that acquired a trailer key |
| `Signed-off-by: Matej Michalko <m@decentcybersecurity.eu>` | the real sign-off |

Both sit in the message's last paragraph, and git's rule for trailers is positional — the last
paragraph is the trailer block — so both are trailers to `git log`, to `%(trailers:…)`, and to the
DCO app. The author was reaching for the `Suite:` summary line the previous commit used and typed a
sign-off instead.

**Nothing in this repository could have noticed, and that is the entry.** Entry 2's gate reads
sign-offs through `%(trailers:key=Signed-off-by,valueonly)`, finds a non-empty value, and calls the
commit signed. It **is** signed, by the second line. The DCO app agrees for the same reason. Every
check here asked *is there a sign-off?* and none asked *does the trailer block say what it appears
to say* — so a false statement about provenance passed a gate designed to catch exactly that, by
standing next to a true one.

**Disposition: left in place, on entry 2's precedent.** No history rewrite is contemplated. Entry 2
declines to rewrite three unsigned commits because doing so would falsify the record of how this
repository was actually built, and the same argument governs a fourth: amending `c4a1071f` would
erase the only instance of a defect this file now describes, and the description would then rest on
nothing. `main-protection`'s **`non_fast_forward`** rule stands and is not being relaxed for this —
the amend-and-force-push path is the one the ruleset refuses, as witnessed above, and no exception
is being sought.

**Mechanized rather than remembered.** `gates/commit_message.py` refuses a message whose trailer
block carries a line that is not the trailer it appears to be, and refuses a certifying trailer
stranded in the body — the mirror-image failure, where a commit reads as signed to a human and is
unsigned to git. `tests/test_cdm_commit_message.py` holds it to both directions on synthetic
messages, replays the incident out of git, and recomputes the offending set from the actual history
and requires it to equal the one commit named above. A second malformed message fails the build.

**One thing the mechanization found that the incident did not.** The trailer vocabulary was
derived from git's parse of all 95 messages rather than decided, and it is `Signed-off-by` (93),
`Co-Authored-By` (51) and **`Suite` (1)** — a one-line result summary, used once, declared nowhere.
It is a legitimate trailer and it is now declared; an undeclared key used once is how the next one
gets in by typo, which is what happened here.

### 8. The deployment record, reconciled — and it starts existing here

**The defect was an absence.** This file named exactly one deployment, `e08d2ea7`, and named it
inside a measurement rather than as a record. Nothing in the tree recorded a deploy as an act. The
project's list was therefore the only account of what had been served, and it was never read back
against what this file said — so a claim in the present tense outlived the state it described by
two days and two deployments.

**The list, measured 2026-08-27.** Sixteen deployments, every one `ad_hoc` — an explicit upload,
which is what the mechanism `docs/README.md` states predicts, and no other trigger type appears.
Every recorded source commit resolves in this repository's history; none is from anywhere else.

| Deployment | UTC | Source | Recorded, before this round |
| --- | --- | --- | --- |
| `222a55be` | 2026-08-27 12:37:06 | `43213316` | **did not exist** — deployed by the 1.2.1 release; ledger entry 10 |
| `5ed34cd8` | 2026-08-27 01:01:32 | `c4a1071f` | **this entry** |
| `57ac1878` | 2026-08-25 14:35:07 | `01fb685f` | no |
| `919b58db` | 2026-08-25 10:42:03 | `30fa0454` | no |
| `e08d2ea7` | 2026-08-25 09:12:28 | `e1161489` | yes — the measurement above, and `f916ba2` |
| `e4a1c33d` | 2026-08-25 07:00:13 | `26c7f3f3` | yes — commit messages `4732429` and `7e641e6` |
| the eleven named below | 2026-08-22 → 2026-08-25 | all resolve | no |

**Two of sixteen had ever been written down**, and both of those in passing. The other fourteen
happened and left no trace outside Cloudflare's own list.

**Amended 2026-08-28 by the ruled round, and the three figures above stand as dated claims.** They
were **true when written** by commit `7544880`, whose table carried five rows above the eleven named
below them, and whose second sentence balanced its pair over that same set. What falsified them is this
repository's own later act rather than any error in the reading: commit `1fc35e8` appended the
`222a55be` row when the 1.2.1 release deployed at `12:37:06Z`, and **the enumeration grew while the
prose count did not**. The list this entry accounts for is **seventeen deployments — six carrying a
row and eleven covered by the naming paragraph below**, derived at writing time from
[`gates/deploy_record.py`](gates/deploy_record.py)'s own reconciliation rather than counted by hand.
**Only the total is restated, and the split it is restated by is the gate's.** The second sentence's
pair is a claim about what earlier rounds had written down, which no tool here derives; restating it
would put a fourth figure in this entry that nothing could keep, which is the failure being amended.
So it is dated and left, and what replaces it is a decomposition a command recomputes.

**The gate was green on every one of those runs, and correctly so.** Its predicate is that no
deployment Cloudflare lists is unaccounted for, and none ever was — the appended row is what kept
it true. A spelled number in a sentence is not a deployment, so the check could not see the
sentence drift away from the table directly above it. **This is the predicate-weaker-than-the-prose
gap, and it landed inside the entry whose subject is that gap** — under a ruling, four paragraphs
above, that a protocol act nobody can fail decays at the speed of somebody's attention, and by
exactly that mechanism: the round that appended the row was the round that would have had to keep
the paragraph, and nothing asked it to.
`tests/test_cdm_deploy_record.py::test_the_entry_states_the_deployment_count_its_own_enumeration_derives`
closes it, and this amendment is the first commit it ruled.

**The eleven earlier deployments, named rather than dated.** `ccfa7476`, `c9494c05`, `bbfad083`,
`fc7bc5db`, `1ba36baf`, `090a5edb`, `10d0dc94`, `33e0e1ba`, `323dff1f`, `7489e528` and `039866b1`.
That row used to read `eleven earlier | 2026-08-22 → 2026-08-25`, and a date range **cannot be
wrong about an id it never mentions** — so it could not be checked, and a sixteenth deployment
arriving inside the range would have been covered by it silently.
[`gates/deploy_record.py`](gates/deploy_record.py) can refuse a deployment this file cannot name
only because this paragraph names them.

**The range was also wrong in its own terms, which is what an enumeration exposes and a heuristic
hides.** `ccfa7476` went up at `07:01:45` — ninety-two seconds *after* the `e4a1c33d` row above it
— so one of the eleven "earlier" deployments was never earlier than the row that was covering it.
Nothing rested on the ordering; it is recorded because the phrase was doing work it could not do.

**The alias, and which deployment serves it.** `docs.synapsecommand.com` is served by deployment
`222a55be`. Witnessed **2026-08-27** by bytes and not read off a settings field: five pages fetched
from the domain are byte-identical to `222a55be`'s own `pages.dev` URL and **differ** from
`5ed34cd8`'s on all five. **The pin moved in the same commit as the deploy**, which is what this
paragraph is for; it named `5ed34cd8` until the 1.2.1 release superseded it at `12:37:06Z`, and the
superseded reading is ledger entry 8's table rather than a struck sentence here, because the id is
the claim and a paragraph carrying two of them is a paragraph a parser has to guess at. Identical to one deployment and different from the one before it is the
pair that distinguishes "serving what was deployed" from "serving something", which is the shape
every deploy measurement in this file has used. The reason it is bytes rather than the `aliases`
field the API also offers: that field says which deployment is *configured* to hold the domain, and
what this file claims is the stronger thing a stranger experiences. `gates/deploy_record.py` re-runs
exactly this probe and fails if the id in this paragraph is not the one the bytes give.

**The unrecorded deploy the live bytes implied, identified.** `57ac1878` served the site from
2026-08-25 until this round. Its recorded source is `01fb685`, which touched no rendered page; the
last commit before it that did is `1a62104`, and the served bytes carried three strings introduced
there — including the changelog admonition separating the package version from `schema_version` —
and none introduced after it. The diff from `1a62104` to `c4a1071` over `docs/` is **5 files, 71
insertions, 22 deletions**, which is the figure the staleness round measured before any of this was
read off the API: the fingerprint and the deployment list were derived independently and agree.

**Disposition of `919b58db` and `57ac1878`: recorded retrospectively, and nothing else.** Neither
was wrong. Both followed the documented order — a commit that changed a rendered page, then a
deploy of the build made from it — and `57ac1878` is the successful half of the sequence whose
first attempt `01fb685`'s message describes failing. What was missing was the writing-down. There
is nothing to roll back and no redeploy is owed; the correction is that the measurement above is
now dated and that this table exists.

**The deploy the round that wrote this entry performed.** `5ed34cd8`, source commit `c4a1071f`, uploaded
2026-08-27 01:01:32Z after `npm --prefix docs run ci` reported all three gates green — 9 generated
files current, 15 directives rendered across 16 pages. The stamp is honest despite an uncommitted
tree: this round changes no file under `docs/`, so the rendered pages uploaded are exactly
`c4a1071f`'s, which is the property the commit-then-deploy order exists to protect.

**Verified from the served bytes, both halves, as the flip measurement was.** Fetched from
<https://docs.synapsecommand.com> after the upload: five pages **byte-identical** to the local
build, and **differing** from `57ac1878` on all five — identical to the current deployment and
different from the previous one, which is the pair that distinguishes "serving what was deployed"
from "serving something". The intro serves thirteen adapters with STANAG 4609 named and the pair
arithmetic reading seventy-eight and thirteen; the "landing next" sentence naming adapters that
shipped in 1.1.0 is gone; the changelog and entity pages match the build; the tutorial carries the
`fixture_dir` material — `--fixtures` optional for a shipped adapter, refused for a
`module:ClassName` one. The seven schema-reference pages differ from `57ac1878` only in their asset
hashes: the generated pages themselves are unchanged, which is what a release that moved
`PACKAGE_VERSION` and not `schema_version` should look like on a rendered site.

**What this entry changes going forward.** A deploy gets a row in this table, with its id and its
source commit, in the commit that follows it. **This paragraph used to end "that is a protocol act
and not a gate", and the round after it made that false:**
[`gates/deploy_record.py`](gates/deploy_record.py) reconciles this table against Cloudflare's list
in both directions and refuses an unrecorded deployment, which is exactly the missing row the old
wording said nothing could fail on. What stays true is the narrower claim the old sentence was
reaching for: the gate is **not a suite member**, because the suite cannot reach Cloudflare and must
not want to, so a missing row fails a command somebody runs rather than a build. Corrected by the
1.2.1 release audit, which found it while writing the row above — the sentence had been superseded
for two rounds by a tool this same entry already cites twice.

### 9. Two claims that were never true, found by the tense sweep

**This is a different defect from the one entry 8 records, and the difference is the entry.** Entry
8 is about **decay**: a claim that was true when written and was overtaken by an event nobody wrote
down. Neither claim below ever had a moment of being true. **Dating them would be worse than
leaving them** — a "true as of" stamp on a sentence that was false when it was typed is a second
false statement about the first — so both are struck and measured rather than dated.

They were found by this round's sweep of every present-tense witnessed claim in this file, which is
published in full under "What is gated and what is witnessed" below. **The sweep was written to
find decay and found these instead**, which is the finding about the sweep and the reason the
collection is shown rather than summarised: a sweep whose results are reported as a count is a
sweep whose misses are invisible.

**Claim 1 — "No commit in the history is GPG/SSH-signed."** Entry 4 asserted it with a parenthesis
reading "`verification.verified` is `false` throughout". Measured 2026-08-27 over the whole
history: **exactly two commits are `verified: true` with `reason: valid`**, PGP-signed, and the set
is `d7986017` and `2a51871f`.

**Stated as a set of two named commits and not as a ratio, on entry 2's rule.** The first draft of
this entry wrote "two of 96 commits", which is a number that moves on the next commit — the exact
shape entry 2 rejected when it replaced "44 of 47 are signed" with a named set. It was caught by
this round's own stale-count sweep, at two sites, in the entry repairing a claim that had gone
unchecked for the same kind of reason. The set is closed unless somebody commits through the web UI
again.

**Those are the same two commits entry 2 names as carrying no sign-off, and the coincidence is the
mechanism.** Both were made in the GitHub web UI. The web UI commits on the author's behalf and
signs the result with GitHub's own key, and it offers no sign-off checkbox — so the single fact that
makes those two commits unsigned in the DCO sense is what makes them the only two signed in the
cryptographic sense. The two senses of "signed" that this repository is careful to keep apart turn
out to be exactly anti-correlated across its history, and neither entry noticed because each was
looking at one of them.

**Corrected 2026-08-28 by the ruled round: the relation word in the sentence above is too strong,
and what refutes it is named in this same file, in the entry that sentence cites.** The two senses
are **disjoint** — no commit in this history is both signed off and cryptographically signed, and
that empty cell is real and is the part worth keeping. Disjoint is not complementary. `965e939d` is
signed in **neither** sense: it carries no `Signed-off-by` trailer, and GitHub reports it
`verified: false` with `reason: unsigned`. It is the fourth cell, the one the sentence above claims
is empty. Entry 2 has named it since it was written, under a heading that says three commits carry
no sign-off and in a table of three rows — **so the sentence cites entry 2 for a set of two, and
entry 2 states a set of three.** No round noticed, this file's own sweep of present-tense claims
included, because the error is not a stale figure and not an unwitnessed assertion: it is a
correctly measured pair of sets joined by a word that claims more about them than either measurement
supports. Nothing that checks claims one at a time can see it.

**The mechanism this paragraph exists to state survives intact, and it is the half the entry needed.**
Re-derived 2026-08-28 from the platform rather than recalled: `d7986017` and `2a51871f` are the only
commits GitHub reports `verified: true` with `reason: valid`, and both carry `committer: GitHub` —
they are the two web-UI commits, and the single fact that they were authored through the web UI is
still exactly what makes them unsigned in the DCO sense and signed in the cryptographic one.
`965e939d` carries a human committer; it is an ordinary local commit from before the sign-off
discipline was installed, which puts it **outside the mechanism's scope rather than against it**.
So Claim 1's repair stands, entry 2's set stands, entry 4's struck bullet stands, and what is
withdrawn is only the stronger claim that the two senses partition the history between them.

**Named and not counted, which is the rule this entry invokes four paragraphs above its own error.**
The occupied cells are a set of two, a set of one, and every other commit — and stating that last
one as a number would be the ratio entry 2 rejected, moving on the very commit that recorded this
correction.

**It was never true and it was never decidable from inside the tree either.** The claim was written
after the flip, about a history that already contained those two commits; nothing changed
underneath it. The sentence beside it — "Sign-off and cryptographic signing are different claims and
only the first is required here" — is correct, and **being correct is why the count next to it went
unread**: a reader who accepts the distinction has no reason to check the number, and the number was
the half that was wrong.

**Claim 2 — entry 6's "Where this stands" table says step C is `NOT DONE`.** Revoking the 1.0.0 API
token was done on 2026-08-26. The table sits four paragraphs above a heading reading "Step C —
done", inside an entry whose own title says CLOSED and two of whose bullets are struck through
*precisely* to mark this kind of supersession. The tool for saying "this was true when written"
existed in that entry, in that entry's own prose, and was not applied to a table.

**Why one entry rather than two corrections.** Neither is reachable by any check this repository can
run — one is a claim about GitHub's API the suite must not hold a token for, the other an internal
contradiction between a table and a heading in one file. What they share is the thing worth a ledger
number: **both are undated present-tense assertions in the file whose own table predicts that exact
failure mode**, and both survived every round since they were written, including two rounds whose
declared subject was claim decay. The repair is therefore the dating discipline applied to the whole
collection below, not two repaired sentences.

**Disposition: corrected in place, with the wrong version preserved at both sites.** Entry 4's
bullet is struck and the measurement written beside it; entry 6's table keeps its as-written value
struck rather than replaced. Nothing is deleted, on entry 5's ruling: a closed record that quietly
updates its own history is a record nobody can date.

**What this entry does not claim.** Not that the collection below is complete. It is a floor — the
sweep is an enumeration over nine record files and a human read of what it collected, and a claim
phrased so as to mention none of the platforms it depends on is a claim it cannot see. The two
found here were both inside its reach; what it cannot bound is how many are outside it.

### 10. `synapse-cdm` 1.2.1 is on the index — CLOSED, and the release renumbered itself

**Published 2026-08-27** by
[run 33061413447](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/33061413447),
triggered by the `v1.2.1` tag. Both jobs succeeded; the upload took 24 seconds once the `pypi`
environment was approved. This entry is the release's own record, written in the commit that
follows the tag, and it closes on the evidence below rather than on the run being green.

**THE NUMBER WAS RULED FROM THE DIFF, AND IT IS NOT THE ONE THE ROUND WAS ASKED FOR.** The release
was specified as **1.3.0**. Not one executable line had changed inside the distribution since
`v1.2.0`: `pyproject.toml` and `adapter.py` changed comment lines only — filtering both diffs to
functional lines yields nothing — and every other file that moved under `packages/` is a shipped
document. No importable name, no `Adapter` contract change, no harness flag or exit code, no fixture
set, no dependency. That is `version.py`'s MINOR list in full and none of it occurred, so the PATCH
row governs and the release is **1.2.1**. Recorded here because a version number is the one claim in
a release that can never be corrected: a PyPI filename is permanent, and 1.3.0 would have been a
distribution asserting a surface change that had not happened.

**`SCHEMA_VERSION` stayed 1.0.0 on evidence rather than on inheritance.** The diff over `schemas/`
since `v1.2.0` is empty and no model, adapter or fixture changed. Unlike 1.2.0's, this required no
ruling — there was no new output surface to adjudicate.

**Installed from the index, not from the local build.** A fresh virtualenv with no clone on its
path, `pip install synapse-cdm==1.2.1 --no-cache-dir`. Read back from `site-packages`:

| | |
| --- | --- |
| `PACKAGE_VERSION` | `1.2.1`, and `Version:` in the installed `METADATA` agrees |
| `SCHEMA_VERSION` | `1.0.0` — unmoved, and this time uncontested |
| `--list-adapters` | **13 adapters**, unchanged from 1.2.0, `stanag4609` at `1.0.0` with fixtures in `klv` |
| harness | the whole roster against the installed copy, no `--fixtures`: **408 verdicts, 0 failed** |

**The first install attempt failed, and it is the propagation lag rather than a defect.** `pip`
answered `Could not find a version that satisfies the requirement synapse-cdm==1.2.1 (from
versions: 1.0.0, 1.1.0, 1.2.0)` while `GET /pypi/synapse-cdm/1.2.1/json` was already answering
**200**. The per-release JSON endpoint, the aggregate JSON endpoint and the simple index update
independently, and `pip` resolves against the last of the three. Retried once and it resolved. The
1.2.0 round met the same lag from the other direction and this is the second observation of it, so
it is recorded as the expected behaviour of the index rather than as an incident.

**The digests, in four readings.** What the gate hashed after building and gating, what the publish
job hashed immediately before uploading, what the index states in its metadata, and what a
recomputation over the downloaded bytes yields:

```
f07f32e057a6e387f12b7c9565a26895873d763469ac0386dc28522c6a1e7e2b  synapse_cdm-1.2.1-py3-none-any.whl
71c06af009a2fb03e2911f8fe18a8d46a4800ad277946888c6c4debff8b47e7f  synapse_cdm-1.2.1.tar.gz
```

**All four readings agree, and the sizes agree with them** — 3 762 311 bytes for the wheel and
1 946 985 for the sdist, identical in the gate's `ls -l`, in the publish job's pre-upload hash, in
PyPI's metadata, and in the files downloaded from the index. The simple index's own `sha256`
fragments carry the same two values, which is a fifth reading nobody asked for. The attestations
name the same digests in their in-toto subjects. The gate handed over artefact
`4c3a9091352c9bf63adb0d84730c85556bed258e5002d714307557f9c58bde05` and the publish job downloaded
that digest. One build, gated as that build, uploaded as those bytes, served as those bytes — for a
fourth release.

**A local build of the same tree was made first and its digests are deliberately NOT recorded.**
They differ from the published ones — `4aa4fd28…` and `e590ad57…` — and the sdist differed in size
as well, 1 953 838 against 1 946 985. That is the ordinary consequence of two builds of one tree
carrying different generated metadata, and it is the whole reason the notes point here instead of
stating a digest: the local build's numbers would have been a true measurement of a file nobody can
install.

**WHAT 1.2.1 IS FOR: the four sentences that shipped wrong inside 1.2.0 are corrected in it.**
Entry 6's block on 1.2.0 recorded them against the artefacts carrying them and said they "will ship
corrected in whatever release comes next". That is this release, and it was verified in the
installed copy rather than in the tree:

**The four are named in entry 6's table and are deliberately not restated here** — that table is
the record of what the 1.2.0 artefacts carry, and a second copy of four verbatim quotations is four
more sites to keep in agreement, which is the defect the round behind this release was about. What
belongs here is the verification, per file, read out of the downloaded 1.2.1 artefacts:

| Artefact | File | Verified in 1.2.1 |
| --- | --- | --- |
| wheel and sdist | `synapse_cdm/MIGRATIONS.md` | release condition 2 states the roster correctly |
| wheel and sdist | `synapse_cdm/adapter.py` | the `fixture_dir` note states the roster correctly, and its uniqueness clause is **gone** — the substring occurs 0 times |
| sdist only | `pyproject.toml` | both sites state the roster correctly |

Each was checked by reading the installed `site-packages` copy and the unpacked sdist, against the
roster the registry derives — not by re-reading the tree, which is what the 1.2.0 round could have
done and would have passed.

**TWO POINTERS IN ENTRY 6 NO LONGER RESOLVE, and they are corrected here rather than there.** Entry
6 is closed, and entry 5's ruling is that a closed record which quietly updates its own history is a
record nobody can date. Its 1.2.0 block sends a reader to `MIGRATIONS.md`'s `### Unreleased` section
"which is where a reader who installed 1.2.0 is told what their copy does not have"; that section
was absorbed into `### 1.2.1` when this release took it, which is what the release-condition test
requires it to do. And its "will ship corrected in whatever release comes next" is discharged by the
table above. Both measurements it accompanies are unchanged.

**The docs site was deployed, and the order was publish first.** Deployment `222a55be`, source commit
`43213316`, uploaded 2026-08-27 12:37:06Z after `npm --prefix docs run ci` reported all three gates
green — 9 generated files current, 15 directives rendered across 16 pages. The only rendered page
that moved is `changelog.mdx`, whose one live version claim read "the package is at `1.2.0`".
**The deploy was deliberately held until 1.2.1 was on the index**: serving a page that claims a
version the index does not have is the same bare-claim class this file spent two rounds
mechanizing against, and the page would have been false for as long as the approval took.

**Verified from the served bytes, both halves.** Five pages fetched from
<https://docs.synapsecommand.com> after the upload are **byte-identical** to the local build and to
`222a55be`'s own `pages.dev` URL, and **differ** from `5ed34cd8`'s on all five. The changelog page
serves `package is at 1.2.1` where `5ed34cd8` serves `1.2.0`, and the two deployments' bytes differ
at exactly one character — the two strings are the same length, so the file sizes are identical at
58 816 bytes and a size comparison would have shown nothing.

**A PROBE FORM THAT REPORTS THE OPPOSITE OF THE TRUTH, found by running it.** The first byte
comparison above was written with Python's `urllib` at its default `User-Agent` and reported the
domain as identical to **both** `222a55be` and `5ed34cd8` and different from the local build —
which is to say it reported that the deploy had changed nothing. Every one of its fifteen fetches
had returned **HTTP 403** from Cloudflare's bot challenge, and the comparison was hashing fifteen
identical error strings. **A uniformly failing probe makes "identical" true.** `curl` gets 200 from
the same URLs, and so does `urllib` with any `User-Agent` set — including
`synapsecommand-deploy-record`, which is the one
[`gates/deploy_record.py`](gates/deploy_record.py) sends, so the gate is unaffected and was checked
rather than assumed. The gate is also structurally immune: its `fetch()` raises on `HTTPError`
instead of returning a value, and its "must differ from the previous deployment" half would refuse
a uniform failure even if it did not. **This is the mirror of the `synapsecdm` 200 already recorded
below** — that one turns a 404 into an apparent 200, this one turns a difference into an apparent
identity — and it belongs to the same lesson: a written-down probe is only as good as the response
it distinguishes.

**What this entry does not claim.** That the release changed anything executable — it did not, and
the PATCH number says so. And not that the four corrected sentences were the only prose defects in
the 1.2.0 artefacts; they are the four the sweep that found them could see, and the sweep that
replaced it derives the roster and reads `git ls-files` rather than an allowlist.

### 11. `synapse-cdm` 1.3.0 is on the index — CLOSED, and it is the release a refusal did not stop

**Published 2026-08-29** by
[run 33247697980](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/33247697980),
triggered by the `v1.3.0` tag. The build job ran 10:23:08–10:26:10Z and the `pypi` environment then
held the upload for **twenty-one minutes** until a required reviewer approved it at **10:47:24Z**;
the publish job ran 10:47:27–10:47:50Z. This entry is the release's own record, written in the
commit that follows the tag, and it closes on the evidence below rather than on the run being green.

**THE RELEASE WAS REFUSED ONCE AND THE REFUSAL IS NOT DELETED.** 1.3.0 was derived, built and
verified on **2026-08-28**, and the maintainer refused it on a finding about the brief that ordered
it. The operator **reversed** that refusal on **2026-08-29** and this release is the reversal
carried out. Both rulings stand — the refusal as a dated reading, the reversal as the decision that
outranks it — and neither was rewritten out of the history: the refused attempt's bump, rolled
section and notes were unwound before it closed, and this release re-derived every one of them
forward from the tip rather than restoring them. **Nothing from the refused attempt is in these
artefacts**, which is a claim about method and is why the number was re-derived rather than
recalled.

**AND THE STEP THAT REFUSED IT DOES NOT EXIST, which is the finding worth carrying forward.** The
2026-08-28 brief conditioned the release on *"the release protocol's step C"* and a dated PyPI
token witness. `MIGRATIONS.md`'s procedure states **five numbered conditions and no lettered
steps**; the only lettered steps in this repository are **entry 6**'s one-time trusted-publishing
migration, whose step C is *retire the 1.0.0 API token*, recorded **done 2026-08-26**. The
token row in the witness table reads **UNDATABLE from held evidence** by construction, because PyPI
publishes no token state — so a release gate built on it could never open. The refusal was a
person's and not this repository's: no condition was unsatisfiable and no gate went red on the
release itself.

**THE NUMBER WAS DERIVED BY A MACHINE, AND THIS IS THE FIRST RELEASE WHERE THAT HAPPENED
PROSPECTIVELY.** Entry 10 records condition 5 being added after the release that needed it, and
`gates/bump_derivation.py` deriving retroactively the number every prior release actually shipped.
Here it ruled **before** the number was typed: the packaged diff between `v1.2.1` and the tree
classifies **MINOR** on thirteen public top-level names in `adapters/imapb_codec.py`, so the floor
was **1.3.0** and the release is 1.3.0. No unit came out ambiguous, so no human bump ruling was
written or needed. The contrast with entry 10 is the point — 1.2.1 was talked down from 1.3.0 by a
person reading a diff, and 1.3.0 was ruled up to by the gate reading one.

**`SCHEMA_VERSION` stayed 1.0.0 on evidence rather than on inheritance.** The diff over `schemas/`
since `v1.2.1` is empty, no model changed, and all six published schemas regenerate byte-identical
from the models — checked from outside the repository by the wheel gate. A new importable module is
a package MINOR and says nothing about the wire contract, which is the distinction `version.py`
argues and this release is a clean instance of.

**Installed from the index, not from the local build.** A fresh virtualenv with no clone on its
path, `pip install synapse-cdm==1.3.0 --no-cache-dir`. Read back from `site-packages`:

| | |
| --- | --- |
| `PACKAGE_VERSION` | `1.3.0`, and `Version:` in the installed `METADATA` agrees |
| `SCHEMA_VERSION` | `1.0.0` — unmoved, and uncontested |
| `--list-adapters` | **13 adapters**, unchanged from 1.2.1, `stanag4609` at `1.0.0` with fixtures in `klv` |
| harness | the whole roster against the installed copy, no `--fixtures`: **408 verdicts, 0 failed** |
| the new surface | `synapse_cdm.adapters.imapb_codec` imports from `site-packages` and reports **14** IMAPB items |

**No propagation lag this time, and that is worth one line only because entry 10 recorded one.**
`pip` resolved 1.3.0 on the first attempt. Entry 10 met `Could not find a version that satisfies`
while the per-release JSON endpoint already answered 200, and recorded it as the index's expected
behaviour rather than an incident. A second observation that does **not** reproduce is evidence
about the lag being a race and not a rule.

**The digests, in six readings.** What the gate hashed after building and gating, what the publish
job hashed immediately before uploading, what the in-toto attestation names as its subject, what
the simple index declares, what the legacy JSON metadata states, and what a recomputation over the
downloaded bytes yields:

```
5cb8e3fcab683c183b726e344023aaca58bfd878cf0ec2d14a896d4b19a9343a  synapse_cdm-1.3.0-py3-none-any.whl
55a1e9f296880dc6ff27b9692d9639d0b6de770b2faba236d9dd6b5630924fc5  synapse_cdm-1.3.0.tar.gz
```

**All six readings agree, and the sizes agree with them** — 3 960 762 bytes for the wheel and
2 126 808 for the sdist, identical in PyPI's metadata and in the files downloaded from the index.
The gate handed the publish job artefact
`d5eb88be20d70de478e77bca8e09d93da006b0fadef1a349c212f552805727c6` and the publish job downloaded
that digest before uploading. One build, gated as that build, uploaded as those bytes, served as
those bytes.

**A SIZE IS NOT AN IDENTITY, AND THIS RELEASE DEMONSTRATES IT INSTEAD OF ASSERTING IT.** This round
also built the same tree locally, to run `twine check --strict` before the tag. Its wheel is
**3 960 762 bytes — byte-for-byte the same size as the published one — and digests
`2a38b9bb428b48e8d1284f1f62f88f4c43409f4fdbd75c4b0b38c04b20818ee3`, a different file**. Its sdist
differs in size as well, at 2 135 120. So the two builds of one tree differ exactly as
`RELEASE_NOTES.md` has said since 1.1.0, and the wheel half of it is the sharper case: a size
comparison would have called them identical. This is why the served-versus-built check compares the
**workflow's** digests and never a local rebuild's.

**THE PyPI PROVENANCE TRAP, RE-CONFIRMED LIVE ON THIS RELEASE.** `GET /pypi/synapse-cdm/1.3.0/json`
reports `provenance: null` on **both** files while attestations demonstrably exist. The
attestations live on the **simple index**: request `https://pypi.org/simple/synapse-cdm/` with
`Accept: application/vnd.pypi.simple.v1+json`, read each file's `provenance` URL, fetch it. The
bundle's `publisher` block returns PyPI's own statement of the four trusted-publisher values —
`kind` GitHub, `repository` `Decent-Cybersecurity/synapsecommand-public`, `workflow` `publish.yml`,
`environment` `pypi` — and the in-toto subjects carry the two digests above. That is a **second
party** to the identity claim, from the index's side rather than the repository's.

**WHAT THE APPROVAL TIMESTAMP WITNESSES, AND WHAT IT DOES NOT.** The upload was accepted over OIDC
with no credential in `.github/workflows/publish.yml` and no `secrets.*` reference in it, at a
recorded time, after a named reviewer approved a named environment. That is a dated witness that
**the tokenless mechanism works** — the fourth such upload, after 1.1.0, 1.2.0 and 1.2.1. It is
**not** a witness about token state, and it does not supersede the UNDATABLE row: an upload proves
what it used and says nothing about what else would still be accepted. The distinction is the whole
of entry 9's lesson and is kept sharp here deliberately, because the 2026-08-28 brief's error was
to treat exactly these two claims as one.

**What this entry does not claim.** That park 5 is closed — it is not. The codec ships, and not one
of the ST 0601 rows that would consume it has moved: none of the fourteen is witnessed by any held
octet, the pinned stream's 26 items stop at tag 65, and all fourteen still read `not yet`. A
release that adds a capability nothing on a wire has exercised is what this is, and
`RELEASE_NOTES.md` says so in the release's own voice rather than leaving it here.

### 12. `synapse-cdm` 1.4.0 is on the index — CLOSED, and the reading that was called stale was true when it was taken

**Published 2026-08-30** by
[run 33307299409](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/33307299409),
triggered by the `v1.4.0` tag at `62acc12f`. The build job ran 10:46:53–10:49:23Z; the `pypi`
environment then held the upload for **six hours, twenty-nine minutes and twenty-eight seconds**
until a required reviewer approved it at **17:18:53Z**, and the publish job ran 17:18:55–17:19:18Z.
Deployment `6165823339` carries the sequence: `waiting` twice at 10:49:25Z, `queued` at 17:18:53Z,
`in_progress` at 17:18:56Z, `success` at 17:19:19Z. This entry is written **three days after** the
act it records, which is the fact that gave it its subject.

**THE HOLD WAS NOT A STALL, AND THE WATCHER THAT REPORTED IT WAS NOT WRONG.** The brief that
ordered this close-out said the previous round's `waiting` readings *"were stale"* and that a
monitor reporting a stale state as current is the same defect class as a quoted derivation gone
stale. **Read against the status rows, that is not what happened.** The previous round's last
`waiting` readings are dated **2026-08-30T17:16:27Z** — a watcher returning `TIMEOUT after 60m:
waiting` — and **17:16:36Z**, a direct read reporting `waiting … pending: pypi can_approve=true`.
Approval registered at **17:18:53Z**, **two minutes and seventeen seconds later**. Every one of
those readings described the run's actual state at the moment it was taken, and the same session
re-read the deployment at 17:20:26Z, saw `success`, and acted on it.

**So the defect class the brief named is not the one present here, and the distinction is worth
keeping.** A stale reading reports a state that had *already* changed when it was reported. These
reported a state that changed *afterwards* — which is not staleness but the ordinary condition of
every observation. What made them misleading was the three-day carry: restated on **2026-09-02**
without their timestamps, true readings about 17:16Z read as claims about now. **The remedy is the
one this file already applies to every other claim — a date attached at the point of reading, not a
better monitor.** An undated true reading and a stale one are indistinguishable to the next reader,
which is the whole of entry 9's lesson pointed at observations rather than at prose.

**THE RELEASE WAS ALREADY CREATED, AND NOT BY THE OPERATOR.** The same brief reserved the GitHub
Release for the operator and asked this round to hand over a body for them to post. The Release at
`v1.4.0` already exists — created 2026-08-30T10:45:15Z by the tag, **published 17:22:06Z**, not a
draft, and `Latest` — with the completed body on it, posted by the previous round four minutes
after the approval it describes. Nothing was re-posted here and the body was not edited. Recorded
because a reservation that was already spent is exactly the sort of thing a later reader would
otherwise take as still pending.

**The digests, in six readings, and all six were reachable.** What the gate hashed after building
and gating, what the publish job hashed immediately before uploading, what the in-toto attestation
names as its subject, what the simple index declares, what the legacy JSON metadata states, and
what a recomputation over the downloaded bytes yields:

```
006e5f0e8b8557d91c7cf90da1e5a6fd0341d8f398bab6617a1802e4ac1dd9f3  synapse_cdm-1.4.0-py3-none-any.whl
3f16e818d92af4a69721c248110eab16e9dbf8f75fd9bf9201981e09f97635e2  synapse_cdm-1.4.0.tar.gz
```

**All six agree, and the sizes agree with them** — 4 105 837 bytes for the wheel and 2 206 389 for
the sdist, identical in PyPI's metadata and in the files downloaded from the index on
**2026-09-02**. The gate handed the publish job artefact
`0d77928a148fcdcddf492bdccf29f1c6a6ee4a932bd26b3fd069ec025e5f63ae` at 10:49:21Z and the publish job
downloaded that same digest at 17:19:00Z, across the six-and-a-half-hour hold; the wheel was
accepted at 17:19:12.788614Z and the sdist at 17:19:14.909453Z. One build, gated as that build,
uploaded as those bytes, served as those bytes. **The comparison basis is the WORKFLOW's build and
never a local rebuild** — entry 11 demonstrated why with two same-size, different-digest wheels, and
that ruling is inherited here rather than re-argued.

**The probe protocol was applied rather than assumed.** Every request carried a declared
`User-Agent`, non-200 raised before any body was touched, and each downloaded file was checked for
its archive magic — `PK\x03\x04` for the wheel, `\x1f\x8b` for the sdist — **before** it was
hashed. A hash of an error page is a number that compares unequal for the wrong reason, and the
challenge-page trap recorded at the foot of the witness table is the live proof that this endpoint
family serves 200s that are not what they look like.

**THE PyPI PROVENANCE TRAP, RE-CONFIRMED LIVE A THIRD TIME.** `GET /pypi/synapse-cdm/1.4.0/json`
reports `provenance` as **null on both files** while attestations demonstrably exist. The simple
index carries the real URLs, and the bundles fetched from them return PyPI's own statement of the
four trusted-publisher values — `kind` GitHub, `repository`
`Decent-Cybersecurity/synapsecommand-public`, `workflow` `publish.yml`, `environment` `pypi` — with
in-toto subjects carrying the two digests above. Dated 2026-09-02. **This is the third reading,
not the second**, and the count matters because entry 11 was itself a re-confirmation: the trap was
first met in the **1.2.1** round, where a first pass read the legacy field as null across every
release and was about to record entry 10's attestations claim as unwitnessed. Found once and
re-confirmed twice, on three separate releases — a property of the endpoint, not an observation
about one of them.

**THREE SUITE TOTALS THAT DIFFER, AND NONE OF THE DIFFERENCES IS DRIFT.** Reconciled
2026-09-02, because three numbers are quoted for this release and a reader meeting them apart would
read two of them as decay:

| reading | passed | skipped | total |
| --- | --- | --- | --- |
| CI, at the tag, 2026-08-30T10:47:54Z | 3400 | 67 | 3467 |
| fresh clone at the tag, this machine | 3402 | 65 | 3467 |
| fresh clone at `c1cb308` | 3403 | 65 | 3468 |
| maintainer's tree at `c1cb308` | 3460 | 8 | 3468 |

**The totals are what reconcile, and they do exactly.** Clone versus maintainer is **57** tests that
pass here and skip there: the pinned specification PDFs and the KLV streams are gitignored, so a
clone carries the pin records and not the documents. That is the standing clone delta and not a
regression. Tag versus tip is **+1**, the changelog version sentence's gate, added by `7c76b5e`
after the tag — which is why the release body's 3467 and this file's 3468 are both right.

**The remaining two — CI's 3400/67 against this machine's 3402/65 on the SAME tree — are
environment and not tree**, and both are in `tests/test_cdm_version_floor.py`. One skips when there
is no virtualenv inside the clone, which is true of CI's checkout and false of a clone someone
built an environment inside. The other skips when the machine has no CPython 3.11; the CI image
carries none and this one has a `uv`-managed 3.11 that is not on `PATH`. Both are written as
corroboration that skips when absent rather than as an assertion nobody can satisfy, which is why
their absence costs two skips and no failures. **A suite total is a reading of a tree AND of the
machine under it**, and quoting one without the other is how a clone delta gets reported as decay.

**The four untouchables hold, each by its own command, and exactly one of them moved.**
The pinned phrase derives to **35** over the git index; `scripted_edit`'s contract is green at
**9**, with `pytest -k scripted_edit` collecting **11** because two `version_floor`
parametrizations match the name — the recorded trap, reproduced, and not a disagreement;
`git ls-files` matches **no** PDF. The one that cites a version is `RELEASE_NOTES.md`, which now
opens **1.4.0**. The other three are version-free and are unchanged by this release.

**What this entry does not claim.** That the approval says anything about token state. It does
not: the row reading **UNDATABLE from held evidence** stands untouched, and this upload is the
fifth dated witness that the tokenless mechanism works and the fifth that is silent about what else
would be accepted. And it does not claim the round moved anything inside the distribution — it did
not, which is why the bump gate still derives **NONE** over the arc since `v1.4.0` and no
`### Unreleased` section is owed.

### 13. `synapse-cdm` 1.4.1 is on the index — CLOSED, and the docs site has been three releases behind since 1.2.1

**Published 2026-09-04** by
[run 33847019240](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/33847019240),
triggered by the `v1.4.1` tag at `10d0956`. The build job ran 07:03:45–07:06:34Z; the `pypi`
environment then held the upload for **twenty-seven minutes and fifty-one seconds** until a required
reviewer approved it at **07:34:25Z**, and the publish job ran 07:34:28–07:34:54Z. Deployment
`6259605419` carries the sequence: `waiting` at 07:06:35Z, `queued` at 07:34:25Z, `in_progress` at
07:34:28Z, `success` at 07:34:55Z. **The whole act, tag push to `success`, took thirty-one minutes
and fourteen seconds**, of which the hold was twenty-eight.

**NOTHING ABOUT THE UPLOAD ITSELF DIFFERED FROM 1.4.0's PATTERN, AND THAT IS SAID PLAINLY RATHER
THAN DRESSED UP.** Six digest readings agreed on the first pass, the sizes agreed, both archives
carried their magic bytes, and the provenance trap read exactly as entries 10, 11 and 12 record it.
An entry whose subject is that nothing was surprising is worth more than one that manufactures a
finding, and this round's actual find is not in the upload at all — it is three paragraphs down,
in the documentation site.

**THIS ROUND RAN TWICE, AND THE FIRST RUN STOPPED BEFORE IT HAD A SUBJECT.** Its Act 0 read the
publish job at **2026-09-04T07:30:10Z** and found it `waiting`, with deployment `6259605419`
carrying one status row and `/pypi/synapse-cdm/1.4.1/json` answering **404**. It wrote nothing and
stopped, because a witness round whose act has not happened has nothing to witness. The approval
came at 07:34:25Z, four minutes after that reading. **Recorded because the stop is the mechanism
working**: the alternative is a round that treats an expected act as a completed one, which is the
class this file spends entry 12 on from the other direction.

**THE GITHUB RELEASE DID NOT EXIST AND WAS CREATED BY THIS ROUND, WHICH IS THE OPPOSITE OF 1.4.0.**
Entry 12 records that v1.4.0's Release already existed, created by the tag, and warns a later round
to check before creating one. It was checked: `gh release view v1.4.1` answered **release not
found** and the API answered **404** at **07:50:44Z**, with `releases/latest` still naming v1.4.0.
So the tag does **not** reliably create a Release here — v1.2.1 has none either — and entry 12's
warning holds in both directions: check, because either state is possible. Created at
**2026-09-04T07:51:45Z** by `decentcybersecurity`, not a draft, not a prerelease, now `Latest`, with
a body derived from `RELEASE_NOTES.md` and the run summary's condition-4 derivations. **Its
`created_at` field reads 07:02:23Z and that is not when it was made** — GitHub stamps a release
created from an existing tag with the tag object's own time, so `published_at` 07:51:45Z is the
instant that matters and the earlier one would otherwise read as a release predating its run.

**The digests, in six readings, and all six were reachable.** What the gate hashed after building
and gating, what the publish job hashed immediately before uploading, what the in-toto attestation
names as its subject, what the simple index declares, what the legacy JSON metadata states, and
what a recomputation over the downloaded bytes yields:

```
1d0b021f61fd089852ce2be3e5928853542e54a69d89e00d831b958e3e0d75a4  synapse_cdm-1.4.1-py3-none-any.whl
09ca1652c3b03f6134de7e39dd7c9c1499e015457c77f87405a76ebd6f494344  synapse_cdm-1.4.1.tar.gz
```

**All six agree, and the sizes agree with them** — 4 152 919 bytes for the wheel and 2 254 352 for
the sdist, identical in the legacy JSON, in the simple index and in the files downloaded from the
index on **2026-09-04 at 07:39:30–31Z**. The gate hashed them at **07:05:39Z** in the Condition 2
step and the publish job hashed the same two values at **07:34:31Z** in its "What is about to be
uploaded" step, across the twenty-eight-minute hold. PyPI recorded the wheel at
**07:34:49.129013Z** and the sdist at **07:34:51.092029Z**; the runner saw `200 OK` for them at
**07:34:50.934Z** and **07:34:52.651Z**, about 1.8 seconds later each — the index's clock stamps
receipt and the log's stamps the response arriving, and the two are not the same instant. One
build, gated as that build, uploaded as those bytes, served as those bytes. **The comparison basis
is the WORKFLOW's build and never a local rebuild** — entry 11 demonstrated why with two same-size,
different-digest wheels, and that ruling is inherited here rather than re-argued.

**THREE DIGESTS IN THIS RUN ARE NOT READINGS OF EITHER FILE, and they are named so a reader does
not count them among the six.** `sha256:260111a527359f898e8351cb8c8f263de06e41bc94ca0f2914d5c013b6f0c0fb`
is the digest of **GitHub's artifact bundle** — the zip the build job handed the publish job at
07:06:31Z and the publish job downloaded unchanged at 07:34:31Z. That equality is worth having: it
is what carries the two files across the hold intact. But it is a property of a container, not of a
distribution, and it appears in no PyPI metadata. The other two,
`60610d82…cfa2965e` and `eb61b136…9b745c5c`, are the two `.publish.attestation` files uploaded
alongside the distributions, and they are likewise not digests of the wheel or the sdist.

**The probe protocol was applied rather than assumed.** Every request carried a declared
`User-Agent`, non-200 raised before any body was touched, and each downloaded file was checked for
its archive magic — `PK\x03\x04` for the wheel, `\x1f\x8b` for the sdist — **before** it was
hashed. Both checks passed. A hash of an error page is a number that compares unequal for the wrong
reason, and the challenge-page trap recorded at the foot of the witness table is the live proof
that this endpoint family serves 200s that are not what they look like.

**THE PyPI PROVENANCE TRAP, RE-CONFIRMED LIVE A FOURTH TIME, AND IT DID NOT DIFFER.**
`GET /pypi/synapse-cdm/1.4.1/json` reports `provenance` as **null on both files** while attestations
demonstrably exist — read **2026-09-04T07:39:30Z**. The simple index carries the real URLs at
`/integrity/synapse-cdm/1.4.1/<file>/provenance`, and the bundles fetched from them at **07:39:17Z**
return PyPI's own statement of the four trusted-publisher values — `kind` **GitHub**, `repository`
**Decent-Cybersecurity/synapsecommand-public**, `workflow` **publish.yml**, `environment` **pypi** —
with in-toto subjects carrying the two digests above and predicate type
`https://docs.pypi.org/attestations/publish/v1`. **This is the fourth reading and the third
re-confirmation**, on a fourth separate release. Four readings across four releases is no longer an
observation about the endpoint; it is the endpoint's documented-by-repetition behaviour, and a round
that finds the legacy field populated should treat that as the novelty rather than this.

**THREE SUITE TOTALS THAT DIFFER, AND ALL THREE TOTAL 3472.** Reconciled 2026-09-04:

| reading | passed | skipped | total |
| --- | --- | --- | --- |
| CI, at the tag, 2026-09-04T07:04:55Z | 3403 | 69 | 3472 |
| fresh clone at `v1.4.1`, this machine, 07:41:03Z | 3404 | 68 | 3472 |
| maintainer's tree at `10d0956`, 07:41:41Z | 3464 | 8 | 3472 |

**The totals are what reconcile, and they do exactly.** Clone versus maintainer is **60** tests that
pass here and skip there, and the 60 are enumerated rather than waved at: 34 in
`test_cdm_pins.py`, 10 in `test_cdm_format_coverage.py`, 7 in `test_cdm_pin_paths.py`, 6 in
`test_cdm_stanag4609_adapter.py`, and one each in `test_cdm_stanag4586_adapter.py`,
`test_cdm_parks_table.py` and `test_cdm_version_floor.py`. **Fifty-nine of those are the gitignored
bytes** — the pinned specification PDFs and the KLV streams, which a clone has the record of and not
the document — and **the sixtieth is not**: `test_cdm_version_floor.py:368` skips because there is
no virtualenv inside the clone, which is a fact about where the interpreter lives and not about what
is tracked. Counting it with the other fifty-nine would have made the clone delta look purely like
gitignored bytes, which is the kind of rounding this table exists to refuse.

**CI's 3403/69 against the clone's 3404/68 on the SAME tree is one test, and it is environment.**
`test_cdm_version_floor.py:662` skips when the machine has no CPython 3.11; the CI image carries
none and this one has a `uv`-managed 3.11 the test can find. Both `version_floor` skips fire on the
runner and only the first fires here. **A suite total is a reading of a tree AND of the machine
under it**, and entry 12 recorded the same pair at a delta of two where this is a delta of one.

**THE SAME SUITE IS REPORTED TWICE IN ONE RUN WITH TWO DURATIONS, and neither is wrong.** The
Condition 1 step's log reads `3403 passed, 69 skipped in 53.11s` and the condition-4 summary step
runs `pytest -q -rs | tail -1` again and reads `48.84s`. **The counts are the reading and the
duration is not a property of the tree** — quoting the two durations as though they described
different trees is the shape this table exists to prevent, one axis over from the clone delta.

**THE DOCUMENTATION SITE IS THREE RELEASES BEHIND, AND THAT IS THIS ENTRY'S FINDING.** Measured
**2026-09-04T07:50:05Z**: <https://docs.synapsecommand.com/changelog> returns HTTP 200 and its own
text reads **"package is at `1.2.1`"** while the index serves **1.4.1**.
`gates/deploy_record.py` reconciles clean at **07:49:42Z** — **17 deployments listed, 6 with a row,
11 covered retrospectively, 0 unaccounted for**, and the alias `docs.synapsecommand.com` served by
**`222a55be`**, 5/5 pages identical to it and 5/5 differing from `5ed34cd8`. **`222a55be`'s source
commit is `4321331`, which is the v1.2.1 release commit.** So the site has served 1.2.1's changelog
across the 1.3.0, 1.4.0 and 1.4.1 releases.

**This is not a regression and nothing here broke.** The section below states that the Pages project
has **no Git integration**, so a push deploys nothing and the release commit moving
`docs/docs/changelog.mdx` was never going to reach the site. That claim is **confirmed by this
measurement rather than contradicted by it**: the absence of a deployment for `10d0956` is the
integration's absence observed. **What is new is the consequence, which nobody had measured**: a
page a stranger reads states a version three releases old, and the gate that would have caught it
does not check the site's *content* against the tree — it reconciles which deployment serves the
alias, and `222a55be` serving the alias is exactly what it expects. **A deploy is a person's act
here and this round did not perform one**: it moves no version string by its own terms, and
deploying the docs is not a witness round's to do.

**The four untouchables hold, each by its own command, and none of them moved.** The pinned phrase
derives to **35** over the git index; `scripted_edit`'s contract is green at **9**, with
`pytest -k scripted_edit` collecting **11** because two `version_floor` parametrizations match the
name — the recorded trap, reproduced, and not a disagreement; `git ls-files` matches **no** PDF and
**no** zip; and `klv_pin.json`'s delegation tally still reads fourteen. **Unlike entry 12, not even
the notes moved**: this round writes only this file and the test module that states its count, so
`version.py`, `RELEASE_NOTES.md`, `klv_pin.json` and `FORMAT_COVERAGE.md` are byte-identical to
`10d0956` at the close, verified by digest rather than by intent.

**What this entry does not claim.** That the approval says anything about token state. It does not:
the row reading **UNDATABLE from held evidence** stands untouched, and this upload is the sixth
dated witness that the tokenless mechanism works and the sixth that is silent about what else would
be accepted. It does not claim the docs site is broken — it serves what was last deployed to it,
which is what a project with no Git integration does. And it does not claim the round moved anything
inside the distribution: it did not, which is why the bump gate derives **NONE** over the arc since
`v1.4.1` and no pending section is owed.

## The deployment was not affected

The documentation site is deployed by explicit upload and **the Pages project has no Git
integration**, so the flip changed nothing about it: `wrangler pages project list` still reports
none for `synapsecommand-docs`, and no integration appeared as a side effect of the repository
becoming public. **Read 2026-09-03 at 10:28:56Z**, the project listing still naming no provider
for it, its domains `synapsecommand-docs.pages.dev` and `docs.synapsecommand.com`.

**THIS SENTENCE WAS THE SWEEP'S SHARPEST FIND, AND WHERE IT SITS IS WHY.** It asserted a
Cloudflare setting in the present tense with no instant — inside the section whose entire recorded
lesson is an undated present-tense claim about Cloudflare state going false while nothing noticed,
with the diagnosis three paragraphs below. **The round with the most attention this class has ever
had wrote the sentence and then wrote the paragraph explaining why the sentence is dangerous**,
which is the same argument `gates/deploy_record.py` was built on, arriving one class over: the
undated *reading* is not what that gate covers, because the gate reconciles which deployment serves
the alias and says nothing about when anyone last looked at the project's integration setting.
**And the first draft of this very repair was refused by a build**, because it quoted the listing's
column heading in order to report what the column said — one of the two strings
`tests/test_cdm_publication.py` forbids this file, so a note about an undated reading briefly made
the record a site of the deploy mechanism. Rule 9's carrier trap, sprung by a rule 12 repair, and
caught by a gate rather than by care.

The mechanism itself is stated in [`docs/README.md`](docs/README.md) and in `wrangler.toml`, and
`tests/test_cdm_deploy_workflow.py` requires those two to agree. **This file deliberately does not
restate it** — that gate's closure sweep treats any file describing the mechanism as a site it must
check, and a third site would be a third thing to keep in agreement for no gain.

**The post-flip measurement, and it is dated because it has been superseded.** Measured
**2026-08-25, 10:01Z**: the live site at <https://docs.synapsecommand.com> returned HTTP 200 and
was **byte-identical**, across five pages, to deployment `e08d2ea7` — whose recorded source commit
is `e116148`, the tip of `main` at the flip — and **differed** from the deployment before it. The
second half of that is what made it a measurement rather than a tautology: identical to the current
deployment and different from the previous one is the only pair of facts that distinguishes
"serving the last deployed state" from "serving something".

**It stopped being true forty-one minutes later.** Deployment `919b58db` went up at `10:42:03Z`
from source `30fa045`, and `57ac1878` at `14:35:07Z` from source `01fb685`; the second held the
`docs.synapsecommand.com` alias and served the site until `5ed34cd8` superseded it on **2026-08-27
at 01:01:32Z**. Neither was written down anywhere — not here, not in a commit message — and the
paragraph above went on asserting itself in the **present tense** for two days while a stranger
reading it would have been reading a fact about a deployment three back.

**And this sentence made the same mistake, in the round that was diagnosing it.** It read
"`57ac1878` … holds the alias and is what the site has served since" — present tense, undated, and
already false when it was typed: `5ed34cd8` had gone up four hours earlier in that same round, and
ledger entry 8's table records it. The file therefore contradicted itself for one round, with the
correction sitting three paragraphs below the error. **That is the argument for
[`gates/deploy_record.py`](gates/deploy_record.py) rather than for another paragraph about care**:
the round with the most attention this class has ever had still wrote it, because nothing could
fail.

This is the decay the table below predicts for a witnessed claim, arriving exactly as predicted:
*someone changes the setting afterwards and nothing notices*, with the deployment list playing the
part of the setting. The disposition of both unrecorded deploys, the reconciliation of the whole
list against this file, and the deploy that supersedes `57ac1878` are **ledger entry 8**.

## What is gated and what is witnessed

Three kinds of claim appear above and they are not equally strong. Reading them as equal is the
mistake this section exists to prevent.

| Kind | Example | How it can go stale |
| --- | --- | --- |
| **Suite-gated** | the three unsigned commits; the two files agreeing about the required status | it cannot — a test in the suite reads the claim, so a stale one is a red build |
| **Protocol-gated** | which deployment serves `docs.synapsecommand.com`; the deployment list being all `ad_hoc` | silently, and for as long as nobody runs the gate — the claim's truth lives at Cloudflare, which the suite cannot reach, and the gate that refuses a stale one is an act a person performs |
| **Witnessed** | the force-push refusal; the DCO check failing then passing; the byte-identical pages | someone changes the setting afterwards and nothing notices |
| **Recorded from the API** | the `deletion` rule; the ruleset version history; the app install time | same, and it was never observed in action |

**THE SINGLE `GATED` LABEL CARRIED TWO DISJOINT SENSES AND THE TERMS TABLE DEFINED ONLY ONE.
Found 2026-08-28, the two senses named the same day, the rows reclassified under them 2026-08-28 by
the repair round — the half the finding round left undone.** Both terms are now
defined once each, in the terms table above, and every row of the sweep table below carries one of
them. **Suite-gated** is the table's first row: the claim cannot go stale without a red build,
because a test in the suite reads it. **Protocol-gated** is weaker, and it is what four rows of the
sweep table mean — the deployment list's two claims, and the two rows
about which deployment serves the custom domain. Their truth lives at Cloudflare. The suite cannot
reach it and must not want to, and `tests/test_cdm_deploy_record.py` says so in as many words while
checking the part of the gate that can be wrong sitting still; what refuses a stale one is
[`gates/deploy_record.py`](gates/deploy_record.py), and running it is an act a person performs.
**The difference is not academic, and this table already carries the proof.** One custom-domain
claim went false *inside the round that wrote it* and another was superseded a day later, and each
was caught by somebody running the gate rather than by a build going red. A protocol-gated claim
goes stale silently for exactly as long as nobody runs the gate — which is the decay mode the
terms table assigns to a **witnessed** claim, and the reason the split is a split rather than a
qualifier: on the axis the third column measures, protocol-gated sits with witnessed and not with
the word it used to share. Found by sweeping this table's own cells:
**sweep rule 10** in `synapse_cdm/README.md`, written from this finding and from the one
corrected in the treatment column of the sweep table below.

**WHY THE ROWS WERE LEFT UNLABELLED WHEN THE SENSES WERE NAMED, AND WHY THAT IS REVERSED.
2026-08-28.** The finding round recorded the split in this paragraph and left every row saying
`GATED`, on the reasoning that relabelling them "would have thrown away the weaker one, which is
the honest description of four of them". **That reasoning does not survive being read.** Labelling
the four Cloudflare rows protocol-gated is precisely what *applies* the weaker sense; it is the
un-relabelled table that discards it, by showing a reader four claims under the stronger word. Two
terms are only worth defining if the rows use them. And leaving them was the defect sweep rule 10
exists to name, one turn deeper than the round found it: an index of what is checkable, telling a
reader that four claims whose truth lives at Cloudflare cannot go stale without a red build, with
the correction a paragraph away and out of the path of anyone reading the row. **A note that a
label is wrong is not a label that is right.** Which rows moved was re-derived here rather than
carried over — each cell read against what actually refuses its claim, not counted to four: the
four naming [`gates/deploy_record.py`](gates/deploy_record.py) as the check are protocol-gated,
because that gate shells out to `wrangler` and `tests/test_cdm_deploy_record.py` asserts in as many
words that it is not a suite member; the deploy-mechanism row and the prose-defect row's tree half
name suite tests that read only the tree, and stay suite-gated; the 1.2.1-on-the-index row keeps
its **at one remove** qualifier, because the suite test it names gates a proxy — the tag matching
the tree's `PACKAGE_VERSION` — and nothing in the suite reads the index itself.

**One carrier is opened by this repair and is left standing deliberately, named here so the next
sweep does not mistake it.** The paragraph above is now the only place in this file that spells the
retired single label, so a sweep for that label finds this explanation rather than a surviving row.
It is spelled twice, both times inside the sentence that records the retirement, and it cannot be
made unspellable the way sweep rule 9's three mechanized instances were — a retired label has to be
named to be retired. What makes it cheap is that the table it describes no longer contains the
token, so a reader who greps arrives at prose that says so in its first line.

**A FOURTH KIND HAS BEEN RETIRED, and entry 10 is where it was last exercised: a claim that is
merely CONSISTENT.** 2026-08-27. The release number is the sharpest case in this file, because a
PyPI filename is permanent and a version is the one claim in a release that can never be
corrected. Entry 10 records that the round was specified as **1.3.0** and renumbered itself to
1.2.1 from the diff — and every check in this repository would have passed 1.3.0. Each of them asks
whether a number is stated the same way in two places: the tag names the tree's `PACKAGE_VERSION`,
the notes describe that version, the package source that moved is written down. **Consistency is
not a measurement.** Three documents agreeing about a wrong number is three documents agreeing.

The number is now **suite-gated**, on the top row's terms — it cannot go stale because a test fails.
[`gates/bump_derivation.py`](gates/bump_derivation.py) classifies the diff over the distribution's
own contents between the previous tag and the tree being released against `version.py`'s
`PACKAGE_VERSION` table, and refuses a number that exceeds or undershoots it; it is condition 5 of
`MIGRATIONS.md`'s release procedure and it is in the suite, because it needs git and nothing else.
**Retroactively it derives the number every release of this package actually shipped** — 1.1.0 and
1.2.0 as MINOR, 1.2.1 as PATCH — having been told none of them, which is the check
`tests/test_cdm_bump_derivation.py` runs over the tags rather than a claim made here. Entry 10's
ruling is unchanged and is now re-derivable from the two trees it was made about.

**Where the table's prose needs judgement the gate refuses instead of guessing, and that is the
part worth reading as a design decision rather than a feature.** Its PATCH row and its MAJOR row
both reach a function whose body moved and whose name did not, and no diff separates them —
"the meaning changed" is a claim about intent. So the gate names the unit and stops, and a person
rules it in `MIGRATIONS.md` in the section describing the arc. The gate reads those rulings and
**refuses one that outlives its case**, which is this file's own discipline about exemptions applied
to a mechanism a round could otherwise satisfy by writing a sentence.

The suite cannot reach GitHub or Cloudflare, and it must not want to: a test that needs
credentials is a test that fails for every outsider and turns green only for whoever holds the
token. Re-witnessing is therefore a **protocol act**, like the stale-count sweep — the probes in
this file are written out in full so that re-running them is copying, not designing.

### The tense sweep, and the collection it produced

**Every witnessed claim in this file now carries a date or names a gate, and this is the list.** The
table above says a witnessed claim decays when "someone changes the setting afterwards and nothing
notices". Twice now that has happened here and the second time it happened *inside the round
diagnosing the first*, so the treatment is no longer per-incident: a claim about state outside this
tree is either **dated**, so a reader knows what it is a fact about, or it **names the gate** that
re-establishes it continuously. A bare present-tense assertion is neither, and it is what both
defects were made of.

**The collection is published rather than summarised, including the sites it judged already
correct.** A sweep reported as "n sites checked, m repaired" is a sweep whose misses nobody can
find. This one found two claims that were never true — ledger entry 9 — and it found them among
the rows it expected to tick off, which is the argument.

**How it was derived, so re-running it is copying.** Nine files carry claims about external state:
this file, `CONTRIBUTING.md`, `README.md`, `RELEASE_NOTES.md`, `docs/README.md`, `NOTICE`,
`wrangler.toml`, `MIGRATIONS.md` and the package `README.md`. Each was split into sentences and kept
where a sentence names an external system *and* carries a present-tense verb — 158 candidates, then
read by hand, because the filter is a floor and not a judgement. **It cannot see a claim that
mentions no platform**, which is the limit stated in entry 9.

| Claim | Where | Probe | 2026-08-27 | Treatment |
| --- | --- | --- | --- | --- |
| public: `private: false`, `visibility: public` | Visibility | unauthenticated `GET /repos` | holds | dated |
| anonymous `git clone` succeeds, `HEAD` == pushed tip of `main` | Visibility | credential-less shallow clone; `7544880` at both ends | holds | dated |
| ruleset 21205830 `main-protection`, `active`, `bypass_actors: []`, rules `deletion` + `non_fast_forward`, scope `~DEFAULT_BRANCH` | ruleset section | `GET /rulesets/21205830` | holds | dated |
| the ruleset's three-version history | ruleset section | — | historical | already dated per row |
| a non-fast-forward push to `main` is refused | ruleset section | the `GH013` probe | **not re-run** — re-witnessing means attempting the push | dated to its witness, 2026-08-25 |
| the `deletion` rule is recorded from the API and unwitnessed by behaviour | ruleset section | `GET /rules/branches/main` | holds, still unwitnessed | dated |
| DCO app id 1861, slug `dco`, org install `156427530`, `selected`, created 2026-08-25 09:32:51Z | DCO check | `GET /orgs/…/installations` | holds, to the second | dated |
| status-check name is `DCO`; a check run, not a legacy commit status | DCO check | needs a pull request to re-run | **not re-run** | dated to its witness |
| `main-protection` carries no `required_status_checks` rule | entry 1 | `GET /rulesets/21205830` | holds — the ruling stands | dated |
| `GET /commits/f916ba2/check-runs` returns `total_count: 0` | entry 1, ground 1 | — | historical measurement | already dated by its commit |
| `GET /contributors` → one contributor, 2 contributions | entry 4 | `GET /contributors` | holds | dated |
| ~~the other **46** commits are authored by `m@…`~~ | entry 4 | `git log` | **stale count** — 94 of 96 | number removed; the claim is now the set, not a ratio, on entry 2's rule |
| ~~no commit is GPG/SSH-signed~~ | entry 4 | `GET /commits` verification | **FALSE, and never true** — 2 of 96 | struck; **ledger entry 9** |
| SBOM 404; secret scanning disabled; Dependabot security updates disabled | entry 4 | `GET /repos` + SBOM endpoint | all three hold | dated |
| ~~code search returns `total_count: 0`; not indexed yet~~ | entry 4 | `GET /search/code` | **FALSE — decayed**, as the bullet forecast | struck and dated |
| Community Standards 50%; no code of conduct, issue or PR template | entry 4 | `GET /community/profile` | holds, all four | dated |
| 1.0.0 on the index: one release, two files, the digests, the metadata | entry 5 | `GET /pypi/…/json` | superseded by 1.1.0 and 1.2.0 | **already dated 2026-08-25**, and scoped to 1.0.0 deliberately |
| `synapse-cdm` returns 404 on TestPyPI | entry 5 | `GET test.pypi.org/pypi/…/json` | holds | dated |
| `synapse_cdm` answers `301` to the canonical name | entry 5 | `GET /simple/synapse_cdm/` | holds **on the simple index**; `/pypi/synapse_cdm/json` answers `200` directly, without a redirect | dated, and the endpoint named — the claim is true of one of the two APIs |
| `synapsecdm` is 404, unclaimed, a different project | entry 5 | `GET /pypi/synapsecdm/json` | holds | dated, **and see the probe-form warning below** |
| the long description's fifteen links are relative; all five `project.urls` are on the page | entry 5 | `project_urls` in the JSON API | five URLs hold | dated; the relative-link half is **not re-witnessable** — see below |
| the `pypi` environment: reviewer `decentcybersecurity`, tag policy `v*`, `prevent_self_review: false`, `wait_timer: 0`, created 2026-08-26T06:46:16Z | entry 6, step B | `GET /environments/pypi` and its branch policies | all five hold | dated |
| 1.1.0's and 1.2.0's digests equal what the index serves | entry 6 | recomputed over downloaded bytes | historical | **already dated**, 2026-08-26 and 2026-08-27 |
| 1.0.0 and 1.1.0 are both on the index | entry 6, step C | `GET /pypi/…/json` | holds, and 1.2.0 with them | dated |
| the token is revoked; OIDC is the only way in | entry 6, step C | none exists — PyPI publishes no token state | **UNDATABLE from held evidence** | recorded as resting on the maintainer's word, which that step already said in as many words |
| ~~step C is `NOT DONE`~~ | entry 6, "Where this stands" | the same entry, four paragraphs down | **FALSE, and never true as an undated snapshot** | struck; **ledger entry 9** |
| the Pages project has no Git integration | deployment section | `wrangler pages project list` | holds — the project reports none | dated |
| the deploy mechanism is stated in two places and they agree | deployment section | — | — | **SUITE-GATED**: `tests/test_cdm_deploy_workflow.py` |
| the flip-day byte identity to `e08d2ea7` | deployment section | — | superseded | **already dated 2026-08-25 10:01Z**, and this is the pattern the rest of this table follows |
| ~~`57ac1878` holds the alias and is what the site has served since~~ | deployment section | five pages, byte compared | **FALSE — decayed inside the round that wrote it** | dated and superseded; **`gates/deploy_record.py`** |
| the deployment list is all `ad_hoc`, every source commit resolving here | entry 8 | `gates/deploy_record.py` | holds | **PROTOCOL-GATED** for the two claims in the left column. **This cell's own trailing claim about where the list's length lives was wrong in the commit that wrote it** — it said the figure was derived by the gate and appeared in no prose, and entry 8 spelled it three times in this same file on that day. **That sentence is why nobody looked**, and the count it waved off is the one that then decayed. Corrected 2026-08-28: the figure is stated in the entry, derived from the gate's own enumeration, and ruled by `tests/test_cdm_deploy_record.py` |
| every deployment id is named by a row or by the pinned coverage set | entry 8 | `gates/deploy_record.py` | holds | **PROTOCOL-GATED** |
| ~~`docs.synapsecommand.com` is served by `5ed34cd8`~~ | entry 8 | `gates/deploy_record.py`, by bytes | **superseded 2026-08-27 12:37:06Z** by `222a55be` | **PROTOCOL-GATED** — the gate refused the stale id, which is how the pin moved |
| `docs.synapsecommand.com` is served by `222a55be` | entry 8, entry 10 | `gates/deploy_record.py`, by bytes | holds | **PROTOCOL-GATED** |
| ~~the distribution on the index is 1.2.0~~ | `MIGRATIONS.md`, Unreleased | `GET /pypi/…/json` | **superseded 2026-08-27** by 1.2.1, and the section cited was absorbed into `### 1.2.1` | the citation is why this row is struck rather than edited: an `Unreleased` section is by construction not a durable address |
| ~~the distribution on the index is 1.2.1~~ | `MIGRATIONS.md`, `### 1.2.1`; entry 10 | `GET /pypi/…/json`, and `pip install` in a clean venv | **superseded 2026-08-29** by 1.3.0; the section cited is a released heading and stays a durable address, which is the difference from the struck 1.2.0 row above | **SUITE-GATED at one remove**: `tests/test_cdm_release.py` requires every release tag to name the `PACKAGE_VERSION` of the tree it points at. **Corrected 2026-08-28 — the rest of this cell was wrong about the gate it names, and wrong from the commit that wrote it.** It said the gate forbids an `Unreleased` section once the tag exists. That rule is conditional on the moved set: the section is *required* while shipped files have moved past the tag and forbidden only when the tree is identical to it, so a tag and an `Unreleased` section coexist legally — as they have here since `e825e96`, written about an hour after this cell was. Consistent with the tree in that hour and false about the mechanism throughout; sweep rule 10's second instance |
| 1.2.1's digests equal what the index serves, in four readings | entry 10 | recomputed over downloaded bytes | holds | dated 2026-08-27 |
| the four prose defects in the 1.2.0 artefacts are corrected in 1.2.1 | entry 10 | read out of the installed copy and the downloaded sdist | holds | dated 2026-08-27; the tree half is **SUITE-GATED** by `tests/test_cdm_prose_counts.py` |
| ~~the distribution on the index is 1.3.0~~ | `MIGRATIONS.md`, `### 1.3.0`; entry 11 | `GET /pypi/…/json`, and `pip install synapse-cdm==1.3.0` in a clean venv | holds | dated 2026-08-29. **SUITE-GATED at one remove**, on the same reading as the row it supersedes: the suite requires every release tag to name the `PACKAGE_VERSION` of the tree it points at, which ties the tag to the tree and not the tree to the index. **Superseded 2026-09-02** by 1.4.0; the section cited is a released heading and stays a durable address |
| the distribution on the index is 1.4.0 | `MIGRATIONS.md`, `### 1.4.0`; entry 12 | `GET /pypi/…/json`, and `pip install synapse-cdm==1.4.0 --no-cache-dir` in a clean venv with no clone on its path | holds — `PACKAGE_VERSION` `1.4.0`, installed `METADATA` `Version: 1.4.0`, `SCHEMA_VERSION` `1.0.0` unmoved, and `cdm-harness --list-adapters` reports **14 adapters**, three ingest and eleven bidirectional | dated 2026-09-02. **SUITE-GATED at one remove**, on the same reading as every version row before it. `pip` resolved it on the first attempt, so entry 10's propagation lag does not reproduce a second time |
| 1.3.0's served artefacts equal the bytes the workflow gated, both files | entry 11 | SHA-256 recomputed over the downloaded bytes, against the digests `--export-dist` printed inside run `33247697980` | holds | dated 2026-08-29. The comparison basis is the WORKFLOW's build, not a local one: a local rebuild of the same tree differs in generated metadata, and this round rebuilt locally and got two different digests, which is the claim demonstrated rather than asserted |
| 1.4.0's served artefacts equal the bytes the workflow gated, both files | entry 12 | SHA-256 recomputed over the downloaded bytes, against the digests `--export-dist` printed inside run `33307299409` | holds, in **six** readings that were all reachable | dated 2026-09-02. Same comparison basis as the row above — the WORKFLOW's build, never a local rebuild. The probe raised on non-200, declared a `User-Agent`, and checked each file's **archive magic before hashing it**, because a hash of an error body compares unequal for the wrong reason |
| the trusted publisher's four values, from PyPI's own side | entry 11 | the **simple index**'s per-file `provenance` URL, then the bundle's `publisher` block | holds — `kind` GitHub, `repository` `Decent-Cybersecurity/synapsecommand-public`, `workflow` `publish.yml`, `environment` `pypi` | dated 2026-08-29. **The legacy JSON API's per-file `provenance` is the WRONG field** — it reads `null` on every release of this package whether attestations exist or not. **Re-confirmed on 1.4.0, dated 2026-09-02**, with the same four values. That is the **third** reading of it — found in the 1.2.1 round (`MIGRATIONS.md`, where a first pass nearly recorded entry 10's attestations as unwitnessed), re-confirmed on 1.3.0, and again here — which makes it a property of the endpoint rather than an observation about one release |
| the upload was accepted over OIDC with no credential in the workflow | entry 11 | the `pypi` environment's approval and the publish job's own run | holds | dated 2026-08-29T10:47:24–50Z. **This is a witness that the mechanism WORKS, and it is not a witness about token state** — the row four above still reads UNDATABLE and this one does not supersede it, because PyPI publishes no token state and an upload proves only what it used. **A fifth such witness, 1.4.0, dated 2026-08-30T17:18:53–17:19:19Z** — approval to `success` — and it does not supersede the UNDATABLE row either. **A sixth, 1.4.1, dated 2026-09-04T07:34:25–07:34:55Z**, and it does not either: six uploads prove the mechanism works six times and say nothing about what else the index would accept |
| a `urllib` default `User-Agent` gets HTTP 403 from `docs.synapsecommand.com` | entry 10 | four `User-Agent` values compared | holds | dated 2026-08-27 — recorded because a uniformly failing probe reports identity |

**A probe form that gives the wrong answer, and it is the sort of thing this table exists to
carry.** `https://pypi.org/project/synapsecdm/` returns **HTTP 200** — a bot-challenge page titled
`Client Challenge`, not a project page. Anyone re-witnessing "the name is unclaimed" from the
project URL reads a 200 and concludes the opposite of the truth. The probe that answers is the JSON
API, `GET /pypi/synapsecdm/json`, which returns 404. A written-down probe is only as good as the
endpoint it names.

**One claim is recorded as undatable rather than given a date, and one is half-witnessable.** The
revoked token cannot be observed by anyone but the maintainer, so it gets no date and says so — an
invented "verified as of" on a fact nothing can check is the failure this whole file is against. And
the fifteen relative links in the long description cannot be re-read off the project page while that
page answers with a challenge; the five `project.urls` can, and do.
