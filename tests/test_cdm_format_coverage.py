"""FORMAT_COVERAGE.md claims the CDM carries what CoT, STANAG 4676 and GeoJSON need.

A mapping table is a promise to whoever writes the next adapter, and an unchecked promise about
field names rots on the first rename. So every path in the table's CDM column is resolved
against the real Pydantic models here. A renamed or removed field fails the build, which means
the table can be read as a specification rather than as a historical document.

The resolver walks pydantic annotations rather than dictionaries, so `Track.samples[].position.lat`
is checked all the way down to the float.
"""
import hashlib
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

    # ------------------------------------------------------------ the STANAG 4607 gaps
    #
    # Three gaps opened by adapter #8's row set, asserted the same awkward way round: the CDM must
    # still NOT have the field, so a gap quietly closed in code without the document being updated
    # fails the build.

    # Gap 20, detection versus tracked object. Asserted four ways because the four honest shapes
    # are very different — an Entity field, an EntityType member, an EventType member, or a fifth
    # canonical object — and the gap's whole argument is that choosing between them is the work.
    for field in ("observation_kind", "is_detection", "duration_s", "instantaneous"):
        assert field not in models.Entity.model_fields, (
            f"gap 20 (no detection/track distinction) appears to be closed — Entity.{field} now "
            "exists. Read that gap first: a GMTI target report has no identifier, no continuity "
            "and no successor, so its Entity.valid_to has no honest value and its entity_id ends "
            "in two positional ordinals. The fix is a decision about what the four kinds are for, "
            "not a boolean."
        )
    from synapse_cdm.enums import EntityType as _EntityType
    assert not any(m.name in ("DETECTION", "OBSERVATION", "CONTACT") for m in _EntityType), (
        "gap 20 appears to be closed with an EntityType member. That is one of the four shapes — "
        "and note the OTHER half of that gap, which is that twenty-one of D32.10's forty-three "
        "named classifications (Person, Animal, Beacon, Clutter, Phantom, Large Multiple-Return) "
        "have no honest EntityType either. Write the decision down before the member."
    )
    assert "detection" not in models.KINDS and "observation" not in models.KINDS, (
        "gap 20 appears to be closed with a fifth canonical object. Gaps 15, 19 and 20 are all "
        "asking the model to hold something that is not one of the four kinds — resolve them "
        "together, and note that deciding the four kinds are complete is also an answer."
    )

    # Gap 21, radar measurables. Asserted on Kinematics because a velocity COMPONENT would go
    # there, and on Entity because SNR and RCS are properties of the return rather than of the
    # object — which is the part of the gap that argues they belong on an Event instead.
    for field in ("radial_speed_mps", "range_rate_mps", "los_speed_mps"):
        assert field not in models.Kinematics.model_fields, (
            f"gap 21 (no radar measurables) appears to be closed — Kinematics.{field} now exists. "
            "A radial component is meaningless without the bearing it was measured along, so that "
            "field needs a frame beside it or it states a speed in a direction nobody named. This "
            "is NOT gap 4: a component is a projection, not a vector with elements missing."
        )
    for field in ("snr_db", "rcs_dbsm", "radar_cross_section"):
        assert field not in models.Entity.model_fields, (
            f"gap 21 appears to be closed on Entity — Entity.{field} now exists. Read the gap: an "
            "SNR and an RCS are properties of the RETURN, which argues they are Event payload and "
            "not Entity state — the same argument as gap 20's."
        )

    # Gap 22, negative information. Asserted on KINDS, on both enums a coverage statement could
    # plausibly become, and on PlanObject — because the gap's argument is that putting somebody
    # else's sensor footprint into the kind reserved for OUR plans is the wrong shape.
    for name in ("coverage", "observation_area", "surveillance"):
        assert name not in models.KINDS, (
            f"gap 22 (no negative information) appears to be closed with a {name!r} canonical "
            "object. That is one of the three honest shapes. Note the interaction with gap 14: a "
            "coverage statement is worthless without saying which sensor made it, and SourceRef "
            "cannot — so the two move together or the CDM gets a footprint with no owner."
        )
    assert not any(m.name.startswith(("COVERAGE", "SURVEIL", "NO_DETECT")) for m in _EventType), (
        "gap 22 appears to be closed with an EventType. That is the cheapest of the three shapes "
        "and it is defensible — it makes a non-observation an occurrence — but it needs the "
        "sensitivity fields (MDV, detection probability, false alarm density) and the footprint to "
        "go somewhere, and Event.payload is an untyped dict. Write it down in MIGRATIONS.md first."
    )
    assert not any(m.name.startswith(("COVERAGE", "SENSOR", "FOOTPRINT")) for m in _ObjectType), (
        "gap 22 appears to be closed with an ObjectType. Read the gap: PlanObject models OUR plan "
        "drawn on somebody else's map, and a foreign sensor's tasked bounding area is the reverse."
    )

    # Gap 23, an observation whose source states no time. Asserted on the REQUIREDNESS of
    # observed_at and on the absence of a canonical basis field, which are the gap's two proposals
    # — and the GMTIF adapter violates the field's docstring on three object kinds today, so this
    # is the one gap in the list whose interim is a known contract violation rather than a park.
    assert models.Event.model_fields["observed_at"].is_required(), (
        "gap 23 appears to be closed by making Event.observed_at optional. That is the cleaner of "
        "its two proposals and it pushes work onto every consumer that assumes a value — and "
        "models.Event.observed_at's \'Never receipt time\' docstring is part of the v1.0.0 "
        "contract, so it has to be edited in the SAME release. Update the gap, MIGRATIONS.md and "
        "the docstring together."
    )
    for field in ("observed_at_basis", "observed_at_source", "time_basis"):
        assert field not in models.Event.model_fields, (
            f"gap 23 appears to be closed with Event.{field} — a typed, mandatory basis beside the "
            "instant. That is the smaller proposal and it leaves the wrong value in place with a "
            "label, which is a real choice and not a lesser one. Write it down before the field."
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


def _flat(text: str) -> str:
    """The same text with every run of whitespace collapsed to one space.

    Prose in FORMAT_COVERAGE.md is hard-wrapped at 100 columns, so a phrase a test wants to pin is
    as likely as not to have a newline in the middle of it. Asserting against the raw text makes
    the test fail when a paragraph is re-flowed — an edit that changes nothing — and the usual
    repair is to shorten the asserted phrase until it fits on one line, which weakens the
    assertion for a formatting reason. Collapsing whitespace first lets the phrase be as long as
    it needs to be. Table rows are single lines and survive this unchanged, so row-level checks
    can use it too.
    """
    return " ".join(text.split())


def _subsection(heading: str) -> str:
    """One `###`-level block, from its heading to the next heading of the same or higher level.

    `_section` is too coarse for a check that has to be table-local. The GMTIF reserved-segment-code
    table has rows beginning `| 8 |`, and so does the D32.10 classification table, and so does the
    ambiguities table — so a "does code 8 have a row" assertion scoped to the whole section passes
    on any of the three, which is a green test proving nothing. This narrows it to the table.
    """
    text = DOC.read_text()
    start = text.index(heading)
    rest = text[start + len(heading):]
    ends = [o for o in (rest.find("\n## "), rest.find("\n### ")) if o != -1]
    return heading + (rest[:min(ends)] if ends else rest)


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


# ------------------------------------------------ the STANAG 4607 / AEDP-4607 (GMTIF) row set
#
# Adapter #8's row set is a SPECIFICATION: `adapters/gmtif.py` does not exist yet. These tests pin
# it in the ways available before there is code — the documents it was read from, the completeness
# of the field inventory it claims to cover, the settlements it turns on, the declines it makes,
# and the fact that every row still says `not yet`.
#
# The completeness test is the one with teeth, and it has to be a TRANSCRIPTION. GMTIF is a binary
# wire format: there is no XSD, no JSON schema and no machine-readable field list anywhere in the
# three pinned documents, so there is nothing to pin the way `test_every_pinned_legion_field_has_a_
# row` pins Legion's own hashed inventory. The inventory below is transcribed from the segment
# layout tables of AEDP-4607 Ed. A v1 (Tables 3-1, 3-6, 3-7, 3-9, 3-10, 3-12, 3-13, 3-14, 3-19,
# 3-20, 3-21, 3-22, 3-24, 4-1, 4-2) and is the same idea applied to a format that cannot be
# machine-checked: 212 field identifiers, and a missing row for any one of them fails the build.

GMTIF_HEADING = "## STANAG 4607 / AEDP-4607"

#: Every field of every header and segment, by the standard's own identifier, per segment layout
#: table. Container rows (D32, H32, C6) are included because the row set gives them a row: they
#: are where the "one Entity and one Event per target report" and "the array is parked" decisions
#: are stated, and a container with no row is a container nobody decided about.
GMTIF_FIELDS: dict[str, tuple[str, ...]] = {
    # Table 3-1
    "Packet Header": tuple(f"P{i}" for i in range(1, 11)),
    # Table 3-6
    "Segment Header": ("S1", "S2"),
    # Table 3-7
    "Mission Segment": tuple(f"M{i}" for i in range(1, 8)),
    # Table 3-9, including the D32 target-report container
    "Dwell Segment": tuple(f"D{i}" for i in range(1, 33)),
    # Table 3-10
    "Target Report": tuple(f"D32.{i}" for i in range(1, 19)),
    # Table 3-12, including the H32 scatterer container
    "HRR Segment": tuple(f"H{i}" for i in range(1, 33)),
    # Table 3-13
    "HRR Scatterer Record": tuple(f"H32.{i}" for i in range(1, 5)),
    # Table 3-14
    "Job Definition Segment": tuple(f"J{i}" for i in range(1, 29)),
    # Table 3-19
    "Free Text Segment": ("F1", "F2", "F3"),
    # Table 3-20
    "Test and Status Segment": tuple(f"T{i}" for i in range(1, 7)),
    # Tables 3-21 and 3-22
    "Processing History Segment": tuple(f"C{i}" for i in range(1, 7))
                                 + tuple(f"C6.{i}" for i in range(1, 7)),
    # Table 3-24
    "Platform Location Segment": tuple(f"L{i}" for i in range(1, 8)),
    # Table 4-1
    "Job Request Segment": tuple(f"R{i}" for i in range(1, 27)),
    # Table 4-2
    "Job Acknowledge Segment": tuple(f"A{i}" for i in range(1, 26)),
}

#: Every S1 value that is NOT one of the ten defined segment types. Each needs a row saying what
#: happens on encounter, because "no silent omissions" covers the value space and not only the
#: fields — a packet carrying segment type 8 has to have a documented outcome.
GMTIF_RESERVED_SEGMENT_CODES = ("4", "7", "8", "9", "11", "14–100", "103–127", "128–255")


def test_the_gmtif_row_set_names_the_documents_it_was_read_from():
    """An edition number names a document; a SHA-256 names the copy that was read.

    Three documents, and the third one is load-bearing rather than decorative: the standard defers
    the scale-factor choice to the guide in as many words, and the guide is where the delta-position
    arithmetic, the sensor-equals-platform-position statement and the refuse-versus-record split
    actually live. So the pin has to carry it, and the row set has to say what it took from it.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    for label, digest in (
        ("AEDP-4607 Ed. A v1, the target",
         "13f054c2bced1444aac9b5e85682b0b14b82f1d83988bf183f9324095c11a5d9"),
        ("AEDP-4607.1 Ed. A v1, the implementation guide and validation procedures",
         "877f9b6f1bbcd1ac76cddca751a7222deb5bcf8c8061e6530657eb68f655ed94"),
        ("STANAG 4607 Ed. 4, the ratification wrapper",
         "e102f47c51e74d26f61f02947df1228330e0ab6176b4b55c28447cf74574751b"),
    ):
        assert digest in section, f"the pin has lost its SHA-256 for {label}"
    assert "Edition A Version 1" in flat and "February 2024" in section
    assert "16 February 2024" in section, "the STANAG wrapper's date is part of the citation"
    assert "NOT PINNED" in flat, (
        "the pin must say that the Controlled Extension field definitions — five approved segment "
        "types whose Annex L.4 tables read '(TO BE PROVIDED)' — could not be obtained. A pin table "
        "that lists only what was pinned reads as if nothing was missing"
    )
    assert "(TO BE PROVIDED)" in flat, (
        "the exact words Annex L.4 uses are the evidence for the blocker; paraphrasing them makes "
        "the claim unverifiable against the document"
    )


@pytest.mark.parametrize("segment", sorted(GMTIF_FIELDS))
def test_every_gmtif_field_has_a_row(segment):
    """"Every field of every segment" made checkable instead of asserted.

    The failure this guards against is the one a 212-field binary format invites: writing the row
    set segment by segment and quietly skipping the fields that were hard to place — the HRR
    signature parameters, the nominal sensor values, the tasking segments. A skipped field is
    indistinguishable, in a finished document, from a field nobody had to think about.

    Matched on the identifier followed by a SPACE, which is what makes `D32.1` and `D32.10`
    distinguishable and `D3` and `D31` too. The row set's left column is `` `D32.10 Target
    Classification` ``, so the space is always there.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    missing = [f for f in GMTIF_FIELDS[segment] if f"`{f} " not in section]
    assert not missing, (
        f"{segment}: {len(missing)} field(s) from the segment layout table have no row: "
        f"{missing}. Map it or decline it with a reason; do not drop the row"
    )


def test_the_gmtif_row_set_is_the_size_a_212_field_format_needs():
    """A transcription can be complete field by field and still have lost whole tables.

    The per-segment test above passes if every identifier appears anywhere in the section, so it
    cannot see a row that was merged into another or a table that lost its header. This counts
    actual rows carrying the status marker, which is the thing a merged row destroys.

    The marker it counts changed when Phase 2 landed: it was `not yet` while the row set was a
    specification and it is `gmti 1.0.0` now that `adapters/gmtif.py` runs it.
    """
    section = _section(GMTIF_HEADING)
    rows = [line for line in section.splitlines()
            if line.startswith("| `") and "`gmti 1.0.0" in line]
    expected = sum(len(v) for v in GMTIF_FIELDS.values())
    assert expected == 212, f"the inventory itself has drifted: {expected} fields, not 212"
    assert len(rows) >= expected, (
        f"only {len(rows)} status-bearing rows for {expected} fields. Raising this floor "
        "deliberately is fine; losing rows is not"
    )


def test_the_gmtif_row_set_claims_the_adapter_that_now_implements_it():
    """The status column has to move when the code does, in BOTH directions.

    This test was the opposite of itself through Phase 1: it asserted that NO row said
    `gmti 1.0.0`, because a status marker claiming an adapter that does not exist is the one thing
    this table exists to prevent — and it is exactly what the Edition A STANAG 4676 placeholder had
    been doing for as long as it stood. `adapters/gmtif.py` now exists, so the risk is the inverse:
    a row still saying `not yet` is a shipped mapping nobody updated the document for. Inverted
    rather than deleted, so the reversal is readable in the history.
    """
    import synapse_cdm.adapters as _adapters
    module = pathlib.Path(_adapters.__file__).resolve().parent / "gmtif.py"
    codec_module = module.with_name("gmtif_codec.py")
    assert module.exists() and codec_module.exists(), (
        "adapters/gmtif.py or adapters/gmtif_codec.py is gone. If the adapter is being withdrawn, "
        "this test inverts back and every row returns to `not yet` in the same commit"
    )
    section = _section(GMTIF_HEADING)
    rows = [line for line in section.splitlines()
            if line.startswith("|") and not line.startswith("|---")]
    stale = [line for line in rows if "`not yet`" in line]
    assert not stale, (
        f"{len(stale)} GMTIF row(s) still say `not yet` while adapters/gmtif.py implements the row "
        f"set: {[r[:90] for r in stale[:3]]}"
    )
    assert "adapters/gmtif.py" in section and "adapters/gmtif_codec.py" in section, (
        "the row set must name both modules that implement it — the codec is a layer of its own "
        "with its own test suite, and a reader looking for the byte handling has to be sent there"
    )
    legend = _section("## The status column")
    for marker in ("`gmti 1.0.0`", "`gmti 1.0.0 · parked`", "`gmti 1.0.0 · egress`"):
        assert marker in legend, f"the legend does not define the marker {marker} the rows use"
    assert "· provisional" not in _flat(section), (
        "a `· provisional` qualifier has appeared on a GMTIF row. Unlike NITS, nothing here is "
        "provisional: a binary format's field offsets are fixed by the standard's own byte tables, "
        "those tables are in the pinned document, and the layouts are summed against them"
    )


def test_the_gmtif_settlements_are_each_recorded_by_name():
    """Eight named settlements, each of which an adapter author will otherwise re-decide.

    Asserted by name rather than by content because the failure mode is a settlement being edited
    away during implementation — the row set is reviewed once, as a specification, and the
    settlements are the part of it that is expensive to rediscover.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    for phrase in (
        "Edition A Version 1 is the only target",              # 1, the edition gate
        "the reference date is ON THE WIRE",                   # 2, time
        "the digraph is what makes them mean anything",        # 3, confidentiality
        "two payload declarations, one boolean",               # 4, simulation
        "a detection is not a track",                          # 5, identity
        "integer-domain delta recovery",                       # 6, positions
        "The existence mask is the schema",                    # 7, the mask
        "A translator owes no fusion",                         # 8, fusion
    ):
        assert phrase in section, f"the settlement headed {phrase!r} is gone from the row set"


def test_the_reference_date_is_read_from_the_wire_and_never_from_the_clock():
    """Settlement 2, and it is a DEPARTURE from the CAT021 precedent that has to stay stated.

    CAT021 takes the date from the injected clock because the format states none. GMTIF states one,
    in M5/M6/M7, and the clock must therefore never supply it — writing the receipt instant's date
    into a mission reference would date every dwell in the packet to the day we happened to read it
    and every other check would pass. The three paths are the whole of the decision.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "the injected clock is not the date source" in flat, (
        "the settlement heading must say it, because a reader who knows the CAT021 rule will "
        "assume it carries over"
    )
    for path in ("in_packet", "caller_supplied_stream_context"):
        assert path in flat, (
            f"the reference-date settlement no longer names the {path!r} path. A refusal with no "
            "stated alternative reads as 'a packet without a Mission Segment does not work', "
            "which is not the decision — the specification says mission context carries across "
            "packets in a stream, and the caller is the only thing that holds a stream"
        )
    assert "It supplies `Event.received_at` and nothing else in" in flat, (
        "the clock's entire remit in this adapter has to be stated in one place, or the second "
        "path above reads as permission to reach for it"
    )


def test_a_dwell_past_midnight_is_exact_addition_and_never_a_modulo():
    """Settlement 2's departure from the brief, pinned in the direction of the fallback it replaced.

    The brief for this row set stated a fallback — refuse, quoting the raw integer — for the case
    where the text was silent about dwells spanning midnight. The text is not silent: it says so in
    D6's own definition, in a note under the Reference Time fields, and in Annex C-3 with a worked
    example. So the rule is exact addition, and the risk is that an implementer meets a D6 of
    117,935,200 and "fixes" it with a modulo because it looks out of range.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "with the possible addition of multiples of 86400000 for multi-day missions" in flat, (
        "the standard's own words are the whole authority for exact addition. Losing the quote "
        "leaves the rule looking like a choice"
    )
    assert "117 935 200" in flat or "117,935,200" in flat, (
        "Annex C-3's worked example is what makes the rule checkable against the document, and the "
        "fixture set reproduces it — so the number has to be in the row set for the two to agree"
    )
    assert "no modulo" in flat.lower() or "not a modulo" in section.lower(), (
        "the forbidden repair has to be forbidden in as many words: a modulo silently moves every "
        "dwell of a multi-day mission back onto day one"
    )
    assert "46 days" in flat and "49 days" in flat, (
        "Table 3-9's stated range and Annex C-3's stated capacity disagree, and the row set "
        "resolves it by converting and recording. Both numbers belong in the ambiguity"
    )


def test_no_payload_field_sets_source_synthetic_in_gmtif_either():
    """Settlement 4. The STANAG 4676 amendment-B rule, held for a third format.

    The temptation here is stronger than it was for NITS, because P7 Exercise Indicator is
    MANDATORY on every packet and says 'real', 'simulated' or 'synthesized' in as many words. A
    rule that admits an exception whenever the payload field looks close enough is a default, not
    a rule.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    rows = [line for line in section.splitlines() if line.startswith("| `P7 ")]
    assert len(rows) == 1, f"the P7 Exercise Indicator row is missing or duplicated: {rows!r}"
    assert "`Entity.attributes`" in rows[0], (
        f"P7 must park, not map — it is a payload field and source.synthetic is a deployment "
        f"declaration. Row: {rows[0]!r}"
    )
    assert "does not set" in rows[0], (
        "the P7 row has to say so on the row, because that is where an implementer looks"
    )
    assert "logged refusal" in flat or "logged conflict" in flat, (
        "a parked P7 contradicting the deployment declaration is a refusal that names both "
        "values. Without it the rule has no teeth: the adapter would ignore the conflict"
    )
    # Amendment 2. Agreement is not an exception, and the mixture is not resolved onto the boolean.
    assert "INCLUDING AGREEMENT" in flat, (
        "amendment 2's operative words. The Phase 1 reading had `synthesized` 'agreeing with' a "
        "synthetic = true declaration, which is a payload field writing a deployment declaration "
        "whenever the two happen to match — a default with a conflict check bolted on, not a rule"
    )
    assert "writing a value that happens to match is still writing it" in flat, (
        "the reason, in one sentence. Without it the rule reads as a preference about which field "
        "wins rather than as the boundary CAT021 and 4676 amendment B both draw"
    )
    assert "parked visibly, NO refusal" in flat, (
        "the third branch. A P7 of `synthesized` means 'a mix of real and simulated data' in "
        "§3.1.7's own words, so it contradicts neither PURE declaration and must not be refused — "
        "refusing it would reject the case §3.1.7 exists to describe"
    )
    assert "a mixture is exactly what neither pure declaration describes" in flat, (
        "the mixture's reasoning has to come from the standard's definition of P7 = 2, not from "
        "SourceRef.synthetic's docstring. Reading the field's own definition to adjudicate a "
        "payload value is amendment B's forbidden move arrived at one step further back"
    )
    assert "true for anything not from a real source" not in flat, (
        "the Phase 1 justification is back: SourceRef.synthetic's docstring was used to resolve a "
        "payload value onto the boolean. Amendment 2 removed it, and it must not return"
    )
    # And the rule has to be the same rule the sibling row sets state.
    for other in (_section(CAT021_HEADING), _section(NITS_HEADING)):
        assert "synthetic" in other, (
            "a sibling row set no longer discusses source.synthetic, so the 'this is a rule, not "
            "a default' argument has lost the precedent it rests on"
        )


def test_the_target_classification_table_is_a_lookup_and_never_arithmetic():
    """Settlement 4's second half. `128 + n` is wrong for every n above 13, and 142 is not simulated.

    This is the finding that most repays being written down: the live and simulated halves of
    Table 3-11 mirror each other for codes 0-13 and then diverge by an inserted value, so an
    adapter computing `live = code - 128` reads Clutter-Simulated as Ground-Rotator-Live. Both of
    the codes that break the pattern were added or moved in Edition A, which is also the
    edition-gate argument.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    for code, wording in (("| 142 |", "Tagging Device"),
                          ("| 143 |", "Reserved"),
                          ("| 144 |", "Clutter, Simulated Target"),
                          ("| 127 |", "Unknown, Live")):
        row = [line for line in section.splitlines() if line.startswith(code)]
        assert row and wording in row[0], (
            f"the D32.10 row for {code.strip('| ')} is missing or has lost the standard's wording "
            f"({wording!r}); the enumeration must account for every value it names"
        )
    assert "+130, not +128" in flat, (
        "the offset trap is the reason this table is transcribed rather than computed. Losing the "
        "statement invites the arithmetic back"
    )
    assert "a tagging device is detected" in flat, (
        "D32.16's disjunction is the evidence that code 142 is NOT a simulated target, which is "
        "what exempts it from the intra-payload conflict check. Without the quote the exemption "
        "looks like a special case somebody invented"
    )
    assert "Exempt from the intra-payload simulation conflict check" in flat, (
        "the exemption has to be stated on the row it applies to"
    )


def test_the_two_simulation_conflict_checks_are_independent():
    """Settlement 4. Payload-versus-deployment and payload-versus-payload are different failures.

    The STANAG 4676 segment-ordering rule is the precedent: first-match-wins means a producer only
    ever hears about whichever check happened to run first, and a refusal that names the wrong
    cause is a guess wearing a refusal's clothes.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "intra-payload contradiction" in flat, (
        "a P7 of 'Operation, Real Data' carrying a simulated target report is a contradiction "
        "inside the payload, not with the deployment. Collapsing the two loses the only refusal "
        "that can name P7 = 2 as the value the producer needed"
    )
    assert "checked and reported independently" in flat, (
        "the independence is the point; without it the section describes two checks and one code "
        "path"
    )


