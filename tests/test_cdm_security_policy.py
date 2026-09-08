"""SECURITY.md, `security/`, `.gitleaks.toml` and the CI job — the documents, against the tree.

REPOSITORY-BOUND, and the classification is the whole of it: every path this module reads is at
the repository root or under `.github/` and none of them ships in the wheel. It is the half of the
security baseline a consumer of the distribution never sees, which is exactly why it needs a test
of its own — a policy nobody re-derives is a policy that goes stale at the first round that moves
what it describes.

WHAT IT REFUSES TO CHECK
------------------------
Whether the platform settings are actually on. That is a live API reading, it belongs to a gate
and not to the suite, and a test that mocked it would assert its own mock. SECURITY.md's controls
table names the command for each row so a reader can take the reading themselves; this module
checks that the row NAMES a command and does not check what the command answers today.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
POLICY = REPO / "SECURITY.md"
GITLEAKS = REPO / ".gitleaks.toml"
CI = REPO / ".github" / "workflows" / "ci.yml"
SECURITY_DIR = REPO / "security"
PARSER_SAFETY = REPO / "docs" / "docs" / "security" / "parser-safety.mdx"
SUPPLY_CHAIN = REPO / "docs" / "docs" / "security" / "supply-chain.mdx"
CODEQL = REPO / ".github" / "workflows" / "codeql.yml"
DEP_REVIEW = REPO / ".github" / "workflows" / "dependency-review.yml"
RC_BUILD = REPO / ".github" / "workflows" / "rc-build.yml"
DEPENDABOT = REPO / ".github" / "dependabot.yml"
WORKFLOWS = REPO / ".github" / "workflows"

#: M's F5.1 ruling. The address is published, so it is pinned: a typo here is a report nobody
#: receives, and no other test in this repository would notice one.
CONTACT = "security@decentcybersecurity.eu"


def test_the_policy_is_at_the_root_where_github_looks_for_it():
    assert POLICY.is_file(), "SECURITY.md must be at the repository root: GitHub reads it there"


@pytest.mark.parametrize("needle", [
    "## Supported versions",
    "## Reporting a vulnerability",
    "## Scope",
    "## Telemetry: none",
    "## Controls",
    "## Handling a report",
])
def test_the_policy_carries_every_section_the_specification_requires(needle):
    assert needle in POLICY.read_text(), needle


def test_private_vulnerability_reporting_is_offered_before_the_address():
    """M's F5.1: GHSA first, the mailbox second. Order is the substance, not the presentation —
    a reporter reads until they find a channel and uses the first one they see."""
    body = POLICY.read_text()
    advisory = body.index("security/advisories/new")
    address = body.index(CONTACT)
    assert advisory < address, \
        "SECURITY.md names the email address before GitHub private vulnerability reporting"


def test_the_policy_forbids_public_issues_as_a_must_not():
    body = POLICY.read_text()
    assert "MUST NOT" in body and "public GitHub Issue" in body
    forbidding = next(line for line in body.splitlines() if "MUST NOT" in line and "public" in line)
    assert forbidding.startswith(">"), \
        "the prohibition is prose in the middle of a paragraph; it is a normative statement"


def test_the_policy_states_both_periods_as_targets_and_not_guarantees():
    body = POLICY.read_text()
    assert "5 business days" in body
    assert "90 calendar days" in body
    assert "targets and not guarantees" in body


def test_the_policy_names_no_personal_address():
    """M's F5.1: "avoid publishing personal employee addresses". One address, and it is a role."""
    found = set(re.findall(r"[\w.+-]+@[\w.-]+\.\w+", POLICY.read_text()))
    assert found == {CONTACT}, found


def test_the_supported_versions_table_does_not_promise_a_1_x_backport():
    body = POLICY.read_text()
    row = next(line for line in body.splitlines() if line.startswith("| `1.x` |"))
    assert "**no**" in row, row
    assert "No security fix will be backported" in body


def test_the_out_of_scope_list_cites_the_operator_s_trust_decision():
    """The `load_adapter` row. An out-of-scope item with no reason is a refusal to look."""
    body = POLICY.read_text()
    assert "load_adapter" in body
    assert "adapter.py:439" in body, "the citation has moved; re-derive it rather than dropping it"
    source = (REPO / "packages" / "cdm" / "synapse_cdm" / "adapter.py").read_text().splitlines()
    assert "def load_adapter" in source[438], source[438]


