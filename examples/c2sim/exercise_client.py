#!/usr/bin/env python3
"""The opt-in C2SIM exercise client: initialisation, one order, report retrieval and replay against
the pinned OpenC2SIM reference server, with an `independent_endpoint` exercise report written
through the repository's own evidence mechanism.

    export C2SIM_SERVER_URL=http://c2sim-host:8080      # the reference server's Tomcat
    export C2SIM_SERVER_PASSWORD=...                     # the server's command password
    python examples/c2sim/exercise_client.py [--out evidence] [--submitter NAME]
                                             [--stomp-host HOST] [--stomp-port 61613]
                                             [--timeout 30]

Without `C2SIM_SERVER_URL` the client runs nothing, prints the reproduction procedure and exits
with status 2: BLOCKED_EXTERNAL_EVIDENCE is the honest reading, never a pass. This file is the
ONLY place in the repository that opens a socket to a C2SIM server; the adapter
(`synapse_cdm.adapters.c2sim`) holds no session state, no protocol sequencing and no exercise
clock — all three live here, as master prompt §5 and §6 require.

THE PEER, AND THE PROTOCOL AS IT DOCUMENTS IT
---------------------------------------------
OpenC2SIM C2SIM Reference Implementation Server 4.8.3.1 (`C2SIMServer##4.8.3.1.war`, SHA-256
`7cbd6809…`, documentation revised 3 July 2022 — both recorded in the normative directory's
`xsd_pin.json`, decision "reference implementation pairing"). The documentation gives:

* REST submission — `POST http://host:8080/C2SIMServer/c2sim` with query parameters
  `submitterID`, `protocol` (`C2SIM`), and for C2SIM `sender`, `receiver`,
  `communicativeActTypeCode`, `conversationID`, plus `version` (the client software version,
  `4.8.3.1`); the body is the XML document; the response is an XML `<result>` with `<status>`,
  `<message>`, `<serverInitialized>`, `<sessionState>`, `<unitDatabaseSize>` …
* session commands — `http://host:8080/C2SIMServer/command` with `command`, `parm1`, `parm2`,
  `submitter`, `version`: `STATUS` (any state), `RESET` (password; back to UNINITIALIZED),
  `SHARE` (password; publishes the accumulated C2SIMInitializationBody to every subscriber and
  sets INITIALIZED), `START` (password; RUNNING), `STOP` (password; back to INITIALIZED),
  `QUERYINIT` (INITIALIZED or RUNNING; returns the initialisation data, with updated positions
  when the server is configured to track them, in the REST response);
* the state machine — UNINITIALIZED → (an initialisation document) INITIALIZING → SHARE →
  INITIALIZED → START → RUNNING; position and status reports are accepted while RUNNING and
  update the unit database; orders are accepted while RUNNING;
* STOMP 1.2 distribution — Apache Apollo on port 61613, topic `/topic/C2SIM`, every published
  message carrying headers `protocol`, `submitter`, `message-selector` (`C2SIM_Initialization`,
  `C2SIM_Order`, `C2SIM_Report`, `C2SIM_Command`) and `message-type`.

WHAT THE EXERCISE VALIDATES, AND WHAT IT DOES NOT
-------------------------------------------------
Each step's verdict is a digest comparison the evidence runner performs — never a boolean this
script types — over two files it writes: EXPECTED (what this side sent, projected to the fields
the peer is expected to preserve) and OBSERVED (the same projection of what the peer published or
returned, read through the adapter). A peer that re-serialises the message in another element
order or namespace prefix still AGREES; a peer that drops a unit, moves a position or renames a
task DIFFERS.

1. `egress initialisation` — the server accepts the initialisation (`<status>OK`), and after
   SHARE publishes a C2SIMInitializationBody on STOMP whose projection (every UUID, class,
   name, side, superior, subordinates, position) equals what was sent. The server is a
   MARSHALLING server: it re-emits the aggregate, so an identity or relationship it lost would
   be visible here.
2. `egress order` — the move order is accepted and republished with the same order id, task
   id, action code, performing entity and destination.
3. `egress reports` — the two position reports are accepted while RUNNING.
4. `ingress query` — QUERYINIT returns an initialisation the adapter ingests; its projection
   carries the REPORTED positions of the two subjects in place of the initial ones, which is
   the server's unit-status tracking interpreting the report's SubjectEntity and Location — a
   semantic reading by an independent implementation, not an echo. If the server is configured
   not to track positions, this step reads DIFFER and the limitation says why.
5. `ingress replay` — the same two reports re-sent and QUERYINIT read again produce the same
   projection: the exchange is deterministic.

The server does not validate against the XSD (`server.justParseDocument` is a structural
parse); the normative half of the claim is the test suite's validator. The server documentation
says version 4.8.3.1 accepts protocol versions 0.0.9 and 1.0.0 — whether it accepts the
standard's `1.0.0` on this document is what step 1 reads.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import socket
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from synapse_cdm import evidence, times
from synapse_cdm.adapter import packaged_fixtures
from synapse_cdm.adapters import c2sim_codec as codec
from synapse_cdm.adapters.c2sim import C2simAdapter, ExerciseClock
from synapse_cdm.models import Entity, Event, PlanObject

PEER_IMPLEMENTATION = "OpenC2SIM C2SIM Reference Implementation Server"
PEER_VERSION = "4.8.3.1"
CLIENT_VERSION = "4.8.3.1"          # the `version` REST parameter: the client software version the server documents
EDITION = ("SISO-STD-019-2020 v1.0 (Core + SMX) with SISO-STD-020-2020 (LOX); XML schema "
           "C2SIMArtifacts v1.0.1; namespace http://www.sisostds.org/schemas/C2SIM/1.1")
STOMP_TOPIC = "/topic/C2SIM"
INITIALISATION = "initialisation_three_sides.xml"
ORDER = "order_move_to_location.xml"
REPORTS = "report_position_two_subjects.xml"
BLUE = "c2510000-0001-8000-8000-000000000001"
BLOCKED = "BLOCKED_EXTERNAL_EVIDENCE"

PROCEDURE = """\
independent_endpoint: {status} — C2SIM_SERVER_URL is not set, so no exchange ran and nothing is claimed.

