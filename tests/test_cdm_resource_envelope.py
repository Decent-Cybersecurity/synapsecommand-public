"""Audit remediation F06: the resource-limit and streaming claims, held to executable tests.

WHAT THIS MODULE IS FOR
-----------------------
`docs/docs/security/parser-safety.mdx` declares five bounds and says which are enforced; the
existing tests prove the one-over case for size (`test_cdm_input_bounds.py`) and the one-over
and thousand-deep cases for depth (`test_cdm_parser_safety.py`). What was missing, and is here:

1. **The boundary itself.** A payload AT the byte bound is not refused by the size guard; one
   octet past it is, in every octet form the guard counts (bytes, bytearray, memoryview, and
   text as UTF-8 octets rather than characters). A JSON document AT the depth bound is not refused
   by the depth guard; one level past it is, as text and as a parsed twin. An XML tree at the
   bound translates and one past it is refused with the adapter's own `ValueError`.
2. **Which bound runs before which allocation.** The size guard reads `len()` and allocates
   nothing, and it runs FIRST — so a document that is both oversized and too deep is refused for
   its size, and the depth scan never reads more than `max_input_bytes`. The fixture loader,
   the one place this package parses JSON before any adapter's bound can apply, now measures the
   text before `json.loads` (`harness.LOADER_MAX_DEPTH`) and can check a file's size on `stat()`
   before reading it (`harness.LOADER_MAX_BYTES`, a hosting application's knob, off by default).
3. **The worker's envelope is platform-specific and says so.** `suite.ResourceLimits` asks for
   an `RLIMIT_AS` / `RLIMIT_CPU` envelope; `suite.resource_limit_support()` answers per field
   for THIS platform; a request the platform cannot honour is refused with
   `UnsupportedResourceLimit` before a worker exists and with exit 2 from the CLI. Where the
   platform enforces a limit (Linux), the memory hog dies as a crash class and the spinning
   parser is ended by `SIGXCPU` (soft limit; the hard limit sits one second above it, since
   equal limits make Linux send `SIGKILL` — S10, 2026-09-20). Every platform asserts the
   enforcement branch that applies to it, never a skip; the pair ITSELF is read back from a
   spawned worker wherever `RLIMIT_CPU` exists (the one reasoned skip in this module, where the
   platform has no such limit to read — 2026-09-20, the final review).
4. **Streaming is SKIP, never PASS, and says what is absent.** Check M carries the four
   properties a streaming contract would consist of, each "not implemented"/"not applicable".
5. **`integrity` is a container.** Nothing in the package reads or fills it, its description
   says so, and a record carrying a block is not thereby verified.

Sizes are small by construction: the deepest document is fifty thousand brackets (100 KB), the
largest a mebibyte and one, and the memory hog RESERVES address space without touching a page,
so the module costs no memory where nothing enforces the limit it is testing.
"""
from __future__ import annotations

import ast
import json
import multiprocessing
import os
import pathlib
import signal
import sys
import time
from types import SimpleNamespace

import pytest

import synapse_cdm
from synapse_cdm import harness, suite, times
from synapse_cdm.adapter import (InputTooDeep, InputTooLarge, discover, json_nesting_depth,
                                 packaged_fixtures, roster)
from synapse_cdm.models import Entity, Integrity
from tests import synthetic_parsers as sp

REPO = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = pathlib.Path(synapse_cdm.__file__).parent
ENVELOPE_PAGE = REPO / "docs" / "docs" / "security" / "deployment-envelope.mdx"
POLICY = REPO / "SECURITY.md"

#: Generous on purpose: where a CPU limit is enforced, the LIMIT and not the deadline must be
#: what ends the spinning case, so the deadline sits well past it.
DEADLINE_S = 10.0
STARTUP_S = 30.0
BUDGET_S = 45.0

