"""Section 9 (SPEC:140-146): the ECEF gate, WGS84, emission rounding and ENU motion.

Gate held here: G-R29 (SPEC:140 and its continuation SPEC:142), plus the R18 clause on negative
zero in projected output and the R20 clause on extrapolation. Bound here at the level of
`decode_attribute` followed by `geodesy.project_spatial`: A-BODY, A-STATIC, A-ATTITUDE, A-POLE
(round R3 re-asserts them through `project_state`).

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
- `geodesy.json`: the packaged fixture.
- Round geodetic coordinates turned into ECEF by a closed-form forward transform written in
  this file (`forward`, never the production module). The inverse must give the coordinates
  back: within 1e-8 degrees and 1e-4 metres before rounding, and EXACTLY after rounding, because
  the inverse error (at most about 1e-14 degrees and 2e-8 m on this grid) is far smaller than
  half a unit of the 9th or 6th decimal. That forward transform agrees with PROJ 9.9.0's
  EPSG:4979 -> EPSG:4978 to 5e-13 m on the 175-point grid (run in the R1 build, recorded in its
  report).
- Motion: velocities built from the ENU basis vectors at the point, `v = e*E + n*N + u*U`, so
  that east, north and up are e, n and u by construction; speed, course and climb follow by
  hand (3-4-12 gives 5 m/s at atan(3/4) = 36.869897646 degrees). The velocity is a binary32 on
  the wire, so the comparison allows the quantisation that brings (a few 1e-7), and nothing more.
- Exact pins where the trigonometry is exact (on the equator, at longitudes 0, +-90 and 180) and
  rounding pins from COD-01, derived by hand with the exact binary expansion in a comment.
- `oracle_geodetic` and `oracle_enu`: SPEC:142 and SPEC:146 restated here, operation for
  operation, and compared with the product bit for bit at run time. The prose fixes the order of
  operations down to the last bit (COD-13: the kept latitude, the sin**2 grouping, the branch);
  only a same-machine comparison can hold that, because a literal of an unrounded double would
  depend on the platform's libm.
"""

import ast
import copy
import hashlib
import inspect
import math
import pathlib
import platform
import random
import struct
import sys

import pytest

import synapse_hla
from hla_support import (
    SPATIAL_TABLE, assert_strict_equal, canonical, case, encode_spatial, fixture_json,
)
from synapse_hla import HlaError, decode_attribute, geodesy
from synapse_hla.geodesy import project_spatial

SRC = pathlib.Path(synapse_hla.__file__).resolve().parent

# WGS84 as SPEC:140 writes it, in this file.
WGS_A = 6378137.0
WGS_F = 1 / 298.257223563
WGS_B = WGS_A * (1 - WGS_F)
WGS_E2 = WGS_F * (2 - WGS_F)


def forward(lat_deg, lon_deg, h):
    """The closed-form geodetic -> ECEF transform (independent of the module under test)."""
    phi, lam = math.radians(lat_deg), math.radians(lon_deg)
    n = WGS_A / math.sqrt(1 - WGS_E2 * math.sin(phi) ** 2)
    return ((n + h) * math.cos(phi) * math.cos(lam), (n + h) * math.cos(phi) * math.sin(lam),
            (n * (1 - WGS_E2) + h) * math.sin(phi))


def basis(lat_deg, lon_deg):
    """The ENU unit vectors at a point, in ECEF."""
    phi, lam = math.radians(lat_deg), math.radians(lon_deg)
    east = (-math.sin(lam), math.cos(lam), 0.0)
    north = (-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi))
    up = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
    return east, north, up


def velocity_from_enu(lat_deg, lon_deg, e, n, u):
    east, north, up = basis(lat_deg, lon_deg)
    return tuple(e * east[i] + n * north[i] + u * up[i] for i in range(3))


def spatial(algorithm, position, velocity=None, orientation=(0.0, 0.0, 0.0)):
    """Encode with the tests' encoder, then decode with the product: the decoded `value`."""
    _, _, v_at, a_at, w_at = SPATIAL_TABLE[algorithm]
    data = encode_spatial(
        algorithm, position, orientation,
        (velocity if velocity is not None else (0.0, 0.0, 0.0)) if v_at is not None else None,
        (0.125, -0.375, 1.5) if a_at is not None else None,
        (-0.0625, 0.1875, -2.5) if w_at is not None else None)
    return decode_attribute("Spatial", data)["value"]


def project(algorithm, position, velocity=None, orientation=(0.0, 0.0, 0.0)):
    return project_spatial(spatial(algorithm, position, velocity, orientation))


def refused(call):
    with pytest.raises(HlaError) as info:
        call()
    assert type(info.value) is HlaError
    return info.value.code, info.value.path


def position(lat, lon, alt):
    return {"lat": lat, "lon": lon, "alt_m": alt}


def motion(speed, course, climb):
    return {"speed_mps": speed, "course_deg": course, "climb_mps": climb}


# ================================================================= WGS84 and the fixture, R29

@case("G-R29")
def test_the_wgs84_constants_are_the_specifications():
    """R29 clause 4: a = 6378137 m, 1/f = 298.257223563, f = 1/(1/f), b = a(1-f), e2 = f(2-f).
    b is also the polar z of the pole fixture; e2 is f*(2-f) evaluated in binary64."""
    assert geodesy.A == 6378137.0 and geodesy.INVERSE_FLATTENING == 298.257223563
    assert geodesy.F == 1 / 298.257223563
    assert geodesy.B == 6356752.314245179 == WGS_B
    assert geodesy.E2 == 0.0066943799901413165 == WGS_E2


GEODESY_IDS = ("equator-x", "equator-y", "antimeridian", "north-pole", "south-pole", "origin")


@case("G-R29", paragraphs=("SPEC:142",))
@pytest.mark.parametrize("entry_id", GEODESY_IDS)
def test_every_geodesy_fixture_entry_exactly(entry_id):
    """COD-08 (1): each entry of geodesy.json, exact to the bit and the sign of zero.

    R29 clause 5 (ECEF axes: x to (0, 0), y to (0, 90), z to the north pole), clause 6 (+180
    written -180), SPEC:142's pole case (latitude +-90, longitude 0, height |z| - b) and the
    gate (the origin is E_ECEF_RANGE)."""
    entry = [e for e in fixture_json("geodesy.json") if e["id"] == entry_id]
    assert len(entry) == 1
    entry = entry[0]
    if "error" in entry:
        assert entry["error"] == "E_ECEF_RANGE"
        assert refused(lambda: project(1, entry["ecef_m"])) == ("E_ECEF_RANGE", "Spatial")
        return
    result = project(1, entry["ecef_m"])
    lat, lon, alt = entry["expected"]
    assert_strict_equal(result.position, position(lat, lon, alt))
    assert result.kinematics is None


