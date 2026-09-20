"""Audit remediation F08: the workflows as a required-checks surface, and the governance audit.

WHAT IS HELD HERE, AND WHY IT IS THREE THINGS
---------------------------------------------
1. **The workflows**, read as text, for the properties a `required_status_checks` rule needs and
   the properties a pull request from a stranger needs: a `pull_request` trigger with no `paths`
   filter on every workflow that would carry a required check (a path-filtered required check
   never reports and the pull request waits forever), no `pull_request_target`, no `secrets.*`
   reference, no untrusted expression spliced into a `run:` script, every action pinned with a
   version comment beside the SHA, and check names that are DERIVED from the files rather than
   typed — the strings a ruleset has to match exactly.
2. **`gates/governance_audit.py`**, whose three columns must never blur: DOCUMENTED is held to
   `PUBLICATION.md`'s sentences, PROPOSED is held to the derivation above and to its own shape
   rules, and LIVE is `UNVERIFIED` — exit 3, never a pass — whenever no credential is present.
   The live path is exercised against RECORDED responses, shaped after the API readings
   `PUBLICATION.md` records (id 21205830, `deletion` + `non_fast_forward`, `bypass_actors: []`);
   they were not captured from the API in this session, which had no credential, and the module
   says so rather than pretending otherwise. `gh` is on this machine's PATH and is never invoked:
   the subprocess test scrubs PATH and the unit tests inject the probe.
3. **The apply verb**, which this remediation delivered and did NOT run: idempotent (an identical
   live ruleset writes nothing), one ruleset by name, readback verified, and refused outright for
   a proposal that would reverse the advisory-DCO ruling while both documents still carry it.

None of this reads the live repository. Remote enforcement is BLOCKED_ADMIN_ACTION in
`docs/audit-remediation-report.md`, and the runbook is the procedure.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

from gates import governance_audit as ga

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
RULESETS = REPO / "docs" / "governance" / "rulesets"
RUNBOOK = REPO / "docs" / "governance" / "RUNBOOK.md"
ADR = REPO / "docs" / "adr" / "0011-repository-governance-enforcement.md"
PUBLICATION = REPO / "PUBLICATION.md"
REGISTER = REPO / "docs" / "audit-remediation-report.md"
SLUG = "Decent-Cybersecurity/synapsecommand-public"

#: The workflows that carry a check a ruleset could require. `publish.yml` and `rc-build.yml`
#: never run on a pull request and are deliberately outside this set.
PULL_REQUEST_WORKFLOWS = ("ci.yml", "codeql.yml", "dependency-review.yml")

#: Expression roots that carry text somebody outside the repository chose.
UNTRUSTED = ("github.event.", "inputs.", "github.head_ref", "github.ref_name", "github.actor",
             "github.triggering_actor")

#: The only expression shape allowed inside a `run:` script: an output this repository's own
#: steps or jobs produced. Anything else goes through `env:`.
OWN_OUTPUT = re.compile(r"^\$\{\{\s*(?:steps|needs)\.[a-z0-9_-]+\.outputs\.[a-z0-9_-]+\s*\}\}$")


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text()


# =============================================================================== 1. the workflows
@pytest.mark.parametrize("name", PULL_REQUEST_WORKFLOWS)
def test_every_check_carrying_workflow_triggers_on_pull_request_without_a_path_filter(name):
    """A required check that a path filter skips never reports, and the pull request waits forever."""
    triggers = ga.triggers_of(_text(name))
    assert "pull_request" in triggers, f"{name} has no pull_request trigger: {sorted(triggers)}"
    for event, body in triggers.items():
        assert "paths" not in body, f"{name}: `{event}` carries a paths filter — a deadlock once "
        "its checks are required"


@pytest.mark.parametrize("name", PULL_REQUEST_WORKFLOWS)
def test_a_pull_request_branch_filter_where_present_includes_the_default_branch(name):
    body = ga.triggers_of(_text(name))["pull_request"]
    if "branches:" in body:
        assert re.search(r"^\s*-\s*main\s*$", body, re.M), (
            f"{name} filters pull_request by branch and the list omits main: {body!r}")


def test_the_trigger_reader_is_linear_on_a_run_of_blank_lines_after_on():
    """CodeQL py/redos on the `on:` block regex (2026-09-20): `\\s*` and the outer `\\n` both
    absorbed blank lines, so an `on:` followed by many blank lines and then a line no `^\\S`
    lookahead accepts backtracked exponentially (~3.3x per two lines; 20 lines took 48 ms, 40
    would take hours). The reader is now a line walker. This runs it in a subprocess so a
    regression is a clean timeout, not a hung suite; 400 lines must answer within 10 s."""
    script = ("from gates import governance_audit as ga\n"
              "text = 'on:\\n' + '\\n' * 400 + ' x'\n"
              "assert ga.triggers_of(text) == {}\n"
              "print('ok')\n")
    done = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True,
                          text=True, timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


@pytest.mark.parametrize("text, expected", [
    # the ordinary block: two-space keys with their filters, ended by the next top-level key
    ("name: x\non:\n  push:\n    branches: [main]\n  pull_request:\njobs:\n  a:\n",
     {"push": "\n    branches: [main]\n", "pull_request": "\n"}),
    # blank and whitespace-only lines inside the block belong to the event above them
    ("on:\n  push:\n\n    paths: [a]\n  \n  pull_request:\n    branches: [main]\npermissions:\n",
     {"push": "\n\n    paths: [a]\n  \n", "pull_request": "\n    branches: [main]\n"}),
    # a comment line inside the block is not an event and not part of one
    ("on:\n  push:\n  # pull_request:\n  workflow_dispatch:\njobs:\n",
     {"push": "\n", "workflow_dispatch": "\n"}),
    # inline event text on the head line is kept
    ("on:\n  workflow_dispatch: {}\njobs:\n", {"workflow_dispatch": "{}\n"}),
    # the block may end at a final unterminated top-level line
    ("on:\n  push:\njobs:", {"push": "\n"}),
    # no `on:` at a line start at all
    ("name: x\njobs:\n  a:\n    on: 1\n", {}),
    # an `on:` with nothing indented under it before the next key is not a block
    ("on:\njobs:\n  a:\n", {}),
    # a block that runs to the end of the text has no `^\\S` after it and never matched
    ("on:\n  push:\n", {}),
    ("on:\n  push:\n  pull_request:", {}),
    # a one-space line ends the block without being a top-level key: no match here...
    ("on:\n  push:\n x\njobs:\n", {}),
    # ...but a later `on:` line that does close properly still matches
    ("on:\n  push:\n x\non:\n  pull_request:\njobs:\n", {"pull_request": "\n"}),
    # the flagged shape itself: blank lines then a one-space line
    ("on:\n" + "\n" * 8 + " x\n", {}),
    ("on:\n" + "\n" * 8 + "jobs:\n", {}),
])
def test_the_trigger_reader_keeps_the_regex_language_on_the_block_edges(text, expected):
    """The line walker accepts exactly what the regex `^on:\\n((?:(?:  .*|\\s*)\\n)+?)(?=^\\S)`
    accepted: two-space or whitespace-only lines, at least one, ended by a line that begins
    with a non-space character. Each row is a decided edge; together they pin the language."""
    assert ga.triggers_of(text) == expected


def test_no_workflow_uses_pull_request_target_or_references_a_secret():
    """Fork safety in two lines: no privileged trigger, no secret to leak to a fork's code."""
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(ga.live_lines(path.read_text()), start=1):
            if "pull_request_target" in line or "secrets." in line:
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, offenders


