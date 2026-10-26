"""The observer against a real rtinode, the reference tools and the reference checks (round R8).

WHAT RUNS
---------
`rti` group (check.sh step 8 builds every executable named here and sets their variables): the
real worker `sc-hla-federate` under the real host against the pinned OpenRTI's `rtinode`, with the
federation another process created - the synthetic publisher (through `demo_driver.py`, which runs
the demo's own orchestration in a fresh interpreter) or the test-only `sc-hla-test-federate`:
A-MISSING-FOM (a federation from a reduced module set written at test time from the pinned bytes,
OPS-28 b), A-NAME-CONFLICT (another federate already holds the observer's name), A-NO-CREATE's
real evidence (a missing federation is refused and stays missing), A-CLASS in an existing-mode
session, the RST and FIN proxies of NAT-03 and NAV-02, `observe` stopped in order on a real
federation (SIGINT, SIGTERM, the duration), the reference encoder of R47 against the packaged
vectors and the bundle's results (A-ENCODING) and the bundle's FOM check against an rtinode of
the demo's kind.

`perf` group: the DEV run of the publisher's `perf:1000:1:20` load under the host (an early
warning for R42; the evidence of R42 is the reference platform's, CR-L04).

`reference` group: the PROJ check of COD-09 (as corrected) and CDV-02 through `cs2cs`, forward
only (EPSG:4979 to EPSG:4978), against the product's inverse.

Every process a test starts is stopped by its PID and asserted gone; sockets are on 127.0.0.1.
Everything here is development evidence (DEV-macOS-arm64 on the development Mac, CR-L04).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import re
import select
import signal
import subprocess
import sys
import time

import pytest

from hla_support import (
    PACKAGE_ROOT, TESTS_DIR, assert_strict_equal, blocked, case, example_json, fixed_tool,
    fixture_capture_records, fixture_json, fom_modules, native_executable, packaged_pins,
    place_text, positive_hex, process_gone, strict_json, tool_place,
)
from synapse_hla import decode_attribute, geodesy, verify_capture
from test_hla_cli import environment, finish, start
from test_hla_native_sources import code_of
from test_hla_native import (
    CLASSES, NativeSession, Rtinode, exit_class, worker,
)

PE = "HLAobjectRoot.BaseEntity.PhysicalEntity"
GV = "HLAobjectRoot.BaseEntity.PhysicalEntity.Platform.GroundVehicle"
SECOND = 1_000_000_000


def lines(path: pathlib.Path) -> list[dict]:
    return [strict_json(line) for line in path.read_bytes().split(b"\n")[:-1]]


def frames_of(path: pathlib.Path) -> list[dict]:
    return [r for r in lines(path)[1:] if r["type"] == "frame"]


def shape(path: pathlib.Path) -> list[tuple]:
    """A capture as (seq, generation, event type, tag or reason or code, token)."""
    out = []
    for record in lines(path)[1:]:
        if record["type"] == "footer":
            out.append(("footer", record["status"], record["reason_code"],
                        record["last_generation"]))
            continue
        event = record["event"]
        detail = (event.get("tag_hex") if "tag_hex" in event else event.get("reason")
                  if "reason" in event else event.get("diagnostic", {}).get("code"))
        out.append((record["generation"], event["type"], detail, event.get("object_token")))
    return out


# ============================================================================ the test federate

def close_streams(proc: subprocess.Popen) -> None:
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is not None and not stream.closed:
            stream.close()


class EventLines:
    """JSON lines from a child's stdout, read from the descriptor itself (never through a
    buffered reader, whose buffer a select() cannot see), each stamped with the monotonic clock
    of its arrival."""

    def __init__(self, stream) -> None:
        self.fd = stream.fileno()
        self.buffer = b""
        self.events: list[dict] = []
        self.times: list[float] = []
        self.ended = False

    def until(self, name: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            for event in self.events:
                if event.get("event") == name:
                    return event
            assert not self.ended, f"the child ended before {name}: {self.events}"
            ready, _, _ = select.select([self.fd], [], [], max(0.0, deadline - time.monotonic()))
            assert ready, f"no {name} event in time: {self.events}"
            chunk = os.read(self.fd, 65536)
            self.ended = not chunk
            self.buffer += chunk
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                self.events.append(json.loads(line))
                self.times.append(time.monotonic())

    def rest(self) -> None:
        while not self.ended:
            chunk = os.read(self.fd, 65536)
            self.ended = not chunk
            self.buffer += chunk
        self.events += [json.loads(line) for line in self.buffer.split(b"\n") if line]
        self.buffer = b""


class TestFederate:
    """`sc-hla-test-federate`: creates a federation from module files, joins it under a name,
    holds until its stdin ends, then resigns, destroys what it created and disconnects."""

    __test__ = False

    def __init__(self, endpoint: str, federation: str, federate: str,
                 modules: list[pathlib.Path]) -> None:
        executable = pathlib.Path(native_executable("SYNAPSE_HLA_WORKER")).parent / \
            "sc-hla-test-federate"
        if not executable.is_file():
            pytest.fail("sc-hla-test-federate is not beside the worker in the native build")
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENRTI_")}
        self.proc = subprocess.Popen(
            [str(executable), f"--endpoint={endpoint}", f"--federation-name={federation}",
             f"--federate-name={federate}"] + [f"--module={m}" for m in modules],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            start_new_session=True)
        self.lines = EventLines(self.proc.stdout)
        self.lines.until("ready", 20)
        assert not any(e.get("event") == "failure" for e in self.lines.events), self.lines.events

    def finish(self) -> list[str]:
        """Lets it go: it resigns, destroys its federation and disconnects; returns its events."""
        self.proc.stdin.close()
        self.lines.rest()
        code, err = self.proc.wait(30), self.proc.stderr.read()
        close_streams(self.proc)
        assert code == 0 and err == b"" and process_gone(self.proc.pid)
        return [e["event"] for e in self.lines.events]

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)
        close_streams(self.proc)


def existing(endpoint: str, federation: str) -> dict:
    config = example_json("config-existing.json")
    config.update(endpoint=endpoint, federation_name=federation)
    return config


def reduced_modules(directory: pathlib.Path) -> list[pathlib.Path]:
    """OPS-28 (b): the five pinned modules, written into `directory` at test time, with the
    Spatial attribute's definition taken out of RPR-Base (its one <attribute> element whose
    name is Spatial); nothing of it is ever committed."""
    out = []
    for module in fom_modules():
        data = module.read_bytes()
        if module.name == "RPR-Base_v2.0.xml":
            text = data.decode("utf-8")
            reduced, count = re.subn(r"<attribute[^>]*>\s*<name>Spatial</name>.*?</attribute>\s*",
                                     "", text, count=1, flags=re.S)
            assert count == 1 and "<name>Spatial</name>" not in reduced
            data = reduced.encode("utf-8")
        target = directory / module.name
        target.write_bytes(data)
        out.append(target)
    return out


@pytest.mark.rti
@case("A-MISSING-FOM", "G-R10", paragraphs=("SPEC:50",))
def test_a_federation_without_spatial_is_e_fom_profile_without_fallback_or_retry(tmp_path):
    """A-MISSING-FOM against a real rtinode: another process created the federation from the
    five modules with Spatial taken out of RPR-Base; the real worker joins it (generation 1
    starts, SPEC:275), cannot resolve Spatial at PhysicalEntity, reports E_FOM_PROFILE and
    ends: generation_end failure, footer FAILED E_FOM_PROFILE, one worker (never retried,
    SPEC:62), nothing subscribed, no object seen, exit class 5. No fallback: no other class or
    attribute was tried, so the federation's other members saw nothing (the creator then
    destroys its federation, which needs every federate gone)."""
    node = Rtinode(tmp_path)
    holder = None
    try:
        modules = reduced_modules(tmp_path)
        holder = TestFederate(node.endpoint, "SC_DEMO_00000000000000aa", "SC_TEST_HOLDER",
                              modules)
        session = NativeSession(tmp_path / "observer", worker(),
                                config=existing(node.endpoint, "SC_DEMO_00000000000000aa"))
        session.run()
        summary = session.summary
        assert (summary["status"], summary["reason_code"], summary["workers"]) == (
            "FAILED", "E_FOM_PROFILE", 1)
        assert summary["terminal_codes"] == ["E_FOM_PROFILE"] and exit_class(summary) == 5
        assert shape(session.out / "capture.jsonl") == [
            (1, "generation_start", None, None), (1, "diagnostic", "E_FOM_PROFILE", None),
            (1, "generation_end", "failure", None), ("footer", "FAILED", "E_FOM_PROFILE", 1)]
        session.check()
        assert holder.finish() == ["created", "ready", "resigned", "destroyed", "disconnected"]
    finally:
        if holder is not None:
            holder.kill()
        node.stop()


@pytest.mark.rti
@case("A-NAME-CONFLICT", "G-R14", "G-R10", paragraphs=("SPEC:62", "SPEC:50"))
def test_a_federate_name_already_joined_is_e_federate_name_never_renamed_never_retried(
        tmp_path):
    """A-NAME-CONFLICT against a real rtinode: another federate already holds the observer's
    configured name SC_OBSERVER in the federation; the real worker's join is refused
    (FederateNameAlreadyInUse) and the session ends at once: one generation-0 diagnostic
    E_FEDERATE_NAME, no generation, footer FAILED E_FEDERATE_NAME with last_generation 0, one
    worker (no retry, SPEC:62), exit class 5. No renaming: no generation ever started, so no
    join under another name succeeded. The holder keeps its name throughout and then resigns
    and destroys its federation (the observer left nothing joined). The native half with the
    decorator is R7's name-in-use row."""
    node = Rtinode(tmp_path)
    holder = None
    try:
        holder = TestFederate(node.endpoint, "SC_DEMO_00000000000000bb", "SC_OBSERVER",
                              fom_modules())
        session = NativeSession(tmp_path / "observer", worker(),
                                config=existing(node.endpoint, "SC_DEMO_00000000000000bb"))
        session.run()
        summary = session.summary
        assert (summary["status"], summary["reason_code"], summary["workers"],
                summary["last_generation"]) == ("FAILED", "E_FEDERATE_NAME", 1, 0)
        assert CLASSES["E_FEDERATE_NAME"] == 5 and exit_class(summary) == 5
        assert shape(session.out / "capture.jsonl") == [
            (0, "diagnostic", "E_FEDERATE_NAME", None), ("footer", "FAILED", "E_FEDERATE_NAME", 0)]
        session.check()
        assert holder.finish() == ["created", "ready", "resigned", "destroyed", "disconnected"]
    finally:
        if holder is not None:
            holder.kill()
        node.stop()