# ============================================================================ the gate, R29

@case("G-R29")
@pytest.mark.parametrize("ecef,expected", [
    ((1e6, 0.0, 0.0), position(0.0, 0.0, -5378137.0)),          # 1e6 - a
    ((0.0, -1e6, 0.0), position(0.0, -90.0, -5378137.0)),
    ((0.0, 1e8, 0.0), position(0.0, 90.0, 93621863.0)),          # 1e8 - a
    ((0.0, 0.0, 1e6), position(90.0, 0.0, -5356752.314245)),     # 1e6 - b, exact binary
    # -5356752.31424517929553985595703125, rounded to 6 decimals
    ((0.0, 0.0, -1e8), position(-90.0, 0.0, 93643247.685755)),   # 1e8 - b
    # = 93643247.68575482070446014404296875 exactly, rounded to 6 decimals
])
def test_the_norm_bounds_are_inclusive(ecef, expected):
    """R29 clause 1 and COD-11: 1e6 and 1e8 metres are accepted on every axis."""
    result = project(2, ecef, (1.0, 2.0, 3.0))
    assert_strict_equal(result.position, expected)


@case("G-R29")
def test_just_outside_the_norm_bounds_is_e_ecef_range():
    """R29 clauses 1 and 2: the next double below 1e6 and above 1e8, on each axis, both signs."""
    below, above = math.nextafter(1e6, 0.0), math.nextafter(1e8, math.inf)
    assert (below, above) == (999999.9999999999, 100000000.00000001)
    for magnitude in (below, above):
        for axis in range(3):
            for sign in (1.0, -1.0):
                ecef = [0.0, 0.0, 0.0]
                ecef[axis] = sign * magnitude
                assert refused(lambda: project(2, ecef, (1.0, 2.0, 3.0))) == (
                    "E_ECEF_RANGE", "Spatial"), ecef


@case("G-R29")
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_component_is_e_ecef_range(bad):
    """R29 clause 1: all components finite. The decoder refuses such a value first; the gate
    holds on its own for any caller that hands it one."""
    for axis in range(3):
        value = {"algorithm": 1, "frame": "WORLD", "position_ecef_m": [WGS_A, 0.0, 0.0],
                 "velocity_mps": None}
        value["position_ecef_m"][axis] = bad
        assert refused(lambda: project_spatial(value)) == ("E_ECEF_RANGE", "Spatial")


@case("G-R29")
@pytest.mark.parametrize("ecef", [(0.0, 0.0, 0.0), (1e9, 0.0, 0.0), (0.0, 0.0, 999.0),
                                  (1.7976931348623157e308, 1.7976931348623157e308, 0.0)])
def test_the_bound_is_the_profiles_not_hlas(ecef):
    """R29 clause 3: an implementation limit, not a limit of HLA. The decoder accepts the
    position (the Spatial is VALID); only projection refuses it, and it returns nothing partial.
    The largest doubles overflow hypot to inf, which is outside the range, not an exception."""
    value = spatial(2, ecef, (1.0, 2.0, 3.0))
    assert value["position_ecef_m"] == list(ecef)
    assert refused(lambda: project_spatial(value)) == ("E_ECEF_RANGE", "Spatial")


# ===================================================================== the pole case, SPEC:142

@case("G-R29", paragraphs=("SPEC:142",))
@case("A-POLE")
def test_a_pole_position_with_velocity_has_longitude_0_and_no_motion():
    """A-POLE; SPEC:142 'When p<1e-8 set latitude=sign(z)*90 degrees, longitude=0,
    altitude=abs(z)-b'; SPEC:146 'At the p<1e-8 pole case kinematics=null'."""
    north = project(2, (0.0, 0.0, WGS_B), (10.0, 0.0, 0.0))
    assert_strict_equal(north.position, position(90.0, 0.0, 0.0))
    assert north.kinematics is None
    south = project(4, (0.0, 0.0, -WGS_B), (0.0, -3.5, 7.25))
    assert_strict_equal(south.position, position(-90.0, 0.0, 0.0))
    assert south.kinematics is None
    # p = 1e-9 < 1e-8: still the pole; z = b + 100 rounds to 6356852.314245179, so |z| - b
    # is 100 plus at most half an ulp of z (5e-10), which rounds to 100.0.
    near = project(3, (1e-9, 0.0, WGS_B + 100.0), (0.0, 5.0, 0.0))
    assert_strict_equal(near.position, position(90.0, 0.0, 100.0))
    assert near.kinematics is None
    below = project(2, (math.nextafter(1e-8, 0.0), 0.0, WGS_B), (10.0, 0.0, 0.0))
    assert below.kinematics is None


@case("G-R29", paragraphs=("SPEC:142",))
def test_p_equal_to_1e_8_is_not_the_pole_case():
    """'p<1e-8' is strict. At p = 1e-8 the iteration runs (latitude 89.99999999999991 rounds to
    90.0) and motion is reported: at longitude 0 near the pole, east is vy and north is about
    -vx, so v = (10, 0, 0) gives speed 10 and course 180; climb is cos(lat)*10 ~ 1.6e-14,
    which rounds to 0."""
    result = project(2, (1e-8, 0.0, WGS_B), (10.0, 0.0, 0.0))
    assert_strict_equal(result.position, position(90.0, 0.0, 0.0))
    assert_strict_equal(result.kinematics, motion(10.0, 180.0, 0.0))


# ===================================================== the iteration, its oracle, E_GEODESY

def oracle_geodetic(x, y, z):
    """SPEC:142 restated: (lat_deg, lon_deg, h, lat_rad, lon_rad, pole, iterations)."""
    p = math.hypot(x, y)
    if p < 1e-8:
        return (90.0 if z > 0 else -90.0), 0.0, abs(z) - WGS_B, None, None, True, 0
    lam = math.atan2(y, x)
    lat = math.atan2(z, p * (1 - WGS_E2))
    for steps in range(1, 33):
        n = WGS_A / math.sqrt(1 - WGS_E2 * math.sin(lat) ** 2)
        following = math.atan2(z + WGS_E2 * n * math.sin(lat), p)
        change = abs(following - lat)
        lat = following
        if change <= 1e-14:
            break
    else:
        raise AssertionError("no convergence")
    n = WGS_A / math.sqrt(1 - WGS_E2 * math.sin(lat) ** 2)
    if abs(math.cos(lat)) >= 0.5:
        h = p / math.cos(lat) - n
    else:
        h = z / math.sin(lat) - n * (1 - WGS_E2)
    lon_deg = math.degrees(lam)
    return math.degrees(lat), (-180.0 if lon_deg == 180.0 else lon_deg), h, lat, lam, False, steps