#: What the enforcement tests ask for where the platform can honour it. Two GiB of address space
#: is far above a spawned interpreter's footprint and far below the hog's reservation; three CPU
#: seconds are more than the worker's bootstrap spends and less than the spin.
MEMORY_LIMIT = 2 << 30
CPU_LIMIT_S = 3

SUPPORT = suite.resource_limit_support()


def shipped() -> dict:
    discover()
    return {name: cls for name, cls in roster().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


ADAPTERS = sorted(shipped())
JSON_ADAPTERS = ("adsb", "ais", "legion", "pntmap", "tak")
XML_ADAPTERS = ("stanag4676", "tak")


def _limits(name):
    return shipped()[name].metadata.capabilities.limits


def _fresh(name):
    return shipped()[name]()


def _the_guard_is_silent(name, payload, guard: type[Exception]) -> None:
    """`to_cdm` on a payload AT a bound: the named guard must not speak. The decoder's own
    refusal of a nonsense document is not the subject and is allowed."""
    try:
        _fresh(name).to_cdm(payload)
    except guard as e:
        pytest.fail(f"{name}: {guard.__name__} spoke at the bound itself: {e}")
    except Exception:       # noqa: BLE001 - the decoder refusing nonsense is not what is tested
        pass


# --------------------------------------------------------------- 1. the byte bound, at and past

@pytest.mark.parametrize("name", ADAPTERS)
def test_the_byte_bound_is_inclusive_at_the_bound_and_refuses_one_octet_past_it(name):
    bound = _limits(name).max_input_bytes
    _the_guard_is_silent(name, b"\xff" * bound, InputTooLarge)
    with pytest.raises(InputTooLarge) as raised:
        _fresh(name).to_cdm(b"\xff" * (bound + 1))
    assert str(bound) in str(raised.value) and str(bound + 1) in str(raised.value)


@pytest.mark.parametrize("name", ADAPTERS)
def test_text_is_bounded_by_its_utf8_octets_and_not_by_its_character_count(name):
    """`wire_size` counts text as the octets it would have been on the wire. A string of `bound`
    characters whose last one is two octets long is one octet over, and is refused."""
    bound = _limits(name).max_input_bytes
    _the_guard_is_silent(name, "x" * bound, InputTooLarge)
    text = "x" * (bound - 1) + "é"
    assert len(text) == bound and len(text.encode("utf-8")) == bound + 1
    with pytest.raises(InputTooLarge) as raised:
        _fresh(name).to_cdm(text)
    assert str(bound + 1) in str(raised.value)


@pytest.mark.parametrize("name", ADAPTERS)
def test_every_octet_form_is_counted_the_same_way(name):
    bound = _limits(name).max_input_bytes
    over = b"\xff" * (bound + 1)
    for form in (bytearray(over), memoryview(over)):
        with pytest.raises(InputTooLarge):
            _fresh(name).to_cdm(form)


# --------------------------------------------------------------- 2. the depth bound, at and past

def _nested_json(depth: int) -> str:
    return "[" * depth + "]" * depth


def _nested_list(depth: int) -> list:
    node: list = []
    for _ in range(depth - 1):
        node = [node]
    return node


@pytest.mark.parametrize("name", JSON_ADAPTERS)
def test_the_depth_bound_is_inclusive_at_the_bound_and_refuses_one_level_past_it(name):
    limits = _limits(name)
    bound = limits.max_depth
    assert bound is not None
    _the_guard_is_silent(name, _nested_list(bound), InputTooDeep)
    text = _nested_json(bound)
    if len(text) <= limits.max_input_bytes:
        _the_guard_is_silent(name, text, InputTooDeep)
    else:
        assert name == "adsb", f"{name}: sixty-four nested containers do not fit the size bound"
    with pytest.raises(InputTooDeep, match=f"nesting {bound + 1} containers deep"):
        _fresh(name).to_cdm(_nested_list(bound + 1))


@pytest.mark.parametrize("name", JSON_ADAPTERS)
def test_the_size_guard_runs_before_the_depth_scan_reads_a_byte(name):
    """A document that is oversized AND too deep is refused for its SIZE. The size guard reads
    `len()` and allocates nothing; the depth scan decodes the text, so it must only ever run on
    text the size guard has already admitted — at most `max_input_bytes` of it."""
    limits = _limits(name)
    depth = limits.max_depth + 1
    text = "[" * depth + " " * (limits.max_input_bytes + 1) + "]" * depth
    assert json_nesting_depth(text) == depth and len(text) > limits.max_input_bytes
    with pytest.raises(InputTooLarge):
        _fresh(name).to_cdm(text)


def _nested_xml(name: str, depth: int) -> bytes:
    """Shaped as `tests/test_cdm_parser_safety.py` shapes it: refused for depth and nothing else."""
    if name == "tak":
        inner = "<n>" * (depth - 2) + "</n>" * (depth - 2)
        return ('<event uid="x" type="a-f-G" time="2026-01-01T00:00:00Z" '
                'start="2026-01-01T00:00:00Z" stale="2026-01-01T00:01:00Z" how="m-g">'
                f'<point lat="1" lon="2"/><detail>{inner}</detail></event>').encode()
    body = (PACKAGE / "fixtures" / "nits" / "standalone_basic_track.nits.xml").read_text()
    chain = "<extension>" * (depth - 1) + "</extension>" * (depth - 1)
    return body.replace("</NITSRoot>", chain + "</NITSRoot>").encode()


@pytest.mark.parametrize("name", XML_ADAPTERS)
def test_an_xml_tree_at_the_bound_translates_one_past_it_is_refused_and_size_still_runs_first(name):
    limits = _limits(name)
    bound = limits.max_depth
    at = _nested_xml(name, bound)
    assert len(at) < limits.max_input_bytes
    assert _fresh(name).to_cdm(at), "a document at the bound is accepted"
    with pytest.raises(ValueError, match=f"{bound + 1} elements deep") as raised:
        _fresh(name).to_cdm(_nested_xml(name, bound + 1))
    assert not isinstance(raised.value, (RecursionError, InputTooDeep))
    # The tree is measured AFTER expat builds it — only the adapter holds it — so what bounds
    # that allocation is the size guard, and it speaks before the parser sees a byte.
    padded = b"<!--" + b" " * (limits.max_input_bytes + 1) + b"-->" + _nested_xml(name, bound + 1)
    with pytest.raises(InputTooLarge):
        _fresh(name).to_cdm(padded)


# --------------------------------------------------------------- 3. the fixture loader's bounds

def test_the_loader_measures_a_json_fixture_before_the_decoder_sees_it(tmp_path):
    at = tmp_path / "at.json"
    at.write_text(_nested_json(harness.LOADER_MAX_DEPTH))
    assert isinstance(harness.load_raw(at), list)
    over = tmp_path / "over.json"
    over.write_text(_nested_json(harness.LOADER_MAX_DEPTH + 1))
    with pytest.raises(harness.FixtureTooDeep,
                       match=f"nests {harness.LOADER_MAX_DEPTH + 1} containers deep"):
        harness.load_raw(over)
    deep = tmp_path / "deep.json"
    deep.write_text(_nested_json(50_000))
    with pytest.raises(harness.FixtureTooDeep) as raised:
        harness.load_raw(deep)
    assert not isinstance(raised.value, RecursionError)
    assert isinstance(harness.load_raw(over, max_depth=0), list), "0 switches the bound off"


def test_the_loader_byte_bound_is_off_by_default_and_checked_on_stat_before_any_read(
        tmp_path, monkeypatch):
    assert harness.LOADER_MAX_BYTES is None, "no document states a figure, so none is defaulted"
    big = tmp_path / "big.bin"
    big.write_bytes(b"\xff" * 4096)
    twin = tmp_path / "twin.json"
    twin.write_text("{}")
    assert harness.load_raw(big) == b"\xff" * 4096
    assert harness.load_raw(twin) == {}

    def never(self, *args, **kwargs):
        raise AssertionError(f"{self.name} was read before its size was checked")

    monkeypatch.setattr(pathlib.Path, "read_bytes", never)
    monkeypatch.setattr(pathlib.Path, "read_text", never)
    with pytest.raises(harness.FixtureTooLarge, match="4096 octets on disk"):
        harness.load_raw(big, max_bytes=4095)
    with pytest.raises(harness.FixtureTooLarge):
        harness.load_raw(twin, max_bytes=1)


def test_no_shipped_json_file_is_near_the_loader_bound():
    """Read from the tree, goldens included: the bound is a cap and not a hair trigger."""
    deepest = 0
    for name, cls in shipped().items():
        for path in packaged_fixtures(cls).rglob("*.json"):
            deepest = max(deepest, json_nesting_depth(path.read_text()))
    assert 0 < deepest and deepest * 4 <= harness.LOADER_MAX_DEPTH, (
        f"the deepest shipped .json nests {deepest} against LOADER_MAX_DEPTH "
        f"{harness.LOADER_MAX_DEPTH}; re-derive the figure rather than widen this assertion")


# --------------------------------------------------------------- the worker, shared helpers

def _tree(tmp_path: pathlib.Path, first: tuple[str, bytes] = ("a_provoke.bin", sp.MARKER)):
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / first[0]).write_bytes(first[1])
    (malformed / "b_plain.bin").write_bytes(b"plain")
    return tmp_path


