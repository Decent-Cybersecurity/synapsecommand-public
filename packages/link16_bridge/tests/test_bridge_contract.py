"""The API's message validators and the notice schema with its two conditional rules (REQ064,
W5-12). Each refusal is checked for its exact code, path and rule."""
import copy
import json

import pytest

from helpers import REPO, notice, uid
from synapse_link16_bridge import contract
from synapse_link16_bridge.jsonstrict import ContractError

CAPABILITIES = {"profile": "sc-link16-gateway/1.0.0", "gateway_id": "synthetic-gateway-1",
                "native_profiles": ["SYNTHETIC-NO-NATIVE-CODEC"], "receive_families": ["J3.2"],
                "transmit_families": [], "max_batch": 1000, "replay_window_seconds": 86400}
STATUS = {"request_id": uid(1), "state": "SENT", "reason": None,
          "changed_at": "2026-10-04T12:00:00.000Z"}
HEALTH = {"ready": True, "provider_ready": True, "blocked_reasons": [], "queue_depth": 0,
          "oldest_unacked_ms": None}
ERROR = {"code": "NOT_FOUND", "message": "No such resource.", "correlation_id": uid(2),
         "retryable": False}
TRANSMISSION = {"request_id": uid(3), "peer_id": "peer-1",
                "expires_at": "2026-10-04T12:00:10.000Z", "policy_revision": "p1", "report": {}}


def refusal(function, document):
    with pytest.raises(ContractError) as caught:
        function(document)
    return caught.value.code, caught.value.path, caught.value.rule


def changed(document, **changes):
    out = copy.deepcopy(document)
    for key, value in changes.items():
        if value is KeyError:
            del out[key]
        else:
            out[key] = value
    return out


def test_each_valid_message_is_accepted():
    capabilities = contract.validate_capabilities(CAPABILITIES)
    assert (capabilities.gateway_id, capabilities.max_batch,
            capabilities.replay_window_seconds) == ("synthetic-gateway-1", 1000, 86400)
    assert contract.validate_status(STATUS) is STATUS
    assert contract.validate_health(HEALTH) is HEALTH
    assert contract.validate_error(ERROR) is ERROR
    assert contract.validate_error(dict(ERROR, earliest_cursor="1.0"))
    assert contract.validate_transmission(TRANSMISSION) is TRANSMISSION
    assert contract.validate_ack({"consumer_id": "consumer-1", "cursor": "1.4"})


@pytest.mark.parametrize("function, document, expected", [
    (contract.validate_capabilities, changed(CAPABILITIES, replay_window_seconds=KeyError),
     ("SCHEMA_INVALID", "replay_window_seconds", "required")),
    (contract.validate_capabilities, changed(CAPABILITIES, max_batch=1001),
     ("SCHEMA_INVALID", "max_batch", "integer in range")),
    (contract.validate_capabilities, changed(CAPABILITIES, max_batch=True),
     ("SCHEMA_INVALID", "max_batch", "integer in range")),
    (contract.validate_capabilities, changed(CAPABILITIES, profile="sc-link16-gateway/2.0.0"),
     ("SCHEMA_INVALID", "profile", "const")),
    (contract.validate_capabilities, changed(CAPABILITIES, gateway_id="gw\n"),
     ("SCHEMA_INVALID", "gateway_id", "identifier pattern")),
    (contract.validate_capabilities, changed(CAPABILITIES, extra=1),
     ("SCHEMA_INVALID", "", "a key the schema does not define")),
    (contract.validate_capabilities, changed(CAPABILITIES, native_profiles=[""]),
     ("SCHEMA_INVALID", "native_profiles[0]", "string length")),
    (contract.validate_status, changed(STATUS, state="DELIVERED"),
     ("SCHEMA_INVALID", "state", "enum")),
    (contract.validate_status, changed(STATUS, request_id="ABCDEF00-0000-4000-8000-000000000001"),
     ("SCHEMA_INVALID", "request_id", "canonical lowercase UUID")),
    (contract.validate_status, changed(STATUS, changed_at="2026-10-04T24:00:00.000Z"),
     ("SCHEMA_INVALID", "changed_at", "YYYY-MM-DDTHH:mm:ss.sssZ on a strict calendar")),
    (contract.validate_status, changed(STATUS, reason=""),
     ("SCHEMA_INVALID", "reason", "string length")),
    (contract.validate_health, changed(HEALTH, queue_depth=-1),
     ("SCHEMA_INVALID", "queue_depth", "integer in range")),
    (contract.validate_error, changed(ERROR, retryable="no"),
     ("SCHEMA_INVALID", "retryable", "type boolean")),
    (contract.validate_transmission, changed(TRANSMISSION, report=[]),
     ("SCHEMA_INVALID", "report", "a JSON object")),
    (contract.validate_transmission, changed(TRANSMISSION, expires_at="2026-10-04T12:00:10Z"),
     ("SCHEMA_INVALID", "expires_at", "YYYY-MM-DDTHH:mm:ss.sssZ on a strict calendar")),
    (contract.validate_ack, {"consumer_id": "c", "cursor": ""},
     ("SCHEMA_INVALID", "cursor", "string length")),
])
def test_each_message_refusal_names_code_path_and_rule(function, document, expected):
    assert refusal(function, document) == expected


