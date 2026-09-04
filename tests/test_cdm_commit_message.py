"""`gates/commit_message.py` held to its contract, in both directions, on the incident itself.

WHAT HAPPENED, BECAUSE THE TEST IS ONLY WORTH ITS LINES IF THE INCIDENT IS ON THE RECORD
----------------------------------------------------------------------------------------
`c4a1071f`'s message ends with two lines that git parses as `Signed-off-by` trailers:

    Signed-off-by: nothing else changed; the suite is unmoved at 3151 passed, 2 skipped.
    Signed-off-by: Matej Michalko <m@decentcybersecurity.eu>

The first is a sentence that acquired a trailer key — the author reached for the `Suite:` line the
previous commit had used and typed a sign-off instead. **Nothing in this repository noticed.**
`tests/test_cdm_publication.py` reads sign-offs through `%(trailers:key=Signed-off-by,valueonly)`,
finds a non-empty value and calls the commit signed. It is signed, by the second line. The DCO app
would agree, for the same reason. Every check that asks "is there a sign-off?" is satisfied by a
malformed trailer block, and that is what makes this a class rather than a typo.

**The historical fact is checked here rather than described**, out of git, so this module cannot
drift into folklore: `test_the_incident_is_reproducible_from_git` reads the message at `c4a1071f`
and asserts git still parses two sign-off trailers there, one of which is not an identity.

WHAT IS ASSERTED, AND WHY EACH DIRECTION IS HERE
------------------------------------------------
A guard that only checked the refusal would pass on a module that refused everything. So both
directions, for both halves of the class:

* **prose inside the block** — a certifying key carrying something that is not an identity is
  refused, and a well-formed block passes;
* **a trailer outside the block** — a `Signed-off-by:` line stranded mid-body is refused, and the
  prose this repository actually writes (`Ground 1: …`, `USAGE: …`, a colon in a sentence) is not.

The second direction is the one that matters more here. This repository's messages are long prose
with colons everywhere, and a check that flagged them would be turned off within a round.

THE HISTORY SWEEP, AND WHY IT NAMES A SET RATHER THAN COUNTING
---------------------------------------------------------------
`test_the_malformed_set_in_the_record_is_the_malformed_set_in_the_history` recomputes the offending
commits from the actual history and requires them to equal the set `PUBLICATION.md` names. That is
`tests/test_cdm_publication.py`'s unsigned-commit treatment applied to a second defect in the same
family, and for the same reason: a ratio goes stale on the next commit and a set does not. A second
malformed message fails the build; so does dropping the one that is there while it is still
malformed.
"""
import pathlib
import re
import subprocess
import sys

import pytest

from gates.commit_message import (
    CERTIFYING_KEYS,
    IDENTITY,
    KNOWN_KEYS,
    check,
    defects,
    message_of,
    observations,
    revisions,
    sign_offs,
    trailer_block,
    trailers_git_parses,
)

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Shared with `tests/test_cdm_publication.py`, which owns the reasoning. Two modules read
#: two ledger entries under the same convention and one function is what keeps them agreeing.
from tests.test_cdm_publication import _before_the_dated_notes  # noqa: E402

RECORD = "PUBLICATION.md"

#: The heading the table of malformed trailer blocks lives under. Anchored to the heading rather
#: than to the whole file, the way the unsigned-commit ledger is.
MALFORMED_HEADING = "### 7. A malformed trailer block: one commit, recorded and left in place"

#: The commit whose message still carries the defect. Kept as a constant so the assertions below
#: read as statements about it rather than as a literal repeated five times.
INCIDENT = "c4a1071f"

SIGNOFF = "Signed-off-by: Ada Lovelace <ada@example.org>"

CLEAN = f"""Subject line that says what the round did

A paragraph of body prose. Ground 1: it contains colons, because every message in this
repository does, and USAGE: none of them is a trailer.

Suite: 3151 passed, 2 skipped.
{SIGNOFF}
"""


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(args)} failed: {done.stderr}"
    return done.stdout


