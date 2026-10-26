"""The SC4545-CORE-1 benchmark, `gates/nsif_benchmark.py`, reduced: its workload constants, the
containers it builds, the input-cap probe, the nearest-rank percentile, and a verdict that reads
no timing (REQ-087, REQ-088).

REQ-087's and REQ-088's targets are judged on the recorded reference machine by its operator, so
no test here compares a duration with a number. Expectations are literals: the cap, the shapes,
the rewritten size fields (written out by hand from the field widths), the sample formulas'
first values, and the refusal's code, stage and path. Repository-bound: it loads the gate by path
from `gates/`, which the wheel does not carry.
"""

from __future__ import annotations

import copy
import json
import pathlib
import types

import pytest

import synapse_cdm
from synapse_cdm.adapters import nsif_codec as nc

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "nsif_benchmark.py"
MONO = (
    pathlib.Path(synapse_cdm.__file__).resolve().parent
    / "fixtures"
    / "stanag4545"
    / "mono_nsif101.ntf"
)


@pytest.fixture(scope="module")
def bench():
    """The gate module, from its SOURCE, as `tests/test_cdm_dis7_benchmark.py` loads its gate."""
    module = types.ModuleType("_nsif_benchmark_gate")
    module.__file__ = str(GATE_PATH)
    exec(compile(GATE_PATH.read_text(encoding="utf-8"), str(GATE_PATH), "exec"), module.__dict__)
    return module


@pytest.fixture(scope="module")
def quick_report(bench, tmp_path_factory):
    path = tmp_path_factory.mktemp("nsif_benchmark") / "benchmark.json"
    assert bench.main(["--quick", "--machine", "test run", "--out", str(path)]) == 0
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_workloads_are_the_required_ones(bench):
    assert bench.INPUT_CAP == 16_777_216
    assert bench.INVENTORY_SHAPE == (19, 882_967)
    assert 843 + 19 * 882_967 == 16_777_216
    assert (bench.WINDOW_SHAPE, bench.WINDOW_NBPP) == ((1024, 1024), 16)
    assert (bench.WARMUP_RUNS, bench.MEASURED_RUNS) == (1, 10)
    assert bench.WORKLOADS == ("inventory", "translate", "window")


def test_the_sample_formulas_start_where_the_docstring_says(bench):
    assert bench.payload(1, 3, 8) == b"\x00\x01\x02"
    assert bench.payload(1, 252, 8)[249:] == bytes((249, 250, 0))
    assert bench.payload(1, 3, 16) == bytes.fromhex("000700260045")


def test_the_cap_sized_container_rewrites_only_its_size_fields(bench):
    nrows, ncols = bench.INVENTORY_SHAPE
    data = bench.payload(nrows, ncols, 8)
    raw = bench.build_container(nrows, ncols, 8, data)
    mono = MONO.read_bytes()
    assert len(raw) == 16_777_216
    assert raw[342:354] == b"000016777216"  # FL
    assert raw[369:379] == b"0016776373"  # LI
    assert raw[737:753] == b"0000001900882967"  # NROWS, NCOLS
    assert raw[772:774] == b"08"  # ABPP
    assert raw[803:811] == b"00000000"  # NPPBH, NPPBV: one block each way
    assert raw[811:813] == b"08"  # NBPP
    for start, end in ((0, 342), (354, 369), (379, 737), (753, 772), (774, 803), (813, 843)):
        assert raw[start:end] == mono[start:end], (start, end)
    image = nc.parse_container(raw, nc.CORE1_LIMITS).images[0]
    assert (image.nrows, image.ncols, image.block_width, image.block_height) == (
        19,
        882_967,
        882_967,
        19,
    )
    assert image.pixel_status == "native_supported"


def test_the_window_container_is_a_mono_sixteen_bit_image(bench):
    data = bench.payload(4, 3, 16)
    raw = bench.build_container(4, 3, 16, data)
    assert raw[342:354] == b"000000000867" and raw[369:379] == b"0000000024"
    container = nc.parse_container(raw, nc.CORE1_LIMITS)
    image = container.images[0]
    assert (image.nbpp, image.abpp, image.pvtype, image.nrows, image.ncols) == (16, 16, "INT", 4, 3)
    window = nc.decode_nc_window(container, 0, 0, 0, 3, 4, (0,))
    assert window.data == data


def test_the_cap_probe_refuses_one_octet_over(bench):
    probe = bench.cap_probe()
    assert probe == {
        "accepted_octets": 16_777_216,
        "accepted": True,
        "refused_octets": 16_777_217,
        "refusal": ["E_LIMIT", "input", None, "/input"],
        "enforced": True,
    }


def test_the_percentile_is_nearest_rank(bench):
    assert bench.percentile(list(range(1, 11)), 0.50) == 5
    assert bench.percentile(list(range(1, 11)), 0.95) == 10
    assert bench.percentile([10, 20, 30, 40], 0.50) == 20
    assert bench.percentile([10, 20, 30, 40], 0.95) == 40
    assert bench.percentile([7], 0.95) == 7


def test_the_quick_run_passes_its_checks(quick_report):
    report = quick_report
    assert report["quick"] is True and report["verdict"] == "PASS"
    assert report["schema"] == "synapse.nsif-benchmark/v1"
    assert [item["workload"] for item in report["workloads"]] == [
        "inventory",
        "translate",
        "window",
    ]
    assert [item["observed"] for item in report["workloads"]] == [
        {"images": 1, "pixel_status": "native_supported", "data_octets": 19 * 3_449},
        {"objects": 1, "wire_equals_input": True},
        {"samples": 64 * 64, "equals_payload": True},
    ]
    for item in report["workloads"]:
        assert (item["warmup_runs"], item["measured_runs"]) == (1, 10)
        assert len(item["elapsed_ns"]) == 10 and item["passed"] is True
    assert report["cap"]["enforced"] is True
    assert report["environment"]["machine_description"] == "test run"


def test_the_verdict_ignores_every_timing(bench, quick_report):
    doubled = copy.deepcopy(quick_report)
    for item in doubled["workloads"]:
        item["elapsed_ns"] = [2 * value for value in item["elapsed_ns"]]
        item["p50_ns"] *= 2
        item["p95_ns"] *= 2
        if item["peak_rss_bytes"] is not None:
            item["peak_rss_bytes"] *= 2
    assert bench.verdict(quick_report) == bench.verdict(doubled) == "PASS"
    wrong = copy.deepcopy(quick_report)
    wrong["workloads"][2]["observed"]["equals_payload"] = False
    assert bench.verdict(wrong) == "FAIL"
    open_cap = copy.deepcopy(quick_report)
    open_cap["cap"]["enforced"] = False
    assert bench.verdict(open_cap) == "FAIL"
    missing = copy.deepcopy(quick_report)
    missing["workloads"] = missing["workloads"][:2]
    assert bench.verdict(missing) == "FAIL"
