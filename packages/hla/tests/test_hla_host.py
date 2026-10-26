"""The host of round R5 (`synapse_hla.host`): one live session against a real worker process.

Every session here runs `host.run_session` against `fake_worker.py`, a real child process the
host starts through its own spawn, and every test then runs `hla_support.finished` (or
`check_session`) on what the session left: the capture read by the tests' own canonical reader
and hash chain, `verify_capture` (COMPLETE or FAILED as the footer says, or INCOMPLETE with the
right prefix), `replay` compared with the live `observations.jsonl` except for the completion
fields (SPEC:158), `diagnostics.jsonl` against the diagnostic lines, the modes 0700/0600, the
summary against `local_schemas/session-summary.schema.json`, and that no worker process
survived. A case is bound by a test that runs a session and asserts the capture, the output
records and the returned summary (the round's binding rule).

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
- The capture shapes (kind, generation, elapsed_ns, then reason, code, token) are derived by hand
  from the rulings named in each docstring: NAT-08 (one diagnostic per condition, the
  generation_end reason from the code), SPEC:62 (what retries), OPV-01 (generation 0 between
  generations, elapsed time), RED-08 (retraction COMPLETE), OPS-15/OPS-25 (stops), OPS-18 (an RTI
  that never answers), SPEC:293 (reserve), RED-07/RED-12 (the reducer's terminal flag).
- elapsed_ns are exact under the frozen clock (`hla_support.FrozenClock`, starting at
  7000 s): the session origin is the first generation_start's `monotonic_ns`, a fake worker
  stamps its frames with the frozen time at its start plus each step's `dt`, and the host's own
  frames carry the frozen time minus the origin, never below the previous frame. Sessions with
  `frozen=False` use the real clock with shortened timing values and compare shapes without
  elapsed_ns.
- entity_ids are R26 by the tests' own RFC 4122 code (`hla_support.rfc4122_uuid5`), the first
  checked against the fixture's literal 781e68de-....
- Byte-exact captures are built by the tests' own canonical writer and chain
  (`hla_support.CaptureBuilder`, `canonical`), never by the product.
"""

import dataclasses
import errno
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import time

import pytest

from hla_support import (
    AUDIT_TEXT, AUDIT_US, FROZEN_START_NS, PACKAGE_ROOT, SECOND_NS, CaptureBuilder, Session, brief,
    canonical, case, check_session, child_environment, connect_and_join, connect_refused,
    event_diagnostic, event_discover, event_generation_end, event_generation_start,
    event_reflect, event_remove, example_config, fail, finished, fom_modules, frame_step,
    orderly_stop, packaged_pins, positive_hex, process_gone, rfc4122_uuid5, stage,
    worker_executable,
)
from synapse_hla import HlaError, _writer, host
from synapse_hla import limits as limits_module
from synapse_hla import projector as projector_module
from synapse_hla import reducer as reducer_module

FED = "SC_DEMO_0123456789abcdef"
B1 = FROZEN_START_NS
S = SECOND_NS
MS = 1_000_000
#: The pre-flight of the rows that shorten the session's deadline to 1 s to measure it: the version
#: probe gets R14's own 10 s and the worker answers it 1.2 s late, past the 1 s under test, so a
#: probe that shared the session's deadline would refuse the worker before the session began.
#: No row then measures a deadline its pre-flight also depends on (review finding R9-r1-F5: under
#: load a 1 s probe refused the fake worker's slow start, E_DEPENDENCY_PIN).
PROBE = {"probe_deadline_ns": 10 * S, "version": {"delay_ms": 1200}}
EI, ET, FI, SP = "EntityIdentifier", "EntityType", "ForceIdentifier", "Spatial"
HEX = positive_hex()
#: ID-123 (1.2.3), TYPE-PLATFORM, FORCE-1 and SPATIAL-2 of the bundle's positive vectors.
FULL = ((EI, HEX["ID-123"]), (ET, HEX["TYPE-PLATFORM"]), (FI, HEX["FORCE-1"]),
        (SP, HEX["SPATIAL-2"]))
NAMESPACE = "6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50"


def eid(session: str, generation: int, triple: tuple, incarnation: int) -> str:
    """R26 written out: UUIDv5 over "entity|hla-rpr2|" and the six strings as compact JSON."""
    external = json.dumps([session, str(generation), *(str(n) for n in triple), str(incarnation)],
                          separators=(",", ":"))
    return rfc4122_uuid5(NAMESPACE, "entity|hla-rpr2|" + external)


#: The fixture's entity (example-001, generation 1, 1.2.3, incarnation 1), and the same triple
#: in generations 2 and 3: a new UUID for each (R26, A-RECONNECT).
EID_1 = "781e68de-166f-531c-b906-4a2d087f817e"
EID_GEN2 = eid("example-001", 2, (1, 2, 3), 1)
EID_GEN3 = eid("example-001", 3, (1, 2, 3), 1)
EXIT_1 = {"do": "exit", "code": 1}
STALL = {"do": "stall"}


# --- shapes -----------------------------------------------------------------------------------

def START(generation, elapsed):
    return ("generation_start", generation, elapsed, FED)


def END(generation, elapsed, reason):
    return ("generation_end", generation, elapsed, reason)


def DIAG(generation, elapsed, code, token=None, attribute=None):
    return ("diagnostic", generation, elapsed, code, token, attribute)


def DISC(generation, elapsed, token="o1"):
    return ("discover", generation, elapsed, token)


def REFL(generation, elapsed, token="o1"):
    return ("reflect", generation, elapsed, token)


def FOOT(status, reason, last_generation):
    return ("footer", status, reason, last_generation)


def bare(shape):
    """A shape without elapsed_ns (real-clock sessions)."""
    return [item if item[0] == "footer" else item[:2] + item[3:] for item in shape]


# --- worker steps -----------------------------------------------------------------------------

def discover(token="o1", dt=0):
    return frame_step(event_discover(token), dt)


def reflect_full(token="o1", dt=0):
    return frame_step(event_reflect(token, FULL), dt)


def copy_of(code, message="the RTI call failed", dt=0, *, token=None, attribute=None):
    return frame_step(event_diagnostic(code, message, token=token, attribute=attribute), dt)


def reported(code, message="the RTI call failed", dt=0):
    """NAT-08's channel rule: the failure record on fd 3 and the same code as a diagnostic frame;
    then the worker exits non-zero."""
    return [fail(code, message), copy_of(code, message, dt), EXIT_1]


def lost(dt):
    """connectionLost in the event loop (NAT-03's RST case)."""
    return reported("E_RTI_CONNECT", "connection lost", dt)


def joined_session(*middle, dt_join=0):
    """Join, the given steps, then the orderly stop on SIGTERM (R14)."""
    return connect_and_join(dt=dt_join) + list(middle) + orderly_stop()


def by_seq(records):
    out = {}
    for record in records:
        out.setdefault(record["seq"], []).append(brief(record))
    return out


def started(session):
    return [entry["attempt"] for entry in session.starts()]


def message_at(session, seq):
    """The message of the captured diagnostic at `seq`."""
    return session.records()[seq]["event"]["diagnostic"]["message"]


# ============================================================================ the seam (OPS-21)

@case("A-TIMEOUT", "G-R14", "G-R34", paragraphs=("SPEC:62", "SPEC:277"))
def test_the_default_seam_holds_the_specifications_values():
    """D-09, OPS-21: `host.V1` carries `limits.V1` and every timing value, written out here from
    the text: the 10 s host deadline (SPEC:60, A-TIMEOUT's 10 s), the 1, 2 and 4 s reconnect
    delays (SPEC:62), the 1 s drain (SPEC:277), fsync at 100 frames or 250 ms (SPEC:162) and the
    250 ms RSS poll (OPS-23); the clock is CLOCK_MONOTONIC (OPV-02), the opener, fsync and RSS
    probe are the package's own."""
    v1 = host.V1
    assert v1.limits is limits_module.V1
    assert v1.deadline_ns == 10_000_000_000
    assert v1.retry_delays_ns == (1_000_000_000, 2_000_000_000, 4_000_000_000)
    assert v1.drain_ns == 1_000_000_000
    assert v1.fsync_frames == 100
    assert v1.fsync_interval_ns == 250_000_000
    assert v1.rss_poll_ns == 250_000_000
    assert v1.open_capture is _writer.open_capture and v1.fsync is _writer.fsync
    before = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    reading = v1.monotonic_ns()
    after = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    assert type(reading) is int and before <= reading <= after
    wall_before = time.time_ns() // 1000
    wall = v1.wall_clock_us()
    assert type(wall) is int and wall_before <= wall <= time.time_ns() // 1000
    with pytest.raises(dataclasses.FrozenInstanceError):
        v1.deadline_ns = 1


@pytest.mark.parametrize("member,value,error", [
    ("deadline_ns", 0, ValueError), ("deadline_ns", 1.0, ValueError),
    ("deadline_ns", True, ValueError), ("drain_ns", -1, ValueError),
    ("fsync_frames", 0, ValueError), ("fsync_interval_ns", "250", ValueError),
    ("rss_poll_ns", None, ValueError), ("retry_delays_ns", [1, 2, 4], ValueError),
    ("retry_delays_ns", (1, -2), ValueError), ("retry_delays_ns", (1.0,), ValueError),
    ("limits", None, TypeError), ("monotonic_ns", 5, TypeError), ("sleep", None, TypeError),
    ("rss_of", "ps", TypeError), ("getppid", 1, TypeError),
])
def test_a_seam_variant_with_a_bad_member_is_refused(member, value, error):
    with pytest.raises(error):
        dataclasses.replace(host.V1, **{member: value})


def test_the_default_sleep_ends_when_a_signal_wakes_it():
    """OPS-15: a stop during a backoff must not wait for the delay. The default sleep returns as
    soon as the wake-up pipe is readable, whatever delay it was given."""
    read_end, write_end = os.pipe()
    try:
        os.write(write_end, b"\x02")
        started_at = time.monotonic()
        host.V1.sleep(3600 * SECOND_NS, read_end)
        assert time.monotonic() - started_at < 60
    finally:
        os.close(read_end)
        os.close(write_end)


