"""Security and separation (REQ060, REQ065, REQ081, REQ130-132; S01, S02)."""
import http.server
import socket
import ssl
import threading

import pytest

from helpers import CREDENTIAL, notice, report, uid
from synapse_link16_bridge.gateway.client import (GatewayClient, GatewayProtocolError,
                                                  SendOutcomeUnknown, TransportTimeout,
                                                  tls_context)

TABLES = ("meta", "lease", "raw_batch", "ingest", "session_seq", "identity", "observation",
          "sample", "current", "quarantine", "opaque", "outbox", "channel", "audit", "counter",
          "export_job", "allocation")
DUMP = {table: "SELECT * FROM " + table for table in TABLES}


def spy(h):
    calls = []
    adapter = h.bridge.ingestor.translator.adapter
    original = adapter.to_cdm
    adapter.to_cdm = lambda raw: calls.append(raw) or original(raw)
    return calls


@pytest.mark.parametrize("field, value", [("security_context", "ESCALATED-LABEL"),
                                          ("tenant", "another-tenant"),
                                          ("realm", "another-realm"),
                                          ("gateway_id", "another-gateway")])
def test_in_band_label_escalation_stops_the_channel_before_translation(h, field, value):
    calls = spy(h)
    h.publish(report(1))
    h.publish(report(2, track_number="T-2", **{field: value}))
    result = h.run()
    assert result == {"fetched": True, "reason": "SECURITY_CONTEXT_MISMATCH"}
    assert len(calls) == 1                         # the first record only; never the escalated one
    assert h.rows("SELECT COUNT(*) FROM ingest") == [(0,)]      # the whole batch rolled back
    assert h.provider.health_document("c1")["queue_depth"] == 2  # nothing acknowledged
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"]) == ("STOPPED", "SECURITY_CONTEXT_MISMATCH")
    audit = h.rows("SELECT kind, subject_id, code, raw_ref FROM audit")
    assert [a[:3] for a in audit] == [("channel_stop", uid(2), "SECURITY_CONTEXT_MISMATCH")]
    assert h.bridge.store.read_raw_evidence(audit[0][3]) is not None
    assert h.run() == {"fetched": False, "reason": "STOPPED"}
    assert h.bridge.health()["ready"] is False


def test_an_escalated_notice_stops_the_channel_too(h):
    h.publish_notice(notice(1, "DROP_SOURCE", security_context="ESCALATED-LABEL"))
    assert h.run()["reason"] == "SECURITY_CONTEXT_MISMATCH"


def test_replay_record_on_a_live_channel_is_refused_before_translation(make_harness):
    h = make_harness(synthetic=False, realm_kind="live", provider_kwargs={"synthetic": False})
    calls = spy(h)
    h.publish(report(1))                           # synthetic: true on a live channel
    assert h.run() == {"fetched": True, "reason": "SYNTHETIC_MISMATCH"}
    assert calls == []
    assert h.bridge.store.channel()["state"] == "STOPPED"


def test_a_live_record_on_a_synthetic_channel_is_refused(h):
    h.publish(report(1, synthetic=False))
    assert h.run()["reason"] == "SYNTHETIC_MISMATCH"


def test_a_replay_realm_ingests_and_never_exports(make_harness):
    h = make_harness(realm_kind="replay")
    h.publish(report(1))
    assert h.run()["dispositions"] == [(uid(1), "ACCEPTED", None)]
    from synapse_cdm.models import Entity
    from helpers import payload
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    assert h.bridge.export(entity, None, peer_id="peer-1")["reason"] == "POLICY_DENIED"


def test_no_credential_reaches_the_store_or_the_log(h, caplog):
    h.publish(report(1, message_family="J7.0"))
    h.publish(report(2, track_number="T-2", origin_scope="unapproved"))
    with caplog.at_level("DEBUG"):
        h.run()
        h.publish(report(3, security_context="ESCALATED-LABEL"))
        h.run()
    for table, query in DUMP.items():
        for row in h.bridge.store.query(query):
            for value in row:
                text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
                assert CREDENTIAL not in text, table
    assert CREDENTIAL not in caplog.text


def test_the_tls_context_verifies_and_requires_tls_1_2():
    context = tls_context()
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2


@pytest.mark.parametrize("url", ["http://10.0.0.1:1", "http://127.0.0.1.example.net",
                                 "ftp://127.0.0.1"])