def oracle_enu(lat, lam, v):
    """SPEC:146 restated, term for term."""
    vx, vy, vz = v
    east = -math.sin(lam) * vx + math.cos(lam) * vy
    north = (-math.sin(lat) * math.cos(lam) * vx - math.sin(lat) * math.sin(lam) * vy
             + math.cos(lat) * vz)
    up = (math.cos(lat) * math.cos(lam) * vx + math.cos(lat) * math.sin(lam) * vy
          + math.sin(lat) * vz)
    return east, north, up


def bits(number):
    return struct.pack(">d", number)


def oracle_points():
    """Deterministic points: the 175-point grid, 20,000 geodetic points over every latitude band
    (both altitude branches) and every height the gate admits, and 400 points within 1e-11 to
    1e3 m of the polar axis (about a fifth of them inside the 1e-8 m pole case).

    20,000 because a last-bit difference is rare: writing the final N as e2*s*s instead of
    e2*s**2 moves the height's last bit at only a few points in this stream (the first at its
    3,704th point), and the set must contain some of them to hold the grouping."""
    points = [forward(*g) for g in GRID]
    rng = random.Random(142)
    for _ in range(20_000):
        lat = -89.9999 + rng.random() * 179.9998
        lon = -180.0 + rng.random() * 360.0
        h = -5000.0 + rng.random() * 9.0e7
        points.append(forward(lat, lon, h))
    rng = random.Random(1428)
    for _ in range(400):
        p = 10.0 ** (-11.0 + rng.random() * 14.0)
        angle = rng.random() * 2.0 * math.pi
        z = (1.0 if rng.random() < 0.5 else -1.0) * (WGS_B - 2000.0 + rng.random() * 4.0e7)
        points.append((p * math.cos(angle), p * math.sin(angle), z))
    return points


@case("G-R29", paragraphs=("SPEC:142",))
def test_the_iteration_branches_and_kept_latitude_match_spec_142_bit_for_bit():
    """SPEC:142: initial atan2(z, p(1-e2)); N = a/sqrt(1 - e2 sin^2); next = atan2(z + e2 N sin,
    p) until the change is <= 1e-14; keep the last value (COD-13); recompute N; p/cos - N where
    |cos| >= 0.5, else z/sin - N(1-e2). Every unrounded output equals the restatement's."""
    counts = {"pole": 0, "cos-branch": 0, "sin-branch": 0}
    for x, y, z in oracle_points():
        got = geodesy.geodetic(x, y, z)
        lat_deg, lon_deg, h, lat, lam, pole, _ = oracle_geodetic(x, y, z)
        assert got.pole is pole, (x, y, z)
        assert (bits(got.latitude_deg), bits(got.longitude_deg), bits(got.height_m)) == (
            bits(lat_deg), bits(lon_deg), bits(h)), (x, y, z)
        if pole:
            counts["pole"] += 1
            continue
        assert (bits(got.latitude_rad), bits(got.longitude_rad)) == (bits(lat), bits(lam))
        counts["cos-branch" if abs(math.cos(lat)) >= 0.5 else "sin-branch"] += 1
    # Each branch was reached many times (a fact about the point set, not an expectation).
    assert min(counts.values()) > 50, counts


#: (lat, lon, h) and the number of steps the iteration takes there, from `oracle_geodetic`
#: (the change at the step before the last is 5.8e-14 and 3.2e-14 respectively, well above the
#: 1e-14 threshold, so the count does not hang on the last bit).
ITERATION_POINTS = (((30.0, 40.0, 1000.0), 5), ((45.0, 0.0, 1.0e6), 6), ((45.0, 0.0, 0.0), 1))


@case("G-R29", paragraphs=("SPEC:142",))
@pytest.mark.parametrize("point,steps", ITERATION_POINTS)
def test_convergence_on_the_last_allowed_step_counts_and_one_fewer_is_e_geodesy(point, steps):
    """SPEC:142 'at most 32 iterations' and 'Nonconvergence ... E_GEODESY', through the
    iteration bound (COD-12: no finite in-gate input fails to converge within 32)."""
    ecef = forward(*point)
    assert oracle_geodetic(*ecef)[6] == steps
    value = spatial(2, ecef, (1.0, 2.0, 3.0))
    assert_strict_equal(project_spatial(value, max_iterations=steps),
                        project_spatial(value))
    if steps > 1:
        assert refused(lambda: project_spatial(value, max_iterations=steps - 1)) == (
            "E_GEODESY", "Spatial")
    assert geodesy.MAX_ITERATIONS == 32
    assert inspect.signature(project_spatial).parameters["max_iterations"].default == 32
    assert inspect.signature(project_spatial).parameters["max_iterations"].kind is (
        inspect.Parameter.KEYWORD_ONLY)


@pytest.mark.parametrize("bound", [0, -1, 1.5, True, None, "32"])
def test_the_iteration_bound_must_be_a_positive_int(bound):
    with pytest.raises(ValueError):
        geodesy.geodetic(WGS_A, 0.0, 0.0, max_iterations=bound)


# 90 degrees lies in [64, 128), where the spacing of doubles is 2^-46 = 1.4210854715202004e-14;
# 1e-10 / 2^-46 = 7036.87, so 90 + 7036 * 2^-46 is the last double within 1e-10 of 90 and
# 90 + 7037 * 2^-46 the first beyond it.
LAST_ROUNDOFF = 90.0 + 7036 * 2.0 ** -46
FIRST_BEYOND = 90.0 + 7037 * 2.0 ** -46


