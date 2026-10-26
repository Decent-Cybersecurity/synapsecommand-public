"""Round R8: the synthetic publisher, the orchestration of `synapse-hla demo` and its report.

WHAT IS HELD HERE
-----------------
Offline (no marker): what the sources and the pure parts of `_demo` can show without an RTI - the
publisher's fixed bytes against the packaged vectors (R39: fixed bytes, never an encoder), its
order of steps (R38), its module handling (NAT-19) and classes (NAT-01), the constructs R40 bars;
the scenario tables, the run configurations of OPS-13, the federation names of OPV-05, the
expected values the demo takes from the packaged vectors, the semantic checkpoints judged on the
bundled capture with one hand-made fault per row (each row names exactly the checkpoints that
must fail), the demo report's schema with a row per rule, and CR-L16's publisher pre-flight
against stand-in scripts.

`rti` group: the demo itself through the command line, twice, from a directory outside any
checkout (A-DEMO; exit criterion 3 of the round): exit 0, `demo.json` held to its schema and read
line by line against the run directories, every checkpoint PASS, both replays equal to the live
outputs but for SPEC:158's completion fields, every process gone by its PID, the port closed,
nothing written outside --out, every socket on 127.0.0.1. The rtinode start rules of R38 and
NAT-18 against a real rtinode on a busy port. A-NO-PUBLISH and A-NO-CREATE with the recording
decorator around the observer during the demo's real sessions.

EVIDENCE CLASS
--------------
Every run here is development evidence on this machine (DEV-macOS-arm64 on the development Mac,
CR-L04) against the OpenRTI development build of NAT-02; nothing claims more.

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
The packaged fixtures (identity.json, session-checkpoints.json, attributes-positive.json, the
bundled capture and its expected observations) and literals derived by hand in the comments;
never from the code under test.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import shlex
import socket
import subprocess
import sys
import time

import pytest

from hla_support import (
    PACKAGE_ROOT, TESTS_DIR, CaptureBuilder, case, encode_spatial, event_discover,
    event_generation_end, event_generation_start, event_reflect, example_json, fixed_tool,
    fixture_capture_records, fixture_json, fom_modules, local_validator, native_executable,
    package_bytes, packaged_pins, positive_hex, process_gone, strict_json, without_completion,
)
from synapse_hla import _demo, _fom, replay, verify_capture
from test_hla_cli import SRC, command_line, environment, finish, run_cli, start, tree
from test_hla_native_sources import FORBIDDEN_CONSTRUCTS, code_of

PUBLISHER_SOURCE = PACKAGE_ROOT / "tools" / "publisher" / "publisher.cpp"
DEMO_SCHEMA = local_validator("demo.schema.json")
PE = "HLAobjectRoot.BaseEntity.PhysicalEntity"
GV = "HLAobjectRoot.BaseEntity.PhysicalEntity.Platform.GroundVehicle"
#: identity.json: the entity id of the main run's object (session example-001, generation 1,
#: site 1, application 2, entity 3, incarnation 1; OPS-13).
ENTITY_ID = "781e68de-166f-531c-b906-4a2d087f817e"
#: The bundled capture's two Spatial values (seq 5 and 6): DRM_FPW (02), seven padding bytes, x
#: = 6378137.0 (0x415854A640000000) and 6378147.0 (0x415854A8C0000000), y = z = 0, frozen 0,
#: three padding bytes, psi = theta = phi = 0, velocity (0, 10.0 = 0x41200000, 0).
SPATIAL_EQUATOR = ("0200000000000000415854a64000000000000000000000000000000000000000"
                   "00000000000000000000000000000000000000004120000000000000")
SPATIAL_SECOND = ("0200000000000000415854a8c000000000000000000000000000000000000000"
                  "00000000000000000000000000000000000000004120000000000000")
#: The checkpoint ids of each run, in the order demo.json lists them (OPS-13; `reported_class` is
#: A-CLASS, CR-new-R8).
MAIN_CHECKPOINTS = ["capture_verified", "steps_in_order", "reported_class", "one_entity_id",
                    "identifier", "platform", "affiliation", "position_equator",
                    "position_second", "course_east", "revisions", "valid_from_nondecreasing",
                    "no_diagnostics", "removed_notice", "replay_identical"]
NO_TIME_CHECKPOINTS = ["capture_verified", "steps_in_order", "reported_class", "one_entity_id",
                       "identifier", "snapshots_present", "no_entity", "time_unresolved",
                       "removed_notice", "replay_identical"]


# ========================================================================= the publisher's source

def literal(source: str, name: str) -> str:
    """The value of `const char NAME[] = "..." "...";` in a C++ source, its pieces joined."""
    match = re.search(r"const char " + name + r"\[\] =\s*((?:\"[^\"]*\"\s*)+);", source)
    assert match is not None, name
    return "".join(re.findall(r"\"([^\"]*)\"", match.group(1)))


@case("G-R39", "G-R38", paragraphs=("SPEC:211", "SPEC:207"))
def test_the_publisher_sends_the_packaged_vectors_byte_for_byte():
    """R39 "the publisher uses fixed bytes, not the production encoder or decoder" and R38's
    order: the five byte literals of the publisher are the packaged vectors V-ID-123,
    V-TYPE-PLATFORM, V-FORCE-1 and the bundled capture's Spatial values at seq 5 and 6 (the first
    of which is V-SPATIAL-2); the main scenario sends them in R38's order, each step with its own
    tag, then the removal; and nothing in the publisher encodes a number (no float or double, no
    RTI encoding helper)."""
    source = PUBLISHER_SOURCE.read_text(encoding="utf-8")
    vectors = positive_hex()
    frames = {r["seq"]: r for r in fixture_capture_records()[1:] if r["type"] == "frame"}
    spatial = {seq: [a["hex"] for a in frames[seq]["event"]["attributes"]][0] for seq in (5, 6)}
    assert literal(source, "kEntityIdentifier") == vectors["ID-123"] == "000100020003"
    assert literal(source, "kEntityType") == vectors["TYPE-PLATFORM"] == "010100e101020304"
    assert literal(source, "kForceIdentifier") == vectors["FORCE-1"] == "01"
    assert literal(source, "kSpatialEquator") == spatial[5] == vectors["SPATIAL-2"] \
        == SPATIAL_EQUATOR
    assert literal(source, "kSpatialSecond") == spatial[6] == SPATIAL_SECOND
    body = source[source.index("bool main_scenario() {"):source.index("static std::string")]
    steps = re.findall(r'(update|remove)\(0, (?:\{(.*?)\}\}, )?"(step-\d)"\)', body, re.S)
    assert [(kind, re.findall(r"k[A-Z][A-Za-z]+\)", values), tag) for kind, values, tag in steps] \
        == [("update", ["kEntityIdentifier)", "kEntityType)"], "step-1"),
            ("update", ["kForceIdentifier)"], "step-2"),
            ("update", ["kSpatialEquator)"], "step-3"),
            ("update", ["kSpatialSecond)"], "step-4"),
            ("remove", [], "step-5")]
    code = code_of(source)
    assert re.search(r"\b(?:float|double)\b", code) is None
    assert "RTI/encoding" not in source and "HLAfixedRecord" not in code


@case("G-R38", "G-R11", paragraphs=("SPEC:207",))
def test_the_publisher_creates_from_the_hashed_bytes_with_hlafloat64time_on_both_classes():
    """R38 and NAT-19: the five modules in R04's order, each hashed and compared with its pin,
    handed to the RTI as `data:text/plain,` designators built from exactly the bytes that were
    hashed (decoded strictly and checked to re-encode to the same bytes), and the federation
    created with HLAfloat64Time; the digests it reports are those of the bytes it used (R11).
    NAT-01: the four attributes published on PhysicalEntity and on GroundVehicle, objects
    registered at GroundVehicle only, and the class its `ready` event reports read back from the
    RTI rather than written as a literal (the `rti` runs check that report: GroundVehicle, else
    the demo fails). Only a federation this process created is destroyed (R38, SPEC:211). These
    are read off the source; the runs of the `rti` group show the behaviour."""
    source = PUBLISHER_SOURCE.read_text(encoding="utf-8")
    code = code_of(source)
    modules = re.findall(r'"(RPR-[A-Za-z]+_v2\.0\.xml)"', source)
    assert modules == list(_fom.FOM_MODULES)
    assert code.count("createFederationExecution(") == 1
    assert "rti_->createFederationExecution(federation, designators, L\"HLAfloat64Time\")" in \
        source
    assert 'designators->push_back(L"data:text/plain," + text)' in source
    assert "if (digest != arguments_.pins[m]) return fail(\"module_pin\");" in source
    assert "sc_hla::to_utf8(text) != bytes" in source
    assert re.findall(r"publishObjectClassAttributes\((\w+), four\)", code) == \
        ["physical", "ground_vehicle_"]
    assert re.findall(r"registerObjectInstance\((\w+)", code) == ["ground_vehicle_"] * 2
    # R8-r1-F5: the class its `ready` event names is read back from the RTI for every object
    # (getKnownObjectClassHandle) and named by the handle it equals, never written as a literal.
    assert code.count("getKnownObjectClassHandle(") == 2
    assert len(re.findall(r'emit\("\{\\"class\\":" \+ quoted\(registered\) \+', source)) == 2
    assert "quoted(kGroundVehicleName)" not in source
    destroys = [m.start() for m in re.finditer(r"destroyFederationExecution\(", code)]
    assert len(destroys) == 2
    assert "if (created_) {\n      try {\n        rti_->destroyFederationExecution(" in source
    assert "      created_ = true;" in source


@case("G-R02", "G-R39")
def test_the_publisher_uses_none_of_the_constructs_r40_bars():
    """R40 for the publisher as for the worker: no shell or other program, no environment read,
    no format string, no raw byte copies into structures, no casts of bytes to structures; its
    output is written with the worker's write_all, never an iostream."""
    code = code_of(PUBLISHER_SOURCE.read_text(encoding="utf-8"))
    for what, pattern in FORBIDDEN_CONSTRUCTS.items():
        assert re.search(pattern, code) is None, what


# ============================================================================ the pure parts

def test_the_scenarios_are_r38s_order_and_r42s_load_shape():
    """The barrier tables, written out: main waits for the discovery, each step's tag, the
    removal, then the observer's resignation, and stops the observer after the removal; perf
    counts the discoveries, the identity reflections, every load reflection and the removals."""
    main = _demo.main_scenario()
    assert (main.argument, main.stop_after) == ("main", 5)
    assert [(b.number, b.event, b.tag, b.count, b.generation) for b in main.barriers] == [
        (0, "discover", None, 1, None), (1, "reflect", b"step-1", 1, None),
        (2, "reflect", b"step-2", 1, None), (3, "reflect", b"step-3", 1, None),
        (4, "reflect", b"step-4", 1, None), (5, "remove", b"step-5", 1, None),
        (6, "resigned", None, 1, None)]
    perf = _demo.perf_scenario(1000, 1, 20)
    assert (perf.argument, perf.stop_after) == ("perf:1000:1:20", 3)
    assert [(b.number, b.event, b.tag, b.count) for b in perf.barriers] == [
        (0, "discover", None, 1000), (1, "reflect", b"perf-identity", 1000),
        (2, "reflect", b"perf", 20000), (3, "remove", b"perf-remove", 1000),
        (4, "resigned", None, 1)]
    for bad in ((0, 1, 1), (65536, 1, 1), (1, 0, 1), (1, 1001, 1), (1, 1, 0), (1, 1, 86401),
                (True, 1, 1)):
        with pytest.raises(ValueError):
            _demo.perf_scenario(*bad)


