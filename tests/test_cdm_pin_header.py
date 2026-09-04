"""`klv_pin.json`'s header log, held to the counts it states.

WHY THIS EXISTS, AND IT IS AN INCIDENT RATHER THAN A PRINCIPLE
--------------------------------------------------------------
The pin record's root `what_this_is` is an append-only log. Each round that changes what the
directory holds appends a dated `UPDATED <date> BY THE <name> ROUND` clause, and the clauses that
change the holdings end by restating the arithmetic: *this directory now holds TEN documents of
which SEVEN are pins*.

**It stopped.** The last clause before this module existed was the day flight provenance round's,
2026-08-26. Two rounds on 2026-08-27 — the off-peak round and the pins round — added five pins
between them and appended nothing. The header went on saying seven while the record held twelve,
for two days, and **nothing failed**.

That is the whole shape of the defect and it is worth stating precisely, because it is not the
shape people guard against. The header did not become malformed, self-contradictory or
unparseable. It stayed **internally consistent, well-formed and pleasant to read**, and it
described a repository that had stopped existing. A log whose convention is "append when you
change something" has no way to notice the append that did not happen; the omission leaves no
trace in the artefact, which is exactly why a human sweep found it two days late and why the fix
is a derivation rather than a resolution to be careful.

WHAT IS DERIVABLE HERE, AND WHY THAT IS THE WHOLE POINT
-------------------------------------------------------
The counts the header states are not opinions. **Both sides of the equality live in the same
file**, so the check needs no network, no PDF library and no bytes on disk:

* the **pin count** is the wrapper, the target profile, and every entry under
  `delegated_specifications_held` carrying a `sha256`;
* the **document count** is those plus the lineage editions under `edition_history.files`, which
  are held and deliberately **not** pins — a distinction the record makes in prose and this module
  therefore makes in code;
* the **stated counts** are the last `holds N documents of which M are pins` clause in the header.

The equality is `stated == derived`. A round that adds a pin and does not append moves one side
and not the other, and the next `pytest` run says so.

WHY THE DOCUMENTS' ABSENCE DOES NOT WEAKEN THIS
-----------------------------------------------
Nothing under a `fixtures/*/spec/` is tracked but the pin records and the generators — so in a
fresh clone none of the eighteen documents this header counts is on disk. **This module never
looks at the disk.** It counts pin NODES, not files, which is why it is a real check in a fresh
clone and in the installed wheel rather than a check that quietly skips wherever the working tree
is thin. `tests/test_cdm_pins.py` is the module that digests the bytes when they are present; this
one is about the record's internal agreement with itself, and the two are deliberately different
jobs.

THIS HEADING SAID "THE PDFs' ABSENCE" UNTIL 2026-09-04 and cited `git ls-files | grep -c '\\.pdf$'`
as the reason. Both were true and both were narrower than the property: the text-pins round pinned
a document its publisher issues as text, so the thing that is absent from a clone is no longer a
set of PDFs. The load-bearing half — that this module reads NODES and never the disk — was true
throughout and is why the rewording changes no assertion.

FAILING LOUDLY WHEN THE SENTENCE MOVES
--------------------------------------
`test_cdm_prose_counts.py`'s rule, and for its reason: a pattern that silently matches nothing
reads as a passing check on a site nobody is checking any more. If `COUNT_CLAUSE` stops matching,
that is a FAILURE naming the pattern, not a quiet pass over zero clauses — and
`test_the_count_clause_pattern_is_not_vacuous` fails the suite if the pattern ever matches a
header it should not.

THE FIXTURES WITNESS THE FAILURE THAT HAPPENED
-----------------------------------------------
`HEADER_UNMOVED_AFTER_A_PIN_WAS_ADDED` is the recorded incident's exact shape — a pin node added,
the header untouched — and the guard must reject it. It is not a hypothetical: it is what the
file looked like from 2026-08-27 evening until the repair round, reduced to the smallest record
that still has the property.
"""
import copy
import json
import pathlib
import re

import pytest

import synapse_cdm

#: Anchored on the PACKAGE and not on the repository root, which is what puts this module in
#: `gates/wheel_install.py`'s `PACKAGE_ONLY_TESTS`: the record it reads ships in the wheel, so the
#: same assertions hold against an installed distribution. It reaches for the repository nowhere.
PIN_PATH = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures/klv/spec/klv_pin.json"

#: The clause shape the header's convention produces. Written to tolerate the two lead-ins the log
#: has actually used — "this directory now holds" and a bare "holds" — because re-anchoring a
#: pattern to prose that legitimately varies is how a guard acquires a false failure.
COUNT_CLAUSE = re.compile(
    r"holds\s+([A-Z]+)\s+documents\s+of\s+which\s+([A-Z]+)\s+are\s+pins", re.IGNORECASE)

