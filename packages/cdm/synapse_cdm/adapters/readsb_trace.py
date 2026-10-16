"""`readsb_trace`, #24 in the ordinal table: readsb trace JSON -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One trace file of readsb's `globe_history`: one airframe's positions over one UTC day, written by
readsb as `traces/<xx>/trace_full_<hex>.json` with gzip bytes behind the `.json` name (the name
lies about the encoding, so nothing here trusts a name). `to_cdm` takes the file's octets, which
must be one gzip member, or the decompressed document as a dict. The split tar a day archive is
published as, and the day directory inside it, are containers this adapter never opens:
`synapse-decode` takes a tar member by name, and anything else is the caller's.

The document is documented only in readsb's `README-json.md`, section "trace jsons", pinned at
tag v3.16.17 by URL and SHA-256 in `fixtures/readsb_trace/spec/readsb_trace_pin.json` and not
carried here. Two facts the README does not state come from the code at the same tag and are
pinned beside it: every header carries `"version"`, and in a permanent file `"timestamp"` is the
UTC midnight that opened the day. This module still adds element 0 to `timestamp` for every
point and assumes neither midnight nor anything else about the reference.

WHAT ONE TRACE BECOMES
----------------------
`[Entity, Track, Event]`, always the three, in that order:

- an `Entity` PLATFORM, affiliation UNKNOWN for the reason `adsb` gives (an unauthenticated
  cooperative broadcast), identified by the address UPPER-CASED under `ICAO24`, or under
  `ADSB_NONICAO` for a `~` address — the same `(system, external_id)` the `adsb` adapter derives
  from a frame, so one airframe has one `entity_id` across both adapters. Its position and
  kinematics are the last point's; `valid_from` and `valid_to` are the first and last instants.
- a `Track` with one sample per point in file order. The per-point fields `TrackSample` has no
  home for (ground speed, element 5, flags, vertical rate, the aircraft object, the source,
  geometric altitude and rate, IAS, roll, anything past element 13) stay in the Entity's
  structured residual, which holds the whole document, so `residual.data.trace[i]` is sample
  `i`'s point exactly as the file states it; the readings this module takes from them are parked
  beside it in `attributes.readsb_samples`, arrays keyed by the same index. `Track.attributes`
  carries the completeness block: one file is one UTC day of an airframe's history, a fragment,
  and the source states no total.
- one `TRACK_UPDATE` Event at the last point's instant.

TIME
----
A point's instant is `timestamp` + element 0, summed in decimal from the shortest text of each
number, so a hundredth of a second readsb wrote is not lost to binary floating point. Both are on
the AGGREGATOR's clock: readsb stamps a point with the system time at which the message reached
it. That is the source's clock, not the aircraft's (1090ES states no time) and not ours, so it
fills `observed_at` and `valid_from`; `received_at` is the injected clock.

WHAT IS NOT DONE HERE
---------------------
Nothing joins two files: a flight across UTC midnight is two trace files, two Tracks and one
Entity id, and stitching them, merging two readsb instances' copies of one day, or cutting a day
at a new-leg flag are fusion decisions. A new-leg flag is decoded as data and nothing splits on
it. The barometric altitude is never written to `alt_m`; a geometric altitude reaches `alt_m`
only through the declared feet-to-metres conversion. `rc` is a containment radius and goes to
`Quality.uncertainty`, never to `accuracy_m`.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import re
import zlib
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from synapse_cdm import ids, times
from synapse_cdm.adapter import Adapter, InputTooDeep, json_nesting_depth
from synapse_cdm.adapters.adsb import ICAO_SYSTEM, NONICAO_SYSTEM
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
    VerticalReference,
    VerticalUnit,
)
from synapse_cdm.geo import VerticalPosition
from synapse_cdm.lossless import Mapping
from synapse_cdm.manifest import (
    AdapterMetadata,
    Capabilities,
    ClaimStatus,
    Direction,
    Evidence,
    FormatRef,
    LicenseClass,
    LimitBasis,
    Limitation,
    LimitKind,
    Limits,
    Maturity,
    MaturityLevel,
    Residual as ResidualStance,
    UnknownFields,
    WireBinding,
)
from synapse_cdm.models import (
    CDMBase,
    Entity,
    Event,
    Kinematics,
    Position,
    Quality,
    Residual,
    Track,
    TrackAttributes,
    TrackCompleteness,
    TrackSample,
)
from synapse_cdm.observation_contracts import json_number, utf8_text
from synapse_cdm.symbology import sidc_from_affiliation

#: `source.system` on every object: the program whose output this is. One token, because the
#: roster listing parses whitespace-separated columns.
SYSTEM = "READSB"

#: The residual namespace and `SourceRef.format_name`, read from the declaration below.
FORMAT_NAME = "readsb trace JSON"
#: The readsb release whose README-json.md section "trace jsons" this module is written against.
FORMAT_VERSION = "readsb v3.16.17"

#: Bounds (DECISIONS L-09). Implementation caps, each with its basis in the declaration below.
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 64
#: The most points one trace may hold (DECISIONS L-24). `Limits` has no field for a count of
#: points, so the bound and its basis are declared here, in the form a declared limit takes.
MAX_POINTS = 100_000
MAX_POINTS_BASIS = LimitBasis(
    kind=LimitKind.IMPLEMENTATION_CAP,
    source=(
        "One UTC day of one airframe at one point per second is 86 400 points, the densest "
        "trace DECISIONS L-24 takes globe_history to write; 100 000 (`MAX_POINTS`, "
        "`adapters/readsb_trace.py`) sits above it. The byte bounds alone do not bound the "
        "objects: 64 MiB inflated admits well over a million short points, and a review "
        "measurement of 2026-10-15 put the model graph at about 3.9 KB per point, so a trace at "
        "the byte bound could build gigabytes. This is an IMPLEMENTATION CAP and is NOT the "
        "format's normative maximum."
    ),
    enforced_at=(
        "`ReadsbTraceAdapter.to_cdm`: the length of `trace` is compared with MAX_POINTS as soon "
        "as the document is an object, before any point is walked or any model is built, and a "
        "longer trace is refused `too-many-points`"
    ),
    test=(
        "tests/test_cdm_readsb_trace_adapter.py::"
        "test_a_trace_past_the_point_bound_is_refused_before_any_point_is_read"
    ),
)

GZIP_MAGIC = b"\x1f\x8b"

#: The header keys readsb v3.16.17 writes (`json_out.c`, the trace writer): the address, the six
#: database fields and `noRegData` (only with `--db-file`), `version`, `timestamp` and `trace`.
#: A closed set: any other top-level key is refused rather than guessed at.
HEADER_KEYS = (
    "icao",
    "r",
    "t",
    "dbFlags",
    "desc",
    "ownOp",
    "year",
    "noRegData",
    "version",
    "timestamp",
    "trace",
)
REQUIRED_KEYS = ("icao", "timestamp", "trace")
TEXT_KEYS = ("r", "t", "desc", "ownOp", "year", "version")

#: readsb prints the address as six lower-case hex digits, `~` first for a non-ICAO address.
ADDRESS = re.compile(r"~?[0-9a-f]{6}")
NON_ICAO_MARK = "~"

#: A point's elements, 0-based (README-json.md, "trace jsons"). 9 elements before 2022, 14 from
#: 2022, and a 15th (a receiver id) when readsb is built with TRACKS_UUID; more are parked.
MIN_ELEMENTS = 9
DOCUMENTED_ELEMENTS = 14
E_OFFSET, E_LAT, E_LON, E_ALTITUDE, E_GS, E_TRACK = 0, 1, 2, 3, 4, 5
E_FLAGS, E_VRATE, E_AIRCRAFT, E_SOURCE = 6, 7, 8, 9
E_GEOM_ALTITUDE, E_GEOM_VRATE, E_IAS, E_ROLL = 10, 11, 12, 13
#: Elements that are a number or null.
NUMERIC_ELEMENTS = (E_GS, E_TRACK, E_VRATE, E_GEOM_ALTITUDE, E_GEOM_VRATE, E_IAS, E_ROLL)
GROUND = "ground"

#: The flag bits of element 6 (README-json.md), and the four `dbFlags` bits.
FLAG_STALE, FLAG_NEW_LEG, FLAG_VRATE_GEOMETRIC, FLAG_ALTITUDE_GEOMETRIC = 1, 2, 4, 8
FLAG_MASK = 15
DB_FLAGS = (("military", 1), ("interesting", 2), ("pia", 4), ("ladd", 8))

FEET_TO_METRES = 0.3048
KNOTS_TO_MPS = 1852 / 3600
FPM_TO_MPS = 0.00508

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
#: 9999-12-31T23:59:59.999999Z, in microseconds after the epoch: the last instant a datetime holds.
_LAST_MICROSECOND = 253402300799999999

#: Element 9, the source of the position, by the strings README-json.md lists for `type`, and
#: `unknown` (readsb's own enum names an unknown address type). An ADS-B or ADS-R position is the
#: aircraft's own navigation fix; every other source is a position someone else derived or one
#: the source does not qualify, so it is ESTIMATED — which understates, the safe direction.
_GNSS = (
    "the aircraft's own position report, received over ADS-B or rebroadcast over ADS-R, so the "
    "fix is its own navigation solution"
)
POSITION_SOURCES: dict[str, tuple[PositionSource, str]] = {
    "adsb_icao": (PositionSource.GNSS, _GNSS),
    "adsb_icao_nt": (PositionSource.GNSS, _GNSS),
    "adsb_other": (PositionSource.GNSS, _GNSS),
    "adsr_icao": (PositionSource.GNSS, _GNSS),
    "adsr_other": (PositionSource.GNSS, _GNSS),
    "mlat": (
        PositionSource.ESTIMATED,
        "multilateration: the aggregator solved the position from arrival-time differences at "
        "several receivers; it is not the aircraft's own fix",
    ),
    "tisb_icao": (
        PositionSource.ESTIMATED,
        "TIS-B: a ground station's rebroadcast of a track it derived by other means",
    ),
    "tisb_other": (
        PositionSource.ESTIMATED,
        "TIS-B: a ground station's rebroadcast of a track it derived by other means",
    ),
    "tisb_trackfile": (
        PositionSource.ESTIMATED,
        "TIS-B track file: a ground station's track, typically from primary or Mode A/C radar",
    ),
    "adsc": (
        PositionSource.ESTIMATED,
        "ADS-C received over a satellite downlink; the trace does not say how the report's "
        "position was obtained",
    ),
    "other": (
        PositionSource.ESTIMATED,
        "miscellaneous data the aggregator received in the Basestation/SBS form; the README "
        "states its quality and source are unknown",
    ),
    "mode_s": (
        PositionSource.ESTIMATED,
        "Mode S data, which the README says transmits no position; the trace does not say "
        "where this point's position came from",
    ),
    "unknown": (
        PositionSource.ESTIMATED,
        "the aggregator states the source of the position is unknown",
    ),
}
_NO_SOURCE_NULL = (
    PositionSource.ESTIMATED,
    "the point's element 9 is null: the trace states no source for this position",
)
_NO_SOURCE_ABSENT = (
    PositionSource.ESTIMATED,
    "the point has no element 9: a trace written before 2022 states no source for a position",
)

#: The transformations this module applies, by the source path each one reads; the ones a given
#: trace exercises are listed in every object's `source.transformations`, in this order.
T_ADDRESS = (
    "icao: the address is upper-cased for its source id, as the adsb adapter writes it, so one "
    "airframe has one entity_id across both adapters"
)
T_INSTANT = (
    "trace[*][0]: a point's instant is timestamp + element 0, summed in decimal from the "
    "shortest text of each number, then rendered to the CDM's millisecond form"
)
T_GEOMETRIC = (
    "trace[*][3], trace[*][10]: a geometric altitude in feet becomes metres above the WGS 84 "
    "ellipsoid (x 0.3048) in Position.vertical and alt_m"
)
T_SPEED = (
    "trace[-1][4]: the last point's ground speed in knots becomes metres per second (x 1852/3600)"
)
T_CLIMB = (
    "trace[-1][7]: the last point's vertical rate in feet per minute becomes metres per second "
    "(x 0.00508)"
)


class ReadsbTraceRefused(ValueError):
    """A trace this module will not translate. `code` names the rule; the text never quotes a
    value from the payload, only the path of the element that broke the rule."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> ReadsbTraceRefused:
    refusal = ReadsbTraceRefused(code, "")
    refusal.args = (message,)
    return refusal