def _H(cls, tree, *, limits: suite.ResourceLimits | None = None):
    clock = times.frozen_clock()
    diagnostics: dict = {}
    started = time.perf_counter()
    with suite.ParserWorker(cls(clock=clock), clock=clock, timeout_s=DEADLINE_S,
                            startup_timeout_s=STARTUP_S, diagnostics=diagnostics,
                            limits=limits) as worker:
        entry = suite.check_malformed(cls(clock=clock), tree, clock=clock, worker=worker)
    elapsed = time.perf_counter() - started
    assert elapsed < BUDGET_S, f"the check took {elapsed:.1f}s against a {BUDGET_S}s budget"
    return entry, diagnostics


def _outcomes(entry):
    return [case["outcome"] for case in entry["details"]["cases"]]


def _no_orphans(diagnostics: dict) -> None:
    assert multiprocessing.active_children() == [], "a worker outlived the check"
    assert diagnostics["workers"], "the diagnostics record no worker at all"
    if os.name == "posix":
        for record in diagnostics["workers"]:
            with pytest.raises(ProcessLookupError):
                os.kill(record["pid"], 0)


def test_a_deep_twin_reaches_the_worker_as_a_loader_rejection_and_not_a_crash(tmp_path):
    """The loader layer is inside the worker's deadline and inside its bounds: a `.json`
    payload five thousand deep is REJECTED by the loader on every interpreter in the matrix,
    where before this bound CPython 3.11 crashed in `json.loads` before the adapter was asked."""
    tree = _tree(tmp_path, first=("a_deep.json", _nested_json(5000).encode()))
    entry, diagnostics = _H(sp.Refusing, tree)
    assert entry["verdict"] == suite.PASS
    assert _outcomes(entry) == [suite.PARSER_REJECTED, suite.PARSER_REJECTED]
    text = json.dumps(entry)
    assert "FixtureTooDeep" in text and "RecursionError" not in text
    _no_orphans(diagnostics)


