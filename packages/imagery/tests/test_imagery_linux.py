"""What only a Linux kernel, or the reference environment's pip and setuptools, can show: the
worker's 512 MiB address-space cap is the kernel's limit exactly, an allocation past it ends the
child with the memory status the pool reports as E_LIMIT, the normal path (inventory, translation,
a window and a preview of a 16,000,000-octet image) fits under it, and the distribution built
into a wheel and installed outside the checkout runs its command. Selected with `-m linux`;
deselected everywhere else."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

import pytest
from conftest import LOCAL
from helpers import build_nsif, image, sha, vector

from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.ingest import IngestService
from synapse_imagery.result import HostError
from synapse_imagery.worker import Window, WorkerPool

pytestmark = pytest.mark.linux

SLOW_CHILD = str(pathlib.Path(__file__).with_name("slow_child.py"))
CAP = 536_870_912


def child(mode, aux):
    return WorkerPool(_child_command=[sys.executable, "-I", "-B", SLOW_CHILD, mode, str(aux)])


def test_the_cap_is_the_kernels_limit_exactly(tmp_path):
    answer, _ = child("rlimit", tmp_path / "starts")._exchange(
        {}, pass_fds=(), stage="input", deadline=5.0
    )
    assert answer["worker"]["memory_enforcement"] == "rlimit_as"
    assert answer["worker"]["memory_limit_bytes"] == CAP
    assert answer["rlimit"] == [CAP, CAP]


def test_an_allocation_past_the_cap_ends_the_child_with_e_limit(tmp_path):
    with pytest.raises(HostError) as caught:
        child("allocate", tmp_path / "starts")._exchange(
            {}, pass_fds=(), stage="pixels", deadline=30.0
        )
    assert (caught.value.code, caught.value.stage, caught.value.path, caught.value.message) == (
        "E_LIMIT",
        "pixels",
        "/worker",
        "worker memory cap reached",
    )
    assert len((tmp_path / "starts").read_text().splitlines()) == 1, (
        "no retry after the memory status"
    )


def test_the_normal_path_fits_under_the_cap(tmp_path):
    big = build_nsif([image(rows=4000, cols=4000)])
    assert 16_000_000 < len(big) < 16_777_216
    store = LocalAssetStore(tmp_path / "store")
    with IngestService(store) as service:
        for octets in (vector("geo_dms.ntf"), big):
            result = service.ingest(
                octets, principal=LOCAL, dataset_namespace="default", synthetic=True
            )
            assert result["state"] == "committed", result["diagnostics"]
            record = store.read_record("local", result["record_id"], area="records")
            assert record["host"]["worker"]["memory_enforcement"] == "rlimit_as"
        answer = service.decode_window(
            result["record_id"], 0, Window(0, 0, 256, 256), (0,), principal=LOCAL
        )
        receipt = service.preview(result["record_id"], 0, tmp_path / "big.png", principal=LOCAL)
    assert answer.window.values()[:4] == (0, 64, 128, 255)
    assert len(answer.window.data) == 256 * 256
    assert receipt["size"] == [1024, 1024]
    stored = store.read_derivative(receipt["derivative_id"], tenant="local")
    assert stored["provenance"]["worker"]["memory_enforcement"] == "rlimit_as"
    assert os.listdir(tmp_path / "store" / "staging") == []


def test_a_preview_of_the_kit_vector_under_the_cap(tmp_path):
    store = LocalAssetStore(tmp_path / "store")
    with IngestService(store) as service:
        result = service.ingest(
            vector("geo_dms.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
        )
        receipt = service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    assert receipt["size"] == [2, 2]
    stored = store.read_derivative(receipt["derivative_id"], tenant="local")
    assert stored["provenance"]["worker"]["memory_limit_bytes"] == CAP


DISTRIBUTION = pathlib.Path(__file__).resolve().parents[1]


def quiet(**extra) -> dict:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
    }
    environment.update(extra)
    return environment


def test_the_installed_wheel_runs_outside_the_checkout(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
        shutil.copy2(DISTRIBUTION / name, source / name)
    shutil.copytree(
        DISTRIBUTION / "synapse_imagery",
        source / "synapse_imagery",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "-w",
            str(tmp_path / "dist"),
            str(source),
        ],
        env=quiet(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stderr[-2000:]
    wheels = sorted((tmp_path / "dist").glob("*.whl"))
    assert [wheel.name for wheel in wheels] == ["synapse_imagery-1.0.0-py3-none-any.whl"]
    names = zipfile.ZipFile(wheels[0]).namelist()
    for name in (
        "synapse_imagery/cli.py",
        "synapse_imagery/__main__.py",
        "synapse_imagery/contracts/ingest-result.schema.json",
        "synapse_imagery/contracts/write-nc8-recipe.schema.json",
        "synapse_imagery-1.0.0.dist-info/licenses/LICENSE",
        "synapse_imagery-1.0.0.dist-info/licenses/NOTICE",
    ):
        assert name in names, name
    assert not [name for name in names if name.startswith(("tests/", "docs/"))]
    target = tmp_path / "site"
    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--target",
            str(target),
            str(wheels[0]),
        ],
        env=quiet(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert installed.returncode == 0, installed.stderr[-2000:]
    environment = quiet(PYTHONPATH=str(target))
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.metadata as m, json, synapse_imagery as s\n"
            "print(json.dumps({'file': s.__file__, 'version': m.version('synapse-imagery'),"
            " 'requires': m.requires('synapse-imagery')}))",
        ],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert probe.returncode == 0, probe.stderr[-2000:]
    found = json.loads(probe.stdout)
    assert pathlib.Path(found["file"]).resolve().is_relative_to(target.resolve())
    assert found["version"] == "1.0.0"
    (cdm,) = [entry for entry in found["requires"] if entry.startswith("synapse-cdm")]
    assert set(cdm[len("synapse-cdm") :].split(",")) == {">=3.10.0", "<4"}
    assert [entry for entry in found["requires"] if entry != cdm] == ["jsonschema>=4.0"]
    script = str(target / "bin" / "sc-imagery")
    octets = vector("geo_dms.ntf")
    (tmp_path / "geo.ntf").write_bytes(octets)

    def run(*arguments):
        done = subprocess.run(
            [script, *arguments],
            env=environment,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return done.returncode, done.stdout, done.stderr.splitlines()

    assert run("--version") == (0, "sc-imagery 1.0.0\n", [])
    status, out, err = run("inspect", "geo.ntf", "--json", "-")
    assert (status, err, json.loads(out)["sha256"]) == (0, ["sc-imagery: inspect ok"], sha(octets))
    status, out, err = run(
        "ingest", "geo.ntf", "--store", "store", "--dataset", "default", "--synthetic", "true"
    )
    result = json.loads(out)
    assert (status, result["state"]) == (0, "committed")
    status, out, _ = run(
        "preview", result["record_id"], "--image", "0", "--store", "store", "--output", "p.png"
    )
    assert status == 0 and json.loads(out)["size"] == [2, 2]
    status, _, _ = run("replay", result["record_id"], "--store", "store", "--output", "r.ntf")
    assert status == 0 and (tmp_path / "r.ntf").read_bytes() == octets
