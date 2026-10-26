"""`reduce_frame` and the state of section 7 (R21-R25, R32, R33, section 20), frame by frame.

Every test drives `synapse_hla.reducer.reduce_frame` through `hla_support.reduce_checked` (directly
or through `Scenario`), so every record any test here produces is held to the output, snapshot
and diagnostic schemas and to RED-16, RED-03, R33 and SPEC:283, every input is checked unchanged
after every call, and every stream is held to `check_stream`. A case is bound by a test that runs
its frames and asserts the complete ordered records of the frames that matter, as `brief` tuples:
(kind, token, entity_id, then code and attribute | lifecycle, reasons, changed attributes and
last revision | revision | reason and last revision).

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
- The bundled capture and its expected records (the oracle), `session-checkpoints.json`, and the
  attribute vectors of the bundle: every scenario is built from the positive vectors' hex (ID-123,
  TYPE-PLATFORM, FORCE-1, FORCE-255, SPATIAL-n, SPATIAL-PADDING), the negative ones where a decode
  must fail, and the Spatial of the bundled capture's seq 6.
- Reasons, codes, orders, revisions and lifecycles are derived by hand from the rulings named in
  each test and written as literals; the few rule tables (A-PARTIAL-ORDER) are written out from
  R23 and SPEC:285 here, not taken from the product.
- entity_ids are R26 derived by the tests' own RFC 4122 implementation (`hla_support.
  rfc4122_uuid5`, held to identity.json), with the fixture's 781e68de... as a literal check;
  the scout verifier observed the same 2cc17970... (incarnation 2) and 552c4e02...
  (generation 2) with Python's uuid module, which the tests check as prefixes.
- Effective times are the epoch 2026-01-01T00:00:00.000000Z plus elapsed_ns // 1000 (CR-L05),
  written out per frame.
"""

import copy
import dataclasses
import hashlib
import itertools
import json
import math
import random
import sys

import pytest

import synapse_hla
from hla_support import (
    ReferenceConsumer, Scenario, brief, briefs, case, check_frame_records, check_stream,
    encode_spatial, event_diagnostic, event_discover, event_generation_end,
    event_generation_start, event_reflect, event_remove, example_json, fixture_capture_records,
    fixture_jsonl, header_with, negative_hex, package_bytes, positive_hex, reduce_checked,
    rfc4122_uuid5, refused_frame, run_python, without_completion,
)
from synapse_hla import HlaError, geodesy, reducer
from synapse_hla.limits import V1

NAMESPACE = "6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50"
SECOND = 1_000_000_000
EI, ET, FI, SP = "EntityIdentifier", "EntityType", "ForceIdentifier", "Spatial"
PHYSICAL = "HLAobjectRoot.BaseEntity.PhysicalEntity"

HEX = positive_hex()
BAD = negative_hex()
#: 000100020003: site 1, application 2, entity 3 (ID-123).
ID_123 = HEX["ID-123"]
#: Hand-encoded identifiers: big-endian uint16 site, application, entity (SPEC:81).
ID_456 = "000400050006"
ID_789 = "000700080009"
ID_ABC = "000a000b000c"
ID_NULL = "000000000000"
#: 010100e101020304: kind 1 (PLATFORM), domain 1, country 225, category 1, 2, 3, 4.
TYPE = HEX["TYPE-PLATFORM"]
FORCE_1, FORCE_255 = HEX["FORCE-1"], HEX["FORCE-255"]
#: SPATIAL-2: FPW at ECEF (6378137, 0, 0), velocity (0, 10, 0): lat 0, lon 0, alt 0, east 10 m/s.
SPATIAL_A = HEX["SPATIAL-2"]
#: The bundled capture's seq-6 Spatial: the same at x = 6378147 m, so alt 10 (checkpoints).
SPATIAL_B = fixture_capture_records()[6]["event"]["attributes"][0]["hex"]
#: 59 bytes of an FPW (needs 60): E_ATTRIBUTE_LENGTH.
BAD_SPATIAL = BAD["TRUNC-2"]
#: Two bytes of a ForceIdentifier (needs 1): E_ATTRIBUTE_LENGTH.
BAD_FORCE = BAD["LENGTH-ForceIdentifier"]

FULL = ((EI, ID_123), (ET, TYPE), (FI, FORCE_1), (SP, SPATIAL_A))
#: SHA-256 of SPATIAL-2's raw bytes, as first-upsert.entity.json records it.
SPATIAL_A_SHA256 = "67cd7e47f9dcf5b6556e173b92fc7e930584f3c4ddbba761180463d2ab544dfb"
EPOCH = "2026-01-01T00:00:00.000000Z"


def eid(session: str, generation: int, triple: tuple, incarnation: int) -> str:
    """R26 written out: UUIDv5 over "entity|hla-rpr2|" and the six strings as compact JSON."""
    external = json.dumps([session, str(generation), *(str(n) for n in triple), str(incarnation)],
                          separators=(",", ":"))
    return rfc4122_uuid5(NAMESPACE, "entity|hla-rpr2|" + external)


#: The fixture's entity: example-001, generation 1, 1.2.3, incarnation 1.
EID_1 = "781e68de-166f-531c-b906-4a2d087f817e"
EID_INC2 = eid("example-001", 1, (1, 2, 3), 2)
EID_INC3 = eid("example-001", 1, (1, 2, 3), 3)
EID_GEN2 = eid("example-001", 2, (1, 2, 3), 1)
EID_456 = eid("example-001", 1, (4, 5, 6), 1)
EID_789 = eid("example-001", 1, (7, 8, 9), 1)
EID_ABC = eid("example-001", 1, (10, 11, 12), 1)


def at(seconds_ns: int) -> str:
    """The effective time of elapsed `seconds_ns` after the fixture's epoch, by hand: whole
    seconds and microseconds of 2026-01-01 (no test here crosses a minute)."""
    micro = seconds_ns // 1000
    return f"2026-01-01T00:00:{micro // 1_000_000:02d}.{micro % 1_000_000:06d}Z"


def reflect(token: str, *attributes, retractable: bool = False) -> dict:
    return event_reflect(token, attributes, retractable=retractable)


def retractable_remove(token: str) -> dict:
    return dict(event_remove(token), retractable=True)


def started(header: dict | None = None) -> Scenario:
    """seq 1 generation_start, seq 2 discover o1."""
    return Scenario(header).frame(1, 0, event_generation_start()).frame(1, 0, event_discover("o1"))


def eligible(header: dict | None = None) -> Scenario:
    """`started`, then seq 3: o1 supplies all four attributes at 1 s and becomes eligible."""
    return started(header).frame(1, SECOND, reflect("o1", *FULL))


def snapshot_of(records: list) -> dict:
    return next(r for r in records if r["kind"] == "snapshot")["payload"]


def upsert_of(records: list) -> dict:
    return next(r for r in records if r["kind"] == "upsert")["payload"]


def slot(status, value, raw, seq, elapsed, effective_at) -> dict:
    return {"status": status, "value": value, "hex": raw, "seq": seq, "elapsed_ns": elapsed,
            "effective_at": effective_at}


ABSENT = slot("ABSENT", None, None, None, None, None)
IDENTITY_123 = {"site": 1, "application": 2, "entity": 3}
TYPE_VALUE = {"kind": 1, "domain": 1, "country": 225, "category": 1, "subcategory": 2,
              "specific": 3, "extra": 4}
SPATIAL_A_VALUE = {"algorithm": 2, "frame": "WORLD", "frozen": False,
                   "position_ecef_m": [6378137.0, 0.0, 0.0], "orientation_rad": [0.0, 0.0, 0.0],
                   "velocity_mps": [0.0, 10.0, 0.0], "acceleration_mps2": None,
                   "angular_velocity_radps": None, "padding_hex": "00000000000000000000"}
#: The row of seq 3 of `eligible()`: snapshot then upsert, revision 1.
ELIGIBLE_AT_3 = [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
                 ("upsert", "o1", EID_1, 1)]


# ============================================================================ the bundled oracle

@case("G-R33", "G-R21", paragraphs=("SPEC:287", "SPEC:283"))
def test_the_bundled_capture_reduces_to_the_bundled_records_line_for_line():
    """The oracle through reduce_frame: each frame's records, written by `output_line`, are the
    bundled expected lines in order (RED-15); the frame census is SPEC:287's (four snapshots,
    two upserts, one removed, no diagnostic or invalidated); discover, generation_start and
    generation_end emit nothing."""
    records = fixture_capture_records()
    expected = [raw + b"\n" for raw, _ in fixture_jsonl("expected.observations.jsonl")]
    state = reducer.initial_state(records[0], True)
    produced, per_seq = [], {}
    for frame in records[1:-1]:
        state, out = reduce_checked(state, frame)
        per_seq[frame["seq"]] = [r["kind"] for r in out]
        produced += [reducer.output_line(r) for r in out]
    assert produced == expected
    assert per_seq == {1: [], 2: [], 3: ["snapshot"], 4: ["snapshot"], 5: ["snapshot", "upsert"],
                       6: ["snapshot", "upsert"], 7: ["removed"], 8: []}


@case("G-R33", paragraphs=("SPEC:287",))
def test_header_and_footer_produce_no_observations():
    """SPEC:287: the header only builds the initial state, and the footer is not a frame:
    reduce_frame refuses it at its line (E_CAPTURE_SCHEMA `line:10#/type`, the footer being line
    10 of the bundled capture), so it can never produce a record."""
    records = fixture_capture_records()
    state = reducer.initial_state(records[0], True)
    for frame in records[1:-1]:
        state, _ = reduce_checked(state, frame)
    error = refused_frame(state, records[-1])
    assert (error.code, error.path) == ("E_CAPTURE_SCHEMA", "line:10#/type")


def test_the_fixture_entity_id_is_r26_of_its_lifecycle():
    """The literal of the fixture and the tests' own derivation agree, and the scout verifier's
    observations for incarnation 2 and generation 2 (uuid.uuid5) are the same derivation."""
    assert eid("example-001", 1, (1, 2, 3), 1) == EID_1
    assert EID_INC2.startswith("2cc17970") and EID_GEN2.startswith("552c4e02")
    assert len({EID_1, EID_INC2, EID_INC3, EID_GEN2, EID_456, EID_789, EID_ABC}) == 7


# ============================================================================ R22: partial updates

#: R23 and SPEC:285 for one attribute supplied at a time: the reason an absent required
#: attribute gives.
MISSING = {EI: "MISSING_ENTITY_IDENTIFIER", ET: "MISSING_ENTITY_TYPE", SP: "MISSING_SPATIAL"}
ORDER_HEX = {EI: ID_123, ET: TYPE, FI: FORCE_1, SP: SPATIAL_A}
ORDER_VALUE = {EI: IDENTITY_123, ET: TYPE_VALUE, FI: {"value": 1}, SP: SPATIAL_A_VALUE}
ORDERS = list(itertools.permutations((EI, ET, FI, SP)))


@case("A-PARTIAL-ORDER", "G-R22", "G-R23", "G-R21", paragraphs=("SPEC:283", "SPEC:285"))
@pytest.mark.parametrize("order", ORDERS, ids=["-".join(n[0] + n[-1] for n in o) for o in ORDERS])
def test_every_order_of_the_four_attributes(order):
    """A-PARTIAL-ORDER over all 24 orders (OPS-28: ID-123, TYPE-PLATFORM, FORCE-1, SPATIAL-2 under
    config-demo, four single-attribute reflections at 1, 2, 3 and 4 s, seq 3 to 6). After each
    frame the snapshot lists the MISSING_ reason of every required attribute not yet supplied,
    every attribute supplied so far is VALID with the hex, seq, elapsed and time of ITS frame
    (omitted values are retained, never re-stamped), the identity exists from the identifier's
    frame on, and the state is eligible exactly when EntityIdentifier, EntityType and Spatial
    have all arrived (ForceIdentifier is optional): from then on every frame upserts, with
    revisions 1, 2, ... ."""
    scenario = started()
    for k, name in enumerate(order, start=1):
        scenario.frame(1, k * SECOND, reflect("o1", (name, ORDER_HEX[name])))
    out = scenario.reduce()
    supplied, revision = [], 0
    for k, name in enumerate(order, start=1):
        seq = k + 2
        supplied.append(name)
        reasons = tuple(sorted(MISSING[n] for n in MISSING if n not in supplied))
        entity = EID_1 if EI in supplied else None
        expected = [("snapshot", "o1", entity, "ACTIVE", reasons, (name,), revision)]
        if not reasons:
            revision += 1
            expected.append(("upsert", "o1", entity, revision))
        records = out[seq - 1]
        assert [brief(r) for r in records] == expected, (order, seq)
        slots = snapshot_of(records)["attributes"]
        for n in (EI, ET, FI, SP):
            if n in supplied:
                when = (order.index(n) + 1) * SECOND
                assert slots[n] == slot("VALID", ORDER_VALUE[n], ORDER_HEX[n],
                                        order.index(n) + 3, str(when), at(when)), (order, seq, n)
            else:
                assert slots[n] == ABSENT, (order, seq, n)
        if not reasons:
            hla = upsert_of(records)["attributes"]["hla"]
            assert hla["attribute_sequences"] == {
                n: (order.index(n) + 3 if n in supplied else None) for n in (EI, ET, FI, SP)}
            assert hla["time"]["spatial_seq"] == order.index(SP) + 3
            assert upsert_of(records)["valid_from"] == at((order.index(SP) + 1) * SECOND)[:23] + "Z"
            assert upsert_of(records)["affiliation"] == (
                "FRIENDLY" if FI in supplied else "UNKNOWN")


# ============================================================================ R22: atomic callbacks

@case("A-ATOMIC", "G-R22", paragraphs=("SPEC:281", "SPEC:283"))
def test_a_valid_changed_force_and_a_malformed_spatial_together_apply_nothing():
    """A-ATOMIC. o1 is eligible (seq 3, revision 1). Seq 4 at 2 s supplies ForceIdentifier 02 (a
    valid, changed, unmapped value) and the 59-byte TRUNC-2 Spatial. Expected (R22, SPEC:283,
    SPEC:285): one diagnostic E_ATTRIBUTE_LENGTH for Spatial; o1, eligible before, invalidated
    once with invalid_required_attribute; the snapshot lists INVALID_FORCE_IDENTIFIER and
    INVALID_SPATIAL; both supplied slots are INVALID with this frame's hex, seq, elapsed and
    time and no value (neither the force 2 nor any Spatial value applied); the two others keep
    seq 3. No W_FORCE_UNMAPPED: a rejected value is never applied (RED-17)."""
    out = eligible().frame(1, 2 * SECOND, reflect("o1", (FI, "02"), (SP, BAD_SPATIAL))).reduce()
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("diagnostic", "o1", EID_1, "E_ATTRIBUTE_LENGTH", SP),
            ("invalidated", "o1", EID_1, "invalid_required_attribute", 1),
            ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_FORCE_IDENTIFIER", "INVALID_SPATIAL"),
             (FI, SP), 1)],
    }
    slots = snapshot_of(out[3])["attributes"]
    assert slots == {
        EI: slot("VALID", IDENTITY_123, ID_123, 3, str(SECOND), at(SECOND)),
        ET: slot("VALID", TYPE_VALUE, TYPE, 3, str(SECOND), at(SECOND)),
        FI: slot("INVALID", None, "02", 4, str(2 * SECOND), at(2 * SECOND)),
        SP: slot("INVALID", None, BAD_SPATIAL, 4, str(2 * SECOND), at(2 * SECOND)),
    }


@case("A-REPAIR", "G-R22", "G-R24")
def test_a_repair_after_an_atomic_rejection_restores_the_identity_and_the_next_revision():
    """A-REPAIR. After A-ATOMIC's seq 4, seq 5 at 3 s supplies the same identifier, force 01 and
    the seq-6 Spatial of the bundle: the state is eligible again under the same entity_id, and
    the upsert's revision is 2, one after the last emitted (no new invalidation, no diagnostic).
    The repaired slots carry seq 5."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (FI, "02"), (SP, BAD_SPATIAL)))
           .frame(1, 3 * SECOND, reflect("o1", (EI, ID_123), (FI, FORCE_1), (SP, SPATIAL_B)))
           .reduce())
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("diagnostic", "o1", EID_1, "E_ATTRIBUTE_LENGTH", SP),
            ("invalidated", "o1", EID_1, "invalid_required_attribute", 1),
            ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_FORCE_IDENTIFIER", "INVALID_SPATIAL"),
             (FI, SP), 1)],
        5: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, FI, SP), 1), ("upsert", "o1", EID_1, 2)],
    }
    entity = upsert_of(out[4])
    assert entity["entity_id"] == EID_1
    assert entity["attributes"]["hla"]["attribute_sequences"] == {EI: 5, ET: 3, FI: 5, SP: 5}
    assert entity["position"]["alt_m"] == 10.0
    assert entity["valid_from"] == "2026-01-01T00:00:03.000Z"


@case("A-UNSUBSCRIBED", "G-R22", paragraphs=("SPEC:283",))
def test_an_unknown_attribute_rejects_its_reflection_atomically():
    """A-UNSUBSCRIBED (OPS-05: a crafted capture; NAT-06: four or fewer attributes with an
    unknown name are captured). Seq 4 supplies EntityType and `Other`: E_UNSUBSCRIBED_ATTRIBUTE
    names `Other` (the name the frame gave, CR-R1-04), EntityType turns INVALID, o1 is
    invalidated and the snapshot's changed attributes list only the known name (SPEC:283).
    Seq 5 repairs with EntityType alone (revision 2). Seq 6 supplies only `Other`: rejected
    again, but no known attribute changes, so the state stays eligible: a snapshot with no
    changed attribute, no upsert (no known attribute supplied, SPEC:287), no invalidation."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (ET, TYPE), ("Other", "00")))
           .frame(1, 3 * SECOND, reflect("o1", (ET, TYPE)))
           .frame(1, 4 * SECOND, reflect("o1", ("Other", "00"))).reduce())
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("diagnostic", "o1", EID_1, "E_UNSUBSCRIBED_ATTRIBUTE", "Other"),
            ("invalidated", "o1", EID_1, "invalid_required_attribute", 1),
            ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_ENTITY_TYPE",), (ET,), 1)],
        5: [("snapshot", "o1", EID_1, "ACTIVE", (), (ET,), 1), ("upsert", "o1", EID_1, 2)],
        6: [("diagnostic", "o1", EID_1, "E_UNSUBSCRIBED_ATTRIBUTE", "Other"),
            ("snapshot", "o1", EID_1, "ACTIVE", (), (), 2)],
    }
    assert snapshot_of(out[3])["attributes"][ET] == slot("INVALID", None, TYPE, 4,
                                                          str(2 * SECOND), at(2 * SECOND))
    assert "Other" not in snapshot_of(out[5])["attributes"]


