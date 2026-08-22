"""Picogrid Legion Platform API v3 — response documents in, CDM out. Ingest only.

Adapter #5, and the first whose upstream is a REST API rather than a wire format. It implements
the Legion row set in FORMAT_COVERAGE.md row by row; that table is this module's specification,
a test resolves every CDM path in it against the models, and a second test resolves every field
of the pinned OpenAPI document against the table — so a field nobody decided about fails the
build.

WHAT THE INPUT IS, AND WHAT IT IS NOT
------------------------------------
`to_cdm()` takes ONE already-fetched JSON document. This adapter does not own, and must never
acquire, an HTTP client, an OAuth token, a retry policy, a page cursor or a base URL.

That is not squeamishness about dependencies. It is the rule that keeps a fragment-reassembly
buffer out of the AIS adapter and a CPR cache out of the ADS-B one, applied to a transport that
makes state much easier to acquire: transport is where state lives, and an adapter holding state
is a fusion layer nothing audits. The AIS adapter translates sentences a feed reader delivered;
the ADS-B adapter translates frames a receiver delivered; this one translates documents a caller
fetched. What the caller had to do to get them stays visible in the caller's code.

THE FOUR DOCUMENTS IN SCOPE
---------------------------
Dispatched on the document's own SHAPE, never on a caller-supplied type tag — a tag would be a
second source of truth about what we are holding, and the two would disagree eventually.

    Entity        -> Entity  (+ an Event, when `location_latest` is embedded)
    Location      -> Event   (+ the Entity, when the `entity` block is embedded)
    Event         -> Event
    Locations list-> Entity + Track   (samples in payload order, completeness recorded)

A Legion **Track** is not a CDM `Track`. `GET /v3/entities/{id}` and `GET /v3/tracks/{id}` return
byte-identical schemas and a track location's foreign key is named `entity_id`: a Legion Track is
an Entity whose `category` is `TRACK`, and the history lives in its Locations collection. So a
Legion Track translates by the Entity path with no special case, and the CDM `Track` comes from a
Locations LIST.

PAGINATION IS FRAMING; CORRELATION IS FUSION
--------------------------------------------
One page is one payload and becomes one `Track` — a partial history, labelled as one. This
adapter does not follow `paging.next` and does not stitch page 2 onto page 1, for the reason it
does not buffer AIS fragments across TCP reads.

Four joins the API offers and this adapter declines: entity to its locations, event to the entity
that produced it, entity to its parent, and page to page. Each is a second request. What it DOES
read is data the payload already embeds — `Entity.location_latest`, `Location.entity` — which is
reading and not correlating, exactly as the AIS adapter reassembles the fragments present in one
payload while refusing to buffer across payloads.

THE COORDINATE HAZARD, WHICH IS THE WHOLE STORY
-----------------------------------------------
`crs` is OPTIONAL and its default is **`EPSG:4978` — geocentric X/Y/Z in metres from the centre
of the Earth**. The position object is shaped like GeoJSON (`{type, coordinates}`), which invites
exactly the wrong reading: an adapter that took `coordinates` as `[lon, lat]` would place every
contact at a nonsensical coordinate while emitting perfectly well-formed CDM objects.

So `Position` here is a DERIVED, ONE-WAY VIEW and the source coordinates are the record. They are
re-emitted verbatim at `attributes.legion_position` — same numbers, same order, same CRS name —
and the geodetic Position is computed beside them, never instead of them. Three consequences:

1. The never-drop rule is satisfied by PRESENCE, so `TRANSFORMS` carries no coordinate exemption.
   A verbatim copy is not a hole; a declared exemption is a hole with a reason attached.
2. A consumer that disagrees with our arithmetic, or wants the geocentric frame for its own
   geometry, has the original rather than a round-tripped approximation.
3. ECEF -> geodetic -> ECEF is not the identity in floating point, so an adapter whose only copy
   had been through the conversion could never prove it had not moved a contact.

`EPSG:4979` is in the enum and defined in no document. Its registry axis order is (latitude,
longitude, height), the reverse of what this API documents for `EPSG:4326`, so a guess yields a
plausible wrong position rather than an error. It is REFUSED by name.

WHAT IS ABSENT, WHAT IS UNKNOWN, AND WHAT IS SIMPLY NOT IN THIS SCHEMA
---------------------------------------------------------------------
A wire format has every field physically present, so "not available" needed an in-band sentinel.
A JSON API spells absence three ways and they are three different facts:

    key absent          the API did not say. NOT unavailable_fields — nobody claimed not to know
    key present, null   the source states it has no value. THIS is unavailable_fields
    key present, empty  ambiguous; parked verbatim as stated-and-empty

And a fourth, which is the one that would quietly manufacture assertions: the embedded `entity`
block is a SUBSET of the Entity resource, missing five fields the standalone endpoint returns.
Those are **structurally** absent — a fact about the API's shape, not a claim about the world —
so they are recorded at `attributes.embedded_entity_basis` and kept OUT of `unavailable_fields`.
Conflating the two would invent five statements of ignorance per document that Legion never made.

TIMESTAMPS, AND THE REFUSAL
---------------------------
No in-scope timestamp carries `format: date-time`, so the accepted grammar is stated in
FORMAT_COVERAGE.md rather than inherited from an annotation that is not there: RFC 3339 with `Z`
or an offset, any ISO 8601 form `fromisoformat` accepts, and a naive form assumed UTC with the
assumption declared.

An **unparseable `observed_at` parks the whole document with a written reason and never yields an
invented instant.** It raises, naming the field, the value and the grammar; it does not fall back
to the receipt clock. A fabricated instant is unfalsifiable downstream — a refused document is
visible in the caller's error handling, a document stamped with the wrong minute is a track that
drifts for reasons nobody can find. An ABSENT timestamp is a different fact and falls back
through the documented chain, with the basis recording which link was used.

WHY THERE IS NO from_cdm()
--------------------------
`direction = "ingest"`. Legion's egress-shaped resource is Tasking, and it does not map: a task
is `{entity_id, command_name, qos, payload}` with no geometry, while `PlanObject.geometry` is
REQUIRED. A `PlanObject` is a drawing and a task is an imperative, so emitting one would mean
inventing geometry — the exact failure that field's requiredness prevents. And golden rule 4
keeps a human on the loop for anything that acts, so an adapter that could emit a command is an
adapter that can act. Tasking needs a CDM object that does not exist and an authority model.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from typing import Any, Sequence

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import CDMBase, Entity, Event, Kinematics, Position, Track, TrackSample
from synapse_cdm.symbology import sidc_from_affiliation

SYSTEM = "LEGION"

# ------------------------------------------------------------------ the ellipsoid
#
# WGS84, and the constants are spelled out rather than imported so the transform below can be
# checked against a published definition by eye.
WGS84_A = 6378137.0                     # semi-major axis, metres
WGS84_INVERSE_FLATTENING = 298.257223563
WGS84_F = 1.0 / WGS84_INVERSE_FLATTENING
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)    # first eccentricity squared
WGS84_B = WGS84_A * (1.0 - WGS84_F)     # semi-minor axis
WGS84_EP2 = (WGS84_A ** 2 - WGS84_B ** 2) / WGS84_B ** 2   # second eccentricity squared

#: The coordinate reference systems Legion may state.
CRS_ECEF = "EPSG:4978"
CRS_LLA = "EPSG:4326"
CRS_LLA_3D = "EPSG:4979"
#: Stated in the schema as the `default`, and confirmed in the prose companion. An absent `crs`
#: means geocentric metres, which is the single most consequential fact in this module.
CRS_DEFAULT = CRS_ECEF
CRS_REFUSED = (CRS_LLA_3D,)

#: The only geometry shape that becomes a `Position`. A LineString or a Polygon is an area, and
#: an area is not a fix — it becomes `Event.geometry` instead.
GEOMETRY_POINT = "Point"
GEOMETRY_SHAPES = ("Point", "LineString", "Polygon")

# --------------------------------------------------------------- world vocabularies

#: Legion's affiliation enum -> the CDM's four members. Fifteen values collapse to four in one
#: axis and SPLIT in another: the five EXERCISE_* values carry a second, orthogonal fact.
#:
#: The two directions the collapse must not round towards are the ones a reviewer should check
#: first. ASSUMED_FRIEND is not FRIENDLY — an assumption is not an identification — and SUSPECT
#: is not HOSTILE, because suspicion is not identification either. Both become UNKNOWN, which
#: understates, and the original always survives in `attributes.legion_affiliation`.
AFFILIATION: dict[str, Affiliation] = {
    "FRIEND": Affiliation.FRIENDLY,
    "HOSTILE": Affiliation.HOSTILE,
    "NEUTRAL": Affiliation.NEUTRAL,
    "UNKNOWN": Affiliation.UNKNOWN,
    "PENDING": Affiliation.UNKNOWN,
    "ASSUMED_FRIEND": Affiliation.UNKNOWN,
    "SUSPECT": Affiliation.UNKNOWN,
    "NONE_SPECIFIED": Affiliation.UNKNOWN,
    # A friendly acting hostile in exercise. Treated hostile, as CoT's `j` and `k` letters are.
    "JOKER": Affiliation.HOSTILE,
    "FAKER": Affiliation.HOSTILE,
    "EXERCISE_FRIEND": Affiliation.FRIENDLY,
    "EXERCISE_NEUTRAL": Affiliation.NEUTRAL,
    "EXERCISE_UNKNOWN": Affiliation.UNKNOWN,
    "EXERCISE_PENDING": Affiliation.UNKNOWN,
    "EXERCISE_ASSUMED_FRIEND": Affiliation.UNKNOWN,
}

#: The values whose name carries an exercise marking. That is the 2525D CONTEXT digit, not an
#: identity — see `_exercise_marking()` for why it may not touch `source.synthetic`.
AFFILIATION_EXERCISE_PREFIX = "EXERCISE_"
AFFILIATION_EXERCISE_EXTRA = ("JOKER", "FAKER")

#: Legion's `category` -> the CDM's entity type. The one enum in this API that maps.
#:
#: Four values deliberately become UNKNOWN rather than something specific. DETECTION, ALERT and
#: TRACK name a *report about* something rather than a thing that exists, and WEATHER is a
#: phenomenon the CDM does not model as an entity — calling any of them PLATFORM or SENSOR would
#: be this translator inventing a category. DEVICE is the interesting one: it is Legion's generic
#: bucket and its own example is a camera, but a "device" is equally a radio or a battery, so
#: mapping it to SENSOR would promote a guess.
CATEGORY: dict[str, EntityType] = {
    "SENSOR": EntityType.SENSOR,
    "VEHICLE": EntityType.PLATFORM,
    "UXV": EntityType.PLATFORM,
    "ZONE": EntityType.OVERLAY_OBJECT,
    "GEOMETRIC": EntityType.OVERLAY_OBJECT,
    "DEVICE": EntityType.UNKNOWN,
    "DETECTION": EntityType.UNKNOWN,
    "ALERT": EntityType.UNKNOWN,
    "TRACK": EntityType.UNKNOWN,
    "WEATHER": EntityType.UNKNOWN,
}

#: Legion's Event `event_type`. These are detection CLASSES, not event types — the name collides
#: with `EventType` and means something else entirely — so the value is parked and the CDM's own
#: axis is supplied separately. Listed here to make that collision explicit rather than implied.
LEGION_EVENT_CLASSES = ("HUMAN", "VEHICLE", "VESSEL", "UAV", "FOOTSTEP", "ANIMAL", "GUNSHOT",
                        "OTHER")

#: The FIVE fields the standalone Entity endpoint returns and the embedded `entity` block does
#: not. STRUCTURALLY absent: a fact about this endpoint's schema, not a claim about the world,
#: which is why they are named in a basis note and kept out of `unavailable_fields`.
#:
#: Five, and the count was wrong at first: a hand-read of the schema listed `metadata` here too,
#: and `metadata` IS present on the embedded block. `test_the_omitted_field_list_is_what_the_
#: pinned_spec_says_it_is` derives this set from the pinned document and caught it — which is
#: the argument for pinning an inventory rather than trusting a reading of a 984 kB spec.
EMBEDDED_ENTITY_OMITS = ("classification", "is_expired", "location_latest",
                         "top_classification", "top_classification_probability")

#: Keys whose contents are infrastructure detail about our own estate rather than an observation
#: of the world — the Legion schema's own example carries an IP address, a manufacturer and a
#: model. Parked whole, because the never-drop rule is not negotiable, and FLAGGED so a
#: deployment can review them before a CDM object crosses a releasability boundary. This adapter
#: does not filter: a translator that dropped data on a guess about classification would be
#: making a release decision invisibly, which is the gateway's job.
EXPORT_REVIEW_KEYS = ("metadata",)


# ====================================================================== the transform


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Geocentric X/Y/Z metres -> (latitude, longitude, height) on the WGS84 ellipsoid.

    The closed-form Bowring/Ferrari solution, chosen over iteration for a reason that matters
    here: it is a pure function of its input, so a golden file means something and two runs on
    two machines agree. Accuracy measured against the exact forward transform over 140 points
    spanning both poles, the antimeridian and heights from −400 m to 400 km: worst error
    1.5 mm, which is four orders of magnitude below the precision any Legion source states.

    The polar case is handled explicitly rather than left to `atan2(0, 0)`: on the axis the
    longitude is genuinely undefined and 0.0 is the conventional answer, and the height is the
    distance from the pole along the minor axis.
    """
    longitude = math.atan2(y, x)
    p = math.hypot(x, y)
    if p == 0.0:
        return (90.0 if z >= 0 else -90.0), math.degrees(longitude), abs(z) - WGS84_B
    theta = math.atan2(z * WGS84_A, p * WGS84_B)
    latitude = math.atan2(z + WGS84_EP2 * WGS84_B * math.sin(theta) ** 3,
                          p - WGS84_E2 * WGS84_A * math.cos(theta) ** 3)
    curvature = WGS84_A / math.sqrt(1.0 - WGS84_E2 * math.sin(latitude) ** 2)
    return (math.degrees(latitude), math.degrees(longitude),
            p / math.cos(latitude) - curvature)