@case("G-R38", "G-R39", paragraphs=("SPEC:207", "SPEC:211"))
def test_the_runs_use_config_demo_with_only_the_endpoint_and_federation_replaced():
    """OPS-13: main is examples/config-demo.json with `endpoint` and `federation_name` replaced
    (so session example-001, generation 1 and the fixture's entity id); no-time is the same with
    time policy none and session id example-001-none (R39). Nothing else differs."""
    demo = example_json("config-demo.json")
    main = _demo.run_config("main", 40123, "SC_DEMO_00112233445566ff")
    changed = {k for k in demo if demo[k] != main[k]}
    assert changed == {"endpoint", "federation_name"}
    assert (main["endpoint"], main["federation_name"]) == ("rti://127.0.0.1:40123",
                                                           "SC_DEMO_00112233445566ff")
    none = _demo.run_config("no-time", 40123, "SC_DEMO_00112233445566ff")
    assert {k for k in demo if demo[k] != none[k]} == {"endpoint", "federation_name",
                                                       "time_policy", "session_id"}
    assert (none["time_policy"], none["session_id"]) == ({"mode": "none"}, "example-001-none")
    assert main["time_policy"]["basis"] == \
        "Synthetic 1x scenario clock asserted by fixture author"


@case("G-R38", paragraphs=("SPEC:207",))
def test_each_federation_name_is_sc_demo_and_16_random_lowercase_hex_digits():
    """OPV-05 and R38: SC_DEMO_ plus 16 lowercase hexadecimal digits, 24 characters, new for
    every run (the names of 200 runs are all different)."""
    names = [_demo.new_federation_name() for _ in range(200)]
    assert all(re.fullmatch(r"SC_DEMO_[0-9a-f]{16}", name) for name in names)
    assert len(set(names)) == 200


def test_the_expected_values_are_the_packaged_vectors():
    """What the checkpoints compare with, read from the packaged fixtures by `_demo` and written
    out here again from the files themselves: identity.json's entity and external id, the two
    session checkpoints keyed by the Spatial bytes the bundled capture carries at their seqs, the
    decoded identifier and entity type of V-ID-123 and V-TYPE-PLATFORM, and FRIENDLY for force 1."""
    expected = _demo.expectations()
    identity = fixture_json("identity.json")
    checkpoints = fixture_json("session-checkpoints.json")
    assert expected["entity_id"] == identity["entity_id"] == ENTITY_ID
    assert expected["external_id"] == '["example-001","1","1","2","3","1"]'
    assert expected["by_spatial"] == {SPATIAL_EQUATOR: checkpoints["upserts"][0],
                                      SPATIAL_SECOND: checkpoints["upserts"][1]}
    assert [(u["lat"], u["lon"], u["alt_m"], u["speed_mps"], u["course_deg"], u["climb_mps"])
            for u in expected["by_spatial"].values()] == [(0, 0, 0, 10, 90, 0),
                                                          (0, 0, 10, 10, 90, 0)]
    assert expected["identifier"] == {"site": 1, "application": 2, "entity": 3}
    assert expected["entity_type"] == {"kind": 1, "domain": 1, "country": 225, "category": 1,
                                       "subcategory": 2, "specific": 3, "extra": 4}
    assert expected["affiliation"] == "FRIENDLY"


def test_only_spec_158s_completion_fields_are_normalised():
    """Live and replay records may differ in the envelope's capture_complete and an upsert's
    attributes.hla.capture_complete, nothing else (SPEC:158)."""
    upsert = {"capture_complete": True, "kind": "upsert", "seq": 5,
              "payload": {"attributes": {"hla": {"capture_complete": True, "x": 1}}}}
    snapshot = {"capture_complete": False, "kind": "snapshot", "seq": 3, "payload": {"y": 2}}
    assert _demo._normalised([upsert, snapshot]) == [
        b'{"capture_complete":null,"kind":"upsert","payload":{"attributes":{"hla":'
        b'{"capture_complete":null,"x":1}}},"seq":5}',
        b'{"capture_complete":null,"kind":"snapshot","payload":{"y":2},"seq":3}']
    assert upsert["capture_complete"] is True


# --------------------------------------------------- the checkpoints, judged on the bundled run

class _Tail:
    """What a run's capture tail holds, from a capture file."""

    def __init__(self, path: pathlib.Path) -> None:
        self.frames = [json.loads(line) for line in path.read_bytes().split(b"\n")[1:-1]
                       if json.loads(line)["type"] == "frame"]


class _BundledRun:
    """A stand-in for `_demo.Run` over the bundled capture: R38's steps at seqs 2..7 (discover,
    the four reflections, the removal), every barrier acknowledged, the object registered at
    GroundVehicle."""

    def __init__(self, capture: pathlib.Path) -> None:
        self.scenario = _demo.main_scenario()
        self.acknowledged = {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: None}
        self.tail = _Tail(capture)
        self.registered_class = GV


def _write_jsonl(path: pathlib.Path, records: list[dict]) -> None:
    path.write_bytes(b"".join(json.dumps(r, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=True).encode() + b"\n" for r in records))


def _bundled_run(tmp_path: pathlib.Path, mutate_live=None, mutate_both=None, mutate_run=None):
    """The bundled capture replayed (the replay directory) and its live form (completion fields
    null), with one fault applied: to both outputs (`mutate_both`, so that only the checkpoint
    that looks at the fault fails), to the live one alone, or to the run."""
    replayed = tmp_path / "replay"
    summary = replay(package_path("fixtures", "session.capture.jsonl", tmp_path), replayed)
    live = tmp_path / "live"
    live.mkdir()
    (live / "capture.jsonl").write_bytes((replayed / "capture.jsonl").read_bytes())
    records = [json.loads(line) for line in
               (replayed / "observations.jsonl").read_bytes().split(b"\n")[:-1]]
    if mutate_both is not None:
        mutate_both(records)
        _write_jsonl(replayed / "observations.jsonl", records)
        _write_jsonl(replayed / "diagnostics.jsonl",
                     [r for r in records if r["kind"] == "diagnostic"])
    live_records = copy.deepcopy(records)
    for record in live_records:
        record["capture_complete"] = None
        if record["kind"] == "upsert":
            record["payload"]["attributes"]["hla"]["capture_complete"] = None
    if mutate_live is not None:
        mutate_live(live_records)
    _write_jsonl(live / "observations.jsonl", live_records)
    _write_jsonl(live / "diagnostics.jsonl",
                 [r for r in live_records if r["kind"] == "diagnostic"])
    run = _BundledRun(live / "capture.jsonl")
    if mutate_run is not None:
        mutate_run(run)
    results = _demo.checkpoints("main", run, os.fsencode(live), os.fsencode(replayed), summary)
    return {c["id"]: c["result"] for c in results}, [c["id"] for c in results]


def package_path(directory: str, name: str, tmp_path: pathlib.Path) -> pathlib.Path:
    target = tmp_path / name
    target.write_bytes(package_bytes(directory, name))
    return target


def _upserts(records):
    return [r for r in records if r["kind"] == "upsert"]


def _set_upsert(index, *path_value):
    *path, value = path_value

    def apply(records):
        node = _upserts(records)[index]["payload"]
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return apply


#: One fault per row and the checkpoints it must fail, hand-derived (every other checkpoint must
#: pass). Tolerances (SPEC:144, SPEC:146): 1e-8 degrees, 1e-4 metres, 1e-6 metres per second.
CHECKPOINT_FAULTS = {
    "none": ({}, set()),
    "affiliation-hostile": ({"both": _set_upsert(0, "affiliation", "HOSTILE")}, {"affiliation"}),
    "entity-type-sensor": ({"both": _set_upsert(1, "entity_type", "SENSOR")}, {"platform"}),
    "identifier-entity-4": ({"both": _set_upsert(0, "attributes", "hla", "identifier",
                                                 {"site": 1, "application": 2, "entity": 4})},
                            {"identifier"}),
    "lat-2e-8": ({"both": _set_upsert(0, "position", "lat", 2e-8)}, {"position_equator"}),
    "lat-0.5e-8": ({"both": _set_upsert(0, "position", "lat", 0.5e-8)}, set()),
    "alt-10.0002": ({"both": _set_upsert(1, "position", "alt_m", 10.0002)},
                    {"position_second"}),
    "alt-10.00005": ({"both": _set_upsert(1, "position", "alt_m", 10.00005)}, set()),
    "course-90+2e-8": ({"both": _set_upsert(0, "kinematics", "course_deg", 90.00000002)},
                       {"course_east"}),
    "speed-10+2e-6": ({"both": _set_upsert(1, "kinematics", "speed_mps", 10.000002)},
                      {"course_east"}),
    "climb-2e-6": ({"both": _set_upsert(1, "kinematics", "climb_mps", 0.000002)},
                   {"course_east"}),
    "valid-from-backwards": ({"both": _set_upsert(1, "valid_from", "2026-01-01T00:00:00.999Z")},
                             {"valid_from_nondecreasing"}),
    "revision-gap": ({"both": lambda rs: _upserts(rs)[1].update(revision=3)}, {"revisions"}),
    "extra-diagnostic": ({"both": lambda rs: rs.insert(0, {
        "capture_complete": True, "entity_id": None, "generation": 1, "kind": "diagnostic",
        "object_token": None, "ordinal": 0, "output_version": 1, "revision": None, "seq": 2,
        "session_id": "example-001", "payload": {"code": "W_FORCE_UNMAPPED"}})},
                         {"no_diagnostics"}),
    "removed-last-revision-1": ({"both": lambda rs: [r for r in rs if r["kind"] == "removed"][0][
        "payload"].update(last_revision=1)}, {"removed_notice"}),
    "removed-twice": ({"both": lambda rs: rs.append(copy.deepcopy(
        [r for r in rs if r["kind"] == "removed"][0]))}, {"removed_notice"}),
    "second-entity-id": ({"both": lambda rs: [r for r in rs if r["kind"] == "removed"][0].update(
        entity_id="00000000-0000-5000-8000-000000000000")}, {"one_entity_id"}),
    "snapshot-class-leaf": ({"both": lambda rs: [r for r in rs if r["kind"] == "snapshot"][0][
        "payload"].update(reported_class=GV)}, {"reported_class"}),
    "replay-differs": ({"live": _set_upsert(0, "affiliation", "NEUTRAL")},
                       {"affiliation", "replay_identical"}),
    "step-unacknowledged": ({"run": lambda run: run.acknowledged.pop(3)}, {"steps_in_order"}),
    "steps-out-of-order": ({"run": lambda run: run.acknowledged.update({3: 6, 4: 5})},
                           {"steps_in_order"}),
    "registered-at-physical-entity": ({"run": lambda run: setattr(run, "registered_class", PE)},
                                      {"reported_class"}),
}


@case("A-DEMO", "G-R39", paragraphs=("SPEC:211",))
@pytest.mark.parametrize("row", sorted(CHECKPOINT_FAULTS))
def test_the_checkpoints_judge_the_bundled_run_and_fail_exactly_where_it_is_wrong(tmp_path, row):
    """OPS-13's semantic checkpoints, the demo's oracle, held on the bundled capture (whose steps
    are R38's and whose values the session checkpoints describe): unchanged, every checkpoint
    passes; each fault fails exactly the checkpoints of its row, a fault inside the tolerance
    none. Live and replay outputs carry the same fault (so only the checkpoint that reads it
    fails), except in `replay-differs`."""
    mutations, failing = CHECKPOINT_FAULTS[row]
    results, order = _bundled_run(tmp_path, mutate_live=mutations.get("live"),
                                  mutate_both=mutations.get("both"),
                                  mutate_run=mutations.get("run"))
    assert order == MAIN_CHECKPOINTS
    assert {k for k, v in results.items() if v == "FAIL"} == failing
    assert set(results.values()) <= {"PASS", "FAIL"}