def test_the_default_rss_probe_reads_a_live_process_and_nothing_for_a_gone_one():
    """OPS-23: the RSS of a live process in bytes (ps -o rss= in KiB here, /proc VmRSS on
    Linux), and None once the process is gone."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             env=child_environment())
    try:
        rss = host.V1.rss_of(child.pid)
        assert type(rss) is int and rss > 0 and rss % 1024 == 0
    finally:
        child.kill()
        child.wait()
    assert host.V1.rss_of(child.pid) is None


def test_lines_are_cut_and_bounded_as_they_grow():
    """SPEC:226 and SPEC:277: a line is judged by its length before it is parsed, and a line
    longer than the limit is reported once and skipped to its LF without being held; a line of
    exactly the limit is a line; bytes after the last LF are a partial line."""
    lines = host._Lines(8)
    assert lines.feed(b"12345678\n123") == [b"12345678"] and lines.partial
    assert lines.feed(b"456789") == [host._OVERSIZE] and lines.partial
    assert lines.feed(b"0123456789") == [] and lines.buffer == bytearray()
    assert lines.feed(b"tail\nok\n") == [b"ok"] and not lines.partial
    assert lines.feed(b"abcdefghi\nx") == [host._OVERSIZE] and lines.partial
    assert lines.feed(b"\n") == [b"x"] and not lines.partial


# ===================================================================== before anything exists

def _flip_fom(session):
    copy = session.root / "fom"
    copy.mkdir()
    for module in fom_modules():
        (copy / module.name).write_bytes(module.read_bytes())
    base = copy / "RPR-Base_v2.0.xml"
    data = bytearray(base.read_bytes())
    data[100] ^= 0x01
    base.write_bytes(bytes(data))
    session.environ["SYNAPSE_HLA_FOM_DIR"] = str(copy)


def _worker_directory(session):
    folder = session.root / "a-directory"
    folder.mkdir()
    session.environ["SYNAPSE_HLA_WORKER"] = str(folder)


PREFLIGHT = [
    ("fom-unset", lambda s: s.environ.pop("SYNAPSE_HLA_FOM_DIR"), {}, "RPR-Foundation_v2.0.xml"),
    ("fom-byte-flipped", _flip_fom, {}, "RPR-Base_v2.0.xml"),
    ("worker-missing",
     lambda s: s.environ.update(SYNAPSE_HLA_WORKER=str(s.root / "nowhere")), {},
     "sc-hla-federate"),
    ("worker-relative", lambda s: s.environ.update(SYNAPSE_HLA_WORKER="sc-hla-federate"), {},
     "sc-hla-federate"),
    ("worker-empty", lambda s: s.environ.update(SYNAPSE_HLA_WORKER=""), {}, "sc-hla-federate"),
    ("worker-is-a-directory", _worker_directory, {}, "sc-hla-federate"),
    ("version-other-text", None, {"version": {"hex": b'{"name":"sc-hla-federate"}\n'.hex()}},
     "sc-hla-federate"),
    ("version-exit-1", None, {"version": {"exit": 1}}, "sc-hla-federate"),
    ("version-and-more",
     None, {"version": {"hex": (host.VERSION_LINE + b"more\n").hex()}}, "sc-hla-federate"),
    ("version-without-lf", None, {"version": {"hex": host.VERSION_LINE[:-1].hex()}},
     "sc-hla-federate"),
    ("version-never-answers", None,
     {"version": {"stall": True}, "frozen": False, "deadline_ns": S}, "sc-hla-federate"),
]


@case("G-R15", "G-R34", paragraphs=("SPEC:293",))
@pytest.mark.parametrize("name,breakage,options,path", PREFLIGHT, ids=[p[0] for p in PREFLIGHT])
def test_the_pre_flight_refuses_before_the_run_directory_exists(tmp_path, name, breakage,
                                                               options, path):
    """OPS-11 (as corrected), OPV-04 and R15's carried clause (SPEC:293: validating the local
    dependency pins is mandatory for observation): the five FOM modules are checked against the
    packaged pins (an unset variable is refused under the first module's name, a flipped byte
    under the module's own), then the worker is located (an absolute SYNAPSE_HLA_WORKER, never a
    PATH search) and must answer `--version` with exactly the version line and exit 0 within the
    deadline. Every refusal is E_DEPENDENCY_PIN before the run directory exists, and no session
    worker was started."""
    session = Session(tmp_path, [joined_session()], **options)
    if breakage is not None:
        breakage(session)
    with pytest.raises(HlaError) as caught:
        session.run()
    assert (caught.value.code, caught.value.path) == ("E_DEPENDENCY_PIN", path)
    assert not session.out.exists() and not os.path.lexists(session.out)
    assert session.starts() == []
    for entry in session.log_entries():
        assert process_gone(entry["pid"])


def test_the_configuration_and_the_output_path_are_refused_first(tmp_path):
    """The order of the refusals before anything exists: the configuration (E_CONFIG at its
    pointer) comes before the dependencies, and an output path no directory can have (E_IO
    `output_dir`) too; neither starts anything."""
    session = Session(tmp_path, [joined_session()],
                      config=example_config(time_policy={"mode": "sometimes"}))
    session.environ.pop("SYNAPSE_HLA_FOM_DIR")
    with pytest.raises(HlaError) as caught:
        session.run()
    assert (caught.value.code, caught.value.path) == ("E_CONFIG", "/time_policy/mode")
    session = Session(tmp_path / "second", [joined_session()])
    session.environ.pop("SYNAPSE_HLA_FOM_DIR")
    session.out = tmp_path / "second" / "bad\x00name"
    with pytest.raises(HlaError) as caught:
        session.run()
    assert (caught.value.code, caught.value.path) == ("E_IO", "output_dir")
    assert session.log_entries() == []


@case("G-R07", "G-R34")
@pytest.mark.parametrize("kind", ["directory", "file", "dangling-symlink", "symlink-to-directory",
                                  "missing-parent"])
def test_the_run_directory_is_created_exclusively(tmp_path, kind):
    """R07's carried clause (session directories are created exclusively; a run never resumes
    into an existing capture) and OPS-17 at the host: only the last component is judged; it
    must not exist in any form, not even as a dangling symbolic link (E_OUTPUT_EXISTS), and its
    parent must exist (E_IO). Whatever was there is left byte for byte as it was, and no session
    worker starts (the pre-flight's `--version` has run: the directory comes after it)."""
    session = Session(tmp_path, [joined_session()])
    out = session.out
    old_capture = b'{"type":"header"}\n'
    if kind == "directory":
        out.mkdir()
        (out / "capture.jsonl").write_bytes(old_capture)
    elif kind == "file":
        out.write_bytes(old_capture)
    elif kind == "dangling-symlink":
        out.symlink_to(tmp_path / "nothing-here")
    elif kind == "symlink-to-directory":
        (tmp_path / "elsewhere").mkdir()
        out.symlink_to(tmp_path / "elsewhere")
    else:
        session.out = tmp_path / "no-such-parent" / "run"
    with pytest.raises(HlaError) as caught:
        session.run()
    expected = "E_IO" if kind == "missing-parent" else "E_OUTPUT_EXISTS"
    assert (caught.value.code, caught.value.path) == (expected, "output_dir")
    if kind == "directory":
        assert sorted(p.name for p in out.iterdir()) == ["capture.jsonl"]
        assert (out / "capture.jsonl").read_bytes() == old_capture
    elif kind == "file":
        assert out.read_bytes() == old_capture
    elif kind == "symlink-to-directory":
        assert list((tmp_path / "elsewhere").iterdir()) == []
    assert session.starts() == []
    assert [e["event"] for e in session.log_entries()] == ["version"]


def test_locate_worker_takes_the_override_or_the_fixed_place_and_never_the_path(tmp_path):
    """OPV-04: SYNAPSE_HLA_WORKER when set (an absolute path), otherwise one fixed place beside
    the installed package; a `sc-hla-federate` on PATH is never looked at."""
    worker = worker_executable(tmp_path)
    assert host.locate_worker({"SYNAPSE_HLA_WORKER": str(worker)}) == str(worker)
    package = pathlib.Path(host.__file__).resolve().parent
    assert host.WORKER_LOCATION == str(package / "bin" / "sc-hla-federate")
    assert host.locate_worker({"PATH": str(tmp_path)}) == host.WORKER_LOCATION
    for value in ("sc-hla-federate", "./sc-hla-federate", ""):
        with pytest.raises(HlaError) as caught:
            host.locate_worker({"SYNAPSE_HLA_WORKER": value})
        assert (caught.value.code, caught.value.path) == ("E_DEPENDENCY_PIN", "sc-hla-federate")
    for bad in ({"A": 1}, {1: "a"}, ["SYNAPSE_HLA_WORKER"]):
        with pytest.raises(TypeError):
            host.locate_worker(bad)
    with pytest.raises(ValueError):
        host.locate_worker({"A": "x\x00y"})


# ============================================================ the header and the worker process

@case("G-R09", "G-R15", "G-R34", paragraphs=("SPEC:293",))
def test_the_header_records_the_validated_configuration_and_the_pins_before_the_worker(tmp_path):
    """R06, R09's and R15's carried clauses: the header is written (and synced) before the
    worker starts, holds the validated configuration exactly as given (force_map included) and
    the packaged nine-entry pin map (OPS-11, RED-V-03), with the injected audit time; the
    session cannot change it (nothing rewrites line 1)."""
    config = example_config(force_map={"1": "FRIENDLY", "2": "HOSTILE", "255": "UNKNOWN"})
    session = Session(tmp_path, [joined_session()], config=config).run(stop_on_waiting=1)
    finished(session)
    header = session.records()[0]
    pins = {name: entry["sha256"] for name, entry in packaged_pins().items()}
    assert header == {"type": "header", "capture_version": 1, "profile": "SC-HLA-RPR2-OBS-1",
                      "adapter_version": "1.0.0", "config": config, "pins": pins,
                      "record_created_at": AUDIT_TEXT}
    assert len(pins) == 9
    header_line = session.capture_bytes().split(b"\n")[0] + b"\n"
    assert [e["watched"] for e in session.starts()] == [len(header_line)]


@case("G-R14", "G-R34", paragraphs=("SPEC:277",))
def test_the_worker_gets_its_arguments_environment_and_descriptors(tmp_path):
    """OPS-08, NAV-01, NAT-09 and SPEC:277, as the worker sees them: exactly the three
    `--key=value` tokens; no OpenRTI debug variable although the host's environment has both;
    fd 3 a FIFO (the status pipe), stdin the null device, no other inherited descriptor; and a
    process group of its own (a terminal's interrupt reaches the host alone)."""
    session = Session(tmp_path, [joined_session()],
                      extra_env={"OPENRTI_DEBUG_PRIORITY": "9", "OPENRTI_DEBUG_CATEGORY": "all"})
    session.run(stop_on_waiting=1)
    finished(session)
    (start,) = session.starts()
    assert start["argv"] == ["--endpoint=rti://127.0.0.1:14321",
                             f"--federation-name={FED}", "--federate-name=SC_OBSERVER"]
    assert start["openrti_debug"] == []
    assert start["fd3_fifo"] and start["stdin_null"] and start["inherited"] == []
    assert start["pgid"] == start["pid"] != os.getpgrp()
    assert start["ppid"] == os.getpid()
    assert session.summary["status"] == "COMPLETE"


@case("G-R14", paragraphs=("SPEC:277",))
def test_text_on_the_workers_stderr_is_never_read_as_protocol(tmp_path):
    """R14: ordinary stderr text must not be parsed as protocol. A worker that writes a status
    failure record, a frame and garbage to its stderr changes nothing: COMPLETE."""
    noise = (b'{"code":"E_LIMIT","message":"x","type":"failure"}\n'
             b'{"event":{"type":"generation_end","reason":"limit"},"monotonic_ns":"1"}\n\xff\n')
    session = Session(tmp_path, [joined_session({"do": "stderr_raw", "hex": noise.hex()},
                                                discover("o1", MS))])
    session.run(stop_on_waiting=1)
    finished(session)
    assert session.shape() == [START(1, 0), DISC(1, MS), END(1, MS, "stop"),
                               FOOT("COMPLETE", None, 1)]


# ===================================================================== the two channels (SPEC:277)

def run_case(tmp_path, attempts, *, stop_on_waiting=None, **options):
    session = Session(tmp_path, attempts, **options)
    session.run(stop_on_waiting=stop_on_waiting)
    finished(session)
    return session


def burst(count, first=1):
    return {"do": "frames", "count": count, "first": first, "numbered": True,
            "event": event_discover("o1")}


@case("G-R14", "G-R34", paragraphs=("SPEC:277",))
def test_a_full_stdout_pipe_never_stalls_the_status_channel_nor_the_reverse(tmp_path):
    """Exit criterion 4 and SPEC:277 ("Stdout and status are separately polled"). The worker
    announces request_update and, before its `running`, writes 2000 frames: far more than a pipe
    holds, so it blocks on stdout while the status record waits. Then 10000 request_update /
    running pairs flood fd 3 before 2000 more frames. A host that waited on one channel while
    the other filled would deadlock and, with the deadline shortened to 5 s, end with
    E_RTI_TIMEOUT; this one captures every frame and stops COMPLETE."""
    steps = joined_session(stage("request_update"), burst(2000), stage("running"),
                           {"do": "pairs", "count": 10000}, burst(2000, first=2001))
    session = run_case(tmp_path, [steps], stop_on_waiting=1, frozen=False,
                       deadline_ns=5 * S)
    shape = session.shape(elapsed=False)
    assert shape[0] == ("generation_start", 1, FED)
    assert shape[1:-2] == [("discover", 1, f"o{n}") for n in range(1, 4001)]
    assert shape[-2:] == [("generation_end", 1, "stop"), FOOT("COMPLETE", None, 1)]
    assert session.summary["frames"] == 4002 and session.summary["workers"] == 1


def bad_line(data: bytes) -> dict:
    return {"do": "stdout_raw", "hex": data.hex()}


_DISCOVER = b'{"type":"discover","object_token":"o1","name":"a","reported_class":"b"}'
_REFLECT_UNSORTED = event_reflect("o1", ((SP, HEX["SPATIAL-2"]), (ET, HEX["TYPE-PLATFORM"])))

#: (name, steps after the join, code, generation_end reason); each is a worker frame the host
#: must not capture (OPS-19: malformed E_CAPTURE_SCHEMA, oversize E_LIMIT).
FRAME_FAULTS = [
    ("not-json", [bad_line(b"{not json}\n")], "E_CAPTURE_SCHEMA", "failure"),
    ("a-float", [bad_line(b'{"event":' + _DISCOVER + b',"monotonic_ns":"1","x":1.5}\n')],
     "E_CAPTURE_SCHEMA", "failure"),
    ("a-duplicate-key",
     [bad_line(b'{"event":' + _DISCOVER + b',"monotonic_ns":"1","monotonic_ns":"2"}\n')],
     "E_CAPTURE_SCHEMA", "failure"),
    ("a-lone-surrogate", [bad_line(
        b'{"event":{"type":"discover","object_token":"o1","name":"\\ud800",'
        b'"reported_class":"b"},"monotonic_ns":"7000000000000"}\n')],
     "E_CAPTURE_SCHEMA", "failure"),
    ("outside-the-schema",
     [bad_line(b'{"event":' + _DISCOVER + b',"monotonic_ns":"1","seq":1}\n')],
     "E_CAPTURE_SCHEMA", "failure"),
    ("monotonic-not-canonical",
     [bad_line(b'{"event":' + _DISCOVER + b',"monotonic_ns":"07000000000000"}\n')],
     "E_CAPTURE_SCHEMA", "failure"),
    ("unsorted-attributes", [frame_step(_REFLECT_UNSORTED)], "E_CAPTURE_SCHEMA", "failure"),
    ("a-name-over-1024-utf8-bytes",
     [frame_step(event_discover("o1", "\N{LATIN SMALL LETTER E WITH ACUTE}" * 600))],
     "E_CAPTURE_SCHEMA", "failure"),
    ("severity-against-the-code", [frame_step(dict(event_diagnostic("E_LIMIT"), diagnostic=dict(
        event_diagnostic("E_LIMIT")["diagnostic"], severity="WARNING")))],
     "E_CAPTURE_SCHEMA", "failure"),
    ("generation_end-from-the-worker", [frame_step(event_generation_end("stop"))],
     "E_CAPTURE_SCHEMA", "failure"),
    ("a-second-generation_start", [frame_step(event_generation_start())],
     "E_CAPTURE_SCHEMA", "failure"),
    ("a-derived-code-E_NULL_ID", [copy_of("E_NULL_ID", token="o1", attribute=EI)],
     "E_CAPTURE_SCHEMA", "failure"),
    ("a-derived-code-W_FOM_UNVERIFIED", [frame_step(event_diagnostic("W_FOM_UNVERIFIED", "w"))],
     "E_CAPTURE_SCHEMA", "failure"),
    ("a-derived-code-E_UNKNOWN_OBJECT", [copy_of("E_UNKNOWN_OBJECT", token="o9")],
     "E_CAPTURE_SCHEMA", "failure"),
    ("the-host-only-E_RTI_TIMEOUT", [copy_of("E_RTI_TIMEOUT")], "E_CAPTURE_SCHEMA", "failure"),
    ("a-retraction-naming-an-object", [copy_of("E_RETRACTION_UNSUPPORTED", token="o1")],
     "E_CAPTURE_SCHEMA", "failure"),
    ("oversize", [bad_line(b"x" * 65537 + b"\n")], "E_LIMIT", "limit"),
    ("oversize-without-lf", [bad_line(b"x" * 70000)], "E_LIMIT", "limit"),
]


@case("G-R14", "G-R34", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("name,steps,code,reason", FRAME_FAULTS, ids=[f[0] for f in FRAME_FAULTS])
def test_a_frame_the_host_must_not_capture_ends_the_session(tmp_path, name, steps, code, reason):
    """OPS-19 (a malformed worker line is E_CAPTURE_SCHEMA, an oversize one E_LIMIT), the strict
    reader (RED-04, CR-R2-11/12), the worker protocol of SPEC:277 (the host authors every
    generation_end; one generation_start per worker), and RED-01 with CR-R4-02 (a worker
    diagnostic carries only one of OPS-30's codes, so a derived code is never captured). The
    frame is not captured; the host writes one diagnostic for the condition, generation_end
    with the reason NAT-08 gives the code, and a FAILED footer; it kills the worker and does not
    retry (a capture fault is not transient, SPEC:62)."""
    session = run_case(tmp_path, [connect_and_join() + steps + [STALL]])
    assert session.shape() == [START(1, 0), DIAG(1, 0, code), END(1, 0, reason),
                               FOOT("FAILED", code, 1)]
    assert session.summary["workers"] == 1 and session.summary["terminal_codes"] == [code]
    assert session.summary["errors"] == {code: 1}


def raw_frames(*events) -> bytes:
    """Worker frame lines as `fake_worker.py` writes them, stamped with the frozen start B1 (the
    time every frame of a first frozen worker carries at dt 0)."""
    return b"".join(json.dumps({"event": event, "monotonic_ns": str(B1)}, sort_keys=True,
                               separators=(",", ":")).encode() + b"\n" for event in events)


#: (name, the faulty line, code, generation_end reason): each is followed, in the same write, by
#: three valid discovers.
FAULTS_BEFORE_FRAMES = [
    ("not-json", b"{not json}\n", "E_CAPTURE_SCHEMA", "failure"),
    ("oversize", b"x" * 65537 + b"\n", "E_LIMIT", "limit"),
    ("generation_end-from-the-worker", raw_frames(event_generation_end("stop")),
     "E_CAPTURE_SCHEMA", "failure"),
]


@case("G-R14", "G-R34", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("name,fault,code,reason", FAULTS_BEFORE_FRAMES,
                         ids=[f[0] for f in FAULTS_BEFORE_FRAMES])
def test_nothing_behind_a_faulty_frame_is_captured(tmp_path, name, fault, code, reason):
    """RED-12 and CR-new-R5-08: after a fault the host finds in what the worker sent, it captures
    no more worker frames. The faulty line and three valid discovers (o2, o3, o4) arrive in one
    write, so they are read together; none of the three is captured, although each would be a
    valid frame on its own."""
    behind = raw_frames(event_discover("o2"), event_discover("o3"), event_discover("o4"))
    steps = connect_and_join() + [discover("o1"), bad_line(fault + behind), STALL]
    session = run_case(tmp_path, [steps])
    assert session.shape() == [START(1, 0), DISC(1, 0, "o1"), DIAG(1, 0, code),
                               END(1, 0, reason), FOOT("FAILED", code, 1)]
    assert session.summary["workers"] == 1 and session.summary["terminal_codes"] == [code]


@case("G-R14", paragraphs=("SPEC:275",))
def test_a_worker_frame_earlier_than_the_frame_before_it_is_refused(tmp_path):
    """R16 and SPEC:275: elapsed_ns never decreases; a worker frame stamped before the previous
    frame cannot be captured with its own time, and is not captured with another. Here o2 is
    stamped 1 ms before o1."""
    session = run_case(tmp_path, [connect_and_join() + [discover("o1", 5 * MS),
                                                        discover("o2", 4 * MS), STALL]])
    assert session.shape() == [START(1, 0), DISC(1, 5 * MS), DIAG(1, 5 * MS, "E_CAPTURE_SCHEMA"),
                               END(1, 5 * MS, "failure"), FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)]


@case("G-R14", paragraphs=("SPEC:275",))
def test_a_worker_frame_earlier_than_the_origin_is_refused(tmp_path):
    """SPEC:275: elapsed_ns is a subtraction from the origin and is never negative. A frame
    stamped 2 ms before the generation_start that made the origin is a protocol fault
    (E_CAPTURE_SCHEMA), not a capture record."""
    session = run_case(tmp_path, [connect_and_join(dt=5 * MS) + [discover("o1", 3 * MS),
                                                                  STALL]])
    assert session.shape() == [START(1, 0), DIAG(1, 0, "E_CAPTURE_SCHEMA"),
                               END(1, 0, "failure"), FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)]


def test_a_generation_start_for_another_federation_is_refused(tmp_path):
    """SPEC:275 and OPS-08: the worker joins the configured federation; a generation_start that
    names another one is a protocol fault (E_CAPTURE_SCHEMA), and no generation opens."""
    steps = [stage("connect"), stage("running"), stage("join"), stage("running"),
             frame_step(event_generation_start("SC_DEMO_ffffffffffffffff")), STALL]
    session = run_case(tmp_path, [steps])
    assert session.shape() == [DIAG(0, 0, "E_CAPTURE_SCHEMA"),
                               FOOT("FAILED", "E_CAPTURE_SCHEMA", 0)]


def test_only_diagnostics_come_from_a_worker_before_its_generation_start(tmp_path):
    """SPEC:275: frames before a successful join are diagnostic-only; a discover there is a
    protocol fault, recorded at generation 0 with no generation_end."""
    steps = [stage("connect"), stage("running"), stage("join"), stage("running"), discover(),
             STALL]
    session = run_case(tmp_path, [steps])
    assert session.shape() == [DIAG(0, 0, "E_CAPTURE_SCHEMA"),
                               FOOT("FAILED", "E_CAPTURE_SCHEMA", 0)]


def status_line(data: bytes) -> dict:
    return {"do": "status_raw", "hex": data.hex()}


STATUS_FAULTS = [
    ("not-json", [status_line(b"{oops\n")]),
    ("outside-the-schema", [status_line(b'{"type":"stage","stage":"subscribe"}\n')]),
    ("a-float", [status_line(b'{"type":"stage","stage":"request_update","x":1.0}\n')]),
    ("oversize", [status_line(b"y" * 65537 + b"\n")]),
    ("running-without-a-stage", [stage("running")]),
    ("a-stage-twice", [stage("request_update"), stage("request_update")]),
    ("join-again", [stage("join")]),
    ("resign-without-a-stop", [stage("resign")]),
    ("failure-E_RTI_TIMEOUT", [fail("E_RTI_TIMEOUT")]),
    ("failure-W_FOM_UNVERIFIED", [fail("W_FOM_UNVERIFIED")]),
    ("failure-not-a-code", [fail("E_NEW_THING")]),
    ("failure-message-over-1024-utf8-bytes",
     [fail("E_RTI_CONNECT", "\N{LATIN SMALL LETTER E WITH ACUTE}" * 600)]),
]


@case("G-R14", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("name,steps", STATUS_FAULTS, ids=[f[0] for f in STATUS_FAULTS])
def test_a_status_record_outside_the_protocol_ends_the_session(tmp_path, name, steps):
    """NAT-15 (one UTF-8 JSON object per line, at most 65536 bytes, the stage order), OPS-30
    (a worker reports only its seven codes; E_RTI_TIMEOUT is the host's) and R37 (1024 UTF-8
    bytes): anything else on fd 3 is E_CAPTURE_SCHEMA, a terminal fault of the host's own,
    never retried."""
    session = run_case(tmp_path, [connect_and_join() + steps + [STALL]])
    assert session.shape() == [START(1, 0), DIAG(1, 0, "E_CAPTURE_SCHEMA"),
                               END(1, 0, "failure"), FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)]
    assert session.summary["workers"] == 1


def test_the_stage_order_before_the_join(tmp_path):
    """NAT-15: connect, running, join, running, resolve ... A worker that resolves before it
    joined breaks the order: E_CAPTURE_SCHEMA at generation 0."""
    session = run_case(tmp_path, [[stage("connect"), stage("running"), stage("resolve"), STALL]])
    assert session.shape() == [DIAG(0, 0, "E_CAPTURE_SCHEMA"),
                               FOOT("FAILED", "E_CAPTURE_SCHEMA", 0)]


@case("G-R14", paragraphs=("SPEC:277",))
def test_a_partial_line_is_never_accepted(tmp_path):
    """SPEC:277: never accept a partial line. A worker that exits cleanly after the orderly stop
    with half a frame on stdout broke the protocol (E_CAPTURE_SCHEMA); the half frame is not
    captured."""
    steps = connect_and_join() + [discover("o1", MS), {"do": "wait_term"},
                                  bad_line(b'{"event":{"type":"disc'), stage("resign"),
                                  stage("running"), stage("disconnect"), stage("running")]
    session = run_case(tmp_path, [steps], stop_on_waiting=1)
    assert session.shape() == [START(1, 0), DISC(1, MS), DIAG(1, MS, "E_CAPTURE_SCHEMA"),
                               END(1, MS, "failure"), FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)]


