"""Case A14 (group T16, requirement R27): the DIS 7 mutation gate, `gates/dis7_mutation.py`.

The gate injects each implementation fault of case A14 into a temporary copy of `packages/cdm`
and runs the DIS7 test modules against it. This module holds the gate to its table, its anchors,
its classification rule and, in the slow test, to "control green, nine mutants DETECTED" with the
worktree left exactly as it was.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "dis7_mutation.py"

ADAPTER_PY = "synapse_cdm/adapters/dis7.py"
CODEC_PY = "synapse_cdm/adapters/dis7_codec.py"
IDS_PY = "synapse_cdm/ids.py"

TABLE = {
    "swap_lat_lon": ("swap latitude and longitude", ADAPTER_PY, ("t05",)),
    "body_velocity_as_world": ("treat body velocity as world velocity", CODEC_PY, ("t06",)),
    "drop_opaque_record": ("drop an opaque record", CODEC_PY, ("t03", "t10")),
    "affiliation_from_force": ("infer affiliation from force ID", ADAPTER_PY, ("t10",)),
    "receipt_time_adapter_clock": ("use receipt time", ADAPTER_PY, ("t09", "t13")),
    "receipt_time_wall_clock": ("use receipt time", ADAPTER_PY, ("t09", "t13")),
    "uuid_namespace": ("change the UUID namespace", IDS_PY, ("t01", "t08")),
    "restamp_timestamp": ("restamp the DIS timestamp", ADAPTER_PY, ("t09",)),
    "stale_pdu_after_edit": ("emit a stale source PDU after a canonical edit", ADAPTER_PY, ("t11",)),
}


@pytest.fixture(scope="module")
def gate():
    """The gate module, from its SOURCE, loaded by path and never registered in `sys.modules`."""
    module = types.ModuleType("_dis7_mutation_gate")
    module.__file__ = str(GATE_PATH)
    exec(compile(GATE_PATH.read_text(), str(GATE_PATH), "exec"), module.__dict__)
    return module


def test_t16_a14_gate_loads_with_no_side_effects(gate):
    assert callable(gate.main)
    assert gate.REPO == REPO
    assert len(gate.MUTANTS) == 9


def test_t16_a14_mutant_table_is_the_eight_faults(gate):
    got = {m["id"]: (m["fault"], m["file"], tuple(m["groups"])) for m in gate.MUTANTS}
    assert got == TABLE
    assert [m["id"] for m in gate.MUTANTS] == list(TABLE)
    faults = [m["fault"] for m in gate.MUTANTS]
    assert len(set(faults)) == 8
    shared = sorted(m["id"] for m in gate.MUTANTS if faults.count(m["fault"]) > 1)
    assert shared == ["receipt_time_adapter_clock", "receipt_time_wall_clock"]


def test_t16_a14_every_patch_anchor_occurs_exactly_once(gate):
    for row in gate.MUTANTS:
        text = (REPO / "packages" / "cdm" / row["file"]).read_text(encoding="utf-8")
        assert text.count(row["old"]) == 1, row["id"]
        assert row["old"] != row["new"], row["id"]


def test_t16_a14_module_list_excludes_itself_and_the_reference_module(gate):
    excluded = {"test_cdm_dis7_mutation.py", "test_cdm_dis7_reference.py"}
    expected = sorted("tests/" + p.name for p in (REPO / "tests").glob("test_cdm_dis7_*.py")
                      if p.name not in excluded)
    assert gate.dis7_modules() == expected
    assert "tests/test_cdm_dis7_adapter.py" in expected
    assert not excluded & {name.split("/")[-1] for name in expected}


def test_t16_a14_classify_needs_exit_one_and_a_failure_in_the_group(gate):
    hit = "tests.test_cdm_dis7_adapter::test_t05_a03_x"
    sweep = "tests.test_cdm_dis7_adapter::test_sweep[t05_a03]"
    assert gate.classify(1, [hit], ("t05",), True) == ("DETECTED", [hit])
    assert gate.classify(1, [sweep], ("t05",), True) == ("DETECTED", [sweep])
    assert gate.classify(1, ["tests.test_cdm_dis7_adapter::test_t02_n01_x"], ("t05",), True) \
        == ("NOT_DETECTED", [])
    assert gate.classify(1, ["tests.test_cdm_dis7_adapter::test_shift05_x"], ("t05",), True) \
        == ("NOT_DETECTED", [])
    assert gate.classify(0, [], ("t05",), True) == ("NOT_DETECTED", [])
    for code in (2, 3, 4, 5, None):
        assert gate.classify(code, [hit], ("t05",), True) == ("ERROR", []), code
    assert gate.classify(1, [hit], ("t05",), False) == ("ERROR", [])


def test_t16_a14_patch_refuses_an_absent_or_repeated_anchor(gate):
    assert gate.apply_patch("a b a", "b", "X") == "a X a"
    for old, new in (("a", "X"), ("z", "X"), ("b", "b")):
        with pytest.raises(ValueError):
            gate.apply_patch("a b a", old, new)


def _porcelain():
    return subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True,
                          text=True, check=True).stdout


def test_t16_a14_every_fault_is_detected_and_the_control_is_green(gate, tmp_path):
    before = _porcelain()
    out = tmp_path / "matrix.json"
    assert gate.main(["--out", str(out)]) == 0
    matrix = json.loads(out.read_text(encoding="utf-8"))
    assert matrix["schema"] == "synapse.dis7-mutation-matrix/v1"
    assert matrix["control"]["status"] == "GREEN"
    assert matrix["control"]["imported_from_copy"] is True
    rows = matrix["mutants"]
    assert [row["id"] for row in rows] == list(TABLE)
    for row in rows:
        assert row["status"] == "DETECTED", row
        assert row["killers"], row["id"]
        assert row["exit_code"] == 1, row["id"]
    assert len({row["fault"] for row in rows}) == 8
    assert matrix["summary"] == {"faults": 8, "mutants": 9, "detected": 9,
                                 "control_green": True, "complete": True}
    assert matrix["result"] == "PASS"
    assert _porcelain() == before
