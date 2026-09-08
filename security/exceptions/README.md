# `security/exceptions/`

A documented, time-bounded decision **not to fix a security finding immediately**. SOIF Part 1
§45: "no permanent undocumented exemptions".

**There are two today, and both are about `docs/`.** `GHSA-w3rx-r6r6-pgpr.json` and
`GHSA-5p2g-fcmc-qvqq.json` cover `image-size`'s two high npm advisories: a denial of service in
its ICNS, JXL and HEIF parsers, reachable only when Docusaurus measures an image, at documentation
build time, in a toolchain the Python distribution does not carry. They were written on
2026-09-08 by round PB, they have no upstream fix to take, and they expire **2026-11-07** — sixty
days, on M's ruling of the same day, with removal on the first upstream fix rather than at expiry.
Each file's `upstream_status` says which event that would be.

Until 2026-09-08 this paragraph read "there are none today", and the empty state is still the one
the tooling is written for: both consumers below derive an EMPTY allowlist from an empty
directory, which is not the same thing as having no allowlist mechanism. Two tests in other
modules had encoded that emptiness as a constant and went red the moment these files landed —
`tests/test_cdm_codeql_gate.py` and `tests/test_cdm_release_notes.py`, both now deriving from the
directory instead. If you are reading this because you are about to add the third file, that is
the failure mode to look for: a test that passes because the directory is empty rather than
because the derivation is right.

`pip-audit --strict` over the installed Python environment reports *No known vulnerabilities
found*, and nothing in this directory excepts a Python finding.

## The shape

One file per exception, `<identifier>.json`, validated against `schema.json` by
`tests/test_cdm_security_exceptions.py`:

```json
{
  "identifier": "GHSA-xxxx-xxxx-xxxx",
  "affected_package": "some-dependency",
  "version_range": ">=1.0,<1.4",
  "risk": "what an attacker gets if this is exploited in THIS repository's use of the package",
  "reason": "why the exception is being granted",
  "mitigation": "the compensating controls in force NOW, present tense and checkable",
  "upstream_status": "whether a fix exists, the advisory's state, and the event that ends this",
  "owner": "a person or team that answers for it",
  "expiry": "2026-12-31",
  "created": "2026-09-08",
  "references": ["https://github.com/advisories/GHSA-xxxx-xxxx-xxxx"]
}
```

The filename's stem MUST be the `identifier`. Two files could otherwise carry one identifier and
disagree, and which of them a consumer honoured would depend on directory order.

**The four prose fields are four for a reason** (M's ruling, 2026-09-08T16:45:00Z, which added the
last two and made them required): `risk` is the security IMPACT and nothing else; `reason` is why
the exception is being GRANTED; `mitigation` is the concrete compensating controls IN FORCE NOW;
`upstream_status` is whether a fix exists, what state the upstream issue or advisory is in, and
**the event that will trigger removal**. With only the first two, a file can state a risk and a
reason and say nothing about what holds the risk down or what would end the exception — and the
first draft of the two files in this directory did exactly that, with both buried inside `reason`.
An incomplete file now fails validation, field by field:
`tests/test_cdm_security_exceptions.py::test_an_incomplete_exception_file_fails_validation_field_by_field`
omits each required key in turn and requires the refusal to name it.

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
