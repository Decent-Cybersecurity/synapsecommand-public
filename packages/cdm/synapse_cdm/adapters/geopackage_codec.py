"""The three binary layers of a GeoPackage, decoded with `struct` and nothing else: the SQLite
file header (the identification bytes OGC 12-128r19 §1.1.1.1.1 reads), the GeoPackageBinary
header (§2.1.3, "GeoPackage SQL Geometry Binary Format") and the ISO WKB it wraps (OGC 06-103r4,
the +1000/+2000/+3000 dimension convention), plus the one piece of text this adapter has to read
by definition rather than by number — the `gpkg_spatial_ref_sys.definition` WKT that says whether
a layer really is WGS84.

Everything here is a pure function over `bytes` or `str`; nothing opens a file, a socket or a
database. `adapters/geopackage.py` is the module that holds the SQLite snapshot and calls these.

WHAT IS REFUSED, BY NAME
------------------------
* a SQLite header whose magic, `application_id` or `user_version` is not a GeoPackage 1.4.0's
  (`sqlite_header`), and a header whose write/read version bytes say WAL (2/2) — the caller
  decides whether a checkpointed snapshot was asserted; this module only reports the bytes;
* a GeoPackageBinary header with the ExtendedGeoPackageBinary bit (X = 1), a reserved bit set,
  an envelope indicator of 5–7, or fewer octets than its own indicator promises;
* WKB with an unknown byte-order octet, a PostGIS/EWKB flag bit, a measured (XYM / XYZM)
  dimension — "M refused explicitly, never dropped and never read as elevation" — a
  GeometryCollection, a non-linear or user-defined type code, a member of a Multi* whose type or
  dimension differs from its parent's, or a coordinate that is not finite in a geometry the
  header calls non-empty;
* any count (points, rings, parts) that the remaining octets cannot hold, CHECKED BEFORE the
  array it describes is read — a 32-bit count of four billion points is refused by arithmetic on
  the buffer length, not by running out of memory — and any count that crosses the caller's
  coordinate budget.

Nothing is repaired: a ring is not closed, an axis is not swapped, a NaN is not zeroed.
"""
from __future__ import annotations

import math
import re
import struct
from typing import Any

# --------------------------------------------------------------------------- SQLite file header

SQLITE_MAGIC = b"SQLite format 3\x00"
#: 0x47504B47, "GPKG" — Requirement 2 (GeoPackage 1.2 and later; 1.0 and 1.1 wrote "GP10" and
#: "GP11", which this adapter reports and refuses).
APPLICATION_ID_GPKG = 0x47504B47
#: Requirement 2's five-digit form — major, two-digit minor, two-digit bug-fix — for 1.4.0.
USER_VERSION_1_4_0 = 10400
SQLITE_HEADER_LENGTH = 100

_KNOWN_APPLICATION_IDS = {
    0x47503130: "GP10 (GeoPackage 1.0)",
    0x47503131: "GP11 (GeoPackage 1.1)",
    APPLICATION_ID_GPKG: "GPKG (GeoPackage 1.2 or later)",
}


class GeopackageError(ValueError):
    """Every refusal in this module and in `adapters/geopackage.py`. A `ValueError`, so the
    harness and the conformance suite read it as a refusal and never as a crash."""


