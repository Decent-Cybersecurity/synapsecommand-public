# Security policy

**This document covers the `synapse-cdm` distribution and this repository.** It is the
repository-level policy `spec/governance/SECURITY-REPORTING.md` records as outstanding work; that
document's own scope — reports about the SC-OES specification's text — is narrower, and it stays
where it is.

Dated 2026-09-08. Every reading in the controls table below was taken on that date and the command
that took it is named beside it.

## Supported versions

| version | supported | what that means |
|---|---|---|
| `2.x` | **yes** | the current line. Security fixes are made here and released from here. |
| `1.x` | **no** | superseded by 2.0.0. No security fix will be backported to a 1.x release. |

**This is a statement about RELEASES, not about data.** A 1.x *reader* is not abandoned by the
above: `version.compatible()` accepts an object whose `schema_version` shares its major, and
`RELEASE_NOTES.md`'s 2.0.0 notes set out what a 1.x consumer must do about the two keys that made
that release a major. Support is about which distribution receives a fix; compatibility is about
which objects a reader may accept, and the two are deliberately different questions.

`PACKAGE_VERSION` and the CDM's `SCHEMA_VERSION` are separate axes and both appear in
`VERSIONING.md`'s table with the line each is declared on. The supported line above is the
PACKAGE's.

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting.** Open
<https://github.com/Decent-Cybersecurity/synapsecommand-public/security/advisories/new> and file a
draft advisory. It is private to you and to the maintainers, it is the channel this repository
monitors, and it is the path to a CVE: a draft advisory becomes a published GHSA, and a GHSA is
where a CVE identifier is requested and attached.

**If you cannot use it, write to `security@decentcybersecurity.eu`.** The mailbox is monitored by
Decent Cybersecurity. It is a second channel and not the preferred one, because an email thread
has no shared state with the advisory a fix eventually needs.

> **MUST NOT: do not report a vulnerability through a public GitHub Issue, a pull request, a
> discussion, or any other public channel.** A public report is a disclosure, made before anyone
> has had the chance to fix what it discloses, and it cannot be taken back.

No personal address is published here, deliberately. A named individual's mailbox is a channel
that stops working when that individual does, and a reporter has no way to find out that it has.

### What to expect, and what these figures are

| | target | what it is |
|---|---|---|
| acknowledgement | **5 business days** | a human has read the report and says so |
| coordinated disclosure | **90 calendar days** from the initial report | the default embargo |

**These are targets and not guarantees.** They say what Decent Cybersecurity aims at; they are not
a contractual commitment and a reporter should not plan on the assumption that they are.

- Disclosure may happen **earlier** by agreement, when a fix is ready and both sides are content.
- The date may be **extended** by mutual agreement where an issue is genuinely complex.
- A vulnerability that is **actively exploited**, or exceptionally high-risk, may need an
  accelerated process — including release before a fix is complete, where warning is the better
  protection.
- Decent Cybersecurity will keep the reporter informed of material status changes where
  practicable.

### What a report should contain

Guidance, not a requirement — a report missing any of it is still worth making.

- The file and line, or the document and clause.
- What an adversary gains, and what they need in order to gain it.
- A concrete case: an input, and the wrong behaviour it produces.
- Which released version, or which commit, you observed it on.

## Scope

**In scope.**

- The `synapse-cdm` distribution published on PyPI, and the code in `packages/cdm/`.
- The adapters: a payload that makes one crash, hang, consume unbounded memory, or emit a CDM
  object that misrepresents its source.
- The bounds and refusals this repository publishes as active — an input larger than a declared
  `max_input_bytes` that is accepted anyway, a conformance check that passes where it should fail.
- This repository's own workflows under `.github/workflows/`, and the artefacts they produce:
  the wheel, the sdist, the generated schemas, the manifests, the evidence records.
- A published claim that overstates what this repository does. A document asserting an assurance
  the code does not provide is a security defect in the document.

**Out of scope, each with the reason.**

- **The content of the third-party standards this repository pins.** A defect in EUROCONTROL's,
  NATO's or MISB's own specification belongs to its publisher. A defect in this repository's
  *implementation* of one is in scope, and so is a transcription that says something the
  document does not.
- **The documentation site's hosting**, and anything belonging to GitHub Pages.
- **PyPI and GitHub platform issues.** Report those to PyPI and to GitHub.
- **A finding that requires the operator to load a hostile adapter.** `load_adapter` accepts
  `module:ClassName` and imports it (`packages/cdm/synapse_cdm/adapter.py:439`). Choosing which
  module to import is the operator's trust decision, and code an operator has decided to import
  runs with the operator's privileges by construction. An adapter *shipped in this repository*
  behaving badly is in scope; the mechanism that lets an operator load their own is not.
