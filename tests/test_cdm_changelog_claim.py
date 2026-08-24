"""What `docs/docs/changelog.mdx` claims about `MIGRATIONS.md`, and the direction that is checkable.

WHY THIS EXISTS
---------------
The page used to open with "This page **mirrors** `packages/cdm/synapse_cdm/MIGRATIONS.md`", and
the push gate for `6f8aa61` found it two Phase 1 entries behind — `stanag4609` from `1b0316b` and
`stanag5527` from `6f8aa61`. The obvious repair was to add the two entries and make the word true.
Reading both files first is what stopped that, because the word was false in **four** ways and
three of them predate both entries:

* the page's "Proposed for 1.1.0" section carries **5** of the file's **10** bullets. The five it
  carries are named field paths; the five it drops — a sensor frame, a vocabulary for the life of a
  track, a presentation profile, gap 8 extent, gap 10 air-data speeds — are design questions and
  gaps. That is curation, and it was there before either Phase 1 landed;
* the page has a section the FILE does not: "Compatibility is not equality", with a worked
  `version.compatible()` snippet. So the page is not a subset of the file either;
* the entries are reworded and abridged — the file writes ``**`adapters/tak.py` 1.0.0
  (Cursor-on-Target, bidirectional)** — implements…`` and the page writes ``**`adapters/tak.py`
  1.0.0 — Cursor-on-Target, bidirectional.** Implements…`` — and reordered: the file runs
  …cat021, stanag4676, gmtif, cat048 and the page runs …stanag4676, gmtif, cat048, cat021;
* and then the two Phase 1 entries, which are the symptom rather than the disease.

So the claim was narrowed to what the page does — a curated summary — rather than the page being
widened to fit the claim. Adding the Phase 1 entries would also have changed the page's GENRE: it
is a public page for a reader of the published contract, and "no adapter code, no fixtures, one
park, ADatP-36 Edition B not in hand" is repository-internal process, not schema history.

THE RULED UNIT, BECAUSE "SUMMARY" NEEDS ONE AS MUCH AS "MIRRORS" DID
--------------------------------------------------------------------
A narrowed claim with nothing behind it re-widens itself, so the summary claim is given the one
kind of teeth it can honestly carry — **a subset assertion in one direction**:

* **the adapter set** — every ``adapters/<name>.py`` the page's history section names must be named
  by the file;
* **the proposed-field set** — every dotted CDM path in a 1.1.0 bullet on the page must be proposed
  by the file.

**Page ⊆ file, and NOT file ⊆ page.** That asymmetry is the ruling, not an omission. It catches the
failure that matters — the page minting a claim the source does not make — and it permits the thing
the page is for, which is leaving material out. The consequence is stated plainly here so nobody
has to infer it: **the mutation where `MIGRATIONS.md` gains an entry and this page does not is
designed NOT to fail.** It was run, it did not fail, and that is correct. The converse — the page
gaining an adapter or a field the file does not name — fails.

AND THE ABSENCE, SCOPED RATHER THAN BLANKET
-------------------------------------------
"Mirror" is used legitimately across this repository in an unrelated sense — the "mirror-image
defect" of null-to-zero, and GMTIF's "144–148 mirror 14–18 at +130" — at more than thirty sites. A
ban on the word would have an exemption list longer than itself. So the ban is on the *pairing*:
no occurrence of "mirror" may sit within 300 characters of "MIGRATIONS". That is the windowed form
`tests/test_cdm_ordinals.py` arrived at for the retired `nffi` name, for the same reason — prose
here is hard-wrapped, so a line-scoped check reports the repair as the offence.

TWO SITES, NOT ONE
------------------
The claim was stated twice: `docs/docs/changelog.mdx` and `docs/README.md`'s directory listing
("changelog.mdx  mirrors packages/cdm/synapse_cdm/MIGRATIONS.md"). The second is not a rendered
page — it sits outside `docs/docs/` — which is exactly why it would have survived a fix aimed at
the rendered one. The disjunction protocol says a fact stated twice gets collected and required to
agree, so both are swept by one regex here.
"""
import pathlib
import re

import pytest

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
MIGRATIONS = PKG / "MIGRATIONS.md"
CHANGELOG = REPO / "docs" / "docs" / "changelog.mdx"

