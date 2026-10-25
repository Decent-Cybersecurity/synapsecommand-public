"""`CesmoInternalAdapter` (#34): the mapping, the identities, the ledger, the limits and the metadata.

The specification is the SynapseCommand STANAG 4658 CESMO and EOB Engineering Kit 1.0 (Decent
Cybersecurity, 4 October 2026): its sections 7 to 12 and 19, read with the run's rulings on it
(DECISIONS C-01 to C-15). Every expected value below is written by hand from those texts and from
the fixtures' own content — identities as their literal scoped keys, refusals as their whole
message, the kit's two UUIDs and its `expected-upsert-cdm.json` as the kit states them — and never
read back from the adapter's output. A test that binds one of the kit's acceptance rows names it
(C01 ... C40) in its docstring.

PACKAGE-ONLY: everything this module reads ships in the wheel (the adapter, its fixture tree, the
goldens and the kit's expected projection under `fixtures/cesmo_internal/reference/`), all through
`synapse_cdm.__file__`. The contract's own refusal table is `tests/test_cdm_cesmo_internal_contract.py`,
the fuzz target `tests/test_cdm_cesmo_internal_fuzz.py`, and the repository-bound half (the
published schema copy) `tests/test_cdm_cesmo_internal_schema.py`.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import pathlib
import pickle
import subprocess
import sys

import pytest
import synapse_cdm
from synapse_cdm import harness, ids, lossless, projection, times
from synapse_cdm.adapter import REGISTRY, InputTooDeep, InputTooLarge
from synapse_cdm.adapters import cesmo_internal as module
from synapse_cdm.adapters.cesmo_internal import CesmoInternalAdapter
from synapse_cdm.adapters.cesmo_internal_codec import CesmoError
from synapse_cdm.manifest import (
    ClaimStatus,
    Direction,
    LicenseClass,
    LimitKind,
    MaturityLevel,
    Residual,
    UnknownFields,
    WireBinding,
)
from synapse_cdm.version import SCHEMA_VERSION

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
SET = PKG / "fixtures" / "cesmo_internal"
MALFORMED = SET / "malformed"
GOLDEN = SET / "golden"
EXPECTED = SET / "reference" / "expected-upsert-cdm.json"

UTC = dt.timezone.utc
#: The kit's receipt clock for its expected output (README.txt: 2026-10-04T12:00:01Z).
KIT_RECEIPT = dt.datetime(2026, 10, 4, 12, 0, 1, tzinfo=UTC)
SYSTEM = "SC_CESMO_INTERNAL"
ID, TIME, METHOD = (
    "identity-scoping-v1",
    "timestamp-millisecond-truncation-v1",
    "position-method-enum-v1",
)
SCOPE = '"synthetic","TEST-NET","TEST-SOURCE-A","EXERCISE-1"'


def kit_clock():
    return KIT_RECEIPT


def ekey(object_id: str, scope: str = SCOPE) -> str:
    """Kit §11's emitter key, written out: J([mode, network, originator, epoch, object_id])."""
    return f'[{scope},"{object_id}"]'


def vkey(message_id: str, record_id: str, scope: str = SCOPE) -> str:
    """Kit §11's event key, written out: J([mode, network, originator, epoch, message, record])."""
    return f'[{scope},"{message_id}","{record_id}"]'


def pad(prefix: str) -> str:
    return prefix + "0" * (64 - len(prefix))


SCOPE_64 = f'"synthetic","{pad("TEST-NET-")}","{pad("TEST-SOURCE-A-")}","{pad("EXERCISE-1-")}"'


def adapter(**kwargs) -> CesmoInternalAdapter:
    return CesmoInternalAdapter(times.frozen_clock(), **kwargs)


def raw(name: str):
    return harness.load_raw(SET / name)


def doc(name: str) -> dict:
    return json.loads((SET / name).read_bytes())


def dumps(objects) -> list[dict]:
    return [o.model_dump(mode="json") for o in objects]


# ------------------------------------------------------------------ the expected projections

