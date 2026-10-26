"""Writes the release SBOM of synapse-hla, locks/sbom.cdx.json (CycloneDX 1.6 JSON), from the locks.

    python tests/release_sbom.py            (from packages/hla: write the file)
    python tests/release_sbom.py --check    (exit 1 when the file is not what the locks give)

A test-side tool (D-04: Python lives under src/synapse_hla and tests only), not product code. Its
inputs are the tracked locks and nothing typed here: `locks/runtime.lock` (the Python runtime
dependencies, exact versions and every distribution file's SHA-256), `locks/native-toolchain.json`
(the OpenRTI source archive, the toolchains that built the native part and the libraries they
linked), `src/synapse_hla/pins.json` (the archive's pin, which the toolchain record must agree
with) and the licence expression each locked Python distribution declares in its own installed
metadata. The installed distributions must be the locked ones, version for version, or the tool
refuses: an SBOM never names a licence read from another version than the one it lists. The one
exception is `synapse-cdm`, the sibling distribution of this repository (CR-L22): a checkout's
own `packages/cdm` may be installed at a later release than the locked one, as at a release
commit whose version the index does not hold yet, so the tool admits an installed `synapse-cdm`
inside the declared range (`pyproject.toml`) and at or above the locked version, and when the
two differ it requires the installed one to declare this repository's licence, the one
`pyproject.toml` declares, which is then the licence listed.

What R43 and NAT-14 ask the SBOM to enumerate: the source archive (by SHA-256, with the licence
offered and the one elected), the compilers (one entry per toolchain that built the native part,
as build tools outside the runtime), the linked libraries (OpenRTI's own, and whether the system
expat and zlib were linked, with their licences) and the Python dependencies. The output carries
no time stamp and no serial number, so the same locks always give the same bytes. No digest is
claimed for anything built (the wheel, the executables): R43 forbids claiming a real digest for a
build the release does not ship as a file.
"""

from __future__ import annotations

import importlib.metadata
import json
import pathlib
import re
import sys
import tomllib

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCKS = PACKAGE_ROOT / "locks"
OUTPUT = LOCKS / "sbom.cdx.json"

#: Licences of the linked system libraries, by the projects' own licence names in SPDX form.
#: expat: the MIT licence of its COPYING; zlib: the zlib licence; the C++ runtimes: libstdc++
#: under GPL-3.0 with the GCC runtime library exception, libc++ under Apache-2.0 with the LLVM
#: exception.
SYSTEM_LICENCES = {
    "expat": "MIT",
    "zlib": "Zlib",
    "c++ runtime": None,
}
CXX_RUNTIME_LICENCES = {
    "DEV-linux-aarch64": ("libstdc++", "GPL-3.0-or-later WITH GCC-exception-3.1"),
    "DEV-macOS-arm64": ("libc++", "Apache-2.0 WITH LLVM-exception"),
}

#: The co-released sibling (CR-L22) and the one shape its declared range may have.
SIBLING = "synapse-cdm"
_RANGE = re.compile(r"^synapse-cdm>=(\d+)\.(\d+)\.(\d+),<(\d+)$")
_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^ ;\\]+)(?: ; ([^\\]+?))? \\$")
_HASH = re.compile(r"^    --hash=sha256:([0-9a-f]{64})(?: \\)?$")


def read_lock(path: pathlib.Path) -> list[dict]:
    """The pinned requirements of a `uv pip compile --generate-hashes` file, in file order:
    name, version, marker or None, and the sorted SHA-256 list. Anything else is refused."""
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        requirement = _REQUIREMENT.match(line)
        if requirement:
            entries.append({"name": requirement.group(1).lower(),
                            "version": requirement.group(2),
                            "marker": requirement.group(3), "sha256": []})
            continue
        digest = _HASH.match(line)
        if digest and entries:
            entries[-1]["sha256"].append(digest.group(1))
            continue
        raise ValueError(f"{path.name}: unexpected line {line!r}")
    for entry in entries:
        if not entry["sha256"]:
            raise ValueError(f"{path.name}: {entry['name']} has no hash")
        entry["sha256"].sort()
    return entries


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _project() -> dict:
    return tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def release(version: str) -> tuple[int, int, int]:
    """A final release number `X.Y.Z` as integers; a pre-release, a development or a local
    version is refused, since the declared range is read for releases only."""
    match = _RELEASE.match(version)
    if not match:
        raise SystemExit(f"{SIBLING}: {version!r} is not a release number X.Y.Z")
    return tuple(int(part) for part in match.groups())


