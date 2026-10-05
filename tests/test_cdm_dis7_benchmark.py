"""The reduced DIS 7 benchmark: the input bound and the absence of retained growth, never a timing.

`gates/dis7_benchmark.py` records requirement R23's measurements; this module runs its reduced
workload (`--quick`) on every test run and asserts only what the requirement makes mandatory:
4224 octets are accepted with all 255 records, one more octet is refused with `E_INPUT_LIMIT` at
`$` (case N09), and a second identical pass retains no memory beyond the allowance. No test here
compares `elapsed_s`, `throughput_per_s`, `p50_us` or `p95_us` with a number: no numeric SLA
applies.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import types

import pytest

from synapse_cdm.adapters.dis7 import Dis7Error
from tests import dis7_support

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "dis7_benchmark.py"

#: case A02's maximal PDU built from the equator vector, computed independently of the gate.
MAX_PDU_SHA256 = "2e800c75a805bea772ecc4da612e93d15b08907257998521b01ad850364cef5c"


@pytest.fixture(scope="module")
def bench():
    """The gate module, from its SOURCE, loaded as `tests/test_cdm_gate_rosters.py` loads its gate."""
    module = types.ModuleType("_dis7_benchmark_gate")
    module.__file__ = str(GATE_PATH)
    exec(compile(GATE_PATH.read_text(), str(GATE_PATH), "exec"), module.__dict__)
    return module


@pytest.fixture(scope="module")
def quick_report(bench, tmp_path_factory):
    path = tmp_path_factory.mktemp("dis7_benchmark") / "benchmark.json"
    assert bench.main(["--quick", "--out", str(path)]) == 0
    return json.loads(path.read_text(encoding="utf-8"))


def test_r23_workload_sizes_are_the_required_ones(bench):
    assert bench.FULL_CALLS == 100000
    assert bench.WARMUP_CALLS == 1000
    assert bench.QUICK_CALLS == 2000
    assert bench.RETAINED_ALLOWANCE_BYTES == 65536


def test_r23_maximal_pdu_is_case_a02(bench):
    raw = bench.build_max_pdu(dis7_support.seed())
    assert len(raw) == 4224
    assert raw[19] == 255
    assert raw[8:10] == bytes.fromhex("1080")
    assert raw[144:] == bytes(4080)
    assert hashlib.sha256(raw).hexdigest() == MAX_PDU_SHA256


def test_r23_bound_is_enforced_at_4224_octets(bench):
    raw = bench.build_max_pdu(dis7_support.seed())
    adapter = bench.make_adapter()

    objects = adapter.to_cdm(raw)
    assert len(objects) == 1
    assert objects[0].residual.data["pdu"]["variable_parameters_hex"] == ["00" * 16] * 255

    with pytest.raises(Dis7Error) as caught:
        adapter.to_cdm(raw + b"\x00")
    assert caught.value.code == "E_INPUT_LIMIT"
    assert caught.value.path == "$"

    assert bench.bound_enforced(adapter, raw) is True

    class StandIn:
        def to_cdm(self, raw):
            return [object()]

    assert bench.bound_enforced(StandIn(), raw) is False


def test_r23_percentile_is_nearest_rank(bench):
    assert bench.percentile(list(range(1, 101)), 0.50) == 50
    assert bench.percentile(list(range(1, 101)), 0.95) == 95
    assert bench.percentile([10, 20, 30, 40], 0.50) == 20
    assert bench.percentile([10, 20, 30, 40], 0.95) == 40
    assert bench.percentile([7], 0.95) == 7


def test_r23_retained_growth_sees_a_leak(bench):
    kept = []

    def leak(raw):
        kept.append(bytearray(64))

    def length(raw):
        return len(raw)

    assert bench.retained_growth(leak, b"", 2000)["retained_growth_bytes"] > 65536
    assert bench.retained_growth(length, b"", 2000)["retained_growth_bytes"] <= 65536


def test_r23_quick_run_has_no_retained_growth(quick_report):
    report = quick_report
    assert report["quick"] is True
    assert report["calls"] == 2000
    assert [f["bytes"] for f in report["fixtures"]] == [144, 4224]
    assert [f["records"] for f in report["fixtures"]] == [0, 255]
    for fixture in report["fixtures"]:
        assert fixture["retained_growth_bytes"] <= 65536, fixture["name"]
    assert report["bound_enforced"] is True
    assert report["result"] == "PASS"
    assert report["schema"] == "synapse.dis7-benchmark/v1"
    assert set(report["environment"]) == {
        "cpu_model", "cpu_count", "ram_bytes", "os", "machine", "python", "package_version",
        "adapter_version", "cdm_schema_version", "adapter_api_version", "pydantic_version",
    }


def test_r23_verdict_ignores_timings(bench):
    def report(growth, enforced=True):
        fixture = {"elapsed_s": 1e9, "throughput_per_s": 1e-9, "p50_us": 1e12, "p95_us": 1e12,
                   "retained_growth_bytes": growth}
        return {"fixtures": [dict(fixture), dict(fixture)], "bound_enforced": enforced,
                "retained_allowance_bytes": 65536}

    assert bench.verdict(report(0)) == "PASS"
    assert bench.verdict(report(65536)) == "PASS"
    assert bench.verdict(report(65537)) == "FAIL"
    assert bench.verdict(report(0, enforced=False)) == "FAIL"