@case("G-R22", paragraphs=("SPEC:281",))
def test_one_diagnostic_per_failure_sorted_by_code_then_attribute():
    """R22, SPEC:281: every supplied attribute is decoded first, one diagnostic per failing
    attribute, sorted by code then attribute name; every supplied known attribute turns
    INVALID, the failing and the valid ones alike. Seq 3 supplies four values that each fail:
    EntityIdentifier of 5 bytes, EntityType of 9 and ForceIdentifier of 2 (E_ATTRIBUTE_LENGTH),
    Spatial with algorithm 10 (E_SPATIAL_VARIANT). Seq 4 supplies a valid EntityType with a
    Spatial whose frozen octet is 2 (BOOL-2): E_BOOLEAN for Spatial, and EntityType INVALID
    although it decoded. Seq 5: a non-finite velocity (NONFINITE-48): E_NONFINITE. The
    diagnostic names the attribute, never the decoder's `Spatial/<offset>` path (CR-R1-04)."""
    out = (started()
           .frame(1, SECOND, reflect("o1", (EI, BAD["LENGTH-EntityIdentifier"]),
                                     (ET, BAD["LENGTH-EntityType"]), (FI, BAD_FORCE),
                                     (SP, BAD["ALG-10"])))
           .frame(1, 2 * SECOND, reflect("o1", (ET, TYPE), (SP, BAD["BOOL-2"])))
           .frame(1, 3 * SECOND, reflect("o1", (SP, BAD["NONFINITE-48"]))).reduce())
    reasons_all = ("INVALID_ENTITY_IDENTIFIER", "INVALID_ENTITY_TYPE", "INVALID_FORCE_IDENTIFIER",
                   "INVALID_SPATIAL")
    assert briefs(out) == {
        3: [("diagnostic", "o1", None, "E_ATTRIBUTE_LENGTH", EI),
            ("diagnostic", "o1", None, "E_ATTRIBUTE_LENGTH", ET),
            ("diagnostic", "o1", None, "E_ATTRIBUTE_LENGTH", FI),
            ("diagnostic", "o1", None, "E_SPATIAL_VARIANT", SP),
            ("snapshot", "o1", None, "ACTIVE", reasons_all, (EI, ET, FI, SP), 0)],
        4: [("diagnostic", "o1", None, "E_BOOLEAN", SP),
            ("snapshot", "o1", None, "ACTIVE", reasons_all, (ET, SP), 0)],
        5: [("diagnostic", "o1", None, "E_NONFINITE", SP),
            ("snapshot", "o1", None, "ACTIVE", reasons_all, (SP,), 0)],
    }
    assert snapshot_of(out[3])["attributes"][ET] == slot("INVALID", None, TYPE, 4,
                                                          str(2 * SECOND), at(2 * SECOND))


@case("A-EMPTY", "G-R22", paragraphs=("SPEC:279", "SPEC:118"))
def test_an_empty_reflection_changes_nothing_and_emits_nothing():
    """A-EMPTY. o1 is eligible; seq 4 is an empty reflection: no record at all, and the object
    is the same object state as before (SPEC:116, SPEC:279: an empty callback map produces no
    state output; SPEC:118 counts only nonempty reflections). An empty reflection for a token
    nobody discovered, seq 5, is E_UNKNOWN_OBJECT (RED-11)."""
    scenario = eligible().frame(1, 2 * SECOND, reflect("o1")).frame(1, 2 * SECOND, reflect("o99"))
    out = scenario.reduce()
    assert briefs(out) == {3: ELIGIBLE_AT_3,
                           5: [("diagnostic", "o99", None, "E_UNKNOWN_OBJECT", None)]}
    assert scenario.states[4].objects == scenario.states[3].objects
    assert scenario.states[4].objects["o1"] is scenario.states[3].objects["o1"]


@case("A-REPEATED", "G-R22", "G-R32", paragraphs=("SPEC:118", "SPEC:154"))
def test_the_same_spatial_bytes_twice_give_two_snapshots_and_two_revisions():
    """A-REPEATED (SPEC:118, SPEC:154): seq 4 at 2 s repeats SPATIAL-2 byte for byte. Not a
    duplicate to drop: a second snapshot and revision 2, whose provenance is the new frame's
    (Spatial seq 4, original_id .../o1/4, record_index 3, source_hash the seq-4 frame's digest)
    and whose validity advanced to 2 s, while the attribute hash, a hash of the same bytes, is
    the same."""
    scenario = eligible().frame(1, 2 * SECOND, reflect("o1", (SP, SPATIAL_A)))
    out = scenario.reduce()
    assert briefs(out) == {3: ELIGIBLE_AT_3,
                           4: [("snapshot", "o1", EID_1, "ACTIVE", (), (SP,), 1),
                               ("upsert", "o1", EID_1, 2)]}
    first, second = upsert_of(out[2]), upsert_of(out[3])
    hla = second["attributes"]["hla"]
    assert hla["attribute_sequences"] == {EI: 3, ET: 3, FI: 3, SP: 4}
    assert hla["time"] == {"kind": "external_elapsed", "basis": "Synthetic 1x scenario clock "
                           "asserted by fixture author", "effective_at": at(2 * SECOND),
                           "spatial_seq": 4}
    assert hla["attribute_hashes"][SP] == first["attributes"]["hla"]["attribute_hashes"][SP] \
        == SPATIAL_A_SHA256
    assert second["source"]["original_id"] == "example-001/1/o1/4"
    assert second["source"]["record_index"] == 3
    assert second["source"]["source_hash"] == {"algorithm": "sha256",
                                               "value": scenario.chained[4]["sha256"]}
    assert (first["valid_from"], second["valid_from"]) == ("2026-01-01T00:00:01.000Z",
                                                           "2026-01-01T00:00:02.000Z")


@case("A-UNKNOWN", "G-R22", "G-R25")
def test_a_reflection_or_removal_for_an_undiscovered_token_creates_nothing():
    """A-UNKNOWN: a reflect for o99 (seq 2) and a remove for o98 (seq 3) that no discover
    introduced: E_UNKNOWN_OBJECT each (token, no entity, no attribute; RED-03), no object is
    created, and generation_end has nothing to invalidate."""
    scenario = (Scenario().frame(1, 0, event_generation_start())
                .frame(1, SECOND, reflect("o99", (FI, FORCE_1)))
                .frame(1, SECOND, event_remove("o98"))
                .frame(1, SECOND, event_generation_end()))
    out = scenario.reduce()
    assert briefs(out) == {2: [("diagnostic", "o99", None, "E_UNKNOWN_OBJECT", None)],
                           3: [("diagnostic", "o98", None, "E_UNKNOWN_OBJECT", None)]}
    assert scenario.states[2].objects == {} and scenario.states[3].objects == {}


# ============================================================================ R23: eligibility

@case("A-FORCE-ABSENT", "G-R23", "G-R09")
def test_a_complete_state_without_force_projects_unknown_without_a_warning():
    """A-FORCE-ABSENT (R23: ABSENT force means UNKNOWN; SPEC:201: absent force has no warning).
    Seq 3 supplies the three required attributes only: eligible, affiliation UNKNOWN, the
    provenance's force_identifier, force sequence and force hash null, and no diagnostic."""
    out = started().frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE), (SP, SPATIAL_A))
                          ).reduce()
    assert briefs(out) == {3: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, SP), 0),
                               ("upsert", "o1", EID_1, 1)]}
    entity = upsert_of(out[2])
    hla = entity["attributes"]["hla"]
    assert entity["affiliation"] == "UNKNOWN"
    assert (hla["force_identifier"], hla["attribute_sequences"][FI],
            hla["attribute_hashes"][FI]) == (None, None, None)


@case("A-FORCE-INVALID", "G-R23", "G-R25", paragraphs=("SPEC:285",))
def test_a_malformed_force_after_an_entity_invalidates_it_until_repaired():
    """A-FORCE-INVALID (R23: an INVALID force suppresses until corrected; SPEC:285). Seq 4 sends
    a 2-byte force: E_ATTRIBUTE_LENGTH, invalidated once (invalid_required_attribute), no upsert.
    Seq 5 moves the Spatial: still suppressed by the force, no upsert and no second
    invalidation. Seq 6 repairs the force: revision 2, FRIENDLY again, at the seq-5 position."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (FI, BAD_FORCE)))
           .frame(1, 3 * SECOND, reflect("o1", (SP, SPATIAL_B)))
           .frame(1, 4 * SECOND, reflect("o1", (FI, FORCE_1))).reduce())
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("diagnostic", "o1", EID_1, "E_ATTRIBUTE_LENGTH", FI),
            ("invalidated", "o1", EID_1, "invalid_required_attribute", 1),
            ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_FORCE_IDENTIFIER",), (FI,), 1)],
        5: [("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_FORCE_IDENTIFIER",), (SP,), 1)],
        6: [("snapshot", "o1", EID_1, "ACTIVE", (), (FI,), 1), ("upsert", "o1", EID_1, 2)],
    }
    entity = upsert_of(out[5])
    assert (entity["affiliation"], entity["position"]["alt_m"]) == ("FRIENDLY", 10.0)


@case("A-FORCE-UNMAPPED", "G-R09", "G-R23")
@case("G-R37", paragraphs=("SPEC:201",))
def test_an_unmapped_force_warns_once_per_object_per_new_value():
    """A-FORCE-UNMAPPED under an empty force_map (RED-17). Seq 3: force 255 applied, unmapped:
    W_FORCE_UNMAPPED (attribute ForceIdentifier) and affiliation UNKNOWN. Seq 4: 255 again, no
    warning. Seq 5: 1, new and unmapped: a warning. Seq 6: back to 255, no warning (no repeat
    on return). Seq 7: 254 in a rejected reflection: no warning. Seq 8: 254 applied: a warning.
    Revisions run 1 to 5 over the eligible frames (seq 7 invalidates)."""
    header = header_with(force_map={})
    full_255 = ((EI, ID_123), (ET, TYPE), (FI, FORCE_255), (SP, SPATIAL_A))
    out = (started(header).frame(1, SECOND, reflect("o1", *full_255))
           .frame(1, 2 * SECOND, reflect("o1", (FI, FORCE_255)))
           .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1)))
           .frame(1, 4 * SECOND, reflect("o1", (FI, FORCE_255)))
           .frame(1, 5 * SECOND, reflect("o1", (FI, "fe"), (SP, BAD_SPATIAL)))
           .frame(1, 6 * SECOND, reflect("o1", (FI, "fe"), (SP, SPATIAL_A))).reduce())
    unmapped = ("diagnostic", "o1", EID_1, "W_FORCE_UNMAPPED", FI)
    assert briefs(out) == {
        3: [unmapped, ("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_1, 1)],
        4: [("snapshot", "o1", EID_1, "ACTIVE", (), (FI,), 1), ("upsert", "o1", EID_1, 2)],
        5: [unmapped, ("snapshot", "o1", EID_1, "ACTIVE", (), (FI,), 2),
            ("upsert", "o1", EID_1, 3)],
        6: [("snapshot", "o1", EID_1, "ACTIVE", (), (FI,), 3), ("upsert", "o1", EID_1, 4)],
        7: [("diagnostic", "o1", EID_1, "E_ATTRIBUTE_LENGTH", SP),
            ("invalidated", "o1", EID_1, "invalid_required_attribute", 4),
            ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_FORCE_IDENTIFIER", "INVALID_SPATIAL"),
             (FI, SP), 4)],
        8: [unmapped, ("snapshot", "o1", EID_1, "ACTIVE", (), (FI, SP), 4),
            ("upsert", "o1", EID_1, 5)],
    }
    assert [upsert_of(out[k])["affiliation"] for k in (2, 3, 4, 5, 7)] == ["UNKNOWN"] * 5
    assert upsert_of(out[2])["attributes"]["hla"]["force_identifier"] == 255


@case("G-R09")
@pytest.mark.parametrize("force_map,affiliation,warned", [
    ({"255": "UNKNOWN"}, "UNKNOWN", False),
    ({"255": "HOSTILE"}, "HOSTILE", False),
    ({"1": "FRIENDLY"}, "UNKNOWN", True),
    ({}, "UNKNOWN", True),
])
def test_an_explicit_entry_is_mapped_whatever_its_value(force_map, affiliation, warned):
    """RED-17: the lookup is by the canonical decimal string, and an explicit `"255": "UNKNOWN"`
    entry counts as mapped (no warning, affiliation UNKNOWN); the RPR enumeration's label for
    255 plays no part (R09)."""
    out = started(header_with(force_map=force_map)).frame(
        1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE), (FI, FORCE_255), (SP, SPATIAL_A))
    ).reduce()
    codes = [r["payload"]["code"] for r in out[2] if r["kind"] == "diagnostic"]
    assert codes == (["W_FORCE_UNMAPPED"] if warned else [])
    assert upsert_of(out[2])["affiliation"] == affiliation


@case("A-NULL-ID", "G-R24", "G-R23", paragraphs=("SPEC:281", "SPEC:285"))
def test_the_null_identifier_allocates_nothing_until_a_real_one_claims():
    """A-NULL-ID (SPEC:281, RED-02, RED-10). Seq 3: identifier 0.0.0 with type and Spatial:
    E_NULL_ID (attribute EntityIdentifier) beside a snapshot that lists NULL_ID, with no
    identity, no incarnation and no entity_id, and no upsert. Seq 4 (force only): the same
    reason, so E_NULL_ID again (co-located with every such snapshot). Seq 5: identifier 1.2.3
    claims (null then nonnull is a claim, not a change): incarnation 1, eligible, revision 1.
    Seq 6: generation_end invalidates it."""
    out = (started().frame(1, SECOND, reflect("o1", (EI, ID_NULL), (ET, TYPE), (SP, SPATIAL_A)))
           .frame(1, 2 * SECOND, reflect("o1", (FI, FORCE_1)))
           .frame(1, 3 * SECOND, reflect("o1", (EI, ID_123)))
           .frame(1, 3 * SECOND, event_generation_end()).reduce())
    assert briefs(out) == {
        3: [("diagnostic", "o1", None, "E_NULL_ID", EI),
            ("snapshot", "o1", None, "ACTIVE", ("NULL_ID",), (EI, ET, SP), 0)],
        4: [("diagnostic", "o1", None, "E_NULL_ID", EI),
            ("snapshot", "o1", None, "ACTIVE", ("NULL_ID",), (FI,), 0)],
        5: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI,), 0), ("upsert", "o1", EID_1, 1)],
        6: [("invalidated", "o1", EID_1, "generation_end", 1)],
    }
    first = snapshot_of(out[2])
    assert (first["identity"], first["incarnation"]) == (None, None)
    assert first["attributes"][EI]["value"] == {"site": 0, "application": 0, "entity": 0}
    assert (snapshot_of(out[4])["identity"], snapshot_of(out[4])["incarnation"]) == (
        IDENTITY_123, 1)


@case("G-R23", paragraphs=("SPEC:285",))
def test_a_body_frame_spatial_projects_its_position_and_no_kinematics():
    """R23: every Spatial variant decodes, but BODY velocity stays source data: an RPB value
    (SPATIAL-7) makes o1 eligible with kinematics null and the BODY velocity kept in the
    provenance; transformations carry no ENU step."""
    out = started().frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE),
                                             (SP, HEX["SPATIAL-7"]))).reduce()
    entity = upsert_of(out[2])
    assert entity["kinematics"] is None
    assert entity["source"]["transformations"] == ["external-time-context", "ecef-to-wgs84"]
    spatial = entity["attributes"]["hla"]["spatial"]
    assert (spatial["frame"], spatial["velocity_mps"]) == ("BODY", [0.0, 10.0, 0.0])


def _forward(lat_deg: float, lon_deg: float, h: float) -> tuple:
    """Closed-form geodetic -> ECEF (WGS84), written here as in test_hla_projector.py."""
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    phi, lam = math.radians(lat_deg), math.radians(lon_deg)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    return ((n + h) * math.cos(phi) * math.cos(lam), (n + h) * math.cos(phi) * math.sin(lam),
            (n * (1 - e2) + h) * math.sin(phi))


#: A static Spatial at the Earth's centre: norm 0, below the 1e6 m gate (R29).
SPATIAL_CENTRE = encode_spatial(1, position=(0.0, 0.0, 0.0)).hex()


@case("G-R23", "G-R32", paragraphs=("SPEC:285",))
def test_e_ecef_range_suppresses_with_its_diagnostic_once_the_state_is_otherwise_complete():
    """OPS-19's named test for E_ECEF_RANGE (RED-02, SPEC:285). Seq 3 supplies the identifier
    and a Spatial at the Earth's centre, no type: GEOGRAPHY_UNPROJECTABLE is listed beside
    MISSING_ENTITY_TYPE but no geography error is emitted (a MISSING_ reason is present). Seq 4
    supplies the type: the state is complete but unprojectable, so E_ECEF_RANGE (attribute
    Spatial) comes with the snapshot and no Entity is fabricated. Seq 5 moves to a valid
    position: eligible, revision 1. Seq 6 moves back to the centre: invalidated with
    projection_unavailable (no INVALID_ reason, no identity or retraction reason; SPEC:285)."""
    out = (started().frame(1, SECOND, reflect("o1", (EI, ID_123), (SP, SPATIAL_CENTRE)))
           .frame(1, 2 * SECOND, reflect("o1", (ET, TYPE)))
           .frame(1, 3 * SECOND, reflect("o1", (SP, SPATIAL_A)))
           .frame(1, 4 * SECOND, reflect("o1", (SP, SPATIAL_CENTRE))).reduce())
    assert briefs(out) == {
        3: [("snapshot", "o1", EID_1, "ACTIVE", ("GEOGRAPHY_UNPROJECTABLE", "MISSING_ENTITY_TYPE"),
             (EI, SP), 0)],
        4: [("diagnostic", "o1", EID_1, "E_ECEF_RANGE", SP),
            ("snapshot", "o1", EID_1, "ACTIVE", ("GEOGRAPHY_UNPROJECTABLE",), (ET,), 0)],
        5: [("snapshot", "o1", EID_1, "ACTIVE", (), (SP,), 0), ("upsert", "o1", EID_1, 1)],
        6: [("diagnostic", "o1", EID_1, "E_ECEF_RANGE", SP),
            ("invalidated", "o1", EID_1, "projection_unavailable", 1),
            ("snapshot", "o1", EID_1, "ACTIVE", ("GEOGRAPHY_UNPROJECTABLE",), (SP,), 1)],
    }


@case("G-R23", "G-R32")
def test_e_geodesy_through_the_geodesy_seam(monkeypatch):
    """OPS-19's named test for E_GEODESY. It cannot come from finite data (COD-12, CR-L06), so
    the real iteration runs with a bound of one step through R1's seam (`max_iterations`), at
    (30 deg, 40 deg, 1000 m), which needs five: E_GEODESY with the snapshot, attribute Spatial,
    and no Entity."""
    real = geodesy.project_spatial
    monkeypatch.setattr(geodesy, "project_spatial", lambda value: real(value, max_iterations=1))
    deep = encode_spatial(2, position=_forward(30.0, 40.0, 1000.0), velocity=(0.0, 0.0, 0.0))
    out = started().frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE),
                                             (SP, deep.hex()))).reduce()
    assert briefs(out) == {3: [
        ("diagnostic", "o1", EID_1, "E_GEODESY", SP),
        ("snapshot", "o1", EID_1, "ACTIVE", ("GEOGRAPHY_UNPROJECTABLE",), (EI, ET, SP), 0)]}


# ============================================================================ R24: identity

@case("A-COLLISION", "G-R24", paragraphs=("SPEC:281",))
def test_two_active_tokens_asserting_one_triple_quarantine_both():
    """A-COLLISION (R24, RED-10, RED-V-02). o1 holds 1.2.3 and is eligible (seq 3, revision 1).
    o2 asserts 1.2.3 at seq 5: E_IDENTITY_COLLISION for o1 (it keeps its entity_id) and for o2
    (none), in token order; o1 invalidated once (identity_collision) in o2's frame, and no
    snapshot of o1 there; o2's snapshot is QUARANTINED with no identity. Seq 6: o1 applies a
    force: QUARANTINED, no upsert, no second invalidation. Seq 7: o2, quarantined, applies 4.5.6:
    it never claims, so no diagnostic. Seq 8 removes o1, releasing 1.2.3; o3 claims it at seq 10
    with incarnation 2 (o2 never advanced the counter). Seq 11: generation_end invalidates o3
    only (o2 has no entity_id)."""
    out = (eligible().frame(1, SECOND, event_discover("o2", "SYNTHETIC-002"))
           .frame(1, 2 * SECOND, reflect("o2", (EI, ID_123), (ET, TYPE), (SP, SPATIAL_A)))
           .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1)))
           .frame(1, 4 * SECOND, reflect("o2", (EI, ID_456)))
           .frame(1, 4 * SECOND, event_remove("o1"))
           .frame(1, 4 * SECOND, event_discover("o3", "SYNTHETIC-003"))
           .frame(1, 5 * SECOND, reflect("o3", *FULL))
           .frame(1, 5 * SECOND, event_generation_end()).reduce())
    quarantined = ("QUARANTINED",)
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        5: [("diagnostic", "o1", EID_1, "E_IDENTITY_COLLISION", EI),
            ("diagnostic", "o2", None, "E_IDENTITY_COLLISION", EI),
            ("invalidated", "o1", EID_1, "identity_collision", 1),
            ("snapshot", "o2", None, "QUARANTINED", quarantined, (EI, ET, SP), 0)],
        6: [("snapshot", "o1", EID_1, "QUARANTINED", quarantined, (FI,), 1)],
        7: [("snapshot", "o2", None, "QUARANTINED", quarantined, (EI,), 0)],
        8: [("removed", "o1", EID_1, "removed", 1)],
        10: [("snapshot", "o3", EID_INC2, "ACTIVE", (), (EI, ET, FI, SP), 0),
             ("upsert", "o3", EID_INC2, 1)],
        11: [("invalidated", "o3", EID_INC2, "generation_end", 1)],
    }
    assert [r["kind"] for r in out[4]].count("invalidated") == 1
    second = snapshot_of(out[4])
    assert (second["identity"], second["incarnation"]) == (None, None)


@case("G-R24")
def test_removal_releases_the_triple_but_never_unquarantines_a_survivor():
    """R24: the index is released on removal, but a surviving object stays quarantined; only a
    new discovery after removal, or a new generation, starts unquarantined. o2 collides with o1
    (seq 5); o1 is removed (seq 6); o2 asserts 1.2.3 again (seq 7): still QUARANTINED, no
    claim, no diagnostic. In generation 2 the token o2 is a new object that claims 1.2.3 as
    incarnation 1 and projects."""
    out = (eligible().frame(1, SECOND, event_discover("o2", "SYNTHETIC-002"))
           .frame(1, 2 * SECOND, reflect("o2", (EI, ID_123), (ET, TYPE), (SP, SPATIAL_A)))
           .frame(1, 2 * SECOND, event_remove("o1"))
           .frame(1, 3 * SECOND, reflect("o2", (EI, ID_123)))
           .frame(1, 3 * SECOND, event_generation_end())
           .frame(2, 4 * SECOND, event_generation_start())
           .frame(2, 4 * SECOND, event_discover("o2", "SYNTHETIC-002"))
           .frame(2, 5 * SECOND, reflect("o2", (EI, ID_123), (ET, TYPE), (SP, SPATIAL_A)))
           ).reduce()
    assert briefs(out)[6] == [("removed", "o1", EID_1, "removed", 1)]
    assert briefs(out)[7] == [("snapshot", "o2", None, "QUARANTINED", ("QUARANTINED",), (EI,), 0)]
    assert briefs(out)[11] == [("snapshot", "o2", EID_GEN2, "ACTIVE", (), (EI, ET, SP), 0),
                               ("upsert", "o2", EID_GEN2, 1)]


@case("G-R24")
def test_e_identity_collision_names_each_newly_quarantined_token():
    """OPS-19's named test for E_IDENTITY_COLLISION (A-COLLISION has both tokens newly
    quarantined; here one). RED-10: one diagnostic for each NEWLY quarantined token. o1 claims
    1.2.3 and is quarantined by an identity change (seq 4); o2's claim of 1.2.3 (seq 6)
    quarantines o2 alone: one diagnostic, no invalidation (o1 is not eligible any more)."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (EI, ID_456)))
           .frame(1, 2 * SECOND, event_discover("o2", "SYNTHETIC-002"))
           .frame(1, 3 * SECOND, reflect("o2", (EI, ID_123))).reduce())
    assert briefs(out)[6] == [
        ("diagnostic", "o2", None, "E_IDENTITY_COLLISION", EI),
        ("snapshot", "o2", None, "QUARANTINED", ("MISSING_ENTITY_TYPE", "MISSING_SPATIAL",
                                                 "QUARANTINED"), (EI,), 0)]