def sibling_range() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """The declared range of the sibling as (floor, excluded ceiling), read from the one
    dependency `pyproject.toml` declares; any other shape is refused."""
    dependencies = _project()["dependencies"]
    match = _RANGE.match(dependencies[0]) if len(dependencies) == 1 else None
    if not match:
        raise SystemExit(f"pyproject.toml declares {dependencies!r}, not one {SIBLING} range "
                         "of the form >=X.Y.Z,<N")
    major, minor, patch, ceiling = (int(part) for part in match.groups())
    return (major, minor, patch), (ceiling, 0, 0)


def sibling_admitted(installed: str, locked: str) -> bool:
    """CR-L22: an installed sibling inside the declared range and at or above the locked
    version."""
    floor, ceiling = sibling_range()
    return floor <= release(installed) < ceiling and release(installed) >= release(locked)


def installed_licence(name: str, version: str) -> str:
    """The licence expression the installed distribution declares, which must be the locked
    version, or for the sibling a version `sibling_admitted` admits (the module text)."""
    metadata = importlib.metadata.metadata(name)
    installed = metadata["Version"]
    if _normal(name) == SIBLING:
        admitted = sibling_admitted(installed, version)
    else:
        admitted = installed == version
    if not admitted:
        raise SystemExit(f"{name}: installed {installed}, locked {version}; install the locked "
                         "set (pip install --require-hashes -r locks/test.lock) and run again")
    expression = metadata.get("License-Expression")
    if not expression:
        raise SystemExit(f"{name} {installed} declares no License-Expression")
    if installed != version and expression != _project()["license"]:
        raise SystemExit(f"{name}: the installed {installed} declares {expression!r}, not this "
                         f"repository's {_project()['license']!r}, so it says nothing of the "
                         f"locked {version}")
    return expression


def _property(name: str, value: str) -> dict:
    return {"name": f"synapse-hla:{name}", "value": value}


