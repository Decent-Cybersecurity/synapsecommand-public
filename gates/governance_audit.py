"""Repository governance, in three columns that are never confused: DOCUMENTED, PROPOSED, LIVE.

WHY THIS EXISTS
---------------
`PUBLICATION.md` records what the `main-protection` ruleset WAS when somebody read it from the
API, and ledger entry 1 records the ruling that keeps the `DCO` check advisory and direct pushes
to `main` legal. Both are records. Neither is a reading of the repository's settings today, and a
JSON file in `docs/governance/` describing a ruleset is not proof that `main` is protected — it is
a proposal until an administrator applies it and somebody reads the result back.

This gate keeps those three states apart and says which one each line of its output is:

* **DOCUMENTED** — the state `PUBLICATION.md` records, carried here as data with its citation.
  `tests/test_cdm_governance.py` holds this block to the document's own sentences, so the gate
  cannot drift from the record it claims to restate.
* **PROPOSED** — the staged ruleset files under `docs/governance/rulesets/`. Stage 1 can be
  applied without changing any ruling; stage 2 changes the working shape and is refused by
  `apply` for as long as `CONTRIBUTING.md` and `PUBLICATION.md` still carry the ruling it would
  reverse (ADR 0011 records both stages and the reasons).
* **LIVE** — the settings as the GitHub API returns them, read only when a credential is
  available (`GH_TOKEN`/`GITHUB_TOKEN` in the environment, or `gh auth status` succeeding), and
  otherwise reported as **UNVERIFIED**. The gate never infers the live state from files, never
  prints a token, and never treats UNVERIFIED as a pass: the exit code says so.

DEFAULT IS AUDIT; APPLY IS A SEPARATE VERB
------------------------------------------
`python gates/governance_audit.py` mutates nothing under any credential. `apply` is a separate
sub-command that needs a proposal file, a typed confirmation, a credential, a plan it prints
first, and a readback it verifies afterwards; it is idempotent (an identical live ruleset is a
no-op that writes nothing) and narrowly scoped (one ruleset, by name). Audit remediation F08
delivered it and did NOT run it — remote enforcement is BLOCKED_ADMIN_ACTION in the register
until an administrator applies a stage and reads it back.

EXIT CODES
----------
0  live state read and equal to DOCUMENTED (audit), or apply succeeded and the readback agrees
1  live state read and it DIFFERS from DOCUMENTED (audit), or the readback disagrees (apply)
2  usage, or a proposal file that fails its own shape checks
3  UNVERIFIED — no credential, so nothing was read; the DOCUMENTED and PROPOSED columns printed
4  apply refused: the proposal reverses a ruling both documents still carry
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
RULESETS = REPO / "docs" / "governance" / "rulesets"
PUBLICATION = REPO / "PUBLICATION.md"
CONTRIBUTING = REPO / "CONTRIBUTING.md"

#: The environment variables a credential may arrive in. Their VALUES are never read into a
#: message, a log line or a JSON report; only whether one is non-empty.
TOKEN_VARIABLES = ("GH_TOKEN", "GITHUB_TOKEN")

#: GitHub App ids the required-checks rule addresses a context to. Actions is the app every
#: workflow check run belongs to; the DCO app id is the one `PUBLICATION.md` records.
GITHUB_ACTIONS_APP_ID = 15368
DCO_APP_ID = 1861

#: The `main-protection` ruleset as `PUBLICATION.md` records it (section "The `main-protection`
#: ruleset, and its history is not what it looks like", and ledger entry 1). A RECORD: the test
#: module holds every value here to the document, and nothing here is presented as live.
DOCUMENTED: dict[str, Any] = {
    "ruleset": {
        "id": 21205830,
        "name": "main-protection",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
    },
    "dco": {"app_id": DCO_APP_ID, "slug": "dco", "required": False,
            "ruling": "PUBLICATION.md ledger entry 1: `DCO` stays advisory — RULED"},
    "direct_pushes_to_default_branch": True,
    "citation": "PUBLICATION.md — 'The `main-protection` ruleset' section and ledger entry 1",
}

#: The wording both documents carry while the ruling stands. `apply` refuses a proposal that
#: reverses the ruling for as long as EITHER site still says this; the same two phrases are the
#: ones `tests/test_cdm_publication.py` requires the two sites to agree on.
RULING_MARKERS = {
    "PUBLICATION.md": "stays advisory",
    "CONTRIBUTING.md": "settled decision and not an oversight",
}

RULE_TYPES_THAT_END_DIRECT_PUSHES = ("pull_request", "required_status_checks")


# ----------------------------------------------------------------------------- workflows, read as text
_JOB_HEADER = re.compile(r"^  ([a-z][a-z0-9_-]*):[ \t]*$", re.MULTILINE)
_MATRIX_EXPR = re.compile(r"\$\{\{\s*matrix\.([a-zA-Z0-9_-]+)\s*\}\}")


def job_blocks(workflow_text: str) -> dict[str, str]:
    """Each job id mapped to its text. No YAML parser: PyYAML is not a dependency here."""
    body = workflow_text[workflow_text.index("\njobs:"):]
    matches = list(_JOB_HEADER.finditer(body))
    return {m.group(1): body[m.start():(matches[i + 1].start() if i + 1 < len(matches)
                                       else len(body))]
            for i, m in enumerate(matches)}


def live_lines(block: str) -> list[str]:
    """The block without comment lines, so a commented-out key is not a key."""
    return [line for line in block.splitlines() if not line.lstrip().startswith("#")]


def _matrix_combinations(block: str) -> list[dict[str, str]]:
    """The matrix a job declares, as the combinations Actions would run.

    Two spellings are handled because two occur in this repository: `key: [a, b]` lists, whose
    product is taken, and an `include:` list of `- key: value` entries, each of which is one
    combination. A matrix that mixes the two is refused rather than guessed at.
    """
    lines = live_lines(block)
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "matrix:")
    except StopIteration:
        return []
    indent = len(lines[start]) - len(lines[start].lstrip())
    body: list[str] = []
    for line in lines[start + 1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        body.append(line)
    lists: dict[str, list[str]] = {}
    include: list[dict[str, str]] = []
    in_include = False
    for line in body:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "include:":
            in_include = True
            continue
        if in_include:
            if stripped.startswith("- "):
                include.append({})
                stripped = stripped[2:].strip()
            key, _, value = stripped.partition(":")
            include[-1][key.strip()] = value.strip().strip("'\"")
            continue
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):\s*\[(.*)\]", stripped)
        if match:
            lists[match.group(1)] = [v.strip().strip("'\"") for v in match.group(2).split(",")
                                     if v.strip()]
    if lists and include:
        raise ValueError("a matrix mixing key lists and include: entries is not expanded here")
    if include:
        return include
    keys = sorted(lists)
    return [dict(zip(keys, values)) for values in itertools.product(*(lists[k] for k in keys))]


def check_contexts(workflows_dir: pathlib.Path = WORKFLOWS) -> list[dict[str, str]]:
    """Every status-check context the pull-request-triggered workflows would report.

    A check run is named after the job's `name:` (its id when there is none), with matrix
    expressions expanded once per combination. These are the strings a `required_status_checks`
    rule has to match EXACTLY, which is why the proposal is held to this derivation and not to a
    list somebody typed.
    """
    out: list[dict[str, str]] = []
    for path in sorted(workflows_dir.glob("*.yml")):
        text = path.read_text()
        triggers = triggers_of(text)
        if "pull_request" not in triggers:
            continue
        for job, block in job_blocks(text).items():
            names = [line.strip()[len("name:"):].strip() for line in live_lines(block)
                     if line.startswith("    name:")]
            template = names[0] if names else job
            combinations = _matrix_combinations(block) or [{}]
            for combination in combinations:
                def _sub(match: re.Match[str], combo: dict[str, str] = combination) -> str:
                    key = match.group(1)
                    if key not in combo:
                        raise ValueError(f"{path.name}:{job}: `matrix.{key}` in the name but "
                                         f"not in the matrix ({sorted(combo)})")
                    return combo[key]
                out.append({"workflow": path.name, "job": job,
                            "context": _MATRIX_EXPR.sub(_sub, template)})
    return out


def _on_block(workflow_text: str) -> str | None:
    """The text under the first `on:` line that is closed by a top-level key, else None.

    This was the regex `^on:\\n((?:(?:  .*|\\s*)\\n)+?)(?=^\\S)` until CodeQL's py/redos read it
    on 2026-09-20: `\\s*` and the group's own `\\n` could each take a blank line, so an `on:`
    followed by many blank lines and then a line the lookahead rejects backtracked
    exponentially. The walker below accepts the same language — a line of `on:` alone, then
    at least one line that is two-space indented or whitespace-only, ended by a line whose
    first character is not whitespace — in one pass, and `tests/test_cdm_governance.py`
    holds it to that language edge by edge.
    """
    lines = workflow_text.split("\n")
    tail = len(lines) - 1  # the last element is the text after the final newline: no `\n`
    for start in range(tail):
        if lines[start] != "on:":
            continue
        end = start + 1
        while end < tail and (lines[end].startswith("  ") or not lines[end].strip()):
            end += 1
        closing = lines[end][:1]
        if end == start + 1 or not closing or closing.isspace():
            continue
        return "\n".join(lines[start + 1:end]) + "\n"
    return None


def triggers_of(workflow_text: str) -> dict[str, str]:
    """The `on:` block's event names mapped to each event's own text (filters included)."""
    block = _on_block(workflow_text)
    if block is None:
        return {}
    events: dict[str, str] = {}
    current = None
    for line in live_lines(block):
        head = re.match(r"^  ([a-z_]+):\s*(.*)$", line)
        if head:
            current = head.group(1)
            events[current] = head.group(2) + "\n"
        elif current is not None:
            events[current] += line + "\n"
    return events


def run_block_expressions(workflow_text: str) -> list[tuple[int, str]]:
    """`${{ … }}` expressions that sit INSIDE a `run:` script, with their line numbers.

    An expression inside `run:` is expanded into the script's text before the shell reads it —
    a dispatch input, a pull-request title or a branch name spliced into bash. The safe carrier
    is `env:`; this returns what a test then requires to be empty.
    """
    found: list[tuple[int, str]] = []
    in_run = False
    run_indent = 0
    for number, line in enumerate(workflow_text.splitlines(), start=1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- "):  # `- run:` as the first key of a step
            stripped = stripped[2:].lstrip()
        if re.match(r"run:\s*[|>]", stripped):
            in_run, run_indent = True, indent
            continue
        if in_run and stripped and indent <= run_indent:
            in_run = False
        if in_run or re.match(r"run:\s*\S", stripped):
            for expression in re.findall(r"\$\{\{[^}]*\}\}", line):
                found.append((number, expression.strip()))
    return found


# ----------------------------------------------------------------------------- proposals
REQUIRED_PROPOSAL_KEYS = ("stage", "status", "requires_ruling_reversal", "adr", "summary")


def load_proposal(path: pathlib.Path) -> dict[str, Any]:
    """A proposal file: `{"proposal": {...metadata...}, "ruleset": {...API body...}}`."""
    data = json.loads(path.read_text())
    problems: list[str] = []
    meta, ruleset = data.get("proposal"), data.get("ruleset")
    if not isinstance(meta, dict) or not isinstance(ruleset, dict):
        raise ValueError(f"{path.name}: needs both a `proposal` and a `ruleset` object")
    for key in REQUIRED_PROPOSAL_KEYS:
        if key not in meta:
            problems.append(f"proposal.{key} missing")
    for key in ("name", "target", "enforcement", "bypass_actors", "conditions", "rules"):
        if key not in ruleset:
            problems.append(f"ruleset.{key} missing")
    types = [rule.get("type") for rule in ruleset.get("rules", [])]
    ends_direct_pushes = any(t in RULE_TYPES_THAT_END_DIRECT_PUSHES for t in types)
    if ends_direct_pushes and not meta.get("requires_ruling_reversal"):
        problems.append("the rules end direct pushes (pull_request / required_status_checks) but "
                        "proposal.requires_ruling_reversal is not true")
    if not ends_direct_pushes and meta.get("requires_ruling_reversal"):
        problems.append("proposal.requires_ruling_reversal is true but no rule ends direct pushes")
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return data


def proposals(directory: pathlib.Path = RULESETS) -> list[tuple[pathlib.Path, dict[str, Any]]]:
    return [(path, load_proposal(path)) for path in sorted(directory.glob("*.json"))]


def required_contexts(ruleset: Mapping[str, Any]) -> list[dict[str, Any]]:
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "required_status_checks":
            return list(rule.get("parameters", {}).get("required_status_checks", []))
    return []


def ruling_in_force(repo: pathlib.Path = REPO) -> dict[str, bool]:
    """Whether each site still carries the advisory-DCO ruling's wording."""
    return {name: marker in (repo / name).read_text() for name, marker in RULING_MARKERS.items()}


