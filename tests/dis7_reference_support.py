"""The pinned open-dis-python checkout for the DIS 7 reference tests, or a BLOCKED skip.

Not a test module: no `test_` function lives here. `tests/test_cdm_dis7_reference.py` (acceptance
case A13) compares OpenDIS's own serialisation and parse with the codec and the `dis7` adapter.
OpenDIS is a development reference held OUTSIDE the repository, named by the hook
`SYNAPSE_CDM_OPENDIS_DIR` (https://github.com/open-dis/open-dis-python, BSD-2-Clause, at the
commit in `PIN`). It is never a runtime dependency and never enters the test process: every
OpenDIS call happens in a child interpreter that loads the checkout through the generator's own
`load_opendis`, and answers in JSON.

A test that asks for the checkout through `checkout()` either gets a directory verified at the
pin with a clean tree, or is skipped with the repository's reason format,
`BLOCKED_EXTERNAL_EVIDENCE at step '<step>': <reason>` — never passed.

Run as a module, it writes the specification of an `independent_expected` exercise and the files
it names, for `python -m synapse_cdm.evidence exercise`:

    SYNAPSE_CDM_OPENDIS_DIR=<checkout> python -m tests.dis7_reference_support --exercise-out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import sysconfig
import tomllib
import types

import pytest

import synapse_cdm
from synapse_cdm import canonical
from tests import dis7_support, normative_support

ENV_VAR = "SYNAPSE_CDM_OPENDIS_DIR"
PIN = "732b6655bb47e34ccc73722eefe0f4706fd0032f"
GENERATOR = dis7_support.FIXTURES / "spec" / "build_fixtures.py"


def child_env() -> dict[str, str]:
    """The environment of every Python child: the package the parent imported, no bytecode."""
    return {**os.environ,
            "PYTHONPATH": str(pathlib.Path(synapse_cdm.__file__).resolve().parents[1]),
            "PYTHONDONTWRITEBYTECODE": "1"}


class Blocked(Exception):
    """The checkout cannot be used: `step` is a member of `normative_binding.STEPS`."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason


def _git(directory: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True,
                          timeout=60)