# --------------------------------------------------------------- the two directions, on messages


def test_a_clean_message_passes():
    """The direction a module that refused everything would fail.

    Deliberately the hardest clean message this repository could produce: colons in the prose, a
    non-certifying trailer, and a sign-off. All three have to survive.
    """
    assert defects(CLEAN) == [], f"a clean message was refused: {defects(CLEAN)}"
    check(CLEAN)                                    # must not raise


def test_a_mid_body_sign_off_is_refused():
    """THE MUTATION, and it is the half git cannot see.

    A `Signed-off-by:` line in the body is body text to git — so the commit reads as signed to a
    human and is unsigned to the DCO app and to the unsigned-commit ledger. Nothing in this
    repository could have caught it before this module.
    """
    mutant = CLEAN.replace(
        "A paragraph of body prose.",
        f"A paragraph of body prose.\n{SIGNOFF}\nAnd the paragraph continues.",
    )
    found = defects(mutant)
    assert found, "a message carrying a mid-body Signed-off-by: line was accepted"
    assert any("reads as a sign-off and is not one" in reason for reason in found), (
        f"the mid-body sign-off was refused for the wrong reason: {found}"
    )
    with pytest.raises(ValueError):
        check(mutant)


def test_prose_under_a_certifying_key_is_refused():
    """The incident's own shape, as a synthetic message: the key is right, the value is prose."""
    mutant = CLEAN.replace(
        SIGNOFF,
        "Signed-off-by: nothing else changed; the suite is unmoved.\n" + SIGNOFF,
    )
    found = defects(mutant)
    assert found, "prose under a Signed-off-by: key was accepted"
    assert any("takes a name and an address" in reason for reason in found), (
        f"refused for the wrong reason: {found}"
    )


def test_an_unknown_trailer_key_is_refused_rather_than_ignored():
    """Widening the vocabulary is a deliberate act; a typo must not do it silently."""
    mutant = CLEAN.replace("Suite: 3151", "Suit: 3151")
    found = defects(mutant)
    assert found, "an unknown trailer key was accepted"
    assert any("unknown key" in reason for reason in found), f"wrong reason: {found}"


def test_a_message_with_no_sign_off_at_all_is_REFUSED_and_this_test_used_to_assert_the_opposite():
    """**INVERTED 2026-09-04, AND THE OLD ARGUMENT DESERVES AN ANSWER RATHER THAN A DELETION.**

    This test used to assert `defects(unsigned) == []`, on a real argument: *the unsigned-commit
    ledger owns sign-off PRESENCE, and two checks on one fact is how they disagree.* It named
    `tests/test_cdm_publication.py` as the owner and warned that duplicating it would let the two
    drift.

    **`41d3d2d` IS WHAT THAT DIVISION OF LABOUR COST.** An unsigned commit reached `origin/main`
    on 2026-09-04 and had to be removed by a force-push under a temporary ruleset bypass —
    PUBLICATION.md entry 2 carries the record. The ledger did its job: it recomputes the unsigned
    set from the actual history and requires it to equal entry 2's three commits, so the fourth
    failed the build exactly as designed. **It just did it AFTERWARDS.**

    So the old argument was wrong in its premise, not its logic. These are not two checks on one
    fact; they are two checks at two MOMENTS. The ledger asks *is the history what the record
    says* and answers it at suite time, over commits that already exist. This module asks *is
    this message signed* and answers it about a message, before `git push` — which is where
    `41d3d2d` needed an answer and got none. Neither can substitute for the other, and the drift
    the old docstring feared is guarded against directly by
    `test_the_defect_set_over_the_history_is_exactly_the_recorded_one` below, which requires this
    module's verdict over the whole history to equal PUBLICATION.md's two entries.
    """
    unsigned = "Subject\n\nBody with no trailer block at all.\n"
    found = defects(unsigned)
    assert len(found) == 1 and "no `Signed-off-by:` trailer" in found[0], (
        f"an unsigned message produced {found}. Since 2026-09-04 this module requires a sign-off: "
        "the check that would have caught 41d3d2d before it reached origin/main is a check on the "
        "MESSAGE, and the ledger's check on the history necessarily runs later"
    )
    # A subject line alone has no trailer block at all, and that is still unsigned rather than
    # exempt — git will not parse a subject as a trailer and neither does this.
    assert defects("Subject only, no body\n"), "a subject-only message read as signed"


