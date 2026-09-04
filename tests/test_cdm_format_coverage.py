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
import os
import pathlib
import uuid
import re
import types
import typing

import pytest
from pydantic import BaseModel

import synapse_cdm
from gates import parks_table, pin_paths
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

    - **It missed the egress tables entirely.** Those put the CDM path in column ZERO, so every
      `Position.lat`, `Kinematics.speed_mps` and `Track.samples[].position.lat` on an egress row
      went unresolved for as long as those rows had existed. A renamed field would not have failed
      the build. **Header-awareness made the fix POSSIBLE and did not by itself complete it**, and
      that distinction cost two more rounds: five egress tables went on being headed `CDM`, which
      names no column, so they went on contributing nothing. The egress-header ruling aligned all
      seven and `test_every_egress_table_heads_its_cdm_column_the_ruled_way` is what holds them
      there.
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


#: An EGRESS table's header: the CDM column first, the format second. Anchored on the format
#: column being a known format name rather than on the CDM column's spelling, so a table headed
#: the WRONG way still matches the collector and fails the agreement check — which is the whole
#: point. A collector that only recognised the correct form would report a mis-headed table as
#: absent, and absence is what this closure exists to make impossible.
EGRESS_HEADER = re.compile(
    r"^\|\s*(?P<cdm>CDM|CDM field)\s*\|\s*"
    r"(?P<format>AIS|ADS-B|CAT021|CAT023|CAT034|CAT048|CAT062|GMTIF|KLV|NITS)"
    r"\s*\|\s*Status\s*\|\s*Notes\s*\|$")

#: The ten formats with an egress row set of their own. `tak` is absent deliberately and it is
#: not an omission: its egress rows live INSIDE the ingress table, marked `· egress` in the status
#: column, because CoT egress emits the same element shape it ingests. `legion` and `pntmap` are
#: ingest-only. `stanag5527` is Phase 1 and specifies no egress table yet.
#:
#: `KLV` joined when adapter #10 shipped, and its format column says KLV rather than STANAG4609 for
#: the reason the fixture directory is `klv`: the format column names the BYTES and STANAG 4609 is a
#: five-page covering document. It is also the first egress table here written AFTER its adapter
#: rather than before, and the difference shows in the rows — every one of them describes octet
#: replay, which is a mechanism a specification written first would not have arrived at.
#:
#: CAT062 and CAT023 joined at PHASE 1, which is the case this roster had not met: their egress
#: tables are written before any code exists, so every row says `not yet`. That is exactly why
#: they have to be collected NOW rather than when the adapters land — an egress table nothing
#: reads is a row set whose CDM paths are never resolved against the models, which is the state
#: five of the first seven were in until the header ruling.
EGRESS_FORMATS = ("AIS", "ADS-B", "CAT021", "CAT023", "CAT034", "CAT048", "CAT062",
                  "GMTIF", "KLV", "NITS")


def _egress_headers() -> dict[str, list[tuple[int, str]]]:
    """`{format: [(line number, the CDM column's heading)]}`, collected from the document."""
    found: dict[str, list[tuple[int, str]]] = {}
    for number, line in enumerate(DOC.read_text().splitlines(), 1):
        match = EGRESS_HEADER.match(line.strip())
        if match:
            found.setdefault(match.group("format"), []).append(
                (number, match.group("cdm")))
    return found


def test_every_egress_table_heads_its_cdm_column_the_ruled_way():
    """THE DISJUNCTION, on a fact stated seven times — see "The egress header, ruled from what
    the rows state".

    The header is a SELECTOR and not a label: `_cdm_paths` reads the CDM column out of the index
    its table's header points at, so a table headed `CDM` contributes nothing and its rows are
    resolved against the models never. Five of the seven were in that state until the ruling, and
    two paths — `Track.entity_id` and `Track.source_ids[].external_id` — were consequently checked
    nowhere in the document at all.
    """
    headers = _egress_headers()
    wrong = {fmt: sites for fmt, sites in headers.items()
             if any(heading != CDM_COLUMN for _line, heading in sites)}
    assert not wrong, (
        f"these egress tables do not head their CDM column {CDM_COLUMN!r}: "
        + "; ".join(f"{fmt} at line(s) "
                    + ", ".join(str(line) for line, heading in sites if heading != CDM_COLUMN)
                    for fmt, sites in sorted(wrong.items()))
        + f".\nA column headed anything else contributes ZERO paths to _cdm_paths(), so its rows "
        "stop being resolved against the Pydantic models and a renamed field no longer fails the "
        "build. The ruling is in FORMAT_COVERAGE.md and it comes from the cells: they hold CDM "
        "field paths, which is what 'CDM field' names."
    )


def test_the_egress_header_closure_holds_in_both_directions():
    """A collector that reads eight of nine row sets agrees with itself about the ninth.

    Both directions, and the two failures are different. A format on the list with no table is a
    stale list — the shape `test_cdm_prose_counts.py` guards for its allowlist. A table the
    collector does not read is a row set nothing checks, which is the state all five aligned ones
    were in, so it is the direction that catches the real mistake.

    The second direction is derived rather than trusted: every `### Row set — egress` and
    `### Egress —` heading in the document must be followed by a table the collector matched.
    """
    headers = _egress_headers()
    assert set(headers) == set(EGRESS_FORMATS), (
        f"the egress-table roster and the document disagree: only in the roster "
        f"{sorted(set(EGRESS_FORMATS) - set(headers))}, only in the document "
        f"{sorted(set(headers) - set(EGRESS_FORMATS))}"
    )
    assert len(headers) == len(EGRESS_FORMATS), (
        f"{len(headers)} egress tables collected, expected {len(EGRESS_FORMATS)}"
    )

    # THE DIRECTION WITH TEETH: find the egress SECTIONS independently of the header regex, and
    # require each to contain a table the collector read. A new egress row set whose header the
    # collector cannot parse fails here rather than being silently skipped.
    lines = DOC.read_text().splitlines()
    matched_lines = {line for sites in headers.values() for line, _heading in sites}
    unread = []
    for number, line in enumerate(lines, 1):
        if not re.match(r"^#{3,4} (Row set — egress|Egress —)", line):
            continue
        # THE SECTION, and it ends at the NEXT heading rather than after a fixed number of
        # lines. A fixed window was tried and MUTATION KILLED IT: an egress section with an
        # unreadable header passed, because the window ran on into the next section and found
        # that one's header instead. A check whose evidence can come from a neighbour is not a
        # check on this section at all.
        end = next((n for n in range(number + 1, len(lines) + 1)
                    if lines[n - 1].startswith("#")), len(lines) + 1)
        if not any(number < n < end for n in matched_lines):
            unread.append(f"line {number}: {line.strip()[:80]}")
    assert not unread, (
        "these egress row-set headings are not followed by a table this collector can read:\n  "
        + "\n  ".join(unread) +
        "\nEither the header form changed and EGRESS_HEADER has to be re-anchored deliberately, "
        "or a new egress table was written with a header nothing checks."
    )


def test_the_egress_collector_is_not_vacuous():
    """A regex that matches nothing passes every agreement check above.

    Asserted two ways: the collector finds one table per listed format, and it PROVABLY
    recognises the wrong form —
    because a collector anchored on the correct spelling would report a mis-headed table as
    absent, and the closure would then read a real defect as a stale roster entry.
    """
    headers = _egress_headers()
    assert sum(len(sites) for sites in headers.values()) == len(EGRESS_FORMATS)
    assert EGRESS_HEADER.match("| CDM | CAT048 | Status | Notes |"), (
        "the collector no longer recognises the RETIRED header form, so a table that regressed to "
        "it would read as a missing table rather than as a wrong one"
    )
    assert EGRESS_HEADER.match("| CDM field | CAT048 | Status | Notes |")
    assert not EGRESS_HEADER.match("| CAT048 | CDM field | Status | Notes |"), (
        "the collector matches an INGRESS header, so it is no longer selecting egress tables"
    )


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
# No adapter here tracks its specification: `fixtures/*/spec/*.pdf` is untracked
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
    ("nits", "nato-stanag-4676-edition-2.pdf",
     "5c74626102ca0b24735a98c6e0b67191d241afec075f2298c72e51b6223f8a9f", 255_250, 5,
     "STANAG 4676 Ed. 2, the ratification wrapper"),
    ("nits", "nato-aedp-12-edition-b-v2.pdf",
     "c55573231a5882f031862b06589d5a7abaeda9cf7c0b7a55d81843eeb7dc138b", 6_785_016, 150,
     "AEDP-12 Ed. B v2, the target"),
    ("nits", "nato-aedp-12-1-edition-a-v1.pdf",
     "7a4267fced81c760c8a8b487a70b9bb8507b9f765cb32bc4a0a97996b0c4341d", 6_815_298, 192,
     "AEDP-12.1 Ed. A v1, the implementation guide"),
)

#: Which section each pinned document's record belongs to. A digest in the wrong row set is the
#: failure this mapping exists to catch: the two NATO sections have the same table shape.
#: Keyed on the FIXTURE DIRECTORY name, not the adapter name — they differ for this one
#: adapter (`stanag4676` translates, `fixtures/nits` holds its fixtures and its pins), and
#: keying on the adapter name is exactly the slip that put the pins in the wrong directory.
NATO_PIN_SECTIONS = {"gmti": GMTIF_HEADING, "nits": NITS_HEADING}

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
    other = _section(NATO_PIN_SECTIONS["nits" if family == "gmti" else "gmti"])
    assert digest not in other, (
        f"{label}'s digest appears in the OTHER NATO section as well. The two pin tables have the "
        "same shape, so a copy-paste between them is invisible on a read and fatal to the record"
    )


def test_no_text_points_at_the_old_nits_spec_directory():
    """One adapter, one spec directory, and the document has to agree with itself about which.

    The pins were briefly in `fixtures/stanag4676/spec/` — the adapter is `stanag4676`, its
    fixtures are `nits`, and a copy command took the adapter's name — which left the pin record
    and the XSD exit condition four hundred lines apart naming two different directories for the
    same adapter's specs. Both statements were individually true, which is why nothing caught it:
    a contradiction between two accurate sentences is invisible to any check that reads one at a
    time. This one reads both.
    """
    doc = DOC.read_text()
    section = _flat(_section(NITS_HEADING))
    # EXACTLY ONE occurrence, and it is the sentence recording the move. Not zero: this document
    # states its reversals in the place they changed rather than in a commit message — the seven
    # GMTIF amendments and the three overturned NITS decisions are all written down where they
    # apply — and a correction that cannot name what it corrected is one the next reader repeats.
    # So the invariant is "no LIVE path", not "no mention", and the difference is checked.
    occurrences = doc.count("fixtures/stanag4676")
    assert occurrences == 1, (
        f"{occurrences} references to `fixtures/stanag4676`, expected exactly 1 — the historical "
        "sentence recording the move. More than one means a live path is back; zero means the "
        "correction stopped saying what it corrected, and the pins go back to the wrong directory "
        "the next time somebody reads the adapter's name off the roster"
    )
    assert "They were briefly in a `fixtures/stanag4676/spec/` of their own" in section, (
        "the single permitted occurrence is not the historical one any more. Whatever now carries "
        "that path is pointing at a directory that does not exist"
    )
    # And it is nowhere a pin row or an exit condition could pick it up.
    for line in doc.splitlines():
        if "fixtures/stanag4676" in line:
            assert "briefly" in line, f"a non-historical use of the old path: {line[:120]}"
            assert not line.startswith("|"), (
                f"the old path is in a TABLE ROW, which is where pin records live: {line[:120]}"
            )
    # The pin record and the exit condition, checked against each other rather than each alone.
    # EVERY mention, not "at least one": `xsd_pin.json` is named twice — the syntax-binding row
    # and the XSD-validation row both carry the exit condition — so an `in` check passes with one
    # of the two re-pointed. Same shape as the page-count disjunction the mutation check killed
    # earlier: a fact stated twice has to be checked at every site or the second one is decoration.
    pin_paths = re.findall(r"`fixtures/[A-Za-z0-9_./-]*xsd_pin\.json`", DOC.read_text())
    assert len(pin_paths) == 2, (
        f"expected the XSD pin path at 2 sites, found {len(pin_paths)}: {pin_paths}. The "
        "syntax-binding row and the XSD-validation row both state it"
    )
    assert set(pin_paths) == {"`fixtures/nits/spec/xsd_pin.json`"}, (
        f"the XSD exit condition sites disagree about where the pin goes: {sorted(set(pin_paths))}. "
        "They must name the same directory the pin record names, or the fix for this park sends "
        "two readers to two places"
    )
    assert "`fixtures/nits/spec/nato-aedp-12-edition-b-v2.pdf`" in section, \
        "the pin record has lost its path for the target document"
    assert "They were briefly in a `fixtures/stanag4676/spec/` of their own" in section, (
        "the correction has to say what moved and why, or the next person to add a pin for this "
        "adapter reads the adapter's name off the roster and repeats it"
    )


def _nato_pin_path(family: str, filename: str) -> pathlib.Path:
    """Where a pinned NATO document lives, in ONE place rather than at each caller.

    A function rather than an expression inline, because the expression is the thing that was
    wrong: written out at its only call site it read correctly and resolved to
    `fixtures/klv/gmti/spec/…`, and nothing compared it against the directory the pin record
    names. Named and called, it is something a test can assert about without the PDF being here.
    """
    return FIXTURES / family / "spec" / filename


