"""The SC4545-CORE-1 direct-corner footprints, `adapters/nsif_geometry.py`, and the inventory step
of `adapters/nsif_codec.py` that stores one footprint and at most one geometry diagnostic per image.

Every expectation is a literal: a status and reason, a failing corner and part, a ring written out
coordinate by coordinate (each value the exact decimal of the corner text, rounded once), a
diagnostic's code, offset, path and fixed message, or a number GDAL gave: the geotransforms of five
axis-aligned vectors (recorded under `fixtures/stanag4545/independent/` by
`gates/nsif_gdal_reading.py`) and the seam splits GDAL's vector tool wrote for six footprints
(`ogr2ogr -f GeoJSON -wrapdateline`, GDAL 3.13.3, 2026-10-24), held below as literals. Corners at
the poles, across the antimeridian or out of range exist only in memory here; no tracked vector
states them. Package-only: every path is anchored on the imported package, nothing is written, and
no GDAL is needed.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import pathlib
import re
import types
from fractions import Fraction

import pytest

import synapse_cdm
from synapse_cdm.adapters import nsif_codec as nc
from synapse_cdm.adapters import nsif_geometry as ng
from synapse_cdm.geo import MultiPolygon, Polygon
from tests import observation_support as support

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "stanag4545"
GEOMETRY = PACKAGE / "adapters" / "nsif_geometry.py"
LIMITS = nc.CORE1_LIMITS

#: geo_dms.ntf's IGEOLO (at 776; ICORDS `G` at 775): UL 48N 17E, UR 48N 18E, LR 47N 18E, LL 47N 17E.
GEO_DMS = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
GEO_DMS_RING = [[17.0, 48.0], [17.0, 47.0], [18.0, 47.0], [18.0, 48.0], [17.0, 48.0]]
GEO_DMS_CORNERS = ((17.0, 48.0), (18.0, 48.0), (18.0, 47.0), (17.0, 47.0))


def dq(*corners: tuple[int, int]) -> str:
    """ICORDS D text of four (longitude, latitude) corners in whole degrees."""

    def part(value: int, width: int) -> str:
        return f"{'+' if value >= 0 else '-'}{abs(value):0{width}d}.000"

    return "".join(part(lat, 2) + part(lon, 3) for lon, lat in corners)


def fp(icords: str, text: str) -> ng.Footprint:
    return ng.footprint(icords, text.encode("ascii"))


def outcome(found: ng.Footprint) -> tuple:
    return (found.status, found.reason, found.issue_corner, found.issue_part)


def polygon(*ring) -> dict:
    return {"type": "Polygon", "coordinates": [list(map(list, ring))]}


def multipolygon(*rings) -> dict:
    return {"type": "MultiPolygon", "coordinates": [[list(map(list, ring))] for ring in rings]}


def kit(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def put(raw: bytes, offset: int, octets: bytes) -> bytes:
    assert offset + len(octets) <= len(raw)
    return raw[:offset] + octets + raw[offset + len(octets) :]


def geo_dms_with(icords: str, text: str) -> bytes:
    """geo_dms.ntf with another ICORDS and IGEOLO, every other octet unchanged."""
    return put(put(kit("geo_dms.ntf"), 775, icords.encode()), 776, text.encode())


def _build_fixtures_module():
    """The packaged builder, loaded from source as the codec tests load it, to build images the
    tracked set does not hold (another block grid, a sensor-model TRE)."""
    path = FIXTURES / "spec" / "build_fixtures.py"
    module = types.ModuleType("stanag4545_build_fixtures")
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


def twice_area(ring: list[list[float]]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))


def rings(geometry: dict) -> list[list[list[float]]]:
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    return [part[0] for part in geometry["coordinates"]]


def assert_well_formed(geometry: dict) -> None:
    """GeoJSON as the repository's models take it: closed, two-element positions in range, every
    ring counter-clockwise, no holes, at most two parts."""
    model = Polygon if geometry["type"] == "Polygon" else MultiPolygon
    assert model(**geometry).model_dump()["coordinates"] == geometry["coordinates"]
    if geometry["type"] == "Polygon":
        assert len(geometry["coordinates"]) == 1
    else:
        assert len(geometry["coordinates"]) == 2
        assert all(len(part) == 1 for part in geometry["coordinates"])
    for ring in rings(geometry):
        assert ring[0] == ring[-1] and len(ring) >= 4
        assert all(len(p) == 2 and type(p[0]) is float and type(p[1]) is float for p in ring)
        assert all(-180.0 <= p[0] <= 180.0 and -90.0 <= p[1] <= 90.0 for p in ring)
        assert twice_area(ring) > 0


# =========================================================================== GEO: the record


def test_the_footprint_record_and_its_vocabulary():
    assert [f.name for f in dataclasses.fields(ng.Footprint)] == [
        "status",
        "reason",
        "issue_corner",
        "issue_part",
        "geometry",
        "corners",
        "reversed",
        "split",
        "seam_corner",
        "duplicates_removed",
        "transformations",
    ]
    assert ng.STATUSES == ("available", "absent", "unsupported", "invalid")
    assert ng.REASONS == (
        "icords_unsupported",
        "corner_syntax",
        "corner_range",
        "pole_corner",
        "ambiguous_edge",
        "span",
        "degenerate",
        "self_intersection",
        "seam_fragment",
    )
    assert ng.INVALID_REASONS == {
        "corner_syntax",
        "corner_range",
        "degenerate",
        "self_intersection",
    }
    found = fp("G", GEO_DMS)
    with pytest.raises(dataclasses.FrozenInstanceError):
        found.status = "absent"
    # Nothing that would claim more than the corners do.
    for word in (
        "gsd",
        "meters_per_pixel",
        "metres",
        "altitude",
        "elevation",
        "height",
        "accuracy",
    ):
        assert not any(word in f.name for f in dataclasses.fields(ng.Footprint))


def test_a_blank_icords_has_no_footprint_and_no_finding():
    for igeolo in (None, b"", GEO_DMS.encode()):
        assert ng.footprint(" ", igeolo) == ng.Footprint(
            "absent", None, None, None, None, None, False, False, False, False, ()
        )


def test_the_argument_shapes_the_parser_cannot_produce_are_type_errors():
    for icords, igeolo in (
        ("GG", b""),
        ("", None),
        (b"G", None),
        (None, None),
        ("G", "x"),
        ("G", bytearray(60)),
        ("G", memoryview(GEO_DMS.encode())),
    ):
        with pytest.raises(TypeError):
            ng.footprint(icords, igeolo)
    # G or D with no corners, or not exactly sixty octets of them: a corner syntax finding.
    for igeolo in (None, b"", GEO_DMS.encode()[:59], GEO_DMS.encode() + b"0"):
        for icords in ("G", "D"):
            assert outcome(ng.footprint(icords, igeolo)) == ("invalid", "corner_syntax", 0, "lat")


def test_every_call_builds_its_geometry_afresh():
    first, second = fp("G", GEO_DMS), fp("G", GEO_DMS)
    assert first == second and first.geometry is not second.geometry
    first.geometry["coordinates"][0][0][0] = 99.0
    assert fp("G", GEO_DMS).geometry == polygon(*GEO_DMS_RING)


# =========================================================================== REQ-051: grammar


#: Corner faults, each naming the corner (0 to 3) and the part that fails first.
CORNER_FAULTS = [
    # G: DDMMSSH / DDDMMSSH.
    (
        "G",
        "486000N0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_range"),
    ),
    (
        "G",
        "480000N0170060E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lon", "corner_range"),
    ),
    (
        "G",
        "480000X0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_syntax"),
    ),
    (
        "G",
        "480000n0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_syntax"),
    ),
    (
        "G",
        "480000E0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_syntax"),
    ),
    (
        "G",
        "48 000N0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_syntax"),
    ),
    (
        "G",
        "910000N0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_range"),
    ),
    (
        "G",
        "900001N0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_range"),
    ),
    (
        "G",
        "480000N1810000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lon", "corner_range"),
    ),
    (
        "G",
        "480000N1800100E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lon", "corner_range"),
    ),
    (
        "G",
        "480000N0170000E480000N01800O0E470000N0180000E470000N0170000E",
        (1, "lon", "corner_syntax"),
    ),
    (
        "G",
        "480000N0170000N480000N0180000E470000N0180000E470000N0170000E",
        (0, "lon", "corner_syntax"),
    ),
    (
        "G",
        "480000N0170000e480000N0180000E470000N0180000E470000N0170000E",
        (0, "lon", "corner_syntax"),
    ),
    (
        "G",
        "+48000N0170000E480000N0180000E470000N0180000E470000N0170000E",
        (0, "lat", "corner_syntax"),
    ),
    (
        "G",
        "480000N0170000E480000N0180000E470000N0180000E47.000N0170000E",
        (3, "lat", "corner_syntax"),
    ),
    (
        "G",
        "480000N0170000E480000N0180000E470000N0180000E470000N0170000\xc9",
        (3, "lon", "corner_syntax"),
    ),
    (
        "G",
        "480000N0170000E480000N0180000E475900N0186000E470000N0170000E",
        (2, "lon", "corner_range"),
    ),
    # D: an explicit sign, digits, a point, three decimals.
    (
        "D",
        " 48.000+017.000+48.000+018.000+47.000+018.000+47.000+017.000",
        (0, "lat", "corner_syntax"),
    ),
    (
        "D",
        "+48,000+017.000+48.000+018.000+47.000+018.000+47.000+017.000",
        (0, "lat", "corner_syntax"),
    ),
    (
        "D",
        "+90.001+017.000+48.000+018.000+47.000+018.000+47.000+017.000",
        (0, "lat", "corner_range"),
    ),
    (
        "D",
        "+48.000+180.001+48.000+018.000+47.000+018.000+47.000+017.000",
        (0, "lon", "corner_range"),
    ),
    (
        "D",
        "+48.000017.000++48.000+018.000+47.000+018.000+47.000+017.000",
        (0, "lon", "corner_syntax"),
    ),
    (
        "D",
        "+48.000+017.00048.000+018.000+47.000+018.000+47.000+017.000+",
        (1, "lat", "corner_syntax"),
    ),
    (
        "D",
        "+48.000+017.000+48.000+018.000+47.000+018.0 0+47.000+017.000",
        (2, "lon", "corner_syntax"),
    ),
    (
        "D",
        "148.000+017.000+48.000+018.000+47.000+018.000+47.000+017.000",
        (0, "lat", "corner_syntax"),
    ),
    (
        "D",
        "+48.000+017.000+48.000+018.000+47.000+018.000+47.000+017.00\xc9",
        (3, "lon", "corner_syntax"),
    ),
]


@pytest.mark.parametrize(
    "icords, text, expected",
    CORNER_FAULTS,
)
def test_every_corner_fault_names_its_corner_and_part(icords, text, expected):
    corner, part, reason = expected
    found = ng.footprint(icords, text.encode("latin-1"))
    assert outcome(found) == ("invalid", reason, corner, part)
    assert (found.geometry, found.corners, found.transformations) == (None, None, ())


def test_the_first_finding_in_check_order_is_the_one_reported():
    # Corner 0's longitude range is found before corner 2's latitude syntax.
    text = "480000N1810000E480000N0180000E47000XN0180000E470000N0170000E"
    assert outcome(fp("G", text)) == ("invalid", "corner_range", 0, "lon")
    # A pole corner before an ambiguous edge, and before degeneracy.
    pole_and_edge = "900000N0000000E100000N1800000E090000N1800000E090000N0000000E"
    assert fp("G", pole_and_edge).reason == "pole_corner"
    all_poles = "900000N0170000E900000N0180000E900000N0180000E900000N0170000E"
    assert fp("G", all_poles).reason == "pole_corner"
    # An ambiguous edge before degeneracy.
    assert fp("D", dq((0, 0), (180, 0), (0, 0), (0, 0))).reason == "ambiguous_edge"


def test_corners_are_exact_decimals_rounded_once():
    # 1 minute 1 second: the exact 61/3600 rounds to ...446, summing floats gives ...443.
    found = fp("G", "000101N0170000E000101N0180000E000000N0180000E000000N0170000E")
    assert found.corners[0] == (17.0, 0.016944444444444446)
    assert fp("D", "+01.118+017.000+01.118+018.000+00.000+018.000+00.000+017.000").corners[0] == (
        17.0,
        1.118,
    )
    found = fp("G", "480101N0170203E480101N0180000E470000N0180000E470000N0170203E")
    assert found.geometry == polygon(
        [17.034166666666668, 48.01694444444445],
        [17.034166666666668, 47.0],
        [18.0, 47.0],
        [18.0, 48.01694444444445],
        [17.034166666666668, 48.01694444444445],
    )


def test_d_corners_on_the_meridian_and_negative_zero():
    found = fp("D", "+48.000-180.000+48.000-179.000+47.000-179.000+47.000-180.000")
    assert found.geometry == polygon(
        [-180.0, 48.0], [-180.0, 47.0], [-179.0, 47.0], [-179.0, 48.0], [-180.0, 48.0]
    )
    found = fp("D", "-00.000-000.000-00.000+001.123-01.500+001.123-01.500+000.000")
    assert found.geometry == polygon(
        [0.0, 0.0], [0.0, -1.5], [1.123, -1.5], [1.123, 0.0], [0.0, 0.0]
    )
    # Every zero is a positive zero; the source's minus signs stay in the raw IGEOLO octets.
    zeros = [v for ring in rings(found.geometry) for p in ring for v in p if v == 0]
    zeros += [v for corner in found.corners for v in corner if v == 0]
    assert zeros and all(repr(v) == "0.0" for v in zeros)
    found = fp("G", "000000S0000000W000000S0010000E010000S0010000E010000S0000000W")
    assert found.corners[0] == (0.0, 0.0) and repr(found.corners[0][1]) == "0.0"
    assert (
        fp("G", "100000N1800000E100000N1800000W090000N1800000W090000N1800000E").reason
        == "degenerate"
    )


# =========================================================================== REQ-052: the ring


def test_the_ring_is_counter_clockwise_and_the_corners_keep_their_stated_order():
    found = fp("G", GEO_DMS)
    assert found.status == "available" and found.reason is None
    assert found.geometry == {"type": "Polygon", "coordinates": [GEO_DMS_RING]}
    assert found.corners == GEO_DMS_CORNERS
    assert (found.reversed, found.split, found.seam_corner, found.duplicates_removed) == (
        True,
        False,
        False,
        False,
    )
    south_up = fp("G", "470000N0170000E470000N0180000E480000N0180000E480000N0170000E")
    assert south_up.geometry == polygon(
        [17.0, 47.0], [18.0, 47.0], [18.0, 48.0], [17.0, 48.0], [17.0, 47.0]
    )
    assert south_up.reversed is False
    assert south_up.corners == ((17.0, 47.0), (18.0, 47.0), (18.0, 48.0), (17.0, 48.0))


def test_the_transformations_name_exactly_the_steps_applied():
    coordinates, orientation, splitting = (
        ng.REASON_COORDINATES,
        ng.REASON_ORIENTATION,
        ng.REASON_SPLITTING,
    )
    assert fp("G", GEO_DMS).transformations == (coordinates, orientation)
    south_up = "470000N0170000E470000N0180000E480000N0180000E480000N0170000E"
    assert fp("G", south_up).transformations == (coordinates,)
    seam = "100000N1790000E100000N1790000W090000N1790000W090000N1790000E"
    assert fp("G", seam).transformations == (coordinates, orientation, splitting)
    west_corner = "100000N1800000W100000N1790000E090000N1790000E090000N1800000W"
    assert fp("G", west_corner).transformations == (coordinates, splitting)
    # A repeated corner alone is an orientation step too: this triangle already winds the right way.
    repeated = fp("D", dq((0, 0), (0, 0), (1, 0), (0, 1)))
    assert (repeated.reversed, repeated.duplicates_removed) == (False, True)
    assert repeated.transformations == (coordinates, orientation)
    assert repeated.geometry == polygon([0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0])


def test_the_three_transformation_texts():
    assert ng.REASON_COORDINATES == (
        "ICORDS G (ddmmssH/dddmmssH) and D (signed dd.ddd/ddd.ddd) corners become decimal degrees "
        "in [longitude, latitude] order by exact rational arithmetic with one rounding per "
        "coordinate; the raw 60 IGEOLO bytes stay in the residual"
    )
    assert ng.REASON_ORIENTATION == (
        "the corners are stated upper-left, upper-right, lower-right, lower-left in image order; "
        "the footprint ring is emitted counter-clockwise (RFC 7946 exterior), reversed with the "
        "upper-left corner kept first when the stated order winds clockwise, and an adjacent "
        "repeated corner is emitted once"
    )
    assert ng.REASON_SPLITTING == (
        "a footprint whose unwrapped longitudes cross longitude 180 is clipped at the seam "
        "(Sutherland-Hodgman, latitude interpolated linearly) into a two-part MultiPolygon, west "
        "part first; a corner on longitude 180 or -180 takes the sign of the side the footprint "
        "lies on; an engineering approximation for display, not a geodesic"
    )
    for text in (ng.REASON_COORDINATES, ng.REASON_ORIENTATION, ng.REASON_SPLITTING):
        assert text.isascii()


# =========================================================================== REQ-053: degeneracy


#: Corner sets with no area or a crossing.
NO_AREA = [
    ("G", "480000N0170000E" * 4, "degenerate"),
    ("D", dq((0, 0), (1, 0), (2, 0), (3, 0)), "degenerate"),
    ("D", dq((0, 0), (1, 0), (0, 0), (1, 0)), "degenerate"),
    ("D", dq((0, 0), (1, 1), (1, 0), (0, 1)), "degenerate"),
    ("D", dq((0, 0), (1, 0), (1, 0), (0, 0)), "degenerate"),
    ("G", "480000N0170000E470000N0180000E480000N0180000E465000N0170000E", "self_intersection"),
    ("D", dq((0, 0), (2, 0), (1, 0), (0, 1)), "self_intersection"),
    ("D", dq((0, 0), (2, 2), (2, 0), (0, 1)), "self_intersection"),
]


@pytest.mark.parametrize(
    "icords, text, reason",
    NO_AREA,
    ids=[
        "four-equal",
        "collinear",
        "two-repeated",
        "symmetric-bowtie",
        "fold-back",
        "bowtie",
        "spike",
        "crossed",
    ],
)
def test_a_footprint_with_no_area_or_a_crossing_is_invalid(icords, text, reason):
    found = fp(icords, text)
    assert (found.status, found.reason, found.geometry) == ("invalid", reason, None)
    # The corners parsed, so they are kept; nothing is emitted.
    assert len(found.corners) == 4 and found.transformations == ()


def test_a_repeated_corner_leaves_a_triangle_and_collinear_vertices_are_kept():
    found = fp("G", "480000N0170000E480000N0170000E470000N0180000E470000N0170000E")
    assert found.geometry == polygon([17.0, 48.0], [17.0, 47.0], [18.0, 47.0], [17.0, 48.0])
    assert (found.duplicates_removed, found.reversed) == (True, True)
    found = fp("D", dq((0, 0), (1, 0), (2, 0), (1, 1)))
    assert found.geometry == polygon([0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [1.0, 1.0], [0.0, 0.0])
    arrow = fp("D", dq((0, 0), (4, 2), (1, 0), (4, -2)))
    assert arrow.geometry == polygon([0.0, 0.0], [4.0, -2.0], [1.0, 0.0], [4.0, 2.0], [0.0, 0.0])


def test_the_segment_predicate_has_an_absolute_tolerance_of_1e_12():
    tick = Fraction(1, 10**12)
    a, b = (Fraction(0), Fraction(0)), (Fraction(1), Fraction(0))
    half = Fraction(1, 2)
    assert ng.TOLERANCE == tick
    # An end point within the tolerance of the other segment touches it; twice as far does not.
    assert ng._segments_meet(a, b, (half, tick / 2), (half, Fraction(1))) is True
    assert ng._segments_meet(a, b, (half, 2 * tick), (half, Fraction(1))) is False
    assert ng._segments_meet(a, b, (half, -1), (half, 1)) is True
    assert ng._segments_meet(a, b, (2, 0), (3, 0)) is False
    assert ng._segments_meet(a, b, (1 + tick, 0), (3, 0)) is True


def test_the_tolerance_is_inclusive_and_widens_every_side_of_the_box():
    tick = Fraction(1, 10**12)
    a, b = (Fraction(0), Fraction(0)), (Fraction(1), Fraction(0))
    half = Fraction(1, 2)
    # A cross product of exactly 1e-12 is "on the line"; 1e-12 + 1e-15 is not. The upright
    # segment from (1/2, h) to (1/2, 1) meets ab only through that end point.
    assert ng._segments_meet(a, b, (half, tick), (half, Fraction(1))) is True
    above = tick + Fraction(1, 10**15)
    assert ng._segments_meet(a, b, (half, above), (half, Fraction(1))) is False
    # One end point on the line of ab, past one end of the segment by exactly the tolerance, the
    # other end ten units away, so no other clause of the predicate can admit it (each other
    # cross product is at least 10 * 1e-12): the box's widening on that side alone decides. At
    # twice the tolerance nothing does.
    up, side = (Fraction(0), Fraction(0)), (Fraction(0), Fraction(1))
    for p, q, segment in (
        ((-tick, 0), (-tick, 10), (a, b)),  # x, lower side
        ((1 + tick, 0), (1 + tick, 10), (a, b)),  # x, upper side
        ((0, -tick), (10, -tick), (up, side)),  # y, lower side
        ((0, 1 + tick), (10, 1 + tick), (up, side)),  # y, upper side
    ):
        p = (Fraction(p[0]), Fraction(p[1]))
        q = (Fraction(q[0]), Fraction(q[1]))
        assert ng._segments_meet(*segment, p, q) is True, p
    for p, q, segment in (
        ((-2 * tick, 0), (-2 * tick, 10), (a, b)),
        ((1 + 2 * tick, 0), (1 + 2 * tick, 10), (a, b)),
        ((0, -2 * tick), (10, -2 * tick), (up, side)),
        ((0, 1 + 2 * tick), (10, 1 + 2 * tick), (up, side)),
    ):
        p = (Fraction(p[0]), Fraction(p[1]))
        q = (Fraction(q[0]), Fraction(q[1]))
        assert ng._segments_meet(*segment, p, q) is False, p


# =========================================================================== REQ-054: antimeridian


#: Corner sets outside the profile's assumptions.
UNRESOLVED = [
    ("G", "900000N0170000E480000N0180000E470000N0180000E470000N0170000E", "pole_corner"),
    ("D", "+48.000+017.000+48.000+018.000-90.000+018.000+47.000+017.000", "pole_corner"),
    ("D", dq((0, 10), (180, 10), (180, 9), (0, 9)), "ambiguous_edge"),
    ("D", dq((10, 10), (-170, 10), (-170, 9), (10, 9)), "ambiguous_edge"),
    ("D", dq((0, 10), (90, 10), (180, 9), (0, 9)), "ambiguous_edge"),
    ("D", dq((0, 10), (100, 10), (-170, 9), (50, 9)), "span"),
    ("D", dq((0, 10), (90, 10), (180, 9), (90, 9)), "span"),
    ("D", "+00.000-175.000+05.000+170.000+10.000-175.000+05.000+178.000", "seam_fragment"),
]


@pytest.mark.parametrize(
    "icords, text, reason",
    UNRESOLVED,
    ids=[
        "g-pole",
        "d-pole",
        "edge-0-180",
        "edge-10-190",
        "third-edge",
        "span-190",
        "span-180",
        "dart",
    ],
)
def test_a_footprint_outside_the_profiles_assumptions_stays_unresolved(icords, text, reason):
    found = fp(icords, text)
    assert (found.status, found.reason, found.geometry) == ("unsupported", reason, None)
    assert len(found.corners) == 4


def test_each_edge_takes_its_shorter_way_round():
    # From 0 to 179.5 W is 179.5 degrees westward, not 180.5 eastward: the ring runs west.
    found = fp("D", "+10.000+000.000+10.000-179.500+09.000-179.500+09.000+000.000")
    assert found.geometry == polygon(
        [0.0, 10.0], [-179.5, 10.0], [-179.5, 9.0], [0.0, 9.0], [0.0, 10.0]
    )
    assert found.reversed is False
    # And from 0 to 179.5 E eastward.
    found = fp("D", "+10.000+000.000+10.000+179.500+09.000+179.500+09.000+000.000")
    assert found.geometry == polygon(
        [0.0, 10.0], [0.0, 9.0], [179.5, 9.0], [179.5, 10.0], [0.0, 10.0]
    )
    assert found.reversed is True


def test_the_last_footprints_inside_the_assumptions():
    near_pole = fp("G", "895959N0170000E895959N0180000E890000N0180000E890000N0170000E")
    assert near_pole.status == "available"
    span = fp("D", dq((0, 10), (179, 10), (179, 9), (0, 9)))
    assert span.geometry == polygon(
        [0.0, 10.0], [0.0, 9.0], [179.0, 9.0], [179.0, 10.0], [0.0, 10.0]
    )


#: G footprints in one longitude slab, with (reversed, split, seam_corner).
ONE_SLAB = [
    (
        "100000N1800000E100000N1790000W090000N1790000W090000N1800000E",
        polygon([-180.0, 10.0], [-180.0, 9.0], [-179.0, 9.0], [-179.0, 10.0], [-180.0, 10.0]),
        (True, False, True),
    ),
    (
        "100000N1800000W100000N1790000E090000N1790000E090000N1800000W",
        polygon([180.0, 10.0], [179.0, 10.0], [179.0, 9.0], [180.0, 9.0], [180.0, 10.0]),
        (False, False, True),
    ),
    (
        "100000N1790000E100000N1800000E090000N1800000E090000N1790000E",
        polygon([179.0, 10.0], [179.0, 9.0], [180.0, 9.0], [180.0, 10.0], [179.0, 10.0]),
        (True, False, False),
    ),
    (
        "100000N1800000W100000N1790000W090000N1790000W090000N1800000W",
        polygon([-180.0, 10.0], [-180.0, 9.0], [-179.0, 9.0], [-179.0, 10.0], [-180.0, 10.0]),
        (True, False, False),
    ),
    (
        "100000N1790000W100000N1780000W090000N1780000W090000N1790000W",
        polygon([-179.0, 10.0], [-179.0, 9.0], [-178.0, 9.0], [-178.0, 10.0], [-179.0, 10.0]),
        (True, False, False),
    ),
]


@pytest.mark.parametrize(
    "text, geometry, flags",
    ONE_SLAB,
    ids=[
        "on-180E-rest-east",
        "on-180W-rest-west",
        "on-180E-rest-west",
        "on-180W-rest-east",
        "179W",
    ],
)
def test_a_footprint_in_one_slab_is_one_polygon_and_a_seam_corner_takes_its_sides_sign(
    text, geometry, flags
):
    found = fp("G", text)
    assert found.geometry == geometry
    assert (found.reversed, found.split, found.seam_corner) == flags


#: Footprints across the seam, with whether the stated order was reversed.
ACROSS = [
    (
        "G",
        "100000N1790000E100000N1790000W090000N1790000W090000N1790000E",
        multipolygon(
            [[180.0, 10.0], [179.0, 10.0], [179.0, 9.0], [180.0, 9.0], [180.0, 10.0]],
            [[-180.0, 10.0], [-180.0, 9.0], [-179.0, 9.0], [-179.0, 10.0], [-180.0, 10.0]],
        ),
        True,
    ),
    (
        "D",
        "+10.000+179.000+12.000-179.000+08.000-178.000+06.000+179.500",
        multipolygon(
            [[180.0, 11.0], [179.0, 10.0], [179.5, 6.0], [180.0, 6.4], [180.0, 11.0]],
            [[-180.0, 11.0], [-180.0, 6.4], [-178.0, 8.0], [-179.0, 12.0], [-180.0, 11.0]],
        ),
        True,
    ),
    (
        "G",
        "100000N1790000E100000N1800000E090000N1790000W090000N1790000E",
        multipolygon(
            [[179.0, 10.0], [179.0, 9.0], [180.0, 9.0], [180.0, 10.0], [179.0, 10.0]],
            [[-180.0, 10.0], [-180.0, 9.0], [-179.0, 9.0], [-180.0, 10.0]],
        ),
        True,
    ),
    (
        "D",
        "+00.000+175.000+05.000-170.000+10.000+175.000+05.000+178.000",
        multipolygon(
            [
                [175.0, 0.0],
                [180.0, 1.6666666666666667],
                [180.0, 8.333333333333334],
                [175.0, 10.0],
                [178.0, 5.0],
                [175.0, 0.0],
            ],
            [
                [-180.0, 1.6666666666666667],
                [-170.0, 5.0],
                [-180.0, 8.333333333333334],
                [-180.0, 1.6666666666666667],
            ],
        ),
        False,
    ),
    (
        "D",
        "-04.000-179.000-04.000+175.000+00.000+175.000-02.000+177.000",
        multipolygon(
            [
                [180.0, -4.0],
                [180.0, -3.5],
                [177.0, -2.0],
                [175.0, 0.0],
                [175.0, -4.0],
                [180.0, -4.0],
            ],
            [[-180.0, -4.0], [-179.0, -4.0], [-180.0, -3.5], [-180.0, -4.0]],
        ),
        True,
    ),
    (
        "D",
        "-04.000-179.000-02.000-179.000-04.000-177.000+04.000+177.000",
        multipolygon(
            [[180.0, -2.0], [180.0, 0.0], [177.0, 4.0], [180.0, -2.0]],
            [
                [-180.0, -2.0],
                [-179.0, -4.0],
                [-179.0, -2.0],
                [-177.0, -4.0],
                [-180.0, 0.0],
                [-180.0, -2.0],
            ],
        ),
        False,
    ),
]


@pytest.mark.parametrize(
    "icords, text, geometry, reversed_",
    ACROSS,
    ids=[
        "g-square",
        "d-slanted",
        "corner-on-seam",
        "dart-one-east-piece",
        "five-west",
        "five-east",
    ],
)
def test_a_footprint_across_the_seam_is_clipped_west_part_first(icords, text, geometry, reversed_):
    found = fp(icords, text)
    assert found.status == "available" and found.geometry == geometry
    assert (found.split, found.seam_corner, found.reversed) == (True, False, reversed_)
    assert_well_formed(found.geometry)
    west, east = rings(found.geometry)
    assert max(p[0] for p in west) == 180.0 and min(p[0] for p in east) == -180.0


# =========================================================================== GDAL's vector tool

#: Six seam splits GDAL 3.13.3 wrote on 2026-10-24 (`ogr2ogr -f GeoJSON out in -wrapdateline`) for
#: each footprint's closed unwrapped ring, verbatim. GDAL may list the parts the other way round
#: and start a ring elsewhere; what is compared is each part's vertex set and its area.
GDAL_SPLITS = [
    (
        "G",
        "100000N1790000E100000N1790000W090000N1790000W090000N1790000E",
        [[[179.0, 10.0], [181.0, 10.0], [181.0, 9.0], [179.0, 9.0], [179.0, 10.0]]],
        [
            [[[179.0, 10.0], [180.0, 10.0], [180.0, 9.0], [179.0, 9.0], [179.0, 10.0]]],
            [[[-180.0, 10.0], [-179.0, 10.0], [-179.0, 9.0], [-180.0, 9.0], [-180.0, 10.0]]],
        ],
    ),
    (
        "D",
        "+10.000+179.000+12.000-179.000+08.000-178.000+06.000+179.500",
        [[[179.0, 10.0], [181.0, 12.0], [182.0, 8.0], [179.5, 6.0], [179.0, 10.0]]],
        [
            [[[179.0, 10.0], [180.0, 11.0], [180.0, 6.4], [179.5, 6.0], [179.0, 10.0]]],
            [[[-180.0, 11.0], [-179.0, 12.0], [-178.0, 8.0], [-180.0, 6.4], [-180.0, 11.0]]],
        ],
    ),
    (
        "G",
        "100000N1790000E100000N1800000E090000N1790000W090000N1790000E",
        [[[179.0, 10.0], [180.0, 10.0], [181.0, 9.0], [179.0, 9.0], [179.0, 10.0]]],
        [
            [[[179.0, 10.0], [180.0, 10.0], [180.0, 9.0], [179.0, 9.0], [179.0, 10.0]]],
            [[[-180.0, 10.0], [-179.0, 9.0], [-180.0, 9.0], [-180.0, 10.0]]],
        ],
    ),
    (
        "D",
        "+00.000+175.000+05.000-170.000+10.000+175.000+05.000+178.000",
        [[[175.0, 0.0], [190.0, 5.0], [175.0, 10.0], [178.0, 5.0], [175.0, 0.0]]],
        [
            [
                [
                    [180.0, 1.666666666666667],
                    [175.0, 0.0],
                    [178.0, 5.0],
                    [175.0, 10.0],
                    [180.0, 8.333333333333334],
                    [180.0, 1.666666666666667],
                ]
            ],
            [
                [
                    [-180.0, 8.333333333333334],
                    [-170.0, 5.0],
                    [-180.0, 1.666666666666667],
                    [-180.0, 8.333333333333334],
                ]
            ],
        ],
    ),
    (
        "D",
        "-04.000-179.000-04.000+175.000+00.000+175.000-02.000+177.000",
        [[[-179.0, -4.0], [-185.0, -4.0], [-185.0, 0.0], [-183.0, -2.0], [-179.0, -4.0]]],
        [
            [[[-179.0, -4.0], [-180.0, -4.0], [-180.0, -3.5], [-179.0, -4.0]]],
            [
                [
                    [180.0, -4.0],
                    [175.0, -4.0],
                    [175.0, 0.0],
                    [177.0, -2.0],
                    [180.0, -3.5],
                    [180.0, -4.0],
                ]
            ],
        ],
    ),
    (
        "D",
        "-04.000-179.000-02.000-179.000-04.000-177.000+04.000+177.000",
        [[[-179.0, -4.0], [-179.0, -2.0], [-177.0, -4.0], [-183.0, 4.0], [-179.0, -4.0]]],
        [
            [
                [
                    [-180.0, 0.0],
                    [-177.0, -4.0],
                    [-179.0, -2.0],
                    [-179.0, -4.0],
                    [-180.0, -2.0],
                    [-180.0, 0.0],
                ]
            ],
            [[[180.0, -2.0], [177.0, 4.0], [180.0, 0.0], [180.0, -2.0]]],
        ],
    ),
]


def _parts(polygons) -> list[tuple[frozenset, float]]:
    """Each polygon as (its distinct vertices rounded to 9 decimals, its area)."""
    return [
        (
            frozenset((round(lon, 9), round(lat, 9)) for lon, lat in polygon[0]),
            abs(twice_area(polygon[0])) / 2,
        )
        for polygon in polygons
    ]


@pytest.mark.parametrize("icords, text, unwrapped, gdal", GDAL_SPLITS)
def test_the_seam_split_has_gdals_parts(icords, text, unwrapped, gdal):
    found = fp(icords, text)
    ours = _parts(found.geometry["coordinates"])
    theirs = _parts(gdal)
    assert len(ours) == len(theirs) == 2
    for vertices, area in theirs:
        matches = [a for v, a in ours if v == vertices]
        assert len(matches) == 1 and abs(matches[0] - area) <= 1e-9
    # The unwrapped ring GDAL was given is this footprint's: its corners in stated order.
    stated = [corner for corner in unwrapped[0][:-1]]
    assert [[lon % 360, lat] for lon, lat in stated] == [
        [lon % 360, lat] for lon, lat in found.corners
    ]


# =========================================================================== the sweep


def _quads(count: int):
    """`count` sets of four D corners in thousandths of a degree, near the seam and elsewhere,
    from a fixed linear congruential sequence (no random module: the same set on every
    interpreter)."""
    state = 0x4545

    def draw(n: int) -> int:
        nonlocal state
        state = (state * 6364136223846793005 + 1442695040888963407) % 2**64
        return (state >> 33) % n

    for _ in range(count):
        base = draw(4) * 90_000 - 180_000
        yield [(base + draw(24_001) - 12_000, draw(36_001) - 18_000) for _ in range(4)]


def _d_text(corners) -> str:
    text = ""
    for lon, lat in corners:
        lon = (lon + 180_000) % 360_000 - 180_000
        text += f"{'+' if lat >= 0 else '-'}{abs(lat) // 1000:02d}.{abs(lat) % 1000:03d}"
        text += f"{'+' if lon >= 0 else '-'}{abs(lon) // 1000:03d}.{abs(lon) % 1000:03d}"
    return text


def test_every_emitted_footprint_is_well_formed_over_a_fixed_sweep():
    seen: dict[str, int] = {}
    splits = 0
    for corners in _quads(3000):
        found = fp("D", _d_text(corners))
        key = found.reason or found.status
        seen[key] = seen.get(key, 0) + 1
        if found.status == "available":
            assert_well_formed(found.geometry)
            splits += found.split
        else:
            assert found.geometry is None and found.transformations == ()
    # Not vacuous: plain and split footprints, and the refusals random corners reach.
    assert seen["available"] > 300 and splits > 50
    assert seen["self_intersection"] > 50 and seen["seam_fragment"] > 0


#: Every IGEOLO text this module states, for the totality sweep.
_LITERALS = sorted(
    {GEO_DMS}
    | {text for _, text, _ in CORNER_FAULTS}
    | {text for _, text, _ in NO_AREA}
    | {text for _, text, _ in UNRESOLVED}
    | {text for text, _, _ in ONE_SLAB}
    | {text for _, text, _, _ in ACROSS}
    | {text for _, text, _, _ in GDAL_SPLITS}
)


def test_every_available_literal_is_well_formed_geojson():
    available = 0
    for text in _LITERALS:
        for icords in ("G", "D"):
            found = ng.footprint(icords, text.encode("latin-1"))
            if found.status == "available":
                available += 1
                assert_well_formed(found.geometry)
                assert found.transformations[0] == ng.REASON_COORDINATES
    assert available >= 10


def test_footprint_is_total_over_its_domain():
    for code in range(0x20, 0x7F):
        found = ng.footprint(chr(code), GEO_DMS.encode())
        expected = {" ": "absent", "G": "available", "D": "invalid"}.get(chr(code), "unsupported")
        assert found.status == expected
        if expected == "unsupported":
            assert (found.reason, found.corners) == ("icords_unsupported", None)
    probes = (0x00, 0xFF, 0x20, 0x2B, 0x2D, 0x2E, 0x30, 0x39, 0x4E, 0x53, 0x45, 0x57)
    texts = sorted(set(_LITERALS) | {text for (_, text), *_ in FINDINGS.values()})
    assert len(texts) > 50
    for text in texts:
        octets = text.encode("latin-1")
        for icords in ("G", "D"):
            for position in range(60):
                for probe in probes:
                    mutated = octets[:position] + bytes((probe,)) + octets[position + 1 :]
                    found = ng.footprint(icords, mutated)
                    assert found.status in ng.STATUSES
                    if found.status == "available":
                        assert_well_formed(found.geometry)
                    else:
                        assert found.geometry is None
                        assert found.status == (
                            "invalid" if found.reason in ng.INVALID_REASONS else "unsupported"
                        )
            for length in range(60):
                assert outcome(ng.footprint(icords, octets[:length])) == (
                    "invalid",
                    "corner_syntax",
                    0,
                    "lat",
                )


# =========================================================================== the inventory


#: Each finding through a whole container: geo_dms with another ICORDS or IGEOLO. The code, the
#: field it is reported at (ICORDS 775 or IGEOLO 776) and the fixed message, and whether the
#: profile counts it as a violation (`validate_source` lists GEOMETRY_INVALID only).
FINDINGS = {
    "icords_unsupported": (
        ("U", GEO_DMS),
        "GEOMETRY_UNSUPPORTED",
        775,
        "ICORDS",
        "ICORDS names a coordinate system this profile preserves but does not project",
    ),
    "corner_syntax": (
        ("G", "480000X0170000E480000N0180000E470000N0180000E470000N0170000E"),
        "GEOMETRY_INVALID",
        776,
        "IGEOLO",
        "corner text does not match the ICORDS grammar",
    ),
    "corner_range": (
        ("G", "486000N0170000E480000N0180000E470000N0180000E470000N0170000E"),
        "GEOMETRY_INVALID",
        776,
        "IGEOLO",
        "corner value is outside its valid range",
    ),
    "pole_corner": (
        ("G", "900000N0170000E480000N0180000E470000N0180000E470000N0170000E"),
        "GEOMETRY_UNRESOLVED",
        776,
        "IGEOLO",
        "a corner lies exactly on a pole",
    ),
    "ambiguous_edge": (
        ("G", "100000N0000000E100000N1800000E090000N1800000E090000N0000000E"),
        "GEOMETRY_UNRESOLVED",
        776,
        "IGEOLO",
        "two consecutive corners are exactly 180 degrees of longitude apart",
    ),
    "span": (
        ("G", "100000N0000000E100000N1000000E090000N1700000W090000N0500000E"),
        "GEOMETRY_UNRESOLVED",
        776,
        "IGEOLO",
        "the footprint spans 180 degrees of longitude or more",
    ),
    "degenerate": (
        ("G", "480000N0170000E" * 4),
        "GEOMETRY_INVALID",
        776,
        "IGEOLO",
        "the corners do not enclose a nonzero area",
    ),
    "self_intersection": (
        ("G", "480000N0170000E470000N0180000E480000N0180000E465000N0170000E"),
        "GEOMETRY_INVALID",
        776,
        "IGEOLO",
        "the corner ring intersects itself",
    ),
    "seam_fragment": (
        ("D", "+00.000-175.000+05.000+170.000+10.000-175.000+05.000+178.000"),
        "GEOMETRY_UNRESOLVED",
        776,
        "IGEOLO",
        "clipping at the antimeridian does not give simple parts",
    ),
}


@pytest.mark.parametrize("reason", sorted(FINDINGS))
def test_each_finding_is_one_geometry_diagnostic_and_suppresses_only_the_footprint(reason):
    (icords, text), code, offset, field, message = FINDINGS[reason]
    found = nc.parse_container(geo_dms_with(icords, text), LIMITS)
    image = found.images[0]
    assert image.footprint == ng.footprint(icords, text.encode())
    assert (image.geometry_status, image.geometry_reason) == (image.footprint.status, reason)
    assert image.geometry_status == ("invalid" if reason in ng.INVALID_REASONS else "unsupported")
    assert found.diagnostics == (
        nc.Diagnostic(code, "geometry", offset, f"/segments/image[0]/{field}", message),
    )
    assert nc.DIAGNOSTIC_CODES[code] is (code == "GEOMETRY_INVALID")
    rendered = {
        "corner_range": (
            "GEOMETRY_INVALID @byte 776 /segments/image[0]/IGEOLO: corner value is outside its "
            "valid range"
        ),
        "icords_unsupported": (
            "GEOMETRY_UNSUPPORTED @byte 775 /segments/image[0]/ICORDS: ICORDS names a coordinate "
            "system this profile preserves but does not project"
        ),
    }
    if reason in rendered:
        assert str(found.diagnostics[0]) == rendered[reason]
    # The image is otherwise intact: its pixels still decode, its raw corners are kept.
    window = nc.decode_nc_window(found, 0, 0, 0, 2, 2, (0,))
    assert window.values() == (0, 64, 128, 255)
    assert image.igeolo == nc.Slice(776, 60) and found.raw[776:836] == text.encode()
    assert image.pixel_status == "native_supported"


def test_the_kit_footprint_is_stored_on_its_image_with_no_diagnostic():
    found = nc.parse_container(kit("geo_dms.ntf"), LIMITS)
    image = found.images[0]
    assert (image.geometry_status, image.geometry_reason) == ("available", None)
    assert image.footprint.geometry == polygon(*GEO_DMS_RING)
    assert image.footprint.corners == GEO_DMS_CORNERS
    assert found.diagnostics == ()
    for name in ("mono_nsif101.ntf", "mode_B.ntf", "image_and_text.ntf", "uint16.ntf"):
        blank = nc.parse_container(kit(name), LIMITS).images[0]
        assert (blank.icords, blank.igeolo, blank.geometry_status, blank.geometry_reason) == (
            " ",
            None,
            "absent",
            None,
        )
    # The image-subheader seam computes the footprint the same way.
    record, notes = nc.image_subheader(kit("geo_dms.ntf")[404:903], LIMITS, data_length=4)
    assert record.footprint == image.footprint and notes == ()
    record, notes = nc.image_subheader(geo_dms_with("U", GEO_DMS)[404:903], LIMITS, data_length=4)
    assert record.geometry_reason == "icords_unsupported"
    assert [(n.code, n.offset) for n in notes] == [("GEOMETRY_UNSUPPORTED", 371)]


def test_the_footprint_does_not_depend_on_the_pixel_cell():
    # geo_dms with ABPP and NBPP 12 (at 772 and 871): no native pixel path, the same footprint.
    raw = put(put(kit("geo_dms.ntf"), 772, b"12"), 871, b"12")
    found = nc.parse_container(raw, LIMITS)
    image = found.images[0]
    assert (image.pixel_status, image.pixel_reason) == ("unsupported", "unsupported_sample_type")
    assert image.footprint == nc.parse_container(kit("geo_dms.ntf"), LIMITS).images[0].footprint
    assert [d.code for d in found.diagnostics] == ["UNSUPPORTED_SAMPLE_TYPE"]


def test_other_coordinate_systems_are_preserved_and_never_projected():
    for icords, text in (
        ("N", GEO_DMS),
        ("S", GEO_DMS),
        ("U", "00AAA0000000000" * 4),
        ("C", "0" * 60),
        ("g", GEO_DMS),
        ("d", "+48.000+017.000+48.000+018.000+47.000+018.000+47.000+017.000"),
    ):
        found = nc.parse_container(geo_dms_with(icords, text), LIMITS)
        image = found.images[0]
        assert (image.icords, image.geometry_status, image.geometry_reason) == (
            icords,
            "unsupported",
            "icords_unsupported",
        )
        assert (image.footprint.geometry, image.footprint.corners) == (None, None)
        assert image.igeolo == nc.Slice(776, 60) and found.raw[776:836] == text.encode()


def test_sensor_models_and_display_offsets_change_nothing():
    builder = _build_fixtures_module()
    rpc = b"RPC00B" + b"01041" + bytes(range(256)) * 4 + b"\x00" * 17
    assert len(rpc) == 11 + 1041
    blank = nc.parse_container(builder.container([builder.image(tre=rpc)]), LIMITS)
    assert blank.images[0].geometry_status == "absent" and blank.diagnostics == ()
    assert [(t.tag, t.data.length) for t in blank.extensions] == [("RPC00B", 1041)]
    with_tre = nc.parse_container(builder.container([builder.image(geo=GEO_DMS, tre=rpc)]), LIMITS)
    plain = nc.parse_container(kit("geo_dms.ntf"), LIMITS)
    assert with_tre.images[0].footprint == plain.images[0].footprint
    # ILOC (at 879 in geo_dms) moves the image in its display, never on the ground.
    moved = nc.parse_container(put(kit("geo_dms.ntf"), 879, b"0010000020"), LIMITS)
    assert (moved.images[0].iloc.row, moved.images[0].iloc.column) == (100, 20)
    assert moved.images[0].footprint == plain.images[0].footprint
    # Nor do the display level and attachment (IDLVL 873, IALVL 876): an attachment to a level no
    # item holds is a composition finding, and the footprint is unchanged.
    attached = nc.parse_container(put(kit("geo_dms.ntf"), 873, b"005007"), LIMITS)
    assert (attached.images[0].idlvl, attached.images[0].ialvl) == (5, 7)
    assert attached.composition_status == "unavailable"
    assert [d.code for d in attached.diagnostics] == ["COMPOSITION_MISSING_PARENT"]
    assert attached.images[0].footprint == plain.images[0].footprint


def test_the_footprint_is_the_stated_corners_whatever_the_block_grid():
    builder = _build_fixtures_module()
    samples = builder.planes(1, 5, 7, builder.sample8)
    padded = builder.container([builder.native_image(samples, 4, 4, icords="G", igeolo=GEO_DMS)])
    found = nc.parse_container(padded, LIMITS)
    image = found.images[0]
    assert (image.ncols, image.nrows, image.nbpr, image.nbpc, image.segment.data.length) == (
        7,
        5,
        2,
        2,
        64,
    )
    assert image.footprint == nc.parse_container(kit("geo_dms.ntf"), LIMITS).images[0].footprint
    # The four corners exactly, with no half-pixel widening (GDAL reads them as pixel centres).
    assert image.footprint.corners == GEO_DMS_CORNERS


# =========================================================================== GDAL's corners


RECTANGLES = {
    "geo_dms": ("geo_dms.ntf", [16.5, 1.0, 0.0, 48.5, 0.0, -1.0]),
    "native_geo_g_northup": (
        "vectors/native_geo_g_northup.ntf",
        [20.6875, 0.625, 0.0, 58.25, 0.0, -0.5],
    ),
    "native_geo_g_southup": (
        "vectors/native_geo_g_southup.ntf",
        [20.6875, 0.625, 0.0, 56.75, 0.0, 0.5],
    ),
    "native_geo_d_northup": (
        "vectors/native_geo_d_northup.ntf",
        [20.03125, 0.9375, 0.0, 58.625, 0.0, -0.75],
    ),
    "native_geo_d_southup": (
        "vectors/native_geo_d_southup.ntf",
        [20.03125, 0.9375, 0.0, 56.375, 0.0, 0.75],
    ),
}


def test_only_the_five_rectangles_carry_a_recorded_geotransform():
    carrying = sorted(
        p.name[: -len(".gdal.json")]
        for p in (FIXTURES / "independent").glob("*.gdal.json")
        if "geo_transform" in json.loads(p.read_text())
    )
    assert carrying == sorted(RECTANGLES)


@pytest.mark.parametrize("stem", sorted(RECTANGLES))
def test_gdals_geotransform_corroborates_axis_order_corner_order_and_winding(stem):
    location, transform = RECTANGLES[stem]
    reading = json.loads((FIXTURES / "independent" / f"{stem}.gdal.json").read_text())
    assert reading["file"] == location and reading["geo_transform"] == transform
    gt = reading["geo_transform"]
    assert gt[2] == gt[4] == 0
    found = nc.parse_container((FIXTURES / location).read_bytes(), LIMITS).images[0].footprint
    assert found.status == "available" and len(reading["corners"]) == 4
    for theirs, ours in zip(reading["corners"], found.corners):
        assert abs(theirs[0] - ours[0]) <= 1e-9 and abs(theirs[1] - ours[1]) <= 1e-9
    # An axis-aligned raster winds clockwise as stated exactly when its column and row steps have
    # opposite signs.
    assert found.reversed == (gt[1] * gt[5] < 0)
    assert found.reversed == stem.endswith(("northup", "geo_dms"))


# =========================================================================== fixtures and imports


def test_every_authored_corner_lies_in_the_baltic_rectangle_and_only_the_kits_does_not():
    outside = []
    for path in sorted(FIXTURES.rglob("*.ntf")):
        if "malformed" in path.parts:
            continue
        found = nc.parse_container(path.read_bytes(), LIMITS)
        for image in found.images:
            if image.footprint.corners is None:
                continue
            document = {
                "corners": {"coordinates": [list(c) for c in image.footprint.corners]},
                "footprint": image.footprint.geometry,
            }
            if support.positions_outside_the_rectangle(document):
                outside.append(path.relative_to(FIXTURES).as_posix())
    assert outside == ["geo_dms.ntf"]
    authored = sorted(p.name for p in (FIXTURES / "vectors").glob("native_geo_*.ntf"))
    assert len(authored) == 4


def test_the_geometry_module_imports_only_its_named_set_and_nothing_from_the_parser():
    source = GEOMETRY.read_text()
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "dataclasses", "fractions", "typing"}
    assert "nsif_codec" not in source
    assert not re.search(r"ET\.fromstring|json\.loads|zipfile|sqlite3|gzip|zlib", source)
    assert "nsif_geometry" in (PACKAGE / "adapters" / "nsif_codec.py").read_text()


def test_the_geometry_tests_need_no_gdal():
    source = pathlib.Path(__file__).read_text()
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"subprocess", "o" + "sgeo", "shutil", "os"}
    assert ("o" + "sgeo") not in source
