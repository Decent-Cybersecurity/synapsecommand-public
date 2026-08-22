"""FORMAT_COVERAGE.md claims the CDM carries what CoT, STANAG 4676 and GeoJSON need.

A mapping table is a promise to whoever writes the next adapter, and an unchecked promise about
field names rots on the first rename. So every path in the table's CDM column is resolved
against the real Pydantic models here. A renamed or removed field fails the build, which means
the table can be read as a specification rather than as a historical document.

The resolver walks pydantic annotations rather than dictionaries, so `Track.samples[].position.lat`
is checked all the way down to the float.
"""
import json
import pathlib
import uuid
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


#: A model path inside a table cell, e.g. `Track.samples[].observed_at`.
MODEL_PATH = re.compile(r"^[A-Z][A-Za-z]+(?:\[\])?(?:\.[A-Za-z_]+(?:\[\])?)+$")


def _cell_paths(cell: str) -> list[str]:
    """Every model path a CDM-field cell names — plural, because one source field can set two.

    A source value legitimately lands in more than one canonical field: an ADS-B surveillance
    status sets `Event.severity` AND `Event.event_type`, and an AIS navigational status does the
    same. The first version of this parser read one path per cell, so the SECOND path in such a
    row was never resolved against the models — a stale name there would have survived exactly
    the rot this test exists to prevent.
    """
    quoted = re.findall(r"`([^`]+)`", cell)
    candidates = quoted or [cell.strip()]
    return [c.strip() for c in candidates
            if c.strip() not in NOT_A_PATH and MODEL_PATH.match(c.strip())]


#: The column heading that marks which column of a table holds CDM paths.
CDM_COLUMN = "CDM field"


def _cdm_paths() -> list[str]:
    """Every CDM path in the document, read from the column its table's header points at.

    HEADER-AWARE, and it has to be. The first version read column 1 of every table in the file,
    which was wrong in both directions:

    - **It missed the egress tables entirely.** Those are headed `| CDM | AIS | Status | Notes |`
      — the CDM path is in column ZERO — so every `Position.lat`, `Kinematics.speed_mps` and
      `Track.samples[].position.lat` on an egress row went unresolved for as long as those rows
      have existed. A renamed field would not have failed the build.
    - **It read prose as paths.** A two- or three-column table of decisions has explanatory text
      in column 1, and any `Model.field` mentioned there was resolved as if it were a mapping.
      That passes by luck when the path happens to exist and fails confusingly when it does not.

    So a table is parsed only if its header names the CDM column, and the paths are read from
    that column's index. A table with no such header contributes nothing, which is right: it is
    not a mapping table.
    """
    paths = []
    column = None
    for line in DOC.read_text().splitlines():
        if not line.startswith("|"):
            column = None            # a blank line or prose ends the table
            continue
        if line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if CDM_COLUMN in cells:
            column = cells.index(CDM_COLUMN)
            continue
        if column is None or column >= len(cells):
            continue
        paths += _cell_paths(cells[column])
    return paths


PATHS = _cdm_paths()


def test_the_table_was_actually_parsed():
    """A coverage test that found no rows would pass silently and prove nothing."""
    assert len(PATHS) >= 25, f"parsed only {len(PATHS)} CDM paths from {DOC.name}"
    assert any(p.startswith("Track.samples[]") for p in PATHS), "STANAG rows missing"
    assert any(p.startswith("PlanObject.") for p in PATHS), "egress rows missing"


def test_a_cell_naming_two_fields_yields_both():
    """The hole the plural parser closed, pinned so it cannot reopen."""
    assert _cell_paths("`Event.severity` / `Event.event_type`") == [
        "Event.severity", "Event.event_type"]
    assert _cell_paths("`Entity.attributes`") == ["Entity.attributes"]
    assert _cell_paths("—") == []
    assert _cell_paths("*(derived)*") == []
    assert any(p == "Event.event_type" for p in PATHS), (
        "no row in the document names Event.event_type as a second path, so the plural parser "
        "is not actually being exercised by the table it guards")