#: Decimal places kept on a derived coordinate. Seven is about 11 mm at the equator — finer than
#: the transform's own error and finer than anything Legion states — and rounding at all is what
#: keeps a golden file stable across platform float formatting.
COORDINATE_DECIMALS = 7
ALTITUDE_DECIMALS = 3


def _coordinates_of(position: Any, crs: str | None) -> tuple[float, float, float | None, str]:
    """One position object plus its CRS -> (lat, lon, alt, basis). Raises on what it cannot read.

    The basis string is not decoration: it is the only record of which of two mutually
    incompatible readings was applied to three bare numbers.
    """
    if not isinstance(position, dict):
        raise ValueError(
            f"Legion position is {type(position).__name__}, expected an object with `type` and "
            "`coordinates` — refusing to guess a coordinate from something that is not one"
        )
    shape = position.get("type")
    coordinates = position.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError(
            f"Legion position has coordinates {coordinates!r}; a fix needs at least two "
            "numbers. Refusing to translate a partial coordinate"
        )
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in coordinates):
        raise ValueError(
            f"Legion position coordinates {coordinates!r} are not all numbers — refusing to "
            "coerce, because a coordinate read out of a string is a coordinate nobody checked"
        )

    stated = crs or CRS_DEFAULT
    if stated in CRS_REFUSED:
        raise ValueError(
            f"Legion states crs {stated!r}, which is in the API's enum and defined in no "
            "document: the prose companion specifies EPSG:4978 and EPSG:4326 only. Its EPSG "
            "registry axis order is (latitude, longitude, height) — the REVERSE of the order "
            "this API documents for EPSG:4326 — so reading it either way yields a plausible "
            "position in the wrong place rather than an error. Refused by name; see "
            "FORMAT_COVERAGE.md"
        )
    if stated == CRS_LLA:
        # The prose companion is explicit: [longitude, latitude, altitude]. Note this is GeoJSON
        # axis order and NOT the EPSG registry's order for 4326, which the API overrides.
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        altitude = float(coordinates[2]) if len(coordinates) > 2 else None
        basis = (f"crs {CRS_LLA} stated; coordinates read as [longitude, latitude, altitude] "
                 "per the Legion prose companion, which overrides the EPSG registry's axis "
                 "order for this code. No conversion applied")
    elif stated == CRS_ECEF:
        if len(coordinates) < 3:
            raise ValueError(
                f"Legion states crs {stated!r} (geocentric X/Y/Z metres) with only "
                f"{len(coordinates)} coordinates: {coordinates!r}. A geocentric position needs "
                "three, and inferring the third would invent a location"
            )
        latitude, longitude, altitude = ecef_to_geodetic(*(float(v) for v in coordinates[:3]))
        latitude, longitude = (round(latitude, COORDINATE_DECIMALS),
                              round(longitude, COORDINATE_DECIMALS))
        altitude = round(altitude, ALTITUDE_DECIMALS)
        basis = (
            f"crs {'stated as ' + stated if crs else 'ABSENT, so ' + CRS_DEFAULT + ' by the '
             'schema default'}; coordinates read as geocentric [X, Y, Z] metres and converted "
            f"to geodetic on the WGS84 ellipsoid (a={WGS84_A} m, 1/f={WGS84_INVERSE_FLATTENING}) "
            "by the closed-form Bowring/Ferrari solution. The source coordinates are re-emitted "
            "verbatim at attributes.legion_position; this Position is a derived one-way view")
    else:
        raise ValueError(
            f"Legion states crs {stated!r}, which is not in the API's enum "
            f"({CRS_ECEF}, {CRS_LLA}, {CRS_LLA_3D}) — refusing to assume a coordinate system, "
            "because the two this adapter reads are mutually incompatible readings of the same "
            "three numbers"
        )

    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        raise ValueError(
            f"Legion position resolves to {latitude}/{longitude} under crs {stated}, which is "
            "outside the world — refusing to place a contact at a coordinate that cannot exist"
        )
    if shape not in GEOMETRY_SHAPES:
        raise ValueError(
            f"Legion position type {shape!r} is not one of {GEOMETRY_SHAPES} — the schema pins "
            "that set with a pattern, so another value is a document this adapter cannot read"
        )
    return latitude, longitude, altitude, basis


