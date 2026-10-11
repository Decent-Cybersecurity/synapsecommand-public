"""The bridge's client for the gateway API: explicit URL, bounded, typed, no redirects.

`https://` uses `ssl.create_default_context()` (certificate and host name verified) with TLS 1.2
as the minimum; `http://` is accepted only for an exact loopback host name (`127.0.0.1`, `::1`,
`localhost`, compared on `urlsplit(...).hostname`), the "deployment approved local authenticated
channel" of the API section. No URL is discovered and nothing falls back to another protocol. The
connection is opened with `connect_timeout_seconds`; the request deadline (REQ061) is one bound on
the whole request, from before the connection to the last octet of the answer: the time left is
recomputed before every read (fix round 1, 2026-10-11) and before every send, the header block and
the body each (fix round 2, 2026-10-11), and given to the socket as that operation's whole timeout,
so neither a request sent into a slow sink nor an answer that arrives in slow pieces runs past the
deadline however short each pause is. A redirect is a protocol error, never followed; a response is
read up to 8 MiB plus one octet, and a longer one is refused.

The bearer credential is checked when the client is built (A2F, 2026-10-11): one or more visible
ASCII characters (0x21 to 0x7E; no space, no control character, nothing outside ASCII), the
characters a bearer token is written in. Anything else is refused as a configuration error whose
message names the reference and never the value, before it can reach a header (a CR or LF in a
header value raised an exception that quoted the whole header).

Typed outcomes: `GatewayError` (and its subclasses by status) for a JSON error the gateway sent,
`TransportError` when no answer arrived (a GET is retried with backoff), and `SendOutcomeUnknown`
for a POST whose request may have reached the gateway but whose answer did not: REQ062's
"transport timeouts require status reconciliation for writes" — the caller marks the job UNKNOWN
and reconciles; it never re-sends on its own.
"""
from __future__ import annotations

import functools
import http.client
import io
import re
import socket
import ssl
import time
import urllib.parse
from typing import Callable

from synapse_link16_bridge import contract, jsonstrict
from synapse_link16_bridge.config import LOOPBACK_HOSTS, ConfigError
from synapse_link16_bridge.contract import ContractError


#: A bearer credential: visible ASCII only (no space, no control character).
CREDENTIAL = re.compile(r"[\x21-\x7e]+")


class GatewayProtocolError(Exception):
    """An answer that is not the API's: a redirect, an oversized or malformed body."""

    def __init__(self, rule: str) -> None:
        self.rule = rule
        super().__init__(f"gateway protocol error: {rule}")


class TransportError(Exception):
    """No answer: the connection failed or the deadline passed before a response."""


class TransportTimeout(TransportError):
    pass


class SendOutcomeUnknown(Exception):
    """A write may have reached the gateway and its answer did not arrive (SEND_OUTCOME_UNKNOWN)."""


class GatewayError(Exception):
    def __init__(self, status: int, code: str, retryable: bool, correlation_id: str,
                 earliest_cursor: str | None = None) -> None:
        self.status, self.code, self.retryable = status, code, retryable
        self.correlation_id, self.earliest_cursor = correlation_id, earliest_cursor
        super().__init__(f"gateway refused: {status} {code}")


class AuthFailure(GatewayError):
    pass


class CursorExpired(GatewayError):
    pass


class Conflict(GatewayError):
    pass


class Capacity(GatewayError):
    pass


class Unavailable(GatewayError):
    pass


class NotFound(GatewayError):
    pass


_BY_STATUS = {401: AuthFailure, 403: AuthFailure, 404: NotFound, 409: Conflict,
              410: CursorExpired, 429: Capacity, 503: Unavailable}


def _time_left(deadline: float, monotonic: Callable[[], float]) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise socket.timeout("the request deadline passed")
    return remaining


class _DeadlineReader(io.RawIOBase):
    """The response's socket reads, each given only the time left before the request's
    deadline; at the deadline a read fails as a socket timeout. It reads through the socket's own
    file object (`raw`), which keeps the socket open until the response is closed."""

    def __init__(self, raw: io.RawIOBase, sock: socket.socket, deadline: float,
                 monotonic: Callable[[], float]) -> None:
        super().__init__()
        self._raw, self._sock = raw, sock
        self._deadline, self._monotonic = deadline, monotonic

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        self._sock.settimeout(_time_left(self._deadline, self._monotonic))
        return self._raw.readinto(buffer)

    def close(self) -> None:
        if not self.closed:
            self._raw.close()
        super().close()


class _DeadlineResponse(http.client.HTTPResponse):
    """An `HTTPResponse` whose reads (status line, headers and body) share one deadline."""

    def __init__(self, sock, *args, deadline: float, monotonic: Callable[[], float],
                 **kwargs) -> None:
        super().__init__(sock, *args, **kwargs)
        raw = self.fp.detach()
        self.fp = io.BufferedReader(_DeadlineReader(raw, sock, deadline, monotonic))


class _DeadlineSend:
    """A connection whose every send (`http.client` sends the header block and the body
    separately) is given only the time left before the request's deadline; Python's `sendall`
    treats the socket timeout as the bound on the whole call. At the deadline nothing more is
    sent and the send fails as a socket timeout (R4-F11, fix round 2, 2026-10-11)."""

    deadline: float
    monotonic: Callable[[], float]

    def send(self, data) -> None:
        remaining = _time_left(self.deadline, self.monotonic)
        if self.sock is not None:
            self.sock.settimeout(remaining)
        super().send(data)