def test_the_egress_tables_are_parsed_too():
    """The hole the header-aware parser closed: egress rows put the CDM path in column ZERO.

    Pinned so it cannot silently reopen — a parser that reads a fixed column index would drop
    every one of these again.
    """
    for path in ("Track.samples[].position.lat", "Kinematics.climb_mps"):
        assert path in PATHS, (
            f"{path} appears only in an egress table, so its absence means those tables are "
            "no longer being resolved against the models"
        )


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
    # Gap 7 is two fields on purpose: heading and turn rate answer one question between them,
    # and a gap opened twice for one concept gets closed twice differently. Both are asserted
    # so closing either half alone still trips this.
    for field in ("heading_deg", "turn_rate_dpm"):
        assert field not in models.Kinematics.model_fields, (
            f"gap 7 (no heading, no turn rate) appears to be closed — Kinematics.{field} now "
            "exists. Update FORMAT_COVERAGE.md, MIGRATIONS.md and the AIS true-heading and "
            "rate-of-turn rows, which park their values today. Note that ADS-B added a "
            "REQUIREMENT to that gap: a heading needs a stated datum, because an ADS-B heading "
            "is magnetic and an AIS one is true."
        )
    # Gap 9 is asserted on both models on purpose. The open question it records is precisely
    # WHERE a barometric altitude should hang — off Position, which requires a coordinate, or
    # off Entity, which does not — so closing it in either place has to come with the document.
    assert "baro_alt_m" not in models.Position.model_fields, (
        "gap 9 (no barometric altitude) appears to be closed on Position — update "
        "FORMAT_COVERAGE.md, MIGRATIONS.md and the ADS-B barometric-altitude row. Check the "
        "note under gap 9 first: hanging it off Position leaves an altitude with no horizontal "
        "fix homeless, which is the half of that gap easiest to miss."
    )
    assert "baro_alt_m" not in models.Entity.model_fields, (
        "gap 9 (no barometric altitude) appears to be closed on Entity — update "
        "FORMAT_COVERAGE.md and MIGRATIONS.md with it."
    )
    # Gap 10 is deliberately NOT proposed as a field, so this guards against one appearing
    # without the decision being written down.
    for field in ("airspeed_mps", "air_speed_mps"):
        assert field not in models.Kinematics.model_fields, (
            f"gap 10 (no air-data speeds) appears to be closed — Kinematics.{field} now "
            "exists, and that gap has no accepted proposal: it records that indicated "
            "airspeed, true airspeed and Mach are three quantities and that a consumer "
            "wanting wind needs gap 7 as well. Write the decision down before the field."
        )
    # Gap 11, entity hierarchy. Asserted on Entity because that is where a parent pointer
    # would naturally be put, and the gap's whole argument is that putting it there gives the
    # CDM a dangling reference it has no story for.
    for field in ("parent_id", "parent_entity_id", "children"):
        assert field not in models.Entity.model_fields, (
            f"gap 11 (no entity hierarchy) appears to be closed — Entity.{field} now exists. "
            "Read that gap's note first: it is unproposed because a uuid pointing outside the "
            "payload is a reference the CDM cannot resolve, and traversing the hierarchy is a "
            "per-level request and therefore fusion."
        )
    # Gap 12, classification label. Both models, because the label could plausibly be put on
    # either — and the gap says it must be designed together with gap 1 rather than in passing.
    for model, field in ((models.Entity, "classification"),
                         (models.Entity, "top_classification"),
                         (models.Event, "classification")):
        assert field not in model.model_fields, (
            f"gap 12 (no classification label) appears to be closed — {model.__name__}."
            f"{field} now exists. That gap is proposed only once gap 1 is settled: a name and "
            "a classification are different concepts and closing one without the other is how "
            "the CDM ends up with two string fields and no rule for choosing between them."
        )


# The Picogrid Legion row set is a SPECIFICATION: adapter #5 does not exist yet. These two
# tests pin it in the only two ways available before there is code — the size of the row set,
# and the presence of the version pin the row set is only trustworthy with.
LEGION_HEADING = "## Picogrid Legion Platform API v3"


def _section(heading: str) -> str:
    text = DOC.read_text()
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start:nxt if nxt != -1 else len(text)]


def test_the_legion_row_set_is_pinned_to_an_exact_spec_document():
    """Legion is a VENDOR API, so the row set is only meaningful against a pinned document.

    Every other format here is a ratified standard that moves in public on committee timescales.
    This one can change between two deploys, and its `info.version` demonstrably does not move
    when it does — so the hash is the change signal and it has to be present.
    """
    section = _section(LEGION_HEADING)
    assert "464857b081f1fb47c82e56b23f7585eb44e475c64cec1678629b41a252f6b9e1" in section, (
        "the Legion section has lost its SHA-256 pin. Without it the row set describes an "
        "unknown version of a moving API, which is worse than describing none"
    )
    assert "2026-08-22T21:04:41Z" in section, "the retrieval date is part of the pin"
    assert "/v3/openapi.json" in section, "the pin must name the document it pinned"
    assert "`3.0.0`" in section, "info.version belongs in the pin even though it is not a signal"