@case("G-R47", "G-R18")
def test_nonzero_padding_survives_capture_export_and_replay_unchanged(tmp_path):
    """R47: "include nonzero padding variants and prove that preserved bytes are not normalized
    by capture export". A capture whose two Spatial values carry nonzero uninterpreted bytes (the
    packaged V-SPATIAL-PADDING, a5 in bytes 1-7 and 5a in 33-35, and one with 01..0a there,
    written by the tests' own encoder) is exported byte for byte by `synapse-hla
    export-capture`, and the copy, replayed, reports each value's padding as it came
    (padding_hex, R16), in the snapshots and in the upserts' attributes.hla.spatial."""
    vectors = positive_hex()
    padded = vectors["SPATIAL-PADDING"]
    numbered = encode_spatial(2, velocity=(0.0, 10.0, 0.0), padding=bytes(range(1, 11))).hex()
    source = (CaptureBuilder()
              .frame(1, 0, event_generation_start())
              .frame(1, 0, event_discover())
              .frame(1, 0, event_reflect(attributes=(("EntityIdentifier", vectors["ID-123"]),
                                                     ("EntityType", vectors["TYPE-PLATFORM"]),
                                                     ("Spatial", padded))))
              .frame(1, 1_000_000_000, event_reflect(attributes=(("Spatial", numbered),)))
              .frame(1, 1_000_000_000, event_generation_end())
              .footer()).write(tmp_path / "padded.jsonl")
    ran = run_cli(tmp_path, "export-capture", "--capture", source, "--out",
                  tmp_path / "copy.jsonl", creates=["copy.jsonl"])
    assert (ran.code, ran.stdout, ran.stderr) == (0, b"", b"")
    assert (tmp_path / "copy.jsonl").read_bytes() == source.read_bytes()
    replay(tmp_path / "copy.jsonl", tmp_path / "replayed")
    records = [strict_json(line) for line in
               (tmp_path / "replayed" / "observations.jsonl").read_bytes().split(b"\n")[:-1]]
    snapshots = [r["payload"]["attributes"]["Spatial"]["value"]["padding_hex"]
                 for r in records if r["kind"] == "snapshot"]
    upserts = [r["payload"]["attributes"]["hla"]["spatial"]["padding_hex"]
               for r in records if r["kind"] == "upsert"]
    assert snapshots == upserts == ["a5" * 7 + "5a" * 3, "0102030405060708090a"]


def test_evidence_class_is_development_evidence_named_by_the_platform():
    """CR-L04: DEV-macOS-arm64 on the development Mac; a build of this round never says more."""
    value = _demo.evidence_class()
    assert re.fullmatch(r"DEV-[A-Za-z0-9._-]+-[A-Za-z0-9._-]+", value)
    if sys.platform == "darwin" and os.uname().machine == "arm64":
        assert value == "DEV-macOS-arm64"


@pytest.mark.parametrize("member,value", [("barrier_ns", 0), ("rtinode_starts", 0),
                                          ("deadline_ns", -1), ("session_seconds", 1.5),
                                          ("rss_poll_ns", True)])
def test_the_demo_seams_take_positive_ints_only(member, value):
    with pytest.raises(ValueError):
        _demo.DemoSeams(**{member: value})
    with pytest.raises(TypeError):
        _demo.DemoSeams(choose_port=7)


# ------------------------------------------------------------------ CR-L16: locating the publisher

def test_the_publisher_is_found_by_its_variable_or_beside_the_worker_never_on_path():
    """CR-L16: the absolute path in SYNAPSE_HLA_PUBLISHER, else <package>/bin/sc-hla-publisher;
    a relative value is refused (None), PATH is never read."""
    assert _demo.PUBLISHER_LOCATION == str(pathlib.Path(_demo.host.WORKER_LOCATION).parent
                                           / "sc-hla-publisher")
    assert _demo.locate({}, "SYNAPSE_HLA_PUBLISHER", _demo.PUBLISHER_LOCATION) == \
        _demo.PUBLISHER_LOCATION
    assert _demo.locate({"SYNAPSE_HLA_PUBLISHER": "/x/p"}, "SYNAPSE_HLA_PUBLISHER", "/y") == "/x/p"
    assert _demo.locate({"SYNAPSE_HLA_PUBLISHER": "bin/p", "PATH": "/bin"},
                        "SYNAPSE_HLA_PUBLISHER", "/y") is None


VERSION = '{"name":"sc-hla-publisher","profile":"SC-HLA-RPR2-OBS-1","version":"1.0.0"}'
PUBLISHER_STANDINS = {
    "exact": (f"printf '%s\\n' '{VERSION}'", None),
    "trailing-space": (f"printf '%s \\n' '{VERSION}'", "answer"),
    "worker-line": ("printf '%s\\n' "
                    "'{\"name\":\"sc-hla-federate\",\"profile\":\"SC-HLA-RPR2-OBS-1\","
                    "\"version\":\"1.0.0\"}'", "answer"),
    "exit-3": (f"printf '%s\\n' '{VERSION}'; exit 3", "answer"),
    "two-lines": (f"printf '%s\\n%s\\n' '{VERSION}' '{VERSION}'", "answer"),
    "silent": ("exit 0", "answer"),
}


@pytest.mark.parametrize("row", sorted(PUBLISHER_STANDINS))
def test_the_publisher_pre_flight_wants_exactly_its_version_line(tmp_path, row):
    """CR-L16: `--version` prints exactly the publisher's line and exits 0, or the publisher
    counts as missing (the demo's BLOCKED result, OPS-18). Stand-in scripts, one per row; also a
    file that is not executable and one that does not exist."""
    body, problem = PUBLISHER_STANDINS[row]
    script = tmp_path / "sc-hla-publisher"
    script.write_text(f"#!/bin/sh\n[ \"$1\" = --version ] || exit 9\n{body}\n", encoding="utf-8")
    script.chmod(0o700)
    found = _demo.check_publisher(str(script), {})
    assert (found is None) == (problem is None), found
    script.chmod(0o600)
    assert _demo.check_publisher(str(script), {}) is not None
    assert _demo.check_publisher(str(tmp_path / "absent"), {}) is not None


# ------------------------------------------------- the publisher's events (R8-r1-F3, CR-R2-24)

FEDERATION = "SC_DEMO_00112233445566ff"


def _pins() -> dict:
    return {name: packaged_pins()[name]["sha256"] for name in _fom.FOM_MODULES}


def _event_run() -> _demo.Run:
    """A run of the main scenario whose publisher is only its stdout buffer (no process, no file,
    no socket): what `Run` makes of the lines it is given."""
    import types
    document = _demo.run_config("main", 40123, FEDERATION)
    run = _demo.Run("main", document, b"/nonexistent", _demo.main_scenario(), publisher="/x",
                    fom_dir="/x", pins=_pins(), environ={}, start_host=None, check=lambda: None,
                    seams=_demo.V1)
    run.publisher = types.SimpleNamespace(stdout=bytearray())
    return run


def _feed(run: _demo.Run, *lines: bytes) -> None:
    for line in lines:
        run.publisher.stdout.extend(line + b"\n")
    for event in run._publisher_events():
        run._on_event(event)


def _line(event) -> bytes:
    return json.dumps(event, separators=(",", ":")).encode("ascii")


def _valid_events() -> dict[str, dict]:
    """One event of each kind exactly as tools/publisher/publisher.cpp writes it (its emit calls,
    written out), for the run's federation and the packaged pins."""
    return {
        "modules": {"event": "modules", "sha256": _pins()},
        "created": {"event": "created", "federation": FEDERATION},
        "ready": {"class": GV, "event": "ready", "object_name": "SYNTHETIC-001", "objects": 1},
        "waiting": {"barrier": 0, "event": "waiting"},
        "acknowledged": {"barrier": 0, "event": "acknowledged"},
        "sent": {"event": "sent", "step": 1},
        "refresh": {"attributes": 4, "event": "refresh"},
        "resigned": {"event": "resigned"},
        "destroyed": {"event": "destroyed", "federation": FEDERATION},
        "disconnected": {"event": "disconnected"},
        "failure": {"event": "failure", "reason": "barrier_timeout", "stage": "barrier"},
        "cleanup": {"event": "cleanup", "reason": "NotConnected", "stage": "disconnect"},
    }


#: What must have come before an event of each kind for it to be in order (R38: modules, the
#: federation and the object before the observer joins at barrier 0).
_PREFIX = {"modules": (), "created": ("modules",), "ready": ("modules", "created")}


def _prefixed_run(kind: str) -> _demo.Run:
    run = _event_run()
    valid = _valid_events()
    _feed(run, *[_line(valid[k]) for k in _PREFIX.get(kind, ("modules", "created", "ready"))])
    return run


def test_the_publishers_own_events_are_read_as_it_writes_them():
    """The lines the publisher writes are accepted and recorded: its module digests (equal to the
    pins), the federation it created, the class it registered at, the barrier it waits at, its
    answers to update requests (one with values, one without), its destroy; a failure event of its
    vocabulary ends the run with that stage and reason recorded, E_DEPENDENCY_PIN for module_pin
    and E_RTI_CONNECT otherwise; foreign but well-formed digests are E_DEPENDENCY_PIN."""
    valid = _valid_events()
    run = _event_run()
    _feed(run, *[_line(valid[k]) for k in ("modules", "created", "ready", "waiting")])
    assert (run.module_sha256, run.created, run.registered_class, run.waiting) == (
        _pins(), True, GV, 0)
    run.acknowledged[0], run.waiting = 2, None
    _feed(run, _line(valid["acknowledged"]), _line(valid["sent"]),
          _line({"attributes": 0, "event": "refresh"}), _line(valid["refresh"]),
          _line(valid["resigned"]), _line(valid["destroyed"]), _line(valid["disconnected"]),
          _line(valid["cleanup"]))
    assert (run.refreshes, run.refresh_reflections, run.destroyed) == (2, 1, True)
    assert run.publisher_failure is None
    for reason, code in (("barrier_timeout", "E_RTI_CONNECT"), ("module_pin", "E_DEPENDENCY_PIN"),
                         ("FederationExecutionAlreadyExists", "E_RTI_CONNECT")):
        run = _event_run()
        with pytest.raises(_demo.RunFailure) as failed:
            _feed(run, _line({"event": "failure", "reason": reason, "stage": "create"}))
        assert (failed.value.stage, failed.value.code) == ("publisher", code)
        assert run.publisher_failure == {"stage": "create", "reason": reason}
    run = _event_run()
    foreign = dict(_pins(), **{"RPR-Base_v2.0.xml": "0" * 64})
    with pytest.raises(_demo.RunFailure) as failed:
        _feed(run, _line({"event": "modules", "sha256": foreign}))
    assert (failed.value.stage, failed.value.code) == ("publisher", "E_DEPENDENCY_PIN")
    assert run.module_sha256 == foreign


def test_the_schemas_publisher_failure_words_are_the_vocabulary_demo_admits():
    """R8-r2-F2: the `stage` and `reason` enums of a publisher failure in demo.schema.json are
    exactly `_demo.PUBLISHER_STAGES` and `PUBLISHER_REASONS` (the words the publisher's source
    can write, the test above), and a FAIL document carrying each word validates: a genuine
    publisher failure can never turn into the command line's schema defect."""
    failure = DEMO_SCHEMA.schema["$defs"]["run"]["properties"]["publisher"]["properties"][
        "failure"]["anyOf"][0]["properties"]
    assert sorted(failure["stage"]["enum"]) == sorted(_demo.PUBLISHER_STAGES)
    assert sorted(failure["reason"]["enum"]) == sorted(_demo.PUBLISHER_REASONS)
    for stage in sorted(_demo.PUBLISHER_STAGES):
        for reason in sorted(_demo.PUBLISHER_REASONS):
            document = _passing_document()
            _fail(document)
            document["runs"][0]["publisher"]["failure"] = {"stage": stage, "reason": reason}
            assert not list(DEMO_SCHEMA.iter_errors(document)), (stage, reason)


def test_the_publishers_failure_vocabulary_is_the_one_its_source_writes():
    """The stages and reasons `_demo` admits in a failure or cleanup event are exactly those
    tools/publisher/publisher.cpp can write: its `stage_` values, its own `fail("...")` reasons
    and the labels of its RTI exception types (never the RTI's text)."""
    code = PUBLISHER_SOURCE.read_text(encoding="utf-8")
    stages = set(re.findall(r'stage_ = "([a-z_]+)"', code))
    own = set(re.findall(r'fail\("([a-z_]+)"\)', code))
    labels = set(re.findall(r'return "([A-Za-z]+)";', code))
    cleanup = set(re.findall(r'\\"stage\\":\\"([a-z]+)\\"', code))
    assert stages == set(_demo.PUBLISHER_STAGES)
    assert labels == set(_demo.PUBLISHER_EXCEPTIONS)
    assert own | labels == set(_demo.PUBLISHER_REASONS)
    assert cleanup == set(_demo._CLEANUP_STAGES)


