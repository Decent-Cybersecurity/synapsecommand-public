"""Hand-written validators for the gateway API's messages and the lifecycle notice.

The bridge's runtime dependencies are synapse-cdm and the standard library, so the API schema and
the notice schema of SC Link16 Gateway 1.0.0 are applied by the functions below rather than by a
schema engine: every `$defs` object of `api.schema.json` (capabilities, batch, ack, transmission,
status, health, error) and the notice of `notice.schema.json` with its two `if/then/else` rules.
`API_SCHEMA` and `NOTICE_SCHEMA` at the end of this module are the two schemas as data, printed by
`synapse-link16-bridge schema api|notice`; a repository-bound test holds them equal to the copies
published under `schemas/link16_gateway/`.

The patterns are applied as ECMA-262 applies them: anchored with `re.fullmatch` (no trailing
newline admitted) and with ASCII classes, never Python's Unicode `\\d`. A UUID is accepted only in
its canonical lowercase 8-4-4-4-12 form and a timestamp only as `YYYY-MM-DDTHH:mm:ss.sssZ` on a
strict calendar (no second 60, no hour 24), the same rules the `link16_gateway` adapter applies to
a report, so a notice and a report are judged alike. A report body is not validated here: the
adapter judges it on its octets. A batch envelope is validated by `jsonstrict.parse_batch`.

Every refusal is `ContractError(code, path, rule)`, never a value.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any

from synapse_cdm.adapters.link16_gateway import Link16GatewayRefusal, instant

from synapse_link16_bridge.jsonstrict import ContractError

PROFILE = "sc-link16-gateway/1.0.0"
UINT64_MAX = 2 ** 64 - 1
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DECIMAL = re.compile(r"0|[1-9][0-9]{0,19}")
TRANSMISSION_STATES = ("REJECTED", "ACCEPTED", "ENCODED", "SENT", "DELIVERY_CONFIRMED", "EXPIRED",
                       "FAILED", "UNKNOWN")
OPERATIONS = ("DROP_SOURCE", "REKEY", "GAP", "RESET_SCOPE")
NOTICE_KEYS = ("record_id", "session_id", "sequence", "received_at", "effective_at", "tenant",
               "realm", "synthetic", "origin_scope", "security_context", "track_number",
               "incarnation", "operation", "reason")
IDENTITY_KEYS = ("tenant", "realm", "synthetic", "origin_scope", "track_number", "incarnation")


def _fail(path: str, rule: str, code: str = "SCHEMA_INVALID") -> ContractError:
    return ContractError(code, path, rule)


def _object(doc: Any, path: str, required: tuple, optional: tuple = ()) -> dict:
    if type(doc) is not dict:
        raise _fail(path, "a JSON object")
    for key in required:
        if key not in doc:
            raise _fail(f"{path}.{key}" if path else key, "required")
    allowed = set(required) | set(optional)
    if any(key not in allowed for key in doc):
        raise _fail(path, "a key the schema does not define")
    return doc


def _string(value: Any, path: str, low: int = 0, high: int | None = None) -> str:
    if type(value) is not str:
        raise _fail(path, "type string")
    if len(value) < low or (high is not None and len(value) > high):
        raise _fail(path, "string length")
    return value


def identifier(value: Any, path: str) -> str:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise _fail(path, "identifier pattern")
    return value


def uuid_text(value: Any, path: str) -> str:
    if type(value) is not str or UUID.fullmatch(value) is None:
        raise _fail(path, "canonical lowercase UUID")
    return value


def decimal_u64(value: Any, path: str) -> str:
    if type(value) is not str or DECIMAL.fullmatch(value) is None or int(value) > UINT64_MAX:
        raise _fail(path, "decimal uint64 without leading zeroes")
    return value


def timestamp(value: Any, path: str, code: str = "SCHEMA_INVALID") -> str:
    if type(value) is not str:
        raise _fail(path, "type string")
    try:
        instant(value, path)
    except Link16GatewayRefusal:
        raise _fail(path, "YYYY-MM-DDTHH:mm:ss.sssZ on a strict calendar", code) from None
    return value


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise _fail(path, "type boolean")
    return value


def _integer(value: Any, path: str, low: int, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        raise _fail(path, "integer in range")
    return value


def _strings(value: Any, path: str, low: int, high: int, most: int) -> tuple[str, ...]:
    if type(value) is not list or len(value) > most:
        raise _fail(path, "array of bounded length")
    return tuple(_string(item, f"{path}[{i}]", low, high) for i, item in enumerate(value))


@dataclasses.dataclass(frozen=True)
class Capabilities:
    gateway_id: str
    native_profiles: tuple[str, ...]
    receive_families: tuple[str, ...]
    transmit_families: tuple[str, ...]
    max_batch: int
    replay_window_seconds: int


def validate_capabilities(doc: Any) -> Capabilities:
    _object(doc, "", ("profile", "gateway_id", "native_profiles", "receive_families",
                      "transmit_families", "max_batch", "replay_window_seconds"))
    if doc["profile"] != PROFILE or type(doc["profile"]) is not str:
        raise _fail("profile", "const")
    return Capabilities(
        gateway_id=identifier(doc["gateway_id"], "gateway_id"),
        native_profiles=_strings(doc["native_profiles"], "native_profiles", 1, 128, 64),
        receive_families=_strings(doc["receive_families"], "receive_families", 1, 32, 256),
        transmit_families=_strings(doc["transmit_families"], "transmit_families", 1, 32, 256),
        max_batch=_integer(doc["max_batch"], "max_batch", 1, 1000),
        replay_window_seconds=_integer(doc["replay_window_seconds"], "replay_window_seconds", 0))


def validate_ack(doc: Any) -> dict:
    _object(doc, "", ("consumer_id", "cursor"))
    identifier(doc["consumer_id"], "consumer_id")
    _string(doc["cursor"], "cursor", 1, 512)
    return doc


def validate_transmission(doc: Any) -> dict:
    """The transmission envelope. Its `report` must be a JSON object here; whether it is a valid
    report is the adapter's judgement on its octets."""
    _object(doc, "", ("request_id", "peer_id", "expires_at", "policy_revision", "report"))
    uuid_text(doc["request_id"], "request_id")
    identifier(doc["peer_id"], "peer_id")
    timestamp(doc["expires_at"], "expires_at")
    _string(doc["policy_revision"], "policy_revision", 1, 128)
    if type(doc["report"]) is not dict:
        raise _fail("report", "a JSON object")
    return doc


