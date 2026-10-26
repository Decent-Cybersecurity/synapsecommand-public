"""SC4545-CORE-1 direct-corner footprints: an image's ICORDS and IGEOLO to a GeoJSON ring.

`footprint(icords, igeolo)` is the one entry point. It is pure and total: for a one-character
ICORDS and an IGEOLO that is `bytes` or None it returns a `Footprint` and never raises, so a bad
corner suppresses that image's footprint and nothing else. The container parser calls it once per
image and turns a finding into the image's one geometry diagnostic; this module builds no
diagnostic and imports nothing from the parser.

WHAT IS READ
------------
ICORDS `G` (latitude `ddmmssH`, longitude `dddmmssH`) and `D` (latitude `+dd.ddd`, longitude
`+ddd.ddd`, sign explicit) corners, four of them in IGEOLO's order: upper-left, upper-right,
lower-right, lower-left of the image. Every other ICORDS (UTM, MGRS, geocentric, lower-case
letters) is preserved by the parser as raw octets and never projected here; a blank ICORDS means
no footprint. Sensor-model TREs, ILOC and display attachment play no part: the footprint is the
polygon through the four stated corners, with no pixel-centre, pad or block-grid adjustment and
no height.

HOW IT IS COMPUTED
------------------
Exactly, in rationals, from the integer arcseconds or thousandths the text spells; each emitted
coordinate is rounded to a float once. The checks run in a fixed order and stop at the first
finding (grammar and range per corner, latitude before longitude; a pole corner; an edge exactly
180 degrees of longitude long; a span of 180 degrees or more; fewer than three distinct vertices
or no area; a self-intersection; a seam fragment that is not simple), so an image has at most one
finding. Longitudes are unwrapped edge by edge from the upper-left corner, the ring is emitted
counter-clockwise (reversed with the upper-left corner kept first when the stated order winds the
other way, while `corners` keeps the stated order), and a footprint whose unwrapped longitudes
cross 180 is clipped at the seam by one Sutherland-Hodgman pass into a west and an east part.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

#: The TRANSFORMS texts of the three geometry steps, recorded on each emitted footprint in this
#: order: the coordinates always, the orientation when the ring was reversed or a repeated corner
#: dropped, the splitting when the seam was crossed or a seam corner changed sign.
REASON_COORDINATES = (
    "ICORDS G (ddmmssH/dddmmssH) and D (signed dd.ddd/ddd.ddd) corners become decimal degrees in "
    "[longitude, latitude] order by exact rational arithmetic with one rounding per coordinate; "
    "the raw 60 IGEOLO bytes stay in the residual"
)
REASON_ORIENTATION = (
    "the corners are stated upper-left, upper-right, lower-right, lower-left in image order; the "
    "footprint ring is emitted counter-clockwise (RFC 7946 exterior), reversed with the "
    "upper-left corner kept first when the stated order winds clockwise, and an adjacent repeated "
    "corner is emitted once"
)
REASON_SPLITTING = (
    "a footprint whose unwrapped longitudes cross longitude 180 is clipped at the seam "
    "(Sutherland-Hodgman, latitude interpolated linearly) into a two-part MultiPolygon, west part "
    "first; a corner on longitude 180 or -180 takes the sign of the side the footprint lies on; "
    "an engineering approximation for display, not a geodesic"
)

#: The four statuses this module returns. `policy_blocked`, the result schema's fifth, is a host
#: decision and never comes from here.
STATUSES = ("available", "absent", "unsupported", "invalid")

#: The nine findings in check order. The first four that are source defects make the footprint
#: `invalid`; the rest are limits of this profile, under which a footprint stays unresolved.
REASONS = (
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
INVALID_REASONS = frozenset(("corner_syntax", "corner_range", "degenerate", "self_intersection"))

#: REQ-053's absolute tolerance, in degrees, of the orientation and bounding-box predicates.
TOLERANCE = Fraction(1, 10**12)

_NORTH, _SOUTH, _EAST, _WEST = 0x4E, 0x53, 0x45, 0x57
_PLUS, _MINUS, _POINT = 0x2B, 0x2D, 0x2E


@dataclass(frozen=True, slots=True)
class Footprint:
    """One image's footprint decision.

    `corners` holds the four parsed corners as `(longitude, latitude)` in the stated order
    (upper-left, upper-right, lower-right, lower-left) whenever all four parsed, also when a later
    check made the footprint unsupported or invalid. `geometry` is a plain GeoJSON Polygon or
    MultiPolygon dict, built afresh by every call, only when the status is `available`; the four
    flags and `transformations` describe that emitted ring and are false and empty otherwise.
    `issue_corner` (0 to 3) and `issue_part` (`lat` or `lon`) name the failing corner of a
    `corner_syntax` or `corner_range` finding.
    """

    status: str
    reason: str | None
    issue_corner: int | None
    issue_part: str | None
    geometry: dict[str, Any] | None
    corners: tuple[tuple[float, float], ...] | None
    reversed: bool
    split: bool
    seam_corner: bool
    duplicates_removed: bool
    transformations: tuple[str, ...]


def _finding(
    reason: str,
    corners: tuple[tuple[float, float], ...] | None = None,
    issue_corner: int | None = None,
    issue_part: str | None = None,
) -> Footprint:
    status = "invalid" if reason in INVALID_REASONS else "unsupported"
    return Footprint(
        status, reason, issue_corner, issue_part, None, corners, False, False, False, False, ()
    )


# --------------------------------------------------------------------------- the two grammars


def _digits(octets: bytes, start: int, end: int) -> bool:
    return all(0x30 <= octets[position] <= 0x39 for position in range(start, end))


def _number(octets: bytes, start: int, end: int) -> int:
    value = 0
    for position in range(start, end):
        value = value * 10 + octets[position] - 0x30
    return value


def _dms(part: bytes, width: int, positive: int, negative: int, limit: int) -> Fraction | str:
    """A G latitude (`width` 2) or longitude (3): degrees, minutes, seconds, hemisphere."""
    hemisphere = part[width + 4]
    if not _digits(part, 0, width + 4) or hemisphere not in (positive, negative):
        return "corner_syntax"
    degrees = _number(part, 0, width)
    minutes = _number(part, width, width + 2)
    seconds = _number(part, width + 2, width + 4)
    if (
        minutes >= 60
        or seconds >= 60
        or degrees > limit
        or (degrees == limit and minutes + seconds)
    ):
        return "corner_range"
    # Integer arcseconds first, one division last: summing degree fractions in floats rounds a
    # third of the arcsecond grid differently from the exact value.
    total = degrees * 3600 + minutes * 60 + seconds
    return Fraction(-total if hemisphere == negative else total, 3600)


def _decimal(part: bytes, width: int, limit: int) -> Fraction | str:
    """A D latitude (`width` 2) or longitude (3): an explicit sign, digits, a point, 3 digits."""
    sign = part[0]
    if (
        sign not in (_PLUS, _MINUS)
        or not _digits(part, 1, width + 1)
        or part[width + 1] != _POINT
        or not _digits(part, width + 2, width + 5)
    ):
        return "corner_syntax"
    thousandths = _number(part, 1, width + 1) * 1000 + _number(part, width + 2, width + 5)
    if thousandths > limit:
        return "corner_range"
    # -00.000 is zero: the value is canonical, the raw octets stay in the parser's IGEOLO slice.
    return Fraction(-thousandths if sign == _MINUS else thousandths, 1000)


def _corner_value(icords: str, part: bytes, axis: str) -> Fraction | str:
    if icords == "G":
        if axis == "lat":
            return _dms(part, 2, _NORTH, _SOUTH, 90)
        return _dms(part, 3, _EAST, _WEST, 180)
    if axis == "lat":
        return _decimal(part, 2, 90_000)
    return _decimal(part, 3, 180_000)


# --------------------------------------------------------------------------- plane predicates


def _float(value: Fraction) -> float:
    # The one rounding of an emitted coordinate: int / int is correctly rounded binary64.
    return value.numerator / value.denominator


def _twice_area(ring: list[tuple[Fraction, Fraction]]) -> Fraction:
    """The shoelace sum, positive for a counter-clockwise ring in (longitude, latitude)."""
    total = Fraction(0)
    previous = ring[-1]
    for current in ring:
        total += previous[0] * current[1] - current[0] * previous[1]
        previous = current
    return total


def _orientation(a, b, c) -> int:
    turn = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if abs(turn) <= TOLERANCE:
        return 0
    return 1 if turn > 0 else -1


def _in_box(p, a, b) -> bool:
    return (
        min(a[0], b[0]) - TOLERANCE <= p[0] <= max(a[0], b[0]) + TOLERANCE
        and min(a[1], b[1]) - TOLERANCE <= p[1] <= max(a[1], b[1]) + TOLERANCE
    )


def _segments_meet(a, b, c, d) -> bool:
    """Whether segment ab meets segment cd: a proper crossing, or an endpoint on (within the
    tolerance of) the other segment."""
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return (
        (o1 == 0 and _in_box(c, a, b))
        or (o2 == 0 and _in_box(d, a, b))
        or (o3 == 0 and _in_box(a, c, d))
        or (o4 == 0 and _in_box(b, c, d))
    )


def _self_intersects(ring: list[tuple[Fraction, Fraction]]) -> bool:
    """Every pair of edges that share no vertex, over the whole cyclic list. The corner ring has
    two such pairs; a clipped fragment of five or six entries has five or nine, and checking only
    the corner ring's two would refuse simple fragments."""
    n = len(ring)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_meet(ring[i], ring[(i + 1) % n], ring[j], ring[(j + 1) % n]):
                return True
    return False


