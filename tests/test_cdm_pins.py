"""The pin gate, derived rather than enumerated.

WHY THIS EXISTS
---------------
The push gate used to name the pins by hand, and it went stale the way hand-maintained lists go
stale: the last one named **eight** pinned PDFs while the tree at that moment held **nine**.
Nothing was wrong with any of the nine — the list had simply not been extended when CAT048's
EUROCONTROL pin landed, and a gate that under-counts what it is checking reports a clean run over a
smaller tree than the one in front of it. (Those two numbers are the historical ones and they are
left as they were. The tree holds **fourteen** pins across **eight** homes today, and nothing below
restates that: the gate derives it, which is the point. Those two numbers moved on 2026-08-26, when
ST 0601.19, ST 0102.12 and then ST 0601.14 landed in `fixtures/klv/spec/` — a directory that was
already a home, which is why the pin count moved by three and the home count did not move at all.)

So the enumeration is gone. This module *discovers* the pin set from the two places the repository
already states it, and then compares that set against the disk:

* every `*_pin.json` under `fixtures/` that declares a `local_path` with a `sha256` and a `bytes`;
* every pin row in `FORMAT_COVERAGE.md`, which are written
  ``| SHA-256 (wrapper) | `<64 hex>`, 558 866 bytes, 6 pages, `fixtures/…/x.pdf` |``.

Both are needed and neither is redundant. `gmti` and `nits` state their pins only in the document;
`cat048` states its local path only in its pin record; `klv` and `fft` state both, which is what
makes the two sources checkable against each other. A pin recorded in neither place is not a pin —
it is a PDF somebody left in `spec/`.

THE CLOSURE PROPERTY, WHICH IS THE PART WITH TEETH
--------------------------------------------------
The derived set must EQUAL the PDFs actually sitting directly in a `fixtures/*/spec/` directory.
Equality in both directions is what an enumeration could never give: a pin recorded and missing
from disk fails, and a PDF on disk recorded nowhere fails. The eight-versus-nine drift is caught by
the second direction, positively, without anybody counting.

THE CITED CLASS, WHICH IS NEITHER A PIN NOR AN ABSENCE
-------------------------------------------------------
Everything above assumes that a document this repository names is a document whose bytes it may
hold. #9's classification contingency breaks that assumption before it has to: if ADatP-36
Edition B turns out to be NATO RESTRICTED, the FFT round takes the **cite-not-carry** branch —
promulgation identity, edition, date and the NSDD classification line recorded, and the bytes never
in this tree at all. See `FORMAT_COVERAGE.md`, "The classification contingency, and why it is
written before the fact that decides it".

Such an entry is a third thing. It is not a pin — there is no hash, no byte count and no copy to
compare against — and it is not an absence either, because the repository is asserting a document's
identity and citing its clauses. The closure property above has no vocabulary for it, so the
vocabulary is added **before** the first entry exists rather than under time pressure with the
document already in hand and nowhere lawful to put it.

A cited entry is a node in a `*_pin.json` carrying ``"cite_not_carry": true``. It must state what
it is (`document`, `edition`, `classification`, `why_not_carried`) and, in `must_not_appear_at`,
the `fixtures/*/spec/` path the document *would* occupy if it were carried. That last field is what
gives the class teeth: **a cited document that grows bytes on disk fails**, which is the branch's
whole point.

Three properties are asserted, and one of them is asserted at zero:

* **disjoint from the pin set, both directions.** One path may not be both recorded as a pin and
  declared cite-not-carry. The property is symmetric and the two messages are not, because the
  repair depends on which record is the newer one;
* **no measurement.** A cited node carrying `sha256`, `bytes`, `pages` or `local_path` has measured
  a copy, which is the thing the branch forgoes. Refused by key;
* **no bytes, anywhere under `fixtures/`** — not at `must_not_appear_at` and not under any other
  name that basename could take, so dropping the file into a `history/` subdirectory fails too.

**Today the class is empty, and that is Branch U's shape, not a broken parser.** An empty discovery
would satisfy all three vacuously, so the parser is factored out as `citations_in()` and exercised
against a synthetic record — the only honest way to keep a zero-member class load-bearing.

A THIRD CLASS, AND IT IS COMPUTED WHERE THE OTHER TWO ARE DECLARED
------------------------------------------------------------------
**Cited-but-unpublished**: an edition a sibling specification names and no publisher offers. It is
a fourth thing again — not a pin, not an absence, not a cited-not-carried document, because nobody
declined to carry it and nobody could. CAT034 Edition 1.30 is the member and the state was prose
for two rounds before it was a class.

What makes it different from the two above is that **nothing declares it**. A pin is declared by a
record with a hash; a cite-not-carry entry is declared by a flag; membership here is the
CONJUNCTION of two halves discovered separately —

* **the citation**, found by reading quotations across every pin record for an identifier followed
  by an edition. The member's strongest one sits in `cat048_pin.json`, written a round before the
  cited document had a pin at all;
* **the availability**, from a dated check in the pin record for that identifier, stating an
  edition and whether it is `offered`. Two machine-readable fields in a node that is otherwise
  prose for a human.

A flag would let a round assert the class without doing the work — the state's whole content is
"somebody looked and did not find it", and a flag records that somebody SAID so. `classify()`
sorts every cited edition into **held**, **member** or **candidate**, and its docstring carries the
ruling on the question that decides the class's shape: **a citation alone does not join.** It
yields a candidate, the candidate set must be empty, and only a dated check turns a question into a
finding — because inferring unavailability from a citation is the exact mistake that produced the
class.

**The reopen is a test failure, not a state change.** When the edition publishes it becomes the
pinned one, `classify()` sorts it into `held`, the declared roster stops matching, and the gate
fails naming the pair. That is deliberate: a document leaving this class is an event somebody has
to see.

SINGLETON TREE-FACTS: RULED **NOT** MECHANICALLY CHECKED, AND THE MEASUREMENT IS WHY
-------------------------------------------------------------------------------------
The pre-publication audit found `cat048_pin.json` asserting "no .gitignore exists anywhere in
this repository". That was **false when it was written** — `.gitignore` landed in `965e939` on
2026-08-22 and the sentence in `7e13f27` a day later — and nothing could have caught it: the
disjunction protocol only compares facts stated at two or more sites, and this was a **singleton**
claim about the tree, mechanically checkable and checked by nobody.

So: should a sweep parse factual claims about the tree out of the pin records and verify them?
**No, and the number that decides it was measured rather than argued.** A sweep over path-shaped
tokens in the six pin records finds **209 distinct tokens, of which 175 do not resolve on disk** —
and almost none of the 175 is a path. They are ASTERIX data-item numbers (`I048/230`, `I034/120`,
sixty of them), bit ranges (`bits-16/13`), LSB fractions (`1/128`, `360/2`), DD/MM/YYYY dates
(`15/03/2021`), compound English (`and/or`, `Warning/Error`, `Mode-3/A`, `SAC/SIC`), bilingual
NATO headers (`April/avril`), and document references (`ED-73F/DO-181F`). **Eighty-four per cent
noise**, and the exemption list would have to encode "an ASTERIX item number is not a path" — which
is exactly the trade `tests/test_cdm_prose_counts.py` refuses in its own docstring: *the
maintenance cost of the exemption list would exceed the cost of the sweep it replaced.*

And the residue does not rescue it. Every repo-path in the records that does NOT resolve is one of
three things: a **deliberately-rejected candidate** (`fixtures/adatp36/spec/…`, `fixtures/misp/…`,
`fixtures/cat034/history/` — named in order to be declined), a **punctuation artefact** of a real
path (`fixtures/klv.`, `tests/test_cdm_ordinals.py.`), or a **private-core reference** that is
correctly absent here (`airtasking/SOURCES.md`). Telling those apart needs the SENTENCE, not the
token. A sweep assuming "mentioned implies must exist" fires on all of them; one assuming nothing
fires on none.

WHAT ALREADY IS MECHANICAL, WHICH IS WHY THE GAP IS NARROWER THAN IT LOOKS
--------------------------------------------------------------------------
Every path that carries weight is already a FIELD with a gate on it. `local_path` must exist and
must hash to its record — `test_every_pin_is_present_intact_and_untracked`. `must_not_appear_at`
must NOT exist, anywhere under `fixtures/`, under any name —
`test_no_cited_document_has_grown_bytes_anywhere_under_fixtures`. What failed was neither: it was a
**prose aside**, in a field whose job is to explain a decision. Structured claims are gated; prose
asides are what review is for, and this one got through review twice.

THE COMPENSATING ACT, AND IT PAID FOR ITSELF IMMEDIATELY
---------------------------------------------------------
Ruling "no" obliges the round to do by hand what it declined to automate. All twenty-five
existence claims in the six records were swept and the tree-facts among them verified: `git
ls-files | grep -ci pdf` is 0; this module does assert that; `asterix_cat021.py` contains no
reference to Part 1 (0 occurrences); `FORMAT_COVERAGE.md`'s STANAG 5527 section has no status
column (0). **And the sweep found a SECOND instance of the same false claim**, in
`klv_pin.json`, written in `1b0316b` on 2026-08-23 — the sentence had been copied between records
without its premise being re-checked. The audit found one; the hand sweep found the other. That is
the argument for the manual act being real work rather than a concession.

THE FRESH-CLONE BOUNDARY: WHICH PDF-TOUCHING CHECK SKIPS AND WHICH ONE MUST STILL FAIL
----------------------------------------------------------------------------------------
No pinned document is tracked, so **the ordinary state of this repository for everybody who is not
its maintainer is: records present, bytes absent.** Thirteen checks here touch a PDF and eleven of
them already skipped on a fresh clone; two did not, and an outsider's first run was
`2 failed`. Both were repaired, and they were repaired DIFFERENTLY — which is the useful part, and
the reason this section exists instead of two more skip lines.

**The rule. A check skips iff its subject is BYTES; it must fail iff its subject is a RECORD, the
INDEX, or the IGNORE RULES.** All three of the latter are in every clone in full, so a clone can
decide them, and a check that went quiet about them would be reporting a pass over a document
nobody looked at. Bytes are the only thing a clone legitimately cannot produce.

Read as a table, and the middle column is the question to ask of the next check that lands here:

===========================================  ==========================  ====================
check                                        subject                     fresh clone
===========================================  ==========================  ====================
size and hash of a held document             the bytes                   **SKIP**, per pin
every history PDF against its lineage        the bytes                   **SKIP**, per lineage
the derived pin set equals what is on disk   the bytes                   **SKIP** — but see below
`.gitignore` refuses to stage a document     the ignore RULES            **runs, must fail**
no PDF is tracked anywhere                   the INDEX                   **runs, must fail**
a pin record's fields, roster, page method   the RECORD                  **runs, must fail**
every prose site states the same count       the RECORD                  **runs, must fail**
===========================================  ==========================  ====================

The two repairs, because neither is "add a skip and move on":

* `test_the_derived_pin_set_equals_the_pdfs_in_spec_directories` compares the record against the
  disk, so half of it is genuinely about bytes. It now skips **only when the tree holds no
  specification document at all** — not per missing pin. A tree holding SOME is a maintainer's
  tree, and "recorded and not on disk" is exactly the 80b38d1 defect (a file moved out from under
  its record) that this check exists to catch; degrading it to per-pin skips would retire that
  property to catch nothing. Holding none is a fresh clone, and completeness is not a claim a
  fresh clone is making.
* `test_gitignore_refuses_a_specification_document_before_the_gate_has_to` **does not skip at all
  any more**, and by the rule above it must not: the ignore rules are the subject and they are in
  the clone. What was missing was not the rules but the paths to try them on, and it was asking
  the disk for those. It now asks the RECORD as well — `git check-ignore --no-index` answers about
  a path, not about a file, and returns the same verdict for a document nobody holds. So the check
  runs everywhere, over the union of the recorded pin paths and whatever is on disk: fourteen paths
  on a fresh clone, forty-seven here. It got STRONGER by being made to work for an outsider, which
  is the outcome to prefer over a skip whenever the subject allows it.

And the skip messages are held to a shape, because a skip nobody can read is a silent pass: **name
what is absent, and say the clone has the record and not the PDF.** Eleven siblings already say it
that way and the twelfth now matches them.

WHAT IS NOT A PIN
-----------------
**Two** `spec/history/` directories now hold edition lineages, and neither holds a pin.
`fixtures/cat048/spec/history/` holds 22 CAT048 edition PDFs — 1.10 to 1.32, governing text
Edition 1.32 alone — and `fixtures/cat034/spec/history/` holds 3 CAT034 edition PDFs — 1.26, 1.27
and 1.28, governing text Edition 1.29 alone. All 25 are covered by the zero-tracked check like every
other PDF and none is a pin. That distinction is asserted in both directions here, because the
placement invites the opposite reading — 80b38d1's harness message tells a reader that "pinned
standards live in `spec/`", and 24 non-pins inside `spec/` would otherwise read as 24 pins.

The rule is written against `history/` as a NAME rather than against the two directories that have
one, so the third lineage needs no edit here. What does need an edit each time is the per-format
count check, and that is deliberate: a count nobody restates is a count nobody notices going stale.
"""
import hashlib
import json
import pathlib
import re
import subprocess

