"""The synthetic gateway's API (REQ051, REQ060-063, REQ095 provider side, REQ096, REQ097, E04)
over its loopback server, with raw HTTP where the client would hide the case."""
import http.client
import json

import pytest

from helpers import CHANNEL, CONSUMER, CREDENTIAL, OTHER_CREDENTIAL, report, uid
from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.gateway.client import CursorExpired, GatewayError
from synapse_link16_bridge.gateway.provider import UINT64_MAX

ERROR_KEYS = ["code", "correlation_id", "message", "retryable"]


def call(h, method, path, body=None, *, credential=CREDENTIAL, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", h.server.port, timeout=5)
    try:
        sent = {} if credential is None else {"Authorization": "Bearer " + credential}
        sent.update(headers or {})
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        data = response.read()
        return response.status, json.loads(data) if data else None
    finally:
        connection.close()


def transmission(n, body_report, *, expires="2026-10-04T12:00:10.000Z", peer="peer-1"):
    return jsonstrict.canonical({"request_id": uid(n), "peer_id": peer, "expires_at": expires,
                                 "policy_revision": "policy-1", "report": body_report})


def test_capabilities_carry_the_required_replay_window(h):
    status, document = call(h, "GET", "/v1/capabilities")
    assert status == 200
    assert document == {"profile": "sc-link16-gateway/1.0.0", "gateway_id": "synthetic-gateway-1",
                        "native_profiles": ["SYNTHETIC-NO-NATIVE-CODEC"],
                        "receive_families": ["J3.2", "J3.3", "J3.4", "J3.5"],
                        "transmit_families": ["J3.2", "J3.3", "J3.4", "J3.5"],
                        "max_batch": 1000, "replay_window_seconds": 86400}


@pytest.mark.parametrize("method, path", [
    ("GET", "/v1/other"), ("GET", "/v1/ack"), ("POST", "/v1/reports"), ("PUT", "/v1/ack"),
    ("DELETE", "/v1/transmissions"), ("GET", "/v1/transmissions/not-a-uuid"), ("GET", "/"),
    ("GET", "/v1/capabilities/"),
])
def test_anything_but_the_six_endpoints_is_404_in_the_error_form(h, method, path):
    status, document = call(h, method, path, body=b"{}" if method in ("POST", "PUT") else None,
                            headers={"Content-Length": "2"} if method in ("POST", "PUT") else None)
    assert status == 404
    assert sorted(document) == ERROR_KEYS
    assert (document["code"], document["message"], document["retryable"]) == (
        "NOT_FOUND", "No such resource.", False)


def test_missing_credential_is_401_and_wrong_consumer_is_403(h):
    assert call(h, "GET", "/v1/capabilities", credential=None)[1]["code"] == "UNAUTHENTICATED"
    status, document = call(h, "GET", "/v1/reports", credential="synthetic-bearer-" + "z" * 16)
    assert (status, document["code"], document["retryable"]) == (401, "UNAUTHENTICATED", False)
    status, document = call(h, "GET", "/v1/health", headers={"Authorization": "Basic x"},
                            credential=None)
    assert status == 401
    body = jsonstrict.canonical({"consumer_id": "consumer-2", "cursor": "1.0"})
    status, document = call(h, "POST", "/v1/ack", body, headers={"Content-Length": str(len(body))})
    assert (status, document["code"]) == (403, "FORBIDDEN")


def test_reports_serve_only_the_authenticated_channel(h):
    h.publish(report(1))
    h.provider.publish("c2", "report", report(2, track_number="OTHER-CHANNEL"))
    _, mine = call(h, "GET", "/v1/reports")
    _, theirs = call(h, "GET", "/v1/reports", credential=OTHER_CREDENTIAL)
    assert [r["body"]["record_id"] for r in mine["records"]] == [uid(1)]
    assert [r["body"]["record_id"] for r in theirs["records"]] == [uid(2)]


def test_body_over_8_mib_is_413_before_reading(h):
    connection = http.client.HTTPConnection("127.0.0.1", h.server.port, timeout=5)
    try:
        connection.putrequest("POST", "/v1/transmissions")
        connection.putheader("Authorization", "Bearer " + CREDENTIAL)
        connection.putheader("Content-Length", str(8 * 1024 * 1024 + 1))
        connection.endheaders()                      # not one octet of the body is sent
        response = connection.getresponse()
        document = json.loads(response.read())
    finally:
        connection.close()
    assert (response.status, document["code"]) == (413, "LIMIT_EXCEEDED")


@pytest.mark.parametrize("headers, code", [({}, "SCHEMA_INVALID"),
                                           ({"Content-Length": "abc"}, "SCHEMA_INVALID"),
                                           ({"Content-Length": "012"}, "SCHEMA_INVALID")])
def test_a_post_needs_a_plain_content_length(h, headers, code):
    connection = http.client.HTTPConnection("127.0.0.1", h.server.port, timeout=5)
    try:
        connection.putrequest("POST", "/v1/ack", skip_accept_encoding=True)
        connection.putheader("Authorization", "Bearer " + CREDENTIAL)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.endheaders()
        response = connection.getresponse()
        document = json.loads(response.read())
    finally:
        connection.close()
    assert (response.status, document["code"]) == (400, code)


@pytest.mark.parametrize("query", ["?limit=0", "?limit=1001", "?limit=abc", "?limit=01",
                                   "?limit=5&limit=6", "?other=1", "?after=", "?limit"])
def test_limit_bounds_and_unknown_parameters_are_400(h, query):
    status, document = call(h, "GET", "/v1/reports" + query)
    assert (status, document["code"], document["retryable"]) == (400, "SCHEMA_INVALID", False)


def test_limit_default_is_100_and_the_bounds_are_inclusive(h):
    for n in range(150):
        h.publish(report(n + 1, track_number=f"T-{n}"))
    _, first = call(h, "GET", "/v1/reports")
    assert (len(first["records"]), first["next_cursor"], first["has_more"]) == (100, "1.100", True)
    _, one = call(h, "GET", "/v1/reports?limit=1")
    assert len(one["records"]) == 1
    _, rest = call(h, "GET", "/v1/reports?after=1.100&limit=1000")
    assert (len(rest["records"]), rest["next_cursor"], rest["has_more"]) == (50, "1.150", False)


def test_after_returns_records_strictly_after_the_cursor(h):
    for n in (1, 2, 3):
        h.publish(report(n, track_number=f"T-{n}"))
    _, batch = call(h, "GET", "/v1/reports?after=1.1")
    assert [r["body"]["record_id"] for r in batch["records"]] == [uid(2), uid(3)]
    _, empty = call(h, "GET", "/v1/reports?after=1.3")
    assert (empty["records"], empty["next_cursor"], empty["has_more"]) == ([], "1.3", False)


@pytest.mark.parametrize("cursor, code", [("2.1", "CURSOR_FOREIGN"), ("x", "CURSOR_FOREIGN"),
                                          ("1.9", "CURSOR_FUTURE")])
def test_foreign_and_future_cursors_are_422(h, cursor, code):
    h.publish(report(1))
    status, document = call(h, "GET", "/v1/reports?after=" + cursor)
    assert (status, document["code"], document["retryable"]) == (422, code, False)


def test_acks_are_idempotent_and_refuse_a_future_cursor(h):
    for n in (1, 2):
        h.publish(report(n, track_number=f"T-{n}"))
    call(h, "GET", "/v1/reports")
    for cursor in ("1.2", "1.2", "1.1"):
        body = jsonstrict.canonical({"consumer_id": CONSUMER, "cursor": cursor})
        status, document = call(h, "POST", "/v1/ack", body,
                                headers={"Content-Length": str(len(body))})
        assert (status, document) == (200, {"consumer_id": CONSUMER, "cursor": cursor})
    body = jsonstrict.canonical({"consumer_id": CONSUMER, "cursor": "1.3"})
    status, document = call(h, "POST", "/v1/ack", body, headers={"Content-Length": str(len(body))})
    assert (status, document["code"]) == (422, "CURSOR_FUTURE")


def test_unacked_retention_is_24_hours_on_the_injected_clock(h):
    h.publish(report(1))
    h.clock.advance(24 * 3600 - 0.001)
    h.publish(report(2, track_number="T-2"))
    assert h.provider.losses() == []
    h.clock.advance(0.001)
    status, document = call(h, "GET", "/v1/reports?after=1.0")
    assert (status, document["code"], document["earliest_cursor"], document["retryable"]) == (
        410, "CURSOR_EXPIRED", "1.1", False)
    assert h.provider.losses() == [{"channel": CHANNEL, "from_position": 1, "to_position": 1,
                                    "count": 1, "bytes": len(jsonstrict.canonical(
                                        dict(report(1), session_id=h.provider.session(CHANNEL)[0],
                                             sequence="0"))),
                                    "reason": "RETENTION_TIME"}]
    with pytest.raises(CursorExpired) as caught:
        h.client().reports("1.0", 100)
    assert caught.value.earliest_cursor == "1.1"


def test_gateway_byte_bound_produces_explicit_loss_and_410(make_harness):
    """Each stamped record here is 1135 octets; under a 3000-octet bound the third and the fourth
    each push the oldest unacknowledged record out, each with its own loss row."""
    h = make_harness(provider_kwargs={"retention_bytes": 3000})
    for n in range(1, 5):
        h.publish(report(n, track_number=f"T-{n}"))
    losses = h.provider.losses()
    assert [(x["from_position"], x["to_position"], x["count"], x["bytes"], x["reason"])
            for x in losses] == [(1, 1, 1, 1135, "RETENTION_BYTES"),
                                 (2, 2, 1, 1135, "RETENTION_BYTES")]
    status, document = call(h, "GET", "/v1/reports?after=1.0")
    assert (status, document["code"], document["earliest_cursor"]) == (410, "CURSOR_EXPIRED", "1.2")
    _, batch = call(h, "GET", "/v1/reports?after=1.2")
    assert [r["body"]["record_id"] for r in batch["records"]] == [uid(3), uid(4)]


def test_sequence_never_wraps_and_a_new_session_opens_before_exhaustion(make_harness):
    h = make_harness(provider_kwargs={"start_sequence": UINT64_MAX - 1})
    first_session = h.provider.session(CHANNEL)[0]
    for n in (1, 2, 3):
        h.publish(report(n, track_number=f"T-{n}"))
    _, batch = call(h, "GET", "/v1/reports")
    assert batch["session_id"] == first_session
    assert [(r["body"]["session_id"], r["body"]["sequence"]) for r in batch["records"]] == [
        (first_session, str(UINT64_MAX - 1)), (first_session, str(UINT64_MAX))]
    assert batch["has_more"] is True                 # a batch never spans a session change
    _, second = call(h, "GET", "/v1/reports?after=" + batch["next_cursor"])
    new_session = second["records"][0]["body"]["session_id"]
    assert new_session != first_session and second["session_id"] == new_session
    assert second["records"][0]["body"]["sequence"] == "0"


def test_same_request_id_different_body_is_409_and_no_second_send(h):
    client = h.client()
    first = client.transmit(transmission(1, report(1)))
    assert (first["request_id"], first["state"], first["reason"]) == (uid(1), "SENT", None)
    with pytest.raises(GatewayError) as caught:
        client.transmit(transmission(1, report(1, track_number="CHANGED")))
    assert (caught.value.status, caught.value.code, caught.value.retryable) == (
        409, "REQUEST_ID_CONFLICT", False)
    assert [s["request_id"] for s in h.provider.sent()] == [uid(1)]


def test_same_request_id_identical_body_is_idempotent(h):
    client = h.client()
    one = client.transmit(transmission(1, report(1)))
    again = client.transmit(transmission(1, report(1)))
    assert one == again and again["state"] == "SENT"
    assert len(h.provider.sent()) == 1


def test_an_expired_request_is_422_recorded_expired_and_never_sent(h):
    client = h.client()
    late = transmission(1, report(1), expires="2026-10-04T12:00:00.000Z")
    with pytest.raises(GatewayError) as caught:
        client.transmit(late)
    assert (caught.value.status, caught.value.code) == (422, "REQUEST_EXPIRED")
    assert client.transmission_status(uid(1))["state"] == "EXPIRED"
    assert client.transmit(late)["state"] == "EXPIRED"     # the same body: never SENT later
    assert h.provider.sent() == []


def test_gateway_refuses_profile_mismatch_with_409(h):
    with pytest.raises(GatewayError) as caught:
        h.client().transmit(transmission(1, report(1, native_profile="OTHER-PROFILE")))
    assert (caught.value.status, caught.value.code) == (409, "PROFILE_MISMATCH")
    assert h.provider.sent() == []


def test_synthetic_provider_encode_refuses_out_of_contract_and_never_saturates(h):
    bad = report(1)
    bad["position"]["lat_deg"] = 90.5
    with pytest.raises(GatewayError) as caught:
        h.client().transmit(transmission(1, bad))
    assert (caught.value.status, caught.value.code) == (400, "SCHEMA_INVALID")
    live = report(2, synthetic=False)
    with pytest.raises(GatewayError) as caught:
        h.client().transmit(transmission(2, live))
    assert (caught.value.status, caught.value.code) == (422, "SYNTHETIC_MISMATCH")
    assert h.provider.sent() == []


def test_an_unknown_request_id_is_404(h):
    status, document = call(h, "GET", "/v1/transmissions/" + uid(77))
    assert (status, document["code"]) == (404, "NOT_FOUND")


def test_delivery_is_never_confirmed_by_the_synthetic_transport(h):
    h.client().transmit(transmission(1, report(1)))
    assert h.provider.status(uid(1)) == "SENT"


@pytest.mark.parametrize("setup, request_args, status, code", [
    (None, ("POST", "/v1/ack", b"{"), 400, "JSON_INVALID"),
    (None, ("POST", "/v1/ack", b'{"consumer_id":"c"}'), 400, "SCHEMA_INVALID"),
    (None, ("GET", "/v1/reports", None, "nobody"), 401, "UNAUTHENTICATED"),
    (None, ("POST", "/v1/ack", b'{"consumer_id":"other","cursor":"1.0"}'), 403, "FORBIDDEN"),
    (None, ("GET", "/v1/nothing", None), 404, "NOT_FOUND"),
    ("idempotent", ("POST", "/v1/transmissions", "conflict"), 409, "REQUEST_ID_CONFLICT"),
    ("retained", ("GET", "/v1/reports?after=1.0", None), 410, "CURSOR_EXPIRED"),
    (None, ("GET", "/v1/reports?after=1.5", None), 422, "CURSOR_FUTURE"),
    ("capacity", ("POST", "/v1/transmissions", "fresh"), 429, "CAPACITY"),
    ("unavailable", ("GET", "/v1/reports", None), 503, "PROVIDER_UNAVAILABLE"),
])
def test_every_status_code_has_a_json_error_body_with_retryable_only_for_429_and_503(
        h, setup, request_args, status, code):
    method, path, body, *credential = request_args
    if setup == "idempotent":
        h.client().transmit(transmission(1, report(1)))
    if setup == "retained":
        h.publish(report(1))
        h.clock.advance(24 * 3600)
    if setup == "capacity":
        h.provider.capacity_full = True
    if setup == "unavailable":
        h.provider.unavailable = True
    if body == "conflict":
        body = transmission(1, report(1, track_number="CHANGED"))
    if body == "fresh":
        body = transmission(2, report(2))
    got, document = call(h, method, path, body,
                         credential=("synthetic-bearer-" + "n" * 16) if credential else CREDENTIAL,
                         headers={"Content-Length": str(len(body))} if body is not None else None)
    assert got == status
    assert sorted(set(document) - {"earliest_cursor"}) == ERROR_KEYS
    assert document["code"] == code and document["retryable"] is (status in (429, 503))
    assert len(document["correlation_id"]) == 36


def test_an_error_message_never_carries_payload_bytes(h):
    marker = "PAYLOAD-MARKER-" + "m" * 8
    body = b'{"consumer_id":"' + marker.encode() + b'","consumer_id":"x","cursor":"1.0"}'
    status, document = call(h, "POST", "/v1/ack", body, headers={"Content-Length": str(len(body))})
    assert status == 400 and marker not in json.dumps(document)


def test_health_without_positions_identifiers_or_labels(h):
    h.publish(report(1))
    status, document = call(h, "GET", "/v1/health")
    assert status == 200
    assert sorted(document) == ["blocked_reasons", "oldest_unacked_ms", "provider_ready",
                                "queue_depth", "ready"]
    assert (document["ready"], document["queue_depth"], document["oldest_unacked_ms"]) == \
        (True, 1, 0)
    text = json.dumps(document)
    for forbidden in ("48.15", "TEST-0001", "SIMULATED-REPORTER", "SYNTHETIC-UNCLASSIFIED"):
        assert forbidden not in text


def test_long_poll_returns_an_empty_batch_when_nothing_arrives(make_harness):
    h = make_harness(long_poll=0.05)
    status, document = call(h, "GET", "/v1/reports?after=1.0")
    assert (status, document["records"], document["next_cursor"]) == (200, [], "1.0")


def test_the_server_compares_every_credential_with_compare_digest(h, monkeypatch):
    """HYGIENE-5 (A2F, 2026-10-11): the presented credential is compared with
    `hmac.compare_digest` against every configured one, the right one or not (an `==` comparison
    passed every other test)."""
    from synapse_link16_bridge.gateway import server
    calls = []
    real = server.hmac.compare_digest
    monkeypatch.setattr(server.hmac, "compare_digest",
                        lambda a, b: calls.append((a, b)) or real(a, b))
    assert call(h, "GET", "/v1/health")[0] == 200
    known = [CREDENTIAL.encode("ascii"), OTHER_CREDENTIAL.encode("ascii")]
    assert calls == [(CREDENTIAL.encode("ascii"), k) for k in known]
    calls.clear()
    wrong = "synthetic-bearer-" + "z" * 16
    assert call(h, "GET", "/v1/health", credential=wrong)[0] == 401
    assert calls == [(wrong.encode("ascii"), k) for k in known]


def stalled_post(port):
    """A connection that sends a POST's headers and 5 of its 100 body octets, then nothing."""
    import socket
    stalled = socket.create_connection(("127.0.0.1", port), timeout=5)
    stalled.sendall(b"POST /v1/ack HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " +
                    CREDENTIAL.encode("ascii") + b"\r\nContent-Type: application/json\r\n"
                    b"Content-Length: 100\r\n\r\nabcde")
    return stalled


def test_a_stalled_body_loses_its_connection_at_the_request_timeout(h):
    """HYGIENE-3 / RUNTIME-9 (A2F, 2026-10-11): the handler's socket operations time out after
    `request_timeout_seconds` (default 10), so a body that stops arriving ends the connection
    without an answer instead of holding a request thread."""
    from synapse_link16_bridge.gateway.server import DEFAULT_REQUEST_TIMEOUT, GatewayServer
    assert DEFAULT_REQUEST_TIMEOUT == 10.0
    server = GatewayServer(h.provider, {CREDENTIAL: (CONSUMER, CHANNEL)},
                           request_timeout_seconds=0.3).start()
    stalled = stalled_post(server.port)
    try:
        assert stalled.recv(1024) == b""            # closed by the server, no answer
    finally:
        stalled.close()
        server.stop()


def test_stop_returns_while_a_client_holds_a_connection_open(h):
    """HYGIENE-3 / RUNTIME-9 (A2F, 2026-10-11): `stop()` shuts down the connections still open
    before it joins their threads, so neither an idle client nor a stalled body holds it."""
    import socket
    import threading
    from synapse_link16_bridge.gateway.server import GatewayServer
    server = GatewayServer(h.provider, {CREDENTIAL: (CONSUMER, CHANNEL)}).start()
    idle = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    stalled = stalled_post(server.port)
    assert call_port(server.port) == 200            # the server is serving
    stopped = threading.Event()
    threading.Thread(target=lambda: (server.stop(), stopped.set()), daemon=True).start()
    try:
        assert stopped.wait(5)
    finally:
        idle.close()
        stalled.close()
        stopped.wait(15)


def call_port(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", "/v1/health", headers={"Authorization": "Bearer " + CREDENTIAL})
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()