- **A `.parsed.json` twin larger than the adapter's declared `max_input_bytes`.** The bound is on
  the octets an adapter is handed. A caller holding a parsed document has already done the parse
  the bound exists to prevent — see `docs/docs/security/parser-safety.mdx`, which states this as
  a rule rather than leaving it to be inferred.

## Telemetry: none

**The package makes no network call.** No telemetry, no licence check, no remote registry lookup,
no update ping, no error reporting. An adapter that needs data from a network is handed it as a
payload by its caller, who is the party entitled to decide what to connect to.

This is not an assurance offered on trust. `tests/test_cdm_no_network.py` proves it twice: it
sweeps every module under `synapse_cdm` for an import of any networking module — the syntax tree,
so an import inside a function body is caught as well as one at the top — and then it takes
`socket.socket` away and runs the conformance suite over all fourteen adapters underneath, which
exits 0 with no socket obtainable in the process.

What that test does **not** claim: that no dependency of this package opens a socket. `pydantic`
is a dependency and is not audited by it. The claim is about this package's own code.

## Controls

Every row is a reading taken on 2026-09-08 with the command beside it, and every row is either
active or says in words what is not.

| control | state | reading |
|---|---|---|
| GitHub secret scanning | **active** | `gh api repos/Decent-Cybersecurity/synapsecommand-public --jq .security_and_analysis` → `secret_scanning: enabled` |
| Secret-scanning push protection | **active** | same call → `secret_scanning_push_protection: enabled` |
| Private vulnerability reporting | **active** | `gh api .../private-vulnerability-reporting` → `{"enabled": true}` |
| Secret scanning in CI (gitleaks) | **active** | `.github/workflows/ci.yml`, job `secrets`: gitleaks 8.30.1, pinned by the release artefact's SHA-256, `--redact`, over `--all` history at `fetch-depth: 0` |
| No secret in the repository's history | **active** | `gitleaks git . --redact --config .gitleaks.toml` → 246 commits scanned, no leaks found; `--log-opts "origin/main..HEAD"` over the SOIF Part 1 arc, taken at the commit this row ships in → 7 commits scanned, no leaks found. Both are gitleaks 8.30.1's own counts; see `.gitleaks.toml`'s header for why they are not `git rev-list` counts. |
| Input bounds on every adapter | **active** | all fourteen declare `capabilities.limits.max_input_bytes` with its basis; enforced in `Adapter.__init_subclass__` before decode; conformance check O is required in CI |
| Parser-safety policy | **active** | `docs/docs/security/parser-safety.mdx`, with the audit of all fourteen |
| Signed commits | **active** | every commit on the SOIF Part 1 branch is `git commit -s -S`; DCO sign-off is the repository's policy, recorded in `CONTRIBUTING.md` |
| Dependabot security updates | **not enabled in this round** | same call → `dependabot_security_updates: disabled`. Dependency scanning, `pip-audit`, CodeQL and SBOMs are the next round's subject, and none of them is claimed here. |
| Secret-scanning non-provider patterns | **not enabled in this round** | same call → `secret_scanning_non_provider_patterns: disabled`. Not requested for this round; the gitleaks job in CI is the broader-pattern layer. |
| Secret-scanning validity checks | **not enabled in this round** | same call → `secret_scanning_validity_checks: disabled`. |
| Cryptographic signing of CDM objects | **not provided** | none exists, deliberately. `tests/test_cdm_boundary.py` forbids `cryptography`, `hmac`, `secrets`, `ssl` and `nacl` in the translation layer entirely, and `hashlib` everywhere but the evidence module. `docs/adr/0006-canonicalization-and-integrity.md` records why. |
| Defence against a producer asserting false semantics | **not provided** | the CDM carries a producer's claims and does not verify them. Producer authentication and trust are the deployment's. |

## Handling a report

- The report is assessed against the trust boundaries in
  `spec/sc-oes/14-security-considerations.md`, and the assessment says which boundary the defect
  sits on.
- A defect that is a document overclaiming is corrected **at the sentence that overclaims**, never
  by weakening the surrounding text until the claim becomes defensible.
- A fix to normative text is classified under `spec/governance/SC-OES-GOVERNANCE.md`. A security
  motive does not make a substantive change editorial.
- A dated record that has become false gains a dated correction beside it, and is not rewritten.
- Where a fix affects a published artefact, the advisory names the artefact and the version.
