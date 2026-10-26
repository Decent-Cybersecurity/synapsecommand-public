"""`replay(capture_path, output_dir, *, allow_prefix=False)`: R35, SPEC:164-168, SPEC:293, R17.

The oracle is the bundle's: the bundled capture replays to `expected.observations.jsonl` byte for
byte, with the checkpoints of `session-checkpoints.json`, and the digest of that output is the
literal D-19 pins on every interpreter. Refusals are judged by their code and path (CR-L01) and
by what is left on disk: nothing, for a refused capture, and no partial directory for a fault
injected after the directory was made. Crafted captures come from the tests' own capture builder;
every record a replay writes is read back and held to the contract checker of `hla_support`.
"""

import copy
import dataclasses
import hashlib
import json
import os
import pathlib
import random
import stat
import sys
import time

import pytest

import synapse_hla
from hla_support import (
    FIXTURE_HEADER_SHA256, CaptureBuilder, Scenario, capture_bytes, case, chain_lines,
    check_frame_records,
    check_stream, contract_json, event_diagnostic, event_discover, event_generation_end,
    event_generation_start, event_reflect, example_json, fixture_capture_records,
    fixture_json, fixture_jsonl, header_with, local_validator, package_bytes, positive_hex,
    reduce_checked, strict_json, without_completion,
)
from synapse_hla import HlaError, reducer

replay = synapse_hla.replay
#: The module (the package attribute `replay` is the function and shadows it).
REPLAY = sys.modules["synapse_hla.replay"]

#: D-19: the SHA-256 of the bundled expected observation stream, the replay output of the
#: bundled capture on every interpreter (FACTS.md, reducer; the scout prototype and the
#: verifier both observed it, and `expected.observations.jsonl` hashes to it).
OBSERVATIONS_SHA256 = "d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125"
#: SHA-256 of zero bytes: the diagnostics file of a session without a diagnostic.
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
FILES = ["capture.jsonl", "diagnostics.jsonl", "observations.jsonl"]
SECOND = 1_000_000_000
HEX = positive_hex()
FULL = (("EntityIdentifier", HEX["ID-123"]), ("EntityType", HEX["TYPE-PLATFORM"]),
        ("ForceIdentifier", HEX["FORCE-1"]), ("Spatial", HEX["SPATIAL-2"]))


def capture_data() -> bytes:
    return package_bytes("fixtures", "session.capture.jsonl")


def expected_lines() -> list[bytes]:
    return [raw + b"\n" for raw, _ in fixture_jsonl("expected.observations.jsonl")]


def write(tmp_path: pathlib.Path, data: bytes, name: str = "capture.jsonl") -> pathlib.Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def records_of(run: pathlib.Path) -> list[dict]:
    """The records a replay wrote, each line parsed strictly and checked to be canonical."""
    data = (run / "observations.jsonl").read_bytes()
    out = []
    for line in data.splitlines():
        record = strict_json(line)
        assert reducer.output_line(record) == line + b"\n"
        out.append(record)
    return out


def held_to_the_contract(run: pathlib.Path, capture_path: pathlib.Path) -> list[dict]:
    """The replay's records grouped by frame, each frame's records held to `check_frame_records`
    against the capture's own frame, the stream to `check_stream`."""
    records = records_of(run)
    # Only whole lines: a prefix replay's capture may end inside one.
    whole = capture_path.read_bytes().split(b"\n")[1:-1]
    frames = {r["seq"]: r for r in (strict_json(line) for line in whole)
              if r.get("type") == "frame"}
    grouped = {}
    for record in records:
        grouped.setdefault(record["seq"], []).append(record)
    for seq, group in grouped.items():
        check_frame_records(frames[seq], group)
    check_stream(list(grouped.values()))
    return records


@pytest.fixture(scope="module")
def summary_validator():
    # The summary's `verification` is the verify report (CR-L08), which refers to the footer
    # schema: both resolve through the tests' own registry of the packaged schemas.
    return local_validator("replay-summary.schema.json")


def summary_of(path, out, summary_validator, **options) -> dict:
    summary = replay(path, out, **options)
    errors_ = list(summary_validator.iter_errors(summary))
    assert not errors_, errors_[0].message
    for name in FILES:
        data = (out / name).read_bytes()
        assert summary["files"][name] == {"bytes": len(data),
                                          "sha256": hashlib.sha256(data).hexdigest()}
    return summary


def refused(call) -> HlaError:
    with pytest.raises(HlaError) as info:
        call()
    assert type(info.value) is HlaError
    return info.value


# ============================================================================ the oracle

@case("A-REPLAY", "G-R35", paragraphs=("SPEC:166",))
@case("G-R45", paragraphs=("SPEC:287",))
def test_the_bundled_capture_replays_to_the_bundled_records(tmp_path, summary_validator):
    """A-REPLAY and R35: replay of the bundled capture writes `expected.observations.jsonl` byte
    for byte (its SHA-256 is D-19's literal, the same on 3.11, 3.12 and 3.14, which check.sh
    runs), an empty diagnostics file, and a byte copy of the capture (SPEC:166: raw capture
    reproduction is byte-identical; the capture stays beside what was made of it). The summary
    is the literal below: 8 frames, 4 snapshots (two of them suppressed by MISSING_SPATIAL), 2
    upserts, 1 removed, no diagnostic, and the verify report of the whole file (CR-L08): its
    header digest is the tests' literal of the bundled header, its chain head and footer the
    bundled footer's own, its verified bytes the file's length."""
    path = write(tmp_path, capture_data())
    out = tmp_path / "run"
    summary = summary_of(path, out, summary_validator)
    assert (out / "observations.jsonl").read_bytes() == b"".join(expected_lines())
    assert hashlib.sha256((out / "observations.jsonl").read_bytes()).hexdigest() == \
        OBSERVATIONS_SHA256
    assert (out / "capture.jsonl").read_bytes() == capture_data()
    pins = {e["path"]: e for e in contract_json("vendored-pins.json")["files"]}
    capture_pin = pins["src/synapse_hla/fixtures/session.capture.jsonl"]
    assert summary == {
        "replay_summary_version": 1, "status": "COMPLETE", "capture_complete": True,
        "verified_seq": 9, "frames": 8,
        "records": {"diagnostic": 0, "snapshot": 4, "upsert": 2, "removed": 1, "invalidated": 0},
        "suppressions": {"MISSING_ENTITY_IDENTIFIER": 0, "MISSING_ENTITY_TYPE": 0,
                         "MISSING_SPATIAL": 2, "INVALID_ENTITY_IDENTIFIER": 0,
                         "INVALID_ENTITY_TYPE": 0, "INVALID_SPATIAL": 0,
                         "INVALID_FORCE_IDENTIFIER": 0, "NULL_ID": 0, "QUARANTINED": 0,
                         "TIME_UNRESOLVED": 0, "GEOGRAPHY_UNPROJECTABLE": 0},
        "errors": {}, "warnings": {},
        "verification": {
            "verify_report_version": 1, "status": "COMPLETE", "code": None, "path": None,
            "message": None, "verified_seq": 9, "verified_bytes": capture_pin["bytes"],
            "frames": 8, "header_sha256": FIXTURE_HEADER_SHA256,
            "last_sha256": fixture_capture_records()[-1]["sha256"], "capture_complete": True,
            "footer": fixture_capture_records()[-1]},
        "files": {"capture.jsonl": {"bytes": capture_pin["bytes"],
                                    "sha256": capture_pin["sha256"]},
                  "observations.jsonl": {"bytes": 10822, "sha256": OBSERVATIONS_SHA256},
                  "diagnostics.jsonl": {"bytes": 0, "sha256": EMPTY_SHA256}},
    }
    held_to_the_contract(out, path)


