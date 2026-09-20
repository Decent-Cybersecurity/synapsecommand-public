# ADR 0011 — Repository governance enforcement: what is documented, what is proposed, what is applied

## Status

Proposed — audit remediation F08, 2026-09-20. Nothing in this ADR is applied. The standing ruling
it must not silently change is `PUBLICATION.md` ledger entry 1 (`DCO` stays advisory; direct
pushes to `main` continue), and `CONTRIBUTING.md` states the same ruling in the contributor's
terms. Both remain in force. Remote enforcement is **BLOCKED_ADMIN_ACTION** in
`docs/audit-remediation-report.md` until an administrator applies a stage and reads it back by
the procedure in `docs/governance/RUNBOOK.md`.

This ADR becomes *Accepted (stage 1)* when the runbook's readback for stage 1 is recorded in
`PUBLICATION.md` as a dated API reading, and *Accepted (stage 2)* only after the ruling in entry 1
is reversed at both sites in one commit, as entry 1 itself prescribes.

## Context

The audit (finding F08) asked for enforceable governance without silently changing policy, and
found three things that were true at once:

1. **The platform settings are a record, not a reading.** `PUBLICATION.md` records ruleset
   `main-protection` (id 21205830) with rules `deletion` and `non_fast_forward`, an empty
   `bypass_actors`, scope `~DEFAULT_BRANCH`, and no `required_status_checks` rule, each row dated
   to the day it was read from the API. Nothing in the repository re-reads those settings, so the
   record can go stale without a red build — the document's own "What is gated and what is
   witnessed" section says so.
2. **The advisory `DCO` check is a ruling with a measured ground.** The DCO app produces check
   runs on pull-request events only; a required status check in a branch ruleset gates every push
   to the branch. Requiring it while direct pushes stay legal would deadlock `main`. Entry 1
   records this, `tests/test_cdm_publication.py` holds both documents to it, and this ADR does not
   reopen it.
3. **The workflows were already close to the shape a required-checks rule needs**, and one
   defect stood: `rc-build.yml` expanded a `workflow_dispatch` input inside a `run:` script.
   Everything else the brief asked to inspect held: every action pinned to a full commit SHA,
   read-only top-level permissions in every file, writes declared per job, no
   `pull_request_target`, no `secrets.*` reference anywhere, no `paths` filter on any workflow
   that would carry a required check, dependency review on pull requests, gitleaks over the whole
   reachable history on every push and pull request, CodeQL on push, pull request and a weekly
   schedule.

The repository has **one maintainer**, who is also its administrator. Two consequences follow
and this ADR states them rather than designing around them: a pull request cannot be approved by
its own author, so a required approval count above zero would block every change; and any
ruleset an administrator applies is a constraint the same administrator can remove, so the value
of a ruleset here is that a bypass is a **logged event** rather than that it is impossible.

## Decision

1. **Three states, never conflated.** `gates/governance_audit.py` prints DOCUMENTED (the record,
   carried as data and held to `PUBLICATION.md` by `tests/test_cdm_governance.py`), PROPOSED (the
   files under `docs/governance/rulesets/`) and LIVE (the API, read only with a credential, and
   otherwise reported as `UNVERIFIED` with exit status 3 — never a pass by default, never inferred
   from files, never printing a token).
2. **Two staged proposals, one ruleset name.**
   - *Stage 1* (`stage1-main-protection.json`) adds `required_linear_history` to the documented
     rules and changes nothing else. It is compatible with direct pushes and with entry 1; the
     history it was derived against has zero merge commits, so it refuses nothing the documented
     workflow does. `bypass_actors` stays empty, as recorded.
   - *Stage 2* (`stage2-main-protection-pull-request-only.json`) is the pull-request-only shape:
     a `pull_request` rule with zero required approvals, `required_status_checks` naming every
     context the pull-request workflows report plus the DCO app's `DCO` check, linear history,
     squash or rebase merges, and one emergency bypass for the repository admin role. It
     **requires the ruling in entry 1 to be reversed first**, and the apply verb refuses it for as
     long as either document still carries the ruling's wording.