# ====================================================================== timestamps


def _instant(document: dict, field: str, *, required: bool) -> _dt.datetime | None:
    """One timestamp field, parsed — or a refusal naming the value and the grammar.

    ABSENT and UNPARSEABLE are different outcomes on purpose. Absent returns None and the caller
    falls back through the documented chain, recording which link it used. Unparseable RAISES:
    an invented instant is unfalsifiable downstream, and the `Adapter` contract forbids a partial
    object, which is exactly what an Event with a clock-supplied `observed_at` would be.
    """
    value = document.get(field)
    if value is None:
        if required and field in document:
            raise ValueError(
                f"Legion document states {field}: null. That is the API asserting it has no "
                "value for a field this translation needs, and there is no honest substitute — "
                "the receipt clock would be our time presented as the source's"
            )
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"Legion {field} is {value!r} ({type(value).__name__}), not a string. The accepted "
            "grammar is RFC 3339 with Z or a numeric offset, any ISO 8601 form, or a naive form "
            "assumed UTC — see FORMAT_COVERAGE.md"
        )
    try:
        return times.parse(value)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Legion {field} is {value!r}, which is not a time this adapter can parse. The "
            "accepted grammar is RFC 3339 with Z (2026-04-29T06:11:20Z), RFC 3339 with a "
            "numeric offset, any ISO 8601 form datetime.fromisoformat accepts, or a naive form "
            "which is assumed UTC. The whole document is refused rather than stamped with an "
            "invented instant: a fabricated time is unfalsifiable downstream, where a refused "
            f"document is visible to the caller. Parse error: {e}"
        ) from e