@case("G-R29", paragraphs=("SPEC:142",))
def test_the_latitude_clamp_takes_roundoff_only():
    """SPEC:142 'Clamp only floating roundoff latitude exceeding 90 by <=1e-10 degrees;
    otherwise fail', for both signs (COD-12). No data reaches it; this drives the step that
    settles the unrounded result directly."""
    assert math.nextafter(LAST_ROUNDOFF, 100.0) == FIRST_BEYOND
    for sign in (1.0, -1.0):
        settled = geodesy._settled(sign * LAST_ROUNDOFF, 10.0, 5.0, 0.0, 0.0, False)
        assert_strict_equal(settled.latitude_deg, sign * 90.0)
        for beyond in (FIRST_BEYOND, 90.0 + 1e-6, 180.0):
            assert refused(lambda: geodesy._settled(sign * beyond, 10.0, 5.0, 0.0, 0.0,
                                                    False)) == ("E_GEODESY", "Spatial")
    for inside in (90.0, -90.0, 89.999, 0.0):
        assert geodesy._settled(inside, 10.0, 5.0, 0.0, 0.0, False).latitude_deg == inside


@case("G-R29", paragraphs=("SPEC:142",))
@pytest.mark.parametrize("lat,lon,h", [(math.nan, 0.0, 0.0), (0.0, math.inf, 0.0),
                                       (0.0, 0.0, -math.inf), (math.inf, 0.0, 0.0)])
def test_a_non_finite_result_is_e_geodesy(lat, lon, h):
    """SPEC:142 'a nonfinite result suppresses projection with E_GEODESY' (unreachable from
    finite in-gate data, COD-12)."""
    assert refused(lambda: geodesy._settled(lat, lon, h, 0.0, 0.0, False)) == (
        "E_GEODESY", "Spatial")


def test_a_non_finite_velocity_projection_is_e_geodesy():
    """Proposed CR-new-R1-02: motion is never emitted with a non-finite number either."""
    for components in ((math.nan, 0.0, 0.0), (0.0, math.inf, 0.0), (0.0, 0.0, -math.inf)):
        assert refused(lambda: geodesy.emitted_kinematics(*components)) == (
            "E_GEODESY", "Spatial")


# ============================================================ negative zero and rounding

@case("G-R29", paragraphs=("SPEC:142",))
@pytest.mark.parametrize("ecef", [(WGS_A, -1e-6, 0.0), (WGS_A, 0.0, -1e-6), (WGS_A, -0.0, -0.0)])
def test_a_tiny_negative_or_negative_zero_is_emitted_as_positive_zero(ecef):
    """SPEC:142 'Normalize negative zero to zero', applied after rounding (COD-02): longitude
    -8.98e-12 and latitude -9.04e-12 round to -0.0 and are written 0.0."""
    result = project(2, ecef, (0.0, 10.0, 0.0))
    assert_strict_equal(result.position, position(0.0, 0.0, 0.0))
    assert_strict_equal(result.kinematics, motion(10.0, 90.0, 0.0))


@case("G-R18")
def test_negative_zero_is_kept_in_decoded_values_and_normalised_only_in_projected_output():
    """R18 'Negative zero is permitted and normalized to positive zero only in projected
    numeric output' (COD-15): the decoded value keeps -0.0, before and after projection."""
    value = spatial(2, (WGS_A, -0.0, -0.0), (-0.0, 10.0, -0.0), orientation=(-0.0, 0.0, -0.0))
    before = copy.deepcopy(value)
    result = project_spatial(value)
    assert_strict_equal(value, before)
    assert_strict_equal(value["position_ecef_m"], [WGS_A, -0.0, -0.0])
    assert_strict_equal(value["velocity_mps"], [-0.0, 10.0, -0.0])
    assert_strict_equal(value["orientation_rad"], [-0.0, 0.0, -0.0])
    assert_strict_equal(result.position, position(0.0, 0.0, 0.0))
    assert_strict_equal(result.kinematics, motion(10.0, 90.0, 0.0))


#: COD-01: CPython round() on the exact binary value, ties to even. Exact binary expansions:
#: 0.1234567895 = 0.12345678949999999707... -> 0.123456789 (Decimal(repr) would give ...790);
#: 2.0000005 = 2.00000050000000006988... -> 2.000001 (Decimal(repr) would give 2.000000);
#: 100.0078125 is exact, a true tie -> 100.007812 (half-up would give ...813);
#: 29017031.5968535 = ...596853498369... -> 29017031.596853 (Decimal(repr): ...854);
#: 27913390.5195015 = ...519501499831... -> 27913390.519501 (Decimal(repr): ...502);
#: 52739506.0297245 = ...029724501073... -> 52739506.029725 (Decimal(repr): ...724);
#: 20141334.7296335 = ...729633498936... -> 20141334.729633 (Decimal(repr): ...634).
ROUNDING = (
    ((0.1234567895, 0.1234567895, 2.0000005), position(0.123456789, 0.123456789, 2.000001)),
    ((-0.1234567895, -0.1234567895, -2.0000005),
     position(-0.123456789, -0.123456789, -2.000001)),
    ((0.0, 0.0, 100.0078125), position(0.0, 0.0, 100.007812)),
    ((0.0, 0.0, 29017031.5968535), position(0.0, 0.0, 29017031.596853)),
    ((0.0, 0.0, 27913390.5195015), position(0.0, 0.0, 27913390.519501)),
    ((0.0, 0.0, 52739506.0297245), position(0.0, 0.0, 52739506.029725)),
    ((0.0, 0.0, 20141334.7296335), position(0.0, 0.0, 20141334.729633)),
    ((-4e-10, 4e-10, -4e-7), position(0.0, 0.0, 0.0)),
    ((0.0, 179.9999999996, 0.0), position(0.0, -180.0, 0.0)),
    ((0.0, -179.9999999996, 0.0), position(0.0, -180.0, 0.0)),
    ((0.0, 179.9999999994, 0.0), position(0.0, 179.999999999, 0.0)),
)


@pytest.mark.parametrize("unrounded,expected", ROUNDING,
                         ids=[f"round{i}" for i in range(len(ROUNDING))])
def test_emission_rounds_half_even_on_the_binary_value_then_wraps_then_normalises(unrounded,
                                                                                  expected):
    """R30 (round 9/9/6, half-even), 'wrap longitude again if rounded longitude becomes +180',
    then COD-02's zero normalisation: the step that turns unrounded degrees into output."""
    assert_strict_equal(geodesy.emitted_position(*unrounded), expected)


def test_a_rounding_tie_reached_through_the_whole_projection():
    """x = 6378237.0078125 is a + 100 + 2^-7, exactly representable; on the equator p = x,
    N = a and h = p - N = 100.0078125 exactly, a tie that rounds to even: 100.007812."""
    result = project(1, (6378237.0078125, 0.0, 0.0))
    assert_strict_equal(result.position, position(0.0, 0.0, 100.007812))


# ============================================================================ longitude, R29