def test_no_untrusted_expression_is_spliced_into_a_run_script():
    """`${{ inputs.reason }}` inside `run:` was the defect (rc-build.yml, closed 2026-09-20).

    An expression in a script is expanded into the script's TEXT before bash reads it; `env:` is
    the carrier. What remains inside `run:` blocks is limited to this repository's own outputs.
    """
    offenders, foreign = [], []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, expression in ga.run_block_expressions(path.read_text()):
            if any(root in expression for root in UNTRUSTED):
                offenders.append(f"{path.name}:{number}: {expression}")
            elif not OWN_OUTPUT.match(expression):
                foreign.append(f"{path.name}:{number}: {expression}")
    assert not offenders, offenders
    assert not foreign, (f"expressions inside run: scripts that are neither untrusted nor an own "
                         f"step/job output — carry them through env: instead: {foreign}")


def test_the_rc_build_reason_reaches_the_shell_through_env():
    text = _text("rc-build.yml")
    assert re.search(r"^\s+env:\n\s+REASON: \$\{\{ inputs\.reason \}\}", text, re.M), (
        "rc-build.yml no longer carries inputs.reason through env: REASON")
    assert 'echo "Reason: ${REASON}"' in text


def test_the_run_block_detector_sees_an_injection_and_ignores_the_env_carrier():
    """Not vacuous: a synthetic workflow with the defect is caught, the fixed shape is not."""
    bad = ("jobs:\n  j:\n    steps:\n      - run: |\n          echo ${{ github.event.pull_request.title }}\n"
           "      - run: echo ${{ inputs.reason }}\n")
    found = [e for _, e in ga.run_block_expressions(bad)]
    assert found == ["${{ github.event.pull_request.title }}", "${{ inputs.reason }}"], found
    good = ("jobs:\n  j:\n    steps:\n      - env:\n          T: ${{ github.event.pull_request.title }}\n"
            "        run: |\n          echo \"$T\"\n      - run: echo done\n")
    assert ga.run_block_expressions(good) == []