def _the_copy_matches_the_pin(raw: bytes, filename: str, digest: str, size: int,
                              label: str) -> None:
    """Byte count then hash, in one place so a synthetic-bytes companion can exercise the REAL one.

    Extracted for that reason alone: the six real comparisons run only where somebody holds six
    untracked PDFs, so a copy of this arithmetic in a companion would prove the copy works. The
    companion calls this.
    """
    assert len(raw) == size, (
        f"{filename} is {len(raw)} bytes, and the pin for {label} says {size}. Either the pin is "
        "stale or this is a different copy of the same edition — which is exactly the difference "
        "an edition number cannot express and a hash can"
    )
    assert hashlib.sha256(raw).hexdigest() == digest, (
        f"{filename} does not hash to the pin recorded for {label}. Every citation in the row set "
        "is a claim about the copy that was read, and this is not it"
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

    THE SKIP WAS DISHONEST FOR THE WHOLE OF ITS LIFE ANYWAY, and not because of anything above.
    A second module-level `FIXTURES` three hundred lines down (now `KLV_FIXTURES`, see the comment
    there) meant this body resolved `fixtures/klv/gmti/spec/…`, so the guard was permanently true:
    six skips reporting six absent documents while all six sat in `spec/` matching their pins to
    the byte. The two companions below are what a permanently-true guard has to fail against —
    `_nato_pin_path` is asserted to point where the pin record says, and the comparison itself is
    exercised on synthetic bytes so it cannot be dead code in a tree that holds no PDFs.
    """
    path = _nato_pin_path(family, filename)
    if not path.exists():
        pytest.skip(f"{path.relative_to(FIXTURES.parent)} is untracked and not present; "
                    f"drop the document in to verify {label} against its pin")
    _the_copy_matches_the_pin(path.read_bytes(), filename, digest, size, label)


@pytest.mark.parametrize("family,filename,digest,size,pages,label",
                         NATO_PINS, ids=lambda q: q if isinstance(q, str) else "")
def test_the_pin_locator_finds_every_pinned_document_that_is_in_this_tree(
        family, filename, digest, size, pages, label):
    """The guard above may be true of a fresh clone; it may not be true of nothing.

    A test that skips itself reports the same thing whether the document is absent or the code is
    looking in the wrong place, and this repository ran for several rounds in the second state.
    So the locator is checked independently of whether any PDF is here:

    * the directory it names EXISTS — `fixtures/<family>/spec/` is tracked (each holds a
      `build_fixtures.py`), so this holds in a fresh clone and fails the moment the locator is
      re-pointed at a directory that is not the one the pin record names;
    * and the locator agrees with `spec/`'s own listing about whether this document is here.
      `.exists()` on a wrong path is False; so is `.exists()` on a right path for an absent
      document; the difference is invisible from inside the guard and visible from here.

    Which makes this the check a permanently-true skip condition fails against. That is the
    property the skip needed and did not have.
    """
    spec = FIXTURES / family / "spec"
    assert spec.is_dir(), (
        f"the pin locator points at {spec}, which is not a directory. The pin record for {label} "
        f"names `fixtures/{family}/spec/{filename}`, and a locator aimed anywhere else makes "
        "every one of these tests skip forever while reporting an absent document"
    )
    on_disk = filename in {q.name for q in spec.iterdir() if q.is_file()}
    assert _nato_pin_path(family, filename).exists() == on_disk, (
        f"`spec/` {'holds' if on_disk else 'does not hold'} {filename} and the locator disagrees. "
        f"The locator resolves to {_nato_pin_path(family, filename)}; the pin record for {label} "
        f"names `fixtures/{family}/spec/{filename}`"
    )


def test_the_pin_comparison_bites_on_synthetic_bytes():
    """The checking machinery, exercised where no pinned PDF has to be present at all.

    The six comparisons above run only in a tree whose owner holds six untracked NATO documents.
    There is no CI here that holds them, so on the evidence of the suite alone that arithmetic
    could be gutted and nothing would say so — the same "passing check on nothing" this file
    guards against everywhere else, one level up. This calls `_the_copy_matches_the_pin` itself,
    with bytes it makes up, and requires it to refuse two wrong records.

    The wrong-digest case keeps the RIGHT length, deliberately. Corrupting the bytes would trip
    the byte-count assertion first and the hash comparison would never run — which is how a
    companion for two assertions ends up covering one.
    """
    raw = b"%PDF-1.4 not a NATO document, and pinned as itself\n"
    digest = hashlib.sha256(raw).hexdigest()

    _the_copy_matches_the_pin(raw, "synthetic.pdf", digest, len(raw), "a synthetic stand-in")

    with pytest.raises(AssertionError, match="says"):
        _the_copy_matches_the_pin(raw, "synthetic.pdf", digest, len(raw) + 1,
                                  "a synthetic stand-in with a stale byte count")

    other = bytes(raw[:-1]) + b"!"
    assert len(other) == len(raw), "the digest case has to differ in content and not in length"
    with pytest.raises(AssertionError, match="does not hash to the pin"):
        _the_copy_matches_the_pin(other, "synthetic.pdf", digest, len(raw),
                                  "a synthetic stand-in that is a different copy")


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


# ------------------------------- the STANAG 4609 / MISP-2019.1 (KLV metadata stream) row set
#
# Adapter #10's row set is a SPECIFICATION: `adapters/stanag4609.py` does not exist yet, and this
# one is a specification in a stronger sense than the four before it. STANAG 4609 promulgates a
# PROFILE, the profile delegates every field dictionary to documents published by somebody else,
# and not one of those documents is in hand. So there is no field inventory to pin the way
# `test_every_gmtif_field_has_a_row` pins 212 identifiers off the segment layout tables — the
# equivalent inventory here lives in MISB ST 0601.14, which is park 1.
#
# What CAN be pinned, and what these tests do pin:
#
#   * the two documents, by hash, byte count, page count and filename, AT EVERY SITE that states
#     them — FORMAT_COVERAGE.md, spec/klv_pin.json and fixtures/klv/README.md. That is 80b38d1's
#     finding: an `in` check is satisfied by one site, so a fact stated at three sites and checked
#     at one can drift at two;
#   * the delegation table, because every version string in it was a REPORTED reading before it
#     was a verified one, and a table that silently lost a revision suffix would look identical;
#   * the scope split, which is three declines that are load-bearing on each other;
#   * ABSENCES — the two that matter most here are that no requirement ID in the section is
#     `MISP-2019.1-nn` and that no epoch is stated anywhere. Both are things the pinned text does
#     NOT contain, and a check that only ever confirms presence cannot refute an invention. That
#     was the hole 3e0aed0's mutation round closed and it is the hole most available here, because
#     the temptation in a phase like this one is to fill a gap from memory of the format rather
#     than from the document.

KLV_HEADING = "## STANAG 4609 / MISP-2019.1"

#: PREFIXED, and the prefix is a repair rather than a style choice. This was a second
#: module-level `FIXTURES`, three hundred lines below the one the NATO pin tests read — and the
#: later binding is the one every test BODY sees, because the rebinding happens at import and the
#: bodies run afterwards. So `test_the_pinned_nato_copy_matches_its_record_when_the_file_is_present`
#: was looking for `fixtures/klv/gmti/spec/nato-stanag-4607-edition-4.pdf`, a path that cannot
#: exist, and skipped itself six times over — reporting "untracked and not present" about six
#: documents that were sitting on disk and matching their pins exactly. A skip that cannot stop
#: skipping is the one kind of skip nothing notices, which is why the two companions above it
#: exist now. `FFT_FIXTURES` below already had this shape; this matches it.
KLV_FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "klv"
KLV_PIN = KLV_FIXTURES / "spec" / "klv_pin.json"
KLV_README = KLV_FIXTURES / "README.md"

#: Every pinned document: filename, SHA-256, byte count, page count, and the key path to its own
#: node in `klv_pin.json`. Every one of the four values is asserted at every site, and the byte
#: counts are asserted in BOTH spellings — the digit form the JSON uses and the space-grouped form
#: the prose uses — because the two are the same fact and a half-edit that fixed one would
#: otherwise pass.
#:
#: TWO WHEN IT WAS WRITTEN AND FIVE SINCE 2026-08-26, and the three that arrived are not the same
#: kind of thing as the two that were here. The wrapper and the profile are the documents the row
#: set is written FROM; ST 0601.14, ST 0102.12 and ST 0601.19 are three of the fourteen documents
#: the profile DELEGATES to, and only the first two are editions it delegates to. The roster does
#: not encode that distinction — `reconciliation_ruling` in the pin record does — because this
#: gate's job is that the numbers agree everywhere, and a wrong-edition document's numbers have to
#: agree too. ST0601.14a.pdf is listed under the filename the REGISTRY SERVES, letter and all,
#: which is the same discipline: this gate checks that the five files are identified identically
#: at every site, and renaming one to match the citation would make four sites agree about a file
#: that does not exist.
#:
#: The node path is carried here rather than derived from the filename. It used to be derived, by
#: `"wrapper" if filename.startswith("nato-") else "target"`, and that expression silently maps
#: BOTH new documents onto `target` — so the two new pins would have been asserted against the
#: profile's numbers and the parametrisation would have failed for the right reason by luck rather
#: than checked what it names.
KLV_PINNED_DOCUMENTS = (
    ("nato-stanag-4609-edition-5.pdf",
     "f2f9ae1a5a74528664a8751c3c105161f4597b1041928b7cedba1a57b2dbf8d8", 273801, 5,
     ("wrapper",)),
    ("misb-misp-2019-1.pdf",
     "3167362ace20746ed13e85522130c2e9f3fc9ecf62a112bd75bdced7b102d5ea", 1372771, 73,
     ("target",)),
    ("ST0601.14a.pdf",
     "3d5f1ca105befe6f48023a3cdd29262883d6b77c73c06ba915c4da91ab212ce4", 3969201, 218,
     ("delegated_specifications_held", "st_0601_14")),
    ("ST0601.19.pdf",
     "e53c1e7bfdda888d5946610f89a8146a3f339394e1b127807302676c0cfb92b1", 4700978, 226,
     ("delegated_specifications_held", "st_0601_19")),
    ("ST0102.12.pdf",
     "20d40b5237cdcd2f486547add8eee238e37d5a6b11b7e0aca306be0785eca267", 514842, 18,
     ("delegated_specifications_held", "st_0102_12")),
    # THE FIRST ROSTER ROW THAT IS NOT A PDF, added 2026-09-04 by the text-pins round. Nothing in
    # the parametrised check below reads the extension — it composes a path from the filename and
    # asserts four statements of one fact — so the row needed no code change to be admitted, which
    # is worth a comment because the surface round predicted the opposite. What DID have to move
    # was the discovery side: see `PIN_SUFFIXES` in `tests/test_cdm_pins.py`.
    ("rfc2781.txt",
     "e3fed703a962e1e8a1740fef500d1908df3eca2d80de8bad012835f0ae75b502", 29870, 14,
     ("delegated_specifications_held", "rfc_2781")),
)

#: The delegation map, exactly as the profile pins it. `document` is how the row names it,
#: `version` is the revision string the profile gives, and `locus` is a phrase the row must carry
#: so the citation stays checkable against the pinned PDF.
#: Revisions a delegated document may be stated at IN THIS SECTION beyond the one the profile
#: pins, and what the section must say wherever the extra one appears.
#:
#: THE GATE BELOW USED TO REQUIRE EXACTLY ONE REVISION PER DOCUMENT and that was right for as long
#: as this repository held none of the delegated documents: any second revision string was drift,
#: because there was no legitimate reason to name one. On 2026-08-26 ST 0601.19 was obtained while
#: the profile still pins 0601.14, so the section now names two revisions of ST 0601 on purpose —
#: the pinned one, and the held one that may not stand in for it.
#:
#: WIDENING IT WOULD HAVE LOST THE TEETH, so it is not widened: an extra revision is admitted only
#: by being named here, and only if the section also carries the phrase that says what the extra
#: revision is NOT.
#:
#: THE COMMENT HERE USED TO PREDICT ITS OWN DELETION — "a round that obtains ST 0601.14 deletes
#: this entry rather than editing it, and the gate goes back to demanding one revision" — and the
#: round that obtained ST 0601.14 did NOT delete it, because the prediction assumed .19 would leave
#: with the stop it caused. It did not: .19 stays pinned as CONTEXT ONLY, so the section still
#: names two revisions and still needs to say what the second one is not. What changed is the
#: PHRASE, and it had to change: "may not substitute" was the language of a stop, and the stop is
#: over. "context only" is the language of the ruling that replaced it, and a gate still asserting
#: the old phrase would have been a gate demanding the section describe a ruling it no longer
#: makes. Recorded rather than quietly swapped, because a prediction a later round declines to
#: follow is worth more than one it obeys.
#: Document family -> {revision suffix: the phrase in the section that admits it}. ONE PHRASE PER
#: REVISION, and that shape is new as of 2026-08-26. It used to be one phrase per DOCUMENT licensing
#: a whole set, which was adequate while every extra revision of a family was extra for the same
#: reason. The walk round broke that: it opened park 13 on **ST 0601.1** — a revision the profile
#: does not pin and this repository does not hold, named as a park's deciding document, which is a
#: THIRD kind after "held but not pinned" and "pinned by another delegation" — and it quotes §8.65's
#: value range verbatim, which puts `0601.0` and `0601.255` in the section as parts of a QUOTED RANGE
#: rather than as statements that any such edition governs anything. A single phrase would have
#: licensed all three on one reason, and three of those reasons are different. So each number now
#: names the sentence that admits it, and admitting a number means finding that sentence.
KLV_HELD_NOT_PINNED = {
    # A FIFTH KIND, ADDED 2026-09-04 BY THE PARK 3 ROUND, and it is the narrowest one in this
    # table: a revision named because THE PINNED DELEGATION'S OWN TEXT names it. MISB ST 0603.5 is
    # held, pinned and quoted in register entry KLV 22, and two of the sentences quoted there name
    # its predecessors — its Appendix A says the POSIX-derived guidance was in force "Prior to MISB
    # ST 0603.3", and that earlier ST 0601 editions "have been updated to use terminology
    # consistent with ST 0603.4". Neither is a text any row is read against and neither is on disk;
    # the profile pins .5 and the section states .5 everywhere it states a delegation. **They could
    # not be one entry** for the same reason the ST 0601 five could not: .3 is the revision the
    # POSIX guidance was withdrawn AT, which is what makes edition 1's Table 1 note a superseded
    # claim rather than a disagreement, and .4 is the revision the field dictionaries were
    # re-based ON, which is what makes ST 0601.14a's silence about POSIX evidence rather than
    # absence. One phrase licensing both would license the load-bearing one on the other's reason.
    "MISB ST 0603": {
        "3": "Prior to MISB ST 0603.3",
        "4": "consistent with ST 0603.4",
    },
    "MISB ST 0601": {
        "19": "context only",
        # PARK 13, opened by the walk round and CLOSED THE SAME DAY by the adjudication round. The
        # phrase is unchanged and its REASON is not: when this entry was written .1 was a park's
        # deciding document that nobody held, and it is now PINNED, at
        # `fixtures/klv/spec/EG0601.1.pdf`. It stays in this table because the table's subject is
        # "stated in this section and not the pinned DELEGATION" — the profile pins .14 and always
        # did — and because the sentence that admits it is still the sentence that says why the
        # section names it at all. Kept rather than promoted to a fifth kind, because the gate's
        # question is which revisions the section may state, not which ones are on disk.
        "1": "the edition item 65 declares on the wire",
        # Both of these occur ONLY inside §8.65's own value range, quoted verbatim. `0601.0` is the
        # pre-release the item defines and `0601.255` is the top of a range, and neither is an
        # edition this section pins, holds or parks — so the sentence that admits them is the
        # quotation itself, which is the narrowest admitting phrase in this table.
        "0": "1..255 corresponds to document revisions MISB ST 0601.1 thru MISB ST 0601.255",
        "255": "1..255 corresponds to document revisions MISB ST 0601.1 thru MISB ST 0601.255",
        # FIVE MORE, ADDED 2026-08-26 BY THE ADJUDICATION ROUND, and they are a FOURTH kind after
        # "held but not pinned", "a park's deciding document" and "part of a quoted range": a
        # revision named because the SERIES' OWN CHANGELOG names it, or because an archive index
        # does. Two of them this repository now holds as LINEAGE — .4 and .8, in
        # `fixtures/klv/spec/history/`, which are deliberately not pins — and three it does not hold
        # at all. The distinction the gate exists to protect is untouched: the profile pins .14, and
        # none of these five is offered as a text any row is read against.
        #
        # WHY THEY COULD NOT BE ONE ENTRY. .2 is the edition the series stopped being an
        # Engineering Guideline at, which is the fact that makes edition 1 non-normative and is
        # therefore load-bearing on park 13's ruling. .3 appears only inside the enumeration of the
        # changelog chain. .4 carries the full §3 history the later editions dropped. .8 is where
        # that history was dropped. .17 is the top of what the Wayback index holds, which is the
        # evidence for "obtainable and simply not obtained". One phrase licensing all five would
        # have licensed the load-bearing one on the incidental one's reason.
        "2": "the series became a Standard at 0601.2",
        "3": "STD 0601.2`, `STD 0601.3` and",
        "4": "revision history back to the initial release",
        "8": "ST 0601.8's reformatting",
        "17": "ST 0601.2 through ST 0601.17 under",
    },
    # AMENDED 2026-08-26 BY THE FRAMING ROUND, and this entry is a different KIND from the one
    # above it. ST 0601.19 is a revision this repository HOLDS and the profile does not pin; ST
    # 336:2007 is a revision this repository does not hold and ANOTHER HELD DOCUMENT PINS — ST
    # 0102.12's reference [3], where `ST 0102.12-65` and `-66` require conformance to it. So the
    # section now states two editions of ST 336 for a reason that is neither drift nor a second
    # copy, and the admitting phrase says what that reason is rather than merely licensing the
    # number. Register entry KLV 11.
    "SMPTE ST 336": {"2007": "a divergence between two delegations of one profile"},
    # ADDED 2026-08-27 BY THE PARKS ROUND, and it is a FIFTH kind after "held but not pinned", "a
    # park's deciding document", "part of a quoted range" and "named by the series' own changelog":
    # a revision of a DIFFERENT SERIES DESIGNATION, quoted from a held document's own reference
    # list and used as a DATE WITNESS rather than as a text anything is read against.
    #
    # READ THE DESIGNATION. The section states **RP** 0102.5, not ST 0102.5 — EG 0601.1's §2.3
    # cites "MISB RP 0102.5, Security Metadata Universal and Local Sets for Digital motion
    # Imagery, 15 May 2008". The 0102 series converted Recommended Practice to Standard exactly as
    # the 0601 series converted Engineering Guideline to Standard, so this is KLV 15's phenomenon
    # one series over, and it is why a gate whose family is the bare number `0102` reads a
    # revision of the RP as a second revision of the ST. That is the gate being blunt in the
    # correct direction: it stopped a genuinely new citation and made it be declared.
    #
    # WHAT IT IS LOAD-BEARING ON. That date decides KLV 16's "15 May" row — a document cannot cite
    # a reference published a year after itself, so EG 0601.1's cover date of 15 May 2008 is
    # corroborated from inside its own 98 pages and §3's "15 May 2007" is the typo. Nothing is
    # read against RP 0102.5; this repository does not hold it and the profile does not pin it.
    # The delegation the gate protects is untouched: the profile pins ST 0102.12.
    #
    # TWO MORE, ADDED 2026-09-04 BY THE PARK 2 ROUND, when ST 0102.12's own row set landed and put
    # two further 0102 revision strings in the section. Neither is drift and neither is a text any
    # row is read against; each names the one sentence that admits it, the way every entry above
    # does. The profile still pins ST 0102.12 and that row is untouched.
    #
    # `.10` IS PART OF A QUOTATION, which is the `0601.0`/`0601.255` kind one series over. §6.7's
    # Allowed Values cell for tag 22 Version states the rule by example — "Value is version number
    # of this document; e. g. for ST 0102.10, this value is 0x000A" — and the row set quotes it,
    # because that sentence is the whole derivation of why this document's own value is `0x000C`.
    # The admitting phrase is the quotation itself, which is the narrowest form available. NOTE the
    # requirement IDs `ST 0102.10-02` through `-62` do NOT reach this gate at all: the `(?![\d-])`
    # lookahead above excludes them, and the row set cites thirty-eight of them.
    #
    # `.11` IS A SIXTH KIND — A REVISION NAMED AS AN ABSENCE. Tags 15 through 21 are missing from
    # §6.7's Table 2, the revision history names four deleted KEYS against seven missing TAG
    # NUMBERS and never prints a tag number, and MISB ST 0102.11 is the document that would settle
    # which numbers those keys held. It is not held, it is not a delegation the profile makes, and
    # no park stands on it. So the section names it precisely to say that the question stops there
    # — the opposite of a claim that anything is read against it — and the admitting phrase is the
    # clause that says it is not held. A gate that refused this would be a gate forbidding the
    # record to name the document whose absence bounds a finding.
    "MISB ST 0102": {
        "5": "MISB RP 0102.5, Security Metadata Universal and Local Sets",
        "10": "for ST 0102.10, this value is 0x000A",
        "11": "MISB ST 0102.11 — which would settle it — is not held",
    },
}

#: The nested ST 0102.12 row set's own subsection heading. Named as a constant beside the
#: delegation roster because two tests now have to tell the two tag tables in this section
#: apart, and a literal repeated at two sites is a literal that drifts at one of them.
KLV_ST_0102_HEADING = "### The ST 0102.12 Security Metadata Local Set"

KLV_DELEGATION = (
    ("SMPTE ST 336", "ST 336:2017", "MISP-2015.1-07"),
    ("MISB ST 0107", "0107.3", "MISP-2015.1-08"),
    ("MISB ST 0601", "0601.14", "§4.4.4.1"),
    ("MISB ST 0102", "0102.12", "MISP-2015.1-73"),
    ("MISB ST 0603", "0603.5", "§2.1.5"),
    ("MISB ST 0903", "0903.4", "§4.4.2.4"),
    ("MISB ST 0806", "0806.4", "§4.4.2.4"),
    ("MISB ST 1402", "1402.2", "MISP-2015.1-48"),
)


MIGRATIONS = pathlib.Path(synapse_cdm.__file__).resolve().parent / "MIGRATIONS.md"


def _klv_sites() -> dict[str, str]:
    """The three files that state the pin in full, so a fact can be checked at every one of them."""
    return {
        "FORMAT_COVERAGE.md": _section(KLV_HEADING),
        "fixtures/klv/spec/klv_pin.json": KLV_PIN.read_text(),
        "fixtures/klv/README.md": KLV_README.read_text(),
    }


def _abbreviated(digest: str) -> str:
    """`MIGRATIONS.md` and the commit messages ellipsise a hash: `8f9c51ff…c996e`.

    That is this repository's established form in those two places and it is not worth changing —
    but it is still a statement of the same fact, so it is still a site that can drift. The
    abbreviation is derived from the full digest here rather than typed twice.
    """
    return f"{digest[:8]}…{digest[-8:]}"


def test_the_klv_row_set_is_partly_promoted_and_the_partition_is_the_witnessed_set():
    """The INVERTED form, which is what this test becomes once the adapter it gated has shipped.

    Until the witnessed-set round this asserted that every row said `not yet` and that no
    `stanag4609 1.0.0` marker existed anywhere — Phase 1's whole claim, that the row set is a
    specification and nothing in it is implemented. `adapters/stanag4609.py` has now landed against
    26 of the 141 rows, so the assertion inverts on the pattern Legion, NITS, GMTIF, CAT048, CAT034,
    CAT062 and CAT023 each established: it fails if a row still says `not yet` while the code
    implements it.

    WHAT MAKES THIS ONE DIFFERENT FROM THE SEVEN BEFORE IT: the promotion is **partial**, and this
    is the first row set in the document where that is true. So both halves are asserted and the
    lower bound on `not yet` rows matters as much as the upper — a round that quietly promoted the
    rows still reading `not yet` would pass a test that only checked for the presence of markers,
    and that many decoders checkable against nothing but themselves is the exact failure this
    section has spent six rounds avoiding. **The figure is not spelled in this docstring**: it said
    "the remaining 115" twice until 2026-09-05, a count four rounds moved on 2026-09-04 while the
    assertion below re-derived it on every run. `klv_uas_codec.WITNESSED_TAGS` is the authority for which side of the line a row is
    on, and `test_the_st_0601_tag_table_agrees_between_the_pin_record_and_the_document` checks the
    partition tag by tag.
    """
    from synapse_cdm.adapters import klv_uas_codec as uas_codec

    section = _section(KLV_HEADING)
    # SCOPED TO THE TAG TABLE's rows, which is what `WITNESSED_TAGS` is a set of. The section also
    # holds an egress table whose eight rows carry the same marker, and counting those against a
    # tag count would make this assertion fail for a reason that has nothing to do with the scope
    # contract — the shape `_klv_tag_rows()` exists to avoid one level up.
    #
    # AND SINCE 2026-09-04 THE SCOPING IS LOAD-BEARING RATHER THAN TIDY, WHICH IS WHY IT NOW USES
    # THE SUBSECTION AND NOT A ROW PATTERN. The park 2 round added a SECOND tag table to this
    # section — ST 0102.12's seventeen elements, nested under item 48 — whose rows open `| `1` |`
    # exactly as ST 0601's do, because both documents number their tags from 1. A pattern-only
    # filter collected all 158 rows and compared 42 promoted markers against a 26-tag witnessed
    # set. That is the same defect one table over that the comment above describes for the egress
    # table, met a second time, and a row pattern cannot fix it: the two tables are distinguished
    # by which SUBSECTION they are in and by nothing on the row itself.
    start = section.index(KLV_TAG_TABLE_HEADING)
    body = section[start:section.index("\n### ", start + 10)]
    tag_rows = [ln for ln in body.splitlines() if re.match(r"^\| `\d+` \| ", ln)]
    not_yet = [ln for ln in tag_rows if "| `not yet` |" in ln]
    promoted = [ln for ln in tag_rows if "| `stanag4609 1.0.0" in ln]
    # THE WITNESSED SET PLUS THE NESTED SETS, and the two terms are stated separately because they
    # are two different claims. `WITNESSED_TAGS` is what the pinned stream attests and the codec
    # maps; `NESTED_SETS` is the one item whose value another held document defines and whose key
    # TWO held documents state identically — item 48, ruled at the tag-by-tag guard below. Summing
    # them here rather than widening `WITNESSED_TAGS` is the point: the scope contract's number
    # does not move, and the crossing has to be declared in its own table to be counted.
    # THREE TERMS SINCE 2026-09-04, AND THEY ARE SUMMED RATHER THAN MERGED BECAUSE THEY ARE THREE
    # DIFFERENT CLAIMS ABOUT WHAT WITNESSES A ROW. `WITNESSED_TAGS` is what the pinned stream
    # attests and is still 26. `NESTED_SETS` is the one item whose value another held document
    # defines and whose key TWO held documents state identically — item 48, park 2's round.
    # `DOCUMENT_WITNESSED_TAGS` is the park 5 round's fifteen, promoted under RULING 1 on ST
    # 0601.14a's OWN printed worked examples, reproduced by
    # `check_against_the_documents_own_examples()` on every suite run. Summing them here rather
    # than widening `WITNESSED_TAGS` is the whole point and is the decision
    # `klv_uas_codec.WITNESS_KINDS` records: the scope contract's number does not move, and each
    # crossing has to be declared in its own table to be counted.
    expected = (len(uas_codec.WITNESSED_TAGS) + len(uas_codec.NESTED_SETS)
                + len(uas_codec.DOCUMENT_WITNESSED_TAGS))
    assert len(promoted) == expected, (
        f"{len(promoted)} rows carry a stanag4609 marker and the codec covers "
        f"{len(uas_codec.WITNESSED_TAGS)} witnessed tags plus {len(uas_codec.NESTED_SETS)} nested "
        f"set(s) plus {len(uas_codec.DOCUMENT_WITNESSED_TAGS)} document-witnessed tags. Each "
        "crossing of the scope contract is declared in its own table so that it can be counted "
        "here; a promotion with no table behind it fails this assertion"
    )
    # 96 SINCE 2026-09-05, DOWN FROM 97, 99, 114 AND 115, AND WHAT MOVED IS NAMED AT EACH STEP:
    # item 48 left for the nested-set ruling (park 2), fifteen left for the document-side witness
    # (park 5), items 136 and 137 left on the same witness (park 3, RULING 3) once MISB ST 0603.5
    # gave the MISP Time System a definition here and §6.4's two equations had terms to put in
    # them, and TAG 75 left on that same witness on 2026-09-05 (the pre-release round, RULING 4) —
    # §8.75 prints `14190.7195 Meters` against `C221`, and the reason it was not one of park 5's
    # fifteen is that its map is a plain affine `uint16` and not `IMAPB`, so RULING 1's scope did
    # not reach it. Every remaining row is blocked on the scope contract, and tag 130 is the one
    # that is ALSO one of park 5's sixteen — it stays because §8.130 prints no worked example,
    # which is the condition RULING 1 measures against.
    assert len(not_yet) >= 96, (
        f"only {len(not_yet)} `not yet` rows left in the ST 0601 tag table. 96 of the 141 rows "
        "are outside all three witness grounds and each is blocked on the scope contract; a round "
        "that promoted them wrote decoders nothing can check, which is the trap this section "
        "exists to avoid"
    )
    assert 130 in {int(re.match(r"^\| `(\d+)` \| ", ln).group(1)) for ln in not_yet}, (
        "tag 130 Airbase Locations is no longer `not yet`. It is the sixteenth of park 5's sixteen "
        "and the one RULING 1 did NOT reach: §8.130 prints no worked example — Example Software "
        "Value 'N/A', Example KLV Item '8102 - N/A' — so there is nothing for a document-side "
        "check to be as strong as, and its own section states its HAE member's range two ways, "
        "IMAPB(-900, 9000,3) in Figures 60/61 against IMAPB(-600, 9000, 3) in the prose. A round "
        "that promoted it either found a third statement of that range or waived the condition, "
        "and the second is what this assertion exists to stop"
    )
    # THE NESTED ST 0102.12 ROW SET HAS ITS OWN PARTITION AND IT IS ASSERTED SEPARATELY, because
    # scoping the check above to ST 0601's table would otherwise have stopped checking these rows
    # at all — a scoping fix that quietly drops seventeen rows out of every assertion is a fix
    # that makes the file less checked than it was.
    sec_start = section.index(KLV_ST_0102_HEADING)
    sec_body = section[sec_start:section.index("\n### ", sec_start + 10)]
    sec_rows = [ln for ln in sec_body.splitlines() if re.match(r"^\| `\d+` \| ", ln)]
    assert len(sec_rows) == 17, (
        f"the ST 0102.12 row set parsed to {len(sec_rows)} rows, expected seventeen — §6.7's "
        "Table 2 draws rows for tags 1-14, 22, 23 and 24 and for no others"
    )
    sec_not_yet = [ln for ln in sec_rows if "| `not yet` |" in ln]
    assert len(sec_not_yet) == 1 and sec_not_yet[0].startswith("| `13` |"), (
        f"the ST 0102.12 row set has {len(sec_not_yet)} `not yet` rows and exactly one is right: "
        "tag 13 Object Country Codes, whose Data Type cell names RFC 2781 — a document this "
        "repository does not hold, so its octets are carried and no string is produced. A second "
        "`not yet` row means an element stopped being read; none means tag 13 was decoded by "
        "guessing a byte order, which is the one thing that row exists to forbid"
    )
    assert "RFC 2781 is not held" in _flat(sec_body), (
        "the ST 0102.12 row set no longer says WHY tag 13 is `not yet`. An unread row whose reason "
        "is missing reads as unfinished work rather than as a bounded absence"
    )

    before = DOC.read_text().split(KLV_HEADING)[0]
    assert "`stanag4609 1.0.0`" in before, (
        "the status-column table at the top of the document does not define the marker the KLV row "
        "set now uses. A status nobody defined is a status a reader has to guess at"
    )
    assert "`klv 1.0.0`" not in section and "`klv 1.0.0`" not in before, (
        "a `klv 1.0.0` marker has appeared. The registered adapter name is `stanag4609`; `klv` is "
        "the fixture directory, and a status marker naming a directory claims an adapter that is "
        "not in the registry"
    )


@pytest.mark.parametrize("filename,digest,size,pages,node", KLV_PINNED_DOCUMENTS,
                         ids=lambda q: q if isinstance(q, str) else "")
def test_every_klv_pin_agrees_at_every_site_that_states_them(filename, digest, size, pages, node):
    """Every occurrence, not any occurrence — and each one asserted as ONE composite fact.

    Two lessons from earlier rounds, and the second was found here by mutation. 80b38d1 found the
    NITS pin naming two directories for one adapter at two sites four hundred lines apart, its own
    re-pointing test passing because `xsd_pin.json in text` was satisfied by one of the two; so
    every site that states the pin is checked, not one of them.

    THEN mutation found the residue of the same shape inside a single site. Checking hash, byte
    count and page count as three independent substrings makes each one a disjunction over the
    whole file: changing `"pages": 73` to `74` in `klv_pin.json` left the suite green, because the
    string `73` still occurred in that file's prose. The repair is that a pin row is ONE fact and
    is asserted as one string — hash, byte count, page count and path together — plus a structural
    read of the JSON, where the values are addressable and no substring search is needed at all.
    """
    spaced = _spaced(size)

    # 1. The JSON, read as data. Four documents, four values each, no substrings.
    pin = json.loads(KLV_PIN.read_text())
    key = ".".join(node)
    record = pin
    for step in node:
        assert step in record, (
            f"klv_pin.json has no node at {key} — the roster names it, so either the record was "
            "restructured or a pin was dropped"
        )
        record = record[step]
    assert record["sha256"] == digest, f"klv_pin.json {key}.sha256 is {record['sha256']}"
    assert record["bytes"] == size, f"klv_pin.json {key}.bytes is {record['bytes']}"
    assert record["pages"] == pages, f"klv_pin.json {key}.pages is {record['pages']}"
    assert record["local_path"] == f"fixtures/klv/spec/{filename}", (
        f"klv_pin.json {key}.local_path is {record['local_path']}"
    )

    # 2. FORMAT_COVERAGE.md's pin row, as one composite string.
    row = f"`{digest}`, {spaced} bytes, {pages} pages, `fixtures/klv/spec/{filename}`"
    assert row in _section(KLV_HEADING), (
        f"FORMAT_COVERAGE.md's pin row for {filename} is not\n  {row}\nA row asserted "
        "value-by-value would pass on a wrong page count, because the right number still occurs "
        "elsewhere on the page — which is what mutation found"
    )

    # 3. The fixture README's table row, likewise.
    readme_row = f"| `spec/{filename}` | `{digest}` | {spaced} | {pages} |"
    assert readme_row in KLV_README.read_text(), (
        f"fixtures/klv/README.md's table row for {filename} is not\n  {readme_row}"
    )

    # 4. MIGRATIONS.md, in this document's own ellipsised form, also as one string.
    migrations_fact = f"(`{_abbreviated(digest)}`, {spaced} bytes, {pages} pages)"
    assert migrations_fact in MIGRATIONS.read_text(), (
        f"MIGRATIONS.md's Phase 1 entry no longer states {filename} as\n  {migrations_fact}\n"
        "It is the same fact in the ellipsised form this file established, so it drifts the same "
        "way"
    )


KLV_TAG_TABLE_HEADING = "### Row set — the ST 0601.14 UAS Datalink Local Set, transcribed"

#: A row of that table: `| `42` | Target Location Elevation | m | `uint16` | `2` | … | `not yet` | …`
KLV_TAG_ROW = re.compile(
    r"^\| `(?P<tag>\d+)` \| (?P<name>[^|]+?) \| (?P<units>[^|]*?) \| `(?P<format>[^|`]+)` \| "
    r"`(?P<length>[^|`]+)` \| (?P<field>[^|]+?) \| `(?P<status>[^|`]+)` \| (?P<notes>.*) \|$")


def _klv_build_fixtures():
    """Compile `fixtures/klv/spec/build_fixtures.py` IN MEMORY, never through the source loader.

    The same reason `tests/test_cdm_klv_framing.py` does it this way and
    `tests/test_cdm_generator_loading.py` asserts it: `spec_from_file_location` + `exec_module`
    reads and writes `__pycache__`, a `.pyc` is revalidated on the source's mtime in whole seconds
    and its size, and this test's subject is what the SOURCE on disk produces today.
    """
    import types
    path = KLV_FIXTURES / "spec" / "build_fixtures.py"
    module = types.ModuleType("klv_build_fixtures")
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


def _klv_tag_rows() -> list[dict]:
    section = _section(KLV_HEADING)
    start = section.index(KLV_TAG_TABLE_HEADING)
    body = section[start:section.index("\n### ", start + 10)]
    return [m.groupdict() for m in
            (KLV_TAG_ROW.match(ln) for ln in body.splitlines()) if m]


def test_the_st_0601_tag_table_agrees_between_the_pin_record_and_the_document():
    """THE DISJUNCTION, on the fact this round added: 141 items stated at two sites.

    `klv_pin.json`'s `tag_table_st_0601_14.items` is the transcription; the row set in
    `FORMAT_COVERAGE.md` is the same transcription with a CDM target and a status column bolted
    on. Two statements of one reading of one table, which is the shape 80b38d1's finding is about
    — and the shape a 141-row table makes worst, because nobody proofreads 141 rows twice and a
    single transposed `uint16`/`int16` or `2`/`4` is invisible to a reader and catastrophic to a
    decoder. So the two are compared field by field rather than trusted to have been generated
    together, and the comparison covers the columns a decoder would ACT on: name, units, format,
    length and CDM target.

    The Notes column is deliberately NOT compared. It carries this round's per-item findings and
    lives only in the document — prose belongs where prose is read, and asserting it here would
    pin editorial wording as though it were a transcribed value.

    THE STATUS COLUMN IS NOW A THIRD DISJUNCTION, AND IT IS THE ONE THE WITNESSED-SET ROUND ADDED.
    Until adapter #10 shipped, every row read `not yet` and this test asserted exactly that. It now
    asserts the property that replaced it: a row carries a `stanag4609 1.0.0…` marker **if and only
    if** its tag is in `klv_uas_codec.WITNESSED_TAGS`, which is the code's own scope contract. That
    is stronger than the sentence it replaces in both directions — a row promoted without a decoder
    fails, and a decoder written without its row being promoted fails too — and it is the check that
    keeps "the witnessed set" one set rather than a phrase two files each interpret.
    """
    from synapse_cdm.adapters import klv_uas_codec as uas_codec

    pin = json.loads(KLV_PIN.read_text())
    node = pin["tag_table_st_0601_14"]
    items = {int(i["tag"]): i for i in node["items"]}
    rows = {int(r["tag"]): r for r in _klv_tag_rows()}

    assert node["item_count"] == 141 and len(items) == 141, (
        f"the pin record states {node['item_count']} items and carries {len(items)}"
    )
    assert len(rows) == 141, (
        f"FORMAT_COVERAGE.md's ST 0601 row set parsed to {len(rows)} rows, expected 141. Either "
        "the table changed shape or the row pattern has stopped matching — and a pattern that "
        "matches nothing makes every assertion below vacuous, which is what "
        "test_the_table_was_actually_parsed exists for one level up"
    )
    assert set(items) == set(range(1, 142)) == set(rows), (
        "the tag numbers are not 1..141 at both sites. ST 0601.14's Table 1 has no gap and no "
        "duplicate, which is the one positive control a summary table offers about itself"
    )
    for tag in sorted(items):
        a, b = items[tag], rows[tag]
        assert a["name"] == b["name"].strip(), f"item {tag} name: {a['name']!r} vs {b['name']!r}"
        assert a["units"] == b["units"].strip(), f"item {tag} units: {a['units']!r} vs {b['units']!r}"
        assert a["format"] == b["format"], f"item {tag} format: {a['format']!r} vs {b['format']!r}"
        assert a["length"] == b["length"], f"item {tag} length: {a['length']!r} vs {b['length']!r}"
        assert a["cdm_field"] == b["field"].replace("`", "").strip(), (
            f"item {tag} CDM field: {a['cdm_field']!r} vs {b['field']!r}"
        )
        witnessed = tag in uas_codec.WITNESSED_TAGS
        # THE ONE ITEM PROMOTED PAST THE WITNESSED SET, AND THE CROSSING IS RULED RATHER THAN
        # WAIVED — added 2026-09-04 by the park 2 round. Item 48's value is not a value this
        # repository maps: it is a NESTED LOCAL SET whose seventeen elements another held
        # document, MISB ST 0102.12, defines, and `klv_uas_codec.NESTED_SETS` is a second table
        # beside `ITEMS` for exactly that distinction. `WITNESSED_TAGS` is unchanged at 26 and the
        # scope contract's sentence is untouched.
        #
        # WHY THE CONTRACT'S REASON DOES NOT REACH IT. The contract exists because an unwitnessed
        # item's decoder "could only ever be checked against a fixture written from the same
        # reading of the same table". Item 48's is checked against a SECOND DOCUMENT: ST 0601.14a
        # §8.48 prints `KLV Key 06.0E.2B.34.02.03.01.01.0E.01.03.03.02.00.00.00 (CRC 40980)` and
        # ST 0102.12 §6.7 registers the Security Metadata Local Set under the same sixteen octets
        # and the same CRC — two documents, obtained on different days by different routes, in
        # agreement. NO OTHER UNWITNESSED ITEM HAS A SECOND DOCUMENT BEHIND IT, which is why this
        # admission is one tag wide and cannot grow without another one arriving.
        #
        # THE ADMISSION IS NARROW ON PURPOSE: only tag 48, only if `NESTED_SETS` still claims it,
        # and the row must still say which document owns the elements. Deleting the nested-set
        # table or promoting a second unwitnessed row fails here.
        nested = tag in uas_codec.NESTED_SETS
        # AND A THIRD GROUND SINCE 2026-09-04, WHOSE ADMISSION IS WIDER AND WHOSE CHECK IS
        # DIFFERENT. `DOCUMENT_WITNESSED_TAGS` is the park 5 round's fifteen, admitted under
        # RULING 1 on the reopen condition the "Not witnessed" ledger row has stated since
        # 2026-08-26: "a second pinned stream, OR a document-side check as strong as a worked
        # example — and ST 0601.14a prints one per item." Item 48's ground is TWO DOCUMENTS
        # agreeing; these fifteen rest on ONE document checking itself, which is weaker and is why
        # the check is asserted mechanically below rather than described: the admission holds only
        # while `check_against_the_documents_own_examples()` actually reproduces each one.
        document_witnessed = tag in uas_codec.DOCUMENT_WITNESSED_TAGS
        if witnessed:
            assert b["status"].startswith("stanag4609 1.0.0"), (
                f"item {tag} is in klv_uas_codec.WITNESSED_TAGS — the pinned stream attests it and "
                f"the codec decodes it — and its row still reads {b['status']!r}. A decoded item "
                "whose row says `not yet` makes the status column a claim nobody can rely on"
            )
        elif nested:
            assert tag == 48 and set(uas_codec.NESTED_SETS) == {48}, (
                f"klv_uas_codec.NESTED_SETS claims {sorted(uas_codec.NESTED_SETS)} and the only "
                "item admitted past the witnessed set is 48, whose elements ST 0102.12 defines "
                "and whose key TWO held documents state identically. A second entry needs its own "
                "second document and its own ruling here"
            )
            assert b["status"].startswith("stanag4609 1.0.0"), (
                f"item {tag} is a nested set klv_uas_codec delegates to another document's item "
                f"layer, and its row reads {b['status']!r}. The codec reads it, so the row says so"
            )
            assert "ST 0102.12" in b["notes"] and "CRC 40980" in b["notes"], (
                "item 48's row no longer names the document whose elements it carries and the key "
                "the two documents agree on. That agreement IS the ground for crossing the scope "
                "contract; a row that stops stating it is a promotion with no argument left"
            )
        elif document_witnessed:
            assert b["status"].startswith("stanag4609 1.0.0"), (
                f"item {tag} is in klv_uas_codec.DOCUMENT_WITNESSED_TAGS — the codec decodes it "
                f"and ST 0601.14a prints a worked example for it — and its row reads "
                f"{b['status']!r}. A decoded item whose row says `not yet` makes the status "
                "column a claim nobody can rely on"
            )
            assert "witnessed by §" in b["notes"] or "worked example" in b["notes"], (
                f"item {tag}'s row no longer states its witness basis. RULING 1 requires EACH "
                "ROW to say which kind of witness stands behind it — 'witnessed by §8.n's own "
                "worked example; no held stream carries this tag' — because the "
                "stream-versus-document distinction is this record's whole argument and a "
                "promotion that stops stating it is indistinguishable from one made on a wire"
            )
        else:
            assert b["status"] == "not yet", (
                f"item {tag} reads {b['status']!r} and is in none of klv_uas_codec's three witness "
                "tables — WITNESSED_TAGS, NESTED_SETS, DOCUMENT_WITNESSED_TAGS. The scope "
                "contract: a row promoted past all three is a decoder checkable only against a "
                "fixture written from the same reading of the same table"
            )


def test_the_tag_table_is_read_from_0601_14_and_says_so_where_it_could_be_misread():
    """The edition ruling, asserted at the one site where getting it wrong is worst.

    A 141-row table of tag semantics sitting in the same document as a pin for a LATER revision of
    the same standard is the most misreadable artefact this section has ever held. The ruling that
    keeps them apart is not decorative, so it is asserted here as well as in the delegation gate:
    the table says which edition it is read from, and it says what the other one is for.
    """
    section = _section(KLV_HEADING)
    start = section.index(KLV_TAG_TABLE_HEADING)
    block = _flat(section[start:section.index("\n### ", start + 10)])
    assert "ST 0601.14 — this copy, this hash — is the authoritative tag table" in block, (
        "the row set no longer states which edition it is read from, in the one place a reader "
        "arrives at the numbers"
    )
    assert "context only" in block, (
        "the row set no longer says what ST 0601.19 is for. Two revisions of one dictionary in one "
        "document, with only one of them labelled, is the KLV 9 hazard reproduced editorially"
    )
    # The item-42 divergence: recorded, and NOT applied.
    assert "states no datum for item 42 at all" in block, (
        "item 42's divergence note is gone. It is the one item where .14 and .19 disagree in "
        "MEANING, and .14's silence is what this row set carries"
    )
    assert "conditionally either MSL or HAE" in block, (
        "the note no longer says what .19 later resolved item 42 to. Recording the divergence "
        "means recording both sides; recording only ours makes it an assertion"
    )
    assert "None of that is in the table above and none of it is applied" in block, (
        "the note quotes .19's resolution without saying it was not applied, which is exactly how "
        "a note becomes an import"
    )
    row_42 = [r for r in _klv_tag_rows() if r["tag"] == "42"]
    assert len(row_42) == 1 and "MSL or HAE" not in row_42[0]["units"], "item 42's row is malformed"
    assert "unstated" in row_42[0]["notes"] or "no datum" in row_42[0]["notes"], (
        "item 42's own row does not record that .14 leaves the datum unstated. The divergence note "
        "below the table is context; the ROW is what a Phase 2 reads"
    )


def test_the_row_set_states_what_every_one_of_its_rows_is_still_blocked_on():
    """Closing park 1 is the edit most likely to be read as `this adapter can now decode`.

    It cannot. The tag table says what each item MEANS and what its length and format are; parks 4
    and 8 still own how an item is FOUND in an octet stream, so not one of the 141 rows can be
    read from a stream. Stated once above the table rather than 141 times, which means one
    sentence carries the whole qualification — and a qualification carried by one sentence is a
    qualification a test should hold in place.
    """
    section = _section(KLV_HEADING)
    start = section.index(KLV_TAG_TABLE_HEADING)
    block = _flat(section[start:section.index("\n### ", start + 10)])
    assert "every row below is additionally *(blocked)* on parks 4 and 8" in block, (
        "the blanket blocker is gone from the row set's preamble. Per-row Notes name the FURTHER "
        "blockers only, so without this sentence 141 rows read as unblocked"
    )
    assert "made the stream nameable" in block, (
        "the sentence that stops park 1's closure being read as a decoder is gone"
    )


def _group(digits: str) -> list[str]:
    """`'1372771'` -> `['1', '372', '771']`, the grouping the prose uses."""
    out, rest = [], digits
    while len(rest) > 3:
        out.insert(0, rest[-3:])
        rest = rest[:-3]
    out.insert(0, rest)
    return out


def _spaced(size: int) -> str:
    """The byte count as the prose writes it: groups of three separated by an ordinary space."""
    return " ".join(_group(str(size)))


def test_the_pin_records_that_no_pdf_is_committed_and_none_is():
    """The claim and the fact, checked together rather than only the claim.

    Every adapter here pins rather than vendors, and the statement of that is in three documents.
    A statement that stops being true is worse than no statement, so the repository is asked as
    well: `git ls-files` is the authority and the prose is the claim.
    """
    tracked = [p for p in _tracked_files() if p.endswith(".pdf")]
    assert tracked == [], f"PDFs are tracked: {tracked}"
    for label, text in _klv_sites().items():
        assert "not committed" in text.lower() or "is 0" in text, (
            f"{label} no longer records that the pinned PDFs stay out of the index"
        )
    # And the files really are present in the working tree, because a pin nobody can re-verify is
    # a recollection — which is what the pin's own preamble says it is not.
    for filename, _digest, _size, _pages, _node in KLV_PINNED_DOCUMENTS:
        path = KLV_FIXTURES / "spec" / filename
        if path.exists():                      # a fresh clone will not have them
            assert path.stat().st_size == _size, f"{filename} at the pinned path is the wrong size"
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            assert got == _digest, f"{filename} at the pinned path hashes to {got}, not {_digest}"


def _tracked_files() -> list[str]:
    import subprocess
    root = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True)
    return out.stdout.splitlines() if out.returncode == 0 else []


@pytest.mark.parametrize("document,version,locus", KLV_DELEGATION)
def test_the_delegation_table_states_the_exact_version_the_profile_pins(document, version, locus):
    """Each row of the delegation map, with its revision suffix and the locus that proves it.

    The revision suffix is the whole value of this table. "MISB ST 0601" names a document revised
    at least fourteen times; "0601.14" names the one MISP-2019.1 actually pins, and a tag added in
    a later revision decoded against an earlier one is a plausible number in the wrong field
    rather than an exception.

    SCOPED TO THE ROW, and mutation is why. `version in section` is a disjunction over the whole
    section: each version string is also stated in the parks table and again in register entry
    KLV 5, so **stripping the suffix off the delegation row left the suite green**. The row is
    located by its own document name, the version is asserted inside it, and then every OTHER
    statement of a revision for the same document family is required to agree — because three
    sites stating one revision is three places it can drift.
    """
    section = _section(KLV_HEADING)
    flat = _flat(section)

    rows = [ln for ln in section.splitlines() if ln.startswith(f"| **{document}**")]
    assert len(rows) == 1, (
        f"expected exactly one delegation row opening `| **{document}**`, found {len(rows)}"
    )
    row = rows[0]
    assert version in row, (
        f"{document}'s delegation row no longer states {version!r}. The version IS the pin — the "
        f"document name alone identifies a family, not a text.\n  row: {row}"
    )
    assert locus in row, (
        f"{document}'s delegation row no longer carries {locus!r}, so the citation cannot be "
        f"checked against the pinned PDF.\n  row: {row}"
    )

    # And no other statement of a revision for this document may disagree with it. The family is
    # the bare number (`0601`, `336`); the pattern is whatever follows it in the pinned form.
    family, _, suffix = version.replace("ST ", "").partition("." if "." in version else ":")
    separator = "." if "." in version.replace("ST ", "") else ":"
    # `(?![\d-])` IS LOAD-BEARING AND WAS ADDED ON 2026-08-26, when the ST 0601 row set landed.
    # ST 0601 numbers its requirements `ST 0601.<revision>-<n>` — `ST 0601.8-17`, `ST 0601.13-23`,
    # `ST 0601.14-35` — so a bare `\b0601\.(\d+)` reads the revision half of a REQUIREMENT ID as a
    # statement that the section pins that edition, and the row set quotes three of them. Those are
    # citations of the revision that INTRODUCED a requirement, which is a different claim from
    # naming an edition, and the gate's subject is the second.
    #
    # THE OBVIOUS NEGATIVE LOOKAHEAD IS WRONG AND PASSED ANYWAY. `(?!\s*-\s*\d)` looks correct and
    # is defeated by backtracking: on `0601.13-23` the greedy `\d+` takes `13`, the lookahead sees
    # `-` and fails, and the engine then backtracks to `\d+` = `1`, where the lookahead sees `3`,
    # is satisfied, and the gate is handed a phantom revision `0601.1`. Excluding a following
    # DIGIT as well as a dash is what actually closes it, because it leaves no shorter match to
    # retreat to. Checked against the section before and after: the set is unchanged on every
    # document family the roster names, so this narrows what the gate reads and not what it rules.
    stated = set(re.findall(rf"\b{re.escape(family)}{re.escape(separator)}(\d+)(?![\d-])", section))
    admitted = KLV_HELD_NOT_PINNED.get(document, {})
    extra = set(admitted)
    assert stated == {suffix} | extra, (
        f"{document} is stated at more than one revision in this section: "
        f"{sorted(family + separator + x for x in stated)}, expected "
        f"{sorted(family + separator + x for x in {suffix} | extra)}. The delegation table, the "
        f"parks table and register entry KLV 5 all name it, and they have to name the same text. A "
        f"revision this repository HOLDS but the profile does not pin is admitted only by "
        f"KLV_HELD_NOT_PINNED, because the whole value of this table is that the suffix is the pin"
    )
    for extra_suffix, ruling_phrase in sorted(admitted.items()):
        # AGAINST THE FLATTENED TEXT, not the raw section. An admitting phrase long enough to be
        # worth reading is long enough to wrap, and a substring check against wrapped markdown
        # fails on a phrase that is present — which would push the next editor to shorten the
        # phrase until it fits on one line, i.e. to make the reason less specific to satisfy the
        # gate. `_flat` collapses the wrapping and leaves the sentence.
        assert ruling_phrase in flat, (
            f"{document} is stated at {family + separator + extra_suffix} as well as at the pinned "
            f"{version}, and the section does not carry {ruling_phrase!r}. A revision that is not "
            "the pinned one is only safe while the section says OUT LOUD why it is there — "
            "otherwise the two numbers sit side by side and a reader picks whichever they saw "
            "last. One phrase per revision, because the reasons differ: .19 is held and not "
            "pinned, .1 is a park's deciding document and is now pinned, .0 and .255 are parts of "
            "a quoted range, and .2/.3/.4/.8/.17 are revisions the series' own changelog or an "
            "archive index names — of which .4 and .8 are held as LINEAGE and are not pins"
        )
    assert document in flat, f"the delegation table no longer names {document}"


def test_every_delegation_row_says_where_its_VERSION_comes_from():
    """The version and the requirement are different pages, and the row has to say which is which.

    A challenge to the ST 1402 row asked the right question of the whole table: §3.6.9.1 and
    §3.7.12.1 both cite "MISB ST 1402 [48]" with no revision suffix, so where does `.2` come from?
    Appendix B, and only Appendix B. Checking it generalised into a fact about the document —
    **every** revision suffix in MISP-2019.1 lives on six of its 73 pages (the Change Log, Appendix
    B, and one stray in an Appendix A.2 deprecation note), and not one requirement or body section
    states a revision of anything.

    That matters to a reader in a way a table of bare version strings hides: taking a version from
    the requirement that mandates a document gets you no version, and taking one from a later
    revision silently changes what the profile requires. So every row separates the two loci, and
    this test is what stops them collapsing back into one cell reading "Appendix B; cited by …".
    """
    section = _section(KLV_HEADING)
    flat = _flat(section)
    rows = [ln for ln in section.splitlines()
            if ln.startswith("| **") and "Appendix B" in ln and "**version:**" in ln]
    assert len(rows) == len(KLV_DELEGATION), (
        f"{len(rows)} delegation rows name where their version comes from, expected "
        f"{len(KLV_DELEGATION)}. A row that asserts a revision without citing the page it is "
        "stated on is a version taken on trust"
    )
    for row in rows:
        assert "**version:** ref [" in row, (
            "the version cell no longer opens with the Appendix B reference number it stands on. "
            "MUTATION FOUND THIS: replacing the cell with \"per the delegation table\" left the "
            "row matching, because the *Required by* half happens to mention Appendix B too — so "
            "the check has to be anchored to the version cell itself and not to the line.\n"
            f"  {row[:160]}"
        )
        assert "**Required by:**" in row, (
            f"a delegation row states a version and not what requires the document:\n  {row[:160]}"
        )
        assert "unsuffixed" in row, (
            "every requirement in this profile cites its document WITHOUT a revision, and each row "
            f"has to say so — that is the fact that makes the version cell necessary:\n  {row[:160]}"
        )

    # The row the challenge was about carries Appendix B's entry verbatim, because a paraphrase
    # cannot settle a question about a suffix.
    assert ('"MISB ST 1402.2 MPEG-2 Transport Stream for Class 1/Class 2 Motion Imagery, Audio and '
            'Metadata, Oct 2016."') in flat, (
        "Appendix B entry [48] is no longer quoted verbatim. It is the whole evidence for the "
        "`.2` in the delegation table, and the reason register entry KLV 5's count stays six"
    )

    # And the generalisation, with the page loci that make it re-runnable against the PDF.
    for locus in ("PDF page 7", "PDF pages 63–66", "PDF page 62"):
        assert locus in flat, (
            f"the Appendix-B-only rule no longer states {locus!r}. Its value is that a reader can "
            "re-derive it from the pinned document, and a claim about where facts live needs the "
            "page numbers to be checkable"
        )
    assert "PDF pages 10 to 57" in flat, (
        "the rule's negative half — that no requirement and no body section states a revision — is "
        "the half a reader acts on, and it needs its page range too"
    )


def test_no_verbatim_requirement_quotation_has_had_a_revision_added_to_it():
    """AN ABSENCE, and the most plausible well-meant corruption in this section.

    The profile's requirements cite bare document numbers: "SMPTE ST 336 [13]", "MISB ST 0107 [14]",
    "MISB ST 1402 [48]". An editor who has just read the delegation table will be tempted to make a
    quotation "more useful" by writing the revision into it — and that turns a verbatim quotation
    into a misquotation of a normative requirement, which is the one thing a pinned-document section
    must never do. Presence checks cannot catch an addition; only this can.
    """
    section = _section(KLV_HEADING)
    for wrong in ("SMPTE ST 336:2017 [13]", "MISB ST 0107.3 [14]", "MISB ST 1402.2 [48]",
                  "MISB ST 0102.12 [55]", "MISB ST 0603.5 [12]", "MISB ST 0601.14 [53]"):
        assert wrong not in section, (
            f"{wrong!r} appears in the section. No requirement in MISP-2019.1 cites a revision — "
            "every one of them writes the bare document number and a bracketed reference index — so "
            "a suffix beside a bracketed index is a quotation this document has altered"
        )


#: KLV 2's four live figures, each the figure WITH ITS BASIS. Shared by the guard below and by its
#: vacuity check, so the two cannot drift apart — the property `occurrences_over_tracked_files()`
#: has in `tests/test_cdm_prose_counts.py` and for the same reason.
KLV2_FIGURES = ("120 distinct", "`MISP-2015.1` 84", "**129**", "`MISP-2015.1` 93")


def _figure_occurrences(section_text: str) -> dict[str, int]:
    """How many times each of KLV 2's live figures occurs. The predicate, over text.

    A function rather than an inline count so the vacuity check below can run it against mutated
    copies of the real section without writing to the tree.
    """
    flat = _flat(section_text)
    return {figure: flat.count(figure) for figure in KLV2_FIGURES}


def test_no_requirement_id_in_the_section_names_this_profile_version():
    """AN ABSENCE. MISP-2019.1 contains no requirement of its own, and the section must not invent one.

    All 120 DISTINCT requirement IDs in the pinned copy carry an earlier profile version — 84 of
    them `MISP-2015.1`, which occurs 93 times because it is the one family whose IDs repeat. Stating
    either figure without its basis is what KLV 2 was repaired for on 2026-08-28, and this guard
    asserts BOTH so the repaired form cannot decay back into one number. That is register entry
    KLV 2, and it is the kind of finding a later editor
    "tidies" by rewriting `MISP-2015.1-07` as `MISP-2019.1-07`, which reads more natural and is
    false. Presence checks cannot catch that; only this can.
    """
    section = _section(KLV_HEADING)
    invented = re.findall(r"MISP-2019\.1-\d+", section)
    assert invented == [], (
        f"the section cites {sorted(set(invented))}, and no such requirement ID exists. Every "
        "requirement in MISP-2019.1 is numbered against the profile version that INTRODUCED it — "
        "see register entry KLV 2 — so an ID with this document's own version in it was invented"
    )
    # And the finding itself is on the record, with the count that makes it checkable — each
    # figure EXACTLY ONCE, which is sweep rule 9's carrier rule mechanized. A correction note that
    # re-quoted a figure would leave two copies of it, and dropping the live one would then still
    # pass on the note's copy — the defect the mutation check caught by hand in the commit that
    # repaired this entry. Counting refuses that WITHOUT having to recognise a correction note,
    # which is the predicate rule 9 records as unmechanizable.
    #
    # THE PINNED FORM IS THE FIGURE WITH ITS BASIS AND NEVER THE BARE NUMERAL, and that is forced
    # rather than stylistic: `129`, `120`, `84` and `93` are each live tag numbers or reference
    # numbers elsewhere in this section, so a bare-numeral count would be counting other claims.
    flat = _flat(section)
    for figure in KLV2_FIGURES:
        found = flat.count(figure)
        assert found == 1, (
            f"{figure!r} occurs {found} times in the section and must occur exactly ONCE. KLV 2's "
            "evidence is TWO enumerations, each named with its basis: 120 distinct IDs of which 84 "
            "are MISP-2015.1, and 129 occurrences of which 93 are.\n"
            "  ZERO means a live figure was dropped, and asserting only one enumeration is how the "
            "entry came to state a distinct headline over an occurrence distribution — see the "
            "2026-08-28 repair.\n"
            "  MORE THAN ONE means a second site in this section now carries the figure, which is "
            "the carrier pattern sweep rule 9 names: describe a superseded figure, never re-quote "
            "it, and state each live figure exactly once"
        )


def test_the_klv_2_figure_guard_is_not_vacuous_in_either_direction():
    """The established form, aimed at a class that has already produced a defect once.

    The guard above is four substring counts, and a guard whose real input happens to satisfy it
    is indistinguishable from one that asserts nothing. Both failure directions are mutated here,
    because the two mean opposite things and only one of them is the ordinary staleness case:

    * **dropped** — a live figure removed from the entry, which is the direction the 2026-08-28
      repair was about: an entry stating one enumeration where its evidence is two.
    * **re-quoted** — a live figure stated a SECOND time somewhere in the section, which is the
      carrier pattern of sweep rule 9. This is the direction that a presence check could not see
      at all: with a second copy on the record, dropping the live one still leaves the substring
      behind, so the guard passes over the defect it exists to catch. It was caught by hand, on
      this entry, in the commit that repaired it. A count sees it without having to recognise a
      correction note, which is the reading rule 9 records as refused.
    """
    section = _section(KLV_HEADING)
    live = _figure_occurrences(section)
    assert set(live.values()) == {1}, (
        f"the live guard is already failing ({live}); read its message rather than this one"
    )

    for figure in KLV2_FIGURES:
        dropped = section.replace(figure, "«removed»")
        assert _figure_occurrences(dropped)[figure] == 0, (
            f"removing {figure!r} from the section left the count unmoved, so this mutation "
            "proves nothing about the guard"
        )
        requoted = section.replace(figure, figure + " (and again: " + figure + ")", 1)
        assert _figure_occurrences(requoted)[figure] == 2, (
            f"a section re-quoting {figure!r} did not raise its count, so the guard cannot "
            "distinguish one statement of a figure from several and the carrier direction is "
            "unguarded"
        )


def test_no_epoch_is_stated_anywhere_in_the_section():
    """AN ABSENCE — and since 2026-08-26 an absence with exactly one licensed exception.

    The premise carried into Phase 1 was that the MISP fixes the Precision Time Stamp's epoch. It
    does not: `epoch`, `1970`, `microsecond` and `leap` occur zero times in its 73 pages. Anyone
    who knows the format knows the epoch from ST 0603 and will be tempted to write it down — and
    writing it down would state, in a document whose whole discipline is that it pins what it
    read, a value that came from memory.

    THE RULE WAS NEVER "DO NOT WRITE AN EPOCH". It was "do not write one from memory", and that
    distinction is what this test has to encode now that the distinction has teeth. ST 0601.14 —
    the dictionary the profile delegates to, obtained and pinned on 2026-08-26 — states the epoch
    outright in §6.4 and again in §8.2: SI seconds since 1970-01-01T00:00:00Z, in microseconds,
    leap seconds excluded and therefore not UTC. That value is quoted from a document this
    repository holds by hash, which is the opposite of the failure this test exists to catch.

    So `1970` is admitted in two contexts and no others: beside the statement that the words do
    NOT occur in the profile, which is the original allowance; and beside a citation of ST
    0601.14, which is the new one. A bare epoch with neither anchor is still a value from memory,
    and the profile-absence claim is still asserted positively below so that widening the gate
    cannot quietly retire the finding it was built around.
    """
    section = _section(KLV_HEADING)
    # `1970` is permitted in exactly one context: the sentence listing the words that do NOT
    # occur in the profile. Anywhere else it is an epoch, and an epoch here came from memory of
    # the format rather than from either pinned document. So each occurrence is checked for its
    # context rather than the numeral being banned outright — banning it would force settlement 3
    # to state its own evidence in a paraphrase, which is the weaker of the two failures.
    # THE WINDOW IS WIDER FOR THE SECOND ANCHOR AND NARROW FOR THE FIRST, deliberately. The
    # profile-absence sentence sits right beside its numeral; ST 0601.14's epoch arrives inside a
    # 400-character block quotation of §6.4, so a 220-character window lands in the middle of the
    # quotation and sees neither end of it. 600 still binds — it is a paragraph, not the section —
    # and the alternative was to chop the quotation, which would make a normative sentence from a
    # pinned document into a paraphrase to satisfy a test.
    for match in re.finditer("1970", section):
        window = _flat(section[max(0, match.start() - 220):match.end() + 220])
        wide = _flat(section[max(0, match.start() - 600):match.end() + 600])
        # A THIRD ANCHOR SINCE 2026-09-04, AND IT IS THE ONE THE OTHER TWO WERE STANDING IN
        # FOR. The rule is "do not write an epoch from memory", and the document that DEFINES this
        # epoch normatively — MISB ST 0603.5, whose §6 gives the MISP Time System an "Epoch of
        # 1970-01-01T00:00:00.0Z" and whose Appendix A closes the question with "Nothing has
        # changed across all ST 0603 versions regarding the Epoch" — was not held when this test
        # was written. It is held and pinned now, so quoting it is the strongest form of the thing
        # this test protects rather than an exception to it. The first two anchors stay: the
        # profile-absence finding is still a finding, and ST 0601.14's statement is still quoted
        # where the row set needs it.
        licensed = ("do not occur anywhere" in window or "occur zero times" in window
                    or "ST 0601.14" in wide or "ST 0603.5" in wide)
        assert licensed, (
            "the section states an epoch with none of its three anchors nearby. An epoch is "
            "admitted beside the statement that the profile does NOT contain one, beside a "
            "citation of ST 0601.14, or beside a citation of ST 0603.5 — see settlement 3. With "
            "none, this value came from somewhere other than the documents this phase read: "
            f"...{window[:160]}..."
        )
    flat = _flat(section)
    assert "do not occur anywhere in the 73 pages" in flat, (
        "settlement 3's evidence for the correction is the absence itself, and it has to be "
        "stated as an absence a reader can re-run against the PDF"
    )
    assert "such as International Atomic Time (TAI)" in flat, (
        "the only timescale the profile names, it names as an EXAMPLE. Quoting the 'such as' is "
        "what stops the sentence being read as the profile choosing TAI"
    )
    # AND THE CORRECTION IS ASSERTED TOO, in both halves. Widening the allowance above without
    # this would let the section keep the numeral and lose the reason it is entitled to it.
    assert "1970-01-01T00:00:00Z" in flat, (
        "the section no longer states the epoch ST 0601.14 gives it. The absence in the PROFILE "
        "is a finding; refusing to state what the DICTIONARY says once the dictionary is in hand "
        "would be the discipline eating its own purpose"
    )
    assert "does not represent UTC" in flat, (
        "ST 0601.14's epoch statement is only usable with its negative half: a count of SI "
        "seconds since 1970 that EXCLUDES leap seconds is not UTC, and an adapter that dropped "
        "that clause would emit a UTC instant that is wrong by the leap-second offset"
    )
    assert "does not close on it" in flat, (
        "stating the epoch from ST 0601.14 is exactly the edit that would tempt a later reader to "
        "close park 3, and the section has to say why it does not — ST 0603.5 is still the "
        "normative definition and items 136 and 137 are still its"
    )


def test_the_scope_split_declines_the_essence_and_the_container_together():
    """Settlement 1, and the coupling is the part worth pinning rather than the two declines.

    Declining the video essence is only coherent because the container is declined too: an
    elementary stream in another PID is not in this adapter's payload, so the never-drop rule is
    not engaged. If a later edit widened the input to a transport stream and left the essence
    decline in place, the section would be claiming the right to drop megabytes that ARRIVED — and
    the two sentences are far enough apart that nothing but a test would notice.
    """
    section = _section(KLV_HEADING)
    # The two requirements are quoted in a Markdown blockquote, so a quotation long enough to be
    # worth pinning is wrapped across lines with a `> ` marker in the middle of it. Flattening
    # whitespace is not enough on its own — the marker has to come out first, or the only
    # quotations this file can assert against are the ones short enough to fit on one line, which
    # is the weakening `_flat` was written to avoid.
    quoted = _flat(section.replace("\n> ", " "))
    flat = _flat(section)
    assert "the essence is out of scope because the container is" in flat, (
        "the coupling between the two declines is gone. Each reads as defensible alone and the "
        "pair is what makes either one honest"
    )
    assert "One KLV metadata stream, and nothing else" in flat, (
        "the input's identity is the premise of every decline in settlement 1"
    )
    for requirement, text in (
        ("MISP-2015.1-07", "KLV (Key-Length-Value) Metadata shall be encoded in accordance with "
                           "SMPTE ST 336 [13]."),
        ("MISP-2015.1-08", "KLV Metadata shall be formatted in accordance with MISB ST 0107 [14]."),
    ):
        assert requirement in flat, f"{requirement} is no longer cited"
        assert text in quoted, (
            f"{requirement}'s text is no longer quoted verbatim. A requirement paraphrased is a "
            "requirement a reader cannot check against the PDF, and these two are the ones that "
            "define what this adapter reads"
        )


def test_the_parks_are_numbered_and_the_smpte_one_is_named_as_CLOSED():
    """Thirteen numbered parks, FIVE of them CLOSED, and the SMPTE row's closure held to its date.

    **THIS GUARD USED TO ASSERT THE OPPOSITE AND THAT IS THE MOST USEFUL THING ABOUT IT.** It
    required park 8's row to keep saying *a purchase decision, not a download*, required it not to
    say *public download*, and pinned how many rows did — on the reasoning that the MISB parks and
    the one SMPTE park have the same SHAPE, "obtain the document and pin it", and that collapsing
    them would hide the only entry no browser could close.

    **The reasoning was sound and the premise was false.** SMPTE opened its library in June 2026;
    the maintenance round asked `pub.smpte.org` on 2026-09-03 and got a 200; the publisher round
    fetched both editions the same day for nothing and park 8 closed. So for eleven days this test
    **required the record to state a refuted claim**, and went green the whole time.

    **What that cost, named precisely, because it is the reason this docstring is long.** The
    assertion was labelled a suite check, and what it actually checked was that the record agreed
    with itself: its subject — whether a publisher sells a document — lives at `pub.smpte.org`, and
    no test in this repository can reach it. A **protocol-gated** fact wearing a **suite-gated**
    label cannot fail, because the only thing that could falsify it is a request nobody makes.

    **It is document-gated now and that is a real improvement and a small one.** The row states a
    closure, and the closure's evidence is two PDFs on disk with recorded digests, page counts and
    title-page identities — things the suite CAN reach, and `tests/test_cdm_pins.py` does. It is
    still a tree-agrees-with-itself check; the difference is that the tree now contains the bytes
    the claim is about. **No test here re-asks the publisher, and none should**: rule 12's point is
    that an external reading carries the instant it was taken, not that a suite should take one.

    PARK 1 CLOSED ON 2026-08-26 AND THE NUMBERING DID NOT MOVE, which this test now pins in both
    directions. Parks are cited by number from the row sets, from the fixture plan and from the
    register, so renumbering eleven rows to close a gap would silently re-point every one of those
    citations at a different document — the failure mode is not that a reader sees a gap, it is
    that they do not. So a closed park keeps its row, row 1 says CLOSED, and the public-download
    count drops when a park closes because a closed park no longer offers a reopen route. That count
    is the honest-strength paragraph's own claim, which is why it is asserted rather than left to
    the prose.

    PARK 13 WAS OPENED ON 2026-08-26 BY THE WALK ROUND, and the upper bound moved 12 -> 13 as the
    deliberate act this test exists to force. It is the first park in the table a STREAM opened
    rather than a document: a held stream declares edition 1 in item 65, nothing in either held
    ST 0601 copy dates any item's introduction, and item 22's four octets against a Required Length
    of 2 cannot be classified without ST 0601.1's tag table. Opening it moved the download count the
    other way for the first time - 9 -> 10 - which is the same claim read in reverse and is why the
    count is asserted rather than described.

    AND PARK 13 CLOSED ON 2026-08-26 TOO, hours later, which is the first time this table has had a
    row open and close on one day and the first time the download count has moved TWICE in one - 9
    to 10 on the opening, 10 back to 9 on the closing. THE UPPER BOUND DID NOT MOVE: a closed park
    keeps its number, so the table still has thirteen rows and still refuses a fourteenth.

    THE `superseded` ASSERTION SURVIVED THE CLOSURE AND IS NOW A DIFFERENT CLAIM, which is why it
    was kept rather than deleted. It used to guard a ROUTE - a row that did not say "superseded"
    read as an instruction to fetch the current edition, and the current edition is the one that
    cannot answer the question. The route has been walked, so what the word now records is what was
    actually obtained: edition 1, a superseded revision, rather than the .19 a careless reading
    would have fetched. The assertion is unchanged and its reason is rewritten, because a gate whose
    stated reason has expired is a gate nobody can maintain.

    WHAT THE CLOSURE DID *NOT* LICENSE: dropping `0601.1` from the row. The row now names TWO
    documents - the edition the stream declares and MISB EG 0601.1, which is the document that
    answers to it, there being no "ST 0601.1" at all (register entry KLV 15) - and the version
    string is asserted exactly as before, because a park 13 row that lost it would be a row about
    "ST 0601", which this repository holds three times over.
    """
    section = _section(KLV_HEADING)
    flat = _flat(section)
    for n in range(1, 14):
        assert f"| **{n}** |" in section, (
            f"park {n} is missing from the table. The numbers are cited from the row sets — a hole "
            "in the numbering is a row pointing at nothing"
        )
    assert "| **14** |" not in section, (
        "the park table has grown past thirteen without this test being updated. A new park has to "
        "extend the numbering deliberately, because every row set cites parks by number"
    )
    # Park 13 is the one a STREAM opened, and its reopen route is the one park 4 already walked —
    # a superseded revision from the registry, not "the current ST 0601". A row that lost that
    # distinction would send the next reader to fetch .19 and answer a different question.
    park_13 = [ln for ln in section.splitlines() if ln.startswith("| **13** |")]
    assert len(park_13) == 1, f"expected exactly one park row numbered 13, found {len(park_13)}"
    assert "0601.1" in park_13[0], (
        "park 13's document is MISB ST 0601.1 — the edition item 65 declares on the wire. Without "
        "the version the row is a park on 'ST 0601', which this repository already holds twice"
    )
    assert "superseded" in park_13[0].lower(), (
        "park 13 CLOSED by fetching a SUPERSEDED revision, which is the route park 4 proved. The "
        "word used to guard the route and now records what was obtained - edition 1 rather than the "
        "current edition, which is the one that cannot answer the question. A row that stops saying "
        "so loses the only part of the closure a later reader could check the pin against"
    )
    assert "CLOSED" in park_13[0], (
        "park 13's row no longer says it is closed. It closed on 2026-08-26 by obtaining MISB "
        "EG 0601.1 and ruling item 22's four octets a stream defect; a row that stops saying so "
        "reads as an open park, and this one is the narrowest in the table rather than a live one"
    )
    assert "EG 0601.1" in park_13[0], (
        "park 13's row no longer names MISB EG 0601.1, the document it actually closed on. There is "
        "no 'ST 0601.1' - edition 1 is an Engineering Guideline - so a row naming only the version "
        "string sends the next reader after a document that does not exist. Register entry KLV 15"
    )
    # The closed park keeps its number and says so, and nothing has quietly taken its place.
    park_1 = [ln for ln in section.splitlines() if ln.startswith("| **1** |")]
    assert len(park_1) == 1, f"expected exactly one park row numbered 1, found {len(park_1)}"
    assert "CLOSED" in park_1[0], (
        "park 1's row no longer says it is closed. It was closed on 2026-08-26 by obtaining ST "
        "0601.14 and writing the row set it supports; a row that stops saying so reads as an open "
        "park whose document happens to be on disk — which is what park 2 WAS, from 2026-08-26 "
        "until it closed on 2026-09-04 by writing its own row set. The comparison is kept in its "
        "own tense: park 2 was the shape this failure would produce, and it stopped being it by "
        "doing exactly what park 1 did"
    )
    assert "closed 2026-08-26" in flat.lower(), (
        "the date park 1 closed is gone. A park that closes without a date cannot be checked "
        "against the commit that closed it"
    )
    # PARK 2, CLOSED 2026-09-04, IN THE PARK 1 AND PARK 8 GUARDS' SHAPE: that it is closed, WHEN,
    # and on WHICH document — plus one thing neither of those needs. Park 2 is the only park in
    # this table that closed WITHOUT ACQUIRING ANYTHING, so "the document that closed it" is not
    # what a reader has to be able to check; the ARTEFACT is. A row saying only that the document
    # is held would describe park 2's state on any of the nine days it was open.
    park_2 = [ln for ln in section.splitlines() if ln.startswith("| **2** |")]
    assert len(park_2) == 1, f"expected exactly one park row numbered 2, found {len(park_2)}"
    assert "CLOSED" in park_2[0], (
        "park 2's row no longer says it is closed. It closed on 2026-09-04 by writing the row set "
        "MISB ST 0102.12 supports — seventeen elements, nested under item 48 — and a row that "
        "stops saying so reads as the open park it was the table's own precedent for"
    )
    assert "CLOSED 2026-09-04" in park_2[0], (
        "the date park 2 closed is gone, or is not in the shape gates/parks_table.py reads. That "
        "gate wants exactly '**CLOSED YYYY-MM-DD**' in the title cell, and the closed set it "
        "derives is what park 12's set-claims are checked against"
    )
    assert "0102.12" in park_2[0], (
        "park 2's row no longer names the edition its row set was written from. MISP-2019.1's "
        "Appendix B reference [55] pins 0102.12 and a later revision is a different document"
    )
    assert "seventeen elements" in _flat(park_2[0]), (
        "park 2's row no longer states the ARTEFACT that closed it. Its document had been held "
        "since 2026-08-26 and the park stayed open for nine days on the row set alone, so a "
        "closure cell that names only the pin describes the state the park was in while OPEN. "
        "This is the one closure in the table where the document is not the news"
    )
    assert "~~" in park_2[0], (
        "park 2's title cell is not struck through. gates/parks_table.py requires BOTH the "
        "strikethrough and '**CLOSED YYYY-MM-DD**' before it counts a row closed, so a row with "
        "the date and no strikethrough reads as closed to a person and open to the gate"
    )
    # THE PREAMBLE'S OPEN-ROW CLAIM, WITH ITS NUMBER DERIVED RATHER THAN SPELLED IN THIS NEEDLE.
    # This assertion read `"all eight still open are public downloads" in flat` until 2026-09-05,
    # which is a literal naming a figure it does not derive — the shape `fixtures/klv/README.md`
    # records for its own guard, one file over. Parks 2, 5 and 3 all closed on 2026-09-04 and the
    # preamble did not move, so for a day this needle was the thing keeping the stale pair in place:
    # correcting the prose would have gone RED and leaving it went green. A guard that pins prose to
    # whatever it last said cannot catch prose that stopped being true.
    open_count = len(parks_table.derive().open_parks)
    spelled = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
               "ten", "eleven", "twelve", "thirteen")[open_count]
    assert f"all {spelled} still open are public downloads" in flat, (
        f"the table's summary claim about its open rows does not state today's derived figure. "
        f"gates/parks_table.py reads {open_count} open row(s) — {parks_table.derive().open_parks} — "
        f"so the preamble should read 'all {spelled} still open are public downloads'. It used to "
        "read 'eight are public downloads and one is not', and the ONE was park 8, which closed on "
        "2026-09-03 leaving no row on the other side of the contrast; the comparison stays retired "
        "and only the count moves"
    )
    assert "http://www.gwg.nga.mil/misb" in section and "https://nsgreg.nga.mil/misb.jsp" in section, (
        "the reopen route the open public-download parks share is quoted from the profile's own "
        "FORWARD. Without the URLs the reopen condition is an instruction to go and look. This "
        "message named 'the eleven public parks' until 2026-09-05, a figure last true when eleven "
        "rows were open — the route is quoted once for the rows that share it and the count of "
        "them is derived above, not spelled here"
    )
    # AN ABSENCE, scoped to one row. Park 8 is the SMPTE one, and the failure mode is not that
    # somebody deletes it — it is that somebody normalises its reopen condition into the phrasing
    # the other open rows use, at which point the table reads as one afternoon of work per row. The
    # count is not spelled here: this comment said "the other eleven" and "twelve afternoons" until
    # 2026-09-05, both last true when eleven rows were open, and a comment is a site under rule 9.
    # The row
    # is located by its own document name rather than by position, so reordering the table does
    # not silently turn this into a check on a different row.
    # Rows of the PARK table specifically: `| **n** | ...`. The delegation table's rows also open
    # with `| **`, and one of them names SMPTE ST 336 too — a looser filter matched both and
    # asserted against whichever came first, which is a green test on the wrong table.
    park_rows = [ln for ln in section.splitlines() if re.match(r"\| \*\*\d+\*\* \|", ln)]
    smpte = [ln for ln in park_rows if "SMPTE ST 336" in ln]
    assert len(smpte) == 1, (
        f"expected exactly one park row for SMPTE ST 336, found {len(smpte)} — this is the row "
        "the table priced as a purchase for eleven days and closed on 2026-09-03"
    )
    # THE THREE THINGS A CLOSURE HAS TO SAY, mirroring the park 1 and park 13 guards above: that it
    # is closed, WHEN, and on WHICH document. A closure without a date cannot be checked against
    # the commit that made it, and one without a document cannot be checked against anything.
    assert "CLOSED" in smpte[0], (
        "park 8's row no longer says it is closed. It was closed on 2026-09-03 by obtaining SMPTE "
        "ST 336:2017 from the publisher's own library and ruling both of its residual absences "
        "against §5.3; a row that stops saying so reads as an open park whose document happens to "
        "be on disk — which is what park 2 WAS until 2026-09-04. Kept in its own tense for the "
        "reason the park 1 guard above gives"
    )
    assert "CLOSED 2026-09-03" in smpte[0], (
        "the date park 8 closed is gone, or is not in the shape gates/parks_table.py reads. That "
        "gate wants exactly '**CLOSED YYYY-MM-DD**' in the title cell, and the closed set it "
        "derives is what park 12's set-claims are checked against"
    )
    assert "ST 336:2017" in smpte[0], (
        "park 8's row no longer names the edition it closed on. Two editions were acquired and "
        "only ST 336:2017 is the one MISP-2019.1 pins and the one this park required"
    )
    assert "Public download" not in smpte[0], (
        "park 8's row describes itself as a public download. ST 336 IS a public download — that is "
        "what closed the park — but this row's reopen condition is CLOSED, not a route. Every OPEN "
        "row says 'Public download' because that is how it will be closed; a closed row borrowing "
        "the phrasing of an open one is the uniformity this guard has always been about, pointing "
        "the other way. This message said 'the other eight rows' until 2026-09-05, when the sweep "
        "derived the phrase's real spread: eight rows carry it and only five of them are open, "
        "because parks 2, 3 and 5 closed on 2026-09-04 and each keeps the phrase in a historical "
        "or pre-repair cell. So the count is not stated and the CONTRAST is, which is the claim "
        "this assertion actually rests on"
    )
    # And the OPEN rows DO say it, so the distinction is a real contrast rather than one row
    # being vague.
    downloads = [ln for ln in park_rows if "Public download" in ln]
    assert len(downloads) == 8, (
        f"{len(downloads)} park rows state a public-download reopen condition, expected 8 — and "
        "EVERY open row is now one, which is the change park 8's closure made to this count's "
        "meaning rather than to its value. It has moved five times: 11 to 10 when park 1 closed, "
        "10 to 9 when park 4 closed, 9 to 10 when the walk round opened park 13, 10 back to 9 "
        "when the adjudication round closed it hours later, and 9 to 8 when the off-peak round "
        "closed park 9. The publisher round closed park 8 and this number did NOT move, because "
        "park 8's row never said 'Public download' — it said the opposite. That is the sharpest "
        "form of the finding: the count the honest-strength paragraph rested on was blind to the "
        "one row the paragraph was about. It falls when somebody does the cheap thing and rises "
        "when a round finds a question it cannot answer from what is held; park 13 is the one row "
        "that has done both, and park 8 is the one row that did neither"
    )


def test_the_klv_ambiguity_register_is_numbered_by_its_own_convention():
    """Every `KLV n` present up to the bound, none past it, and every CITATION defined.

    THE COUNT USED TO BE SPELLED IN THIS LINE — "Fourteen entries ... no fifteenth" — and it was
    stale by five entries when the pins round's sweep reached it, having been written when the bound
    was 14 and not moved by any of the three rounds that moved the bound. It is DELETED rather than
    re-synced, per sweep rule 7: the `range()` below is the count, it cannot drift from itself, and a
    docstring restating it is a second site with nothing reading it. The rule that a new entry is a
    deliberate edit is unchanged and is what the upper assertion enforces.

    Numbered per the new adapter's own convention rather than continuing the GMTIF or NITS series,
    because a register is scoped to the document it reads. The upper guard matters as much as the
    lower one: these numbers are cited from the row sets and from the fixture plan, so a register
    that grew without the citations moving is a set of dangling references.

    AND THE OTHER DIRECTION, WHICH THIS TEST DID NOT CHECK AND SHOULD HAVE. It guarded growth
    only, and a citation can outrun the register just as easily as the register can outrun the
    citations. It did: on 2026-08-26 the pin table gained the sentence "Register entry **KLV 9**"
    while KLV 9's entry was written into `klv_pin.json` and never into this document, so for the
    life of that commit this file pointed at a register entry it did not contain — and the guard
    that would have caught it was instead ASSERTING that KLV 9 must not appear. A one-directional
    check on a two-directional invariant reads as protection and is not. Both directions now.
    """
    section = _section(KLV_HEADING)
    # THE BOUND MOVED 10 -> 11 -> 13 ON 2026-08-26, twice in one day, and each edit is the mechanism
    # working rather than an inconvenience. The framing round added KLV 11: ST 0102.12 pins SMPTE
    # ST 336:2007 where the profile and ST 0601.14a pin 2017. The length round added two, both found
    # in a six-page document nobody had read before that day — KLV 12, that two of ST 0107.3's
    # requirement identifiers carry the previous edition's number, and KLV 13, that it sources the BER
    # rules to ITU X.680 where BER is X.690. Moving the bound is the deliberate act the upper guard
    # exists to force, and it has now been forced three times by three rounds that each read a document.
    # THE BOUND MOVED 13 -> 14 ON 2026-08-26 for the first time on evidence that is not a document.
    # The walk round read a real stream and found KLV 14: ST 0601 requires an edition stamp in every
    # packet (ST 0601.8-12, item 65) and no held edition says which items each edition admits, so a
    # reader cannot act on the declaration a conforming emitter is required to send. That is why the
    # round parked instead of ruling, and why park 13 exists.
    # THE BOUND MOVED 14 -> 16 ON 2026-08-26, the same day, and both new entries are about a
    # document's IDENTITY rather than its content - which is a first for this register and is what
    # going to FETCH a document turns up that reading the ones you have cannot. KLV 15: the document
    # ST 0601.14a §8.65 sends a reader to for edition 1, "MISB ST 0601.1", was never published -
    # edition 1 is an Engineering Guideline, EG 0601.1, and the standard has renamed its own
    # history. KLV 16: that document disagrees with itself and with ST 0601.4 about its own date.
    # Note what did NOT happen: KLV 14 was not deleted. Park 13 closing answers its question for
    # edition 1 only, and the entry now carries that as an amendment, because an entry retired on
    # one edition's evidence would overstate a closure that bought exactly one row.
    # THE BOUND MOVED 16 -> 17 IN THE WITNESSED-SET ROUND, and this is the first entry the register
    # has gained from reading TWO editions against each other item by item rather than from reading
    # one. KLV 17: ST 0601.14a states items 11 and 12 as `utf8` and EG 0601.1 states them as `ISO7`,
    # and that is the ONLY column of the only two of the 26 witnessed items where the two editions
    # differ at all. It costs nothing on any octet either edition admits — ISO 646 is a UTF-8
    # subset — which is precisely why an entry is the right home for it: a divergence that costs
    # nothing today is a divergence nobody would remember when it stops costing nothing.
    # THE BOUND MOVED 17 -> 19 ON 2026-08-27 EVENING, and both new entries are about a document
    # that was already held — ST 1402.2, pinned by the off-peak round hours earlier — rather than
    # about any of the four the pins round fetched. That is worth noting here because the round
    # that files a finding is usually the round that fetched the document, and these two are the
    # exception: they are what re-reading a held copy at writing time turns up. Both were
    # RE-DERIVED from the pinned bytes rather than copied from the closing round's report, which is
    # the discipline that separates a register entry from a quotation of one.
    # KLV 18: twenty-five of ST 1402.2's twenty-six requirement identifiers carry no revision
    # suffix, and the twenty-sixth carries the PREVIOUS edition's. It is deliberately not
    # adjudicated — KLV 12 rules the converse shape in ST 0107.3 as provenance, but there the
    # suffixed form is the majority, and here it is one in twenty-six.
    # KLV 19: the four deprecated requirements are withdrawn as RE-SPECIFICATIONS of ISO/IEC
    # 13818-1 and not as facts, so the stream_type and stream_id values they carry still apply. A
    # reader taking "deprecated" in its ordinary sense loses the ability to locate the KLV stream,
    # which is what park 9 existed to buy — the two readings differ by the whole value of the
    # document.
    # THE BOUND MOVED 19 -> 20 ON 2026-08-28, in the round that wrote the IMAPB row set, and it is
    # the first entry here found by COMPUTING against a document rather than by reading one. KLV 20:
    # §8.132's Example Software Value is stated in GHz while the item's Units cell says MHz, so the
    # octets the same row prints are reproducible only after a conversion the row does not mention.
    # It was found by running both mappings, not by noticing the units — which is why it is filed
    # under this round and not under any of the three that read this document before it.
    # THE BOUND MOVED 20 -> 23 ON 2026-09-04, in the park 3 round, and all three come from
    # holding MISB ST 0603.5 — the first entries here filed against a document obtained the same
    # day the entries were written since the pins round. KLV 21: ST 0603.5 §6 derives UTC from the
    # MISP Time System with TWO terms, "its correct offset and inclusion of leap seconds", and ST
    # 0601.14a §6.4's Equation 2 has one, leaving the 82-microsecond residue the standard's own
    # footnote 2 licenses ignoring. The KLV 11 shape: a divergence between a profile's delegation
    # and its field dictionary, registered rather than reconciled. KLV 22: ST 0603.5's Appendix A
    # deprecates the POSIX derivation EG 0601.1's Table 1 note states, and names ST 0601 by series
    # as the family that carried the confusion — which is the authority this adapter's conversion
    # rested on until that appendix could be read. KLV 23: §8.137 states its Format as signed
    # twice in its drawn table and as `Softval = KLVuint` in its conversion line, and its printed
    # example has a clear top bit so it cannot separate the two readings. The third is the only
    # one of the three that changes a decoded value, and it was found by WIRING the item rather
    # than by reading its block — the round that promoted 136 and 137 had to pick a signedness.
    for n in range(1, 24):
        assert f"**KLV {n} —" in section, f"register entry KLV {n} is missing"
    assert "**KLV 24 —" not in section, (
        "the register has grown past KLV 23 without this test being updated"
    )
    # Every `KLV n` this section CITES has an entry in it. The numbers come out of the prose
    # rather than out of a list here, so a citation of KLV 14 fails without anybody maintaining a
    # roster of what is legal to cite.
    cited = {int(m) for m in re.findall(r"KLV (\d+)", section)}
    defined = {int(m) for m in re.findall(r"\*\*KLV (\d+) —", section)}
    assert cited <= defined, (
        f"the section cites register entries it does not define: {sorted(cited - defined)}. That "
        "is the failure this test missed once already — a citation is a promise that an entry "
        "exists, and `klv_pin.json` holding the entry does not discharge it here"
    )
    flat = _flat(section)
    # The two entries whose value is entirely in a precise quotation.
    assert "mandatory for Metadata packets which include a Metadata item for a timestamp" in flat, (
        "KLV 6 rests on the circularity of one sentence, so the sentence has to be quoted. "
        "Paraphrased, the finding reads as an opinion about drafting"
    )
    assert "Three components: Motion Imagery (see definition below), Metadata and/or Audio" in flat, (
        "KLV 7 is a distinction between two DEFINED terms, so Appendix E's definition is the "
        "evidence. Without it the entry is an assertion that two phrases differ"
    )
    # KLV 4 is external context and must say so, on the AEDP-12-2014 precedent.
    assert "explicitly not as an error" in flat, (
        "KLV 4 records the NISP as a year behind the chain, and the honest reading is that it "
        "PREDATES Edition 5. An entry that filed it as an error would be wrong about the document"
    )
    assert "not in `fixtures/klv/spec/`" in flat, (
        "the NISP copy is not pinned, so the one hash in this section that a later re-verification "
        "cannot check has to say so — the AEDP-12 Edition A (2014) treatment"
    )


def test_the_name_ruling_states_both_names_and_rejects_the_alternatives_on_grounds():
    """The adapter name, the fixture directory, and why they differ — with the three rejections.

    80b38d1 had to move three PDFs because one command took the adapter's name where the fixture
    directory's name was wanted. The fix was a map pinned by a test; this is the other half, which
    is that the REASON the two names differ is written down at the moment of choosing rather than
    reconstructed nine months later from a directory listing.
    """
    flat = _flat(_section(KLV_HEADING))
    assert "`stanag4609`" in flat and "`fixtures/klv`" in flat, "the two ruled names are gone"
    assert "a covering document rather than a standalone document" in flat, (
        "the adapter-name ruling rests on the profile describing STANAG 4609 in its own words, "
        "and the quotation is the evidence"
    )
    for rejected in ("`misp`", "`misb`", "`fmv`"):
        assert rejected in flat, f"the rejected alternative {rejected} is no longer named"
    assert ("FMV has no formal definition and conveys different meanings to different "
            "communities") in flat, (
        "`fmv` is rejected BY THE PINNED TEXT, which is the strongest rejection available here. "
        "Dropping the quotation turns it back into a matter of taste"
    )


# ------------------------------- the walk round: a real stream, and the park it opened -----------
#
# THE FIRST NUMBERS IN THIS SECTION THAT CAME OUT OF OCTETS RATHER THAN OUT OF A PDF. Every other
# KLV guard below asserts that the prose agrees with a document; these assert that the prose agrees
# with a STREAM, and the stream is not in the index — `.gitignore` carries `fixtures/klv/streams/`
# because a hundred-megabyte transport container is pinned by hash and never vendored. So the
# derivation test skips when the bytes are absent, on the same rule the PDF-hash check uses, and
# the claims that can be checked without them are checked unconditionally.

#: The two pins the walk round recorded, stated here so the section, the pin record and this file
#: are three sites that must agree rather than one site nobody checks.
KLV_STREAM_PINS = (
    ("day_flight.mpg", "a491ceff524b0008e3076d9eb30782badac2d53053731accc0a4e1226177260e", 102004664),
    ("day_flight.klv", "a810e4b60ff33b1bdc1831594201d8158655c0808bdef1b22d84a9eb26e22e51", 977),
)

KLV_WALK_HEADING = "### The walk over a real stream"


def _klv_stream(name: str) -> pathlib.Path:
    """Where a pinned stream artefact lives, via the one resolver.

    THIS USED TO REBUILD THE PATH AS A LITERAL — `parents[3] / "fixtures" / "klv" / "streams"` —
    which is a second spelling of the repository root and a second statement of a directory the
    pin already names. It is now read from the pin's own `local_path` form, so the record and the
    lookup cannot disagree. See `gates/pin_paths.py`.
    """
    return pin_paths.resolve(f"fixtures/klv/streams/{name}")


def test_the_walk_sections_numbers_are_the_bytes_own_numbers():
    """Re-walk the pinned extraction and check the prose against what comes back.

    THE POINT OF THIS TEST IS THAT THE SECTION SAYS ITS COUNTS ARE DERIVED. A section that claims
    "every count below came out of the walk's output" and is in fact typed is the exact class of
    defect `klv_pin.json`'s `a_derived_count_in_gitignore_had_gone_stale_and_is_corrected` records
    — a number describing itself as derived while nothing re-derives it. So the walk is run again
    here, and the section is asked to agree with it.

    SKIPPED WHEN THE STREAM IS ABSENT, and that is not a hole. The stream is excluded from the
    index by a DIRECTORY rule, so a fresh clone has the prose and not the octets; the pin's hash is
    what a reader re-verifies with, and this test is what the working tree re-verifies with. The
    hashes are asserted first, so a test that runs at all runs against the pinned bytes and never
    against some other clip that happens to share a filename.
    """
    from synapse_cdm.adapters.klv_codec import (
        decode_ber_length, decode_ber_oid, encode_ber_length, is_local_set_key,
        read_local_set_key, walk_local_set, bcc_16,
    )
    for name, digest, size in KLV_STREAM_PINS:
        path = _klv_stream(name)
        if not path.exists():
            pytest.skip(f"{path} is not in the working tree — the stream is pinned, not vendored")
        assert path.stat().st_size == size, f"{name} is the wrong size for the pin"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, (
            f"{name} does not hash to the pinned value — this is a different clip"
        )

    buf = _klv_stream("day_flight.klv").read_bytes()

    packets, offset = [], 0
    while offset < len(buf):
        assert is_local_set_key(buf, offset), f"offset {offset} is not a UAS Datalink LS key"
        after_key = read_local_set_key(buf, offset)
        declared, after_len = decode_ber_length(buf, after_key)
        packets.append((offset, after_key, declared, after_len, list(walk_local_set(buf, offset))))
        offset = after_len + declared

    section = DOC.read_text().split(KLV_WALK_HEADING)[1].split("\n### ")[0]

    # --- the counts the section prints, each re-derived ---
    assert len(packets) == 6, f"the extraction holds {len(packets)} packets"
    assert offset == len(buf), f"{len(buf) - offset} octets left over after the last packet"
    items = [it for _, _, _, _, its in packets for it in its]
    assert {len(its) for _, _, _, _, its in packets} == {26}
    assert len(items) == 156
    assert len({tuple(it.tag for it in its) for _, _, _, _, its in packets}) == 1
    assert len({it.tag for it in items}) == 26
    assert {d for _, _, d, _, _ in packets} == {144, 145}
    assert {a - k for _, k, _, a, _ in packets} == {2}, "packet length fields are not all 2 octets"

    for claim in ("| Packets | **6**", "| Items per packet | **26**", "| Items in total | **156**",
                  "| Distinct tags | **26**"):
        assert claim in section, f"the section no longer states {claim!r}, or states it differently"

    # Minimality, over EVERY length field — the section says 162 and that number is the sum of the
    # six packet-level fields and the 156 item-level ones, so it is checked as that sum.
    checked = 0
    for start, after_key, declared, after_len, its in packets:
        assert buf[after_key:after_len] == encode_ber_length(declared)
        checked += 1
        for it in its:
            _, after_tag = decode_ber_oid(buf, it.tag_offset)
            assert buf[after_tag:it.value_offset] == encode_ber_length(it.length)
            checked += 1
    assert checked == 162, f"{checked} length fields were checked, the section says 162"
    assert "| Length fields that are not minimal — packet or item, all 162 of them | **0**" in section

    # `0x80` never appears as a first length octet — the measurement that shows park 8 was not
    # reached rather than merely not mentioned.
    assert {buf[k] for _, k, _, _, _ in packets} == {0x81}
    assert "**one**: `0x81`. **Never `0x80`**" in section

    # Item 2 first, item 1 last, item 65 present and 0x01 everywhere.
    assert all(its[0].tag == 2 and its[-1].tag == 1 for _, _, _, _, its in packets)
    assert {it.value.hex() for it in items if it.tag == 65} == {"01"}
    assert {it.length for it in items if it.tag == 65} == {1}
    assert all(any(it.tag == 65 for it in its) for _, _, _, _, its in packets)

    # THE CHECKSUMS. Six of six, and the section calls this the load-bearing result because it is
    # what rules out corruption for item 22 — so a silent regression here would leave the section
    # asserting a classification it can no longer support.
    for start, _, _, _, its in packets:
        last = its[-1]
        assert bcc_16(buf[start:last.value_offset]) == int.from_bytes(last.value, "big"), (
            f"the packet at {start} does not checksum — ST 0601.14a §6.6"
        )
    assert "| **Checksums that validate** | **6 of 6**" in section

    # ITEM 22: four octets at six sites, top two zero, and the offsets the section tabulates.
    sites = [(start, it.tag_offset, it.value_offset, it.length, it.value.hex())
             for start, _, _, _, its in packets for it in its if it.tag == 22]
    assert len(sites) == 6
    assert {s[3] for s in sites} == {4}
    assert all(s[4].startswith("0000") for s in sites)
    for start, tag_off, val_off, length, value in sites:
        row = f"| {start} | {tag_off} | {val_off} | {length} | `{value}` |"
        assert row in section, f"the item-22 table's row for the packet at {start} is not\n  {row}"


def test_the_walk_section_withdraws_the_era_premise_and_names_where_it_came_from():
    """A briefing defect recorded with its SOURCE, on the settlement-3 precedent.

    The round was briefed to walk an "ST 0601.8-era" clip and the claim came from the `droneklv`
    README, which states the edition that LIBRARY supports — a fact about a decoder read as a fact
    about an emitter. The withdrawal is worth a test for the reason settlement 3's corrected epoch
    premise is: a false premise that is quietly deleted leaves the habit that produced it, and the
    next round has no way to see that this section has been wrong this way before. So the entry has
    to keep BOTH halves — that the claim is withdrawn, and where it came from.
    """
    flat = _flat(DOC.read_text().split(KLV_WALK_HEADING)[1].split("\n### ")[0])
    assert "ST 0601.8-era" in flat, "the withdrawn claim is no longer quoted, so nothing says what was withdrawn"
    assert "WITHDRAWN" in flat, "the era premise no longer says it is withdrawn"
    assert "droneklv" in flat, (
        "the withdrawn premise no longer names its source. A defect recorded without its source is "
        "a confession rather than a finding — the useful half is that a decoder's supported edition "
        "was read as an emitter's"
    )
    assert "the edition the library supports" in flat.lower(), (
        "the distinction that makes this a defect — a decoder's supported edition against an "
        "emitter's — is gone, and without it the withdrawal reads as a change of mind"
    )


def test_the_walk_rounds_ruling_and_its_park_do_not_depend_on_each_other():
    """Act 2 is recorded UNCONDITIONED, and the park keeps three candidates rather than two.

    These are one test because they are one discipline. The ruling — the framing layer is correct
    as shipped and the flag is the value-decoding layer's — must not be phrased as conditional on
    whether item 65's stamp is trustworthy, or the next round reopens it while re-deciding the
    edition question. And the park must keep the third candidate: if item 22 postdates edition 1
    then it is an UNKNOWN TAG under the declared edition, the four octets are opaque, and the
    length question never arises at all. A two-candidate park has silently assumed the item exists
    in edition 1, which is the assumption the whole round refused to make.
    """
    section = DOC.read_text().split(KLV_WALK_HEADING)[1].split("\n### ")[0]
    flat = _flat(section)
    assert "correct as shipped" in flat.lower(), "Act 2's ruling on the framing layer is gone"
    assert "unconditioned on the edition question" in flat, (
        "the ruling no longer says it is unconditioned. That word is what stops the next round "
        "reopening it: whether the stamp is trustworthy changes what the four octets MEAN and "
        "changes nothing about which layer owes the check"
    )
    assert "value-decoding layer" in flat, "the layer that owes the flag is no longer named"
    for candidate in ("**(a)**", "**(b)**", "**(c)**"):
        assert candidate in section, (
            f"candidate {candidate} is gone from the disposition. Three is the honest count — "
            "dropping (c) assumes item 22 exists in edition 1, which is the assumption the round "
            "declined to make"
        )
    assert "the length question never arises" in flat, (
        "candidate (c)'s consequence is the one that makes it a different KIND of answer rather "
        "than a variant of (a), and it is what makes the third candidate worth carrying"
    )
    assert "transmission corruption" in flat.lower(), (
        "the ruled-out candidate is gone. The checksums decided it, and a park that does not say "
        "what it eliminated reads as a park that eliminated nothing"
    )
    assert "ST 0601.1's tag table" in section or "ST 0601.1's TAG TABLE" in section, (
        "the deciding fact is no longer named. A park whose deciding fact is unnamed cannot be "
        "closed by anyone but its author"
    )


def test_the_walk_round_did_not_touch_parks_8_or_9_and_says_so_with_the_measurement():
    """Two absences, each stated as a measurement rather than as a disclaimer.

    "Park 8 was not reached" and "park 9 is untouched" are cheap to write and impossible to check.
    What makes them checkable is that the stream was MEASURED for both: `0x80` does not occur as a
    first length octet in 977 octets, and the PES observation that might have looked like park 9
    work is filed with its numbers and explicitly not acted on. The failure mode this guards is a
    later editor reading the PES paragraph as transport-layer coverage.
    """
    flat = _flat(DOC.read_text().split(KLV_WALK_HEADING)[1].split("\n### ")[0])
    assert "204 transport packets" in flat and "198 carry a PES header and no payload" in flat, (
        "the PES observation lost its numbers. Filed WITH them it is a measured case waiting for "
        "whoever opens park 9; filed without them it is a suspicion"
    )
    assert "park 9" in flat.lower(), "the PES observation no longer names the park that owns it"
    assert "did not open, did not close and did not narrow" in flat, (
        "the PES paragraph no longer says what it did NOT do to park 9, which is the whole reason "
        "a transport-layer observation is allowed to be recorded in a KLV section at all"
    )
    assert "park 8" in flat.lower() and "does not occur as a first length octet" in flat, (
        "park 8's non-reach is no longer stated as a measurement over the stream. Stated as a "
        "disclaimer it is unfalsifiable; stated as a measurement it is the prediction 'neither is "
        "reachable from a conforming stream' being confirmed"
    )


# ------------------- the provenance round: an origin verified, and a lead that did not -----------
#
# THE ROUND WHOSE USEFUL RESULT IS A NEGATIVE, which is the case these guards exist for. It was sent
# to verify one lead — that the held clip might be one of MISB's own supplementary test files — and
# the lead did not verify. Three things can go wrong with a section like that and each has a test:
# the negative can quietly drift into a REFUTATION it never earned; the adjacent fact that DID
# verify (where the bytes came from) can be reported as though it were the lead; and the route list
# can lose the failure modes, at which point the next round re-runs the hunt.

PROVENANCE_HEADING = "### The Day Flight provenance round"

#: The origin the round established, stated here so the section, the pin record, the fixture README
#: and this file are FOUR sites that must agree. `KLV_STREAM_PINS` above is the precedent: a hash
#: asserted at one site is a hash nobody checks.
DAY_FLIGHT_ORIGIN = "https://samples.ffmpeg.org/MPEG2/mpegts-klv/Day%20Flight.mpg"


def _provenance_section() -> str:
    return DOC.read_text().split(PROVENANCE_HEADING)[1].split("\n### ")[0]


def test_the_stream_origin_is_stated_identically_at_every_site_that_states_it():
    """Four sites, one URL — and the pin record is the one that has to carry it.

    The round's finding about this repository is that the transport-stream pin recorded a hash, a
    byte count, a local path and an extraction command and NO ORIGIN, while every PDF beside it
    records the URL that served it. A fix that wrote the URL into the prose and not into the pin
    would leave the pin exactly as unreproducible as it was, so the pin record is asserted first.
    """
    record = json.loads((DOC.parent / "fixtures/klv/spec/klv_pin.json").read_text())
    pin = record["walk_ruling_real_stream_2026_08_26"]["the_two_pins"]["transport_stream"]
    assert pin.get("origin_url") == DAY_FLIGHT_ORIGIN, (
        "the transport-stream pin has no `origin_url`, or it has drifted. This field is the whole "
        "repair the provenance round made to this record"
    )
    assert pin["sha256"] == KLV_STREAM_PINS[0][1] and pin["bytes"] == KLV_STREAM_PINS[0][2], (
        "the origin was added to a pin whose hash or byte count moved, which would mean the origin "
        "describes a different file than the one this suite walks"
    )
    for site, text in (
        ("FORMAT_COVERAGE.md", _provenance_section()),
        ("fixtures/klv/README.md", (DOC.parent / "fixtures/klv/README.md").read_text()),
    ):
        assert DAY_FLIGHT_ORIGIN in text, f"{site} no longer states the origin URL"
    section = _flat(_provenance_section())
    assert "102 004 664" in _provenance_section() and "content-length" in section, (
        "the origin is stated without the server's own byte count beside it. That header is what "
        "makes the claim checkable by somebody who has not got the file"
    )
    assert "cmp" in section and "identical" in section.lower(), (
        "the section no longer says the two files were COMPARED. Agreeing digests and identical "
        "bytes are different claims and the stronger one was available"
    )


def test_the_lead_is_closed_as_unverifiable_and_never_as_refuted():
    """The distinction the whole round turns on, and the one an editor would flatten.

    MISB's test-file area was account-gated and is not in the index, so absence there is not
    evidence of absence: the lead is UNVERIFIED and unverifiable from held routes, which is weaker
    and more accurate than refuted. A section that said "refuted" would be asserting something no
    held byte supports — and it would close a question that is still open.
    """
    section = _provenance_section()
    flat = _flat(section)
    assert "unverifiable from the routes this repository can reach" in flat, (
        "the disposition no longer says WHAT KIND of not-verified this is. 'Unverified' alone reads "
        "as 'nobody looked'"
    )
    assert "neither verifies nor refutes" in flat, (
        "the section no longer says the origin cannot settle the lead in either direction, which is "
        "the sentence that stops a later reader treating samples.ffmpeg.org as a refutation"
    )
    assert "a491ceff" in section and "MISB listing that names" in flat, (
        "the reopen condition no longer states both of the two things that would verify it — bytes "
        "hashing to the pin, or a listing naming the file in text"
    )
    # AND THE LEAD ITSELF SURVIVES VERBATIM in the adjudication round's section. A lead edited into
    # its own answer leaves no record of what was suspected on what grounds.
    adjudication = _flat(DOC.read_text().split("### Park 13 adjudicated and CLOSED")[1].split("\n### ")[0])
    assert "A lead, not a finding: the held stream may be one of MISB's own test files." in adjudication, (
        "the original lead sentence is gone from the adjudication section. It is the record of what "
        "was suspected before the routes were run, and the round that ran them does not get to "
        "rewrite it"
    )
    assert "DISPOSITIONED 2026-08-26" in adjudication, (
        "the lead paragraph no longer points at its disposition, so a reader meeting the lead first "
        "has no way to know it was chased"
    )
    # AND THE POINTER SAYS THE SAME KIND OF NOT-VERIFIED as the section it points at. A pointer
    # reading "refuted" beside a section reading "unverifiable" is worse than no pointer: the
    # adjudication section is where a reader meets the lead first, so it is where the overstatement
    # would be believed.
    assert "closed as unverifiable from the routes this repository can reach" in adjudication, (
        "the disposition pointer in the adjudication section no longer states the disposition in "
        "the same terms the provenance section rules it. MISB's test-file area was account-gated "
        "and is not in the index, so 'refuted' is a claim no held byte supports"
    )


def test_every_route_is_named_with_its_own_failure_mode():
    """A route list without failure modes is an invitation to re-run the hunt.

    That is the stated purpose of the list: "so nobody re-runs the hunt". A row saying a route was
    tried buys nothing — the next round tries it again. A row saying WHY it could not succeed is
    what retires it, and route 1's failure mode is the load-bearing one because it is not "the
    crawler missed it" but "the public site never served motion imagery, and MISB says so".
    """
    section = _provenance_section()
    flat = _flat(section)
    # Checked STRUCTURALLY rather than by counting a phrase. The failure mode lives in the table's
    # third column, so what has to hold is that every route row HAS a third cell and that the cell
    # says something — a row whose failure mode is an empty cell or a dash is the exact defect, and
    # a substring count over the section cannot see it.
    # SCOPED TO THE ROUTE TABLE and not to the section, because the origin table above it has rows
    # that begin `| **` too — `| **Origin URL** | … |` — and a section-wide parse folds them in.
    # That is the disjunction failure this file keeps finding: a check that reads the right rows by
    # accident passes for the wrong reason and stops passing when a row moves.
    table = section.split("#### The three routes")[1].split("\n####")[0]
    rows = {}
    for line in table.splitlines():
        if line.startswith("| **") and "—" in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0].split("—")[0].strip("* ")] = cells
    assert len(rows) == 5, (
        f"the route table parsed to {sorted(rows)}. Five routes were run and each owns one row; a "
        "parse that finds four has lost one, and a parse that finds six is reading another table"
    )
    for route in ("1", "1b", "1c", "2", "3"):
        assert route in rows, f"route row {route!r} is gone from the route table"
        cells = rows[route]
        assert len(cells) == 3, f"route {route} has {len(cells)} cells, not route | swept | failure mode"
        assert len(cells[2]) >= 60, (
            f"route {route}'s failure mode is {cells[2]!r}. A route recorded without one is a route "
            "the next round repeats, which is the stated purpose of this table"
        )
        assert len(cells[1]) >= 60, (
            f"route {route} does not say what was swept. 'We looked' is not a sweep; a stated set "
            "of URLs over a stated host is"
        )
    # The counts that make the negatives checkable rather than assertable. Each is derived from a
    # dump held in `fixtures/klv/provenance/` and pinned in `klv_pin.json`.
    for count in ("2 961", "770", "17 806", "26 837", "14 310", "1 442", "63 356",
                  "16 949", "2 308", "20 081 234"):
        assert count in section, (
            f"the derived count {count!r} is gone. These are what turn 'we looked and found "
            "nothing' into a sweep of stated size over a stated set of hosts"
        )
    assert "smaller than the 102 004 664-byte stream" in section, (
        "the one archive the public MISB host ever served is no longer excluded by arithmetic. "
        "AllMISBDocs.zip is the single candidate that could have HIDDEN a stream, and the byte "
        "count is what rules it out rather than an assumption about what a zip named for documents "
        "contains"
    )
    assert "children's educational clips" in section, (
        "the five `.mpg` files the sweep did find are no longer characterised. Reported as a bare "
        "count they look like leads; named as what they are, they are the sweep working"
    )


def test_the_corroboration_is_quoted_and_filed_below_verification():
    """MISB's own sentence, verbatim, because it is what makes route 1's zero mean something.

    The FAQ is the round's best evidence and it is NOT verification: it says MISB had test files
    behind an account and names no filename. So two things are asserted — that the sentence is
    quoted rather than paraphrased, and that the section says which of the two claims it
    corroborates. It corroborates the CHANGELOG SENTENCE, not the lead.
    """
    section = _provenance_section()
    flat = _flat(section)
    # The quotation sits in a blockquote and carries bold markers, so `_flat` alone leaves `> ` and
    # `**` inside it. Stripping both is what lets the asserted phrase be the SENTENCE rather than
    # whichever fragment happens to survive the wrapping.
    quoted = " ".join(section.replace("**", "").replace("\n>", " ").split())
    assert ("If you need access to draft documents, test files, and other support documentation "
            "follow the instructions on the website to apply for an account to access the MISB "
            "protected website.") in quoted, (
        "the FAQ sentence is no longer quoted verbatim. Paraphrased, 'MISB kept test files behind a "
        "login' is an assertion about a website; quoted, it is the website's own statement and it "
        "is what converts route 1's zero from a gap into an explanation"
    )
    assert "401" in section and "protected" in flat, (
        "the protected site's HTTP status is gone. That the archive holds the REFUSAL and not the "
        "content is the difference between a route that was tried and one that was blocked"
    )
    assert "corroborated, not contradicted" in flat, (
        "the section no longer states that the changelog sentence which motivated the lead survives "
        "the fetch. The standing rule is that a fetch contradicting it STOPS the round, so whether "
        "it was contradicted is a fact the section owes"
    )


def test_the_origin_does_not_reach_the_park_13_classification_and_says_why():
    """The strongest form of the claim: it would not have moved had the lead VERIFIED.

    A section that said "the lead did not verify, so nothing changes" would leave the reader unable
    to tell whether the classification survived on its merits or on the failure of the hunt. The
    ruling's two bases are a document's table and a current requirement, and a publisher is an input
    to neither — so the counterfactual is the honest statement and it is the one asserted here.
    """
    flat = _flat(_provenance_section())
    assert "would have been unaffected had the lead verified" in flat, (
        "the section no longer states the counterfactual, so 'unaffected' reads as a consequence of "
        "finding nothing rather than as a property of the ruling"
    )
    assert "factual" in flat and "normative" in flat and "ST 0601.13-29" in flat, (
        "the two bases are no longer both named. Saying only the factual one overstates what an "
        "Engineering Guideline can require; saying only the normative one leaves the retroactivity "
        "objection unanswered"
    )
    assert "publisher of the file is an input to neither" in flat, (
        "the reason the origin cannot reach the classification is gone, and it is one sentence"
    )
    assert "fielded emitter" in flat and "published test file" in flat, (
        "the section no longer says what the failed verification COSTS. The lead existed to separate "
        "those two, and a round that reports only what it kept has not said what it lost"
    )


def test_the_briefing_definition_of_candidate_a_is_withdrawn_with_what_supersedes_it():
    """The second briefing defect, filed the way the first one was.

    `test_the_walk_section_withdraws_the_era_premise_and_names_where_it_came_from` guards the first:
    a withdrawal has to keep BOTH halves, the claim and its source, or it reads as a change of mind.
    The same shape applies to a DEFINITION: the adjudication round's briefing defined candidate (a)
    as requiring declared-edition normativity, and its own Act 2(iii) refuted that. So the entry
    must name what was withdrawn, what refuted it, and what stands in its place — and it must carry
    the annotation that closure did NOT discharge.
    """
    flat = _flat(_provenance_section())
    assert "Act 2(iii)" in flat, (
        "the withdrawal no longer names the act that refuted the definition. Without it, this is an "
        "editor disagreeing with a briefing rather than a briefing refuting itself"
    )
    assert "Engineering Guideline" in flat and (
        "in order to enforce requirements upon developers implementing this document" in flat), (
        "the quotation that does the refuting is gone. That an EG is not enforceable is the series' "
        "own account of why it converted to a Standard, and paraphrased it becomes an opinion"
    )
    assert "factual/normative split supersedes" in flat, (
        "the entry says what was withdrawn and not what replaced it, which leaves candidate (a) "
        "with no definition at all"
    )
    assert "retroactivity is still unestablished" in flat and "standing annotation" in flat, (
        "ST 0601.13-29's unestablished retroactivity has been shed. Park 13 closed on edition 1's "
        "own table — the FACTUAL basis — which is a different move from establishing that a "
        "requirement stamped edition 13 reaches an emitter written against edition 1. An annotation "
        "dropped at closure is a question that stops being asked without being answered"
    )


def test_the_provenance_round_states_what_it_did_not_touch():
    """The absences, each one a thing a reader would otherwise have to verify by reading everything.

    Same discipline as the walk round's and the adjudication round's closing lists. The two that
    matter most here are that no park moved — a round about provenance has no business moving one —
    and that the ambiguity register did not grow, because this round's finding is about THIS
    repository's pinning and the register's subject is the documents.
    """
    flat = _flat(_provenance_section())
    assert "No park moved" in flat, "the section no longer states that no park moved"
    assert "KLV 14 stays open as scoped" in flat, (
        "KLV 14's state is unstated. Park 13 closing answered its question for edition 1 only, and "
        "a provenance round is not the round that retires it"
    )
    assert "parks 8 and 9 are untouched" in flat.lower(), "parks 8 and 9 are no longer named"
    assert "141" in flat and "not yet" in flat, (
        "the tag row set's state is gone. A round that fetched a hundred megabytes and moved no row "
        "should say so"
    )
    assert "No specification was fetched" in flat, (
        "the section no longer says it pinned no document, which is what keeps the pin counts in "
        "`klv_pin.json` from needing a reader to re-derive them"
    )
    assert "protected site was not accessed" in flat.lower() and "not a fetch" in flat, (
        "the one route this repository declined is no longer recorded as declined. Applying for an "
        "NGA account is a relationship rather than a fetch, and a route left unmentioned reads as a "
        "route nobody thought of"
    )


def test_the_klv_fixture_directory_holds_the_generators_payloads_and_says_what_each_catches():
    """The INVERTED form of a Phase 1 test, and the one whose old claim was an EMPTY DIRECTORY.

    Until the witnessed-set round this test asserted `fixtures/klv` held no payload at all, and
    read the README for the two sentences that made the emptiness a park rather than an oversight:
    "There are none yet" and the two failure modes of the harness command it printed. Adapter #10
    has shipped, so all three of those claims are false and the test asserts what replaced them.

    WHAT IS WORTH ASSERTING NOW, AND WHY EACH HALF IS HERE:

    * **the payloads on disk are exactly the ones the generator writes** — a hand-written `.klv`
      would be a payload nothing cites, which is the rule every fixture set in this repository
      follows and the one this directory spent six rounds unable to break;
    * **every payload has a parsed twin and a golden** — a binary fixture with no twin is a
      lossless check reported SKIP, which is how a never-drop claim goes unmeasured;
    * **the README still explains itself**, and specifically still quotes the sentence it used to
      open with. A directory that fills up and loses the record of having been empty loses the only
      part a later reader could check the parks against.
    """
    from synapse_cdm.adapters import stanag4609            # noqa: F401 - registers the adapter
    module = _klv_build_fixtures()

    expected = {spec["name"] for spec in module.ADAPTER_FIXTURES}
    payloads = {p.stem for p in KLV_FIXTURES.glob("*.klv")}
    assert payloads == expected, (
        f"fixtures/klv holds payloads {sorted(payloads)} and the generator writes "
        f"{sorted(expected)}. Every fixture here is built by fixtures/klv/spec/build_fixtures.py; "
        "a hand-written one is a byte nobody cites, which is the rule this directory could not "
        "break for six rounds and must not break now that it can"
    )
    assert len(expected) == 42, (
        f"{len(expected)} adapter fixtures, expected forty-two — ten from the witnessed-set "
        "round, the seven `security_*` payloads the park 2 round added for ST 0102.12's "
        "seventeen elements inside item 48, the six `security_object_country_codes_*` "
        "payloads the text-pins round added on 2026-09-04 once RFC 2781 was held (a byte-order "
        "mark in each direction, the no-BOM default, `ST 0102.10-24`'s semi-colon split, and the "
        "two refusals — an odd octet count and a lone surrogate), and the NINE the park 5 round "
        "added the same day for the fifteen document-witnessed items: the fourteen IMAPB items "
        "from their own printed examples, RULING 4's pair, all eight of ST 1201.3 Table 2's "
        "special patterns, tag 128's printed pack example, a short pack refused, a course of "
        "exactly 360 degrees, a zero-length IMAPB item and one past its Max Length; and the FIVE "
        "the park 3 round added the same day for items 136 and 137 — both §8.x printed examples "
        "in one packet, each of §6.4's two equations alone, a NEGATIVE pair the document prints "
        "no example for, and a zero-length pair proving an explicit unknown is not a +0 "
        "adjustment; and the FIVE the pre-release round added on 2026-09-05 for tag 75 under its "
        "RULING 4 — §8.75's own printed example with no coordinates and therefore no Position, "
        "tag 75 alone filling `Position.alt_m`, both HAE items agreeing inside tag 75's own LSB "
        "and raising nothing, both disagreeing by 9 265 m and raising `hae_items_disagree`, and "
        "tag 75 beside tag 15 at values that are deliberately NOT the printed pair, because "
        "§8.15 and §8.75 print the same one"
    )
    for name in sorted(expected):
        assert (KLV_FIXTURES / f"{name}.parsed.json").is_file(), (
            f"{name}.klv has no parsed twin. A bytes-only fixture has no leaf structure for the "
            "harness to harvest, so its lossless check is reported SKIP — and an unrun check that "
            "reads as a pass is how a never-drop claim goes unmeasured"
        )
        for golden in (f"{name}.cdm.json", f"{name}.parsed.cdm.json"):
            assert (KLV_FIXTURES / "golden" / golden).is_file(), f"missing golden {golden}"
    assert (KLV_FIXTURES / "spec").is_dir(), "fixtures/klv/spec is where the pin lives"
    assert (KLV_FIXTURES / "framing").is_dir(), "fixtures/klv/framing holds the framing fixtures"

    readme = KLV_README.read_text()
    assert "There are none yet" in readme, (
        "the README no longer quotes the sentence it opened with for six rounds. It is kept as a "
        "quotation rather than deleted for the reason every withdrawn premise in this section is "
        "kept: a directory that fills up and loses the record of having been empty loses the "
        "evidence a reader could check the parks against"
    )
    assert "There are THIRTY-SEVEN" in readme, "the README does not state the new count"
    # **THE COUNT SENTENCE HAD DECAYED AND THIS ASSERTION IS WHY NOTHING CAUGHT IT.** It read
    # `assert "There are SEVENTEEN" in readme` from the park 2 round until 2026-09-04, and the
    # text-pins round of the same day added six fixtures without re-dating the sentence — so the
    # README said SEVENTEEN while twenty-three payloads sat beside it, and this test ASSERTED the
    # stale string rather than catching it. A literal that names a number the test does not derive
    # is a check that pins the prose to whatever it happened to say. The count above is now
    # derived — `len(expected)` — and the historical strings below are asserted as QUOTATIONS,
    # which is what they are, so the same failure cannot recur silently: a round that adds a
    # fixture and does not re-date the sentence fails on the derived count, not on a literal.
    assert "There were THIRTY-TWO" in readme, (
        "the README no longer records that the count was THIRTY-TWO between the park 5 round and "
        "the park 3 round of 2026-09-04. FOUR rounds moved this count in one day and every "
        "intermediate value is kept, for the reason the note below gives"
    )
    assert "There were TWENTY-THREE" in readme, (
        "the README no longer records that the count was TWENTY-THREE between the text-pins round "
        "and the park 5 round of 2026-09-04. Both moved it on the same day and the middle value is "
        "the one that had no trace at all — see the note above this assertion"
    )
    assert "There were SEVENTEEN" in readme, (
        "the README no longer records that the count was SEVENTEEN between the park 2 round and "
        "the text-pins round. It is re-dated rather than re-synced for the same reason the "
        "opening sentence is quoted rather than deleted"
    )
    assert "There were TEN" in readme, (
        "the README no longer records that the count was TEN between the witnessed-set round "
        "and the park 2 round. It is re-dated rather than re-synced for the same reason the "
        "opening sentence is quoted rather than deleted: a count that moves and leaves no "
        "trace of having moved is a count a reader cannot check against a commit"
    )
    assert "NoFixturesFound" not in readme and "unknown adapter" not in readme, (
        "the README still promises the two failures the harness command used to produce. It "
        "produces neither now, and a demonstration of a failure that no longer fails is a wrong "
        "instruction — which is exactly why tests/test_cdm_consumer_path.py took this site off "
        "its deliberate-failure allowlist"
    )
    flat = _flat(_section(KLV_HEADING))
    assert "self-consistency without an external anchor" in flat, (
        "the round-trip trap is gone from the fixture section. It has NOT been solved by shipping "
        "fixtures — what discharges it is that every value in the value-carrying fixture is the "
        "document's own printed example, and saying so requires still naming the trap"
    )
    assert "check_against_the_documents_own_examples" in flat, (
        "the fixture section claims an external anchor and does not name the check that provides "
        "it. An anchor nobody runs is a claim"
    )


def test_migrations_records_the_phase_1_row_set_and_why_it_proposes_nothing():
    """A Phase 1 that proposes no field, said out loud.

    `MIGRATIONS.md`'s own rule for the section above this one is that "'no entry' and 'nobody wrote
    an entry' look identical from here". The same indistinguishability applies one level up: a row
    set that landed with no schema question and one nobody examined for schema questions leave the
    same trace, which is none. So the entry has to exist and it has to say which gaps it reached
    rather than only that it reached none.
    """
    text = MIGRATIONS.read_text()
    flat = _flat(text)
    assert "Row sets written as specifications, with no adapter code yet" in text, (
        "the Phase 1 heading is gone. Three earlier Phase 1 commits wrote nothing in this file and "
        "that is the gap it was added to close"
    )
    assert "`stanag4609`" in text, "the #10 entry is missing"
    assert "no gap is opened and no field proposed" in flat, (
        "the entry's whole content is that it proposes nothing, stated rather than inferred"
    )
    for gap in ("Gap 23", "Gap 18"):
        assert gap in text, (
            f"{gap} is no longer named. The two places the CDM genuinely has nowhere to put "
            "something are the useful result of this phase, and an entry that only said 'nothing "
            "to propose' would have buried them"
        )
    assert "epoch" in flat and "such as International Atomic Time (TAI)" in flat, (
        "the false premise this phase corrected has to be recorded here too — a correction stated "
        "in one document and not the other is the drift this file's own procedure warns about"
    )


# ------------------------------------------------- the CAT048 edition lineage (read-and-rule)
#
# 22 CAT048 edition PDFs landed in `fixtures/cat048/spec/history/` and NOTHING in the row set moved:
# the governing text is Edition 1.32 alone. So what these tests pin is not a mapping — it is the
# lineage's own claims, and specifically the ones a later reader would otherwise have to re-derive
# from 22 documents: which edition changed which item, which edition is missing, and the verdict
# that no change record contradicts anything the row set asserts.
#
# `tests/test_cdm_pins.py` owns the placement, the counts and the not-a-pin property. This owns the
# READING.

CAT048_HEADING = "## ASTERIX Category 048"
LINEAGE_HEADING = "### The edition history"

#: The change-record entries this row set actually leans on, each transcribed from Edition 1.32's
#: own Document Change Record (printed pages iv–vi) and corroborated against Edition 1.30's.
#: Keyed by edition, because the edition is the fact a settlement cites when it says "Edition 1.30
#: relaxed" — and a table that lost the pairing would let that citation drift.
CAT048_LINEAGE = (
    ("1.16", "SI/II Indication added to I048/230"),
    ("1.17", "I048/030 codes 19, 20"),
    ("1.21", "X-Pulse indication added to I048/020 1st ext."),
    ("1.22", "definition of `CDM` in I048/170 updated"),
    ("1.23", "bit 1 of I048/120 changed to an FX-bit in line with Part 1"),
    ("1.24", "I048/030 value 24 defined and the data item renamed"),
    ("1.27", "I048/030 value 31"),
    ("1.30", "the encoding rules of I048/220, /230, /240 and /250 all updated"),
    ("1.31", "second extension added to I048/020"),
    ("1.32", "§5.1's \"Standard Data Items\" table removed"),
)


def _lineage() -> str:
    section = _section(CAT048_HEADING)
    start = section.index(LINEAGE_HEADING)
    return section[start:section.index("\n### ", start + 10)]


def test_the_lineage_section_exists_and_says_the_pin_did_not_move():
    """The load-bearing sentence of the whole round: 22 editions, none of them governing.

    A section that lands 21 further editions of the same standard beside the pin is one edit away
    from a reader concluding that a row was read against one of them. So the disclaimer is asserted,
    not merely written, and the pin table's own provenance row is asserted with it — that row said
    "Editions NOT read: 1.31 and earlier" and this commit made it false.
    """
    lineage = _flat(_lineage())
    assert "The governing text is still Edition 1.32 alone" in lineage, (
        "the lineage section no longer opens by saying the pin did not move"
    )
    assert "none of them a pin" in lineage, (
        "the heading's own disclaimer is what a reader skimming the table of contents sees"
    )
    pin_section = _flat(_section(CAT048_HEADING))
    assert "the governing text is still 1.32 alone and no row is read against any other edition" \
        in pin_section, (
        "the pin table's provenance row no longer carries the disclaimer. Before this commit it "
        "read 'Editions NOT read | 1.31 and earlier', which the commit falsified — a corrected row "
        "that drops the constraint is worse than the stale one"
    )
    assert "Editions NOT read" not in pin_section, (
        "AN ABSENCE: the stale provenance row is back. All 22 editions are in hand and their change "
        "records read, so a row saying they were not is a false statement about this repository"
    )


@pytest.mark.parametrize("edition,change", CAT048_LINEAGE, ids=lambda x: str(x)[:34])
def test_the_lineage_table_pairs_each_edition_with_what_its_record_says_changed(edition, change):
    """Edition and change on ONE row, because the pairing is the fact.

    Asserted row-scoped rather than section-scoped for the reason mutation keeps finding: every one
    of these edition numbers appears elsewhere in the section — in the register, in the verdict
    table, in the pin rows — so `edition in section and change in section` is a disjunction that
    passes when the two are on different lines.
    """
    rows = [ln for ln in _lineage().splitlines() if ln.startswith(f"| {edition} |")
            or ln.startswith(f"| **{edition}** |")]
    assert len(rows) == 1, (
        f"expected exactly one lineage row for edition {edition}, found {len(rows)}"
    )
    assert change in rows[0], (
        f"the lineage row for edition {edition} no longer states {change!r}.\n  row: {rows[0][:180]}"
    )


def test_the_verdict_is_stated_and_names_the_items_checked():
    """Ruling 3's answer, and the list that makes it more than an assurance.

    "No contradiction" is worth nothing without the checked set beside it: an unnamed sweep that
    found nothing is indistinguishable from a sweep nobody ran. So the verdict and the item table
    are asserted together, and the strongest corroboration in it — settlement 8's four items against
    Edition 1.30's four — is asserted by name.
    """
    lineage = _flat(_lineage())
    assert "No change record contradicts any mapping, any settlement or any refusal" in lineage, (
        "Ruling 3's verdict is gone. It is the sentence the whole round exists to be able to write"
    )
    for item in ("`I048/020`", "`I048/030`", "`I048/120`", "`I048/140`", "`I048/170`",
                 "`I048/220`", "`I048/260`"):
        assert item in lineage, f"the checked-items table no longer lists {item}"
    assert "1.30's record names exactly those four" in lineage, (
        "the strongest corroboration in the round — settlement 8 says 'the four items Edition 1.30 "
        "relaxed' and the record names exactly I048/220, /230, /240, /250 — is no longer stated"
    )
    # The one place the deletion of §5.1 could have cost something, and did not.
    assert "the deletion cost nothing" in lineage and "§5.2.15" in lineage, (
        "1.31 corrected I048/120's resolution in §5.1 and 1.32 deleted §5.1's table. That the row "
        "set takes the LSB from §5.2.15 instead is the reason the deletion is harmless, and it has "
        "to be stated or the next reader re-runs the scare"
    )


def test_the_three_findings_are_closed_and_ambiguity_13_names_the_note_it_found():
    """The follow-up round's own gate, and it REPLACES an assertion that has been retired.

    RETIRED: `"grown in nearly every edition since 1.17" in section`, and the absence assertion
    beside it that the loose phrasing must stay loose. Both were correct for exactly one round —
    844e336 recorded the phrasing as newly checkable and ruled nothing, so freezing it was the way
    to stop it being edited on the way past. This round rules: the phrasing is TIGHTENED to ten of
    sixteen and the frozen-loose assertion would now guard a sentence that no longer exists. A dead
    assertion pointing at a retired sentence is worse than no assertion, because the next reader
    trusts it.

    What replaces it is stricter, not looser: the exact count must be stated, and the ten editions
    must be listed at exactly ONE site.
    """
    lineage = _flat(_lineage())
    section = _section(CAT048_HEADING)
    flat = _flat(section)

    # 1. Ambiguity 13, closed, and closed with the Note NAMED. "Resolved" without the answer in it
    #    would be the same unfalsifiable claim the entry started as.
    thirteen = [ln for ln in section.splitlines() if ln.startswith("| 13 | **")]
    assert len(thirteen) == 1, "ambiguity 13's row is gone"
    assert "RESOLVED" in thirteen[0] and "is Note 5" in thirteen[0], (
        f"ambiguity 13 must close by naming the Note the diff found.\n  row: {thirteen[0][:200]}"
    )
    assert "is not determinable from the pinned copy" not in thirteen[0], (
        "AN ABSENCE: the unresolved wording is back in ambiguity 13's row while the lineage section "
        "says the diff was run. One of the two is now lying"
    )
    assert "1.31 carries four Notes, 1.32 five, Notes 1–4 identical" in _flat(thirteen[0]), (
        "the evidence is the count on each side of the diff; without it the row asserts a "
        "conclusion a reader cannot re-derive"
    )
    # And the wrong inference is recorded AS wrong rather than quietly replaced.
    assert "inference — Note 3 as the likely insertion — was **wrong**" in _flat(thirteen[0]), (
        "the row no longer says its own earlier inference was wrong. A correction that cannot name "
        "what it corrected is one the next reader repeats — this document's own rule"
    )

    # 2. The phrasing, tightened — and the list at exactly one site.
    assert "grown in nearly every edition since 1.17" not in flat, (
        "AN ABSENCE, and the inversion of a retired assertion: the loose phrasing is back. This "
        "round ruled it tightened to the exact count"
    )
    assert "grew in **ten of the sixteen editions from 1.17 to 1.32**" in flat, (
        "the pin row no longer states the exact count the lineage made available"
    )
    enumerations = flat.count("1.17, 1.18, 1.19, 1.24, 1.25, 1.26, 1.27, 1.28, 1.31, 1.32")
    assert enumerations == 1, (
        f"the ten editions are enumerated {enumerations} times in this section, expected exactly 1. "
        "A second enumeration is a second site to drift, which is why the pin row points at the "
        "lineage table instead of repeating it"
    )
    # The COUNT, unlike the list, is legitimately stated twice — the pin row and the closure — so it
    # gets the treatment a twice-stated count gets: both statements compared, not just one checked.
    # Case-folded: one of the two sites opens a sentence with the count, so "Ten" and "ten" are the
    # same statement and only a difference in the NUMBER is drift.
    stated = {(a.lower(), b.lower())
              for a, b in re.findall(r"(\w+) of the (\w+) editions from 1\.17 to 1\.32", flat)}
    assert stated == {("ten", "sixteen")}, (
        f"the I048/030 growth count is stated as {sorted(stated)}. It appears at two sites and they "
        "have to agree — the half-edit shape `test_cdm_prose_counts.py` exists for, one document down"
    )
    assert len(re.findall(r"of the sixteen editions from 1\.17 to 1\.32", flat)) == 2, (
        "the count is stated at two sites by design — the pin row warns a reader off earlier "
        "editions and the closure records the ruling. If one went, say which and why"
    )

    # 3. Ed 1.27's date, ruled, with the witness the ruling turned up.
    assert "Edition 1.27's own change record dates itself" in lineage, (
        "the finding that reframed entry 16 — 1.27 disagreeing with ITSELF — is the whole reason "
        "the ruling is not 'two later documents are wrong'"
    )
    assert "all three now closed" in lineage, (
        "the lineage section still presents the three as open work"
    )
    assert "for a **follow-up** ruling rather than this one" not in lineage, (
        "AN ABSENCE: the follow-up framing survived the round that did the follow-up"
    )


@pytest.mark.parametrize("number,phrase", [
    (15, "omits two of them"),
    (16, "disagrees with ITSELF about its own date"),
    (17, "the one edition of the lineage not obtained"),
    (18, "states no edition at all"),
])
def test_the_lineage_register_entries_are_filed_at_the_next_numbers(number, phrase):
    """Four findings, numbered 15 to 18 per this section's own convention, prose left alone."""
    section = _section(CAT048_HEADING)
    rows = [ln for ln in section.splitlines() if ln.startswith(f"| {number} | **")]
    assert len(rows) == 1, f"register entry {number} is missing or duplicated"
    assert phrase in rows[0], (
        f"register entry {number} no longer states {phrase!r}.\n  row: {rows[0][:180]}"
    )


def test_the_register_did_not_grow_past_eighteen_without_this_test_moving():
    """The upper guard. These numbers are cited from the lineage table, so a gap dangles a citation."""
    section = _section(CAT048_HEADING)
    assert "| 19 | **" not in section, (
        "the CAT048 register has grown past 18 without this test being updated"
    )
    for n in range(1, 19):
        assert f"| {n} | **" in section, f"register entry {n} vanished"


def test_the_pin_corroboration_records_the_grade_it_upgraded():
    """Ruling 1: the same artefact obtained twice, and an evidence grade that moved because of it.

    The pin recorded its member-filename claim as GRADE 2 of 3 *because* the archive had not been
    opened. It has now been opened and the member's bytes are the pinned bytes, so the grade moves.
    A corroboration that did not say which claim it strengthened would be a note nobody could act
    on — grades of evidence are not interchangeable, which is `sac_pin.json`'s own principle.
    """
    flat = _flat(_section(CAT048_HEADING))
    assert "byte-identical" in flat, "the Ruling 1 verdict is gone"
    assert "GRADE 2 of 3 to **GRADE 3**" in flat, (
        "the corroboration no longer names the grade it upgraded, so the pin record and the "
        "document disagree about how strong the member-filename claim is"
    )
    pin = json.loads(
        (pathlib.Path(synapse_cdm.__file__).resolve().parent
         / "fixtures" / "cat048" / "spec" / "cat048_pin.json").read_text())
    strength = pin["source"]["how_strong_the_member_filename_claim_is"]
    assert strength.startswith("GRADE 3 of 3"), (
        f"cat048_pin.json still grades the claim as: {strength[:60]}"
    )
    assert pin["source"]["independent_corroboration_2026_08_24"]["verdict"].startswith(
        "BYTE-IDENTICAL"), "the pin record's corroboration verdict changed"


def test_the_added_note_is_quoted_verbatim_and_the_diff_evidence_is_recorded():
    """The §5.2.12 diff, at the document and at the pin record, with the Note itself.

    A resolution that says "it was Note 5" and does not carry Note 5 is a conclusion with no
    evidence under it — the exact shape the ambiguity had before this round, one level up. So the
    Note is asserted verbatim, and the pin record's copy is asserted to be the same text: two sites,
    one quotation, and the disjunction protocol says check both.
    """
    note5 = ("For radar systems interrogating with various technologies (such as military radars "
             "interrogating in Mode S and Mode 5), element I048/REF/GEN48/ALTFL provides the "
             "possibility to transmit an alternative Flight Level value. If this Data Item carries a "
             "Flight Level value that has been derived from a Mode 5 Reply/Report, then bit-2 in "
             "I048/REF/MD5/SF#1 or bit-2 in I048/REF/M5N/SF#1 shall be set to 1.")
    raw = _section(CAT048_HEADING)
    # The Notes are quoted in a Markdown blockquote, so the `>` continuation markers come out
    # before whitespace is collapsed — the same repair the MISP requirement quotations needed.
    quoted = _flat(re.sub(r"\n>\s*", " ", raw))
    section = _flat(raw)
    assert note5 in quoted, (
        "Note 5 is no longer quoted verbatim in the CAT048 section. It is the answer to ambiguity 13 "
        "and the evidence for it at once"
    )
    pin = json.loads(
        (pathlib.Path(synapse_cdm.__file__).resolve().parent
         / "fixtures" / "cat048" / "spec" / "cat048_pin.json").read_text())
    closure = pin["edition_history"]["closures_2026_08_24"]["finding_1_ambiguity_13"]
    assert closure["verdict"].startswith("RESOLVED"), closure["verdict"]
    assert closure["ed_1_31_notes"] == 4 and closure["ed_1_32_notes"] == 5, (
        "the pin record's note counts are the diff itself; without them the verdict is an assertion"
    )
    assert note5 in " ".join(closure["the_added_note_verbatim_from_ed_1_32"].split()), (
        "the pin record's copy of Note 5 is not the same text as the document's"
    )
    assert "was false" in closure["the_earlier_inference_was_wrong"], (
        "the pin record no longer records that the Note 3 inference was wrong"
    )
    # The clarification is a SECOND change, and conflating the two is the easy mistake.
    assert "in two's complement form" in section
    assert "two changes, not one described twice" in section, (
        "the record's §5.2.12 entry names a clarification AND a Note. That they are two distinct "
        "changes is what the diff established, and it is what stops the next reader concluding the "
        "'clarification' and the 'Note' were the same edit"
    )


def test_the_RE_park_cost_is_recorded_where_the_park_lives():
    """Note 5's only real consequence, filed where somebody deciding about the RE will read it.

    The mapping did not move, so the temptation is to record the closure and stop. But Note 5 says
    the Reserved Expansion Field can carry an ALTERNATIVE Flight Level and a provenance bit for
    I048/090's value — so the park hides a second altitude and the first one's source. That is a
    strictly worse park than settlement 1 described, and a cost discovered and not written down is a
    cost the reopen decision will be made without.
    """
    section = _flat(_section(CAT048_HEADING))
    assert "alternative\n**Flight Level**" in _section(CAT048_HEADING) or \
        "alternative Flight Level" in section, (
        "settlement 5 no longer records that the RE can carry an alternative Flight Level"
    )
    assert "an undercount by one whenever an RE is present" in section, (
        "the sharpened cost — settlement 5's 'three quantities against three datums' is short by one "
        "when an RE is present — is the actionable half of the closure"
    )
    pin = json.loads(
        (pathlib.Path(synapse_cdm.__file__).resolve().parent
         / "fixtures" / "cat048" / "spec" / "cat048_pin.json").read_text())
    cost = pin["edition_history"]["closures_2026_08_24"]["finding_1_ambiguity_13"][
        "consequence_for_the_RE_park"]
    assert "undercount by one" in cost, "the pin record no longer carries the sharpened park cost"


def test_edition_1_27_is_ruled_18_06_2020_with_the_self_disagreement_named():
    """Finding 3's ruling, and the witness that made it a different finding than it looked.

    The proposed default was "the document outranks later documents". The check found that Edition
    1.27's OWN change record says May 2020 — so the rule had to go one level finer, to identification
    pages over change record, and the finding became "1.27 disagrees with itself". Both halves are
    asserted: the ruled date, and the reason the change record cannot be the authority.
    """
    section = _section(CAT048_HEADING)
    flat = _flat(section)
    sixteen = [ln for ln in section.splitlines() if ln.startswith("| 16 | **")]
    assert len(sixteen) == 1, "register entry 16 is gone"
    row = _flat(sixteen[0])
    assert "the edition date **is 18/06/2020**" in row, (
        f"entry 16 no longer states the ruled date.\n  row: {row[:200]}"
    )
    assert "disagrees with ITSELF" in row, (
        "entry 16 still reads as 'later documents are wrong', which is what the check disproved"
    )
    assert "month-granularity throughout" in row, (
        "the reason the change record cannot be the authority — its DATE column cannot express a "
        "day at all — is what turns a two-witness disagreement into a ruling"
    )
    assert "1.28, 1.29, 1.30, 1.31 and 1.32 all repeat that value" in row, (
        "the propagation is the part that matters to a reader of the PINNED edition's own record"
    )
    # And the lineage row agrees with the register, which is the every-site half.
    lineage_rows = [ln for ln in section.splitlines() if ln.startswith("| 1.27 |")]
    assert len(lineage_rows) == 1
    # THE DATE CELL, not the row. MUTATION FOUND THIS: changing the cell from 18/06/2020 to
    # "May 2020" left the suite green, because the row's NOTES cell also contains 18/06/2020 while
    # explaining the discrepancy — a disjunction inside one line, which is the same shape as the
    # pin-row page count and the delegation suffix. The cell is the claim; the note is the reason.
    cells = [c.strip() for c in lineage_rows[0].strip("|").split("|")]
    assert cells[1] == "18/06/2020", (
        f"the lineage table's 1.27 DATE CELL reads {cells[1]!r} and register entry 16 rules for "
        "18/06/2020. The notes cell mentions the date too, so only the cell itself is the claim"
    )
    assert "register entry 16, which rules for" in _flat(lineage_rows[0]), (
        "the lineage row must point at the ruling rather than restating it"
    )


def test_no_site_still_frames_the_three_findings_as_open():
    """AN ABSENCE, swept by finding number and by register number rather than by topic.

    The close-out protocol is explicit that a reference to a closed finding is worse than no
    reference: it sends the next reader looking for work that is done. So the phrases that framed
    them as open are banned outright, across the document and the tests' own prose.
    """
    doc = DOC.read_text()
    banned = (
        "Ambiguity 13 is now resolvable and is not resolved here",
        "for a **follow-up** ruling rather than this one",
        "nothing here picks a side",
        "Left exactly as written; the number is available when",
        "is not determinable from the pinned copy",
        "establishing it needs Edition 1.31",
        # NOT banned: "which nothing here pins" on its own. It appears legitimately elsewhere in
        # this section, about DO-181F, and banning a phrase that has an innocent home is how a
        # sweep acquires an exemption list longer than itself. The 1.31-specific form above is the
        # one that framed ambiguity 13 as open.
    )
    for phrase in banned:
        assert phrase not in doc, (
            f"{phrase!r} still appears in FORMAT_COVERAGE.md. All three findings closed in this "
            "round, so a sentence framing one as open points a reader at finished work"
        )


# ------------------------------------- the STANAG 5527 (Friendly Force Tracking) covering document
#
# Adapter #9's section is a Phase 1 with NO ROW SET, which is a different thing from the four
# specifications-before-code that came before it and from the KLV row set above. STANAG 4609
# promulgates a profile and the profile was in hand, so that phase could write 37 rows saying
# `not yet` and plan twelve fixtures. STANAG 5527 promulgates ADatP-36 Edition B and ADatP-36
# Edition B is NOT in hand, so this phase writes no mapping row at all.
#
# That inverts what these tests have to do. Everywhere else the risk is a mapping row drifting away
# from the document; here the risk is a mapping row EXISTING. Five pages of ratification prose are
# the most inviting possible surface for filling a table in from memory of the format, and nothing
# in the pinned copy could contradict an invention. So the assertions below are weighted towards
# absences that a from-memory edit would have to break:
#
#   * the section contains no `not yet` row and no terminal status marker, asserted as ZERO rather
#     than as a floor — the exact opposite of `test_the_klv_row_set_exists_and_every_row_of_it_
#     says_not_yet`, and for the same underlying reason: the count is the claim;
#   * the one delegation row names ADatP-36 Edition B and says it is unsuffixed at the requirement,
#     SCOPED TO THE ROW, because "Edition B" also occurs in the prose around it and an unscoped
#     `in` check would be a disjunction over the section — the mutation lesson from the KLV
#     delegation table, applied on the first day here;
#   * STANAG 7149 and STANAG 2019 are recorded as related and NOT as delegations, asserted in BOTH
#     directions, because the failure is silent: filing a related document as a delegation
#     overstates what the nations agreed to implement and reads as correct at every site;
#   * the fixture directory ruling says PROVISIONAL at every site that states it, and the reopen
#     conditions are named. A provisional ruling that loses the word is a settled ruling nobody
#     decided to settle;
#   * one park, named at every site, and no site names a second.

FFT_HEADING = "## STANAG 5527"
FFT_FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "fft"
FFT_PIN = FFT_FIXTURES / "spec" / "fft_pin.json"
FFT_README = FFT_FIXTURES / "README.md"

#: The one pinned document: filename, SHA-256, byte count, page count.
FFT_PINNED_DOCUMENT = ("nato-stanag-5527-edition-2.pdf",
                       "2dba2026cab49c2c3c6f576244edc1be1abfe2df9c545a46ae341cc2a2d30b83",
                       319795, 5)


#: The classification claim, and the hedge that makes an occurrence of it legitimate. Every site
#: has to be able to SAY what it is not asserting, so the ban is windowed rather than flat — the
#: same shape `tests/test_cdm_changelog_claim.py` and `tests/test_cdm_ordinals.py` both arrived at,
#: and for the same reason: a flat ban would have an exemption list longer than itself.
_CLASSIFICATION_CLAIM = re.compile(
    r"Edition B is (?:NATO RESTRICTED|RESTRICTED|classified|unclassified|public)", re.I)
_CLASSIFICATION_HEDGE = re.compile(
    r"nothing (?:in this record |below |here )?asserts|does not assert|or that it is not|"
    r"is not established|not in hand|if Edition B", re.I)


def _fft_sites() -> dict[str, str]:
    """The three files that state the ruling in full, so a fact can be checked at every one."""
    return {
        "FORMAT_COVERAGE.md": _section(FFT_HEADING),
        "fixtures/fft/spec/fft_pin.json": FFT_PIN.read_text(),
        "fixtures/fft/README.md": FFT_README.read_text(),
    }


def test_the_stanag5527_section_has_no_row_set_and_says_why():
    """Phase 1's whole claim here, and it is an ABSENCE asserted as zero rather than as a floor.

    The KLV test one block up asserts `>= 30` rows saying `not yet`, because that phase specified a
    mapping it could not implement. This one asserts **none**, because this phase specified nothing:
    `not yet` says a mapping exists and is unimplemented, and there is no document in hand from
    which a mapping could be written. A row appearing here is not a status-column error — it is a
    field invented out of five pages of ratification prose, which is the single most likely way this
    section could go wrong.
    """
    section = _section(FFT_HEADING)
    rows = [ln for ln in section.splitlines() if ln.startswith("|")]
    assert rows, "the STANAG 5527 section has no tables at all, so this check is vacuous"
    mapping_rows = [ln for ln in rows if "`not yet`" in ln]
    assert mapping_rows == [], (
        f"the STANAG 5527 section has {len(mapping_rows)} `not yet` rows: {mapping_rows[:2]}. "
        "This phase holds no document from which a mapping row could be written — the AGREEMENT "
        "clause names ADatP-36 Edition B and it is not in hand — so a row here is an invention"
    )
    for marker in ("`stanag5527 1.0.0`", "`fft 1.0.0`"):
        assert marker not in DOC.read_text(), (
            f"{marker} appears in FORMAT_COVERAGE.md. There is no adapter, so a terminal status "
            "marker anywhere in the document is a claim nothing implements"
        )
    # And the absence is STATED, not just true. An empty section and a section that explains its
    # emptiness look identical to a grep and completely different to a reader.
    flat = _flat(section)
    assert "Nothing below is a mapping row, and that absence is the section." in flat, (
        "the section no longer opens by saying it has no row set. The next editor's first instinct "
        "on meeting a heading with no table is to add one"
    )


def test_the_stanag5527_pin_agrees_at_every_site_that_states_it():
    """One document, four sites, and the pin row asserted as ONE composite string at each.

    The KLV block's mutation finding, applied here on the first day rather than after: checking
    hash, byte count and page count as three independent substrings makes each a disjunction over
    the whole file, and a wrong page count passes because the right number still occurs elsewhere.
    So the prose sites are checked as one string and the JSON is read as data.
    """
    filename, digest, size, pages = FFT_PINNED_DOCUMENT
    spaced = _spaced(size)

    # 1. The JSON, read as data. No substrings.
    pin = json.loads(FFT_PIN.read_text())
    assert pin["sha256"] == digest, f"fft_pin.json sha256 is {pin['sha256']}"
    assert pin["bytes"] == size, f"fft_pin.json bytes is {pin['bytes']}"
    assert pin["pages"] == pages, f"fft_pin.json pages is {pin['pages']}"
    assert pin["local_path"] == f"fixtures/fft/spec/{filename}", pin["local_path"]

    # 2. FORMAT_COVERAGE.md's pin row, as one composite string.
    row = f"`{digest}`, {spaced} bytes, {pages} pages, `fixtures/fft/spec/{filename}`"
    assert row in _section(FFT_HEADING), (
        f"FORMAT_COVERAGE.md's pin row for {filename} is not\n  {row}"
    )

    # 3. The fixture README's table row, likewise.
    readme_row = f"| `spec/{filename}` | `{digest}` | {spaced} | {pages} |"
    assert readme_row in FFT_README.read_text(), (
        f"fixtures/fft/README.md's table row is not\n  {readme_row}"
    )

    # 4. MIGRATIONS.md, in this document's own ellipsised form, also as one string.
    migrations_fact = f"(`{_abbreviated(digest)}`, {spaced} bytes, {pages} pages)"
    assert migrations_fact in MIGRATIONS.read_text(), (
        f"MIGRATIONS.md's Phase 1 entry no longer states the pin as\n  {migrations_fact}"
    )

    # 5. And the file itself, when this working tree has it.
    path = FFT_FIXTURES / "spec" / filename
    if path.exists():
        assert path.stat().st_size == size, f"{filename} at the pinned path is the wrong size"
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        assert got == digest, f"{filename} at the pinned path hashes to {got}"
    assert [p for p in _tracked_files() if p.endswith(".pdf")] == [], "PDFs are tracked"


def test_the_delegation_row_names_adatp36_edition_b_and_records_that_it_is_unsuffixed():
    """The one delegation row, SCOPED TO THE ROW rather than to the section.

    "Edition B" occurs in the prose around this table as well — in the preamble, in the pin block
    and in the park — so `"Edition B" in section` would be a disjunction satisfied by any of them
    and would survive the row losing its version cell entirely. That is precisely the mutation the
    KLV delegation table taught, and it is cheaper to apply it now than to find it later.
    """
    section = _section(FFT_HEADING)
    rows = [ln for ln in section.splitlines()
            if ln.startswith("|") and "**ADatP-36**" in ln]
    assert len(rows) == 1, (
        f"expected exactly one delegation row for ADatP-36, found {len(rows)}. The AGREEMENT "
        "clause names exactly one standard, so the table has exactly one row"
    )
    row = _flat(rows[0])
    assert "**Edition B**" in row, "the delegation row no longer states the edition"
    assert "unsuffixed at the requirement" in row, (
        "the delegation row no longer says the requirement cites the document unsuffixed. That "
        "phrase is the convention this repository's delegation rows carry, and dropping it turns "
        "an edition letter read off one clause into a version the requirement appears to state"
    )
    assert "AGREEMENT clause" in row, (
        "the delegation row no longer names WHERE the document is required. A delegation with no "
        "requirement locus is a citation, not a delegation"
    )
    assert "STANDARD clause" in row, (
        "the delegation row no longer names where the VERSION is stated. The two loci are separate "
        "cells' worth of fact for the reason the STANAG 4609 table gives: a reader who takes a "
        "version from the requirement can get no version at all"
    )
    # The document is named as NOT held at every site, because a delegation to a document in hand
    # and a delegation to one that is not are different claims about this phase.
    for label, text in _fft_sites().items():
        assert "not in hand" in text or "NOT held" in text or '"held": false' in text, (
            f"{label} no longer records that ADatP-36 Edition B is not held"
        )


def test_stanag_7149_and_stanag_2019_are_recorded_as_related_and_never_as_delegations():
    """AN ABSENCE with a positive half, and the failure it guards is silent in both directions.

    The pinned document names three other documents: one in the AGREEMENT and two under OTHER
    RELATED DOCUMENTS. Promoting either of the two into the delegation table would overstate what
    the nations agreed to implement, and demoting the one out of it would understate it. Neither
    misreading is detectable without the pinned copy, so both are asserted here.
    """
    section = _section(FFT_HEADING)
    delegation_rows = [ln for ln in section.splitlines()
                       if ln.startswith("|") and "**ADatP-36**" in ln]
    assert len(delegation_rows) == 1
    for other in ("7149", "2019"):
        assert other not in delegation_rows[0], (
            f"STANAG {other} appears in the delegation row. It is under OTHER RELATED DOCUMENTS "
            "and not in the AGREEMENT, and the AGREEMENT clause names exactly one standard"
        )
    flat = _flat(section)
    for other, app in (("STANAG 7149", "APP-11"), ("STANAG 2019", "APP-06")):
        assert f"**{other}**" in flat, f"{other} is no longer recorded at all"
        assert app in flat, f"{other}'s APP number is no longer recorded"
    assert "recorded as *related* rather than as delegations" in flat, (
        "the section no longer states the distinction in as many words. The distinction IS the "
        "finding — a reader who cannot see it will file all three documents the same way"
    )
    # And neither is counted as a park, because nothing here depends on either.
    assert "from one to three" in flat, (
        "the section no longer says that calling the related documents parks would inflate what "
        "this adapter is waiting for. The park count is a fact this round states at three sites"
    )


def test_the_fixture_directory_ruling_says_provisional_at_every_site_and_names_its_reopen():
    """A provisional ruling that loses the word is a settled ruling nobody decided to settle.

    This is the one thing about #9 that no document in hand can settle: the adapter name is ruled
    on the covering document and the DIRECTORY name rests on a single clause of it. The word and
    the overturn conditions are therefore checked at all three sites, in the shape the pin-row
    lesson gives — every occurrence rather than any one.
    """
    for label, text in _fft_sites().items():
        assert "PROVISIONAL" in text, (
            f"{label} no longer marks the fixture-directory ruling PROVISIONAL. The adapter name is "
            "settled and the directory is not, and a site that states only the ruling has lost the "
            "half a later reader needs"
        )
        assert "ADatP-36" in text, (
            f"{label} states the ruling is provisional without naming what would settle it"
        )
    section = _flat(_section(FFT_HEADING))
    assert "Two findings would overturn it" in section, (
        "the section no longer names what would overturn the directory ruling. 'Provisional' with "
        "no overturn condition is a hedge rather than a ruling"
    )
    assert "What is not a reopen condition" in section, (
        "the section no longer says what would NOT reopen the ruling. A provisional ruling attracts "
        "revisiting for the wrong reasons and the exclusions are the guard against that"
    )
    # The adapter name, by contrast, is NOT provisional, and the two must not blur together.
    assert "no content document can unrule it" in section, (
        "the section no longer distinguishes the settled adapter name from the provisional "
        "directory. Both rulings in one undifferentiated block is what this subsection exists to "
        "avoid"
    )
    pin = json.loads(FFT_PIN.read_text())
    ruling = pin["adapter"]["fixture_directory_ruling"]
    assert ruling["ruled"] == "fft" and ruling["status"] == "PROVISIONAL", ruling
    assert len(ruling["provisional"]["what_would_overturn_it"]) == 2, (
        "the pin record no longer states exactly two overturn conditions"
    )
    assert pin["adapter"]["name"] == "stanag5527", pin["adapter"]["name"]


def test_the_covering_documents_absences_are_stated_as_counts_and_nothing_is_invented():
    """AN ABSENCE, and the hole most available in a phase like this one.

    Every other row set here can be checked against a technical document. This one cannot, because
    the technical document is not in hand — so a sentence about how Friendly Force Tracking works
    would be unfalsifiable from inside this repository. The guard is that the section's claims about
    the pinned copy are COUNTS and QUOTATIONS, which a reader can re-run against the PDF, and that
    the shapes an invention would take are banned outright.
    """
    flat = _flat(_section(FFT_HEADING))
    for claim in (
        "`shall` occurs four times in five pages and not one of the four governs a data element",
        "`should` occurs three times",
        "No requirement is numbered, because there are no requirements to number",
        "The term NFFI does not occur",
    ):
        assert claim in flat, (
            f"the counted-absence {claim!r} is no longer stated. These counts are what make the "
            "'this document contains nothing technical' claim checkable against the pinned copy "
            "rather than an impression of it"
        )
    # The shapes an invention would take. Each is a thing ADatP-36 Edition B would decide and the
    # covering document does not, so any of them appearing here is a claim with no source.
    # Each pattern is the SHAPE an assertion would take, not a topic word: this section legitimately
    # says it does NOT state what NFFI stands for, so banning that phrase would ban the disclaimer
    # along with the claim.
    for invented in ("local set", "message set is", "the field dictionary defines",
                     "NFFI is ", "NFFI (N", "the wire format is", "XML schema"):
        assert invented.lower() not in flat.lower(), (
            f"{invented!r} appears in the STANAG 5527 section. Nothing about the structure, "
            "encoding or message set of Friendly Force Tracking is establishable from the pinned "
            "copy — it is all in ADatP-36 Edition B, which is park 1"
        )


def test_the_single_park_is_stated_once_and_agrees_at_every_site():
    """One park, three sites, and the count is the claim.

    The KLV phase has thirteen parks over fifteen documents and needed a table. This one has one,
    and the risk runs the other way: a second park drifting in — the two related documents are the
    obvious candidates — would change what #9 is waiting for from a single access decision into a
    programme. So the count is asserted, and so is the identity of the one.
    """
    for label, text in _fft_sites().items():
        assert "ADatP-36, Edition B" in text or "ADatP-36 Edition B" in text, (
            f"{label} no longer names the park's document"
        )
    flat = _flat(_section(FFT_HEADING))
    assert "One park over one document" in flat, (
        "the section no longer states that there is exactly one park. The count is what stops the "
        "two related documents drifting in as parks 2 and 3"
    )
    assert "**ADatP-36, Edition B. Park 1**, and the only park this phase has" in flat, (
        "the pin block no longer names park 1 as the only one"
    )
    assert "Park 2" not in flat and "park 2" not in flat, (
        "a second park has appeared without the count above it moving"
    )
    pin = json.loads(FFT_PIN.read_text())
    parks = pin["parks"]
    assert set(parks) == {"how_many", "park_1"}, (
        f"fft_pin.json's park set is {sorted(parks)}; exactly one park is recorded and the count "
        "sits beside it"
    )
    assert parks["park_1"]["document"] == "ADatP-36, Edition B", parks["park_1"]["document"]
    assert "not 'the current ADatP-36'" in parks["park_1"]["reopen_condition"], (
        "the reopen condition no longer excludes 'the current ADatP-36'. Obtaining a later "
        "revision and reading it against this citation is the failure that condition exists for"
    )


def test_the_classification_contingency_is_stated_in_the_SAME_two_branch_form_at_every_site():
    """THE DISJUNCTION SWEEP for #9's park, applied to a fact that does not exist yet.

    The park was single-branched until this round: obtain the document, land the pin. That collapses
    two acts into one, and it is only safe if the document may be carried. Whether ADatP-36 Edition
    B may be carried is **not established** — a third-party index shows two records and one
    RESTRICTED marking between them, which is not a NATO source — so the park now states two
    branches and every site that states the park must state both.

    The failure this guards is the ordinary one for a fact recorded four times: a later editor
    tidies one site back to the single-branch form, and the repository then says two different
    things about what happens when the document arrives. It is worse than the usual case, because
    the site that keeps the simpler sentence is the one a hurried reader believes.

    Both directions are checked. No site may lose a branch, and **no site may assert the fact that
    decides it** — this round does not know Edition B's classification and a site that states one
    has invented it.
    """
    sites = dict(_fft_sites())
    migrations = MIGRATIONS.read_text()
    entry = migrations[migrations.index("- **`stanag5527` — STANAG 5527"):]
    entry = entry[:entry.index("\n## ", 10)]
    sites["MIGRATIONS.md (the stanag5527 entry)"] = entry

    # THE SITE LIST IS DERIVED AGAINST THE TREE, not trusted. A disjunction sweep whose own list of
    # sites can shrink is not a sweep — drop one entry and it reports clean over three of four,
    # which is the eight-versus-nine pin drift in a different costume. So the closure is asserted
    # the way `tests/test_cdm_pins.py` asserts the pin set: every file in the repository that names
    # a branch must be one this test actually reads. Found by mutation; the list had been a literal.
    # `is_virtualenv` is IMPORTED rather than reimplemented, and this sweep is the LAST of the four
    # to adopt it. It carried a literal directory list that never contained `.venv` at all, so it
    # was clean only while nobody had installed this package into an environment inside the clone —
    # and the consumer-path round did exactly that, at which point the sweep found FOUR extra
    # "sites" that were site-packages copies of the four it already reads. A sweep whose site list
    # can be inflated by an interpreter is not a sweep over this repository. PEP 405's `pyvenv.cfg`
    # is the property, for the reason `tests/test_cdm_version_floor.py` records at length.
    from tests.test_cdm_version_floor import NOT_OURS, is_virtualenv

    repo = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]
    naming = set()
    for dirpath, dirnames, filenames in os.walk(repo):
        here = pathlib.Path(dirpath)
        if is_virtualenv(here):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in NOT_OURS)
        for name in sorted(filenames):
            path = here / name
            if path.suffix not in {".md", ".mdx", ".py", ".json"} or not path.is_file():
                continue
            if path.name == pathlib.Path(__file__).name:
                continue                   # this module states the branches to check for them
            if "Branch R" in path.read_text(errors="ignore"):
                naming.add(str(path.relative_to(repo)))
    swept = {"packages/cdm/synapse_cdm/FORMAT_COVERAGE.md",
             "packages/cdm/synapse_cdm/fixtures/fft/spec/fft_pin.json",
             "packages/cdm/synapse_cdm/fixtures/fft/README.md",
             "packages/cdm/synapse_cdm/MIGRATIONS.md"}
    assert len(sites) == len(swept), (
        f"the sweep assembled {len(sites)} sites and names {len(swept)}: {sorted(sites)}. The two "
        "have to move together — a site removed from `sites` and left in `swept` is a site nobody "
        "checks"
    )
    assert naming == swept, (
        f"the set of files naming a branch is not the set this sweep reads.\n"
        f"  naming a branch but NOT swept: {sorted(naming - swept)}\n"
        f"  swept but no longer naming one: {sorted(swept - naming)}\n"
        "A new site stating the contingency has to be added to `_fft_sites()` (or to `sites` here) "
        "and to `swept`; a site that has stopped stating it has to be removed from both. Either "
        "direction left unrepaired is a fact stated somewhere this test does not look"
    )

    for label, text in sites.items():
        flat = _flat(text)
        low_flat = flat.lower()
        for token in ("Branch U", "Branch R"):
            assert token in flat, (
                f"{label} no longer states {token}. The park closes down one of two branches and a "
                "site that names one of them reads as a settled plan"
            )
        # WINDOWED, not a plain `in`. Every one of these sites names cite-not-carry more than
        # once — the branch, then the precedent paragraph that contrasts it with AEDP-12 — so
        # `"cite-not-carry" in text` is a disjunction that survives Branch R losing its treatment
        # entirely. The mutation that found this took the phrase off the branch and left it in the
        # precedent sentence, and the check passed.
        attached = [m for m in re.finditer(r"branch r", low_flat)
                    if "cite-not-carry" in low_flat[m.start():m.end() + 400]]
        assert attached, (
            f"{label} names Branch R and does not name cite-not-carry as its treatment within 400 "
            "characters of it. That phrase is the whole content of the branch — identity recorded, "
            "bytes never in this repository — and a Branch R without it is a branch with no rule"
        )
        assert "nsdd classification line" in low_flat, (
            f"{label} no longer names the deciding fact. Without it the two branches read as a "
            "preference between two ways of recording a document rather than as a contingency on "
            "something nobody here has read"
        )
        assert "not established" in low_flat, (
            f"{label} no longer records that WHICH EDITION the marking attaches to is unestablished."
            " That sentence is what keeps the contingency a contingency"
        )
        # And the fact itself is still not in hand, at any site. A flat ban on the words would ban
        # the DISCLAIMER along with the claim — every one of these sites has to say "nothing here
        # asserts that Edition B is classified or that it is not", and that sentence contains the
        # banned string. That is the lesson the invention check below already records about the
        # retired reserved name, and the repair is the same windowed form: the phrase is allowed,
        # an UNHEDGED occurrence of it is not.
        for m in _CLASSIFICATION_CLAIM.finditer(flat):
            window = flat[max(0, m.start() - 200):m.end() + 80]
            assert _CLASSIFICATION_HEDGE.search(window), (
                f"{label} states {m.group(0)!r} with nothing around it that withholds the claim: "
                f"…{window}… . The NSDD classification line has not been read, so a site that "
                "states the answer has invented the fact this whole contingency exists to wait for"
            )
        # These take no disclaimer form at all, so they are banned outright.
        for invented in ("Branch R is taken", "Branch U is taken", "the branch is decided",
                         "Branch R applies", "Branch U applies"):
            assert invented.lower() not in flat.lower(), (
                f"{label} asserts {invented!r}. Neither branch has been taken and this round "
                "cannot take one"
            )

    # The precedent is CITED rather than paraphrased, and it is located: a branch that says "like
    # the AEDP-12 case" without saying where that case is written is a pointer to somebody's memory.
    flat_doc = _flat(_section(FFT_HEADING))
    assert "3e0aed0" in flat_doc, (
        "the Branch R text no longer cites the commit that recorded the AEDP-12 Edition A "
        "treatment. That precedent is the reason Branch R is a known shape rather than an invention"
    )
    assert "SHA-256 (2014)" in flat_doc, (
        "the Branch R text no longer names the row the precedent lives in. 'The AEDP-12 treatment' "
        "is not locatable by grep; the row label is"
    )
    assert "Not present in `fixtures/nits/spec/`" in _section("## STANAG 4676 / AEDP-12"), (
        "the AEDP-12 Edition A row no longer says its copy is outside the tree, so the Branch R "
        "text now cites a precedent this document does not contain"
    )

    # And the two facts the visit must return, which are the park's exit condition now. WINDOWED
    # for the same reason as the branch treatment above, and found by the same kind of mutation:
    # "which version of Edition B" occurs elsewhere in every one of these sites — it is the point
    # the delegation row and the reopen condition both already make — so a bare `in` check passes
    # with the fact struck out of the visit's list. Both facts must sit with the visit that has to
    # return them.
    for label, text in sites.items():
        low_flat = _flat(text).lower()
        windows = [low_flat[m.start():m.end() + 900]
                   for m in re.finditer(r"nsdd[ _]visit", low_flat)]
        assert windows, (
            f"{label} no longer names the NSDD visit at all. It is the act that closes this park "
            "and the only thing that can return either fact"
        )
        for fact in ("classification line", "which version of edition b"):
            assert any(fact in w for w in windows), (
                f"{label} names the NSDD visit and does not require {fact!r} of it. The visit has "
                "to return TWO facts — the classification line decides the branch, the version "
                "identifies the text — and a visit that returns the document and neither leaves "
                "the park where it is"
            )
    assert "it is two facts" in flat_doc, (
        "FORMAT_COVERAGE.md no longer states that the NSDD visit must return TWO facts. One of "
        "them — the classification line — is new this round, and a visit that returns the document "
        "and neither fact leaves the park where it is"
    )