@case("G-R29")
@pytest.mark.parametrize("y", [0.0, -0.0, 1e-6, -1e-6])
def test_longitude_is_atan2_and_plus_180_is_written_minus_180(y):
    """R29 clause 6 and COD-10: atan2(+0, -a) is +180 exactly and becomes -180; atan2(-0, -a)
    is -180; +-1e-6 m off the antimeridian gives +-179.99999999999102, which rounds to +-180
    and is written -180 either way."""
    result = project(1, (-WGS_A, y, 0.0))
    assert_strict_equal(result.position, position(0.0, -180.0, 0.0))


@case("G-R29")
def test_the_unrounded_longitude_is_already_wrapped_and_its_radians_are_not():
    """The first +180 wrap of SPEC:140 (COD-10), in `geodetic()` itself and not only in the
    emitted position (review finding R1-r1-F1, item 4). At (-a, +0.0, 0.0): p = a, far from the
    pole case; IEEE 754 atan2(+0.0, x < 0) is +pi exactly (the double nearest pi), and
    math.degrees of that double is 180.0 exactly (CPython multiplies by the double nearest
    180/pi, and the product rounds to 180.0). The wrap writes it -180.0. COD-10 keeps the radians
    unnormalised for ENU, so `longitude_rad` stays +pi. With y = -0.0 atan2 gives -pi and -180.0
    with no wrap needed, so the sign of zero in y must not show in the degrees."""
    plus = geodesy.geodetic(-WGS_A, 0.0, 0.0)
    assert_strict_equal(plus.longitude_deg, -180.0)
    assert_strict_equal(plus.longitude_rad, math.pi)
    minus = geodesy.geodetic(-WGS_A, -0.0, 0.0)
    assert_strict_equal(minus.longitude_deg, -180.0)
    assert_strict_equal(minus.longitude_rad, -math.pi)
    assert_strict_equal(plus.latitude_deg, 0.0)


@case("G-R29")
def test_altitude_is_ellipsoidal_with_no_geoid_or_terrain():
    """R29 clause 7: no terrain, geoid or map projection. On the equator at longitude 0 the
    height above the ellipsoid of (a + h, 0, 0) is exactly h; a geoid would move it by the
    local undulation (some 17 m there) and terrain by the ground's height."""
    for h in (-1000.0, 0.0, 8848.0, 1.0e6, 9.0e7):
        result = project(1, (WGS_A + h, 0.0, 0.0))
        assert_strict_equal(result.position, position(0.0, 0.0, h))