@case("A-ID-CHANGE", "G-R24", paragraphs=("SPEC:281",))
def test_a_changed_identifier_quarantines_the_token_for_its_incarnation():
    """A-ID-CHANGE (R24, SPEC:281, RED-10). o1 is eligible as 1.2.3. Seq 4 applies 4.5.6:
    E_IDENTITY_CHANGED, quarantine and one invalidation (identity_changed); the identity stays
    1.2.3 (immutable once established) while the slot holds 4.5.6. Seq 5 applies 1.2.3 again:
    no diagnostic, but still QUARANTINED and no upsert (permanent for the incarnation). Seq 6:
    4.5.6 again: E_IDENTITY_CHANGED on every differing applied value, no second invalidation.
    Seq 7: 0.0.0: E_IDENTITY_CHANGED and E_NULL_ID (RED-10). Seq 8: generation_end invalidates
    the quarantined holder (RED-V-02)."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (EI, ID_456)))
           .frame(1, 3 * SECOND, reflect("o1", (EI, ID_123)))
           .frame(1, 4 * SECOND, reflect("o1", (EI, ID_456)))
           .frame(1, 5 * SECOND, reflect("o1", (EI, ID_NULL)))
           .frame(1, 5 * SECOND, event_generation_end()).reduce())
    q = ("QUARANTINED",)
    changed_ = ("diagnostic", "o1", EID_1, "E_IDENTITY_CHANGED", EI)
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [changed_, ("invalidated", "o1", EID_1, "identity_changed", 1),
            ("snapshot", "o1", EID_1, "QUARANTINED", q, (EI,), 1)],
        5: [("snapshot", "o1", EID_1, "QUARANTINED", q, (EI,), 1)],
        6: [changed_, ("snapshot", "o1", EID_1, "QUARANTINED", q, (EI,), 1)],
        7: [changed_, ("diagnostic", "o1", EID_1, "E_NULL_ID", EI),
            ("snapshot", "o1", EID_1, "QUARANTINED", ("NULL_ID", "QUARANTINED"), (EI,), 1)],
        8: [("invalidated", "o1", EID_1, "generation_end", 1)],
    }
    after = snapshot_of(out[3])
    assert after["identity"] == IDENTITY_123
    assert after["attributes"][EI]["value"] == {"site": 4, "application": 5, "entity": 6}


@case("G-R24", paragraphs=("SPEC:281",))
def test_a_null_identifier_on_an_established_identity_is_a_change():
    """SPEC:281: a valid 0.0.0 on a token whose identity is established is an identity change and
    quarantines it permanently: E_IDENTITY_CHANGED and E_NULL_ID, invalidated identity_changed."""
    out = eligible().frame(1, 2 * SECOND, reflect("o1", (EI, ID_NULL))).reduce()
    assert briefs(out)[4] == [
        ("diagnostic", "o1", EID_1, "E_IDENTITY_CHANGED", EI),
        ("diagnostic", "o1", EID_1, "E_NULL_ID", EI),
        ("invalidated", "o1", EID_1, "identity_changed", 1),
        ("snapshot", "o1", EID_1, "QUARANTINED", ("NULL_ID", "QUARANTINED"), (EI,), 1)]


@case("G-R24")
def test_an_identifier_that_decodes_invalidly_keeps_its_reservation():
    """R24: an identifier that temporarily decodes invalidly keeps its reservation and suppresses
    projection, and a later matching valid value restores eligibility under the same entity_id.
    Seq 4: a 5-byte identifier (INVALID). Seq 5: o1 matches again: eligible, revision 2. Seq 7:
    o2 asserting 1.2.3 collides with o1, which still holds it."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (EI, BAD["LENGTH-EntityIdentifier"])))
           .frame(1, 3 * SECOND, reflect("o1", (EI, ID_123)))
           .frame(1, 3 * SECOND, event_discover("o2", "SYNTHETIC-002"))
           .frame(1, 4 * SECOND, reflect("o2", (EI, ID_123)))).reduce()
    assert briefs(out)[4] == [
        ("diagnostic", "o1", EID_1, "E_ATTRIBUTE_LENGTH", EI),
        ("invalidated", "o1", EID_1, "invalid_required_attribute", 1),
        ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_ENTITY_IDENTIFIER",), (EI,), 1)]
    assert briefs(out)[5] == [("snapshot", "o1", EID_1, "ACTIVE", (), (EI,), 1),
                              ("upsert", "o1", EID_1, 2)]
    assert briefs(out)[7][:2] == [("diagnostic", "o1", EID_1, "E_IDENTITY_COLLISION", EI),
                                  ("diagnostic", "o2", None, "E_IDENTITY_COLLISION", EI)]


@case("G-R24")
def test_an_invalid_identifier_holder_still_holds_against_a_claimant():
    """RED-10: a holder whose identifier is currently INVALID still holds its triple: o2's claim
    while o1's slot is INVALID collides (o1 newly quarantined; it is not eligible, so no
    invalidation)."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (EI, BAD["LENGTH-EntityIdentifier"])))
           .frame(1, 2 * SECOND, event_discover("o2", "SYNTHETIC-002"))
           .frame(1, 3 * SECOND, reflect("o2", (EI, ID_123))).reduce())
    assert briefs(out)[6] == [
        ("diagnostic", "o1", EID_1, "E_IDENTITY_COLLISION", EI),
        ("diagnostic", "o2", None, "E_IDENTITY_COLLISION", EI),
        ("snapshot", "o2", None, "QUARANTINED",
         ("MISSING_ENTITY_TYPE", "MISSING_SPATIAL", "QUARANTINED"), (EI,), 0)]


# ============================================================================ R25: lifecycle

@case("A-REINCARNATE", "G-R25", paragraphs=("SPEC:291",))
def test_remove_then_rediscover_gives_the_next_incarnation_and_a_new_uuid():
    """A-REINCARNATE (R25, RED-13). o1 claims 1.2.3 (incarnation 1, 781e68de..., revision 1) and
    is removed; the worker gives the rediscovered handle a fresh token, o2, which claims 1.2.3
    as incarnation 2 (2cc17970...), its revisions starting at 1 again; removed again, o3 is
    incarnation 3. Each removal notice names its incarnation's entity_id."""
    out = (eligible().frame(1, SECOND, event_remove("o1"))
           .frame(1, SECOND, event_discover("o2"))
           .frame(1, 2 * SECOND, reflect("o2", *FULL))
           .frame(1, 2 * SECOND, event_remove("o2"))
           .frame(1, 2 * SECOND, event_discover("o3"))
           .frame(1, 3 * SECOND, reflect("o3", *FULL))
           .frame(1, 3 * SECOND, event_generation_end()).reduce())
    full = (EI, ET, FI, SP)
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("removed", "o1", EID_1, "removed", 1)],
        6: [("snapshot", "o2", EID_INC2, "ACTIVE", (), full, 0), ("upsert", "o2", EID_INC2, 1)],
        7: [("removed", "o2", EID_INC2, "removed", 1)],
        9: [("snapshot", "o3", EID_INC3, "ACTIVE", (), full, 0), ("upsert", "o3", EID_INC3, 1)],
        10: [("invalidated", "o3", EID_INC3, "generation_end", 1)],
    }
    assert [snapshot_of(out[k])["incarnation"] for k in (2, 5, 8)] == [1, 2, 3]
    assert upsert_of(out[5])["source_ids"] == [{
        "system": "hla-rpr2", "external_id": '["example-001","1","1","2","3","2"]'}]


@case("G-R25", paragraphs=("SPEC:126",))
def test_a_new_generation_resets_incarnations_and_changes_the_identity():
    """R25: reconnect resets incarnation counters but changes generation, keeping identities
    distinct (SPEC:126: nothing is carried into the new generation). Generation 2 claims 1.2.3
    as incarnation 1 under generation 2: 552c4e02..., not 781e68de...; o1 of generation 2 is a
    new object (its reflect before its discover would be E_UNKNOWN_OBJECT)."""
    out = (eligible().frame(1, SECOND, event_generation_end("connection_lost"))
           .frame(0, SECOND, event_diagnostic("E_RTI_CONNECT"))
           .frame(2, 2 * SECOND, event_generation_start())
           .frame(2, 2 * SECOND, reflect("o1", (FI, FORCE_1)))
           .frame(2, 2 * SECOND, event_discover("o1"))
           .frame(2, 3 * SECOND, reflect("o1", *FULL)).reduce())
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("invalidated", "o1", EID_1, "generation_end", 1)],
        5: [("diagnostic", None, None, "E_RTI_CONNECT", None)],
        7: [("diagnostic", "o1", None, "E_UNKNOWN_OBJECT", None)],
        9: [("snapshot", "o1", EID_GEN2, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_GEN2, 1)],
    }
    assert out[8][1]["generation"] == 2 and snapshot_of(out[8])["incarnation"] == 1


@case("A-REMOVE", "G-R25", paragraphs=("SPEC:291",))
def test_remove_an_eligible_entity_then_repeat():
    """A-REMOVE (R25, RED-13, SPEC:291). Seq 4 removes o1: one `removed` record naming its
    entity_id with last_revision 1 and nothing else in its payload: no Entity is synthesized and
    there is no valid_to. Seq 5 removes o1 again: W_DUPLICATE_REMOVE (the removed-token set
    tells it from an unknown token). Seq 6 reflects o1: E_UNKNOWN_OBJECT (RED-13). The cache is
    deleted: the state holds no o1 and no byte of it."""
    scenario = (eligible().frame(1, 2 * SECOND, event_remove("o1"))
                .frame(1, 2 * SECOND, event_remove("o1"))
                .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1)))
                .frame(1, 3 * SECOND, event_generation_end()))
    out = scenario.reduce()
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("removed", "o1", EID_1, "removed", 1)],
        5: [("diagnostic", "o1", None, "W_DUPLICATE_REMOVE", None)],
        6: [("diagnostic", "o1", None, "E_UNKNOWN_OBJECT", None)],
    }
    assert out[3][0]["payload"] == {"reason": "removed", "last_revision": 1}
    after = scenario.states[4]
    assert (after.objects, after.index, after.cache_bytes, after.removed) == (
        {}, {}, 0, frozenset({"o1"}))


