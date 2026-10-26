"""The label-lattice interface: the shipped lattice returns only identical labels and refuses
every other combination by name; every lattice, the toy scheme fake included, meets the contract
that it never downgrades and never reads an empty releasability as everyone."""

from __future__ import annotations

import copy
import itertools

import pytest
from helpers import vector

from synapse_cdm.adapters.stanag4545 import CORE1_LIMITS, parse_container, security_labels
from synapse_imagery.fakes import FakeSchemeLattice
from synapse_imagery.policy import (
    LATTICE_REFUSALS,
    IdenticalOnlyLattice,
    LabelCombinationRefused,
)

FILE_LABEL = security_labels(parse_container(vector("geo_dms.ntf"), CORE1_LIMITS))[0]


def label(clsy: str = "", clas: str = "U", rel: str = "", **fields) -> dict:
    out = copy.deepcopy(FILE_LABEL)
    out["fields"].update(CLSY=clsy, CLAS=clas, REL=rel, **fields)
    return out


def refusal(lattice, labels) -> str:
    with pytest.raises(LabelCombinationRefused) as caught:
        lattice.combine(labels)
    assert caught.value.reason in LATTICE_REFUSALS
    return caught.value.reason


def test_identical_labels_combine_to_the_common_label():
    combined = IdenticalOnlyLattice().combine([FILE_LABEL, copy.deepcopy(FILE_LABEL)])
    assert combined["fields"] == FILE_LABEL["fields"]
    assert (combined["scope"], combined["index"], combined["offset"], combined["length"]) == (
        "combined",
        None,
        None,
        None,
    )
    assert combined["uninterpreted"] == []
    assert IdenticalOnlyLattice.lattice_id == "sc-imagery-identical-only/1"


@pytest.mark.parametrize(
    "labels, reason",
    [
        ([], "EMPTY_INPUT"),
        ([label(clas="U"), label(clas="R")], "DIFFERENT_LEVEL"),
        ([label(clsy="XN"), label(clsy="")], "DIFFERENT_SYSTEM"),
        ([label(rel="AB"), label(rel="")], "DIFFERENT_CAVEATS"),
        ([label(CODE="X1"), label()], "DIFFERENT_CAVEATS"),
        ([label(clas="")], "UNRECOGNISED_LEVEL"),
        ([label(clas="u"), label(clas="u")], "UNRECOGNISED_LEVEL"),
    ],
)
def test_the_identical_only_lattice_refuses_by_name(labels, reason):
    assert refusal(IdenticalOnlyLattice(), labels) == reason


def test_an_uninterpreted_field_is_refused_before_anything_else():
    unread = label(CTLN=None)
    unread["uninterpreted"] = ["CTLN"]
    assert refusal(IdenticalOnlyLattice(), [unread, unread]) == "UNINTERPRETED_FIELD"
    assert refusal(FakeSchemeLattice("XN", ("U", "R", "C")), [unread]) == "UNINTERPRETED_FIELD"


# --------------------------------------------------------------------------- the toy scheme

SCHEME = FakeSchemeLattice("XN", ("U", "R", "C"))


def test_the_toy_scheme_takes_the_higher_level_unites_handling_and_intersects_recipients():
    combined = SCHEME.combine(
        [
            label("XN", "U", "AB CD", CODE="K1", CTLH="H"),
            label("XN", "R", "CD EF", CODE="K2"),
        ]
    )
    assert combined["fields"]["CLAS"] == "R"
    assert combined["fields"]["REL"] == "CD"
    assert combined["fields"]["CODE"] == "K1 K2"
    assert combined["fields"]["CTLH"] == "H"
    assert combined["scope"] == "combined"


@pytest.mark.parametrize(
    "labels, reason",
    [
        ([label("YM", "U", "AB")], "DIFFERENT_SYSTEM"),
        ([label("XN", "S", "AB")], "UNRECOGNISED_LEVEL"),
        ([label("XN", "U", "AB"), label("XN", "U", "")], "EMPTY_RELEASABILITY"),
        ([label("XN", "U", "AB"), label("XN", "R", "CD")], "NO_COMMON_RECIPIENT"),
        (
            [label("XN", "U", "AB", CODE="AAAA BBBB"), label("XN", "U", "AB", CODE="CCCC")],
            "FIELD_OVERFLOW",
        ),
        (
            [label("XN", "U", "AB", CLTX="ONE"), label("XN", "U", "AB", CLTX="TWO")],
            "DIFFERENT_CAVEATS",
        ),
    ],
)
def test_the_toy_scheme_refuses_what_it_cannot_decide(labels, reason):
    assert refusal(SCHEME, labels) == reason


# --------------------------------------------------------------------------- the contract

CORPUS = [
    label(clsy, clas, rel)
    for clsy in ("XN", "YM")
    for clas in ("U", "R", "C")
    for rel in ("", "AB CD")
]
RANK = {"U": 0, "R": 1, "C": 2}


@pytest.mark.parametrize("lattice", [IdenticalOnlyLattice(), SCHEME], ids=["identical", "scheme"])
def test_every_lattice_meets_the_contract(lattice):
    assert len(CORPUS) == 12
    combined_count = refused_count = 0
    for first, second in itertools.product(CORPUS, repeat=2):
        pair = [first, second]
        rels = [entry["fields"]["REL"] for entry in pair]
        try:
            combined = lattice.combine(copy.deepcopy(pair))
        except LabelCombinationRefused as refused:
            assert refused.reason in LATTICE_REFUSALS
            refused_count += 1
            continue
        combined_count += 1
        level = RANK[combined["fields"]["CLAS"]]
        assert all(level >= RANK[entry["fields"]["CLAS"]] for entry in pair)
        if any(rel for rel in rels):
            assert combined["fields"]["REL"]
        assert not ("" in rels and "AB CD" in rels), "an empty releasability was combined"
    assert combined_count and refused_count
