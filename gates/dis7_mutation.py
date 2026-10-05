"""The DIS 7 mutation matrix: each implementation fault of case A14, injected into a copy.

WHAT IT DOES
------------
The gate copies `packages/cdm` into a temporary directory, runs the DIS7 test modules of this
repository against that copy once unpatched (the control) and once per row of `MUTANTS`, and
records which tests caught each fault. No file in the worktree is ever patched: a patch is written
into the copy, the run is made, and the copy's file is restored from the worktree and compared
byte for byte before the next row.

Two path settings put the copy under test, and both are needed. `pytest.ini`'s `pythonpath`
outranks `PYTHONPATH` inside the pytest process, so the nested run passes `-o pythonpath=<copy>`;
child processes the tests spawn see only `PYTHONPATH`, so it is exported as well. A planted test
module proves both: the package, `ids` and the two DIS7 modules must be imported from the copy in
process and in a child. A control that is not green, or a plant that did not pass, stops the gate
before any mutant runs.

A row is DETECTED only when pytest exits exactly 1 and at least one failing test belongs to one of
the row's groups (the acceptance groups whose tests execute the seam). Exit codes 2 to 5, a
timeout, a failed plant or an anchor that is absent or repeated are harness errors (ERROR), never
detections.

    python gates/dis7_mutation.py --out matrix.json [--only ID ...] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ElementTree

REPO = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = "synapse.dis7-mutation-matrix/v1"
EXCLUDED = ("test_cdm_dis7_mutation.py", "test_cdm_dis7_reference.py")
PLANT_NAME = "test_zzz_mutation_copy_probe.py"
PLANT_TESTS = ("test_the_suite_imported_the_copy_in_process", "test_a_child_process_imports_the_copy")
TIMEOUT = 900
MAX_KILLERS = 20

PLANT = '''import pathlib, subprocess, sys
import synapse_cdm, synapse_cdm.ids
import synapse_cdm.adapters.dis7, synapse_cdm.adapters.dis7_codec
COPY = pathlib.Path({copy!r})
MODULES = (synapse_cdm, synapse_cdm.ids, synapse_cdm.adapters.dis7, synapse_cdm.adapters.dis7_codec)
def test_the_suite_imported_the_copy_in_process():
    for module in MODULES:
        assert COPY in pathlib.Path(module.__file__).resolve().parents, module.__file__
def test_a_child_process_imports_the_copy():
    code = ("import synapse_cdm.ids, synapse_cdm.adapters.dis7 as a, synapse_cdm.adapters.dis7_codec as c;"
            "print(synapse_cdm.__file__); print(synapse_cdm.ids.__file__); print(a.__file__); print(c.__file__)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(out) == 4
    for path in out:
        assert COPY in pathlib.Path(path).resolve().parents, path
'''

# The restamp row patches the one call site of `_replay_bytes` in `from_cdm`, where the stored
# instant is in scope as `context.instant`: octets 4 to 7 become the DIS encoding of the state
# instant's position in its hour. On every vector that is 0x40000001, the octets already there.
_RESTAMP = (
    "        _wire = _replay_bytes(stored_wire)\n"
    "        _text = context.instant\n"
    "        _seconds = int(_text[14:16]) * 60 + int(_text[17:19]) + int(_text[20:23]) / 1000\n"
    "        _stamp = (int(_seconds * 2**31 / 3600) << 1) | 1\n"
    "        return _wire[:4] + _stamp.to_bytes(4, \"big\") + _wire[8:]\n"
)

MUTANTS = (
    {
        "id": "swap_lat_lon",
        "fault": "swap latitude and longitude",
        "seam": "_assemble_position",
        "file": "synapse_cdm/adapters/dis7.py",
        "old": "def _assemble_position(lat_deg, lon_deg, hae_m):\n",
        "new": ("def _assemble_position(lat_deg, lon_deg, hae_m):\n"
                "    return _assemble_position_original(lon_deg, lat_deg, hae_m)\n\n\n"
                "def _assemble_position_original(lat_deg, lon_deg, hae_m):\n"),
        "groups": ("t05",),
    },
    {
        "id": "body_velocity_as_world",
        "fault": "treat body velocity as world velocity",
        "seam": "WORLD_ALGORITHMS",
        "file": "synapse_cdm/adapters/dis7_codec.py",
        "old": "WORLD_ALGORITHMS = frozenset({2, 3, 4, 5})\n",
        "new": "WORLD_ALGORITHMS = frozenset({2, 3, 4, 5, 6, 7, 8, 9})\n",
        "groups": ("t06",),
    },
    {
        "id": "drop_opaque_record",
        "fault": "drop an opaque record",
        "seam": "_decode_records",
        "file": "synapse_cdm/adapters/dis7_codec.py",
        "old": "def _decode_records(raw: bytes, count: int) -> list[str]:\n",
        "new": ("def _decode_records(raw: bytes, count: int) -> list[str]:\n"
                "    return _decode_records_original(raw, count)[:-1]\n\n\n"
                "def _decode_records_original(raw: bytes, count: int) -> list[str]:\n"),
        "groups": ("t03", "t10"),
    },
    {
        "id": "affiliation_from_force",
        "fault": "infer affiliation from force ID",
        "seam": "_affiliation",
        "file": "synapse_cdm/adapters/dis7.py",
        "old": "def _affiliation(force_id):\n",
        "new": ("def _affiliation(force_id):\n"
                "    if force_id == 1:\n"
                "        return Affiliation.FRIENDLY\n"
                "    return _affiliation_original(force_id)\n\n\n"
                "def _affiliation_original(force_id):\n"),
        "groups": ("t10",),
    },
    {
        "id": "receipt_time_adapter_clock",
        "fault": "use receipt time",
        "seam": "_state_instant",
        "file": "synapse_cdm/adapters/dis7.py",
        "old": "def _state_instant(adapter, context):\n",
        "new": ("def _state_instant(adapter, context):\n"
                "    _state_instant_original(adapter, context)\n"
                "    return adapter.now()\n\n\n"
                "def _state_instant_original(adapter, context):\n"),
        "groups": ("t09", "t13"),
    },
    {
        "id": "receipt_time_wall_clock",
        "fault": "use receipt time",
        "seam": "_state_instant",
        "file": "synapse_cdm/adapters/dis7.py",
        "old": "def _state_instant(adapter, context):\n",
        "new": ("def _state_instant(adapter, context):\n"
                "    _state_instant_original(adapter, context)\n"
                "    return __import__(\"datetime\").datetime.now(__import__(\"datetime\").timezone.utc)\n\n\n"
                "def _state_instant_original(adapter, context):\n"),
        "groups": ("t09", "t13"),
    },
    {
        "id": "uuid_namespace",
        "fault": "change the UUID namespace",
        "seam": "NAMESPACE",
        "file": "synapse_cdm/ids.py",
        "old": "NAMESPACE = uuid.UUID(\"6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50\")",
        "new": "NAMESPACE = uuid.UUID(\"6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c51\")",
        "groups": ("t01", "t08"),
    },
    {
        "id": "restamp_timestamp",
        "fault": "restamp the DIS timestamp",
        "seam": "_replay_bytes",
        "file": "synapse_cdm/adapters/dis7.py",
        "old": "        return _replay_bytes(stored_wire)\n",
        "new": _RESTAMP,
        "groups": ("t09",),
    },
    {
        "id": "stale_pdu_after_edit",
        "fault": "emit a stale source PDU after a canonical edit",
        "seam": "_canonical_equal",
        "file": "synapse_cdm/adapters/dis7.py",
        "old": "def _canonical_equal(provided, expected):\n",
        "new": ("def _canonical_equal(provided, expected):\n"
                "    _canonical_equal_original(provided, expected)\n"
                "    return True\n\n\n"
                "def _canonical_equal_original(provided, expected):\n"),
        "groups": ("t11",),
    },
)


def dis7_modules() -> list[str]:
    """The DIS7 test modules the gate runs: every one but this gate's own and the reference one."""
    return sorted("tests/" + p.name for p in (REPO / "tests").glob("test_cdm_dis7_*.py")
                  if p.name not in EXCLUDED)


