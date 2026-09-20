"""STANAG 4676's two bindings: the provisional internal profile and the explicit normative mode.

Audit remediation F05 (2026-09-20). The adapter reads and writes XML whose element names are
AEDP-12's UML attribute names bound through one table, in no namespace, because the normative XSD
is not held here. Before F05 that was stated in FORMAT_COVERAGE.md's status column and nowhere a
program could read; the reader also stripped every namespace, so a document claiming any
namespace was silently read as the profile. This module holds three things:

1. THE DISTINCTION, BOTH DIRECTIONS. The profile refuses a namespaced document by name; the
   normative mode refuses an unqualified one by name. Egress under the profile emits unqualified
   names and says so on its first line; egress under the normative mode emits the recorded
   namespace and is validated before it is returned.
2. NO SILENT FALLBACK. An explicit request for the normative binding is answered with the
   normative binding or with `NormativeBindingBlocked` naming the first unmet step of the
   procedure — at construction, before any fixture is read — and never with the profile's
   result. The success path is exercised with an injected validator, because neither `xmlschema`
   nor `lxml` is installed here and the mode adds no dependency; the register records that leg
   as not observed on this host.
3. THE PARSER. External entity references fail the parse and the external DTD subset is never
   requested — set on the parser, not read off its defaults — while an internal entity still
   expands, as `tests/test_cdm_parser_safety.py` has always read.
"""
import hashlib
import json
import pathlib

import pytest

import synapse_cdm
from synapse_cdm import harness, normative_binding, times
from synapse_cdm.adapters import stanag4676 as nits
from synapse_cdm.adapters.stanag4676 import (NitsError, NormativeBindingBlocked,
                                             NormativeValidationFailed, Stanag4676Adapter)
from synapse_cdm.manifest import WireBinding, limitation_text

FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures/nits"
BASIC = FIXTURES / "standalone_basic_track.nits.xml"
TARGET = "urn:test:nits:normative:B.2"


def adapter(**kwargs) -> Stanag4676Adapter:
    return Stanag4676Adapter(clock=times.frozen_clock(), **kwargs)


def qualified(document: bytes, namespace: str = TARGET) -> bytes:
    """The same document with its root in `namespace` — the normative mode's input shape."""
    return document.replace(b"<NITSRoot", f'<NITSRoot xmlns="{namespace}"'.encode(), 1)


class RecordingValidator:
    """A stand-in for the XSD validator: records what it was asked to validate, and refuses on
    request. What it does NOT do is read a schema — that leg needs `xmlschema` or `lxml`."""

    name = "recording-validator 0"

    def __init__(self, schema_path: pathlib.Path, *, refuse: str | None = None) -> None:
        self.schema_path = schema_path
        self.refuse = refuse
        self.seen: list[bytes] = []

    def validate(self, document: bytes) -> None:
        self.seen.append(document)
        if self.refuse:
            raise ValueError(self.refuse)


