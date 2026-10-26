"""The contract projection (`synapse_cdm.projection`): its ledger, derived, and `dump_for`'s rule.

The ledger names what the current models carry that the frozen 3.0.0 contract does not. This
module derives the same facts from the bytes — `tests/frozen/cdm/3.0.0/*.schema.json` against the
published `schemas/*.schema.json`, top-level properties and enum members, kind by kind — and holds
the two equal, so a later MINOR that adds a field or a member the ledger does not name fails here
before a 3.0.0 reader is handed something it refuses. It also holds the derivation's two other
answers to what `dump_for` can handle: no definition both contracts share gained a property, and
every definition the current contract adds is reachable only through a ledger property.

Then `dump_for(obj, "3.0.0")` is driven case by case, every expectation a literal written by hand
(the dumped keys, the refusal paths, the messages), and over every golden in the tree: each object
is either accepted by the frozen 3.0.0 contract once dumped for it, or refused at exactly the
first position whose source is a CDM 3.1.0 member, found by a walk of the JSON written here.

REPO-BOUND: it reads `tests/frozen/cdm/3.0.0/`, the published `schemas/` and the fixture goldens
through the repository; the wheel carries none of them.
"""

import json
import pathlib

import pytest

import synapse_cdm
from synapse_cdm import projection
from synapse_cdm.enums import EventType, PositionSource
from synapse_cdm.models import KINDS, Entity, Event, PlanObject, Position, Track
from synapse_cdm.projection import LEDGERS, TARGETS, ProjectionRefused, dump_for
from synapse_cdm.schemas import validator_for

REPO = pathlib.Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "schemas"
FROZEN_3_0_0 = REPO / "tests" / "frozen" / "cdm" / "3.0.0"
FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures"

T0 = "2026-04-29T06:00:00.000Z"
T1 = "2026-04-29T07:00:00.000Z"
SOURCE = {"system": "TEST", "adapter": "test", "adapter_version": "1.0.0", "synthetic": True}
IDS = [{"system": "TEST", "external_id": "EX001"}]


def _schema(directory: pathlib.Path, kind: str) -> dict:
    return json.loads((directory / f"{kind}.schema.json").read_text(encoding="utf-8"))


def _frozen_errors(doc: dict) -> list[str]:
    validator = validator_for(_schema(FROZEN_3_0_0, doc["object_kind"]))
    return sorted(error.message for error in validator.iter_errors(doc))


# ============================================================ the ledger, derived from the bytes

FROZEN_KINDS = sorted(
    p.name.removesuffix(".schema.json") for p in FROZEN_3_0_0.glob("*.schema.json")
)


