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
    trailer_block,
    trailers_git_parses,
)

REPO = pathlib.Path(__file__).resolve().parents[1]

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


def test_a_message_with_no_sign_off_at_all_is_not_this_modules_business():
    """The unsigned-commit ledger owns that, and two checks on one fact is how they disagree.

    Asserted positively rather than left implied: a module that also refused unsigned messages
    would duplicate `tests/test_cdm_publication.py` and the two would drift.
    """
    unsigned = "Subject\n\nBody with no trailer block at all.\n"
    assert defects(unsigned) == [], (
        "this module refused an unsigned message. Sign-off PRESENCE belongs to the unsigned-commit "
        "ledger; what belongs here is whether the trailer block says what it appears to say"
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
    found = re.findall(r"`([0-9a-f]{8})`", section)
    assert found, (
        f"no backticked 8-hex commit id found under {MALFORMED_HEADING!r} in {RECORD}. Either the "
        "table changed shape — re-anchor deliberately — or the entry was emptied, which is a "
        "decision that must not be made by a regex quietly matching nothing"
    )
    return found


def actual_malformed_commits() -> list[str]:
    """Every commit reachable from HEAD whose message this module refuses, abbreviated to 8."""
    return [rev[:8] for rev in _git("rev-list", "HEAD").split() if defects(message_of(rev))]


def test_the_malformed_set_in_the_record_is_the_malformed_set_in_the_history():
    """Both directions, the unsigned-commit ledger's property one defect along.

    A commit in the history and not in the record is a defect nobody accepted. A commit in the
    record and not in the history means the history was rewritten, which the record forbids in its
    own terms.
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