def test_every_action_pin_is_a_full_sha_with_the_version_it_stands_for_beside_it():
    """The SHA is what runs; the comment is what Dependabot and a reader read. Both, always."""
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("uses:"):
                continue
            ref, _, comment = stripped[len("uses:"):].partition("#")
            if not re.fullmatch(r"[0-9a-f]{40}", ref.strip().split("@", 1)[-1]):
                offenders.append(f"{path.name}:{number}: not a full SHA: {ref.strip()}")
            if not re.search(r"v\d", comment):
                offenders.append(f"{path.name}:{number}: no version comment beside the SHA")
    assert not offenders, offenders


@pytest.mark.parametrize("name", PULL_REQUEST_WORKFLOWS)
def test_no_job_in_a_check_carrying_workflow_is_conditional(name):
    """A job-level `if:` turns a required context into one that can be satisfied by not running."""
    for job, block in ga.job_blocks(_text(name)).items():
        head = block.split("steps:", 1)[0]
        assert not re.search(r"^    if:", head, re.M), f"{name}: job `{job}` carries an if:"


def test_check_contexts_are_derived_from_every_pull_request_job_with_the_matrix_expanded():
    contexts = ga.check_contexts()
    names = [c["context"] for c in contexts]
    assert len(names) == len(set(names)), "two jobs would report the same check name"
    assert not any("${{" in n for n in names), names
    suite = sorted(n for n in names if n.startswith("Suite, gates and manifests"))
    assert suite == [f"Suite, gates and manifests (Python 3.{minor})" for minor in (11, 12, 13, 14)]
    assert {"Analyse python", "Analyse javascript-typescript",
            "Newly introduced vulnerable dependencies"} <= set(names)
    ci_jobs = set(ga.job_blocks(_text("ci.yml")))
    assert {c["job"] for c in contexts if c["workflow"] == "ci.yml"} == ci_jobs
    assert {c["workflow"] for c in contexts} == set(PULL_REQUEST_WORKFLOWS)


def test_the_context_derivation_refuses_a_name_that_names_a_key_the_matrix_lacks(tmp_path):
    """A half-expanded context is a check name nothing will ever report; refuse, never guess."""
    (tmp_path / "w.yml").write_text(
        "name: W\non:\n  pull_request:\n\njobs:\n  j:\n    name: Leg ${{ matrix.os }}\n"
        "    strategy:\n      matrix:\n        python: ['3.11', '3.12']\n    steps: []\n")
    with pytest.raises(ValueError, match=r"matrix\.os"):
        ga.check_contexts(tmp_path)
    (tmp_path / "w.yml").write_text(
        "name: W\non:\n  pull_request:\n\njobs:\n  j:\n    name: Leg ${{ matrix.python }}\n"
        "    strategy:\n      matrix:\n        python: ['3.11', '3.12']\n    steps: []\n"
        "  k:\n    steps: []\n")
    assert [c["context"] for c in ga.check_contexts(tmp_path)] == ["Leg 3.11", "Leg 3.12", "k"]