#: The dated-clause shape. THE HYPHEN IN THE CHARACTER CLASS IS LOAD-BEARING and was earned: the
#: first draft of this pattern used `[A-Z0-9 ]+` and silently lost the OFF-PEAK ROUND's clause,
#: which is the precise failure mode the module docstring above calls worse than no test at all.
DATED_CLAUSE = re.compile(r"\b(UPDATED|APPENDED)\s+(\d{4}-\d\d-\d\d)\s+BY\s+THE\s+([A-Z0-9 -]+?ROUND)\b")

#: Spelled out because the header spells them out. Deliberately not `word2number` or a general
#: parser: the vocabulary is the one this log uses, and an unknown word must be a failure rather
#: than a silent zero.
NUMBER_WORDS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7, "EIGHT": 8,
    "NINE": 9, "TEN": 10, "ELEVEN": 11, "TWELVE": 12, "THIRTEEN": 13, "FOURTEEN": 14,
    "FIFTEEN": 15, "SIXTEEN": 16, "SEVENTEEN": 17, "EIGHTEEN": 18, "NINETEEN": 19, "TWENTY": 20,
}


def load() -> dict:
    return json.loads(PIN_PATH.read_text())


def derived_counts(record: dict) -> tuple[int, int]:
    """`(documents, pins)`, computed from the record's own nodes.

    A pin is a node carrying a `sha256` that names a DOCUMENT: the wrapper, the target profile and
    the entries under `delegated_specifications_held`. The lineage editions under
    `edition_history.files` are held and are explicitly not pins, so they raise the document count
    and not the pin count — which is the distinction the header's two numbers exist to carry, and
    the reason this returns a pair rather than one figure.
    """
    pins = 0
    for name in ("wrapper", "target"):
        if "sha256" in record.get(name, {}):
            pins += 1
    for value in record.get("delegated_specifications_held", {}).values():
        if isinstance(value, dict) and "sha256" in value:
            pins += 1
    lineage = len(record.get("edition_history", {}).get("files", []))
    return pins + lineage, pins


def stated_counts(record: dict) -> tuple[int, int]:
    """The LAST count clause in the header, as a pair.

    The last one and not the first: the log is a history, every earlier clause is a true statement
    about an earlier day, and only the final one is a claim about the record as it stands.
    """
    header = record["what_this_is"]
    clauses = COUNT_CLAUSE.findall(header)
    assert clauses, (
        f"COUNT_CLAUSE matched NOTHING in {PIN_PATH.name}'s header. The pattern is "
        f"{COUNT_CLAUSE.pattern!r}. This is a failure and not a pass over zero clauses: either the "
        "header's convention for restating its arithmetic has changed, in which case re-anchor "
        "this pattern deliberately, or the clauses have been deleted, in which case the header no "
        "longer states what this module exists to check")
    documents_word, pins_word = clauses[-1]
    for word in (documents_word, pins_word):
        assert word.upper() in NUMBER_WORDS, (
            f"the header's last count clause spells a number this module does not know: {word!r}. "
            "Add it to NUMBER_WORDS deliberately rather than letting an unknown word read as zero")
    return NUMBER_WORDS[documents_word.upper()], NUMBER_WORDS[pins_word.upper()]


# ==================== the equality itself


def test_the_header_states_the_pin_count_the_record_actually_carries():
    """The guard, and the one assertion the incident would have failed.

    On 2026-08-27 the derived pin count became twelve and the stated one stayed seven. Nothing in
    the file was malformed; the two numbers had simply come apart, and no check compared them.
    """
    record = load()
    stated_documents, stated_pins = stated_counts(record)
    derived_documents, derived_pins = derived_counts(record)
    assert (stated_documents, stated_pins) == (derived_documents, derived_pins), (
        f"{PIN_PATH.name}'s header states {stated_documents} documents of which {stated_pins} are "
        f"pins; the record carries {derived_documents} and {derived_pins}. This is the append that "
        "did not happen. APPEND a dated clause recording what changed — do NOT edit an existing "
        "clause to make this pass, because every clause below the last one is a true statement "
        "about the day it names and the log's append-only character is the thing being preserved")