def _naive(value: Any) -> bool:
    """Whether a timestamp string carried no zone, so UTC was ASSUMED rather than read."""
    return isinstance(value, str) and not (
        value.endswith(("Z", "z")) or "+" in value[10:] or "-" in value[10:])


# ====================================================================== absence


def _stated_null(document: dict, *, prefix: str = "") -> list[str]:
    """Keys the document states as `null` — the JSON-native sentinel, and nothing else.

    A key that is ABSENT is not here, and that is the whole point: `required` in OpenAPI
    constrains the document rather than the world, so a required-and-nullable field carrying null
    is the API asserting "you will always be told, and the answer is nothing". An absent key is
    the API not having said. Collapsing the two would manufacture assertions Legion never made.

    Nested one level into the two blocks Legion embeds, because a null inside `location_latest`
    is as much a statement as one at the top.
    """
    found = []
    for key, value in document.items():
        path = f"{prefix}{key}"
        if value is None:
            found.append(path)
        elif isinstance(value, dict) and key in ("location_latest", "entity", "paging"):
            found += _stated_null(value, prefix=f"{path}.")
    return sorted(found)


# ====================================================================== translation


class LegionAdapter(Adapter):
    """Legion API response documents in, CDM objects out. No HTTP, no auth, no pagination."""

    name = "legion"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    TRANSFORMS = {
        "bearing": "degrees, and the schema admits 360 inclusive while Kinematics.course_deg is "
                   "[0, 360). 360 is reduced to 0 — the same bearing, and the only one the "
                   "field can hold — exactly as the CoT adapter reduces detail/track/@course. "
                   "Every other value passes through unchanged",
        "created_at": "re-rendered to the CDM's fixed-millisecond UTC form, a declared "
                      "transform: Legion states 2026-04-29T06:11:23Z and the CDM emits "
                      "2026-04-29T06:11:23.000Z. The same instant, a different string",
        "recorded_at": "re-rendered to fixed milliseconds, as created_at",
        "expires_at": "re-rendered to fixed milliseconds, as created_at — it becomes valid_to, "
                      "so the raw string is not parked separately",
        "deleted_at": "re-rendered to fixed milliseconds, as created_at — it becomes valid_to",
        "event_timestamp": "re-rendered to fixed milliseconds, as created_at",
    }

    # Dotted paths this adapter maps to canonical fields or places under a name of its own.
    # Everything else is collected by `lossless.residual()` and parked with its structure intact.
    #
    # Note what is NOT here and why that is the design working: `position` and `crs` are absent,
    # so the source coordinates park automatically and verbatim — which is what lets the
    # coordinate conversion stay out of TRANSFORMS entirely. A verbatim copy is not a hole.
    CONSUMED = (
        "id",
        "organization_id",
        "name",
        "category",
        "affiliation",
        "top_classification_probability",
        "created_at",
        "deleted_at",
        "expires_at",
        "recorded_at",
        "bearing",
        "entity_id",
        "source_id",
        "event_type",
        "event_timestamp",
    )

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One Legion response document -> CDM objects. Raises on one it cannot translate."""
        document = self._as_document(raw)
        kind = self._kind(document)
        if kind == "locations_list":
            return self._from_locations_list(document)
        if kind == "location":
            return self._from_location(document)
        if kind == "event":
            return self._from_event(document)
        return self._from_entity(document)

    def _kind(self, document: dict) -> str:
        """Which document this is, from its own shape rather than a caller-supplied tag.

        A tag would be a second source of truth about what we are holding, and the two would
        disagree eventually — on the day someone wires the wrong constant to a search response.
        The discriminators are the fields each schema makes `required`, tested in order of
        specificity.
        """
        if isinstance(document.get("results"), list) and "paging" in document:
            return "locations_list"
        if "position" in document and "entity_id" in document:
            return "location"
        if "event_timestamp" in document and "event_type" in document:
            return "event"
        if "category" in document and "affiliation" in document:
            return "entity"
        raise ValueError(
            "Legion document matches none of the four shapes in scope. Expected a locations "
            "list (results + paging), a location (position + entity_id), an event "
            "(event_timestamp + event_type) or an entity (category + affiliation); got keys "
            f"{sorted(document)}. Tasking, feed data, video, notifications, permissions and "
            "federation are out of scope by name — see FORMAT_COVERAGE.md"
        )

    # ---------------------------------------------------------------- entity doc

    def _from_entity(self, document: dict) -> list[CDMBase]:
        """An Entity document -> [Entity], plus an Event when a location is embedded."""
        entity_id = _identifier(document, "id")
        location = document.get("location_latest")
        received_at = self.now()

        observed_at, observed_basis = self._entity_instant(document, location)
        entity = self._entity(document, location, observed_at, observed_basis,
                             embedded=False, parsed=document)
        if not isinstance(location, dict):
            return [entity]
        return [entity, self._location_event(location, entity, document, received_at,
                                             report_id=location.get("id") or entity_id)]

    def _entity_instant(self, document: dict, location: Any) -> tuple[_dt.datetime, str]:
        """`valid_from`: the embedded location's own instant where there is one, else creation.

        The fallback CHAIN is recorded rather than the result alone, because "the entity was
        first seen then" and "the record was created then" are different claims and only one of
        them is about the world.
        """
        if isinstance(location, dict):
            for field in ("recorded_at", "created_at"):
                stamp = _instant(location, field, required=False)
                if stamp is not None:
                    return stamp, (f"embedded location_latest.{field}"
                                   + (" (UTC assumed: the value carried no zone)"
                                      if _naive(location.get(field)) else ""))
        stamp = _instant(document, "created_at", required=True)
        if stamp is None:
            raise ValueError(
                "Legion entity document states no created_at and embeds no located instant, so "
                "there is nothing to set valid_from from. The receipt clock would be our time "
                "presented as the entity's, which is the one thing this adapter will not do"
            )
        return stamp, ("entity created_at — the record's creation instant, the entity itself "
                       "states no observation time and none was invented")

    # -------------------------------------------------------------- location doc

    def _from_location(self, document: dict) -> list[CDMBase]:
        """A Location document -> [Entity, Event], or [Event] when no entity block is embedded.

        The Entity is translated from the EMBEDDED block only. Where Legion did not embed one,
        no Entity is emitted: the document names an entity id and says nothing else about it, and
        an object built from an id alone would be six invented fields wearing a uuid. The Event
        still carries the derived id in `related_entities`, so fusion can join it later.
        """
        received_at = self.now()
        embedded = document.get("entity")
        observed_at, observed_basis = self._location_instant(document)

        if not isinstance(embedded, dict):
            event = self._location_event(document, None, document, received_at,
                                         report_id=_identifier(document, "id"),
                                         related=_identifier(document, "entity_id"),
                                         observed=(observed_at, observed_basis))
            return [event]

        entity = self._entity(embedded, document, observed_at, observed_basis,
                             embedded=True, parsed=document)
        return [entity, self._location_event(document, entity, document, received_at,
                                             report_id=_identifier(document, "id"),
                                             observed=(observed_at, observed_basis))]

    def _location_instant(self, location: dict) -> tuple[_dt.datetime, str]:
        """`observed_at` for a location: `recorded_at`, else `created_at`. Never the clock."""
        stamp = _instant(location, "recorded_at", required=False)
        if stamp is not None:
            return stamp, ("location recorded_at — when the source recorded the fix"
                           + (" (UTC assumed: the value carried no zone)"
                              if _naive(location.get("recorded_at")) else ""))
        stamp = _instant(location, "created_at", required=True)
        if stamp is None:
            raise ValueError(
                "Legion location states neither recorded_at nor created_at, so there is no "
                "instant to attribute the fix to and none will be invented"
            )
        return stamp, ("location created_at — recorded_at was absent, so this is when LEGION "
                       "stored the fix rather than when the source took it")

    # ----------------------------------------------------------------- event doc

    def _from_event(self, document: dict) -> list[CDMBase]:
        """A Legion Event document -> [Event]. No entity, and no geometry."""
        received_at = self.now()
        observed_at = _instant(document, "event_timestamp", required=True)
        source_id = _identifier(document, "source_id")
        event_class = document.get("event_type")

        payload = {
            # The name collision is the finding: Legion's `event_type` says WHAT was detected,
            # the CDM's says what kind of report this is. Parked, never mapped across.
            "legion_event_class": event_class,
            "legion_event_class_is_a_detection_class": event_class in LEGION_EVENT_CLASSES,
            "legion_organization_id": document.get("organization_id"),
            "legion_actor_id": document.get("actor_id"),
            # An actor is not the subject, and a USER is not a CDM object at all, so the actor
            # stays out of related_entities however tempting the uuid looks.
            "legion_actor_type": document.get("actor_type"),
            "legion_event_description": document.get("event_description"),
            "legion_metadata": document.get("metadata"),
            "event_type_basis": (
                "DETECTION. Legion's own event_type names the detected CLASS "
                f"({event_class!r}), not the kind of report, so the CDM's axis is supplied here "
                "and the source value is parked"),
            "observed_at_basis": (
                "event_timestamp"
                + (" (UTC assumed: the value carried no zone)"
                   if _naive(document.get("event_timestamp")) else "")),
            "received_at_basis": (
                "the injected clock. A Legion document carries created_at — when LEGION stored "
                "the record — which is the platform's receipt and not ours"),
            "legion_created_at": _rendered(document.get("created_at")),
            "severity_basis": (
                "INFO. Legion states no severity or urgency field on any resource; grading a "
                f"{event_class!r} would be this translator judging operational significance, "
                "which belongs to fusion where it is visible and attributable"),
            "source_extras": lossless.residual(document, self.CONSUMED),
        }
        return [Event(
            source=self.source_ref(),
            source_ids=[{"system": SYSTEM, "external_id": _identifier(document, "id")}],
            event_id=ids.derive(SYSTEM, _identifier(document, "id"), kind="event"),
            event_type=EventType.DETECTION,
            severity=Severity.INFO,
            related_entities=[ids.derive(SYSTEM, source_id, kind="entity")],
            # A Legion Event carries no position whatsoever. Taking one from the entity it names
            # would be both a join and an invention.
            geometry=None,
            payload={k: v for k, v in payload.items() if v is not None},
            observed_at=observed_at,
            received_at=received_at,
        )]

    # ------------------------------------------------------------ locations list

    def _from_locations_list(self, document: dict) -> list[CDMBase]:
        """A locations list -> [Entity, Track]. One page, one Track, completeness recorded.

        The Entity is emitted because the CDM cannot state a track without the entity it belongs
        to, and because it is the only object with an extension bag to record completeness in —
        `Track` has none. Its type and affiliation are UNKNOWN and the basis says why: a list
        asserts that these locations belong to this id and nothing else about the object.
        """
        results = document.get("results") or []
        if not results:
            raise ValueError(
                "Legion locations list carries an empty `results` array. A CDM Track requires "
                "at least one sample, and a Track with no samples would be a history asserting "
                "nothing — the caller is holding an empty page, which is not a translation "
                "failure but is also not a track"
            )
        envelope_crs = document.get("crs")
        entity_ids = {r.get("entity_id") for r in results if isinstance(r, dict)}
        if len(entity_ids) != 1 or None in entity_ids:
            raise ValueError(
                f"Legion locations list spans {len(entity_ids)} entity ids ({sorted(str(e) for e in entity_ids)}). "
                "One page is one entity's history: a Track addresses one entity, and building "
                "one from a mixed page would merge two objects into one track"
            )
        legion_entity_id = str(entity_ids.pop())

        samples, positions = [], []
        for index, result in enumerate(results):
            if not isinstance(result, dict):
                raise ValueError(f"Legion locations list result {index} is not an object")
            latitude, longitude, altitude, basis = _coordinates_of(
                result.get("position"), result.get("crs") or envelope_crs)
            observed_at, _ = self._location_instant(result)
            positions.append((latitude, longitude, altitude, basis))
            samples.append(TrackSample(
                position=Position(lat=latitude, lon=longitude, alt_m=altitude,
                                  position_source=PositionSource.ESTIMATED, accuracy_m=None),
                observed_at=observed_at,
            ))

        entity_uuid = ids.derive(SYSTEM, legion_entity_id, kind="entity")
        # Keyed on the entity AND the page's own span, so two pages of one history do not
        # collapse into one track id — the same reason an AIS event id is not keyed on the MMSI
        # alone.
        span = f"{times.render(samples[0].observed_at)}..{times.render(samples[-1].observed_at)}"
        track_uuid = ids.derive(SYSTEM, f"{legion_entity_id}@{span}", kind="track")

        completeness = _completeness(document, len(samples), track_uuid)
        latest = positions[-1]
        attributes = {
            "legion_entity_id": legion_entity_id,
            "legion_crs": envelope_crs,
            "legion_position": [
                _verbatim_position(r.get("position"), r.get("crs") or envelope_crs)
                for r in results
            ],
            "position_basis": latest[3],
            "legion_track_completeness": completeness,
            "entity_id_basis": "Legion entity id, from the locations the page carries",
            "entity_type_basis": (
                "UNKNOWN. A locations list asserts that these fixes belong to this entity id "
                "and states nothing else about the object — no category, no name, no "
                "affiliation. Fetching the entity would be a second request and therefore "
                "fusion, so nothing is inferred"),
            "affiliation_basis": (
                "UNKNOWN. As entity_type_basis: the list states no affiliation, and this is the "
                "format's silence rather than a collapsed vocabulary"),
            "symbol_basis": "derived from affiliation; a locations list states no symbol",
            "valid_from_basis": "the first sample's instant on this page",
            # Pruned per-index and NOT as `results` wholesale, which is what the first version
            # did — and the harness caught it immediately: pruning the array dropped every
            # sample's id, `source`, timestamps and `position.type`, none of which has a
            # canonical home and all of which the never-drop rule keeps. Only the coordinates
            # `legion_position` re-emits verbatim above are pruned, so nothing is both parked
            # twice and nothing is lost once.
            "source_extras": lossless.residual(
                document,
                ["crs"] + [f"results[{i}].position.coordinates" for i in range(len(results))]),
        }
        entity = Entity(
            source=self.source_ref(),
            entity_id=entity_uuid,
            source_ids=[{"system": SYSTEM, "external_id": legion_entity_id}],
            entity_type=EntityType.UNKNOWN,
            affiliation=Affiliation.UNKNOWN,
            symbol=sidc_from_affiliation(Affiliation.UNKNOWN, synthetic=self._synthetic),
            position=Position(lat=latest[0], lon=latest[1], alt_m=latest[2],
                              position_source=PositionSource.ESTIMATED, accuracy_m=None),
            kinematics=None,
            valid_from=samples[0].observed_at,
            valid_to=None,
            confidence=None,
            attributes={k: v for k, v in attributes.items() if v is not None},
        )
        track = Track(
            source=self.source_ref(),
            source_ids=[{"system": SYSTEM, "external_id": legion_entity_id}],
            track_id=track_uuid,
            entity_id=entity_uuid,
            samples=samples,
            # Legion states no track quality. top_classification_probability is a classification
            # confidence and a different claim, so this stays None rather than borrowing it.
            track_quality=None,
        )
        return [entity, track]

    # ------------------------------------------------------------------ builders

    def _entity(self, source_entity: dict, location: Any, observed_at: _dt.datetime,
                observed_basis: str, *, embedded: bool, parsed: dict) -> Entity:
        """One Legion entity block -> a CDM Entity. Shared by all three paths that produce one."""
        legion_id = _identifier(source_entity, "id")
        affiliation_raw = source_entity.get("affiliation")
        affiliation, affiliation_basis = _affiliation(affiliation_raw)
        category = source_entity.get("category")
        valid_to, valid_to_basis = _valid_to(source_entity)

        position = position_basis = None
        if isinstance(location, dict) and location.get("position") is not None:
            latitude, longitude, altitude, position_basis = _coordinates_of(
                location.get("position"), location.get("crs"))
            position = Position(
                lat=latitude, lon=longitude, alt_m=altitude,
                # Legion's `source` names the SYSTEM that produced the fix, never how it was
                # obtained, so there is nothing here to read a positioning method off.
                # ESTIMATED understates, which is the safe direction for the field a commander
                # uses to tell a fix from a guess.
                position_source=PositionSource.ESTIMATED,
                # NOT the covariance and NOT the radius: one is a matrix in an undocumented
                # frame and the other is ambiguous between an error and an extent. Both parked.
                accuracy_m=None,
            )

        attributes: dict[str, Any] = {
            "legion_organization_id": source_entity.get("organization_id"),
            "legion_parent_id": source_entity.get("parent_id"),
            "legion_name": source_entity.get("name"),
            "legion_type": source_entity.get("type"),
            "legion_status": source_entity.get("status"),
            "legion_category": category,
            "legion_affiliation": affiliation_raw,
            "legion_top_classification": source_entity.get("top_classification"),
            "legion_classification": source_entity.get("classification"),
            "legion_metadata": source_entity.get("metadata"),
            "legion_is_active": source_entity.get("is_active"),
            "legion_is_expired": source_entity.get("is_expired"),
            "legion_updated_at": _rendered(source_entity.get("updated_at")),
            "affiliation_basis": affiliation_basis,
            "affiliation_exercise": _exercise_marking(affiliation_raw),
            "entity_type_basis": _category_basis(category),
            "symbol_basis": "derived from affiliation; Legion states no symbol",
            "entity_id_basis": "Legion entity id",
            "valid_from_basis": observed_basis,
            "valid_to_basis": valid_to_basis,
            "position_basis": position_basis,
            "position_source_basis": (
                "ESTIMATED. Legion's location `source` names the SYSTEM that produced the fix "
                f"({(location or {}).get('source')!r}) and never the positioning method, so "
                "there is nothing to read a method from. ESTIMATED understates rather than "
                "overstates, which is the safe direction for this field"
                if position is not None else None),
            "unavailable_fields": _stated_null(parsed),
            "export_review": _export_review(source_entity),
            "source_extras": lossless.residual(parsed, self.CONSUMED),
        }
        if isinstance(location, dict):
            attributes["legion_position"] = _verbatim_position(location.get("position"),
                                                               location.get("crs"))
            attributes["legion_location_id"] = location.get("id")
        if embedded:
            attributes["embedded_entity_basis"] = (
                "this entity was read from the `entity` block embedded in a location document, "
                f"which is a SUBSET of the standalone Entity schema: {', '.join(EMBEDDED_ENTITY_OMITS)} "
                "are absent from this endpoint's schema entirely. That is a fact about the API's "
                "shape and NOT a claim that Legion does not know them — they are deliberately "
                "kept out of unavailable_fields, and the standalone entity endpoint carries them"
            )

        return Entity(
            source=self.source_ref(),
            entity_id=ids.derive(SYSTEM, legion_id, kind="entity"),
            source_ids=[{"system": SYSTEM, "external_id": legion_id}],
            entity_type=CATEGORY.get(str(category), EntityType.UNKNOWN),
            affiliation=affiliation,
            symbol=sidc_from_affiliation(affiliation, synthetic=self._synthetic),
            position=position,
            kinematics=_kinematics(location),
            valid_from=observed_at,
            valid_to=valid_to,
            confidence=_confidence(source_entity),
            attributes={k: v for k, v in attributes.items() if v is not None},
        )

    def _location_event(self, location: dict, entity: Entity | None, parsed: dict,
                        received_at: _dt.datetime, *, report_id: str,
                        related: str | None = None,
                        observed: tuple[_dt.datetime, str] | None = None) -> Event:
        """One Legion location -> the Event that reports it. No geometry: the fix is the entity's."""
        observed_at, observed_basis = observed or self._location_instant(location)
        related_uuid = (entity.entity_id if entity is not None
                        else ids.derive(SYSTEM, related or _identifier(location, "entity_id"),
                                        kind="entity"))
        payload = {
            "legion_location_id": location.get("id"),
            "legion_source": location.get("source"),
            "legion_created_at": _rendered(location.get("created_at")),
            "observed_at_basis": observed_basis,
            "received_at_basis": (
                "the injected clock. Legion's created_at is when the PLATFORM stored the "
                "record, which is its receipt and not ours"),
            "event_type_basis": (
                "TRACK_UPDATE. A location document reports where something was at an instant, "
                "which is what that member means"),
            "severity_basis": (
                "INFO. Legion states no severity on any resource, so this is the format's "
                "silence and not an assessment that nothing is wrong"),
            "entity_block_embedded": entity is not None,
        }
        if entity is None:
            payload["entity_basis"] = (
                "the location document embedded no `entity` block, so no Entity was emitted: "
                "the document names an entity id and says nothing else about the object, and "
                "one built from an id alone would be invented fields wearing a uuid. Resolving "
                "it is a second request and therefore fusion"
            )
        return Event(
            source=self.source_ref(),
            source_ids=[{"system": SYSTEM, "external_id": report_id}],
            event_id=ids.derive(SYSTEM, report_id, kind="event"),
            event_type=EventType.TRACK_UPDATE,
            severity=Severity.INFO,
            related_entities=[related_uuid],
            geometry=None,
            payload={k: v for k, v in payload.items() if v is not None},
            observed_at=observed_at,
            received_at=received_at,
        )

    # ------------------------------------------------------------------ helpers

    def _as_document(self, raw: bytes | dict) -> dict:
        """A parsed dict, or JSON text. Nothing else — this adapter does not fetch."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray, str)):
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            document = json.loads(text)
            if not isinstance(document, dict):
                raise ValueError(
                    f"Legion payload is a JSON {type(document).__name__}, not an object. Every "
                    "in-scope response is a single object — a bare array is not one of the four "
                    "documents in scope"
                )
            return document
        raise TypeError(
            f"Legion adapter takes a parsed dict or JSON text as bytes or str, got "
            f"{type(raw).__name__}. It does not take a URL, a session or a response object: "
            "transport stays with the caller"
        )


# ---------------------------------------------------------------- field helpers


def _identifier(document: dict, field: str) -> str:
    """A required identifier, or a refusal. An object with no id cannot be recognised twice."""
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Legion document has {field}={value!r}; a non-empty string identifier is required. "
            "It is what the CDM id is derived from, so an object without one could never be "
            "recognised as the same object twice"
        )
    return value


def _rendered(value: Any) -> str | None:
    """A source timestamp string kept VERBATIM, not re-rendered.

    The CDM's canonical fields carry the parsed instant; this keeps the string Legion actually
    sent, so the exact form survives — `…06:11:23Z` does not silently become `…06:11:23.000Z`
    in the only copy.
    """
    return value if isinstance(value, str) else None


def _verbatim_position(position: Any, crs: Any) -> dict[str, Any]:
    """The source coordinates exactly as Legion sent them — the record the Position derives from.

    `crs` is present here only when the document STATED one. An absent `crs` is not recorded as
    `null`, because this adapter spends a docstring insisting that absent and null are different
    facts and it would be odd to conflate them in its own output. The interpretation that was
    actually applied is in `position_basis`, which names the default explicitly.
    """
    verbatim: dict[str, Any] = {
        "coordinates": (position or {}).get("coordinates") if isinstance(position, dict) else None,
        "type": (position or {}).get("type") if isinstance(position, dict) else None,
    }
    if crs is not None:
        verbatim["crs"] = crs
    return {k: v for k, v in verbatim.items() if v is not None}


def _affiliation(raw: Any) -> tuple[Affiliation, str]:
    """Legion's fifteen-value enum -> one of the CDM's four, with the reasoning recorded."""
    if not isinstance(raw, str) or raw not in AFFILIATION:
        return Affiliation.UNKNOWN, (
            f"Legion affiliation {raw!r} is not one of the fifteen values in the API's enum, so "
            "it is read as UNKNOWN rather than guessed at. The raw value is parked at "
            "attributes.legion_affiliation")
    mapped = AFFILIATION[raw]
    note = (f"Legion affiliation {raw!r} -> {mapped.value}; the source vocabulary is fifteen "
            "values wide and the CDM's is four, so the original is parked at "
            "attributes.legion_affiliation and the collapse is recoverable")
    if raw in ("ASSUMED_FRIEND", "EXERCISE_ASSUMED_FRIEND"):
        note += ". Deliberately NOT FRIENDLY: an assumption is not an identification"
    if raw == "SUSPECT":
        note += ". Deliberately NOT HOSTILE: suspicion is not identification"
    if raw in AFFILIATION_EXERCISE_EXTRA:
        note += (f". {raw} is an exercise-only value for a friendly acting hostile and is "
                 "treated hostile, as CoT's j and k letters are")
    return mapped, note


def _exercise_marking(raw: Any) -> dict[str, Any] | None:
    """The exercise fact Legion folds into its affiliation enum, recorded SEPARATELY.

    `source.synthetic` is NOT touched, and the distinction is the point. That flag describes the
    FEED — is this an exercise system — and is a deployment declaration set once at construction.
    This describes the OBJECT: is this contact a simulated participant. A live Legion instance
    can hold both during a rehearsal, and letting payload content rewrite a provenance flag
    would be an adapter making a decision about provenance, which adapters may not do.
    """
    if not isinstance(raw, str):
        return None
    marked = raw.startswith(AFFILIATION_EXERCISE_PREFIX) or raw in AFFILIATION_EXERCISE_EXTRA
    if not marked:
        return None
    return {
        "legion_affiliation": raw,
        "basis": ("Legion folds an exercise marking into its affiliation enum. The CDM separates "
                  "identity from context, so the affiliation carries the identity and this "
                  "records the context. source.synthetic is deliberately NOT changed by it: that "
                  "flag is a declaration about the feed, not a fact about one contact"),
    }


def _category_basis(category: Any) -> str:
    """Why this category became the entity type it did — including when it became UNKNOWN."""
    mapped = CATEGORY.get(str(category))
    if mapped is None:
        return (f"Legion category {category!r} is not one of the ten values in the API's enum, "
                "so the entity type is UNKNOWN rather than guessed")
    if mapped is not EntityType.UNKNOWN:
        return f"Legion category {category!r} -> {mapped.value}; the raw value is parked"
    return (
        f"Legion category {category!r} -> UNKNOWN deliberately. DETECTION, ALERT and TRACK name "
        "a report ABOUT something rather than a thing that exists; WEATHER is a phenomenon the "
        "CDM does not model as an entity; DEVICE is Legion's generic bucket and is as easily a "
        "radio or a battery as a sensor. Mapping any of them to a specific member would be this "
        "translator inventing a category, and the raw value is parked")


def _valid_to(source_entity: dict) -> tuple[_dt.datetime | None, str | None]:
    """`valid_to` from a deletion or an expiry, and which one won.

    A deletion is a FACT and an expiry is a SCHEDULE, so a stated `deleted_at` wins when both
    are present — and the basis says so, because a consumer comparing two objects needs to know
    which kind of end it is looking at.
    """
    deleted = _instant(source_entity, "deleted_at", required=False)
    if deleted is not None:
        note = "Legion deleted_at — a soft-delete instant IS an interval end"
        if source_entity.get("expires_at"):
            note += (", and it wins over the expires_at also present: a deletion is a fact, an "
                     "expiry is a schedule")
        return deleted, note
    expires = _instant(source_entity, "expires_at", required=False)
    if expires is not None:
        return expires, ("Legion expires_at — a scheduled end, used because no deleted_at was "
                         "stated. Note it may be in the future, which is what an expiry is")
    return None, None


def _confidence(source_entity: dict) -> float | None:
    """`top_classification_probability` -> `confidence`, and absent means unknown.

    Never 0.0 for an absent value: confidence 0 is certainty-that-not, which is a claim. A value
    outside 0..1 is refused rather than clamped — clamping 1.4 to 1.0 would turn a source defect
    into a confident maximum.
    """
    value = source_entity.get("top_classification_probability")
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(
            f"Legion top_classification_probability is {value!r}, not a number — refusing to "
            "coerce a confidence out of it"
        )
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(
            f"Legion top_classification_probability is {value}, outside 0..1. Refusing to clamp: "
            "a clamped 1.4 becomes a confident maximum and hides a source defect"
        )
    return float(value)


#: The schema admits 360 inclusive; `Kinematics.course_deg` is [0, 360).
BEARING_FULL_CIRCLE = 360.0


def _kinematics(location: Any) -> Kinematics | None:
    """Motion, which for Legion is a bearing and nothing else.

    `speed` is deliberately NOT read. Its units are documented nowhere, and the schema's own
    `speed` and `velocity` examples contradict each other — 2.236 against a vector of magnitude
    42.6 — so there is no way to infer them and no honest way to write a number into
    `speed_mps`. It is parked. The vectors (`velocity`, `acceleration`, `angular_velocity`,
    `orientation`) are parked for the same reason plus a second: their reference frame is
    undocumented too, and ECEF against local east-north-up gives completely different answers
    for the same three numbers. This is the ADS-B altitude lesson applied before the fact.
    """
    if not isinstance(location, dict):
        return None
    bearing = location.get("bearing")
    if not isinstance(bearing, (int, float)) or isinstance(bearing, bool):
        return None
    course = float(bearing)
    if course == BEARING_FULL_CIRCLE:
        # The same bearing, and the only one the field can hold — as the CoT adapter does.
        course = 0.0
    if not 0.0 <= course < BEARING_FULL_CIRCLE:
        raise ValueError(
            f"Legion bearing is {bearing}, outside the schema's own 0..360 range — refusing to "
            "wrap it, because a wrapped bearing is a plausible wrong direction"
        )
    return Kinematics(speed_mps=None, course_deg=course, climb_mps=None)


def _completeness(document: dict, carried: int, track_uuid: Any) -> dict[str, Any]:
    """How much of a history this page carries, so a consumer can machine-read it.

    Recorded on the ENTITY rather than the Track, because `Track` has no extension bag — see the
    completeness section in FORMAT_COVERAGE.md for why the three alternatives were worse. A
    consumer holding both objects can tell a fragment from a whole history; one holding only the
    Track cannot, and that is a limit of the model rather than of this translation.

    `complete` is None unless it can be established, never False. "We cannot tell" and "we can
    tell it is partial" are different answers and only one of them is a finding.
    """
    paging = document.get("paging") if isinstance(document.get("paging"), dict) else {}
    total = document.get("total_count")
    has_more = paging.get("has_more")
    complete: bool | None = None
    if isinstance(total, int):
        complete = total == carried and has_more is not True
    elif has_more is True:
        complete = False
    return {
        "track_id": str(track_uuid),
        "total_count": total,
        "carried_samples": carried,
        "complete": complete,
        "paging": paging or None,
        "basis": (
            "carried_samples is the length of this page's results; total_count is the "
            "collection size Legion stated, or null where it stated none. complete is true only "
            "when both agree and paging.has_more is not set, and null when it cannot be "
            "established — never false on missing evidence. This adapter does not follow "
            "paging.next: one page is one payload, and stitching pages is state"),
    }


def _export_review(source_entity: dict) -> dict[str, Any] | None:
    """Keys present on this object whose contents a release boundary should look at.

    Flagged, never filtered. `metadata` is a free-form bag whose own schema example carries an IP
    address, a manufacturer and a model — infrastructure detail about our estate rather than an
    observation of the world. Dropping it here would be a translator making a release decision
    invisibly, which belongs to the gateway; saying nothing would leave it to be found by
    accident.
    """
    present = [key for key in EXPORT_REVIEW_KEYS if source_entity.get(key) not in (None, {}, "")]
    if not present:
        return None
    return {
        "keys": present,
        "basis": ("free-form vendor content that may describe our own estate rather than the "
                  "world — the API's own example for `metadata` carries an ip_address, a "
                  "manufacturer and a model. Parked in full because the never-drop rule is not "
                  "negotiable, and flagged so a deployment reviews it before a CDM object "
                  "crosses a releasability boundary. This adapter does not filter it"),
    }