def hook(tmp_path: pathlib.Path, **overrides) -> tuple[dict[str, str], pathlib.Path]:
    """A complete, self-consistent resource directory; `overrides` break one thing at a time."""
    directory = tmp_path / "authorised-xsd"
    directory.mkdir(parents=True)
    files = {}
    for name in nits.XSD_FILES:
        content = f"<!-- stand-in for {name}; a test cannot hold the real schema -->".encode()
        (directory / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()
    record = {
        "edition": "AEDP-12 Edition B Version 2",
        "schema_revision": "test-revision",
        "schema_revision_date": "2026-01-01",
        "target_namespace": TARGET,
        "provenance": "a test fixture; not obtained from any channel",
        "usage_rights": "test only",
        "obtained_on": "2026-09-20",
        "files": files,
    }
    record.update(overrides)
    (directory / nits.XSD_RECORD_NAME).write_text(json.dumps(record))
    return {nits.XSD_DIR_ENV: str(directory)}, directory


# ------------------------------------------------------------------ which binding, and how


def test_the_default_binding_is_the_provisional_profile_and_it_is_the_manifests_value():
    a = adapter(environ={})
    assert a.binding == nits.BINDING_PROVISIONAL == WireBinding.PROVISIONAL_INTERNAL_PROFILE.value
    assert a.normative is None and a.binding_report is None
    assert Stanag4676Adapter.metadata.binding is WireBinding.PROVISIONAL_INTERNAL_PROFILE
    assert any("provisional" in limitation_text(line).lower()
               for line in Stanag4676Adapter.metadata.limitations), (
        "the manifest declares the provisional binding and no limitation says so")


def test_the_environment_variable_selects_the_binding_and_the_constructor_wins_over_it():
    env = {nits.BINDING_ENV: nits.BINDING_NORMATIVE}
    with pytest.raises(NormativeBindingBlocked) as blocked:
        adapter(environ=env)
    assert blocked.value.step == "hook"
    # Told explicitly, the constructor's word is the one that counts.
    assert adapter(environ=env, binding=nits.BINDING_PROVISIONAL).binding == nits.BINDING_PROVISIONAL


def test_an_unknown_binding_is_refused_and_the_refusal_says_where_it_came_from():
    with pytest.raises(NitsError, match="constructor"):
        adapter(environ={}, binding="normative-ish")
    with pytest.raises(NitsError, match=nits.BINDING_ENV):
        adapter(environ={nits.BINDING_ENV: "whatever"})


def test_the_procedure_is_keyed_on_the_resolvers_steps_in_their_order():
    assert tuple(step for step, _ in nits.NORMATIVE_PROCEDURE) == normative_binding.STEPS
    assert all(text.strip() for _, text in nits.NORMATIVE_PROCEDURE)
    assert nits.NORMATIVE_VERIFIED == WireBinding.NORMATIVE_VERIFIED.value


def test_the_blocked_exception_is_a_value_error_naming_the_status_and_every_step():
    assert issubclass(NormativeBindingBlocked, ValueError)
    assert not issubclass(NormativeBindingBlocked, NitsError), (
        "a blocked normative request is raised at construction, not from to_cdm; it is not a "
        "document refusal and must not read as one")
    with pytest.raises(ValueError, match="not one of"):
        NormativeBindingBlocked("teleport", "no such step")
    caught = NormativeBindingBlocked("hook", "unset", nits.NORMATIVE_PROCEDURE)
    assert caught.status == normative_binding.BLOCKED_STATUS == "BLOCKED_EXTERNAL_EVIDENCE"
    text = str(caught)
    assert "BLOCKED_EXTERNAL_EVIDENCE" in text and "NOT used" not in text.upper()[:0]
    for step, _ in nits.NORMATIVE_PROCEDURE:
        assert f"[{step}]" in text, f"the refusal does not carry step {step!r} of the procedure"
    assert "fallback" in text or "provisional" in text


# ------------------------------------------------------------ the hook, one failure at a time


def test_without_the_hook_the_normative_mode_is_blocked_at_the_first_step():
    with pytest.raises(NormativeBindingBlocked) as blocked:
        adapter(binding=nits.BINDING_NORMATIVE, environ={})
    assert blocked.value.step == "hook" and nits.XSD_DIR_ENV in str(blocked.value)


def test_the_harness_under_the_normative_environment_fails_before_reading_a_fixture(monkeypatch):
    """`SYNAPSE_CDM_NITS_BINDING=normative python -m synapse_cdm.harness --adapter stanag4676`
    with no hook: the run does not happen, so no verdict of the profile's can be reported as the
    normative binding's."""
    monkeypatch.setenv(nits.BINDING_ENV, nits.BINDING_NORMATIVE)
    monkeypatch.delenv(nits.XSD_DIR_ENV, raising=False)
    with pytest.raises(NormativeBindingBlocked) as blocked:
        harness.main(["--adapter", "stanag4676"])
    assert blocked.value.step == "hook"


@pytest.mark.parametrize("break_it, step, fragment", [
    ("no-such-directory", "directory", "not a directory"),
    ("empty", "record", nits.XSD_RECORD_NAME),
    ("not-json", "record", "not JSON"),
    ("not-object", "record", "not a JSON object"),
    ("empty-field", "record", "['usage_rights']"),
    ("files-unnamed", "files", "no checksum"),
    ("file-missing", "files", "not present"),
    ("checksum", "checksum", "hashes to"),
])
def test_each_unmet_step_is_reported_by_name_and_nothing_is_constructed(tmp_path, break_it, step,
                                                                       fragment):
    env, directory = hook(tmp_path)
    if break_it == "no-such-directory":
        env = {nits.XSD_DIR_ENV: str(tmp_path / "elsewhere")}
    elif break_it == "empty":
        (directory / nits.XSD_RECORD_NAME).unlink()
    elif break_it == "not-json":
        (directory / nits.XSD_RECORD_NAME).write_text("{not json")
    elif break_it == "not-object":
        (directory / nits.XSD_RECORD_NAME).write_text("[]")
    elif break_it == "empty-field":
        env, directory = hook(tmp_path / "again", usage_rights="")
    elif break_it == "files-unnamed":
        record = json.loads((directory / nits.XSD_RECORD_NAME).read_text())
        record["files"].pop(nits.XSD_FILES[1])
        (directory / nits.XSD_RECORD_NAME).write_text(json.dumps(record))
    elif break_it == "file-missing":
        (directory / nits.XSD_FILES[1]).unlink()
    elif break_it == "checksum":
        (directory / nits.XSD_FILES[0]).write_bytes(b"<!-- altered after the record -->")
    with pytest.raises(NormativeBindingBlocked) as blocked:
        adapter(binding=nits.BINDING_NORMATIVE, environ=env, validator_factory=RecordingValidator)
    assert blocked.value.step == step, str(blocked.value)
    assert fragment in str(blocked.value)


def test_with_neither_validator_installed_the_mode_is_blocked_at_the_validator_step(tmp_path,
                                                                                    monkeypatch):
    """The real lookup, with the two libraries forced absent whether or not this host has them."""
    class Absent:
        def __init__(self, schema_path):
            raise ImportError("forced absent by the test")

    monkeypatch.setattr(normative_binding, "VALIDATORS", (Absent, Absent))
    env, _ = hook(tmp_path)
    with pytest.raises(NormativeBindingBlocked) as blocked:
        adapter(binding=nits.BINDING_NORMATIVE, environ=env)
    assert blocked.value.step == "validator"
    assert "xmlschema" in str(blocked.value) and "lxml" in str(blocked.value)


def test_the_real_validator_lookup_names_both_libraries_when_they_are_absent(tmp_path):
    """On a host without `xmlschema` and `lxml` — this one — the default factory is the refusal
    above; on a host with one of them it is a validator with a name. Either reading is asserted,
    neither is skipped."""
    env, directory = hook(tmp_path)
    try:
        resource = normative_binding.resolve(
            env_var=nits.XSD_DIR_ENV, record_name=nits.XSD_RECORD_NAME, files=nits.XSD_FILES,
            fields=nits.XSD_RECORD_FIELDS, environ=env)
    except NormativeBindingBlocked as blocked:
        assert blocked.step == "validator"
        for library in ("xmlschema", "lxml"):
            with pytest.raises(ImportError):
                __import__(library)
    else:
        assert resource.validator.name.split()[0] in ("xmlschema", "lxml")


# --------------------------------------------------------- the success path, validator injected


def test_a_verified_resource_reads_a_namespaced_document_and_reports_what_it_validated_against(
        tmp_path):
    env, directory = hook(tmp_path)
    a = adapter(binding=nits.BINDING_NORMATIVE, environ=env, validator_factory=RecordingValidator)
    assert a.binding == nits.BINDING_NORMATIVE and a.normative is not None
    assert a.normative.target_namespace == TARGET
    document = qualified(BASIC.read_bytes())
    objects = a.to_cdm(document)
    assert objects, "the namespaced document translated to nothing"
    assert a.normative.validator.seen == [document], "the validator did not see the exact bytes"
    report = a.binding_report
    assert report["binding"] == WireBinding.NORMATIVE_VERIFIED.value
    assert report["validator"] == RecordingValidator.name
    assert report["record"]["target_namespace"] == TARGET
    assert report["record"]["schema_revision"] == "test-revision"
    assert set(report["files"]) == set(nits.XSD_FILES)
    for name, digest in report["files"].items():
        assert digest == hashlib.sha256((directory / name).read_bytes()).hexdigest()
    # The same CDM the profile produces from the unqualified twin: the namespace is the binding,
    # the values are the document's.
    profile = adapter(environ={}).to_cdm(BASIC.read_bytes())
    assert [o.model_dump(mode="json") for o in objects] == \
           [o.model_dump(mode="json") for o in profile]


def test_a_document_the_validator_refuses_is_refused_and_nothing_falls_back(tmp_path):
    env, _ = hook(tmp_path)
    a = adapter(binding=nits.BINDING_NORMATIVE, environ=env,
                validator_factory=lambda path: RecordingValidator(path, refuse="element x unknown"))
    with pytest.raises(NormativeValidationFailed, match="element x unknown"):
        a.to_cdm(qualified(BASIC.read_bytes()))
    assert a.binding_report is None, "a refused document left a report behind"


def test_the_normative_mode_refuses_the_profiles_unqualified_document_by_name(tmp_path):
    """The distinction on ingest, normative side: the fixture as shipped is the PROFILE."""
    env, _ = hook(tmp_path)
    a = adapter(binding=nits.BINDING_NORMATIVE, environ=env, validator_factory=RecordingValidator)
    with pytest.raises(NormativeValidationFailed) as refused:
        a.to_cdm(BASIC.read_bytes())
    assert "namespace ''" in str(refused.value) and TARGET in str(refused.value)
    assert a.normative.validator.seen == [], "the validator was consulted about the wrong binding"
    assert a.binding_report is None


def test_the_normative_mode_refuses_a_parsed_twin_because_a_dict_has_no_wire_form(tmp_path):
    env, _ = hook(tmp_path)
    a = adapter(binding=nits.BINDING_NORMATIVE, environ=env, validator_factory=RecordingValidator)
    twin = json.loads((FIXTURES / "standalone_basic_track.parsed.json").read_text())
    with pytest.raises(NormativeValidationFailed, match="parsed twin"):
        a.to_cdm(twin)


def test_the_profile_refuses_a_namespaced_document_by_name_and_points_at_the_normative_mode():
    """The distinction on ingest, profile side: never read by dropping the namespace."""
    a = adapter(environ={})
    with pytest.raises(NitsError) as refused:
        a.to_cdm(qualified(BASIC.read_bytes()))
    text = str(refused.value)
    assert TARGET in text and nits.BINDING_PROVISIONAL in text
    assert f"{nits.BINDING_ENV}={nits.BINDING_NORMATIVE}" in text and nits.XSD_DIR_ENV in text


def test_a_modelled_element_in_a_foreign_namespace_is_a_mixed_binding_and_is_refused():
    document = BASIC.read_bytes().replace(
        b"<profile>", b'<profile xmlns="urn:someone:else">', 1)
    with pytest.raises(NitsError, match="mixed document"):
        adapter(environ={}).to_cdm(document)


def test_an_unmodelled_element_in_its_own_namespace_is_still_parked_and_not_refused():
    """The refusal is about MODELLED names only: an extension element in a vendor namespace is
    what Ed B §2.1.1.5 permits, and it stays parked verbatim as it always was."""
    document = BASIC.read_bytes().replace(
        b"</NITSRoot>", b'<vendorNote xmlns="urn:vendor:x">kept</vendorNote></NITSRoot>', 1)
    objects = adapter(environ={}).to_cdm(document)
    parked = json.dumps([o.model_dump(mode="json") for o in objects])
    assert "vendorNote" in parked and "urn:vendor:x" in parked


# ------------------------------------------------------------------------ egress, both bindings


def test_egress_under_the_profile_is_unqualified_and_says_so_on_its_first_line(tmp_path):
    a = adapter(environ={})
    emitted = a.from_cdm(a.to_cdm(BASIC.read_bytes()))
    first, second = emitted.decode().split("\n", 2)[:2]
    assert first.startswith("<?xml")
    assert second == nits.PROVISIONAL_MARKER and nits.BINDING_PROVISIONAL in second
    assert b'xmlns="' not in emitted.split(b"<NITSRoot", 1)[1].split(b">", 1)[0]
    # The profile reads its own output back, and the normative mode refuses it by name.
    assert a.to_cdm(emitted)
    env, _ = hook(tmp_path)
    with pytest.raises(NormativeValidationFailed):
        adapter(binding=nits.BINDING_NORMATIVE, environ=env,
                validator_factory=RecordingValidator).to_cdm(emitted)


def test_egress_under_the_normative_mode_is_namespaced_validated_and_refused_by_the_profile(
        tmp_path):
    env, _ = hook(tmp_path)
    a = adapter(binding=nits.BINDING_NORMATIVE, environ=env, validator_factory=RecordingValidator)
    objects = a.to_cdm(qualified(BASIC.read_bytes()))
    emitted = a.from_cdm(objects)
    assert f'<NITSRoot xmlns="{TARGET}"'.encode() in emitted
    assert nits.PROVISIONAL_MARKER.encode() not in emitted
    assert a.normative.validator.seen[-1] == emitted, "the emitted bytes were not validated"
    assert a.binding_report["binding"] == WireBinding.NORMATIVE_VERIFIED.value
    # Both directions of the distinction: the normative mode reads it back; the profile refuses.
    assert a.to_cdm(emitted)
    with pytest.raises(NitsError, match=TARGET):
        adapter(environ={}).to_cdm(emitted)


def test_egress_the_validator_refuses_is_not_returned(tmp_path):
    env, _ = hook(tmp_path)
    seen: list[bytes] = []

    class RefuseEmitted(RecordingValidator):
        def validate(self, document: bytes) -> None:
            seen.append(document)
            if len(seen) > 1:
                raise ValueError("the emitted document is not schema-valid")

    a = adapter(binding=nits.BINDING_NORMATIVE, environ=env, validator_factory=RefuseEmitted)
    objects = a.to_cdm(qualified(BASIC.read_bytes()))
    with pytest.raises(NormativeValidationFailed, match="not schema-valid"):
        a.from_cdm(objects)
    assert a.binding_report is None


# ------------------------------------------------------------------------------- the parser


def test_an_external_entity_reference_fails_the_parse_at_the_reference():
    document = (b'<?xml version="1.0"?>\n'
                b'<!DOCTYPE NITSRoot [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>\n'
                b"<NITSRoot><profile>&xxe;</profile></NITSRoot>")
    with pytest.raises(NitsError, match="external entity"):
        nits.parse_document(document)


def test_an_external_dtd_subset_is_never_requested():
    """`example.invalid` cannot resolve (RFC 2606); a parser that requested the subset would
    fail on the name or hang. Parameter-entity parsing is off, so it does neither."""
    document = (b'<?xml version="1.0"?>\n'
                b'<!DOCTYPE NITSRoot SYSTEM "http://example.invalid/nits.dtd">\n'
                b"<NITSRoot><profile>STANDALONE</profile></NITSRoot>")
    assert nits.parse_document(document)["profile"] == ["STANDALONE"]


def test_an_internal_entity_still_expands_and_a_bomb_is_still_refused():
    small = (b'<?xml version="1.0"?>\n<!DOCTYPE NITSRoot [ <!ENTITY p "STANDALONE"> ]>\n'
             b"<NITSRoot><profile>&p;</profile></NITSRoot>")
    assert nits.parse_document(small)["profile"] == ["STANDALONE"]
    # The same construction `tests/test_cdm_parser_safety.py::_bomb(6)` uses, root renamed:
    # libexpat's limit is a heuristic over the amplified size, and the layout of the DTD is
    # part of what it measures, so the bomb that module proves refused is the one used here.
    entities = ['<!ENTITY lol "lol">']
    for level in range(1, 7):
        previous = "lol" if level == 1 else f"lol{level - 1}"
        entities.append(f'<!ENTITY lol{level} "{f"&{previous};" * 10}">')
    bomb = ('<?xml version="1.0"?>\n<!DOCTYPE lolz [\n' + "\n".join(entities)
            + "\n]>\n<NITSRoot><profile>&lol6;</profile></NITSRoot>").encode()
    with pytest.raises(NitsError, match="amplification"):
        nits.parse_document(bomb)
    # Below libexpat's activation threshold the expansion is permitted, as it always was; what
    # bounds it there is `max_input_bytes` on the document, not this parser.
    assert nits.parse_document(bomb.replace(b"&lol6;", b"&lol3;"))["profile"] == ["lol" * 1000]


def test_an_undefined_entity_and_a_truncated_document_are_refused_as_not_well_formed():
    with pytest.raises(NitsError, match="not well-formed XML"):
        nits.parse_document(b"<NITSRoot><profile>&nope;</profile></NITSRoot>")
    with pytest.raises(NitsError, match="not well-formed XML"):
        nits.parse_document(b"<NITSRoot><profile>STANDALONE</NITSRoot>")


def test_the_hardened_parser_builds_the_same_tree_as_the_standard_one_for_every_fixture():
    """Same element tags, attributes and text, fixture by fixture: the hardening removed two
    behaviours and changed nothing else."""
    import xml.etree.ElementTree as ET

    def flat(element):
        return [(e.tag, dict(e.attrib), (e.text or "").strip()) for e in element.iter()]

    checked = 0
    for path in sorted(FIXTURES.glob("*.nits.xml")):
        assert flat(nits._parse_xml(path.read_bytes())) == flat(ET.fromstring(path.read_bytes()))
        checked += 1
    assert checked >= 10