@case("A-REPLAY", "G-R35")
def test_the_checkpoints_of_the_bundle(tmp_path):
    """A-REPLAY's expected checkpoints, read from `session-checkpoints.json`: the upserts at
    seq 5 and 6 with their revision, entity_id, position, motion and valid_from; snapshots at
    seq 3 to 6; the removal at seq 7; no invalidation and no diagnostic."""
    checkpoints = fixture_json("session-checkpoints.json")
    replay(write(tmp_path, capture_data()), tmp_path / "run")
    records = records_of(tmp_path / "run")
    upserts = [r for r in records if r["kind"] == "upsert"]
    assert len(upserts) == len(checkpoints["upserts"])
    for got, want in zip(upserts, checkpoints["upserts"]):
        entity = got["payload"]
        assert (got["seq"], got["revision"], got["entity_id"]) == (want["seq"], want["revision"],
                                                                   want["entity_id"])
        assert (entity["position"]["lat"], entity["position"]["lon"],
                entity["position"]["alt_m"]) == (want["lat"], want["lon"], want["alt_m"])
        assert (entity["kinematics"]["speed_mps"], entity["kinematics"]["course_deg"],
                entity["kinematics"]["climb_mps"]) == (want["speed_mps"], want["course_deg"],
                                                       want["climb_mps"])
        assert entity["valid_from"] == want["valid_from"]
    assert [r["seq"] for r in records if r["kind"] == "snapshot"] == checkpoints["snapshots_at"]
    assert [r["seq"] for r in records if r["kind"] == "removed"] == [checkpoints["removed_at"]]
    assert sum(r["kind"] == "invalidated" for r in records) == checkpoints["invalidations"]
    assert sum(r["kind"] == "diagnostic" for r in records) == checkpoints["diagnostics"]


@case("A-REPLAY", "G-R35", paragraphs=("SPEC:168",))
def test_two_replays_write_identical_directories(tmp_path):
    """A-REPLAY, R35: two replays of one capture by one build give byte-identical files and
    equal summaries (no clock, no randomness, nothing of the run itself in them)."""
    path = write(tmp_path, capture_data())
    first, second = replay(path, tmp_path / "a"), replay(path, tmp_path / "b")
    assert first == second
    assert sorted(os.listdir(tmp_path / "a")) == sorted(os.listdir(tmp_path / "b")) == FILES
    for name in FILES:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


# ============================================================================ the run directory

def _session_with_diagnostics() -> Scenario:
    """A session with captured and derived diagnostics: an existing-mode capture (W_FOM_
    UNVERIFIED at each start), a reconnect with a captured E_RTI_CONNECT, an unknown token, an
    atomic rejection and a repair."""
    existing = header_with(mode="existing", profile_declaration="external-fom-unverified")
    return (Scenario(existing).frame(0, 0, event_diagnostic("E_RTI_CONNECT"))
            .frame(1, 0, event_generation_start()).frame(1, 0, event_discover("o1"))
            .frame(1, SECOND, event_reflect("o1", FULL))
            .frame(1, SECOND, event_reflect("o9", (("ForceIdentifier", "01"),)))
            .frame(1, 2 * SECOND, event_reflect("o1", (("EntityType", "00"),)))
            .frame(1, 3 * SECOND, event_reflect("o1", (("EntityType", HEX["TYPE-PLATFORM"]),)))
            .frame(1, 3 * SECOND, event_generation_end("connection_lost"))
            .frame(0, 4 * SECOND, event_diagnostic("E_RTI_CONNECT"))
            .frame(2, 5 * SECOND, event_generation_start())
            .frame(2, 5 * SECOND, event_generation_end()).footer())