def test_the_changelog_page_states_none_of_the_number_nine_park():
    """AN ABSENCE, and it is the one site the sweep must find EMPTY rather than agreeing.

    `f99a4b0` ruled that `docs/docs/changelog.mdx` is a curated summary of `MIGRATIONS.md` for a
    reader of the published contract, and that "no adapter code, no fixtures, one park, ADatP-36
    Edition B not in hand" is repository-internal process rather than schema history. A two-branch
    contingency over a document nobody has read is that same genre, only more so.

    So this round's sweep visits the page and requires it to say nothing — which is a finding the
    sweep has to record either way, because "the changelog was not checked" and "the changelog
    correctly says nothing" look identical afterwards.
    """
    repo = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]
    page = (repo / "docs" / "docs" / "changelog.mdx").read_text()
    for token in ("ADatP-36", "5527", "stanag5527", "Branch R", "cite-not-carry", "NSDD"):
        assert token not in page, (
            f"docs/docs/changelog.mdx now mentions {token!r}. That page carries schema history for "
            "a reader of the published contract; #9 has no schema to report, and its park is "
            "repository process — see the f99a4b0 ruling in tests/test_cdm_changelog_claim.py"
        )


def test_the_two_ruled_names_agree_at_every_site_that_states_them():
    """THE DISJUNCTION TREATMENT, applied to the two names #9's round rules.

    A name stated at four sites and checked at one is a name that can drift at three, and this is
    the exact shape 80b38d1 had to repair: the NITS pin record and the XSD exit condition named two
    different directories for one adapter, four hundred lines apart, and the test that should have
    caught it was satisfied by whichever one it happened to read.

    So both names are COLLECTED here rather than asserted at a chosen site — the harness map, the
    pin record, the fixture README and FORMAT_COVERAGE.md's ordinal table — and required to agree.
    The harness map is not the authority for either: the ordinal table decides the adapter name and
    the pin record carries the ruling. It is included because it is the site a mistyped `cp` would
    contradict, which is the failure the map was pinned to prevent.
    """
    import importlib
    harness_tests = importlib.import_module("tests.test_cdm_harness")

    pin = json.loads(FFT_PIN.read_text())
    readme = FFT_README.read_text()
    ordinal_table = _section("### The adapter ordinals")

    adapter_name = {
        "fft_pin.json": pin["adapter"]["name"],
        "test_cdm_harness.py PLANNED_FIXTURE_DIRS":
            next(n for n in harness_tests.PLANNED_FIXTURE_DIRS if n.startswith("stanag5")),
        "FORMAT_COVERAGE.md ordinal table":
            re.search(r"\|\s*9\s*\|\s*`([a-z0-9]+)`", ordinal_table).group(1),
    }
    assert len(set(adapter_name.values())) == 1, (
        f"the adapter name disagrees across sites: {adapter_name}"
    )
    name = next(iter(adapter_name.values()))
    assert name == "stanag5527", name
    assert f"`{name}` is adapter #9" in readme, (
        f"fixtures/fft/README.md no longer states the ordinal in the claim form. That form is what "
        f"tests/test_cdm_ordinals.py binds, so without it this site states {name!r} and no number"
    )

    directory = {
        "fft_pin.json (adapter.fixture_directory)": pin["adapter"]["fixture_directory"],
        "fft_pin.json (the ruling)": pin["adapter"]["fixture_directory_ruling"]["ruled"],
        "test_cdm_harness.py PLANNED_FIXTURE_DIRS": harness_tests.PLANNED_FIXTURE_DIRS[name],
        "the pinned path": pin["local_path"].split("/")[1],
    }
    assert len(set(directory.values())) == 1, (
        f"the fixture directory disagrees across sites: {directory}. This is 80b38d1's failure "
        "exactly — one adapter, two directory names, and each site individually plausible"
    )
    fixture_dir = next(iter(directory.values()))
    assert fixture_dir == "fft", fixture_dir
    assert (FFT_FIXTURES.parent / fixture_dir).is_dir(), (
        f"every site agrees the directory is {fixture_dir!r} and it does not exist"
    )
    # And the two names must still DIFFER, which is the thing the ruling is about. A round that
    # quietly collapsed them into one would satisfy every agreement check above.
    assert name != fixture_dir, (
        "the adapter name and the fixture directory have become the same string. They differ on "
        "purpose — a directory holds payloads and a payload is not a standard — and collapsing "
        "them is the bug 80b38d1 had to repair, not a simplification"
    )