# ----------------------------------------------------------------------------- credentials, never printed
Runner = Callable[[list[str]], int]


def _default_runner(argv: list[str]) -> int:
    """Run and return the exit status; stdout and stderr are DISCARDED, not captured."""
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=30, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        return 127


def credential_source(env: Mapping[str, str] | None = None,
                      which: Callable[[str], str | None] = shutil.which,
                      run: Runner = _default_runner) -> str | None:
    """`"token"`, `"gh"`, or None. The token's value is never read past `bool()`."""
    env = os.environ if env is None else env
    if any(env.get(name) for name in TOKEN_VARIABLES):
        return "token"
    if which("gh") and run(["gh", "auth", "status"]) == 0:
        return "gh"
    return None


# ----------------------------------------------------------------------------- transports
class Transport:
    """`request(method, path, body) -> (status, payload)`; `path` is relative to the API root."""

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        raise NotImplementedError


class RecordedTransport(Transport):
    """Responses played back from a mapping of `"GET /path"` to `(status, payload)`.

    Writes are appended to `.writes` and answered from the same mapping, so a test can assert
    both that nothing was written and what a readback after a write returns.
    """

    def __init__(self, responses: Mapping[str, tuple[int, Any]]):
        self.responses = dict(responses)
        self.writes: list[tuple[str, str, Any]] = []

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if method != "GET":
            self.writes.append((method, path, body))
        return self.responses.get(f"{method} {path}", (404, None))


