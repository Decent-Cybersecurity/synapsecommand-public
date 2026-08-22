"""FORMAT_COVERAGE.md claims the CDM carries what CoT, STANAG 4676 and GeoJSON need.

A mapping table is a promise to whoever writes the next adapter, and an unchecked promise about
field names rots on the first rename. So every path in the table's CDM column is resolved
against the real Pydantic models here. A renamed or removed field fails the build, which means
the table can be read as a specification rather than as a historical document.

The resolver walks pydantic annotations rather than dictionaries, so `Track.samples[].position.lat`
is checked all the way down to the float.
"""
import pathlib
import re
import types
import typing

import pytest
from pydantic import BaseModel

import synapse_cdm
from synapse_cdm import models
from synapse_cdm.geo import LineString, Point, Polygon

# The package lives under packages/cdm/ while this suite sits at the repo root, so its
# internal files are located through the import system rather than by walking up from
# this file: a relative hop between the two breaks the moment either one moves, and this
# way the files checked are the ones belonging to the package that is actually importable.
DOC = pathlib.Path(synapse_cdm.__file__).resolve().parent / "FORMAT_COVERAGE.md"

ROOTS: dict[str, type[BaseModel]] = {
    "Entity": models.Entity,
    "Event": models.Event,
    "Track": models.Track,
    "PlanObject": models.PlanObject,
    "Position": models.Position,
    "Kinematics": models.Kinematics,
    "SourceId": models.SourceId,
    "SourceRef": models.SourceRef,
    "Integrity": models.Integrity,
    "TrackSample": models.TrackSample,
    "GnssInterferencePayload": models.GnssInterferencePayload,
    "Point": Point,
    "LineString": LineString,
    "Polygon": Polygon,
}

# Cells that deliberately say "no canonical home" — the gaps section explains each one.
NOT_A_PATH = {"—", "-", ""}


def _unwrap(annotation):
    """Peel Annotated, Optional/Union and list wrappers down to the underlying type."""
    while True:
        origin = typing.get_origin(annotation)
        if origin is typing.Annotated or (hasattr(typing, "Annotated")
                                          and getattr(annotation, "__metadata__", None)):
            annotation = typing.get_args(annotation)[0]
            continue
        if origin in (typing.Union, types.UnionType):
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            if not args:
                return annotation
            annotation = args[0]
            continue
        if origin in (list, tuple, set, frozenset):
            annotation = typing.get_args(annotation)[0]
            continue
        return annotation


def _cdm_paths() -> list[str]:
    paths = []
    for line in DOC.read_text().splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| CDM field |" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        cell = cells[1].strip("`").strip()
        if cell in NOT_A_PATH:
            continue
        if re.match(r"^[A-Z][A-Za-z]+\.", cell):
            paths.append(cell)
    return paths


PATHS = _cdm_paths()


def test_the_table_was_actually_parsed():
    """A coverage test that found no rows would pass silently and prove nothing."""
    assert len(PATHS) >= 25, f"parsed only {len(PATHS)} CDM paths from {DOC.name}"
    assert any(p.startswith("Track.samples[]") for p in PATHS), "STANAG rows missing"
    assert any(p.startswith("PlanObject.") for p in PATHS), "egress rows missing"


@pytest.mark.parametrize("path", sorted(set(PATHS)))
def test_every_mapped_cdm_path_exists_on_the_models(path):
    parts = path.split(".")
    root = parts[0].removesuffix("[]")
    assert root in ROOTS, f"{path}: unknown root model {root!r}"
    current: type[BaseModel] | None = ROOTS[root]
    walked = root
    for part in parts[1:]:
        field_name = part.removesuffix("[]")
        assert current is not None and issubclass(current, BaseModel), (
            f"{path}: {walked} is not a model, so it has no field {field_name!r}"
        )
        assert field_name in current.model_fields, (
            f"{path}: {current.__name__} has no field {field_name!r} — the table is stale, "
            f"fields are: {sorted(current.model_fields)}"
        )
        annotation = _unwrap(current.model_fields[field_name].annotation)
        current = annotation if isinstance(annotation, type) and \
            issubclass(annotation, BaseModel) else None
        walked = f"{walked}.{field_name}"


def test_the_documented_gaps_are_still_gaps():
    """Each gap is a field the CDM does NOT have. If one appears, close the doc entry with it.

    This runs in the awkward direction on purpose: a gap silently fixed in code but left open
    in the document is how an adapter author ends up parking a value in `attributes` that has
    had a canonical home for months.
    """
    assert "label" not in models.Entity.model_fields, (
        "gap 1 (no canonical name) appears to be closed — Entity.label now exists. Update "
        "FORMAT_COVERAGE.md, MIGRATIONS.md and the CoT callsign row."
    )
    assert "alt_accuracy_m" not in models.Position.model_fields, (
        "gap 6 (no vertical accuracy) appears to be closed — update FORMAT_COVERAGE.md and "
        "the CoT point/@le row."
    )


def test_the_gap_notes_are_referenced_from_the_table():
    text = DOC.read_text()
    for number in range(1, 7):
        assert f"**gap {number}**" in text or f"{number}. **" in text, (
            f"gap {number} is listed but never referenced from a table row"
        )