3. **Required checks are derived, not typed.** The stage 2 contexts are the `name:` of every job
   in every workflow with a `pull_request` trigger, matrix-expanded, exactly as Actions reports
   them. The test holds the file to that derivation; a renamed job reds the suite until the file
   is regenerated, which is what "stable check names" means in practice.
4. **The apply path is a separate verb, and it was not run.** `apply` needs a proposal file, the
   typed confirmation `APPLY main-protection`, a credential, prints its plan, writes nothing when
   the live ruleset already equals the proposal, addresses one ruleset by name, and reads the
   result back before reporting success. The audit default mutates nothing under any credential.
5. **One workflow defect fixed.** The `rc-build.yml` job summary now receives the dispatch reason
   through `env:`; the test forbids any `github.event.*`, `inputs.*` or `github.head_ref`
   expression inside a `run:` block in any workflow, and limits the remaining in-script
   expressions to this repository's own step and job outputs.
6. **Nothing is invented for review.** No CODEOWNERS file, no team, no second reviewer. Review in
   stage 2 is the required checks, the DCO check and the maintainer's own read; `PUBLICATION.md`
   entry 16 records that releases are already approved on a reviewer's recorded verdict, and that
   mechanism is untouched.

## Alternatives considered

- **Require `DCO` now, without a `pull_request` rule.** Refused: entry 1's ground 1 is measured —
  a direct push acquires no `DCO` check run, so it could never acquire a passing one.
- **Apply stage 2 as part of this remediation.** Refused twice over: the brief forbids executing
  the apply operation, and it would reverse a ruling by a settings change rather than by the
  documented sequence (restore `pull_request`, then require `DCO`, then probe, then update both
  sites in one commit).
- **A tag ruleset over `v*`.** Considered and not proposed. The release procedure records that a
  tag is deleted and re-pushed when a gate refuses it at the tag (`PUBLICATION.md` entries 18
  to 20), and a `deletion`/`update` rule over tags would refuse that routine; proposing it means
  changing the release procedure first, which is another decision.
- **Cryptographic commit signing as a rule.** Not proposed. The control actually in force is
  the DCO sign-off; no commit in this history is GPG- or SSH-signed, and `required_signatures`
  would refuse every push until that changes. Sign-off and signing are distinct controls and this
  ADR leaves both exactly where they are.
- **An empty `bypass_actors` in stage 2.** Considered. With one administrator the alternative to a
  bypass actor is editing the ruleset in an emergency, which leaves it in a changed state and is
  logged as a settings edit rather than a bypass; the logged bypass is the more legible of the two.
- **Reading live settings from a cached JSON in the tree.** Refused by the brief and by this ADR:
  a JSON ruleset file is not proof of protected `main`.

## Consequences

- The repository gains a non-mutating audit whose `UNVERIFIED` verdict is honest about the
  absence of a credential, and whose live verdict compares the API's reading against the record.
- Stage 1 can be applied by an administrator today without changing any ruling; the runbook's
  readback is what turns "proposed" into "recorded".
- Stage 2 stays a proposal. If the working shape ever changes to pull requests only, the ADR, the
  file and the apply verb are ready, and the apply verb will still refuse until the ruling is
  reversed where it is written.
- Every job rename now has a second consequence: the stage 2 file must be regenerated. That is the
  cost of check names being an interface.

## Compatibility impact

None on the package, the schemas, the manifests or the evidence. No version axis moves. No
workflow trigger changes, so `ARCHITECTURE.md` §7's inventory and trigger table are unaffected.
`rc-build.yml`'s dispatch input keeps its name, default and description; only the carrier changes.

## Security impact

- Closes an expression-injection surface in a dispatch-only workflow (reachable only by someone
  who already holds write; closed anyway because least privilege is not "trust whoever can
  dispatch").
- The audit never prints a credential: token variables are tested for presence only, `gh auth
  status` output is discarded, and no exception message carries a header or a response body.
- No new permission in any workflow. Trusted Publishing, the `pypi` environment and the release
  approval flow are untouched.

## Reversibility

Complete. Stage 1 is reverted by applying the documented ruleset again (the audit's DOCUMENTED
block is the API body). Stage 2 is never applied without the ruling reversal that entry 1
prescribes, and the same entry names the sequence for going back. The gate, the proposals, the
runbook and this ADR can be deleted without touching the distribution.
