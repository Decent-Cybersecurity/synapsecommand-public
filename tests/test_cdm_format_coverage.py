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

    # Gap 13, per-measurement time. Asserted on Position and Kinematics because that is where a
    # measurement instant would naturally hang, and on Event because the twenty-three data ages
    # would need somewhere too. CAT021 states TWO applicability times in one record.
    for model in (models.Position, models.Kinematics):
        for field in ("observed_at", "measured_at", "age_s"):
            assert field not in model.model_fields, (
                f"gap 13 (no per-measurement time) appears to be closed — {model.__name__}."
                f"{field} now exists. Read that gap first: CAT021 states an applicability time "
                "for the POSITION and a different one for the VELOCITY in the same record, and "
                "I021/295 states twenty-three per-item ages besides. A time on two models "
                "covers the first and none of the second, so closing half of it silently is "
                "the risk."
            )
    assert "data_ages" not in models.Event.model_fields, (
        "gap 13 appears to be closed on Event — update FORMAT_COVERAGE.md and the I021/295 row."
    )

    # Gap 14, the producing sensor. SourceRef names the ADAPTER and the SYSTEM; CAT021 names the
    # ground station in every single record and the CDM has nowhere to put it.
    for field in ("sensor", "sensor_id", "station", "producer"):
        assert field not in models.SourceRef.model_fields, (
            f"gap 14 (no producing sensor) appears to be closed — SourceRef.{field} now exists. "
            "That gap is unproposed on purpose: a sensor is arguably an Entity of type SENSOR, "
            "and relating an observation to it needs a relation the CDM does not have — the "
            "same missing machinery as gap 11's hierarchy, and the two should be designed "
            "together or the CDM acquires two kinds of dangling pointer."
        )

    # Gap 15, intent. Asserted three ways because an intent could plausibly be added as a fifth
    # kind, as an ObjectType, or as an EventType — and the gap says the shape is the question.
    assert "intent" not in models.KINDS, (
        "gap 15 (no intent) appears to be closed with a fifth canonical object. Update "
        "FORMAT_COVERAGE.md, MIGRATIONS.md and the I021/110, I021/146, I021/148, REF/SelH and "
        "REF/NAV rows, which park their values today."
    )
    from synapse_cdm.enums import EventType as _EventType, ObjectType as _ObjectType
    assert not any(member.name.startswith("INTENT") for member in _EventType), (
        "gap 15 appears to be closed with an EventType. That is one of the two honest shapes — "
        "write the decision down in MIGRATIONS.md before the member."
    )
    assert not any(member.name.startswith("INTENT") for member in _ObjectType), (
        "gap 15 appears to be closed with an ObjectType. Read that gap first: PlanObject models "
        "OUR plan drawn on somebody else's map, and a target's declared future is not that."
    )


    # ------------------------------------------------------------ the STANAG 4676 gaps
    #
    # Four gaps opened by adapter #7's row set. Each is asserted the awkward way round, like the
    # rest: the CDM must still NOT have the field, so a gap quietly closed in code without the
    # document being updated fails the build.

    # Gap 16, no per-sample extension. Asserted on TrackSample because that is where a bag would
    # naturally go, and on Track because the Legion row set already found there is none there
    # either — and the gap's argument is precisely that the smallest diff (a dict on the CDM's
    # most-repeated object) is the wrong size.
    for field in ("attributes", "payload", "extras"):
        assert field not in models.TrackSample.model_fields, (
            f"gap 16 (no per-sample extension) appears to be closed — TrackSample.{field} now "
            "exists. Read that gap first: a NITS TrackPoint carries sixteen attributes and a "
            "thousand-point track would carry a thousand dicts, so the honest options are a bag "
            "here, a parallel per-sample structure on Track, or deciding that a rich track point "
            "is an Event with a position."
        )
    assert "attributes" not in models.Track.model_fields, (
        "gap 16 appears to be closed on Track — update FORMAT_COVERAGE.md, MIGRATIONS.md and the "
        "Legion envelope rows, which park a page's crs and paging on the owning Entity today "
        "precisely because Track has no bag."
    )

    # Gap 17, state-vector uncertainty. Asserted on Position and Kinematics because a covariance
    # would hang off one of them, and the gap says both plus gap 6 have to be designed together.
    for field in ("covariance", "covariance_matrix", "accuracy_matrix"):
        assert field not in models.Position.model_fields, (
            f"gap 17 (no state-vector uncertainty) appears to be closed — Position.{field} now "
            "exists. That gap is unproposed because a covariance is meaningless without the frame "
            "it was expressed in, and Position is always WGS84 geodetic — so the field needs a "
            "frame beside it or it states a matrix in units nobody named."
        )
    for field in ("covariance", "accuracy_mps", "uncertainty"):
        assert field not in models.Kinematics.model_fields, (
            f"gap 17 appears to be closed on Kinematics — Kinematics.{field} now exists. The "
            "velocity and acceleration terms are 15 of the 21 numbers in a NITS VEL3D matrix and "
            "are the part a consumer needs to judge a predicted position."
        )

    # Gap 18, confidence provenance and retraction. Asserted three ways because the gap has two
    # halves and the easy half is the one likely to be added alone.
    for model, field in ((models.Entity, "confidence_type"),
                         (models.Entity, "source_reliability"),
                         (models.Track, "quality_type")):
        assert field not in model.model_fields, (
            f"gap 18 (no confidence provenance) appears to be closed — {model.__name__}.{field} "
            "now exists. That is the EASY half. Read the gap: the hard half is retraction — a "
            "NITS Confidence.valid of FALSE withdraws a previously emitted object, and the CDM "
            "has no concept of one object superseding another."
        )
    for field in ("superseded_by", "retracted", "valid"):
        assert field not in models.Entity.model_fields, (
            f"gap 18's retraction half appears to be closed — Entity.{field} now exists. That "
            "touches identity, valid_to and whether a consumer holds state at all, and the row "
            "set carries retractions without applying them — so whatever closes this decides "
            "WHERE they are applied. Write that down before the field."
        )

    # Gap 19, no relation object. Asserted on CDMBase's subclasses and on KINDS, because the three
    # honest shapes are a list on the base, a fifth canonical object, or neither.
    for model in (models.Entity, models.Event, models.Track):
        for field in ("relations", "links", "related"):
            assert field not in model.model_fields, (
                f"gap 19 (no relation object) appears to be closed — {model.__name__}.{field} "
                "now exists. Gaps 11 and 14 both say they should be closed by whatever closes "
                "this one, so all three entries move together or the CDM acquires three kinds of "
                "dangling pointer."
            )
    assert "relation" not in models.KINDS, (
        "gap 19 appears to be closed with a fifth canonical object. That is one of the three "
        "honest shapes and it would also give gap 18's retraction somewhere to live — write both "
        "decisions down in MIGRATIONS.md before the object."
    )
    # The one relation the CDM does have, pinned: gap 19's whole argument is that it holds entity
    # ids and nothing else, so a NITS track linkage cannot go in it.
    assert "related_entities" in models.Event.model_fields, (
        "Event.related_entities has been renamed or removed. Gap 19 and the NITS TrackLinkage "
        "rows both argue from what it can and cannot hold; update them with it."
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
    for number in range(1, 20):
        assert f"**gap {number}**" in text or f"{number}. **" in text, (
            f"gap {number} is listed but never referenced from a table row"
        )


# ---------------------------------------------------------------- the CAT021 SAC pin
#
# The CAT021 row set is a SPECIFICATION, like the Legion one was before adapter #5 landed, and
# these tests pin the one part of it that rests on an external allocation list rather than on a
# ratified standard: the System Area Code its fixtures use.
#
# The first version of that decision was an assertion in a test on a value nobody had checked
# (`SAC = 0xFE`). That is worth stating because it is a trap the house style invites: an
# assertion on an unverified constant LOOKS like evidence, fails loudly when someone edits the
# constant, and never fails for the reason that matters — the constant being wrong to begin with.
# 0xFE turned out to be Nicaragua. So the assertions below sit on top of a pinned copy of the
# list rather than in place of one.
CAT021_HEADING = "## ASTERIX Category 021"

SAC_PIN = (pathlib.Path(synapse_cdm.__file__).resolve().parent
           / "fixtures/cat021/spec/sac_pin.json")


def _sac_pin() -> dict:
    return json.loads(SAC_PIN.read_text())


def _sac_entries(code: str) -> list[tuple[str, str]]:
    """Every (region, country_cell) the pinned copy shows for one SAC, across all six tables."""
    return [(region, country)
            for region, rows in _sac_pin()["extraction"]["tables"].items()
            for hex_code, country in rows
            if hex_code == code.upper()]


def test_the_sac_pin_names_the_document_it_was_read_from():
    """A pin that does not identify its source is a number, not evidence."""
    source = _sac_pin()["source"]
    assert source["url"] == "https://www.eurocontrol.int/asterix"
    assert source["retrieved_at"] == "2026-08-23T05:14:49Z"
    assert source["bytes"] == 142913
    assert len(source["sha256"]) == 64
    section = _section(CAT021_HEADING)
    assert source["sha256"] in section, (
        "the table and the pin file must name the same retrieved copy"
    )
    assert _sac_pin()["extraction"]["sha256"] in section, (
        "the extraction hash is the re-checkable half of this pin and belongs in the document"
    )


def test_the_sac_extraction_hash_matches_the_table_the_pin_carries():
    """The pin cannot drift against itself.

    This is the tooth of the whole amendment. Everything else here reads values out of the pin,
    so a hand-edited pin would satisfy all of it; recomputing the hash over the stored tables is
    what makes the stored tables the thing that was actually retrieved rather than a
    plausible-looking transcription of it.
    """
    pin = _sac_pin()
    canonical = json.dumps(pin["extraction"]["tables"], sort_keys=True, separators=(",", ":"))
    import hashlib
    recomputed = hashlib.sha256(canonical.encode()).hexdigest()
    assert recomputed == pin["extraction"]["sha256"], (
        "the pinned allocation table no longer hashes to the pinned extraction hash — either "
        "the table was edited by hand or the hash was. Re-fetch and re-extract; do not "
        "reconcile them by updating one to match the other"
    )
    assert sum(len(rows) for rows in pin["extraction"]["tables"].values()) == \
        pin["extraction"]["total_rows"]


def test_the_fixture_sac_is_unallocated_in_the_pinned_copy():
    """The claim the fixtures actually rest on, checked against the pinned list.

    `listed with an empty country cell` is the strong form of the claim — the page positively
    showing a code with no allocation, which is what ITU MID 299 gives the AIS fixtures. A code
    merely ABSENT from every table is the weak form and no fixture value may rest on one.
    """
    entries = _sac_entries("29")
    assert entries, (
        "SAC 0x29 does not appear in the pinned allocation tables at all. That is the WEAK form "
        "of the claim and the fixtures may not rest on it — see the pin's `reading` section"
    )
    assert all(country == "" for _, country in entries), (
        f"SAC 0x29 is allocated in the pinned copy: {entries}. The fixtures must move to a "
        "value the pinned copy shows as unallocated, and the evidence belongs in the commit "
        "message"
    )


def test_the_rejected_sac_values_are_still_allocated_in_the_pinned_copy():
    """The negative half, and the one that would have caught the original mistake.

    Without this, a future edit could quietly move the fixtures back to a comfortable-looking
    placeholder. Each of these three is a real state's allocation, and 0x00 is the one an
    uninitialised field produces.
    """
    for code, expected in (("FE", "Nicaragua"), ("FF", "Panama"), ("00", "LocalAirport")):
        entries = _sac_entries(code)
        assert entries and any(country for _, country in entries), (
            f"SAC 0x{code} reads as unallocated in the pinned copy, but this row set rejected "
            f"it as allocated to {expected!r}. The pin and the document disagree"
        )


def test_the_sic_claim_is_explicitly_weaker_than_the_sac_one():
    """SIC is operator-assigned within a SAC, so no list exists for it and none is pinned.

    Asserted because the failure mode is a reader taking the pin as evidence about both halves
    of the pair, which it is not and does not claim to be.
    """
    pin = _sac_pin()
    assert pin["fixture_sic"]["carries_no_allocation_claim"] is True
    section = _section(CAT021_HEADING)
    assert "no allocation claim at all" in section, (
        "the document must say that the SIC half of the pair rests on the SAC and not on a "
        "list of its own"
    )


# ------------------------------------------------------ the STANAG 4676 / AEDP-12 row set
#
# Adapter #7's row set is a SPECIFICATION: `adapters/stanag4676.py` does not exist yet. These
# tests pin it in the four ways available before there is code — the documents it was read from,
# the completeness of the model it claims to cover, the settlements it turns on, and the fact
# that every row still says `not yet`.
#
# The completeness test is the one with teeth. STANAG 4676 Edition B Version 2 is a full UML data
# model, not a field list, and "no silent omissions" is only a claim until something counts. The
# inventory below is transcribed from the Edition B attribute tables (§2.5, §2.6) and Annex D's
# alphabetical entity list, and it is the Legion `test_every_pinned_legion_field_has_a_row` idea
# applied to a model that has no machine-readable schema available to pin instead.

NITS_HEADING = "## STANAG 4676 / AEDP-12"

#: Every class in AEDP-12 Ed. B v2 Annex D, with the attributes its §2.5 / §2.6 table gives it.
#: Three classes are empty on purpose — the standard says so in as many words.
NITS_MODEL: dict[str, tuple[str, ...]] = {
    # 2.5 — MAIN
    "NITSRoot": ("profile", "streamUID", "fileUID", "fileLID", "lidScopeUID", "numFiles",
                 "msgCreatedTime", "nitsVersion", "product", "collection", "sensor", "tracker",
                 "message"),
    "ProductIdentification": ("uid", "lid", "id", "name", "shortName", "effectivity"),
    "CollectionInformation": ("uid", "lid", "intent", "essence", "targetID"),
    "SensorInformation": ("uid", "lid", "sensorID", "name", "description", "modality", "url",
                          "collectionMode", "absTimeUncertainty", "relTimeUncertainty", "comment",
                          "esmSensor", "imagingSensor", "radarSensor"),
    "ESMSensor": (),
    "RadarSensor4607": ("platformID", "missionID", "jobID"),
    "ImagingSensor": ("motionImageryCoreID", "frameHeight", "frameWidth", "fpaIndex", "filter",
                      "phenomenology", "band"),
    "TrackerInformation": ("type", "uid", "lid", "trackerID", "name", "description", "version",
                           "supplementaryData"),
    "SupplementaryData": ("type", "name", "version", "description"),
    "TrackMessage": ("numDetections", "numTracks", "baseTime", "relTimeIncrement", "dynSrcInfo",
                     "detection", "track", "processedTrack", "trackLinkage", "motionEvent"),
    "DynamicSourceInformation": ("uid", "lid", "relTime", "sensorUID", "sensorLID",
                                 "sensorLocation", "groupID", "numDetections",
                                 "numReportedDetections", "dynCFT", "sourceMI", "sourceRadar",
                                 "sourceESM"),
    "DynamicCFT": ("uid", "lid", "cft"),
    "CoordinateFrameTransformation": ("from", "translation", "rotation"),
    "MotionImageryInformation": ("frameBoundingBox", "frameNumber", "niirs", "vniirs", "sea",
                                 "tea", "gsd", "grd", "useableFOV", "processedFOV"),
    "RadarInformation": ("revisitIndex", "dwellIndex"),
    "ESMInformation": (),
    "Detection": ("uid", "lid", "relTime", "centroid", "outline", "sensorUID", "sensorLID",
                  "dynSrcUID", "dynSrcLID", "confidence", "source", "esm", "im", "radar", "sm"),
    "ESM": (),
    "Radar4607": ("reportIndex", "hrrType"),
    "Image": ("pixelMask", "centroidPixel", "color", "chip"),
    "ImageChip": ("type", "uri", "image"),
    "SensorMeasurement": ("quantity", "method", "value", "uncertainty"),
    "TrackData": ("uid", "lid", "trackSource", "segment", "object"),
    "TrackSource": ("sensorUID", "sensorLID", "trackerUID", "trackerLID", "collectionUID",
                    "collectionLID", "productUID", "productLID"),
    "TrackSegment": ("uid", "lid", "segmentSource", "confidence", "comment", "status",
                     "initiationReason", "terminationReason", "tp"),
    "TrackPoint": ("uid", "lid", "relTime", "dynSrcUID", "dynSrcLID", "associatedDetection",
                   "processType", "confidence", "comment", "outline", "outlineObscured",
                   "nearestConfuser", "nearestConfuserConfidence", "sm", "dynamics", "evidence"),
    "Dynamics": ("cs", "pos", "vel", "acc", "cov", "cftUID", "cftLID"),
    "Evidence": ("type", "subtype", "uid", "lid", "detectionUID", "detectionLID", "confidence"),
    "TrackedObject": ("uid", "lid", "description", "numberOfObjects", "objectColor", "confidence",
                      "dims", "priority", "iffCode", "objectClass", "idSourceInformation",
                      "id1241", "exampleDetectionUID", "exampleDetectionLID"),
    "IFFCode": ("value", "mode"),
    "ObjectClass": ("table", "entity", "entityType", "entitySubtype", "sector1Modifier",
                    "sector2Modifier", "code"),
    "IDSourceInformation": ("idQualityNumber", "sourceDeclarationBinary",
                            "sourceDeclarationExtension", "relTimeCreation", "relTimeExchange",
                            "idSourceNumber"),
    "IDSourceNumber": ("sourceType", "sourceSubtype", "sourceDeviceClass"),
    "ID1241": ("identity", "identityAmplification", "identitySourceModality", "environment"),
    "ProcessedTrack": ("type", "uid", "lid", "confidence", "inputUID", "inputLID", "outputUID",
                       "outputLID"),
    "TrackLinkage": ("type", "uid", "lid", "relTime", "confidence", "preUID", "postUID", "preLID",
                     "postLID"),
    "MotionEvent": ("type", "uid", "lid", "trackUID", "trackLID", "startRelTime", "endRelTime",
                    "confidence", "region", "tripwire"),
    # 2.6 — COMMON
    "Shape": ("dims", "cs", "cftUID", "cftLID"),
    "Polygon": ("nRings", "vertices"),
    "Ellipsoid": ("center", "ellipsoidParameters"),
    "PixelMask": ("pixelPolygon", "pixelRun"),
    "PixelPolygon": ("nRings", "integerArray"),
    "PixelRun": ("rs", "cs"),
    "IDData": ("stationID", "nationality"),
    "CovarianceMatrix": ("covarianceType",),
    "Confidence": ("type", "value", "sourceReliability", "valid"),
    "PositionPoints": ("dims", "cs", "points", "cftUID", "cftLID"),
    "UUID": ("gidp",),
}

#: The two classes whose payload is the element's own content rather than a named attribute.
NITS_CORE_VALUE_CLASSES = ("CovarianceMatrix", "UUID")


def test_the_nits_row_set_names_the_documents_it_was_read_from():
    """An edition number names a document; a SHA-256 names the copy that was read.

    Four documents, and the fourth is the interesting one: the 2014 edition is pinned as
    *compatibility context* and the row set is explicitly not built against it. Pinning a document
    you did not map from is unusual and it is the point — the edition-delta settlement rests on
    having read it.
    """
    section = _section(NITS_HEADING)
    for label, digest in (
        ("AEDP-12 Ed. B v2, the target",
         "c55573231a5882f031862b06589d5a7abaeda9cf7c0b7a55d81843eeb7dc138b"),
        ("AEDP-12.1 Ed. A v1, the implementation guide",
         "7a4267fced81c760c8a8b487a70b9bb8507b9f765cb32bc4a0a97996b0c4341d"),
        ("STANAG 4676 Ed. 2, the ratification wrapper",
         "5c74626102ca0b24735a98c6e0b67191d241afec075f2298c72e51b6223f8a9f"),
        ("AEDP-12 Ed. A v1 2014, compatibility context only",
         "a9e88c81369ff4f13a9d4d7e457de55c6cefcc024162efe5a198e395d8898814"),
    ):
        assert digest in section, f"the pin has lost its SHA-256 for {label}"
    assert "Edition B Version 2" in section and "March 2022" in section
    assert "13 October 2021" in section, "the STANAG wrapper's date is part of the citation"
    assert "NOT PINNED" in section, (
        "the pin must say that the XSD — normative for conformance, and distributed through "
        "national representatives — could not be obtained or hashed. A pin table that lists only "
        "what was pinned reads as if nothing was missing"
    )


@pytest.mark.parametrize("nits_class", sorted(NITS_MODEL))
def test_every_nits_class_and_attribute_has_a_row(nits_class):
    """"Every class and every attribute" made checkable instead of asserted.

    The failure this guards against is the one a 48-class model invites: writing the row set class
    by class and quietly skipping the attributes that were hard to place. A skipped attribute is
    indistinguishable, in a finished document, from an attribute nobody had to think about.

    Matched on the qualified form the row set uses in its left column (`TrackPoint.relTime`), not
    on the bare leaf, because a model this size reuses `uid`, `lid`, `type`, `name` and `value`
    across dozens of classes and a bare-leaf match would pass on any of them.
    """
    section = _section(NITS_HEADING)
    assert f"`{nits_class}" in section or f"**{nits_class}" in section, (
        f"{nits_class} is a class in AEDP-12 Ed. B v2 Annex D and is not mentioned in the row set "
        "at all. A class with no row is a class nobody decided about"
    )
    missing = [a for a in NITS_MODEL[nits_class] if f"`{nits_class}.{a}`" not in section]
    assert not missing, (
        f"{nits_class}: {len(missing)} attribute(s) from the Edition B table have no row: "
        f"{missing}. Map it or decline it with a reason; do not drop the row"
    )
    if not NITS_MODEL[nits_class]:
        assert "no attributes" in section, (
            f"{nits_class} has no attributes in the standard, and the row set must say so rather "
            "than leaving the class looking forgotten"
        )


def test_the_two_nits_core_value_classes_are_stated_as_such():
    """`UUID` and `CovarianceMatrix` carry their payload as the element's own content.

    Pinned because the attribute inventory above cannot express it — the value has no attribute
    name — so without this the two classes would look like a one-attribute and a zero-attribute
    class rather than what they are.
    """
    section = _section(NITS_HEADING)
    assert section.count("*(core class value)*") >= len(NITS_CORE_VALUE_CLASSES), (
        "the row set must name the core class value of "
        f"{', '.join(NITS_CORE_VALUE_CLASSES)} explicitly; the attribute tables in the standard "
        "list only their siblings"
    )


def test_the_nits_row_set_claims_its_adapter():
    """The status column has to move when the code does, in BOTH directions.

    This test was the opposite of itself through Phase 1: it asserted that NO row said
    `nits 1.0.0`, because a status marker claiming an adapter that does not exist is the one
    thing this table exists to prevent — and it is exactly what the Edition A placeholder this
    section replaced had been doing for as long as it stood. `adapters/stanag4676.py` now exists,
    so the risk is the inverse: a row still saying `not yet` is a shipped mapping nobody updated
    the document for.
    """
    section = _section(NITS_HEADING)
    rows = [line for line in section.splitlines()
            if line.startswith("|") and not line.startswith("|---")]
    mapped = [line for line in rows if "`nits 1.0.0" in line]
    assert len(mapped) >= 300, (
        f"the STANAG 4676 row set is down to {len(mapped)} mapped rows, below what a 48-class, "
        "273-attribute model needs. Raising this floor deliberately is fine; losing rows is not"
    )
    stale = [line for line in rows if "`not yet`" in line]
    assert not stale, (
        f"{len(stale)} STANAG 4676 row(s) still say `not yet` while adapters/stanag4676.py "
        "implements the row set. Either the row is genuinely unimplemented — in which case say "
        f"which and why — or the document has fallen behind the code: {stale[:3]}"
    )
    assert "nits 1.0.0" in _section("## The status column"), (
        "the status legend does not define the marker the rows use"
    )
    assert "adapters/stanag4676.py" in section, (
        "the row set must name the module that implements it"
    )


def test_every_nits_row_carries_the_provisional_qualifier():
    """The XML element binding is provisional, and the STATUS COLUMN has to say so on its own.

    A reader deciding whether to point a real feed at this adapter reads the status column, not
    the paragraph three sections up — and "provisional" is exactly the kind of caveat that gets
    read once and forgotten. So it is a marker on every flipped row, and this test is what makes
    deleting it from one row a build failure rather than an editing slip.

    It comes off in the same commit that pins the XSD, fills `ELEMENT_NAMES` from it and adds
    schema validation to the fixture build — the exit condition is spelled out in the
    declines-and-blockers table.
    """
    section = _section(NITS_HEADING)
    rows = [line for line in section.splitlines()
            if line.startswith("|") and "`nits 1.0.0" in line]
    assert len(rows) >= 300, f"only {len(rows)} rows carry a nits marker at all"
    unqualified = [line for line in rows if "· provisional`" not in line]
    assert not unqualified, (
        f"{len(unqualified)} STANAG 4676 row(s) claim the adapter without the `· provisional` "
        f"qualifier: {[r[:90] for r in unqualified[:3]]}. The XML element name these rows bind "
        "to is not pinned to anything — the XSD is distributed through NATO national "
        "representatives — so the status column must carry the caveat until it is"
    )
    legend = _section("## The status column")
    for marker in ("`nits 1.0.0 · provisional`", "`nits 1.0.0 · parked · provisional`",
                   "`nits 1.0.0 · egress · provisional`"):
        assert marker in legend, f"the legend does not define {marker}"
    assert "XSD validation of an emitted document" in section, (
        "provisionality with no stated exit condition is a caveat nobody can ever discharge; "
        "the blocker row is where the five steps that remove it are written down"
    )


def test_the_nits_settlements_are_each_recorded_by_name():
    """Eight named settlements, each of which an adapter author will otherwise re-decide.

    Asserted by name rather than by content because the failure mode is a settlement being edited
    away during implementation — the row set is reviewed once, as a specification, and the
    settlements are the part of it that is expensive to rediscover.
    """
    section = _section(NITS_HEADING)
    for phrase in (
        "Edition B Version 2 is the only target",          # 1, the edition delta
        "no rollover to reconstruct",                       # 2, time
        "the model is silent, the syntax is not",           # 3, confidentiality
        "plain-text XML in 1.0.0, EXI deferred",            # 4, encoding
        "STANDALONE is read and emitted",                   # 5, compliance profiles
        "three of them do not produce a Position",          # 6, coordinates
        "almost none of them is a name",                    # 7, identity
        "A translator owes no fusion",                      # 8, fusion
    ):
        assert phrase in section, f"the settlement headed {phrase!r} is gone from the row set"
    # The two that are load-bearing enough to assert on their substance, not their heading.
    assert "does not default to `baseTime`" in section, (
        "MotionEvent.startRelTime is the single exception to the model-wide rule that an omitted "
        "relTime means zero, and the exception is the standard's own words. Losing it means an "
        "adapter silently dates every timeless motion event to the message base"
    )
    assert "originatorConfidentialityLabel" in section and "TN-1491" in section, (
        "the confidentiality settlement must name the 4774 element that is mandatory on the root "
        "and the binding document, or 'carried, not interpreted' has nothing behind it"
    )


# ---------------------------------------------------------- the Phase 1 amendments
#
# Three Phase 1 decisions were overturned on review and one was split. Each is pinned here, in
# the direction that would catch it being quietly reverted during Phase 2 — which is the risk a
# spec-first row set carries once someone is writing code against it and the original reading
# starts to look more convenient.


def test_a_track_is_one_per_trackdata_not_one_per_tracksegment():
    """Amendment A. `TrackData` is the format's identity boundary; a segment is a subdivision.

    Ed B §2.5.25 defines a TrackSegment as points "adjacent in time" existing so a producer can
    invalidate a group, report status, or reassign source information for "a specific portion of
    the track" — and says a producer may put every point of a track in one segment if it likes.
    A row set that minted a track_id per segment would make the number of tracks a consumer sees
    depend on a producer's private chunking choice.
    """
    section = _section(NITS_HEADING)
    assert "One `Track` per `TrackData`" in section, (
        "the structural settlement has been reworded or reverted. It is the decision the whole "
        "row set turns on and every TrackSegment row depends on it"
    )
    assert "One `Track` per `TrackSegment`" not in section, (
        "the Phase 1 reading is back: one Track per TrackSegment was overturned because it makes "
        "track identity depend on how a producer chose to chunk its output"
    )
    rows = [line for line in section.splitlines()
            if line.startswith("| `TrackSegment.")]
    assert rows, "the TrackSegment row table has disappeared"
    for row in rows:
        # The CDM-field column, not the whole row: the uid row legitimately says "not a
        # `Track.track_id`" in its notes, which is the amendment being stated rather than undone.
        cdm_cell = [c.strip() for c in row.strip("|").split("|")][2]
        assert "Track.track_id" not in cdm_cell, (
            f"a TrackSegment attribute is mapped to Track.track_id again: {row[:120]!r}. "
            "A segment has no track identity under amendment A"
        )
    assert "attributes.nits_segments[]" in section, (
        "per-segment attributes have to land somewhere, and the settlement says a half-open range "
        "of sample indices on the owning Entity. Losing the key loses the segment structure"
    )
    # The cost of the amendment, which the row set is required to name rather than bury.
    assert "10 hypothesized tracks" in section, (
        "amendment A refuses a multi-hypothesis TrackData whose segments overlap in time. That is "
        "a real cost of the settlement and Ed B's own TrackSegment.confidence example describes "
        "the producer that pays it — the row set must keep naming it"
    )


def test_no_payload_field_sets_source_synthetic():
    """Amendment B. `SourceRef.synthetic` is a deployment declaration; essence is a payload field.

    The CAT021 row set states the rule for I021/040 SIM and the Legion row set for its EXERCISE_*
    identities. Phase 1 made an exception for CollectionInformation.essence on the grounds that it
    is a statement about the same thing; a rule with an exception whenever the payload field looks
    close enough is a default, not a rule.
    """
    section = _section(NITS_HEADING)
    rows = [line for line in section.splitlines() if line.startswith("| `CollectionInformation.")]
    assert rows, "the CollectionInformation row table has disappeared"
    for row in rows:
        assert "source.synthetic" not in row or "does not set" in row, (
            f"a CollectionInformation attribute maps to source.synthetic again: {row[:120]!r}"
        )
    essence = [r for r in rows if r.startswith("| `CollectionInformation.essence`")]
    assert len(essence) == 1 and "`Entity.attributes`" in essence[0], (
        "CollectionInformation.essence must park, not map — it is a payload field and "
        f"source.synthetic is a deployment declaration. Row: {essence!r}"
    )
    assert "logged refusal" in section or "logged conflict" in section, (
        "a parked essence contradicting the deployment declaration is a refusal that names both "
        "values. Without it the rule has no teeth: the adapter would simply ignore the conflict"
    )
    # The rule is only worth anything if it is the same rule the other row sets state.
    for other in (_section(CAT021_HEADING), _section(LEGION_HEADING)):
        assert "synthetic" in other, (
            "a sibling row set no longer discusses source.synthetic, so the 'this is a rule, not "
            "a default' argument has lost the precedent it rests on"
        )


def test_faker_and_joker_are_friendly_not_unknown():
    """Amendment C. Ed B defines FAKER and JOKER as friendly in the definition's first word.

    Phase 1 forced UNKNOWN on the argument that HOSTILE and FRIENDLY were both over-claims. They
    are not symmetric: HOSTILE contradicts the standard's definition and FRIENDLY restates it, so
    withholding was a third wrong answer and the one that lost information.
    """
    section = _section(NITS_HEADING)
    amplification = [line for line in section.splitlines()
                     if line.startswith("| `FAKER`") or line.startswith("| `JOKER`")
                     or line.startswith("| `KILO`")]
    assert len(amplification) == 3, (
        "the IdentityAmplification mapping table is gone or incomplete; all five literals need a "
        f"decision and the three friendly ones need a row. Found: {amplification!r}"
    )
    for row in amplification:
        assert "`FRIENDLY`" in row, (
            f"an IdentityAmplification literal Ed B defines as friendly does not map to FRIENDLY: "
            f"{row[:120]!r}"
        )
        assert "`UNKNOWN`" not in row, (
            f"the Phase 1 reading is back on {row[:40]!r} — FAKER/JOKER/KILO forcing UNKNOWN was "
            "overturned"
        )
    assert "attributes.exercise_role" in section, (
        "the exercise role is a SECOND fact, not an ambiguity, and it must be parked — otherwise "
        "a consumer cannot tell a FAKER from an ordinary friendly at all, which is worse than the "
        "reading this amendment replaced"
    )
    # TRAVELER and ZOMBIE are defined as SUSPECT, and amendment C's logic applies to them
    # symmetrically — so the question is whether the CDM has a member that carries it. It does
    # not, and the answer is pinned in both directions: the rows must not claim FRIENDLY, and
    # gap 2 must CITE them rather than receiving them silently.
    from synapse_cdm.enums import Affiliation as _Affiliation
    assert not hasattr(_Affiliation, "SUSPECT"), (
        "Affiliation has grown a SUSPECT member, so TRAVELER and ZOMBIE now have a value that "
        "honestly carries what they state. Map them to it, park the qualifier, and update gap 2 "
        "and this test together — routing a stated identity through a gap is the discard "
        "amendment C forbids"
    )
    for literal in ("`TRAVELER`", "`ZOMBIE`"):
        row = [line for line in section.splitlines() if line.startswith(f"| {literal}")]
        assert row and "`FRIENDLY`" not in row[0], (
            f"{literal} is defined as SUSPECT in Ed B and must not map to FRIENDLY: {row!r}"
        )
    gaps = DOC.read_text()[DOC.read_text().index("## Gaps, and what each one costs"):]
    gap_two = gaps[gaps.index("2. **Affiliation collapse"):gaps.index("3. **Track quality")]
    for literal in ("TRAVELER", "ZOMBIE"):
        assert literal in gap_two, (
            f"{literal} states an identity the CDM cannot hold, which is gap 2 — and the gap has "
            "to name it. A loss recorded only in a row set is a loss nobody counting the cost of "
            "this gap will find"
        )
    assert "symbology.AFFILIATION_FROM_COT" in gap_two and "legion.AFFILIATION" in gap_two, (
        "three adapters map FAKER/JOKER and one of them disagrees with the other two. The "
        "divergence belongs in the gap that owns affiliation, stated rather than resolved"
    )


def test_the_wgs84_velocity_conversion_states_both_branches():
    """Amendment D. Convert when the height axis is present; park when it is not.

    The radii of curvature are closed forms in (phi, h). Phi is always given; h is optional under
    Ed B's all-or-nothing third-axis rule, and h = 0 would be a fabricated input rather than a
    rounded one — so the row splits instead of choosing.
    """
    section = _section(NITS_HEADING)
    assert "Third axis present" in section and "Third axis omitted" in section, (
        "the WGS_84 kinematics row has to state both branches explicitly. A single sentence "
        "saying 'converted' hides the case where the conversion has no height to work from"
    )
    assert "fabricated input" in section, (
        "the parked branch's reason is that h = 0 is a fabricated input to the conversion, not a "
        "rounding of a real one. Without the reason the branch reads as an unfinished mapping"
    )
    # LOCAL_CARTESIAN must NOT split the same way: there the standard supplies the missing value.
    assert "shall set `L₃` equal to 0.0" in section, (
        "the row set must say why LOCAL_CARTESIAN does not split like WGS_84 — the standard "
        "mandates L3 = 0.0 for a 2-D local coordinate, so that zero is stated rather than assumed"
    )


def test_local_spherical_is_refused_as_an_unverifiable_convention():
    """Amendment E. The reason is a producer convention nothing in the data records.

    Not "a drafting error": the slot labelled azimuthal sits in the zenith position of the
    mandated equations, so a label-driven and an equation-driven producer both emit conformant
    documents that a consumer cannot tell apart, and both decode to a valid point on a sphere.
    """
    section = _section(NITS_HEADING)
    assert "unverifiable producer convention" in section, (
        "the LOCAL_SPHERICAL refusal must be stated as an unverifiable convention rather than as "
        "a defect in the text — the distinction is what makes it a refusal rather than a bug "
        "report, and it is what a custodian's clarification would resolve"
    )
    assert "zenith position" in section, (
        "the mechanism — the azimuthal-labelled slot appearing as the argument of z = r cos phi — "
        "is the whole evidence for the refusal"
    )
    assert "cannot be used to directly convert to a non-Cartesian coordinate system" in section, (
        "the standard's own note that the CFT cannot reach WGS 84 directly belongs here: it says "
        "the route is three hops and that the undetermined hop is the first one"
    )


def test_the_egress_label_paths_are_three_and_named():
    """Amendment F. Round-tripped, configuration-supplied, or refused. Never defaulted."""
    section = _section(NITS_HEADING)
    for path in ("round_tripped", "configuration_supplied"):
        assert path in section, (
            f"the egress confidentiality settlement no longer names the {path!r} path. A refusal "
            "with no stated alternative reads as 'egress does not work', which is not the decision"
        )
    assert "silent `UNCLASSIFIED` default remains forbidden" in section, (
        "the forbidden case has to stay forbidden in as many words. It is the only one of the "
        "three whose consequence is not a wrong pixel on a map"
    )



def test_the_nits_scope_decisions_say_deferred_or_rejected():
    """An out-of-scope list without reasons is indistinguishable from an oversight.

    And this row set has to go one further than Legion's: the brief for it was explicitly that a
    decline says *deferred* where deferred is the truth, because several of these are blocked on a
    document or on a custodian's erratum rather than on anyone's judgement.
    """
    section = _section(NITS_HEADING)
    for out in ("EXI encoding", "STANAG 4676 Edition 1", "DATASTREAM", "ECI_J2K",
                "LOCAL_SPHERICAL", "PIXELS", "MIIS Core Identifier", "AIDPP-01",
                "Mode 4 or Mode 5", "consolidation rule", "2525D SIDC"):
        assert out in section, f"{out!r} is not named in the STANAG 4676 declines table"
    assert "**deferred**" in section and "**rejected**" in section, (
        "the declines table must distinguish the two. 'Not supported' with no reason is what this "
        "column exists to stop, and 'deferred' and 'rejected' are different promises"
    )
    assert "blocked, not declined" in section, (
        "the XML syntax binding is blocked on an XSD distributed through national representatives "
        "and hashable nowhere in this repository. That is neither a deferral nor a rejection, and "
        "recording it as one of those would hide the only thing standing between this row set and "
        "Phase 2"
    )


def test_the_nits_row_set_does_not_reopen_the_placeholder_it_replaced():
    """The Edition A row set that stood here is gone, and must not come back by accident.

    Its class names are the tell: `trackUUID`, `trackNumber`, `trackPointPosition` and
    `IdentityIndicator` are Edition A, and a document asserting them alongside the Edition B model
    would be claiming two incompatible readings of one format.
    """
    rows = [line for line in DOC.read_text().splitlines()
            if line.startswith("|") and not line.startswith("|---")]
    for stale in ("TrackMessage/trackUUID", "Track/trackNumber",
                  "TrackPoint/trackPointPosition", "IdentityIndicator"):
        # In a ROW, not in prose: the edition-delta settlement quotes these names in order to say
        # they are gone, and a substring check over the whole file would fire on the explanation.
        offenders = [r for r in rows if stale in r.split("|")[1]]
        assert not offenders, (
            f"{stale!r} is an Edition A name and is back in a mapping row. The edition-delta "
            "settlement says a 2014 feed is a separate adapter, not a mode"
        )
    section = _section(NITS_HEADING)
    assert "supersedes the placeholder row set" in section, (
        "the section must record that it replaced an earlier table rather than silently deleting "
        "one; gap 3's premise was corrected in the same move and the trail has to be readable"
    )