def test_no_target_track_is_ever_emitted():
    """Settlement 5, asserted in the direction that would catch it being softened during Phase 2.

    Associating detections across dwells is what a GMTI tracker does, and the format's own
    implementation guide sends the reader to the sensor manufacturer for the rule. An implementer
    who has just written a working platform Track will find a target Track very easy to add.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "no target `Track` is emitted from" in flat or "no `Track` for any target, ever" in flat, (
        "the no-target-Track rule has been reworded or removed. It is the decision the identity "
        "settlement turns on and it is the format's whole difference from the other seven"
    )
    # The platform Track IS emitted, and the guide sentence is what licenses it. Both halves have
    # to stand, because the argument is that one is stated identity and the other is inference.
    assert "are assumed to be the same" in flat, (
        "guide §E.8's sentence is what makes one platform Track out of two segment types a reading "
        "rather than a merge. Losing the quote leaves the platform Track unjustified while the "
        "target Track is refused, which is the inconsistent-looking half"
    )
    assert "best recommended by the sensor manufacturer" in flat, (
        "the guide declining to specify the association rule is the strongest argument that a "
        "translator may not invent one"
    )
    # No row may put a target quantity into a Track.
    target_rows = [line for line in section.splitlines() if line.startswith("| `D32.")]
    assert target_rows, "the target report row table has disappeared"
    for row in target_rows:
        cdm_cell = [c.strip() for c in row.strip("|").split("|")][3]
        assert "Track." not in cdm_cell, (
            f"a target-report field is mapped into a Track: {row[:120]!r}. A GMTI detection has no "
            "history, and building one is fusion"
        )


def test_the_entity_key_admits_that_it_is_positional():
    """Settlement 5. The honest part of the identity decision is the part that says it is fragile.

    GMTIF guarantees no identifier below the job, so the target entity_id ends in two ordinals —
    and the format explicitly permits the re-segmentation that invalidates them. A row set that
    derived the key and did not say this would be claiming a stability the format does not offer.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "attributes.entity_key_basis" in flat, (
        "the derived key's components have to be recorded on the object, or a consumer cannot tell "
        "a stable id from a positional one"
    )
    assert "positional" in flat and "re-segmentation" in flat, (
        "the fragility is the finding. §3.4.32 and guide §D.2 both permit a dwell to be split "
        "differently on retransmission, which gives the same detection a different entity_id"
    )
    assert "within the dwell" in flat, (
        "D32.1 MTI Report Index states its own scope, and quoting it is what rules out the "
        "tempting reading that it is a report identifier"
    )