def sqlite_header(octets: bytes) -> dict[str, Any]:
    """The identification fields of the 100-octet SQLite header, decoded and checked.

    Returns the reading as a dict (magic, page size, write/read versions, `user_version`,
    `application_id`) so the parsed twin can carry it. Raises `GeopackageError` for anything
    that is not a GeoPackage 1.4.0 container. WAL is NOT refused here: the write/read version
    bytes are reported and `adapters/geopackage.py` applies the caller's policy to them.
    """
    if len(octets) < SQLITE_HEADER_LENGTH:
        raise GeopackageError(
            f"GeoPackage payload is {len(octets)} octets; a SQLite database starts with a "
            f"{SQLITE_HEADER_LENGTH}-octet header (OGC 12-128r19 §1.1.1.1.1, Requirement 1) and "
            "this cannot be one")
    if octets[:16] != SQLITE_MAGIC:
        raise GeopackageError(
            "GeoPackage payload does not start with the SQLite magic 'SQLite format 3\\0' "
            f"(Requirement 1); the first sixteen octets are {octets[:16]!r}")
    page_size = struct.unpack(">H", octets[16:18])[0]
    write_version, read_version = octets[18], octets[19]
    user_version = struct.unpack(">I", octets[60:64])[0]
    application_id = struct.unpack(">I", octets[68:72])[0]
    if application_id != APPLICATION_ID_GPKG:
        known = _KNOWN_APPLICATION_IDS.get(application_id)
        spelled = f"0x{application_id:08X}" + (f" ({known})" if known else "")
        raise GeopackageError(
            f"SQLite application_id is {spelled}; a GeoPackage carries 0x47504B47 ('GPKG', "
            "Requirement 2). " + ("An earlier GeoPackage version is not supported by this adapter"
                                  if known else "This is a SQLite database but not a GeoPackage"))
    if user_version != USER_VERSION_1_4_0:
        spelled = f"{user_version} ({_spell_version(user_version)})" \
            if 10000 <= user_version < 100000 else str(user_version)
        raise GeopackageError(
            f"GeoPackage user_version is {spelled}; this adapter implements GeoPackage 1.4.0 "
            f"(user_version {USER_VERSION_1_4_0}, Requirement 2) and no other version is "
            "supported — unsupported, not malformed")
    return {
        "magic": "SQLite format 3",
        "page_size": 65536 if page_size == 1 else page_size,
        "write_version": write_version,
        "read_version": read_version,
        "user_version": user_version,
        "application_id": "GPKG",
        "octets": len(octets),
    }


def _spell_version(user_version: int) -> str:
    major, rest = divmod(user_version, 10000)
    minor, patch = divmod(rest, 100)
    return f"GeoPackage {major}.{minor}.{patch}"


def is_wal(header: dict[str, Any]) -> bool:
    """Write/read version 2 means the file is in WAL mode: its committed content may sit in a
    `-wal` file the caller did not supply, so the bytes alone are not a complete snapshot."""
    return header["write_version"] == 2 or header["read_version"] == 2


# ----------------------------------------------------------------------- GeoPackageBinary header

GPB_MAGIC = b"GP"
#: Table 5's envelope contents indicator: code -> number of doubles.
ENVELOPE_DOUBLES = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}
ENVELOPE_LABELS = {
    0: [],
    1: ["min_x", "max_x", "min_y", "max_y"],
    2: ["min_x", "max_x", "min_y", "max_y", "min_z", "max_z"],
    3: ["min_x", "max_x", "min_y", "max_y", "min_m", "max_m"],
    4: ["min_x", "max_x", "min_y", "max_y", "min_z", "max_z", "min_m", "max_m"],
}


