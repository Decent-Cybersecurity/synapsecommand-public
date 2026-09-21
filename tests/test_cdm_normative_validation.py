"""`normative_validation`: VALID, INVALID and UNAVAILABLE kept apart, the closure resolved
locally through the catalog, the network never touched, and the four phase-0 bindings judged
where the environment holds them — BLOCKED rather than passed where it does not.

The synthetic half builds a two-file closure in `tmp_path` with a record beside it, so it runs
wherever `lxml` imports; the real half is marked `normative` and goes through
`tests/normative_support.py`.
"""
from __future__ import annotations

import json
import subprocess
import sys as _sys
import pathlib
import sys

import pytest

from synapse_cdm import normative_binding, normative_validation as nv, secure_xml
from synapse_cdm.normative_validation import Binding, Outcome
from tests import normative_support

A_XSD = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:a" xmlns="urn:a"
           elementFormDefault="qualified">
  <xs:import namespace="urn:b" schemaLocation="{b_location}"/>
  <xs:element name="root"><xs:complexType><xs:sequence>
    <xs:element ref="b:leaf" xmlns:b="urn:b"/>
  </xs:sequence></xs:complexType></xs:element>
</xs:schema>
"""
B_XSD = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:b" xmlns="urn:b"
           elementFormDefault="qualified">
  <xs:element name="leaf" type="xs:int"/>
</xs:schema>
"""
CATALOG = """<?xml version="1.0"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <rewriteURI uriStartString="http://example.invalid/schemas/" rewritePrefix="lib/"/>
  <uri name="http://example.invalid/exact/b.xsd" uri="lib/b.xsd"/>
</catalog>
"""
VALID_DOC = b'<root xmlns="urn:a" xmlns:b="urn:b"><b:leaf>4</b:leaf></root>'
INVALID_DOC = b'<root xmlns="urn:a" xmlns:b="urn:b"><b:leaf>four</b:leaf></root>'
FIELDS = ("edition", "files")


def _closure(root: pathlib.Path, *, b_location: str, catalog: bool = False,
             corrupt: str | None = None) -> dict:
    """A closure under `root`: `a.xsd` importing `b.xsd` by `b_location`, the record, and the
    environment that names the directory."""
    (root / "lib").mkdir(exist_ok=True)
    (root / "a.xsd").write_text(A_XSD.format(b_location=b_location))
    (root / "lib" / "b.xsd").write_text(B_XSD)
    record = {"edition": "synthetic 1", "entry_file": "a.xsd",
              "files": {"a.xsd": normative_binding.sha256_of(root / "a.xsd"),
                        "lib/b.xsd": normative_binding.sha256_of(root / "lib" / "b.xsd")}}
    if catalog:
        (root / "catalog.xml").write_text(CATALOG)
        record["catalog"] = "catalog.xml"
    if corrupt:
        record["files"][corrupt] = "0" * 64
    (root / "xsd_pin.json").write_text(json.dumps(record))
    return {"SYNTHETIC_XSD_DIR": str(root)}


BINDING = Binding("synthetic", "SYNTHETIC_XSD_DIR", fields=FIELDS)


def _lxml_imports() -> bool:
    try:
        import lxml.etree  # noqa: F401
    except ImportError:
        return False
    return True


#: The six synthetic tests whose verdict is the VALIDATOR's — VALID, INVALID, or the resolver's
#: refusal reached only once a validator exists — carry this. Where `lxml` does not import the
#: package's answer is UNAVAILABLE by design (the test after them proves that reading), so those
#: six can prove nothing there and say so in the repository's word for it rather than passing or
#: failing: `gates/wheel_install.py` runs this module against a bare wheel, without the `validate`
#: extra, and read six failures on 2026-09-21 that were this environment fact and not a defect.
needs_validator = pytest.mark.skipif(
    not _lxml_imports(),
    reason="BLOCKED_EXTERNAL_EVIDENCE at step 'validator': lxml does not import here, so the "
           "outcome is UNAVAILABLE by design; install the `validate` extra "
           "(`pip install \"synapse-cdm[validate]\"`) to run this half")


