"""`coops_csv`, #27 in the ordinal table: one NOAA CO-OPS data response -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One response of the CO-OPS data API (`api.tidesandcurrents.noaa.gov/api/prod/datagetter`), in
either of the two forms it answers in (DECISIONS L-11): the CSV form — one header line, then one
row per sample — or the JSON form, `{"metadata": {id, name, lat, lon}, "data": [{t, v, s, f, q}]}`
with every value a string. `to_cdm` takes the response's octets (a CSV header or a JSON object),
the parsed JSON document, or the CSV form's parsed twin (`<name>.parsed.json`: `form`, the header
line as written and every row's fields).

The format is read from the API's own pages (the parameter list and the response field
definitions), cited by URL and not carried: they are HTML, and no copy of them is held
(`fixtures/coops_csv/spec/coops_csv_pin.json`).

WHAT THE RESPONSE DOES NOT SAY, AND WHO SAYS IT INSTEAD
-------------------------------------------------------
A response states neither the datum its water levels are measured from, nor its units, nor the
time zone its stamps are in, and the CSV form does not state its station either: all are
parameters of the REQUEST, and none is echoed (research-station-text F05). So the request is a
REQUIRED constructor argument, `CoopsRequest{station, product, datum, units, time_zone,
interval}` (design-judge DJ-17; gap-host-manifest HM-01), and every value it gives is in the
determinism tuple:

- `time_zone` decides what a stamp means. `gmt` is UTC. `lst` is local standard time, and is read
  with the offset the caller declares beside it (`lst_offset`), a declared transformation, so the
  Battery-style `-05:00` turns `2026-04-28 00:00` into `05:00Z`. `lst_ldt`, local time with
  daylight saving, is refused by name: the switch dates are a time-zone database this package does
  not read (DECISIONS L-11). A request with no zone is refused: `times.parse` would read the naive
  stamp as UTC, a five-hour error that raises nothing.
- `datum` is carried as `{name, namespace}` beside the water level it refers to (DJ-07), never as
  a `VerticalReference`: MLLW is not a height above the ellipsoid.
- `units` is carried verbatim as the unit of every value it governs, `metric` or `english` under
  the namespace of the request parameter (DJ-05): the response states no unit string, and this
  module does not turn one into another.

WHAT ONE RESPONSE BECOMES
-------------------------
One `ENVIRONMENTAL_OBSERVATION` Event per sample row, in the response's order, each carrying the
`point-observation/1` contract; then the station's `Entity` (SENSOR, `site_entity`), last. A
sample's stamp is `observed_at` and both ends of `validity.effective`. The flags the API defines
for the product — water level's O (a count of samples outside three sigma) or I, F, R and L or T,
and the p/v quality level; air pressure's X, N and R; wind's X and R — are typed quality flags,
verbatim (F06). The CSV header is read POSITIONALLY and compared whole with the product's own:
`csv.DictReader` would collapse wind's two `Direction` columns into one, and air pressure's header
ends in a space the comparison keeps. The JSON form's position (`metadata.lat`/`lon`, strings) is
the station's stated position; the CSV form's comes only from a caller's `StationTable`. A
sample's identity is the station, the product, the datum, the units, the interval and the UTC
instant: each request parameter that changes the value is in it, so one sample asked for against
two datums or in two unit systems is two Events, and asked for in two zones is one. A number or a
flag no binary double holds is refused by its own code, never handed to the contract.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime as _dt
import json
import re
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
    Datum,
    Measurement,
    PointObservation,
    QualityFlag,
    Reading,
    StationTable,
    TableLocator,
    TimeInputs,
    TimeSystem,
    decimal_float,
    decimal_integer,
    observation_event,
    site_entity,
    text_lines,
    twin_text,
)

#: `source.system` on every object and the system of every identifier.
SYSTEM = "CO-OPS"
FORMAT_NAME = "NOAA CO-OPS data API response (datagetter)"
FORMAT_VERSION = "api.tidesandcurrents.noaa.gov/api/prod, read 2026-10-14"
API = "the CO-OPS data API page (api.tidesandcurrents.noaa.gov/api/prod/)"
RESPONSE_HELP = "the CO-OPS response field definitions (api/prod/responseHelp.html)"

#: DECISIONS U-07: station text, one file of at most 8 MiB.
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 64

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_coops_csv_adapter.py::"

#: The CSV header of each product this module reads, whole and as the API writes it
#: (research-station-text F04, F05, F06): air pressure's ends in a space, and wind names
#: `Direction` twice, degrees then the compass point.
HEADERS: MappingType[str, str] = {
    "water_level": "Date Time, Water Level, Sigma, O or I (for verified), F, R, L, Quality",
    "air_pressure": "Date Time, Pressure, X, N, R ",
    "wind": "Date Time, Speed, Direction, Direction, Gust, X, R",
}

#: The water-level flags by quality level, in the order the API writes them (F06): a
#: preliminary sample's O (a count), F, R, L; a verified sample's I, F, R, T.
WATER_LEVEL_FLAGS = {"p": ("O", "F", "R", "L"), "v": ("I", "F", "R", "T")}

#: The datum names the API lists (research-station-text F05).
DATUMS = ("MLLW", "MLW", "MSL", "MHW", "MHHW", "NAVD", "STND", "CRD", "IGLD", "LWD", "MTL")
UNITS = ("metric", "english")
INTERVALS = ("6", "h")
TIME_ZONES = ("gmt", "lst")

_STATION = re.compile(r"[0-9]{7}")
_STAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2})")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_FLAG = re.compile(r"[0-9]+")
_OFFSET = re.compile(r"([+-])([0-9]{2}):([0-9]{2})")
_JSON_FLAGS = re.compile(r"[0-9]+,[0-9]+,[0-9]+,[0-9]+")

UNITS_NAMESPACE = "CO-OPS datagetter request parameter units"
DATUM_NAMESPACE = "CO-OPS datagetter request parameter datum"
DIRECTION_NAMESPACE = f"{RESPONSE_HELP}: wind Direction in degrees (research-station-text F06)"
FLAG_NAMESPACE = f"{RESPONSE_HELP}: the product's quality flags"
QUALITY_NAMESPACE = f"{RESPONSE_HELP}: p preliminary, v verified"

T_GMT = "the request's time_zone is gmt, so each stamp is read as UTC"
T_LST = (
    "the request's time_zone is lst, local standard time: each stamp is read as UTC by "
    "subtracting the caller's declared lst_offset"
)
T_NUMBER = "each value's decimal text is read as a binary floating-point number"
T_FLAGS = "each flag's decimal text is read as an integer"

LST_LDT_REFUSAL = (
    "time_zone lst_ldt is refused by name: local time with daylight saving needs the switch "
    "dates of a time-zone database, which this package does not read (DECISIONS L-11)"
)
NO_ZONE_REFUSAL = (
    "the request states no time_zone: a CO-OPS stamp carries no zone, and read without one it "
    "would be taken as UTC"
)


class CoopsRefused(ValueError):
    """A response this module will not translate. `code` names the rule; the text names the
    line, row or field, never a value from the payload."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> CoopsRefused:
    refusal = CoopsRefused(code, "")
    refusal.args = (message,)
    return refusal


