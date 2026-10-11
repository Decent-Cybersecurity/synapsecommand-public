"""The command line: subcommands, exit codes 0/2/3/4, audited operator records."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

import synapse_cdm
from helpers import CREDENTIAL, bidirectional, config_dict, notice, report
from synapse_link16_bridge import cli, contract

ENV = "SYNAPSE_LINK16_TEST_CREDENTIAL"


@pytest.fixture
def configured(h, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, CREDENTIAL)
    h.bridge.close()
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_dict(h.store_path, h.server.base_url, **bidirectional())),
                    encoding="utf-8")
    return h, str(path)


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_check_config_accepts_and_refuses(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(config_dict(str(tmp_path / "s.sqlite"))), encoding="utf-8")
    code, out, _ = run(capsys, "check-config", str(good))
    assert code == 0 and json.loads(out) == {"config": "VALID", "config_revision": "rev-1",
                                             "mode": "ingest"}
    literal = "literal-" + "w" * 12
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(config_dict(str(tmp_path / "s.sqlite"), credential_ref=literal)),
                   encoding="utf-8")
    code, _, err = run(capsys, "check-config", str(bad))
    assert code == 2
    assert err.strip() == "CONFIG_INVALID: credential_ref — env:NAME, a reference and never a value"
    assert literal not in err


def test_usage_errors_exit_2(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["resync-identities", "x.json", "--decision", "forget", "--evidence", "e"])
    assert caught.value.code == 2


@pytest.mark.parametrize("which, literal", [("api", contract.API_SCHEMA),
                                            ("notice", contract.NOTICE_SCHEMA)])
def test_schema_prints_the_contract(capsys, which, literal):
    code, out, _ = run(capsys, "schema", which)
    assert code == 0 and json.loads(out) == literal


def test_run_once_health_status_and_operator_records(configured, tmp_path, capsys):
    h, path = configured
    h.publish(report(1))
    h.publish(report(2, track_number="T-2", message_family="J7.0"))
    sink = tmp_path / "sink"
    code, out, _ = run(capsys, "run", path, "--once", "--sink-dir", str(sink))
    assert code == 0
    printed = json.loads(out)
    assert (printed["status"], printed["channel_state"], printed["counters"]["accepted"],
            printed["counters"]["unsupported"]) == ("READY", "NORMAL", 1, 1)
    files = sorted(json.loads(p.read_text())["event_key"] for p in sink.glob("*.json"))
    assert files == ["00000000-0000-4000-8000-000000000001:0",
                     "00000000-0000-4000-8000-000000000001:1",
                     "00000000-0000-4000-8000-000000000001:freshness:EXPIRED:EXPIRED"]
    code, out, _ = run(capsys, "health", path)
    assert code == 0 and json.loads(out)["ready"] is True
    code, _, err = run(capsys, "recover", path, "--evidence", "nothing to recover")
    assert code == 4 and err.startswith("REFUSED: recover applies")
    code, _, _ = run(capsys, "status", path, "00000000-0000-4000-8000-0000000000ff")
    assert code == 4
    code, _, err = run(capsys, "resync", path, "--evidence", "e")
    assert code == 4 and "accept-earliest" in err
    key = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
    dest = json.dumps({"tenant": "demo", "realm": "dest-realm", "synthetic": True,
                       "origin_scope": "dest-scope", "track_number": "D-1", "incarnation": "0"})
    code, _, _ = run(capsys, "allocate", path, "--peer", "peer-1", "--realm", "dest-realm",
                     "--identity", key, "--dest-tuple", dest, "--evidence", "e" * 2000)
    assert code == 0
    bridge = h.new_bridge(holder="holder-check", config=h.config(**bidirectional()))
    details = bridge.store.query("SELECT kind, length(detail) FROM audit WHERE kind = ?",
                                 ("allocation",))
    assert details == [("allocation", 1024)]
    bridge.close()


def test_run_exits_3_when_the_bridge_blocks_mid_run(configured, tmp_path, capsys,
                                                    monkeypatch):
    """R4-F9 (fix round 1, 2026-10-11): the second pass finds the lease taken by another
    instance; `run` stops BLOCKED (`LEASE_LOST`) and exits 3, printing the status."""
    from synapse_link16_bridge.lease import Lease, LeaseHeld, LeaseLost
    h, path = configured
    h.publish(report(1))
    passes = {"renewed": 0}
    real_renew = Lease.renew

    def renew(self):
        passes["renewed"] += 1
        if passes["renewed"] >= 2:
            raise LeaseLost("taken over")
        return real_renew(self)

    def acquire_after_start(self):
        raise LeaseHeld("held by another instance")

    real_start = cli.Bridge.start

    def start(self):
        status = real_start(self)
        monkeypatch.setattr(Lease, "acquire", acquire_after_start)
        return status

    monkeypatch.setattr(Lease, "renew", renew)
    monkeypatch.setattr(cli.Bridge, "start", start)
    code, out, _ = run(capsys, "run", path, "--sink-dir", str(tmp_path / "sink"))
    assert code == 3
    printed = json.loads(out)
    assert (printed["status"], printed["counters"]["accepted"]) == ("BLOCKED", 1)


def test_evidence_is_the_audited_reader_of_raw_batches(configured, tmp_path, capsys):
    h, path = configured
    h.publish(report(1, message_family="J7.0"))
    h.bridge = h.new_bridge(holder="holder-run", config=h.config(**bidirectional()))
    sha = h.run()["batch_sha256"]
    h.bridge.close()
    out_file = tmp_path / "raw.json"
    code, out, _ = run(capsys, "evidence", path, "--raw-ref", sha, "--out", str(out_file),
                       "--evidence", "incident 12 review")
    assert code == 0 and json.loads(out) == {"raw_ref": sha, "kept": True,
                                             "bytes": out_file.stat().st_size}
    assert json.loads(out_file.read_bytes())["records"][0]["body"]["message_family"] == "J7.0"
    code, _, _ = run(capsys, "evidence", path, "--raw-ref", "0" * 64, "--out",
                     str(tmp_path / "none"), "--evidence", "x")
    assert code == 4


def test_serve_gateway_and_run_once_as_processes(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "one.json").write_text(json.dumps(report(1)), encoding="utf-8")
    root = pathlib.Path(__file__).resolve().parent.parent
    environment = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": os.pathsep.join(
                       [str(root), str(pathlib.Path(synapse_cdm.__file__).parent.parent)]),
                   "SYNAPSE_LINK16_GATEWAY_CREDENTIAL": CREDENTIAL, ENV: CREDENTIAL}
    server = subprocess.Popen([sys.executable, "-m", "synapse_link16_bridge", "serve-gateway",
                               "--reports", str(reports), "--port", "0", "--channel", "c1"],
                              env=environment, cwd=str(tmp_path), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    try:
        line = server.stdout.readline().strip()
        assert line.startswith("serving on http://127.0.0.1:")
        config = tmp_path / "config.json"
        config.write_text(json.dumps(config_dict(str(tmp_path / "s.sqlite"),
                                                 line.split()[-1])), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "synapse_link16_bridge", "run",
                                    str(config), "--once", "--sink-dir", str(tmp_path / "sink")],
                                   env=environment, cwd=str(tmp_path), capture_output=True,
                                   text=True, timeout=60)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["counters"]["accepted"] == 1
    finally:
        server.terminate()
        server.communicate(timeout=30)


def test_run_exits_3_when_the_lease_is_lost_before_the_ack_is_recorded(configured, tmp_path,
                                                                       capsys, monkeypatch):
    """RUNTIME-3 (A2F, 2026-10-11): the lease expires while the acknowledgement is in flight (here
    another writer expires it in the store); `run --once` prints the BLOCKED status and exits 3
    instead of raising."""
    import sqlite3
    from synapse_link16_bridge.gateway.client import GatewayClient
    h, path = configured
    h.publish(report(1))
    real_ack = GatewayClient.ack

    def ack_then_expire(self, consumer, cursor):
        real_ack(self, consumer, cursor)
        other = sqlite3.connect(h.store_path, isolation_level=None)
        try:
            other.execute("UPDATE lease SET expires_at = 0")
        finally:
            other.close()

    monkeypatch.setattr(GatewayClient, "ack", ack_then_expire)
    code, out, _ = run(capsys, "run", path, "--once", "--sink-dir", str(tmp_path / "sink"))
    assert code == 3
    printed = json.loads(out)
    assert (printed["status"], printed["counters"]["accepted"]) == ("BLOCKED", 1)


@pytest.mark.parametrize("credential", ["SECRETMARKER7\n", "SECRETMARKER7\r\nX-Inject: 1"],
                         ids=["LF", "CRLF-header"])
def test_a_credential_with_a_line_break_exits_2_and_is_never_printed(configured, tmp_path,
                                                                    capsys, monkeypatch,
                                                                    credential):
    """HYGIENE-2 (A2F, 2026-10-11): the client refuses the credential when it is built, with the
    configuration's typed exit code and a message that names the reference only."""
    h, path = configured
    monkeypatch.setenv(ENV, credential)
    code, out, err = run(capsys, "run", path, "--once", "--sink-dir", str(tmp_path / "sink"))
    assert code == 2 and out == ""
    assert err == ("CONFIG_INVALID: credential_ref — the credential it names must be visible "
                   "ASCII, without space or control characters\n")
    assert "SECRETMARKER7" not in out + err


def test_health_names_a_gap_held_under_another_state(configured, tmp_path, capsys):
    """A2F-F1 (fix round 1, 2026-10-11): `health` reads a gap no operator has recovered whatever
    state holds the channel meanwhile: after a GAP and a RESET_SCOPE it names both. Before, it
    named only RESYNC_REQUIRED."""
    h, path = configured
    h.publish_notice(notice(1, "GAP", track_number=None, incarnation=None))
    h.publish_notice(notice(2, "RESET_SCOPE", at_ms=1000, track_number=None, incarnation=None))
    code, _, _ = run(capsys, "run", path, "--once", "--sink-dir", str(tmp_path / "sink"))
    assert code == 0
    code, out, _ = run(capsys, "health", path)
    printed = json.loads(out)
    assert (code, printed["ready"], printed["blocked_reasons"], printed["channel_state"]) == (
        3, False, ["CHANNEL_INCOMPLETE", "RESYNC_REQUIRED"], "RESYNC_REQUIRED")