@needs_validator
def test_a_valid_document_is_valid_and_an_invalid_one_is_invalid_with_the_validators_message(tmp_path):
    env = _closure(tmp_path, b_location="lib/b.xsd")
    good = nv.validate(BINDING, VALID_DOC, environ=env)
    assert good.outcome is Outcome.VALID and good.problems == () and good.step is None
    assert good.validator.startswith("lxml ")
    bad = nv.validate(BINDING, INVALID_DOC, environ=env)
    assert bad.outcome is Outcome.INVALID and bad.step is None
    assert any("'four' is not a valid value" in line for line in bad.problems), bad.problems
    assert bad.describe().startswith("INVALID by lxml")


def test_unavailable_is_distinct_from_invalid_at_every_step_before_the_validator(tmp_path):
    env = _closure(tmp_path, b_location="lib/b.xsd")
    unset = nv.validate(BINDING, VALID_DOC, environ={})
    assert unset.outcome is Outcome.UNAVAILABLE and unset.step == "hook"
    assert unset.describe().startswith("BLOCKED_EXTERNAL_EVIDENCE at step 'hook'")
    missing = nv.validate(BINDING, VALID_DOC, environ={"SYNTHETIC_XSD_DIR": str(tmp_path / "no")})
    assert missing.step == "directory"
    (tmp_path / "xsd_pin.json").unlink()
    assert nv.validate(BINDING, VALID_DOC, environ=env).step == "record"
    _closure(tmp_path, b_location="lib/b.xsd", corrupt="lib/b.xsd")
    tampered = nv.validate(BINDING, VALID_DOC, environ=env)
    assert tampered.outcome is Outcome.UNAVAILABLE and tampered.step == "checksum"
    assert tampered.blocked and "lib/b.xsd hashes to" in tampered.problems[0]


def test_a_record_without_an_entry_file_is_unavailable_at_the_record_step(tmp_path):
    env = _closure(tmp_path, b_location="lib/b.xsd")
    record = json.loads((tmp_path / "xsd_pin.json").read_text())
    del record["entry_file"]
    (tmp_path / "xsd_pin.json").write_text(json.dumps(record))
    verdict = nv.validate(BINDING, VALID_DOC, environ=env)
    assert verdict.step == "record" and "entry_file" in verdict.problems[0]


@needs_validator
def test_a_remote_import_is_refused_by_the_local_resolver_and_reads_unavailable(tmp_path):
    """The closure names a URL the catalog does not rewrite: the resolver refuses it, the compile
    fails, and the verdict is UNAVAILABLE at `validator` naming the URL — not INVALID, and never
    a fetch."""
    env = _closure(tmp_path, b_location="http://example.invalid/elsewhere/b.xsd")
    verdict = nv.validate(BINDING, VALID_DOC, environ=env)
    assert verdict.outcome is Outcome.UNAVAILABLE and verdict.step == "validator"
    assert "http://example.invalid/elsewhere/b.xsd" in verdict.problems[0]
    assert "refused by the local resolver" in verdict.problems[0]


@needs_validator
def test_a_remote_import_the_catalog_rewrites_is_resolved_to_the_local_copy(tmp_path):
    env = _closure(tmp_path, b_location="http://example.invalid/schemas/b.xsd", catalog=True)
    verdict = nv.validate(BINDING, VALID_DOC, environ=env)
    assert verdict.outcome is Outcome.VALID, verdict
    assert verdict.refused == ()
    assert verdict.resolved == (f"http://example.invalid/schemas/b.xsd -> {tmp_path / 'lib' / 'b.xsd'}",)
    exact = _closure(tmp_path, b_location="http://example.invalid/exact/b.xsd", catalog=True)
    assert nv.validate(BINDING, VALID_DOC, environ=exact).outcome is Outcome.VALID


@needs_validator
def test_an_absolute_path_outside_the_directory_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "b.xsd").write_text(B_XSD)
    inside = tmp_path / "inside"
    inside.mkdir()
    env = _closure(inside, b_location=str(outside / "b.xsd"))
    verdict = nv.validate(BINDING, VALID_DOC, environ=env)
    assert verdict.outcome is Outcome.UNAVAILABLE and verdict.step == "validator"
    assert str(outside / "b.xsd") in verdict.problems[0]