def validate_status(doc: Any) -> dict:
    _object(doc, "", ("request_id", "state", "reason", "changed_at"))
    uuid_text(doc["request_id"], "request_id")
    if doc["state"] not in TRANSMISSION_STATES or type(doc["state"]) is not str:
        raise _fail("state", "enum")
    if doc["reason"] is not None:
        _string(doc["reason"], "reason", 1, 1024)
    timestamp(doc["changed_at"], "changed_at")
    return doc


def validate_health(doc: Any) -> dict:
    _object(doc, "", ("ready", "provider_ready", "blocked_reasons", "queue_depth",
                      "oldest_unacked_ms"))
    _boolean(doc["ready"], "ready")
    _boolean(doc["provider_ready"], "provider_ready")
    _strings(doc["blocked_reasons"], "blocked_reasons", 1, 128, 128)
    _integer(doc["queue_depth"], "queue_depth", 0)
    if doc["oldest_unacked_ms"] is not None:
        _integer(doc["oldest_unacked_ms"], "oldest_unacked_ms", 0)
    return doc


def validate_error(doc: Any) -> dict:
    _object(doc, "", ("code", "message", "correlation_id", "retryable"), ("earliest_cursor",))
    _string(doc["code"], "code", 1, 128)
    _string(doc["message"], "message", 1, 1024)
    uuid_text(doc["correlation_id"], "correlation_id")
    _boolean(doc["retryable"], "retryable")
    if "earliest_cursor" in doc:
        _string(doc["earliest_cursor"], "earliest_cursor", 1, 512)
    return doc


