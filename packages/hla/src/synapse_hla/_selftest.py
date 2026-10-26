"""`synapse-hla self-test`: the packaged fixture runner of OPS-26 (round R6), without pytest.

WHAT IT RUNS
------------
Every case compares what the product gives with what a packaged fixture of the handoff expects,
never with an earlier output of the product (SPEC:259):
- `V-<id>`: the 14 positive attribute vectors through `decode_attribute`, the decoded value
  against the fixture's, and `N-<id>`: the 30 negative vectors, the refusal's code against the
  fixture's (`attributes-positive.json`, `attributes-negative.json`);
- `GEO-<id>`: the six points of `geodesy.json` through section 9's projection, the emitted
  latitude, longitude and height against the fixture's, or the gate's code;
- `IDENTITY`: `identity.json`'s external_id taken apart and written again, its UUIDv5 and the
  namespace;
- `CONFIG-<file>`: both example configurations through the strict loader and `validate_config`;
- `SCHEMA-<file>`: every packaged schema (the bundle's thirteen and the product's own) is a valid
  Draft 2020-12 schema;
- `FIXTURE-<file>`: every packaged fixture has the size and SHA-256 its provenance record states;
- `PINS-FOM`: the five FOM modules of the directory the caller names (the command line reads
  `SYNAPSE_HLA_FOM_DIR`) against the packaged pins, then the XML scan; BLOCKED when no directory
  is named (OPS-11 as corrected, R46);
- `REPLAY-session.capture.jsonl` and `FIRST-UPSERT`: the packaged capture verified and replayed
  into `fixture-replay/` (the replay command's directory, `run.json` included), its observations
  against `expected.observations.jsonl` byte for byte, and its first upsert against
  `first-upsert.entity.json`.

Values are compared exactly: both sides are written as canonical JSON with floats in their
shortest form, so 1 and 1.0, true and 1, and 0.0 and -0.0 all differ (sorted keys make member order
irrelevant, as it is in JSON). Each case records the SHA-256 of its input bytes, the expected and
the actual value. A case that cannot even be compared (the product raised something that is not
an `HlaError`) is a defect, not a FAIL: it propagates.

The report is held to `local_schemas/self-test.schema.json`. Its global result is PASS only when
every case passed, FAIL when one failed, and BLOCKED when none failed but one could not run: a
global PASS never hides either (D-14).
"""

from __future__ import annotations

import hashlib
import importlib.resources
import os

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from synapse_hla import (
    _examples, _fom, _identity, _resources, _runfile, _schema, canonical, capture, config,
    geodesy,
)
from synapse_hla.codec import decode_attribute
from synapse_hla.errors import HlaError
from synapse_hla.replay import OBSERVATIONS, replay_with

SCHEMA = "self-test.schema.json"
VERSION = 1
FIXTURE_REPLAY = "fixture-replay"
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

_FIXTURES = "fixtures"
_CAPTURE = "session.capture.jsonl"
_EXPECTED = "expected.observations.jsonl"
_VALID = "VALID"
_NO_DIRECTORY = "SYNAPSE_HLA_FOM_DIR is not set, so the FOM modules could not be checked"