# ---------------------------------------- the ASTERIX Category 034 (Monoradar Service Messages) row set
#
# Adapter #12's section is a Phase 1 with a FULL row set, which puts it between the two above it and
# changes what these tests have to guard. STANAG 5527 pins a covering document that states nothing
# technical, so its risk is a mapping row EXISTING and its tests assert zero. STANAG 4609 pins a
# profile that delegates every field dictionary, so its risk is a row quoting a document nobody
# read. Here the document is present and complete — twelve data items with Definitions, Formats,
# Structures and Encoding Rules, and a fourteen-FRN UAP — so the row set is written FROM it, and
# the risks are different again:
#
#   * a row FLIPPING OFF `not yet` before code exists. Asserted as an equality over the whole
#     section rather than as a floor, because a Phase 1's claim is that NOTHING is implemented and
#     a floor cannot say that;
#   * the PIN being read as current. This is the first pin in this repository that is knowingly
#     SUPERSEDED — CAT048's own §2.2 names Edition 1.30 — so every site that states the pin must
#     also state that, and a site that quietly drops it is a site claiming Edition 1.29 is what a
#     conformant encoder emits;
#   * the two ruled NAMES collapsing into one by accident rather than by ruling. #9's test asserts
#     that its two names DIFFER; the naive generalisation of that rule to the whole roster is FALSE
#     here, so the coincidence is asserted POSITIVELY and with the reasoning required to be present;
#   * the PAGE COUNT, which needed a method change. The number 41 is not what the method the earlier
#     pins recorded produces, so the disagreement, the validation and the folio cross-check are all
#     required to be stated — a corrected number with no record of the correction is indistinguishable
#     from a typo that happened to be right.

