"""Regenerate the three packaged DIS 7 Entity State PDUs through open-dis-python and compare them.

The three PDUs under `vectors/` are the handoff bundle's bytes, packaged byte-identical; the bundle
records that they were generated with open-dis-python. This script rebuilds each one from its
scenario in `SCENARIOS` through that library and reports whether the octets it produces equal the
packaged file. It never writes a file: the packaged vectors stay the bundle's bytes, and a
difference is a finding to report, not something this script repairs.

The reference is open-dis-python (https://github.com/open-dis/open-dis-python, BSD-2-Clause) at
commit 732b6655bb47e34ccc73722eefe0f4706fd0032f. It is a development reference: never a runtime
dependency of the package, never imported by it, and nothing in this repository is copied from it.
The checkout is put on `sys.path` only inside `load_opendis`, which only this script and the
reference tests' child process call.

Run it from the directory this file is in:

    python build_fixtures.py <open-dis-python checkout>

The script reads the checkout's commit from its `.git` directory and refuses any other commit. A
clean checkout (no local modification) is the caller's obligation; the reference tests verify it.
Exit status 0 when every PDU equals its packaged file, 1 when one differs, 2 for a wrong commit.
"""
from __future__ import annotations

import argparse
import importlib
import io
import pathlib
import sys

REFERENCE_URL = "https://github.com/open-dis/open-dis-python"
REFERENCE_COMMIT = "732b6655bb47e34ccc73722eefe0f4706fd0032f"

HERE = pathlib.Path(__file__).resolve().parent
VECTORS = HERE.parent / "vectors"

#: The scenario of each packaged PDU, in the order of the vectors' index. Every value is a literal
#: written here, never read from the codec.
SCENARIOS = {
    "equator_eastbound": {
        "exercise_id": 42,
        "timestamp": 0x40000001,
        "status": 0,
        "entity_id": [7, 11, 1],
        "force_id": 1,
        "entity_kind": 1,
        "domain": 1,
        "country": 0,
        "category": 0,
        "position": [6378257.0, 0.0, 0.0],
        "velocity": [0.0, 25.0, 0.0],
        "orientation": [0.5, -0.25, 0.125],
        "appearance": 0x12345678,
        "dead_reckoning_algorithm": 2,
        "marking_character_set": 1,
        "marking": "EXERCISE-01",
        "capabilities": 0xAABBCCDD,
        "records": [],
    },
    "north_pole_stationary": {
        "exercise_id": 42,
        "timestamp": 0x40000001,
        "status": 0,
        "entity_id": [7, 11, 2],
        "force_id": 2,
        "entity_kind": 1,
        "domain": 1,
        "country": 0,
        "category": 0,
        "position": [0.0, 0.0, 6356792.314245179],
        "velocity": [0.0, -0.0, 0.0],
        "orientation": [0.5, -0.25, 0.125],
        "appearance": 0x12345678,
        "dead_reckoning_algorithm": 2,
        "marking_character_set": 1,
        "marking": "EXERCISE-01",
        "capabilities": 0xAABBCCDD,
        "records": [],
    },
    "unprojectable_with_extensions": {
        "exercise_id": 42,
        "timestamp": 0x40000001,
        "status": 0,
        "entity_id": [7, 11, 3],
        "force_id": 9,
        "entity_kind": 0,
        "domain": 1,
        "country": 0,
        "category": 0,
        "position": [0.0, 0.0, 0.0],
        "velocity": [1.0, 2.0, 3.0],
        "orientation": [0.5, -0.25, 0.125],
        "appearance": 0x12345678,
        "dead_reckoning_algorithm": 9,
        "marking_character_set": 1,
        "marking": "EXERCISE-01",
        "capabilities": 0xAABBCCDD,
        "records": [[255, 1.25, 0x12345678, 0xABCD, 0xEF]],
    },
}


def load_opendis(directory):
    """The checkout's `opendis.dis7` and `opendis.stream` modules, imported from `directory`."""
    sys.path.insert(0, str(pathlib.Path(directory).resolve()))
    return importlib.import_module("opendis.dis7"), importlib.import_module("opendis.stream")