#: Values no member of any publisher event may hold: wrong types (bool is not an int), numbers
#: out of every range or beyond the strict reader's, oversize, empty and near-miss strings,
#: control, bidirectional and invisible code points, a lone surrogate, nesting.
def _nested(depth: int):
    value = []
    for _ in range(depth):
        value = [value]
    return value


HOSTILE_VALUES = [
    None, True, False, -1, 70000, 2 ** 53, 2 ** 64, 1.5, float("inf"), "", " ", "x" * 257,
    "x" * 900, "zz", "BARRIER_TIMEOUT", "barrier_timeout ", "a\u202eb", "\u0000", "\u0007",
    "\u061c", "\u2028", "\ud800", "\udfff", "\u00e9", "\ufeff", "SYNTHETIC-001\u200f", [], {},
    [1], {"a": [1]}, _nested(40), {"event": "failure"},
]


def _hostile_events():
    """Every event kind with each member in turn set to each hostile value (`object_name` keeps
    its one admitted null), one member missing, one member too many, the digest map broken
    member by member; then the same kinds with seeded random values (Random(20261024))."""
    import random
    valid = _valid_events()
    for kind, event in valid.items():
        for member in event:
            for value in HOSTILE_VALUES:
                if member == "object_name" and value is None:
                    continue
                yield kind, dict(event, **{member: value})
            if member != "event":
                yield kind, {k: v for k, v in event.items() if k != member}
        yield kind, dict(event, extra=1)
        yield kind, dict(event, Event=kind)
    for value in HOSTILE_VALUES + ["A" * 64, "0" * 63, "0" * 65, "g" * 64]:
        for name in _fom.FOM_MODULES:
            yield "modules", {"event": "modules", "sha256": dict(_pins(), **{name: value})}
    yield "modules", {"event": "modules", "sha256": dict(_pins(), **{"other.xml": "0" * 64})}
    yield "modules", {"event": "modules", "sha256": {k: v for k, v in list(_pins().items())[:4]}}
    pool = HOSTILE_VALUES + ["event", "SC_DEMO_", "HLAobjectRoot"]
    rng = random.Random(20261024)
    for _ in range(600):
        kind = rng.choice(sorted(valid))
        event = dict(valid[kind])
        members = [m for m in sorted(event) if m != "object_name"]
        for member in rng.sample(members, rng.randint(1, len(members))):
            event[member] = rng.choice(pool)
        if rng.random() < 0.25:
            event[rng.choice(["extra", "Event", "sha256", "barrier"])] = rng.choice(pool)
        yield kind, event


#: Lines that are no JSON object of the publisher at all.
HOSTILE_LINES = [
    b"", b"[]", b"0", b'"modules"', b"null", b"{}", b'{"event":"modules"', b"{" * 40 + b"}" * 40,
    b'{"event":"modules","sha256":' + b"[" * 100000 + b"]" * 100000 + b"}",
    b'{"event":"resigned","event":"resigned"}', b'{"event":"failure","reason":"' + b"r" * 2000
    + b'","stage":"barrier"}', b'{"event":"resigned"}' + b" " * 1100,
    b'{"event":"resigned\x01"}', b'{"event":"resigned"}\x7f', b'{"event":"resigned"}\r',
    b'{"event":"r\xc3\xa9signed"}', b'{"event":"resigned\xff"}', b'{"event":"resigned"}\x00',
    b'{"event":"resi\tgned"}', b'{"attributes":4.0,"event":"refresh"}',
    b'{"attributes":4e0,"event":"refresh"}', b'{"attributes":NaN,"event":"refresh"}',
    b'{"attributes":9007199254740993,"event":"refresh"}',
    b'{"event":"failure","reason":"\\ud800","stage":"barrier"}',
    b'{"event":"failure","reason":"barrier_timeout","stage":"barrier","stage":"x"}',
]


def _hostile_cases():
    for kind, event in _hostile_events():
        yield kind, json.dumps(event, separators=(",", ":")).encode("ascii")
    for line in HOSTILE_LINES:
        yield "waiting", line


@case("G-R38", paragraphs=("SPEC:207",))
def test_hostile_publisher_events_end_the_run_cleanly_and_never_reach_the_record():
    """R8-r1-F3 and CR-R2-24: a seeded pass of hostile publisher lines - every member of every
    event kind set to values of the wrong type, out of range, oversize, empty, near misses of its
    vocabulary, control, bidirectional and invisible code points, lone surrogates in the JSON
    escapes, nesting; members missing or added; broken digest maps; then lines that are no event
    at all (other JSON, unterminated, nesting beyond any bound, duplicate keys, floats, NaN,
    integers beyond 2^53, raw control, DEL, CR, NUL, non-ASCII and invalid UTF-8 bytes, lines over
    the bound). Each ends the run with the one fixed `RunFailure` of stage publisher and no code
    (exit 5 in the demo), never another exception, and records nothing it carried: no module map
    but the pinned one, no class but GroundVehicle, no failure stage or reason."""
    count = 0
    for kind, line in _hostile_cases():
        run = _prefixed_run(kind)
        with pytest.raises(_demo.RunFailure) as failed:
            _feed(run, line)
        assert (failed.value.stage, failed.value.code, failed.value.reason) == (
            "publisher", None, _demo._NOT_AN_EVENT), (kind, line[:200])
        assert run.module_sha256 in (None, _pins()) and run.registered_class in (None, GV)
        assert run.publisher_failure is None and run.destroyed is False
        count += 1
    assert count == 1676


def test_publisher_events_out_of_their_order_end_the_run():
    """R38's order as the publisher writes it: the module digests, then the federation, then the
    object at GroundVehicle (one, for main), and only then barrier 0; the barriers one by one, never
    one while another is pending; each of the first three once; a destroy only of a federation it
    created. Anything else ends the run (stage publisher, no code); an object reported at another
    class or in another number has its own fixed reason."""
    valid = _valid_events()
    cases = {
        "created-first": ("created",), "ready-first": ("ready",), "waiting-first": ("waiting",),
        "destroyed-first": ("destroyed",), "modules-twice": ("modules", "modules"),
        "created-twice": ("modules", "created", "created"),
        "ready-before-created": ("modules", "ready"),
        "waiting-before-ready": ("modules", "created", "waiting"),
        "ready-twice": ("modules", "created", "ready", "ready"),
        "waiting-twice": ("modules", "created", "ready", "waiting", "waiting"),
    }
    for name, kinds in cases.items():
        run = _event_run()
        with pytest.raises(_demo.RunFailure) as failed:
            _feed(run, *[_line(valid[k]) for k in kinds])
        assert (failed.value.stage, failed.value.code, failed.value.reason) == (
            "publisher", None, _demo._OUT_OF_ORDER), name
    run = _prefixed_run("waiting")
    with pytest.raises(_demo.RunFailure) as failed:
        _feed(run, _line({"barrier": 1, "event": "waiting"}))
    assert failed.value.reason == _demo._OUT_OF_ORDER
    for event, reason in (
            (dict(valid["ready"], **{"class": PE}), "the publisher registered its objects at a "
             "class other than GroundVehicle"),
            (dict(valid["ready"], objects=2), "the publisher registered another number of objects "
             "than its scenario has")):
        run = _prefixed_run("ready")
        with pytest.raises(_demo.RunFailure) as failed:
            _feed(run, _line(event))
        assert (failed.value.stage, failed.value.code, failed.value.reason) == (
            "publisher", None, reason)
        assert run.registered_class is None


def test_a_line_that_stops_the_run_leaves_the_lines_after_it_for_the_abort():
    """The publisher's events are taken one line at a time: when one ends the run (here its
    failure event), the lines it wrote after it in the same read (resigned, destroyed) are still
    there for `abort`, which records the destroy of the federation it created."""
    valid = _valid_events()
    run = _prefixed_run("waiting")
    with pytest.raises(_demo.RunFailure):
        _feed(run, _line(valid["failure"]), _line(valid["resigned"]), _line(valid["destroyed"]))
    assert run.destroyed is False
    assert [e["event"] for e in run._publisher_events()] == ["resigned", "destroyed"]


def test_the_end_of_a_child_never_waits_on_a_pipe_another_process_holds():
    """A child that leaves a process of its own behind holding its stdout (here a shell that
    starts a `sleep` in the background and exits) is reaped, what it wrote is read, and its end
    returns after one deadline at most with every pipe closed: a hostile publisher cannot hold
    the demo (or spin it) by never closing its pipe. The left-behind process was started by the
    child, not by `_demo`; the test stops it by the PID the shell printed."""
    import signal as signals
    import threading
    child = _demo._Child.start(["/bin/sh", "-c", "/bin/sleep 30 & echo $!; exit 0"],
                               {"PATH": "/usr/bin:/bin"}, stdin=False)
    deadline = time.monotonic() + 10
    while not child.poll() and time.monotonic() < deadline:
        child.pump(10)
    seams = _demo.DemoSeams(deadline_ns=200_000_000)
    ending = threading.Thread(target=child.end, args=(seams,), kwargs={"graceful": True},
                              daemon=True)
    ending.start()
    ending.join(5)
    finished = not ending.is_alive()
    holder = int(bytes(child.stdout).split()[0])
    try:
        os.kill(holder, signals.SIGKILL)
    except ProcessLookupError:
        pass
    ending.join(10)
    assert finished
    assert (child.reaped, child.status, child.stdout_fd, child.stderr_fd) == (True, 0, None, None)
    assert process_gone(holder)


# ------------------------------------------------------------------------ the report's schema

def _passing_document() -> dict:
    """A PASS document written out by hand, for the schema's rows."""
    pins = {name: packaged_pins()[name]["sha256"] for name in _fom.FOM_MODULES}
    steps = [{"barrier": n, "event": e, "tag": t, "seq": s, "acknowledged": True}
             for n, e, t, s in ((0, "discover", None, 2), (1, "reflect", "step-1", 3),
                                (2, "reflect", "step-2", 4), (3, "reflect", "step-3", 5),
                                (4, "reflect", "step-4", 6), (5, "remove", "step-5", 7),
                                (6, "resigned", None, None))]

    def run(name, session_id, policy, ids):
        return {
            "name": name, "directory": name, "replay_directory": f"{name}-replay",
            "session_id": session_id, "time_policy": policy,
            "federation_name": "SC_DEMO_0123456789abcdef", "federate_name": "SC_OBSERVER",
            "endpoint": "rti://127.0.0.1:40123", "config_sha256": "a" * 64,
            "publisher": {"pid": 101, "exit_status": 0, "module_sha256": pins,
                          "registered_class": GV, "created": True, "destroyed": True,
                          "refreshes": 1, "refresh_reflections": 0, "failure": None},
            "host": {"pid": 102, "exit_status": 0}, "steps": steps, "refresh_seqs": [],
            "session": {"status": "COMPLETE", "reason_code": None, "terminal_codes": [],
                        "frames": 8, "last_seq": 9, "last_generation": 1, "workers": 1,
                        "records": {"snapshot": 4}},
            "capture_sha256": "b" * 64,
            "replay": {"status": "COMPLETE", "observations_sha256": "c" * 64},
            "checkpoints": [{"id": i, "result": "PASS"} for i in ids], "result": "PASS"}
    return {
        "demo_version": 1, "status": "PASS", "profile": "SC-HLA-RPR2-OBS-1",
        "adapter_version": "1.0.0", "source_commit": None, "evidence_class": "DEV-macOS-arm64",
        "tested_reference": _demo.TESTED_REFERENCE, "scope": _demo.SCOPE,
        "external_customer_interoperability": "NOT_TESTED",
        "profile_declaration": "bundled-fom-created", "fom_sha256": pins,
        "rtinode": {"address": "127.0.0.1", "port": 40123, "pid": 100,
                    "attempts": [{"port": 40123, "pid": 100, "outcome": "listening"}],
                    "exit_status": 0},
        "runs": [run("main", "example-001", "external_elapsed", MAIN_CHECKPOINTS),
                 run("no-time", "example-001-none", "none", NO_TIME_CHECKPOINTS)],
        "cleanup": {"result": "PASS", "port_released": True,
                    "processes": [{"role": "rtinode", "pid": 100, "reaped": True,
                                   "exit_status": 0}]},
        "failures": []}