CAT034_HEADING = "## ASTERIX Category 034"
CAT034_FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "cat034"
CAT034_PIN = CAT034_FIXTURES / "spec" / "cat034_pin.json"
CAT034_README = CAT034_FIXTURES / "README.md"

#: The pinned document: filename, SHA-256, byte count, page count.
CAT034_PINNED_DOCUMENT = ("eurocontrol-asterix-cat034-pt2b-ed129.pdf",
                          "32925e6a04d124cf1f699adb68371bd88806d8cc4ae957df8aacba18cfcae101",
                          639615, 41)

#: The three lineage PDFs: filename, edition, SHA-256, byte count, page count. NOT pins — the
#: not-a-pin property is `tests/test_cdm_pins.py`'s; what is checked here is that the RECORD of
#: them matches the disk, which is the direction that goes stale silently.
CAT034_HISTORY = (
    ("eurocontrol-asterix-cat034-pt2b-ed128.pdf", "1.28",
     "86c13575e95863dcc96b672e47ac8228ccf81f7962428d1a8e8c92752aa91a49", 635545, 43),
    ("cat034p2bed127.pdf", "1.27",
     "57585afaef37ce1afa19980a6fe73c90ac0ea7d2fbbe2a24786c0e28f9199264", 265707, 38),
    ("asterix-cat034-monoradar-service-messages-next-version-of-cat-002part-2b-v1.26-112000.pdf",
     "1.26", "c0161f64adb3e2b051845e4f4f6f658f1083a6da8fa53e62bc1376c526cd38f5", 188590, 38),
)


