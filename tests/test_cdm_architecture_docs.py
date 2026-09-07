"""The three architecture documents, against the tree they describe.

WHY THIS EXISTS
---------------
`ARCHITECTURE.md`, `VERSIONING.md` and `INTEROPERABILITY.md` are prose, and prose with figures in
it is the thing this repository has repaired most often: a count that was right when it was typed,
a line citation that survived the code moving under it, a version number that stopped being the
version. Every one of those was found by a sweep and none of them by a reader.

So the documents STATE and this module DERIVES. Nothing here is a second copy of a figure — each
check reads the authority (`version.py`'s constants, `adapter.roster()`, `harness._COLUMNS`,
`conformance.DIMENSIONS`, the documents' own tables) and compares. A figure in one of the three
documents that no check below reaches is a gap, and the two sweep-bound assertions are what stop
this module from passing by finding nothing.

THE ONE THING IT DOES NOT CHECK, NAMED SO NOBODY ASSUMES IT DOES
----------------------------------------------------------------
It does not judge the documents' ARGUMENTS. Whether the residual policy is right, whether six
directions are the correct six, whether a rule is enforced where the document says it is enforced —
those are a reviewer's, and the review is where they were settled. This module holds the figures.
"""
import pathlib
import re

import pytest

from synapse_cdm import adapter, conformance, harness, version
from synapse_cdm.adapter import Direction

REPO = pathlib.Path(__file__).resolve().parents[1]

ARCHITECTURE = "ARCHITECTURE.md"
VERSIONING = "VERSIONING.md"
INTEROPERABILITY = "INTEROPERABILITY.md"

#: The three documents P0 froze, at the repository root as the specification's §6 places them.
DOCS = (ARCHITECTURE, VERSIONING, INTEROPERABILITY)

#: Number words this repository writes its counts with, digits accepted alongside. The range stops
#: where the documents' counts stop; a count past it is a count this module has not been asked
#: about, and the assertion that finds one says so rather than reading it as zero.
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
                "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
                "nineteen": 19, "twenty": 20}
_NUMBER_WORD = "|".join(NUMBER_WORDS)


def stated(word: str) -> int:
    """A count as written — `fourteen` or `14` — as an integer."""
    return int(word) if word.isdigit() else NUMBER_WORDS[word.lower()]