def test_the_header_is_a_dated_log_and_every_clause_carries_a_date_and_a_round():
    """The convention the equality above rests on, checked rather than assumed."""
    record = load()
    clauses = DATED_CLAUSE.findall(record["what_this_is"])
    assert len(clauses) >= 5, (
        f"DATED_CLAUSE found {len(clauses)} dated clauses and the log has carried at least five "
        f"since 2026-08-27. Pattern: {DATED_CLAUSE.pattern!r}")
    dates = [date for _, date, _ in clauses]
    assert dates == sorted(dates), (
        f"the header's dated clauses are out of order: {dates}. The log is append-only, so a "
        "clause dated before the one above it means a clause was inserted rather than appended")


def test_the_counts_only_ever_rise_because_no_pin_has_ever_been_withdrawn():
    """Every count clause in the log, as a ladder a reader can walk.

    A monotone ladder is what makes the header checkable by eye as well as by this module. It is
    asserted rather than assumed because a repair that renumbered an old clause — the backfill the
    guard above refuses — would most likely show up here first.
    """
    record = load()
    ladder = [(NUMBER_WORDS[d.upper()], NUMBER_WORDS[p.upper()])
              for d, p in COUNT_CLAUSE.findall(record["what_this_is"])]
    assert len(ladder) >= 3, f"expected at least three count clauses, found {len(ladder)}: {ladder}"
    for (documents, pins), (next_documents, next_pins) in zip(ladder, ladder[1:]):
        assert next_documents >= documents and next_pins >= pins, (
            f"the header's count ladder goes backwards: {ladder}")
    for documents, pins in ladder:
        assert pins <= documents, (
            f"a clause claims more pins than documents, which is not a state this record can be "
            f"in: {ladder}")


def test_the_lineage_editions_raise_the_document_count_and_not_the_pin_count():
    """The distinction the two numbers exist to carry.

    `edition_history.files` holds three 0601 editions that are held and NOT pinned. If this module
    counted them as pins the equality would still balance today and would be checking a different
    claim than the header makes.
    """
    record = load()
    documents, pins = derived_counts(record)
    assert documents - pins == len(record["edition_history"]["files"]) == 3, (
        f"documents {documents}, pins {pins}, lineage "
        f"{len(record['edition_history']['files'])} — the gap between the two counts IS the "
        "lineage set, and if that stops being true this module's arithmetic needs re-deriving")


# ==================== the mutations, each the shape of a real or a plausible failure


@pytest.fixture()
def record():
    return load()


def test_a_pin_added_with_the_header_unmoved_is_REFUSED(record):
    """HEADER_UNMOVED_AFTER_A_PIN_WAS_ADDED — the recorded incident, reduced.

    This is what the file looked like from the pins round until the repair round: a new pin node
    present, the header's last clause untouched and still perfectly well-formed.
    """
    mutated = copy.deepcopy(record)
    mutated["delegated_specifications_held"]["st_9999_9"] = {
        "edition": "9999.9", "sha256": "0" * 64, "bytes": 1, "pages": 1,
        "local_path": "fixtures/klv/spec/ST9999.9.pdf",
    }
    stated = stated_counts(mutated)
    derived = derived_counts(mutated)
    assert stated != derived, (
        "a pin was added and the header was left alone, and the two counts still agree — the guard "
        "would not have caught the incident it was built for")


def test_a_pin_removed_with_the_header_unmoved_is_REFUSED(record):
    """The mirror, which has never happened here and is checked anyway."""
    mutated = copy.deepcopy(record)
    held = mutated["delegated_specifications_held"]
    victim = next(k for k, v in held.items() if isinstance(v, dict) and "sha256" in v)
    del held[victim]
    assert stated_counts(mutated) != derived_counts(mutated)


def test_a_lineage_edition_added_with_the_header_unmoved_is_REFUSED(record):
    """A document that is not a pin still moves one of the two numbers."""
    mutated = copy.deepcopy(record)
    mutated["edition_history"]["files"].append(
        {"filename": "ST0601.99.pdf", "edition": "0601.99", "sha256": "1" * 64, "bytes": 2})
    stated_documents, stated_pins = stated_counts(mutated)
    derived_documents, derived_pins = derived_counts(mutated)
    assert stated_documents != derived_documents, (
        "a held-but-unpinned edition was added and the document count did not move")
    assert stated_pins == derived_pins, (
        "adding a lineage edition must NOT move the pin count — if it does, this module is "
        "counting the lineage set as pins and is checking the wrong claim")


