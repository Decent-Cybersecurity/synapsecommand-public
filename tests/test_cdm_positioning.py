"""How this repository describes SC-OES to a reader, checked against what the tree actually is.

WHY THIS EXISTS
---------------
The specification constrains its own PROSE as tightly as it constrains a wire format: a draft must
say it is a draft (§148), a claim of conformance may take two forms and no others (§45), the
positioning sentence may not be widened into "replaces" (§147), a domain that is future work may
not be described as shipped (§149), and the trademark paragraph has to be somewhere a reader
actually arrives (§44). Every one of those is a sentence, and this repository has learned twice —
the adapter-count sweep and the ordinal sweep — that a fact stated in prose and checked nowhere is
a fact that goes stale in silence.

The difference here is the direction of the failure. A stale count is embarrassing; a stale
positioning sentence is a CLAIM: "SC-OES Certified" on a page nobody re-read, or a profile
described as published when the tree has no document for it. So the sweep is over every TRACKED
file rather than over an allowlist of pages, and the allowlist below is of files that quote a
forbidden phrase IN ORDER TO FORBID IT — five of them, each of which would be the wrong place to
find the phrase absent.

THE SUBSTRING THAT IS NOT A CLAIM, AND WHY THE PATTERN CARRIES A LOOKAHEAD
-------------------------------------------------------------------------
"NATO Standard" is forbidden. `NATO Standardization Office` and `NATO Standardization Agreement`
contain it, and this repository writes both dozens of times: every STANAG pin record names the
promulgating office, because that is the citation that makes the pin checkable. A plain substring
sweep reported nine files and every hit was accurate description of a document's publisher — which
is exactly the case `00-conventions.md`'s own non-normative note anticipates ("naming the standard
an adapter implements is accurate description; describing the implementation as approved is not").
So the pattern is `NATO Standard(?!i)`, and the two spellings that would slip past a naive fix —
`Standardisation` as well as `Standardization` — are both covered by the single letter.
"""
import pathlib
import re
import subprocess

import pytest

from synapse_cdm.version import SC_OES_VERSION

REPO = pathlib.Path(__file__).resolve().parents[1]
CONVENTIONS = REPO / "spec" / "sc-oes" / "00-conventions.md"
PROFILE_DIR = REPO / "spec" / "sc-oes" / "profiles"

#: The reader-facing surfaces. `README.md` is the first thing a stranger opens and the rendered
#: SC-OES page is the first thing a reader of the site opens; the specification's own front matter
#: is the authority both of them summarise.
README = "README.md"
SITE = "docs/docs/sc-oes/index.mdx"
SPEC_README = "spec/sc-oes/README.md"
ONTOLOGY_README = "ontology/README.md"
SITE_ONTOLOGY = "docs/docs/sc-oes/ontology.mdx"


def text(rel: str) -> str:
    path = REPO / rel
    assert path.exists(), f"{rel} does not exist; this module's site list is stale"
    return path.read_text()


def flat(value: str) -> str:
    """Whitespace collapsed, and blockquote markers stripped first.

    Every sentence checked here is hard-wrapped, and differently at each site. Two of the sites
    are normative documents that carry the sentence as a blockquote, so collapsing whitespace
    alone leaves a `>` sitting at each wrap point and a pattern written around it is anchored to
    where the paragraph happens to wrap. `test_cdm_prose_counts.py` made the same repair for `#`
    in a TOML comment block, and for the same reason.
    """
    return " ".join(re.sub(r"(?m)^\s*>\s?", "", value).split())


def block(heading: str) -> tuple[str, ...]:
    """A fenced `text` block under a named lead-in in `00-conventions.md`, as its lines.

    The lists are READ from the document rather than typed here, because the document is the
    authority the ADRs and the conformance tool already defer to. A copy in a test module is a
    second authority, and two authorities is how a repository ends up enforcing the older one.
    """
    found = re.search(heading + r".*?```text\n(.*?)```", CONVENTIONS.read_text(), re.S)
    assert found, f"{heading!r} no longer introduces a text block in {CONVENTIONS.name}"
    return tuple(line.strip() for line in found.group(1).strip().splitlines() if line.strip())


FORBIDDEN = block("Forbidden claims")
PERMITTED = block("Permitted claims")

