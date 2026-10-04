"""The DIS 7 error model, `dis7_codec`'s only content so far.

This module starts with the error model; it names the specification once, spelled exactly
`SC DIS7 SPEC 001 v1.0`, as a handoff document that is not in this repository. No acceptance
case covers the error model directly, so these tests are not named `test_t<gg>_<case>_...`;
they are the evidence of requirement R21.
"""
from __future__ import annotations

import copy
import json
import pickle
import re

import pytest

from synapse_cdm.adapter import InputTooDeep, InputTooLarge
from synapse_cdm.adapters import dis7_codec as codec
from synapse_cdm.adapters.dis7_codec import Dis7Error, Dis7InputTooDeep, Dis7InputTooLarge
from tests import dis7_support

EXPECTED_CODES = (
    "E_INPUT_TYPE",
    "E_INPUT_LIMIT",
    "E_CONTEXT_SESSION",
    "E_CONTEXT_SYNTHETIC",
    "E_CONTEXT_TIME",
    "E_CONTEXT_CONFLICT",
    "E_CONTEXT_HASH",
    "E_HEADER_UNSUPPORTED",
    "E_LENGTH_MISMATCH",
    "E_NONFINITE",
    "E_TWIN_SCHEMA",
    "E_TWIN_WIRE_MISMATCH",
    "E_VALUE_RANGE",
    "E_POSITION_DOMAIN",
    "E_PROJECTION",
    "E_REPLAY_SHAPE",
    "E_REPLAY_PROVENANCE",
    "E_REPLAY_CHANGED",
)

EXPECTED_ACCEPTANCE_CODES = {
    "E_CONTEXT_CONFLICT",
    "E_CONTEXT_SESSION",
    "E_CONTEXT_SYNTHETIC",
    "E_CONTEXT_TIME",
    "E_HEADER_UNSUPPORTED",
    "E_INPUT_LIMIT",
    "E_LENGTH_MISMATCH",
    "E_NONFINITE",
    "E_POSITION_DOMAIN",
    "E_REPLAY_CHANGED",
    "E_REPLAY_PROVENANCE",
    "E_REPLAY_SHAPE",
    "E_TWIN_SCHEMA",
    "E_TWIN_WIRE_MISMATCH",
}


def test_r21_codes_are_the_contract_table_in_order():
    assert codec.CODES == EXPECTED_CODES
    assert len(codec.CODES) == 18
    assert len(set(codec.CODES)) == 18
    for name in EXPECTED_CODES:
        assert getattr(codec, name) == name


def test_r21_every_code_an_acceptance_case_expects_is_in_the_table():
    cases_path = dis7_support.CONTRACT / "acceptance-cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    found = set()
    for case in cases:
        found |= set(re.findall(r"E_[A-Z_]+", case["expected"]))
    assert found == EXPECTED_ACCEPTANCE_CODES
    assert found <= set(codec.CODES)


@pytest.mark.parametrize(
    "code, path, message",
    [
        ("E_LENGTH_MISMATCH", "byte[8]", "declared length 144, received 145"),
        ("E_TWIN_SCHEMA", "pdu.header", "unknown key"),
        ("E_CONTEXT_TIME", "time_context.instant", "50% {x} at y: z"),
    ],
)
def test_r21_error_exposes_code_path_message_and_prints_them(code, path, message):
    error = Dis7Error(code, path, message)
    assert error.code == code
    assert error.path == path
    assert error.message == message
    assert str(error) == f"{code} at {path}: {message}"
    assert error.args == (code, path, message)
    assert isinstance(error, ValueError)
    assert not isinstance(error, InputTooLarge)
    assert not isinstance(error, InputTooDeep)


def test_r21_too_large_carries_the_limit_code_and_both_base_classes():
    with pytest.raises(InputTooLarge) as raised:
        raise Dis7InputTooLarge("$", "input is 4225 octets; the limit is 4224")
    error = raised.value
    assert isinstance(error, Dis7Error)
    assert isinstance(error, ValueError)
    assert not isinstance(error, InputTooDeep)
    assert error.code == "E_INPUT_LIMIT"
    assert error.path == "$"
    assert str(error) == "E_INPUT_LIMIT at $: input is 4225 octets; the limit is 4224"
    assert "4224" in str(error) and "4225" in str(error)
    assert Dis7InputTooLarge.__mro__[:3] == (Dis7InputTooLarge, Dis7Error, InputTooLarge)


def test_r21_too_deep_carries_the_limit_code_and_both_base_classes():
    with pytest.raises(InputTooDeep) as raised:
        raise Dis7InputTooDeep("$", "envelope nests 17 containers deep; the limit is 16")
    error = raised.value
    assert isinstance(error, Dis7Error)
    assert isinstance(error, ValueError)
    assert not isinstance(error, InputTooLarge)
    assert str(error) == "E_INPUT_LIMIT at $: envelope nests 17 containers deep; the limit is 16"
    assert Dis7InputTooDeep.__mro__[:3] == (Dis7InputTooDeep, Dis7Error, InputTooDeep)


@pytest.mark.parametrize(
    "error",
    [
        Dis7Error("E_NONFINITE", "byte[36]", "velocity component is not finite"),
        Dis7InputTooLarge("$", "input is 4225 octets; the limit is 4224"),
        Dis7InputTooDeep("$", "envelope nests 17 containers deep; the limit is 16"),
    ],
)
def test_r21_errors_survive_copy_and_pickle(error):
    for clone in (copy.copy(error), copy.deepcopy(error), pickle.loads(pickle.dumps(error))):
        assert type(clone) is type(error)
        assert clone.code == error.code
        assert clone.path == error.path
        assert clone.message == error.message
        assert str(clone) == str(error)