class GhTransport(Transport):
    """`gh api`, which carries its own credential and prints none of it."""

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        argv = ["gh", "api", "--method", method, path]
        stdin = None
        if body is not None:
            argv += ["--input", "-"]
            stdin = json.dumps(body)
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, check=False)
        if done.returncode == 0:
            return (200 if done.stdout.strip() else 204,
                    json.loads(done.stdout) if done.stdout.strip() else None)
        status = re.search(r"HTTP (\d{3})", done.stderr)
        return (int(status.group(1)) if status else 599), None


class TokenTransport(Transport):
    """urllib with `Authorization: Bearer`, the token read from the environment at request time.

    No exception raised here carries the header, the token, or the response body of a failure —
    the status and the path are the whole message.
    """

    def __init__(self, env: Mapping[str, str] | None = None):
        self.env = os.environ if env is None else env

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        import urllib.error
        import urllib.request
        token = next((self.env[n] for n in TOKEN_VARIABLES if self.env.get(n)), "")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            "https://api.github.com/" + path.lstrip("/"), data=data, method=method,
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            return error.code, None
        except urllib.error.URLError:
            return 599, None


def transport_for(source: str, env: Mapping[str, str] | None = None) -> Transport:
    return TokenTransport(env) if source == "token" else GhTransport()