Reproduction procedure (the peer is the pinned OpenC2SIM reference server 4.8.3.1):
  1. Obtain C2SIMServer##4.8.3.1.war (SHA-256 7cbd6809d6a4d26440793f9c172a249e8187d52fae78e6b2acf1a010326fbf83)
     and its documentation from https://openc2sim.github.io/ ; deploy the war on Apache Tomcat with
     Apache Apollo 1.7.1 (STOMP, port 61613) as the documentation's installation chapter describes,
     with `server.c2sim_password` set in C2SIMServer.properties (Appendix B).
  2. export C2SIM_SERVER_URL=http://<host>:8080 ; export C2SIM_SERVER_PASSWORD=<that password>
     (optional: C2SIM_STOMP_HOST, C2SIM_STOMP_PORT, --submitter, --timeout)
  3. python examples/c2sim/exercise_client.py --out evidence
     The client resets the session, submits the packaged initialisation, SHAREs, STARTs, submits
     the packaged MoveToLocation order and the two position reports, reads QUERYINIT, replays the
     reports, STOPs, and writes evidence/c2sim/1.0.0/exercises/<slug>.json through
     `synapse_cdm.evidence.exercise` with one result per step (digests of the projections it
     wrote beside the report) — a verdict of AGREE or DIFFER per direction, computed by the runner.
  4. python -m synapse_cdm.evidence generate --adapter c2sim --exercises evidence/c2sim/1.0.0/exercises
     reads the report into the evidence record's independent_endpoint category.