def apply_patch(text: str, old: str, new: str) -> str:
    """`text` with its one occurrence of `old` replaced; refuses an absent or repeated anchor."""
    if old == new:
        raise ValueError("the patch changes nothing")
    found = text.count(old)
    if found != 1:
        raise ValueError(f"the anchor occurs {found} times, not once")
    return text.replace(old, new)


def classify(exit_code, failed, groups, plant_ok) -> tuple[str, list[str]]:
    """DETECTED needs exit code 1 and a failing test in one of `groups`; harness faults are ERROR."""
    if not plant_ok or exit_code not in (0, 1):
        return ("ERROR", [])
    patterns = [re.compile(rf"(?<![a-z0-9]){re.escape(group)}_") for group in groups]
    killers = [name for name in failed
               if any(p.search(name.split("::", 1)[-1].lower()) for p in patterns)]
    if exit_code == 1 and killers:
        return ("DETECTED", killers)
    return ("NOT_DETECTED", [])


def read_junit(path: pathlib.Path) -> tuple[list[str], bool]:
    """The failed test names and whether both plant tests passed, from one junit file."""
    if not path.is_file():
        return [], False
    failed = []
    plant = {}
    for case in ElementTree.parse(path).getroot().iter("testcase"):
        name = case.get("name", "")
        broken = case.find("failure") is not None or case.find("error") is not None
        if broken:
            failed.append(f"{case.get('classname', '')}::{name}")
        if name in PLANT_TESTS:
            plant[name] = not broken and case.find("skipped") is None
    plant_ok = len(plant) == len(PLANT_TESTS) and all(plant.values())
    return failed, plant_ok


