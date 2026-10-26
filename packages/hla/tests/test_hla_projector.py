"""`project_state`: snapshot to CDM Entity or suppression (R19, R23, R26-R28, R30-R32, R44).

Gates held here, clause by clause, through `project_state` (and `decode_attribute` where the gate
is about decoding): G-R19 (with SPEC:88, SPEC:99, SPEC:281), G-R26 (the identity of emitted
Entities; the identity functions themselves are in test_hla_identity.py), G-R27 (with SPEC:134),
G-R28, G-R30 (with SPEC:146), G-R31 and G-R44; and the carried G-R08 clause of SPEC:42. The four
A- cases of section 9 (A-BODY, A-STATIC, A-ATTITUDE, A-POLE) are re-asserted on the Entity.

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
- The fixtures: `expected.observations.jsonl` (each snapshot record and the upsert after it),
  `first-upsert.entity.json`, `session.capture.jsonl` (the header's config and each triggering
  frame's seq and sha256), `identity.json`, `geodesy.json`.
- Entities other than the fixture's are the fixture's upsert with the members a test changes
  written as literals, derived by hand in the comment beside them. Hashes of new attribute bytes
  are `hashlib.sha256` of the bytes the test itself encoded (SPEC:134's definition, computed by
  the test); new entity_ids come from `hla_support.rfc4122_uuid5` (see test_hla_identity.py).
- Section 9 values off the trivial points come from decimal arithmetic at 70 digits (series
  trigonometry, the specification's WGS84 constants as exact decimals), a derivation independent
  of the product whose results and margins are written in each comment.
- Input snapshots are built by the tests' own encoders (`encode_spatial`, `struct` with
  explicit big-endian formats) together with the decoded value written out by the test; the
  projector re-decodes every VALID value and refuses a snapshot whose value is not what its
  bytes decode to, so a wrong input is caught rather than silently believed.
"""

import copy
import hashlib
import json
import math
import random
import struct
import sys
from types import MappingProxyType

import pytest
from jsonschema import Draft202012Validator
from jsonschema import validators as jsonschema_validators
from synapse_cdm import ids
from synapse_cdm.models import Entity

import synapse_hla
from hla_support import (
    PACKAGE_ROOT, SPATIAL_TABLE, CaptureBuilder, canonical, case, encode_spatial,
    event_discover, event_generation_end, event_generation_start, event_reflect,
    fixture_capture_records, fixture_json, fixture_jsonl, positive_hex, rfc4122_uuid5,
    run_python,
)
from hla_support import registry as support_registry
from hla_support import schemas as support_schemas
from synapse_hla import HlaError, _schema, _utc, decode_attribute, errors, geodesy, projector
from synapse_hla.projector import ProjectionDefect, Suppression, project_state

WGS_A = 6378137.0
WGS_F = 1 / 298.257223563
WGS_B = WGS_A * (1 - WGS_F)
WGS_E2 = WGS_F * (2 - WGS_F)
NAMESPACE = "6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50"

# ------------------------------------------------------------------------------------- fixtures

CAPTURE = fixture_capture_records()
HEADER = CAPTURE[0]
CONFIG = HEADER["config"]
FRAMES = {r["seq"]: r for r in CAPTURE if r["type"] == "frame"}
OBSERVATIONS = fixture_jsonl("expected.observations.jsonl")
FIRST_UPSERT = fixture_json("first-upsert.entity.json")
SEQ5_SHA = "06dd4f63197b1a49945cd419d4860577a7795d427a91c43afe3d8605497e2264"
PHYSICAL = "HLAobjectRoot.BaseEntity.PhysicalEntity"
EPOCH = "2026-01-01T00:00:00.000000Z"
ONE_SECOND = "2026-01-01T00:00:01.000000Z"
FIXTURE_ENTITY_ID = "781e68de-166f-531c-b906-4a2d087f817e"


def fixture_context(record: dict) -> dict:
    """RED-19's context of one expected snapshot record: the header's config and the frame."""
    frame = FRAMES[record["seq"]]
    return {"config": HEADER["config"], "generation": frame["generation"],
            "object_token": record["object_token"], "identity": record["payload"]["identity"],
            "incarnation": record["payload"]["incarnation"], "seq": frame["seq"],
            "sha256": frame["sha256"], "capture_complete": record["capture_complete"]}


def payload_bytes(obj) -> bytes:
    return canonical(obj)


def entity_of(result) -> dict:
    """The payload of a returned Entity, after checking it is one."""
    assert type(result) is Entity, result
    return json.loads(projector.entity_bytes(result))


def changed(base: dict, changes: dict) -> dict:
    """A deep copy of `base` with each `(key, key, ...) -> value` of `changes` written in."""
    out = copy.deepcopy(base)
    for path, value in changes.items():
        node = out
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return out


# ------------------------------------------------------------------------- snapshot construction

ABSENT_SLOT = {"status": "ABSENT", "value": None, "hex": None, "seq": None, "elapsed_ns": None,
               "effective_at": None}


def slot(status, value, raw: bytes, seq, elapsed_ns, effective_at):
    return {"status": status, "value": value, "hex": raw.hex(), "seq": seq,
            "elapsed_ns": elapsed_ns, "effective_at": effective_at}


def ident(site=1, application=2, entity=3):
    return {"site": site, "application": application, "entity": entity}


def ident_slot(site=1, application=2, entity=3, *, seq=3, elapsed="0", at=EPOCH):
    return slot("VALID", ident(site, application, entity),
                struct.pack(">HHH", site, application, entity), seq, elapsed, at)


def type_value(kind=1, domain=1, country=225, category=1, subcategory=2, specific=3, extra=4):
    return {"kind": kind, "domain": domain, "country": country, "category": category,
            "subcategory": subcategory, "specific": specific, "extra": extra}


def type_slot(*fields, seq=3, elapsed="0", at=EPOCH):
    value = type_value(*fields)
    raw = struct.pack(">BBHBBBB", *(value[k] for k in value))
    return slot("VALID", value, raw, seq, elapsed, at)


def force_slot(value=1, *, seq=4, elapsed="0", at=EPOCH):
    return slot("VALID", {"value": value}, bytes([value]), seq, elapsed, at)


def f32(x: float) -> float:
    return struct.unpack(">f", struct.pack(">f", x))[0]


def spatial_value(algorithm, position, orientation, velocity, acceleration, angular, frozen,
                  padding):
    """The decoded shape of a Spatial value, written by the test from SPEC:88-110."""
    for triple in (orientation, velocity, acceleration, angular):
        if triple is not None:
            assert all(f32(c) == c for c in triple), "binary32 fields must be binary32 values"
    return {"algorithm": algorithm, "frame": SPATIAL_TABLE[algorithm][0], "frozen": bool(frozen),
            "position_ecef_m": list(position), "orientation_rad": list(orientation),
            "velocity_mps": None if velocity is None else list(velocity),
            "acceleration_mps2": None if acceleration is None else list(acceleration),
            "angular_velocity_radps": None if angular is None else list(angular),
            "padding_hex": padding.hex()}


def spatial_slot(algorithm=2, position=(WGS_A, 0.0, 0.0), orientation=(0.0, 0.0, 0.0),
                 velocity=(0.0, 10.0, 0.0), acceleration=None, angular=None, *, frozen=0,
                 padding=bytes(10), seq=5, elapsed="1000000000", at=ONE_SECOND):
    raw = encode_spatial(algorithm, position, orientation, velocity, acceleration, angular,
                         frozen=frozen, padding=padding)
    value = spatial_value(algorithm, position, orientation, velocity, acceleration, angular,
                          frozen, padding)
    return slot("VALID", value, raw, seq, elapsed, at)


def invalid_slot(raw: bytes, *, seq=5, elapsed="1000000000", at=ONE_SECOND):
    return slot("INVALID", None, raw, seq, elapsed, at)


def make_snapshot(*, ei="default", et="default", force="default", spatial="default",
                  lifecycle="ACTIVE", identity="default", incarnation=1, name="SYNTHETIC-001",
                  reported_class=PHYSICAL):
    """By default the fixture's snapshot at seq 5 (a test holds the equality)."""
    attributes = {
        "EntityIdentifier": ident_slot() if ei == "default" else ei,
        "EntityType": type_slot() if et == "default" else et,
        "ForceIdentifier": force_slot() if force == "default" else force,
        "Spatial": spatial_slot() if spatial == "default" else spatial,
    }
    return {"name": name, "reported_class": reported_class, "lifecycle": lifecycle,
            "identity": ident() if identity == "default" else identity,
            "incarnation": incarnation, "attributes": attributes,
            "changed_attributes": ["Spatial"], "projection_status": "ELIGIBLE",
            "suppression_reasons": [], "last_revision": 0}


def make_context(snapshot, *, config=None, generation=1, token="o1", seq=5, sha256=SEQ5_SHA,
                 capture_complete=True):
    return {"config": copy.deepcopy(CONFIG if config is None else config),
            "generation": generation, "object_token": token,
            "identity": copy.deepcopy(snapshot["identity"]),
            "incarnation": snapshot["incarnation"], "seq": seq, "sha256": sha256,
            "capture_complete": capture_complete}


def project(snapshot, **context):
    return project_state(snapshot, make_context(snapshot, **context))


def config_with(**members) -> dict:
    out = copy.deepcopy(CONFIG)
    out.update(members)
    return out


NONE_POLICY = config_with(time_policy={"mode": "none"})


def untimed(snapshot: dict) -> dict:
    """The same state captured under time policy none: no effective time anywhere (RED-19)."""
    out = copy.deepcopy(snapshot)
    for slot_ in out["attributes"].values():
        slot_["effective_at"] = None
    return out


def raw_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def spatial_hash(snapshot) -> str:
    return raw_hash(bytes.fromhex(snapshot["attributes"]["Spatial"]["hex"]))


def entity_with_spatial(snapshot, changes: dict) -> dict:
    """FIRST_UPSERT with this snapshot's Spatial value and hash, plus `changes`."""
    spatial = snapshot["attributes"]["Spatial"]
    base = {("attributes", "hla", "spatial"): spatial["value"],
            ("attributes", "hla", "attribute_hashes", "Spatial"): spatial_hash(snapshot)}
    base.update(changes)
    return changed(FIRST_UPSERT, base)


def motion(speed, course, climb):
    return {"speed_mps": speed, "course_deg": course, "climb_mps": climb}


def where(lat, lon, alt):
    return {"lat": lat, "lon": lon, "alt_m": alt, "position_source": "ESTIMATED",
            "accuracy_m": None, "vertical": None}


NO_ENU = ["external-time-context", "ecef-to-wgs84"]
WITH_ENU = NO_ENU + ["ecef-velocity-to-enu"]


def forward(lat_deg, lon_deg, h):
    """Closed-form geodetic -> ECEF, written here (as in test_hla_geodesy.py), not the product."""
    phi, lam = math.radians(lat_deg), math.radians(lon_deg)
    n = WGS_A / math.sqrt(1 - WGS_E2 * math.sin(phi) ** 2)
    return ((n + h) * math.cos(phi) * math.cos(lam), (n + h) * math.cos(phi) * math.sin(lam),
            (n * (1 - WGS_E2) + h) * math.sin(phi))


def caller_bug(exception, call):
    with pytest.raises(exception) as info:
        call()
    assert type(info.value) is exception, type(info.value)
    return info.value


def refusal(call) -> HlaError:
    with pytest.raises(HlaError) as info:
        call()
    assert type(info.value) is HlaError
    return info.value


# ======================================================================== the fixture oracle

SNAPSHOT_INDEXES = [i for i, (_, r) in enumerate(OBSERVATIONS) if r["kind"] == "snapshot"]


def test_the_default_snapshot_is_the_fixtures_seq_5_snapshot():
    """The tests' snapshot builder reproduces the fixture's snapshot at seq 5 exactly, so every
    test that changes one member starts from the bundle's own state."""
    fixture = OBSERVATIONS[2][1]["payload"]
    assert OBSERVATIONS[2][1]["seq"] == 5
    assert payload_bytes(make_snapshot()) == payload_bytes(fixture)


@case("G-R27", "G-R30", "G-R44", paragraphs=("SPEC:134", "SPEC:146"))
@pytest.mark.parametrize("index", SNAPSHOT_INDEXES, ids=lambda i: f"line{i + 1}")
def test_each_fixture_snapshot_projects_to_its_record(index):
    """The kit's oracle, snapshot by snapshot: with the context rebuilt from the capture header
    and the triggering frame, a SUPPRESSED snapshot gives exactly its recorded reasons, and an
    ELIGIBLE one gives an Entity whose canonical payload is the following upsert's payload, byte
    for byte as it stands in the fixture line."""
    _, record = OBSERVATIONS[index]
    result = project_state(record["payload"], fixture_context(record))
    if record["payload"]["projection_status"] == "SUPPRESSED":
        assert result == Suppression(tuple(record["payload"]["suppression_reasons"]), None)
        assert result.reasons == ("MISSING_SPATIAL",)
        return
    assert record["payload"]["suppression_reasons"] == []
    upsert_line, upsert = OBSERVATIONS[index + 1]
    assert upsert["kind"] == "upsert" and upsert["seq"] == record["seq"]
    expected = payload_bytes(upsert["payload"])
    assert b'"payload":' + expected + b',"revision":' in upsert_line
    assert type(result) is Entity
    assert projector.entity_bytes(result) == expected
    assert str(result.entity_id) == upsert["entity_id"] == record["entity_id"]


@case("G-R27", "G-R44", paragraphs=("SPEC:134",))
def test_the_first_upsert_fixture_is_reproduced_byte_for_byte():
    _, record = OBSERVATIONS[2]
    result = project_state(record["payload"], fixture_context(record))
    assert projector.entity_bytes(result) == payload_bytes(FIRST_UPSERT)
    assert projector.entity_payload(result) == FIRST_UPSERT


@case("G-R44")
def test_both_fixture_upserts_construct_as_entities_and_round_trip():
    """R44: the required Python integration constructs synapse_cdm.models.Entity. Each fixture
    upsert payload, read from its line, constructs on the JSON path and dumps back to the same
    canonical bytes; and what project_state returns for it is that model type."""
    upserts = [(line, r) for line, r in OBSERVATIONS if r["kind"] == "upsert"]
    assert [r["seq"] for _, r in upserts] == [5, 6]
    for (line, upsert), index in zip(upserts, (2, 4)):
        data = payload_bytes(upsert["payload"])
        assert data in line
        model = Entity.model_validate_json(data)
        assert canonical(model.model_dump(mode="json")) == data
        _, record = OBSERVATIONS[index]
        result = project_state(record["payload"], fixture_context(record))
        assert type(result) is Entity
        assert canonical(result.model_dump(mode="json")) == data
        assert result == model


def test_the_snapshots_own_status_and_reasons_are_recomputed():
    """The input's projection_status and suppression_reasons are the reducer's copy of this
    function's answer; whatever they say, the answer is computed afresh."""
    _, record = OBSERVATIONS[2]
    lying = copy.deepcopy(record["payload"])
    lying["projection_status"] = "SUPPRESSED"
    lying["suppression_reasons"] = ["NULL_ID", "QUARANTINED"]
    result = project_state(lying, fixture_context(record))
    assert projector.entity_bytes(result) == payload_bytes(FIRST_UPSERT)
    _, early = OBSERVATIONS[0]
    lying = copy.deepcopy(early["payload"])
    lying["projection_status"] = "ELIGIBLE"
    lying["suppression_reasons"] = []
    assert project_state(lying, fixture_context(early)) == Suppression(("MISSING_SPATIAL",))


# ===================================================================== identity, R26 and R19

@case("G-R26")
def test_handles_names_class_position_and_force_do_not_enter_identity():
    """R26: 'Runtime handles, names, class, position and force do not enter identity.' The same
    identifier, session, generation and incarnation give the fixture's entity_id and external_id
    whatever the object token (the stand-in for the RTI handle), the object name, the reported
    class, the position or the force value."""
    variants = [
        (make_snapshot(), {"token": "o99"}),
        (make_snapshot(name="RENAMED"), {}),
        (make_snapshot(reported_class=PHYSICAL + ".Platform.GroundVehicle"), {}),
        (make_snapshot(spatial=spatial_slot(position=forward(30.0, 40.0, 1000.0))), {}),
        (make_snapshot(force=force_slot(0)), {}),
        (make_snapshot(force=force_slot(255)), {}),
        (make_snapshot(force=ABSENT_SLOT), {}),
    ]
    for snapshot, context in variants:
        entity = entity_of(project(snapshot, **context))
        assert entity["entity_id"] == FIXTURE_ENTITY_ID
        assert entity["source_ids"] == FIRST_UPSERT["source_ids"]


#: (session, generation, incarnation) -> the external_id written by hand; each differs from the
#: fixture's in exactly one of the three.
LIFECYCLES = (
    ("example-002", 1, 1, '["example-002","1","1","2","3","1"]'),
    ("example-001", 2, 1, '["example-001","2","1","2","3","1"]'),
    ("example-001", 1, 2, '["example-001","1","1","2","3","2"]'),
    ("example-001", 7, 9, '["example-001","7","1","2","3","9"]'),
)


@case("G-R26")
@pytest.mark.parametrize("session,generation,incarnation,external", LIFECYCLES,
                         ids=[f"l{i}" for i in range(len(LIFECYCLES))])
def test_sessions_generations_and_incarnations_give_other_entities(session, generation,
                                                                   incarnation, external):
    """R26 through project_state: the identity of the Entity is the session's, the generation's
    and the incarnation's; the same lifecycle gives the same id (the fixture's two upserts share
    one, checked by the oracle above)."""
    snapshot = make_snapshot(incarnation=incarnation)
    result = project(snapshot, config=config_with(session_id=session), generation=generation)
    entity = entity_of(result)
    entity_id = rfc4122_uuid5(NAMESPACE, "entity|hla-rpr2|" + external)
    assert entity_id == str(ids.derive("hla-rpr2", external)) != FIXTURE_ENTITY_ID
    expected = changed(FIRST_UPSERT, {
        ("entity_id",): entity_id,
        ("source_ids",): [{"system": "hla-rpr2", "external_id": external}],
        ("attributes", "hla", "session_id"): session,
        ("attributes", "hla", "generation"): generation,
        ("source", "original_id"): f"{session}/{generation}/o1/5",
    })
    assert payload_bytes(entity) == payload_bytes(expected)


#: Triples with zero members are identities (R19); the external_id of each, by hand.
ZERO_MEMBER_TRIPLES = (
    ((0, 0, 1), '["example-001","1","0","0","1","1"]'),
    ((0, 1, 0), '["example-001","1","0","1","0","1"]'),
    ((1, 0, 0), '["example-001","1","1","0","0","1"]'),
    ((0, 65535, 65535), '["example-001","1","0","65535","65535","1"]'),
    ((65535, 65535, 65535), '["example-001","1","65535","65535","65535","1"]'),
)


@case("G-R19", "G-R26")
@pytest.mark.parametrize("triple,external", ZERO_MEMBER_TRIPLES,
                         ids=[".".join(map(str, t)) for t, _ in ZERO_MEMBER_TRIPLES])
