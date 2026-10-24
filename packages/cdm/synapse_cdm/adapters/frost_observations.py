"""`frost_observations`, #33 in the ordinal table: MET Frost observations -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One response of Frost's `GET /observations/v0.jsonld`, handed over as its octets (UTF-8 JSON) or
as the parsed `dict`. Its top level is the response header (`@context`, `@type` =
`ObservationResponse`, `apiVersion` = `v0`, `license`, `createdAt`, `queryTime`,
`currentItemCount`, `itemsPerPage`, `offset`, `totalItemCount`, `currentLink`, ...) and `data[]`,
a list of data items. A data item is one `sourceId` at one `referenceTime` with its
`observations[]`; an observation states `elementId`, `value` and usually `unit`, and, where Frost
has them, `level`, `timeOffset`, `timeResolution`, `timeSeriesId`, `performanceCategory`,
`exposureCategory` and `qualityCode`.

WHAT ONE DOCUMENT BECOMES
-------------------------
`ENVIRONMENTAL_OBSERVATION` Events carrying the `point-observation/1` contract, in `data[]` order,
then one `Entity` (SENSOR, `site_entity`, site class `weather_station`) per station, in the order
stations first appear. A data item becomes ONE Event per time class of its observations (see
TIME): normally exactly one, the instant Event; a midnight item that also holds daily (`P1D`)
observations also becomes one daily Event per stated `timeOffset` of those observations.

- Each observation is one `Reading` of the Event its time class puts it in, in the item's order:
  `name` is the `elementId` verbatim (`sum(precipitation_amount PT1H)` included), the value and
  unit are carried verbatim in a `Measurement` whose `unit_namespace` names Frost's element table,
  and `level` is a `VerticalLevel` carrying `levelType`, `value` and `unit` as stated. A level is
  never turned into `Position.alt_m`: a height above ground is not a height above the ellipsoid.
  An observation without `level` has a reading without one.
- UNITS. An observation that states no `unit` takes the unit the caller's element table
  (`ElementTable`, built from Frost's `/elements/v0.jsonld`, e.g. with
  `element_table_from_elements`) names for its exact `elementId`; the measurement's
  `unit_namespace` then names that table, and the Event's transformations say, per reading, that
  the unit was not stated in the observation and was taken from the table. Where neither states a
  unit, the reading is an `Absence` of cause `unit_unknown` (the contract's rule: a value whose
  unit cannot be read is not stated) with the mechanism named; the number stays verbatim in the
  Event's residual. No unit is ever guessed from the element's name.
- The reading's `namespace` names the Frost elementId vocabulary AND the time series the value
  belongs to (`timeOffset`, `timeResolution`, `timeSeriesId` as stated). Frost can return one
  element in several series for one item ("Data is sometimes returned in multiple timeseries,
  with different level heights or time offsets", concepts2.html), and the contract holds no
  per-reading time field; the namespace is where the series is stated, verbatim, so two series
  of one element stay two distinguishable readings.
- `qualityCode`, `performanceCategory` and `exposureCategory` are typed `QualityFlag`s, values
  verbatim, `applies_to` naming the reading of that Event (`readings[j]`). Nobody interprets them
  here: MET's data clarifications page defines the tables (qualityCode 0 "OK, value is controlled
  and found O.K." ... 7 "Erroneous, value is not corrected"). An Event none of whose readings
  carries a flag says so in `quality_flags_basis`.
- Every Event's `residual` (namespace = the format name) holds the response header verbatim, all
  top-level keys but `data`, and its data item verbatim under `data_item` (every Event of one item
  carries the whole item). So a key Frost adds tomorrow, at the top, in an item or in an
  observation, is carried, never dropped.
- `createdAt` is Frost's processing clock: it becomes `product_version.production_time_verbatim`
  and stays in the residual under its own name; it is never an `*_at` time of any object.

TIME (https://frost.met.no/concepts2.html, "Relationship between referenceTime, timeOffset, and
timeResolution", read 2026-10-20)
----
Frost states, Case 1: "Observations with shorter timeResolution than 1 day, are generally stored
with date and time in the data storage. The referenceTime is then equal to the observation time,
and no timeOffset should be added to referenceTime to get the original observation time."; for a
referenceTime that is not midnight, it "is equal to observation time and timeOffset should not be
added"; Case 2.2, diurnal data: "They are stored with date only in the data storage with a
referenceTime of the form <year>-<month>-<day>T00:00. If timeOffset = PT0H, the observation value
represents the period from midnight to midnight on the calendar date ... If timeOffset != PT0H,
the observation represents the last 24 hr, at the time after midnight equal to timeOffset ...
ReferenceTime <date>T00:00 is just the specific date for the diurnal value. The end of the
observation period, is referenceTime + timeOffset."

So each observation falls in one time class:

- INSTANT: the `referenceTime` is not midnight UTC (any `timeResolution`), or it is midnight and
  the observation's `timeResolution` is shorter than one day. `observed_at` is the referenceTime
  and `validity.effective` is that instant; `timeOffset` is never added and is carried verbatim.
  The accumulation window an elementId names (`sum(precipitation_amount PT1H)`) is NOT turned into
  an interval: the concepts page does not state where a sub-daily window lies relative to
  referenceTime, so it stays in the elementId, verbatim.
- DAILY: the `referenceTime` is midnight and `timeResolution` is exactly `P1D` with a stated
  `timeOffset` shorter than one day. Case 2.2: with `PT0H` the period is the calendar date,
  [referenceTime, referenceTime + 24 h]; otherwise it is the 24 h ending at referenceTime +
  timeOffset. `validity.effective` is that period and `observed_at` its END (the contract's rule
  for an observation). The Event's identifier is `<sourceId>/<referenceTime>/P1D/<timeOffset>`.
- UNRESOLVED: the `referenceTime` is midnight and the observation states no `timeResolution`, a
  `timeResolution` longer than one day (P1M, P1Y, ... where Cases 2.3 to 2.5 depend on the element)
  or other than `P1D`, or a `P1D` without a usable `timeOffset`. The observation gets no reading
  (no time can be stated for it); the station Entity lists it in
  `attributes.unresolved_observations` with the reason, the item stays verbatim in the residual of
  its other Events, and an item with no resolvable observation at all is carried verbatim in the
  station Entity's residual under `unresolved_items`, beside the response header
  (`response_header`). Only that observation is set aside; the
  document is never refused for it.

STATIONS
--------
`sourceId` is `SN<station identity number>:<parallel sensor number>` (concepts2.html). The
STATION is the identity: `entity_id = ids.derive("FROST", "SN<n>")`, so the parallel
sensors of one station ("Periods with parallel sensors are typically used in the process of
replacing an old sensor with a new", concepts2.html) are one Entity, and the Entity lists the
sourceIds it was seen under. The full `sourceId`, suffix included, is the contract's `station_id`
verbatim and part of the Event's source identifier, so the sensor is never lost. A sourceId
without a suffix (`SN<n>`, which Frost documents as an alias of `SN<n>:0`) is read as stated and
never rewritten to `:0`.

Positions come ONLY from the caller's `station_table` (a `StationTable` keyed by the Frost station
id `SN<n>`, built from Frost's sources.json SensorSystem list, e.g. with
`station_table_from_sources`). The response states no position, and this module never fetches
one. A station absent from the table is emitted WITHOUT a position, the basis saying so: the
`ndbc_stdmet` / `airnow_hourly` precedent (`site_entity`), because refusing would drop every
reading of an otherwise valid station and inventing one is impossible.

REFUSALS
--------
A document is refused only for structural corruption: `FrostRefused(code, text)`, a `ValueError`;
the text names the path, never a value from the payload. Codes: unsupported-input, not-utf8,
byte-order-mark, not-json, duplicate-key, not-a-number-literal, not-utf8-text,
not-an-observation-response, unsupported-api-version, reserved-key, bad-created-at,
no-data-item, bad-item, bad-source-id, bad-reference-time, no-observation, bad-observation,
bad-element-id, bad-value, bad-unit, bad-level, bad-duration, bad-quality-flag, repeated-series,
repeated-item, too-many-objects.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import re
import types
from typing import Any, Mapping as MappingType

from synapse_cdm import times
from synapse_cdm.adapter import Adapter
from synapse_cdm.geo import Point
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
    Period,
    Residual,
    SourceHash,
    SourceId,
    TemporalValidity,
)
from synapse_cdm.observation_contracts import (
    Absence,
    Measurement,
    PointObservation,
    ProductVersion,
    QualityFlag,
    Reading,
    StationTable,
    TableLocator,
    TimeInputs,
    TimeSystem,
    VerticalLevel,
    json_number,
    observation_event,
    site_entity,
    utf8_text,
)

#: `source.system` on every object and the system of every identifier.
SYSTEM = "FROST"
FORMAT_NAME = "MET Norway Frost ObservationResponse (GET /observations/v0.jsonld)"
FORMAT_VERSION = (
    'Frost API v0 (apiVersion "v0"), as documented at https://frost.met.no/concepts2.html'
)
API_VERSION = "v0"
RESPONSE_TYPE = "ObservationResponse"

#: The residual key that holds the data item beside the header's own keys. A response whose top
#: level states this key itself is refused, so the residual never merges two meanings into one key.
DATA_ITEM_KEY = "data_item"

#: Implementation caps (see `metadata.capabilities.limits.declared_because`).
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64
MAX_OBJECTS = 50_000

CONCEPTS_URL = "https://frost.met.no/concepts2.html"
CLARIFICATIONS_URL = "https://frost.met.no/dataclarifications.html"
ELEMENT_TABLE_URL = "https://frost.met.no/elementtable"

ELEMENT_NAMESPACE = f"MET Norway Frost elementId ({ELEMENT_TABLE_URL})"
UNIT_NAMESPACE = (
    f"MET Norway Frost observation unit, element table vocabulary ({ELEMENT_TABLE_URL})"
)
LEVEL_NAMESPACE = "MET Norway Frost observation level (levelType, value and unit as stated)"
STATION_NAMESPACE = (
    "MET Norway Frost sourceId, SN<station identity number>:<parallel sensor number> "
    f"({CONCEPTS_URL})"
)
FLAG_NAMESPACES = {
    "qualityCode": f"MET Norway Frost qualityCode ({CLARIFICATIONS_URL})",
    "performanceCategory": f"MET Norway Frost performanceCategory ({CLARIFICATIONS_URL})",
    "exposureCategory": f"MET Norway Frost exposureCategory ({CLARIFICATIONS_URL})",
}
#: The observation keys that name the time series a value belongs to, in namespace order.
SERIES_KEYS = ("timeOffset", "timeResolution", "timeSeriesId")

NO_FLAGS_BASIS = (
    "no observation of this Event states qualityCode, performanceCategory or "
    f"exposureCategory; Frost defines them at {CLARIFICATIONS_URL} and states none here"
)
UNIT_UNKNOWN = (
    "the observation states no unit and no caller-supplied Frost element table names one for "
    "its elementId, so the value's unit cannot be read; the number stays verbatim in the "
    "Event's residual (residual.data.data_item.observations)"
)

TIME_SYSTEM = TimeSystem(
    name="UTC",
    stated_by="source",
    basis="Frost writes referenceTime in RFC 3339 with the Z designator (UTC)",
)

T_SUB_DAILY = (
    f"referenceTime is the observation time ({CONCEPTS_URL}, Case 1: each reading of this Event "
    "has a timeResolution shorter than one day; 'no timeOffset should be added'); "
    "validity.effective is that instant and timeOffset is carried verbatim, never added"
)
T_NOT_MIDNIGHT = (
    f"referenceTime is the observation time ({CONCEPTS_URL}: a referenceTime different from "
    "midnight 'is equal to observation time and timeOffset should not be added'); "
    "validity.effective is that instant and timeOffset is carried verbatim, never added"
)
T_DAILY = (
    f"daily value at a midnight referenceTime ({CONCEPTS_URL}, Case 2.2: 'ReferenceTime "
    "<date>T00:00 is just the specific date for the diurnal value'; with timeOffset PT0H the value "
    "'represents the period from midnight to midnight on the calendar date', otherwise 'the last "
    "24 hr, at the time after midnight equal to timeOffset', and 'The end of the observation "
    "period, is referenceTime + timeOffset'); validity.effective is that 24 h period and "
    "observed_at its end"
)
T_STATION = (
    "the station identity is the sourceId's part before ':' (the parallel sensor number is "
    "kept in each Event's station_id and source identifier)"
)

_CAP = (
    "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum (the Frost API "
    "states none)."
)
_TESTS = "tests/test_cdm_frost_observations_adapter.py::"

_SOURCE_ID = re.compile(r"(SN[0-9]+)(?::([0-9]+))?")
_REFERENCE_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z"
)
_DURATION = re.compile(
    r"P(?:([0-9]{1,9})Y)?(?:([0-9]{1,9})M)?(?:([0-9]{1,9})W)?(?:([0-9]{1,9})D)?"
    r"(?:T(?:([0-9]{1,9})H)?(?:([0-9]{1,9})M)?(?:([0-9]{1,9}(?:\.[0-9]{1,9})?)S)?)?"
)
_DAY_SECONDS = 86_400
_DAILY = "P1D"

FIXTURE_STATIONS = StationTable(
    name="frost-observations-fixture-stations",
    basis="synthetic station positions written for the fixtures on 2026-10-22 "
    "(fixtures/frost_observations/README.md), inside CONTRIBUTING.md's Baltic rectangle; no real "
    "station is named",
    rows=[
        {"station_id": "SN00001", "lat": 57.2, "lon": 21.3},
        {"station_id": "SN00002", "lat": 56.8, "lon": 23.9},
        {"station_id": "SN00003", "lat": 58.1, "lon": 22.4},
    ],
)


class FrostRefused(ValueError):
    """A document this module will not translate. `code` names the rule; the text names the
    path, never a value from the payload (the payload may be licensed or sensitive, and a
    diagnostic is published)."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        # Picklable with its code, because the conformance suite refuses payloads in a worker
        # process and ships the exception back.
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> FrostRefused:
    refusal = FrostRefused(code, "")
    refusal.args = (message,)
    return refusal


