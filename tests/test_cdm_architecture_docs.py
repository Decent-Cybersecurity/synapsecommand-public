"""The three architecture documents, against the tree they describe.

WHY THIS EXISTS
---------------
`ARCHITECTURE.md`, `VERSIONING.md` and `INTEROPERABILITY.md` are prose, and prose with figures in
it is the thing this repository has repaired most often: a count that was right when it was typed,
a line citation that survived the code moving under it, a version number that stopped being the
version. Every one of those was found by a sweep and none of them by a reader.

So the documents STATE and this module DERIVES. Nothing here is a second copy of a figure — each
check reads the authority (`version.py`'s constants, `adapter.roster()`, `harness._COLUMNS`,
`conformance.DIMENSIONS`, the workflow files under `.github/workflows/`, the documents' own
tables) and compares. A figure in one of the three documents that no check below reaches is a gap,
and the two sweep-bound assertions are what stop this module from passing by finding nothing.

THE ONE THING IT DOES NOT CHECK, NAMED SO NOBODY ASSUMES IT DOES
----------------------------------------------------------------
It does not judge the documents' ARGUMENTS. Whether the residual policy is right, whether six
directions are the correct six, whether a rule is enforced where the document says it is enforced —
those are a reviewer's, and the review is where they were settled. This module holds the figures.
"""
import ast
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
#: The six constants `version.py` declares as axes, every one a row of VERSIONING.md §2's table.
VERSION_CONSTANTS = ("SCHEMA_VERSION", "PACKAGE_VERSION", "SC_OES_VERSION",
                     "ADAPTER_API_VERSION", "MANIFEST_SCHEMA_VERSION", "EVIDENCE_SCHEMA_VERSION")

#: The three the DOCUMENT-WIDE sweep below reads. Not the six: VERSIONING.md §2's dated corrections
#: legitimately say "`MANIFEST_SCHEMA_VERSION` reads `1.1.0`" about the day they were written and
#: are left standing by rule, so a sweep over those three names would read history as a stale
#: claim. The six are held where they are stated as current — the axis table — by the
#: table-scoped `TABLE_CLAIM` test further down (audit remediation F09, 2026-09-20).
VERSION_CLAIM = re.compile(
    r"`(?P<const>SCHEMA_VERSION|PACKAGE_VERSION|SC_OES_VERSION)`\s*"
    r"(?:is|reads|=|at)\s*`(?P<value>\d+\.\d+\.\d+)`"
)

TABLE_CLAIM = re.compile(
    r"`(?P<const>" + "|".join(VERSION_CONSTANTS) + r")`\s*is\s*`(?P<value>\d+\.\d+\.\d+)`"
)


def version_claims() -> list[tuple[str, str, str]]:
    return [(rel, m.group("const"), m.group("value"))
            for rel in DOCS for m in VERSION_CLAIM.finditer(flat(BODIES[rel]))]