# --------------------------------------------------------------- 4. the worker's envelope

def test_resource_limit_support_answers_for_both_fields_with_a_reason():
    assert set(SUPPORT) == {"memory_bytes", "cpu_seconds"}
    for name, (enforced, reason) in SUPPORT.items():
        assert isinstance(enforced, bool) and len(reason) > 20, (name, enforced, reason)
    if sys.platform in ("darwin", "win32"):
        assert not any(enforced for enforced, _ in SUPPORT.values()), SUPPORT
    if sys.platform.startswith("linux"):
        assert all(enforced for enforced, _ in SUPPORT.values()), SUPPORT


def test_an_unavailable_limit_is_refused_before_a_worker_exists():
    clock = times.frozen_clock()
    figure = {"memory_bytes": MEMORY_LIMIT, "cpu_seconds": CPU_LIMIT_S}
    for name, (enforced, _) in SUPPORT.items():
        limits = suite.ResourceLimits(**{name: figure[name]})
        if enforced:
            with suite.ParserWorker(sp.Refusing(clock=clock), clock=clock, limits=limits) as w:
                assert w.limits.requested() == {name: figure[name]}
            continue
        with pytest.raises(suite.UnsupportedResourceLimit, match=name) as raised:
            suite.ParserWorker(sp.Refusing(clock=clock), clock=clock, limits=limits)
        assert sys.platform in str(raised.value) and "cannot enforce" in str(raised.value)
        assert multiprocessing.active_children() == [], "a refusal must spawn nothing"
    with pytest.raises(suite.UnsupportedResourceLimit, match="positive"):
        suite.ResourceLimits(cpu_seconds=0).validate()
    assert suite.ResourceLimits().requested() == {}, "no limit is the default, on every platform"


