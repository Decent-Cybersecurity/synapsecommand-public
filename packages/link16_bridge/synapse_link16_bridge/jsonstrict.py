"""The one strict JSON reader for the gateway API's bodies, and the canonical encoding.

STRICT
------
UTF-8 without a byte order mark, decoded strictly; no duplicate object key; no `NaN`, `Infinity`
or `-Infinity`; no lone surrogate in a string or a key; no number that overflows a double, no
non-zero number that underflows to zero, and no integer a double cannot hold exactly (the same
number rule the `link16_gateway` adapter applies to a report). A body above 8 MiB is refused
before it is decoded, and nesting is read off the characters before the decoder runs.

ONE BATCH, MANY REPORTS (X12)
-----------------------------
A report batch is one JSON text holding many records, and REQ065 says a malformed report is
quarantined while the other records continue. So the batch parser does not raise on a fault
INSIDE a record's `body`: a duplicate key, a non-finite literal, a lone surrogate or a number no
double holds marks that one record `JSON_INVALID`, and the rest are judged on their own. A fault
OUTSIDE every body — a byte order mark at byte 0, invalid UTF-8, text that is not JSON, nesting
deeper than the batch bound, or an envelope that is not the API's `batch` object — makes the batch
structurally invalid, and nothing of it is consumed.

The batch bound is 67 levels: the contract's per-report bound of 64 that the adapter's base class
enforces, plus the envelope's three (the batch object, `records`, the record object). A legal
report of depth 32 sits at depth 35; a body deeper than the contract's 32 is refused per record by
the adapter (`LIMIT_EXCEEDED`), and only a body deeper than 64 makes its whole batch invalid.

Every refusal is `ContractError(code, path, rule)`, whose message never quotes a value.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from typing import Any

from synapse_cdm.adapter import json_nesting_depth

#: REQ061: an HTTP body is at most 8 MiB.
MAX_BODY_BYTES = 8 * 1024 * 1024
#: X13: the per-report parser bound (64) plus the envelope's three levels.
BATCH_DEPTH = 67
#: The depth bound of every other API body and of the configuration file.
BODY_DEPTH = 32
#: REQ061: `max_batch` is at most 1000.
MAX_RECORDS = 1000

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_NONZERO_DIGIT = re.compile(r"[1-9]")
_EXPONENT = re.compile(r"[eE]")


class ContractError(ValueError):
    """A refusal by the contract: `code` from the contract's error table (or the bridge's local
    codes), `path` a place in the document, `rule` a fixed phrase. Never a value."""

    def __init__(self, code: str, path: str, rule: str) -> None:
        self.code, self.path, self.rule = code, path, rule
        super().__init__(f"{code}: {path or '(body)'} — {rule}")


class _Fault:
    """A defect found while decoding, kept in the tree in place of the value it spoiled."""

    __slots__ = ("rule", "detail")

    def __init__(self, rule: str, detail: Any = None) -> None:
        self.rule = rule
        self.detail = detail


def _pairs(pairs: list[tuple[str, Any]]) -> Any:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            return _Fault("duplicate object key", [list(p) for p in pairs])
        out[key] = value
    return out


def _constant(name: str) -> Any:
    return _Fault("non-finite number literal", name)


def _int(text: str) -> Any:
    try:
        value = int(text)
    except ValueError:
        return _Fault("integer not exactly representable as a double", text[:32])
    try:
        exact = int(float(value)) == value
    except OverflowError:
        exact = False
    return value if exact else _Fault("integer not exactly representable as a double", text[:32])


def _float(text: str) -> Any:
    value = float(text)
    if not math.isfinite(value):
        return _Fault("number overflows a finite double", text[:32])
    if value == 0.0 and _NONZERO_DIGIT.search(_EXPONENT.split(text)[0]):
        return _Fault("number underflows a double to zero", text[:32])
    return value


def _decode(octets: bytes, depth: int) -> Any:
    if len(octets) > MAX_BODY_BYTES:
        raise ContractError("LIMIT_EXCEEDED", "", "body above 8 MiB")
    if octets.startswith(b"\xef\xbb\xbf"):
        raise ContractError("JSON_INVALID", "", "byte order mark")
    try:
        text = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise ContractError("JSON_INVALID", "", "not UTF-8") from None
    if json_nesting_depth(text) > depth:
        raise ContractError("LIMIT_EXCEEDED", "", f"nesting above {depth}")
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant,
                          parse_int=_int, parse_float=_float)
    except (ValueError, RecursionError):
        raise ContractError("JSON_INVALID", "", "not a JSON text") from None


def _first_fault(node: Any) -> str | None:
    """The rule of the first defect anywhere in a decoded tree, or None (iterative walk)."""
    pending = [node]
    while pending:
        item = pending.pop()
        if type(item) is _Fault:
            return item.rule
        if type(item) is dict:
            for key, value in item.items():
                if not _scalar_ok(key):
                    return "lone surrogate"
                pending.append(value)
        elif type(item) is list:
            pending.extend(item)
        elif type(item) is str and not _scalar_ok(item):
            return "lone surrogate"
    return None


def _scalar_ok(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def loads(octets: bytes, *, depth: int = BODY_DEPTH) -> Any:
    """One whole API body (or the configuration file), strictly: any defect refuses it all."""
    document = _decode(bytes(octets), depth)
    rule = _first_fault(document)
    if rule is not None:
        raise ContractError("JSON_INVALID", "", rule)
    return document


def canonical(obj: Any) -> bytes:
    """The canonical JSON encoding: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fault_safe(node: Any) -> Any:
    """A decoded tree with every `_Fault` replaced by a marker, for a stable digest of a body
    that cannot be canonicalised (the same bytes always give the same digest)."""
    if type(node) is _Fault:
        return {"\u0000fault": [node.rule, _fault_safe(node.detail)]}
    if type(node) is dict:
        return {k.encode("utf-8", "surrogatepass").hex(): _fault_safe(v) for k, v in node.items()}
    if type(node) is list:
        return [_fault_safe(v) for v in node]
    if type(node) is str:
        return node.encode("utf-8", "surrogatepass").hex()
    if type(node) is float and not math.isfinite(node):
        return repr(node)
    return node