def test_a_triple_with_zero_members_is_an_identity(triple, external):
    """R19: 'Other triples, including triples with individual zero components, are accepted':
    each decodes VALID and projects to an Entity identified by it."""
    raw = struct.pack(">HHH", *triple)
    assert decode_attribute("EntityIdentifier", raw) == {
        "name": "EntityIdentifier", "value": ident(*triple)}
    snapshot = make_snapshot(ei=ident_slot(*triple), identity=ident(*triple))
    entity = entity_of(project(snapshot))
    expected = changed(FIRST_UPSERT, {
        ("entity_id",): rfc4122_uuid5(NAMESPACE, "entity|hla-rpr2|" + external),
        ("source_ids",): [{"system": "hla-rpr2", "external_id": external}],
        ("attributes", "hla", "identifier"): ident(*triple),
        ("attributes", "hla", "attribute_hashes", "EntityIdentifier"): raw_hash(raw),
    })
    assert payload_bytes(entity) == payload_bytes(expected)


@case("G-R19", paragraphs=("SPEC:281",))
def test_the_null_identifier_never_produces_an_entity():
    """R19 and SPEC:281: 0.0.0 decodes VALID and keeps its decoded value, allocates no identity,
    and is reported during projection eligibility as NULL_ID; on an established identity it is
    an identity change, so the object is quarantined as well (RED-10)."""
    assert decode_attribute("EntityIdentifier", bytes(6)) == {
        "name": "EntityIdentifier", "value": ident(0, 0, 0)}
    null = ident_slot(0, 0, 0)
    assert null["status"] == "VALID" and null["value"] == ident(0, 0, 0)
    fresh = make_snapshot(ei=null, identity=None, incarnation=None)
    assert project(fresh) == Suppression(("NULL_ID",))
    established = make_snapshot(ei=null, lifecycle="QUARANTINED")
    assert project(established) == Suppression(("NULL_ID", "QUARANTINED"))
    assert project(untimed(fresh), config=NONE_POLICY) == Suppression(
        ("NULL_ID", "TIME_UNRESOLVED"))
    # Never an identity, whatever a caller claims: a context naming 0.0.0 is refused.
    caller_bug(ValueError, lambda: project_state(
        fresh, dict(make_context(fresh), identity=ident(0, 0, 0), incarnation=1)))


# ============================================================ decode shapes and tables, R19

#: SPEC:81-83 and R19's shapes: (name, value bytes written by hand, the decoded value).
FIXED_SHAPES = (
    ("EntityIdentifier", "000100020003", ident(1, 2, 3)),
    ("EntityIdentifier", "fffe00007fff", ident(65534, 0, 32767)),
    ("EntityType", "010100e101020304", type_value(1, 1, 225, 1, 2, 3, 4)),
    # Unknown enumerations are data: kind 255, domain 254, country 65535 (0xffff), and so on.
    ("EntityType", "fffeffff80c0e0f0", type_value(255, 254, 65535, 128, 192, 224, 240)),
    ("EntityType", "0000000000000000", type_value(0, 0, 0, 0, 0, 0, 0)),
    ("ForceIdentifier", "00", {"value": 0}),
    ("ForceIdentifier", "1f", {"value": 31}),
    ("ForceIdentifier", "ff", {"value": 255}),
)


@case("G-R19")
@pytest.mark.parametrize("name,hex_value,expected", FIXED_SHAPES,
                         ids=[f"{n}-{h}" for n, h, _ in FIXED_SHAPES])
def test_the_decode_shapes_of_the_fixed_size_attributes(name, hex_value, expected):
    """R19: 'Decode shapes are {site,application,entity}, {kind,domain,country,category,
    subcategory,specific,extra}, {value}'; unknown enumerations are preserved and are not a
    decoder failure (the FOM enumerates force 0-30 and a handful of kinds)."""
    got = decode_attribute(name, bytes.fromhex(hex_value))
    assert list(got) == ["name", "value"] and got["name"] == name
    assert list(got["value"]) == list(expected)
    assert got["value"] == expected
    assert all(type(v) is int for v in got["value"].values())


@case("G-R19", paragraphs=("SPEC:88",))
def test_the_spatial_layout_table():
    """SPEC:88-97, written byte by byte at the table's offsets for the variant that has every
    field (algorithm 4, RVW, 84 bytes): the discriminator at 0, padding at 1-7, ECEF binary64 at
    8/16/24, frozen at 32, padding at 33-35, psi/theta/phi binary32 at 36/40/44, velocity at
    48/52/56, acceleration at 60/64/68 and angular velocity at 72/76/80. Every value is exactly
    representable, so the decoded numbers are the literals below."""
    data = bytearray(84)
    data[0] = 4
    data[1:8] = bytes.fromhex("01020304050607")
    for offset, number in ((8, 1234567.5), (16, -2345678.25), (24, 3456789.125)):
        struct.pack_into(">d", data, offset, number)
    data[32] = 1
    data[33:36] = bytes.fromhex("aabbcc")
    for offset, number in ((36, 0.5), (40, -1.25), (44, 2.75), (48, 10.5), (52, -20.25),
                           (56, 30.125), (60, 0.0625), (64, -0.125), (68, 0.25), (72, -1.5),
                           (76, 2.5), (80, -3.5)):
        struct.pack_into(">f", data, offset, number)
    got = decode_attribute("Spatial", bytes(data))["value"]
    assert list(got) == ["algorithm", "frame", "frozen", "position_ecef_m", "orientation_rad",
                         "velocity_mps", "acceleration_mps2", "angular_velocity_radps",
                         "padding_hex"]
    assert got == {"algorithm": 4, "frame": "WORLD", "frozen": True,
                   "position_ecef_m": [1234567.5, -2345678.25, 3456789.125],
                   "orientation_rad": [0.5, -1.25, 2.75], "velocity_mps": [10.5, -20.25, 30.125],
                   "acceleration_mps2": [0.0625, -0.125, 0.25],
                   "angular_velocity_radps": [-1.5, 2.5, -3.5],
                   "padding_hex": "01020304050607aabbcc"}
    data[32] = 0
    assert decode_attribute("Spatial", bytes(data))["value"]["frozen"] is False
    data[32] = 2
    assert refusal(lambda: decode_attribute("Spatial", bytes(data))).path == "Spatial/32"


#: SPEC:99-108, row by row: algorithm, frame, total bytes, the fields that follow the
#: orientation, in wire order.
VARIANT_ROWS = (
    (1, "WORLD", 48, ()),
    (2, "WORLD", 60, ("velocity_mps",)),
    (3, "WORLD", 72, ("velocity_mps", "angular_velocity_radps")),
    (4, "WORLD", 84, ("velocity_mps", "acceleration_mps2", "angular_velocity_radps")),
    (5, "WORLD", 72, ("velocity_mps", "acceleration_mps2")),
    (6, "BODY", 60, ("velocity_mps",)),
    (7, "BODY", 72, ("velocity_mps", "angular_velocity_radps")),
    (8, "BODY", 84, ("velocity_mps", "acceleration_mps2", "angular_velocity_radps")),
    (9, "BODY", 72, ("velocity_mps", "acceleration_mps2")),
)


@case("G-R19", paragraphs=("SPEC:99",))
@pytest.mark.parametrize("algorithm,frame,total,fields", VARIANT_ROWS,
                         ids=[f"alg{r[0]}" for r in VARIANT_ROWS])