@case("G-R29")
def test_the_geodesy_module_uses_arithmetic_only():
    """R29 clause 7: no external service, file or data set. The module imports math and the
    package's error type and nothing else (the purity test bars files, clocks and sockets)."""
    tree = ast.parse((SRC / "geodesy.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"__future__", "math", "typing", "synapse_hla", "synapse_hla.errors"}


# ===================================================== the 175-point grid round trip, COD-08

GRID = [(lat, lon, h) for lat in (-89.999, -75.0, -45.0, 0.0, 45.0, 75.0, 89.999)
        for lon in (-180.0, -90.0, 0.0, 90.0, 179.999)
        for h in (-1000.0, 0.0, 10000.0, 1000000.0, 90000000.0)]


@case("G-R29", paragraphs=("SPEC:142",))
def test_the_175_point_grid_round_trips_within_tolerance_and_exactly_after_rounding():
    """COD-08 (2): the grid of the handoff's geodesy check, forward by the closed form, inverse
    by the product: within 1e-8 degrees and 1e-4 metres unrounded, and equal to the grid values
    once rounded (longitude -180 written -180). |lat| 75 and 89.999 use the z/sin branch."""
    assert len(GRID) == 175
    worst_lat = worst_alt = 0.0
    for lat, lon, h in GRID:
        ecef = forward(lat, lon, h)
        geo = geodesy.geodetic(*ecef)
        worst_lat = max(worst_lat, abs(geo.latitude_deg - lat))
        worst_alt = max(worst_alt, abs(geo.height_m - h))
        assert abs(geo.latitude_deg - lat) < 1e-8 and abs(geo.height_m - h) < 1e-4
        assert abs((geo.longitude_deg - lon + 180.0) % 360.0 - 180.0) < 1e-8
        result = project(1, ecef)
        assert_strict_equal(result.position, position(lat, -180.0 if lon == -180.0 else lon, h))
    assert worst_lat < 1e-13 and worst_alt < 1e-7


# ===================================================================== motion, SPEC:146

#: (lat, lon, h), (east, north, up) and the hand-derived speed, course and climb:
#: 3-4-12 -> speed 5, course atan(3/4) = 36.8698976458440213 deg; (-6, 8) -> speed 10, course
#: 360 - 36.8698976458440213 = 323.1301023541559787; (0, -7) -> 180; (-20, -20) -> speed
#: 20*sqrt(2) = 28.2842712474619010, course 225; (5, 0) -> 90; (0, 9) -> 0.
ENU_POINTS = (
    ((30.0, 40.0, 1000.0), (3.0, 4.0, 12.0), (5.0, 36.8698976458440213, 12.0)),
    ((-45.0, -120.0, 250.0), (-6.0, 8.0, -2.5), (10.0, 323.1301023541559787, -2.5)),
    ((0.0, 90.0, 0.0), (0.0, -7.0, 1.0), (7.0, 180.0, 1.0)),
    ((75.0, 170.0, 12000.0), (-20.0, -20.0, 0.5), (28.2842712474619010, 225.0, 0.5)),
    ((89.9, 45.0, 100.0), (5.0, 0.0, 0.0), (5.0, 90.0, 0.0)),
    ((-60.0, -10.0, -100.0), (0.0, 9.0, -4.0), (9.0, 0.0, -4.0)),
)
#: What binary32 quantisation of a velocity of up to ~30 m/s can move the result by: half an
#: ulp per component (2^-20 at 16-32 m/s, about 1e-6), plus the 6-decimal rounding. Course: that
#: over the smallest speed here (5 m/s), in degrees, about 2e-5.
SPEED_TOLERANCE = 3e-6
COURSE_TOLERANCE = 5e-5


def course_error(got, expected):
    return abs((got - expected + 180.0) % 360.0 - 180.0)


@pytest.mark.parametrize("point,enu,expected", ENU_POINTS,
                         ids=[f"lat{p[0][0]}-lon{p[0][1]}" for p in ENU_POINTS])
@pytest.mark.parametrize("algorithm", [2, 3, 4, 5])
def test_world_velocity_is_projected_onto_the_enu_basis(algorithm, point, enu, expected):
    """CDV-01: ENU at non-trivial latitude and longitude, from the basis vectors. Every WORLD
    variant projects; the position is the point itself."""
    result = project(algorithm, forward(*point), velocity_from_enu(*point[:2], *enu))
    lat, lon, h = point
    assert_strict_equal(result.position, position(lat, lon, h))
    speed, course, climb = expected
    got = result.kinematics
    assert list(got) == ["speed_mps", "course_deg", "climb_mps"]
    assert abs(got["speed_mps"] - speed) < SPEED_TOLERANCE, got
    assert course_error(got["course_deg"], course) < COURSE_TOLERANCE, got
    assert abs(got["climb_mps"] - climb) < SPEED_TOLERANCE, got
    assert 0.0 <= got["course_deg"] < 360.0


#: Exact pins on the equator, where sin and cos of the longitude are 0, +-1 or ~6e-17. At
#: longitude 90, east = -vx, north = vz, up = vy (+ 6e-17 vx): v = (-10, 0, 3) gives speed
#: sqrt(109) = 10.44030650891055018 -> 10.440307, course atan(10/3) = 73.3007557660063782 deg
#: -> 73.300755766, climb -6.1e-16 -> 0.0. At longitude 180 (atan2 gives pi), east = -vy:
#: v = (0, 5, 0) is due west, 270. At -90, east = vx: v = (10, 0, 0) is due east, 90.
EQUATOR_PINS = (
    ((0.0, WGS_A, 0.0), (-10.0, 0.0, 3.0), motion(10.440307, 73.300755766, 0.0)),
    ((-WGS_A, 0.0, 0.0), (0.0, 5.0, 0.0), motion(5.0, 270.0, 0.0)),
    ((0.0, -WGS_A, 0.0), (10.0, 0.0, 0.0), motion(10.0, 90.0, 0.0)),
    ((WGS_A, 0.0, 0.0), (0.0, 10.0, 0.0), motion(10.0, 90.0, 0.0)),        # east
    ((WGS_A, 0.0, 0.0), (0.0, 0.0, 10.0), motion(10.0, 0.0, 0.0)),         # north
    ((WGS_A, 0.0, 0.0), (0.0, -10.0, 0.0), motion(10.0, 270.0, 0.0)),      # west
    ((WGS_A, 0.0, 0.0), (0.0, 0.0, -10.0), motion(10.0, 180.0, 0.0)),      # south
    ((WGS_A, 0.0, 0.0), (10.0, 0.0, 0.0), motion(0.0, None, 10.0)),        # straight up
    ((WGS_A, 0.0, 0.0), (0.0, 100.0078125, 0.0), motion(100.007812, 90.0, 0.0)),  # speed tie
    ((WGS_A, 0.0, 0.0), (-100.0078125, 0.0, 0.0), motion(0.0, None, -100.007812)),  # climb tie
)


@pytest.mark.parametrize("ecef,velocity,expected", EQUATOR_PINS,
                         ids=[f"pin{i}" for i in range(len(EQUATOR_PINS))])
def test_motion_on_the_equator_exactly(ecef, velocity, expected):
    """SPEC:146 and COD-03: course from atan2(east, north) + 360 modulo 360; speed and climb
    rounded to 6 (ties to even); a straight-up velocity is motion with no course, not null."""
    assert_strict_equal(project(2, ecef, velocity).kinematics, expected)


def test_the_cdv01_worked_point_exactly():
    """CDV-01's worked point: (30, 40, 1000 m) with the binary32-exact ECEF velocity (3, 5, 7).

    By hand with 60-digit decimal trigonometry (sin 30 = 1/2, the rest by series):
    east = -sin40*3 + cos40*5 = 1.90185938653527219704; north = -sin30 cos40*3 - sin30 sin40*5
    + cos30*7 = 3.30614213759625515874; up = cos30 cos40*3 + cos30 sin40*5 + sin30*7 =
    8.27359384063891202088. Speed sqrt(e^2 + n^2) = 3.81413751196018852703 -> 3.814138; course
    atan(e/n) = 29.90968010865811051715 deg -> 29.909680109; climb -> 8.273594. The nearest of
    these to a rounding boundary is the course, 1.6e-10 deg away; the position this point
    projects from is within about 1e-14 deg of (30, 40)."""
    result = project(2, forward(30.0, 40.0, 1000.0), (3.0, 5.0, 7.0))
    assert_strict_equal(result.position, position(30.0, 40.0, 1000.0))
    assert_strict_equal(result.kinematics, motion(3.814138, 29.909680109, 8.273594))


#: The binary32 neighbours of 1e-6: 358637bd = 9.999999974752427e-07 (below) and 358637be =
#: 1.0000001111620804e-06 (above). Both round to a speed of 1e-06; only the second exceeds the
#: threshold, so only the UNROUNDED comparison tells them apart (COD-03).
BELOW_THRESHOLD = 9.999999974752427e-07
ABOVE_THRESHOLD = 1.0000001111620804e-06


def test_the_course_threshold_compares_the_unrounded_speed():
    assert struct.unpack(">f", bytes.fromhex("358637bd"))[0] == BELOW_THRESHOLD
    assert struct.unpack(">f", bytes.fromhex("358637be"))[0] == ABOVE_THRESHOLD
    above = project(2, (WGS_A, 0.0, 0.0), (0.0, ABOVE_THRESHOLD, 0.0)).kinematics
    below = project(2, (WGS_A, 0.0, 0.0), (0.0, BELOW_THRESHOLD, 0.0)).kinematics
    assert_strict_equal(above, motion(1e-06, 90.0, 0.0))
    assert_strict_equal(below, motion(1e-06, None, 0.0))
    assert_strict_equal(geodesy.emitted_kinematics(1e-6, 0.0, 0.0), motion(1e-06, None, 0.0))


def test_a_course_that_rounds_to_360_is_written_0():
    """east = f32(-1e-12) = -9.999999960041972e-13, north = 10: atan2 gives -1e-13 rad, so the
    course is 360 - 5.7e-12 degrees, which rounds to 360.0 and is written 0.0 (COD-03)."""
    result = project(2, (WGS_A, 0.0, 0.0), (0.0, -9.999999960041972e-13, 10.0))
    assert_strict_equal(result.kinematics, motion(10.0, 0.0, 0.0))
    assert_strict_equal(geodesy.emitted_kinematics(-1e-12, 10.0, -1e-9), motion(10.0, 0.0, 0.0))
    assert_strict_equal(geodesy.emitted_kinematics(0.0, -0.0, -0.0), motion(0.0, None, 0.0))


@pytest.mark.parametrize("seed", [146, 251])
def test_the_enu_rotation_matches_spec_146_bit_for_bit(seed):
    """SPEC:146 term for term, over random points and velocities, against the restatement."""
    rng = random.Random(seed)
    for _ in range(2000):
        ecef = forward(-89.9 + rng.random() * 179.8, -180.0 + rng.random() * 360.0,
                       -1000.0 + rng.random() * 5.0e7)
        geo = geodesy.geodetic(*ecef)
        velocity = [struct.unpack(">f", struct.pack(">f", -400.0 + rng.random() * 800.0))[0]
                    for _ in range(3)]
        got = geodesy.enu(geo.latitude_rad, geo.longitude_rad, velocity)
        expected = oracle_enu(geo.latitude_rad, geo.longitude_rad, velocity)
        assert [bits(g) for g in got] == [bits(e) for e in expected]


# ============================================================== the four A- cases at this level

@case("A-BODY")
@pytest.mark.parametrize("algorithm", [6, 7, 8, 9])
def test_a_body_frame_spatial_has_a_position_no_motion_and_keeps_its_body_values(algorithm):
    """A-BODY: 'Position mapped; kinematics null; body values preserved' — for the handoff's
    vector of each BODY variant and for a value at (30, 40, 1000 m) with every slot non-zero."""
    vector = [v for v in fixture_json("attributes-positive.json")
              if v["id"] == f"SPATIAL-{algorithm}"][0]
    decoded = decode_attribute("Spatial", bytes.fromhex(vector["hex"]))["value"]
    kept = copy.deepcopy(decoded)
    result = project_spatial(decoded)
    assert_strict_equal(result.position, position(0.0, 0.0, 0.0))
    assert result.kinematics is None
    assert_strict_equal(decoded, kept)
    assert decoded["frame"] == "BODY" and decoded["velocity_mps"] == [0.0, 10.0, 0.0]

    value = spatial(algorithm, forward(30.0, 40.0, 1000.0), (-3.5, 7.25, 11.0625),
                    orientation=(0.5, -1.25, 2.75))
    kept = copy.deepcopy(value)
    result = project_spatial(value)
    assert_strict_equal(result.position, position(30.0, 40.0, 1000.0))
    assert result.kinematics is None
    assert_strict_equal(value, kept)
    assert value["velocity_mps"] == [-3.5, 7.25, 11.0625]
    assert value["orientation_rad"] == [0.5, -1.25, 2.75]
    _, _, _, a_at, w_at = SPATIAL_TABLE[algorithm]
    assert value["acceleration_mps2"] == ([0.125, -0.375, 1.5] if a_at else None)
    assert value["angular_velocity_radps"] == ([-0.0625, 0.1875, -2.5] if w_at else None)


@case("A-STATIC")
def test_a_static_spatial_has_no_motion_never_an_inferred_zero():
    """A-STATIC: 'kinematics null, never inferred zero' — for the handoff's vector and at
    several positions; a WORLD variant with a zero velocity, by contrast, IS motion."""
    vector = [v for v in fixture_json("attributes-positive.json") if v["id"] == "SPATIAL-1"][0]
    decoded = decode_attribute("Spatial", bytes.fromhex(vector["hex"]))["value"]
    assert decoded["velocity_mps"] is None
    result = project_spatial(decoded)
    assert_strict_equal(result.position, position(0.0, 0.0, 0.0))
    assert result.kinematics is None
    for point in ((30.0, 40.0, 1000.0), (-75.0, 179.999, 90000000.0), (0.0, -90.0, -1000.0)):
        assert project(1, forward(*point)).kinematics is None
    assert_strict_equal(project(2, (WGS_A, 0.0, 0.0), (0.0, 0.0, 0.0)).kinematics,
                        motion(0.0, None, 0.0))


@case("A-ATTITUDE")
def test_course_follows_world_velocity_not_psi():
    """A-ATTITUDE: psi = 1.0 and WORLD velocity due east at the equator -> course 90, psi kept
    1.0; SPEC:251: course must follow velocity rather than psi. Any attitude gives the same
    motion; due east at (30, 40) is course 90 too."""
    value = spatial(2, (WGS_A, 0.0, 0.0), (0.0, 10.0, 0.0), orientation=(1.0, 0.0, 0.0))
    assert_strict_equal(value["orientation_rad"], [1.0, 0.0, 0.0])
    result = project_spatial(value)
    assert_strict_equal(result.kinematics, motion(10.0, 90.0, 0.0))
    assert_strict_equal(value["orientation_rad"], [1.0, 0.0, 0.0])
    for attitude in ((0.0, 0.0, 0.0), (-2.5, 0.5, 3.0), (3.140625, -1.5, 0.25)):
        assert_strict_equal(project(2, (WGS_A, 0.0, 0.0), (0.0, 10.0, 0.0), attitude).kinematics,
                            motion(10.0, 90.0, 0.0))
    east = project(2, forward(30.0, 40.0, 1000.0), velocity_from_enu(30.0, 40.0, 10.0, 0.0, 0.0),
                   orientation=(1.0, 0.0, 0.0)).kinematics
    assert course_error(east["course_deg"], 90.0) < COURSE_TOLERANCE


# ========================================================= no extrapolation, R20 clause 6

@case("G-R20")
def test_the_position_depends_on_the_position_alone():
    """R20: 'does not extrapolate movement between updates, even when algorithm or velocity is
    known'. The same ECEF position gives the same position for every variant, any velocity,
    acceleration or attitude; and the projection takes no time argument at all."""
    ecef = forward(30.0, 40.0, 1000.0)
    expected = position(30.0, 40.0, 1000.0)
    for algorithm in range(1, 10):
        for velocity in ((0.0, 0.0, 0.0), (250.0, -125.0, 60.0)):
            assert_strict_equal(project(algorithm, ecef, velocity).position, expected)
    assert list(inspect.signature(project_spatial).parameters) == ["spatial", "max_iterations"]


# ============================================================ source rules: floats and text

def _module_tree(name):
    return ast.parse((SRC / f"{name}.py").read_text(encoding="utf-8"))


#: The names a codec message or path may interpolate: each holds an int (a length, a limit, an
#: offset, an octet) or the fixed attribute-name constant.
CODEC_FORMATTED = {"length", "limit", "algorithm", "total", "flag", "offset", "SPATIAL",
                   "FROZEN_OFFSET"}


@pytest.mark.parametrize("module", ["codec", "geodesy"])
def test_no_float_is_formatted_rounded_or_compared_through_a_string(module):
    """Exit criterion of round R1: in the two numeric modules no value goes through text — no
    repr/str/format/ascii/float()/Decimal, no '%' formatting, no `.format`, no float `.hex`,
    no json or decimal import; f-strings only interpolate the int-valued names above, with no
    conversion or format spec, and geodesy has none at all."""
    tree = _module_tree(module)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"repr", "str", "format", "ascii", "float", "Decimal",
                                        "Fraction", "eval"}, node.func.id
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"format", "fromhex", "as_integer_ratio"}
            if node.func.attr == "hex":
                assert module == "codec" and isinstance(node.func.value, ast.BinOp)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            assert not (isinstance(node.left, ast.Constant) and type(node.left.value) is str)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ({a.name for a in node.names} if isinstance(node, ast.Import)
                     else {node.module})
            assert not names & {"decimal", "fractions", "json", "locale", "string"}, names
        if isinstance(node, ast.JoinedStr):
            assert module == "codec", "geodesy builds no text from values"
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    assert part.conversion == -1 and part.format_spec is None
                    assert isinstance(part.value, ast.Name), ast.dump(part)
                    assert part.value.id in CODEC_FORMATTED, part.value.id
    rounds = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "round"]
    assert all(len(n.args) == 2 for n in rounds)
    assert (module == "geodesy") == bool(rounds)


