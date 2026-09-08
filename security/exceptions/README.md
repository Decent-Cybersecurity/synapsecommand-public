# `security/exceptions/`

A documented, time-bounded decision **not to fix a security finding immediately**. SOIF Part 1
§45: "no permanent undocumented exemptions".

**There are none today.** This directory holds `schema.json` and this file and no exception, and
that is a reading rather than an aspiration: `pip-audit --strict` over the installed environment
on 2026-09-08 reported *No known vulnerabilities found*, and no CodeQL run has yet produced a
SARIF for this repository — advanced setup landed in round P6 and its first run is round P7's to
record. An empty directory is the correct state and the tooling is written for it: both consumers
below derive an empty allowlist from an empty directory, which is not the same thing as having no
allowlist mechanism.

## The shape

One file per exception, `<identifier>.json`, validated against `schema.json` by
`tests/test_cdm_security_exceptions.py`:

```json
{
  "identifier": "GHSA-xxxx-xxxx-xxxx",
  "affected_package": "some-dependency",
  "version_range": ">=1.0,<1.4",
  "risk": "what an attacker gets if this is exploited in THIS repository's use of the package",
  "reason": "why it is not fixed now, and what has to change for it to be fixed",
  "owner": "a person or team that answers for it",
  "expiry": "2026-12-31",
  "created": "2026-09-08",
  "references": ["https://github.com/advisories/GHSA-xxxx-xxxx-xxxx"]
}
```

The filename's stem MUST be the `identifier`. Two files could otherwise carry one identifier and
disagree, and which of them a consumer honoured would depend on directory order.

## What makes it an exception rather than a note

**One directory, two consumers, no second list.** The allowlists are DERIVED from these files at
run time and are never typed into a workflow:

- `gates/codeql_gate.py` reads this directory and treats a result as excepted only when a valid,
  unexpired file names its rule id. Run it against a downloaded SARIF and it behaves identically
  to the CI step, because it is the same code.
- the `supply-chain` job in `.github/workflows/ci.yml` runs
  `python gates/codeql_gate.py --emit-pip-audit-ignores` and passes the result to `pip-audit`.

A list written into a workflow file is a list that stops matching this directory the first time
somebody edits one and not the other, and the divergence is silent in the direction that matters:
a finding suppressed by a workflow line whose exception has expired.

## Expiry is enforced, not documented

`tests/test_cdm_security_exceptions.py` fails **the whole suite** on the day an `expiry` passes.
There is no grace period, no environment flag and no skip. That is deliberate and it is the point
of the mechanism: the failure mode §45 names is an exemption that outlives the reason for it, and
the only enforcement that catches it is one that fires without anybody choosing to look.

An expired exception is repaired by fixing the finding or by writing a NEW exception with a new
`expiry` and a `reason` that says what changed. It is not repaired by moving the date.

## What is not an exception

- A finding below the blocking threshold. Those are reported and not blocked (see
  `gates/codeql_gate.py`'s header for the threshold and M's ruling that set it); nothing needs to
  be written here for them.
- A false positive in a CodeQL query. That is a query problem: suppress it at the source with
  CodeQL's own mechanism, or narrow the query, and say so in the pull request. An exception here
  would record a risk that does not exist and would expire pointlessly.
- A secret in the history. `.gitleaks.toml` has its own allowlist, deliberately empty, and its
  own reasoning in its header. Nothing in this directory affects the secret scanner.