# -- the request ---------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CoopsRequest:
    """The parameters a CO-OPS response was requested with, which the response does not echo.

    `station`, `product`, `units` and `time_zone` are required; `datum` is required for
    `water_level` ("Datum is mandatory for all water level products") and refused for the
    others, which state no height; `interval` is the API's own (`6` or `h`) or absent (the API's
    default). `lst_offset` is the station's standard-time offset from UTC, `+HH:MM` or `-HH:MM`,
    required exactly when `time_zone` is `lst`.
    """

    station: str
    product: str
    units: str
    time_zone: str | None
    datum: str | None = None
    interval: str | None = None
    lst_offset: str | None = None

    def __post_init__(self) -> None:
        if type(self.station) is not str or _STATION.fullmatch(self.station) is None:
            raise ValueError("station is the seven-digit CO-OPS station identifier")
        if self.product not in HEADERS:
            raise ValueError("product is water_level, air_pressure or wind")
        if self.units not in UNITS:
            raise ValueError("units is metric or english")
        if self.time_zone is None:
            raise ValueError(NO_ZONE_REFUSAL)
        if self.time_zone == "lst_ldt":
            raise ValueError(LST_LDT_REFUSAL)
        if self.time_zone not in TIME_ZONES:
            raise ValueError("time_zone is gmt or lst")
        if self.product == "water_level":
            if self.datum not in DATUMS:
                raise ValueError("a water_level request states one of the API's datum names")
        elif self.datum is not None:
            raise ValueError("only a water_level request states a datum")
        if self.interval is not None and self.interval not in INTERVALS:
            raise ValueError("interval is 6 or h, or absent for the API's default")
        if self.time_zone == "lst":
            if type(self.lst_offset) is not str or self.offset is None:
                raise ValueError(
                    "an lst request states its standard-time offset as lst_offset, +HH:MM or "
                    "-HH:MM within 14 hours"
                )
        elif self.lst_offset is not None:
            raise ValueError("lst_offset is stated with time_zone lst, and only then")

    @property
    def offset(self) -> _dt.timedelta | None:
        match = _OFFSET.fullmatch(self.lst_offset or "")
        if match is None:
            return None
        sign, hours, minutes = match.groups()
        if int(minutes) > 59 or int(hours) * 60 + int(minutes) > 14 * 60:
            return None
        delta = _dt.timedelta(hours=int(hours), minutes=int(minutes))
        return -delta if sign == "-" else delta

    @classmethod
    def from_pairs(cls, pairs: Any) -> CoopsRequest:
        """A request from `KEY=VALUE` pairs (the host's `--request`): the keys are the field
        names, and a key that is not one is refused."""
        values = dict(pairs)
        stray = sorted(set(values) - {f.name for f in dataclasses.fields(cls)})
        if stray:
            raise ValueError("a request key is not a CoopsRequest field")
        return cls(
            station=values.get("station"),
            product=values.get("product"),
            units=values.get("units"),
            time_zone=values.get("time_zone"),
            datum=values.get("datum"),
            interval=values.get("interval"),
            lst_offset=values.get("lst_offset"),
        )

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