#: The page's history section and the file's, by their own headings. Read rather than assumed: a
#: heading that stops matching is a FAILURE here, not a silently empty section.
PAGE_HISTORY = "## Adapters that landed with no schema change"
FILE_HISTORY = "### Adapters that landed with no schema change"
PAGE_PROPOSED = "## Proposed for 1.1.0 — MINOR, not yet implemented"
FILE_PROPOSED = "## Proposed for 1.1.0 (MINOR — not yet implemented)"

ADAPTER = re.compile(r"adapters/([a-z0-9_]+)\.py")
#: A dotted CDM path, e.g. `Entity.label`. Collected only from a bullet's own line, so a path
#: mentioned in a paragraph of rationale is not read as a proposal.
FIELD = re.compile(r"`([A-Z][A-Za-z]+\.[a-z_]+)`")


def _section(text: str, heading: str, terminator: str) -> str:
    """The text under `heading`, up to the next heading of `terminator`'s level.

    Asserts the heading is there. A helper that returned "" for a missing heading would turn every
    check below into a check on an empty string, which is the failure mode
    `test_cdm_pins.py::test_the_pin_set_was_actually_discovered` exists for one level up.
    """
    assert text.count(heading) == 1, (
        f"the heading {heading!r} occurs {text.count(heading)} times, expected 1. Re-anchor this "
        "deliberately — a section this module cannot find is a section it cannot check"
    )
    rest = text[text.index(heading) + len(heading):]
    nxt = re.search(terminator, rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _bullet_fields(block: str) -> set[str]:
    return {p for line in block.splitlines() if line.startswith("- **")
            for p in FIELD.findall(line)}


def test_no_site_claims_this_page_mirrors_the_migrations_file():
    """THE ABSENCE, and it is a ban on a PAIRING rather than on a word.

    A narrowed claim that keeps the old verb re-widens itself, and the old verb has thirty-odd
    innocent homes in this repository — so what is banned is "mirror" within 300 characters of
    "MIGRATIONS", which no innocent use has ever been.
    """
    offenders = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".mdx", ".py", ".json", ".ts"}:
            continue
        if any(part in {".git", "node_modules", ".docusaurus", "build"} for part in path.parts):
            continue
        if path.name == pathlib.Path(__file__).name:
            continue                      # this module quotes the retired sentence, on purpose
        try:
            low = path.read_text().lower()
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer("mirror", low):
            window = low[max(0, m.start() - 300):m.end() + 300]
            if "migrations" in window:
                offenders.append(f"{path.relative_to(REPO)}:{low.count(chr(10), 0, m.start()) + 1}")
    assert not offenders, (
        f"these sites pair 'mirror' with MIGRATIONS.md again: {offenders}. The page is a curated "
        "summary — it drops the Phase 1 row sets, drops five of the ten 1.1.0 items, adds a "
        "section the file does not have, and rewords, reorders and abridges the rest. Either "
        "narrow the sentence or make the page a real copy and re-rule this module"
    )
    # And the ban is not a blanket one, which is the half that keeps it honest: the unrelated uses
    # of the word must still be there. If they vanished, this check would be passing on nothing.
    innocent = (REPO / "docs" / "docs" / "intro.mdx").read_text()
    assert "mirror-image defect" in innocent, (
        "the innocent uses of 'mirror' are gone, so this ban is no longer distinguishing a claim "
        "about MIGRATIONS.md from ordinary prose — it has become a blanket word ban"
    )


def test_every_adapter_the_page_names_is_named_by_the_migrations_file():
    """UNIT ONE of the summary claim: page ⊆ file, on the adapter set."""
    page = set(ADAPTER.findall(_section(CHANGELOG.read_text(), PAGE_HISTORY, r"^## ")))
    file_all = set(ADAPTER.findall(MIGRATIONS.read_text()))
    assert len(page) >= 8, (
        f"the page's history section names {len(page)} adapters: {sorted(page)}. Eight landed "
        "with no schema change, so a lower count means the extractor has stopped matching and "
        "the subset check below is passing on almost nothing"
    )
    invented = sorted(page - file_all)
    assert not invented, (
        f"the page names adapters the source file does not: {invented}. A curated summary may "
        "leave things out and may never add them — a claim minted docs-side has no source, which "
        "is the one failure this direction exists to catch"
    )