# ================================================ cross-interpreter regression pin (D-19, COD-16)

#: SHA-256 of the canonical outcome lines of `projected_points()`, per platform. NOT a
#: correctness expectation: it was recorded from this code, and its only job is to show that
#: 3.11, 3.12 and 3.14 compute the same bits (the correctness of the same arithmetic is held by
#: the tests above). A platform with another libm may differ in a last bit; a pin for it is
#: recorded there after its interpreters have been seen to agree. A platform without an entry
#: fails this test with the digest it computed (CR-R1-06): that is how a new platform's pin is
#: first seen, never a pass.
#:
#: Platforms differ (CR-L20, the Linux reference run's finding F5): glibc's and Apple's libm
#: give the test's own input generator (`math.cos`, `math.sin`) other last bits for 674 of the
#: 10,000 inputs, and of the 9,326 identical inputs 5 projected altitudes differ by 1e-6 m at
#: heights of 27,451 to 89,704 km. Byte identity across platforms is therefore not promised at
#: such heights; identity across interpreters on one platform is what each entry pins.
CROSS_INTERPRETER_PINS = {
    # DEV-macOS-arm64 (CR-L04): recorded from 3.11.15, 3.12.13 and 3.14.7, which agreed.
    "darwin-arm64": "1989ad7159d77fe68711c8e1a19ca0fce88ca542fb359e608f154eee1242a1c0",
    # DEV-linux-aarch64 (CR-L04, CR-L20): the Linux reference run ref-1 of 2026-10-25 (Ubuntu
    # 24.04 userland, glibc 2.39, aarch64), from Python 3.12.3 ONLY: Ubuntu 24.04 ships one
    # interpreter, so the agreement of interpreters this pin otherwise stands for was not
    # observable there. Recorded from that run's failing message, not computed here.
    "linux-aarch64": "2af1d796a76bb9b08e3c70bc6f573236bb354c24ac4f081c24a8ff753a654a0f",
}