FIXTURE_REQUEST = CoopsRequest(
    station="0000001",
    product="water_level",
    datum="MLLW",
    units="metric",
    time_zone="gmt",
    interval="6",
)


# -- octets to a document ------------------------------------------------------------------------


def _no_repeat(pairs: list) -> dict:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise CoopsRefused("repeated-key", "a JSON object names one key twice")
    return dict(pairs)


def _no_constant(name: str) -> Any:
    raise CoopsRefused("not-json", "the JSON text holds NaN or an infinity")


def _json_integer(text: str) -> int:
    """`json.loads`'s integer hook: an integer no double holds is refused here, by its digits,
    before `int()` would raise its own `ValueError` past the interpreter's digit limit."""
    value = decimal_integer(text)
    if value is None:
        raise CoopsRefused(
            "number-out-of-range", "the JSON text holds an integer no binary double holds"
        )
    return value


def parse_response(octets: bytes) -> dict:
    """The response's octets as the dict `to_cdm` reads: the JSON document as parsed, or the CSV
    form's twin."""
    if octets.lstrip(b" \t\r\n").startswith(b"{"):
        try:
            text = octets.decode("utf-8")
        except UnicodeDecodeError:
            raise CoopsRefused("not-utf8", "the response is not UTF-8 text") from None
        try:
            document = json.loads(
                text,
                object_pairs_hook=_no_repeat,
                parse_constant=_no_constant,
                parse_int=_json_integer,
            )
        except json.JSONDecodeError:
            raise CoopsRefused("not-json", "the response opens with { and is not JSON") from None
        if not isinstance(document, dict):
            raise CoopsRefused("not-json", "the JSON response is not an object")
        return document
    lines, _ = text_lines(octets, CoopsRefused)
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        try:
            rows.append(next(csv.reader([line], strict=True)))
        except csv.Error:
            raise CoopsRefused("bad-csv-row", f"line {number} is not one CSV record") from None
    return {"form": "csv", "header": lines[0], "rows": rows}


def _text(value: Any, where: str) -> str:
    if not twin_text(value):
        raise CoopsRefused("not-text", f"{where} is not text a response could hold")
    return value


def _check_csv_twin(document: dict) -> dict:
    if set(document) != {"form", "header", "rows"} or document["form"] != "csv":
        raise CoopsRefused("not-a-twin", "a CSV twin holds exactly form 'csv', header and rows")
    _text(document["header"], "header")
    rows = document["rows"]
    if not isinstance(rows, list):
        raise CoopsRefused("not-a-twin", "rows is not a list")
    for index, row in enumerate(rows):
        if not isinstance(row, list):
            raise CoopsRefused("not-a-twin", f"rows[{index}] is not a list of fields")
        for position, field in enumerate(row):
            _text(field, f"rows[{index}][{position}]")
    return document


