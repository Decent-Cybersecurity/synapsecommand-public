"""OGC GeoPackage 1.4.0 (OGC 12-128r19) vector features -> CDM. Adapter #17, ingest only, the
second to declare `residual: structured`, and the first whose payload is a DATABASE: the caller
hands over the octets of a `.gpkg` SQLite container and gets one canonical object per feature
row of every selected vector layer.

THE SUPPORTED PROFILE, EXACTLY
------------------------------
GeoPackage 1.4.0 Core (`user_version` 10400, `application_id` GPKG) plus the Simple Features
vector subset: feature tables listed in `gpkg_contents` with `data_type = 'features'`, described
in `gpkg_geometry_columns`, holding StandardGeoPackageBinary geometries of the six linear types
(Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon) or a `GEOMETRY` column
carrying any of them, in XY or XYZ, whose `gpkg_spatial_ref_sys.definition` says WGS 84 —
EPSG:4326, OGC:CRS84 or EPSG:4979, judged by the definition's root, datum, ellipsoid and
authority and never by the id alone. Other GeoPackage versions are refused with the value
reported. Raster tiles, gridded coverages, attributes-only tables, views, GeometryCollection,
measured (M) geometry, non-linear and user-defined geometry types, and any CRS that is not WGS 84
are outside the profile: the first four are inventoried as unsupported content and the package
still translates its supported layers; the rest refuse the package whole with the offending row
or declaration named. Nothing is reprojected, dropped, truncated or repaired.

WHAT A ROW BECOMES
------------------
One feature row becomes one `PlanObject` of type `ANNOTATION` (`geo-object/1`, the mapping
profile `adapters/geojson.py` defines): geographic content with a geometry and no operational
meaning. No attribute is promoted to a canonical field — `name`, `status`, `type` are as opaque
as any other column and ride, typed, in the residual. A row whose geometry is SQL NULL or an
empty geometry (GeoPackageBinary Y = 1) becomes an `Entity` of type `OVERLAY_OBJECT` with no
position, which needs `valid_from` and therefore the caller's as-of context (below); without it
that package is refused rather than stamped with the epoch, the clock or `last_change`.

THE SNAPSHOT: UNTRUSTED BYTES, READ-ONLY, ONE CONNECTION, NO SQL FROM ANYONE ELSE
----------------------------------------------------------------------------------
The octets are copied into an in-memory connection with `sqlite3.Connection.deserialize`
(Python 3.11+); the caller's object is never written and a test hashes it before and after.
`PRAGMA query_only = ON` and `PRAGMA trusted_schema = OFF` are set before any schema-dependent
statement; `enable_load_extension(False)` is called and a progress handler aborts any statement
past `GEOPACKAGE_MAX_SQL_STEPS` virtual-machine steps; an authorizer installed before the first read
permits exactly SELECT, READ on `sqlite_master`, the four `gpkg_*` core tables and the SELECTED
feature tables, the four functions this module calls (`count`, `length`, `max`, `typeof`) and
one pragma (`table_xinfo`), and denies everything else — ATTACH, any write,
any other function, any other table, and every view, so a view is never selected from. No
trigger runs because nothing is written. Every identifier in every statement is a name read
from `sqlite_master` or `PRAGMA table_xinfo`, validated and double-quoted; no caller-supplied
SQL exists. R-tree index tables, `gpkg_metadata`, `gpkg_ogr_contents` and other extension
tables are tolerated — never read, never executed — and every `gpkg_extensions` row is carried.

WAL. A SQLite header whose write/read version octets say 2 describes a database in WAL mode:
committed content may sit in a `-wal` file the caller did not hand over, so the bytes alone are
not a complete snapshot and the package is refused as WAL-dependent. A caller who KNOWS the file
was checkpointed (the `-wal` is empty or gone) says so with `wal_checkpointed=True`; the adapter
then reads a copy whose two header octets are rewritten to the legacy values — the only way
`deserialize` opens such bytes — and every object records the assertion.

IDENTITY: NAMESPACE + LAYER + PRIMARY KEY
-----------------------------------------
`object_id` / `entity_id` is uuid5 (`ids.derive`) over the namespace (`GeoPackage` or
`GeoPackage:<dataset>` when the caller names a dataset), the layer name and the row's integer
primary key, encoded as one JSON array so `["areas", 1]` and `["routes", 1]` cannot collide.
`source_ids[0].external_id` is `<layer>/<pk>` and `source.original_id` is the primary key as
text. Rows are read in primary-key order; `record_index` is the row's position in the whole
translation.

TIME. A GeoPackage states no observation time. `gpkg_contents.last_change` is the timestamp of
the last edit to the TABLE and is carried as package metadata in every object's residual and
in a `source.transformations` line that says it is not an observation time. A `PlanObject`
needs no instant, so the as-of context (`GeopackageAdapter(as_of=AsOf(instant, basis))`, the
same class the GeoJSON adapter takes) is optional there and lands at `validity.observed_at`
with its basis recorded; the Entity path REQUIRES it.

Z AND M. A Z ordinate is carried as the third element of every position, and every object of
a Z layer says what the package declares about it: `gpkg_geometry_columns.z` (1 mandatory, 2
optional) and the SRS definition's vertical axis — EPSG:4979 declares ellipsoidal height in
metres; EPSG:4326 and CRS84 declare no vertical axis, so the datum and unit of z are UNDECLARED
by the package and the value is carried as sent, not asserted as height above the ellipsoid. M
is refused wherever it appears (a layer declaring `m` = 1 or 2 is unsupported content, refused
if selected by name; a row of an `m = 0` layer carrying an XYM/XYZM geometry refuses the
package): never dropped, never read as elevation.

THE RESIDUAL AND THE PARSED TWIN
--------------------------------
Every object's `residual.data` is `{package, row}`: `package` is the whole parsed reading of the
container minus its rows (SQLite header, the four core tables verbatim, the layer descriptors,
the inventory) and `row` is the row minus the geometry's `type` and `coordinates`, the only two
leaves the CDM models. That parsed reading is also the `.parsed.json` twin shipped beside every
`.gpkg` fixture (`parse_payload`), so the harness's ledger has leaves to bind and
`tests/test_cdm_geopackage_adapter.py` proves the twin and the octets translate identically.
`to_cdm` takes either.

THE INVENTORY, WHICH EVERY OBJECT CARRIES
-----------------------------------------
`package.inventory` is `{included: [layer, ...], unselected: [{table, reason}, ...],
unsupported: [{table, data_type, reason}, ...]}` — every `gpkg_contents` row lands in exactly
one list, and a `source.transformations` line repeats the three counts on every object, so a
package read for two of its five layers cannot be mistaken for a package read whole.

PARSER LIMITS
-------------
Size (`GEOPACKAGE_MAX_INPUT_BYTES`) before `deserialize`; the twin's depth before any walk;
rows (`GEOPACKAGE_MAX_ROWS`, §3.5's `max_objects`) by `count(*)` before any row is fetched;
the largest value of every column (`GEOPACKAGE_MAX_BLOB_BYTES`) by `max(length(...))` before
any row is fetched; the estimated output (`GEOPACKAGE_MAX_OUTPUT_BYTES`) from the package block
and the row count before any row is fetched, and again as rows accumulate; coordinates
(`GEOPACKAGE_MAX_COORDINATES`) as a running budget every WKB array debits before it is decoded.
A package past any bound is refused whole; nothing is truncated.
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import geopackage_codec as codec
from synapse_cdm.adapters.geojson import MAPPING_PROFILE, AsOf
from synapse_cdm.adapters.geopackage_codec import GeopackageError
from synapse_cdm.enums import Affiliation, EntityType, ObjectType
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                   Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                   Limitation, Limits, Maturity, MaturityLevel, Residual,
                                   UnknownFields, WireBinding)
from synapse_cdm.models import CDMBase, Entity, PlanObject, SourceRef, TemporalValidity

SYSTEM = "GeoPackage"
FORMAT_VERSION = "1.4.0 (OGC 12-128r19)"

# The declared bounds. Each is an IMPLEMENTATION CAP — OGC 12-128r19 states a maximum only for
# the file (about 140 TB, Requirement 1's note) — and each is declared in the metadata below
# FROM its constant so the number the manifest publishes is the number that is enforced.
#
# 64 MiB of octets: a GeoPackage is a database with page overhead, so the smallest useful
# package is already ~100 KiB (the fixtures here are 96–120 KiB each) and a municipal vector
# dataset of tens of thousands of features fits in a few MiB.
GEOPACKAGE_MAX_INPUT_BYTES = 67_108_864
# 64 containers deep, for the PARSED TWIN only — the octets have no nesting to measure. The
# deepest shipped twin (a MultiPolygon row) nests eight containers; the harness loader's own
# bound is the same 64.
GEOPACKAGE_MAX_DEPTH = 64
# 10 000 rows across every selected layer: one canonical object per row, so this is §3.5's
# `max_objects`, checked by `count(*)` before a single row is fetched.
GEOPACKAGE_MAX_ROWS = 10_000
# 1 MiB for any single stored value — a geometry BLOB or an attribute — read off
# `max(length(column))` before any row is fetched.
GEOPACKAGE_MAX_BLOB_BYTES = 1_048_576
# 500 000 coordinates across the whole package, the same figure the GeoJSON adapter caps
# positions at; debited by every WKB array before it is decoded.
GEOPACKAGE_MAX_COORDINATES = 500_000
# 64 MiB of estimated canonical output: the package block every object carries times the row
# count, plus the rows themselves, estimated from their JSON length as they are read.
GEOPACKAGE_MAX_OUTPUT_BYTES = 67_108_864

#: The core tables (OGC 12-128r19 §1.1.2–1.1.3, §2.1.5, §2.3) the snapshot may read.
CORE_TABLES = ("gpkg_spatial_ref_sys", "gpkg_contents", "gpkg_geometry_columns",
               "gpkg_extensions")
#: Column vocabulary of the core tables, in the standard's order, so a row is read the same way
#: whatever order a writer created the columns in; extension columns follow.
_CORE_COLUMNS = {
    "gpkg_spatial_ref_sys": ("srs_name", "srs_id", "organization", "organization_coordsys_id",
                             "definition", "description"),
    "gpkg_contents": ("table_name", "data_type", "identifier", "description", "last_change",
                      "min_x", "min_y", "max_x", "max_y", "srs_id"),
    "gpkg_geometry_columns": ("table_name", "column_name", "geometry_type_name", "srs_id",
                              "z", "m"),
    "gpkg_extensions": ("table_name", "column_name", "extension_name", "definition", "scope"),
}
#: The WKT column the `gpkg_crs_wkt` extension (F.10) adds; read when `definition` is 'undefined'.
CRS_WKT_COLUMN = "definition_12_063"
#: Table 21's names for the profile's geometry types; `GEOMETRY` admits any of the six.
GEOMETRY_TYPE_NAMES = {"GEOMETRY": None, "POINT": "Point", "LINESTRING": "LineString",
                       "POLYGON": "Polygon", "MULTIPOINT": "MultiPoint",
                       "MULTILINESTRING": "MultiLineString", "MULTIPOLYGON": "MultiPolygon"}
_TABLE_NAME_MAX = 256

#: The authorizer's allow-lists. Everything not here is denied.
_ALLOWED_FUNCTIONS = frozenset({"count", "length", "max", "typeof"})
_ALLOWED_PRAGMAS = frozenset({"table_xinfo"})
#: The progress handler's budget: virtual-machine steps ONE statement may take before SQLite is
#: told to abort it. Deterministic (a count, not a clock) and far above what any bounded read
#: here needs — `SELECT count(*)` over 10 000 rows is tens of thousands of steps — so a schema
#: built to make one statement run for ever meets an interrupt, not a hang.
GEOPACKAGE_MAX_SQL_STEPS = 20_000_000
_PROGRESS_EVERY = 10_000


class RowCountExceeded(GeopackageError):
    """More rows across the selected layers than `GEOPACKAGE_MAX_ROWS`."""


class BlobSizeExceeded(GeopackageError):
    """A stored value longer than `GEOPACKAGE_MAX_BLOB_BYTES`."""


class OutputSizeExceeded(GeopackageError):
    """The estimated canonical output past `GEOPACKAGE_MAX_OUTPUT_BYTES`."""


class CoordinateCountExceeded(GeopackageError):
    """More coordinates across the package than `GEOPACKAGE_MAX_COORDINATES`."""


# ------------------------------------------------------------------------------- the snapshot


class _Snapshot:
    """One bounded, read-only, authorized in-memory connection over the caller's octets."""

    def __init__(self, octets: bytes, *, wal_checkpointed: bool) -> None:
        self.header = codec.sqlite_header(octets)
        self.wal_rewritten = False
        if codec.is_wal(self.header):
            if not wal_checkpointed:
                raise GeopackageError(
                    "SQLite header write/read version octets are "
                    f"{self.header['write_version']}/{self.header['read_version']}: the "
                    "database is in WAL mode and its committed content may be in a `-wal` "
                    "file these octets do not include, so they are not a complete snapshot. "
                    "Refused as WAL-dependent; a caller who knows the file was checkpointed "
                    "passes GeopackageAdapter(wal_checkpointed=True)")
            copy = bytearray(octets)
            copy[18] = copy[19] = 1
            octets = bytes(copy)
            self.wal_rewritten = True
        self.connection = sqlite3.connect(":memory:")
        self.readable: set[str] = {"sqlite_master", *CORE_TABLES}
        self._steps = 0
        try:
            # Extension loading is OFF by default in the sqlite3 module; the explicit call is
            # the parser-safety policy's rule (§4) stated where it applies, and a build without
            # loadable-extension support has no method to call and nothing to disable.
            if hasattr(self.connection, "enable_load_extension"):
                self.connection.enable_load_extension(False)
            self.connection.deserialize(octets)
            self.connection.set_progress_handler(self._progress, _PROGRESS_EVERY)
            self.query("PRAGMA query_only = ON")
            self.query("PRAGMA trusted_schema = OFF")
            # SQLite's own walk over every page (Requirement 6's integrity check, bounded to
            # one reported problem). It runs BEFORE the authorizer is installed because it has
            # to read every table — R-tree shadow tables included — and nothing of what it reads
            # reaches this module but the one-word verdict; every statement this module itself
            # issues runs under the authorizer that follows.
            verdict = self._one("PRAGMA quick_check(1)")
            if verdict != ("ok",):
                raise GeopackageError(f"PRAGMA quick_check reports {verdict!r}; the container "
                                      "is not a consistent SQLite database (Requirement 6)")
            self.connection.set_authorizer(self._authorize)
        except sqlite3.Error as problem:
            self.close()
            raise GeopackageError(f"SQLite refused the container: {problem}") from problem
        except Exception:                          # a refusal raised below, already worded
            self.close()
            raise

    def close(self) -> None:
        try:
            self.connection.close()
        except sqlite3.Error:                     # pragma: no cover - close cannot fail here
            pass

    def _authorize(self, action: int, first: str | None, second: str | None,
                   database: str | None, trigger: str | None) -> int:
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK if first in self.readable else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if second in _ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA:
            return sqlite3.SQLITE_OK if first in _ALLOWED_PRAGMAS else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY

    def _progress(self) -> int:
        """Called every `_PROGRESS_EVERY` VM steps; a non-zero return aborts the statement."""
        self._steps += _PROGRESS_EVERY
        return 1 if self._steps > GEOPACKAGE_MAX_SQL_STEPS else 0

    def _one(self, sql: str) -> tuple:
        rows = self.query(sql)
        return tuple(rows[0]) if rows else ()

    def query(self, sql: str) -> list[tuple]:
        self._steps = 0
        try:
            return self.connection.execute(sql).fetchall()
        except sqlite3.Error as problem:
            if self._steps > GEOPACKAGE_MAX_SQL_STEPS:
                raise GeopackageError(
                    f"a read exceeded {GEOPACKAGE_MAX_SQL_STEPS} SQLite VM steps "
                    "(GEOPACKAGE_MAX_SQL_STEPS) and was aborted by the progress handler; the "
                    "package is refused rather than read for ever") from problem
            raise GeopackageError(f"SQLite refused a read: {problem}") from problem

    def columns(self, table: str) -> list[dict[str, Any]]:
        """`PRAGMA table_xinfo` as dicts; a hidden (generated or virtual) column is refused
        because reading it would evaluate an expression the package supplied."""
        out = []
        for cid, name, declared, notnull, default, pk, hidden in self.query(
                f"PRAGMA table_xinfo({_quote(table)})"):
            if hidden:
                raise GeopackageError(f"table {table!r} column {name!r} is generated or hidden "
                                      "(PRAGMA table_xinfo hidden = {hidden}); a source-defined "
                                      "expression is never evaluated")
            out.append({"cid": cid, "name": name, "declared_type": declared or "",
                        "not_null": bool(notnull), "primary_key": int(pk)})
        return out