def _edit(path, value):
    def apply(document):
        node = document
        for key in path[:-1]:
            node = node[key]
        if value is _DELETE:
            del node[path[-1]]
        else:
            node[path[-1]] = value
    return apply


_DELETE = object()
#: Each row breaks one rule of demo.schema.json; the hand-written PASS document passes.
SCHEMA_ROWS = {
    "pass-with-a-failed-checkpoint": _edit(("runs", 0, "checkpoints", 3, "result"), "FAIL"),
    "pass-with-a-failure": _edit(("failures",), [{"stage": "rtinode", "reason": "x", "run": None,
                                                  "code": "E_RTI_CONNECT"}]),
    "pass-with-cleanup-fail": _edit(("cleanup", "result"), "FAIL"),
    "pass-with-the-port-open": _edit(("cleanup", "port_released"), False),
    "pass-with-one-run": lambda d: d["runs"].pop(),
    "pass-with-a-run-fail": _edit(("runs", 1, "result"), "FAIL"),
    "interoperability-claimed": _edit(("external_customer_interoperability",), "PASS"),
    "scope-changed": _edit(("scope",), "OpenRTI is the tested reference."),
    "reference-evidence-claimed": _edit(("evidence_class",), "REFERENCE-linux-x86_64"),
    "federation-uppercase": _edit(("runs", 0, "federation_name"), "SC_DEMO_0123456789ABCDEF"),
    "federation-short": _edit(("runs", 0, "federation_name"), "SC_DEMO_0123456789abcde"),
    "endpoint-not-loopback": _edit(("runs", 0, "endpoint"), "rti://127.0.0.2:40123"),
    "rtinode-elsewhere": _edit(("rtinode", "address"), "0.0.0.0"),
    "six-rtinode-starts": lambda d: d["rtinode"]["attempts"].extend(
        [{"port": 40124 + i, "pid": 200 + i, "outcome": "address_in_use"} for i in range(5)]),
    "module-digest-uppercase": _edit(("runs", 0, "publisher", "module_sha256",
                                      "RPR-Base_v2.0.xml"), "A" * 64),
    "registered-elsewhere": _edit(("runs", 0, "publisher", "registered_class"), PE),
    "unknown-checkpoint": _edit(("runs", 0, "checkpoints", 0, "id"), "capture_ok"),
    "blocked-with-runs": _edit(("status",), "BLOCKED"),
    "missing-on-a-run": _edit(("missing",), [{"item": "rtinode", "code": "E_DEPENDENCY_PIN",
                                              "message": "x"}]),
    "no-cleanup": _edit(("cleanup",), _DELETE),
    "source-commit-invented": _edit(("source_commit",), "c4bba1b6" * 5),
    "extra-member": _edit(("verdict",), "PASS"),
    # R8-r1-F4: what PASS and a clean-up PASS must also carry.
    "pass-with-an-unreaped-process": _edit(("cleanup", "processes", 0, "reaped"), False),
    "pass-with-no-process": _edit(("cleanup", "processes"), []),
    "pass-with-an-unacknowledged-step": _edit(("runs", 0, "steps", 3, "acknowledged"), False),
    "pass-with-six-steps": lambda d: d["runs"][1]["steps"].pop(),
    "pass-without-destroy": _edit(("runs", 0, "publisher", "destroyed"), False),
    "pass-without-create": _edit(("runs", 1, "publisher", "created"), False),
    "pass-with-a-publisher-failure": _edit(("runs", 0, "publisher", "failure"),
                                           {"stage": "barrier", "reason": "barrier_timeout"}),
    "pass-with-the-publisher-exit-1": _edit(("runs", 1, "publisher", "exit_status"), 1),
    "pass-without-registered-class": _edit(("runs", 0, "publisher", "registered_class"), None),
    "pass-without-module-digests": _edit(("runs", 1, "publisher", "module_sha256"), None),
    "pass-without-host": _edit(("runs", 0, "host"), None),
    "pass-with-session-failed": _edit(("runs", 0, "session", "status"), "FAILED"),
    "pass-without-session": _edit(("runs", 1, "session"), None),
    "pass-without-replay": _edit(("runs", 0, "replay"), None),
    "pass-with-replay-incomplete": _edit(("runs", 1, "replay", "status"), "INCOMPLETE"),
    "pass-without-capture-digest": _edit(("runs", 0, "capture_sha256"), None),
    "pass-without-rtinode-pid": _edit(("rtinode", "pid"), None),
    "pass-without-rtinode-port": _edit(("rtinode", "port"), None),
    "pass-without-a-listening-start": _edit(("rtinode", "attempts", 0, "outcome"),
                                            "address_in_use"),
    "pass-with-two-listening-starts": lambda d: d["rtinode"]["attempts"].append(
        {"port": 40124, "pid": 99, "outcome": "listening"}),
    "checkpoints-reordered": lambda d: d["runs"][0]["checkpoints"].insert(
        0, d["runs"][0]["checkpoints"].pop(1)),
    "checkpoints-one-missing": lambda d: d["runs"][1]["checkpoints"].pop(4),
    "checkpoints-one-repeated": lambda d: d["runs"][0]["checkpoints"].append(
        {"id": "capture_verified", "result": "PASS"}),
    "no-time-with-main-checkpoints": _edit(("runs", 1, "checkpoints"),
                                           [{"id": i, "result": "PASS"}
                                            for i in MAIN_CHECKPOINTS]),
    "failed-cleanup-pass-with-an-unreaped-process": lambda d: (
        _fail(d), _edit(("cleanup", "processes", 0, "reaped"), False)(d)),
    "failed-cleanup-pass-with-the-port-open": lambda d: (
        _fail(d), _edit(("cleanup", "port_released"), False)(d)),
    "publisher-failure-outside-its-vocabulary": lambda d: (
        _fail(d), _edit(("runs", 0, "publisher", "failure"),
                        {"stage": "barrier", "reason": "barrier timeout"})(d)),
    "publisher-failure-stage-outside-its-vocabulary": lambda d: (
        _fail(d), _edit(("runs", 0, "publisher", "failure"),
                        {"stage": "x\u202ey", "reason": "barrier_timeout"})(d)),
    "failure-stage-unknown": lambda d: (_fail(d), _edit(("failures",), [
        {"stage": "worker", "reason": "x", "run": "main", "code": None}])(d)),
    "failure-reason-not-printable-ascii": lambda d: (_fail(d), _edit(("failures",), [
        {"stage": "publisher", "reason": "a\u202eb", "run": "main", "code": None}])(d)),
    # R8-r2-F1: the seven steps are R38's, each at its position, whatever the status.
    "steps-reversed": lambda d: d["runs"][0]["steps"].reverse(),
    "steps-two-swapped": lambda d: d["runs"][1]["steps"].insert(1, d["runs"][1]["steps"].pop(2)),
    "steps-a-barrier-repeated": _edit(("runs", 0, "steps", 2, "barrier"), 1),
    "steps-an-event-moved": _edit(("runs", 0, "steps", 5, "event"), "reflect"),
    "steps-a-tag-moved": _edit(("runs", 1, "steps", 2, "tag"), "step-3"),
    "steps-an-eighth": lambda d: d["runs"][0]["steps"].append(
        {"barrier": 6, "event": "resigned", "tag": None, "seq": None, "acknowledged": True}),
    "failed-steps-reversed": lambda d: (_fail(d), d["runs"][0]["steps"].reverse()),
}


def _fail(document: dict) -> None:
    """The PASS document turned into a FAIL one (a failed checkpoint), to show a rule that holds
    whatever the status."""
    document["status"] = "FAIL"
    document["runs"][0]["checkpoints"][3]["result"] = "FAIL"
    document["runs"][0]["result"] = "FAIL"


def test_the_hand_written_pass_document_is_valid():
    """The PASS document, and FAIL documents the demo writes: a failed checkpoint; a publisher
    failure of its vocabulary that stopped the main run before any checkpoint (no checkpoints, the
    publisher not destroyed, no replay); rtinode that never listened (no runs, no pid or port, the
    clean-up PASS with the port's state unknown)."""
    assert not list(DEMO_SCHEMA.iter_errors(_passing_document()))
    failed = _passing_document()
    _fail(failed)
    assert not list(DEMO_SCHEMA.iter_errors(failed))
    stopped = _passing_document()
    stopped["status"] = "FAIL"
    run = stopped["runs"].pop(0)
    stopped["runs"] = [run]
    run.update(result="FAIL", checkpoints=[], replay=None, session=None)
    run["publisher"].update(failure={"stage": "barrier", "reason": "barrier_timeout"},
                            destroyed=False, exit_status=1)
    stopped["failures"] = [{"stage": "publisher", "reason": "the publisher failed", "run": "main",
                            "code": "E_RTI_CONNECT"}]
    assert not list(DEMO_SCHEMA.iter_errors(stopped))
    unstarted = _passing_document()
    unstarted.update(status="FAIL", runs=[], failures=[
        {"stage": "rtinode", "reason": "every port tried for rtinode was in use", "run": None,
         "code": "E_RTI_CONNECT"}])
    unstarted["rtinode"].update(port=None, pid=None, exit_status=None, attempts=[
        {"port": 40123, "pid": 100, "outcome": "address_in_use"}])
    unstarted["cleanup"].update(port_released=None, processes=[
        {"role": "rtinode", "pid": 100, "reaped": True, "exit_status": 1}])
    assert not list(DEMO_SCHEMA.iter_errors(unstarted))


@pytest.mark.parametrize("row", sorted(SCHEMA_ROWS))
def test_the_demo_schema_refuses_each_broken_rule(row):
    """CR-L03: demo.schema.json is the contract of DIR/demo.json; each row breaks one of its
    rules (PASS only with every checkpoint, no failure, a clean clean-up and both runs; the
    interoperability field and the scope statement fixed; development evidence only; the
    federation and endpoint forms; at most five rtinode starts; BLOCKED and ran exclusive)."""
    document = _passing_document()
    SCHEMA_ROWS[row](document)
    assert list(DEMO_SCHEMA.iter_errors(document))


# ============================================================================ the demo, for real

def native_paths() -> dict:
    """The variables of the four executables (D-07: absent is BLOCKED)."""
    out = {}
    for variable in ("SYNAPSE_HLA_WORKER", "SYNAPSE_HLA_RTINODE", "SYNAPSE_HLA_PUBLISHER"):
        out[variable] = str(native_executable(variable))
    return out


def demo_environment(tmp_path: pathlib.Path, extra: dict | None = None) -> dict:
    """The command line's guards in their loopback form: every socket on 127.0.0.1 (logged),
    nothing written outside the test's directory."""
    env = environment(tmp_path, extra={**native_paths(), **(extra or {})})
    env["SC_HLA_SOCKETS"] = "loopback"
    env["SC_HLA_SOCKET_LOG"] = str(tmp_path / "sockets.log")
    return env


def run_demo(tmp_path: pathlib.Path, out_name: str = "demo", extra: dict | None = None,
             creates: tuple = ()):
    args = ["demo", "--out", tmp_path / out_name]
    proc, before = start(tmp_path, *args, env=demo_environment(tmp_path, extra))
    ran = finish(tmp_path, proc, before, args, creates=[out_name, "sockets.log", *creates],
                 timeout=600)
    return ran, strict_json((tmp_path / out_name / "demo.json").read_bytes())


def lines(path: pathlib.Path) -> list[dict]:
    return [strict_json(line) for line in path.read_bytes().split(b"\n")[:-1]]


def assert_nothing_left(document: dict) -> None:
    """R39, SPEC:211: every process the demo started, and every worker its hosts reported, is
    gone; the port no longer accepts a connection."""
    pids = [p["pid"] for p in document["cleanup"]["processes"]]
    assert pids and all(process_gone(pid) for pid in pids), pids
    assert all(p["reaped"] for p in document["cleanup"]["processes"])
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", document["rtinode"]["port"]), timeout=1).close()