def _identity_object(value: Any, path: str) -> dict:
    _object(value, path, IDENTITY_KEYS)
    for key in ("tenant", "realm", "origin_scope"):
        identifier(value[key], f"{path}.{key}")
    _boolean(value["synthetic"], f"{path}.synthetic")
    _string(value["track_number"], f"{path}.track_number", 1, 64)
    decimal_u64(value["incarnation"], f"{path}.incarnation")
    return value


def validate_notice(doc: Any) -> dict:
    """A lifecycle notice, with the schema's two conditional rules. Timestamps that are not
    calendar instants are TIME_UNRESOLVED (the code the contract gives an unreadable time)."""
    _object(doc, "", NOTICE_KEYS, ("old_identity", "new_identity"))
    uuid_text(doc["record_id"], "record_id")
    uuid_text(doc["session_id"], "session_id")
    decimal_u64(doc["sequence"], "sequence")
    for key in ("tenant", "realm", "origin_scope", "security_context"):
        identifier(doc[key], key)
    _boolean(doc["synthetic"], "synthetic")
    operation = doc["operation"]
    if type(operation) is not str or operation not in OPERATIONS:
        raise _fail("operation", "enum")
    _string(doc["reason"], "reason", 1, 1024)
    if operation == "REKEY":
        for key in ("old_identity", "new_identity"):
            if key not in doc:
                raise _fail(key, "required for REKEY")
            _identity_object(doc[key], key)
    elif "old_identity" in doc or "new_identity" in doc:
        raise _fail("old_identity" if "old_identity" in doc else "new_identity",
                    "only REKEY carries identity objects")
    if operation in ("GAP", "RESET_SCOPE"):
        for key in ("track_number", "incarnation"):
            if doc[key] is not None:
                raise _fail(key, "null for a channel-scoped notice")
    else:
        _string(doc["track_number"], "track_number", 1, 64)
        decimal_u64(doc["incarnation"], "incarnation")
    timestamp(doc["received_at"], "received_at", "TIME_UNRESOLVED")
    timestamp(doc["effective_at"], "effective_at", "TIME_UNRESOLVED")
    return doc


# ------------------------------------------------------------------ the two schemas, as data