#: Forbidden phrase → the pattern that finds a CLAIM of it rather than a substring of something
#: else. Only one needs a lookahead; see the module docstring.
CLAIM_PATTERNS = {phrase: re.compile(re.escape(phrase) + (r"(?!i)" if phrase == "NATO Standard"
                                                          else ""))
                  for phrase in FORBIDDEN}

#: Files that carry a forbidden phrase in order to forbid it. Each is checked below for still
#: doing so — an allowlist whose entries have stopped quoting the thing is an allowlist that has
#: quietly become an exemption.
QUOTING_FILES = (
    "spec/sc-oes/00-conventions.md",
    "spec/sc-oes/13-conformance.md",
    "docs/adr/0009-conformance-model.md",
    "docs/adr/0010-open-source-packaging-and-licensing.md",
    "tests/test_cdm_conformance.py",
    "tests/test_cdm_conformance_spec.py",
    "tests/test_cdm_positioning.py",
)


def tracked() -> tuple[pathlib.Path, ...]:
    """Every file git tracks. `git ls-files`, not a walk of the filesystem.

    The distinction is load-bearing here for a reason this repository has hit before: the working
    tree carries untracked apparatus — the rounds directory, the pinned PDFs, a virtualenv — and a
    sweep that walks the disk reports whatever a maintainer happens to have beside the checkout.
    What is being asserted is a property of the REPOSITORY, so the repository's own file list is
    what is swept.
    """
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
    return tuple(REPO / name for name in listing.split("\0") if name)


def readable() -> tuple[tuple[str, str], ...]:
    out = []
    for path in tracked():
        try:
            out.append((str(path.relative_to(REPO)), path.read_text()))
        except (UnicodeDecodeError, OSError):
            continue                      # binary fixture payloads carry no prose to sweep
    return tuple(out)


DOCUMENTS = readable()


def test_the_sweep_reads_the_repository_it_claims_to_sweep():
    assert len(DOCUMENTS) > 500, f"the sweep found {len(DOCUMENTS)} readable tracked files"


# ------------------------------------------------------------------------ §45 terminology


def test_the_two_lists_are_the_ones_the_specification_defines():
    assert PERMITTED == ("SC-OES Conformant", "SC-OES PNT Profile Conformant")
    assert FORBIDDEN == ("SC-OES Certified", "Official SynapseCommand Partner",
                         "Approved by Decent Cybersecurity", "NATO Certified", "NATO Approved",
                         "NATO Standard")


@pytest.mark.parametrize("phrase", FORBIDDEN)
def test_no_tracked_file_makes_a_forbidden_claim(phrase):
    pattern = CLAIM_PATTERNS[phrase]
    strays = [rel for rel, body in DOCUMENTS
              if rel not in QUOTING_FILES and pattern.search(body)]
    assert not strays, (
        f"{phrase!r} appears in {strays}. It is forbidden by spec/sc-oes/00-conventions.md in "
        "documents, tooling output, packaging metadata and promotional material alike. If the "
        "hit is accurate description of a third-party document rather than a claim about this "
        "work, the repair is to reword it — naming the standard an adapter implements is "
        "description; describing the implementation as approved is not"
    )


@pytest.mark.parametrize("rel", QUOTING_FILES)
def test_every_file_on_the_quoting_allowlist_still_quotes_something(rel):
    """An exemption for a file that stopped quoting is an exemption for a file that could start."""
    body = text(rel)
    assert any(pattern.search(body) for pattern in CLAIM_PATTERNS.values()), (
        f"{rel} is exempt from the forbidden-claim sweep and no longer carries any of the "
        "phrases. Drop it from QUOTING_FILES: an exemption nobody needs is one nobody re-reads"
    )


@pytest.mark.parametrize("rel", (README, SITE))
def test_the_permitted_claims_are_stated_where_a_reader_meets_them(rel):
    body = flat(text(rel))
    for claim in PERMITTED:
        assert claim in body, f"{rel} does not state the permitted claim {claim!r}"


def test_the_profile_form_of_the_permitted_claim_names_a_profile_that_exists():
    """`SC-OES PNT Profile Conformant` is the general form's one worked instance."""
    named = PERMITTED[1].split()[1]
    assert (PROFILE_DIR / f"{named.lower()}.md").exists(), (
        f"the permitted claim names the {named} profile and spec/sc-oes/profiles/ has no "
        "document for it")


# ------------------------------------------------------------------------ §147 positioning


POSITIONING = ("lightweight operational-event semantics layer applied after source-format "
               "translation into the SynapseCommand Canonical Data Model")


