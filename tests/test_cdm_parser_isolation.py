"""Audit remediation F03: the conformance suite's adversarial parser checks run in a killable
process and a deadline is ENFORCED, not merely measured after the fact.

Until this round checks H (`suite.check_malformed`) and N (`suite.check_parser_robustness`)
called the adapter in-process and compared the wall clock after `to_cdm` returned. That reads a
slow parser correctly and a non-returning one never: the sweep hangs before any verdict exists.
The adapters under test are the six in `tests/synthetic_parsers.py` — normal, refusing, hard
crash, slow, never-returning, init-failing — each provoked by one fixture and left alone by the
next, so every test asserts BOTH that the failure was contained and that the following case ran.

Timing here is deliberately coarse: deadlines of half a second, an overall budget of ten, and
never a millisecond comparison. What is exact is the outcome code, the verdict, the absence of
a live child, and the absence of a wall-clock reading in the canonical details.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import pathlib
import socket
import time

import pytest

from synapse_cdm import suite, times
from synapse_cdm.adapters.pntmap import PntmapAdapter

from tests import synthetic_parsers as sp

DEADLINE_S = 0.5
STARTUP_S = 10.0
BUDGET_S = 10.0

#: Keys whose presence in canonical evidence would make its digest a function of the machine.
VOLATILE_KEYS = ("pid", "pids", "exit_code", "exitcode", "duration_s", "elapsed", "elapsed_s",
                 "seconds", "started", "finished")


def _tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """`malformed/` with the provoking payload FIRST, so the plain one proves the worker ran on."""
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "a_provoke.bin").write_bytes(sp.MARKER)
    (malformed / "b_plain.bin").write_bytes(b"plain")
    return tmp_path


def _walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    else:
        yield path, node


def _no_orphans(diagnostics: dict) -> None:
    assert multiprocessing.active_children() == [], "a worker outlived the check"
    pids = diagnostics["workers"]
    assert pids, "the diagnostics record no worker at all"
    if os.name == "posix":
        for entry in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(entry["pid"], 0)


def _H(cls, tree, **kwargs):
    clock = times.frozen_clock()
    diagnostics: dict = {}
    started = time.perf_counter()
    entry = suite.check_malformed(cls(clock=clock), tree, clock=clock, timeout_s=DEADLINE_S,
                                  startup_timeout_s=STARTUP_S, diagnostics=diagnostics, **kwargs)
    elapsed = time.perf_counter() - started
    assert elapsed < BUDGET_S, f"the check took {elapsed:.1f}s against a {BUDGET_S}s budget"
    return entry, diagnostics


def _outcomes(entry):
    return [c["outcome"] for c in entry["details"]["cases"]]


def test_the_outcome_codes_are_the_five_the_plan_named_plus_acceptance():
    assert suite.OUTCOME_CODES == ("PARSER_REJECTED", "PARSER_ACCEPTED", "PARSER_TIMEOUT",
                                   "PARSER_CRASH", "WORKER_INIT_FAILED", "HARNESS_ERROR")
    assert suite.PARSER_REJECTED not in suite.FAILING_OUTCOMES
    for code in suite.OUTCOME_CODES[1:]:
        assert code in suite.FAILING_OUTCOMES


def test_a_shipped_adapter_travels_by_registry_name_and_a_double_by_module_path():
    clock = times.frozen_clock()
    assert suite.adapter_reference(PntmapAdapter(clock=clock)) == "pntmap"
    assert suite.adapter_reference(sp.Normal(clock=clock)) == "tests.synthetic_parsers:Normal"


def test_a_refusing_adapter_passes_and_every_case_is_a_controlled_rejection(tmp_path):
    entry, diagnostics = _H(sp.Refusing, _tree(tmp_path))
    assert entry["verdict"] == suite.PASS
    assert _outcomes(entry) == [suite.PARSER_REJECTED, suite.PARSER_REJECTED]
    assert entry["details"]["refused_by_adapter"] == 2
    assert entry["details"]["outcomes"] == {suite.PARSER_REJECTED: 2}
    _no_orphans(diagnostics)


def test_a_normal_adapter_that_accepts_a_malformed_payload_fails(tmp_path):
    entry, diagnostics = _H(sp.Normal, _tree(tmp_path))
    assert entry["verdict"] == suite.FAIL and "ACCEPTED" in entry["reason"]
    assert entry["details"]["accepted"] == ["a_provoke.bin: returned 1 object(s)"]
    assert _outcomes(entry) == [suite.PARSER_ACCEPTED, suite.PARSER_REJECTED]
    assert entry["details"]["outcomes"] == {suite.PARSER_ACCEPTED: 1, suite.PARSER_REJECTED: 1}
    _no_orphans(diagnostics)


def test_a_hard_crash_kills_the_worker_is_recorded_and_the_next_case_still_runs(tmp_path):
    entry, diagnostics = _H(sp.HardCrashing, _tree(tmp_path))
    assert entry["verdict"] == suite.FAIL and "crash" in entry["reason"]
    assert _outcomes(entry) == [suite.PARSER_CRASH, suite.PARSER_REJECTED]
    assert entry["details"]["crashed"] == ["a_provoke.bin: PARSER_CRASH"]
    assert entry["details"]["refused_by_adapter"] == 1
    # The worker that died is not the one that ran the second case.
    assert diagnostics["restarts"] == 1 and len(diagnostics["workers"]) == 2
    assert diagnostics["workers"][0]["exit_code"] == sp.CRASH_EXIT_CODE
    _no_orphans(diagnostics)


def test_a_slow_parser_is_a_timeout_is_terminated_and_the_next_case_still_runs(tmp_path):
    entry, diagnostics = _H(sp.Slow, _tree(tmp_path))
    assert entry["verdict"] == suite.FAIL
    assert "PARSER_TIMEOUT" in entry["reason"] and "refused" not in entry["reason"].lower()
    assert _outcomes(entry) == [suite.PARSER_TIMEOUT, suite.PARSER_REJECTED]
    # A timeout is not a refusal row: the row shape H has published since round PB is unchanged
    # and the killed case is recorded by its code, in order, beside the one that ran after it.
    assert entry["details"]["cases"] == [{"fixture": "a_provoke.bin", "outcome": "PARSER_TIMEOUT"},
                                         {"fixture": "b_plain.bin", "outcome": "PARSER_REJECTED"}]
    assert [r["fixture"] for r in entry["details"]["refusals"]] == ["b_plain.bin"]
    assert all(set(r) == {"fixture", "refused_by", "exception", "over_time_bound"}
               for r in entry["details"]["refusals"])
    assert entry["details"]["over_time_bound"] == ["a_provoke.bin"]
    assert diagnostics["restarts"] == 1
    _no_orphans(diagnostics)


def test_a_parser_that_never_returns_and_ignores_sigterm_is_killed_within_the_bound(tmp_path):
    entry, diagnostics = _H(sp.NeverReturns, _tree(tmp_path))
    assert entry["verdict"] == suite.FAIL
    assert _outcomes(entry) == [suite.PARSER_TIMEOUT, suite.PARSER_REJECTED]
    first = diagnostics["workers"][0]
    assert first["killed"] is True, "SIGTERM was ignored, so the escalation to kill() had to run"
    assert first["duration_s"] < DEADLINE_S + suite.KILL_GRACE_S + 5.0
    _no_orphans(diagnostics)


def test_a_timeout_is_never_counted_as_a_successful_rejection(tmp_path):
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "only_provoke.bin").write_bytes(sp.MARKER)
    entry, diagnostics = _H(sp.Slow, tmp_path)
    assert entry["verdict"] == suite.FAIL
    assert entry["details"]["refused_by_adapter"] == 0
    assert entry["details"]["exception_classes"] == []
    _no_orphans(diagnostics)


def test_an_adapter_that_fails_to_initialise_is_a_worker_init_failure_not_a_pass(tmp_path):
    entry, diagnostics = _H(sp.InitFailing, _tree(tmp_path))
    assert entry["verdict"] == suite.FAIL and "WORKER_INIT_FAILED" in entry["reason"]
    assert "RuntimeError" in entry["reason"]
    assert entry["details"]["refused_by_adapter"] == 0
    assert entry["details"]["outcomes"] == {suite.WORKER_INIT_FAILED: 2}
    assert entry["details"]["cases_not_run"] == 2
    _no_orphans(diagnostics)


def test_an_oversized_refusal_message_is_capped_and_the_class_is_still_recorded(tmp_path):
    entry, diagnostics = _H(sp.LoudRefusing, _tree(tmp_path))
    assert entry["verdict"] == suite.PASS
    for refusal in entry["details"]["refusals"]:
        assert refusal["exception"] == "builtins.ValueError"
        assert len(json.dumps(refusal)) <= suite.OUTPUT_CAP_BYTES
    _no_orphans(diagnostics)


def test_an_undecodable_worker_reply_is_a_harness_error_and_the_worker_is_restarted(tmp_path):
    """S10 (2026-09-20), from the S3 review: `_send`'s last resort clips the encoded reply to the
    cap, and a clipped JSON document does not decode. That is the harness's failure, not the
    parser's, so it is `HARNESS_ERROR` with the worker restarted — never an exception out of the
    check. Driven by replacing `_receive` for ONE case so the real pipe is not corrupted."""
    clock = times.frozen_clock()
    diagnostics: dict = {}
    tree = _tree(tmp_path)
    with suite.ParserWorker(sp.Refusing(clock=clock), clock=clock, timeout_s=DEADLINE_S,
                            startup_timeout_s=STARTUP_S, diagnostics=diagnostics) as worker:
        real = worker._receive

        def clipped(timeout):
            raise json.JSONDecodeError("Unterminated string", '{"outcome": "PARSER_R', 21)

        started = worker._run_case(tree / "malformed" / "a_provoke.bin", None)  # handshake done
        worker._receive = clipped
        first = worker._run_case(tree / "malformed" / "a_provoke.bin", None)
        worker._receive = real                    # the restart's handshake needs the real pipe
        second = worker._run_case(tree / "malformed" / "b_plain.bin", None)
    assert started["outcome"] == suite.PARSER_REJECTED, started
    assert first["outcome"] == suite.HARNESS_ERROR
    assert "undecodable worker reply" in first["detail"] and "JSONDecodeError" in first["detail"]
    assert second["outcome"] == suite.PARSER_REJECTED, second
    assert diagnostics["restarts"] == 1
    _no_orphans(diagnostics)


def test_N_runs_every_offset_in_the_worker_and_a_hanging_offset_is_a_timeout(tmp_path):
    # Four bytes of padding, then the seven-byte marker, then two more: the payload is 13 bytes
    # and `range(1, size)` tries offsets 1..12. Offsets 1..10 hold at most a prefix of the marker
    # and refuse; 11 and 12 carry the whole marker and hang, so exactly two cases time out.
    (tmp_path / "bytes.bin").write_bytes(b"xxxx" + sp.MARKER + b"yy")
    clock = times.frozen_clock()
    diagnostics: dict = {}
    started = time.perf_counter()
    entry = suite.check_parser_robustness(sp.Slow(clock=clock), tmp_path, clock=clock,
                                          timeout_s=DEADLINE_S, startup_timeout_s=STARTUP_S,
                                          diagnostics=diagnostics)
    assert time.perf_counter() - started < BUDGET_S
    assert entry["verdict"] == suite.FAIL and "PARSER_TIMEOUT" in entry["reason"]
    assert entry["details"]["offsets_tried"] == 12
    assert entry["details"]["over_time_bound"] == ["bytes.bin[:11]: PARSER_TIMEOUT",
                                                   "bytes.bin[:12]: PARSER_TIMEOUT"]
    assert entry["details"]["outcomes"] == {suite.PARSER_REJECTED: 10, suite.PARSER_TIMEOUT: 2}
    assert diagnostics["restarts"] == 2
    _no_orphans(diagnostics)


def test_N_keeps_the_offset_cap_and_the_coverage_it_had(tmp_path):
    (tmp_path / "bytes.bin").write_bytes(bytes(range(256)) * 40)
    clock = times.frozen_clock()
    entry = suite.check_parser_robustness(sp.Refusing(clock=clock), tmp_path, clock=clock,
                                          offset_cap=16, startup_timeout_s=STARTUP_S)
    assert entry["verdict"] == suite.PASS
    assert entry["details"]["offsets_tried"] == 16
    assert entry["details"]["offset_cap_per_fixture"] == 16
    assert entry["details"]["outcomes"] == {suite.PARSER_REJECTED: 16}
    assert multiprocessing.active_children() == []


def test_canonical_details_carry_the_codes_and_bounds_and_no_volatile_reading(tmp_path):
    entry, diagnostics = _H(sp.NeverReturns, _tree(tmp_path))
    details = entry["details"]
    assert details["timeout_s"] == DEADLINE_S
    assert details["startup_timeout_s"] == STARTUP_S
    assert details["max_worker_restarts"] == suite.DEFAULT_MAX_WORKER_RESTARTS
    assert details["isolation"] == suite.ISOLATION
    volatile = [path for path, _ in _walk(entry) if path.rsplit(".", 1)[-1] in VOLATILE_KEYS]
    assert not volatile, f"machine-dependent readings reached canonical evidence: {volatile}"
    # …and the same readings ARE in the diagnostics, which is where a person debugging looks.
    assert {"pid", "exit_code", "duration_s", "killed"} <= set(diagnostics["workers"][0])
    assert diagnostics["cases"] and all("duration_s" in c for c in diagnostics["cases"])


def test_run_shares_one_worker_between_H_and_N_and_the_report_shape_is_unchanged(tmp_path):
    # `Normal` accepts the provoked payload and refuses everything else, so the valid fixture
    # carries the marker and the malformed set does not: H passes, and N's truncations of the
    # valid fixture either refuse (a partial marker) or decode (the whole one), both allowed.
    (tmp_path / "malformed").mkdir()
    (tmp_path / "malformed" / "b_plain.bin").write_bytes(b"plain")
    (tmp_path / "ok.bin").write_bytes(sp.MARKER + b"\n")
    clock = times.frozen_clock()
    diagnostics: dict = {}
    report = suite.run(sp.Normal(clock=clock), tmp_path, clock=clock,
                       startup_timeout_s=STARTUP_S, diagnostics=diagnostics)
    assert set(report) == {"adapter", "checks", "result", "maturity_eligible", "generated_with",
                           "loss_report"}
    assert report["checks"]["H"]["verdict"] == suite.PASS
    assert report["checks"]["N"]["verdict"] == suite.PASS
    assert len(diagnostics["workers"]) == 1 and diagnostics["restarts"] == 0
    _no_orphans(diagnostics)


def test_the_worker_opens_no_socket(tmp_path, monkeypatch):
    """§41 reaches the worker: the first full run after F03 failed
    `tests/test_cdm_no_network.py::test_the_whole_roster_conforms_with_no_socket_available`,
    because `Pipe(duplex=True)` is `socket.socketpair()` on Unix. The worker is built on two
    `os.pipe()`-backed simplex connections now, and this holds it there: the same capability the
    roster test removes is removed here, around the whole life of one worker."""
    def refuse(*args, **kwargs):
        raise AssertionError("the parser worker opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "socketpair", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    entry, diagnostics = _H(sp.Refusing, _tree(tmp_path))
    assert entry["verdict"] == suite.PASS
    _no_orphans(diagnostics)


def test_the_cli_writes_diagnostics_beside_the_evidence_and_not_inside_it(tmp_path, capsys):
    sink = tmp_path / "diagnostics.json"
    rc = suite.main(["conformance", "run", "--adapter", "pntmap", "--format", "json",
                     "--diagnostics", str(sink)])
    assert rc == suite.EXIT_OK
    report = json.loads(capsys.readouterr().out)
    volatile = [path for path, _ in _walk(report) if path.rsplit(".", 1)[-1] in VOLATILE_KEYS]
    assert not volatile
    written = json.loads(sink.read_text())
    assert written["pntmap"]["workers"]