@case("G-R14", paragraphs=("SPEC:62",))
def test_nothing_of_a_previous_worker_is_carried_into_the_next(tmp_path):
    """SPEC:62: no data is buffered from a previous worker. The first worker dies with half a
    frame on stdout (an exit nobody asked for: E_RTI_CONNECT, OPS-19, retried); the second
    worker's frames are read from its own pipe from their first byte."""
    first = connect_and_join() + [discover("o1", MS),
                                  bad_line(b'{"event":{"type":"discover","object_to'),
                                  {"do": "exit", "code": 0}]
    second = joined_session(discover("o1", MS))
    session = run_case(tmp_path, [first, second], stop_on_waiting=2)
    assert session.shape() == [
        START(1, 0), DISC(1, MS), DIAG(1, MS, "E_RTI_CONNECT"), END(1, MS, "connection_lost"),
        START(2, S), DISC(2, S + MS), END(2, S + MS, "stop"), FOOT("COMPLETE", None, 2)]
    assert session.clock.sleeps == [(B1, S)]


# ================================================= NAT-08's conditions, one named test each

def _join_stage_only():
    return [stage("connect"), stage("running"), stage("join")]


@case("G-R14", paragraphs=("SPEC:62", "SPEC:277"))
def test_connection_failed_before_the_join_is_retried(tmp_path):
    """NAT-08, ConnectionFailed: E_RTI_CONNECT at generation 0 (the worker's own copy, so no
    second diagnostic), no generation_end (no generation is open), and a retry after 1 s
    (SPEC:62); the second worker joins, and its generation_start is the session origin
    (elapsed 0, CR-R2-05)."""
    session = run_case(tmp_path, [connect_refused(), joined_session()], stop_on_waiting=2)
    assert session.shape() == [DIAG(0, 0, "E_RTI_CONNECT"), START(1, 0), END(1, 0, "stop"),
                               FOOT("COMPLETE", None, 1)]
    assert session.clock.sleeps == [(B1, S)] and started(session) == [1, 2]
    assert session.summary["errors"] == {"E_RTI_CONNECT": 1}


@case("G-R14", paragraphs=("SPEC:62",))
def test_a_federation_that_does_not_exist_at_join_is_retried(tmp_path):
    """NAT-08, FederationExecutionDoesNotExist at join: E_RTI_CONNECT before any generation,
    retried like a refused connection."""
    first = _join_stage_only() + reported("E_RTI_CONNECT", "the federation does not exist")
    session = run_case(tmp_path, [first, joined_session()], stop_on_waiting=2)
    assert session.shape() == [DIAG(0, 0, "E_RTI_CONNECT"), START(1, 0), END(1, 0, "stop"),
                               FOOT("COMPLETE", None, 1)]
    assert session.clock.sleeps == [(B1, S)]


@case("G-R14", "G-R17", paragraphs=("SPEC:62", "SPEC:277"))
def test_connection_lost_ends_the_generation_and_is_retried(tmp_path):
    """NAT-08, connectionLost in the event loop: E_RTI_CONNECT in the open generation,
    generation_end connection_lost, and a retry after 1 s that joins as generation 2; the session
    stops COMPLETE because every boundary was recorded (R17's carried clause)."""
    first = connect_and_join() + lost(MS)
    session = run_case(tmp_path, [first, joined_session()], stop_on_waiting=2)
    assert session.shape() == [START(1, 0), DIAG(1, MS, "E_RTI_CONNECT"),
                               END(1, MS, "connection_lost"), START(2, S), END(2, S, "stop"),
                               FOOT("COMPLETE", None, 2)]
    assert session.summary["status"] == "COMPLETE" and session.summary["terminal_codes"] == []


@case("G-R14", paragraphs=("SPEC:62",))
def test_a_federate_name_in_use_is_never_retried(tmp_path):
    """NAT-08, FederateNameAlreadyInUse at join: E_FEDERATE_NAME at generation 0, no
    generation_end, FAILED; SPEC:62: name conflicts never retry."""
    session = run_case(tmp_path, [_join_stage_only() + reported("E_FEDERATE_NAME"),
                                  joined_session()])
    assert session.shape() == [DIAG(0, 0, "E_FEDERATE_NAME"),
                               FOOT("FAILED", "E_FEDERATE_NAME", 0)]
    assert started(session) == [1] and session.clock.sleeps == []


@case("G-R14", paragraphs=("SPEC:62", "SPEC:277"))
def test_a_profile_error_after_the_join_ends_its_generation_and_is_never_retried(tmp_path):
    """NAT-08, NameNotFound while resolving: generation_start comes right after the join, so the
    failure is inside generation 1 and consumes it: E_FOM_PROFILE, generation_end failure,
    FAILED; profile errors never retry (SPEC:62)."""
    steps = [stage("connect"), stage("running"), stage("join"), stage("running"),
             frame_step(event_generation_start()), stage("resolve")] + \
        reported("E_FOM_PROFILE", "NameNotFound: Spatial", MS)
    session = run_case(tmp_path, [steps, joined_session()])
    assert session.shape() == [START(1, 0), DIAG(1, MS, "E_FOM_PROFILE"),
                               END(1, MS, "failure"), FOOT("FAILED", "E_FOM_PROFILE", 1)]
    assert started(session) == [1]


def test_a_profile_error_before_the_join_has_no_generation(tmp_path):
    """NAT-08, CouldNotCreateLogicalTimeFactory at join: E_FOM_PROFILE at generation 0 and no
    generation_end; never retried."""
    session = run_case(tmp_path, [_join_stage_only() + reported("E_FOM_PROFILE")])
    assert session.shape() == [DIAG(0, 0, "E_FOM_PROFILE"), FOOT("FAILED", "E_FOM_PROFILE", 0)]


@case("G-R14", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("code,reason", [("E_CAPTURE_SCHEMA", "failure"), ("E_LIMIT", "limit")])
def test_a_capture_fault_or_a_limit_the_worker_reports(tmp_path, code, reason):
    """NAT-08: a name the worker cannot convert to UTF-8 (E_CAPTURE_SCHEMA, SPEC:289) and a
    value, tag, name or time over its limit (E_LIMIT, OPS-22) are reported by the worker, with
    its diagnostic copy; generation_end failure or limit; FAILED; never retried."""
    session = run_case(tmp_path, [connect_and_join() + [discover("o1", MS)]
                                  + reported(code, "the worker refused a callback", 2 * MS)])
    assert session.shape() == [START(1, 0), DISC(1, MS), DIAG(1, 2 * MS, code),
                               END(1, 2 * MS, reason), FOOT("FAILED", code, 1)]
    assert started(session) == [1]


@case("G-R14", paragraphs=("SPEC:277",))
def test_a_queue_overflow_reported_on_the_status_channel_alone(tmp_path):
    """SPEC:277 and R41: when the callback queue cannot carry the failure, the status channel
    does, and the host turns it into the diagnostic frame (the worker's message kept as data),
    then generation_end limit and a FAILED footer whose reason identifies the lost evidence."""
    message = "the callback queue is full: 4096 frames"
    steps = connect_and_join() + [discover("o1", MS), fail("E_QUEUE_OVERFLOW", message), EXIT_1]
    session = run_case(tmp_path, [steps])
    assert session.shape() == [START(1, 0), DISC(1, MS), DIAG(1, MS, "E_QUEUE_OVERFLOW"),
                               END(1, MS, "limit"), FOOT("FAILED", "E_QUEUE_OVERFLOW", 1)]
    assert message_at(session, 3) == message


@case("G-R14", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("copy", [True, False], ids=["with-its-copy", "status-only"])
def test_request_retraction_ends_the_generation_and_the_session_complete(tmp_path, copy):
    """SPEC:58, SPEC:281 and RED-08: requestRetraction invalidates the generation and ends it:
    E_RETRACTION_UNSUPPORTED (no object, no attribute) once, then generation_end retraction,
    whose invalidations carry reason generation_end; no rejoin (the retry list is closed); the
    footer is COMPLETE with no reason, because every boundary was recorded and the worker exited
    by itself (the E_ diagnostic makes the exit 3, round R6)."""
    tail = reported("E_RETRACTION_UNSUPPORTED", "requestRetraction", 3 * MS) if copy else \
        [fail("E_RETRACTION_UNSUPPORTED", "requestRetraction"), EXIT_1]
    steps = connect_and_join() + [discover("o1", MS), reflect_full("o1", 2 * MS)] + tail
    session = run_case(tmp_path, [steps, joined_session()])
    last = 3 * MS if copy else 2 * MS
    assert session.shape() == [START(1, 0), DISC(1, MS), REFL(1, 2 * MS),
                               DIAG(1, last, "E_RETRACTION_UNSUPPORTED"),
                               END(1, last, "retraction"), FOOT("COMPLETE", None, 1)]
    assert by_seq(session.observations())[4] == [
        ("diagnostic", None, None, "E_RETRACTION_UNSUPPORTED", None)]
    assert by_seq(session.observations())[5] == [("invalidated", "o1", EID_1, "generation_end", 1)]
    assert started(session) == [1]
    assert session.summary["status"] == "COMPLETE" and session.summary["terminal_codes"] == []
    assert session.summary["errors"] == {"E_RETRACTION_UNSUPPORTED": 1}
    assert message_at(session, 4) == "requestRetraction"


@case("G-R14", paragraphs=("SPEC:62", "SPEC:277"))
def test_an_exit_nobody_asked_for_is_a_lost_connection(tmp_path):
    """OPS-19: an unexpected worker exit is E_RTI_CONNECT, written by the host (the worker said
    nothing), generation_end connection_lost, retried within the same budget."""
    session = run_case(tmp_path, [connect_and_join() + [discover("o1", MS),
                                                        {"do": "exit", "code": 0}],
                                  joined_session()], stop_on_waiting=2)
    assert session.shape() == [START(1, 0), DISC(1, MS), DIAG(1, MS, "E_RTI_CONNECT"),
                               END(1, MS, "connection_lost"), START(2, S), END(2, S, "stop"),
                               FOOT("COMPLETE", None, 2)]


@case("G-R14", paragraphs=("SPEC:62", "SPEC:277"))
def test_a_worker_alive_without_its_channels_is_an_exit_nobody_asked_for(tmp_path):
    """CR-new-R5-22: a worker that closes stdout and fd 3 can report nothing more (SPEC:277).
    It has reported no failure and was not asked to stop, so nothing else bounds it (no stage is
    pending, NAT-03: no idle timeout): the host kills it once it has not exited one drain window
    (200 ms here, real clock) after the second channel ended, and records the exit nobody asked
    for (OPS-19: E_RTI_CONNECT, connection_lost, retried). Without that bound the session would
    wait for the duration (10 s) and end with a forced stop (FAILED E_RTI_TIMEOUT); here the
    second worker joins and the session stops COMPLETE. The pre-flight is `PROBE`'s."""
    steps = connect_and_join() + [discover("o1"), {"do": "close", "fd": 1},
                                  {"do": "close", "fd": 3}, STALL]
    session = run_case(tmp_path, [steps, joined_session()], stop_on_waiting=2, frozen=False,
                       drain_ns=200 * MS, deadline_ns=S, retry_delays_ns=(0, 0, 0),
                       duration_ns=10 * S, **PROBE)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), END(1, 0, "connection_lost"),
        START(2, 0), END(2, 0, "stop"), FOOT("COMPLETE", None, 2)])
    assert started(session) == [1, 2]
    events = [(e["event"], e.get("attempt")) for e in session.log_entries()]
    assert ("exit", 1) not in events and ("sigterm", 1) not in events


@case("A-SIGNAL", "G-R14", "G-R17", paragraphs=("SPEC:277",))
def test_a_worker_without_its_channels_that_was_asked_to_stop_is_bounded_by_the_stop(tmp_path):
    """CR-new-R5-22's other half (review finding R5-r2-F1): the silent-worker bound applies only
    while nothing else bounds the worker. Here the worker closes stdout and fd 3, then the
    session is stopped (SIGINT to this process once the worker waits): the orderly stop's own
    bound, the host deadline (5 s here), now governs it, so the worker may take longer than the
    drain window (500 ms) to exit by itself (1.5 s here) and the session still ends as an orderly
    stop: generation_end stop, COMPLETE, one worker, never killed (it logs its own exit with
    status 0). A host that applied the silent bound despite the stop would kill it 500 ms after
    the second channel ended and end FAILED E_RTI_CONNECT with generation_end connection_lost
    (the reviewer's mutant f7c). The stop reaches the host within milliseconds of the worker's
    `waiting`, well inside the 500 ms. Real clock, so the shape is compared without elapsed_ns."""
    steps = connect_and_join() + [discover("o1"), {"do": "close", "fd": 1},
                                  {"do": "close", "fd": 3}, {"do": "wait_term"},
                                  {"do": "sleep", "ms": 1500}, {"do": "exit", "code": 0}]
    session = run_case(tmp_path, [steps], stop_on_waiting=1, frozen=False, drain_ns=500 * MS,
                       deadline_ns=5 * S, retry_delays_ns=(0, 0, 0), duration_ns=20 * S)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0), END(1, 0, "stop"), FOOT("COMPLETE", None, 1)])
    assert started(session) == [1]
    assert session.summary["status"] == "COMPLETE" and session.summary["terminal_codes"] == []
    assert session.summary["workers"] == 1
    events = [(e["event"], e.get("attempt"), e.get("code")) for e in session.log_entries()]
    assert ("sigterm", 1, None) in events and ("exit", 1, 0) in events


@case("G-R14", "G-R17", paragraphs=("SPEC:277",))
def test_an_unclean_exit_during_the_orderly_stop(tmp_path):
    """The orderly stop ends COMPLETE only when the worker exits by itself with status 0
    (OPS-25); one that exits 3 after resigning is E_RTI_CONNECT, generation_end connection_lost,
    and, the stop having been asked for, no retry: FAILED."""
    steps = connect_and_join() + [{"do": "wait_term"}, stage("resign"), stage("running"),
                                  {"do": "exit", "code": 3}]
    session = run_case(tmp_path, [steps, joined_session()], stop_on_waiting=1)
    assert session.shape() == [START(1, 0), DIAG(1, 0, "E_RTI_CONNECT"),
                               END(1, 0, "connection_lost"), FOOT("FAILED", "E_RTI_CONNECT", 1)]
    assert started(session) == [1]


@case("G-R14", paragraphs=("SPEC:277",))
def test_after_a_reported_failure_frames_are_drained_for_one_window_then_the_worker_is_killed(
        tmp_path):
    """SPEC:277: after a reported failure the host captures the complete stdout frames that come
    within the drain window, then terminates the worker if it is still there. Real clock, a
    300 ms window: the frames written right after the failure record are captured, and the
    worker that then stalls is killed (it never logs an exit); the host's diagnostic carries the
    status record's message."""
    steps = connect_and_join() + [fail("E_RTI_CONNECT", "connection lost"), discover("o1"),
                                  discover("o2"), STALL]
    session = run_case(tmp_path, [steps], frozen=False, drain_ns=300 * MS, retry_delays_ns=())
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0, "o1"), DISC(1, 0, "o2"), DIAG(1, 0, "E_RTI_CONNECT"),
        END(1, 0, "connection_lost"), FOOT("FAILED", "E_RTI_CONNECT", 1)])
    assert [e["event"] for e in session.log_entries()] == ["version", "start"]
    assert message_at(session, 4) == "connection lost"


@case("G-R14", paragraphs=("SPEC:277",))
def test_a_retraction_whose_worker_must_be_killed_is_not_complete(tmp_path):
    """RED-08 with OPS-25 and SPEC:184 (forced termination cannot produce COMPLETE): the worker
    reports requestRetraction and then does not exit within the drain window; the host kills it,
    records E_RTI_TIMEOUT beside the retraction, still ends the generation with reason
    retraction, and the footer is FAILED E_RTI_TIMEOUT."""
    steps = connect_and_join() + [fail("E_RETRACTION_UNSUPPORTED", "requestRetraction"), STALL]
    session = run_case(tmp_path, [steps], frozen=False, drain_ns=200 * MS)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DIAG(1, 0, "E_RETRACTION_UNSUPPORTED"), DIAG(1, 0, "E_RTI_TIMEOUT"),
        END(1, 0, "retraction"), FOOT("FAILED", "E_RTI_TIMEOUT", 1)])
    assert session.summary["terminal_codes"] == ["E_RTI_TIMEOUT"]