@case("G-R35", paragraphs=("SPEC:168",))
def test_the_run_directory_holds_the_three_files_and_diagnostics_is_their_subsequence(
        tmp_path, summary_validator):
    """SPEC:168, OPS-20: the directory holds capture.jsonl, observations.jsonl and
    diagnostics.jsonl and nothing else (run.json is the command line's, R6), and
    diagnostics.jsonl is exactly the diagnostic lines of observations.jsonl, byte for byte, in
    order. OPS-17: the directory is mode 0700 and the files 0600. The summary counts what the
    files hold."""
    path = _session_with_diagnostics().write(tmp_path / "capture.jsonl")
    out = tmp_path / "run"
    summary = summary_of(path, out, summary_validator)
    assert sorted(os.listdir(out)) == FILES
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o700
    assert [stat.S_IMODE(os.stat(out / n).st_mode) for n in FILES] == [0o600] * 3
    lines = (out / "observations.jsonl").read_bytes().splitlines(keepends=True)
    diagnostic_lines = [line for line in lines if json.loads(line)["kind"] == "diagnostic"]
    assert (out / "diagnostics.jsonl").read_bytes() == b"".join(diagnostic_lines)
    records = held_to_the_contract(out, path)
    codes = [r["payload"]["code"] for r in records if r["kind"] == "diagnostic"]
    assert codes == ["E_RTI_CONNECT", "W_FOM_UNVERIFIED", "E_UNKNOWN_OBJECT",
                     "E_ATTRIBUTE_LENGTH", "E_RTI_CONNECT", "W_FOM_UNVERIFIED"]
    assert summary["errors"] == {"E_ATTRIBUTE_LENGTH": 1, "E_UNKNOWN_OBJECT": 1,
                                 "E_RTI_CONNECT": 2}
    assert summary["warnings"] == {"W_FOM_UNVERIFIED": 2}
    assert summary["records"] == {"diagnostic": 6, "snapshot": 3, "upsert": 2, "removed": 0,
                                  "invalidated": 2}
    assert summary["suppressions"]["INVALID_ENTITY_TYPE"] == 1
    assert sum(summary["suppressions"].values()) == 1


# ============================================================================ refusals

def _flipped_hex(data: bytes) -> bytes:
    """A-HASH as R2 binds it: one hex digit of the seq-5 Spatial changed (02 -> 03), digests
    left as they were."""
    lines = data.split(b"\n")
    lines[5] = lines[5].replace(b'"hex":"0200', b'"hex":"0300', 1)
    return b"\n".join(lines)


def _refusals():
    data = capture_data()
    lines = data.split(b"\n")[:-1]
    records = fixture_capture_records()
    gap = copy.deepcopy(records)
    gap[4]["seq"] = 5
    gap_lines = chain_lines(gap[:5]) + chain_lines(records)[5:]
    bad_epoch = copy.deepcopy(records)
    bad_epoch[0]["config"]["time_policy"]["epoch"] = "2026-02-30T00:00:00.000000Z"
    return [
        ("hash", _flipped_hex(data), "E_CAPTURE_HASH", "line:6#/sha256"),
        ("sequence", capture_bytes(gap_lines), "E_CAPTURE_SEQUENCE", "line:5#/seq"),
        ("not-canonical", data.replace(b'{"elapsed_ns":"0","event":{"name"',
                                       b'{"elapsed_ns": "0","event":{"name"', 1),
         "E_CAPTURE_SCHEMA", "line:3"),
        ("header-config", capture_bytes(chain_lines(bad_epoch)), "E_CONFIG",
         "line:1#/config/time_policy/epoch"),
        ("bytes-after-the-footer", data + lines[-1] + b"\n", "E_CAPTURE_SCHEMA", "line:11"),
        ("effective-time-past-9998", _overflowing(), "E_CONFIG",
         "line:1#/config/time_policy/epoch"),
    ]


def _overflowing() -> bytes:
    """RED-V-01: one second before the end of 9998, a frame at 2 s names an effective time past
    9998-12-31T23:59:59.999999Z (SPEC:289)."""
    header = header_with(time_policy={"mode": "external_elapsed",
                                      "epoch": "9998-12-31T23:59:59.000000Z", "basis": "b"})
    return (CaptureBuilder(header).frame(1, 0, event_generation_start())
            .frame(1, 0, event_discover("o1")).frame(1, 2 * SECOND, event_reflect("o1", FULL))
            .frame(1, 2 * SECOND, event_generation_end()).footer().data())


@case("G-R17", "G-R15", "A-HASH", "G-R35")
@pytest.mark.parametrize("allow_prefix", [False, True])
@pytest.mark.parametrize("what,data,code,path", _refusals(), ids=[r[0] for r in _refusals()])
def test_an_invalid_capture_is_refused_with_or_without_allow_prefix(tmp_path, what, data, code,
                                                                    path, allow_prefix):
    """OPS-16, RED-06, R15's carried A-HASH clause: a hash, sequence, schema or configuration
    fault refuses replay with the code and path verification reports, whatever allow_prefix
    says, and nothing is written: the output directory does not exist afterwards (R35)."""
    capture_path = write(tmp_path, data)
    report = synapse_hla.verify_capture(capture_path)
    assert (report["status"], report["code"], report["path"]) == ("INVALID", code, path)
    error = refused(lambda: replay(capture_path, tmp_path / "run", allow_prefix=allow_prefix))
    assert (error.code, error.path) == (code, path)
    assert not (tmp_path / "run").exists() and sorted(os.listdir(tmp_path)) == ["capture.jsonl"]


def _cut_inside_line_8() -> bytes:
    data = capture_data()
    ends = [i for i, b in enumerate(data) if b == 0x0A]
    return data[:ends[6] + 1 + 40]


@case("A-TRUNCATED", "A-PREFIX", "G-R17", "G-R35")
def test_a_truncated_capture_is_refused_and_replays_as_a_prefix_on_request(tmp_path,
                                                                           summary_validator):
    """A-TRUNCATED, A-PREFIX and R17's carried clause. The capture cut 40 bytes into line 8
    (seq 7): normal replay refuses it, E_CAPTURE_INCOMPLETE at `line:8`, writing nothing. With
    allow_prefix the verified prefix (seq 1 to 6) is replayed: the records are the bundled ones
    of seq 3 to 6 with every capture_complete false (the envelope's and, in the upserts,
    attributes.hla.capture_complete), the summary says INCOMPLETE and not complete, and
    capture.jsonl is the whole input file, its partial tail included."""
    data = _cut_inside_line_8()
    path = write(tmp_path, data)
    error = refused(lambda: replay(path, tmp_path / "run"))
    assert (error.code, error.path) == ("E_CAPTURE_INCOMPLETE", "line:8")
    assert not (tmp_path / "run").exists()
    summary = summary_of(path, tmp_path / "run", summary_validator, allow_prefix=True)
    assert (summary["status"], summary["capture_complete"], summary["verified_seq"],
            summary["frames"]) == ("INCOMPLETE", False, 6, 6)
    # CR-L08: the summary carries the verify report: stopped at line 8, inside it; verified are
    # the first seven lines (the header and seq 1 to 6), whose last digest is seq 6's.
    verification = dict(summary["verification"])
    assert type(verification.pop("message")) is str
    assert verification == {
        "verify_report_version": 1, "status": "INCOMPLETE", "code": "E_CAPTURE_INCOMPLETE",
        "path": "line:8", "verified_seq": 6, "verified_bytes": len(data) - 40, "frames": 6,
        "header_sha256": FIXTURE_HEADER_SHA256,
        "last_sha256": fixture_capture_records()[6]["sha256"], "capture_complete": False,
        "footer": None}
    records = records_of(tmp_path / "run")
    expected = [strict_json(line) for line in expected_lines()[:6]]
    assert [without_completion(r) for r in records] == [without_completion(r) for r in expected]
    assert {r["capture_complete"] for r in records} == {False}
    assert [r["payload"]["attributes"]["hla"]["capture_complete"] for r in records
            if r["kind"] == "upsert"] == [False, False]
    assert (tmp_path / "run" / "capture.jsonl").read_bytes() == data
    held_to_the_contract(tmp_path / "run", path)