def check_run(root: pathlib.Path, run: dict) -> None:
    """One run of demo.json against its directories: the capture verifies COMPLETE and has the
    recorded digest; each acknowledged step is at its recorded seq with its event and tag; each
    refresh seq is a reflection tagged `refresh`; the replay equals the live outputs but for
    SPEC:158's completion fields (the tests' own `without_completion`)."""
    live, replayed = root / run["directory"], root / run["replay_directory"]
    report = verify_capture(live / "capture.jsonl")
    assert (report["status"], report["capture_complete"]) == ("COMPLETE", True)
    assert run["capture_sha256"] == _sha256(live / "capture.jsonl")
    frames = {r["seq"]: r for r in lines(live / "capture.jsonl")[1:] if r["type"] == "frame"}
    seqs = []
    for step in run["steps"]:
        assert step["acknowledged"], step
        if step["event"] == "resigned":
            assert step["seq"] is None
            continue
        event = frames[step["seq"]]["event"]
        assert event["type"] == step["event"]
        if step["tag"] is not None:
            assert bytes.fromhex(event["tag_hex"]).decode("ascii") == step["tag"]
        seqs.append(step["seq"])
    assert seqs == sorted(set(seqs))
    for seq in run["refresh_seqs"]:
        assert frames[seq]["event"]["type"] == "reflect"
        assert frames[seq]["event"]["tag_hex"] == b"refresh".hex()
    for name in ("observations.jsonl", "diagnostics.jsonl"):
        live_records = lines(live / name)
        replay_records = lines(replayed / name)
        assert [without_completion(r) for r in live_records] == \
            [without_completion(r) for r in replay_records]
        assert all(r["capture_complete"] is None for r in live_records)
        assert all(r["capture_complete"] is True for r in replay_records)
    assert (replayed / "capture.jsonl").read_bytes() == (live / "capture.jsonl").read_bytes()
    assert run["replay"]["observations_sha256"] == _sha256(replayed / "observations.jsonl")


def _sha256(path: pathlib.Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def two_demos(tmp_path_factory):
    """Exit criterion 3: the demo through the command line twice, each from a directory outside
    any checkout (the test's temporary directory), as `synapse-hla demo --out <dir>`."""
    out = []
    for index in (1, 2):
        tmp = tmp_path_factory.mktemp(f"demo{index}")
        ran, document = run_demo(tmp)
        out.append((tmp, ran, document))
    return out


@pytest.mark.rti
@case("A-DEMO", "G-R38", "G-R39", "G-R07", "G-R36", "G-R02",
      paragraphs=("SPEC:207", "SPEC:211", "SPEC:38", "SPEC:174", "SPEC:8"))
def test_the_demo_passes_every_checkpoint_and_leaves_nothing_behind(two_demos):
    """A-DEMO, through the command line: exit 0 with a PASS summary; demo.json valid against its
    schema, status PASS, both runs PASS with every checkpoint of OPS-13 in its fixed order; the
    run directories hold exactly the four files each (OPS-13's layout) and agree with demo.json
    (`check_run`); the main run's objects carry the fixture's entity id; the no-time run has
    snapshots and no upsert (R39); rtinode was started once on 127.0.0.1 at the port recorded;
    every process gone and the port closed (R39, SPEC:211); nothing written outside --out (the
    write guard) and every socket the command opened on 127.0.0.1 (the loopback guard's log)."""
    for tmp, ran, document in two_demos:
        assert ran.code == 0 and ran.summary["exit_code"] == 0
        assert ran.summary["result"] == {
            "status": "PASS", "cleanup": "PASS", "failures": [],
            "runs": [{"name": "main", "result": "PASS", "failed_checkpoints": []},
                     {"name": "no-time", "result": "PASS", "failed_checkpoints": []}]}
        assert ran.diagnostics == [] and ran.summary["codes"] == ["W_TIME_UNRESOLVED"]
        assert not list(DEMO_SCHEMA.iter_errors(document))
        assert document["status"] == "PASS" and document["failures"] == []
        root = tmp / "demo"
        assert tree(root) == {"demo.json"} | {
            f"{d}{suffix}" for d in ("main", "main-replay", "no-time", "no-time-replay")
            for suffix in ("", "/capture.jsonl", "/observations.jsonl", "/diagnostics.jsonl",
                           "/run.json")}
        main, none = document["runs"]
        assert [c["id"] for c in main["checkpoints"]] == MAIN_CHECKPOINTS
        assert [c["id"] for c in none["checkpoints"]] == NO_TIME_CHECKPOINTS
        assert {c["result"] for r in document["runs"] for c in r["checkpoints"]} == {"PASS"}
        for run in document["runs"]:
            check_run(root, run)
        entity_ids = {r["entity_id"] for r in lines(root / "main" / "observations.jsonl")}
        assert entity_ids == {ENTITY_ID}
        none_kinds = [r["kind"] for r in lines(root / "no-time" / "observations.jsonl")]
        assert "upsert" not in none_kinds and none_kinds.count("snapshot") >= 4
        assert [a["outcome"] for a in document["rtinode"]["attempts"]] == ["listening"]
        assert document["rtinode"]["port"] == document["rtinode"]["attempts"][0]["port"]
        port = document["rtinode"]["port"]
        assert {r["endpoint"] for r in document["runs"]} == {f"rti://127.0.0.1:{port}"}
        assert_nothing_left(document)
        logged = (tmp / "sockets.log").read_text(encoding="utf-8").splitlines()
        assert logged and all("('127.0.0.1', " in line for line in logged)


@pytest.mark.rti
@case("G-R38", "G-R39", paragraphs=("SPEC:207", "SPEC:211"))
def test_two_demos_agree_on_every_checkpoint_and_differ_only_in_their_names(two_demos):
    """Exit criterion 3 of the round: the checkpoint results of the two manifests are identical;
    each run used a federation of its own (four distinct SC_DEMO_ names, R38: random names enter
    no golden value) while the main runs' entity id is the fixture's in both; the publisher
    reported the pinned digests of the five modules in every run (R11)."""
    (_, _, first), (_, _, second) = two_demos
    assert [r["checkpoints"] for r in first["runs"]] == [r["checkpoints"] for r in second["runs"]]
    names = [r["federation_name"] for d in (first, second) for r in d["runs"]]
    assert len(set(names)) == 4
    pins = {name: packaged_pins()[name]["sha256"] for name in _fom.FOM_MODULES}
    for document in (first, second):
        assert document["fom_sha256"] == pins
        for run in document["runs"]:
            assert run["publisher"]["module_sha256"] == pins
            assert (run["publisher"]["created"], run["publisher"]["destroyed"]) == (True, True)


@pytest.mark.rti
@case("G-R11", "G-R39", "G-R38", paragraphs=("SPEC:211", "SPEC:207"))
def test_the_demo_report_keeps_its_evidence_apart_from_an_existing_federation(two_demos):
    """R11: the demo proves which hashed module bytes created its federation (the publisher's
    digests, equal to the pins) and declares bundled-fom-created; its runs' captures hold mode
    demo with that declaration and no W_FOM_UNVERIFIED (which an existing federation's session
    emits); R39: the report states that OpenRTI is the tested reference and that neither a
    customer simulator nor a second RTI implementation was tested; the interoperability field
    stays NOT_TESTED (OPS-01) and the evidence is development evidence (CR-L04)."""
    for tmp, _, document in two_demos:
        assert document["profile_declaration"] == "bundled-fom-created"
        assert document["tested_reference"] == \
            "OpenRTI 814a210978b7faafd65affbe70a2e25679921b23"
        assert document["scope"].endswith(
            "Neither a customer simulator nor a second RTI implementation was tested.")
        assert document["external_customer_interoperability"] == "NOT_TESTED"
        assert document["evidence_class"].startswith("DEV-")
        for run in document["runs"]:
            header = lines(tmp / "demo" / run["directory"] / "capture.jsonl")[0]
            assert (header["config"]["mode"], header["config"]["profile_declaration"]) == (
                "demo", "bundled-fom-created")
            codes = {r["payload"]["code"] for r in
                     lines(tmp / "demo" / run["directory"] / "observations.jsonl")
                     if r["kind"] == "diagnostic"}
            assert "W_FOM_UNVERIFIED" not in codes


@pytest.mark.rti
@case("A-CLASS", "G-R10", paragraphs=("SPEC:50",))
def test_the_demo_object_is_reported_at_physical_entity_though_registered_at_ground_vehicle(
        two_demos):
    """A-CLASS through the demo (NAT-01, NAT-04, SPEC:50): the publisher registered its object at
    GroundVehicle (its own report) and the observer, subscribed at PhysicalEntity, captured the
    discovery with the qualified name of PhysicalEntity; no capture or output names the leaf
    class, which no RTI call told the observer."""
    for tmp, _, document in two_demos:
        for run in document["runs"]:
            assert run["publisher"]["registered_class"] == GV
            directory = tmp / "demo" / run["directory"]
            discovers = [r["event"] for r in lines(directory / "capture.jsonl")[1:]
                         if r["type"] == "frame" and r["event"]["type"] == "discover"]
            assert [d["reported_class"] for d in discovers] == [PE]
            for name in ("capture.jsonl", "observations.jsonl"):
                assert b"GroundVehicle" not in (directory / name).read_bytes()


# ------------------------------------------------------------------- rtinode's start (R38, NAT-18)

class _Busy:
    """Ports held by listening sockets of this test on 127.0.0.1."""

    def __init__(self, count: int) -> None:
        self.sockets = []
        for _ in range(count):
            held = socket.socket()
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            self.sockets.append(held)
        self.ports = [s.getsockname()[1] for s in self.sockets]

    def close(self) -> None:
        for held in self.sockets:
            held.close()


def _rtinode_with(ports, path=None):
    node = _demo.Rtinode()
    sequence = iter(ports)
    seams = _demo.DemoSeams(choose_port=lambda: next(sequence))
    environ = {k: v for k, v in os.environ.items() if not k.startswith("SYNAPSE_HLA_")}
    problem = node.start(path or str(native_executable("SYNAPSE_HLA_RTINODE")), environ, seams,
                         lambda: None)
    return node, seams, problem


@pytest.mark.rti
@case("G-R38", paragraphs=("SPEC:207",))
def test_a_busy_port_is_tried_again_on_another_at_most_five_starts_in_all():
    """R38 and NAT-18: rtinode on a port another socket holds exits 1 with "Address already in
    use" (LC_ALL=C), and only that is retried, on the next port chosen; a free port then gives
    a listening rtinode, ready by a raw connect and still running at the end of its start-up
    window (the busy port's own listener accepts the probe too, so a connect alone would
    mistake it for rtinode). Five busy ports in a row are five starts and a failure, every start
    reaped, nothing listening. CR-new-R8: at most five starts in all, which holds under both
    readings of "retry ... at most five times"."""
    busy = _Busy(5)
    try:
        free = _demo._free_port()
        node, seams, problem = _rtinode_with([busy.ports[0], free])
        try:
            assert problem is None
            assert [(a["port"], a["outcome"]) for a in node.attempts] == [
                (busy.ports[0], "address_in_use"), (free, "listening")]
            assert node.port == free
            listening = subprocess.run([str(fixed_tool("lsof")), "-nP", "-a", "-p",
                                        str(node.child.pid), "-iTCP", "-sTCP:LISTEN"],
                                       capture_output=True, text=True)
            if listening.returncode == 0:
                # R38: bound explicitly to 127.0.0.1, not to every address.
                assert re.findall(r"TCP (\S+) \(LISTEN\)", listening.stdout) == \
                    [f"127.0.0.1:{free}"]
        finally:
            node.stop(seams)
        assert node.port_released is True and process_gone(node.child.pid)
        # The clean-up's records are what was observed (R8-r1-F1): the busy start ended with
        # status 1, the listening one was reaped after its stop.
        records = node.processes()
        assert [(r["role"], r["pid"], r["reaped"]) for r in records] == [
            ("rtinode", a["pid"], True) for a in node.attempts]
        assert records[0]["exit_status"] == 1 and type(records[1]["exit_status"]) is int
        node, seams, problem = _rtinode_with(busy.ports + [free])
        assert problem == "every port tried for rtinode was in use"
        assert [(a["port"], a["outcome"]) for a in node.attempts] == [
            (port, "address_in_use") for port in busy.ports]
        assert node.child is None
        assert all(process_gone(a["pid"]) for a in node.attempts)
        assert node.processes() == [{"role": "rtinode", "pid": a["pid"], "reaped": True,
                                     "exit_status": 1} for a in node.attempts]
    finally:
        busy.close()


@pytest.mark.rti
@case("G-R38", paragraphs=("SPEC:207",))
def test_any_other_early_end_of_rtinode_is_a_failure_without_retry(tmp_path):
    """NAT-18: a start that ends for another reason (here a stand-in rtinode that exits 1 with
    another message, and one that exits 2 mentioning a busy address) fails the demo at once:
    one start, no retry."""
    for body in ("echo 'cannot open the configuration' >&2; exit 1",
                 "echo 'Address already in use' >&2; exit 2"):
        script = tmp_path / "rtinode"
        script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        script.chmod(0o700)
        node, _seams, problem = _rtinode_with([_demo._free_port()] * 5, path=str(script))
        assert problem == "rtinode ended during its start for a reason other than a busy port"
        assert [a["outcome"] for a in node.attempts] == ["exited"]


class _Stop(BaseException):
    """What a command's `check` raises once a stop signal has arrived (as `cli._Interrupted`)."""


def _stop_at(call: int):
    """A `check` that raises `_Stop` from its `call`-th call on, as a SIGINT noted just before
    that call would make the command's `check_stop` do."""
    calls = []

    def check() -> None:
        calls.append(None)
        if len(calls) >= call:
            raise _Stop()
    return check


def _rtinode_environ() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("SYNAPSE_HLA_")}