class SelfTestDefect(RuntimeError):
    """The report this module built fails its own schema: a defect here."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _same(expected, actual) -> bool:
    """Exact equality of two JSON values: their canonical spellings, floats included."""
    try:
        return canonical.canonical_bytes(expected, floats=True) == \
            canonical.canonical_bytes(actual, floats=True)
    except canonical.StrictJsonError:
        return False


def _case(identifier: str, group: str, input_bytes: bytes | None, expected, actual,
          *, result: str | None = None, reason: str | None = None) -> dict:
    if result is None:
        result = PASS if _same(expected, actual) else FAIL
    return {"id": identifier, "group": group, "result": result,
            "input_sha256": None if input_bytes is None else _sha256(input_bytes),
            "expected": expected, "actual": actual, "reason": reason}


def _refusal(error: HlaError) -> dict:
    return {"code": error.code, "path": error.path}


def _fixture(name: str):
    return _resources.package_json(_FIXTURES, name)


def _vectors() -> list[dict]:
    cases = []
    for entry in _fixture("attributes-positive.json"):
        raw = bytes.fromhex(entry["hex"])
        try:
            decoded = decode_attribute(entry["name"], raw)
            actual = decoded["value"] if decoded["name"] == entry["name"] else decoded
        except HlaError as error:
            actual = _refusal(error)
        cases.append(_case(f"V-{entry['id']}", "vector", raw, entry["expected"], actual))
    for entry in _fixture("attributes-negative.json"):
        raw = bytes.fromhex(entry["hex"])
        try:
            actual = {"value": decode_attribute(entry["name"], raw)["value"]}
        except HlaError as error:
            actual = {"code": error.code}
        cases.append(_case(f"N-{entry['id']}", "vector", raw, {"code": entry["code"]}, actual))
    return cases


def _geodesy() -> list[dict]:
    cases = []
    for entry in _fixture("geodesy.json"):
        point = entry["ecef_m"]
        if "error" in entry:
            expected = {"code": entry["error"]}
        else:
            expected = entry["expected"]
        try:
            projection = geodesy.project_spatial({"algorithm": 1, "position_ecef_m": point,
                                                  "velocity_mps": None})
            position = projection.position
            actual = [position["lat"], position["lon"], position["alt_m"]]
        except HlaError as error:
            actual = {"code": error.code}
        cases.append(_case(f"GEO-{entry['id']}", "geodesy",
                           canonical.canonical_bytes(point, floats=True), expected, actual))
    return cases


def _identity_case() -> dict:
    data = _resources.package_bytes(_FIXTURES, "identity.json")
    fixture = _fixture("identity.json")
    session_id, generation, site, application, entity, incarnation = \
        _identity.parts(fixture["external_id"])
    external = _identity.external_id(session_id, generation, {
        "site": site, "application": application, "entity": entity}, incarnation)
    actual = {"external_id": external, "entity_id": _identity.entity_id(external),
              "uuid_namespace": str(_identity.NAMESPACE)}
    return _case("IDENTITY", "identity", data, fixture, actual)


def _configs() -> list[dict]:
    cases = []
    for name, data in _examples.EXAMPLES:
        try:
            config.load_config_bytes(data)
            actual = _VALID
        except HlaError as error:
            actual = _refusal(error)
        cases.append(_case(f"CONFIG-{name}", "config", data, _VALID, actual))
    return cases


def _schemas() -> list[dict]:
    cases = []
    for directory in (_resources.SCHEMA_DIR, _resources.LOCAL_SCHEMA_DIR):
        for name in _resources.schema_names(directory):
            data = _resources.package_bytes(directory, name)
            try:
                Draft202012Validator.check_schema(_resources.package_json(directory, name))
                actual = _VALID
            except SchemaError:
                actual = "INVALID"
            cases.append(_case(f"SCHEMA-{name}", "schema", data, _VALID, actual))
    return cases


def _fixture_digests() -> list[dict]:
    cases = []
    for entry in _fixture("PROVENANCE.json")["fixtures"]:
        data = _resources.package_bytes(_FIXTURES, entry["file"])
        cases.append(_case(f"FIXTURE-{entry['file']}", "fixture", data,
                           {"bytes": entry["bytes"], "sha256": entry["sha256"]},
                           {"bytes": len(data), "sha256": _sha256(data)}))
    return cases


def _pins(fom_dir: str | None) -> tuple[dict, HlaError | None]:
    pinned = {pin.path: pin.sha256 for pin in _fom.packaged_pins()}
    expected = {name: pinned[name] for name in _fom.FOM_MODULES}
    if not fom_dir:
        return _case("PINS-FOM", "pins", None, expected, None, result=BLOCKED,
                     reason=_NO_DIRECTORY), None
    try:
        modules = _fom.check_fom_modules(fom_dir)
    except HlaError as error:
        return _case("PINS-FOM", "pins", None, expected, _refusal(error)), error
    return _case("PINS-FOM", "pins", None, expected,
                 {module.name: module.sha256 for module in modules}), None


def _replay(target: bytes, synapse_cdm_version: str | None, check) -> list[dict]:
    package = importlib.resources.files("synapse_hla")
    capture_bytes = _resources.package_bytes(_FIXTURES, _CAPTURE)
    expected_bytes = _resources.package_bytes(_FIXTURES, _EXPECTED)
    expected = {"status": capture.COMPLETE, "observations_sha256": _sha256(expected_bytes)}
    first_upsert = _fixture("first-upsert.entity.json")
    with importlib.resources.as_file(package.joinpath(_FIXTURES, _CAPTURE)) as path:
        try:
            summary = replay_with(
                path, target, manifest=lambda summary, header: _runfile.replay_run(
                    summary, header, synapse_cdm_version=synapse_cdm_version), check=check)
        except HlaError as error:
            failed = _refusal(error)
            return [_case(f"REPLAY-{_CAPTURE}", "replay", capture_bytes, expected, failed),
                    _case("FIRST-UPSERT", "replay", capture_bytes, first_upsert, failed)]
    observations_path = os.path.join(target, OBSERVATIONS.encode("ascii"))
    with open(observations_path, "rb") as stream:
        produced = stream.read()
    actual = {"status": summary["status"], "observations_sha256": _sha256(produced)}
    upserts = [record for record in (canonical.strict_loads(line, floats=True,
                                                            surrogates=False)
                                     for line in produced.splitlines())
               if record["kind"] == "upsert"]
    upsert = upserts[0]["payload"] if upserts else None
    return [_case(f"REPLAY-{_CAPTURE}", "replay", capture_bytes, expected, actual),
            _case("FIRST-UPSERT", "replay", capture_bytes, first_upsert, upsert)]


def run(target: bytes, fom_dir: str | None, *, synapse_cdm_version: str | None,
        check=None) -> tuple[dict, HlaError | None]:
    """Run every case; `target` is the directory to replay the packaged capture into (it must
    not exist yet). Returns the report and, when the pin check refused the FOM modules, its
    `HlaError` (for the command line's stderr and exit class). `check()` is called between the
    groups of cases and before each line of the replay; whatever it raises ends the run."""
    check = (lambda: None) if check is None else check
    cases = []
    for group in (_vectors, _geodesy, lambda: [_identity_case()], _configs, _schemas,
                  _fixture_digests):
        check()
        cases.extend(group())
    check()
    pins_case, pins_error = _pins(fom_dir)
    cases.append(pins_case)
    check()
    cases.extend(_replay(target, synapse_cdm_version, check))
    counts = {result: sum(1 for case in cases if case["result"] == result)
              for result in (PASS, FAIL, BLOCKED)}
    if counts[FAIL]:
        overall = FAIL
    elif counts[BLOCKED]:
        overall = BLOCKED
    else:
        overall = PASS
    report = {"self_test_version": VERSION, "profile": capture.PROFILE,
              "adapter_version": capture.ADAPTER_VERSION, "result": overall, "counts": counts,
              "cases": cases, "fixture_replay": FIXTURE_REPLAY}
    error = next(iter(_schema.checked_validator(SCHEMA).iter_errors(report)), None)
    if error is not None:
        raise SelfTestDefect(f"self-test.json fails {SCHEMA} ({error.validator})")
    return report, pins_error