def test_the_spatial_variant_table(algorithm, frame, total, fields):
    """Each row of SPEC:99-108: the binary32 slots from offset 48 hold 1, 2, 3, ... and land in
    the row's fields in order; absent fields are null; the length is exact (no end padding)."""
    data = bytearray(total)
    data[0] = algorithm
    for k in range((total - 48) // 4):
        struct.pack_into(">f", data, 48 + 4 * k, float(k + 1))
    got = decode_attribute("Spatial", bytes(data))["value"]
    assert got["algorithm"] == algorithm and got["frame"] == frame
    expected = {name: None for name in ("velocity_mps", "acceleration_mps2",
                                        "angular_velocity_radps")}
    for i, name in enumerate(fields):
        expected[name] = [float(3 * i + 1), float(3 * i + 2), float(3 * i + 3)]
    assert {name: got[name] for name in expected} == expected
    for wrong in (total - 1, total + 1):
        error = refusal(lambda: decode_attribute("Spatial", bytes(data[:wrong]).ljust(wrong,
                                                                                      b"\0")))
        assert (error.code, error.path) == (errors.E_ATTRIBUTE_LENGTH, "Spatial")


def _spatial_bytes(algorithm, total, *, frozen=0, floats=()):
    data = bytearray(total)
    data[0] = algorithm
    data[32] = frozen
    for offset, raw in floats:
        data[offset:offset + len(raw)] = raw
    return bytes(data)


NAN64 = bytes.fromhex("7ff8000000000000")
NAN32 = bytes.fromhex("7fc00000")
INF32 = bytes.fromhex("7f800000")

#: SPEC:281's ladder, one rung per row, each value carrying the defects of every lower rung
#: too: (what, name, value, the one code and path reported).
PRECEDENCE = (
    ("size before everything", "Spatial", bytes([0]) + bytes(4096), "E_LIMIT", "Spatial"),
    ("size before the name", "Bogus", bytes(4097), "E_LIMIT", "Bogus"),
    ("discriminator before length", "Spatial", bytes([0, 0, 0]), "E_SPATIAL_VARIANT", "Spatial"),
    ("discriminator before length (10)", "Spatial", _spatial_bytes(10, 85, frozen=2),
     "E_SPATIAL_VARIANT", "Spatial"),
    ("length before boolean", "Spatial", _spatial_bytes(2, 59, frozen=2,
                                                        floats=[(8, NAN64)]),
     "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("boolean before floats", "Spatial", _spatial_bytes(2, 60, frozen=2, floats=[(8, NAN64)]),
     "E_BOOLEAN", "Spatial/32"),
    ("floats in ascending offset", "Spatial",
     _spatial_bytes(4, 84, floats=[(36, NAN32), (80, INF32)]), "E_NONFINITE", "Spatial/36"),
    ("the lowest offset of two", "Spatial",
     _spatial_bytes(8, 84, floats=[(8, NAN64), (72, NAN32)]), "E_NONFINITE", "Spatial/8"),
    ("fixed length", "EntityIdentifier", bytes(7), "E_ATTRIBUTE_LENGTH", "EntityIdentifier"),
)


@case("G-R19", paragraphs=("SPEC:281",))
@pytest.mark.parametrize("what,name,value,code,path", PRECEDENCE,
                         ids=[p[0].replace(" ", "-") for p in PRECEDENCE])
def test_decoder_precedence_reports_one_error(what, name, value, code, path):
    """SPEC:281: size bound first, discriminator second, exact length third, boolean fourth,
    interpreted floats in ascending offset fifth; at most one decode error per attribute."""
    error = refusal(lambda: decode_attribute(name, value))
    assert (error.code, error.path) == (code, path)


@case("G-R19", "G-R28")
def test_force_identifier_is_preserved_data_and_never_an_identity():
    """R19: 'ForceIdentifier does not identify an HLA federation member or an RTI process', and
    R28: no identity is inferred from it. Every one of the 256 values decodes and is carried as
    attributes.hla.force_identifier; the entity_id, the source block and everything else but
    the affiliation, the force value and its hash stay the fixture's."""
    for value in range(256):
        assert decode_attribute("ForceIdentifier", bytes([value]))["value"] == {"value": value}
    for value in (0, 1, 2, 30, 31, 128, 255):
        entity = entity_of(project(make_snapshot(force=force_slot(value))))
        expected = changed(FIRST_UPSERT, {
            ("affiliation",): "FRIENDLY" if value == 1 else "UNKNOWN",
            ("attributes", "hla", "force_identifier"): value,
            ("attributes", "hla", "attribute_hashes", "ForceIdentifier"):
                raw_hash(bytes([value])),
        })
        assert payload_bytes(entity) == payload_bytes(expected)


@case("G-R19")
@pytest.mark.parametrize("kind", [0, 2, 3, 4, 5, 6, 7, 8, 10, 11, 200, 255])
@case("G-R37", paragraphs=("SPEC:201",))
def test_an_unknown_entity_type_is_preserved_and_projects_as_unknown(kind):
    """R19 and R32: an EntityType enumeration the profile does not map is not a fault; the
    Entity's type is UNKNOWN and the seven decoded members stand unchanged in the provenance.
    Odd domain, country and category values ride along."""
    fields = (kind, 254, 65535, 77, 0, 255, 9)
    raw = struct.pack(">BBHBBBB", *fields)
    entity = entity_of(project(make_snapshot(et=type_slot(*fields))))
    expected = changed(FIRST_UPSERT, {
        ("entity_type",): "UNKNOWN",
        ("attributes", "hla", "entity_type"): type_value(*fields),
        ("attributes", "hla", "attribute_hashes", "EntityType"): raw_hash(raw),
    })
    assert payload_bytes(entity) == payload_bytes(expected)


# ===================================================== the type and affiliation mappings, R32

def test_entity_type_follows_the_kind_alone():
    """R32: PLATFORM if EntityType.kind is 1, SENSOR if 9, UNKNOWN for every other of the 256
    kinds; the name and the reported class never make a UNIT (no unit is inferred from a
    lifeform or aggregate name)."""
    for kind in range(256):
        fields = (kind, 1, 225, 1, 2, 3, 4)
        entity = entity_of(project(make_snapshot(et=type_slot(*fields))))
        assert entity["entity_type"] == {1: "PLATFORM", 9: "SENSOR"}.get(kind, "UNKNOWN"), kind
        assert entity["attributes"]["hla"]["entity_type"] == type_value(*fields)
    for name, reported_class, kind, expected in (
            ("INFANTRY PLATOON", PHYSICAL + ".Lifeform.Human", 3, "UNKNOWN"),
            ("1st BATTALION", "HLAobjectRoot.BaseEntity.AggregateEntity", 11, "UNKNOWN"),
            ("SENSOR TOWER", PHYSICAL + ".Platform", 1, "PLATFORM"),
            ("TANK", PHYSICAL + ".Sensor", 9, "SENSOR")):
        snapshot = make_snapshot(et=type_slot(kind, 1, 225, 1, 2, 3, 4), name=name,
                                 reported_class=reported_class)
        assert entity_of(project(snapshot))["entity_type"] == expected


#: (force_map, ForceIdentifier slot, expected affiliation): R09 and RED-17. The map alone
#: decides; the RPR enumeration's own labels (1 Friendly, 2 Opposing, 3 Neutral) mean nothing.
AFFILIATIONS = (
    ({"1": "FRIENDLY"}, force_slot(1), "FRIENDLY"),
    ({"1": "FRIENDLY"}, force_slot(2), "UNKNOWN"),          # valid but unmapped
    ({"1": "FRIENDLY"}, ABSENT_SLOT, "UNKNOWN"),             # absent: no inference
    ({}, force_slot(1), "UNKNOWN"),                          # {}: no configured affiliation
    ({"1": "HOSTILE"}, force_slot(1), "HOSTILE"),            # not the label "Friendly"
    ({"2": "FRIENDLY"}, force_slot(2), "FRIENDLY"),          # not the label "Opposing"
    ({"3": "NEUTRAL"}, force_slot(3), "NEUTRAL"),
    ({"0": "NEUTRAL"}, force_slot(0), "NEUTRAL"),
    ({"255": "HOSTILE"}, force_slot(255), "HOSTILE"),
    ({"5": "UNKNOWN"}, force_slot(5), "UNKNOWN"),            # an explicit UNKNOWN entry
    ({"1": "HOSTILE", "10": "FRIENDLY", "100": "NEUTRAL"}, force_slot(10), "FRIENDLY"),
    ({"1": "HOSTILE", "10": "FRIENDLY", "100": "NEUTRAL"}, force_slot(100), "NEUTRAL"),
)


@case("G-R28")
@pytest.mark.parametrize("force_map,force,expected", AFFILIATIONS,
                         ids=[f"a{i}" for i in range(len(AFFILIATIONS))])
def test_affiliation_follows_the_force_map_alone(force_map, force, expected):
    """R28: no trust or relationship is inferred from a force identifier; R32 and R09: the
    affiliation is the configured map's entry for the canonical decimal of a VALID force value,
    and UNKNOWN for an absent or unmapped one. Nothing else in the Entity changes with it."""
    snapshot = make_snapshot(force=force)
    entity = entity_of(project(snapshot, config=config_with(force_map=force_map)))
    absent = force["status"] == "ABSENT"
    expected_entity = changed(FIRST_UPSERT, {
        ("affiliation",): expected,
        ("attributes", "hla", "force_identifier"): None if absent else force["value"]["value"],
        ("attributes", "hla", "attribute_sequences", "ForceIdentifier"): None if absent else 4,
        ("attributes", "hla", "attribute_hashes", "ForceIdentifier"):
            None if absent else raw_hash(bytes.fromhex(force["hex"])),
    })
    assert payload_bytes(entity) == payload_bytes(expected_entity)


def test_an_invalid_force_suppresses_whatever_the_map_says():
    """R23: an INVALID ForceIdentifier suppresses until corrected, so an earlier affiliation
    cannot survive a rejected update."""
    for force_map in ({"1": "FRIENDLY"}, {}):
        snapshot = make_snapshot(force=invalid_slot(bytes.fromhex("0102"), seq=6))
        result = project(snapshot, config=config_with(force_map=force_map), seq=6)
        assert result == Suppression(("INVALID_FORCE_IDENTIFIER",))


# ========================================================================== suppression reasons

UNPROJECTABLE = spatial_slot(position=(0.0, 0.0, 0.0), velocity=(0.0, 10.0, 0.0))

#: (what, snapshot, context changes, the reasons, the geography code): each reason alone.
ALONE = (
    ("missing identifier", lambda: make_snapshot(ei=ABSENT_SLOT, identity=None,
                                                 incarnation=None),
     {}, ("MISSING_ENTITY_IDENTIFIER",), None),
    ("missing type", lambda: make_snapshot(et=ABSENT_SLOT), {}, ("MISSING_ENTITY_TYPE",), None),
    ("missing spatial", lambda: make_snapshot(spatial=ABSENT_SLOT), {}, ("MISSING_SPATIAL",),
     None),
    ("invalid identifier", lambda: make_snapshot(ei=invalid_slot(bytes(5), seq=5)), {},
     ("INVALID_ENTITY_IDENTIFIER",), None),
    ("invalid type", lambda: make_snapshot(et=invalid_slot(bytes(9), seq=5)), {},
     ("INVALID_ENTITY_TYPE",), None),
    ("invalid spatial", lambda: make_snapshot(spatial=invalid_slot(bytes([0]) + bytes(59))), {},
     ("INVALID_SPATIAL",), None),
    ("invalid force", lambda: make_snapshot(force=invalid_slot(bytes(2), seq=5)), {},
     ("INVALID_FORCE_IDENTIFIER",), None),
    ("null identifier", lambda: make_snapshot(ei=ident_slot(0, 0, 0), identity=None,
                                              incarnation=None), {}, ("NULL_ID",), None),
    ("quarantined", lambda: make_snapshot(lifecycle="QUARANTINED"), {}, ("QUARANTINED",), None),
    ("time unresolved", lambda: untimed(make_snapshot()), {"config": NONE_POLICY},
     ("TIME_UNRESOLVED",), None),
    ("ecef range", lambda: make_snapshot(spatial=UNPROJECTABLE), {},
     ("GEOGRAPHY_UNPROJECTABLE",), "E_ECEF_RANGE"),
)


@pytest.mark.parametrize("what,build,context,reasons,code", ALONE, ids=[a[0] for a in ALONE])
def test_each_suppression_reason_alone(what, build, context, reasons, code):
    """SPEC:285's vocabulary, each reason the only one: ABSENT optional force is none of them."""
    assert project(build(), **context) == Suppression(reasons, code)


#: (what, snapshot, context changes, the complete sorted reasons, the geography code).
COMBINED = (
    ("nothing yet", lambda: make_snapshot(ei=ABSENT_SLOT, et=ABSENT_SLOT, force=ABSENT_SLOT,
                                          spatial=ABSENT_SLOT, identity=None, incarnation=None),
     {}, ("MISSING_ENTITY_IDENTIFIER", "MISSING_ENTITY_TYPE", "MISSING_SPATIAL"), None),
    ("incomplete and untimed", lambda: untimed(make_snapshot(spatial=ABSENT_SLOT)),
     {"config": NONE_POLICY}, ("MISSING_SPATIAL", "TIME_UNRESOLVED"), None),
    ("unprojectable while incomplete", lambda: make_snapshot(et=ABSENT_SLOT,
                                                             spatial=UNPROJECTABLE),
     {}, ("GEOGRAPHY_UNPROJECTABLE", "MISSING_ENTITY_TYPE"), "E_ECEF_RANGE"),
    ("unprojectable and untimed", lambda: untimed(make_snapshot(spatial=UNPROJECTABLE)),
     {"config": NONE_POLICY}, ("GEOGRAPHY_UNPROJECTABLE", "TIME_UNRESOLVED"), "E_ECEF_RANGE"),
    ("null, quarantined, untimed", lambda: untimed(make_snapshot(ei=ident_slot(0, 0, 0),
                                                                 lifecycle="QUARANTINED")),
     {"config": NONE_POLICY}, ("NULL_ID", "QUARANTINED", "TIME_UNRESOLVED"), None),
    ("six at once", lambda: untimed(make_snapshot(
        ei=ident_slot(0, 0, 0), et=invalid_slot(bytes(1), seq=5),
        force=invalid_slot(bytes(0), seq=5), spatial=UNPROJECTABLE, lifecycle="QUARANTINED")),
     {"config": NONE_POLICY},
     ("GEOGRAPHY_UNPROJECTABLE", "INVALID_ENTITY_TYPE", "INVALID_FORCE_IDENTIFIER", "NULL_ID",
      "QUARANTINED", "TIME_UNRESOLVED"), "E_ECEF_RANGE"),
    ("all invalid", lambda: make_snapshot(
        ei=invalid_slot(bytes(1), seq=5), et=invalid_slot(bytes(1), seq=5),
        force=invalid_slot(bytes(1) * 2, seq=5), spatial=invalid_slot(bytes(1))),
     {}, ("INVALID_ENTITY_IDENTIFIER", "INVALID_ENTITY_TYPE", "INVALID_FORCE_IDENTIFIER",
          "INVALID_SPATIAL"), None),
    ("quarantined collider", lambda: make_snapshot(lifecycle="QUARANTINED", identity=None,
                                                   incarnation=None),
     {}, ("QUARANTINED",), None),
)


@pytest.mark.parametrize("what,build,context,reasons,code", COMBINED,
                         ids=[c[0] for c in COMBINED])
def test_reasons_are_complete_sorted_and_unique(what, build, context, reasons, code):
    """RED-02 and RED-16: every applicable reason, sorted, each once; GEOGRAPHY_UNPROJECTABLE
    whenever Spatial is VALID and refused, whatever else is listed, with section 9's code."""
    result = project(build(), **context)
    assert result == Suppression(reasons, code)
    assert list(result.reasons) == sorted(set(result.reasons))


def test_both_geodesy_refusals_become_geography_unprojectable(monkeypatch):
    """R29's two refusals. E_ECEF_RANGE from data (the gate's bounds, COD-11); E_GEODESY cannot
    be reached from finite data (COD-12), so the real iteration is run with a bound of one step
    through geodesy's own seam, at (30, 40, 1000 m), which needs five."""
    below = spatial_slot(position=(math.nextafter(1e6, 0.0), 0.0, 0.0))
    assert project(make_snapshot(spatial=below)) == Suppression(("GEOGRAPHY_UNPROJECTABLE",),
                                                                "E_ECEF_RANGE")
    beyond = spatial_slot(position=(0.0, 0.0, math.nextafter(-1e8, -math.inf)))
    assert project(make_snapshot(spatial=beyond)) == Suppression(("GEOGRAPHY_UNPROJECTABLE",),
                                                                 "E_ECEF_RANGE")
    real = geodesy.project_spatial
    monkeypatch.setattr(geodesy, "project_spatial",
                        lambda value: real(value, max_iterations=1))
    deep = make_snapshot(spatial=spatial_slot(position=forward(30.0, 40.0, 1000.0)))
    assert project(deep) == Suppression(("GEOGRAPHY_UNPROJECTABLE",), "E_GEODESY")
    assert project(make_snapshot(et=ABSENT_SLOT,
                                 spatial=spatial_slot(position=forward(30.0, 40.0, 1000.0)))) \
        == Suppression(("GEOGRAPHY_UNPROJECTABLE", "MISSING_ENTITY_TYPE"), "E_GEODESY")


def test_the_suppression_result_holds_its_own_rules():
    """CR-L02's structured suppression: non-empty, sorted, unique reasons of the vocabulary,
    and section 9's code exactly with GEOGRAPHY_UNPROJECTABLE."""
    assert Suppression(("MISSING_SPATIAL",)).geography_code is None
    for reasons, code, exception in (
            ((), None, ValueError),
            (("NULL_ID", "MISSING_SPATIAL"), None, ValueError),
            (("NULL_ID", "NULL_ID"), None, ValueError),
            (("STALE",), None, ValueError),
            (("GEOGRAPHY_UNPROJECTABLE",), None, ValueError),
            (("GEOGRAPHY_UNPROJECTABLE",), "E_LIMIT", ValueError),
            (("MISSING_SPATIAL",), "E_ECEF_RANGE", ValueError),
            (["MISSING_SPATIAL"], None, TypeError),
            ((1,), None, TypeError)):
        caller_bug(exception, lambda: Suppression(reasons, code))
    assert projector.REASONS == (
        "MISSING_ENTITY_IDENTIFIER", "MISSING_ENTITY_TYPE", "MISSING_SPATIAL",
        "INVALID_ENTITY_IDENTIFIER", "INVALID_ENTITY_TYPE", "INVALID_SPATIAL",
        "INVALID_FORCE_IDENTIFIER", "NULL_ID", "QUARANTINED", "TIME_UNRESOLVED",
        "GEOGRAPHY_UNPROJECTABLE")


# ===================================================================================== time

#: (epoch, Spatial elapsed_ns, its effective_at, the Entity's valid_from), by hand: effective
#: time = epoch + elapsed_ns // 1000 microseconds (CR-L05), valid_from that instant cut to
#: milliseconds. 1234567891 ns -> 1234567 us (891 ns dropped) -> 01.234567 -> 01.234;
#: 999999 ns -> 999 us; 1000 ns onto 23:59:59.999999 of 2026-02-28 (2026 is not a leap year)
#: -> 03-01T00:00:00.000000; 600999 ns -> 600 us onto 23:59:59.999500 of 2028-02-28 (a leap
#: year) -> 02-29T00:00:00.000100; 86400000000999 ns -> 86400000000 us = one day;
#: 1234999 ns -> 1234 us onto 59.998765 -> 59.999999, cut (never rounded) to 59.999.
TIMES = (
    ("2026-01-01T00:00:00.000000Z", "1234567891", "2026-01-01T00:00:01.234567Z",
     "2026-01-01T00:00:01.234Z"),
    ("2026-01-01T00:00:00.000000Z", "999999", "2026-01-01T00:00:00.000999Z",
     "2026-01-01T00:00:00.000Z"),
    ("2026-02-28T23:59:59.999999Z", "1000", "2026-03-01T00:00:00.000000Z",
     "2026-03-01T00:00:00.000Z"),
    ("2028-02-28T23:59:59.999500Z", "600999", "2028-02-29T00:00:00.000100Z",
     "2028-02-29T00:00:00.000Z"),
    ("1970-01-01T00:00:00.000000Z", "86400000000999", "1970-01-02T00:00:00.000000Z",
     "1970-01-02T00:00:00.000Z"),
    ("2026-12-31T23:59:59.998765Z", "1234999", "2026-12-31T23:59:59.999999Z",
     "2026-12-31T23:59:59.999Z"),
)


def timed_snapshot(epoch, elapsed, effective_at):
    """The fixture's state with the other three attributes at elapsed 0 (effective = epoch)."""
    return make_snapshot(ei=ident_slot(at=epoch), et=type_slot(at=epoch),
                         force=force_slot(at=epoch),
                         spatial=spatial_slot(elapsed=elapsed, at=effective_at))


@case("G-R08", paragraphs=("SPEC:42",))
@pytest.mark.parametrize("epoch,elapsed,effective_at,valid_from", TIMES,
                         ids=[f"t{i}" for i in range(len(TIMES))])
def test_effective_time_is_epoch_plus_elapsed_truncated(epoch, elapsed, effective_at,
                                                        valid_from):
    """SPEC:42 (the carried G-R08 clause): effective time is the epoch plus the elapsed
    nanoseconds truncated to microseconds; the Entity carries the basis and the external_elapsed
    kind in attributes.hla.time at six-digit precision, source.observed_at null, and the
    external-time-context transformation; valid_from is that time cut to milliseconds."""
    policy = {"mode": "external_elapsed", "epoch": epoch,
              "basis": "Synthetic 1x scenario clock asserted by fixture author"}
    snapshot = timed_snapshot(epoch, elapsed, effective_at)
    entity = entity_of(project(snapshot, config=config_with(time_policy=policy)))
    assert entity["attributes"]["hla"]["time"] == {
        "kind": "external_elapsed",
        "basis": "Synthetic 1x scenario clock asserted by fixture author",
        "effective_at": effective_at, "spatial_seq": 5}
    assert entity["valid_from"] == valid_from
    assert entity["source"]["observed_at"] is None
    assert entity["source"]["transformations"] == WITH_ENU
    assert entity["source"]["transformations"][0] == "external-time-context"
    assert _utc.parse_millisecond(valid_from) == _utc.parse_microsecond(effective_at) // 1000 * 1000


def test_valid_from_is_the_spatial_time_never_a_later_update():
    """R32: valid_from is the effective time of the most recently accepted Spatial value, never
    the time of a later ForceIdentifier-only update; the other times and sequences stay
    traceable through attribute_sequences (SPEC:134)."""
    snapshot = make_snapshot(force=force_slot(seq=6, elapsed="3000000000",
                                              at="2026-01-01T00:00:03.000000Z"))
    entity = entity_of(project(snapshot, seq=6))
    expected = changed(FIRST_UPSERT, {
        ("attributes", "hla", "attribute_sequences", "ForceIdentifier"): 6,
        ("source", "original_id"): "example-001/1/o1/6",
        ("source", "record_index"): 5,
    })
    assert payload_bytes(entity) == payload_bytes(expected)
    assert entity["valid_from"] == "2026-01-01T00:00:01.000Z"


def test_an_effective_time_past_year_9998_is_e_config():
    """SPEC:289 and RED-V-01 seen from the projector: 9998-12-31T23:59:59.999999Z is the last
    instant an external effective time may name. From the epoch 9998-12-31T23:59:59.000000Z,
    999999999 ns reach it exactly (valid_from ...59.999Z), and so do 999999000 ns (the same
    microsecond); 1000000000 ns pass it by one microsecond, and so does the longest elapsed
    value a snapshot can hold (24 digits): E_CONFIG at the epoch. Any attribute's time counts,
    a rejected one's too."""
    epoch = "9998-12-31T23:59:59.000000Z"
    policy = {"mode": "external_elapsed", "epoch": epoch, "basis": "b"}
    late = config_with(time_policy=policy)
    for elapsed in ("999999999", "999999000"):
        snapshot = timed_snapshot(epoch, elapsed, "9998-12-31T23:59:59.999999Z")
        entity = entity_of(project(snapshot, config=late))
        assert entity["valid_from"] == "9998-12-31T23:59:59.999Z"
        assert entity["attributes"]["hla"]["time"]["effective_at"] == \
            "9998-12-31T23:59:59.999999Z"
    for elapsed, effective_at in (("1000000000", "9999-01-01T00:00:00.000000Z"),
                                  ("1000000000", None),
                                  ("9" * 24, None)):
        snapshot = timed_snapshot(epoch, elapsed, effective_at)
        error = refusal(lambda: project(snapshot, config=late))
        assert (error.code, error.path) == ("E_CONFIG", "/time_policy/epoch")
    rejected = make_snapshot(ei=ident_slot(at=epoch), et=type_slot(at=epoch),
                             force=invalid_slot(bytes(2), seq=5, elapsed="1000000000",
                                                at=None),
                             spatial=spatial_slot(elapsed="0", at=epoch))
    error = refusal(lambda: project(rejected, config=late))
    assert (error.code, error.path) == ("E_CONFIG", "/time_policy/epoch")


def test_time_policy_none_projects_no_entity():
    """R08 and RED-19: under none every effective_at is null and no Entity is produced, only
    TIME_UNRESOLVED; an effective time under none contradicts the policy."""
    assert project(untimed(make_snapshot()), config=NONE_POLICY) == Suppression(
        ("TIME_UNRESOLVED",))
    caller_bug(ValueError, lambda: project(make_snapshot(), config=NONE_POLICY))


# ============================================================== negative zero, COD-15 and RED-18

@case("G-R30", "G-R31")
def test_negative_zero_is_kept_in_the_provenance_and_normalised_in_position_and_motion():
    """COD-15 and RED-18: the decoded Spatial value keeps every -0.0 bit for bit in
    attributes.hla.spatial; only the computed position and kinematics are normalised (R30,
    SPEC:142). At (a, -0.0, -0.0) the latitude is atan2(-0.0, .) = -0.0 and stays so through the
    iteration, the longitude atan2(-0.0, a) = -0.0, and both round to -0.0 before the
    normalisation writes 0.0; the height is a/cos(-0.0) - a = +0.0. With velocity (-0.0, 10, 5)
    the up component is -0.0 + (1 * -0.0 * 10) + (-0.0 * 5) = -0.0, so the climb rounds to -0.0
    and is written 0.0. east = 10, north = 5: speed sqrt(125) = 11.180339887498949 -> 11.18034,
    course atan(10/5) = 63.4349488229220 degrees -> 63.434948823."""
    lat_raw = math.atan2(-0.0, WGS_A * (1 - WGS_E2))
    lon_raw = math.atan2(-0.0, WGS_A)
    up_raw = (math.cos(lat_raw) * math.cos(lon_raw) * -0.0
              + math.cos(lat_raw) * math.sin(lon_raw) * 10.0 + math.sin(lat_raw) * 5.0)
    assert math.copysign(1.0, lat_raw) == math.copysign(1.0, lon_raw) == -1.0
    assert math.copysign(1.0, up_raw) == -1.0 and math.copysign(1.0, round(up_raw, 6)) == -1.0
    spatial = spatial_slot(position=(WGS_A, -0.0, -0.0), orientation=(-0.0, 0.0, -0.0),
                           velocity=(-0.0, 10.0, 5.0))
    snapshot = make_snapshot(spatial=spatial)
    entity_bytes = projector.entity_bytes(project(snapshot))
    expected = entity_with_spatial(snapshot, {("kinematics",): motion(11.18034, 63.434948823,
                                                                      0.0)})
    assert entity_bytes == payload_bytes(expected)
    entity = json.loads(entity_bytes)
    hla_spatial = entity["attributes"]["hla"]["spatial"]
    assert [math.copysign(1.0, v) for v in hla_spatial["position_ecef_m"]] == [1.0, -1.0, -1.0]
    assert [math.copysign(1.0, v) for v in hla_spatial["orientation_rad"]] == [-1.0, 1.0, -1.0]
    assert math.copysign(1.0, hla_spatial["velocity_mps"][0]) == -1.0
    for value in (*entity["position"].values(), *entity["kinematics"].values()):
        if type(value) is float:
            assert math.copysign(1.0, value) == 1.0
    assert b'"position_ecef_m":[6378137.0,-0.0,-0.0]' in entity_bytes
    assert b'"lat":0.0' in entity_bytes and b'"climb_mps":0.0' in entity_bytes


# ===================================== SPEC:146 clauses the R1 review found unbound (R1-r1-F1)

@case("G-R30", paragraphs=("SPEC:146",))
def test_course_is_degrees_of_atan2_plus_360_modulo_360():
    """R1-r1-F1 item 1: course_deg = (degrees(atan2(east, north)) + 360) modulo 360, in that
    grouping. On the equator at longitude 0, east = vy and north = vz exactly. With vy the
    binary32 0.0002169007930206135 and vz 1000, degrees(atan2) is
    1.2427500013121580e-05 (70-digit arithmetic), 1.3e-14 above the 9-decimal tie 1.24275e-05,
    so rounding it alone would give 1.2428e-05. Adding 360 first rounds it to a multiple of
    2^-44 (the spacing of doubles near 360): k = 218626892, k * 2^-44 = 1.2427499996192637e-05,
    3.8e-15 BELOW the tie, so the specified grouping gives 1.2427e-05. Speed: hypot(2.2e-4,
    1000) = 1000.0000000000235 -> 1000.0; climb 0."""
    snapshot = make_snapshot(spatial=spatial_slot(velocity=(0.0, 0.0002169007930206135, 1000.0)))
    entity = entity_of(project(snapshot))
    assert entity["kinematics"] == motion(1000.0, 1.2427e-05, 0.0)
    assert payload_bytes(entity) == payload_bytes(entity_with_spatial(snapshot, {
        ("kinematics",): motion(1000.0, 1.2427e-05, 0.0)}))


#: The ECEF point the closed-form forward transform gives for lat 30.00000000044, lon
#: 40.00000000044, h 1000 m, written as exact doubles so that no libm enters the input.
UNROUNDED_ECEF = (float.fromhex("0x1.028486c530901p+22"), float.fromhex("0x1.b1d81c54a0079p+21"),
                  float.fromhex("0x1.8311cde226f75p+21"))


@case("G-R30", paragraphs=("SPEC:146",))
def test_enu_uses_the_unrounded_latitude_and_longitude():
    """R1-r1-F1 item 2: SPEC:146 converts the velocity 'using the unrounded geodetic latitude
    phi and longitude lambda'. The exact geodetic coordinates of this point (70-digit
    iteration with the specification's constants) are lat 30.000000000439996, lon
    40.000000000439994, h 999.99999999976; they round to (30, 40, 1000). With the binary32
    velocity (-233.86483764648438, 368.6172790527344, 77.25826263427734) the exact course is
    84.9796110697554 degrees, 2.6e-10 above the tie 84.9796110695, so 84.97961107; the same
    velocity turned with the ROUNDED angles 30 and 40 gives 84.9796110694527, which rounds to
    84.979611069. Speed 434.3690428138686 -> 434.369043, climb 88.6782639314084 -> 88.678264."""
    velocity = (-233.86483764648438, 368.6172790527344, 77.25826263427734)
    snapshot = make_snapshot(spatial=spatial_slot(position=UNROUNDED_ECEF, velocity=velocity))
    entity = entity_of(project(snapshot))
    assert entity["position"] == where(30.0, 40.0, 1000.0)
    assert entity["kinematics"] == motion(434.369043, 84.97961107, 88.678264)
    assert payload_bytes(entity) == payload_bytes(entity_with_spatial(snapshot, {
        ("position",): where(30.0, 40.0, 1000.0),
        ("kinematics",): motion(434.369043, 84.97961107, 88.678264)}))


@case("G-R30", "G-R31", paragraphs=("SPEC:146",))
def test_enu_at_plus_180_uses_the_unnormalised_atan2():
    """R1-r1-F1 item 3 (COD-10): the position is written at longitude -180, but ENU turns with
    the plain atan2(+0.0, -a) = +pi (the double below pi). sin of that double is
    1.2246467991473532e-16 > 0, so with vx the binary32 1.0000000200408773e+20 east =
    -sin * vx = -12246.468236903495 (the exact product of the two doubles, rounded once): due
    west, course 270. With -pi the sign of sin flips and the course would be 90. north = 0;
    up = cos(pi) * vx = -1.0000000200408773e+20, rounded to 6 places unchanged. No clipping of a
    finite speed (R31): the speed is 12246.468237 m/s as computed."""
    snapshot = make_snapshot(spatial=spatial_slot(position=(-WGS_A, 0.0, 0.0),
                                                  velocity=(f32(1e20), 0.0, 0.0)))
    assert f32(1e20) == 1.0000000200408773e+20
    entity = entity_of(project(snapshot))
    assert entity["kinematics"] == motion(12246.468237, 270.0, -1.0000000200408773e+20)
    assert payload_bytes(entity) == payload_bytes(entity_with_spatial(snapshot, {
        ("position",): where(0.0, -180.0, 0.0),
        ("kinematics",): motion(12246.468237, 270.0, -1.0000000200408773e+20)}))


#: (lat, lon, h), (east, north, up) and speed, course, climb by hand (as in test_hla_geodesy):
#: 3-4-12 -> 5 m/s at atan(3/4) = 36.8698976458440213 degrees; (-6, 8) -> 10 at 360 -
#: 36.8698976458440213; (0, -7) -> 7 at 180; (-20, -20) -> 20 sqrt 2 = 28.2842712474619010 at
#: 225; (0, 9) -> 9 at 0. The velocity is built from the ENU basis at the point, v = e E + n N +
#: u U, and is quantised to binary32 on the wire, which moves the result by a few 1e-7.
ENU_POINTS = (
    ((30.0, 40.0, 1000.0), (3.0, 4.0, 12.0), (5.0, 36.8698976458440213, 12.0)),
    ((-45.0, -120.0, 250.0), (-6.0, 8.0, -2.5), (10.0, 323.1301023541559787, -2.5)),
    ((0.0, 90.0, 0.0), (0.0, -7.0, 1.0), (7.0, 180.0, 1.0)),
    ((75.0, 170.0, 12000.0), (-20.0, -20.0, 0.5), (28.2842712474619010, 225.0, 0.5)),
    ((-60.0, -10.0, -100.0), (0.0, 9.0, -4.0), (9.0, 0.0, -4.0)),
)


def enu_velocity(lat_deg, lon_deg, e, n, u):
    phi, lam = math.radians(lat_deg), math.radians(lon_deg)
    east = (-math.sin(lam), math.cos(lam), 0.0)
    north = (-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi))
    up = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
    return tuple(f32(e * east[i] + n * north[i] + u * up[i]) for i in range(3))