API_SCHEMA: dict[str, Any] = (
    {'$schema': 'https://json-schema.org/draft/2020-12/schema',
     '$id': 'urn:synapsecommand:sc-link16-gateway:api:1.0.0',
     '$defs': {'capabilities': {'type': 'object',
                                'properties': {'profile': {'const': 'sc-link16-gateway/1.0.0'},
                                               'gateway_id': {'type': 'string',
                                                              'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                               'native_profiles': {'type': 'array',
                                                                   'items': {'type': 'string',
                                                                             'minLength': 1,
                                                                             'maxLength': 128},
                                                                   'maxItems': 64},
                                               'receive_families': {'type': 'array',
                                                                    'items': {'type': 'string',
                                                                              'minLength': 1,
                                                                              'maxLength': 32},
                                                                    'maxItems': 256},
                                               'transmit_families': {'type': 'array',
                                                                     'items': {'type': 'string',
                                                                               'minLength': 1,
                                                                               'maxLength': 32},
                                                                     'maxItems': 256},
                                               'max_batch': {'type': 'integer',
                                                             'minimum': 1,
                                                             'maximum': 1000},
                                               'replay_window_seconds': {'type': 'integer',
                                                                         'minimum': 0}},
                                'required': ['profile',
                                             'gateway_id',
                                             'native_profiles',
                                             'receive_families',
                                             'transmit_families',
                                             'max_batch',
                                             'replay_window_seconds'],
                                'additionalProperties': False},
               'batch': {'type': 'object',
                         'properties': {'session_id': {'type': 'string', 'format': 'uuid'},
                                        'records': {'type': 'array',
                                                    'items': {'oneOf': [{'type': 'object',
                                                                         'properties': {'kind': {'const': 'report'},
                                                                                        'body': {'$ref': 'urn:synapsecommand:sc-link16-gateway:report:1.0.0'}},
                                                                         'required': ['kind',
                                                                                      'body'],
                                                                         'additionalProperties': False},
                                                                        {'type': 'object',
                                                                         'properties': {'kind': {'const': 'notice'},
                                                                                        'body': {'$ref': 'urn:synapsecommand:sc-link16-gateway:notice:1.0.0'}},
                                                                         'required': ['kind',
                                                                                      'body'],
                                                                         'additionalProperties': False}]},
                                                    'maxItems': 1000},
                                        'next_cursor': {'type': 'string',
                                                        'minLength': 1,
                                                        'maxLength': 512},
                                        'has_more': {'type': 'boolean'}},
                         'required': ['session_id', 'records', 'next_cursor', 'has_more'],
                         'additionalProperties': False},
               'ack': {'type': 'object',
                       'properties': {'consumer_id': {'type': 'string',
                                                      'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                      'cursor': {'type': 'string',
                                                 'minLength': 1,
                                                 'maxLength': 512}},
                       'required': ['consumer_id', 'cursor'],
                       'additionalProperties': False},
               'transmission': {'type': 'object',
                                'properties': {'request_id': {'type': 'string', 'format': 'uuid'},
                                               'peer_id': {'type': 'string',
                                                           'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                               'expires_at': {'type': 'string',
                                                              'format': 'date-time',
                                                              'pattern': '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$'},
                                               'policy_revision': {'type': 'string',
                                                                   'minLength': 1,
                                                                   'maxLength': 128},
                                               'report': {'$ref': 'urn:synapsecommand:sc-link16-gateway:report:1.0.0'}},
                                'required': ['request_id',
                                             'peer_id',
                                             'expires_at',
                                             'policy_revision',
                                             'report'],
                                'additionalProperties': False},
               'status': {'type': 'object',
                          'properties': {'request_id': {'type': 'string', 'format': 'uuid'},
                                         'state': {'type': 'string',
                                                   'enum': ['REJECTED',
                                                            'ACCEPTED',
                                                            'ENCODED',
                                                            'SENT',
                                                            'DELIVERY_CONFIRMED',
                                                            'EXPIRED',
                                                            'FAILED',
                                                            'UNKNOWN']},
                                         'reason': {'anyOf': [{'type': 'string',
                                                               'minLength': 1,
                                                               'maxLength': 1024},
                                                              {'type': 'null'}]},
                                         'changed_at': {'type': 'string',
                                                        'format': 'date-time',
                                                        'pattern': '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$'}},
                          'required': ['request_id', 'state', 'reason', 'changed_at'],
                          'additionalProperties': False},
               'health': {'type': 'object',
                          'properties': {'ready': {'type': 'boolean'},
                                         'provider_ready': {'type': 'boolean'},
                                         'blocked_reasons': {'type': 'array',
                                                             'items': {'type': 'string',
                                                                       'minLength': 1,
                                                                       'maxLength': 128},
                                                             'maxItems': 128},
                                         'queue_depth': {'type': 'integer', 'minimum': 0},
                                         'oldest_unacked_ms': {'anyOf': [{'type': 'integer',
                                                                          'minimum': 0},
                                                                         {'type': 'null'}]}},
                          'required': ['ready',
                                       'provider_ready',
                                       'blocked_reasons',
                                       'queue_depth',
                                       'oldest_unacked_ms'],
                          'additionalProperties': False},
               'error': {'type': 'object',
                         'properties': {'code': {'type': 'string',
                                                 'minLength': 1,
                                                 'maxLength': 128},
                                        'message': {'type': 'string',
                                                    'minLength': 1,
                                                    'maxLength': 1024},
                                        'correlation_id': {'type': 'string', 'format': 'uuid'},
                                        'retryable': {'type': 'boolean'},
                                        'earliest_cursor': {'type': 'string',
                                                            'minLength': 1,
                                                            'maxLength': 512}},
                         'required': ['code', 'message', 'correlation_id', 'retryable'],
                         'additionalProperties': False}}}
)