@case("A-END", "G-R25", paragraphs=("SPEC:126",))
def test_generation_end_invalidates_every_identified_object_in_token_number_order():
    """A-END (SPEC:126, RED-V-02). Five objects discovered as o10, o2, o1, o3, o4: o1 eligible
    (revision 1), o2 identified but never eligible (revision 0), o10 eligible twice (revision
    2), o3 never identified, o4 identified and removed. generation_end (seq 13) invalidates o1,
    o2, o10, in that order (by token number: as strings o10 would sort before o2), reason
    generation_end, each with its last revision; not o3 (no identity) and not o4 (removed).
    Then nothing survives: an empty state, and o1 is unknown in generation 2."""
    full_789 = ((EI, ID_789), (ET, TYPE), (SP, SPATIAL_A))
    scenario = Scenario().frame(1, 0, event_generation_start())
    for token in ("o10", "o2", "o1", "o3", "o4"):
        scenario.frame(1, 0, event_discover(token))
    (scenario.frame(1, SECOND, reflect("o1", *FULL))
     .frame(1, SECOND, reflect("o2", (EI, ID_456)))
     .frame(1, SECOND, reflect("o10", *full_789))
     .frame(1, 2 * SECOND, reflect("o10", (SP, SPATIAL_B)))
     .frame(1, 2 * SECOND, reflect("o3", (ET, TYPE)))
     .frame(1, 2 * SECOND, reflect("o4", (EI, ID_ABC)))
     .frame(1, 2 * SECOND, event_remove("o4"))
     .frame(1, 3 * SECOND, event_generation_end())
     .frame(2, 4 * SECOND, event_generation_start())
     .frame(2, 4 * SECOND, reflect("o1", (FI, FORCE_1))))
    out = scenario.reduce()
    missing_type_and_spatial = ("MISSING_ENTITY_TYPE", "MISSING_SPATIAL")
    assert briefs(out) == {
        7: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_1, 1)],
        8: [("snapshot", "o2", EID_456, "ACTIVE", missing_type_and_spatial, (EI,), 0)],
        9: [("snapshot", "o10", EID_789, "ACTIVE", (), (EI, ET, SP), 0),
            ("upsert", "o10", EID_789, 1)],
        10: [("snapshot", "o10", EID_789, "ACTIVE", (), (SP,), 1),
             ("upsert", "o10", EID_789, 2)],
        11: [("snapshot", "o3", None, "ACTIVE", ("MISSING_ENTITY_IDENTIFIER", "MISSING_SPATIAL"),
              (ET,), 0)],
        12: [("snapshot", "o4", EID_ABC, "ACTIVE", missing_type_and_spatial, (EI,), 0)],
        13: [("removed", "o4", EID_ABC, "removed", 0)],
        14: [("invalidated", "o1", EID_1, "generation_end", 1),
             ("invalidated", "o2", EID_456, "generation_end", 0),
             ("invalidated", "o10", EID_789, "generation_end", 2)],
        16: [("diagnostic", "o1", None, "E_UNKNOWN_OBJECT", None)],
    }
    after = scenario.states[14]
    assert (after.generation, after.objects, after.index, after.incarnations, after.removed,
            after.seen, after.cache_bytes, after.terminal) == (
        None, {}, {}, {}, frozenset(), frozenset(), 0, False)


@case("A-RETRACT", "G-R22", "G-R24", paragraphs=("SPEC:281",))
def test_retractable_callbacks_are_diagnosed_quarantined_and_never_applied():
    """A-RETRACT (R13, RED-11, OPS-05: crafted frames). o1 eligible. Seq 4: a retractable
    reflection of force 255: E_RETRACTION_UNSUPPORTED (no attribute), quarantine, one invalidated
    (retraction_unsupported), a snapshot whose changed attributes list ForceIdentifier while the
    slot keeps seq 3 and value 1 (nothing applied, nothing decoded, no W_FORCE_UNMAPPED). Seq 5:
    a retractable remove: the diagnostic only (already ineligible), the object kept. Seq 6: an
    empty retractable reflection: the diagnostic only, no snapshot. Seq 7: an ordinary reflect:
    the quarantined object applies it, still no upsert. Seq 8: an ordinary remove: removed."""
    out = (eligible().frame(1, 2 * SECOND, reflect("o1", (FI, FORCE_255), retractable=True))
           .frame(1, 2 * SECOND, retractable_remove("o1"))
           .frame(1, 2 * SECOND, reflect("o1", retractable=True))
           .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1)))
           .frame(1, 3 * SECOND, event_remove("o1")).reduce())
    retraction = ("diagnostic", "o1", EID_1, "E_RETRACTION_UNSUPPORTED", None)
    q = ("QUARANTINED",)
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [retraction, ("invalidated", "o1", EID_1, "retraction_unsupported", 1),
            ("snapshot", "o1", EID_1, "QUARANTINED", q, (FI,), 1)],
        5: [retraction],
        6: [retraction],
        7: [("snapshot", "o1", EID_1, "QUARANTINED", q, (FI,), 1)],
        8: [("removed", "o1", EID_1, "removed", 1)],
    }
    assert snapshot_of(out[3])["attributes"][FI] == slot("VALID", {"value": 1}, FORCE_1, 3,
                                                          str(SECOND), at(SECOND))
    assert snapshot_of(out[6])["attributes"][FI]["seq"] == 7


@case("A-RETRACT", "G-R24", "G-R25", paragraphs=("SPEC:281",))
def test_a_retractable_remove_quarantines_and_keeps_the_cache():
    """SPEC:281, RED-11: a retractable removal of an eligible object emits the diagnostic and the
    invalidation (retraction_unsupported) and nothing else: no removal notice; the object, its
    cached bytes and its reservation stay (a claim of 1.2.3 by o2 still collides)."""
    scenario = (eligible().frame(1, 2 * SECOND, retractable_remove("o1"))
                .frame(1, 2 * SECOND, event_discover("o2", "SYNTHETIC-002"))
                .frame(1, 3 * SECOND, reflect("o2", (EI, ID_123))))
    out = scenario.reduce()
    assert briefs(out)[4] == [("diagnostic", "o1", EID_1, "E_RETRACTION_UNSUPPORTED", None),
                              ("invalidated", "o1", EID_1, "retraction_unsupported", 1)]
    kept = scenario.states[4]
    assert kept.objects["o1"].lifecycle == "QUARANTINED"
    assert kept.cache_bytes == 6 + 8 + 1 + 60 and kept.index == {(1, 2, 3): "o1"}
    assert briefs(out)[6][0] == ("diagnostic", "o2", None, "E_IDENTITY_COLLISION", EI)


@case("A-RETRACT", "G-R22", "G-R24", paragraphs=("SPEC:281",))
def test_an_empty_retractable_reflection_quarantines_and_invalidates_an_eligible_object():
    """RED-11: a retractable reflect "(even empty) emits E_RETRACTION_UNSUPPORTED (attribute
    null), quarantines and invalidates if eligible (retraction_unsupported), with no decoding and
    nothing applied"; SPEC:281: capture and quarantine without applying. Here the empty
    retractable reflection meets an object that is still eligible (review finding R4-r1-F1).

    o1 is eligible at seq 3 (revision 1). Seq 4, an empty retractable reflection: the diagnostic
    (its envelope names o1's entity, which quarantine does not take away, RED-03) and one
    invalidated (retraction_unsupported, last revision 1), and no snapshot, because the
    reflection is empty (SPEC:116; RED-11 adds the snapshot only "if nonempty"). Nothing is
    decoded or applied: o1's slots, cached bytes and reservation are seq 3's, and o1 is
    QUARANTINED and no longer eligible. Seq 5, an ordinary force reflection, is applied (a
    quarantined object keeps applying valid values) and gives a QUARANTINED snapshot, no upsert
    and no second invalidation (once per transition, SPEC:285). Seq 6, a second empty
    retractable reflection: the diagnostic alone. o2 (discovered at seq 7) is not eligible: an
    empty retractable reflection (seq 8) gives the diagnostic alone (no entity, nothing to
    invalidate) and still quarantines it, so its complete state at seq 9 claims nothing and
    never projects (RED-10: a quarantined token never claims)."""
    scenario = (eligible().frame(1, 2 * SECOND, reflect("o1", retractable=True))
                .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1)))
                .frame(1, 3 * SECOND, reflect("o1", retractable=True))
                .frame(1, 3 * SECOND, event_discover("o2", "SYNTHETIC-002"))
                .frame(1, 3 * SECOND, reflect("o2", retractable=True))
                .frame(1, 4 * SECOND, reflect("o2", (EI, ID_456), (ET, TYPE), (SP, SPATIAL_A))))
    out = scenario.reduce()
    quarantined = ("QUARANTINED",)
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("diagnostic", "o1", EID_1, "E_RETRACTION_UNSUPPORTED", None),
            ("invalidated", "o1", EID_1, "retraction_unsupported", 1)],
        5: [("snapshot", "o1", EID_1, "QUARANTINED", quarantined, (FI,), 1)],
        6: [("diagnostic", "o1", EID_1, "E_RETRACTION_UNSUPPORTED", None)],
        8: [("diagnostic", "o2", None, "E_RETRACTION_UNSUPPORTED", None)],
        9: [("snapshot", "o2", None, "QUARANTINED", quarantined, (EI, ET, SP), 0)],
    }
    states = scenario.states
    before, after = states[3].objects["o1"], states[4].objects["o1"]
    assert (after.lifecycle, after.eligible, after.last_revision) == ("QUARANTINED", False, 1)
    assert (after.identity, after.incarnation, after.entity_id) == ((1, 2, 3), 1, EID_1)
    assert after.slots == before.slots
    assert states[4].cache_bytes == states[3].cache_bytes == 6 + 8 + 1 + 60
    assert states[4].index == {(1, 2, 3): "o1"}
    assert snapshot_of(out[4])["attributes"][FI] == slot("VALID", {"value": 1}, FORCE_1, 5,
                                                          str(3 * SECOND), at(3 * SECOND))
    second = states[8].objects["o2"]
    assert (second.lifecycle, second.eligible, second.slots) == (
        "QUARANTINED", False, (reducer.ABSENT_SLOT,) * 4)
    assert (states[9].objects["o2"].identity, states[9].index, states[9].incarnations) == (
        None, {(1, 2, 3): "o1"}, {(1, 2, 3): 1})


@case("A-UNKNOWN", "A-RETRACT", "G-R22", "G-R25")
def test_retractable_callbacks_for_a_token_that_is_not_an_object_quarantine_nothing():
    """CR-new-R4-09 (review finding R4-r1-F2): a retractable reflect or remove for a token that
    is not a discovered, unremoved object has no object to quarantine, so it is judged as the
    unknown or repeated callback it is (R22: unknown tokens are diagnosed and never
    auto-discovered; R25: unknown and repeated removals are diagnostic no-ops; RED-13), never as
    a retraction.

    o1 is eligible (seq 3). For o9, which no discover introduced, a retractable reflection with
    a force (seq 4), an empty one (seq 5) and a retractable removal (seq 6) are each
    E_UNKNOWN_OBJECT (no entity, no attribute) and nothing else; o1 is untouched. After o1's
    removal (seq 7), a retractable removal of o1 (seq 8) is W_DUPLICATE_REMOVE, and a
    retractable reflection of o1 with a force (seq 9) or empty (seq 10) is E_UNKNOWN_OBJECT. No
    frame creates or quarantines an object, and generation_end (seq 11) has nothing to
    invalidate. o9 counts once as a distinct token: the worker allocated it (NAT-11)."""
    scenario = (eligible().frame(1, 2 * SECOND, reflect("o9", (FI, FORCE_1), retractable=True))
                .frame(1, 2 * SECOND, reflect("o9", retractable=True))
                .frame(1, 2 * SECOND, retractable_remove("o9"))
                .frame(1, 3 * SECOND, event_remove("o1"))
                .frame(1, 3 * SECOND, retractable_remove("o1"))
                .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1), retractable=True))
                .frame(1, 3 * SECOND, reflect("o1", retractable=True))
                .frame(1, 3 * SECOND, event_generation_end()))
    out = scenario.reduce()
    unknown_o9 = ("diagnostic", "o9", None, "E_UNKNOWN_OBJECT", None)
    unknown_o1 = ("diagnostic", "o1", None, "E_UNKNOWN_OBJECT", None)
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [unknown_o9],
        5: [unknown_o9],
        6: [unknown_o9],
        7: [("removed", "o1", EID_1, "removed", 1)],
        8: [("diagnostic", "o1", None, "W_DUPLICATE_REMOVE", None)],
        9: [unknown_o1],
        10: [unknown_o1],
    }
    states = scenario.states
    for k in (4, 5, 6):
        assert states[k].objects == states[3].objects, k
        assert states[k].objects["o1"].lifecycle == "ACTIVE" and states[k].objects["o1"].eligible
        assert (states[k].removed, states[k].index, states[k].cache_bytes) == (
            frozenset(), {(1, 2, 3): "o1"}, 6 + 8 + 1 + 60), k
    for k in (8, 9, 10):
        assert (states[k].objects, states[k].removed, states[k].index, states[k].cache_bytes) \
            == ({}, frozenset({"o1"}), {}, 0), k
    assert not any(state.terminal for state in states)
    assert states[6].distinct_tokens == states[10].distinct_tokens == 2


@case("G-R25", paragraphs=("SPEC:291",))
@case("G-R40", paragraphs=("SPEC:291",))
def test_w_duplicate_discovery_and_the_red_07_rediscovery():
    """OPS-19's named test for W_DUPLICATE_DISCOVERY, and RED-07 / RED-13 (SPEC:291). Seq 4
    rediscovers o1 with the same name and class: W_DUPLICATE_DISCOVERY, nothing changes. Seq 5
    with another name and seq 6 with another class: E_CAPTURE_SCHEMA (ERROR, the token, no
    attribute), the object unchanged, the terminal flag set. Seq 8 discovers the removed o2:
    E_CAPTURE_SCHEMA with no entity (the token is removed)."""
    scenario = (eligible().frame(1, SECOND, event_discover("o1"))
                .frame(1, SECOND, event_discover("o1", "RENAMED"))
                .frame(1, SECOND, event_discover("o1", reported_class=PHYSICAL + ".Platform"))
                .frame(1, SECOND, event_discover("o2"))
                .frame(1, SECOND, event_remove("o2"))
                .frame(1, SECOND, event_discover("o2")))
    out = scenario.reduce()
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("diagnostic", "o1", EID_1, "W_DUPLICATE_DISCOVERY", None)],
        5: [("diagnostic", "o1", EID_1, "E_CAPTURE_SCHEMA", None)],
        6: [("diagnostic", "o1", EID_1, "E_CAPTURE_SCHEMA", None)],
        8: [("removed", "o2", None, "removed", 0)],
        9: [("diagnostic", "o2", None, "E_CAPTURE_SCHEMA", None)],
    }
    states = scenario.states
    assert states[4].objects == states[3].objects and not states[4].terminal
    assert states[5].objects["o1"].name == "SYNTHETIC-001" and states[5].terminal
    assert states[6].objects["o1"] == states[3].objects["o1"]
    assert "o2" not in states[9].objects


@case("G-R25", paragraphs=("SPEC:291",))
def test_discovering_a_removed_token_is_a_terminal_capture_fault():
    """RED-13 and RED-07 with CR-new-R4-03 (review finding R4-r1-F4, item 1): only a discover
    allocates a fresh token, so a discover that names a REMOVED token is a capture fault:
    E_CAPTURE_SCHEMA (the token, no attribute, no entity: the token is removed), nothing is
    created, and the terminal flag is set, the one signal the live host stops on (round R5).
    o1 is eligible (seq 3) and removed (seq 4, not terminal); seq 5 discovers o1 again; the
    flag ends with the generation (seq 6)."""
    scenario = (eligible().frame(1, 2 * SECOND, event_remove("o1"))
                .frame(1, 2 * SECOND, event_discover("o1"))
                .frame(1, 2 * SECOND, event_generation_end()))
    out = scenario.reduce()
    assert briefs(out) == {3: ELIGIBLE_AT_3,
                           4: [("removed", "o1", EID_1, "removed", 1)],
                           5: [("diagnostic", "o1", None, "E_CAPTURE_SCHEMA", None)]}
    states = scenario.states
    assert [state.terminal for state in states] == [False, False, False, False, False, True,
                                                    False]
    assert (states[5].objects, states[5].removed, states[5].index, states[5].cache_bytes) == (
        {}, frozenset({"o1"}), {}, 0)


@case("G-R25", paragraphs=("SPEC:291",))
def test_a_quarantined_object_rediscovered_alike_is_a_duplicate_and_warns_its_new_force():
    """Review finding R4-r2-F3 (round R5 carry-in). RED-11: "active = discovered and not removed
    (ACTIVE or QUARANTINED)", and quarantined objects "keep applying valid values"; SPEC:291: a
    still-active handle rediscovered with the same name and class is a warning only; RED-17: an
    applied VALID force absent from force_map warns once per object per new value.

    o1 is eligible at seq 3 with force 1 (mapped FRIENDLY in the fixture's force_map). Seq 4, an
    empty retractable reflection, quarantines it (the diagnostic and one invalidated, no
    snapshot). Seq 5 rediscovers o1 with the same name and class: W_DUPLICATE_DISCOVERY, not the
    fatal E_CAPTURE_SCHEMA; nothing changes and the state is not terminal. Seq 6 applies force 255
    (unmapped): W_FORCE_UNMAPPED (attribute ForceIdentifier) and a QUARANTINED snapshot, no upsert.
    Seq 7, force 255 again: the snapshot alone, no second warning."""
    scenario = (eligible().frame(1, 2 * SECOND, reflect("o1", retractable=True))
                .frame(1, 2 * SECOND, event_discover("o1"))
                .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_255)))
                .frame(1, 4 * SECOND, reflect("o1", (FI, FORCE_255))))
    out = scenario.reduce()
    quarantined = ("QUARANTINED",)
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        4: [("diagnostic", "o1", EID_1, "E_RETRACTION_UNSUPPORTED", None),
            ("invalidated", "o1", EID_1, "retraction_unsupported", 1)],
        5: [("diagnostic", "o1", EID_1, "W_DUPLICATE_DISCOVERY", None)],
        6: [("diagnostic", "o1", EID_1, "W_FORCE_UNMAPPED", FI),
            ("snapshot", "o1", EID_1, "QUARANTINED", quarantined, (FI,), 1)],
        7: [("snapshot", "o1", EID_1, "QUARANTINED", quarantined, (FI,), 1)],
    }
    states = scenario.states
    assert states[5].objects == states[4].objects and not states[5].terminal
    assert states[6].objects["o1"].lifecycle == "QUARANTINED"
    # out[k] holds the records of seq k + 1: the seq-6 snapshot carries the force applied at 6.
    assert snapshot_of(out[5])["attributes"][FI] == slot("VALID", {"value": 255}, FORCE_255, 6,
                                                          str(3 * SECOND), at(3 * SECOND))
    assert not any(state.terminal for state in states)


# ============================================================================ time

