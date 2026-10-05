"""`Adapter.fixture_instance`: the hook, its callers, and the command lines' refusals around it.

The hook is the one construction the harness, the conformance suite (and its spawned parser
worker) and the evidence generator use to build an adapter for its PACKAGED fixtures. Its default
is the plain construction, so every adapter that predates `dis7` behaves exactly as before; an
adapter whose constructor needs context overrides it. `dis7` is the one shipped adapter that does;
the overriding adapter here is a test double (`tests/fixture_instance_double.py`), replayed over a
fixture directory under `tmp_path`.
"""

import ast
import json
import pathlib

import pytest

import synapse_cdm
from synapse_cdm import adapter as adapter_module
from synapse_cdm import evidence, harness, suite, times
from synapse_cdm.adapter import Adapter, InputTooLarge
from synapse_cdm.adapters.pntmap import PntmapAdapter

from tests import fixture_instance_double
from tests import probe_metadata

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
REFERENCE = "tests.fixture_instance_double:ContextDouble"
Q = "tests.fixture_instance_double."

ContextDouble = fixture_instance_double.ContextDouble
RequiresContext = fixture_instance_double.RequiresContext
ContextMissing = fixture_instance_double.ContextMissing
CodedRefusal = fixture_instance_double.CodedRefusal
CodedInputTooLarge = fixture_instance_double.CodedInputTooLarge


class _KeywordClock(Adapter):
    """An adapter whose `clock` is keyword-only: a positional pass in the hook would break it."""

    name = "probe-keyword-clock"
    version = "0.1.0"
    direction = "ingest"
    system = "probe"
    metadata = probe_metadata("probe-keyword-clock")

    def __init__(self, *, clock=None, synthetic=True):
        super().__init__(clock=clock, synthetic=synthetic)

    def to_cdm(self, raw):
        return []


def _provenance(directory: str, files: list[str]) -> str:
    return json.dumps({
        "schema_id": "synapse.fixture-provenance/v1",
        "directory": directory,
        "fixtures": [{
            "file": name,
            "synthetic": True,
            "classification": "PUBLIC",
            "operational_data": False,
            "personal_data": False,
            "origin": "Written by hand for the fixture_instance hook tests.",
        } for name in files],
    }, indent=2) + "\n"


@pytest.fixture
def tree(tmp_path):
    directory = tmp_path / "root" / "fixture-context-double"
    malformed = directory / "malformed"
    malformed.mkdir(parents=True)
    (directory / "one.bin").write_bytes(b"FXD1AAAA")
    (directory / "two.bin").write_bytes(b"FXD1BBBB")
    (malformed / "short.bin").write_bytes(b"FXD1")
    (malformed / "wrong_magic.bin").write_bytes(b"XXXXAAAA")
    (directory / "PROVENANCE.json").write_text(
        _provenance("fixture-context-double", ["one.bin", "two.bin"]))
    (malformed / "PROVENANCE.json").write_text(
        _provenance("fixture-context-double/malformed", ["short.bin", "wrong_magic.bin"]))
    return directory


def _shipped(cls):
    return True


def _check(report, letter, verdict=suite.PASS):
    entry = report["checks"][letter]
    assert entry["verdict"] == verdict, (letter, entry)
    return entry["details"]


def test_the_hook_is_a_classmethod_placed_immediately_after_encode():
    module = ast.parse((PACKAGE / "adapter.py").read_text())
    adapter = next(node for node in module.body
                   if isinstance(node, ast.ClassDef) and node.name == "Adapter")
    names = [node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
             for node in adapter.body]
    hook = adapter.body[names.index("encode") + 1]
    assert isinstance(hook, ast.FunctionDef) and hook.name == "fixture_instance"
    assert [ast.unparse(d) for d in hook.decorator_list] == ["classmethod"]
    assert [a.arg for a in hook.args.args] == ["cls", "clock"]
    assert [ast.literal_eval(d) for d in hook.args.defaults] == [None]
    assert [a.arg for a in hook.args.kwonlyargs] == ["synthetic"]
    assert [ast.literal_eval(d) for d in hook.args.kw_defaults] == [True]