def _without_repeats(points: list[tuple[Fraction, Fraction]]) -> list[tuple[Fraction, Fraction]]:
    """Adjacent duplicates removed, cyclically; the first entry is always kept."""
    kept = [points[0]]
    for point in points[1:]:
        if point != kept[-1]:
            kept.append(point)
    if len(kept) > 1 and kept[-1] == kept[0]:
        kept.pop()
    return kept


def _clip(ring, bound: Fraction, west: bool) -> list[tuple[Fraction, Fraction]]:
    """One Sutherland-Hodgman pass against the meridian `bound`, keeping the west (lon <= bound)
    or east (lon >= bound) side. The fragment starts where the pass starts emitting: rotating it
    would change the vertex sequence, and the sequence is part of the output."""

    def inside(point) -> bool:
        return point[0] <= bound if west else point[0] >= bound

    kept = []
    previous = ring[-1]
    for current in ring:
        if inside(current) != inside(previous):
            # The two longitudes differ, one on each side of the bound, so this never divides by 0.
            t = (bound - previous[0]) / (current[0] - previous[0])
            kept.append((bound, previous[1] + t * (current[1] - previous[1])))
        if inside(current):
            kept.append(current)
        previous = current
    return kept


def _ring(points, shift: Fraction) -> list[list[float]]:
    ring = [[_float(lon + shift), _float(lat)] for lon, lat in points]
    ring.append(list(ring[0]))
    return ring


