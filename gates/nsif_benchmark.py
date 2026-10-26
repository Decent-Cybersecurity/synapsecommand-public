"""The SC4545-CORE-1 benchmark: recorded measurements of three workloads, never a performance claim.

WHY THIS EXISTS
---------------
The STANAG 4545 imagery adapter's requirement REQ-087 states acceptance targets for a recorded
Linux x86_64 machine with four virtual CPUs, at least 8 GiB of memory and a local SSD: one warm-up
and ten measured runs, p50/p95 elapsed time and peak RSS, for the inventory of a 16 MiB simple NC
container, for its full CDM serialisation, and (REQ-088) for the decode of a 1024 x 1024 mono
16-bit window. Those targets are measured on that machine by its operator; a run anywhere else is
indicative only and its figures are never copied into the repository or compared between runs.
So the verdict reads no timing field. It is PASS when every workload produced exactly what it
must (the counts and digests below, each known before the workload runs) and the input cap holds:
16,777,216 octets are parsed and 16,777,217 are refused `E_LIMIT` at `/input`.

THE WORKLOADS
-------------
* `inventory`: `parse_container` over a 16,777,216-octet container holding one mono 8-bit image
  of 19 x 882,967 samples in one block (the file is exactly the input cap);
* `translate`: `to_cdm` of the same container and the canonical serialisation of what it
  returns, the form the goldens are written in;
* `window`: `decode_nc_window` of the whole of a 1024 x 1024 mono 16-bit image.

The containers are `mono_nsif101.ntf`'s header and subheader with the size fields rewritten, built
in memory on every run and never written to disk. Each workload runs in its own child interpreter
(an explicit argument list, the parent's `synapse_cdm` on `PYTHONPATH`), so its peak RSS is its
own.

    python gates/nsif_benchmark.py --machine "<description>" --out FILE   # the full workloads
    python gates/nsif_benchmark.py --quick --machine "<description>" --out FILE

`tests/test_cdm_nsif_benchmark.py` runs the reduced workloads and asserts the cap, the
constants, the checks and that the verdict ignores timings; it asserts no duration.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import pathlib
import platform
import subprocess
import sys
import time

try:
    import resource
except ImportError:
    resource = None

import synapse_cdm
from synapse_cdm import canonical, times, version
from synapse_cdm.adapters import nsif_codec
from synapse_cdm.adapters.stanag4545 import Stanag4545Adapter

SCHEMA = "synapse.nsif-benchmark/v1"
NOTE = (
    "Indicative measurements: REQ-087's targets are judged on the recorded reference machine "
    "only, and no figure here is evidence or a commitment."
)
WARMUP_RUNS = 1
MEASURED_RUNS = 10
INPUT_CAP = 16_777_216
#: The full inventory container: one mono 8-bit image of 19 x 882,967 samples, so that the 843
#: octets of header and subheader and the payload are exactly the input cap.
INVENTORY_SHAPE = (19, 882_967)
#: The full window: 1024 x 1024 mono samples of 16 bits.
WINDOW_SHAPE = (1024, 1024)
WINDOW_NBPP = 16
#: The reduced shapes `--quick` runs.
QUICK_INVENTORY_SHAPE = (19, 3_449)
QUICK_WINDOW_SHAPE = (64, 64)
WORKLOADS = ("inventory", "translate", "window")
GATE = str(pathlib.Path(__file__).resolve())

#: Where `mono_nsif101.ntf` keeps the fields a rebuilt container rewrites: (offset, width).
FL = (342, 12)
LI = (369, 10)
NROWS = (737, 8)
NCOLS = (745, 8)
ABPP = (772, 2)
NPPBH = (803, 4)
NPPBV = (807, 4)
NBPP = (811, 2)
HEADERS = 843


def _seed() -> bytes:
    package = pathlib.Path(synapse_cdm.__file__).resolve().parent
    return (package / "fixtures" / "stanag4545" / "mono_nsif101.ntf").read_bytes()


def payload(nrows: int, ncols: int, nbpp: int) -> bytes:
    """Deterministic samples, row-major, big-endian: sample i is i modulo 251 (8 bits) or
    (31 * i + 7) modulo 65,521 (16 bits)."""
    count = nrows * ncols
    if nbpp == 8:
        unit = bytes(range(251))
        return (unit * (count // 251 + 1))[:count]
    return b"".join(((31 * i + 7) % 65521).to_bytes(2, "big") for i in range(count))


def build_container(nrows: int, ncols: int, nbpp: int, data: bytes) -> bytes:
    """One mono NC image in one block (NPPBH and NPPBV 0000) holding `data`."""
    octets = bytearray(_seed()[:HEADERS])
    for (offset, width), value in (
        (FL, HEADERS + len(data)),
        (LI, len(data)),
        (NROWS, nrows),
        (NCOLS, ncols),
        (ABPP, nbpp),
        (NPPBH, 0),
        (NPPBV, 0),
        (NBPP, nbpp),
    ):
        octets[offset : offset + width] = str(value).zfill(width).encode("ascii")
    return bytes(octets) + data


def percentile(sorted_values: list, q: float):
    """Nearest rank: the smallest value at or above the fraction `q` of the sorted values."""
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def peak_rss_bytes():
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def _workload(name: str, quick: bool):
    """(the call to time, the check of its last result, the input size, what is expected)."""
    if name in ("inventory", "translate"):
        nrows, ncols = QUICK_INVENTORY_SHAPE if quick else INVENTORY_SHAPE
        data = payload(nrows, ncols, 8)
        raw = build_container(nrows, ncols, 8, data)
        if name == "inventory":
            expected = {"images": 1, "pixel_status": "native_supported", "data_octets": len(data)}

            def run():
                return nsif_codec.parse_container(raw, nsif_codec.CORE1_LIMITS)

            def check(container) -> dict:
                image = container.images[0]
                return {
                    "images": len(container.images),
                    "pixel_status": image.pixel_status,
                    "data_octets": image.segment.data.length,
                }

            return run, check, len(raw), expected
        adapter = Stanag4545Adapter(clock=times.frozen_clock())
        expected = {"objects": 1, "wire_equals_input": True}

        def run():
            return canonical.serialise(
                [item.model_dump(mode="json") for item in adapter.to_cdm(raw)]
            )

        def check(text) -> dict:
            document = json.loads(text)
            wire = document[0]["residual"]["data"]["stanag4545"]["wire_b64"]
            return {"objects": len(document), "wire_equals_input": base64.b64decode(wire) == raw}

        return run, check, len(raw), expected
    nrows, ncols = QUICK_WINDOW_SHAPE if quick else WINDOW_SHAPE
    data = payload(nrows, ncols, WINDOW_NBPP)
    raw = build_container(nrows, ncols, WINDOW_NBPP, data)
    container = nsif_codec.parse_container(raw, nsif_codec.CORE1_LIMITS)
    expected = {"samples": nrows * ncols, "equals_payload": True}

    def run():
        return nsif_codec.decode_nc_window(container, 0, 0, 0, ncols, nrows, (0,))

    def check(window) -> dict:
        return {"samples": len(window.data) // 2, "equals_payload": window.data == data}

    return run, check, len(raw), expected


def measure(name: str, quick: bool) -> dict:
    """One workload in this process: the warm-up, the measured runs, the check of the last."""
    run, check, size, expected = _workload(name, quick)
    for _ in range(WARMUP_RUNS):
        run()
    elapsed = []
    result = None
    for _ in range(MEASURED_RUNS):
        start = time.perf_counter_ns()
        result = run()
        elapsed.append(time.perf_counter_ns() - start)
    observed = check(result)
    ordered = sorted(elapsed)
    return {
        "workload": name,
        "input_octets": size,
        "warmup_runs": WARMUP_RUNS,
        "measured_runs": MEASURED_RUNS,
        "elapsed_ns": elapsed,
        "p50_ns": percentile(ordered, 0.50),
        "p95_ns": percentile(ordered, 0.95),
        "peak_rss_bytes": peak_rss_bytes(),
        "expected": expected,
        "observed": observed,
        "passed": observed == expected,
    }


def cap_probe() -> dict:
    """The cap holds at the limit and one octet over, through `parse_container`."""
    nrows, ncols = INVENTORY_SHAPE
    raw = build_container(nrows, ncols, 8, payload(nrows, ncols, 8))
    accepted = (
        len(raw) == INPUT_CAP
        and len(nsif_codec.parse_container(raw, nsif_codec.CORE1_LIMITS).images) == 1
    )
    refusal = None
    try:
        nsif_codec.parse_container(raw + b"\x00", nsif_codec.CORE1_LIMITS)
    except nsif_codec.NsifError as error:
        refusal = [error.code, error.stage, error.offset, error.path]
    return {
        "accepted_octets": len(raw),
        "accepted": accepted,
        "refused_octets": len(raw) + 1,
        "refusal": refusal,
        "enforced": accepted and refusal == ["E_LIMIT", "input", None, "/input"],
    }


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(pathlib.Path(synapse_cdm.__file__).resolve().parent.parent)
    return environment


def measure_isolated(name: str, quick: bool) -> dict:
    """One workload in a fresh child interpreter, so that its peak RSS is its own."""
    flags = ["--quick"] if quick else []
    completed = subprocess.run(
        [sys.executable, "-B", GATE, "--workload", name, *flags],
        capture_output=True,
        text=True,
        env=_child_environment(),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"the {name} workload's child failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def verdict(report: dict) -> str:
    """PASS only if every workload's check holds and the cap is enforced; no timing is read."""
    if report["cap"]["enforced"] is not True:
        return "FAIL"
    if [item["workload"] for item in report["workloads"]] != list(WORKLOADS):
        return "FAIL"
    for item in report["workloads"]:
        if item["observed"] != item["expected"]:
            return "FAIL"
    return "PASS"