# ------------------------------------------------------------------ octets to a document


def inflate(data: bytes, limit: int = MAX_DECOMPRESSED_BYTES) -> bytes:
    """One gzip member, inflated with the running total held to `limit`.

    The compression level is not read and not assumed: readsb writes level 9 for a permanent
    trace and 1 or 5 for the live ones. The member's CRC and length are checked by zlib; a stream
    that ends early, a second member and trailing octets are refused, and so is a total past
    `limit`, before the octet past it is kept.
    """
    if bytes(data[:2]) != GZIP_MAGIC:
        raise ReadsbTraceRefused(
            "not-gzip",
            "the octets do not begin with the gzip magic number; a trace file is one gzip "
            "member, and a decompressed document is handed over as a dict",
        )
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = bytearray()
    pending = bytes(data)
    try:
        while True:
            out += inflater.decompress(pending, limit + 1 - len(out))
            if len(out) > limit:
                raise ReadsbTraceRefused(
                    "inflates-past-the-bound",
                    f"the gzip member inflates past max_decompressed_bytes = {limit}; refused "
                    "before the octet past the bound was kept",
                )
            pending = inflater.unconsumed_tail
            if inflater.eof or not pending:
                break
    except zlib.error:
        raise ReadsbTraceRefused(
            "does-not-inflate",
            "the gzip member does not inflate: its deflate data, its CRC or its length is wrong",
        ) from None
    if not inflater.eof:
        raise ReadsbTraceRefused(
            "truncated-gzip", "the gzip member ends before its deflate stream and trailer do"
        )
    if inflater.unused_data:
        raise ReadsbTraceRefused(
            "trailing-octets",
            "octets follow the gzip member; a trace file is exactly one member",
        )
    return bytes(out)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ReadsbTraceRefused(
                "duplicate-key", "an object states one key twice; readsb never writes that"
            )
        seen[key] = value
    return seen


