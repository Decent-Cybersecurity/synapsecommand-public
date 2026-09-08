"""The never-drop rule. If these tests are weak, the rule is decoration."""
from synapse_cdm import lossless


def test_a_dropped_value_is_reported():
    raw = {"kept": "alpha", "dropped": "bravo"}
    missing = lossless.unrepresented(raw, [{"field": "alpha"}])
    assert missing == {"dropped": "bravo"}


def test_a_renamed_key_is_not_a_drop():
    """Renaming is what translation IS — comparing keys would flag every correct adapter."""
    assert lossless.unrepresented({"band": "L1"}, [{"frequency_band": "L1"}]) == {}


def test_numeric_forms_of_the_same_measurement_match():
    for value, rendered in ((71.5, "71.50"), (2500, 2500.0), (4, "4"), (1e3, 1000.0)):
        assert lossless.unrepresented({"v": value}, [{"v": rendered}]) == {}


def test_booleans_are_not_treated_as_uninteresting():
    """A dropped `"estimated": true` is exactly the loss this check exists to catch."""
    assert lossless.unrepresented({"estimated": True}, [{"other": 1}]) == {"estimated": True}
    assert lossless.unrepresented({"estimated": True}, [{"flag": "true"}]) == {}


def test_absent_values_are_not_losses():
    assert lossless.unrepresented({"a": None, "b": "", "c": [], "d": {}}, [{}]) == {}


def test_a_declared_transform_exempts_a_subtree():
    raw = {"vendor": {"firmware": "2.11.4", "nested": {"deep": 7}}}
    assert lossless.unrepresented(raw, [{}]) != {}
    assert lossless.unrepresented(raw, [{}], {"vendor": "handled elsewhere"}) == {}


def test_a_parked_key_name_counts_as_presence():
    """`attributes.receiver_count: 3` keeps the NAME as evidence even for a common number."""
    assert lossless.unrepresented({"receiver_count": 3},
                                  [{"attributes": {"receiver_count": 3}}]) == {}


def test_residual_preserves_lists_and_nesting():
    """The defect the first golden review caught: lists must not become key[0], key[1]."""
    raw = {"consumed": 1, "keep": {"list": ["GPS", "GALILEO"], "deep": {"x": 2}}}
    assert lossless.residual(raw, ["consumed"]) == {
        "keep": {"list": ["GPS", "GALILEO"], "deep": {"x": 2}}
    }


def test_residual_drops_husks_of_fully_consumed_blocks():
    raw = {"emitter": {"lat": 1.0, "lon": 2.0}, "other": 3}
    assert lossless.residual(raw, ["emitter.lat", "emitter.lon"]) == {"other": 3}


def test_residual_keeps_an_empty_block_the_source_actually_sent():
    """'The source sent an empty object here' is information, not noise."""
    assert lossless.residual({"detail": {}}, ["other"]) == {"detail": {}}


def test_residual_addresses_one_list_element():
    assert lossless.residual({"l": ["a", "b"]}, ["l[0]"]) == {"l": ["b"]}


def test_leaves_walks_lists_and_dicts():
    assert lossless.leaves({"a": [{"b": 1}]}) == {"a[0].b": 1}


# --- P3: the structured residual container (§28) -----------------------------------------------

import uuid

from synapse_cdm.adapter import Adapter, discover
from synapse_cdm.enums import Affiliation, EntityType
from synapse_cdm.manifest import FormatRef, Residual as ResidualStance
from synapse_cdm.models import Entity
from tests import probe_metadata


def _double(stance="legacy", format_name="a test double's format"):
    """An adapter class built for one assertion.

    Built with `type()` rather than a `class` statement because the contract is enforced at
    CLASS-DEFINITION time (`adapter.py:__init_subclass__`), so the identity attributes have to be
    in the namespace before the class exists — assigning them afterwards is too late, which is
    the whole point of that enforcement and is worth meeting rather than working around.
    """
    name = f"test_residual_{stance}_{uuid.uuid4().hex[:8]}"

    def to_cdm(self, raw):
        return [Entity(source=self.source_ref(),
                       source_ids=[{"system": "TEST", "external_id": "E-1"}],
                       entity_id=uuid.uuid4(), entity_type=EntityType.UNKNOWN,
                       affiliation=Affiliation.UNKNOWN, valid_from=self.now())]

    return type(f"_Double_{name}", (Adapter,), {
        "name": name, "version": "0.1.0", "direction": "ingest", "system": "TEST",
        "metadata": probe_metadata(name, residual=ResidualStance(stance),
                                   format=FormatRef(name=format_name, version="0")),
        "to_cdm": to_cdm,
    })


def test_the_residual_block_takes_its_namespace_from_the_adapters_own_declaration():
    """§28's origin rule, and the namespace is READ rather than passed in."""
    adapter = _double(format_name="PNTMAP GNSS interference alert")(synthetic=True)
    block = lossless.residual_block(adapter, {"kept": 1, "vendor": {"fw": "3.1"}}, ["kept"])
    assert block.namespace == "PNTMAP GNSS interference alert"
    assert block.data == {"vendor": {"fw": "3.1"}}