import pytest

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
FIXTURES = PKG / "fixtures"
DOC = PKG / "FORMAT_COVERAGE.md"

#: Pin records and FORMAT_COVERAGE.md both write a pin path as `fixtures/gmti/spec/x.pdf` —
#: relative to the PACKAGE, which is the form every one of those documents uses. Git speaks
#: repo-relative. The recorded form is the key here and `_full` and `_repo_rel` convert, because
#: normalising the records to git's form instead would mean rewriting nine statements to satisfy a
#: test rather than the other way round.
PKG_PREFIX = str(PKG.relative_to(REPO)) + "/"


def _full(recorded: str) -> pathlib.Path:
    return PKG / recorded


def _repo_rel(recorded: str) -> str:
    return PKG_PREFIX + recorded

#: A pin row in FORMAT_COVERAGE.md. The byte count is written with thin grouping — `558 866` — and
#: the path is the last backticked cell, so both are read rather than assumed.
DOC_PIN_ROW = re.compile(
    r"`(?P<sha>[0-9a-f]{64})`,\s*(?P<bytes>[\d  ]+?)\s*bytes,\s*(?P<pages>\d+)\s*pages,\s*"
    r"`(?P<path>fixtures/[^`]+\.pdf)`"
)


def _ungroup(text: str) -> int:
    """`'1 372 771'` → `1372771`. Prose groups digits; JSON does not."""
    return int(re.sub(r"[^\d]", "", text))


def discover_pins() -> dict[str, dict]:
    """`{repo-relative path: {sha256, bytes, pages?, sources[]}}`, from both statements of it."""
    pins: dict[str, dict] = {}

    def record(path: str, sha: str, size: int, pages, source: str):
        entry = pins.setdefault(path, {"sha256": sha, "bytes": size, "pages": pages,
                                       "sources": []})
        entry["sources"].append(source)
        # Two sources for one pin must agree. This is the cross-check `klv` makes possible.
        assert entry["sha256"] == sha, (
            f"{path}: {source} states SHA-256 {sha} and {entry['sources'][0]} states "
            f"{entry['sha256']}. One pin, two records, two answers"
        )
        assert entry["bytes"] == size, (
            f"{path}: {source} states {size} bytes and {entry['sources'][0]} states "
            f"{entry['bytes']}"
        )

    for pin_file in sorted(FIXTURES.rglob("*_pin.json")):
        data = json.loads(pin_file.read_text())
        rel_pin = str(pin_file.relative_to(REPO))
        for node in _walk(data):
            if not isinstance(node, dict):
                continue
            path, sha, size = node.get("local_path"), node.get("sha256"), node.get("bytes")
            if isinstance(path, str) and path.endswith(".pdf") and sha and size:
                record(path, sha, int(size), node.get("pages"), rel_pin)

    for m in DOC_PIN_ROW.finditer(DOC.read_text()):
        record(m.group("path"), m.group("sha"), _ungroup(m.group("bytes")),
               int(m.group("pages")), "FORMAT_COVERAGE.md")
    return pins


def _walk(node):
    """Every dict and list element in a pin record, at any depth."""
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


#: What a cite-not-carry entry must state. `must_not_appear_at` is the load-bearing one: it is the
#: `fixtures/*/spec/` path the document WOULD occupy, and it exists so the gate can check that it
#: does not.
CITED_REQUIRED = ("document", "edition", "classification", "why_not_carried", "must_not_appear_at")

#: And what it may not state. Each of these four measures a copy — which is the act this class
#: exists to decline — and `local_path` additionally is how `discover_pins` recognises a pin, so a
#: node carrying both keys would be two classes at once.
CITED_FORBIDDEN = ("sha256", "bytes", "pages", "local_path")

#: A cited entry names a path in the same shape a pin does, and only there: a citation is a
#: statement about a document that has a home in this layout and is deliberately not in it.
CITED_PATH = re.compile(r"fixtures/[^/]+/spec/[^/]+\.pdf\Z")


def citations_in(node, source: str):
    """Yield `(must_not_appear_at, entry)` for one node, validating it on the way through.

    Factored out of `discover_citations` so it can be run against a synthetic record. The class has
    zero members today and every assertion over it is therefore vacuous; a parser that CANNOT match
    and a parser that finds nothing to match look identical from a green run, and this is the seam
    that tells them apart.
    """
    if not isinstance(node, dict) or node.get("cite_not_carry") is not True:
        return
    missing = [k for k in CITED_REQUIRED if not node.get(k)]
    assert not missing, (
        f"{source}: a cite_not_carry entry is missing {missing}. A cited document is recorded by "
        "its IDENTITY, since it is recorded by nothing else — name the document, the edition, the "
        "classification line that put it in this class, why it is not carried, and the "
        "fixtures/*/spec/ path it would occupy if it were"
    )
    present = [k for k in CITED_FORBIDDEN if k in node]
    assert not present, (
        f"{source}: a cite_not_carry entry states {present}. Every one of those measures a COPY of "
        "the document, and this class exists precisely because this repository holds no copy it "
        "may redistribute. Either drop the key, or — if the document may in fact be carried — "
        "delete `cite_not_carry` and record it as an ordinary pin"
    )
    path = node["must_not_appear_at"]
    assert CITED_PATH.fullmatch(path), (
        f"{source}: must_not_appear_at is {path!r}, which is not a fixtures/*/spec/*.pdf path. It "
        "names the home the document would have had, so it has to be a path this gate could "
        "otherwise find a pin at"
    )
    yield path, dict(node, recorded_by=source)


def discover_citations() -> dict[str, dict]:
    """`{must_not_appear_at: entry}` for every cite-not-carry node in every pin record.

    One source, unlike the pin set, and the reason is structural rather than an omission:
    `DOC_PIN_ROW` matches on a SHA-256, a byte count, a page count and a path, which are the exact
    four things a cited entry does not have. The document parser cannot see one by construction,
    and that is also why the two classes cannot be confused for each other.
    """
    out: dict[str, dict] = {}
    for pin_file in sorted(FIXTURES.rglob("*_pin.json")):
        data = json.loads(pin_file.read_text())
        rel_pin = str(pin_file.relative_to(REPO))
        for node in _walk(data):
            for path, entry in citations_in(node, rel_pin):
                assert path not in out, (
                    f"{path} is declared cite-not-carry twice — by {out[path]['recorded_by']} and "
                    f"by {rel_pin}. One document, one record"
                )
                out[path] = entry
    return out


# ------------------------------------------------- the cited-but-unpublished class
#
# THE THIRD CLASS, AND IT IS COMPUTED WHERE THE OTHER TWO ARE DECLARED
# ---------------------------------------------------------------------
# A pin is declared by a record with a hash. A cite-not-carry entry is declared by a flag. This
# class is declared by NOTHING: a (document identifier, edition) pair is cited-but-unpublished
# when BOTH halves are found in the data, and the two halves live in different records written by
# different rounds for different reasons.
#
#   the citation     a QUOTATION in any pin record naming an identifier and an edition — found by
#                    reading the quotation, never by a list. The one member's strongest citation
#                    sits in `cat048_pin.json`, a record written before the cited document had a
#                    pin at all, which is exactly the independence that makes discovery worth
#                    doing rather than asserting.
#   the availability a dated check in the pin record FOR THAT IDENTIFIER, stating an edition and
#                    whether it is offered. Two machine-readable fields in a node that is
#                    otherwise prose.
#
# WHY COMPUTED RATHER THAN FLAGGED, which is the whole design and not a preference. A flag would
# let a round assert the class without doing the work: the state's entire content is "somebody
# looked for this document and did not find it", and a flag records that somebody SAID so. The
# conjunction records that somebody DID.

#: A citation: an identifier in parentheses followed by an edition. This is the form EUROCONTROL
#: reference lists use and the form both of the member's citations are quoted in.
CITATION = re.compile(r"\(([A-Z][A-Za-z0-9-]*-[A-Za-z0-9-]+)\)\s*Edition\s+(\d+\.\d+)")

#: THE DECLARED ROSTER, and it is the only hand-written thing in this class — deliberately, because
#: it is what the closure compares against. Discovery computes membership from the data; this says
#: what the data is expected to yield. A member appearing, disappearing or publishing all show up
#: as a disagreement between the two.
CITED_BUT_UNPUBLISHED = (("EUROCONTROL-SPEC-0149-2b", "1.30"),)


