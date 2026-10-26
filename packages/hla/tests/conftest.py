"""Session wiring for the synapse-hla tests: the offline socket guard and the trace export.

THE GUARD (D-10)
----------------
Every test outside the `rti`, `perf` and `reference` groups runs with the guarded socket
functions replaced by a refusal, so a test of the offline group cannot open a connection or
resolve a name even by accident; `test_hla_infrastructure.py` proves it, in this process and in a
child. The refusal and the list come from `tests/sockguard/sitecustomize.py`, the same file a
child interpreter runs at start-up, so the two cannot disagree.

THE TRACE EXPORT
----------------
`pytest_itemcollected` records, for every collected test, the case ids and paragraph keys its
`hla_case` marks carry. When `SYNAPSE_HLA_TRACE_EXPORT` names a file, the record is written there
at the end of collection; `hla_support.collected_bindings()` runs a collection in a child with
that variable set and reads it back. Recording happens at collection, before `-m` deselects
anything, so a case bound by a test of another group still counts as bound.

THE RESULTS EXPORT
------------------
When `SYNAPSE_HLA_RESULTS_EXPORT` names a file, every test that ran is written there at the end
of the session: its node id, its outcome (passed, failed, error or skipped, with the skip's
reason), its duration and the properties it recorded (`record_property`). The release evidence
tool (`tests/release_evidence.py`) reads these files; nothing else does.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket

import pytest

# hla_support asserts on behalf of the tests (timestamps, FOM pins); give its asserts the same
# detailed failure messages as a test module's. Must run before anything imports it.
pytest.register_assert_rewrite("hla_support")

from sockguard import sitecustomize as sockguard

#: The groups that may use the network or external tools; every other test is offline.
NON_OFFLINE_MARKERS = ("rti", "perf", "reference")

_BINDINGS = pytest.StashKey[dict]()
#: The results export, filled by the report hook (a test report does not carry its config).
_RESULTS: dict[str, dict] = {}


def is_offline(marker_names) -> bool:
    """True when a test carrying these marker names belongs to the offline group."""
    return not any(name in NON_OFFLINE_MARKERS for name in marker_names)


@pytest.fixture(autouse=True)
def _offline_socket_guard(request, monkeypatch):
    if is_offline(m.name for m in request.node.iter_markers()):
        for name in sockguard.GUARDED:
            monkeypatch.setattr(socket, name, sockguard.refusal(name))
    yield


def pytest_configure(config):
    config.stash[_BINDINGS] = {}


def pytest_itemcollected(item):
    ids: list[str] = []
    paragraphs: list[str] = []
    for mark in item.iter_markers(name="hla_case"):
        ids.extend(mark.args)
        paragraphs.extend(mark.kwargs.get("paragraphs", ()))
    if ids or paragraphs:
        item.config.stash[_BINDINGS][item.nodeid] = {
            "ids": sorted(set(ids)),
            "paragraphs": sorted(set(paragraphs)),
        }


def pytest_collection_finish(session):
    target = os.environ.get("SYNAPSE_HLA_TRACE_EXPORT")
    if target:
        record = json.dumps(session.config.stash[_BINDINGS], sort_keys=True, indent=1)
        pathlib.Path(target).write_text(record + "\n", encoding="utf-8")


def pytest_runtest_logreport(report):
    """One entry per test: the call's outcome, or the setup's or teardown's when that is what
    failed or skipped; durations of the three phases summed."""
    entry = _RESULTS.setdefault(report.nodeid, {"outcome": None, "duration_s": 0.0,
                                               "reason": None, "properties": {}})
    entry["duration_s"] += report.duration
    for name, value in report.user_properties:
        entry["properties"][name] = value if isinstance(value, str) else repr(value)
    if report.when == "call" or report.outcome != "passed":
        if entry["outcome"] in ("failed", "error"):
            return
        if report.outcome == "failed":
            entry["outcome"] = "failed" if report.when == "call" else "error"
        elif report.outcome == "skipped":
            entry["outcome"] = "skipped"
            longrepr = report.longrepr
            entry["reason"] = longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)
        elif report.when == "call":
            entry["outcome"] = "passed"


def pytest_sessionfinish(session):
    target = os.environ.get("SYNAPSE_HLA_RESULTS_EXPORT")
    if target:
        for entry in _RESULTS.values():
            entry["duration_s"] = round(entry["duration_s"], 3)
        record = json.dumps(_RESULTS, sort_keys=True, indent=1)
        pathlib.Path(target).write_text(record + "\n", encoding="utf-8")
