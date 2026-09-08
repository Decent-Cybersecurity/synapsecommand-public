# `security/`

The repository's security working files. **The policy itself is `SECURITY.md` at the root**, where
GitHub looks for it and where a reporter will find it; this directory holds what the policy points
at rather than a second copy of it.

## What lives here

- `README.md` — this file.
- `exceptions/` — **present since round P6 (2026-09-08).** A documented, dated, owner-named
  exception for a dependency or static-analysis finding that will not be fixed immediately, one
  file per exception. It holds `schema.json`, its own `README.md` and — today — **no exception
  file at all**, which is a reading rather than an omission: `pip-audit --strict` reported no
  known vulnerabilities on 2026-09-08 and no CodeQL analysis of this repository has been read yet.
  `exceptions/README.md` is where the mechanism is written down; the short version is that an
  `expiry` in the past fails the whole suite on the day it passes, and that both consumers derive
  their allowlist from the directory rather than from a list in a workflow.

  *(The sentence this replaces said "not present yet. Round P6 introduces it", and gave as its
  reason that "an empty directory is not something git records and a reader would find nothing".
  That reason held while the directory would have been empty. It now carries two files, so git
  records it and a reader finds the schema and the rules.)*

## What does not live here, and will not

> **Secrets never.** No key, no token, no credential, no certificate with a private half, in any
> form, including an example, a redacted one, or one that has been rotated.

The reasons, stated rather than assumed:

- A rotated credential is still evidence — of a naming scheme, of an issuer, of where else the
  same pattern is used.
- An "example" secret is indistinguishable from a real one to every scanner, so it trains the
  people reading the alerts to dismiss them.
- This repository's history is public and permanent. A secret committed here is a secret disclosed
  at the moment of the push, and deleting the file does not undo it — the object stays in the
  pack.

Two layers enforce it and neither is advisory: GitHub secret-scanning **push protection** is
enabled on this repository, so a push carrying a recognised credential is refused before it lands;
and the `secrets` job in `.github/workflows/ci.yml` runs gitleaks over the full history reachable
from every push, failing the build on any finding. `.gitleaks.toml` holds the allowlist, which is
empty — see that file's header for the reading that made it empty.

## The supply chain is a separate subject with a separate page

Round P6 added Dependabot, dependency review, `pip-audit`, CodeQL with a gate, SBOMs and build
attestation. None of that is about secrets and none of it is described here:
`docs/docs/security/supply-chain.mdx` is the page, `SECURITY.md`'s controls table carries the
readings, and `exceptions/` above is the one documented way past a blocking finding.

If a secret does reach this repository, the response is to **rotate it first** and clean up
second. Rewriting history is not a remedy: the object has already been fetched by anybody watching,
and treating the rewrite as the fix is how a live credential stays live.
