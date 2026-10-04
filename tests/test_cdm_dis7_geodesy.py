"""The WGS84 projection and the ENU kinematics of the `dis7` codec, at helper level.

Groups T05 (cases A03 and N11), T06 (case A04), T07 (case A05) and the always-on T16 geodesy
oracle. Every expected value is a literal typed here, an analytical height, the forward
equations of `dis7_support.geodetic_to_ecef` or a closed-form inverse that exists only in this
file; none comes from `ecef_to_geodetic`. The adapter-level halves of these cases (through
`to_cdm`, with notes, residual and replay) are tested elsewhere.
"""
from __future__ import annotations

import inspect
import itertools
import math
import struct

import pytest

from synapse_cdm.adapters import dis7_codec
from synapse_cdm.adapters.dis7_codec import Dis7Error
from tests import dis7_support

A = 6378137.0
B = 6356752.314245179

LAT_TOL = 1e-9
HEIGHT_TOL = 0.001
SPEED_TOL = 1e-6
COURSE_TOL = 1e-7


def circular(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def assert_geodetic(got, expected, *, polar: bool = False) -> None:
    lat, lon, h = expected
    assert got is not None
    assert abs(got[0] - lat) <= LAT_TOL, (got, expected)
    if polar:
        assert -180.0 <= got[1] <= 180.0, (got, expected)
    else:
        assert circular(got[1], lon) <= LAT_TOL, (got, expected)
    assert abs(got[2] - h) <= HEIGHT_TOL, (got, expected)


def assert_kinematics(got, speed, course, climb) -> None:
    assert set(got) == {"speed_mps", "course_deg", "climb_mps"}
    assert abs(got["speed_mps"] - speed) <= SPEED_TOL, got
    assert abs(got["climb_mps"] - climb) <= SPEED_TOL, got
    if course is None:
        assert got["course_deg"] is None, got
    else:
        assert got["course_deg"] is not None, got
        assert circular(got["course_deg"], course) <= COURSE_TOL, got


def positive(value: float) -> bool:
    return math.copysign(1.0, value) == 1.0


def refused(code: str, call, *args) -> Dis7Error:
    with pytest.raises(Dis7Error) as caught:
        call(*args)
    assert caught.value.code == code
    assert caught.value.path == "byte[48]"
    return caught.value


A03 = [  # (lat, lon, h), and its ECEF vector from the forward equations
    ((0.0, 180.0, 35786000.0), (-42164137.0, 5.163617541586048e-09, 0.0)),
    ((49.0, 16.0, 400.0), (4030279.376829747, 1155664.0146248138, 4790860.631304157)),
    ((-45.0, -179.5, 12000.0), (-4525903.821111661, -39496.964280531596, -4495833.690240158)),
    ((89.999, 34.0, -100.0), (92.59705873447245, 62.45750475096009, 6356652.313270481)),
    ((-90.0, 0.0, 0.0), (3.9186209248144716e-10, 0.0, -6356752.314245179)),
]


# CR-19
@pytest.mark.parametrize(("geodetic", "ecef"), A03)
def test_t05_a03_analytical_positions(geodetic, ecef):
    assert math.dist(dis7_support.geodetic_to_ecef(*geodetic), ecef) <= 1e-6
    assert_geodetic(dis7_codec.ecef_to_geodetic(*ecef), geodetic)


# CR-19
def test_t05_a03_pole_branch_is_exact():
    assert dis7_codec.ecef_to_geodetic(0.0, 0.0, B) == (90.0, 0.0, 0.0)
    assert dis7_codec.ecef_to_geodetic(0.0, 0.0, -B) == (-90.0, 0.0, 0.0)
    assert dis7_codec.ecef_to_geodetic(0.0, 0.0, 6356792.314245179) == (90.0, 0.0, 40.0)
    assert dis7_codec.ecef_to_geodetic(0.0, 0.0, -6356792.314245179) == (-90.0, 0.0, 40.0)
    got = dis7_codec.ecef_to_geodetic(-0.0, -0.0, B)
    assert got == (90.0, 0.0, 0.0)
    assert positive(got[1])


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_t05_a03_vector_positions_match_the_bundle(stem):
    position = dis7_support.vector_json(stem, "expected")[0]["position"]
    got = dis7_codec.ecef_to_geodetic(*struct.unpack_from(">ddd", dis7_support.vector_bytes(stem), 48))
    if stem == "unprojectable_with_extensions":
        assert position is None
        assert got is None
    else:
        assert got == (position["lat"], position["lon"], position["alt_m"])


def test_t05_a03_dateline_sign_follows_atan2():
    assert dis7_codec.ecef_to_geodetic(-6379137.0, 0.0, 0.0) == (0.0, 180.0, 1000.0)
    assert dis7_codec.ecef_to_geodetic(-6379137.0, -0.0, 0.0) == (0.0, -180.0, 1000.0)


def test_t05_a03_negative_zero_outputs_are_normalised():
    got = dis7_codec.ecef_to_geodetic(6378257.0, -0.0, -0.0)
    assert got == (0.0, 0.0, 120.0)
    assert all(positive(value) for value in got)


def test_t05_wgs84_constants_are_the_published_values():
    assert dis7_codec.WGS84_A == 6378137.0
    assert dis7_codec.WGS84_F == 0.0033528106647474805
    assert dis7_codec.WGS84_E2 == 0.0066943799901413165
    assert dis7_codec.WGS84_B == 6356752.314245179


N11 = [
    (1.0, 1.0, 1.0),                                      # the case's own vector, r = 1.73 m
    (math.nextafter(1e9, math.inf), 0.0, 0.0),            # 1000000000.0000001, just over the cap
    (1.7e308, 1.7e308, 1.7e308),                          # math.hypot overflows to inf
    (math.nextafter(3178376.1571225896, 0.0), 0.0, 0.0),  # just under b/2
    (1e9, 1e5, 0.0),                                      # r = 1000000005.0
    (math.nan, 0.0, 0.0),
    (math.inf, 0.0, 0.0),
    (0.0, 0.0, 5e-324),                                   # not the zero vector
]


@pytest.mark.parametrize("ecef", N11)
def test_t05_n11_refused_positions(ecef):
    error = refused(dis7_codec.E_POSITION_DOMAIN, dis7_codec.ecef_to_geodetic, *ecef)
    if ecef == N11[1]:
        assert "1000000000.0000001" not in error.message


def test_t05_n11_boundary_radii_are_accepted():
    assert_geodetic(dis7_codec.ecef_to_geodetic(3178376.1571225896, 0.0, 0.0),
                    (0.0, 0.0, -3199760.8428774104))
    assert_geodetic(dis7_codec.ecef_to_geodetic(0.0, 0.0, 3178376.1571225896),
                    (90.0, 0.0, -3178376.1571225896))
    assert_geodetic(dis7_codec.ecef_to_geodetic(1e9, 0.0, 0.0), (0.0, 0.0, 993621863.0))
    assert_geodetic(dis7_codec.ecef_to_geodetic(0.0, 0.0, 1e9), (90.0, 0.0, 993643247.6857548))
    assert math.hypot(1e9, 1.0, 0.0) == 1e9
    assert_geodetic(dis7_codec.ecef_to_geodetic(1e9, 1.0, 0.0),
                    (0.0, 5.7295779513082324e-08, 993621863.0))


# CR-35
def test_t05_n11_origin_and_negative_zero_origin_have_no_projection():
    assert dis7_codec.ecef_to_geodetic(0.0, 0.0, 0.0) is None
    assert dis7_codec.ecef_to_geodetic(-0.0, -0.0, -0.0) is None
    assert dis7_codec.ecef_to_geodetic(0.0, -0.0, 0.0) is None


def test_t05_projection_iteration_cap_is_a_seam(monkeypatch):
    mid = (4030279.376829747, 1155664.0146248138, 4790860.631304157)
    assert dis7_codec.PROJECTION_MAX_ITERATIONS == 15
    assert_geodetic(dis7_codec.ecef_to_geodetic(*mid), (49.0, 16.0, 400.0))
    monkeypatch.setattr(dis7_codec, "PROJECTION_MAX_ITERATIONS", 1)
    refused(dis7_codec.E_PROJECTION, dis7_codec.ecef_to_geodetic, *mid)
    assert dis7_codec.ecef_to_geodetic(6378257.0, 0.0, 0.0) == (0.0, 0.0, 120.0)
    assert dis7_codec.ecef_to_geodetic(0.0, 0.0, B) == (90.0, 0.0, 0.0)
    monkeypatch.setattr(dis7_codec, "PROJECTION_MAX_ITERATIONS", 0)
    refused(dis7_codec.E_PROJECTION, dis7_codec.ecef_to_geodetic, 6378257.0, 0.0, 0.0)


ANALYTICAL = [  # ECEF input, expected (lat, lon, h): h = p - a on the equatorial plane, abs(z) - b on the axis
    ((A + 120.0, 0.0, 0.0), (0.0, 0.0, 120.0)),
    ((0.0, A + 1000.0, 0.0), (0.0, 90.0, 1000.0)),
    ((-(A + 1000.0), 0.0, 0.0), (0.0, 180.0, 1000.0)),
    ((0.0, -(A + 1000.0), 0.0), (0.0, -90.0, 1000.0)),
    ((0.0, 0.0, B + 40.0), (90.0, 0.0, 40.0)),
    ((0.0, 0.0, -(B + 40.0)), (-90.0, 0.0, 40.0)),
    ((3178376.1571225896, 0.0, 0.0), (0.0, 0.0, -3199760.8428774104)),
    ((1e9, 0.0, 0.0), (0.0, 0.0, 993621863.0)),
    ((0.0, 0.0, 1e9), (90.0, 0.0, 993643247.6857548)),
]

LATS = (-90.0, -89.999, -45.0, 0.0, 30.0, 49.0, 89.999, 90.0)
LONS = (-180.0, -179.9999999, -179.5, -90.0, 0.0, 16.0, 179.9999999, 180.0)
HEIGHTS = (-3000000.0, -100.0, 0.0, 400.0, 12000.0, 35786000.0, 990000000.0)
GRID = list(itertools.product(LATS, LONS, HEIGHTS))

RAW = [(1234567.0, -2345678.0, 3456789.0), (-4000000.0, 3000000.0, -2000000.0), (6378137.0, 0.0, 0.0),
       (100.0, 100.0, 6400000.0), (-2.5e8, -7.5e8, 5.0e8), (3000000.0, 0.0, -1500000.0),
       (0.5, -0.5, -6356752.0), (2000000.0, 2000000.0, 2000000.0)]


def closed_form(x, y, z):
    a = 6378137.0
    f = 1 / 298.257223563
    b = a * (1 - f)
    e2 = (a * a - b * b) / (a * a)
    ep2 = (a * a - b * b) / (b * b)
    r = math.hypot(x, y)
    ff = 54 * b * b * z * z
    g = r * r + (1 - e2) * z * z - e2 * (a * a - b * b)
    c = e2 * e2 * ff * r * r / (g * g * g)
    s = math.cbrt(1 + c + math.sqrt(c * c + 2 * c))
    p = ff / (3 * (s + 1 / s + 1) ** 2 * g * g)
    q = math.sqrt(1 + 2 * e2 * e2 * p)
    r0 = -p * e2 * r / (1 + q) + math.sqrt(max(0.0, 0.5 * a * a * (1 + 1 / q)
                                               - p * (1 - e2) * z * z / (q * (1 + q)) - 0.5 * p * r * r))
    u = math.sqrt((r - e2 * r0) ** 2 + z * z)
    v = math.sqrt((r - e2 * r0) ** 2 + (1 - e2) * z * z)
    z0 = b * b * z / (a * v)
    return (math.degrees(math.atan2(z + ep2 * z0, r)), math.degrees(math.atan2(y, x)),
            u * (1 - b * b / (a * v)))


@pytest.mark.parametrize(("ecef", "expected"), ANALYTICAL)
def test_t16_oracle_analytical_literals(ecef, expected):
    assert_geodetic(dis7_codec.ecef_to_geodetic(*ecef), expected)


def test_t16_oracle_forward_equations_over_the_grid():
    assert len(GRID) == 448
    for lat, lon, h in GRID:
        ecef = dis7_support.geodetic_to_ecef(lat, lon, h)
        assert B / 2 <= math.hypot(*ecef) <= 1e9, (lat, lon, h)
        assert_geodetic(dis7_codec.ecef_to_geodetic(*ecef), (lat, lon, h), polar=abs(lat) == 90.0)


def test_t16_oracle_closed_form_inverse():
    assert_geodetic(closed_form(1234567.0, -2345678.0, 3456789.0),
                    (52.78941737221455, -62.241466445951495, -2008513.639100221))
    points = [dis7_support.geodetic_to_ecef(*row) for row in GRID] + RAW
    for point in points:
        assert_geodetic(dis7_codec.ecef_to_geodetic(*point), closed_form(*point))


@pytest.mark.parametrize("code", range(256))
def test_t06_a04_only_algorithms_2_to_5_are_world_coordinate(code):
    assert (code in dis7_codec.WORLD_ALGORITHMS) is (code in (2, 3, 4, 5))


def test_t06_a04_world_algorithms_is_a_frozenset_of_four():
    assert type(dis7_codec.WORLD_ALGORITHMS) is frozenset
    assert sorted(dis7_codec.WORLD_ALGORITHMS) == [2, 3, 4, 5]


A05 = [  # velocity, speed_mps, course_deg, climb_mps
    ((0.0, 25.0, 0.0), 25.0, 90.0, 0.0),
    ((0.0, 0.0, 25.0), 25.0, 0.0, 0.0),
    ((0.0, -25.0, 0.0), 25.0, 270.0, 0.0),
    ((0.0, 0.0, -25.0), 25.0, 180.0, 0.0),
    ((25.0, 0.0, 0.0), 0.0, None, 25.0),
    ((-25.0, 0.0, 0.0), 0.0, None, -25.0),
    ((0.0, 0.0, 0.0), 0.0, None, 0.0),
    ((3.0, 4.0, 4.0), 5.656854249492381, 45.0, 3.0),
]


@pytest.mark.parametrize(("velocity", "speed", "course", "climb"), A05)
def test_t07_a05_velocity_table_at_the_equator(velocity, speed, course, climb):
    # At latitude 0, longitude 0: east = vy, north = vz, up = vx.
    assert_kinematics(dis7_codec.velocity_to_kinematics(list(velocity), 0.0, 0.0),
                      speed, course, climb)


def test_t07_a05_pole_has_no_course():
    for lat in (90.0, -90.0):
        for velocity in ([10.0, 0.0, 0.0], [0.0, 10.0, 0.0]):
            assert_kinematics(dis7_codec.velocity_to_kinematics(velocity, lat, 0.0),
                              10.0, None, 0.0)
    assert_kinematics(dis7_codec.velocity_to_kinematics([10.0, 0.0, 0.0], 89.999, 0.0),
                      9.999999998476913, 180.0, 0.00017453292519072937)


def test_t07_a05_computed_360_is_emitted_as_0():
    assert math.degrees(math.atan2(-1e-30, 25.0)) % 360.0 == 360.0
    got = dis7_codec.velocity_to_kinematics([0.0, -1e-30, 25.0], 0.0, 0.0)
    assert got["course_deg"] == 0.0
    assert got["speed_mps"] == 25.0


def test_t07_a05_negative_zero_is_normalised():
    got = dis7_codec.velocity_to_kinematics([-0.0, -0.0, -0.0], 0.0, 0.0)
    assert got["course_deg"] is None
    assert got["climb_mps"] == 0.0 and positive(got["climb_mps"])
    assert got["speed_mps"] == 0.0 and positive(got["speed_mps"])
    got = dis7_codec.velocity_to_kinematics([0.0, -0.0, 25.0], 0.0, 0.0)
    assert got["course_deg"] == 0.0 and positive(got["course_deg"])


ENU = [
    ((49.0, 16.0), (3.0, 4.0, 12.0), (3.838927266562389, 4.221692987535245, 11.680751078635293), 5.0, 36.86989764584402),
    ((-45.0, -179.5), (-5.0, -12.0, -2.0), (9.855485316686357, 5.0861979093011715, -7.071067811865476), 13.0, 202.61986494804043),
]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


@pytest.mark.parametrize(("position", "local", "velocity", "speed", "course"), ENU)
def test_t07_a05_enu_against_an_independent_rotation(position, local, velocity, speed, course):
    lat, lon = position
    east, north, up = local
    phi, lam = math.radians(lat), math.radians(lon)
    u = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
    e = cross((0.0, 0.0, 1.0), u)
    length = math.hypot(*e)
    e = tuple(component / length for component in e)
    n = cross(u, e)
    rebuilt = [east * e[i] + north * n[i] + up * u[i] for i in range(3)]
    assert math.dist(rebuilt, velocity) <= 1e-9
    assert_kinematics(dis7_codec.velocity_to_kinematics(list(velocity), lat, lon),
                      speed, course, up)


@pytest.mark.parametrize("stem", ["equator_eastbound", "north_pole_stationary"])
def test_t07_a05_vector_kinematics_match_the_bundle(stem):
    raw = dis7_support.vector_bytes(stem)
    expected = dis7_support.vector_json(stem, "expected")[0]
    position = expected["position"]
    kinematics = expected["kinematics"]
    assert raw[88] in (2, 3, 4, 5)
    got = dis7_codec.velocity_to_kinematics(list(struct.unpack_from(">fff", raw, 36)),
                                            position["lat"], position["lon"])
    assert_kinematics(got, kinematics["speed_mps"], kinematics["course_deg"],
                      kinematics["climb_mps"])


def test_t07_a05_non_finite_output_is_refused():
    refused(dis7_codec.E_PROJECTION, dis7_codec.velocity_to_kinematics, [0.0, 1.7e308, 1.7e308], 0.0, 0.0)
    refused(dis7_codec.E_PROJECTION, dis7_codec.velocity_to_kinematics, [math.nan, 0.0, 0.0], 0.0, 0.0)


def test_t07_a05_kinematics_take_only_velocity_and_position():
    assert list(inspect.signature(dis7_codec.velocity_to_kinematics).parameters) == [
        "velocity", "lat_deg", "lon_deg"]
