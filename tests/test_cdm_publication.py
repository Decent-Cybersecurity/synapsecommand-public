"""The publication record, and the three claims in it that the tree can decide for itself.

WHY THIS MODULE EXISTS
----------------------
`PUBLICATION.md` records what became true when this repository went public: the protections, the
probes that witnessed them, and sixteen ledger entries — thirteen settled, three still open. Most of it
is a *witness statement* — a force-push was refused, a check ran and failed and then passed — and
a witness statement is not gateable. The suite cannot reach GitHub, must not hold a token, and a test that needed one would
fail for every outsider and turn green only for whoever holds it.

But three of the claims are decidable **from the tree**, and each of the three is a claim that
had already gone wrong once:

1. **The unsigned history.** Stated for five rounds as "44 of 47 are signed" — a ratio that goes
   stale on the next commit. It is now a named set of three, and this module recomputes the set
   from the actual history and requires the two to be equal. A fourth unsigned commit fails the
   build; so does dropping one of the three from the table while it is still unsigned.
2. **The absence of per-file licence headers.** `NOTICE` asserted it as "none of its 769 tracked
   files", and by the day of publication the tree held 770. The count was never the claim; the
   absence was. So the absence is checked over every tracked file, both halves, and the count is
   gone from the prose entirely.
3. **Whether the `DCO` check is a required status.** `CONTRIBUTING.md` said it was, in a document
   published to the world, and it was not: the ruleset carries no `required_status_checks` rule.
   Nothing could have caught that from inside the tree — but the moment the true state is written
   down at a second site, the two sites can be required to agree, and the next half-edit fails a
   build instead of shipping.

THE SHAPE OF THE THIRD ONE, WHICH IS THE INTERESTING ONE
--------------------------------------------------------
The truth being tracked lives on GitHub, so no test can assert it. What a test *can* assert is
that the repository does not contradict itself about it: `PUBLICATION.md` records the state and
the pending decision, `CONTRIBUTING.md` tells a contributor what to expect, and the two must not
disagree. When the wiring is done, both sites change in the same commit or this module fails —
which is the whole point, because the failure mode being prevented is exactly the one that
happened: one site updated to describe an intention, the other left describing reality, and no
way to tell from the tree which was which.

This is the `tests/test_cdm_deploy_workflow.py` treatment applied to a platform setting rather
than to a deploy: the gate cannot check the fact, so it checks the agreement.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
It does not re-check anything another module owns. `tests/test_cdm_pins.py` enforces that no
pinned document is tracked and that `.gitignore` refuses to stage one; the no-bytes-ship claim in
`PUBLICATION.md` is checked here only in the sense that the claim must **name that gate**, so a
reader who wants the enforcement can find it. And `PUBLICATION.md` must NOT restate the deploy
mechanism: `tests/test_cdm_deploy_workflow.py` sweeps the tree for files describing it and
requires every one to be on its site list, so a third site would be a third thing to keep in
agreement for no gain. That constraint is asserted below rather than left as a convention,
because a convention nobody checks is how the mechanism drifted in the first place.
"""
import pathlib
import re
import subprocess

import pytest

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]

RECORD = "PUBLICATION.md"
GUIDE = "CONTRIBUTING.md"

#: This module quotes the sentences it checks, so a sweep that did not exclude it would find the
#: checker and call it a site. The same exclusion `tests/test_cdm_deploy_workflow.py` and
#: `tests/test_cdm_ordinals.py` both make, for the same reason.
SELF = "tests/test_cdm_publication.py"


def _read(rel: str) -> str:
    path = REPO / rel
    assert path.exists(), f"{rel} does not exist; this module's site list is stale"
    return path.read_text()


def _flat(text: str) -> str:
    """Whitespace-collapsed, so a sentence checked here survives being re-wrapped there."""
    return " ".join(text.split())


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def _require_git_history() -> None:
    """SKIP rather than FAIL where there is no history to read, and say which it is.

    An sdist and an unpacked wheel have the package and no `.git`. A hard failure there would be
    a test that reports a broken repository when what it actually found was a legitimate
    distribution form — and this repository's own rule is that an unrun check reports SKIP and
    never PASS. The skip names the reason so it cannot be mistaken for a pass.
    """
    if not (REPO / ".git").exists():
        pytest.skip("no .git in this tree, so the commit history cannot be read (an sdist or an "
                    "unpacked wheel is the normal case); the unsigned-commit set is unverifiable "
                    "here and is NOT asserted")


# ----------------------------------------------------------------- 1. the unsigned-commit ledger

#: The heading the table of unsigned commits lives under. Anchored to the heading rather than to
#: the whole file so that a table added elsewhere cannot satisfy this by accident.
UNSIGNED_HEADING = "### 2. Unsigned history: three commits, known and accepted"


def _record_section(heading: str) -> str:
    text = _read(RECORD)
    assert heading in text, (
        f"{RECORD} no longer contains the heading {heading!r}. This is a re-anchoring job and not "
        "a deletion: the section it names carries a ledger entry a future round has to act on, so "
        "find where it went and update this constant deliberately"
    )
    start = text.index(heading) + len(heading)
    rest = text[start:]
    nxt = re.search(r"\n#{2,3} ", rest)
    return rest[:nxt.start()] if nxt else rest