def build_sbom() -> dict:
    """The SBOM document, from the locks (see the module text)."""
    toolchain = json.loads((LOCKS / "native-toolchain.json").read_text(encoding="utf-8"))
    pins = {entry["path"]: entry for entry in json.loads(
        (PACKAGE_ROOT / "src/synapse_hla/pins.json").read_text(encoding="utf-8"))["files"]}
    openrti = toolchain["openrti"]
    pin = pins[openrti["archive"]]
    if (pin["sha256"], pin["bytes"]) != (openrti["sha256"], openrti["bytes"]):
        raise SystemExit("native-toolchain.json disagrees with pins.json about the archive")

    components: list[dict] = []
    python_refs = []
    for entry in read_lock(LOCKS / "runtime.lock"):
        if entry["marker"] is not None:
            raise SystemExit(f"runtime.lock: {entry['name']} carries a marker; the SBOM "
                             "enumerates an unconditional runtime set")
        ref = f"pypi:{_normal(entry['name'])}"
        python_refs.append(ref)
        components.append({
            "type": "library", "bom-ref": ref, "name": _normal(entry["name"]),
            "version": entry["version"],
            "purl": f"pkg:pypi/{_normal(entry['name'])}@{entry['version']}",
            "scope": "required",
            "licenses": [{"expression": installed_licence(entry["name"], entry["version"])}],
            "hashes": [{"alg": "SHA-256", "content": h} for h in entry["sha256"]],
            "properties": [_property("hashes", "every distribution file of this release on "
                                     "the Python package index, as locks/runtime.lock lists "
                                     "them")],
        })

    components.append({
        "type": "library", "bom-ref": "openrti:source-archive", "name": "OpenRTI",
        "version": openrti["commit"],
        "description": f"source archive {openrti['archive']}, {openrti['bytes']} bytes",
        "scope": "required",
        "licenses": [{"expression": openrti["licence_elected"]}],
        "hashes": [{"alg": "SHA-256", "content": openrti["sha256"]}],
        "externalReferences": [{"type": "vcs", "url": "https://github.com/onox/OpenRTI/tree/"
                                + openrti["commit"]}],
        "properties": [
            _property("licence-offered", openrti["licence_offered"]),
            _property("linkage", "dynamic: shared libraries, not modified"),
            _property("build-options", " ".join(openrti["options"])),
            _property("bundled-expat-compiled", "yes" if openrti["bundled_expat_compiled"]
                      else "no: the system expat was found and linked"),
        ],
    })
    for name in openrti["libraries"] + openrti["programs"]:
        components.append({
            "type": "library" if name.startswith("lib") else "application",
            "bom-ref": f"openrti:{name}", "name": name, "version": openrti["commit"],
            "scope": "required",
            "licenses": [{"expression": openrti["licence_elected"]}],
            "properties": [_property("built-from", "openrti:source-archive"),
                           _property("installed-at", "lib/" if name.startswith("lib")
                                     else "bin/")],
        })
    for program in ("sc-hla-federate", "sc-hla-publisher"):
        components.append({
            "type": "application", "bom-ref": f"native:{program}", "name": program,
            "version": "1.0.0", "scope": "required", "licenses": [{"expression": "Apache-2.0"}],
            "properties": [_property("built-from", "src/native (C++14) of this distribution"),
                           _property("installed-at", "bin/")],
        })

    for build in toolchain["builds"]:
        label = build["evidence_class"]
        for role, text in (("compiler", build["compiler"]), ("cmake", build["cmake"])):
            components.append({
                "type": "application", "bom-ref": f"build:{label}:{role}",
                "name": role, "version": text, "scope": "excluded",
                "properties": [_property("role", "build tool"),
                               _property("evidence-class", label),
                               _property("system", build["system"]),
                               _property("source", build["source"])],
            })
        for library, linked in sorted(build["linked"].items()):
            if library == "c++ runtime":
                name, licence = CXX_RUNTIME_LICENCES[label]
            else:
                name, licence = library, SYSTEM_LICENCES[library]
            package = {"expat": "libexpat1", "zlib": "zlib1g",
                       "c++ runtime": "libstdc++6"}[library]
            version = build["packages"].get(package, "the system's")
            components.append({
                "type": "library", "bom-ref": f"system:{label}:{name}", "name": name,
                "version": version, "scope": "required",
                "licenses": [{"expression": licence}],
                "properties": [_property("linked", linked),
                               _property("evidence-class", label)],
            })

    components.sort(key=lambda c: c["bom-ref"])
    openrti_refs = [f"openrti:{n}" for n in openrti["libraries"]]
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {
            "component": {
                "type": "application", "bom-ref": "synapse-hla", "name": "synapse-hla",
                "version": "1.0.0", "purl": "pkg:pypi/synapse-hla@1.0.0",
                "licenses": [{"expression": "Apache-2.0"}],
                "properties": [
                    _property("profile", "SC-HLA-RPR2-OBS-1"),
                    _property("wheel", "pure Python (py3-none-any); no digest is claimed for a "
                              "build (R43)"),
                    _property("reference-platform", toolchain["reference"]["status"] + ": "
                              + toolchain["reference"]["missing"]),
                    _property("package-hashes", toolchain["package_hashes"]["status"] + ": "
                              + toolchain["package_hashes"]["missing"]),
                ],
            },
            "tools": {"components": [{"type": "application", "name": "tests/release_sbom.py",
                                      "version": "1.0.0"}]},
        },
        "components": components,
        "dependencies": [
            {"ref": "synapse-hla", "dependsOn": sorted(python_refs + ["native:sc-hla-federate"])},
            {"ref": "native:sc-hla-federate", "dependsOn": sorted(openrti_refs)},
            {"ref": "native:sc-hla-publisher", "dependsOn": sorted(openrti_refs)},
            {"ref": "openrti:rtinode", "dependsOn": ["openrti:libOpenRTI"]},
        ],
    }


def sbom_bytes() -> bytes:
    return (json.dumps(build_sbom(), indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "ascii")


def main(argv: list[str]) -> int:
    data = sbom_bytes()
    if argv == ["--check"]:
        return 0 if OUTPUT.read_bytes() == data else 1
    if argv:
        print(__doc__.split("\n\n", 1)[0], file=sys.stderr)
        return 2
    OUTPUT.write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