def test_the_version_sweep_bound_something():
    """Before the comparison: a sweep that matches nothing passes for the wrong reason.

    Three constants, and the version model has to state all three somewhere or it is not a
    statement of this package's version axes. (The other three are held in the axis table alone;
    see `VERSION_CLAIM`'s comment.)
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
    (ARCHITECTURE, "### 3.4 Claim status — seven statuses",
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


def adapter_members() -> dict[str, str]:
    """Every member the `Adapter` class body declares, by name, as `attribute` or `method`.

    Read with `ast` rather than `dir(adapter.Adapter)` so that an inherited name (`ABC`'s, or
    `object`'s) cannot satisfy a row that claims the member is this class's own.
    """
    tree = ast.parse((REPO / "packages" / "cdm" / "synapse_cdm" / "adapter.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Adapter":
            members = {}
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    members[item.name] = "method"
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    members[item.target.id] = "attribute"
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            members[target.id] = "attribute"
            return members
    raise AssertionError("adapter.py no longer declares a top-level class named Adapter")


def test_every_element_the_api_section_lists_is_a_member_of_adapter_of_the_kind_it_states():
    """§1.1's table, against the `Adapter` class body itself.

    Until audit remediation F09 (2026-09-20) each row cited an `adapter.py` LINE, and every
    insertion above a cited member moved every number below it — twice in the document's own dated
    corrections and once more in F02. A line is a figure that goes stale when nothing about the
    member changed. What a row has to say is WHERE the member is in a form that survives the file
    being edited: the class it belongs to and whether it is a class attribute or a method. Both are
    derived here from the AST, so a renamed or removed member reds this test and a moved one does
    not. No row may cite a line any more.
    """
    members = adapter_members()
    rows = table_rows(section(ARCHITECTURE, "## 1. Adapter API v2"))
    assert rows, "§1.1's table is gone"
    wrong = []
    for row in rows:
        element = row[0].strip("`")
        where = row[1]
        if re.search(r"adapter\.py:\d+", where):
            wrong.append(f"{element}: the `where` cell cites a line ({where!r}); cite the kind")
            continue
        if "`adapter.py`" not in where or "`Adapter`" not in where:
            wrong.append(f"{element}: the `where` cell {where!r} names neither the file nor the class")
            continue
        stated_kind = ("method" if "method" in where
                       else "attribute" if "class attribute" in where else None)
        if stated_kind is None:
            wrong.append(f"{element}: the `where` cell {where!r} states neither kind")
        elif element not in members:
            wrong.append(f"{element}: not a member the Adapter class body declares "
                         f"(it declares {sorted(members)})")
        elif members[element] != stated_kind:
            wrong.append(f"{element}: the table says {stated_kind}, adapter.py declares a "
                         f"{members[element]}")
    assert not wrong, "§1.1's table disagrees with adapter.py:\n  " + "\n  ".join(wrong)


def test_the_api_section_gate_can_fail():
    """The AST reader sees what the gate compares against, or the gate above passes vacuously."""
    members = adapter_members()
    assert members.get("to_cdm") == "method" and members.get("name") == "attribute", members
    assert "not_a_member_of_adapter" not in members


def test_the_axis_table_cites_version_py_by_constant_and_every_constant_is_declared_there():
    """The six Python-constant axes, against `version.py`'s own top-level assignments.

    Until audit remediation F09 (2026-09-20) each row cited a `version.py` LINE and this test held
    the number; the numbers moved at every insertion above them — the document's own dated note
    records four readings for one constant in four days — and a release had to re-point them. A
    row now cites the file and names the constant's top-level assignment; the constant must be
    assigned at the top level of `version.py` (a rename reds this), the row may cite no line, and
    the reading in the row's `version today` cell must be the constant's value — for all six,
    table-scoped, so that a dated correction elsewhere in the document is not read as a claim.
    """
    rows = table_rows(section(VERSIONING, "## 2. The axes"))
    seen = {}
    wrong = []
    for row in rows:
        claim = TABLE_CLAIM.search(row[3])
        if not claim:
            continue
        const = claim.group("const")
        seen[const] = row[-1]
        if claim.group("value") != getattr(version, const):
            wrong.append(f"{const}: the table says {claim.group('value')!r}, version.py says "
                         f"{getattr(version, const)!r}")
        if re.search(r"version\.py:\d+", row[-1]):
            wrong.append(f"{const}: the `authored in` cell cites a line ({row[-1]!r})")
        elif "`packages/cdm/synapse_cdm/version.py`" not in row[-1] or f"`{const}`" not in row[-1]:
            wrong.append(f"{const}: the `authored in` cell {row[-1]!r} names neither the file "
                         "nor the constant")
        else:
            try:
                version_py_line(const)
            except AssertionError as failure:
                wrong.append(str(failure))
    assert set(seen) == set(VERSION_CONSTANTS), (
        f"the axis table states a reading for {sorted(seen)}; all six constants have rows"
    )
    assert not wrong, "\n  ".join(["the axis table's citations are wrong:"] + wrong)


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


# ------------------------------------------------------------------------------ §7, the CI layout
#
# Added 2026-09-16. ARCHITECTURE.md §7 said "`.github/workflows/` holds exactly one workflow" for
# nine days after the second one landed, cited `publish.yml`'s `on:` block at a line it had moved
# off, and tabled two jobs that were steps of another — and this module, which the document's own
# preamble says "derives every figure the three documents state from the tree", had no check that
# reached §7. The section was rewritten on the same date; these are the checks that were missing,
# so the rewrite cannot go stale the way the paragraph it replaced did. The authority is the
# workflow files themselves, read as text: the dependency budget of this repository is two packages
# and neither is a YAML parser, and the shape of an `on:` block is fixed enough to scan.

WORKFLOWS = REPO / ".github" / "workflows"

#: The section's opening paragraph, which is the inventory the checks below read.
INVENTORY_LEAD = "**What exists today"

#: How §7 may spell each event an `on:` block can declare. The prose writes "pull requests" where
#: the file writes `pull_request:`; a check that demanded the key's spelling would be checking
#: typography, and one that accepted any word would be checking nothing.
EVENT_SPELLINGS = {
    "push": r"push",
    "pull_request": r"pull[ _-]request",
    "workflow_dispatch": r"workflow_dispatch",
    "schedule": r"schedule",
}


def workflow_triggers(path: pathlib.Path) -> dict[str, list[str]]:
    """One workflow's `on:` block: each event it declares, with that event's branch or tag patterns.

    The block's shape is the one GitHub documents — `on:` at column 0, events two spaces in,
    `branches:` or `tags:` four in, patterns six in — and the scanner stops at the next top-level
    key. Anything else under an event (`inputs:`, a `cron:` item) is not a filter and is ignored.
    An event this module has no spelling for is refused rather than read as nothing.
    """
    events: dict[str, list[str]] = {}
    inside = False
    current = None
    filter_key = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not inside:
            inside = raw == "on:"
            continue
        if not raw.startswith(" "):
            break
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 2:
            assert re.fullmatch(r"[a-z_]+:", stripped), f"{path.name}: unexpected `on:` line {raw!r}"
            current = stripped[:-1]
            assert current in EVENT_SPELLINGS, (
                f"{path.name} triggers on `{current}`, an event this module has no spelling for; "
                "add it to EVENT_SPELLINGS rather than letting the check skip it")
            events[current] = []
            filter_key = None
        elif indent == 4:
            filter_key = stripped if stripped in ("branches:", "tags:") else None
        elif indent == 6 and filter_key and stripped.startswith("- "):
            events[current].append(stripped[2:].strip().strip("'\""))
    assert events, f"{path.name} declares no `on:` block this scanner recognises"
    return events


def ci_section_clauses() -> dict[str, str]:
    """§7's inventory paragraph, cut into the clause each workflow file gets.

    A clause runs from the file's backticked name to the next file's; the last runs to the end
    of the paragraph. Each file is named once in that paragraph, or the cut is ambiguous.
    """
    paragraphs = [p for p in re.split(r"\n\s*\n", section(ARCHITECTURE, "## 7. CI layout")) if p.strip()]
    leads = [p for p in paragraphs if p.startswith(INVENTORY_LEAD)]
    assert len(leads) == 1, (
        f"§7 has {len(leads)} paragraph(s) opening {INVENTORY_LEAD!r}; the inventory of workflow "
        "files is read from that one paragraph")
    inventory = flat(leads[0])
    names = list(re.finditer(r"`([a-z-]+\.yml)`", inventory))
    clauses: dict[str, str] = {}
    for index, match in enumerate(names):
        end = names[index + 1].start() if index + 1 < len(names) else len(inventory)
        assert match.group(1) not in clauses, f"§7's inventory names `{match.group(1)}` twice"
        clauses[match.group(1)] = inventory[match.start():end]
    return clauses


def ci_job_ids() -> list[str]:
    """`ci.yml`'s job ids, in file order: the keys two spaces in under its one `jobs:` line."""
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert text.count("\njobs:\n") == 1, "ci.yml does not carry exactly one `jobs:` block"
    ids = re.findall(r"(?m)^  ([a-z][a-z0-9-]*):$", text[text.index("\njobs:\n"):])
    assert ids, "ci.yml's `jobs:` block declares no job this scanner recognises"
    return ids


def test_the_ci_section_names_every_workflow_file_the_tree_holds_and_no_other():
    """The inventory, against `ls .github/workflows`. "Exactly one" was wrong by four."""
    in_tree = sorted(p.name for p in WORKFLOWS.glob("*.yml"))
    assert len(in_tree) >= 2, (
        f".github/workflows/ holds {in_tree}; §7 is about the relationship between the release "
        "pipeline and the workflow that can fail on a branch, and needs both to be about anything")
    named = sorted(ci_section_clauses())
    assert named == in_tree, (
        f"§7's inventory names {named} and .github/workflows/ holds {in_tree}. Every file gets a "
        "clause and no clause names a file that is not there")


def test_the_ci_section_states_each_workflows_triggers_as_its_on_block_declares_them():
    """Each clause, against its file's `on:` block, in both directions.

    Every declared event is mentioned in the clause and no undeclared one is; every branch or tag
    pattern the file filters on appears in the clause, backticked. The second half is what catches
    "on the same pushes and pull requests" said of a workflow whose pull-request trigger carries a
    branch filter the workflow it is compared with does not.
    """
    wrong = []
    checked = 0
    for name, clause in ci_section_clauses().items():
        declared = workflow_triggers(WORKFLOWS / name)
        for event, spelling in EVENT_SPELLINGS.items():
            mentioned = re.search(spelling, clause) is not None
            checked += 1
            if (event in declared) and not mentioned:
                wrong.append(f"{name} triggers on `{event}` and its clause does not say so: {clause!r}")
            if mentioned and event not in declared:
                wrong.append(f"{name}'s clause mentions `{event}` and the file does not declare it: {clause!r}")
        for event, patterns in declared.items():
            for pattern in patterns:
                checked += 1
                if f"`{pattern}`" not in clause:
                    wrong.append(f"{name} filters `{event}` on `{pattern}` and its clause does not name it: {clause!r}")
    assert checked, "no clause and no `on:` block was compared; the section or the scanner is empty"
    assert not wrong, "§7's trigger statements have parted from the workflow files:\n  " + "\n  ".join(wrong)


def test_the_ci_job_table_is_ci_ymls_job_set_in_its_order():
    """The table's first column, against `ci.yml`'s `jobs:` keys, as a list and not a set.

    The P1 design tabled `gates` and `manifests` as jobs; the file made them steps of `suite`,
    and for nine days the table said otherwise while a `docs-audit` job it never mentioned ran
    on every push. The section now says "the table is the job set as it stands", and this is
    what makes that sentence checkable.
    """
    tabled = [row[0].strip("`") for row in table_rows(section(ARCHITECTURE, "## 7. CI layout"))]
    declared = ci_job_ids()
    assert tabled == declared, (
        f"§7's job table lists {tabled}; ci.yml declares {declared}, in that order. A job the file "
        "has and the table lacks is a control a reader is not told about, and the reverse is a "
        "control that does not exist")


def test_the_suite_rows_interpreters_are_ci_ymls_matrix_and_pyprojects_classifiers():
    """The one figure the job table states, against the two files it is a reading of.

    The `suite` row names the interpreters the job runs on and says they are "every interpreter
    `pyproject.toml` declares"; the row is compared with `ci.yml`'s matrix and the matrix with the
    classifiers, so neither half of the sentence can drift on its own.
    """
    rows = {row[0].strip("`"): row for row in table_rows(section(ARCHITECTURE, "## 7. CI layout"))}
    assert "suite" in rows, "§7's job table has no `suite` row"
    stated = re.findall(r"\b3\.\d{1,2}\b", rows["suite"][2])
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    suite_block = re.search(r"(?ms)^  suite:$.*?(?=^  [a-z][a-z0-9-]*:$)", text)
    assert suite_block, "ci.yml has no `suite` job followed by another job"
    matrix_line = re.search(r"^\s+python:\s*\[(.*)\]\s*$", suite_block.group(0), re.M)
    assert matrix_line, "ci.yml's `suite` job carries no `python: [...]` matrix"
    matrix = re.findall(r"\d+\.\d+", matrix_line.group(1))
    classifiers = re.findall(
        r'"Programming Language :: Python :: (\d+\.\d+)"',
        (REPO / "packages" / "cdm" / "pyproject.toml").read_text(encoding="utf-8"))
    assert matrix and classifiers, "the matrix or the classifier list is empty; nothing was compared"
    assert stated == matrix, (
        f"§7's `suite` row names interpreters {stated}; ci.yml's matrix runs {matrix}")
    assert matrix == classifiers, (
        f"ci.yml's matrix runs {matrix}; pyproject.toml's classifiers declare {classifiers}. The "
        "row says the job runs every declared interpreter, which is only true while these agree")
