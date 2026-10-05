"""The DIS 7 benchmark: recorded decode-plus-mapping measurements, never a performance commitment.

WHY THIS EXISTS
---------------
The DIS 7 contract (the handoff document `SC DIS7 SPEC 001 v1.0`, which is not in this
repository; requirement R23) asks for performance to be RECORDED rather than promised: decoding
plus mapping for 100 000 accepted PDUs after a 1000-call warm-up, for the 144-byte equator vector
and for the 4224-byte maximal PDU of case A02, with the machine, the runtimes, elapsed time,
throughput, p50/p95 call latency and peak process memory written down. No numeric SLA applies,
so the verdict reads no timing field. What IS mandatory is that the input bound holds (4224
octets accepted, 4225 refused with `E_INPUT_LIMIT` at `$`, case N09) and that a repeated
identical workload retains no memory: both decide the verdict.

The maximal PDU is built in-process from the equator seed on every run; it is never written to
disk and is not a packaged fixture.

    python gates/dis7_benchmark.py --out FILE            # the full workload; exit 0 on PASS
    python gates/dis7_benchmark.py --quick --out FILE    # the reduced workload the tests run

`tests/test_cdm_dis7_benchmark.py` runs the reduced workload on every test run and asserts the
bound and the absence of retained growth, never a timing.
"""
from __future__ import annotations

import argparse
import datetime
import gc
import importlib.metadata
import json
import math
import os
import pathlib
import platform
import subprocess
import sys
import time
import tracemalloc

try:
    import resource
except ImportError:
    resource = None

from synapse_cdm import version
from synapse_cdm.adapters.dis7 import Dis7Adapter, Dis7Error, TimeContext

#: Requirement R23's workload: accepted PDUs per fixture, and the untimed warm-up before them.
FULL_CALLS = 100000
WARMUP_CALLS = 1000
#: The reduced workload `--quick` runs (the always-on test).
QUICK_CALLS = 2000
QUICK_WARMUP = 200
#: Traced bytes a second identical pass may hold beyond the first before the verdict is FAIL.
RETAINED_ALLOWANCE_BYTES = 65536

SESSION = "benchmark"
INSTANT = "2026-04-29T06:15:00.000Z"
BASIS = "Benchmark workload on a synthetic fixture; not capture time"

SCHEMA = "synapse.dis7-benchmark/v1"
NOTE = "Recorded measurements, not a performance commitment; no numeric SLA applies."
MAX_PDU_BYTES = 4224
MAX_RECORDS = 255
RECORD_BYTES = 16


def seed_pdu() -> bytes:
    """The equator vector's bytes, read from the installed package."""
    package = pathlib.Path(sys.modules["synapse_cdm"].__file__).resolve().parent
    return (package / "fixtures" / "dis7" / "vectors" / "equator_eastbound.dis").read_bytes()


def build_max_pdu(seed: bytes) -> bytes:
    """Case A02: the seed with 255 zero-filled records and the length field set to 4224."""
    raw = bytearray(seed)
    raw[19] = MAX_RECORDS
    raw[8:10] = MAX_PDU_BYTES.to_bytes(2, "big")
    raw += bytes(MAX_RECORDS * RECORD_BYTES)
    return bytes(raw)


def make_adapter():
    return Dis7Adapter(session=SESSION, synthetic=True, time_context=TimeContext(INSTANT, BASIS))


def bound_enforced(adapter, max_pdu) -> bool:
    """True only if the maximal PDU maps to one object and one more octet is refused at `$`."""
    accepted = adapter.to_cdm(max_pdu)
    if not isinstance(accepted, list) or len(accepted) != 1:
        return False
    try:
        adapter.to_cdm(max_pdu + b"\x00")
    except Dis7Error as exc:
        return exc.code == "E_INPUT_LIMIT" and exc.path == "$"
    return False


def percentile(sorted_values, q):
    """Nearest rank: the smallest value at or above the fraction `q` of the sorted values."""
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def timed_pass(call, raw, calls, warmup) -> dict:
    for _ in range(warmup):
        call(raw)
    latencies = [0] * calls
    counter = time.perf_counter_ns
    first_start = counter()
    for index in range(calls):
        start = counter()
        call(raw)
        latencies[index] = counter() - start
    last_end = counter()
    elapsed_s = (last_end - first_start) / 1e9
    latencies.sort()
    return {
        "calls": calls,
        "elapsed_s": elapsed_s,
        "throughput_per_s": calls / elapsed_s,
        "p50_us": percentile(latencies, 0.50) / 1000,
        "p95_us": percentile(latencies, 0.95) / 1000,
    }