@case("G-R14", "G-R34", "G-R41", paragraphs=("SPEC:277",))
def test_a_worker_over_its_rss_limit_is_killed_with_e_limit(tmp_path):
    """OPS-23 and R41: the host reads the worker's RSS every poll period through the seam; above
    512 MiB it kills the worker and records E_LIMIT, generation_end limit, FAILED, no retry."""
    holder = {}

    def rss_of(pid):
        waiting = any(e["event"] == "waiting" for e in holder["session"].log_entries())
        return 512 * 1024 * 1024 + 1 if waiting else 512 * 1024 * 1024

    session = Session(tmp_path, [joined_session(discover("o1"))], frozen=False,
                      rss_poll_ns=20 * MS, rss_of=rss_of)
    holder["session"] = session
    session.run()
    finished(session)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0), DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
        FOOT("FAILED", "E_LIMIT", 1)])
    assert [e["event"] for e in session.log_entries()] == ["version", "start", "waiting"]


@case("G-R14", paragraphs=("SPEC:62",))
def test_a_worker_that_cannot_be_started_again_is_a_dependency_failure(tmp_path):
    """The worker disappears during the session: the next spawn fails, which is recorded as
    E_DEPENDENCY_PIN at generation 0 (the pre-flight's code for a missing worker, OPS-18) and
    ends the session FAILED; nothing more is attempted. The spawn is tried after the 1 s
    backoff, so its diagnostic is stamped 1 s after the origin."""
    first = connect_and_join() + [{"do": "unlink_self"}] + lost(MS)
    session = run_case(tmp_path, [first, joined_session()])
    assert session.shape() == [START(1, 0), DIAG(1, MS, "E_RTI_CONNECT"),
                               END(1, MS, "connection_lost"), DIAG(0, S, "E_DEPENDENCY_PIN"),
                               FOOT("FAILED", "E_DEPENDENCY_PIN", 1)]
    assert started(session) == [1] and session.clock.sleeps == [(B1, S)]


_LOST = "connection lost"

#: (name, what the worker writes after its E_RTI_CONNECT copy, the capture, the terminal codes).
#: Each competing failure comes on stdout after the copy, or on fd 3 only once the host has
#: captured the copy (`await_capture`), so the order in which the host learns the two is fixed
#: (the copy first). Without that wait the status record raced the copy: when both pipes were
#: ready in one poll the host could read fd 3 first (round R8 found this test failing about one
#: run in two on the development Mac).
COMPETING = [
    ("a-line-the-host-refuses", [bad_line(b"x" * 65537 + b"\n"), STALL],
     [START(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
      FOOT("FAILED", "E_LIMIT", 1)], ["E_LIMIT", "E_RTI_CONNECT"]),
    ("a-diagnostic-frame-the-worker-writes",
     [copy_of("E_LIMIT", "a value over its limit"), EXIT_1],
     [START(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
      FOOT("FAILED", "E_LIMIT", 1)], ["E_LIMIT", "E_RTI_CONNECT"]),
    ("a-status-record-the-worker-writes",
     [{"do": "await_capture", "contains": "E_RTI_CONNECT"},
      fail("E_QUEUE_OVERFLOW", "the callback queue is full"), EXIT_1],
     [START(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), DIAG(1, 0, "E_QUEUE_OVERFLOW"),
      END(1, 0, "limit"), FOOT("FAILED", "E_QUEUE_OVERFLOW", 1)],
     ["E_QUEUE_OVERFLOW", "E_RTI_CONNECT"]),
    ("a-fault-the-reducer-derives",
     [discover("o1"), frame_step(event_discover("o1", "RENAMED")), STALL],
     [START(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), DISC(1, 0), DISC(1, 0), END(1, 0, "failure"),
      FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)], ["E_CAPTURE_SCHEMA", "E_RTI_CONNECT"]),
    ("a-second-competing-failure",
     [copy_of("E_LIMIT", "a value over its limit"), bad_line(b"{not json}\n"), STALL],
     [START(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
      FOOT("FAILED", "E_LIMIT", 1)], ["E_LIMIT", "E_CAPTURE_SCHEMA", "E_RTI_CONNECT"]),
]


@case("G-R14", paragraphs=("SPEC:62", "SPEC:277"))
@pytest.mark.parametrize("name,tail,shape,codes", COMPETING, ids=[c[0] for c in COMPETING])
def test_a_never_retried_failure_that_competes_with_a_lost_connection_ends_the_session(
        tmp_path, name, tail, shape, codes):
    """SPEC:62 (resource exhaustion, capture faults and limits never retry), OPS-02 (competing
    terminal failures), NAT-08 (one diagnostic frame per condition; the generation_end reason
    and the footer's reason_code come from the same code), RED-07 and RED-12 (a fault the
    reducer derives ends the generation with failure or limit, whatever came before), and
    CR-new-R5-21. The worker reports a lost connection (its E_RTI_CONNECT copy), which alone
    would be retried; while its frames are still drained, a failure that is never retried
    arrives: an oversize line, an E_LIMIT diagnostic frame of the worker's, an E_QUEUE_OVERFLOW
    on the status channel alone, or an inconsistent rediscovery (the reducer's E_CAPTURE_SCHEMA,
    in the output stream only, RED-01). The session is not retried; that failure has its
    diagnostic (the host's frame for the oversize line and the queue overflow, keeping the
    worker's message; the worker's own frame; the reducer's record), names generation_end's
    reason and the FAILED footer, and leads the summary's terminal codes. A second such failure
    (a malformed line after the worker's E_LIMIT) is only one more terminal code: the end of a
    session writes at most `_writer.END_FRAMES` frames."""
    steps = connect_and_join() + [copy_of("E_RTI_CONNECT", _LOST)] + tail
    session = run_case(tmp_path, [steps, joined_session()])
    assert session.shape() == shape
    assert started(session) == [1] and session.summary["workers"] == 1
    assert (session.summary["status"], session.summary["reason_code"]) == ("FAILED", codes[0])
    assert session.summary["terminal_codes"] == codes
    if name == "a-status-record-the-worker-writes":
        assert message_at(session, 3) == "the callback queue is full"
    if name == "a-fault-the-reducer-derives":
        assert by_seq(session.observations())[4] == [
            ("diagnostic", "o1", None, "E_CAPTURE_SCHEMA", None)]


@case("G-R14", paragraphs=("SPEC:62", "SPEC:277"))
def test_a_never_retried_failure_on_the_other_channel_wins_in_either_order(tmp_path):
    """The case of R5-r1-F3 and F6: the worker reports E_RTI_CONNECT on fd 3 alone, then writes
    an oversize line on stdout. The two channels keep no order between them, so the host may
    learn either first; either way the session is not retried, ends with an E_LIMIT diagnostic,
    generation_end limit and FAILED E_LIMIT, and E_LIMIT leads the terminal codes. Read first,
    the E_RTI_CONNECT report gets its own diagnostic (the worker's message); read after the
    oversize line, it comes from a worker the host has stopped listening to and adds nothing."""
    steps = connect_and_join() + [fail("E_RTI_CONNECT", _LOST), bad_line(b"x" * 65537 + b"\n"),
                                  STALL]
    session = run_case(tmp_path, [steps, joined_session()])
    shape = session.shape()
    assert shape[-3:] == [DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
                          FOOT("FAILED", "E_LIMIT", 1)]
    assert shape[:-3] in ([START(1, 0)], [START(1, 0), DIAG(1, 0, "E_RTI_CONNECT")])
    assert started(session) == [1] and session.summary["workers"] == 1
    assert session.summary["terminal_codes"][0] == "E_LIMIT"


@case("G-R14", "G-R34", paragraphs=("SPEC:277",))
def test_a_worker_over_its_rss_limit_while_it_drains_ends_the_session_with_e_limit(tmp_path):
    """OPS-23 with CR-new-R5-21: the worker reported a lost connection (its copy is captured) and
    is still alive in its drain window when its RSS passes 512 MiB (the probe reports so only
    once the copy is in the capture, so the order is fixed). The RSS limit is never retried: the
    host kills the worker, writes its E_LIMIT diagnostic after the worker's E_RTI_CONNECT,
    generation_end limit and FAILED E_LIMIT. Real clock, a 30 s drain window that the kill cuts
    short."""
    holder = {}

    def rss_of(pid):
        reported = b'"E_RTI_CONNECT"' in holder["session"].capture_bytes()
        return 512 * 1024 * 1024 + 1 if reported else 512 * 1024 * 1024

    steps = connect_and_join() + [copy_of("E_RTI_CONNECT", _LOST), STALL]
    session = Session(tmp_path, [steps, joined_session()], frozen=False, rss_poll_ns=20 * MS,
                      drain_ns=30 * S, rss_of=rss_of)
    holder["session"] = session
    session.run()
    finished(session)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
        FOOT("FAILED", "E_LIMIT", 1)])
    assert started(session) == [1]
    assert session.summary["terminal_codes"] == ["E_LIMIT", "E_RTI_CONNECT"]


# ================================================================== A-RECONNECT and the budget

@case("A-RECONNECT", "G-R14", "G-R08", "G-R17", paragraphs=("SPEC:62", "SPEC:275"))
def test_a_reconnect_after_three_delays_is_a_new_generation_with_a_new_uuid(tmp_path):
    """A-RECONNECT (OPS-28: the delays measured on the injected clock from the recorded failure
    to the next spawn), SPEC:62 and SPEC:275, under the frozen clock (start B1 = 7000 s).

    Worker 1 joins (origin B1, elapsed 0), discovers o1 at 1 ms and makes it eligible at 2 ms
    (snapshot and upsert, entity 781e68de..., revision 1), then loses the connection at 3 ms
    (its E_RTI_CONNECT copy; generation_end connection_lost stamped no earlier than 3 ms, which
    invalidates o1). Workers 2 and 3 are refused at connect: generation-0 diagnostics stamped
    at the frozen time minus the origin, 1 s and 3 s. Worker 4 joins as generation 2 at 7 s:
    the same o1 and the same triple 1.2.3 give a NEW entity_id (generation 2 in R26's name) and
    revision 1 again: nothing was retained. The sleeps were 1, 2 and 4 s, each begun at the
    moment its failure was recorded, and each worker started exactly when its sleep ended."""
    worker_1 = connect_and_join() + [discover("o1", MS), reflect_full("o1", 2 * MS)] + lost(3 * MS)
    worker_4 = joined_session(discover("o1", MS), reflect_full("o1", 2 * MS))
    session = run_case(tmp_path, [worker_1, connect_refused(), connect_refused(), worker_4],
                       stop_on_waiting=4)
    assert session.shape() == [
        START(1, 0), DISC(1, MS), REFL(1, 2 * MS), DIAG(1, 3 * MS, "E_RTI_CONNECT"),
        END(1, 3 * MS, "connection_lost"),
        DIAG(0, S, "E_RTI_CONNECT"), DIAG(0, 3 * S, "E_RTI_CONNECT"),
        START(2, 7 * S), DISC(2, 7 * S + MS), REFL(2, 7 * S + 2 * MS),
        END(2, 7 * S + 2 * MS, "stop"), FOOT("COMPLETE", None, 2)]
    assert session.clock.sleeps == [(B1, S), (B1 + S, 2 * S), (B1 + 3 * S, 4 * S)]
    bases = [entry["clock"] for entry in session.starts()]
    assert bases == [B1, B1 + S, B1 + 3 * S, B1 + 7 * S]
    recorded = [B1, B1 + S, B1 + 3 * S]
    assert [b - r for b, r in zip(bases[1:], recorded)] == [S, 2 * S, 4 * S]
    assert by_seq(session.observations()) == {
        3: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_1, 1)],
        4: [("diagnostic", None, None, "E_RTI_CONNECT", None)],
        5: [("invalidated", "o1", EID_1, "generation_end", 1)],
        6: [("diagnostic", None, None, "E_RTI_CONNECT", None)],
        7: [("diagnostic", None, None, "E_RTI_CONNECT", None)],
        10: [("snapshot", "o1", EID_GEN2, "ACTIVE", (), (EI, ET, FI, SP), 0),
             ("upsert", "o1", EID_GEN2, 1)],
        11: [("invalidated", "o1", EID_GEN2, "generation_end", 1)],
    }
    assert EID_GEN2 != EID_1
    assert session.summary["workers"] == 4 and session.summary["last_generation"] == 2


@case("A-RECONNECT", "G-R14", "G-R17", paragraphs=("SPEC:62",))
def test_a_successful_join_resets_the_retry_budget(tmp_path):
    """SPEC:62: after successful recovery the retry budget resets. Two losses, each followed by
    a rejoin after 1 s (the first delay again, not 2 s): generations 1, 2 and 3, each with its
    own boundaries, and COMPLETE (R17: a reconnect keeps the capture complete when every
    generation boundary was recorded)."""
    session = run_case(tmp_path, [connect_and_join() + lost(MS), connect_and_join() + lost(MS),
                                  joined_session()], stop_on_waiting=3)
    assert session.shape() == [
        START(1, 0), DIAG(1, MS, "E_RTI_CONNECT"), END(1, MS, "connection_lost"),
        START(2, S), DIAG(2, S + MS, "E_RTI_CONNECT"), END(2, S + MS, "connection_lost"),
        START(3, 2 * S), END(3, 2 * S, "stop"), FOOT("COMPLETE", None, 3)]
    assert session.clock.sleeps == [(B1, S), (B1 + S, S)]


@case("A-RECONNECT", "G-R14", "G-R17", paragraphs=("SPEC:62",))
def test_a_failed_final_reconnect_is_failed(tmp_path):
    """R17's carried clause: a failed final reconnect is FAILED. After the loss of generation 1
    the three attempts allowed (after 1, 2 and 4 s) are refused; no fourth is made, and the
    footer is FAILED with the last code, last_generation 1."""
    session = run_case(tmp_path, [connect_and_join() + lost(MS)] + [connect_refused()] * 3
                       + [joined_session()])
    assert session.shape() == [
        START(1, 0), DIAG(1, MS, "E_RTI_CONNECT"), END(1, MS, "connection_lost"),
        DIAG(0, S, "E_RTI_CONNECT"), DIAG(0, 3 * S, "E_RTI_CONNECT"),
        DIAG(0, 7 * S, "E_RTI_CONNECT"), FOOT("FAILED", "E_RTI_CONNECT", 1)]
    assert session.clock.sleeps == [(B1, S), (B1 + S, 2 * S), (B1 + 3 * S, 4 * S)]
    assert started(session) == [1, 2, 3, 4]
    assert session.summary["terminal_codes"] == ["E_RTI_CONNECT"]


@case("A-RECONNECT", "G-R14", paragraphs=("SPEC:62", "SPEC:275"))
def test_an_rti_that_never_answers_gives_the_unreachable_capture(tmp_path):
    """OPS-18: the header, one generation-0 diagnostic per failed attempt with elapsed_ns 0 (no
    join ever happened, SPEC:275), no generation_start or generation_end, and a FAILED footer
    with the last E_RTI_CONNECT and last_generation 0, after the 1, 2 and 4 s retries."""
    session = run_case(tmp_path, [connect_refused()] * 5)
    assert session.shape() == [DIAG(0, 0, "E_RTI_CONNECT")] * 4 + [
        FOOT("FAILED", "E_RTI_CONNECT", 0)]
    assert session.clock.sleeps == [(B1, S), (B1 + S, 2 * S), (B1 + 3 * S, 4 * S)]
    assert [entry["clock"] for entry in session.starts()] == [B1, B1 + S, B1 + 3 * S,
                                                              B1 + 7 * S]
    assert session.summary["records"]["diagnostic"] == 4


# ===================================================================== A-TIMEOUT and deadlines

TIMEOUTS = [
    ("start-up", [STALL], [DIAG(0, 0, "E_RTI_TIMEOUT")]),
    ("connect", [stage("connect"), STALL], [DIAG(0, 0, "E_RTI_TIMEOUT")]),
    ("join", [stage("connect"), stage("running"), stage("join"), STALL],
     [DIAG(0, 0, "E_RTI_TIMEOUT")]),
    ("resolve", [stage("connect"), stage("running"), stage("join"), stage("running"),
                 frame_step(event_generation_start()), stage("resolve"), STALL],
     [START(1, 0), DIAG(1, 0, "E_RTI_TIMEOUT"), END(1, 0, "timeout")]),
    ("request_update", connect_and_join() + [stage("request_update"), STALL],
     [START(1, 0), DIAG(1, 0, "E_RTI_TIMEOUT"), END(1, 0, "timeout")]),
]


@case("A-TIMEOUT", "G-R14", paragraphs=("SPEC:62", "SPEC:277"))
@pytest.mark.parametrize("name,first,head", TIMEOUTS, ids=[t[0] for t in TIMEOUTS])
def test_a_call_that_never_returns_is_killed_and_recorded_as_e_rti_timeout(tmp_path, name,
                                                                           first, head):
    """A-TIMEOUT, R14 and NAV-03: the host deadline applies from the start until the first
    status record, and from each stage record (connect, join, resolve, request_update) until its
    `running`; on expiry the host kills the worker at once (SIGKILL: it never logs a SIGTERM or
    an exit) and records E_RTI_TIMEOUT, which only the host authors (OPS-30), with
    generation_end timeout when a generation is open. It is transient (SPEC:62): the next worker
    joins and the session stops COMPLETE. Real clock, deadline shortened to 1 s through the
    seam; the 10 s default is held by `test_the_default_seam_holds_the_specifications_values`.
    The pre-flight is `PROBE`'s, so its version probe never shares the 1 s under test."""
    session = run_case(tmp_path, [first, joined_session()], stop_on_waiting=2, frozen=False,
                       deadline_ns=S, retry_delays_ns=(0, 0, 0), **PROBE)
    generation = 2 if head[0][0] == "generation_start" else 1
    assert session.shape(elapsed=False) == bare(head + [
        START(generation, 0), END(generation, 0, "stop"), FOOT("COMPLETE", None, generation)])
    events = [(e["event"], e.get("attempt")) for e in session.log_entries()]
    assert ("exit", 1) not in events and ("sigterm", 1) not in events
    diagnostics = [brief(r) for r in session.observations() if r["kind"] == "diagnostic"]
    assert diagnostics == [("diagnostic", None, None, "E_RTI_TIMEOUT", None)]
    assert session.summary["errors"] == {"E_RTI_TIMEOUT": 1}
    assert (session.summary["status"], session.summary["workers"]) == ("COMPLETE", 2)