def _before_the_dated_notes(section: str) -> str:
    """A ledger entry with its appended dated notes cut off. The entry's own claim, in other words.

    **WHY THIS EXISTS, AND IT IS A DEFECT THIS ROUND CAUSED AND CAUGHT IN ONE RUN.** The two
    parsers below extract a SET OF COMMITS from a ledger entry by scanning it for backticked 8-hex
    strings. That was exact while an entry was a heading, a statement of its set, and prose about
    that set. On 2026-09-04 both entry 2 and entry 7 gained a dated note recording the `41d3d2d`
    incident, and those notes name other commits for good reasons — the replaced tip, the commit
    that replaced it, and the three carrying two well-formed sign-offs. **Every one was
    immediately read as a member of the set.** The gates failed instantly and by name, which is
    the only reason this is a footnote rather than an entry of its own.

    THE RULE, AND IT IS THE ONE THIS REPOSITORY ALREADY APPLIES TO APPEND-ONLY LOGS. A ledger entry
    states its set once and then accretes dated notes underneath, exactly as `klv_pin.json`'s
    header log does — and `tests/test_cdm_pin_header.py` reads the LAST clause of that log for the
    same reason this reads the FIRST part of an entry: each convention puts the current claim in a
    known place. So the set is whatever the entry says before its first `**DATED NOTE`, and a note
    may name as many commits as it needs to without being mistaken for the subject.

    A section with no dated note comes back unchanged, which is what every other entry is.
    """
    marker = "**DATED NOTE"
    return section.split(marker)[0] if marker in section else section


def stated_unsigned_commits() -> list[str]:
    """The abbreviated SHAs the record names as unsigned, in the order it names them.

    Read from the entry above its dated notes — see `_before_the_dated_notes`.
    """
    section = _before_the_dated_notes(_record_section(UNSIGNED_HEADING))
    found = re.findall(r"`([0-9a-f]{8})`", section)
    assert found, (
        f"no backticked 8-hex commit id found under {UNSIGNED_HEADING!r} in {RECORD}. Either the "
        "table changed shape — re-anchor this pattern deliberately — or the entry was deleted, "
        "which is a decision that needs to be made in the open and not by a regex that quietly "
        "matches nothing"
    )
    return found


def actual_unsigned_commits() -> list[str]:
    """Every commit reachable from HEAD with no `Signed-off-by` trailer, abbreviated to 8.

    Read through `--format` with `%(trailers:key=Signed-off-by,valueonly)` rather than by
    grepping the message body, because that is git's own notion of a trailer and it is the notion
    the DCO app applies: a line reading `Signed-off-by:` in the middle of a paragraph is not a
    trailer, and a check that disagreed with git about which lines are trailers would be checking
    a different thing from the one that gates a pull request.
    """
    out = _git("log", "--format=%H%x1f%(trailers:key=Signed-off-by,valueonly)%x1e")
    assert out.returncode == 0, f"git log failed: {out.stderr}"
    unsigned = []
    for record in out.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        sha, _, trailers = record.partition("\x1f")
        if not trailers.strip():
            unsigned.append(sha[:8])
    return unsigned


def test_the_record_names_three_unsigned_commits():
    """The floor is a hard three, because this is a CLOSED set and not a growing one.

    Every commit since `965e939d` has been signed and the project intends to keep it that way, so
    "three" is the number and `>= 1` would be a check that passes while two of the three quietly
    vanish from the table.
    """
    stated = stated_unsigned_commits()
    assert len(stated) == 3, (
        f"{RECORD} names {len(stated)} unsigned commits and the ledger entry is about three: "
        f"{stated}. If a fourth genuinely exists, the entry's prose has to change with it — it "
        "says the enforcement is forward-looking from a point, and a fourth would move the point"
    )
    assert len(set(stated)) == 3, f"the same commit is named twice: {stated}"


def test_the_unsigned_set_in_the_record_is_the_unsigned_set_in_the_history():
    """THE GATE. Recomputed from the history, not trusted from the table.

    Both directions matter and they catch different mistakes. A commit in the history and not in
    the table is an unsigned commit nobody has accepted — the case that turns "three known
    exceptions" into "some number of exceptions", which is the sentence the DCO story cannot
    survive. A commit in the table and not in the history is a table describing a repository that
    no longer exists: a rewrite happened, or a SHA was mistyped, and either way the record is
    now fiction.
    """
    _require_git_history()
    stated = set(stated_unsigned_commits())
    actual = set(actual_unsigned_commits())
    assert stated == actual, (
        f"the unsigned-commit ledger in {RECORD} and the history disagree.\n"
        f"  unsigned in the history, absent from the record: {sorted(actual - stated)}\n"
        f"  named in the record, not unsigned in the history: {sorted(stated - actual)}\n"
        "The record is the thing that is wrong here unless a history rewrite happened, which "
        f"{RECORD} states is not contemplated. Sign off the new commit rather than adding a row"
    )