def test_the_cli_refuses_an_unenforceable_or_nonsensical_limit_with_the_usage_exit_code(capsys):
    run = ["conformance", "run", "--adapter", "pntmap"]
    assert suite.main([*run, "--cpu-limit-seconds", "0"]) == suite.EXIT_USAGE
    assert "positive" in capsys.readouterr().err
    flags = {"memory_bytes": "--memory-limit-bytes", "cpu_seconds": "--cpu-limit-seconds"}
    for name, (enforced, _) in SUPPORT.items():
        if enforced:
            continue
        code = suite.main([*run, flags[name], str(1 << 30)])
        err = capsys.readouterr().err
        assert code == suite.EXIT_USAGE, err
        assert name in err and "cannot enforce" in err and sys.platform in err


def test_a_memory_limit_ends_a_hog_as_a_crash_class_where_the_platform_enforces_it(tmp_path):
    limits = suite.ResourceLimits(memory_bytes=MEMORY_LIMIT)
    if not SUPPORT["memory_bytes"][0]:
        with pytest.raises(suite.UnsupportedResourceLimit, match="memory_bytes"):
            limits.validate()
        return
    entry, diagnostics = _H(sp.MemoryHog, _tree(tmp_path), limits=limits)
    assert entry["verdict"] == suite.FAIL
    assert _outcomes(entry) == [suite.PARSER_CRASH, suite.PARSER_REJECTED], (
        "the hog must die as a crash class and the plain case must still run")
    assert "MemoryError" in json.dumps(entry) + json.dumps(diagnostics)
    assert entry["details"]["resource_limits"] == {"memory_bytes": MEMORY_LIMIT}
    _no_orphans(diagnostics)


def test_a_cpu_limit_ends_a_spinning_parser_where_the_platform_enforces_it(tmp_path):
    limits = suite.ResourceLimits(cpu_seconds=CPU_LIMIT_S)
    if not SUPPORT["cpu_seconds"][0]:
        with pytest.raises(suite.UnsupportedResourceLimit, match="cpu_seconds"):
            limits.validate()
        return
    entry, diagnostics = _H(sp.Spinning, _tree(tmp_path), limits=limits)
    assert entry["verdict"] == suite.FAIL
    assert _outcomes(entry) == [suite.PARSER_CRASH, suite.PARSER_REJECTED]
    assert diagnostics["workers"][0]["exit_code"] == -signal.SIGXCPU, diagnostics["workers"]
    assert entry["details"]["resource_limits"] == {"cpu_seconds": CPU_LIMIT_S}
    _no_orphans(diagnostics)