@pytest.mark.parametrize("rel", (README, SITE, "spec/sc-oes/00-conventions.md"))
def test_the_positioning_sentence_is_stated_at_every_reader_facing_site(rel):
    assert POSITIONING in flat(text(rel)), (
        f"{rel} no longer carries the positioning sentence. It is the claim the specification "
        f"makes about itself in full, and it is stated at every site so that no site can widen it")


#: The formats §147 names, none of which SC-OES replaces. Read as a set of things that must never
#: appear on the other side of a "replaces" verb.
NOT_REPLACED = ("ASTERIX", "STANAG 4676", "STANAG 4607", "TAK", "AIS", "AIXM", "MIP / JC3IEDM")

REPLACEMENT_CLAIM = re.compile(r"SC-OES\s+(?:\w+\s+){0,3}?(replaces|supersedes|replacing|"
                               r"superseding)\b", re.I)

#: The two files that write the banned shape in order to ban it. `docs/adr/0010` states §147's
#: prohibition by quoting the claim it forbids — decision 8, which is also where this whole sweep
#: was predicted: "A sweep in the shape this repository already uses for prose bans asserts the
#: absence over the tracked tree, so the rule is a build failure rather than a style note."
REPLACEMENT_QUOTING_FILES = ("docs/adr/0010-open-source-packaging-and-licensing.md",
                             "tests/test_cdm_positioning.py")


def test_no_tracked_file_says_sc_oes_replaces_anything():
    """§147's ban, swept rather than reviewed. The verbs are the ones the section itself uses."""
    strays = []
    for rel, body in DOCUMENTS:
        if rel in REPLACEMENT_QUOTING_FILES:
            continue
        for found in REPLACEMENT_CLAIM.finditer(flat(body)):
            strays.append(f"{rel}: {found.group(0)!r}")
    assert not strays, (
        "SC-OES is described as replacing something at these sites:\n  " + "\n  ".join(strays) +
        "\nIt replaces nothing: a source format remains the record of its own wire semantics, and "
        "SC-OES applies after translation into the CDM")


@pytest.mark.parametrize("rel", (README, SITE))
def test_the_formats_sc_oes_does_not_replace_are_named_where_the_claim_is_made(rel):
    """Naming them is what makes the disclaimer checkable by a reader as well as by this test."""
    body = flat(text(rel))
    missing = [name for name in NOT_REPLACED if name not in body]
    assert not missing, f"{rel} does not name {missing} among the formats SC-OES does not replace"


# ------------------------------------------------------------------------ §148 draft status


#: Site → the label it must carry, with the version DERIVED from the package rather than typed.
DRAFT_LABELS = {
    README: (f"SC-OES v{SC_OES_VERSION} — Draft",
             f"SynapseCommand Operational Ontology v{SC_OES_VERSION} — Draft"),
    SITE: (f"SC-OES v{SC_OES_VERSION} — Draft",),
    SITE_ONTOLOGY: (f"SynapseCommand Operational Ontology v{SC_OES_VERSION} — Draft",),
    SPEC_README: (f"SC-OES v{SC_OES_VERSION} — Draft",),
    ONTOLOGY_README: (f"SC-OES v{SC_OES_VERSION} — Draft",),
}


@pytest.mark.parametrize("rel", sorted(DRAFT_LABELS))
def test_every_reader_facing_site_labels_the_work_a_draft(rel):
    body = flat(text(rel))
    for label in DRAFT_LABELS[rel]:
        assert label in body, (
            f"{rel} does not carry {label!r}. §148 requires the draft status to be labelled "
            f"clearly wherever the work is described, and the version comes from "
            f"synapse_cdm.version.SC_OES_VERSION — if the two have diverged, that is the finding")


@pytest.mark.parametrize("rel", (README, SITE, SPEC_README))
def test_no_site_implies_an_external_standards_body_has_approved_this(rel):
    body = flat(text(rel))
    assert "submitted to, reviewed by, or approved by any external standards body" in body, (
        f"{rel} no longer disclaims external approval. §148: do not imply standard-body approval")


# ------------------------------------------------------------------------ §149 future profiles


#: §149's ten domains, which are future work. NOT a claim about the tree — the test below is what
#: makes it one, by requiring each to have no profile document and no governed type.
FUTURE_DOMAINS = ("maritime", "land", "space", "cyber", "medical", "fires", "IAMD", "exercise",
                  "weather", "infrastructure")


