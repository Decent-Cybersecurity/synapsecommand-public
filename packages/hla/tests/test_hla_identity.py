"""R26: the external_id and entity_id of an observed object (`synapse_hla._identity`).

Gate held here: G-R26 (SPEC:130; it has no continuation paragraph), at the level of the identity
functions. `test_hla_projector.py` holds the same gate through `project_state`: what does not
enter identity, and the identities of the Entities it emits.

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
- `identity.json`: the packaged fixture, its one vector.
- external_id strings written out by hand from R26's rule (six decimal strings in a JSON array,
  no spaces).
- entity_id values derived in the test by `hla_support.rfc4122_uuid5`, an independent spelling
  of RFC 4122's name-based UUID (SHA-1, version 5, variant 10), first checked against the
  fixture vector; and, as R3's brief asks, `synapse_cdm.ids.derive("hla-rpr2", external_id)` of
  the SDK must agree with both.
"""

import inspect
import random
import re
import uuid

import pytest
from synapse_cdm import ids

from hla_support import case, fixture_json, rfc4122_uuid5
from synapse_hla import _identity

NAMESPACE_TEXT = "6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50"
#: A version 5, variant 10 UUID in lowercase canonical form.
CANONICAL_UUID5 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def ident(site, application, entity):
    return {"site": site, "application": application, "entity": entity}


@case("G-R26")
def test_the_identity_fixture_vector():
    """identity.json: the namespace, the external_id of session example-001, generation 1,
    identifier 1.2.3, incarnation 1, and its entity_id."""
    vector = fixture_json("identity.json")
    assert vector["uuid_namespace"] == NAMESPACE_TEXT
    external = _identity.external_id("example-001", 1, ident(1, 2, 3), 1)
    assert external == vector["external_id"] == '["example-001","1","1","2","3","1"]'
    assert _identity.entity_id(external) == vector["entity_id"] == \
        "781e68de-166f-531c-b906-4a2d087f817e"
    # The test's own RFC 4122 derivation reproduces the fixture before it judges anything else.
    assert rfc4122_uuid5(NAMESPACE_TEXT, "entity|hla-rpr2|" + external) == vector["entity_id"]


@case("G-R26")
def test_the_namespace_is_the_public_cdm_namespace():
    assert _identity.NAMESPACE == uuid.UUID(NAMESPACE_TEXT) == ids.NAMESPACE
    assert str(_identity.NAMESPACE) == NAMESPACE_TEXT
    assert (_identity.KIND, _identity.SYSTEM) == ("entity", "hla-rpr2")


#: (session_id, generation, identifier, incarnation) -> the external_id, written by hand.
VECTORS = (
    ("example-001", 1, (1, 2, 3), 1, '["example-001","1","1","2","3","1"]'),
    ("a.b_C-9", 12, (0, 65535, 7), 3, '["a.b_C-9","12","0","65535","7","3"]'),
    ("S", 9007199254740991, (65535, 0, 0), 9007199254740991,
     '["S","9007199254740991","65535","0","0","9007199254740991"]'),
    ("x" * 64, 2, (0, 0, 1), 1, '["' + "x" * 64 + '","2","0","0","1","1"]'),
    ("-._", 10, (1, 0, 0), 100, '["-._","10","1","0","0","100"]'),
)


@case("G-R26")
@pytest.mark.parametrize("session_id,generation,triple,incarnation,external", VECTORS,
                         ids=[f"v{i}" for i in range(len(VECTORS))])
def test_external_id_and_entity_id_by_r26(session_id, generation, triple, incarnation, external):
    """R26: six strings, canonical JSON without spaces; UUIDv5 of 'entity|hla-rpr2|' + it,
    lowercase canonical; the same value from the SDK's `ids.derive` and from RFC 4122 by hand."""
    got = _identity.external_id(session_id, generation, ident(*triple), incarnation)
    assert got == external
    assert got.isascii() and " " not in got
    expected_id = rfc4122_uuid5(NAMESPACE_TEXT, "entity|hla-rpr2|" + external)
    got_id = _identity.entity_id(got)
    assert got_id == expected_id == str(ids.derive("hla-rpr2", external))
    assert CANONICAL_UUID5.fullmatch(got_id)
    assert _identity.parts(got) == (session_id, generation, *triple, incarnation)


