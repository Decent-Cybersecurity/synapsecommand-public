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
