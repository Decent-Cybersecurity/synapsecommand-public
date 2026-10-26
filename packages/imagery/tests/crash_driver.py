"""The process-level crash driver: one ingest in its own process whose fault point either kills
the process with `os._exit(97)`, so the store is left exactly as a real process death leaves it,
or pauses it on a pipe until the test lets it continue.

    python crash_driver.py ROOT VECTOR POINT MODE

MODE `exit` dies at POINT (a service step or a store link point); `pause` prints `paused` and
waits for one line on stdin at POINT; `derivative` ingests VECTOR normally and then dies at POINT
inside a derivative commit. On a normal end the driver prints the result's state and exits 0."""

import io
import os
import sys

from helpers import sha, vector

from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.fakes import FakePolicy
from synapse_imagery.ingest import IngestService
from synapse_imagery.policy import (
    Artefact,
    PolicyRequest,
    Principal,
    SecurityDescriptor,
    TicketAuthority,
)

LOCAL = Principal("local", "local-operator")


def main() -> int:
    root, name, point, mode = sys.argv[1:5]
    armed = [mode != "derivative"]

    def fault(reached: str) -> None:
        if not armed[0] or reached != point:
            return
        if mode == "pause":
            sys.stdout.write("paused\n")
            sys.stdout.flush()
            sys.stdin.readline()
            return
        os._exit(97)

    store = LocalAssetStore(root, _fault=fault)
    with IngestService(store, _fault=fault) as service:
        result = service.ingest(
            vector(name), principal=LOCAL, dataset_namespace="default", synthetic=True
        )
    if mode == "derivative":
        record = store.read_record("local", result["record_id"], area="records")
        descriptor = SecurityDescriptor.from_json(record["descriptor"])
        authority = TicketAuthority(FakePolicy({Artefact.THUMBNAIL: True}))
        ticket = authority.issue(
            PolicyRequest(
                LOCAL, Artefact.THUMBNAIL, descriptor, True, result["record_id"], result["asset_id"]
            )
        )
        job = store.new_job(tenant="local")
        temp = store.new_temp(job, ".png")
        payload = b"derivative octets"
        out = store.open_temp(temp)
        with io.FileIO(out, "wb") as handle:
            handle.write(payload)
        armed[0] = True
        store.commit_derivative(
            result["asset_id"],
            temp,
            sha(payload),
            {"algorithm": "test"},
            descriptor,
            tenant="local",
            policy_ticket=ticket,
            provenance={},
        )
    sys.stdout.write(result["state"] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