@pytest.mark.rti
@case("A-NO-CREATE", "G-R07", paragraphs=("SPEC:38",))
def test_a_federation_that_does_not_exist_is_refused_and_still_does_not_exist_afterwards(
        tmp_path):
    """A-NO-CREATE's real evidence (NAT-07): the observer is configured with a federation nobody
    created; the real rtinode refuses each join (FederationExecutionDoesNotExist, E_RTI_CONNECT,
    retried 1, 2, 4 s: four workers), the session ends FAILED at generation 0, and afterwards a
    federation of exactly that name can still be created by another process: the observer
    created nothing, injected no FOM and destroyed nothing (SPEC:38, R10)."""
    node = Rtinode(tmp_path)
    holder = None
    try:
        session = NativeSession(tmp_path / "observer", worker(),
                                config=existing(node.endpoint, "SC_DEMO_00000000000000cc"))
        session.run()
        summary = session.summary
        assert (summary["status"], summary["reason_code"], summary["workers"],
                summary["last_generation"]) == ("FAILED", "E_RTI_CONNECT", 4, 0)
        assert session.sleeps == [1 * SECOND, 2 * SECOND, 4 * SECOND]
        assert shape(session.out / "capture.jsonl") == \
            [(0, "diagnostic", "E_RTI_CONNECT", None)] * 4 + [
                ("footer", "FAILED", "E_RTI_CONNECT", 0)]
        session.check()
        holder = TestFederate(node.endpoint, "SC_DEMO_00000000000000cc", "SC_TEST_HOLDER",
                              fom_modules())
        assert holder.finish() == ["created", "ready", "resigned", "destroyed", "disconnected"]
    finally:
        if holder is not None:
            holder.kill()
        node.stop()


# ============================================================================ the driver

def run_driver(tmp_path: pathlib.Path, kind: str, **extra) -> dict:
    """`demo_driver.py` in a fresh interpreter (it forks the host as the command line does);
    the result it wrote. The executables come from this process's environment."""
    result = tmp_path / f"{kind}.json"
    arguments = {"kind": kind, "out": str(tmp_path / kind), "result": str(result), **extra}
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for variable in ("SYNAPSE_HLA_WORKER", "SYNAPSE_HLA_RTINODE", "SYNAPSE_HLA_PUBLISHER"):
        env[variable] = str(native_executable(variable))
    env["SYNAPSE_HLA_FOM_DIR"] = str(fom_modules()[0].parent)
    proc = subprocess.run([sys.executable, str(TESTS_DIR / "demo_driver.py"),
                           json.dumps(arguments)], env=env, capture_output=True, timeout=900)
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")[-3000:]
    out = json.loads(result.read_text(encoding="utf-8"))
    for process in out["processes"]:
        assert process["reaped"] and process_gone(process["pid"]), process
    assert out["rtinode"]["port_released"] is True and process_gone(out["rtinode"]["pid"])
    if "proxy_pid" in out:
        assert process_gone(out["proxy_pid"])
    return out


def steps(result: dict) -> dict:
    return {int(k): v for k, v in result["acknowledged"].items()}


@pytest.mark.rti
@case("A-CLASS", "G-R10", "G-R12", "G-R13", paragraphs=("SPEC:50", "SPEC:56"))
def test_an_existing_mode_session_reports_physical_entity_for_a_ground_vehicle(tmp_path):
    """A-CLASS in mode existing (the carried G-R10 clause): the synthetic publisher created its
    federation, published at both classes (NAT-01) and registered its object at GroundVehicle;
    the observer joined without modules, resolved and subscribed the four attributes at
    PhysicalEntity and was told of the object at PhysicalEntity (NAT-04), which is what every
    capture line and output says. Across processes (G-R12, G-R13): the discovery, the four
    reflections and the removal came from the publisher through rtinode in R38's order, each
    receive ordered; the observer's request was answered (a `refresh` event of the publisher);
    W_FOM_UNVERIFIED is emitted once in this generation (R11, existing mode)."""
    result = run_driver(tmp_path, "main")
    assert result["failure"] is None and result["registered_class"] == GV
    capture = tmp_path / "main" / "capture.jsonl"
    frames = frames_of(capture)
    by_seq = {f["seq"]: f["event"] for f in frames}
    acknowledged = steps(result)
    assert sorted(acknowledged) == list(range(7)) and acknowledged[6] is None
    seqs = [acknowledged[n] for n in range(6)]
    assert seqs == sorted(set(seqs))
    assert [by_seq[s]["type"] for s in seqs] == ["discover"] + ["reflect"] * 4 + ["remove"]
    assert [bytes.fromhex(by_seq[s]["tag_hex"]) for s in seqs[1:]] == [
        b"step-1", b"step-2", b"step-3", b"step-4", b"step-5"]
    # Besides the planned steps, only the publisher's answers to the request for values.
    planned = set(seqs) | {frames[0]["seq"], frames[-1]["seq"]}
    assert {bytes.fromhex(f["event"]["tag_hex"]) for f in frames
            if f["seq"] not in planned} <= {b"refresh"}
    events = [f["event"] for f in frames]
    assert events[0]["type"] == "generation_start" and events[-1]["type"] == "generation_end"
    assert by_seq[seqs[0]]["reported_class"] == PE
    assert {(e["sent_order"], e["received_order"]) for e in events
            if e["type"] == "reflect"} == {("RECEIVE", "RECEIVE")}
    assert result["refreshes"] >= 1
    records = lines(tmp_path / "main" / "observations.jsonl")
    assert {r["payload"]["reported_class"] for r in records if r["kind"] == "snapshot"} == {PE}
    assert [r["payload"]["code"] for r in records if r["kind"] == "diagnostic"].count(
        "W_FOM_UNVERIFIED") == 1
    assert b"GroundVehicle" not in capture.read_bytes() + \
        (tmp_path / "main" / "observations.jsonl").read_bytes()
    assert result["destroyed"] and verify_capture(capture)["status"] == "COMPLETE"