@dataclasses.dataclass(frozen=True)
class ElementTable:
    """Element units the caller supplies, keyed by Frost `elementId` exactly as written.

    The `StationTable` pattern for units: a constructor argument (so part of the determinism
    tuple), read from Frost's `/elements/v0.jsonld` by the CALLER, never fetched here. It is
    consulted only for an observation that states no `unit`, and only by exact `elementId`: a
    calculation-method id (`sum(precipitation_amount PT1H)`) matches only a row with that id.
    """

    name: str
    basis: str
    units: MappingType[str, str]

    def __post_init__(self) -> None:
        for field in ("name", "basis"):
            value = getattr(self, field)
            if type(value) is not str or not value.strip() or not utf8_text(value):
                raise ValueError(f"ElementTable.{field} is a non-blank string")
        if not isinstance(self.units, MappingType) or not self.units:
            raise ValueError("ElementTable.units maps at least one elementId to its unit")
        for element, unit in self.units.items():
            for text in (element, unit):
                if type(text) is not str or not text.strip() or not utf8_text(text):
                    raise ValueError(
                        "ElementTable.units maps non-blank strings to non-blank strings"
                    )
        # Frozen copy: a caller mutating its dict later must not change what this table says.
        object.__setattr__(self, "units", types.MappingProxyType(dict(self.units)))

    def unit_of(self, element_id: str) -> str | None:
        return self.units.get(element_id)


