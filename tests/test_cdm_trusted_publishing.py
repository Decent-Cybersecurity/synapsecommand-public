"""The publish workflow, and the four values it has to agree with PyPI about.

WHY THIS MODULE EXISTS
----------------------
`.github/workflows/publish.yml` uploads to PyPI with no credential in it. What authorises the
upload is a match: GitHub mints an OIDC token carrying the repository owner, the repository name,
the workflow's FILENAME and the environment name, and PyPI compares all four against a trusted
publisher a human registered on the project. A single character wrong at any of the four and the
upload is refused.

That makes those four values a textbook disjunction — one fact, stated in two places that cannot
see each other. `PUBLICATION.md` ledger entry 6 states them as instructions for the human filling
in the PyPI form; the workflow states two of them by being the file it is and naming the
environment it runs in. Nothing on either side can observe the third copy, which is the one on
pypi.org and is not public. So the only drift this repository CAN catch is between its own two
statements, and it catches it here — because the failure mode is not exotic: someone renames the
workflow file, or changes the environment, and entry 6 keeps confidently instructing a reader to
type the old value into a form that will then silently authorise nothing.

`tests/test_cdm_deploy_workflow.py` is the precedent and the warning. A claim that a push deployed
the documentation site was made in the one window where nothing could falsify it, and it stayed
wrong for a round. This module is written on the assumption that the same thing is possible here,
because the publish job has never run: at the time of writing, every statement in this repository
about the upload working is a statement about a mechanism that has never been exercised.

WHAT THIS MODULE CANNOT CHECK, AND SAYS SO INSTEAD OF IMPLYING OTHERWISE
------------------------------------------------------------------------
* whether a trusted publisher exists on pypi.org. Not public, no token here, and a test that
  needed one would fail for every outsider and go green only for whoever holds it;
* whether the environment exists on GitHub with reviewers on it. Same reason;
* whether the upload works. It has never run. The `build` job is exercised by
  `workflow_dispatch`; the `publish` job's first execution is the 1.1.0 tag.

What it does check is everything that is decidable from the tree: that the two local statements
agree, that no credential has appeared in the workflow, that every action is pinned to a commit
rather than to a movable tag, and that the publish job is reachable only by a tag.
"""
import pathlib
import re
from urllib.parse import urlsplit

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "publish.yml"
PUBLICATION = REPO / "PUBLICATION.md"

#: The environment name, stated here as a third independent copy on purpose. Two statements can
#: agree with each other while both being changed in one careless edit; a test that derived this
#: from the workflow would move with it and check nothing.
ENVIRONMENT = "pypi"

#: The PyPI project this publishes. `synapse-cdm` is the normalised form and the one on the index.
PROJECT = "synapse-cdm"

#: TestPyPI's host, compared as a WHOLE host and never as a substring of a line.
TESTPYPI_HOST = "test.pypi.org"

#: What separates one YAML token from the next, for the purpose of finding hosts in a line.
#: Quotes, brackets and `=` are here because `url: "https://…"`, `[a, b]` and `VAR=https://…`
#: all put a host flush against punctuation, and a token that still carries the punctuation
#: parses to a different host or to none.
_TOKEN_SPLIT = re.compile(r"""[\s,;'"()\[\]{}<>=]+""")


def hosts_named_in(line: str) -> set[str]:
    """Every host `line` names, as whole host components.

    Substring matching on an unparsed URL is the mistake CodeQL's
    `py/incomplete-url-substring-sanitization` is named after, and it flagged the TestPyPI check
    below for it on 2026-09-08 (run 34212170555, CVSS 7.8). The complaint is exact: "the string
    test.pypi.org may be at an arbitrary position in the sanitized URL". It cuts both ways here
    — `https://pypi.org/project/test.pypi.org-shim/` contains those characters and targets the
    real index, while what the check is for is a host.

    So every token is parsed and its HOST component compared. A token with no scheme is parsed
    as a bare authority (`//<token>`) rather than string-split, so exactly one code path decides
    what a host is: `urlsplit` strips userinfo, port, path, query and fragment, and lowercases
    the host, none of which a `split('/')` would do.
    """
    hosts: set[str] = set()
    for token in _TOKEN_SPLIT.split(line):
        if not token:
            continue
        try:
            host = urlsplit(token if "://" in token else f"//{token}").hostname
        except ValueError:  # a malformed authority names no host, which is the safe direction
            continue
        if host:
            hosts.add(host)
    return hosts


def targets_testpypi(line: str) -> bool:
    """True if `line` names TestPyPI as a host — the host itself or any subdomain of it.

    The subdomain arm is the form CodeQL's own recommendation gives (`host.endswith('.' + h)`
    on a PARSED host), and it is checked here rather than assumed unnecessary: an index that
    ever answered on `files.test.pypi.org` would be TestPyPI as much as the apex is.
    """
    return any(
        host == TESTPYPI_HOST or host.endswith(f".{TESTPYPI_HOST}")
        for host in hosts_named_in(line)
    )


@pytest.fixture(scope="module")
def workflow() -> str:
    assert WORKFLOW.exists(), (
        f"{WORKFLOW.relative_to(REPO)} is gone. PyPI matches the OIDC token's workflow claim "
        "against the FILENAME, so renaming or removing this file breaks publishing in a way no "
        "local run can show — the failure appears as a refused upload on a release. If it is "
        "renamed deliberately, the new name goes into PUBLICATION.md entry 6 and the trusted "
        "publisher on pypi.org has to be re-registered, in that order")
    return WORKFLOW.read_text()


def entry_six() -> str:
    text = PUBLICATION.read_text()
    start = text.index("### 6.")
    nxt = text.find("\n### ", start + 6)
    end = text.find("\n## ", start)
    stop = min(x for x in (nxt, end, len(text)) if x != -1)
    return text[start:stop]