@pytest.mark.rti
@case("G-R14", "G-R12", paragraphs=("SPEC:62", "SPEC:56"))
def test_a_tcp_reset_is_connection_lost_then_a_rejoin_under_the_same_name(tmp_path):
    """NAT-03 with the RST proxy between the real worker and rtinode (the native evidence of
    A-RECONNECT): once the capture shows the first generation's discovery, the proxy resets the
    observer's connection. OpenRTI calls connectionLost: the worker reports E_RTI_CONNECT, the
    host ends generation 1 with connection_lost and starts the next worker after the first
    delay (1 s: the capture's own elapsed time grows by at least that between the two
    boundaries), which joins again under the same federate name through the proxy (generation 2
    starts) and sees the object anew as o1 of generation 2; the steps then arrive in generation
    2, the session ends in order, COMPLETE, two workers."""
    result = run_driver(tmp_path, "rst")
    assert result["failure"] is None and result["broken"] == 1
    capture = tmp_path / "rst" / "capture.jsonl"
    got = shape(capture)
    refresh = (2, "reflect", b"refresh".hex(), "o1")
    # The publisher may answer the new generation's request for values (a `refresh`
    # reflection, R38: extra refreshes are allowed and are evidence); never before the discovery.
    assert [row for row in got if row != refresh] == [
        (1, "generation_start", None, None), (1, "discover", None, "o1"),
        (1, "diagnostic", "E_RTI_CONNECT", None), (1, "generation_end", "connection_lost", None),
        (2, "generation_start", None, None), (2, "discover", None, "o1")] + [
        (2, "reflect", f"step-{n}".encode().hex(), "o1") for n in range(1, 5)] + [
        (2, "remove", b"step-5".hex(), "o1"), (2, "generation_end", "stop", None),
        ("footer", "COMPLETE", None, 2)], got
    assert refresh not in got[:6]
    frames = frames_of(capture)
    assert int(frames[4]["elapsed_ns"]) - int(frames[3]["elapsed_ns"]) >= 1 * SECOND
    session = result["host_result"]["result"]["session"]
    assert (session["status"], session["workers"], session["last_generation"]) == (
        "COMPLETE", 2, 2)
    assert result["destroyed"]


#: The values the publisher holds once step 4 was sent, as the capture must show them in its answer
#: to a request for values: V-ID-123 (site 1, application 2, entity 3: 0001 0002 0003),
#: V-TYPE-PLATFORM (kind 1, domain 1, country 225 = 0x00e1, category 1, subcategory 2, specific
#: 3, extra 4), V-FORCE-1 (01) and step 4's Spatial, the bundled capture's at seq 6 (DRM_FPW 02,
#: seven padding bytes, x = 6378147.0 = 0x415854A8C0000000, y = z = 0, frozen 0, three padding
#: bytes, the three angles 0, velocity (0, 10.0 = 0x41200000, 0)).
CURRENT_VALUES = {
    "EntityIdentifier": "000100020003",
    "EntityType": "010100e101020304",
    "ForceIdentifier": "01",
    "Spatial": ("0200000000000000415854a8c000000000000000000000000000000000000000"
                "00000000000000000000000000000000000000004120000000000000"),
}


@pytest.mark.rti
@case("G-R38", "G-R12", paragraphs=("SPEC:207", "SPEC:56"))
def test_a_request_between_scripted_updates_is_answered_with_the_publishers_current_values(
        tmp_path):
    """R38 (SPEC:207): "It responds to provideAttributeValueUpdate by sending its current values,
    including requests arriving between scripted updates" (R8-r1-F2). With the RST proxy between
    the real worker and rtinode, the reset comes once the capture shows step 4: the publisher then
    waits at barrier 4 holding a value of each of the four attributes; the worker rejoins
    (generation 2), is told of the object again and asks for its values (R12). The publisher's
    answer is one reflection tagged `refresh` carrying exactly its current bytes of the four
    attributes (the packaged vectors and step 4's Spatial, written out above), captured in
    generation 2 after the discovery and before the removal; the publisher's own `refresh` event
    for it says 4 attributes and came while it waited at barrier 4, between step 4 and step 5;
    and the run's refresh evidence (`Run.refresh_seqs`, what demo.json's `refresh_seqs` holds)
    lists exactly the capture's reflections tagged `refresh`. A publisher that announces an
    answer but sends none never passes barrier 4."""
    vectors = positive_hex()
    seq6 = [r for r in fixture_capture_records()[1:] if r.get("seq") == 6][0]
    assert CURRENT_VALUES == {"EntityIdentifier": vectors["ID-123"],
                              "EntityType": vectors["TYPE-PLATFORM"],
                              "ForceIdentifier": vectors["FORCE-1"],
                              "Spatial": seq6["event"]["attributes"][0]["hex"]}
    result = run_driver(tmp_path, "refresh")
    assert result["failure"] is None and result["broken"] == 1, result["failure"]
    capture = tmp_path / "refresh" / "capture.jsonl"
    got = shape(capture)
    refresh = b"refresh".hex()
    # The first generation's request may reach the publisher after a step and be answered with
    # the values it had then (R38: allowed, and evidence); everything else is fixed.
    early = [row for row in got if row[0] == 1 and row[1:3] == ("reflect", refresh)]
    assert [row for row in got if row not in early] == [
        (1, "generation_start", None, None), (1, "discover", None, "o1")] + [
        (1, "reflect", f"step-{n}".encode().hex(), "o1") for n in range(1, 5)] + [
        (1, "diagnostic", "E_RTI_CONNECT", None), (1, "generation_end", "connection_lost", None),
        (2, "generation_start", None, None), (2, "discover", None, "o1"),
        (2, "reflect", refresh, "o1"), (2, "remove", b"step-5".hex(), "o1"),
        (2, "generation_end", "stop", None), ("footer", "COMPLETE", None, 2)], got
    frames = frames_of(capture)
    [answer] = [f for f in frames if f["generation"] == 2 and f["event"]["type"] == "reflect"]
    assert {a["name"]: a["hex"] for a in answer["event"]["attributes"]} == CURRENT_VALUES
    assert len(answer["event"]["attributes"]) == 4
    tagged = [f["seq"] for f in frames
              if f["event"]["type"] == "reflect" and f["event"]["tag_hex"] == refresh]
    assert answer["seq"] in tagged and result["refresh_seqs"] == tagged
    events = result["publisher_events"]
    answers = [e for e in events if e["event"] == "refresh"]
    assert answers[-1] == {"attributes": 4, "event": "refresh"}
    assert sum(1 for e in answers if e["attributes"]) == len(tagged) == \
        result["refresh_reflections"]
    position = events.index(answers[-1])
    assert events.index({"barrier": 4, "event": "waiting"}) < position < \
        events.index({"barrier": 4, "event": "acknowledged"}) < \
        events.index({"event": "sent", "step": 5})
    session = result["host_result"]["result"]["session"]
    assert (session["status"], session["workers"], session["last_generation"]) == (
        "COMPLETE", 2, 2)
    assert result["destroyed"] and verify_capture(capture)["status"] == "COMPLETE"