#: Per fixture, per object in output order: (object kind, event type, operation, original_id,
#: record_index, observed_at, transformations, Point coordinates, related emitter object_id, the
#: scoped key of `source_ids[0]`). Written from each fixture's content by hand.
E, V = "entity", "event"
EXPECTED_OBJECTS = {
    "observation.json": [
        (
            V,
            "DETECTION",
            "observation",
            "OBS-1",
            0,
            "2026-10-04T12:00:00.000Z",
            [ID],
            None,
            None,
            vkey("MSG-1", "OBS-1"),
        ),
    ],
    "upsert.json": [
        (
            E,
            None,
            None,
            "EOB-1",
            0,
            "2026-10-04T12:00:00.000Z",
            [ID, METHOD],
            None,
            None,
            ekey("EMITTER-1"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-1",
            0,
            "2026-10-04T12:00:00.000Z",
            [ID, METHOD],
            [0.0, 0.0],
            "EMITTER-1",
            vkey("MSG-2", "EOB-1"),
        ),
    ],
    "withdrawal.json": [
        (
            V,
            "STATUS_CHANGE",
            "withdraw",
            "DEL-1",
            0,
            "2026-10-04T12:00:00.000Z",
            [ID],
            None,
            "EMITTER-1",
            vkey("MSG-3", "DEL-1"),
        ),
    ],
    "status.json": [
        (
            V,
            "STATUS_CHANGE",
            "status",
            "STATE-1",
            0,
            "2026-10-04T12:00:00.000Z",
            [ID],
            None,
            None,
            vkey("MSG-5", "STATE-1"),
        ),
    ],
    "empty-complete-snapshot.json": [
        (
            V,
            "STATUS_CHANGE",
            "snapshot",
            "SNAP-1",
            None,
            "2026-10-04T12:00:00.000Z",
            [ID],
            None,
            None,
            vkey("MSG-4", "$snapshot"),
        ),
    ],
    "every-kind.json": [
        (
            V,
            "DETECTION",
            "observation",
            "OBS-2",
            0,
            "2026-10-04T12:00:05.000Z",
            [ID, METHOD],
            [21.5, 57.25, 41.5],
            "EMITTER-2",
            vkey("MSG-6", "OBS-2"),
        ),
        (
            E,
            None,
            None,
            "EOB-2",
            1,
            "2026-10-04T12:00:06.000Z",
            [ID, METHOD],
            None,
            None,
            ekey("EMITTER-2"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-2",
            1,
            "2026-10-04T12:00:06.000Z",
            [ID, METHOD],
            [21.5, 57.25],
            "EMITTER-2",
            vkey("MSG-6", "EOB-2"),
        ),
        (
            V,
            "STATUS_CHANGE",
            "withdraw",
            "DEL-2",
            2,
            "2026-10-04T12:00:07.000Z",
            [ID],
            None,
            "EMITTER-3",
            vkey("MSG-6", "DEL-2"),
        ),
        (
            V,
            "STATUS_CHANGE",
            "status",
            "STATE-2",
            3,
            "2026-10-04T12:00:08.000Z",
            [ID],
            None,
            None,
            vkey("MSG-6", "STATE-2"),
        ),
    ],
    "complete-snapshot-with-upserts.json": [
        (
            E,
            None,
            None,
            "EOB-3",
            0,
            "2026-10-04T11:59:30.000Z",
            [ID, METHOD],
            None,
            None,
            ekey("EMITTER-2"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-3",
            0,
            "2026-10-04T11:59:30.000Z",
            [ID, METHOD],
            [22.25, 57.5, 312.5],
            "EMITTER-2",
            vkey("MSG-7", "EOB-3"),
        ),
        (
            E,
            None,
            None,
            "EOB-4",
            1,
            "2026-10-04T11:59:31.000Z",
            [ID],
            None,
            None,
            ekey("EMITTER-4"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-4",
            1,
            "2026-10-04T11:59:31.000Z",
            [ID],
            None,
            "EMITTER-4",
            vkey("MSG-7", "EOB-4"),
        ),
        (
            V,
            "STATUS_CHANGE",
            "snapshot",
            "SNAP-2",
            None,
            "2026-10-04T12:00:00.000Z",
            [ID],
            None,
            None,
            vkey("MSG-7", "$snapshot"),
        ),
    ],
    "observation-position-no-object.json": [
        (
            V,
            "DETECTION",
            "observation",
            "OBS-3",
            0,
            "2026-10-04T12:00:10.000Z",
            [ID, METHOD],
            [23.75, 56.5],
            None,
            vkey("MSG-8", "OBS-3"),
        ),
    ],
    "sub-millisecond.json": [
        (
            E,
            None,
            None,
            "EOB-5",
            0,
            "2026-10-04T12:00:09.123Z",
            [ID, TIME, METHOD],
            None,
            None,
            ekey("EMITTER-5"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-5",
            0,
            "2026-10-04T12:00:09.123Z",
            [ID, TIME, METHOD],
            [24.0, 58.0],
            "EMITTER-5",
            vkey("MSG-9", "EOB-5"),
        ),
        (
            E,
            None,
            None,
            "EOB-6",
            1,
            "2026-10-04T12:00:09.120Z",
            [ID],
            None,
            None,
            ekey("EMITTER-6"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-6",
            1,
            "2026-10-04T12:00:09.120Z",
            [ID],
            None,
            "EMITTER-6",
            vkey("MSG-9", "EOB-6"),
        ),
        (
            E,
            None,
            None,
            "EOB-7",
            2,
            "2026-10-04T12:00:09.500Z",
            [ID],
            None,
            None,
            ekey("EMITTER-7"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-7",
            2,
            "2026-10-04T12:00:09.500Z",
            [ID],
            None,
            "EMITTER-7",
            vkey("MSG-9", "EOB-7"),
        ),
        (
            V,
            "STATUS_CHANGE",
            "snapshot",
            "SNAP-3",
            None,
            "2026-10-04T12:00:09.000Z",
            [ID, TIME],
            None,
            None,
            vkey("MSG-9", "$snapshot"),
        ),
    ],
    "cdm-shaped-extension-keys.json": [
        (
            V,
            "DETECTION",
            "observation",
            "OBS-4",
            0,
            "2026-10-04T12:00:11.000Z",
            [ID],
            None,
            "EMITTER-8",
            vkey("MSG-10", "OBS-4"),
        ),
        (
            E,
            None,
            None,
            "EOB-8",
            1,
            "2026-10-04T12:00:12.000Z",
            [ID],
            None,
            None,
            ekey("EMITTER-8"),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            "EOB-8",
            1,
            "2026-10-04T12:00:12.000Z",
            [ID],
            None,
            "EMITTER-8",
            vkey("MSG-10", "EOB-8"),
        ),
    ],
    "tokens-at-64.json": [
        (
            E,
            None,
            None,
            pad("EOB-"),
            0,
            "2026-10-04T12:00:13.000Z",
            [ID],
            None,
            None,
            ekey(pad("EMITTER-"), SCOPE_64),
        ),
        (
            V,
            "TRACK_UPDATE",
            "upsert",
            pad("EOB-"),
            0,
            "2026-10-04T12:00:13.000Z",
            [ID],
            None,
            pad("EMITTER-"),
            vkey(pad("MSG-"), pad("EOB-"), SCOPE_64),
        ),
        (
            V,
            "STATUS_CHANGE",
            "snapshot",
            pad("SNAP-"),
            None,
            "2026-10-04T12:00:00.000Z",
            [ID],
            None,
            None,
            vkey(pad("MSG-"), "$snapshot", SCOPE_64),
        ),
    ],
}
EXPECTED_OBJECTS["upsert_octets.bin"] = EXPECTED_OBJECTS["upsert.json"]
#: The emitter scope of `tokens-at-64.json`'s related entity.
RELATED_SCOPE = {"tokens-at-64.json": SCOPE_64}
#: The document each fixture parses to (the octet twin is `upsert.json`'s bytes).
DOCUMENT = {name: name for name in EXPECTED_OBJECTS} | {"upsert_octets.bin": "upsert.json"}


def _check_object(name: str, obj: dict, row: tuple) -> None:
    kind, event_type, operation, original, index, observed, transforms, coords, related, key = row
    assert obj["object_kind"] == kind
    assert obj["source"]["original_id"] == original
    assert obj["source"]["record_index"] == index
    assert obj["source"]["observed_at"] == observed
    assert obj["source"]["transformations"] == transforms
    assert obj["source"]["system"] == SYSTEM and obj["source"]["adapter"] == "cesmo_internal"
    assert obj["source"]["format_name"] == "SC CESMO Internal Exchange"
    assert obj["source"]["format_version"] == "1.0.0" and obj["source"]["synthetic"] is True
    assert obj["source_ids"] == [{"system": SYSTEM, "external_id": key}]
    assert obj["schema_version"] == SCHEMA_VERSION
    if kind == E:
        assert obj["entity_id"] == str(ids.derive(SYSTEM, key, kind="entity"))
        assert obj["entity_type"] == "UNKNOWN" and obj["valid_from"] == observed
        assert obj["valid_to"] is None and obj["symbol"] is None and obj["kinematics"] is None
        assert obj["attributes"]["cesmo"]["role"] == "emitter"
        return
    assert obj["event_id"] == str(ids.derive(SYSTEM, key, kind="event"))
    assert obj["event_type"] == event_type and obj["severity"] == "INFO"
    assert obj["payload"]["cesmo"]["operation"] == operation
    assert obj["observed_at"] == observed
    assert obj["geometry"] == (None if coords is None else {"type": "Point", "coordinates": coords})
    emitter = [] if related is None else [ekey(related, RELATED_SCOPE.get(name, SCOPE))]
    assert obj["related_entities"] == [str(ids.derive(SYSTEM, k, kind="entity")) for k in emitter]


@pytest.mark.parametrize("name", sorted(EXPECTED_OBJECTS))
def test_every_fixture_projects_to_its_hand_written_objects_in_the_kit_order(name):
    """C01, C03, C08 and C13 through the fixtures: per record Entity before Event, the snapshot
    Event last; event types, operations, severity, geometry presence and absence, related
    entities, original ids, record indices, source times and transformations (kit §11-§12,
    DECISIONS C-05)."""
    out = dumps(adapter().to_cdm(raw(name)))
    rows = EXPECTED_OBJECTS[name]
    assert len(out) == len(rows)
    for obj, row in zip(out, rows):
        _check_object(name, obj, row)


@pytest.mark.parametrize("name", sorted(EXPECTED_OBJECTS))
def test_every_golden_holds_the_hand_written_objects(name):
    """The goldens are a regression record written by `--update-golden`; this pins their content
    to the same literals, under the harness clock."""
    golden = json.loads((GOLDEN / (pathlib.Path(name).stem + ".cdm.json")).read_text("utf-8"))
    rows = EXPECTED_OBJECTS[name]
    assert len(golden) == len(rows)
    for obj, row in zip(golden, rows):
        _check_object(name, obj, row)
        if obj["object_kind"] == V:
            assert obj["received_at"] == "2026-04-29T06:15:00.000Z"


def test_the_fixture_directory_holds_exactly_the_expected_set():
    shipped = sorted(p.name for p in harness.select_fixtures(SET))
    assert shipped == sorted(EXPECTED_OBJECTS)
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(
        pathlib.Path(n).stem + ".cdm.json" for n in EXPECTED_OBJECTS
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_OBJECTS))
def test_every_object_carries_the_envelope_without_records_and_its_record_verbatim(name):
    """Kit L173 as DECISIONS C-02/C-05 rule it: `{"envelope", "record"}` on record objects, the
    envelope minus `records` only (the snapshot stays), `{"envelope"}` on the snapshot Event."""
    source = doc(DOCUMENT[name])
    envelope = {k: v for k, v in source.items() if k != "records"}
    for obj in dumps(adapter().to_cdm(raw(name))):
        assert obj["residual"]["namespace"] == "SC CESMO Internal Exchange"
        index = obj["source"]["record_index"]
        if index is None:
            assert obj["residual"]["data"] == {"envelope": envelope}
        else:
            assert obj["residual"]["data"] == {
                "envelope": envelope,
                "record": source["records"][index],
            }
            if obj["object_kind"] == V:
                assert obj["payload"]["cesmo"] == {
                    **source["records"][index],
                    "operation": obj["payload"]["cesmo"]["operation"],
                    "source_scope": source["source"],
                }
            # Key order too: the residual keeps the source's own order (json.dumps of a dict).
            assert list(obj["residual"]["data"]["record"]) == list(source["records"][index])
        assert list(obj["residual"]["data"]["envelope"]) == list(envelope)


# ------------------------------------------------------------------ the kit's expected output


@pytest.mark.parametrize("form", ["bytes", "dict"])
def test_the_kits_expected_upsert_projection_is_reproduced_byte_for_byte(form):
    """C02: `expected-upsert-cdm.json` from `upsert.json`, octets and dict, under the kit's
    receipt clock. The kit wrote it against CDM 3.0.0, so the comparison is the adapter's
    `cdm_schema="3.0.0"` stamp dumped for a 3.0.0 reader (`projection.dump_for`), the file's
    exact bytes; the default projection differs only by its stamp and the Event's 3.2.0
    `validity`, null."""
    octets = (SET / "upsert.json").read_bytes()
    source = octets if form == "bytes" else json.loads(octets)
    objects = CesmoInternalAdapter(kit_clock, cdm_schema="3.0.0").to_cdm(source)
    written = json.dumps([projection.dump_for(o, "3.0.0") for o in objects], indent=2) + "\n"
    assert written.encode("utf-8") == EXPECTED.read_bytes()
    full = dumps(CesmoInternalAdapter(kit_clock).to_cdm(source))
    kit = json.loads(EXPECTED.read_bytes())
    assert full[0] == {**kit[0], "schema_version": "3.2.0"}
    assert full[1] == {**kit[1], "schema_version": "3.2.0", "validity": None}


def test_the_kits_two_expected_identities_are_derived():
    """C01/C02's identities, the kit's literals: the emitter Entity and the upsert Event."""
    entity, event = adapter().to_cdm(raw("upsert.json"))
    assert str(entity.entity_id) == "75ccd4f2-f73a-5d32-9c27-82585ce69f55"
    assert str(event.event_id) == "64e3ed4a-b5c5-5ec3-9653-adfc5324d3e0"
    assert [str(u) for u in event.related_entities] == ["75ccd4f2-f73a-5d32-9c27-82585ce69f55"]


def test_the_carried_kit_files_are_the_kits_bytes():
    """The five fixtures and the expected projection, held to the SHA-256 the kit's
    SHA256SUMS.txt states (also recorded in spec/cesmo_internal_pin.json)."""
    digests = {
        "empty-complete-snapshot.json": "7a5d1b8f78d56c2364e5b7ffaa28d64d6aa388aadcd0fae01734d6847821d492",
        "observation.json": "c5cacd97f4af77bb134a7d2d84e687c29a5ca46331a2f7e3784b6ec557bc97e2",
        "status.json": "178a325047ec8fa51c31d555ae13795afd3b998e7e46a4d794e95d1f2acaf40e",
        "upsert.json": "5bb87565a27794e293b610c4c352b84410103b820be5f7e40572e0d55c1b7780",
        "withdrawal.json": "e015339a9059080e2bb3667c47af31be480e4d1a63a219a54ca785231d585d11",
        "reference/expected-upsert-cdm.json": "425b77be2b671de814f30e818497b287651c363adf48999cba25e11cd5827f54",
        "upsert_octets.bin": "5bb87565a27794e293b610c4c352b84410103b820be5f7e40572e0d55c1b7780",
    }
    assert {n: hashlib.sha256((SET / n).read_bytes()).hexdigest() for n in digests} == digests
    pin = json.loads((SET / "spec" / "cesmo_internal_pin.json").read_bytes())
    recorded = {f["file"]: f["sha256"] for f in pin["files"]}
    for name, digest in digests.items():
        if name != "upsert_octets.bin":
            kit_name = (
                name.replace("reference/", "")
                if name.startswith("reference/")
                else f"fixtures/{name}"
            )
            assert recorded[kit_name] == digest


# ------------------------------------------------------------------ the mapping, value by value


def test_the_upsert_entity_holds_position_ellipse_and_zero_confidence():
    """C02, C11, C13: latitude 0 and longitude 0 are a real position, confidence 0 is 0.0 and
    not None, the ellipse stays verbatim in attributes and `accuracy_m` is None."""
    entity, event = dumps(adapter().to_cdm(raw("upsert.json")))
    assert entity["position"] == {
        "lat": 0.0,
        "lon": 0.0,
        "alt_m": None,
        "position_source": "ESTIMATED",
        "accuracy_m": None,
        "vertical": None,
    }
    assert entity["confidence"] == 0.0 and entity["affiliation"] == "UNKNOWN"
    assert entity["attributes"] == {
        "cesmo": {
            "contract": "sc.cesmo.internal/1.0",
            "role": "emitter",
            "operation": "upsert",
            "revision": 4,
            "uncertainty": {
                "semi_major_m": 400,
                "semi_minor_m": 100,
                "orientation_deg": 30,
                "probability": 0.95,
                "frame": "ENU_TRUE_NORTH",
            },
            "signal": {"frequency_hz": 1000000000},
            "mapping_basis": "source-asserted EOB object; no RF identification performed",
        }
    }
    assert event["geometry"] == {"type": "Point", "coordinates": [0.0, 0.0]}


def test_an_emitter_with_every_block_and_one_with_none():
    """C11: confidence 0.75 kept, an absent confidence None and an absent affiliation UNKNOWN;
    `hae_m` is `alt_m` and the third coordinate, `vertical` and `accuracy_m` stay None."""
    objs = dumps(adapter().to_cdm(raw("complete-snapshot-with-upserts.json")))
    full, empty = objs[0], objs[2]
    assert full["position"] == {
        "lat": 57.5,
        "lon": 22.25,
        "alt_m": 312.5,
        "position_source": "GNSS",
        "accuracy_m": None,
        "vertical": None,
    }
    assert (full["affiliation"], full["confidence"]) == ("HOSTILE", 0.75)
    assert full["attributes"]["cesmo"]["signal"] == {
        "frequency_hz": 2900000000,
        "bandwidth_hz": 5000000,
        "pulse_width_s": 0.000001,
        "pri_s": 0.001,
        "power_dbm": -71.5,
        "sensor_id": "SENSOR-2",
    }
    assert list(full["attributes"]["cesmo"]) == [
        "contract",
        "role",
        "operation",
        "revision",
        "uncertainty",
        "signal",
        "mapping_basis",
    ]
    assert (empty["position"], empty["affiliation"], empty["confidence"]) == (None, "UNKNOWN", None)
    assert empty["attributes"] == {
        "cesmo": {
            "contract": "sc.cesmo.internal/1.0",
            "role": "emitter",
            "operation": "upsert",
            "revision": 8,
            "mapping_basis": "source-asserted EOB object; no RF identification performed",
        }
    }
    assert objs[3]["geometry"] is None


def test_every_kind_maps_methods_and_affiliations_by_their_literal_tables():
    every = dumps(adapter().to_cdm(raw("every-kind.json")))
    entity = every[1]
    assert entity["position"] == {
        "lat": 57.25,
        "lon": 21.5,
        "alt_m": None,
        "position_source": "MANUAL",
        "accuracy_m": None,
        "vertical": None,
    }
    assert (entity["affiliation"], entity["confidence"]) == ("FRIENDLY", 1.0)
    assert {k: v.value for k, v in module.METHODS.items()} == {
        "estimated": "ESTIMATED",
        "gnss": "GNSS",
        "inertial": "INERTIAL",
        "manual": "MANUAL",
    }
    assert {k: v.value for k, v in module.AFFILIATIONS.items()} == {
        "FRIENDLY": "FRIENDLY",
        "HOSTILE": "HOSTILE",
        "NEUTRAL": "NEUTRAL",
        "UNKNOWN": "UNKNOWN",
    }


def test_an_observation_never_fabricates_an_entity_and_a_bearing_never_becomes_geometry():
    """C01 and C08: one DETECTION, no Entity, no geometry and no emitter for a bearing-only
    observation; an observation with an `object_id` names the scoped emitter and still makes no
    Entity (kit L161)."""
    (only,) = dumps(adapter().to_cdm(raw("observation.json")))
    assert (
        only["object_kind"],
        only["event_type"],
        only["geometry"],
        only["related_entities"],
    ) == ("event", "DETECTION", None, [])
    assert only["payload"]["cesmo"]["signal"] == {
        "frequency_hz": 1000000000,
        "bearing_deg_true": 45,
        "sensor_id": "SENSOR-1",
    }
    named = dumps(adapter().to_cdm(raw("cdm-shaped-extension-keys.json")))[0]
    assert named["object_kind"] == "event" and named["geometry"] is None
    assert named["related_entities"] == [str(ids.derive(SYSTEM, ekey("EMITTER-8"), kind="entity"))]


def test_other_datums_and_magnetic_bearings_stay_in_extensions():
    """C09: a height above mean sea level and a magnetic bearing have no contract field; carried
    in `extensions` they are neither an HAE nor a true bearing: no third coordinate, no
    `alt_m`, and the payload carries them verbatim (kit L143)."""
    source = doc("every-kind.json")
    record = copy.deepcopy(source["records"][1])
    record["extensions"] = {"height_msl_m": 120, "bearing_deg_magnetic": 33}
    source["records"] = [record]
    entity, event = dumps(adapter().to_cdm(source))
    assert entity["position"]["alt_m"] is None and entity["position"]["vertical"] is None
    assert event["geometry"] == {"type": "Point", "coordinates": [21.5, 57.25]}
    assert event["payload"]["cesmo"]["extensions"] == {
        "height_msl_m": 120,
        "bearing_deg_magnetic": 33,
    }
    assert "bearing_deg_true" not in event["payload"]["cesmo"].get("signal", {})


def test_withdrawals_of_a_present_and_an_absent_emitter():
    """C03: a STATUS_CHANGE Event naming the scoped emitter, operation `withdraw`, no Entity,
    whether or not the emitter's Entity is in the message; nothing asserts a destruction."""
    (gone,) = dumps(adapter().to_cdm(raw("withdrawal.json")))
    assert (
        gone["event_type"] == "STATUS_CHANGE"
        and gone["payload"]["cesmo"]["operation"] == "withdraw"
    )
    assert gone["related_entities"] == ["75ccd4f2-f73a-5d32-9c27-82585ce69f55"]
    every = dumps(adapter().to_cdm(raw("every-kind.json")))
    assert [o["object_kind"] for o in every].count("entity") == 1
    assert every[3]["related_entities"] == [
        str(ids.derive(SYSTEM, ekey("EMITTER-3"), kind="entity"))
    ]
    assert all(o["severity"] == "INFO" for o in every if o["object_kind"] == "event")


def test_the_snapshot_event():
    """DECISIONS C-05 b: one STATUS_CHANGE Event after every record object; key with
    `$snapshot`; original_id the snapshot_id, record_index None, observed_at the envelope's;
    payload the snapshot, `snapshot` and the source scope; no related entity."""
    (event,) = dumps(adapter().to_cdm(raw("empty-complete-snapshot.json")))
    assert event["payload"] == {
        "cesmo": {
            "snapshot": {"snapshot_id": "SNAP-1", "complete": True, "revision": 6},
            "operation": "snapshot",
            "source_scope": {
                "network_id": "TEST-NET",
                "originator_id": "TEST-SOURCE-A",
                "identity_epoch": "EXERCISE-1",
            },
        }
    }
    assert (
        event["source_ids"][0]["external_id"]
        == '["synthetic","TEST-NET","TEST-SOURCE-A","EXERCISE-1","MSG-4","$snapshot"]'
    )
    assert event["related_entities"] == [] and event["geometry"] is None


def test_the_truncation_token_only_where_a_digit_is_dropped():
    """DECISIONS C-05 d and kit L152: `.123456` drops 456 (token), `.120000` drops nothing (no
    token), `.5` has no sub-millisecond digit; the envelope's `.000250` gives the snapshot Event
    the token. The source strings stay in payload and residual."""
    objs = adapter().to_cdm(raw("sub-millisecond.json"))
    assert [(o.source.transformations, times.render(o.source.observed_at)) for o in objs] == [
        ([ID, TIME, METHOD], "2026-10-04T12:00:09.123Z"),
        ([ID, TIME, METHOD], "2026-10-04T12:00:09.123Z"),
        ([ID], "2026-10-04T12:00:09.120Z"),
        ([ID], "2026-10-04T12:00:09.120Z"),
        ([ID], "2026-10-04T12:00:09.500Z"),
        ([ID], "2026-10-04T12:00:09.500Z"),
        ([ID, TIME], "2026-10-04T12:00:09.000Z"),
    ]
    assert objs[1].payload["cesmo"]["observed_at"] == "2026-10-04T12:00:09.123456Z"
    assert objs[6].residual.data["envelope"]["observed_at"] == "2026-10-04T12:00:09.000250Z"


def test_the_observed_time_is_the_sources_and_the_receipt_the_clock():
    """C10's second half and kit L108: received_at is the injected clock's, never substituted
    for observed_at; a replay under another receipt clock changes received_at only (C05)."""
    first = dumps(CesmoInternalAdapter(kit_clock).to_cdm(raw("every-kind.json")))
    later = dumps(
        CesmoInternalAdapter(lambda: dt.datetime(2026, 10, 5, 9, 0, tzinfo=UTC)).to_cdm(
            raw("every-kind.json")
        )
    )
    assert [o.get("received_at") for o in first if o["object_kind"] == "event"] == [
        "2026-10-04T12:00:01.000Z"
    ] * 4
    for a, b in zip(first, later):
        if a["object_kind"] == "event":
            assert b["received_at"] == "2026-10-05T09:00:00.000Z"
            a = {**a, "received_at": None}
            b = {**b, "received_at": None}
        assert a == b


def test_two_originators_reusing_an_emitter_id_are_two_entities():
    """C04: the originator is in the emitter key, so the same `object_id` from TEST-SOURCE-B is
    another Entity."""
    other = doc("upsert.json")
    other["source"]["originator_id"] = "TEST-SOURCE-B"
    (a, _), (b, _) = adapter().to_cdm(raw("upsert.json")), adapter().to_cdm(other)
    assert str(a.entity_id) == "75ccd4f2-f73a-5d32-9c27-82585ce69f55"
    assert str(b.entity_id) == str(
        ids.derive(
            SYSTEM,
            '["synthetic","TEST-NET","TEST-SOURCE-B","EXERCISE-1","EMITTER-1"]',
            kind="entity",
        )
    )
    assert a.entity_id != b.entity_id


def test_the_live_and_synthetic_partitions_never_share_an_identity():
    """C06: the same identifiers in mode live under `synthetic=False` derive other UUIDs, and a
    mode the constructor disagrees with is E_MODE_MISMATCH both ways."""
    live = doc("upsert.json")
    live["mode"] = "live"
    entity, event = CesmoInternalAdapter(kit_clock, synthetic=False).to_cdm(live)
    assert entity.source.synthetic is False
    assert str(entity.entity_id) == str(
        ids.derive(
            SYSTEM, '["live","TEST-NET","TEST-SOURCE-A","EXERCISE-1","EMITTER-1"]', kind="entity"
        )
    )
    assert str(entity.entity_id) != "75ccd4f2-f73a-5d32-9c27-82585ce69f55"
    assert str(event.event_id) != "64e3ed4a-b5c5-5ec3-9653-adfc5324d3e0"
    for document, synthetic in ((live, True), (doc("upsert.json"), False)):
        with pytest.raises(CesmoError) as raised:
            CesmoInternalAdapter(kit_clock, synthetic=synthetic).to_cdm(document)
        assert str(raised.value) == "E_MODE_MISMATCH mode mode differs from the constructor's"


def test_a_trusted_source_hash_is_carried_and_never_read_from_the_document():
    digest = {"algorithm": "sha256", "value": "0" * 64}
    objs = CesmoInternalAdapter(kit_clock, source_hash=digest).to_cdm(raw("every-kind.json"))
    assert [o.source.source_hash.model_dump() for o in objs] == [digest] * 5
    assert all(o.source.source_hash is None for o in adapter().to_cdm(raw("every-kind.json")))


def test_the_constructor_refuses_what_it_cannot_honour():
    with pytest.raises(TypeError, match="synthetic must be a bool"):
        CesmoInternalAdapter(synthetic=1)
    with pytest.raises(ValueError, match="cdm_schema must be None"):
        CesmoInternalAdapter(cdm_schema="3.1.0")
    with pytest.raises(ValueError):
        CesmoInternalAdapter(source_hash={"algorithm": "sha256"})
    assert (
        CesmoInternalAdapter(cdm_schema=SCHEMA_VERSION).to_cdm(raw("status.json"))[0].schema_version
        == SCHEMA_VERSION
    )


def test_the_callers_dict_is_never_changed_and_never_shared():
    source = doc("complete-snapshot-with-upserts.json")
    before = copy.deepcopy(source)
    objs = adapter().to_cdm(source)
    assert source == before
    objs[1].payload["cesmo"]["signal"]["frequency_hz"] = 1
    objs[0].residual.data["record"]["object_id"] = "X"
    assert source == before
    assert objs[1].residual.data["record"]["object_id"] == "EMITTER-2"


def test_the_object_cap_is_reached_exactly_and_not_passed():
    """Kit §19's 2,001 CDM objects: 1,000 upserts and a snapshot make exactly 2,001; a 1,001st
    record is the schema's maxItems, E_SCHEMA at `records`, on both paths."""
    source = doc("upsert.json")
    template = source["records"][0]
    source["records"] = [
        {**copy.deepcopy(template), "record_id": f"EOB-{i}", "object_id": f"EMITTER-{i}"}
        for i in range(1000)
    ]
    source["snapshot"] = {"snapshot_id": "SNAP-9", "complete": True, "revision": 4}
    assert len(adapter().to_cdm(source)) == module.MAX_OBJECTS == 2001
    source["records"].append(
        {**copy.deepcopy(template), "record_id": "EOB-X", "object_id": "EMITTER-X"}
    )
    for form in (source, json.dumps(source).encode()):
        with pytest.raises(CesmoError) as raised:
            adapter().to_cdm(form)
        assert str(raised.value) == "E_SCHEMA records maxItems"


# ------------------------------------------------------------------ the limits and C-07


def _nested_dict(depth: int) -> dict:
    """upsert.json whose `extensions` nest so the document nests exactly `depth` containers."""
    source = doc("upsert.json")
    node: list = []
    for _ in range(depth - 5):
        node = [node]
    source["records"][0]["extensions"]["nested"] = node
    return source


def _nested_octets(depth: int) -> bytes:
    text = (SET / "upsert.json").read_text("utf-8")
    nested = "[" * (depth - 4) + "]" * (depth - 4)
    return text.replace('"source_category": "synthetic-emitter",', f'"nested": {nested},').encode()


def test_depth_16_and_64_and_their_successors():
    """C16 and DECISIONS C-03/C-07: 16 containers translate and the nested data survives
    verbatim; 17 to 64 are the contract's E_LIMIT (a CesmoError, not InputTooDeep); 65 is the
    SDK's bound, raised as CesmoInputTooDeep — both InputTooDeep and E_LIMIT — on octets and on
    a dict."""
    from synapse_cdm.adapter import container_depth, json_nesting_depth

    for depth in (16, 17, 64, 65):
        assert container_depth(_nested_dict(depth)) == depth
        assert json_nesting_depth(_nested_octets(depth).decode()) == depth
    for form in (_nested_dict(16), _nested_octets(16)):
        entity, event = adapter().to_cdm(form)
        assert (
            event.residual.data["record"]["extensions"]
            == (_nested_dict(16) if isinstance(form, dict) else json.loads(form))["records"][0][
                "extensions"
            ]
        )
    for depth in (17, 64):
        for form in (_nested_dict(depth), _nested_octets(depth)):
            with pytest.raises(CesmoError) as raised:
                adapter().to_cdm(form)
            assert not isinstance(raised.value, InputTooDeep)
            assert str(raised.value) == "E_LIMIT (root) nesting deeper than 16 containers"
    for form, unit in ((_nested_dict(65), "parsed"), (_nested_octets(65), "JSON")):
        with pytest.raises(InputTooDeep) as raised:
            adapter().to_cdm(form)
        assert isinstance(raised.value, CesmoError) and raised.value.code == "E_LIMIT"
        assert raised.value.path == "" and raised.value.record_index is None
        assert str(raised.value).startswith(
            f"E_LIMIT (root) cesmo_internal was handed a {unit} document nesting 65 containers deep "
            "and declares max_depth = 64."
        )


def test_one_octet_over_the_cap_is_both_input_too_large_and_e_limit():
    """DECISIONS C-06 e and C-07: the cap is on the input octets before any parse; 1,048,576
    octets of an otherwise valid document translate, 1,048,577 are CesmoInputTooLarge."""
    base = (SET / "upsert.json").read_bytes()
    at = base + b" " * (1_048_576 - len(base))
    assert len(adapter().to_cdm(at)) == 2
    over = at + b" "
    with pytest.raises(InputTooLarge) as raised:
        adapter().to_cdm(over)
    assert isinstance(raised.value, CesmoError) and raised.value.code == "E_LIMIT"
    assert str(raised.value).startswith(
        "E_LIMIT (root) cesmo_internal was handed 1048577 octets and declares "
        "max_input_bytes = 1048576."
    )
    assert len(str(raised.value)) <= 512
    # A dict is never re-serialised to be measured: a document whose JSON text would pass the
    # cap translates (DECISIONS C-06 e, the kit validator's re-serialisation cap not followed).
    wide = doc("upsert.json")
    wide["records"][0]["extensions"]["filler"] = ["x" * 4096] * 300
    assert len(json.dumps(wide).encode()) > 1_048_576
    assert len(adapter().to_cdm(wide)) == 2


def test_the_limit_refusals_survive_a_pickle_round_trip():
    """The conformance suite's worker pickles what a decoder raises."""
    for refusal in (
        module.CesmoInputTooLarge("E_LIMIT", "", "x"),
        module.CesmoInputTooDeep("E_LIMIT", "", "y"),
        CesmoError("E_SEMANTIC", "records/3/kind", "z"),
    ):
        back = pickle.loads(pickle.dumps(refusal))
        assert type(back) is type(refusal) and str(back) == str(refusal)
        assert (back.code, back.path, back.record_index) == (
            refusal.code,
            refusal.path,
            refusal.record_index,
        )


def test_to_cdm_runs_the_sdk_bounds_itself_and_is_not_wrapped_twice():
    assert CesmoInternalAdapter.to_cdm.__input_bounded__ is True
    assert not hasattr(CesmoInternalAdapter.to_cdm, "__wrapped__")


@pytest.mark.parametrize(
    "name", sorted(p.name for p in MALFORMED.iterdir() if p.name != "PROVENANCE.json")
)
def test_every_malformed_fixture_is_refused_with_the_code_its_name_states(name):
    """C14 and C15 through the fixtures; the octet ones as octets, the .json ones as dicts and
    again as their octets: one code, no objects."""
    source = harness.load_raw(MALFORMED / name)
    code = {
        "e_schema": "E_SCHEMA",
        "e_semantic": "E_SEMANTIC",
        "e_limit": "E_LIMIT",
        "e_mode": "E_MODE_MISMATCH",
        "e_unsupported": "E_UNSUPPORTED_MESSAGE",
    }
    want = next(v for k, v in code.items() if name.startswith(k))
    forms = [source] if isinstance(source, bytes) else [source, (MALFORMED / name).read_bytes()]
    for form in forms:
        with pytest.raises(CesmoError) as raised:
            adapter().to_cdm(form)
        assert raised.value.code == want


def test_the_malformed_table_names_every_file():
    readme = (SET / "README.md").read_text("utf-8")
    for p in MALFORMED.iterdir():
        if p.name != "PROVENANCE.json":
            assert f"| `{p.name}` |" in readme, p.name


# ------------------------------------------------------------------ detect and validate_source


def test_detect_reads_the_discriminator_and_never_validates():
    a = adapter()
    octets = (SET / "upsert.json").read_bytes()
    assert a.detect(octets) is True and a.detect(bytearray(octets)) is True
    assert a.detect(memoryview(octets)) is True and a.detect(octets.decode()) is True
    assert a.detect(doc("upsert.json")) is True
    assert (
        a.detect(json.loads((MALFORMED / "e_semantic_repeated_record_id.json").read_bytes()))
        is True
    )
    assert a.detect({"contract": "sc.cesmo.internal/2.0"}) is False and a.detect({}) is False
    assert (
        a.detect(b"\xff") is False and a.detect(b"not json") is False and a.detect(b"[1]") is False
    )
    assert a.detect(b"[" * 65 + b"]" * 65) is False
    assert a.detect(b" " * 1_048_577) is False
    assert a.detect(None) is None and a.detect([1]) is None and a.detect(7) is None


def test_validate_source_returns_the_diagnostics_and_never_raises():
    a = adapter()
    for name in EXPECTED_OBJECTS:
        assert a.validate_source(raw(name)) == []
    assert a.validate_source(raw("malformed/e_semantic_repeated_record_id.json")) == [
        "E_SEMANTIC records/1/record_id repeated record_id"
    ]
    assert a.validate_source("text") == ["E_SCHEMA (root) expected JSON octets or a dict"]
    assert a.validate_source(b" " * 1_048_577) == [
        "E_LIMIT (root) cesmo_internal was handed 1048577 octets and declares max_input_bytes = "
        "1048576. Refused before decode: the declaration is at capabilities.limits, its basis at "
        "capabilities.limits.declared_because['max_input_bytes'], and a parser that read this far "
        "would already have done the work the bound exists to prevent"
    ]
    # The codec alone, for a direct caller, states the same cap in its own words.
    assert module.codec.diagnostics(b" " * 1_048_577) == [
        "E_LIMIT (root) 1048577 octets past the cap of 1048576"
    ]
    cyclic = doc("upsert.json")
    cyclic["records"][0]["extensions"]["self"] = cyclic
    assert a.validate_source(cyclic) == ["E_LIMIT (root) more than 100000 JSON values"]
    with pytest.raises(CesmoError) as raised:
        a.to_cdm(cyclic)
    assert str(raised.value) == "E_LIMIT (root) more than 100000 JSON values"
    assert a.validate_source(raw("malformed/e_mode_mismatch_live.json")) == [
        "E_MODE_MISMATCH mode mode differs from the constructor's"
    ]
    assert (
        CesmoInternalAdapter(synthetic=False).validate_source(
            raw("malformed/e_mode_mismatch_live.json")
        )
        == []
    )


@pytest.mark.parametrize("form", ["dict", "bytes"])
def test_validate_source_names_every_missing_key_once(form):
    """Review R1-F1: several required keys missing at one place are each listed once, by their own
    path, keys compared as text; `to_cdm` refuses with the first. Written from the schema's
    `required` lists (kit `cesmo-internal-1.0.schema.json`)."""
    a = adapter()
    gutted = doc("upsert.json")
    for key in ("record_id", "kind", "revision"):
        del gutted["records"][0][key]
    for key in ("network_id", "identity_epoch"):
        del gutted["source"][key]
    del gutted["records"][0]["position"]["method"]
    del gutted["observed_at"], gutted["message_id"]
    cases = [
        (
            {},
            [
                "E_SCHEMA contract required",
                "E_SCHEMA message_id required",
                "E_SCHEMA mode required",
                "E_SCHEMA observed_at required",
                "E_SCHEMA records required",
                "E_SCHEMA source required",
            ],
        ),
        (
            gutted,
            [
                "E_SCHEMA message_id required",
                "E_SCHEMA observed_at required",
                "E_SCHEMA records/0/kind required",
                "E_SCHEMA records/0/position/method required",
                "E_SCHEMA records/0/record_id required",
                "E_SCHEMA records/0/revision required",
                "E_SCHEMA source/identity_epoch required",
                "E_SCHEMA source/network_id required",
            ],
        ),
    ]
    for document, expected in cases:
        source = document if form == "dict" else json.dumps(document).encode()
        assert a.validate_source(source) == expected
        with pytest.raises(CesmoError) as raised:
            a.to_cdm(source)
        assert str(raised.value) == expected[0]


# ------------------------------------------------------------------ the ledger (C39)


@pytest.mark.parametrize("name", sorted(n for n in EXPECTED_OBJECTS if n.endswith(".json")))
def test_the_ledger_has_no_lost_leaf_and_every_mutated_source_leaf_is_caught(name):
    """C39: every leaf of every fixture is MAPPED or RESIDUAL (0 LOST), and a source leaf
    changed after translation no longer matches the objects: each one is reported LOST."""
    source = doc(name)
    objects = dumps(adapter().to_cdm(source))
    ledger = lossless.ledger(source, objects, CesmoInternalAdapter.MAPPINGS)
    assert ledger.counts["LOST"] == 0 and ledger.total > 0
    for path, value in lossless.typed_leaves(source):
        mutated = copy.deepcopy(source)
        node = mutated
        for token in path[:-1]:
            node = node[token]
        if isinstance(value, bool):
            node[path[-1]] = not value
        elif isinstance(value, (int, float)):
            node[path[-1]] = value + 7
        elif isinstance(value, str):
            node[path[-1]] = value + "-MUTATED"
        else:  # an empty container is a leaf too
            node[path[-1]] = "MUTATED"
        lost = {
            e.source_path
            for e in lossless.ledger(mutated, objects, CesmoInternalAdapter.MAPPINGS).lost
        }
        assert lossless.render_path(path) in lost, (name, path)


# ------------------------------------------------------------------ the declaration


def test_registration_and_class_attributes():
    assert REGISTRY["cesmo_internal"] is CesmoInternalAdapter
    assert (
        CesmoInternalAdapter.name,
        CesmoInternalAdapter.version,
        CesmoInternalAdapter.direction,
        CesmoInternalAdapter.system,
    ) == ("cesmo_internal", "1.0.0", "ingest", SYSTEM)
    assert "Adapter #34." in module.__doc__.splitlines()[0]
    with pytest.raises(NotImplementedError):
        adapter().from_cdm([])


def test_metadata_values_field_by_field():
    """C38 and DECISIONS C-01/C-04: provisional internal profile, PROVISIONAL, OPEN, ingest, L3,
    structured residual, no profiles, evidence available from the release that attaches the
    records; the limits with bases."""
    m = CesmoInternalAdapter.metadata
    assert (m.id, m.name, m.adapter_version) == (
        "cesmo_internal",
        "SC CESMO Internal Exchange",
        "1.0.0",
    )
    assert (m.format.name, m.format.version) == ("SC CESMO Internal Exchange", "1.0.0")
    assert m.binding is WireBinding.PROVISIONAL_INTERNAL_PROFILE
    assert m.claim_status is ClaimStatus.PROVISIONAL and m.license_class is LicenseClass.OPEN
    assert m.direction is Direction.INGEST and m.maturity.level is MaturityLevel.L3
    assert m.residual is Residual.STRUCTURED and m.profiles == [] and m.constituents == []
    # The 3.8.0 release commit (2026-10-25) flips the evidence declaration it landed with.
    assert m.evidence.available is True and m.claim_external_system is None
    assert m.capabilities.unknown_fields is UnknownFields.NONE
    limits = m.capabilities.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects) == (1_048_576, 64, 2_001)
    assert (limits.max_decompressed_bytes, limits.max_parse_seconds) == (None, None)
    assert set(limits.absent_because) == {"max_decompressed_bytes", "max_parse_seconds"}
    for name in ("max_input_bytes", "max_depth", "max_objects"):
        basis = limits.declared_because[name]
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP
        assert "IMPLEMENTATION CAP" in basis.source and "§19" in basis.source
    assert "16" in limits.declared_because["max_depth"].source
    assert "2,001" in limits.declared_because["max_objects"].source
    assert "1,048,576" in limits.declared_because["max_input_bytes"].source
    ids_ = [lim.id for lim in m.limitations]
    assert ids_ == [
        "provisional-internal-profile",
        "stanag-4658-binding-blocked",
        "stateless-translation",
        "one-exchange-per-call",
        "octet-only-refusals",
        "contract-limits",
        "stricter-than-the-kit-validator",
        "emitter-entity-only",
        "asserted-position-only",
        "millisecond-rendering",
        "binary64-numbers",
        "synthetic-fixtures-only",
        "evidence-availability",
    ]
    text = {lim.id: lim.summary for lim in m.limitations}
    assert "provisional" in text["provisional-internal-profile"]
    assert "not STANAG 4658 interoperability" in text["stanag-4658-binding-blocked"]
    assert (
        "BLOCKED" in text["stanag-4658-binding-blocked"]
        and "N01-N12" in text["stanag-4658-binding-blocked"]
    )
    assert "gateway, is not in this repository" in text["stanag-4658-binding-blocked"]
    assert text["evidence-availability"] == (
        "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
        "untracked and unpackaged, CI generates the set on every run, and the release pipeline "
        "generates the records for every shipped adapter and attaches them to the GitHub "
        "Release of the version it publishes. `evidence.available` is true because every "
        "published distribution that carries this adapter has that Release, so its records "
        "are retrievable by a third party; it says nothing about what the wheel contains"
    )


def test_the_builder_regenerates_the_set_exactly(tmp_path):
    """`spec/build_fixtures.py --check`, run as the release check runs it: under -I -B, from a
    directory outside the tree."""
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(SET / "spec" / "build_fixtures.py"), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "CURRENT\n", "")


@pytest.mark.parametrize("name", sorted(EXPECTED_OBJECTS))
def test_every_fixture_projects_for_a_3_0_0_reader_under_the_compatibility_stamp(name):
    """`cdm_schema="3.0.0"` stamps the objects for the contract the kit's expected output was
    written against; nothing this adapter emits needs a CDM 3.1.0 or 3.2.0 member, so
    `projection.dump_for(obj, "3.0.0")` accepts every object and differs from the full dump only
    by the Event's null `validity`."""
    for obj in CesmoInternalAdapter(kit_clock, cdm_schema="3.0.0").to_cdm(raw(name)):
        assert obj.schema_version == "3.0.0"
        dumped = projection.dump_for(obj, "3.0.0")
        full = obj.model_dump(mode="json")
        if obj.object_kind == "event":
            assert full.pop("validity") is None
        assert dumped == full