def _cat034_sites() -> dict[str, str]:
    """The three files that state the ruling, so a fact can be checked at every one."""
    return {
        "FORMAT_COVERAGE.md": _section(CAT034_HEADING),
        "fixtures/cat034/spec/cat034_pin.json": CAT034_PIN.read_text(),
        "fixtures/cat034/README.md": CAT034_README.read_text(),
    }


def test_the_cat034_row_set_claims_the_adapter_that_now_implements_it():
    """The status column has to move when the code does, in BOTH directions.

    This test was the opposite of itself through Phase 1. It asserted, as an EQUALITY over the
    whole document, that no row anywhere said `cat034 1.0.0` — because a status marker claiming an
    adapter that does not exist is the one thing the table exists to prevent, and it is exactly
    what the Edition A STANAG 4676 placeholder had been doing for as long as it stood.
    `adapters/asterix_cat034.py` now exists, so the risk is the inverse: a row still saying
    `not yet` is a shipped mapping nobody updated the document for. Inverted rather than deleted,
    so the reversal is readable in the history — the treatment CAT021's, NITS's, GMTIF's and
    CAT048's each got.
    """
    import synapse_cdm.adapters as _adapters
    module = pathlib.Path(_adapters.__file__).resolve().parent / "asterix_cat034.py"
    codec_module = module.with_name("cat034_codec.py")
    assert module.exists() and codec_module.exists(), (
        "adapters/asterix_cat034.py or adapters/cat034_codec.py is gone. If the adapter is being "
        "withdrawn, this test inverts back and every row returns to `not yet` in the same commit"
    )
    section = _section(CAT034_HEADING)
    rows = [ln for ln in section.splitlines() if ln.startswith("|")]
    assert len(rows) >= 60, (
        f"the CAT034 section has {len(rows)} table lines. A twelve-item row set with an egress "
        "table and a nineteen-fixture list contributes far more than that, so the section has "
        "been truncated or the heading no longer matches"
    )
    mapped = [ln for ln in rows if "`cat034 1.0.0" in ln]
    assert len(mapped) >= 40, (
        f"only {len(mapped)} rows carry a `cat034 1.0.0` marker. Twelve data items, a block "
        "envelope, an egress table and the filled-in fields contribute far more; raising this "
        "floor deliberately is fine, losing rows is not"
    )
    stale = [ln for ln in rows if "`not yet`" in ln]
    assert not stale, (
        f"{len(stale)} CAT034 row(s) still say `not yet` while adapters/asterix_cat034.py "
        f"implements the row set: {[r[:90] for r in stale[:3]]}"
    )
    from synapse_cdm import adapter as adapter_module
    assert "cat034" in set(adapter_module.discover()), (
        "`cat034` is not a registered adapter, so nothing implements these rows. Either the "
        "adapter was withdrawn — in which case the rows return to `not yet` in the same commit — "
        "or the registry is not being reached from here"
    )
    legend = _section("## The status column")
    for marker in ("`cat034 1.0.0`", "`cat034 1.0.0 · parked`", "`cat034 1.0.0 · egress`"):
        assert marker in legend, f"the legend does not define the marker {marker} the rows use"
    assert "adapters/asterix_cat034.py" in section and "adapters/cat034_codec.py" in section, (
        "the row set must name both modules that implement it — the codec is a layer of its own "
        "with its own tests, and a reader looking for the byte handling has to be sent there"
    )
    assert "· provisional" not in _flat(section), (
        "a `· provisional` qualifier has appeared on a CAT034 row. Nothing here is provisional: "
        "every offset is checkable against a table in the pinned document, and check_layouts() "
        "sums them against the standard's own byte counts on every suite run"
    )
    # And the flip is STATED. A section that flipped and a section that says it flipped look
    # identical to a grep and completely different to a reader.
    assert "Not one row below says `not yet` any more, and that is the section." in _flat(section), (
        "the section no longer opens by saying that everything in it is implemented"
    )