FIXTURE_ELEMENTS = ElementTable(
    name="frost-observations-fixture-elements",
    basis="synthetic element units written for the fixtures on 2026-10-22 "
    "(fixtures/frost_observations/README.md), in the shape of Frost's /elements/v0.jsonld",
    units={"wind_speed": "m/s", "wind_from_direction": "degrees", "air_temperature": "degC"},
)


# -- octets to the document ----------------------------------------------------------------------


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    # `json.loads` keeps the LAST of two equal keys and drops the first without a word, which is a
    # value lost before this adapter ever sees it; refusing is the only lossless answer.
    document: dict = {}
    for key, value in pairs:
        if key in document:
            raise FrostRefused("duplicate-key", "an object states one key twice")
        document[key] = value
    return document


def _refuse_constant(name: str) -> Any:
    raise FrostRefused(
        "not-a-number-literal", "the document holds NaN or an infinity, which JSON does not"
    )


def parse_document(octets: bytes) -> Any:
    """The parsed document of a Frost response's octets: UTF-8 without a byte-order mark, JSON
    with no duplicate key and no NaN/Infinity literal."""
    if octets.startswith(b"\xef\xbb\xbf"):
        raise FrostRefused("byte-order-mark", "the document opens with a byte-order mark")
    try:
        text = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise FrostRefused("not-utf8", "the document is not UTF-8 text") from None
    try:
        return json.loads(
            text, object_pairs_hook=_no_duplicate_keys, parse_constant=_refuse_constant
        )
    except json.JSONDecodeError:
        raise FrostRefused("not-json", "the document is not one JSON value") from None


def _check_json_shape(node: Any, path: str = "$") -> None:
    """Every key and string Unicode a UTF-8 serialisation carries, every number finite and
    within a double, and nothing that is not JSON. A `dict` handed over by a caller skipped the
    parser, so this is what holds it to what a parse could have produced; the residual carries
    the whole document, so a value it cannot serialise must be refused here, not at write time.
    Iterative, for the reason `adapter.container_depth` gives."""
    pending = [(node, path)]
    while pending:
        value, where = pending.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if type(key) is not str or not utf8_text(key):
                    raise FrostRefused("not-utf8-text", f"a key under {where} is not UTF-8 text")
                pending.append((child, f"{where}.{key}"))
        elif isinstance(value, list):
            pending.extend((child, f"{where}[{i}]") for i, child in enumerate(value))
        elif isinstance(value, str):
            if not utf8_text(value):
                raise FrostRefused("not-utf8-text", f"{where} is not UTF-8 text")
        elif value is None or isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)):
            if not json_number(value):
                raise FrostRefused("bad-value", f"{where} is not a finite number a double holds")
        else:
            raise FrostRefused("bad-item", f"{where} is not a JSON value")