@case("G-R30", paragraphs=("SPEC:146",))
@pytest.mark.parametrize("algorithm", [2, 3, 4, 5])
@pytest.mark.parametrize("point,enu,expected", ENU_POINTS,
                         ids=[f"lat{p[0][0]}-lon{p[0][1]}" for p in ENU_POINTS])
def test_world_velocity_turns_into_east_north_up(algorithm, point, enu, expected):
    """SPEC:146: for algorithms 2-5 the WORLD velocity is turned into east, north and up at the
    point; speed is hypot(east, north), climb is up, course (atan2(east, north) in degrees + 360)
    modulo 360. Every WORLD variant does it; the other fields of a variant do not matter."""
    _, _, _, a_at, w_at = SPATIAL_TABLE[algorithm]
    snapshot = make_snapshot(spatial=spatial_slot(
        algorithm, position=forward(*point), velocity=enu_velocity(*point[:2], *enu),
        acceleration=(1.0, 2.0, 3.0) if a_at else None, angular=(0.5, 0.5, 0.5) if w_at else None))
    entity = entity_of(project(snapshot))
    assert entity["position"] == where(*point)
    speed, course, climb = expected
    got = entity["kinematics"]
    assert abs(got["speed_mps"] - speed) < 3e-6 and abs(got["climb_mps"] - climb) < 3e-6, got
    assert abs((got["course_deg"] - course + 180.0) % 360.0 - 180.0) < 5e-5, got
    assert entity["source"]["transformations"] == WITH_ENU


@case("G-R30", paragraphs=("SPEC:146",))
def test_course_threshold_rounding_and_360():
    """SPEC:146: course only when the UNROUNDED horizontal speed exceeds 1e-6 m/s. The binary32
    neighbours of 1e-6, 0x358637bd = 9.999999974752427e-07 and 0x358637be =
    1.0000001111620804e-06, both round to a speed of 1e-06; only the second gets a course (90,
    due east). Speeds round to 6 places half to even: 100.0078125 is a tie -> 100.007812. A
    course that rounds to 360 is written 0: east f32(-1e-12) = -9.999999960041972e-13 and
    north 10 give 360 - 5.7e-12 degrees."""
    below, above = 9.999999974752427e-07, 1.0000001111620804e-06
    assert struct.pack(">f", below).hex() == "358637bd"
    assert struct.pack(">f", above).hex() == "358637be"
    for vy, expected in ((above, motion(1e-06, 90.0, 0.0)), (below, motion(1e-06, None, 0.0)),
                         (100.0078125, motion(100.007812, 90.0, 0.0))):
        snapshot = make_snapshot(spatial=spatial_slot(velocity=(0.0, vy, 0.0)))
        assert entity_of(project(snapshot))["kinematics"] == expected
    snapshot = make_snapshot(spatial=spatial_slot(velocity=(0.0, -9.999999960041972e-13, 10.0)))
    assert entity_of(project(snapshot))["kinematics"] == motion(10.0, 0.0, 0.0)


# ======================================================================= position, R30

@case("G-R30")
def test_the_position_is_wgs84_degrees_and_hae_metres_estimated():
    """R30: lat and lon in degrees, alt_m in metres above the ellipsoid, position_source
    ESTIMATED, accuracy_m and vertical null. The height is a conversion of the supplied ECEF and
    not terrain: (1e6, 0, 0), the gate's lower bound, is at height 1e6 - a = -5378137 m, deep
    under any ground, and is written so; a + 9e7 on the x axis is at 9e7 m."""
    for ecef, expected in (((1e6, 0.0, 0.0), where(0.0, 0.0, -5378137.0)),
                           ((WGS_A + 9.0e7, 0.0, 0.0), where(0.0, 0.0, 90000000.0)),
                           (forward(30.0, 40.0, -1000.0), where(30.0, 40.0, -1000.0))):
        entity = entity_of(project(make_snapshot(spatial=spatial_slot(position=ecef))))
        assert entity["position"] == expected
        assert set(entity["position"]) == {"lat", "lon", "alt_m", "position_source",
                                           "accuracy_m", "vertical"}


@case("G-R30")
def test_rounding_is_half_even_and_a_rounded_plus_180_is_written_minus_180():
    """R30: 9 places for latitude and longitude, 6 for the height, half to even; a longitude
    that rounds to +180 is wrapped again. x = a + 100 + 2^-7 = 6378237.0078125 is exact and on
    the equator h = x - a = 100.0078125 exactly, a tie -> 100.007812 (half up would give ...813).
    At (-a, 1e-6, 0) the longitude is pi - 1.5679e-13 rad = 179.99999999999102 degrees, which
    rounds to 180 and is written -180; ENU there: east = cos(lon) * 10 = -10, course 270, and
    up = sin(lon) * 10 = 1.6e-12, climb 0."""
    tie = entity_of(project(make_snapshot(spatial=spatial_slot(
        position=(6378237.0078125, 0.0, 0.0)))))
    assert tie["position"] == where(0.0, 0.0, 100.007812)
    wrapped = entity_of(project(make_snapshot(spatial=spatial_slot(
        position=(-WGS_A, 1e-6, 0.0)))))
    assert wrapped["position"] == where(0.0, -180.0, 0.0)
    assert wrapped["kinematics"] == motion(10.0, 270.0, 0.0)


GRID = [(lat, lon, h) for lat in (-89.999, -75.0, -45.0, 0.0, 45.0, 75.0, 89.999)
        for lon in (-180.0, -90.0, 0.0, 90.0, 179.999)
        for h in (-1000.0, 0.0, 10000.0, 1000000.0, 90000000.0)]


@case("G-R30")
def test_positions_meet_the_tolerances_against_an_independent_transform():
    """R30: 'Validation tolerances are 1e-8 degrees and 1e-4 metres against an independent
    geodesy implementation'. The 175 points of the handoff's grid, carried to ECEF by this
    file's closed-form forward transform and projected by project_state, come back within the
    tolerances and, once rounded, equal to the grid values (-180 written -180)."""
    for lat, lon, h in GRID:
        snapshot = make_snapshot(spatial=spatial_slot(1, position=forward(lat, lon, h),
                                                      velocity=None))
        got = entity_of(project(snapshot))["position"]
        assert abs(got["lat"] - lat) <= 1e-8 and abs(got["alt_m"] - h) <= 1e-4
        assert abs((got["lon"] - lon + 180.0) % 360.0 - 180.0) <= 1e-8
        assert got == where(lat, lon, h), (lat, lon, h)


#: geodesy.json through project_state with the fixture's velocity (0, 10, 0); the motion by
#: hand: at longitude 0 east = vy (course 90); at +90, east = cos(pi/2) * 10 = 6.1e-16, below
#: the 1e-6 threshold (no course) and up = 10; at the antimeridian east = cos(pi) * 10 = -10
#: (course 270); at the poles no motion (SPEC:146).
GEODESY_MOTION = {"equator-x": motion(10.0, 90.0, 0.0), "equator-y": motion(0.0, None, 10.0),
                  "antimeridian": motion(10.0, 270.0, 0.0), "north-pole": None,
                  "south-pole": None}


@case("G-R30")
@pytest.mark.parametrize("entry", fixture_json("geodesy.json"), ids=lambda e: e["id"])
def test_the_geodesy_fixture_and_its_pole_convention(entry):
    """R30: 'fixtures near poles explicitly check the selected longitude convention': each
    geodesy.json point as an Entity (the poles at longitude 0 with no motion); the origin is
    refused by the gate and suppresses the Entity."""
    snapshot = make_snapshot(spatial=spatial_slot(position=tuple(entry["ecef_m"])))
    result = project(snapshot)
    if "error" in entry:
        assert result == Suppression(("GEOGRAPHY_UNPROJECTABLE",), entry["error"])
        return
    entity = entity_of(result)
    assert entity["position"] == where(*entry["expected"])
    assert entity["kinematics"] == GEODESY_MOTION[entry["id"]]
    assert entity["source"]["transformations"] == (
        NO_ENU if GEODESY_MOTION[entry["id"]] is None else WITH_ENU)


# ========================================================= the four A- cases, on the Entity

@case("A-POLE", "G-R30", paragraphs=("SPEC:146",))
def test_a_pole_with_velocity_projects_at_longitude_0_with_no_motion():
    """A-POLE: 'North-pole position with velocity' -> 'longitude 0 and kinematics null'; at the
    p < 1e-8 pole case course depends on a convention (SPEC:146), so no motion at all and no
    ENU transformation. The south pole likewise."""
    for z, lat in ((WGS_B, 90.0), (-WGS_B, -90.0)):
        snapshot = make_snapshot(spatial=spatial_slot(position=(0.0, 0.0, z),
                                                      velocity=(1.5, -2.25, 3.0)))
        entity = entity_of(project(snapshot))
        assert payload_bytes(entity) == payload_bytes(entity_with_spatial(snapshot, {
            ("position",): where(lat, 0.0, 0.0), ("kinematics",): None,
            ("source", "transformations"): NO_ENU}))


@case("A-STATIC", "G-R30", paragraphs=("SPEC:146",))
def test_a_static_spatial_has_null_kinematics_never_an_inferred_zero():
    """A-STATIC: 'kinematics null, never inferred zero': algorithm 1 has no velocity field; a
    WORLD variant with a measured zero velocity, by contrast, is motion: speed 0, no course,
    climb 0."""
    for position, expected in (((WGS_A, 0.0, 0.0), where(0.0, 0.0, 0.0)),
                               (forward(30.0, 40.0, 1000.0), where(30.0, 40.0, 1000.0))):
        snapshot = make_snapshot(spatial=spatial_slot(1, position=position, velocity=None))
        entity = entity_of(project(snapshot))
        assert entity["attributes"]["hla"]["spatial"]["velocity_mps"] is None
        assert payload_bytes(entity) == payload_bytes(entity_with_spatial(snapshot, {
            ("position",): expected, ("kinematics",): None,
            ("source", "transformations"): NO_ENU}))
    still = make_snapshot(spatial=spatial_slot(velocity=(0.0, 0.0, 0.0)))
    entity = entity_of(project(still))
    assert entity["kinematics"] == motion(0.0, None, 0.0)
    assert entity["source"]["transformations"] == WITH_ENU


@case("A-BODY", "G-R31")
@pytest.mark.parametrize("algorithm", [6, 7, 8, 9])
def test_a_body_frame_spatial_maps_its_position_and_keeps_its_body_values(algorithm):
    """A-BODY: 'Position mapped; kinematics null; body values preserved'. R31: BODY velocity
    and acceleration stay frame-tagged and are not transformed; nor is the angular velocity.
    At (30, 40, 1000 m) with every slot non-zero."""
    _, _, _, a_at, w_at = SPATIAL_TABLE[algorithm]
    spatial = spatial_slot(algorithm, position=forward(30.0, 40.0, 1000.0),
                           orientation=(0.5, -1.25, 2.75), velocity=(-3.5, 7.25, 11.0625),
                           acceleration=(0.125, -0.375, 1.5) if a_at else None,
                           angular=(-0.0625, 0.1875, -2.5) if w_at else None)
    snapshot = make_snapshot(spatial=spatial)
    entity = entity_of(project(snapshot))
    assert payload_bytes(entity) == payload_bytes(entity_with_spatial(snapshot, {
        ("position",): where(30.0, 40.0, 1000.0), ("kinematics",): None,
        ("source", "transformations"): NO_ENU}))
    body = entity["attributes"]["hla"]["spatial"]
    assert body["frame"] == "BODY" and body["algorithm"] == algorithm
    assert body["velocity_mps"] == [-3.5, 7.25, 11.0625]
    assert body["acceleration_mps2"] == ([0.125, -0.375, 1.5] if a_at else None)
    assert body["angular_velocity_radps"] == ([-0.0625, 0.1875, -2.5] if w_at else None)


@case("A-ATTITUDE", "G-R31")
def test_course_follows_world_velocity_and_psi_is_kept():
    """A-ATTITUDE: psi = 1.0 and WORLD velocity due east at the equator -> course 90, psi kept
    1.0. R31: the attitude is not a heading, course or body rate and never becomes course_deg;
    any attitude gives the same motion."""
    snapshot = make_snapshot(spatial=spatial_slot(orientation=(1.0, 0.0, 0.0)))
    entity = entity_of(project(snapshot))
    assert entity["attributes"]["hla"]["spatial"]["orientation_rad"] == [1.0, 0.0, 0.0]
    assert payload_bytes(entity) == payload_bytes(entity_with_spatial(snapshot, {}))
    assert entity["kinematics"] == motion(10.0, 90.0, 0.0)
    for attitude in ((-2.5, 0.5, 3.0), (3.140625, -1.5, 0.25), (4.0, 0.0, 0.0)):
        moved = entity_of(project(make_snapshot(spatial=spatial_slot(orientation=attitude))))
        assert moved["kinematics"] == motion(10.0, 90.0, 0.0)
        assert moved["attributes"]["hla"]["spatial"]["orientation_rad"] == list(attitude)


# ============================================================================== R31 otherwise

@case("G-R31")
def test_orientation_is_kept_in_radians_unwrapped():
    """R31: psi, theta, phi stay as decoded, in radians, in attributes.hla.spatial
    .orientation_rad: no wrap to +-pi, no conversion to degrees, -0.0 kept."""
    snapshot = make_snapshot(spatial=spatial_slot(orientation=(1000.0, -1000.0, -0.0)))
    entity = entity_of(project(snapshot))
    orientation = entity["attributes"]["hla"]["spatial"]["orientation_rad"]
    assert orientation == [1000.0, -1000.0, 0.0] and math.copysign(1.0, orientation[2]) == -1.0
    assert entity["kinematics"] == motion(10.0, 90.0, 0.0)


@case("G-R31")
def test_frozen_is_kept_and_stops_neither_motion_nor_the_clock():
    """R31: 'Preserve frozen but do not force velocity to zero or stop the external context
    clock': a frozen value with velocity (0, 10, 0) still moves east at 10 m/s, and a later
    frozen value still advances valid_from by its own elapsed time."""
    for elapsed, at, valid_from in (("1000000000", ONE_SECOND, "2026-01-01T00:00:01.000Z"),
                                    ("2500000000", "2026-01-01T00:00:02.500000Z",
                                     "2026-01-01T00:00:02.500Z")):
        snapshot = make_snapshot(spatial=spatial_slot(frozen=1, elapsed=elapsed, at=at))
        entity = entity_of(project(snapshot))
        assert entity["attributes"]["hla"]["spatial"]["frozen"] is True
        assert entity["kinematics"] == motion(10.0, 90.0, 0.0)
        assert entity["valid_from"] == valid_from


@case("G-R31")
def test_finite_speeds_and_angles_are_not_clipped():
    """R31: no clipping threshold on a finite speed or angle beyond the schema and projection
    limits: the largest binary32, 3.4028234663852886e+38 m/s due east, is the speed; psi of
    1000 rad is kept."""
    top = 3.4028234663852886e+38
    assert f32(top) == top
    snapshot = make_snapshot(spatial=spatial_slot(orientation=(1000.0, 0.0, 0.0),
                                                  velocity=(0.0, top, 0.0)))
    entity = entity_of(project(snapshot))
    assert entity["kinematics"] == motion(top, 90.0, 0.0)
    assert entity["attributes"]["hla"]["spatial"]["orientation_rad"][0] == 1000.0


# ================================================================== source and provenance, R27

OTHER_SHA = "0123456789abcdef" * 4


