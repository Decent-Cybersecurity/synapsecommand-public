"""The release form of synapse-hla: the wheel, the native install, the locks, the SBOM, the licence
texts, and the version and profile strings everywhere they appear (round R9).

WHAT RUNS WHERE
---------------
Offline group: what the tree itself shows. The wheel's contents follow from the package data
rules and the package directory (a test derives them from the tree and holds the counts to
literals); the lock files are hashed, exact and the tested set; the SBOM is, byte for byte, what
`tests/release_sbom.py` makes of the locks; the OpenRTI licence texts are the pinned archive's
own bytes; the version and profile strings agree in every place that states them.

`rti` group: the installed form. A wheel is built from a copy of this directory with `uv build`
(offline, the build backend held to `locks/build.lock` by hash) and its member list compared with
the derived one; it is installed into a fresh directory, the native build is installed beside the
package with `cmake --install --prefix <package directory>` (docs/installation.md), and the
command line, run from outside any checkout with no SYNAPSE_HLA_WORKER, SYNAPSE_HLA_PUBLISHER or
SYNAPSE_HLA_RTINODE set, finds the worker, the publisher and rtinode at their fixed places
(OPV-04, CR-R5-02, CR-L16) and passes `self-test` and `demo`.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile

import pytest

import release_sbom
import synapse_hla
from hla_support import (
    PACKAGE_ROOT, blocked, case, fixed_tool, fom_modules, native_executable, packaged_pins,
    process_gone, strict_json,
)
from synapse_hla import _demo, cli, host

PYPROJECT = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
SOURCE = PACKAGE_ROOT / "src" / "synapse_hla"
LOCKS = PACKAGE_ROOT / "locks"

#: The package directory's files by kind, counted by hand from the layout of COMMON section 4 and
#: the rounds' reports: 24 modules (the 9 of the layout, cli, host, replay, reducer, projector,
#: geodesy and the 11 private helpers named in the build reports), the 13 schemas of the bundle,
#: the 8 product schemas of CR-L03 and CR-L08, the 8 fixtures and their provenance record, and
#: pins.json.
PACKAGE_COUNTS = {"modules": 24, "schemas": 13, "local_schemas": 8, "fixtures": 9, "pins": 1}
#: What setuptools adds in `.dist-info`: the core metadata, the record, the wheel file, the
#: console script's entry points, setuptools' top-level list, and the licence files of
#: pyproject's license-files under licenses/.
DIST_INFO = {"METADATA", "RECORD", "WHEEL", "entry_points.txt", "top_level.txt",
             "licenses/LICENSE", "licenses/NOTICE", "licenses/licences/openrti/lgpl-2.1",
             "licenses/licences/openrti/lgpl-3"}


def package_files() -> list[str]:
    """Every file of the package directory, relative to src/, bytecode caches aside."""
    return sorted(str(p.relative_to(SOURCE.parent)) for p in SOURCE.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts)


def kind_of(name: str) -> str:
    parts = name.split("/")
    if name.endswith(".py") and len(parts) == 2:
        return "modules"
    if name == "synapse_hla/pins.json":
        return "pins"
    if len(parts) == 3 and parts[1] in ("schemas", "local_schemas", "fixtures"):
        return parts[1]
    return "other"


def expected_wheel_members() -> set[str]:
    return set(package_files()) | {f"synapse_hla-1.0.0.dist-info/{n}" for n in DIST_INFO}


# ============================================================================ the wheel (offline)

@case("G-R05", "G-R03", paragraphs=("SPEC:28", "SPEC:20"))
def test_the_package_directory_is_what_the_wheel_carries_and_nothing_else():
    """R05, R03 and OPV-03: the wheel is the package directory, which holds the modules, the 13
    contract schemas, the product's schemas, the 8 fixtures with their provenance record and
    pins.json, by the counts derived by hand above, and nothing else: no FOM module, no archive,
    no `.txt`, no executable or library (the native part is built from the checkout and
    installed beside the package, never inside the wheel). The package data rules of
    pyproject.toml match every non-module file, and the wheel is pure (no extension module)."""
    files = package_files()
    counts = {}
    for name in files:
        counts[kind_of(name)] = counts.get(kind_of(name), 0) + 1
    assert counts == PACKAGE_COUNTS
    for name in files:
        assert not name.endswith((".xml", ".tar.gz", ".tgz", ".zip", ".txt", ".so", ".dylib",
                                  ".pyd", ".c", ".cpp")), name
        assert "/bin/" not in name and "/lib/" not in name, name
    globs = PYPROJECT["tool"]["setuptools"]["package-data"]["synapse_hla"]
    for name in files:
        if name.endswith(".py"):
            continue
        inner = name.split("/", 1)[1]
        assert any(pathlib.PurePosixPath(inner).match(g) for g in globs), name
    assert PYPROJECT["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert not (PACKAGE_ROOT / "setup.py").exists() and not (PACKAGE_ROOT / "setup.cfg").exists()


# ============================================================ locks, SBOM, licence texts (offline)

def locked(name: str) -> list[dict]:
    return release_sbom.read_lock(LOCKS / name)


@case("G-R43", "G-R05", paragraphs=("SPEC:241", "SPEC:8"))
def test_the_locks_hold_the_tested_set_with_exact_versions_and_hashes():
    """R43: Python wheels and build tools locked with exact versions and hashes. runtime.lock is
    the dependency closure of synapse-cdm>=3.8.0,<4, with synapse-cdm at 3.9.0, the newest
    release on the index inside that range when the locks were made (CR-L22); test.lock adds
    pytest 9.1.1 and its own; both hold exactly the versions of locks/tested-set.in (the set the
    tests ran with) and each pinned name carries at least one SHA-256; build.lock locks the build
    backend uv build used, setuptools 84.2.1, which satisfies the declared setuptools>=77. The
    interpreter running this test has exactly the locked versions installed, with one exception
    (CR-L22): synapse-cdm, the sibling distribution of this repository, may be a later release
    than the locked one, as a checkout's own packages/cdm is at a release commit, but it must
    satisfy the declared range and be at or above the locked version."""
    tested = {}
    for line in (LOCKS / "tested-set.in").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==")
            tested[release_sbom._normal(name)] = version
    runtime = {release_sbom._normal(e["name"]): e for e in locked("runtime.lock")}
    test = {release_sbom._normal(e["name"]): e for e in locked("test.lock")}
    assert set(runtime) == {"annotated-types", "attrs", "jsonschema", "jsonschema-specifications",
                            "pydantic", "pydantic-core", "referencing", "rpds-py", "synapse-cdm",
                            "typing-extensions", "typing-inspection"}
    assert set(test) == set(runtime) | {"colorama", "iniconfig", "packaging", "pluggy",
                                        "pygments", "pytest"}
    assert runtime["synapse-cdm"]["version"] == "3.9.0"
    assert test["pytest"]["version"] == "9.1.1"
    # colorama is pytest's only on Windows, which no run of this release used.
    assert test["colorama"]["marker"] == "sys_platform == 'win32'"
    for name, entry in test.items():
        if name != "colorama":
            assert entry["version"] == tested[name], name
            assert entry["marker"] is None, name
        if name in runtime:
            assert runtime[name] == entry, name
        installed = importlib.metadata.version(name) if name != "colorama" else None
        if name == "synapse-cdm":
            triple = tuple(int(part) for part in installed.split("."))
            assert (3, 8, 0) <= triple < (4, 0, 0), installed
            assert triple >= tuple(int(part) for part in entry["version"].split(".")), installed
        else:
            assert installed in (None, entry["version"]), name
    build = locked("build.lock")
    assert [(e["name"], e["version"]) for e in build] == [("setuptools", "84.2.1")]
    assert PYPROJECT["build-system"]["requires"] == ["setuptools>=77"]
    for name in ("runtime.lock", "test.lock", "build.lock"):
        head = (LOCKS / name).read_text(encoding="utf-8").splitlines()[1]
        assert "--generate-hashes" in head and "--index-url https://pypi.org/simple" in head


@case("G-R43", "G-R05", paragraphs=("SPEC:241",))
def test_the_sbom_is_what_the_locks_give_and_enumerates_what_r43_names():
    """R43 and NAT-14: locks/sbom.cdx.json is, byte for byte, the output of
    tests/release_sbom.py over the locks (so nothing in it was typed), and it enumerates the
    OpenRTI source archive by the SHA-256 of pins.json with the licence offered and the one
    elected, the OpenRTI libraries and rtinode, the two native programs, every locked runtime
    distribution with its hashes and licence, the compiler and CMake of each toolchain that built
    the native part (outside the runtime scope), and the system expat and zlib each build linked,
    with their licences; it claims no digest for a build of synapse-hla itself."""
    assert (LOCKS / "sbom.cdx.json").read_bytes() == release_sbom.sbom_bytes()
    sbom = json.loads((LOCKS / "sbom.cdx.json").read_bytes())
    assert (sbom["bomFormat"], sbom["specVersion"]) == ("CycloneDX", "1.6")
    by_ref = {c["bom-ref"]: c for c in sbom["components"]}
    archive = by_ref["openrti:source-archive"]
    assert archive["hashes"] == [{"alg": "SHA-256",
                                  "content": packaged_pins()["openrti-814a210.tar.gz"]["sha256"]}]
    assert archive["licenses"] == [{"expression": "LGPL-2.1-or-later"}]
    for ref in ("openrti:libOpenRTI", "openrti:librti1516e", "openrti:libfedtime1516e",
                "openrti:rtinode", "native:sc-hla-federate", "native:sc-hla-publisher"):
        assert ref in by_ref and "hashes" not in by_ref[ref], ref
    for entry in locked("runtime.lock"):
        component = by_ref[f"pypi:{release_sbom._normal(entry['name'])}"]
        assert component["version"] == entry["version"]
        assert [h["content"] for h in component["hashes"]] == entry["sha256"]
        assert component["licenses"][0]["expression"]
    for label in ("DEV-macOS-arm64", "DEV-linux-aarch64"):
        for role in ("compiler", "cmake"):
            assert by_ref[f"build:{label}:{role}"]["scope"] == "excluded"
        assert by_ref[f"system:{label}:expat"]["licenses"] == [{"expression": "MIT"}]
        assert by_ref[f"system:{label}:zlib"]["licenses"] == [{"expression": "Zlib"}]
    assert "hashes" not in sbom["metadata"]["component"]
    assert not any(k in sbom for k in ("serialNumber", "timestamp"))


#: (installed sibling, locked sibling, admitted): CR-L22's rule for synapse-cdm against the
#: declared range >=3.8.0,<4, written by hand.
SIBLING_ROWS = (
    ("3.9.0", "3.9.0", True),     # the locked release itself
    ("3.9.1", "3.9.0", True),     # a later release inside the range (a release commit)
    ("3.10.0", "3.9.0", True),    # compared as numbers, not as text
    ("3.8.0", "3.9.0", False),    # inside the range but below the locked release
    ("4.0.0", "3.9.0", False),    # the next major is outside the range
    ("3.7.9", "3.7.9", False),    # below the floor, even when it is the locked one
)


@case("G-R43", "G-R05", paragraphs=("SPEC:241",))
@pytest.mark.parametrize("installed, locked, admitted", SIBLING_ROWS)
def test_the_sbom_tool_admits_a_later_synapse_cdm_only_inside_the_declared_range(
        installed, locked, admitted, monkeypatch):
    """CR-L22 in the SBOM tool: the installed synapse-cdm is admitted when it is the locked
    version, or a later release inside the declared range (read from pyproject.toml); then the
    licence listed is the installed sibling's, which must be this repository's own. Anything
    else is refused as for every other locked distribution, and a third-party distribution is
    still held to its locked version exactly."""
    monkeypatch.setattr(release_sbom.importlib.metadata, "metadata",
                        lambda name: {"Version": installed, "License-Expression": "Apache-2.0"})
    assert release_sbom.sibling_range() == ((3, 8, 0), (4, 0, 0))
    assert release_sbom.sibling_admitted(installed, locked) is admitted
    if admitted:
        assert release_sbom.installed_licence("synapse-cdm", locked) == "Apache-2.0"
    else:
        with pytest.raises(SystemExit, match=f"installed {installed}, locked {locked}"):
            release_sbom.installed_licence("synapse-cdm", locked)
    with pytest.raises(SystemExit, match=f"pydantic: installed {installed}, locked 2.14.1"):
        release_sbom.installed_licence("pydantic", "2.14.1")


@case("G-R43", "G-R05", paragraphs=("SPEC:241",))
def test_the_sbom_tool_refuses_a_later_sibling_that_declares_another_licence(monkeypatch):
    """CR-L22: a later synapse-cdm than the locked one is listed with the licence it declares
    only when that is this repository's licence (Apache-2.0, pyproject.toml), since it then
    speaks for the locked release too; a pre-release number is refused before any comparison."""
    monkeypatch.setattr(release_sbom.importlib.metadata, "metadata",
                        lambda name: {"Version": "3.9.1", "License-Expression": "MIT"})
    with pytest.raises(SystemExit, match="declares 'MIT', not this repository's 'Apache-2.0'"):
        release_sbom.installed_licence("synapse-cdm", "3.9.0")
    with pytest.raises(SystemExit, match="'3.9.1rc1' is not a release number X.Y.Z"):
        release_sbom.sibling_admitted("3.9.1rc1", "3.9.0")


def openrti_member(name: str) -> bytes:
    """One file of the pinned OpenRTI archive (beside the FOM modules, held to its pin first)."""
    path = fom_modules()[0].parent / "openrti-814a210.tar.gz"
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == packaged_pins()["openrti-814a210.tar.gz"]["sha256"]
    with tarfile.open(path, "r:gz") as archive:
        member = archive.getmember(f"OpenRTI-814a210978b7faafd65affbe70a2e25679921b23/{name}")
        assert member.isfile()
        return archive.extractfile(member).read()


#: The OpenRTI texts this release carries (NAT-14), as licences/README.md lists them.
OPENRTI_TEXTS = {"LICENSE": "LICENSE", "lgpl-2.1": "lgpl-2.1.txt", "lgpl-3": "lgpl-3.txt",
                 "mpl-2.0": "mpl-2.0.txt"}


@case("G-R43", "G-R05", paragraphs=("SPEC:241",))
def test_the_openrti_licence_texts_are_the_archives_own_bytes_and_the_election_is_stated():
    """NAT-14 and R43 ("retain OpenRTI's included licences"): licences/openrti holds the
    archive's LICENSE, lgpl-2.1.txt, lgpl-3.txt and mpl-2.0.txt byte for byte (named without the
    `.txt` the repository ignores), each listed in licences/README.md with its SHA-256; that file
    states the elected licence (LGPL-2.1-or-later, dynamically linked, the pinned archive shipped
    alongside), the IEEE and SISO attributions, and that COPYING-expat is not carried because the
    system expat was linked; the two LGPL texts are licence files of the distribution."""
    readme = (PACKAGE_ROOT / "licences" / "README.md").read_text(encoding="utf-8")
    assert sorted(p.name for p in (PACKAGE_ROOT / "licences" / "openrti").iterdir()) == sorted(
        OPENRTI_TEXTS)
    for here, there in OPENRTI_TEXTS.items():
        data = (PACKAGE_ROOT / "licences" / "openrti" / here).read_bytes()
        assert data == openrti_member(there), here
        assert f"| `openrti/{here}` | `{there}`" in readme
        assert hashlib.sha256(data).hexdigest() in readme
    flat = " ".join(readme.split())
    for statement in (
            "Elected licence: this release uses OpenRTI under the GNU Lesser General Public "
            "License, version 2.1 or (at your option) any later version (LGPL-2.1-or-later).",
            "OpenRTI is linked dynamically",
            "the pinned source archive is shipped alongside",
            '"Reprinted with permission from IEEE 1516.1(TM)-2010"',
            '"Reprinted with permission from SISO Inc."',
            "so `COPYING-expat` is not carried"):
        assert statement in flat, statement
    assert PYPROJECT["project"]["license-files"][2:] == ["licences/openrti/lgpl-2.1",
                                                         "licences/openrti/lgpl-3"]


# ===================================================== one version and one profile everywhere

@case("G-R03", "G-R49")
def test_one_version_and_one_profile_wherever_the_release_states_them():
    """The distribution's version 1.0.0 and profile SC-HLA-RPR2-OBS-1 are the same in
    pyproject.toml, `synapse_hla.__version__` and `PROFILE`, the command line's --version line,
    the version lines of the worker and the publisher (in their C++ sources and in the host's
    and the demo's expectations; the installed-form test below runs both programs), the capture
    header's adapter version and profile, the projector's, the demo manifest's (its writer and
    its schema), the README's profile declaration and the evidence report."""
    assert PYPROJECT["project"]["version"] == synapse_hla.__version__ == "1.0.0"
    assert synapse_hla.PROFILE == "SC-HLA-RPR2-OBS-1"
    assert json.loads(cli.VERSION_LINE) == {"name": "synapse-hla", "version": "1.0.0",
                                            "profile": "SC-HLA-RPR2-OBS-1"}
    assert json.loads(host.VERSION_LINE) == {"name": "sc-hla-federate", "version": "1.0.0",
                                             "profile": "SC-HLA-RPR2-OBS-1"}
    assert json.loads(_demo.PUBLISHER_VERSION_LINE) == {
        "name": "sc-hla-publisher", "version": "1.0.0", "profile": "SC-HLA-RPR2-OBS-1"}
    for source, name in (("src/native/worker/process.cpp", "sc-hla-federate"),
                         ("tools/publisher/publisher.cpp", "sc-hla-publisher")):
        text = (PACKAGE_ROOT / source).read_text(encoding="utf-8")
        line = ('"{\\"name\\":\\"' + name + '\\",\\"profile\\":\\"SC-HLA-RPR2-OBS-1\\",'
                '\\"version\\":\\"1.0.0\\"}\\n"')
        assert line in text, source
    from synapse_hla import capture, projector
    assert (capture.ADAPTER_VERSION, capture.PROFILE) == ("1.0.0", "SC-HLA-RPR2-OBS-1")
    assert (projector.ADAPTER_VERSION, projector.PROFILE) == ("1.0.0", "SC-HLA-RPR2-OBS-1")
    # The demo manifest writes capture's two constants, and its schema holds them.
    from hla_support import local_schema
    demo = local_schema("demo.schema.json")["properties"]
    assert (demo["adapter_version"], demo["profile"]) == ({"const": "1.0.0"},
                                                          {"const": "SC-HLA-RPR2-OBS-1"})
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Profile `SC-HLA-RPR2-OBS-1`, synapse-hla 1.0.0" in readme
    report = strict_json((PACKAGE_ROOT / "docs/evidence/evidence-report.json").read_bytes())
    assert (report["release"]["version"], report["release"]["profile"]) == (
        "1.0.0", "SC-HLA-RPR2-OBS-1")