def geopackage_binary(blob: bytes, *, budget: list[int], where: str) -> dict[str, Any]:
    """One geometry BLOB -> its decoded reading: the header fields, the envelope and the WKB.

    `budget` is a one-element list holding the caller's remaining coordinate allowance across
    the whole package; every point array decrements it BEFORE the array is read and the blob is
    refused at the array that crosses it. The result's `coordinates` is the GeoJSON-shaped
    nesting `geo.py` takes, or None for an empty geometry.
    """
    if len(blob) < 8:
        raise GeopackageError(f"{where}: a GeoPackageBinary blob is at least 8 octets (magic, "
                              f"version, flags, srs_id); this one is {len(blob)}")
    if blob[:2] != GPB_MAGIC:
        raise GeopackageError(f"{where}: GeoPackageBinary magic is 'GP' (0x4750); found "
                              f"{blob[:2]!r}")
    version = blob[2]
    if version != 0:
        raise GeopackageError(f"{where}: GeoPackageBinary version octet is {version}; OGC "
                              "12-128r19 Table 4 defines 0 (version 1) and nothing else")
    flags = blob[3]
    reserved = (flags >> 6) & 0b11
    extended = bool((flags >> 5) & 1)
    empty = bool((flags >> 4) & 1)
    envelope_code = (flags >> 1) & 0b111
    little_endian = bool(flags & 1)
    if reserved:
        raise GeopackageError(f"{where}: GeoPackageBinary flags 0x{flags:02X} set a reserved "
                              "bit (bits 7-6 are 'reserved for future use; set to 0', Table 5)")
    if extended:
        raise GeopackageError(f"{where}: GeoPackageBinary flags 0x{flags:02X} set X = 1, an "
                              "ExtendedGeoPackageBinary carrying a user-defined geometry type "
                              "(Table 5). Refused: no extension geometry type is implemented")
    if envelope_code not in ENVELOPE_DOUBLES:
        raise GeopackageError(f"{where}: GeoPackageBinary envelope indicator {envelope_code} is "
                              "invalid (Table 5 defines 0-4; 5-7 are invalid)")
    order = "<" if little_endian else ">"
    envelope_length = 8 * ENVELOPE_DOUBLES[envelope_code]
    header_length = 8 + envelope_length
    if len(blob) < header_length:
        raise GeopackageError(f"{where}: GeoPackageBinary envelope indicator {envelope_code} "
                              f"promises {envelope_length} envelope octets and the blob holds "
                              f"{len(blob) - 8} after the fixed header")
    srs_id = struct.unpack(order + "i", blob[4:8])[0]
    envelope_values = list(struct.unpack(order + "d" * ENVELOPE_DOUBLES[envelope_code],
                                         blob[8:header_length]))
    if envelope_code in (3, 4):
        raise GeopackageError(f"{where}: GeoPackageBinary envelope indicator {envelope_code} "
                              "carries an M range; measured geometry is refused by this "
                              "adapter's profile (M is never dropped and never read as height)")
    envelope = dict(zip(ENVELOPE_LABELS[envelope_code], envelope_values)) or None
    if envelope is not None and any(not math.isfinite(v) for v in envelope_values):
        raise GeopackageError(f"{where}: GeoPackageBinary envelope carries a non-finite value")
    geometry = wkb(blob, header_length, budget=budget, where=where)
    if empty:
        if geometry["coordinates"] is not None and not _all_nan(geometry["coordinates"]):
            raise GeopackageError(f"{where}: GeoPackageBinary flags say empty (Y = 1) but the "
                                  "WKB carries coordinates")
        geometry["coordinates"] = None
        if envelope is not None:
            raise GeopackageError(f"{where}: an empty geometry (Y = 1) carries an envelope; an "
                                  "empty geometry has no bounds")
    else:
        if geometry["coordinates"] is None:
            raise GeopackageError(f"{where}: GeoPackageBinary flags say non-empty (Y = 0) but the "
                                  f"WKB {geometry['type']} carries no coordinates")
        finite_or_refuse(geometry, where=where)
        if envelope is not None:
            _check_envelope(envelope, geometry, where=where)
    return {
        "flags": {"byte_order": "little" if little_endian else "big",
                  "envelope_indicator": envelope_code, "empty": empty, "extended": False},
        "srs_id": srs_id,
        "envelope": envelope,
        "wkb_offset": header_length,
        "wkb_octets": len(blob) - header_length,
        **geometry,
    }


def _all_nan(node: Any) -> bool:
    if isinstance(node, list):
        return all(_all_nan(v) for v in node)
    return isinstance(node, float) and math.isnan(node)


def _check_envelope(envelope: dict[str, float], geometry: dict[str, Any], *, where: str) -> None:
    """Table 5's envelope against the decoded bounds, exactly: an envelope is a cache of the
    coordinates and a writer that computed it from them reproduces them to the bit."""
    xs, ys, zs = [], [], []
    for position in positions(geometry["coordinates"]):
        xs.append(position[0])
        ys.append(position[1])
        if len(position) > 2:
            zs.append(position[2])
    expected = {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}
    if "min_z" in envelope:
        if not zs:
            raise GeopackageError(f"{where}: envelope carries a Z range and the WKB is 2-D")
        expected.update({"min_z": min(zs), "max_z": max(zs)})
    for key, value in expected.items():
        if envelope[key] != value:
            raise GeopackageError(
                f"{where}: GeoPackageBinary envelope {key} = {envelope[key]!r} disagrees with the "
                f"decoded bound {value!r}; the header and the WKB describe different geometries")


