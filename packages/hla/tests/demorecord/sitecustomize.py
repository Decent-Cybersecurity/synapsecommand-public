"""The command-line guards, and a record of how each demo run ended (round RF, one test).

`tests/test_hla_demo.py` starts `synapse-hla demo` with this directory first on PYTHONPATH in the
row that stops the demo at its observer host's fork, so Python imports this file as
`sitecustomize` at start-up. It loads `tests/cliguard/sitecustomize.py` by its path, so the
command runs under exactly the guards every other command-line test uses, and then wraps
`synapse_hla._demo.Run.abort`, the end of a run after a failure or a stop. The wrapper runs the
original and then appends one JSON line to the file `SC_HLA_DEMO_RECORD` names, with what the run
knew at that moment: the host's exit status, the publisher's, whether the publisher destroyed its
federation, the workers the host reported, and the run's capture as it stood then. The command
removes its --out directory only after `abort` has returned, so the capture is read before that.
It only reads: nothing of the product's behaviour changes, and the capture is read by the test's
own reading (each line's type, generation, diagnostic code, generation_end reason, the footer),
not through the package.
"""

import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_sc_hla_cliguard", os.path.join(os.path.dirname(_HERE), "cliguard", "sitecustomize.py"))
_cliguard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cliguard)

from synapse_hla import _demo  # the guards above are in place before the package is imported

_RECORD = os.environ["SC_HLA_DEMO_RECORD"]
_original_abort = _demo.Run.abort


def capture_shape(out_path: bytes) -> list | None:
    """The run's capture as the test compares it, or None when there is no capture file."""
    try:
        with open(os.path.join(out_path, b"capture.jsonl"), "rb") as stream:
            data = stream.read()
    except FileNotFoundError:
        return None
    shape = []
    for line in data.split(b"\n")[:-1]:
        record = json.loads(line)
        if record["type"] == "header":
            shape.append(["header"])
        elif record["type"] == "footer":
            shape.append(["footer", record["status"], record["reason_code"]])
        else:
            event = record["event"]
            item = [event["type"], record["generation"]]
            if event["type"] == "diagnostic":
                item.append(event["diagnostic"]["code"])
            elif event["type"] == "generation_end":
                item.append(event["reason"])
            shape.append(item)
    return shape


def _recording_abort(self) -> None:
    _original_abort(self)
    entry = {
        "run": self.name,
        "host_status": None if self.host is None else self.host.status,
        "host_reaped": None if self.host is None else self.host.reaped,
        "workers": None if self.host is None else len(self.host.workers),
        "publisher_status": None if self.publisher is None else self.publisher.status,
        "destroyed": self.destroyed,
        "capture": capture_shape(self.out_path),
    }
    with open(_RECORD, "a", encoding="ascii") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")


_demo.Run.abort = _recording_abort