def _strings(node, path=""):
    """Every string value in a record, with the dotted path that reached it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def _pin_records() -> dict[str, dict]:
    return {str(f.relative_to(REPO)): json.loads(f.read_text())
            for f in sorted(FIXTURES.rglob("*_pin.json"))}


def cited_editions(records: dict[str, dict] | None = None) -> dict[tuple[str, str], list[str]]:
    """`{(identifier, edition): [where it is quoted]}` — FOUND, never told.

    Every string in every pin record is read, and any that quotes an identifier-and-edition is a
    citation. That deliberately includes a record's quotation of ANOTHER document's reference list,
    which is where the strongest evidence lives: `cat048_pin.json` quotes CAT048 Edition 1.32's
    §2.2 reference 5 naming Part 2b Edition 1.30, and it did so a round before Part 2b had a pin.
    """
    found: dict[tuple[str, str], list[str]] = {}
    for rel, data in (records or _pin_records()).items():
        for where, text in _strings(data):
            for match in CITATION.finditer(text):
                found.setdefault(match.groups(), []).append(f"{rel}:{where}")
    return found


def availability_checks(records: dict[str, dict] | None = None) -> dict[tuple[str, str], dict]:
    """`{(identifier, edition): entry}` for every dated availability check.

    An availability check is bound to the identifier of the record it lives in — a pin record is
    about one document, and a check inside it is a check on that document. `edition` and `offered`
    are read as DATA; every other field in the node is prose for a human and is not parsed.
    """
    out: dict[tuple[str, str], dict] = {}
    for rel, data in (records or _pin_records()).items():
        identifier = (data.get("source") or {}).get("document_identifier")
        for node in _walk(data):
            if not isinstance(node, dict) or "checked_on" not in node:
                continue
            assert identifier, (
                f"{rel} records a dated availability check and its source states no "
                "document_identifier, so the check cannot be bound to a document"
            )
            for field in ("edition", "offered", "result"):
                assert field in node, (
                    f"{rel}: an availability check is missing {field!r}. `edition` and `offered` "
                    "are what class membership is computed from and `result` is what a human "
                    "reads; a check with prose and no data is the state this class replaced"
                )
            assert isinstance(node["offered"], bool), (
                f"{rel}: availability_check.offered is {node['offered']!r}, not a boolean. "
                "'Offered' is the finding; a string here would make the class depend on parsing "
                "prose, which is what it exists to stop"
            )
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", node["checked_on"]), (
                f"{rel}: checked_on is {node['checked_on']!r}, not an ISO date. The date is the "
                "whole point of the entry — 'was not offered' and 'was not checked' are "
                "indistinguishable without it"
            )
            # THE DISJUNCTION, inside one node: the machine-readable fields and the prose that
            # states the same finding must agree, or the two halves of this record can drift —
            # and the data half is the one the class is computed from, so a drift would make the
            # gate right about a document the record describes differently.
            offered_words = "not offered" not in node["result"].lower()
            assert offered_words is node["offered"], (
                f"{rel}: availability_check.offered is {node['offered']!r} and the prose result "
                f"reads {node['result']!r}. One of them is wrong, and the class is computed from "
                "the field while a human reads the sentence"
            )
            assert f"Edition {node['edition']}" in node["result"], (
                f"{rel}: availability_check.edition is {node['edition']!r} and the prose result "
                f"does not mention 'Edition {node['edition']}'. The data field and the sentence a "
                "human reads are the same fact stated twice and must say the same thing"
            )
            key = (identifier, node["edition"])
            assert key not in out, f"{key} has two availability checks"
            out[key] = dict(node, recorded_by=rel)
    return out


def held_editions(records: dict[str, dict] | None = None) -> set[tuple[str, str]]:
    """The (identifier, edition) pairs this repository PINS. A document you hold needs no check."""
    held = set()
    for data in (records or _pin_records()).values():
        source = data.get("source") or {}
        if source.get("document_identifier") and source.get("edition"):
            held.add((source["document_identifier"], source["edition"]))
    return held


def classify(records: dict[str, dict] | None = None) -> dict[str, dict]:
    """Every cited (identifier, edition) sorted into exactly one of three buckets.

    HELD       cited and pinned here. Needs no availability check: the copy is the answer.
    MEMBER     cited, not held, and a dated check found it NOT offered.
    CANDIDATE  cited, not held, and no dated check — availability UNKNOWN.

    **THE RULING ON THE EMPTY-ADJACENT QUESTION, and it is the reason CANDIDATE exists at all.**
    A second citation to an unoffered edition does NOT join this class automatically. Joining
    requires the dated availability check, and the reason is the mistake that produced the class:
    CAT034 Phase 1 read a citation and concluded the pinned edition "is not the newest published",
    which was false — a citation establishes that an edition EXISTS and says nothing whatever about
    whether anyone offers it. So a citation alone yields a CANDIDATE, which is a question, and only
    a check turns it into a member, which is a finding.

    And a candidate is not permitted to sit quietly: the gate requires the candidate set to be
    empty, so a new citation to an edition nobody has looked for FAILS until somebody looks. The
    alternative — candidates accumulating silently — would make this class the place unanswered
    questions go to be forgotten, which is the opposite of why it was built.
    """
    records = records or _pin_records()
    citations = cited_editions(records)
    checks = availability_checks(records)
    held = held_editions(records)
    out = {"held": {}, "member": {}, "candidate": {}}
    for key, sites in sorted(citations.items()):
        if key in held:
            out["held"][key] = {"cited_at": sites}
        elif key in checks and not checks[key]["offered"]:
            out["member"][key] = {"cited_at": sites, "check": checks[key]}
        elif key in checks:
            out["held"][key] = {"cited_at": sites, "check": checks[key]}
        else:
            out["candidate"][key] = {"cited_at": sites}
    return out


CLASSIFIED = classify()
MEMBERS = CLASSIFIED["member"]


def spec_pdfs_on_disk() -> set[str]:
    """PDFs sitting DIRECTLY in a `fixtures/*/spec/` directory — not in a subdirectory of one.

    Non-recursive on purpose: the FIVE `spec/history/` directories hold 33 edition PDFs between
    them and none is a pin, so a recursive glob would sweep them into the set this module says must
    equal the pins.

    THAT SENTENCE READ "the two ... hold 25" UNTIL 2026-08-26 AND WAS STALE BY THREE DIRECTORIES,
    corrected by the KLV park 13 round, which added the fifth. It had drifted as cat023's and
    cat062's lineages landed and nothing sent anybody back to a docstring. The load-bearing half -
    that the glob is non-recursive and that nothing under `history/` is a pin - was true throughout,
    so the FUNCTION never stopped working; only the arithmetic describing it went wrong. Derived by:
      ls -d packages/cdm/synapse_cdm/fixtures/*/spec/history | wc -l
      ls packages/cdm/synapse_cdm/fixtures/*/spec/history/*.pdf | wc -l
    """
    out = set()
    for spec in sorted(FIXTURES.glob("*/spec")):
        for pdf in sorted(spec.glob("*.pdf")):
            out.add(str(pdf.relative_to(PKG)))
    return out


def tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, f"git ls-files failed: {out.stderr}"
    return set(out.stdout.splitlines())


PINS = discover_pins()
CITED = discover_citations()
DISK = spec_pdfs_on_disk()
TRACKED = tracked_files()


def test_the_pin_set_was_actually_discovered():
    """A gate that discovered no pins would pass every check below and prove nothing.

    The floor is deliberately a hard number and not `>= 1`: this repository has pinned standards for
    six adapters, and a discovery that found one of them is a broken parser rather than a small
    tree. The floor moves when a pin lands — 9 to 10 and four homes to five when STANAG 5527's
    covering document landed in `fixtures/fft/spec/`, then 10 to 11 and five homes to six when
    CAT034 Edition 1.29 landed in `fixtures/cat034/spec/` — and moving it is the deliberate act,
    because a floor left behind is a gate reporting a clean run over a smaller tree than the one in
    front of it. That is the same failure this module was written for, one level up.

    11 to 13 on 2026-08-26, when MISB ST 0601.19 and ST 0102.12 landed in `fixtures/klv/spec/`. The
    homes floor did NOT move with it: `fixtures/klv/spec/` was already a home, holding the wrapper
    and the profile, so two pins arrived into an eighth home rather than a ninth. A floor raised on
    both numbers because two files appeared would have been a guess that happened to be half right.

    13 to 14 later the same day, when MISB ST 0601.14 landed in the same directory and closed the
    KLV section's park 1. The homes floor stays at eight for the same reason it did not move for
    the previous two: it is the ninth pin to arrive into an existing home.

    14 to 19 on 2026-08-26, and FOUR OF THOSE FIVE WERE A LAG RATHER THAN AN ARRIVAL — which is the
    failure this docstring predicts about itself and had not, until now, been made to admit. Only
    one pin landed in the round that moved this number: MISB EG 0601.1, which closed park 13. The
    other four had been on disk and in the records for one or more rounds with the floor left at 14,
    so this gate has been "reporting a clean run over a smaller tree than the one in front of it"
    by four documents. It was not caught by this assertion, because a floor cannot catch its own
    slack; it was caught by re-deriving the number while moving it. THE REASON IT COST NOTHING is
    that the floor is the weaker of two gates on the same fact -
    `test_the_derived_pin_set_equals_the_pdfs_in_spec_directories` asserts EQUALITY in both
    directions and would have failed the moment a pin went unrecorded, which is precisely what it
    did when EG 0601.1 landed before its record did. The floor is kept anyway, and kept exact,
    because the closure test skips on a tree holding no documents and this one does not.
    """
    assert len(PINS) >= 19, (
        f"discovered only {len(PINS)} pins: {sorted(PINS)}. Both statements of a pin are parsed — "
        "the *_pin.json records and FORMAT_COVERAGE.md's pin rows — so a low count means one of the "
        "two parsers has stopped matching"
    )
    homes = {p.rsplit("/", 1)[0] for p in PINS}
    assert len(homes) >= 8, f"pins found in only {sorted(homes)}"
    # And both sources are load-bearing, which is why neither can be dropped.
    from_doc = {p for p, v in PINS.items() if "FORMAT_COVERAGE.md" in v["sources"]}
    from_json = {p for p, v in PINS.items() if any(s.endswith("_pin.json") for s in v["sources"])}
    assert from_doc - from_json, (
        "every pin the document states is also in a pin record, so the document parser is not "
        "load-bearing any more — gmti's and nits' pins are stated ONLY in the document, and if that "
        "changed the reason for parsing it changed too"
    )
    assert from_json - from_doc, (
        "every pin a record states is also in the document, so the record parser is not "
        "load-bearing — cat048's local path is stated ONLY in its pin record"
    )


def test_the_derived_pin_set_equals_the_pdfs_in_spec_directories():
    """THE CLOSURE PROPERTY. Equality in both directions, which is what the enumeration lost.

    The push gate that named eight pins while the tree held nine failed in exactly one direction: a
    PDF present and unlisted. An enumeration cannot catch that, because it is the enumeration that
    is wrong. Comparing the derived set against the disk catches it without anybody counting.

    SKIPS ON A TREE HOLDING NO DOCUMENTS AT ALL, and only then — see the fresh-clone boundary in
    this module's docstring. Both halves are about bytes, so a clone has nothing to compare; a tree
    holding SOME documents is a maintainer's and both directions apply to it in full, because
    "recorded and not on disk" is the moved-file defect and a per-pin skip would retire it.
    """
    if not DISK:
        pytest.skip(f"no specification document is in this working tree at all, so the {len(PINS)} "
                    "recorded pins cannot be compared against a disk (a fresh clone has the "
                    "record, not the PDF). The equality runs as soon as one document is held")
    missing_from_disk = sorted(set(PINS) - DISK)
    unrecorded_on_disk = sorted(DISK - set(PINS))
    assert not missing_from_disk, (
        f"recorded as a pin and not on disk: {missing_from_disk}. Either the file was moved — the "
        "80b38d1 failure — or a pin record names a path that never existed"
    )
    assert not unrecorded_on_disk, (
        f"on disk in a spec/ directory and recorded as a pin NOWHERE: {unrecorded_on_disk}.\n"
        "This is the eight-versus-nine drift, caught from the disk side. Either add it to a pin "
        "record and to FORMAT_COVERAGE.md's pin table, or move it out of spec/ — a PDF in spec/ "
        "that no record names is a document nobody can identify"
    )