@case("G-R27")
@pytest.mark.parametrize("capture_complete", [True, False, None])
def test_the_source_block_is_r27(capture_complete):
    """R27: source.system from the config, adapter hla-rpr2, adapter_version 1.0.0, synthetic
    as configured (false here: an existing-mode session), the format name and version;
    original_id session/generation/token/seq; record_index seq - 1; source_hash the triggering
    frame's sha256 field verbatim; observed_at null. The provenance block carries the declared
    profile verification and the completion flag of the context (null live, SPEC:158)."""
    session = config_with(mode="existing", profile_declaration="external-fom-unverified",
                          synthetic=False, source_system="other-system")
    entity = entity_of(project(make_snapshot(), config=session, generation=3, token="o12",
                               seq=41, sha256=OTHER_SHA, capture_complete=capture_complete))
    external = '["example-001","3","1","2","3","1"]'
    expected = changed(FIRST_UPSERT, {
        ("entity_id",): rfc4122_uuid5(NAMESPACE, "entity|hla-rpr2|" + external),
        ("source_ids",): [{"system": "hla-rpr2", "external_id": external}],
        ("source",): {"system": "other-system", "adapter": "hla-rpr2", "adapter_version": "1.0.0",
                      "synthetic": False, "format_name": "HLA RPR FOM",
                      "format_version": "IEEE 1516-2010 / RPR FOM 2.0 / SC-HLA-RPR2-OBS-1",
                      "original_id": "example-001/3/o12/41", "record_index": 40,
                      "source_hash": {"algorithm": "sha256", "value": OTHER_SHA},
                      "observed_at": None, "transformations": WITH_ENU},
        ("attributes", "hla", "generation"): 3,
        ("attributes", "hla", "object_token"): "o12",
        ("attributes", "hla", "profile_verification"): "external-fom-unverified",
        ("attributes", "hla", "capture_complete"): capture_complete,
    })
    assert payload_bytes(entity) == payload_bytes(expected)


@case("G-R27", paragraphs=("SPEC:134",))
def test_the_provenance_block_is_spec_134():
    """SPEC:134: one SourceId {hla-rpr2, external_id}; transformations exactly as listed;
    attributes.hla with exactly its fifteen members; attribute_sequences and attribute_hashes
    for the four cached attributes, null for an absent one; each hash the SHA-256 of the raw
    value bytes and not of their hex spelling; the source bytes themselves only in the capture,
    never in the Entity. Attributes used from earlier frames stay traceable by their seq."""
    snapshot = make_snapshot()
    entity = entity_of(project(snapshot))
    hla = entity["attributes"]["hla"]
    assert set(entity["attributes"]) == {"hla"}
    assert set(hla) == {"profile", "session_id", "generation", "object_token", "reported_class",
                        "name", "identifier", "entity_type", "force_identifier", "spatial",
                        "attribute_sequences", "attribute_hashes", "time",
                        "profile_verification", "capture_complete"}
    assert entity["source_ids"] == [{"system": "hla-rpr2",
                                     "external_id": '["example-001","1","1","2","3","1"]'}]
    assert entity["source"]["transformations"] == WITH_ENU
    assert hla["attribute_sequences"] == {"EntityIdentifier": 3, "EntityType": 3,
                                          "ForceIdentifier": 4, "Spatial": 5}
    data = projector.entity_bytes(project(snapshot))
    for name, slot_ in snapshot["attributes"].items():
        raw = bytes.fromhex(slot_["hex"])
        assert hla["attribute_hashes"][name] == raw_hash(raw) == \
            FIRST_UPSERT["attributes"]["hla"]["attribute_hashes"][name]
        assert hla["attribute_hashes"][name] != raw_hash(slot_["hex"].encode("ascii"))
        if len(slot_["hex"]) > 2:
            assert slot_["hex"].encode("ascii") not in data
    absent = entity_of(project(make_snapshot(force=ABSENT_SLOT)))["attributes"]["hla"]
    assert absent["force_identifier"] is None
    assert absent["attribute_sequences"]["ForceIdentifier"] is None
    assert absent["attribute_hashes"]["ForceIdentifier"] is None


#: (EntityIdentifier seq, EntityType seq, ForceIdentifier seq, Spatial seq, the expected
#: attribute_sequences, the expected time.spatial_seq), each expectation written out by hand.
OWN_SEQUENCES = (
    (2, 3, 4, 5, {"EntityIdentifier": 2, "EntityType": 3, "ForceIdentifier": 4, "Spatial": 5}, 5),
    (3, 2, 5, 4, {"EntityIdentifier": 3, "EntityType": 2, "ForceIdentifier": 5, "Spatial": 4}, 4),
)


@case("G-R27", paragraphs=("SPEC:134",))
@pytest.mark.parametrize("ei,et,fi,sp,sequences,spatial_seq", OWN_SEQUENCES,
                         ids=["2-3-4-5", "3-2-5-4"])
def test_each_cached_attribute_keeps_the_seq_of_its_own_frame(ei, et, fi, sp, sequences,
                                                              spatial_seq):
    """SPEC:134 and R32 ('preserve all other attribute times and sequences'): the
    attribute_sequences entry of each of the four cached attributes is the seq of the frame that
    supplied THAT attribute, and time.spatial_seq is Spatial's. The fixture has EntityIdentifier
    and EntityType both at seq 3, so a swap of the two went unseen (review finding R3-r1-F2);
    here the four come from four different frames, in two orders. Nothing else changes: the
    hashes are those of the attributes' own bytes, the source still names the triggering frame
    (seq 5), and valid_from is still Spatial's effective time, which the seq does not move."""
    snapshot = make_snapshot(ei=ident_slot(seq=ei), et=type_slot(seq=et),
                             force=force_slot(seq=fi), spatial=spatial_slot(seq=sp))
    expected = changed(FIRST_UPSERT, {
        ("attributes", "hla", "attribute_sequences"): sequences,
        ("attributes", "hla", "time", "spatial_seq"): spatial_seq,
    })
    assert payload_bytes(entity_of(project(snapshot))) == payload_bytes(expected)


# ======================================================================== no trust claims, R28

def keys_of(value) -> set:
    found = set()
    if type(value) is dict:
        for key, item in value.items():
            found.add(key)
            found |= keys_of(item)
    elif type(value) is list:
        for item in value:
            found |= keys_of(item)
    return found


@case("G-R28")
def test_ids_and_digests_are_correlation_aids_and_integrity_is_never_set():
    """R28: the entity_id and the frame digest correlate an Entity with its capture and claim no
    authenticated identity: anyone can compute the id from the six public values (here with the
    test's own RFC 4122 code), source_hash is the triggering frame's chain digest as written in
    the capture, which an assurance layer may sign separately without any change here; CDM
    integrity is null on every Entity, and no member speaks of signatures, trust or
    authorisation."""
    cases = [make_snapshot(), make_snapshot(force=ABSENT_SLOT),
             make_snapshot(spatial=spatial_slot(8, position=forward(30.0, 40.0, 1000.0),
                                                acceleration=(0.5, 0.5, 0.5),
                                                angular=(0.25, 0.25, 0.25)))]
    for snapshot in cases:
        entity = entity_of(project(snapshot))
        assert entity["integrity"] is None
        assert not {k for k in keys_of(entity)
                    if any(w in k.lower() for w in ("sign", "trust", "auth", "verified"))}
        assert entity["entity_id"] == rfc4122_uuid5(
            NAMESPACE, "entity|hla-rpr2|" + entity["source_ids"][0]["external_id"])
        assert entity["source"]["source_hash"] == {"algorithm": "sha256",
                                                   "value": FRAMES[5]["sha256"]}


@case("G-R28")
@pytest.mark.parametrize("name,reported_class", [
    ("FRIENDLY", PHYSICAL), ("HOSTILE", PHYSICAL), ("TRUSTED-COMMANDER", PHYSICAL),
    ("\N{RIGHT-TO-LEFT OVERRIDE}ADMIN\x1b[0m", PHYSICAL),
    ("SYNTHETIC-001", PHYSICAL + ".Platform.GroundVehicle.Friendly"),
    ("", "Hostile"),
])
def test_names_and_classes_carry_no_trust_identity_or_affiliation(name, reported_class):
    """R28: no trust, identity or authorisation is inferred from names (or tags, which a
    snapshot does not even carry). Whatever the name and class say, the Entity is the fixture's
    but for the two strings, kept verbatim as data."""
    snapshot = make_snapshot(name=name, reported_class=reported_class)
    entity = entity_of(project(snapshot))
    expected = changed(FIRST_UPSERT, {("attributes", "hla", "name"): name,
                                      ("attributes", "hla", "reported_class"): reported_class})
    assert payload_bytes(entity) == payload_bytes(expected)
    snapshot_schema = json.loads(
        (PACKAGE_ROOT / "src/synapse_hla/schemas/snapshot.schema.json").read_bytes())
    assert not {k for k in keys_of(snapshot_schema["properties"]) if "tag" in k}


# ================================================================ the CDM baseline and R44

#: The members of a JSON Schema that are prose, removed at every depth before the additivity
#: comparison of CR-L18 (they change between CDM releases without changing what validates).
_SCHEMA_PROSE = frozenset({"description", "title", "examples", "$comment"})


def _without_prose(node):
    if isinstance(node, dict):
        return {k: _without_prose(v) for k, v in node.items() if k not in _SCHEMA_PROSE}
    if isinstance(node, list):
        return [_without_prose(v) for v in node]
    return node


def _entry_differences(path: str, vendored, generated, *, default_allowed: bool) -> list[str]:
    """The JSON paths at which one property or $defs entry of the installed SDK's schema is not
    the vendored one, other than CR-L18's two admitted kinds: a `default` (only where
    `default_allowed`) and an `enum` that keeps every vendored value."""
    if isinstance(vendored, dict) and isinstance(generated, dict):
        out = []
        for key in sorted(set(vendored) | set(generated)):
            where = f"{path}/{key}"
            if key == "default" and default_allowed and key in vendored and key in generated:
                continue
            if key not in vendored or key not in generated:
                out.append(where)
            elif (key == "enum" and isinstance(vendored[key], list)
                  and isinstance(generated[key], list)):
                if not all(v in generated[key] for v in vendored[key]):
                    out.append(where)
            else:
                out += _entry_differences(where, vendored[key], generated[key],
                                          default_allowed=default_allowed)
        return out
    if type(vendored) is not type(generated) or vendored != generated:
        return [path]
    return []


def additive_differences(vendored: dict, generated: dict) -> list[str]:
    """CR-L18 (4): the paths where the installed SDK's Entity schema is not additive over the
    vendored 3.0.0 one. Same property names, `required`, `additionalProperties` and `$defs`
    names; each property and `$defs` entry identical or differing only by `default` (the
    `schema_version` property alone) or by an `enum` that is a superset of the vendored one."""
    v, g = _without_prose(vendored), _without_prose(generated)
    out = []
    for key in ("required", "additionalProperties", "type", "$schema"):
        if v.get(key) != g.get(key):
            out.append(f"/{key}")
    if set(v) != set(g):
        out.append("/")
    for group in ("properties", "$defs"):
        names_v, names_g = set(v.get(group, {})), set(g.get(group, {}))
        if names_v != names_g:
            out.append(f"/{group}")
        for name in sorted(names_v & names_g):
            out += _entry_differences(
                f"/{group}/{name}", v[group][name], g[group][name],
                default_allowed=(group, name) == ("properties", "schema_version"))
    return out


def _installed_entity_schema() -> dict:
    from synapse_cdm import schemas
    return schemas.generate()["entity"]


def _vendored_entity_schema() -> dict:
    return json.loads((PACKAGE_ROOT / "src/synapse_hla/schemas/cdm-entity.schema.json")
                      .read_bytes())


@case("G-R44")
def test_the_cdm_baseline_and_its_complete_entity_schema():
    """R44 under D-28 and CR-L18. The handoff's baseline was synapse-cdm 3.1.1 (schema 3.0.0) at
    commit c4bba1b6; the package was landed on synapse-cdm 3.8.0 (schema 3.2.0) and declares
    that as its floor. The vendored contract does not move: cdm-entity.schema.json stays the
    handoff's 3.0.0 bytes and every Entity the package emits declares and validates against
    3.0.0. What an SDK upgrade must keep, and this test holds in CR-L18's order: (1) the
    declared dependency; (2) the installed distribution is the SDK's own version, inside the
    floor and below the next major; (3) the vendored schema is the handoff's bytes and the
    emitted Entity says 3.0.0; (4) the installed SDK's generated Entity schema is ADDITIVE over
    the vendored one (prose aside: the same property names, required list, additionalProperties
    and $defs names, each entry identical or differing only by the schema_version default or by
    an enum that keeps every vendored value); (5) the projector's own Entity and the entity
    payloads of the kit's replay validate against both schemas, with format checking. An SDK
    whose Entity changed otherwise fails (4) or (5) naming the path: that is where the next
    migration starts (README, "The CDM")."""
    import importlib.metadata
    import tomllib

    from jsonschema import FormatChecker
    from synapse_cdm import version
    # (1)
    project_doc = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project_doc["project"]["dependencies"] == ["synapse-cdm>=3.8.0,<4"]
    # (2)
    installed = importlib.metadata.version("synapse-cdm")
    assert installed == version.PACKAGE_VERSION
    triple = tuple(int(part) for part in installed.split("."))
    assert (3, 8, 0) <= triple < (4, 0, 0), installed
    # (3)
    assert projector.CDM_SCHEMA_VERSION == "3.0.0"
    packaged = (PACKAGE_ROOT / "src/synapse_hla/schemas/cdm-entity.schema.json").read_bytes()
    pins = {e["path"]: e["sha256"] for e in
            json.loads((PACKAGE_ROOT / "tests/contract/vendored-pins.json").read_bytes())["files"]}
    assert hashlib.sha256(packaged).hexdigest() == \
        pins["src/synapse_hla/schemas/cdm-entity.schema.json"]
    own = entity_of(project(make_snapshot()))
    assert own["schema_version"] == "3.0.0"
    replayed = [record["payload"] for _, record in OBSERVATIONS if record["kind"] == "upsert"]
    assert len(replayed) == 2
    assert {payload["schema_version"] for payload in replayed} == {"3.0.0"}
    # (4)
    vendored, generated = _vendored_entity_schema(), _installed_entity_schema()
    assert additive_differences(vendored, generated) == []
    assert generated["$id"] == f"urn:synapsecommand:cdm:{version.SCHEMA_VERSION}:entity"
    assert generated["x-cdm-schema-version"] == version.SCHEMA_VERSION
    # (5)
    for schema in (vendored, generated):
        checker = Draft202012Validator(schema, format_checker=FormatChecker())
        for payload in [own] + replayed:
            assert not list(checker.iter_errors(payload)), schema["$id"]


def _schema_mutant(change):
    schema = _without_prose(_vendored_entity_schema())
    change(schema)
    return schema


#: (what, a change to the vendored schema seen as an SDK's, the path the comparison must name):
#: each is a difference CR-L18 does not admit, written by hand, so (4) above cannot pass by
#: comparing nothing.
NOT_ADDITIVE = (
    ("a property removed", lambda s: s["properties"].pop("valid_to"), "/properties"),
    ("a property added", lambda s: s["properties"].update(extra={"type": "string"}),
     "/properties"),
    ("a required member added", lambda s: s["required"].append("valid_to"), "/required"),
    ("additionalProperties opened", lambda s: s.update(additionalProperties=True),
     "/additionalProperties"),
    ("a $defs entry removed", lambda s: s["$defs"].pop("PositionSource"), "/$defs"),
    ("an enum narrowed", lambda s: s["$defs"]["PositionSource"]["enum"].remove("GNSS"),
     "/$defs/PositionSource/enum"),
    ("a default on another property",
     lambda s: s["properties"]["entity_id"].update(default="x"),
     "/properties/entity_id/default"),
    ("a type changed", lambda s: s["properties"]["schema_version"].update(type="integer"),
     "/properties/schema_version/type"),
)


@pytest.mark.parametrize("what,change,path", NOT_ADDITIVE, ids=[r[0] for r in NOT_ADDITIVE])
def test_the_additivity_comparison_names_each_difference_it_does_not_admit(what, change, path):
    """CR-L18 (4), the negative half: a schema that differs from the vendored one in a way
    CR-L18 does not admit is reported at its path; the admitted kinds (a superset enum, the
    schema_version default) are not."""
    vendored = _vendored_entity_schema()
    assert path in additive_differences(vendored, _schema_mutant(change))
    admitted = _schema_mutant(lambda s: (
        s["$defs"]["PositionSource"]["enum"].append("SENSOR"),
        s["properties"]["schema_version"].update(default="3.9.0")))
    assert additive_differences(vendored, admitted) == []