def test_the_two_rulings_phase_1_deferred_are_both_ruled_and_both_rest_on_table_2():
    """Phase 1 named two questions as Phase 2's and this is what stops them being forgotten.

    A deferred ruling is the easiest thing in a two-phase protocol to lose: the row set says
    "Phase 2 rules it", Phase 2 ships, and nobody checks that the ruling was actually made. Both
    are asserted here against the SECTION and against the CODE, because a settlement in prose that
    the adapter does not implement is worse than no settlement.
    """
    section = _section(CAT034_HEADING)
    flat = _flat(section)

    # 1. The polar window never becomes a Geometry, and Table 2 is why.
    assert "### Settlement 7" in section, "settlement 7 is gone; it is the geometry ruling"
    assert "there is no message type for which both are permitted" in flat.lower(), (
        "settlement 7 no longer states the property it rests on — that Table 2 makes I034/100 and "
        "I034/120 mutually exclusive. Without that sentence the ruling reads as a preference"
    )
    # 2. An undefined message type is translated, not refused, at ADVISORY.
    assert "### Settlement 8" in section, "settlement 8 is gone; it is the Table 2 asymmetry"
    assert "`STATUS_CHANGE` and **`ADVISORY`**" in flat, (
        "settlement 8 no longer names the pair an undefined message type gets. Both halves matter "
        "and the second is the ruling: INFO would call an unreadable message ordinary and WARNING "
        "would invent an alarm out of it"
    )

    # The code half. Read from the adapter rather than restated here, so a settlement that stops
    # being implemented fails even while the prose still reads correctly.
    from synapse_cdm.adapters import asterix_cat034 as cat034
    both_permitted = [t for t, column in cat034.TABLE_2.items()
                      if column["I034/100"] != "X" and column["I034/120"] != "X"]
    assert both_permitted == [], (
        f"message type(s) {both_permitted} permit BOTH I034/100 and I034/120, so settlement 7's "
        "premise is false as transcribed. Either Table 2 was transcribed wrongly or the "
        "settlement has to be re-argued"
    )
    assert cat034.EVENT_TYPE_BY_MESSAGE_TYPE.keys() == set(range(1, 8)), (
        "the message-type vocabulary is no longer 001..007, which is what settlement 8's third "
        "case is defined against"
    )


def test_the_cat034_pin_agrees_at_every_site_and_says_edition_1_30_is_cited_and_unpublished():
    """One document, four sites, the pin row as ONE composite string — plus the two-part fact.

    The composite-string form is the residue of the mutation found inside `klv_pin.json`: checking
    hash, bytes and pages as three substrings makes each a disjunction over the whole file, and a
    wrong page count passes because the right number still occurs elsewhere.

    **The second half is the one this test exists for, and Phase 2 rewrote it.** Phase 1 asserted a
    SUPERSESSION — that Edition 1.29 "is not the newest published" — which was an unchecked
    inference from a citation and was false. The availability check on 2026-08-24 found the
    publisher offers nothing newer than Edition 1.29, so the fact is two-part and both parts are
    asserted separately here, because a site could carry either one alone and read as complete:

    * **cited**, by two independent sibling specifications, with the identifier and the edition
      quoted together — so the claim that the edition exists is sourced rather than recalled;
    * **unpublished**, with the CHECK DATE, because "was not published" and "was not checked" are
      indistinguishable in a repository a year later and the difference decides whether the next
      round re-checks the page or re-reads the record.

    A site stating only the first reads as a supersession, which is what Phase 1 wrote. A site
    stating only the second reads as an absence with no reason to look further. Both, or the site
    fails.
    """
    filename, digest, size, pages = CAT034_PINNED_DOCUMENT
    spaced = _spaced(size)

    # 1. The JSON, read as data. No substrings.
    pin = json.loads(CAT034_PIN.read_text())["source"]
    assert pin["sha256"] == digest, f"cat034_pin.json sha256 is {pin['sha256']}"
    assert pin["bytes"] == size, f"cat034_pin.json bytes is {pin['bytes']}"
    assert pin["pages"] == pages, f"cat034_pin.json pages is {pin['pages']}"
    assert pin["edition"] == "1.29", pin["edition"]
    assert pin["local_path"] == f"fixtures/cat034/spec/{filename}", pin["local_path"]

    # 2. FORMAT_COVERAGE.md's pin row, as one composite string.
    row = f"`{digest}`, {spaced} bytes, {pages} pages, `fixtures/cat034/spec/{filename}`"
    assert row in _section(CAT034_HEADING), (
        f"FORMAT_COVERAGE.md's pin row for {filename} is not\n  {row}"
    )

    # 3. The fixture README's table row, likewise.
    readme_row = f"| `spec/{filename}` | `{digest}` | {spaced} | {pages} |"
    assert readme_row in CAT034_README.read_text(), (
        f"fixtures/cat034/README.md's table row is not\n  {readme_row}"
    )

    # 4. MIGRATIONS.md, in this document's own ellipsised form, also as one string.
    migrations_fact = f"(`{_abbreviated(digest)}`, {spaced} bytes, {pages} pages)"
    assert migrations_fact in MIGRATIONS.read_text(), (
        f"MIGRATIONS.md's entry no longer states the pin as\n  {migrations_fact}"
    )

    # 5. The file itself, when this working tree has it, and no PDF tracked anywhere.
    path = CAT034_FIXTURES / "spec" / filename
    if path.exists():
        assert path.stat().st_size == size, f"{filename} at the pinned path is the wrong size"
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        assert got == digest, f"{filename} at the pinned path hashes to {got}"
    assert [p for p in _tracked_files() if p.endswith(".pdf")] == [], "PDFs are tracked"

    # 6. PART ONE — CITED, at all three prose sites and in the JSON as data.
    #
    # SCOPED, and the scoping is the lesson rather than a detail. `"Edition 1.30" in section` is a
    # disjunction over everything the section says, and mutation showed it: deleting the pin
    # table's row left the suite green because the prose below still mentioned the edition. So
    # each site is pinned to the ONE sentence that carries the claim, as a composite string.
    record = json.loads(CAT034_PIN.read_text())
    node = record["the_pin_is_not_the_latest_edition_and_that_is_stated_first"]
    assert "Edition 1.30" in node["finding"], node["finding"]
    citations = node["citations"]
    assert len(citations) == 2, (
        f"the record carries {len(citations)} citation(s) of Edition 1.30. TWO independent "
        "sibling specifications name it, and the second is what raises the claim above a single "
        "possibly-stale reference list. Dropping one is a deliberate act"
    )
    assert [c["pinned_here"] for c in citations] == [True, False], (
        "the citations no longer distinguish the one this repository PINS from the one it merely "
        "cites. CAT048 Edition 1.32 is on disk and hashed; CAT007 Edition 1.12 is not, and a "
        "record that levelled the two would be claiming evidence it does not hold"
    )
    for citation in citations:
        assert "Edition 1.30" in citation["quoted"], citation

    site_claims = {
        "FORMAT_COVERAGE.md": (
            "| **Edition 1.30** | **CITED BY TWO SIBLING SPECIFICATIONS AND OFFERED BY NONE.** "
            "Not in hand, and — checked 2026-08-24 — not published: see immediately below |"),
        # The README's claim has to NAME the superseding edition, not merely assert that one
        # exists: "1.29 is not the newest" tells a reader to go looking and "Edition 1.30" tells
        # them what to look for. Mutation removed the number and left the sentence, and the first
        # version of this string could not tell the difference.
        "fixtures/cat034/README.md": (
            "**Edition 1.29 is the newest edition in hand and it is also the newest edition "
            "PUBLISHED**"),
    }
    for label, claim in site_claims.items():
        text = _cat034_sites()[label]
        assert claim in " ".join(text.split()) or claim in text, (
            f"{label} no longer carries the two-part Edition 1.30 claim as\n  {claim}\n"
            "Asserted as one composite string because a bare 'Edition 1.30' is satisfied by any "
            "other mention"
        )
    # And every prose site carries the SOURCED form of the claim: the reference quoted with its
    # document identifier and its edition together. A count of "Edition 1.30" was tried and
    # rejected — the number occurs several times in the README, so a threshold either passes with
    # the sourced sentence gutted or fails on an ordinary edit. The quotation cannot be satisfied
    # by an incidental later mention, which is the property a count does not have.
    sourced = "(EUROCONTROL-SPEC-0149-2b)"
    for label in ("FORMAT_COVERAGE.md", "fixtures/cat034/README.md"):
        flat = _flat(_cat034_sites()[label])
        assert f"{sourced} **Edition 1.30**" in flat or f"{sourced}\n**Edition 1.30**" in flat, (
            f"{label} no longer quotes the reference with the identifier and the edition "
            "together. That quotation is the EVIDENCE that Edition 1.30 exists; without it the "
            "site asserts an edition and names no source for it"
        )
    # And the source is the OTHER pin, not a recollection — so the quotation has to still be there
    # to be cited. Read from the node that holds it rather than from the whole file, because
    # `"Edition 1.30" in json.dumps(pin)` is a disjunction over 1 400 lines and would survive the
    # cat034_boundary node being deleted outright.
    cat048_pin = json.loads(
        (pathlib.Path(synapse_cdm.__file__).resolve().parent
         / "fixtures" / "cat048" / "spec" / "cat048_pin.json").read_text())
    assert "Edition 1.30" in cat048_pin["cat034_boundary"]["quoted"], (
        "cat048_pin.json's cat034_boundary no longer quotes CAT034 Edition 1.30. That quotation "
        "is the SOURCE of the first of the two citations; without it the claim is a recollection"
    )

    # 7. PART TWO — UNPUBLISHED, WITH THE CHECK DATE, at every site that states it.
    CHECKED_ON = "2026-08-24"
    check = node["availability_check"]
    assert check["checked_on"] == CHECKED_ON, (
        f"the pin record says the publication page was checked on {check['checked_on']!r}. The "
        "date is the whole point of the entry: without it a later round cannot tell 'was not "
        "published' from 'was not checked'"
    )
    assert "Edition 1.29" in check["result"], check["result"]
    for label in ("FORMAT_COVERAGE.md", "fixtures/cat034/README.md"):
        flat = _flat(_cat034_sites()[label])
        assert CHECKED_ON in flat, (
            f"{label} states that Edition 1.30 is not published and does not say WHEN that was "
            f"checked. Every site carrying the availability half has to carry {CHECKED_ON} with "
            "it, or the claim decays into an assertion nobody can date"
        )
    # THE ABSENCE, and it is the half Phase 1 got wrong. No site may still say that the pinned
    # edition is not the newest PUBLISHED one — that sentence was written from a citation, was
    # never checked, and is false.
    for label, text in _cat034_sites().items():
        flat = _flat(text)
        assert "It is not the newest published" not in flat, (
            f"{label} still carries Phase 1's sentence 'It is not the newest published'. The "
            f"publisher's own Category 034 page was checked on {CHECKED_ON} and its newest file "
            "is Edition 1.29, which IS the pin. The edition is cited-but-unpublished, which is a "
            "different claim"
        )

    # 8. AND THE INFERENCE IS STILL AN INFERENCE. The availability finding says nothing about
    # contents, so Message Type 008 must not have been promoted to a fact on the strength of it.
    inference = node["what_edition_1_30_is_known_to_contain_without_being_in_hand"]
    assert "Message Type 008" in inference["claim"], inference["claim"]
    assert "inference" in inference["standing_after_the_availability_check"].lower(), (
        "the Message Type 008 claim no longer records that it is an inference AFTER the "
        "availability check. A page that does not offer a document says nothing about what the "
        "document contains, so nothing about that claim moved — and a record that stopped saying "
        "so would read as though the check had confirmed it"
    )
    assert node["reopen_condition"].startswith("Obtain Edition 1.30"), node["reopen_condition"]