def test_every_control_row_is_active_or_says_what_it_is_not():
    """§42: every row of the controls table reads active-with-a-reading, or names what is absent.

    A row that said neither would be the table's whole failure mode: a control listed, a reader
    assuming it is on, and nothing anywhere saying it is not.
    """
    body = POLICY.read_text()
    table = body[body.index("## Controls"):body.index("## Handling a report")]
    rows = [line for line in table.splitlines()
            if line.startswith("|") and not line.startswith("| control") and "---" not in line]
    assert len(rows) >= 10, rows
    undecided = [r for r in rows if "**active**" not in r and "**not " not in r]
    assert not undecided, undecided
    thin = [r for r in rows if len(r.split("|")[3].strip()) < 30]
    assert not thin, f"these control rows state no reading: {thin}"


def test_the_telemetry_claim_cites_the_test_that_proves_it():
    body = POLICY.read_text()
    assert "tests/test_cdm_no_network.py" in body
    assert (REPO / "tests" / "test_cdm_no_network.py").is_file()


def test_the_security_directory_exists_and_forbids_secrets_in_words():
    assert (SECURITY_DIR / "README.md").is_file()
    body = (SECURITY_DIR / "README.md").read_text()
    assert "Secrets never" in body
    assert "exceptions/" in body, "the directory P6 fills is named here or a reader finds nothing"


def test_the_gitleaks_config_declares_no_allowlist_entry():
    """The allowlist is empty by reading (see the file's header), and this is what keeps it so.

    An entry cannot be added without this test being changed too, which is the point: §39 requires
    an allowlist to be "narrow and documented", and the cheapest way to widen one is quietly.
    """
    body = GITLEAKS.read_text()
    assert "[extend]" in body and "useDefault = true" in body
    # The comment half of this file EXPLAINS the empty allowlist at length, so the assertions are
    # over the declarations only. A test that read the prose would fail on the paragraph saying
    # there is nothing to allowlist.
    declarations = "\n".join(line for line in body.splitlines()
                             if line.strip() and not line.lstrip().startswith("#"))
    assert "[[allowlists]]" not in declarations
    assert "[allowlist]" not in declarations
    for key in ("paths", "regexes", "stopwords", "commits"):
        assert re.search(rf"^\s*{key}\s*=", declarations, re.M) is None, key


def test_ci_scans_the_history_for_secrets_and_cannot_pass_by_ignoring_the_exit_status():
    body = CI.read_text()
    assert "gitleaks" in body
    assert "fetch-depth: 0" in body
    assert "--redact" in body
    assert "--config .gitleaks.toml" in body
    assert "--log-opts \"--all\"" in body
    scan = next(line for line in body.splitlines() if "./gitleaks git" in line)
    assert "|| true" not in scan and "continue-on-error" not in body, scan


def test_the_gitleaks_binary_is_pinned_by_version_and_by_checksum():
    """§39 and P6's rule: a tag is a moving target on somebody else's account.

    The upstream ACTION is unusable here — it requires a paid licence for an organization-owned
    repository — so the release artefact is pinned instead, and pinned harder: the version AND the
    SHA-256 of the tarball, verified by `sha256sum -c` before anything is executed.
    """
    body = CI.read_text()
    version = re.search(r"GITLEAKS_VERSION: (\d+\.\d+\.\d+)", body)
    digest = re.search(r"GITLEAKS_SHA256: ([0-9a-f]{64})", body)
    assert version and digest, body[-2000:]
    assert "sha256sum -c" in body
    assert body.index("sha256sum -c") < body.index("./gitleaks version"), \
        "the checksum is verified after the binary has already been run"
    steps = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    assert "gitleaks/gitleaks-action" not in steps, \
        "the action is named in a STEP; it needs an organization licence and would fail for that"


def test_conformance_check_o_is_required_in_ci():
    """P5's bounds are only enforced in CI if O is in the required set. It is, for all fourteen."""
    body = CI.read_text()
    assert "--require A,B,C,D,F,G,H,J,K,L,O" in body
    assert "--require A,B,C,D,F,G,H,J,K,L\n" not in body


def test_the_parser_safety_policy_exists_and_covers_the_three_families():
    body = PARSER_SAFETY.read_text()
    for heading in ("## 2. XML", "## 3. Archives", "## 4. SQLite", "## 5. Timeouts"):
        assert heading in body, heading
    plain = body.replace("**", "")
    for rule in ("MUST NOT resolve external entities",
                 "MUST NOT fetch an external DTD",
                 "enable_load_extension(False)",
                 "mode=ro"):
        assert rule in plain, rule