@case("A-TIME-CONTEXT", "G-R32", "G-R20", paragraphs=("SPEC:154",))
def test_a_force_only_update_keeps_the_spatial_effective_time():
    """A-TIME-CONTEXT (R32: valid_from is the time of the most recently accepted Spatial value,
    never of a later force-only update) and R20's carried clause: no position is extrapolated.
    o1 is eligible at 1 s moving east at 10 m/s; seq 4, 4.5 s later, supplies only the force:
    revision 2 keeps valid_from 00:00:01.000 and the time block's 00:00:01.000000 and Spatial seq
    3, at the same position (lat 0, lon 0, alt 0: extrapolation would have moved it 45 m east),
    while the force slot carries its own time 00:00:05.500000."""
    out = eligible().frame(1, 5_500_000_000, reflect("o1", (FI, FORCE_1))).reduce()
    assert briefs(out) == {3: ELIGIBLE_AT_3,
                           4: [("snapshot", "o1", EID_1, "ACTIVE", (), (FI,), 1),
                               ("upsert", "o1", EID_1, 2)]}
    entity = upsert_of(out[3])
    assert entity["valid_from"] == "2026-01-01T00:00:01.000Z"
    assert entity["attributes"]["hla"]["time"]["effective_at"] == "2026-01-01T00:00:01.000000Z"
    assert entity["attributes"]["hla"]["time"]["spatial_seq"] == 3
    assert (entity["position"]["lat"], entity["position"]["lon"], entity["position"]["alt_m"]) \
        == (0.0, 0.0, 0.0)
    assert entity["kinematics"] == {"speed_mps": 10.0, "course_deg": 90.0, "climb_mps": 0.0}
    assert snapshot_of(out[3])["attributes"][FI]["effective_at"] == "2026-01-01T00:00:05.500000Z"
    assert snapshot_of(out[3])["attributes"][SP]["effective_at"] == "2026-01-01T00:00:01.000000Z"


@case("G-R32", paragraphs=("SPEC:154",))
@pytest.mark.parametrize("elapsed,effective_at,valid_from", [
    (1_000_000_999, "2026-01-01T00:00:01.000000Z", "2026-01-01T00:00:01.000Z"),
    (1_999_999_999, "2026-01-01T00:00:01.999999Z", "2026-01-01T00:00:01.999Z"),
    (59_000_999_000, "2026-01-01T00:00:59.000999Z", "2026-01-01T00:00:59.000Z"),
])
def test_effective_time_truncates_nanoseconds_and_valid_from_truncates_microseconds(
        elapsed, effective_at, valid_from):
    """CR-L05: effective time = epoch + elapsed_ns // 1000 (microseconds, truncated), and
    valid_from cuts it to milliseconds; every slot of the frame carries the same time."""
    out = started().frame(1, elapsed, reflect("o1", *FULL)).reduce()
    entity = upsert_of(out[2])
    assert entity["valid_from"] == valid_from
    assert entity["attributes"]["hla"]["time"]["effective_at"] == effective_at
    assert {n: s["effective_at"] for n, s in snapshot_of(out[2])["attributes"].items()} == \
        dict.fromkeys((EI, ET, FI, SP), effective_at)


def _regression_frames():
    """Frames whose elapsed_ns decreases at seq 4 (5 s, then 3 s): a capture can never hold this
    (verify refuses it), so only a direct reduce_frame call meets it (RED-09). Seq 6 repeats
    seq 5's time: equal is allowed."""
    return (started().frame(1, 5 * SECOND, reflect("o1", *FULL))
            .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_255), (SP, SPATIAL_B)))
            .frame(1, 6 * SECOND, reflect("o1", (SP, SPATIAL_A)))
            .frame(1, 6 * SECOND, reflect("o1", (SP, SPATIAL_B))))


@case("G-R32", paragraphs=("SPEC:154",))
def test_e_time_regression_through_a_direct_reduce_frame_call(tmp_path):
    """OPS-19's named test for E_TIME_REGRESSION (RED-09, SPEC:154). Seq 4 supplies a Spatial
    whose effective time (3 s) is earlier than the accepted one (5 s), with force 255: the
    Spatial slot turns INVALID (no value; this frame's hex, seq, elapsed and time), E_TIME_
    REGRESSION names Spatial, o1 is invalidated (invalid_required_attribute), and the force,
    supplied in the same frame, still applies (VALID 255, and its W_FORCE_UNMAPPED). Seq 5 at 6 s
    is accepted again: revision 2, valid_from 6 s; seq 6 at the same 6 s too (equal is allowed:
    revision 3). The same capture is refused by verify."""
    scenario = _regression_frames()
    out = scenario.reduce()
    assert briefs(out) == {
        3: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_1, 1)],
        4: [("diagnostic", "o1", EID_1, "E_TIME_REGRESSION", SP),
            ("diagnostic", "o1", EID_1, "W_FORCE_UNMAPPED", FI),
            ("invalidated", "o1", EID_1, "invalid_required_attribute", 1),
            ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_SPATIAL",), (FI, SP), 1)],
        5: [("snapshot", "o1", EID_1, "ACTIVE", (), (SP,), 1), ("upsert", "o1", EID_1, 2)],
        6: [("snapshot", "o1", EID_1, "ACTIVE", (), (SP,), 2), ("upsert", "o1", EID_1, 3)],
    }
    slots = snapshot_of(out[3])["attributes"]
    assert slots[SP] == slot("INVALID", None, SPATIAL_B, 4, str(3 * SECOND), at(3 * SECOND))
    assert slots[FI] == slot("VALID", {"value": 255}, FORCE_255, 4, str(3 * SECOND),
                             at(3 * SECOND))
    assert upsert_of(out[4])["valid_from"] == "2026-01-01T00:00:06.000Z"
    report = synapse_hla.verify_capture(scenario.footer().write(tmp_path / "regress.jsonl"))
    assert (report["status"], report["code"], report["path"]) == (
        "INVALID", "E_CAPTURE_SCHEMA", "line:5#/elapsed_ns")


@case("G-R32", paragraphs=("SPEC:154",))
def test_a_rejected_spatial_never_lowers_the_regression_bar():
    """CR-new-R4-07, second half (review finding R4-r1-F4, item 5): RED-09's bar is the effective
    time of the last ACCEPTED Spatial value, so the earlier time of a rejected (INVALID) Spatial
    never lowers it, and valid_from never goes back (R32). Direct reduce_frame calls, elapsed_ns
    decreasing as only such calls allow. Spatial is accepted at 5 s (seq 3, revision 1); at 3 s
    (seq 4) it is E_TIME_REGRESSION, the slot INVALID and o1 invalidated; at 4 s (seq 5) it is
    E_TIME_REGRESSION again, although 4 s is later than the INVALID slot's 3 s (no second
    invalidation: o1 is not eligible); at 5 s (seq 6), equal to the bar, it is accepted:
    revision 2, valid_from 5 s, the time block citing seq 6."""
    scenario = (started().frame(1, 5 * SECOND, reflect("o1", *FULL))
                .frame(1, 3 * SECOND, reflect("o1", (SP, SPATIAL_A)))
                .frame(1, 4 * SECOND, reflect("o1", (SP, SPATIAL_A)))
                .frame(1, 5 * SECOND, reflect("o1", (SP, SPATIAL_A))))
    out = scenario.reduce()
    regression = ("diagnostic", "o1", EID_1, "E_TIME_REGRESSION", SP)
    rejected = ("snapshot", "o1", EID_1, "ACTIVE", ("INVALID_SPATIAL",), (SP,), 1)
    assert briefs(out) == {
        3: [("snapshot", "o1", EID_1, "ACTIVE", (), (EI, ET, FI, SP), 0),
            ("upsert", "o1", EID_1, 1)],
        4: [regression, ("invalidated", "o1", EID_1, "invalid_required_attribute", 1), rejected],
        5: [regression, rejected],
        6: [("snapshot", "o1", EID_1, "ACTIVE", (), (SP,), 1), ("upsert", "o1", EID_1, 2)],
    }
    assert snapshot_of(out[3])["attributes"][SP] == slot("INVALID", None, SPATIAL_A, 4,
                                                          str(3 * SECOND), at(3 * SECOND))
    assert snapshot_of(out[4])["attributes"][SP] == slot("INVALID", None, SPATIAL_A, 5,
                                                          str(4 * SECOND), at(4 * SECOND))
    entity = upsert_of(out[5])
    assert entity["valid_from"] == "2026-01-01T00:00:05.000Z"
    assert entity["attributes"]["hla"]["time"]["spatial_seq"] == 6


@case("A-NO-TIME", "G-R08", "G-R11", "G-R23", "G-R32", paragraphs=("SPEC:285", "SPEC:154"))
def test_a_capture_recorded_under_time_policy_none():
    """A-NO-TIME and R08's carried clause (time policy none gives normalized observations and no
    Entity), on a capture recorded with config-existing (RED-19: the header says none, nothing
    overrides it): W_FOM_UNVERIFIED at generation_start (existing mode, R11); seq 3 (identifier
    and type) lists MISSING_SPATIAL and TIME_UNRESOLVED and does not warn (incomplete, SPEC:285);
    from seq 4 on the state is complete and every snapshot carries W_TIME_UNRESOLVED (one per
    snapshot, RED-02); seq 6 adds W_FORCE_UNMAPPED (the map is empty). No upsert at all; every
    effective_at is null; generation_end invalidates the identity it allocated (last_revision
    0, RED-V-02)."""
    existing = example_json("config-existing.json")
    header = header_with(**existing)
    eid_local = eid("local-observation", 1, (1, 2, 3), 1)
    out = (started(header).frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE)))
           .frame(1, 2 * SECOND, reflect("o1", (SP, SPATIAL_A)))
           .frame(1, 3 * SECOND, reflect("o1", (SP, SPATIAL_B)))
           .frame(1, 4 * SECOND, reflect("o1", (FI, FORCE_1)))
           .frame(1, 4 * SECOND, event_generation_end()).reduce())
    unresolved = ("diagnostic", "o1", eid_local, "W_TIME_UNRESOLVED", None)
    only_time = ("TIME_UNRESOLVED",)
    assert briefs(out) == {
        1: [("diagnostic", None, None, "W_FOM_UNVERIFIED", None)],
        3: [("snapshot", "o1", eid_local, "ACTIVE", ("MISSING_SPATIAL", "TIME_UNRESOLVED"),
             (EI, ET), 0)],
        4: [unresolved, ("snapshot", "o1", eid_local, "ACTIVE", only_time, (SP,), 0)],
        5: [unresolved, ("snapshot", "o1", eid_local, "ACTIVE", only_time, (SP,), 0)],
        6: [("diagnostic", "o1", eid_local, "W_FORCE_UNMAPPED", FI), unresolved,
            ("snapshot", "o1", eid_local, "ACTIVE", only_time, (FI,), 0)],
        7: [("invalidated", "o1", eid_local, "generation_end", 0)],
    }
    assert all(s["effective_at"] is None for records in out for r in records
               if r["kind"] == "snapshot" for s in r["payload"]["attributes"].values())
    assert all(r["session_id"] == "local-observation" for records in out for r in records)


@case("G-R11")
def test_w_fom_unverified_once_per_generation_in_existing_mode_only():
    """OPS-19's named test for W_FOM_UNVERIFIED (R11, RED-01): derived by the reducer at each
    generation_start when the header declares external-fom-unverified, once per generation,
    with no token and no attribute; never under bundled-fom-created; the provenance of an
    Entity keeps the declaration (profile_verification); and the decoders stay strict under
    it (R11: a 1-byte EntityType at seq 4 is E_ATTRIBUTE_LENGTH as in any mode)."""
    existing = header_with(mode="existing", profile_declaration="external-fom-unverified",
                           force_map={"1": "FRIENDLY"})
    two = (eligible(existing).frame(1, 2 * SECOND, reflect("o1", (ET, "00")))
           .frame(1, 2 * SECOND, event_generation_end())
           .frame(2, 3 * SECOND, event_generation_start())
           .frame(2, 3 * SECOND, event_generation_end()))
    out = two.reduce()
    warned = ("diagnostic", None, None, "W_FOM_UNVERIFIED", None)
    assert briefs(out)[1] == [warned] and briefs(out)[6] == [warned]
    assert briefs(out)[4][0] == ("diagnostic", "o1", EID_1, "E_ATTRIBUTE_LENGTH", ET)
    assert sum(r["kind"] == "diagnostic" and r["payload"]["code"] == "W_FOM_UNVERIFIED"
               for records in out for r in records) == 2
    assert upsert_of(out[2])["attributes"]["hla"]["profile_verification"] == \
        "external-fom-unverified"
    demo = eligible().reduce()
    assert not any(r["kind"] == "diagnostic" for records in demo for r in records)
    assert upsert_of(demo[2])["attributes"]["hla"]["profile_verification"] == "bundled-fom-created"


# ============================================================================ limits (RED-12)

def _limits(**members):
    return dataclasses.replace(V1, **members)


@case("G-R21", "G-R25")
def test_active_objects_at_the_limit_and_one_past_it():
    """RED-12 and OPS-22 through the limits seam (2 active objects): o1 and o2 are admitted, o3
    is E_LIMIT (token, no attribute, no entity), not admitted, and the state is terminal. After
    o1's removal the count is 1 and o4 is admitted (each frame is judged on its own); the flag
    ends with the generation."""
    scenario = (Scenario().frame(1, 0, event_generation_start())
                .frame(1, 0, event_discover("o1")).frame(1, 0, event_discover("o2"))
                .frame(1, 0, event_discover("o3"))
                .frame(1, 0, event_remove("o1")).frame(1, 0, event_discover("o4"))
                .frame(1, 0, event_generation_end()))
    out = scenario.reduce(limits=_limits(active_objects_per_generation=2))
    assert briefs(out) == {4: [("diagnostic", "o3", None, "E_LIMIT", None)],
                           5: [("removed", "o1", None, "removed", 0)]}
    states = scenario.states
    assert set(states[3].objects) == {"o1", "o2"} and not states[3].terminal
    assert set(states[4].objects) == {"o1", "o2"} and states[4].terminal
    assert set(states[6].objects) == {"o2", "o4"} and states[6].terminal
    assert not states[7].terminal and states[7].objects == {}


@case("G-R21")
def test_distinct_tokens_of_a_session_at_the_limit_and_one_past_it():
    """RED-12, OPS-22, A.2: distinct (generation, token) pairs over the session, through the seam
    (3). Generation 1 sees o1, o2 and o99 (a reflection for a never-discovered token is a token
    the worker allocated, NAT-11): 3. In generation 2, o1 is a new pair, the fourth: E_LIMIT,
    not admitted; repeating a pair already seen costs nothing."""
    scenario = (Scenario().frame(1, 0, event_generation_start())
                .frame(1, 0, event_discover("o1")).frame(1, 0, event_discover("o2"))
                .frame(1, 0, reflect("o99", (FI, FORCE_1)))
                .frame(1, 0, reflect("o99", (FI, FORCE_1)))
                .frame(1, 0, event_discover("o1"))
                .frame(1, 0, event_generation_end())
                .frame(2, 0, event_generation_start())
                .frame(2, 0, event_discover("o1")))
    out = scenario.reduce(limits=_limits(object_tokens_per_session=3))
    assert briefs(out) == {4: [("diagnostic", "o99", None, "E_UNKNOWN_OBJECT", None)],
                           5: [("diagnostic", "o99", None, "E_UNKNOWN_OBJECT", None)],
                           6: [("diagnostic", "o1", None, "W_DUPLICATE_DISCOVERY", None)],
                           9: [("diagnostic", "o1", None, "E_LIMIT", None)]}
    assert scenario.states[6].distinct_tokens == 3 and scenario.states[9].distinct_tokens == 3
    assert scenario.states[9].objects == {} and scenario.states[9].terminal


@case("G-R21", "G-R22")
def test_supplied_attributes_per_reflection_at_the_limit_and_one_past_it():
    """NAT-06 point 1 as the reducer sees it (count first), through the seam (2): two supplied
    attributes are processed; three are E_LIMIT, terminal, nothing applied, no snapshot. At the
    real limit four are processed, and a fifth cannot even be a frame (the event schema's
    maxItems 4: E_CAPTURE_SCHEMA)."""
    scenario = (started().frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE)))
                .frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE), (SP, SPATIAL_A))))
    out = scenario.reduce(limits=_limits(attributes_per_reflection=2))
    assert briefs(out) == {
        3: [("snapshot", "o1", EID_1, "ACTIVE", ("MISSING_SPATIAL",), (EI, ET), 0)],
        4: [("diagnostic", "o1", EID_1, "E_LIMIT", None)]}
    assert scenario.states[4].objects == scenario.states[3].objects
    assert scenario.states[4].terminal
    four = eligible().reduce()
    assert briefs(four)[3] == ELIGIBLE_AT_3
    state = reducer.initial_state(fixture_capture_records()[0], True)
    frames = eligible().builder.records()
    for frame in frames[1:3]:
        state, _ = reduce_checked(state, frame)
    five = dict(frames[3])
    five["event"] = dict(five["event"], attributes=five["event"]["attributes"]
                         + [{"name": "Zeta", "hex": "00"}])
    error = refused_frame(state, five)
    assert (error.code, error.path) == ("E_CAPTURE_SCHEMA", "line:4#/event/attributes")


@case("G-R21", "G-R25")
def test_cached_bytes_of_a_generation_at_the_limit_and_one_past_it():
    """RED-12, OPS-22: the cache budget counts the raw bytes of the four slots, VALID and INVALID,
    of the generation's unremoved objects, checked before applying. Through the seam at 75 bytes
    (one full object: 6 + 8 + 1 + 60): o1's full state is exactly 75 and is admitted; o2's
    identifier (6 more) is E_LIMIT, not applied, no snapshot, terminal. Replacing o1's Spatial
    by an INVALID 59-byte one frees one byte, so a 1-byte force for o2 fits (75 again); after
    o1's removal its 74 bytes are free and o2's identifier is admitted."""
    scenario = (eligible().frame(1, SECOND, event_discover("o2", "SYNTHETIC-002"))
                .frame(1, SECOND, reflect("o2", (EI, ID_456)))
                .frame(1, SECOND, reflect("o1", (SP, BAD_SPATIAL)))
                .frame(1, SECOND, reflect("o2", (FI, FORCE_1)))
                .frame(1, SECOND, event_remove("o1"))
                .frame(1, SECOND, reflect("o2", (EI, ID_456))))
    out = scenario.reduce(limits=_limits(cached_attribute_bytes_per_generation=75))
    states = scenario.states
    assert states[3].cache_bytes == 75
    assert briefs(out)[5] == [("diagnostic", "o2", None, "E_LIMIT", None)]
    assert states[5].cache_bytes == 75 and states[5].terminal
    assert states[5].objects["o2"] == states[4].objects["o2"]
    assert states[6].cache_bytes == 74 and states[7].cache_bytes == 75
    assert briefs(out)[7] == [("snapshot", "o2", None, "ACTIVE", (
        "MISSING_ENTITY_IDENTIFIER", "MISSING_ENTITY_TYPE", "MISSING_SPATIAL"), (FI,), 0)]
    assert states[8].cache_bytes == 1
    assert briefs(out)[9][0][0] == "snapshot" and states[9].cache_bytes == 7


