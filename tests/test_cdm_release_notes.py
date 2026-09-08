"""`synapse release-notes` — §52's ten fields, and the refusal that makes them mean something.

WHAT IS WORTH TESTING HERE AND WHAT IS NOT
-------------------------------------------
A renderer's output is prose, and asserting on prose produces tests that break when a sentence is
improved and pass when the derivation is wrong. So nothing below reads the wording. Three
properties are checked instead, and each of them is a way the file could be wrong that a reader
could not see:

1. **All ten §52 fields are present.** The list is `release_notes.SECTION_52`, and the check is
   that every entry of it is reachable in the rendered document — so deleting a section from the
   template is a red test rather than a shorter release note.
2. **It is deterministic.** §53's witness carries a digest over this file. A renderer that read a
   clock would make the witness unverifiable on the second run, and the failure would appear as a
   digest mismatch in a release round rather than as a bug here.
3. **It refuses rather than misdescribing.** Notes about 2.0.0 published under a 2.1.0 tag are the
   §52 failure with no visible symptom: the heading carries the right number and the prose
   describes the previous release. `PUBLICATION.md` entry 10 records what a wrong number costs
   once a filename is permanent.

The fixtures are written here rather than read from the repository's own `RELEASE_NOTES.md`,
except where the point IS the repository's own file. A test that rendered the real tree and
asserted "14 adapters" would be a stale-count sweep site, and this repository has enough of those.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from synapse_cdm import release_notes, version

REPO = pathlib.Path(__file__).resolve().parents[1]
MANIFESTS = REPO / "manifests"
SECURITY = REPO / "SECURITY.md"
EXCEPTIONS = REPO / "security" / "exceptions"

DECLARED = version.PACKAGE_VERSION


@pytest.fixture
def notes(tmp_path) -> pathlib.Path:
    path = tmp_path / "RELEASE_NOTES.md"
    path.write_text(f"# synapse-cdm {DECLARED}\n\nProse a person wrote.\n\n"
                    "## A heading of its own\n\nMore prose.\n", encoding="utf-8")
    return path


@pytest.fixture
def sweep() -> dict:
    """A two-adapter sweep in the shape `--all` writes, with no absolute path in it."""
    return {
        "pntmap": {"adapter": {"id": "pntmap", "adapter_version": "1.0.0", "direction": "ingest",
                               "fixtures": "<packaged>/pntmap"},
                   "result": "CONFORMANT", "maturity_eligible": "L5",
                   "checks": {"A": {"verdict": "PASS"}, "E": {"verdict": "SKIP"}}},
        "tak": {"adapter": {"id": "tak", "adapter_version": "1.0.0", "direction": "both",
                            "fixtures": "<packaged>/tak"},
                "result": "CONFORMANT", "maturity_eligible": "L5",
                "checks": {"A": {"verdict": "PASS"}, "E": {"verdict": "SKIP"}}},
    }


def render(notes: pathlib.Path, sweep: dict, **kwargs) -> str:
    return release_notes.render(
        DECLARED, notes_path=notes, manifests_dir=MANIFESTS, conformance=sweep,
        security_path=SECURITY, exceptions_dir=EXCEPTIONS,
        codeql=kwargs.pop("codeql", "0 findings at or above 7.0"),
        pip_audit=kwargs.pop("pip_audit", "0 findings"), **kwargs)


# ------------------------------------------------------------------------------ §52's ten fields

def test_section_52_lists_exactly_the_ten_fields_the_specification_names():
    """The tuple is read by the renderer and by this module. It is the specification, transcribed."""
    assert release_notes.SECTION_52 == (
        "package version", "CDM version", "SC-OES version", "Adapter API version",
        "manifest schema version", "major changes", "adapter status", "security status",
        "known limitations", "conformance summary")
    assert len(release_notes.SECTION_52) == 10


def test_every_one_of_the_ten_fields_appears_in_the_rendered_document(notes, sweep):
    """A section dropped from the template is a red test, not a shorter release note."""
    text = render(notes, sweep).lower()
    for field in release_notes.SECTION_52:
        assert field.lower() in text, f"§52 requires `{field}` and the rendered notes have no such"


def test_the_five_version_axes_are_the_constants_and_not_copies(notes, sweep):
    text = render(notes, sweep)
    for _, constant in release_notes.VERSION_AXES:
        assert f"`{getattr(version, constant)}`" in text, constant


def test_the_axes_are_read_from_version_py_rather_than_listed_here():
    """`VERSIONING.md` §2 is the authority; a second list is a second thing to drift."""
    for _, constant in release_notes.VERSION_AXES:
        assert hasattr(version, constant), f"{constant} is not a constant version.py declares"


# ------------------------------------------------------------------------------------ determinism

def test_two_renders_of_one_tree_are_byte_identical(notes, sweep):
    """§53's witness hashes this output. A renderer that read a clock would break the witness."""
    assert render(notes, sweep) == render(notes, sweep)


