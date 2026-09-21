"""A normative resource for a test, or a BLOCKED skip — never a pass (adapter expansion phase 1).

The register's word for "the resource this needs is not in this environment" is
`BLOCKED_EXTERNAL_EVIDENCE`, and a test that cannot reach an authorised schema has to record that
word rather than a green tick. A `pytest.skip` is what this suite already uses for a held document
that is absent from a fresh clone (`tests/test_cdm_pins.py`), and its reason string is what the
run log carries; so a test that asks for a binding through this module either gets the resource
or is skipped with a reason that begins with the register's word and names the step that failed.

Mark such a test `@pytest.mark.normative` (registered in `pytest.ini`) so a run can select or
deselect the class as a whole: `pytest -m normative` is the set that needs `env.sh` sourced and
the `validate` extra installed; `-m "not normative"` is the set that does not.
"""
from __future__ import annotations

import pytest

from synapse_cdm import normative_validation as nv
from synapse_cdm.normative_binding import BLOCKED_STATUS, NormativeBindingBlocked


def blocked_reason(step: str, reason: str) -> str:
    return f"{BLOCKED_STATUS} at step {step!r}: {reason}"


def resource(name: str):
    """The verified `LocalSchemaResource` for a binding, or a BLOCKED skip."""
    binding = nv.BINDINGS[name]
    try:
        return nv.build(binding)
    except NormativeBindingBlocked as e:
        pytest.skip(blocked_reason(e.step, e.reason))


def verdict(name: str, document: bytes | str, *, limits=None) -> nv.Verdict:
    """The verdict on a document, or a BLOCKED skip when the environment cannot judge it. The
    caller asserts VALID or INVALID; it never has to consider UNAVAILABLE, which is what the skip
    is for."""
    result = nv.validate(name, document, limits=limits)
    if result.blocked:
        pytest.skip(blocked_reason(result.step or "?", "; ".join(result.problems)))
    return result
