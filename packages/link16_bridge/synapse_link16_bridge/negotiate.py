"""Schema negotiation with the sink (REQ013, REQ140; X15).

`choose(accepts, installed)` is a pure function of the versions the sink accepts and the CDM
schema version the installed `synapse-cdm` writes:

- `FULL` when the sink accepts `installed` and `installed` is 3.1.0 or later — the version that
  carries `PositionSource.SENSOR` and `UNKNOWN`, so every report projects in full;
- otherwise `COMPAT_3_0` when the sink accepts 3.0.0: the adapter's compatibility projection,
  every object stamped 3.0.0, a SENSOR or UNKNOWN position omitted and the delivery marked
  `POSITION_NOT_PROJECTED_CDM3`;
- otherwise `NEGOTIATION_FAILED`: health is not ready (`SCHEMA_NEGOTIATION_FAILED`) and ingest
  does not start.

Keyed on the installed number on purpose: while the tree's `SCHEMA_VERSION` still reads 3.0.0
(between the landing and the release commit), a 3.0.0 sink is served the compatibility
projection, which the frozen 3.0.0 contract accepts, and no SENSOR object is ever stamped 3.0.0 on
its way to a sink.
"""
from __future__ import annotations

import enum

from synapse_cdm.version import SCHEMA_VERSION

COMPAT = "3.0.0"
FIRST_FULL = (3, 1, 0)


class Projection(enum.Enum):
    FULL = "FULL"
    COMPAT_3_0 = "COMPAT_3_0"
    NEGOTIATION_FAILED = "NEGOTIATION_FAILED"


def _triple(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def choose(accepts: tuple[str, ...] | list[str], installed: str = SCHEMA_VERSION) -> Projection:
    accepted = set(accepts)
    if installed in accepted and _triple(installed) >= FIRST_FULL:
        return Projection.FULL
    if COMPAT in accepted:
        return Projection.COMPAT_3_0
    return Projection.NEGOTIATION_FAILED


def adapter_schema(projection: Projection) -> str | None:
    """The adapter's `cdm_schema` keyword for a negotiated projection."""
    if projection is Projection.FULL:
        return None
    if projection is Projection.COMPAT_3_0:
        return COMPAT
    raise ValueError("no projection was negotiated")