@case("G-R26")
def test_sessions_generations_and_incarnations_do_not_merge():
    """R26: 'different sessions, generations or incarnations do not merge', and the same
    lifecycle gives the same id every time. Changing any one of the six values changes the id."""
    base = ("example-001", 1, (1, 2, 3), 1)
    variants = [base, ("example-002", 1, (1, 2, 3), 1), ("example-001", 2, (1, 2, 3), 1),
                ("example-001", 1, (1, 2, 3), 2), ("example-001", 1, (2, 2, 3), 1),
                ("example-001", 1, (1, 3, 3), 1), ("example-001", 1, (1, 2, 4), 1),
                ("example-001", 1, (3, 2, 1), 1)]
    found = [_identity.entity_id(_identity.external_id(s, g, ident(*t), i))
             for s, g, t, i in variants]
    assert len(set(found)) == len(variants)
    again = _identity.entity_id(_identity.external_id("example-001", 1, ident(1, 2, 3), 1))
    assert again == found[0] == "781e68de-166f-531c-b906-4a2d087f817e"


@case("G-R26")
def test_nothing_but_the_six_values_can_enter_identity():
    """R26: 'Runtime handles, names, class, position and force do not enter identity': the
    identity functions take the session, the generation, the identifier and the incarnation,
    and nothing else (test_hla_projector holds the same through project_state)."""
    assert list(inspect.signature(_identity.external_id).parameters) == [
        "session_id", "generation", "identifier", "incarnation"]
    assert list(inspect.signature(_identity.entity_id).parameters) == ["external"]


@case("G-R26")
def test_an_hla_identity_is_never_another_protocols():
    """R26: cross-protocol DIS/HLA identity correlation is outside this adapter. The UUID name
    is scoped to the issuing system hla-rpr2, so the same six values issued by any other system
    name, or the bare triple, give another id."""
    external = _identity.external_id("example-001", 1, ident(1, 2, 3), 1)
    ours = _identity.entity_id(external)
    for system in ("dis7", "dis", "kml", "hla", "HLA-RPR2"):
        assert str(ids.derive(system, external)) != ours
    assert str(ids.derive("hla-rpr2", "1.2.3")) != ours
    assert str(ids.derive("hla-rpr2", external, kind="event")) != ours