def published_profiles() -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in PROFILE_DIR.glob("*.md")))


def test_the_published_profiles_are_the_documents_on_disk():
    from synapse_cdm.oes_registry import PROFILES
    assert published_profiles() == tuple(sorted(name.lower() for name in PROFILES))


@pytest.mark.parametrize("rel", (README, SITE))
def test_the_published_profiles_are_named_where_the_count_is_stated(rel):
    """The count and the roster together, so a profile cannot be added and left unmentioned."""
    body = flat(text(rel))
    names = published_profiles()
    assert f"Seven domain profiles" in body or "Seven are published" in body, (
        f"{rel} no longer states how many profiles are published")
    assert len(names) == 7, f"the tree has {len(names)} profile documents and the prose says seven"
    missing = [name for name in names if name.lower() not in body.lower()]
    assert not missing, f"{rel} states the profile roster and omits {missing}"


@pytest.mark.parametrize("rel", (README, SITE))
def test_the_future_domains_are_described_as_future_work_and_nothing_else(rel):
    body = flat(text(rel))
    missing = [domain for domain in FUTURE_DOMAINS if domain not in body]
    assert not missing, f"{rel} does not list {missing} among the domains that are future work"
    assert "future work and are not implemented here" in body


@pytest.mark.parametrize("domain", FUTURE_DOMAINS)
def test_no_future_domain_has_been_quietly_implemented(domain):
    """The direction that matters: a domain called future work while the tree ships it."""
    from synapse_cdm.oes_registry import list_event_types
    assert not (PROFILE_DIR / f"{domain.lower()}.md").exists(), (
        f"{domain} is documented as future work and spec/sc-oes/profiles/ has a document for it")
    claimed = [record.id for record in list_event_types()
               if record.id.split(".")[1] == domain.lower()]
    assert not claimed, (
        f"{domain} is documented as future work and the governed registry carries {claimed}")


# ------------------------------------------------------------------------ §44 trademark


#: The three clauses of the trademark paragraph, matched separately so that a rewording that
#: preserves the substance passes and one that drops a limb does not. `licen[cs]e` because the
#: specification writes the American spelling and this repository's prose writes the British one;
#: the boundary being drawn is about trademarks, not orthography.
TRADEMARK_CLAUSES = (
    r"open interoperability specification maintained within the SynapseCommand project by\s+"
    r"Decent Cybersecurity",
    r"licen[cs]e governing these materials does not grant rights to use Decent Cybersecurity or\s+"
    r"SynapseCommand trademarks",
    r"except as necessary for accurate descriptive reference",
)


@pytest.mark.parametrize("rel", (README, SITE, "spec/sc-oes/00-conventions.md"))
def test_the_trademark_boundary_is_stated_where_a_reader_arrives(rel):
    body = flat(text(rel))
    missing = [clause for clause in TRADEMARK_CLAUSES if not re.search(clause, body)]
    assert not missing, (
        f"{rel} no longer carries the trademark paragraph in full; missing {missing}. §44 asks "
        "for it in documentation, which means the pages a reader actually opens")


@pytest.mark.parametrize("rel", (README, SITE))
def test_no_certification_programme_is_created_or_implied(rel):
    body = flat(text(rel))
    assert "no certification programme" in body, (
        f"{rel} no longer says outright that there is no certification programme. §44 forbids "
        "creating one in this work, and the sentence saying so is what keeps a reader from "
        "assuming otherwise")


# ------------------------------------------------------------------------ §146 README


def test_the_readme_positions_the_repository_as_the_contract_layer():
    """§146's description, in this repository's own words, with all five members present."""
    opening = flat(text(README).split("## ")[0])
    assert "open integration and semantic contract layer" in opening
    for member in ("Canonical Data Model", "Operational Event Specification",
                   "Operational Ontology", "JSON\nSchemas".replace("\n", " "), "adapters",
                   "conformance tooling"):
        assert member in opening, f"README.md's opening does not name {member!r}"


def test_the_readme_layout_names_every_top_level_directory_the_semantic_layer_added():
    body = text(README)
    for directory in ("spec/", "ontology/", "examples/"):
        assert f"\n{directory}" in body or f"`{directory}`" in body, (
            f"README.md's layout does not name {directory}, which is a top-level directory a "
            "reader will see in the tree")