#: (what, a change to the fixture's Entity payload): each breaks one rule of R44's validation.
BROKEN = (
    ("entity type outside the enum", {("entity_type",): "TANK"}),
    ("entity_id not a UUID (only format checking sees it)", {("entity_id",): "not-a-uuid"}),
    ("valid_from with a final newline (ECMA-262 anchors)",
     {("valid_from",): "2026-01-01T00:00:01.000Z\n"}),
    ("latitude past 90", {("position", "lat"): 91.0}),
    ("affiliation outside the enum", {("affiliation",): "ALLY"}),
    ("a member the schema does not have", {("callsign",): "X"}),
    ("valid_from not a real date (only the explicit check sees it)",
     {("valid_from",): "2026-02-30T00:00:01.000Z"}),
    ("effective_at past year 9998", {("attributes", "hla", "time", "effective_at"):
                                     "9999-01-01T00:00:00.000000Z"}),
    ("valid_from not the Spatial time", {("valid_from",): "2026-01-01T00:00:02.000Z"}),
    ("valid_from rounded, not cut", {("attributes", "hla", "time", "effective_at"):
                                     "2026-01-01T00:00:00.999999Z"}),
    ("attributes beyond hla", {("attributes", "extra"): {}}),
    ("provenance without its time", {("attributes", "hla", "time"): None}),
    ("provenance token malformed", {("attributes", "hla", "object_token"): "x1"}),
    ("provenance completion not a bool", {("attributes", "hla", "capture_complete"): "yes"}),
    ("schema_version 3.0.1", {("schema_version",): "3.0.1"}),
    ("a symbol", {("symbol",): "10031000001211000000"}),
    ("a confidence", {("confidence",): 0.5}),
    ("an integrity block", {("integrity",): {"signature": "s", "algorithm": "ML-DSA-87",
                                             "chain_hash": "h"}}),
    ("a valid_to", {("valid_to",): "2026-01-01T00:00:02.000Z"}),
    ("a quality", {("quality",): {}}),
    ("a status", {("status",): {"state": "UP", "namespace": "HLA RPR FOM"}}),
    ("a residual", {("residual",): {"namespace": "HLA RPR FOM"}}),
    ("ontology types", {("ontology_types",): ["x"]}),
    ("no position", {("position",): None}),
    ("position source GNSS", {("position", "position_source"): "GNSS"}),
    ("an accuracy", {("position", "accuracy_m"): 1.0}),
    ("no altitude", {("position", "alt_m"): None}),
    ("entity type not the kind's", {("entity_type",): "SENSOR"}),
    ("frame not the algorithm's", {("attributes", "hla", "spatial", "frame"): "BODY"}),
    ("motion from a static value", {("attributes", "hla", "spatial", "algorithm"): 1,
                                    ("attributes", "hla", "spatial", "velocity_mps"): None}),
    ("motion without the ENU step", {("source", "transformations"): NO_ENU}),
    ("the ENU step without motion", {("kinematics",): None}),
    ("transformations reordered", {("source", "transformations"): [
        "ecef-to-wgs84", "external-time-context", "ecef-velocity-to-enu"]}),
    ("another adapter", {("source", "adapter"): "hla"}),
    ("another adapter version", {("source", "adapter_version"): "1.0.1"}),
    ("another format version", {("source", "format_version"): "RPR FOM 2.0"}),
    ("an observed_at", {("source", "observed_at"): "2026-01-01T00:00:01.000Z"}),
    ("no source hash", {("source", "source_hash"): None}),
    ("another hash algorithm", {("source", "source_hash", "algorithm"): "sha1"}),
    ("a source hash in capitals", {("source", "source_hash", "value"): SEQ5_SHA.upper()}),
    ("original_id of another seq", {("source", "original_id"): "example-001/1/o1/6"}),
    ("no record index", {("source", "record_index"): None}),
    ("an attribute from a later frame", {
        ("attributes", "hla", "attribute_sequences", "Spatial"): 9,
        ("attributes", "hla", "time", "spatial_seq"): 9}),
    ("time names another seq", {("attributes", "hla", "time", "spatial_seq"): 4}),
    # Integral floats where the provenance schema says integer (R3-r1-F1, defence in depth):
    # JSON Schema counts 3.0 as an integer and the profile rules compare by value, so only the
    # exact-integer reading of the provenance schema refuses these.
    ("a sequence as an integral float", {
        ("attributes", "hla", "attribute_sequences", "EntityType"): 3.0}),
    ("Spatial's seq as an integral float", {
        ("attributes", "hla", "attribute_sequences", "Spatial"): 5.0,
        ("attributes", "hla", "time", "spatial_seq"): 5.0}),
    ("an identifier field as an integral float", {
        ("attributes", "hla", "identifier", "site"): 1.0}),
    ("an EntityType field as an integral float", {
        ("attributes", "hla", "entity_type", "kind"): 1.0}),
    ("the force value as an integral float", {("attributes", "hla", "force_identifier"): 1.0}),
    ("the Spatial algorithm as an integral float", {
        ("attributes", "hla", "spatial", "algorithm"): 2.0}),
    # A bool is not an integer either (review finding R3-r2-F1): True compares equal to 1, so
    # the profile rules (which compare the identifier by value) let it through, and only the
    # exact reading of "integer" in the provenance schema refuses it.
    ("an identifier field as a bool", {("attributes", "hla", "identifier", "site"): True}),
    ("a required attribute without its hash", {
        ("attributes", "hla", "attribute_hashes", "EntityIdentifier"): None}),
    ("force null with a force seq", {("attributes", "hla", "force_identifier"): None}),
    ("the null identifier", {("attributes", "hla", "identifier"):
                             {"site": 0, "application": 0, "entity": 0}}),
    ("two source ids", {("source_ids",): FIRST_UPSERT["source_ids"] * 2}),
    ("a DIS source id", {("source_ids", 0, "system"): "dis7"}),
    ("an external_id of another identifier", {
        ("source_ids", 0, "external_id"): '["example-001","1","1","2","4","1"]'}),
    ("an external_id not of this profile", {("source_ids", 0, "external_id"): "x"}),
    ("an entity_id of another external_id", {
        ("entity_id",): rfc4122_uuid5(NAMESPACE, 'entity|hla-rpr2|["example-001","1","1","2",'
                                                 '"3","2"]')}),
)


#: Members the CDM schema lets an Entity omit (they have defaults) and the profile always
#: writes (R32's nulls, R27's source, R30's position, SPEC:146's three motion members).
OMITTED = (("symbol",), ("valid_to",), ("kinematics",), ("source", "observed_at"),
           ("source", "format_version"), ("position", "vertical"), ("position", "accuracy_m"),
           ("kinematics", "course_deg"))


@case("G-R44")
@pytest.mark.parametrize("path", OMITTED, ids=["/".join(p) for p in OMITTED])
def test_an_omitted_member_is_refused_though_the_schema_admits_it(path):
    payload = copy.deepcopy(FIRST_UPSERT)
    node = payload
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    assert _schema.entity_validator().is_valid(payload)
    with pytest.raises(ProjectionDefect):
        projector.check_entity_payload(payload)


@case("G-R44")
def test_the_entity_validators_check_formats_and_read_anchors_as_ecma_262():
    """R44 'with format checking': the CDM validator asserts `uuid` and reads `^...$` as
    ECMA-262 does (no match before a final newline), as the SDK validates its published
    schemas; the provenance validator carries the same format checker."""
    validator = _schema.entity_validator()
    assert "uuid" in validator.format_checker.checkers
    assert not validator.is_valid(changed(FIRST_UPSERT, {("entity_id",): "not-a-uuid"}))
    assert not validator.is_valid(changed(FIRST_UPSERT, {("valid_from",):
                                                         "2026-01-01T00:00:01.000Z\n"}))
    assert not validator.is_valid(changed(FIRST_UPSERT, {("source", "adapter_version"):
                                                         "1.0.0\n"}))
    provenance = _schema.checked_validator("hla-provenance.schema.json")
    assert provenance.format_checker is not None
    assert "uuid" in provenance.format_checker.checkers


@case("G-R44")
@pytest.mark.parametrize("what,changes", BROKEN, ids=[b[0] for b in BROKEN])
def test_every_rule_of_the_entity_check_refuses_its_breach(what, changes):
    """R44: every Entity is validated against the CDM schema with format checking (the SDK's
    validator: ECMA-262 anchors, format asserted), its provenance block against its schema, its
    timestamps by explicit code, and the profile's assertions; each breach is a defect."""
    projector.check_entity_payload(copy.deepcopy(FIRST_UPSERT))
    with pytest.raises(ProjectionDefect):
        projector.check_entity_payload(changed(FIRST_UPSERT, changes))


@case("G-R44")
def test_dates_are_judged_by_explicit_code_not_by_the_schema():
    """OPS-03: the schemas' date forms are patterns (and `format: date-time`, which the
    installed jsonschema does not check), so a day that does not exist passes the CDM schema and
    the provenance schema; only the explicit check of `_utc` refuses it."""
    both = changed(FIRST_UPSERT, {("valid_from",): "2026-02-30T00:00:01.000Z",
                                  ("attributes", "hla", "time", "effective_at"):
                                  "2026-02-30T00:00:01.000000Z"})
    assert _schema.entity_validator().is_valid(both)
    assert _schema.checked_validator("hla-provenance.schema.json").is_valid(
        both["attributes"]["hla"])
    # The two name the same (impossible) instant, so only a calendar check can refuse them.
    with pytest.raises(ProjectionDefect):
        projector.check_entity_payload(both)


@case("G-R44")
@pytest.mark.parametrize("seed", [44, 4444])
def test_the_entity_check_meets_hostile_values_with_a_defect_only(seed):
    """CR-R2-24 next to the Entity check: hostile values anywhere in a fixture Entity give
    ProjectionDefect or acceptance, never another exception, and the payload is not changed."""
    rng = random.Random(seed)
    outcomes = set()
    for _ in range(300):
        payload = copy.deepcopy(FIRST_UPSERT)
        for _ in range(rng.randint(1, 2)):
            target = rng.choice(_containers(payload, []))
            if type(target) is list:
                if target:
                    target[rng.randrange(len(target))] = rng.choice(_hostile_values())
                continue
            key = rng.choice(sorted(target) + ["x", "\ud800"])
            target[key] = rng.choice(_hostile_values())
        before = _fingerprint(payload)
        try:
            projector.check_entity_payload(payload)
        except ProjectionDefect:
            outcomes.add("defect")
        else:
            outcomes.add("accepted")
        assert _fingerprint(payload) == before
    assert "defect" in outcomes


@case("G-R44")
def test_the_fixture_upserts_pass_the_entity_check():
    for _, record in OBSERVATIONS:
        if record["kind"] == "upsert":
            projector.check_entity_payload(copy.deepcopy(record["payload"]))
    with pytest.raises(ProjectionDefect):
        projector.check_entity_payload([FIRST_UPSERT])


def _broken_position(value):
    return geodesy.Projection({"lat": 91.0, "lon": 0.0, "alt_m": 0.0}, None)


@case("G-R44")
@pytest.mark.parametrize("target,attribute,replacement", [
    (geodesy, "project_spatial", _broken_position),                         # schema
    (_utc, "format_millisecond", lambda us: "2026-02-30T00:00:01.000Z"),   # explicit date check
    (projector._identity, "entity_id", lambda external: "not-a-uuid"),      # format checker
    (projector, "entity_bytes", lambda entity: b"{}"),                      # model round trip
], ids=["schema", "timestamp", "uuid-format", "round-trip"])
def test_project_state_checks_every_entity_before_returning_it(monkeypatch, target, attribute,
                                                               replacement):
    """R44 inside project_state: an Entity that would break the schema, a timestamp, the uuid
    format or the model's round trip is never returned; it raises ProjectionDefect, never a
    suppression and never HlaError (a defect is not a data fault)."""
    monkeypatch.setattr(target, attribute, replacement)
    caller_bug(ProjectionDefect, lambda: project(make_snapshot()))


def test_a_rule_only_the_profile_check_holds_is_still_enforced(monkeypatch):
    """Motion from a static variant is valid CDM and the model accepts it; only the profile's
    own assertion refuses it (SPEC:146: no motion for algorithm 1), so an Entity built so by a
    defective section 9 never leaves project_state."""
    monkeypatch.setattr(geodesy, "project_spatial", lambda value: geodesy.Projection(
        {"lat": 0.0, "lon": 0.0, "alt_m": 0.0}, motion(1.0, 0.0, 0.0)))
    snapshot = make_snapshot(spatial=spatial_slot(1, velocity=None))
    error = caller_bug(ProjectionDefect, lambda: project(snapshot))
    assert "WORLD velocity" in str(error)


def test_the_model_is_a_second_guard(monkeypatch):
    """With the payload check switched off, synapse_cdm.models.Entity itself refuses a latitude
    past 90 on the JSON path, and project_state reports that as a defect."""
    monkeypatch.setattr(projector, "check_entity_payload", lambda payload: None)
    monkeypatch.setattr(geodesy, "project_spatial", _broken_position)
    error = caller_bug(ProjectionDefect, lambda: project(make_snapshot()))
    assert "refuses" in str(error)


def test_entity_payload_and_bytes_take_an_entity_only():
    entity = project(make_snapshot())
    assert projector.entity_payload(entity) == FIRST_UPSERT
    assert projector.entity_bytes(entity) == payload_bytes(FIRST_UPSERT)
    for wrong in (FIRST_UPSERT, None, Suppression(("MISSING_SPATIAL",))):
        caller_bug(TypeError, lambda: projector.entity_payload(wrong))
        caller_bug(TypeError, lambda: projector.entity_bytes(wrong))


def _imports(module_name):
    import ast
    import pathlib
    source = pathlib.Path(sys.modules[module_name].__file__).read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _package_modules():
    import pkgutil
    found = ["synapse_hla"]
    for info in pkgutil.iter_modules(synapse_hla.__path__):
        found.append(f"synapse_hla.{info.name}")
    for name in found:
        __import__(name)
    return found


@case("G-R44")
def test_no_dis_or_kml_code_is_imported_and_the_sdk_is_used_only_for_the_entity():
    """R44: 'Do not import DIS7 or KML to implement HLA decoding.' No module of the package
    imports anything with dis or kml in its name, nor any CDM adapter; the SDK is used for
    exactly two things, the Entity model and its schema validator."""
    sdk = set()
    for module in _package_modules():
        for name in _imports(module):
            parts = name.lower().split(".")
            assert not any("dis" in p or "kml" in p for p in parts if p != "dataclasses"), name
            assert not name.startswith("synapse_cdm.adapters"), name
            if name.split(".")[0] == "synapse_cdm":
                sdk.add(name)
    assert sdk == {"synapse_cdm.models", "synapse_cdm.schemas"}


@case("G-R30")
def test_section_9_is_implemented_once_in_geodesy():
    """One implementation of the section 9 formulas: no module but geodesy uses trigonometry,
    square roots or decimal rounding, so the projector cannot hold a second copy of the ENU or
    geodetic arithmetic (exit criterion 4 of round R3)."""
    import ast
    import pathlib
    section_9 = {"sin", "cos", "tan", "asin", "acos", "atan", "atan2", "hypot", "degrees",
                 "radians", "sqrt", "fmod", "fsum", "pi"}
    for module in _package_modules():
        tree = ast.parse(pathlib.Path(sys.modules[module].__file__).read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "math"}
        rounds = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "round"]
        if module == "synapse_hla.geodesy":
            assert {"sin", "cos", "atan2", "hypot", "degrees", "sqrt"} <= used and rounds
        else:
            assert not (used & section_9) and not rounds, module


# ============================================================ arguments outside the contract

def _deep(levels):
    value = []
    for _ in range(levels):
        value = [value]
    return value


def _with(snapshot, path, value):
    return changed(snapshot, {path: value})


def _ctx_with(**members):
    def build(snapshot):
        context = make_context(snapshot)
        context.update(members)
        return context
    return build


def _ctx_without(member):
    def build(snapshot):
        context = make_context(snapshot)
        del context[member]
        return context
    return build


S = make_snapshot()
SPATIAL_PATH = ("attributes", "Spatial")
#: 512 two-byte characters: exactly 1024 UTF-8 bytes.
_BYTES_1024 = "\N{LATIN SMALL LETTER E WITH ACUTE}" * 512
_ALL_ABSENT = make_snapshot(ei=ABSENT_SLOT, et=ABSENT_SLOT, force=ABSENT_SLOT, spatial=ABSENT_SLOT,
                            identity=None, incarnation=None)


class _Str(str):
    pass


#: (what, the snapshot, a context builder or None for the matching one, the exception).
CALLER_BUGS = (
    ("snapshot a tuple", ("x",), lambda s: make_context(S), TypeError),
    ("a set in the snapshot", _with(S, ("name",), {"x"}), None, TypeError),
    ("a non-str member name", {**S, 1: "x"}, None, TypeError),
    ("a str subclass", _with(S, ("name",), _Str("x")), None, TypeError),
    ("bytes as hex", _with(S, SPATIAL_PATH + ("hex",), b"00"), None, TypeError),
    ("context bytes", S, lambda s: dict(make_context(s), sha256=SEQ5_SHA.encode()), TypeError),
    ("snapshot a list", [S], lambda s: make_context(S), ValueError),
    ("snapshot null", None, lambda s: make_context(S), ValueError),
    ("no lifecycle", {k: v for k, v in S.items() if k != "lifecycle"}, None, ValueError),
    ("an extra member", {**S, "tag_hex": ""}, None, ValueError),
    ("lifecycle REMOVED", _with(S, ("lifecycle",), "REMOVED"), None, ValueError),
    ("nesting past 32", _with(S, ("changed_attributes",), _deep(40)), None, ValueError),
    ("an integer past 2^53 - 1", _with(S, ("last_revision",), 2 ** 53), None, ValueError),
    ("an integer Python cannot print", _with(S, ("last_revision",), 10 ** 5000), None,
     ValueError),
    ("a NaN", _with(S, SPATIAL_PATH + ("value", "position_ecef_m", 0), math.nan), None,
     ValueError),
    ("a lone surrogate", _with(S, ("name",), "a\udc80"), None, ValueError),
    ("ABSENT with a hex", _with(make_snapshot(force=ABSENT_SLOT),
                                ("attributes", "ForceIdentifier", "hex"), "01"), None,
     ValueError),
    ("VALID without a hex", _with(S, SPATIAL_PATH + ("hex",), None), None, ValueError),
    ("VALID without a value", _with(S, SPATIAL_PATH + ("value",), None), None, ValueError),
    ("INVALID with a value", _with(S, SPATIAL_PATH + ("status",), "INVALID"), None, ValueError),
    ("a value its hex does not hold", _with(S, SPATIAL_PATH + ("value", "position_ecef_m", 0),
                                            6378138.0), None, ValueError),
    ("an int where the hex holds a float", _with(S, SPATIAL_PATH + ("value", "position_ecef_m",
                                                                    0), 6378137), None,
     ValueError),
    ("+0.0 where the hex holds -0.0", _with(make_snapshot(spatial=spatial_slot(
        position=(WGS_A, -0.0, 0.0))), SPATIAL_PATH + ("value", "position_ecef_m", 1), 0.0),
     None, ValueError),
    ("VALID bytes that do not decode", _with(S, ("attributes", "EntityIdentifier", "hex"),
                                             "0001000200"), None, ValueError),
    ("effective_at a microsecond off", _with(S, SPATIAL_PATH + ("effective_at",),
                                             "2026-01-01T00:00:01.000001Z"), None, ValueError),
    ("no effective_at under external_elapsed", _with(S, SPATIAL_PATH + ("effective_at",), None),
     None, ValueError),
    ("an INVALID with no effective_at", make_snapshot(force=invalid_slot(bytes(2), seq=5,
                                                                         at=None)),
     None, ValueError),
    ("an attribute after the triggering frame", _with(S, SPATIAL_PATH + ("seq",), 6), None,
     ValueError),
    # JSON Schema counts 5.0 as an integer, and the output writer would spell it 5.0 where the
    # same state with 5 writes 5 (review finding R3-r1-F1): every integer of the snapshot is an
    # exact int. One row per slot, each the fixture's own seq as a float (3, 3, 4, 5); one on an
    # INVALID slot; and the one integer that reaches no output.
    ("EntityIdentifier seq 3.0", _with(S, ("attributes", "EntityIdentifier", "seq"), 3.0), None,
     ValueError),
    ("EntityType seq 3.0", _with(S, ("attributes", "EntityType", "seq"), 3.0), None,
     ValueError),
    ("ForceIdentifier seq 4.0", _with(S, ("attributes", "ForceIdentifier", "seq"), 4.0), None,
     ValueError),
    ("Spatial seq 5.0", _with(S, SPATIAL_PATH + ("seq",), 5.0), None, ValueError),
    ("an INVALID slot's seq 5.0", _with(make_snapshot(force=invalid_slot(bytes(2))),
                                        ("attributes", "ForceIdentifier", "seq"), 5.0), None,
     ValueError),
    ("last_revision 0.0", _with(S, ("last_revision",), 0.0), None, ValueError),
    # A bool where the schema says integer (review finding R3-r2-F1): True < 5 and True is
    # not None, so nothing after the schema would notice, and the Entity would carry `true` as
    # a sequence number.
    ("EntityType seq True", _with(S, ("attributes", "EntityType", "seq"), True), None,
     ValueError),
    # SPEC:283: every member of an ABSENT slot is null, not only its hex (review finding
    # R3-r2-F3). Each row sets one member on the otherwise ABSENT force slot.
    ("ABSENT with a value", _with(make_snapshot(force=ABSENT_SLOT),
                                  ("attributes", "ForceIdentifier", "value"), {"value": 1}),
     None, ValueError),
    ("ABSENT with a seq", _with(make_snapshot(force=ABSENT_SLOT),
                                ("attributes", "ForceIdentifier", "seq"), 4), None, ValueError),
    ("ABSENT with an elapsed_ns", _with(make_snapshot(force=ABSENT_SLOT),
                                        ("attributes", "ForceIdentifier", "elapsed_ns"), "0"),
     None, ValueError),
    ("ABSENT with an effective_at", _with(make_snapshot(force=ABSENT_SLOT),
                                          ("attributes", "ForceIdentifier", "effective_at"),
                                          EPOCH), None, ValueError),
    ("identity not the context's", S, _ctx_with(identity=ident(9, 9, 9)), ValueError),
    ("incarnation not the context's", S, _ctx_with(incarnation=2), ValueError),
    ("identity not the context's while suppressed", make_snapshot(spatial=ABSENT_SLOT),
     _ctx_with(identity=ident(9, 9, 9)), ValueError),
    ("an identity the context does not hold", make_snapshot(spatial=ABSENT_SLOT),
     _ctx_with(identity=None, incarnation=None), ValueError),
    ("incarnation not the context's while suppressed", make_snapshot(spatial=ABSENT_SLOT),
     _ctx_with(incarnation=3), ValueError),
    ("an identity without incarnation", make_snapshot(incarnation=None), None, ValueError),
    ("the null identity", make_snapshot(identity=ident(0, 0, 0)), None, ValueError),
    ("eligible with another identity", make_snapshot(identity=ident(9, 9, 9)), None,
     ValueError),
    ("eligible with no identity", make_snapshot(identity=None, incarnation=None), None,
     ValueError),
    ("a name over 1024 UTF-8 bytes", make_snapshot(name="\N{LATIN SMALL LETTER E WITH ACUTE}"
                                                        * 513), None, ValueError),
    ("a class over 1024 UTF-8 bytes", make_snapshot(reported_class="\N{EURO SIGN}" * 342), None,
     ValueError),
    # One byte past each limit (review finding R3-r2-F3): 512 two-byte characters are 1024
    # bytes, one ASCII letter more is 1025; the accepted 1024 is in
    # test_the_name_limits_are_inclusive_utf8_byte_counts.
    ("a name of 1025 UTF-8 bytes", make_snapshot(name=_BYTES_1024 + "a"), None, ValueError),
    ("a class of 1025 UTF-8 bytes", make_snapshot(reported_class=_BYTES_1024 + "a"), None,
     ValueError),
    ("context without seq", S, _ctx_without("seq"), ValueError),
    ("context with more", S, _ctx_with(frame="x"), ValueError),
    ("context a list", S, lambda s: [make_context(s)], ValueError),
    ("generation 0", S, _ctx_with(generation=0), ValueError),
    ("generation true", S, _ctx_with(generation=True), ValueError),
    ("generation text", S, _ctx_with(generation="1"), ValueError),
    ("generation past 2^53 - 1", S, _ctx_with(generation=2 ** 53), ValueError),
    ("token o0", S, _ctx_with(object_token="o0"), ValueError),
    ("token x1", S, _ctx_with(object_token="x1"), ValueError),
    ("token of 17 characters", S, _ctx_with(object_token="o" + "1" * 16), ValueError),
    ("token with a newline", S, _ctx_with(object_token="o1\n"), ValueError),
    ("identity a list", S, _ctx_with(identity=[1, 2, 3]), ValueError),
    ("identity of two members", S, _ctx_with(identity={"site": 1, "application": 2}),
     ValueError),
    ("incarnation 0", S, _ctx_with(incarnation=0), ValueError),
    ("seq 0", S, _ctx_with(seq=0), ValueError),
    ("digest in capitals", S, _ctx_with(sha256=SEQ5_SHA.upper()), ValueError),
    ("digest of 63 digits", S, _ctx_with(sha256=SEQ5_SHA[:63]), ValueError),
    ("completion 1", S, _ctx_with(capture_complete=1), ValueError),
    ("completion text", S, _ctx_with(capture_complete="true"), ValueError),
    # The counters' lower bound on a suppressed state (review finding R3-r2-F3), where no
    # identity derivation or slot comparison downstream would refuse a 0 by itself: generation
    # 0 with Spatial ABSENT, and seq 0 with every slot ABSENT and no identity. Incarnation 0
    # cannot be isolated that way: the snapshot's own schema refuses it (minimum 1) and the
    # context must equal the snapshot, so the row holds the refusal, not the bound alone.
    ("generation 0 while suppressed", make_snapshot(spatial=ABSENT_SLOT),
     _ctx_with(generation=0), ValueError),
    ("seq 0 while suppressed", _ALL_ABSENT, _ctx_with(seq=0), ValueError),
    ("incarnation 0 while suppressed", make_snapshot(spatial=ABSENT_SLOT, incarnation=0), None,
     ValueError),
)