@case("A-PREFIX", "G-R17")
def test_a_capture_without_its_footer_replays_whole_as_a_prefix(tmp_path, summary_validator):
    """RED-06: every frame verified but no footer: INCOMPLETE at `line:10`; as a prefix, all
    seven records, every one marked incomplete, and the copy is the whole file (no tail)."""
    data = b"".join(line + b"\n" for line in capture_data().split(b"\n")[:9])
    path = write(tmp_path, data)
    error = refused(lambda: replay(path, tmp_path / "run"))
    assert (error.code, error.path) == ("E_CAPTURE_INCOMPLETE", "line:10")
    summary = summary_of(path, tmp_path / "run", summary_validator, allow_prefix=True)
    assert (summary["status"], summary["verified_seq"], summary["capture_complete"]) == (
        "INCOMPLETE", 8, False)
    verification = summary["verification"]
    assert (verification["status"], verification["code"], verification["path"],
            verification["verified_seq"], verification["verified_bytes"],
            verification["last_sha256"], verification["footer"]) == (
        "INCOMPLETE", "E_CAPTURE_INCOMPLETE", "line:10", 8, len(data),
        fixture_capture_records()[8]["sha256"], None)
    records = records_of(tmp_path / "run")
    assert len(records) == 7 and {r["capture_complete"] for r in records} == {False}
    assert (tmp_path / "run" / "capture.jsonl").read_bytes() == data


def _failed_capture() -> bytes:
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start()).frame(1, 0, event_discover("o1"))
    builder.frame(1, SECOND, event_reflect("o1", FULL))
    builder.frame(1, SECOND, event_diagnostic("E_RTI_CONNECT", "the RTI went away"))
    builder.frame(1, SECOND, event_generation_end("connection_lost"))
    builder.footer("FAILED", "E_RTI_CONNECT", 1)
    return builder.data()


@case("A-PREFIX", "G-R17")
def test_a_failed_capture_is_refused_unless_replayed_as_a_prefix(tmp_path, summary_validator):
    """R17, OPS-16: a FAILED footer refuses normal replay (E_CAPTURE_INCOMPLETE at the footer's
    `/status`, `line:7#/status`: the footer is seq 6, line 7; proposed CR-new-R4-05) and is
    replayed whole with allow_prefix, every record marked incomplete and the summary FAILED."""
    path = write(tmp_path, _failed_capture())
    assert synapse_hla.verify_capture(path)["status"] == "FAILED"
    error = refused(lambda: replay(path, tmp_path / "run"))
    assert (error.code, error.path) == ("E_CAPTURE_INCOMPLETE", "line:7#/status")
    assert not (tmp_path / "run").exists()
    summary = summary_of(path, tmp_path / "run", summary_validator, allow_prefix=True)
    assert (summary["status"], summary["capture_complete"], summary["verified_seq"]) == (
        "FAILED", False, 6)
    footer = strict_json(path.read_bytes().split(b"\n")[6])
    assert summary["verification"] == {
        "verify_report_version": 1, "status": "FAILED", "code": None, "path": None,
        "message": None, "verified_seq": 6, "verified_bytes": len(path.read_bytes()),
        "frames": 5, "header_sha256": FIXTURE_HEADER_SHA256, "last_sha256": footer["sha256"],
        "capture_complete": False, "footer": footer}
    records = records_of(tmp_path / "run")
    assert [r["kind"] for r in records] == ["snapshot", "upsert", "diagnostic", "invalidated"]
    assert {r["capture_complete"] for r in records} == {False}


@case("G-R17")
@pytest.mark.parametrize("data,path", [
    (b"", "line:1"),
    (b'{"adapter_version":"1.0.0"', "line:1"),
], ids=["empty", "partial-header"])
def test_a_prefix_without_its_header_is_refused_even_with_allow_prefix(tmp_path, data, path):
    """Without the recorded configuration there is nothing to replay with (R35): an incomplete
    capture whose header did not verify is refused with or without allow_prefix."""
    capture_path = write(tmp_path, data)
    for allow in (False, True):
        error = refused(lambda: replay(capture_path, tmp_path / "run", allow_prefix=allow))
        assert (error.code, error.path) == ("E_CAPTURE_INCOMPLETE", path)
        assert not (tmp_path / "run").exists()


@case("G-R17")
def test_allow_prefix_on_a_complete_capture_changes_nothing(tmp_path):
    """RED-06: capture_complete is true for a COMPLETE capture verified to its end, whatever the
    flag: the output is the bundled stream itself."""
    replay(write(tmp_path, capture_data()), tmp_path / "run", allow_prefix=True)
    assert (tmp_path / "run" / "observations.jsonl").read_bytes() == b"".join(expected_lines())


def _with_pins(pins: dict) -> bytes:
    records = fixture_capture_records()
    records[0]["pins"] = pins
    return capture_bytes(chain_lines(records))