@dataclasses.dataclass(frozen=True)
class RawRecord:
    """One record of a batch. `body` is the decoded object when it is sound JSON, else None and
    `fault` names the rule; `digest` is the SHA-256 of the canonical body (or, for a faulty one,
    of a stable marker encoding), `record_id` the body's own when it carries one as a string."""

    index: int
    kind: str
    body: dict | None
    fault: str | None
    digest: str
    record_id: str | None


@dataclasses.dataclass(frozen=True)
class Batch:
    session_id: str
    next_cursor: str
    has_more: bool
    records: tuple[RawRecord, ...]
    sha256: str
    size: int


_ENVELOPE = ("session_id", "records", "next_cursor", "has_more")


def parse_batch(octets: bytes) -> Batch:
    """A `GET /v1/reports` body -> `Batch`, or `ContractError` when it is structurally invalid."""
    octets = bytes(octets)
    document = _decode(octets, BATCH_DEPTH)
    if type(document) is not dict:
        raise ContractError("JSON_INVALID" if type(document) is _Fault else "SCHEMA_INVALID",
                            "", "the batch is not one JSON object")
    if sorted(document) != sorted(_ENVELOPE):
        raise ContractError("SCHEMA_INVALID", "", "batch keys are not exactly the API's")
    session, cursor, more, records = (document["session_id"], document["next_cursor"],
                                      document["has_more"], document["records"])
    if type(session) is not str or _UUID.fullmatch(session) is None:
        raise ContractError("SCHEMA_INVALID", "session_id", "canonical lowercase UUID")
    if type(cursor) is not str or not 1 <= len(cursor) <= 512 or not _scalar_ok(cursor):
        raise ContractError("SCHEMA_INVALID", "next_cursor", "string of 1 to 512 characters")
    if type(more) is not bool:
        raise ContractError("SCHEMA_INVALID", "has_more", "boolean")
    if type(records) is not list:
        raise ContractError("SCHEMA_INVALID", "records", "array")
    if len(records) > MAX_RECORDS:
        raise ContractError("LIMIT_EXCEEDED", "records", "more than 1000 records")
    out = []
    for index, item in enumerate(records):
        path = f"records[{index}]"
        if type(item) is not dict or sorted(item) != ["body", "kind"]:
            raise ContractError("SCHEMA_INVALID", path, "a record is exactly kind and body")
        kind, body = item["kind"], item["body"]
        if type(kind) is not str or kind not in ("report", "notice"):
            raise ContractError("SCHEMA_INVALID", f"{path}.kind", "report or notice")
        if type(body) is not dict and not (type(body) is _Fault and type(body.detail) is list):
            raise ContractError("SCHEMA_INVALID", f"{path}.body", "a JSON object")
        rule = _first_fault(body)
        if rule is None:
            digest = sha256_hex(canonical(body))
            record_id = body.get("record_id")
            record_id = record_id if type(record_id) is str and len(record_id) <= 128 else None
            session_of_body = body.get("session_id")
            if type(session_of_body) is str and session_of_body != session:
                raise ContractError("SCHEMA_INVALID", f"{path}.body.session_id",
                                    "a record of another session inside this batch")
            out.append(RawRecord(index, kind, body, None, digest, record_id))
        else:
            digest = sha256_hex(json.dumps(_fault_safe(body), sort_keys=True,
                                           separators=(",", ":")).encode("ascii"))
            out.append(RawRecord(index, kind, None, rule, digest, None))
    return Batch(session, cursor, more, tuple(out), sha256_hex(octets), len(octets))
