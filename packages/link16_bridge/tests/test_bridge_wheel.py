"""The installed wheel, outside the checkout (G01's bridge half, REQ191).

The distribution's files are copied to a temporary directory, built into a wheel there with
`--no-deps --no-build-isolation` (no network: the Linux run has none), installed with `--no-deps`
into a target directory beside the interpreter's installed CDM, and then the installed console
script serves the synthetic gateway and runs one ingest pass from a temporary working directory.
The checkout is never on the path of the processes that run."""
import importlib.metadata
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

import pytest

from helpers import CREDENTIAL, config_dict, report

pytestmark = pytest.mark.wheel
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _tools_missing() -> str | None:
    if importlib.util.find_spec("pip") is None:
        return "pip"
    if importlib.util.find_spec("setuptools") is None:
        return "setuptools"
    # Read from the installed metadata, never imported here: importing setuptools in the test
    # process warns on some interpreters, and the build runs in its own process anyway.
    if int(importlib.metadata.version("setuptools").split(".")[0]) < 77:
        return "setuptools>=77"
    return None


MISSING = _tools_missing()


def _quiet_environment(**extra) -> dict:
    environment = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
                   "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"}
    environment.update(extra)
    return environment


@pytest.mark.skipif(MISSING is not None,
                    reason=f"wheel: this interpreter has no {MISSING} to build and install the "
                           "wheel with (the worktree's uv-made venv carries neither pip nor "
                           "setuptools); CI and the Linux run install them")
def test_installed_bridge_wheel_runs_outside_the_checkout(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(ROOT / "synapse_link16_bridge", source / "synapse_link16_bridge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    environment = _quiet_environment()
    built = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps",
                            "--no-build-isolation", "--no-index", "-w", str(tmp_path / "dist"),
                            str(source)], env=environment, cwd=str(tmp_path),
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stderr[-2000:]
    wheels = sorted((tmp_path / "dist").glob("*.whl"))
    assert [w.name for w in wheels] == ["synapse_link16_bridge-1.0.0-py3-none-any.whl"]
    names = zipfile.ZipFile(wheels[0]).namelist()
    assert "synapse_link16_bridge/cli.py" in names
    assert "synapse_link16_bridge-1.0.0.dist-info/licenses/LICENSE" in names
    assert "synapse_link16_bridge-1.0.0.dist-info/licenses/NOTICE" in names
    assert not [n for n in names if n.startswith(("tests/", "docs/"))]
    target = tmp_path / "site"
    installed = subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps",
                                "--no-index", "--target", str(target), str(wheels[0])],
                               env=environment, cwd=str(tmp_path), capture_output=True,
                               text=True, timeout=300)
    assert installed.returncode == 0, installed.stderr[-2000:]

    run_env = _quiet_environment(PYTHONPATH=str(target),
                                 SYNAPSE_LINK16_GATEWAY_CREDENTIAL=CREDENTIAL,
                                 SYNAPSE_LINK16_TEST_CREDENTIAL=CREDENTIAL)
    probe = subprocess.run(
        [sys.executable, "-c",
         "import importlib.metadata as m, json, synapse_link16_bridge as b, synapse_cdm\n"
         "print(json.dumps({'file': b.__file__, 'version': m.version('synapse-link16-bridge'),"
         " 'requires': m.requires('synapse-link16-bridge'),"
         " 'cdm': hasattr(synapse_cdm, '__file__')}))"],
        env=run_env, cwd=str(tmp_path), capture_output=True, text=True, timeout=120)
    assert probe.returncode == 0, probe.stderr[-2000:]
    found = json.loads(probe.stdout)
    assert pathlib.Path(found["file"]).resolve().is_relative_to(target.resolve())
    assert found["version"] == "1.0.0" and found["cdm"] is True
    (requirement,) = found["requires"]
    assert requirement.startswith("synapse-cdm")
    assert set(requirement[len("synapse-cdm"):].split(",")) == {">=3.4.0", "<4"}

    script = target / "bin" / "synapse-link16-bridge"
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "one.json").write_text(json.dumps(report(1)), encoding="utf-8")
    server = subprocess.Popen([str(script), "serve-gateway", "--reports", str(reports),
                               "--port", "0", "--channel", "c1"], env=run_env,
                              cwd=str(tmp_path), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    try:
        line = server.stdout.readline().strip()
        assert line.startswith("serving on http://127.0.0.1:"), server.stderr.read()[-2000:]
        config = tmp_path / "config.json"
        config.write_text(json.dumps(config_dict(str(tmp_path / "store.sqlite"),
                                                 line.split()[-1])), encoding="utf-8")
        ran = subprocess.run([str(script), "run", str(config), "--once", "--sink-dir",
                              str(tmp_path / "sink")], env=run_env, cwd=str(tmp_path),
                             capture_output=True, text=True, timeout=120)
        assert ran.returncode == 0, ran.stderr[-2000:]
        assert json.loads(ran.stdout)["counters"]["accepted"] == 1
        delivered = sorted(json.loads(p.read_text())["event_key"]
                           for p in (tmp_path / "sink").glob("*.json"))
        assert delivered[:2] == ["00000000-0000-4000-8000-000000000001:0",
                                 "00000000-0000-4000-8000-000000000001:1"]
        status = subprocess.run([str(script), "native-status", str(config)], env=run_env,
                                cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
        assert status.returncode == 3
        assert json.loads(status.stdout)["status"] == "BLOCKED_EXTERNAL_EVIDENCE"
    finally:
        server.terminate()
        server.communicate(timeout=30)