# =============================================================================== 2. documented
def test_the_documented_block_is_what_publication_md_records():
    """The gate restates the record; the record is the authority. Every value, by sentence."""
    text = PUBLICATION.read_text()
    documented = ga.DOCUMENTED["ruleset"]
    assert f"(id {documented['id']})" in text
    assert f"**`{documented['name']}`**" in text
    assert "**`bypass_actors: []`**" in text and documented["bypass_actors"] == []
    assert "**`deletion`** and **`non_fast_forward`**" in text
    assert [r["type"] for r in documented["rules"]] == ["deletion", "non_fast_forward"]
    assert '`ref_name.include = ["~DEFAULT_BRANCH"]`' in text
    assert documented["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert "carries **no `required_status_checks` rule**" in text
    assert ga.DOCUMENTED["dco"]["required"] is False
    assert f"app id {ga.DOCUMENTED['dco']['app_id']}" in text
    assert ga.DOCUMENTED["direct_pushes_to_default_branch"] is True


def test_the_ruling_markers_are_the_sentences_the_publication_test_holds_both_sites_to():
    """One vocabulary: the apply verb's refusal reads the same two phrases the suite gates."""
    publication_test = (REPO / "tests" / "test_cdm_publication.py").read_text()
    for marker in ga.RULING_MARKERS.values():
        assert f'"{marker}"' in publication_test, marker
    assert ga.ruling_in_force() == {"PUBLICATION.md": True, "CONTRIBUTING.md": True}, (
        "the advisory-DCO ruling no longer reads as in force at both sites; if that is a "
        "deliberate reversal, PUBLICATION.md entry 1 names the sequence and stage 2 applies")


# =============================================================================== 3. proposed
@pytest.fixture(scope="module")
def stages() -> dict[int, dict]:
    loaded = {p["proposal"]["stage"]: p for _, p in ga.proposals(RULESETS)}
    assert sorted(loaded) == [1, 2], sorted(loaded)
    return loaded


def test_both_proposals_address_the_documented_ruleset_by_name_and_scope(stages):
    for stage in stages.values():
        ruleset = stage["ruleset"]
        assert ruleset["name"] == ga.DOCUMENTED["ruleset"]["name"]
        assert ruleset["conditions"] == ga.DOCUMENTED["ruleset"]["conditions"]
        assert ruleset["target"] == "branch" and ruleset["enforcement"] == "active"
        assert stage["proposal"]["adr"] == "docs/adr/0011-repository-governance-enforcement.md"
        assert (REPO / stage["proposal"]["adr"]).exists()
        assert "not proof" in stage["proposal"]["not_a_reading"]


def test_stage_1_adds_linear_history_and_nothing_that_ends_direct_pushes(stages):
    ruleset = stages[1]["ruleset"]
    types = [r["type"] for r in ruleset["rules"]]
    assert types == ["deletion", "non_fast_forward", "required_linear_history"]
    assert ruleset["bypass_actors"] == []
    assert stages[1]["proposal"]["requires_ruling_reversal"] is False
    assert not set(types) & set(ga.RULE_TYPES_THAT_END_DIRECT_PUSHES)


def test_stage_1_is_compatible_with_this_history_which_has_no_merge_commit():
    done = subprocess.run(["git", "log", "--merges", "--oneline"], cwd=REPO,
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        pytest.skip("no git history to read (fresh archive)")
    assert done.stdout.strip() == "", (
        "the history now carries merge commits; stage 1's required_linear_history would refuse "
        f"the next one. Re-decide before applying: {done.stdout.splitlines()[:3]}")


def test_stage_2_requires_every_derived_context_and_the_dco_check_and_nothing_else(stages):
    """Stable check names, operationally: the file must equal the derivation, byte for byte."""
    required = ga.required_contexts(stages[2]["ruleset"])
    actions = {c["context"] for c in required if c["integration_id"] == ga.GITHUB_ACTIONS_APP_ID}
    derived = {c["context"] for c in ga.check_contexts()}
    assert actions == derived, (
        f"stage 2's required contexts differ from the workflows' job names.\n"
        f"missing from the file: {sorted(derived - actions)}\n"
        f"in the file but no longer reported: {sorted(actions - derived)}")
    dco = [c for c in required if c["context"] == "DCO"]
    assert dco == [{"context": "DCO", "integration_id": ga.DCO_APP_ID}]
    assert len(required) == len(derived) + 1
    assert stages[2]["proposal"]["requires_ruling_reversal"] is True


def test_stage_2_accounts_for_one_maintainer_and_names_its_emergency_bypass(stages):
    ruleset, meta = stages[2]["ruleset"], stages[2]["proposal"]
    pull_request = next(r for r in ruleset["rules"] if r["type"] == "pull_request")
    assert pull_request["parameters"]["required_approving_review_count"] == 0
    assert pull_request["parameters"]["require_code_owner_review"] is False
    assert not (REPO / "CODEOWNERS").exists() and not (REPO / ".github" / "CODEOWNERS").exists()
    assert ruleset["bypass_actors"] == [
        {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    assert "audit log" in meta["emergency_bypass"]
    assert "one maintainer" in meta["single_maintainer"]
    assert "required_linear_history" in [r["type"] for r in ruleset["rules"]]
    assert set(pull_request["parameters"]["allowed_merge_methods"]) == {"squash", "rebase"}


def test_the_loader_refuses_a_proposal_whose_rules_and_flag_disagree(tmp_path):
    base = json.loads((RULESETS / "stage1-main-protection.json").read_text())
    lying = json.loads(json.dumps(base))
    lying["ruleset"]["rules"].append({"type": "pull_request", "parameters": {}})
    (tmp_path / "a.json").write_text(json.dumps(lying))
    with pytest.raises(ValueError, match="end direct pushes"):
        ga.load_proposal(tmp_path / "a.json")
    overclaiming = json.loads(json.dumps(base))
    overclaiming["proposal"]["requires_ruling_reversal"] = True
    (tmp_path / "b.json").write_text(json.dumps(overclaiming))
    with pytest.raises(ValueError, match="no rule ends direct pushes"):
        ga.load_proposal(tmp_path / "b.json")
    headless = {"ruleset": base["ruleset"]}
    (tmp_path / "c.json").write_text(json.dumps(headless))
    with pytest.raises(ValueError, match="`proposal`"):
        ga.load_proposal(tmp_path / "c.json")


# =============================================================================== 4. the audit
def _no_gh(name: str) -> str | None:
    return None


def _gh_present(name: str) -> str | None:
    return "/fake/bin/gh" if name == "gh" else None


def test_credential_detection_reads_presence_only_and_prefers_the_token():
    calls: list[list[str]] = []

    def run(argv):
        calls.append(argv)
        return 0

    assert ga.credential_source({"GH_TOKEN": "x"}, _no_gh, run) == "token"
    assert ga.credential_source({"GITHUB_TOKEN": "x"}, _gh_present, run) == "token"
    assert calls == [], "a present token must short-circuit the gh probe"
    assert ga.credential_source({}, _no_gh, run) is None
    assert calls == [], "gh absent from PATH must not be executed"
    assert ga.credential_source({}, _gh_present, run) == "gh"
    assert calls == [["gh", "auth", "status"]]
    assert ga.credential_source({}, _gh_present, lambda argv: 1) is None
    assert ga.credential_source({"GH_TOKEN": ""}, _no_gh, run) is None, "empty is absent"


def _audit(**kwargs) -> tuple[int, str]:
    out = io.StringIO()
    code = ga.audit(out=out, **kwargs)
    return code, out.getvalue()


def test_without_a_credential_the_audit_is_unverified_exit_3_and_says_so():
    code, text = _audit(env={}, which=_no_gh, run=lambda argv: 1)
    assert code == 3
    assert "LIVE: UNVERIFIED" in text and "no credential" in text
    assert "DOCUMENTED" in text and "PROPOSED" in text
    assert "HOLDS" not in text and "DRIFT" not in text
    assert "Nothing above is a reading" in text
    assert text.rstrip().endswith("exit 3")


def test_the_offline_flag_never_probes_for_a_credential():
    probed = []
    code, text = _audit(env={"GH_TOKEN": "x"}, offline=True,
                        which=lambda n: probed.append(n), run=lambda argv: 0)
    assert code == 3 and "offline flag" in text and probed == []


def test_the_audit_as_a_subprocess_with_a_scrubbed_path_is_unverified():
    """The CLI, end to end, with no gh on PATH and no token: exit 3, in text and in JSON."""
    env = {"PATH": "/nonexistent", "HOME": os.environ.get("HOME", "/"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    text = subprocess.run([sys.executable, "gates/governance_audit.py"], cwd=REPO, env=env,
                          capture_output=True, text=True, check=False)
    assert text.returncode == 3, text.stderr
    assert "LIVE: UNVERIFIED" in text.stdout and "is not on PATH" in text.stdout
    machine = subprocess.run([sys.executable, "gates/governance_audit.py", "--json"], cwd=REPO,
                             env=env, capture_output=True, text=True, check=False)
    assert machine.returncode == 3, machine.stderr
    report = json.loads(machine.stdout)
    assert report["live"]["verdict"] == "UNVERIFIED"
    assert report["documented"]["ruleset"]["id"] == 21205830
    assert {p["proposal"]["stage"] for p in report["proposed"]} == {1, 2}


#: Recorded responses SHAPED AFTER the readings `PUBLICATION.md` records — not captured from the
#: API (this session had no credential). The shape is the REST API's: list, detail, branch rules.
def _recorded(rules=None, bypass=None, rulesets_status=200) -> dict[str, tuple[int, object]]:
    rules = rules if rules is not None else [{"type": "deletion"}, {"type": "non_fast_forward"}]
    detail = {"id": 21205830, "name": "main-protection", "target": "branch",
              "enforcement": "active", "bypass_actors": bypass or [],
              "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
              "rules": rules}
    base = f"repos/{SLUG}"
    return {
        f"GET {base}": (200, {"default_branch": "main", "private": False, "visibility": "public"}),
        f"GET {base}/rulesets": (rulesets_status, [{"id": 21205830, "name": "main-protection"}]
                                 if rulesets_status == 200 else None),
        f"GET {base}/rulesets/21205830": (200, detail),
        f"GET {base}/rules/branches/main": (200, [{"type": t["type"]} for t in rules]),
        f"GET {base}/actions/permissions": (200, {"enabled": True, "allowed_actions": "all"}),
        f"GET {base}/actions/permissions/workflow": (200, {"default_workflow_permissions": "read"}),
        f"GET {base}/vulnerability-alerts": (204, None),
    }


def test_a_live_reading_equal_to_the_record_holds_with_exit_0_and_prints_no_token():
    transport = ga.RecordedTransport(_recorded())
    env = {"GH_TOKEN": "sekrit-value-that-must-never-print"}
    code, text = _audit(env=env, which=_no_gh, run=lambda argv: 1, transport=transport,
                        slug=SLUG)
    assert code == 0, text
    assert "HOLDS" in text and "sekrit" not in text
    assert "vulnerability_alerts: GET /repos/" in text and "HTTP 204" in text
    assert transport.writes == []
    out = io.StringIO()
    ga.audit(env=env, which=_no_gh, run=lambda argv: 1, transport=transport, slug=SLUG,
             as_json=True, out=out)
    assert "sekrit" not in out.getvalue()
    assert json.loads(out.getvalue())["live"]["verdict"] == "HOLDS"


def test_a_live_ruleset_with_a_required_checks_rule_is_drift_exit_1():
    rules = [{"type": "deletion"}, {"type": "non_fast_forward"},
             {"type": "required_status_checks", "parameters": {"required_status_checks": []}}]
    code, text = _audit(env={"GH_TOKEN": "x"}, which=_no_gh, run=lambda argv: 1,
                        transport=ga.RecordedTransport(_recorded(rules=rules)), slug=SLUG)
    assert code == 1
    assert "DRIFT" in text and "drift: rules:" in text
    assert "drift: a required_status_checks rule exists" in text


def test_a_bypass_actor_that_appeared_is_drift():
    actor = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    code, text = _audit(env={"GH_TOKEN": "x"}, which=_no_gh, run=lambda argv: 1,
                        transport=ga.RecordedTransport(_recorded(bypass=actor)), slug=SLUG)
    assert code == 1 and "drift: bypass_actors:" in text


def test_an_unreadable_rulesets_endpoint_is_reported_as_unreadable_and_never_as_absent():
    code, text = _audit(env={"GH_TOKEN": "x"}, which=_no_gh, run=lambda argv: 1,
                        transport=ga.RecordedTransport(_recorded(rulesets_status=403)), slug=SLUG)
    assert code == 1
    assert "unreadable (HTTP 403)" in text and "no ruleset named" not in text


def test_a_missing_ruleset_is_named_as_missing():
    responses = _recorded()
    responses[f"GET repos/{SLUG}/rulesets"] = (200, [])
    code, text = _audit(env={"GH_TOKEN": "x"}, which=_no_gh, run=lambda argv: 1,
                        transport=ga.RecordedTransport(responses), slug=SLUG)
    assert code == 1 and "no ruleset named 'main-protection'" in text


# =============================================================================== 5. apply
def _apply(transport, path: pathlib.Path) -> tuple[int, str]:
    out = io.StringIO()
    code = ga.apply(transport, SLUG, ga.load_proposal(path), out=out)
    return code, out.getvalue()


STAGE1 = RULESETS / "stage1-main-protection.json"
STAGE2 = RULESETS / "stage2-main-protection-pull-request-only.json"


def test_apply_writes_nothing_when_the_live_ruleset_already_equals_the_proposal():
    stage1 = json.loads(STAGE1.read_text())["ruleset"]
    transport = ga.RecordedTransport(_recorded(rules=stage1["rules"]))
    code, text = _apply(transport, STAGE1)
    assert code == 0 and "idempotent" in text and '"action": "noop"' in text
    assert transport.writes == []


def test_apply_updates_by_one_put_with_the_six_fields_and_verifies_the_readback():
    stage1 = json.loads(STAGE1.read_text())["ruleset"]
    responses = _recorded()
    applied = dict(stage1, id=21205830)
    responses[f"PUT repos/{SLUG}/rulesets/21205830"] = (200, applied)
    transport = ga.RecordedTransport(responses)
    # The readback must be the applied body, so the mapping is swapped after the PUT is answered.
    original_request = transport.request

    def request(method, path, body=None):
        status, payload = original_request(method, path, body)
        if method == "PUT":
            transport.responses[f"GET repos/{SLUG}/rulesets/21205830"] = (200, applied)
        return status, payload

    transport.request = request
    code, text = _apply(transport, STAGE1)
    assert code == 0, text
    assert "applied and read back" in text and '"changes": ["rules"]' in text
    assert [(m, p) for m, p, _ in transport.writes] == [("PUT", f"repos/{SLUG}/rulesets/21205830")]
    body = transport.writes[0][2]
    assert set(body) == {"name", "target", "enforcement", "bypass_actors", "conditions", "rules"}
    assert body["rules"] == stage1["rules"]


def test_apply_reports_a_readback_that_disagrees_and_exits_1():
    responses = _recorded()
    responses[f"PUT repos/{SLUG}/rulesets/21205830"] = (200, {"id": 21205830})
    transport = ga.RecordedTransport(responses)  # the GET still answers the OLD ruleset
    code, text = _apply(transport, STAGE1)
    assert code == 1 and "READBACK DISAGREES" in text
    assert len(transport.writes) == 1


def test_apply_creates_by_post_when_no_ruleset_of_that_name_exists():
    stage1 = json.loads(STAGE1.read_text())["ruleset"]
    responses = _recorded()
    responses[f"GET repos/{SLUG}/rulesets"] = (200, [])
    responses[f"POST repos/{SLUG}/rulesets"] = (201, dict(stage1, id=99))
    responses[f"GET repos/{SLUG}/rulesets/99"] = (200, dict(stage1, id=99))
    transport = ga.RecordedTransport(responses)
    code, text = _apply(transport, STAGE1)
    assert code == 0 and '"action": "create"' in text
    assert [(m, p) for m, p, _ in transport.writes] == [("POST", f"repos/{SLUG}/rulesets")]


def test_apply_refuses_stage_2_while_both_documents_carry_the_ruling_and_touches_nothing():
    transport = ga.RecordedTransport(_recorded())
    reads_before = dict(transport.responses)
    code, text = _apply(transport, STAGE2)
    assert code == 4
    assert "REFUSED" in text and "CONTRIBUTING.md" in text and "PUBLICATION.md" in text
    assert transport.writes == [] and transport.responses == reads_before


def test_apply_proceeds_for_stage_2_only_once_both_sites_drop_the_ruling(tmp_path):
    """The refusal is the documents', not the file's: a tree without the wording is not refused."""
    for name in ga.RULING_MARKERS:
        (tmp_path / name).write_text("the ruling was reversed here on a dated ledger entry\n")
    stage2 = json.loads(STAGE2.read_text())["ruleset"]
    transport = ga.RecordedTransport(_recorded(rules=stage2["rules"], bypass=stage2["bypass_actors"]))
    out = io.StringIO()
    code = ga.apply(transport, SLUG, ga.load_proposal(STAGE2), repo=tmp_path, out=out)
    assert code == 0 and "idempotent" in out.getvalue()


def test_the_cli_apply_verb_demands_the_typed_confirmation_before_any_credential(capsys, monkeypatch):
    monkeypatch.setattr(ga, "credential_source", lambda *a, **k: pytest.fail("probed"))
    assert ga.main(["apply", "--proposal", str(STAGE1), "--confirm", "yes"]) == 2
    assert "APPLY main-protection" in capsys.readouterr().err


def test_the_cli_apply_verb_without_a_credential_is_unverified_and_writes_nothing(capsys, monkeypatch):
    monkeypatch.setattr(ga, "credential_source", lambda *a, **k: None)
    monkeypatch.setattr(ga, "transport_for", lambda *a, **k: pytest.fail("a transport was built"))
    assert ga.main(["apply", "--proposal", str(STAGE1), "--confirm", "APPLY main-protection"]) == 3
    assert "UNVERIFIED" in capsys.readouterr().err


def test_the_default_verb_is_the_audit_and_apply_is_never_reached_by_it(monkeypatch, capsys):
    monkeypatch.setattr(ga, "credential_source", lambda *a, **k: None)
    monkeypatch.setattr(ga, "apply", lambda *a, **k: pytest.fail("apply ran from the default verb"))
    assert ga.main([]) == 3
    assert "UNVERIFIED" in capsys.readouterr().out


# =============================================================================== 6. the documents
def test_the_adr_is_proposed_names_every_artefact_and_marks_enforcement_blocked():
    text = ADR.read_text()
    status = text[text.index("## Status"):text.index("## Context")]
    assert status.strip().splitlines()[2].startswith("Proposed"), status
    assert "BLOCKED_ADMIN_ACTION" in status
    for artefact in ("stage1-main-protection.json", "stage2-main-protection-pull-request-only.json",
                     "gates/governance_audit.py", "docs/governance/RUNBOOK.md",
                     "tests/test_cdm_governance.py"):
        assert artefact in text, artefact
    for heading in ("## Alternatives considered", "## Security impact", "## Reversibility"):
        assert heading in text, heading
    assert "one maintainer" in text and "CODEOWNERS" in text


def test_the_runbook_reads_back_defaults_to_audit_and_states_the_bypass():
    text = RUNBOOK.read_text()
    assert "python gates/governance_audit.py apply" in text
    assert "--confirm 'APPLY main-protection'" in text
    assert "UNVERIFIED" in text and "readback" in text.lower()
    assert "## 5. Emergency bypass" in text and "audit log" in text
    assert "not proof" in text
    assert "settled decision and not an oversight" in text and "stays advisory" in text, (
        "the runbook must quote the two ruling sentences the apply verb refuses on")
    assert "one maintainer" in text


def test_neither_new_document_claims_the_check_is_a_required_status():
    for path in (ADR, RUNBOOK):
        assert "is a **required status**" not in path.read_text(), path.name


def test_the_register_marks_remote_enforcement_as_an_administrator_action():
    rows = [line for line in REGISTER.read_text().splitlines() if line.startswith("| F08 |")]
    assert rows, f"{REGISTER.name} has no status-table row starting with `| F08 |`"
    assert "BLOCKED_ADMIN_ACTION" in rows[0], rows[0]