def positions(coordinates: Any):
    """Every position of a GeoJSON-shaped coordinate nesting, in order."""
    if coordinates is None:
        return
    if coordinates and not isinstance(coordinates[0], list):
        yield coordinates
        return
    for child in coordinates:
        yield from positions(child)


# ----------------------------------------------------------------------------------------- WKB

#: OGC 06-103r4 Table — the seven base type codes; 7 is refused, not translated.
WKB_TYPES = {1: "Point", 2: "LineString", 3: "Polygon", 4: "MultiPoint", 5: "MultiLineString",
             6: "MultiPolygon", 7: "GeometryCollection"}
SUPPORTED_TYPES = ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString",
                   "MultiPolygon")
_MEMBER = {"MultiPoint": "Point", "MultiLineString": "LineString", "MultiPolygon": "Polygon"}
DIMENSIONS = {0: "XY", 1: "XYZ", 2: "XYM", 3: "XYZM"}
_EWKB_FLAGS = 0xE0000000


def wkb(buf: bytes, offset: int, *, budget: list[int], where: str) -> dict[str, Any]:
    """One ISO WKB geometry at `offset` -> {type, dimension, byte_order, coordinates}.

    Trailing octets after the geometry are refused: a blob is one geometry and nothing else.
    """
    geometry, end = _geometry(buf, offset, budget=budget, where=where, expect=None)
    if end != len(buf):
        raise GeopackageError(f"{where}: {len(buf) - end} octet(s) follow the WKB geometry; a "
                              "GeoPackageBinary blob holds exactly one geometry")
    return geometry


def _geometry(buf: bytes, offset: int, *, budget: list[int], where: str,
              expect: tuple[str, str] | None) -> tuple[dict[str, Any], int]:
    if len(buf) - offset < 5:
        raise GeopackageError(f"{where}: WKB needs a byte-order octet and a 4-octet type at "
                              f"offset {offset}; {len(buf) - offset} octet(s) remain")
    order_octet = buf[offset]
    if order_octet not in (0, 1):
        raise GeopackageError(f"{where}: WKB byte-order octet at offset {offset} is "
                              f"0x{order_octet:02X}; OGC 06-103r4 defines 0 (big endian) and 1 "
                              "(little endian)")
    order = "<" if order_octet == 1 else ">"
    code = struct.unpack(order + "I", buf[offset + 1:offset + 5])[0]
    if code & _EWKB_FLAGS:
        raise GeopackageError(f"{where}: WKB type 0x{code:08X} sets a PostGIS EWKB flag bit; a "
                              "GeoPackage carries ISO WKB, where Z and M are +1000 and +2000 on "
                              "the type code (Requirement 19)")
    dimension_code, base = divmod(code, 1000)
    if dimension_code not in DIMENSIONS or base not in WKB_TYPES:
        raise GeopackageError(f"{where}: WKB type code {code} is not a base simple-feature type "
                              "(1-7, +1000 for Z); non-linear and user-defined types are "
                              "outside this adapter's profile")
    kind, dimension = WKB_TYPES[base], DIMENSIONS[dimension_code]
    if dimension in ("XYM", "XYZM"):
        raise GeopackageError(f"{where}: WKB {kind} carries M ordinates ({dimension}, type code "
                              f"{code}); measured geometry is refused by this adapter's profile "
                              "— the M value is never dropped and never read as height")
    if kind == "GeometryCollection":
        raise GeopackageError(f"{where}: WKB GeometryCollection (type code {code}); the CDM "
                              "models no heterogeneous geometry and this adapter refuses it "
                              "rather than choosing one member")
    if expect is not None and (kind, dimension) != expect:
        raise GeopackageError(f"{where}: a member of a {_multi_of(expect[0])} {expect[1]} is a "
                              f"{kind} {dimension}; every member of a Multi* geometry carries "
                              "its parent's member type and dimension")
    stride = 8 * (3 if dimension == "XYZ" else 2)
    offset += 5
    coordinates: Any
    if kind == "Point":
        coordinates, offset = _points(buf, offset, 1, order, stride, budget=budget, where=where)
        coordinates = coordinates[0]
    elif kind == "LineString":
        count, offset = _count(buf, offset, order, stride, where=where, what="points")
        coordinates, offset = _points(buf, offset, count, order, stride, budget=budget,
                                      where=where)
        coordinates = coordinates or None
    elif kind == "Polygon":
        coordinates, offset = _rings(buf, offset, order, stride, budget=budget, where=where)
    else:
        count, offset = _count(buf, offset, order, 5, where=where, what="members")
        coordinates = []
        for _ in range(count):
            member, offset = _geometry(buf, offset, budget=budget, where=where,
                                       expect=(_MEMBER[kind], dimension))
            coordinates.append(member["coordinates"])
        if not coordinates:
            coordinates = None
    return {"type": kind, "dimension": dimension,
            "byte_order": "little" if order == "<" else "big",
            "coordinates": coordinates}, offset