@case("A-SIGNAL", "G-R14", "G-R17", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("where", ["resign", "disconnect", "no-stage"])
def test_a_stop_that_needs_force_is_failed_with_e_rti_timeout(tmp_path, where):
    """OPS-25 (from SPEC:74 and SPEC:184) and NAV-03: the orderly stop gives the worker at most
    the deadline; a worker blocked in resign or disconnect, or one that ignores the stop, is
    killed: E_RTI_TIMEOUT, generation_end timeout, footer FAILED E_RTI_TIMEOUT. Real clock,
    deadline 1 s; the pre-flight is `PROBE`'s."""
    tail = {"resign": [stage("resign"), STALL],
            "disconnect": [stage("resign"), stage("running"), stage("disconnect"), STALL],
            "no-stage": [STALL]}[where]
    steps = connect_and_join() + [discover("o1"), {"do": "wait_term"}] + tail
    session = run_case(tmp_path, [steps], stop_on_waiting=1, frozen=False, deadline_ns=S,
                       **PROBE)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0), DIAG(1, 0, "E_RTI_TIMEOUT"), END(1, 0, "timeout"),
        FOOT("FAILED", "E_RTI_TIMEOUT", 1)])
    assert ("exit", 1) not in [(e["event"], e.get("attempt")) for e in session.log_entries()]


# ================================================================ the live reducer and limits

@case("A-OBJECT-LIMIT", "G-R34", paragraphs=("SPEC:293",))
def test_ten_thousand_objects_then_one_more(tmp_path):
    """A-OBJECT-LIMIT at the real limit (RED-12, OPS-22, CR-R4-03): 10,000 discovers are
    admitted; the 10,001st is captured (SPEC:162: the raw frame first), and the reducer, which
    decides the limit, emits E_LIMIT for o10001 (no attribute) and sets its terminal flag. The
    host stops capturing (RED-12: the burst holds 10,003 discovers in one write, and the two
    behind the 10,001st are not captured), kills the worker, writes generation_end limit and a
    FAILED footer with E_LIMIT, and writes no E_LIMIT frame of its own (RED-01: the reducer's
    diagnostic is in the output stream already). Never retried."""
    session = run_case(tmp_path, [connect_and_join() + [burst(10003), STALL], joined_session()])
    shape = session.shape()
    assert shape[0] == START(1, 0)
    assert shape[1:10002] == [DISC(1, 0, f"o{n}") for n in range(1, 10002)]
    assert shape[10002:] == [END(1, 0, "limit"), FOOT("FAILED", "E_LIMIT", 1)]
    assert by_seq(session.observations()) == {
        10002: [("diagnostic", "o10001", None, "E_LIMIT", None)]}
    assert session.summary["errors"] == {"E_LIMIT": 1}
    assert session.summary["terminal_codes"] == ["E_LIMIT"] and started(session) == [1]


@case("G-R14", paragraphs=("SPEC:277",))
def test_an_inconsistent_rediscovery_ends_the_session(tmp_path):
    """RED-07 live: the rediscovery is captured, the reducer emits E_CAPTURE_SCHEMA for o1 and
    sets its terminal flag; the host writes generation_end failure and a FAILED footer with
    E_CAPTURE_SCHEMA, writes no diagnostic of its own, and does not retry."""
    steps = connect_and_join() + [discover("o1", MS),
                                  frame_step(event_discover("o1", "RENAMED"), 2 * MS), STALL]
    session = run_case(tmp_path, [steps, joined_session()])
    assert session.shape() == [START(1, 0), DISC(1, MS), DISC(1, 2 * MS),
                               END(1, 2 * MS, "failure"),
                               FOOT("FAILED", "E_CAPTURE_SCHEMA", 1)]
    assert by_seq(session.observations()) == {
        3: [("diagnostic", "o1", None, "E_CAPTURE_SCHEMA", None)]}
    assert started(session) == [1]


def test_in_existing_mode_every_generation_warns_its_fom_unverified(tmp_path):
    """R11, RED-01 and OPS-19: W_FOM_UNVERIFIED is derived by the reducer at each
    generation_start of an existing-mode session and is never a capture frame."""
    session = run_case(tmp_path, [connect_and_join() + lost(MS), joined_session()],
                       config=example_config("config-existing.json"), stop_on_waiting=2)
    assert [item[3] for item in session.shape() if item[0] == "diagnostic"] == ["E_RTI_CONNECT"]
    observed = by_seq(session.observations())
    assert observed[1] == [("diagnostic", None, None, "W_FOM_UNVERIFIED", None)]
    assert observed[4] == [("diagnostic", None, None, "W_FOM_UNVERIFIED", None)]


@case("G-R34")
def test_untrusted_strings_from_the_worker_are_kept_as_data(tmp_path):
    """R34 and R40: externally received content is preserved as untrusted data. A name with
    control, bidirectional and line-separator characters and a tag of arbitrary bytes are
    captured exactly as received (escaped by the canonical writer, never interpreted), and the
    session goes on."""
    name = ("\N{RIGHT-TO-LEFT OVERRIDE}evil\x1b[31m\N{LINE SEPARATOR}\x00"
            "\N{ARABIC LETTER MARK}")
    tag = bytes(range(256)).hex()
    steps = joined_session(frame_step(event_discover("o1", name), MS),
                           frame_step(event_remove("o1", tag_hex=tag), 2 * MS))
    session = run_case(tmp_path, [steps], stop_on_waiting=1)
    records = session.records()
    assert records[2]["event"]["name"] == name and records[3]["event"]["tag_hex"] == tag
    assert session.summary["status"] == "COMPLETE"


# ====================================================================== time (G-R08, SPEC:275)

@case("G-R08", "G-R14", paragraphs=("SPEC:275",))
def test_the_origin_is_the_first_generation_start_across_workers(tmp_path):
    """R08's carried clause (SPEC:275): the first generation_start's monotonic_ns is the session
    origin, every elapsed_ns is a subtraction from it, and the origin is kept across reconnects
    and worker restarts; frames before the first join carry 0.

    Worker 1 is refused at B1 (its diagnostic: 0). Worker 2 starts at B1 + 1 s and joins 5 ms
    later: the origin is B1 + 1 s + 5 ms. Its frames at +6 and +9 ms carry 1 and 4 ms, its loss
    at +10 ms carries 5 ms, and the host's generation_end, stamped with the frozen time
    (before the origin), is held at 5 ms (never below the previous frame, OPV-01). The join
    reset the budget, so worker 3 starts 1 s later at B1 + 2 s and joins at +7 ms: 1 s + 2 ms;
    its frame at +8 ms: 1 s + 3 ms."""
    second = connect_and_join(dt=5 * MS) + [discover("o1", 6 * MS), discover("o2", 9 * MS)] + \
        lost(10 * MS)
    third = connect_and_join(dt=7 * MS) + [discover("o1", 8 * MS)] + orderly_stop()
    session = run_case(tmp_path, [connect_refused(), second, third], stop_on_waiting=3)
    assert session.shape() == [
        DIAG(0, 0, "E_RTI_CONNECT"), START(1, 0), DISC(1, MS), DISC(1, 4 * MS, "o2"),
        DIAG(1, 5 * MS, "E_RTI_CONNECT"), END(1, 5 * MS, "connection_lost"),
        START(2, S + 2 * MS), DISC(2, S + 3 * MS), END(2, S + 3 * MS, "stop"),
        FOOT("COMPLETE", None, 2)]
    assert session.clock.sleeps == [(B1, S), (B1 + S, S)]


@case("G-R08", paragraphs=("SPEC:289",))
def test_a_live_effective_time_past_year_9998_ends_the_session_with_e_config(tmp_path):
    """R08's carried clause (SPEC:289: overflow terminates with E_CONFIG). Epoch
    9998-12-31T23:59:59.999000Z leaves 999 us: a frame 999,999 ns after the origin is effective
    at 23:59:59.999999 and is captured; one at 1,000,000 ns would be 9999-01-01 and is not. The
    host writes E_CONFIG and generation_end failure, both stamped at the last admissible
    instant (999,999 ns, never later), and a FAILED footer; never retried. The worker's frames
    are stamped 2 ms before the frozen time (dt negative), so the host's own clock reads 2 ms
    after the origin when it writes: past the last admissible instant, which it never stamps."""
    config = example_config(time_policy={"mode": "external_elapsed",
                                         "epoch": "9998-12-31T23:59:59.999000Z",
                                         "basis": "Synthetic 1x scenario clock"})
    steps = connect_and_join(dt=-2 * MS) + [discover("o1", -2 * MS + 999_999),
                                            discover("o2", -2 * MS + 1_000_000), STALL]
    session = run_case(tmp_path, [steps, joined_session()], config=config)
    assert session.shape() == [START(1, 0), DISC(1, 999_999), DIAG(1, 999_999, "E_CONFIG"),
                               END(1, 999_999, "failure"), FOOT("FAILED", "E_CONFIG", 1)]
    assert started(session) == [1]


# ===================================================================== stopping (OPS-15, OPS-25)

@case("A-SIGNAL", "G-R14", "G-R17", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_the_orderly_stop_in_process(tmp_path, signum):
    """SPEC:184 (SIGTERM performs the same bounded orderly shutdown as SIGINT) and SPEC:277: the
    host sends SIGTERM to the worker, keeps capturing the frames of its last batch, follows its
    resign and disconnect, and once it has exited by itself with status 0 writes generation_end
    stop and a COMPLETE footer."""
    steps = connect_and_join() + [discover("o1", MS), reflect_full("o1", 2 * MS),
                                  {"do": "wait_term"}, discover("o2", 3 * MS), stage("resign"),
                                  stage("running"), stage("disconnect"), stage("running")]
    session = Session(tmp_path, [steps]).run(stop_on_waiting=1, signum=signum)
    finished(session)
    assert session.shape() == [START(1, 0), DISC(1, MS), REFL(1, 2 * MS),
                               DISC(1, 3 * MS, "o2"), END(1, 3 * MS, "stop"),
                               FOOT("COMPLETE", None, 1)]
    assert by_seq(session.observations()) == {
        3: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_1, 1)],
        5: [("invalidated", "o1", EID_1, "generation_end", 1)]}
    assert (session.summary["status"], session.summary["reason_code"],
            session.summary["terminal_codes"]) == ("COMPLETE", None, [])
    assert [e["event"] for e in session.log_entries()] == ["version", "start", "waiting",
                                                           "sigterm", "exit"]


@case("G-R14", "G-R17", paragraphs=("SPEC:62",))
def test_a_stop_before_any_join_is_failed(tmp_path):
    """OPS-15: a stop before any join ends FAILED. With no failed attempt before it there is no
    last connection code, so the host records E_RTI_CONNECT for the session that never joined;
    the worker, stopped while connected, disconnects and exits 0."""
    steps = [stage("connect"), stage("running"), {"do": "wait_term"}, stage("disconnect"),
             stage("running")]
    session = run_case(tmp_path, [steps], stop_on_waiting=1)
    assert session.shape() == [DIAG(0, 0, "E_RTI_CONNECT"), FOOT("FAILED", "E_RTI_CONNECT", 0)]


@case("G-R14", "G-R17", paragraphs=("SPEC:62",))
def test_a_stop_during_a_reconnect_attempt_is_failed_with_the_last_code(tmp_path):
    """OPS-15: after the loss of generation 1, a stop while the next worker is still connecting
    ends FAILED with the last connection code (no new diagnostic)."""
    second = [stage("connect"), stage("running"), {"do": "wait_term"}, stage("disconnect"),
              stage("running")]
    session = run_case(tmp_path, [connect_and_join() + lost(MS), second], stop_on_waiting=2)
    assert session.shape() == [START(1, 0), DIAG(1, MS, "E_RTI_CONNECT"),
                               END(1, MS, "connection_lost"), FOOT("FAILED", "E_RTI_CONNECT", 1)]


@case("G-R14", paragraphs=("SPEC:62",))
def test_the_duration_ending_during_a_backoff_is_failed_with_the_last_code(tmp_path):
    """OPS-15: the duration bound is counted from the header write on the host's clock; when it
    ends during a backoff the session ends FAILED with the last connection code, and the sleep
    was cut to the end of the duration (here 600 ms into a 1 s delay)."""
    session = run_case(tmp_path, [connect_and_join() + lost(MS), joined_session()],
                       duration_ns=600 * MS)
    assert session.shape() == [START(1, 0), DIAG(1, MS, "E_RTI_CONNECT"),
                               END(1, MS, "connection_lost"), FOOT("FAILED", "E_RTI_CONNECT", 1)]
    assert session.clock.sleeps == [(B1, 600 * MS)] and started(session) == [1]


@case("A-SIGNAL", "G-R14", "G-R17", paragraphs=("SPEC:277",))
def test_the_duration_bound_performs_the_orderly_stop(tmp_path):
    """OPS-15: the duration is counted on the host's clock from the header write, and its end
    performs the same orderly stop as SIGINT. A 60 s duration; the frozen clock is moved 60 s on
    while the joined worker waits: SIGTERM, resign, disconnect, generation_end stop stamped at
    60 s after the origin, COMPLETE."""
    session = Session(tmp_path, [joined_session(discover("o1", MS))], duration_ns=60 * S)
    session.run(advance_on_waiting=(1, 60 * S))
    finished(session)
    assert session.shape() == [START(1, 0), DISC(1, MS), END(1, 60 * S, "stop"),
                               FOOT("COMPLETE", None, 1)]
    assert "sigterm" in [e["event"] for e in session.log_entries()]



# ============================================== the durable capture (R34, SPEC:293, A-FILE-LIMIT)

def expected_header(config=None) -> dict:
    """The header the tests expect for a frozen session: R15's members, the packaged pin map
    and the frozen audit time (built here, not by the product)."""
    return {"type": "header", "capture_version": 1, "profile": "SC-HLA-RPR2-OBS-1",
            "adapter_version": "1.0.0", "config": config or example_config(),
            "pins": {name: entry["sha256"] for name, entry in packaged_pins().items()},
            "record_created_at": AUDIT_TEXT}


def expected_lines(discovers: int) -> list[bytes]:
    """The capture lines (LF included) of a frozen session that joins and discovers o1 ... oN at
    elapsed 0, by the tests' own canonical writer and chain (`CaptureBuilder`)."""
    builder = CaptureBuilder(expected_header()).frame(1, 0, event_generation_start())
    for n in range(1, discovers + 1):
        builder.frame(1, 0, event_discover(f"o{n}"))
    return [line + b"\n" for line in builder.lines()]


def with_limits(**members):
    return dataclasses.replace(limits_module.V1, **members)


@case("A-FILE-LIMIT", "G-R34", "G-R15", "G-R41", paragraphs=("SPEC:293",))
@pytest.mark.parametrize("slack,admitted", [(0, 5), (-1, 4)], ids=["exactly-at", "one-byte-short"])
@case("G-R40", paragraphs=("SPEC:293",))
def test_the_capture_keeps_its_reserve_and_never_passes_the_file_limit(tmp_path, slack, admitted):
    """A-FILE-LIMIT through the seam (OPS-21), SPEC:293 and R15's carried clause: a frame that
    would enter the last `capture_reserve_bytes` of the file budget is not written; the session
    stops with E_LIMIT, and the terminal diagnostic, generation_end limit and the FAILED footer
    use the reserve without passing the limit.

    The budget is set from the tests' own lines: the file limit is the size of the header,
    generation_start and five discovers, plus `slack`, plus a 4096-byte reserve. With slack 0 the
    fifth discover ends exactly at the start of the reserve and is written (the limit is
    inclusive, "fail before exceeding"); one byte less and only four are. Those lines are byte
    for byte the tests' own."""
    lines = expected_lines(8)
    budget = sum(len(line) for line in lines[:7]) + slack
    limits = with_limits(capture_file_bytes=budget + 4096, capture_reserve_bytes=4096)
    session = run_case(tmp_path, [connect_and_join() + [burst(8), STALL], joined_session()],
                       limits=limits)
    data = session.capture_bytes()
    written = b"".join(lines[:2 + admitted])
    assert data.startswith(written)
    assert len(written) <= budget < len(written) + len(lines[2 + admitted])
    assert session.shape()[1 + admitted:] == [DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
                                              FOOT("FAILED", "E_LIMIT", 1)]
    assert len(data) <= budget + 4096
    assert started(session) == [1]
    assert by_seq(session.observations()) == {
        admitted + 2: [("diagnostic", None, None, "E_LIMIT", None)]}
    assert (session.summary["status"], session.summary["reason_code"],
            session.summary["terminal_codes"], session.summary["frames"]) == (
        "FAILED", "E_LIMIT", ["E_LIMIT"], admitted + 3)


