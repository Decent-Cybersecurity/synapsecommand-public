"""Test children for the worker pool, started through `WorkerPool(_child_command=...)` exactly as
the real child is: argument list, scrubbed environment, private directory, inherited descriptors.

    python -I -B slow_child.py MODE AUX [EXTRA] PACKAGE_DIR MEMORY_BYTES

The pool appends PACKAGE_DIR and MEMORY_BYTES, as it does for the real child. Every mode first
appends one line `start <pid>` to AUX, so a test counts how many children ran and can check that
each is dead afterwards. Modes:

    sleep      sleep a minute (a deadline test kills it)
    exit3      exit with status 3
    block      wait until AUX.release exists, then run the real child job
    big        answer one line longer than any lowered answer bound
    overrun    state a 4-octet payload and send 10
    write      write b"partial" to the descriptor EXTRA, then sleep a minute
    preview_partial
               read the request line, write b"partial" to its output descriptor, then sleep a
               minute (a preview killed half-written)
    probe      run the real child setup, then try what the audit hook must refuse (EXTRA is a
               sidecar path to read) and answer what happened
    rlimit     run the real child setup and answer the address-space limit it reads back
    allocate   run the real child setup, allocate 64 MiB, then 1 GiB under the memory guard
"""

import json
import os
import resource
import sys
import time

MODE, AUX = sys.argv[1], sys.argv[2]
EXTRA = sys.argv[3] if len(sys.argv) > 5 else None
PACKAGE_DIR, MEMORY = sys.argv[-2], sys.argv[-1]


def mark() -> None:
    with open(AUX, "a", encoding="ascii") as handle:
        handle.write(f"start {os.getpid()}\n")


def answer(body: dict) -> None:
    sys.stdout.buffer.write((json.dumps(body) + "\n").encode("ascii"))
    sys.stdout.buffer.flush()


def attempt(action) -> str:
    try:
        action()
    except PermissionError:
        return "refused"
    except OSError as error:
        return f"oserror:{error.errno}"
    return "allowed"


def main() -> int:
    mark()
    sys.path.insert(0, PACKAGE_DIR)
    if MODE == "sleep":
        time.sleep(60)
        return 0
    if MODE == "exit3":
        return 3
    if MODE == "write":
        os.write(int(EXTRA), b"partial")
        time.sleep(60)
        return 0
    if MODE == "preview_partial":
        request = json.loads(sys.stdin.buffer.readline())
        os.write(request["output_fd"], b"partial")
        time.sleep(60)
        return 0
    if MODE == "big":
        answer({"ok": True, "pad": "x" * 5000})
        return 0
    if MODE == "overrun":
        sys.stdout.buffer.write(b'{"ok": true, "payload_bytes": 4}\n' + b"0123456789")
        sys.stdout.buffer.flush()
        return 0
    if MODE == "block":
        release = AUX + ".release"
        for _ in range(6000):
            if os.path.exists(release):
                break
            time.sleep(0.01)
        sys.argv = ["-c", PACKAGE_DIR, MEMORY]
        from synapse_imagery.worker import _child_main

        _child_main()
    from synapse_imagery import worker

    report = worker._child_setup(int(MEMORY))
    if MODE == "probe":
        import threading

        probe = {
            "socket": attempt(lambda: __import__("socket").create_connection(("127.0.0.1", 9), 1)),
            "sidecar": attempt(lambda: open(EXTRA, "rb").close()),
            "hosts": attempt(lambda: open("/etc/hosts", "rb").close()),
            "write": attempt(lambda: open(os.path.join(os.getcwd(), "written"), "wb").close()),
            "spawn": attempt(lambda: __import__("subprocess").run(["/bin/echo", "x"])),
            "environment": sorted(os.environ),
            "threads": threading.active_count(),
            "cwd_entries": os.listdir("."),
        }
        answer({"ok": True, "worker": report, "probe": probe})
        return 0
    if MODE == "rlimit":
        answer(
            {"ok": True, "worker": report, "rlimit": list(resource.getrlimit(resource.RLIMIT_AS))}
        )
        return 0
    if MODE == "allocate":

        def allocate() -> int:
            small = bytearray(64 * 1024 * 1024)
            del small
            large = bytearray(1024 * 1024 * 1024)
            del large
            return 0

        return worker._run_guarded(allocate)
    return 2


if __name__ == "__main__":
    os._exit(main())