def test_a_sign_off_stranded_in_the_body_is_refused_TWICE_and_both_complaints_are_right():
    """The interaction the two clauses have with each other, asserted because it looks like a bug.

    A message whose only sign-off sits mid-body earns both complaints: the stranded-trailer
    complaint, because a line reads as a sign-off and is not one to git, AND the missing-sign-off
    complaint, because the trailer block genuinely has none. **That is not double-counting.** It
    is the two true things about such a message, and a reader needs both: the first says what to
    move and the second says what the commit currently is.
    """
    stranded = f"Subject\n\n{SIGNOFF}\n\nBody prose, so the sign-off is not in the last paragraph.\n"
    found = defects(stranded)
    assert len(found) == 2, f"expected both complaints, got {found}"
    assert any("reads as a sign-off and is not one" in f for f in found)
    assert any("no `Signed-off-by:` trailer" in f for f in found)


def test_two_identities_for_one_person_are_ACCEPTED_and_REPORTED():
    """RULING 3's third clause, and the history is what forced it.

    The round that specified this rule asked for *exactly one* sign-off and made two a defect.
    Three commits here carry two well-formed sign-offs, one person at two addresses, so "exactly
    one" would have failed real history to satisfy a sentence in a brief.
    """
    two = (f"Subject\n\nBody.\n\nSigned-off-by: Ada Lovelace <ada@example.org>\n"
           f"Signed-off-by: Ada Lovelace <ada@other.example.org>\n")
    assert defects(two) == [], (
        f"two well-formed sign-offs were refused: {defects(two)}. A duplicate sign-off certifies "
        "the same person twice — redundant and true — and three commits in this history carry one"
    )
    noted = observations(two)
    assert len(noted) == 1 and "NOT A DEFECT" in noted[0], noted
    assert "one person at two addresses" in noted[0], noted


def test_two_identities_for_two_people_are_ACCEPTED_and_the_observation_says_which():
    """The case the observation exists to make visible, as opposed to the benign duplicate.

    Two different people's sign-offs on one commit is legitimate — a pair programming session, a
    patch carried forward — and is also what an accidental rebase looks like. This channel cannot
    tell those apart and does not try; it says which shape it found and leaves the judgement to a
    reader, which is the difference between an observation and a gate.
    """
    two = ("Subject\n\nBody.\n\nSigned-off-by: Ada Lovelace <ada@example.org>\n"
           "Signed-off-by: Grace Hopper <grace@example.org>\n")
    assert defects(two) == []
    noted = observations(two)
    assert len(noted) == 1 and "more than one person" in noted[0], noted


def test_one_sign_off_produces_no_observation_which_is_what_makes_the_others_mean_anything():
    """The negative control on the second channel."""
    assert observations(CLEAN) == [], observations(CLEAN)
    assert sign_offs(CLEAN) == ["Ada Lovelace <ada@example.org>"]


