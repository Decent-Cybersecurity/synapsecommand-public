"""Schema negotiation with the sink (REQ013, REQ140, P04's runtime half; X15)."""
import json

import pytest

from helpers import REPO, payload, report
from synapse_cdm.adapters.link16_gateway import T_COMPAT
from synapse_cdm.version import SCHEMA_VERSION
from synapse_link16_bridge.negotiate import Projection, adapter_schema, choose

FULL, COMPAT, FAILED = Projection.FULL, Projection.COMPAT_3_0, Projection.NEGOTIATION_FAILED
INSTALLED = tuple(int(part) for part in SCHEMA_VERSION.split("."))


@pytest.mark.parametrize("accepts, installed, expected", [
    (["3.1.0"], "3.1.0", FULL),
    (["3.0.0", "3.1.0"], "3.1.0", FULL),
    (["3.0.0"], "3.1.0", COMPAT),
    (["3.1.0"], "3.0.0", FAILED),
    (["3.0.0"], "3.0.0", COMPAT),
    (["3.0.0", "3.1.0"], "3.0.0", COMPAT),
    (["2.1.0"], "3.1.0", FAILED),
    (["2.1.0"], "3.0.0", FAILED),
    (["3.2.0"], "3.2.0", FULL),
    (["3.0.0", "3.2.0"], "3.1.0", COMPAT),
])
def test_choose_is_a_pure_function_of_the_sink_and_the_installed_version(accepts, installed,
                                                                         expected):
    assert choose(accepts, installed) is expected


@pytest.mark.parametrize("accepts, installed, expected", [
    ([], "3.0.0", FAILED),
    (["9.9.9"], "3.0.0", FAILED),
    (["3.0.1"], "3.0.0", FAILED),
    (["3.0.0"], "9.9.9", COMPAT),
    (["9.9.9", "3.1.0"], "3.0.0", FAILED),
    (["3.1.0"], "3.1.1", FAILED),
])
def test_choose_offers_only_a_contract_the_sink_names(accepts, installed, expected):
    """HYGIENE-5 (A2F, 2026-10-11): FULL only for the installed version the sink names, COMPAT
    only when it names 3.0.0; a version the sink does not name is never offered."""
    assert choose(accepts, installed) is expected


def test_the_adapter_keyword_of_each_projection():
    assert adapter_schema(FULL) is None
    assert adapter_schema(COMPAT) == "3.0.0"
    with pytest.raises(ValueError):
        adapter_schema(FAILED)


def test_compat_projection_for_a_300_sink_marks_position_not_projected(h):
    """A 3.0.0 sink: the SENSOR report yields an Entity with no position and no Track, flagged;
    the GNSS report keeps its position and Track; every object is stamped 3.0.0."""
    h.publish(report(1, base="air_sensor.json"))
    h.publish(report(2, base="air_hae_feet_gnss_hostile.json", track_number="GNSS-2"))
    h.publish(report(3, base="subsurface_unknown_method.json", track_number="SUB-3"))
    h.run()
    assert h.bridge.projection is COMPAT
    events = h.sink.events
    keys = sorted(k for k in events if events[k][0] == "cdm")
    assert keys == ["00000000-0000-4000-8000-000000000001:0",
                    "00000000-0000-4000-8000-000000000002:0",
                    "00000000-0000-4000-8000-000000000002:1",
                    "00000000-0000-4000-8000-000000000003:0"]
    sensor = payload(h.sink, "00000000-0000-4000-8000-000000000001:0")
    assert sensor["position"] is None and sensor["schema_version"] == "3.0.0"
    assert sensor["source"]["transformations"][-1] == T_COMPAT
    assert sensor["residual"]["data"]["report"]["position"]["method"] == "SENSOR"
    assert events["00000000-0000-4000-8000-000000000001:0"][2] == ("POSITION_NOT_PROJECTED_CDM3",)
    assert events["00000000-0000-4000-8000-000000000003:0"][2] == ("POSITION_NOT_PROJECTED_CDM3",)
    gnss = payload(h.sink, "00000000-0000-4000-8000-000000000002:0")
    track = payload(h.sink, "00000000-0000-4000-8000-000000000002:1")
    assert gnss["position"]["position_source"] == "GNSS" and gnss["schema_version"] == "3.0.0"
    assert track["schema_version"] == "3.0.0" and events[
        "00000000-0000-4000-8000-000000000002:0"][2] == ()


@pytest.mark.skipif(REPO is None, reason="repository-bound: the frozen 3.0.0 contract lives under "
                                         "tests/frozen/cdm/3.0.0/ in a checkout and is not shipped")
def test_compat_objects_validate_against_frozen_300(h):
    import jsonschema
    frozen = REPO / "tests" / "frozen" / "cdm" / "3.0.0"
    validators = {kind: jsonschema.Draft202012Validator(
        json.loads((frozen / f"{kind}.schema.json").read_text(encoding="utf-8")))
        for kind in ("entity", "track")}
    for n, base in enumerate(("air_sensor.json", "subsurface_unknown_method.json",
                              "air_hae_feet_gnss_hostile.json", "surface_zero.json",
                              "land_unknown_position.json"), start=1):
        h.publish(report(n, base=base, track_number=f"F-{n}"))
    h.run()
    checked = 0
    for key, (kind, octets, _flags) in h.sink.events.items():
        if kind != "cdm":
            continue
        document = json.loads(octets)
        errors = list(validators[document["object_kind"]].iter_errors(document))
        assert errors == [], (key, [e.message for e in errors][:3])
        checked += 1
    assert checked == 7


def test_no_common_version_blocks_ingest(make_harness):
    h = make_harness(accepts=("2.1.0",))
    h.publish(report(1))
    assert h.bridge.status == "BLOCKED"
    assert h.bridge.run_once() == {"fetched": False, "reason": "BLOCKED"}
    health = h.bridge.health()
    assert health["ready"] is False and "SCHEMA_NEGOTIATION_FAILED" in health["blocked_reasons"]
    assert h.bridge.startup_steps[-1] == "negotiate_schema"
    assert h.sink.events == {}


@pytest.mark.skipif(INSTALLED < (3, 1, 0), reason="version-pending until the 3.4.0 release commit "
                                                   "types SCHEMA_VERSION 3.1.0")
def test_full_projection_for_a_310_sink(make_harness):
    h = make_harness(accepts=(SCHEMA_VERSION,))
    h.publish(report(1, base="air_sensor.json"))
    h.run()
    assert h.bridge.projection is FULL
    entity = payload(h.sink, "00000000-0000-4000-8000-000000000001:0")
    assert entity["position"]["position_source"] == "SENSOR"
    assert entity["schema_version"] == SCHEMA_VERSION
    assert "00000000-0000-4000-8000-000000000001:1" in h.sink.events
