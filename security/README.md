# `security/`

The repository's security working files. **The policy itself is `SECURITY.md` at the root**, where
GitHub looks for it and where a reporter will find it; this directory holds what the policy points
at rather than a second copy of it.

## What lives here

- `README.md` — this file.
- `exceptions/` — **not present yet.** Round P6 introduces it: a documented, dated, owner-named
  exception for a dependency finding that will not be fixed immediately, one file per exception.
  The directory is named here rather than created empty, because an empty directory is not
  something git records and a reader would find nothing.

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

If a secret does reach this repository, the response is to **rotate it first** and clean up
second. Rewriting history is not a remedy: the object has already been fetched by anybody watching,
and treating the rewrite as the fix is how a live credential stays live.