@case("G-R17", "G-R35", paragraphs=("SPEC:293",))
@pytest.mark.parametrize("change,path", [
    ("digest", "RPR-Base_v2.0.xml"),
    ("missing", "NOTICES.txt"),
    ("extra", "RPR-Extra_v2.0.xml"),
    ("empty", "CDM-LICENSE.txt"),
])
@case("G-R04", paragraphs=("SPEC:293",))
def test_replay_requires_the_packaged_pins(tmp_path, change, path):
    """SPEC:293, RED-V-03 and R17's carried clause: replay requires the header's pin map to be the
    packaged one, entry for entry, else E_DEPENDENCY_PIN under the file's name, before any
    output. Each capture is otherwise valid (rechained by the tests' builder), so verify accepts
    it: verify never compares pins (A.2)."""
    pins = dict(fixture_capture_records()[0]["pins"])
    if change == "digest":
        pins["RPR-Base_v2.0.xml"] = "0" * 64
    elif change == "missing":
        del pins["NOTICES.txt"]
    elif change == "extra":
        pins["RPR-Extra_v2.0.xml"] = "0" * 64
    else:
        pins = {}
    capture_path = write(tmp_path, _with_pins(pins))
    assert synapse_hla.verify_capture(capture_path)["status"] == "COMPLETE"
    error = refused(lambda: replay(capture_path, tmp_path / "run"))
    assert (error.code, error.path) == ("E_DEPENDENCY_PIN", path)
    assert not (tmp_path / "run").exists()


@case("G-R17", "G-R11", "G-R35", paragraphs=("SPEC:293",))
def test_replay_never_reads_or_contacts_the_recorded_endpoint_or_the_fom(tmp_path, monkeypatch):
    """SPEC:293: replay needs no RTI and no FOM file: a header naming a remote endpoint (allowed
    by allow_remote) replays under the socket guard of the offline group, with
    SYNAPSE_HLA_FOM_DIR unset (R11: nothing here proves a remote FOM; replay compares recorded
    digests, never files)."""
    monkeypatch.delenv("SYNAPSE_HLA_FOM_DIR", raising=False)
    records = fixture_capture_records()
    records[0]["config"].update(endpoint="rti://192.0.2.7:9", allow_remote=True)
    path = write(tmp_path, capture_bytes(chain_lines(records)))
    replay(path, tmp_path / "run")
    assert (tmp_path / "run" / "observations.jsonl").read_bytes().count(b"\n") == 7


# ========================================================================= the output path (OPS-17)

@case("G-R35")
@pytest.mark.parametrize("kind", ["directory", "file", "dangling-link", "link-to-directory"])
def test_an_existing_output_is_refused_and_left_alone(tmp_path, kind):
    """OPS-17, R35 ("writes to a new directory"): the final component must not exist, even as a
    dangling symbolic link: E_OUTPUT_EXISTS at `output_dir`, and what was there is untouched."""
    capture_path = write(tmp_path, capture_data())
    out = tmp_path / "out"
    if kind == "directory":
        out.mkdir()
        (out / "keep").write_bytes(b"k")
    elif kind == "file":
        out.write_bytes(b"k")
    elif kind == "dangling-link":
        out.symlink_to(tmp_path / "nowhere")
    else:
        (tmp_path / "target").mkdir()
        out.symlink_to(tmp_path / "target")
    error = refused(lambda: replay(capture_path, out))
    assert (error.code, error.path) == ("E_OUTPUT_EXISTS", "output_dir")
    if kind == "directory":
        assert os.listdir(out) == ["keep"]
    elif kind == "file":
        assert out.read_bytes() == b"k"
    elif kind == "dangling-link":
        assert out.is_symlink() and not (tmp_path / "nowhere").exists()
    else:
        assert os.listdir(tmp_path / "target") == []


@case("G-R35")
def test_output_and_capture_paths_that_name_nothing_are_e_io(tmp_path):
    """OPS-17: the parent must already exist (E_IO `output_dir`); a path the file-system encoding
    cannot write or one with a NUL byte names nothing (E_IO, CR-R2-17); a missing capture is
    E_IO `capture_path`. Wrong argument types are caller bugs (TypeError)."""
    capture_path = write(tmp_path, capture_data())
    for out in (tmp_path / "missing" / "run", str(tmp_path / "a\udc00b\ud800"),
                str(tmp_path / "nul\x00")):
        error = refused(lambda: replay(capture_path, out))
        assert (error.code, error.path) == ("E_IO", "output_dir")
    for source in (tmp_path / "absent.jsonl", str(tmp_path / "x\x00y"), tmp_path):
        error = refused(lambda: replay(source, tmp_path / "run"))
        assert (error.code, error.path) == ("E_IO", "capture_path")
    for bad in (1, None, 1.5):
        with pytest.raises(TypeError):
            replay(capture_path, bad)
    for flag in (1, "yes", None):
        with pytest.raises(TypeError):
            replay(capture_path, tmp_path / "run", allow_prefix=flag)
    assert sorted(os.listdir(tmp_path)) == ["capture.jsonl"]


def _two_faults():
    """Rows of the order test: (id, the capture's bytes or None for no capture at all, the
    output path, the refusal's code and path). The hash fault is A-HASH's (`_flipped_hex`); the
    wrong pins are a valid capture whose header names another RPR-Base digest (`_with_pins`)."""
    data = capture_data()
    pins = dict(fixture_capture_records()[0]["pins"])
    pins["RPR-Base_v2.0.xml"] = "0" * 64
    hash_fault = ("E_CAPTURE_HASH", "line:6#/sha256")
    return [
        ("nul-output-and-hash-fault", _flipped_hex(data), "nul", ("E_IO", "output_dir")),
        ("unencodable-output-and-hash-fault", _flipped_hex(data), "unencodable",
         ("E_IO", "output_dir")),
        ("nul-output-and-no-capture", None, "nul", ("E_IO", "output_dir")),
        ("hash-fault-and-existing-output", _flipped_hex(data), "existing", hash_fault),
        ("no-capture-and-existing-output", None, "existing", ("E_IO", "capture_path")),
        ("hash-fault-and-wrong-pins", _flipped_hex(_with_pins(pins)), "new", hash_fault),
        ("wrong-pins-and-existing-output", _with_pins(pins), "existing",
         ("E_DEPENDENCY_PIN", "RPR-Base_v2.0.xml")),
        ("hash-fault-alone", _flipped_hex(data), "new", hash_fault),
    ]


@case("G-R35")
@pytest.mark.parametrize("what,data,output,expected", _two_faults(),
                         ids=[row[0] for row in _two_faults()])