def test_a_prose_value_beside_a_real_identity_is_still_a_DEFECT_and_not_an_observation():
    """`c4a1071f` EXACTLY, and the assertion that keeps clause 3 from swallowing clause 2.

    This is the shape that makes the two channels worth separating. `c4a1071f` carries two lines
    git parses as `Signed-off-by`, one of them a sentence. Its defect was never the COUNT — if it
    had been, clause 3 would now excuse it — but that a value under a person-certifying key was
    prose. So it must still fail, and it must NOT be reported as a benign duplicate.
    """
    incident = ("Subject\n\nBody.\n\n"
                "Signed-off-by: nothing else changed; the suite is unmoved at 3151 passed.\n"
                f"{SIGNOFF}\n")
    found = defects(incident)
    assert len(found) == 1 and "takes a name and an address" in found[0], found
    assert observations(incident) == [], (
        f"the incident was reported as a benign duplicate: {observations(incident)}. Only "
        "WELL-FORMED identities count toward the observation, or clause 3 would launder clause 2's "
        "defect into a note"
    )


def test_the_defect_set_over_the_history_is_exactly_the_recorded_one():
    """**THE CALIBRATION, AND IT IS THE ASSERTION THAT MAKES THE RULE TRUE RATHER THAN PLAUSIBLE.**

    A sign-off rule can be wrong in a way no synthetic message reveals: too strict, and it
    condemns history the record has already accepted. The round that wrote RULING 3 carried this
    as a STOP — *if the rule names any commit outside the four defects and three observations, the
    rule is wrong and the history is not* — and it fired once already, on "exactly one".

    So both channels are recomputed over every commit and required to equal the record:

    * DEFECTS — the three commits PUBLICATION.md entry 2 accepts as unsigned, plus `c4a1071f`
      from entry 7. Four, and no more.
    * OBSERVATIONS — the three commits carrying two well-formed sign-offs. Three, and no more.
    * The two sets are DISJOINT, which is not implied by either count.
    """
    expected_defects = {"d7986017", "2a51871f", "965e939d", "c4a1071f"}
    expected_observations = {"9fcfbadf", "431b0c55", "7c27ac1d"}
    got_defects, got_observations = set(), set()
    revs = revisions("HEAD")
    for rev in revs:
        message = message_of(rev)
        short = rev[:8]
        if defects(message):
            got_defects.add(short)
        if observations(message):
            got_observations.add(short)
    assert len(revs) >= 190, f"only {len(revs)} commits reached this check"
    assert got_defects == expected_defects, (
        f"the sign-off rule names {sorted(got_defects)} as defective and the record accounts for "
        f"{sorted(expected_defects)}. A commit in one set and not the other means the RULE is "
        "wrong, not the history — that is the round's own stop rule. Extra: "
        f"{sorted(got_defects - expected_defects)}; missing: "
        f"{sorted(expected_defects - got_defects)}"
    )
    assert got_observations == expected_observations, (
        f"the observation channel names {sorted(got_observations)} and the three commits carrying "
        f"two well-formed sign-offs are {sorted(expected_observations)}"
    )
    assert not (got_defects & got_observations), (
        f"{sorted(got_defects & got_observations)} is both a defect and an observation. The two "
        "channels answer different questions and a commit in both means one of them is confused"
    )


def test_the_module_ships_no_hook_and_says_why():
    """RULING 3's second half, asserted because it is a decision and not an omission.

    The 2026-09-04 incident is the obvious argument FOR a `commit-msg` hook, and the ruling
    declines one on two grounds the docstring has to keep making: a hook lives in one clone, and
    the layer that actually failed was the PUSH rather than the commit. A round that quietly added
    a hook later would be reversing a ruling by forgetting it, so the position is checked.
    """
    import gates.commit_message as module
    doc = module.__doc__
    assert "a rule that applies to one person" in doc, (
        "the no-hook argument has left the docstring"
    )
    assert "41d3d2d" in doc, "the incident that tested the no-hook position is not named"
    assert not (REPO / ".githooks").exists() and not (REPO / "hooks").exists(), (
        "a tracked hooks directory has appeared. RULING 3 declines a hook; if that has been "
        "reversed, reverse it in the docstring too"
    )
    contributing = (REPO / "CONTRIBUTING.md").read_text()
    assert "core.hooksPath" not in contributing, (
        "CONTRIBUTING.md now documents a hook install. RULING 3 says it gets none: enforcement is "
        "this gate plus `python3 gates/commit_message.py --rev HEAD` clean before push"
    )
    assert "gates/commit_message.py --rev HEAD" in contributing, (
        "CONTRIBUTING.md does not name the pre-push check that stands in for a hook"
    )


