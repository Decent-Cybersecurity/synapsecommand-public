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