def test_the_unsigned_check_is_not_vacuous():
    """A trailer reader that found nothing would agree with an empty table and with a wrong one.

    Asserted positively: the history must contain BOTH signed and unsigned commits for the
    comparison above to have any discriminating power. If every commit came back unsigned the
    parser is broken; if none did, the ledger entry describes nothing.
    """
    _require_git_history()
    out = _git("log", "--format=%H")
    assert out.returncode == 0, f"git log failed: {out.stderr}"
    total = len([line for line in out.stdout.splitlines() if line.strip()])
    unsigned = len(actual_unsigned_commits())
    assert total >= 40, (
        f"only {total} commits reachable from HEAD. This history had 48 at publication, so the "
        "walk is truncated (a shallow clone?) and the closure above is being checked against a "
        "fragment"
    )
    assert 0 < unsigned < total, (
        f"{unsigned} of {total} commits read as unsigned. Neither extreme is credible: the "
        "trailer reader has stopped seeing trailers, or it has stopped seeing their absence"
    )


def test_the_record_states_that_no_rewrite_is_contemplated():
    """The entry is only coherent WITH this sentence, so the sentence is load-bearing.

    Three accepted unsigned commits and a forward-looking check is a defensible position. Three
    unsigned commits with no stated policy reads as an oversight nobody noticed, which is the
    reading the entry exists to prevent — and it is the reading a future maintainer would resolve
    by rewriting history.
    """
    section = _flat(_record_section(UNSIGNED_HEADING))
    assert "forward-looking" in section, (
        f"the unsigned-history entry in {RECORD} no longer says the DCO enforcement is "
        "forward-looking. Without it the table reads as a list of defects rather than a ruling"
    )
    assert "rewrite" in section, (
        f"the unsigned-history entry in {RECORD} no longer addresses history rewriting. It is the "
        "obvious remedy and the one this project has declined; declining it silently means the "
        "next reader gets to decide"
    )


# ------------------------------------------------- 2. the absence NOTICE asserts, over every file

#: The files whose copyright notices are LICENCE notices rather than per-file headers.
#:
#: The three at the repository root are typed out: `LICENSE`, `NOTICE`, and `DCO`, which carries
#: the Linux Foundation's notice verbatim and is included for that reason.
#:
#: The rest are DERIVED from `packages/cdm/pyproject.toml`'s `license-files`, and the derivation
#: is the point. A distribution has to carry its licence text and setuptools resolves that glob
#: against the DISTRIBUTION root, so a copy of `LICENSE` and `NOTICE` sits beside the package —
#: without them the wheel shipped `License-Expression: Apache-2.0` and no licence text at all,
#: which is section 4(d) unmet. Those copies are real files with real copyright notices in them,
#: and this invariant had no vocabulary for that: a fresh clone failed the moment they were
#: committed. Derived rather than added to the literal set above, because a second distribution
#: would need the same two files again and a typed list is a list somebody has to remember.
def _licence_files() -> set[str]:
    import tomllib
    root = {"LICENSE", "NOTICE", "DCO"}
    for pyproject in sorted(REPO.glob("packages/*/pyproject.toml")):
        declared = tomllib.loads(pyproject.read_text()).get("project", {}).get("license-files", [])
        rel = pyproject.parent.relative_to(REPO)
        root |= {str(rel / name) for name in declared}
    return root


LICENCE_FILES = _licence_files()

SPDX = re.compile(r"SPDX-(License-Identifier|FileCopyrightText)")

#: Deliberately narrow. `copyright` as a bare word occurs in prose about licensing — `NOTICE`
#: discusses the Apache appendix, `CONTRIBUTING.md` discusses the licence — and a pattern that
#: matched the word alone would flag every such sentence. A NOTICE is the word followed by a year,
#: a `(c)`, or a `©`, which is what a per-file header actually looks like.
COPYRIGHT = re.compile(r"(?i)\bcopyright\b\s*(\(c\)|©|\d{4}|\[yyyy\])")


def tracked_files() -> list[str]:
    out = _git("ls-files")
    assert out.returncode == 0, f"git ls-files failed: {out.stderr}"
    return [line for line in out.stdout.splitlines() if line.strip()]