@case("A-FILE-LIMIT", "G-R34", paragraphs=("SPEC:293",))
def test_a_retry_whose_frames_would_enter_the_reserve_ends_the_session(tmp_path):
    """SPEC:293: the frames of a retry are not the end of the session, so they may not use the
    reserve. The worker reports a lost connection on the status channel alone after the budget
    is exactly used: the host's E_RTI_CONNECT diagnostic would enter the reserve, so the session
    ends there with E_LIMIT, generation_end limit and FAILED, and is not retried."""
    lines = expected_lines(3)
    budget = sum(len(line) for line in lines)
    limits = with_limits(capture_file_bytes=budget + 4096, capture_reserve_bytes=4096)
    steps = connect_and_join() + [burst(3), fail("E_RTI_CONNECT", "connection lost"), EXIT_1]
    session = run_case(tmp_path, [steps, joined_session()], limits=limits)
    assert session.capture_bytes().startswith(b"".join(lines))
    assert session.shape()[4:] == [DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"),
                                   FOOT("FAILED", "E_LIMIT", 1)]
    assert started(session) == [1]


@case("G-R34", paragraphs=("SPEC:293",))
def test_the_frame_limit_keeps_room_for_the_end_of_the_session(tmp_path):
    """OPS-21 through the seam: the verifier counts every frame against frames_per_session, the
    end's too, so the host keeps room for the most frames an end writes and stops with E_LIMIT
    when a normal frame would take it. The most an end writes is five (the first condition's
    diagnostic, a competing never-retried failure's, a forced retraction's E_RTI_TIMEOUT,
    generation_end and a generation-0 E_IO). With 8 frames per session, 8 - 5 = 3 normal frames:
    generation_start and two discovers; the third discover would be a fourth, so E_LIMIT and
    generation_end end the session: 5 frames."""
    session = run_case(tmp_path, [connect_and_join() + [burst(8), STALL]],
                       limits=with_limits(frames_per_session=8))
    assert session.shape() == [START(1, 0)] + [DISC(1, 0, f"o{n}") for n in range(1, 3)] + [
        DIAG(1, 0, "E_LIMIT"), END(1, 0, "limit"), FOOT("FAILED", "E_LIMIT", 1)]
    assert session.summary["frames"] == 5


@case("G-R34", paragraphs=("SPEC:293",))
def test_an_end_that_does_not_fit_is_not_claimed(tmp_path):
    """SPEC:293 with a reserve (through the seam) too small for the end of the session: the
    terminal diagnostic cannot be written without passing the file limit, so nothing more is
    written; no footer is claimed, the capture is an incomplete one ending on a whole line,
    and the summary says INCOMPLETE with E_LIMIT."""
    lines = expected_lines(3)
    budget = sum(len(line) for line in lines)
    session = run_case(tmp_path, [connect_and_join() + [burst(5), STALL]],
                       limits=with_limits(capture_file_bytes=budget + 10,
                                          capture_reserve_bytes=10))
    assert session.capture_bytes() == b"".join(lines)
    assert (session.summary["status"], session.summary["reason_code"],
            session.summary["terminal_codes"]) == ("INCOMPLETE", None, ["E_LIMIT"])


def test_a_header_over_the_budget_is_refused_before_any_worker(tmp_path):
    """Through the seam: a file limit that cannot even hold the header and its reserve refuses
    the session with E_LIMIT (path output_dir) before a worker starts; nothing was written."""
    session = Session(tmp_path, [joined_session()],
                      limits=with_limits(capture_file_bytes=1000, capture_reserve_bytes=500))
    with pytest.raises(HlaError) as caught:
        session.run()
    assert (caught.value.code, caught.value.path) == ("E_LIMIT", "output_dir")
    assert session.capture_bytes() == b"" and session.starts() == []


class _FailingCapture:
    """The capture opened by the package, but taking at most `budget` more bytes: a write that
    meets the end takes what fits (as a full disk or RLIMIT_FSIZE do), the next raises ENOSPC."""

    def __init__(self, stream, budget):
        self.stream = stream
        self.budget = budget

    def write(self, data):
        if self.budget == 0:
            raise OSError(errno.ENOSPC, "No space left on device")
        taken = self.stream.write(data[:self.budget])
        self.budget -= taken
        return taken

    def fileno(self):
        return self.stream.fileno()

    def close(self):
        self.stream.close()


def failing_opener(budget):
    def open_capture(directory_fd, name):
        return _FailingCapture(_writer.open_capture(directory_fd, name), budget)
    return open_capture


@case("A-DISK", "G-R34", "G-R15", paragraphs=("SPEC:293",))
@pytest.mark.parametrize("where,extra", [("inside-a-frame", 30), ("between-lines", 0)])
def test_a_full_disk_is_e_io_and_never_a_complete_capture(tmp_path, where, extra):
    """A-DISK with an injected writer (OPS-24) and R15's carried clause: the disk fills while the
    session captures (the third discover is cut after 30 bytes, or not begun). The host records
    E_IO, kills the worker, writes nothing more to the capture (no footer is ever claimed after
    an I/O failure, SPEC:293), and the capture verifies as the incomplete prefix it is."""
    lines = expected_lines(4)
    budget = sum(len(line) for line in lines[:4]) + extra
    session = run_case(tmp_path, [connect_and_join() + [burst(4), STALL], joined_session()],
                       open_capture=failing_opener(budget))
    assert session.capture_bytes() == b"".join(lines[:4]) + lines[4][:extra]
    assert (session.summary["status"], session.summary["reason_code"],
            session.summary["terminal_codes"], session.summary["last_seq"]) == (
        "INCOMPLETE", None, ["E_IO"], 3)
    assert session.observations() == []
    assert started(session) == [1]
    assert "exit" not in [e["event"] for e in session.log_entries()]


@case("A-DISK", "G-R34", paragraphs=("SPEC:293",))
def test_a_full_disk_at_the_footer_claims_no_footer(tmp_path):
    """A-DISK at the last record: the orderly stop's generation_end is written, the footer is
    cut; the capture is incomplete at the footer's line and the summary does not claim it."""
    lines = expected_lines(1)
    end = CaptureBuilder(expected_header()).frame(1, 0, event_generation_start()).frame(
        1, 0, event_discover("o1")).frame(1, 0, event_generation_end("stop")).lines()[-1] + b"\n"
    budget = sum(len(line) for line in lines) + len(end) + 20
    session = run_case(tmp_path, [joined_session(discover("o1"))], stop_on_waiting=1,
                       open_capture=failing_opener(budget))
    data = session.capture_bytes()
    assert data.startswith(b"".join(lines) + end) and len(data) == budget
    assert session.summary["status"] == "INCOMPLETE"
    assert session.summary["terminal_codes"] == ["E_IO"]


@case("A-DISK", "G-R34", paragraphs=("SPEC:293",))
def test_an_fsync_that_fails_is_e_io(tmp_path):
    """OPS-24: an fsync that fails leaves nothing durable beyond the last good one, so it is an
    I/O failure like a write: E_IO, no footer."""
    calls = []

    def fsync(fd):
        calls.append(fd)
        if len(calls) == 4:
            raise OSError(errno.EIO, "Input/output error")
        os.fsync(fd)

    session = run_case(tmp_path, [joined_session(discover("o1"))], stop_on_waiting=1,
                       fsync=fsync)
    # The 4th fsync is generation_end's (after the directory, the header and generation_start):
    # that line reached the file, nothing after it was written.
    assert session.shape() == [START(1, 0), DISC(1, 0), END(1, 0, "stop")]
    assert (session.summary["status"], session.summary["last_seq"]) == ("INCOMPLETE", 3)
    assert session.summary["terminal_codes"] == ["E_IO"]


def fsync_recorder():
    """An fsync seam that records, for each call, "directory" or the file's size then."""
    sizes = []

    def fsync(fd):
        info = os.fstat(fd)
        sizes.append("directory" if stat.S_ISDIR(info.st_mode) else info.st_size)
        os.fsync(fd)
    return sizes, fsync


def line_counts(data: bytes, sizes: list) -> list:
    ends = []
    total = 0
    for line in data.split(b"\n")[:-1]:
        total += len(line) + 1
        ends.append(total)
    return [s if s == "directory" else ends.index(s) + 1 for s in sizes]


@case("G-R34", paragraphs=("SPEC:293",))
def test_fsync_follows_the_hundred_frame_rule_and_every_boundary(tmp_path):
    """R34 and OPS-24: the directory is synced once its files exist, then the capture after the
    header, after every generation_start and generation_end and after the footer, and otherwise
    no later than the 100th unsynced line. A session of generation_start, 250 discovers,
    generation_end and footer: syncs after lines 1, 2, 102, 202, 253 and 254 (by line count)."""
    sizes, fsync = fsync_recorder()
    session = run_case(tmp_path, [joined_session(burst(250))], stop_on_waiting=1, fsync=fsync)
    assert line_counts(session.capture_bytes(), sizes) == ["directory", 1, 2, 102, 202, 253,
                                                            254]


@case("G-R34", paragraphs=("SPEC:293",))
def test_fsync_after_the_interval_without_new_data(tmp_path):
    """OPS-24: timer-driven; no line stays unsynced longer than the interval (here 100 ms
    through the seam, real clock): the discover written before the worker pauses for 500 ms is
    synced on its own, before anything else arrives."""
    sizes, fsync = fsync_recorder()
    steps = joined_session(discover("o1"), {"do": "sleep", "ms": 500}, discover("o2"))
    session = run_case(tmp_path, [steps], stop_on_waiting=1, frozen=False,
                       fsync_interval_ns=100 * MS, fsync=fsync)
    counts = line_counts(session.capture_bytes(), sizes)
    assert counts[:4] == ["directory", 1, 2, 3] and counts[-2:] == [5, 6]
    assert set(counts[4:-2]) <= {4}


def record_syncs_and_sleeps(session) -> list:
    """Replace the session's fsync and sleep seams by recorders on one list: ("fsync", the line
    count the file then ends at, or "directory") and ("sleep", duration); the sleep is still the
    frozen clock's."""
    events = []

    def fsync(fd):
        info = os.fstat(fd)
        events.append(("fsync", "directory" if stat.S_ISDIR(info.st_mode) else info.st_size))
        os.fsync(fd)

    def sleep(duration_ns, wake_fd):
        events.append(("sleep", duration_ns))
        session.clock.sleep(duration_ns, wake_fd)

    session.seams = dataclasses.replace(session.seams, fsync=fsync, sleep=sleep)
    return events


def in_lines(events: list, data: bytes) -> list:
    sizes = [value for kind, value in events if kind == "fsync"]
    lines = iter(line_counts(data, sizes))
    return [("fsync", next(lines)) if kind == "fsync" else (kind, value)
            for kind, value in events]


#: (name, attempts, attempt to stop on, capture shape, fsync/sleep sequence by line count).
BACKOFFS = [
    ("the-workers-copy", [connect_refused(), joined_session()], 2,
     [DIAG(0, 0, "E_RTI_CONNECT"), START(1, 0), END(1, 0, "stop"), FOOT("COMPLETE", None, 1)],
     ["directory", 1, 2, ("sleep", S), 3, 4, 5]),
    ("the-hosts-own", [[stage("connect"), {"do": "exit", "code": 1}], joined_session()], 2,
     [DIAG(0, 0, "E_RTI_CONNECT"), START(1, 0), END(1, 0, "stop"), FOOT("COMPLETE", None, 1)],
     ["directory", 1, 2, ("sleep", S), 3, 4, 5]),
    ("an-rti-that-never-answers", [connect_refused()] * 4, None,
     [DIAG(0, 0, "E_RTI_CONNECT")] * 4 + [FOOT("FAILED", "E_RTI_CONNECT", 0)],
     ["directory", 1, 2, ("sleep", S), 3, ("sleep", 2 * S), 4, ("sleep", 4 * S), 6]),
]


@case("G-R34", "G-R14", paragraphs=("SPEC:62", "SPEC:293"))
@pytest.mark.parametrize("name,attempts,stop_on,shape,expected", BACKOFFS,
                         ids=[b[0] for b in BACKOFFS])
def test_nothing_waits_unsynced_through_a_reconnect_backoff(tmp_path, name, attempts, stop_on,
                                                            shape, expected):
    """OPS-24 and R34 (no line unsynced longer than 250 ms) with SPEC:62's backoff (R5-r1-F1):
    the diagnostic a failed attempt leaves before any generation is not a boundary, and the host
    writes nothing while it waits 1, 2 or 4 s, so it syncs that line before the wait begins (the
    timer is not served during the wait). Under the frozen clock the fsync of each such line
    comes before its sleep: the worker's own copy, the host's E_RTI_CONNECT for an exit nobody
    asked for, and OPS-18's unreachable RTI (the fourth refusal is not retried, so the footer's
    sync covers it)."""
    session = Session(tmp_path, attempts)
    events = record_syncs_and_sleeps(session)
    session.run(stop_on_waiting=stop_on)
    finished(session)
    assert session.shape() == shape
    assert in_lines(events, session.capture_bytes()) == [
        item if isinstance(item, tuple) else ("fsync", item) for item in expected]


@case("A-DISK", "G-R34", paragraphs=("SPEC:293",))
def test_an_fsync_that_fails_before_a_backoff_ends_the_session_with_e_io(tmp_path):
    """OPS-24 and SPEC:293: the sync before a backoff failing is an I/O failure like any other:
    no wait, no next worker, nothing more written, no footer; the summary says INCOMPLETE with
    E_IO. The third fsync is that one (after the directory's and the header's)."""
    session = Session(tmp_path, [connect_refused(), joined_session()])
    calls = []

    def fsync(fd):
        calls.append(fd)
        if len(calls) == 3:
            raise OSError(errno.EIO, "Input/output error")
        os.fsync(fd)

    session.seams = dataclasses.replace(session.seams, fsync=fsync)
    session.run()
    finished(session)
    assert session.shape() == [DIAG(0, 0, "E_RTI_CONNECT")]
    assert (session.summary["status"], session.summary["terminal_codes"],
            session.summary["last_seq"]) == ("INCOMPLETE", ["E_IO"], 1)
    assert session.clock.sleeps == [] and started(session) == [1]


@case("G-R34", paragraphs=("SPEC:293",))
def test_every_frame_is_on_disk_before_the_reducer_sees_it(tmp_path, monkeypatch):
    """R34: the host writes the raw frame and flushes it before applying the reducer. Every call
    of the reducer (`reduce_admitted`, the entry for a frame the writer's chain has just admitted,
    CR-L07) finds its frame's canonical line already at the end of capture.jsonl."""
    seen = []
    original = host.reducer.reduce_admitted
    holder = {}

    def watched(state, frame):
        line = canonical(frame) + b"\n"
        seen.append(holder["session"].capture_bytes().endswith(line))
        return original(state, frame)

    monkeypatch.setattr(host.reducer, "reduce_admitted", watched)
    session = Session(tmp_path, [joined_session(discover("o1", MS), reflect_full("o1", 2 * MS))])
    holder["session"] = session
    session.run(stop_on_waiting=1)
    monkeypatch.undo()
    finished(session)
    assert seen == [True] * 4


# ======================================================== the host as a process of its own

#: A host in a child process: reads a JSON spec, may close descriptors or set RLIMIT_FSIZE first,
#: may kill itself with SIGKILL while writing a chosen capture line, runs `run_session`, and
#: prints the summary (or the refusal) as one JSON line.
DRIVER = r"""
import dataclasses, json, os, signal, sys
spec = json.loads(sys.argv[1])
sys.path.insert(0, spec["src"])
for fd in spec.get("close", ()):
    try:
        os.close(fd)
    except OSError:
        pass
if spec.get("rlimit"):
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE, (spec["rlimit"], spec["rlimit"]))
from synapse_hla import HlaError, _writer, host, limits

if spec.get("probe_pipe"):
    read_end, write_end = host._pipe()
    def is_open(fd):
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False
    print(json.dumps({"pipe": [read_end, write_end],
                      "low_open": [fd for fd in range(4) if is_open(fd)]}), flush=True)
    sys.exit(0)

class Killing:
    def __init__(self, stream, prefix, occurrence, keep):
        self.stream, self.prefix, self.left, self.keep = stream, prefix, occurrence, keep
    def write(self, data):
        if data.startswith(self.prefix):
            self.left -= 1
            if self.left == 0:
                os.write(self.stream.fileno(), data[:self.keep])
                os.kill(os.getpid(), signal.SIGKILL)
        return self.stream.write(data)
    def fileno(self):
        return self.stream.fileno()
    def close(self):
        self.stream.close()

kill = spec.get("kill")
def opener(directory_fd, name):
    stream = _writer.open_capture(directory_fd, name)
    if kill:
        return Killing(stream, kill["prefix"].encode(), kill["occurrence"], kill["keep"])
    return stream

seams = dataclasses.replace(host.V1, rss_of=lambda pid: 1 << 22,
                            wall_clock_us=lambda: spec["audit"], open_capture=opener,
                            **spec.get("seams", {}))
try:
    summary = host.run_session(spec["config"], spec["out"], environ=spec["environ"],
                               seams=seams)
    print(json.dumps({"summary": summary}), flush=True)
except HlaError as refusal:
    print(json.dumps({"refused": [refusal.code, refusal.path]}), flush=True)
"""