def test_the_prose_this_repository_writes_is_not_flagged():
    """The false-positive direction, on real text rather than on an invented example.

    A check that reddened on ordinary prose would be disabled within a round, so the sample is
    every message in the history that this module already accepts — and the accepted count has to
    be nearly all of them.
    """
    revs = _git("rev-list", "HEAD").split()
    refused = [rev[:8] for rev in revs if defects(message_of(rev))]
    assert len(refused) < len(revs) * 0.1, (
        f"{len(refused)} of {len(revs)} messages in the history are refused. A rule that rejects "
        f"a tenth of the record is describing the record rather than checking it: {refused[:10]}"
    )


# ------------------------------------------------------------------- the parser, and its anchors


def test_the_trailer_block_is_the_last_paragraph_and_nothing_else():
    """Git's rule is positional, and this module mirrors it rather than inventing one."""
    body, block = trailer_block(CLEAN)
    assert block == ["Suite: 3151 passed, 2 skipped.", SIGNOFF], block
    assert SIGNOFF not in body
    single = "Subject only, no blank line"
    assert trailer_block(single) == ([single], []), (
        "a message with no blank line has no trailer block — git will not parse a subject as a "
        "trailer either"
    )


def test_the_trailer_reader_is_gits_own_and_not_a_regex_of_ours():
    """The same argument the unsigned-commit ledger makes for `%(trailers:…)`.

    A checker that disagreed with git about which lines are trailers would be checking something
    nobody else applies — not the DCO app, not the ledger, not `git log`.
    """
    assert trailers_git_parses(CLEAN) == ["Suite: 3151 passed, 2 skipped.", SIGNOFF]
    stranded = "Subject\n\nSigned-off-by: Ada <a@b.c>\n\nOrdinary last paragraph.\n"
    assert trailers_git_parses(stranded) == [], (
        "git parsed a trailer outside the last paragraph, so the positional assumption this "
        "module rests on no longer holds and the mid-body check is checking nothing"
    )


def test_the_identity_pattern_is_not_vacuous():
    """A pattern that matched everything would accept the incident it was written for."""
    assert IDENTITY.match("Ada Lovelace <ada@example.org>")
    assert not IDENTITY.match("nothing else changed; the suite is unmoved.")
    assert not IDENTITY.match("Ada Lovelace")
    assert not IDENTITY.match("<ada@example.org>"), "a bare address certifies nobody"


def test_every_certifying_key_is_in_the_vocabulary_and_takes_an_identity():
    """The closure between the two constants: a key can be hunted mid-body only if it is known."""
    for key in CERTIFYING_KEYS:
        shape, _ = KNOWN_KEYS[key.lower()]
        assert shape is IDENTITY, f"{key} is hunted mid-body but does not take an identity"


# ------------------------------------------------------------------ the incident, read out of git


def test_the_incident_is_reproducible_from_git():
    """The historical claim, checked rather than described.

    If the message is ever amended this fails, and that is correct: the record says the commit is
    left in place, so a rewrite is a decision that has to be made in the open.
    """
    message = message_of(INCIDENT)
    parsed = trailers_git_parses(message)
    signoffs = [line for line in parsed if line.lower().startswith("signed-off-by:")]
    assert len(signoffs) == 2, (
        f"{INCIDENT} no longer carries two Signed-off-by trailers ({parsed}). Either the history "
        "was rewritten — which the record says it was not — or this anchor is stale"
    )
    assert any(not IDENTITY.match(line.split(":", 1)[1].strip()) for line in signoffs), (
        f"{INCIDENT}'s trailer block no longer carries a sign-off that is not an identity, so the "
        "incident this module exists for is gone from the history"
    )
    assert any(IDENTITY.match(line.split(":", 1)[1].strip()) for line in signoffs), (
        f"{INCIDENT} no longer carries a REAL sign-off beside the bogus one. That half is why the "
        "commit is not in the unsigned set and why nothing caught this"
    )