#: (call, exception): every refusal of a caller's value. Wrong Python types are TypeError,
#: values outside R26's domain ValueError; neither is HlaError (no input here is from the wire).
REFUSALS = (
    (lambda: _identity.external_id(1, 1, ident(1, 2, 3), 1), TypeError),
    (lambda: _identity.external_id(b"s", 1, ident(1, 2, 3), 1), TypeError),
    (lambda: _identity.external_id("", 1, ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("a b", 1, ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("x" * 65, 1, ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("caf\N{LATIN SMALL LETTER E WITH ACUTE}", 1,
                                   ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("a\N{RIGHT-TO-LEFT OVERRIDE}", 1, ident(1, 2, 3), 1),
     ValueError),
    (lambda: _identity.external_id("a\n", 1, ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("s", 0, ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("s", -1, ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("s", 2 ** 53, ident(1, 2, 3), 1), ValueError),
    (lambda: _identity.external_id("s", True, ident(1, 2, 3), 1), TypeError),
    (lambda: _identity.external_id("s", 1.0, ident(1, 2, 3), 1), TypeError),
    (lambda: _identity.external_id("s", "1", ident(1, 2, 3), 1), TypeError),
    (lambda: _identity.external_id("s", 1, ident(0, 0, 0), 1), ValueError),
    (lambda: _identity.external_id("s", 1, ident(65536, 0, 1), 1), ValueError),
    (lambda: _identity.external_id("s", 1, ident(-1, 0, 1), 1), ValueError),
    (lambda: _identity.external_id("s", 1, ident(True, 0, 1), 1), TypeError),
    (lambda: _identity.external_id("s", 1, ident(1.0, 0, 1), 1), TypeError),
    (lambda: _identity.external_id("s", 1, {"site": 1, "application": 2}, 1), ValueError),
    (lambda: _identity.external_id("s", 1, {**ident(1, 2, 3), "x": 0}, 1), ValueError),
    (lambda: _identity.external_id("s", 1, [1, 2, 3], 1), TypeError),
    (lambda: _identity.external_id("s", 1, None, 1), TypeError),
    (lambda: _identity.external_id("s", 1, ident(1, 2, 3), 0), ValueError),
    (lambda: _identity.external_id("s", 1, ident(1, 2, 3), 2 ** 53), ValueError),
    (lambda: _identity.external_id("s", 1, ident(1, 2, 3), None), TypeError),
    (lambda: _identity.entity_id(None), TypeError),
    (lambda: _identity.entity_id(b'["s","1","1","2","3","1"]'), TypeError),
    (lambda: _identity.entity_id('["s","1","1","2","3"]'), ValueError),
    (lambda: _identity.entity_id('["s","01","1","2","3","1"]'), ValueError),
    (lambda: _identity.entity_id('["s", "1","1","2","3","1"]'), ValueError),
    (lambda: _identity.entity_id('["s","1","1","2","3","1"]\n'), ValueError),
    (lambda: _identity.entity_id('["s","1","1","2","3",1]'), ValueError),
    (lambda: _identity.entity_id("[\"s\",\"1\",\"1\",\"2\",\"3\",\"1\",\"1\"]"), ValueError),
    (lambda: _identity.parts('["a b","1","1","2","3","1"]'), ValueError),
    (lambda: _identity.parts(7), TypeError),
)


@case("G-R26")
@pytest.mark.parametrize("call,exception", REFUSALS, ids=[f"r{i}" for i in range(len(REFUSALS))])
def test_values_outside_r26_are_caller_bugs(call, exception):
    """The null identifier 0.0.0 never becomes an identity (R19, SPEC:281); everything else in
    this table is outside the domain the configuration and the capture already enforce."""
    with pytest.raises(exception) as info:
        call()
    assert type(info.value) is exception


def _hostile():
    """A fresh list on every call: values a Python caller could pass for any argument."""
    from collections import OrderedDict
    return [None, True, 0, -1, 1, 2 ** 53, 10 ** 5000, 1.0, float("nan"), "", "s", "a b",
            "\ud800", "\N{RIGHT-TO-LEFT OVERRIDE}", "x" * 10_000, b"s", [], [1, 2, 3], (1, 2, 3),
            {}, ident(1, 2, 3), ident(0, 0, 0), {"site": 2 ** 70, "application": 0, "entity": 0},
            OrderedDict(site=1, application=2, entity=3), object(),
            '["s","1","1","2","3","1"]', '["s","1","1","2","3","1"]\n']


@case("G-R26")
@pytest.mark.parametrize("seed", [26, 2626])
def test_hostile_values_give_an_identity_or_a_caller_bug_only(seed):
    """CR-R2-24 next to the identity functions' refusals: any mix of hostile values gives a
    str, TypeError or ValueError, never another exception."""
    rng = random.Random(seed)
    for _ in range(500):
        args = [rng.choice(_hostile()) for _ in range(4)]
        for call in (lambda: _identity.external_id(*args), lambda: _identity.entity_id(args[0]),
                     lambda: _identity.parts(args[0])):
            try:
                result = call()
            except (TypeError, ValueError) as error:
                assert type(error) in (TypeError, ValueError)
            else:
                assert type(result) in (str, tuple)