def _multi_of(member: str) -> str:
    return next(k for k, v in _MEMBER.items() if v == member)


def _count(buf: bytes, offset: int, order: str, unit: int, *, where: str, what: str
           ) -> tuple[int, int]:
    """A uint32 count, refused before use when the remaining octets cannot hold `count` items of
    at least `unit` octets each."""
    if len(buf) - offset < 4:
        raise GeopackageError(f"{where}: WKB {what} count needs 4 octets at offset {offset}; "
                              f"{len(buf) - offset} remain")
    count = struct.unpack(order + "I", buf[offset:offset + 4])[0]
    offset += 4
    if count * unit > len(buf) - offset:
        raise GeopackageError(f"{where}: WKB declares {count} {what} needing at least "
                              f"{count * unit} octets and {len(buf) - offset} remain; refused "
                              "before any coordinate is read")
    return count, offset


def _points(buf: bytes, offset: int, count: int, order: str, stride: int, *,
            budget: list[int], where: str) -> tuple[list[list[float]], int]:
    if count * stride > len(buf) - offset:
        raise GeopackageError(f"{where}: WKB point array of {count} needs {count * stride} "
                              f"octets and {len(buf) - offset} remain")
    budget[0] -= count
    if budget[0] < 0:
        raise GeopackageError(f"{where}: the package's coordinate budget is exhausted at this "
                              "geometry (GEOPACKAGE_MAX_COORDINATES); refused whole before the "
                              "array was decoded")
    width = stride // 8
    values = struct.unpack(order + "d" * (count * width), buf[offset:offset + count * stride])
    out = [list(values[i * width:(i + 1) * width]) for i in range(count)]
    for point in out:
        for v in point:
            if not math.isfinite(v) and not math.isnan(v):
                raise GeopackageError(f"{where}: WKB coordinate is infinite")
    return out, offset + count * stride


def _rings(buf: bytes, offset: int, order: str, stride: int, *, budget: list[int], where: str
           ) -> tuple[list | None, int]:
    count, offset = _count(buf, offset, order, 4, where=where, what="rings")
    rings = []
    for _ in range(count):
        points, offset = _count(buf, offset, order, stride, where=where, what="ring points")
        ring, offset = _points(buf, offset, points, order, stride, budget=budget, where=where)
        rings.append(ring)
    return (rings or None), offset


def finite_or_refuse(geometry: dict[str, Any], *, where: str) -> None:
    """A non-empty geometry with a NaN anywhere is refused; the empty case is the header's."""
    if geometry["coordinates"] is None:
        return
    for position in positions(geometry["coordinates"]):
        if any(math.isnan(v) for v in position):
            raise GeopackageError(f"{where}: WKB coordinate is NaN in a geometry the header "
                                  "calls non-empty (Y = 0)")


# ------------------------------------------------------------------------------- the CRS check