What it validates: acceptance of the standard's Protocol/ProtocolVersion strings, the marshalling
server's re-emission of every identity and relationship, the order's ids and task form, and the
server's interpretation of the reports' SubjectEntity/Location through QUERYINIT's updated
positions. What it does not: XSD validity (the test suite's validator does that, offline).
"""


# ------------------------------------------------------------------------ the REST surface


def submit_url(base: str, submitter: str, header: codec.Header) -> str:
    """`/C2SIMServer/c2sim` with the parameters the documentation lists for a C2SIM document."""
    query = urllib.parse.urlencode({
        "submitterID": submitter, "protocol": "C2SIM", "sender": header.from_sending_system,
        "receiver": header.to_receiving_system, "communicativeActTypeCode": header.communicative_act,
        "conversationID": header.conversation_id, "version": CLIENT_VERSION})
    return f"{base.rstrip('/')}/C2SIMServer/c2sim?{query}"


def command_url(base: str, submitter: str, command: str, parm1: str = "", parm2: str = "") -> str:
    query = urllib.parse.urlencode({"command": command, "parm1": parm1, "parm2": parm2,
                                    "submitter": submitter, "version": CLIENT_VERSION})
    return f"{base.rstrip('/')}/C2SIMServer/command?{query}"


def parse_result(text: str) -> dict[str, str]:
    """The `<result>` document the server answers with, as a flat dict; anything else is kept
    whole under `raw` so a refusal is readable."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {"raw": text[:2000]}
    if root.tag.split("}")[-1] != "result":
        return {"raw": text[:2000], "root": root.tag}
    return {child.tag.split("}")[-1]: (child.text or "").strip() for child in root}


class Rest:
    def __init__(self, base: str, submitter: str, password: str, timeout: float) -> None:
        self.base, self.submitter, self.password, self.timeout = base, submitter, password, timeout
        self.log: list[dict] = []

    def _call(self, url: str, body: bytes | None) -> str:
        request = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
        if body is not None:
            request.add_header("Content-Type", "application/xml; charset=utf-8")
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - the operator's URL
            text = response.read().decode("utf-8", errors="replace")
        self.log.append({"url": url, "bytes_sent": len(body or b""), "seconds": round(time.monotonic() - started, 3),
                         "response": text[:500]})
        return text

    def command(self, command: str, with_password: bool = True) -> dict[str, str]:
        url = command_url(self.base, self.submitter, command, self.password if with_password else "")
        return parse_result(self._call(url, None))

    def submit(self, document: bytes, header: codec.Header) -> dict[str, str]:
        return parse_result(self._call(submit_url(self.base, self.submitter, header), document))

    def query_init(self) -> str:
        """QUERYINIT's response is the initialisation document itself, not a `<result>`."""
        return self._call(command_url(self.base, self.submitter, "QUERYINIT", self.password), None)


# ----------------------------------------------------------------------- STOMP 1.2 (minimal)


def stomp_frame(command: str, headers: dict[str, str], body: bytes = b"") -> bytes:
    lines = [command.encode()] + [f"{k}:{v}".encode() for k, v in headers.items()]
    return b"\n".join(lines) + b"\n\n" + body + b"\x00"


def parse_frames(buffer: bytes) -> tuple[list[tuple[str, dict[str, str], bytes]], bytes]:
    """Every complete frame in `buffer` (command, headers, body) and the unread remainder.
    Heart-beat newlines between frames are skipped; a `content-length` header is honoured."""
    frames = []
    while True:
        buffer = buffer.lstrip(b"\r\n")
        if not buffer:
            break
        head_end = buffer.find(b"\n\n")
        if head_end == -1:
            break
        head = buffer[:head_end].decode("utf-8", errors="replace").replace("\r", "")
        command, *header_lines = head.split("\n")
        headers = {}
        for line in header_lines:
            key, _, value = line.partition(":")
            headers.setdefault(key, value)
        body_start = head_end + 2
        if "content-length" in headers:
            length = int(headers["content-length"])
            if len(buffer) < body_start + length + 1:
                break
            body = buffer[body_start:body_start + length]
            buffer = buffer[body_start + length + 1:]
        else:
            terminator = buffer.find(b"\x00", body_start)
            if terminator == -1:
                break
            body = buffer[body_start:terminator]
            buffer = buffer[terminator + 1:]
        frames.append((command, headers, body))
    return frames, buffer


class Stomp:
    """One subscription to the C2SIM topic; messages are collected as they arrive."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buffer = b""
        self.messages: list[tuple[dict[str, str], bytes]] = []
        self.sock.sendall(stomp_frame("CONNECT", {"accept-version": "1.2", "host": host, "heart-beat": "0,0"}))
        connected = self._wait(lambda frames: any(c == "CONNECTED" for c, _, _ in frames), timeout)
        if not connected:
            raise RuntimeError("STOMP: no CONNECTED frame")
        self.sock.sendall(stomp_frame("SUBSCRIBE", {"id": "c2sim-exercise", "destination": STOMP_TOPIC, "ack": "auto"}))

    def _wait(self, done, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.1, deadline - time.monotonic()))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                chunk = b""
            if chunk:
                self.buffer += chunk
            frames, self.buffer = parse_frames(self.buffer)
            for command, headers, body in frames:
                if command == "MESSAGE":
                    self.messages.append((headers, body))
                if command == "ERROR":
                    raise RuntimeError(f"STOMP ERROR frame: {headers} {body[:200]!r}")
            if done(frames):
                return True
            if not chunk:
                continue
        return False

    def collect(self, selector: str, count: int, timeout: float) -> list[bytes]:
        """Wait for `count` messages whose `message-selector` header is `selector`."""
        seen = len([m for m in self.messages if m[0].get("message-selector") == selector])
        self._wait(lambda frames: len([m for m in self.messages if m[0].get("message-selector") == selector])
                   >= seen + count, timeout)
        matching = [body for headers, body in self.messages if headers.get("message-selector") == selector]
        return matching[seen:seen + count]

    def close(self) -> None:
        try:
            self.sock.sendall(stomp_frame("DISCONNECT", {}))
        finally:
            self.sock.close()


# ------------------------------------------------------------------------- the projections


def initialisation_projection(objects: list) -> dict:
    """The fields the peer is expected to preserve, keyed by UUID: class, name, side, superior,
    subordinates, position. Order-free, prefix-free, whitespace-free."""
    out: dict = {}
    for obj in objects:
        if isinstance(obj, Entity):
            block = codec.ObjectBlock.model_validate(obj.attributes["c2sim"])
            org = block.organisation or codec.Organisation()
            out[block.uuid] = {
                "class": block.object_class, "name": block.name, "names": block.names, "side": org.side,
                "superior": org.superior, "subordinates": sorted(org.subordinates),
                "position": None if obj.position is None else [obj.position.lat, obj.position.lon]}
        elif isinstance(obj, PlanObject):
            block = codec.ObjectBlock.model_validate(obj.route.metadata["c2sim"])
            out[block.uuid] = {"class": "Route", "name": obj.label,
                               "points": [[w.position.lat, w.position.lon] for w in obj.route.waypoints]}
    return out


def order_projection(objects: list) -> dict:
    event = next(o for o in objects if isinstance(o, Event))
    order = codec.OrderPayload.model_validate(event.payload["c2sim"])
    return {"order_id": order.order_id, "from": order.from_sender, "to": order.to_receiver,
            "tasks": [{"uuid": t.uuid, "action": t.action_code, "performing": t.performing_entity,
                       "destination": [[loc.latitude, loc.longitude] for loc in t.locations],
                       "map_graphics": t.map_graphic_ids} for t in order.tasks]}


def reported_positions(report_objects: list) -> dict[str, list[float]]:
    out = {}
    for event in report_objects:
        payload = codec.ReportPayload.model_validate(event.payload["c2sim"])
        if payload.subject_entity and payload.location and payload.location.form == "GeodeticCoordinate":
            out[payload.subject_entity] = [payload.location.latitude, payload.location.longitude]
    return out


def render(projection) -> bytes:
    return (json.dumps(projection, sort_keys=True, indent=2) + "\n").encode("utf-8")


# ----------------------------------------------------------------------------- the exercise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("evidence"))
    parser.add_argument("--submitter", default="synapsecommand-exercise")
    parser.add_argument("--stomp-host", default=os.environ.get("C2SIM_STOMP_HOST"))
    parser.add_argument("--stomp-port", type=int, default=int(os.environ.get("C2SIM_STOMP_PORT", "61613")))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--work", type=pathlib.Path, default=None,
                        help="where the expected/observed projections are written (default: beside the report)")
    args = parser.parse_args(argv)

    base = os.environ.get("C2SIM_SERVER_URL")
    if not base:
        print(PROCEDURE.format(status=BLOCKED))
        return 2
    password = os.environ.get("C2SIM_SERVER_PASSWORD")
    if not password:
        print(f"{BLOCKED}: C2SIM_SERVER_PASSWORD is not set; the server's RESET/SHARE/START/STOP commands "
              "need it (C2SIMServer.properties, server.c2sim_password)")
        return 2
    stomp_host = args.stomp_host or urllib.parse.urlparse(base).hostname
    fixtures = packaged_fixtures(C2simAdapter)
    started = _dt.datetime.now(_dt.timezone.utc)
    slug = "openc2sim-server-4-8-3-1-" + started.strftime("%Y%m%dT%H%M%SZ")
    work = args.work or (args.out / "c2sim" / C2simAdapter.version / "exercises" / slug)
    work.mkdir(parents=True, exist_ok=True)

    # -- the exercise-side state: own side, epoch, roster — this client's, never the adapter's
    plain = C2simAdapter(own_side=BLUE)
    init_bytes = (fixtures / INITIALISATION).read_bytes()
    initial = plain.to_cdm(init_bytes)
    scenario = codec.ObjectBlock.model_validate(initial[3].attributes["c2sim"]).scenario
    clock = ExerciseClock(epoch=codec.parse_iso_date_time(scenario.date_time.iso_date_time, "ScenarioSetting"),
                          basis=f"ScenarioSetting/DateTime of the initialisation submitted by this client ({INITIALISATION})")
    adapter = C2simAdapter(own_side=BLUE, exercise=clock)
    headers = {name: codec.read_header(codec.twin_of(ET.fromstring((fixtures / name).read_bytes()))["Message"]["C2SIMHeader"])
               for name in (INITIALISATION, ORDER, REPORTS)}

    rest = Rest(base, args.submitter, password, args.timeout)
    limitations: list[str] = []
    results: list[dict] = []
    stomp = None
    try:
        stomp = Stomp(stomp_host, args.stomp_port, args.timeout)
        status = rest.command("STATUS", with_password=False)
        state = status.get("sessionState", "?")
        print(f"server {status.get('serverVersion', '?')} state {state}")
        if state == "RUNNING":
            rest.command("STOP")
        if state != "UNINITIALIZED":
            rest.command("RESET")

        # 1. initialisation: submit, SHARE, read what the server publishes
        accepted = rest.submit(init_bytes, headers[INITIALISATION])
        print("initialisation:", accepted.get("status"), accepted.get("message"))
        shared = rest.command("SHARE")
        print("SHARE:", shared.get("status"), shared.get("sessionState"))
        published = stomp.collect("C2SIM_Initialization", 1, args.timeout)
        expected = render(initialisation_projection(initial))
        observed = render(initialisation_projection(adapter.to_cdm(published[0]))) if published else \
            render({"error": "no C2SIM_Initialization message on STOMP within the timeout", "accepted": accepted})
        results.append(_result(work, "egress", "initialisation", expected, observed,
                               f"submit {INITIALISATION} then SHARE; projection of the C2SIMInitializationBody the "
                               f"server published on {STOMP_TOPIC}; server answered status={accepted.get('status')} "
                               f"message={accepted.get('message')}"))

        # 2. START, then the order
        started_state = rest.command("START")
        print("START:", started_state.get("status"), started_state.get("sessionState"))
        order_bytes = (fixtures / ORDER).read_bytes()
        accepted = rest.submit(order_bytes, headers[ORDER])
        published = stomp.collect("C2SIM_Order", 1, args.timeout)
        expected = render(order_projection(adapter.to_cdm(order_bytes)))
        observed = render(order_projection(adapter.to_cdm(published[0]))) if published else \
            render({"error": "no C2SIM_Order message on STOMP within the timeout", "accepted": accepted})
        results.append(_result(work, "egress", "order", expected, observed,
                               f"submit {ORDER} while RUNNING; projection of the OrderBody the server republished; "
                               f"server answered status={accepted.get('status')}"))

        # 3. the reports, 4. QUERYINIT, 5. replay
        report_bytes = (fixtures / REPORTS).read_bytes()
        accepted = rest.submit(report_bytes, headers[REPORTS])
        results.append(_result(work, "egress", "reports", render({"status": "OK"}),
                               render({"status": accepted.get("status", accepted.get("raw", "?"))}),
                               f"submit {REPORTS} while RUNNING; the server's <status> against OK"))
        reported = reported_positions(adapter.to_cdm(report_bytes))
        queried = rest.query_init()
        expected_projection = initialisation_projection(initial)
        for uuid, position in reported.items():
            if uuid in expected_projection:
                expected_projection[uuid]["position"] = position
        try:
            observed_projection = initialisation_projection(adapter.to_cdm(_c2sim_document(queried)))
        except Exception as e:                            # noqa: BLE001 - recorded as the observation
            observed_projection = {"error": f"{type(e).__name__}: {e}", "response": queried[:1000]}
        results.append(_result(work, "ingress", "query", render(expected_projection), render(observed_projection),
                               "QUERYINIT after the reports; projection of the returned initialisation, expected "
                               "to carry the REPORTED positions of the two subjects (server unit-status tracking)"))
        rest.submit(report_bytes, headers[REPORTS])
        replayed = rest.query_init()
        try:
            replay_projection = initialisation_projection(adapter.to_cdm(_c2sim_document(replayed)))
        except Exception as e:                            # noqa: BLE001
            replay_projection = {"error": f"{type(e).__name__}: {e}", "response": replayed[:1000]}
        results.append(_result(work, "ingress", "replay", render(observed_projection), render(replay_projection),
                               "the same reports re-submitted and QUERYINIT read again: the projection is unchanged"))
        rest.command("STOP")
    except Exception as e:                                # noqa: BLE001 - the exchange's own failure IS the record
        limitations.append(f"the exchange stopped at step {len(results) + 1}: {type(e).__name__}: {e}")
        print(f"exchange stopped: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        if stomp is not None:
            stomp.close()
    (work / "rest.log.json").write_text(json.dumps(rest.log, indent=2) + "\n")
    if not results:
        print(f"{BLOCKED}: no step completed; see {work}/rest.log.json")
        return 1

    spec = {
        "category": "independent_endpoint",
        "peer": {"implementation": PEER_IMPLEMENTATION, "version": PEER_VERSION},
        "edition": EDITION,
        "profile": "C2SIMInitializationBody / OrderBody (MoveToLocation) / ReportBody (PositionReportContent)",
        "inputs": [{"path": str(fixtures / name), "provenance": "synthetic fixture shipped in synapse_cdm (fixtures/c2sim/PROVENANCE.json)",
                    "authorised_by": "the repository's own fixture provenance record"}
                   for name in (INITIALISATION, ORDER, REPORTS)],
        "directions": sorted({r["direction"] for r in results}),
        "results": results,
        "limitations": limitations + [
            "the server does not validate against the XSD (structural parse only); normative validity of the "
            "submitted documents is the test suite's validator's reading, taken offline",
            "the `ingress query` step reads DIFFER when the server is configured not to track unit positions "
            "(c2simServer.properties); that is a server configuration reading, not a translation defect",
            f"server version, session states and every REST response are in rest.log.json beside this report; "
            f"STOMP host {stomp_host}:{args.stomp_port}, topic {STOMP_TOPIC}",
        ],
        "environment": {"C2SIM_SERVER_URL": base, "submitter": args.submitter,
                        "started_at": times.render(started)},
    }
    spec_path = work / "exercise.spec.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")
    report = evidence.exercise("c2sim", spec, base=spec_path.parent)
    written = evidence.write_exercise(report, args.out, slug)
    agreed = sum(1 for r in report.results if r.verdict == evidence.AGREE)
    print(f"wrote {written}: {agreed} of {len(report.results)} step(s) AGREE; "
          f"projections and rest.log.json under {work}")
    return 0 if agreed == len(report.results) else 1


def _result(work: pathlib.Path, direction: str, step: str, expected: bytes, observed: bytes, command: str) -> dict:
    (work / f"{step}.expected.json").write_bytes(expected)
    (work / f"{step}.observed.json").write_bytes(observed)
    return {"direction": direction, "command": command, "expected": f"{step}.expected.json",
            "observed": f"{step}.observed.json", "note": step}


def _c2sim_document(response: str) -> bytes:
    """QUERYINIT answers with the initialisation document; some deployments wrap it. The C2SIM
    `<Message>` element is what the adapter reads."""
    start = response.find("<Message")
    end = response.rfind("</Message>")
    if start == -1 or end == -1:
        raise ValueError("QUERYINIT's response carries no <Message> element")
    return response[start:end + len("</Message>")].encode("utf-8")


if __name__ == "__main__":
    sys.exit(main())