def test_notices_of_every_operation_are_accepted():
    old = {"tenant": "demo", "realm": "test-only", "synthetic": True,
           "origin_scope": "exercise-source-1", "track_number": "TEST-0001", "incarnation": "0"}
    new = dict(old, track_number="TEST-0002")
    assert contract.validate_notice(notice(1, "DROP_SOURCE"))
    assert contract.validate_notice(notice(1, "REKEY", old_identity=old, new_identity=new))
    assert contract.validate_notice(notice(1, "GAP", track_number=None, incarnation=None))
    assert contract.validate_notice(notice(1, "RESET_SCOPE", track_number=None, incarnation=None))


OLD = {"tenant": "demo", "realm": "test-only", "synthetic": True,
       "origin_scope": "exercise-source-1", "track_number": "TEST-0001", "incarnation": "0"}


@pytest.mark.parametrize("document, expected", [
    (notice(1, "REKEY"), ("SCHEMA_INVALID", "old_identity", "required for REKEY")),
    (notice(1, "REKEY", old_identity=OLD), ("SCHEMA_INVALID", "new_identity",
                                            "required for REKEY")),
    (notice(1, "REKEY", old_identity=OLD, new_identity=dict(OLD, extra=1)),
     ("SCHEMA_INVALID", "new_identity", "a key the schema does not define")),
    (notice(1, "DROP_SOURCE", old_identity=OLD),
     ("SCHEMA_INVALID", "old_identity", "only REKEY carries identity objects")),
    (notice(1, "GAP"), ("SCHEMA_INVALID", "track_number", "null for a channel-scoped notice")),
    (notice(1, "RESET_SCOPE", track_number=None),
     ("SCHEMA_INVALID", "incarnation", "null for a channel-scoped notice")),
    (notice(1, "DROP_SOURCE", track_number=None), ("SCHEMA_INVALID", "track_number",
                                                   "type string")),
    (notice(1, "DROP_SOURCE", incarnation="01"),
     ("SCHEMA_INVALID", "incarnation", "decimal uint64 without leading zeroes")),
    (notice(1, "DROP_SOURCE", incarnation="18446744073709551616"),
     ("SCHEMA_INVALID", "incarnation", "decimal uint64 without leading zeroes")),
    (notice(1, "DROP_SOURCE", sequence="１"),
     ("SCHEMA_INVALID", "sequence", "decimal uint64 without leading zeroes")),
    (notice(1, "DELETE"), ("SCHEMA_INVALID", "operation", "enum")),
    (notice(1, "DROP_SOURCE", reason=""), ("SCHEMA_INVALID", "reason", "string length")),
    (notice(1, "DROP_SOURCE", tenant="demo\n"), ("SCHEMA_INVALID", "tenant",
                                                 "identifier pattern")),
    (notice(1, "DROP_SOURCE", record_id="ABCDEF00-0000-4000-8000-000000000001"),
     ("SCHEMA_INVALID", "record_id", "canonical lowercase UUID")),
    (dict(notice(1, "DROP_SOURCE"), gateway_id="gw"),
     ("SCHEMA_INVALID", "", "a key the schema does not define")),
    (notice(1, "DROP_SOURCE", effective_at="2026-10-04T24:00:00.000Z"),
     ("TIME_UNRESOLVED", "effective_at", "YYYY-MM-DDTHH:mm:ss.sssZ on a strict calendar")),
    (notice(1, "DROP_SOURCE", received_at="2026-10-04T12:00:60.000Z"),
     ("TIME_UNRESOLVED", "received_at", "YYYY-MM-DDTHH:mm:ss.sssZ on a strict calendar")),
])
def test_notice_schema_rules(document, expected):
    assert refusal(contract.validate_notice, document) == expected


def test_a_notice_refusal_never_quotes_the_payload():
    document = notice(1, "DROP_SOURCE", reason="")
    document["tenant"] = "PAYLOAD-MARKER\n"
    with pytest.raises(ContractError) as caught:
        contract.validate_notice(document)
    assert "PAYLOAD-MARKER" not in str(caught.value)


@pytest.mark.skipif(REPO is None, reason="repository-bound: the published schemas under "
                                         "schemas/link16_gateway/ exist only in a checkout")
@pytest.mark.parametrize("name, literal", [("api", contract.API_SCHEMA),
                                           ("notice", contract.NOTICE_SCHEMA)])
def test_the_schema_literals_are_the_published_schemas(name, literal):
    published = json.loads((REPO / "schemas" / "link16_gateway" / f"{name}.schema.json")
                           .read_text(encoding="utf-8"))
    assert literal == published


def test_the_literals_carry_the_contract_ids_and_the_required_replay_window():
    assert contract.API_SCHEMA["$id"] == "urn:synapsecommand:sc-link16-gateway:api:1.0.0"
    assert contract.NOTICE_SCHEMA["$id"] == "urn:synapsecommand:sc-link16-gateway:notice:1.0.0"
    assert "replay_window_seconds" in \
        contract.API_SCHEMA["$defs"]["capabilities"]["required"]
    assert sorted(contract.API_SCHEMA["$defs"]) == ["ack", "batch", "capabilities", "error",
                                                     "health", "status", "transmission"]