def test_the_rendered_document_carries_no_absolute_path(notes, sweep):
    """A machine-local path in a published note is a digest that differs per runner."""
    text = render(notes, sweep)
    assert str(REPO) not in text, "the renderer leaked the checkout path into the notes"


# -------------------------------------------------------------------------------- the refusals

def test_notes_about_another_version_are_refused(tmp_path, sweep):
    other = tmp_path / "RELEASE_NOTES.md"
    other.write_text("# synapse-cdm 0.0.1\n\nAbout a different release.\n", encoding="utf-8")
    with pytest.raises(release_notes.NotesRefused) as refusal:
        render(other, sweep)
    assert "0.0.1" in str(refusal.value) and DECLARED in str(refusal.value)


def test_a_version_that_is_not_this_trees_package_version_is_refused(notes, sweep):
    with pytest.raises(release_notes.NotesRefused) as refusal:
        release_notes.render("99.0.0", notes_path=notes, manifests_dir=MANIFESTS,
                             conformance=sweep, security_path=SECURITY, exceptions_dir=EXCEPTIONS,
                             codeql="x", pip_audit="y")
    assert "condition 3" in str(refusal.value)


def test_notes_with_no_heading_are_refused(tmp_path, sweep):
    headless = tmp_path / "RELEASE_NOTES.md"
    headless.write_text("Prose with nothing saying what it is about.\n", encoding="utf-8")
    with pytest.raises(release_notes.NotesRefused):
        render(headless, sweep)


def test_a_missing_notes_file_is_refused(tmp_path, sweep):
    with pytest.raises(release_notes.NotesRefused):
        render(tmp_path / "absent.md", sweep)


def test_an_empty_manifest_directory_is_refused(tmp_path, notes, sweep):
    with pytest.raises(release_notes.NotesRefused) as refusal:
        release_notes.render(DECLARED, notes_path=notes, manifests_dir=tmp_path,
                             conformance=sweep, security_path=SECURITY, exceptions_dir=EXCEPTIONS,
                             codeql="x", pip_audit="y")
    assert "no manifest" in str(refusal.value)


def test_a_named_conformance_file_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(release_notes.NotesRefused):
        release_notes.load_conformance(tmp_path / "nothing.json")


# ------------------------------------------------------------------------- the derived sections

def test_the_adapter_table_has_one_row_per_shipped_manifest(notes, sweep):
    rows = release_notes.adapter_status(MANIFESTS, sweep)
    assert len(rows) == len(list(MANIFESTS.glob("*.json")))
    assert {r["id"] for r in rows} >= {"pntmap", "tak"}


def test_an_adapter_absent_from_the_sweep_says_so_rather_than_claiming_a_verdict(notes):
    """A missing reading reports as `not run`. A check that did not run is never a pass."""
    rows = release_notes.adapter_status(MANIFESTS, {})
    assert rows and all(r["eligible"] == "not run" and r["result"] == "not run" for r in rows)


def test_the_declared_and_eligible_rungs_are_separate_columns(notes, sweep):
    """ARCHITECTURE.md §3.6 rule 5: a declared rung above an eligible one is the defect."""
    rows = {r["id"]: r for r in release_notes.adapter_status(MANIFESTS, sweep)}
    assert rows["pntmap"]["declared"] == "L3" and rows["pntmap"]["eligible"] == "L5"


