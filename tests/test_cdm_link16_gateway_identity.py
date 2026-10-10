"""`link16_gateway` identity (the handoff's REQ070–REQ074; acceptance rows I01 and I02).

The canonical identity tuple is `[tenant, realm, synthetic, origin_scope, track_number,
incarnation]`, serialised as compact JSON with `ensure_ascii` and never sorted; `entity_id` and
`track_id` are uuid5 under the repository namespace of `entity|Link16Track|<tuple>` and
`track|Link16Track|<tuple>`. Every expected identifier below is recomputed here from those input
strings with the standard library's `uuid`, or quoted from the handoff's own reference
projections — never read from the adapter. Reporter, session, gateway, record, sequence and
receipt time are provenance and must never move an identifier.

PACKAGE-ONLY: the adapter and its packaged fixtures are all this module reads.
"""
from __future__ import annotations

import json
import pathlib
import uuid

import pytest
import synapse_cdm
from synapse_cdm import harness

from synapse_cdm.adapters.link16_gateway import IDENTITY_KEYS, Link16GatewayAdapter, identity_key

SET = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "link16_gateway"
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")

#: The handoff's reference projections give these for its six examples (one identity tuple).
HANDOFF_TUPLE = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
HANDOFF_ENTITY_ID = "fbaab310-0fe0-5c9f-ade3-4d81fb6b3f71"
HANDOFF_TRACK_ID = "5d6324f0-8ab3-5fdb-b8e5-d9081c92471b"


def reference_ids(tuple_text: str) -> tuple[str, str]:
    """The rule as the specification states it, on its own input strings."""
    return (str(uuid.uuid5(NAMESPACE, f"entity|Link16Track|{tuple_text}")),
            str(uuid.uuid5(NAMESPACE, f"track|Link16Track|{tuple_text}")))


def base() -> dict:
    return json.loads((SET / "air_sensor.json").read_bytes())


def ids_of(doc: dict, *, synthetic: bool = True) -> tuple[str, str]:
    entity, track = Link16GatewayAdapter(synthetic=synthetic).to_cdm(doc)
    return str(entity.entity_id), str(track.track_id)


def test_identity_key_is_compact_ensure_ascii_in_tuple_order():
    assert IDENTITY_KEYS == ("tenant", "realm", "synthetic", "origin_scope", "track_number",
                             "incarnation")
    assert identity_key(base()) == HANDOFF_TUPLE
    doc = base()
    doc.update(tenant="b", realm="a", track_number="TN-é-☃", incarnation="18446744073709551615")
    assert identity_key(doc) == \
        '["b","a",true,"exercise-source-1","TN-\\u00e9-\\u2603","18446744073709551615"]'
    doc["track_number"] = "\U0001f600"
    assert identity_key(doc).split(",")[4] == '"\\ud83d\\ude00"'


def test_the_handoff_identifiers_are_reproduced():
    assert reference_ids(HANDOFF_TUPLE) == (HANDOFF_ENTITY_ID, HANDOFF_TRACK_ID)
    assert ids_of(base()) == (HANDOFF_ENTITY_ID, HANDOFF_TRACK_ID)


@pytest.mark.parametrize("name", [p.name for p in harness.select_fixtures(SET)])
def test_ids_derive_matches_the_reference_rule_on_every_fixture(name):
    raw = harness.load_raw(SET / name)
    doc = json.loads((SET / name).read_bytes())
    tuple_text = json.dumps([doc[k] for k in IDENTITY_KEYS], ensure_ascii=True,
                            separators=(",", ":"))
    entity_id, track_id = reference_ids(tuple_text)
    objects = Link16GatewayAdapter().to_cdm(raw)
    assert str(objects[0].entity_id) == entity_id
    assert [(s.system, s.external_id) for s in objects[0].source_ids] == \
        [("Link16Track", tuple_text)]
    if len(objects) == 2:
        assert str(objects[1].track_id) == track_id
        assert objects[1].entity_id == objects[0].entity_id
        assert [(s.system, s.external_id) for s in objects[1].source_ids] == \
            [("Link16Track", tuple_text)]


