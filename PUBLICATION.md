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

Five entries, and the set does not move — entries change **state**, they are not deleted. Entry 1
is **ruled on** and stays here as the ruling; entries 2, 3 and 4 are open, and all four were
previously recorded only in commit messages. Entry 5 was opened by the SDK round, which built and
verified a publishable distribution and stopped short of publishing it. None blocks anything.

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

### 5. `synapse-cdm` is not on PyPI — built, verified, and waiting on a human

The SDK round made `packages/cdm` a real distribution: `python -m build` produces a clean sdist
and wheel, `gates/wheel_install.py` installs the wheel into an environment with no part of this
repository on its path and runs the harness and half the suite against it, and `twine check
--strict` PASSES on both artefacts. What has **not** happened is an upload, and this entry says
exactly why and exactly what closing it takes.

**The name is free, measured on 2026-08-25.** All three spellings return **HTTP 404** from both
the JSON API and the simple index — `synapse-cdm`, `synapse_cdm` and `synapsecdm` — and
`synapse-cdm` is 404 on TestPyPI as well. PEP 503 normalises the first two to the same name, so
that is one name checked three ways rather than three names. A 404 is availability at a moment,
not a reservation: nothing holds the name until something is uploaded under it.

**The metadata is complete and it is gated.** `tests/test_cdm_packaging.py` asserts the author is
`Decent Cybersecurity s.r.o.` as `NOTICE` spells it, the licence expression and both licence
files, the five project URLs, the classifiers including the declared Python floor, and that the
long description is a file inside the distribution. `twine check --strict` confirms the README
renders.

**Why it stopped here.** There are no credentials on this machine — no `~/.pypirc`, no API token
in the environment — and Trusted Publishing is not an option that merely needs switching on: it
authenticates a **GitHub Actions workflow**, and this repository has no `.github/workflows` and no
CI at all (see MIGRATIONS.md, "What is deliberately not automated"). Inventing a publishing
mechanism to close this entry would be the deploy-claim mistake in a new place: a workflow written
to satisfy a checklist, never run, describing an automation nobody has watched work.

**What a human has to do, in order.** Nothing below is inferrable from the repository; that is why
it is written out.

1. Create the PyPI account and enable two-factor authentication on it — PyPI has required 2FA for
   uploads since 2024, so an account without it cannot publish at all.
2. Decide the owner. `synapse-cdm` should belong to an organisation account for
   Decent Cybersecurity s.r.o. rather than to an individual, because the package's declared author
   is the company and a personal account makes succession a favour rather than a process.
3. Upload to **TestPyPI first** and install from it into a clean environment. The project page
   cannot be previewed any other way, and an upload to PyPI is irreversible: a filename can never
   be reused, even after the release is deleted.
4. Mint a **project-scoped API token** — scoped to `synapse-cdm` once it exists, which means one
   throwaway upload under an account-scoped token first, or an initial upload with the wider token
   and an immediate re-scope.
5. `python -m build packages/cdm && twine upload packages/cdm/dist/*`, then verify by installing
   from the index in a clean venv and running `python -m synapse_cdm.harness --adapter pntmap`.
6. Update the two places that say it is unpublished — `README.md` ("Using it") and
   `docs/docs/intro.mdx` ("Installing it") — and this entry.

**One accepted limitation, ruled rather than overlooked.** The long description is the package's
own `README.md`, and its fifteen links are relative (`adapters/pntmap.py`, `MIGRATIONS.md`). PyPI
does not rewrite relative links, so they will not resolve on the project page. They are left
relative on purpose: they are correct in all three places the file actually lives — the
repository, the sdist and the installed package — and the alternative, absolute `blob/main` URLs
baked into a released wheel, points a 1.0.0 reader at whatever `main` says years later. Navigation
on the project page is what the five `project.urls` entries are for.

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
