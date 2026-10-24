"""Shared support for the observation adapters' tests: builders, fixture sets, identifiers.

A helper, not a test module. The observation adapters' test modules import it, so the three
checks every one of them owes are written once, here, and tested once, in
`tests/test_cdm_observation_contracts.py`:

- the fixture builder's `--check`, run the way the mechanical check runs it — `python -I -B
  <dir>/spec/build_fixtures.py --check` from a working directory outside the tree — and required
  to print `CURRENT`, exit 0 and leave the fixture directory byte-identical (CONTRIBUTING.md,
  "Writing a fixture builder"); and the in-process loader, which compiles the builder in memory
  as `tests/test_cdm_generator_loading.py` requires of every loader, so no bytecode is read or
  written beside it;
- the fixture set: every payload listed in its directory's `PROVENANCE.json`, synthetic, and every
  binary payload beside its `.parsed.json` twin;
- the identifier convention for observation fixtures (CONTRIBUTING.md, "Identifiers and places in
  observation fixtures"): the synthetic station, radar-site and aircraft-address blocks, and the
  Baltic rectangle every stated position lies in.

Every check returns its findings as a list of strings — empty means it holds — so a test asserts
`== []` and a failure names what is wrong.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import types
from typing import Any

from synapse_cdm import evidence, harness

#: One synthetic block per identifier grammar, as CONTRIBUTING.md states them.
STATION_ID_FORMS = {
    "alphanumeric-5": re.compile(r"EX0(?:0[1-9]|[1-9][0-9])"),
    "numeric-7": re.compile(r"00000(?:0[1-9]|[1-9][0-9])"),
    "air-quality-9": re.compile(r"0000000(?:0[1-9]|[1-9][0-9])"),
    "air-quality-12": re.compile(r"0000000000(?:0[1-9]|[1-9][0-9])"),
    "frost-station": re.compile(r"SN000(?:0[1-9]|[1-9][0-9])"),
}
RADAR_SITE = re.compile(r"ZZZZ|XZZ[A-Z]")
AIRCRAFT_ADDRESS = re.compile(r"0029[0-9A-Fa-f]{2}")
#: The `ais` fixtures' MMSI rule (fixtures/ais/README.md): MID 299, as a ship station, a coast
#: station, an aid to navigation or an AIS-SART; nine digits, leading zeros kept.
MMSI_MID_299 = re.compile(r"299[0-9]{6}|00299[0-9]{4}|99299[0-9]{4}|970299[0-9]{3}")

#: (south, north, west, east), degrees: the Baltic rectangle.
BALTIC_RECTANGLE = (56.0, 58.5, 20.0, 24.5)


def station_id_problems(station_id: str, form: str) -> list[str]:
    if form not in STATION_ID_FORMS:
        return [f"{form!r} is not a station-id form of the convention"]
    if not isinstance(station_id, str) or STATION_ID_FORMS[form].fullmatch(station_id) is None:
        return [f"{station_id!r} is not in the synthetic {form} block"]
    return []


def radar_site_problems(site: str) -> list[str]:
    if not isinstance(site, str) or RADAR_SITE.fullmatch(site) is None:
        return [f"{site!r} is not ZZZZ or XZZA to XZZZ"]
    return []


def aircraft_address_problems(address: str) -> list[str]:
    if not isinstance(address, str) or AIRCRAFT_ADDRESS.fullmatch(address) is None:
        return [f"{address!r} is not in the 0029xx block"]
    return []


def mmsi_problems(mmsi: str) -> list[str]:
    """An MMSI as its nine decimal digits, held to the MID 299 block."""
    if not isinstance(mmsi, str) or MMSI_MID_299.fullmatch(mmsi) is None:
        return [f"{mmsi!r} is not under MID 299"]
    return []


def _inside(lat: float, lon: float) -> bool:
    south, north, west, east = BALTIC_RECTANGLE
    return south <= lat <= north and west <= lon <= east


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positions(coordinates: Any, path: str) -> list[tuple[str, float, float]]:
    """Every [lon, lat, ...] position below a GeoJSON `coordinates` member."""
    if (
        isinstance(coordinates, list)
        and len(coordinates) >= 2
        and all(_number(v) for v in coordinates)
    ):
        return [(path, coordinates[1], coordinates[0])]
    found = []
    if isinstance(coordinates, list):
        for index, child in enumerate(coordinates):
            found += _positions(child, f"{path}[{index}]")
    return found


def positions_outside_the_rectangle(document: Any, path: str = "$") -> list[str]:
    """Every stated position in a JSON document that lies outside the Baltic rectangle.

    A position is an object holding numeric `lat` and `lon`, or a GeoJSON position under a
    `coordinates` member. Walks CDM dumps, parsed twins and goldens alike.
    """
    found: list[str] = []
    if isinstance(document, dict):
        lat, lon = document.get("lat"), document.get("lon")
        if _number(lat) and _number(lon) and not _inside(lat, lon):
            found.append(f"{path}: ({lat}, {lon})")
        for key, value in document.items():
            if key == "coordinates":
                found += [
                    f"{where}: ({la}, {lo})"
                    for where, la, lo in _positions(value, f"{path}.{key}")
                    if not _inside(la, lo)
                ]
            else:
                found += positions_outside_the_rectangle(value, f"{path}.{key}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found += positions_outside_the_rectangle(value, f"{path}[{index}]")
    return found


# -- the fixture set -----------------------------------------------------------------------------


def provenance_problems(adapter_dir: pathlib.Path) -> list[str]:
    """`evidence.provenance_problems` for one adapter's directory and its covered subdirectories."""
    name = adapter_dir.name
    return [
        problem
        for problem in evidence.provenance_problems(adapter_dir.parent)
        if problem.startswith((f"{name}/", f"{name}:"))
    ]