def test_the_cited_class_is_disjoint_from_the_pin_set_in_both_directions():
    """A document is carried or it is cited. Never both, and the two messages are not the same.

    The property is one intersection and is symmetric; the REPAIRS are not, which is why it is
    asserted twice. A path that gained a pin record while a citation stood means somebody landed
    bytes the citation says may not be here — the citation is the thing to check. A path that
    gained a citation while a pin record stood means somebody declared an already-carried document
    uncarriable and left the copy on disk — the copy is the thing to remove.

    Because the two assertions are the same set intersection, only the first can fire on a given
    run: the mutation log for this round records that the second was demonstrated with the first
    neutralised, which is the honest way to check a branch that a passing sibling shadows.

    Empty today, because the cited class is empty today. `citations_in` is exercised against a
    synthetic record below, which is what stops that emptiness from being a broken parser.
    """
    both = sorted(set(CITED) & set(PINS))
    assert not both, (
        f"recorded as a PIN and declared cite-not-carry: {both}. A pin record states a SHA-256 for "
        "a copy in this tree and a citation states that no copy may be in this tree. Both cannot "
        f"be true — check {[CITED[p]['recorded_by'] for p in both]} against the pin record"
    )
    # The same fact from the other side, because the repair differs by which record moved last.
    also_pinned = sorted(p for p in PINS if p in CITED)
    assert not also_pinned, (
        f"declared cite-not-carry and ALSO recorded as a pin: {also_pinned}. If the document may "
        "not be carried, delete the pin record and remove the copy from the working tree; if it "
        "may, delete the citation. Leaving both makes the gate assert a contradiction quietly"
    )


@pytest.mark.parametrize("path", sorted(CITED) or [None],
                         ids=lambda p: (p or "none-cited").rsplit("/", 1)[-1])
def test_no_cited_document_has_grown_bytes_anywhere_under_fixtures(path):
    """THE TEETH. A cited entry that acquires a file is the failure this class exists to catch.

    Checked two ways, because the obvious one is too narrow. `must_not_appear_at` is the home the
    document would have had, and a copy that arrives by accident is at least as likely to land in a
    `spec/history/` subdirectory or beside a fixture as at exactly that path — so the basename is
    swept across the whole fixture tree as well. Either hit fails, and the repair is the same one:
    the file goes, not the citation.
    """
    if path is None:
        pytest.skip("the cited class is empty — Branch U's shape, and a legal state. The parser "
                    "that would populate it is exercised by test_the_citation_parser_is_not_vacuous")
    entry = CITED[path]
    full = _full(path)
    assert not full.exists(), (
        f"{path} EXISTS. It is declared cite-not-carry by {entry['recorded_by']} — "
        f"{entry['document']}, {entry['edition']}, {entry['classification']} — which says its bytes "
        "may not be in this repository at all, tracked or untracked. Delete the file. If the "
        "classification was wrong, the repair is to correct the citation and re-record the document "
        "as an ordinary pin, in that order"
    )
    name = path.rsplit("/", 1)[-1]
    elsewhere = sorted(str(q.relative_to(PKG)) for q in FIXTURES.rglob(name))
    assert not elsewhere, (
        f"{name} is declared cite-not-carry and a file of that name is under fixtures/ at "
        f"{elsewhere}. A subdirectory is not a loophole — {entry['document']} may not be in this "
        "tree under any path. Delete it"
    )


def test_the_cited_but_unpublished_class_matches_its_declared_roster():
    """CLOSURE, BOTH DIRECTIONS, on a class whose membership is COMPUTED.

    The roster is the only hand-written thing here and it exists to be disagreed with. Discovery
    reads the citations out of quotations and the availability out of dated checks, and the two
    sets must be equal:

    * **a pair discovered and not declared** is a document that entered this state and nobody
      noticed — the direction that catches the real mistake;
    * **a pair declared and not discovered** is a roster entry whose evidence has gone: either the
      citation was deleted, or the availability check was, or the edition PUBLISHED and is now
      held. All three need a human, and all three are the same failure from here.
    """
    discovered = set(MEMBERS)
    declared = set(CITED_BUT_UNPUBLISHED)
    assert discovered == declared, (
        f"the cited-but-unpublished class and its roster disagree.\n"
        f"  discovered and not declared: {sorted(discovered - declared)}\n"
        f"  declared and not discovered: {sorted(declared - discovered)}\n"
        "Membership is computed from two halves — a citation quoted in some pin record, and a "
        "dated availability check in the pin record for that identifier finding the edition not "
        "offered. A pair leaving this set is an EVENT: most likely the edition published, which "
        "is the reopen firing."
    )
    assert declared, (
        "the roster is empty, so every assertion over this class is vacuous. That is a legal "
        "state — it is `cite_not_carry`'s state — but it has to be reached deliberately, and the "
        "parser is exercised against synthetic records either way"
    )


@pytest.mark.parametrize("member", CITED_BUT_UNPUBLISHED, ids=lambda m: f"{m[0]}-ed{m[1]}")
def test_every_member_is_still_discoverable_as_cited_by_a_sibling_record(member):
    """Direction two, per member, with the independence the class rests on made explicit.

    A member's citation is what establishes the edition EXISTS. One citation could be a stale
    reference list; the member here is cited by two specifications three years apart, and the
    quotations are recorded in two different pin records — including one written before the cited
    document had a pin at all. So the check is not just "a citation exists" but "the citation is
    still found in more than one record", because a single record citing itself would be this
    repository believing its own summary.
    """
    identifier, edition = member
    sites = cited_editions().get(member)
    assert sites, (
        f"{identifier} Edition {edition} is on the roster and no pin record quotes it any more. "
        "The citation is half the class; without it the entry asserts an edition exists on this "
        "repository's own say-so"
    )
    records = {site.split(":", 1)[0] for site in sites}
    assert len(records) >= 2, (
        f"{identifier} Edition {edition} is quoted only in {sorted(records)}. The independence of "
        "the citations is what makes the existence claim stronger than a recollection — see the "
        "record's own why_two_citations_matter"
    )
    check = availability_checks()[member]
    assert check["offered"] is False
    assert check["checked_on"], "a member with no check date is not a member of this class"


@pytest.mark.parametrize("member", CITED_BUT_UNPUBLISHED, ids=lambda m: f"{m[0]}-ed{m[1]}")
def test_a_member_that_publishes_fails_the_gate(member):
    """THE REOPEN, and it has to be a failure someone SEES rather than a state that changes.

    A document leaves this class by being published, and the way that shows up here is that the
    edition becomes the pinned one for its identifier. When it does, `classify()` sorts the pair
    into HELD instead of MEMBER, the roster no longer matches, and the test above fails — loudly,
    naming the pair. This test is the same event caught one step earlier and with the right words
    on it, so the failure a reader meets says "the reopen fired" rather than "a set disagreed".

    The repair is not to edit the roster. It is: pin the edition, move the previous one into the
    lineage, and remove the entry — in that order, because the entry is what records why the
    document was absent and it should be the last thing to go.
    """
    identifier, edition = member
    held = held_editions()
    assert (identifier, edition) not in held, (
        f"THE REOPEN HAS FIRED: {identifier} Edition {edition} is now PINNED, so it is no longer "
        "cited-but-unpublished. This is the outcome the class was built to make visible. Pin the "
        "edition, move the superseded one into the lineage, drop the entry from "
        "CITED_BUT_UNPUBLISHED, and rewrite the availability record as history rather than as a "
        "current finding."
    )
    pinned_editions = {i: e for i, e in held if i == identifier}
    assert pinned_editions.get(identifier) != edition


def test_no_citation_is_left_as_an_unanswered_candidate():
    """THE RULING, asserted: a citation alone does not join, and it does not sit quietly either.

    A cited edition with no dated availability check is a CANDIDATE — the class's own name for a
    question. It is not a member, because a citation says an edition exists and says nothing about
    whether anybody offers it; that inference is exactly the one CAT034 Phase 1 made and got
    backwards. And it may not accumulate, because a class that silently collects unanswered
    questions is where they go to be forgotten. So the candidate set must be EMPTY: a new citation
    fails this test until somebody performs the check that makes it a member — or pins the
    document, which makes it held.
    """
    candidates = CLASSIFIED["candidate"]
    assert not candidates, (
        "these editions are cited in a pin record and nobody has checked whether they are "
        "offered:\n  " + "\n  ".join(
            f"{i} Edition {e} — quoted at {', '.join(v['cited_at'])}"
            for (i, e), v in sorted(candidates.items())) +
        "\nA citation establishes that the edition EXISTS. It establishes nothing about "
        "availability, so it does not make the edition cited-but-unpublished on its own. Either "
        "check the publisher's page and record the finding with its date — which makes it a "
        "member — or pin the document, which makes it held."
    )


def test_the_cited_but_unpublished_parser_is_not_vacuous():
    """One member is not enough to prove the machine works, so it is run against synthetics.

    Four records, exercising every branch the class has, in memory with nothing written to disk:
    a well-formed member, a candidate, a held pair, and the REOPEN — the same member with its
    availability flipped to offered, which must stop being a member.
    """
    def record(identifier, edition, *, cite=True, check=None, pinned=None):
        data = {"source": {"document_identifier": identifier, "edition": pinned or "1.00"}}
        if cite:
            data["boundary"] = {"quoted": f"A sibling spec ({identifier}) Edition {edition}."}
        if check is not None:
            data["note"] = {"availability_check": {
                "edition": edition, "offered": check, "checked_on": "2026-01-01",
                "result": f"Edition {edition} is {'offered' if check else 'not offered'}."}}
        return data

    key = ("SYNTHETIC-SPEC-1", "9.99")
    # 1. the member: cited, checked, not offered.
    found = classify({"synthetic.json": record(*key, check=False)})
    assert list(found["member"]) == [key], found
    assert not found["candidate"] and not found["held"]

    # 2. the candidate: cited, never checked. The RULING — it must not become a member.
    found = classify({"synthetic.json": record(*key)})
    assert list(found["candidate"]) == [key], found
    assert not found["member"], (
        "a citation with no availability check produced a MEMBER. That is the Phase 1 inference "
        "the class exists to refuse: a citation says the edition exists, not that it is unoffered"
    )

    # 3. the held pair: cited and pinned. Needs no check; the copy is the answer.
    found = classify({"synthetic.json": record(*key, pinned=key[1])})
    assert list(found["held"]) == [key] and not found["member"] and not found["candidate"]

    # 4. THE REOPEN: the same member, offered. It must leave the class.
    found = classify({"synthetic.json": record(*key, check=True)})
    assert not found["member"], (
        "an edition the publisher OFFERS is still classified cited-but-unpublished. The whole "
        "content of this class is that somebody looked and did not find it"
    )
    assert list(found["held"]) == [key], found

    # And the citation reader itself finds a quotation it was never told about.
    assert cited_editions({"synthetic.json": record(*key)}) == {key: ["synthetic.json:boundary.quoted"]}
    assert cited_editions({"synthetic.json": record(*key, cite=False)}) == {}