# ----------------------------------------------------------- the disjunction: two sites, one fact


def test_entry_six_names_the_workflow_file_that_actually_exists():
    """The filename in the instructions is the filename on disk.

    Entry 6 tells a human to type this into PyPI's "Workflow name" field. PyPI matches the path,
    not the `name:` inside the file, and entry 6 says so — this checks that what it says to type
    is a file that exists.
    """
    entry = entry_six()
    named = re.findall(r"`([A-Za-z0-9_.-]+\.ya?ml)`", entry)
    assert named, (
        "PUBLICATION.md entry 6 names no workflow file. It is the instruction sheet for the PyPI "
        "form and the form has a Workflow name field; leaving it unnamed there means the value "
        "gets guessed from the repository at the moment somebody fills the form in")
    on_disk = {p.name for p in WORKFLOWS.glob("*.y*ml")}
    unknown = sorted(set(named) - on_disk)
    assert not unknown, (
        f"entry 6 names workflow file(s) that do not exist: {unknown}; .github/workflows holds "
        f"{sorted(on_disk)}. A reader following the entry would register a publisher for a "
        "workflow that can never run, and the mismatch surfaces as a refused upload on a release")


def test_the_environment_is_the_same_string_in_the_workflow_and_in_entry_six(workflow):
    """One environment name, three sites, all three compared.

    The workflow's `environment:` is what GitHub puts in the OIDC token. Entry 6's table is what a
    human types into PyPI. `ENVIRONMENT` above is this module's own copy, so that changing both of
    the other two in one edit still fails here rather than agreeing its way past the check.
    """
    match = re.search(r"environment:\s*\n\s*name:\s*([A-Za-z0-9_.-]+)", workflow)
    assert match, (
        "the publish job declares no `environment:` name. Without it PyPI cannot match on an "
        "environment claim, so a trusted publisher registered with an Environment name would "
        "refuse this workflow — and one registered WITHOUT it would accept a token from any job "
        "in this repository, which is a much broader grant than intended")
    in_workflow = match.group(1)
    assert in_workflow == ENVIRONMENT, (
        f"the workflow publishes in environment {in_workflow!r}, this module expects "
        f"{ENVIRONMENT!r}. If the environment was renamed, three things move together: this "
        "constant, entry 6's table, and the trusted publisher on pypi.org. The third is not "
        "checkable from here, which is why the other two are")
    assert f"`{ENVIRONMENT}`" in entry_six(), (
        f"PUBLICATION.md entry 6 does not name the {ENVIRONMENT!r} environment. It is one of the "
        "four values PyPI matches on and the entry is what a human reads while filling the form")


def test_entry_six_names_the_repository_the_rest_of_the_file_does():
    """The owner and repository in entry 6 are the ones `canonical_owner()` already derives.

    Not a second copy of the owner: `tests/test_cdm_publication.py` derives it from this file's
    first sentence and sweeps the tree against it. This only requires entry 6 to be inside that
    sweep's reach rather than stating the pair some other way.
    """
    entry = entry_six()
    for value, why in ((PROJECT, "the PyPI project being published"),
                       ("synapsecommand-public", "the repository name PyPI matches on")):
        assert value in entry, (
            f"entry 6 does not name {value!r} ({why}). Every value the PyPI form takes has to be "
            "readable off the entry, because the entry is written to be followed by someone who "
            "was not in the conversation that produced it")


# --------------------------------------------------------------- no credential, now or by accident