def _no_constant(_token: str) -> Any:
    raise ReadsbTraceRefused(
        "non-finite-number", "the text holds NaN or Infinity, which JSON does not define"
    )


def parse_document(octets: bytes) -> Any:
    """The inflated octets as JSON: UTF-8, depth measured before decoding, no duplicate key, no
    NaN or Infinity."""
    try:
        text = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise ReadsbTraceRefused("not-utf-8", "the inflated octets are not UTF-8") from None
    depth = json_nesting_depth(text)
    if depth > MAX_DEPTH:
        raise InputTooDeep(
            f"{ReadsbTraceAdapter.name} inflated a JSON document nesting {depth} containers deep "
            f"and declares max_depth = {MAX_DEPTH}. Refused before json.loads: every walk that "
            "follows a parse descends one frame per level"
        )
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constant)
    except ReadsbTraceRefused:
        raise
    except ValueError:
        raise ReadsbTraceRefused(
            "not-json", "the inflated text is not one complete JSON document"
        ) from None


# ------------------------------------------------------------------ the document's grammar


def _json_problem(document: Any) -> tuple[str, str] | None:
    """(code, text) for the first value that is not JSON — a dict with a key that is not text, a
    tuple, a set, bytes, a non-finite float — or for the first key or string holding a lone
    surrogate; None when there is none. A dict handed over was parsed by its caller, and it is
    held to what a JSON document can state; a parsed document is held to what UTF-8 can carry.
    The text names a path and never a value; a key that fails is named by the object holding it,
    so the path itself never carries the surrogate."""
    pending: list[tuple[Any, str]] = [(document, "$")]
    while pending:
        node, path = pending.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str):
                    return "not-json-value", f"{path} (a key that is not text) is not a JSON value"
                if not utf8_text(key):
                    return (
                        "not-unicode",
                        f"{path} has a key holding a lone surrogate, which UTF-8 cannot carry",
                    )
                pending.append((value, f"{path}.{key}"))
        elif isinstance(node, list):
            pending.extend((value, f"{path}[{index}]") for index, value in enumerate(node))
        elif isinstance(node, str):
            if not utf8_text(node):
                return "not-unicode", f"{path} holds a lone surrogate, which UTF-8 cannot carry"
        elif isinstance(node, float):
            if not math.isfinite(node):
                return "not-json-value", f"{path} is not a JSON value"
        elif node is not None and not isinstance(node, (int, bool)):
            return "not-json-value", f"{path} is not a JSON value"
    return None