def test_the_client_refuses_plain_http_off_loopback(url):
    with pytest.raises(ValueError):
        GatewayClient(url, "c", connect_timeout=1, request_deadline=2)


class _Odd(http.server.BaseHTTPRequestHandler):
    """Answers every GET with a redirect or with a body one octet over the client's bound."""

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"[" + b"0," * 600 + b"0]"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return None


class _JoiningServer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True


@pytest.fixture
def odd_server():
    server = _JoiningServer(("127.0.0.1", 0), _Odd)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()
    thread.join()


def test_the_client_never_follows_a_redirect_and_bounds_the_body(odd_server):
    redirecting = GatewayClient(f"http://127.0.0.1:{odd_server}/redirect", "c",
                                connect_timeout=2, request_deadline=5)
    with pytest.raises(GatewayProtocolError) as caught:
        redirecting.capabilities()
    assert caught.value.rule == "a redirect, which is never followed"
    bounded = GatewayClient(f"http://127.0.0.1:{odd_server}", "c", connect_timeout=2,
                            request_deadline=5, max_body_bytes=1024)
    with pytest.raises(GatewayProtocolError) as caught:
        bounded.capabilities()
    assert caught.value.rule == "a response above the body limit"


class _Dribble(http.server.BaseHTTPRequestHandler):
    """Answers in pieces a quarter of a second apart, for five seconds: the body (`/body`) or
    the status line and headers (`/headers`). Stops as soon as the client has gone."""

    protocol_version = "HTTP/1.1"
    PIECES, GAP = 20, 0.25

    def _dribble(self):
        stopped = self.server.stopped
        body = b"x" * self.PIECES
        head = [b"HTTP/1.1 200 OK\r\n", b"Content-Type: application/json\r\n"] + \
            [b"X-Slow-%d: y\r\n" % n for n in range(self.PIECES)] + \
            [b"Content-Length: %d\r\n" % len(body), b"\r\n"]
        try:
            if self.path.startswith("/headers"):
                for line in head:
                    self.wfile.write(line)
                    self.wfile.flush()
                    if stopped.wait(self.GAP):
                        return
                self.wfile.write(body)
                return
            self.wfile.write(b"".join(head))
            for n in range(self.PIECES):
                self.wfile.write(body[n:n + 1])
                self.wfile.flush()
                if stopped.wait(self.GAP):
                    return
        except OSError:
            return
        finally:
            self.close_connection = True

    def do_GET(self):  # noqa: N802
        self._dribble()

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._dribble()

    def log_message(self, *args):
        return None


@pytest.fixture
def dribbling_server():
    server = _JoiningServer(("127.0.0.1", 0), _Dribble)
    server.stopped = threading.Event()
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield server.server_address[1]
    server.stopped.set()
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("part", ["body", "headers"])
def test_the_request_deadline_bounds_the_whole_request(dribbling_server, part):
    """R4-F4 (fix round 1, 2026-10-11): REQ061's request deadline is one bound on the whole
    request, not a bound on each read. A gateway that answers one piece at a time, each well
    inside the deadline, five seconds in all, is cut off at a one-second deadline: a read is a
    `TransportTimeout`, a write `SendOutcomeUnknown`. Asserted as outcomes, never as times."""
    client = GatewayClient(f"http://127.0.0.1:{dribbling_server}/{part}", "c",
                           connect_timeout=1, request_deadline=1.0)
    with pytest.raises(TransportTimeout):
        client.capabilities()
    with pytest.raises(SendOutcomeUnknown):
        client.ack("consumer-1", "1.1")


