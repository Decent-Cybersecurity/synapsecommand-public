"""`barentswatch_hais`, #32 in the ordinal table: BarentsWatch AIS track JSON -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One response of the BarentsWatch Historic AIS API's track endpoint
(`GET /v1/historic/tracks/{mmsi}/{from}/{to}`, documented at
https://developer.barentswatch.no/docs/AIS/historic-ais-api and cited, never carried): a JSON
array of decoded AIS position reports for ONE MMSI over one requested window. `to_cdm` takes the
response's octets (UTF-8 JSON text) or the already parsed array as a `list`. Nothing else is
taken: not JSON text as `str`, not a dict, not several files.

An element is an object. Keys observed in the API's output: `mmsi`, `msgtime`, `latitude`,
`longitude`, `speedOverGround`, `courseOverGround`, `trueHeading`, `rateOfTurn`,
`navigationalStatus`, `shipType`, `name`, `stream`. `mmsi`, `msgtime`, `latitude` and
`longitude` are REQUIRED on every element and a missing one is refused, never defaulted. Every
other key is optional; a key outside that list is preserved verbatim (the whole document is the
Entity's residual) and named in `attributes.unknown_keys`.

WHAT ONE FILE BECOMES
---------------------
`[Entity, Track, Event]`, always the three, in that order (the structure of `readsb_trace`):

- an `Entity` typed from the MMSI's ITU category exactly as the shipped `ais` adapter types a
  decoded message (`ais._entity_type`'s MMSI rule: a coast-station or aid-to-navigation MMSI is a
  FACILITY whatever it transmits, every other MMSI is a PLATFORM), affiliation UNKNOWN (AIS
  states no side), identified by the MMSI rendered as nine digits under the source-id system
  `AIS` -- the same `(system, external_id)` the `ais` adapter derives, so one vessel has one
  `entity_id` and one `entity_type` across both adapters. Its position and kinematics are the
  last sample's;
  `valid_from` / `valid_to` are the first and last sample instants. Its residual holds the whole
  document, in file order, at `residual.data.points`, so `residual.data.points[i]` is element i
  exactly as the API stated it. The readings taken from each sampled element are parked in
  `attributes.barentswatch_samples`, arrays keyed by SAMPLE index.
- a `Track` with one sample per element that states a usable position, sorted ascending by
  `msgtime`, and a completeness block with `fragment=True`.
- one `TRACK_UPDATE` Event at the last sample's instant.

ORDER
-----
The API delivers a track NEWEST FIRST. A CDM Track is non-decreasing in time (SEM-012), so the
samples are re-ordered ascending: the sort key is `(instant, -file_index)`, which turns a
strictly descending file into exactly its reversal and keeps ties in reverse file order, so the
result is a pure function of the file. Any input order is accepted (the API's order is an
observation, not a documented guarantee) and the order the file arrived in is recorded at
`attributes.source_order`. `attributes.barentswatch_samples.source_index[k]` is the file index of
sample k. The re-ordering is declared in TRANSFORMS and listed in `source.transformations`.

DUPLICATE INSTANTS: KEPT, NEVER MERGED, NEVER REFUSED
-----------------------------------------------------
Two elements may state the same `msgtime`. Every one is kept as its own sample -- the CDM Track
permits equal instants, and choosing a winner would be a fusion decision made invisibly inside
a translator -- and every group is listed at `attributes.duplicate_instants` with the sample
indices it spans and whether the elements are IDENTICAL (a re-delivered report) or CONFLICTING
(the same instant stated twice with different values). Refusing the conflicting case was
considered and rejected: it would discard a whole day of a vessel's history over one pair of
reports whose meaning the file cannot settle, and the consumer can.

SENTINELS
---------
`null` is the API's own "unknown" and becomes an absent CDM field. The AIS in-band "not
available" values are honoured too, by EQUALITY and with the `ais` adapter's own constants, in
case the API ever passes one through: latitude 91 / longitude 181 (no position: the element
gets no sample), speed 102.3 kn, course 360 (and above, as the `ais` adapter reads it), heading
511, rate of turn -128. None of them is ever written as a number into a CDM field. A speed of
102.2 kn is a FLOOR ("102.2 knots or higher") and is kept, flagged per sample. An element with a
null or sentinel coordinate is carried in the residual and listed at
`attributes.points_without_position`; a file in which NO element states a usable position is
refused, because a Track holds at least one sample.

UNITS AND POSITION SOURCE
-------------------------
`speedOverGround` is knots and becomes `Kinematics.speed_mps` (x 1852/3600, rounded to four
decimals exactly as the `ais` adapter does) for the last sample. `courseOverGround` is degrees
true and is carried unchanged. `trueHeading` has no CDM field (FORMAT_COVERAGE gap 7) and is
parked per sample. `rateOfTurn` is carried VERBATIM and never converted: the API documentation
does not establish whether it is the raw ROT_AIS integer or degrees per minute.
`position_source` is ESTIMATED with the `ais` adapter's own basis: the record states neither an
EPFD nor a usable UTC second, and ESTIMATED understates rather than overstates the fix.

TIME
----
`msgtime` is an RFC 3339 instant with an explicit offset (observed `+00:00`); a string without
one is refused rather than assumed UTC. It is converted to UTC and rendered in the CDM's
three-decimal `Z` form (truncating any sub-millisecond digits), a re-rendering declared in
TRANSFORMS. It is the instant the provider recorded for the report and fills `observed_at`;
`received_at` is the injected clock (`self.now()`), never the system clock.

SOURCE HASH
-----------
The constructor's optional `source_hash` is the SHA-256 of the file as the CALLER read it,
carried into `source.source_hash` on all three objects. It is never computed here, and never from
a re-serialisation of the parsed list, which would be a digest of bytes nobody received. Absent,
`source.source_hash` is null.

WHAT IS NOT DONE HERE
---------------------
Nothing is joined across files: two windows of one vessel are two Tracks with one entity_id.
No severity is derived from navigational status (a history file is not a live alert). A virtual
aid to navigation, which the `ais` adapter reads from a type 21 message's own flag, cannot be told
from a track file, so an aid-to-navigation MMSI here is always the physical FACILITY. No position
is interpolated, filtered or de-duplicated.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import re
from typing import Any

from synapse_cdm import ids, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import ais as _ais
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
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
    Residual,
    SourceHash,
    Track,
    TrackAttributes,
    TrackCompleteness,
    TrackSample,
)
from synapse_cdm.symbology import sidc_from_affiliation

#: `source.system` on every object: the service whose output this is. One token, because the
#: roster listing parses whitespace-separated columns.
SYSTEM = "BARENTSWATCH"

#: The source-id system of the MMSI. Read from the `ais` adapter rather than spelled again, so the
#: two adapters cannot drift apart and derive two entity_ids for one vessel.
MMSI_SYSTEM = _ais.SYSTEM

FORMAT_NAME = "BarentsWatch Historic AIS track JSON"
FORMAT_VERSION = "Historic AIS API v1 (GET /v1/historic/tracks/{mmsi}/{from}/{to})"
API_DOCS = "https://developer.barentswatch.no/docs/AIS/historic-ais-api"

#: Bounds. Implementation caps, each with its basis in the declaration below.
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64
MAX_POINTS = 200_000

#: The AIS sentinels, taken from the `ais` adapter so both read "not available" identically.
LAT_UNAVAILABLE = _ais.LAT_UNAVAILABLE
LON_UNAVAILABLE = _ais.LON_UNAVAILABLE
SOG_UNAVAILABLE = _ais.SOG_UNAVAILABLE
SOG_AT_OR_ABOVE_MAXIMUM = _ais.SOG_AT_OR_ABOVE_MAXIMUM
COG_UNAVAILABLE = _ais.COG_UNAVAILABLE
HEADING_UNAVAILABLE = _ais.HEADING_UNAVAILABLE
ROT_UNAVAILABLE = _ais.ROT_UNAVAILABLE
KNOT_MPS = _ais.KNOT_MPS

#: The largest MMSI: nine decimal digits.
MAX_MMSI = 999_999_999

REQUIRED_KEYS = ("mmsi", "msgtime", "latitude", "longitude")
#: Keys whose value is a finite number or null.
NUMERIC_KEYS = (
    "speedOverGround",
    "courseOverGround",
    "trueHeading",
    "rateOfTurn",
    "navigationalStatus",
    "shipType",
)
#: Keys whose value is text or null.
TEXT_KEYS = ("name", "stream")
KNOWN_KEYS = frozenset(REQUIRED_KEYS + NUMERIC_KEYS + TEXT_KEYS)

#: (key, sentinel) pairs that mark a value "not available" in AIS, compared for equality.
#: `courseOverGround` is handled apart because the `ais` adapter reads 360 AND ABOVE as no course.
SENTINELS: tuple[tuple[str, float], ...] = (
    ("latitude", LAT_UNAVAILABLE),
    ("longitude", LON_UNAVAILABLE),
    ("speedOverGround", SOG_UNAVAILABLE),
    ("trueHeading", HEADING_UNAVAILABLE),
    ("rateOfTurn", ROT_UNAVAILABLE),
)

#: RFC 3339 with an explicit offset and at most six fractional digits (what a datetime holds).
MSGTIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})"
)

POSITION_SOURCE_BASIS = (
    "ESTIMATED, as the ais adapter reads an AIS position that states no EPFD and no usable UTC "
    "second: a BarentsWatch track element states neither, and ESTIMATED understates rather than "
    "overstates the fix, which is the safe direction for this field"
)

#: The transformations this module applies, by the source path each one reads. The ones a given
#: file exercises are listed in each object's `source.transformations`, in this order.
T_MMSI = (
    "[*].mmsi: the integer MMSI is rendered as nine decimal digits for its AIS source id, as the "
    "ais adapter writes it, so one vessel has one entity_id across both adapters"
)
T_ORDER = (
    "[*]: the elements, delivered newest first, are re-ordered ascending by msgtime into Track "
    "samples (sort key: instant, then descending file index); the residual keeps file order and "
    "attributes.barentswatch_samples.source_index maps each sample to its element"
)
T_INSTANT = (
    "[*].msgtime: the RFC 3339 instant is converted to UTC and re-rendered in the CDM's "
    "three-decimal Z form, truncating any sub-millisecond digits"
)
T_POSITION_SENTINEL = (
    "[*].latitude, [*].longitude: null, latitude 91 or longitude 181 ('not available') yields no "
    "Track sample rather than a coordinate; a real coordinate, 0.0 included, is carried unchanged"
)
T_SPEED = (
    "[*].speedOverGround: a speed in knots becomes metres per second (x 1852/3600, rounded to 4 "
    "decimals as the ais adapter does) in attributes.barentswatch_samples.speed_mps and, for the "
    "last sample, Kinematics.speed_mps; null and the 102.3 sentinel become absent"
)
T_COURSE = (
    "[*].courseOverGround: null, and 360 or above (the AIS 'not available' value), become an "
    "absent course; any other value is carried unchanged in degrees true"
)
T_HEADING = "[*].trueHeading: null and the 511 sentinel become an absent heading"
T_ROT = (
    "[*].rateOfTurn: null and the -128 sentinel become an absent rate; any other value is carried "
    "verbatim and never converted"
)


class BarentswatchHaisRefused(ValueError):
    """A track file this module will not translate. `code` names the rule; the text never quotes
    a value from the payload, only the path of the element that broke the rule."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        # Pickling round-trips through the conformance suite's worker process.
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> BarentswatchHaisRefused:
    refusal = BarentswatchHaisRefused(code, "")
    refusal.args = (message,)
    return refusal


