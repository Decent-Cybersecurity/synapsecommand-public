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
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


Geometry = Annotated[Union[Point, LineString, Polygon], Field(discriminator="type")]