def test_the_workflow_carries_no_credential_of_any_kind(workflow):
    """The point of the round, as an assertion.

    A `password:` or a `secrets.` reference appearing here would mean Trusted Publishing had been
    abandoned — probably as a quick fix for a refused upload during a release, which is exactly
    when nobody is reading carefully. Entry 6 would then be describing a mechanism that is no
    longer in use.
    """
    offenders = []
    for number, line in enumerate(workflow.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue  # see _executable(): the header explains these patterns and would match them
        for pattern in (r"secrets\.\w+", r"^\s*password:", r"^\s*user:\s*__token__",
                        r"pypi-AgEIcHlwaS5vcmc"):
            if re.search(pattern, line):
                offenders.append(f"{number}: {line.strip()[:90]}")
    assert not offenders, (
        f"the publish workflow references a credential: {offenders}. This file publishes over "
        "OIDC and must contain no token, password or secret. If an upload was refused, the fix is "
        "on pypi.org — register or correct the trusted publisher per PUBLICATION.md entry 6 — not "
        "a token pasted in here, which would retire the mechanism and leave the ledger wrong")


def test_nothing_uploads_to_testpypi_implicitly(workflow):
    """A preview lane, if it is ever added, is an explicit trigger and not a silent second upload.

    Ledger entry 5 records that the 1.0.0 release skipped its own TestPyPI preview step and that
    this was found out afterwards from a 404. The lesson is not "upload twice on every tag": that
    is a second irreversible act nobody asked for, on an index whose filenames are also permanent.
    """
    live = [line for line in workflow.splitlines() if not line.lstrip().startswith("#")]
    hits = [line.strip() for line in live if targets_testpypi(line)]
    assert not hits, (
        f"the workflow targets TestPyPI in executable YAML: {hits}. A preview belongs on its own "
        "explicit trigger with its own environment, so that running it is a decision and skipping "
        "it is visible — which is the failure entry 5 recorded about itself")


# ------------------------------------------------------------------ provenance: pins, not pointers


def test_every_action_is_pinned_to_a_commit_and_not_to_a_tag(workflow):
    """A tag is movable, and this workflow's entire purpose is provenance.

    `v1` and `v1.14.2` alike can be repointed by whoever owns the action, so a tag reference means
    "whatever that account publishes next" — which is the trust OIDC was adopted to remove, put
    back one layer down. Note that `pypa/gh-action-pypi-publish` uses ANNOTATED release tags: the
    tag object's SHA is not a commit SHA, and pinning that value would pin a tag object rather than
    the code. The pin has to be the dereferenced commit.
    """
    uses = re.findall(r"^\s*uses:\s*(\S+)", workflow, re.MULTILINE)
    assert uses, "the workflow uses no actions at all, so this check is asserting nothing"
    unpinned = [u for u in uses if not re.fullmatch(r"[^@]+@[0-9a-f]{40}", u)]
    assert not unpinned, (
        f"these actions are not pinned to a full commit SHA: {unpinned}. Use "
        "owner/action@<40 hex> with the tag it corresponded to in a trailing comment, and change "
        "both in the same commit when updating")


def test_every_pin_records_the_tag_it_came_from(workflow):
    """The SHA is the pin; the comment is how a human knows what they are looking at.

    A bare 40-character hex string is unreviewable — nobody can tell v1.14.2 from an arbitrary
    commit on a fork's default branch. The comment does not authorise anything and is not checked
    against GitHub; it exists so that updating a pin is a legible diff rather than one opaque
    string replacing another.
    """
    missing = [line.strip() for line in workflow.splitlines()
               if re.search(r"^\s*uses:\s*\S+@[0-9a-f]{40}", line)
               and not re.search(r"#\s*v?\d", line)]
    assert not missing, (
        f"these pins name no version in a trailing comment: {missing}. Write `# v1.2.3` after the "
        "SHA so the next person can see what the pin is meant to be")


# ------------------------------------------------------------------ the publish job's own gating


#: A job header is two spaces, a name, a colon and nothing else. Matching "two spaces then
#: anything" also matches this file's own section-divider comments, which is how the first draft of
#: `test_the_jobs_realise_section_50s_order` reported six comment lines as jobs.
_JOB_HEADER = re.compile(r"^  ([a-z][a-z0-9_-]*):[ \t]*$", re.MULTILINE)


def _job_blocks(workflow: str) -> dict[str, str]:
    """Each job's name mapped to its text, without a YAML parser."""
    body = workflow[workflow.index("\njobs:"):]
    matches = list(_JOB_HEADER.finditer(body))
    return {m.group(1): body[m.start():(matches[i + 1].start() if i + 1 < len(matches) else len(body))]
            for i, m in enumerate(matches)}


def needs_of(workflow: str) -> dict[str, list[str]]:
    """Each job's `needs:`, in either spelling, without a YAML parser.

    PyYAML is not a dependency of this repository (`tests/test_cdm_security_policy.py` records the
    same absence), and the two spellings Actions accepts — `needs: build` and `needs: [a, b]` — are
    a two-line regex. A parser would be a dependency added to read one key.
    """
    out: dict[str, list[str]] = {}
    for name, block in _job_blocks(workflow).items():
        match = re.search(r"^    needs:\s*(.+)$", block, re.MULTILINE)
        if match is None:
            out[name] = []
            continue
        value = match.group(1).strip()
        out[name] = [n.strip() for n in value.strip("[]").split(",") if n.strip()]
    return out


def test_the_publish_job_is_reachable_only_by_a_tag_and_only_after_the_gate(workflow):
    """Three conditions, all of them in the file: after the gate chain, on a tag, in the environment.

    Any one of them missing turns a dispatch run — or a push to a branch — into an upload. That is
    an irreversible act, so it is not enough for the current triggers to make it unlikely.

    **THIS USED TO READ `needs: build` AND THAT WAS THE WRONG ASSERTION, 2026-09-08 (round P7).**
    The property is that nothing can upload before everything that gates the upload has passed, and
    a literal job name is a proxy for it that stops being true the moment a stage is inserted — as
    §50's order required here, where `attest` now sits between `build` and `publish`. Reading one
    name would have failed on a change that made the guarantee STRONGER, which is how a check gets
    deleted rather than fixed. So the chain is walked instead, and the assertion is what it was
    always meant to be: `publish` transitively needs `gate`.
    """
    publish = workflow[workflow.index("\n  publish:"):]
    needs = needs_of(workflow)
    assert "publish" in needs, "there is no publish job"

    reached, frontier = set(), list(needs.get("publish", []))
    assert frontier, ("the publish job declares no `needs:` at all, so an upload could start while "
                      "the gate is still running or after it has failed")
    while frontier:
        job = frontier.pop()
        if job in reached:
            continue
        reached.add(job)
        frontier.extend(needs.get(job, []))
    assert "gate" in reached, (
        f"the publish job does not depend on `gate`, even transitively: it reaches {sorted(reached)}. "
        "Every stage that gates the upload has to be upstream of it, or the upload is not gated")
    assert "build" in reached, (
        f"the publish job does not depend on `build`: it reaches {sorted(reached)}. It uploads "
        "the artefact `build` produced, so an upload that did not wait for it uploads nothing or "
        "something stale")

    assert re.search(r"if:\s*startsWith\(github\.ref,\s*'refs/tags/v'\)", publish), (
        "the publish job has no tag guard. Without `if: startsWith(github.ref, 'refs/tags/v')` a "
        "workflow_dispatch run — the thing that exists so the build half can be tested — would "
        "publish to PyPI")
    assert re.search(r"id-token:\s*write", publish), (
        "the publish job does not request `id-token: write`, so it cannot mint an OIDC token and "
        "the upload has no credential at all")


def _executable(text: str) -> str:
    """The YAML with comment lines dropped.

    Every sweep in this module that looks for a FORBIDDEN string needs this. The first draft of
    the check below searched the whole header and failed on the header's own paragraph explaining
    why `id-token` must not be there — prose about a rule read as a breach of it. It is the same
    shape `tests/test_cdm_generator_loading.py` records about one of its own sweeps, which keyed on
    `compile(` and matched a module's `re.compile` calls.

    Checks that look for a REQUIRED string do not use this, because several of them are deliberately
    about what the comments say.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_oidc_permission_is_not_granted_to_the_whole_workflow(workflow):
    """`id-token: write` on the publish job alone, never at the top level.

    At workflow level, every job can mint a token that PyPI would accept — including the job that
    runs the test suite, which executes far more code than the publish job does.
    """
    head = _executable(workflow[:workflow.index("\njobs:")])
    assert "id-token" not in head, (
        "`id-token` appears in the workflow-level permissions block. Grant it on the publish job "
        "only: a token mintable by the job that runs the suite is a token mintable by anything "
        "the suite imports")
    assert re.search(r"^permissions:\s*\n\s*contents:\s*read\s*$", head, re.MULTILINE), (
        "the workflow does not set a read-only default `permissions:` block. Without one, jobs "
        "inherit whatever the repository's default is, which may be write")


def test_the_build_half_is_runnable_without_publishing(workflow):
    """`workflow_dispatch` exists, so the gated-build half can be exercised before a release.

    This is what makes the first half of the file testable at all. It is also why the tag guard
    above matters: the trigger that exists for testing must not be able to upload.
    """
    head = workflow[:workflow.index("\njobs:")]
    assert "workflow_dispatch" in head, (
        "the workflow has no `workflow_dispatch` trigger, so nothing in it can be exercised "
        "without cutting a release — and a mechanism first run during a release is a mechanism "
        "debugged during a release")


def test_the_environment_is_described_as_a_confirmation_and_not_as_review(workflow):
    """The header must not overstate what the reviewer gate is.

    `prevent_self_review` is off, because with one maintainer the only person who can push a tag is
    the only person who could approve it. So the gate stops a mistaken or automatic tag and does
    not stop a determined maintainer, and prose calling it "review" or "a second pair of eyes"
    would be describing a control that is not there. Entry 6 carries the same statement and the
    trigger for changing it — a second maintainer.

    This is the `tests/test_cdm_deploy_workflow.py` failure in its subtler form: not a mechanism
    that does not exist, but a mechanism weaker than the sentence describing it.
    """
    header = workflow[:workflow.index("\nname:")]
    assert "prevent_self_review" in header, (
        "the header does not mention `prevent_self_review`. Whether the approver may be the person "
        "who triggered the deployment is the difference between a confirmation prompt and a "
        "review, and the file should not let a reader assume the stronger one")
    assert "confirmation" in header.lower(), (
        "the header does not say the reviewer gate is a confirmation step. If "
        "`prevent_self_review` has since been turned ON, this test is what should change — and "
        "PUBLICATION.md entry 6, which names a second maintainer as the trigger for doing it")


def test_the_header_records_the_run_that_first_exercised_the_publish_job(workflow):
    """INVERTED. This required the header to say the publish job had NEVER RUN.

    Its old form looked for the literal `NEVER RUN` and carried its own instruction: "Once the
    publish job HAS run, this is the paragraph that changes." 1.1.0 ran it, the paragraph changed —
    and the test still passed, because the rewritten paragraph opens by QUOTING the phrase it
    retires ("used to say the publish job had NEVER RUN"). A required-substring check cannot tell a
    claim from a quotation of one, so it had become vacuous in the worst way: green on a header
    asserting the opposite of what it was written to enforce.

    That is the same trap this repository has now hit three times, and the other two were in the
    FORBIDDEN direction — prose explaining a rule, matched as a breach of it. This is its mirror:
    prose retiring a claim, matched as the claim. Neither is fixable by a cleverer regex, because
    both readings are legitimate English. What fixes it is noticing that the gate's PREMISE expired
    and inverting it, which is what this is.

    The premise now is the opposite one and it is equally worth defending: the header must name the
    run that first published, so nobody can claim the lane is unproven, and nobody can claim it
    proved more than it did. `NEVER RUN` is no longer required and no longer forbidden — quoting
    history is fine; what is checked is the positive statement.
    """
    header = workflow[:workflow.index("\nname:")]
    for fragment, why in (
            ("32944124955", "the run id that first exercised the publish job"),
            ("1.1.0", "the release it published"),
            ("workflow_dispatch", "which trigger proved the build half first"),
            ("OIDC", "how the upload was authenticated")):
        # `id-token` is deliberately NOT required here. It is the subject of
        # `test_the_oidc_permission_is_not_granted_to_the_whole_workflow`, which strips comments
        # before looking — so requiring the string in the commented header while another test
        # forbids it in the executable header is two checks reading one string two ways, and the
        # first draft of this test failed on exactly that.
        assert fragment in header, (
            f"the workflow header no longer states {why} (looked for {fragment!r}). The header is "
            "where a reader learns what this file has actually been shown to do; a run id is the "
            "only form of that claim anybody can check")
    assert "not to paste a token in here" in header or "NOT to paste a token" in header, (
        "the header no longer says what to do when an upload is REFUSED. That path is still "
        "unexercised — the configuration was right the first time — and the tempting fix during a "
        "failed release is a token, which would retire the whole mechanism to save one upload")


# ------------------------------------------------- the two procedures, collected so they cannot fight
#
# There are now two documented ways to get a distribution onto PyPI: the workflow, and `twine
# upload` by hand. That is a deliberate pair — an undocumented fallback gets improvised under
# pressure, which is worse than a written one — and a deliberate pair is exactly what drifts. The
# failure to fear is not that one of them is wrong. It is that a reader lands on the wrong one and
# cannot tell, because whichever document they opened presented its own path as the procedure.
#
# So every site that states a publishing mechanism is collected here, and each is required to say
# the same two things: the workflow is how a release publishes, and the manual path is a fallback.

#: Documents that describe how publishing happens, and are read by different people. README is the
#: first thing a stranger opens; MIGRATIONS is what a maintainer opens to cut a release;
#: PUBLICATION is the record. A mechanism claim in any of them is a claim to a real audience.
PUBLISHING_SITES = (
    "README.md",
    "packages/cdm/synapse_cdm/MIGRATIONS.md",
    "PUBLICATION.md",
)

#: The wordings that mean "run twine yourself". Matched case-insensitively.
MANUAL_MARKERS = ("twine upload", "twine.upload")

#: The wordings that mark a passage as the fallback rather than the procedure. Any one is enough.
FALLBACK_MARKERS = ("fallback", "not the procedure", "by hand", "manual")


def _sites():
    for name in PUBLISHING_SITES:
        path = REPO / name
        assert path.exists(), f"{name} is gone; this collection is asserting over nothing"
        yield name, path.read_text()


def _inside_a_closed_ledger_entry(text: str, position: int) -> bool:
    """Is `position` inside a `### N. ... — CLOSED` entry of PUBLICATION.md's ledger?

    THE EXEMPTION, AND WHY IT IS STRUCTURAL RATHER THAN A KEYWORD
    ------------------------------------------------------------
    Entry 5 records the 1.0.0 upload: "`twine check --strict` on both artefacts, then `twine upload
    packages/cdm/dist/*`", and its sequence table has a `twine upload` row. Those are the sweeps
    below finding real text — and they are not instructions. They are a dated account of an act
    that happened, in an entry whose heading says CLOSED, and the ledger's own discipline is that a
    closed entry is never edited: it records what was known when it closed and carries a
    superseding pointer when that stops being true.

    The exemption is therefore the closed heading and not a word in the paragraph. A keyword
    exemption — "allow it near the word 'record'" — would let any passage anywhere opt out of these
    checks by mentioning a record. This one can only be claimed by text a human deliberately marked
    CLOSED in a numbered ledger, which is a much smaller door and one the ledger's other gates
    already watch.

    An OPEN entry gets no exemption. An open entry is live text about what should happen next, and
    that is exactly where a stale instruction does damage.
    """
    heading = None
    for match in re.finditer(r"\n### (\d+)\. (.+)", text):
        if match.start() > position:
            break
        heading = match.group(2)
    return heading is not None and "CLOSED" in heading


def test_every_document_that_mentions_twine_upload_marks_it_as_the_fallback():
    """`twine upload` may appear anywhere, provided the passage says what it is.

    Not a ban: the fallback is documented on purpose. The requirement is that a reader who lands on
    it learns, in the same breath, that it is not how releases happen — because the version of this
    document that presented it as the procedure was correct when written, and a reader cannot date
    a paragraph.
    """
    offenders = []
    for name, text in _sites():
        low = text.lower()
        for marker in MANUAL_MARKERS:
            start = 0
            while (found := low.find(marker, start)) != -1:
                start = found + len(marker)
                # The claim's neighbourhood, not the whole document: a "fallback" heading four
                # sections away does not qualify a command a reader is looking at right now.
                window = low[max(0, found - 1200):found + 600]
                if any(flag in window for flag in FALLBACK_MARKERS):
                    continue
                if _inside_a_closed_ledger_entry(text, found):
                    continue  # a dated record, not an instruction — see _inside_a_closed_ledger_entry
                line = text[:found].count("\n") + 1
                offenders.append(f"{name}:{line}")
    assert not offenders, (
        f"these mention a manual upload without marking it as a fallback: {offenders}. Releases "
        "publish through .github/workflows/publish.yml; a `twine upload` that reads as the "
        "procedure sends a reader to an upload with no gate run against the artefact, no record in "
        "the Actions log, and a need for the API token PUBLICATION.md entry 6 retires. Say "
        f"'fallback' — or one of {FALLBACK_MARKERS} — near the command")


def test_every_document_that_describes_releasing_names_the_workflow():
    """Whoever states how a release publishes must name the file that does it.

    The two-site failure this guards is not hypothetical here. MIGRATIONS said "a release is a
    sequence a person runs" and was right for a round after it stopped being right, and README
    said nothing at all about releasing, so there was no second site to disagree with it. Silence
    is the version of drift that no comparison catches, which is why this requires a positive
    statement rather than forbidding a wrong one.
    """
    missing = []
    for name, text in _sites():
        low = text.lower()
        if not any(m in low for m in MANUAL_MARKERS) and "publish" not in low:
            continue
        if "publish.yml" not in text:
            missing.append(name)
    assert not missing, (
        f"these describe publishing without naming the workflow that does it: {missing}. The "
        "filename is load-bearing — PyPI matches the OIDC token against the workflow path — so a "
        "document that says 'CI publishes it' is a document nobody can check against the tree")


def test_no_document_still_says_publishing_is_unautomated():
    """The retired claim, swept across every site rather than the one that had it.

    MIGRATIONS carried this and `tests/test_cdm_release.py` now forbids it there. It is swept here
    too, because the sentence was copyable and the next place it would appear is a document that
    was written while it was true — README's release section, or a docs page, added later from an
    older mental model.
    """
    banned = (
        "no ci in this repository",
        "there is no ci",
        "publishing to pypi is not automated",
        "a release is a sequence a person runs",
    )
    offenders = []
    for name, text in _sites():
        low = text.lower()
        for phrase in banned:
            found = low.find(phrase)
            if found == -1:
                continue
            # PUBLICATION.md's closed entry 5 is a dated record and keeps its wording; it carries a
            # superseding pointer instead. A record of what was believed is not a claim.
            window = low[max(0, found - 1500):found + 800]
            if "superseded" in window:
                continue
            offenders.append(f"{name}:{low[:found].count(chr(10)) + 1}: {phrase!r}")
    assert not offenders, (
        f"these still say publishing is unautomated: {offenders}. It is automated. If a passage is "
        "a dated RECORD of what was believed rather than a present claim, mark it superseded the "
        "way PUBLICATION.md entry 5 is — otherwise a reader takes it as current")


def test_the_fallback_is_documented_somewhere_rather_than_only_forbidden():
    """The pair must actually be a pair.

    A gate that only ever refuses the manual path would push it out of the documents and into
    somebody's shell history, which is the outcome all of this is trying to avoid. So a fallback
    has to EXIST in writing, with its costs stated.
    """
    text = (REPO / "packages/cdm/synapse_cdm/MIGRATIONS.md").read_text()
    assert "The manual fallback" in text, (
        "MIGRATIONS.md documents no manual fallback. If the workflow is broken during an incident, "
        "somebody will upload by hand regardless; the choice is whether they do it from a written "
        "procedure that names what is lost, or from memory")
    section = text[text.index("The manual fallback"):]
    section = section[:section.find("\n## ") if "\n## " in section else len(section)]
    for cost, why in (("no record", "that nothing logs the upload"),
                      ("entry 6", "that it needs the credential being retired")):
        assert cost in section.lower() or cost in section, (
            f"the manual fallback does not state {why}. A fallback whose costs are not written is "
            "a second procedure, not a fallback")


# ------------------------------------------------------- §50's pipeline, added by round P7 (2026-09-08)

#: §50's required order, as job names. The specification's diagram is the authority; this is it
#: transcribed, and `test_the_jobs_realise_section_50s_order` is what holds the file to it.
SECTION_50_ORDER = ("gate", "build", "attest", "publish", "release", "witness")

#: Which job may hold which write permission. Anything not listed here holds none of them, and
#: that is the assertion — a permission is a thing you grant to one job, not a thing a file has.
PERMITTED_WRITES = {
    "id-token: write": {"publish", "attest"},
    "attestations: write": {"attest"},
    "contents: write": {"release", "witness"},
}

#: The jobs that must never run without a tag. Each of them either performs an irreversible act or
#: records one, and a dispatch run reaching any of them would be a release nobody asked for.
TAG_ONLY = ("publish", "release", "witness")


def jobs_in_order(workflow: str) -> list[str]:
    return list(_job_blocks(workflow))


def job_block(workflow: str, name: str) -> str:
    blocks = _job_blocks(workflow)
    assert name in blocks, f"no job named {name}: the file declares {list(blocks)}"
    return blocks[name]


def test_the_jobs_realise_section_50s_order(workflow):
    """One job per stage boundary, each `needs:` the one before it.

    §50 fixes an ORDER, and an order enforced by the dependency graph is enforced; an order that is
    only the sequence the steps happen to be written in is a convention. The difference shows up
    the first time somebody adds a stage in the wrong place.
    """
    assert jobs_in_order(workflow) == list(SECTION_50_ORDER)
    needs = needs_of(workflow)
    for earlier, later in zip(SECTION_50_ORDER, SECTION_50_ORDER[1:]):
        assert earlier in needs[later], (
            f"`{later}` does not declare `needs: {earlier}`, so §50's order is not enforced by "
            f"anything: it reads {needs[later]}")


@pytest.mark.parametrize("job", TAG_ONLY)
def test_every_irreversible_job_is_reachable_only_by_a_tag(workflow, job):
    """`workflow_dispatch` exercises the pipeline up to the upload and no further."""
    assert re.search(r"if:\s*startsWith\(github\.ref,\s*'refs/tags/v'\)", job_block(workflow, job)), (
        f"the `{job}` job has no tag guard. `workflow_dispatch` exists so the gated half can be "
        "tested on a branch; a stage without this guard turns that test into a release")


def test_the_stages_before_the_upload_carry_no_tag_guard(workflow):
    """The other half of the same property: a dispatch must actually exercise them."""
    for job in ("gate", "build", "attest"):
        assert "startsWith(github.ref, 'refs/tags/v')" not in job_block(workflow, job).split(
            "steps:")[0], (
            f"the `{job}` job is guarded to tags, so a dispatch run would skip it and prove "
            "nothing — which is the whole reason the dispatch trigger exists")


@pytest.mark.parametrize("permission,allowed", sorted(PERMITTED_WRITES.items()))
def test_each_write_permission_is_granted_to_the_jobs_that_need_it_and_no_others(
        workflow, permission, allowed):
    """Least privilege, checked per job rather than believed per file."""
    holders = {name for name in jobs_in_order(workflow)
               if re.search(rf"^\s*{re.escape(permission)}\s*$",
                            _executable(job_block(workflow, name)), re.MULTILINE)}
    assert holders == allowed, (
        f"`{permission}` is held by {sorted(holders)} and should be held by {sorted(allowed)}. A "
        "permission on a job that does not need it is a permission everything that job runs has")


def test_the_four_release_conditions_survived_the_restructure_verbatim(workflow):
    """The untouchable of this file's history: conditions are added to, never edited.

    They moved between jobs — 1 and 3 are the gate's, 2 and 4 are the build's, because 2 and 4 read
    `dist/` and `dist/` is what the build makes — and not one word of any of them changed.
    """
    for condition in ("Condition 1 — the suite is green",
                      "Condition 2 — the gate, including the mutation check",
                      "Condition 3 — the tag names this tree's PACKAGE_VERSION",
                      "Condition 4 — the derivations, for notes that are derived and not remembered"):
        assert workflow.count(f"- name: {condition}") == 1, (
            f"`{condition}` appears {workflow.count(f'- name: {condition}')} times. MIGRATIONS.md's "
            "conditions are this file's contract; they are moved, never reworded and never dropped")
    assert "python -m pytest -q -rs" in workflow, "condition 1 no longer runs the suite"
    assert "python gates/wheel_install.py --mutation-check --export-dist dist" in workflow, (
        "condition 2 no longer runs the gate with the mutation check and the one build")
    assert "the annotated-tag" not in workflow.lower() or "git cat-file -t" in workflow, (
        "the annotated-tag check is named but not performed")


def test_condition_4_is_still_described_as_a_persons(workflow):
    """The renderer added by §52 does not take condition 4 over, and the file must not imply it did.

    "Derived" is a claim about what the WRITER read. A generated file does not satisfy it, the
    header says so, and `synapse release-notes` refuses rather than inventing the one field that
    is a person's.
    """
    assert "CANNOT RUN HERE" in workflow
    assert "it is still a" in workflow and "person's" in workflow


def test_the_conformance_sweep_is_one_artefact_and_not_a_loop(workflow):
    """§53 hashes it. Fourteen files produced by a shell loop have no digest to record."""
    gate = _executable(job_block(workflow, "gate"))
    assert "conformance run --all" in gate, (
        "the gate does not run the sweep with `--all`, so there is no single conformance artefact "
        "for the notes to summarise or for the witness record to hash")
    assert "for adapter in" not in gate, (
        "the gate sweeps with a shell loop; §50's conformance stage is one invocation producing "
        "one document, because `conformance_sha256` is a digest of a file")


def test_the_release_carries_the_full_asset_set(workflow):
    """F7.4's default, as an assertion rather than as a ruling nobody reads again."""
    release = _executable(job_block(workflow, "release"))
    for asset in ("dist/*", "SHA256SUMS", "synapse_cdm.spdx.json", "synapse_cdm.cdx.json",
                  "evidence-${version}.tar.gz", "conformance-${version}.json",
                  "release-notes-${version}.md"):
        assert asset in release, f"the Release does not attach {asset}"


def test_the_release_notes_are_rendered_and_not_written_in_the_workflow(workflow):
    release = _executable(job_block(workflow, "release"))
    assert "release-notes" in release and "--from RELEASE_NOTES.md" in release, (
        "the release job does not render §52's notes from the tree")
    assert "--verify-tag" in release, (
        "`gh release create` without `--verify-tag` will create a tag that does not exist rather "
        "than refusing, which is a release pointing at a commit nobody tagged")


def test_the_witness_record_is_produced_after_the_release_and_not_committed(workflow):
    """§53, and RUNNER.md's hard limit that a workflow does not commit."""
    witness = _executable(job_block(workflow, "witness"))
    assert "build_witness.py" in witness and "witness_verify.py" in witness, (
        "the witness job does not both build and verify the record; a record nothing verified is "
        "a file asserting its own correctness")
    assert "gh release upload" in witness
    for forbidden in ("git commit", "git push", "add-and-commit"):
        assert forbidden not in witness, (
            f"the witness job runs `{forbidden}`. RUNNER.md's hard limits: only the runner commits, "
            "and the witness round is what commits the record")


def test_the_pipeline_names_a_script_that_exists(workflow):
    """A workflow referencing a file nobody shipped fails at release time and nowhere earlier."""
    for script in re.findall(r"(?:python |bash )?(\.github/scripts/\S+\.py|gates/\S+\.py)", workflow):
        assert (REPO / script).is_file(), f"the workflow runs {script}, which is not in the tree"


# ------------------------------------------------- §46: the SBOM, and the paths the ref must not name
#
# Round PS, 2026-09-08. Round P8's qualification dispatched this workflow and it failed in `build`
# at the SPDX step, for two reasons that are one shape: a path nobody could have taken and a
# document nobody could have used. The step read
# `file: dist/synapse_cdm-${{ github.ref_name }}-py3-none-any.whl`, which on the dispatch named
# `synapse_cdm-soif/1.0-py3-none-any.whl` and on a `v2.1.0` tag would have named
# `synapse_cdm-v2.1.0-py3-none-any.whl` — a wheel is named by its packaging metadata, so neither
# file has ever existed. And had the path been right, syft over a `.whl` FILE catalogues one SPDX
# package (the filename) and zero CycloneDX components, so the green step would have published an
# SBOM naming no dependency of anything. The four assertions below are M's rulings of the same day.

#: The ways this workflow can name the ref it was triggered by.
REF_TOKENS = ("github.ref_name", "GITHUB_REF_NAME")

#: What a release artefact looks like in a path. A ref token and one of these on one line is the
#: defect: `${GITHUB_REF_NAME#v}` compared against `PACKAGE_VERSION` is the ref used as a VERSION,
#: which is its only legitimate use here, and no legitimate use builds a filename.
ARTEFACT_TOKENS = ("dist/", ".whl", ".tar.gz", "sbom/", "SHA256SUMS")

#: The action and step inputs that name a file or a directory. A ref token in one of these is the
#: exact line round P8's dispatch died on.
PATH_INPUTS = ("file:", "path:", "output-file:", "artifact-name:")


def test_no_artefact_path_in_this_workflow_is_built_from_the_git_ref(workflow):
    """M's ruling of 2026-09-08: `do not use the raw git ref/tag to construct the artifact path`.

    The ref is legitimate as a VERSION — `${GITHUB_REF_NAME#v}` compared against
    `PACKAGE_VERSION`, or handed to `gh release` as the name of the release — and never as part of
    a filename. Both halves are checked because both are cheap: no line pairs a ref with an
    artefact path, and no action input that names a file or a directory carries a ref at all.
    """
    for name in jobs_in_order(workflow):
        for line in _executable(job_block(workflow, name)).splitlines():
            if not any(ref in line for ref in REF_TOKENS):
                continue
            named = [token for token in ARTEFACT_TOKENS if token in line]
            assert not named, (
                f"the `{name}` job builds a path from the git ref: {line.strip()!r} names "
                f"{named}. Round P8's dispatch failed on exactly this line — a wheel is named "
                "by PACKAGE_VERSION, and a ref-derived path is wrong on a branch and wrong on a "
                "tag")
            stripped = line.strip()
            for prefix in PATH_INPUTS:
                assert not stripped.startswith(prefix), (
                    f"the `{name}` job passes the git ref to a `{prefix}` input: "
                    f"{stripped!r}. That input is a path, and a path derived from the ref is the "
                    "defect round PS repaired")


def test_the_release_artefacts_are_named_from_package_version_and_exported_once(workflow):
    """One step computes the two names, refuses a `dist/` it cannot account for, and exports them.

    M's ruling: compute the filename from the package name and PACKAGE_VERSION, fail if the
    expected wheel is missing, fail if more than the expected release artefact would create
    ambiguity, and do not use an unconstrained `dist/*.whl` glob. A glob is not a smaller version
    of this: it hashes and uploads whatever it happens to find, which is how a stale wheel from an
    earlier step gets published under a digest nobody derived.
    """
    build = _executable(job_block(workflow, "build"))
    assert "from synapse_cdm.version import PACKAGE_VERSION" in build, (
        "the build job never asks the package for its version, so every artefact name in it is "
        "either a glob or a guess")
    for exported in ("VERSION=${version}", "WHEEL=${wheel}", "SDIST=${sdist}"):
        assert exported in build, (
            f"the build job does not export {exported} into $GITHUB_ENV. The names are computed "
            "once and read by every later step, or they are computed differently in each of them")
    assert '"${held}" != "2"' in build, (
        "nothing refuses a `dist/` holding more or fewer than the wheel and the sdist. M's "
        "ruling: fail if more than the expected release artefact would create ambiguity")
    assert '[ ! -f "${artefact}" ]' in build, (
        "nothing refuses a MISSING expected artefact, which is the failure round P8 hit: the "
        "path was computed, the file was not there, and the step that used it reported the "
        "absence as its own kind of error")
    assert "dist/*.whl" not in build, (
        "the build job still resolves a release artefact through an unconstrained glob")


def test_the_release_sbom_is_taken_over_the_clean_install_environment(workflow):
    """M's ruling: syft over the clean venv, `cyclonedx-py` over the same one, in that order.

    The subject of the SBOM is the environment, not the wheel file: an SBOM over the file names
    the file and stops, and what a consumer of a release needs is the closure that got installed.
    The order is part of the property — an SBOM taken before the install describes an environment
    that does not exist yet — and it is checked as an order of steps, since nothing else in the
    file enforces it.
    """
    build = job_block(workflow, "build")
    executable = _executable(build)
    assert 'echo "CLEAN_VENV=/tmp/clean" >> "${GITHUB_ENV}"' in executable, (
        "the clean-install step does not export the venv it created, so any SBOM step below it "
        "names a directory of its own and the two can drift apart silently")
    assert executable.count("path: ${{ env.CLEAN_VENV }}") == 2, (
        "both syft SBOMs are not taken over the exported clean venv: the file points them at "
        f"{executable.count('path: ${{ env.CLEAN_VENV }}')} such path(s)")
    assert 'cyclonedx-py environment "${CLEAN_VENV}/bin/python"' in executable, (
        "the cross-check does not run over the same environment. M's ruling of 2026-09-08 names "
        "cyclonedx-py over that venv, and a cross-check over a different environment compares "
        "nothing")
    assert "--output-file /tmp/environment.cdx.json" in executable, (
        "the cross-check writes into the released artefact set. `sbom/` is hashed into "
        "SHA256SUMS and handed to the release job, and P6's default 4 — the release artefacts "
        "are syft's — is what keeps a second producer's document out of it")
    order = [
        "- name: Clean install from the built package",
        "- name: SBOM — SPDX",
        "- name: SBOM — CycloneDX",
        "- name: SBOM cross-check",
        "- name: The SBOMs describe this release",
    ]
    positions = []
    for step in order:
        assert step in build, f"the build job has no step `{step}`"
        positions.append(build.index(step))
    assert positions == sorted(positions), (
        "the SBOM steps do not run after the clean install and before the assertion: the build "
        f"job orders them {[order[i] for i in sorted(range(len(order)), key=positions.__getitem__)]}")


def test_the_sbom_assertions_refuse_the_four_things_m_ruled(workflow):
    """`the release pipeline MUST fail if` — four conditions, and the step that fails on them.

    Generation succeeding is not the property. A file that parses as an SBOM and describes
    nothing passes every check a workflow makes about exit statuses, which is what the wheel-file
    SBOM did: one SPDX package, zero CycloneDX components, both steps green.
    """
    build = _executable(job_block(workflow, "build"))
    step = build[build.index("- name: The SBOMs describe this release"):]
    step = step[:step.index("- name: Fetch the gate")]
    for refusal, why in (
            ("carries no packages[] entry at all", "an empty SPDX document"),
            ("carries no components[] entry at all", "an empty CycloneDX document"),
            ("names no synapse-cdm entry", "an SBOM that does not mention the package"),
            ("PACKAGE_VERSION is", "a version that is not the one being released"),
            ("set -euo pipefail", "a generation step that failed"),
    ):
        assert refusal in step, f"nothing in the assertion step refuses {why} ({refusal!r})"
    assert 'r"[-_.]+"' in step, (
        "the assertion compares names without normalising them PEP 503 style. syft and "
        "cyclonedx-py need not spell the distribution the same way, and `synapse_cdm` failing a "
        "check for `synapse-cdm` is a release blocked by punctuation")