@pytest.mark.parametrize("field", ["name", "reported_class"])
def test_the_name_limits_are_inclusive_utf8_byte_counts(field):
    """SPEC:223-224, SPEC:289: 1024 UTF-8 bytes is within the limit (512 two-byte characters,
    512 characters for the schema's maxLength) and projects; 1025 is a caller bug (the
    CALLER_BUGS rows), so the bound is inclusive and counted in bytes."""
    snapshot = make_snapshot(**{field: _BYTES_1024})
    assert len(_BYTES_1024.encode("utf-8")) == 1024 and len(_BYTES_1024) == 512
    payload = entity_of(project(snapshot))
    assert payload["attributes"]["hla"][field] == _BYTES_1024


@pytest.mark.parametrize("what,snapshot,context,exception", CALLER_BUGS,
                         ids=[c[0] for c in CALLER_BUGS])
def test_arguments_outside_the_contract_are_caller_bugs(what, snapshot, context, exception):
    """The arguments are the reducer's state: a Python value that is not JSON is TypeError,
    JSON outside the contract is ValueError (plain: HlaError is a ValueError too, and must not
    be mistaken for one), and nothing here is HlaError. Unless a row says otherwise, the context
    is the one that matches the row's snapshot, so each row breaks one rule only."""
    built = make_context(snapshot) if context is None else context(snapshot)
    caller_bug(exception, lambda: project_state(snapshot, built))


@pytest.mark.parametrize("path,value,fragment", [
    (("last_revision",), 2 ** 53, "2^53"),
    (("last_revision",), 10 ** 5000, "2^53"),
    (SPATIAL_PATH + ("value", "position_ecef_m", 0), 10 ** 5000, "2^53"),
    (SPATIAL_PATH + ("value", "position_ecef_m", 0), math.nan, "not finite"),
    (SPATIAL_PATH + ("value", "position_ecef_m", 0), -math.inf, "not finite"),
    (("name",), "\ud800", "lone surrogate"),
    (("changed_attributes",), _deep(40), "nests deeper"),
], ids=["2^53", "10^5000", "10^5000-in-a-value", "nan", "-inf", "surrogate", "deep"])
def test_the_copy_refuses_what_json_cannot_carry_before_anything_reads_it(path, value,
                                                                          fragment):
    """Integers beyond 2^53 - 1, non-finite numbers, lone surrogates and deep nesting are
    refused by the copy, before the schema or the decoder sees them: otherwise an integer of
    5000 digits would surface as the interpreter's own conversion error from inside the schema
    validator, and a NaN would compare unequal to everything (R2-F1). The message is checked
    only to tell the product's refusal from such an accidental one."""
    error = caller_bug(ValueError, lambda: project_state(_with(S, path, value), make_context(S)))
    assert fragment in str(error)


def test_a_self_containing_snapshot_is_refused_not_recursed():
    snapshot = make_snapshot()
    snapshot["attributes"]["self"] = snapshot
    caller_bug(ValueError, lambda: project_state(snapshot, make_context(make_snapshot())))


@pytest.mark.parametrize("config,path", [
    (config_with(session_id="a b"), "/session_id"),
    (config_with(time_policy={"mode": "external_elapsed", "epoch": "2026-02-30T00:00:00.000000Z",
                              "basis": "b"}), "/time_policy/epoch"),
    (config_with(force_map={"256": "HOSTILE"}), "/force_map/256"),
    ([CONFIG], ""),
    # What JSON cannot carry is validate_config's to refuse too, with its own pointer (review
    # finding R3-r1-F4): a non-finite number and an integer past 2^53 - 1 at the member
    # (CR-R2-11/12, CR-R2-16), a lone surrogate at the member that holds it, nesting past 32 at
    # the whole document. The pointers are those R2's tests fix for validate_config itself.
    (config_with(source_system=math.nan), "/source_system"),
    (config_with(force_map={"1": 2 ** 53}), "/force_map/1"),
    (config_with(force_map={"1": 10 ** 5000}), "/force_map/1"),
    (config_with(x=_deep(40)), ""),
    (config_with(source_system="a\udc80"), "/source_system"),
], ids=["session-id", "epoch", "force-256", "not-an-object", "nan", "2^53", "10^5000", "deep",
        "surrogate"])
def test_a_configuration_validate_config_refuses_is_e_config(config, path):
    """The context's configuration is the session's, held to validate_config: E_CONFIG at its
    pointer (CR-L01), as the capture header's would be. The projector hands it over as it came,
    so the refusal is validate_config's own, whatever the fault."""
    context = make_context(S)
    context["config"] = config
    error = refusal(lambda: project_state(S, context))
    assert (error.code, error.path) == ("E_CONFIG", path)


def test_a_self_containing_configuration_is_e_config_at_the_document():
    """validate_config refuses a mapping that contains itself as nesting past 32 levels, at the
    whole document (R2's test of validate_config fixes the pointer); the projector does not
    turn that into a ValueError of its own."""
    config = copy.deepcopy(CONFIG)
    config["force_map"] = config
    context = make_context(S)
    context["config"] = config
    error = refusal(lambda: project_state(S, context))
    assert (error.code, error.path) == ("E_CONFIG", "")


@pytest.mark.parametrize("config", [
    config_with(source_system=b"x"), config_with(source_system=_Str("x")),
    config_with(force_map=MappingProxyType({})), config_with(time_policy=object()),
], ids=["bytes", "str-subclass", "mappingproxy", "object"])
def test_a_configuration_that_is_not_json_is_a_caller_bug(config):
    """CR-R2-16 at the projector: a configuration holding a Python value that is not JSON is
    validate_config's TypeError, not HlaError."""
    context = make_context(S)
    context["config"] = config
    caller_bug(TypeError, lambda: project_state(S, context))


def test_a_hostile_member_name_reaches_a_message_only_as_safe_text():
    """CR-R0-04 and CR-R1-04 for the refusals here: a member name from the caller is quoted in
    a message only through errors.safe_text (refused code points replaced, 64 characters)."""
    for name, shown in (("\N{RIGHT-TO-LEFT OVERRIDE}x", "\N{REPLACEMENT CHARACTER}x"),
                        ("k" * 10_000, "k" * 64),
                        ("\x1b[2J", "\N{REPLACEMENT CHARACTER}[2J")):
        error = caller_bug(ValueError, lambda: project_state({**S, name: 1}, make_context(S)))
        assert f"'/{shown}'" in str(error)
        assert name not in str(error) or name == shown


# ========================================================================== purity, R3 seams

def test_the_arguments_are_only_read_and_nothing_is_shared():
    """reduce_frame's contract applies here too: no argument is changed, and the Entity shares
    no object with them, so neither side can change the other afterwards."""
    snapshot, context = make_snapshot(), make_context(make_snapshot())
    kept = (copy.deepcopy(snapshot), copy.deepcopy(context))
    entity = project_state(snapshot, context)
    assert (snapshot, context) == kept
    data = projector.entity_bytes(entity)
    snapshot["attributes"]["Spatial"]["value"]["position_ecef_m"][0] = 0.0
    snapshot["name"] = "CHANGED"
    context["config"]["force_map"]["1"] = "HOSTILE"
    assert projector.entity_bytes(entity) == data
    entity.attributes["hla"]["spatial"]["orientation_rad"][0] = 9.0
    assert kept[0]["attributes"]["Spatial"]["value"]["orientation_rad"][0] == 0.0
    fresh = project_state(kept[0], kept[1])
    assert projector.entity_bytes(fresh) == data
    suppressed = untimed(make_snapshot())
    kept = copy.deepcopy(suppressed)
    project_state(suppressed, make_context(suppressed, config=NONE_POLICY))
    assert suppressed == kept


def test_projection_opens_nothing_once_warm():
    """D-08: the projector reads no file, clock, process or socket. Once the packaged schemas
    are loaded (the first call reads them through `_resources`), projecting an eligible and a
    suppressed state raises no audit event of the file, OS, socket, process or time families,
    in a fresh interpreter with an audit hook installed."""
    script = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(PACKAGE_ROOT / 'src')!r})\n"
        "from synapse_hla import projector\n"
        f"fixtures = {str(PACKAGE_ROOT / 'src/synapse_hla/fixtures')!r}\n"
        "records = [json.loads(line) for line in open(fixtures + '/expected.observations.jsonl',"
        " 'rb').read().splitlines()]\n"
        "capture = [json.loads(line) for line in open(fixtures + '/session.capture.jsonl',"
        " 'rb').read().splitlines()]\n"
        "frames = {r['seq']: r for r in capture if r['type'] == 'frame'}\n"
        "def context(r):\n"
        "    f = frames[r['seq']]\n"
        "    return {'config': capture[0]['config'], 'generation': 1, 'object_token': 'o1',\n"
        "            'identity': r['payload']['identity'], 'incarnation': 1, 'seq': f['seq'],\n"
        "            'sha256': f['sha256'], 'capture_complete': True}\n"
        "for r in (records[2], records[0]):\n"
        "    projector.project_state(r['payload'], context(r))\n"
        "events = []\n"
        "sys.addaudithook(lambda event, args: events.append(event))\n"
        "for r in (records[2], records[0], records[4]):\n"
        "    projector.project_state(r['payload'], context(r))\n"
        "print(json.dumps(sorted(set(events))))\n")
    proc = run_python(["-c", script], cwd=PACKAGE_ROOT)
    assert proc.returncode == 0, proc.stderr[-2000:]
    events = json.loads(proc.stdout.strip().splitlines()[-1])
    forbidden = ("open", "os.", "socket.", "subprocess.", "shutil.", "glob.", "ctypes.",
                 "urllib.", "http.", "time.", "fcntl.", "mmap.", "pty.", "sqlite3.")
    assert not [e for e in events if e == "open" or e.startswith(forbidden)], events


# ========================================================== hostile values (CR-R2-24)

class _Int(int):
    pass


def _hostile_values():
    """A fresh list on every call, so that no hostile object is shared between two places.
    The integral floats (5.0, 3.0, 1e0, and -0.0) are integers to JSON Schema and floats to the
    output writer (review finding R3-r1-F1)."""
    from collections import OrderedDict
    return [10 ** 5000, -10 ** 5000, 2 ** 53, -(2 ** 53), 2 ** 53 - 1, 0, -1, 1.5, -0.0, 1e308,
            5.0, 3.0, 1e0,
            math.nan, math.inf, -math.inf, True, False, None, "", "x" * 70_000, "\ud800",
            "a\udfff", "\x00", "\N{RIGHT-TO-LEFT OVERRIDE}", "o1", "ABSENT", "VALID", "INVALID",
            "QUARANTINED", "00", "zz", "0" * 9000, [], {}, [[[[]]]], _deep(40), [10 ** 5000],
            {"k": {"k": -10 ** 5000}}, (1, 2), {1, 2}, b"00", bytearray(b"00"),
            OrderedDict(a=1), MappingProxyType({}), _Str("x"), _Int(1), object(),
            ident(0, 0, 0), ident(70000, 0, 0), copy.deepcopy(ABSENT_SLOT),
            invalid_slot(bytes(3)), {"\ud800": 1}, {"a/b~": 1}]


def _containers(value, out):
    if type(value) is dict:
        out.append(value)
        for item in value.values():
            _containers(item, out)
    elif type(value) is list:
        out.append(value)
        for item in value:
            _containers(item, out)
    return out


def _fingerprint(value, depth=0):
    """A comparable record of a value tree that survives NaN and integers repr refuses."""
    if depth > 50:
        return "deep"
    kind = type(value)
    if kind is dict:
        return ("dict", tuple((_fingerprint(k, depth + 1), _fingerprint(v, depth + 1))
                              for k, v in value.items()))
    if kind is list:
        return ("list", tuple(_fingerprint(v, depth + 1) for v in value))
    if kind is int:
        return ("int", hex(value))
    if kind is float:
        return ("float", value.hex())
    if kind in (str, bool, type(None)):
        return (kind.__name__, value)
    return (kind.__name__, id(value))


#: The seeds of the hostile-value corpus (CR-R2-24); the CR-L17 equivalence reuses the corpus.
HOSTILE_SEEDS = (3, 2026, 101010)


def _hostile_pairs(seed: int, count: int = 400):
    """The seeded corpus of CR-R2-24: `count` pairs of an eligible or a suppressed snapshot and
    its context, each with one to three hostile changes (members replaced, added and removed;
    integers past 2^53 and past what Python prints, lone surrogates, deep nesting, hostile member
    names, non-JSON types). The same seed gives the same pairs."""
    rng = random.Random(seed)
    starts = [make_snapshot(), untimed(make_snapshot()), make_snapshot(spatial=ABSENT_SLOT)]
    for _ in range(count):
        base = rng.choice(starts)
        snapshot = copy.deepcopy(base)
        context = make_context(base, config=NONE_POLICY if base is starts[1] else None)
        for _ in range(rng.randint(1, 3)):
            target = rng.choice(_containers(rng.choice([snapshot, context]), []))
            roll = rng.random()
            if type(target) is list:
                if target and roll < 0.2:
                    del target[rng.randrange(len(target))]
                elif target:
                    target[rng.randrange(len(target))] = rng.choice(_hostile_values())
                else:
                    target.append(rng.choice(_hostile_values()))
                continue
            if target and roll < 0.15:
                del target[rng.choice(sorted(target))]
                continue
            key = rng.choice(sorted(target) + ["x", "\ud800", "\N{RIGHT-TO-LEFT OVERRIDE}",
                                               "k" * 300])
            target[key] = rng.choice(_hostile_values())
        yield snapshot, context


@pytest.mark.parametrize("seed", HOSTILE_SEEDS)
def test_hostile_values_anywhere_give_only_documented_outcomes(seed):
    """CR-R2-24: a seeded fuzz of hostile Python values put anywhere in an eligible or a
    suppressed snapshot and in its context (members replaced, added and removed; integers past
    2^53 and past what Python prints, lone surrogates, deep nesting, hostile member names,
    non-JSON types). Every outcome is an Entity, a Suppression, HlaError with a catalogue code,
    or the documented TypeError / ValueError of a caller bug; never another exception, and the
    arguments are never changed."""
    outcomes = {}
    for snapshot, context in _hostile_pairs(seed):
        before = (_fingerprint(snapshot), _fingerprint(context))
        try:
            result = project_state(snapshot, context)
        except HlaError as error:
            assert type(error) is HlaError and error.code in errors.CODES
            kind = error.code
        except (TypeError, ValueError) as error:
            assert type(error) in (TypeError, ValueError), type(error)
            kind = type(error).__name__
        else:
            assert type(result) in (Entity, Suppression)
            kind = type(result).__name__
            if kind == "Entity":
                assert _integer_members_are_ints(result), projector.entity_bytes(result)
        assert (_fingerprint(snapshot), _fingerprint(context)) == before
        outcomes[kind] = outcomes.get(kind, 0) + 1
    assert {"ValueError", "TypeError", "E_CONFIG"} <= set(outcomes), outcomes