def test_every_prose_site_that_names_the_class_points_at_the_gate_that_checks_it():
    """The class is a registry, not a rewrite — so the prose keeps its words and gains a pointer.

    A named state with no gate behind it is what "cited-but-unpublished" was for one round, and a
    reader meeting the phrase had no way to find out whether anything checked it. Both sites that
    name the class now say where it is computed. The `.md` sites are swept and `MIGRATIONS.md` is
    not: it records what a round DID, in the past tense, and pointing a history entry at a
    current gate would date it wrongly.
    """
    sites = ("FORMAT_COVERAGE.md", "fixtures/cat034/README.md")
    for rel in sites:
        text = (PKG / rel).read_text()
        flat = " ".join(text.split())
        low = flat.lower()
        assert "cited-but-unpublished" in low, (
            f"{rel} no longer names the class. If the name changed, this list and the class's own "
            "docstring change with it"
        )
        # SCOPED TO THE SENTENCE THAT NAMES THE CLASS, not to the file. Both of these documents
        # mention this module elsewhere — `FORMAT_COVERAGE.md` six times, the README twice — so a
        # whole-file check is a disjunction that passes while the pointer beside the class name is
        # gone. That is the same defect a mutation found in the deploy-workflow assertion one round
        # ago, and it recurred here, which is why the window is now part of the rule rather than a
        # thing to remember.
        at = low.index("cited-but-unpublished")
        window = flat[at:at + 600]
        assert "tests/test_cdm_pins.py" in window, (
            f"{rel} names the cited-but-unpublished class and does not say WHERE IT IS CHECKED "
            f"within 600 characters of naming it. The pointer has to be beside the name: this "
            "class exists because the state was a phrase with no gate behind it for a round, and "
            "a reader meeting the phrase has to be able to find the gate without grepping.\n"
            f"  window: {window[:200]!r}"
        )


def test_the_citation_parser_is_not_vacuous():
    """The cited class has zero members, so this is the check that keeps the other two honest.

    Every assertion above is vacuously true today and would stay vacuously true if `citations_in`
    stopped matching altogether — the same failure one level up from the eight-versus-nine drift,
    where a gate reports clean over a smaller tree than the one in front of it. So the parser is
    run against a synthetic record here: it must FIND a well-formed citation, and it must REFUSE
    each of the three malformations, in-memory and with nothing written to disk.
    """
    good = {
        "cite_not_carry": True,
        "document": "A NATO standardization document",
        "edition": "Edition B",
        "classification": "NATO RESTRICTED, per the NSDD record",
        "why_not_carried": "the bytes may not be redistributed from a public repository",
        "must_not_appear_at": "fixtures/fft/spec/a-document-not-carried.pdf",
    }
    found = dict(citations_in(good, "synthetic"))
    assert list(found) == ["fixtures/fft/spec/a-document-not-carried.pdf"], (
        f"the citation parser did not find a well-formed citation: {found}. Every assertion over "
        "the cited class is vacuous while this is true, which is exactly what it would look like "
        "if the class were simply empty"
    )
    assert found["fixtures/fft/spec/a-document-not-carried.pdf"]["recorded_by"] == "synthetic"

    # A node that does not opt in is not a citation, so the flag is what selects, not the shape.
    assert list(citations_in(dict(good, cite_not_carry=False), "synthetic")) == []
    assert list(citations_in({"document": "x"}, "synthetic")) == []
    assert list(citations_in("not a dict", "synthetic")) == []

    for key in CITED_REQUIRED:
        with pytest.raises(AssertionError, match="is missing"):
            list(citations_in({k: v for k, v in good.items() if k != key}, "synthetic"))
    for key in CITED_FORBIDDEN:
        with pytest.raises(AssertionError, match="measures a COPY"):
            list(citations_in(dict(good, **{key: "anything"}), "synthetic"))
    for bad in ("a-document-not-carried.pdf", "fixtures/fft/a-document.pdf",
                "fixtures/fft/spec/history/a-document.pdf", "fixtures/fft/spec/a-document.txt"):
        with pytest.raises(AssertionError, match="must_not_appear_at"):
            list(citations_in(dict(good, must_not_appear_at=bad), "synthetic"))


#: The pin records that state how a page count was produced. Derived rather than typed by the
#: closure test below, which is what stops a fifth record growing one nothing reads.
#:
#: `cat062_pin.json` and `cat023_pin.json` joined in the CAT062/CAT023 specification round, and
#: they are the first two records whose measurements make the ruling look obvious rather than
#: merely correct: the retired raw-object scan reports 423 pages for a 146-page document and 60
#: for a 31-page one. `cat034_pin.json`'s largest previous disagreement was 41 against 43.
PAGE_COUNT_METHOD_RECORDS = ("fixtures/cat023/spec/cat023_pin.json",
                             "fixtures/cat034/spec/cat034_pin.json",
                             "fixtures/cat062/spec/cat062_pin.json",
                             "fixtures/fft/spec/fft_pin.json",
                             "fixtures/klv/spec/klv_pin.json")

#: The ruled method, verbatim. Stated once here and required of every record — see
#: FORMAT_COVERAGE.md, "The page count, ruled from what a reader does with the number".
RULED_METHOD = ("The page objects REACHABLE FROM THE CATALOG'S /Pages TREE, walked in /Kids order.")

#: The phrase the RETIRED method is defined by. No record's `how` may contain it any more; every
#: record that changed must still MENTION it, in the field that says what it used to say — those
#: are opposite requirements on purpose, and together they are what preserves the history without
#: leaving a false description standing.
RETIRED_METHOD_PHRASE = "occurrences of /Type /Page across raw objects"


def _method_nodes() -> dict[str, dict]:
    return {rel: json.loads((PKG / rel).read_text())["page_count_method"]
            for rel in PAGE_COUNT_METHOD_RECORDS}


def test_every_page_count_method_record_states_the_ruled_method():
    """THE DISJUNCTION, on a fact stated three times, and it disagreed with itself for nine
    documents.

    `klv_pin.json` and `fft_pin.json` each used to open "Counted from the PDF's own page tree" and
    then define a raw-object scan of `/Type /Page` — the page tree and a raw-object scan are two
    different methods, so the sentence was self-contradictory from the day it was written. Nothing
    noticed, because the two agree on any file with no orphaned page objects and no incremental
    update, and no such file was pinned until CAT034.
    """
    for rel, node in _method_nodes().items():
        assert node["how"] == RULED_METHOD, (
            f"{rel}'s page_count_method.how is not the ruled method.\n  is:     {node['how']}\n"
            f"  ruled:  {RULED_METHOD}\n"
            "A page count's job is to let someone holding a copy check they hold the same "
            "document, and what they do is open it — so the count is the number of pages the "
            "document HAS, which is the page tree."
        )
        assert RETIRED_METHOD_PHRASE not in node["how"], (
            f"{rel} defines the retired raw-object method in its `how` field again"
        )
        assert "FORMAT_COVERAGE.md" in node.get("ruling", ""), (
            f"{rel}'s method record does not cite the ruling. A method stated three times with "
            "the reasoning nowhere is three assertions rather than one decision"
        )


def test_the_two_records_that_changed_still_say_what_they_used_to_say():
    """A correction that erases what it corrected is a correction nobody can audit.

    The two records whose METHOD changed must still name the retired one — not in `how`, which is
    the live description, but in the field that records the change. `cat034_pin.json` is exempt
    from this one: it was written under the ruled method and had nothing to retract.
    """
    for rel in ("fixtures/fft/spec/fft_pin.json", "fixtures/klv/spec/klv_pin.json"):
        node = _method_nodes()[rel]
        history = node.get("what_this_record_used_to_say_and_why_it_changed", "")
        assert RETIRED_METHOD_PHRASE in history, (
            f"{rel} no longer records the method it used to state. The values did not move, so "
            "this field is the only evidence that anything about them changed"
        )
        assert "did not move" in history.lower() or "DID NOT MOVE" in history, (
            f"{rel} does not say whether its COUNTS moved. They did not, and a correction that "
            "leaves that ambiguous reads as a re-measurement"
        )


def test_the_three_corrected_cat048_history_counts_are_recorded_as_corrections():
    """The one place the ruling changed a number, and it has to say so rather than just differ.

    Editions 1.28 and 1.29 move 58 → 56 and edition 1.30 moves 59 → 57. Each entry carries the
    old value, the new one and the CAUSE, and the summary node carries the corroboration — because
    "the number is different now" is not a record of anything.
    """
    pin = json.loads((PKG / "fixtures/cat048/spec/cat048_pin.json").read_text())
    history = pin["edition_history"]
    corrected = {"1.28": 56, "1.29": 56, "1.30": 57}
    by_edition = {e["edition"]: e for e in history["files"]}
    for edition, pages in corrected.items():
        entry = by_edition[edition]
        assert entry["pages"] == pages, (
            f"CAT048 edition {edition} records {entry['pages']} pages; the ruled method gives "
            f"{pages}"
        )
        note = entry.get("pages_corrected_2026_08_25", "")
        assert note.startswith("CORRECTION:"), (
            f"edition {edition}'s new page count is not marked as a correction"
        )
        assert "/Count" in note, (
            f"edition {edition}'s correction does not cite the file's own declared /Count, which "
            "is the witness that makes it a correction rather than a preference"
        )
    summary = history["page_count_correction_2026_08_25"]
    assert "METHOD RULING" in summary["why"], summary["why"]
    assert "%%EOF" in summary["how_the_new_numbers_were_corroborated"]
    # THE ABSENCE: the pin itself did not move, and nineteen of the twenty-two did not either.
    assert pin["source"]["pages"] == 64, "the CAT048 PIN moved; only the lineage was corrected"
    unchanged = [e for e in history["files"] if e["edition"] not in corrected]
    assert len(unchanged) == 19, f"{len(unchanged)} unchanged entries, expected 19"
    assert all("pages_corrected_2026_08_25" not in e for e in unchanged), (
        "an entry that did not move is marked as corrected"
    )


def test_the_page_count_method_closure_holds_in_both_directions():
    """A pin record that grows a method node nothing reads is the failure this catches.

    Derived rather than trusted: every `*_pin.json` under `fixtures/` is opened, and any that
    carries a `page_count_method` and is not on the list fails. The pin gate's own property,
    applied to a node inside the records rather than to the records themselves.
    """
    carriers = sorted(str(p.relative_to(PKG)) for p in FIXTURES.rglob("*_pin.json")
                      if "page_count_method" in json.loads(p.read_text()))
    assert carriers == sorted(PAGE_COUNT_METHOD_RECORDS), (
        f"the page-count-method record list and the tree disagree:\n"
        f"  only in the list: {sorted(set(PAGE_COUNT_METHOD_RECORDS) - set(carriers))}\n"
        f"  only in the tree: {sorted(set(carriers) - set(PAGE_COUNT_METHOD_RECORDS))}\n"
        "A new pin that records how it counted pages joins the list and passes the agreement "
        "check; one that stops recording it leaves deliberately."
    )
    assert len(carriers) >= 3, (
        "fewer than three records state the method, so there is no disjunction left to check"
    )


