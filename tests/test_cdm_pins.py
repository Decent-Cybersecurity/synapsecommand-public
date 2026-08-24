"""The pin gate, derived rather than enumerated.

WHY THIS EXISTS
---------------
The push gate used to name the pins by hand, and it went stale the way hand-maintained lists go
stale: the last one named **eight** pinned PDFs while the tree at that moment held **nine**.
Nothing was wrong with any of the nine — the list had simply not been extended when CAT048's
EUROCONTROL pin landed, and a gate that under-counts what it is checking reports a clean run over a
smaller tree than the one in front of it. (Those two numbers are the historical ones and they are
left as they were. The tree holds **ten** pins across **five** homes today, and nothing below
restates that: the gate derives it, which is the point.)

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

WHAT IS NOT A PIN
-----------------
`fixtures/cat048/spec/history/` holds 22 CAT048 edition PDFs — the lineage, 1.10 to 1.32. They are
covered by the zero-tracked check like every other PDF and they are **not pins**: the governing text
is Edition 1.32 alone. That distinction is asserted in both directions here, because the placement
invites the opposite reading — 80b38d1's harness message tells a reader that "pinned standards live
in `spec/`", and 21 non-pins inside `spec/` would otherwise read as 21 pins.
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


def spec_pdfs_on_disk() -> set[str]:
    """PDFs sitting DIRECTLY in a `fixtures/*/spec/` directory — not in a subdirectory of one.

    Non-recursive on purpose: `spec/history/` holds 22 edition PDFs that are not pins, and a
    recursive glob would sweep them into the set this module says must equal the pins.
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
    five adapters, and a discovery that found one of them is a broken parser rather than a small
    tree. The floor moves when a pin lands — 9 to 10, and four homes to five, when STANAG 5527's
    covering document landed in `fixtures/fft/spec/` — and moving it is the deliberate act, because
    a floor left behind is a gate reporting a clean run over a smaller tree than the one in front
    of it. That is the same failure this module was written for, one level up.
    """
    assert len(PINS) >= 10, (
        f"discovered only {len(PINS)} pins: {sorted(PINS)}. Both statements of a pin are parsed — "
        "the *_pin.json records and FORMAT_COVERAGE.md's pin rows — so a low count means one of the "
        "two parsers has stopped matching"
    )
    homes = {p.rsplit("/", 1)[0] for p in PINS}
    assert len(homes) >= 5, f"pins found in only {sorted(homes)}"
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
    """
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
    history = sorted((PKG / "fixtures" / "cat048" / "spec" / "history").glob("*.pdf"))
    lines.append(f"  NOT pins: {len(history)} CAT048 edition PDFs in "
                 f"fixtures/cat048/spec/history/ — the lineage, covered by the zero-tracked check")
    # The cited class, printed at zero as well as at one. A class that only appears in the output
    # once it has a member is a class a reader has no reason to believe is being checked.
    lines.append(f"  CITED, not carried: {len(CITED)}"
                 + ("" if CITED else " — legal and empty, which is #9's Branch U shape"))
    for path in sorted(CITED):
        lines.append(f"      {path}  ({CITED[path]['classification']}) — must not exist")
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