def _integer_members_are_ints(entity) -> bool:
    """Every member of an Entity that hla-provenance.schema.json and the CDM schema type as an
    integer is a Python int, never an integral float (R3-r1-F1): the generation, the identifier
    and EntityType fields, the force value, the Spatial algorithm, the four attribute sequences,
    the time block's spatial_seq and the source's record_index. Listed by hand from the two
    schemas."""
    hla = entity.attributes["hla"]
    values = [hla["generation"], hla["spatial"]["algorithm"], hla["time"]["spatial_seq"],
              entity.source.record_index]
    values += list(hla["identifier"].values()) + list(hla["entity_type"].values())
    values += [v for v in hla["attribute_sequences"].values() if v is not None]
    if hla["force_identifier"] is not None:
        values.append(hla["force_identifier"])
    return all(type(v) is int for v in values)


# ======================================================================= the CDM's timestamp

@pytest.mark.parametrize("text,microsecond", [
    ("1970-01-01T00:00:00.000Z", 0),
    ("2026-01-01T00:00:01.000Z", 1767225601000000),
    ("2026-01-01T00:00:01.234Z", 1767225601234000),
    ("2028-02-29T00:00:00.000Z", 1835395200000000),
    ("9998-12-31T23:59:59.999Z", 253370764799999000),
])
def test_the_millisecond_timestamp_is_parsed_by_explicit_code(text, microsecond):
    """`_utc.parse_millisecond`: the CDM's form, by hand: 2026-01-01 is day 20454 after
    1970-01-01 (56 years, 14 leap days: 56 * 365 + 14), so 20454 * 86400 + 1 seconds; 2028-02-29
    is day 21243 (20454 + 365 + 365 + 59); 9998-12-31T23:59:59.999 is one millisecond less one
    microsecond before _utc.MAX_MICROSECOND + 1."""
    assert _utc.parse_millisecond(text) == microsecond


@pytest.mark.parametrize("text", [
    "2026-01-01T00:00:01.000000Z", "2026-01-01T00:00:01.00Z", "2026-01-01T00:00:01Z",
    "2026-02-29T00:00:00.000Z", "2026-02-30T00:00:00.000Z", "2026-04-31T00:00:00.000Z",
    "2026-13-01T00:00:00.000Z", "2026-01-01T24:00:00.000Z", "1969-12-31T23:59:59.999Z",
    "9999-01-01T00:00:00.000Z", "2026-01-01T00:00:01.000Z\n", "2026-01-01 00:00:01.000Z",
    "\N{ARABIC-INDIC DIGIT TWO}026-01-01T00:00:01.000Z",
])
def test_the_millisecond_timestamp_refuses_every_other_form(text):
    caller_bug(ValueError, lambda: _utc.parse_millisecond(text))
    caller_bug(TypeError, lambda: _utc.parse_millisecond(text.encode("utf-8")))


# ============================================================ the session's validated configuration

def test_a_validated_config_is_projected_without_another_validation(monkeypatch):
    """CR-L07: the reducer validates the session's configuration once and hands the projector a
    `config.ValidatedConfig`, which is trusted as it is: with `validate_config` counting its
    calls, the fixture's snapshot projects through the wrapper to the bundle's first upsert byte
    for byte and the count stays 0; the same snapshot with the plain mapping still goes through
    `validate_config` once (CR-R3-03 unchanged) and gives the same bytes."""
    from synapse_hla import config as config_module
    validated = config_module.validated_config(CONFIG)
    calls = []
    real = config_module.validate_config

    def counted(mapping):
        calls.append(1)
        return real(mapping)
    monkeypatch.setattr(config_module, "validate_config", counted)
    through_wrapper = project(make_snapshot(), config=validated)
    assert calls == []
    assert projector.entity_bytes(through_wrapper) == payload_bytes(FIRST_UPSERT)
    through_mapping = project(make_snapshot())
    assert calls == [1]
    assert projector.entity_bytes(through_mapping) == payload_bytes(FIRST_UPSERT)


def test_a_validated_config_gives_the_same_answers_as_its_mapping():
    """The suppressions and the session's E_CONFIG are the same through the wrapper: time policy
    none suppresses with TIME_UNRESOLVED alone, and an effective time one microsecond past
    9998-12-31T23:59:59.999999Z is E_CONFIG at the epoch, whichever form the configuration has."""
    from synapse_hla import config as config_module
    untimed = config_with(time_policy={"mode": "none"})
    snapshot = make_snapshot(ei=ident_slot(at=None), et=type_slot(at=None),
                             force=force_slot(at=None), spatial=spatial_slot(at=None))
    for given in (untimed, config_module.validated_config(untimed)):
        assert project(snapshot, config=given) == Suppression(("TIME_UNRESOLVED",))
    epoch = "9998-12-31T23:59:59.000000Z"
    late = config_with(time_policy={"mode": "external_elapsed", "epoch": epoch, "basis": "b"})
    past = timed_snapshot(epoch, "1000000000", "9999-01-01T00:00:00.000000Z")
    for given in (late, config_module.validated_config(late)):
        error = refusal(lambda: project(past, config=given))
        assert (error.code, error.path) == ("E_CONFIG", "/time_policy/epoch")


# ================================================== the reducer's entry (lead ruling CR-L17)
#
# The reducer projects through `projector._project_from_reducer`, which is `project_state` without
# the snapshot schema and the provenance schema. The ruling's test: both entries give identical
# results over every fixture snapshot, the fuzz corpus and the 1000 x 60 load of CR-L07. The
# expectation is the public entry's own answer for the same arguments: the claim under test is
# that the two entries agree, and the public entry's answers are held to the fixtures by the rest
# of this module.

#: snapshot.schema.json read as the projector reads it (CR-R3-12): "integer" is exactly an int.
#: Built here from the packaged schema, not through `_schema`.
_EXACT_INTEGERS = jsonschema_validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _checker, value: type(value) is int))
SNAPSHOT_EXACT = _EXACT_INTEGERS(support_schemas()["snapshot.schema.json"],
                                 registry=support_registry())


def _answer(result) -> tuple:
    """A result in comparable form: an Entity by its canonical bytes, a Suppression by value."""
    if type(result) is Entity:
        return ("Entity", projector.entity_bytes(result))
    assert type(result) is Suppression, type(result)
    return ("Suppression", result.reasons, result.geography_code)


def _outcome(entry, snapshot, context) -> tuple:
    """What one entry does with the arguments: its answer, or the exception it raises (type,
    code and path of an HlaError, type and text of a caller bug; nothing else may escape)."""
    try:
        result = entry(snapshot, context)
    except HlaError as error:
        return ("HlaError", error.code, error.path, error.message)
    except (TypeError, ValueError) as error:
        assert type(error) in (TypeError, ValueError), type(error)
        return (type(error).__name__, str(error))
    return _answer(result)


def _in_domain(snapshot) -> bool:
    """Whether `snapshot` is one the reducer's entry is for: it satisfies snapshot.schema.json
    with exact integers, which every snapshot the reducer builds does (its records are held to
    the schema by `hla_support.check_frame_records` in every reducer test)."""
    try:
        return SNAPSHOT_EXACT.is_valid(snapshot)
    except (TypeError, ValueError, RecursionError):
        return False


@pytest.mark.parametrize("index", SNAPSHOT_INDEXES, ids=lambda i: f"line{i + 1}")
def test_the_reducer_entry_answers_every_fixture_snapshot_as_project_state(index):
    """CR-L17 over every snapshot record of `expected.observations.jsonl`, with the context
    rebuilt from the header and the triggering frame (as the fixture oracle above does): the
    reducer's entry gives the same Suppression, or an Entity with the same canonical bytes, as
    `project_state`, both with the plain configuration and with the session's ValidatedConfig."""
    from synapse_hla import config as config_module
    _, record = OBSERVATIONS[index]
    for config in (CONFIG, config_module.validated_config(CONFIG)):
        context = dict(fixture_context(record), config=config)
        public = _outcome(project_state, copy.deepcopy(record["payload"]), copy.deepcopy(context))
        private = _outcome(projector._project_from_reducer, copy.deepcopy(record["payload"]),
                           copy.deepcopy(context))
        assert private == public
        assert public[0] == ("Entity" if record["payload"]["projection_status"] == "ELIGIBLE"
                             else "Suppression")


def test_the_reducer_entry_answers_the_fuzz_corpus_as_project_state():
    """CR-L17 over the hostile-value corpus of CR-R2-24 (the 400 pairs of each of its three
    seeds). The reducer's entry is for the snapshots the reducer builds, which satisfy
    snapshot.schema.json; for every such pair, and for every pair `project_state` does not refuse
    as a broken snapshot (ValueError), the two entries give the same answer or the same refusal
    (HlaError code, path and message; TypeError or ValueError and its text), and neither changes
    its arguments. Only a pair whose snapshot the schema refuses and which `project_state` refuses
    with ValueError is outside the comparison: there the public entry's schema check is the
    refusal the ruling removes from the reducer's path."""
    compared = {}
    outside = 0
    for seed in HOSTILE_SEEDS:
        for snapshot, context in _hostile_pairs(seed):
            before = (_fingerprint(snapshot), _fingerprint(context))
            public = _outcome(project_state, snapshot, context)
            assert (_fingerprint(snapshot), _fingerprint(context)) == before
            if public[0] == "ValueError" and not _in_domain(snapshot):
                outside += 1
                continue
            private = _outcome(projector._project_from_reducer, snapshot, context)
            assert (_fingerprint(snapshot), _fingerprint(context)) == before
            assert private == public, (seed, private[:2], public[:2])
            compared[public[0]] = compared.get(public[0], 0) + 1
    # The corpus reaches every kind of outcome inside the comparison, not only refusals.
    assert {"Entity", "Suppression", "HlaError", "TypeError", "ValueError"} <= set(compared), \
        compared
    assert sum(compared.values()) + outside == 400 * len(HOSTILE_SEEDS)


def _equivalence_spy(monkeypatch) -> dict:
    """Wrap the reducer's entry so that every call it gets is also answered by `project_state`
    on deep copies of the same arguments; the two answers must be equal, and the reducer gets
    the private entry's own result. Returns the counts of answers by kind."""
    real = projector._project_from_reducer
    seen: dict = {}

    def spy(snapshot, context):
        public = _outcome(project_state, copy.deepcopy(snapshot), copy.deepcopy(context))
        result = real(snapshot, context)
        answer = _answer(result)
        assert answer == public, (answer[:1], public[:2])
        seen[answer[0]] = seen.get(answer[0], 0) + 1
        return result
    monkeypatch.setattr(projector, "_project_from_reducer", spy)
    return seen


def test_the_reducer_entry_answers_the_bundled_capture_as_project_state(tmp_path, monkeypatch):
    """CR-L17 inside the reducer: the bundled capture replayed with every projection answered
    by both entries (equal each time); the output is still the bundle's, byte for byte (the D-19
    digest), and the calls are the fixture's snapshots: one per snapshot record of
    `expected.observations.jsonl`, eligible ones as Entities, the others as Suppressions."""
    seen = _equivalence_spy(monkeypatch)
    out = tmp_path / "out"
    synapse_hla.replay(PACKAGE_ROOT / "src" / "synapse_hla" / "fixtures" / "session.capture.jsonl",
                       out)
    assert hashlib.sha256((out / "observations.jsonl").read_bytes()).hexdigest() == \
        "d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125"
    snapshots = [r["payload"]["projection_status"] for _, r in OBSERVATIONS
                 if r["kind"] == "snapshot"]
    assert seen == {"Entity": snapshots.count("ELIGIBLE"),
                    "Suppression": snapshots.count("SUPPRESSED")}


#: The SHA-256 of the 1000 x 60 capture CR-L07 measured in round R6 (CR-new-R6-12: 61,002 frames,
#: 42,319,537 bytes). `perf_load` rebuilds it with the tests' own capture builder.
PERF_LOAD_SHA256 = "18b297b7a74464cb85e2af95a8e07c06b70112247bb0d343aec63a6aa12cae47"


def perf_load(objects: int, rounds: int) -> CaptureBuilder:
    """CR-L07's load: one generation, `objects` discovers, then `rounds` rounds of one full
    reflection of every object (EntityIdentifier 1.2.k, a platform, force 1, the SPATIAL-2 vector)
    one second apart, the generation's end one second after the last round, COMPLETE."""
    hexes = positive_hex()
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start())
    for k in range(1, objects + 1):
        builder.frame(1, 0, event_discover(f"o{k}", f"OBJ-{k}"))
    for r in range(1, rounds + 1):
        for k in range(1, objects + 1):
            builder.frame(1, r * 1_000_000_000, event_reflect(f"o{k}", (
                ("EntityIdentifier", "00010002" + format(k, "04x")),
                ("EntityType", hexes["TYPE-PLATFORM"]), ("ForceIdentifier", hexes["FORCE-1"]),
                ("Spatial", hexes["SPATIAL-2"]))))
    builder.frame(1, (rounds + 1) * 1_000_000_000, event_generation_end("stop"))
    return builder.footer()


def _both_entries_over_the_load(tmp_path, monkeypatch, objects: int, rounds: int,
                                digest: str | None = None) -> None:
    """Replay `perf_load(objects, rounds)` with both entries answering every projection. By hand:
    a discover emits nothing; each of the objects x rounds reflections supplies four VALID
    attributes of an object with a non-null identity, so it is eligible: one snapshot and one
    upsert, and the projection answers with an Entity; the generation's end invalidates every
    object (each holds an entity_id): `objects` invalidated records; no diagnostic, no removal."""
    data = perf_load(objects, rounds).data()
    assert len(data.splitlines()) == 1 + 1 + objects + objects * rounds + 1 + 1
    if digest is not None:
        assert hashlib.sha256(data).hexdigest() == digest
    capture_path = tmp_path / "load.jsonl"
    capture_path.write_bytes(data)
    seen = _equivalence_spy(monkeypatch)
    summary = synapse_hla.replay(capture_path, tmp_path / "out")
    assert seen == {"Entity": objects * rounds}
    assert summary["records"] == {"diagnostic": 0, "snapshot": objects * rounds,
                                  "upsert": objects * rounds, "removed": 0,
                                  "invalidated": objects}


def test_the_reducer_entry_answers_a_slice_of_the_perf_load_as_project_state(tmp_path,
                                                                             monkeypatch):
    """CR-L17 on the construction of CR-L07's load, cut to 1000 objects x 2 rounds so that it
    belongs in the offline group (the full 1000 x 60 load is the `perf` test below)."""
    _both_entries_over_the_load(tmp_path, monkeypatch, 1000, 2)


@pytest.mark.perf
def test_the_reducer_entry_answers_the_whole_perf_load_as_project_state(tmp_path, monkeypatch):
    """CR-L17 on the 1000 x 60 load itself, byte for byte the capture R6 measured (its SHA-256):
    60,000 projections, each answered equally by both entries. A `perf` test: the public entry's
    two extra schema validations on 60,000 snapshots make it the longest test of the package."""
    _both_entries_over_the_load(tmp_path, monkeypatch, 1000, 60, PERF_LOAD_SHA256)


def _counting_schema_use(monkeypatch) -> list:
    """Record every snapshot-schema and provenance-schema validation the projector asks for."""
    asked = []
    first_problem, checked_validator = _schema.first_problem, _schema.checked_validator

    def counted_first_problem(name, instance, **kwargs):
        asked.append(name)
        return first_problem(name, instance, **kwargs)

    def counted_checked_validator(name):
        asked.append(name)
        return checked_validator(name)
    monkeypatch.setattr(_schema, "first_problem", counted_first_problem)
    monkeypatch.setattr(_schema, "checked_validator", counted_checked_validator)
    return asked


def test_the_reducer_entry_leaves_out_exactly_the_two_schema_checks(monkeypatch):
    """CR-L17: on the fixture's eligible snapshot, with the session's ValidatedConfig (as the
    reducer passes it, so that no configuration schema is asked for either), `project_state`
    validates the snapshot against snapshot.schema.json and the provenance block against
    hla-provenance.schema.json; the reducer's entry asks for neither, and both give the bundle's
    first upsert byte for byte."""
    from synapse_hla import config as config_module
    validated = config_module.validated_config(CONFIG)
    asked = _counting_schema_use(monkeypatch)
    entity = project(make_snapshot(), config=validated)
    assert asked == ["snapshot.schema.json", "hla-provenance.schema.json"]
    assert projector.entity_bytes(entity) == payload_bytes(FIRST_UPSERT)
    asked.clear()
    snapshot = make_snapshot()
    entity = projector._project_from_reducer(snapshot, make_context(snapshot, config=validated))
    assert asked == []
    assert projector.entity_bytes(entity) == payload_bytes(FIRST_UPSERT)


@pytest.mark.parametrize("target,attribute,replacement", [
    (geodesy, "project_spatial", _broken_position),                         # CDM schema
    (_utc, "format_millisecond", lambda us: "2026-02-30T00:00:01.000Z"),   # explicit date check
    (projector._identity, "entity_id", lambda external: "not-a-uuid"),      # format checker
    (projector, "entity_bytes", lambda entity: b"{}"),                      # model round trip
], ids=["schema", "timestamp", "uuid-format", "round-trip"])
def test_the_reducer_entry_keeps_every_other_check_of_the_entity(monkeypatch, target, attribute,
                                                                 replacement):
    """CR-L17 keeps R44's checks on the reducer's path: an Entity that would break the CDM schema
    (a latitude of 91), a timestamp (a 30 February), the uuid format of entity_id or the model's
    byte round trip raises ProjectionDefect from the reducer's entry, as from `project_state`,
    and from `reduce_frame` on the fixture's frame at seq 5 (the first eligible one)."""
    from synapse_hla import reducer
    monkeypatch.setattr(target, attribute, replacement)
    snapshot = make_snapshot()
    caller_bug(ProjectionDefect,
               lambda: projector._project_from_reducer(snapshot, make_context(snapshot)))
    state = reducer.initial_state(HEADER, True)
    for seq in range(1, 5):
        state, _ = reducer.reduce_frame(state, FRAMES[seq])
    caller_bug(ProjectionDefect, lambda: reducer.reduce_frame(state, FRAMES[5]))


def test_the_reducer_entry_keeps_the_profile_rules(monkeypatch):
    """The profile's own assertions stay on the reducer's path: motion from a static Spatial is
    valid CDM, and only the profile refuses it (as `test_a_rule_only_the_profile_check_holds`
    shows for `project_state`)."""
    monkeypatch.setattr(geodesy, "project_spatial", lambda value: geodesy.Projection(
        {"lat": 0.0, "lon": 0.0, "alt_m": 0.0}, motion(1.0, 0.0, 0.0)))
    snapshot = make_snapshot(spatial=spatial_slot(1, velocity=None))
    error = caller_bug(ProjectionDefect, lambda: projector._project_from_reducer(
        snapshot, make_context(snapshot)))
    assert "WORLD velocity" in str(error)