def _quote(identifier: str) -> str:
    """A validated `sqlite_master` name as a double-quoted SQL identifier."""
    if not isinstance(identifier, str) or not identifier or "\x00" in identifier \
            or len(identifier) > _TABLE_NAME_MAX:
        raise GeopackageError(f"identifier {identifier!r} is not a usable SQLite name")
    return '"' + identifier.replace('"', '""') + '"'


# ------------------------------------------------------------------------------ the reading


def parse_payload(raw: bytes, *, layers: tuple[str, ...] | None = None,
                  wal_checkpointed: bool = False) -> dict[str, Any]:
    """The octets of a `.gpkg` -> the parsed reading (module docstring). The dict a
    `.parsed.json` twin holds; `GeopackageAdapter.to_cdm` accepts it in place of the octets."""
    octets = bytes(raw)
    snapshot = _Snapshot(octets, wal_checkpointed=wal_checkpointed)
    try:
        return _read(snapshot, layers=layers)
    finally:
        snapshot.close()


def _read(snapshot: _Snapshot, *, layers: tuple[str, ...] | None) -> dict[str, Any]:
    master = {name: kind for name, kind in snapshot.query(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")}
    for table in ("gpkg_spatial_ref_sys", "gpkg_contents"):
        if master.get(table) != "table":
            raise GeopackageError(f"the container has no {table} table (OGC 12-128r19 "
                                  f"Requirement {'10' if table.endswith('sys') else '13'}); it "
                                  "is not a GeoPackage")
    core: dict[str, list[dict[str, Any]]] = {}
    for table in CORE_TABLES:
        core[table] = _core_rows(snapshot, table, master)
    srs_by_id = {row["srs_id"]: row for row in core["gpkg_spatial_ref_sys"]}
    geometry_columns = {row["table_name"]: row for row in core["gpkg_geometry_columns"]}

    candidates: dict[str, dict[str, Any]] = {}
    unsupported: list[dict[str, Any]] = []
    for row in core["gpkg_contents"]:
        table, data_type = row["table_name"], row["data_type"]
        if data_type != "features":
            unsupported.append({"table": table, "data_type": data_type,
                                "reason": _unsupported_reason(data_type)})
            continue
        if master.get(table) == "view":
            unsupported.append({"table": table, "data_type": data_type,
                                "reason": "a view: this adapter never selects from a view "
                                          "(a source-defined query is never executed)"})
            continue
        if master.get(table) != "table":
            raise GeopackageError(f"gpkg_contents names feature table {table!r} and the "
                                  "container has no such table")
        if table.startswith(("gpkg_", "sqlite_", "rtree_")):
            raise GeopackageError(f"gpkg_contents names {table!r} as a feature table; a "
                                  "reserved-prefix table is never read as user data")
        column = geometry_columns.get(table)
        if column is None:
            raise GeopackageError(f"feature table {table!r} has no gpkg_geometry_columns row "
                                  "(Requirement 22)")
        if column["srs_id"] != row["srs_id"]:
            raise GeopackageError(f"feature table {table!r}: gpkg_geometry_columns.srs_id "
                                  f"{column['srs_id']} differs from gpkg_contents.srs_id "
                                  f"{row['srs_id']} (Requirement 146)")
        if column["srs_id"] not in srs_by_id:
            raise GeopackageError(f"feature table {table!r} declares srs_id {column['srs_id']}, "
                                  "which gpkg_spatial_ref_sys does not define (Requirement 26)")
        if column["z"] not in (0, 1, 2) or column["m"] not in (0, 1, 2):
            raise GeopackageError(f"feature table {table!r}: z = {column['z']!r}, m = "
                                  f"{column['m']!r}; each is 0, 1 or 2 (Requirements 27, 28)")
        type_name = str(column["geometry_type_name"]).upper()
        if type_name not in GEOMETRY_TYPE_NAMES:
            unsupported.append({"table": table, "data_type": data_type,
                                "reason": f"geometry_type_name {column['geometry_type_name']!r}"
                                          " is outside the profile (the six linear types and "
                                          "GEOMETRY); GeometryCollection and the non-linear "
                                          "extension types are not translated"})
            continue
        if column["m"] != 0:
            unsupported.append({"table": table, "data_type": data_type,
                                "reason": f"m = {column['m']} ({'mandatory' if column['m'] == 1 else 'optional'}"
                                          " measure ordinates): M is refused by this adapter's "
                                          "profile, never dropped and never read as height"})
            continue
        candidates[table] = {"contents": row, "geometry_column": column,
                             "type_name": type_name}

    if layers is None:
        included = sorted(candidates)
        unselected: list[dict[str, Any]] = []
    else:
        for name in layers:
            if name not in candidates:
                reason = next((u["reason"] for u in unsupported if u["table"] == name), None)
                raise GeopackageError(
                    f"layer {name!r} was selected and " + (
                        f"is unsupported content: {reason}" if reason else
                        "is not a feature table of this package; the supported vector layers "
                        f"are {sorted(candidates)}"))
        included = sorted(dict.fromkeys(layers))
        unselected = [{"table": name, "reason": "not in the caller's layer selection"}
                      for name in sorted(candidates) if name not in included]
    snapshot.readable.update(included)

    descriptors: list[dict[str, Any]] = []
    total_rows = 0
    for name in included:
        descriptor = _describe_layer(snapshot, name, candidates[name], srs_by_id)
        descriptors.append(descriptor)
        total_rows += descriptor["row_count"]
        if total_rows > GEOPACKAGE_MAX_ROWS:
            raise RowCountExceeded(
                f"the selected layers hold more than {GEOPACKAGE_MAX_ROWS} rows "
                f"(GEOPACKAGE_MAX_ROWS, the declared max_objects); refused whole by count(*) "
                "before any row was fetched — nothing is truncated")
    package: dict[str, Any] = {
        "sqlite": {**snapshot.header, "wal_read_as_checkpointed": snapshot.wal_rewritten},
        "spatial_ref_sys": core["gpkg_spatial_ref_sys"],
        "contents": core["gpkg_contents"],
        "geometry_columns": core["gpkg_geometry_columns"],
        "extensions": core["gpkg_extensions"],
        "inventory": {"included": included, "unselected": unselected,
                      "unsupported": unsupported},
        "layers": descriptors,
    }
    package_octets = len(json.dumps(package, sort_keys=True))
    output_estimate = [package_octets * max(total_rows, 1)]
    if output_estimate[0] > GEOPACKAGE_MAX_OUTPUT_BYTES:
        raise OutputSizeExceeded(
            f"the package block ({package_octets} octets) carried by each of {total_rows} rows "
            f"would exceed {GEOPACKAGE_MAX_OUTPUT_BYTES} octets of output "
            "(GEOPACKAGE_MAX_OUTPUT_BYTES); refused before any row was fetched")
    budget = [GEOPACKAGE_MAX_COORDINATES]
    rows: list[dict[str, Any]] = []
    for descriptor in descriptors:
        rows.extend(_rows(snapshot, descriptor, budget, output_estimate))
    return {**package, "rows": rows}


def _unsupported_reason(data_type: Any) -> str:
    if data_type == "tiles":
        return "raster tiles (data_type 'tiles') are outside the vector profile; not read"
    if data_type == "attributes":
        return ("attributes-only table (data_type 'attributes', no geometry column) is outside "
                "the Simple Features vector profile; not read")
    if data_type == "2d-gridded-coverage":
        return "a gridded coverage (extension data_type) is outside the vector profile; not read"
    return f"data_type {data_type!r} is not 'features'; not read"


def _core_rows(snapshot: _Snapshot, table: str, master: dict[str, str]
               ) -> list[dict[str, Any]]:
    """Every row of a core table as a dict, standard columns first, extension columns after."""
    if master.get(table) != "table":
        if table == "gpkg_extensions":
            return []
        raise GeopackageError(f"the container has no {table} table")
    columns = [c["name"] for c in snapshot.columns(table)]
    standard = [c for c in _CORE_COLUMNS[table] if c in columns]
    missing = [c for c in _CORE_COLUMNS[table] if c not in columns]
    if missing:
        raise GeopackageError(f"{table} lacks the standard column(s) {missing} (OGC 12-128r19 "
                              f"table definition for {table})")
    ordered = standard + [c for c in columns if c not in standard]
    order_by = {"gpkg_spatial_ref_sys": '"srs_id"', "gpkg_contents": '"table_name"',
                "gpkg_geometry_columns": '"table_name", "column_name"',
                "gpkg_extensions": '"table_name", "column_name", "extension_name"'}[table]
    select = ", ".join(_quote(c) for c in ordered)
    out = []
    for values in snapshot.query(f"SELECT {select} FROM {_quote(table)} ORDER BY {order_by}"):
        out.append({name: _plain(value) for name, value in zip(ordered, values)})
    return out


def _plain(value: Any) -> Any:
    """A SQLite value as JSON: TEXT, INTEGER, REAL and NULL as themselves, a BLOB as a hex
    envelope that says it is one."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"encoding": "hex", "hex": bytes(value).hex().upper()}
    if isinstance(value, float) and not math.isfinite(value):
        raise GeopackageError("a REAL value is not finite")
    return value


def _describe_layer(snapshot: _Snapshot, name: str, candidate: dict[str, Any],
                    srs_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    column = candidate["geometry_column"]
    columns = snapshot.columns(name)
    keys = [c for c in columns if c["primary_key"]]
    if len(keys) != 1 or keys[0]["declared_type"].upper() != "INTEGER":
        raise GeopackageError(f"feature table {name!r} has no single INTEGER PRIMARY KEY column "
                              "(Requirement 29: the key is a rowid alias); found "
                              f"{[k['name'] for k in keys]}")
    geometry_name = column["column_name"]
    if geometry_name not in [c["name"] for c in columns]:
        raise GeopackageError(f"feature table {name!r} has no column {geometry_name!r} named "
                              "by gpkg_geometry_columns (Requirement 31)")
    srs = srs_by_id[column["srs_id"]]
    definition, source = srs["definition"], "definition"
    if str(definition).strip().lower() == "undefined" and isinstance(srs.get(CRS_WKT_COLUMN),
                                                                     str) \
            and srs[CRS_WKT_COLUMN].strip().lower() != "undefined":
        definition, source = srs[CRS_WKT_COLUMN], CRS_WKT_COLUMN
    try:
        reading = codec.crs_profile(str(definition))
    except GeopackageError as problem:
        raise GeopackageError(f"layer {name!r}: srs_id {srs['srs_id']} ({srs['organization']}:"
                              f"{srs['organization_coordsys_id']}, {srs['srs_name']!r}) has a "
                              f"definition this adapter cannot read — {problem}") from problem
    if not reading["accepted"]:
        raise GeopackageError(
            f"layer {name!r}: srs_id {srs['srs_id']} ({srs['organization']}:"
            f"{srs['organization_coordsys_id']}, {srs['srs_name']!r}) is not WGS 84 — "
            f"{reading['reason']}. Declared: {str(definition)[:160]!r}. Only WGS 84 "
            "longitude/latitude data is accepted and nothing is reprojected")
    row_count = snapshot.query(f"SELECT count(*) FROM {_quote(name)}")[0][0]
    lengths = snapshot.query("SELECT " + ", ".join(f"max(length({_quote(c['name'])}))"
                                                    for c in columns)
                             + f" FROM {_quote(name)}")[0]
    for spec, longest in zip(columns, lengths):
        if longest is not None and longest > GEOPACKAGE_MAX_BLOB_BYTES:
            raise BlobSizeExceeded(
                f"layer {name!r} column {spec['name']!r} holds a value of {longest} octets; "
                f"the bound is {GEOPACKAGE_MAX_BLOB_BYTES} (GEOPACKAGE_MAX_BLOB_BYTES). Refused "
                "before any row was fetched")
    return {
        "name": name,
        "identifier": candidate["contents"]["identifier"],
        "primary_key": keys[0]["name"],
        "geometry_column": geometry_name,
        "geometry_type_name": column["geometry_type_name"],
        "srs_id": column["srs_id"],
        "z": column["z"],
        "m": column["m"],
        "columns": [{"name": c["name"], "declared_type": c["declared_type"],
                     "not_null": c["not_null"], "primary_key": bool(c["primary_key"])}
                    for c in columns],
        "row_count": row_count,
        "crs": {"srs_id": srs["srs_id"], "definition_column": source,
                "accepted_as": reading["accepted_as"], "kind": reading["kind"],
                "root": reading["root"], "datum": reading["datum"],
                "ellipsoid": reading["ellipsoid"], "authority": reading["authority"]},
    }


def _rows(snapshot: _Snapshot, descriptor: dict[str, Any], budget: list[int],
          output_estimate: list[int]) -> list[dict[str, Any]]:
    name = descriptor["name"]
    key, geometry_name = descriptor["primary_key"], descriptor["geometry_column"]
    attribute_columns = [c["name"] for c in descriptor["columns"]
                         if c["name"] not in (key, geometry_name)]
    select = ", ".join([_quote(key), _quote(geometry_name)]
                       + [f"{_quote(c)}, typeof({_quote(c)})" for c in attribute_columns])
    expected = GEOMETRY_TYPE_NAMES[descriptor["geometry_type_name"].upper()]
    out = []
    for values in snapshot.query(f"SELECT {select} FROM {_quote(name)} ORDER BY {_quote(key)}"):
        pk, blob = values[0], values[1]
        where = f"layer {name!r} pk {pk!r}"
        if not isinstance(pk, int):
            raise GeopackageError(f"{where}: the primary key is not an integer")
        geometry: dict[str, Any] | None
        if blob is None:
            geometry = None
        elif not isinstance(blob, bytes):
            raise GeopackageError(f"{where}: the geometry column holds a "
                                  f"{type(blob).__name__}, not a BLOB")
        else:
            geometry = codec.geopackage_binary(blob, budget=budget, where=where)
            geometry["octets"] = len(blob)
            if geometry["srs_id"] != descriptor["srs_id"]:
                raise GeopackageError(f"{where}: GeoPackageBinary srs_id {geometry['srs_id']} "
                                      f"differs from the layer's declared {descriptor['srs_id']} "
                                      "(gpkg_geometry_columns.srs_id)")
            if expected is not None and geometry["type"] != expected:
                raise GeopackageError(f"{where}: the geometry is a {geometry['type']} and the "
                                      f"column is declared {descriptor['geometry_type_name']} "
                                      "(Requirement 32)")
            if descriptor["z"] == 0 and geometry["dimension"] == "XYZ":
                raise GeopackageError(f"{where}: the geometry carries Z and the column declares "
                                      "z = 0 (Z prohibited)")
        attributes: dict[str, Any] = {}
        attribute_types: dict[str, str] = {}
        for index, column in enumerate(attribute_columns):
            attributes[column] = _plain(values[2 + 2 * index])
            attribute_types[column] = values[3 + 2 * index]
        row = {"layer": name, "pk": pk, "geometry": geometry, "attributes": attributes,
               "attribute_types": attribute_types}
        output_estimate[0] += len(json.dumps(row, sort_keys=True))
        if output_estimate[0] > GEOPACKAGE_MAX_OUTPUT_BYTES:
            raise OutputSizeExceeded(
                f"the estimated output passed {GEOPACKAGE_MAX_OUTPUT_BYTES} octets "
                f"(GEOPACKAGE_MAX_OUTPUT_BYTES) at {where}; refused whole")
        out.append(row)
    if budget[0] < 0:                             # pragma: no cover - the codec raises first
        raise CoordinateCountExceeded("coordinate budget exhausted")
    return out


# --------------------------------------------------------------------------------- the adapter


class GeopackageAdapter(Adapter):
    name = "geopackage"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Licence class OPEN: OGC 12-128r19 is an OGC Implementation Standard, freely retrievable
    #: at docs.ogc.org and freely implementable under the OGC document licence.
    metadata = AdapterMetadata(
        id="geopackage",
        name="GeoPackage",
        adapter_version="1.0.0",
        format=FormatRef(name="GeoPackage", version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today. The harness's "
                  "`translate`, `schema` and `provenance` checks are PASS on every fixture of "
                  "this adapter (L1 to L3). Its `lossless` column rests on the PATH-BOUND LEDGER: "
                  "this adapter declares `MAPPINGS` for every leaf of the parsed twin shipped "
                  "beside each `.gpkg` — the geometry type and coordinates at every nesting "
                  "depth, the primary key, and residual subtrees for the row's attributes and "
                  "geometry header and for the whole package block — with the `#[*]` target "
                  "holding each row's leaves to its own object, and the ledger reports no LOST "
                  "leaf on any fixture. This adapter is INGEST ONLY: `from_cdm` is the base "
                  "class's refusal, the harness's `roundtrip` column is a declared SKIP, and "
                  "`synapse conformance run --adapter geopackage` computes E as a declared "
                  "inapplicability. There is no egress direction for information to be lost "
                  "in, so the round-trip rung is passed vacuously — and a rung passed vacuously "
                  "is not a rung declared (ARCHITECTURE.md §3.6, rule 4): L4 is NOT declared. "
                  "The independent oracle for every fixture is GDAL 3.13.3's own reading "
                  "(`ogrinfo -json`, `ogr2ogr -f GeoJSON`), recorded in "
                  "`fixtures/geopackage/spec/geopackage_pin.json` and held by "
                  "tests/test_cdm_geopackage_adapter.py::test_the_adapter_agrees_with_the_independent_gdal_reading.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "GeoPackage 1.4.0 container (the octets of a .gpkg SQLite database) — one "
                "ANNOTATION PlanObject per feature row of every selected vector layer, in "
                "layer-name then primary-key order, or an OVERLAY_OBJECT Entity with no "
                "position for a row whose geometry is SQL NULL or empty",
                "the parsed twin of a container (`parse_payload`'s dict) — the same objects",
            ],
            limits=Limits(
                max_input_bytes=GEOPACKAGE_MAX_INPUT_BYTES,
                max_depth=GEOPACKAGE_MAX_DEPTH,
                max_objects=GEOPACKAGE_MAX_ROWS,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes":
                        "a GeoPackage is an uncompressed SQLite database and this adapter "
                        "accepts no archived or compressed payload, so there is no expansion "
                        "to bound; `deserialize` copies exactly the octets it was handed",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced by this adapter; the conformance "
                        "suite's parser worker kills a decode that overruns its deadline, "
                        "`PRAGMA quick_check(1)` is linear in the bounded input, and the row, "
                        "value, coordinate and output bounds make every read linear in a "
                        "bounded package",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "OGC 12-128r19 bounds a GeoPackage only by SQLite's own file limit "
                            "(about 140 TB, Requirement 1's note). 64 MiB "
                            "(`GEOPACKAGE_MAX_INPUT_BYTES`, `adapters/geopackage.py`) is chosen "
                            "on 2026-09-20 because a database carries page overhead — the "
                            "fixtures here are 96 to 120 KiB each — and a vector dataset of "
                            "tens of thousands of features fits in a few MiB. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused "
                            "before `sqlite3.Connection.deserialize` copies a single octet"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The octets of a SQLite database have no nesting to measure; the "
                            "bound is for the PARSED TWIN this adapter also accepts, whose "
                            "deepest shipped form (a MultiPolygon row under `rows[*]`) nests "
                            "eight containers. 64 (`GEOPACKAGE_MAX_DEPTH`, "
                            "`adapters/geopackage.py`) is chosen on 2026-09-20 as the harness "
                            "loader's own bound (`harness.LOADER_MAX_DEPTH`) and eight times "
                            "the deepest shipped twin. This is an IMPLEMENTATION CAP and is "
                            "NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_depth_bound` beside `enforce_input_bound` (`adapter.py`, "
                            "`_bind_input_bound`): a dict is measured off its containers by "
                            "`container_depth` before any walk in this module runs; octets "
                            "that do not open with `{` or `[` are not measured"),
                        test="tests/test_cdm_geopackage_adapter.py::test_the_depth_bound_admits_a_twin_at_it_and_refuses_one_level_past",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "OGC 12-128r19 states no maximum row count. One feature row becomes "
                            "one canonical object, so `max_objects` is the row count across the "
                            "selected layers: 10 000 (`GEOPACKAGE_MAX_ROWS`, "
                            "`adapters/geopackage.py`), chosen on 2026-09-20 with the estimated "
                            "output bound in view (every object carries the package block). "
                            "This is an IMPLEMENTATION CAP and is NOT the format's normative "
                            "maximum. Three further caps the manifest schema has no field for "
                            "are declared beside it in the module: `GEOPACKAGE_MAX_BLOB_BYTES` "
                            "(1 MiB per stored value), `GEOPACKAGE_MAX_COORDINATES` (500 000 "
                            "across the package) and `GEOPACKAGE_MAX_OUTPUT_BYTES` (64 MiB of "
                            "estimated output)."),
                        enforced_at=(
                            "`_read` sums `SELECT count(*)` over the selected layers and raises "
                            "`RowCountExceeded` (a `ValueError`) before any row is fetched; "
                            "`_describe_layer` reads `max(length(column))` for every column "
                            "and raises `BlobSizeExceeded` before any row is fetched; the "
                            "coordinate budget is debited by `geopackage_codec._points` before "
                            "each array is decoded; the output estimate is checked from the "
                            "package block and the row count before any row is fetched and "
                            "again per row"),
                        test="tests/test_cdm_geopackage_adapter.py::test_the_row_bound_admits_a_package_at_it_and_refuses_one_row_past",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "every column of a feature row, every column of the four core tables "
                "(extension columns included), every `gpkg_extensions` row and every member of "
                "the parsed twin this adapter does not consume is kept verbatim in the "
                "structured residual at its own relative path"),
        ),
        limitations=[
            Limitation(
                id="version-1-4-0-only",
                summary="only GeoPackage 1.4.0 (`user_version` 10400, `application_id` GPKG) is "
                        "read; any other `user_version`, and the GP10/GP11 application ids of "
                        "1.0 and 1.1, are refused as unsupported with the value reported. "
                        "Earlier versions are not implemented and are not silently accepted",
                unsupported_paths=[],
            ),
            Limitation(
                id="wgs84-only",
                summary="a selected layer's SRS must be WGS 84 by DEFINITION — EPSG:4326, "
                        "OGC:CRS84 or EPSG:4979, judged on the WKT's root, datum, ellipsoid and "
                        "authority; an 'undefined' definition (srs_id 0 or -1), a projected "
                        "CRS or any other datum refuses the package with the declaration "
                        "reported. Nothing is reprojected and no other CRS is relabelled",
                unsupported_paths=[],
            ),
            Limitation(
                id="measured-geometry",
                summary="M ordinates are refused, never dropped and never read as height: a "
                        "layer declaring m = 1 or m = 2 is inventoried as unsupported content "
                        "(refused if selected by name), and a row carrying an XYM or XYZM "
                        "geometry, or an envelope with an M range, refuses the package",
                unsupported_paths=[],
            ),
            Limitation(
                id="geometry-collection-and-extended-types",
                summary="GeometryCollection, the non-linear extension types (CircularString, "
                        "CompoundCurve, CurvePolygon, MultiCurve, MultiSurface, Curve, Surface) "
                        "and ExtendedGeoPackageBinary (flag X = 1) are outside the profile: a "
                        "layer declared with such a type is inventoried as unsupported; a row "
                        "of a GEOMETRY column carrying one refuses the package",
                unsupported_paths=[],
            ),
            Limitation(
                id="non-vector-content",
                summary="raster tiles, gridded coverages, attributes-only tables and views are "
                        "inventoried as unsupported content in every object's "
                        "`residual.data.package.inventory` and are never read; a mixed package "
                        "translates its selected vector layers only and every object says so",
                unsupported_paths=[],
            ),
            Limitation(
                id="wal-dependent",
                summary="a container whose SQLite header says WAL mode (write/read version 2) is "
                        "refused as WAL-dependent, because its committed content may be in a "
                        "`-wal` file the octets do not include; `wal_checkpointed=True` is the "
                        "caller's assertion that the file was checkpointed, recorded on every "
                        "object",
                unsupported_paths=[],
            ),
            Limitation(
                id="no-source-time",
                summary="a GeoPackage states no observation time; `gpkg_contents.last_change` "
                        "is the table's last-edit stamp and is carried as package metadata, "
                        "never as a row's time. No object carries a timestamp unless the "
                        "caller supplies an as-of context "
                        "(`GeopackageAdapter(as_of=AsOf(instant, basis))`), which lands at "
                        "`validity.observed_at` (PlanObject) or `valid_from` (Entity) with its "
                        "basis in `source.transformations`. The conformance suite's check J "
                        "reads this id as the declared reason it has no timestamp to judge",
                unsupported_paths=[],
            ),
            Limitation(
                id="z-meaning-as-declared",
                summary="a Z ordinate is carried as the third coordinate element with the "
                        "meaning the package declares and no other: under EPSG:4979 the SRS "
                        "declares ellipsoidal height in metres; under EPSG:4326 or CRS84 the "
                        "SRS declares no vertical axis and the value's datum and unit are "
                        "undeclared — carried as sent, not asserted as height above the "
                        "ellipsoid",
                unsupported_paths=[],
            ),
            "ingest only: `from_cdm` is the base class's refusal (`NotImplementedError`), the "
            "manifest advertises no egress, and no GeoPackage is ever written. The cross-format "
            "path is the GeoJSON adapter's export (examples/geopackage_to_geojson)",
            "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
            "untracked and unpackaged. `evidence.available` is true because 3.1.0 is the first "
            "release carrying this adapter and its pipeline generates the records for every "
            "shipped adapter and attaches them to the `v3.1.0` Release as "
            "`evidence-3.1.0.tar.gz`, retrievable by a third party; it says nothing about what "
            "the wheel contains, and a tag that released nothing carries this sentence to nobody",
            "of §3.5's five resource limits this adapter enforces THREE — `max_input_bytes` "
            "and `max_depth` by the base class before decode, and `max_objects` (the row "
            "count) in this module before any row is fetched — plus a per-value size, a "
            "coordinate count and an output estimate the manifest schema has no field for. "
            "The other two are absent with their reasons in `capabilities.limits.absent_because`",
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=True),
    )

    #: Nothing a source states changes value in translation: coordinates are carried as the
    #: doubles the WKB holds, TEXT/INTEGER/REAL attributes verbatim, a BLOB as its own hex, the
    #: primary key as an integer beside its text form. The map is empty because there is nothing
    #: to excuse.
    TRANSFORMS: dict[str, str] = {}

    # The path-bound preservation declarations, in the order the ledger tries them — SPECIFIC
    # keys before the residual subtree that would otherwise absorb them. `rows[*]` binds each
    # row to its own object (`#[*]`); the empty key is the package block every object carries.
    MAPPINGS = {
        "rows[*].pk": (
            lossless.Mapping("#[*]:source.original_id", "text"),
            lossless.Mapping("#[*]:residual.data.row.pk"),
        ),
        "rows[*].geometry.type": lossless.Mapping("#[*]:geometry.type"),
        "rows[*].geometry.coordinates[*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*]", "number"),
        "rows[*].geometry.coordinates[*][*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*][*]", "number"),
        "rows[*].geometry.coordinates[*][*][*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*][*][*]", "number"),
        "rows[*].geometry.coordinates[*][*][*][*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*][*][*][*]", "number"),
        "rows[*].geometry": lossless.Mapping("#[*]:residual.data.row.geometry", kind="residual"),
        "rows[*].attributes": lossless.Mapping("#[*]:residual.data.row.attributes",
                                               kind="residual"),
        "rows[*]": lossless.Mapping("#[*]:residual.data.row", kind="residual"),
        "": lossless.Mapping("*:residual.data.package", kind="residual"),
    }

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 dataset: str | None = None, layers: tuple[str, ...] | list[str] | None = None,
                 as_of: AsOf | None = None, wal_checkpointed: bool = False) -> None:
        """`dataset` names the identity namespace (`GeoPackage:<dataset>`; None = `GeoPackage`).
        `layers` selects feature tables by name (None = every supported vector layer; the rest
        are inventoried as unselected). `as_of` is the snapshot context. `wal_checkpointed` is
        the caller's assertion about a WAL-mode header. Every one is part of the determinism
        tuple (ARCHITECTURE.md §6.1)."""
        super().__init__(clock, synthetic=synthetic)
        if dataset is not None and (not isinstance(dataset, str) or not dataset.strip()):
            raise ValueError("dataset must be a non-empty name or None")
        if layers is not None:
            if isinstance(layers, str) or not all(isinstance(n, str) and n for n in layers) \
                    or not list(layers):
                raise ValueError("layers must be None or a non-empty sequence of layer names")
            layers = tuple(layers)
        if as_of is not None and not isinstance(as_of, AsOf):
            raise TypeError("as_of must be an AsOf(instant, basis)")
        self._dataset = dataset
        self._layers = layers
        self._as_of = as_of
        self._wal_checkpointed = bool(wal_checkpointed)

    @property
    def namespace(self) -> str:
        """The identity namespace every object's `source_ids[].system` carries."""
        return SYSTEM if self._dataset is None else f"{SYSTEM}:{self._dataset}"

    # ------------------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        if isinstance(raw, (bytes, bytearray, memoryview)):
            parsed = parse_payload(bytes(raw), layers=self._layers,
                                   wal_checkpointed=self._wal_checkpointed)
        elif isinstance(raw, dict):
            parsed = _check_twin(raw)
        else:
            raise TypeError("GeoPackage adapter takes the octets of a .gpkg or its parsed twin "
                            f"(dict), got {type(raw).__name__}")
        package = {key: value for key, value in parsed.items() if key != "rows"}
        layers = {d["name"]: d for d in package["layers"]}
        inventory = package["inventory"]
        scope_note = (f"inventory: {len(inventory['included'])} layer(s) included "
                      f"{inventory['included']}, {len(inventory['unselected'])} unselected, "
                      f"{len(inventory['unsupported'])} unsupported "
                      f"({[u['table'] for u in inventory['unsupported']]}); a partial reading "
                      "of the package where either later count is not zero")
        contents = {c["table_name"]: c for c in package["contents"]}
        objects: list[CDMBase] = []
        for index, row in enumerate(parsed["rows"]):
            objects.append(self._object(row, index, package, layers[row["layer"]],
                                        contents.get(row["layer"], {}), scope_note))
        return objects

    def _object(self, row: dict[str, Any], index: int, package: dict[str, Any],
                layer: dict[str, Any], contents: dict[str, Any], scope_note: str) -> CDMBase:
        name, pk = row["layer"], row["pk"]
        where = f"layer {name!r} pk {pk!r}"
        notes = [scope_note]
        crs = layer["crs"]
        notes.append(f"crs: layer {name!r} srs_id {crs['srs_id']} accepted as {crs['accepted_as']} "
                     f"by its {crs['definition_column']} ({crs['root']}, datum {crs['datum']!r}, "
                     f"ellipsoid {crs['ellipsoid']}); coordinates carried as [longitude, "
                     "latitude] per OGC 12-128r19's WKB axis-order clause; no reprojection")
        if contents.get("last_change") is not None:
            notes.append(f"last_change: gpkg_contents.last_change {contents['last_change']!r} for "
                         f"layer {name!r} is package metadata (residual.data.package.contents) "
                         "and is NOT an observation time")
        notes.append(f"identity: uuid5 over (namespace {self.namespace!r}, layer {name!r}, "
                     f"primary key {pk}); equal primary keys in two layers are two objects")
        if package["sqlite"].get("wal_read_as_checkpointed"):
            notes.append("wal: the SQLite header declares WAL mode and the caller asserted a "
                         "checkpointed snapshot (wal_checkpointed=True); the two header octets "
                         "were rewritten on a copy so the octets could be opened")
        geometry = row["geometry"]
        consumed: tuple[str, ...] = ()
        if geometry is not None and geometry.get("coordinates") is not None:
            consumed = ("row.geometry.type", "row.geometry.coordinates")
            if geometry.get("dimension") == "XYZ":
                notes.append(_z_note(name, layer))
        key = json.dumps([name, pk])
        source_ids = [{"system": self.namespace, "external_id": f"{name}/{pk}"}]
        object_id = ids.derive(self.namespace, key, kind="feature")
        residual = lossless.residual_block(self, {"package": package, "row": row}, consumed)

        if not consumed:
            reason = "SQL NULL" if geometry is None else "empty (GeoPackageBinary Y = 1)"
            if self._as_of is None:
                raise GeopackageError(
                    f"{where}: the geometry is {reason}. The {MAPPING_PROFILE} profile keeps "
                    "it as an Entity with no position, and an Entity's `valid_from` is "
                    "required; the package states no time, so the caller's as-of context is "
                    "needed (GeopackageAdapter(as_of=AsOf(instant, basis))). Refused rather "
                    "than stamped with the epoch, the clock or last_change")
            notes.append(f"geometry: {reason} — an Entity with no position, never (0, 0)")
            notes.append(f"valid_from: the caller's as-of context — {self._as_of.basis}")
            return Entity(
                source=self._source(index, pk, notes),
                source_ids=source_ids,
                entity_id=object_id,
                entity_type=EntityType.OVERLAY_OBJECT,
                affiliation=Affiliation.UNKNOWN,
                symbol=None,
                position=None,
                valid_from=self._as_of.instant,
                attributes={},
                residual=residual,
            )
        validity = None
        if self._as_of is not None:
            validity = TemporalValidity(observed_at=self._as_of.instant)
            notes.append(f"validity.observed_at: the caller's as-of context — {self._as_of.basis}")
        return PlanObject(
            source=self._source(index, pk, notes),
            source_ids=source_ids,
            object_id=object_id,
            object_type=ObjectType.ANNOTATION,
            label=None,
            geometry={"type": geometry["type"], "coordinates": geometry["coordinates"]},
            style={},
            validity=validity,
            residual=residual,
        )

    def _source(self, index: int, pk: int, notes: list[str]) -> SourceRef:
        source = self.source_ref()
        return source.model_copy(update={"record_index": index, "original_id": str(pk),
                                         "transformations": list(notes)})

    # ---------------------------------------------------------------------------- v2 surface

    def detect(self, raw: bytes | dict) -> bool | None:
        """The cheap structural test: the SQLite magic, the GPKG application id and the 1.4.0
        user_version, read off the first 100 octets; for a dict, the twin's own header."""
        if isinstance(raw, dict):
            sqlite = raw.get("sqlite")
            return isinstance(sqlite, dict) and sqlite.get("application_id") == "GPKG" \
                and sqlite.get("user_version") == codec.USER_VERSION_1_4_0 and "rows" in raw
        if isinstance(raw, (bytes, bytearray, memoryview)):
            octets = bytes(raw[:codec.SQLITE_HEADER_LENGTH])
            try:
                codec.sqlite_header(octets)
            except ValueError:
                return False
            return True
        return None

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """Refusals first, then the standard's SHOULD-level facts this adapter accepts but
        names: a z = 1 (mandatory) layer with a 2-D row, and a `gpkg_contents` extent that
        disagrees with the decoded coordinates."""
        try:
            if isinstance(raw, (bytes, bytearray, memoryview)):
                parsed = parse_payload(bytes(raw), layers=self._layers,
                                       wal_checkpointed=self._wal_checkpointed)
            else:
                parsed = _check_twin(raw)
            self.to_cdm(raw)
        except Exception as problem:                     # noqa: BLE001 - reported, not raised
            return [f"{type(problem).__name__}: {problem}"]
        problems: list[str] = []
        layers = {d["name"]: d for d in parsed["layers"]}
        contents = {c["table_name"]: c for c in parsed["contents"]}
        extents: dict[str, list[float | None]] = {}
        for row in parsed["rows"]:
            layer, geometry = layers[row["layer"]], row["geometry"]
            if geometry is None or geometry.get("coordinates") is None:
                continue
            if layer["z"] == 1 and geometry["dimension"] != "XYZ":
                problems.append(f"layer {row['layer']!r} pk {row['pk']}: the column declares "
                                "z = 1 (Z mandatory) and this geometry is 2-D")
            box = extents.setdefault(row["layer"], [None, None, None, None])
            for position in codec.positions(geometry["coordinates"]):
                x, y = position[0], position[1]
                box[0] = x if box[0] is None else min(box[0], x)
                box[1] = y if box[1] is None else min(box[1], y)
                box[2] = x if box[2] is None else max(box[2], x)
                box[3] = y if box[3] is None else max(box[3], y)
        for name, box in extents.items():
            declared = [contents[name].get(k) for k in ("min_x", "min_y", "max_x", "max_y")]
            if all(v is not None for v in declared) and declared != box:
                problems.append(f"layer {name!r}: gpkg_contents extent {declared} disagrees with "
                                f"the decoded extent {box}; the informational bounding box is "
                                "stale (carried as package metadata, not used)")
        return problems


def _z_note(name: str, layer: dict[str, Any]) -> str:
    crs = layer["crs"]
    declared = {1: "mandatory", 2: "optional"}.get(layer["z"], str(layer["z"]))
    if crs["kind"] == "geographic-3d":
        meaning = (f"the SRS ({crs['accepted_as']}) declares its third axis as ellipsoidal "
                   "height, up, in metres — carried as sent, not converted")
    else:
        meaning = (f"the SRS ({crs['accepted_as']}) declares no vertical axis, so the datum and "
                   "unit of z are UNDECLARED by the package — carried as sent, not asserted as "
                   "height above the ellipsoid")
    return (f"z: carried as the third coordinate element; gpkg_geometry_columns.z = {layer['z']} "
            f"({declared}) for layer {name!r}; {meaning}")


def _check_twin(raw: dict) -> dict[str, Any]:
    """A parsed twin's shape, checked before it is trusted: the keys `parse_payload` writes,
    typed, with the CRS of every layer re-judged from the definition the twin carries and
    every geometry's coordinates finite. Unknown members ride through untouched."""
    for key, kind in (("sqlite", dict), ("spatial_ref_sys", list), ("contents", list),
                      ("geometry_columns", list), ("inventory", dict), ("layers", list),
                      ("rows", list)):
        if not isinstance(raw.get(key), kind):
            raise GeopackageError(f"a parsed GeoPackage twin holds {key!r} as a "
                                  f"{kind.__name__}; top-level keys: {sorted(raw)}")
    sqlite = raw["sqlite"]
    if sqlite.get("application_id") != "GPKG" \
            or sqlite.get("user_version") != codec.USER_VERSION_1_4_0:
        raise GeopackageError(f"the twin's header says application_id "
                              f"{sqlite.get('application_id')!r}, user_version "
                              f"{sqlite.get('user_version')!r}; this adapter reads GeoPackage "
                              f"1.4.0 (GPKG, {codec.USER_VERSION_1_4_0})")
    srs_by_id = {s.get("srs_id"): s for s in raw["spatial_ref_sys"] if isinstance(s, dict)}
    layers: dict[str, dict[str, Any]] = {}
    for layer in raw["layers"]:
        if not isinstance(layer, dict) or not isinstance(layer.get("name"), str) \
                or not isinstance(layer.get("crs"), dict):
            raise GeopackageError("a twin layer descriptor needs `name` and `crs`")
        srs = srs_by_id.get(layer["crs"].get("srs_id"))
        if srs is None:
            raise GeopackageError(f"twin layer {layer['name']!r} names srs_id "
                                  f"{layer['crs'].get('srs_id')!r}, absent from spatial_ref_sys")
        column = layer["crs"].get("definition_column", "definition")
        reading = codec.crs_profile(str(srs.get(column, "undefined")))
        if not reading["accepted"] or reading["accepted_as"] != layer["crs"].get("accepted_as"):
            raise GeopackageError(f"twin layer {layer['name']!r}: the srs definition reads as "
                                  f"{reading['accepted_as'] or reading['reason']} and the twin "
                                  f"claims {layer['crs'].get('accepted_as')!r}")
        layers[layer["name"]] = layer
    for index, row in enumerate(raw["rows"]):
        if not isinstance(row, dict) or row.get("layer") not in layers \
                or not isinstance(row.get("pk"), int) or isinstance(row.get("pk"), bool) \
                or not isinstance(row.get("attributes"), dict):
            raise GeopackageError(f"twin rows[{index}] needs a known `layer`, an integer `pk` "
                                  "and an `attributes` object")
        geometry = row.get("geometry")
        if geometry is None:
            continue
        if not isinstance(geometry, dict) or geometry.get("type") not in codec.SUPPORTED_TYPES:
            raise GeopackageError(f"twin rows[{index}].geometry is not one of the profile's "
                                  f"types {codec.SUPPORTED_TYPES}")
        if geometry.get("dimension") not in ("XY", "XYZ"):
            raise GeopackageError(f"twin rows[{index}].geometry.dimension "
                                  f"{geometry.get('dimension')!r}: measured geometry is refused")
        coordinates = geometry.get("coordinates")
        if coordinates is None:
            continue
        width = 3 if geometry["dimension"] == "XYZ" else 2
        _check_positions(coordinates, width, where=f"twin rows[{index}]")
    return raw


def _check_positions(node: Any, width: int, *, where: str, depth: int = 0) -> None:
    """A twin's coordinate nesting: lists of lists down to positions of `width` finite numbers,
    at most four containers deep (MultiPolygon)."""
    if not isinstance(node, list) or not node:
        raise GeopackageError(f"{where}: coordinates nest a {type(node).__name__} where a "
                              "non-empty array was expected")
    if isinstance(node[0], list):
        if depth >= 4:
            raise GeopackageError(f"{where}: coordinates nest deeper than a MultiPolygon")
        for child in node:
            _check_positions(child, width, where=where, depth=depth + 1)
        return
    if len(node) != width or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                 or not math.isfinite(v) for v in node):
        raise GeopackageError(f"{where}: a position is {width} finite numbers; found {node!r}")
