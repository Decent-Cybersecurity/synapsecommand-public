"""The strict reader of API bodies and the batch parser (REQ061, REQ065, C03 and C04 at the
runtime, X12, X13, critic amendments 10 and 15)."""
import json
import random
import re

import pytest

from helpers import report
from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.jsonstrict import ContractError, canonical, loads, parse_batch

SESSION = "22222222-2222-4222-8222-222222222222"


def batch(*bodies: bytes, session: str = SESSION, kinds=None) -> bytes:
    kinds = kinds or ["report"] * len(bodies)
    items = b",".join(b'{"kind":"' + k.encode() + b'","body":' + b + b"}"
                      for k, b in zip(kinds, bodies))
    return (b'{"session_id":"' + session.encode() + b'","records":[' + items +
            b'],"next_cursor":"1.3","has_more":false}')


def body_of(n: int) -> bytes:
    return canonical(report(n))


def test_canonical_is_sorted_compact_utf8():
    assert canonical({"b": 1, "a": "é", "c": [1.5, None, True]}) == \
        b'{"a":"\xc3\xa9","b":1,"c":[1.5,null,true]}'


@pytest.mark.parametrize("octets, code, rule", [
    (b"\xef\xbb\xbf{}", "JSON_INVALID", "byte order mark"),
    (b'{"a":"\xff"}', "JSON_INVALID", "not UTF-8"),
    (b'{"a":1,"a":2}', "JSON_INVALID", "duplicate object key"),
    (b'{"a":NaN}', "JSON_INVALID", "non-finite number literal"),
    (b'{"a":Infinity}', "JSON_INVALID", "non-finite number literal"),
    (b'{"a":-Infinity}', "JSON_INVALID", "non-finite number literal"),
    (b'{"a":"\\ud800"}', "JSON_INVALID", "lone surrogate"),
    (b'{"\\udc00":1}', "JSON_INVALID", "lone surrogate"),
    (b'{"a":9007199254740993}', "JSON_INVALID", "integer not exactly representable as a double"),
    (b'{"a":1e400}', "JSON_INVALID", "number overflows a finite double"),
    (b'{"a":1e-400}', "JSON_INVALID", "number underflows a double to zero"),
    (b'{"a":1', "JSON_INVALID", "not a JSON text"),
    (b"[" * 33 + b"]" * 33, "LIMIT_EXCEEDED", "nesting above 32"),
])
def test_loads_refuses_every_strictness_case_with_its_rule(octets, code, rule):
    with pytest.raises(ContractError) as caught:
        loads(octets)
    assert (caught.value.code, caught.value.path, caught.value.rule) == (code, "", rule)


def test_loads_accepts_what_every_reader_reads_alike():
    assert loads(b'{"a":0.0,"b":-0,"c":9007199254740992,"d":"\\u00e9","e":1e-300}') == \
        {"a": 0.0, "b": 0, "c": 9007199254740992, "d": "é", "e": 1e-300}
    assert loads(b"[" * 32 + b"]" * 32) is not None


def test_a_body_above_8_mib_is_refused_before_it_is_decoded():
    octets = b'"' + b"a" * (8 * 1024 * 1024) + b'"'
    with pytest.raises(ContractError) as caught:
        loads(octets)
    assert (caught.value.code, caught.value.rule) == ("LIMIT_EXCEEDED", "body above 8 MiB")


def test_a_refusal_message_never_quotes_the_value():
    with pytest.raises(ContractError) as caught:
        loads(b'{"a":"VALUE-OF-THE-PAYLOAD","a":"VALUE-OF-THE-PAYLOAD"}')
    assert "VALUE-OF-THE-PAYLOAD" not in str(caught.value)
    assert str(caught.value) == "JSON_INVALID: (body) — duplicate object key"


def test_a_sound_batch_parses_record_by_record():
    parsed = parse_batch(batch(body_of(1), body_of(2), kinds=["report", "report"]))
    assert parsed.session_id == SESSION and parsed.next_cursor == "1.3" and not parsed.has_more
    assert [(r.index, r.kind, r.fault, r.record_id) for r in parsed.records] == [
        (0, "report", None, "00000000-0000-4000-8000-000000000001"),
        (1, "report", None, "00000000-0000-4000-8000-000000000002")]
    assert parsed.records[0].digest == jsonstrict.sha256_hex(body_of(1))


@pytest.mark.parametrize("fault, rule", [
    (b'{"a":1,"a":1}', "duplicate object key"),
    (b'{"a":NaN}', "non-finite number literal"),
    (b'{"a":"\\udfff"}', "lone surrogate"),
    (b'{"a":18446744073709551615}', "integer not exactly representable as a double"),
    (b'{"a":[1,{"b":2,"b":3}]}', "duplicate object key"),
])
def test_a_fault_inside_one_body_marks_that_record_and_the_rest_parse(fault, rule):
    parsed = parse_batch(batch(body_of(1), fault, body_of(3)))
    assert [r.fault for r in parsed.records] == [None, rule, None]
    assert parsed.records[1].body is None and parsed.records[1].record_id is None
    assert parsed.records[0].body["record_id"].endswith("0001")


def test_the_digest_of_a_faulty_body_is_stable_and_distinguishes_bodies():
    one = parse_batch(batch(b'{"a":1,"a":1}')).records[0].digest
    again = parse_batch(batch(b'{"a":1,"a":1}')).records[0].digest
    other = parse_batch(batch(b'{"a":1,"a":2}')).records[0].digest
    assert one == again != other


