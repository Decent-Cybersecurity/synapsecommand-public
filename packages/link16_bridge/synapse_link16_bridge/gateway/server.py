"""The loopback HTTP server for the synthetic provider: exactly the six endpoints of the API.

Bound to the literal address `127.0.0.1` and nothing else — a synthetic gateway has no reason to
listen on another interface, and no bind address is configurable. Endpoints: `GET
/v1/capabilities`, `GET /v1/reports`, `POST /v1/ack`, `POST /v1/transmissions`, `GET
/v1/transmissions/{request_id}`, `GET /v1/health`; anything else is 404 `NOT_FOUND`.

Every request carries `Authorization: Bearer <credential>`; the credential is compared with
`hmac.compare_digest` against the configured ones and is never hashed, logged or stored. Each
credential is bound to one consumer and one channel: a request without a valid one is 401
`UNAUTHENTICATED`, an acknowledgement for another consumer is 403 `FORBIDDEN`, and the report
endpoint serves only the bound channel (REQ060). A POST needs `Content-Length`; above 8 MiB it is
413 before a byte of the body is read. Errors are `{code, message, correlation_id, retryable}`
from the provider's fixed table (`retryable` only for 429 and 503), never an exception's text or a
payload value; even the HTTP parser's own refusals are answered in that form. The report endpoint
long-polls on a condition up to the configured `long_poll_seconds`. Health carries no position,
participant identifier or label.

Every connection's socket operations time out after `request_timeout_seconds` (default 10), so a
client that stops sending in the middle of a body, or idles on a kept-alive connection, loses its
connection instead of holding a request thread; and `stop()` shuts down every connection still
open before it joins the request threads, so it returns while a client holds one open (A2F,
2026-10-11).
"""
from __future__ import annotations

import hmac
import http.server
import json
import re
import socket
import threading
import urllib.parse
import uuid

from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.gateway.provider import ERRORS, ApiError, Reply, SyntheticProvider

BIND_ADDRESS = "127.0.0.1"
DEFAULT_REQUEST_TIMEOUT = 10.0
ENDPOINTS = (
    ("GET", "/v1/capabilities"),
    ("GET", "/v1/reports"),
    ("POST", "/v1/ack"),
    ("POST", "/v1/transmissions"),
    ("GET", "/v1/transmissions/{request_id}"),
    ("GET", "/v1/health"),
)
_STATUS_PATH = re.compile(r"/v1/transmissions/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
                          r"-[0-9a-f]{12})")
_DECIMAL = re.compile(r"[1-9][0-9]{0,3}")