@pytest.mark.parametrize("path", sorted(PINS), ids=lambda p: p.rsplit("/", 1)[-1])
def test_every_pin_is_present_intact_and_untracked(path):
    """Present, hashing to what the record says, and out of the index. All three, per pin."""
    assert _repo_rel(path) not in TRACKED, (
        f"{path} is TRACKED. Every pinned standard in this repository stays in the working tree and "
        "out of the index — the pin is the artefact, and these are other people's documents on "
        "other people's terms"
    )
    full = _full(path)
    if not full.exists():
        pytest.skip(f"{path} is not in this working tree (a fresh clone has the record, not the PDF)")
    entry = PINS[path]
    assert full.stat().st_size == entry["bytes"], (
        f"{path} is {full.stat().st_size} bytes and its record says {entry['bytes']}"
    )
    got = hashlib.sha256(full.read_bytes()).hexdigest()
    assert got == entry["sha256"], (
        f"{path} hashes to {got} and its record says {entry['sha256']} — this is a different copy "
        f"of the document, whatever its filename says. Recorded by: {entry['sources']}"
    )


def test_gitignore_refuses_a_specification_document_before_the_gate_has_to():
    """The MECHANISM behind the gate below, and the two now fail in the same direction.

    `test_no_pdf_is_tracked_anywhere_in_the_repository` is a good check that fires LATE: it runs
    at suite time, after `git add -A` has already staged 47 held documents, and only a suite run
    or a careful reading of `git status` stands between that and a commit. The pre-publication
    audit found the invariant resting on exactly that, and recorded that the near-miss had
    happened twice. So `.gitignore` now refuses the staging itself.

    Checked through `git check-ignore` rather than by grepping the file, because the question is
    whether git IGNORES the path — which is what a rule has to achieve — and a rule can be
    present and shadowed by a later negation. The positive control matters as much: the pin
    RECORDS and the generators live in the same directories and must still stage, so this asserts
    both directions and a `spec/`-wide rule would fail it.

    THIS CHECK DOES NOT SKIP, on any tree, and the fresh-clone boundary in this module's docstring
    says why: its subject is the ignore rules, and a clone has those in full. It used to demand
    documents on disk and fail an outsider for not having any — asking the disk for paths when the
    pin records state fourteen of them, none of which has to exist for `--no-index` to rule on it.
    """
    import subprocess
    def ignored(rel: str) -> bool:
        # `--no-index` is load-bearing and a MUTATION is what found it. Without it, git does not
        # apply ignore rules to already-TRACKED files and `check-ignore` reports them unignored
        # whatever the patterns say — so the positive control below could never fire, and a rule
        # widened to `fixtures/*/spec/` (which would hide the pin records) passed. `--no-index`
        # asks what the PATTERNS say, which is the question a rule has to answer.
        return subprocess.run(["git", "check-ignore", "-q", "--no-index", rel],
                              cwd=REPO).returncode == 0

    # Every document this repository RECORDS, plus every one it happens to hold. Real paths in
    # both cases — nothing synthetic — but the record is the half that makes this check work for
    # a reader who has no PDFs, and that is the ordinary case: `--no-index` asks the PATTERNS
    # about a path, so it answers identically whether or not the file is there. Fourteen paths on
    # a fresh clone, forty-seven here, and the held half is what covers the `spec/history/` lineages
    # that no pin record names.
    # PINS is keyed relative to the PACKAGE and `check-ignore` wants repo-relative, so the prefix
    # is DERIVED. Typing it got it wrong first time — `packages/cdm/` instead of
    # `packages/cdm/synapse_cdm/` — and every assertion still passed, because `*.pdf` is ignored
    # at any depth and a wrong path is ignored just as convincingly as a right one. The
    # spec-directory check below is what makes a wrong prefix fail instead of pass.
    #
    # THE TWO COUNTS IN THE PARAGRAPH ABOVE ARE NARRATIVE AND THEY HAVE MOVED, which is worth a
    # line rather than a silent edit: the recorded set is 14 on a fresh clone and the held set is
    # 47 in this tree, not eleven and thirty-six. Neither number is asserted here — the floor
    # below is — and both drifted because pins land in this repository without anybody being sent
    # back to a docstring. The same drift, in a file that insists its numbers are DERIVED, is
    # recorded as a finding in `fixtures/klv/spec/klv_pin.json` under
    # `not_committed.a_derived_count_in_gitignore_had_gone_stale_and_is_corrected`.
    package = PKG.relative_to(REPO)
    recorded = {str(package / path) for path in PINS}
    held = {str(p.relative_to(REPO)) for p in FIXTURES.rglob("*.pdf")}
    documents = sorted(recorded | held)
    assert documents, (
        "neither a pin record nor the disk yields a single specification document, so this check "
        "is vacuous. The pin records are tracked and a clone has all fourteen, so an empty set here "
        "means discovery is broken rather than that the tree is clean — see "
        "test_the_pin_set_was_actually_discovered"
    )
    assert len(recorded) >= 14, (
        f"only {len(recorded)} recorded pin path(s) reached this check. It is keyed on the record "
        "precisely so that a fresh clone checks fourteen paths instead of none"
    )
    # THE PREFIX IS CHECKED, on a tracked directory, because an unignored PDF and a nonexistent
    # one are indistinguishable to `check-ignore` — both come back ignored. Every pin sits beside
    # its `*_pin.json` in a `spec/` directory, and those directories ARE tracked, so their
    # presence is decidable on a fresh clone and a mis-derived prefix fails here rather than
    # sailing through as a green check over fourteen paths that do not exist.
    homeless = sorted(d for d in recorded if not (REPO / d).parent.is_dir())
    assert not homeless, (
        f"{len(homeless)} recorded pin path(s) name a directory that is not in this tree: "
        f"{homeless[:3]}. Every pin lives in a `spec/` directory that also holds its pin record, "
        "and those are tracked — so this is a mis-derived prefix, and every check-ignore verdict "
        "above it was answered about a path nothing will ever be written to"
    )
    not_ignored = [d for d in documents if not ignored(d)]
    assert not not_ignored, (
        f"{len(not_ignored)} specification document(s) are NOT ignored by git: {not_ignored[:3]}. "
        "`git add -A` would stage them, and the only thing left between that and a commit is a "
        "suite run. Restore the `*.pdf` rule in .gitignore"
    )
    # An archive, because that is how a lineage arrives — cat048_pin.json records `bundle_url`
    # pointing at EUROCONTROL's `archive_download/all`.
    assert ignored("packages/cdm/synapse_cdm/fixtures/klv/spec/anything.zip")
    # THE POSITIVE CONTROL, both directions. These must still stage.
    for keep in ("packages/cdm/synapse_cdm/fixtures/klv/spec/klv_pin.json",
                 "packages/cdm/synapse_cdm/fixtures/cat034/spec/build_fixtures.py"):
        assert not ignored(keep), (
            f"{keep} is ignored. The pin record and the generator are the COMMITTED artefacts of "
            "a spec directory — a `spec/` rule would hide exactly the files pinning exists to "
            "produce, which is why the rule is on the extension"
        )


def test_no_pdf_is_tracked_anywhere_in_the_repository():
    """The repo-wide half, which covers the history PDFs and anything else nobody has recorded."""
    tracked_pdfs = sorted(p for p in TRACKED if p.endswith(".pdf"))
    assert tracked_pdfs == [], (
        f"{len(tracked_pdfs)} PDFs are tracked: {tracked_pdfs}. No specification PDF has ever been "
        "committed here and the pin records say so in as many words"
    )


def test_the_cat048_edition_history_is_covered_but_is_not_a_pin():
    """AN ABSENCE, and the reason this module can live with 22 non-pins inside a `spec/`.

    The placement invites the wrong reading: 80b38d1's harness message tells a reader that "pinned
    standards live in spec/", so 22 edition PDFs under `spec/history/` could read as 22 pins. The
    distinction is asserted in BOTH directions — none of them is in the derived pin set, and the
    derived set does not shrink because of them — so the day somebody records one as a pin, or
    drops one into `spec/` itself, a build fails instead of a reader guessing.
    """
    history = sorted((PKG / "fixtures" / "cat048" / "spec" / "history").glob("*.pdf"))
    if not history:
        pytest.skip("the edition history is not in this working tree; the record of it is")
    rels = {str(p.relative_to(PKG)) for p in history}
    assert len(rels) == 22, f"the edition history holds {len(rels)} PDFs, expected 22"
    overlap = sorted(rels & set(PINS))
    assert not overlap, (
        f"a history PDF is recorded as a pin: {overlap}. The governing text is Edition 1.32 alone; "
        "the other 21 are the lineage, and a lineage entry promoted to a pin would make this "
        "document say a row was read against an edition it was not"
    )
    for rel in sorted(rels):
        assert _repo_rel(rel) not in TRACKED, f"{rel} is tracked"
    # And the count and home are stated in the pin record, so the prose and the disk agree.
    pin = json.loads((PKG / "fixtures" / "cat048" / "spec" / "cat048_pin.json").read_text())
    hist = pin["edition_history"]
    assert hist["count"] == len(rels), (
        f"cat048_pin.json says the history holds {hist['count']} files and the disk holds "
        f"{len(rels)}"
    )
    assert hist["home"] == "fixtures/cat048/spec/history/", hist["home"]
    assert hist["committed"] is False


def test_the_cat034_edition_history_is_covered_but_is_not_a_pin():
    """The same absence, for the second lineage, and it is NOT a parametrised copy of the first.

    Two `spec/history/` directories exist now and the temptation is to fold the two checks into one
    parametrised case over `(directory, count, pin file)`. Declined, and the reason is the reason
    the count is a hard number at all: a parametrised form takes its expected count from a table,
    and a table is one more place to update in the same edit that made it wrong. Two tests naming
    two counts in two sentences fail with the format's name in the message and cannot be satisfied
    by editing one row.

    What IS shared is the property, and it is asserted the same way in both directions: none of the
    lineage files is in the derived pin set, and the derived set does not shrink because of them.
    """
    history = sorted((PKG / "fixtures" / "cat034" / "spec" / "history").glob("*.pdf"))
    if not history:
        pytest.skip("the edition history is not in this working tree; the record of it is")
    rels = {str(p.relative_to(PKG)) for p in history}
    assert len(rels) == 3, f"the CAT034 edition history holds {len(rels)} PDFs, expected 3"
    overlap = sorted(rels & set(PINS))
    assert not overlap, (
        f"a CAT034 history PDF is recorded as a pin: {overlap}. The governing text is Edition 1.29 "
        "alone; 1.26, 1.27 and 1.28 are the lineage, and a lineage entry promoted to a pin would "
        "make this document say a row was read against an edition it was not"
    )
    for rel in sorted(rels):
        assert _repo_rel(rel) not in TRACKED, f"{rel} is tracked"
    pin = json.loads((PKG / "fixtures" / "cat034" / "spec" / "cat034_pin.json").read_text())
    hist = pin["edition_history"]
    assert hist["count"] == len(rels), (
        f"cat034_pin.json says the history holds {hist['count']} files and the disk holds "
        f"{len(rels)}"
    )
    assert hist["home"] == "fixtures/cat034/spec/history/", hist["home"]
    assert hist["committed"] is False
    # The pin is NOT among them, which is the half the CAT048 test never had to state: there the
    # pinned edition is also present in `history/` as a 23rd copy of itself, and here it is not.
    assert not any("ed129" in r for r in rels), (
        "Edition 1.29 is in fixtures/cat034/spec/history/. It is the pin and it lives in spec/ "
        "itself; a second copy under history/ would be an unrecorded PDF and the closure check "
        "would be right to say so"
    )


