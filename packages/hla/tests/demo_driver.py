"""Runs one scenario of the demo's orchestration in a fresh interpreter (test only).

    python demo_driver.py ARGUMENTS_JSON

`tests/test_hla_rti.py` starts it as a child process, because the orchestration forks the
observer's host as the command line does, and a fork inside the pytest process (whose other
tests leave threads behind) is neither safe nor allowed by its warning filter. ARGUMENTS_JSON
names the kind of run, the output directory, the result file, and the executables (the same
SYNAPSE_HLA_* variables the command line reads are in the environment). It starts the demo's
own rtinode (`_demo.Rtinode`), runs `_demo.run_scenario` with the command line's host fork, and
writes what happened as JSON for the test to judge:

- `main`: the publisher's main scenario, the observer joining in mode existing (A-CLASS evidence
  outside the demo command);
- `perf`: the publisher's `perf:O:H:S` load shape under the host (the DEV early warning of R42);
- `rst`, `fin`: the observer connects through `rti_proxy.py`, which is told to break the
  connection at a moment the capture shows (NAT-03, NAV-02);
- `refresh`: as `rst`, but the reset comes once the capture shows step 4, so the rejoined
  observer's request for values reaches a publisher that holds a value of every attribute
  (R38: "It responds to provideAttributeValueUpdate by sending its current values, including
  requests arriving between scripted updates").

Nothing here judges anything; the tests do.
"""

import json
import os
import pathlib
import select
import signal
import subprocess
import sys

from synapse_hla import _demo, _examples, _fom, canonical, cli, config

ARGS = json.loads(sys.argv[1])
HERE = pathlib.Path(__file__).resolve().parent
ENVIRON = dict(os.environ)
SEAMS = _demo.V1


def existing_config(port: int, federation: str) -> dict:
    """config-existing.json with only the endpoint and the federation replaced."""
    document = canonical.strict_loads(_examples.CONFIG_EXISTING, floats=False, surrogates=False)
    document["endpoint"] = f"rti://127.0.0.1:{port}"
    document["federation_name"] = federation
    return config.validate_config(document)