def test_the_default_hook_passes_the_clock_by_keyword():
    instance = _KeywordClock.fixture_instance(times.frozen_clock())
    assert type(instance) is _KeywordClock
    assert instance.now() == times.FROZEN_NOW
    assert instance._synthetic is True
    assert _KeywordClock.fixture_instance(times.frozen_clock(), synthetic=False)._synthetic is False


def test_the_default_hook_is_the_old_construction_for_a_shipped_adapter():
    assert PntmapAdapter.fixture_instance.__func__ is Adapter.fixture_instance.__func__
    raw = harness.load_raw(PACKAGE / "fixtures" / "pntmap" / "jamming_gulf_of_riga.json")
    clock = times.frozen_clock()
    hooked = PntmapAdapter.fixture_instance(clock=clock, synthetic=True)
    old = PntmapAdapter(clock=clock, synthetic=True)
    assert harness._dump(hooked.to_cdm(raw)) == harness._dump(old.to_cdm(raw))
    live = PntmapAdapter.fixture_instance(clock=clock, synthetic=False)
    assert live.source_ref().synthetic is False


@pytest.mark.parametrize("name", sorted(adapter_module.shipped()))
def test_every_shipped_adapter_is_constructible_through_the_hook(name):
    cls = adapter_module.shipped()[name]
    instance = cls.fixture_instance(clock=times.frozen_clock())
    assert type(instance) is cls
    assert instance.now() == times.FROZEN_NOW
    assert instance.source_ref().synthetic is True


def test_the_seven_package_sites_construct_through_the_hook():
    expected = {"harness.py": 1, "suite.py": 5, "evidence.py": 1}
    for filename, count in expected.items():
        calls = [node for node in ast.walk(ast.parse((PACKAGE / filename).read_text()))
                 if isinstance(node, ast.Call)
                 and any(k.arg == "synthetic" for k in node.keywords)]
        assert len(calls) == count, filename
        for call in calls:
            assert isinstance(call.func, ast.Attribute), (filename, ast.unparse(call))
            assert call.func.attr == "fixture_instance", (filename, ast.unparse(call))
            assert any(k.arg == "clock" for k in call.keywords), (filename, ast.unparse(call))


def test_the_docstrings_state_the_packaged_fixture_limit():
    assert "packaged-fixture context ONLY" in Adapter.fixture_instance.__doc__
    assert "fixture_instance" in suite.run.__doc__
    assert "packaged fixtures only" in suite.run.__doc__


def test_the_double_refuses_generic_construction_and_a_live_hook():
    assert issubclass(ContextMissing, ValueError)
    with pytest.raises(ContextMissing):
        ContextDouble()
    with pytest.raises(ContextMissing):
        ContextDouble(clock=times.frozen_clock(), synthetic=True)
    with pytest.raises(ContextMissing):
        RequiresContext.fixture_instance(times.frozen_clock())
    with pytest.raises(ContextMissing):
        ContextDouble.fixture_instance(synthetic=False)
    instance = ContextDouble.fixture_instance(clock=times.frozen_clock())
    assert instance.to_cdm(b"FXD1AAAA")[0].attributes == {"context": "packaged-fixture-context"}


def test_the_coded_guard_runs_first_and_keeps_the_sdk_wrapper_reachable():
    outer = ContextDouble.to_cdm
    assert outer.__input_bounded__ is True
    assert outer.__wrapped__.__input_bounded__ is True
    assert outer.__wrapped__.__wrapped__.__name__ == "to_cdm"
    instance = ContextDouble.fixture_instance(clock=times.frozen_clock())
    oversized = b"\xff" * 65
    with pytest.raises(CodedInputTooLarge) as caught:
        instance.to_cdm(oversized)
    assert caught.value.code == "E_PROBE_LIMIT"
    assert isinstance(caught.value, InputTooLarge)
    assert "64" in str(caught.value) and "65" in str(caught.value)
    with pytest.raises(CodedRefusal) as caught:
        instance.to_cdm("FXD1AAAA")
    assert caught.value.code == "E_PROBE_TYPE"
    with pytest.raises(InputTooLarge) as caught:
        outer.__wrapped__(instance, oversized)
    assert type(caught.value) is InputTooLarge