@pytest.mark.parametrize("header_send, expected", [
    (0.9, [(1.0, 0.0), (0.1, 0.9)]),     # the body's send is given the 0.1 s left, not 1.0 s
    (1.0, [(1.0, 0.0)]),                 # the deadline passed in the header send: no body send
])
def test_the_request_deadline_bounds_every_send(monkeypatch, header_send, expected):
    """R4-F11 (fix round 2, 2026-10-11): `http.client` sends a POST's header block and its body
    in two sends; each is given only the time left before REQ061's deadline. A fake clock moves
    by `header_send` seconds during each send into a loopback listener that never accepts, so the
    sink is as slow as the test says; each send's socket timeout and the clock reading before it
    are recorded. The write ends `SendOutcomeUnknown` at the deadline."""
    now = [0.0]
    sends = []
    original = socket.socket.sendall

    def slow_sendall(self, data, *args):
        sends.append((round(self.gettimeout(), 6), round(now[0], 6)))
        result = original(self, data, *args)
        now[0] += header_send
        return result

    with socket.create_server(("127.0.0.1", 0), backlog=4) as sink:
        client = GatewayClient(f"http://127.0.0.1:{sink.getsockname()[1]}", "c",
                               connect_timeout=1, request_deadline=1.0,
                               monotonic=lambda: now[0])
        monkeypatch.setattr(socket.socket, "sendall", slow_sendall)
        with pytest.raises(SendOutcomeUnknown):
            client.transmit(b'{"report":"' + b"x" * 2000 + b'"}')
        monkeypatch.undo()
    assert sends == expected


@pytest.mark.parametrize("credential", [
    "SECRETMARKER7\n", "SECRETMARKER7\r\nX-Inject: 1", "SECRET MARKER7", "SECRETMARKER7\x00",
    "SECRETMARKER7\x7f", "SECRETMARKER7\t", "SECRETMARKER\u00e9", "SECRETMARKER\u2028", ""],
    ids=["LF", "CRLF-header", "space", "NUL", "DEL", "tab", "non-ascii", "line-separator",
         "empty"])
def test_a_credential_outside_visible_ascii_is_refused_when_the_client_is_built(credential):
    """HYGIENE-2 (A2F, 2026-10-11): a bearer credential is one or more visible ASCII characters
    (0x21 to 0x7E). Anything else is refused when the client is built, as a configuration error
    that names the reference and never the value (a CR or LF had reached `putheader`, whose
    exception quoted the whole header)."""
    from synapse_link16_bridge.config import ConfigError
    with pytest.raises(ConfigError) as caught:
        GatewayClient("http://127.0.0.1:9", credential, connect_timeout=1, request_deadline=2)
    assert (caught.value.key, str(caught.value)) == (
        "credential_ref", "CONFIG_INVALID: credential_ref — the credential it names must be "
                          "visible ASCII, without space or control characters")
    assert "SECRET" not in repr(caught.value.args)


@pytest.mark.parametrize("credential", [
    CREDENTIAL, "a", "".join(chr(c) for c in range(0x21, 0x7F))],
    ids=["harness", "one-character", "every-visible-character"])
def test_a_visible_ascii_credential_builds_the_client(credential):
    client = GatewayClient("http://127.0.0.1:9", credential, connect_timeout=1, request_deadline=2)
    assert client._authorization == "Bearer " + credential


@pytest.mark.parametrize("url, kind", [("http://127.0.0.1:9", "_HTTPConnection"),
                                       ("https://gateway.example:8443", "_HTTPSConnection")])
def test_both_connection_classes_are_built_with_the_connect_timeout(url, kind):
    """HYGIENE-5 (A2F, 2026-10-11): the plain and the TLS connection are each built with the
    timeout `_exchange` gives (a connection built without one waits on the system default)."""
    from synapse_link16_bridge.gateway import client as client_module
    client = GatewayClient(url, CREDENTIAL, connect_timeout=2, request_deadline=5)
    connection = client._connection(1.25, 100.0)
    try:
        assert type(connection) is getattr(client_module, kind)
        assert (connection.timeout, connection.deadline) == (1.25, 100.0)
        if kind == "_HTTPSConnection":
            assert connection._context is client._tls
    finally:
        connection.close()


@pytest.mark.parametrize("connect, deadline, expected", [(2, 5, 2), (5, 3, 3), (4, 4, 4)])
def test_the_exchange_connects_with_the_smaller_of_connect_timeout_and_deadline(
        monkeypatch, connect, deadline, expected):
    client = GatewayClient("http://127.0.0.1:9", CREDENTIAL, connect_timeout=connect,
                           request_deadline=deadline)
    seen = []
    real = client._connection
    monkeypatch.setattr(client, "_connection",
                        lambda timeout, end: seen.append(timeout) or real(timeout, end))
    from synapse_link16_bridge.gateway.client import TransportError
    with pytest.raises(TransportError):             # nothing listens on port 9
        client.health()
    assert seen == [expected]