def _decimal(value: int | float) -> Decimal:
    """The number as readsb wrote it: `repr` of a float is the shortest text that reads back as
    the same float, so `Decimal(repr(x))` is the decimal the file stated."""
    return Decimal(value) if isinstance(value, int) else Decimal(repr(value))


def _instant(base: Decimal, offset: Decimal, where: str) -> _dt.datetime:
    micro = int(((base + offset) * 1_000_000).to_integral_value(rounding=ROUND_FLOOR))
    if not 0 <= micro <= _LAST_MICROSECOND:
        raise ReadsbTraceRefused(
            "instant-out-of-range",
            f"{where}: timestamp + element 0 is not an instant between 1970 and 9999",
        )
    return _EPOCH + _dt.timedelta(microseconds=micro)


def _check_header(document: dict) -> None:
    unknown = [key for key in document if key not in HEADER_KEYS]
    if unknown:
        raise ReadsbTraceRefused(
            "unknown-key",
            f"the document has {len(unknown)} top-level key(s) outside the eleven readsb "
            "writes; an unknown key is refused rather than guessed at",
        )
    missing = [key for key in REQUIRED_KEYS if key not in document]
    if missing:
        raise ReadsbTraceRefused(
            "missing-key", f"the document has no {', '.join(missing)}; every trace states them"
        )
    if not isinstance(document["icao"], str) or ADDRESS.fullmatch(document["icao"]) is None:
        raise ReadsbTraceRefused(
            "bad-address",
            "icao is not six lower-case hexadecimal digits, with ~ first for a non-ICAO address",
        )
    for key in TEXT_KEYS:
        if key in document and not isinstance(document[key], str):
            raise ReadsbTraceRefused("bad-header", f"{key} is not text")
    if "dbFlags" in document and not (
        isinstance(document["dbFlags"], int)
        and not isinstance(document["dbFlags"], bool)
        and document["dbFlags"] >= 0
    ):
        raise ReadsbTraceRefused("bad-header", "dbFlags is not a non-negative integer")
    if "noRegData" in document and not isinstance(document["noRegData"], bool):
        raise ReadsbTraceRefused("bad-header", "noRegData is not a boolean")
    if not json_number(document["timestamp"]) or document["timestamp"] < 0:
        raise ReadsbTraceRefused(
            "bad-timestamp", "timestamp is not a finite, non-negative number of seconds"
        )
    if not isinstance(document["trace"], list):
        raise ReadsbTraceRefused("bad-trace", "trace is not an array")
    if not document["trace"]:
        raise ReadsbTraceRefused(
            "empty-trace", "trace holds no point, and a Track holds at least one sample"
        )


def _check_point(point: Any, index: int) -> None:
    where = f"trace[{index}]"
    if not isinstance(point, list):
        raise ReadsbTraceRefused("bad-point", f"{where} is not an array")
    if len(point) < MIN_ELEMENTS:
        raise ReadsbTraceRefused(
            "fewer-than-nine-elements",
            f"{where} has {len(point)} element(s); a point has at least {MIN_ELEMENTS}",
        )
    for element in range(min(len(point), DOCUMENTED_ELEMENTS)):
        if element != E_ALTITUDE and point[element] == GROUND:
            raise ReadsbTraceRefused(
                "ground-outside-element-3",
                f"{where}[{element}] is the string ground, which only element 3 may state",
            )
    if not json_number(point[E_OFFSET]):
        raise ReadsbTraceRefused("bad-element", f"{where}[0] is not a finite number")
    if point[E_OFFSET] < 0:
        raise ReadsbTraceRefused("negative-offset", f"{where}[0] is negative")
    for element, low, high in ((E_LAT, -90, 90), (E_LON, -180, 180)):
        if not json_number(point[element]):
            raise ReadsbTraceRefused("bad-element", f"{where}[{element}] is not a finite number")
        if not low <= point[element] <= high:
            raise ReadsbTraceRefused(
                "coordinate-out-of-range",
                f"{where}[{element}] is outside [{low}, {high}] degrees",
            )
    altitude = point[E_ALTITUDE]
    if not (altitude is None or altitude == GROUND or json_number(altitude)):
        raise ReadsbTraceRefused(
            "bad-element", f"{where}[3] is not a number, the string ground or null"
        )
    for element in NUMERIC_ELEMENTS:
        if element < len(point) and not (point[element] is None or json_number(point[element])):
            raise ReadsbTraceRefused(
                "bad-element", f"{where}[{element}] is not a finite number or null"
            )
    if point[E_GS] is not None and point[E_GS] < 0:
        raise ReadsbTraceRefused("bad-element", f"{where}[4] is a negative ground speed")
    if point[E_TRACK] is not None and not 0 <= point[E_TRACK] <= 360:
        raise ReadsbTraceRefused("bad-element", f"{where}[5] is outside [0, 360] degrees")
    flags = point[E_FLAGS]
    if not isinstance(flags, int) or isinstance(flags, bool) or not 0 <= flags <= FLAG_MASK:
        raise ReadsbTraceRefused(
            "bad-flags", f"{where}[6] is not an integer holding only the four documented bits"
        )
    aircraft = point[E_AIRCRAFT]
    if not (aircraft is None or isinstance(aircraft, dict)):
        raise ReadsbTraceRefused("bad-element", f"{where}[8] is not an object or null")
    # `rc` is the one key of the aircraft object this module reads (the last point's, into
    # Quality), so it is held to what readsb prints there, an unsigned number of metres, on every
    # point alike; the rest of the object is the source's own vocabulary and is carried as stated.
    if aircraft is not None and aircraft.get("rc") is not None:
        rc = aircraft["rc"]
        if not json_number(rc) or rc < 0:
            raise ReadsbTraceRefused(
                "bad-element", f"{where}[8].rc is not a non-negative finite number or null"
            )
    if len(point) > E_SOURCE:
        source = point[E_SOURCE]
        if not (source is None or isinstance(source, str)):
            raise ReadsbTraceRefused("bad-element", f"{where}[9] is not text or null")
        if isinstance(source, str) and source not in POSITION_SOURCES:
            raise ReadsbTraceRefused(
                "unknown-source",
                f"{where}[9] is not a position source README-json.md lists",
            )