def start_proxy(upstream: int, mode: str) -> tuple[subprocess.Popen, int]:
    proxy = subprocess.Popen([sys.executable, str(HERE / "rti_proxy.py"), str(upstream), mode],
                             stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    return proxy, json.loads(proxy.stdout.readline())["port"]


def break_through(proxy: subprocess.Popen) -> int:
    """SIGUSR1 to the proxy, then its confirmation: the break has happened before the run goes
    on (a step acknowledged after it cannot reach the observer before it)."""
    proxy.send_signal(signal.SIGUSR1)
    ready, _, _ = select.select([proxy.stdout], [], [], 10)
    assert ready, "the proxy did not confirm the break"
    return json.loads(proxy.stdout.readline())["broken"]


def main() -> None:
    kind = ARGS["kind"]
    out = os.fsencode(ARGS["out"])
    modules = _fom.check_fom_modules(ENVIRON[cli.FOM_DIR_VARIABLE])
    pins = {module.name: module.sha256 for module in modules}
    node = _demo.Rtinode()
    result = {"kind": kind, "broken": None, "triggered_at": None}
    proxy = None
    try:
        problem = node.start(ENVIRON[cli.RTINODE_VARIABLE], ENVIRON, SEAMS, lambda: None)
        assert problem is None, problem
        federation = _demo.new_federation_name()
        hook = None
        if kind in ("rst", "fin", "refresh"):
            proxy, proxy_port = start_proxy(node.port, "fin" if kind == "fin" else "rst")
            document = existing_config(proxy_port, federation)
            if kind == "rst":
                # The break once the observer's first generation has discovered the object; the
                # steps then wait for the second generation.
                scenario = _demo.Scenario("main", tuple(
                    [_demo.Barrier(0, "discover", None, 1, generation=2)] +
                    [_demo.Barrier(n, "reflect", f"step-{n}".encode(), 1, generation=2)
                     for n in range(1, 5)] +
                    [_demo.Barrier(5, "remove", b"step-5", 1, generation=2),
                     _demo.Barrier(6, "resigned", None, 1)]), stop_after=5)

                def trigger(run: _demo.Run) -> bool:
                    return run.tail.count("discover", None, 1) >= 1
            elif kind == "refresh":
                # The reset once the capture shows step 4 (the publisher then waits at barrier
                # 4, holding all four values); barrier 4 is the answer to the second
                # generation's request (a reflection tagged `refresh`), barrier 5 the removal
                # in that generation.
                scenario = _demo.Scenario("main", tuple(
                    [_demo.Barrier(0, "discover", None, 1)] +
                    [_demo.Barrier(n, "reflect", f"step-{n}".encode(), 1) for n in range(1, 4)] +
                    [_demo.Barrier(4, "reflect", b"refresh", 1, generation=2),
                     _demo.Barrier(5, "remove", b"step-5", 1, generation=2),
                     _demo.Barrier(6, "resigned", None, 1)]), stop_after=5)

                def trigger(run: _demo.Run) -> bool:
                    return run.tail.count("reflect", b"step-4") >= 1
            else:
                # The break once the capture shows step 4; barrier 5 is then the removal OpenRTI
                # makes up for the object it knows when the connection ends (an empty tag).
                scenario = _demo.Scenario("main", tuple(
                    [_demo.Barrier(0, "discover", None, 1)] +
                    [_demo.Barrier(n, "reflect", f"step-{n}".encode(), 1) for n in range(1, 5)] +
                    [_demo.Barrier(5, "remove", b"", 1), _demo.Barrier(6, "resigned", None, 1)]),
                    stop_after=5)

                def trigger(run: _demo.Run) -> bool:
                    return run.tail.count("reflect", b"step-4") >= 1

            def hook(run: _demo.Run) -> None:
                if result["broken"] is None and trigger(run):
                    result["triggered_at"] = run.tail.frames[-1]["seq"]
                    result["broken"] = break_through(proxy)
        elif kind == "main":
            document = existing_config(node.port, federation)
            scenario = _demo.main_scenario()
        else:
            objects, hz, seconds = ARGS["perf"]
            document = _demo.run_config(ARGS.get("config", "main"), node.port, federation)
            scenario = _demo.perf_scenario(objects, hz, seconds)
        run, failure = _demo.run_scenario(
            "main", document, out, scenario, publisher=ENVIRON[_demo.PUBLISHER_VARIABLE],
            fom_dir=os.path.dirname(modules[0].path), pins=pins, environ=ENVIRON,
            start_host=lambda d, o, c: cli._start_demo_host(d, o, c, ENVIRON, False),
            check=lambda: None, hook=hook, publisher_endpoint=f"rti://127.0.0.1:{node.port}")
        result.update({
            "failure": None if failure is None else {"stage": failure.stage,
                                                     "reason": failure.reason},
            "federation": federation, "document": document,
            "acknowledged": {str(k): v for k, v in run.acknowledged.items()},
            "registered_class": run.registered_class, "destroyed": run.destroyed,
            "publisher_failure": run.publisher_failure,
            "publisher_status": run.publisher.status if run.publisher else None,
            "host_result": None if run.host is None else run.host.result,
            "host_status": None if run.host is None else run.host.status,
            "processes": run.processes(), "refreshes": run.refreshes,
            "refresh_reflections": run.refresh_reflections,
            "refresh_seqs": run.refresh_seqs(), "module_sha256": run.module_sha256,
            # Every line the publisher wrote, as written (the tests read its own words).
            "publisher_events": [] if run.publisher is None else [
                json.loads(line) for line in bytes(run.publisher.stdout).split(b"\n") if line],
        })
    finally:
        if proxy is not None:
            proxy.terminate()
            proxy.wait(10)
            result["proxy_pid"] = proxy.pid
        node.stop(SEAMS)
        result["rtinode"] = {"pid": None if node.child is None else node.child.pid,
                             "port": node.port, "port_released": node.port_released}
        pathlib.Path(ARGS["result"]).write_text(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