def _refs(node) -> set[str]:
    """Every `#/$defs/<name>` a schema fragment references, at any depth."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            found.add(ref.removeprefix("#/$defs/"))
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def _reachable(schema: dict, roots: set[str]) -> set[str]:
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(_refs(schema["$defs"][name]))
    return seen


def test_the_frozen_contract_has_the_four_kinds_and_the_ledger_covers_exactly_them():
    assert FROZEN_KINDS == ["entity", "event", "plan_object", "track"]
    assert sorted(LEDGERS["3.0.0"].properties) == FROZEN_KINDS
    assert TARGETS == ("3.0.0",)


@pytest.mark.parametrize("kind", FROZEN_KINDS)
def test_the_ledger_properties_are_the_top_level_properties_the_frozen_contract_lacks(kind):
    frozen, current = _schema(FROZEN_3_0_0, kind), _schema(PUBLISHED, kind)
    added = set(current["properties"]) - set(frozen["properties"])
    assert added == set(LEDGERS["3.0.0"].properties[kind])
    assert set(frozen["properties"]) <= set(current["properties"])
    assert frozen["additionalProperties"] is False and current["additionalProperties"] is False


@pytest.mark.parametrize("kind", FROZEN_KINDS)
def test_no_shared_definition_gained_a_property_and_new_ones_hang_off_ledger_properties(kind):
    """`dump_for` removes top-level keys only; a property added inside a definition both
    contracts share would need a nested projection, and must fail here first."""
    frozen, current = _schema(FROZEN_3_0_0, kind), _schema(PUBLISHED, kind)
    shared = set(frozen["$defs"]) & set(current["$defs"])
    for name in sorted(shared):
        assert set(current["$defs"][name].get("properties", {})) == set(
            frozen["$defs"][name].get("properties", {})
        ), name
    ledger = set(LEDGERS["3.0.0"].properties[kind])
    without = {k: v for k, v in current["properties"].items() if k not in ledger}
    assert _reachable(current, _refs(without)) <= set(frozen["$defs"])


def _members(schema: dict) -> set[tuple[str, str]]:
    return {
        (name, member) for name, node in schema["$defs"].items() for member in node.get("enum", [])
    }


def test_the_ledger_members_are_every_enum_member_the_frozen_contract_lacks():
    added: set[tuple[str, str]] = set()
    for kind in FROZEN_KINDS:
        frozen, current = _schema(FROZEN_3_0_0, kind), _schema(PUBLISHED, kind)
        assert _members(frozen) <= _members(current), kind
        added |= _members(current) - _members(frozen)
    ledger = {(cls.__name__, value) for cls, value in LEDGERS["3.0.0"].members}
    assert added == ledger


def test_the_ledger_reads_as_written_with_the_version_that_added_each_entry():
    ledger = LEDGERS["3.0.0"]
    assert {kind: dict(names) for kind, names in ledger.properties.items()} == {
        "entity": {},
        "event": {"validity": "3.2.0"},
        "plan_object": {},
        "track": {"attributes": "3.2.0"},
    }
    assert dict(ledger.members) == {
        (PositionSource, "SENSOR"): "3.1.0",
        (PositionSource, "UNKNOWN"): "3.1.0",
        (EventType, "ENVIRONMENTAL_OBSERVATION"): "3.2.0",
    }


def test_the_ledger_cannot_be_edited_at_run_time():
    with pytest.raises(TypeError):
        LEDGERS["3.0.0"].properties["event"]["observed_at"] = "3.2.0"
    with pytest.raises(TypeError):
        LEDGERS["3.1.0"] = LEDGERS["3.0.0"]


# ============================================================ dump_for, case by case


def event(**overrides) -> Event:
    doc = {
        "object_kind": "event",
        "source": SOURCE,
        "source_ids": IDS,
        "event_id": "6f1c2a52-0b7e-5e0a-9a36-1b1f4c3c2d10",
        "event_type": "DETECTION",
        "severity": "INFO",
        "observed_at": T1,
        "received_at": T1,
        "payload": {"note": "SENSOR", "position_source": "UNKNOWN"},
    }
    doc.update(overrides)
    return Event.model_validate_json(json.dumps(doc))


def track(*sources: str, **overrides) -> Track:
    samples = [
        {"observed_at": T0, "position": {"lat": 57.0, "lon": 21.0, "position_source": source}}
        for source in sources
    ]
    doc = {
        "object_kind": "track",
        "source": SOURCE,
        "source_ids": IDS,
        "track_id": "0d3e7b8a-4c1f-5a6e-8b2d-9e0f1a2b3c4d",
        "entity_id": "1a2b3c4d-5e6f-5a7b-8c9d-0e1f2a3b4c5d",
        "samples": samples,
    }
    doc.update(overrides)
    return Track.model_validate_json(json.dumps(doc))


def entity(position_source: str | None, **overrides) -> Entity:
    doc = {
        "object_kind": "entity",
        "source": SOURCE,
        "source_ids": IDS,
        "entity_id": "1a2b3c4d-5e6f-5a7b-8c9d-0e1f2a3b4c5d",
        "entity_type": "UNKNOWN",
        "affiliation": "UNKNOWN",
        "valid_from": T0,
        "position": None
        if position_source is None
        else {"lat": 57.0, "lon": 21.0, "position_source": position_source},
    }
    doc.update(overrides)
    return Entity.model_validate_json(json.dumps(doc))


def plan_object(*sources: str) -> PlanObject:
    waypoints = [
        {"sequence": n, "position": {"lat": 57.0 + n / 10, "lon": 21.0, "position_source": source}}
        for n, source in enumerate(sources)
    ]
    doc = {
        "object_kind": "plan_object",
        "source": SOURCE,
        "source_ids": IDS,
        "object_id": "2b3c4d5e-6f7a-5b8c-9d0e-1f2a3b4c5d6e",
        "object_type": "ROUTE",
        "geometry": {"type": "LineString", "coordinates": [[21.0, 57.0], [21.0, 57.1]]},
        "route": {"waypoints": waypoints},
    }
    return PlanObject.model_validate_json(json.dumps(doc))


def test_a_null_validity_is_removed_and_the_event_is_what_3_0_0_reads():
    obj = event()
    dumped = dump_for(obj, "3.0.0")
    full = obj.model_dump(mode="json")
    assert "validity" not in dumped and full["validity"] is None
    assert sorted(set(full) - set(dumped)) == ["validity"]
    assert {k: v for k, v in full.items() if k != "validity"} == dumped
    # The payload's strings "SENSOR" and "UNKNOWN" are text, not members, and ride through.
    assert dumped["payload"] == {"note": "SENSOR", "position_source": "UNKNOWN"}
    assert _frozen_errors(dumped) == []
    # The full projection is untouched: the model still dumps the key.
    assert "validity" in obj.model_dump(mode="json")


def test_a_null_attributes_is_removed_and_the_track_is_what_3_0_0_reads():
    obj = track("GNSS", "ESTIMATED")
    dumped = dump_for(obj, "3.0.0")
    assert sorted(set(obj.model_dump(mode="json")) - set(dumped)) == ["attributes"]
    assert [s["position"]["position_source"] for s in dumped["samples"]] == ["GNSS", "ESTIMATED"]
    assert _frozen_errors(dumped) == []


def test_an_entity_and_a_plan_object_dump_exactly_as_the_model_does():
    """No property was added to either kind, and `Affiliation.UNKNOWN`/`EntityType.UNKNOWN` are
    3.0.0 members: the enum class decides, not the text."""
    for obj in (entity("GNSS"), entity(None), plan_object("GNSS", "MANUAL")):
        dumped = dump_for(obj, "3.0.0")
        assert dumped == obj.model_dump(mode="json")
        assert _frozen_errors(dumped) == []
    assert dump_for(entity("GNSS"), "3.0.0")["affiliation"] == "UNKNOWN"
    assert dump_for(entity("GNSS"), "3.0.0")["entity_type"] == "UNKNOWN"


REFUSALS = [
    pytest.param(
        lambda: event(validity={"effective": {"start": T0, "end": T1}}),
        "validity",
        "3.2.0",
        "validity: a populated property added in CDM 3.2.0, which the 3.0.0 contract cannot state",
        id="validity-populated",
    ),
    pytest.param(
        lambda: event(validity={}),
        "validity",
        "3.2.0",
        "validity: a populated property added in CDM 3.2.0, which the 3.0.0 contract cannot state",
        id="validity-empty-block",
    ),
    pytest.param(
        lambda: event(event_type="ENVIRONMENTAL_OBSERVATION"),
        "event_type",
        "3.2.0",
        "event_type: a member of EventType added in CDM 3.2.0, which the 3.0.0 contract "
        "cannot state",
        id="member-environmental-observation",
    ),
    pytest.param(
        lambda: track(
            "GNSS",
            attributes={"completeness": {"carried_samples": 1, "completeness_basis": "counted"}},
        ),
        "attributes",
        "3.2.0",
        "attributes: a populated property added in CDM 3.2.0, which the 3.0.0 "
        "contract cannot state",
        id="attributes-populated",
    ),
    pytest.param(
        lambda: track("GNSS", "SENSOR", "UNKNOWN"),
        "samples[1].position.position_source",
        "3.1.0",
        "samples[1].position.position_source: a member of PositionSource added in CDM "
        "3.1.0, which the 3.0.0 contract cannot state",
        id="track-second-sample-sensor",
    ),
    pytest.param(
        lambda: entity("UNKNOWN"),
        "position.position_source",
        "3.1.0",
        "position.position_source: a member of PositionSource added in CDM 3.1.0, which "
        "the 3.0.0 contract cannot state",
        id="entity-position-unknown",
    ),
    pytest.param(
        lambda: plan_object("MANUAL", "GNSS", "SENSOR"),
        "route.waypoints[2].position.position_source",
        "3.1.0",
        "route.waypoints[2].position.position_source: a member of PositionSource added in "
        "CDM 3.1.0, which the 3.0.0 contract cannot state",
        id="waypoint-sensor",
    ),
]


@pytest.mark.parametrize("build, path, since, message", REFUSALS)
def test_what_3_0_0_cannot_state_is_refused_by_path_and_never_quoted(build, path, since, message):
    obj = build()
    with pytest.raises(ProjectionRefused) as caught:
        dump_for(obj, "3.0.0")
    refusal = caught.value
    assert isinstance(refusal, ValueError)
    assert (refusal.target, refusal.path, refusal.since, str(refusal)) == (
        "3.0.0",
        path,
        since,
        message,
    )
    for value in (T0, T1, "counted", "SENSOR", "ENVIRONMENTAL_OBSERVATION"):
        assert value not in str(refusal)


def test_an_assignment_after_construction_is_judged_too():
    obj = track("GNSS")
    obj.samples[0].position = Position(lat=57.0, lon=21.0, position_source=PositionSource.SENSOR)
    with pytest.raises(ProjectionRefused, match=r"^samples\[0\]\.position\.position_source: "):
        dump_for(obj, "3.0.0")


# Corrected 2026-10-16, the 3.5.0 release commit (the replay review's F-02): "2.1.0" and "3.2.0"
# were cases of this test, and both are frozen contracts on this tree, so they moved to the
# frozen-without-a-ledger test below; "3.3.0" is a CDM number no contract has.
@pytest.mark.parametrize("target", ["3.3.0", "", None, b"3.0.0", 3])
def test_a_target_that_is_not_a_frozen_contract_is_refused(target):
    with pytest.raises(ValueError) as caught:
        dump_for(event(), target)
    assert str(caught.value) == "dump_for: the target must be one of ['3.0.0']"
    assert not isinstance(caught.value, ProjectionRefused)


# Corrected 2026-10-16, at the replay onto `v3.4.0`: 3.1.0 is frozen on this tree, so the case is
# a contract with no ledger rather than one that is not frozen. The same day the 3.5.0 release
# commit froze 3.2.0, the current contract, and "2.1.0" (frozen since 2026-09-20) joined the case.
@pytest.mark.parametrize("target", ["2.1.0", "3.1.0", "3.2.0"])
def test_a_frozen_contract_with_no_ledger_is_refused_as_a_target(target):
    assert (REPO / "tests" / "frozen" / "cdm" / target).is_dir()
    assert target not in LEDGERS and TARGETS == ("3.0.0",)
    with pytest.raises(ValueError) as caught:
        dump_for(event(), target)
    assert str(caught.value) == "dump_for: the target must be one of ['3.0.0']"
    assert not isinstance(caught.value, ProjectionRefused)


@pytest.mark.parametrize(
    "obj",
    [{"object_kind": "event"}, None, Position(lat=57.0, lon=21.0, position_source="GNSS")],
    ids=["dict", "none", "position"],
)
def test_only_a_cdm_object_is_projected(obj):
    with pytest.raises(TypeError) as caught:
        dump_for(obj, "3.0.0")
    assert str(caught.value) == "dump_for: obj must be a CDM Entity, Event, PlanObject or Track"


def test_the_module_is_reached_by_its_own_name():
    """Public on the module, like `harness.run` and `schemas.generate`: the package `__init__`
    exports nothing new for it."""
    assert projection.dump_for is dump_for
    for name in ("dump_for", "ProjectionRefused", "LEDGERS", "TARGETS"):
        assert name not in synapse_cdm.__all__


# ============================================================ every golden in the tree

GOLDENS = sorted(FIXTURES.glob("**/golden/*.cdm.json"))

#: Where a Position sits, per kind: the three model fields typed `Position`
#: (`Entity.position`, `TrackSample.position`, `Waypoint.position`).
_POSITION_PATHS = {
    "entity": lambda d: [("position", d.get("position"))],
    "track": lambda d: [
        (f"samples[{i}].position", s["position"]) for i, s in enumerate(d["samples"])
    ],
    "plan_object": lambda d: [
        (f"route.waypoints[{i}].position", w["position"])
        for i, w in enumerate((d.get("route") or {}).get("waypoints", []))
    ],
    "event": lambda d: [],
}


def _first_3_1_0_source(doc: dict) -> str | None:
    for path, position in _POSITION_PATHS[doc["object_kind"]](doc):
        if position is not None and position["position_source"] in ("SENSOR", "UNKNOWN"):
            return f"{path}.position_source"
    return None


#: The two top-level properties CDM 3.2.0 added, by kind, written out (2026-10-15, the
#: `readsb_trace` landing): the first golden that POPULATES one is a Track whose `attributes` carry
#: the completeness block. `dump_for` judges these before any member (D-R0-12), so a populated one
#: is the refusal, whatever the positions hold.
_POPULATED_3_2_0 = {"event": "validity", "track": "attributes"}


def _expected_refusal(doc: dict) -> tuple[str, str] | None:
    """(path, since) of the refusal `dump_for(…, "3.0.0")` must raise, or None for acceptance."""
    name = _POPULATED_3_2_0.get(doc["object_kind"])
    if name is not None and doc.get(name) is not None:
        return name, "3.2.0"
    source = _first_3_1_0_source(doc)
    return (source, "3.1.0") if source is not None else None


#: The `readsb_trace` fixtures (2026-10-15): each Track golden carries `attributes.completeness`.
_READSB_TRACE_FIXTURES = (
    "airborne_adsb_2022_form",
    "equal_instants_and_db_flags",
    "every_flag_bit",
    "ground_heading_slot",
    "midnight_fragment_day_one",
    "midnight_fragment_day_two",
    "mlat_positions",
    "nonicao_address",
    "null_altitude_and_speed",
    "pre2022_nine_elements",
    "receiver_id_fifteen_elements",
    "reference_not_midnight",
    "tisb_positions",
)

#: The `nexrad2` fixtures (2026-10-15) and how many sweep Events each golden holds: every Event
#: states `validity.effective`, a populated 3.2.0 property; the site Entity is accepted.
_NEXRAD2_SWEEPS = {
    "all_moments_one_elevation": 1,
    "coded_gates_and_bad_radial": 1,
    "one_sweep_across_two_records": 1,
    "sails_repeated_lowest_angle": 3,
    "two_elevations_two_records": 2,
}


#: The three station-text adapters (2026-10-15) and how many Events each golden holds, one a row,
#: sample or line: every Event states `validity.effective`; each station's Entity is accepted.
#: `coops_csv`'s JSON-form fixture is a `.json` payload with no twin, so it has one golden.
_STATION_TEXT_EVENTS = {
    "ndbc_stdmet": {
        "before_2007_no_units_line": 2,
        "historical_nine_runs": 3,
        "realtime_newest_first": 3,
        "two_digit_year_1998": 2,
    },
    "coops_csv": {
        "water_level_below_datum_flagged": 3,
        "water_level_preliminary": 3,
        "water_level_verified": 2,
    },
    "airnow_hourly": {
        "hourly_aqobs_fact_sheet_date_blank_unit": 1,
        "hourly_aqobs_two_sites": 2,
        "hourly_data_site_without_position": 2,
        "hourly_data_two_sites": 4,
    },
}

#: The `grib2` fixtures (2026-10-17) and how many field Events each golden holds: every Event states
#: `validity.effective`, a populated 3.2.0 property; one message of two fields, twelve of one.
_GRIB2_FIELDS = {
    "bitmap_simple_packing": 1,
    "complex_order_1": 1,
    "complex_order_1_primary_and_secondary_missing": 1,
    "complex_order_2_missing": 1,
    "complex_order_2_with_bitmap": 1,
    "jpeg2000_reference_form": 1,
    "lambert_conformal_simple": 1,
    "mrms_style_png_sentinels": 1,
    "png_16_bit": 1,
    "png_8_bit": 1,
    "simple_packing_latlon": 1,
    "two_fields_one_message": 2,
    "zero_width_accumulation": 1,
}

#: The `cog` fixtures whose golden holds an Event (2026-10-17): the two band files that state a
#: sensing time, each Event stating `validity.effective`; the other eight are PlanObjects, whose
#: `validity` predates 3.0.0 and is null here.
_COG_EVENTS = ("ecostress_shaped_lst_tiled", "hls_shaped_band_cog")

#: The `iem_n0q` fixtures (2026-10-17): each golden holds one Event stating `validity.effective`,
#: the archive slot as an instant.
#: The `barentswatch_hais` fixtures (2026-10-22): each golden holds one Track with populated 3.2.0
#: `attributes` (its completeness block), the `readsb_trace` shape.
_BARENTSWATCH_HAIS_FIXTURES = (
    "duplicate_instants_unordered",
    "nulls_and_sentinels",
    "single_point",
    "underway_newest_first",
    "unknown_extra_key",
)

#: The `frost_observations` fixtures (2026-10-22): the Events of each golden, every one stating
#: `validity.effective` (an instant, or a Case 2.2 daily period).
_FROST_OBSERVATIONS_EVENTS = {
    "midnight_mixed_daily": 5,
    "observation_without_unit": 1,
    "quality_codes_no_level_unknown_keys": 3,
    "station_missing_parallel_sensors": 4,
    "two_stations_hourly": 4,
}

_IEM_N0Q_EVENTS = (
    "all_missing_no_gentime",
    "corner_cells_paeth_average",
    "echo_patch_split_idat",
    "ramp_ends_every_filter_type",
)


def test_the_golden_census_is_what_the_tree_holds():
    """809 golden files (631 at R0, the 26 `readsb_trace` wrote on 2026-10-15, the 10 `nexrad2`
    wrote the same day, the 23 of the three station-text adapters the same day: 8 `ndbc_stdmet`,
    7 `coops_csv`, 8 `airnow_hourly`, the 26 `grib2` wrote on 2026-10-17, the 20 `cog` wrote the
    same day, the 8 `iem_n0q` wrote the same day, the 10 `barentswatch_hais` and the 10
    `frost_observations` wrote on 2026-10-22, the 12 `cesmo_internal` wrote on 2026-10-24, whose
    Events carry `"validity": null` and so reach no refusal, the 9 of the three STANAG 4559
    translators, 3 each, wrote on 2026-10-24, whose Events state no 3.2.0 member and so reach no
    refusal, and the 24 `stanag4545` wrote on 2026-10-25 (22 at the top level, 2 for its context
    vector, none of whose objects reaches the refusal branch: the product is an Entity with no
    position and each footprint a PlanObject with no route); the refusal branch
    below is reached by six objects at a 3.1.0
    position source, an Entity and its Track in each of three `link16_gateway` goldens (counted
    with grep when this was written), by the 26 `readsb_trace` Tracks at their populated 3.2.0
    `attributes`, one in each of its goldens, by the 16 `nexrad2` sweep Events at their populated
    3.2.0 `validity`, one to three in each of its goldens, by the 56 station-text Events at
    theirs, one a row, sample or line, by the 28 `grib2` field Events at theirs, one a field, by
    the 4 `cog` Events at theirs, one in each golden of its two sensed band files, and by the 8
    `iem_n0q` Events at theirs, one in each of its goldens, by the 10 `barentswatch_hais` Tracks at
    their populated 3.2.0 `attributes`, one in each of its goldens, and by the 34 `frost_observations`
    Events at their 3.2.0 `validity`, one to five in each of its goldens."""
    assert len(GOLDENS) == 809
    refused = []
    for path in GOLDENS:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for item in doc if isinstance(doc, list) else [doc]:
            expected = _expected_refusal(item)
            if expected is not None:
                refused.append((str(path.relative_to(FIXTURES)), item["object_kind"], expected))
    readsb = [
        (f"readsb_trace/golden/{name}{suffix}", "track", ("attributes", "3.2.0"))
        for name in _READSB_TRACE_FIXTURES
        for suffix in (".cdm.json", ".parsed.cdm.json")
    ]
    nexrad2 = [
        (f"nexrad2/golden/{name}{suffix}", "event", ("validity", "3.2.0"))
        for name, sweeps in _NEXRAD2_SWEEPS.items()
        for suffix in (".cdm.json", ".parsed.cdm.json")
        for _ in range(sweeps)
    ]
    assert len(nexrad2) == 16
    station_text = [
        (f"{adapter}/golden/{name}{suffix}", "event", ("validity", "3.2.0"))
        for adapter, cases in _STATION_TEXT_EVENTS.items()
        for name, events in cases.items()
        for suffix in (".cdm.json", ".parsed.cdm.json")
        for _ in range(events)
    ] + [("coops_csv/golden/water_level_json_form.cdm.json", "event", ("validity", "3.2.0"))] * 2
    assert len(station_text) == 56
    grib2 = [
        (f"grib2/golden/{name}{suffix}", "event", ("validity", "3.2.0"))
        for name, fields in _GRIB2_FIELDS.items()
        for suffix in (".cdm.json", ".parsed.cdm.json")
        for _ in range(fields)
    ]
    assert len(grib2) == 28
    cog = [
        (f"cog/golden/{name}{suffix}", "event", ("validity", "3.2.0"))
        for name in _COG_EVENTS
        for suffix in (".cdm.json", ".parsed.cdm.json")
    ]
    assert len(cog) == 4
    iem_n0q = [
        (f"iem_n0q/golden/{name}{suffix}", "event", ("validity", "3.2.0"))
        for name in _IEM_N0Q_EVENTS
        for suffix in (".cdm.json", ".parsed.cdm.json")
    ]
    assert len(iem_n0q) == 8
    barentswatch_hais = [
        (f"barentswatch_hais/golden/{name}{suffix}", "track", ("attributes", "3.2.0"))
        for name in _BARENTSWATCH_HAIS_FIXTURES
        for suffix in (".cdm.json", ".parsed.cdm.json")
    ]
    assert len(barentswatch_hais) == 10
    frost_observations = [
        (f"frost_observations/golden/{name}{suffix}", "event", ("validity", "3.2.0"))
        for name, events in _FROST_OBSERVATIONS_EVENTS.items()
        for suffix in (".cdm.json", ".parsed.cdm.json")
        for _ in range(events)
    ]
    assert len(frost_observations) == 34
    assert sorted(refused) == sorted(
        [
            (
                "link16_gateway/golden/air_sensor.cdm.json",
                "entity",
                ("position.position_source", "3.1.0"),
            ),
            (
                "link16_gateway/golden/air_sensor.cdm.json",
                "track",
                ("samples[0].position.position_source", "3.1.0"),
            ),
            (
                "link16_gateway/golden/air_sensor_octets.cdm.json",
                "entity",
                ("position.position_source", "3.1.0"),
            ),
            (
                "link16_gateway/golden/air_sensor_octets.cdm.json",
                "track",
                ("samples[0].position.position_source", "3.1.0"),
            ),
            (
                "link16_gateway/golden/subsurface_unknown_method.cdm.json",
                "entity",
                ("position.position_source", "3.1.0"),
            ),
            (
                "link16_gateway/golden/subsurface_unknown_method.cdm.json",
                "track",
                ("samples[0].position.position_source", "3.1.0"),
            ),
        ]
        + readsb
        + nexrad2
        + station_text
        + grib2
        + cog
        + iem_n0q
        + barentswatch_hais
        + frost_observations
    )


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_every_golden_object_is_accepted_by_3_0_0_or_refused_at_its_first_3_1_0_position(path):
    """Accepted, or refused exactly where `_expected_refusal` says: at a populated 3.2.0 property
    (added 2026-10-15, when the first golden populated one) or at the first 3.1.0 position."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    for index, item in enumerate(doc if isinstance(doc, list) else [doc]):
        obj = KINDS[item["object_kind"]].model_validate_json(json.dumps(item))
        expected = _expected_refusal(item)
        if expected is None:
            dumped = dump_for(obj, "3.0.0")
            assert _frozen_errors(dumped) == [], (index, item["object_kind"])
            ledger = LEDGERS["3.0.0"].properties[item["object_kind"]]
            assert {k: v for k, v in item.items() if k not in ledger} == dumped, index
        else:
            with pytest.raises(ProjectionRefused) as caught:
                dump_for(obj, "3.0.0")
            assert (caught.value.path, caught.value.since) == expected, index
