"""The Synapse Conformance Suite — every check proved BOTH ways.

A conformance tool is the one piece of software whose failure mode is invisible: a check that
silently passes everything looks exactly like a check that passes because the adapter is good.
So each of G–O gets a NEGATIVE case built on a synthetic in-test adapter (the pattern
`tests/test_cdm_harness.py` established) as well as a positive one on a real adapter, and the
SKIP semantics get their own tests, because SKIP-printed-as-PASS is the specific defect
ARCHITECTURE.md §4.7 exists to prevent.
"""
import datetime as _dt
import json
import pathlib
import uuid

import pytest

import synapse_cdm
from synapse_cdm import harness, ids, suite, times, version
from synapse_cdm.adapter import Adapter, packaged_fixtures, roster
from synapse_cdm.adapters.pntmap import PntmapAdapter
from synapse_cdm.enums import Affiliation, EntityType
from synapse_cdm.manifest import UnknownFields
from synapse_cdm.models import Entity

from tests import probe_metadata

REPO = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent

#: The set every adapter in this repository is held to. E, I, M, N and O are absent and each
#: absence is a READING rather than a preference — see
#: `test_the_required_set_this_suite_sweeps_with_excludes_only_checks_no_adapter_can_pass`.
SWEEP = ("A", "B", "C", "D", "F", "G", "H", "J", "K", "L")