@case("G-R21", "G-R22")
def test_the_attribute_count_is_judged_before_the_token():
    """NAT-06 point 1 ("count first") and CR-new-R4-04's order (review finding R4-r1-F4, item
    2), through the seam (2 attributes per reflection). Seq 2, a reflection of three attributes
    for the never-discovered o99: E_LIMIT (the token, no attribute), not E_UNKNOWN_OBJECT;
    terminal; and it allocates nothing, so no distinct token is counted. Seq 3, the same token
    with two attributes: now E_UNKNOWN_OBJECT, and o99 counts as one distinct token (NAT-11)."""
    scenario = (Scenario().frame(1, 0, event_generation_start())
                .frame(1, 0, reflect("o99", (EI, ID_123), (ET, TYPE), (FI, FORCE_1)))
                .frame(1, 0, reflect("o99", (EI, ID_123), (ET, TYPE))))
    out = scenario.reduce(limits=_limits(attributes_per_reflection=2))
    assert briefs(out) == {2: [("diagnostic", "o99", None, "E_LIMIT", None)],
                           3: [("diagnostic", "o99", None, "E_UNKNOWN_OBJECT", None)]}
    states = scenario.states
    assert [state.distinct_tokens for state in states] == [0, 0, 0, 1]
    assert [state.terminal for state in states] == [False, False, True, True]
    assert states[3].objects == {}


@case("G-R21", "G-R25")
def test_a_discover_refused_for_a_limit_allocates_no_token():
    """CR-new-R4-04, "a frame refused for a limit allocates nothing" (review finding R4-r1-F4,
    item 3), through the seam: one active object per generation and two distinct tokens per
    session. o1 is admitted (one token); o2 is E_LIMIT for the active objects (the token, no
    attribute) and is not counted (still one); after o1's removal, o3 is admitted as the second
    token, which it could not be had the refused o2 been counted."""
    scenario = (Scenario().frame(1, 0, event_generation_start())
                .frame(1, 0, event_discover("o1")).frame(1, 0, event_discover("o2"))
                .frame(1, 0, event_remove("o1")).frame(1, 0, event_discover("o3")))
    out = scenario.reduce(limits=_limits(active_objects_per_generation=1,
                                         object_tokens_per_session=2))
    assert briefs(out) == {3: [("diagnostic", "o2", None, "E_LIMIT", None)],
                           4: [("removed", "o1", None, "removed", 0)]}
    states = scenario.states
    assert [state.distinct_tokens for state in states] == [0, 0, 1, 1, 1, 2]
    assert states[3].seen == frozenset({"o1"}) and states[3].terminal
    assert set(states[5].objects) == {"o3"} and states[5].seen == frozenset({"o1", "o3"})


@case("G-R21", "G-R22")
def test_unknown_attribute_names_are_not_cached_bytes():
    """OPS-22 (the budget counts the four-entry state maps, "not unknown attributes") and
    CR-new-R4-04 (review finding R4-r1-F4, item 4), through the seam: a cache budget of 8 bytes.
    Seq 3 supplies EntityType (8 bytes) and `Other` (1 byte): E_UNSUBSCRIBED_ATTRIBUTE, not
    E_LIMIT; EntityType is kept INVALID with its 8 bytes, the whole budget, and `Other` enters
    no slot (SPEC:283). Seq 4 replaces it by a valid EntityType of the same 8 bytes: at the
    limit, admitted. Seq 5 adds a 1-byte force: 9 bytes, E_LIMIT, terminal, nothing applied."""
    scenario = (started().frame(1, SECOND, reflect("o1", (ET, TYPE), ("Other", "00")))
                .frame(1, SECOND, reflect("o1", (ET, TYPE)))
                .frame(1, SECOND, reflect("o1", (FI, FORCE_1))))
    out = scenario.reduce(limits=_limits(cached_attribute_bytes_per_generation=8))
    no_identifier_no_spatial = ("MISSING_ENTITY_IDENTIFIER", "MISSING_SPATIAL")
    assert briefs(out) == {
        3: [("diagnostic", "o1", None, "E_UNSUBSCRIBED_ATTRIBUTE", "Other"),
            ("snapshot", "o1", None, "ACTIVE", ("INVALID_ENTITY_TYPE",) + no_identifier_no_spatial,
             (ET,), 0)],
        4: [("snapshot", "o1", None, "ACTIVE", no_identifier_no_spatial, (ET,), 0)],
        5: [("diagnostic", "o1", None, "E_LIMIT", None)],
    }
    states = scenario.states
    assert [state.cache_bytes for state in states] == [0, 0, 0, 8, 8, 8]
    assert [state.terminal for state in states] == [False, False, False, False, False, True]
    assert states[5].objects == states[4].objects
    assert snapshot_of(out[2])["attributes"][ET] == slot("INVALID", None, TYPE, 3, str(SECOND),
                                                          at(SECOND))


@case("G-R21", "G-R25")
@pytest.mark.parametrize("retractable", [False, True], ids=["remove", "retractable-remove"])
def test_a_removal_that_first_names_a_token_counts_it_once_and_meets_the_token_limit(retractable):
    """Review finding R4-r2-F1 (round R5 carry-in). NAT-11: "a reflect or remove for a
    never-seen handle allocates the next token"; CR-new-R4-04: distinct tokens include tokens
    first named by a removal; RED-12: the token beyond the session's limit is E_LIMIT and
    terminal, and a frame refused for a limit allocates nothing. A retractable removal of a
    token that is no object is judged like any unknown removal (CR-new-R4-09).

    Through the seam, two distinct tokens per session. Seq 2 discovers o1 (one token). Seq 3, a
    removal of the never-seen o6: E_UNKNOWN_OBJECT (no entity, no attribute), and o6 is the
    second token. Seq 4, the same removal again: E_UNKNOWN_OBJECT, still two (counted once).
    Seq 5, a removal of the never-seen o7: the third token, so E_LIMIT (o7, no attribute),
    terminal, and o7 is not counted."""
    remove = retractable_remove if retractable else event_remove
    scenario = (Scenario().frame(1, 0, event_generation_start())
                .frame(1, 0, event_discover("o1"))
                .frame(1, 0, remove("o6")).frame(1, 0, remove("o6"))
                .frame(1, 0, remove("o7")))
    out = scenario.reduce(limits=_limits(object_tokens_per_session=2))
    assert briefs(out) == {3: [("diagnostic", "o6", None, "E_UNKNOWN_OBJECT", None)],
                           4: [("diagnostic", "o6", None, "E_UNKNOWN_OBJECT", None)],
                           5: [("diagnostic", "o7", None, "E_LIMIT", None)]}
    states = scenario.states
    assert [state.distinct_tokens for state in states] == [0, 0, 1, 2, 2, 2]
    assert [state.terminal for state in states] == [False, False, False, False, False, True]
    assert states[5].seen == frozenset({"o1", "o6"})
    assert states[5].removed == frozenset() and set(states[5].objects) == {"o1"}


@case("G-R21", "G-R22", "G-R24")
def test_a_retractable_reflection_is_judged_before_the_cache_budget():
    """Review finding R4-r2-F2 (round R5 carry-in). CR-new-R4-04's order: attribute count, token,
    unknown or removed, retractable, empty, cache budget, decode. A retractable reflection is
    never applied (RED-11), so its bytes never meet the budget.

    Through the seam, a cache budget of 8 bytes. Seq 3 supplies EntityType (8 bytes, the whole
    budget). Seq 4, a retractable reflection of a 1-byte force (9 bytes if it were applied):
    E_RETRACTION_UNSUPPORTED (no attribute), the object QUARANTINED and a snapshot listing
    ForceIdentifier as changed while the force slot stays ABSENT; the cached bytes stay 8 and the
    state is not terminal. Seq 5, the same force in an ordinary reflection: E_LIMIT (o1, no
    attribute), terminal, nothing applied, no snapshot."""
    scenario = (started().frame(1, SECOND, reflect("o1", (ET, TYPE)))
                .frame(1, 2 * SECOND, reflect("o1", (FI, FORCE_1), retractable=True))
                .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1))))
    out = scenario.reduce(limits=_limits(cached_attribute_bytes_per_generation=8))
    missing = ("MISSING_ENTITY_IDENTIFIER", "MISSING_SPATIAL")
    assert briefs(out) == {
        3: [("snapshot", "o1", None, "ACTIVE", missing, (ET,), 0)],
        4: [("diagnostic", "o1", None, "E_RETRACTION_UNSUPPORTED", None),
            ("snapshot", "o1", None, "QUARANTINED", missing + ("QUARANTINED",), (FI,), 0)],
        5: [("diagnostic", "o1", None, "E_LIMIT", None)],
    }
    states = scenario.states
    assert [state.cache_bytes for state in states] == [0, 0, 0, 8, 8, 8]
    assert [state.terminal for state in states] == [False, False, False, False, False, True]
    assert states[4].objects["o1"].lifecycle == "QUARANTINED"
    assert states[4].objects["o1"].slots == states[3].objects["o1"].slots
    assert states[5].objects == states[4].objects
    assert snapshot_of(out[3])["attributes"][FI] == ABSENT


# ====================================================================== the gates, clause by clause

@case("G-R21", paragraphs=("SPEC:283",))
def test_the_generation_state_holds_r21s_members():
    """R21: a generation state holds the object-token map, the identity index, the object
    counters (incarnations, distinct tokens), the frame sequence, the byte budget and the
    terminal flag; each object its discovery metadata, per-attribute status, decoded value,
    source hex, seq, elapsed time and effective time, its lifecycle and its identity once
    established (immutable: the object state is frozen). A removed object leaves the map and its
    token joins the removed set (REMOVED). SPEC:283: the snapshot carries exactly these slot
    facts (the snapshot schema, held by `check_record` on every record)."""
    scenario = (eligible().frame(1, SECOND, event_discover("o2", "SYNTHETIC-002"))
                .frame(1, 2 * SECOND, reflect("o2", (EI, ID_456)))
                .frame(1, 2 * SECOND, reflect("o2", (FI, BAD_FORCE)))
                .frame(1, 2 * SECOND, event_discover("o3"))
                .frame(1, 2 * SECOND, event_remove("o3")))
    scenario.reduce()
    state = scenario.states[-1]
    assert (state.generation, state.next_seq, state.terminal, state.distinct_tokens) == (1, 9,
                                                                                       False, 3)
    assert set(state.objects) == {"o1", "o2"} and state.removed == frozenset({"o3"})
    assert state.index == {(1, 2, 3): "o1", (4, 5, 6): "o2"}
    assert state.incarnations == {(1, 2, 3): 1, (4, 5, 6): 1}
    assert state.cache_bytes == (6 + 8 + 1 + 60) + (6 + 2)
    o1, o2 = state.objects["o1"], state.objects["o2"]
    assert (o1.name, o1.reported_class, o1.lifecycle, o1.identity, o1.incarnation,
            o1.entity_id, o1.last_revision, o1.eligible) == (
        "SYNTHETIC-001", PHYSICAL, "ACTIVE", (1, 2, 3), 1, EID_1, 1, True)
    assert o1.slot(SP) == reducer.Slot("VALID", SPATIAL_A_VALUE, SPATIAL_A, 3, str(SECOND),
                                       at(SECOND))
    assert o2.slot(FI) == reducer.Slot("INVALID", None, BAD_FORCE, 6, str(2 * SECOND),
                                       at(2 * SECOND))
    assert o2.slot(SP) == reducer.ABSENT_SLOT
    with pytest.raises(dataclasses.FrozenInstanceError):
        o1.identity = (9, 9, 9)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.objects = {}


@case("G-R32", paragraphs=("SPEC:287",))
@pytest.mark.parametrize("type_hex,name,entity_type", [
    (TYPE, "SYNTHETIC-001", "PLATFORM"),
    ("090100e101020304", "SYNTHETIC-001", "SENSOR"),
    # kind 3 is a lifeform; a name that sounds like a unit infers nothing (R32: no Unit).
    ("030100e101020304", "Infantry Platoon 2 (Unit)", "UNKNOWN"),
    ("0b0100e101020304", "SYNTHETIC-001", "UNKNOWN"),
])
def test_the_upsert_is_r32s_entity(type_hex, name, entity_type):
    """R32 through the reducer: schema_version 3.0.0, object_kind entity, entity_type from
    EntityType.kind alone (1 PLATFORM, 9 SENSOR, else UNKNOWN; the object name infers nothing),
    affiliation from force_map alone, the seven members R32 empties null, ontology_types [],
    valid_to null, and the upsert only for a reflection with a known attribute and an eligible
    result (SPEC:287)."""
    out = (Scenario().frame(1, 0, event_generation_start()).frame(1, 0, event_discover("o1", name))
           .frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, type_hex), (FI, FORCE_1),
                                     (SP, SPATIAL_A)))
           .frame(1, SECOND, reflect("o1", ("Other", "00"))).reduce())
    entity = upsert_of(out[2])
    assert (entity["schema_version"], entity["object_kind"], entity["entity_type"],
            entity["affiliation"]) == ("3.0.0", "entity", entity_type, "FRIENDLY")
    assert all(entity[m] is None for m in ("symbol", "confidence", "quality", "status",
                                           "residual", "integrity", "valid_to"))
    assert entity["ontology_types"] == [] and entity["valid_from"] == "2026-01-01T00:00:01.000Z"
    assert [r["kind"] for r in out[3]] == ["diagnostic", "snapshot"]


def _header_with_epoch(epoch: str) -> dict:
    return header_with(time_policy={"mode": "external_elapsed", "epoch": epoch, "basis": "b"})


@case("G-R32", paragraphs=("SPEC:289",))
def test_an_effective_time_past_year_9998_is_refused_with_e_config():
    """SPEC:289: an externally assigned effective time never exceeds 9998-12-31T23:59:59.999999Z;
    a frame that would pass it is refused before anything is applied, with E_CONFIG at the
    epoch (RED-V-01's path form, CR-L01). With the epoch one second before the end of 9998,
    elapsed 999 999 999 ns lands on the last microsecond and is accepted (valid_from cut to
    .999); 1 000 000 000 ns is refused, and the state is unchanged."""
    header = _header_with_epoch("9998-12-31T23:59:59.000000Z")
    edge = started(header).frame(1, 999_999_999, reflect("o1", *FULL))
    out = edge.reduce()
    assert upsert_of(out[2])["valid_from"] == "9998-12-31T23:59:59.999Z"
    assert snapshot_of(out[2])["attributes"][SP]["effective_at"] == "9998-12-31T23:59:59.999999Z"
    past = started(header).frame(1, 1_000_000_000, reflect("o1", *FULL))
    records = past.builder.records()
    state = reducer.initial_state(records[0], True)
    for frame in records[1:3]:
        state, _ = reduce_checked(state, frame)
    error = refused_frame(state, records[3])
    assert (error.code, error.path) == ("E_CONFIG", "line:1#/config/time_policy/epoch")


@case("G-R09", "G-R11", paragraphs=("SPEC:289",))
@pytest.mark.parametrize("members,path", [
    ({"force_map": {"256": "HOSTILE"}}, "line:1#/config/force_map/256"),
    ({"force_map": {"01": "HOSTILE"}}, "line:1#/config/force_map/01"),
    ({"force_map": {"1": "ALLY"}}, "line:1#/config/force_map/1"),
    ({"profile_declaration": "external-fom-unverified"}, "line:1#/config/profile_declaration"),
    ({"mode": "existing"}, "line:1#/config/profile_declaration"),
], ids=["force-key-256", "force-key-01", "force-value", "demo-declared-unverified",
        "existing-declared-bundled"])
def test_the_header_configuration_is_validated_semantically(members, path):
    """SPEC:289 for R09 and R11: force-map keys are canonical decimals up to 255 with one of the
    four values, and the declaration agrees with the mode; a header that breaks either is
    refused before any frame, E_CONFIG (or E_CAPTURE_SCHEMA for a schema fault, CR-R2-10) at
    `line:1#/config/...` (RED-V-01). The configuration comes only from the header: reduce_frame
    takes a state and a frame and nothing else (R09: no runtime change of configuration)."""
    with pytest.raises(HlaError) as info:
        reducer.initial_state(header_with(**members), True)
    assert info.value.path == path
    assert info.value.code in ("E_CONFIG", "E_CAPTURE_SCHEMA")
    assert list(__import__("inspect").signature(reducer.reduce_frame).parameters) == [
        "state", "frame"]


@case("G-R09")
def test_affiliation_follows_only_the_recorded_force_map():
    """R09: the affiliation is the header's force_map value for the decimal of the force, and
    nothing else: the RPR enumeration (1 is Friendly there), the country code, the name and the
    class infer nothing. The same frames under three recorded maps give three affiliations."""
    def affiliation(force_map, name="SYNTHETIC-001", country_type=TYPE):
        out = (Scenario(header_with(force_map=force_map)).frame(1, 0, event_generation_start())
               .frame(1, 0, event_discover("o1", name))
               .frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, country_type), (FI, FORCE_1),
                                         (SP, SPATIAL_A))).reduce())
        return upsert_of(out[2])["affiliation"]
    assert affiliation({"1": "HOSTILE"}) == "HOSTILE"
    assert affiliation({"1": "NEUTRAL"}) == "NEUTRAL"
    assert affiliation({}) == "UNKNOWN"
    assert affiliation({}, name="FRIENDLY BLUFOR") == "UNKNOWN"
    assert affiliation({}, country_type="010100e201020304") == "UNKNOWN"


