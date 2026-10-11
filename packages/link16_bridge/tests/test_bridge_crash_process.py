"""Crash recovery across a real process death (R01, R02): `os._exit(137)` at the crash point,
the WAL file left on disk, then a new instance on the same store.

The child is `sys.executable` with `PYTHONPATH` naming this distribution and the directory the
`synapse_cdm` under test was imported from, so that what the child imports is decided here and
not by an editable finder of the interpreter's environment."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

import synapse_cdm
from helpers import CREDENTIAL, config_dict, report, uid

pytestmark = pytest.mark.process
HERE = pathlib.Path(__file__).resolve().parent
INGEST = "SELECT record_key, disposition FROM ingest ORDER BY rowid"


def run_child(h, point):
    config_path = h.tmp_path / "config.json"
    config_path.write_text(json.dumps(config_dict(h.store_path, h.server.base_url)),
                           encoding="utf-8")
    h.bridge.close()
    paths = [str(HERE), str(HERE.parent),
             str(pathlib.Path(synapse_cdm.__file__).resolve().parent.parent)]
    environment = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": os.pathsep.join(paths)}
    completed = subprocess.run(
        [sys.executable, str(HERE / "crash_driver.py"), str(config_path), CREDENTIAL, point,
         "holder-process"], env=environment, cwd=str(h.tmp_path), capture_output=True,
        timeout=120)
    return completed.returncode


def test_process_exit_after_commit_before_ack(h):
    h.publish(report(1))
    h.publish(report(2, track_number="T-2"))
    assert run_child(h, "ingest.after_commit_before_ack") == 137
    assert h.provider.health_document("c1")["queue_depth"] == 2
    restarted = h.new_bridge(holder="holder-process")
    assert restarted.store.query(INGEST) == [(uid(1), "ACCEPTED"), (uid(2), "ACCEPTED")]
    result = h.run(restarted)
    assert [d[1:] for d in result["dispositions"]] == [("DUPLICATE", None), ("DUPLICATE", None)]
    assert h.provider.health_document("c1")["queue_depth"] == 0
    assert sorted(k for k, v in h.sink.events.items() if v[0] == "cdm") == [
        f"{uid(1)}:0", f"{uid(1)}:1", f"{uid(2)}:0", f"{uid(2)}:1"]


def test_process_exit_before_commit_leaves_nothing(h):
    h.publish(report(1))
    assert run_child(h, "ingest.before_commit") == 137
    restarted = h.new_bridge(holder="holder-process")
    assert restarted.store.query(INGEST) == []
    assert h.provider.health_document("c1")["queue_depth"] == 1
    assert [d[1:] for d in h.run(restarted)["dispositions"]] == [("ACCEPTED", None)]