def test_an_EDITED_last_clause_passes_the_equality_and_that_is_why_the_message_forbids_it(record):
    """The honest limit of this guard, asserted so nobody mistakes its reach.

    Editing the last clause's numbers satisfies the equality exactly as appending a new clause
    does. **This module cannot tell those apart** — both leave the file balanced. What stops the
    edit is the failure message, which says to append, and the reviewer reading the diff. Stating
    the limit in a test is better than implying a reach the check does not have.
    """
    mutated = copy.deepcopy(record)
    mutated["delegated_specifications_held"]["st_9999_9"] = {"sha256": "0" * 64}
    documents, pins = derived_counts(mutated)
    header = mutated["what_this_is"]
    last = list(COUNT_CLAUSE.finditer(header))[-1]
    inverse = {v: k for k, v in NUMBER_WORDS.items()}
    mutated["what_this_is"] = (
        header[:last.start()]
        + f"holds {inverse[documents]} documents of which {inverse[pins]} are pins"
        + header[last.end():])
    assert stated_counts(mutated) == derived_counts(mutated), (
        "a rewritten last clause is expected to satisfy this guard — the docstring says so")


# ==================== non-vacuity


def test_the_count_clause_pattern_is_not_vacuous():
    """The pattern must match what it is for and must not match what it is not for.

    A regex that matches everything is as useless as one that matches nothing, and the first draft
    of a pattern like this one is usually the former.
    """
    assert COUNT_CLAUSE.findall("holds FIFTEEN documents of which TWELVE are pins") == [
        ("FIFTEEN", "TWELVE")]
    for negative in (
        "holds fifteen documents",
        "of which twelve are pins",
        "holds FIFTEEN documents of which TWELVE are parks",
        "the directory is large",
    ):
        assert not COUNT_CLAUSE.findall(negative), f"pattern wrongly matched {negative!r}"


def test_the_dated_clause_pattern_keeps_the_hyphenated_round_it_once_lost():
    """A regression, and the reason `DATED_CLAUSE`'s character class carries a hyphen.

    `[A-Z0-9 ]+` DROPS THE WHOLE OFF-PEAK CLAUSE — not truncating it to "PEAK ROUND", which is
    what a first guess predicts, but failing to match it at all, because the hyphen breaks the run
    the class must cross to reach ROUND. So the clause is present in the header and the pattern
    reports one fewer, with no error anywhere. That happened while this module was being written,
    which is the only reason it is known.
    """
    sample = ("UPDATED 2026-08-27 BY THE OFF-PEAK ROUND: text. "
              "UPDATED 2026-08-27 BY THE PINS ROUND: more text.")
    found = [name for _, _, name in DATED_CLAUSE.findall(sample)]
    assert found == ["OFF-PEAK ROUND", "PINS ROUND"], found
    narrow = [n for _, _, n in re.findall(
        r"\b(UPDATED|APPENDED)\s+(\d{4}-\d\d-\d\d)\s+BY\s+THE\s+([A-Z0-9 ]+?ROUND)\b", sample)]
    assert narrow == ["PINS ROUND"], (
        f"the narrow class no longer loses the hyphenated clause (it found {narrow}), so this "
        "regression note needs re-deriving")
    assert len(narrow) == len(found) - 1, (
        "the failure mode this note records is UNDER-COUNTING BY ONE WITH NO ERROR, and that is "
        "the property worth keeping true in the note")


def test_the_guard_passes_on_the_real_record_which_is_what_makes_the_mutations_mean_anything():
    """The positive control.

    Every mutation above asserts that a broken record is REFUSED. That is only evidence if the
    unbroken record is ACCEPTED — otherwise the mutations would pass against a guard that refuses
    everything.

    THE PAIR MOVED FROM (17, 14) TO (18, 15) TO (19, 16) ON 2026-09-04, twice in one day, and
    each move is what a control is FOR.
    The text-pins round pinned IETF RFC 2781 as a text document, which added one node carrying a
    `sha256` under `delegated_specifications_held` — so the derived pin count went to fifteen and
    the derived document count to eighteen, and the header gained an APPENDED dated clause saying
    so. **The number here had to move with it, and that is the whole hazard this test carries.** A
    control whose expectation is a literal goes stale in exactly one direction: somebody adds a pin,
    the equality assertion above fails, they append the clause, the equality passes, and THIS test
    still fails against the old literal — which is the good case, because it is loud. The bad case
    is the one where a maintainer reads the literal as the authority and edits the header to match
    it. It is not the authority; `derived_counts` is, and this line is a witness that the two agree
    at a number a human has read.

    **AND IT MOVED A SECOND TIME THE SAME DAY**, in the park 3 round, which pinned MISB ST
    0603.5 — an ordinary PDF pin of a delegated document, so both counts moved by one and
    neither moved for a reason peculiar to its kind. Two moves in one day is the loudest
    argument available for the literal being a witness rather than the authority: a pair
    that moves twice between two commits is a pair nobody could have carried in their head.
    """
    record = load()
    assert stated_counts(record) == derived_counts(record) == (19, 16)