def resolve(environ=None) -> pathlib.Path:
    """The checkout, verified at `PIN` with a clean tree, or `Blocked` at the first failing step."""
    env = os.environ if environ is None else environ
    where = (env.get(ENV_VAR) or "").strip()
    if not where:
        raise Blocked("hook", f"{ENV_VAR} is not set")
    directory = pathlib.Path(where)
    if not directory.is_dir():
        raise Blocked("directory", f"{ENV_VAR}={where!r} is not a directory")
    if not (directory / "opendis" / "dis7.py").is_file():
        raise Blocked("directory", f"{ENV_VAR}={where!r} holds no opendis/dis7.py")
    if not (directory / ".git").exists():
        raise Blocked("record", f"{ENV_VAR}={where!r} is not a git checkout (no .git)")
    try:
        head = _git(directory, "rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError) as e:
        raise Blocked("record", f"git rev-parse HEAD cannot run: {e}") from e
    if head.returncode != 0:
        raise Blocked("record", f"git rev-parse HEAD exited {head.returncode}: "
                                f"{head.stderr.strip()}")
    commit = head.stdout.strip()
    if commit != PIN:
        raise Blocked("checksum", f"the checkout is at {commit}, not the pinned {PIN}")
    try:
        status = _git(directory, "status", "--porcelain")
    except (OSError, subprocess.SubprocessError) as e:
        raise Blocked("record", f"git status cannot run: {e}") from e
    if status.returncode != 0 or status.stdout.strip():
        raise Blocked("checksum", "the checkout is not clean: git status --porcelain printed "
                                  f"{(status.stdout or status.stderr).strip()!r}")
    return directory.resolve()


def checkout() -> pathlib.Path:
    """The verified checkout, or a `BLOCKED_EXTERNAL_EVIDENCE` skip naming the failing step."""
    try:
        return resolve()
    except Blocked as e:
        pytest.skip(normative_support.blocked_reason(e.step, e.reason))


def generator() -> types.ModuleType:
    """`spec/build_fixtures.py` compiled IN MEMORY, never through the caching source loader."""
    module = types.ModuleType("dis7_build_fixtures")
    module.__file__ = str(GENERATOR)
    exec(compile(GENERATOR.read_text(), str(GENERATOR), "exec"), module.__dict__)
    return module


#: The child interpreter's program: argv is [checkout, generator]; requests on stdin, answers on
#: stdout, both JSON, octets as hex. A fresh PDU instance per parse, since a parsed instance
#: accumulates variable parameter records.
_CHILD = r'''
import io
import json
import struct
import sys
import types

path = sys.argv[2]
module = types.ModuleType("dis7_build_fixtures")
module.__file__ = path
with open(path, encoding="utf-8") as handle:
    exec(compile(handle.read(), path, "exec"), module.__dict__)
try:
    dis7, stream = module.load_opendis(sys.argv[1])
except ImportError as e:
    sys.stderr.write(f"IMPORT: {e}\n")
    sys.exit(3)


def vector(v):
    return [v.x, v.y, v.z]


def entity_type(t):
    return [t.entityKind, t.domain, t.country, t.category, t.subcategory, t.specific, t.extra]


def fields(pdu):
    dr = pdu.deadReckoningParameters
    return {
        "header": {
            "protocol_version": pdu.protocolVersion, "exercise_id": pdu.exerciseID,
            "pdu_type": pdu.pduType, "protocol_family": pdu.protocolFamily,
            "timestamp": pdu.timestamp, "length": pdu.length, "status": pdu.pduStatus,
            "padding": pdu.padding,
        },
        "entity_id": [pdu.entityID.simulationAddress.site,
                      pdu.entityID.simulationAddress.application, pdu.entityID.entityNumber],
        "force_id": pdu.forceId,
        "entity_type": entity_type(pdu.entityType),
        "alternative_entity_type": entity_type(pdu.alternativeEntityType),
        "velocity_mps": vector(pdu.entityLinearVelocity),
        "position_ecef_m": vector(pdu.entityLocation),
        "orientation_radians": [pdu.entityOrientation.psi, pdu.entityOrientation.theta,
                                pdu.entityOrientation.phi],
        "appearance": pdu.entityAppearance,
        "dead_reckoning_hex": struct.pack(
            ">B15B3f3f", dr.deadReckoningAlgorithm, *dr.parameters,
            *vector(dr.entityLinearAcceleration), *vector(dr.entityAngularVelocity)).hex(),
        "marking_hex": bytes([pdu.marking.characterSet]
                             + [c & 0xFF for c in pdu.marking.characters]).hex(),
        "capabilities": pdu.capabilities,
        "variable_parameters_hex": [
            struct.pack(">BdIHB", r.recordType, r.variableParameterFields1,
                        r.variableParameterFields2, r.variableParameterFields3,
                        r.variableParameterFields4).hex()
            for r in pdu.variableParameters],
    }


answers = []
for request in json.loads(sys.stdin.read()):
    if request["op"] == "build":
        answers.append({"hex": module.build_pdu(dis7, stream, request["scenario"]).hex()})
    elif request["op"] == "parse":
        pdu = dis7.EntityStatePdu()
        pdu.parse(stream.DataInputStream(io.BytesIO(bytes.fromhex(request["hex"]))))
        again = io.BytesIO()
        pdu.serialize(stream.DataOutputStream(again))
        answers.append({"fields": fields(pdu), "reserialised_hex": again.getvalue().hex()})
    else:
        raise ValueError(f"unknown op {request['op']!r}")
sys.stdout.write(json.dumps(answers))
'''


def run_opendis(directory, requests: list[dict]) -> list[dict]:
    """Answer `requests` in one child interpreter that has OpenDIS loaded; this process never
    imports it. An `ImportError` in the child is a BLOCKED skip at step `validator`."""
    done = subprocess.run(
        [sys.executable, "-B", "-c", _CHILD, str(directory), str(GENERATOR)],
        input=json.dumps(requests), capture_output=True, text=True, env=child_env(), timeout=120)
    lines = done.stderr.strip().splitlines()
    last = lines[-1] if lines else ""
    if done.returncode == 3 and last.startswith("IMPORT: "):
        pytest.skip(normative_support.blocked_reason("validator", last[len("IMPORT: "):]))
    if done.returncode != 0:
        raise AssertionError(f"the OpenDIS child exited {done.returncode}: {last}")
    answers = json.loads(done.stdout)
    assert len(answers) == len(requests), (len(answers), len(requests))
    return answers


def build(directory, scenario: dict) -> bytes:
    """The PDU OpenDIS serialises for `scenario`, through the generator's `build_pdu`."""
    return bytes.fromhex(run_opendis(directory, [{"op": "build", "scenario": scenario}])[0]["hex"])


def parse(directory, raw: bytes) -> dict:
    """OpenDIS's parse of `raw`: `fields` in `decode_pdu`'s shape, and `reserialised_hex`."""
    return run_opendis(directory, [{"op": "parse", "hex": raw.hex()}])[0]


def tool_versions(directory) -> dict[str, str]:
    """The interpreter, platform tag, git and OpenDIS version of a reading."""
    project = tomllib.loads((pathlib.Path(directory) / "pyproject.toml").read_text())
    version = (project.get("project", {}).get("version")
               or project.get("tool", {}).get("poetry", {}).get("version"))
    git = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=60)
    return {
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "platform": sysconfig.get_platform(),
        "git": git.stdout.strip(),
        "opendis": f"{version}@{PIN}",
    }