def test_the_cpu_limit_pair_the_worker_sets_is_soft_n_and_hard_n_plus_one():
    """S10 (2026-09-20) set `RLIMIT_CPU` to `(value, value + 1)` in `suite._apply_resource_limits`
    so Linux delivers `SIGXCPU` at the soft limit instead of `SIGKILL` at a hard limit equal to
    it; the enforcement test above observes that only where the platform enforces the limit.
    This reads the PAIR back on every platform that has `RLIMIT_CPU`: a worker is spawned by
    `suite._worker_main` — the target `ParserWorker._start` spawns, with the same argument list
    and the limit dict `ResourceLimits.requested()` hands it — and the double refuses to
    initialise with the pair it read, so the reading arrives as the init-error reply.
    `ParserWorker` is not used because `validate()` refuses `cpu_seconds` wherever the platform
    does not ENFORCE it (macOS accepts the syscall and enforces nothing), and what is under test
    is what the syscall was given, not whether it bites."""
    try:
        import resource
    except ImportError:
        pytest.skip(f"{sys.platform}: no `resource` module, so RLIMIT_CPU cannot be read back")
    if not hasattr(resource, "RLIMIT_CPU"):
        pytest.skip(f"{sys.platform}: `resource.RLIMIT_CPU` is absent, so there is no pair to read")
    limits = suite.ResourceLimits(cpu_seconds=CPU_LIMIT_S)
    assert limits.requested() == {"cpu_seconds": CPU_LIMIT_S}
    clock = times.frozen_clock()
    adapter = sp.CpuLimitReporting(clock=clock)
    ctx = multiprocessing.get_context("spawn")
    inbox_r, inbox_w = ctx.Pipe(duplex=False)
    outbox_r, outbox_w = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=suite._worker_main, name="parser-worker:cpu-limit-pair",
                       args=(inbox_r, outbox_w, suite.adapter_reference(adapter),
                             clock().isoformat(), adapter._synthetic, suite.OUTPUT_CAP_BYTES,
                             limits.requested()), daemon=True)
    proc.start()
    inbox_r.close()
    outbox_w.close()
    try:
        assert outbox_r.poll(STARTUP_S), "the worker sent nothing within the start-up budget"
        reply = json.loads(outbox_r.recv_bytes(suite.OUTPUT_CAP_BYTES))
    finally:
        inbox_w.close()
        outbox_r.close()
        proc.join(DEADLINE_S)
        if proc.is_alive():
            proc.kill()
            proc.join()
    assert "RuntimeError" in (reply.get("init_error") or ""), reply
    assert reply["detail"] == f"RLIMIT_CPU soft={CPU_LIMIT_S} hard={CPU_LIMIT_S + 1}", reply
    assert multiprocessing.active_children() == [], "the worker outlived the reading"


def test_a_default_run_writes_no_resource_limits_key_and_a_requested_one_does(tmp_path):
    """The canonical details name a limit only when one was asked for — a default run's bytes
    do not move — while the diagnostics always carry the request and the platform's answer."""
    entry, diagnostics = _H(sp.Refusing, _tree(tmp_path))
    assert "resource_limits" not in entry["details"]
    assert entry["details"]["isolation"] == suite.ISOLATION
    assert diagnostics["resource_limits"] == {}
    assert set(diagnostics["resource_limit_support"]) == {"memory_bytes", "cpu_seconds"}
    for answer in diagnostics["resource_limit_support"].values():
        assert set(answer) == {"enforced", "reason"}
    stub = SimpleNamespace(timeout_s=1.0, startup_timeout_s=2.0, max_restarts=3,
                           limits=suite.ResourceLimits(cpu_seconds=CPU_LIMIT_S))
    assert suite._worker_bounds(stub)["resource_limits"] == {"cpu_seconds": CPU_LIMIT_S}
    stub.limits = suite.ResourceLimits()
    assert "resource_limits" not in suite._worker_bounds(stub)


# --------------------------------------------------------------- 5. streaming: SKIP, never PASS