def test_the_residual_block_preserves_structure_and_not_dotted_leaves():
    """The defect `residual()`'s own docstring records, asserted through the new container."""
    adapter = _double()(synthetic=True)
    block = lossless.residual_block(
        adapter, {"consumed": 1, "affected_constellations": ["GPS", "GALILEO"]}, ["consumed"])
    assert block.data == {"affected_constellations": ["GPS", "GALILEO"]}


def test_an_empty_residual_is_still_a_block_so_the_caller_decides_whether_to_attach_it():
    adapter = _double()(synthetic=True)
    assert lossless.residual_block(adapter, {"consumed": 1}, ["consumed"]).data == {}


# --- the rule that makes "exactly one way" true for Part 2 --------------------------------------


def structured_residual_offences(adapter, objects):
    """Objects from a `residual: structured` adapter that still park in the legacy bag.

    THE RULE, in one function so the sweep below and the both-ways proof above are the same
    check. ARCHITECTURE.md §5 rules that the fourteen adapters shipped in Part 1 keep parking
    leftovers in `attributes.source_extras` / `payload.source_extras` and declare
    `residual: legacy`; every Part 2 adapter declares `residual: structured` and uses
    `Residual`. What must not happen is BOTH, because then one leftover is filed in two places
    and a consumer reading either is right — which is "exactly one way" being false on the first
    day of Part 2.

    Returns an empty list for a `legacy` adapter by construction: the rule is about what a
    STRUCTURED declaration promises, and applying it to the fourteen would contradict §5.
    """
    if adapter.metadata.residual is not ResidualStance.STRUCTURED:
        return []
    offending = []
    for index, obj in enumerate(objects):
        dumped = obj.model_dump(mode="json")
        for bag in ("attributes", "payload"):
            parked = (dumped.get(bag) or {}).get("source_extras")
            if parked:
                offending.append(f"object {index} [{dumped['object_kind']}]: {bag}."
                                 f"source_extras still carries {sorted(parked)}")
    return offending


def test_the_structured_rule_fires_on_a_structured_adapter_and_not_on_a_legacy_one():
    """Both ways, on classes defined here — the fourteen all declare `legacy`, so a sweep over
    them alone would assert nothing at all and would keep passing after the rule broke."""
    raw = {"consumed": 1, "vendor": {"fw": "3.1"}}

    def _objects_parking_in_attributes(stance):
        adapter = _double(stance)(synthetic=True)
        objects = adapter.to_cdm(raw)
        objects[0].attributes = {"source_extras": lossless.residual(raw, ["consumed"])}
        return adapter, objects

    legacy, legacy_objects = _objects_parking_in_attributes("legacy")
    assert structured_residual_offences(legacy, legacy_objects) == [], (
        "the legacy stance IS this parking (ARCHITECTURE.md §5); the rule must not touch it")

    structured, structured_objects = _objects_parking_in_attributes("structured")
    assert structured_residual_offences(structured, structured_objects) == [
        "object 0 [entity]: attributes.source_extras still carries ['vendor']"]


def test_a_structured_adapter_using_the_container_has_no_offence():
    raw = {"consumed": 1, "vendor": {"fw": "3.1"}}
    adapter = _double("structured")(synthetic=True)
    objects = adapter.to_cdm(raw)
    objects[0].residual = lossless.residual_block(adapter, raw, ["consumed"])
    assert objects[0].residual.data == {"vendor": {"fw": "3.1"}}
    assert structured_residual_offences(adapter, objects) == []


def test_the_shipped_adapters_declare_legacy_and_the_sweep_says_so_rather_than_passing_silently():
    """The sweep over the real roster, and it states its own vacuity instead of hiding it.

    Fourteen `legacy` and zero `structured` is ARCHITECTURE.md §5's Part 1 ruling, read from the
    declarations rather than quoted. The day a Part 2 adapter lands, the count moves and the
    `structured` branch of `structured_residual_offences` starts doing work on real fixtures.
    """
    # SHIPPED only. `discover()` returns the process-wide registry, and this module defines test
    # doubles that land in it — a sweep that counted them would report a roster that depends on
    # test execution order, which is the least reproducible reading there is.
    roster = {name: cls for name, cls in discover().items()
              if cls.__module__.startswith("synapse_cdm.adapters")}
    census = {stance: sorted(cls.name for cls in roster.values()
                             if cls.metadata.residual is stance)
              for stance in ResidualStance}
    assert len(census[ResidualStance.LEGACY]) == len(roster) == 14
    assert census[ResidualStance.STRUCTURED] == []
    for cls in roster.values():
        assert structured_residual_offences(cls(synthetic=True), []) == []