def test_the_klv_0601_edition_history_is_covered_but_is_not_a_pin():
    """The same absence, for the THIRD lineage, and again not a parametrised copy of the first two.

    The reason for declining to parametrise is the reason the CAT034 test gives and it has not got
    weaker with a third instance: a parametrised form takes its expected count from a table, and a
    table is one more place to update in the same edit that made it wrong. Three tests naming three
    counts in three sentences fail with the format's name in the message.

    WHAT IS DIFFERENT HERE, AND IT IS THE POINT OF WRITING IT OUT. In the other two lineages the
    pinned edition is the LATEST and the history is what came before it. Here the history straddles
    the pin in BOTH directions: the governing text is ST 0601.14, the lineage holds .0, .4 and .8
    which precede it, and the `spec/` directory also holds .19 which follows it and is pinned as
    context only. So "lineage" here means "not the governing text" rather than "older than the
    governing text", and the assertion that none of the three is in the derived pin set is doing
    more work than its equivalents: it is the only thing keeping a reader from taking ST 0601.4's
    tag table - which states item 22 at a Len of 2, exactly as .14a does - for a row set source.

    AND ONE OF THESE THREE IS WHY PARK 13 COULD BE RULED AT ALL. ST 0601.4 carries the full §3
    revision history back to the initial release; ST 0601.8's carries one row. A round holding only
    the later document would have had no chain to enumerate. That is recorded in the pin record
    rather than asserted here, because it is a fact about the documents and not about the layout.
    """
    history = sorted((PKG / "fixtures" / "klv" / "spec" / "history").glob("*.pdf"))
    if not history:
        pytest.skip("the edition history is not in this working tree; the record of it is")
    rels = {str(p.relative_to(PKG)) for p in history}
    assert len(rels) == 3, f"the KLV 0601 edition history holds {len(rels)} PDFs, expected 3"
    overlap = sorted(rels & set(PINS))
    assert not overlap, (
        f"a KLV 0601 history PDF is recorded as a pin: {overlap}. The governing text is ST 0601.14 "
        "alone; the initial release, .4 and .8 are the lineage, and a lineage entry promoted to a "
        "pin would make this document say a row was read against an edition it was not"
    )
    for rel in sorted(rels):
        assert _repo_rel(rel) not in TRACKED, f"{rel} is tracked"
    pin = json.loads((PKG / "fixtures" / "klv" / "spec" / "klv_pin.json").read_text())
    hist = pin["edition_history"]
    assert hist["count"] == len(rels), (
        f"klv_pin.json says the history holds {hist['count']} files and the disk holds {len(rels)}"
    )
    assert hist["home"] == "fixtures/klv/spec/history/", hist["home"]
    assert hist["committed"] is False
    # Every lineage file is recorded INDIVIDUALLY, by name, with the hash that identifies the copy —
    # the shape cat048's record set. A count alone would let a file be swapped for another.
    declared = {f["filename"] for f in hist["files"]}
    assert declared == {p.name for p in history}, (
        f"klv_pin.json declares {sorted(declared)} and the disk holds "
        f"{sorted(p.name for p in history)}"
    )
    for entry in hist["files"]:
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), entry["filename"]
        assert isinstance(entry["bytes"], int) and entry["bytes"] > 0, entry["filename"]
        assert isinstance(entry["pages"], int) and entry["pages"] > 0, entry["filename"]
        # And each one states where its bytes came from, which for this lineage is load-bearing in
        # a way it is not for the EUROCONTROL ones: these arrived from MIRRORS rather than from the
        # publisher, and the records differ per file — two Wayback snapshots of the publisher's own
        # host and one Wikimedia copy that names no origin at all.
        assert entry["source"].startswith("http"), entry["filename"]
    # The pinned editions are NOT among them, in both directions: .14a is the governing text and
    # .19 is pinned as context, and both live in `spec/` itself.
    assert not any("0601.14" in r or "0601.19" in r for r in rels), (
        "a pinned ST 0601 edition is in fixtures/klv/spec/history/. The pins live in spec/ itself; "
        "a second copy under history/ would be an unrecorded PDF and the closure check would be "
        "right to say so"
    )
    # AND THE PARK 13 PIN IS NOT A LINEAGE FILE EITHER, which is the inverse mistake and the easier
    # one to make: EG 0601.1 is older than every governing text here, so "oldest" would have sorted
    # it into `history/`. It is a PIN because a park closed on it.
    assert not any("EG0601.1" in r for r in rels), (
        "EG0601.1.pdf is in fixtures/klv/spec/history/. It is park 13's deciding document and a "
        "pin; filing it as lineage would make the park's closure rest on a file this module "
        "asserts no ruling is read against"
    )


def test_every_history_directory_is_one_a_pin_record_declares(capsys):
    """AN ABSENCE over the NAME rather than over the two directories that currently have one.

    `spec_pdfs_on_disk()` is non-recursive, so ANY subdirectory of a `spec/` is invisible to the
    closure property — which is exactly what makes `history/` safe and exactly what would make an
    undeclared `spec/drafts/` a place to hide a PDF from this gate. So the sweep is inverted: every
    subdirectory of every `spec/` that holds PDFs must be a `history/` whose format's pin record
    declares it, with a matching count.

    Written as a rule about the shape rather than about CAT048 and CAT034, because the third
    lineage should land against a gate that already covers it.
    """
    declared, found = {}, {}
    for pin_file in sorted(FIXTURES.rglob("*_pin.json")):
        hist = json.loads(pin_file.read_text()).get("edition_history")
        if isinstance(hist, dict) and "home" in hist:
            declared[hist["home"].rstrip("/")] = hist["count"]
    for spec in sorted(FIXTURES.glob("*/spec")):
        for sub in sorted(p for p in spec.iterdir() if p.is_dir()):
            pdfs = sorted(sub.glob("*.pdf"))
            if pdfs:
                found[str(sub.relative_to(PKG))] = len(pdfs)
    undeclared = sorted(set(found) - set(declared))
    assert not undeclared, (
        f"these subdirectories of a fixtures/*/spec/ hold PDFs and no pin record declares them: "
        f"{undeclared}. spec_pdfs_on_disk() is non-recursive, so a PDF in one is invisible to the "
        "closure property — which is what makes a declared history/ safe and an undeclared "
        "subdirectory a blind spot"
    )
    for home, count in sorted(declared.items()):
        if home in found:
            assert found[home] == count, (
                f"{home} holds {found[home]} PDFs and its pin record declares {count}"
            )
    print(f"HISTORY: {len(found)} declared lineage directories, "
          f"{sum(found.values())} PDFs, 0 of them pins")


def test_the_pin_gate_states_its_derived_count_and_homes(capsys):
    """The gate's output, so a push gate can invoke this instead of restating a list.

    Printed rather than only asserted: the thing a human reads off a gate run is the count and the
    homes, and a check that verifies them silently makes the reader go and count again.
    """
    homes: dict[str, list[str]] = {}
    for path in sorted(PINS):
        home, name = path.rsplit("/", 1)
        homes.setdefault(home, []).append(name)
    lines = [f"PIN GATE: {len(PINS)} pinned documents across {len(homes)} homes, all untracked"]
    for home in sorted(homes):
        lines.append(f"  {home}/  ({len(homes[home])})")
        for name in homes[home]:
            lines.append(f"      {name}  {PINS[home + '/' + name]['sha256'][:12]}…")
    # Every lineage directory, not just CAT048's. A hard-coded home printed a truthful line while
    # a second lineage sat unmentioned beside it, which is the shape of under-reporting this whole
    # module exists to end.
    histories = {str(sub.relative_to(PKG)): len(sorted(sub.glob("*.pdf")))
                 for spec in sorted(FIXTURES.glob("*/spec"))
                 for sub in sorted(p for p in spec.iterdir() if p.is_dir())
                 if sorted(sub.glob("*.pdf"))}
    lines.append(f"  NOT pins: {sum(histories.values())} edition PDFs across "
                 f"{len(histories)} lineage directories — covered by the zero-tracked check")
    for home in sorted(histories):
        lines.append(f"      {home}/  ({histories[home]})")
    # The cited class, printed at zero as well as at one. A class that only appears in the output
    # once it has a member is a class a reader has no reason to believe is being checked.
    lines.append(f"  CITED, not carried: {len(CITED)}"
                 + ("" if CITED else " — legal and empty, which is #9's Branch U shape"))
    for path in sorted(CITED):
        lines.append(f"      {path}  ({CITED[path]['classification']}) — must not exist")
    # The third class, printed with its two halves, because a COMPUTED class is the one a reader
    # is least able to check by eye: the count alone would not say what it was computed from.
    lines.append(f"  CITED BUT UNPUBLISHED: {len(MEMBERS)}"
                 + ("" if MEMBERS else " — legal and empty"))
    for (identifier, edition), entry in sorted(MEMBERS.items()):
        lines.append(f"      {identifier} Edition {edition}  "
                     f"— cited at {len(entry['cited_at'])} site(s), not offered as of "
                     f"{entry['check']['checked_on']}")
    if CLASSIFIED["candidate"]:  # pragma: no cover - the gate above requires this to be empty
        lines.append(f"      candidates awaiting a check: {len(CLASSIFIED['candidate'])}")
    print("\n".join(lines))
    out = capsys.readouterr().out
    assert "PIN GATE:" in out and "NOT pins:" in out, (
        f"the gate no longer prints its header lines:\n{out}"
    )
    assert "CITED, not carried:" in out, (
        f"the gate no longer prints the cited class:\n{out}\nIt is empty today, which is exactly "
        "why it has to be printed — a reader who cannot see the line has no way to tell a class "
        "checked and empty from a class nobody wired up. Restore the CITED line"
    )
    assert "CITED BUT UNPUBLISHED:" in out, (
        f"the gate no longer prints the computed class:\n{out}\nIt has one member and would be "
        "legal at zero, which is exactly why the line is unconditional — a reader who cannot see "
        "it has no way to tell a class checked and empty from a class nobody wired up"
    )
    assert str(len(PINS)) in out