def test_every_field_the_page_proposes_is_proposed_by_the_migrations_file():
    """UNIT TWO: page ⊆ file, on the proposed-field set — scoped to each file's 1.1.0 section.

    Scoped rather than swept over the whole file, and mutation is the reason: every one of these
    paths also occurs in the history section's prose, so `path in text` would be a disjunction
    satisfied by a mention of the field rather than by a proposal of it.
    """
    page = _bullet_fields(_section(CHANGELOG.read_text(), PAGE_PROPOSED, r"^## "))
    source = _bullet_fields(_section(MIGRATIONS.read_text(), FILE_PROPOSED, r"^## "))
    assert len(page) >= 7, (
        f"the page proposes {len(page)} fields: {sorted(page)}. Five bullets carry seven paths "
        "between them, so a lower count means the extractor has stopped matching"
    )
    invented = sorted(page - source)
    assert not invented, (
        f"the page proposes fields the source file does not: {invented}. The proposals are the "
        "part of this page a consumer of the contract might plan against, so a field that exists "
        "only here is the most expensive possible docs-side invention"
    )


def test_the_page_states_the_asymmetry_it_relies_on():
    """The ruling in the page's own words, because a reader cannot infer a test's scope.

    The subset assertion is one-directional on purpose. That is a decision, and a decision nobody
    wrote down is one the next editor re-makes differently — most likely by "fixing" the page to
    match the file and quietly restoring the claim this round retired.
    """
    flat = " ".join(CHANGELOG.read_text().split())
    assert "curated summary" in flat, (
        "the page no longer says what it is. 'Curated summary' is the ruled wording and the thing "
        "the subset direction below is scoped to"
    )
    assert "The reverse is deliberately not asserted" in flat, (
        "the page no longer records that the file is permitted to run ahead of it. Without that "
        "sentence the subset test reads as a completeness check, which it is not"
    )
    assert "the file in the package wins" in flat, (
        "the precedence statement is gone. It survived the rewording deliberately — narrowing what "
        "the page claims does not change which file is authoritative"
    )
    assert "tests/test_cdm_changelog_claim.py" in flat, (
        "the page no longer names the gate that holds it to its claim. A claim with an unnamed "
        "gate is one a reader has to take on trust"
    )


def test_the_page_is_still_a_curated_summary_and_not_yet_a_copy():
    """AN ABSENCE, and a tripwire rather than a requirement that the page stay behind.

    The wording ruled here — "curated summary", "leaves out what is repository-internal" — is only
    honest while there IS something left out. If a later round brings the page level with the file,
    the wording understates it and the claim needs re-ruling, not preserving. So this fails LOUDLY
    in that direction, with the instruction rather than a demand to undo the work.
    """
    mig, page = MIGRATIONS.read_text(), CHANGELOG.read_text()
    headings = lambda text: {m.group(2).strip()
                             for m in re.finditer(r"^(#{2,3}) (.+)$", text, re.M)}
    only_in_file = headings(mig) - headings(page)
    assert only_in_file, (
        "every section of MIGRATIONS.md now has a counterpart on the page, so 'curated summary — "
        "it leaves out what is repository-internal' understates what the page does. Re-rule the "
        "claim and this module with it; do not delete sections to make this pass"
    )
    # And the one that is load-bearing today, named so the failure says which.
    assert "Row sets written as specifications, with no adapter code yet" in only_in_file, (
        "the Phase 1 section is now on the page. That is a genre change rather than a fix — Phase "
        "1 entries are repository-internal process — so it is a re-ruling and this module has to "
        "be re-read, not re-anchored"
    )
    # The other direction, which is why the page is not a subset of the file either.
    only_in_page = headings(page) - headings(mig)
    assert "Compatibility is not equality" in only_in_page, (
        "the page no longer has the section the FILE lacks. It is half the evidence that 'mirrors' "
        "was the wrong word: a mirror is neither a superset nor a reworded subset"
    )


@pytest.mark.parametrize("heading,terminator,path", [
    (PAGE_HISTORY, r"^## ", "docs/docs/changelog.mdx"),
    (PAGE_PROPOSED, r"^## ", "docs/docs/changelog.mdx"),
    (FILE_HISTORY, r"^### ", "packages/cdm/synapse_cdm/MIGRATIONS.md"),
    (FILE_PROPOSED, r"^## ", "packages/cdm/synapse_cdm/MIGRATIONS.md"),
])
def test_every_heading_this_module_anchors_to_still_exists(heading, terminator, path):
    """Four anchors, and an anchor that stops matching is a FAILURE.

    The `test_cdm_prose_counts.py` stance, applied to headings rather than to sentences: a pattern
    that silently matches nothing reads as a passing check on a site nobody is checking any more.
    """
    text = (REPO / path).read_text()
    body = _section(text, heading, terminator)
    assert body.strip(), f"{path}: the section under {heading!r} is empty"