class HostProcess:
    """A session whose host is a child process (DRIVER), against the fake worker, real clock."""

    def __init__(self, root, attempts, **spec):
        self.session = Session(root, attempts, frozen=False)
        self.spec = {"src": str(PACKAGE_ROOT / "src"), "config": self.session.config,
                     "out": str(self.session.out), "environ": self.session.environ,
                     "audit": AUDIT_US, **spec}
        self.process = None

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-c", DRIVER, json.dumps(self.spec)],
            env=child_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self

    def wait_for(self, event, attempt=1, timeout_s=60):
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if any(e["event"] == event and e.get("attempt") == attempt
                   for e in self.session.log_entries()):
                return
            if self.process.poll() is not None:
                raise AssertionError(f"the host ended before {event}: {self.process.returncode}")
            time.sleep(0.005)
        raise AssertionError(f"no {event} within {timeout_s} s")

    def finish(self, timeout_s=60):
        out, err = self.process.communicate(timeout=timeout_s)
        self.returncode = self.process.returncode
        self.result = json.loads(out) if out.strip() else None
        self.stderr = err
        return self

    def check(self):
        pids = [e["pid"] for e in self.session.log_entries() if "pid" in e]
        summary = None if self.result is None else self.result.get("summary")
        return check_session(self.session.out, summary, pids, replay_root=self.session.root)


@case("A-SIGNAL", "G-R14", "G-R17", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_signal_to_a_real_host_process_stops_it_in_order(tmp_path, signum):
    """A-SIGNAL (SIGINT while running) and SPEC:184 (SIGTERM the same), with a real host
    process: the signal reaches the host (the worker, in its own process group, is told by the
    host), the host sends SIGTERM to the worker, the worker resigns and disconnects within the
    10 s deadline, and the host writes generation_end stop and a COMPLETE footer and returns
    normally (exit 0, the summary on stdout; R6 maps it to the exit code)."""
    run = HostProcess(tmp_path, [joined_session(discover("o1"), reflect_full("o1"))]).start()
    run.wait_for("waiting")
    run.process.send_signal(signum)
    run.finish(timeout_s=30)
    assert run.returncode == 0, run.stderr
    run.check()
    assert run.session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0), REFL(1, 0), END(1, 0, "stop"), FOOT("COMPLETE", None, 1)])
    assert by_seq(run.session.observations()) == {
        3: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_1, 1)],
        4: [("invalidated", "o1", EID_1, "generation_end", 1)]}
    assert run.result["summary"]["status"] == "COMPLETE"
    assert run.result["summary"]["records"] == {"diagnostic": 0, "snapshot": 1, "upsert": 1,
                                                "removed": 0, "invalidated": 1}
    assert [e["event"] for e in run.session.log_entries()] == ["version", "start", "waiting",
                                                               "sigterm", "exit"]


@case("A-SIGNAL", "G-R14", "G-R17", paragraphs=("SPEC:277",))
def test_a_second_signal_does_not_shorten_the_orderly_stop(tmp_path):
    """OPS-25: a second signal does not shorten the bound. The worker takes 400 ms to resign;
    a second SIGINT meanwhile changes nothing: COMPLETE."""
    steps = connect_and_join() + [{"do": "wait_term"}, {"do": "sleep", "ms": 400},
                                  stage("resign"), stage("running"), stage("disconnect"),
                                  stage("running")]
    run = HostProcess(tmp_path, [steps]).start()
    run.wait_for("waiting")
    run.process.send_signal(signal.SIGINT)
    run.wait_for("sigterm")
    run.process.send_signal(signal.SIGINT)
    run.finish(timeout_s=30)
    assert run.returncode == 0, run.stderr
    run.check()
    assert run.result["summary"]["status"] == "COMPLETE"


KILL_POINTS = [
    ("before-the-first-frame", '{"elapsed_ns"', 1, 0, 0),
    ("mid-generation", '{"elapsed_ns"', 3, 50, 2),
    ("during-the-footer", '{"last_generation"', 1, 40, 5),
]


@case("G-R34", "G-R17", paragraphs=("SPEC:293",))
@pytest.mark.parametrize("name,prefix,occurrence,keep,verified", KILL_POINTS,
                         ids=[k[0] for k in KILL_POINTS])
def test_a_host_killed_mid_write_leaves_a_verifiable_prefix(tmp_path, name, prefix, occurrence,
                                                            keep, verified):
    """Exit criterion 3 and R34 (a crash may lose unsynced tail records, which must be reported
    as incomplete): the host is killed with SIGKILL while it writes the first frame (nothing of
    it written), a frame in the middle of the generation (the third, seq 3: 50 bytes of it
    written) or the footer (40 bytes written, after generation_start, three discovers and
    generation_end, seq 1 to 5). Each time the capture verifies as an incomplete prefix whose
    last verified seq is the record before the cut (0, 2, 5), never as a hash or schema fault,
    and no worker outlives the host."""
    steps = joined_session(discover("o1"), discover("o2"), discover("o3"))
    kill = {"prefix": prefix, "occurrence": occurrence, "keep": keep}
    run = HostProcess(tmp_path, [steps], kill=kill).start()
    if prefix == '{"last_generation"':
        run.wait_for("waiting")
        run.process.send_signal(signal.SIGINT)
    run.finish(timeout_s=60)
    assert run.returncode == -signal.SIGKILL
    report = run.check()
    assert (report["status"], report["code"], report["verified_seq"]) == (
        "INCOMPLETE", "E_CAPTURE_INCOMPLETE", verified)
    tail = run.session.capture_bytes().split(b"\n")[-1]
    assert tail == b"" if keep == 0 else len(tail) == keep


@case("A-DISK", "G-R34", "G-R15", paragraphs=("SPEC:293",))
@pytest.mark.parametrize("what", ["capture", "outputs"])
def test_a_file_size_limit_on_the_host_process_is_e_io(tmp_path, what):
    """A-DISK with RLIMIT_FSIZE on a real host process (OPS-24): the host ignores SIGXFSZ, so the
    limit arrives as a short write and then EFBIG, never as the death of the process. When the
    capture meets it (discovers only, which have no output records) the host records E_IO and
    writes nothing more: no footer, an incomplete capture. When the observations file meets it
    first (eligible reflections, each with a snapshot and an upsert) the capture is still
    writable: E_IO is captured, generation_end failure, FAILED. Never COMPLETE."""
    if what == "capture":
        steps = connect_and_join() + [burst(200), STALL]
    else:
        steps = connect_and_join() + [discover("o1")] + [reflect_full("o1")] * 6 + [STALL]
    run = HostProcess(tmp_path, [steps], rlimit=16384).start().finish(timeout_s=60)
    assert run.returncode == 0, run.stderr
    run.check()
    summary = run.result["summary"]
    assert summary["terminal_codes"] == ["E_IO"] and summary["status"] != "COMPLETE"
    if what == "capture":
        assert summary["status"] == "INCOMPLETE"
        assert len(run.session.capture_bytes()) <= 16384
    else:
        assert (summary["status"], summary["reason_code"]) == ("FAILED", "E_IO")
        shape = run.session.shape(elapsed=False)
        assert shape[-3:] == [("diagnostic", 1, "E_IO", None, None),
                              ("generation_end", 1, "failure"), FOOT("FAILED", "E_IO", 1)]
        assert len((run.session.out / "observations.jsonl").read_bytes()) <= 16384


@case("G-R14", paragraphs=("SPEC:277",))
def test_low_numbered_descriptors_never_reach_the_worker_wrongly(tmp_path):
    """NAT-09: a pipe end numbered 0 to 3 is moved to 10 or above before any DUP2, so no action
    has equal source and target. In a host whose stdin and fd 3 are closed, `_pipe` hands out
    descriptors above 3 and leaves 0 and 3 closed; a whole session there still gives the worker
    the status FIFO at fd 3, the null device on stdin and nothing else."""
    probe = HostProcess(tmp_path / "probe", [], close=[0, 3], probe_pipe=True).start()
    probe.finish(timeout_s=60)
    result = probe.result
    assert min(result["pipe"]) >= 10 and result["low_open"] == [1, 2]
    run = HostProcess(tmp_path / "session", [joined_session()], close=[0, 3]).start()
    run.wait_for("waiting")
    run.process.send_signal(signal.SIGINT)
    run.finish(timeout_s=30)
    assert run.returncode == 0, run.stderr
    run.check()
    (start,) = run.session.starts()
    assert start["fd3_fifo"] and start["stdin_null"] and start["inherited"] == []


# ============================================================== the writer on its own (OPS-24)

class _Memory:
    """A capture stream in memory that takes at most `chunk` bytes per write (os.write may)."""

    def __init__(self, chunk=7):
        self.data = bytearray()
        self.chunk = chunk

    def write(self, data):
        taken = min(len(data), self.chunk)
        self.data += data[:taken]
        return taken

    def fileno(self):
        return 99


def _writer_with(times, *, frames=100, interval=250 * MS, chunk=7):
    synced = []
    stream = _Memory(chunk)

    def fsync(fd):
        synced.append((len(stream.data), times[-1]))
    writer = _writer.CaptureWriter(stream, limits=limits_module.V1, fsync=fsync,
                                   fsync_frames=frames, fsync_interval_ns=interval)
    return writer, stream, synced


@case("G-R34", paragraphs=("SPEC:293",))
def test_the_writer_syncs_on_the_timer_the_count_and_every_boundary():
    """OPS-24 on the writer itself, with times given by hand: the header and generation_start are
    synced at once; a discover written at t = 10 ms makes the next sync due at 260 ms (`due`),
    `sync_if_due` does nothing at 259 ms and syncs at 260 ms; three discovers with a count of 3
    are synced at the third; generation_end and the footer at once. A write the stream takes in
    7-byte pieces arrives whole (os.write semantics)."""
    times = [0]
    writer, stream, synced = _writer_with(times, frames=3)
    writer.header(expected_header(), 0)
    assert synced == [(len(stream.data), 0)] and writer.due() is None
    writer.frame(1, 0, event_generation_start(), 0, end=False)
    times.append(10 * MS)
    writer.frame(1, 0, event_discover("o1"), 10 * MS, end=False)
    assert writer.due() == 260 * MS
    times.append(259 * MS)
    writer.sync_if_due(259 * MS)
    assert len(synced) == 2
    times.append(260 * MS)
    writer.sync_if_due(260 * MS)
    assert len(synced) == 3 and writer.due() is None
    for n in (2, 3, 4):
        writer.frame(1, 0, event_discover(f"o{n}"), 300 * MS, end=False)
    assert len(synced) == 4
    writer.frame(1, 0, event_generation_end("stop"), 300 * MS, end=True)
    writer.footer("COMPLETE", None, 300 * MS)
    assert len(synced) == 6 and synced[-1][0] == len(stream.data)
    lines = expected_lines(4)
    end_lines = CaptureBuilder(expected_header()).frame(1, 0, event_generation_start())
    for n in range(1, 5):
        end_lines.frame(1, 0, event_discover(f"o{n}"))
    end_lines.frame(1, 0, event_generation_end("stop")).footer("COMPLETE", None, 1)
    assert bytes(stream.data) == b"".join(line + b"\n" for line in end_lines.lines())
    assert bytes(stream.data).startswith(b"".join(lines))
    assert [size for size, _ in synced] == [
        sum(len(line) for line in lines[:k]) for k in (1, 2, 3, 6)] + [
        len(stream.data) - len(end_lines.lines()[-1]) - 1, len(stream.data)]
    assert (writer.last_seq, writer.frames, writer.last_generation) == (7, 6, 1)


@case("G-R34", paragraphs=("SPEC:293",))
def test_the_writer_serves_the_timer_whenever_it_writes():
    """OPS-24 (no line unsynced longer than the interval): the timer is also checked when a line
    is written, so a long run of frames from one read cannot keep the first of them unsynced
    past 250 ms. Times by hand: o1 at 10 ms makes a sync due at 260 ms; o2 written at 259 ms
    leaves both unsynced; o3 written at 260 ms is synced with them at once."""
    times = [0]
    writer, stream, synced = _writer_with(times)
    writer.header(expected_header(), 0)
    writer.frame(1, 0, event_generation_start(), 0, end=False)
    assert len(synced) == 2
    times.append(10 * MS)
    writer.frame(1, 0, event_discover("o1"), 10 * MS, end=False)
    times.append(259 * MS)
    writer.frame(1, 0, event_discover("o2"), 259 * MS, end=False)
    assert len(synced) == 2 and writer.due() == 260 * MS
    times.append(260 * MS)
    writer.frame(1, 0, event_discover("o3"), 260 * MS, end=False)
    assert synced[2:] == [(len(stream.data), 260 * MS)] and writer.due() is None
    assert bytes(stream.data) == b"".join(expected_lines(3))


@case("G-R34", paragraphs=("SPEC:293",))
def test_the_writer_refuses_an_end_frame_past_the_frame_limit():
    """SPEC:293 with OPS-21 through the seam: a frame of the end of a session may use the frames
    kept for it, but never pass frames_per_session; the writer refuses it (`CaptureFull`, which
    the host records as E_LIMIT with no footer) rather than letting the chain raise. With 7
    frames: 7 - 5 = 2 normal frames (generation_start, o1), a third normal one refused, then
    five end frames (frames 3 to 7: four diagnostics and generation_end), and a sixth (a
    generation-0 diagnostic) refused with nothing written; the footer is not a frame."""
    stream = _Memory(chunk=1 << 20)
    writer = _writer.CaptureWriter(stream, limits=with_limits(frames_per_session=7),
                                   fsync=lambda fd: None, fsync_frames=100,
                                   fsync_interval_ns=250 * MS)
    writer.header(expected_header(), 0)
    writer.frame(1, 0, event_generation_start(), 0, end=False)
    writer.frame(1, 0, event_discover("o1"), 0, end=False)
    with pytest.raises(_writer.CaptureFull):
        writer.frame(1, 0, event_discover("o2"), 0, end=False)
    for _ in range(4):
        writer.frame(1, 0, event_diagnostic("E_LIMIT", "the end"), 0, end=True)
    writer.frame(1, 0, event_generation_end("limit"), 0, end=True)
    size = len(stream.data)
    with pytest.raises(_writer.CaptureFull):
        writer.frame(0, 0, event_diagnostic("E_IO", "the end"), 0, end=True)
    assert len(stream.data) == size and (writer.frames, writer.last_seq) == (7, 7)
    writer.footer("FAILED", "E_LIMIT", 0)
    assert writer.written_footer == {"status": "FAILED", "reason_code": "E_LIMIT"}


def test_the_writer_refuses_a_record_the_chain_refuses_and_stays_usable():
    """The writer writes only what the chain accepts (R2's rules): a frame the chain refuses
    raises the chain's HlaError and nothing reaches the file; the next frame is written."""
    times = [0]
    writer, stream, _ = _writer_with(times)
    writer.header(expected_header(), 0)
    size = len(stream.data)
    with pytest.raises(HlaError) as caught:
        writer.frame(1, 0, event_discover("o1"), 0, end=False)
    assert (caught.value.code, caught.value.path) == ("E_CAPTURE_SCHEMA", "line:2#/event/type")
    assert len(stream.data) == size and writer.last_seq == 0
    writer.frame(1, 0, event_generation_start(), 0, end=False)
    assert writer.last_seq == 1


# ====================================================================== the remaining paths

def test_the_linux_rss_reading_is_vmrss_in_kib():
    """OPS-23 on Linux reads VmRSS from /proc/<pid>/status, which the kernel writes in kB
    (KiB): 2048 kB is 2097152 bytes; a status without the line, or with a line that is not a
    number of kB, gives no reading."""
    status = b"Name:\tsc-hla-federate\nVmPeak:\t  9000 kB\nVmRSS:\t    2048 kB\nThreads:\t3\n"
    assert host.rss_from_proc_status(status) == 2048 * 1024
    assert host.rss_from_proc_status(b"Name:\tx\nThreads:\t3\n") is None
    assert host.rss_from_proc_status(b"VmRSS:\t12 MB\n") is None
    assert host.rss_from_proc_status(b"VmRSS:\t-1 kB\n") is None


def test_run_session_refuses_caller_bugs():
    """Arguments of the wrong kind are caller bugs (TypeError, ValueError), not HlaError."""
    config = example_config()
    with pytest.raises(TypeError):
        host.run_session(config, "out", environ={}, seams=object())
    for duration in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            host.run_session(config, "out", environ={}, duration_ns=duration)
    with pytest.raises(TypeError):
        host.run_session(config, "out", environ={"A": 1})


def test_the_session_restores_the_signal_handlers(tmp_path):
    """The host's SIGINT and SIGTERM handlers and its SIGXFSZ disposition exist only while the
    session runs; afterwards the process has what it had before."""
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGXFSZ)}
    session = run_case(tmp_path, [joined_session()], stop_on_waiting=1)
    assert session.summary["status"] == "COMPLETE"
    assert {s: signal.getsignal(s) for s in before} == before


@pytest.mark.parametrize("defect", [reducer_module.ReducerDefect,
                                    projector_module.ProjectionDefect, RuntimeError],
                         ids=["ReducerDefect", "ProjectionDefect", "RuntimeError"])
def test_a_defect_propagates_after_the_worker_is_killed(tmp_path, monkeypatch, defect):
    """CR-new-R5-15 with CR-R3-07 and CR-R4-11 (R5-r1-F4): an exception that is not `HlaError`
    is a defect. Injected into the third reduction of a live session (`reduce_admitted`, the
    host's entry since CR-L07; the discover of o2,
    seq 3, already written), it propagates out of `run_session` as itself; the worker is killed
    and gone, no descriptor is left open, the signal handlers and the wake-up descriptor are
    the caller's again, and the capture holds the three frames written and no footer:
    `verify_capture` says INCOMPLETE at line 5 (verified_seq 3)."""
    original = host.reducer.reduce_admitted
    calls = []

    def failing(state, frame):
        calls.append(frame["seq"])
        if len(calls) == 3:
            raise defect("an injected defect")
        return original(state, frame)

    session = Session(tmp_path, [joined_session(discover("o1"), discover("o2"))])
    handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGXFSZ)}
    wakeup = signal.set_wakeup_fd(-1)
    signal.set_wakeup_fd(wakeup)
    descriptors = sorted(os.listdir("/dev/fd"))
    monkeypatch.setattr(host.reducer, "reduce_admitted", failing)
    with pytest.raises(defect) as caught:
        host.run_session(session.config, session.out, environ=session.environ,
                         seams=session.seams)
    monkeypatch.undo()
    assert type(caught.value) is defect and calls == [1, 2, 3]
    assert sorted(os.listdir("/dev/fd")) == descriptors
    assert {s: signal.getsignal(s) for s in handlers} == handlers
    assert signal.set_wakeup_fd(wakeup) == wakeup
    (start,) = session.starts()
    assert process_gone(start["pid"])
    assert session.shape() == [START(1, 0), DISC(1, 0, "o1"), DISC(1, 0, "o2")]
    report = check_session(session.out, None, [start["pid"]], replay_root=session.root)
    assert (report["status"], report["code"], report["path"], report["verified_seq"]) == (
        "INCOMPLETE", "E_CAPTURE_INCOMPLETE", "line:5", 3)


