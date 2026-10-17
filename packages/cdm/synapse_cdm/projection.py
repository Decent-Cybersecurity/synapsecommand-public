"""The contract projection: an object of the current models, dumped for a reader of an earlier,
frozen CDM contract.

WHY THIS EXISTS
---------------
A MINOR adds an optional field or an enum member, and readers come before writers
(MIGRATIONS.md): every published schema forbids additional properties, so a reader at the older
contract refuses an object that carries the new key at all, even with a null value. The models
serialise every field, so since CDM 3.2.0 every Event dumps `"validity": null` and every Track
`"attributes": null`, and the frozen 3.0.0 contract refuses both. That is right for the full
projection, and it would break the one promise the tree makes to a 3.0.0 reader: the Link 16
compatibility projection (`adapters/link16_gateway.py`, `cdm_schema="3.0.0"`) and the bridge's
`COMPAT_3_0` delivery hand a 3.0.0 sink objects the frozen 3.0.0 contract accepts. The models
cannot leave a field out, so the promise is kept here, at the dump boundary, and nowhere else.

THE LEDGER
----------
`LEDGERS` names, per frozen target, what the current models carry that the target does not: the
top-level properties per object kind and the enum members, each with the CDM version that added
it. It is written by hand and held by `tests/test_cdm_projection.py`, which derives the same
ledger from `tests/frozen/cdm/<target>/` against the published `schemas/` and asserts equality,
so a later MINOR cannot add a field or a member that this module does not name.

THE RULE
--------
`dump_for(obj, "3.0.0")` is `obj.model_dump(mode="json")` and then, for the ledger of the
target: a ledger property of the object's kind is removed when it is null and refused when it
holds anything, and a ledger member anywhere in the object is refused. A refusal is
`ProjectionRefused` (a `ValueError`) naming the path and the version that added what it found,
never quoting a value. Nothing that carries information is dropped: a populated field is a
refusal, because a 3.0.0 reader has nowhere to put it and a silent drop is a loss nobody
recorded. Members are matched by their enum class, not by their text: `PositionSource.UNKNOWN`
is refused and `Affiliation.UNKNOWN`, which 3.0.0 has always had, is not.

`dump_for` does not re-stamp `schema_version`; the stamp is the producer's (the Link 16
compatibility projection stamps "3.0.0"). `"3.0.0"` is the only target with a ledger (corrected
2026-10-16, at the replay onto `v3.4.0`: the 3.1.0 contract is frozen under `tests/frozen/cdm/`
and has none; and the same day the 3.5.0 release commit froze 3.2.0, the current contract, which
has none either, since an object of this tree needs no projection to the contract it is written
against). The full projection is untouched: `model_dump` still writes every field, and
`compatible()` never drops one.
"""

from __future__ import annotations

import enum
import types
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from synapse_cdm.enums import EventType, PositionSource
from synapse_cdm.models import Entity, Event, PlanObject, Track


@dataclass(frozen=True)
class Ledger:
    """What the current models carry that one frozen contract does not."""

    #: object kind -> {top-level property: the CDM version that added it}
    properties: Mapping[str, Mapping[str, str]]
    #: (enum class, member value) -> the CDM version that added the member
    members: Mapping[tuple[type[enum.Enum], str], str]


def _frozen(mapping: dict) -> Mapping:
    return types.MappingProxyType(mapping)


LEDGERS: Mapping[str, Ledger] = _frozen(
    {
        "3.0.0": Ledger(
            properties=_frozen(
                {
                    "entity": _frozen({}),
                    "event": _frozen({"validity": "3.2.0"}),
                    "plan_object": _frozen({}),
                    "track": _frozen({"attributes": "3.2.0"}),
                }
            ),
            members=_frozen(
                {
                    (PositionSource, PositionSource.SENSOR.value): "3.1.0",
                    (PositionSource, PositionSource.UNKNOWN.value): "3.1.0",
                    (EventType, EventType.ENVIRONMENTAL_OBSERVATION.value): "3.2.0",
                }
            ),
        ),
    }
)

#: The targets `dump_for` accepts: the frozen contracts a ledger is written for.
TARGETS: tuple[str, ...] = tuple(LEDGERS)

_KINDS = (Entity, Event, PlanObject, Track)


class ProjectionRefused(ValueError):
    """The object carries something the target contract cannot state. Names the path and the
    version that added it; never quotes a value."""

    def __init__(self, target: str, path: str, since: str, what: str) -> None:
        self.target = target
        self.path = path
        self.since = since
        self._what = what
        super().__init__(
            f"{path}: {what} added in CDM {since}, which the {target} contract cannot state"
        )

    def __reduce__(self):
        # `BaseException.__reduce__` rebuilds from `args`, which holds the one formatted message,
        # and this `__init__` takes four arguments: without this, `copy.copy` and a pickle round
        # trip raise `TypeError` instead of reproducing the refusal (repaired 2026-10-15).
        return (type(self), (self.target, self.path, self.since, self._what))


def dump_for(obj: Entity | Event | PlanObject | Track, target: str) -> dict[str, Any]:
    """`obj.model_dump(mode="json")` as a reader of the frozen `target` contract reads it."""
    if type(target) is not str or target not in LEDGERS:
        raise ValueError(f"dump_for: the target must be one of {list(TARGETS)}")
    if not isinstance(obj, _KINDS):
        raise TypeError("dump_for: obj must be a CDM Entity, Event, PlanObject or Track")
    ledger = LEDGERS[target]
    added = ledger.properties[obj.object_kind]
    for name, since in added.items():
        if getattr(obj, name) is not None:
            raise ProjectionRefused(target, name, since, "a populated property")
    _refuse_members(obj, "", ledger.members, target)
    dumped = obj.model_dump(mode="json")
    for name in added:
        del dumped[name]
    return dumped


def _refuse_members(value: Any, path: str, members: Mapping, target: str) -> None:
    """Walk the model instance, not its dump: in the dump an enum member is only a string, and
    the string "UNKNOWN" is a 3.0.0 value of one enum and a 3.1.0 value of another."""
    if isinstance(value, enum.Enum):
        since = members.get((type(value), value.value))
        if since is not None:
            raise ProjectionRefused(target, path, since, f"a member of {type(value).__name__}")
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            _refuse_members(getattr(value, name), _join(path, name), members, target)
        for name, item in (value.__pydantic_extra__ or {}).items():
            _refuse_members(item, _join(path, str(name)), members, target)
    elif isinstance(value, Mapping):
        for name, item in value.items():
            _refuse_members(item, _join(path, str(name)), members, target)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _refuse_members(item, f"{path}[{index}]", members, target)


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name