# In a subdirectory, not beside the fixtures: `harness.run()` replays every FILE it finds
# through `to_cdm()`, so a reference document sitting next to the payloads would be fed
# to the adapter and fail its own gate.
PIN = (pathlib.Path(synapse_cdm.__file__).resolve().parent
       / "fixtures/legion/spec/openapi_pin.json")


def _pinned_fields() -> dict[str, list[str]]:
    return {name: sorted(resource["fields"])
            for name, resource in json.loads(PIN.read_text())["resources"].items()}


def test_the_pinned_legion_inventory_matches_the_documents_own_hash():
    """The inventory is only evidence if it names the document it was read from."""
    pin = json.loads(PIN.read_text())["source"]
    assert pin["sha256"] == pin["etag"], (
        "the server's ETag is the SHA-256 of the body, which is what makes a re-fetch "
        "comparable without downloading twice; if they have diverged the pin is stale"
    )
    assert pin["retrieved_at"] == "2026-08-22T21:04:41Z"
    assert pin["bytes"] == 984135
    assert pin["openapi"] == "3.1.0"
    section = _section(LEGION_HEADING)
    assert pin["sha256"] in section, "the table and the pin file must name the same document"


@pytest.mark.parametrize("resource", sorted(_pinned_fields()))
def test_every_pinned_legion_field_has_a_row(resource):
    """"Every field of every in-scope resource" made checkable instead of asserted.

    The failure this guards against is specific and it has already happened once: writing the
    row set by reading a flattened field dump missed two fields whose schema is a bare
    `type: object` with no properties, because a flattener that walks leaves does not see them.
    Both are now rows. The other failure it guards against is an adapter author who cannot map
    a field deleting the row instead of parking the value — the table would then agree with the
    code by having stopped asking.

    Matched on either the dotted path or the bare leaf name in backticks, because the table
    legitimately uses both: a nested field is clearer written as `paging.has_more`, a top-level
    one as `speed`. Accepting either is looser than demanding one form, and it is the right
    looseness — this test exists to catch a field that is UNMENTIONED, not to police notation.
    """
    section = _section(LEGION_HEADING)

    def mentioned(field: str) -> bool:
        leaf = field.split(".")[-1].replace("[]", "")
        # Also the bracketed form: the table writes an array field as `results[]`, which reads
        # better in prose, while the pinned inventory names the property itself.
        return any(f"`{form}`" in section
                   for form in (field, field.replace("[]", ""), f"{field}[]", leaf,
                                f"{leaf}[]"))

    missing = [f for f in _pinned_fields()[resource] if not mentioned(f)]
    assert not missing, (
        f"{resource}: {len(missing)} field(s) from the pinned spec have no row in "
        f"FORMAT_COVERAGE.md: {missing}. A field with no row is a field nobody decided about"
    )


def test_the_legion_rows_claim_the_adapter_that_now_implements_them():
    """The status column has to move when the code does, in BOTH directions.

    This test was the opposite of itself until adapter #5 landed: it asserted that no row said
    `legion 1.0.0`, because a status column claiming an adapter that did not exist is the one
    thing this table exists to prevent. Now the adapter exists, so the inverse is the risk — a
    row still saying `not yet` is a shipped mapping nobody updated the document for, which is
    the same failure pointed the other way.
    """
    section = _section(LEGION_HEADING)
    rows = [line for line in section.splitlines()
            if line.startswith("|") and not line.startswith("|---")]
    mapped = [line for line in rows if "`legion 1.0.0" in line]
    assert len(mapped) >= 49, (
        f"the Legion row set is down to {len(mapped)} mapped rows, below what the field "
        "inventory needs. Raising this floor deliberately is fine; losing rows is not"
    )
    assert "`not yet`" not in section, (
        "a Legion row still says `not yet` while adapters/legion.py implements the row set. "
        "Either the row is genuinely unimplemented — in which case say which and why — or the "
        "document has fallen behind the code"
    )
    assert "legion 1.0.0" in _section("## The status column"), (
        "the status legend does not define the marker the rows use"
    )


LEGION_FIXTURES = sorted((pathlib.Path(synapse_cdm.__file__).resolve().parent
                         / "fixtures/legion").glob("*.json"))