@pytest.mark.parametrize("filename,edition,digest,size,pages", CAT034_HISTORY,
                         ids=lambda x: str(x)[:24])
def test_every_cat034_lineage_entry_matches_the_disk(filename, edition, digest, size, pages):
    """The lineage record against the files, one test per edition rather than one over three.

    `tests/test_cdm_pins.py` asserts that none of these is a pin. This asserts the other thing:
    that the RECORD of each one is true. Those are different failures — a lineage entry promoted
    to a pin is loud, and a lineage entry whose hash silently stops matching its file is not.

    Parametrised per edition so the failure names the edition. The pin gate deliberately does NOT
    parametrise its two history checks, for the opposite reason given there; here the entries are
    already a list in the record, so reading them from it adds no second site.
    """
    entry = next((e for e in json.loads(CAT034_PIN.read_text())["edition_history"]["files"]
                  if e["filename"] == filename), None)
    assert entry is not None, (
        f"cat034_pin.json's edition_history has no entry for {filename}"
    )
    assert entry["edition"] == edition, entry["edition"]
    assert entry["sha256"] == digest, entry["sha256"]
    assert entry["bytes"] == size, entry["bytes"]
    assert entry["pages"] == pages, entry["pages"]
    assert entry["document_identifier"] in (
        "SUR.ET1.ST05.2000-STD-02b-01", "EUROCONTROL-SPEC-0149-2b"), entry["document_identifier"]
    path = CAT034_FIXTURES / "spec" / "history" / filename
    if not path.exists():
        pytest.skip(f"{filename} is not in this working tree; the record of it is")
    assert path.stat().st_size == size, f"{filename} is {path.stat().st_size} bytes on disk"
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    assert got == digest, f"{filename} hashes to {got} on disk"


def test_the_reference_number_migration_is_bracketed_and_states_both_sides():
    """The migration is a FACT OF THE HISTORY and its evidence is that both sides are in hand.

    The claim "the reference number changed between 1.27 and 1.28" is exactly the kind that gets
    written from a filename and never checked. What makes it checkable here is that the lineage
    record carries a `document_identifier` for every edition, read off each title page — so the
    boundary is asserted against the record rather than against the prose that states it.
    """
    history = json.loads(CAT034_PIN.read_text())["edition_history"]["files"]
    by_edition = {e["edition"]: e["document_identifier"] for e in history}
    by_edition["1.29"] = json.loads(CAT034_PIN.read_text())["source"]["document_identifier"]
    assert by_edition["1.26"] == "SUR.ET1.ST05.2000-STD-02b-01", by_edition
    assert by_edition["1.27"] == "SUR.ET1.ST05.2000-STD-02b-01", by_edition
    assert by_edition["1.28"] == "EUROCONTROL-SPEC-0149-2b", by_edition
    assert by_edition["1.29"] == "EUROCONTROL-SPEC-0149-2b", by_edition
    # The boundary is bracketed: the last old and the first new are both held.
    old = {e for e, i in by_edition.items() if i.startswith("SUR.")}
    new = {e for e, i in by_edition.items() if i.startswith("EUROCONTROL-")}
    assert max(old) < min(new), f"the migration is not monotonic: old={old} new={new}"
    node = json.loads(CAT034_PIN.read_text())["the_reference_number_migration"]
    assert "1.27" in node["fact"] and "1.28" in node["fact"], node["fact"]
    # SCOPED to the migration subsection. Both identifiers also appear in the lineage table two
    # paragraphs up, so `both in section` is a disjunction that survives the migration statement
    # being reduced to "the reference number changed" — which mutation demonstrated.
    section = _section(CAT034_HEADING)
    start = section.index("#### The reference-number migration")
    end = section.index("\n#### ", start + 10)
    migration = _flat(section[start:end])
    assert "`SUR.ET1.ST05.2000-STD-02b-01` → `EUROCONTROL-SPEC-0149-2b`" in migration, (
        "the migration subsection no longer states the change as one arrow between the two "
        "identifiers. One side alone reads as the document's only identifier, which is what makes "
        "a stale ICD citation invisible"
    )
    assert "between Edition 1.27 and Edition 1.28" in migration, (
        "the migration subsection no longer states WHERE the boundary is"
    )
    assert "bracketed" in migration, (
        "the migration subsection no longer records that both sides of the boundary are in hand, "
        "which is the whole reason this claim is checkable rather than inferred"
    )


def test_the_cat002_lineage_is_recorded_at_the_strength_of_a_filename_and_no_stronger():
    """A publisher's filename is the whole of the evidence, and the record has to say so.

    This is the assertion that stops a later editor promoting the lineage to a document fact. The
    claim is true and its source is weak, and both halves have to survive: an edit that deletes the
    hedge turns "EUROCONTROL names the file this way" into "the standard says so", which no
    document in hand does.
    """
    node = json.loads(CAT034_PIN.read_text())["the_cat002_lineage"]
    assert "filename" in node["where_the_claim_comes_from_and_where_it_does_not"], node
    assert "zero times" in node["where_the_claim_comes_from_and_where_it_does_not"], (
        "the record no longer states that 'Category 002' occurs zero times in the document bodies. "
        "That measurement is what makes the hedge a finding rather than a caveat"
    )
    assert node["what_is_NOT_claimed"], "the not-claimed list is empty"
    flat = _flat(_section(CAT034_HEADING))
    assert "publisher's filename" in flat, (
        "the section no longer says the CAT002 claim rests on a filename"
    )
    assert "zero** times" in flat or "**zero**" in flat, (
        "the section no longer states the zero-occurrence measurement"
    )
    # And the same device is recorded as already present for Part 4, which is what makes the
    # DISPOSITION (record it, do not name the adapter after it) a precedent rather than a choice.
    assert "next version of cat-001" in flat, (
        "the section no longer cites CAT048's identically-named history files. Without them the "
        "decision not to name this adapter `cat002` has no precedent behind it"
    )


def _cat034_map(harness_tests) -> dict:
    """Whichever half of the harness's fixture-directory map holds `cat034`, and only one may.

    The two halves are kept apart deliberately — the shipped half is an equality against the
    registry, and a Phase 1 name in it would break that — so an adapter crossing from one to the
    other is an ordinary event and a check reading only one half breaks on it. A name in BOTH is a
    real defect and fails here rather than being resolved silently by precedence.
    """
    holders = [half for half in (harness_tests.PLANNED_FIXTURE_DIRS,
                                 harness_tests.SHIPPED_FIXTURE_DIRS) if "cat034" in half]
    assert len(holders) == 1, (
        f"`cat034` is in {len(holders)} halves of the harness fixture-directory map. It belongs to "
        "exactly one: PLANNED_FIXTURE_DIRS while it is a specification, SHIPPED_FIXTURE_DIRS once "
        "the adapter registers, and the move happens in the same commit as the code"
    )
    return holders[0]


def test_the_two_cat034_names_are_the_same_string_and_the_section_says_why():
    """THE DISJUNCTION TREATMENT, applied to a case where the two names COINCIDE.

    #9's test asserts that its adapter name and fixture directory still DIFFER, because collapsing
    two rulings with different evidence into one cell hides that they have different lifetimes.
    The naive generalisation — "an adapter's name always differs from its directory" — is FALSE for
    the ASTERIX family, and a round that applied it would rename this directory for no reason.

    So the coincidence is asserted POSITIVELY, collected from every site the way #9's difference is,
    AND the reasoning is required to be present. A ruling that happens to be right with no record
    of why is the thing the next editor overturns.

    **The map half moved when the adapter shipped**, and this test reads whichever half holds it
    rather than being pinned to one: `cat034` was in `PLANNED_FIXTURE_DIRS` at Phase 1 and is in
    `SHIPPED_FIXTURE_DIRS` now. Reading only one would have turned a correct transition into a
    failure, and hard-coding the new one would leave the check unable to survive the next.
    """
    import importlib
    harness_tests = importlib.import_module("tests.test_cdm_harness")

    pin = json.loads(CAT034_PIN.read_text())
    ordinal_table = _section("### The adapter ordinals")

    adapter_name = {
        "cat034_pin.json": pin["adapter"]["name"],
        "cat034_pin.json (the ruling)": pin["adapter"]["name_ruling"]["ruled"],
        "test_cdm_harness.py fixture-directory map":
            next(n for n in _cat034_map(harness_tests) if n == "cat034"),
        "FORMAT_COVERAGE.md ordinal table":
            re.search(r"\|\s*12\s*\|\s*`([a-z0-9]+)`", ordinal_table).group(1),
    }
    assert len(set(adapter_name.values())) == 1, (
        f"the adapter name disagrees across sites: {adapter_name}"
    )
    name = next(iter(adapter_name.values()))
    assert name == "cat034", name

    directory = {
        "cat034_pin.json": pin["adapter"]["fixture_directory"],
        "test_cdm_harness.py fixture-directory map": _cat034_map(harness_tests)[name],
        "the pinned path": pin["source"]["local_path"].split("/")[1],
    }
    assert len(set(directory.values())) == 1, (
        f"the fixture directory disagrees across sites: {directory}"
    )
    fixture_dir = next(iter(directory.values()))
    assert fixture_dir == "cat034" and (CAT034_FIXTURES.parent / fixture_dir).is_dir()

    # THE POSITIVE ASSERTION, and the one #9's mirror image would get wrong.
    assert name == fixture_dir, (
        "the adapter name and the fixture directory have diverged. They are the same string here "
        "on purpose — an ASTERIX category IS the payload — exactly as `cat021`'s and `cat048`'s "
        "are, and splitting them would be applying #9's rule to a case it does not reach"
    )
    for other in ("cat021", "cat048"):
        assert harness_tests.SHIPPED_FIXTURE_DIRS[other] == other, (
            f"{other}'s directory is no longer its own name, so the precedent this ruling rests on "
            "has moved. Re-rule the CAT034 name in the same commit"
        )
    # And the reasoning is present rather than only the outcome.
    assert f"`{name}` is adapter #12" in CAT034_README.read_text(), (
        "fixtures/cat034/README.md no longer states the ordinal in the claim form, which is the "
        "form tests/test_cdm_ordinals.py binds"
    )
    flat = _flat(_section(CAT034_HEADING))
    assert "precedent and the document agree" in flat.lower(), (
        "the section no longer records WHAT decided the name. RULING 0 asked for the deciding "
        "source to be stated, and 'both' is the answer only while it is written down"
    )
    assert "only bites when the adapter is named after a" in flat, (
        "the section no longer says why the payload-versus-standard split does not apply here. "
        "Without it, the coincidence reads as the bug 80b38d1 repaired rather than as a ruling"
    )


def test_the_page_count_method_change_is_recorded_with_its_validation():
    """A corrected number with no record of the correction is a typo that happened to be right.

    41 is not what the method `klv_pin.json` records would produce for this file, and this is the
    first round where the two methods disagree. Three things therefore have to be stated, and each
    is a different kind of claim: WHAT disagrees (a measurement), WHY the new method is trusted
    (a validation against ten known answers), and a check that does not depend on either tool (the
    document's own printed folios). Any one of them alone is an assertion; the three together are
    a derivation.

    The fourth assertion is the one that keeps the past honest: `klv_pin.json`'s method string must
    NOT have been rewritten. It describes what was done for those documents and it was correct for
    them, and editing it to match a later method would erase the fact that the method changed.
    """
    node = json.loads(CAT034_PIN.read_text())["page_count_method"]
    assert "/pages tree" in node["how"].lower(), node["how"]
    disagreement = node["the_disagreement_measured"]
    assert "41" in disagreement["edition_1_29"] and "43" in disagreement["edition_1_29"]
    assert "43" in disagreement["edition_1_28"] and "44" in disagreement["edition_1_28"]
    assert "38" in disagreement["editions_1_27_and_1_26"]
    # The validation, and it has to name the reproduced counts rather than assert success.
    for count in ("64", "73", "212", "104", "192", "150"):
        assert count in node["the_method_was_validated_before_it_was_preferred"], (
            f"the validation no longer names the page count {count}. A validation that says "
            "'all ten reproduced' without the numbers is a claim, not evidence"
        )
    assert "printed folios" in node["the_stronger_check_does_not_depend_on_either_tool"]
    assert "1 + 7 + 33 = 41" in node["the_stronger_check_does_not_depend_on_either_tool"]
    # The section states it too, because a reader meets 41 there first.
    flat = _flat(_section(CAT034_HEADING))
    assert "over-counts two of these four files" in flat, (
        "the section no longer records that the earlier page-count method over-counts here"
    )
    assert "no existing pin moves" in flat, (
        "the section no longer states that the new method reproduces every existing pin's count. "
        "Without it, a method change reads as a reason to re-open ten settled numbers"
    )
    # AN ABSENCE: the past record is untouched.
    klv = json.loads((pathlib.Path(synapse_cdm.__file__).resolve().parent
                      / "fixtures" / "klv" / "spec" / "klv_pin.json").read_text())
    assert "/Type /Page" in json.dumps(klv), (
        "klv_pin.json's page_count_method no longer describes the raw-object scan. It was rewritten "
        "to match the newer method, which erases the fact that the method changed — the CAT034 pin "
        "records the change deliberately so that record does not have to move"
    )


def test_the_change_record_over_claim_is_measured_and_the_governing_rule_is_stated():
    """Two of Edition 1.29's three change-record claims are false, and the finding sets a RULE.

    This is not a curiosity. A change record is what a later round reaches for when it wants to
    know when something was introduced, and the CAT048 lineage round built an entire table from
    one. So the disposition matters more than the finding: where a record and the text disagree,
    the TEXT governs. That sentence has to survive, or the next round quietly treats a record as a
    source again.

    The measurements are asserted as numbers because "identical" is a judgement and "254
    characters" is a check somebody can repeat.
    """
    node = json.loads(CAT034_PIN.read_text())["the_document_change_record_over_claims_and_it_is_measured"]
    verdicts = {c["claim"]: c["verdict"] for c in node["what_edition_1_29_s_record_says_it_changed"]}
    assert sum(v == "FALSE" for v in verdicts.values()) == 2, verdicts
    assert sum(v == "TRUE" for v in verdicts.values()) == 1, verdicts
    assert "254 characters" in node["section_2_2"], node["section_2_2"]
    assert "1690 characters" in node["section_3_1"], node["section_3_1"]
    # The TRUE one is corroborated two ways, which is what makes the two FALSE ones credible.
    assert "Five types" in node["section_4_6_1_and_5_2_1"]
    assert "Seven types" in node["section_4_6_1_and_5_2_1"]
    # THE RULE, at the pin and in the section.
    assert "TEXT governs" in node["verdict"] or "TEXT GOVERNS" in node["verdict"], node["verdict"]
    flat = _flat(_section(CAT034_HEADING))
    assert "where a change record and the text disagree, the TEXT governs" in flat, (
        "the section no longer states the governing rule the over-claim produced. The finding "
        "without the rule is trivia; the rule is what the next lineage round inherits"
    )


def test_the_sensor_position_finding_changes_nothing_and_says_so_at_both_ends():
    """The strongest cross-format finding of the round, and its whole content is a REFUSAL.

    `I034/120` is the value CAT048 settlement 3 has the caller inject and gap 24 records as absent
    from the CAT048 document. The tempting move is to close gap 24, or to have this adapter hand
    the position over to the one at #11. Both are cross-payload state, the fusion refusal.

    So this is asserted at BOTH ends: the CAT034 section must state the refusal, and gap 24 must
    still be open. The second half is the one that decays — a later reader meeting both sections
    could reasonably conclude the gap was closed and nobody updated the list.
    """
    flat = _flat(_section(CAT034_HEADING))
    assert "I034/120" in flat, "the section no longer names the item"
    assert "Gap 24 does not close, deliberately" in flat, (
        "the section no longer states that gap 24 stays open. Without it, the finding reads as a "
        "closure that nobody recorded"
    )
    assert "hand it to nobody" in flat or "hands it to nobody" in flat, (
        "the section no longer states the refusal in as many words"
    )
    # Gap 24 is still a gap, in the gaps list, unqualified.
    gaps = DOC.read_text()[DOC.read_text().index("## Gaps, and what each one costs"):]
    assert re.search(r"^24\. \*\*No sensor frame", gaps, re.M), (
        "gap 24 is no longer in the gaps list under its own number. CAT034 carrying a station "
        "position does not change what the CAT048 document contains"
    )
    # And the eighth statement of the fusion refusal is present and numbered — bound to the
    # SETTLEMENT HEADING, not to the section. "for the eighth time" occurs twice (the heading and
    # the declines table), so an unscoped `in` is a disjunction: mutation changed the heading and
    # the suite stayed green because the table still said it.
    assert "### Settlement 6 — A translator owes no fusion. Stated once, and for the eighth time" \
        in DOC.read_text(), (
            "the CAT034 fusion-refusal settlement is no longer numbered as the eighth in its own "
            "heading. The count is how a reader sees that it is a standing rule and not a "
            "per-format opinion, and the heading is the site a reader meets first"
        )


def test_gap_29_is_opened_for_the_interference_vocabulary_and_no_field_is_proposed():
    """The one gap this round opens, and the proposal it deliberately does not make.

    The bar this repository holds itself to is stated in MIGRATIONS.md: one format wanting a shape
    is a gap and two are a proposal. Only CAT034 has raised this one. So two things are asserted
    together — that the gap exists with its reasoning, and that nothing was added to the 1.1.0
    list on the strength of a single format.
    """
    gaps = DOC.read_text()[DOC.read_text().index("## Gaps, and what each one costs"):]
    assert re.search(r"^29\. \*\*No interference vocabulary that is not about GNSS", gaps, re.M), (
        "gap 29 is not in the gaps list under its own number"
    )
    gap = gaps[gaps.index("29. **No interference vocabulary"):]
    flat = _flat(gap)
    assert "GnssInterferencePayload" in flat, "gap 29 no longer names the payload it is about"
    assert "Not proposed as a field for 1.1.0" in flat, (
        "gap 29 no longer states that it is not a proposal. A gap that does not say why it stopped "
        "short of one is a proposal somebody forgot to write"
    )
    assert "one format wanting a shape is a gap and two are a proposal" in flat, (
        "gap 29 no longer states the bar it is being held to"
    )
    # The row set's ruling agrees with the gap, at the other end of the document.
    section = _flat(_section(CAT034_HEADING))
    assert "never sets `GNSS_INTERFERENCE`" in section or \
           "`GNSS_INTERFERENCE` is never set" in section or \
           "and it never sets `GNSS_INTERFERENCE`" in section, (
        "the CAT034 settlement no longer states that GNSS_INTERFERENCE is never set"
    )
    assert "**Gap 29** is opened for it" in section, (
        "the settlement no longer points at the gap it opened"
    )
    # AN ABSENCE: nothing was added to the 1.1.0 proposal list.
    proposed = MIGRATIONS.read_text()
    proposed = proposed[proposed.index("## Proposed for the next MINOR"):]
    for token in ("RF_INTERFERENCE", "InterferencePayload", "GNSS_INTERFERENCE"):
        assert token not in proposed, (
            f"{token} has appeared in MIGRATIONS.md's 1.1.0 proposal list. One format raised this; "
            "the bar for a proposal is two, and gap 29 says so"
        )


def test_migrations_records_the_cat034_landing_and_the_entry_moved_out_of_the_phase_1_heading():
    """The entry MOVED, and the move is the assertion — in both directions.

    Phase 1 put `cat034` under "Row sets written as specifications, with no adapter code yet", a
    heading that exists because a Phase 1 proposing nothing and a Phase 1 nobody thought about look
    identical from that file. **The heading means what it says**, so an adapter that has landed
    cannot stay under it: leaving the entry there would make the heading false about one of its own
    members, which is a worse failure than never having had the entry.

    So this test asserts the absence under the old heading and the presence under the new one. The
    absence is the half that would rot silently — a duplicated entry reads as complete from either
    end — and it is why the two are checked together rather than the new one alone.
    """
    text = MIGRATIONS.read_text()
    spec_start = text.index("### Row sets written as specifications, with no adapter code yet")
    spec_end = text.index("## Proposed for the next MINOR")
    spec_block = text[spec_start:spec_end]
    spec_section = _flat(spec_block)
    # Anchored to the ENTRY form — a bullet that opens with the name — and not to any mention of
    # it, because the two remaining entries legitimately refer to `cat034` in prose: one of them
    # dates its own harness-map sentence by saying the shipped set was nine when it was written
    # and ten since `cat034` landed. A check on the bare name would read that record as the
    # defect it records the absence of.
    entries = [line for line in spec_block.splitlines() if line.startswith("- **")]
    assert not [e for e in entries if e.startswith("- **`cat034`")], (
        "MIGRATIONS.md still has a `cat034` ENTRY under 'Row sets written as specifications, with "
        "no adapter code yet'. The adapter has landed, so that heading is now false about it — "
        "the entry moves to 'Adapters that landed with no schema change' in the same commit as "
        "the code, it does not get a second copy"
    )
    assert len(entries) == 2, (
        f"{len(entries)} entries under the specifications heading, expected 2. `stanag4609` and "
        "`stanag5527` are the two adapters still at Phase 1"
    )
    assert "`stanag4609`" in spec_section and "`stanag5527`" in spec_section, (
        "the two remaining Phase 1 entries are gone from the specifications heading, so the check "
        "above is passing on an empty section rather than on a section cat034 has left"
    )

    landed_start = text.index("### Adapters that landed with no schema change")
    landed_section = _flat(text[landed_start:spec_start])
    assert "`adapters/asterix_cat034.py` 1.0.0" in landed_section, (
        "MIGRATIONS.md has no CAT034 entry under 'Adapters that landed with no schema change'"
    )
    assert "with no field added, removed or retyped" in landed_section
    assert "**gap 29**" in landed_section, "the entry no longer names the gap it opened"
    assert "it stays a gap rather than becoming a 1.1.0 proposal" in landed_section, (
        "the entry no longer says what it declined to propose. One format wanting a shape is a "
        "gap and two are a proposal, and the entry has to state which side of that line it is on"
    )
    assert "gap 24 does not close" in landed_section.lower(), (
        "the entry no longer records that the I034/120 finding closes nothing"
    )
    # The two rulings Phase 1 deferred, named in the file a reader of the schema history opens.
    assert "there is no message type for which both are permitted" in landed_section.lower(), (
        "the entry no longer states WHY no Geometry is derived. 'We decided not to' and 'the "
        "document forbids it' are different claims and only one of them survives review"
    )
    # And the Edition 1.30 correction, which is the one part of this entry that is not about code.
    assert "2026-08-24" in landed_section, (
        "the entry records the Edition 1.30 finding without the date the publication page was "
        "checked. This file is where a reader goes for what changed and when"
    )


def test_the_changelog_page_carries_the_cat034_entry_now_that_the_adapter_landed():
    """The convention Phase 1 established, applied in the direction Phase 1 could not.

    `tests/test_cdm_changelog_claim.py` rules that `docs/docs/changelog.mdx` is a CURATED SUMMARY
    of `MIGRATIONS.md` and not a copy — page ⊆ file, never file ⊆ page. Phase 1 used that to keep
    the page clean of `cat034` entirely, on the ground that "no adapter code, no fixtures, one
    park" is repository process rather than schema history, and this test asserted the absence.

    **Phase 2 is the other case, and the same ruling decides it the other way.** A landed adapter
    IS the page's genre — every one of the other adapters that landed has an entry there — so
    keeping `cat034` off it would leave the page's history section stating a roster smaller than
    the one the contract ships. The subset direction is unchanged and is still what
    `test_cdm_changelog_claim.py` enforces: the page may leave things out and may never add an
    adapter the file does not name.
    """
    repo = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]
    page = (repo / "docs" / "docs" / "changelog.mdx").read_text()
    assert "`adapters/asterix_cat034.py` 1.0.0" in page, (
        "docs/docs/changelog.mdx has no CAT034 entry. Every adapter that landed has one, and a "
        "page whose history section is a roster short is the drift that ruling exists to prevent"
    )
    assert "asterix_cat034.py" in MIGRATIONS.read_text(), (
        "the page names a module MIGRATIONS.md does not — which is the ONE direction the summary "
        "claim forbids. See tests/test_cdm_changelog_claim.py"
    )
    # The page is still a summary rather than a copy: the Phase 1 material stays off it. Anchored
    # to the sentence a Phase 1 entry actually carries rather than to the words "Phase 1", which
    # the page uses legitimately in its own paragraph about what it curates.
    for token in ("no adapter code, no codec, no fixtures", "reserved-ordinal rule",
                  "cited-but-unpublished"):
        assert token not in page, (
            f"docs/docs/changelog.mdx now carries {token!r}. That page is for a reader of the "
            "published contract; the two-phase protocol, the ordinal rule and the pin lineage are "
            "repository process — the f99a4b0 ruling, which Phase 2 narrows rather than reverses"
        )


def test_the_cat034_rows_are_actually_resolved_against_the_models():
    """A section that contributes ZERO paths passes the parametrised resolver by contributing no
    cases, and a silent zero looks exactly like a clean pass.

    The GMTIF block makes the same check for the same reason. What is different here is the egress
    table. CAT034's was written headed `CDM field` while five siblings were still headed `CDM` and
    therefore contributed nothing to the resolver at all — the defect `_cdm_paths`'s docstring
    records. All seven are aligned now, so this test's claim is no longer unique to this section;
    it is kept because the CAT034 egress paths are the ones this section is answerable for, and a
    per-section check fails with the section named where the document-wide one does not.
    """
    section = _section(CAT034_HEADING)
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
    assert len(paths) >= 30, (
        f"the CAT034 section resolved only {len(paths)} CDM path cells. A twelve-item row set with "
        "an egress table contributes far more, so a table header the parser does not recognise has "
        "crept in — check that every mapping table says exactly 'CDM field'"
    )
    # THE HEADERS THEMSELVES, counted. A floor plus a required-paths list is not enough and
    # mutation proved it: dropping ONE table's header left both satisfied, because that table's
    # paths (`Entity.attributes`, `Event.payload`) also occur in six others. Nine mapping tables
    # go in and nine have to be parseable, so the count is the claim — the same reason the
    # `not yet` check above is an equality rather than a floor.
    headers = section.count("| CAT034 | CDM field | Status | Notes |")
    assert headers == 7, (
        f"{headers} of the CAT034 ingress row-set tables are headed `| CAT034 | CDM field | Status "
        "| Notes |`, expected 7. A table headed anything else contributes ZERO paths to the "
        "resolver and its rows silently stop being checked against the models — which a floor "
        "cannot catch, because the other tables carry the floor on their own"
    )
    assert section.count("| CDM field | CAT034 | Status | Notes |") == 1, (
        "the egress table's header changed. There is exactly one egress table"
    )
    assert section.count("| CDM field | Filled with | Why the format cannot say |") == 1, (
        "the fills table's header changed. There is exactly one fills table"
    )
    # The paths the settlements turn on. Each would be the tell if a whole table were dropped.
    for required in ("Entity.position", "Position.lat", "Position.lon", "Position.alt_m",
                     "Position.accuracy_m", "Position.position_source", "Entity.entity_type",
                     "Entity.affiliation", "Entity.source_ids", "Entity.attributes",
                     "Event.payload", "Event.event_type", "Event.severity", "Event.geometry",
                     "SourceRef.synthetic", "Event.received_at"):
        assert required in paths, (
            f"{required} is not among the paths the CAT034 section resolves. Either the row that "
            "should carry it has lost its CDM field, or its table's header no longer names the "
            "column — and in both cases the row stopped being checked against the models"
        )
    # The egress half specifically, which is what the header change bought.
    egress = section[section.index("### Row set — egress"):]
    assert "| CDM field | CAT034 | Status | Notes |" in egress, (
        "the CAT034 egress table's header no longer names the CDM column, so its rows have stopped "
        "being resolved against the models — the state five of the seven egress tables were in "
        "until the egress-header ruling, "
        "and the one this table was written out of"
    )
    assert set(paths) <= set(PATHS), (
        f"the section resolves paths the document-wide sweep does not: "
        f"{sorted(set(paths) - set(PATHS))}"
    )


def test_the_provenance_round_says_it_RAN_the_route_rather_than_describing_it():
    """The walk round's rule, extended one link back — and it has to say so or it is a description.

    `the_command_was_re_run_not_recalled` is the precedent: an extraction command stated because it
    was re-run is worth more than one stated because it was remembered. The same distinction applies
    to a fetch. A pin that says "fetch this URL, then run this command" and was never followed
    end to end is a plausible route, and a plausible route is what this repository has twice found
    to be wrong about itself. So both halves are asserted here — the fetch AND the re-extraction —
    and the pin record's own field is checked, because the prose can be edited without it.
    """
    flat = _flat(_provenance_section())
    assert "was RUN, not assembled from its parts" in flat, (
        "the section no longer says the route was exercised. Stated as a route it is a claim about "
        "what a reader can do; stated as an exercised route it is a report of doing it"
    )
    assert "977" in flat and "ffmpeg\n9.0.1".replace("\n", " ") in flat, (
        "the re-extraction's result or its tool version is gone. A byte count without the version "
        "that produced it is not reproducible — the walk round's pin records the version for that "
        "reason"
    )
    record = json.loads((DOC.parent / "fixtures/klv/spec/klv_pin.json").read_text())
    extraction = record["walk_ruling_real_stream_2026_08_26"]["the_two_pins"]["extraction"]
    ran = extraction.get("the_complete_route_was_RUN_this_round_and_not_only_described", "")
    assert extraction["sha256"] in ran and "IDENTICAL" in ran, (
        "the pin record no longer states that the fetch-to-extraction chain was followed, or states "
        "it without the digest it arrived at. The extraction pin has no URL of its own — its "
        "provenance IS the command applied to the transport stream — so this field is the only place "
        "that says the chain closes"
    )
