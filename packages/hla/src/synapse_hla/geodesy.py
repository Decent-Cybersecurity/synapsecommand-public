"""Section 9 of the profile: a decoded Spatial value to a WGS84 position and, for world velocity,
ENU motion. Pure arithmetic on binary64; the projector (round R3) builds the CDM Entity around it.

THE ARITHMETIC IS THE SPECIFICATION'S, OPERATION FOR OPERATION
--------------------------------------------------------------
SPEC:140-146 gives the formulas, and the rulings fix what the prose leaves open; the code below
follows them in the order they are written, because a different but algebraically equal grouping
moves the last bit of a result and, near a rounding boundary, the emitted decimal (COD-13):

- the gate: every component finite and `1e6 <= hypot(x, y, z) <= 1e8` metres, both inclusive,
  else E_ECEF_RANGE (R29, COD-11). That bound belongs to this profile, not to HLA: the decoder
  accepts any finite position, and only projection refuses one outside it;
- WGS84 from a and the inverse flattening, `f = 1/inverse_flattening`, `b = a*(1-f)`,
  `e2 = f*(2-f)`, each written exactly that way;
- `p = hypot(x, y)`; below 1e-8 m from the polar axis the latitude is the sign of z times 90
  degrees, the longitude 0 and the height `|z| - b`;
- otherwise the latitude starts at `atan2(z, p*(1-e2))` and is replaced by
  `atan2(z + e2*N*sin(lat), p)`, `N = a/sqrt(1 - e2*sin(lat)**2)`, until a step changes it by at
  most 1e-14 rad; the latitude kept is the last one computed, convergence on the last allowed
  step counts, and N is computed once more at that latitude (COD-13). No convergence within
  `max_iterations` steps is E_GEODESY. The bound is a keyword-only parameter defaulting to the
  specified 32 so that a test can reach E_GEODESY, which no finite in-gate input reaches
  (COD-12); production code never passes it;
- the height is `p/cos(lat) - N` where `|cos(lat)| >= 0.5`, else `z/sin(lat) - N*(1-e2)`;
- a non-finite latitude, longitude or height is E_GEODESY; a latitude beyond +-90 degrees by at
  most 1e-10 degrees is floating roundoff and is clamped, by more it is E_GEODESY (both signs);
- the longitude is `degrees(atan2(y, x))`, and exactly +180 becomes -180 (COD-10).

Emission (R30, COD-01, COD-02, COD-10): latitude and longitude are rounded to 9 decimals and the
height to 6 with CPython's `round`, which rounds the exact binary value half to even; a longitude
that rounds to +180 becomes -180; then a zero of either sign is written as +0.0. That last step
is applied to the emitted numbers only, after rounding, because a tiny negative value rounds to
-0.0 (COD-02).

Motion (SPEC:146, COD-03): only the WORLD velocity of algorithms 2-5 is projected, and not at the
pole case, where course depends on a convention. The ENU rotation uses the unrounded latitude
and the unwrapped `atan2` longitude, in radians. Speed is `hypot(east, north)` and course is
null unless that UNROUNDED speed exceeds 1e-6 m/s; course is
`(degrees(atan2(east, north)) + 360) % 360` rounded to 9 decimals with 360 mapped to 0; speed
and climb are rounded to 6. Below the threshold the motion is still reported, with a null
course. Static, BODY-frame and pole values give no motion at all: null, never an invented zero.
A non-finite east, north or up (which finite binary32 input cannot produce) is E_GEODESY rather
than a NaN in the output (proposed CR-new-R1-02).
A position does not depend on velocity, acceleration, algorithm or time: nothing here
extrapolates between updates (R20).

`path` of both errors is `Spatial`, the attribute whose decoded value could not be projected
(proposed CR-new-R1-01; CR-L01 names no form for projection). Every message is fixed text: a
float is never formatted here, nor rounded or compared through a string.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from synapse_hla import errors
from synapse_hla.errors import HlaError

# --- WGS84 and the profile's bounds, SPEC:140-146 ---------------------------------------------------

A = 6378137.0
INVERSE_FLATTENING = 298.257223563
F = 1 / INVERSE_FLATTENING
B = A * (1 - F)
E2 = F * (2 - F)

#: The inclusive range of the ECEF norm this profile projects, metres (R29).
ECEF_NORM_MIN_M = 1_000_000.0
ECEF_NORM_MAX_M = 100_000_000.0
#: Closer than this to the polar axis, the pole case applies (metres).
POLE_AXIS_M = 1e-8
#: The iteration stops when a step changes the latitude by at most this (radians).
CONVERGENCE_RAD = 1e-14
#: The most latitude steps the specification allows.
MAX_ITERATIONS = 32
#: How far beyond +-90 degrees a latitude may be and still count as roundoff (degrees).
LATITUDE_ROUNDOFF_DEG = 1e-10
#: Course is computed only above this unrounded horizontal speed (metres per second).
SPEED_THRESHOLD_MPS = 1e-6
#: Decimal places of the emitted numbers (R30, SPEC:146).
ANGLE_PLACES = 9
LENGTH_PLACES = 6
#: The algorithms whose velocity is in the WORLD frame and is projected (SPEC:146).
WORLD_VELOCITY_ALGORITHMS = frozenset({2, 3, 4, 5})

#: Where both errors of this module point (CR-new-R1-01).
PATH = "Spatial"


class Geodetic(NamedTuple):
    """The unrounded result of the inverse transform, before emission.

    `latitude_deg` is already clamped and `longitude_deg` already has +180 replaced by -180;
    `latitude_rad` and `longitude_rad` are the converged latitude and the plain `atan2(y, x)`,
    the angles the ENU rotation uses. In the pole case the two radian values are not used and
    are set to the pole's latitude and to 0.
    """

    latitude_deg: float
    longitude_deg: float
    height_m: float
    latitude_rad: float
    longitude_rad: float
    pole: bool


class Projection(NamedTuple):
    """What section 9 makes of one decoded Spatial value.

    `position` is `{"lat", "lon", "alt_m"}`, the three emitted numbers; the projector adds the
    constant fields of R30. `kinematics` is `{"speed_mps", "course_deg", "climb_mps"}`, or None
    where section 9 gives no motion (algorithms 1 and 6-9, and the pole case). The projector of
    round R3 is to list "ecef-velocity-to-enu" among the transformations exactly when it is not
    None (SPEC:134).
    """

    position: dict
    kinematics: dict | None


def project_spatial(spatial: dict, *, max_iterations: int = MAX_ITERATIONS) -> Projection:
    """Position and motion of one decoded Spatial value (the `value` of `decode_attribute`).

    Raises `HlaError` E_ECEF_RANGE or E_GEODESY, path `Spatial`; returns nothing partial. The
    input is only read.
    """
    x, y, z = spatial["position_ecef_m"]
    check_ecef(x, y, z)
    geo = geodetic(x, y, z, max_iterations=max_iterations)
    position = emitted_position(geo.latitude_deg, geo.longitude_deg, geo.height_m)
    if geo.pole or spatial["algorithm"] not in WORLD_VELOCITY_ALGORITHMS:
        return Projection(position, None)
    east, north, up = enu(geo.latitude_rad, geo.longitude_rad, spatial["velocity_mps"])
    return Projection(position, emitted_kinematics(east, north, up))


def check_ecef(x: float, y: float, z: float) -> None:
    """R29's gate: finite components and an inclusive norm range, else E_ECEF_RANGE."""
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        raise HlaError(errors.E_ECEF_RANGE, PATH, "an ECEF position component is not finite")
    norm = math.hypot(x, y, z)
    if not (ECEF_NORM_MIN_M <= norm <= ECEF_NORM_MAX_M):
        raise HlaError(errors.E_ECEF_RANGE, PATH,
                       "the ECEF position is not between 1,000,000 and 100,000,000 metres from "
                       "the centre of the Earth")