def test_the_position_arithmetic_is_stated_in_the_integer_domain():
    """Settlement 6. Guide §E.7 requires it, and a float-degrees implementation is wrong at the seam.

    The delta reconstruction is not "multiply and add in degrees". It is signed 32-bit arithmetic
    for latitude, unsigned 32-bit arithmetic for longitude, and the longitude case is REQUIRED to
    wrap — which is how a dwell straddling the prime meridian recovers at all.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "congruent" in flat and "mod 2^n" in flat, (
        "the guide's own requirement that unsigned overflow wrap is the authority for the "
        "longitude branch; without it the wrap looks like a bug being preserved"
    )
    assert "a latitude has no seam to wrap at" in flat, (
        "the asymmetry is the substance: longitude wrapping is correct and latitude wrapping is a "
        "defect, so one is converted and the other is refused"
    )
    assert "never two conversions with arithmetic in between" in flat, (
        "the rule an implementer needs in one sentence"
    )
    # The exclusive-or between the hi-res and delta pairs, which is where guessing almost works.
    assert "if and only if" in flat, (
        "the standard's own 'if and only if' governs D10/D11 against D32.4/D32.5, and it is what "
        "makes a delta report with no scale factors a refusal instead of a scale factor of zero"
    )


def test_the_height_unit_split_is_stated_on_the_rows_and_in_a_table():
    """Settlement 6. Two altitudes in centimetres and one height in metres, in the same packet.

    A single conversion factor applied to all three puts the target 100x too high or the platform
    100x too low, and neither error has a structural symptom. This is the cheapest possible test
    for the most likely possible bug.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    for field, unit in (("`D9 ", "**cm**"), ("`L4 ", "**cm**"), ("`D32.6 ", "**m**")):
        row = [line for line in section.splitlines() if line.startswith(f"| {field}")]
        assert row, f"the {field.strip('` ')} row is missing"
        assert unit in row[0], (
            f"the {field.strip('` ')} row must mark its unit emphatically: two of these three "
            f"fields are centimetres and one is metres, and the row is where an implementer looks"
        )
    assert "unit split" in flat, "the settlement must name the trap it is preventing"