def test_two_faults_at_once_are_refused_in_the_stated_order(tmp_path, what, data, output,
                                                            expected):
    """CR-new-R4-06's order (review finding R4-r1-F4, item 6): the argument types, the output
    path's encodability, the whole capture (R35: validated before anything is written), the pins
    (RED-V-03), and only then the directory (OPS-17). With two faults at once the earlier step
    names the refusal, with or without allow_prefix: an output path with a NUL byte or a code
    point the file-system encoding cannot write is E_IO `output_dir` before a capture with a
    hash fault (alone, the same capture is E_CAPTURE_HASH `line:6#/sha256`) or a missing one is
    looked at; a hash fault and a missing capture come before an existing output and before the
    pins; wrong pins come before an existing output. Nothing is written or changed, and a wrong
    argument type is a caller bug (TypeError) whatever else is wrong."""
    capture_path = tmp_path / "capture.jsonl"
    if data is not None:
        capture_path.write_bytes(data)
    run = tmp_path / "run"
    out = {"nul": str(run) + chr(0), "unencodable": str(run) + chr(0xD800), "existing": run,
           "new": run}[output]
    if output == "existing":
        run.mkdir()
        (run / "keep").write_bytes(b"k")
    before = sorted(os.listdir(tmp_path))
    for allow_prefix in (False, True):
        error = refused(lambda: replay(capture_path, out, allow_prefix=allow_prefix))
        assert (error.code, error.path) == expected, allow_prefix
    assert sorted(os.listdir(tmp_path)) == before
    if output == "existing":
        assert os.listdir(run) == ["keep"] and (run / "keep").read_bytes() == b"k"
    with pytest.raises(TypeError):
        replay(capture_path, out, allow_prefix=1)
    with pytest.raises(TypeError):
        replay(capture_path, 1)
    assert sorted(os.listdir(tmp_path)) == before


# ============================================================================ no partial directory

def _counting(real, fault, after: int):
    calls = []

    def wrapper(*args, **kwargs):
        calls.append(1)
        if len(calls) == after:
            raise fault
        return real(*args, **kwargs)
    return wrapper


@case("G-R35")
@pytest.mark.parametrize("fault", [RuntimeError("injected"), KeyboardInterrupt(),
                                   reducer.ReducerDefect("injected")],
                         ids=["runtime-error", "interrupt", "reducer-defect"])
def test_a_fault_after_the_directory_exists_leaves_nothing_behind(tmp_path, monkeypatch, fault):
    """R35 and OPS-17: a fault raised by the reduction of the fifth frame, once the directory
    and its three files exist and records have been written, propagates unchanged, and the
    files and the directory are gone. Replay reduces each frame its reader has just verified
    through `reducer.reduce_admitted` (CR-L07, round R6), so the fault is injected there."""
    monkeypatch.setattr(reducer, "reduce_admitted", _counting(reducer.reduce_admitted, fault, 5))
    with pytest.raises(type(fault)):
        replay(write(tmp_path, capture_data()), tmp_path / "run")
    assert not (tmp_path / "run").exists()


@case("G-R35")
def test_a_write_that_fails_is_e_io_and_leaves_nothing_behind(tmp_path, monkeypatch):
    """A write that fails once the directory exists (the third write to a file stream raises
    the OSError a full disk gives) is E_IO at `output_dir`, mapped by the writer itself, and the
    files and the directory are removed."""
    class Failing:
        def __init__(self, real):
            self.real, self.calls = real, 0

        def write(self, data):
            self.calls += 1
            if self.calls == 3:
                raise OSError(28, "No space left on device")
            return self.real.write(data)

        def close(self):
            self.real.close()
    original_init = REPLAY._File.__init__

    def init(self, fd):
        original_init(self, fd)
        self.stream = Failing(self.stream)
    monkeypatch.setattr(REPLAY._File, "__init__", init)
    error = refused(lambda: replay(write(tmp_path, capture_data()), tmp_path / "run"))
    assert (error.code, error.path) == ("E_IO", "output_dir")
    assert not (tmp_path / "run").exists()


@case("G-R35")
def test_a_capture_that_changes_between_the_two_readings_is_e_io(tmp_path, monkeypatch):
    """R35 verifies the whole capture first and reads it again to replay it; if the second
    reading reports anything else (here the file grew a frame and its footer in between), the
    replay is refused with E_IO `capture_path` and the directory removed."""
    path = write(tmp_path, b"\n".join(capture_data().split(b"\n")[:9]) + b"\n")
    # Replay's first reading is `_verified` (verify_capture's reader, line by line with the
    # caller's check: round R6); the change is made right after it.
    real = REPLAY._verified

    def verify_then_grow(capture_path, check):
        report = real(capture_path, check)
        path.write_bytes(capture_data())
        return report
    monkeypatch.setattr(REPLAY, "_verified", verify_then_grow)
    error = refused(lambda: replay(path, tmp_path / "run", allow_prefix=True))
    assert (error.code, error.path) == ("E_IO", "capture_path")
    assert not (tmp_path / "run").exists()


@case("G-R35")
def test_a_capture_replaced_between_the_two_readings_is_e_io(tmp_path, monkeypatch):
    """The second reading must report exactly what the first did: a complete capture replaced in
    between by another complete capture of the same length (only the header's audit time
    differs, so every digest of the chain does) is refused with E_IO `capture_path`, although
    each file alone would replay; the directory is removed."""
    records = fixture_capture_records()
    other = copy.deepcopy(records)
    other[0]["record_created_at"] = "2031-07-15T12:34:56.789012Z"
    first, second = capture_bytes(chain_lines(records)), capture_bytes(chain_lines(other))
    assert len(first) == len(second) and first != second
    path = write(tmp_path, first)
    real = REPLAY._verified

    def verify_then_replace(capture_path, check):
        report = real(capture_path, check)
        path.write_bytes(second)
        return report
    monkeypatch.setattr(REPLAY, "_verified", verify_then_replace)
    error = refused(lambda: replay(path, tmp_path / "run"))
    assert (error.code, error.path) == ("E_IO", "capture_path")
    assert not (tmp_path / "run").exists()