# -- the caller's tables -------------------------------------------------------------------------


def station_table_from_sources(document: Any, *, name: str, basis: str) -> StationTable:
    """A `StationTable` from a Frost `GET /sources/v0.jsonld` response (a SensorSystem list).

    For the CALLER, who owns the join: each `SensorSystem` with a `Point` geometry contributes
    one row, `station_id` = its `id` (`SN<n>`), `lat`/`lon` from `geometry.coordinates`
    ([lon, lat], GeoJSON order). A source without a Point geometry contributes no row, so its
    observations' station Entity has no position and says why. Anything else in the document
    is outside a StationTable and not read. Raises `FrostRefused` on a malformed list.
    """
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        raise FrostRefused("bad-item", "a sources response is an object with a data list")
    rows = []
    for index, source in enumerate(document["data"]):
        where = f"data[{index}]"
        if not isinstance(source, dict) or type(source.get("id")) is not str:
            raise FrostRefused("bad-item", f"{where} is not a source with an id")
        geometry = source.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("@type") != "Point":
            continue
        coordinates = geometry.get("coordinates")
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 2
            or not all(json_number(c) for c in coordinates)
        ):
            raise FrostRefused("bad-item", f"{where}.geometry.coordinates is not [lon, lat]")
        lon, lat = (float(c) for c in coordinates)
        rows.append({"station_id": source["id"], "lat": lat, "lon": lon})
    if not rows:
        raise FrostRefused("bad-item", "the sources response holds no source with a Point")
    try:
        return StationTable(name=name, basis=basis, rows=rows)
    except ValueError as problem:
        raise FrostRefused(
            "bad-item", f"the sources do not make a station table: {type(problem).__name__}"
        ) from None


def element_table_from_elements(document: Any, *, name: str, basis: str) -> ElementTable:
    """An `ElementTable` from a Frost `GET /elements/v0.jsonld` response.

    For the CALLER: each `data[]` element with a string `id` and a non-blank string `unit`
    contributes `id -> unit`; an element without a unit contributes nothing, so an observation of
    it that states no unit stays `unit_unknown`. Two rows of one id with different units are
    refused (`bad-item`) rather than one chosen. Nothing else in the document is read.
    """
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        raise FrostRefused("bad-item", "an elements response is an object with a data list")
    units: dict[str, str] = {}
    for index, element in enumerate(document["data"]):
        where = f"data[{index}]"
        if (
            not isinstance(element, dict)
            or type(element.get("id")) is not str
            or not element["id"].strip()
        ):
            raise FrostRefused("bad-item", f"{where} is not an element with an id")
        unit = element.get("unit")
        if type(unit) is not str or not unit.strip():
            continue
        if units.get(element["id"], unit) != unit:
            raise FrostRefused("bad-item", f"{where} states another unit for an id already read")
        units[element["id"]] = unit
    if not units:
        raise FrostRefused("bad-item", "the elements response holds no element with a unit")
    try:
        return ElementTable(name=name, basis=basis, units=units)
    except ValueError as problem:
        raise FrostRefused(
            "bad-item", f"the elements do not make an element table: {type(problem).__name__}"
        ) from None


# -- the declaration -----------------------------------------------------------------------------