def test_the_unicode_fixture_has_these_identifiers():
    """Recomputed by hand on 2026-10-10 from the tuple text below."""
    tuple_text = ('["demo","test-only",true,"exercise-source-1","TN-\\u00e9-\\u2603",'
                  '"18446744073709551615"]')
    assert reference_ids(tuple_text) == ("2ec2d3ed-5c40-54a5-8dfa-5736f1b47cdd",
                                         "643ffe9a-71ab-5670-9392-a60aedbb53a6")
    for name in ("unknown_domain_poles_uint64_unicode.json",
                 "unknown_domain_poles_uint64_unicode_octets.bin"):
        entity, track = Link16GatewayAdapter().to_cdm(harness.load_raw(SET / name))
        assert entity.source_ids[0].external_id == tuple_text
        assert (str(entity.entity_id), str(track.track_id)) == \
            ("2ec2d3ed-5c40-54a5-8dfa-5736f1b47cdd", "643ffe9a-71ab-5670-9392-a60aedbb53a6")


PROVENANCE_ONLY = {
    "session_id": "33333333-3333-4333-8333-333333333333",    # a reconnect opens a new session
    "reporter": "SIMULATED-RELAY-2",                         # a second participant relays it
    "gateway_id": "synthetic-gateway-2",
    "record_id": "44444444-4444-4444-8444-444444444444",
    "sequence": "981",
    "received_at": "2026-10-04T12:00:07.500Z",
}


@pytest.mark.parametrize("key", sorted(PROVENANCE_ONLY))
def test_reconnect_and_changed_reporter_keep_ids(key):
    doc = base()
    doc[key] = PROVENANCE_ONLY[key]
    assert ids_of(doc) == (HANDOFF_ENTITY_ID, HANDOFF_TRACK_ID)


def test_all_provenance_changed_at_once_keeps_ids():
    doc = base()
    doc.update(PROVENANCE_ONLY)
    doc["message_family"] = "J3.3"
    doc["native_profile"] = "SYNTHETIC-OTHER-PROFILE"
    doc["domain"] = "SURFACE"
    assert ids_of(doc) == (HANDOFF_ENTITY_ID, HANDOFF_TRACK_ID)


TUPLE_MEMBERS = {
    "tenant": "demo-2",
    "realm": "test-only-2",
    "origin_scope": "exercise-source-2",
    "track_number": "TEST-0002",
    "incarnation": "1",
}


@pytest.mark.parametrize("key", sorted(TUPLE_MEMBERS))
def test_each_tuple_member_changes_both_ids(key):
    doc = base()
    doc[key] = TUPLE_MEMBERS[key]
    expected = reference_ids(identity_key(doc))
    got = ids_of(doc)
    assert got == expected
    assert got[0] != HANDOFF_ENTITY_ID and got[1] != HANDOFF_TRACK_ID


def test_the_synthetic_layer_is_a_tuple_member():
    doc = base()
    doc["synthetic"] = False
    got = ids_of(doc, synthetic=False)
    assert got[0] == "a1d42383-d001-55ab-9f09-e49bc6d2a668"     # recomputed by hand, 2026-10-10
    assert got == reference_ids('["demo","test-only",false,"exercise-source-1","TEST-0001","0"]')
    assert got[0] != HANDOFF_ENTITY_ID


def test_identical_track_numbers_in_two_realms_or_layers_never_collide():
    seen = {}
    for realm in ("test-only", "test-only-b"):
        for synthetic in (True, False):
            for scope in ("exercise-source-1", "exercise-source-2"):
                doc = base()
                doc.update(realm=realm, synthetic=synthetic, origin_scope=scope)
                seen[(realm, synthetic, scope)] = ids_of(doc, synthetic=synthetic)
    assert len({e for e, _t in seen.values()}) == len(seen) == 8
    assert len({t for _e, t in seen.values()}) == 8


def test_entity_and_track_ids_differ_and_track_points_to_entity():
    entity, track = Link16GatewayAdapter().to_cdm(base())
    assert entity.entity_id != track.track_id
    assert track.entity_id == entity.entity_id
    assert entity.entity_id.version == track.track_id.version == 5


def test_ids_are_uuid5_and_stable_across_fresh_instances():
    for path in harness.select_fixtures(SET):
        raw = harness.load_raw(path)
        first = [o.model_dump(mode="json") for o in Link16GatewayAdapter().to_cdm(raw)]
        second = [o.model_dump(mode="json") for o in Link16GatewayAdapter().to_cdm(raw)]
        assert first == second
        assert uuid.UUID(first[0]["entity_id"]).version == 5


def test_a_positionless_report_has_the_same_entity_id_and_no_track():
    doc = base()
    doc["position"] = None
    objects = Link16GatewayAdapter().to_cdm(doc)
    assert [o.object_kind for o in objects] == ["entity"]
    assert str(objects[0].entity_id) == HANDOFF_ENTITY_ID