# ----------------------------------------------------------------------------- live readings
def origin_slug(repo: pathlib.Path = REPO) -> str:
    """`owner/name` from `git remote get-url origin`; both https and ssh spellings."""
    done = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True,
                          text=True, check=False)
    url = done.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise ValueError(f"origin is not a github.com remote: {url!r}")
    return f"{match.group(1)}/{match.group(2)}"


def read_live(transport: Transport, slug: str) -> dict[str, Any]:
    """Every reading the audit uses, each labelled with its endpoint and status.

    A non-200 is recorded as `unreadable` with the status, never as a value: a 403 on the
    rulesets endpoint is "this credential cannot see rulesets", not "there are none".
    """
    readings: dict[str, Any] = {}

    def take(key: str, path: str) -> Any:
        status, payload = transport.request("GET", path)
        readings[key] = {"endpoint": f"GET /{path}", "status": status,
                         "value": payload if status in (200, 204) else None}
        return payload if status == 200 else None

    repository = take("repository", f"repos/{slug}")
    default_branch = (repository or {}).get("default_branch", "main")
    listed = take("rulesets", f"repos/{slug}/rulesets") or []
    details = []
    for entry in listed:
        detail = take(f"ruleset:{entry.get('id')}", f"repos/{slug}/rulesets/{entry.get('id')}")
        if detail is not None:
            details.append(detail)
    readings["ruleset_details"] = details
    take("branch_rules", f"repos/{slug}/rules/branches/{default_branch}")
    take("actions_permissions", f"repos/{slug}/actions/permissions")
    take("workflow_token_permissions", f"repos/{slug}/actions/permissions/workflow")
    take("vulnerability_alerts", f"repos/{slug}/vulnerability-alerts")
    return readings