def error_body(code: str, earliest_cursor: str | None = None) -> bytes:
    status, message = ERRORS[code]
    document = {"code": code, "message": message, "correlation_id": str(uuid.uuid4()),
                "retryable": status in (429, 503)}
    if earliest_cursor is not None:
        document["earliest_cursor"] = earliest_cursor
    return json.dumps(document, separators=(",", ":")).encode("ascii")


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "synapse-link16-synthetic-gateway"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        """Every socket operation of this connection is bounded (`request_timeout_seconds`); a
        read that times out ends the connection without an answer."""
        self.timeout = self.server.request_timeout
        super().setup()

    # -- every answer goes through here
    def _send(self, status: int, body: bytes, *, close: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: str, earliest_cursor: str | None = None, *,
               close: bool = False) -> None:
        self._send(ERRORS[code][0], error_body(code, earliest_cursor), close=close)

    def send_error(self, code, message=None, explain=None) -> None:  # noqa: D401
        """The HTTP parser's refusals, answered in the API's error form with fixed text."""
        self._error("NOT_FOUND" if code in (404, 405, 501) else "SCHEMA_INVALID", close=True)

    def log_message(self, format, *args) -> None:  # noqa: A002 - the base class's signature
        """Request lines are not logged: the server logs nothing."""
        return None

    # -- authentication
    def _binding(self) -> tuple[str, str] | None:
        presented = self.headers.get("Authorization", "")
        if not presented.startswith("Bearer "):
            return None
        offered = presented[len("Bearer "):].encode("utf-8", "surrogateescape")
        found = None
        for known, binding in self.server.bindings:
            if hmac.compare_digest(offered, known):
                found = binding
        return found

    def _dispatch(self, method: str) -> None:
        provider: SyntheticProvider = self.server.provider
        binding = self._binding()
        if binding is None:
            self._error("UNAUTHENTICATED", close=method == "POST")
            return
        consumer, channel = binding
        parts = urllib.parse.urlsplit(self.path)
        path, query = parts.path, parts.query
        try:
            if method == "GET" and path == "/v1/reports":
                reply = self._reports(provider, channel, query)
            elif query:
                raise ApiError("SCHEMA_INVALID")
            elif method == "GET" and path == "/v1/capabilities":
                reply = Reply(200, jsonstrict.canonical(provider.capabilities_document()))
            elif method == "GET" and path == "/v1/health":
                reply = Reply(200, jsonstrict.canonical(provider.health_document(channel)))
            elif method == "GET" and _STATUS_PATH.fullmatch(path):
                reply = provider.transmission_status(channel, _STATUS_PATH.fullmatch(path).group(1))
            elif method == "POST" and path in ("/v1/ack", "/v1/transmissions"):
                octets = self._body()
                if octets is None:
                    return
                if path == "/v1/ack":
                    reply = provider.ack(channel, consumer, octets)
                    if provider.hold_ack_response_seconds > 0:
                        provider.release_hold.wait(provider.hold_ack_response_seconds)
                else:
                    reply = provider.transmit(channel, octets)
                    if reply.status == 202 and provider.hold_response_seconds > 0:
                        provider.release_hold.wait(provider.hold_response_seconds)
            else:
                raise ApiError("NOT_FOUND")
        except ApiError as error:
            self._error(error.code, error.earliest_cursor, close=method == "POST")
            return
        self._send(reply.status, reply.body)

    def _body(self) -> bytes | None:
        if self.headers.get("Transfer-Encoding") is not None:
            self._error("SCHEMA_INVALID", close=True)
            return None
        text = (self.headers.get("Content-Length") or "").strip()
        if not text or not text.isascii() or not text.isdigit() or \
                (len(text) > 1 and text[0] == "0"):
            self._error("SCHEMA_INVALID", close=True)
            return None
        size = int(text) if len(text) <= 12 else self.server.max_body_bytes + 1
        if size > self.server.max_body_bytes:
            self._error("LIMIT_EXCEEDED", close=True)
            return None
        return self.rfile.read(size)

    def _reports(self, provider: SyntheticProvider, channel: str, query: str) -> Reply:
        try:
            pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True) \
                if query else []
        except ValueError:
            raise ApiError("SCHEMA_INVALID") from None
        names = [name for name, _value in pairs]
        if len(set(names)) != len(names) or any(name not in ("after", "limit") for name in names):
            raise ApiError("SCHEMA_INVALID")
        given = dict(pairs)
        limit = 100
        if "limit" in given:
            if _DECIMAL.fullmatch(given["limit"]) is None or int(given["limit"]) > 1000:
                raise ApiError("SCHEMA_INVALID")
            limit = int(given["limit"])
        limit = min(limit, provider.max_batch)
        after = given.get("after")
        if after is not None and not 1 <= len(after) <= 512:
            raise ApiError("SCHEMA_INVALID")
        reply = provider.reports(channel, after, limit)
        if reply is None and self.server.long_poll_seconds > 0:
            with provider.arrived:
                provider.arrived.wait(self.server.long_poll_seconds)
            reply = provider.reports(channel, after, limit)
        return reply if reply is not None else provider.empty_batch(channel, after)

    def do_GET(self) -> None:  # noqa: N802 - the base class's naming
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _not_found(self) -> None:
        self._error("NOT_FOUND", close=True)

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _not_found


class _Server(http.server.ThreadingHTTPServer):
    # Request threads are joined when the server closes, so no request outlives `stop()`; the
    # connections still open are shut down first, so the join does not wait on a client.
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._open: set[socket.socket] = set()
        self._open_lock = threading.Lock()

    def process_request_thread(self, request, client_address) -> None:
        with self._open_lock:
            self._open.add(request)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._open_lock:
                self._open.discard(request)

    def shut_open_connections(self) -> None:
        with self._open_lock:
            open_now = list(self._open)
        for connection in open_now:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class GatewayServer:
    """Serve a `SyntheticProvider` on `127.0.0.1:port` (0 picks a free port).

    `bindings` maps each accepted bearer credential to `(consumer_id, channel)`; the mapping is
    held in memory only."""

    def __init__(self, provider: SyntheticProvider, bindings: dict[str, tuple[str, str]], *,
                 port: int = 0, long_poll_seconds: float = 0.0,
                 max_body_bytes: int = jsonstrict.MAX_BODY_BYTES,
                 request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT) -> None:
        self._httpd = _Server((BIND_ADDRESS, port), _Handler)
        self._httpd.provider = provider
        self._httpd.bindings = tuple((key.encode("utf-8"), value)
                                     for key, value in bindings.items())
        self._httpd.long_poll_seconds = long_poll_seconds
        self._httpd.max_body_bytes = max_body_bytes
        self._httpd.request_timeout = request_timeout_seconds
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://{BIND_ADDRESS}:{self.port}"

    def start(self) -> "GatewayServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever, args=(0.05,),
                                        daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.provider.release_hold.set()
        self._httpd.shutdown()
        self._httpd.shut_open_connections()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join()
