"""The synthetic provider wrapper (P02's runtime half, REQ031, REQ033): complete snapshots, a
partial coordinate kept aside, inherited component times never redated."""
import pathlib

import pytest

from helpers import stamp, uid
from synapse_cdm.adapters.link16_gateway import Link16GatewayAdapter
from synapse_link16_bridge.gateway import wrapper
from synapse_link16_bridge.gateway.wrapper import SyntheticWrapper

ENVELOPE = {"gateway_id": "synthetic-gateway-1", "tenant": "demo", "realm": "test-only",
            "synthetic": True, "origin_scope": "exercise-source-1",
            "reporter": "SIMULATED-REPORTER", "track_number": "TEST-0001", "incarnation": "0",
            "message_family": "J3.2", "native_profile": "SYNTHETIC-NO-NATIVE-CODEC",
            "domain": "AIR", "entity_kind": "PLATFORM",
            "security_context": "SYNTHETIC-UNCLASSIFIED", "time_basis": "EXERCISE",
            "time_evidence": "synthetic wrapper test clock"}


def snap(w, n, update):
    return w.snapshot(update, record_id=uid(n), session_id=uid(0), sequence=str(n),
                      received_at=stamp(0))


def adapter():
    return Link16GatewayAdapter(synthetic=True)


def test_every_update_is_a_complete_snapshot_of_28_keys():
    w = SyntheticWrapper(ENVELOPE)
    body = snap(w, 1, {"effective_at": stamp(0)})
    assert len(body) == 28 and body["position"] is None and body["kinematics"] is None
    assert adapter().validate_source(body) == []


def test_wrapper_uses_null_for_an_unavailable_fix_and_keeps_the_partial_coordinate():
    w = SyntheticWrapper(ENVELOPE)
    body = snap(w, 1, {"effective_at": stamp(0),
                       "position": {"observed_at": stamp(0), "lat_deg": 48.15}})
    assert body["position"] is None
    assert body["source_fields"] == {"partial_position": {"lat_deg": 48.15}}
    objects = adapter().to_cdm(body)
    assert [type(o).__name__ for o in objects] == ["Entity"]
    assert objects[0].position is None


def test_identity_only_update_does_not_redate_position():
    w = SyntheticWrapper(ENVELOPE)
    first = snap(w, 1, {"effective_at": stamp(0),
                        "position": {"observed_at": stamp(0), "lat_deg": 1.0, "lon_deg": 2.0,
                                     "method": "SENSOR"}})
    second = snap(w, 2, {"effective_at": stamp(5000), "identity": "HOSTILE"})
    assert second["position"] == first["position"]
    assert second["position"]["observed_at"] == stamp(0)
    assert second["identity"] == "HOSTILE" and second["effective_at"] == stamp(5000)
    objects = adapter().to_cdm(second)
    assert objects[1].samples[0].observed_at.isoformat() == "2026-10-04T12:00:00+00:00"


def test_a_component_without_a_resolvable_time_is_null():
    w = SyntheticWrapper(ENVELOPE)
    body = snap(w, 1, {"effective_at": stamp(0),
                       "position": {"lat_deg": 1.0, "lon_deg": 2.0},
                       "kinematics": {"speed_mps": 3.0, "course_deg": 4.0, "climb_mps": None}})
    assert body["position"] is None and body["kinematics"] is None


def test_an_explicit_null_clears_a_component_and_a_later_fix_restores_it():
    w = SyntheticWrapper(ENVELOPE)
    snap(w, 1, {"effective_at": stamp(0), "position": {"observed_at": stamp(0), "lat_deg": 0.0,
                                                       "lon_deg": 0.0, "method": "GNSS"}})
    assert snap(w, 2, {"effective_at": stamp(1000), "position": None})["position"] is None
    restored = snap(w, 3, {"effective_at": stamp(2000),
                           "position": {"observed_at": stamp(2000), "lat_deg": 0.0,
                                        "lon_deg": 0.0, "method": "GNSS"}})
    assert (restored["position"]["lat_deg"], restored["position"]["lon_deg"]) == (0.0, 0.0)


@pytest.mark.parametrize("envelope_change, update", [
    ({"synthetic": False}, None), ({"extra": 1}, None),
    (None, {"effective_at": stamp(0), "lat_deg": 1.0}), (None, {"identity": "HOSTILE"}),
])
def test_only_synthetic_envelopes_and_the_update_keys_are_accepted(envelope_change, update):
    with pytest.raises(ValueError):
        w = SyntheticWrapper(dict(ENVELOPE, **(envelope_change or {})))
        snap(w, 1, update)


def test_the_wrapper_never_reads_a_j_series_code():
    """REQ030: the family is a label the wrapper copies; nothing in it parses one."""
    source = pathlib.Path(wrapper.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#") and '"""' not in line)
    assert "J3" not in code and "J2" not in code and "J7" not in code
    w = SyntheticWrapper(dict(ENVELOPE, message_family="J7.0"))
    assert snap(w, 1, {"effective_at": stamp(0)})["message_family"] == "J7.0"