NOTICE_SCHEMA: dict[str, Any] = (
    {'type': 'object',
     'properties': {'record_id': {'type': 'string', 'format': 'uuid'},
                    'session_id': {'type': 'string', 'format': 'uuid'},
                    'sequence': {'type': 'string', 'pattern': '^(0|[1-9][0-9]{0,19})$'},
                    'received_at': {'type': 'string',
                                    'format': 'date-time',
                                    'pattern': '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$'},
                    'effective_at': {'type': 'string',
                                     'format': 'date-time',
                                     'pattern': '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$'},
                    'tenant': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                    'realm': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                    'synthetic': {'type': 'boolean'},
                    'origin_scope': {'type': 'string',
                                     'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                    'security_context': {'type': 'string',
                                         'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                    'track_number': {'anyOf': [{'type': 'string', 'minLength': 1, 'maxLength': 64},
                                               {'type': 'null'}]},
                    'incarnation': {'anyOf': [{'type': 'string',
                                               'pattern': '^(0|[1-9][0-9]{0,19})$'},
                                              {'type': 'null'}]},
                    'operation': {'type': 'string',
                                  'enum': ['DROP_SOURCE', 'REKEY', 'GAP', 'RESET_SCOPE']},
                    'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1024},
                    'old_identity': {'type': 'object',
                                     'properties': {'tenant': {'type': 'string',
                                                               'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                                    'realm': {'type': 'string',
                                                              'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                                    'synthetic': {'type': 'boolean'},
                                                    'origin_scope': {'type': 'string',
                                                                     'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                                    'track_number': {'type': 'string',
                                                                     'minLength': 1,
                                                                     'maxLength': 64},
                                                    'incarnation': {'type': 'string',
                                                                    'pattern': '^(0|[1-9][0-9]{0,19})$'}},
                                     'required': ['tenant',
                                                  'realm',
                                                  'synthetic',
                                                  'origin_scope',
                                                  'track_number',
                                                  'incarnation'],
                                     'additionalProperties': False},
                    'new_identity': {'type': 'object',
                                     'properties': {'tenant': {'type': 'string',
                                                               'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                                    'realm': {'type': 'string',
                                                              'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                                    'synthetic': {'type': 'boolean'},
                                                    'origin_scope': {'type': 'string',
                                                                     'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
                                                    'track_number': {'type': 'string',
                                                                     'minLength': 1,
                                                                     'maxLength': 64},
                                                    'incarnation': {'type': 'string',
                                                                    'pattern': '^(0|[1-9][0-9]{0,19})$'}},
                                     'required': ['tenant',
                                                  'realm',
                                                  'synthetic',
                                                  'origin_scope',
                                                  'track_number',
                                                  'incarnation'],
                                     'additionalProperties': False}},
     'required': ['record_id',
                  'session_id',
                  'sequence',
                  'received_at',
                  'effective_at',
                  'tenant',
                  'realm',
                  'synthetic',
                  'origin_scope',
                  'security_context',
                  'track_number',
                  'incarnation',
                  'operation',
                  'reason'],
     'additionalProperties': False,
     'allOf': [{'if': {'properties': {'operation': {'const': 'REKEY'}}},
                'then': {'required': ['old_identity', 'new_identity']},
                'else': {'not': {'anyOf': [{'required': ['old_identity']},
                                           {'required': ['new_identity']}]}}},
               {'if': {'properties': {'operation': {'enum': ['GAP', 'RESET_SCOPE']}}},
                'then': {'properties': {'track_number': {'type': 'null'},
                                        'incarnation': {'type': 'null'}}},
                'else': {'properties': {'track_number': {'type': 'string',
                                                         'minLength': 1,
                                                         'maxLength': 64},
                                        'incarnation': {'type': 'string',
                                                        'pattern': '^(0|[1-9][0-9]{0,19})$'}}}}],
     '$schema': 'https://json-schema.org/draft/2020-12/schema',
     '$id': 'urn:synapsecommand:sc-link16-gateway:notice:1.0.0'}
)