def test_the_security_section_reads_securitys_own_controls_table():
    status = release_notes.security_status(SECURITY, EXCEPTIONS, codeql="clean", pip_audit="clean")
    assert len(status["controls"]) >= 10, status["controls"]
    assert all(c["control"] and c["state"] for c in status["controls"])


def test_an_empty_exception_directory_renders_as_none_rather_than_as_nothing(notes, sweep):
    text = render(notes, sweep)
    assert "Security exceptions in force: **none**" in text, (
        "an empty exceptions directory must be stated, not omitted: a section that is silent "
        "about exceptions reads the same whether there are none or nobody looked")


def test_the_limitations_come_from_the_manifests_themselves():
    limits = release_notes.known_limitations(MANIFESTS)
    assert limits, "no adapter states a limitation, which the manifests refute"
    for entry in limits:
        assert all(isinstance(item, str) and item for item in entry["limitations"])


def test_the_conformance_summary_covers_every_adapter_in_the_sweep(sweep):
    letters, rows = release_notes.conformance_summary(sweep)
    assert letters == ["A", "E"]
    assert [r["id"] for r in rows] == ["pntmap", "tak"]
    assert rows[0]["verdicts"] == {"A": "PASS", "E": "SKIP"}


def test_a_sweep_missing_a_check_reports_a_dash_and_not_a_pass(sweep):
    del sweep["tak"]["checks"]["A"]
    _, rows = release_notes.conformance_summary(sweep)
    assert {r["id"]: r["verdicts"]["A"] for r in rows}["tak"] == "—"


# ------------------------------------------------------------- the quoted prose stays a person's

def test_the_human_prose_is_quoted_and_not_summarised(notes, sweep):
    assert "Prose a person wrote." in render(notes, sweep)


def test_the_quoted_proses_own_headings_are_demoted_under_major_changes(notes, sweep):
    """Embedded unchanged, `RELEASE_NOTES.md`'s H2s become siblings of §52's ten sections."""
    text = render(notes, sweep)
    assert "### A heading of its own" in text
    assert "\n## A heading of its own" not in text


def test_a_hash_at_the_start_of_a_fenced_line_is_not_a_heading(tmp_path, sweep):
    """A shell comment inside a code fence is not a heading and must not be demoted."""
    fenced = tmp_path / "RELEASE_NOTES.md"
    fenced.write_text(f"# synapse-cdm {DECLARED}\n\n```bash\n# a comment, not a heading\n```\n",
                      encoding="utf-8")
    assert "# a comment, not a heading" in render(fenced, sweep)
    assert "## a comment, not a heading" not in render(fenced, sweep)


# ------------------------------------------------------------------------------------- the CLI

def test_the_command_is_reachable_through_the_synapse_entry_point(tmp_path, notes, sweep, capsys):
    """`synapse release-notes …` is what §50's pipeline invokes; the module path is not."""
    from synapse_cdm import suite
    payload = tmp_path / "sweep.json"
    payload.write_text(json.dumps({"adapters": sweep}), encoding="utf-8")
    out = tmp_path / "notes.md"
    code = suite.main(["release-notes", "--version", DECLARED, "--from", str(notes),
                       "--manifests", str(MANIFESTS), "--conformance", str(payload),
                       "--security", str(SECURITY), "--exceptions", str(EXCEPTIONS),
                       "--out", str(out)])
    assert code == 0, capsys.readouterr()
    assert out.is_file() and "## Conformance summary" in out.read_text(encoding="utf-8")


def test_the_cli_exits_non_zero_on_a_refusal(tmp_path, sweep, capsys):
    other = tmp_path / "RELEASE_NOTES.md"
    other.write_text("# synapse-cdm 0.0.1\n\nAbout a different release.\n", encoding="utf-8")
    from synapse_cdm import suite
    code = suite.main(["release-notes", "--version", DECLARED, "--from", str(other),
                       "--manifests", str(MANIFESTS), "--evidence", str(tmp_path / "absent")])
    assert code == 2, "a refusal that exits 0 is a pipeline that publishes the wrong notes"
    assert "0.0.1" in capsys.readouterr().err