@pytest.mark.parametrize("octets, code, path, rule", [
    (b"\xef\xbb\xbf" + batch(), "JSON_INVALID", "", "byte order mark"),
    (batch(b'{"a":"\xff"}'), "JSON_INVALID", "", "not UTF-8"),
    (b"[]", "SCHEMA_INVALID", "", "the batch is not one JSON object"),
    (b'{"session_id":"x","session_id":"y"}', "JSON_INVALID", "",
     "the batch is not one JSON object"),
    (batch() + b"x", "JSON_INVALID", "", "not a JSON text"),
    (b'{"session_id":"' + SESSION.encode() + b'","records":[],"next_cursor":"1.0"}',
     "SCHEMA_INVALID", "", "batch keys are not exactly the API's"),
    (batch(session="ABCDEF12-2222-4222-8222-222222222222"), "SCHEMA_INVALID", "session_id",
     "canonical lowercase UUID"),
    (batch().replace(b'"1.3"', b'""'), "SCHEMA_INVALID", "next_cursor",
     "string of 1 to 512 characters"),
    (batch().replace(b"false", b'"false"'), "SCHEMA_INVALID", "has_more", "boolean"),
    (batch(body_of(1)).replace(b'"kind":"report"', b'"kind":"other"'), "SCHEMA_INVALID",
     "records[0].kind", "report or notice"),
    (batch(b'"text"'), "SCHEMA_INVALID", "records[0].body", "a JSON object"),
    (batch(b"[]"), "SCHEMA_INVALID", "records[0].body", "a JSON object"),
    (batch(body_of(1)).replace(b'"kind":"report",', b'"kind":"report","extra":1,'),
     "SCHEMA_INVALID", "records[0]", "a record is exactly kind and body"),
    (batch(*[b"{}"] * 1001), "LIMIT_EXCEEDED", "records", "more than 1000 records"),
])
def test_a_fault_outside_every_body_makes_the_batch_structurally_invalid(octets, code, path,
                                                                         rule):
    with pytest.raises(ContractError) as caught:
        parse_batch(octets)
    assert (caught.value.code, caught.value.path, caught.value.rule) == (code, path, rule)


def test_a_record_of_another_session_makes_the_batch_structurally_invalid():
    other = canonical(dict(report(1), session_id="33333333-3333-4333-8333-333333333333"))
    with pytest.raises(ContractError) as caught:
        parse_batch(batch(other))
    assert (caught.value.code, caught.value.path) == ("SCHEMA_INVALID", "records[0].body.session_id")


def nested(depth: int) -> bytes:
    """A JSON object nesting `depth` containers (the root object counts one)."""
    return b'{"x":' * (depth - 1) + b"{}" + b"}" * (depth - 1)


@pytest.mark.parametrize("depth", [32, 33, 64])
def test_bodies_up_to_64_deep_parse_and_are_judged_per_record(depth):
    parsed = parse_batch(batch(nested(depth)))
    assert parsed.records[0].fault is None


def test_a_body_deeper_than_64_makes_its_batch_structurally_invalid():
    with pytest.raises(ContractError) as caught:
        parse_batch(batch(nested(65)))
    assert (caught.value.code, caught.value.rule) == ("LIMIT_EXCEEDED", "nesting above 67")


_PATH = re.compile(r"\(body\)|session_id|next_cursor|has_more|records"
                   r"|records\[[0-9]+\](\.kind|\.body|\.body\.session_id)?")
_RULES = {"byte order mark", "not UTF-8", "nesting above 67", "not a JSON text",
          "the batch is not one JSON object", "batch keys are not exactly the API's",
          "canonical lowercase UUID", "string of 1 to 512 characters", "boolean", "array",
          "more than 1000 records", "a record is exactly kind and body", "report or notice",
          "a JSON object", "a record of another session inside this batch", "body above 8 MiB"}


def test_seeded_mutation_fuzz_of_the_batch_parser_refuses_only_with_its_vocabulary():
    """Amendment 10: a fixed seed derives byte mutations of a sound batch; each one parses or is
    refused as ContractError, never another exception, and every refusal message is a code, a
    schema path and a fixed rule phrase — never a value from the input."""
    rng = random.Random(20261011)
    sound = batch(body_of(1), canonical(report(2, base="surface_zero.json")))
    keys = [m.start() for m in re.finditer(rb'"[a-z_]+":', sound)]
    outcomes = {"parsed": 0, "refused": 0}
    for _ in range(600):
        octets = bytearray(sound)
        operation = rng.choice(("flip", "insert", "delete", "truncate", "duplicate"))
        at = rng.randrange(len(octets))
        if operation == "flip":
            octets[at] ^= 1 << rng.randrange(8)
        elif operation == "insert":
            octets[at:at] = bytes([rng.randrange(256)])
        elif operation == "delete":
            del octets[at]
        elif operation == "truncate":
            del octets[at:]
        else:
            start = rng.choice(keys)
            end = octets.find(b",", start) + 1
            octets[start:start] = octets[start:end]
        try:
            parse_batch(bytes(octets))
            outcomes["parsed"] += 1
        except ContractError as error:
            outcomes["refused"] += 1
            assert error.code in ("JSON_INVALID", "SCHEMA_INVALID", "LIMIT_EXCEEDED")
            assert _PATH.fullmatch(error.path or "(body)"), error.path
            assert error.rule in _RULES, error.rule
            assert str(error) == f"{error.code}: {error.path or '(body)'} — {error.rule}"
    assert outcomes["parsed"] > 0 and outcomes["refused"] > 0
    assert json.loads(sound)["records"][0]["body"]["record_id"].endswith("1")