def test_the_catalog_rules_apply_longest_prefix_first_and_exact_before_prefix(tmp_path):
    (tmp_path / "catalog.xml").write_text(
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">'
        '<rewriteURI uriStartString="http://h/" rewritePrefix="short/"/>'
        '<rewriteURI uriStartString="http://h/deep/" rewritePrefix="long/"/>'
        '<uri name="http://h/deep/x.xsd" uri="exact.xsd"/>'
        '</catalog>')
    rules = nv.read_catalog(tmp_path / "catalog.xml")
    assert nv.apply_catalog(rules, "http://h/a.xsd") == tmp_path / "short" / "a.xsd"
    assert nv.apply_catalog(rules, "http://h/deep/a.xsd") == tmp_path / "long" / "a.xsd"
    assert nv.apply_catalog(rules, "http://h/deep/x.xsd") == tmp_path / "exact.xsd"
    assert nv.apply_catalog(rules, "http://elsewhere/a.xsd") is None


def test_a_catalog_carrying_a_doctype_is_refused_like_any_document(tmp_path):
    (tmp_path / "catalog.xml").write_text("<!DOCTYPE c [<!ENTITY x 'y'>]><catalog>&x;</catalog>")
    with pytest.raises(secure_xml.XmlRefused):
        nv.read_catalog(tmp_path / "catalog.xml")


@needs_validator
def test_document_limits_are_applied_before_the_validator_and_read_as_invalid(tmp_path):
    env = _closure(tmp_path, b_location="lib/b.xsd")
    bomb = b"<!DOCTYPE r [<!ENTITY x 'y'>]>" + VALID_DOC
    verdict = nv.validate(BINDING, bomb, environ=env,
                          limits=secure_xml.XmlLimits(max_bytes=4096, max_depth=8, max_elements=8))
    assert verdict.outcome is Outcome.INVALID and "XML refused (dtd)" in verdict.problems[0]


@needs_validator
def test_a_document_that_is_not_well_formed_is_invalid_not_unavailable(tmp_path):
    env = _closure(tmp_path, b_location="lib/b.xsd")
    verdict = nv.validate(BINDING, b"<root", environ=env)
    assert verdict.outcome is Outcome.INVALID and verdict.problems


class _NoLxml:
    """A meta-path finder that makes `lxml` unimportable for the duration of one test."""

    def find_spec(self, name, path=None, target=None):
        if name == "lxml" or name.startswith("lxml."):
            raise ImportError(f"{name} is blocked for this test")
        return None


def test_a_missing_validator_is_unavailable_at_the_validator_step_and_names_the_extra(tmp_path, monkeypatch):
    env = _closure(tmp_path, b_location="lib/b.xsd")
    saved = {name: module for name, module in sys.modules.items()
             if name == "lxml" or name.startswith("lxml.")}
    for name in saved:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_NoLxml()] + sys.meta_path)
    verdict = nv.validate(BINDING, VALID_DOC, environ=env)
    assert verdict.outcome is Outcome.UNAVAILABLE and verdict.step == "validator"
    assert "synapse-cdm[validate]" in verdict.problems[0]
    assert verdict.validator is None


def test_the_module_imports_and_the_adapters_discover_without_lxml_at_module_level():
    """`lxml` is imported inside the validator's constructor and nowhere else, so the package —
    and every adapter — loads on a host without the `validate` extra. Asserted on the source
    rather than by blocking the import, which the test above already does for the call path."""
    source = pathlib.Path(nv.__file__).read_text()
    module_level = [line for line in source.splitlines()
                    if line.startswith(("import lxml", "from lxml"))]
    assert module_level == [], module_level


def test_an_unknown_binding_name_is_refused_and_the_four_phase_zero_hooks_are_named():
    with pytest.raises(KeyError):
        nv.validate("no-such-binding", b"<x/>")
    assert sorted(nv.BINDINGS) == ["aixm511", "aixm52", "c2sim", "dnotam"]
    assert {b.env_var for b in nv.BINDINGS.values()} == {
        "SYNAPSE_CDM_C2SIM_XSD_DIR", "SYNAPSE_CDM_AIXM511_XSD_DIR",
        "SYNAPSE_CDM_AIXM52_XSD_DIR", "SYNAPSE_CDM_DNOTAM_XSD_DIR"}


