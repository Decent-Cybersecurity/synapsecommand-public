"""The trace ratchet of D-11: every acceptance case is bound by a collected test or pending.

`tests/contract/pending.json` carries three things: the frozen case-to-round assignment of the
run (`assignment`), the ids of each round that no collected test binds yet (`pending`), and the
last round whose ids must all be bound (`finished_through`). A round removes its ids from
`pending` as it binds them with `hla_support.case(...)`, records any clause of a gate it cannot
hold yet in `carried.json`, and moves `finished_through` to itself when it is done.

The first test runs the ratchet over the real tree, with the bindings of a real collection of
the whole suite; the rest prove that each rule fires, on small hand-built inputs.
"""

import hashlib
import json
import re

import pytest

from hla_support import (
    ROUNDS, case, collected_bindings, contract_json, trace_problems,
)

INDEX = contract_json("case-index.json")
PENDING = contract_json("pending.json")
CARRIED = contract_json("carried.json")
PARAGRAPHS = contract_json("paragraph-map.json")

#: SHA-256 of the run's case-to-round assignment serialised canonically (sorted keys, ',' and ':'
#: separators, ASCII), computed from the run's assignment file when this ratchet was written.
#: A round that moves an id between rounds changes this digest and has to say so in review.
ASSIGNMENT_SHA256 = "987b95d3f2878c88eb9403f0ed7193cbd490601fab4c431a8b102cfeb03c3e52"


@pytest.fixture(scope="module")
def bindings(tmp_path_factory):
    return collected_bindings(tmp_path_factory.mktemp("trace"))


def test_the_tree_satisfies_the_ratchet(bindings):
    assert trace_problems(INDEX, PENDING, CARRIED, PARAGRAPHS, bindings) == []