class FrostObservationsAdapter(Adapter):
    """One Frost ObservationResponse in; Events per data item and time class, one Entity per
    station out."""

    name = "frost_observations"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: `PUBLIC_GOVERNMENT`: the Frost API is the free public data service of a government agency
    #: (the Norwegian Meteorological Institute), the class `ndbc_stdmet`, `coops_csv` and
    #: `airnow_hourly` declare for their agencies' services. The data licence is the RESPONSE's
    #: own statement (`license`, carried verbatim in every Event's residual).
    metadata = AdapterMetadata(
        id="frost_observations",
        name="MET Norway Frost ObservationResponse (observations/v0.jsonld) translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today: `python -m "
            "synapse_cdm.harness --adapter frost_observations` reports translate, schema, "
            "provenance, lossless (basis: ledger, MAPPINGS declared, no LOST leaf) and golden PASS "
            "on every fixture. Every fixture is synthetic, written from the documented response "
            "shape and Frost's concepts page; the daily-at-midnight and missing-unit cases were "
            "found on real responses outside this repository, none of which is evidence here. L4 "
            "is NOT declared: the adapter is ingest-only, so the roundtrip check is inapplicable "
            "rather than passed, and a rung passed vacuously is not a rung declared.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "MET Norway Frost GET /observations/v0.jsonld ObservationResponse, one document "
                "per call, as its UTF-8 octets or its parsed dict; ENVIRONMENTAL_OBSERVATION "
                "Events carrying point-observation/1, one per data item (sourceId x "
                "referenceTime) and time class (instant, or Case 2.2 daily), and one SENSOR "
                "Entity per Frost station",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=MAX_OBJECTS,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes": "this adapter inflates nothing: a compressed "
                    "response is unwrapped by the host under its own bounds before it is handed "
                    "over",
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, and every pass is one walk of the document; a synthetic 3,000-item "
                    "document translates in seconds "
                    "(tests/test_cdm_frost_observations_adapter.py perf "
                    "test), and the conformance suite's parser worker kills a decode that "
                    "overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "No Frost document states a maximum response size. The largest "
                            "batch response observed outside this repository (about 2,900 data "
                            "items for about 20 stations over one day) is about 3.5 MB; 16 MiB "
                            "(16 777 216 octets, `MAX_INPUT_BYTES`, "
                            "`adapters/frost_observations.py`) leaves four times that headroom. "
                            + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time, so the octets are "
                            "measured and refused before this module decodes them"
                        ),
                        test="tests/test_cdm_input_bounds.py::"
                        "test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "A Frost response nests six containers (response, data, item, "
                            "observations, observation, level). 64 (`MAX_DEPTH`) is the "
                            "harness loader's own bound and the figure the JSON-reading "
                            "adapters of synapse_cdm declare. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` on the JSON text or the dict before "
                            "this class's `to_cdm` runs"
                        ),
                        test="tests/test_cdm_parser_safety.py::"
                        "test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "One Event per data item and time class plus one Entity per "
                            "station. A batch observed outside this repository is about 2,900 "
                            "items for about 20 stations; 50 000 objects (`MAX_OBJECTS`) is "
                            "about seventeen times that. " + _CAP
                        ),
                        enforced_at=(
                            "`FrostObservationsAdapter.to_cdm` counts the Events and the "
                            "distinct stations after classifying every observation and before "
                            "any object is built, and refuses `too-many-objects`"
                        ),
                        test=_TESTS + "test_a_document_past_the_object_bound_is_refused",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "every Event's residual holds the response header (every top-level key but "
                "data) and its own data item verbatim, so a key this module does not know, at the "
                "top, in an item or in an observation, is carried under the format's namespace"
            ),
        ),
        limitations=[
            Limitation(
                id="observations-response-only",
                summary="only the observations/v0.jsonld ObservationResponse is translated; "
                "sources and elements responses are read only through the caller's "
                "StationTable and ElementTable, and no other Frost endpoint is read",
            ),
            Limitation(
                id="station-position-from-the-caller",
                summary="the response states no position: a station's position comes only from "
                "the caller's StationTable keyed by the Frost station id (SN<n>); a station "
                "absent from it, or no table at all, gives an Entity with a null position and a "
                "position_basis saying so (the ndbc_stdmet/airnow_hourly precedent); masl and "
                "other SensorSystem fields are not carried",
            ),
            Limitation(
                id="sensor-suffix-not-an-entity",
                summary="the parallel sensor number (the ':N' of sourceId) does not make an "
                "Entity of its own: the station is the identity, and the full sourceId is "
                "carried verbatim on each Event (contract station_id and source identifier) and "
                "listed on the station Entity",
            ),
            Limitation(
                id="observation-time-cases",
                summary="instant Events for sub-daily observations and for any referenceTime "
                "not at midnight; a separate Case 2.2 daily Event for P1D observations at "
                "midnight (period by timeOffset, observed_at its end); an observation at "
                "midnight with no timeResolution, one longer than P1D (monthly, seasonal, "
                "annual) or a P1D without a usable timeOffset gets no reading and is listed on "
                "the station Entity as unresolved; an instantaneous P1D value stored at exactly "
                "00:00 would be read as diurnal, which the response cannot distinguish",
            ),
            Limitation(
                id="accumulation-window-not-resolved",
                summary="the window a sub-daily elementId's calculation method names "
                "(sum(... PT1H)) is carried verbatim in the reading's name and not turned into "
                "an interval: validity.effective is the referenceTime instant, because the "
                "concepts page does not state where a sub-daily window lies relative to "
                "referenceTime",
            ),
            Limitation(
                id="unit-from-the-caller",
                summary="an observation without a unit takes the unit the caller's ElementTable "
                "names for its exact elementId, recorded as a transformation with the table's "
                "name; with no such row the reading is an Absence (unit_unknown) and the value "
                "stays only in the residual",
            ),
            Limitation(
                id="series-in-the-reading-namespace",
                summary="timeOffset, timeResolution and timeSeriesId have no field in "
                "point-observation/1; they are stated verbatim in each reading's namespace "
                "(and in the residual), which is also what keeps two series of one element "
                "apart",
            ),
            Limitation(
                id="ledger-binds-items-to-any-event",
                summary="because one item can make several Events (or none), the lossless "
                "ledger binds each item's leaves to the data_item residual of ANY Event, not to "
                "one object index; an item with no resolvable observation is carried in the "
                "station Entity's residual (unresolved_items), which the ledger does not bind",
            ),
            Limitation(
                id="quality-flags-uninterpreted",
                summary="qualityCode, performanceCategory and exposureCategory are carried "
                "verbatim as typed quality flags and never interpreted into a confidence or a "
                "pass/fail; Event.quality is not set",
            ),
            Limitation(
                id="data-licence-as-stated",
                summary="the data licence is the response's own license statement (observed: "
                "CC BY 3.0 NO), carried verbatim; MET Norway's terms page names NLOD 2.0 and "
                "CC BY 4.0, and reconciling the two is the consumer's, not this module's",
            ),
            Limitation(
                id="missing-value-refused",
                summary="an observation without a numeric value is refused (bad-value): Frost "
                "publishes no sentinel for it, so there is no documented absence to translate",
            ),
            Limitation(
                id="synthetic-fixtures-only",
                summary="every fixture is synthetic (stations in the SN0000x block, positions "
                "inside CONTRIBUTING.md's Baltic rectangle, invented values) written from the "
                "documented response shape, which is what the gates ran against; no recorded "
                "Frost response is part of the evidence",
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

    #: The ledger. One item can make an instant Event, daily Events, both, or (if nothing in it
    #: resolves) none, so object index and item index no longer coincide and `#[*]` cannot bind
    #: them. Each item is carried whole in the residual of every Event made from it, so its leaves
    #: are bound to that residual on an Event (`event:`), and its sourceId to an Event's contract
    #: `station_id`. More specific keys come first: the ledger takes the first pattern that matches.
    MAPPINGS = {
        "data[*].sourceId": (
            Mapping(to="event:residual.data.data_item.sourceId", kind="residual"),
            Mapping(to="event:payload.observation.station_id"),
        ),
        "data[*]": Mapping(to="event:residual.data.data_item", kind="residual"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        station_table: StationTable | None = None,
        element_table: ElementTable | None = None,
        source_hash: SourceHash | dict | None = None,
    ) -> None:
        """`station_table` supplies station positions, keyed by the Frost station id (`SN<n>`,
        no sensor suffix); `element_table` supplies element units, keyed by exact `elementId`,
        used only for an observation that states no unit. Both are constructor arguments, so
        both are in the determinism tuple; `None` means no position / no unit is supplied, and
        the output says so. `source_hash` is the SHA-256 of the input file as the CALLER read
        it (the `ndbc_stdmet` / `cog` pattern); it is stamped on every object's
        `source.source_hash` and never computed here. A live deployment passes
        `synthetic=False`."""
        super().__init__(clock, synthetic=synthetic)
        if station_table is not None and not isinstance(station_table, StationTable):
            raise ValueError("station_table is a StationTable")
        if element_table is not None and not isinstance(element_table, ElementTable):
            raise ValueError("element_table is an ElementTable")
        self._station_table = station_table
        if source_hash is not None:
            source_hash = SourceHash.model_validate(source_hash)
            if source_hash.algorithm != "sha256" or not re.fullmatch(
                "[0-9a-f]{64}", source_hash.value
            ):
                raise ValueError("source_hash is a sha256 digest of 64 lower-case hex digits")
        self._element_table = element_table
        self._source_hash = source_hash

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        """The fixtures' context: the synthetic stations SN00001 to SN00003 (SN00009 left out
        on purpose) and the synthetic element table naming wind_speed, wind_from_direction and
        air_temperature units (`synthetic_element_x` left out on purpose). It is the context of
        those fixtures only (`Adapter.fixture_instance`)."""
        return cls(
            clock=clock,
            synthetic=synthetic,
            station_table=FIXTURE_STATIONS,
            element_table=FIXTURE_ELEMENTS,
        )

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One response -> [Events in data order (per item: the instant Event, then daily
        Events), then one Entity per station]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            document = parse_document(bytes(raw))
        elif isinstance(raw, dict):
            document = raw
        else:
            raise FrostRefused(
                "unsupported-input",
                "a response is handed over as its octets or as its parsed dict; text and other "
                "types are not taken",
            )
        if not isinstance(document, dict):
            raise FrostRefused("not-an-observation-response", "the document is not a JSON object")
        _check_json_shape(document)
        header = self._header(document)
        items = [self._item(item, index) for index, item in enumerate(document["data"])]
        return self._objects(header, items)

    # -- the header ------------------------------------------------------------------------------

    @staticmethod
    def _header(document: dict) -> dict:
        if document.get("@type") != RESPONSE_TYPE:
            raise FrostRefused("not-an-observation-response", "@type is not ObservationResponse")
        if document.get("apiVersion") != API_VERSION:
            # The shape this module reads is v0's; a later API version is a new reading.
            raise FrostRefused("unsupported-api-version", "apiVersion is not v0")
        if DATA_ITEM_KEY in document:
            raise FrostRefused(
                "reserved-key",
                f"the response states a top-level {DATA_ITEM_KEY} key, which the "
                "residual reserves for the data item",
            )
        created = document.get("createdAt")
        if created is not None and (type(created) is not str or not created.strip()):
            raise FrostRefused("bad-created-at", "createdAt is not a non-blank string")
        data = document.get("data")
        if not isinstance(data, list):
            raise FrostRefused("not-an-observation-response", "data is not a list")
        if not data:
            # An empty list would read as "this response legitimately carries nothing"; Frost
            # answers a query that matches nothing with an error, not an empty data list.
            raise FrostRefused("no-data-item", "data holds no item")
        return {key: value for key, value in document.items() if key != "data"}

    # -- one data item ---------------------------------------------------------------------------

    def _item(self, item: Any, index: int) -> dict:
        where = f"data[{index}]"
        if not isinstance(item, dict):
            raise FrostRefused("bad-item", f"{where} is not an object")
        source_id = item.get("sourceId")
        match = _SOURCE_ID.fullmatch(source_id) if type(source_id) is str else None
        if match is None:
            raise FrostRefused(
                "bad-source-id", f"{where}.sourceId is not SN<number> or SN<number>:<sensor>"
            )
        reference = self._reference_time(item.get("referenceTime"), f"{where}.referenceTime")
        observations = item.get("observations")
        if not isinstance(observations, list):
            raise FrostRefused("bad-item", f"{where}.observations is not a list")
        if not observations:
            raise FrostRefused("no-observation", f"{where} states no observation")
        midnight = (reference.hour, reference.minute, reference.second, reference.microsecond) == (
            0,
            0,
            0,
            0,
        )
        # Groups keyed by time class: ("instant",) or ("daily", timeOffset text).
        groups: dict[tuple, list[dict]] = {}
        unresolved: list[dict] = []
        series = set()
        for j, observation in enumerate(observations):
            parsed = self._observation(observation, f"{where}.observations[{j}]")
            key = (parsed["reading"].name, parsed["reading"].namespace, parsed["reading"].level)
            if key in series:
                raise FrostRefused(
                    "repeated-series",
                    f"{where}.observations[{j}] repeats the element, series and level of an "
                    "earlier observation of the item",
                )
            series.add(key)
            parsed["observation_index"] = j
            time_class, reason = self._time_class(midnight, parsed)
            if time_class is None:
                unresolved.append(
                    {
                        "data_index": index,
                        "observation_index": j,
                        "sourceId": source_id,
                        "referenceTime": item["referenceTime"],
                        "elementId": parsed["reading"].name,
                        "reason": reason,
                    }
                )
            else:
                groups.setdefault(time_class, []).append(parsed)
        return {
            "index": index,
            "source_id": source_id,
            "station": match.group(1),
            "reference": reference,
            "midnight": midnight,
            "groups": groups,
            "unresolved": unresolved,
            "item": item,
        }

    @staticmethod
    def _time_class(midnight: bool, parsed: dict) -> tuple[tuple | None, str | None]:
        """The observation's time class, or None and the reason it has none (see TIME)."""
        if not midnight:
            return ("instant",), None
        resolution = parsed["resolution"]
        if resolution is None:
            return None, (
                "midnight referenceTime and no timeResolution: Frost's Case 1 and Case 2 differ "
                "and the observation does not say which applies"
            )
        if resolution < _DAY_SECONDS:
            return ("instant",), None
        if parsed["resolution_text"] != _DAILY:
            return None, (
                "midnight referenceTime and a timeResolution of one day or longer other than "
                "P1D: the period depends on the element (concepts2.html Cases 2.1 to 2.5) and "
                "is not resolved here"
            )
        offset = parsed["offset"]
        if offset is None or offset >= _DAY_SECONDS:
            return None, (
                "P1D at a midnight referenceTime without a timeOffset shorter than one day: "
                "Case 2.2 places the period by timeOffset, and none usable is stated"
            )
        return ("daily", parsed["offset_text"]), None

    @staticmethod
    def _reference_time(text: Any, where: str) -> _dt.datetime:
        if type(text) is not str or _REFERENCE_TIME.fullmatch(text) is None:
            raise FrostRefused(
                "bad-reference-time", f"{where} is not an RFC 3339 UTC instant ending in Z"
            )
        try:
            return times.parse(text)
        except ValueError:
            raise FrostRefused("bad-reference-time", f"{where} names no real instant") from None

    @staticmethod
    def _text(value: Any, code: str, where: str) -> str:
        if type(value) is not str or not value.strip():
            raise FrostRefused(code, f"{where} is not a non-blank string")
        return value

    def _observation(self, observation: Any, where: str) -> dict:
        """The reading (without its Event-relative flag index), its flags as (name, value)
        pairs, its unit's provenance, and its time series as stated."""
        if not isinstance(observation, dict):
            raise FrostRefused("bad-observation", f"{where} is not an object")
        element = self._text(observation.get("elementId"), "bad-element-id", f"{where}.elementId")
        value = observation.get("value")
        if not json_number(value):
            raise FrostRefused("bad-value", f"{where}.value is not a number")
        level = self._level(observation, where)
        stated = {}
        series_parts = []
        for key in SERIES_KEYS:
            if key not in observation:
                continue
            text = observation[key]
            if key == "timeSeriesId":
                if isinstance(text, bool) or not isinstance(text, int):
                    raise FrostRefused("bad-observation", f"{where}.timeSeriesId is not an integer")
                series_parts.append(f"{key}={text}")
                continue
            text = self._text(text, "bad-duration", f"{where}.{key}")
            seconds = _duration_seconds(text)
            if seconds is None:
                raise FrostRefused("bad-duration", f"{where}.{key} is not an ISO 8601 duration")
            if key == "timeResolution" and seconds == 0:
                raise FrostRefused("bad-duration", f"{where}.timeResolution is zero")
            stated[key] = (text, seconds)
            series_parts.append(f"{key}={text}")
        namespace = ELEMENT_NAMESPACE
        if series_parts:
            namespace += "; time series " + ", ".join(series_parts)
        flags = []
        for key in FLAG_NAMESPACES:
            if key not in observation:
                continue
            flag = observation[key]
            if isinstance(flag, bool) or not (
                (isinstance(flag, int) and json_number(flag))
                or (type(flag) is str and flag.strip())
            ):
                raise FrostRefused(
                    "bad-quality-flag",
                    f"{where}.{key} is neither an integer nor a non-blank string",
                )
            flags.append((key, flag))
        unit_note = None
        if "unit" in observation:
            unit = self._text(observation["unit"], "bad-unit", f"{where}.unit")
            reading = Reading(
                name=element,
                namespace=namespace,
                measurement=Measurement(value=value, unit=unit, unit_namespace=UNIT_NAMESPACE),
                level=level,
            )
        else:
            table = self._element_table
            unit = table.unit_of(element) if table is not None else None
            if unit is not None:
                reading = Reading(
                    name=element,
                    namespace=namespace,
                    measurement=Measurement(
                        value=value,
                        unit=unit,
                        unit_namespace=(
                            f"MET Norway Frost element table {table.name} supplied by the "
                            "caller (/elements/v0.jsonld unit of this elementId)"
                        ),
                    ),
                    level=level,
                )
                unit_note = (
                    f"unit not stated in the observation; taken from the caller's Frost element "
                    f"table {table.name} ({table.basis})"
                )
            else:
                reading = Reading(
                    name=element,
                    namespace=namespace,
                    absence=Absence(cause="unit_unknown", mechanism=UNIT_UNKNOWN),
                    level=level,
                )
        resolution = stated.get("timeResolution")
        offset = stated.get("timeOffset")
        return {
            "reading": reading,
            "flags": flags,
            "unit_note": unit_note,
            "resolution": None if resolution is None else resolution[1],
            "resolution_text": None if resolution is None else resolution[0],
            "offset": None if offset is None else offset[1],
            "offset_text": None if offset is None else offset[0],
        }

    def _level(self, observation: dict, where: str) -> VerticalLevel | None:
        if "level" not in observation:
            return None
        level = observation["level"]
        if not isinstance(level, dict):
            raise FrostRefused("bad-level", f"{where}.level is not an object")
        level_type = self._text(level.get("levelType"), "bad-level", f"{where}.level.levelType")
        value, unit = level.get("value"), level.get("unit")
        if (value is None) != (unit is None):
            raise FrostRefused(
                "bad-level", f"{where}.level states one of value and unit; a value needs its unit"
            )
        if value is not None:
            if not json_number(value):
                raise FrostRefused("bad-level", f"{where}.level.value is not a number")
            unit = self._text(unit, "bad-level", f"{where}.level.unit")
        return VerticalLevel(type=level_type, value=value, unit=unit, namespace=LEVEL_NAMESPACE)

    # -- the objects -----------------------------------------------------------------------------

    def _objects(self, header: dict, items: list[dict]) -> list[CDMBase]:
        seen: dict[tuple[str, str], int] = {}
        stations: dict[str, dict] = {}
        event_count = 0
        for item in items:
            key = (item["source_id"], times.render(item["reference"]))
            if key in seen:
                raise FrostRefused(
                    "repeated-item",
                    f"data[{item['index']}] states the sourceId and referenceTime of "
                    f"data[{seen[key]}]",
                )
            seen[key] = item["index"]
            station = stations.setdefault(
                item["station"],
                {"earliest": item["reference"], "source_ids": [], "unresolved": [], "items": []},
            )
            station["earliest"] = min(station["earliest"], item["reference"])
            if item["source_id"] not in station["source_ids"]:
                station["source_ids"].append(item["source_id"])
            station["unresolved"].extend(item["unresolved"])
            if not item["groups"]:
                # Nothing in the item resolves to a time, so no Event carries it: the station
                # Entity's residual does, verbatim, so the item is set aside, never dropped.
                station["items"].append({"data_index": item["index"], "item": item["item"]})
            event_count += len(item["groups"])
        if event_count + len(stations) > MAX_OBJECTS:
            raise FrostRefused(
                "too-many-objects",
                f"the document would make {event_count + len(stations)} objects and the bound "
                f"is {MAX_OBJECTS}",
            )

        # Every object of the call (Events and Entities) is stamped from this one base, so the
        # caller's digest lands on all of them or, when not given, on none.
        stamp_base = self.source_ref().model_copy(update={"source_hash": self._source_hash})
        received = self.now()
        created = header.get("createdAt")
        product_version = (
            ProductVersion(production_time_verbatim=created) if created is not None else None
        )

        entities = {}
        for station_id, station in stations.items():
            entity = site_entity(
                source=stamp_base.model_copy(
                    update={"observed_at": station["earliest"], "transformations": [T_STATION]}
                ),
                system=SYSTEM,
                station_id=station_id,
                site_class="weather_station",
                valid_from=station["earliest"],
                station_table=self._station_table,
            )
            attributes = {
                **entity.attributes,
                "valid_from_basis": "the earliest referenceTime the response states for the "
                "station",
                "station_id_basis": (
                    "the Frost station id, the part of sourceId before ':' "
                    f"({CONCEPTS_URL}: SN<station identity number>:<parallel sensor "
                    "number>); parallel sensors of one station are this one Entity"
                ),
            }
            if station["unresolved"]:
                attributes["unresolved_observations"] = station["unresolved"]
            residual = {"sourceIds": list(station["source_ids"])}
            if station["items"]:
                residual["unresolved_items"] = station["items"]
                # The header too: when no Event carries an item, nothing else may carry the
                # licence and the response's own statements (a document of only such items
                # would otherwise lose them).
                residual["response_header"] = header
            entities[station_id] = entity.model_copy(
                update={
                    "attributes": attributes,
                    "residual": Residual(namespace=FORMAT_NAME, data=residual),
                }
            )

        events = []
        for item in items:
            entity = entities[item["station"]]
            for time_class, members in item["groups"].items():
                events.append(
                    self._event(
                        item,
                        time_class,
                        members,
                        entity,
                        stamp_base,
                        received,
                        product_version,
                        header,
                    )
                )
        return [*events, *entities.values()]

    def _event(
        self, item, time_class, members, entity, stamp_base, received, product_version, header
    ) -> CDMBase:
        reference = item["reference"]
        rendered = times.render(reference)
        if time_class[0] == "instant":
            start = end = reference
            basis = T_SUB_DAILY if item["midnight"] else T_NOT_MIDNIGHT
            external = f"{item['source_id']}/{rendered}"
        else:
            offset_text = time_class[1]
            offset = _dt.timedelta(seconds=members[0]["offset"])
            if offset:
                end = reference + offset
                start = end - _dt.timedelta(days=1)
            else:
                start, end = reference, reference + _dt.timedelta(days=1)
            basis = T_DAILY
            external = f"{item['source_id']}/{rendered}/{_DAILY}/{offset_text}"
        readings, flags, notes = [], [], []
        for position, member in enumerate(members):
            readings.append(member["reading"])
            for name, value in member["flags"]:
                flags.append(
                    QualityFlag(
                        name=name,
                        value=value,
                        namespace=FLAG_NAMESPACES[name],
                        applies_to=f"readings[{position}]",
                    )
                )
            if member["unit_note"]:
                notes.append(
                    f"readings[{position}] (observations[{member['observation_index']}]): "
                    + member["unit_note"]
                )
        contract = PointObservation(
            contract="point-observation/1",
            product_class="observation",
            product_version=product_version,
            time=TimeInputs(source_time_system=TIME_SYSTEM),
            locator=TableLocator(kind="table", row=item["index"], header_lines=0),
            quality_flags=flags,
            quality_flags_basis=None if flags else NO_FLAGS_BASIS,
            station_id=item["source_id"],
            station_namespace=STATION_NAMESPACE,
            readings=readings,
        )
        position = entity.position
        return observation_event(
            source=stamp_base.model_copy(
                update={
                    "observed_at": reference,
                    "record_index": item["index"],
                    "transformations": [basis, T_STATION, *notes],
                }
            ),
            source_ids=[SourceId(system=SYSTEM, external_id=external)],
            observation=contract,
            observed_at=end,
            received_at=received,
            validity=TemporalValidity(effective=Period(start=start, end=end)),
            related_entities=[entity.entity_id],
            geometry=None if position is None else Point(coordinates=[position.lon, position.lat]),
            residual=Residual(namespace=FORMAT_NAME, data={**header, DATA_ITEM_KEY: item["item"]}),
        )


def _duration_seconds(text: str) -> float | None:
    """The length of an ISO 8601 duration, for ORDERING it against one day only, or `None` if
    the text is not one. A year, month or week is counted as at least one day (a year as 365
    days, a month as 28): the only questions asked of the figure are "shorter than one day?" and
    "zero?", and any non-zero Y, M, W or D answers both "no" whatever its exact length. A daily
    period is placed only for the literal `P1D`, never from this figure."""
    match = _DURATION.fullmatch(text)
    if match is None or text in ("P", "PT") or text.endswith("T"):
        return None
    years, months, weeks, days, hours, minutes, seconds = match.groups()
    total = 0.0
    total += int(years or 0) * 365 * _DAY_SECONDS
    total += int(months or 0) * 28 * _DAY_SECONDS
    total += int(weeks or 0) * 7 * _DAY_SECONDS
    total += int(days or 0) * _DAY_SECONDS
    total += int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)
    return total