@case("G-R35")
def test_a_tail_that_is_not_the_verified_one_is_e_io(tmp_path):
    """The unverified tail of a prefix replay is copied only if it is still a partial line
    within the line limit that ends the file; otherwise the file changed (E_IO)."""
    data = _cut_inside_line_8()
    verified = data.rfind(b"\n") + 1
    path = write(tmp_path, data)
    assert REPLAY._tail(path, verified) == data[verified:]
    error = refused(lambda: REPLAY._tail(path, verified - 1))
    assert (error.code, error.path) == ("E_IO", "capture_path")
    error = refused(lambda: REPLAY._tail(path, verified + 1 + len(data)))
    assert (error.code, error.path) == ("E_IO", "capture_path")


@case("G-R17", "G-R35")
@pytest.mark.parametrize("seed", [17, 1717])
def test_damaged_captures_refuse_or_replay_and_never_leave_a_partial_directory(tmp_path, seed):
    """CR-R2-24 for replay: one bit flipped at random positions of the bundled capture, with and
    without allow_prefix: the only outcomes are an `HlaError` with an E_ catalogue code and no
    directory, or a prefix replay of what verified (a cut-short last line); nothing else
    escapes, and a refused replay never leaves a directory."""
    from hla_support import CATALOGUE
    rng = random.Random(seed)
    data = capture_data()
    seen = set()
    for index in range(40):
        position = rng.randrange(len(data))
        changed = bytearray(data)
        changed[position] ^= 1 << rng.randrange(8)
        path = write(tmp_path, bytes(changed), f"flip{index}.jsonl")
        out = tmp_path / f"run{index}"
        try:
            replay(path, out, allow_prefix=bool(index % 2))
            seen.add("replayed")
            assert {r["capture_complete"] for r in records_of(out)} <= {False}
        except HlaError as error:
            assert error.code in CATALOGUE and error.code.startswith("E_")
            assert not out.exists()
            seen.add(error.code)
    assert "E_CAPTURE_HASH" in seen or "E_CAPTURE_SCHEMA" in seen


@case("G-R35")
@case("G-R40", "G-R37")
def test_hostile_names_reach_the_output_as_escaped_data(tmp_path):
    """R40: capture strings are data, never terminal escape sequences. An object name of exactly
    1024 UTF-8 bytes holding an escape sequence and a bidirectional override, a class with a
    bell and a line separator, and an unknown attribute name with an OSC sequence are replayed:
    the snapshot carries the name and class as captured, the diagnostic names the attribute as
    the frame did (CR-R1-04), and every output byte is ASCII with no raw control character
    (canonical JSON escapes them)."""
    name = ("\x1b[2J\N{RIGHT-TO-LEFT OVERRIDE}"
            + "\N{LATIN SMALL LETTER E WITH ACUTE}" * 508 + "x")
    assert len(name.encode("utf-8")) == 1024
    reported_class = "HLAobjectRoot\x07\N{LINE SEPARATOR}x"
    attribute = "\x1b]0;title\x07"
    capture_path = (Scenario().frame(1, 0, event_generation_start())
                    .frame(1, 0, event_discover("o1", name, reported_class))
                    .frame(1, SECOND, event_reflect("o1", ((attribute, "00"),)))
                    .frame(1, SECOND, event_generation_end()).footer()
                    .write(tmp_path / "capture.jsonl"))
    replay(capture_path, tmp_path / "run")
    data = (tmp_path / "run" / "observations.jsonl").read_bytes()
    assert data.isascii() and not any(b < 0x20 and b != 0x0A for b in data)
    records = held_to_the_contract(tmp_path / "run", capture_path)
    snapshot = next(r for r in records if r["kind"] == "snapshot")["payload"]
    assert (snapshot["name"], snapshot["reported_class"]) == (name, reported_class)
    diagnostic = next(r for r in records if r["kind"] == "diagnostic")["payload"]
    assert (diagnostic["code"], diagnostic["attribute"]) == ("E_UNSUBSCRIBED_ATTRIBUTE",
                                                             attribute)
    assert attribute not in diagnostic["message"] and "\x1b" not in diagnostic["message"]


# ==================================================================== time, audit time, policy none

@case("G-R08", "G-R35", paragraphs=("SPEC:42",))
def test_replay_takes_time_from_the_stored_elapsed_values_and_reads_no_clock(tmp_path,
                                                                             monkeypatch):
    """R08's carried SPEC:42 clause and R35: replay uses the stored elapsed_ns and never the
    machine's clock: with every clock and sleep of `time` made to fail, a capture whose Spatial
    arrives at 1 234 567 891 ns replays to effective time 00:00:01.234567 and valid_from
    00:00:01.234 (CR-L05), twice identically."""
    def no_clock(*_args, **_kwargs):
        raise AssertionError("replay read a clock")
    for name in ("time", "time_ns", "monotonic", "monotonic_ns", "perf_counter",
                 "perf_counter_ns", "process_time", "process_time_ns", "sleep", "localtime",
                 "gmtime", "thread_time"):
        monkeypatch.setattr(time, name, no_clock)
    capture_path = (Scenario().frame(1, 0, event_generation_start())
                    .frame(1, 0, event_discover("o1"))
                    .frame(1, 1_234_567_891, event_reflect("o1", FULL))
                    .frame(1, 1_234_567_891, event_generation_end()).footer()
                    .write(tmp_path / "capture.jsonl"))
    first, second = replay(capture_path, tmp_path / "a"), replay(capture_path, tmp_path / "b")
    assert first == second
    upsert = next(r for r in records_of(tmp_path / "a") if r["kind"] == "upsert")
    assert upsert["payload"]["valid_from"] == "2026-01-01T00:00:01.234Z"
    assert upsert["payload"]["attributes"]["hla"]["time"]["effective_at"] == \
        "2026-01-01T00:00:01.234567Z"