@case("A-DISK", "G-R34", paragraphs=("SPEC:293",))
def test_the_header_and_the_files_themselves_can_fail(tmp_path):
    """E_IO before any worker: a header that cannot be written whole is E_IO (path output_dir)
    and no worker starts; a capture that cannot be created is E_IO too, and the directory the
    call made is removed again (nothing was captured in it)."""
    session = Session(tmp_path / "header", [joined_session()], open_capture=failing_opener(10))
    with pytest.raises(HlaError) as caught:
        session.run()
    assert (caught.value.code, caught.value.path) == ("E_IO", "output_dir")
    assert len(session.capture_bytes()) == 10 and session.starts() == []

    def refusing(directory_fd, name):
        raise OSError(errno.EACCES, "Permission denied")

    session = Session(tmp_path / "create", [joined_session()], open_capture=refusing)
    with pytest.raises(HlaError) as caught:
        session.run()
    assert (caught.value.code, caught.value.path) == ("E_IO", "output_dir")
    assert not os.path.lexists(session.out) and session.starts() == []


@case("A-DISK", "G-R34", paragraphs=("SPEC:293",))
def test_a_timed_fsync_that_fails_ends_the_session_with_e_io(tmp_path):
    """OPS-24: the timer's fsync failing is the same I/O failure: the worker, which is pausing,
    is killed, nothing more is written, no footer."""
    calls = []

    def fsync(fd):
        calls.append(fd)
        if len(calls) == 4:
            raise OSError(errno.EIO, "Input/output error")
        os.fsync(fd)

    steps = joined_session(discover("o1"), {"do": "sleep", "ms": 2000}, discover("o2"))
    session = run_case(tmp_path, [steps], frozen=False, fsync_interval_ns=100 * MS, fsync=fsync)
    assert session.shape(elapsed=False) == bare([START(1, 0), DISC(1, 0)])
    assert (session.summary["status"], session.summary["terminal_codes"]) == (
        "INCOMPLETE", ["E_IO"])
    assert "waiting" not in [e["event"] for e in session.log_entries()]


@case("G-R34", paragraphs=("SPEC:293",))
def test_outputs_that_fail_while_the_session_ends_make_it_failed(tmp_path, monkeypatch):
    """R34 (the outputs are derived) and E_IO's row (stop the session FAILED): the outputs fail
    when the orderly stop's generation_end invalidates the eligible o1. The capture is still
    writable, so after generation_end the host records E_IO (generation 0: no generation is
    open any more) and the footer is FAILED E_IO, not COMPLETE."""
    original = _writer.OutputWriter.write

    def failing(self, records):
        if any(r["kind"] == "invalidated" for r in records):
            self.broken = True
            raise _writer.OutputBroken()
        return original(self, records)

    monkeypatch.setattr(_writer.OutputWriter, "write", failing)
    session = Session(tmp_path, [joined_session(discover("o1", MS), reflect_full("o1", 2 * MS))])
    session.run(stop_on_waiting=1)
    monkeypatch.undo()
    finished(session)
    assert session.shape() == [START(1, 0), DISC(1, MS), REFL(1, 2 * MS),
                               END(1, 2 * MS, "stop"), DIAG(0, 2 * MS, "E_IO"),
                               FOOT("FAILED", "E_IO", 1)]
    assert session.summary["terminal_codes"] == ["E_IO"]


@case("G-R14", paragraphs=("SPEC:277",))
def test_a_pipe_held_open_after_the_worker_exited_does_not_hold_the_host(tmp_path):
    """SPEC:277 (drain for at most the window, then close): a child of the worker keeps both
    pipes open after the worker has exited. Once the worker is reaped the host reads the pipes
    for at most the drain window (200 ms here, real clock) and then closes them; the session ends
    while that child still lives."""
    steps = connect_and_join() + [discover("o1"), {"do": "hold_pipes", "ms": 20000},
                                  {"do": "exit", "code": 0}]
    session = Session(tmp_path, [steps], frozen=False, drain_ns=200 * MS, retry_delays_ns=())
    session.run()
    holder = next(e["holder"] for e in session.log_entries() if e["event"] == "holder")
    try:
        assert not process_gone(holder, within_s=0)
    finally:
        os.kill(holder, signal.SIGKILL)
    assert process_gone(holder)
    finished(session)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0), DIAG(1, 0, "E_RTI_CONNECT"), END(1, 0, "connection_lost"),
        FOOT("FAILED", "E_RTI_CONNECT", 1)])


# ================================================== hostile values (CR-R2-24), seeded and fixed

import random  # noqa: E402  (the fuzz section's own)

_HOSTILE_VALUES = [10 ** 30, -(10 ** 30), 2 ** 53, -1, 0, 1.5, float("nan"), float("inf"), None,
                   True, "", "\ud800", "x" * 70000, b"bytes", (1,), {1, 2}, [], {}, [[[]]],
                   "\N{RIGHT-TO-LEFT OVERRIDE}", "\x00", "a\x00b", "\N{LINE SEPARATOR}"]
_ALLOWED = (HlaError, TypeError, ValueError)


def _hostile(rng):
    return rng.choice(_HOSTILE_VALUES)


@pytest.mark.parametrize("seed", range(6))
def test_hostile_python_values_at_the_entry_points(tmp_path, seed):
    """CR-R2-24 for this round's refusal paths: `run_session` (configuration, output path,
    environment, duration, seams), `locate_worker`, `check_worker` and `preflight` given
    hostile Python values only ever raise HlaError with a catalogue E_ code, or TypeError and
    ValueError for a caller bug; nothing else escapes, and nothing starts a session (the
    environment has no FOM directory, so a value that happens to be valid stops at the
    pre-flight)."""
    rng = random.Random(seed)
    worker = str(worker_executable(tmp_path))
    base_env = {"SYNAPSE_HLA_WORKER": worker, "PATH": "/usr/bin:/bin"}
    seen = set()
    for number in range(60):
        config = example_config()
        for _ in range(rng.choice((0, 1, 2))):
            key = rng.choice(list(config))
            config[key] = _hostile(rng)
        output = rng.choice([str(tmp_path / f"out-{number}"), _hostile(rng),
                             str(tmp_path) + "/\udcff\udcfe", str(tmp_path / "a\x00b")])
        environ = dict(base_env)
        if rng.random() < 0.5:
            environ[rng.choice(["X", "SYNAPSE_HLA_WORKER", "\ud800", ""])] = _hostile(rng)
        duration = rng.choice([None, 1, _hostile(rng)])
        try:
            host.run_session(config, output, environ=environ, duration_ns=duration,
                             seams=dataclasses.replace(host.V1, deadline_ns=S))
            raise AssertionError("a session ran")
        except HlaError as refusal:
            assert refusal.code.startswith("E_")
            seen.add(refusal.code)
        except (TypeError, ValueError):
            seen.add("caller-bug")
        path = _hostile(rng)
        for call in (lambda: host.locate_worker({"SYNAPSE_HLA_WORKER": path}),
                     lambda: host.check_worker(path, base_env),
                     lambda: host.preflight({"SYNAPSE_HLA_FOM_DIR": path})):
            try:
                call()
            except _ALLOWED:
                pass
    assert seen  # the loop ran its refusals
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("out-") and
                (p / "capture.jsonl").exists()]


def _hostile_line(rng) -> bytes:
    """One line a broken or hostile worker might write: random bytes, a valid frame or status
    record with one member replaced by a hostile value or spelled out of the strict reader's
    reach (a float, a duplicate key, a lone surrogate escape, a byte order mark, a CR, invalid
    UTF-8, nesting past 32), or a line past the length limit."""
    choice = rng.randrange(9)
    frame = {"event": event_discover("o1"), "monotonic_ns": "7000000000000"}
    status = {"type": "stage", "stage": "request_update"}
    record = rng.choice([frame, status])
    if choice == 0:
        return bytes(rng.randrange(256) for _ in range(rng.randrange(1, 80))).replace(b"\n", b" ")
    if choice == 1:
        value = rng.choice([10 ** 30, 1.5, None, [], {"a": 1}, True, "x" * 2000])
        member = rng.choice(list(record))
        return json.dumps(dict(record, **{member: value})).encode()
    if choice == 2:
        return json.dumps(record).encode()[:-1] + b',"monotonic_ns":"1"}'
    if choice == 3:
        return json.dumps(record).encode().replace(b'"o1"', b'"\\ud800"').replace(
            b'"request_update"', b'"\\udfff"')
    if choice == 4:
        return b"\xef\xbb\xbf" + json.dumps(record).encode()
    if choice == 5:
        return json.dumps(record).encode().replace(b",", b",\r", 1)
    if choice == 6:
        return json.dumps(record).encode().replace(b'"', b'"\xff', 1)
    if choice == 7:
        return b"[" * 40 + b"]" * 40
    return b" " * 65537


@case("G-R14", paragraphs=("SPEC:277",))
@pytest.mark.parametrize("seed", range(24))
def test_hostile_worker_bytes_never_escape_the_host(tmp_path, seed):
    """CR-R2-24 on the worker's two channels: seeded hostile lines on stdout or fd 3 after the
    join never make an exception escape the host. The session ends with a summary, the capture
    verifies and replays like every other (finished), and a line the host refused is a terminal
    E_CAPTURE_SCHEMA or E_LIMIT (OPS-19), never retried; a line it could accept is captured
    and the orderly stop ends COMPLETE."""
    rng = random.Random(seed)
    channel = rng.choice(["stdout_raw", "status_raw"])
    lines = [_hostile_line(rng) for _ in range(rng.randrange(1, 3))]
    steps = connect_and_join() + [{"do": channel, "hex": (line + b"\n").hex()}
                                  for line in lines] + [{"do": "sleep", "ms": 50}]
    session = run_case(tmp_path, [steps + orderly_stop(), joined_session()],
                       stop_on_waiting=1)
    summary = session.summary
    assert summary["workers"] == 1
    assert (summary["status"], summary["reason_code"]) in {
        ("COMPLETE", None), ("FAILED", "E_CAPTURE_SCHEMA"), ("FAILED", "E_LIMIT")}


# ============================================================ the RSS parent's view (round R6)

@case("G-R14", paragraphs=("SPEC:62",))
def test_the_caller_is_told_every_worker_as_it_starts_and_as_it_is_reaped(tmp_path):
    """OPS-23 with CR-new-R5-04 (round R6): the worker has a process group of its own, so the
    command line's RSS parent, which kills the host's group, must end the workers itself, and
    `run_session(on_worker=...)` tells it each worker: started (True), then reaped (False), in
    that order, one worker at a time; the pids are the ones the fake workers logged. When a
    worker is announced the session's own SIGINT handler is already in place, so a stop the
    parent forwards from then on reaches the session. A worker killed by the host (the second
    one, stopped by SIGINT here) is reported reaped like the first."""
    told = []

    def on_worker(pid, running):
        told.append((pid, running, signal.getsignal(signal.SIGINT) is not previous))

    session = Session(tmp_path, [lost(MS), joined_session()])
    previous = signal.getsignal(signal.SIGINT)
    session.run(stop_on_waiting=2, on_worker=on_worker)
    finished(session)
    assert session.summary["status"] == "COMPLETE" and session.summary["workers"] == 2
    pids = [entry["pid"] for entry in session.starts()]
    assert told == [(pids[0], True, True), (pids[0], False, True),
                    (pids[1], True, True), (pids[1], False, True)]


@pytest.mark.parametrize("value", ["not callable", 5])
def test_on_worker_must_be_callable(tmp_path, value):
    session = Session(tmp_path, [joined_session()])
    with pytest.raises(TypeError):
        host.run_session(session.config, session.out, environ=session.environ,
                         seams=session.seams, on_worker=value)
    assert not session.out.exists()


# ===================================================================== a parent that has gone (CR-R6-F2)

class VanishingParent:
    """The seam's parent probe (`HostSeams.getppid`): this process's real parent until `gone()`
    holds, then `new`: 1, the parent macOS and a plain Linux give an orphan, or another process
    (R6F-r1-F2: a subreaper, such as `systemd --user` on the reference platform). Counts its
    calls."""

    def __init__(self, new: int = 1) -> None:
        self.real = os.getppid()
        self.new = new
        self.gone = lambda: False
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        return self.new if self.gone() else self.real


#: R6F-r1-F2: the parent an orphaned host is given: init, or a subreaper that is neither init nor
#: the old parent. A check of "the parent is 1" (or "at most 1") passes the first and not the
#: second.
NEW_PARENTS = pytest.mark.parametrize("new_parent", [1, 4242], ids=["init", "subreaper"])


def worker_waits(session):
    return lambda: any(e["event"] == "waiting" for e in session.log_entries())


@NEW_PARENTS
def test_a_parent_that_has_gone_stops_the_session_in_order(tmp_path, new_parent):
    """CR-R6-F2: the host compares its parent with the one it started with at every poll tick;
    once the parent is another process (the command that started it was killed), the session
    stops in order as a SIGTERM would stop it: the worker gets SIGTERM, resigns, disconnects and
    exits 0, generation_end stop, COMPLETE. No signal is sent and no duration given here, so
    nothing else could end this session."""
    assert new_parent != os.getppid()
    parent = VanishingParent(new_parent)
    steps = connect_and_join() + [discover("o1", MS), {"do": "wait_term"}, stage("resign"),
                                  stage("running"), stage("disconnect"), stage("running")]
    session = Session(tmp_path, [steps], getppid=parent)
    parent.gone = worker_waits(session)
    session.run()
    finished(session)
    assert session.shape() == [START(1, 0), DISC(1, MS), END(1, MS, "stop"),
                               FOOT("COMPLETE", None, 1)]
    assert (session.summary["status"], session.summary["terminal_codes"],
            session.summary["workers"]) == ("COMPLETE", [], 1)
    assert [e["event"] for e in session.log_entries()] == ["version", "start", "waiting",
                                                           "sigterm", "exit"]
    assert parent.calls >= 2


@NEW_PARENTS
def test_a_parent_that_has_gone_with_a_worker_that_will_not_stop_is_e_rti_timeout(tmp_path,
                                                                                   new_parent):
    """CR-R6-F2 with OPS-25: the stop a vanished parent asks for is the orderly stop, with its
    deadline: a worker that ignores SIGTERM is killed after it (1 s here, real clock), and the
    session ends E_RTI_TIMEOUT, generation_end timeout, FAILED. The pre-flight is `PROBE`'s."""
    parent = VanishingParent(new_parent)
    steps = connect_and_join() + [discover("o1"), {"do": "wait_term"}, STALL]
    session = Session(tmp_path, [steps], getppid=parent, frozen=False, deadline_ns=S, **PROBE)
    parent.gone = worker_waits(session)
    session.run()
    finished(session)
    assert session.shape(elapsed=False) == bare([
        START(1, 0), DISC(1, 0), DIAG(1, 0, "E_RTI_TIMEOUT"), END(1, 0, "timeout"),
        FOOT("FAILED", "E_RTI_TIMEOUT", 1)])


@NEW_PARENTS
def test_a_parent_gone_before_the_first_worker_ends_the_session_before_it_starts(tmp_path,
                                                                                 new_parent):
    """CR-R6-F2 when the parent the caller names (`parent_pid`, as the command line passes its
    own pid from before the fork) is already gone when the session begins: the pre-flight and the
    header happen, then the first poll sees the other parent and stops before any worker starts,
    as a stop before any join does (OPS-15): an E_RTI_CONNECT diagnostic of the host and a FAILED
    footer; the worker was asked for its version and never started."""
    parent = VanishingParent(new_parent)
    parent.gone = lambda: True
    session = Session(tmp_path, [joined_session()], getppid=parent)
    summary = host.run_session(session.config, session.out, environ=session.environ,
                               seams=session.seams, parent_pid=parent.real)
    assert session.shape() == [DIAG(0, 0, "E_RTI_CONNECT"), FOOT("FAILED", "E_RTI_CONNECT", 0)]
    assert (summary["status"], summary["terminal_codes"], summary["workers"]) == (
        "FAILED", ["E_RTI_CONNECT"], 0)
    assert [e["event"] for e in session.log_entries()] == ["version"]


@pytest.mark.parametrize("value,error", [("1", TypeError), (1.0, TypeError), (True, TypeError),
                                        (0, ValueError), (-5, ValueError)])
def test_a_parent_pid_that_is_not_a_process_id_is_a_caller_bug(tmp_path, value, error):
    """`parent_pid` is an int of 1 or more, or None; anything else is refused before anything is
    checked or created."""
    session = Session(tmp_path, [joined_session()])
    with pytest.raises(error):
        host.run_session(session.config, session.out, environ=session.environ,
                         seams=session.seams, parent_pid=value)
    assert not session.out.exists() and session.log_entries() == []