@case("G-R20")
def test_the_captured_hex_is_kept_beside_the_decoded_value():
    """R20's carried clause: the source attribute hex is preserved separately for exact replay.
    SPATIAL-PADDING (bytes 1-7 0xa5, 33-35 0x5a) reaches the snapshot as the captured hex byte
    for byte beside its decoded value, the padding preserved in padding_hex in wire order and
    never interpreted, and its hash in the Entity is the hash of those raw bytes."""
    padded = HEX["SPATIAL-PADDING"]
    out = started().frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE), (SP, padded))
                          ).reduce()
    spatial = snapshot_of(out[2])["attributes"][SP]
    assert spatial["hex"] == padded
    assert spatial["value"]["padding_hex"] == "a5a5a5a5a5a5a55a5a5a"
    hla = upsert_of(out[2])["attributes"]["hla"]
    assert hla["spatial"]["padding_hex"] == "a5a5a5a5a5a5a55a5a5a"
    assert hla["attribute_hashes"][SP] == hashlib.sha256(bytes.fromhex(padded)).hexdigest()


@case("G-R33", paragraphs=("SPEC:158",))
def test_live_records_equal_replay_records_but_for_the_completion_fields():
    """SPEC:158: the same frames reduced live (capture_complete null), as a complete replay
    (true) and as a prefix replay (false) give records that differ only in the envelope's
    capture_complete and the upsert's attributes.hla.capture_complete, which carry exactly that
    value; and two complete runs are identical."""
    def run(flag):
        scenario = (eligible().frame(1, SECOND, event_discover("o2", "SYNTHETIC-002"))
                    .frame(1, 2 * SECOND, reflect("o2", (EI, ID_123), (ET, TYPE), (SP, SPATIAL_B)))
                    .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_255)))
                    .frame(1, 3 * SECOND, event_generation_end()))
        return [r for records in scenario.reduce(capture_complete=flag) for r in records]
    live, complete, prefix = run(None), run(True), run(False)
    assert complete == run(True)
    assert [without_completion(r) for r in live] == [without_completion(r) for r in complete] \
        == [without_completion(r) for r in prefix]
    for records, flag in ((live, None), (complete, True), (prefix, False)):
        assert {r["capture_complete"] for r in records} == {flag}
        assert [r["payload"]["attributes"]["hla"]["capture_complete"] for r in records
                if r["kind"] == "upsert"] == [flag]
    assert len(live) > 6


@case("A-OUTPUT-IDEMPOTENCE", "G-R33", paragraphs=("SPEC:158",))
def test_a_record_delivered_twice_is_applied_once():
    """A-OUTPUT-IDEMPOTENCE with RED-14's reference consumer (tests only): every record of a
    session carries a distinct (session_id, seq, ordinal), and delivering each record twice, or
    the whole stream again, leaves the consumer exactly where one delivery left it."""
    scenario = (eligible().frame(1, 2 * SECOND, reflect("o1", (FI, BAD_FORCE)))
                .frame(1, 3 * SECOND, reflect("o1", (FI, FORCE_1)))
                .frame(1, 4 * SECOND, event_remove("o1")))
    records = [r for records in scenario.reduce() for r in records]
    keys = [(r["session_id"], r["seq"], r["ordinal"]) for r in records]
    assert len(keys) == len(set(keys))
    once, twice = ReferenceConsumer(), ReferenceConsumer()
    for record in records:
        assert once.deliver(record) is True
    for record in records:
        assert twice.deliver(record) is True
        assert twice.deliver(copy.deepcopy(record)) is False
    assert [twice.deliver(r) for r in records] == [False] * len(records)
    assert once.entities == twice.entities
    assert once.entities[EID_1]["state"] == "removed" and once.entities[EID_1]["revision"] == 2


@case("G-R33", paragraphs=("SPEC:287",))
def test_decoded_numbers_live_in_the_output_and_never_in_a_frame():
    """R33: decoded numbers are stored only in output, never in the capture's digest preimages:
    a frame carrying a float (anywhere: here generation 1.0) is not a capture frame and is
    refused (E_CAPTURE_SCHEMA at its pointer), while the output carries the decoded floats."""
    records = eligible().builder.records()
    state = reducer.initial_state(records[0], True)
    state, _ = reduce_checked(state, records[1])
    error = refused_frame(state, dict(records[2], generation=1.0))
    assert (error.code, error.path) == ("E_CAPTURE_SCHEMA", "line:3#/generation")
    out = eligible().reduce()
    assert snapshot_of(out[2])["attributes"][SP]["value"]["position_ecef_m"] == [6378137.0, 0.0,
                                                                                  0.0]


@case("G-R33")
def test_the_output_path_holds_no_delivery_database_or_broker():
    """R33: the output stream contains no HTTP delivery, database implementation or message
    broker. The reducer and replay import nothing of the kind (and no module of the package
    imports a socket, test_hla_purity.py); they hand back records and write files."""
    import ast
    import pathlib
    banned = {"http", "urllib", "socket", "ssl", "sqlite3", "dbm", "shelve", "smtplib",
              "xmlrpc", "asyncio", "requests", "aiohttp", "kafka", "pika", "zmq", "redis"}
    for module in (reducer, sys.modules["synapse_hla.replay"]):
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        roots = {alias.name.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.Import) for alias in node.names}
        roots |= {node.module.split(".")[0] for node in ast.walk(tree)
                  if isinstance(node, ast.ImportFrom) and node.module}
        assert not roots & banned, (module.__name__, sorted(roots & banned))


@case("G-R33")
def test_decoded_values_reach_the_output_exactly_and_only_position_is_normalised():
    """Decoded numbers go to the output exactly as decoded (RED-15: the binary32 values as their
    exact doubles; RED-18: -0.0 kept in the snapshot's value and in attributes.hla.spatial),
    and only the projected position and motion are normalised to +0.0 (R18)."""
    value = encode_spatial(2, position=(6378137.0, -0.0, 0.0), orientation=(0.1, -0.0, 0.0),
                           velocity=(-0.0, 10.0, 0.0))
    out = started().frame(1, SECOND, reflect("o1", (EI, ID_123), (ET, TYPE),
                                             (SP, value.hex()))).reduce()
    decoded = snapshot_of(out[2])["attributes"][SP]["value"]
    assert repr(decoded["position_ecef_m"]) == "[6378137.0, -0.0, 0.0]"
    assert repr(decoded["orientation_rad"]) == "[0.10000000149011612, -0.0, 0.0]"
    assert repr(decoded["velocity_mps"]) == "[-0.0, 10.0, 0.0]"
    line = reducer.output_line(out[2][0])
    assert b'"position_ecef_m":[6378137.0,-0.0,0.0]' in line
    entity = upsert_of(out[2])
    assert repr(entity["attributes"]["hla"]["spatial"]["position_ecef_m"]) == \
        "[6378137.0, -0.0, 0.0]"
    assert repr((entity["position"]["lat"], entity["position"]["lon"])) == "(0.0, 0.0)"


def test_the_order_of_diagnostics_in_a_frame_is_red_03s():
    """RED-03's sort key, on hand-made entries: code first, then the attribute with null first,
    then the token by its number with null first (o2 before o10). No frame of the reducer can
    produce one code with both a null and a named attribute, so the key is held here directly."""
    entries = [("E_X", "b", "o10", ""), ("E_X", "b", "o2", ""), ("E_X", None, "o3", ""),
               ("E_A", "z", None, ""), ("E_X", "b", None, ""), ("E_X", "a", "o1", ""),
               ("W_A", None, None, "")]
    ordered = sorted(entries, key=reducer._diagnostic_key)
    assert [(code, attribute, token) for code, attribute, token, _ in ordered] == [
        ("E_A", "z", None), ("E_X", None, "o3"), ("E_X", "a", "o1"), ("E_X", "b", None),
        ("E_X", "b", "o2"), ("E_X", "b", "o10"), ("W_A", None, None)]


@case("G-R33")
def test_a_captured_diagnostic_names_the_entity_its_token_holds_after_the_frame():
    """CR-new-R4-13 (review finding R4-r1-F3) with RED-01 and RED-03 as corrected: a captured
    diagnostic becomes one diagnostic record at its seq, as it stands, and its envelope
    entity_id is the one its token holds after the frame, as for a derived diagnostic: null for
    a token without an allocated identity, for an unknown or removed token and for no token.

    o1 is eligible (seq 3) and o2 discovered without an identity (seq 4). Captured
    E_QUEUE_OVERFLOW frames for o1 (seq 5), o2 (seq 6), the never-discovered o9 (seq 7) and no
    token (seq 8) give the envelope entity_ids 781e68de-... (o1's), null, null and null. After
    o1's removal (seq 9) the same frame for o1 (seq 10) gives null. The frames change no object,
    and a token on a captured diagnostic is not an object token of the generation
    (CR-new-R4-04): o9 is not counted."""
    overflow = "the callback queue overflowed"
    scenario = (eligible().frame(1, SECOND, event_discover("o2", "SYNTHETIC-002"))
                .frame(1, 2 * SECOND, event_diagnostic("E_QUEUE_OVERFLOW", overflow, token="o1"))
                .frame(1, 2 * SECOND, event_diagnostic("E_QUEUE_OVERFLOW", overflow, token="o2"))
                .frame(1, 2 * SECOND, event_diagnostic("E_QUEUE_OVERFLOW", overflow, token="o9"))
                .frame(1, 2 * SECOND, event_diagnostic("E_QUEUE_OVERFLOW", overflow))
                .frame(1, 3 * SECOND, event_remove("o1"))
                .frame(1, 3 * SECOND, event_diagnostic("E_QUEUE_OVERFLOW", overflow, token="o1")))
    out = scenario.reduce()
    assert briefs(out) == {
        3: ELIGIBLE_AT_3,
        5: [("diagnostic", "o1", "781e68de-166f-531c-b906-4a2d087f817e", "E_QUEUE_OVERFLOW",
             None)],
        6: [("diagnostic", "o2", None, "E_QUEUE_OVERFLOW", None)],
        7: [("diagnostic", "o9", None, "E_QUEUE_OVERFLOW", None)],
        8: [("diagnostic", None, None, "E_QUEUE_OVERFLOW", None)],
        9: [("removed", "o1", EID_1, "removed", 1)],
        10: [("diagnostic", "o1", None, "E_QUEUE_OVERFLOW", None)],
    }
    assert out[4][0]["payload"] == {"severity": "ERROR", "code": "E_QUEUE_OVERFLOW",
                                    "message": overflow, "seq": 5, "generation": 1,
                                    "object_token": "o1", "attribute": None}
    states = scenario.states
    for k in (5, 6, 7, 8):
        assert states[k].objects == states[4].objects, k
    assert states[8].seen == frozenset({"o1", "o2"}) and states[8].distinct_tokens == 2


# ============================================================================ the frame refusals

@case("G-R22")
def test_reduce_frame_admits_what_a_capture_holds_at_its_position():
    """reduce_frame judges a frame by the capture's rules at the state's position and refuses it
    with verification's code and `line:<n>` path: a seq that skips (E_CAPTURE_SEQUENCE), a
    broken digest or link (E_CAPTURE_HASH), a frame of another generation or before the first
    generation_start (E_CAPTURE_SCHEMA), unsorted attribute names (RED-04), a diagnostic code
    outside the catalogue; and a refused frame leaves the state as it was."""
    records = eligible().builder.records()
    state = reducer.initial_state(records[0], True)
    first = records[1]
    rows = [
        (dict(first, seq=2), "E_CAPTURE_SEQUENCE", "line:2#/seq"),
        (dict(first, sha256="0" * 64), "E_CAPTURE_HASH", "line:2#/sha256"),
        (dict(first, prev_sha256="0" * 64), "E_CAPTURE_HASH", "line:2#/prev_sha256"),
        (records[2], "E_CAPTURE_SEQUENCE", "line:2#/seq"),
    ]
    for frame, code, path in rows:
        error = refused_frame(state, frame)
        assert (error.code, error.path) == (code, path)
    started_state, _ = reduce_checked(state, first)
    crafted = Scenario().frame(1, 0, event_generation_start()).frame(
        2, 0, event_discover("o1")).builder.records()
    error = refused_frame(started_state, crafted[2])
    assert (error.code, error.path) == ("E_CAPTURE_SCHEMA", "line:3#/generation")
    unsorted = Scenario().frame(1, 0, event_generation_start()).frame(1, 0, event_discover()).frame(
        1, 0, reflect("o1", (SP, SPATIAL_A), (EI, ID_123))).builder.records()
    state2 = reducer.initial_state(unsorted[0], True)
    for frame in unsorted[1:3]:
        state2, _ = reduce_checked(state2, frame)
    error = refused_frame(state2, unsorted[3])
    assert (error.code, error.path) == ("E_CAPTURE_SCHEMA", "line:4#/event/attributes/1/name")
    odd = Scenario().frame(0, 0, event_diagnostic("E_SOMETHING_NEW")).builder.records()
    error = refused_frame(reducer.initial_state(odd[0], True), odd[1])
    assert (error.code, error.path) == ("E_CAPTURE_SCHEMA", "line:2#/event/diagnostic/code")


def test_only_a_state_built_by_the_reducer_is_a_state():
    """A caller bug, TypeError: a state initial_state and reduce_frame did not build, a non-JSON
    frame, a completion flag that is not True, False or None, a limits object that is not a
    `Limits`."""
    header = fixture_capture_records()[0]
    frame = fixture_capture_records()[1]
    state = reducer.initial_state(header, True)
    for bad in (None, {}, dataclasses.asdict(V1), "state", [state]):
        refused_frame(bad, frame, TypeError)
    for bad_frame in (dict(frame, event=("x",)), dict(frame, tag=b"x"), {1: "x"}):
        refused_frame(state, bad_frame, TypeError)
    for flag in (1, 0, "true", 1.0):
        with pytest.raises(TypeError):
            reducer.initial_state(header, flag)
    for limits in (None, {}, dataclasses.asdict(V1)):
        with pytest.raises(TypeError):
            reducer.initial_state(header, True, limits=limits)


class _Str(str):
    pass


class _Int(int):
    pass


def _hostile_values():
    """Values a caller might hand over where a frame member belongs (CR-R2-24): beyond 2^53,
    floats (integral and not), non-finite numbers, bools, lone surrogates, bidirectional and
    control characters, very long text, deep nesting, non-JSON types and subclasses."""
    deep = []
    for _ in range(40):
        deep = [deep]
    return [2 ** 53, -(2 ** 53), 10 ** 30, 1.5, 5.0, -0.0, math.nan, math.inf, True, False, None,
            "", "\ud800", "a\udfff", "\N{RIGHT-TO-LEFT OVERRIDE}" + "o1", "\x00\x1b[2J",
            "x" * 70_000, [], {}, deep,
            {"\ud800": 1}, {"": None}, (1, 2), b"bytes", {1, 2}, _Str("o1"), _Int(3),
            "o0", "o" + "9" * 20, "E_SOMETHING_NEW", 0, -1, "RECEIVE ", "0" * 64, "1" * 65]


def _put(value, path, item):
    node = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = item


def _leaf_paths(value, path=()):
    if type(value) is dict:
        for key, item in value.items():
            yield path + (key,)
            yield from _leaf_paths(item, path + (key,))
    elif type(value) is list:
        for index, item in enumerate(value):
            yield path + (index,)
            yield from _leaf_paths(item, path + (index,))


def _resealed(frame):
    """The frame with its digest recomputed by the tests' own canonical writer when it can be
    written at all, so that a hostile value reaches the checks after the hash."""
    from hla_support import record_digest
    try:
        return dict(frame, sha256=record_digest(frame))
    except (TypeError, ValueError):
        return frame


@case("G-R22")
@pytest.mark.parametrize("seed", [4, 44, 444])
def test_hostile_frames_give_a_catalogue_refusal_or_a_type_error_and_nothing_else(seed):
    """CR-R2-24 next to every refusal path reduce_frame and initial_state add: a seeded fuzz puts
    a hostile value at a random place of a valid frame (digest left as it was, or recomputed so
    the value reaches the rules behind the hash) and of the header. The only outcomes are
    success, `HlaError` with an E_ catalogue code, or `TypeError` for a Python value that is not
    JSON; the state handed in is never changed."""
    rng = random.Random(seed)
    scenario = (eligible().frame(1, 2 * SECOND, reflect("o1", (FI, FORCE_1), ("Other", "00")))
                .frame(1, 2 * SECOND, event_remove("o1"))
                .frame(1, 2 * SECOND, event_diagnostic("E_IO", token="o1", attribute="x"))
                .frame(1, 3 * SECOND, event_generation_end()))
    scenario.reduce()
    chained = scenario.chained
    outcomes = set()
    from hla_support import CATALOGUE
    for _ in range(400):
        position = rng.randrange(1, len(chained))
        target = copy.deepcopy(chained[0] if position == len(chained) - 1 and rng.random() < 0.3
                               else chained[position])
        is_header = target["type"] == "header"
        paths = list(_leaf_paths(target))
        _put(target, rng.choice(paths), rng.choice(_hostile_values()))
        if not is_header and rng.random() < 0.5:
            target = _resealed(target)
        try:
            if is_header:
                reducer.initial_state(target, True)
            else:
                state = scenario.states[position - 1]
                state_copy, target_copy = copy.deepcopy(state), copy.deepcopy(target)
                try:
                    reducer.reduce_frame(state, target)
                finally:
                    assert state == state_copy
                    assert repr(target) == repr(target_copy)
            outcomes.add("ok")
        except HlaError as error:
            assert error.code in CATALOGUE and error.code.startswith("E_"), error.code
            assert error.path.startswith("line:"), error.path
            outcomes.add(error.code)
        except TypeError:
            outcomes.add("TypeError")
    assert {"E_CAPTURE_SCHEMA", "E_CAPTURE_HASH", "TypeError"} <= outcomes, outcomes


# =========================================================================== the state machine fuzz