def test_the_parser_safety_audit_names_every_adapter_that_calls_a_parser():
    """The audit table against the grep it says it was taken with. A row that fell out of the
    table when a call was added would be the audit quietly narrowing."""
    adapters = REPO / "packages" / "cdm" / "synapse_cdm" / "adapters"
    calling = sorted(p.stem for p in adapters.glob("*.py")
                     if re.search(r"ET\.fromstring|json\.loads|zipfile|sqlite3|gzip|zlib",
                                  p.read_text()))
    body = PARSER_SAFETY.read_text()
    audit = body[body.index("## 7. The audit"):]
    missing = [name for name in calling if f"`{name}`" not in audit]
    assert not missing, f"these adapters call a parser and are not in the audit table: {missing}"


def test_the_sc_oes_reporting_document_records_that_the_channel_now_exists():
    """Its normative rule forbids naming a channel that has not been established, and its own
    status section said none was. Establishing one makes that section false, so it carries a dated
    correction rather than a rewrite — this repository's standing habit."""
    body = (REPO / "spec" / "governance" / "SECURITY-REPORTING.md").read_text()
    assert "Dated correction, 2026-09-08" in body
    flat = " ".join(body.split())
    assert "No dedicated private security reporting channel is established" in flat, \
        "the superseded statement was rewritten instead of corrected beside"
    assert flat.index("Dated correction, 2026-09-08") < \
        flat.index("No dedicated private security reporting channel"), \
        "the correction sits after the statement it corrects; a reader meets the false one first"


def test_the_readme_points_at_the_policy():
    body = (REPO / "README.md").read_text()
    assert "SECURITY.md" in body


# ------------------------------------------------------------------------------------------------
# Round P6, the supply chain (§43–§48). Added to THIS module rather than to a new one because the
# subject is identical to the one the header names: the repository's security prose against the
# tree, none of it inside the wheel. The workflow files are the tree, the page is the prose, and
# what follows is the comparison — a page describing a job that has been renamed is the failure
# mode, and it is silent.
# ------------------------------------------------------------------------------------------------

def test_the_supply_chain_page_exists_and_covers_the_five_layers():
    assert SUPPLY_CHAIN.is_file()
    body = SUPPLY_CHAIN.read_text()
    for needle in ("Dependabot", "Dependency review", "pip-audit", "CodeQL",
                   "security/exceptions/", "attestation", "SPDX", "CycloneDX"):
        assert needle in body, f"the supply-chain page does not mention {needle!r}"


def test_every_job_the_page_names_is_a_job_the_workflow_declares():
    """The chain table in `docs/docs/security/supply-chain.mdx` §1 against `rc-build.yml`.

    §47 draws a provenance chain and the page claims a JOB realises each arrow. A job renamed in
    the workflow leaves the page describing a workflow that no longer exists, and nothing about
    the page's own prose changes when that happens — the same shape as the parks table's
    set-claims, which is the failure `gates/parks_table.py` is named for.
    """
    page = SUPPLY_CHAIN.read_text()
    declared = set(re.findall(r"^  ([a-z][a-z0-9-]*):$", RC_BUILD.read_text(), re.M))
    assert {"qualify", "build", "attest"} <= declared, sorted(declared)
    chain = page[page.index("## 1. The chain"):page.index("## 2. Five scanners")]
    named = set(re.findall(r"`([a-z][a-z0-9-]*)`(?=,| declares| needs)", chain))
    unknown = sorted(named - declared)
    assert not unknown, (
        f"the page's chain table names job(s) rc-build.yml does not declare: {unknown}; the "
        f"workflow declares {sorted(declared)}")


def test_the_page_names_the_supply_chain_job_ci_actually_has():
    ci = CI.read_text()
    assert re.search(r"^  supply-chain:$", ci, re.M), (
        "ci.yml has no `supply-chain` job. ARCHITECTURE.md §7's job table names it as round P6's")
    assert "job `supply-chain`" in SUPPLY_CHAIN.read_text()