def test_accuracy_m_is_none_everywhere_and_the_reason_is_recorded():
    """Settlement 6. Twelve uncertainty figures, not one of them a horizontal 1-sigma scalar.

    Asserted because D12 and D13 are the most reducible uncertainty pair in any format in this
    document — both horizontal, both 1-sigma, both centimetres, orthogonal — so this is where the
    discipline is most likely to be relaxed "just this once".
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    fills = [line for line in section.splitlines()
             if line.startswith("|") and "`Position.accuracy_m`" in line]
    assert fills, "the fills table has lost its Position.accuracy_m row"
    assert any("`None`, always" in line for line in fills), (
        "the fills table must state that accuracy_m is None on every object, not merely that "
        "individual fields park"
    )
    for row in [line for line in section.splitlines()
                if line.startswith("| `D12 ") or line.startswith("| `D13 ")
                or line.startswith("| `D32.12 ")]:
        assert "`Entity.attributes`" in row, (
            f"an uncertainty field has been mapped out of attributes: {row[:120]!r}"
        )
    assert "a slant is not a horizontal error" in section or \
           "a slant is not horizontal" in flat, (
        "D32.12's refusal needs its reason on the page: a line-of-sight standard deviation needs a "
        "grazing angle to become a ground error, and the format states none"
    )


def test_the_mask_discipline_keeps_absence_and_no_statement_apart():
    """Settlement 7. §2.4 creates a fourth category the existence mask cannot express.

    "For Mandatory Fields for which no information is being provided, a 'No Statement' value may be
    transmitted" — so a Mandatory field is always present and may still say nothing. A row set that
    collapsed that into "absent" would lose the difference between a source that did not send a
    field and a source that sent it to say it does not know.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "No Statement" in flat, "the fourth category has to be named"
    assert "the source sent it and said it does not know" in flat, (
        "the distinction is the finding, and it has to be stated rather than implied by a list of "
        "sentinels"
    )
    # The standard's own exception to its own mask rules, which desynchronises a reader that
    # misses it.
    assert "not present even if the existence mask indicates they are" in flat, (
        "§3.4.1's D5 = 0 exception makes a mask that claims target-report fields CONFORMANT when "
        "the count is zero. A reader that honours the mask instead consumes bytes belonging to the "
        "next segment, and the row set has to quote the exception"
    )
    # Amendment 5. The refuse-versus-record split no longer rests on guide Annex G Subtest 18,
    # which sits in the annex ambiguity 1 discredits, and now rests on whether the parse can
    # continue deterministically — a property the adapter can verify against §3.2.1 and §3.2.2.
    assert "whether the parse can continue deterministically" in flat, (
        "the re-grounded criterion. A row set cannot discredit an annex over its P6 table in one "
        "settlement and cite the same annex as authority in another, so the split has to stand on "
        "something checkable: whether the byte offsets of everything after the problem are known"
    )
    assert "Skipping is available where the format hands over a length and withheld where it does not" in flat, (
        "the criterion stated in one sentence, which is what an implementer will read"
    )
    assert "§3.2.1 is **silent** on receiver behaviour" in flat, (
        "the honest admission that there is no normative statement of the split anywhere in the "
        "pinned set. Without it the new grounding reads as a discovered rule rather than as a "
        "construction this row set is responsible for"
    )


@pytest.mark.parametrize("code", GMTIF_RESERVED_SEGMENT_CODES)
def test_every_reserved_segment_type_code_has_a_row(code):
    """"No silent omissions" covers the value space of an enumeration, not only the field list.

    A packet carrying segment type 8 has a documented outcome or it does not, and the CAT021 rule
    says it must. All eight of these resolve to the same behaviour — skip by S2, park, record — and
    that is precisely why it would be easy to leave them out.
    """
    # Table-local, not section-local: `| 8 |` also begins a D32.10 classification row and an
    # ambiguity row, so a section-wide check would pass on either and prove nothing.
    table = _subsection("### Row set — the reserved and extension segment type codes")
    rows = [line for line in table.splitlines() if line.startswith(f"| {code} |")]
    assert rows, (
        f"segment type code {code} has no row in the reserved-and-extension table saying what "
        "happens on encounter. Every S1 value that is not one of the ten defined segments needs "
        "one, and the CAT021 rule covers an enumeration's value space and not only its fields"
    )
    assert "skip" in rows[0] and ("park" in rows[0] or "parked" in rows[0]), (
        f"code {code}'s row no longer states the skip-by-S2-and-park behaviour. Annex G Subtest "
        "18's continue branch is what makes this a record rather than a refusal, and a row that "
        "does not say so leaves the outcome to whoever writes the parser"
    )


def test_the_controlled_extension_blocker_is_recorded_with_an_exit_condition():
    """Five approved extension segment types, and no pinned document defines any of them.

    This is the GMTIF equivalent of the STANAG 4676 XSD blocker and it is worse in one way: the
    document that should carry the field tables IS pinned, and the section is empty. A blocker with
    no exit condition is a caveat nobody can ever discharge.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    for name in ("Advanced Dwell", "Advanced Job Definition", "Advanced Platform Location",
                 "Target Centroid", "Releasability"):
        assert name in flat, (
            f"the registered Controlled Extension {name!r} is not named. Five are approved in "
            "guide Annex L.3.1 and a producer may emit any of them"
        )
    assert "blocked, with a stated exit condition" in flat, (
        "this is neither a deferral nor a rejection: the definitions do not exist to implement. "
        "Recording it as one of those would hide the only thing standing between this row set and "
        "a complete one"
    )
    assert "Exit condition" in flat, (
        "the steps that discharge the blocker have to be written down, in order, the way the NITS "
        "XSD blocker's five are"
    )


def test_the_gmtif_scope_decisions_say_deferred_rejected_or_blocked():
    """An out-of-scope list without reasons is indistinguishable from an oversight.

    And this row set needs three words rather than two: several of these are blocked on a document
    that does not exist rather than on anyone's judgement, and "deferred" would imply somebody
    could pick it up tomorrow.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    for out in ("Egress", "Edition 3", "Range-Doppler Segment", "Controlled Extension",
                "Job Request and Job Acknowledge", "signature data", "Reassembling a dwell",
                "Associating target reports across dwells", "terrain or geoid models",
                "DIS Entity State PDU", "NSIF", "Transport"):
        assert out in section, f"{out!r} is not named in the GMTIF declines table"
    for word in ("**deferred**", "**rejected**", "**blocked"):
        assert word in flat, (
            f"the declines table must use {word}: 'not supported' with no reason is what this "
            "column exists to stop, and the three are different promises"
        )
    assert "rejected as unimplementable" in flat, (
        "the four segments whose paragraphs read 'RESERVED FOR FUTURE DEFINITION' are not deferred "
        "— there is nothing to defer to — and the distinction is worth the extra word"
    )