def _refused(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return True
    return False


def _kill_and_reap(pids) -> None:
    """A leak a failing test found is still stopped by its PID, so the suite leaves nothing."""
    import signal as signals
    for pid in pids:
        try:
            os.kill(pid, signals.SIGKILL)
        except ProcessLookupError:
            continue
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass


@pytest.mark.rti
@case("G-R39", "G-R38", paragraphs=("SPEC:211", "SPEC:207"))
@pytest.mark.parametrize("call", [1, 2, 10])
def test_a_stop_while_rtinode_starts_ends_it_by_its_pid_and_its_port_refuses(call):
    """R8-r1-F1, SPEC:211 ("verify process exit and report leaked resources as failure"): a stop
    that reaches `Rtinode.start` after it spawned rtinode (the `check` raises on its 2nd call, just
    after the spawn, or on its 10th, inside the start-up window while rtinode already listens)
    leaves `start` by that exception only after rtinode was ended by its PID and reaped: the
    process is gone, its port refuses a connect, and the attempt's process record says reaped with
    the status it ended with. A stop before the first spawn (1st call) starts nothing."""
    port = _demo._free_port()
    node = _demo.Rtinode()
    seams = _demo.DemoSeams(choose_port=lambda: port)
    try:
        with pytest.raises(_Stop):
            node.start(str(native_executable("SYNAPSE_HLA_RTINODE")), _rtinode_environ(), seams,
                       _stop_at(call))
        assert node.child is None
        if call == 1:
            assert node.attempts == [] and node.processes() == []
            return
        assert [(a["port"], a["outcome"]) for a in node.attempts] == [(port, None)]
        pid = node.attempts[0]["pid"]
        assert process_gone(pid), pid
        assert _refused(port)
        [record] = node.processes()
        assert (record["role"], record["pid"], record["reaped"]) == ("rtinode", pid, True)
        assert type(record["exit_status"]) is int
    finally:
        _kill_and_reap([a["pid"] for a in node.attempts])


@pytest.mark.rti
@case("G-R39", paragraphs=("SPEC:211",))
@pytest.mark.parametrize("call", [2, 10])
def test_run_demo_stopped_while_rtinode_starts_leaves_no_process_and_no_listener(tmp_path, call):
    """R8-r1-F1 through `run_demo`, the orchestration the command line runs: the stop raised by
    `check` while rtinode starts leaves `run_demo` only after rtinode was ended (its docstring:
    "whatever is raised, everything started here has been stopped and reaped first"): no process
    is left below this test's process and the chosen port refuses a connect. No observer was
    started and nothing was written into the target."""
    port = _demo._free_port()
    seams = _demo.DemoSeams(choose_port=lambda: port)
    modules = _fom.check_fom_modules(str(fom_modules()[0].parent))
    target = tmp_path / "demo"
    target.mkdir()

    def no_host(*_arguments):
        raise AssertionError("no observer may start")
    before = _below_this_process()
    left: set[int] = set()
    try:
        with pytest.raises(_Stop):
            _demo.run_demo(os.fsencode(target), _rtinode_environ(), modules,
                           rtinode=str(native_executable("SYNAPSE_HLA_RTINODE")),
                           publisher=str(native_executable("SYNAPSE_HLA_PUBLISHER")),
                           start_host=no_host, check=_stop_at(call), synapse_cdm_version=None,
                           seams=seams)
        left = _below_this_process() - before
        assert left == set(), left
        assert _refused(port)
        assert list(target.iterdir()) == []
    finally:
        _kill_and_reap(left | (_below_this_process() - before))


def _below_this_process() -> set[int]:
    """The processes below this test's process, but the `ps` that lists them."""
    return {pid for pid, command in descendant_commands(os.getpid()).items()
            if not command.startswith("/bin/ps ")}


# ---------------------------------------------- A-NO-PUBLISH, A-NO-CREATE: the decorator, for real

def harness_shim(directory: pathlib.Path, log: pathlib.Path) -> pathlib.Path:
    """`sc-hla-federate` for the demo: the harness playing real-rti (the observer wrapped in the
    recording decorator, connected to the demo's own rtinode), with the host's arguments."""
    harness = native_executable("SYNAPSE_HLA_HARNESS")
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "sc-hla-federate"
    command = " ".join(shlex.quote(part) for part in [
        str(harness), "--scenario=real-rti", f"--fom-dir={fom_modules()[0].parent}",
        f"--log={log}"])
    shim.write_text(f'#!/bin/sh\nexec {command} "$@"\n', encoding="utf-8")
    shim.chmod(0o700)
    return shim


#: NAT-07 (b): the ten services an observer may call; every other one is publication, ownership,
#: time, DDM, save/restore, interaction or federation control.
ALLOWED = {"connect", "joinFederationExecution", "getObjectClassHandle", "getAttributeHandle",
           "getAttributeName", "subscribeObjectClassAttributes", "requestAttributeValueUpdate",
           "evokeMultipleCallbacks", "resignFederationExecution", "disconnect"}


@pytest.mark.rti
@case("A-NO-PUBLISH", "A-NO-CREATE", "G-R39", "G-R10", "G-R12", "G-R13", "G-R14",
      paragraphs=("SPEC:211", "SPEC:50", "SPEC:56", "SPEC:62"))
def test_the_observer_of_a_real_demo_session_calls_no_publication_or_control_service(tmp_path):
    """A-NO-PUBLISH and A-NO-CREATE with the real RTI: the demo runs with the observer's own code
    wrapped in the recording decorator (harness scenario real-rti) as its worker, against its
    rtinode and the publisher's federations. The demo still passes every checkpoint, and the
    decorator's log of each of the two sessions holds only NAT-07's ten services: connect to the
    demo's endpoint, join with no module (never create, never inject a FOM), resolve and
    subscribe the four attributes at PhysicalEntity, request the discovered object's values once,
    evoke with (0.0, 0.05), resign NO_ACTION and disconnect - zero publication, update, deletion,
    interaction or federation control calls (SPEC:211). The publisher destroyed each federation
    after the observer resigned. Across processes (the carried G-R10/G-R12/G-R13/G-R14 clauses):
    discovery, reflection and removal delivered from the publisher through rtinode, receive
    ordered (R13), and the SIGTERM stop of a worker joined to a real federation, COMPLETE."""
    log = tmp_path / "bin" / "decorator.log"
    shim = harness_shim(tmp_path / "bin", log)
    ran, document = run_demo(tmp_path, extra={"SYNAPSE_HLA_WORKER": str(shim)}, creates=("bin",))
    assert ran.code == 0 and document["status"] == "PASS", document["failures"]
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    starts = [e for e in entries if e.get("event") == "start"]
    assert len(starts) == 2
    sessions = []
    for start_entry in starts:
        index = entries.index(start_entry)
        following = [entries.index(e) for e in starts if entries.index(e) > index]
        end = following[0] if following else len(entries)
        sessions.append([e for e in entries[index:end] if "call" in e])
    port = document["rtinode"]["port"]
    for run, calls in zip(document["runs"], sessions):
        assert all(c["call"] in ALLOWED and "forbidden" not in c for c in calls), calls
        names = [c["call"] for c in calls if c["call"] != "evokeMultipleCallbacks"]
        assert names == ["connect", "joinFederationExecution", "getObjectClassHandle"] + \
            ["getAttributeHandle"] * 4 + ["subscribeObjectClassAttributes",
                                          "requestAttributeValueUpdate",
                                          "resignFederationExecution", "disconnect"]
        assert calls[0] == {"call": "connect", "designator": f"rti://127.0.0.1:{port}",
                            "model": "HLA_EVOKED"}
        assert calls[1] == {"call": "joinFederationExecution", "federate_name": "SC_OBSERVER",
                            "federate_type": "SynapseCommandObserver",
                            "federation": run["federation_name"], "modules": 0}
        assert {"action": "NO_ACTION", "call": "resignFederationExecution"} in calls
        assert all((c["minimum"], c["maximum"]) == (0.0, 0.05) for c in calls
                   if c["call"] == "evokeMultipleCallbacks")
        assert run["publisher"]["destroyed"] and run["session"]["status"] == "COMPLETE"
        frames = [r for r in lines(tmp_path / "demo" / run["directory"] / "capture.jsonl")[1:]
                  if r["type"] == "frame"]
        assert [f["event"]["type"] for f in frames] == [
            "generation_start", "discover"] + ["reflect"] * (4 + len(run["refresh_seqs"])) + [
            "remove", "generation_end"]
        assert frames[-1]["event"] == {"type": "generation_end", "reason": "stop"}
        assert {(f["event"]["sent_order"], f["event"]["received_order"]) for f in frames
                if f["event"]["type"] == "reflect"} == {("RECEIVE", "RECEIVE")}
    assert_nothing_left(document)


def descendants(root: int) -> set[int]:
    """Every process below `root` right now (ps, by parent pid)."""
    table = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                           text=True, check=True).stdout.split()
    children: dict[int, list[int]] = {}
    for pid, ppid in zip(table[0::2], table[1::2]):
        children.setdefault(int(ppid), []).append(int(pid))
    out, todo = set(), [root]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in out:
                out.add(child)
                todo.append(child)
    return out


@pytest.mark.rti
@case("G-R39", "G-R36", paragraphs=("SPEC:211", "SPEC:184"))
@pytest.mark.parametrize("signum", [2, 15], ids=["SIGINT", "SIGTERM"])
def test_a_demo_stopped_by_a_signal_stops_everything_it_started_and_removes_its_directory(
        tmp_path, signum):
    """SPEC:184 and SPEC:211: SIGINT or SIGTERM while the main run's observer is joined stops the
    demo at its next turn: the observer's host is stopped in order, the publisher resigns and
    destroys its federation, rtinode is stopped, every process the demo started (rtinode, the
    publisher, the host and its worker, all seen below the command while it ran) is gone, --out is
    removed and the exit is 128 plus the signal number with nothing printed (the CLI's rule for a
    command stopped before it finished)."""
    args = ["demo", "--out", tmp_path / "demo"]
    proc, before = start(tmp_path, *args, env=demo_environment(tmp_path))
    capture = tmp_path / "demo" / "main" / "capture.jsonl"
    deadline = time.monotonic() + 60
    while not (capture.exists() and b'"generation_start"' in capture.read_bytes()):
        assert proc.poll() is None and time.monotonic() < deadline
        time.sleep(0.01)
    started = descendants(proc.pid)
    assert len(started) >= 4, started
    proc.send_signal(signum)
    ran = finish(tmp_path, proc, before, args, creates=["sockets.log"], ended="interrupted")
    assert ran.code == 128 + signum
    assert not (tmp_path / "demo").exists()
    assert all(process_gone(pid) for pid in started), started