# ------------------------------------------------------------------ octets to a document


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            # json.loads would silently keep the last one, which is a value lost unseen.
            raise BarentswatchHaisRefused("duplicate-key", "an object states one key twice")
        seen[key] = value
    return seen


def _no_constant(_token: str) -> Any:
    raise BarentswatchHaisRefused(
        "non-finite-number", "the text holds NaN or Infinity, which JSON does not define"
    )


def parse_document(octets: bytes) -> Any:
    """The octets as one JSON document: UTF-8, no duplicate key, no NaN or Infinity. The depth
    bound has already been enforced on the octets by the base class's wrapper."""
    try:
        text = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise BarentswatchHaisRefused("not-utf-8", "the octets are not UTF-8") from None
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constant)
    except BarentswatchHaisRefused:
        raise
    except ValueError:
        raise BarentswatchHaisRefused(
            "not-json", "the octets are not one complete JSON document"
        ) from None


def _json_problem(document: Any) -> tuple[str, str] | None:
    """(code, text) for the first value a JSON document cannot hold -- a key that is not text, a
    tuple, bytes, a non-finite float, a lone surrogate -- or None. A list handed over was parsed
    by its caller and is held to what a JSON document can state. Iterative, so a deep payload
    cannot exhaust the stack here."""
    pending: list[tuple[Any, str]] = [(document, "$")]
    while pending:
        node, path = pending.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str):
                    return "not-json-value", f"{path} has a key that is not text"
                if not _utf8(key):
                    return "not-unicode", f"{path} has a key UTF-8 cannot carry"
                pending.append((value, f"{path}.{key}"))
        elif isinstance(node, list):
            pending.extend((value, f"{path}[{index}]") for index, value in enumerate(node))
        elif isinstance(node, str):
            if not _utf8(node):
                return "not-unicode", f"{path} holds text UTF-8 cannot carry"
        elif isinstance(node, float):
            if not math.isfinite(node):
                return "not-json-value", f"{path} is not a finite number"
        elif node is not None and not isinstance(node, (int, bool)):
            return "not-json-value", f"{path} is not a JSON value"
    return None