def test_the_gmtif_ambiguities_are_recorded_rather_than_resolved_silently():
    """Fourteen findings, and the first three each change what an adapter does.

    Asserted on the ones whose loss would change behaviour rather than merely cost a reader time:
    the P6 double table (which is the whole argument for parking the label), the D6 range
    disagreement, and the truth-tag guard naming the wrong classification code.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "NOCONTRACT" in flat and "EUFOR" in flat, (
        "the two published codeword tables for P6 have to be quoted side by side. It is a "
        "demonstrated contradiction rather than an analogy, and it is the strongest argument in "
        "this row set for carrying rather than interpreting a classification"
    )
    assert "Edition 2, 2 August 2007" in flat, (
        "Annex G's own reference list is what explains the divergence — the validation annex was "
        "carried forward without being re-based on Edition A — and the cause is what tells a "
        "reader which table is stale"
    )
    assert "the truth tags guard on classification value `140`" in flat.lower(), (
        "the truth-tag discrepancy row is gone. It is what blocks the only SourceId candidate in "
        "the format, and amendment 6 keys it on the LABEL rather than on a value"
    )


def test_the_gmtif_gaps_are_referenced_from_the_row_set():
    """A gap opened by a row set that the row set never cites is a gap nobody will find.

    Three new gaps and eleven cross-referenced ones, and the row set has to point at each — the
    amendment-H discipline: where the finding is the same finding, say so rather than opening a
    fourteenth number.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    for gap in (1, 4, 6, 7, 8, 9, 12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23):
        assert f"**gap {gap}**" in flat.lower() or f"**Gap {gap}**" in flat, (
            f"gap {gap} is not cited anywhere in the GMTIF row set, and the row set is either "
            "opening it or sharpening it"
        )

def test_the_gmtif_rows_are_actually_resolved_against_the_models():
    """The whole point of the CDM-field column is that something checks it. Prove it is checked.

    `test_every_mapped_cdm_path_exists_on_the_models` is parametrised over the paths the parser
    found, so a section whose tables were headed `| GMTIF | ... | CDM | Status |` instead of
    `CDM field` would contribute ZERO paths and the parametrised test would stay green by
    contributing no cases. That is the failure mode this catches: a silent zero looks exactly like
    a clean pass.
    """
    doc = DOC.read_text()
    section = _section(GMTIF_HEADING)
    paths, column = [], None
    for line in section.splitlines():
        if not line.startswith("|"):
            column = None
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
    assert len(paths) >= 150, (
        f"the GMTIF section resolved only {len(paths)} CDM path cells. A 212-field row set that "
        "contributes almost nothing to the resolver has a table header the parser does not "
        "recognise — check that every mapping table says exactly 'CDM field'"
    )
    # The paths the settlements turn on, each of which would be the tell if a whole table were
    # dropped: the platform Track, the target position, the two velocity halves, and the three
    # fields the fills table pins to a constant.
    for required in ("Track.samples[].position.lat", "Track.samples[].observed_at",
                     "Position.lat", "Position.lon", "Position.alt_m",
                     "Kinematics.course_deg", "Kinematics.speed_mps", "Kinematics.climb_mps",
                     "Position.accuracy_m", "Entity.affiliation", "SourceRef.synthetic",
                     "Entity.entity_type", "Event.observed_at", "Event.received_at"):
        assert required in paths, (
            f"{required} is not among the paths the GMTIF section resolves. Either the row that "
            "should carry it has lost its CDM field, or its table's header no longer names the "
            "column — and in both cases the row stopped being checked against the models"
        )
    # And every one of them must be in the document-wide set the parametrised test walks.
    assert set(paths) <= set(PATHS), (
        "the GMTIF section resolves paths the document-wide parser does not see, which means the "
        "two disagree about where the tables are"
    )


# ------------------------------------------------------- the GMTIF Phase 1 amendments
#
# Seven amendments applied on review, still before any adapter code. Each is pinned here in the
# direction that would catch it being quietly reverted during Phase 2 — which is the risk a
# spec-first row set carries once someone is writing code against it and the original reading
# starts to look more convenient. Two of the seven overturned a Phase 1 reading, so those two are
# asserted BOTH ways: the new rule must be present and the old one must be absent.


def test_a_rotator_class_is_not_a_facility():
    """Amendment 1. `Stationary Rotator` and `Ground Rotator` are Doppler signature classes.

    Phase 1 mapped D32.10 codes 5, 16, 133 and 146 to FACILITY on the reasoning that a rotating
    antenna that does not move is a fixed structure — presented as the ADS-B/CAT021 obstacle
    exception reached through a third vocabulary. It is not that exception: ADS-B's category set C
    and CAT021's codes 22-24 NAME an obstacle, while a rotator class names the spectrum of a
    return. Inferring an installation from a motion characteristic is the inference this row set
    already refuses for M3 Platform Type.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    table = _subsection("#### `D32.10` Target Classification — every one of the 256 values accounted for")
    # The MAPPING column, not the row and not the prose: the amendment's own explanation names
    # FACILITY in order to say it is gone, and row 5's note states the reversal outright — both of
    # which a looser check would fire on. This is the 4676 TrackSegment test's discipline.
    mapping_rows = [line for line in table.splitlines()
                    if line.startswith("| ") and not line.startswith("|---")
                    and len(line.strip("|").split("|")) >= 3]
    offenders = [r for r in mapping_rows
                 if "FACILITY" in [c.strip() for c in r.strip("|").split("|")][2]]
    assert not offenders, (
        f"the D32.10 table has a FACILITY mapping again: {[r[:100] for r in offenders]}. "
        "Amendment 1 removed the only one this table claimed, and the collapse is now uniform: a "
        "vehicle, vessel or aircraft is a PLATFORM and everything else parks as UNKNOWN"
    )
    for code, wording in (("| 5 |", "Stationary Rotator, Live"),
                          ("| 16 |", "Ground Rotator Live"),
                          ("| 146 |", "Ground Rotator Simulated")):
        row = [line for line in table.splitlines() if line.startswith(code)]
        assert row and wording in row[0], f"the D32.10 row for {code.strip('| ')} is gone"
        assert "`UNKNOWN`" in row[0], (
            f"{wording!r} no longer maps to UNKNOWN: {row[0][:140]!r}. Amendment 1 reversed this "
            "and a reversion would put an installation claim behind a Doppler signature"
        )
    assert "Doppler signature class" in flat, (
        "the reason has to be stated, because 'Stationary Rotator' reads architectural and that is "
        "exactly the trap. It is a class of RETURN, not a class of object"
    )
    assert "refuses for `M3` Platform Type" in flat or "refuses for `M3`" in flat, (
        "the consistency argument is what makes this a rule rather than a taste: the row set "
        "already declines to read an inventory of NATO hardware as an affiliation, and reading a "
        "motion characteristic as an installation is the same move"
    )
    # The count moved, and the count is what a reader checks the table against.
    assert "eighteen of the forty-three named values" in flat, (
        "the mapped-value count was not updated with the amendment. Four values left the mapped "
        "set, so twenty-two became eighteen and twenty-one became twenty-five"
    )
    assert "the other twenty-five park" in flat, "the parked count was not updated either"


def test_the_person_divergence_from_cat021_is_deliberate_and_pinned():
    """Amendment 7. One concept, two answers, stated rather than resolved.

    D32.10 code 9 `Person, Live Target` maps to UNKNOWN here; CAT021's emitter category 16
    `Parachutist / skydiver` maps to PLATFORM in a SHIPPED adapter with a fixture and a golden file
    behind it. Both mappings are pinned so the question cannot be closed by accident in either
    direction, on the I021/170 precedent gap 2 uses for FAKER.
    """
    gmtif = _subsection("#### `D32.10` Target Classification — every one of the 256 values accounted for")
    person = [line for line in gmtif.splitlines() if line.startswith("| 9 |")]
    assert person and "Person, Live" in person[0], "the D32.10 person row is gone"
    assert "`UNKNOWN`" in person[0], (
        f"GMTI `Person, Live Target` no longer maps to UNKNOWN: {person[0][:140]!r}. If this is a "
        "deliberate change, it settles the divergence recorded in gap 20 and the gap, the CAT021 "
        "row and this test all move together"
    )
    cat021 = _section(CAT021_HEADING)
    para = [line for line in cat021.splitlines() if line.startswith("| 16 |")]
    assert para and "Parachutist" in para[0], "the CAT021 parachutist row is gone"
    assert "`PLATFORM`" in para[0], (
        f"the SHIPPED CAT021 adapter's parachutist mapping has changed: {para[0][:140]!r}. That is "
        "a published behaviour with a fixture and a golden file behind it, so changing it is a "
        "1.1.0 question with a migration note — not a side effect of an eighth adapter's row set"
    )
    # The divergence lives in the gap that owns the EntityType shortage, with BOTH arguments.
    gaps = DOC.read_text()
    gap20 = gaps[gaps.index("20. **No detection"):gaps.index("21. **No home for a radar")]
    flat20 = _flat(gap20)
    assert "Parachutist / skydiver" in flat20 and "Person, Live Target" in flat20, (
        "gap 20 must name both sides of the divergence. A loss recorded only in a row set is a "
        "loss nobody counting the cost of this gap will find"
    )
    assert "For `PLATFORM` (the CAT021 answer)" in flat20 and \
           "For `UNKNOWN` (the GMTIF answer)" in flat20, (
        "both arguments have to be written down, not just the one this row set took. Whoever "
        "settles this weighs them; inheriting a preference is what the I021/170 treatment exists "
        "to prevent"
    )
    assert "1.1.0" in flat20, (
        "the divergence is a 1.1.0 resolution question and has to say so, or it reads as an "
        "inconsistency somebody forgot"
    )
    # And it closes properly only when the enum grows the member both answers are working around.
    from synapse_cdm.enums import EntityType as _ET
    assert not any(m.name in ("PERSON", "DISMOUNT", "INDIVIDUAL") for m in _ET), (
        "EntityType has grown a member for a person, which is the honest resolution of the "
        "divergence rather than either mapping. Map both sides to it, update gap 20 and this "
        "test together, and write the migration note — the CAT021 change is the MINOR-bump half"
    )


def test_the_platform_track_parks_a_time_basis_per_sample():
    """Amendment 3. D6 is a dwell midpoint and L1 is an authoring instant; one Track holds both.

    The platform Track stands, but the mixed time semantics have to be visible on the samples or a
    consumer will interpolate across them. And the argument no longer rests on guide §E.8, which is
    silent about the instants and lives in the guide whose Annex G this row set discredits.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "attributes.platform_track_points[]" in flat, (
        "the per-sample record is the amendment. Without it a four-sample platform Track mixing "
        "dwell centres and report-preparation instants is indistinguishable from four homogeneous "
        "samples, and nothing in the CDM would show it"
    )
    for basis in ("dwell_center", "report_prepared"):
        assert basis in flat, (
            f"the {basis!r} time basis is not named. The two instants are different KINDS of "
            "instant — a midpoint of an unstated interval and a producer's authoring time — and "
            "the sample has to say which it is"
        )
    assert "would be mixing an observation midpoint with an authoring timestamp" in flat, (
        "the consequence, stated. It is why this is a settlement and not bookkeeping"
    )
    assert "attributes.platform_track_basis" in flat, (
        "the per-track summary has to exist too: a mixed track is the one a consumer must not "
        "smooth, and that fact belongs somewhere a consumer reads once rather than per sample"
    )
    # The re-grounding, asserted in both directions.
    assert "the standard's own field definitions are what license it" in flat, (
        "the platform Track's justification is now §3.4.6/§3.4.7 and §3.15.1/§3.15.2 — each "
        "segment states the platform's position AND the instant, under one Packet Header whose "
        "P3 + P8 identifies the platform uniquely. That is on the wire, in the standard"
    )
    assert "the guide is what licenses it" not in flat, (
        "the Phase 1 heading is back. Amendment 3 moved the argument off guide §E.8 because that "
        "sentence is about POSITIONS and says nothing about the instants — which is the half that "
        "decides whether two samples belong in one ordered list"
    )
    assert "It says **nothing** about `D6` versus" in flat, (
        "§E.8's limit has to be stated where §E.8 is cited, or a later reader will promote it back "
        "to an authority. It corroborates the position coincidence and carries no time semantics"
    )