def canonical_ruleset(ruleset: Mapping[str, Any]) -> dict[str, Any]:
    """The comparable subset of a ruleset: what the API accepts on write, sorted for equality."""
    rules = sorted((json.loads(json.dumps(rule, sort_keys=True)) for rule in ruleset.get("rules", [])),
                   key=lambda r: json.dumps(r, sort_keys=True))
    actors = sorted((dict(a) for a in ruleset.get("bypass_actors", []) or []),
                    key=lambda a: json.dumps(a, sort_keys=True))
    return {"name": ruleset.get("name"), "target": ruleset.get("target"),
            "enforcement": ruleset.get("enforcement"), "bypass_actors": actors,
            "conditions": ruleset.get("conditions"), "rules": rules}


def find_ruleset(details: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((d for d in details if d.get("name") == name), None)


def drift(live: dict[str, Any], documented: Mapping[str, Any] = DOCUMENTED) -> list[str]:
    """Where the live reading disagrees with the documented record. Empty means the record holds."""
    findings: list[str] = []
    wanted = documented["ruleset"]
    if live["rulesets"]["status"] != 200:
        return [f"rulesets unreadable (HTTP {live['rulesets']['status']}): nothing compared"]
    found = find_ruleset(live["ruleset_details"], wanted["name"])
    if found is None:
        return [f"no ruleset named {wanted['name']!r} exists; the record describes one"]
    if found.get("id") != wanted["id"]:
        findings.append(f"ruleset id is {found.get('id')}, recorded {wanted['id']}")
    have, want = canonical_ruleset(found), canonical_ruleset(wanted)
    for key in ("enforcement", "bypass_actors", "conditions", "rules"):
        if have[key] != want[key]:
            findings.append(f"{key}: live {json.dumps(have[key], sort_keys=True)} != recorded "
                            f"{json.dumps(want[key], sort_keys=True)}")
    types = {rule.get("type") for rule in found.get("rules", [])}
    if "required_status_checks" in types and not documented["dco"]["required"]:
        findings.append("a required_status_checks rule exists; the record says none does")
    return findings


def plan(live: dict[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    """What `apply` would change: `create`, `update` with the differing keys, or `noop`."""
    wanted = canonical_ruleset(proposal["ruleset"])
    found = find_ruleset(live.get("ruleset_details", []), wanted["name"])
    if found is None:
        return {"action": "create", "name": wanted["name"], "changes": sorted(wanted)}
    have = canonical_ruleset(found)
    changes = [key for key in wanted if have[key] != wanted[key]]
    return {"action": "update" if changes else "noop", "id": found.get("id"),
            "name": wanted["name"], "changes": changes}


# ----------------------------------------------------------------------------- apply (separate verb)
def apply(transport: Transport, slug: str, proposal: Mapping[str, Any], *,
          repo: pathlib.Path = REPO, out=None) -> int:
    """Create or update ONE ruleset to match the proposal, then read it back. Idempotent."""
    out = sys.stdout if out is None else out  # resolved at call time, so a redirect is honoured
    meta = proposal["proposal"]
    if meta.get("requires_ruling_reversal"):
        standing = {site: yes for site, yes in ruling_in_force(repo).items() if yes}
        if standing:
            print("REFUSED: the proposal reverses the advisory-DCO ruling and these documents "
                  f"still carry it: {', '.join(sorted(standing))}. Reverse the ruling at both "
                  "sites in one commit first (PUBLICATION.md entry 1 names the sequence).",
                  file=out)
            return 4
    live = read_live(transport, slug)
    step = plan(live, proposal)
    print(f"plan: {json.dumps(step, sort_keys=True)}", file=out)
    if step["action"] == "noop":
        print("idempotent: the live ruleset already equals the proposal; nothing written.",
              file=out)
        return 0
    body = {k: proposal["ruleset"][k] for k in
            ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")}
    if step["action"] == "create":
        status, payload = transport.request("POST", f"repos/{slug}/rulesets", body)
    else:
        status, payload = transport.request("PUT", f"repos/{slug}/rulesets/{step['id']}", body)
    if status not in (200, 201) or not isinstance(payload, dict):
        print(f"write failed: HTTP {status}; nothing verified.", file=out)
        return 1
    ruleset_id = payload.get("id", step.get("id"))
    status, readback = transport.request("GET", f"repos/{slug}/rulesets/{ruleset_id}")
    if status != 200 or canonical_ruleset(readback) != canonical_ruleset(proposal["ruleset"]):
        print(f"READBACK DISAGREES (HTTP {status}): the ruleset as returned is not the proposal. "
              "Treat the write as unverified.", file=out)
        return 1
    print(f"applied and read back: ruleset {ruleset_id} ({body['name']}) equals the proposal.",
          file=out)
    return 0


# ----------------------------------------------------------------------------- report
def _describe(ruleset: Mapping[str, Any]) -> str:
    rules = ", ".join(r.get("type", "?") for r in ruleset.get("rules", []))
    actors = ruleset.get("bypass_actors") or []
    return (f"{ruleset.get('name')}: enforcement {ruleset.get('enforcement')}, "
            f"bypass_actors {len(actors)}, rules [{rules}]")


def audit(*, env: Mapping[str, str] | None = None, offline: bool = False, slug: str | None = None,
          which: Callable[[str], str | None] = shutil.which, run: Runner = _default_runner,
          transport: Transport | None = None, rulesets_dir: pathlib.Path = RULESETS,
          workflows_dir: pathlib.Path = WORKFLOWS, repo: pathlib.Path = REPO,
          as_json: bool = False, out=None) -> int:
    out = sys.stdout if out is None else out  # resolved at call time, so a redirect is honoured
    report: dict[str, Any] = {"documented": DOCUMENTED, "proposed": [], "live": None,
                              "check_contexts": check_contexts(workflows_dir)}
    for path, proposal in proposals(rulesets_dir):
        report["proposed"].append({"file": str(path.relative_to(repo)),
                                   "proposal": proposal["proposal"],
                                   "ruleset": _describe(proposal["ruleset"]),
                                   "required_contexts": [c["context"] for c in
                                                         required_contexts(proposal["ruleset"])]})
    report["ruling_in_force"] = ruling_in_force(repo)

    source = None if offline else credential_source(env, which, run)
    if source is None:
        reason = "offline flag" if offline else (
            f"no credential: none of {'/'.join(TOKEN_VARIABLES)} is set and `gh auth status` "
            f"{'is not on PATH' if not which('gh') else 'did not succeed'}")
        report["live"] = {"verdict": "UNVERIFIED", "reason": reason}
        exit_code = 3
    else:
        transport = transport or transport_for(source, env)
        slug = slug or origin_slug(repo)
        readings = read_live(transport, slug)
        findings = drift(readings)
        report["live"] = {"verdict": "HOLDS" if not findings else "DRIFT", "source": source,
                          "repository": slug, "findings": findings,
                          "readings": {k: v for k, v in readings.items() if k != "ruleset_details"},
                          "rulesets": [_describe(d) for d in readings["ruleset_details"]]}
        exit_code = 0 if not findings else 1

    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True), file=out)
        return exit_code
    print("governance audit — mutates nothing", file=out)
    print(f"DOCUMENTED ({DOCUMENTED['citation']}; a record, not a reading)", file=out)
    print(f"  {_describe(DOCUMENTED['ruleset'])} (id {DOCUMENTED['ruleset']['id']})", file=out)
    print(f"  DCO app {DOCUMENTED['dco']['app_id']}: installed, required={DOCUMENTED['dco']['required']} "
          f"— {DOCUMENTED['dco']['ruling']}", file=out)
    print(f"  ruling wording present: {report['ruling_in_force']}", file=out)
    print("PROPOSED (docs/governance/rulesets/; a proposal is not an applied setting)", file=out)
    for item in report["proposed"]:
        meta = item["proposal"]
        print(f"  stage {meta['stage']} [{meta['status']}] {item['file']}: {item['ruleset']}; "
              f"requires ruling reversal: {meta['requires_ruling_reversal']}; "
              f"required contexts: {len(item['required_contexts'])}", file=out)
    print(f"  check contexts the pull-request workflows would report: "
          f"{len(report['check_contexts'])}", file=out)
    live = report["live"]
    if live["verdict"] == "UNVERIFIED":
        print(f"LIVE: UNVERIFIED — {live['reason']}. Nothing above is a reading of the "
              "repository's settings.", file=out)
    else:
        print(f"LIVE ({live['source']}, {live['repository']}): {live['verdict']}", file=out)
        for name in live["rulesets"]:
            print(f"  {name}", file=out)
        for finding in live["findings"]:
            print(f"  drift: {finding}", file=out)
        for key, reading in live["readings"].items():
            print(f"  {key}: {reading['endpoint']} -> HTTP {reading['status']}", file=out)
    print(f"exit {exit_code}", file=out)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/name; default: parsed from `git remote origin`")
    parser.add_argument("--offline", action="store_true",
                        help="never probe for a credential; print DOCUMENTED and PROPOSED only")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    sub = parser.add_subparsers(dest="verb")
    applier = sub.add_parser("apply", help="create/update ONE ruleset from a proposal; readback")
    applier.add_argument("--proposal", required=True, type=pathlib.Path)
    applier.add_argument("--confirm", required=True,
                         help="must equal `APPLY <ruleset name>` — typed, not defaulted")
    args = parser.parse_args(argv)

    if args.verb == "apply":
        try:
            proposal = load_proposal(args.proposal)
        except (ValueError, OSError, json.JSONDecodeError) as error:
            print(f"usage: {error}", file=sys.stderr)
            return 2
        expected = f"APPLY {proposal['ruleset']['name']}"
        if args.confirm != expected:
            print(f"usage: --confirm must be exactly {expected!r}", file=sys.stderr)
            return 2
        source = credential_source()
        if source is None:
            print("UNVERIFIED: no credential, so nothing can be applied or read back.",
                  file=sys.stderr)
            return 3
        return apply(transport_for(source), args.repo or origin_slug(), proposal)

    try:
        return audit(offline=args.offline, slug=args.repo, as_json=args.json)
    except ValueError as error:
        print(f"usage: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