def _readable_text(rel: str) -> str | None:
    try:
        return (REPO / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def test_no_tracked_file_carries_an_spdx_tag():
    """Half of what NOTICE asserts, over the whole index rather than over a sample."""
    _require_git_history()
    tagged = [rel for rel in tracked_files()
              if rel != SELF and (text := _readable_text(rel)) and SPDX.search(text)]
    assert not tagged, (
        f"{len(tagged)} tracked file(s) carry an SPDX tag: {tagged[:5]}. NOTICE states that this "
        "repository has no per-file headers and explains that filling in Apache-2.0's appendix "
        "template would be completing the wrong form. One tagged file makes that paragraph false "
        "— either remove the tag, or adopt per-file headers everywhere and rewrite NOTICE"
    )


def test_the_only_copyright_notices_are_in_licence_files():
    """The other half, and the direction that actually catches a stray header.

    An SPDX tag is deliberate and rare. A copyright block pasted at the top of a new module is
    the ordinary way this invariant breaks, and it breaks silently: the file is correct in
    isolation and wrong only relative to a policy stated in a file nobody reads while writing
    code.

    It used to be named for the number three and it broke on a fourth and fifth file that were
    not headers at all — the licence copies a wheel has to carry. The set is derived now, so the
    invariant is about the KIND of file rather than about a count.
    """
    _require_git_history()
    carriers = [rel for rel in tracked_files()
                if rel != SELF and (text := _readable_text(rel)) and COPYRIGHT.search(text)]
    unexpected = sorted(set(carriers) - LICENCE_FILES)
    assert not unexpected, (
        f"copyright notice(s) outside the licence files: {unexpected}. The licence files are "
        f"{sorted(LICENCE_FILES)} — the three at the root plus whatever a distribution declares "
        "in `license-files` — and NOTICE states that the policy is stated at the repository "
        "level instead. A header in a source file is a second, per-file licence statement, the "
        "exact thing NOTICE says this repository does not do"
    )


def test_the_copyright_sweep_is_not_vacuous():
    """A pattern that matched nothing would agree that there are no notices anywhere.

    Asserted against each licence file positively, because they carry the notice in three
    different shapes — `Copyright 2026`, `Copyright (C) 2004, 2006`, and the bracketed `[yyyy]`
    of the Apache appendix — and a pattern could stop seeing one of them and keep passing.
    """
    _require_git_history()
    tracked = set(tracked_files())
    for rel in sorted(LICENCE_FILES):
        assert rel in tracked, f"{rel} is not tracked; this module's licence-file list is stale"
        text = _readable_text(rel)
        assert text is not None, f"{rel} is not readable as UTF-8"
        assert COPYRIGHT.search(text), (
            f"the copyright pattern no longer matches {rel}, which certainly contains a notice. "
            "The sweep above is therefore blind and would pass over a tree full of headers — "
            "re-anchor the pattern rather than trusting the green"
        )


def test_notice_states_the_absence_and_does_not_restate_a_file_count():
    """The stale count is not allowed back, and the reason is written next to the assertion.

    A total-file count in prose has a guaranteed expiry date: the next commit that adds a file
    falsifies it, and nothing in a build notices. It went stale exactly that way — 769 stated
    while the tree held 770 — and it was published in that state. The absence is the claim and
    the absence does not rot.
    """
    notice = _flat(_read("NOTICE"))
    assert "no per-file headers" in notice, (
        "NOTICE no longer states that this repository has no per-file headers, which is the claim "
        "the two sweeps above enforce. A gate whose prose has gone is a gate over nothing"
    )
    stale = re.findall(r"\b(\d{3,4}) tracked files\b", notice)
    live = [n for n in stale if "used to read" not in notice[:notice.index(n)][-120:]]
    assert not live, (
        f"NOTICE states a tracked-file count again: {live}. That number is stale on the next "
        "commit that adds a file, which is how it came to say 769 of 770. State the absence; the "
        "sweeps in this module are what make the absence checkable"
    )


# ------------------------------------- 3. the required-status claim, stated twice and made to agree

#: The two files that tell a reader whether a red `DCO` check stops a merge. Neither can check
#: GitHub; what is checkable is that they do not contradict each other.
STATUS_SITES = (RECORD, GUIDE)

#: The phrase that means "wired". Present at a site → that site claims the check gates merges.
CLAIMS_REQUIRED = "is a **required status**"

#: The phrase at each site that means "and this is a RULING, not a to-do". The pre-flip round left
#: the wiring as an open decision and both sites described it that way; the outsider round closed
#: it — `DCO` stays advisory, `main` keeps direct pushes — and closing it at one site only would
#: leave a contributor reading `CONTRIBUTING.md` waiting for a gate that is never coming, or a
#: maintainer reading `PUBLICATION.md` re-deciding something already decided. Different words
#: again, for the reason `DENIES_REQUIRED` uses different words: this is agreement about a fact.
SETTLED = {
    RECORD: "stays advisory",
    GUIDE: "settled decision and not an oversight",
}

#: The phrase at each site that means "not wired". Deliberately DIFFERENT words at the two sites,
#: and keyed by site rather than zipped so the pairing cannot silently swap: this is a check for
#: AGREEMENT ABOUT A FACT and not for a copied sentence. A copied sentence would satisfy a
#: same-string check while both copies were wrong together, and the record has to speak the
#: ruleset's language while the guide speaks the contributor's.
DENIES_REQUIRED = {
    RECORD: "no `required_status_checks` rule",
    GUIDE: "not currently a required status",
}


def test_neither_site_claims_the_dco_check_is_a_required_status():
    """The regression that shipped. Asserted as an ABSENCE, at both sites.

    `CONTRIBUTING.md` said "a failing DCO check is a **required status**, so the pull request
    **cannot be merged** until it passes". The ruleset carries no `required_status_checks` rule,
    so it was false — and it was false in the one document a first-time contributor is most
    likely to read, for the whole first day the repository was public.

    This assertion is what has to be deleted, deliberately and in the same commit, on the day the
    wiring is actually done. That is the intended cost: the claim becomes true by an action on
    GitHub that no test can see, so the only honest gate is one that makes a human confirm the
    action happened.
    """
    for site in STATUS_SITES:
        assert CLAIMS_REQUIRED not in _read(site), (
            f"{site} claims the DCO check is a required status. If the ruleset has since been "
            f"wired, update BOTH {STATUS_SITES} and remove this assertion in the same commit. If "
            "it has not, this is the sentence that was published while false and it must not "
            "come back"
        )


def test_both_sites_state_that_the_check_is_not_yet_required():
    """AN ABSENCE is not enough on its own, and this is the half that makes it a disjunction.

    A file that simply stopped mentioning the subject would satisfy the assertion above, and a
    contributor reading it would be left to assume whichever answer suits them. Each site has to
    say the thing, in its own terms — the record in the ruleset's language, the guide in the
    contributor's.
    """
    assert set(DENIES_REQUIRED) == set(STATUS_SITES), (
        f"the site list {STATUS_SITES} and the phrase map {sorted(DENIES_REQUIRED)} disagree, so "
        "one site is unchecked. Both constants move together or neither does"
    )
    for site in STATUS_SITES:
        phrase = DENIES_REQUIRED[site]
        assert phrase in _flat(_read(site)), (
            f"{site} no longer states that the DCO check is not a required status (looked for "
            f"{phrase!r}). Silence at either site is what lets the two drift: the reader supplies "
            "the missing half from the other document and gets an answer neither file gave"
        )


def test_the_record_carries_the_status_check_name_the_wiring_needs():
    """The one value the pending manual action cannot be performed without.

    "Require status checks to pass" takes the check's name as GitHub reports it, and the name is
    not derivable from the app's name, its slug, or the repository. It was read off the check run
    and it is written down; a record of a pending action that omits the value the action needs is
    a note to look it up again.
    """
    record = _flat(_read(RECORD))
    assert "Status-check name, as GitHub reports it: `DCO`" in record, (
        f"{RECORD} no longer states the status-check name verbatim. It is the value the ruleset's "
        '"Require status checks to pass" needs, it was obtained by running the check once, and '
        "re-obtaining it means re-running the probe"
    )
    # Anchored to two phrases that occur ONCE each, and a mutation is why. The first version of
    # this assertion looked for the bare substring "commit status", which the sentence two lines
    # further on satisfies all by itself once whitespace is flattened ("commit\nstatuses" becomes
    # "commit statuses") — so deleting the distinction left the check green.
    for phrase in ("not a legacy commit status", "combined-status endpoint"):
        assert phrase in record, (
            f"{RECORD} no longer distinguishes the Checks API from legacy commit statuses "
            f"(looked for {phrase!r}). The combined-status endpoint reports nothing at all for "
            "these commits, so anything wired against commit statuses sees no check — a wiring "
            "failure that looks like a passing repository"
        )


def test_the_record_warns_that_requiring_the_check_without_requiring_pull_requests_deadlocks_main():
    """The consequence, kept next to the instruction, because the instruction is dangerous.

    The DCO app produces check runs on pull-request events. A required status check in a branch
    ruleset gates pushes to the branch. This repository pushes directly to `main` — the
    `pull_request` rule was removed for exactly that reason — so requiring `DCO` without
    restoring it would refuse every direct push for want of a check that never runs.

    A record that said only "add `DCO` under Require status checks to pass" would be an
    instruction to break the repository, written by the round that had just finished proving the
    protections work.
    """
    record = _flat(_read(RECORD))
    for phrase in ("deadlock", "pull-request", "direct push"):
        assert phrase in record.lower(), (
            f"{RECORD} no longer warns about {phrase!r} in the status-check wiring entry. The "
            "warning is the reason the entry is a decision rather than a chore"
        )


# --------------------------------------------------------------- the closure, and the one taboo

def test_the_record_does_not_restate_the_deploy_mechanism():
    """`tests/test_cdm_deploy_workflow.py` owns that fact at two sites; a third is a liability.

    That module sweeps the tree for the strings that occur only where the deploy is described and
    fails if a file carries one without being on its site list. So this is not a style rule: a
    `PUBLICATION.md` that quoted either marker would turn the deploy gate red, and the fix would
    be either to add this file to a list of documents that must all agree about wrangler, or to
    do what it does instead — state the measurement, and point at the mechanism.

    This docstring does not name the markers either, for the same reason the assertion imports
    them: a checker that spells the forbidden string is itself a carrier of it.
    """
    # The markers are IMPORTED rather than restated. Spelling them here is what broke first:
    # this module quoted both strings in order to forbid them, the deploy gate's own sweep found
    # them, and the checker became a site. Importing means there is exactly one copy of each
    # marker in the repository — which is the property the deploy gate is about — and it means a
    # marker changing there cannot leave this assertion checking a string nobody uses.
    from tests.test_cdm_deploy_workflow import MARKERS, _files_stating_the_mechanism

    swept = _files_stating_the_mechanism()
    assert RECORD not in swept, (
        f"{RECORD} now reads as a site that states the deploy mechanism (it carries one of "
        f"{MARKERS}), so tests/test_cdm_deploy_workflow.py's closure will fail. Either rephrase — "
        "the record needs only the MEASUREMENT, and the mechanism is docs/README.md's to state — "
        f"or add {RECORD} to that module's SITES and accept that it must then agree about the "
        "whole mechanism forever"
    )
    assert swept, (
        "the deploy gate's marker sweep found no files at all, so the assertion above passes "
        "vacuously. That module has its own non-vacuity check; if it is failing, fix it there"
    )
    # Scoped to the deployment section, not to the whole file. The record mentions
    # `docs/README.md` twice — once in the preamble about where mechanism-level facts live — and
    # a whole-file check was satisfied by that one while the section itself had stopped pointing
    # anywhere. The reader who needs the pointer is the one reading this section.
    deployment = _record_section("## The deployment was not affected")
    assert "docs/README.md" in deployment, (
        f"the deployment section of {RECORD} no longer points at the file that does state the "
        "mechanism. Declining to restate it is only correct if the reader is told where it is; "
        "without the pointer this section is a measurement of something it will not name"
    )


def test_the_record_names_the_gate_behind_the_no_bytes_ship_claim():
    """A claim with a gate behind it should say which gate, so the next reader can check it.

    `PUBLICATION.md` asserts that no pinned document is in the tree or the history. That is
    enforced — `tests/test_cdm_pins.py` requires every pin untracked and requires `.gitignore` to
    refuse the staging — and this module does not re-check it. What it checks is that the claim
    is not floating: an unattributed assertion in a licence-adjacent document is one a future
    reader has to take on trust or re-derive.
    """
    record = _read(RECORD)
    assert "tests/test_cdm_pins.py" in record, (
        f"{RECORD} states that no pinned document ships and no longer names the gate that "
        "enforces it. The claim is load-bearing for the licence boundary in NOTICE; a reader must "
        "be able to get from the claim to the check without searching"
    )
    assert (REPO / "tests/test_cdm_pins.py").exists(), (
        "PUBLICATION.md cites tests/test_cdm_pins.py and that file is gone. The citation is now "
        "a pointer to nothing, which is worse than no citation"
    )


def test_the_five_pending_distribution_statements_are_five_and_are_named():
    """The deferral is only actionable if it says WHICH documents, and it must not lose one.

    "Five distribution statements pending a human read" was a commit-message sentence for one
    round. A human doing the read needs the list, and a count without the list decays into "some
    of the NATO documents" within a round or two.
    """
    section = _flat(_record_section("### 3. Five distribution statements, pending a human read"))
    expected = ("AEDP-4607", "AEDP-4607.1", "MISP-2019.1", "AEDP-12", "AEDP-12.1")
    missing = [name for name in expected if name not in section]
    assert not missing, (
        f"the pending-front-matter entry in {RECORD} no longer names {missing}. Five documents "
        "were found to have no extractable distribution statement; an entry that names four is a "
        "read that will come back declaring itself complete"
    )
    coverage = _read("packages/cdm/synapse_cdm/FORMAT_COVERAGE.md")
    unknown = [name for name in expected if name not in coverage]
    assert not unknown, (
        f"{RECORD} names {unknown} as pinned sources and FORMAT_COVERAGE.md does not mention "
        "them. Either the record has invented a document or the coverage table has lost one, and "
        "both are worse than a missing front matter"
    )
    assert "image-only" in section, (
        f"the entry in {RECORD} no longer says WHY the statements are unread. 'Pending a human "
        "read' without 'the text layer is not there' reads as a task nobody got round to, and "
        "the next round will try to automate it again"
    )


def test_the_record_states_what_it_cannot_check():
    """The distinction between gated, witnessed and merely recorded is the record's own honesty.

    Every protection in this file was verified by a refusal, except one: the `deletion` rule
    cannot be witnessed on the default branch, because GitHub's older default-branch guard
    refuses first and never cites the ruleset. Collapsing that into "protections verified" is the
    kind of rounding-up this repository treats as a defect, so the tiers are written out and
    the unwitnessed rule is named.

    THE ROSTER WAS THREE AND IS FOUR, and the reason is the finding that split it. `Gated` carried
    two disjoint senses: a claim a suite test reads, which cannot go stale without a red build, and
    a claim whose truth lives at Cloudflare, which goes stale silently until somebody runs
    `gates/deploy_record.py`. This roster asserted only the collapsed word, so it was green through
    the whole period the table applied one label to both — which is the shape of the defect, not an
    accident of it. A tier vocabulary is exactly the kind of index sweep rule 10 puts in scope, and
    a gate that pins it is the reason the rename could not be half-done: the second assertion below
    refuses the retired label as a row label, so the split cannot be silently reverted in the table
    while this roster still names the two senses.
    """
    record = _flat(_read(RECORD))
    assert "unwitnessed by behaviour" in record, (
        f"{RECORD} no longer flags that the deletion rule was never observed refusing anything. "
        "It is recorded from the API only, and the probe that would witness it needs a "
        "non-default branch inside a ruleset whose scope is the default branch alone"
    )
    # By the table ROW rather than by the bare token, and the difference is not pedantic: every
    # one of these four names also occurs in the prose underneath the table, so a membership test
    # over the whole file is satisfied by the paragraph that DISCUSSES a tier and cannot see the
    # tier itself being renamed or dropped. Found by mutating this assertion — renaming the
    # `Protocol-gated` row left it green — which is the same lesson as the finding it was written
    # for: a check on an index has to read the index and not the commentary beside it.
    for tier in ("Suite-gated", "Protocol-gated", "Witnessed", "Recorded from the API"):
        assert f"| **{tier}** |" in _read(RECORD), (
            f"{RECORD} no longer separates its claims into tiers (missing a {tier!r} row in the "
            "kinds table). A witness statement and a gated invariant read identically on the page "
            "and decay completely differently, which is why the table exists; and a suite-gated "
            "claim reads identically to a protocol-gated one, which is why there are two gated "
            "tiers and not one"
        )
    assert "**GATED**" not in _read(RECORD), (
        f"{RECORD} carries the retired collapsed label as a row label again. It was split into "
        "`Suite-gated` and `Protocol-gated` because four rows whose truth lives at Cloudflare were "
        "labelled as though a red build would catch them going stale, and two of those four had "
        "already gone stale silently. Label the row with whichever of the two senses actually "
        "refuses it rather than restoring the word that covered both"
    )


# --------------------------------------------- 4. the repository's own URL, read and not retyped

#: Any reference to this repository on GitHub, whatever owner segment it carries. The owner is
#: captured rather than matched, because the defect is a WRONG owner and a pattern that spelled
#: the right one would only ever find the occurrences that are already correct.
REPO_URL = re.compile(r"github\.com/(?P<owner>[A-Za-z0-9._-]+)/synapsecommand-public")


def canonical_owner() -> str:
    """The owner segment, READ from the record's own statement of where this repository is.

    The same discipline `tests/test_cdm_version_floor.py` applies to the Python floor: the value
    is read from the one place that declares it, so a move re-points every check at once instead
    of leaving a constant somebody has to remember to retype. `PUBLICATION.md`'s first sentence
    is that declaration.
    """
    first = _flat(_read(RECORD))[:400]
    found = REPO_URL.search(first)
    assert found, (
        f"{RECORD} no longer opens by stating where this repository is, so there is nothing to "
        "read the canonical owner from. That sentence is the declaration this gate is built on; "
        "restore it rather than typing the owner into this module"
    )
    return found.group("owner")


def test_every_reference_to_this_repository_uses_the_canonical_owner():
    """The organisation renamed and GitHub kept redirecting, which is why nothing failed.

    `origin` and `packages/cdm/pyproject.toml` both carried `decentcybersecurity/…`. Every fetch
    and every push worked and printed `This repository moved to …` — a warning that is invisible
    in the docs site's rendered links, invisible in PyPI metadata, and invisible to anyone who
    only ever reads the page the redirect lands on. A redirect is a courtesy that can be
    withdrawn: the day the old organisation name is claimed by someone else, `Homepage` in this
    package's metadata points at a stranger's repository.

    Case matters and is asserted as such. GitHub resolves owners case-insensitively, so
    `decent-cybersecurity` would work today and would still not be the name the organisation has.
    """
    _require_git_history()
    canonical = canonical_owner()
    wrong: list[str] = []
    for rel in tracked_files():
        if rel == SELF:
            continue
        text = _readable_text(rel)
        if not text:
            continue
        for found in REPO_URL.finditer(text):
            if found.group("owner") != canonical:
                wrong.append(f"{rel}: {found.group(0)}")
    assert not wrong, (
        f"{len(wrong)} reference(s) to this repository use an owner other than {canonical!r}:\n  "
        + "\n  ".join(sorted(wrong)[:8])
        + f"\nGitHub redirects them, so nothing breaks and nothing warns except `git push`. The "
        f"canonical path is read from {RECORD}; fix the reference rather than this gate"
    )


def test_the_canonical_owner_sweep_is_not_vacuous():
    """A regex that matched nothing would report a clean tree with every URL wrong.

    Two independent halves, because either alone can pass while the check is dead: the pattern
    must find this repository's URL in more than one file, and it must be able to see a wrong
    owner when there is one — asserted against a synthetic string, since the tree is expected to
    hold none.
    """
    _require_git_history()
    carriers = sorted({rel for rel in tracked_files()
                       if rel != SELF and (text := _readable_text(rel)) and REPO_URL.search(text)})
    assert len(carriers) >= 3, (
        f"the repository-URL pattern matched in only {carriers}. It is stated in the record, in "
        "the package metadata and in the docs site's configuration, so a count this low means "
        "the pattern has stopped matching and the sweep above is passing over nothing"
    )
    mutant = REPO_URL.search("see https://github.com/decentcybersecurity/synapsecommand-public")
    assert mutant and mutant.group("owner") == "decentcybersecurity", (
        "the pattern cannot capture a wrong owner, so the sweep would report every reference "
        "canonical whatever it said"
    )
    assert canonical_owner() == "Decent-Cybersecurity", (
        f"the canonical owner read from {RECORD} is {canonical_owner()!r}. Renaming the "
        "organisation is allowed and must be deliberate: update this assertion in the same "
        "commit that updates the record, so a rename cannot happen by a typo in one file"
    )


def test_both_sites_state_that_the_advisory_check_is_a_RULING_and_not_a_pending_decision():
    """The half the outsider round added, and it is the same shape as the one above it.

    Being honest about the state was enough while the state was "nobody has decided". Once a round
    decides, honesty needs the second sentence: a reader who is told only that the check does not
    gate cannot tell a deliberate design from a job somebody has not got round to — and the two
    lead to opposite actions. One says leave it; the other says wire it, which would deadlock
    `main` for the reason the warning below spells out.

    Both sites, because the audiences differ and each will act on its own document: the maintainer
    reading the record must not re-open a closed question, and the contributor reading the guide
    must not read the absence of a gate as slack.
    """
    assert set(SETTLED) == set(STATUS_SITES), (
        f"the site list {STATUS_SITES} and the ruling map {sorted(SETTLED)} disagree, so one site "
        "is unchecked. Both constants move together or neither does"
    )
    for site in STATUS_SITES:
        phrase = SETTLED[site]
        assert phrase in _flat(_read(site)), (
            f"{site} no longer says the advisory `DCO` check is a settled ruling (looked for "
            f"{phrase!r}). It states the STATE and not the DECISION, which is what both files said "
            "before the ruling — and a state without a decision beside it reads as an unfinished "
            "chore to the next person who finds it"
        )


def test_the_ruling_carries_its_grounds_and_the_measurement_behind_the_first_one():
    """A ruling without grounds is an assertion, and the next round would relitigate it.

    Three grounds were given and each is checkable in the record's own words. The first is the one
    that matters most and it is the one that could most easily decay into a plausible-sounding
    inference: it rests on `total_count: 0` for a real commit, measured, and not on a reading of
    how the DCO app probably behaves.
    """
    section = _flat(_record_section("### 1. `DCO` stays advisory"))
    assert "total_count: 0" in section and "f916ba2" in section, (
        f"the ruling in {RECORD} no longer names the commit and the measured zero its first "
        "ground rests on. Without them the ground is 'the app probably only runs on pull "
        "requests', which is exactly the kind of confident inference this file separates from "
        "what was observed"
    )
    assert "trailers:key=Signed-off-by" in section, (
        f"the ruling in {RECORD} no longer names how the local gate reads a sign-off. The second "
        "ground is that the pre-push gate and the platform check agree about what a trailer IS, "
        "and that claim is only as good as the mechanism it names"
    )
    assert "still inferred" in section.lower() or "stated as inferred" in section.lower(), (
        f"the ruling in {RECORD} no longer separates what was measured from what is inferred. "
        "Half of the deadlock warning is observed and half is not, and a ruling that presented "
        "both as observed would be over-claiming in the file that invented the three-tier table"
    )
    for ground in ("Ground 1", "Ground 2", "Ground 3"):
        assert ground in section, (
            f"the ruling in {RECORD} no longer states {ground}. A decision recorded without its "
            "reasons is one the next round has to make again from scratch"
        )
    assert "Reopening this is allowed" in section, (
        f"the ruling in {RECORD} no longer says how to reopen it. A closed decision with no "
        "stated way back is indistinguishable from a rule nobody may question, and the sequence "
        "matters here — restore `pull_request` FIRST, or requiring the check deadlocks `main`"
    )


# ------------------------------------------------------- the ledger is a set that does not move
#
# `PUBLICATION.md` says so in its own words — "the set does not move, entries change STATE, they
# are not deleted" — and until now nothing checked it. The count was written out in prose in two
# places (the file and this module's docstring) and a fifth entry landing meant a person had to
# remember both. That is a stale-count generator of exactly the kind `tests/test_cdm_prose_counts.py`
# exists for, one document along, so it gets the same treatment: derive the number, compare it to
# every place that states it.


def ledger_entries() -> list[tuple[int, str]]:
    """The `### N. …` headings under `## Open ledger`, in file order."""
    text = _read(RECORD)
    start = text.index("## Open ledger")
    rest = text[start + len("## Open ledger"):]
    end = re.search(r"\n## ", rest)
    section = rest[:end.start()] if end else rest
    return [(int(m.group(1)), m.group(2).strip())
            for m in re.finditer(r"\n### (\d+)\. (.+)", section)]


def test_the_ledger_is_numbered_consecutively_from_one():
    """Numbering is the ledger's only identity: entries are cited by number elsewhere.

    A gap would mean an entry was deleted, which the file forbids in its own terms, and a repeat
    would mean two entries answer to one citation.
    """
    numbers = [n for n, _ in ledger_entries()]
    assert numbers, f"{RECORD} has an Open ledger section with no numbered entries in it"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"the ledger is numbered {numbers}. It must run 1..N with no gap and no repeat — an entry "
        "is cited by its number, and the file's own rule is that entries change state rather than "
        "being deleted"
    )


def test_every_place_that_states_the_ledger_count_states_the_derived_one():
    """Two sites carry the count in prose. Both are checked against the headings.

    This module is one of them, and it is checked too — a docstring that says "four ledger
    entries" beside a file holding five is a small wrongness in the one document whose whole job
    is being right about the repository's state.
    """
    count = len(ledger_entries())
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven",
             8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve", 13: "Thirteen",
             14: "Fourteen", 15: "Fifteen", 16: "Sixteen"}
    assert count in words, f"{count} ledger entries; extend the number words in this test"
    record = _flat(_read(RECORD))
    assert f"{words[count]} entries, and the set does not move" in record, (
        f"the ledger holds {count} entries and {RECORD} does not say so in the sentence under "
        f"`## Open ledger` (looked for {words[count]!r}). The count is stated in prose there and "
        "is the kind of number that goes stale the moment an entry is added"
    )
    mine = _flat((REPO / SELF).read_text().split('"""')[1])
    assert f"{words[count].lower()} ledger entries" in mine, (
        f"this module's own docstring does not say there are {words[count].lower()} ledger "
        "entries. It is a site like any other and it went stale first"
    )