def test_the_reference_date_provenance_is_per_instant_and_the_wire_is_not_overridden():
    """Amendment 4. Two conditions on the caller-supplied path, and one re-classification.

    (a) The path is recorded on every emitted instant, because a consumer holding an Event does not
    necessarily hold the Entity whose attributes explained it. (b) A Mission Segment contradicting
    the caller's argument is a refusal — neither silently wins. And the argument is a stand-in for
    absent wire context, NOT a deployment declaration, so it gets no amendment-B protection.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "payload.reference_date_basis" in flat, (
        "condition (a): an Event's observed_at is an absolute instant computed from the reference "
        "date, and the Event has to carry the provenance of that date itself"
    )
    assert "on every emitted instant, not once per packet" in flat, (
        "the condition stated as a rule. A basis on the owning Entity is not enough"
    )
    assert "must be distinguishable from one computed from a date it did" in flat, (
        "the reason, which is the whole point of recording it at all"
    )
    assert "Neither\nsilently wins" in section or "Neither silently wins" in flat, (
        "condition (b): a Mission Segment contradicting the caller's date is a refusal quoting "
        "both. Letting the wire win discards a caller statement that may indicate mis-tracked "
        "stream state; letting the argument persist lets a stale date override §3.3's own home "
        "for the answer. Both failures are silent"
    )
    assert "Identical values are not a contradiction" in flat, (
        "the case that would otherwise refuse a perfectly good packet: a caller confirming what "
        "the Mission Segment says is agreement, not conflict"
    )
    # The re-classification, asserted both ways.
    assert "is NOT a deployment declaration" in flat, (
        "amendment 4's third part. The Phase 1 text called the caller's date a deployment "
        "declaration and likened it to the 4676 configured confidentiality label, which gave it "
        "amendment-B protection against the wire that it must not have"
    )
    assert "the wire is its designated home" in flat, (
        "the distinction needs its reason: synthetic and a confidentiality label are facts about "
        "the DEPLOYMENT that no payload may contradict; a reference date is a fact about the "
        "MISSION whose designated home is the Mission Segment"
    )
    paths = _subsection("#### The Mission Segment may be in a different packet, and there are exactly three date paths")
    caller_row = [l for l in paths.splitlines() if "caller_supplied_stream_context" in l and l.startswith("|")]
    assert caller_row, "the caller path has lost its row in the three-paths table"
    assert "**A deployment declaration**" not in paths, (
        "the Phase 1 classification is back in the three-paths table"
    )


def test_reserved_segments_are_skip_and_record_and_never_a_silent_skip():
    """Amendment 5. The behaviour stands on §3.2.1 and §3.2.2, and the record is mandatory.

    The Annex G citation is struck — it is the annex this row set discredits over its P6 table — and
    the operative half is that a skipped segment must leave a trace. Otherwise a packet carrying an
    Advanced Dwell Segment nobody can decode is indistinguishable from one carrying nothing, and
    that particular segment's absence from the output would look like an empty dwell.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "skip-and-record" in flat, "the behaviour needs a name that includes the record"
    assert "never a silent skip" in flat, (
        "the forbidden case has to be forbidden in as many words, on every row and in the prose"
    )
    assert "The floor is the count, never nothing" in flat, (
        "the minimum has to be stated: where a deployment caps the parked byte volume, the type "
        "code, the size and a count still go in with the omission stated"
    )
    assert "would look like an empty dwell" in flat, (
        "the concrete consequence. `S1 = 128` is Advanced Dwell, so silently dropping it produces "
        "a plausible-looking dwell with no targets — which is gap 22's failure mode arriving "
        "through a parser shortcut"
    )
    # Grounded on the standard's own clauses, and NOT on the discredited annex.
    assert "§3.2.1 reserves those codes" in flat and "§3.2.2" in flat, (
        "the two clauses that carry the behaviour: the reservation says the adapter cannot decode "
        "them and S2 says exactly where they end"
    )
    assert "Annex G Subtest 18's \"continue\" branch rather than leniency" not in flat, (
        "the Phase 1 grounding is back in the reserved-codes table intro"
    )
    assert "struck every\n  citation of Annex G as *authority*" in section or \
           "struck every citation of Annex G as *authority*" in flat, (
        "the pin has to record that Annex G is read as evidence against itself and never as "
        "authority, or a later reader will cite it again"
    )
    # Every row states the behaviour including the record.
    table = _subsection("### Row set — the reserved and extension segment type codes")
    rows = [l for l in table.splitlines() if l.startswith("| ") and "|" in l[2:]
            and not l.startswith("| `S1`") and not l.startswith("|---")]
    assert len(rows) >= len(GMTIF_RESERVED_SEGMENT_CODES), "the reserved-codes table lost rows"
    for row in rows:
        assert "log and record" in row or "logged" in row, (
            f"a reserved-code row does not state the record: {row[:110]!r}. Skipping without "
            "recording is the one behaviour amendment 5 forbids"
        )