# ============================================================================ the installed form

def _copy_package(target: pathlib.Path) -> None:
    """This directory without bytecode caches, as a fresh checkout would hold it."""
    shutil.copytree(PACKAGE_ROOT, target, ignore=shutil.ignore_patterns("__pycache__"))


def _run(argv: list, *, env: dict, cwd: pathlib.Path, timeout: float = 600):
    return subprocess.run([str(a) for a in argv], env=env, cwd=cwd, capture_output=True,
                          timeout=timeout)


#: What uv (0.12) prints when an offline build finds its pinned backend nowhere in its cache.
#: The backend is then a resource this machine lacks (D-07: BLOCKED), not a fault of the tree; the
#: README's "Running the tests" names the one online step that puts it there.
UV_BACKEND_NOT_CACHED = (b"was not found in the cache", b"the network was disabled")


@pytest.mark.rti
@case("G-R49", "G-R05", "G-R43", paragraphs=("SPEC:28", "SPEC:241"))
def test_the_wheel_and_the_native_install_form_the_installed_product(tmp_path):
    """R49 and R43, with the mechanism of docs/installation.md: a wheel built from a copy of this
    directory (uv build, offline, its build backend held to locks/build.lock by hash) is pure
    (py3-none-any, Root-Is-Purelib) and holds exactly the package directory and its metadata, the
    vendored files with their pinned bytes and no FOM module, archive or `.txt` outside its
    `.dist-info`; its metadata declares the CDM floor and carries the README with the profile
    declaration. Installed into a new directory, with the native build installed beside the
    package by `cmake --install --prefix <package directory>`, the command line run from outside
    any checkout with no executable variable set finds the worker, the publisher and rtinode at
    their fixed places (OPV-04, CR-R5-02, CR-L16): the installed worker and publisher answer
    their version lines, and the command line answers --version and passes self-test and demo,
    whose manifest names version 1.0.0 and the profile."""
    uv, cmake = fixed_tool("uv"), fixed_tool("cmake")
    worker = native_executable("SYNAPSE_HLA_WORKER")
    build_dir = worker.parent.parent
    copy = tmp_path / "hla-copy"
    _copy_package(copy)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SYNAPSE_HLA_", "PYTHON", "UV_", "VIRTUAL_ENV"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    built = _run([uv, "build", "--wheel", "--offline", "--out-dir", tmp_path / "dist",
                  "--build-constraints", copy / "locks" / "build.lock", "--require-hashes"],
                 env=env, cwd=copy)
    if built.returncode != 0 and all(part in built.stderr for part in UV_BACKEND_NOT_CACHED):
        blocked("the build backend of locks/build.lock (setuptools 84.2.1) in uv's cache, which "
                "an offline build reads it from (README, \"Running the tests\")")
    assert built.returncode == 0, built.stderr.decode(errors="replace")[-2000:]
    wheels = list((tmp_path / "dist").glob("*.whl"))
    assert [w.name for w in wheels] == ["synapse_hla-1.0.0-py3-none-any.whl"]
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        assert names == expected_wheel_members()
        for name in names:
            if not name.startswith("synapse_hla-1.0.0.dist-info/"):
                assert wheel.read(name) == (SOURCE.parent / name).read_bytes(), name
        meta = wheel.read("synapse_hla-1.0.0.dist-info/METADATA").decode("utf-8")
        info = wheel.read("synapse_hla-1.0.0.dist-info/WHEEL").decode("utf-8")
    assert "Root-Is-Purelib: true" in info and "Tag: py3-none-any" in info
    assert "Requires-Dist: synapse-cdm<4,>=3.8.0" in meta
    assert "## Profile declaration" in meta
    assert not [n for n in names if n.endswith(".txt") and ".dist-info/" not in n]

    site = tmp_path / "site"
    installed = _run([uv, "pip", "install", "--offline", "--no-deps", "--target", site,
                      wheels[0]], env=env, cwd=tmp_path)
    assert installed.returncode == 0, installed.stderr.decode(errors="replace")[-2000:]
    package_dir = site / "synapse_hla"
    native = _run([cmake, "--install", build_dir, "--prefix", package_dir], env=env,
                  cwd=tmp_path)
    assert native.returncode == 0, native.stderr.decode(errors="replace")[-2000:]
    assert sorted(p.name for p in (package_dir / "bin").iterdir()) == [
        "rtinode", "sc-hla-federate", "sc-hla-publisher"]
    for program, line in (("sc-hla-federate", host.VERSION_LINE),
                          ("sc-hla-publisher", _demo.PUBLISHER_VERSION_LINE)):
        answered = _run([package_dir / "bin" / program, "--version"], env=env, cwd=tmp_path)
        assert (answered.returncode, answered.stdout) == (0, line), program

    outside = tmp_path / "outside"
    outside.mkdir()
    run_env = dict(env, PYTHONPATH=str(site),
                   SYNAPSE_HLA_FOM_DIR=str(fom_modules()[0].parent))
    where = _run([sys.executable, "-c", "import synapse_hla, synapse_hla.host as h, "
                  "synapse_hla._demo as d; print(synapse_hla.__file__); print(h.WORKER_LOCATION);"
                  " print(d.PUBLISHER_LOCATION); print(d.RTINODE_LOCATION)"],
                 env=run_env, cwd=outside)
    assert where.returncode == 0, where.stderr
    assert where.stdout.decode().split() == [
        str(package_dir / "__init__.py"), str(package_dir / "bin" / "sc-hla-federate"),
        str(package_dir / "bin" / "sc-hla-publisher"), str(package_dir / "bin" / "rtinode")]
    version = _run([sys.executable, "-m", "synapse_hla.cli", "--version"], env=run_env,
                   cwd=outside)
    assert (version.returncode, version.stdout) == (0, cli.VERSION_LINE)
    selftest = _run([sys.executable, "-m", "synapse_hla.cli", "self-test", "--out",
                     outside / "selftest"], env=run_env, cwd=outside)
    assert selftest.returncode == 0, selftest.stderr.decode(errors="replace")[-2000:]
    assert json.loads(selftest.stdout)["result"]["result"] == "PASS"
    demo = _run([sys.executable, "-m", "synapse_hla.cli", "demo", "--out", outside / "demo"],
                env=run_env, cwd=outside, timeout=900)
    assert demo.returncode == 0, demo.stderr.decode(errors="replace")[-2000:]
    document = json.loads((outside / "demo" / "demo.json").read_bytes())
    assert document["status"] == "PASS"
    assert (document["adapter_version"], document["profile"]) == ("1.0.0", "SC-HLA-RPR2-OBS-1")
    for process in document["cleanup"]["processes"]:
        assert process["reaped"] and process_gone(process["pid"]), process
    assert sorted(os.listdir(outside)) == ["demo", "selftest"]


def test_the_installed_form_expectations_name_every_file_the_tree_ships():
    """The member list the installed-form test compares a built wheel with is the package
    directory plus nine metadata files, by the hand counts above: 55 package files."""
    assert len(package_files()) == sum(PACKAGE_COUNTS.values()) == 55
    assert len(expected_wheel_members()) == 64
    assert re.fullmatch(r"\d+\.\d+\.\d+", importlib.metadata.version("synapse-cdm"))