def _uuids(value, found=None):
    """Every string in a document that parses as a UUID."""
    found = [] if found is None else found
    if isinstance(value, dict):
        for sub in value.values():
            _uuids(sub, found)
    elif isinstance(value, list):
        for sub in value:
            _uuids(sub, found)
    elif isinstance(value, str):
        try:
            found.append(uuid.UUID(value))
        except ValueError:
            pass
    return found


def test_the_legion_fixture_set_is_not_silently_empty():
    """A parametrised suite over a glob that matches nothing passes while testing nothing."""
    assert len(LEGION_FIXTURES) >= 6, (
        f"expected >=6 Legion fixtures, found {len(LEGION_FIXTURES)}")


@pytest.mark.parametrize("path", LEGION_FIXTURES, ids=lambda q: q.name)
def test_every_legion_fixture_identifier_is_a_version_8_uuid(path):
    """Synthetic only, and asserted rather than described — see the fixtures README.

    A UUID has no reserved test range, so the guarantee here is RFC 9562 §5.8: version 8 is for
    custom and experimental use, and a system issuing identifiers normally emits version 4 or 7.
    A real Legion id pasted in while debugging is therefore a build failure rather than something
    that ships, which is the same job the MID 299 and ICAO `0029xx` checks do for the other two
    fixture sets.
    """
    found = _uuids(json.loads(path.read_text()))
    assert found, f"{path.name} contains no identifiers at all — is it the right document?"
    wrong = [str(u) for u in found if u.version != 8]
    assert not wrong, (
        f"{path.name} carries {len(wrong)} non-version-8 identifier(s): {wrong}. Legion issues "
        "v4 and v7, so a v8 id cannot collide with a real one; anything else may be real"
    )
    off_scheme = [str(u) for u in found if not str(u).startswith("f1c7")]
    assert not off_scheme, (
        f"{path.name} carries identifier(s) outside the documented `f1c7` prefix: {off_scheme}"
    )


def test_the_legion_fixtures_exercise_both_documented_coordinate_systems():
    """The CRS is the largest hazard in the row set, so both readings need a fixture.

    One document must omit `crs` entirely — that is the case that decides whether an adapter
    honours the ECEF default or quietly reads GeoJSON order — and one must state EPSG:4326.
    """
    absent = "(absent — ECEF by default)"
    seen = set()
    for path in LEGION_FIXTURES:
        doc = json.loads(path.read_text())
        # The EFFECTIVE crs, which is not the same as the key being present on the object: a
        # list envelope declares `crs` once for all of `results`, so a result without its own is
        # covered by the envelope's and is NOT an exercise of the default. Getting this wrong
        # made the first version of this test unfalsifiable — the patrol list kept supplying the
        # "absent" marker no matter what the other fixtures said.
        envelope = doc.get("crs")
        for holder, inherited in ((doc, None),
                                  (doc.get("location_latest") or {}, None),
                                  *((r, envelope) for r in (doc.get("results") or []))):
            if isinstance(holder, dict) and "position" in holder:
                seen.add(holder.get("crs") or inherited or absent)
    assert absent in seen, (
        "no fixture omits `crs`, so nothing exercises the ECEF default — the single mapping "
        "an adapter is most likely to get wrong"
    )
    assert "EPSG:4326" in seen, "no fixture states EPSG:4326, so the lat/lon path is unexercised"
    assert "EPSG:4979" not in seen, (
        "a fixture uses EPSG:4979, which the row set refuses because no document defines its "
        "axis order. Remove it or resolve the refusal first"
    )


def test_the_legion_scope_decision_names_what_is_out_and_why():
    """An out-of-scope list without reasons is indistinguishable from an oversight."""
    section = _section(LEGION_HEADING)
    for resource in ("Tasking", "Feed Data", "Video streams", "WebRTC", "Notifications",
                     "Permissions", "Federation", "EPSG:4979"):
        assert resource in section, f"{resource!r} is not named in the Legion declines table"
    # The two structural refusals, which are the ones that carry an argument rather than a note.
    assert "PlanObject" in section and "geometry" in section, (
        "the Tasking decline must say WHY a task is not a PlanObject — geometry is required on "
        "that model and a task has none"
    )
    assert "Pagination is framing" in section, (
        "the pagination-versus-correlation line is the type-24 test applied to a REST API and "
        "is the scope decision this row set turns on"
    )


def test_the_gap_notes_are_referenced_from_the_table():
    text = DOC.read_text()
    for number in range(1, 13):
        assert f"**gap {number}**" in text or f"{number}. **" in text, (
            f"gap {number} is listed but never referenced from a table row"
        )