def test_the_support_helper_skips_with_the_registers_word_when_the_hook_is_unset(monkeypatch):
    monkeypatch.delenv("SYNAPSE_CDM_C2SIM_XSD_DIR", raising=False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        normative_support.resource("c2sim")
    assert str(skipped.value).startswith("BLOCKED_EXTERNAL_EVIDENCE at step 'hook'")
    with pytest.raises(pytest.skip.Exception) as skipped:
        normative_support.verdict("c2sim", b"<x/>")
    assert "BLOCKED_EXTERNAL_EVIDENCE" in str(skipped.value)


# ---------------------------------------------------------------- the real bindings (phase 0)


@pytest.mark.normative
@pytest.mark.parametrize("name", sorted(nv.BINDINGS))
def test_each_phase_zero_closure_compiles_offline_through_the_local_resolver(name):
    """The four closures phase 0 provisioned, compiled with the network off and every remote
    `schemaLocation` answered by THIS module's resolver from the binding's catalog. BLOCKED, not
    passed, where the hook is unset.

    Run in a subprocess with `XML_CATALOG_FILES` removed from the environment, because libxml2
    consults that variable's catalogs BEFORE it consults a Python resolver (read 2026-09-20: with
    `env.sh` sourced the resolver was never asked for a remote URL at all), and a reading taken
    under it would prove libxml2's catalog rather than this module's."""
    normative_support.resource(name)          # BLOCKED here if the hook or the record is absent
    script = (
        "import json, sys\n"
        "from synapse_cdm import normative_validation as nv\n"
        f"resource = nv.build(nv.BINDINGS[{name!r}])\n"
        "print(json.dumps({'name': resource.validator.name, 'resolved': resource.validator.resolved,"
        " 'refused': resource.validator.refused}))\n")
    env = {k: v for k, v in __import__("os").environ.items() if k != "XML_CATALOG_FILES"}
    run = subprocess.run([_sys.executable, "-c", script], capture_output=True, text=True, env=env,
                         cwd=str(pathlib.Path(nv.__file__).resolve().parents[2]))
    assert run.returncode == 0, run.stderr[-2000:]
    reading = json.loads(run.stdout.strip().splitlines()[-1])
    assert reading["name"].startswith("lxml ")
    assert reading["refused"] == [], reading["refused"]
    if name == "aixm52":
        # Phase 0 proved this closure FAILS without a catalog (its GML/ISO/xlink imports spell
        # the OGC and W3C URLs), so here the local resolver must have answered at least one.
        # The `dnotam` closure beside its relocated AIXM copy compiles with no remote URL asked
        # for at all (read 2026-09-20 in this very subprocess), so nothing is asserted of it.
        assert reading["resolved"], "the 5.2 closure imports by remote URL, so the local " \
                                    "resolver must have answered at least one"


@pytest.mark.normative
def test_a_publisher_digital_notam_example_is_valid_and_a_corrupted_copy_is_invalid():
    """An independent input: a Digital NOTAM coding example published with the Donlon fictitious
    data set, judged against AIXM 5.1.1 + Event 2.0.m; the same bytes with one datum value
    replaced by prose must be INVALID. Both readings, or the test is BLOCKED."""
    resource = normative_support.resource("dnotam")
    examples = sorted((resource.directory / "examples").glob("*.xml"))
    if not examples:
        pytest.skip("BLOCKED_EXTERNAL_EVIDENCE at step 'files': the dnotam binding holds no "
                    "examples/ directory")
    document = examples[0].read_bytes()
    assert normative_support.verdict("dnotam", document).outcome is Outcome.VALID
    # Every Event carries a `gml:beginPosition`; a date that is prose is not a `gml:TimePosition`.
    corrupted = document.replace(b"<gml:beginPosition>", b"<gml:beginPosition>not-a-date ", 1)
    assert corrupted != document, "the example carries no gml:beginPosition to corrupt"
    verdict = normative_support.verdict("dnotam", corrupted)
    assert verdict.outcome is Outcome.INVALID and verdict.problems