# ------------------------------------------------------------------ one point's readings


def _vertical(point: list) -> tuple[VerticalPosition | None, float | None, str, bool]:
    """(vertical, alt_m, basis, converted) for one point."""
    altitude = point[E_ALTITUDE]
    flags = point[E_FLAGS]
    geometric = point[E_GEOM_ALTITUDE] if len(point) > E_GEOM_ALTITUDE else None
    if altitude == GROUND:
        return (
            None,
            None,
            "element 3 is ground: the aircraft is on the ground and no height is stated",
            False,
        )
    if json_number(altitude) and not flags & FLAG_ALTITUDE_GEOMETRIC:
        vertical = VerticalPosition(
            value=altitude, unit=VerticalUnit.FEET, reference=VerticalReference.BARO
        )
        return (
            vertical,
            None,
            "element 3, barometric altitude in feet (flag bit 3 clear), as stated; alt_m is "
            "metres above the ellipsoid and a pressure altitude is not one",
            False,
        )
    if json_number(altitude):
        metres = altitude * FEET_TO_METRES
        return (
            VerticalPosition(
                value=metres, unit=VerticalUnit.METRES, reference=VerticalReference.HAE
            ),
            metres,
            "element 3 with flag bit 3 set: a geometric altitude in feet above the WGS 84 "
            "ellipsoid (README-json.md, alt_geom), converted to metres",
            True,
        )
    if json_number(geometric):
        metres = geometric * FEET_TO_METRES
        return (
            VerticalPosition(
                value=metres, unit=VerticalUnit.METRES, reference=VerticalReference.HAE
            ),
            metres,
            "element 3 is null and element 10 states a geometric altitude in feet above the WGS 84 "
            "ellipsoid (README-json.md, alt_geom), converted to metres",
            True,
        )
    return (
        None,
        None,
        "the point states no altitude: element 3 is null and no geometric altitude is stated",
        False,
    )


def _position_source(point: list) -> tuple[PositionSource, str]:
    if len(point) <= E_SOURCE:
        return _NO_SOURCE_ABSENT
    source = point[E_SOURCE]
    if source is None:
        return _NO_SOURCE_NULL
    member, basis = POSITION_SOURCES[source]
    return member, f"element 9 is {source}: {basis}"


# ------------------------------------------------------------------ the adapter


def _residual(path: str) -> tuple[Mapping, ...]:
    """A header leaf, parked whole on the Entity at its own path."""
    return (Mapping(to=f"entity:residual.data.{path}", kind="residual"),)


def _on_every_object(path: str) -> tuple[Mapping, ...]:
    return tuple(
        Mapping(to=f"{kind}:residual.data.{path}", kind="residual")
        for kind in ("entity", "track", "event")
    )