def projected_points():
    """10,000 generated Spatial values through decode and projection, as canonical lines.

    Only `random.Random(seed).random()` is used, whose sequence Python guarantees across
    versions. Every variant, every latitude band, heights inside and outside the gate, the
    polar axis, binary32 velocities up to 1000 m/s, random padding and attitude."""
    rng = random.Random(20261004)
    lines = []
    for index in range(10_000):
        algorithm = 1 + int(rng.random() * 9)
        z_unit = 2.0 * rng.random() - 1.0
        angle = 2.0 * math.pi * rng.random()
        norm = 9.0e5 + rng.random() * 1.0e8
        if index % 50 == 0:
            ecef = (rng.random() * 2e-8, 0.0, (1.0 if z_unit > 0 else -1.0) * norm)
        else:
            ring = math.sqrt(max(0.0, 1.0 - z_unit * z_unit)) * norm
            ecef = (ring * math.cos(angle), ring * math.sin(angle), z_unit * norm)
        triples = [tuple(-1000.0 + 2000.0 * rng.random() for _ in range(3)) for _ in range(4)]
        _, _, v_at, a_at, w_at = SPATIAL_TABLE[algorithm]
        data = encode_spatial(algorithm, ecef, triples[0],
                              triples[1] if v_at else None, triples[2] if a_at else None,
                              triples[3] if w_at else None, frozen=int(rng.random() * 2),
                              padding=bytes(int(rng.random() * 256) for _ in range(10)))
        value = decode_attribute("Spatial", data)["value"]
        try:
            result = project_spatial(value)
            outcome = [value, result.position, result.kinematics]
        except HlaError as error:
            outcome = [value, error.code, error.path]
        lines.append(canonical(outcome))
    return lines


def test_ten_thousand_projected_points_are_identical_on_every_interpreter():
    """Exit criterion 4 of round R1: the same 10,000 outcomes, bit for bit, on 3.11, 3.12 and
    3.14 (check.sh runs this test on all three against the one pin)."""
    lines = projected_points()
    assert len(lines) == 10_000
    assert sum(b'"E_ECEF_RANGE"' in line for line in lines) > 0
    assert sum(b'"course_deg"' in line for line in lines) > 1000
    digest = hashlib.sha256(b"\n".join(lines)).hexdigest()
    key = f"{sys.platform}-{platform.machine()}"
    assert key in CROSS_INTERPRETER_PINS, f"no cross-interpreter pin for {key}: {digest}"
    assert digest == CROSS_INTERPRETER_PINS[key]


def test_projection_reads_its_input_and_returns_new_objects():
    value = spatial(4, forward(30.0, 40.0, 1000.0), (3.0, 4.0, 12.0))
    kept = copy.deepcopy(value)
    first = project_spatial(value)
    first.position["lat"] = 1.0
    first.kinematics["speed_mps"] = 1.0
    assert_strict_equal(value, kept)
    second = project_spatial(value)
    assert second.position["lat"] == 30.0 and second.kinematics["speed_mps"] != 1.0