def geodetic(x: float, y: float, z: float, *, max_iterations: int = MAX_ITERATIONS) -> Geodetic:
    """The unrounded WGS84 latitude, longitude and height of a gated ECEF position."""
    if type(max_iterations) is not int or max_iterations < 1:
        raise ValueError("max_iterations must be a positive int")
    p = math.hypot(x, y)
    if p < POLE_AXIS_M:
        # The gate keeps z away from zero here (|z| >= ~1e6), so its sign is the pole's.
        latitude_deg = 90.0 if z > 0 else -90.0
        latitude_rad = math.pi / 2 if z > 0 else -math.pi / 2
        height = abs(z) - B
        return _settled(latitude_deg, 0.0, height, latitude_rad, 0.0, True)
    longitude_rad = math.atan2(y, x)
    latitude = math.atan2(z, p * (1 - E2))
    for _ in range(max_iterations):
        n = A / math.sqrt(1 - E2 * math.sin(latitude) ** 2)
        following = math.atan2(z + E2 * n * math.sin(latitude), p)
        change = abs(following - latitude)
        latitude = following
        if change <= CONVERGENCE_RAD:
            break
    else:
        raise HlaError(errors.E_GEODESY, PATH,
                       "the geodetic latitude did not converge within the allowed iterations")
    n = A / math.sqrt(1 - E2 * math.sin(latitude) ** 2)
    if abs(math.cos(latitude)) >= 0.5:
        height = p / math.cos(latitude) - n
    else:
        height = z / math.sin(latitude) - n * (1 - E2)
    return _settled(math.degrees(latitude), math.degrees(longitude_rad), height,
                    latitude, longitude_rad, False)