def test_the_tagging_device_exemption_is_keyed_on_the_label_not_the_number():
    """Amendment 6. The value has been 140, then 143, then 142 — so the rule keys on the label.

    Running the discrepancy down changed the grounds of a decline, and the row set says so. The
    prose was correct when written: guide Annex M.1 added `Tagging Device` at 140 and the very next
    errata item introduced the battery-strength sentence citing 140. The standard never re-based the
    number. So the condition is statable, and what blocks it is that stating it means making an
    editorial correction to a normative document.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "keyed on the LABEL" in flat, (
        "the exemption must be written against `Tagging Device`, not against 142. A rule keyed on "
        "the number silently changes behaviour the next time the value moves — and it has moved "
        "twice already"
    )
    # All four loci, so an erratum request can be written from this row alone.
    for locus in ("PDF page 45", "PDF page 47", "page M-9", "page M-31"):
        assert locus in flat, (
            f"ambiguity 3 no longer cites {locus}. The four loci are what make the trail "
            "checkable, and they are what an erratum request would have to quote"
        )
    assert "140 → 143 → 142" in flat, (
        "the trail in one line. Without it the discrepancy reads as a typo rather than as a stale "
        "cross-reference with a documented origin"
    )
    assert "it was correct when written" in flat, (
        "the finding that changes the grounds: the prose refers to the class, not to the number"
    )
    # The grounds are re-based rather than left standing, and the old reason is gone as a reason.
    assert "re-based the grounds" in flat, (
        "a decline whose strongest reason has been undermined has to be re-argued in the open, not "
        "left with a weakened argument in place"
    )
    assert "It is not unstatable." in flat, (
        "the Phase 1 reason was that the condition is unstatable. It is statable; the objection is "
        "now that stating it means re-basing a normative cross-reference, which is a custodian's "
        "act. Saying so is what keeps the decline honest"
    )
    assert "the wrong one is\n  the conformant one" in section or \
           "the wrong one is the conformant one" in flat, (
        "the precedent for declining an editorial correction is the 4676 row set using the "
        "acknowledged-wrong nga.gov namespace. Losing it leaves the refusal looking like timidity"
    )
    # And the disjunction still carries the exemption itself.
    assert "a disjunction is only meaningful if" in flat or \
           "a disjunction, which is only\n   meaningful if" in section, (
        "the exemption rests on D32.16/D32.17's own conditional, which is untouched by the "
        "provenance finding: the standard treats a tagging device as distinct from simulation"
    )


def test_the_gmtif_amendments_are_recorded_as_amendments():
    """Seven amendments, and a reversal nobody can see in the document is one nobody can review.

    The 4676 row set states its overturned Phase 1 decisions in the rows they changed rather than
    in a footnote, and this is the same discipline: the preamble counts them and each row that
    changed says which amendment changed it.
    """
    section = _section(GMTIF_HEADING)
    flat = _flat(section)
    assert "Seven amendments were applied on review" in flat, (
        "the section must say that it was amended and how many times, before a reader reaches a "
        "row that contradicts what they remember"
    )
    assert "The two overturned readings are visible in the rows they changed" in flat, (
        "the discipline, stated: a reversal recorded only in a commit message is a reversal the "
        "next reader of the document cannot audit"
    )
    for n in range(1, 8):
        assert f"amendment {n}" in flat.lower(), (
            f"amendment {n} is not cited anywhere in the row set. Each one changed something "
            "specific and the place it changed has to name it"
        )


# --------------------------------------------------- the pin records for the two NATO row sets
#
# THE PDFs ARE NOT TRACKED, SO THE PIN RECORD IS THE COMMITTED ARTEFACT
# ---------------------------------------------------------------------
# None of the nine adapters tracks its specification: `fixtures/*/spec/*.pdf` is untracked
# everywhere, deliberately, because NATO and EUROCONTROL documents are redistributable only on
# their own terms and a repository is not a document library. What gets committed instead is the
# pin record — filename, SHA-256, byte count, page count and the title-page identity as printed —
# and a pin record nothing checks is a recollection with a hash in it. So these two tests exist
# for the two halves that can be checked without the file and with it:
#
#   * the record is COMPLETE and in the right section — every field of every pin, asserted against
#     the prose. This runs everywhere, including on a clone that has never seen a PDF.
#   * the record is TRUE of the copy on disk — hash and byte count recomputed. This can only run
#     where the file is, so it SKIPS when the file is absent, and the skip names the file.
#
# The page count is deliberately not recomputed. Reading it needs a PDF library, this package has
# no PDF dependency and is not acquiring one for a test, and the byte count plus the hash already
# identify the copy exactly. A page count is there for a human comparing a document in their hands
# against this table, which is a different job from identifying bytes.
#
# Mutation-checked, all four ways, on the 2026-08-23 re-verification: a wrong digit in a byte
# count, a wrong page count, a filename pointing at the wrong document, and a digest moved from
# one section to the other each fail with the pin and the label named.

NATO_PINS = (
    ("gmti", "nato-stanag-4607-edition-4.pdf",
     "e102f47c51e74d26f61f02947df1228330e0ab6176b4b55c28447cf74574751b", 558_866, 6,
     "STANAG 4607 Ed. 4, the ratification wrapper"),
    ("gmti", "nato-aedp-4607-edition-a-v1.pdf",
     "13f054c2bced1444aac9b5e85682b0b14b82f1d83988bf183f9324095c11a5d9", 1_724_707, 104,
     "AEDP-4607 Ed. A v1, the target"),
    ("gmti", "nato-aedp-4607-1-edition-a-v1.pdf",
     "877f9b6f1bbcd1ac76cddca751a7222deb5bcf8c8061e6530657eb68f655ed94", 3_010_604, 212,
     "AEDP-4607.1 Ed. A v1, the implementation guide"),
    ("stanag4676", "nato-stanag-4676-edition-2.pdf",
     "5c74626102ca0b24735a98c6e0b67191d241afec075f2298c72e51b6223f8a9f", 255_250, 5,
     "STANAG 4676 Ed. 2, the ratification wrapper"),
    ("stanag4676", "nato-aedp-12-edition-b-v2.pdf",
     "c55573231a5882f031862b06589d5a7abaeda9cf7c0b7a55d81843eeb7dc138b", 6_785_016, 150,
     "AEDP-12 Ed. B v2, the target"),
    ("stanag4676", "nato-aedp-12-1-edition-a-v1.pdf",
     "7a4267fced81c760c8a8b487a70b9bb8507b9f765cb32bc4a0a97996b0c4341d", 6_815_298, 192,
     "AEDP-12.1 Ed. A v1, the implementation guide"),
)

#: Which section each pinned document's record belongs to. A digest in the wrong row set is the
#: failure this mapping exists to catch: the two NATO sections have the same table shape.
NATO_PIN_SECTIONS = {"gmti": GMTIF_HEADING, "stanag4676": NITS_HEADING}

FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures"


def _grouped(n: int) -> str:
    """`1724707` as `1 724 707`, which is how the pin tables spell a byte count."""
    return f"{n:,}".replace(",", " ")


@pytest.mark.parametrize("family,filename,digest,size,pages,label",
                         NATO_PINS, ids=lambda q: q if isinstance(q, str) else "")
def test_the_nato_pin_record_is_complete_and_in_the_right_section(
        family, filename, digest, size, pages, label):
    """Filename, SHA-256, byte count and page count, all four, all in the owning section.

    The filename is the field that was missing until the 2026-08-23 re-verification, and it is the
    one a reader needs most: a hash identifies a copy only if you can find the copy. `spec/` holds
    three PDFs per adapter with names that differ by two characters — `nato-aedp-4607-edition-a-v1`
    against `nato-aedp-4607-1-edition-a-v1` — so "the AEDP" is not a locator and the pin now says
    which file it means.
    """
    section = _section(NATO_PIN_SECTIONS[family])
    flat = _flat(section)
    assert f"`fixtures/{family}/spec/{filename}`" in flat, (
        f"the pin for {label} does not name its file. Without the path the hash identifies a copy "
        f"nobody can locate, and {family}/spec/ holds three documents with near-identical names"
    )
    assert digest in section, f"the pin has lost its SHA-256 for {label}"
    assert f"{_grouped(size)} bytes" in flat, (
        f"the pin for {label} has lost or changed its byte count. Expected {_grouped(size)} bytes"
    )
    # BOTH sites, not either: the page count is stated twice per document — in the pin table row
    # and in the re-verification table — and this assertion was written as a disjunction first,
    # which the mutation check killed. Breaking the pin row left the re-verification row matching,
    # so the test passed on a document whose two statements of the same fact disagreed. That is the
    # half-edited-sentence failure `test_cdm_prose_counts.py` exists for, reproduced here in one
    # test, and a fact stated twice has to be checked twice or the second site is decoration.
    assert f"{pages} pages" in flat, (
        f"the pin table row for {label} has lost its page count. Expected {pages}"
    )
    assert f"| {_grouped(size)} | {pages} |" in section, (
        f"the re-verification table row for {label} does not read `| {_grouped(size)} | {pages} |`. "
        "The pin table and the re-verification table state the same two numbers, and they have to "
        "agree — a half-updated pair reads as a record either way"
    )
    other = _section(NATO_PIN_SECTIONS["stanag4676" if family == "gmti" else "gmti"])
    assert digest not in other, (
        f"{label}'s digest appears in the OTHER NATO section as well. The two pin tables have the "
        "same shape, so a copy-paste between them is invisible on a read and fatal to the record"
    )


@pytest.mark.parametrize("family,filename,digest,size,pages,label",
                         NATO_PINS, ids=lambda q: q if isinstance(q, str) else "")
def test_the_pinned_nato_copy_matches_its_record_when_the_file_is_present(
        family, filename, digest, size, pages, label):
    """The other half: the record is true of the bytes, where the bytes are.

    Skips rather than fails when the PDF is absent, because absent is the NORMAL state — the specs
    are untracked and a fresh clone has none of them. A skip is honest here in a way it would not
    be for a prose check: this test makes no claim it cannot check, and the skip message names the
    file so that a reader who does hold the document knows what to drop in to make it run.
    """
    path = FIXTURES / family / "spec" / filename
    if not path.exists():
        pytest.skip(f"{path.relative_to(FIXTURES.parent)} is untracked and not present; "
                    f"drop the document in to verify {label} against its pin")
    raw = path.read_bytes()
    assert len(raw) == size, (
        f"{filename} is {len(raw)} bytes, and the pin for {label} says {size}. Either the pin is "
        "stale or this is a different copy of the same edition — which is exactly the difference "
        "an edition number cannot express and a hash can"
    )
    assert hashlib.sha256(raw).hexdigest() == digest, (
        f"{filename} does not hash to the pin recorded for {label}. Every citation in the row set "
        "is a claim about the copy that was read, and this is not it"
    )


def test_the_annex_l_reopen_condition_records_the_date_it_was_checked():
    """A blocker with a reopen condition has to say when the condition was last tested.

    The Controlled Extension blocker is the one park in this row set that a document revision can
    dissolve without anybody noticing, because §L.4 filling in is not an event this repository sees.
    So the check is a dated act, and the date is the artefact: "still blocked" with no date behind
    it is indistinguishable from "nobody has looked since 2024".

    The quote is asserted as well as the date. §L.4's exact words are the evidence, and the annex
    promising the tables in §L.2 and delivering nothing in §L.4 is what makes this a blocker rather
    than an omission — a paraphrase of either half loses the contradiction.
    """
    flat = _flat(_section(GMTIF_HEADING))
    assert "checked against the promulgated Edition A Version 1 text on 2026-08-23 and remains " \
           "unmet" in flat, (
        "the reopen condition must record the date it was last checked and the edition it was "
        "checked against. A blocker whose currency cannot be dated is a blocker nobody can retire"
    )
    assert "Section L.4 of this Annex provides the tables, descriptions, and rules of use for each " \
           "Controlled Extension." in flat, (
        "§L.2's promise is half the finding. Without it §L.4's silence reads as a section that was "
        "never meant to hold anything"
    )
    assert "(TO BE PROVIDED)" in flat, (
        "the exact words §L.4 uses are the other half, and paraphrasing them makes the claim "
        "unverifiable against the document"
    )
    assert "A populated record sheet is not a populated registry" in flat, (
        "§L.3.1 IS populated and §L.4 is not, and a reader who checks only the first will conclude "
        "the registry exists. The distinction is the blocker and it has to be stated"
    )


def test_the_nits_xsd_park_rests_on_configuration_management_not_on_procurement():
    """The park's reason was corrected on 2026-08-23, and the correction has to stay corrected.

    The original reason was "the file cannot be obtained here", which is a fact about this
    repository rather than about the standard — a reader with the right national representative
    dissolves it in a phone call, and the park would then be standing on nothing. Guide §D.1.1 is
    the reason that survives obtaining the file: the Custodian versions the XSD on its own axis,
    inside the file, so the AEDP edition does not name one schema. This test pins the corrected
    ground and the retracted overstatement together, because a correction that leaves the old
    sentence in place beside it has corrected nothing.
    """
    section = _section(NITS_HEADING)
    flat = _flat(section)
    assert "The XSD file contains the schema revision number, revision date, and change log." in flat, (
        "guide §D.1.1 is the ground this park now rests on, quoted. Summarising it loses the three "
        "things the exit condition has to record"
    )
    assert "the AEDP edition does not fix it" in flat, (
        "the consequence of §D.1.1 has to be stated, not left to the reader: 'the XSD for Edition B "
        "Version 2' does not name one artefact"
    )
    assert "APAN mirror" not in flat, (
        "the retracted claim is back. Ed B §B.5 names DiWEB and the guide's §D.1 names APAN; "
        "neither document mentions the other's channel and nothing says the two hold the same "
        "file, so calling one a mirror of the other asserts a link the pinned text does not"
    )
    assert "Neither document mentions the other's channel" in flat, (
        "what replaced the mirror claim has to say what is actually true of the two channels"
    )
    assert "the schema's own revision number and revision date from inside the file" in flat, (
        "the exit condition has to require the revision number, not just a SHA-256. A hash with no "
        "revision number cannot say which revision of a self-versioning document it identifies"
    )
    assert "The root element of a STANAG 4676 object in XML format must be the NITSRoot element " \
           "of type NITSRoot." in flat, (
        "guide §D.2's AEDP-12 Requirement callout is what settlement 1's root-element refusal now "
        "rests on, and it is the one syntax fact the XSD cannot move"
    )
    # Every cite in this park carries a PAGE, printed and PDF. Three of these four sentences were
    # challenged on 2026-08-23 by an independent read that had gone to the wrong section — §C.1.1
    # for §D.1.1, and a §D.6 wording that is not in the document — and a section number alone is
    # what made that possible. A page number is checkable by someone holding the PDF in a way a
    # section number is not, so it is now part of the citation rather than a courtesy.
    for cite, page in (("Edition B §B.5**, printed page B-4 (PDF page 144)", "B.5"),
                       ("Guide §D.1**, printed page D-1 (PDF page 156)", "D.1"),
                       ("Guide §D.1.1**, printed page D-1 (PDF page 156)", "D.1.1"),
                       ("guide §D.6**, printed page D-2 (PDF page 157)", "D.6"),
                       ("§C.1.1**, \"Configuration Management of the 4676 Data Model\", printed page "
                        "C-1 (PDF page 147)", "C.1.1")):
        assert cite in flat, (
            f"the §{page} citation has lost its page number. The challenge this park survived was "
            "possible because the cites named sections and not pages"
        )
    # The §C.1.1 / §D.1.1 distinction, which is the live way to get this park wrong.
    assert "§D.1.1 is not §C.1.1" in flat, (
        "the two configuration-management sections have to be distinguished in the prose. §C.1.1 "
        "comes first in the document, is about the DATA MODEL files, and gives no change log — a "
        "reader who stops there concludes this row set quoted a section that says something else"
    )
    assert "The files contain revision number and date." in flat, (
        "§C.1.1's own sentence is what makes the distinction checkable. Paraphrasing it leaves the "
        "reader with two section numbers and no way to tell which one this park needs"
    )
    # And the absence findings, which no section number can show.
    assert "neither phrase occurs anywhere in the pinned guide" in flat, (
        "the reported alternative §D.6 wording — the XSD as 'the normative reference for "
        "conformance' in a 'STANAG 4676 library' — is absent from the pinned guide, and the absence "
        "is the finding. A citation check that only ever confirms presence cannot refute a misquote"
    )
    assert "`DiWEB` and `Defense Investment` appear **nowhere** in the 192-page guide" in flat, (
        "the two-channels claim rests on each document NOT naming the other's channel, which is an "
        "absence and has to be stated as one"
    )


def test_the_2014_edition_is_recorded_as_history_and_never_as_a_basis():
    """AEDP-12 Edition A Version 1 exists, was examined, and is not a pin.

    The trap this guards is small and specific: the 2014 document has a hash in the pin table, and a
    hash in a pin table looks like a pin. It is there because the edition-delta settlement rests on
    having read the document, and the row that carries it has to say — in the same cell — that it is
    a watermarked reseller copy, that it is history rather than a target, and that it was NOT
    re-verified in the 2026-08-23 pass because it is not in `spec/`. An unqualified hash would make
    the row set claim four pinned documents where it has three.
    """
    section = _section(NITS_HEADING)
    flat = _flat(section)
    assert "Historical context only, and **never a basis**" in flat, (
        "the 2014 row's label is what stops its hash reading as a pin"
    )
    assert "NOT re-verified on 2026-08-23" in flat, (
        "the one line of the pin table the re-verification could not check has to say so. A "
        "re-verification that silently skips a row reads as a re-verification of every row"
    )
    assert "The incompatibility statement is §2.1.1.1, not the foreword" in flat, (
        "the locus matters: Edition B v2's FOREWORD says nothing about Edition 1, and a reader sent "
        "there to check settlement 1's premise would find nothing and conclude the premise was "
        "invented"
    )
    # And the settlement that depends on it still cites the right section.
    assert "§2.1.1.1" in flat, "settlement 1's citation of the incompatibility clause is gone"


@pytest.mark.parametrize("heading,numbers", [
    (GMTIF_HEADING, (18, 19)),
    (NITS_HEADING, (12, 13, 14)),
])
def test_the_pin_re_verification_filed_its_findings_in_the_ambiguity_registers(heading, numbers):
    """Five new findings, numbered per each register's own convention, prose left alone.

    The re-verification's job was to rule, not to edit: a date or edition discrepancy between a
    cover and its AEDP goes into the register at the next number and the normative prose stays as
    the custodian wrote it. So the check is that the numbers exist and are consecutive with what was
    already there — a finding recorded outside the register is a finding the next reader will
    re-derive from scratch.
    """
    section = _section(heading)
    for n in numbers:
        assert f"\n| {n} | **" in section, (
            f"ambiguity {n} is missing from the register. The 2026-08-23 re-verification filed "
            f"findings at {', '.join(str(x) for x in numbers)} and a register with a hole in its "
            "numbering is a register somebody has edited around"
        )
    assert f"\n| {max(numbers) + 1} | **" not in section, (
        f"the register has grown past {max(numbers)} without this test being updated. The numbers "
        "are the convention and a new finding has to extend it deliberately"
    )