@pytest.mark.rti
@case("G-R14", "G-R25", paragraphs=("SPEC:62",))
def test_an_orderly_close_is_no_connection_lost_but_one_removal_per_known_object(tmp_path):
    """NAV-02 with the FIN proxy: once the capture shows step 4 (the object known, values cached),
    the proxy closes the observer's connection with FIN. OpenRTI calls no connectionLost; it
    removes every object the observer knows: the capture's next event is a removal of o1 with an
    empty tag (not the publisher's `step-5`), received order RECEIVE, no logical time; there is
    no E_RTI_CONNECT and no generation_end until the orderly stop: the generation stays open with
    zero objects (the reducer's removed notice clears the state, R25). The session then ends in
    order, COMPLETE, one worker. Never "last values kept"."""
    result = run_driver(tmp_path, "fin")
    assert result["failure"] is None and result["broken"] == 1
    capture = tmp_path / "fin" / "capture.jsonl"
    events = [f["event"] for f in frames_of(capture)]
    removal = [e for e in events if e["type"] == "remove"]
    assert removal == [{"type": "remove", "object_token": "o1", "tag_hex": "",
                        "received_order": "RECEIVE", "logical_time": None,
                        "retractable": False}]
    assert events.index(removal[0]) == len(events) - 2
    assert events[-1] == {"type": "generation_end", "reason": "stop"}
    assert [e["type"] for e in events].count("generation_end") == 1
    assert "diagnostic" not in [e["type"] for e in events]
    tags = [bytes.fromhex(e["tag_hex"]) for e in events if e["type"] == "reflect"]
    assert [t for t in tags if t != b"refresh"] == [b"step-1", b"step-2", b"step-3", b"step-4"]
    records = lines(tmp_path / "fin" / "observations.jsonl")
    removed = [r for r in records if r["kind"] == "removed"]
    assert len(removed) == 1 and removed[0]["payload"]["reason"] == "removed"
    session = result["host_result"]["result"]["session"]
    assert (session["status"], session["workers"], session["last_generation"]) == (
        "COMPLETE", 1, 1)


# ===================================================================== observe on a real federation

def observe(tmp_path: pathlib.Path, config: dict, *extra):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    args = ["observe", "--config", path, "--out", tmp_path / "run", *extra]
    env = environment(tmp_path, extra={"SYNAPSE_HLA_WORKER": str(worker())})
    proc, before = start(tmp_path, *args, env=env)
    return proc, before, args


@pytest.mark.rti
@case("G-R36", "G-R14", "A-SIGNAL", paragraphs=("SPEC:174", "SPEC:184", "SPEC:62"))
@pytest.mark.parametrize("stop", ["SIGINT", "SIGTERM", "duration"])
def test_observe_joined_to_a_real_federation_stops_in_order_and_exits_0(tmp_path, stop):
    """SPEC:174, R14 and A-SIGNAL against a real rtinode (the carried G-R14 and G-R36 clauses):
    `synapse-hla observe` with the real worker joins a federation another process created; once
    the capture shows the generation started, SIGINT or SIGTERM reaches the command (or the
    duration of 3 seconds ends): the worker finishes its batch, resigns NO_ACTION, disconnects
    and exits by itself; generation_end stop, footer COMPLETE, run.json says complete, exit 0
    with W_FOM_UNVERIFIED only; the federation's creator can destroy it afterwards (nothing of
    the observer is left joined)."""
    node = Rtinode(tmp_path)
    holder = None
    try:
        holder = TestFederate(node.endpoint, "SC_DEMO_00000000000000dd", "SC_TEST_HOLDER",
                              fom_modules())
        config = existing(node.endpoint, "SC_DEMO_00000000000000dd")
        extra = ("--duration-seconds", "3") if stop == "duration" else ()
        proc, before, args = observe(tmp_path, config, *extra)
        capture = tmp_path / "run" / "capture.jsonl"
        if stop != "duration":
            deadline = time.monotonic() + 30
            while not (capture.exists() and b'"generation_start"' in capture.read_bytes()):
                assert time.monotonic() < deadline and proc.poll() is None
                time.sleep(0.02)
            proc.send_signal(getattr(signal, stop))
        ran = finish(tmp_path, proc, before, args, creates=["run"])
        assert ran.code == 0 and ran.summary["codes"] == ["W_FOM_UNVERIFIED"]
        assert shape(capture) == [(1, "generation_start", None, None),
                                  (1, "generation_end", "stop", None),
                                  ("footer", "COMPLETE", None, 1)]
        run = strict_json((tmp_path / "run" / "run.json").read_bytes())
        assert run["capture_complete"] is True
        session = ran.summary["result"]["session"]
        assert (session["status"], session["workers"]) == ("COMPLETE", 1)
        assert holder.finish() == ["created", "ready", "resigned", "destroyed", "disconnected"]
    finally:
        if holder is not None:
            holder.kill()
        node.stop()


# ============================================================================ R47, A-ENCODING

def build_tool(name: str) -> pathlib.Path:
    """A reference tool of the native build, beside the worker (check.sh builds all of them)."""
    path = pathlib.Path(native_executable("SYNAPSE_HLA_WORKER")).parent / name
    if not path.is_file():
        pytest.fail(f"{name} is not beside the worker in the native build")
    return path


def results_file() -> bytes:
    """The bundle's reference-encoding-results.txt, from the handoff's references directory (the
    FOM directory), held to its pin in the packaged pins.json before it is read."""
    path = fom_modules()[0].parent / "reference-encoding-results.txt"
    data = path.read_bytes()
    pin = packaged_pins()["reference-encoding-results.txt"]
    assert len(data) == pin["bytes"] and hashlib.sha256(data).hexdigest() == pin["sha256"]
    return data


@pytest.mark.rti
@case("A-ENCODING", "G-R47", "G-R18")
def test_the_reference_encoder_matches_the_nine_packaged_spatial_vectors_and_the_results():
    """A-ENCODING (R47, the carried G-R18 clause): the bundle's reference_encode.cpp, vendored
    byte for byte and built against the pinned OpenRTI, encodes the nine Spatial variants with
    OpenRTI's HLAfixedRecord and primitive helpers and an explicit one-octet discriminator
    (never HLAvariantRecord): its nine lines are, byte for byte, the bundle's
    reference-encoding-results.txt, and line n carries algorithm n and exactly the hex of the
    packaged vector SPATIAL-n. Each starts with the discriminator and the seven-byte alignment
    prefix of zeros (bytes 1-7), and the product's decoder reads each to the packaged expected
    value (the production codec implements the same table). The encoder never calls the product
    codec: it is C++ against OpenRTI alone."""
    output = subprocess.run([str(build_tool("sc-hla-reference-encode"))], capture_output=True,
                            timeout=60)
    assert output.returncode == 0 and output.stderr == b""
    assert output.stdout == results_file()
    vectors = {v["id"]: v for v in fixture_json("attributes-positive.json")}
    rows = [line.split(" ") for line in output.stdout.decode("ascii").splitlines()]
    assert [int(a) for a, _ in rows] == list(range(1, 10))
    for algorithm, hex_ in rows:
        vector = vectors[f"SPATIAL-{algorithm}"]
        assert hex_ == vector["hex"] and hex_[:16] == f"0{algorithm}" + "00" * 7
        decoded = decode_attribute("Spatial", bytes.fromhex(hex_))
        assert decoded["name"] == "Spatial"
        assert_strict_equal(decoded["value"], vector["expected"])
    code = code_of((PACKAGE_ROOT / "tools" / "reference" / "reference_encode.cpp").read_text(
        "utf-8"))
    assert "HLAvariantRecord" not in code and "HLAfixedRecord" in code
    assert "synapse" not in code.lower() and "include <RTI/encoding/" in code