def _utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _number(value: Any) -> bool:
    """A JSON number: int or finite float, never a bool (which Python counts as an int)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


# ------------------------------------------------------------------ one element's grammar


def _instant(text: Any, where: str) -> _dt.datetime:
    if not isinstance(text, str) or MSGTIME.fullmatch(text) is None:
        raise BarentswatchHaisRefused(
            "bad-msgtime",
            f"{where}.msgtime is not an RFC 3339 date-time with seconds and an explicit offset; "
            "an instant without an offset is refused rather than assumed UTC",
        )
    try:
        stamp = _dt.datetime.fromisoformat(text)
    except ValueError:
        raise BarentswatchHaisRefused(
            "bad-msgtime", f"{where}.msgtime is not a calendar instant"
        ) from None
    try:
        return stamp.astimezone(_dt.timezone.utc)
    except OverflowError:
        raise BarentswatchHaisRefused(
            "bad-msgtime", f"{where}.msgtime falls outside the years a timestamp can hold"
        ) from None


def _check_point(point: Any, index: int) -> None:
    """Hold one element to the grammar. Values are checked for TYPE and for the ranges a CDM
    field would refuse; a value that is merely unusual is carried, not judged."""
    where = f"[{index}]"
    if not isinstance(point, dict):
        raise BarentswatchHaisRefused("bad-point", f"{where} is not an object")
    missing = [key for key in REQUIRED_KEYS if key not in point]
    if missing:
        raise BarentswatchHaisRefused(
            "missing-key",
            f"{where} has no {', '.join(missing)}; every element states mmsi, msgtime, latitude "
            "and longitude and none of them is defaulted",
        )
    mmsi = point["mmsi"]
    if not (isinstance(mmsi, int) and not isinstance(mmsi, bool) and 0 < mmsi <= MAX_MMSI):
        raise BarentswatchHaisRefused(
            "bad-mmsi", f"{where}.mmsi is not an integer of at most nine digits above zero"
        )
    for key, low, high, sentinel in (
        ("latitude", -90, 90, LAT_UNAVAILABLE),
        ("longitude", -180, 180, LON_UNAVAILABLE),
    ):
        value = point[key]
        if value is None:
            continue
        if not _number(value):
            raise BarentswatchHaisRefused(
                "bad-coordinate", f"{where}.{key} is not a number or null"
            )
        # The sentinel is a documented absence, not an out-of-range coordinate.
        if value != sentinel and not low <= value <= high:
            raise BarentswatchHaisRefused(
                "coordinate-out-of-range",
                f"{where}.{key} is outside [{low}, {high}] degrees and is not the AIS 'not "
                "available' value",
            )
    for key in NUMERIC_KEYS:
        if key in point and point[key] is not None and not _number(point[key]):
            raise BarentswatchHaisRefused("bad-element", f"{where}.{key} is not a number or null")
    for key in TEXT_KEYS:
        if key in point and point[key] is not None and not isinstance(point[key], str):
            raise BarentswatchHaisRefused("bad-element", f"{where}.{key} is not text or null")
    # The two ranges a CDM field would refuse outright; refusing here names the element.
    if point.get("speedOverGround") is not None and point["speedOverGround"] < 0:
        raise BarentswatchHaisRefused("bad-element", f"{where}.speedOverGround is negative")
    if point.get("courseOverGround") is not None and point["courseOverGround"] < 0:
        raise BarentswatchHaisRefused("bad-element", f"{where}.courseOverGround is negative")


def _has_position(point: dict) -> bool:
    lat, lon = point["latitude"], point["longitude"]
    if lat is None or lon is None:
        return False
    return lat != LAT_UNAVAILABLE and lon != LON_UNAVAILABLE


def _sentinel_fields(point: dict) -> list[str]:
    """The keys this element marks 'not available' with an AIS in-band value."""
    found = [key for key, sentinel in SENTINELS if point.get(key) == sentinel]
    cog = point.get("courseOverGround")
    if cog is not None and cog >= COG_UNAVAILABLE:
        found.append("courseOverGround")
    return sorted(found)


def _speed_mps(point: dict) -> float | None:
    sog = point.get("speedOverGround")
    if sog is None or sog == SOG_UNAVAILABLE:
        return None
    return round(sog * KNOT_MPS, 4)


def _course(point: dict) -> float | None:
    cog = point.get("courseOverGround")
    if cog is None or cog >= COG_UNAVAILABLE:
        return None
    return float(cog)


def _heading(point: dict) -> int | float | None:
    heading = point.get("trueHeading")
    return None if heading is None or heading == HEADING_UNAVAILABLE else heading


def _rate_of_turn(point: dict) -> int | float | None:
    rot = point.get("rateOfTurn")
    return None if rot is None or rot == ROT_UNAVAILABLE else rot


def _mmsi_category(mmsi: str) -> tuple[str, str | None]:
    """The ITU station category and MID digits, by the `ais` adapter's own prefix table. Recorded,
    never looked up further: a flag state is not an affiliation."""
    for prefix, category, mid_slice in _ais.MMSI_PREFIXES:
        if mmsi.startswith(prefix):
            return category, (mmsi[mid_slice] if mid_slice else None)
    return _ais.MMSI_SHIP_STATION, mmsi[:3]


def _entity_type(category: str) -> EntityType:
    """The `ais` adapter's MMSI rule (`ais._entity_type`, its second input): a coast station or an
    aid to navigation is a fixed installation whatever message it sends, so a FACILITY; every
    other category is a PLATFORM. The first input of that rule, a type 21 message's virtual-aid
    flag, does not exist in a track file."""
    if category in _ais.MMSI_FACILITY_CATEGORIES:
        return EntityType.FACILITY
    return EntityType.PLATFORM


def _source_order(instants: list[_dt.datetime]) -> str:
    """How the file arrived: descending, ascending, single-instant or unordered."""
    pairs = list(zip(instants, instants[1:]))
    if all(a == b for a, b in pairs):
        return "single-instant"
    if all(a >= b for a, b in pairs):
        return "descending"
    if all(a <= b for a, b in pairs):
        return "ascending"
    return "unordered"


# ------------------------------------------------------------------ the adapter


class BarentswatchHaisAdapter(Adapter):
    """One BarentsWatch Historic AIS track file in; an Entity, a Track and a TRACK_UPDATE Event
    out. `synthetic` defaults to True; a caller translating real API output passes False."""

    name = "barentswatch_hais"
    version = "1.2.0"
    direction = "ingest"
    system = SYSTEM

    #: `PUBLIC_GOVERNMENT`, the class this package gives a government agency's free public API
    #: (`airnow_hourly`, `coops_csv`): BarentsWatch is operated for the Norwegian state, the AIS
    #: data are collected by the Norwegian Coastal Administration, the API is documented publicly
    #: at API_DOCS, and the terms page licenses the data under the Norwegian Licence for Open
    #: Government Data (NLOD, no version stated) with the credit "Data delivered by BarentsWatch"
    #: (`fixtures/barentswatch_hais/spec/barentswatch_hais_terms.json`, read 2026-10-22). `OPEN`
    #: is the defensible alternative (NLOD is an open licence); the government-publisher reading
    #: is the one this package's precedents take.
    metadata = AdapterMetadata(
        id="barentswatch_hais",
        name="BarentsWatch Historic AIS track JSON translator",
        adapter_version="1.2.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today: `python -m "
            "synapse_cdm.harness --adapter barentswatch_hais` reports `translate`, `schema` and "
            "`provenance` PASS on "
            "every fixture, which carries L1 to L3, and its `lossless` column rests on the "
            "path-bound ledger (`MAPPINGS` declared, the whole document a structured residual on "
            "the Entity) with no LOST leaf. L4 is NOT declared: this adapter is ingest-only, so "
            "the roundtrip check is inapplicable rather than passed, and a rung passed vacuously "
            "is not a rung declared. Every fixture is synthetic; no real API response is part of "
            "the evidence.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "BarentsWatch Historic AIS track response (GET /v1/historic/tracks/{mmsi}/{from}/"
                "{to}): one JSON array of position reports for one MMSI per call, as its UTF-8 "
                "octets or as the parsed list; one Entity, one Track and one TRACK_UPDATE Event "
                "per file",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_objects": "not a bound this format needs: one file yields exactly three "
                    "objects whatever it holds; the number of elements is bounded by "
                    "max_input_bytes for octets and by MAX_POINTS = 200000 for every input "
                    "(refused too-many-points before any element is read)",
                    "max_decompressed_bytes": "this adapter accepts no compressed payload; HTTP "
                    "content encoding is the caller's to undo, so there is no expansion to bound",
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock but the injected one, and the byte, depth and element bounds make "
                    "every walk linear in a bounded input; the conformance suite's worker kills a "
                    "decode that overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The API documentation states no maximum response size. The "
                            "largest real track file observed for one MMSI over one UTC day "
                            "held a few thousand elements, roughly 1 MB at about 250 octets "
                            "per element; 16 MiB (16 777 216 octets, `MAX_INPUT_BYTES`, "
                            "`adapters/barentswatch_hais.py`) leaves an order of magnitude "
                            "of headroom for a longer window. This is an IMPLEMENTATION CAP "
                            "and is NOT the format's normative maximum."
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused "
                            "before this module decodes anything"
                        ),
                        test=(
                            "tests/test_cdm_input_bounds.py::"
                            "test_every_adapter_refuses_one_octet_over_its_declared_bound"
                        ),
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "A track file nests two containers (the array and an element); an "
                            "unknown key holding a structure can add more. 64 (`MAX_DEPTH`) is "
                            "the harness loader's own bound and the figure synapse_cdm's JSON "
                            "adapters declare. This is an IMPLEMENTATION CAP and is NOT the "
                            "format's normative maximum."
                        ),
                        enforced_at=(
                            "the base class: `Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` on the octets (read off the "
                            "characters before json.loads) and on a parsed list (off its "
                            "containers) before this class's `to_cdm` runs"
                        ),
                        test=(
                            "tests/test_cdm_parser_safety.py::"
                            "test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it"
                        ),
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "the whole document, every element and every key in it, known or not, is the "
                "Entity's structured residual (`residual.data.points`, file order), and the "
                "names of keys outside the twelve the API is observed to write are listed at "
                "`attributes.unknown_keys`. The document is an ARRAY, so the conformance suite's "
                "check I, which injects keys into dict documents only, has no document to probe"
            ),
        ),
        limitations=[
            Limitation(
                id="one-track-file-per-call",
                summary="exactly one track response per call, for one MMSI, as UTF-8 octets or as "
                "the parsed list; JSON text as str, a dict and a batch of files are not taken. A "
                "file holding more than one MMSI is refused mixed-mmsi",
            ),
            Limitation(
                id="no-join-across-files",
                summary="nothing is joined across files: two windows of one vessel are two "
                "Tracks with one entity_id. A Track's and its Event's ids derive from the MMSI "
                "and the first and last sample instants, so two files spanning the same two "
                "instants give one track_id; the id names the vessel's window, not the file",
            ),
            Limitation(
                id="open-data-coverage",
                summary="the open BarentsWatch AIS data EXCLUDE fishing vessels under 15 m and "
                "leisure craft under 45 m, so an absent vessel or an empty window is not "
                "evidence that nothing was there",
            ),
            Limitation(
                id="retention-window",
                summary="the historic API serves a limited retention window (the API "
                "documentation states 'No data older than 14 days', read 2026-10-22); older "
                "history is not retrievable through it, and this adapter states nothing about "
                "what lies outside the file",
            ),
            Limitation(
                id="provider-satellite-filtering",
                summary="the provider filters satellite-received positions when a terrestrial "
                "one exists (`stream` names the receiving network); the file is the provider's "
                "selection, not every report that was transmitted, and a gap may be a filtered "
                "report",
            ),
            Limitation(
                id="rate-of-turn-unit-not-established",
                summary="the API documentation does not establish whether rateOfTurn is the raw "
                "ROT_AIS integer or degrees per minute, so it is carried verbatim per sample and "
                "never converted; -128 is read as the AIS 'not available' value",
            ),
            Limitation(
                id="per-sample-fields-on-the-entity",
                summary="TrackSample holds a position and an instant only, so each element's "
                "speed, course, heading, rate of turn, navigational status and stream ride in "
                "`attributes.barentswatch_samples` (arrays keyed by sample index) and the whole "
                "element in `residual.data.points[source_index]`; only the last sample's speed "
                "and course reach Entity.kinematics",
            ),
            Limitation(
                id="entity-type-from-the-mmsi-category",
                summary="the entity type is the ais adapter's MMSI rule and nothing else: a "
                "coast-station or aid-to-navigation MMSI (ais.MMSI_FACILITY_CATEGORIES) is a "
                "FACILITY whatever it transmits, every other MMSI is a PLATFORM, and the category "
                "is recorded at attributes.mmsi_category. A VIRTUAL aid to navigation, which the "
                "ais adapter reads from a type 21 message's own flag and types OVERLAY_OBJECT, "
                "cannot be told from a track file, so an aid-to-navigation MMSI here is always "
                "the physical FACILITY",
            ),
            Limitation(
                id="ledger-cannot-bind-reordered-samples",
                summary="the lossless ledger binds every source leaf to the residual and the MMSI "
                "to all three objects; it cannot express the time-order permutation from "
                "elements to samples, so the binding of latitude and longitude to "
                "Track.samples is proven by the adapter's tests, not by the ledger",
            ),
            Limitation(
                id="synthetic-evidence-only",
                summary="every fixture is synthetic (MMSIs under the unallocated MID 299, as the "
                "ais fixtures use them, EX-prefixed names, positions inside CONTRIBUTING.md's "
                "Baltic rectangle); the shape follows the API's observed output, and no real "
                "response is part of the evidence",
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
        "[*].mmsi": T_MMSI,
        "[*]": T_ORDER,
        "[*].msgtime": T_INSTANT,
        "[*].latitude": T_POSITION_SENTINEL,
        "[*].longitude": T_POSITION_SENTINEL,
        "[*].speedOverGround": T_SPEED,
        "[*].courseOverGround": T_COURSE,
        "[*].trueHeading": T_HEADING,
        "[*].rateOfTurn": T_ROT,
    }

    #: The ledger. The Entity's residual holds the whole document in file order, so every leaf is
    #: bound to its own path there; the MMSI is also bound, verbatim, to the Track's and the
    #: Event's residuals. The specific key comes before the `[*]` subtree, because the first
    #: declaration that matches a leaf is the one it is held to.
    MAPPINGS = {
        "[*].mmsi": (
            Mapping(to="entity:residual.data.points[*].mmsi", kind="residual"),
            Mapping(to="track:residual.data.mmsi"),
            Mapping(to="event:residual.data.mmsi"),
        ),
        "[*]": (Mapping(to="entity:residual.data.points[*]", kind="residual"),),
    }

    def __init__(
        self,
        clock: times.Clock | None = None,
        *,
        synthetic: bool = True,
        source_hash: SourceHash | dict | None = None,
    ) -> None:
        """`synthetic` defaults to True (the safe direction); a caller translating real API output
        passes False. `source_hash` is the SHA-256 of the input file as the caller read it, given
        as a `SourceHash` or `{"algorithm": "sha256", "value": <64 lower-case hex digits>}`; it is
        validated here, carried onto every object, and never computed by this adapter."""
        super().__init__(clock, synthetic=synthetic)
        if source_hash is not None:
            source_hash = SourceHash.model_validate(source_hash)
            if source_hash.algorithm != "sha256" or not re.fullmatch(
                "[0-9a-f]{64}", source_hash.value
            ):
                raise ValueError("source_hash is a sha256 digest of 64 lower-case hex digits")
        self._source_hash = source_hash

    def to_cdm(self, raw: bytes | list) -> list[CDMBase]:
        """One track file -> [Entity, Track, Event]. Refuses what it cannot read; never returns a
        partial result."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            document = parse_document(bytes(raw))
        elif isinstance(raw, list):
            document = raw
        else:
            raise BarentswatchHaisRefused(
                "unsupported-input",
                "a track file is handed over as its UTF-8 octets or as the parsed list; JSON "
                "text as str, a dict and other types are not taken",
            )
        if not isinstance(document, list):
            raise BarentswatchHaisRefused("not-an-array", "the JSON document is not an array")
        if not document:
            raise BarentswatchHaisRefused(
                "empty-track", "the array holds no element, and a Track holds at least one sample"
            )
        # Before any element is walked or any model built: the byte bound does not bound a list
        # handed over parsed, and the model graph costs far more per element than the JSON does.
        if len(document) > MAX_POINTS:
            raise BarentswatchHaisRefused(
                "too-many-points",
                f"the array holds more than max_points = {MAX_POINTS} elements; refused before "
                "any element is read",
            )
        problem = _json_problem(document)
        if problem is not None:
            raise BarentswatchHaisRefused(*problem)
        for index, point in enumerate(document):
            _check_point(point, index)
        mmsis = {point["mmsi"] for point in document}
        if len(mmsis) != 1:
            raise BarentswatchHaisRefused(
                "mixed-mmsi",
                f"the elements state {len(mmsis)} different MMSIs; one track file is one vessel "
                "and nothing here splits or merges vessels",
            )
        return self._translate(document)

    def _translate(self, document: list[dict]) -> list[CDMBase]:
        mmsi_number = document[0]["mmsi"]
        mmsi = f"{mmsi_number:09d}"
        source_ids = [{"system": MMSI_SYSTEM, "external_id": mmsi}]

        instants = [_instant(point["msgtime"], f"[{i}]") for i, point in enumerate(document)]
        source_order = _source_order(instants)
        positioned = [i for i, point in enumerate(document) if _has_position(point)]
        has_sample = set(positioned)
        without_position = [i for i in range(len(document)) if i not in has_sample]
        if not positioned:
            raise BarentswatchHaisRefused(
                "no-positioned-point",
                "no element states a usable position (every latitude or longitude is null or "
                "the AIS 'not available' value), and a Track holds at least one sample",
            )
        # Ascending by instant; among equal instants, later file index first, so a newest-first
        # file maps onto exactly its reversal and the order is a pure function of the file.
        order = sorted(positioned, key=lambda i: (instants[i], -i))

        samples: list[TrackSample] = []
        readings: dict[str, list] = {
            "source_index": [],
            "speed_mps": [],
            "speed_at_or_above_maximum": [],
            "course_deg": [],
            "true_heading_deg": [],
            "rate_of_turn": [],
            "navigational_status": [],
            "stream": [],
            "sentinel_fields": [],
            "null_fields": [],
        }
        for i in order:
            point = document[i]
            samples.append(
                TrackSample(
                    position=Position(
                        lat=point["latitude"],
                        lon=point["longitude"],
                        # AIS states no height; a vessel's sea level would be a value nobody stated.
                        alt_m=None,
                        position_source=PositionSource.ESTIMATED,
                        accuracy_m=None,
                    ),
                    observed_at=instants[i],
                )
            )
            readings["source_index"].append(i)
            readings["speed_mps"].append(_speed_mps(point))
            readings["speed_at_or_above_maximum"].append(
                point.get("speedOverGround") == SOG_AT_OR_ABOVE_MAXIMUM
            )
            readings["course_deg"].append(_course(point))
            readings["true_heading_deg"].append(_heading(point))
            readings["rate_of_turn"].append(_rate_of_turn(point))
            readings["navigational_status"].append(point.get("navigationalStatus"))
            readings["stream"].append(point.get("stream"))
            readings["sentinel_fields"].append(_sentinel_fields(point))
            readings["null_fields"].append(sorted(k for k, v in point.items() if v is None))

        duplicates = []
        start = 0
        while start < len(order):
            end = start
            while end + 1 < len(order) and instants[order[end + 1]] == instants[order[start]]:
                end += 1
            if end > start:
                group = [document[order[k]] for k in range(start, end + 1)]
                duplicates.append(
                    {
                        "instant": times.render(instants[order[start]]),
                        "sample_indices": list(range(start, end + 1)),
                        "identical": all(p == group[0] for p in group[1:]),
                    }
                )
            start = end + 1

        first, last = samples[0].observed_at, samples[-1].observed_at
        span = f"{mmsi}@{times.render(first)}..{times.render(last)}"
        entity_id = ids.derive(MMSI_SYSTEM, mmsi, kind="entity")
        track_id = ids.derive(MMSI_SYSTEM, span, kind="track")
        event_id = ids.derive(MMSI_SYSTEM, span, kind="event")

        last_point = document[order[-1]]
        speed, course = _speed_mps(last_point), _course(last_point)
        kinematics = (
            None
            if speed is None and course is None
            else Kinematics(speed_mps=speed, course_deg=course)
        )

        # Rule 5's chain, per object: each lists the transformations ITS fields went through.
        exercised_sentinels = {f for fields in readings["sentinel_fields"] for f in fields}
        position_sentinel = bool(without_position)
        track_chain = [T_MMSI, T_ORDER, T_INSTANT] + [T_POSITION_SENTINEL] * position_sentinel
        entity_chain = (
            track_chain
            # A converted speed anywhere (per-sample readings included) or a speed sentinel.
            + [T_SPEED]
            * (
                any(v is not None for v in readings["speed_mps"])
                or "speedOverGround" in exercised_sentinels
            )
            # A real course is carried unchanged; only the sentinel is a transformation.
            + [T_COURSE] * ("courseOverGround" in exercised_sentinels)
            + [T_HEADING] * ("trueHeading" in exercised_sentinels)
            + [T_ROT] * ("rateOfTurn" in exercised_sentinels)
        )
        stamp = self.source_ref().model_copy(
            update={"original_id": mmsi, "source_hash": self._source_hash}
        )
        namespace = self.metadata.format.name
        stated = {"mmsi": mmsi_number}

        category, mid = _mmsi_category(mmsi)
        entity_type = _entity_type(category)
        names = list(dict.fromkeys(p["name"] for p in document if p.get("name") is not None))
        ship_types = list(
            dict.fromkeys(p["shipType"] for p in document if p.get("shipType") is not None)
        )
        unknown_keys = sorted({k for p in document for k in p if k not in KNOWN_KEYS})

        attributes: dict[str, Any] = {
            "mmsi": mmsi,
            "mmsi_category": category,
            "mmsi_mid": mid,
            "entity_id_basis": (
                f"the MMSI rendered as nine digits under {MMSI_SYSTEM}, as the ais adapter writes "
                "it, so a decoded AIS message and a BarentsWatch track of one vessel give one "
                "entity_id"
            ),
            "entity_type_basis": (
                f"{entity_type.value}: the ais adapter's MMSI rule, so one MMSI has one entity "
                "type across both adapters; a coast-station or aid-to-navigation MMSI "
                "(mmsi_category) is a FACILITY whatever it transmits, every other is a PLATFORM"
            ),
            "affiliation_basis": (
                "UNKNOWN: AIS states an identity and no side, and nothing in it is authenticated"
            ),
            "symbol_basis": "derived from affiliation; the file states no symbol",
            "position_basis": "the Track's last sample: the latest element stating a position",
            "position_source_basis": POSITION_SOURCE_BASIS,
            "kinematics_basis": (
                "the last sample's element: speedOverGround in knots converted to m/s, "
                "courseOverGround in degrees true; null and the AIS sentinels (102.3 kn; 360 deg "
                "and above) are unknown, never zero. trueHeading has no CDM field and is parked "
                "per sample"
            ),
            "valid_from_basis": "the instant of the earliest sample",
            "valid_to_basis": (
                "the instant of the latest sample: the file holds nothing after it, which says "
                "nothing about the vessel after it"
            ),
            "source_order": source_order,
            "source_order_basis": (
                "the order of msgtime across the file as delivered: descending (the API's "
                "observed newest-first order), ascending, single-instant or unordered; the "
                "samples are ascending whatever it was"
            ),
            "points_without_position": without_position,
            "points_without_position_basis": (
                "file indices of elements whose latitude or longitude is null or the AIS 'not "
                "available' value; they have no Track sample and stay whole in "
                "residual.data.points"
            ),
            "duplicate_instants": duplicates,
            "duplicate_instants_basis": (
                "groups of samples sharing one instant, every one kept: identical means the "
                "elements are equal key for key (a re-delivered report), otherwise the same "
                "instant is stated with different values and nothing here chooses between them"
            ),
            "vessel_names": names,
            "ship_types": ship_types,
            "names_basis": (
                "the distinct non-null name and shipType values in file order, verbatim; a "
                "shipType of 0 is AIS 'not available' and is listed as stated"
            ),
            "unknown_keys": unknown_keys,
            "unknown_keys_basis": (
                "keys outside the twelve the API is observed to write, preserved verbatim in "
                "residual.data.points and read for nothing"
            ),
            "barentswatch_samples": readings,
            "barentswatch_samples_basis": (
                "readings taken from each sampled element, keyed by sample index: index k is "
                "Track.samples[k] and residual.data.points[source_index[k]]. speed_mps is "
                "speedOverGround converted from knots; speed_at_or_above_maximum marks the 102.2 "
                "kn floor; course_deg and true_heading_deg are degrees; rate_of_turn is verbatim "
                "(unit not established); null and AIS sentinels read as null; sentinel_fields "
                "and null_fields name the keys each element marked unknown"
            ),
            "attribution": (
                "Data delivered by BarentsWatch (the credit its API terms require); the data are "
                "collected by the Norwegian Coastal Administration and licensed under the "
                "Norwegian Licence for Open Government Data (NLOD), as read on 2026-10-22 "
                "(fixtures/barentswatch_hais/spec/barentswatch_hais_terms.json)"
            ),
        }

        entity = Entity(
            source=stamp.model_copy(update={"transformations": entity_chain}),
            source_ids=source_ids,
            entity_id=entity_id,
            entity_type=entity_type,
            affiliation=Affiliation.UNKNOWN,
            symbol=sidc_from_affiliation(Affiliation.UNKNOWN, synthetic=self._synthetic),
            position=samples[-1].position,
            kinematics=kinematics,
            valid_from=first,
            valid_to=last,
            confidence=None,
            attributes=attributes,
            residual=Residual(namespace=namespace, data={"points": copy.deepcopy(document)}),
        )
        track = Track(
            source=stamp.model_copy(update={"transformations": list(track_chain)}),
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
                        "carried_samples counts the elements stating a usable position; a file "
                        "is one requested window of the vessel's history under a limited "
                        "retention period and the provider's filtering, so it is a fragment, and "
                        "the API states no total"
                    ),
                )
            ),
            residual=Residual(namespace=namespace, data=dict(stated)),
        )
        event = Event(
            source=stamp.model_copy(update={"transformations": [T_MMSI, T_INSTANT]}),
            source_ids=source_ids,
            event_id=event_id,
            event_type=EventType.TRACK_UPDATE,
            severity=Severity.INFO,
            related_entities=[entity_id],
            geometry=None,
            payload={
                "track_id": str(track_id),
                "sample_count": len(samples),
                "element_count": len(document),
                "observed_at_basis": (
                    "the msgtime of the latest sample, the instant the provider recorded for "
                    "that report, converted to UTC"
                ),
                "received_at_basis": "the injected clock; the file states no delivery instant",
                "event_type_basis": "TRACK_UPDATE: one track file is one update of a history",
                "event_id_basis": "the MMSI and the first and last sample instants",
                "severity_basis": (
                    "INFO: a history file states no urgency; navigational status is carried per "
                    "sample and no alert is derived from it"
                ),
                "validity_basis": (
                    "no validity: the event is an instant, and the span is the Entity's "
                    "valid_from and valid_to and the Track's samples"
                ),
            },
            observed_at=last,
            received_at=self.now(),
            residual=Residual(namespace=namespace, data=dict(stated)),
        )
        return [entity, track, event]