# --------------------------------------------------------------------------- the entry point


def footprint(icords: str, igeolo: bytes | None) -> Footprint:
    """The footprint of one image from its ICORDS character and its 60 IGEOLO octets."""
    if type(icords) is not str or len(icords) != 1:
        raise TypeError("icords must be a one-character str")
    if igeolo is not None and type(igeolo) is not bytes:
        raise TypeError("igeolo must be bytes or None")
    if icords == " ":
        return Footprint("absent", None, None, None, None, None, False, False, False, False, ())
    if icords not in ("G", "D"):
        return _finding("icords_unsupported")
    if igeolo is None or len(igeolo) != 60:
        return _finding("corner_syntax", issue_corner=0, issue_part="lat")

    lats: list[Fraction] = []
    lons: list[Fraction] = []
    for k in range(4):
        start = 15 * k
        for axis, part, values in (
            ("lat", igeolo[start : start + 7], lats),
            ("lon", igeolo[start + 7 : start + 15], lons),
        ):
            value = _corner_value(icords, part, axis)
            if type(value) is str:
                return _finding(value, issue_corner=k, issue_part=axis)
            values.append(value)
    corners = tuple((_float(lon), _float(lat)) for lon, lat in zip(lons, lats))

    if any(abs(lat) == 90 for lat in lats):
        return _finding("pole_corner", corners)

    # Unwrapping: each edge in turn takes the longitude step in [-180, 180). A raw step that is
    # 180 modulo 360, either way round, has no shorter direction, so the edge is ambiguous. The
    # closing edge is not unwrapped; the span rule bounds it.
    unwrapped = [lons[0]]
    for lon in lons[1:]:
        step = lon - unwrapped[-1]
        if step % 360 == 180:
            return _finding("ambiguous_edge", corners)
        unwrapped.append(unwrapped[-1] + (step + 180) % 360 - 180)
    if max(unwrapped) - min(unwrapped) >= 180:
        return _finding("span", corners)

    stated = list(zip(unwrapped, lats))
    ring = _without_repeats(stated)
    area = _twice_area(ring) if len(ring) >= 3 else Fraction(0)
    if area == 0:
        return _finding("degenerate", corners)
    if _self_intersects(ring):
        return _finding("self_intersection", corners)
    reversed_ = area < 0
    if reversed_:
        ring = [ring[0], *ring[:0:-1]]
    duplicates_removed = len(ring) < 4

    # The slab [-180 + 360k, 180 + 360k] that holds the westernmost vertex; span < 180 means at
    # most the next one is touched as well.
    k0 = (min(unwrapped) + 180) // 360
    bound = Fraction(180 + 360 * k0)
    if max(unwrapped) <= bound:
        shift = Fraction(-360 * k0)
        emitted = [lon + shift for lon in unwrapped]
        seam_corner = any(
            (lon == 180 and out == -180) or (lon == -180 and out == 180)
            for lon, out in zip(lons, emitted)
        )
        geometry = {"type": "Polygon", "coordinates": [_ring(ring, shift)]}
        split = False
    else:
        parts = []
        for west, shift in ((True, Fraction(-360 * k0)), (False, Fraction(-360 * (k0 + 1)))):
            fragment = _without_repeats(_clip(ring, bound, west))
            # Clipping a concave footprint can join two separate pieces along the seam; this
            # profile refuses such a part rather than repairing it.
            if len(fragment) < 3 or _self_intersects(fragment):
                return _finding("seam_fragment", corners)
            parts.append([_ring(fragment, shift)])
        geometry = {"type": "MultiPolygon", "coordinates": parts}
        split = True
        seam_corner = False

    transformations = [REASON_COORDINATES]
    if reversed_ or duplicates_removed:
        transformations.append(REASON_ORIENTATION)
    if split or seam_corner:
        transformations.append(REASON_SPLITTING)
    return Footprint(
        "available",
        None,
        None,
        None,
        geometry,
        corners,
        reversed_,
        split,
        seam_corner,
        duplicates_removed,
        tuple(transformations),
    )