def _settled(latitude_deg: float, longitude_deg: float, height: float,
             latitude_rad: float, longitude_rad: float, pole: bool) -> Geodetic:
    """The non-finite check, the roundoff clamp and the first +180 wrap of SPEC:140-142."""
    if not (math.isfinite(latitude_deg) and math.isfinite(longitude_deg)
            and math.isfinite(height)):
        raise HlaError(errors.E_GEODESY, PATH, "the geodetic result is not finite")
    if abs(latitude_deg) > 90.0:
        if abs(latitude_deg) - 90.0 > LATITUDE_ROUNDOFF_DEG:
            raise HlaError(errors.E_GEODESY, PATH,
                           "the geodetic latitude lies beyond a pole by more than roundoff")
        latitude_deg = 90.0 if latitude_deg > 0 else -90.0
    if longitude_deg == 180.0:
        longitude_deg = -180.0
    return Geodetic(latitude_deg, longitude_deg, height, latitude_rad, longitude_rad, pole)


def emitted_position(latitude_deg: float, longitude_deg: float, height_m: float) -> dict:
    """R30's rounding, the second +180 wrap and the zero normalisation of COD-02."""
    lat = round(latitude_deg, ANGLE_PLACES)
    lon = round(longitude_deg, ANGLE_PLACES)
    if lon == 180.0:
        lon = -180.0
    alt = round(height_m, LENGTH_PLACES)
    return {"lat": _positive_zero(lat), "lon": _positive_zero(lon), "alt_m": _positive_zero(alt)}


def enu(latitude_rad: float, longitude_rad: float, velocity: list[float]) -> tuple[float, ...]:
    """East, north and up components of an ECEF velocity, SPEC:146 term for term."""
    vx, vy, vz = velocity
    east = -math.sin(longitude_rad) * vx + math.cos(longitude_rad) * vy
    north = (-math.sin(latitude_rad) * math.cos(longitude_rad) * vx
             - math.sin(latitude_rad) * math.sin(longitude_rad) * vy
             + math.cos(latitude_rad) * vz)
    up = (math.cos(latitude_rad) * math.cos(longitude_rad) * vx
          + math.cos(latitude_rad) * math.sin(longitude_rad) * vy
          + math.sin(latitude_rad) * vz)
    return east, north, up


def emitted_kinematics(east: float, north: float, up: float) -> dict:
    """Speed, course and climb from unrounded ENU components (SPEC:146, COD-03)."""
    if not (math.isfinite(east) and math.isfinite(north) and math.isfinite(up)):
        raise HlaError(errors.E_GEODESY, PATH, "the projected velocity is not finite")
    speed = math.hypot(east, north)
    course = None
    if speed > SPEED_THRESHOLD_MPS:
        course = round((math.degrees(math.atan2(east, north)) + 360.0) % 360.0, ANGLE_PLACES)
        if course == 360.0:
            course = 0.0
        course = _positive_zero(course)
    return {"speed_mps": _positive_zero(round(speed, LENGTH_PLACES)),
            "course_deg": course,
            "climb_mps": _positive_zero(round(up, LENGTH_PLACES))}


def _positive_zero(value: float) -> float:
    return 0.0 if value == 0 else value