def test_the_threshold_is_one_number_in_one_place():
    """7.0 lives in `gates/codeql_gate.py`; the page and the policy quote it, never redefine it.

    Two thresholds is the arrangement where a gate blocks at one number and the documentation
    promises another, and the direction that goes wrong is the documentation promising the
    stricter one.
    """
    gate = (REPO / "gates" / "codeql_gate.py").read_text()
    assert re.search(r"^HIGH = 7\.0$", gate, re.M), "the gate's HIGH floor is not 7.0"
    assert re.search(r"^CRITICAL = 9\.0$", gate, re.M)
    for path in (SUPPLY_CHAIN, POLICY):
        body = path.read_text()
        assert "7.0" in body, f"{path.name} does not state the threshold the gate enforces"
    codeql = CODEQL.read_text()
    numeric = [line for line in codeql.splitlines()
               if "security-severity" in line and not line.lstrip().startswith("#")]
    assert not numeric, (
        f"codeql.yml compares security-severity itself: {numeric}. The threshold is "
        "gates/codeql_gate.py's, and a second copy in a workflow is a second thing to keep in step")


def test_every_action_in_every_workflow_is_pinned_to_a_full_commit_sha():
    """§47's supply chain starts with the actions this repository runs.

    A tag is a moving target on somebody else's account, and `github-actions` is in Dependabot's
    configuration precisely because a SHA pin is the staleness nobody notices by reading.
    """
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("uses:"):
                continue
            ref = stripped.split("uses:", 1)[1].split("#")[0].strip()
            if "@" not in ref or not re.fullmatch(r"[0-9a-f]{40}", ref.split("@", 1)[1]):
                offenders.append(f"{path.name}:{number}: {ref}")
    assert not offenders, offenders


def test_the_only_job_that_can_sign_is_the_attest_job():
    """`id-token: write` and `attestations: write` in one job, in one file, and nowhere else.

    §47's "avoid long-lived signing secrets where a safer OIDC mechanism is available" is only
    worth anything if the OIDC token is not reachable from everything: a job that can mint an
    identity token can attest bytes nothing gated.
    """
    holders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped in ("id-token: write", "attestations: write"):
                holders.append((path.name, number, stripped))
    files = {name for name, _, _ in holders}
    assert files <= {"rc-build.yml", "publish.yml"}, holders
    assert {"id-token: write", "attestations: write"} <= {
        what for name, _, what in holders if name == "rc-build.yml"}, holders


def test_no_workflow_widens_its_top_level_permissions():
    """Every workflow starts read-only; a write is declared on the job that needs it.

    The failure this prevents is a permission granted at the top of a file and inherited by a job
    added later — which is how a pull request from a fork ends up able to write.
    """
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        top = re.search(r"^permissions:\n((?:  .*\n)+)", text, re.M)
        assert top, f"{path.name} declares no top-level permissions block"
        for line in top.group(1).splitlines():
            if line.strip() and not line.strip().endswith(": read"):
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, offenders


def test_dependabot_covers_the_three_manifest_locations_that_exist():
    """And the directories are the ones with a manifest in them, which is a tree reading.

    A Dependabot entry pointing at a directory with no manifest is reported as an error on a page
    nobody watches, so the paths are checked against the files rather than against the intent.
    """
    body = DEPENDABOT.read_text()
    for ecosystem, directory, manifest in (
        ("pip", "/packages/cdm", "packages/cdm/pyproject.toml"),
        ("github-actions", "/", ".github/workflows"),
        ("npm", "/docs", "docs/package-lock.json"),
    ):
        assert f"package-ecosystem: {ecosystem}" in body, ecosystem
        assert f"directory: {directory}\n" in body, (ecosystem, directory)
        assert (REPO / manifest).exists(), (
            f"dependabot.yml declares {ecosystem} at {directory} but {manifest} does not exist")


def test_dependency_review_is_pull_request_only_and_the_page_says_so():
    """The limit is the point of the row, and it must be written where a reader meets the green.

    This campaign pushes directly, so dependency review does not run on the commits that built
    the package. A page that listed it as a dependency scanner without that sentence would be
    describing coverage this repository does not have.
    """
    review = DEP_REVIEW.read_text()
    assert re.search(r"^on:\n  pull_request:", review, re.M), (
        "dependency-review.yml triggers on more than pull_request, so the page's limit is wrong")
    page = SUPPLY_CHAIN.read_text()
    assert "only on pull requests" in page or "exercises only on pull requests" in page, (
        "the supply-chain page does not state that dependency review runs only on pull requests")

