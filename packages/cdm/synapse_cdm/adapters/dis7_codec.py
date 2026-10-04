"""The DIS 7 Entity State codec's public error model.

Every refusal this codec and the `dis7` adapter raise is a `Dis7Error`, which prints as
`CODE at PATH: message`. The code order below is the order of the code table in the handoff
document `SC DIS7 SPEC 001 v1.0`, which is not in this repository. The acceptance cases this
codec is held to ship in `fixtures/dis7/contract/acceptance-cases.json`. The wire codec, the
projection and the kinematics are added in later work.
"""
from __future__ import annotations

from synapse_cdm.adapter import InputTooDeep, InputTooLarge

E_INPUT_TYPE = "E_INPUT_TYPE"
E_INPUT_LIMIT = "E_INPUT_LIMIT"
E_CONTEXT_SESSION = "E_CONTEXT_SESSION"
E_CONTEXT_SYNTHETIC = "E_CONTEXT_SYNTHETIC"
E_CONTEXT_TIME = "E_CONTEXT_TIME"
E_CONTEXT_CONFLICT = "E_CONTEXT_CONFLICT"
E_CONTEXT_HASH = "E_CONTEXT_HASH"
E_HEADER_UNSUPPORTED = "E_HEADER_UNSUPPORTED"
E_LENGTH_MISMATCH = "E_LENGTH_MISMATCH"
E_NONFINITE = "E_NONFINITE"
E_TWIN_SCHEMA = "E_TWIN_SCHEMA"
E_TWIN_WIRE_MISMATCH = "E_TWIN_WIRE_MISMATCH"
E_VALUE_RANGE = "E_VALUE_RANGE"
E_POSITION_DOMAIN = "E_POSITION_DOMAIN"
E_PROJECTION = "E_PROJECTION"
E_REPLAY_SHAPE = "E_REPLAY_SHAPE"
E_REPLAY_PROVENANCE = "E_REPLAY_PROVENANCE"
E_REPLAY_CHANGED = "E_REPLAY_CHANGED"

CODES = (
    E_INPUT_TYPE,
    E_INPUT_LIMIT,
    E_CONTEXT_SESSION,
    E_CONTEXT_SYNTHETIC,
    E_CONTEXT_TIME,
    E_CONTEXT_CONFLICT,
    E_CONTEXT_HASH,
    E_HEADER_UNSUPPORTED,
    E_LENGTH_MISMATCH,
    E_NONFINITE,
    E_TWIN_SCHEMA,
    E_TWIN_WIRE_MISMATCH,
    E_VALUE_RANGE,
    E_POSITION_DOMAIN,
    E_PROJECTION,
    E_REPLAY_SHAPE,
    E_REPLAY_PROVENANCE,
    E_REPLAY_CHANGED,
)


class Dis7Error(ValueError):
    """Every coded refusal the codec and the `dis7` adapter raise."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(code, path, message)
        self.code = code
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"


class Dis7InputTooLarge(Dis7Error, InputTooLarge):
    """An `E_INPUT_LIMIT` refusal for a payload over the declared byte bound."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(E_INPUT_LIMIT, path, message)
        # Copy and pickle rebuild an exception as type(self)(*self.args).
        self.args = (path, message)


class Dis7InputTooDeep(Dis7Error, InputTooDeep):
    """An `E_INPUT_LIMIT` refusal for an envelope nested past the declared depth bound."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(E_INPUT_LIMIT, path, message)
        # Copy and pickle rebuild an exception as type(self)(*self.args).
        self.args = (path, message)