class ReadsbTraceAdapter(Adapter):
    """One readsb trace file in; an Entity, a Track and a TRACK_UPDATE Event out."""

    name = "readsb_trace"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Adapter API v2's declaration. `OPEN`: the format is documented by readsb's README-json.md,
    #: cited by URL and SHA-256 and never carried (DECISIONS L-10, the class the tree's nearest
    #: by-reference precedent, `geojson`, records; the README belongs to readsb, a program
    #: licensed GPL-3.0-or-later, which governs readsb's code and not an independent reader of its
    #: output).
    metadata = AdapterMetadata(
        id="readsb_trace",
        name="readsb trace JSON (globe_history trace_full) translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter readsb_trace` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "the whole document a structured residual on the Entity) with no LOST leaf on any "
            "parsed twin. L4 is NOT declared: this adapter is ingest-only, so the roundtrip "
            "check is inapplicable rather than passed (ARCHITECTURE.md §3.6, rule 4), and a rung "
            "passed vacuously is not a rung declared.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "readsb trace JSON (README-json.md, trace jsons, readsb v3.16.17): one "
                "globe_history trace_full file per call, as its gzip octets or as the "
                "decompressed document in a dict; one Entity, one Track and one TRACK_UPDATE "
                "Event per file",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=None,
                max_decompressed_bytes=MAX_DECOMPRESSED_BYTES,
                max_parse_seconds=None,
                absent_because={
                    "max_objects": "not a bound this format needs: one trace file yields exactly "
                    "three objects, an Entity, a Track and an Event, whatever it holds; the "
                    "number of points it may hold is bounded by max_decompressed_bytes and, "
                    "since 2026-10-15, by MAX_POINTS = 100000 per trace (refused "
                    "too-many-points before any model is built; its basis is MAX_POINTS_BASIS)",
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, and the byte, inflation and depth bounds make every walk of the "
                    "document linear in a bounded input; the conformance suite's parser worker "
                    "kills a decode that overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "No document states a maximum size for a readsb trace file. The "
                            "design record's only figure is a secondary source's mean for one "
                            "day: about 23 KB of gzip and 140 KB of JSON per trace on "
                            "2023-11-19 (research-readsb-globe-history F9); the per-file "
                            "maximum is not established. 8 MiB (8 388 608 octets, "
                            "`MAX_INPUT_BYTES`, `adapters/readsb_trace.py`) is the geojson "
                            "adapter's cap, ruled for this adapter by DECISIONS L-09. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused before "
                            "this module inflates or parses anything"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_decompressed_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "A trace file is one gzip member, and nothing in the format bounds "
                            "how far it inflates. The design record's figure is a secondary "
                            "source's day mean, about 140 KB of JSON per trace "
                            "(research-readsb-globe-history F9), with no per-file maximum "
                            "established; 64 MiB (67 108 864 octets, "
                            "`MAX_DECOMPRESSED_BYTES`, `adapters/readsb_trace.py`) is DECISIONS "
                            "L-09's figure, eight times the input cap. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."
                        ),
                        enforced_at=(
                            "`readsb_trace.inflate`, called by `to_cdm` on octets: zlib "
                            "inflates with its output held to the octets still allowed, and the "
                            "first octet past the bound is refused `inflates-past-the-bound` "
                            "before it is kept"
                        ),
                        test="tests/test_cdm_readsb_trace_adapter.py::test_inflation_is_held_to_the_declared_bound_and_one_octet_past_it_is_refused",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "A trace nests four containers (the document, `trace`, a point, "
                            "the aircraft object in element 8). 64 (`MAX_DEPTH`, "
                            "`adapters/readsb_trace.py`) is the harness loader's own bound and "
                            "the figure most JSON-reading adapters of synapse_cdm declare, at "
                            "least eight times the deepest JSON document this adapter ships, "
                            "goldens included. This is an IMPLEMENTATION CAP and is NOT the "
                            "format's normative maximum."
                        ),
                        enforced_at=(
                            "for a dict and for JSON text, the base class: "
                            "`Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` before this class's `to_cdm` runs; "
                            "for gzip octets, `readsb_trace.parse_document` measures the "
                            "inflated text with `adapter.json_nesting_depth` before `json.loads` "
                            "and refuses with `InputTooDeep`"
                        ),
                        test="tests/test_cdm_parser_safety.py::test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the trace header is a closed set of eleven keys, read off readsb's trace "
                "writer, and an unknown top-level key is refused `unknown-key` rather than "
                "preserved, so an injected key is refused; inside a point, the aircraft object "
                "(element 8) and any element past 13 are the source's own open vocabulary and "
                "are carried whole, every key with them, in the Entity's residual"
            ),
        ),
        limitations=[
            Limitation(
                id="one-trace-per-call",
                summary="exactly one readsb trace file per call, as its gzip octets (one gzip "
                "member) or as the decompressed document in a dict; a day archive, a tar part, "
                "a list of traces and JSON text are not taken. synapse-decode takes one tar "
                "member by name",
            ),
            Limitation(
                id="no-join-across-files",
                summary="nothing is joined across files: a flight across UTC midnight is two "
                "files, two Tracks and one entity_id, and a new-leg flag is decoded as data and "
                "nothing is split on it. A Track's and its Event's ids derive from the address "
                "and the first and last instants, so two files of one airframe spanning the same "
                "two instants (two readsb instances' copies of one day, or a copy holding more "
                "points between them) give one track_id and one event_id: the id names the "
                "airframe's window, not the file, and files with different spans are different "
                "Tracks. Stitching, merging and leg-splitting are fusion's",
            ),
            Limitation(
                id="per-sample-fields-on-the-entity",
                summary="TrackSample holds a position and an instant only, so a point's ground "
                "speed, element 5, flags, vertical rate, aircraft object, source, geometric "
                "altitude and rate, IAS and roll stay in the Entity's residual "
                "(`residual.data.trace[i]`, sample i's point as stated), with the readings "
                "taken from them in `attributes.readsb_samples`, arrays keyed by the same index; "
                "only the last point's speed, track and vertical rate reach Entity.kinematics",
            ),
            Limitation(
                id="barometric-altitude-not-hae",
                summary="a barometric altitude is carried as Position.vertical in feet against "
                "BARO and never as alt_m; only a geometric altitude reaches alt_m, converted from "
                "feet (x 0.3048). When element 3 is barometric, element 10's geometric altitude "
                "stays in the residual",
            ),
            Limitation(
                id="db-strings-not-exercised",
                summary="the database fields r, t, desc, ownOp and year are carried verbatim in "
                "the residual and read for nothing; no packaged fixture states them, because "
                "every registration mark is a claim about a real allocation, so the shipped set "
                "is readsb's database-less form",
            ),
            Limitation(
                id="evidence-availability",
                summary="`evidence.available` is false because no published Release carries "
                "this adapter's records yet; it becomes true at the first release that "
                "attaches them",
            ),
        ],
        limitations_empty_reason=None,
        residual=ResidualStance.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    TRANSFORMS: dict[str, str] = {
        "icao": T_ADDRESS,
        "timestamp": T_INSTANT,
    }

    #: The ledger. The Entity's residual holds the whole document, so every leaf is bound to its
    #: own path there; the address and the time base are bound on all three objects, and the two
    #: coordinates of every point to the Track's sample at the same index. A specific key comes
    #: before the `trace` subtree it falls under, because the first declaration that matches a
    #: leaf is the one it is held to.
    MAPPINGS = {
        "icao": _on_every_object("icao"),
        "timestamp": _on_every_object("timestamp"),
        "trace[*][1]": (
            Mapping(to="entity:residual.data.trace[*][1]", kind="residual"),
            Mapping(to="track:samples[*].position.lat"),
        ),
        "trace[*][2]": (
            Mapping(to="entity:residual.data.trace[*][2]", kind="residual"),
            Mapping(to="track:samples[*].position.lon"),
        ),
        "trace": _residual("trace"),
        **{key: _residual(key) for key in HEADER_KEYS if key not in ("icao", "timestamp", "trace")},
    }

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One trace file -> [Entity, Track, Event]. Refuses what it cannot read."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            document = parse_document(inflate(bytes(raw)))
        elif isinstance(raw, dict):
            document = raw
        else:
            raise ReadsbTraceRefused(
                "unsupported-input",
                "a trace is handed over as its gzip octets or as the decompressed document in a "
                "dict; JSON text and other types are not taken",
            )
        if not isinstance(document, dict):
            raise ReadsbTraceRefused("not-a-document", "the JSON document is not an object")
        trace = document.get("trace")
        if isinstance(trace, list) and len(trace) > MAX_POINTS:
            raise ReadsbTraceRefused(
                "too-many-points",
                f"trace holds more than max_points = {MAX_POINTS} points; refused before any "
                "point is read",
            )
        problem = _json_problem(document)
        if problem is not None:
            raise ReadsbTraceRefused(*problem)
        _check_header(document)
        for index, point in enumerate(document["trace"]):
            _check_point(point, index)
        return self._translate(document)

    def _translate(self, document: dict) -> list[CDMBase]:
        trace = document["trace"]
        address = document["icao"]
        non_icao = address.startswith(NON_ICAO_MARK)
        hex_upper = address.removeprefix(NON_ICAO_MARK).upper()
        id_system = NONICAO_SYSTEM if non_icao else ICAO_SYSTEM
        source_ids = [{"system": id_system, "external_id": hex_upper}]
        base = _decimal(document["timestamp"])

        samples: list[TrackSample] = []
        readings: dict[str, list] = {
            "on_ground": [],
            "element_5": [],
            "stale": [],
            "new_leg": [],
            "vertical_rate_geometric": [],
            "altitude_geometric": [],
            "elements": [],
        }
        previous: Decimal | None = None
        converted = last_converted = False
        last_basis: tuple[str, str] = ("", "")
        for index, point in enumerate(trace):
            offset = _decimal(point[E_OFFSET])
            if previous is not None and offset < previous:
                raise ReadsbTraceRefused(
                    "offsets-not-monotonic",
                    f"trace[{index}][0] is earlier than trace[{index - 1}][0]; readsb writes a "
                    "trace in time order and nothing here re-orders one",
                )
            previous = offset
            vertical, alt_m, vertical_basis, metres = _vertical(point)
            converted = converted or metres
            last_converted = metres
            source, source_basis = _position_source(point)
            samples.append(
                TrackSample(
                    position=Position(
                        lat=point[E_LAT],
                        lon=point[E_LON],
                        alt_m=alt_m,
                        position_source=source,
                        accuracy_m=None,
                        vertical=vertical,
                    ),
                    observed_at=_instant(base, offset, f"trace[{index}]"),
                )
            )
            on_ground = point[E_ALTITUDE] == GROUND
            flags = point[E_FLAGS]
            readings["on_ground"].append(on_ground)
            readings["element_5"].append(
                None if point[E_TRACK] is None else "true_heading" if on_ground else "track"
            )
            readings["stale"].append(bool(flags & FLAG_STALE))
            readings["new_leg"].append(bool(flags & FLAG_NEW_LEG))
            readings["vertical_rate_geometric"].append(bool(flags & FLAG_VRATE_GEOMETRIC))
            readings["altitude_geometric"].append(bool(flags & FLAG_ALTITUDE_GEOMETRIC))
            readings["elements"].append(len(point))
            last_basis = (vertical_basis, source_basis)

        first, last = samples[0].observed_at, samples[-1].observed_at
        span = f"{hex_upper}@{times.render(first)}..{times.render(last)}"
        entity_id = ids.derive(id_system, hex_upper, kind="entity")
        track_id = ids.derive(id_system, span, kind="track")
        event_id = ids.derive(id_system, span, kind="event")

        point = trace[-1]
        kinematics, kinematics_basis, speed, climb = _kinematics(point)
        # Rule 5's chain, per object: each lists the transformations ITS fields went through.
        timed = [T_ADDRESS, T_INSTANT]
        stamp = self.source_ref().model_copy(
            update={
                "original_id": address,
                "observed_at": _instant(base, Decimal(0), "timestamp"),
            }
        )
        entity_source = stamp.model_copy(
            update={
                "transformations": timed
                + [T_GEOMETRIC] * last_converted
                + [T_SPEED] * speed
                + [T_CLIMB] * climb
            }
        )
        track_source = stamp.model_copy(
            update={"transformations": timed + [T_GEOMETRIC] * converted}
        )
        event_source = stamp.model_copy(update={"transformations": list(timed)})
        stated = {"icao": address, "timestamp": document["timestamp"]}
        namespace = self.metadata.format.name
        quality, quality_basis = _quality(point)

        attributes: dict[str, Any] = {
            "entity_id_basis": (
                f"the trace's address under {id_system}, upper-cased as the adsb adapter writes "
                "it, so a frame and a trace of one airframe give one entity_id"
            ),
            "entity_type_basis": (
                "PLATFORM: a trace is one airframe's history. The emitter category in an aircraft "
                "object is sampled on some points only and is not read as a type"
            ),
            "affiliation_basis": (
                "UNKNOWN: ADS-B states an identity and nothing in it is authenticated, so "
                "nothing here infers a side"
            ),
            "symbol_basis": "derived from affiliation; a trace states no symbol",
            "position_basis": "the trace's last point, the Track's last sample",
            "position_source_basis": last_basis[1],
            "vertical_basis": last_basis[0],
            "kinematics_basis": kinematics_basis,
            "quality_basis": quality_basis,
            "valid_from_basis": "the instant of the trace's first point",
            "valid_to_basis": (
                "the instant of the trace's last point: the file holds nothing after it, which "
                "says nothing about the airframe after it"
            ),
            "readsb_samples": readings,
            "readsb_samples_basis": (
                "readings taken from each point, keyed by sample index: index i is "
                "Track.samples[i] and residual.data.trace[i]. on_ground is element 3 being "
                "ground; element_5 says whether element 5 is a track or, on the ground, a true "
                "heading; the four booleans are element 6's bits 0 to 3; elements is how many "
                "elements the point states"
            ),
        }
        if "dbFlags" in document:
            value = document["dbFlags"]
            attributes["readsb_db_flags"] = {
                **{name: bool(value & bit) for name, bit in DB_FLAGS},
                "unassigned_bits": value & ~FLAG_MASK,
            }

        entity = Entity(
            source=entity_source,
            source_ids=source_ids,
            entity_id=entity_id,
            entity_type=EntityType.PLATFORM,
            affiliation=Affiliation.UNKNOWN,
            symbol=sidc_from_affiliation(Affiliation.UNKNOWN, synthetic=self._synthetic),
            position=samples[-1].position,
            kinematics=kinematics,
            valid_from=first,
            valid_to=last,
            confidence=None,
            quality=quality,
            attributes=attributes,
            residual=Residual(namespace=namespace, data=copy.deepcopy(document)),
        )
        track = Track(
            source=track_source,
            source_ids=source_ids,
            track_id=track_id,
            entity_id=entity_id,
            samples=samples,
            track_quality=None,
            attributes=TrackAttributes(
                completeness=TrackCompleteness(
                    carried_samples=len(samples),
                    stated_samples=None,
                    fragment=True,
                    completeness_basis=(
                        "carried_samples counts the trace's points; readsb writes one permanent "
                        "trace per airframe per UTC day, so a file is a window of the airframe's "
                        "history and never the whole of it; the trace states no total"
                    ),
                )
            ),
            residual=Residual(namespace=namespace, data=dict(stated)),
        )
        event = Event(
            source=event_source,
            source_ids=source_ids,
            event_id=event_id,
            event_type=EventType.TRACK_UPDATE,
            severity=Severity.INFO,
            related_entities=[entity_id],
            geometry=None,
            payload={
                "track_id": str(track_id),
                "sample_count": len(samples),
                "observed_at_basis": (
                    "the instant of the trace's last point: timestamp + element 0, on the "
                    "aggregator's clock (readsb stamps a point with the system time at which the "
                    "message reached it); the aircraft states no time"
                ),
                "received_at_basis": "the injected clock; a trace states no delivery instant",
                "event_type_basis": (
                    "TRACK_UPDATE: one trace file is one update of one airframe's history"
                ),
                "event_id_basis": "the address and the trace's first and last instants",
                "severity_basis": (
                    "INFO: a trace states no urgency; an emergency code in an aircraft object "
                    "stays in the residual"
                ),
                "validity_basis": (
                    "no validity: the event is an instant, and the span the trace covers is "
                    "the Entity's valid_from and valid_to and the Track's samples"
                ),
            },
            observed_at=last,
            received_at=self.now(),
            residual=Residual(namespace=namespace, data=dict(stated)),
        )
        return [entity, track, event]