WGS84_SEMI_MAJOR_M = 6378137.0
WGS84_INVERSE_FLATTENING = 298.257223563
#: The three identifiers OGC 12-128r19 and RFC 7946 name for WGS 84 longitude/latitude data:
#: EPSG:4326 (2-D), OGC:CRS84 (2-D, longitude first by definition) and EPSG:4979 (3-D, with
#: ellipsoidal height). Anything else — including an unstated authority — is judged by the
#: definition's datum and ellipsoid alone.
WGS84_AUTHORITIES = {("EPSG", "4326"): "geographic-2d", ("OGC", "CRS84"): "geographic-2d",
                     ("EPSG", "4979"): "geographic-3d"}
_GEOGRAPHIC_ROOTS = {"GEOGCS", "GEOGCRS", "GEODCRS", "GEODETICCRS", "GEOGRAPHICCRS"}
_DATUM = re.compile(r"(WGS[ _]?(19)?84|WORLD GEODETIC SYSTEM 1984)", re.IGNORECASE)
CRS_DEFINITION_MAX_CHARS = 65536
CRS_DEFINITION_MAX_DEPTH = 32


class _Node:
    __slots__ = ("keyword", "args")

    def __init__(self, keyword: str, args: list) -> None:
        self.keyword, self.args = keyword, args


def _parse_wkt(text: str) -> _Node:
    """A small WKT reader: `KEYWORD[arg, arg, ...]` where an arg is a quoted string, a number, a
    bare word or another node. Enough for WKT 1 and WKT 2; anything else is refused."""
    if len(text) > CRS_DEFINITION_MAX_CHARS:
        raise GeopackageError(f"srs definition is {len(text)} characters; the reader bounds it "
                              f"at {CRS_DEFINITION_MAX_CHARS}")
    position = 0
    length = len(text)

    def skip() -> None:
        nonlocal position
        while position < length and text[position] in " \t\r\n":
            position += 1

    def node(depth: int) -> _Node:
        nonlocal position
        if depth > CRS_DEFINITION_MAX_DEPTH:
            raise GeopackageError("srs definition nests deeper than the reader's bound")
        skip()
        start = position
        while position < length and (text[position].isalnum() or text[position] == "_"):
            position += 1
        keyword = text[start:position].upper()
        skip()
        if not keyword or position >= length or text[position] not in "[(":
            raise GeopackageError(f"srs definition is not WKT at character {start}")
        close = "]" if text[position] == "[" else ")"
        position += 1
        args: list = []
        while True:
            skip()
            if position >= length:
                raise GeopackageError("srs definition ends inside a bracket")
            char = text[position]
            if char == close:
                position += 1
                return _Node(keyword, args)
            if char == '"':
                end = text.find('"', position + 1)
                if end < 0:
                    raise GeopackageError("srs definition has an unterminated string")
                args.append(text[position + 1:end])
                position = end + 1
            elif char.isalpha() or char == "_":
                start = position
                while position < length and (text[position].isalnum() or text[position] == "_"):
                    position += 1
                skip()
                if position < length and text[position] in "[(":
                    position = start
                    args.append(node(depth + 1))
                else:
                    args.append(text[start:position])
            else:
                start = position
                while position < length and text[position] not in ",])":
                    position += 1
                token = text[start:position].strip()
                try:
                    args.append(float(token))
                except ValueError:
                    raise GeopackageError(f"srs definition has an unreadable token {token!r}") \
                        from None
            skip()
            if position < length and text[position] == ",":
                position += 1

    root = node(0)
    skip()
    if position != length:
        raise GeopackageError("srs definition has text after the root node")
    return root


def _children(node: _Node, *keywords: str) -> list[_Node]:
    return [a for a in node.args if isinstance(a, _Node) and a.keyword in keywords]


def _descendants(node: _Node, *keywords: str) -> list[_Node]:
    out = []
    for arg in node.args:
        if isinstance(arg, _Node):
            if arg.keyword in keywords:
                out.append(arg)
            out.extend(_descendants(arg, *keywords))
    return out