def _check_json(document: dict) -> dict:
    if set(document) != {"metadata", "data"}:
        raise CoopsRefused(
            "not-a-response", "a JSON response holds exactly the keys metadata and data"
        )
    metadata = document["metadata"]
    if not isinstance(metadata, dict) or set(metadata) != {"id", "name", "lat", "lon"}:
        raise CoopsRefused(
            "not-a-response", "metadata holds exactly the keys id, name, lat and lon"
        )
    for key in ("id", "name", "lat", "lon"):
        _text(metadata[key], f"metadata.{key}")
    data = document["data"]
    if not isinstance(data, list):
        raise CoopsRefused("not-a-response", "data is not a list")
    for index, record in enumerate(data):
        if not isinstance(record, dict) or set(record) != {"t", "v", "s", "f", "q"}:
            raise CoopsRefused(
                "not-a-response", f"data[{index}] holds exactly the keys t, v, s, f and q"
            )
        for key in ("t", "v", "s", "f", "q"):
            _text(record[key], f"data[{index}].{key}")
    return document


# -- the declaration -----------------------------------------------------------------------------


def _residual(path: str, target: str) -> Mapping:
    return Mapping(to=f"{target}:residual.data.{path}", kind="residual")


class CoopsCsvAdapter(Adapter):
    """One CO-OPS response in; one Event per sample and the station's Entity out."""

    name = "coops_csv"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: `PUBLIC_GOVERNMENT`: NOS states the information on its servers public domain unless
    #: annotated otherwise, with attribution requested (research-station-text F11).
    metadata = AdapterMetadata(
        id="coops_csv",
        name="NOAA CO-OPS data API response (CSV and JSON) translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter coops_csv` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "every row or record a structured residual on its own Event) with no LOST leaf on "
            "any parsed form. L4 is NOT declared: this adapter is ingest-only, so the roundtrip "
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
                "NOAA CO-OPS datagetter response: the CSV form of water_level, air_pressure or "
                "wind, or the JSON form of water_level, one response per call under the "
                "caller's CoopsRequest; one ENVIRONMENTAL_OBSERVATION Event per sample carrying "
                "point-observation/1, and the station's Entity",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_objects": "not a bound of its own: one Event per sample and one "
                    "Entity, and a sample row is at least 26 octets (a 16-character stamp, a "
                    "value, the flags and the line end), so max_input_bytes bounds the count",
                    "max_decompressed_bytes": "this adapter inflates nothing: a compressed "
                    "response is unwrapped by synapse-decode --container gzip under the host's "
                    "own bounds before the adapter is handed it",
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, and every pass over the response is one walk of its lines or its "
                    "parsed records; the conformance suite's parser worker kills a decode that "
                    "overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The API bounds a request by its time range — 6-minute data one "
                            "month a request, hourly data one year (research-station-text F05, "
                            "the API page) — and states no size; a month of 6-minute samples is "
                            "7 440 rows and a year of hourly ones 8 784. DECISIONS U-07 rules "
                            "one station-text file at most 8 MiB (8 388 608 octets, "
                            "`MAX_INPUT_BYTES`, `adapters/coops_csv.py`), over a kilobyte a row "
                            "for the longer of the two. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused before "
                            "this module decodes a line or a JSON token"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "A JSON response nests three containers (the response, data, a "
                            "record) and the CSV twin three (the twin, rows, a row). 64 "
                            "(`MAX_DEPTH`, `adapters/coops_csv.py`) is the harness loader's own "
                            "bound and the figure the JSON-reading adapters of synapse_cdm "
                            "declare. " + _CAP
                        ),
                        enforced_at=(
                            "for a dict and for JSON octets, the base class: "
                            "`Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` before this class's `to_cdm` runs, so "
                            "JSON text past the bound never reaches `json.loads`"
                        ),
                        test="tests/test_cdm_parser_safety.py::test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the CSV header is compared whole with the product's own, and the JSON response, "
                "its metadata and each data record are closed key sets read off the API's "
                "response, so a column or a key this module does not know is refused rather than "
                "carried"
            ),
        ),
        limitations=[
            Limitation(
                id="request-from-the-caller",
                summary="a response echoes none of the request's datum, units, time zone or "
                "interval, and the CSV form not its station: they are the caller's required "
                "CoopsRequest, and a JSON response naming another station is refused",
            ),
            Limitation(
                id="lst-ldt-refused",
                summary="time_zone lst_ldt is refused by name (DECISIONS L-11): daylight-saving "
                "local time needs a time-zone database; gmt is read as UTC, and lst with the "
                "caller's declared standard-time offset",
            ),
            Limitation(
                id="products-read",
                summary="the CSV form of water_level, air_pressure and wind and the JSON form of "
                "water_level are read; every other product, and the JSON form of air_pressure "
                "and wind, whose record keys the design record does not hold, are refused",
            ),
            Limitation(
                id="units-verbatim",
                summary="the request's units (metric or english) is every value's unit, verbatim "
                "under the request parameter's namespace; no unit string is derived from it, "
                "and wind's degrees direction is the one value with a unit of its own",
            ),
            Limitation(
                id="blank-values-refused",
                summary="a blank field is refused blank-value: the design record does not hold "
                "how the API writes a missing sample, so this module neither reads a blank as "
                "a sentinel nor drops the reading",
            ),
            Limitation(
                id="direction-text-in-residual",
                summary="wind's second Direction column, the compass point, is text and not a "
                "measurement; it stays in each Event's residual row",
            ),
            Limitation(
                id="evidence-availability",
                summary="the evidence RECORD for this adapter is not IN the distribution: "
                "`evidence/` is untracked and unpackaged, CI generates the set on every "
                "run, and the release pipeline generates the records for every shipped "
                "adapter and attaches them to the GitHub Release of the version it "
                "publishes. `evidence.available` is true because every published "
                "distribution that carries this adapter has that Release, so its records "
                "are retrievable by a third party; it says nothing about what the wheel "
                "contains",
            ),
        ],
        limitations_empty_reason=None,
        residual=ResidualStance.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=True),
    )

    #: The ledger. Each Event's residual holds its own row (CSV) or record (JSON) as written, and
    #: the Events come first in row order with the station's Entity last, so row i is bound to
    #: object i; the value of every row is also held to the contract's first reading. The JSON
    #: form's metadata is the Entity's residual, its id the Entity's identifier and its lat and
    #: lon the Entity's position.
    MAPPINGS = {
        "rows[*][1]": (
            Mapping(to="#[*]:residual.data.row[1]", kind="residual"),
            Mapping(
                to="#[*]:payload.observation.readings[0].measurement.value",
                rule="numeric_text",
            ),
        ),
        "rows[*]": Mapping(to="#[*]:residual.data.row", kind="residual"),
        "data[*].v": (
            Mapping(to="#[*]:residual.data.record.v", kind="residual"),
            Mapping(
                to="#[*]:payload.observation.readings[0].measurement.value",
                rule="numeric_text",
            ),
        ),
        "data[*].s": (
            Mapping(to="#[*]:residual.data.record.s", kind="residual"),
            Mapping(
                to="#[*]:payload.observation.readings[1].measurement.value",
                rule="numeric_text",
            ),
        ),
        "data[*]": Mapping(to="#[*]:residual.data.record", kind="residual"),
        "metadata.id": (
            _residual("metadata.id", "entity"),
            Mapping(to="entity:source_ids[0].external_id"),
        ),
        "metadata.lat": (
            _residual("metadata.lat", "entity"),
            Mapping(to="entity:position.lat", rule="numeric_text"),
        ),
        "metadata.lon": (
            _residual("metadata.lon", "entity"),
            Mapping(to="entity:position.lon", rule="numeric_text"),
        ),
        "metadata": _residual("metadata", "entity"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        request: CoopsRequest,
        station_table: StationTable | None = None,
        source_hash: SourceHash | dict | None = None,
        frame_sha256: str | None = None,
    ) -> None:
        """`request` is what the response was requested with (required: the response does not
        say); `station_table` supplies the CSV form's position. `source_hash` is the SHA-256 of
        the file as the host read it and `frame_sha256` that of what it handed over when that is
        not the file. All are constructor arguments, so all are in the determinism tuple."""
        super().__init__(clock, synthetic=synthetic)
        if not isinstance(request, CoopsRequest):
            raise ValueError("request is a CoopsRequest")
        if station_table is not None and not isinstance(station_table, StationTable):
            raise ValueError("station_table is a StationTable")
        if source_hash is not None:
            source_hash = SourceHash.model_validate(source_hash)
            if source_hash.algorithm != "sha256" or not re.fullmatch(
                "[0-9a-f]{64}", source_hash.value
            ):
                raise ValueError("source_hash is a sha256 digest of 64 lower-case hex digits")
        if frame_sha256 is not None and (
            type(frame_sha256) is not str or not re.fullmatch("[0-9a-f]{64}", frame_sha256)
        ):
            raise ValueError("frame_sha256 is 64 lower-case hexadecimal digits")
        self._request = request
        self._station_table = station_table
        self._source_hash = source_hash
        self._frame_sha256 = frame_sha256

    @property
    def request(self) -> CoopsRequest:
        return self._request

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        """The packaged fixtures' context: station `0000001`'s water level against MLLW, metric,
        in GMT at the default 6-minute interval. It is the context of those fixtures only
        (`Adapter.fixture_instance`)."""
        return cls(clock=clock, synthetic=synthetic, request=FIXTURE_REQUEST)

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One response -> [one Event per sample, in order, then the station's Entity]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            document = parse_response(bytes(raw))
        elif isinstance(raw, dict):
            document = raw
        else:
            raise CoopsRefused(
                "unsupported-input",
                "a response is handed over as its octets, its parsed JSON document or its CSV "
                "twin; text and other types are not taken",
            )
        if "form" in document:
            return self._from_csv(_check_csv_twin(document))
        return self._from_json(_check_json(document))

    # -- the two forms ---------------------------------------------------------------------------

    def _from_csv(self, twin: dict) -> list[CDMBase]:
        product = self._request.product
        header = twin["header"]
        if header != HEADERS[product]:
            other = [name for name, line in HEADERS.items() if line == header]
            if other:
                raise CoopsRefused(
                    "header-of-another-product",
                    "the CSV header is another product's than the request's",
                )
            raise CoopsRefused(
                "unknown-header", "the CSV header is not the request's product's header"
            )
        width = header.count(",") + 1
        samples = []
        for index, row in enumerate(twin["rows"]):
            if len(row) != width:
                raise CoopsRefused(
                    "width-mismatch", f"row {index} has another number of fields than the header"
                )
            for position, field in enumerate(row):
                if not field.strip():
                    raise CoopsRefused("blank-value", f"row {index}, field {position} is blank")
            stamp = self._stamp(row[0], f"row {index}")
            readings, flags = self._csv_sample(product, row, index)
            samples.append((index, stamp, readings, flags, {"row": list(row)}))
        if not samples:
            raise CoopsRefused("no-data-row", "the response holds no sample")
        residual_base = {"form": "csv", "header": header}
        return self._objects(samples, residual_base, header_lines=1, stated=None)

    def _from_json(self, document: dict) -> list[CDMBase]:
        if self._request.product != "water_level":
            raise CoopsRefused(
                "json-form-not-read",
                "the JSON form is read for water_level only; the record keys of the other "
                "products are not in the design record",
            )
        metadata = document["metadata"]
        if metadata["id"] != self._request.station:
            raise CoopsRefused("station-disagrees", "metadata.id is not the request's station")
        lat = self._coordinate(metadata["lat"], "metadata.lat", 90.0)
        lon = self._coordinate(metadata["lon"], "metadata.lon", 180.0)
        samples = []
        for index, record in enumerate(document["data"]):
            where = f"data[{index}]"
            stamp = self._stamp(record["t"], where)
            quality = record["q"]
            if quality not in WATER_LEVEL_FLAGS:
                raise CoopsRefused("bad-quality", f"{where}.q is not p or v")
            if _JSON_FLAGS.fullmatch(record["f"]) is None:
                raise CoopsRefused("bad-flag", f"{where}.f is not four comma-separated integers")
            value = self._number(record["v"], f"{where}.v")
            sigma = self._number(record["s"], f"{where}.s")
            readings = self._water_level(value, sigma)
            flags = self._water_level_flags(record["f"].split(","), quality, f"{where}.f")
            samples.append((index, stamp, readings, flags, {"record": dict(record)}))
        if not samples:
            raise CoopsRefused("no-data-row", "the response holds no sample")
        return self._objects(
            samples, {"form": "json"}, header_lines=0, stated=(lat, lon, dict(metadata))
        )

    # -- the pieces ------------------------------------------------------------------------------

    def _stamp(self, text: str, where: str) -> _dt.datetime:
        match = _STAMP.fullmatch(text)
        if match is None:
            raise CoopsRefused("bad-time", f"{where}: the stamp is not YYYY-MM-DD HH:MM")
        year, month, day, hour, minute = (int(g) for g in match.groups())
        try:
            local = _dt.datetime(year, month, day, hour, minute, tzinfo=_dt.timezone.utc)
        except ValueError:
            raise CoopsRefused("bad-time", f"{where}: the stamp names no instant") from None
        if self._request.time_zone == "gmt":
            return local
        try:
            return local - self._request.offset
        except OverflowError:
            raise CoopsRefused(
                "bad-time", f"{where}: the stamp leaves the years 1 to 9999"
            ) from None

    @staticmethod
    def _number(text: str, where: str) -> float:
        if _NUMBER.fullmatch(text) is None:
            raise CoopsRefused("not-a-number", f"{where} is not a decimal number")
        value = decimal_float(text)
        if value is None:
            raise CoopsRefused(
                "number-out-of-range", f"{where} lies outside what a binary double holds"
            )
        return value

    @staticmethod
    def _flag(text: str, where: str) -> int:
        if _FLAG.fullmatch(text) is None:
            raise CoopsRefused("bad-flag", f"{where} is not a non-negative integer")
        value = decimal_integer(text)
        if value is None:
            raise CoopsRefused("flag-out-of-range", f"{where} is an integer no binary double holds")
        return value

    @staticmethod
    def _coordinate(text: str, where: str, bound: float) -> float:
        value = decimal_float(text) if _NUMBER.fullmatch(text) is not None else None
        if value is None or not -bound <= value <= bound:
            raise CoopsRefused(
                "bad-position", f"{where} is not decimal degrees within +/-{bound:g}"
            )
        return value

    def _measurement(self, value: float) -> Measurement:
        return Measurement(value=value, unit=self._request.units, unit_namespace=UNITS_NAMESPACE)

    def _water_level(self, value: float, sigma: float) -> list[Reading]:
        namespace = "CO-OPS datagetter water_level"
        return [
            Reading(
                name="Water Level",
                namespace=namespace,
                measurement=self._measurement(value),
                datum=Datum(name=self._request.datum, namespace=DATUM_NAMESPACE),
            ),
            Reading(name="Sigma", namespace=namespace, measurement=self._measurement(sigma)),
        ]

    @staticmethod
    def _water_level_flags(texts: list[str], quality: str, where: str) -> list[QualityFlag]:
        flags = [
            QualityFlag(
                name=name,
                value=CoopsCsvAdapter._flag(text, f"{where}, flag {name}"),
                namespace=FLAG_NAMESPACE,
                applies_to="Water Level",
            )
            for name, text in zip(WATER_LEVEL_FLAGS[quality], texts)
        ]
        flags.append(
            QualityFlag(
                name="Quality", value=quality, namespace=QUALITY_NAMESPACE, applies_to="record"
            )
        )
        return flags

    def _csv_sample(self, product: str, row: list[str], index: int):
        where = f"row {index}"
        if product == "water_level":
            quality = row[7]
            if quality not in WATER_LEVEL_FLAGS:
                raise CoopsRefused("bad-quality", f"{where}: the Quality field is not p or v")
            readings = self._water_level(
                self._number(row[1], f"{where}, Water Level"),
                self._number(row[2], f"{where}, Sigma"),
            )
            return readings, self._water_level_flags(row[3:7], quality, where)
        if product == "air_pressure":
            readings = [
                Reading(
                    name="Pressure",
                    namespace="CO-OPS datagetter air_pressure",
                    measurement=self._measurement(self._number(row[1], f"{where}, Pressure")),
                )
            ]
            names = ("X", "N", "R")
            flags = [
                QualityFlag(
                    name=name,
                    value=self._flag(text, f"{where}, flag {name}"),
                    namespace=FLAG_NAMESPACE,
                    applies_to="Pressure",
                )
                for name, text in zip(names, row[2:5])
            ]
            return readings, flags
        namespace = "CO-OPS datagetter wind"
        readings = [
            Reading(
                name="Speed",
                namespace=namespace,
                measurement=self._measurement(self._number(row[1], f"{where}, Speed")),
            ),
            Reading(
                name="Direction",
                namespace=namespace,
                measurement=Measurement(
                    value=self._number(row[2], f"{where}, Direction"),
                    unit="degrees",
                    unit_namespace=DIRECTION_NAMESPACE,
                ),
            ),
            Reading(
                name="Gust",
                namespace=namespace,
                measurement=self._measurement(self._number(row[4], f"{where}, Gust")),
            ),
        ]
        flags = [
            QualityFlag(
                name=name,
                value=self._flag(text, f"{where}, flag {name}"),
                namespace=FLAG_NAMESPACE,
                applies_to="record",
            )
            for name, text in zip(("X", "R"), row[5:7])
        ]
        return readings, flags

    def _time_system(self) -> TimeSystem:
        request = self._request
        if request.time_zone == "gmt":
            basis = (
                "CoopsRequest.time_zone gmt, the request parameter the response does not echo "
                "(research-station-text F05): each stamp is read as UTC"
            )
        else:
            basis = (
                f"CoopsRequest.time_zone lst with the caller's lst_offset {request.lst_offset}, "
                "the request parameter the response does not echo (research-station-text F05): "
                "each stamp is local standard time"
            )
        return TimeSystem(name=request.time_zone, stated_by="caller", basis=basis)

    def _objects(self, samples, residual_base, *, header_lines, stated) -> list[CDMBase]:
        request = self._request
        stamp_base = self.source_ref().model_copy(update={"source_hash": self._source_hash})
        seen: dict[_dt.datetime, int] = {}
        for index, stamp, _, _, _ in samples:
            if stamp in seen:
                raise CoopsRefused(
                    "repeated-instant", f"sample {index} states the instant of sample {seen[stamp]}"
                )
            seen[stamp] = index
        earliest = min(stamp for _, stamp, _, _, _ in samples)
        zone = T_GMT if request.time_zone == "gmt" else T_LST
        site = {
            "source": stamp_base.model_copy(
                update={"observed_at": earliest, "transformations": [zone]}
            ),
            "system": SYSTEM,
            "station_id": request.station,
            "site_class": "tide_gauge",
            "valid_from": earliest,
            "station_table": self._station_table,
        }
        if stated is not None:
            lat, lon, metadata = stated
            site["stated_position"] = (lat, lon)
            site["stated_position_basis"] = (
                "the JSON response's metadata lat and lon, decimal-degree strings read as numbers"
            )
        entity = site_entity(**site)
        attributes = {
            **entity.attributes,
            "valid_from_basis": "the earliest sample the response states",
        }
        update: dict[str, Any] = {"attributes": attributes}
        # The station's own residual: the JSON form's metadata, or the CSV form's header line,
        # what the response states about itself rather than a sample.
        update["residual"] = Residual(
            namespace=FORMAT_NAME,
            data={"metadata": stated[2]}
            if stated is not None
            else {"header": residual_base["header"]},
        )
        entity = entity.model_copy(update=update)
        position = entity.position
        geometry = None if position is None else Point(coordinates=[position.lon, position.lat])
        time_system = self._time_system()
        # Every request parameter that changes a sample's value is in its identity, so a store
        # keyed by event_id never overwrites one reading with another: the datum ("-" for a
        # product that states none), the units and the interval (absent is the API's 6-minute
        # default, research-station-text F15). The zone is not: the instant is UTC, so one sample
        # requested in two zones is one Event.
        identity = "/".join(
            (
                request.station,
                request.product,
                request.datum or "-",
                request.units,
                request.interval or "6",
            )
        )
        events = []
        for index, stamp, readings, flags, own in samples:
            contract = PointObservation(
                contract="point-observation/1",
                product_class="observation",
                time=TimeInputs(source_time_system=time_system),
                locator=TableLocator(
                    kind="table",
                    row=index,
                    header_lines=header_lines,
                    frame_sha256=self._frame_sha256,
                ),
                quality_flags=flags,
                station_id=request.station,
                station_namespace="CO-OPS station identifier",
                readings=readings,
            )
            events.append(
                observation_event(
                    source=stamp_base.model_copy(
                        update={
                            "observed_at": stamp,
                            "record_index": index,
                            "transformations": [zone, T_NUMBER, T_FLAGS],
                        }
                    ),
                    source_ids=[
                        SourceId(system=SYSTEM, external_id=f"{identity}/{times.render(stamp)}")
                    ],
                    observation=contract,
                    observed_at=stamp,
                    received_at=self.now(),
                    validity=TemporalValidity(effective=Period(start=stamp, end=stamp)),
                    related_entities=[entity.entity_id],
                    geometry=geometry,
                    residual=Residual(
                        namespace=FORMAT_NAME,
                        data={**residual_base, **own, "request": request.as_dict()},
                    ),
                )
            )
        return [*events, entity]