def run_suite(copy: pathlib.Path, plant: pathlib.Path, junit: pathlib.Path) -> dict:
    """One nested pytest run of the DIS7 modules against `copy`."""
    junit.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(copy), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("PYTEST_ADDOPTS", None)
    started = time.monotonic()
    try:
        exit_code = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "-o", f"pythonpath={copy}", "--junitxml", str(junit), *dis7_modules(), str(plant)],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        exit_code = None
    failed, plant_ok = read_junit(junit)
    return {"exit_code": exit_code, "failed": failed, "plant_ok": plant_ok,
            "seconds": round(time.monotonic() - started, 1)}


def run_mutant(row: dict, copy: pathlib.Path, plant: pathlib.Path, tmp: pathlib.Path) -> dict:
    """One row: patch the copy, run, restore and confirm the copy equals the worktree again."""
    result = {"id": row["id"], "fault": row["fault"], "seam": row["seam"], "file": row["file"],
              "groups": list(row["groups"]), "exit_code": None, "failed": 0, "killers": [],
              "detail": "", "seconds": 0.0}
    source = REPO / "packages" / "cdm" / row["file"]
    target = copy / row["file"]
    try:
        patched = apply_patch(source.read_text(encoding="utf-8"), row["old"], row["new"])
    except ValueError as error:
        result.update(status="ERROR", detail=f"patch refused: {error}")
        return result
    target.write_text(patched, encoding="utf-8")
    try:
        run = run_suite(copy, plant, tmp / "junit" / f"{row['id']}.xml")
    finally:
        shutil.copyfile(source, target)
    if target.read_bytes() != source.read_bytes():
        raise RuntimeError(f"the copy of {row['file']} was not restored")
    status, killers = classify(run["exit_code"], run["failed"], row["groups"], run["plant_ok"])
    if status == "ERROR":
        detail = "harness error: exit code {} with the plant {}".format(
            run["exit_code"], "passing" if run["plant_ok"] else "not passing")
    elif status == "NOT_DETECTED":
        detail = f"no failing test in {list(row['groups'])}"
    else:
        detail = f"{len(killers)} failing tests in {list(row['groups'])}"
    result.update(status=status, exit_code=run["exit_code"], failed=len(run["failed"]),
                  killers=killers[:MAX_KILLERS], detail=detail, seconds=run["seconds"])
    return result


def write_matrix(out: pathlib.Path, matrix: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="where the JSON matrix is written")
    parser.add_argument("--only", action="append", default=[], metavar="ID",
                        help="run the control and only this row (repeatable)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the temporary directory and print its path")
    args = parser.parse_args(argv)

    known = [row["id"] for row in MUTANTS]
    unknown = [ident for ident in args.only if ident not in known]
    if unknown:
        print(f"unknown mutant id: {', '.join(unknown)}")
        return 2
    rows = [row for row in MUTANTS if not args.only or row["id"] in args.only]

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dis7-mutation-")).resolve()
    if tmp == REPO or REPO in tmp.parents:
        print(f"refusing a temporary directory inside the repository: {tmp}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 2
    try:
        copy = tmp / "packages" / "cdm"
        shutil.copytree(REPO / "packages" / "cdm", copy,
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "dist"))
        plant = tmp / "plant" / PLANT_NAME
        plant.parent.mkdir(parents=True)
        plant.write_text(PLANT.format(copy=str(copy)), encoding="utf-8")

        matrix = {"schema": SCHEMA, "python": sys.version.split()[0], "modules": dis7_modules()}
        control = run_suite(copy, plant, tmp / "junit" / "control.xml")
        green = control["exit_code"] == 0 and control["plant_ok"]
        matrix["control"] = {"status": "GREEN" if green else "RED",
                             "exit_code": control["exit_code"],
                             "imported_from_copy": control["plant_ok"],
                             "seconds": control["seconds"]}
        print(f"control: {matrix['control']['status']} (exit code {control['exit_code']}, "
              f"imported from the copy: {control['plant_ok']})")
        results = []
        if green:
            for row in rows:
                result = run_mutant(row, copy, plant, tmp)
                results.append(result)
                print(f"{result['id']}: {result['status']} ({result['detail']})")
        else:
            print("the control is not green: no mutant was run")
        detected = sum(1 for r in results if r["status"] == "DETECTED")
        passed = green and len(results) == len(rows) and detected == len(rows)
        matrix["mutants"] = results
        matrix["summary"] = {"faults": len({r["fault"] for r in results}),
                             "mutants": len(results), "detected": detected,
                             "control_green": green, "complete": not args.only}
        matrix["result"] = "PASS" if passed else "FAIL"
        write_matrix(pathlib.Path(args.out), matrix)
        print(f"result: {matrix['result']} ({detected} of {len(rows)} detected)")
        return 0 if passed else 1
    finally:
        if args.keep:
            print(f"temporary directory kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