def test_the_incident_commit_still_reads_as_signed_to_the_ledger():
    """The reason this went unnoticed, asserted rather than asserted about.

    `tests/test_cdm_publication.py` computes the unsigned set through git's own trailer reader.
    `c4a1071f` is not in it and must not be: it carries a valid sign-off. The two checks are about
    different properties of the same block and this is the line where that is visible.
    """
    from tests.test_cdm_publication import actual_unsigned_commits
    assert INCIDENT not in actual_unsigned_commits(), (
        f"{INCIDENT} now reads as unsigned. That is a different defect from the one recorded here "
        "and it belongs in the unsigned-commit ledger, not in this one"
    )


# ------------------------------------------------------- the set is a set, and it does not move


def stated_malformed_commits() -> list[str]:
    """The abbreviated SHAs `PUBLICATION.md` names under the malformed-trailer entry."""
    text = (REPO / RECORD).read_text()
    assert MALFORMED_HEADING in text, (
        f"{RECORD} no longer contains the heading {MALFORMED_HEADING!r}. This is a re-anchoring "
        "job and not a deletion: the entry records a defect left in the history deliberately"
    )
    start = text.index(MALFORMED_HEADING) + len(MALFORMED_HEADING)
    rest = text[start:]
    nxt = re.search(r"\n#{2,3} ", rest)
    section = rest[:nxt.start()] if nxt else rest
    # SCOPED ABOVE THE ENTRY'S DATED NOTES ON 2026-09-04, for the reason
    # `tests/test_cdm_publication.py::_before_the_dated_notes` records at length: the note added
    # to entry 7 that day names the three commits carrying two well-formed sign-offs, and a
    # section-wide scan read all three as members of the malformed set. An entry states its set
    # once, above its notes; a note may name whatever it needs to.
    #
    # THE HELPER IS IMPORTED AND NOT REIMPLEMENTED. Two modules parse two ledger entries the same
    # way, and the reason to share one function rather than copy four lines is the reason this
    # repository shares `gates/pin_paths.py`: the copy that drifts is the one nobody is looking at.
    found = re.findall(r"`([0-9a-f]{8})`", _before_the_dated_notes(section))
    assert found, (
        f"no backticked 8-hex commit id found under {MALFORMED_HEADING!r} in {RECORD}. Either the "
        "table changed shape — re-anchor deliberately — or the entry was emptied, which is a "
        "decision that must not be made by a regex quietly matching nothing"
    )
    return found


def actual_malformed_commits() -> list[str]:
    """Every commit HEAD reaches whose message this module refuses for a MALFORMED BLOCK.

    **PARTITIONED 2026-09-04, AND THE PARTITION IS THE POINT.** `defects()` used to refuse exactly
    one class — a trailer block that does not say what it appears to say — so "every commit this
    module refuses" and "entry 7's malformed set" were the same set and this helper could be the
    whole of it. RULING 3 added a second class: a message with no sign-off at all. Those commits
    are accounted for by entry 2 and not by entry 7, so a helper that returned all refusals would
    now compare a two-class set against a one-class ledger and fail for the right reason at the
    wrong site.

    The two classes are told apart by the ABSENCE OF A SIGN-OFF rather than by matching the defect
    string: a message is unsigned or it is not, which is a property of the message, and keying on
    the prose of an error message would make this helper break when somebody improves the wording.
    """
    out = []
    for rev in _git("rev-list", "HEAD").split():
        message = message_of(rev)
        if defects(message) and sign_offs(message):
            out.append(rev[:8])
    return out