def crs_profile(definition: str) -> dict[str, Any]:
    """Is this `gpkg_spatial_ref_sys.definition` WGS 84 longitude/latitude data? Judged by the
    DEFINITION — root type, datum, ellipsoid, authority — and never by the srs_id alone.

    Returns {accepted, kind, accepted_as, root, datum, ellipsoid, authority, axes, reason}.
    Never raises for a definition that merely is not WGS 84; raises `GeopackageError` only for
    text the reader cannot parse at all, which the caller reports as an unreadable definition.
    """
    text = definition.strip()
    reading: dict[str, Any] = {"accepted": False, "kind": None, "accepted_as": None,
                               "root": None, "datum": None, "ellipsoid": None,
                               "authority": None, "axes": None, "reason": None}
    if not text or text.lower() == "undefined":
        reading.update(kind="undefined", reason="the definition is 'undefined' (OGC 12-128r19 "
                       "Requirement 11's undefined SRS); an undefined SRS is not WGS 84")
        return reading
    root = _parse_wkt(text)
    reading["root"] = root.keyword
    authority = None
    for auth in _children(root, "AUTHORITY", "ID"):
        if len(auth.args) >= 2:
            code = auth.args[1]
            authority = (str(auth.args[0]).upper(),
                         str(int(code)) if isinstance(code, float) else str(code).upper())
            break
    reading["authority"] = list(authority) if authority else None
    datums = _descendants(root, "DATUM", "ENSEMBLE", "GEODETICDATUM")
    reading["datum"] = datums[0].args[0] if datums and datums[0].args else None
    ellipsoids = _descendants(root, "SPHEROID", "ELLIPSOID")
    if ellipsoids and len(ellipsoids[0].args) >= 3:
        try:
            reading["ellipsoid"] = [float(ellipsoids[0].args[1]), float(ellipsoids[0].args[2])]
        except (TypeError, ValueError):
            reading["ellipsoid"] = None
    axes = len(_descendants(root, "AXIS"))
    cs = _children(root, "CS")
    if cs and len(cs[0].args) >= 2 and isinstance(cs[0].args[1], float):
        axes = int(cs[0].args[1])
    reading["axes"] = axes or None

    if root.keyword not in _GEOGRAPHIC_ROOTS:
        reading.update(kind="projected" if root.keyword in ("PROJCS", "PROJCRS", "PROJECTEDCRS")
                       else "other",
                       reason=f"the definition's root is {root.keyword}, not a geographic CRS; "
                              "only WGS 84 longitude/latitude data is accepted and nothing is "
                              "reprojected")
        return reading
    if authority is not None and authority not in WGS84_AUTHORITIES:
        reading.update(kind="geographic-other",
                       reason=f"the definition names authority {authority[0]}:{authority[1]}, "
                              "which is not EPSG:4326, OGC:CRS84 or EPSG:4979")
        return reading
    ellipsoid = reading["ellipsoid"]
    if ellipsoid is None or abs(ellipsoid[0] - WGS84_SEMI_MAJOR_M) > 1e-3 \
            or abs(ellipsoid[1] - WGS84_INVERSE_FLATTENING) > 1e-6:
        reading.update(kind="geographic-other",
                       reason=f"the definition's ellipsoid {ellipsoid} is not WGS 84's "
                              f"({WGS84_SEMI_MAJOR_M} m, 1/f {WGS84_INVERSE_FLATTENING})")
        return reading
    if not reading["datum"] or not _DATUM.search(reading["datum"]):
        reading.update(kind="geographic-other",
                       reason=f"the definition's datum {reading['datum']!r} is not WGS 84")
        return reading
    if authority is not None:
        kind = WGS84_AUTHORITIES[authority]
        accepted_as = f"{authority[0]}:{authority[1]}"
    else:
        kind = "geographic-3d" if axes == 3 else "geographic-2d"
        accepted_as = "WGS 84 by definition (no authority stated)"
    if axes and axes != (3 if kind == "geographic-3d" else 2):
        reading.update(kind="geographic-other",
                       reason=f"the definition declares {axes} axes and its authority "
                              f"{accepted_as} defines {3 if kind == 'geographic-3d' else 2}")
        return reading
    reading.update(accepted=True, kind=kind, accepted_as=accepted_as)
    return reading
