# Repository governance runbook — audit, apply, read back

This is the operator procedure for the ruleset proposals under `docs/governance/rulesets/` and
the audit gate `gates/governance_audit.py`. It is written for the repository as it is: **one
maintainer, who is also the administrator**, direct pushes to `main` legal by ruling
(`PUBLICATION.md` ledger entry 1), sign-off by DCO trailer, no cryptographic commit signing.
ADR 0011 (`docs/adr/0011-repository-governance-enforcement.md`) records the decisions; this file
records the acts.

Three states are kept apart throughout, and the gate labels every line of its output with one:

| State | Where it lives | What it proves |
| --- | --- | --- |
| DOCUMENTED | `PUBLICATION.md` (ruleset section, entry 1, the sweep table) and the `DOCUMENTED` block in the gate, which the suite holds to the document | what the settings WERE when they were last read from the API, on the date each row carries |
| PROPOSED | `docs/governance/rulesets/stage1-*.json`, `stage2-*.json` | nothing about the live repository. A JSON ruleset file is not proof of protected `main` |
| LIVE | the GitHub API, read by the gate only with a credential | the settings now — and only for as long as the reading is fresh |

## Prerequisites

- Administrator on `Decent-Cybersecurity/synapsecommand-public`.
- One of: `gh auth login` as that administrator, or a fine-grained token in `GH_TOKEN` with
  *Administration: read* (audit) or *Administration: write* (apply) on this repository.
- **Never paste the token anywhere.** The gate tests the variable for presence only, discards
  `gh auth status`'s output, and prints neither a header nor a failed response body. Keep the
  same discipline in the shell: no `echo $GH_TOKEN`, no token in a commit message or a report.
- A checkout of the commit whose proposals you are applying, so the file and the readback are
  compared against the same bytes.

## 0. Read the proposals without touching the network

```
python gates/governance_audit.py --offline
```

Prints DOCUMENTED and PROPOSED, and `LIVE: UNVERIFIED — offline flag`, exit 3. Use this to see
what a stage would change before there is any credential in the environment.

## 1. Audit the live settings (mutates nothing)

```
python gates/governance_audit.py
python gates/governance_audit.py --json > /tmp/governance-audit.json
```

| Exit | Meaning | What to do |
| --- | --- | --- |
| 0 | `LIVE … HOLDS`: the API reading equals the DOCUMENTED record | add a dated row to `PUBLICATION.md`'s sweep table ("holds", today's date) |
| 1 | `LIVE … DRIFT`: the reading differs; each difference is printed as `drift: …` | the record is stale or the settings moved. Update `PUBLICATION.md` with the reading and the date; if the settings moved without a ledger entry, that is the finding |
| 3 | `LIVE: UNVERIFIED`: no credential | nothing was read. Do not record a "holds" |
| 2 | usage, or a proposal file failing its own checks | fix the file; the message names the field |

An `unreadable (HTTP 403)` finding means the credential cannot see rulesets. It is not "no
ruleset exists"; do not record it as either.

## 2. Apply stage 1 (compatible with the standing ruling)

Stage 1 adds `required_linear_history` to the documented rules and nothing else. It needs no
ruling change: `bypass_actors` stays empty, no `pull_request` rule, no `required_status_checks`
rule, direct pushes continue. The history it was derived against has no merge commit, so it
refuses nothing the documented workflow does. Check that is still true before applying:

```
git log --merges --oneline origin/main | wc -l      # expect 0
```

Then:

```
python gates/governance_audit.py apply \
  --proposal docs/governance/rulesets/stage1-main-protection.json \
  --confirm 'APPLY main-protection'
```

The verb prints its plan first (`{"action": "update", "changes": ["rules"], …}`), writes one
`PUT /repos/…/rulesets/21205830` with exactly the proposal's six fields, reads the ruleset back
and compares. Outcomes:

- `idempotent: … nothing written.` (exit 0) — the live ruleset already equals the proposal.
  Running the verb twice is safe by design.
- `applied and read back: ruleset 21205830 (main-protection) equals the proposal.` (exit 0).
- `READBACK DISAGREES` (exit 1) — treat the write as unverified; read the ruleset by hand (step 3)
  and do not record success.
- `REFUSED` (exit 4) — only stage 2 can produce this; see below.

## 3. Read back independently and record

Do not rely on the verb's own readback alone; the point of a readback is a second reading.

```
gh api repos/Decent-Cybersecurity/synapsecommand-public/rulesets/21205830 \
  --jq '{name, enforcement, bypass_actors, conditions, rules: [.rules[].type]}'
python gates/governance_audit.py          # expect exit 1 now: DRIFT against the OLD record
```

That exit 1 is correct and expected: the gate compares against the DOCUMENTED block, which still
describes the pre-stage-1 ruleset. Recording the change is what closes it:

1. `PUBLICATION.md`: add a version row to the ruleset table (the API's `version` history will show
   a fourth version), and a dated sweep-table row for the new rule set. State that the
   `required_linear_history` rule is **recorded from the API and unwitnessed by behaviour** until
   a merge-commit push to `main` has actually been refused — and do not manufacture one to witness
   it; the ruleset section already records that re-witnessing a refusal means attempting the
   push.
2. `gates/governance_audit.py`: move the `DOCUMENTED` block to the new rule list, in the same
   commit as the `PUBLICATION.md` change (the suite holds the two to each other).
3. ADR 0011: *Status* becomes "Accepted (stage 1) — <date>, readback recorded in PUBLICATION.md".
4. `docs/audit-remediation-report.md`: F08's disposition moves from BLOCKED_ADMIN_ACTION to the
   dated readback, for stage 1 only.

Re-run the audit; expect exit 0.

## 4. Stage 2 — only after the ruling is reversed, in this order

Stage 2 is the pull-request-only shape. The verb **refuses it** (exit 4, nothing read, nothing
written) while `CONTRIBUTING.md` still calls the advisory check a
"settled decision and not an oversight" and `PUBLICATION.md` still says `DCO` "stays advisory".
That refusal is deliberate:
a settings change must not be the thing that reverses a ruling. Entry 1 names the sequence, and
it is the sequence here:

1. Decide, and record the decision as a new ledger entry in `PUBLICATION.md` that closes entry 1's
   ruling and gives the reason direct pushes stopped being the working shape.
2. In the **same commit**, reword `CONTRIBUTING.md`'s DCO paragraph and entry 1's marker sentence;
   `tests/test_cdm_publication.py` will insist the two sites move together, and
   `tests/test_cdm_governance.py`'s ruling-in-force reading turns false for both.
3. Regenerate the stage 2 context list if any job has been renamed since the file was written
   (`python gates/governance_audit.py --offline --json | jq '.check_contexts[].context'`), and
   confirm every listed workflow still triggers on `pull_request` with no `paths` filter — the
   suite holds both.
4. Apply: same verb, `--proposal docs/governance/rulesets/stage2-main-protection-pull-request-only.json`.
5. Probe the result the way the protections were probed originally, on a throwaway branch and
   pull request: one deliberately unsigned commit → expect the `DCO` check failing and the merge
   button blocked; sign it off → expect the check passing and every required context green;
   attempt a direct push to `main` from a non-admin token → expect refusal citing the
   `pull_request` rule. Record each observation with its timestamp.
6. Read back (step 3), record the fourth-or-later ruleset version, move `DOCUMENTED`, set the ADR
   to "Accepted (stage 2)".

Merges under stage 2 are squash or rebase only (`allowed_merge_methods`), because
`required_linear_history` refuses a merge commit; set the repository's merge-button options to
match before the first pull request.

## 5. Emergency bypass

**Under the documented ruleset and under stage 1** there is no bypass actor. An emergency change
that the rules would refuse (a non-fast-forward push, a merge commit) is made by editing the
ruleset — set `enforcement` to `disabled`, push, set it back to `active` — and every edit is a
`repository_ruleset.update` event in the organisation audit log. Record the window (both
timestamps) in `PUBLICATION.md` the way entry 2 records the temporary bypass actor that was added
and removed on 2026-08-25.

**Under stage 2** the repository admin role is a bypass actor with `bypass_mode: always`. An
administrator's direct push to `main` succeeds and is logged as a `bypass` of ruleset
`main-protection`; nothing else changes and the ruleset stays as applied. After any use:

```
gh api "repos/Decent-Cybersecurity/synapsecommand-public/rulesets/rule-suites?ref=main&time_period=week" \
  --jq '.[] | select(.result == "bypass") | {pushed_at, actor_name, after_sha}'
```

Record each bypass in `PUBLICATION.md` with the SHA it landed and the reason. A bypass that is
not recorded is the failure this whole arrangement exists to make visible.

## 6. Rolling back

Stage 1 → documented: write a proposal file whose `ruleset` equals the gate's DOCUMENTED block
(`python gates/governance_audit.py --offline --json | jq .documented.ruleset`), with
`requires_ruling_reversal: false`, and apply it with the same verb; then step 3.

Stage 2 → stage 1: apply the stage 1 file. The ruling reversal is a document change and is
reverted where it was made, with a ledger entry saying so.

## What this runbook does not do

- It invents no CODEOWNERS file, team or second reviewer; there is one maintainer.
- It does not require cryptographic signatures; the control in force is the DCO sign-off.
- It does not touch Trusted Publishing, the `pypi` environment or the release approval flow.
- It does not treat this file, the proposals or the ADR as evidence of anything applied.