def environment(machine: str) -> dict:
    return {
        "machine_description": machine,
        "platform": platform.platform(),
        "processor": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "package_version": version.PACKAGE_VERSION,
        "adapter_version": Stanag4545Adapter.version,
    }


def run(machine: str, quick: bool) -> dict:
    report = {
        "schema": SCHEMA,
        "quick": quick,
        "environment": environment(machine),
        "workloads": [measure_isolated(name, quick) for name in WORKLOADS],
        "cap": cap_probe(),
        "note": NOTE,
    }
    report["verdict"] = verdict(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nsif_benchmark",
        description="Record SC4545-CORE-1 workload measurements (indicative off the reference).",
    )
    parser.add_argument("--out", type=pathlib.Path, help="the JSON report to write")
    parser.add_argument("--machine", help="a description of the machine, written into the report")
    parser.add_argument("--quick", action="store_true", help="the reduced workloads")
    parser.add_argument("--workload", choices=WORKLOADS, help="the child side: one workload")
    args = parser.parse_args(argv)
    if args.workload:
        print(json.dumps(measure(args.workload, args.quick)))
        return 0
    if args.out is None or not args.machine:
        parser.error("--out and --machine are required")
    report = run(args.machine, args.quick)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for item in report["workloads"]:
        print(f"{item['workload']}: {item['input_octets']} octets, check {item['observed']}")
    print(f"cap enforced: {report['cap']['enforced']}; verdict: {report['verdict']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