@pytest.mark.rti
@case("G-R47", "G-R38", paragraphs=("SPEC:207",))
def test_the_bundles_fom_check_passes_against_an_rtinode_of_the_demos_kind(tmp_path):
    """REFERENCE-CHECKS: the bundle's reference_fom_check.cpp, vendored and built, against an
    rtinode the demo's way (`_demo.Rtinode`: 127.0.0.1, LC_ALL=C, ready by a raw connect): the
    five modules load, PhysicalEntity and its four attributes resolve, subscription and cleanup
    succeed, and it creates and destroys only SC_REFERENCE_FOM_CHECK (a second run passes too,
    so the first left nothing behind)."""
    from synapse_hla import _demo
    node = _demo.Rtinode()
    environ = {k: v for k, v in os.environ.items() if not k.startswith("SYNAPSE_HLA_")}
    assert node.start(str(native_executable("SYNAPSE_HLA_RTINODE")), environ, _demo.V1,
                      lambda: None) is None
    try:
        for _ in range(2):
            check = subprocess.run([str(build_tool("sc-hla-reference-fom-check")),
                                    f"rti://127.0.0.1:{node.port}", str(fom_modules()[0].parent)],
                                   capture_output=True, timeout=60)
            assert check.returncode == 0, check.stderr
            assert check.stdout == (b"PASS: five modules load; PhysicalEntity and four "
                                    b"attributes resolve; subscribe and cleanup succeed\n")
    finally:
        node.stop(_demo.V1)
    assert node.port_released is True and process_gone(node.child.pid)


# ============================================================================ R42's load shape, DEV

@pytest.mark.perf
@case("G-R12", "G-R41", paragraphs=("SPEC:279",))
def test_the_perf_load_shape_runs_under_the_host_without_loss(tmp_path):
    """The publisher's perf:1000:1:20 under the real host on this machine (DEV-macOS-arm64, an
    early warning for R42, never its evidence, CR-L04), with the demo's no-time configuration
    (time policy none: every reflection captured, reduced and written as a snapshot, no CDM
    projection): 1000 objects discovered, 1000 identity reflections, 20000 load reflections (1000
    objects at 1 Hz for 20 s) and 1000 removals, every one in the capture (no loss), no
    E_QUEUE_OVERFLOW or E_LIMIT, the capture verifies COMPLETE. The counts are printed as the
    observation. The same load with external_elapsed (a CDM Entity validated per reflection,
    R44) is the R42 question CR-L17 leaves to the reference platform; its DEV observation on this
    machine is in the round's report, not asserted here."""
    result = run_driver(tmp_path, "perf", perf=[1000, 1, 20], config="no-time")
    assert result["failure"] is None, result
    capture = tmp_path / "perf" / "capture.jsonl"
    events = [f["event"] for f in frames_of(capture)]
    count = {}
    for event in events:
        key = (event["type"], bytes.fromhex(event["tag_hex"]).decode() if "tag_hex" in event
               else None)
        count[key] = count.get(key, 0) + 1
    assert count[("discover", None)] == 1000
    assert count[("reflect", "perf-identity")] == 1000
    assert count[("reflect", "perf")] == 20000
    assert count[("remove", "perf-remove")] == 1000
    assert set(count) <= {("generation_start", None), ("discover", None),
                          ("reflect", "perf-identity"), ("reflect", "perf"),
                          ("reflect", "refresh"), ("remove", "perf-remove"),
                          ("generation_end", None)}
    report = verify_capture(capture)
    assert report["status"] == "COMPLETE"
    session = result["host_result"]["result"]["session"]
    assert session["status"] == "COMPLETE" and session["workers"] == 1
    assert session["terminal_codes"] == []
    print(json.dumps({"observation": "DEV perf:1000:1:20, time policy none",
                      "frames": report["frames"],
                      "counts": {f"{k[0]}:{k[1]}": v for k, v in sorted(count.items(),
                                                                          key=str)},
                      "records": session["records"]}, sort_keys=True))


# ================================================================== R42: A-PERFORMANCE, overload

#: R42's machine: "a recorded 4-vCPU x86_64 system with 8 GiB RAM", on the reference platform of
#: SPEC:20 (Linux x86_64, Ubuntu 24.04). Memory reads a little under the nominal size inside a VM,
#: so 7 to 9 GiB is accepted as 8 GiB.
R42_CPUS = 4
R42_MEMORY = (7 * 2**30, 9 * 2**30)
#: R42's load and its target: 1000 objects, 1 reflection per object per second, 60 seconds, and a
#: p95 host callback-to-output delay of at most 250 ms.
R42_SHAPE = (1000, 1, 60)
R42_P95_NS = 250_000_000


def memory_bytes() -> int | None:
    """Physical memory, read from the system (Linux /proc/meminfo, macOS sysctl), or None."""
    try:
        for line in pathlib.Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    sysctl = pathlib.Path("/usr/sbin/sysctl")
    if sysctl.is_file():
        out = subprocess.run([str(sysctl), "-n", "hw.memsize"], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip().isdigit():
            return int(out.stdout.strip())
    return None


def os_release() -> dict:
    try:
        lines = pathlib.Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    return dict(line.split("=", 1) for line in lines if "=" in line)


def machine_label() -> str:
    """CR-L04's evidence class of this machine: DEV-macOS-arm64, DEV-linux-<machine>, or the
    reference platform's REFERENCE-linux-x86_64 when R42's machine is this one."""
    import platform
    system, machine = platform.system(), platform.machine()
    if system == "Darwin":
        return f"DEV-macOS-{machine}"
    release = os_release()
    memory = memory_bytes()
    if (system == "Linux" and machine == "x86_64" and release.get("ID") == "ubuntu"
            and release.get("VERSION_ID") == '"24.04"' and os.cpu_count() == R42_CPUS
            and memory is not None and R42_MEMORY[0] <= memory < R42_MEMORY[1]):
        return "REFERENCE-linux-x86_64"
    return f"DEV-{system.lower()}-{machine}"


def _unescape_mount_field(field: str) -> str:
    # /proc/self/mounts writes a space, tab, newline or backslash in a path as a 3-digit octal
    # escape.
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def filesystem_of(directory: pathlib.Path) -> dict:
    """The filesystem `directory` lives on, as R42's report names it: its type (apfs, ext4, ...),
    with the device and mount point that identify it. The mount comes from `df -P`; its type
    from the mount table (`mount` on macOS, /proc/self/mounts on Linux; the last entry for the
    mount point is the one in effect). A fact that cannot be read is None, never a guess."""
    import platform
    facts = {"type": None, "device": None, "mount_point": None}
    listed = subprocess.run(["/bin/df", "-P", str(directory)], capture_output=True, text=True)
    if listed.returncode != 0 or len(listed.stdout.splitlines()) < 2:
        return facts
    # Six columns, the last of which (the mount point) may itself hold spaces.
    fields = listed.stdout.splitlines()[-1].split(None, 5)
    if len(fields) != 6:
        return facts
    device, mount_point = fields[0], fields[5]
    facts.update(device=device, mount_point=mount_point)
    if platform.system() == "Darwin":
        table = subprocess.run(["/sbin/mount"], capture_output=True, text=True)
        for line in table.stdout.splitlines() if table.returncode == 0 else []:
            head, _, options = line.rpartition(" (")
            if head == f"{device} on {mount_point}" and options:
                facts["type"] = options.split(",", 1)[0].rstrip(")").strip()
    else:
        try:
            table_text = pathlib.Path("/proc/self/mounts").read_text(encoding="utf-8")
        except OSError:
            return facts
        for line in table_text.splitlines():
            parts = line.split()
            if len(parts) >= 3 and _unescape_mount_field(parts[1]) == mount_point:
                facts["type"] = parts[2]
    return facts


#: A mount-table type name: lower-case letters, digits, dots, underscores and hyphens (a FUSE
#: subtype carries hyphens, as fuse.fuse-overlayfs of rootless containers or fuse.vmhgfs-fuse of
#: VMware shared folders do; review finding R9-r2-F9), never a device path.
MOUNT_TYPE = re.compile(r"[a-z0-9_.-]+")


@pytest.mark.parametrize("name,admitted", [
    ("apfs", True), ("ext4", True), ("overlay", True), ("tmpfs", True), ("virtiofs", True),
    ("9p", True), ("fuse.sshfs", True), ("fuse.fuse-overlayfs", True),
    ("fuse.vmhgfs-fuse", True), ("/dev/disk3s5", False), ("/dev/vda1", False), ("", False),
    ("ext4 rw", False)])
def test_a_mount_type_is_a_mount_table_name_hyphens_included(name, admitted):
    """The filesystem type the performance report names is a mount-table name; hyphens are
    admitted (review finding R9-r2-F9), a device path, an empty name or a name with a space is
    not. The names are real mount types (macOS, Linux, FUSE) and devices, written by hand."""
    assert bool(MOUNT_TYPE.fullmatch(name)) is admitted


def test_the_performance_report_names_the_filesystem_type_not_only_its_device(tmp_path):
    """R42 asks a performance report to name the filesystem (review finding R9-r1-F6): the
    machine facts carry the type of the filesystem the run's directory lives on, beside the
    device node and mount point that identify it. The type is a mount-table name (`MOUNT_TYPE`:
    letters, digits, dots, underscores, hyphens), never a device path; on macOS a temporary
    directory lives on APFS (the filesystem of the data volume every supported macOS keeps)."""
    import platform
    facts = filesystem_of(tmp_path)
    assert set(facts) == {"type", "device", "mount_point"}
    assert facts["type"] and MOUNT_TYPE.fullmatch(facts["type"]), facts
    assert facts["device"] and facts["mount_point"].startswith("/"), facts
    assert facts["type"] != facts["device"]
    if platform.system() == "Darwin":
        assert facts["type"] == "apfs", facts


def machine_facts(directory: pathlib.Path) -> dict:
    """What R42 asks a performance report to name: hardware, filesystem and build."""
    import platform
    worker = native_executable("SYNAPSE_HLA_WORKER")
    return {
        "evidence_class": machine_label(), "system": platform.system(),
        "release": platform.release(), "machine": platform.machine(),
        "cpus": os.cpu_count(), "memory_bytes": memory_bytes(),
        "distribution": os_release().get("PRETTY_NAME", "").strip('"') or None,
        "python": platform.python_version(),
        # Other work on the machine competes for it; the run neither controls nor excludes it.
        "load_average_1m": f"{os.getloadavg()[0]:.2f}",
        "filesystem": filesystem_of(directory),
        "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
    }


def monotonic_ns() -> int:
    # The worker's clock (CLOCK_MONOTONIC), which on macOS is not time.monotonic's.
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC)