def test_the_double_passes_the_harness_through_the_hook(tree):
    report = harness.run(ContextDouble.fixture_instance(clock=times.frozen_clock()), tree)
    assert report["passed"] == 2
    assert report["failed"] == 0
    assert [r["fixture"] for r in report["results"]] == ["one.bin", "two.bin"]
    assert all(r["checks"]["translate"] == harness.PASS for r in report["results"])


def test_the_double_passes_the_suite_and_the_spawned_worker_through_the_hook(tree):
    report = suite.run(ContextDouble.fixture_instance(clock=times.frozen_clock()), tree)
    assert report["result"] == "CONFORMANT", report
    g = _check(report, "G")
    assert g["fixtures_compared"] == 2
    assert g["undecodable"] == []
    assert _check(report, "K")["identifiers"] == 2
    assert _check(report, "O")["refusal"] == Q + "CodedInputTooLarge"
    h = _check(report, "H")
    assert h["outcomes"] == {"PARSER_REJECTED": 2}
    assert h["refused_by_adapter"] == 2
    assert h["exception_classes"] == [Q + "CodedRefusal"]
    n = _check(report, "N")
    assert n["offsets_tried"] == 14
    assert n["outcomes"] == {"PARSER_REJECTED": 14}


def test_a_hook_refusal_is_not_read_as_the_bound_refusing(tree):
    """Final review F-39: check O builds the adapter through the hook before it feeds anything.

    A refusal raised while building is FAIL, never the adapter refusing the oversized payload,
    which never reached `to_cdm`.
    """
    clock = times.frozen_clock()
    instance = ContextDouble(clock=clock, context="x", synthetic=False)
    payloads = [(p.name, harness.load_raw(p)) for p in suite._fixtures(tree)]
    entry = suite.check_resource_limits(instance, payloads, clock=clock)
    assert entry["verdict"] == suite.FAIL, entry
    assert "fixture_instance" in entry["reason"]
    assert "bytes_fed" not in entry["details"]
    assert suite.exit_status(suite.run(instance, tree), ("O",)) != 0


def test_without_an_override_the_worker_cannot_construct_the_adapter(tree):
    clock = times.frozen_clock()
    entry = suite.check_malformed(RequiresContext(clock=clock, context="given by hand"), tree,
                                  clock=clock)
    assert entry["verdict"] == suite.FAIL
    assert "WORKER_INIT_FAILED" in entry["reason"]
    assert Q + "ContextMissing" in entry["reason"]
    assert entry["details"]["outcomes"] == {"WORKER_INIT_FAILED": 2}


def test_evidence_generate_builds_the_double_through_the_hook(tree, monkeypatch):
    def root():
        return tree.parent
    monkeypatch.setattr(evidence, "fixture_root", root)
    record = evidence.generate(REFERENCE, fixtures=tree)
    assert [h.path for h in record.fixture_hashes] == [
        "fixture-context-double/malformed/short.bin",
        "fixture-context-double/malformed/wrong_magic.bin",
        "fixture-context-double/one.bin",
        "fixture-context-double/two.bin",
    ]
    assert record.adapter["adapter"]["id"] == "fixture-context-double"
    assert record.conformance["result"] == "CONFORMANT"
    checks = record.conformance["checks"]
    assert checks["H"]["verdict"] == suite.PASS
    assert checks["N"]["details"]["outcomes"] == {"PARSER_REJECTED": 14}
    assert record.fixture_provenance.fixtures == 4


@pytest.mark.parametrize("command, prefix", [
    ("harness", "harness: "),
    ("conformance", "synapse conformance: "),
    ("evidence", "synapse evidence: "),
])
def test_a_cli_refuses_caller_fixtures_for_a_shipped_adapter_that_overrides_the_hook(
        command, prefix, tree, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "is_shipped", _shipped)
    out = tmp_path / "out"
    if command == "harness":
        status = harness.main(["--adapter", REFERENCE, "--fixtures", str(tree), "--update-golden"])
    elif command == "conformance":
        status = suite.main(["conformance", "run", "--adapter", REFERENCE, "--fixtures", str(tree)])
    else:
        status = evidence.main(["generate", "--adapter", REFERENCE, "--fixtures", str(tree),
                                "--out", str(out)])
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert captured.err.startswith(prefix + "--fixtures is refused for "), captured.err
    assert Q + "ContextDouble overrides fixture_instance()" in captured.err
    assert not (tree / "golden").exists()
    assert not out.exists()