#: Values a fuzzed reflection draws from: mostly valid, some that fail to decode, some that
#: suppress (0.0.0, the Earth's centre), and two unknown names.
_POOL = {
    EI: [ID_123, ID_456, ID_789, ID_ABC, ID_NULL, BAD["LENGTH-EntityIdentifier"]],
    ET: [TYPE, TYPE, "090100e101020304", BAD["LENGTH-EntityType"]],
    FI: [FORCE_1, FORCE_1, FORCE_255, "02", BAD_FORCE],
    SP: [SPATIAL_A, SPATIAL_B, SPATIAL_A, SPATIAL_CENTRE, HEX["SPATIAL-7"],
         HEX["SPATIAL-PADDING"], BAD_SPATIAL, BAD["ALG-0"], BAD["NONFINITE-36"]],
    "Alpha": ["00"], "Other": ["0102"],
}
#: The rest of a complete state, so that the seeds also reach eligibility, upserts and
#: transitions, and the suppressions that only a complete state reports (RED-02).
_SPATIAL_OF_A_COMPLETE_STATE = (SPATIAL_A, SPATIAL_A, SPATIAL_B, SPATIAL_CENTRE)
_TOKENS = ("o1", "o2", "o3", "o10")
#: Object names: repeated ones (for rediscovery), the empty name, control and bidirectional
#: characters, and a name of exactly 1024 UTF-8 bytes; names are data (R40).
_NAMES = ("A", "A", "B", "", "\x1b[0m\N{RIGHT-TO-LEFT OVERRIDE}",
          "\N{LATIN SMALL LETTER E WITH ACUTE}" * 512)
_HEADERS = (None, dict(force_map={}), dict(**example_json("config-existing.json")),
            dict(mode="existing", profile_declaration="external-fom-unverified"))


def _fuzz_scenario(seed: int) -> Scenario:
    """A random session that verification accepts: legal and odd frames over four tokens
    (unknown and removed tokens, rediscoveries, decode failures, unknown attributes, empty and
    retractable callbacks, captured diagnostics, reconnects), elapsed never decreasing."""
    rng = random.Random(seed)
    members = _HEADERS[seed % len(_HEADERS)]
    scenario = Scenario(None if members is None else header_with(**members))
    elapsed, generation, open_ = 0, 0, False
    if rng.random() < 0.5:
        scenario.frame(0, 0, event_diagnostic("E_RTI_CONNECT"))
    for _ in range(rng.randrange(60, 110)):
        if not open_:
            if rng.random() < 0.2:
                scenario.frame(0, elapsed, event_diagnostic(rng.choice(("E_RTI_CONNECT", "E_IO"))))
            generation += 1
            open_ = True
            scenario.frame(generation, elapsed, event_generation_start())
            continue
        elapsed += rng.choice((0, 1, 250_000_000, SECOND, 1_000_000_007))
        token = rng.choice(_TOKENS)
        roll = rng.random()
        if roll < 0.18:
            event = event_discover(token, rng.choice(_NAMES),
                                   rng.choice((PHYSICAL, PHYSICAL, PHYSICAL + ".Platform", "")))
        elif roll < 0.42:
            identifier = rng.choice((ID_123, ID_456, ID_789, ID_ABC, ID_NULL))
            event = reflect(token, (EI, identifier), (ET, TYPE), (FI, FORCE_1),
                            (SP, rng.choice(_SPATIAL_OF_A_COMPLETE_STATE)))
        elif roll < 0.75:
            names = sorted(rng.sample(sorted(_POOL), rng.randrange(0, 5)))
            event = reflect(token, *((n, rng.choice(_POOL[n])) for n in names),
                            retractable=rng.random() < 0.06)
        elif roll < 0.85:
            event = event_remove(token) if rng.random() < 0.85 else retractable_remove(token)
        elif roll < 0.92:
            event = event_diagnostic(rng.choice(("E_QUEUE_OVERFLOW", "E_RTI_TIMEOUT", "E_LIMIT")),
                                     token=rng.choice((None, token)))
        else:
            event = event_generation_end(rng.choice(("stop", "connection_lost")))
            open_ = False
            scenario.frame(generation, elapsed, event)
            continue
        scenario.frame(generation, elapsed, event)
    if open_:
        scenario.frame(generation, elapsed, event_generation_end())
    return scenario.footer()


@case("G-R21", "G-R22", "G-R24", "G-R25", "G-R33")
@pytest.mark.parametrize("seed", range(12))
def test_a_deterministic_state_machine_fuzz(seed, tmp_path):
    """Random legal and odd frame sequences (fixed seeds), every record held to the contract by
    `reduce_checked` and the stream by `check_stream` (revisions per entity_id run 1, 2, 3;
    an entity_id stays with one token in a generation). Further invariants: at most one snapshot
    and one upsert per frame (in the checker); no snapshot or upsert for a token that was not a
    discovered, unremoved object before the frame; an upsert only for an ACTIVE, eligible
    object (in the checker); an identity never changes once set and a quarantine never ends
    while the object lives; nothing survives a generation_end; identical input gives identical
    output and state; the replay of the same capture writes exactly these records."""
    scenario = _fuzz_scenario(seed)
    out = scenario.reduce()
    states = scenario.states
    frames = [r for r in scenario.chained[1:] if r["type"] == "frame"]
    for k, (frame, records) in enumerate(zip(frames, out), start=1):
        before, after = states[k - 1], states[k]
        for record in records:
            if record["kind"] in ("snapshot", "upsert"):
                assert record["object_token"] in before.objects, (seed, k)
        for token, obj in after.objects.items():
            old = before.objects.get(token)
            if old is not None and old.identity is not None:
                assert obj.identity == old.identity and obj.entity_id == old.entity_id
            if old is not None and old.lifecycle == "QUARANTINED":
                assert obj.lifecycle == "QUARANTINED"
        if frame["event"]["type"] == "generation_end":
            assert (after.generation, after.objects, after.index, after.incarnations,
                    after.removed, after.seen, after.cache_bytes, after.terminal) == (
                None, {}, {}, {}, frozenset(), frozenset(), 0, False)
    again = _fuzz_scenario(seed)
    assert again.reduce() == out and again.states[-1] == states[-1]
    path = scenario.write(tmp_path / "fuzz.jsonl")
    synapse_hla.replay(path, tmp_path / "run")
    written = (tmp_path / "run" / "observations.jsonl").read_bytes()
    assert written == b"".join(reducer.output_line(r) for records in out for r in records)
    kinds = {r["kind"] for records in out for r in records}
    assert {"diagnostic", "snapshot"} <= kinds


def test_the_fuzz_reaches_every_kind_and_the_interesting_codes():
    """The fuzz above is only worth its seeds if they reach the paths: across them every record
    kind and the main reducer codes occur."""
    kinds, codes = set(), set()
    for seed in range(12):
        for records in _fuzz_scenario(seed).reduce():
            for record in records:
                kinds.add(record["kind"])
                if record["kind"] == "diagnostic":
                    codes.add(record["payload"]["code"])
    assert kinds == {"diagnostic", "snapshot", "upsert", "removed", "invalidated"}
    assert {"E_UNKNOWN_OBJECT", "E_IDENTITY_COLLISION", "E_IDENTITY_CHANGED", "E_NULL_ID",
            "E_ATTRIBUTE_LENGTH", "E_UNSUBSCRIBED_ATTRIBUTE", "W_DUPLICATE_REMOVE",
            "W_DUPLICATE_DISCOVERY", "E_CAPTURE_SCHEMA", "E_RETRACTION_UNSUPPORTED",
            "E_ECEF_RANGE"} <= codes, sorted(codes)


# ========================================================================== the product's own check

def _valid_frame_records():
    scenario = eligible()
    out = scenario.reduce()
    return scenario.chained[3], out[2]


BREACHES = [
    ("upsert before snapshot", lambda f, r: [dict(r[1], ordinal=0), dict(r[0], ordinal=1)]),
    ("revision on a snapshot", lambda f, r: [dict(r[0], revision=1), r[1]]),
    ("upsert without revision", lambda f, r: [r[0], dict(r[1], revision=None)]),
    ("upsert of another entity", lambda f, r: [r[0], dict(r[1], entity_id=EID_INC2)]),
    ("an ordinal skipped", lambda f, r: [r[0], dict(r[1], ordinal=2)]),
    ("another seq", lambda f, r: [dict(r[0], seq=4), r[1]]),
    ("another generation", lambda f, r: [dict(r[0], generation=2), r[1]]),
    ("a member short", lambda f, r: [{k: v for k, v in r[0].items() if k != "revision"}, r[1]]),
    ("two snapshots", lambda f, r: [r[0], dict(r[0], ordinal=1)]),
    ("unsorted reasons", lambda f, r: [dict(r[0], payload=dict(
        r[0]["payload"], projection_status="SUPPRESSED",
        suppression_reasons=["MISSING_SPATIAL", "MISSING_ENTITY_TYPE"])), r[1]]),
    ("a reason outside the vocabulary", lambda f, r: [dict(r[0], payload=dict(
        r[0]["payload"], projection_status="SUPPRESSED", suppression_reasons=["STALE"])), r[1]]),
    ("eligible with a reason", lambda f, r: [dict(r[0], payload=dict(
        r[0]["payload"], suppression_reasons=["QUARANTINED"])), r[1]]),
    ("changed attributes repeated", lambda f, r: [dict(r[0], payload=dict(
        r[0]["payload"], changed_attributes=[EI, EI])), r[1]]),
    ("a removed record on a reflect", lambda f, r: [
        dict(r[0], kind="removed", payload={"reason": "removed", "last_revision": 0})]),
    ("an invalidated record with reason removed", lambda f, r: [
        dict(r[0], kind="invalidated", payload={"reason": "removed", "last_revision": 0})]),
    ("a generation_end invalidation off generation_end", lambda f, r: [
        dict(r[0], kind="invalidated", payload={"reason": "generation_end", "last_revision": 0})]),
    ("a diagnostic with the wrong severity", lambda f, r: [dict(
        r[0], kind="diagnostic", payload={"severity": "WARNING", "code": "E_IO", "message": "m",
                                          "seq": 3, "generation": 1, "object_token": "o1",
                                          "attribute": None})]),
    ("a diagnostic outside the catalogue", lambda f, r: [dict(
        r[0], kind="diagnostic", payload={"severity": "ERROR", "code": "E_NEW", "message": "m",
                                          "seq": 3, "generation": 1, "object_token": "o1",
                                          "attribute": None})]),
    ("a kind outside the five", lambda f, r: [dict(r[0], kind="entity")]),
    # Review finding R4-r2-F4 (round R5 carry-in): the two checks no row reached before.
    ("an upsert without a snapshot", lambda f, r: [dict(r[1], ordinal=0)]),
    ("an upsert after another object's snapshot", lambda f, r: [
        dict(r[0], object_token="o2"), r[1]]),
    ("a diagnostic whose payload names another token", lambda f, r: [dict(
        r[0], kind="diagnostic", payload={"severity": "ERROR", "code": "E_IO", "message": "m",
                                          "seq": 3, "generation": 1, "object_token": "o2",
                                          "attribute": None})]),
]


@case("G-R33")
@pytest.mark.parametrize("what,breach", BREACHES, ids=[b[0] for b in BREACHES])
def test_the_reducer_holds_its_own_records_to_red_16_and_r33(what, breach):
    """RED-16: the product asserts what the schemas let through. `check_records` accepts the
    records the reducer made for a frame and refuses each breach with `ReducerDefect`, a defect
    of the module and never an `HlaError`."""
    frame, records = _valid_frame_records()
    reducer.check_records(frame, records)
    with pytest.raises(reducer.ReducerDefect):
        reducer.check_records(frame, breach(frame, copy.deepcopy(records)))
    end = Scenario().frame(1, 0, event_generation_start()).frame(
        1, 0, event_generation_end()).builder.records()[2]
    with pytest.raises(reducer.ReducerDefect):
        reducer.check_records(end, [dict(records[0], seq=2, ordinal=0)])


def test_a_defect_in_the_records_escapes_as_a_defect(monkeypatch):
    """A reducer that built its records out of order would be stopped by its own check: the
    defect propagates out of reduce_frame (it is never an HlaError, never swallowed)."""
    original = reducer._Step.result

    def swapped(self):
        if self.upsert is not None and self.snapshot is not None:
            self.snapshot, self.upsert = None, None
            self.removals.append(("o1", None, 0))
        return original(self)
    monkeypatch.setattr(reducer._Step, "result", swapped)
    records = eligible().builder.records()
    state = reducer.initial_state(records[0], True)
    for frame in records[1:3]:
        state, _ = reduce_checked(state, frame)
    refused_frame(state, records[3], reducer.ReducerDefect)


def test_reduction_opens_nothing_once_warm():
    """D-08: the reducer reads no file, clock, process or socket. Once the packaged schemas are
    loaded, reducing a whole session raises no audit event of the file, OS, socket, process or
    time families, in a fresh interpreter with an audit hook installed."""
    script = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(__import__('hla_support').PACKAGE_ROOT / 'src')!r})\n"
        "from synapse_hla import reducer\n"
        f"capture = {str(__import__('hla_support').PACKAGE_ROOT / 'src/synapse_hla/fixtures')!r}"
        " + '/session.capture.jsonl'\n"
        "records = [json.loads(line) for line in open(capture, 'rb').read().splitlines()]\n"
        "def run():\n"
        "    state = reducer.initial_state(records[0], True)\n"
        "    for frame in records[1:-1]:\n"
        "        state, out = reducer.reduce_frame(state, frame)\n"
        "        [reducer.output_line(r) for r in out]\n"
        "run()\n"
        "events = []\n"
        "sys.addaudithook(lambda event, args: events.append(event))\n"
        "run()\n"
        "print(json.dumps(sorted(set(events))))\n")
    proc = run_python(["-c", script], cwd=__import__("hla_support").PACKAGE_ROOT)
    assert proc.returncode == 0, proc.stderr[-2000:]
    events = json.loads(proc.stdout.strip().splitlines()[-1])
    forbidden = ("open", "os.", "socket.", "subprocess.", "shutil.", "glob.", "ctypes.",
                 "urllib.", "http.", "time.", "fcntl.", "mmap.", "pty.", "sqlite3.")
    assert not [e for e in events if e == "open" or e.startswith(forbidden)], events


def test_check_stream_and_check_frame_records_are_not_vacuous():
    """The test-side contract checker refuses what it is there to refuse: a snapshot whose
    revision does not follow, an upsert revision that skips, an entity_id on two tokens."""
    out = eligible().frame(1, 2 * SECOND, reflect("o1", (FI, FORCE_1))).reduce()
    check_stream(out)
    skipped = copy.deepcopy(out)
    skipped[3][1]["revision"] = 3
    with pytest.raises(AssertionError):
        check_stream(skipped)
    moved = copy.deepcopy(out)
    for record in moved[3]:
        record["object_token"] = "o2"
    with pytest.raises(AssertionError):
        check_stream(moved)
    frame = eligible().builder.records()[3]
    swapped = [dict(out[2][1], ordinal=0), dict(out[2][0], ordinal=1)]
    with pytest.raises(AssertionError):
        check_frame_records(frame, swapped)
    assert sys.modules["synapse_hla.reducer"] is reducer


# ============================================================ one validation per session (CR-L07)

def test_the_session_configuration_is_validated_once_per_session(monkeypatch):
    """CR-L07: `initial_state` validates the header's configuration once and keeps it as a
    `config.ValidatedConfig`; reducing every frame of the bundled capture (four snapshots, two
    of them projected to upserts) validates it no further time. The records are the bundle's
    expected observations byte for byte, so nothing of the output changed."""
    from synapse_hla import config as config_module
    calls = []
    real = config_module.validate_config

    def counted(mapping):
        calls.append(1)
        return real(mapping)
    monkeypatch.setattr(config_module, "validate_config", counted)
    records = fixture_capture_records()
    state = reducer.initial_state(records[0], True)
    assert calls == [1]
    assert type(state.config) is config_module.ValidatedConfig
    assert state.config == config_module.validated_config(records[0]["config"])
    calls.clear()
    lines = []
    for frame in records[1:-1]:
        state, out = reducer.reduce_frame(state, frame)
        lines.extend(reducer.output_line(r) for r in out)
    assert calls == []
    assert b"".join(lines) == package_bytes("fixtures", "expected.observations.jsonl")


def test_a_frame_admitted_by_the_callers_rules_reduces_as_reduce_frame_reduces_it():
    """CR-L07: `reduce_admitted` takes a frame its caller's own capture rules have just admitted
    (replay's verified reader, the live writer's chain). Over the bundled capture it gives the
    same records and the same next state as `reduce_frame`, frame for frame."""
    records = fixture_capture_records()
    by_frame = reducer.initial_state(records[0], True)
    admitted = reducer.initial_state(records[0], True)
    for frame in records[1:-1]:
        by_frame, expected = reducer.reduce_frame(by_frame, frame)
        admitted, got = reducer.reduce_admitted(admitted, copy.deepcopy(frame))
        assert got == expected
        assert admitted == by_frame


@pytest.mark.parametrize("change", ["seq-ahead", "seq-behind", "prev-sha256", "footer",
                                    "header", "not-a-dict", "no-sha256"])
def test_reduce_admitted_takes_only_the_next_frame_of_its_capture(change):
    """The one check `reduce_admitted` keeps: the frame is the one for this position (seq next,
    prev_sha256 the chain head, a frame with a digest). Anything else is a caller bug
    (ValueError), and the state is unchanged."""
    records = fixture_capture_records()
    state = reducer.initial_state(records[0], True)
    state, _ = reducer.reduce_frame(state, records[1])
    snapshot = copy.deepcopy(state)
    frame = copy.deepcopy(records[2])
    if change == "seq-ahead":
        frame["seq"] = 3
    elif change == "seq-behind":
        frame["seq"] = 1
    elif change == "prev-sha256":
        frame["prev_sha256"] = "0" * 64
    elif change == "footer":
        frame = copy.deepcopy(records[-1])
        frame["seq"], frame["prev_sha256"] = 2, records[1]["sha256"]
    elif change == "header":
        frame = copy.deepcopy(records[0])
    elif change == "not-a-dict":
        frame = [frame]
    else:
        del frame["sha256"]
    with pytest.raises(ValueError):
        reducer.reduce_admitted(state, frame)
    assert state == snapshot
    with pytest.raises(TypeError):
        reducer.reduce_admitted(dict(vars(state)), records[2])