def actual_unsigned_commits() -> list[str]:
    """Every commit HEAD reaches whose trailer block carries no sign-off. Entry 2's class."""
    return [rev[:8] for rev in _git("rev-list", "HEAD").split()
            if not sign_offs(message_of(rev))]


def test_the_malformed_set_in_the_record_is_the_malformed_set_in_the_history():
    """Both directions, the unsigned-commit ledger's property one defect along.

    A commit in the history and not in the record is a defect nobody accepted. A commit in the
    record and not in the history means the history was rewritten, which the record forbids in its
    own terms.

    SCOPED TO THE MALFORMED CLASS SINCE 2026-09-04 — see `actual_malformed_commits`. The unsigned
    class is asserted against entry 2 by the test below, and
    `test_the_defect_set_over_the_history_is_exactly_the_recorded_one` asserts that the two
    classes TOGETHER are the whole of what this module refuses, so nothing falls between them.
    """
    stated = set(stated_malformed_commits())
    actual = set(actual_malformed_commits())
    assert stated == actual, (
        f"the malformed-trailer ledger in {RECORD} and the history disagree.\n"
        f"  malformed in the history, absent from the record: {sorted(actual - stated)}\n"
        f"  named in the record, not malformed in the history: {sorted(stated - actual)}\n"
        "A new one is a message to fix BEFORE it is committed — `python gates/commit_message.py "
        "--file .git/COMMIT_EDITMSG` — not an entry to add."
    )


def test_the_two_refused_classes_together_are_the_whole_of_what_this_module_refuses():
    """THE SEAM BETWEEN THE TWO LEDGER ENTRIES, asserted so nothing can fall down it.

    Entry 7 accounts for malformed blocks and entry 2 for unsigned commits. Two helpers partition
    the refused set between them — but a partition is only a partition if it is exhaustive and
    disjoint, and neither is implied by the two tests above passing. A third class of defect added
    later, accounted for by neither entry, would leave both of those tests green.
    """
    refused = {rev[:8] for rev in _git("rev-list", "HEAD").split() if defects(message_of(rev))}
    malformed = set(actual_malformed_commits())
    unsigned = set(actual_unsigned_commits())
    assert not (malformed & unsigned), (
        f"{sorted(malformed & unsigned)} is in both classes. A commit cannot be unsigned and have "
        "a sign-off, so this means the two helpers disagree about what `sign_offs` returns"
    )
    assert malformed | unsigned == refused, (
        f"the two classes do not exhaust the refused set. Refused and in neither class: "
        f"{sorted(refused - (malformed | unsigned))}. Every commit this module refuses must be "
        "accounted for by PUBLICATION.md entry 2 or entry 7 — a third class needs a third entry, "
        "which is a decision and not something a passing suite should hide"
    )
    assert unsigned == {"d7986017", "2a51871f", "965e939d"}, (
        f"the unsigned set is {sorted(unsigned)} and PUBLICATION.md entry 2 accepts exactly three "
        "named commits. A fourth is 41d3d2d's class and must not reach origin/main"
    )


def test_the_malformed_check_is_not_vacuous():
    """A rule that found nothing would agree with an empty table and with a wrong one."""
    actual = actual_malformed_commits()
    assert actual, (
        "no commit in the history is refused, so the comparison above passes vacuously. The "
        f"incident at {INCIDENT} is real and is in the history; if it stopped being found, the "
        "rule stopped working"
    )


def test_the_tool_is_tracked_and_runnable():
    """A protocol act nobody can run is a protocol act nobody runs."""
    tool = REPO / "gates" / "commit_message.py"
    assert tool.is_file()
    assert "gates/commit_message.py" in _git("ls-files", "gates"), (
        "gates/commit_message.py is untracked, so it exists in one clone and the rule applies to "
        "one person"
    )
    done = subprocess.run([sys.executable, "gates/commit_message.py", "--rev", "HEAD~1"],
                          cwd=REPO, capture_output=True, text=True)
    assert done.returncode in (0, 1), f"the CLI crashed: {done.stderr}"