@pytest.mark.parametrize("name", ADAPTERS)
def test_check_m_is_a_declared_skip_that_names_the_four_absent_properties(name):
    entry = suite.check_streaming(_fresh(name))
    assert entry["verdict"] == suite.SKIP and entry["declared_inapplicable"] is True
    statuses = entry["details"]["streaming"]
    assert set(statuses) == {"chunk_framing", "partial_messages", "reassembly", "backpressure"}
    for key, status in statuses.items():
        assert status.startswith(("not implemented", "not applicable")), (key, status)
    assert statuses == suite.STREAMING_STATUS


def test_requiring_check_m_makes_the_invocation_unsuccessful_without_rewriting_the_verdict():
    entry = suite.check_streaming(_fresh("pntmap"))
    report = {"checks": {"M": entry}}
    assert suite.exit_status(report, ("M",)) != suite.EXIT_OK
    assert report["checks"]["M"]["verdict"] == suite.SKIP, "the verdict is not rewritten"


# --------------------------------------------------------------- 6. integrity is a container

def test_the_integrity_field_is_described_as_a_container_and_nothing_reads_or_fills_it():
    description = Entity.model_fields["integrity"].description
    assert "DATA CONTAINER" in description and "verifies none" in description
    schema = (REPO / "schemas" / "cdm_object.schema.json").read_text()
    assert "DATA CONTAINER" in schema, "the generated schema carries the same sentence"
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "models.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr == "integrity":
                offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno} reads .integrity")
            if isinstance(node, ast.keyword) and node.arg == "integrity":
                offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno} sets integrity=")
    assert not offenders, offenders


def test_a_record_carrying_an_integrity_block_is_not_thereby_verified():
    clock = times.frozen_clock()
    plain = sp.Normal(clock=clock).to_cdm(sp.MARKER)[0]
    block = Integrity(signature="c2lnbmF0dXJl", algorithm="ML-DSA-87", chain_hash="00" * 32)
    carrying = plain.model_copy(update={"integrity": block})
    dumped = carrying.model_dump(mode="json")
    assert dumped["integrity"] == block.model_dump(mode="json")
    assert {**dumped, "integrity": None} == plain.model_dump(mode="json"), \
        "the block changes nothing else"
    assert "verified" not in json.dumps(dumped).lower()
    with pytest.raises(ValueError):
        Integrity(signature="c2lnbmF0dXJl")     # a partial block is refused: all three or none


# --------------------------------------------------------------- 7. the published envelope

def test_the_envelope_page_states_the_three_layers_the_platform_table_and_the_absences():
    body = ENVELOPE_PAGE.read_text()
    for heading in ("## 1. The library", "## 2. The conformance worker",
                    "## 3. The hosting application", "## 4. Streaming", "## 5. Integrity"):
        assert heading in body, heading
    for platform in ("Linux", "macOS", "Windows"):
        assert platform in body, platform
    for key in suite.STREAMING_STATUS:
        assert f"`{key}`" in body, key
    assert "data container" in body.lower()
    assert "UnsupportedResourceLimit" in body and "LOADER_MAX_DEPTH" in body
    # The page's platform rows say what the code says on this platform.
    for name, (enforced, _) in SUPPORT.items():
        assert f"`{name}`" in body, name
    if sys.platform == "darwin":
        assert "EINVAL" in body and "not enforced" in body


def test_the_security_policy_carries_the_three_f06_rows():
    body = POLICY.read_text()
    table = body[body.index("## Controls"):body.index("## Handling a report")]
    rows = {line.split("|")[1].strip(): line for line in table.splitlines() if line.startswith("|")}
    for label, state in (("Resource isolation of the conformance worker", "**active**"),
                         ("Streaming input", "**not provided**"),
                         ("Verification of the `integrity` block", "**not provided**")):
        assert label in rows, f"SECURITY.md has no control row {label!r}"
        assert state in rows[label], rows[label]