def test_the_assignment_is_the_runs():
    data = json.dumps(PENDING["assignment"], sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")
    assert hashlib.sha256(data).hexdigest() == ASSIGNMENT_SHA256
    counts = {r: len(ids) for r, ids in PENDING["assignment"].items()}
    assert counts == {"R0": 0, "R1": 51, "R2": 14, "R3": 7, "R4": 32, "R5": 8, "R6": 1,
                      "R7": 9, "R8": 10, "R9": 15}


def test_pending_json_has_exactly_its_four_members():
    assert set(PENDING) == {"about", "assignment", "pending", "finished_through"}
    assert PENDING["finished_through"] in ROUNDS


def test_the_paragraph_map_is_well_formed():
    """OPS-27 as recorded: keys SPEC:<line>, each a prose paragraph or a table with its last line,
    mapped to sorted, distinct, existing requirements."""
    assert PARAGRAPHS, "the map is empty"
    lines = []
    for key, row in PARAGRAPHS.items():
        m = re.fullmatch(r"SPEC:([1-9][0-9]*)", key)
        assert m, key
        line = int(m.group(1))
        lines.append(line)
        assert row["kind"] in ("prose", "table"), key
        if row["kind"] == "table":
            assert set(row) == {"kind", "last_line", "requirements", "rule"}, key
            assert row["last_line"] > line, key
        else:
            assert set(row) == {"kind", "requirements", "rule"}, key
        reqs = row["requirements"]
        assert reqs and reqs == sorted(set(reqs)), key
        assert all(re.fullmatch(r"R(0[1-9]|[1-4][0-9]|50)", r) for r in reqs), key
        assert row["rule"] in ("nearest-preceding", "OPS-27", "CR-new-R0-02", "CR-new-R0-03")
    assert lines == sorted(lines)


def test_the_paragraph_map_records_ops_27():
    """The mappings OPS-27 states explicitly, compared with the ruling's text."""
    stated = {
        "SPEC:20": ["R02", "R03", "R43"],
        "SPEC:259": ["R45", "R46"],
        "SPEC:275": ["R06", "R08", "R14", "R16"],
        "SPEC:277": ["R06", "R14", "R41"],
        "SPEC:279": ["R12", "R22", "R41"],
        "SPEC:281": ["R13", "R18", "R19", "R22", "R24"],
        "SPEC:283": ["R12", "R21", "R22"],
        "SPEC:285": ["R23", "R25", "R32"],
        "SPEC:287": ["R32", "R33", "R45"],
        "SPEC:289": ["R07", "R08", "R09", "R11", "R15", "R32", "R37", "R40"],
        "SPEC:291": ["R12", "R25", "R40"],
        "SPEC:293": ["R04", "R15", "R17", "R34", "R35", "R40", "R41"],
    }
    for key, reqs in stated.items():
        assert PARAGRAPHS[key]["requirements"] == reqs, key
        assert PARAGRAPHS[key]["rule"] == "OPS-27", key
    assert {k for k, v in PARAGRAPHS.items() if v["rule"] == "OPS-27"} == set(stated)


def test_the_paragraph_map_applies_the_nearest_preceding_rule():
    """Every other continuation paragraph and table after SPEC:12, with the R that precedes it in
    its section, read off the specification by hand; and the two proposals of this round."""
    nearest = {
        "SPEC:28": "R05", "SPEC:32": "R06", "SPEC:38": "R07", "SPEC:42": "R08",
        "SPEC:50": "R10", "SPEC:56": "R12", "SPEC:62": "R14", "SPEC:68": "R15",
        "SPEC:72": "R16", "SPEC:80": "R18", "SPEC:88": "R19", "SPEC:99": "R19",
        "SPEC:118": "R22", "SPEC:126": "R25", "SPEC:134": "R27", "SPEC:142": "R29",
        "SPEC:146": "R30", "SPEC:154": "R32", "SPEC:158": "R33", "SPEC:166": "R35",
        "SPEC:168": "R35", "SPEC:174": "R36", "SPEC:184": "R36", "SPEC:190": "R37",
        "SPEC:201": "R37", "SPEC:207": "R38", "SPEC:211": "R39", "SPEC:217": "R40",
        "SPEC:241": "R43", "SPEC:251": "R46",
    }
    for key, req in nearest.items():
        assert PARAGRAPHS[key]["requirements"] == [req], key
        assert PARAGRAPHS[key]["rule"] == "nearest-preceding", key
    assert {k for k, v in PARAGRAPHS.items() if v["rule"] == "nearest-preceding"} == set(nearest)
    tables = {k: v["last_line"] for k, v in PARAGRAPHS.items() if v["kind"] == "table"}
    assert tables == {"SPEC:80": 84, "SPEC:88": 97, "SPEC:99": 108, "SPEC:174": 182,
                      "SPEC:190": 199, "SPEC:217": 231}
    # CR-new-R0-02: section 19 has no requirement; its three paragraphs limit claims (R50).
    for key in ("SPEC:267", "SPEC:269", "SPEC:271"):
        assert PARAGRAPHS[key] == {"kind": "prose", "requirements": ["R50"],
                                   "rule": "CR-new-R0-02"}
    # CR-new-R0-03: the two preamble paragraphs before section 1.
    assert PARAGRAPHS["SPEC:8"]["requirements"] == ["R02", "R05"]
    assert PARAGRAPHS["SPEC:10"]["requirements"] == ["R50"]
    assert len(PARAGRAPHS) == 47


# ------------------------------------------------------------------- each rule, on small inputs

SMALL_INDEX = [
    {"id": "G-R07", "requirement": "R07", "layer": "release"},
    {"id": "A-UTF8", "requirement": "R07", "layer": "behavior"},
    {"id": "G-R18", "requirement": "R18", "layer": "release"},
    {"id": "V-ID-123", "requirement": "R19", "layer": "codec"},
]
SMALL_MAP = {"SPEC:38": {"kind": "prose", "requirements": ["R07"], "rule": "nearest-preceding"},
             "SPEC:289": {"kind": "prose", "requirements": ["R07", "R09"], "rule": "OPS-27"}}


def small_pending(pending=None, assignment=None, finished="R0"):
    rounds = {r: [] for r in ROUNDS}
    base = dict(rounds, R1=["G-R18", "V-ID-123"], R2=["G-R07", "A-UTF8"])
    return {"about": "", "assignment": assignment or base,
            "pending": dict(rounds, **(pending if pending is not None else
                                       {"R1": ["G-R18", "V-ID-123"], "R2": ["G-R07", "A-UTF8"]})),
            "finished_through": finished}


def problems(pending_doc=None, carried=(), bindings=None, index=None):
    return trace_problems(index or SMALL_INDEX, pending_doc or small_pending(), list(carried),
                          SMALL_MAP, bindings or {})


def test_the_small_baseline_is_clean():
    assert problems() == []


def test_an_id_neither_bound_nor_pending_fails():
    doc = small_pending({"R1": ["G-R18"], "R2": ["G-R07", "A-UTF8"]})
    assert problems(doc) == [("unbound-not-pending", "V-ID-123")]


def test_an_id_both_bound_and_pending_fails():
    assert problems(bindings={"t::a": {"ids": ["V-ID-123"], "paragraphs": []}}) == [
        ("bound-and-pending", "V-ID-123")]


def test_binding_an_unknown_id_fails():
    assert problems(bindings={"t::a": {"ids": ["A-NOPE"], "paragraphs": []}}) == [
        ("bound-unknown-id", "A-NOPE")]


def test_binding_removes_the_need_to_be_pending():
    doc = small_pending({"R1": ["G-R18"], "R2": ["G-R07", "A-UTF8"]})
    assert problems(doc, bindings={"t::a": {"ids": ["V-ID-123"], "paragraphs": []}}) == []


def test_a_pending_id_under_another_round_than_its_assignment_fails():
    doc = small_pending({"R1": ["G-R18"], "R2": ["G-R07", "A-UTF8", "V-ID-123"]})
    assert problems(doc) == [("pending-wrong-round", "V-ID-123")]


def test_an_assignment_that_differs_from_the_index_fails():
    rounds = {r: [] for r in ROUNDS}
    moved = dict(rounds, R1=["G-R18"], R2=["G-R07", "A-UTF8", "A-EXTRA"])
    doc = small_pending({"R1": ["G-R18"], "R2": ["G-R07", "A-UTF8"]}, assignment=moved)
    assert problems(doc) == [("assignment-missing", "V-ID-123"),
                             ("assignment-unknown-id", "A-EXTRA"),
                             ("unbound-not-pending", "V-ID-123")]


def test_an_id_assigned_twice_fails():
    rounds = {r: [] for r in ROUNDS}
    twice = dict(rounds, R1=["G-R18", "V-ID-123"], R2=["G-R07", "A-UTF8", "V-ID-123"])
    assert ("assignment-duplicate", "V-ID-123") in problems(small_pending(assignment=twice))


def test_unknown_and_duplicate_pending_ids_fail():
    doc = small_pending({"R1": ["G-R18", "V-ID-123", "V-ID-123"],
                         "R2": ["G-R07", "A-UTF8", "A-NOPE"]})
    assert problems(doc) == [("pending-duplicate", "V-ID-123"), ("pending-unknown-id", "A-NOPE")]


def test_a_finished_round_with_pending_ids_fails():
    assert problems(small_pending(finished="R1")) == [("finished-round-pending", "R1")]


def test_a_finished_round_with_every_id_bound_passes():
    doc = small_pending({"R2": ["G-R07", "A-UTF8"]}, finished="R1")
    bound = {"t::a": {"ids": ["G-R18"], "paragraphs": []},
             "t::b": {"ids": ["V-ID-123"], "paragraphs": []}}
    assert problems(doc, bindings=bound) == []


@pytest.mark.parametrize("mutate", ["missing-round", "extra-round", "bad-finished", "not-lists"])
def test_a_malformed_pending_document_fails(mutate):
    doc = small_pending()
    if mutate == "missing-round":
        del doc["pending"]["R9"]
    elif mutate == "extra-round":
        doc["assignment"]["R10"] = []
    elif mutate == "bad-finished":
        doc["finished_through"] = "R10"
    else:
        doc["pending"]["R3"] = "A-UTF8"
    assert problems(doc) == [("round-keys", "pending.json")]


def test_a_duplicate_index_id_fails():
    index = SMALL_INDEX + [SMALL_INDEX[1]]
    assert problems(index=index) == [("index-duplicate", "A-UTF8")]


# ---------------------------------------------------------------------------- carried clauses

GATE_R18_BOUND = {"t::g": {"ids": ["G-R18"], "paragraphs": []}}
DOC_R18_BOUND = small_pending({"R1": ["V-ID-123"], "R2": ["G-R07", "A-UTF8"]})


def test_a_carried_clause_of_a_bound_gate_due_later_passes():
    carried = [{"gate": "G-R18", "clause": "decoder error precedence", "due": "R2"}]
    assert problems(DOC_R18_BOUND, carried, GATE_R18_BOUND) == []


def test_a_carried_clause_due_in_a_round_whose_pending_list_is_empty_fails():
    carried = [{"gate": "G-R18", "clause": "decoder error precedence", "due": "R3"}]
    assert problems(DOC_R18_BOUND, carried, GATE_R18_BOUND) == [
        ("carried-due-empty-round", "G-R18 decoder error precedence")]


def test_a_carried_clause_naming_an_unknown_gate_or_round_fails():
    carried = [{"gate": "G-R99", "clause": "c", "due": "R2"},
               {"gate": "A-UTF8", "clause": "c", "due": "R2"},
               {"gate": "G-R18", "clause": "c", "due": "R10"}]
    assert problems(DOC_R18_BOUND, carried, GATE_R18_BOUND) == [
        ("carried-unknown-gate", "A-UTF8 c"), ("carried-unknown-gate", "G-R99 c"),
        ("carried-unknown-round", "G-R18 c")]


def test_a_carried_clause_of_an_unbound_gate_fails():
    carried = [{"gate": "G-R07", "clause": "c", "due": "R3"}]
    doc = small_pending({"R1": ["G-R18", "V-ID-123"], "R2": ["G-R07", "A-UTF8"],
                         "R3": []}, finished="R0")
    found = problems(doc, carried)
    assert ("carried-gate-not-bound", "G-R07 c") in found


def test_a_carried_clause_due_no_later_than_its_gate_fails():
    carried = [{"gate": "G-R18", "clause": "c", "due": "R1"}]
    assert ("carried-due-not-later", "G-R18 c") in problems(DOC_R18_BOUND, carried,
                                                             GATE_R18_BOUND)


@pytest.mark.parametrize("entry", [
    {"gate": "G-R18", "clause": "c"},
    {"gate": "G-R18", "clause": "", "due": "R2"},
    {"gate": "G-R18", "clause": "c", "due": "R2", "extra": 1},
    {"gate": "G-R18", "clause": 3, "due": "R2"},
    "G-R18",
])
def test_a_malformed_carried_entry_fails(entry):
    assert [p[0] for p in problems(DOC_R18_BOUND, [entry], GATE_R18_BOUND)] == [
        "carried-malformed"]


def test_a_duplicate_carried_entry_fails():
    entry = {"gate": "G-R18", "clause": "c", "due": "R2"}
    assert problems(DOC_R18_BOUND, [entry, dict(entry)], GATE_R18_BOUND) == [
        ("carried-duplicate", "G-R18 c")]


# ------------------------------------------------------------------- paragraphs held by a gate

DOC_R07_BOUND = small_pending({"R1": ["G-R18", "V-ID-123"], "R2": ["A-UTF8"]})


def test_a_bound_gate_must_hold_every_paragraph_mapped_to_it():
    bound = {"t::g": {"ids": ["G-R07"], "paragraphs": ["SPEC:38"]}}
    assert problems(DOC_R07_BOUND, bindings=bound) == [("paragraph-uncovered", "G-R07 SPEC:289")]


def test_a_gate_holding_all_its_paragraphs_across_tests_passes():
    bound = {"t::a": {"ids": ["G-R07"], "paragraphs": ["SPEC:38"]},
             "t::b": {"ids": ["G-R07", "A-UTF8"], "paragraphs": ["SPEC:289"]}}
    doc = small_pending({"R1": ["G-R18", "V-ID-123"], "R2": []})
    assert problems(doc, bindings=bound) == []


def test_a_carried_paragraph_counts_as_held_until_it_is_due():
    bound = {"t::g": {"ids": ["G-R07"], "paragraphs": ["SPEC:38"]}}
    carried = [{"gate": "G-R07", "clause": "SPEC:289 year-9998 overflow", "due": "R4"}]
    doc = small_pending({"R1": ["G-R18", "V-ID-123"], "R2": ["A-UTF8"], "R4": ["A-X"]},
                        assignment=dict({r: [] for r in ROUNDS}, R1=["G-R18", "V-ID-123"],
                                        R2=["G-R07", "A-UTF8"], R4=["A-X"]))
    index = SMALL_INDEX + [{"id": "A-X", "requirement": "R09", "layer": "behavior"}]
    assert problems(doc, carried, bound, index) == []


def test_a_clause_prefix_does_not_carry_a_longer_paragraph_number():
    bound = {"t::g": {"ids": ["G-R07"], "paragraphs": ["SPEC:38"]}}
    carried = [{"gate": "G-R07", "clause": "SPEC:2890 is not SPEC:289", "due": "R4"}]
    doc = small_pending({"R1": ["G-R18", "V-ID-123"], "R2": ["A-UTF8"], "R4": ["A-X"]},
                        assignment=dict({r: [] for r in ROUNDS}, R1=["G-R18", "V-ID-123"],
                                        R2=["G-R07", "A-UTF8"], R4=["A-X"]))
    index = SMALL_INDEX + [{"id": "A-X", "requirement": "R09", "layer": "behavior"}]
    assert problems(doc, carried, bound, index) == [("paragraph-uncovered", "G-R07 SPEC:289")]


def test_naming_an_unknown_paragraph_or_one_of_another_gate_fails():
    bound = {"t::a": {"ids": ["G-R07"], "paragraphs": ["SPEC:38", "SPEC:289", "SPEC:999"]},
             "t::b": {"ids": ["G-R18"], "paragraphs": ["SPEC:38"]}}
    doc = small_pending({"R1": ["V-ID-123"], "R2": ["A-UTF8"]})
    assert problems(doc, bindings=bound) == [("paragraph-not-of-gate", "t::b SPEC:38"),
                                             ("paragraph-unknown", "t::a SPEC:999")]


# --------------------------------------------------------------------------- the decorator

def test_case_returns_the_marker_with_ids_and_paragraphs():
    mark = case("G-R07", "A-UTF8", paragraphs=("SPEC:289",)).mark
    assert mark.name == "hla_case"
    assert mark.args == ("G-R07", "A-UTF8")
    assert mark.kwargs == {"paragraphs": ("SPEC:289",)}


@pytest.mark.parametrize("args,kwargs", [
    ((), {}),
    (("",), {}),
    (("A-",), {}),
    (("X-FOO",), {}),
    (("A-UTF8 ",), {}),
    (("A-UTF8", "A-UTF8"), {}),
    ((b"A-UTF8",), {}),
    (("G-R07",), {"paragraphs": ["SPEC:289"]}),
    (("G-R07",), {"paragraphs": ("SPEC:0",)}),
    (("G-R07",), {"paragraphs": ("289",)}),
    (("A-UTF8",), {"paragraphs": ("SPEC:289",)}),
])
def test_case_refuses_malformed_arguments_at_import_time(args, kwargs):
    with pytest.raises(ValueError):
        case(*args, **kwargs)