def twin_problems(directory: pathlib.Path) -> list[str]:
    """Every binary payload of `directory` without its `.parsed.json` twin, and every twin
    without its payload. The twin of `x.ext` is `x.parsed.json`."""
    payloads = harness.select_fixtures(directory)
    names = {p.name for p in payloads}
    problems = []
    for payload in payloads:
        if payload.name.endswith(".json"):
            continue
        twin = f"{payload.stem}.parsed.json"
        if twin not in names:
            problems.append(f"{payload.name}: no {twin} beside it")
    for payload in payloads:
        if payload.name.endswith(".parsed.json"):
            stem = payload.name.removesuffix(".parsed.json")
            if not any(p.stem == stem and not p.name.endswith(".json") for p in payloads):
                problems.append(f"{payload.name}: a twin of no payload")
    return problems


# -- the builder ---------------------------------------------------------------------------------


def _snapshot(directory: pathlib.Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    """Every path added, removed or rewritten with other bytes, sorted."""
    return sorted(set(after) ^ set(before) | {k for k in before if after.get(k) != before[k]})


def run_builder_check(
    fixture_dir: pathlib.Path, cwd: pathlib.Path, python: str = sys.executable
) -> subprocess.CompletedProcess:
    """`python -I -B <fixture_dir>/spec/build_fixtures.py --check`, from `cwd`."""
    script = fixture_dir / "spec" / "build_fixtures.py"
    return subprocess.run(
        [python, "-I", "-B", str(script), "--check"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=600,
    )


def builder_problems(
    fixture_dir: pathlib.Path, cwd: pathlib.Path, python: str = sys.executable
) -> list[str]:
    """What is wrong with a builder's `--check` run: an exit other than 0, a last line other
    than `CURRENT`, a fixture directory that changed, a working directory that changed (since
    2026-10-15: a builder that writes beside wherever it is run from leaves a file the fixture
    directory's snapshot never sees), bytecode left beside the builder."""
    before, cwd_before = _snapshot(fixture_dir), _snapshot(cwd)
    # Bytecode directories are read before and after as well (2026-10-16): the claim is that the
    # `--check` run writes none, not that none exists. In one pytest session other modules import
    # their own `spec/build_fixtures.py` in memory, and an interpreter without `-B` leaves
    # `spec/__pycache__` behind them; the wheel gate's slice runs exactly such a session against
    # the installed package, where an absolute "no `__pycache__` anywhere" reading failed for the
    # five observation adapters on CI run 38976967421 while the kit, which sets
    # PYTHONDONTWRITEBYTECODE, never saw it.
    pycache_before = _pycache_dirs(fixture_dir)
    result = run_builder_check(fixture_dir, cwd, python)
    after, cwd_after = _snapshot(fixture_dir), _snapshot(cwd)
    problems = []
    if result.returncode != 0:
        problems.append(f"--check exited {result.returncode}: {result.stdout}{result.stderr}")
    if result.stdout.strip().splitlines()[-1:] != ["CURRENT"]:
        problems.append(f"--check did not end with CURRENT: {result.stdout!r}")
    if after != before:
        problems.append(f"--check changed the fixture directory: {_changed(before, after)}")
    if cwd_after != cwd_before:
        problems.append(f"--check changed its working directory: {_changed(cwd_before, cwd_after)}")
    written = sorted(_pycache_dirs(fixture_dir) - pycache_before)
    if written:
        problems.append(f"bytecode was written under the fixture directory: {written}")
    return problems


def _pycache_dirs(directory: pathlib.Path) -> set[str]:
    """Every `__pycache__` directory under `directory`, relative, as the bytecode delta's basis."""
    return {
        p.relative_to(directory).as_posix() for p in directory.rglob("__pycache__") if p.is_dir()
    }


def load_builder(path: pathlib.Path, name: str = "build_fixtures") -> types.ModuleType:
    """A fixture builder, compiled in memory from its source, with `sys.path` restored after.

    `exec(compile(...))` and never `exec_module`: the source loader consults and writes
    `__pycache__`, and a `.pyc` validated on whole-second mtime and size can stand for a source it
    was not compiled from (`tests/test_cdm_generator_loading.py`).
    """
    module = types.ModuleType(name)
    module.__file__ = str(path)
    saved = list(sys.path)
    try:
        exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    finally:
        sys.path[:] = saved
    return module
