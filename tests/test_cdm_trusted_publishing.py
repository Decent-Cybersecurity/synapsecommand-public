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
    hits = [line.strip() for line in live if "test.pypi.org" in line]
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


def test_the_publish_job_is_reachable_only_by_a_tag_and_only_after_the_gate(workflow):
    """Three conditions, all of them in the file: after `build`, on a tag, in the environment.

    Any one of them missing turns a dispatch run — or a push to a branch — into an upload. That is
    an irreversible act, so it is not enough for the current triggers to make it unlikely.
    """
    publish = workflow[workflow.index("\n  publish:"):]
    assert re.search(r"^\s*needs:\s*build\s*$", publish, re.MULTILINE), (
        "the publish job does not declare `needs: build`, so an upload could start while the gate "
        "is still running or after it has failed")
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