def test_every_site_that_states_the_history_count_states_the_same_count():
    """Four sites now say how many edition PDFs there are, so the count gets the usual treatment.

    The protocol is explicit about this: a count stated in prose and checked nowhere drifts, which
    is what `test_cdm_prose_counts.py` exists for and what the eight-versus-nine pin drift was. The
    difference here is that the count has an authority — the disk — so every statement of it is
    compared against that rather than against each other.
    """
    disk = len(list((PKG / "fixtures" / "cat048" / "spec" / "history").glob("*.pdf")))
    if disk == 0:
        pytest.skip("the edition history is not in this working tree")
    n = str(disk)
    sites = {
        "cat048_pin.json": json.loads(
            (PKG / "fixtures" / "cat048" / "spec" / "cat048_pin.json").read_text()
        )["edition_history"]["count"] == disk,
    }
    assert sites["cat048_pin.json"], "cat048_pin.json's edition_history.count disagrees with disk"

    coverage = DOC.read_text()
    section = coverage[coverage.index("### The edition history"):]
    section = section[:section.index("\n### ", 10)]
    assert f"{n} editions in hand" in section, (
        f"FORMAT_COVERAGE.md's edition-history heading no longer says '{n} editions in hand'"
    )
    assert f"holds **{n} edition PDFs**" in section, (
        f"FORMAT_COVERAGE.md's edition-history prose no longer states {n} PDFs"
    )
    readme = (PKG / "fixtures" / "cat048" / "README.md").read_text()
    assert f"**{n} CAT048 edition PDFs" in readme, (
        f"fixtures/cat048/README.md no longer states {n} edition PDFs"
    )
    # The pin gate's own assertion is the fourth, and it is the one that would catch a file
    # appearing or vanishing rather than a number being mistyped.
    assert disk == 22, f"the history holds {disk} PDFs; every site above says 22"


def test_the_one_edition_not_obtained_is_named_at_every_site_that_mentions_the_gap():
    """AN ABSENCE, and the one register entry 17 exists to keep visible.

    Edition 1.26 is missing from the bundle. The failure mode is not that somebody deletes the
    statement — it is that a later reader, seeing 1.25 and 1.27 side by side, silently reads the
    lineage as continuous. So the gap is named in the document, in the pin record and in the
    fixtures README, and no site may claim the lineage is complete.
    """
    coverage = DOC.read_text()
    section = coverage[coverage.index("### The edition history"):]
    # Scoped to the lineage TABLE rather than the whole subsection: the verdict block below it
    # also names 1.26, so a subsection-wide check would pass on the wrong statement.
    section = section[:section.index("\n#### Does any change record", 10)]
    assert "1.26" in section and "NOT OBTAINED" in section, (
        "the lineage table no longer marks Edition 1.26 as not obtained"
    )
    pin = json.loads((PKG / "fixtures" / "cat048" / "spec" / "cat048_pin.json").read_text())
    assert pin["edition_history"]["not_obtained"]["edition"] == "1.26"
    assert pin["edition_history"]["editions_in_hand"].endswith("except 1.26")
    readme = (PKG / "fixtures" / "cat048" / "README.md").read_text()
    assert "**1.26** is the one edition" in readme, (
        "fixtures/cat048/README.md no longer names the missing edition"
    )
    # And nowhere claims completeness.
    for label, text in (("FORMAT_COVERAGE.md", section), ("README.md", readme)):
        for wrong in ("all 23 editions", "every edition of the lineage is",
                      "the complete lineage is in hand"):
            assert wrong not in text, f"{label} claims a completeness the bundle does not have"


# --------------------------------------------- the fetched provenance evidence (the third rule) ---
#
# THE THIRD NOT-COMMITTED RULE IN THIS REPOSITORY, and the first one whose subject is somebody
# else's website. `*.pdf` is an EXTENSION rule over specification documents; `fixtures/klv/streams/`
# is a DIRECTORY rule over real streams; `fixtures/klv/provenance/` is a DIRECTORY rule over
# FETCHED EVIDENCE — CDX index dumps, archived pages, site catalogues, directory listings — held
# because the standing rule is that every asserted fact comes from bytes held and pinned, and a
# quotation from a page that was read and thrown away is a recollection.
#
# WHAT THESE CHECKS OWN, and it is deliberately narrow: that the rule ignores the directory, that
# nothing under it is tracked, and that the pin record's roster agrees with the disk wherever the
# disk has the file. The READING of those files — the counts, the quotation, the failure modes —
# belongs to `tests/test_cdm_format_coverage.py`, which is where every other reading lives.

PROVENANCE_DIR = "fixtures/klv/provenance"

#: The pin record's own roster of what the provenance round fetched. Read rather than enumerated,
#: for the reason this module's docstring gives about the pin set: a hand-kept list of nineteen
#: files is a list that goes stale on the twentieth.
def _provenance_roster() -> dict:
    record = json.loads((PKG / "fixtures/klv/spec/klv_pin.json").read_text())
    node = record["day_flight_provenance_2026_08_26"]
    return node["the_held_evidence_nineteen_files_each_pinned"]["files"]


def test_the_provenance_rule_ignores_the_directory_and_nothing_under_it_is_tracked():
    """The rule has to bite, and the index has to be empty of it — two different claims.

    `.gitignore` carrying a line and git ignoring a path are not the same fact: a rule can be
    present and shadowed by a later negation, which is why this asks `check-ignore` rather than
    grepping. And an ignore rule says nothing about what is ALREADY tracked, so the index is asked
    separately. A round that fetched 63 356 URLs' worth of index dumps and then committed them
    would have put somebody else's website in this repository's history permanently.

    DOES NOT SKIP ON A FRESH CLONE. `--no-index` rules on the PATTERN, so the answer is the same
    whether or not the directory exists — and the tracked-files half is decided by the index, which
    a clone has in full.
    """
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", f"{PROVENANCE_DIR}/cdx_gwg_nga_mil_host.txt"],
        cwd=REPO).returncode == 0
    assert ignored, (
        f"{PROVENANCE_DIR}/ is no longer ignored. Nineteen fetched files sit there when the "
        "provenance round's working tree is present, and `git add -A` would stage every one"
    )
    leaked = sorted(p for p in TRACKED if p.startswith(PROVENANCE_DIR + "/"))
    assert not leaked, (
        f"fetched provenance evidence is TRACKED: {leaked}. These are other people's pages and "
        "index dumps, held as evidence and never shipped"
    )


def test_the_provenance_roster_is_nineteen_files_each_with_a_hash_a_size_and_an_origin():
    """A roster entry without an origin URL is the exact defect this round was sent to fix.

    The round's whole finding about this repository is that the transport-stream pin recorded a hash
    and no origin, so a reader could not re-obtain it. A roster of the evidence that repeated the
    omission would be the same defect one level down — so every entry is required to carry all
    three fields, and the count is asserted against the sentence the pin record's own key states.
    """
    roster = _provenance_roster()
    assert len(roster) == 19, (
        f"the roster holds {len(roster)} files and its own key says nineteen. Both the key and the "
        "prose in FORMAT_COVERAGE.md state that number, so a file added without updating them "
        "leaves three sites disagreeing"
    )
    for name, entry in roster.items():
        assert set(entry) == {"sha256", "bytes", "origin_url"}, f"{name} has fields {sorted(entry)}"
        assert len(entry["sha256"]) == 64 and int(entry["sha256"], 16) >= 0, name
        assert entry["bytes"] > 0, name
        assert entry["origin_url"].startswith("https://"), (
            f"{name} records no fetchable origin. A pinned page whose URL is missing is a "
            "recollection with a hash on it"
        )


def test_every_held_provenance_file_matches_its_pin():
    """Re-hash what is on disk, for the same reason the pinned PDFs are re-hashed.

    SKIPS PER FILE when the bytes are absent, on the rule the stream guards use: the directory is
    excluded by a directory rule, so a fresh clone has the roster and not the evidence. A file that
    IS present must match — a truncated CDX dump would otherwise quietly change every count the
    provenance section derives from it.
    """
    roster = _provenance_roster()
    checked = 0
    for name, entry in roster.items():
        path = REPO / PROVENANCE_DIR / name
        if not path.exists():
            continue
        blob = path.read_bytes()
        assert len(blob) == entry["bytes"], f"{name} is {len(blob)} bytes, the pin says {entry['bytes']}"
        assert hashlib.sha256(blob).hexdigest() == entry["sha256"], (
            f"{name} does not hash to its pin — this is different evidence than was read"
        )
        checked += 1
    if not checked:
        pytest.skip("no provenance evidence in this working tree — it is pinned, not vendored")


def test_the_disk_holds_no_provenance_file_the_roster_does_not_name():
    """The closure property, in the direction an enumeration can never give.

    The pin gate above exists because a list of pins went stale in the direction nobody checks — a
    PDF on disk that no record named. The same failure is available here and is cheaper to make: a
    round that fetches one more page, quotes it, and forgets the roster leaves a sentence in
    `FORMAT_COVERAGE.md` whose evidence is unpinned. Skips when the directory is absent, which is
    every fresh clone.
    """
    directory = REPO / PROVENANCE_DIR
    if not directory.is_dir():
        pytest.skip("no provenance directory in this working tree")
    on_disk = {p.name for p in directory.iterdir() if p.is_file() and p.name != ".DS_Store"}
    unnamed = sorted(on_disk - set(_provenance_roster()))
    assert not unnamed, (
        f"held but pinned nowhere: {unnamed}. Fetched evidence that no roster names is evidence "
        "nobody can re-obtain, which is the state this round found the transport-stream pin in"
    )


def test_the_cited_gitignore_line_for_the_provenance_rule_is_the_line_it_cites():
    """A citation to a LINE is only worth having if the line holds still.

    `klv_pin.json` cites `.gitignore:42` five times and now cites `.gitignore:121` too, and
    `FORMAT_COVERAGE.md` cites 121 as well. The `.gitignore` comment block says in its own words why
    that is fragile: a rule inserted ABOVE an existing one silently re-points every citation at a
    different line. So this asserts the two facts a citation promises — that the line holds the rule
    named, and that `check-ignore` attributes the ignore to THAT line and not to some other rule
    that happens to cover the same path.

    Line 42 is asserted alongside it, unasked, because this round appended below it and the cheapest
    proof that the append did not disturb it is to check.
    """
    lines = (REPO / ".gitignore").read_text().splitlines()
    assert lines[41] == "*.pdf", (
        f".gitignore line 42 is {lines[41]!r}. Five citations in klv_pin.json point at it by number"
    )
    assert lines[120] == "fixtures/klv/provenance/", (
        f".gitignore line 121 is {lines[120]!r}. `klv_pin.json` and `FORMAT_COVERAGE.md` both cite "
        "121 by number for the provenance rule"
    )
    reported = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", f"{PROVENANCE_DIR}/cdx_gwg_nga_mil_host.txt"],
        cwd=REPO, capture_output=True, text=True).stdout.strip()
    assert reported.startswith(".gitignore:121:fixtures/klv/provenance/"), (
        f"check-ignore attributes the ignore to {reported!r}. Both prose sites state that this path "
        "is refused by line 121, and an ignore that comes from a different rule makes those "
        "sentences false even though the file still is not staged"
    )