def _hostile_publisher_rows() -> dict[str, list[bytes]]:
    """Stand-in publishers' lines: one hostile line, after the valid ones it needs to be read at
    all; `{FED}` stands for the federation name of the stand-in's arguments."""
    modules = json.dumps({"event": "modules", "sha256": _pins()},
                         separators=(",", ":")).encode("ascii")
    created = b'{"event":"created","federation":"{FED}"}'
    ready = b'{"class":"' + GV.encode("ascii") + \
        b'","event":"ready","object_name":"SYNTHETIC-001","objects":1}'
    return {
        "modules-not-a-map": [b'{"event":"modules","sha256":[1]}'],
        "modules-bad-digest": [b'{"event":"modules","sha256":{"RPR-Base_v2.0.xml":"zz"}}'],
        "ready-class-number": [modules, created, b'{"class":123,"event":"ready",'
                               b'"object_name":"SYNTHETIC-001","objects":1}',
                               b'{"barrier":0,"event":"waiting"}'],
        "waiting-true": [modules, created, ready, b'{"barrier":true,"event":"waiting"}'],
        "failure-long-stage": [b'{"event":"failure","reason":"ok","stage":"' + b"s" * 5000
                               + b'"}'],
        "failure-long-reason": [b'{"event":"failure","reason":"' + b"r" * 100000
                                + b'","stage":"s"}'],
        "failure-bidi": [b'{"event":"failure","reason":"barrier\\u202etimeout",'
                         b'"stage":"barrier"}'],
        "failure-lone-surrogate": [b'{"event":"failure","reason":"\\ud800","stage":"barrier"}'],
        "failure-nested": [b'{"event":"failure","reason":{"a":[1,2]},"stage":null}'],
        "nesting": [b'{"event":"modules","sha256":' + b"[" * 100000 + b"]" * 100000 + b"}"],
    }


def hostile_publisher(directory: pathlib.Path, lines: list[bytes]) -> pathlib.Path:
    """A stand-in `sc-hla-publisher`: one Python process (isolated, so no guard or package is
    imported), answering --version exactly; otherwise it writes `lines` with its federation name
    put in, then sleeps until the demo stops it by its PID."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "events").write_bytes(b"\n".join(lines) + b"\n")
    script = directory / "sc-hla-publisher"
    script.write_text(
        f"#!{sys.executable} -I\n"
        "import os, sys, time\n"
        "if sys.argv[1:] == ['--version']:\n"
        f"    os.write(1, {(VERSION + chr(10)).encode('ascii')!r})\n"
        "    sys.exit(0)\n"
        "federation = sys.argv[2].split('=', 1)[1].encode('ascii')\n"
        f"data = open({str(directory / 'events')!r}, 'rb').read()\n"
        "os.write(1, data.replace(b'{FED}', federation))\n"
        "time.sleep(30)\n", encoding="utf-8")
    script.chmod(0o700)
    return script


@pytest.mark.rti
@case("G-R38", "G-R39", paragraphs=("SPEC:207", "SPEC:211"))
@pytest.mark.parametrize("row", sorted(_hostile_publisher_rows()))
def test_a_publisher_writing_hostile_events_fails_the_demo_cleanly(tmp_path, row):
    """R8-r1-F3 through the command line, with the real rtinode and worker: a publisher (any
    executable SYNAPSE_HLA_PUBLISHER names that answers --version exactly) that writes a hostile
    event - wrong types, a broken digest map, oversize or bidirectional or lone-surrogate text,
    nesting far beyond any bound - fails the demo cleanly: exit 5, no traceback, the summary and
    demo.json valid, status FAIL with the one publisher failure of fixed text and no code, none
    of the line's values in demo.json, the clean-up PASS and nothing left behind (every PID gone,
    the port closed)."""
    script = hostile_publisher(tmp_path / "bin", _hostile_publisher_rows()[row])
    ran, document = run_demo(tmp_path, extra={"SYNAPSE_HLA_PUBLISHER": str(script)},
                             creates=("bin",))
    assert ran.code == 5, (ran.code, ran.stderr[-2000:])
    assert ran.summary["result"] == {
        "status": "FAIL", "runs": [{"name": "main", "result": "FAIL", "failed_checkpoints": []}],
        "failures": [{"stage": "publisher", "run": "main"}], "cleanup": "PASS"}
    assert ran.diagnostics == [] and ran.summary["codes"] == []
    assert not list(DEMO_SCHEMA.iter_errors(document))
    assert document["status"] == "FAIL" and document["failures"] == [
        {"stage": "publisher", "reason": _demo._NOT_AN_EVENT, "run": "main", "code": None}]
    [run] = document["runs"]
    assert run["publisher"]["failure"] is None
    assert run["publisher"]["registered_class"] in (None, GV)
    assert run["publisher"]["module_sha256"] in (None, _pins())
    assert document["cleanup"]["result"] == "PASS"
    assert_nothing_left(document)


def descendant_commands(root: int) -> dict[int, str]:
    """Every process below `root` right now, with its command line (ps)."""
    table = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True,
                           text=True, check=True).stdout.splitlines()
    rows = [line.split(None, 2) for line in table]
    commands = {int(r[0]): (r[2] if len(r) == 3 else "") for r in rows if r}
    return {pid: commands[pid] for pid in descendants(root) if pid in commands}


@pytest.mark.rti
@case("G-R39", "G-R36", paragraphs=("SPEC:211", "SPEC:184"))
@pytest.mark.parametrize("signum", [2, 15], ids=["SIGINT", "SIGTERM"])
def test_a_demo_stopped_while_its_rtinode_starts_stops_it_and_removes_its_directory(
        tmp_path, signum):
    """R8-r1-F1 through the command line: SIGINT or SIGTERM sent as soon as rtinode is seen below
    the command, inside its start-up window and before any run began (no run directory exists
    yet), stops the demo at its next turn: rtinode is ended by its PID, every process seen below
    the command is gone, --out is removed, and the exit is 128 plus the signal number with nothing
    printed. The test above signals only once the observer is joined, after this window."""
    args = ["demo", "--out", tmp_path / "demo"]
    rtinode = str(native_executable("SYNAPSE_HLA_RTINODE"))
    proc, before = start(tmp_path, *args, env=demo_environment(tmp_path))
    seen: dict[int, str] = {}
    try:
        deadline = time.monotonic() + 60
        while not any(c.startswith(f"{rtinode} -i 127.0.0.1:") for c in seen.values()):
            assert proc.poll() is None and time.monotonic() < deadline, seen
            seen.update(descendant_commands(proc.pid))
        no_run_yet = not (tmp_path / "demo" / "main").exists()
        proc.send_signal(signum)
        ran = finish(tmp_path, proc, before, args, creates=["sockets.log"], ended="interrupted")
        assert no_run_yet
        assert ran.code == 128 + signum
        assert not (tmp_path / "demo").exists()
        assert all(process_gone(pid) for pid in seen), seen
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        _kill_and_reap([pid for pid in seen if not process_gone(pid, within_s=0)])


#: The record `tests/demorecord/sitecustomize.py` writes of a run's end, for the two ways the
#: observer's session can end in order after a stop that reached its host at the fork (OPS-15 and
#: R14, written out from host.py's rules): the stop was still pending when the session began, so
#: no worker ever started and the host closed the capture with its own E_RTI_CONNECT diagnostic
#: in generation 0 and a FAILED footer naming it; or, on a machine slow enough that the stop came
#: after the observer had joined, the session ended with generation_end stop and a COMPLETE
#: footer.
STOPPED_BEFORE_THE_JOIN = [["header"], ["diagnostic", 0, "E_RTI_CONNECT"],
                           ["footer", "FAILED", "E_RTI_CONNECT"]]


def slow_version_worker(directory: pathlib.Path) -> pathlib.Path:
    """`sc-hla-federate` whose `--version` answers half a second late (then the real worker
    answers it), as a slow disk or a loaded machine stretches the host's pre-flight; any other
    argument vector runs the real worker at once."""
    worker = native_executable("SYNAPSE_HLA_WORKER")
    directory.mkdir(parents=True)
    shim = directory / "sc-hla-federate"
    shim.write_text('#!/bin/sh\nif [ "$*" = "--version" ]; then sleep 0.5; fi\n'
                    f'exec {shlex.quote(str(worker))} "$@"\n', encoding="utf-8")
    shim.chmod(0o700)
    return shim


@pytest.mark.rti
@case("G-R39", "G-R36", "G-R14", paragraphs=("SPEC:211", "SPEC:184"))
@pytest.mark.parametrize("signum", [2, 15], ids=["SIGINT", "SIGTERM"])
def test_a_demo_stopped_at_its_observer_hosts_fork_stops_the_observer_in_order(tmp_path,
                                                                               signum):
    """CR-R8-06 and SPEC:211 (observer, then publisher, then rtinode, each in order), R14's
    orderly stop and SPEC:184, at the one moment final review finding F-host-01 found them
    broken: SIGINT or SIGTERM sent to `synapse-hla demo` as soon as its forked observer host (a
    child with the command's own argument vector) is seen, while the host's pre-flight is still
    asking a slowed worker for its version. The demo sends the host its SIGTERM at once; the
    host holds it blocked, not ignored, until the session's handlers exist, so the session stops
    in order: the host exits 0 with its capture closed by a footer, COMPLETE or the stop's
    FAILED E_RTI_CONNECT (OPS-15), before --out is removed; the publisher then resigns and
    destroys its federation (exit status 1, its status for a stop, publisher.cpp), and the
    command ends well inside one deadline of the signal (R14's 10 s: zero whole periods), with
    128 plus the signal number, nothing printed, --out removed and every process gone. A host
    that discarded the stop is SIGKILLed after two deadlines with no footer and the publisher's
    destroy fails (the R9 tree: host -9, no footer, destroyed false, two periods)."""
    record = tmp_path / "record.jsonl"
    slow = slow_version_worker(tmp_path / "slow")
    env = demo_environment(tmp_path, {"SYNAPSE_HLA_WORKER": str(slow),
                                      "SC_HLA_DEMO_RECORD": str(record)})
    env["PYTHONPATH"] = os.pathsep.join([str(TESTS_DIR / "demorecord"), str(SRC)])
    args = ["demo", "--out", tmp_path / "demo"]
    own = " ".join(command_line(*args))
    proc, before = start(tmp_path, *args, env=env)
    seen: dict[int, str] = {}
    try:
        deadline = time.monotonic() + 60
        while own not in seen.values():
            assert proc.poll() is None and time.monotonic() < deadline, seen
            seen.update(descendant_commands(proc.pid))
        proc.send_signal(signum)
        signalled = time.monotonic_ns()
        ran = finish(tmp_path, proc, before, args, creates=["sockets.log", "record.jsonl"],
                     ended="interrupted")
        ended = time.monotonic_ns()
        assert ran.code == 128 + signum
        runs = [json.loads(line) for line in record.read_text(encoding="ascii").splitlines()]
        assert [r["run"] for r in runs] == ["main"]
        run = runs[0]
        assert (run["host_reaped"], run["host_status"]) == (True, 0), run
        if run["workers"] == 0:
            assert run["capture"] == STOPPED_BEFORE_THE_JOIN, run
        else:
            assert run["capture"][:2] == [["header"], ["generation_start", 1]], run
            assert run["capture"][-2:] == [["generation_end", 1, "stop"],
                                           ["footer", "COMPLETE", None]], run
        assert (run["destroyed"], run["publisher_status"]) == (True, 1), run
        assert (ended - signalled) // _demo.V1.deadline_ns == 0
        assert not (tmp_path / "demo").exists()
        assert all(process_gone(pid) for pid in seen), seen
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        _kill_and_reap([pid for pid in seen if not process_gone(pid, within_s=0)])