def shipped() -> dict:
    """The adapters this PACKAGE ships, not everything the registry holds.

    `roster()` is `REGISTRY`, and every `Adapter` subclass registers itself — including the test
    doubles this module and `test_cdm_harness.py` define. A sweep parametrised on `roster()`
    would grow or shrink with pytest's import order, which is the one thing a conformance sweep
    must not do.
    """
    return {name: cls for name, cls in roster().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


def _fixtures(name: str) -> pathlib.Path:
    return PACKAGE / "fixtures" / (shipped()[name].fixture_dir or name)


def _report(name: str = "pntmap", **kwargs) -> dict:
    cls = shipped()[name]
    return suite.run(cls(clock=times.frozen_clock()), _fixtures(name), **kwargs)


# --- the shape of the thing ------------------------------------------------------------------

def test_the_fifteen_checks_are_seventeen_seventeens_A_to_O_in_order():
    assert suite.CHECK_LETTERS == tuple("ABCDEFGHIJKLMNO")
    assert [c.harness_key for c in suite.CHECKS[:6]] == list(harness._COLUMNS)
    assert all(c.harness_key is None for c in suite.CHECKS[6:])


def test_the_harness_publishes_the_letters_beside_its_own_keys_and_changes_nothing_else():
    """F2.1: `cdm-harness --json` gains ONE key. Re-keying it would break its consumers."""
    report = harness.run(PntmapAdapter(clock=times.frozen_clock()), _fixtures("pntmap"))
    assert report["check_letters"] == {"translate": "A", "schema": "B", "provenance": "C",
                                       "lossless": "D", "roundtrip": "E", "golden": "F"}
    for result in report["results"]:
        assert set(result["checks"]) == set(harness._COLUMNS), \
            "the per-fixture check keys are unchanged; the letters are a parallel key"
    without = {k: v for k, v in report.items() if k != "check_letters"}
    assert harness.render_report(report) == harness.render_report(without), \
        "the letters are a JSON addition; the text rendering does not move"


def test_the_text_report_is_section_18s_layout_and_the_reasons_follow_it():
    text = suite.render_report(_report())
    lines = text.split("\n")
    assert lines[0] == "Synapse Conformance Suite"
    assert lines[1] == "Adapter: pntmap"
    assert lines[2] == ""
    assert lines[3] == "A translate                 PASS"
    assert lines[17] == "O resource limits           SKIP"
    assert lines[18] == ""
    assert "RESULT: CONFORMANT" in text
    assert "MATURITY ELIGIBLE: L" in text
    assert text.index("RESULT:") < text.index("why, for every check that is not PASS")


def test_the_json_report_carries_section_18s_keys_and_is_sorted():
    report = _report()
    assert set(report) == {"adapter", "checks", "result", "maturity_eligible", "generated_with"}
    assert report["generated_with"] == {"package": version.PACKAGE_VERSION,
                                        "schema": version.SCHEMA_VERSION,
                                        "adapter_api": version.ADAPTER_API_VERSION}
    for entry in report["checks"].values():
        assert set(entry) <= {"verdict", "declared_inapplicable", "reason", "details"}
        assert entry["verdict"] in (suite.PASS, suite.FAIL, suite.SKIP)
    text = json.dumps(report, indent=2, sort_keys=True)
    assert json.loads(text) == report


def test_every_check_entry_carries_the_pair_the_eligibility_layer_reads():
    """§3.6 rule 5: the report says SKIP and says WHICH DECLARATION made it inapplicable."""
    for letter, entry in _report()["checks"].items():
        assert isinstance(entry["declared_inapplicable"], bool), letter
        if entry["verdict"] != suite.PASS:
            assert entry.get("reason"), f"{letter} is {entry['verdict']} with no reason"


# --- SKIP is never PASS ----------------------------------------------------------------------

def test_no_skip_is_ever_rendered_or_recorded_as_a_pass():
    for name in shipped():
        report = _report(name)
        text = suite.render_report(report)
        for check in suite.CHECKS:
            entry = report["checks"][check.letter]
            row = f"{check.letter} {check.name}".ljust(28) + entry["verdict"]
            assert row in text, row
            if entry["verdict"] == suite.SKIP:
                assert suite.PASS not in row


def test_a_skip_with_no_declared_inapplicability_blocks_the_rung_and_every_rung_above():
    """§3.6 rule 6, exercised on the algorithm rather than argued about."""
    checks = {letter: {"verdict": suite.PASS, "declared_inapplicable": False}
              for letter in suite.CHECK_LETTERS}
    assert suite.eligible_level(checks) == "L5"
    checks["E"] = {"verdict": suite.SKIP, "declared_inapplicable": False}
    assert suite.eligible_level(checks) == "L3", "an undeclared SKIP on E blocks L4 and L5"
    checks["E"] = {"verdict": suite.SKIP, "declared_inapplicable": True}
    assert suite.eligible_level(checks) == "L5", "§3.6 rule 4: a declared one does not block"
    checks["C"] = {"verdict": suite.FAIL, "declared_inapplicable": False}
    assert suite.eligible_level(checks) == "L2"
    checks["A"] = {"verdict": suite.FAIL, "declared_inapplicable": False}
    assert suite.eligible_level(checks) == "L0", "L0 is a document, not a check (§3.6 step 2)"


def test_l6_is_never_computed_from_this_repositorys_own_evidence():
    checks = {letter: {"verdict": suite.PASS, "declared_inapplicable": False}
              for letter in suite.CHECK_LETTERS}
    assert suite.eligible_level(checks) != "L6"


# --- the required set and the exit status ----------------------------------------------------

def test_require_fails_the_invocation_on_a_skip_without_rewriting_the_verdict():
    """§19, and `conformance.py:754`'s rule that the two layers stay apart."""
    report = _report()
    assert report["checks"]["M"]["verdict"] == suite.SKIP
    assert suite.exit_status(report, ("M",)) == suite.EXIT_FAILED
    assert report["checks"]["M"]["verdict"] == suite.SKIP, "the verdict is not rewritten"
    assert suite.exit_status(report, ("A", "B")) == suite.EXIT_OK
    assert suite.exit_status(report) == suite.EXIT_OK, "no --require: only a FAIL is non-zero"


def test_a_caller_who_scoped_the_run_is_not_failed_by_a_check_it_did_not_ask_about():
    """`conformance.py:754`'s ruling, one namespace over (ADR 0009 alternative C)."""
    report = _report()
    report["checks"]["G"] = {"verdict": suite.FAIL, "declared_inapplicable": False}
    assert suite.exit_status(report, ("A",)) == suite.EXIT_OK
    assert suite.exit_status(report, ("A", "G")) == suite.EXIT_FAILED
    assert suite.exit_status(report) == suite.EXIT_FAILED, \
        "a caller who scoped nothing asked about everything"


@pytest.mark.parametrize("name", sorted(shipped()))
def test_every_shipped_adapter_passes_the_sweep(name):
    """The whole point of the round: fourteen adapters, one bar, exit 0."""
    report = _report(name)
    assert report["result"] == "CONFORMANT", suite.render_report(report)
    assert suite.exit_status(report, SWEEP) == suite.EXIT_OK, suite.render_report(report)


def test_the_required_set_this_suite_sweeps_with_excludes_only_checks_no_adapter_can_pass():
    """The five absences from SWEEP, each derived from the tree rather than chosen.

    A sweep set that quietly dropped a check an adapter merely fails would be a green bar over a
    hole. So each exclusion is re-derived here: every one of the five is SKIP for at least one
    adapter for a reason that is DECLARED, and none of the five is FAIL anywhere.
    """
    excluded = set("EIMNO")
    assert set(suite.CHECK_LETTERS) - set(SWEEP) == excluded
    for letter in excluded:
        skipped = {name: _report(name)["checks"][letter] for name in shipped()}
        assert any(e["verdict"] == suite.SKIP for e in skipped.values()), letter
        assert not any(e["verdict"] == suite.FAIL for e in skipped.values()), \
            f"{letter} FAILs somewhere and is being excluded rather than reported"


# --- the synthetic adapters: every check proved to bite --------------------------------------

class _Base(Adapter):
    """A minimal in-test adapter. Subclasses break exactly one property each."""

    name = "probe-base"
    version = "0.1.0"
    direction = "ingest"
    system = "probe"
    metadata = probe_metadata("probe-base")

    def to_cdm(self, raw):
        return [self._entity(raw)]

    def _entity(self, raw):
        return Entity(
            entity_id=ids.derive(self.system, str(raw.get("id")), kind="entity"),
            source_ids=[{"system": self.system, "external_id": str(raw.get("id"))}],
            entity_type=EntityType.UNKNOWN, affiliation=Affiliation.UNKNOWN,
            valid_from=self.now(), source=self.source_ref(),
            attributes=dict(raw),
        )


class _NonDeterministic(_Base):
    name = "probe-nondeterministic"
    metadata = probe_metadata("probe-nondeterministic")
    _counter = 0

    def to_cdm(self, raw):
        type(self)._counter += 1
        entity = self._entity(raw)
        entity.attributes["draw"] = type(self)._counter
        return [entity]


class _Accepting(_Base):
    name = "probe-accepting"
    metadata = probe_metadata("probe-accepting")

    def to_cdm(self, raw):
        return [self._entity(raw if isinstance(raw, dict) else {"id": "anything"})]


class _Dropping(_Base):
    name = "probe-dropping"
    metadata = probe_metadata("probe-dropping", unknown_fields_declaration="preserved")

    def to_cdm(self, raw):
        return [Entity(entity_id=ids.derive(self.system, str(raw.get("id")), kind="entity"),
                       source_ids=[{"system": self.system,
                                    "external_id": str(raw.get("id"))}],
                       entity_type=EntityType.UNKNOWN, affiliation=Affiliation.UNKNOWN,
                       valid_from=self.now(), source=self.source_ref(),
                       attributes={"id": raw.get("id")})]


class _Epoch(_Base):
    name = "probe-epoch"
    metadata = probe_metadata("probe-epoch")

    def to_cdm(self, raw):
        entity = self._entity(raw)
        entity.valid_from = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
        return [entity]


class _Drawn(_Base):
    name = "probe-drawn"
    metadata = probe_metadata("probe-drawn")

    def to_cdm(self, raw):
        entity = self._entity(raw)
        entity.entity_id = uuid.uuid4()
        return [entity]


class _Crashing(_Base):
    name = "probe-crashing"
    metadata = probe_metadata("probe-crashing")

    def to_cdm(self, raw):
        raise MemoryError("a crash class, not a refusal")


@pytest.fixture
def probe_fixtures(tmp_path):
    (tmp_path / "one.json").write_text(json.dumps({"id": "a", "nested": {"k": 1}}) + "\n")
    (tmp_path / "two.json").write_text(json.dumps({"id": "b", "nested": {"k": 2}}) + "\n")
    return tmp_path


def _payloads(directory):
    return [(p.name, harness.load_raw(p)) for p in suite._fixtures(directory)]


def test_G_catches_an_adapter_that_does_not_produce_the_same_bytes_twice(probe_fixtures):
    clock = times.frozen_clock()
    good = suite.check_deterministic(_Base(clock=clock), _payloads(probe_fixtures), clock=clock)
    assert good["verdict"] == suite.PASS
    bad = suite.check_deterministic(_NonDeterministic(clock=clock), _payloads(probe_fixtures),
                                    clock=clock)
    assert bad["verdict"] == suite.FAIL
    assert "serialised differently" in bad["reason"]


def test_G_compares_the_serialisation_architecture_md_froze_and_imports_no_hash():
    """§6.2's form, and the collision `suite.canonical`'s docstring records.

    `tests/test_cdm_boundary.py` forbids `hashlib` under `synapse_cdm/` and ARCHITECTURE.md §4.4
    says this check hashes. Neither is edited: G compares the serialisations themselves, which
    decides the same question more strongly. This test pins BOTH halves, so that a later round
    which resolves the collision has to come back here and say so.
    """
    objects = [{"b": 1, "a": 2}]
    assert suite.canonical(objects) == json.dumps(objects, sort_keys=True, indent=2) + "\n"
    assert not hasattr(suite, "digest"), \
        "a digest reappeared without the boundary gate's ruling; see canonical()'s docstring"
    source = (PACKAGE / "suite.py").read_text()
    assert "\nimport hashlib" not in source


def test_H_skips_when_no_malformed_set_is_declared_and_fails_on_an_empty_one(probe_fixtures):
    clock = times.frozen_clock()
    absent = suite.check_malformed(_Base(clock=clock), probe_fixtures, clock=clock)
    assert absent["verdict"] == suite.SKIP and absent["declared_inapplicable"]
    (probe_fixtures / "malformed").mkdir()
    empty = suite.check_malformed(_Base(clock=clock), probe_fixtures, clock=clock)
    assert empty["verdict"] == suite.FAIL
    assert "empty" in empty["reason"]


def test_H_fails_an_adapter_that_accepts_a_malformed_payload(probe_fixtures):
    clock = times.frozen_clock()
    (probe_fixtures / "malformed").mkdir()
    (probe_fixtures / "malformed" / "nonsense.bin").write_bytes(b"\xff\xfe\x00")
    accepted = suite.check_malformed(_Accepting(clock=clock), probe_fixtures, clock=clock)
    assert accepted["verdict"] == suite.FAIL
    assert "ACCEPTED" in accepted["reason"]
    refused = suite.check_malformed(_Base(clock=clock), probe_fixtures, clock=clock)
    assert refused["verdict"] == suite.PASS
    assert refused["details"]["exception_classes"], "the exception class is recorded (F2.2)"


def test_H_fails_a_crash_class_and_a_refusal_only_the_loader_made(probe_fixtures):
    clock = times.frozen_clock()
    (probe_fixtures / "malformed").mkdir()
    (probe_fixtures / "malformed" / "nonsense.bin").write_bytes(b"\xff\xfe\x00")
    crashed = suite.check_malformed(_Crashing(clock=clock), probe_fixtures, clock=clock)
    assert crashed["verdict"] == suite.FAIL and "crash class" in crashed["reason"]
    (probe_fixtures / "malformed" / "nonsense.bin").unlink()
    (probe_fixtures / "malformed" / "broken.json").write_text("{,,,")
    loader_only = suite.check_malformed(_Base(clock=clock), probe_fixtures, clock=clock)
    assert loader_only["verdict"] == suite.FAIL
    assert "none reached the adapter" in loader_only["reason"]


def test_I_reads_the_declaration_and_does_not_probe_a_format_that_has_no_carrier(probe_fixtures):
    clock = times.frozen_clock()
    declared_none = suite.check_unknown_fields(_Base(clock=clock), probe_fixtures, clock=clock)
    assert declared_none["verdict"] == suite.SKIP
    assert declared_none["declared_inapplicable"]
    assert "format has no unknown-field carrier" in declared_none["reason"]


def test_I_catches_an_adapter_that_drops_what_it_declares_it_preserves(probe_fixtures):
    clock = times.frozen_clock()
    keeping = suite.check_unknown_fields(
        _preserving(_Base)(clock=clock), probe_fixtures, clock=clock)
    assert keeping["verdict"] == suite.PASS
    assert keeping["details"]["documents_probed"] == 2
    dropping = suite.check_unknown_fields(_Dropping(clock=clock), probe_fixtures, clock=clock)
    assert dropping["verdict"] == suite.FAIL
    assert "dropped" in dropping["reason"]


def test_J_refuses_the_epoch_and_passes_a_real_instant(probe_fixtures):
    clock = times.frozen_clock()
    good = suite.check_temporal(_Base(clock=clock), _payloads(probe_fixtures), clock=clock,
                                frozen_at=times.FROZEN_NOW)
    assert good["verdict"] == suite.PASS
    bad = suite.check_temporal(_Epoch(clock=clock), _payloads(probe_fixtures), clock=clock,
                               frozen_at=times.FROZEN_NOW)
    assert bad["verdict"] == suite.FAIL
    assert "1970-01-01" in bad["reason"]


def test_J_uses_a_second_clock_rather_than_equality_to_the_first():
    """The differential is the check; the equality proxy would fail a real source time.

    `cat048`'s `fspec_longer_than_necessary` carries I048/140 = 22500.0 s = 06:15:00, which IS
    the frozen instant and IS a source time. It passes, and that is the reading this test pins.
    """
    report = _report("cat048")
    assert report["checks"]["J"]["verdict"] == suite.PASS
    assert report["checks"]["J"]["details"]["alternative_clock"] != times.render(times.FROZEN_NOW)


def test_K_catches_a_drawn_identifier_and_accepts_a_derived_one(probe_fixtures):
    clock = times.frozen_clock()
    derived = suite.check_identity(_Base(clock=clock), _payloads(probe_fixtures), clock=clock)
    assert derived["verdict"] == suite.PASS and derived["details"]["identifiers"] == 2
    drawn = suite.check_identity(_Drawn(clock=clock), _payloads(probe_fixtures), clock=clock)
    assert drawn["verdict"] == suite.FAIL
    assert "uuid4" in drawn["reason"] or "differs" in drawn["reason"]


def test_K_does_not_judge_the_sources_own_identifier():
    """`source.external_id` is somebody else's uuid and is deliberately outside the check."""
    assert "external_id" not in suite.IDENTITY_FIELDS
    report = _report("stanag4676")
    assert report["checks"]["K"]["verdict"] == suite.PASS


def test_L_reads_the_objects_against_this_package_and_this_manifest(probe_fixtures):
    clock = times.frozen_clock()
    good = suite.check_version(_Base(clock=clock), _payloads(probe_fixtures), clock=clock,
                               supported="2.x")
    assert good["verdict"] == suite.PASS
    outside = suite.check_version(_Base(clock=clock), _payloads(probe_fixtures), clock=clock,
                                  supported="9.x")
    assert outside["verdict"] == suite.FAIL
    assert "cdm.supported" in outside["reason"]


def test_M_is_skip_for_every_adapter_and_says_why():
    for name in shipped():
        entry = _report(name)["checks"]["M"]
        assert entry["verdict"] == suite.SKIP and entry["declared_inapplicable"]
        assert "no streaming capability" in entry["reason"]


def test_N_truncates_at_a_stated_cap_and_reports_a_crash_class(probe_fixtures):
    clock = times.frozen_clock()
    (probe_fixtures / "bytes.bin").write_bytes(bytes(range(256)) * 40)
    crashing = suite.check_parser_robustness(_Crashing(clock=clock), probe_fixtures, clock=clock,
                                             offset_cap=16)
    assert crashing["verdict"] == suite.FAIL and "crash class" in crashing["reason"]
    assert crashing["details"]["offset_cap_per_fixture"] == 16
    refusing = suite.check_parser_robustness(_Base(clock=clock), probe_fixtures, clock=clock,
                                             offset_cap=16)
    assert refusing["verdict"] == suite.PASS
    assert refusing["details"]["offsets_tried"] == 16


def test_N_skips_a_dict_only_adapter_by_declaration(probe_fixtures):
    clock = times.frozen_clock()
    entry = suite.check_parser_robustness(_Base(clock=clock), probe_fixtures, clock=clock)
    assert entry["verdict"] == suite.SKIP and entry["declared_inapplicable"]
    assert "not a byte stream" in entry["reason"]


def test_O_skips_on_the_declared_absence_and_bites_where_a_bound_is_declared(probe_fixtures):
    clock = times.frozen_clock()
    entry = suite.check_resource_limits(_Base(clock=clock), _payloads(probe_fixtures),
                                        clock=clock)
    assert entry["verdict"] == suite.SKIP and entry["declared_inapplicable"]
    assert "no limit declared" in entry["reason"]

    bounded = _bounded(_Accepting, 32)(clock=clock)
    (probe_fixtures / "bytes.bin").write_bytes(b"\x01" * 8)
    accepted = suite.check_resource_limits(bounded, _payloads(probe_fixtures), clock=clock)
    assert accepted["verdict"] == suite.FAIL
    assert "accepted it" in accepted["reason"]

    refusing = suite.check_resource_limits(_bounded(_Base, 32)(clock=clock),
                                           _payloads(probe_fixtures), clock=clock)
    assert refusing["verdict"] == suite.PASS


# --- the CLI ---------------------------------------------------------------------------------

def test_the_cli_runs_lists_and_honours_require(capsys):
    assert suite.main(["conformance", "list"]) == suite.EXIT_OK
    listing = capsys.readouterr().out
    assert f"{len(roster())} adapters registered" in listing
    assert all(name in listing for name in shipped())
    assert suite.main(["conformance", "run", "--adapter", "pntmap"]) == suite.EXIT_OK
    assert "MATURITY ELIGIBLE" in capsys.readouterr().out
    assert suite.main(["conformance", "run", "--adapter", "pntmap", "--require", "M"]) == \
        suite.EXIT_FAILED
    capsys.readouterr()
    assert suite.main(["conformance", "run", "--adapter", "pntmap", "--format", "json"]) == \
        suite.EXIT_OK
    assert json.loads(capsys.readouterr().out)["adapter"]["id"] == "pntmap"


def test_the_cli_refuses_an_unknown_adapter_and_an_unknown_letter(capsys):
    assert suite.main(["conformance", "run", "--adapter", "nope"]) == suite.EXIT_USAGE
    assert "unknown adapter" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        suite.main(["conformance", "run", "--adapter", "pntmap", "--require", "Z"])


def test_the_console_script_and_the_dash_m_path_are_the_same_entry_point():
    pyproject = (REPO / "packages" / "cdm" / "pyproject.toml").read_text()
    assert 'synapse = "synapse_cdm.suite:main"' in pyproject
    assert (PACKAGE / "suite.py").read_text().rstrip().endswith("raise SystemExit(main())")


# --- the fixtures this round shipped ----------------------------------------------------------

@pytest.mark.parametrize("name", sorted(shipped()))
def test_every_adapter_ships_at_least_two_malformed_fixtures_and_refuses_each(name):
    directory = _fixtures(name) / suite.MALFORMED_DIR
    assert directory.is_dir(), f"{name} declares no malformed set"
    assert len(suite._fixtures(directory)) >= 2
    entry = _report(name)["checks"]["H"]
    assert entry["verdict"] == suite.PASS, entry.get("reason")
    assert entry["details"]["refused_by_adapter"] >= 1


@pytest.mark.parametrize("name", sorted(shipped()))
def test_the_malformed_set_is_invisible_to_the_harness(name):
    """`harness.py:343` selects FILES; a subdirectory is out of A–F's reach by construction."""
    report = harness.run(shipped()[name](clock=times.frozen_clock()), _fixtures(name))
    replayed = {result["fixture"] for result in report["results"]}
    assert not any(name.startswith("truncated") or name.startswith("malformed")
                   for name in replayed)


# --- helpers ----------------------------------------------------------------------------------

def _preserving(base):
    class _Preserving(base):
        name = f"{base.name}-preserving"
        metadata = probe_metadata(f"{base.name}-preserving",
                                  unknown_fields_declaration="preserved")
    return _Preserving


def _bounded(base, limit):
    class _Bounded(base):
        name = f"{base.name}-bounded-{limit}"
        metadata = probe_metadata(f"{base.name}-bounded-{limit}", max_input_bytes=limit)
    return _Bounded