@case("G-R15")
def test_the_audit_time_of_the_header_reaches_the_output_only_through_the_cited_digests(tmp_path):
    """R15's carried clause, in the form the hash chain allows (proposed CR-new-R4-08):
    record_created_at never affects state, identity or any projected value. Two captures that
    differ only in it replay to identical diagnostics and to observations identical in every
    member but one: each upsert's source.source_hash, which R27 defines as the triggering
    frame's sha256 and which R15's chain derives from the exact header bytes, so each cites its
    own capture's frame. The reducer states after the last frame are equal but for that chain
    position."""
    records = fixture_capture_records()
    other = copy.deepcopy(records)
    other[0]["record_created_at"] = "2031-07-15T12:34:56.789012Z"
    a = write(tmp_path, capture_bytes(chain_lines(records)), "a.jsonl")
    b = write(tmp_path, capture_bytes(chain_lines(other)), "b.jsonl")
    replay(a, tmp_path / "ra")
    replay(b, tmp_path / "rb")
    assert (tmp_path / "ra" / "diagnostics.jsonl").read_bytes() == \
        (tmp_path / "rb" / "diagnostics.jsonl").read_bytes()
    first, second = records_of(tmp_path / "ra"), records_of(tmp_path / "rb")
    frames_b = {r["seq"]: r for r in (json.loads(line) for line in b.read_bytes().splitlines())
                if r["type"] == "frame"}
    cited = 0
    for x, y in zip(first, second, strict=True):
        if x["kind"] == "upsert":
            assert y["payload"]["source"]["source_hash"]["value"] == frames_b[y["seq"]]["sha256"]
            assert x["payload"]["source"]["source_hash"] != y["payload"]["source"]["source_hash"]
            y = copy.deepcopy(y)
            y["payload"]["source"]["source_hash"] = x["payload"]["source"]["source_hash"]
            cited += 1
        assert x == y
    assert cited == 2
    states = []
    for capture in (chain_lines(records), chain_lines(other)):
        parsed = [json.loads(line) for line in capture]
        state = reducer.initial_state(parsed[0], True)
        for frame in parsed[1:-1]:
            state, _ = reduce_checked(state, frame)
        states.append(state)
    assert states[0].rules != states[1].rules
    assert dataclasses.replace(states[1], rules=states[0].rules) == states[0]


@case("A-NO-TIME", "G-R08")
def test_a_capture_recorded_under_none_with_pauses_and_bursts_replays(tmp_path,
                                                                      summary_validator):
    """R08's carried clause: time policy none gives normalized observations and no Entity, and a
    capture of a paused, accelerated or reset exercise, recorded under none, replays: elapsed
    jumps by an hour, then advances by a nanosecond, and every snapshot is SUPPRESSED with
    TIME_UNRESOLVED, no upsert at all (A-NO-TIME through replay)."""
    header = header_with(**example_json("config-existing.json"))
    capture_path = (Scenario(header).frame(1, 0, event_generation_start())
                    .frame(1, 0, event_discover("o1"))
                    .frame(1, 3600 * SECOND, event_reflect("o1", FULL))
                    .frame(1, 3600 * SECOND + 1, event_reflect("o1", FULL[3:]))
                    .frame(1, 3600 * SECOND + 1, event_reflect("o1", FULL[2:3]))
                    .frame(1, 7200 * SECOND, event_generation_end()).footer()
                    .write(tmp_path / "capture.jsonl"))
    summary = summary_of(capture_path, tmp_path / "run", summary_validator)
    assert summary["records"] == {"diagnostic": 5, "snapshot": 3, "upsert": 0, "removed": 0,
                                  "invalidated": 1}
    assert summary["warnings"] == {"W_FOM_UNVERIFIED": 1, "W_FORCE_UNMAPPED": 1,
                                   "W_TIME_UNRESOLVED": 3}
    assert summary["suppressions"]["TIME_UNRESOLVED"] == 3
    held_to_the_contract(tmp_path / "run", capture_path)


@case("G-R35")
def test_replay_output_equals_the_reducer_records_of_the_same_frames(tmp_path):
    """R35: replay invokes the same reducer and projector: its observation lines are exactly
    `output_line` of the records reduce_frame gives for the verified frames, with
    capture_complete true."""
    scenario = _session_with_diagnostics()
    out = scenario.reduce()
    path = scenario.write(tmp_path / "capture.jsonl")
    replay(path, tmp_path / "run")
    assert (tmp_path / "run" / "observations.jsonl").read_bytes() == b"".join(
        reducer.output_line(r) for records in out for r in records)


def test_the_summary_schema_refuses_an_inconsistent_summary(summary_validator, tmp_path):
    """CR-L03: the summary schema has a version, closes every object and ties completion to the
    status, so a summary that contradicts itself does not validate."""
    good = replay(write(tmp_path, capture_data()), tmp_path / "run")
    assert not list(summary_validator.iter_errors(good))
    for change in ({"capture_complete": False}, {"status": "INVALID"},
                   {"replay_summary_version": 2}, {"extra": 1},
                   {"errors": {"W_FOM_UNVERIFIED": 1}}, {"warnings": {"E_IO": 1}},
                   {"errors": {"E_IO": 0}}, {"records": {"snapshot": 1}},
                   {"files": {"capture.jsonl": {"bytes": 1, "sha256": "x"}}}):
        assert list(summary_validator.iter_errors({**good, **change})), change


def test_the_first_reading_is_verify_capture_line_by_line(tmp_path):
    """Round R6: replay's first reading drives the verified reader itself so that a caller's
    check runs before each line; its report is verify_capture's, for a complete, a truncated and
    an invalid capture alike, and the check is called once per line read plus once at the end."""
    data = capture_data()
    for name, content in (("complete", data), ("cut", data[:3000]),
                          ("invalid", data.replace(b'"seq":3', b'"seq":4', 1))):
        path = write(tmp_path, content, f"{name}.jsonl")
        calls = []
        assert REPLAY._verified(path, lambda: calls.append(1)) == synapse_hla.verify_capture(path)
        assert calls
    calls = []
    REPLAY._verified(write(tmp_path, data, "again.jsonl"), lambda: calls.append(1))
    assert len(calls) == 10 + 1


def test_a_check_that_raises_ends_the_replay_and_removes_its_directory(tmp_path):
    """The command line's stop (round R6): what `check` raises before a line of the second
    reading propagates as itself, and the directory is gone."""
    class Stop(BaseException):
        pass
    calls = []

    def check():
        calls.append(1)
        if len(calls) == 15:
            raise Stop()
    with pytest.raises(Stop):
        REPLAY.replay_with(write(tmp_path, capture_data()), tmp_path / "run", check=check)
    assert not (tmp_path / "run").exists()