def test_the_refusal_is_for_shipped_overriding_adapters_only(tree, monkeypatch, capsys):
    assert harness.fixtures_refused_message(REFERENCE, ContextDouble) is None
    assert harness.fixtures_refused_message("pntmap", PntmapAdapter) is None
    assert harness.main(["--adapter", REFERENCE, "--fixtures", str(tree)]) == 0
    assert "2 passed, 0 failed" in capsys.readouterr().out
    assert harness.main(["--adapter", REFERENCE]) == 2
    assert "--fixtures is required" in capsys.readouterr().err
    monkeypatch.setattr(harness, "is_shipped", _shipped)
    reference = "tests.fixture_instance_double:RequiresContext"
    assert harness.fixtures_refused_message(reference, RequiresContext) is None
    assert isinstance(harness.fixtures_refused_message(REFERENCE, ContextDouble), str)


def test_the_api_is_not_restricted_by_the_cli_refusal(tree, monkeypatch):
    def root():
        return tree.parent
    monkeypatch.setattr(harness, "is_shipped", _shipped)
    monkeypatch.setattr(evidence, "fixture_root", root)
    instance = ContextDouble.fixture_instance(clock=times.frozen_clock())
    assert harness.run(instance, tree)["passed"] == 2
    assert evidence.generate(REFERENCE, fixtures=tree).conformance["result"] == "CONFORMANT"


@pytest.mark.parametrize("command, prefix", [
    ("harness", "harness: "),
    ("conformance", "synapse conformance: "),
])
def test_a_refusal_raised_by_the_hook_is_exit_2(command, prefix, tree, capsys):
    if command == "harness":
        status = harness.main(["--adapter", REFERENCE, "--fixtures", str(tree),
                               "--synthetic", "false"])
    else:
        status = suite.main(["conformance", "run", "--adapter", REFERENCE, "--fixtures", str(tree),
                             "--synthetic", "false"])
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert captured.err == prefix + "the fixture context is synthetic; synthetic=False is refused\n"


@pytest.mark.parametrize("command, prefix", [
    ("harness", "harness: "),
    ("conformance", "synapse conformance: "),
])
def test_a_staticmethod_hook_is_an_override_and_its_refusal_is_exit_2(command, prefix, tree,
                                                                     capsys):
    static = "tests.fixture_instance_double:StaticRefusal"
    assert harness.overrides_fixture_instance(fixture_instance_double.StaticRefusal) is True
    if command == "harness":
        status = harness.main(["--adapter", static, "--fixtures", str(tree)])
    else:
        status = suite.main(["conformance", "run", "--adapter", static, "--fixtures", str(tree)])
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert captured.err == prefix + "the static hook refuses\n"


def test_a_constructor_error_without_an_override_still_propagates(tree, monkeypatch):
    unoverridden = "tests.fixture_instance_double:RequiresContext"
    with pytest.raises(ContextMissing):
        harness.main(["--adapter", unoverridden, "--fixtures", str(tree)])
    with pytest.raises(ContextMissing):
        suite.main(["conformance", "run", "--adapter", unoverridden, "--fixtures", str(tree)])

    def roster():
        return {"fixture-context-required": RequiresContext}
    monkeypatch.setattr(suite, "shipped_adapters", roster)
    with pytest.raises(ContextMissing):
        suite.main(["conformance", "run", "--all"])
    assert harness.overrides_fixture_instance(ContextDouble) is True
    assert harness.overrides_fixture_instance(RequiresContext) is False
    assert harness.overrides_fixture_instance(PntmapAdapter) is False


def test_a_hook_refusal_fails_one_row_and_the_sweep_continues(monkeypatch, capsys):
    def roster():
        return {"fixture-context-double": ContextDouble, "pntmap": PntmapAdapter}
    monkeypatch.setattr(suite, "shipped_adapters", roster)
    status = suite.main(["conformance", "run", "--all", "--synthetic", "false", "--format", "json"])
    captured = capsys.readouterr()
    assert status == suite.EXIT_USAGE == 2
    assert captured.err.startswith(
        "synapse conformance: fixture-context-double: the fixture context is synthetic"), \
        captured.err
    assert sorted(json.loads(captured.out)["adapters"]) == ["pntmap"]
