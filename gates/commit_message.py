"""Commit messages held to one rule: a trailer is a trailer and prose is prose.

WHY THIS EXISTS, AND IT IS AN INCIDENT RATHER THAN A PRINCIPLE
--------------------------------------------------------------
`c4a1071f` carries two `Signed-off-by:` trailers. Git parses both, because both sit in the
message's last paragraph and that paragraph is the trailer block:

    Signed-off-by: nothing else changed; the suite is unmoved at 3151 passed, 2 skipped.
    Signed-off-by: Matej Michalko <m@decentcybersecurity.eu>

The first is a sentence of prose that acquired a trailer key. **Nothing noticed.** The suite's
unsigned-commit ledger reads sign-offs through git's own
`%(trailers:key=Signed-off-by,valueonly)`, finds a non-empty value, and calls the commit signed —
which it is, by the second line. The DCO app would agree for the same reason. So a malformed
trailer block is invisible to every check that asks "is there a sign-off?", and the only thing
that reads it is a human, later, trying to work out who certified what.

THE CLASS, WHICH IS WIDER THAN THE INCIDENT
-------------------------------------------
Git's rule is positional: **the trailer block is the last paragraph and nothing else is.** Two
failures follow from that and they are mirror images:

1. **prose inside the block** — a line in the last paragraph that git parses as a trailer and a
   human never meant as one. That is `c4a1071f`.
2. **a trailer outside the block** — a `Signed-off-by:` line stranded mid-body, which looks like
   a sign-off to every human reader and **is not one to git**, so a commit that appears signed is
   unsigned to the DCO app and to the ledger.

The second is the more dangerous of the two and it has never happened here. It is checked anyway,
because the reason it has not happened is that `git commit -s` appends the trailer itself — and
the moment a message is written by hand, pasted, or assembled by a script, that protection is
gone.

WHAT COUNTS AS AN INTENDED TRAILER
----------------------------------
A known key and a value of the shape that key requires. The vocabulary was **derived** from git's
own parse of all 95 messages rather than decided: `Signed-off-by` (93), `Co-Authored-By` (51) and
`Suite` (1) are the only keys that occur. `Suite` occurring once is itself a finding — a one-line
result summary that had never been declared anywhere, and the key `c4a1071f` was reaching for when
it typed a sign-off instead.

The split between them is the rule. `Signed-off-by` and `Co-authored-by` **certify a person**, so
their values are identities and prose under either is a false statement about provenance. `Suite`
certifies nothing, so any non-empty line is a legitimate value for it. An unknown key is refused
rather than ignored: widening the vocabulary is a decision, and a vocabulary widened by a typo is
exactly the failure above.

WHAT THIS MODULE IS NOT
-----------------------
It is not a hook and it cannot be one that anybody would receive: this repository ships no
`.git/hooks`, and a hook that lives in one clone is a rule that applies to one person. It is a
check, runnable on a message before the commit and over the whole history afterwards.
`tests/test_cdm_commit_message.py` runs it both ways and holds it to both directions — a message
with a mid-body sign-off must be refused, and a clean message must pass.

USAGE

    python gates/commit_message.py --rev HEAD          # a commit already made
    python gates/commit_message.py --file .git/COMMIT_EDITMSG
    git log -1 --format=%B | python gates/commit_message.py -

Exit `0` if the message is clean, `1` if it is not, and the defects are printed one per line with
the offending text quoted. Over a range:

    python gates/commit_message.py --range origin/main..HEAD
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Identity: a name and an address in angle brackets. Deliberately loose about the name and strict
#: about the shape — this decides whether the value is an identity AT ALL, not whether the address
#: exists. `CONTRIBUTING.md` owns that second requirement and no local check can decide it.
IDENTITY = re.compile(r"^\S.*\s<[^<>@\s]+@[^<>@\s]+>$")

#: The trailer vocabulary this repository uses, derived by reading git's own parse of every commit
#: in the history rather than by deciding what it ought to be: `Signed-off-by`, `Co-Authored-By`
#: and `Suite` are the only keys that occur. Each maps to what its value has to look like.
#:
#: The split is the whole rule. `Signed-off-by` and `Co-authored-by` CERTIFY A PERSON, so their
#: values are identities and prose under either of them is a false statement about provenance —
#: that is the defect this module exists for. `Suite` certifies nothing; it is a one-line result
#: summary and any non-empty text is a legitimate one.
#:
#: An unknown key is refused rather than ignored. Widening the vocabulary is a deliberate act, and
#: a vocabulary widened by a typo is how a mislabelled line gets in.
KNOWN_KEYS: dict[str, tuple[re.Pattern[str], str]] = {
    "signed-off-by": (IDENTITY, "a name and an address in angle brackets"),
    "co-authored-by": (IDENTITY, "a name and an address in angle brackets"),
    "suite": (re.compile(r"^\S.*$"), "a one-line summary of what the suite reported"),
}

#: Git's own trailer syntax, narrowed to the keys that certify a person. Those are the only ones
#: worth hunting for mid-body: a stranded `Suite:` line is untidy, a stranded sign-off is a commit
#: that reads as signed and is not.
CERTIFYING_KEYS = ("Signed-off-by", "Co-authored-by")
KNOWN_TRAILER_LINE = re.compile(
    r"^(?P<key>" + "|".join(re.escape(k) for k in CERTIFYING_KEYS) + r")\s*:\s*(?P<value>.*)$",
    re.IGNORECASE,
)

#: Any `Token: value` line, which is what git considers trailer-SHAPED inside the block.
ANY_TRAILER_LINE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9-]*)\s*:\s*(?P<value>.*)$")


class NotAGitRepository(RuntimeError):
    """Raised when git itself is unavailable — the parse below has no substitute."""


def _git(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, input=stdin,
                          capture_output=True, text=True)


def trailers_git_parses(message: str) -> list[str]:
    """The trailer lines **git itself** finds in `message`, in order.

    `git interpret-trailers --parse` and not a regex of our own, for the reason the unsigned-commit
    ledger gives for reading `%(trailers:…)`: a check that disagreed with git about which lines are
    trailers would be checking something nobody else applies. This is the same parser the DCO app's
    notion of a sign-off rests on.
    """
    done = _git("interpret-trailers", "--parse", stdin=message)
    if done.returncode != 0:
        raise NotAGitRepository(
            "`git interpret-trailers --parse` failed, so there is no authority for what a trailer "
            f"is: {done.stderr.strip()}"
        )
    return [line for line in done.stdout.splitlines() if line.strip()]


def trailer_block(message: str) -> tuple[list[str], list[str]]:
    """`(body_lines, block_lines)` — the message split at its last blank line.

    Git's rule is positional and this mirrors it: the trailer block is the final paragraph. A
    message with no blank line in it has no trailer block at all, and every trailer-shaped line in
    it is therefore in the body — which is the correct reading, because git will not parse a
    subject line as a trailer either.
    """
    lines = message.rstrip("\n").split("\n")
    last_blank = max((i for i, line in enumerate(lines) if not line.strip()), default=None)
    if last_blank is None:
        return lines, []
    return lines[:last_blank], lines[last_blank + 1:]


def defects(message: str) -> list[str]:
    """Every reason to refuse `message`, as sentences. Empty means clean.

    Both directions of the class in the module docstring, and the order below is the order a
    reader wants them: what git actually parsed first, then what it could not see.
    """
    found: list[str] = []
    body, block = trailer_block(message)
    parsed = trailers_git_parses(message)

    # 1. Prose inside the block. Every line git parses as a trailer has to be one somebody meant.
    for line in parsed:
        shaped = ANY_TRAILER_LINE.match(line)
        if shaped is None:
            found.append(
                f"git parses {line!r} as a trailer and it is not a `Token: value` line at all"
            )
            continue
        key, value = shaped.group("key"), shaped.group("value").strip()
        rule = KNOWN_KEYS.get(key.lower())
        if rule is None:
            found.append(
                f"the trailer block carries the unknown key {key!r} ({line!r}). The vocabulary is "
                f"{', '.join(sorted(KNOWN_KEYS))}; adding to it is a deliberate act and not "
                "something a message should do in passing"
            )
            continue
        shape, wanted = rule
        if not shape.match(value):
            found.append(
                f"`{key}:` carries {value!r}, and this key takes {wanted}. A line of prose that "
                "lands in the last paragraph is parsed as a trailer by git and read as one by "
                "everything downstream — the DCO app included"
            )

    # 2. A trailer stranded in the body, where git cannot see it. Restricted to the known keys on
    #    purpose: this repository's messages are prose, and `Ground 1: …` or `USAGE: …` are not
    #    trailers to anybody. A general `Token: value` ban here would flag the prose and teach the
    #    reader to ignore the check.
    for offset, line in enumerate(body, start=1):
        shaped = KNOWN_TRAILER_LINE.match(line)
        if shaped is None:
            continue
        found.append(
            f"line {offset} is {line!r}, which reads as a sign-off and is not one: git parses "
            "trailers in the last paragraph only, so this line is body text to git, to the DCO "
            "app and to every check that asks whether the commit is signed"
        )
    return found


def check(message: str) -> None:
    """Raise `ValueError` carrying every defect, or return quietly."""
    found = defects(message)
    if found:
        raise ValueError("\n".join(f"  - {reason}" for reason in found))


def message_of(rev: str) -> str:
    done = _git("log", "-1", "--format=%B", rev)
    if done.returncode != 0:
        raise SystemExit(f"no such revision {rev!r}: {done.stderr.strip()}")
    return done.stdout


def revisions(rng: str) -> list[str]:
    done = _git("rev-list", rng)
    if done.returncode != 0:
        raise SystemExit(f"cannot list {rng!r}: {done.stderr.strip()}")
    return done.stdout.split()


def _report(label: str, message: str) -> bool:
    found = defects(message)
    if not found:
        return True
    print(f"{label}: {len(found)} defect(s)")
    for reason in found:
        print(f"  - {reason}")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--rev", help="check the message of one revision")
    source.add_argument("--range", dest="rng", help="check every revision in a range")
    source.add_argument("--file", help="check a message file, e.g. .git/COMMIT_EDITMSG")
    source.add_argument("-", dest="stdin", action="store_true", help="check a message on stdin")
    args = parser.parse_args(argv)

    if args.stdin:
        clean = _report("<stdin>", sys.stdin.read())
    elif args.file:
        clean = _report(args.file, pathlib.Path(args.file).read_text())
    elif args.rev:
        clean = _report(args.rev, message_of(args.rev))
    else:
        revs = revisions(args.rng)
        clean = all([_report(rev[:8], message_of(rev)) for rev in revs])
        print(f"{len(revs)} message(s) checked")

    print("clean" if clean else "REFUSED")
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
