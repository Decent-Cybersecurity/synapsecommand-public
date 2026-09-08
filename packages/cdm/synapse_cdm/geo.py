"""GeoJSON geometry, restricted to what the CDM needs, in WGS84 decimal degrees.

THE COORDINATE ORDER TRAP
-------------------------
GeoJSON (RFC 7946) orders coordinates [LONGITUDE, LATITUDE]. Nearly everything a human
writes, and `Position` in this very package, orders them (lat, lon). That inversion is the
single most common defect in an integration layer, it is silent, and its symptom is a contact
in the wrong hemisphere — 24.1E 57.5N is in the Baltic, 57.5E 24.1N is in Saudi Arabia.

Two things guard it here. `Point.lat` / `.lon` are the only accessors adapter code should use,
so no adapter needs to remember the order; and the validators below reject a latitude outside
[-90, 90], which catches the swap for every coordinate outside the equatorial band where both
readings happen to be legal. The remaining band is covered by fixture tests.

WHY ONLY Point / LineString / Polygon
-------------------------------------
Those three cover Cursor-on-Target's point and shape drawings, STANAG 4676's track geometry,
and the jamming-area polygons PNTMAP emits. MultiPolygon and GeometryCollection are not here
because nothing consumes them yet; adding one is a MINOR bump, and a `type` the CDM does not
know is REFUSED rather than passed through, so an unsupported geometry fails loudly at the
adapter instead of arriving as an unrenderable blob on a map.

**CORRECTED 2026-09-08, round P3 (SOIF Part 1, R03).** The paragraph above is kept as written
because its rule still holds — an unknown `type` is refused, and a widening is a MINOR bump —
but its list is no longer this module's list. `MultiPoint`, `MultiLineString` and `MultiPolygon`
are now in the union, and the "nothing consumes them yet" clause is what stopped being true:
GeoJSON sources send them directly, KML's `MultiGeometry` of like parts is exactly a Multi*, and
AIXM airspace is routinely several disjoint lateral parts. The alternative for an adapter meeting
one was to emit several objects that a consumer could not tell were one thing, or to merge them
into a Polygon whose rings would then read as holes. Both invent structure the source did not
send, which is the thing this package refuses to do.

`GeometryCollection` is DELIBERATELY still absent, and this is a decision rather than a gap.
A collection is heterogeneous — a point and a polygon and a line in one value — so it has no
single geometry semantics for a consumer to act on: "draw this", "is my position inside it",
"how long is it" all stop having one answer. RFC 7946 §3.1.8 itself advises against using one
where a single-type geometry will do, and every case the formats in scope actually produce is
homogeneous, which is what the three Multi* types are for. An object that genuinely needs mixed
geometry is more than one canonical object, and saying so keeps the count of things on the map
equal to the count of things the source described.

THE COORDINATE REFERENCE SYSTEM, STATED ONCE
--------------------------------------------
Every coordinate in this module, and every coordinate in `models.Position`, is WGS84 decimal
degrees — the CRS RFC 7946 §4 fixes for GeoJSON and the only CRS the canonical form has. There
is no `crs` field and there will not be one: a per-object CRS makes every consumer a coordinate
transformation library, and the transformation it would have to perform is exactly the one an
adapter is in a position to do correctly, once, with the source's own parameters to hand. So an
adapter CONVERTS to WGS84 or REFUSES the payload; it never labels a UTM easting as a longitude
and it never passes a national grid reference through. §25's rule, in one sentence: adapters are
responsible for explicit source mapping.

Two coordinate ORDERS live in this repository and there is no third:

    geo.Point/LineString/Polygon/Multi*   `coordinates` is [lon, lat] — GeoJSON, RFC 7946 §3.1.1
    models.Position                       named fields `lat` and `lon` — order cannot be got wrong

`BoundingBox` below is the third shape and it uses the SECOND convention's discipline for the
first convention's reason: its four bounds are NAMED (`min_lon`, `min_lat`, `max_lon`, `max_lat`)
rather than a four-element array, because RFC 7946 §5's bbox array is [west, south, east, north]
and a reader who assumes [south, west, north, east] gets a box in the wrong hemisphere with no
validator able to tell. A name cannot be transposed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from synapse_cdm.enums import VerticalReference, VerticalUnit

STRICT = ConfigDict(extra="forbid")


def _check_lonlat(pair: list[float]) -> list[float]:
    if not 2 <= len(pair) <= 3:
        raise ValueError("a GeoJSON coordinate is [lon, lat] or [lon, lat, alt]")
    lon, lat = float(pair[0]), float(pair[1])
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude {lon} outside [-180, 180]")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(
            f"latitude {lat} outside [-90, 90] — the usual cause is [lat, lon] order; "
            "GeoJSON is [lon, lat] (RFC 7946)"
        )
    return [lon, lat] + list(pair[2:])


class Point(BaseModel):
    model_config = STRICT
    type: Literal["Point"] = "Point"
    coordinates: list[float]

    @field_validator("coordinates")
    @classmethod
    def _valid(cls, v: list[float]) -> list[float]:
        return _check_lonlat(v)

    @property
    def lon(self) -> float:
        return self.coordinates[0]

    @property
    def lat(self) -> float:
        return self.coordinates[1]


class LineString(BaseModel):
    model_config = STRICT
    type: Literal["LineString"] = "LineString"
    coordinates: list[list[float]] = Field(min_length=2)

    @field_validator("coordinates")
    @classmethod
    def _valid(cls, v: list[list[float]]) -> list[list[float]]:
        return [_check_lonlat(p) for p in v]


class Polygon(BaseModel):
    model_config = STRICT
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def _valid(cls, v: list[list[list[float]]]) -> list[list[list[float]]]:
        return [[_check_lonlat(p) for p in ring] for ring in v]

    @model_validator(mode="after")
    def _closed(self) -> "Polygon":
        """RFC 7946 requires a linear ring to be closed — first position equals last.

        Enforced rather than repaired. A ring that arrives open is a source or adapter defect,
        and silently closing it invents an edge the source never stated: for a jamming
        footprint that means inventing coverage, which is the wrong direction to guess in.
        """
        for index, ring in enumerate(self.coordinates):
            if len(ring) < 4:
                raise ValueError(
                    f"ring {index} has {len(ring)} positions; a closed linear ring needs "
                    "at least 4 (RFC 7946)"
                )
            if ring[0] != ring[-1]:
                raise ValueError(
                    f"ring {index} is not closed: first position {ring[0]} != last {ring[-1]}"
                )
        return self


class MultiPoint(BaseModel):
    """Several points that are ONE thing — a scatter of detections from one report.

    Not a list of `Point` objects, because a list of geometries is a list of objects and this is
    one object with a discontinuous location. The difference is visible the moment a consumer
    counts contacts.
    """
    model_config = STRICT
    type: Literal["MultiPoint"] = "MultiPoint"
    coordinates: list[list[float]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def _valid(cls, v: list[list[float]]) -> list[list[float]]:
        return [_check_lonlat(p) for p in v]


class MultiLineString(BaseModel):
    """Several lines that are one thing — a route with a gap, a corridor in two legs."""
    model_config = STRICT
    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[list[list[float]]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def _valid(cls, v: list[list[list[float]]]) -> list[list[list[float]]]:
        return [[_check_lonlat(p) for p in line] for line in v]

    @model_validator(mode="after")
    def _each_line_has_two(self) -> "MultiLineString":
        """Each part is a LineString, so each part needs two positions — RFC 7946 §3.1.5.

        Checked here rather than inherited, because `min_length` on the outer list only counts
        parts. A part holding one position is a Point wearing a line's type, and it renders as
        nothing at all.
        """
        for index, line in enumerate(self.coordinates):
            if len(line) < 2:
                raise ValueError(
                    f"part {index} has {len(line)} position(s); a LineString needs at least 2 "
                    "(RFC 7946 §3.1.4)"
                )
        return self


class MultiPolygon(BaseModel):
    """Several polygons that are one thing — an airspace in disjoint lateral parts.

    The ring rules are `Polygon`'s and are enforced per part, for the reason they are enforced
    there: a ring that arrives open is a source or adapter defect, and closing it invents an edge
    the source never stated.
    """
    model_config = STRICT
    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: list[list[list[list[float]]]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def _valid(cls, v: list[list[list[list[float]]]]) -> list[list[list[list[float]]]]:
        return [[[_check_lonlat(p) for p in ring] for ring in poly] for poly in v]

    @model_validator(mode="after")
    def _closed(self) -> "MultiPolygon":
        for part, polygon in enumerate(self.coordinates):
            if not polygon:
                raise ValueError(f"part {part} has no rings; a Polygon needs at least 1")
            for index, ring in enumerate(polygon):
                if len(ring) < 4:
                    raise ValueError(
                        f"part {part} ring {index} has {len(ring)} positions; a closed linear "
                        "ring needs at least 4 (RFC 7946)"
                    )
                if ring[0] != ring[-1]:
                    raise ValueError(
                        f"part {part} ring {index} is not closed: first position {ring[0]} != "
                        f"last {ring[-1]}"
                    )
        return self


Geometry = Annotated[
    Union[Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon],
    Field(discriminator="type"),
]


class VerticalPosition(BaseModel):
    """A height, with the unit it was stated in and the datum it was measured from.

    §26's rule made structural: `value` is never alone. Three fields are required together
    because any two of them without the third is the ambiguity the policy exists to prevent —
    600 could be metres or feet, and 600 ft AGL over the Alps is not 600 ft MSL.

    NO CONVERSION HAPPENS HERE. This model records; it does not normalise. `models.Position`
    keeps `alt_m` as the canonical HAE-in-metres projection and a validator (there, not here)
    requires the two to agree when both are stated and the reference really is HAE. When the
    source's altitude is anything else, `alt_m` stays `None` — Rule 2, unknown is not a
    substituted value — and this block carries what the source actually said. Converting MSL to
    HAE needs a geoid model, converting a flight level needs the local QNH, and an adapter that
    performed either silently would be publishing a number nobody measured.

    `uncertainty` is in the SAME unit as `value`, and is one-sigma, matching
    `Position.accuracy_m`'s convention. Absent means unknown, never zero: zero would assert a
    height with no error, which no altimeter and no GNSS receiver produces.
    """
    model_config = STRICT
    value: float = Field(description="The number the source stated, in `unit`.")
    unit: VerticalUnit = Field(description="Never inferred; see VerticalUnit.")
    reference: VerticalReference = Field(description="The datum. UNKNOWN is a member, not null.")
    uncertainty: float | None = Field(
        default=None, ge=0.0,
        description="1-sigma, in the same unit as `value`. None = unknown, never 0.",
    )

    @model_validator(mode="after")
    def _flight_level_is_its_own_scale(self) -> "VerticalPosition":
        """`FL` as a unit and `FL` as a reference are one fact and must be stated together.

        A flight level is a number on the standard isobaric surface. "350 FL above MSL" and
        "35000 ft, reference FL" are both incoherent: the first states a datum the scale does not
        use, the second states a scale the datum does not belong to. Refused rather than
        repaired, because either repair picks a number the source did not send.
        """
        is_fl_unit = self.unit is VerticalUnit.FLIGHT_LEVEL
        is_fl_reference = self.reference is VerticalReference.FL
        if is_fl_unit != is_fl_reference:
            raise ValueError(
                f"unit {self.unit.value!r} with reference {self.reference.value!r}: a flight "
                "level is a scale AND a datum, so `FL` must appear in both or in neither"
            )
        return self


class VerticalExtent(BaseModel):
    """Lower and upper bounds of a volume. An airspace's floor and ceiling.

    Both optional and both may be absent: "surface to unlimited" is a real airspace and it is
    spelled by two absences, not by 0 and 999999. An extent with neither bound is still worth
    carrying, because its PRESENCE says the source described a volume rather than a surface.

    A bound may be stated in a different unit or against a different datum from the other — a
    danger area really is published as "surface to FL195" — so no comparison between the two is
    attempted here. Comparing 0 AGL with FL195 would need a terrain model and a pressure, and a
    validator that guessed at either would refuse real airspace.
    """
    model_config = STRICT
    lower: VerticalPosition | None = Field(default=None, description="Floor. None = unstated.")
    upper: VerticalPosition | None = Field(default=None, description="Ceiling. None = unstated.")


class BoundingBox(BaseModel):
    """A rectangular region in WGS84, bounds NAMED rather than positional.

    Why not RFC 7946 §5's `bbox` array: it is [west, south, east, north] and nothing in a
    four-float array stops a reader from taking it as [south, west, north, east]. That transposed
    reading is legal for most of the globe and puts the box in the wrong hemisphere, which is the
    same silent defect `_check_lonlat` exists to catch and cannot catch inside an array of four.
    Named fields make it unspellable. An adapter that must emit RFC 7946's array builds it from
    these four, in that order, at the edge where it is writing GeoJSON anyway.

    A box is not a Polygon and is not a substitute for one. It is the coarse extent a source
    states about itself — a coverage envelope, a search area, a tile — and a consumer that draws
    it as a shape is drawing something the source did not describe. Where the source really does
    describe a region, that region is a Polygon or a MultiPolygon.
    """
    model_config = STRICT
    min_lon: float = Field(ge=-180.0, le=180.0, description="West edge, WGS84 degrees.")
    min_lat: float = Field(ge=-90.0, le=90.0, description="South edge, WGS84 degrees.")
    max_lon: float = Field(ge=-180.0, le=180.0, description="East edge, WGS84 degrees.")
    max_lat: float = Field(ge=-90.0, le=90.0, description="North edge, WGS84 degrees.")
    vertical: VerticalExtent | None = Field(
        default=None, description="Floor and ceiling, when the source states a volume.",
    )

    @model_validator(mode="after")
    def _ordered(self) -> "BoundingBox":
        """min <= max on both axes, and the antimeridian case is REFUSED, not accommodated.

        RFC 7946 §5.2 permits `min_lon > max_lon` to mean a box that crosses 180°. This model
        does not, and the reason is that the two readings are indistinguishable: a box with
        min_lon 170 and max_lon -170 is either 20 degrees of the Pacific or 340 degrees of
        everything else, and which one the source meant is not in the numbers. Every consumer
        that gets it wrong gets it wrong silently and by a factor of seventeen. An adapter with a
        genuine antimeridian extent sends two boxes, or a MultiPolygon, and says which it meant.
        """
        if self.min_lon > self.max_lon:
            raise ValueError(
                f"min_lon {self.min_lon} exceeds max_lon {self.max_lon}. RFC 7946 §5.2 would "
                "read that as crossing the antimeridian; this model refuses it, because the "
                "same two numbers also read as a box seventeen times larger. Send two boxes"
            )
        if self.min_lat > self.max_lat:
            raise ValueError(f"min_lat {self.min_lat} exceeds max_lat {self.max_lat}")
        return self