def write_exercise(directory, out) -> pathlib.Path:
    """Write the inputs, expected and observed files and the exercise specification under `out`
    (created when absent); return the specification's path, `out/opendis.json`."""
    from synapse_cdm.adapters.dis7 import Dis7Adapter
    from synapse_cdm.adapters.dis7_codec import decode_pdu

    out = pathlib.Path(out)
    for where in (out, out / "inputs", out / "expected", out / "observed"):
        where.mkdir(parents=True, exist_ok=True)
    adapter = Dis7Adapter.fixture_instance()
    scenarios = generator().SCENARIOS
    stems = list(dis7_support.STEMS)
    packaged = {stem: dis7_support.vector_bytes(stem) for stem in stems}
    answers = run_opendis(directory, [{"op": "build", "scenario": scenarios[stem]} for stem in stems]
                          + [{"op": "parse", "hex": packaged[stem].hex()} for stem in stems])
    built, parsed = answers[:len(stems)], answers[len(stems):]
    inputs, results = [], []
    for stem, made, read in zip(stems, built, parsed):
        raw = packaged[stem]
        (out / "inputs" / f"{stem}.dis").write_bytes(raw)
        (out / "expected" / f"{stem}.dis").write_bytes(bytes.fromhex(made["hex"]))
        (out / "observed" / f"{stem}.dis").write_bytes(adapter.from_cdm(adapter.to_cdm(raw)))
        (out / "expected" / f"{stem}.pdu.json").write_text(canonical.serialise(read["fields"]))
        (out / "observed" / f"{stem}.pdu.json").write_text(canonical.serialise(decode_pdu(raw)))
        inputs.append({
            "path": f"inputs/{stem}.dis",
            "provenance": "synthetic vector of the handoff bundle SC DIS7 SPEC 001 v1.0, packaged "
                          "byte-identical under fixtures/dis7/vectors",
            "authorised_by": "the repository's own fixture provenance record",
        })
        results.append({
            "direction": "ingress",
            "command": "OpenDIS EntityStatePdu.parse against decode_pdu",
            "expected": f"expected/{stem}.pdu.json", "observed": f"observed/{stem}.pdu.json",
            "note": stem,
        })
        results.append({
            "direction": "egress",
            "command": "OpenDIS EntityStatePdu.serialize against Dis7Adapter.from_cdm(to_cdm(input))",
            "expected": f"expected/{stem}.dis", "observed": f"observed/{stem}.dis",
            "note": stem,
        })
    versions = tool_versions(directory)
    spec = {
        "category": "independent_expected",
        "peer": {"implementation": "open-dis-python", "version": versions["opendis"]},
        "edition": "DIS 7 / IEEE 1278.1-2012 Entity State subset",
        "profile": "Entity State PDU (type 1, family 1)",
        "inputs": inputs,
        "directions": ["ingress", "egress"],
        "results": results,
        "limitations": [
            "three synthetic Entity State PDUs; no other PDU type, no network exchange, no live "
            "simulator",
            "open-dis-python at the pinned commit is the layout authority; the IEEE text was not "
            "consulted and no IEEE certification is claimed",
            "the ingress comparison is of decoded wire fields; OpenDIS performs no geodetic "
            "projection",
        ],
        "environment": {**versions, "hook": ENV_VAR},
    }
    path = out / "opendis.json"
    path.write_text(canonical.serialise(spec))
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exercise-out", required=True, type=pathlib.Path,
                        help="the directory the specification and its files are written to")
    args = parser.parse_args(argv)
    try:
        directory = resolve()
    except Blocked as e:
        print(normative_support.blocked_reason(e.step, e.reason), file=sys.stderr)
        return 1
    print(write_exercise(directory, args.exercise_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