def build_pdu(dis7, stream, scenario) -> bytes:
    """One Entity State PDU serialised by OpenDIS from `scenario`, on a fresh PDU instance.

    OpenDIS never computes the length field: key `length` absent sets `144 + 16 * records`, an
    integer sets that integer, and `None` leaves the library's default. A key `pdu_type` sets the
    header's PDU type octet.
    """
    records = scenario["records"]
    pdu = dis7.EntityStatePdu()
    pdu.exerciseID = scenario["exercise_id"]
    pdu.timestamp = scenario["timestamp"]
    pdu.pduStatus = scenario["status"]
    if "pdu_type" in scenario:
        pdu.pduType = scenario["pdu_type"]
    if "length" not in scenario:
        pdu.length = 144 + 16 * len(records)
    elif scenario["length"] is not None:
        pdu.length = scenario["length"]
    site, application, entity = scenario["entity_id"]
    pdu.entityID.simulationAddress.site = site
    pdu.entityID.simulationAddress.application = application
    pdu.entityID.entityNumber = entity
    pdu.forceId = scenario["force_id"]
    pdu.entityType = dis7.EntityType(entityKind=scenario["entity_kind"], domain=scenario["domain"],
                                     country=scenario["country"], category=scenario["category"])
    pdu.entityLocation = dis7.WorldCoordinates(*scenario["position"])
    pdu.entityLinearVelocity = dis7.Vector3Float(*scenario["velocity"])
    pdu.entityOrientation = dis7.EulerAngles(*scenario["orientation"])
    pdu.entityAppearance = scenario["appearance"]
    pdu.deadReckoningParameters.deadReckoningAlgorithm = scenario["dead_reckoning_algorithm"]
    pdu.marking = dis7.EntityMarking(characterSet=scenario["marking_character_set"],
                                     characters=list(scenario["marking"].encode("ascii")))
    pdu.capabilities = scenario["capabilities"]
    pdu.variableParameters = [
        dis7.VariableParameter(recordType=kind, variableParameterFields1=fields1,
                               variableParameterFields2=fields2,
                               variableParameterFields3=fields3,
                               variableParameterFields4=fields4)
        for kind, fields1, fields2, fields3, fields4 in records]
    buffer = io.BytesIO()
    pdu.serialize(stream.DataOutputStream(buffer))
    return buffer.getvalue()


def _checkout_commit(checkout: pathlib.Path) -> str:
    """The commit `.git/HEAD` names, following one `ref: ` indirection; read as text, no git."""
    head = (checkout / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        head = (checkout / ".git" / head[len("ref: "):]).read_text(encoding="utf-8").strip()
    return head


def _sha256(path: pathlib.Path) -> str:
    """Through `evidence.digest`, the package's one content-digest site: no fixture generator
    imports a digest module of its own."""
    sys.path.insert(0, str(HERE.parents[3]))
    from synapse_cdm.evidence import digest
    return digest(path)[0]


def main(argv=None) -> int:
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("checkout", type=pathlib.Path,
                        help="the open-dis-python checkout at the pinned commit")
    args = parser.parse_args(argv)
    try:
        commit = _checkout_commit(args.checkout)
    except OSError as e:
        print(f"build_fixtures: cannot read the commit of {args.checkout}: {e}", file=sys.stderr)
        return 2
    if commit != REFERENCE_COMMIT:
        print(f"build_fixtures: {args.checkout} is at {commit!r}, not {REFERENCE_COMMIT}",
              file=sys.stderr)
        return 2
    dis7, stream = load_opendis(args.checkout)
    differ = 0
    for stem, scenario in SCENARIOS.items():
        path = VECTORS / f"{stem}.dis"
        built = build_pdu(dis7, stream, scenario)
        equal = built == path.read_bytes()
        differ += not equal
        print(f"{stem}.dis: {len(built)} bytes, sha256 {_sha256(path)}: "
              f"{'equal' if equal else 'DIFFERENT'}")
    if differ:
        print(f"{len(SCENARIOS)} vectors regenerated through open-dis-python {REFERENCE_COMMIT}: "
              f"{differ} differ")
        return 1
    print(f"{len(SCENARIOS)} vectors regenerated through open-dis-python {REFERENCE_COMMIT}: "
          "all equal the packaged files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