class Tail:
    """The complete lines a growing file gains, each stamped with the monotonic instant this
    process first saw it."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.offset = 0
        self.partial = b""
        self.lines: list[tuple[int, bytes]] = []

    def poll(self) -> None:
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
        except FileNotFoundError:
            return
        if not chunk:
            return
        now = monotonic_ns()
        self.offset += len(chunk)
        data = self.partial + chunk
        *complete, self.partial = data.split(b"\n")
        self.lines += [(now, line) for line in complete]


def watched_perf_run(tmp_path: pathlib.Path, shape: tuple, config: str) -> tuple[dict, dict]:
    """`demo_driver.py` running the publisher's perf:O:H:S under the real host, while this
    process tails the capture and the observations: (the driver's result, what the tails saw).
    Every process the run started is asserted reaped and gone, as `run_driver` asserts."""
    out = tmp_path / "perf"
    result_path = tmp_path / "perf.json"
    arguments = {"kind": "perf", "out": str(out), "result": str(result_path),
                 "perf": list(shape), "config": config}
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for variable in ("SYNAPSE_HLA_WORKER", "SYNAPSE_HLA_RTINODE", "SYNAPSE_HLA_PUBLISHER"):
        env[variable] = str(native_executable(variable))
    env["SYNAPSE_HLA_FOM_DIR"] = str(fom_modules()[0].parent)
    tails = {"capture": Tail(out / "capture.jsonl"),
             "observations": Tail(out / "observations.jsonl")}
    # stderr goes to a file: a pipe nobody reads while the run lasts could fill and stall it.
    with (tmp_path / "driver.stderr").open("wb") as errors:
        proc = subprocess.Popen([sys.executable, str(TESTS_DIR / "demo_driver.py"),
                                 json.dumps(arguments)], env=env, stdout=subprocess.DEVNULL,
                                stderr=errors)
    deadline = time.monotonic() + 1800
    while proc.poll() is None:
        if time.monotonic() > deadline:
            proc.terminate()
            proc.wait(60)
            pytest.fail("the perf run did not end within its safety bound")
        for tail in tails.values():
            tail.poll()
        time.sleep(0.005)
    for tail in tails.values():
        tail.poll()
    stderr = (tmp_path / "driver.stderr").read_bytes()
    assert proc.returncode == 0, stderr.decode(errors="replace")[-3000:]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    for process in result["processes"]:
        assert process["reaped"] and process_gone(process["pid"]), process
    assert result["rtinode"]["port_released"] is True and process_gone(result["rtinode"]["pid"])
    return result, tails


def nearest_rank(values: list[int], percent: int) -> int:
    """The nearest-rank percentile of integer nanoseconds (no float arithmetic)."""
    ordered = sorted(values)
    rank = -(-percent * len(ordered) // 100)
    return ordered[max(rank, 1) - 1]


def measure(tails: dict, shape: tuple) -> dict:
    """R42's measurement from the capture's own timestamps and the moments the outputs appeared.

    A load frame's callback instant is the session origin plus its `elapsed_ns`, both on the
    worker's CLOCK_MONOTONIC. The origin is not written anywhere, so it is bounded from the
    capture: no frame can appear in the file before its callback, so the origin is at most the
    smallest (instant seen - elapsed_ns) over the frames; that bound is used, which can only
    make a delay look shorter, by at most the smallest write latency of the run, and this
    process's 5 ms polling can make one look longer by as much. The delay of a load reflection
    is the instant its first output record (a snapshot, then the Entity upsert) appeared minus
    its callback instant: host callback-to-output, RTI delivery excluded."""
    frames: dict[int, tuple[int, int, str | None, str]] = {}
    for seen, line in tails["capture"].lines:
        record = json.loads(line)
        if record.get("type") != "frame":
            continue
        event = record["event"]
        tag = bytes.fromhex(event["tag_hex"]).decode() if "tag_hex" in event else None
        frames[record["seq"]] = (seen, int(record["elapsed_ns"]), tag, event["type"])
    origin = min(seen - elapsed for seen, elapsed, _, _ in frames.values())
    first_output: dict[int, int] = {}
    for seen, line in tails["observations"].lines:
        seq = json.loads(line)["seq"]
        first_output.setdefault(seq, seen)
    load = {seq: f for seq, f in frames.items() if f[3] == "reflect" and f[2] == "perf"}
    delays = [first_output[seq] - (origin + f[1]) for seq, f in load.items()
              if seq in first_output]
    objects, hz, seconds = shape
    expected = objects * hz * seconds
    out = {"shape": "perf:{}:{}:{}".format(*shape), "load_expected": expected,
           "load_captured": len(load), "load_with_output": len(delays),
           "overflow": any(f[3] == "diagnostic" for f in frames.values())}
    if delays:
        callbacks = [origin + f[1] for f in load.values()]
        window = max(first_output[s] for s in load if s in first_output) - min(callbacks)
        out.update({
            "throughput_per_s": (len(delays) * 10**9) // max(window, 1),
            "p50_ms": nearest_rank(delays, 50) // 10**6,
            "p95_ms": nearest_rank(delays, 95) // 10**6,
            "p99_ms": nearest_rank(delays, 99) // 10**6,
            "p95_ns": nearest_rank(delays, 95),
        })
    return out


@pytest.mark.perf
@case("A-PERFORMANCE", "G-R42")
def test_r42_load_on_the_reference_machine_without_loss_within_the_p95_target(tmp_path,
                                                                              record_property):
    """A-PERFORMANCE and R42: the synthetic publisher's perf:1000:1:60 (1000 reflections per
    second over 1000 objects for 60 seconds) under the real host with the demo's main
    configuration (time policy external_elapsed: every reflection projected and validated as a
    CDM Entity, R44), measured live, never from a replay: every load reflection captured and
    output (no loss), no queue overflow, the capture COMPLETE, and the p95 host callback-to-output
    delay at most 250 ms; throughput and p50/p95/p99 reported with the hardware, the filesystem
    and the build. PASS only on R42's machine (CR-L04): anywhere else the run is made and
    measured, its figures are recorded as this test's `observation` property, and the test
    reports BLOCKED on the reference platform it lacks."""
    result, tails = watched_perf_run(tmp_path, R42_SHAPE, "main")
    measured = measure(tails, R42_SHAPE)
    session = (result["host_result"] or {}).get("result", {}).get("session") or {}
    report = verify_capture(tmp_path / "perf" / "capture.jsonl")
    measured.update({"session_status": session.get("status"),
                     "terminal_codes": session.get("terminal_codes"),
                     "capture_status": report["status"], "frames": report["frames"],
                     "machine": machine_facts(tmp_path)})
    record_property("observation", json.dumps(measured, sort_keys=True))
    print(json.dumps({"observation": measured}, sort_keys=True))
    if measured["machine"]["evidence_class"] != "REFERENCE-linux-x86_64":
        blocked(f"R42's reference machine (Linux x86_64, Ubuntu 24.04, {R42_CPUS} vCPU, 8 GiB): "
                f"this one is {measured['machine']['evidence_class']}; its measurement is the "
                "recorded observation")
    assert result["failure"] is None, result["failure"]
    assert session["status"] == "COMPLETE" and session["terminal_codes"] == []
    assert report["status"] == "COMPLETE"
    assert measured["load_captured"] == measured["load_expected"] == 60000
    assert measured["load_with_output"] == 60000 and not measured["overflow"]
    assert measured["p95_ns"] <= R42_P95_NS


@pytest.mark.perf
@case("G-R42")
def test_a_load_beyond_the_queue_fails_visibly(tmp_path, record_property):
    """R42's second run: a load that deliberately exceeds the worker's queue capacity
    (perf:1000:5:20, five times R42's rate, with every reflection projected) must fail visibly,
    on any machine: the worker reports E_QUEUE_OVERFLOW, the host closes the generation and
    writes the footer FAILED with that code (R41), the session's first terminal code is
    E_QUEUE_OVERFLOW, the capture verifies FAILED (not INVALID: what was captured is evidence),
    the overflow is a captured diagnostic, nothing captured is dropped silently, and every
    process is stopped. A machine fast enough to carry this load would fail the test, which then
    no longer exceeds its capacity and must be made heavier."""
    shape = (1000, 5, 20)
    result, tails = watched_perf_run(tmp_path, shape, "main")
    measured = measure(tails, shape)
    session = result["host_result"]["result"]["session"]
    capture = tmp_path / "perf" / "capture.jsonl"
    report = verify_capture(capture)
    records = lines(capture)
    footer = records[-1]
    diagnostics = [r["event"]["diagnostic"]["code"] for r in records[1:-1]
                   if r["event"]["type"] == "diagnostic"]
    record_property("observation", json.dumps(dict(measured, frames=report["frames"],
                                                   machine=machine_label()), sort_keys=True))
    assert session["status"] == "FAILED" and session["terminal_codes"][0] == "E_QUEUE_OVERFLOW"
    assert (footer["type"], footer["status"], footer["reason_code"]) == (
        "footer", "FAILED", "E_QUEUE_OVERFLOW")
    assert report["status"] == "FAILED" and report["capture_complete"] is False
    assert diagnostics == ["E_QUEUE_OVERFLOW"]
    assert records[-2]["event"]["type"] == "generation_end"
    assert 0 < measured["load_captured"] < measured["load_expected"]
    assert result["failure"] is not None


# ============================================================================ COD-09, CDV-02: PROJ

#: cs2cs at its fixed places (`hla_support.TOOL_PLACES`), never through PATH.
CS2CS = tool_place("cs2cs")
#: The 175 points of the handoff's geodesy check (tools/check_geodesy.py): latitude, longitude,
#: height in metres.
GRID = [(lat, lon, h) for lat in (-89.999, -75.0, -45.0, 0.0, 45.0, 75.0, 89.999)
        for lon in (-180.0, -90.0, 0.0, 90.0, 179.999)
        for h in (-1000.0, 0.0, 10000.0, 1000000.0, 90000000.0)]


def cs2cs_forward(points: list[tuple]) -> tuple[list[tuple], str]:
    """PROJ's forward EPSG:4979 -> EPSG:4978 (latitude, longitude, height in -> ECEF metres out)
    through the cs2cs binary, a fixed argument vector, and the version it reports."""
    if CS2CS is None:
        fixed_tool("cs2cs")
    version = subprocess.run([str(CS2CS)], capture_output=True, text=True, timeout=30)
    first = (version.stdout + version.stderr).splitlines()[0]
    text = "".join(f"{lat!r} {lon!r} {h!r}\n" for lat, lon, h in points)
    run = subprocess.run([str(CS2CS), "-f", "%.17g", "EPSG:4979", "EPSG:4978"], input=text,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = [tuple(float(v) for v in line.split()[:3]) for line in run.stdout.splitlines()]
    assert len(out) == len(points)
    return out, first


@pytest.mark.reference
@case("G-R47", "G-R29", paragraphs=("SPEC:142",))
def test_the_product_inverse_agrees_with_proj_forward_on_the_175_point_grid(record_property):
    """COD-09 as corrected and CDV-02 (R47: a separate geodesy implementation): PROJ's cs2cs
    carries the handoff's 175 grid points forward, EPSG:4979 to EPSG:4978 (the direction only:
    its inverse is off by up to 0.32 m there, DECISIONS C.1), and the product's inverse gives the
    latitude, longitude and height back within 1e-8 degrees and 1e-4 metres (SPEC:144); the
    geodesy fixture's five points go forward to their ECEF values within 1e-4 m and come back to
    their expected coordinates the same way. The PROJ version is the one cs2cs states at run
    time (never a copied string), asserted to name a PROJ release and recorded, with the fixed
    place of the cs2cs that stated it, as the test's observation: the release evidence report
    carries it with the cases this test binds (CDV-02, final review finding F-release-01)."""
    ecef, version = cs2cs_forward(GRID)
    record_property("proj_version", version)
    print(f"cs2cs: {CS2CS}: {version}")
    assert re.match(r"Rel\. \d+\.\d+\.\d+, ", version), version
    record_property("observation", json.dumps({"cs2cs": place_text("cs2cs", CS2CS),
                                                "proj_version": version}, sort_keys=True))
    worst_lat = worst_h = 0.0
    for (lat, lon, h), (x, y, z) in zip(GRID, ecef):
        geo = geodesy.geodetic(x, y, z)
        assert abs(geo.latitude_deg - lat) < 1e-8 and abs(geo.height_m - h) < 1e-4, (lat, lon, h)
        assert abs((geo.longitude_deg - lon + 180.0) % 360.0 - 180.0) < 1e-8, (lat, lon, h)
        worst_lat = max(worst_lat, abs(geo.latitude_deg - lat))
        worst_h = max(worst_h, abs(geo.height_m - h))
    record_property("max_latitude_error_deg", worst_lat)
    record_property("max_altitude_error_m", worst_h)
    entries = [e for e in fixture_json("geodesy.json") if "expected" in e]
    assert len(entries) == 5
    forward, _ = cs2cs_forward([tuple(e["expected"]) for e in entries])
    for entry, (x, y, z) in zip(entries, forward):
        assert math.dist((x, y, z), entry["ecef_m"]) < 1e-4, entry["id"]
        geo = geodesy.geodetic(*entry["ecef_m"])
        lat, lon, h = entry["expected"]
        assert abs(geo.latitude_deg - lat) < 1e-8 and abs(geo.height_m - h) < 1e-4
        assert abs((geo.longitude_deg - lon + 180.0) % 360.0 - 180.0) < 1e-8


# ============================================================================ the publisher alone

class Publisher:
    """`sc-hla-publisher` started as the demo starts it (its own process group, stdin the barrier
    pipe, stdout its events), against a real rtinode, with nobody observing."""

    def __init__(self, endpoint: str, federation: str, *, pins: dict | None = None,
                 scenario: str = "main") -> None:
        pins = pins or {name: packaged_pins()[name]["sha256"] for name in _FOM_ORDER}
        argv = [str(native_executable("SYNAPSE_HLA_PUBLISHER")), f"--endpoint={endpoint}",
                f"--federation-name={federation}", f"--fom-dir={fom_modules()[0].parent}"] + [
            f"--module-sha256={pins[name]}" for name in _FOM_ORDER] + [f"--scenario={scenario}"]
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENRTI_")}
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env, start_new_session=True)
        self.lines = EventLines(self.proc.stdout)

    def until(self, name: str, timeout: float = 30) -> dict:
        return self.lines.until(name, timeout)

    def time_of(self, event: dict) -> float:
        return self.lines.times[self.lines.events.index(event)]

    def end(self, timeout: float = 30) -> tuple[int, list[str]]:
        if not self.proc.stdin.closed:
            self.proc.stdin.close()
        self.lines.rest()
        code, err = self.proc.wait(timeout), self.proc.stderr.read()
        close_streams(self.proc)
        assert err == b"" and process_gone(self.proc.pid)
        return code, [e["event"] for e in self.lines.events]


_FOM_ORDER = ("RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml", "RPR-Base_v2.0.xml",
              "RPR-Physical_v2.0.xml", "RPR-Switches_v2.0.xml")


@pytest.mark.rti
@case("G-R38", "G-R39", "G-R11", paragraphs=("SPEC:207", "SPEC:211"))
def test_the_publisher_alone_keeps_its_barrier_bound_and_destroys_only_its_own_federation(
        tmp_path):
    """The publisher's own rules against a real rtinode, with no observer (R38, SPEC:207,
    SPEC:211): it reports the five pinned digests of the modules it used (R11) and that it created
    the federation, registered at GroundVehicle and waits at barrier 0; with nobody acknowledging,
    it fails that barrier no earlier than 5 seconds after it began waiting (barrier_timeout), then
    resigns, destroys the federation it created and disconnects, exit 1. A wrong line on the
    barrier pipe is a protocol failure, a closed pipe ends it the same way, and SIGTERM does too
    (stopped). A module whose bytes are not their pin is refused before any federation exists
    (module_pin). A federation name that already exists is never touched: create fails
    (FederationExecutionAlreadyExists), nothing is destroyed, and its owner can still destroy it."""
    node = Rtinode(tmp_path)
    holder = None
    try:
        publisher = Publisher(node.endpoint, "SC_DEMO_000000000000000a")
        modules = publisher.until("modules")
        assert modules["sha256"] == {name: packaged_pins()[name]["sha256"]
                                     for name in _FOM_ORDER}
        assert publisher.until("ready")["class"] == GV
        waiting = publisher.until("waiting")
        assert waiting == {"barrier": 0, "event": "waiting"}
        began = publisher.time_of(waiting)
        failure = publisher.until("failure", timeout=30)
        assert failure == {"event": "failure", "reason": "barrier_timeout", "stage": "barrier"}
        assert publisher.time_of(failure) - began >= 4.9
        code, events = publisher.end()
        assert code == 1 and events[-3:] == ["resigned", "destroyed", "disconnected"]

        for line, reason in ((b"7\n", "barrier_protocol"), (None, "barrier_closed"),
                             ("SIGTERM", "stopped")):
            publisher = Publisher(node.endpoint, "SC_DEMO_000000000000000b")
            publisher.until("waiting")
            if line == "SIGTERM":
                publisher.proc.send_signal(signal.SIGTERM)
            elif line is None:
                publisher.proc.stdin.close()
            else:
                publisher.proc.stdin.write(line)
                publisher.proc.stdin.flush()
            assert publisher.until("failure")["reason"] == reason
            code, events = publisher.end()
            assert code == 1 and events[-3:] == ["resigned", "destroyed", "disconnected"], events

        wrong = {name: packaged_pins()[name]["sha256"] for name in _FOM_ORDER}
        wrong["RPR-Physical_v2.0.xml"] = "0" * 64
        publisher = Publisher(node.endpoint, "SC_DEMO_000000000000000c", pins=wrong)
        assert publisher.until("failure") == {"event": "failure", "reason": "module_pin",
                                              "stage": "modules"}
        code, events = publisher.end()
        assert (code, events) == (1, ["failure"])

        holder = TestFederate(node.endpoint, "SC_DEMO_000000000000000d", "SC_TEST_HOLDER",
                              fom_modules())
        publisher = Publisher(node.endpoint, "SC_DEMO_000000000000000d")
        assert publisher.until("failure") == {
            "event": "failure", "reason": "FederationExecutionAlreadyExists", "stage": "create"}
        code, events = publisher.end()
        assert code == 1 and "destroyed" not in events and "created" not in events
        assert holder.finish() == ["created", "ready", "resigned", "destroyed", "disconnected"]
    finally:
        if holder is not None:
            holder.kill()
        node.stop()


@pytest.mark.rti
@case("G-R02", "G-R38")
def test_the_publisher_answers_version_and_refuses_any_other_argument_vector():
    """CR-L16: `--version` prints exactly the publisher's line and exits 0; any other vector
    (a token missing, out of order or malformed, a scenario that is neither main nor a bounded
    perf triple, a relative module directory) is exit 64 with the fixed usage line on stderr and
    nothing on stdout."""
    path = str(native_executable("SYNAPSE_HLA_PUBLISHER"))
    version = subprocess.run([path, "--version"], capture_output=True, timeout=30)
    assert (version.returncode, version.stdout, version.stderr) == (
        0, b'{"name":"sc-hla-publisher","profile":"SC-HLA-RPR2-OBS-1","version":"1.0.0"}\n', b"")
    good = ["--endpoint=rti://127.0.0.1:1", "--federation-name=SC_DEMO_000000000000000e",
            f"--fom-dir={fom_modules()[0].parent}"] + ["--module-sha256=" + "a" * 64] * 5 + [
        "--scenario=main"]
    bad = [good[:-1], good[1:] + good[:1], [good[0].replace("rti://", "http://")] + good[1:],
           good[:1] + ["--federation-name=SC DEMO"] + good[2:],
           good[:2] + ["--fom-dir=relative/dir"] + good[3:],
           good[:3] + ["--module-sha256=" + "A" * 64] + good[4:],
           good[:-1] + ["--scenario=perf:0:1:1"], good[:-1] + ["--scenario=perf:1:1"],
           good[:-1] + ["--scenario=perf:1:1001:1"], good[:-1] + ["--scenario=perf:01:1:1"],
           good[:-1] + ["--scenario=other"], ["--version", "--version"], []]
    for argv in bad:
        run = subprocess.run([path] + argv, capture_output=True, timeout=30)
        assert (run.returncode, run.stdout) == (64, b""), argv
        assert run.stderr.startswith(b"sc-hla-publisher: usage: ") and \
            run.stderr.count(b"\n") == 1, argv