def _kinematics(point: list) -> tuple[Kinematics | None, str, bool, bool]:
    """(kinematics, basis, speed converted, climb converted) from the last point."""
    speed = point[E_GS] * KNOTS_TO_MPS if point[E_GS] is not None else None
    course = point[E_TRACK]
    if point[E_ALTITUDE] == GROUND or (course is not None and course >= 360):
        course = None
    climb = point[E_VRATE] * FPM_TO_MPS if point[E_VRATE] is not None else None
    basis = (
        "the last point: element 4 (ground speed, knots), element 5 as course only when the "
        "point is airborne (on the ground it is the true heading and stays in the residual; 360 "
        "is not a course this field holds), element 7 (vertical rate, feet per minute, "
        + ("geometric" if point[E_FLAGS] & FLAG_VRATE_GEOMETRIC else "barometric")
        + " by flag bit 2); a null element is an unknown, never zero"
    )
    if speed is None and course is None and climb is None:
        return None, basis, False, False
    return (
        Kinematics(speed_mps=speed, course_deg=course, climb_mps=climb),
        basis,
        speed is not None,
        climb is not None,
    )


def _quality(point: list) -> tuple[Quality | None, str]:
    """The last point's source and containment radius, when it states them."""
    source = point[E_SOURCE] if len(point) > E_SOURCE else None
    aircraft = point[E_AIRCRAFT]
    # `_check_point` has held a stated `rc` to a non-negative number a double holds.
    rc = aircraft.get("rc") if isinstance(aircraft, dict) else None
    uncertainty = {"rc_m": float(rc)} if rc is not None else {}
    basis = (
        "the last point: source_quality is element 9, the source readsb names; rc_m is the "
        "radius of containment in metres from element 8's aircraft object, an integrity bound "
        "and not a one-sigma accuracy, so accuracy_m is never set; a point without either "
        "states nothing here"
    )
    if source is None and not uncertainty:
        return None, basis
    return Quality(source_quality=source, uncertainty=uncertainty), basis
