"""`gates/deploy_record.py`, held to its contract without reaching Cloudflare.

WHY THIS MODULE EXISTS
----------------------
The gate is a protocol act: it shells out to `wrangler` and fetches pages over HTTPS, so it cannot
be a suite member for the reason `PUBLICATION.md` gives — the suite cannot reach Cloudflare and
must not want to. `tests/test_cdm_gate_rosters.py` was written because that arrangement had already
cost this repository once: `gates/wheel_install.py` held three rosters, nothing in the suite read
them, they drifted, and the gate went red on `main` and stayed red because the thing that noticed
was the thing nobody runs.

So the same treatment applies here, and it is the whole of this module's job: **check the part of
the gate that can be wrong while sitting still.** That is more than it sounds, because everything
the gate knows about this repository is parsed out of `PUBLICATION.md` and `wrangler.toml` — the
project name, the custom domain, the recorded deployment ids, the coverage set, the alias holder.
Every one of those is a pattern over prose, and a pattern over prose that stops matching turns a
gate into a green run over nothing.

WHAT IS CHECKED HERE AND WHAT IS NOT
------------------------------------
Checked: that the gate imports without acting; that each of its five parsers finds something in the
record as the record is written today; that the coverage set and the row set are disjoint and
together account for a plausible list; that `reconcile()` refuses both failure directions on
synthetic input; and that the record does not fall back into the shape the gate was written against
— a date range standing in for a set of ids.

Not checked: anything that needs the network. `reconcile()` is exercised against hand-built
`Deployment` values, which is the point — the reconciliation logic is pure, and the only reason it
lived behind a network call was that nobody had separated the two.

The gate is loaded with `exec(compile(...))` and NOT with `spec.loader.exec_module`, for the reason
`tests/test_cdm_gate_rosters.py` records at length: `exec_module` consults and writes
`__pycache__`, a `.pyc` is revalidated on the source's mtime in whole SECONDS plus its size, and
the way you check the assertions below is by mutating this very gate and reverting — which is
exactly the edit pattern a stale `.pyc` defeats.
"""
import pathlib
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "deploy_record.py"
RECORD = REPO / "PUBLICATION.md"


#: The name the gate module is registered under while it is loaded. It has to be registered, and
#: the reason is worth a comment because the failure is obscure and the fix looks like a hack.
#: The gate declares `from __future__ import annotations`, so every annotation is a STRING at class
#: creation time, and `@dataclasses.dataclass` resolves each one to decide whether it is a
#: `ClassVar` or an `InitVar` — through `sys.modules.get(cls.__module__).__dict__`. A module built
#: with `types.ModuleType` and never registered is not in `sys.modules`, so that lookup returns
#: `None` and the decorator raises `AttributeError: 'NoneType' object has no attribute '__dict__'`
#: from inside the standard library, naming nothing about this repository. Registering it is simply
#: what a real `import` would have done; the gate is importable by name, and this module loads it
#: by path only to keep `__pycache__` out of it.
GATE_MODULE_NAME = "_deploy_record_gate"