def retained_growth(call, raw, calls) -> dict:
    """Traced memory after a second identical pass, less the memory after the first."""
    gc.collect()
    tracemalloc.start()
    for _ in range(calls):
        call(raw)
    gc.collect()
    first = tracemalloc.get_traced_memory()[0]
    for _ in range(calls):
        call(raw)
    gc.collect()
    second, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "retained_after_first_bytes": first,
        "retained_after_second_bytes": second,
        "retained_growth_bytes": second - first,
        "tracemalloc_peak_bytes": peak,
    }


def peak_rss_bytes():
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def _cpu_model() -> str:
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/cpuinfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        elif sys.platform == "darwin":
            completed = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, check=True, timeout=10,
            )
            model = completed.stdout.strip()
            if model:
                return model
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return platform.processor() or platform.machine()


def _ram_bytes():
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return None


def environment() -> dict:
    return {
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": _ram_bytes(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "package_version": version.PACKAGE_VERSION,
        "adapter_version": Dis7Adapter.version,
        "cdm_schema_version": version.SCHEMA_VERSION,
        "adapter_api_version": version.ADAPTER_API_VERSION,
        "pydantic_version": importlib.metadata.version("pydantic"),
    }


def run(calls, warmup, quick) -> dict:
    adapter = make_adapter()
    seed = seed_pdu()
    inputs = (
        {"name": "equator_eastbound", "bytes": len(seed), "records": seed[19], "raw": seed},
        {"name": "a02_maximal", "bytes": MAX_PDU_BYTES, "records": MAX_RECORDS,
         "raw": build_max_pdu(seed)},
    )
    enforced = bound_enforced(adapter, inputs[1]["raw"])
    timings = [timed_pass(adapter.to_cdm, item["raw"], calls, warmup) for item in inputs]
    peak_rss = peak_rss_bytes()
    growths = [retained_growth(adapter.to_cdm, item["raw"], calls) for item in inputs]
    fixtures = []
    for item, timing, growth in zip(inputs, timings, growths):
        fixtures.append({"name": item["name"], "bytes": item["bytes"], "records": item["records"],
                         **timing, **growth})
    report = {
        "schema": SCHEMA,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "quick": quick,
        "calls": calls,
        "warmup": warmup,
        "environment": environment(),
        "context": {"session": SESSION, "synthetic": True, "instant": INSTANT, "basis": BASIS},
        "fixtures": fixtures,
        "peak_rss_bytes": peak_rss,
        "bound_enforced": enforced,
        "retained_allowance_bytes": RETAINED_ALLOWANCE_BYTES,
        "note": NOTE,
    }
    report["result"] = verdict(report)
    return report


def verdict(report) -> str:
    """PASS only if the bound holds and no fixture retains more than the allowance; no timing."""
    if report["bound_enforced"] is not True:
        return "FAIL"
    allowance = report["retained_allowance_bytes"]
    for fixture in report["fixtures"]:
        if fixture["retained_growth_bytes"] > allowance:
            return "FAIL"
    return "PASS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dis7_benchmark",
        description="Record DIS 7 decode-plus-mapping measurements (no numeric SLA applies).",
    )
    parser.add_argument("--out", required=True, type=pathlib.Path, help="the JSON report to write")
    parser.add_argument("--quick", action="store_true",
                        help=f"the reduced workload: {QUICK_CALLS} calls after {QUICK_WARMUP}")
    args = parser.parse_args(argv)
    if args.quick:
        report = run(QUICK_CALLS, QUICK_WARMUP, True)
    else:
        report = run(FULL_CALLS, WARMUP_CALLS, False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for fixture in report["fixtures"]:
        print(f"{fixture['name']}: {fixture['bytes']} bytes, {fixture['records']} records, "
              f"{fixture['calls']} calls, retained growth {fixture['retained_growth_bytes']} bytes")
    print(f"bound enforced: {report['bound_enforced']}; result: {report['result']}")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