def shipped_adapters() -> dict:
    """The adapters this package SHIPS, which is not the length of the registry.

    `adapter.REGISTRY` is a module-level global that `__init_subclass__` adds to, so any `Adapter`
    subclass defined anywhere — including the throwaway ones in the contract and harness tests — is
    in it once that module has been imported. THIS MODULE PASSED ALONE AND FAILED IN THE FULL SUITE
    until it was scoped, which is the same defect `tests/test_cdm_prose_counts.py` records for the
    same reason and the same repair: the prose says adapters are shipped, and a test double is not
    shipped. Computed on every call, because what is in the registry depends on what has been
    imported.
    """
    return {name: cls for name, cls in adapter.discover().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


def read(rel: str) -> str:
    path = REPO / rel
    assert path.exists(), f"{rel} does not exist; this module's document list is stale"
    body = path.read_text(encoding="utf-8")
    assert body.strip(), f"{rel} is empty"
    return body


def flat(value: str) -> str:
    """Whitespace collapsed. Every sentence checked here is hard-wrapped, and a pattern written
    around where a paragraph happens to wrap is anchored to the wrapping."""
    return " ".join(value.split())


BODIES = {rel: read(rel) for rel in DOCS}


# --------------------------------------------------------------------- the documents themselves


@pytest.mark.parametrize("rel", DOCS)
def test_the_document_is_here_and_says_it_is_normative(rel):
    """A frozen contract that does not say it is one is a design note somebody may disagree with."""
    body = flat(BODIES[rel])
    assert "normative" in body, (
        f"{rel} no longer states that it is normative. The three documents are a freeze; a "
        "document that does not say so is read as a proposal"
    )
    assert "MUST" in BODIES[rel], f"{rel} states no MUST, which is not a normative document"


@pytest.mark.parametrize("rel", DOCS)
def test_each_document_points_at_the_other_two(rel):
    """Three documents split one contract, so each has to say where the rest of it is."""
    missing = [other for other in DOCS if other != rel and other not in BODIES[rel]]
    assert not missing, f"{rel} does not reference {missing}"


# ------------------------------------------------------------------------- the version figures

#: A claim about one of `version.py`'s constants: the constant named, a linking word, the number.
#: The linking word is required — without it, every semver written within forty characters of a
#: constant's name would be read as a claim about it, and the documents legitimately discuss
#: numbers that are not readings (a version this campaign expects to land, a historical release).
VERSION_CLAIM = re.compile(
    r"`(?P<const>SCHEMA_VERSION|PACKAGE_VERSION|SC_OES_VERSION)`\s*"
    r"(?:is|reads|=|at)\s*`(?P<value>\d+\.\d+\.\d+)`"
)


def version_claims() -> list[tuple[str, str, str]]:
    return [(rel, m.group("const"), m.group("value"))
            for rel in DOCS for m in VERSION_CLAIM.finditer(flat(BODIES[rel]))]


def test_the_version_sweep_bound_something():
    """Before the comparison: a sweep that matches nothing passes for the wrong reason.

    Three constants, and the version model has to state all three somewhere or it is not a
    statement of this package's version axes.
    """
    found = {const for _rel, const, _value in version_claims()}
    assert found == {"SCHEMA_VERSION", "PACKAGE_VERSION", "SC_OES_VERSION"}, (
        f"the three documents state readings for {sorted(found)}. All three constants have to be "
        "stated, in the form `CONSTANT` is `x.y.z`, or the version model is incomplete and this "
        "sweep is checking a subset of it"
    )


def test_every_version_figure_the_documents_state_is_the_constant_it_names():
    """THE CHECK. One authority — `version.py` — and every prose reading compared with it."""
    wrong = []
    for rel, const, value in version_claims():
        actual = getattr(version, const)
        if value != actual:
            wrong.append(f"{rel}: says {const} is {value!r}, version.py says {actual!r}")
    assert not wrong, (
        "these version figures are stale:\n  " + "\n  ".join(wrong) +
        "\nCorrect the prose where it is stated. The constant is the authority and is never "
        "adjusted to match a document"
    )


def version_py_line(const: str) -> int:
    """The line `version.py` assigns `const` on. Derived, because the documents cite it."""
    source = (REPO / "packages" / "cdm" / "synapse_cdm" / "version.py").read_text()
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith(f"{const} = "):
            return number
    raise AssertionError(f"version.py no longer assigns {const} at the top level")


# ------------------------------------------------------------------------------ markdown tables


def section(rel: str, heading: str) -> str:
    """A document section by its exact heading line, up to the next heading of the same depth."""
    body = BODIES[rel]
    start = body.find(heading)
    assert start != -1, f"{rel} no longer carries the heading {heading!r}"
    depth = len(heading) - len(heading.lstrip("#"))
    following = re.compile(rf"(?m)^#{{1,{depth}}} ")
    match = following.search(body, start + len(heading))
    return body[start:match.start() if match else len(body)]


def table_rows(text: str) -> list[list[str]]:
    """The data rows of the FIRST markdown table in `text`, as cell lists.

    The separator row is what identifies a table, and the row above it is the header; everything
    after it until a non-pipe line is data. Written out rather than pulled from a library because
    the whole dependency budget of this repository is two packages.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^\s*\|[\s:|-]+\|\s*$", line) and index and lines[index - 1].lstrip().startswith("|"):
            rows = []
            for candidate in lines[index + 1:]:
                if not candidate.lstrip().startswith("|"):
                    break
                rows.append([cell.strip() for cell in candidate.strip().strip("|").split("|")])
            return rows
    raise AssertionError("no markdown table found in the section")


#: (document, heading, the regex whose one group is the count that section states). The count is
#: compared with the length of that section's own table, so the sentence and the list cannot part.
COUNTED_SECTIONS = (
    (ARCHITECTURE, "## 2. Direction model",
     rf"\*\*(?P<n>{_NUMBER_WORD}) values are frozen here\.\*\*"),
    (ARCHITECTURE, "### 3.2 Licence classes",
     rf"(?P<n>{_NUMBER_WORD}) classes are frozen"),
    (ARCHITECTURE, "### 3.3 Maturity model — seven levels",
     rf"Maturity model — (?P<n>{_NUMBER_WORD}) levels"),
    (ARCHITECTURE, "### 3.4 Claim status — six statuses",
     rf"Claim status — (?P<n>{_NUMBER_WORD}) statuses"),
    (VERSIONING, "## 2. The axes",
     rf"the union is (?P<n>{_NUMBER_WORD})"),
)


@pytest.mark.parametrize("rel,heading,pattern", COUNTED_SECTIONS,
                         ids=[f"{rel}:{heading}" for rel, heading, _p in COUNTED_SECTIONS])
def test_every_count_a_section_states_is_the_length_of_its_own_table(rel, heading, pattern):
    """The stale-count defect in its commonest form: a list grows and the sentence above it does not."""
    text = section(rel, heading)
    found = re.search(pattern, flat(text), re.I)
    assert found, (
        f"{rel}'s {heading!r} no longer states its count in the form this module reads "
        f"({pattern!r}). If the sentence was rewritten, re-anchor it here deliberately"
    )
    rows = table_rows(text)
    assert stated(found.group("n")) == len(rows), (
        f"{rel}'s {heading!r} says {found.group('n')!r} and its table has {len(rows)} rows: "
        f"{[row[0] for row in rows]}"
    )


def test_the_maturity_levels_are_l0_to_l6_and_the_top_rung_carries_its_prohibition():
    """Seven rungs, keyed, and L6's limit — the one rung this repository cannot award itself."""
    text = section(ARCHITECTURE, "### 3.3 Maturity model — seven levels")
    keys = [row[0].strip("`") for row in table_rows(text)]
    assert keys == [f"L{n}" for n in range(7)], f"the maturity table's levels are {keys}"
    assert "L6 MUST NOT be awarded solely by Decent Cybersecurity using synthetic fixtures" in \
        flat(text), (
        "the L6 prohibition is gone from the maturity section. Every fixture in this repository is "
        "synthetic, so it is the clause that stops the top rung being awarded by the party that "
        "also writes the gate"
    )


def test_the_direction_table_carries_the_code_spellings_the_registry_enforces():
    """The three implemented directions, from the type the enforcement reads.

    `adapter.Direction` is a `Literal`, so its members ARE the accepted strings — and
    `__init_subclass__` refuses anything else at class-definition time. The document says the
    upper-case names are the specification's spellings of the same facts; this is what holds that
    claim to the three strings the code will actually accept.
    """
    text = section(ARCHITECTURE, "## 2. Direction model")
    spellings = {cell.strip("`") for row in table_rows(text) for cell in row[1:2]}
    for literal in Direction.__args__:
        assert literal in spellings, (
            f"the direction table does not give {literal!r} as a code spelling, and "
            f"`adapter.Direction` accepts it"
        )
    assert f'Direction = Literal["{Direction.__args__[0]}", "{Direction.__args__[1]}", ' \
           f'"{Direction.__args__[2]}"]' in flat(text), (
        "the direction section no longer quotes `adapter.py`'s Literal as it stands. It is quoted "
        "so a fourth accepted string cannot arrive without this section moving"
    )


# ------------------------------------------------------------------------------- the roster count

#: A number qualifying the roster's noun, with at most two words between — the grammar
#: `tests/test_cdm_prose_counts.py` measured for this fact, applied to the new documents.
ROSTER_COUNT = re.compile(
    rf"(?<![\w-])(?P<num>{_NUMBER_WORD}|\d{{1,3}})(?:[ -][a-z]+){{0,2}}[ -](?:adapters)(?![\w])",
    re.I,
)


def roster_sites() -> list[tuple[str, str, int]]:
    return [(rel, m.group(0), stated(m.group("num")))
            for rel in DOCS for m in ROSTER_COUNT.finditer(flat(BODIES[rel]))]


def test_the_roster_sweep_bound_something():
    """These documents describe an adapter framework; one of them states how many ship."""
    assert roster_sites(), (
        "none of the three documents states an adapter count. If that is deliberate, this "
        "assertion is what has to be retired deliberately — a sweep with nothing to sweep is a "
        "green check that means nothing"
    )


def test_no_document_states_an_adapter_count_that_is_not_the_roster():
    """One derivation of the roster, every stated count compared with it."""
    shipped = len(shipped_adapters())
    strays = [f"{rel}: {phrase!r} ({count})" for rel, phrase, count in roster_sites()
              if count != shipped]
    assert not strays, (
        f"{len(strays)} site(s) state an adapter count that is not the {shipped} the registry "
        "ships:\n  " + "\n  ".join(strays) +
        "\nThe registry is the authority. A sentence stating the roster needs no exemption here — "
        "it is checked by comparison, today and after the next adapter"
    )


# ---------------------------------------------------------------- the two conformance namespaces


def test_the_harness_checks_the_document_names_are_the_columns_the_harness_reports():
    """§8's first namespace, against `harness._COLUMNS`.

    The count and the names both, because this repository has had the count stay right while a
    name went wrong: `harness.py`'s own docstring said FIVE checks for as long as `roundtrip` had
    existed, and the sixth column was in every report the whole time.
    """
    text = flat(section(ARCHITECTURE, "## 8. Conformance namespaces"))
    columns = harness._COLUMNS
    found = re.search(rf"harness's (?P<n>{_NUMBER_WORD}) checks are the framework's", text)
    assert found, "§8 no longer states how many harness checks there are"
    assert stated(found.group("n")) == len(columns), (
        f"§8 says the harness has {found.group('n')!r} checks and `harness._COLUMNS` has "
        f"{len(columns)}: {columns}"
    )
    quoted = ", ".join(f"`{name}`" for name in columns)
    assert quoted in text, (
        f"§8 no longer lists the harness checks in the order the harness reports them. Expected "
        f"the sequence {quoted!r}"
    )


def test_the_sc_oes_dimensions_the_document_names_are_the_tools_own():
    """§8's second namespace, against `conformance.DIMENSIONS`. Keys AND names.

    The names are part of a published report's consumer-visible surface, so a document that
    renamed one would be describing a tool nobody has.
    """
    text = flat(section(ARCHITECTURE, "## 8. Conformance namespaces"))
    dimensions = conformance.DIMENSIONS
    found = re.search(rf"tool's (?P<n>{_NUMBER_WORD}) dimensions are", text)
    assert found, "§8 no longer states how many SC-OES dimensions there are"
    assert stated(found.group("n")) == len(dimensions), (
        f"§8 says {found.group('n')!r} dimensions and `conformance.DIMENSIONS` has "
        f"{len(dimensions)}"
    )
    missing = [f"{d.key} {d.name!r}" for d in dimensions
               if f'{d.key} "{d.name}"' not in text]
    assert not missing, f"§8 does not name these dimensions as the tool declares them: {missing}"


def test_both_documents_forbid_the_bare_letter():
    """The rule that keeps two letterings from merging, stated where each document discusses both."""
    for rel in (ARCHITECTURE, INTEROPERABILITY):
        assert "never a bare letter" in flat(BODIES[rel]), (
            f"{rel} no longer forbids the bare letter. Two namespaces share the alphabet, and a "
            "document that discusses both without the rule is ambiguous in the way a reader "
            "cannot detect"
        )


# --------------------------------------------------------------------------- the line citations


def test_every_adapter_py_line_the_api_section_cites_holds_what_it_says_it_holds():
    """§1.1's table, against `adapter.py` itself.

    A `file:line` citation is the figure that goes stale silently: the code moves, the number does
    not, and nothing reads either. Each row names an element and a line, so each row is checkable —
    the cited line has to mention the element.
    """
    source = (REPO / "packages" / "cdm" / "synapse_cdm" / "adapter.py").read_text().splitlines()
    rows = table_rows(section(ARCHITECTURE, "## 1. Adapter API v2"))
    checked = 0
    wrong = []
    for row in rows:
        element = row[0].strip("`")
        cite = re.search(r"`adapter\.py:(\d+)`", row[1])
        if not cite:
            continue
        checked += 1
        number = int(cite.group(1))
        if not (1 <= number <= len(source)) or element not in source[number - 1]:
            actual = source[number - 1] if 1 <= number <= len(source) else "<past end of file>"
            wrong.append(f"{element}: cited at adapter.py:{number}, which reads {actual.strip()!r}")
    assert checked == len(rows), (
        f"§1.1's table has {len(rows)} rows and {checked} of them cite an `adapter.py` line. "
        "Every row names one element of the v1 surface and has to say where it is"
    )
    assert not wrong, "these citations no longer point at what they name:\n  " + "\n  ".join(wrong)


def test_the_axis_table_cites_the_line_version_py_declares_each_constant_on():
    """The three Python-constant axes, against `version.py`'s own line numbers."""
    rows = table_rows(section(VERSIONING, "## 2. The axes"))
    seen = {}
    for row in rows:
        cite = re.search(r"`packages/cdm/synapse_cdm/version\.py:(\d+)`", row[-1])
        claim = VERSION_CLAIM.search(row[3])
        if not (cite and claim):
            continue
        seen[claim.group("const")] = int(cite.group(1))
    assert set(seen) == {"SCHEMA_VERSION", "PACKAGE_VERSION", "SC_OES_VERSION"}, (
        f"the axis table gives a version.py line for {sorted(seen)}; all three constants have rows"
    )
    wrong = [f"{const}: table says line {line}, version.py assigns it on {version_py_line(const)}"
             for const, line in seen.items() if line != version_py_line(const)]
    assert not wrong, "\n  ".join(["the axis table's line citations are stale:"] + wrong)


def test_the_axis_table_lists_every_axis_the_version_model_carries():
    """Nine rows, and the six the specification names are all among them.

    The union is the point of the table: the specification enumerates six axes and the tree carries
    six, three overlap, and an implementer who is told about six of the nine finds out about the
    rest from an incident.
    """
    rows = table_rows(section(VERSIONING, "## 2. The axes"))
    spec_names = {"PACKAGE_VERSION", "CDM_SCHEMA_VERSION", "SC_OES_VERSION", "ADAPTER_API_VERSION",
                  "MANIFEST_SCHEMA_VERSION", "EVIDENCE_SCHEMA_VERSION"}
    listed = {cell.strip("`") for row in rows for cell in row[1:2]}
    assert spec_names <= listed, (
        f"the axis table does not carry the specification's names {sorted(spec_names - listed)}. "
        "The mapping from the specification's name to this tree's is the table's whole job"
    )
    tree_names = {row[2].strip("`") for row in rows}
    assert "SCHEMA_VERSION" in tree_names, (
        "the axis table no longer maps `CDM_SCHEMA_VERSION` to this tree's `SCHEMA_VERSION`. The "
        "name is not changed, and the mapping is the one sentence a reader arriving from the "
        "specification needs"
    )