@pytest.fixture(scope="module")
def gate():
    """The gate module, from its SOURCE — never from bytecode. See this module's docstring."""
    assert GATE_PATH.exists(), (
        "gates/deploy_record.py is gone. It is the only thing that reconciles this repository's "
        "deployment record against Cloudflare's list; a deleted gate is a silent return to the "
        "habit that let fourteen deployments go unrecorded"
    )
    module = types.ModuleType(GATE_MODULE_NAME)
    module.__file__ = str(GATE_PATH)
    sys.modules[GATE_MODULE_NAME] = module
    try:
        exec(compile(GATE_PATH.read_text(), str(GATE_PATH), "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(GATE_MODULE_NAME, None)


def _deployment(gate, short: str, source: str = "abc12345"):
    """A `Deployment` with a chosen 8-character prefix and a full-length id."""
    return gate.Deployment(id=short + "0" * (36 - len(short)), source=source, status="test")


# ------------------------------------------------------------------------- it does not act


def test_the_gate_imports_with_no_side_effects(gate):
    """Importing it must not run wrangler, fetch a page or write anything — only define.

    `main()` is the only thing that acts. The cost of getting this wrong is specific rather than
    theoretical: a contributor who opens the file with a tool that imports it would spend a
    `npx wrangler` invocation and five HTTPS fetches, and a test collection would do it once per
    worker.
    """
    for name in ("main", "reconcile", "check_alias", "wrangler_deployments", "serving_deployment"):
        assert callable(getattr(gate, name)), f"{name} is not callable on the gate module"


# -------------------------------------------------------- the parsers, against today's record


def test_the_gate_reads_the_project_name_from_wrangler_toml(gate):
    """Derived, not typed. A project rename must re-point the gate rather than break it silently."""
    name = gate.project_name()
    assert name and " " not in name, f"project_name() returned {name!r}"
    assert f'name = "{name}"' in (REPO / "wrangler.toml").read_text(), (
        "project_name() did not come from wrangler.toml's `name`, so the gate and the deploy "
        "command could be pointed at different projects"
    )


def test_the_gate_finds_the_ledger_entry_it_reconciles_against(gate):
    """The section anchor, which is the one thing that makes every other parser non-vacuous."""
    section = gate.entry_section()
    assert len(section) > 500, (
        f"ledger entry 8 parsed to {len(section)} characters. The heading matched but the section "
        "is empty or nearly so, which would make every check below pass over nothing"
    )
    assert "| Deployment |" in section, (
        "the deployment table is no longer inside the section the gate anchors on. Either the table "
        "moved out of entry 8 or the next-heading regex is cutting the section short"
    )


def test_the_record_names_every_deployment_individually_or_in_the_pinned_set(gate):
    """Rows and coverage set: both non-empty, disjoint, and together a plausible list.

    The plausibility floor is deliberately low — this module cannot know how many deployments exist
    without asking Cloudflare, and asking is the gate's job. What it can refuse is the degenerate
    shape: a coverage paragraph that has lost its ids and now names none.
    """
    rows, coverage = gate.recorded_rows(), gate.recorded_coverage()
    assert len(rows) >= 5, (
        f"only {len(rows)} deployment(s) have a row of their own: {sorted(rows)}. The table is the "
        "record; a table that has lost its rows accounts for nothing"
    )
    assert len(coverage) >= 5, (
        f"the pinned coverage set names {len(coverage)} deployment(s): {sorted(coverage)}. It is "
        "the retrospective account of the deployments that predate the record, and it replaced a "
        "date range precisely so that it could be compared to a list"
    )
    # The set is CLOSED, and its size is spelled out in the marker the gate anchors on, so the
    # word and the ids can disagree with nothing noticing. That is a stale count one layer in —
    # the shape `packages/cdm/synapse_cdm/README.md`'s sweep rule 8 exists for — so the two are
    # compared. A deployment that happens from now on gets a ROW; nothing joins this set.
    words = {"eleven": 11, "twelve": 12, "thirteen": 13}
    spelled = [word for word in words if word in gate.COVERAGE_MARKER]
    assert len(spelled) == 1, (
        f"the coverage marker {gate.COVERAGE_MARKER!r} spells {spelled} number words. It must "
        "spell exactly one, because that word is the only statement of the set's size"
    )
    assert words[spelled[0]] == len(coverage), (
        f"the coverage paragraph says {spelled[0]!r} and names {len(coverage)} ids: "
        f"{sorted(coverage)}. The set is closed — a deployment made from now on gets a row of its "
        "own — so a disagreement here is either an id added to a closed set or a word left behind"
    )
    assert not (rows & coverage), (
        f"{sorted(rows & coverage)} are accounted for twice — once as a row and once in the "
        "coverage set. Two accounts of one deployment is two things to keep in agreement"
    )


def test_the_coverage_set_is_a_set_of_ids_and_not_a_date_range(gate):
    """The exact shape the gate was written against, forbidden by substring.

    The table's first version carried `| eleven earlier | 2026-08-22 → 2026-08-25 | all resolve |`.
    That row cannot be wrong about an id it never mentions, so nothing could check it, and a
    deployment landing inside the range would have been covered by it silently. The row was also
    wrong in its own terms — one of the eleven happened ninety-two seconds AFTER the row above it —
    which is recorded in the entry.
    """
    section = gate.entry_section()
    assert "| eleven earlier |" not in section, (
        "ledger entry 8's table has gone back to accounting for deployments by a date range. That "
        "is the shape gates/deploy_record.py cannot check: name the ids in the coverage paragraph"
    )


def test_the_record_names_the_alias_holder_and_the_domain(gate):
    """Both halves of the claim the gate pins, and it is the claim that went false."""
    holder = gate.recorded_alias_holder()
    assert len(holder) == 8 and all(c in "0123456789abcdef" for c in holder), (
        f"the alias paragraph yielded {holder!r}, which is not an 8-character deployment prefix"
    )
    assert holder in gate.recorded_rows(), (
        f"the record says `{holder}` serves the custom domain and gives it no row of its own. The "
        "deployment that is being served is the one that most needs a row"
    )
    domain = gate.custom_domain()
    assert "." in domain and not domain.endswith(".pages.dev"), (
        f"custom_domain() returned {domain!r}. It must be the custom hostname, not a pages.dev "
        "preview URL — comparing a deployment against its own preview URL is a tautology"
    )
    assert domain in RECORD.read_text(), f"{domain!r} does not occur in the record it was read from"


# -------------------------------------------------- the reconciliation, on synthetic input


def test_reconcile_passes_when_every_listed_deployment_is_recorded(gate):
    """The baseline. Built from the record's own ids, so it passes for the right reason."""
    known = gate.recorded_rows() | gate.recorded_coverage()
    result = gate.reconcile([_deployment(gate, short) for short in sorted(known)])
    assert result["listed"] == len(known), result
    assert result["rows"] + result["coverage"] == len(known), (
        f"reconcile() accounted for {result['rows']} + {result['coverage']} of {len(known)}"
    )


def test_reconcile_refuses_a_deployment_the_record_cannot_name(gate):
    """Direction one: the defect the gate exists for.

    Sixteen deployments, two recorded. A gate that cannot fail on this is not a gate.
    """
    known = sorted(gate.recorded_rows() | gate.recorded_coverage())
    listed = [_deployment(gate, s) for s in known] + [_deployment(gate, "deadbeef")]
    with pytest.raises(gate.Finding) as raised:
        gate.reconcile(listed)
    assert "deadbeef" in str(raised.value), (
        f"the refusal does not name the offending deployment:\n{raised.value}"
    )
    assert "cannot name" in str(raised.value)


def test_reconcile_refuses_an_id_the_project_does_not_list(gate):
    """Direction two, and it is the one that stops the gate being satisfiable by typing rows.

    A record that may add ids freely can always be made to pass. An id in the table that Cloudflare
    has never held is either a typo — in which case the row accounts for nothing — or a deleted
    deployment, which is a fact the entry should state rather than leave as a row that no longer
    resolves.
    """
    known = sorted(gate.recorded_rows() | gate.recorded_coverage())
    with pytest.raises(gate.Finding) as raised:
        gate.reconcile([_deployment(gate, s) for s in known[1:]])
    assert known[0] in str(raised.value), (
        f"the refusal does not name the id that failed to resolve:\n{raised.value}"
    )
    assert "does not list" in str(raised.value)


def test_reconcile_refuses_a_deployment_accounted_for_twice(gate):
    """A row AND a coverage entry for one deployment is two things to keep in agreement.

    This is not pedantry about tidiness: the coverage set exists to say "these were never written
    down individually", so a deployment in both is a contradiction about its own history.
    """
    duplicated = sorted(gate.recorded_rows())[0]
    section = gate.entry_section()
    marker = gate.COVERAGE_MARKER
    paragraph = section[section.index(marker):].split("\n\n", 1)[0]
    assert duplicated not in paragraph, (
        f"`{duplicated}` has a row AND appears in the coverage paragraph. The gate's own overlap "
        "check will refuse this; it is asserted here so the failure arrives from pytest"
    )


def test_the_alias_probe_is_not_a_tautology(gate):
    """`serving_deployment` must require a DIFFERENCE from the previous deployment, not just a match.

    Asserted against the source rather than by running it, because running it needs the network.
    The property: a check that only compared the live site to one deployment would pass if every
    deployment served identical bytes — which is exactly the state a project has before its second
    deploy, and exactly when the claim means least. `PUBLICATION.md`'s flip measurement had this
    half and said why; the gate must not lose it.
    """
    source = GATE_PATH.read_text()
    for fragment in ("differing_from_previous", "previous.preview", "byte-identical to BOTH"):
        assert fragment in source, (
            f"gates/deploy_record.py no longer carries {fragment!r}, so the alias probe may have "
            "lost the half that makes it a measurement: identical to the current deployment AND "
            "different from the one before it"
        )


def test_the_gate_does_not_read_a_credential_out_of_a_config_file(gate):
    """It shells out to wrangler, and that decision is load-bearing rather than stylistic.

    The first draft read wrangler's OAuth token from its config file and called the REST API. The
    token had expired four hours earlier; the API answered `9109 Invalid access token` while
    `wrangler` itself worked, because wrangler refreshes on use. A gate that manages credentials
    reports an authentication failure as a deployment finding.
    """
    source = GATE_PATH.read_text()
    for forbidden in ("oauth_token", "CLOUDFLARE_API_TOKEN", "api.cloudflare.com"):
        assert forbidden not in source, (
            f"gates/deploy_record.py mentions {forbidden!r}. The list comes from `npx wrangler`, "
            "which refreshes its own token; a gate that reaches for the credential directly fails "
            "with an auth error dressed up as a reconciliation finding"
        )
    assert '"npx", "wrangler"' in source, (
        "the gate no longer invokes wrangler, so it is getting the deployment list from somewhere "
        "that is not the tool the deploy itself uses"
    )


def test_the_gate_is_not_a_suite_member_and_says_so(gate):
    """A protocol act nobody can run is a protocol act nobody runs.

    The same assertion `tests/test_cdm_commit_message.py` makes about its own gate: the usage block
    has to be in the file, because re-running a protocol act should be copying and not designing.
    """
    doc = gate.__doc__ or ""
    assert "python gates/deploy_record.py" in doc, (
        "the gate's docstring no longer shows how to run it. `PUBLICATION.md` calls re-witnessing a "
        "protocol act on the grounds that the probes are written out in full"
    )
    assert "--mutation-check" in doc, (
        "the gate no longer documents its mutation check. A gate nobody has seen fail is a gate "
        "nobody has seen"
    )


# ==================== the served-version witness, over a saved page and never over the network


#: A saved fragment of what the site serves, in the shape the built page actually has: the version
#: is inside a `<code>` element and the sentence wraps across a newline, because that is what
#: Docusaurus emitted for the source paragraph and a parser written against the .mdx source would
#: have missed it. Held here as bytes rather than fetched, on this module's own rule — the gate is
#: a protocol act and the suite must pass for an outsider with no network.
#: THE FIXTURE STATES NO COUNT, AND THAT IS A RULE RATHER THAN AN OVERSIGHT. The page it stands
#: for opens with a clause counting the adapters that shipped without a schema change; reproducing
#: it here would make this module a live site of that figure, which is sweep rule 1's own sub-rule
#: — a synthetic fixture is written to LOOK like the thing it stands for, and that is exactly what
#: makes it indistinguishable from a real claim to a grep. Commit 90f65f7 made the same repair to
#: two fixtures in `gates/bump_derivation.py`, and the repair is to stop stating the fact rather
#: than to exempt the file. The clause is elided; the version sentence and the decoy semvers, which
#: are what this parser has to get right, are verbatim.
SERVED_PAGE = (
    "and the two are allowed to diverge: adapters have shipped without a single\n"
    "change to <code>schema_version</code>, and each of them would have been a release of the "
    "package. They were\nboth <code>1.0.0</code> at first release, by coincidence of two first "
    "releases, and they parted at 1.1.0: the\npackage is at <code>1.5.0</code> and the schema "
    "stays at <code>1.0.0</code>."
)


def test_the_served_version_parser_reads_the_page_the_site_actually_serves(gate):
    """The witness's parser, over the saved page. It must find the PACKAGE version and not another.

    The trap this pins is specific and the page is full of it: that fragment carries `1.0.0` three
    times and `1.1.0` once, and only one of the four is the distribution's version. A parser keyed
    on "the first semver on the page" would read the schema's, agree with nothing, and disagree
    with `version.py` forever — which is the failure mode of a witness that cannot fail a build:
    nobody would find out from a red run.
    """
    assert gate.served_version(SERVED_PAGE) == "1.5.0", (
        "served_version() no longer reads the package version out of the served changelog. The "
        "sentence is 'the package is at <code>X.Y.Z</code>' with the number inside a code element; "
        "if the page's markup changed, re-anchor the pattern rather than loosening it to any semver"
    )


def test_the_served_version_parser_returns_None_rather_than_guessing(gate):
    """A page that states no version is a reading of `None`, not a reading of whatever is nearby.

    The two directions matter differently. A parser that returned a wrong version would make the
    witness report a confident disagreement that is really a parse failure; one that returns `None`
    reports that it could not read the page, which is the truth and is what the gate prints.
    """
    assert gate.served_version("<p>no version here</p>") is None
    assert gate.served_version("") is None
    # The schema's version in the same sentence shape must NOT satisfy it.
    assert gate.served_version("the schema stays at <code>1.0.0</code>") is None


def test_the_witness_compares_against_version_py_read_the_same_way_bump_derivation_reads_it(gate):
    """The tree half of the comparison, and it is read from the assignment rather than imported.

    `gates/bump_derivation.py` reads `PACKAGE_VERSION` out of the file's own assignment for the
    reason this gate has too: both run standalone, and importing the package would make the number
    depend on what happens to be on the path.
    """
    declared = gate.declared_package_version()
    assert declared.count(".") == 2, f"declared_package_version() returned {declared!r}"
    assert f'PACKAGE_VERSION = "{declared}"' in gate.VERSION_PY.read_text()


def test_the_witness_cannot_fail_the_gate_and_the_file_says_why(gate):
    """The scope of it, asserted rather than remembered.

    A witness that acquired an exit code would be red for every hour between a release and its
    deploy — a state the tree cannot fix — and `PUBLICATION.md`'s own terms table is what this
    rests on: what the site serves is protocol-gated, and this gate is the protocol.
    """
    doc = gate.check_served_version.__doc__ or ""
    assert "WITNESS, NOT AN ASSERTION" in doc, (
        "check_served_version()'s docstring no longer states that it cannot fail the gate. If it "
        "has become an assertion, that is a decision about what a red gate means and it belongs in "
        "PUBLICATION.md's terms table, not in a docstring nobody re-read"
    )
    source = GATE_PATH.read_text()
    assert "1 witness, which cannot fail" in source, (
        "the gate's own output no longer distinguishes its witness from its checks. A reader "
        "counting 'checks' has to be able to tell which lines the exit code covers"
    )


# ==================== the prose count, against the gate's own enumeration
#
# WHY THIS EXISTS, AND IT IS AN INCIDENT RATHER THAN A PRINCIPLE
# --------------------------------------------------------------
# Entry 8 said "Sixteen deployments" for a day and a half after its own table stopped listing that
# many. Commit `7544880` wrote the sentence over five rows and eleven named ids, which was true;
# commit `1fc35e8` appended the `222a55be` row for the 1.2.1 release and left the sentence alone.
# The gate went green throughout and was right to: its predicate is "0 unaccounted for", every
# deployment WAS accounted for, and the appended row is what kept it so. **A spelled number in a
# sentence is not a deployment**, so nothing compared the prose to the table above it.
#
# That is the same gap in the same shape as the two the repository has already paid for — the
# gate's rosters that drifted because nothing read them, and the header count that stayed at seven
# while the record reached twelve pins. The move is the one `synapse_cdm/README.md`'s sweep rule 9
# settled on: check the CONSEQUENCE, not the intent. A stale count's consequence is that two
# statements of one fact disagree, and that is countable without reading anything.
#
# WHAT IS COUNTED IS THE FIGURE WITH ITS BASIS, NEVER THE BARE NUMERAL
# --------------------------------------------------------------------
# Rule 9's carrier rule, and here it is forced rather than stylistic. The entry is dense with
# spelled numbers that are other claims — "the eleven named below" and "The eleven earlier
# deployments" are the same eleven twice, and "two" is the recorded-before count in a sentence this
# module has no business ruling. So each figure is pinned as the phrase that carries its basis.
#
# EXACTLY ONCE, AND THE SUPERSEDED FIGURE IS OUT OF SCOPE BY CONSTRUCTION
# -----------------------------------------------------------------------
# Zero means the enumeration moved and the prose did not — the recorded incident. More than one
# means a second site in the entry now carries the live figure, which is the carrier pattern that
# cost the KLV 2 repair a first draft: a correction note re-quoting the figure it corrected leaves
# a copy the guard passes on after the live one is deleted.
#
# The date-scoped original is deliberately NOT constrained. Entry 8 is amended in the KLV 11 form —
# the false sentence stands, dated, with the amendment beneath it — so the superseded count is
# still spelled in the entry, twice, and must be. This guard rules the LIVE figure only. That is a
# real limit and it is the honest one: requiring the superseded figure to be absent would forbid
# the amendment form, and recognising which of two spellings is the live one is a reading of the
# prose rather than a derivation from the tree. See rule 9, where the briefed form of exactly that
# check was specced, measured against the tracked record, and refused.

#: Spelled out because the entry spells them out, and an unknown word must be a loud failure rather
#: than a silent miss. Deliberately not a general parser, for `tests/test_cdm_pin_header.py`'s
#: reason: the vocabulary is the one this record uses.
NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
    9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    21: "twenty-one", 22: "twenty-two", 23: "twenty-three", 24: "twenty-four", 25: "twenty-five",
}


def _spell(count: int) -> str:
    """The number word this record would write, or a failure naming the number it could not spell."""
    assert count in NUMBER_WORDS, (
        f"the enumeration derives {count} and this module cannot spell it. Extend NUMBER_WORDS "
        "deliberately rather than letting an unspellable count read as a figure nobody stated"
    )
    return NUMBER_WORDS[count]


def live_figures(rows: set[str], coverage: set[str]) -> tuple[str, ...]:
    """The entry's live count and its two parts, each figure WITH ITS BASIS.

    Derived from the gate's own two sets and nothing else, so the guard and the reconciliation
    cannot come apart: the total is the union because an id in both sets is one deployment, which
    is the double-accounting `reconcile()` already refuses in its own direction.
    """
    return (
        f"{_spell(len(set(rows) | set(coverage)))} deployments",
        f"{_spell(len(rows))} carrying a row",
        f"{_spell(len(coverage))} covered by the naming paragraph below",
    )


def figure_occurrences(section_text: str, figures: tuple[str, ...]) -> dict[str, int]:
    """How many times each figure occurs in the entry. The predicate, over text.

    A function rather than an inline count so the vacuity checks below can run it against mutated
    copies of the real entry without writing to the tree — the property the KLV 2 guard has, and
    for the same reason.
    """
    flat = " ".join(section_text.split()).lower()
    return {figure: flat.count(figure.lower()) for figure in figures}


def test_the_entry_states_the_deployment_count_its_own_enumeration_derives(gate):
    """The guard, and the one assertion the incident would have failed.

    Every figure exactly once, over the entry as it stands. Run against the tree, so this is also
    the module's non-vacuity check in the direction that matters most: if the entry stopped
    carrying these phrases at all, this fails rather than passing over nothing.
    """
    figures = live_figures(gate.recorded_rows(), gate.recorded_coverage())
    for figure, found in figure_occurrences(gate.entry_section(), figures).items():
        assert found == 1, (
            f"{figure!r} occurs {found} times in ledger entry 8 and must occur exactly ONCE.\n"
            "  ZERO means the enumeration moved and the sentence did not — the 2026-08-28 finding, "
            "where a row was appended for the 1.2.1 deploy and the count above the table stayed "
            "where the previous round left it. Amend the entry; do not rewrite the dated claim.\n"
            "  MORE THAN ONE means a second site in the entry now spells the live figure, which is "
            "sweep rule 9's carrier pattern: describe a superseded figure, never re-quote it, and "
            "state each live figure exactly once, with its basis"
        )


def test_the_deployment_count_guard_is_not_vacuous_in_either_direction(gate):
    """Both failure directions, mutated on the real entry, because they mean opposite things.

    A guard whose real input happens to satisfy it is indistinguishable from one that asserts
    nothing, and three substring counts is exactly the shape that goes quietly green.
    """
    section = gate.entry_section()
    figures = live_figures(gate.recorded_rows(), gate.recorded_coverage())
    total = figures[0]

    dropped = " ".join(section.split()).replace(total, "", 1)
    assert figure_occurrences(dropped, (total,))[total] == 0, (
        "deleting the live count from the entry left the guard's predicate satisfied. The guard "
        "cannot see the staleness it exists to refuse")

    requoted = " ".join(section.split()) + f" ... which superseded the {total} this entry states."
    assert figure_occurrences(requoted, (total,))[total] == 2, (
        "re-quoting the live count did not raise its occurrence count, so a correction note could "
        "carry a second copy and the guard would pass on it after the live one was deleted")


def test_the_guard_refuses_the_shape_the_incident_ACTUALLY_HAD(gate):
    """The recorded failure, as a fixture: the enumeration grows and the prose count does not.

    This is the fixture that makes the guard a witness rather than a plausible check. It does not
    invent a defect — it replays the one in the history. A deployment id is added to the row set,
    exactly as commit `1fc35e8` added `222a55be`, and the entry's text is left untouched. The
    derived total moves; the sentence does not; the guard must go red.
    """
    section = gate.entry_section()
    rows, coverage = set(gate.recorded_rows()), set(gate.recorded_coverage())
    assert figure_occurrences(section, live_figures(rows, coverage))[
        live_figures(rows, coverage)[0]] == 1, "the entry does not state its live count today"

    grown = rows | {"deadbeef"}
    stale = live_figures(grown, coverage)
    assert figure_occurrences(section, stale)[stale[0]] == 0, (
        "a deployment was added to the enumeration, the entry's prose was left exactly as it is, "
        "and the guard still found the total it states. That is the 2026-08-28 incident passing")
    assert figure_occurrences(section, stale)[stale[1]] == 0, (
        "the row count moved and the guard still found the part-figure the entry states")


def test_the_number_vocabulary_refuses_a_count_it_cannot_spell(gate):
    """An unspellable count must fail loudly, not read as a figure nobody wrote.

    `tests/test_cdm_pin_header.py` states the rule this borrows: a word the module does not know is
    a failure rather than a silent zero. The inverse direction has the same hazard — a count past
    the end of the table would otherwise raise a `KeyError` naming nothing about this record.
    """
    with pytest.raises(AssertionError, match="cannot spell it"):
        _spell(max(NUMBER_WORDS) + 1)
    assert _spell(len(set(gate.recorded_rows()) | set(gate.recorded_coverage()))) in {
        word for word in NUMBER_WORDS.values()}