class _HTTPConnection(_DeadlineSend, http.client.HTTPConnection):
    pass


class _HTTPSConnection(_DeadlineSend, http.client.HTTPSConnection):
    pass


def tls_context() -> ssl.SSLContext:
    """The TLS context of every `https://` connection: verified certificates and host names,
    TLS 1.2 at least."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class GatewayClient:
    def __init__(self, base_url: str, credential: str, *, connect_timeout: float,
                 request_deadline: float,
                 max_body_bytes: int = jsonstrict.MAX_BODY_BYTES,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme == "https":
            self._tls = tls_context()
        elif parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS:
            self._tls = None
        else:
            raise ValueError("gateway_base_url: https, or http to a loopback host only")
        if type(credential) is not str or CREDENTIAL.fullmatch(credential) is None:
            raise ConfigError("credential_ref", "the credential it names must be visible ASCII, "
                                                "without space or control characters")
        self._host = parts.hostname
        self._port = parts.port
        self._prefix = parts.path.rstrip("/")
        self._authorization = "Bearer " + credential
        self.connect_timeout = connect_timeout
        self.request_deadline = request_deadline
        self.max_body_bytes = max_body_bytes
        self.monotonic = monotonic

    def _connection(self, timeout: float, deadline: float) -> http.client.HTTPConnection:
        if self._tls is not None:
            connection = _HTTPSConnection(self._host, self._port, timeout=timeout,
                                          context=self._tls)
        else:
            connection = _HTTPConnection(self._host, self._port, timeout=timeout)
        connection.deadline, connection.monotonic = deadline, self.monotonic
        connection.response_class = functools.partial(_DeadlineResponse, deadline=deadline,
                                                      monotonic=self.monotonic)
        return connection

    def _exchange(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
        write = method == "POST"
        deadline = self.monotonic() + self.request_deadline
        connection = self._connection(min(self.connect_timeout, self.request_deadline), deadline)
        try:
            try:
                connection.connect()
            except (OSError, socket.timeout):
                raise TransportError("connection failed") from None
            headers = {"Authorization": self._authorization, "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            try:
                # each send and each read is given the time left (_DeadlineSend, _DeadlineReader)
                connection.request(method, self._prefix + path, body=body, headers=headers)
                response = connection.getresponse()
                try:
                    status = response.status
                    data = response.read(self.max_body_bytes + 1)
                finally:
                    response.close()
            except (OSError, socket.timeout, http.client.HTTPException):
                if write:
                    raise SendOutcomeUnknown("the write's answer did not arrive") from None
                raise TransportTimeout("the answer did not arrive") from None
        finally:
            connection.close()
        if 300 <= status < 400:
            raise GatewayProtocolError("a redirect, which is never followed")
        if len(data) > self.max_body_bytes:
            raise GatewayProtocolError("a response above the body limit")
        return status, data

    def _ok(self, method: str, path: str, expect: tuple[int, ...], body: bytes | None = None
            ) -> bytes:
        status, data = self._exchange(method, path, body)
        if status in expect:
            return data
        try:
            document = contract.validate_error(jsonstrict.loads(data))
        except ContractError:
            raise GatewayProtocolError("an error answer that is not the API's error form") \
                from None
        kind = _BY_STATUS.get(status, GatewayError)
        raise kind(status, document["code"], document["retryable"], document["correlation_id"],
                   document.get("earliest_cursor"))

    def _document(self, data: bytes):
        try:
            return jsonstrict.loads(data)
        except ContractError:
            raise GatewayProtocolError("a body that is not strict JSON") from None

    def capabilities(self) -> contract.Capabilities:
        data = self._ok("GET", "/v1/capabilities", (200,))
        try:
            return contract.validate_capabilities(self._document(data))
        except ContractError:
            raise GatewayProtocolError("capabilities outside the API contract") from None

    def reports(self, after: str | None, limit: int) -> bytes:
        query = {"limit": str(limit)}
        if after is not None:
            query["after"] = after
        return self._ok("GET", "/v1/reports?" + urllib.parse.urlencode(query), (200,))

    def ack(self, consumer_id: str, cursor: str) -> None:
        body = jsonstrict.canonical({"consumer_id": consumer_id, "cursor": cursor})
        self._ok("POST", "/v1/ack", (200,), body)

    def transmit(self, body: bytes) -> dict:
        data = self._ok("POST", "/v1/transmissions", (202,), body)
        try:
            return contract.validate_status(self._document(data))
        except ContractError:
            raise GatewayProtocolError("a status outside the API contract") from None

    def transmission_status(self, request_id: str) -> dict:
        data = self._ok("GET", f"/v1/transmissions/{request_id}", (200,))
        try:
            return contract.validate_status(self._document(data))
        except ContractError:
            raise GatewayProtocolError("a status outside the API contract") from None

    def health(self) -> dict:
        data = self._ok("GET", "/v1/health", (200,))
        try:
            return contract.validate_health(self._document(data))
        except ContractError:
            raise GatewayProtocolError("health outside the API contract") from None