# ================================================ the counts these pages state about the tree
#
# The same protocol `test_cdm_prose_counts.py` applies to the adapter roster, applied to the
# numbers the SC-OES prose states. Each site is anchored to its own sentence, each number is
# DERIVED, and a pattern that stops matching is a failure rather than a pass — the reason is that
# module's and is not restated here.


def spelled_(word: str) -> int:
    from tests.test_cdm_prose_counts import spelled
    return spelled(word)


def numbered_documents() -> tuple[str, ...]:
    """`00-conventions.md` … `15-governance.md`. `README.md` and `profiles/` are not documents."""
    return tuple(sorted(p.name for p in (REPO / "spec" / "sc-oes").glob("[0-9][0-9]-*.md")))


def ontology_modules() -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in (REPO / "ontology").glob("*.ttl")))


#: (site, pattern with the count as `n`, what the number must equal, how it is derived).
COUNT_SITES = (
    (README, r"SC-OES: the (?P<n>[a-z]+) normative documents",
     lambda: len(numbered_documents()), "spec/sc-oes/NN-*.md"),
    (SITE, r"The specification itself is (?P<n>[a-z]+) documents under",
     lambda: len(numbered_documents()), "spec/sc-oes/NN-*.md"),
    (SITE, r"(?P<n>[A-Z][a-z]+) governed event types are published",
     lambda: len(_event_types()), "the packaged event registry"),
    (SITE, r"published in v0\.1\.0, across (?P<n>[a-z]+) domains",
     lambda: len({record.id.split(".")[1] for record in _event_types()}),
     "the domain segment of every governed type id"),
    (SITE_ONTOLOGY, r"The (?P<n>[a-z]+) modules are",
     lambda: len(ontology_modules()), "ontology/*.ttl"),
    ("docs/docs/intro.mdx", r"its (?P<n>[a-z]+) governed types and its",
     lambda: len(_event_types()), "the packaged event registry"),
    ("docs/docs/intro.mdx", r"governed types and its (?P<n>[a-z]+) conformance dimensions",
     lambda: len(_dimensions()), "the conformance module's own dimension list"),
)


def _event_types():
    from synapse_cdm.oes_registry import list_event_types
    return list_event_types()


def _dimensions():
    from synapse_cdm.conformance import DIMENSIONS
    return DIMENSIONS


@pytest.mark.parametrize("rel,pattern,derive,how", COUNT_SITES,
                         ids=[f"{rel}::{i}" for i, (rel, *_) in enumerate(COUNT_SITES)])
def test_every_count_these_pages_state_is_derived_from_the_tree(rel, pattern, derive, how):
    found = list(re.finditer(pattern, flat(text(rel))))
    assert len(found) == 1, (
        f"{rel}: the sentence this is anchored to matched {len(found)} times, expected 1.\n"
        f"  pattern: {pattern}\nRe-anchor it deliberately; do not delete the row")
    stated = spelled_(found[0].group("n"))
    actual = derive()
    assert stated == actual, (
        f"{rel} says {found[0].group('n')!r} ({stated}) and {how} gives {actual}")


def test_the_modules_the_ontology_page_names_are_the_files_on_disk():
    """The roster as well as its size, because a renamed module reads as prose either way."""
    body = flat(text(SITE_ONTOLOGY))
    missing = [name for name in ontology_modules() if f"`{name}`" not in body]
    assert not missing, f"{SITE_ONTOLOGY} names the ontology modules and omits {missing}"


def test_the_documents_the_page_lists_are_as_many_as_it_says():
    """The subjects listed in the closing sentence, counted against the documents themselves."""
    body = flat(text(SITE))
    listed = re.search(r"documents under\s+`spec/sc-oes/` in the repository, and they are "
                       r"normative: (?P<subjects>.*?)\. Governance", body)
    assert listed, "the closing sentence of the SC-OES page no longer lists the documents"
    # Commas separate the items; `and` joins only the LAST pair. Splitting on both would break
    # `verification and confidence` and `provenance and evidence` in half — two documents that
    # each carry a compound subject, and the reason this split is written out rather than
    # regexed in one line.
    subjects = [part.strip() for part in listed.group("subjects").split(",")]
    subjects[-1:] = [part.strip() for part in subjects[-1].rsplit(" and ", 1)]
    assert len(subjects) == len(numbered_documents()), (
        f"the page lists {len(subjects)} subjects and spec/sc-oes/ holds "
        f"{len(numbered_documents())} documents: {subjects}")
